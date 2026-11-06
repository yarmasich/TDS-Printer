<script setup lang="ts">
import { useAdminRequests } from "@/composables/adminRequests";
const requests = useAdminRequests();
const requestError = requests.error;
import { onMounted, ref } from "vue";
import { api } from "@/api/client";
import type { AuthName, Reason } from "@/api/types";

import InputText from "primevue/inputtext";
import Button from "primevue/button";

const reasons = ref<Reason[]>([]);
const ops = ref<AuthName[]>([]);
const newReason = ref("");
const newOp = ref("");

onMounted(refresh);

async function refresh() {
  await requests.run("refresh", () => refreshRequest());
}
async function refreshRequest() {
  [reasons.value, ops.value] = await Promise.all([
    api.get<Reason[]>("/api/reasons"),
    api.get<AuthName[]>("/api/auth-names"),
  ]);
}

async function addReason() {
  await requests.run("addReason", () => addReasonRequest());
}
async function addReasonRequest() {
  if (!newReason.value.trim()) return;
  await api.post("/api/reasons", { text: newReason.value.trim() });
  newReason.value = "";
  await refresh();
}
async function removeReason(id: number) {
  await requests.run("removeReason", () => removeReasonRequest(id));
}
async function removeReasonRequest(id: number) {
  await api.delete(`/api/reasons/${id}`);
  await refresh();
}
async function addOp() {
  await requests.run("addOp", () => addOpRequest());
}
async function addOpRequest() {
  if (!newOp.value.trim()) return;
  await api.post("/api/auth-names", { name: newOp.value.trim() });
  newOp.value = "";
  await refresh();
}
async function removeOp(id: number) {
  await requests.run("removeOp", () => removeOpRequest(id));
}
async function removeOpRequest(id: number) {
  await api.delete(`/api/auth-names/${id}`);
  await refresh();
}
</script>

<template>
  <div class="admin-touch grid grid-cols-1 md:grid-cols-2 gap-4">
    <section class="admin-touch bg-surface border border-edge rounded-2xl p-5 shadow-sm">
    <p v-if="requestError" role="alert" class="text-danger my-3">{{ requestError }} — Please try again.</p>
    <p v-if="requests.busy('refresh')" role="status" class="text-ink-2 my-3">Loading…</p>
    <Button v-if="requestError" label="Retry loading" severity="secondary" @click="refresh" />

      <h2 class="text-lg font-bold mb-3">
        Reasons <span class="text-ink-4">({{ reasons.length }})</span>
      </h2>
      <div class="flex flex-wrap gap-2 mb-3">
        <InputText
            aria-label="New reason"
            v-model="newReason"
          placeholder="New reason"
          class="min-w-0 flex-1"
          @keydown.enter="addReason"
        />
        <Button :disabled="requests.pending.value.size > 0" label="Add" @click="addReason" />
      </div>
      <p v-if="!reasons.length && !requests.busy('refresh')" class="text-ink-2">No reasons yet.</p>
      <ul class="space-y-1">
        <li
          v-for="r in reasons"
          :key="r.id"
          class="flex justify-between items-center bg-sunken border border-edge rounded-lg px-3 py-1.5"
        >
          <span class="text-sm">{{ r.text }}</span>
          <Button :disabled="requests.pending.value.size > 0"
            icon="pi pi-times"
            text
            severity="danger"
            size="small"
            aria-label="Delete"
            @click="removeReason(r.id)"
          />
        </li>
      </ul>
    </section>

    <section class="bg-surface border border-edge rounded-2xl p-5 shadow-sm">
      <h2 class="text-lg font-bold mb-3">
        Operators <span class="text-ink-4">({{ ops.length }})</span>
      </h2>
      <div class="flex flex-wrap gap-2 mb-3">
        <InputText
            aria-label="Operator name"
            v-model="newOp"
          placeholder="Operator name"
          class="min-w-0 flex-1"
          @keydown.enter="addOp"
        />
        <Button :disabled="requests.pending.value.size > 0" label="Add" @click="addOp" />
      </div>
      <p v-if="!ops.length && !requests.busy('refresh')" class="text-ink-2">No operators yet.</p>
      <ul class="space-y-1">
        <li
          v-for="a in ops"
          :key="a.id"
          class="flex justify-between items-center bg-sunken border border-edge rounded-lg px-3 py-1.5"
        >
          <span class="text-sm">{{ a.name }}</span>
          <Button :disabled="requests.pending.value.size > 0"
            icon="pi pi-times"
            text
            severity="danger"
            size="small"
            aria-label="Delete"
            @click="removeOp(a.id)"
          />
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
@media (pointer: coarse) { .admin-touch :deep(.p-button), .admin-touch :deep(.p-select), .admin-touch :deep(.p-inputtext) { min-height:44px; } .admin-touch :deep(.p-button-icon-only) { min-width:44px; } }
</style>
