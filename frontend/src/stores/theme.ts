/**
 * Dark mode preference.
 *
 * `system` is the default so the admin desktop, where someone actually
 * configures their OS, needs no setup. The explicit overrides exist for the
 * wall-mounted tablets: nobody configures those, and the OS setting describes
 * the time of day, not how dark the data hall they hang in happens to be.
 *
 * A class on <html> rather than `prefers-color-scheme` because the override
 * has to be reachable per device without touching the OS, and because one
 * signal then drives PrimeVue's `darkModeSelector` and the token block in
 * style.css — they cannot disagree.
 */
import { defineStore } from "pinia";

export type ThemePreference = "system" | "light" | "dark";

const STORAGE_KEY = "tds-theme";
const DARK_CLASS = "tds-dark";
const MEDIA = "(prefers-color-scheme: dark)";

/** Cycle order; `system` stays in it so a pinned tablet can be handed back. */
const NEXT: Record<ThemePreference, ThemePreference> = {
  system: "light",
  light: "dark",
  dark: "system",
};

export function isPreference(value: unknown): value is ThemePreference {
  return typeof value === "string" && value in NEXT;
}

export function nextPreference(current: ThemePreference): ThemePreference {
  return NEXT[current];
}

/** Mirrored by the pre-paint script in index.html — keep the two in step. */
export function resolveDark(
  preference: ThemePreference,
  systemDark: boolean,
): boolean {
  return preference === "dark" || (preference !== "light" && systemDark);
}

function readStored(): ThemePreference {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (isPreference(raw)) return raw;
  } catch {
    /* storage can throw outright, not just come back empty */
  }
  return "system";
}

function systemPrefersDark(): boolean {
  try {
    return window.matchMedia(MEDIA).matches;
  } catch {
    return false;
  }
}

export const useTheme = defineStore("theme", {
  state: () => ({
    preference: "system" as ThemePreference,
    systemDark: false,
    /** Guards against a second `load()` stacking media listeners. */
    watching: false,
  }),
  getters: {
    dark(state): boolean {
      return resolveDark(state.preference, state.systemDark);
    },
  },
  actions: {
    load() {
      this.preference = readStored();
      this.systemDark = systemPrefersDark();
      if (!this.watching) {
        this.watching = true;
        try {
          window.matchMedia(MEDIA).addEventListener("change", (e) => {
            this.systemDark = e.matches;
            this.apply();
          });
        } catch {
          /* a browser without matchMedia just never leaves `systemDark` */
        }
      }
      this.apply();
    },
    set(preference: ThemePreference) {
      this.preference = preference;
      try {
        localStorage.setItem(STORAGE_KEY, preference);
      } catch {
        /* unwritable storage must still let the operator see this session */
      }
      this.apply();
    },
    cycle() {
      this.set(nextPreference(this.preference));
    },
    apply() {
      if (typeof document === "undefined") return;
      document.documentElement.classList.toggle(DARK_CLASS, this.dark);
    },
  },
});
