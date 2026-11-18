/** Run `refresh` every `ms` while the page is visible, and at once when it
 * becomes visible again. A wall tablet with its screen off polls nothing; one
 * that wakes up shows the printer's current state, not the one it slept on. */
export function startVisibleInterval(
  refresh: () => void,
  ms: number,
  doc: Pick<Document, "visibilityState" | "addEventListener" | "removeEventListener"> = document,
): () => void {
  const tick = () => { if (doc.visibilityState === "visible") refresh(); };
  const timer = setInterval(tick, ms);
  doc.addEventListener("visibilitychange", tick);
  return () => {
    clearInterval(timer);
    doc.removeEventListener("visibilitychange", tick);
  };
}
