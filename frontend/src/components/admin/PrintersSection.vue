<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { api } from "@/api/client";
import type { Printer } from "@/api/types";
import { usePrinters } from "@/stores/printers";
import { useToast } from "primevue/usetoast";
import { useConfirm } from "primevue/useconfirm";

import DataTable from "primevue/datatable";
import Column from "primevue/column";
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import InputText from "primevue/inputtext";
import InputNumber from "primevue/inputnumber";
import PingPill from "@/components/PingPill.vue";

const store = usePrinters();
const toast = useToast();
const confirm = useConfirm();

const dialogOpen = ref(false);
const editId = ref<number | null>(null);
const form = reactive<Omit<Printer, "id">>({
  name: "",
  ip: "",
  port: 9100,
  notes: "",
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
  dialogOpen.value = true;
}

async function openEdit(p: Printer) {
  editId.value = p.id;
  Object.assign(form, { name: p.name, ip: p.ip, port: p.port, notes: p.notes });
  dialogOpen.value = true;
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
      <Column field="notes" header="Notes" />
      <Column header="Status">
        <template #body="{ data }">
          <PingPill :ping="store.pingByPrinter[data.id]" />
        </template>
      </Column>
      <Column header="" :style="{ width: '220px' }">
        <template #body="{ data }">
          <div class="flex gap-1 justify-end">
            <Button
              icon="pi pi-bolt"
              size="small"
              text
              aria-label="Test"
              @click="store.pingOne(data.id)"
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
