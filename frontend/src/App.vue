<script setup lang="ts">
import { computed } from "vue";
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router";
import Toast from "primevue/toast";
import ConfirmDialog from "primevue/confirmdialog";
import Button from "primevue/button";
import { useAuth } from "@/stores/auth";

const route = useRoute();
const router = useRouter();
const auth = useAuth();
auth.load();

const isKiosk = computed(() => Boolean(route.meta.kiosk));
const isAdminArea = computed(
  () => route.meta.requiresAdmin || route.name === "admin-login",
);

function logoutAdmin() {
  auth.logout();
  router.push("/admin/login");
}
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
            v-if="auth.isAuthenticated"
            to="/admin"
            class="px-4 py-2 rounded-lg text-sm font-semibold transition"
            active-class="bg-white/20"
          >
            Admin
          </RouterLink>
          <RouterLink
            v-else
            to="/admin/login"
            class="px-4 py-2 rounded-lg text-sm font-semibold transition"
            active-class="bg-white/20"
          >
            Admin login
          </RouterLink>
          <Button
            v-if="auth.isAuthenticated && isAdminArea"
            label="Sign out"
            icon="pi pi-sign-out"
            severity="secondary"
            text
            class="!text-white hover:!bg-white/10"
            @click="logoutAdmin"
          />
        </nav>
      </div>
    </header>

    <main :class="isKiosk ? 'kiosk-main' : 'mx-auto max-w-7xl px-6 py-6'">
      <RouterView />
    </main>

    <Toast :position="isKiosk ? 'top-center' : 'bottom-right'" />
    <ConfirmDialog class="tds-confirm-dialog" />
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
