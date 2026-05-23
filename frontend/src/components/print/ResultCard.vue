<script setup lang="ts">
import type { SearchHit } from "@/api/types";
import Button from "primevue/button";

defineProps<{ hit: SearchHit; kiosk?: boolean }>();

defineEmits<{
  cart: [labelId: number];
}>();
</script>

<template>
  <div
    class="bg-white border border-slate-200 rounded-2xl shadow-sm"
    :class="kiosk ? 'p-5 result-card--kiosk' : 'p-4'"
  >
    <div class="flex gap-3 items-stretch">
      <!-- LEFT cell -->
      <div class="flex-1 min-w-0 flex flex-col gap-1.5">
        <div
          class="text-[11px] font-extrabold tracking-wider uppercase"
          :class="hit.matched_left ? 'text-sky-600' : 'text-slate-400'"
        >
          Left{{ hit.matched_left ? " ✓" : "" }}
        </div>
        <div
          class="flex-1 flex items-center justify-center text-center leading-snug px-3 py-3 rounded-lg border whitespace-pre-wrap break-words"
          :class="[
            kiosk ? 'min-h-[110px] text-base' : 'min-h-[90px] text-sm',
            hit.matched_left
              ? 'bg-sky-50 border-sky-500 shadow-[inset_0_0_0_1px_#0284c7]'
              : 'bg-slate-50 border-slate-300',
          ]"
        >
          {{ hit.left_text || "—" }}
        </div>
      </div>

      <!-- RIGHT cell -->
      <div class="flex-1 min-w-0 flex flex-col gap-1.5">
        <div
          class="text-[11px] font-extrabold tracking-wider uppercase"
          :class="hit.matched_right ? 'text-sky-600' : 'text-slate-400'"
        >
          Right{{ hit.matched_right ? " ✓" : "" }}
        </div>
        <div
          class="flex-1 flex items-center justify-center text-center leading-snug px-3 py-3 rounded-lg border whitespace-pre-wrap break-words"
          :class="[
            kiosk ? 'min-h-[110px] text-base' : 'min-h-[90px] text-sm',
            hit.matched_right
              ? 'bg-sky-50 border-sky-500 shadow-[inset_0_0_0_1px_#0284c7]'
              : 'bg-slate-50 border-slate-300',
          ]"
        >
          {{ hit.right_text || "—" }}
        </div>
      </div>

      <!-- Actions — all printing flows through the cart, so a single
           "Add" button is enough. Use Print all in the sticky cart to
           actually send labels to the printer. -->
      <div class="flex flex-col gap-2 justify-center">
        <Button
          label="+ Add"
          icon="pi pi-plus"
          :size="kiosk ? 'large' : 'small'"
          :fluid="kiosk"
          class="result-add-btn"
          @click="$emit('cart', hit.label_id)"
        />
      </div>
    </div>

    <div class="text-xs text-slate-500 mt-2">
      {{ hit.project_name }} / {{ hit.data_hall_name }} /
      {{ hit.discipline_name }}
      <span class="opacity-60">· {{ hit.sheet_name }}:{{ hit.row_idx }}</span>
    </div>
  </div>
</template>

<style scoped>
.result-card--kiosk :deep(.result-add-btn) {
  min-width: 88px;
  min-height: 56px;
}
</style>
