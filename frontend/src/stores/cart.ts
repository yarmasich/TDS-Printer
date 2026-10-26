import { defineStore } from "pinia";
import { api, STATION_TOKEN_KEY } from "@/api/client";
import type { CartItem, PrintAllResult, PrintPolicy } from "@/api/types";
import { useSession, type CartScope } from "./session";

const identity = () => sessionStorage.getItem(STATION_TOKEN_KEY);

const createCart = (scope: CartScope) => defineStore(`cart-${scope}`, {
  state: () => ({
    items: [] as CartItem[],
    loading: false,
    printing: false,
    error: "",
    revision: 0,
  }),
  getters: {
    queuedCount: (state) => state.items.filter(i => i.status === "queued").length,
    hasPrinting: (state) => state.printing || state.items.some(i => i.status === "printing"),
    count(state) {
      return state.items.length;
    },
  },
  actions: {
    async fetch() {
      const account = identity();
      const sid = useSession().ensure(scope);
      const revision = ++this.revision;
      this.loading = true;
      this.error = "";
      try {
        const items = await api.get<CartItem[]>(
          `/api/cart?sid=${encodeURIComponent(sid)}`,
        );
        if (account === identity() && revision === this.revision) this.items = items;
      } catch (error) {
        if (account === identity() && revision === this.revision) this.error = error instanceof Error ? error.message : String(error);
        throw error;
      } finally {
        if (account === identity() && revision === this.revision) this.loading = false;
      }
    },
    async add(labelId: number) {
      const account = identity();
      const sid = useSession().ensure(scope);
      await api.post<CartItem>("/api/cart", { sid, label_id: labelId });
      if (account === identity()) await this.fetch();
    },
    async addMany(labelIds: number[]) {
      if (!labelIds.length) return;
      const account = identity();
      const sid = useSession().ensure(scope);
      try {
        for (const label_id of labelIds) {
          if (account !== identity()) break;
          await api.post<CartItem>("/api/cart", { sid, label_id });
        }
      } finally { if (account === identity()) await this.fetch(); }
    },
    async remove(itemId: number) {
      const account = identity();
      const sid = useSession().ensure(scope);
      if (this.printing || this.items.find(i => i.id === itemId)?.status === "printing") throw new Error("Printing is active. Refresh the cart when it finishes.");
      await api.delete(
        `/api/cart/${itemId}?sid=${encodeURIComponent(sid)}`,
      );
      if (account === identity()) await this.fetch();
    },
    async clear() {
      if (this.hasPrinting) throw new Error("Printing is active. Wait, then refresh the cart.");
      const account = identity();
      const sid = useSession().ensure(scope);
      await api.delete(`/api/cart?sid=${encodeURIComponent(sid)}`);
      if (account === identity()) await this.fetch();
    },
    async printPolicy() {
      const sid = useSession().ensure(scope);
      return api.get<PrintPolicy>(`/api/cart/print-policy?sid=${encodeURIComponent(sid)}`);
    },
    async printAll(operator?: string, reason?: string, rfidCode?: string) {
      const account = identity();
      const sid = useSession().ensure(scope);
      if (this.hasPrinting) throw new Error("Printing is already active. Wait, then refresh the cart.");
      if (!this.queuedCount) throw new Error("No queued labels. Check uncertain labels at the printer before deciding to print again.");
      this.printing = true;
      try {
        return await api.post<PrintAllResult>("/api/cart/print", {
          sid, operator: operator ?? "", reason: reason ?? "",
          ...(rfidCode === undefined ? {} : { rfid_code: rfidCode }),
        });
      } finally {
        if (account === identity()) {
          try { await this.fetch(); }
          catch {
            // Without a fresh snapshot, never offer the just-submitted rows again.
            for (const item of this.items) if (account === identity() && item.status === "queued") {
              item.status = "uncertain";
              item.error = "Could not refresh print status. Refresh the cart and check the printer before printing again.";
            }
          } finally { if (account === identity()) this.printing = false; }
        }
      }
    },
  },
});

const cartStores = { print: createCart("print"), kiosk: createCart("kiosk") };
export const useCart = (scope: CartScope = "print") => cartStores[scope]();
