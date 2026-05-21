<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { api } from "@/api/client";
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
import Select from "primevue/select";
import ToggleSwitch from "primevue/toggleswitch";

const printers = usePrinters();
const toast = useToast();
const confirm = useConfirm();

const templates = ref<Template[]>([]);
const dialogOpen = ref(false);
const editId = ref<number | null>(null);

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
  mirror_mode: false,
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

function previewUrl(t: Template) {
  return (
    `/api/print/preview?template_id=${t.id}` +
    `&left_text=${encodeURIComponent(t.left_text)}` +
    `&right_text=${encodeURIComponent(t.right_text)}`
  );
}

const ALIGN_H = ["LEFT", "CENTER", "RIGHT"];
const ALIGN_V = ["TOP", "CENTER", "BOTTOM"];
const FONTS = ["Microsoft Sans Serif", "Calibri"];
const STYLES = ["Bold", "Regular"];
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
      <Column header="Mirror">
        <template #body="{ data }">{{ data.mirror_mode ? "yes" : "no" }}</template>
      </Column>
      <Column header="" :style="{ width: '180px' }">
        <template #body="{ data }">
          <div class="flex gap-1 justify-end">
            <a :href="previewUrl(data)" target="_blank" rel="noopener">
              <Button
                icon="pi pi-eye"
                size="small"
                text
                severity="secondary"
                aria-label="Preview"
              />
            </a>
            <Button
              icon="pi pi-pencil"
              size="small"
              text
              aria-label="Edit"
              @click="openEdit(data)"
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
        <fieldset class="grid grid-cols-2 gap-3">
          <legend class="text-xs font-bold text-slate-500 uppercase mb-1 col-span-2">
            Identity
          </legend>
          <div>
            <label class="block text-xs font-bold text-slate-600 mb-1">Name</label>
            <InputText v-model="form.name" class="w-full" />
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

        <fieldset class="grid grid-cols-3 gap-3">
          <legend class="text-xs font-bold text-slate-500 uppercase mb-1 col-span-3">
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
          <div class="flex items-end gap-2">
            <label class="text-xs font-bold text-slate-600">Mirror</label>
            <ToggleSwitch v-model="form.mirror_mode" />
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
          </legend>
          <div><label class="block text-xs text-slate-600">Left</label>
            <InputText v-model="form.left_text" class="w-full" /></div>
          <div><label class="block text-xs text-slate-600">Right</label>
            <InputText v-model="form.right_text" class="w-full" /></div>
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
          <div><label class="block text-xs text-slate-600">H align</label>
            <Select v-model="form.h_align" :options="ALIGN_H" class="w-full" /></div>
          <div><label class="block text-xs text-slate-600">V align</label>
            <Select v-model="form.v_align" :options="ALIGN_V" class="w-full" /></div>
          <div><label class="block text-xs text-slate-600">L offset</label>
            <InputNumber v-model="form.left_offset" class="w-full" /></div>
          <div><label class="block text-xs text-slate-600">R offset</label>
            <InputNumber v-model="form.right_offset" class="w-full" /></div>
        </fieldset>
      </div>

      <template #footer>
        <Button label="Cancel" severity="secondary" @click="dialogOpen = false" />
        <Button :label="editId ? 'Save' : 'Create'" @click="save" />
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
.template-dialog .p-select,
.template-dialog .p-iconfield {
  width: 100% !important;
}
.template-dialog fieldset {
  border: 0;
  padding: 0;
  margin: 0;
}
.template-dialog legend {
  padding: 0;
}
</style>
