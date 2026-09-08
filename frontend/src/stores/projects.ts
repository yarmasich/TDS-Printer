import { defineStore } from "pinia";
import { api } from "@/api/client";
import type { DataHall, Discipline, Project } from "@/api/types";

export const useProjects = defineStore("projects", {
  state: () => ({
    projects: [] as Project[],
    disciplineRevision: 0,
    loadingDisciplines: false,
    disciplineError: "",
    halls: [] as DataHall[],
    /** Disciplines for the currently selected project, with template+printer joined */
    disciplines: [] as Discipline[],
  }),
  actions: {
    async loadProjects() {
      this.projects = await api.get<Project[]>("/api/projects");
    },
    async loadHalls(projectId?: number) {
      const q = projectId ? `?project_id=${projectId}` : "";
      this.halls = await api.get<DataHall[]>(`/api/halls${q}`);
    },
    clearDisciplines() {
      this.disciplineRevision++;
      this.disciplines = [];
      this.loadingDisciplines = false;
      this.disciplineError = "";
    },
    async loadDisciplinesForProject(projectId: number, isCurrent: () => boolean = () => true) {
      return this.loadDisciplines(`/api/disciplines?project_id=${projectId}`, isCurrent);
    },
    async loadDisciplinesAll() {
      return this.loadDisciplines("/api/disciplines");
    },
    async loadDisciplines(url: string, isCurrent: () => boolean = () => true) {
      if (!isCurrent()) return;
      const revision = ++this.disciplineRevision;
      this.disciplines = [];
      this.disciplineError = "";
      this.loadingDisciplines = true;
      try {
        const rows = await api.get<Discipline[]>(url);
        if (revision === this.disciplineRevision && isCurrent()) this.disciplines = rows;
      } catch (error) {
        if (revision === this.disciplineRevision && isCurrent()) this.disciplineError = error instanceof Error ? error.message : String(error);
        throw error;
      } finally {
        if (revision === this.disciplineRevision) this.loadingDisciplines = false;
      }
    },
  },
});
