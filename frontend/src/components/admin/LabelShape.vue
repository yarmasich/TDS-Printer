<script setup lang="ts">
/**
 * Schematic of a PANDUIT R-series self-laminating wrap-around label,
 * drawn as the operator sees it on the roll: two labels per row,
 * separated by a die-cut gap. Length axis is vertical (this is the
 * axis that wraps around the cable); width axis is horizontal (along
 * the cable). Print-On Area is a horizontal strip in the middle of
 * each label, with transparent laminating wrap tails above and below.
 *
 * The live preview PNG (which holds both labels' text side-by-side as
 * one bitmap) is split visually: left half lands in the left label,
 * right half in the right label, using SVG clipping.
 */
import { computed } from "vue";
import type { PanduitSpec } from "@/data/panduit";
import { formatInMm } from "@/data/panduit";

const props = defineProps<{
  spec: PanduitSpec;
  /** Live print preview PNG (Blob URL). The same bitmap is drawn into
   * both labels — left half visible in the left one, right half in
   * the right one. */
  previewSrc?: string | null;
  /** Show a spinner overlay while a new preview is being fetched. */
  loading?: boolean;
  /** When the template uses mirror_mode the printer flips the text 180°
   * so it reads right-side-up after the label is wrapped around a
   * cable. The schematic counter-rotates the preview bitmap so the
   * operator can actually read it on screen. */
  mirror?: boolean;
}>();

// 96 user units = 1 inch — gives crisp numbers in the SVG.
const UPI = 96;

const labelW = computed(() => props.spec.width_in * UPI);   // horizontal — along cable
const labelL = computed(() => props.spec.length_in * UPI);  // vertical   — wraps around
const printH = computed(() => props.spec.print_area_in * UPI);
// On real PANDUIT R-series labels the Print-On Area sits slightly
// off-centre: a short anchor tail at the top, the white print strip,
// then a longer wrap tail at the bottom that loops around the cable
// and laminates the printed side. ~1:2 split of the non-print height
// matches the physical labels closely.
const slack = computed(() => labelL.value - printH.value);
const topTail = computed(() => slack.value / 3);
const bottomTail = computed(() => slack.value - topTail.value);

// Two labels per row, separated by a thin die-cut gap.
const COUNT = 2;
const LABEL_GAP = 6;

// Margins around the body — leave room for outer dimension tics and
// the cable disc below.
const PAD_L = 24;
const PAD_R = 60;  // 'W = …' tic label lives here
const PAD_T = 28;  // 'W = …' tic label and row-pitch label live here
const PAD_B = 16;
const DISC_GAP = 24;
const discR = computed(() => (props.spec.max_od_in / 2) * UPI);
const discBlock = computed(() => discR.value * 2 + DISC_GAP + 18);

const rowWidth = computed(() => COUNT * labelW.value + (COUNT - 1) * LABEL_GAP);
const vbW = computed(() => rowWidth.value + PAD_L + PAD_R);
const vbH = computed(() => labelL.value + PAD_T + PAD_B + discBlock.value);

const labelBg = computed(() => props.spec.color.hex);
const strokeColor = computed(() =>
  props.spec.color.hex === "#ffffff" ? "#475569" : "#1e293b",
);
const skuCode = computed(
  () =>
    `R${String(props.spec.width_in * 100).padStart(3, "0")}` +
    `X${String(props.spec.length_in * 100).padStart(3, "0")}` +
    `${props.spec.color.code}T`,
);

/** Left-edge X of the n-th label (0-based). */
function labelX(n: number): number {
  return PAD_L + n * (labelW.value + LABEL_GAP);
}
</script>

<template>
  <div class="shape-wrap">
    <div class="shape-canvas">
      <div v-if="loading" class="shape-spinner-bg">
        <div class="shape-spinner" />
      </div>
    <svg
      :viewBox="`0 0 ${vbW} ${vbH}`"
      xmlns="http://www.w3.org/2000/svg"
      class="shape-svg"
      role="img"
      :aria-label="`${skuCode} schematic — ${COUNT} labels per row`"
    >
      <defs>
        <!-- Transparent wrap hatching: diagonal stripes over the tails. -->
        <pattern
          id="wrap-hatch"
          width="6" height="6"
          patternUnits="userSpaceOnUse"
          patternTransform="rotate(45)"
        >
          <line x1="0" y1="0" x2="0" y2="6" :stroke="strokeColor" stroke-width="0.5" opacity="0.25" />
        </pattern>
        <!-- One clip path per label, cropping the bitmap to that label's
             Print-On Area rectangle. -->
        <clipPath v-for="n in COUNT" :key="`clip-${n}`" :id="`label-clip-${n - 1}`">
          <rect
            :x="labelX(n - 1)"
            :y="PAD_T + topTail"
            :width="labelW"
            :height="printH"
          />
        </clipPath>
      </defs>

      <!-- One label slot per column -->
      <template v-for="n in COUNT" :key="n">
        <!-- full body -->
        <rect
          :x="labelX(n - 1)" :y="PAD_T"
          :width="labelW" :height="labelL"
          rx="4" ry="4"
          :fill="labelBg"
          :stroke="strokeColor"
          stroke-width="1.5"
        />
        <!-- top wrap tail (short anchor) -->
        <rect
          :x="labelX(n - 1)" :y="PAD_T"
          :width="labelW" :height="topTail"
          fill="url(#wrap-hatch)"
        />
        <!-- bottom wrap tail (longer, wraps around cable) -->
        <rect
          :x="labelX(n - 1)" :y="PAD_T + topTail + printH"
          :width="labelW" :height="bottomTail"
          fill="url(#wrap-hatch)"
        />
        <!-- print-on area (opaque white strip) -->
        <rect
          :x="labelX(n - 1)" :y="PAD_T + topTail"
          :width="labelW" :height="printH"
          fill="#ffffff"
        />
        <!-- Live print bitmap: the *full* PNG is drawn stretched across
             the entire row, then clipped to this one label's Print-On
             Area. That way the left label sees the left half of the
             bitmap, the right label sees the right half — same as how
             the bitmap is physically laid out by the printer.
             When mirror_mode is on the printer flips the bitmap 180°
             (so the wrapped label reads right-side-up); we counter-
             rotate it here so the schematic stays readable. -->
        <image
          v-if="previewSrc"
          :href="previewSrc"
          :x="PAD_L"
          :y="PAD_T + topTail"
          :width="rowWidth"
          :height="printH"
          preserveAspectRatio="none"
          :clip-path="`url(#label-clip-${n - 1})`"
          :transform="mirror
            ? `rotate(180, ${labelX(n - 1) + labelW / 2}, ${PAD_T + topTail + printH / 2})`
            : undefined"
          style="image-rendering: pixelated"
        />
        <!-- Dashed outline of the Print-On Area, drawn on top so it
             stays crisp over the bitmap. -->
        <rect
          :x="labelX(n - 1)" :y="PAD_T + topTail"
          :width="labelW" :height="printH"
          fill="none"
          stroke="#0284c7"
          stroke-width="1.5"
          stroke-dasharray="4 3"
        />
      </template>

      <!-- ─── outer dimension lines ─── -->
      <!-- Single-label Width (top, over the first label) -->
      <g :stroke="strokeColor" stroke-width="1">
        <line :x1="labelX(0)" :y1="PAD_T - 10" :x2="labelX(0) + labelW" :y2="PAD_T - 10" />
        <line :x1="labelX(0)" :y1="PAD_T - 14" :x2="labelX(0)" :y2="PAD_T - 6" />
        <line :x1="labelX(0) + labelW" :y1="PAD_T - 14" :x2="labelX(0) + labelW" :y2="PAD_T - 6" />
      </g>
      <text
        :x="labelX(0) + labelW / 2"
        :y="PAD_T - 16"
        text-anchor="middle"
        font-size="10"
        :fill="strokeColor"
      >W = {{ spec.width_in.toFixed(2) }}″</text>

      <!-- Length (right side of the row — long axis, wraps around cable) -->
      <g :stroke="strokeColor" stroke-width="1">
        <line
          :x1="labelX(COUNT - 1) + labelW + 10" :y1="PAD_T"
          :x2="labelX(COUNT - 1) + labelW + 10" :y2="PAD_T + labelL"
        />
        <line
          :x1="labelX(COUNT - 1) + labelW + 6" :y1="PAD_T"
          :x2="labelX(COUNT - 1) + labelW + 14" :y2="PAD_T"
        />
        <line
          :x1="labelX(COUNT - 1) + labelW + 6" :y1="PAD_T + labelL"
          :x2="labelX(COUNT - 1) + labelW + 14" :y2="PAD_T + labelL"
        />
      </g>
      <text
        :x="labelX(COUNT - 1) + labelW + 18"
        :y="PAD_T + labelL / 2 + 4"
        font-size="10"
        :fill="strokeColor"
      >L = {{ spec.length_in.toFixed(2) }}″</text>

      <!-- ─── cable cross-section disc, below the row ─── -->
      <g :transform="`translate(${PAD_L + rowWidth / 2}, ${PAD_T + labelL + DISC_GAP + discR})`">
        <circle
          :r="discR"
          fill="#e2e8f0"
          :stroke="strokeColor"
          stroke-width="1"
          stroke-dasharray="3 2"
        />
        <circle
          :r="(spec.min_od_in / 2) * UPI"
          fill="#cbd5e1"
          :stroke="strokeColor"
          stroke-width="1"
        />
        <text
          :y="discR + 14"
          text-anchor="middle"
          font-size="10"
          :fill="strokeColor"
        >cable Ø {{ spec.min_od_in.toFixed(2) }}–{{ spec.max_od_in.toFixed(2) }}″</text>
      </g>
    </svg>
    </div>

    <div class="shape-meta">
      <div class="meta-row">
        <b>{{ skuCode }}</b>
        <span class="dot">·</span>
        <span>{{ spec.color.name }}</span>
        <span class="dot">·</span>
        <span>{{ COUNT }} per row</span>
      </div>
      <div class="meta-row text-slate-600">
        <span><span class="swatch print-swatch" /> Print-On {{ formatInMm(spec.print_area_in) }}</span>
        <span class="dot">·</span>
        <span>
          <span class="swatch wrap-swatch" />
          wraps {{ ((spec.length_in - spec.print_area_in) / 2).toFixed(2) }}″ each side
        </span>
      </div>
      <div class="meta-row text-slate-500">{{ spec.wire_range }}</div>
    </div>
  </div>
</template>

<style scoped>
.shape-wrap {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}
.shape-canvas {
  position: relative;
  width: 100%;
}
.shape-svg {
  width: 100%;
  height: auto;
  display: block;
}
.shape-spinner-bg {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(248, 250, 252, 0.5);
  z-index: 1;
}
.shape-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid #cbd5e1;
  border-top-color: #0284c7;
  border-radius: 50%;
  animation: shape-spin 0.9s linear infinite;
}
.shape-meta {
  font-size: 12px;
  line-height: 1.5;
}
.meta-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.dot {
  color: #94a3b8;
}
.swatch {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 2px;
  margin-right: 4px;
  vertical-align: -1px;
}
.print-swatch {
  background: #ffffff;
  border: 1.5px dashed #0284c7;
}
.wrap-swatch {
  background:
    repeating-linear-gradient(
      45deg,
      transparent 0 2px,
      #475569 2px 3px
    );
  border: 1px solid #cbd5e1;
}
@keyframes shape-spin {
  to { transform: rotate(360deg); }
}
</style>
