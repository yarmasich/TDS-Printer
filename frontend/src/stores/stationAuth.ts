import { defineStore } from "pinia";
import { api, ApiError, STATION_TOKEN_KEY } from "@/api/client";
import { useCart } from "./cart";
import type { Discipline } from "@/api/types";

export interface Station {
  id: number; username: string; display_name: string; enabled: boolean;
  allowed_printers: { id: number; name: string }[];
  default_printer_id: number | null;
}

export function eligiblePrinters(station: Station, printerIds: number[]) {
  return station.allowed_printers.filter(printer => printerIds.includes(printer.id));
}

export function stationPrinter(station: Station | null, discipline: Discipline | null | undefined) {
  if (!discipline?.printer_id) return;
  if (!station) return discipline;
  const eligible = eligiblePrinters(station, discipline.printer_ids?.length ? discipline.printer_ids : [discipline.printer_id]);
  const target = eligible.length === 1 ? eligible[0] : eligible.find(printer => printer.id === station.default_printer_id);
  if (target) return { printer_id: target.id, printer_name: target.name };
}

export function needsPrinterChoice(station: Station | null, discipline: Discipline) {
  return !!station && eligiblePrinters(station, discipline.printer_ids ?? []).length > 1
    && !stationPrinter(station, discipline);
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
        // Offline or 5xx is no answer about station requirements. Claiming one
        // strands the operator on a sign-in form with no credentials to type,
        // because the router redirects on `error` and the form hides its way
        // back. Only a 401 is an answer, and it fails closed.
        if (!(error instanceof ApiError && error.status === 401)) return;
        this.required = true;
        this.logout();
        this.error = error.message;
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
        // Hand the print flag to this reset so an in-flight printAll cannot
        // release it after the next station starts printing.
        cart.printTicket++;
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
      // A stale message keeps the router bouncing to /login; callers that still
      // need one (a revoked session) set it after signing out.
      this.error = "";
    },
  },
});
