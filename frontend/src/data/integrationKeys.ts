export type IntegrationScope = 'policy.read' | 'policy.write' | 'print';
export type PrinterPurpose = 'cable_labels' | 'qr_labels';
const scopes: readonly string[] = ['policy.read', 'policy.write', 'print'];

export function keyRequest(name: string, selected: readonly string[]): {name: string; scopes: IntegrationScope[]} {
  const trimmed = name.trim();
  if (!trimmed) throw new Error('Enter a key name.');
  if (!selected.length || new Set(selected).size !== selected.length || selected.some(value => !scopes.includes(value))) {
    throw new Error('Choose valid scoped permissions.');
  }
  return {name: trimmed, scopes: [...selected] as IntegrationScope[]};
}

export function purposeLabel(purposes: readonly string[]): string {
  const labels = purposes.flatMap(purpose => purpose === 'cable_labels' ? ['Cable labels'] : purpose === 'qr_labels' ? ['QR labels'] : []);
  return labels.join(' · ') || 'No supported print type';
}

const scopeLabels: Record<string, string> = {
  'policy.read': 'Read assignments',
  'policy.write': 'Manage assignments',
  print: 'Print cable labels',
};

export function scopeSummary(keyScopes: readonly string[]): string {
  return keyScopes.map(scope => scopeLabels[scope] ?? scope).join(' · ') || 'No permissions';
}

/** Server timestamps are UTC; a value without an offset is read as UTC, not local time. */
export function parseServerTime(value: string): number {
  const zoned = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`;
  return Date.parse(zoned);
}

const units: [Intl.RelativeTimeFormatUnit, number][] = [
  ['year', 365 * 86_400], ['month', 30 * 86_400], ['week', 7 * 86_400],
  ['day', 86_400], ['hour', 3_600], ['minute', 60],
];

export function relativeTime(value: string, now: number = Date.now()): string {
  const at = parseServerTime(value);
  if (Number.isNaN(at)) return 'at an unknown time';
  const seconds = Math.round((at - now) / 1000);
  if (Math.abs(seconds) < 60) return 'just now';
  const format = new Intl.RelativeTimeFormat('en-US', {numeric: 'always'});
  const [unit, size] = units.find(([, length]) => Math.abs(seconds) >= length) ?? units[units.length - 1]!;
  return format.format(Math.trunc(seconds / size), unit);
}

/** "Last used 3 hours ago" or "Never used". The server refreshes it at most every 5 minutes. */
export function lastUsedLabel(lastUsedAt: string | null | undefined, now: number = Date.now()): string {
  return lastUsedAt ? `Last used ${relativeTime(lastUsedAt, now)}` : 'Never used';
}

export function createdLabel(createdAt: string): string {
  const at = parseServerTime(createdAt);
  return Number.isNaN(at) ? 'Created' : `Created ${new Date(at).toLocaleDateString('en-US', {year: 'numeric', month: 'short', day: 'numeric'})}`;
}

/** Project assignment heading: the stored FloorHub name, else the ID. */
export function projectTitle(policy: {external_project_id: string; external_project_name?: string | null}): {title: string; id: string | null} {
  const name = policy.external_project_name?.trim();
  return name ? {title: name, id: policy.external_project_id} : {title: `FloorHub project ${policy.external_project_id}`, id: null};
}
