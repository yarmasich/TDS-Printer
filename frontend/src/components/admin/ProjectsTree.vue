<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { api } from "@/api/client";
import type { DataHall, Discipline, Project, Template } from "@/api/types";
import { useToast } from "primevue/usetoast";
import { useConfirm } from "primevue/useconfirm";

import Button from "primevue/button";
import InputText from "primevue/inputtext";
import Select from "primevue/select";
import Dialog from "primevue/dialog";

const toast = useToast();
const confirm = useConfirm();

const projects = ref<Project[]>([]);
const halls = ref<DataHall[]>([]);
const disciplines = ref<Discipline[]>([]);
const templates = ref<Template[]>([]);

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
  await api.post("/api/projects", { name: newProject.value });
  newProject.value = "";
  projectDialog.value = false;
  await refresh();
}

async function createHall() {
  await api.post("/api/halls", {
    project_id: newHall.value.projectId,
    name: newHall.value.name,
  });
  hallDialog.value = false;
  await refresh();
}

async function createDisc() {
  await api.post("/api/disciplines", {
    data_hall_id: newDisc.value.hallId,
    name: newDisc.value.name,
    template_id: newDisc.value.template_id,
    color: newDisc.value.color,
  });
  discDialog.value = false;
  await refresh();
}

async function bindTemplate(d: Discipline, templateId: number | null) {
  try {
    await api.put(`/api/disciplines/${d.id}`, { template_id: templateId });
    await refresh();
    toast.add({ severity: "success", summary: "Template bound", life: 1500 });
  } catch (e: unknown) {
    toast.add({
      severity: "error",
      summary: "Bind failed",
      detail: e instanceof Error ? e.message : String(e),
    });
  }
}

function del(url: string, label: string) {
  confirm.require({
    message: `Delete ${label}?`,
    accept: async () => {
      await api.delete(url);
      await refresh();
    },
  });
}
</script>

<template>
  <section class="bg-white border border-slate-200 rounded-2xl p-5 shadow-sm">
    <div class="flex items-center justify-between mb-3">
      <h2 class="text-lg font-bold">Projects · Halls · Disciplines</h2>
      <Button
        label="Add project"
        icon="pi pi-plus"
        size="small"
        @click="
          newProject = '';
          projectDialog = true;
        "
      />
    </div>

    <p v-if="projects.length === 0" class="text-slate-500">
      No projects yet.
    </p>

    <div
      v-for="p in projects"
      :key="p.id"
      class="bg-slate-50 rounded-xl p-3 mb-3 space-y-2"
    >
      <div class="flex justify-between items-center">
        <b>📁 {{ p.name }}</b>
        <div class="flex gap-1">
          <Button
            label="+ hall"
            size="small"
            text
            @click="openHall(p.id)"
          />
          <Button
            icon="pi pi-trash"
            size="small"
            text
            severity="danger"
            aria-label="Delete project"
            @click="del('/api/projects/' + p.id, p.name)"
          />
        </div>
      </div>

      <div
        v-for="h in hallsByProject.get(p.id) ?? []"
        :key="h.id"
        class="ml-5 bg-white border border-slate-200 rounded-lg p-3 space-y-2"
      >
        <div class="flex justify-between items-center">
          <span>🏢 {{ h.name }}</span>
          <div class="flex gap-1">
            <Button
              label="+ discipline"
              size="small"
              text
              @click="openDisc(h.id)"
            />
            <Button
              icon="pi pi-trash"
              size="small"
              text
              severity="danger"
              aria-label="Delete hall"
              @click="del('/api/halls/' + h.id, h.name)"
            />
          </div>
        </div>

        <div
          v-for="d in discByHall.get(h.id) ?? []"
          :key="d.id"
          class="ml-5 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 flex justify-between items-center gap-2"
        >
          <div class="flex items-center gap-2 min-w-0">
            <span
              class="inline-block w-4 h-4 rounded border border-slate-300"
              :style="{ background: '#' + d.color }"
            />
            <span class="font-semibold">{{ d.name }}</span>
            <span class="text-xs text-slate-400">
              {{ d.label_count }} labels
            </span>
          </div>
          <div class="flex items-center gap-2">
            <Select
              :model-value="d.template_id"
              :options="templates"
              option-label="name"
              option-value="id"
              show-clear
              placeholder="— template —"
              class="!min-w-[180px]"
              @update:model-value="(v) => bindTemplate(d, v)"
            />
            <Button
              icon="pi pi-trash"
              size="small"
              text
              severity="danger"
              aria-label="Delete discipline"
              @click="del('/api/disciplines/' + d.id, d.name)"
            />
          </div>
        </div>
      </div>
    </div>

    <!-- Dialogs -->
    <Dialog
      v-model:visible="projectDialog"
      modal
      header="New project"
      :style="{ width: '24rem' }"
    >
      <InputText v-model="newProject" class="w-full" placeholder="Project name" />
      <template #footer>
        <Button label="Cancel" severity="secondary" @click="projectDialog = false" />
        <Button label="Create" @click="createProject" />
      </template>
    </Dialog>

    <Dialog
      v-model:visible="hallDialog"
      modal
      header="New data hall"
      :style="{ width: '24rem' }"
    >
      <InputText v-model="newHall.name" class="w-full" placeholder="DH3" />
      <template #footer>
        <Button label="Cancel" severity="secondary" @click="hallDialog = false" />
        <Button label="Create" @click="createHall" />
      </template>
    </Dialog>

    <Dialog
      v-model:visible="discDialog"
      modal
      header="New discipline"
      :style="{ width: '32rem' }"
    >
      <div class="space-y-3">
        <div>
          <label class="block text-xs font-bold text-slate-600 mb-1">Name</label>
          <InputText v-model="newDisc.name" class="w-full" placeholder="GPU-MS" />
        </div>
        <div>
          <label class="block text-xs font-bold text-slate-600 mb-1">Template</label>
          <Select
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
          <label class="block text-xs font-bold text-slate-600 mb-1">Color (hex, no #)</label>
          <InputText v-model="newDisc.color" class="w-full" />
        </div>
      </div>
      <template #footer>
        <Button label="Cancel" severity="secondary" @click="discDialog = false" />
        <Button label="Create" @click="createDisc" />
      </template>
    </Dialog>
  </section>
</template>
