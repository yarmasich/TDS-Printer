<script setup lang="ts">
import { computed, onMounted, ref, useTemplateRef, watch } from "vue";
import { api, ApiError } from "@/api/client";
import type {
  AuthName,
  Discipline,
  PingResult,
  Reason,
  SearchResponse,
} from "@/api/types";
import { useProjects } from "@/stores/projects";
import { useCart } from "@/stores/cart";
import { usePrinters } from "@/stores/printers";

import Select from "primevue/select";
import InputText from "primevue/inputtext";
import Button from "primevue/button";
import { useToast } from "primevue/usetoast";

import ResultCard from "@/components/print/ResultCard.vue";
import StickyCart from "@/components/print/StickyCart.vue";
import QuickPickChip from "@/components/print/QuickPickChip.vue";
import PingPill from "@/components/PingPill.vue";

const projects = useProjects();
const cart = useCart();
const printers = usePrinters();
const toast = useToast();

const selectedProject = ref<number | null>(null);
const selectedDiscipline = ref<number | null>(null);
const query = ref("");
const operator = ref("");
const reason = ref("");
const reasons = ref<Reason[]>([]);
const operators = ref<AuthName[]>([]);

const searchResults = ref<SearchResponse | null>(null);
const searching = ref(false);
const printerPing = ref<PingResult | null | undefined>(undefined);

// PrimeVue InputText wraps a native <input>; the template ref points
// at the component instance, so reach through `$el` to focus the real
// element.
const queryInput = useTemplateRef<{ $el: HTMLInputElement }>("queryInput");

onMounted(async () => {
  await Promise.all([
    projects.loadProjects(),
    api.get<Reason[]>("/api/reasons").then((r) => (reasons.value = r)),
    api.get<AuthName[]>("/api/auth-names").then((a) => (operators.value = a)),
    cart.fetch(),
  ]);
  // Auto-focus the search box so a kiosk operator can just start typing.
  queryInput.value?.$el?.focus();
});

watch(selectedProject, async (pid) => {
  selectedDiscipline.value = null;
  printerPing.value = undefined;
  if (pid != null) await projects.loadDisciplinesForProject(pid);
  else projects.disciplines = [];
});

const currentDiscipline = computed<Discipline | undefined>(() =>
  projects.disciplines.find((d) => d.id === selectedDiscipline.value),
);

watch(currentDiscipline, async (d) => {
  printerPing.value = undefined;
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
});

async function doSearch() {
  if (!query.value.trim()) return;
  searching.value = true;
  try {
    const params = new URLSearchParams({ q: query.value.trim() });
    if (selectedProject.value)
      params.set("project_id", String(selectedProject.value));
    if (selectedDiscipline.value)
      params.set("discipline_id", String(selectedDiscipline.value));
    searchResults.value = await api.get<SearchResponse>(
      `/api/labels/search?${params}`,
    );
  } catch (e: unknown) {
    toast.add({
      severity: "error",
      summary: "Search failed",
      detail: e instanceof Error ? e.message : String(e),
    });
  } finally {
    searching.value = false;
  }
}

function clearQuery() {
  query.value = "";
  searchResults.value = null;
  queryInput.value?.$el?.focus();
}

async function onPrintOne(labelId: number) {
  try {
    const res = await api.post<{ ok: boolean; log_id: number }>("/api/print", {
      label_id: labelId,
      operator: operator.value || "",
      reason: reason.value || "",
    });
    toast.add({
      severity: "success",
      summary: `Printed (log #${res.log_id})`,
      life: 2500,
    });
  } catch (e: unknown) {
    const msg =
      e instanceof ApiError
        ? e.message
        : e instanceof Error
          ? e.message
          : String(e);
    toast.add({ severity: "error", summary: "Print failed", detail: msg });
  }
}

async function onAddToCart(labelId: number) {
  try {
    await cart.add(labelId);
    toast.add({ severity: "info", summary: "Added to cart", life: 1500 });
  } catch (e: unknown) {
    toast.add({
      severity: "error",
      summary: "Could not add",
      detail: e instanceof Error ? e.message : String(e),
    });
  }
}
</script>

<template>
  <div class="space-y-4 pb-24">
    <!-- ============ Context bar ============ -->
    <header
      class="bg-white border border-slate-200 rounded-2xl px-5 py-3 shadow-sm flex items-center gap-3 flex-wrap"
    >
      <div class="flex items-center gap-2 flex-1 min-w-[260px]">
        <span class="text-xs font-bold text-slate-500 uppercase">Context</span>
        <Select
          v-model="selectedProject"
          :options="projects.projects"
          option-label="name"
          option-value="id"
          placeholder="Project"
          show-clear
          size="small"
          class="min-w-[160px]"
        />
        <Select
          v-model="selectedDiscipline"
          :options="projects.disciplines"
          option-label="name"
          option-value="id"
          :disabled="!selectedProject"
          placeholder="Discipline"
          show-clear
          size="small"
          class="min-w-[160px]"
        />
      </div>

      <div v-if="currentDiscipline" class="flex items-center gap-2 text-sm">
        <template v-if="!currentDiscipline.template_id">
          <span class="text-red-700 font-semibold">
            ⚠ no template — printing will fail
          </span>
          <RouterLink to="/admin" class="text-sky-600 underline">
            Open Admin
          </RouterLink>
        </template>
        <template v-else-if="currentDiscipline.printer_id">
          <span class="text-slate-600">Printer:</span>
          <b>{{ currentDiscipline.printer_name }}</b>
          <PingPill :ping="printerPing" />
        </template>
      </div>
    </header>

    <!-- ============ Hero search ============ -->
    <section class="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm">
      <div class="search-row">
        <i class="pi pi-search search-icon"></i>
        <InputText
          ref="queryInput"
          v-model="query"
          placeholder="Cable id, text, range 45.5-7 or list 45.5,6,7"
          class="search-input"
          autocomplete="off"
          @keydown.enter="doSearch"
        />
        <Button
          v-if="query"
          icon="pi pi-times"
          severity="secondary"
          text
          rounded
          aria-label="Clear"
          @click="clearQuery"
        />
        <Button
          label="Find"
          icon="pi pi-search"
          :loading="searching"
          size="large"
          @click="doSearch"
        />
      </div>

      <!-- Operator / Reason chips (compact, opt-in) -->
      <div class="flex items-center gap-2 mt-4 flex-wrap text-sm">
        <span class="text-slate-500">When printing:</span>
        <QuickPickChip
          v-model="operator"
          label="Operator"
          :options="operators"
          option-label="name"
          option-value="name"
        />
        <QuickPickChip
          v-model="reason"
          label="Reason"
          :options="reasons"
          option-label="text"
          option-value="text"
        />
      </div>
    </section>

    <!-- ============ Results / Empty ============ -->
    <section
      v-if="searchResults"
      class="bg-white border border-slate-200 rounded-2xl p-5 shadow-sm"
    >
      <h2 class="text-lg font-bold mb-3">
        <i class="pi pi-list-check text-sky-600 mr-1"></i>
        Results
        <span class="text-slate-400">({{ searchResults.total }})</span>
        <span
          v-if="searchResults.expanded.length > 1"
          class="text-sm font-normal text-slate-500 ml-2"
        >
          for {{ searchResults.expanded.join(", ") }}
        </span>
      </h2>
      <p v-if="searchResults.hits.length === 0" class="text-slate-500">
        No matches.
      </p>
      <div v-else class="space-y-3">
        <ResultCard
          v-for="h in searchResults.hits"
          :key="h.label_id"
          :hit="h"
          @print="onPrintOne"
          @cart="onAddToCart"
        />
      </div>
    </section>

    <section v-else class="empty-state">
      <i class="pi pi-search text-5xl text-slate-300 mb-3"></i>
      <p class="text-slate-500">
        Pick a project / discipline above and type a cable id to begin.
      </p>
      <p v-if="!projects.projects.length" class="text-slate-400 text-sm mt-2">
        No projects yet —
        <RouterLink to="/admin" class="text-sky-600 underline">
          add one in Admin
        </RouterLink>.
      </p>
    </section>

    <!-- ============ Sticky cart ============ -->
    <StickyCart :operator="operator" :reason="reason" />
  </div>
</template>

<style scoped>
.search-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 10px 6px 18px;
  border: 2px solid #e2e8f0;
  border-radius: 16px;
  background: #f8fafc;
  transition: border-color 0.15s;
}
.search-row:focus-within {
  border-color: #0284c7;
  background: #ffffff;
}
.search-icon {
  color: #94a3b8;
  font-size: 18px;
}
.search-input {
  flex: 1;
  min-width: 0;
}
:deep(.search-input) {
  border: 0 !important;
  background: transparent !important;
  font-size: 20px !important;
  padding: 14px 4px !important;
  box-shadow: none !important;
  outline: none !important;
}

.empty-state {
  text-align: center;
  padding: 64px 24px;
  background: #ffffff;
  border: 1px dashed #cbd5e1;
  border-radius: 16px;
}
</style>
