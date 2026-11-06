/** Keep Auto Fit's lower bound valid after either maximum changes. */
export function clampMinimumFont(minimum: number, left: number, right: number) {
  return Math.max(1, Math.min(minimum, left, right));
}
export function calibrationPending(x: unknown, y: unknown, savedX: number, savedY: number, measuredX: unknown, measuredY: unknown) {
  return x !== savedX || y !== savedY || measuredX !== 0 || measuredY !== 0;
}
export function draftChanged(snapshot: string, draft: unknown) {
  return snapshot !== JSON.stringify(draft);
}
/** Router and section navigation may ask simultaneously; never replace a pending dialog. */
export function singleLeaveDecision(decide: () => Promise<boolean>) {
  let pending: Promise<boolean> | null = null;
  return () => {
    if (!pending) pending = decide().finally(() => { pending = null; });
    return pending;
  };
}
