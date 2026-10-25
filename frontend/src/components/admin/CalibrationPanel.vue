<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { api } from '@/api/client';
import type { Printer } from '@/api/types';
const props = defineProps<{ printer?: Printer; sku: string; testing: boolean }>();
const emit = defineEmits<{ saved: [Printer]; test: [] }>();
const x = ref(0), y = ref(0), measuredX = ref(0), measuredY = ref(0);
const busy = ref(false), error = ref(''), message = ref('');
const enabled = computed(() => !!props.sku && !!props.printer && props.printer.model !== 'custom' && ['jscript', 'ezpl'].includes(props.printer.protocol));
const saved = computed(() => props.printer?.material_calibrations?.[props.sku] ?? { x_mm: 0, y_mm: 0 });
const dirty = computed(() => x.value !== saved.value.x_mm || y.value !== saved.value.y_mm);
watch(() => [props.printer?.id, props.sku, saved.value.x_mm, saved.value.y_mm], () => {
  x.value = saved.value.x_mm; y.value = saved.value.y_mm;
  measuredX.value = 0; measuredY.value = 0; error.value = ''; message.value = '';
}, { immediate: true });
function correctMeasured() {
  if (![x.value, y.value, measuredX.value, measuredY.value].every(v => typeof v === 'number' && Number.isFinite(v))) { error.value = 'Enter a number for both measured displacements.'; return; }
  const nextX = Math.round((x.value - measuredX.value) * 100) / 100;
  const nextY = Math.round((y.value - measuredY.value) * 100) / 100;
  if (![nextX,nextY].every(v => Number.isFinite(v) && Math.abs(v) <= 5)) { error.value = 'Correction must be within ±5 mm. Check material and feed settings.'; return; }
  x.value = nextX; y.value = nextY; measuredX.value = 0; measuredY.value = 0; error.value = '';
}
async function save() {
  if (busy.value || !props.printer || !enabled.value) return;
  if (![x.value,y.value].every(v => typeof v === 'number' && Number.isFinite(v) && Math.abs(v) <= 5)) { error.value = 'Enter corrections between −5 and +5 mm.'; return; }
  busy.value = true; error.value = ''; message.value = '';
  const printerId = props.printer.id, sku = props.sku;
  try {
    const result = await api.put<Printer>(`/api/printers/${printerId}/calibration/${encodeURIComponent(sku)}`, { x_mm: x.value, y_mm: y.value });
    emit('saved', result);
    if (props.printer?.id === printerId && props.sku === sku) message.value = 'Calibration saved. Print another test to verify alignment.';
  } catch (e) { if (props.printer?.id === printerId && props.sku === sku) error.value = e instanceof Error ? e.message : String(e); }
  finally { busy.value = false; }
}
</script>
<template>
  <details class="calibration-panel">
    <summary>Printer & material calibration <span>{{ dirty ? 'Unsaved correction' : `${saved.x_mm} / ${saved.y_mm} mm` }}</span></summary>
    <p v-if="!enabled">Select a catalog material and a Panduit printer model to calibrate this pair.</p>
    <template v-else>
      <p><strong>{{ printer?.name }} · {{ sku }}</strong><br>Shared by all templates using this printer and material. Saved separately from the template.</p>
      <ol><li>Load the matching roll and send one test label.</li><li>Compare the text position with the carrier preview; measure the displacement in mm.</li><li>Save the opposite correction and print again to verify.</li></ol>
      <div class="calibration-fields">
        <label>X correction · mm<input v-model.number="x" type="number" min="-5" max="5" step="0.01" :disabled="busy"></label>
        <label>Y correction · mm<input v-model.number="y" type="number" min="-5" max="5" step="0.01" :disabled="busy"></label>
      </div>
      <p>Positive X moves right; positive Y moves down in the carrier view. Corrections are limited to ±5 mm.</p>
      <details><summary>Calculate from a measured displacement</summary>
        <div class="calibration-fields">
          <label>Printed too far right · mm<input v-model.number="measuredX" type="number" step="0.01" :disabled="busy"></label>
          <label>Printed too far down · mm<input v-model.number="measuredY" type="number" step="0.01" :disabled="busy"></label>
        </div>
        <p>Use negative values for left/up. Measure from the latest test with the saved correction.</p>
        <button type="button" :disabled="dirty || busy" @click="correctMeasured">Calculate correction</button>
      </details>
      <div class="calibration-actions">
        <button type="button" :disabled="busy || testing || dirty" @click="emit('test')">{{ testing ? 'Sending…' : 'Send one test label' }}</button>
        <button type="button" :disabled="busy || !dirty" @click="save">{{ busy ? 'Saving…' : 'Save calibration' }}</button>
        <button type="button" :disabled="busy" @click="x = 0; y = 0">Reset to zero</button>
      </div>
      <p v-if="dirty">Save the correction before testing. The preview shows the saved profile.</p>
      <p v-if="error" role="alert" class="calibration-error">{{ error }}</p>
      <p v-if="message" role="status">{{ message }}</p>
    </template>
  </details>
</template>
<style scoped>
.calibration-panel { border:1px solid #dbe4ee; border-radius:10px; padding:14px; color:#475569; font-size:12px; }
summary { cursor:pointer; font-weight:600; } summary span { display:block; color:#64748b; font-size:11px; margin-top:3px; }
p, ol { margin:10px 0; line-height:1.5; } ol { padding-left:18px; }
.calibration-fields { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin:10px 0; }
input { display:block; width:100%; border:1px solid #cbd5e1; border-radius:6px; padding:7px; margin-top:5px; }
button { border:1px solid #cbd5e1; background:white; border-radius:6px; padding:7px 9px; cursor:pointer; } button:disabled { opacity:.5; cursor:default; }
.calibration-actions { display:flex; flex-wrap:wrap; gap:6px; margin-top:12px; }
.calibration-error { color:#b91c1c; } :focus-visible { outline:2px solid #0284c7; outline-offset:2px; }
</style>
