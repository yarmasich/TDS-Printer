<script setup lang="ts">
import { computed } from "vue";
import { RouterLink, RouterView, useRoute } from "vue-router";
import Toast from "primevue/toast";
import ConfirmDialog from "primevue/confirmdialog";

const route = useRoute();
const isKiosk = computed(() => Boolean(route.meta.kiosk));
</script>

<template>
  <div class="min-h-full" :class="{ 'kiosk-app': isKiosk }">
    <header
      v-if="!isKiosk"
      class="bg-gradient-to-r from-slate-900 to-indigo-900 text-white shadow-lg"
    >
      <div class="mx-auto max-w-7xl px-6 py-4 flex items-center gap-6">
        <h1 class="text-2xl font-bold tracking-tight">TDS Printer</h1>
        <nav class="flex gap-2 flex-wrap">
          <RouterLink
            to="/"
            class="px-4 py-2 rounded-lg text-sm font-semibold transition"
            active-class="bg-white/20"
            exact-active-class="bg-white/20"
          >
            Print
          </RouterLink>
          <RouterLink
            to="/kiosk"
            class="px-4 py-2 rounded-lg text-sm font-semibold transition"
            active-class="bg-white/20"
          >
            Kiosk
          </RouterLink>
          <RouterLink
            to="/admin"
            class="px-4 py-2 rounded-lg text-sm font-semibold transition"
            active-class="bg-white/20"
          >
            Admin
          </RouterLink>
          <a
            href="/docs"
            target="_blank"
            class="px-4 py-2 rounded-lg text-sm font-semibold transition hover:bg-white/10"
            >API</a
          >
        </nav>
      </div>
    </header>

    <main :class="isKiosk ? 'kiosk-main' : 'mx-auto max-w-7xl px-6 py-6'">
      <RouterView />
    </main>

    <Toast :position="isKiosk ? 'top-center' : 'bottom-right'" />
    <ConfirmDialog />
  </div>
</template>

<style>
.kiosk-app {
  height: 100dvh;
  overflow: visible;
}
.kiosk-main {
  height: 100%;
  padding: 0;
  max-width: none;
  overflow: auto;
  -webkit-overflow-scrolling: touch;
}
</style>
