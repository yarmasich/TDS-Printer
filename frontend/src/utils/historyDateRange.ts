function localDate(value: string): Date | null {
  const parts = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(value);
  if (!parts) return null;
  const date = new Date(value);
  const expected = parts.slice(1).map(Number);
  const actual = [date.getFullYear(), date.getMonth() + 1, date.getDate(), date.getHours(), date.getMinutes()];
  if (!Number.isFinite(date.getTime()) || actual.some((part, i) => part !== expected[i])) return null;
  if (parts[6] !== undefined && date.getSeconds() !== expected[5]) return null;
  return date;
}

/** Validate datetime-local values before converting them to UTC API parameters. */
export function historyDateRange(since: string, until: string) {
  const fromDate = since ? localDate(since) : null;
  const untilDate = until ? localDate(until) : null;
  let error = '';
  if (since && !fromDate) error = 'Enter a valid From date and time.';
  else if (until && !untilDate) error = 'Enter a valid Until date and time.';
  else if (fromDate && untilDate && untilDate <= fromDate) error = 'Until must be later than From (the end time is exclusive).';
  return {since: fromDate?.toISOString(), until: untilDate?.toISOString(), error};
}
