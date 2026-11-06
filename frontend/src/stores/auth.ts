import { defineStore } from "pinia";
import { api } from "@/api/client";

const TOKEN_KEY = "tds-admin-token";

export const useAuth = defineStore("auth", {
  state: () => ({
    token: null as string | null,
    configured: null as boolean | null,
    statusLoading: false,
    statusError: "",
  }),
  getters: {
    isAuthenticated(state): boolean {
      return !!state.token;
    },
  },
  actions: {
    load() {
      this.token = sessionStorage.getItem(TOKEN_KEY);
    },
    async checkStatus() {
      if (this.statusLoading) return;
      this.statusLoading = true;
      this.statusError = "";
      this.configured = null;
      try {
        const s = await api.get<{ configured: boolean }>("/api/auth/status");
        this.configured = s.configured;
      } catch (error) {
        this.statusError = error instanceof Error ? error.message : String(error);
      } finally {
        this.statusLoading = false;
      }
    },
    async login(username: string, password: string) {
      const res = await api.post<{ access_token: string }>("/api/auth/login", {
        username,
        password,
      });
      this.token = res.access_token;
      sessionStorage.setItem(TOKEN_KEY, res.access_token);
    },
    logout() {
      this.token = null;
      sessionStorage.removeItem(TOKEN_KEY);
    },
  },
});
