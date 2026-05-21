<script setup lang="ts">
import type { PingResult } from "@/api/types";

defineProps<{
  /** null = checking, undefined = no info yet */
  ping?: PingResult | null;
}>();
</script>

<template>
  <span
    v-if="ping === undefined"
    class="inline-block rounded-full px-2 py-0.5 text-[11px] font-bold bg-slate-200 text-slate-500"
  >
    unknown
  </span>
  <span
    v-else-if="ping === null"
    class="inline-block rounded-full px-2 py-0.5 text-[11px] font-bold bg-sky-100 text-sky-700"
  >
    checking…
  </span>
  <span
    v-else-if="ping.ok"
    class="inline-block rounded-full px-2 py-0.5 text-[11px] font-bold bg-emerald-100 text-emerald-800"
  >
    online · {{ ping.ms }} ms
  </span>
  <span
    v-else
    :title="ping.error"
    class="inline-block rounded-full px-2 py-0.5 text-[11px] font-bold bg-red-100 text-red-800 cursor-help"
  >
    offline
  </span>
</template>
