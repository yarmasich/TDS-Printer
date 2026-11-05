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
