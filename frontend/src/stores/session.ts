/**
 * Per-browser session ids for the print cart vs the kiosk cart.
 * Each scope has its own localStorage key so / and /kiosk do not share
 * a basket on the same device.
 */
import { defineStore } from "pinia";

export type CartScope = "print" | "kiosk";

const LEGACY_KEY = "tds.sid";
const KEYS: Record<CartScope, string> = {
  print: "tds.sid.print",
  kiosk: "tds.sid.kiosk",
};

function makeSid(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return "s-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
}

function storageKey(scope: CartScope): string {
  const stationId = sessionStorage.getItem("tds-station-id");
  return stationId ? `${KEYS[scope]}.station.${stationId}` : KEYS[scope];
}

function readSid(scope: CartScope): string {
  const key = storageKey(scope);
  let sid = localStorage.getItem(key) ?? "";
  if (!sid && scope === "print" && key === KEYS.print) {
    sid = localStorage.getItem(LEGACY_KEY) ?? "";
    if (sid) {
      localStorage.setItem(key, sid);
      localStorage.removeItem(LEGACY_KEY);
    }
  }
  return sid;
}

export const useSession = defineStore("session", {
  actions: {
    ensure(scope: CartScope = "print"): string {
      let sid = readSid(scope);
      if (!sid) {
        sid = makeSid();
        localStorage.setItem(storageKey(scope), sid);
      }
      return sid;
    },
    /** New opaque id — previous cart rows stay in DB but are no longer visible. */
    reset(scope: CartScope = "print"): string {
      const sid = makeSid();
      localStorage.setItem(storageKey(scope), sid);
      return sid;
    },
  },
});
