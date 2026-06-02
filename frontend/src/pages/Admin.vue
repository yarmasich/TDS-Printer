<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import PrintersSection from "@/components/admin/PrintersSection.vue";
import TemplatesSection from "@/components/admin/TemplatesSection.vue";
import ProjectsTree from "@/components/admin/ProjectsTree.vue";
import ImportsSection from "@/components/admin/ImportsSection.vue";
import ListsSection from "@/components/admin/ListsSection.vue";
import ApiKeysSection from "@/components/admin/ApiKeysSection.vue";
import HistorySection from "@/components/admin/HistorySection.vue";

interface NavItem {
  key: string;
  label: string;
  icon: string;
  component: any;
}

const sections: NavItem[] = [
  { key: "printers", label: "Printers", icon: "pi pi-print", component: PrintersSection },
  { key: "templates", label: "Templates", icon: "pi pi-tags", component: TemplatesSection },
  { key: "projects", label: "Projects · Halls · Disciplines", icon: "pi pi-sitemap", component: ProjectsTree },
  { key: "import", label: "Import labels", icon: "pi pi-upload", component: ImportsSection },
  { key: "lists", label: "Reasons & Operators", icon: "pi pi-list", component: ListsSection },
  { key: "api-keys", label: "API keys", icon: "pi pi-key", component: ApiKeysSection },
  { key: "history", label: "Print history", icon: "pi pi-history", component: HistorySection },
];

const keys = sections.map((s) => s.key);
const DEFAULT_KEY = sections[0]!.key;

function fromHash(): string {
  const h = window.location.hash.replace(/^#/, "");
  return keys.includes(h) ? h : DEFAULT_KEY;
}

const active = ref(fromHash());

const activeComponent = computed(
  () => sections.find((s) => s.key === active.value)?.component,
);

function select(key: string) {
  active.value = key;
  if (window.location.hash !== `#${key}`) {
    // Preserve Vue Router's history.state — passing null wipes it and the
    // router warns about a manually-replaced state.
    history.replaceState(history.state, "", `#${key}`);
  }
}

function onHashChange() {
  active.value = fromHash();
}

onMounted(() => window.addEventListener("hashchange", onHashChange));
onUnmounted(() => window.removeEventListener("hashchange", onHashChange));
</script>

<template>
  <div class="flex flex-col md:flex-row gap-4">
    <!-- Settings menu -->
    <nav
      class="md:w-60 shrink-0 md:sticky md:top-4 md:self-start
             bg-white border border-slate-200 rounded-2xl p-2 shadow-sm"
    >
      <ul class="flex md:flex-col flex-wrap gap-1">
        <li v-for="s in sections" :key="s.key" class="flex-1 md:flex-none">
          <button
            type="button"
            class="w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-sm text-left
                   transition-colors"
            :class="
              active === s.key
                ? 'bg-sky-50 text-sky-700 font-semibold'
                : 'text-slate-600 hover:bg-slate-50'
            "
            :aria-current="active === s.key ? 'page' : undefined"
            @click="select(s.key)"
          >
            <i :class="s.icon" class="text-base shrink-0" />
            <span class="truncate">{{ s.label }}</span>
          </button>
        </li>
      </ul>
    </nav>

    <!-- Active section -->
    <div class="min-w-0 flex-1">
      <KeepAlive>
        <component :is="activeComponent" :key="active" />
      </KeepAlive>
    </div>
  </div>
</template>
