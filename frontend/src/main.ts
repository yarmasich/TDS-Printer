import "./style.css";
import "primeicons/primeicons.css";
import { createApp } from "vue";
import { createPinia } from "pinia";
import PrimeVue from "primevue/config";
import ToastService from "primevue/toastservice";
import ConfirmationService from "primevue/confirmationservice";
import Aura from "@primeuix/themes/aura";
import { definePreset } from "@primeuix/themes";

import App from "./App.vue";
import { router } from "./router";

// Aura's dark surfaces are zinc (neutral grey); this app is slate everywhere
// else, and a zinc dialog on a slate page reads as two different products.
// Re-points only the dark ramp, so light mode is untouched. The values here
// are what the `--tds-*` dark tokens in style.css are matched against:
// card = 900, page and form field = 950, border = 700.
const TdsAura = definePreset(Aura, {
  semantic: {
    colorScheme: {
      dark: {
        surface: {
          0: "#ffffff",
          50: "{slate.50}",
          100: "{slate.100}",
          200: "{slate.200}",
          300: "{slate.300}",
          400: "{slate.400}",
          500: "{slate.500}",
          600: "{slate.600}",
          700: "{slate.700}",
          800: "{slate.800}",
          900: "{slate.900}",
          950: "{slate.950}",
        },
      },
    },
  },
});

const app = createApp(App);
app.use(createPinia());
app.use(router);
app.use(PrimeVue, {
  theme: {
    preset: TdsAura,
    options: {
      // Driven by stores/theme.ts and the pre-paint script in index.html, so
      // PrimeVue's components and our own token block flip off one signal.
      darkModeSelector: ".tds-dark",
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
