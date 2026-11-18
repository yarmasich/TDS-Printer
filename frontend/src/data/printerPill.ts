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

// Conditions the printer reports that never hold a print (server `warnings`).
const WARNINGS: Record<string, { short: string; sentence: string }> = {
  media_low: { short: "labels low", sentence: "Labels are running low." },
  ribbon_low: { short: "ribbon low", sentence: "Ribbon is running low." },
  maintenance_due: { short: "maintenance due", sentence: "Maintenance is due." },
};

function knownWarnings(warnings: readonly string[] | null | undefined) {
  // Own keys only, so a value like "toString" is never read as a warning.
  return (warnings ?? []).flatMap((w) => {
    const known = Object.prototype.hasOwnProperty.call(WARNINGS, w) ? WARNINGS[w] : undefined;
    return known ? [known] : [];
  });
}

/** " · ribbon low · labels low" for the warnings the UI knows, else "". */
export function warningSuffix(warnings: readonly string[] | null | undefined): string {
  return knownWarnings(warnings).map((w) => ` · ${w.short}`).join("");
}

/** The state label followed by its warnings, e.g. "Ready · ribbon low". */
export function withWarnings(label: string, warnings: readonly string[] | null | undefined): string {
  return label + warningSuffix(warnings);
}

function warningSentences(warnings: readonly string[] | null | undefined): string {
  return knownWarnings(warnings).map((w) => w.sentence).join(" ");
}

/** null = checking, undefined = no info yet. */
export function pillFor(ping: PingResult | null | undefined): Pill {
  if (ping === undefined) return { label: "unknown", tone: "muted" };
  if (ping === null) return { label: "checking…", tone: "checking" };
  const fault = FAULTS[ping.device_status?.state ?? ""];
  const warnings = ping.device_status?.warnings;
  const notes = warningSentences(warnings);
  // A fault found mid-job outranks "busy": TCP is skipped then, SNMP is not.
  if (fault && (ping.ok || ping.error.toLowerCase().includes("busy"))) {
    return notes ? { ...fault, title: `${fault.title} ${notes}` } : fault;
  }
  if (!ping.ok) {
    return ping.error.toLowerCase().includes("busy")
      ? { label: "busy", tone: "warn", title: ping.error }
      : { label: "offline", tone: "danger", title: ping.error };
  }
  const state = ping.device_status?.state;
  // Warnings never hold a print, so the state stays first and they follow it.
  if (state === "busy") {
    return notes
      ? { label: withWarnings("Printing", warnings), tone: "warn", title: `Printing works. ${notes}` }
      : { label: "printing", tone: "warn" };
  }
  if (state === "ready" && notes) {
    return { label: withWarnings("Ready", warnings), tone: "warn", title: `Printing works. ${notes}` };
  }
  return { label: `online · ${ping.ms} ms`, tone: "ok" };
}
