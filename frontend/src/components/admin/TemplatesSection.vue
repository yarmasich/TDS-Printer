<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import { adminAuthHeader, api, apiUrl } from "@/api/client";
import { readApiError } from "@/api/errors";
import { pageSizeRepair } from "@/data/templateGeometry";
import type { Printer, Template } from "@/api/types";
import { usePrinters } from "@/stores/printers";
import { useToast } from "primevue/usetoast";
import { useConfirm } from "primevue/useconfirm";

import DataTable from "primevue/datatable";
import Column from "primevue/column";
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import InputText from "primevue/inputtext";
import InputNumber from "primevue/inputnumber";
import Textarea from "primevue/textarea";
import Select from "primevue/select";

import CalibrationPanel from "@/components/admin/CalibrationPanel.vue";
import MaterialPicker from "@/components/admin/MaterialPicker.vue";
import TypographyPanel from "@/components/admin/TypographyPanel.vue";
import PrintWorkspace from "@/components/admin/PrintWorkspace.vue";

const printers = usePrinters();
const toast = useToast();
const confirm = useConfirm();

const templates = ref<Template[]>([]);
const dialogOpen = ref(false);
const editId = ref<number | null>(null);

// Live preview state — Blob URL refreshed on each form change (debounced).
const previewSrc = ref<string | null>(null);
const previewLoading = ref(false);
const previewError = ref<string | null>(null);
const testing = ref(false);
const saving = ref(false);

// Click-to-zoom: opens a full-screen Dialog with the same preview at
// max size so the operator can actually read the small text.
const zoomOpen = ref(false);

const blank = (): Omit<Template, "id"> => ({
  name: "",
  printer_id: printers.printers[0]?.id ?? 0,
  bytes_per_row: 156,
  height: 862,
  left_top: 480,
  left_bottom: 670,
  left_left: 20,
  left_right: 600,
  right_top: 480,
  right_bottom: 670,
  right_left: 648,
  right_right: 1228,
  gap_top: 20,
  gap_bottom: 20,
  gap_left: 20,
  gap_right: 20,
  left_text: "TEXT+12345",
  right_text: "TEXT+12345",
  auto_fit: false,
  min_font_pt: 4,
  letter_spacing_px: 0,
  line_spacing_px: null,
  left_pt: 7,
  right_pt: 7,
  h_align: "CENTER",
  v_align: "CENTER",
  font_name: "Microsoft Sans Serif",
  font_style: "Bold",
  left_offset: 0,
  right_offset: 0,
  scale_x: 1,
  mirror_legend: false,
  material_sku: "",
  media_height_mm: 0,
  media_gap_mm: 3,
});

const form = reactive<Omit<Template, "id">>(blank());

async function refresh() {
  templates.value = await api.get<Template[]>("/api/templates");
}
onMounted(async () => {
  try { await Promise.all([printers.loadAll(), refresh()]); }
  catch (e) { toast.add({ severity: "error", summary: "Could not load templates or printers", detail: String(e) }); }
});

const printerById = computed(
  () => new Map(printers.printers.map((p) => [p.id, p])),
);

function openCreate() {
  editId.value = null;
  Object.assign(form, blank());
  dialogOpen.value = true;
}

function openEdit(t: Template) {
  editId.value = t.id;
  const { id: _id, ...rest } = t;
  void _id;
  Object.assign(form, { material_sku: "", media_height_mm: 0, media_gap_mm: 3 }, rest);
  dialogOpen.value = true;
}

function openDuplicate(t: Template) {
  editId.value = null; // saving will POST a new row
  const { id: _id, ...rest } = t;
  void _id;
  Object.assign(form, { material_sku: "", media_height_mm: 0, media_gap_mm: 3 }, rest);
  // Auto-suffix until the name is unique among existing templates.
  const taken = new Set(templates.value.map((x) => x.name));
  let candidate = `${t.name} copy`;
  let n = 2;
  while (taken.has(candidate)) candidate = `${t.name} copy ${n++}`;
  form.name = candidate;
  dialogOpen.value = true;
}

async function save() {
  if (saving.value || testing.value) return;
  saving.value = true;
  try {
    if (editId.value) {
      await api.put<Template>(`/api/templates/${editId.value}`, form);
    } else {
      await api.post<Template>("/api/templates", form);
    }
    dialogOpen.value = false;
    toast.add({ severity: "success", summary: "Saved", life: 2000 });
    try { await refresh(); }
    catch (e) { toast.add({ severity: "warn", summary: "Saved, but the list could not refresh", detail: String(e) }); }
  } catch (e: unknown) {
    toast.add({
      severity: "error",
      summary: "Save failed",
      detail: e instanceof Error ? e.message : String(e),
    });
  } finally { saving.value = false; }
}

function remove(t: Template) {
  confirm.require({
    message: `Delete template "${t.name}"?`,
    accept: async () => {
      try {
        await api.delete(`/api/templates/${t.id}`);
        templates.value = templates.value.filter(template => template.id !== t.id);
      } catch (e) { toast.add({ severity: "error", summary: "Delete failed", detail: String(e) }); }
    },
  });
}

async function openPreview(t: Template) {
  const q = new URLSearchParams({
    template_id: String(t.id),
    left_text: t.left_text,
    right_text: t.right_text,
  });
  try {
    const res = await fetch(`${apiUrl("/api/print/preview")}?${q}`, {
      headers: adminAuthHeader(),
    });
    if (!res.ok) throw new Error(await readApiError(res));
    const blob = await res.blob();
    window.open(URL.createObjectURL(blob), "_blank", "noopener");
  } catch (e: unknown) {
    toast.add({
      severity: "error",
      summary: "Preview failed",
      detail: e instanceof Error ? e.message : String(e),
    });
  }
}

// ──────────────── live preview ────────────────

// Held outside reactive state so the watcher's debounce token doesn't
// itself trigger re-runs.
let previewTimer: number | null = null;
let previewSeq = 0;

function clearPreview() {
  if (previewSrc.value) {
    URL.revokeObjectURL(previewSrc.value);
    previewSrc.value = null;
  }
  previewError.value = null;
}

function calibrationSaved(printer: Printer) {
  const index = printers.printers.findIndex(p => p.id === printer.id);
  if (index >= 0) printers.printers[index] = printer;
  if (dialogOpen.value && form.printer_id === printer.id) refreshPreview();
}

async function refreshPreview() {
  const seq = ++previewSeq;
  if (!dialogOpen.value) return;
  // Skip if the form is half-filled — printer must be picked for the
  // template to even validate server-side.
  if (!form.printer_id) {
    clearPreview();
    previewLoading.value = false;
    return;
  }
  previewLoading.value = true;
  previewError.value = null;
  try {
    const res = await fetch(apiUrl("/api/print/preview-draft"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...adminAuthHeader(),
      },
      // Preserve the full 300-DPI canvas so guides match the server raster.
      body: JSON.stringify({ template: form, printer_id: form.printer_id, crop: false }),
    });
    if (seq !== previewSeq) return; // a newer call already ran
    if (!res.ok) {
      const detail = await readApiError(res);
      if (seq !== previewSeq) return;
      // Keep the last successful frame retained during width-slider edits.
      // The workspace marks it stale; rejected settings are never shown as valid.
      previewError.value = detail;
      return;
    }
    const blob = await res.blob();
    if (seq !== previewSeq) return;
    const url = URL.createObjectURL(blob);
    if (previewSrc.value) URL.revokeObjectURL(previewSrc.value);
    previewSrc.value = url;
  } catch (e) {
    if (seq === previewSeq) {
      previewError.value = e instanceof Error ? e.message : String(e);
    }
  } finally {
    if (seq === previewSeq) previewLoading.value = false;
  }
}

watch(
  () => ({ ...form }),
  (current, previous) => {
    if (!dialogOpen.value) return;
    ++previewSeq;
    // A slider emits continuously: retain its last rendered frame during
    // debounce. Geometry changes still clear it to avoid misleading guides.
    const widthOnly = previous && Object.keys(current).every(key =>
      key === 'scale_x' || current[key as keyof typeof current] === previous[key as keyof typeof previous],
    );
    if (!widthOnly) clearPreview();
    previewError.value = null;
    previewLoading.value = true;
    if (previewTimer !== null) window.clearTimeout(previewTimer);
    previewTimer = window.setTimeout(() => {
      previewTimer = null;
      refreshPreview();
    }, 350);
  },
  { deep: true },
);

watch(dialogOpen, (open) => {
  if (open) {
    refreshPreview();
  } else {
    zoomOpen.value = false;
    ++previewSeq;
    previewLoading.value = false;
    if (previewTimer !== null) {
      window.clearTimeout(previewTimer);
      previewTimer = null;
    }
    clearPreview();
  }
});

onUnmounted(() => {
  ++previewSeq;
  if (previewTimer !== null) window.clearTimeout(previewTimer);
  clearPreview();
});

// ──────────────── test print ────────────────

async function testPrint() {
  if (testing.value || saving.value) return;
  if (!form.printer_id) {
    toast.add({
      severity: "warn",
      summary: "Pick a printer first",
      life: 2500,
    });
    return;
  }
  testing.value = true;
  try {
    const res = await api.post<{ ok: boolean; log_id: number }>(
      "/api/print/test",
      { template: form, printer_id: form.printer_id, reason: "TEST" },
    );
    toast.add({
      severity: "success",
      summary: `Test printed (log #${res.log_id})`,
      life: 2500,
    });
  } catch (e: unknown) {
    toast.add({
      severity: "error",
      summary: "Test print failed",
      detail: e instanceof Error ? e.message : String(e),
    });
  } finally {
    testing.value = false;
  }
}


function applyMaterial(geometry: Partial<Template>) {
  Object.assign(form, geometry);
  if (!form.name) form.name = form.material_sku;
  toast.add({ severity: "info", summary: "Material applied to draft", detail: "Review preview and save to keep these settings.", life: 3500 });
}

// Repair legacy pages without replacing calibrated text rectangles.
const suggestedPage = computed(() => pageSizeRepair(form));
function repairPageSize() {
  if (suggestedPage.value) Object.assign(form, suggestedPage.value);
}

// SKU used by the legacy page-size repair hint.
const presetSku = computed(() => {
  const m = (form.name || "").match(/^([RS])(\d{3})[xX](\d{3})/i);
  return m ? `${m[1]!.toUpperCase()}${m[2]}X${m[3]}` : null;
});

</script>

<template>
  <section class="bg-white border border-slate-200 rounded-2xl p-5 shadow-sm">
    <div class="flex items-center justify-between mb-3">
      <h2 class="text-lg font-bold">
        Templates <span class="text-slate-400">({{ templates.length }})</span>
      </h2>
      <Button
        label="Add template"
        icon="pi pi-plus"
        size="small"
        :disabled="printers.printers.length === 0"
        @click="openCreate"
      />
    </div>

    <p v-if="printers.printers.length === 0" class="text-sm text-slate-500">
      Create a printer first.
    </p>

    <DataTable
      :value="templates"
      data-key="id"
      striped-rows
      empty-message="No templates"
      size="small"
    >
      <Column field="name" header="Name" />
      <Column header="Printer">
        <template #body="{ data }">
          <span v-if="printerById.get(data.printer_id)">
            {{ printerById.get(data.printer_id)?.name }}
            <span class="text-slate-400">
              ({{ printerById.get(data.printer_id)?.ip }}:{{
                printerById.get(data.printer_id)?.port
              }})
            </span>
          </span>
          <span v-else class="text-red-600">⚠ missing</span>
        </template>
      </Column>
      <Column header="Geometry">
        <template #body="{ data }">
          {{ data.bytes_per_row }}×{{ data.height }}
        </template>
      </Column>
      <Column header="Font">
        <template #body="{ data }">
          {{ data.font_name }} {{ data.font_style }}
        </template>
      </Column>
      <Column header="" :style="{ width: '220px' }">
        <template #body="{ data }">
          <div class="flex gap-1 justify-end">
            <Button
              icon="pi pi-eye"
              size="small"
              text
              severity="secondary"
              aria-label="Preview"
              @click="openPreview(data)"
            />
            <Button
              icon="pi pi-pencil"
              size="small"
              text
              aria-label="Edit"
              @click="openEdit(data)"
            />
            <Button
              icon="pi pi-copy"
              size="small"
              text
              severity="secondary"
              aria-label="Duplicate"
              @click="openDuplicate(data)"
            />
            <Button
              icon="pi pi-trash"
              size="small"
              severity="danger"
              text
              aria-label="Delete"
              @click="remove(data)"
            />
          </div>
        </template>
      </Column>
    </DataTable>

    <Dialog
      v-model:visible="dialogOpen"
      modal
      :header="editId ? 'Edit template' : 'Add template'"
      :style="{ width: '88rem', maxWidth: '96vw' }"
      :closable="!saving"
      :close-on-escape="!saving"
      content-class="template-dialog"
    >
      <fieldset class="template-editor" :disabled="saving">
        <div class="editor-identity">
        <fieldset class="grid grid-cols-2 gap-3">
          <legend class="text-xs font-bold text-slate-500 uppercase mb-1 col-span-2">
            Template & printer
          </legend>
          <div>
            <label class="block text-xs font-bold text-slate-600 mb-1" for="template-name">Template name</label>
            <InputText id="template-name" v-model="form.name" class="w-full" />

          </div>
          <div>
            <label class="block text-xs font-bold text-slate-600 mb-1" for="template-printer">Printer</label>
            <Select
              input-id="template-printer" v-model="form.printer_id"
              :options="printers.printers"
              option-label="name"
              option-value="id"
              class="w-full"
            />
            <p v-if="printerById.get(form.printer_id)?.model && printerById.get(form.printer_id)?.model !== 'custom'" class="printer-ready">
              {{ printerById.get(form.printer_id)?.model }} · {{ printerById.get(form.printer_id)?.dpi }} dpi
            </p>
            <p v-else class="printer-setup-note" role="status">
              To use catalog materials, set this printer’s model in Admin → Printers.
              You can still edit this template manually.
            </p>
          </div>
        </fieldset>

        </div>
        <div class="editor-workspace">
          <aside class="editor-preview">
            <div class="preview-caption"><span>PRINT WORKSPACE</span><span>{{ form.material_sku || 'Custom layout' }}</span></div>
        <fieldset class="preview-pane">
          <legend class="text-xs font-bold text-slate-500 uppercase mb-1">
            Live preview
            <span class="text-slate-400 font-normal normal-case">
              ({{ form.bytes_per_row * 8 }}×{{ form.height }}px)
            </span>
          </legend>
          <div class="zoomable" role="button" tabindex="0" aria-label="Open print workspace"
            @click="!saving && (zoomOpen = true)" @keydown.enter="!saving && (zoomOpen = true)" @keydown.space.prevent="!saving && (zoomOpen = true)">
            <PrintWorkspace :template="form" :src="previewSrc" :loading="previewLoading" :error="previewError" compact />
          </div>
          <div v-if="suggestedPage" class="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm" role="status">
            <p>The text areas exceed the current page. {{ presetSku }} uses
              {{ suggestedPage.bytes_per_row * 8 }}×{{ suggestedPage.height }} px.
              Update the page size while keeping your text positions and font settings, then save.</p>
            <Button class="mt-2" label="Fix page size" severity="warn" @click="repairPageSize" />
          </div>
        </fieldset>

            <div class="preview-edit-action"><Button label="Edit text & typography" icon="pi pi-pencil" @click="zoomOpen = true" /></div>
          </aside>
          <div class="editor-settings">
            <section class="editor-card">
        <MaterialPicker :sku="form.material_sku" :enabled="!!printerById.get(form.printer_id)?.model && printerById.get(form.printer_id)?.model !== 'custom'" @apply="applyMaterial" />
            </section>
            <CalibrationPanel :printer="printerById.get(form.printer_id)" :sku="form.material_sku" :testing="testing" @saved="calibrationSaved" @test="testPrint" />
            <details class="editor-card editor-advanced">
              <summary>Advanced layout<span>Feed, page size and text areas</span></summary>
              <div class="advanced-content">
        <fieldset v-if="['jscript', 'ezpl'].includes(printerById.get(form.printer_id)?.protocol ?? '')" class="grid grid-cols-2 gap-3">
          <legend class="text-xs font-bold text-slate-500 uppercase mb-1 col-span-2">Material feed</legend>
          <div>
            <label class="block text-xs font-bold text-slate-600 mb-1">Label height (mm; 0 = automatic)</label>
            <InputNumber v-model="form.media_height_mm" :min="0" :max="2000" :max-fraction-digits="3" class="w-full" />
          </div>
          <div>
            <label class="block text-xs font-bold text-slate-600 mb-1">Gap between labels (mm)</label>
            <InputNumber v-model="form.media_gap_mm" :min="0" :max="100" :max-fraction-digits="3" class="w-full" />
          </div>
          <p class="col-span-2 text-xs text-slate-500">Use the dimensions of the loaded material.
            Automatic height preserves the existing feed setting. Gap detection remains enabled.</p>
        </fieldset>

        <fieldset class="grid grid-cols-2 gap-3">
          <legend class="text-xs font-bold text-slate-500 uppercase mb-1 col-span-2">
            Bitmap
          </legend>
          <div>
            <label class="block text-xs font-bold text-slate-600 mb-1">Bytes/row</label>
            <InputNumber v-model="form.bytes_per_row" :use-grouping="false" class="w-full" />
          </div>
          <div>
            <label class="block text-xs font-bold text-slate-600 mb-1">Height (px)</label>
            <InputNumber v-model="form.height" :use-grouping="false" class="w-full" />
          </div>
        </fieldset>

        <fieldset class="grid grid-cols-2 md:grid-cols-4 gap-3">
          <legend class="text-xs font-bold text-slate-500 uppercase mb-1 col-span-2 md:col-span-4">
            Left rectangle (edges)
          </legend>
          <div><label class="block text-xs text-slate-600">Top</label>
            <InputNumber v-model="form.left_top" :min-fraction-digits="0" class="w-full" /></div>
          <div><label class="block text-xs text-slate-600">Bottom</label>
            <InputNumber v-model="form.left_bottom" :min-fraction-digits="0" class="w-full" /></div>
          <div><label class="block text-xs text-slate-600">Left</label>
            <InputNumber v-model="form.left_left" :min-fraction-digits="0" class="w-full" /></div>
          <div><label class="block text-xs text-slate-600">Right</label>
            <InputNumber v-model="form.left_right" :min-fraction-digits="0" class="w-full" /></div>
        </fieldset>

        <fieldset class="grid grid-cols-2 md:grid-cols-4 gap-3">
          <legend class="text-xs font-bold text-slate-500 uppercase mb-1 col-span-2 md:col-span-4">
            Right rectangle (edges)
          </legend>
          <div><label class="block text-xs text-slate-600">Top</label>
            <InputNumber v-model="form.right_top" :min-fraction-digits="0" class="w-full" /></div>
          <div><label class="block text-xs text-slate-600">Bottom</label>
            <InputNumber v-model="form.right_bottom" :min-fraction-digits="0" class="w-full" /></div>
          <div><label class="block text-xs text-slate-600">Left</label>
            <InputNumber v-model="form.right_left" :min-fraction-digits="0" class="w-full" /></div>
          <div><label class="block text-xs text-slate-600">Right</label>
            <InputNumber v-model="form.right_right" :min-fraction-digits="0" class="w-full" /></div>
        </fieldset>

        <fieldset class="grid grid-cols-2 md:grid-cols-4 gap-3">
          <legend class="text-xs font-bold text-slate-500 uppercase mb-1 col-span-2 md:col-span-4">
            Gap (px)
          </legend>
          <div><label class="block text-xs text-slate-600">Top</label>
            <InputNumber v-model="form.gap_top" class="w-full" /></div>
          <div><label class="block text-xs text-slate-600">Bottom</label>
            <InputNumber v-model="form.gap_bottom" class="w-full" /></div>
          <div><label class="block text-xs text-slate-600">Left</label>
            <InputNumber v-model="form.gap_left" class="w-full" /></div>
          <div><label class="block text-xs text-slate-600">Right</label>
            <InputNumber v-model="form.gap_right" class="w-full" /></div>
        </fieldset>


              </div>
            </details>
          </div>
        </div>
      </fieldset>

      <template #footer>
        <div class="editor-footer">
          <Button
            label="Send test print"
            icon="pi pi-bolt"
            severity="secondary"
            :loading="testing"
            :disabled="!form.printer_id || testing || saving"
            @click="testPrint"
          />
          <div class="flex gap-2">
            <Button label="Cancel" severity="secondary" :disabled="saving" @click="dialogOpen = false" />
            <Button :label="editId ? 'Save' : 'Create'" :loading="saving" :disabled="saving || testing" @click="save" />
          </div>
        </div>
      </template>
    </Dialog>

    <!-- Full-size preview zoom + live tweak panel. Same ``form`` reactive
         drives the preview watcher, so every change here re-renders the
         schematic with the debounced refresh. Renders on top of the
         template editor (PrimeVue handles nested Dialog stacking via
         teleport). -->
    <Dialog
      v-model:visible="zoomOpen"
      modal
      dismissable-mask
      :header="`Print workspace · ${form.name || 'Untitled template'}`"
      :style="{ width: '1120px', maxWidth: '96vw', maxHeight: '90vh' }"
      content-class="zoom-dialog"
    >
      <div class="zoom-layout">
        <div class="zoom-preview">
          <PrintWorkspace :template="form" :src="previewSrc" :loading="previewLoading" :error="previewError" />

        </div>

        <aside class="zoom-controls">
          <div class="zoom-card"><TypographyPanel :model="form" /></div>
          <details class="zoom-card" open>
            <summary class="zoom-card-title">Label content</summary>
            <div class="grid grid-cols-2 gap-2">
              <label class="zoom-field-label">Left<Textarea v-model="form.left_text" :rows="2" class="w-full" /></label>
              <label class="zoom-field-label">Right<Textarea v-model="form.right_text" :rows="2" class="w-full" /></label>
            </div>
            <button type="button" class="copy-label-text" @click="form.right_text = form.left_text">Copy left text → right</button>
          </details>
        </aside>
      </div>
      <template #footer>
        <span class="workspace-draft-note">Changes stay in the draft. Save in the template editor to keep them.</span>
        <Button label="Done" icon="pi pi-check" @click="zoomOpen = false" />
      </template>
    </Dialog>
  </section>
</template>

<!-- PrimeVue Dialog teleports its content to <body>, so scoped styles
     can't reach inside. This block is intentionally unscoped — every
     selector is anchored on `.template-dialog` so we don't leak styles. -->
<style>
.template-dialog .p-inputtext,
.template-dialog .p-inputnumber,
.template-dialog .p-inputnumber-input,
.template-dialog .p-textarea,
.template-dialog .p-select,
.template-dialog .p-iconfield,
.zoom-dialog .p-inputtext,
.zoom-dialog .p-inputnumber,
.zoom-dialog .p-inputnumber-input,
.zoom-dialog .p-textarea,
.zoom-dialog .p-select,
.zoom-dialog .p-iconfield {
  width: 100% !important;
  min-width: 0 !important;
}
.template-dialog .p-textarea {
  resize: vertical;
  min-height: 5.5rem;
}
.template-dialog fieldset {
  border: 0;
  padding: 0;
  margin: 0;
}
.template-dialog legend {
  padding: 0;
}

.template-dialog .preview-pane {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.template-dialog .shape-frame {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px;
  /* Two labels per row need more breathing room than one. Centred so
     the schematic doesn't crowd the form fields below. */
  max-width: 620px;
  margin: 0 auto;
}
.template-dialog .zoomable {
  position: relative;
  cursor: zoom-in;
  transition: box-shadow 0.15s, transform 0.15s;
}
.template-dialog .zoomable:hover,
.template-dialog .zoomable:focus-visible {
  box-shadow: 0 0 0 3px rgba(2, 132, 199, 0.35);
  outline: none;
}
.template-dialog .zoom-hint {
  position: absolute;
  top: 8px;
  right: 8px;
  background: rgba(15, 23, 42, 0.55);
  color: #fff;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  pointer-events: none;
}

/* ─── full-screen zoom modal ─── */
.zoom-dialog {
  padding: 16px !important;
}
.zoom-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: 16px;
  align-items: start;
}
@media (max-width: 900px) {
  /* Stack on small screens — preview on top, controls below. */
  .zoom-layout {
    grid-template-columns: 1fr;
  }
}
.zoom-preview {
  /* Make the preview claim the full column width so the schematic can
     stretch as the dialog grows. */
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.zoom-geometry {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
}
.zoom-controls {
  display: flex;
  flex-direction: column;
  gap: 12px;
  /* Stay readable but cap the height on tall monitors so the panel doesn't
     stretch into a sparse column. */
  max-height: 80vh;
  overflow-y: auto;
  padding-right: 4px;
}
.zoom-card {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px;
  background: #f8fafc;
  /* Don't let PrimeVue's wider InputNumber children blow the card out of
     the column. ``min-width: 0`` lets flex/grid children shrink properly. */
  min-width: 0;
}
.zoom-card-title {
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin: 0 0 8px;
}
.zoom-field-label {
  display: block;
  font-size: 11px;
  color: #475569;
  margin-bottom: 2px;
}
.zoom-shape {
  /* Let LabelShape stretch to the full dialog width. */
  width: 100%;
}
.zoom-bitmap {
  display: flex;
  align-items: center;
  justify-content: center;
  background:
    repeating-conic-gradient(#f1f5f9 0 25%, #ffffff 0 50%) 0 0/24px 24px;
  border: 1px dashed #cbd5e1;
  border-radius: 8px;
  padding: 16px;
  min-height: 60vh;
  position: relative;
}
.zoom-bitmap img {
  max-width: 100%;
  max-height: 80vh;
  image-rendering: pixelated;
  background: #ffffff;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.12);
}
.template-dialog .preview-frame {
  position: relative;
  min-height: 180px;
  display: flex;
  align-items: center;
  justify-content: center;
  background:
    repeating-conic-gradient(#f1f5f9 0 25%, #ffffff 0 50%) 0 0/16px 16px;
  border: 1px dashed #cbd5e1;
  border-radius: 8px;
  overflow: hidden;
  padding: 8px;
}
.template-dialog .preview-img {
  /* Scale to whatever the dialog gives us, preserve aspect ratio.
     The dialog is ~52rem wide, so a 1248×862 label renders ~720×500 — big
     enough to actually see what's on it without scrolling the page. */
  width: 100%;
  height: auto;
  /* Keep printed pixels crisp at any zoom — these are 1-bit thermal rasters. */
  image-rendering: pixelated;
  background: #ffffff;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
}
.template-dialog .preview-spinner {
  position: absolute;
  width: 38px;
  height: 38px;
}
.template-dialog .preview-msg {
  font-size: 13px;
  padding: 24px 12px;
  text-align: center;
}
.template-dialog .template-editor { display: grid; gap: 1.25rem; }
.template-dialog .editor-identity { padding: 1rem 1.25rem; border: 1px solid #dce4ed; border-radius: 12px; background: #fff; }
.template-dialog .editor-identity legend { margin-bottom: .75rem; }
.template-dialog .editor-workspace { display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr); gap: 1.5rem; align-items: start; }
.template-dialog .editor-preview { position: sticky; top: 0; min-width: 0; padding: 1.25rem; border: 1px solid #dbe4eb; border-radius: 14px; background: #edf2f5; }
.template-dialog .preview-caption { display: flex; justify-content: space-between; flex-wrap: wrap; gap: .5rem; margin-bottom: 1.5rem; color: #536779; font-size: 11px; letter-spacing: .06em; }
.template-dialog .preview-caption span:last-child { font-family: ui-monospace, monospace; letter-spacing: 0; }
.template-dialog .editor-settings { min-width: 0; display: grid; gap: 1rem; }
.template-dialog .editor-card { min-width: 0; border: 1px solid #dce4ed; border-radius: 12px; padding: 1.1rem; background: #fff; }
.template-dialog .editor-text { display: grid; gap: 1.5rem; }
.template-dialog .editor-text legend { margin-bottom: .65rem; }
.template-dialog .shape-frame { width: 100%; max-width: none; margin: 0; padding: 1rem; background: #fff; box-sizing: border-box; }
.template-dialog .shape-frame svg { display: block; width: 100%; height: auto; }
.template-dialog .preview-frame { min-height: 300px; padding: 1rem; }
.template-dialog .preview-footnote { margin: .8rem 0 0; color: #64748b; text-align: center; font-size: 12px; }
.template-dialog .printer-ready { color: #047857; font-size: 12px; margin-top: 6px; }
.template-dialog .printer-setup-note { color: #9a5411; font-size: 12px; margin-top: 6px; line-height: 1.5; }
.template-dialog .editor-advanced summary { cursor: pointer; font-weight: 600; color: #334155; }
.template-dialog .editor-advanced summary span { display: block; margin-top: 4px; font-size: 12px; font-weight: 400; color: #64748b; }
.template-dialog .editor-advanced summary:focus-visible { outline: 2px solid #059669; outline-offset: 4px; }
.template-dialog .advanced-content { display: grid; gap: 1.25rem; padding-top: 1.5rem; }
.editor-footer { display: flex; justify-content: space-between; flex-wrap: wrap; gap: .75rem; width: 100%; padding-top: .5rem; }
@media (max-width: 980px) {
  .template-dialog .editor-workspace { grid-template-columns: minmax(0, 1fr); }
  .template-dialog .editor-preview { position: static; }
  .template-dialog .shape-frame { max-width: 640px; margin: auto; }
}
@media (max-width: 540px) {
  .template-dialog .editor-identity > fieldset { grid-template-columns: minmax(0, 1fr); }
  .template-dialog .editor-identity legend { grid-column: 1; }
  .template-dialog .editor-preview, .template-dialog .editor-card, .template-dialog .editor-identity { padding: .8rem; }
  .template-dialog .preview-frame { min-height: 200px; }
  .editor-footer > .p-button { flex: 1 1 100%; }
  .editor-footer > div { width: 100%; justify-content: flex-end; }
}
</style>

<style>
.workspace-mirror { display:flex; align-items:center; gap:8px; font-size:12px; margin-bottom:10px; }
.workspace-advanced { padding:16px; background:#f8fafc; border:1px solid #dbe4eb; border-radius:10px; }
.workspace-advanced summary { cursor:pointer; font-size:13px; font-weight:600; color:#475569; padding:4px 0; }
.workspace-advanced[open] summary { margin-bottom:12px; }
.workspace-draft-note { margin-right:auto; color:#64748b; font-size:12px; text-align:left; }
@media (max-width:900px) { .zoom-controls { max-height:none; overflow:visible; } }
</style>

<style>
.zoom-dialog { max-height:72vh; overflow-y:auto; }
.zoom-layout { grid-template-columns:minmax(0,1fr) 320px; gap:12px; }
.zoom-controls { max-height:none; overflow:visible; padding:0; gap:10px; }
.zoom-dialog .workspace-toolbar { padding:10px 12px; }
.zoom-dialog .workspace-stage { padding:14px; }
.zoom-dialog .manufacturer-reference { padding:10px 12px; }
.zoom-dialog .manufacturer-reference dl { margin:8px 0; }
.zoom-dialog .workspace-note { font-size:10px; padding:8px 12px; }
.zoom-dialog .workspace-toolbar strong { font-size:13px; }
.zoom-dialog .workspace-toolbar small { font-size:10px; }
.zoom-dialog .zoom-card { padding:10px; }
.copy-label-text { color:#0369a1; font-size:11px; margin-top:8px; cursor:pointer; }
@media(max-width:850px) { .zoom-layout { grid-template-columns:1fr; } }
</style>

<style>
.template-dialog .preview-edit-action { display:flex; justify-content:center; margin-top:12px; }
</style>
