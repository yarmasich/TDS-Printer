import { defineStore } from "pinia";
import { api } from "@/api/client";
import type { CartItem, PrintAllResult } from "@/api/types";
import { useSession } from "./session";

export const useCart = defineStore("cart", {
  state: () => ({
    items: [] as CartItem[],
    loading: false,
  }),
  getters: {
    count(state) {
      return state.items.length;
    },
  },
  actions: {
    async fetch() {
      const sid = useSession().ensure();
      this.loading = true;
      try {
        this.items = await api.get<CartItem[]>(
          `/api/cart?sid=${encodeURIComponent(sid)}`,
        );
      } finally {
        this.loading = false;
      }
    },
    async add(labelId: number) {
      const sid = useSession().ensure();
      await api.post<CartItem>("/api/cart", { sid, label_id: labelId });
      await this.fetch();
    },
    async remove(itemId: number) {
      const sid = useSession().ensure();
      await api.delete(
        `/api/cart/${itemId}?sid=${encodeURIComponent(sid)}`,
      );
      await this.fetch();
    },
    async clear() {
      const sid = useSession().ensure();
      await api.delete(`/api/cart?sid=${encodeURIComponent(sid)}`);
      await this.fetch();
    },
    async printAll(operator?: string, reason?: string) {
      const sid = useSession().ensure();
      const res = await api.post<PrintAllResult>("/api/cart/print", {
        sid,
        operator: operator ?? "",
        reason: reason ?? "",
      });
      await this.fetch();
      return res;
    },
  },
});
