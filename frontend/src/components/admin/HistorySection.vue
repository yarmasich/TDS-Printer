<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from 'vue';
import { api } from '@/api/client';
import type { PrintLog } from '@/api/types';
import DataTable from 'primevue/datatable';
import Column from 'primevue/column';
import Tag from 'primevue/tag';
import Button from 'primevue/button';

type Counts = { attempts: number; sent: number; errors: number; uncertain: number };
type OperatorSummary = Counts & {operator: string; operator_source: string; operator_verified: boolean; operator_employee_id: string | null; last_at: string};
const logs = ref<PrintLog[]>([]);
const summary = ref<{totals:Counts} | null>(null);
const people = ref<OperatorSummary[]>([]);
const projects = ref<{id:number;name:string}[]>([]);
const error = ref('');
const loading = ref(false);
const projectId = ref('');
const stationId = ref('');
const stations = ref<{id:number;display_name:string;username:string}[]>([]);
const operator = ref('');
function localInput(date: Date) { return new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0,16); }
const since = ref(localInput(new Date(Date.now()-7*86400000)));
const until = ref('');
let generation=0;
function when(value:string) {
  // SQLite timestamps are UTC even when the serialized value lacks an offset.
  const utc = /(?:Z|[+-]\d\d:\d\d)$/i.test(value) ? value : `${value}Z`;
  return new Date(utc).toLocaleString();
}
async function load() {
  const seq=++generation; loading.value=true; error.value='';
  try {
    const params=new URLSearchParams();
    if(since.value) params.set('since',new Date(since.value).toISOString());
    if(until.value) params.set('until',new Date(until.value).toISOString());
    if(projectId.value) params.set('project_id',projectId.value);
    if(stationId.value) params.set('station_id',stationId.value);
    if(operator.value.trim()) params.set('operator',operator.value.trim());
    const [entries, totals]=await Promise.all([
      api.get<PrintLog[]>(`/api/history?limit=200&${params}`),
      api.get<{totals:Counts;operators:OperatorSummary[]}>(`/api/history/summary?${params}`),
    ]);
    if(seq!==generation)return;
    logs.value=entries; summary.value={totals:totals.totals}; people.value=totals.operators;
  } catch(e) { if(seq===generation){ error.value=e instanceof Error ? e.message:String(e); summary.value=null; logs.value=[]; people.value=[]; } }
  finally { if(seq===generation)loading.value=false; }
}
onMounted(async()=>{
  void load();
  try{
    [projects.value,stations.value]=await Promise.all([
      api.get<{id:number;name:string}[]>('/api/projects'),
      api.get<{id:number;display_name:string;username:string}[]>('/api/stations'),
    ]);
  }catch(e){error.value=`Could not load filters: ${String(e)}`;}
});
onBeforeUnmount(()=>{generation++;});
</script>

<template>
  <section class="history-section bg-white border border-slate-200 rounded-2xl p-5 shadow-sm">
    <h2 class="text-2xl font-bold">Print history</h2>
    <p class="history-note">Times are shown in your local time zone. Counts are print attempts / rows (normally a pair of labels), not confirmed physical output.</p>
    <form class="history-filters" @submit.prevent="load">
      <label>From<input type="datetime-local" v-model="since" /></label>
      <label>Until (exclusive)<input type="datetime-local" v-model="until" /></label>
      <label>Project<select v-model="projectId"><option value="">All projects</option><option v-for="p in projects" :key="p.id" :value="p.id">{{p.name}}</option></select></label>
      <label>Station<select v-model="stationId"><option value="">All stations</option><option v-for="s in stations" :key="s.id" :value="s.id">{{s.display_name || s.username}}</option></select></label>
      <label>Operator (exact name)<input v-model="operator" placeholder="All operators" /></label>
      <Button type="submit" label="Apply / refresh" :loading="loading" :disabled="loading" />
    </form>
    <p v-if="error" role="alert" class="text-red-700 my-3">{{error}}</p>
    <div v-if="summary" class="history-counts">
      <div><span>Sent to printer</span><strong>{{summary.totals.sent}}</strong></div>
      <div><span>Errors</span><strong>{{summary.totals.errors}}</strong></div>
      <div><span>Outcome unknown</span><strong>{{summary.totals.uncertain}}</strong></div>
      <div><span>Total attempts</span><strong>{{summary.totals.attempts}}</strong></div>
    </div>
    <h3 class="font-semibold mt-5 mb-2">By operator · full selected period</h3>
    <DataTable class="operator-history-table" :value="people" striped-rows :paginator="people.length>10" :rows="10">
      <Column header="Operator"><template #body="{data}">{{data.operator || 'Not recorded'}}<small v-if="data.operator_employee_id" class="block text-slate-500">{{data.operator_employee_id}}</small></template></Column>
      <Column header="Identity"><template #body="{data}"><Tag :value="data.operator_verified ? 'RFID verified' : data.operator_source==='api' ? 'API key' : 'Manual / legacy'" :severity="data.operator_verified ? 'success':'secondary'" /></template></Column>
      <Column field="sent" header="Sent" sortable /><Column field="errors" header="Errors" /><Column field="uncertain" header="Unknown" />
      <Column header="Last attempt"><template #body="{data}">{{when(data.last_at)}}</template></Column>
      <template #empty>No attempts in this period.</template>
    </DataTable>
    <h3 class="font-semibold mt-5 mb-2">Latest entries (up to 200)</h3>
    <DataTable class="print-history-table" :value="logs" data-key="id" striped-rows :paginator="logs.length>20" :rows="20" sort-mode="single" sort-field="ts" :sort-order="-1">
      <Column field="ts" header="When" sortable><template #body="{data}">{{when(data.ts)}}</template></Column>
      <Column field="project_name" header="Project"><template #body="{data}">{{data.project_name || 'Not recorded'}}</template></Column>
      <Column field="operator" header="Operator"><template #body="{data}">{{data.operator}}<small v-if="data.operator_employee_id" class="block text-slate-500">{{data.operator_employee_id}}</small></template></Column>
      <Column header="Identity"><template #body="{data}"><Tag :value="data.operator_verified ? 'RFID verified' : data.operator_source==='api' ? 'API key' : 'Manual / legacy'" :severity="data.operator_verified ? 'success':'secondary'" /></template></Column>
      <Column field="station_name" header="Station"><template #body="{data}">{{data.station_name || '—'}}</template></Column>
      <Column field="template_name" header="Template" /><Column field="printer_name" header="Printer"><template #body="{data}">{{data.printer_name || '—'}}<small class="block text-slate-500">{{data.printer_ip}}</small></template></Column><Column field="reason" header="Reason" />
      <Column header="Result"><template #body="{data}"><Tag :value="data.status==='ok' ? 'Sent' : data.status==='uncertain' ? 'Unknown' : data.status" :severity="data.status==='ok' ? 'success' : data.status==='uncertain' ? 'warn' : 'danger'" /><span v-if="data.error" class="text-xs text-slate-500 ml-2">{{data.error}}</span></template></Column>
      <template #empty>No attempts in this period.</template>
    </DataTable>
  </section>
</template>
<style scoped>
.history-section :deep(.p-datatable-table-container) { overflow-x: auto; }
.operator-history-table :deep(table) { min-width: 720px; }
.print-history-table :deep(table) { min-width: 1280px; }
.history-section :deep(.p-datatable-tbody > tr > td),
.history-section :deep(.p-datatable-thead > tr > th) { padding: 14px 12px; font-size: 16px; }
.history-note { color:#64748b; font-size:14px; margin:8px 0 16px; }
.history-filters { display:flex; flex-wrap:wrap; align-items:end; gap:12px; }
.history-filters label { display:flex; flex-direction:column; gap:5px; font-size:14px; color:#475569; min-width:160px; flex:1; }
.history-filters input,.history-filters select { min-height:44px; border:1px solid #cbd5e1; border-radius:6px; padding:8px; font-size:16px; min-width:0; background:white; }
.history-counts { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin-top:20px; }
.history-counts div { padding:14px; border:1px solid #e2e8f0; border-radius:8px; }
.history-counts span { display:block; font-size:12px; color:#64748b; }
.history-counts strong { font-size:24px; font-variant-numeric:tabular-nums; }
@media(max-width:700px) { .history-counts { grid-template-columns:repeat(2,minmax(0,1fr)); } }
</style>
