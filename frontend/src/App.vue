<script setup lang="ts">
import { RouterLink, RouterView } from "vue-router";
import Toast from "primevue/toast";
import ConfirmDialog from "primevue/confirmdialog";
</script>

<template>
  <div class="min-h-full">
    <header
      class="bg-gradient-to-r from-slate-900 to-indigo-900 text-white shadow-lg"
    >
      <div class="mx-auto max-w-7xl px-6 py-4 flex items-center gap-6">
        <h1 class="text-2xl font-bold tracking-tight">TDS Printer</h1>
        <nav class="flex gap-2">
          <RouterLink
            to="/"
            class="px-4 py-2 rounded-lg text-sm font-semibold transition"
            active-class="bg-white/20"
            exact-active-class="bg-white/20"
          >
            Print
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

    <main class="mx-auto max-w-7xl px-6 py-6">
      <RouterView />
    </main>

    <Toast position="bottom-right" />
    <!-- Global confirm dialog so any component calling
         `useConfirm().require(...)` actually pops up. Without this in
         the DOM PrimeVue silently no-ops the call. -->
    <ConfirmDialog />
  </div>
</template>
