import { defineStore } from "pinia";
import { api, ApiError, STATION_TOKEN_KEY } from "@/api/client";
import { useCart } from "./cart";
export interface Station {
  id: number; username: string; display_name: string; printer_id: number;
  printer_name: string | null; enabled: boolean;
}
export const useStationAuth = defineStore("station-auth", {
  state: () => ({ station: null as Station | null, required: true, error: "" }),
  actions: {
    async restore() {
      this.error = "";
      const token = sessionStorage.getItem(STATION_TOKEN_KEY);
      try {
        const status = await api.get<{ required: boolean }>("/api/station-auth/status");
        if (token !== sessionStorage.getItem(STATION_TOKEN_KEY)) return;
        this.required = status.required;
        if (sessionStorage.getItem(STATION_TOKEN_KEY)) {
          const station = await api.get<Station>("/api/station-auth/me");
          if (token !== sessionStorage.getItem(STATION_TOKEN_KEY)) return;
          this.station = station;
          sessionStorage.setItem("tds-station-id", String(this.station.id));
        } else this.station = null;
      } catch (error) {
        if (token && sessionStorage.getItem(STATION_TOKEN_KEY) && token !== sessionStorage.getItem(STATION_TOKEN_KEY)) return;
        this.required = true;
        if (error instanceof ApiError && error.status === 401) this.logout();
        this.error = error instanceof Error ? error.message : String(error);
      }
    },
    async login(username: string, password: string) {
      const result = await api.post<{ access_token: string; station: Station }>("/api/station-auth/login", { username, password });
      this.clearLocalCarts();
      sessionStorage.setItem(STATION_TOKEN_KEY, result.access_token);
      sessionStorage.setItem("tds-station-id", String(result.station.id));
      this.station = result.station;
      this.error = "";
    },
    clearLocalCarts() {
      for (const scope of ["print", "kiosk"] as const) {
        const cart = useCart(scope);
        cart.revision++;
        cart.items = [];
        cart.loading = false;
        cart.printing = false;
        cart.error = "";
      }
    },
    logout() {
      this.clearLocalCarts();
      sessionStorage.removeItem(STATION_TOKEN_KEY);
      sessionStorage.removeItem("tds-station-id");
      this.station = null;
    },
  },
});
