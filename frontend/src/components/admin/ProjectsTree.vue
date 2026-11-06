<script setup lang="ts">
import { useAdminRequests } from "@/composables/adminRequests";
const requests = useAdminRequests();
const requestError = requests.error;
import { computed, onMounted, ref } from "vue";
import { api } from "@/api/client";
import type { DataHall, Discipline, Project, Template } from "@/api/types";
import { useToast } from "primevue/usetoast";
import { useConfirm } from "primevue/useconfirm";

import Button from "primevue/button";
import InputText from "primevue/inputtext";
import Select from "primevue/select";
import Dialog from "primevue/dialog";
import ColorPicker from "primevue/colorpicker";

const toast = useToast();
const confirm = useConfirm();

const projects = ref<Project[]>([]);
const halls = ref<DataHall[]>([]);
const disciplines = ref<Discipline[]>([]);
const templates = ref<Template[]>([]);

// Keep expansion across data refreshes and navigation within Admin.
const collapsedProjects = ref(new Set<number>());
const expandedHalls = ref(new Set<number>());
function toggleProject(id: number) {
  if (collapsedProjects.value.has(id)) collapsedProjects.value.delete(id);
  else collapsedProjects.value.add(id);
}
function toggleHall(id: number) {
  if (expandedHalls.value.has(id)) expandedHalls.value.delete(id);
  else expandedHalls.value.add(id);
}
function collapseAll() {
  collapsedProjects.value = new Set(projects.value.map(p => p.id));
  expandedHalls.value.clear();
}
function expandAll() {
  collapsedProjects.value.clear();
  expandedHalls.value = new Set(halls.value.map(h => h.id));
}

const savingRfid = ref(new Set<number>());
const rfidErrors = ref<Record<number, string>>({});

const projectDialog = ref(false);
const hallDialog = ref(false);
const discDialog = ref(false);

const newProject = ref("");
const newHall = ref({ projectId: 0, name: "" });
const newDisc = ref({
  hallId: 0,
  name: "",
  template_id: null as number | null,
  color: "FFFFFF",
});

async function refresh() {
  await requests.run("refresh", () => refreshRequest());
}
async function refreshRequest() {
  const [p, h, d, t] = await Promise.all([
    api.get<Project[]>("/api/projects"),
    api.get<DataHall[]>("/api/halls"),
    api.get<Discipline[]>("/api/disciplines"),
    api.get<Template[]>("/api/templates"),
  ]);
  projects.value = p;
  halls.value = h;
  disciplines.value = d;
  templates.value = t;
}
onMounted(refresh);

const hallsByProject = computed(() => {
  const m = new Map<number, DataHall[]>();
  for (const h of halls.value) {
    const a = m.get(h.project_id) ?? [];
    a.push(h);
    m.set(h.project_id, a);
  }
  return m;
});

const discByHall = computed(() => {
  const m = new Map<number, Discipline[]>();
  for (const d of disciplines.value) {
    const a = m.get(d.data_hall_id) ?? [];
    a.push(d);
    m.set(d.data_hall_id, a);
  }
  return m;
});

function openHall(projectId: number) {
  newHall.value = { projectId, name: "" };
  hallDialog.value = true;
}

function openDisc(hallId: number) {
  newDisc.value = { hallId, name: "", template_id: null, color: "FFFFFF" };
  discDialog.value = true;
}

async function createProject() {
  await requests.run("createProject", () => createProjectRequest());
}
async function createProjectRequest() {
  await api.post("/api/projects", { name: newProject.value });
  newProject.value = "";
  projectDialog.value = false;
  await refresh();
}

async function createHall() {
  await requests.run("createHall", () => createHallRequest());
}
async function createHallRequest() {
  await api.post("/api/halls", {
    project_id: newHall.value.projectId,
    name: newHall.value.name,
  });
  hallDialog.value = false;
  collapsedProjects.value.delete(newHall.value.projectId);
  await refresh();
}

async function createDisc() {
  await requests.run("createDisc", () => createDiscRequest());
}
async function createDiscRequest() {
  await api.post("/api/disciplines", {
    data_hall_id: newDisc.value.hallId,
    name: newDisc.value.name,
    template_id: newDisc.value.template_id,
    color: newDisc.value.color,
  });
  discDialog.value = false;
  expandedHalls.value.add(newDisc.value.hallId);
  await refresh();
}

async function bindTemplate(d: Discipline, templateId: number | null) {
  await requests.run("bindTemplate", () => bindTemplateRequest(d, templateId));
}
async function bindTemplateRequest(d: Discipline, templateId: number | null) {
  try {
    await api.put(`/api/disciplines/${d.id}`, { template_id: templateId });
    await refresh();
    toast.add({ severity: "success", summary: "Template bound", life: 1500 });
  } catch (e: unknown) {
    requestError.value = e instanceof Error ? e.message : String(e);
    toast.add({
      severity: "error",
      summary: "Bind failed",
      detail: e instanceof Error ? e.message : String(e),
    });
  }
}

async function toggleRfid(project: Project, event: Event) {
  const input = event.target as HTMLInputElement;
  const previous = Boolean(project.require_rfid);
  if (savingRfid.value.has(project.id)) { input.checked = previous; return; }
  const next = input.checked;
  savingRfid.value.add(project.id);
  delete rfidErrors.value[project.id];
  try {
    await api.patch(`/api/projects/${project.id}`, { require_rfid: next });
    project.require_rfid = next;
    toast.add({ severity: "success", summary: next ? "RFID required for this project" : "RFID requirement disabled", life: 2500 });
  } catch (e) {
    input.checked = previous;
    project.require_rfid = previous;
    rfidErrors.value[project.id] = e instanceof Error ? e.message : String(e);
  } finally {
    savingRfid.value.delete(project.id);
  }
}

async function toggleBundle(d: Discipline) {
  await requests.run("toggleBundle", () => toggleBundleRequest(d));
}
async function toggleBundleRequest(d: Discipline) {
  const next = !d.bundle_mode;
  try {
    await api.put(`/api/disciplines/${d.id}`, { bundle_mode: next });
    d.bundle_mode = next; // optimistic — avoid full refresh flash
    toast.add({
      severity: "success",
      summary: next ? "Bundle mode on" : "Bundle mode off",
      detail: next
        ? "Re-import this discipline's files so labels get tagged by bundle."
        : "",
      life: 3500,
    });
  } catch (e: unknown) {
    requestError.value = e instanceof Error ? e.message : String(e);
    toast.add({
      severity: "error",
      summary: "Save failed",
      detail: e instanceof Error ? e.message : String(e),
    });
  }
}

async function updateColor(d: Discipline, color: string) {
  await requests.run("updateColor", () => updateColorRequest(d, color));
}
async function updateColorRequest(d: Discipline, color: string) {
  // PrimeVue's ColorPicker (format=hex) returns the colour without the
  // leading '#', which matches what the DB stores.
  if (!color || color.toUpperCase() === d.color.toUpperCase()) return;
  try {
    await api.put(`/api/disciplines/${d.id}`, { color: color.toUpperCase() });
    d.color = color.toUpperCase(); // optimistic — avoid full refresh flash
  } catch (e: unknown) {
    requestError.value = e instanceof Error ? e.message : String(e);
    toast.add({
      severity: "error",
      summary: "Color save failed",
      detail: e instanceof Error ? e.message : String(e),
    });
  }
}

function deletionMessage(url: string, label: string) {
  const id = Number(url.split('/').pop());
  const kind = url.includes('/projects/') ? 'project' : url.includes('/halls/') ? 'hall' : 'discipline';
  const affectedHalls = kind === 'project' ? halls.value.filter(h => h.project_id === id) : halls.value.filter(h => h.id === id);
  const affected = kind === 'discipline' ? disciplines.value.filter(d => d.id === id) : disciplines.value.filter(d => affectedHalls.some(h => h.id === d.data_hall_id));
  const labels = affected.reduce((total, d) => total + (d.label_count ?? 0), 0);
  return `Permanently delete ${kind} "${label}"? This removes ${kind === 'project' ? `${affectedHalls.length} halls, ` : ''}${affected.length} disciplines and ${labels} labels, including their imported files. This cannot be undone.`;
}

function del(url: string, label: string) {
  confirm.require({
    header: "Delete project data",
    message: deletionMessage(url, label),
    acceptLabel: "Delete permanently",
    rejectLabel: "Cancel",
    acceptProps: { severity: "danger" },
    accept: async () => requests.run("delete", async () => {
      try {
        await api.delete(url);
        await refresh();
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
  <section class="admin-touch bg-white border border-slate-200 rounded-2xl p-5 shadow-sm">
    <p v-if="requestError" role="alert" class="text-red-700 my-3">{{ requestError }} — Please try again.</p>
    <p v-if="requests.busy('refresh')" role="status" class="text-slate-600 my-3">Loading…</p>
    <Button v-if="requestError" label="Retry loading" severity="secondary" @click="refresh" />

    <div class="flex flex-wrap gap-3 items-center justify-between mb-3">
      <h2 class="text-lg font-bold">Projects · Halls · Disciplines</h2>
      <Button :disabled="requests.pending.value.size > 0"
        label="Add project"
        icon="pi pi-plus"
        size="small"
        @click="
          newProject = '';
          projectDialog = true;
        "
      />
    </div>

    <div v-if="projects.length" class="flex flex-wrap gap-2 mb-4">
      <Button :disabled="requests.pending.value.size > 0" label="Expand all" icon="pi pi-angle-double-down" text severity="secondary" class="min-h-11" @click="expandAll" />
      <Button :disabled="requests.pending.value.size > 0" label="Collapse all" icon="pi pi-angle-double-up" text severity="secondary" class="min-h-11" @click="collapseAll" />
    </div>

    <p v-if="projects.length === 0" class="text-slate-500">
      No projects yet.
    </p>

    <div
      v-for="p in projects"
      :key="p.id"
      class="bg-slate-50 rounded-xl p-3 mb-3 space-y-2"
    >
      <div class="flex flex-wrap gap-2 justify-between items-center">
        <button type="button" class="tree-toggle" :aria-expanded="!collapsedProjects.has(p.id)" :aria-controls="`project-content-${p.id}`" @click="toggleProject(p.id)">
          <i :class="collapsedProjects.has(p.id) ? 'pi pi-chevron-right' : 'pi pi-chevron-down'" aria-hidden="true" />
          <b>{{ p.name }}</b>
          <span class="tree-count">{{ hallsByProject.get(p.id)?.length ?? 0 }} halls</span>
        </button>
        <div class="flex gap-1">
          <Button :disabled="requests.pending.value.size > 0"
            label="+ hall"
            size="small"
            text
            @click="openHall(p.id)"
          />
          <Button :disabled="requests.pending.value.size > 0"
            icon="pi pi-trash"
            size="small"
            text
            severity="danger"
            aria-label="Delete project"
            @click="del('/api/projects/' + p.id, p.name)"
          />
        </div>
      </div>

      <div v-if="!collapsedProjects.has(p.id)" :id="`project-content-${p.id}`" class="space-y-2">
      <label class="inline-flex min-h-12 items-center gap-3 cursor-pointer text-sm font-semibold">
        <input
          type="checkbox"
          class="h-5 w-5 accent-sky-600"
          :checked="Boolean(p.require_rfid)"
          :disabled="savingRfid.has(p.id)"
          @change="toggleRfid(p, $event)"
        />
        RFID required before printing
        <span v-if="savingRfid.has(p.id)" role="status" class="font-normal text-slate-500">Saving…</span>
      </label>
      <p class="text-xs text-slate-500">Requires a configured RFID lookup service. Off by default.</p>
      <p v-if="rfidErrors[p.id]" role="alert" class="text-sm text-red-700">Could not save: {{ rfidErrors[p.id] }}</p>

      <div
        v-for="h in hallsByProject.get(p.id) ?? []"
        :key="h.id"
        class="sm:ml-5 bg-white border border-slate-200 rounded-lg p-3 space-y-2"
      >
        <div class="flex flex-wrap gap-2 justify-between items-center">
          <button type="button" class="tree-toggle" :aria-expanded="expandedHalls.has(h.id)" :aria-controls="`hall-content-${h.id}`" @click="toggleHall(h.id)">
            <i :class="expandedHalls.has(h.id) ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" aria-hidden="true" />
            <span class="font-semibold">{{ h.name }}</span>
            <span class="tree-count">{{ discByHall.get(h.id)?.length ?? 0 }} disciplines</span>
          </button>
          <div class="flex gap-1">
            <Button :disabled="requests.pending.value.size > 0"
              label="+ discipline"
              size="small"
              text
              @click="openDisc(h.id)"
            />
            <Button :disabled="requests.pending.value.size > 0"
              icon="pi pi-trash"
              size="small"
              text
              severity="danger"
              aria-label="Delete hall"
              @click="del('/api/halls/' + h.id, h.name)"
            />
          </div>
        </div>

        <div v-if="expandedHalls.has(h.id)" :id="`hall-content-${h.id}`" class="space-y-2">
        <p v-if="!discByHall.get(h.id)?.length" class="text-sm text-slate-500 px-3 py-2">No disciplines yet.</p>
        <div
          v-for="d in discByHall.get(h.id) ?? []"
          :key="d.id"
          class="sm:ml-5 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 flex flex-wrap justify-between items-center gap-2"
        >
          <div class="flex items-center gap-2 min-w-0">
            <ColorPicker
              :model-value="d.color"
              format="hex"
              :pt="{ preview: { 'aria-label': `Color for ${d.name}` } }"
              @update:model-value="(v) => updateColor(d, String(v))"
            />
            <span class="font-semibold">{{ d.name }}</span>
            <span class="text-xs text-slate-400">
              {{ d.label_count }} labels
            </span>
          </div>
          <div class="flex flex-wrap items-center gap-2">
            <label
              class="inline-flex min-h-11 items-center gap-2 text-sm cursor-pointer select-none"
              :class="d.bundle_mode ? 'text-orange-600 font-semibold' : 'text-slate-500'"
              title="Bundle mode: imports parse 'BUNDLE #N' headers and tag labels; Print shows a bundle picker. Re-import after turning on."
            >
              <input
                type="checkbox"
                class="h-5 w-5 accent-orange-600" :disabled="requests.busy('toggleBundle')"
                :checked="d.bundle_mode"
                @change="toggleBundle(d)"
              />
              <span>Bundle</span>
            </label>
            <Select
              :model-value="d.template_id"
              :options="templates"
              option-label="name"
              option-value="id"
              show-clear
              placeholder="— template —"
              class="w-full sm:w-auto sm:min-w-[180px]" :disabled="requests.busy('bindTemplate')"
              @update:model-value="(v) => bindTemplate(d, v)"
            />
            <Button :disabled="requests.pending.value.size > 0"
              icon="pi pi-trash"
              size="small"
              text
              severity="danger"
              aria-label="Delete discipline"
              @click="del('/api/disciplines/' + d.id, d.name)"
            />
          </div>
          <p v-if="d.bundle_mode" class="w-full text-sm text-slate-600">Re-import this discipline’s files after enabling Bundle so labels are grouped by bundle.</p>
        </div>
      </div>
      </div>
      </div>
    </div>

    <!-- Dialogs -->
    <Dialog
      v-model:visible="projectDialog"
      modal class="admin-touch"
      header="New project"
      :style="{ width: 'min(24rem, 94vw)' }"
    >
      <InputText aria-label="Project name" v-model="newProject" class="w-full" placeholder="Project name" />
      <p v-if="requestError" role="alert" class="text-red-700 mt-3">{{ requestError }} — Please try again.</p>
      <template #footer>
        <Button :disabled="requests.pending.value.size > 0" label="Cancel" severity="secondary" @click="projectDialog = false" />
        <Button :disabled="requests.pending.value.size > 0 || !newProject.trim()" label="Create" @click="createProject" />
      </template>
    </Dialog>

    <Dialog
      v-model:visible="hallDialog"
      modal class="admin-touch"
      header="New data hall"
      :style="{ width: 'min(24rem, 94vw)' }"
    >
      <InputText aria-label="Name" v-model="newHall.name" class="w-full" placeholder="DH3" />
      <p v-if="requestError" role="alert" class="text-red-700 mt-3">{{ requestError }} — Please try again.</p>
      <template #footer>
        <Button :disabled="requests.pending.value.size > 0" label="Cancel" severity="secondary" @click="hallDialog = false" />
        <Button :disabled="requests.pending.value.size > 0 || !newHall.name.trim()" label="Create" @click="createHall" />
      </template>
    </Dialog>

    <Dialog
      v-model:visible="discDialog"
      modal class="admin-touch"
      header="New discipline"
      :style="{ width: 'min(32rem, 94vw)' }"
    >
      <div class="space-y-3">
        <div>
          <label for="projectstree-field-1" class="block text-xs font-bold text-slate-600 mb-1">Name</label>
          <InputText id="projectstree-field-1" aria-label="Name" v-model="newDisc.name" class="w-full" placeholder="GPU-MS" />
        </div>
        <div>
          <label for="projectstree-field-2" class="block text-xs font-bold text-slate-600 mb-1">Template</label>
          <Select input-id="projectstree-field-2"
            aria-label="Template"
            v-model="newDisc.template_id"
            :options="templates"
            option-label="name"
            option-value="id"
            show-clear
            placeholder="— assign later —"
            class="w-full"
          />
        </div>
        <div>
          <label class="block text-xs font-bold text-slate-600 mb-1">Color</label>
          <div class="flex items-center gap-2">
            <ColorPicker v-model="newDisc.color" format="hex" />
            <code class="text-xs text-slate-500">#{{ newDisc.color }}</code>
          </div>
        </div>
      </div>
      <p v-if="requestError" role="alert" class="text-red-700 mt-3">{{ requestError }} — Please try again.</p>
      <template #footer>
        <Button :disabled="requests.pending.value.size > 0" label="Cancel" severity="secondary" @click="discDialog = false" />
        <Button :disabled="requests.pending.value.size > 0 || !newDisc.name.trim()" label="Create" @click="createDisc" />
      </template>
    </Dialog>
  </section>
</template>

<style scoped>
@media (pointer: coarse) { .admin-touch :deep(.p-button), .admin-touch :deep(.p-select), .admin-touch :deep(.p-inputtext) { min-height:44px; } .admin-touch :deep(.p-button-icon-only) { min-width:44px; } }
.tree-toggle { display:flex; align-items:center; flex-wrap:wrap; gap:10px; min-height:44px; padding:6px 8px; min-width:0; text-align:left; border-radius:8px; cursor:pointer; overflow-wrap:anywhere; }
.tree-toggle:hover { background:#e0f2fe; }
.tree-toggle:focus-visible { outline:2px solid #0284c7; outline-offset:2px; }
.tree-toggle > i { font-size:12px; flex-shrink:0; }
.tree-count { font-size:13px; font-weight:400; color:#64748b; }
</style>
