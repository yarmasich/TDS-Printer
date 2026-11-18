<script lang="ts">
// The delete flow lives here rather than in setup() so it can be driven by
// tests/discipline-force-delete.test.mjs without a mounted component.
import { ApiError } from "@/api/client";

// Only DELETE /api/disciplines/{id} accepts force; projects and halls have no
// such escape hatch, so only that shape may offer the retry.
const FORCEABLE_DELETE = /^\/api\/disciplines\/\d+$/;

export interface DeleteFlow {
  remove: (url: string) => Promise<unknown>;
  /** Resolves true only when the admin accepts the forced delete. */
  confirmForce: (message: string) => Promise<boolean>;
  fail: (message: string, forced: boolean) => void;
  reload: () => Promise<void>;
}

/** The 409 names its blockers in parentheses, e.g. "(1 printing, 2 uncertain)".
 * Only the counts are reused; the rest of the detail is the curl hint that the
 * forced-delete button now replaces. */
export function blockerSummary(detail: string): string {
  return /\(([^()]*\b(?:printing|uncertain)\b[^()]*)\)/.exec(detail)?.[1]?.trim() ?? "";
}

/** Names what a forced delete throws away: an uncertain row is the only record
 * that a send was interrupted, so the physical labels must be checked first. */
export function forceDeleteMessage(label: string, detail: string): string {
  const blockers = blockerSummary(detail);
  return (
    `“${label}” still has labels held in a print job${blockers ? ` — ${blockers}` : ""}, inside a` +
    " tablet’s cart that cannot be opened from here. “Uncertain” means a send was interrupted and" +
    " nobody knows whether the label physically came out of the printer; that row is the only record" +
    " of it, so check the printer and the labels on the floor before discarding it. A label genuinely" +
    " printing at this moment is never cleared — the delete stops and asks you to wait instead."
  );
}

async function attempt(url: string, remove: DeleteFlow["remove"]) {
  try {
    await remove(url);
    return null;
  } catch (e: unknown) {
    return {
      status: e instanceof ApiError ? e.status : 0,
      message: e instanceof Error ? e.message : String(e),
    };
  }
}

/** One plain attempt, then — for a first 409 on a discipline only — one forced
 * retry. The two 409s are told apart structurally, not by their prose: the
 * forced attempt is a tail call with no retry of its own, so the live-print
 * refusal that force can never lift cannot re-offer force. */
export async function deleteWithForce(url: string, label: string, flow: DeleteFlow): Promise<void> {
  const blocked = await attempt(url, flow.remove);
  if (!blocked) return flow.reload();
  if (blocked.status !== 409 || !FORCEABLE_DELETE.test(url)) return flow.fail(blocked.message, false);
  if (!(await flow.confirmForce(forceDeleteMessage(label, blocked.message)))) return;
  const live = await attempt(`${url}?force=true`, flow.remove);
  if (live) return flow.fail(live.message, true);
  return flow.reload();
}
</script>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useAdminRequests } from "@/composables/adminRequests";
import { api } from "@/api/client";
import type { DataHall, Discipline, Project, Template } from "@/api/types";
import { trunkTargets } from "@/data/trunks";
import { useToast } from "primevue/usetoast";
import { useConfirm } from "primevue/useconfirm";

import Button from "primevue/button";
import InputText from "primevue/inputtext";
import Select from "primevue/select";
import Dialog from "primevue/dialog";
import ColorPicker from "primevue/colorpicker";

const requests = useAdminRequests();
const requestError = requests.error;
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
const renameDialog = ref(false);
const renaming = ref({ id: 0, from: "", name: "", nameMatched: false });
const hallDialog = ref(false);
const discDialog = ref(false);

const newProject = ref("");
const newHall = ref({ projectId: 0, name: "" });
const newDisc = ref({
  hallId: 0,
  name: "",
  template_id: null as number | null,
  color: "FFFFFF",
  // Leg labels (optionally linked to the discipline holding their trunks) or the
  // trunk labels of an existing leg discipline.
  role: "legs" as "legs" | "trunks",
  linkId: null as number | null,
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
  newDisc.value = { hallId, name: "", template_id: null, color: "FFFFFF", role: "legs", linkId: null };
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
  const { role, linkId } = newDisc.value;
  await api.post("/api/disciplines", {
    data_hall_id: newDisc.value.hallId,
    name: newDisc.value.name,
    template_id: newDisc.value.template_id,
    color: newDisc.value.color,
    ...(linkId == null ? {} : role === "trunks" ? { trunks_for_id: linkId } : { trunk_discipline_id: linkId }),
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

// What the new discipline can link to, by the same rules as the row picker: the same
// project, one level deep, and creating never moves an existing link.
const newDiscLinkOptions = computed(() => {
  const project = halls.value.find((h) => h.id === newDisc.value.hallId)?.project_id;
  const holders = new Set(disciplines.value.map((d) => d.trunk_discipline_id).filter((id) => id != null));
  const inProject = disciplines.value.filter((d) =>
    halls.value.find((h) => h.id === d.data_hall_id)?.project_id === project && d.trunk_discipline_id == null);
  return newDisc.value.role === "trunks" ? inProject.filter((d) => !holders.has(d.id)) : inProject;
});
const newDiscReady = computed(() =>
  !!newDisc.value.name.trim() && (newDisc.value.role === "legs" || newDisc.value.linkId != null));
function setNewDiscRole(role: "legs" | "trunks") {
  newDisc.value.role = role;
  newDisc.value.linkId = null;
}

// FloorHub finds a discipline by its exact name (and hall); a trunk discipline is reached
// through its legs' link instead, so only its rename is safe on this side alone.
function openRename(d: Discipline) {
  renaming.value = { id: d.id, from: d.name, name: d.name, nameMatched: !trunksFor(d) };
  requestError.value = "";  // an earlier action's error is not about this rename
  renameDialog.value = true;
}
const renameReady = computed(() => {
  const name = renaming.value.name.trim();
  return !!name && name !== renaming.value.from;
});
async function renameDisc() {
  await requests.run("renameDisc", async () => {
    try {
      await api.put(`/api/disciplines/${renaming.value.id}`, { name: renaming.value.name.trim() });
      renameDialog.value = false;
      await refresh();
      toast.add({ severity: "success", summary: `Renamed to ${renaming.value.name.trim()}`, life: 2500 });
    } catch (e: unknown) {
      requestError.value = e instanceof Error ? e.message : String(e);
    }
  });
}

// The discipline holding this one's trunk labels; a leg and its trunk share
// the workbook's Trunk# column.
function trunkOptions(d: Discipline) {
  return trunkTargets(d, disciplines.value, halls.value);
}
// A trunk discipline says whose trunks it holds, since it shows no picker.
function trunksFor(d: Discipline) {
  return disciplines.value.filter((o) => o.trunk_discipline_id === d.id).map((o) => o.name).join(", ");
}
async function linkTrunks(d: Discipline, trunkId: number | null) {
  await requests.run("linkTrunks", async () => {
    try {
      await api.put(`/api/disciplines/${d.id}`, { trunk_discipline_id: trunkId ?? null });
      await refresh();  // both ends of the link change what the other may pick
      toast.add({ severity: "success", summary: trunkId ? "Trunk labels linked" : "Trunk labels unlinked", life: 2500 });
    } catch (e: unknown) {
      requestError.value = e instanceof Error ? e.message : String(e);
      toast.add({ severity: "error", summary: "Link failed", detail: e instanceof Error ? e.message : String(e) });
    }
  });
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
    accept: async () => requests.run("delete", () => deleteWithForce(url, label, {
      remove: (target) => api.delete(target),
      confirmForce: (message) => new Promise<boolean>((resolve) => {
        confirm.require({
          header: "Labels are still in a print job",
          message,
          acceptLabel: "Discard records and delete",
          rejectLabel: "Keep them — cancel",
          acceptProps: { severity: "danger" },
          accept: () => resolve(true),
          reject: () => resolve(false),
          // Esc and the overlay bypass reject, and a pending delete must not hang.
          onHide: () => resolve(false),
        });
      }),
      fail: (message, forced) => {
        requestError.value = message;
        toast.add({
          severity: "error",
          summary: forced ? "Print still running" : "Delete failed",
          detail: message,
        });
      },
      reload: refresh,
    })),
  });
}
</script>

<template>
  <section class="admin-touch bg-surface border border-edge rounded-2xl p-5 shadow-sm">
    <p v-if="requestError" role="alert" class="text-danger my-3">{{ requestError }} — Please try again.</p>
    <p v-if="requests.busy('refresh')" role="status" class="text-ink-2 my-3">Loading…</p>
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

    <p v-if="projects.length === 0" class="text-ink-3">
      No projects yet.
    </p>

    <div
      v-for="p in projects"
      :key="p.id"
      class="bg-sunken rounded-xl p-3 mb-3 space-y-2"
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
          class="h-5 w-5 accent-accent"
          :checked="Boolean(p.require_rfid)"
          :disabled="savingRfid.has(p.id)"
          @change="toggleRfid(p, $event)"
        />
        RFID required before printing
        <span v-if="savingRfid.has(p.id)" role="status" class="font-normal text-ink-3">Saving…</span>
      </label>
      <p class="text-xs text-ink-3">Requires a configured RFID lookup service. Off by default.</p>
      <p v-if="rfidErrors[p.id]" role="alert" class="text-sm text-danger">Could not save: {{ rfidErrors[p.id] }}</p>

      <div
        v-for="h in hallsByProject.get(p.id) ?? []"
        :key="h.id"
        class="sm:ml-5 bg-surface border border-edge rounded-lg p-3 space-y-2"
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
        <p v-if="!discByHall.get(h.id)?.length" class="text-sm text-ink-3 px-3 py-2">No disciplines yet.</p>
        <div
          v-for="d in discByHall.get(h.id) ?? []"
          :key="d.id"
          class="sm:ml-5 bg-sunken border border-edge rounded-lg px-3 py-2 flex flex-wrap justify-between items-center gap-2"
        >
          <div class="flex items-center gap-2 min-w-0">
            <ColorPicker
              :model-value="d.color"
              format="hex"
              :pt="{ preview: { 'aria-label': `Color for ${d.name}` } }"
              @update:model-value="(v) => updateColor(d, String(v))"
            />
            <span class="font-semibold">{{ d.name }}</span>
            <Button :disabled="requests.pending.value.size > 0"
              icon="pi pi-pencil" size="small" text severity="secondary"
              :aria-label="`Rename ${d.name}`" title="Rename"
              @click="openRename(d)"
            />
            <!-- Role: a linked leg discipline, or the trunk labels another discipline prints. -->
            <span v-if="d.trunk_discipline_id" class="rounded px-1.5 py-0.5 text-xs font-semibold bg-accent-soft text-accent-ink">Legs</span>
            <span v-else-if="trunksFor(d)" class="rounded px-1.5 py-0.5 text-xs font-semibold bg-ok-soft text-ok">Trunks</span>
            <span class="text-xs text-ink-4">
              {{ d.label_count }} labels
            </span>
            <span v-if="trunksFor(d)" class="text-xs text-ink-3">· for {{ trunksFor(d) }}</span>
            <span v-if="d.missing_trunk_count" class="text-xs text-warn"
              title="These leg labels have no Trunk#, so their trunk label cannot print. Re-import the workbook with the Trunk# column.">
              · {{ d.missing_trunk_count === d.label_count ? 'No label has a Trunk#' : `${d.missing_trunk_count} labels have no Trunk#` }}. Re-import with the Trunk# column.
            </span>
          </div>
          <div class="flex flex-wrap items-center gap-2">
            <label
              class="inline-flex min-h-11 items-center gap-2 text-sm cursor-pointer select-none"
              :class="d.bundle_mode ? 'text-warn font-semibold' : 'text-ink-3'"
              title="Bundle mode: imports parse 'BUNDLE #N' headers and tag labels; Print shows a bundle picker. Re-import after turning on."
            >
              <input
                type="checkbox"
                class="h-5 w-5 accent-selected" :disabled="requests.busy('toggleBundle')"
                :checked="d.bundle_mode"
                @change="toggleBundle(d)"
              />
              <span>Bundle</span>
            </label>
            <span v-if="trunkOptions(d).length || d.trunk_discipline_id" class="text-xs text-ink-3">Trunk labels</span>
            <Select
              v-if="trunkOptions(d).length || d.trunk_discipline_id"
              :model-value="d.trunk_discipline_id ?? null"
              :options="trunkOptions(d)"
              option-label="name"
              option-value="id"
              show-clear
              placeholder="— trunk labels —"
              aria-label="Trunk labels discipline"
              class="w-full sm:w-auto sm:min-w-[180px]" :disabled="requests.busy('linkTrunks')"
              @update:model-value="(v) => linkTrunks(d, v)"
            />
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
          <p v-if="d.bundle_mode" class="w-full text-sm text-ink-2">Re-import this discipline’s files after enabling Bundle so labels are grouped by bundle.</p>
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
      <p v-if="requestError" role="alert" class="text-danger mt-3">{{ requestError }} — Please try again.</p>
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
      <p v-if="requestError" role="alert" class="text-danger mt-3">{{ requestError }} — Please try again.</p>
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
          <label for="projectstree-field-1" class="block text-xs font-bold text-ink-2 mb-1">Name</label>
          <InputText id="projectstree-field-1" aria-label="Name" v-model="newDisc.name" class="w-full" placeholder="GPU-MS" />
        </div>
        <fieldset>
          <legend class="block text-xs font-bold text-ink-2 mb-1">Labels</legend>
          <div class="grid grid-cols-2 gap-2">
            <label v-for="option in [
                { value: 'legs', title: 'Leg labels', hint: 'One label per leg' },
                { value: 'trunks', title: 'Trunk labels', hint: 'One label per trunk' },
              ] as const" :key="option.value"
              class="flex min-h-11 cursor-pointer items-start gap-2 rounded-lg border px-3 py-2"
              :class="newDisc.role === option.value ? 'border-selected bg-accent-soft' : 'border-edge'">
              <input type="radio" name="new-discipline-role" class="mt-1 h-4 w-4 accent-selected"
                :value="option.value" :checked="newDisc.role === option.value" @change="setNewDiscRole(option.value)" />
              <span>
                <span class="block text-sm font-semibold">{{ option.title }}</span>
                <span class="block text-xs text-ink-3">{{ option.hint }}</span>
              </span>
            </label>
          </div>
        </fieldset>
        <div>
          <label for="projectstree-field-link" class="block text-xs font-bold text-ink-2 mb-1">
            {{ newDisc.role === 'trunks' ? 'Trunk labels for' : 'Trunk labels' }}
            <span v-if="newDisc.role === 'legs'" class="font-normal text-ink-4">(optional)</span>
          </label>
          <Select input-id="projectstree-field-link"
            :aria-label="newDisc.role === 'trunks' ? 'Trunk labels for' : 'Trunk labels'"
            v-model="newDisc.linkId"
            :options="newDiscLinkOptions"
            option-label="name"
            option-value="id"
            show-clear
            :placeholder="newDisc.role === 'trunks' ? '— choose the leg discipline —' : '— link later —'"
            class="w-full"
          />
          <p v-if="newDisc.role === 'trunks' && !newDiscLinkOptions.length" class="text-xs text-warn mt-1">
            No leg discipline in this project is free to link. Unlink one first.
          </p>
        </div>
        <div>
          <label for="projectstree-field-2" class="block text-xs font-bold text-ink-2 mb-1">Template</label>
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
          <label class="block text-xs font-bold text-ink-2 mb-1">Color</label>
          <div class="flex items-center gap-2">
            <ColorPicker v-model="newDisc.color" format="hex" />
            <code class="text-xs text-ink-3">#{{ newDisc.color }}</code>
          </div>
        </div>
      </div>
      <p v-if="requestError" role="alert" class="text-danger mt-3">{{ requestError }} — Please try again.</p>
      <template #footer>
        <Button :disabled="requests.pending.value.size > 0" label="Cancel" severity="secondary" @click="discDialog = false" />
        <Button :disabled="requests.pending.value.size > 0 || !newDiscReady" label="Create" @click="createDisc" />
      </template>
    </Dialog>
    <Dialog
      v-model:visible="renameDialog"
      modal class="admin-touch"
      header="Rename discipline"
      :style="{ width: 'min(32rem, 94vw)' }"
    >
      <div class="space-y-3">
        <div>
          <label for="projectstree-rename" class="block text-xs font-bold text-ink-2 mb-1">Name</label>
          <InputText id="projectstree-rename" v-model="renaming.name" class="w-full" autofocus
            @keydown.enter="renameReady && renameDisc()" />
        </div>
        <p v-if="renaming.nameMatched" class="rounded-lg border border-warn-edge bg-warn-soft px-3 py-2 text-sm text-warn" role="note">
          FloorHub prints this discipline by its name. Rename it in FloorHub to the same name too,
          or its cable labels stop printing.
        </p>
        <p v-else class="text-xs text-ink-3">
          Trunk labels are found through their leg discipline, so FloorHub keeps printing them.
        </p>
      </div>
      <p v-if="requestError" role="alert" class="text-danger mt-3">{{ requestError }} — Please try again.</p>
      <template #footer>
        <Button :disabled="requests.pending.value.size > 0" label="Cancel" severity="secondary" @click="renameDialog = false" />
        <Button :disabled="requests.pending.value.size > 0 || !renameReady" label="Rename" @click="renameDisc" />
      </template>
    </Dialog>
  </section>
</template>

<style scoped>
@media (pointer: coarse) { .admin-touch :deep(.p-button), .admin-touch :deep(.p-select), .admin-touch :deep(.p-inputtext) { min-height:44px; } .admin-touch :deep(.p-button-icon-only) { min-width:44px; } }
.tree-toggle { display:flex; align-items:center; flex-wrap:wrap; gap:10px; min-height:44px; padding:6px 8px; min-width:0; text-align:left; border-radius:8px; cursor:pointer; overflow-wrap:anywhere; }
.tree-toggle:hover { background:var(--tds-accent-soft-hover); }
.tree-toggle:focus-visible { outline:2px solid var(--tds-accent); outline-offset:2px; }
.tree-toggle > i { font-size:12px; flex-shrink:0; }
.tree-count { font-size:13px; font-weight:400; color:var(--tds-ink-3); }
</style>
