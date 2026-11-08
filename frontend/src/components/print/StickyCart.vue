<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useRfidPrint } from "@/composables/useRfidPrint";
import Dialog from "primevue/dialog";
import type { CartItem } from "@/api/types";
import { eligiblePrinters, useStationAuth } from "@/stores/stationAuth";
import { useCart } from "@/stores/cart";
import Button from "primevue/button";
import Drawer from "primevue/drawer";
import { useToast } from "primevue/usetoast";
import { useConfirm } from "primevue/useconfirm";

const props = defineProps<{
  operator: string;
  reason: string;
  kiosk?: boolean;
}>();

const emit = defineEmits<{
  /** Fired after every successful print_all so the host page can reset
   * its workflow (clear search, re-focus the query box, etc). */
  printed: [count: number];
}>();

const cart = useCart(props.kiosk ? "kiosk" : "print");
const stationAuth = useStationAuth();
const toast = useToast();
const confirm = useConfirm();
const drawerOpen = ref(false);
const choosingPrinter = ref(false);
const preparing = ref(false);
const printerChoices = ref<Record<number, number>>({});
const templatesToChoose = computed(() => {
  const station = stationAuth.station;
  if (!station) return [];
  const templates = new Map<number, { id: number; name: string; printers: { id: number; name: string }[] }>();
  for (const item of cart.items) {
    if (item.status !== "queued" || !item.template_id || templates.has(item.template_id)) continue;
    const eligible = eligiblePrinters(station, item.printer_ids ?? []);
    if (eligible.length > 1 && !eligible.some(printer => printer.id === station.default_printer_id)) {
      templates.set(item.template_id, { id: item.template_id, name: item.template_name ?? "Template", printers: eligible });
    }
  }
  return [...templates.values()];
});
const choicesComplete = computed(() => templatesToChoose.value.every(template =>
  template.printers.some(printer => printer.id === printerChoices.value[template.id]),
));
const scanInput = ref<HTMLInputElement | null>(null);
const {
  open: scanOpen, code: scanCode, error: printError, checking,
  submitting, ready: scanReady, busy: printing, start, submit, close: closeScan,
} = useRfidPrint(async () => {
  await stationAuth.restore();
  if (stationAuth.error || (stationAuth.required && !stationAuth.station)) throw new Error(stationAuth.error || "Sign in to this station before printing.");
  return cart.printPolicy();
}, executePrint);

async function focusScan() {
  await nextTick();
  scanInput.value?.focus();
}
watch(submitting, (active) => { if (!active && scanOpen.value) void focusScan(); });

async function printAll() {
  if (!cart.queuedCount || cart.hasPrinting || printing.value || preparing.value || choosingPrinter.value) return;
  preparing.value = true;
  try {
    await stationAuth.restore();
    if (stationAuth.error || (stationAuth.required && !stationAuth.station)) throw new Error(stationAuth.error || "Sign in to this station before printing.");
    await cart.fetch();
    printerChoices.value = {};
    if (templatesToChoose.value.length) choosingPrinter.value = true;
    else await startPrinting();
  } catch (error) {
    reportError(error);
  } finally {
    preparing.value = false;
  }
}

async function startPrinting() {
  choosingPrinter.value = false;
  await start();
  if (printError.value && !scanOpen.value) {
    toast.add({ severity: "error", summary: "Cannot print", detail: printError.value });
  }
}

async function executePrint(rfidCode?: string) {
  try {
    const res = await cart.printAll(props.operator, props.reason, rfidCode, printerChoices.value);
    const destinations = res.printers?.map(printer =>
      `${printer.printer_name}: ${printer.sent} sent${printer.failed ? `, ${printer.failed} failed` : ""}`,
    ).join("; ");
    if (res.errors.length === 0) {
      toast.add({
        severity: "success",
        summary: `Sent ${res.ok} labels`,
        detail: destinations,
        life: 3000,
      });
      drawerOpen.value = false;
      emit("printed", res.ok);
    } else {
      toast.add({
        severity: "warn",
        summary: `Sent ${res.ok}, ${res.errors.length} failed`,
        detail: [destinations, ...res.errors.map((e) => e.error)].filter(Boolean).join("; "),
        life: 6000,
      });
      // Still emit on partial success — the printed items left the cart
      // and the operator typically wants to start a fresh search.
      if (res.ok > 0) emit("printed", res.ok);
    }
  } catch (e: unknown) {
    // The scan dialog or the initiating Print button reports the error.
    throw e;
  }
}

function reportError(error: unknown) {
  toast.add({ severity: "error", summary: "Cart action failed", detail: error instanceof Error ? error.message : String(error) });
}
async function refreshCart() { try { await cart.fetch(); } catch (error) { reportError(error); } }
function removeItem(item: CartItem) {
  const remove = async () => { try { await cart.remove(item.id); } catch (error) { reportError(error); } };
  if (item.status === "uncertain") confirm.require({ header: "Remove uncertain label?", message: "This label may have printed. Check the printer before removing this record or adding it again.", acceptLabel: "Remove record", rejectLabel: "Keep", accept: remove });
  else void remove();
}
function clearCart() {
  confirm.require({
    header: "Clear cart",
    message: cart.items.some(i => i.status === "uncertain") ? "Some labels may have printed. Check the printer before removing their records. Remove all labels from the cart?" : "Remove all labels from the cart?",
    rejectLabel: "Cancel",
    acceptLabel: "Clear",
    accept: async () => {
      try { await cart.clear(); drawerOpen.value = false; }
      catch (error) { reportError(error); }
    },
  });
}
</script>

<template>
  <Dialog v-model:visible="choosingPrinter" modal header="Choose printers" :style="{ width: '28rem', maxWidth: '95vw' }">
    <div class="space-y-3">
      <div v-for="template in templatesToChoose" :key="template.id" class="flex flex-col gap-1">
        <label :for="`cart-${kiosk ? 'kiosk' : 'print'}-printer-${template.id}`">{{ template.name }}</label>
        <select :id="`cart-${kiosk ? 'kiosk' : 'print'}-printer-${template.id}`" v-model="printerChoices[template.id]"
          class="border border-edge rounded-lg bg-surface p-2">
          <option :value="undefined" disabled>Select printer</option>
          <option v-for="printer in template.printers" :key="printer.id" :value="printer.id">{{ printer.name }}</option>
        </select>
      </div>
    </div>
    <template #footer>
      <Button label="Cancel" severity="secondary" @click="choosingPrinter = false" />
      <Button label="Continue" :disabled="!choicesComplete" @click="startPrinting" />
    </template>
  </Dialog>
  <!-- Floating sticky bar that appears when cart has items -->
  <Transition name="slide-up">
    <div
      v-if="cart.count > 0"
      class="sticky-cart"
      :class="{ 'sticky-cart--kiosk': props.kiosk }"
    >
      <div
        class="sticky-cart-inner"
        :class="{ 'sticky-cart-inner--kiosk': props.kiosk }"
      >
        <button class="cart-summary" @click="drawerOpen = true">
          <i class="pi pi-shopping-cart text-lg"></i>
          <span class="cart-summary-count">{{ cart.count }}</span>
          <span class="hidden sm:inline">in cart</span>
        </button>
        <div class="flex gap-2">
          <Button
            label="Clear"
            :disabled="cart.hasPrinting || printing || scanOpen"
            severity="secondary"
            :size="props.kiosk ? 'large' : 'small'"
            :fluid="props.kiosk"
            @click="clearCart"
          />
          <Button
             :label="checking ? 'Checking print requirements…' : `Print queued (${cart.queuedCount})`"
            :disabled="!cart.queuedCount || cart.hasPrinting || printing || scanOpen"
            icon="pi pi-print"
            :size="props.kiosk ? 'large' : undefined"
            :fluid="props.kiosk"
            class="print-all-btn"
            :loading="printing"
            @click="printAll"
          />
        </div>
      </div>
    </div>
  </Transition>

  <!-- Drawer with full cart list -->
  <Drawer
    v-model:visible="drawerOpen"
    position="right"
    :style="{ width: '32rem', maxWidth: '95vw' }"
    header="Cart"
    class="print-cart-drawer"
  >
    <Button label="Refresh cart" icon="pi pi-refresh" severity="secondary" size="small" :loading="cart.loading" @click="refreshCart" />
    <p v-if="cart.error" role="alert" class="text-danger mt-2">{{ cart.error }}</p>
    <p class="text-sm text-ink-2 my-3">Only queued labels are sent. Check uncertain labels at the printer before removing or adding them again.</p>
    <p v-if="!cart.count" class="text-ink-3">Cart is empty.</p>
    <ul v-else class="space-y-2">
      <li
        v-for="item in cart.items"
        :key="item.id"
        class="bg-sunken border border-edge rounded-xl p-3"
      >
        <div class="flex items-start justify-between gap-2">
          <div class="flex-1 min-w-0">
            <p class="text-sm font-semibold capitalize">{{ item.status }}</p>
            <p v-if="item.status === 'printing'" class="text-sm text-accent-ink">Sending to printer. Wait, then refresh. This label cannot be removed or resent while active.</p>
            <p v-if="item.status === 'uncertain'" class="text-sm text-warn">May have printed. Check the printer before removing this record or adding the label again.</p>
            <p v-if="item.error" class="text-sm text-danger">{{ item.error }}</p>
            <div class="text-sm font-medium truncate">
              <b>L:</b> {{ (item.left_text || "—").split("\n")[0] }}
            </div>
            <div class="text-xs text-ink-3 truncate">
              <b>R:</b> {{ (item.right_text || "—").split("\n")[0] }}
            </div>
            <details class="cart-label-details mt-2">
              <summary class="flex items-center min-h-12 cursor-pointer text-sm font-semibold text-accent-ink">Full label text</summary>
              <dl class="text-sm space-y-2 pb-2">
                <div><dt class="font-semibold">Left</dt><dd class="whitespace-pre-wrap break-words">{{ item.left_text || "—" }}</dd></div>
                <div><dt class="font-semibold">Right</dt><dd class="whitespace-pre-wrap break-words">{{ item.right_text || "—" }}</dd></div>
              </dl>
            </details>
            <div class="text-[11px] text-ink-4 mt-1">
              {{ item.project_name }} · {{ item.discipline_name }}
              <span v-if="item.template_name">· {{ item.template_name }}</span>
              <span v-else class="text-danger">· no template</span>
            </div>
          </div>
          <Button
            icon="pi pi-times"
            severity="secondary"
            size="small"
            text
            rounded
            aria-label="Remove"
            :disabled="printing || scanOpen || cart.printing || item.status === 'printing'"
            @click="removeItem(item)"
          />
        </div>
      </li>
    </ul>
    <template #footer>
      <div class="flex gap-2 justify-between w-full">
        <Button
          label="Clear cart"
          severity="secondary"
          size="small"
          :disabled="!cart.count || cart.hasPrinting || printing || scanOpen"
          @click="clearCart"
        />
        <Button
           :label="checking ? 'Checking print requirements…' : `Print queued (${cart.queuedCount})`"
            :disabled="!cart.queuedCount || cart.hasPrinting || printing || scanOpen"
          icon="pi pi-print"
          :loading="printing"
          @click="printAll"
        />
      </div>
    </template>
  </Drawer>

  <Dialog
    :visible="scanOpen"
    modal
    header="Scan your RFID badge"
    :style="{ width: '30rem', maxWidth: '95vw' }"
    :closable="!printing"
    :close-on-escape="!printing"
    class="rfid-print-dialog"
    @update:visible="(visible) => { if (!visible) closeScan(); }"
    @show="focusScan"
  >
    <p class="mb-4 text-ink-2">Scan your badge with the reader to identify yourself and print this batch.</p>
    <form v-if="scanReady" @submit.prevent="submit">
      <label for="rfid-scan" class="block font-semibold mb-2">RFID badge</label>
      <input
        id="rfid-scan"
        ref="scanInput"
        v-model="scanCode"
        type="text"
        autocomplete="off"
        autocapitalize="off"
        autocorrect="off"
        :spellcheck="false"
        :disabled="printing"
        class="w-full rounded-lg border border-edge-strong px-4 py-3 text-lg"
        placeholder="Waiting for badge…"
      />
      <p v-if="submitting" role="status" class="mt-3 text-accent-ink">Checking badge and printing… Please wait.</p>
      <Button
        type="submit"
        label="Verify badge and print"
        icon="pi pi-print"
        size="large"
        class="w-full mt-4"
        :loading="submitting"
        :disabled="printing || !scanCode.trim()"
      />
    </form>
    <p v-if="printError" role="alert" class="mt-3 text-danger">{{ printError }}</p>
    <template #footer>
      <Button label="Cancel" severity="secondary" size="large" :disabled="printing" @click="closeScan" />
    </template>
  </Dialog>
</template>

<style scoped>
.sticky-cart {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 40;
  padding: 12px 16px calc(12px + env(safe-area-inset-bottom));
  background: linear-gradient(
    to top,
    color-mix(in srgb, var(--tds-sunken) 90%, transparent) 0%,
    color-mix(in srgb, var(--tds-sunken) 70%, transparent) 70%,
    color-mix(in srgb, var(--tds-sunken) 0%, transparent) 100%
  );
  pointer-events: none;
}
.sticky-cart-inner {
  pointer-events: auto;
  max-width: 56rem;
  margin: 0 auto;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  background: var(--tds-surface);
  border: 1px solid var(--tds-edge);
  border-radius: 999px;
  padding: 8px 12px 8px 18px;
  box-shadow: 0 8px 24px var(--tds-shadow-strong);
}
.cart-summary {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: transparent;
  border: 0;
  cursor: pointer;
  font-size: 14px;
  color: var(--tds-ink);
  padding: 4px 6px;
  border-radius: 8px;
}
.cart-summary:hover {
  background: var(--tds-muted);
}
.cart-label-details summary::before { content: '›'; margin-right: 8px; font-size: 20px; }
.cart-label-details[open] summary::before { transform: rotate(90deg); }
.cart-label-details summary:focus-visible { outline: 2px solid var(--tds-accent); outline-offset: 2px; }
.cart-label-details dd { overflow-wrap: anywhere; }
.cart-summary-count {
  display: inline-block;
  background: var(--tds-accent-solid);
  color: var(--tds-accent-solid-ink);
  font-weight: 700;
  border-radius: 999px;
  padding: 1px 8px;
  font-size: 12px;
  min-width: 22px;
  text-align: center;
}

.slide-up-enter-active,
.slide-up-leave-active {
  transition: transform 0.25s ease-out, opacity 0.25s ease-out;
}
.slide-up-enter-from,
.slide-up-leave-to {
  transform: translateY(100%);
  opacity: 0;
}

.sticky-cart--kiosk {
  padding: 16px 12px calc(16px + env(safe-area-inset-bottom));
}

.sticky-cart-inner--kiosk {
  max-width: none;
  border-radius: 20px;
  padding: 12px 16px 12px 22px;
}

.sticky-cart-inner--kiosk .cart-summary {
  font-size: 18px;
  padding: 8px 10px;
}

.sticky-cart-inner--kiosk .cart-summary-count {
  font-size: 15px;
  min-width: 28px;
  padding: 3px 10px;
}

.sticky-cart-inner--kiosk :deep(.print-all-btn) {
  min-height: 52px;
  min-width: 140px;
  font-size: 17px;
  font-weight: 700;
}
</style>

<style>
@media (max-width: 1100px), (pointer: coarse) {
  .sticky-cart .p-button, .sticky-cart .cart-summary,
  .print-cart-drawer .p-button, .print-cart-drawer .p-drawer-close-button { min-height: 48px; min-width: 48px; touch-action: manipulation; }
}
@media (max-width: 600px) {
  .sticky-cart-inner { border-radius: 16px; flex-wrap: wrap; padding: 10px; }
  .sticky-cart-inner > div { flex: 1; justify-content: flex-end; }
}
</style>
