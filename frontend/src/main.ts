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
      // Put PrimeVue's generated CSS into its own cascade layer so
      // Tailwind v4's preflight (in `base`) can't strip Dialog's
      // position:fixed etc. Order matches the @layer declaration in
      // style.css; utilities still win over PrimeVue defaults.
      cssLayer: {
        name: "primevue",
        order: "theme, base, primevue, utilities",
      },
    },
  },
  ripple: false,
});
app.use(ToastService);
app.use(ConfirmationService);
app.mount("#app");
