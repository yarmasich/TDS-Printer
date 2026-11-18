/** Toast detail for a partly failed print. A printer fault holds every label
 * routed to it with the same reason, so a 50-label cart would otherwise repeat
 * one sentence fifty times and bury the per-printer summary. */
export function printFailureDetail(destinations: string, errors: { error: string }[]): string {
  return [destinations, ...new Set(errors.map((e) => e.error))].filter(Boolean).join("; ");
}
