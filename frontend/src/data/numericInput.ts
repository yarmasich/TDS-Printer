/** Commit a finite numeric input, retaining the last value when cleared/invalid. */
export function boundedNumber(value: number, previous: number, min: number, max: number): number {
  return Number.isFinite(value) ? Math.max(min, Math.min(max, value)) : previous;
}
