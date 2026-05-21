<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api } from "@/api/client";
import type { AuthName, Reason } from "@/api/types";
import { useToast } from "primevue/usetoast";

import InputText from "primevue/inputtext";
import Button from "primevue/button";

const toast = useToast();

const reasons = ref<Reason[]>([]);
const ops = ref<AuthName[]>([]);
const newReason = ref("");
const newOp = ref("");

onMounted(refresh);

async function refresh() {
  [reasons.value, ops.value] = await Promise.all([
    api.get<Reason[]>("/api/reasons"),
    api.get<AuthName[]>("/api/auth-names"),
  ]);
}

async function addReason() {
  if (!newReason.value.trim()) return;
  await api.post("/api/reasons", { text: newReason.value.trim() });
  newReason.value = "";
  await refresh();
}
async function removeReason(id: number) {
  await api.delete(`/api/reasons/${id}`);
  await refresh();
}
async function addOp() {
  if (!newOp.value.trim()) return;
  await api.post("/api/auth-names", { name: newOp.value.trim() });
  newOp.value = "";
  await refresh();
}
async function removeOp(id: number) {
  await api.delete(`/api/auth-names/${id}`);
  await refresh();
}

void toast;
</script>

<template>
  <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
    <section class="bg-white border border-slate-200 rounded-2xl p-5 shadow-sm">
      <h2 class="text-lg font-bold mb-3">
        Reasons <span class="text-slate-400">({{ reasons.length }})</span>
      </h2>
      <div class="flex gap-2 mb-3">
        <InputText
          v-model="newReason"
          placeholder="New reason"
          class="flex-1"
          @keydown.enter="addReason"
        />
        <Button label="Add" @click="addReason" />
      </div>
      <ul class="space-y-1">
        <li
          v-for="r in reasons"
          :key="r.id"
          class="flex justify-between items-center bg-slate-50 border border-slate-200 rounded-lg px-3 py-1.5"
        >
          <span class="text-sm">{{ r.text }}</span>
          <Button
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

    <section class="bg-white border border-slate-200 rounded-2xl p-5 shadow-sm">
      <h2 class="text-lg font-bold mb-3">
        Operators <span class="text-slate-400">({{ ops.length }})</span>
      </h2>
      <div class="flex gap-2 mb-3">
        <InputText
          v-model="newOp"
          placeholder="Operator name"
          class="flex-1"
          @keydown.enter="addOp"
        />
        <Button label="Add" @click="addOp" />
      </div>
      <ul class="space-y-1">
        <li
          v-for="a in ops"
          :key="a.id"
          class="flex justify-between items-center bg-slate-50 border border-slate-200 rounded-lg px-3 py-1.5"
        >
          <span class="text-sm">{{ a.name }}</span>
          <Button
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
