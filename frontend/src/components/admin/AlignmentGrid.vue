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
  color: #64748b;
}

.align-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 10px 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
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
  color: #475569;
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
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  background: #fff;
  cursor: pointer;
  color: #334155;
  transition: background 0.12s, border-color 0.12s, color 0.12s, box-shadow 0.12s;
}

.align-btn:hover:not(.align-btn--active) {
  border-color: #94a3b8;
  background: #f1f5f9;
}

.align-btn--active {
  background: #ea580c;
  border-color: #c2410c;
  color: #fff;
  box-shadow: 0 1px 3px rgba(234, 88, 12, 0.35);
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
  color: #0f766e;
  line-height: 1.35;
}
</style>
