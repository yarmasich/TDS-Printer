<script setup lang="ts">
import { ref } from "vue";
import type { CartItem } from "@/api/types";
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
const toast = useToast();
const confirm = useConfirm();
const drawerOpen = ref(false);
const printing = ref(false);

async function printAll() {
  if (!cart.queuedCount || cart.hasPrinting) return;
  printing.value = true;
  try {
    const res = await cart.printAll(props.operator, props.reason);
    if (res.errors.length === 0) {
      toast.add({
        severity: "success",
        summary: `Printed ${res.ok} labels`,
        life: 3000,
      });
      drawerOpen.value = false;
      emit("printed", res.ok);
    } else {
      toast.add({
        severity: "warn",
        summary: `Printed ${res.ok}, ${res.errors.length} failed`,
        detail: res.errors.map((e) => e.error).join("; "),
        life: 6000,
      });
      // Still emit on partial success — the printed items left the cart
      // and the operator typically wants to start a fresh search.
      if (res.ok > 0) emit("printed", res.ok);
    }
  } catch (e: unknown) {
    toast.add({
      severity: "error",
      summary: "Print all failed",
      detail: e instanceof Error ? e.message : String(e),
    });
  } finally {
    printing.value = false;
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
            :disabled="cart.hasPrinting"
            severity="secondary"
            :size="props.kiosk ? 'large' : 'small'"
            :fluid="props.kiosk"
            @click="clearCart"
          />
          <Button
             :label="`Print queued (${cart.queuedCount})`"
            :disabled="!cart.queuedCount || cart.hasPrinting"
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
  >
    <Button label="Refresh cart" icon="pi pi-refresh" severity="secondary" size="small" :loading="cart.loading" @click="refreshCart" />
    <p v-if="cart.error" role="alert" class="text-red-700 mt-2">{{ cart.error }}</p>
    <p class="text-sm text-slate-600 my-3">Only queued labels are sent. Check uncertain labels at the printer before removing or adding them again.</p>
    <p v-if="!cart.count" class="text-slate-500">Cart is empty.</p>
    <ul v-else class="space-y-2">
      <li
        v-for="item in cart.items"
        :key="item.id"
        class="bg-slate-50 border border-slate-200 rounded-xl p-3"
      >
        <div class="flex items-start justify-between gap-2">
          <div class="flex-1 min-w-0">
            <p class="text-sm font-semibold capitalize">{{ item.status }}</p>
            <p v-if="item.status === 'printing'" class="text-sm text-sky-800">Sending to printer. Wait, then refresh. This label cannot be removed or resent while active.</p>
            <p v-if="item.status === 'uncertain'" class="text-sm text-amber-800">May have printed. Check the printer before removing this record or adding the label again.</p>
            <p v-if="item.error" class="text-sm text-red-700">{{ item.error }}</p>
            <div class="text-sm font-medium truncate">
              <b>L:</b> {{ (item.left_text || "—").split("\n")[0] }}
            </div>
            <div class="text-xs text-slate-500 truncate">
              <b>R:</b> {{ (item.right_text || "—").split("\n")[0] }}
            </div>
            <div class="text-[11px] text-slate-400 mt-1">
              {{ item.project_name }} · {{ item.discipline_name }}
              <span v-if="item.template_name">· {{ item.template_name }}</span>
              <span v-else class="text-red-600">· no template</span>
            </div>
          </div>
          <Button
            icon="pi pi-times"
            severity="secondary"
            size="small"
            text
            rounded
            aria-label="Remove"
            :disabled="cart.printing || item.status === 'printing'"
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
          :disabled="!cart.count || cart.hasPrinting"
          @click="clearCart"
        />
        <Button
           :label="`Print queued (${cart.queuedCount})`"
            :disabled="!cart.queuedCount || cart.hasPrinting"
          icon="pi pi-print"
          :loading="printing"
          @click="printAll"
        />
      </div>
    </template>
  </Drawer>
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
    rgba(248, 250, 252, 0.9) 0%,
    rgba(248, 250, 252, 0.7) 70%,
    rgba(248, 250, 252, 0) 100%
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
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 999px;
  padding: 8px 12px 8px 18px;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.12);
}
.cart-summary {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: transparent;
  border: 0;
  cursor: pointer;
  font-size: 14px;
  color: #0f172a;
  padding: 4px 6px;
  border-radius: 8px;
}
.cart-summary:hover {
  background: #f1f5f9;
}
.cart-summary-count {
  display: inline-block;
  background: #0284c7;
  color: white;
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
