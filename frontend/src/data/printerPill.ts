import type { PingResult } from "@/api/types";

/** How often a visible print page re-reads its printer. The server shares one
 * SNMP read per printer for 5 s, so any number of tablets cost one probe. */
export const PILL_REFRESH_MS = 20_000;

export type PillTone = "muted" | "checking" | "ok" | "warn" | "danger";
export interface Pill { label: string; tone: PillTone; title?: string }

// The faults the print preflight holds a job for. A DP4600H with its head open
// still accepts TCP on 9100, so without these the pill would read "online".
const FAULTS: Record<string, Pill> = {
  cover_open: { label: "cover open", tone: "danger", title: "Close the printhead, then print." },
  no_media: { label: "no labels", tone: "danger", title: "Load labels, then print." },
  error: { label: "printer error", tone: "danger", title: "Check the ribbon, jams and the printer display." },
};

/** null = checking, undefined = no info yet. */
export function pillFor(ping: PingResult | null | undefined): Pill {
  if (ping === undefined) return { label: "unknown", tone: "muted" };
  if (ping === null) return { label: "checking…", tone: "checking" };
  const fault = FAULTS[ping.device_status?.state ?? ""];
  // A fault found mid-job outranks "busy": TCP is skipped then, SNMP is not.
  if (fault && (ping.ok || ping.error.toLowerCase().includes("busy"))) return fault;
  if (!ping.ok) {
    return ping.error.toLowerCase().includes("busy")
      ? { label: "busy", tone: "warn", title: ping.error }
      : { label: "offline", tone: "danger", title: ping.error };
  }
  if (ping.device_status?.state === "busy") return { label: "printing", tone: "warn" };
  return { label: `online · ${ping.ms} ms`, tone: "ok" };
}
