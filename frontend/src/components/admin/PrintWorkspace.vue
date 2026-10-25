<script setup lang="ts">
import { computed, ref, useId } from 'vue';
import type { Template } from '@/api/types';
import { previewAreas } from '@/data/previewGeometry';
import { parsePanduitSku } from '@/data/panduit';
const props = defineProps<{ template: Omit<Template, 'id'>; src: string | null; loading: boolean; error: string | null; compact?: boolean }>();
const guides = ref(true);
const view = ref('labels');
const svgId = useId().replace(/:/g, '');
const labelAreas = computed(() => previewAreas({ ...props.template, gap_left: 0, gap_right: 0, gap_top: 0, gap_bottom: 0 }));
// Physical proportions; tail placement is illustrative, not a die-cut calibration.
const sticker = computed(() => {
  if (!spec.value) return null;
  const w = spec.value.width_in * 300;
  const h = spec.value.length_in * 300;
  const band = spec.value.print_area_in * 300;
  return { w, h, band, top: (h - band) / 3, gap: 28 };
});
const showLabels = computed(() => !!sticker.value && view.value === 'labels');
const zoom = ref(1);
const areas = computed(() => previewAreas(props.template));
const width = computed(() => Math.max(1, props.template.bytes_per_row * 8));
const height = computed(() => Math.max(1, props.template.height));
// Only show manufacturer specifications for an explicitly selected thermal SKU.
const spec = computed(() => /^R\d{3}X\d{3}V\d+T$/i.test(props.template.material_sku || '') ? parsePanduitSku(props.template.material_sku) : null);
const mm = (px: number) => (px * 25.4 / 300).toFixed(2);
</script>
<template>
  <section class="print-workspace" :class="{ compact }" aria-label="Label print workspace">
    <div v-if="!compact" class="workspace-toolbar">
      <div><strong>{{ template.material_sku || 'Custom material' }}</strong><small>Operator view · 300 dpi design grid</small></div>
      <div class="workspace-tools">
        <select v-if="spec" v-model="view" aria-label="Preview mode"><option value="labels">Labels</option><option value="raster">Carrier raster</option></select>
        <button type="button" :aria-pressed="guides" @click="guides = !guides">{{ guides ? 'Hide guides' : 'Show guides' }}</button>
        <select v-model.number="zoom" aria-label="Preview zoom"><option :value="1">Fit to view</option><option :value="1.5">150% of fit</option><option :value="2">200% of fit</option></select>
      </div>
    </div>
    <div class="workspace-stage" :aria-busy="loading">
      <div class="workspace-sheet" :style="{ width: `${zoom * 100}%` }">
        <div v-if="showLabels && sticker" class="workspace-dimension">{{ mm(sticker.w) }} × {{ mm(sticker.h) }} mm · each label</div>
        <div v-else class="workspace-dimension">{{ mm(width) }} mm · carrier raster width</div>
        <svg v-if="showLabels && sticker" :viewBox="`-25 -50 ${sticker.w * 2 + sticker.gap + 50} ${sticker.h + 110}`" role="img" aria-label="Two separate labels with transparent wrap and white print-on strips">
          <defs>
            <pattern :id="`${svgId}-clear`" width="16" height="16" patternUnits="userSpaceOnUse"><rect width="16" height="16" fill="#f0f4f6"/><path d="M0 0h8v8H0zM8 8h8v8H8z" fill="#e2e9ee"/></pattern>
          </defs>
          <g v-for="(area, i) in labelAreas" :key="area.label" :transform="`translate(${i * (sticker.w + sticker.gap)},0)`">
            <text :x="sticker.w / 2" y="-20" text-anchor="middle" font-size="18" fill="#475569">{{ area.label }}</text>
            <rect x="3" y="5" :width="sticker.w" :height="sticker.h" rx="12" fill="#bdcbd5" opacity=".4" />
            <rect :width="sticker.w" :height="sticker.h" rx="12" :fill="`url(#${svgId}-clear)`" stroke="#93a6b4" stroke-width="1.5" vector-effect="non-scaling-stroke" />
            <rect :y="sticker.top" :width="sticker.w" :height="sticker.band" fill="white" />
            <svg x="0" :y="sticker.top" :width="sticker.w" :height="sticker.band" :viewBox="`${area.x} ${area.y} ${sticker.w} ${sticker.band}`" overflow="hidden">
              <image v-if="src" :href="src" x="0" y="0" :width="width" :height="height" preserveAspectRatio="none" style="image-rendering:pixelated" />
            </svg>
            <rect v-if="guides" :y="sticker.top" :width="sticker.w" :height="sticker.band" fill="none" stroke="#0284c7" stroke-width="1" stroke-dasharray="5 4" vector-effect="non-scaling-stroke" />
            <text v-if="guides" :x="sticker.w / 2" :y="sticker.top + sticker.band + (sticker.h - sticker.top - sticker.band) / 2" text-anchor="middle" font-size="16" fill="#687f90">Transparent wrap</text>
            <text :x="sticker.w / 2" :y="sticker.h + 32" text-anchor="middle" font-size="16" fill="#475569">Print-on strip · {{ mm(sticker.band) }} mm</text>
          </g>
        </svg>
        <svg v-else :viewBox="`-16 -42 ${width + 32} ${height + 58}`" role="img" aria-label="Print raster with editable text area guides">
          <rect :width="width" :height="height" fill="white" stroke="#b6c6d2" />
          <image v-if="src" :href="src" :width="width" :height="height" preserveAspectRatio="none" style="image-rendering: pixelated" />
          <template v-if="guides">
            <g v-for="(area, i) in areas" :key="area.label">
              <rect :x="area.x" :y="area.y" :width="Math.max(0, area.width)" :height="Math.max(0, area.height)" fill="none" :stroke="i === 0 ? '#0369a1' : '#0f766e'" stroke-width="1.5" stroke-dasharray="6 4" vector-effect="non-scaling-stroke" />
              <text :x="area.x + 8" :y="area.y - 12" font-size="18" :fill="i === 0 ? '#0369a1' : '#0f766e'">{{ area.label }} · {{ mm(area.width) }} × {{ mm(area.height) }} mm</text>
            </g>
          </template>
        </svg>
      </div>
    </div>
    <div class="workspace-status" role="status"><span>{{ loading ? 'Updating preview…' : error && src ? 'Last valid preview · current settings rejected' : error ? 'Current settings rejected' : src ? 'Live preview' : 'Preview unavailable' }}</span><span>{{ showLabels ? 'Label appearance · proportional view' : `${mm(height)} mm carrier raster height` }}</span></div>
    <p v-if="error" class="workspace-error" role="alert">{{ error }}<span v-if="src"> The image shows the last valid settings. Reduce character width or font size to update it.</span></p>
    <p v-if="showLabels && !compact" class="workspace-note">Checkerboard represents transparent film. Label proportions follow the material specification; wrap placement is illustrative. Use Carrier raster to check positioning and ink outside the print-on strips.</p>
    <p v-else-if="!compact" class="workspace-note">Dashed guides mark the configured text areas, not the label cut lines. Guides are not printed. Screen size is not physical size.</p>
    <div v-if="spec && !compact" class="manufacturer-reference">
      <div class="reference-heading"><strong>Panduit · Turn-Tell®</strong><a href="https://www.panduit.com/content/dam/panduit/en/website/support/download-center/documents/desktop-printers-and-labels-guide-web-idcb101-sa-eng.pdf" target="_blank" rel="noopener noreferrer">Manufacturer guide ↗</a></div>
      <dl><div><dt>Label size</dt><dd>{{ (spec.width_in * 25.4).toFixed(1) }} × {{ (spec.length_in * 25.4).toFixed(1) }} mm</dd></div><div><dt>Print-on height</dt><dd>{{ (spec.print_area_in * 25.4).toFixed(1) }} mm</dd></div><div><dt>Cable diameter</dt><dd>{{ (spec.min_od_in * 25.4).toFixed(1) }}–{{ (spec.max_od_in * 25.4).toFixed(1) }} mm</dd></div></dl>
      <p>Manufacturer dimensions are a reference. Your draft’s positioning and calibration remain editable.</p>
    </div>
  </section>
</template>
<style scoped>
.print-workspace { border:1px solid #d4dfe7; border-radius:12px; overflow:hidden; background:#fff; color:#334155; }
.workspace-toolbar,.workspace-status,.reference-heading { display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; }
.workspace-toolbar { padding:16px 18px; border-bottom:1px solid #d4dfe7; }
.workspace-toolbar strong { font-size:16px; } .workspace-toolbar small { display:block; margin-top:3px; color:#64748b; }
.workspace-tools { display:flex; gap:8px; flex-wrap:wrap; }
.workspace-tools button,.workspace-tools select { padding:7px 10px; border:1px solid #cbd5e1; border-radius:6px; background:white; font-size:12px; cursor:pointer; }
.workspace-tools button[aria-pressed=true] { color:#0369a1; border-color:#7fb3ce; background:#f0f9ff; }
.workspace-tools :focus-visible { outline:2px solid #0369a1; outline-offset:2px; }
.workspace-stage { padding:24px; overflow:auto; max-height:65vh; background-color:#edf2f5; background-image:radial-gradient(#cbd5df .7px, transparent .7px); background-size:16px 16px; }
.workspace-sheet { min-width:100%; } .workspace-sheet > svg { display:block; width:100%; }
.workspace-dimension { text-align:center; color:#637789; font:11px ui-monospace,monospace; margin-bottom:8px; }
.workspace-status { font-size:11px; padding:10px 16px; background:#f8fafc; border-top:1px solid #d4dfe7; }
.workspace-note,.workspace-error { padding:10px 16px; margin:0; font-size:12px; color:#64748b; } .workspace-error { color:#b91c1c; }
.manufacturer-reference { padding:16px; border-top:1px solid #d4dfe7; }
.reference-heading { font-size:13px; } .reference-heading a { color:#0369a1; text-decoration:underline; font-size:12px; }
.manufacturer-reference dl { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin:16px 0; }
.manufacturer-reference dt,.manufacturer-reference p { font-size:11px; color:#64748b; } .manufacturer-reference dd { font-size:14px; margin:4px 0 0; font-variant-numeric:tabular-nums; }
.compact .workspace-stage { padding:10px; }
@media(max-width:600px) { .workspace-stage { padding:10px; } .manufacturer-reference dl { grid-template-columns:1fr; } }
</style>
