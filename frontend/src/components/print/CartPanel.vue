<script setup lang="ts">
import { useCart } from "@/stores/cart";
import Button from "primevue/button";
import { useToast } from "primevue/usetoast";
import { useConfirm } from "primevue/useconfirm";

const cart = useCart();
const toast = useToast();
const confirm = useConfirm();

defineProps<{
  operator: string;
  reason: string;
}>();

async function onClear() {
  confirm.require({
    message: "Clear the cart?",
    accept: async () => {
      await cart.clear();
      toast.add({
        severity: "success",
        summary: "Cart cleared",
        life: 2000,
      });
    },
  });
}

async function onPrintAll(operator: string, reason: string) {
  try {
    const res = await cart.printAll(operator, reason);
    if (res.errors.length === 0) {
      toast.add({
        severity: "success",
        summary: `Printed ${res.ok} labels`,
        life: 3000,
      });
    } else {
      toast.add({
        severity: "warn",
        summary: `Printed ${res.ok}, ${res.errors.length} failed`,
        detail: res.errors.map((e) => e.error).join("; "),
        life: 6000,
      });
    }
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    toast.add({ severity: "error", summary: "Print failed", detail: msg });
  }
}

defineExpose({ onPrintAll });
</script>

<template>
  <div
    v-if="cart.count > 0"
    class="bg-white border border-slate-200 rounded-2xl p-4 shadow-sm"
  >
    <div class="flex items-center justify-between mb-3">
      <h2 class="text-lg font-bold">
        Cart <span class="text-slate-400">({{ cart.count }})</span>
      </h2>
      <div class="flex gap-2">
        <Button
          label="Clear"
          severity="secondary"
          size="small"
          @click="onClear"
        />
        <Button
          label="Print all"
          icon="pi pi-print"
          size="small"
          @click="onPrintAll(operator, reason)"
        />
      </div>
    </div>

    <ul class="space-y-2">
      <li
        v-for="item in cart.items"
        :key="item.id"
        class="flex items-center justify-between gap-3 bg-slate-50 border border-slate-200 rounded-xl px-3 py-2"
      >
        <div class="flex-1 min-w-0">
          <div class="text-sm truncate">
            <b>L:</b> {{ (item.left_text || "—").split("\n")[0] }}
          </div>
          <div class="text-xs text-slate-500 truncate">
            <b>R:</b> {{ (item.right_text || "—").split("\n")[0] }}
          </div>
          <div class="text-[11px] text-slate-400">
            {{ item.project_name }} / {{ item.discipline_name }}
            <span v-if="item.template_name">· {{ item.template_name }}</span>
            <span v-else class="text-red-600">· no template</span>
          </div>
        </div>
        <Button
          icon="pi pi-times"
          severity="secondary"
          size="small"
          rounded
          text
          aria-label="Remove"
          @click="cart.remove(item.id)"
        />
      </li>
    </ul>
  </div>
</template>
