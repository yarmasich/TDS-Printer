<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { api } from "@/api/client";
import type { Printer, PrinterProtocol, TestPrintResult } from "@/api/types";
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
const toast = useToast();
const confirm = useConfirm();

const protocolOptions: { label: string; value: PrinterProtocol }[] = [
  { label: "EPL2 — TSC TDP-43ME", value: "epl2" },
  { label: "JScript — cab DP4300H", value: "jscript" },
];

const dpiOptions: { label: string; value: number }[] = [
  { label: "300 dpi — DP4300H", value: 300 },
  { label: "600 dpi — DP4600H", value: 600 },
];

const dialogOpen = ref(false);
const editId = ref<number | null>(null);
const testingId = ref<number | null>(null);
const form = reactive<Omit<Printer, "id">>({
  name: "",
  ip: "",
  port: 9100,
  notes: "",
  protocol: "epl2",
  dpi: 300,
});

onMounted(async () => {
  await store.loadAll();
  await store.pingAll();
});

function openCreate() {
  editId.value = null;
  form.name = "";
  form.ip = "";
  form.port = 9100;
  form.notes = "";
  form.protocol = "epl2";
  form.dpi = 300;
  dialogOpen.value = true;
}

async function openEdit(p: Printer) {
  editId.value = p.id;
  Object.assign(form, {
    name: p.name,
    ip: p.ip,
    port: p.port,
    notes: p.notes,
    protocol: p.protocol,
    dpi: p.dpi ?? 300,
  });
  dialogOpen.value = true;
}

async function testPrint(p: Printer) {
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
  try {
    if (editId.value) {
      await api.put<Printer>(`/api/printers/${editId.value}`, form);
    } else {
      await api.post<Printer>("/api/printers", form);
    }
    dialogOpen.value = false;
    await store.loadAll();
    await store.pingAll();
    toast.add({ severity: "success", summary: "Saved", life: 2000 });
  } catch (e: unknown) {
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
    accept: async () => {
      try {
        await api.delete(`/api/printers/${p.id}`);
        await store.loadAll();
      } catch (e: unknown) {
        toast.add({
          severity: "error",
          summary: "Delete failed",
          detail: e instanceof Error ? e.message : String(e),
        });
      }
    },
  });
}
</script>

<template>
  <section class="bg-white border border-slate-200 rounded-2xl p-5 shadow-sm">
    <div class="flex items-center justify-between mb-3">
      <h2 class="text-lg font-bold">
        Printers
        <span class="text-slate-400">({{ store.printers.length }})</span>
      </h2>
      <div class="flex gap-2">
        <Button
          label="Test all"
          icon="pi pi-bolt"
          severity="secondary"
          size="small"
          @click="store.pingAll()"
        />
        <Button
          label="Add printer"
          icon="pi pi-plus"
          size="small"
          @click="openCreate"
        />
      </div>
    </div>

    <DataTable
      :value="store.printers"
      data-key="id"
      striped-rows
      empty-message="No printers yet"
      size="small"
    >
      <Column field="name" header="Name" />
      <Column header="Address">
        <template #body="{ data }">{{ data.ip }}:{{ data.port }}</template>
      </Column>
      <Column header="Protocol">
        <template #body="{ data }">
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
            v-if="data.protocol === 'jscript'"
            class="ml-1 px-2 py-0.5 rounded text-xs font-mono bg-slate-100 text-slate-600"
          >
            {{ data.dpi ?? 300 }} dpi
          </span>
        </template>
      </Column>
      <Column field="notes" header="Notes" />
      <Column header="Status">
        <template #body="{ data }">
          <PingPill :ping="store.pingByPrinter[data.id]" />
        </template>
      </Column>
      <Column header="" :style="{ width: '260px' }">
        <template #body="{ data }">
          <div class="flex gap-1 justify-end">
            <Button
              icon="pi pi-bolt"
              size="small"
              text
              aria-label="Ping"
              title="Ping (TCP connect)"
              @click="store.pingOne(data.id)"
            />
            <Button
              icon="pi pi-print"
              size="small"
              text
              aria-label="Test print"
              title="Send a real label to verify protocol"
              :loading="testingId === data.id"
              @click="testPrint(data)"
            />
            <Button
              icon="pi pi-pencil"
              size="small"
              text
              aria-label="Edit"
              @click="openEdit(data)"
            />
            <Button
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

    <Dialog
      v-model:visible="dialogOpen"
      modal
      :header="editId ? 'Edit printer' : 'Add printer'"
      :style="{ width: '32rem' }"
    >
      <div class="space-y-3">
        <div>
          <label class="block text-xs font-bold text-slate-600 mb-1">Name</label>
          <InputText v-model="form.name" class="w-full" />
        </div>
        <div>
          <label class="block text-xs font-bold text-slate-600 mb-1">IP</label>
          <InputText v-model="form.ip" class="w-full" />
        </div>
        <div>
          <label class="block text-xs font-bold text-slate-600 mb-1">Port</label>
          <InputNumber v-model="form.port" :use-grouping="false" class="w-full" />
        </div>
        <div>
          <label class="block text-xs font-bold text-slate-600 mb-1">
            Protocol
          </label>
          <Select
            v-model="form.protocol"
            :options="protocolOptions"
            option-label="label"
            option-value="value"
            class="w-full"
          />
          <p class="mt-1 text-xs text-slate-500">
            Pick by printer model. EPL2 = TSC TDP-43ME-class; JScript = cab
            (DP4300H, DP4600H — "Made in Germany", MAC starts 00:02:e7).
          </p>
        </div>
        <div v-if="form.protocol === 'jscript'">
          <label class="block text-xs font-bold text-slate-600 mb-1">
            Printhead resolution
          </label>
          <Select
            v-model="form.dpi"
            :options="dpiOptions"
            option-label="label"
            option-value="value"
            class="w-full"
          />
          <p class="mt-1 text-xs text-slate-500">
            Must match the physical head. DP4600H is 600 dpi — the label is
            rendered at 2× so it prints the same size as a 300-dpi DP4300H.
            Wrong value prints everything half/double size.
          </p>
        </div>
        <div>
          <label class="block text-xs font-bold text-slate-600 mb-1">Notes</label>
          <InputText v-model="form.notes" class="w-full" />
        </div>
      </div>
      <template #footer>
        <Button
          label="Cancel"
          severity="secondary"
          @click="dialogOpen = false"
        />
        <Button :label="editId ? 'Save' : 'Create'" @click="save" />
      </template>
    </Dialog>
  </section>
</template>
