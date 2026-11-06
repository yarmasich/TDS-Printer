<script setup lang="ts">
import { useAdminRequests, useImportDestination } from "@/composables/adminRequests";
const requests = useAdminRequests();
const requestError = requests.error;
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
const destination = useImportDestination((pid: number) => api.get<Discipline[]>(`/api/disciplines?project_id=${pid}`));
const disciplines = destination.options;
const destinationLoading = destination.loading;
const destinationError = destination.error;
const imports = ref<ImportDTO[]>([]);

const projectId = ref<number | null>(null);
const disciplineId = ref<number | null>(null);
const file = ref<File | null>(null);
const filePickerKey = ref(0);

onMounted(refresh);

async function refresh() {
  await requests.run("refresh", () => refreshRequest());
}
async function refreshRequest() {
  [projects.value, imports.value] = await Promise.all([
    api.get<Project[]>("/api/projects"),
    api.get<ImportDTO[]>("/api/imports"),
  ]);
}

watch(projectId, (pid) => {
  disciplineId.value = null;
  void destination.load(pid);
}, { flush: "sync" });

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
  () => destination.valid(disciplineId.value) && file.value != null,
);

function onFileSelect(e: { files: File[] }) {
  file.value = e.files[0] ?? null;
}

async function upload() {
  await requests.run("upload", () => uploadRequest());
}
async function uploadRequest() {
  if (!file.value || !destination.valid(disciplineId.value)) return;
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
    filePickerKey.value++;
    await refresh();
  } catch (e: unknown) {
    requestError.value = e instanceof Error ? e.message : String(e);
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
    accept: async () => requests.run("delete", async () => {
      try {
        await api.delete(`/api/imports/${imp.id}`);
        await refresh();
        toast.add({ severity: "success", summary: "Deleted", life: 2000 });
      } catch (e: unknown) {
        requestError.value = e instanceof Error ? e.message : String(e);
        toast.add({
          severity: "error",
          summary: "Delete failed",
          detail: e instanceof Error ? e.message : String(e),
        });
      }
    }),
  });
}
</script>

<template>
  <section class="admin-touch bg-surface border border-edge rounded-2xl p-5 shadow-sm">
    <p v-if="requestError" role="alert" class="text-danger my-3">{{ requestError }} — Please try again.</p>
    <p v-if="requests.busy('refresh')" role="status" class="text-ink-2 my-3">Loading…</p>
    <Button v-if="requestError" label="Retry loading" severity="secondary" @click="refresh" />

    <h2 class="text-lg font-bold mb-3">Import labels</h2>

    <div class="bg-sunken border border-edge rounded-xl p-3 mb-4">
      <div class="grid grid-cols-1 md:grid-cols-3 gap-3 items-end">
        <div>
          <label for="importssection-field-1" class="block text-xs font-bold text-ink-2 mb-1">Project</label>
          <Select input-id="importssection-field-1"
            aria-label="Project"
            v-model="projectId" :disabled="requests.busy('upload')"
            :options="projects"
            option-label="name"
            option-value="id"
            placeholder="— pick —"
            class="w-full"
          />
        </div>
        <div>
          <label for="importssection-field-2" class="block text-xs font-bold text-ink-2 mb-1">Discipline</label>
          <Select input-id="importssection-field-2"
            aria-label="Discipline"
            v-model="disciplineId"
            :options="disciplineOptions"
            option-label="label"
            option-value="id"
            :disabled="projectId == null || destinationLoading || requests.busy('upload')" :loading="destinationLoading"
            placeholder="— pick —"
            filter
            class="w-full"
          />
        </div>
        <div>
          <FileUpload :key="filePickerKey" :disabled="requests.busy('upload')"
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
      <p v-if="destinationError" role="alert" class="text-danger mt-3">{{ destinationError }} <Button label="Retry disciplines" @click="destination.load(projectId)" /></p>
      <p v-if="projectId && !destinationLoading && !destinationError && !disciplines.length" class="mt-3">No disciplines in this project. Add one in Projects · Halls · Disciplines first.</p>
      <div class="mt-3 flex justify-end">
        <Button :disabled="!canUpload || requests.pending.value.size > 0"
          label="Upload"
          icon="pi pi-upload"
          :loading="requests.busy('upload')"
          @click="upload"
        />
      </div>
    </div>

    <h3 class="text-sm font-bold text-ink-2 mb-2 uppercase">
      Uploaded files ({{ imports.length }})
    </h3>
    <DataTable
      :value="imports"
      data-key="id"
      striped-rows

      :paginator="imports.length > 10"
      :rows="10"
      size="small"
      sort-mode="single"
      sort-field="uploaded_at"
      :sort-order="-1"
    >
      <template #empty>No files uploaded yet.</template>
      <Column field="uploaded_at" header="When" sortable />
      <Column field="filename" header="File" sortable />
      <Column header="Project / Hall / Discipline">
        <template #body="{ data }">
          <span class="text-ink-2">
            {{ data.project_name }} / {{ data.data_hall_name }} /
            <b>{{ data.discipline_name }}</b>
          </span>
        </template>
      </Column>
      <Column field="rows" header="Rows" sortable style="text-align: right" />
      <Column field="sheets" header="Sheets" style="text-align: right" />
      <Column header="" :style="{ width: '80px' }">
        <template #body="{ data }">
          <Button :disabled="requests.pending.value.size > 0"
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

<style scoped>
@media (pointer: coarse) { .admin-touch :deep(.p-button), .admin-touch :deep(.p-select), .admin-touch :deep(.p-inputtext) { min-height:44px; } .admin-touch :deep(.p-button-icon-only) { min-width:44px; } }
</style>
