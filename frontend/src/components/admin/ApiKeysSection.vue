<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useToast } from "primevue/usetoast";
import { useConfirm } from "primevue/useconfirm";
import { api, apiUrl } from "@/api/client";
import type { ApiKey, ApiKeyCreated } from "@/api/types";

import InputText from "primevue/inputtext";
import Button from "primevue/button";
import Dialog from "primevue/dialog";

const toast = useToast();
const confirm = useConfirm();

const keys = ref<ApiKey[]>([]);
const newName = ref("");
const creating = ref(false);

// The plaintext is returned once; we hold it only until the dialog closes.
const created = ref<ApiKeyCreated | null>(null);

const printUrl = computed(() => {
  const u = apiUrl("/api/v1/print");
  // apiUrl returns a path when same-origin — make the example absolute.
  return u.startsWith("http") ? u : window.location.origin + u;
});

const curlExample = computed(() => {
  if (!created.value) return "";
  return [
    `curl -X POST ${printUrl.value} \\`,
    `  -H "X-API-Key: ${created.value.key}" \\`,
    `  -H "Content-Type: application/json" \\`,
    `  -d '{"cable": "1.1", "project": "Nscale", "discipline": "8K-IBLFSP"}'`,
  ].join("\n");
});

onMounted(refresh);

async function refresh() {
  keys.value = await api.get<ApiKey[]>("/api/api-keys");
}

async function create() {
  const name = newName.value.trim();
  if (!name) return;
  creating.value = true;
  try {
    created.value = await api.post<ApiKeyCreated>("/api/api-keys", { name });
    newName.value = "";
    await refresh();
  } catch (e: any) {
    toast.add({
      severity: "error",
      summary: "Could not create key",
      detail: e?.message ?? String(e),
      life: 4000,
    });
  } finally {
    creating.value = false;
  }
}

async function toggle(k: ApiKey) {
  await api.put(`/api/api-keys/${k.id}`, { enabled: !k.enabled });
  await refresh();
}

function remove(k: ApiKey) {
  confirm.require({
    message: `Revoke key "${k.name}"? Any app using it will stop printing immediately.`,
    header: "Revoke API key",
    icon: "pi pi-exclamation-triangle",
    acceptLabel: "Revoke",
    rejectLabel: "Cancel",
    acceptProps: { severity: "danger" },
    accept: async () => {
      await api.delete(`/api/api-keys/${k.id}`);
      await refresh();
    },
  });
}

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.add({ severity: "success", summary: "Copied", life: 1200 });
  } catch {
    toast.add({ severity: "warn", summary: "Copy failed — select manually", life: 2000 });
  }
}

function fmt(ts: string | null): string {
  if (!ts) return "—";
  return new Date(ts).toLocaleString();
}
</script>

<template>
  <section class="bg-white border border-slate-200 rounded-2xl p-5 shadow-sm">
    <div class="flex items-center justify-between mb-1">
      <h2 class="text-lg font-bold">
        API keys <span class="text-slate-400">({{ keys.length }})</span>
      </h2>
    </div>
    <p class="text-sm text-slate-500 mb-3">
      For external apps to print over <code class="text-xs">POST /api/v1/print</code>
      with an <code class="text-xs">X-API-Key</code> header. Prints land in History
      as <code class="text-xs">api:&lt;name&gt;</code>.
    </p>

    <div class="flex gap-2 mb-4">
      <InputText
        v-model="newName"
        placeholder="App name (e.g. FloorHub)"
        class="flex-1"
        @keydown.enter="create"
      />
      <Button label="Create key" :loading="creating" @click="create" />
    </div>

    <p v-if="!keys.length" class="text-sm text-slate-400 italic">
      No API keys yet.
    </p>

    <ul v-else class="space-y-1.5">
      <li
        v-for="k in keys"
        :key="k.id"
        class="flex items-center gap-3 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2"
      >
        <span
          class="inline-block w-2 h-2 rounded-full shrink-0"
          :class="k.enabled ? 'bg-emerald-500' : 'bg-slate-300'"
          :title="k.enabled ? 'Enabled' : 'Disabled'"
        />
        <div class="min-w-0 flex-1">
          <div class="font-medium text-sm truncate">{{ k.name }}</div>
          <div class="text-xs text-slate-400 font-mono">
            {{ k.prefix }}••••••
          </div>
        </div>
        <div class="text-xs text-slate-400 text-right hidden sm:block">
          <div>created {{ fmt(k.created_at) }}</div>
          <div>last used {{ fmt(k.last_used_at) }}</div>
        </div>
        <Button
          :label="k.enabled ? 'Disable' : 'Enable'"
          text
          size="small"
          @click="toggle(k)"
        />
        <Button
          icon="pi pi-trash"
          text
          severity="danger"
          size="small"
          aria-label="Revoke"
          @click="remove(k)"
        />
      </li>
    </ul>

    <!-- Plaintext shown exactly once -->
    <Dialog
      :visible="!!created"
      modal
      header="API key created"
      :style="{ width: 'min(40rem, 94vw)' }"
      @update:visible="(v: boolean) => { if (!v) created = null; }"
    >
      <template v-if="created">
        <p class="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-3">
          <i class="pi pi-exclamation-triangle mr-1" />
          Copy this key now — it is shown only once and cannot be retrieved later.
        </p>

        <label class="text-xs font-semibold text-slate-500">Key</label>
        <div class="flex gap-2 mb-4">
          <InputText :model-value="created.key" readonly class="flex-1 font-mono text-sm" />
          <Button icon="pi pi-copy" label="Copy" @click="copy(created.key)" />
        </div>

        <label class="text-xs font-semibold text-slate-500">Example request</label>
        <pre class="bg-slate-900 text-slate-100 text-xs rounded-lg p-3 overflow-x-auto whitespace-pre">{{ curlExample }}</pre>
        <div class="flex justify-end mt-2">
          <Button icon="pi pi-copy" label="Copy example" text size="small" @click="copy(curlExample)" />
        </div>
      </template>
      <template #footer>
        <Button label="Done" @click="created = null" />
      </template>
    </Dialog>
  </section>
</template>
