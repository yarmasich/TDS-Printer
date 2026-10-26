<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import type { SearchHit } from '@/api/types';
import { stationAuthHeader, apiUrl } from '@/api/client';
import { useStationAuth } from "@/stores/stationAuth";
import { readApiError } from '@/api/errors';
import { enqueuePreview, type LabelPreview } from '@/data/labelPreview';
import Button from 'primevue/button';
import StickerPreview from './StickerPreview.vue';

const stationAuth = useStationAuth();
const props = defineProps<{ hit: SearchHit; kiosk?: boolean }>();
defineEmits<{ cart: [labelId: number] }>();
const element = ref<HTMLElement>();
const preview = ref<LabelPreview | null>(null);
const error = ref<string | null>(null);
const visible = ref(false);
const loading = ref(false);
let observer: IntersectionObserver | undefined;
let controller: AbortController | undefined;
const sides = computed(() => [
  { name: 'Left' as const, text: props.hit.left_text, matched: props.hit.matched_left },
  { name: 'Right' as const, text: props.hit.right_text, matched: props.hit.matched_right },
]);
const dimensions = computed(() => {
  const material = preview.value?.material;
  return material ? `${material.width_mm.toFixed(1)} × ${material.height_mm.toFixed(1)} mm each` : 'Text area preview';
});
async function load() {
  controller?.abort();
  const request = new AbortController();
  controller = request;
  loading.value = true;
  error.value = null;
  try {
    const id = props.hit.label_id;
    const result = await enqueuePreview(async () => {
      const response = await fetch(apiUrl(`/api/labels/${id}/preview`), { signal: request.signal, headers: stationAuthHeader() });
      if (!response.ok) throw new Error(await readApiError(response));
      const data = await response.json() as LabelPreview;
      if (!data.image?.startsWith('data:image/png;base64,') || !data.areas?.some(a => a.label === 'Left') || !data.areas.some(a => a.label === 'Right')) throw new Error('Invalid preview');
      return data;
    }, request.signal);
    if (!request.signal.aborted) preview.value = result;
  } catch (cause) {
    if (!request.signal.aborted) {
      preview.value = null;
      error.value = cause instanceof Error ? cause.message : 'Preview could not be loaded.';
    }
  } finally {
    if (!request.signal.aborted) loading.value = false;
  }
}
watch(() => [props.hit.label_id, stationAuth.station?.printer_id], () => {
  controller?.abort();
  preview.value = null;
  error.value = null;
  if (visible.value) void load();
});
onMounted(() => {
  if (typeof IntersectionObserver === 'undefined') { visible.value = true; void load(); return; }
  observer = new IntersectionObserver(entries => {
    if (entries.some(entry => entry.isIntersecting)) {
      visible.value = true;
      observer?.disconnect();
      void load();
    }
  }, { rootMargin: '180px' });
  if (element.value) observer.observe(element.value);
});
onBeforeUnmount(() => { observer?.disconnect(); controller?.abort(); });
</script>

<template>
  <article ref="element" class="result-card" :class="{ 'result-card--kiosk': kiosk }">
    <div class="result-layout">
      <div class="result-labels" :aria-busy="loading">
        <div v-for="side in sides" :key="side.name" class="result-side">
          <div class="side-caption" :class="{ matched: side.matched }">
            <span>{{ side.name }}</span><span v-if="side.matched" class="match-mark">✓ Matched</span>
          </div>
          <div class="sticker-stage" :class="{ 'sticker-stage--matched': side.matched }">
            <StickerPreview v-if="preview" :preview="preview" :side="side.name" />
            <div v-else class="label-fallback">{{ side.text || '—' }}</div>
          </div>
        </div>
      </div>
      <div class="result-actions">
        <Button label="Add" icon="pi pi-plus" class="result-add-btn" @click="$emit('cart', hit.label_id)" />
      </div>
    </div>
    <div v-if="error" class="preview-error" role="status">
      <span>Preview unavailable: {{ error }} Label text is shown.</span>
      <button type="button" @click="load">Retry preview</button>
    </div>
    <p v-else-if="preview" class="material-note">
      <span>{{ preview.material_sku || 'Custom material' }} · {{ dimensions }}</span>
      <span v-if="preview.material">Clear wrap placement is illustrative.</span>
    </p>
    <p v-else class="material-note" role="status">{{ loading ? 'Preparing sticker preview…' : 'Sticker preview loads when visible' }}</p>
    <details v-if="preview" class="label-details">
      <summary>Label text</summary>
      <div class="label-transcript"><div v-for="side in sides" :key="side.name"><strong>{{ side.name }}</strong><p>{{ side.text || '—' }}</p></div></div>
    </details>
    <div class="result-source">
      {{ hit.project_name }} / {{ hit.data_hall_name }} / {{ hit.discipline_name }}
      <span>· {{ hit.sheet_name }}:{{ hit.row_idx }}</span>
    </div>
  </article>
</template>

<style scoped>
.result-card { padding:16px; background:#fff; border:1px solid #dce5ec; border-radius:16px; box-shadow:0 2px 4px #1e293b05; }
.result-layout { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:16px; align-items:center; }
.result-labels { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
.result-side { min-width:0; }
.side-caption { display:flex; align-items:center; justify-content:space-between; gap:4px; margin-bottom:7px; font-size:12px; font-weight:700; color:#64748b; }
.side-caption.matched { color:#0369a1; }
.match-mark { font-size:11px; font-weight:600; }
.sticker-stage { display:flex; align-items:center; height:calc(100% - 25px); padding:12px; border:1px solid #e5ebf0; border-radius:10px; background:#f5f8fa; }
.sticker-stage--matched { border-color:#9dc8df; background:#eff7fb; }
.label-fallback { width:100%; min-height:90px; display:flex; align-items:center; justify-content:center; white-space:pre-wrap; overflow-wrap:anywhere; text-align:center; line-height:1.5; font-size:15px; color:#334155; }
.result-add-btn { min-height:48px; min-width:96px; touch-action:manipulation; }
.result-card--kiosk .result-add-btn { min-height:56px; }
.material-note { display:flex; flex-wrap:wrap; column-gap:12px; row-gap:3px; margin:10px 0 0; font-size:11px; line-height:1.5; color:#64748b; }
.material-note span:first-child { font-variant-numeric:tabular-nums; }
.preview-error { display:flex; flex-wrap:wrap; align-items:center; gap:8px; margin-top:8px; color:#9f3a24; font-size:13px; }
.preview-error button { min-height:48px; padding:0 12px; text-decoration:underline; cursor:pointer; }
.label-details { margin-top:4px; color:#475569; font-size:13px; }
.label-details summary { cursor:pointer; min-height:48px; display:flex; align-items:center; gap:8px; width:fit-content; }
.label-details summary::before { content:'›'; font-size:20px; }
.label-details[open] summary::before { transform:rotate(90deg); }
.label-transcript { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; padding:0 0 12px; }
.label-transcript strong { font-size:11px; color:#64748b; }
.label-transcript p { margin:5px 0 0; white-space:pre-wrap; overflow-wrap:anywhere; line-height:1.5; font-size:16px; }
.result-source { margin-top:10px; padding-top:10px; border-top:1px solid #eef2f6; font-size:12px; line-height:1.5; color:#64748b; overflow-wrap:anywhere; }
.result-source span { color:#8290a2; }
:focus-visible { outline:2px solid #0284c7; outline-offset:3px; }
@media(max-width:900px) { .result-layout { grid-template-columns:minmax(0,1fr); gap:12px; } .result-add-btn { width:100%; } }
@media(max-width:600px) { .result-labels { grid-template-columns:1fr; } }
@media(max-width:400px) { .result-card { padding:12px; } .sticker-stage { padding:7px; } .match-mark { font-size:10px; } .label-transcript { grid-template-columns:1fr; } }
</style>
