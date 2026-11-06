<script setup lang="ts">
/**
 * One tap cycles Auto → Light → Dark. The label names the *preference*, not
 * the resolved theme, because "Auto" on a tablet whose OS is wrong is exactly
 * the state an operator needs to see in order to override it.
 *
 * Only ever rendered on the dark chrome bars, hence the fixed chrome ink.
 */
import { useTheme } from "@/stores/theme";
import Button from "primevue/button";

const theme = useTheme();

const ICONS: Record<string, string> = {
  system: "pi pi-desktop",
  light: "pi pi-sun",
  dark: "pi pi-moon",
};
const LABELS: Record<string, string> = {
  system: "Auto",
  light: "Light",
  dark: "Dark",
};
</script>

<template>
  <Button
    type="button"
    :icon="ICONS[theme.preference]"
    :label="LABELS[theme.preference]"
    :aria-label="`Screen theme: ${LABELS[theme.preference]}. Change.`"
    severity="secondary"
    text
    class="theme-toggle"
    @click="theme.cycle()"
  />
</template>

<style scoped>
/* Unlayered, so it outranks PrimeVue's `primevue` layer without `!important`
   — see the override doctrine at the top of style.css. */
.theme-toggle {
  color: var(--tds-chrome-ink);
  flex-shrink: 0;
}
.theme-toggle:hover {
  background: color-mix(in srgb, var(--tds-chrome-ink) 10%, transparent);
}
@media (max-width: 1100px), (pointer: coarse) {
  .theme-toggle {
    min-height: 48px;
    touch-action: manipulation;
  }
}
</style>
