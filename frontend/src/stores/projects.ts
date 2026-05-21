import { defineStore } from "pinia";
import { api } from "@/api/client";
import type { DataHall, Discipline, Project } from "@/api/types";

export const useProjects = defineStore("projects", {
  state: () => ({
    projects: [] as Project[],
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
    async loadDisciplinesForProject(projectId: number) {
      this.disciplines = await api.get<Discipline[]>(
        `/api/disciplines?project_id=${projectId}`,
      );
    },
    async loadDisciplinesAll() {
      this.disciplines = await api.get<Discipline[]>("/api/disciplines");
    },
  },
});
