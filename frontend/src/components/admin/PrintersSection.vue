<script setup lang="ts">
import { useAdminRequests } from "@/composables/adminRequests";
const requests = useAdminRequests();
const requestError = requests.error;
import { computed, onMounted, reactive, ref } from "vue";
import { api } from "@/api/client";
import type { Printer, PrinterProtocol, PrinterStatus, TestPrintResult } from "@/api/types";
import { brandForModel, modelsForBrand, settingsForModel, isValidPrinterSelection, changePrinterBrand, type PrinterBrand } from "@/data/printerModels";
import { communityUpdate, printerMediaMismatch, type CommunityMode } from "@/data/printerSettings";
import { groupPrinters } from "@/data/printerGroups";
import { usePrinters } from "@/stores/printers";
import { useToast } from "primevue/usetoast";
import { useConfirm } from "primevue/useconfirm";

import DataTable from "primevue/datatable";
import Column from "primevue/column";
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import InputText from "primevue/inputtext";
import InputNumber from "primevue/inputnumber";
import Select from "primevue/select";
import PingPill from "@/components/PingPill.vue";

const store = usePrinters();
const printerGroups = computed(() => groupPrinters(store.printers));
const printerTableStyle = { width: "100%", tableLayout: "fixed", minWidth: "1200px" } as const;
const printerColumnStyles = {
  name: { width: "160px" },
  address: { width: "220px" },
  protocol: { width: "240px" },
  status: { width: "180px" },
  actions: { width: "260px" },
};
const toast = useToast();
const confirm = useConfirm();

const brandOptions: {label: string; value: PrinterBrand}[] = [
  {label: "Panduit", value: "panduit"},
  {label: "Brother", value: "brother"},
  {label: "Other / custom", value: "custom"},
];
const selectedBrand = ref<PrinterBrand | null>(null);
let appliedBrand: PrinterBrand | null = null;
const selectedModel = ref<Printer["model"] | null>(null);

const dialogOpen = ref(false);
const communityMode = ref<CommunityMode>('keep');
const communityValue = ref('');
const communityConfigured = ref(false);
const savedForm = ref('');
const checkedStatus = ref<PrinterStatus | null>(null);
const checkingStatus = ref(false);
let statusGeneration = 0;
const settingsDirty = computed(() => JSON.stringify(form) !== savedForm.value || communityMode.value !== 'keep');
const statusLabel = computed(() => {
  if (!checkedStatus.value) return '';
  if (checkedStatus.value.connection_state === 'busy') return 'Printer busy · status check deferred';
  if (!checkedStatus.value.online) return 'Printer unreachable';
  const state = checkedStatus.value.device_status?.state;
  return ({ready: 'Ready', printing: 'Printing', busy: 'Busy', error: 'Printer error', no_media: 'No media', cover_open: 'Cover open'} as Record<string, string>)[state ?? ''] ?? 'Reachable · device status unknown';
});
const mediaMismatch = computed(() => {
  const width = checkedStatus.value?.device_status?.media_width_mm;
  return printerMediaMismatch(form.qr_media_id, width, checkedStatus.value?.device_status?.media_type);
});
function resetSettingsState() {
  statusGeneration++; checkingStatus.value = false;
  communityMode.value = 'keep'; communityValue.value = ''; checkedStatus.value = null;
  savedForm.value = JSON.stringify(form);
}
async function checkSavedStatus() {
  if (!editId.value || settingsDirty.value || checkingStatus.value) return;
  checkingStatus.value = true;
  const id = editId.value;
  const seq = ++statusGeneration;
  try {
    const result = await api.get<PrinterStatus>(`/api/printers/${id}/status`);
    if (seq === statusGeneration && dialogOpen.value && editId.value === id && !settingsDirty.value) checkedStatus.value = result;
  } catch { if (seq === statusGeneration) requestError.value = 'Could not check printer status. Try again.'; }
  finally { if (seq === statusGeneration) checkingStatus.value = false; }
}
const editId = ref<number | null>(null);
const testingId = ref<number | null>(null);
const form = reactive<Omit<Printer, "id">>({
  name: "",
  ip: "",
  port: 9100,
  notes: "",
  protocol: "epl2",
  dpi: 300,
  model: "custom",
  snmp_enabled: true,
  snmp_port: 161,
  qr_media_id: 'DK-2246',
  qr_label_length_mm: 60,
});

const modelOptions = computed(() => modelsForBrand(selectedBrand.value));
const effectiveSettings = computed(() => selectedModel.value
  ? settingsForModel(selectedModel.value, form)
  : {model: form.model, protocol: form.protocol, dpi: form.dpi});
const invalidManualDpi = computed(() => selectedBrand.value === 'custom' && ![203, 300, 600].includes(form.dpi));
const validSelection = computed(() => isValidPrinterSelection(selectedBrand.value, selectedModel.value, form.protocol, form.dpi));
const protocolOptions = computed<{label: string; value: PrinterProtocol}[]>(() => selectedBrand.value === 'brother'
  ? [{label: 'Brother QL raster — QR labels', value: 'brother_ql'}]
  : [{label: 'Legacy EZPL — existing settings', value: 'epl2'}, {label: 'EZPL', value: 'ezpl'}, {label: 'JScript', value: 'jscript'}]);
const dpiOptions = computed(() => (selectedBrand.value === 'custom' ? [203, 300, 600] : [effectiveSettings.value.dpi])
  .map(value => ({label: `${value} dpi`, value})));

function changeBrand() {
  if (selectedBrand.value !== appliedBrand) {
    communityMode.value = 'keep';
    communityValue.value = '';
  }
  const next = changePrinterBrand({brand: appliedBrand, model: selectedModel.value, protocol: form.protocol, dpi: form.dpi}, selectedBrand.value);
  appliedBrand = next.brand;
  selectedModel.value = next.model;
  form.model = next.model ?? 'custom';
  form.protocol = next.protocol;
  form.dpi = next.dpi;
}
function applyModel() {
  if (selectedModel.value) Object.assign(form, settingsForModel(selectedModel.value, form));
}

async function refresh() { await requests.run("refresh", async () => { await store.loadAll(); await store.pingAll(); }); }
onMounted(refresh);

function openCreate() {
  requestError.value = "";
  appliedBrand = null;
  selectedBrand.value = null;
  selectedModel.value = null;
  editId.value = null;
  form.name = "";
  form.ip = "";
  form.port = 9100;
  form.notes = "";
  form.protocol = "epl2";
  form.dpi = 300;
  form.model = "custom";
  form.snmp_enabled = true; form.snmp_port = 161;
  form.qr_media_id = 'DK-2246'; form.qr_label_length_mm = 60;
  communityConfigured.value = false;
  resetSettingsState();
  dialogOpen.value = true;
}

async function openEdit(p: Printer) {
  requestError.value = "";
  selectedBrand.value = brandForModel(p.model);
  appliedBrand = selectedBrand.value;
  selectedModel.value = p.model ?? 'custom';
  editId.value = p.id;
  Object.assign(form, {
    name: p.name,
    ip: p.ip,
    port: p.port,
    notes: p.notes,
    protocol: p.protocol,
    dpi: p.dpi ?? 300,
    model: p.model ?? "custom",
    snmp_enabled: p.snmp_enabled ?? true,
    snmp_port: p.snmp_port ?? 161,
    qr_media_id: p.qr_media_id ?? 'DK-2246',
    qr_label_length_mm: p.qr_label_length_mm ?? 60,
  });
  communityConfigured.value = p.snmp_community_configured ?? false;
  resetSettingsState();
  dialogOpen.value = true;
}

async function testPrint(p: Printer) {
  if (p.protocol === "brother_ql") {
    requestError.value = "";
    window.location.hash = "qr-labels";
    return;
  }
  await requests.run("testPrint", () => testPrintRequest(p));
}
async function testPrintRequest(p: Printer) {
  testingId.value = p.id;
  try {
    const res = await api.post<TestPrintResult>(
      `/api/printers/${p.id}/test-print`,
    );
    toast.add({
      severity: "success",
      summary: `Sent to ${p.name}`,
      detail: `Used template "${res.template_used}". Check the printer.`,
      life: 4000,
    });
  } catch (e: unknown) {
    requestError.value = e instanceof Error ? e.message : String(e);
    toast.add({
      severity: "error",
      summary: "Test print failed",
      detail: e instanceof Error ? e.message : String(e),
      life: 6000,
    });
  } finally {
    testingId.value = null;
  }
}

async function save() {
  await requests.run("save", () => saveRequest());
}
async function saveRequest() {
  try {
    if (!validSelection.value || !selectedModel.value) {
      requestError.value = 'Choose a brand and a compatible printer model, protocol and resolution.';
      return;
    }
    const payload = {...form, ...settingsForModel(selectedModel.value, form), ...communityUpdate(communityMode.value, communityValue.value)};
    if (editId.value) {
      await api.put<Printer>(`/api/printers/${editId.value}`, payload);
    } else {
      await api.post<Printer>("/api/printers", payload);
    }
    dialogOpen.value = false;
    await store.loadAll();
    await store.pingAll();
    toast.add({ severity: "success", summary: "Saved", life: 2000 });
  } catch (e: unknown) {
    requestError.value = e instanceof Error ? e.message : String(e);
    toast.add({
      severity: "error",
      summary: "Save failed",
      detail: e instanceof Error ? e.message : String(e),
    });
  }
}

async function remove(p: Printer) {
  confirm.require({
    message: `Delete printer "${p.name}"?`,
    accept: async () => requests.run("delete", async () => {
      try {
        await api.delete(`/api/printers/${p.id}`);
        await store.loadAll();
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
    <Button v-if="requestError" label="Retry loading" @click="refresh" />
    <p v-if="requestError" role="alert" class="text-red-700 my-3">{{ requestError }} — Please try again.</p>
    <p v-if="requests.busy('refresh')" role="status" class="text-slate-600 my-3">Loading…</p>

    <div class="flex items-center justify-between mb-3">
      <h2 class="text-lg font-bold">
        Printers
        <span class="text-slate-400">({{ store.printers.length }})</span>
      </h2>
      <div class="flex gap-2">
        <Button :disabled="requests.pending.value.size > 0"
          label="Check connections"
          icon="pi pi-bolt"
          severity="secondary"
          size="small"
          @click="requests.run('ping', () => store.pingAll())"
        />
        <Button :disabled="requests.pending.value.size > 0"
          label="Add printer"
          icon="pi pi-plus"
          size="small"
          @click="openCreate"
        />
      </div>
    </div>

    <div v-if="!requests.busy('refresh') || store.printers.length" class="space-y-6">
      <section v-for="group in printerGroups" :key="group.key" :aria-labelledby="`printers-${group.key}`"
        class="border-t border-slate-200 pt-4">
        <h3 :id="`printers-${group.key}`" class="mb-3 text-sm font-semibold text-slate-700">
          {{ group.title }} <span class="text-slate-400">({{ group.printers.length }})</span>
        </h3>
        <DataTable
          :value="group.printers"
          class="printer-group-table"
          :table-style="printerTableStyle"
          :table-props="{ 'aria-labelledby': `printers-${group.key}` }"
          data-key="id"
          striped-rows

          size="small"
        >
          <template #empty>{{ group.emptyMessage }}</template>
          <Column field="name" header="Name" :style="printerColumnStyles.name" :header-style="printerColumnStyles.name" />
          <Column header="Address" :style="printerColumnStyles.address" :header-style="printerColumnStyles.address">
            <template #body="{ data }">{{ data.ip }}:{{ data.port }}</template>
          </Column>
          <Column header="Protocol" :style="printerColumnStyles.protocol" :header-style="printerColumnStyles.protocol">
            <template #body="{ data }">
              <div class="flex flex-wrap items-center gap-1">
                <span
                  class="px-2 py-0.5 rounded text-xs font-mono"
                  :class="
                    data.protocol === 'jscript'
                      ? 'bg-violet-100 text-violet-700'
                      : 'bg-slate-100 text-slate-700'
                  "
                >
                  {{ data.protocol }}
                </span>
                <span
                  v-if="data.protocol !== 'epl2'"
                  class="px-2 py-0.5 rounded text-xs font-mono bg-slate-100 text-slate-600"
                >
                  {{ data.dpi ?? 300 }} dpi
                </span>
              </div>
            </template>
          </Column>
          <Column field="notes" header="Notes" />
          <Column header="Status" :style="printerColumnStyles.status" :header-style="printerColumnStyles.status">
            <template #body="{ data }">
              <PingPill :ping="store.pingByPrinter[data.id]" />
            </template>
          </Column>
          <Column header="" :style="printerColumnStyles.actions" :header-style="printerColumnStyles.actions">
            <template #body="{ data }">
              <div class="flex gap-1 justify-end">
                <Button :disabled="requests.pending.value.size > 0"
                  icon="pi pi-bolt"
                  size="small"
                  text
                  aria-label="Ping"
                  title="Ping (TCP connect)"
                  @click="requests.run('ping', () => store.pingOne(data.id))"
                />
                <Button :disabled="requests.pending.value.size > 0"
                  :icon="data.protocol === 'brother_ql' ? 'pi pi-qrcode' : 'pi pi-print'"
                  size="small"
                  text
                  :aria-label="data.protocol === 'brother_ql' ? 'Open QR labels' : 'Test print'"
                  :title="data.protocol === 'brother_ql' ? 'Preview and send a label in QR labels' : 'Send a real label to verify protocol'"
                  :loading="testingId === data.id"
                  @click="testPrint(data)"
                />
                <Button :disabled="requests.pending.value.size > 0"
                  icon="pi pi-pencil"
                  size="small"
                  text
                  aria-label="Edit"
                  @click="openEdit(data)"
                />
                <Button :disabled="requests.pending.value.size > 0"
                  icon="pi pi-trash"
                  size="small"
                  severity="danger"
                  text
                  aria-label="Delete"
                  @click="remove(data)"
                />
              </div>
            </template>
          </Column>
        </DataTable>
      </section>
    </div>

    <Dialog
      v-model:visible="dialogOpen"
      modal class="admin-touch"
      :header="editId ? 'Edit printer' : 'Add printer'"
      :style="{ width: 'min(46rem, 94vw)' }"
    >
      <div class="printer-settings-grid">
        <h3 class="settings-wide settings-heading">Connection</h3>
        <div>
          <label for="printerssection-brand" class="block text-xs font-bold text-slate-600 mb-1">Brand</label>
          <Select input-id="printerssection-brand" aria-label="Brand" v-model="selectedBrand" :options="brandOptions"
            option-label="label" option-value="value" placeholder="Select brand" class="w-full" @change="changeBrand" />
        </div>
        <div>
          <label for="printerssection-field-4" class="block text-xs font-bold text-slate-600 mb-1">Printer model</label>
          <Select input-id="printerssection-field-4" aria-label="Model" v-model="selectedModel" :options="modelOptions" option-label="label" option-value="value"
            :disabled="!selectedBrand || selectedBrand === 'custom'" :placeholder="selectedBrand ? 'Select printer model' : 'Select brand first'"
            class="w-full" @change="applyModel" />
          <p v-if="form.model === 'QL-1110NWBc'" class="mt-1 text-xs text-slate-500">
            Brother QL raster · 300 dpi. Configure label defaults below.
          </p>
          <p v-else-if="form.model !== 'custom'" class="mt-1 text-xs text-slate-500">
            Protocol and native resolution are set by model. Printable width: 105.7 mm per side.
          </p>
          <p v-if="form.model === 'DP4300HD'" class="mt-2 text-sm text-amber-700">
            Single-sided templates only. Configure the printer for single-sided operation
            (Disable lower head), following the Panduit instructions. This profile does not
            map a template to two separate printheads.
          </p>
        </div>

        <div>
          <label for="printerssection-field-1" class="block text-xs font-bold text-slate-600 mb-1">Name</label>
          <InputText id="printerssection-field-1" aria-label="Name" v-model="form.name" class="w-full" />
        </div>
        <div>
          <label for="printerssection-field-2" class="block text-xs font-bold text-slate-600 mb-1">IP</label>
          <InputText id="printerssection-field-2" aria-label="IP address" v-model="form.ip" class="w-full" />
        </div>
        <div>
          <label for="printerssection-field-3" class="block text-xs font-bold text-slate-600 mb-1">Port</label>
          <InputNumber input-id="printerssection-field-3" aria-label="Port" v-model="form.port" :use-grouping="false" class="w-full" />
        </div>
        <div v-if="selectedBrand && selectedModel">
          <label for="printerssection-field-5" class="block text-xs font-bold text-slate-600 mb-1">
            Protocol
          </label>
          <Select input-id="printerssection-field-5"
            aria-label="Protocol"
            :model-value="effectiveSettings.protocol" @update:model-value="form.protocol = $event"
            :disabled="form.model !== 'custom'"
            :options="protocolOptions"
            option-label="label"
            option-value="value"
            class="w-full"
          />
          <p v-if="selectedBrand === 'brother'" class="mt-1 text-xs text-slate-500">
            Raw TCP printing, normally port 9100.
          </p>
          <p v-else-if="selectedBrand === 'panduit'" class="mt-1 text-xs text-slate-500">
            Protocol and native resolution are fixed by the selected Panduit model.
          </p>
          <p v-else class="mt-1 text-xs text-slate-500">
            Select the protocol supported by your printer.
          </p>
          <p v-if="selectedBrand === 'custom' && form.protocol === 'brother_ql'" role="alert" class="mt-2 text-sm text-red-700">
            Select a manual protocol, or choose Brother → QL-1110NWBc.
          </p>
        </div>
        <p v-if="form.model === 'TDP43ME'" class="text-sm text-slate-600">
          Network printing · 300 dpi. Enter this printer’s IP and RAW TCP port (normally 9100).
          Verify alignment with a test label before production printing.
        </p>
        <div v-if="selectedBrand && selectedModel && (effectiveSettings.protocol !== 'epl2' || invalidManualDpi)">
          <label for="printerssection-field-6" class="block text-xs font-bold text-slate-600 mb-1">
            Printhead resolution
          </label>
          <Select input-id="printerssection-field-6"
            aria-label="Printhead resolution"
            :model-value="effectiveSettings.dpi" @update:model-value="form.dpi = $event"
            :disabled="form.model !== 'custom'"
            :options="dpiOptions"
            option-label="label"
            option-value="value"
            class="w-full"
          />
          <p v-if="selectedBrand === 'brother'" class="mt-1 text-xs text-slate-500">
            QL-1110NWBc uses 300 dpi. QR labels are rendered at this resolution for the selected DK roll.
          </p>
          <p v-else-if="selectedBrand === 'panduit'" class="mt-1 text-xs text-slate-500">
            Must match the physical head. DP4600H is 600 dpi — the label is
            rendered at 2× so it prints the same size as a 300-dpi DP4300H.
            Wrong value prints everything half/double size.
          </p>
          <p v-else class="mt-1 text-xs text-slate-500">Must match the physical printhead resolution.</p>
          <p v-if="invalidManualDpi" role="alert" class="mt-2 text-sm text-red-700">
            Choose a supported printhead resolution: 203, 300 or 600 dpi.
          </p>
        </div>
        <div>
          <label for="printerssection-field-7" class="block text-xs font-bold text-slate-600 mb-1">Notes</label>
          <InputText id="printerssection-field-7" aria-label="Notes" v-model="form.notes" class="w-full" />
        </div>
        <template v-if="selectedBrand === 'brother' || form.model === 'DP4300H'">
          <h3 class="settings-wide settings-heading">Device status</h3>
          <label class="settings-wide settings-check"><input v-model="form.snmp_enabled" type="checkbox" /> Check printer status using SNMP</label>
          <div><label class="settings-label" for="snmp-port">SNMP UDP port</label><InputNumber input-id="snmp-port" v-model="form.snmp_port" :min="1" :max="65535" :use-grouping="false" :disabled="!form.snmp_enabled" class="w-full" /></div>
          <div class="settings-note">SNMP {{ form.model === 'DP4300H' ? 'v2c' : 'v1' }} · read-only requests<br />Enable SNMP on the printer separately.</div>
          <div><label class="settings-label" for="community-mode">Community</label><select id="community-mode" v-model="communityMode" class="settings-select"><option value="keep">Keep {{ communityConfigured ? 'saved community' : 'server default' }}</option><option value="replace">Replace community</option><option value="reset">Use server default</option></select></div>
          <div v-if="communityMode === 'replace'"><label class="settings-label" for="printer-snmp-replacement">New community</label><InputText id="printer-snmp-replacement" name="printer-snmp-community-replacement" v-model="communityValue" type="password" autocomplete="new-password" class="w-full" /></div>
          <div class="settings-wide settings-status">
            <Button label="Check saved configuration" severity="secondary" size="small" :loading="checkingStatus" :disabled="!editId || settingsDirty || requests.pending.value.size > 0" @click="checkSavedStatus" />
            <span v-if="!editId || settingsDirty" class="settings-note">Save changes before checking.</span>
            <template v-else-if="checkedStatus">
              <strong role="status">{{ statusLabel }}</strong>
              <span v-if="checkedStatus.device_status?.media_width_mm" class="settings-note">Detected: {{ checkedStatus.device_status.media_width_mm }} mm {{ checkedStatus.device_status.media_type }}</span>
              <span v-if="checkedStatus.device_status?.checked_at" class="settings-note">Checked {{ new Date(checkedStatus.device_status.checked_at).toLocaleTimeString() }}</span>
              <span v-if="selectedBrand === 'brother' && mediaMismatch" role="status" class="settings-warning">Loaded media differs from the configured default.</span>
            </template>
          </div>
        </template>
        <template v-if="selectedBrand === 'brother'">
          <h3 class="settings-wide settings-heading">QR label defaults</h3>
          <div><label class="settings-label" for="qr-default-roll">Default roll</label><select id="qr-default-roll" v-model="form.qr_media_id" class="settings-select"><option value="DK-2205">DK-2205 · 62 mm continuous</option><option value="DK-2246">DK-2246 · 103 mm continuous</option></select></div>
          <div><label class="settings-label" for="qr-default-length">Default length, mm</label><InputNumber input-id="qr-default-length" v-model="form.qr_label_length_mm" :min="30" :max="200" :use-grouping="false" class="w-full" /></div>
          <p class="settings-wide settings-note">Defaults for new labels; existing print settings stay unchanged. Configured media does not confirm the roll physically loaded.</p>
        </template>
      </div>
      <p v-if="requestError" role="alert" class="text-red-700 mt-3">{{ requestError }} — Please try again.</p>
      <template #footer>
        <Button :disabled="requests.pending.value.size > 0"
          label="Cancel"
          severity="secondary"
          @click="dialogOpen = false"
        />
        <Button :loading="requests.busy('save')" :disabled="!validSelection || !form.name.trim() || !form.ip.trim() || requests.pending.value.size > 0" :label="editId ? 'Save' : 'Create'" @click="save" />
      </template>
    </Dialog>
  </section>
</template>

<style scoped>
.printer-settings-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px 16px; }
.printer-settings-grid > * { min-width:0; }
.settings-wide { grid-column:1/-1; }
.settings-heading { font-size:14px; font-weight:700; margin:8px 0 0; padding-top:14px; border-top:1px solid #e2e8f0; }
.settings-heading:first-child { padding-top:0; border:0; margin-top:0; }
.settings-label { display:block; font-size:12px; font-weight:700; color:#475569; margin-bottom:4px; }
.settings-select { width:100%; min-height:40px; border:1px solid #cbd5e1; border-radius:6px; padding:8px; background:white; }
.settings-note { font-size:12px; color:#64748b; line-height:1.5; }
.settings-check { display:flex; gap:8px; align-items:center; font-size:14px; }
.settings-status { display:flex; flex-wrap:wrap; gap:8px 12px; align-items:center; padding:12px; background:#f8fafc; border-radius:6px; font-size:13px; }
.settings-warning { color:#92400e; width:100%; }
@media(max-width:560px) { .printer-settings-grid { grid-template-columns:1fr; } .printer-settings-grid > * { grid-column:1; } }

.printer-group-table :deep(.p-datatable-table-container) { overflow-x: auto; }
.printer-group-table :deep(.p-datatable-tbody > tr > td) {
  overflow-wrap: anywhere;
  vertical-align: middle;
}

@media (pointer: coarse) { .admin-touch :deep(.p-button), .admin-touch :deep(.p-select), .admin-touch :deep(.p-inputtext) { min-height:44px; } .admin-touch :deep(.p-button-icon-only) { min-width:44px; } }
</style>
