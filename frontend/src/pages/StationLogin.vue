<script setup lang="ts">
import { onMounted, ref, useTemplateRef } from "vue";
import { useRoute, useRouter } from "vue-router";
import InputText from "primevue/inputtext";
import Button from "primevue/button";
import { useStationAuth } from "@/stores/stationAuth";
import { ApiError } from "@/api/client";

const auth = useStationAuth();
const router = useRouter();
const route = useRoute();

function destination() {
  const value = route.query.redirect;
  return typeof value === "string" && (value === "/" || value === "/kiosk") ? value : "/";
}

const username = ref("");
const password = ref("");
const loading = ref(false);
const error = ref<string | null>(null);

// PrimeVue InputText wraps a native <input>; reach through `$el` to focus
// the real element.
const userInput = useTemplateRef<{ $el: HTMLInputElement }>("userInput");

onMounted(async () => {
  await auth.restore();
  // A restored station redirects, so don't focus a field on the way out.
  if (auth.station) {
    await router.replace(destination());
    return;
  }
  // `restore()` is async: by now the operator may already be typing, or have
  // tapped Password. Only take focus when nothing else holds it. Unlike the
  // search box this focuses on tablets too — sign-in always ends in typing.
  const active = document.activeElement;
  if (!active || active === document.body) userInput.value?.$el?.focus();
});

async function submit() {
  if (loading.value) return;
  error.value = null;
  loading.value = true;
  try {
    const user = username.value.trim();
    const pass =
      typeof password.value === "string"
        ? password.value
        : String(password.value ?? "");
    await auth.login(user, pass);
    await router.replace(destination());
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
      <h1 class="login-title">Station sign in</h1>
      <p class="login-lead">
        Sign in with this workstation’s account. Labels print to its assigned printer. Scan your employee RFID when printing.
      </p>

      <label class="login-label" for="station-user">Username</label>
      <InputText
        ref="userInput"
        id="station-user"
        v-model="username"
        autocomplete="username"
        class="w-full"
      />

      <label class="login-label" for="station-pass">Password</label>
      <InputText
        id="station-pass"
        v-model="password"
        type="password"
        autocomplete="current-password"
        class="w-full"
      />

      <p v-if="error || auth.error" class="login-error" role="alert">{{ error || auth.error }}</p>

      <Button
        type="submit"
        label="Sign in"
        icon="pi pi-lock"
        class="w-full login-submit"
        :loading="loading"
        :disabled="!username.trim() || !password"
      />

      <RouterLink v-if="!auth.required && !auth.error" to="/" class="login-back">← Back to print</RouterLink>
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
