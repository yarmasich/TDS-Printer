<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, useTemplateRef, watch } from "vue";
import { useLatestResource } from "@/composables/latestResource";
import { api } from "@/api/client";
import type {
  AuthName,
  Bundle,
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
import { useKiosk } from "@/stores/kiosk";

const props = defineProps<{ kiosk?: boolean }>();

const projects = useProjects();
const kioskStore = useKiosk();
const cart = useCart(props.kiosk ? "kiosk" : "print");
const printers = usePrinters();
const toast = useToast();

const selectedProject = ref<number | null>(null);
const selectedDiscipline = ref<number | null>(null);
const query = ref("");
const operator = ref("");
const reason = ref("");
const reasons = ref<Reason[]>([]);
const operators = ref<AuthName[]>([]);

const results = useLatestResource<SearchResponse>();
const { data: searchResults, loading: searching, error: searchError } = results;
const setupError = ref("");
// The query string that produced the current results (not the live input).
const lastQuery = ref("");

// When the operator searched a bare integer (e.g. "2"), that matches only the
// single trunk cable #2. Offer a one-click jump to the whole group "2.*"
// (#2 plus every #2.x breakout). Null when the query isn't a plain integer.
const groupSuggestion = computed(() =>
  /^\d+$/.test(lastQuery.value) ? `${lastQuery.value}.*` : null,
);
const addingAll = ref(false);
const ping = useLatestResource<PingResult>();
const printerPing = computed(() => ping.loading.value ? null : ping.data.value ?? undefined);

// Bundle picker — only for disciplines with bundle_mode. Selecting a bundle
// loads all its labels into the same results list the cable search uses.
const bundleResource = useLatestResource<Bundle[]>();
const bundles = computed(() => bundleResource.data.value ?? []);
const selectedBundle = ref<string | null>(null);
const bundleOptions = computed(() =>
  bundles.value.map((b) => ({ value: b.bundle, label: `#${b.bundle} · ${b.count}` })),
);

const cartLabelIds = computed(
  () => new Set(cart.items.map((i) => i.label_id).filter((id) => id != null)),
);

const pendingAddIds = computed(() => {
  if (!searchResults.value?.hits.length) return [];
  return searchResults.value.hits
    .map((h) => h.label_id)
    .filter((id) => !cartLabelIds.value.has(id));
});

const showAddAll = computed(
  () => (searchResults.value?.hits.length ?? 0) > 1,
);

// PrimeVue InputText wraps a native <input>; the template ref points
// at the component instance, so reach through `$el` to focus the real
// element.
const queryInput = useTemplateRef<{ $el: HTMLInputElement }>("queryInput");

let hydrating = false;
let mounted = true;
const isMounted = () => mounted;
onMounted(async () => {
  kioskStore.load();
  const loaded = await Promise.allSettled([
    projects.loadProjects(),
    api.get<Reason[]>("/api/reasons").then((r) => (reasons.value = r)),
    api.get<AuthName[]>("/api/auth-names").then((a) => (operators.value = a)),
    cart.fetch(),
  ]);
  if (!mounted) return;
  setupError.value = loaded.filter(r => r.status === "rejected").map(r => String(r.reason)).join("; ");
  if (props.kiosk && kioskStore.isReady) {
    hydrating = true;
    selectedProject.value = kioskStore.projectId;
    try {
      await projects.loadDisciplinesForProject(kioskStore.projectId!, isMounted);
      if (!mounted) return;
      selectedDiscipline.value = kioskStore.disciplineId;
    } catch (error) { setupError.value = String(error); }
    finally { hydrating = false; }
  }
  queryInput.value?.$el?.focus();
});

function resetResults() {
  results.clear();
  lastQuery.value = "";
  selectedBundle.value = null;
}
watch(selectedProject, async (pid) => {
  resetResults();
  ping.clear();
  bundleResource.clear();
  selectedDiscipline.value = null;
  if (hydrating) return;
  if (pid != null) {
    try { await projects.loadDisciplinesForProject(pid, isMounted); }
    catch { /* rendered through disciplineError */ }
  } else projects.clearDisciplines();
}, { flush: "sync" });

watch(selectedDiscipline, resetResults, { flush: "sync" });
watch(query, resetResults, { flush: "sync" });

const currentDiscipline = computed<Discipline | undefined>(() =>
  projects.disciplines.find((d) => d.id === selectedDiscipline.value),
);
watch(currentDiscipline, (d) => {
  ping.clear();
  bundleResource.clear();
  if (d?.printer_id) {
    const printerId = d.printer_id;
    void ping.run(async () => {
      try { return await printers.pingOne(printerId); }
      catch (error) { return { printer_id: printerId, ok: false, ms: null, error: String(error) }; }
    });
  }
  if (d?.bundle_mode) void bundleResource.run(() => api.get<Bundle[]>(`/api/labels/bundles?discipline_id=${d.id}`));
}, { flush: "sync" });

async function loadBundle(bundle: string | null) {
  resetResults();
  query.value = "";
  selectedBundle.value = bundle;
  if (!bundle || selectedDiscipline.value == null) return;
  const disciplineId = selectedDiscipline.value;
  lastQuery.value = `BUNDLE #${bundle}`;
  await results.run(() => api.get<SearchResponse>(
    `/api/labels/by-bundle?discipline_id=${disciplineId}&bundle=${encodeURIComponent(bundle)}`,
  ));
}

async function doSearch() {
  resetResults();
  const q = query.value.trim();
  if (!q) return;
  lastQuery.value = q;
  const params = new URLSearchParams({ q });
  if (selectedProject.value) params.set("project_id", String(selectedProject.value));
  if (selectedDiscipline.value) params.set("discipline_id", String(selectedDiscipline.value));
  await results.run(() => api.get<SearchResponse>(`/api/labels/search?${params}`));
}
function clearQuery() {
  query.value = "";
  resetResults();
  queryInput.value?.$el?.focus();
}
onUnmounted(() => { mounted = false; results.clear(); ping.clear(); bundleResource.clear(); });

// Re-run the search for the whole group (e.g. "2" → "2.*").
function searchGroup() {
  if (!groupSuggestion.value) return;
  query.value = groupSuggestion.value;
  doSearch();
}

// Called by StickyCart after a successful Print all — reset the search
// so the next batch starts from a clean screen with the cursor in the
// search box. Saves the operator from clearing the previous results by
// hand between cable runs.
function onPrinted() {
  clearQuery();
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

async function onAddAllToCart() {
  const ids = pendingAddIds.value;
  if (!ids.length) {
    toast.add({
      severity: "info",
      summary: "Already in cart",
      life: 2000,
    });
    return;
  }
  addingAll.value = true;
  try {
    await cart.addMany(ids);
    toast.add({
      severity: "success",
      summary: `Added ${ids.length} to cart`,
      life: 2500,
    });
  } catch (e: unknown) {
    toast.add({
      severity: "error",
      summary: "Could not add all",
      detail: e instanceof Error ? e.message : String(e),
    });
  } finally {
    addingAll.value = false;
  }
}
</script>

<template>
  <div class="space-y-4 pb-24" :class="{ 'print-panel--kiosk': kiosk }">
    <!-- ============ Context bar (desktop only) ============ -->
    <header
      v-if="!kiosk"
      class="bg-white border border-slate-200 rounded-2xl px-5 py-3 shadow-sm flex items-center gap-3 flex-wrap"
    >
      <div class="context-filters">
        <span class="text-xs font-bold text-slate-500 uppercase">Context</span>
        <Select
          v-model="selectedProject"
          :options="projects.projects"
          option-label="name"
          option-value="id"
          placeholder="Project"
          show-clear
          size="small"
          class="context-select"
        />
        <Select
          v-model="selectedDiscipline"
          :options="projects.disciplines"
          option-label="name"
          option-value="id"
          :disabled="!selectedProject || projects.loadingDisciplines"
          :loading="projects.loadingDisciplines"
          placeholder="Discipline"
          show-clear
          size="small"
          class="context-select"
        >
          <template #option="{ option }">
            <span
              v-if="option.data_hall_name"
              class="text-slate-400"
            >{{ option.data_hall_name }} / </span>{{ option.name }}
          </template>
          <template #value="{ placeholder }">
            <template v-if="currentDiscipline">
              <span
                v-if="currentDiscipline.data_hall_name"
                class="text-slate-400"
              >{{ currentDiscipline.data_hall_name }} / </span>{{ currentDiscipline.name }}
            </template>
            <span v-else>{{ placeholder }}</span>
          </template>
        </Select>
        <Select
          v-if="currentDiscipline?.bundle_mode"
          :model-value="selectedBundle"
          :options="bundleOptions"
          option-label="label"
          option-value="value"
          placeholder="Bundle"
          show-clear
          size="small"
          class="context-select"
          @update:model-value="loadBundle"
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
    <section
      class="bg-white border border-slate-200 rounded-2xl shadow-sm"
      :class="kiosk ? 'p-4 mx-3 mt-3' : 'p-6'"
    >
      <div class="search-row" :class="{ 'search-row--kiosk': kiosk }">
        <i class="pi pi-search search-icon"></i>
        <InputText
          ref="queryInput"
          v-model="query"
          placeholder="Cable ID or text"
          aria-label="Search cable labels"
          aria-describedby="search-help"
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
          :size="kiosk ? 'large' : 'large'"
          class="find-btn"
          @click="doSearch"
        />
      </div>

      <p id="search-help" class="text-sm text-slate-600 mt-3">Search by cable ID or text. Range: <b>45.5-7</b> · List: <b>45.5,6,7</b> · Whole group: <b>20.*</b></p>
      <p v-if="searchError" role="alert" class="text-red-700 mt-3">Search failed: {{ searchError }}. Try Find again.</p>
      <p v-if="setupError || projects.disciplineError" role="alert" class="text-red-700 mt-3">Could not load setup: {{ setupError || projects.disciplineError }}. Reload to retry.</p>
      <p v-if="bundleResource.error.value" role="alert" class="text-red-700 mt-3">Could not load bundles: {{ bundleResource.error.value }}. Choose the discipline again to retry.</p>
      <p v-if="cart.error" role="alert" class="text-red-700 mt-3">Could not load cart: {{ cart.error }}.</p>
      <!-- Operator / Reason chips (compact, opt-in) -->
      <div
        class="flex items-center gap-2 mt-4 flex-wrap"
        :class="kiosk ? 'text-base' : 'text-sm'"
      >
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
      :class="kiosk ? 'mx-3' : ''"
    >
      <div class="flex items-start justify-between gap-3 mb-3 flex-wrap">
        <h2 class="text-lg font-bold">
          <i class="pi pi-list-check text-sky-600 mr-1"></i>
          Results
          <span class="text-slate-400">({{ searchResults.hits.length }} displayed / {{ searchResults.total }} total)</span>
          <span
            v-if="searchResults.expanded.length > 1"
            class="text-sm font-normal text-slate-500 ml-2"
          >
            for {{ searchResults.expanded.join(", ") }}
          </span>
        </h2>
        <Button
          v-if="showAddAll && searchResults.hits.length > 0"
          :label="
            pendingAddIds.length
              ? `${searchResults.truncated ? 'Add displayed' : 'Add all'} (${pendingAddIds.length})`
              : 'All in cart'
          "
          icon="pi pi-plus"
          severity="success"
          :size="kiosk ? 'large' : undefined"
          :loading="addingAll"
          :disabled="!pendingAddIds.length"
          @click="onAddAllToCart"
        />
      </div>
      <p v-if="searchResults.truncated" class="text-sm text-amber-800 mb-3">Only the displayed labels will be added. Narrow your search to find the remaining matches.</p>
      <button
        v-if="groupSuggestion"
        type="button"
        class="w-full mb-3 flex items-center gap-2 text-left text-sm
               bg-sky-50 hover:bg-sky-100 text-sky-700 border border-sky-200
               rounded-xl px-3 py-2 transition-colors"
        @click="searchGroup"
      >
        <i class="pi pi-sitemap"></i>
        <span>
          Need every cable in group {{ lastQuery }}? Show the whole group
          <strong>{{ groupSuggestion }}</strong> ({{ lastQuery }} + {{ lastQuery }}.1, {{ lastQuery }}.2 …)
        </span>
        <i class="pi pi-arrow-right ml-auto"></i>
      </button>
      <p v-if="searchResults.hits.length === 0" class="text-slate-500">
        No matches.
      </p>
      <div v-else class="space-y-3">
        <ResultCard
          v-for="h in searchResults.hits"
          :key="h.label_id"
          :hit="h"
          :kiosk="kiosk"
          @cart="onAddToCart"
        />
      </div>
    </section>

    <section v-else class="empty-state" :class="kiosk ? 'mx-3 empty-state--kiosk' : ''">
      <i class="pi pi-search text-5xl text-slate-300 mb-3"></i>
      <p class="text-slate-500">
        {{
          kiosk
            ? "Type a cable id, range, or list to search."
            : "Pick a project / discipline above and type a cable id to begin."
        }}
      </p>
      <p v-if="!projects.projects.length" class="text-slate-400 text-sm mt-2">
        No projects yet —
        <RouterLink to="/admin" class="text-sky-600 underline">
          add one in Admin
        </RouterLink>.
      </p>
    </section>

    <!-- ============ Sticky cart ============ -->
    <StickyCart
      :operator="operator"
      :reason="reason"
      :kiosk="kiosk"
      @printed="onPrinted"
    />
  </div>
</template>

<style scoped>
.context-filters { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; flex: 1; min-width: 0; }
.context-select { flex: 1 1 160px; min-width: 0; max-width: 100%; }
.context-filters > span { flex-basis: 100%; }
@media (max-width: 480px) {
  .search-row, .search-row--kiosk { flex-wrap: wrap; padding: 6px 8px; gap: 6px; }
  .find-btn { flex-basis: 100%; }
  .search-input { width: 0; }
}

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

.print-panel--kiosk {
  padding-bottom: calc(100px + env(safe-area-inset-bottom));
  overflow-y: auto;
  flex: 1;
  min-height: 0;
}

.search-row--kiosk {
  padding: 10px 12px 10px 20px;
  border-radius: 20px;
}

.search-row--kiosk :deep(.search-input) {
  font-size: 26px !important;
  padding: 18px 6px !important;
}

.search-row--kiosk .search-icon {
  font-size: 24px;
}

.print-panel--kiosk :deep(.p-button) {
  touch-action: manipulation;
}

.print-panel--kiosk :deep(.find-btn) {
  min-height: 52px;
  min-width: 110px;
  font-size: 17px;
}

.print-panel--kiosk :deep(.p-select) {
  min-height: 48px;
  touch-action: manipulation;
}

.empty-state--kiosk {
  padding: 48px 20px;
}

.empty-state--kiosk .pi-search {
  font-size: 4rem !important;
}

.empty-state--kiosk p {
  font-size: 18px;
}
</style>
