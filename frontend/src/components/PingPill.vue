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
    class="inline-block rounded-full px-2 py-0.5 text-[11px] font-bold bg-edge text-ink-3"
  >
    unknown
  </span>
  <span
    v-else-if="ping === null"
    class="inline-block rounded-full px-2 py-0.5 text-[11px] font-bold bg-accent-soft-hover text-accent-ink"
  >
    checking…
  </span>
  <span
    v-else-if="ping.ok"
    class="inline-block rounded-full px-2 py-0.5 text-[11px] font-bold bg-ok-soft text-ok"
  >
    online · {{ ping.ms }} ms
  </span>
  <span v-else-if="ping.error.toLowerCase().includes('busy')" class="inline-block rounded-full px-2 py-0.5 text-[11px] font-bold bg-warn-soft text-warn" :title="ping.error">busy</span>
  <span
    v-else
    :title="ping.error"
    class="inline-block rounded-full px-2 py-0.5 text-[11px] font-bold bg-danger-soft text-danger cursor-help"
  >
    offline
  </span>
</template>
