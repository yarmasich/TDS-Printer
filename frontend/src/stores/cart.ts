import { defineStore } from "pinia";
import { api, ApiError } from "@/api/client";
import type { CartItem, PrintAllResult } from "@/api/types";
import { useSession, type CartScope } from "./session";

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
      const sid = useSession().ensure(scope);
      const revision = ++this.revision;
      this.loading = true;
      this.error = "";
      try {
        const items = await api.get<CartItem[]>(
          `/api/cart?sid=${encodeURIComponent(sid)}`,
        );
        if (revision === this.revision) this.items = items;
      } catch (error) {
        if (revision === this.revision) this.error = error instanceof Error ? error.message : String(error);
        throw error;
      } finally {
        if (revision === this.revision) this.loading = false;
      }
    },
    async add(labelId: number) {
      const sid = useSession().ensure(scope);
      await api.post<CartItem>("/api/cart", { sid, label_id: labelId });
      await this.fetch();
    },
    async addMany(labelIds: number[]) {
      if (!labelIds.length) return;
      const sid = useSession().ensure(scope);
      try {
        for (const label_id of labelIds) await api.post<CartItem>("/api/cart", { sid, label_id });
      } finally { await this.fetch(); }
    },
    async remove(itemId: number) {
      const sid = useSession().ensure(scope);
      if (this.printing || this.items.find(i => i.id === itemId)?.status === "printing") throw new Error("Printing is active. Refresh the cart when it finishes.");
      await api.delete(
        `/api/cart/${itemId}?sid=${encodeURIComponent(sid)}`,
      );
      await this.fetch();
    },
    async clear() {
      if (this.hasPrinting) throw new Error("Printing is active. Wait, then refresh the cart.");
      const sid = useSession().ensure(scope);
      await api.delete(`/api/cart?sid=${encodeURIComponent(sid)}`);
      await this.fetch();
    },
    async printAll(operator?: string, reason?: string) {
      const sid = useSession().ensure(scope);
      if (this.hasPrinting) throw new Error("Printing is already active. Wait, then refresh the cart.");
      if (!this.queuedCount) throw new Error("No queued labels. Check uncertain labels at the printer before deciding to print again.");
      this.printing = true;
      try {
        return await api.post<PrintAllResult>("/api/cart/print", {
          sid, operator: operator ?? "", reason: reason ?? "",
        });
      } catch (error) {
        if (error instanceof ApiError && error.status === 409) throw new Error("Printing is already active. Wait, then refresh the cart; do not resend labels.");
        throw error;
      } finally {
        try { await this.fetch(); }
        catch {
          // Without a fresh snapshot, never offer the just-submitted rows again.
          for (const item of this.items) if (item.status === "queued") {
            item.status = "uncertain";
            item.error = "Could not refresh print status. Refresh the cart and check the printer before printing again.";
          }
        } finally { this.printing = false; }
      }
    },
  },
});

const cartStores = { print: createCart("print"), kiosk: createCart("kiosk") };
export const useCart = (scope: CartScope = "print") => cartStores[scope]();
