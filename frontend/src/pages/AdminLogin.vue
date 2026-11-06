<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import InputText from "primevue/inputtext";
import Button from "primevue/button";
import { useAuth } from "@/stores/auth";
import { ApiError } from "@/api/client";

const auth = useAuth();
const router = useRouter();
const route = useRoute();

const username = ref("");
const password = ref("");
const loading = ref(false);
const error = ref<string | null>(null);

onMounted(async () => {
  auth.load();
  await auth.checkStatus();
  if (auth.isAuthenticated) {
    await router.replace((route.query.redirect as string) || "/admin");
  }
});

async function submit() {
  if (loading.value || auth.configured !== true || !username.value.trim() || !password.value) return;
  error.value = null;
  loading.value = true;
  try {
    const user = username.value.trim();
    const pass =
      typeof password.value === "string"
        ? password.value
        : String(password.value ?? "");
    await auth.login(user, pass);
    await router.replace((route.query.redirect as string) || "/admin");
  } catch (e: unknown) {
    error.value =
      e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="login-page">
    <form class="login-card" @submit.prevent="submit">
      <h1 class="login-title">Admin sign in</h1>
      <p class="login-lead">
        Manage printers, station accounts, templates and shared label data.
      </p>

      <p v-if="auth.statusLoading" role="status" class="login-lead">Checking sign-in availability…</p>
      <div v-else-if="auth.statusError" class="login-error" role="alert">
        <p>Could not check sign-in availability. {{ auth.statusError }}</p>
        <Button type="button" label="Retry" icon="pi pi-refresh" severity="secondary" class="mt-3" @click="auth.checkStatus()" />
      </div>
      <p v-else-if="auth.configured === false" class="login-error" role="alert">
        Server admin auth is not configured. Set
        <code>ADMIN_USERNAME</code>, <code>ADMIN_PASSWORD</code>, and
        <code>ADMIN_JWT_SECRET</code> on the API host.
      </p>

      <label class="login-label" for="admin-user">Username</label>
      <InputText
        id="admin-user"
        v-model="username"
        autocomplete="username"
        class="w-full"
        :disabled="auth.configured !== true || loading"
        autocapitalize="off"
        :spellcheck="false"
      />

        <label class="login-label" for="admin-pass">Password</label>
        <InputText
          id="admin-pass"
          v-model="password"
          type="password"
          autocomplete="current-password"
          class="w-full"
          :disabled="auth.configured !== true || loading"
        />

      <p v-if="error" class="login-error" role="alert">{{ error }}</p>

      <Button
        type="submit"
        label="Sign in"
        icon="pi pi-lock"
        class="w-full login-submit"
        :loading="loading"
        :disabled="auth.configured !== true || loading || !username.trim() || !password"
      />

      <RouterLink to="/" class="login-back">← Back to print</RouterLink>
    </form>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 60vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.login-card {
  width: 100%;
  max-width: 400px;
  background: var(--tds-surface);
  border: 1px solid var(--tds-edge);
  border-radius: 16px;
  padding: 28px 24px;
  box-shadow: 0 8px 30px var(--tds-shadow);
}

.login-title {
  margin: 0 0 8px;
  font-size: 24px;
  font-weight: 800;
  color: var(--tds-ink);
}

.login-lead {
  margin: 0 0 20px;
  font-size: 14px;
  line-height: 1.45;
  color: var(--tds-ink-3);
}

.login-label {
  display: block;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--tds-ink-2);
  margin-bottom: 6px;
  margin-top: 14px;
}

.login-label:first-of-type {
  margin-top: 0;
}

.login-error {
  margin: 12px 0 0;
  padding: 10px 12px;
  font-size: 13px;
  line-height: 1.4;
  color: var(--tds-danger);
  background: var(--tds-danger-soft);
  border: 1px solid var(--tds-danger-edge);
  border-radius: 8px;
}

.login-submit {
  margin-top: 20px;
}

.login-back {
  display: block;
  margin-top: 16px;
  text-align: center;
  font-size: 14px;
  color: var(--tds-accent);
  text-decoration: none;
}

.login-back:hover {
  text-decoration: underline;
}

</style>
