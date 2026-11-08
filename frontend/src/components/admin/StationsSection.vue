<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from "vue";
import { api } from "@/api/client";
import type { Station } from "@/stores/stationAuth";
import { usePrinters } from "@/stores/printers";
import Button from "primevue/button";
import InputText from "primevue/inputtext";
import MultiSelect from "primevue/multiselect";
const printers = usePrinters();
const stations = ref<Station[]>([]);
const cablePrinters = computed(() => printers.printers.filter(printer => printer.protocol !== "brother_ql"));
const editing = ref<number | null>(null);
const busy = ref(false);
const error = ref("");
const loading = ref(false);
const loadError = ref("");
const formHeading = ref<HTMLElement | null>(null);
let editTrigger: HTMLElement | null = null;
const saved = ref("");
const form = reactive({ username: "", display_name: "", password: "", printer_ids: [] as number[], default_printer_id: null as number | null, enabled: true });
const localPrinters = computed(() => cablePrinters.value.filter(printer => form.printer_ids.includes(printer.id)));
function reset() {
  editing.value = null;
  Object.assign(form, { username: "", display_name: "", password: "", printer_ids: [], default_printer_id: null, enabled: true });
}
async function edit(station: Station, event: Event) {
  editTrigger = event.currentTarget as HTMLElement;
  editing.value = station.id;
  Object.assign(form, { username: station.username, display_name: station.display_name, password: "", printer_ids: station.allowed_printers.map(printer => printer.id), default_printer_id: station.default_printer_id, enabled: station.enabled });
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
  try {
    const [, stationRows] = await Promise.all([printers.loadAll(), api.get<Station[]>("/api/stations")]);
    stations.value = stationRows;
  }
  catch (e) { loadError.value = e instanceof Error ? e.message : String(e); }
  finally { loading.value = false; }
}
async function save() {
  if (busy.value || !form.printer_ids.length) return;
  busy.value = true; error.value = ""; saved.value = "";
  try {
    const body = {
      username: form.username.trim(), display_name: form.display_name.trim(), printer_ids: form.printer_ids,
      default_printer_id: form.printer_ids.includes(form.default_printer_id ?? 0) ? form.default_printer_id : null,
      enabled: form.enabled, ...(form.password ? { password: form.password } : {}),
    };
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
  <section class="bg-surface border border-edge rounded-2xl p-5 space-y-5">
    <div>
      <h2 class="text-xl font-bold">Station accounts</h2>
      <p class="text-ink-2 mt-1">Give each workstation its own login and choose the cable printers it can use. Disciplines and templates are shared; carts stay separate. Employee RFID still identifies who prints.</p>
      <p class="text-sm text-warn mt-2">Creating the first station requires station sign-in for Print and Kiosk on every workstation.</p>
    </div>
    <p v-if="loading" role="status" class="text-ink-2">Loading stations and printers…</p>
    <div v-if="loadError" class="space-y-2">
      <p role="alert" class="text-danger">Could not load station settings: {{ loadError }}</p>
      <Button label="Retry loading" severity="secondary" :disabled="loading || busy" @click="load" />
    </div>
    <p v-if="!loading && !loadError && !stations.length" class="text-ink-2">No station accounts yet. Create the first station below.</p>
    <p v-if="!loading && !loadError && !cablePrinters.length" class="text-warn">Add a printer in Printers before creating a station.</p>
    <p v-if="error" role="alert" class="text-danger">{{ error }}</p>
    <p v-if="saved" role="status" class="text-ok">{{ saved }}</p>
    <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      <article v-for="station in stations" :key="station.id" class="border border-edge rounded-xl p-4">
        <h3 class="font-semibold">{{ station.display_name }}</h3>
        <p class="text-sm text-ink-2">{{ station.username }} · {{ station.enabled ? 'Enabled' : 'Disabled' }}</p>
        <p class="my-2">Allowed printers: <b>{{ station.allowed_printers.map(printer => printer.name).join(", ") || "None" }}</b></p>
        <Button label="Edit station" icon="pi pi-pencil" severity="secondary" :disabled="busy" @click="edit(station, $event)" />
      </article>
    </div>
    <form class="border-t border-edge pt-5 space-y-4" @submit.prevent="save">
      <h3 ref="formHeading" tabindex="-1" class="font-semibold scroll-mt-4">{{ editing === null ? 'Create station' : 'Edit station' }}</h3>
      <div class="grid gap-4 sm:grid-cols-2">
        <label class="flex flex-col gap-1">Username<InputText v-model="form.username" autocomplete="off" maxlength="100" required :disabled="editing !== null || busy" /></label>
        <label class="flex flex-col gap-1">Station name<InputText v-model="form.display_name" required :disabled="busy" maxlength="200" placeholder="Packing desk 1" /></label>
        <label class="flex flex-col gap-1">{{ editing === null ? 'Password' : 'New password (leave blank to keep)' }}<InputText v-model="form.password" type="password" autocomplete="new-password" minlength="8" maxlength="256" :required="editing === null" :disabled="busy" /></label>
        <div class="flex flex-col gap-1">
          <label id="station-printer-label" for="station-printer">Allowed printers</label>
          <MultiSelect input-id="station-printer" aria-labelledby="station-printer-label" v-model="form.printer_ids" @update:model-value="ids => { if (!ids.includes(form.default_printer_id)) form.default_printer_id = null; }" :options="cablePrinters" option-label="name" option-value="id" placeholder="Select printers" display="chip" filter :disabled="busy" />
          <p class="text-sm text-ink-2">Print and Kiosk use these printers. The template sets the label size.</p>
        </div>
      </div>
      <div class="flex flex-col gap-1">
        <label for="station-default-printer">Default printer</label>
        <select id="station-default-printer" v-model="form.default_printer_id" class="border border-edge rounded-lg bg-surface p-2" :disabled="busy">
          <option :value="null">Choose when printing</option>
          <option v-for="printer in localPrinters" :key="printer.id" :value="printer.id">{{ printer.name }}</option>
        </select>
        <p class="text-sm text-ink-2">Used when the template allows multiple printers on this station.</p>
      </div>
      <label class="flex items-center gap-2 min-h-11"><input v-model="form.enabled" type="checkbox" :disabled="busy" /> Enabled</label>
      <p v-if="editing !== null" class="text-sm text-ink-2">Changing the password or disabling a station signs it out. Changes to allowed printers apply to subsequent print jobs.</p>
      <div class="flex gap-2 flex-wrap">
        <Button type="submit" :label="editing === null ? 'Create station' : 'Save changes'" :loading="busy" :disabled="!form.username.trim() || !form.display_name.trim() || !form.printer_ids.length || (editing === null && !form.password)" />
        <Button v-if="editing !== null" label="Cancel" severity="secondary" :disabled="busy" @click="cancelEdit" />
      </div>
    </form>
  </section>
</template>
