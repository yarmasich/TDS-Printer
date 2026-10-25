<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue';
import Button from 'primevue/button';
import InputText from 'primevue/inputtext';
import { api } from '@/api/client';
import { useLatestResource } from '@/composables/latestResource';
import type { Template } from '@/api/types';

type Material = {
  sku: string; printer_type: string; cut_type: string; supported: boolean; limitation: string;
  rows: number; columns: number; page_width_mm: number; page_height_mm: number;
  print_width_mm: number; print_height_mm: number; gap_mm: number; pitch_mm: number;
};
type Detail = { material: Material; geometry: Partial<Template> | null };
const props = defineProps<{ sku: string; enabled: boolean }>();
const emit = defineEmits<{ apply: [geometry: Partial<Template>] }>();
const query = ref('');
const showResults = ref(true);
const results = useLatestResource<{ items: Material[]; total: number }>();
const selected = useLatestResource<Detail>();
function search() {
  showResults.value = true;
  return results.run(() => api.get(`/api/materials?q=${encodeURIComponent(query.value)}&limit=30`));
}
async function choose(sku: string) {
  await selected.run(() => api.get(`/api/materials/${encodeURIComponent(sku)}`));
  if (selected.data.value) showResults.value = false;
}
watch(() => props.sku, sku => {
  if (sku) { query.value = sku; choose(sku); }
  else selected.clear();
}, { immediate: true });
function apply(layout: boolean) {
  const g = selected.data.value?.geometry;
  if (!g || !props.enabled) return;
  if (layout) emit('apply', g);
  else emit('apply', { material_sku: g.material_sku, bytes_per_row: g.bytes_per_row,
    height: g.height, media_height_mm: g.media_height_mm, media_gap_mm: g.media_gap_mm });
}
onUnmounted(() => { results.clear(); selected.clear(); });
</script>

<template>
  <fieldset class="material-picker space-y-3">
    <legend class="text-xs font-bold text-slate-500 uppercase px-1">Material catalog</legend>
    <p class="text-sm text-slate-600">Enter the full part number from the roll.</p>
    <div class="material-search">
      <InputText v-model="query" aria-label="Material part number" placeholder="e.g. R200X150V1T" class="min-w-0 flex-1" @keydown.enter.prevent="search" />
      <Button label="Find material" icon="pi pi-search" :loading="results.loading.value" @click="search" />
    </div>
    <p v-if="results.error.value || selected.error.value" role="alert" class="text-sm text-red-700">{{ results.error.value || selected.error.value }}</p>
    <div v-if="results.data.value && showResults" class="space-y-1">
      <p class="text-xs text-slate-500">{{ results.data.value.items.length }} shown / {{ results.data.value.total }} found</p>
      <div class="max-h-44 overflow-y-auto divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
        <button v-for="item in results.data.value.items" :key="item.sku" type="button"
          class="block w-full px-3 py-2 text-left hover:bg-sky-50 focus-visible:outline-2 focus-visible:outline-sky-500"
          @click="choose(item.sku)">
          <span class="font-semibold text-sm">{{ item.sku }}</span>
          <span class="block text-xs text-slate-500">{{ item.printer_type }} · {{ item.columns }} per row · {{ item.supported ? 'Layout available' : 'Reference only' }}</span>
        </button>
      </div>
    </div>
    <p v-if="selected.loading.value" class="text-sm text-slate-500">Loading material…</p>
    <button v-if="results.data.value && !showResults" type="button" class="text-sm text-emerald-700 underline underline-offset-4" @click="showResults = true">Choose another result ({{ results.data.value.total }})</button>
    <div v-if="selected.data.value" class="material-selection space-y-3">
      <div class="flex justify-between gap-3"><strong>{{ selected.data.value.material.sku }}</strong><span class="text-xs text-emerald-700">{{ sku === selected.data.value.material.sku ? 'Applied to draft' : 'Not applied' }}</span></div>
      <dl class="grid grid-cols-2 gap-2 text-sm">
        <div><dt class="text-slate-500">Page / carrier</dt><dd>{{ selected.data.value.material.page_width_mm }} × {{ selected.data.value.material.page_height_mm }} mm</dd></div>
        <div><dt class="text-slate-500">Print area per label</dt><dd>{{ selected.data.value.material.print_width_mm }} × {{ selected.data.value.material.print_height_mm }} mm</dd></div>
        <div><dt class="text-slate-500">Gap</dt><dd>{{ selected.data.value.material.gap_mm }} mm</dd></div>
        <div><dt class="text-slate-500">Feed pitch</dt><dd>{{ selected.data.value.material.pitch_mm }} mm</dd></div>
      </dl>
      <p v-if="!selected.data.value.material.supported" class="text-sm text-amber-800">{{ selected.data.value.material.limitation }}</p>
      <template v-else>
        <p v-if="!enabled" class="text-sm text-amber-800">Printer setup required — see the printer selector above.</p>
        <div class="flex flex-wrap gap-2">
          <Button :disabled="!enabled" label="Apply sizes only" size="small" @click="apply(false)" />
          <Button :disabled="!enabled" label="Apply full layout" size="small" severity="secondary" outlined @click="apply(true)" />
        </div>
        <p class="text-xs text-slate-500">Sizes only keeps your text positions. Full layout also replaces text areas and padding.</p>
      </template>
    </div>
  </fieldset>
</template>

<style scoped>
.material-search { display: flex; gap: .5rem; }
.material-search > :first-child { min-width: 0; flex: 1; }
.material-search > :last-child { flex-shrink: 0; }
.material-selection { border-top: 1px solid #e2e8f0; padding-top: 1rem; }
.material-selection dd { color: #243c4c; font-variant-numeric: tabular-nums; margin-top: 3px; }
@media (max-width: 540px) { .material-search { flex-direction: column; } }
</style>
