<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, reactive, ref, watch } from 'vue';
import { api, apiUrl, adminAuthHeader } from '@/api/client';
import { readApiError } from '@/api/errors';
import type { Printer } from '@/api/types';
import { printerQrDefaults, shouldApplyPrinterDefaults } from '@/data/printerSettings';
import { QrPrintIntent, qrOutcome } from '@/data/qrPrintIntent';
import Button from 'primevue/button';

const printers = ref<Printer[]>([]);
const form = reactive({ printer_id: 0, media: 'DK-2246', length_mm: 60, scan: '', code: '', description: '', reference: '' });
const mediaDirty = ref(false);
const selectedPrinter = computed(() => printers.value.find(p => p.id === form.printer_id));
const configuredDefaults = computed(() => printerQrDefaults(selectedPrinter.value));
const busy = ref(false);
const error = ref('');
const loadError = ref('');
const message = ref('');
const checked = ref(false);
const image = ref('');
const previewBody = ref('');
const activeIntent = ref(false);
const needsCheck = ref(false);
const intent = new QrPrintIntent();
let generation = 0;
let printerLoadGeneration = 0;
const currentBody = computed(() => JSON.stringify(form));
const canSend = computed(() => !!image.value && previewBody.value === currentBody.value && !busy.value);

function clearPreview() {
  generation++;
  if (image.value) URL.revokeObjectURL(image.value);
  image.value = '';
  previewBody.value = '';
}
watch(() => form.printer_id, (next, previous) => {
  if (shouldApplyPrinterDefaults(previous, next, mediaDirty.value, !!image.value || activeIntent.value || busy.value)) {
    Object.assign(form, printerQrDefaults(printers.value.find(p => p.id === next)));
  }
}, { flush: 'sync' });
watch(currentBody, clearPreview);
onBeforeUnmount(() => { printerLoadGeneration++; clearPreview(); });
onDeactivated(() => { printerLoadGeneration++; });
onActivated(async () => {
  const seq = ++printerLoadGeneration;
  if (busy.value || activeIntent.value) return;
  loadError.value = '';
  try {
    const loaded = await api.get<Printer[]>('/api/printers');
    if (seq !== printerLoadGeneration || busy.value || activeIntent.value) return;
    printers.value = loaded.filter(p => p.protocol === 'brother_ql' && p.model === 'QL-1110NWBc');
    if (!printers.value.some(p => p.id === form.printer_id)) {
      form.printer_id = printers.value[0]?.id ?? 0;
    }
  } catch (e) {
    if (seq === printerLoadGeneration && !busy.value && !activeIntent.value) loadError.value = String(e);
  }
});

async function preview() {
  const body = currentBody.value;
  clearPreview();
  const seq = generation;
  busy.value = true; error.value = ''; message.value = '';
  try {
    const response = await fetch(apiUrl('/api/qr-labels/preview'), { method: 'POST', headers: { ...adminAuthHeader(), 'Content-Type': 'application/json' }, body });
    if (!response.ok) throw new Error(await readApiError(response));
    const blob = await response.blob();
    if (seq !== generation || body !== currentBody.value) return;
    image.value = URL.createObjectURL(blob); previewBody.value = body;
  } catch (e) { if (seq === generation) error.value = e instanceof Error ? e.message : String(e); }
  finally { busy.value = false; }
}

async function send() {
  if (!canSend.value) return;
  busy.value = true; error.value = ''; message.value = '';
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 60000);
  try {
    const frozen = intent.begin(JSON.parse(previewBody.value));
    const response = await fetch(apiUrl('/api/qr-labels'), { method: 'POST', signal: controller.signal,
      headers: { ...adminAuthHeader(), 'Content-Type': 'application/json', 'Idempotency-Key': frozen.key }, body: frozen.body });
    const result = await response.json();
    const detail = response.ok ? result : result.detail;
    const code = qrOutcome(response.ok, result);
    intent.record(code);
    if (!response.ok) throw new Error(detail?.message || 'Request failed. Check the printer before starting another attempt.');
    if (code !== 'sent') throw new Error('No delivery result received. Check the same request before starting another attempt.');
    message.value = `${result.message} History #${result.log_id}. Repeating this request returns the same result without sending another label.`;
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    clearTimeout(timer); busy.value = false;
    activeIntent.value = intent.active; needsCheck.value = intent.requiresCheck;
  }
}

function nextLabel() {
  try {
    intent.newAttempt(checked.value);
    activeIntent.value = false; needsCheck.value = false; checked.value = false;
    error.value = ''; message.value = ''; clearPreview();
  } catch (e) { error.value = String(e); }
}
</script>

<template>
  <section class="qr-workspace bg-surface border border-edge rounded-2xl p-5 shadow-sm">
    <h2 class="text-2xl font-bold">QR labels</h2>
    <p class="text-ink-2 mt-2">Brother QL-1110NWBc · one label per request. Select the roll physically loaded in the printer.</p>
    <p v-if="loadError" role="alert" class="text-danger mt-3">{{ loadError }}</p>
    <p v-if="!printers.length" class="mt-3">Add a QL-1110NWBc in Printers to begin.</p>
    <form @submit.prevent="preview">
      <fieldset :disabled="busy || activeIntent" class="qr-fields">
        <label>Printer<select v-model.number="form.printer_id" required><option :value="0" disabled>Select printer</option><option v-for="p in printers" :key="p.id" :value="p.id">{{ p.name }}</option></select></label>
        <label>Loaded roll<select v-model="form.media" @change="mediaDirty = true"><option value="DK-2246">DK-2246 · 103 mm continuous</option><option value="DK-2205">DK-2205 · 62 mm continuous</option></select></label>
        <label>Label length (mm)<input v-model.number="form.length_mm" @input="mediaDirty = true" type="number" min="30" max="200" step="1" required /></label>
        <label class="qr-wide">QR contents · scanned exactly<input v-model="form.scan" maxlength="512" required placeholder="Pallet code, item barcode or asset tag" /></label>
        <label>Caption (optional)<input v-model="form.code" maxlength="80" /></label>
        <label>Description (optional)<input v-model="form.description" maxlength="240" /></label>
        <label class="qr-wide">Source reference (optional, history only)<input v-model="form.reference" maxlength="200" /></label>
      </fieldset>
      <p class="text-sm text-ink-3 mt-3">Configured defaults: {{ configuredDefaults.media }} · {{ configuredDefaults.length_mm }} mm. Confirm the loaded roll before printing.</p>
      <div class="flex flex-wrap gap-3 mt-4">
        <Button type="submit" label="Preview label" icon="pi pi-eye" :disabled="busy || !form.printer_id || !form.scan" />
        <Button type="button" :label="activeIntent ? 'Check same request' : 'Send one label'" icon="pi pi-print" :disabled="!canSend" :loading="busy" @click="send" />
      </div>
    </form>
    <p v-if="error" role="alert" class="text-danger mt-4">{{ error }}</p>
    <p v-if="message" role="status" class="text-ink-2 mt-4">{{ message }}</p>
    <div v-if="activeIntent" class="qr-next">
      <label v-if="needsCheck" class="qr-check"><input v-model="checked" type="checkbox" />I checked the physical label and want to start a new label or another copy.</label>
      <Button label="Start new attempt" severity="secondary" :disabled="busy || (needsCheck && !checked)" @click="nextLabel" />
    </div>
    <figure v-if="image" class="qr-preview"><img :src="image" alt="QR label preview" /><figcaption>{{ form.media }} · {{ form.length_mm }} mm long · cut after label</figcaption></figure>
    <p class="text-sm text-ink-3 mt-4">Sent means data was transferred. Loaded media and physical output are not confirmed automatically. Before use, disable the old FloorHub relay for this printer so only TDS-Printer controls it.</p>
  </section>
</template>

<style scoped>
.qr-fields { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; margin-top:24px; min-width:0; }
.qr-fields label { display:flex; flex-direction:column; gap:6px; font-size:14px; font-weight:600; min-width:0; }
.qr-fields input,.qr-fields select { width:100%; min-width:0; min-height:44px; padding:10px; border:1px solid var(--tds-edge-strong); border-radius:6px; background:var(--tds-surface); color:var(--tds-ink); font-size:16px; }
.qr-fields input:focus-visible,.qr-fields select:focus-visible { outline:2px solid var(--tds-accent); outline-offset:2px; }
.qr-wide { grid-column:1/-1; }
.qr-next { display:grid; gap:12px; margin-top:20px; }
.qr-check { display:flex; align-items:center; gap:10px; min-height:44px; }
.qr-check input { width:20px; height:20px; }
.qr-preview { margin:24px 0 0; padding:16px; background:var(--tds-stage-muted); color:var(--tds-stage-ink); border:1px solid var(--tds-stage-edge); }
.qr-preview img { display:block; max-width:100%; max-height:560px; width:auto; margin:auto; image-rendering:pixelated; }
.qr-preview figcaption { margin-top:12px; text-align:center; color:var(--tds-stage-ink-2); font-size:14px; }
@media(max-width:640px) { .qr-fields { grid-template-columns:1fr; } }
</style>
