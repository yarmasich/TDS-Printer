<script setup lang="ts">
import { computed } from "vue";
import type { PingResult } from "@/api/types";
import { pillFor, type PillTone } from "@/data/printerPill";

const props = defineProps<{
  /** null = checking, undefined = no info yet */
  ping?: PingResult | null;
}>();

const TONES: Record<PillTone, string> = {
  muted: "bg-edge text-ink-3",
  checking: "bg-accent-soft-hover text-accent-ink",
  ok: "bg-ok-soft text-ok",
  warn: "bg-warn-soft text-warn",
  danger: "bg-danger-soft text-danger",
};

const pill = computed(() => pillFor(props.ping));
</script>

<template>
  <span
    class="inline-block rounded-full px-2 py-0.5 text-[11px] font-bold"
    :class="[TONES[pill.tone], { 'cursor-help': pill.title }]"
    :title="pill.title"
    role="status"
  >
    {{ pill.label }}
  </span>
</template>
