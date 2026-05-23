<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { useConfirm } from "primevue/useconfirm";
import { useToast } from "primevue/usetoast";
import { useProjects } from "@/stores/projects";
import { useKiosk } from "@/stores/kiosk";
import PrintPanel from "@/pages/PrintPanel.vue";
import Select from "primevue/select";
import Button from "primevue/button";
import PingPill from "@/components/PingPill.vue";
import { usePrinters } from "@/stores/printers";
import type { Discipline, PingResult, Project } from "@/api/types";

const router = useRouter();
const confirm = useConfirm();
const toast = useToast();
const projects = useProjects();
const kiosk = useKiosk();
const printers = usePrinters();

const showSetup = ref(true);
/** PrimeVue Select binds full option objects, not raw ids. */
const setupProject = ref<Project | null>(null);
const setupDiscipline = ref<Discipline | null>(null);
const printerPing = ref<PingResult | null | undefined>(undefined);

/** Skip discipline reset while restoring saved kiosk context. */
let hydratingSetup = false;

const currentDiscipline = computed<Discipline | undefined>(() =>
  projects.disciplines.find((d) => d.id === kiosk.disciplineId),
);

const contextLine = computed(() => {
  const d = currentDiscipline.value;
  const proj = projects.projects.find((p) => p.id === kiosk.projectId);
  if (!d || !proj) return "Tap to choose site";
  return `${proj.name} · ${d.name}`;
});

const canStart = computed(
  () => setupProject.value?.id != null && setupDiscipline.value?.id != null,
);

function pickProject(v: Project | number | null | undefined): Project | null {
  if (v == null) return null;
  if (typeof v === "number") {
    return projects.projects.find((p) => p.id === v) ?? null;
  }
  return v;
}

function pickDiscipline(
  v: Discipline | number | null | undefined,
): Discipline | null {
  if (v == null) return null;
  if (typeof v === "number") {
    return projects.disciplines.find((d) => d.id === v) ?? null;
  }
  return v;
}

onMounted(async () => {
  kiosk.load();
  await projects.loadProjects();
  if (kiosk.isReady) {
    hydratingSetup = true;
    setupProject.value = pickProject(kiosk.projectId);
    await projects.loadDisciplinesForProject(kiosk.projectId!);
    setupDiscipline.value = pickDiscipline(kiosk.disciplineId);
    hydratingSetup = false;
    showSetup.value = false;
  }
});

watch(setupProject, async (proj, oldProj) => {
  if (hydratingSetup) return;
  const id = proj?.id ?? null;
  const oldId = oldProj?.id ?? null;
  if (id === oldId) return;
  setupDiscipline.value = null;
  if (id != null) await projects.loadDisciplinesForProject(id);
  else projects.disciplines = [];
});

watch(
  () => kiosk.disciplineId,
  async (id) => {
    printerPing.value = undefined;
    const d = projects.disciplines.find((x) => x.id === id);
    if (!d?.printer_id) return;
    try {
      printerPing.value = null;
      printerPing.value = await printers.pingOne(d.printer_id);
    } catch {
      printerPing.value = {
        printer_id: d.printer_id,
        ok: false,
        ms: null,
        error: "check failed",
      };
    }
  },
  { immediate: true },
);

async function startKiosk() {
  const projectId = setupProject.value?.id;
  const disciplineId = setupDiscipline.value?.id;
  if (projectId == null || disciplineId == null) {
    toast.add({
      severity: "warn",
      summary: "Choose project and discipline",
      life: 3000,
    });
    return;
  }

  try {
    kiosk.save(projectId, disciplineId);
    hydratingSetup = true;
    await projects.loadDisciplinesForProject(projectId);
    setupDiscipline.value =
      projects.disciplines.find((d) => d.id === disciplineId) ??
      setupDiscipline.value;
    hydratingSetup = false;
    showSetup.value = false;
  } catch (e: unknown) {
    hydratingSetup = false;
    toast.add({
      severity: "error",
      summary: "Could not start kiosk",
      detail: e instanceof Error ? e.message : String(e),
      life: 5000,
    });
  }
}

async function openSetup() {
  showSetup.value = true;
  hydratingSetup = true;
  if (kiosk.projectId != null) {
    await projects.loadDisciplinesForProject(kiosk.projectId);
  }
  setupProject.value = pickProject(kiosk.projectId);
  setupDiscipline.value = pickDiscipline(kiosk.disciplineId);
  hydratingSetup = false;
}

function exitKiosk() {
  confirm.require({
    header: "Exit kiosk?",
    message: "Return to the full app. The tablet will keep this site selected.",
    icon: "pi pi-sign-out",
    acceptLabel: "Exit",
    rejectLabel: "Stay",
    accept: () => router.push("/"),
  });
}

async function tryFullscreen() {
  try {
    if (!document.fullscreenElement) {
      await document.documentElement.requestFullscreen();
    }
  } catch {
    /* Safari / locked-down browsers may block this */
  }
}
</script>

<template>
  <div class="kiosk-root">
    <header v-if="!showSetup" class="kiosk-bar">
      <div class="kiosk-bar-main">
        <span class="kiosk-brand">TDS Print</span>
        <button type="button" class="kiosk-site" @click="openSetup">
          {{ contextLine }}
          <i class="pi pi-chevron-down kiosk-site-caret" aria-hidden="true"></i>
        </button>
        <template v-if="currentDiscipline?.printer_id">
          <span class="kiosk-printer">{{ currentDiscipline.printer_name }}</span>
          <PingPill :ping="printerPing" />
        </template>
        <span
          v-else-if="currentDiscipline && !currentDiscipline.template_id"
          class="kiosk-warn"
        >
          No template
        </span>
      </div>
      <div class="kiosk-bar-actions">
        <Button
          icon="pi pi-expand"
          severity="secondary"
          text
          rounded
          aria-label="Fullscreen"
          @click="tryFullscreen"
        />
        <Button
          icon="pi pi-sign-out"
          severity="secondary"
          text
          rounded
          aria-label="Exit kiosk"
          @click="exitKiosk"
        />
      </div>
    </header>

    <section v-if="showSetup" class="kiosk-setup">
      <div class="kiosk-setup-card">
        <h1 class="kiosk-setup-title">Kiosk setup</h1>
        <p class="kiosk-setup-lead">
          Choose the site once for this tablet. Operators only search and print
          after that.
        </p>

        <label class="kiosk-label">Project</label>
        <Select
          v-model="setupProject"
          :options="projects.projects"
          option-label="name"
          placeholder="Select project"
          append-to="body"
          fluid
          class="kiosk-select"
        />

        <label class="kiosk-label">Discipline</label>
        <Select
          v-model="setupDiscipline"
          :options="projects.disciplines"
          option-label="name"
          :disabled="!setupProject"
          placeholder="Select discipline"
          append-to="body"
          fluid
          class="kiosk-select"
        />

        <Button
          type="button"
          label="Start kiosk"
          icon="pi pi-play"
          size="large"
          fluid
          class="kiosk-start-btn"
          :disabled="!canStart"
          @click="startKiosk"
        />

        <Button
          type="button"
          label="Back to full app"
          severity="secondary"
          text
          fluid
          class="mt-2"
          @click="router.push('/')"
        />
      </div>
    </section>

    <PrintPanel v-else kiosk class="kiosk-print" />
  </div>
</template>

<style scoped>
.kiosk-root {
  min-height: 100dvh;
  display: flex;
  flex-direction: column;
  background: #f1f5f9;
  padding-top: env(safe-area-inset-top);
}

.kiosk-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  padding-left: max(14px, env(safe-area-inset-left));
  padding-right: max(14px, env(safe-area-inset-right));
  background: linear-gradient(90deg, #0f172a, #1e3a5f);
  color: #fff;
  flex-shrink: 0;
}

.kiosk-bar-main {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  min-width: 0;
}

.kiosk-brand {
  font-size: 18px;
  font-weight: 800;
  letter-spacing: -0.02em;
}

.kiosk-site {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.25);
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  max-width: min(420px, 55vw);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kiosk-site-caret {
  font-size: 11px;
  opacity: 0.8;
}

.kiosk-printer {
  font-size: 13px;
  opacity: 0.85;
}

.kiosk-warn {
  font-size: 13px;
  font-weight: 700;
  color: #fecaca;
}

.kiosk-bar-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

.kiosk-setup {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px 20px;
  overflow: auto;
  -webkit-overflow-scrolling: touch;
}

.kiosk-setup-card {
  position: relative;
  z-index: 20;
  width: 100%;
  max-width: 480px;
  background: #fff;
  border-radius: 20px;
  padding: 28px 24px;
  box-shadow: 0 12px 40px rgba(15, 23, 42, 0.12);
  isolation: isolate;
}

.kiosk-setup-title {
  margin: 0 0 8px;
  font-size: 28px;
  font-weight: 800;
  color: #0f172a;
}

.kiosk-setup-lead {
  margin: 0 0 24px;
  font-size: 15px;
  line-height: 1.45;
  color: #64748b;
}

.kiosk-label {
  display: block;
  font-size: 13px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #475569;
  margin-bottom: 8px;
  margin-top: 16px;
}

.kiosk-label:first-of-type {
  margin-top: 0;
}

.kiosk-setup-card :deep(.kiosk-select),
.kiosk-setup-card :deep(.p-select) {
  width: 100%;
}

.kiosk-setup-card :deep(.p-select-label),
.kiosk-setup-card :deep(.p-select-dropdown) {
  pointer-events: none;
}

.kiosk-setup-card :deep(.p-select) {
  min-height: 52px;
  touch-action: manipulation;
}

.kiosk-setup-card :deep(.p-button) {
  width: 100%;
  justify-content: center;
  min-height: 52px;
  touch-action: manipulation;
}

.kiosk-start-btn {
  margin-top: 28px;
}

.kiosk-print {
  flex: 1;
  min-height: 0;
}
</style>
