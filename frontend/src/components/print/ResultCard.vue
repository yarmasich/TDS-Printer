<script setup lang="ts">
import type { SearchHit } from "@/api/types";
import Button from "primevue/button";

defineProps<{ hit: SearchHit }>();

defineEmits<{
  print: [labelId: number];
  cart: [labelId: number];
}>();
</script>

<template>
  <div class="bg-white border border-slate-200 rounded-2xl p-4 shadow-sm">
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
          class="flex-1 min-h-[90px] flex items-center justify-center text-center text-sm leading-snug px-3 py-3 rounded-lg border whitespace-pre-wrap break-words"
          :class="
            hit.matched_left
              ? 'bg-sky-50 border-sky-500 shadow-[inset_0_0_0_1px_#0284c7]'
              : 'bg-slate-50 border-slate-300'
          "
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
          class="flex-1 min-h-[90px] flex items-center justify-center text-center text-sm leading-snug px-3 py-3 rounded-lg border whitespace-pre-wrap break-words"
          :class="
            hit.matched_right
              ? 'bg-sky-50 border-sky-500 shadow-[inset_0_0_0_1px_#0284c7]'
              : 'bg-slate-50 border-slate-300'
          "
        >
          {{ hit.right_text || "—" }}
        </div>
      </div>

      <!-- Actions -->
      <div class="flex flex-col gap-2 justify-center">
        <Button
          label="+ Cart"
          severity="secondary"
          size="small"
          @click="$emit('cart', hit.label_id)"
        />
        <Button
          label="Print"
          size="small"
          @click="$emit('print', hit.label_id)"
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
