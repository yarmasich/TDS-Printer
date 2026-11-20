<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import Button from 'primevue/button';
import InputText from 'primevue/inputtext';
import Dialog from 'primevue/dialog';
import { useConfirm } from 'primevue/useconfirm';
import { api } from '@/api/client';
import { createdLabel, keyRequest, lastUsedLabel, projectTitle, purposeLabel, scopeSummary, type IntegrationScope } from '@/data/integrationKeys';

type Rule = {printer_ids: number[]; default_printer_id: number | null};
type Policy = {external_project_id: string; external_project_name?: string | null; revision: number; tds_project_id: number | null; cable_labels: Rule; qr_labels: Rule};
type Key = {id: number; name: string; prefix: string; enabled: boolean; scopes: string[]; created_at: string; last_used_at: string | null};
type Integration = {id: string; name: string; keys: Key[]; policies: Policy[]; printers: {id: number; name: string; purposes: string[]}[]};
const integrations = ref<Integration[]>([]);
const selectedId = ref('');
const selected = computed(() => integrations.value.find(item => item.id === selectedId.value));
const name = ref('');
const credentialName = ref('');
const permissions = ref<IntegrationScope[]>(['policy.read', 'policy.write', 'print']);
const scopeOptions: {value: IntegrationScope; label: string}[] = [
  {value: 'policy.read', label: 'Read printer assignments'},
  {value: 'policy.write', label: 'Manage printer assignments'},
  {value: 'print', label: 'Print assigned cable labels'},
];
const busy = ref(false);
const error = ref('');
const created = ref<{key: string; name: string} | null>(null);
const copied = ref(false);
const confirm = useConfirm();

async function load() {
  integrations.value = await api.get<Integration[]>('/api/integrations');
  if (!integrations.value.some(item => item.id === selectedId.value)) selectedId.value = integrations.value[0]?.id ?? '';
}
async function run(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true;
  error.value = '';
  try { await action(); } catch { error.value = 'Could not update integrations. Check the server connection and try again.'; }
  finally { busy.value = false; }
}
onMounted(() => { void run(load); });
async function addIntegration() {
  const value = name.value.trim();
  if (!value) { error.value = 'Enter an integration name.'; return; }
  await run(async () => {
    const added = await api.post<{id: string; name: string}>('/api/integrations', {name: value});
    await load();
    selectedId.value = added.id;
    name.value = '';
  });
}
async function createKey() {
  const integrationId = selectedId.value;
  if (!integrationId) return;
  let body;
  try { body = keyRequest(credentialName.value, permissions.value); }
  catch (problem) { error.value = problem instanceof Error ? problem.message : 'Check the key settings.'; return; }
  await run(async () => {
    // Keep the one-time credential even if refreshing metadata subsequently fails.
    created.value = await api.post<{key: string; name: string}>(`/api/integrations/${encodeURIComponent(integrationId)}/keys`, body);
    copied.value = false;
    credentialName.value = '';
    await load();
  });
}
async function toggleKey(key: Key) {
  // Scoped and legacy keys share one admin key store; only the listing is split.
  await run(async () => {
    await api.put(`/api/api-keys/${key.id}`, {enabled: !key.enabled});
    await load();
  });
}
function revokeKey(key: Key) {
  confirm.require({
    message: `Revoke key "${key.name}"? FloorHub stops printing through this key immediately. Project assignments stay in place.`,
    header: 'Revoke integration key',
    icon: 'pi pi-exclamation-triangle',
    acceptLabel: 'Revoke',
    rejectLabel: 'Cancel',
    acceptProps: {severity: 'danger'},
    accept: () => run(async () => {
      await api.delete(`/api/api-keys/${key.id}`);
      await load();
    }),
  });
}
async function copyKey() {
  if (!created.value) return;
  try { await navigator.clipboard.writeText(created.value.key); copied.value = true; }
  catch { copied.value = false; }
}
function printerNames(rule: Rule) {
  return rule.printer_ids.map(id => selected.value?.printers.find(printer => printer.id === id)?.name ?? `Printer #${id}`).join(', ') || 'None assigned';
}
function defaultName(rule: Rule) {
  if (rule.default_printer_id === null) return 'Explicit selection required';
  return selected.value?.printers.find(printer => printer.id === rule.default_printer_id)?.name ?? `Printer #${rule.default_printer_id}`;
}
</script>

<template>
  <section class="space-y-5">
    <header>
      <h2 class="text-lg font-bold text-ink">Integrations</h2>
      <p class="mt-1 text-sm text-ink-3">FloorHub assigns printers to projects for cable labels and QR labels. TDS-Printer checks each scoped cable print against those assignments.</p>
    </header>
    <p v-if="error" role="alert" class="rounded-lg border border-danger-edge bg-danger-soft p-3 text-sm text-danger">{{ error }}</p>
    <div class="rounded-xl border border-edge bg-surface p-5">
      <h3 class="font-semibold">Integration identity</h3>
      <p class="mt-1 mb-3 text-sm text-ink-3">Create one identity per connected FloorHub installation. Rotate its keys without creating a new identity; project assignments stay in place.</p>
      <form class="flex flex-wrap gap-2" @submit.prevent="addIntegration">
        <InputText v-model="name" aria-label="New integration name" placeholder="Integration name" :disabled="busy" class="min-w-0 flex-1" />
        <Button type="submit" label="Create integration" :disabled="busy || !name.trim()" />
      </form>
      <label for="routing-integration" class="mt-4 mb-1 block text-sm font-medium">Integration</label>
      <select id="routing-integration" v-model="selectedId" :disabled="busy" class="w-full rounded-lg border border-edge-strong bg-surface p-3 text-sm">
        <option value="">Select integration</option>
        <option v-for="item in integrations" :key="item.id" :value="item.id">{{ item.name }}</option>
      </select>
      <p v-if="selected" class="mt-2 break-all text-xs text-ink-4">ID: {{ selected.id }}</p>
    </div>
    <template v-if="selected">
      <div class="rounded-xl border border-edge bg-surface p-5">
        <h3 class="font-semibold">Integration keys</h3>
        <p class="mt-1 text-sm text-ink-3">Use a scoped key in FloorHub's backend. Existing legacy keys keep their existing access. A scoped key cannot use legacy print endpoints.</p>
        <form class="mt-4 space-y-3" @submit.prevent="createKey">
          <InputText v-model="credentialName" aria-label="Scoped key name" placeholder="Key name" :disabled="busy" class="w-full" />
          <div class="flex flex-wrap gap-4">
            <label v-for="scope in scopeOptions" :key="scope.value" class="flex items-center gap-2 text-sm">
              <input v-model="permissions" type="checkbox" :value="scope.value" :disabled="busy" /> {{ scope.label }}
            </label>
          </div>
          <Button type="submit" label="Create scoped key" :disabled="busy || !credentialName.trim() || !permissions.length" />
        </form>
        <p v-if="!selected.keys.length" class="mt-4 text-sm text-ink-3">No keys for this integration yet.</p>
        <ul v-else class="mt-4 space-y-2">
          <li v-for="key in selected.keys" :key="key.id" class="flex flex-wrap items-center gap-3 rounded-lg border border-edge bg-sunken px-3 py-2 text-sm">
            <span class="inline-block h-2 w-2 shrink-0 rounded-full" :class="key.enabled ? 'bg-ok-solid' : 'bg-edge-strong'" aria-hidden="true" />
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-baseline gap-x-2">
                <span class="truncate font-medium">{{ key.name }}</span>
                <span class="text-xs" :class="key.enabled ? 'text-ok' : 'text-ink-4'">{{ key.enabled ? 'Enabled' : 'Disabled' }}</span>
              </div>
              <p class="mt-0.5 text-xs text-ink-3"><span class="font-mono">{{ key.prefix }}••••••</span> · {{ scopeSummary(key.scopes) }}</p>
              <p class="mt-0.5 text-xs text-ink-4">{{ createdLabel(key.created_at) }} · {{ lastUsedLabel(key.last_used_at) }}</p>
            </div>
            <Button :label="key.enabled ? 'Disable' : 'Enable'" text size="small" :disabled="busy" @click="toggleKey(key)" />
            <Button icon="pi pi-trash" text severity="danger" size="small" :aria-label="`Revoke ${key.name}`" :disabled="busy" @click="revokeKey(key)" />
          </li>
        </ul>
      </div>
      <div class="rounded-xl border border-edge bg-surface p-5">
        <h3 class="font-semibold">Supported print types</h3>
        <ul class="mt-3 space-y-2">
          <li v-for="printer in selected.printers" :key="printer.id" class="flex flex-wrap justify-between gap-2 text-sm">
            <span>{{ printer.name }}</span><span class="text-ink-3">{{ purposeLabel(printer.purposes) }}</span>
          </li>
        </ul>
      </div>
      <div class="rounded-xl border border-edge bg-surface p-5">
        <h3 class="font-semibold">Project assignments</h3>
        <p class="mt-1 text-sm text-ink-3">Edit assignments in FloorHub → Label printers. QR assignments are configuration only; Inventory printing is a separate step.</p>
        <p v-if="!selected.policies.length" class="mt-4 text-sm text-ink-3">No projects assigned. Scoped printing is unavailable until a project has an allowed printer.</p>
        <article v-for="policy in selected.policies" :key="policy.external_project_id" class="mt-4 border-t border-edge pt-4 text-sm">
          <div class="break-words font-medium">{{ projectTitle(policy).title }}</div>
          <div v-if="projectTitle(policy).id" class="break-all text-xs text-ink-4">{{ projectTitle(policy).id }}</div>
          <p class="mt-1 text-xs text-ink-4">Revision {{ policy.revision }} · TDS project: {{ policy.tds_project_id ?? 'Not linked' }}</p>
          <p class="mt-2">Cable labels: {{ printerNames(policy.cable_labels) }}</p>
          <p class="text-xs text-ink-3">Default: {{ defaultName(policy.cable_labels) }}</p>
          <p class="mt-2">QR labels: {{ printerNames(policy.qr_labels) }}</p>
          <p class="text-xs text-ink-3">Default: {{ defaultName(policy.qr_labels) }}</p>
        </article>
      </div>
    </template>
    <Button label="Refresh" severity="secondary" :disabled="busy" @click="run(load)" />
    <Dialog :visible="!!created" modal header="Scoped key created" :style="{width:'min(38rem,94vw)'}" @update:visible="value => { if (!value) created = null; }">
      <template v-if="created">
        <p class="mb-4 text-sm text-warn">Save this key in the FloorHub backend as PRINT_SCOPED_SERVICE_API_KEY. It is shown only once.</p>
        <InputText aria-label="New scoped API key" :model-value="created.key" readonly class="w-full font-mono text-sm" />
        <Button class="mt-3" :label="copied ? 'Copied' : 'Copy key'" @click="copyKey" />
      </template>
      <template #footer><Button label="Done" @click="created = null" /></template>
    </Dialog>
  </section>
</template>
