<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { adminAuthHeader, api, apiUrl } from "@/api/client";
import type { Discipline, ImportDTO, Project } from "@/api/types";
import { useToast } from "primevue/usetoast";
import { useConfirm } from "primevue/useconfirm";

import DataTable from "primevue/datatable";
import Column from "primevue/column";
import Button from "primevue/button";
import Select from "primevue/select";
import FileUpload from "primevue/fileupload";

const toast = useToast();
const confirm = useConfirm();

const projects = ref<Project[]>([]);
const disciplines = ref<Discipline[]>([]);
const imports = ref<ImportDTO[]>([]);

const projectId = ref<number | null>(null);
const disciplineId = ref<number | null>(null);
const file = ref<File | null>(null);

onMounted(refresh);

async function refresh() {
  [projects.value, imports.value] = await Promise.all([
    api.get<Project[]>("/api/projects"),
    api.get<ImportDTO[]>("/api/imports"),
  ]);
}

watch(projectId, async (pid) => {
  disciplineId.value = null;
  if (pid != null) {
    disciplines.value = await api.get<Discipline[]>(
      `/api/disciplines?project_id=${pid}`,
    );
  } else {
    disciplines.value = [];
  }
});

// Same discipline name can exist in several data halls (e.g. DH23/AS-T1 and
// DH26/AS-T1). Prefix the hall so the option — and the picked value — is
// unambiguous. Backend already returns them grouped by hall, then name.
const disciplineOptions = computed(() =>
  disciplines.value.map((d) => ({
    id: d.id,
    label: d.data_hall_name ? `${d.data_hall_name} / ${d.name}` : d.name,
  })),
);

const canUpload = computed(
  () => disciplineId.value != null && file.value != null,
);

function onFileSelect(e: { files: File[] }) {
  file.value = e.files[0] ?? null;
}

async function upload() {
  if (!file.value || disciplineId.value == null) return;
  const fd = new FormData();
  fd.append("discipline_id", String(disciplineId.value));
  fd.append("file", file.value);
  try {
    const res = await fetch(apiUrl("/api/import/upload"), {
      method: "POST",
      headers: adminAuthHeader(),
      body: fd,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "upload failed");
    toast.add({
      severity: "success",
      summary: `Imported ${data.rows} rows · ${data.sheets} sheets`,
      life: 3000,
    });
    file.value = null;
    await refresh();
  } catch (e: unknown) {
    toast.add({
      severity: "error",
      summary: "Upload failed",
      detail: e instanceof Error ? e.message : String(e),
    });
  }
}

function remove(imp: ImportDTO) {
  confirm.require({
    message: `Delete "${imp.filename}" and its ${imp.rows} rows?`,
    accept: async () => {
      try {
        await api.delete(`/api/imports/${imp.id}`);
        await refresh();
        toast.add({ severity: "success", summary: "Deleted", life: 2000 });
      } catch (e: unknown) {
        toast.add({
          severity: "error",
          summary: "Delete failed",
          detail: e instanceof Error ? e.message : String(e),
        });
      }
    },
  });
}
</script>

<template>
  <section class="bg-white border border-slate-200 rounded-2xl p-5 shadow-sm">
    <h2 class="text-lg font-bold mb-3">Import labels</h2>

    <div class="bg-slate-50 border border-slate-200 rounded-xl p-3 mb-4">
      <div class="grid grid-cols-1 md:grid-cols-3 gap-3 items-end">
        <div>
          <label class="block text-xs font-bold text-slate-600 mb-1">Project</label>
          <Select
            v-model="projectId"
            :options="projects"
            option-label="name"
            option-value="id"
            placeholder="— pick —"
            class="w-full"
          />
        </div>
        <div>
          <label class="block text-xs font-bold text-slate-600 mb-1">Discipline</label>
          <Select
            v-model="disciplineId"
            :options="disciplineOptions"
            option-label="label"
            option-value="id"
            :disabled="projectId == null"
            placeholder="— pick —"
            filter
            class="w-full"
          />
        </div>
        <div>
          <FileUpload
            mode="basic"
            accept=".xlsx"
            :auto="false"
            :show-cancel-button="false"
            choose-label="Choose XLSX"
            :custom-upload="true"
            @select="onFileSelect"
          />
        </div>
      </div>
      <div class="mt-3 flex justify-end">
        <Button
          label="Upload"
          icon="pi pi-upload"
          :disabled="!canUpload"
          @click="upload"
        />
      </div>
    </div>

    <h3 class="text-sm font-bold text-slate-600 mb-2 uppercase">
      Uploaded files ({{ imports.length }})
    </h3>
    <DataTable
      :value="imports"
      data-key="id"
      striped-rows
      empty-message="No files uploaded yet"
      :paginator="imports.length > 10"
      :rows="10"
      size="small"
      sort-mode="single"
      sort-field="uploaded_at"
      :sort-order="-1"
    >
      <Column field="uploaded_at" header="When" sortable />
      <Column field="filename" header="File" sortable />
      <Column header="Project / Hall / Discipline">
        <template #body="{ data }">
          <span class="text-slate-600">
            {{ data.project_name }} / {{ data.data_hall_name }} /
            <b>{{ data.discipline_name }}</b>
          </span>
        </template>
      </Column>
      <Column field="rows" header="Rows" sortable style="text-align: right" />
      <Column field="sheets" header="Sheets" style="text-align: right" />
      <Column header="" :style="{ width: '80px' }">
        <template #body="{ data }">
          <Button
            icon="pi pi-trash"
            severity="danger"
            text
            size="small"
            aria-label="Delete"
            @click="remove(data)"
          />
        </template>
      </Column>
    </DataTable>
  </section>
</template>
