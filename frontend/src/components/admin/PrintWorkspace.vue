<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue';
import { api } from '@/api/client';
import type { Template } from '@/api/types';
import { useLatestResource } from '@/composables/latestResource';
import { labelStock, type StockMaterial } from '@/data/labelStock';
import { previewAreas } from '@/data/previewGeometry';
import { parsePanduitSku } from '@/data/panduit';
const props = defineProps<{ template: Omit<Template, 'id'>; src: string | null; loading: boolean; error: string | null; errorKind?: 'validation' | 'transport'; compact?: boolean }>();
const emit = defineEmits<{ retry: [] }>();
const guides = ref(true);
const view = ref('labels');
const svgId = useId().replace(/:/g, '');
// Label shapes come from the Panduit material, never from the template, so
// text areas that drifted off the white area look wrong instead of corrected.
const materialResource = useLatestResource<{ material: StockMaterial & { sku: string } }>();
watch(() => props.template.material_sku, (sku) => {
  if (!sku) materialResource.clear();
  else void materialResource.run(() => api.get(`/api/materials/${encodeURIComponent(sku)}`));
}, { immediate: true });
const material = computed(() => materialResource.data.value?.material ?? null);
const stock = computed(() => labelStock(material.value, props.template));
const sheet = computed(() => {
  const first = stock.value?.labels[0];
  return first ? { w: first.outline.w, h: first.outline.h, gap: 28 } : null;
});
const clearCaption = computed(() => /self-laminating/i.test(stock.value?.kind ?? '') ? 'Transparent laminate' : 'Transparent wrap');
const showLabels = computed(() => !!stock.value && view.value === 'labels');
const zoom = ref(1);
const areas = computed(() => previewAreas(props.template));
const width = computed(() => Math.max(1, props.template.bytes_per_row * 8));
const height = computed(() => Math.max(1, props.template.height));
// Cable diameters are only tabulated for Turn-Tell thermal SKUs.
const spec = computed(() => /^R\d{3}X\d{3}V\d+T$/i.test(props.template.material_sku || '') ? parsePanduitSku(props.template.material_sku) : null);
const mm = (px: number) => (px * 25.4 / 300).toFixed(2);
// Centre the film caption in the larger clear region, above or below the white area.
function clearCaptionY(label: { outline: { y: number; h: number }; printOn: { y: number; h: number } }) {
  const top = label.printOn.y - label.outline.y, bottom = label.outline.h - top - label.printOn.h;
  return bottom >= top ? top + label.printOn.h + bottom / 2 : top / 2;
}
</script>
<template>
  <section class="print-workspace" :class="{ compact }" aria-label="Label print workspace">
    <div v-if="!compact" class="workspace-toolbar">
      <div><strong>{{ template.material_sku || 'Custom material' }}</strong><small>Operator view · 300 dpi design grid</small></div>
      <div class="workspace-tools">
        <select v-if="stock" name="preview_mode" v-model="view" aria-label="Preview mode"><option value="labels">Labels</option><option value="raster">Carrier raster</option></select>
        <button type="button" :aria-pressed="guides" @click="guides = !guides">{{ guides ? 'Hide guides' : 'Show guides' }}</button>
        <select name="preview_zoom" v-model.number="zoom" aria-label="Preview zoom"><option :value="1">Fit to view</option><option :value="1.5">150% of fit</option><option :value="2">200% of fit</option></select>
      </div>
    </div>
    <div class="workspace-stage" :aria-busy="loading">
      <div class="workspace-sheet" :style="{ width: `${zoom * 100}%` }">
        <div v-if="showLabels && sheet" class="workspace-dimension">{{ mm(sheet.w) }} × {{ mm(sheet.h) }} mm · each label</div>
        <div v-else class="workspace-dimension">{{ mm(width) }} mm · carrier raster width</div>
        <svg v-if="showLabels && stock && sheet" :viewBox="`-25 -50 ${sheet.w * 2 + sheet.gap + 50} ${sheet.h + 110}`" role="img" aria-label="Two labels drawn from the Panduit material: white print-on areas, clear film, and ink where it will print">
          <defs>
            <pattern :id="`${svgId}-clear`" width="16" height="16" patternUnits="userSpaceOnUse"><rect width="16" height="16" fill="#f0f4f6"/><path d="M0 0h8v8H0zM8 8h8v8H8z" fill="#e2e9ee"/></pattern>
            <clipPath v-for="(label, i) in stock.labels" :id="`${svgId}-cut-${i}`" :key="label.label"><rect :width="sheet.w" :height="sheet.h" :rx="label.radius" /></clipPath>
          </defs>
          <g v-for="(label, i) in stock.labels" :key="label.label" :transform="`translate(${i * (sheet.w + sheet.gap)},0)`">
            <text :x="sheet.w / 2" y="-20" text-anchor="middle" font-size="18" fill="#475569">{{ label.label }}</text>
            <rect x="3" y="5" :width="sheet.w" :height="sheet.h" :rx="label.radius" fill="#bdcbd5" opacity=".4" />
            <g :clip-path="`url(#${svgId}-cut-${i})`">
              <rect :width="sheet.w" :height="sheet.h" :fill="label.clear ? `url(#${svgId}-clear)` : 'white'" />
              <rect :x="label.printOn.x - label.outline.x" :y="label.printOn.y - label.outline.y" :width="label.printOn.w" :height="label.printOn.h" fill="white" />
              <!-- The whole label's share of the raster, where it prints. Multiply
                   keeps the bitmap's white background from painting over the film. -->
              <svg x="0" y="0" :width="sheet.w" :height="sheet.h" :viewBox="`${label.outline.x} ${label.outline.y} ${sheet.w} ${sheet.h}`" overflow="hidden">
                <image v-if="src" :href="src" x="0" y="0" :width="width" :height="height" preserveAspectRatio="none" style="image-rendering:pixelated; mix-blend-mode:multiply" />
              </svg>
            </g>
            <rect :width="sheet.w" :height="sheet.h" :rx="label.radius" fill="none" stroke="#93a6b4" stroke-width="1.5" vector-effect="non-scaling-stroke" />
            <template v-if="guides">
              <rect :x="label.printOn.x - label.outline.x" :y="label.printOn.y - label.outline.y" :width="label.printOn.w" :height="label.printOn.h" fill="none" stroke="#0284c7" stroke-width="1" stroke-dasharray="5 4" vector-effect="non-scaling-stroke" />
              <rect v-if="areas[i]" :x="areas[i]!.x - label.outline.x" :y="areas[i]!.y - label.outline.y" :width="Math.max(0, areas[i]!.width)" :height="Math.max(0, areas[i]!.height)" fill="none" :stroke="i === 0 ? '#0369a1' : '#0f766e'" stroke-width="1.5" stroke-dasharray="2 3" vector-effect="non-scaling-stroke" />
              <text v-if="label.clear" :x="sheet.w / 2" :y="clearCaptionY(label)" text-anchor="middle" font-size="16" fill="#687f90">{{ clearCaption }}</text>
            </template>
            <text :x="sheet.w / 2" :y="sheet.h + 32" text-anchor="middle" font-size="16" fill="#475569">Print-on area · {{ mm(label.printOn.h) }} mm</text>
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
    <div class="workspace-status" role="status"><span>{{ loading ? 'Updating preview…' : error && errorKind === 'transport' ? 'Preview could not update' : error && src ? 'Last valid preview · current settings rejected' : error ? 'Current settings rejected' : src ? 'Live preview' : 'Preview unavailable' }}</span><span>{{ showLabels ? 'Label appearance · proportional view' : `${mm(height)} mm carrier raster height` }}</span></div>
    <p v-if="error" class="workspace-error" role="alert">{{ error }}<span v-if="src && errorKind !== 'transport'"> The image shows the last valid settings. Reduce character width or font size to update it.</span><span v-if="errorKind === 'transport'"> Check your connection and retry. <button type="button" @click.stop="emit('retry')" @keydown.stop>Retry preview</button></span></p>
    <p v-for="warning in stock?.warnings ?? []" :key="warning" class="workspace-error" role="alert">{{ warning }} Apply the full material layout or move the text areas.</p>
    <p v-if="showLabels && !compact" class="workspace-note">Label outlines and white print-on areas come from the Panduit EasyMark catalog; the checkerboard is clear film. Ink is drawn where it will print, so text outside the white area shows on the film. Each label's top is drawn at the top of its row.</p>
    <p v-else-if="!compact" class="workspace-note">Dashed guides mark the configured text areas, not the label cut lines. Guides are not printed. Screen size is not physical size.</p>
    <div v-if="material && stock && !compact" class="manufacturer-reference">
      <div class="reference-heading"><strong>Panduit · {{ stock.kind ?? material.sku }}</strong><a href="https://www.panduit.com/content/dam/panduit/en/website/support/download-center/documents/desktop-printers-and-labels-guide-web-idcb101-sa-eng.pdf" target="_blank" rel="noopener noreferrer">Manufacturer guide ↗</a></div>
      <dl><div><dt>Label size</dt><dd>{{ material.label_width_mm?.toFixed(1) }} × {{ material.label_length_mm?.toFixed(1) }} mm</dd></div><div><dt>Print-on height</dt><dd>{{ material.print_on_height_mm ? `${material.print_on_height_mm.toFixed(1)} mm` : 'Whole label' }}</dd></div><div v-if="spec"><dt>Cable diameter</dt><dd>{{ (spec.min_od_in * 25.4).toFixed(1) }}–{{ (spec.max_od_in * 25.4).toFixed(1) }} mm</dd></div></dl>
      <p>Manufacturer dimensions are a reference. Your draft’s positioning and calibration remain editable.</p>
    </div>
  </section>
</template>
<style scoped>
.print-workspace { border:1px solid var(--tds-edge); border-radius:12px; overflow:hidden; background:var(--tds-surface); color:var(--tds-ink-2); }
.workspace-toolbar,.workspace-status,.reference-heading { display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; }
.workspace-toolbar { padding:16px 18px; border-bottom:1px solid var(--tds-edge); }
.workspace-toolbar strong { font-size:16px; } .workspace-toolbar small { display:block; margin-top:3px; color:var(--tds-ink-3); }
.workspace-tools { display:flex; gap:8px; flex-wrap:wrap; }
.workspace-tools button,.workspace-tools select { padding:7px 10px; border:1px solid var(--tds-edge-strong); border-radius:6px; background:var(--tds-surface); color:var(--tds-ink); font-size:12px; cursor:pointer; }
.workspace-tools button[aria-pressed=true] { color:var(--tds-accent-ink); border-color:var(--tds-accent-edge); background:var(--tds-accent-soft); }
.workspace-tools :focus-visible { outline:2px solid var(--tds-accent); outline-offset:2px; }
.workspace-stage { padding:24px; overflow:auto; max-height:65vh; background-color:var(--tds-stage); color:var(--tds-stage-ink); background-image:radial-gradient(var(--tds-stage-edge-strong) .7px, transparent .7px); background-size:16px 16px; }
.workspace-sheet { min-width:100%; } .workspace-sheet > svg { display:block; width:100%; }
.workspace-dimension { text-align:center; color:var(--tds-stage-ink-3); font:11px ui-monospace,monospace; margin-bottom:8px; }
.workspace-status { font-size:11px; padding:10px 16px; background:var(--tds-sunken); border-top:1px solid var(--tds-edge); }
.workspace-note,.workspace-error { padding:10px 16px; margin:0; font-size:12px; color:var(--tds-ink-3); } .workspace-error { color:var(--tds-danger); }
.manufacturer-reference { padding:16px; border-top:1px solid var(--tds-edge); }
.reference-heading { font-size:13px; } .reference-heading a { color:var(--tds-accent-ink); text-decoration:underline; font-size:12px; }
.manufacturer-reference dl { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin:16px 0; }
.manufacturer-reference dt,.manufacturer-reference p { font-size:11px; color:var(--tds-ink-3); } .manufacturer-reference dd { font-size:14px; margin:4px 0 0; font-variant-numeric:tabular-nums; }
.compact .workspace-stage { padding:10px; }
@media(max-width:600px) { .workspace-stage { padding:10px; } .manufacturer-reference dl { grid-template-columns:1fr; } }
@media (pointer:coarse), (max-width:1100px) { .workspace-tools button, .workspace-tools select, .workspace-error button { min-height:44px; } }
</style>
