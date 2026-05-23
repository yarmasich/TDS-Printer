<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import InputText from "primevue/inputtext";
import Password from "primevue/password";
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
  error.value = null;
  loading.value = true;
  try {
    await auth.login(username.value, password.value);
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
        Print and kiosk stay open for operators. Only this panel requires a
        password.
      </p>

      <p v-if="!auth.configured" class="login-error">
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
        :disabled="!auth.configured"
      />

      <label class="login-label" for="admin-pass">Password</label>
      <Password
        id="admin-pass"
        v-model="password"
        :feedback="false"
        toggle-mask
        autocomplete="current-password"
        class="w-full"
        input-class="w-full"
        :disabled="!auth.configured"
        @keyup.enter="submit"
      />

      <p v-if="error" class="login-error">{{ error }}</p>

      <Button
        type="submit"
        label="Sign in"
        icon="pi pi-lock"
        class="w-full login-submit"
        :loading="loading"
        :disabled="!auth.configured || !username || !password"
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
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  padding: 28px 24px;
  box-shadow: 0 8px 30px rgba(15, 23, 42, 0.08);
}

.login-title {
  margin: 0 0 8px;
  font-size: 24px;
  font-weight: 800;
  color: #0f172a;
}

.login-lead {
  margin: 0 0 20px;
  font-size: 14px;
  line-height: 1.45;
  color: #64748b;
}

.login-label {
  display: block;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #475569;
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
  color: #b91c1c;
  background: #fef2f2;
  border: 1px solid #fecaca;
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
  color: #0284c7;
  text-decoration: none;
}

.login-back:hover {
  text-decoration: underline;
}

.login-card :deep(.p-password),
.login-card :deep(.p-password-input) {
  width: 100%;
}
</style>
