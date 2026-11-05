<script setup lang="ts">
import { nextTick, onMounted, reactive, ref } from "vue";
import { api } from "@/api/client";
import type { Station } from "@/stores/stationAuth";
import { usePrinters } from "@/stores/printers";
import Button from "primevue/button";
import InputText from "primevue/inputtext";
import Select from "primevue/select";
const printers = usePrinters();
const stations = ref<Station[]>([]);
const editing = ref<number | null>(null);
const busy = ref(false);
const error = ref("");
const loading = ref(false);
const loadError = ref("");
const formHeading = ref<HTMLElement | null>(null);
let editTrigger: HTMLElement | null = null;
const saved = ref("");
const form = reactive({ username: "", display_name: "", password: "", printer_id: null as number | null, enabled: true });
function reset() {
  editing.value = null;
  Object.assign(form, { username: "", display_name: "", password: "", printer_id: null, enabled: true });
}
async function edit(station: Station, event: Event) {
  editTrigger = event.currentTarget as HTMLElement;
  editing.value = station.id;
  Object.assign(form, { username: station.username, display_name: station.display_name, password: "", printer_id: station.printer_id, enabled: station.enabled });
  saved.value = "";
  await nextTick();
  formHeading.value?.focus({ preventScroll: true });
  formHeading.value?.scrollIntoView({ block: "start" });
}
async function cancelEdit() {
  reset();
  await nextTick();
  editTrigger?.focus();
  editTrigger = null;
}
async function load() {
  if (loading.value) return;
  loading.value = true;
  loadError.value = "";
  try { await Promise.all([printers.loadAll(), api.get<Station[]>("/api/stations").then(rows => stations.value = rows)]); }
  catch (e) { loadError.value = e instanceof Error ? e.message : String(e); }
  finally { loading.value = false; }
}
async function save() {
  if (busy.value) return;
  busy.value = true; error.value = ""; saved.value = "";
  try {
    const body = { username: form.username.trim(), display_name: form.display_name.trim(), printer_id: form.printer_id, enabled: form.enabled, ...(form.password ? { password: form.password } : {}) };
    if (editing.value === null) await api.post("/api/stations", body);
    else await api.patch(`/api/stations/${editing.value}`, body);
    reset(); await load();
    if (!loadError.value) saved.value = "Station saved. Sign in on the workstation with its username and password.";
  } catch (e) { error.value = e instanceof Error ? e.message : String(e); }
  finally { busy.value = false; }
}
onMounted(load);
</script>

<template>
  <section class="bg-white border border-slate-200 rounded-2xl p-5 space-y-5">
    <div>
      <h2 class="text-xl font-bold">Station accounts</h2>
      <p class="text-slate-600 mt-1">Give each workstation its own login and printer. Disciplines and templates are shared; carts stay separate. Employee RFID still identifies who prints.</p>
      <p class="text-sm text-amber-800 mt-2">Creating the first station requires station sign-in for Print and Kiosk on every workstation.</p>
    </div>
    <p v-if="loading" role="status" class="text-slate-600">Loading stations and printers…</p>
    <div v-if="loadError" class="space-y-2">
      <p role="alert" class="text-red-700">Could not load station settings: {{ loadError }}</p>
      <Button label="Retry loading" severity="secondary" :disabled="loading || busy" @click="load" />
    </div>
    <p v-if="!loading && !loadError && !stations.length" class="text-slate-600">No station accounts yet. Create the first station below.</p>
    <p v-if="!loading && !loadError && !printers.printers.length" class="text-amber-800">Add a printer in Printers before creating a station.</p>
    <p v-if="error" role="alert" class="text-red-700">{{ error }}</p>
    <p v-if="saved" role="status" class="text-emerald-700">{{ saved }}</p>
    <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      <article v-for="station in stations" :key="station.id" class="border border-slate-200 rounded-xl p-4">
        <h3 class="font-semibold">{{ station.display_name }}</h3>
        <p class="text-sm text-slate-600">{{ station.username }} · {{ station.enabled ? 'Enabled' : 'Disabled' }}</p>
        <p class="my-2">Printer: <b>{{ station.printer_name }}</b></p>
        <Button label="Edit station" icon="pi pi-pencil" severity="secondary" :disabled="busy" @click="edit(station, $event)" />
      </article>
    </div>
    <form class="border-t border-slate-200 pt-5 space-y-4" @submit.prevent="save">
      <h3 ref="formHeading" tabindex="-1" class="font-semibold scroll-mt-4">{{ editing === null ? 'Create station' : 'Edit station' }}</h3>
      <div class="grid gap-4 sm:grid-cols-2">
        <label class="flex flex-col gap-1">Username<InputText v-model="form.username" autocomplete="off" maxlength="100" required :disabled="editing !== null || busy" /></label>
        <label class="flex flex-col gap-1">Station name<InputText v-model="form.display_name" required :disabled="busy" maxlength="200" placeholder="Packing desk 1" /></label>
        <label class="flex flex-col gap-1">{{ editing === null ? 'Password' : 'New password (leave blank to keep)' }}<InputText v-model="form.password" type="password" autocomplete="new-password" minlength="8" maxlength="256" :required="editing === null" :disabled="busy" /></label>
        <label id="station-printer-label" for="station-printer" class="flex flex-col gap-1">Assigned printer<Select input-id="station-printer" aria-labelledby="station-printer-label" v-model="form.printer_id" :options="printers.printers" option-label="name" option-value="id" placeholder="Select printer" :disabled="busy" /></label>
      </div>
      <label class="flex items-center gap-2 min-h-11"><input v-model="form.enabled" type="checkbox" :disabled="busy" /> Enabled</label>
      <p v-if="editing !== null" class="text-sm text-slate-600">Changing the password or disabling a station signs it out. Reassigning its printer affects subsequent prints.</p>
      <div class="flex gap-2 flex-wrap">
        <Button type="submit" :label="editing === null ? 'Create station' : 'Save changes'" :loading="busy" :disabled="!form.username.trim() || !form.display_name.trim() || !form.printer_id || (editing === null && !form.password)" />
        <Button v-if="editing !== null" label="Cancel" severity="secondary" :disabled="busy" @click="cancelEdit" />
      </div>
    </form>
  </section>
</template>
