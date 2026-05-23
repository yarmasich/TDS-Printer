<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import { adminAuthHeader, api, apiUrl } from "@/api/client";
import type { Template } from "@/api/types";
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
import ProgressSpinner from "primevue/progressspinner";
import LabelShape from "@/components/admin/LabelShape.vue";
import AlignmentGrid from "@/components/admin/AlignmentGrid.vue";
import {
  parsePanduitSku,
  findTemplatePreset,
  TEMPLATE_PRESET_SKUS,
} from "@/data/panduit";

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
  left_pt: 7,
  right_pt: 7,
  h_align: "CENTER",
  v_align: "CENTER",
  font_name: "Microsoft Sans Serif",
  font_style: "Bold",
  left_offset: 0,
  right_offset: 0,
  scale_x: 1,
});

const form = reactive<Omit<Template, "id">>(blank());

async function refresh() {
  templates.value = await api.get<Template[]>("/api/templates");
}
onMounted(async () => {
  await Promise.all([printers.loadAll(), refresh()]);
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
  Object.assign(form, rest);
  dialogOpen.value = true;
}

function openDuplicate(t: Template) {
  editId.value = null; // saving will POST a new row
  const { id: _id, ...rest } = t;
  void _id;
  Object.assign(form, rest);
  // Auto-suffix until the name is unique among existing templates.
  const taken = new Set(templates.value.map((x) => x.name));
  let candidate = `${t.name} copy`;
  let n = 2;
  while (taken.has(candidate)) candidate = `${t.name} copy ${n++}`;
  form.name = candidate;
  dialogOpen.value = true;
}

async function save() {
  try {
    if (editId.value) {
      await api.put<Template>(`/api/templates/${editId.value}`, form);
    } else {
      await api.post<Template>("/api/templates", form);
    }
    dialogOpen.value = false;
    await refresh();
    toast.add({ severity: "success", summary: "Saved", life: 2000 });
  } catch (e: unknown) {
    toast.add({
      severity: "error",
      summary: "Save failed",
      detail: e instanceof Error ? e.message : String(e),
    });
  }
}

function remove(t: Template) {
  confirm.require({
    message: `Delete template "${t.name}"?`,
    accept: async () => {
      await api.delete(`/api/templates/${t.id}`);
      await refresh();
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
    if (!res.ok) throw new Error(await res.text());
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

async function refreshPreview() {
  // Skip if the form is half-filled — printer must be picked for the
  // template to even validate server-side.
  if (!form.printer_id) {
    clearPreview();
    return;
  }
  const seq = ++previewSeq;
  previewLoading.value = true;
  previewError.value = null;
  try {
    const res = await fetch(apiUrl("/api/print/preview-draft"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...adminAuthHeader(),
      },
      // crop=true so the preview is the text-bbox only — without
      // it the bitmap is mostly blank canvas and the actual text
      // shrinks to dots when scaled into the small Print-On swatch.
      body: JSON.stringify({ template: form, crop: true }),
    });
    if (seq !== previewSeq) return; // a newer call already ran
    if (!res.ok) {
      const detail = await res.text();
      previewError.value = `${res.status}: ${detail.slice(0, 200)}`;
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
  () => {
    if (!dialogOpen.value) return;
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
    if (previewTimer !== null) {
      window.clearTimeout(previewTimer);
      previewTimer = null;
    }
    clearPreview();
  }
});

onUnmounted(clearPreview);

// ──────────────── test print ────────────────

async function testPrint() {
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

const FONTS = ["Microsoft Sans Serif", "Calibri"];
const STYLES = ["Bold", "Regular"];

// Recognised PANDUIT SKU at the start of the template name (e.g.
// 'R200X225V1T' → R200X225 preset). Null when the name doesn't match.
const panduitSpec = computed(() => parsePanduitSku(form.name || ""));

// Available bitmap preset for this template name (R200X225 / R200X150
// / S200X400 today). Null → form keeps whatever geometry it has.
const availablePreset = computed(() => findTemplatePreset(form.name || ""));

function applyPreset() {
  const preset = availablePreset.value;
  if (!preset) return;
  // Only touch raster/geometry fields — leave typography, text,
  // printer, name untouched.
  Object.assign(form, preset);
  toast.add({
    severity: "success",
    summary: "Preset applied",
    detail: `Geometry set for ${form.name}. Adjust pt / font as needed.`,
    life: 3500,
  });
}

// Auto-apply the SKU preset while the operator is *creating* a new
// template — that's when blank()'s default geometry is irrelevant and
// is almost certainly wrong for the SKU they just named. In edit mode
// we never touch the geometry automatically (the row already has its
// own tuned values; the Load-preset button stays available as an
// explicit opt-in).
watch(
  () => form.name,
  (newName) => {
    if (editId.value !== null) return;
    const preset = findTemplatePreset(newName);
    if (preset) Object.assign(form, preset);
  },
);
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
      :style="{ width: '52rem', maxWidth: '95vw' }"
      content-class="template-dialog"
    >
      <div class="space-y-4">
        <fieldset class="preview-pane">
          <legend class="text-xs font-bold text-slate-500 uppercase mb-1">
            Preview
            <span class="text-slate-400 font-normal normal-case">
              ({{ form.bytes_per_row * 8 }}×{{ form.height }}px)
            </span>
          </legend>
          <!-- When we recognise the SKU, render the label silhouette
               with the live bitmap embedded inside its Print-On Area.
               Otherwise fall back to the plain bitmap frame. Click
               anywhere on the preview to open it full-size. -->
          <div
            v-if="panduitSpec"
            class="shape-frame zoomable"
            role="button"
            tabindex="0"
            aria-label="Zoom preview"
            @click="zoomOpen = true"
            @keydown.enter="zoomOpen = true"
            @keydown.space.prevent="zoomOpen = true"
          >
            <LabelShape
              :spec="panduitSpec"
              :preview-src="previewSrc"
              :loading="previewLoading"
            />
            <i class="pi pi-search-plus zoom-hint" aria-hidden="true" />
            <p v-if="previewError" class="preview-msg text-red-600 text-xs mt-2">
              {{ previewError }}
            </p>
          </div>
          <div
            v-else
            class="preview-frame zoomable"
            role="button"
            tabindex="0"
            aria-label="Zoom preview"
            @click="previewSrc && (zoomOpen = true)"
            @keydown.enter="previewSrc && (zoomOpen = true)"
            @keydown.space.prevent="previewSrc && (zoomOpen = true)"
          >
            <ProgressSpinner
              v-if="previewLoading"
              class="preview-spinner"
              stroke-width="4"
            />
            <img
              v-if="previewSrc"
              :src="previewSrc"
              :alt="`Preview of ${form.name || 'draft'}`"
              class="preview-img"
            />
            <div v-else-if="previewError" class="preview-msg text-red-600">
              {{ previewError }}
            </div>
            <div v-else-if="!previewLoading" class="preview-msg text-slate-400">
              No preview yet
            </div>
            <i v-if="previewSrc" class="pi pi-search-plus zoom-hint" aria-hidden="true" />
          </div>
        </fieldset>

        <fieldset class="grid grid-cols-2 gap-3">
          <legend class="text-xs font-bold text-slate-500 uppercase mb-1 col-span-2">
            Identity
          </legend>
          <div>
            <label class="block text-xs font-bold text-slate-600 mb-1">Name</label>
            <InputText v-model="form.name" class="w-full" />
            <div class="mt-1 text-xs">
              <Button
                v-if="availablePreset"
                :label="`Load ${form.name.match(/^[RS]\\d{3}[xX]\\d{3}/)?.[0]} preset`"
                icon="pi pi-download"
                size="small"
                text
                @click="applyPreset"
              />
              <span v-else class="text-slate-400">
                Built-in presets: {{ TEMPLATE_PRESET_SKUS.join(", ") }}.
                Name your template starting with one of these to load
                its bitmap geometry.
              </span>
            </div>
          </div>
          <div>
            <label class="block text-xs font-bold text-slate-600 mb-1">Printer</label>
            <Select
              v-model="form.printer_id"
              :options="printers.printers"
              option-label="name"
              option-value="id"
              class="w-full"
            />
          </div>
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
          <legend class="text-xs font-bold text-slate-500 uppercase mb-1 col-span-4">
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
          <legend class="text-xs font-bold text-slate-500 uppercase mb-1 col-span-4">
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
          <legend class="text-xs font-bold text-slate-500 uppercase mb-1 col-span-4">
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

        <fieldset class="grid grid-cols-2 gap-3">
          <legend class="text-xs font-bold text-slate-500 uppercase mb-1 col-span-2">
            Default text
            <span class="text-slate-400 font-normal normal-case">
              — press Enter for a new line; the preview updates live
            </span>
          </legend>
          <div>
            <label class="block text-xs text-slate-600">Left</label>
            <Textarea
              v-model="form.left_text"
              :rows="4"
              auto-resize
              class="w-full font-mono"
            />
          </div>
          <div>
            <label class="block text-xs text-slate-600">Right</label>
            <Textarea
              v-model="form.right_text"
              :rows="4"
              auto-resize
              class="w-full font-mono"
            />
          </div>
        </fieldset>

        <fieldset class="grid grid-cols-2 md:grid-cols-4 gap-3">
          <legend class="text-xs font-bold text-slate-500 uppercase mb-1 col-span-4">
            Typography
          </legend>
          <div><label class="block text-xs text-slate-600">Font</label>
            <Select v-model="form.font_name" :options="FONTS" class="w-full" /></div>
          <div><label class="block text-xs text-slate-600">Style</label>
            <Select v-model="form.font_style" :options="STYLES" class="w-full" /></div>
          <div><label class="block text-xs text-slate-600">Left pt</label>
            <InputNumber v-model="form.left_pt" :min-fraction-digits="0" :max-fraction-digits="2" class="w-full" /></div>
          <div><label class="block text-xs text-slate-600">Right pt</label>
            <InputNumber v-model="form.right_pt" :min-fraction-digits="0" :max-fraction-digits="2" class="w-full" /></div>
          <div class="col-span-2 md:col-span-4">
            <AlignmentGrid v-model:h-align="form.h_align" v-model:v-align="form.v_align" />
          </div>
          <div><label class="block text-xs text-slate-600">L offset</label>
            <InputNumber v-model="form.left_offset" class="w-full" /></div>
          <div><label class="block text-xs text-slate-600">R offset</label>
            <InputNumber v-model="form.right_offset" class="w-full" /></div>
          <div class="md:col-span-2">
            <label class="block text-xs text-slate-600">Stretch width</label>
            <InputNumber
              v-model="form.scale_x"
              :min="1"
              :max="1.5"
              :step="0.01"
              :min-fraction-digits="2"
              :max-fraction-digits="2"
              class="w-full"
            />
            <span class="text-[10px] text-slate-400 block mt-0.5">
              1.00 = normal width · 1.12 = slightly wider letters (Turn-Tell)
            </span>
          </div>
        </fieldset>
      </div>

      <template #footer>
        <div class="flex justify-between w-full">
          <Button
            label="Send test print"
            icon="pi pi-bolt"
            severity="secondary"
            :loading="testing"
            :disabled="!form.printer_id"
            @click="testPrint"
          />
          <div class="flex gap-2">
            <Button label="Cancel" severity="secondary" @click="dialogOpen = false" />
            <Button :label="editId ? 'Save' : 'Create'" @click="save" />
          </div>
        </div>
      </template>
    </Dialog>

    <!-- Full-size preview zoom. Renders on top of the template editor
         (PrimeVue handles nested Dialog stacking via teleport). -->
    <Dialog
      v-model:visible="zoomOpen"
      modal
      dismissable-mask
      :header="form.name || 'Preview'"
      :style="{ width: '92vw', maxWidth: '1400px' }"
      content-class="zoom-dialog"
    >
      <div v-if="panduitSpec" class="zoom-shape">
        <LabelShape
          :spec="panduitSpec"
          :preview-src="previewSrc"
          :loading="previewLoading"
        />
      </div>
      <div v-else class="zoom-bitmap">
        <ProgressSpinner
          v-if="previewLoading"
          class="preview-spinner"
          stroke-width="4"
        />
        <img
          v-if="previewSrc"
          :src="previewSrc"
          :alt="`Preview of ${form.name || 'draft'}`"
        />
      </div>
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
.template-dialog .p-iconfield {
  width: 100% !important;
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
</style>
