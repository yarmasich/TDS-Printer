import { defineStore } from "pinia";
import { api } from "@/api/client";
import type { PingResult, Printer } from "@/api/types";

export const usePrinters = defineStore("printers", {
  state: () => ({
    printers: [] as Printer[],
    /** printer_id → last ping result (null while loading) */
    pingByPrinter: {} as Record<number, PingResult | null>,
  }),
  actions: {
    async loadAll() {
      this.printers = await api.get<Printer[]>("/api/printers");
    },
    async pingOne(printerId: number): Promise<PingResult> {
      this.pingByPrinter[printerId] = null;
      const res = await api.get<PingResult>(
        `/api/printers/${printerId}/ping`,
      );
      this.pingByPrinter[printerId] = res;
      return res;
    },
    async pingAll(): Promise<PingResult[]> {
      // mark all checking
      for (const p of this.printers) this.pingByPrinter[p.id] = null;
      const arr = await api.get<PingResult[]>("/api/printers/ping-all");
      for (const r of arr) this.pingByPrinter[r.printer_id] = r;
      return arr;
    },
  },
});
