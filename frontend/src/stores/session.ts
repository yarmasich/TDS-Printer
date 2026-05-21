/**
 * Per-browser session id. Used as the cart's owner key so each tablet
 * has its own basket. Persisted in localStorage so reloads keep the cart.
 */
import { defineStore } from "pinia";

const KEY = "tds.sid";

function makeSid(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return "s-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export const useSession = defineStore("session", {
  state: () => ({
    sid: localStorage.getItem(KEY) ?? "",
  }),
  actions: {
    ensure() {
      if (!this.sid) {
        this.sid = makeSid();
        localStorage.setItem(KEY, this.sid);
      }
      return this.sid;
    },
  },
});
