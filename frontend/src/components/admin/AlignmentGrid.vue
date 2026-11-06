<script setup lang="ts">
import { computed } from "vue";
import type { HAlign, VAlign } from "@/api/types";

const hAlign = defineModel<HAlign>("hAlign", { required: true });
const vAlign = defineModel<VAlign>("vAlign", { required: true });

const H_OPTS: { value: HAlign; short: string; label: string }[] = [
  { value: "LEFT", short: "L", label: "Left" },
  { value: "CENTER", short: "C", label: "Center" },
  { value: "RIGHT", short: "R", label: "Right" },
];

const V_OPTS: { value: VAlign; short: string; label: string }[] = [
  { value: "TOP", short: "T", label: "Top" },
  { value: "CENTER", short: "M", label: "Middle" },
  { value: "BOTTOM", short: "B", label: "Bottom" },
];

const H_LABEL: Record<HAlign, string> = {
  LEFT: "left",
  CENTER: "center",
  RIGHT: "right",
};

const V_LABEL: Record<VAlign, string> = {
  TOP: "top",
  CENTER: "middle",
  BOTTOM: "bottom",
};

const summary = computed(
  () =>
    `Text sits ${H_LABEL[hAlign.value]} horizontally, ${V_LABEL[vAlign.value]} vertically in the white strip.`,
);
</script>

<template>
  <div class="align-wrap">
    <p class="align-help">
      Where the caption sits inside each label’s white print area (preview and print use the same).
    </p>

    <div class="align-panel" role="group" aria-label="Text alignment">
      <div class="align-block">
        <span class="row-label">Horizontal ↔</span>
        <div class="align-row" role="group" aria-label="Horizontal alignment">
          <button
            v-for="opt in H_OPTS"
            :key="opt.value"
            type="button"
            class="align-btn"
            :class="{ 'align-btn--active': hAlign === opt.value }"
            :title="opt.label"
            :aria-label="`${opt.label} horizontally`"
            :aria-pressed="hAlign === opt.value"
            @click="hAlign = opt.value"
          >
            <span class="btn-short">{{ opt.short }}</span>
            <span class="btn-word">{{ opt.label }}</span>
          </button>
        </div>
      </div>

      <div class="align-block">
        <span class="row-label">Vertical ↕</span>
        <div class="align-row" role="group" aria-label="Vertical alignment">
          <button
            v-for="opt in V_OPTS"
            :key="opt.value"
            type="button"
            class="align-btn"
            :class="{ 'align-btn--active': vAlign === opt.value }"
            :title="opt.label"
            :aria-label="`${opt.label} vertically`"
            :aria-pressed="vAlign === opt.value"
            @click="vAlign = opt.value"
          >
            <span class="btn-short">{{ opt.short }}</span>
            <span class="btn-word">{{ opt.label }}</span>
          </button>
        </div>
      </div>
    </div>

    <p class="align-summary" aria-live="polite">{{ summary }}</p>
  </div>
</template>

<style scoped>
.align-wrap {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: 420px;
}

.align-help {
  margin: 0;
  font-size: 11px;
  line-height: 1.4;
  color: var(--tds-ink-3);
}

.align-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 10px 12px;
  background: var(--tds-sunken);
  border: 1px solid var(--tds-edge);
  border-radius: 8px;
}

.align-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.row-label {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--tds-ink-2);
}

.align-row {
  display: flex;
  gap: 6px;
}

.align-btn {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1px;
  min-width: 72px;
  padding: 8px 6px;
  border: 1px solid var(--tds-edge-strong);
  border-radius: 6px;
  background: var(--tds-surface);
  cursor: pointer;
  color: var(--tds-ink-2);
  transition: background 0.12s, border-color 0.12s, color 0.12s, box-shadow 0.12s;
}

.align-btn:hover:not(.align-btn--active) {
  border-color: var(--tds-ink-4);
  background: var(--tds-muted);
}

.align-btn--active {
  background: var(--tds-selected);
  border-color: var(--tds-selected-edge);
  color: var(--tds-selected-ink);
  box-shadow: 0 1px 3px color-mix(in srgb, var(--tds-selected) 35%, transparent);
}

.btn-short {
  font-size: 15px;
  font-weight: 800;
  line-height: 1;
}

.btn-word {
  font-size: 10px;
  font-weight: 600;
  line-height: 1.2;
  opacity: 0.85;
}

.align-summary {
  margin: 0;
  font-size: 12px;
  font-weight: 600;
  color: var(--tds-ok);
  line-height: 1.35;
}
</style>
