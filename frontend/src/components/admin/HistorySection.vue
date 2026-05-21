<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api } from "@/api/client";
import type { PrintLog } from "@/api/types";

import DataTable from "primevue/datatable";
import Column from "primevue/column";
import Tag from "primevue/tag";

const logs = ref<PrintLog[]>([]);

onMounted(async () => {
  logs.value = await api.get<PrintLog[]>("/api/history?limit=200");
});
</script>

<template>
  <section class="bg-white border border-slate-200 rounded-2xl p-5 shadow-sm">
    <h2 class="text-lg font-bold mb-3">
      Recent prints <span class="text-slate-400">({{ logs.length }})</span>
    </h2>
    <DataTable
      :value="logs"
      data-key="id"
      striped-rows
      empty-message="No prints yet"
      :paginator="logs.length > 20"
      :rows="20"
      size="small"
      sort-mode="single"
      sort-field="ts"
      :sort-order="-1"
    >
      <Column field="ts" header="When" sortable />
      <Column field="template_name" header="Template" sortable />
      <Column field="printer_ip" header="Printer" />
      <Column field="operator" header="Operator" />
      <Column field="reason" header="Reason" />
      <Column header="Status">
        <template #body="{ data }">
          <Tag
            :value="data.status"
            :severity="data.status === 'ok' ? 'success' : 'danger'"
          />
          <span v-if="data.error" class="text-xs text-slate-500 ml-2">
            {{ data.error }}
          </span>
        </template>
      </Column>
    </DataTable>
  </section>
</template>
