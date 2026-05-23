import { defineStore } from "pinia";

const STORAGE_KEY = "tds-kiosk-context";

export const useKiosk = defineStore("kiosk", {
  state: () => ({
    projectId: null as number | null,
    disciplineId: null as number | null,
  }),
  getters: {
    isReady(state): boolean {
      return state.projectId != null && state.disciplineId != null;
    },
  },
  actions: {
    load() {
      try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) return;
        const data = JSON.parse(raw) as {
          projectId?: number;
          disciplineId?: number;
        };
        if (typeof data.projectId === "number") this.projectId = data.projectId;
        if (typeof data.disciplineId === "number")
          this.disciplineId = data.disciplineId;
      } catch {
        /* ignore corrupt storage */
      }
    },
    save(projectId: number, disciplineId: number) {
      this.projectId = projectId;
      this.disciplineId = disciplineId;
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ projectId, disciplineId }),
      );
    },
    clear() {
      this.projectId = null;
      this.disciplineId = null;
      localStorage.removeItem(STORAGE_KEY);
    },
  },
});
