import "./style.css";
import { createApp } from "vue";
import { createPinia } from "pinia";
import PrimeVue from "primevue/config";
import ToastService from "primevue/toastservice";
import ConfirmationService from "primevue/confirmationservice";
import Aura from "@primeuix/themes/aura";

import App from "./App.vue";
import { router } from "./router";

const app = createApp(App);
app.use(createPinia());
app.use(router);
app.use(PrimeVue, {
  theme: {
    preset: Aura,
    options: {
      darkModeSelector: ".never-dark", // disable dark mode for kiosk
    },
  },
  ripple: false,
});
app.use(ToastService);
app.use(ConfirmationService);
app.mount("#app");
