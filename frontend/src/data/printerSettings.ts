import type { Printer } from '../api/types';
export type CommunityMode = 'keep' | 'replace' | 'reset';
export function communityUpdate(mode: CommunityMode, value: string): { snmp_community?: string | null } {
  if (mode === 'reset') return { snmp_community: null };
  if (mode === 'replace') {
    if (!value || new TextEncoder().encode(value).length > 128) throw new Error('Enter a community of 1–128 UTF-8 bytes.');
    return { snmp_community: value };
  }
  return {};
}
export function printerQrDefaults(printer?: Pick<Printer, 'qr_media_id' | 'qr_label_length_mm'>) {
  return { media: printer?.qr_media_id ?? 'DK-2246', length_mm: printer?.qr_label_length_mm ?? 60 };
}
export function shouldApplyPrinterDefaults(previousId: number, nextId: number, dirty: boolean, frozen: boolean) {
  return nextId > 0 && previousId !== nextId && !dirty && !frozen;
}

export function printerMediaMismatch(mediaId: string | undefined, detectedWidth: number | null | undefined, detectedType: string | null | undefined) {
  if (detectedWidth == null) return false;
  // DK-2246 is sold as 103 mm; Brother reports its 104 mm media code.
  const supportedWidths = mediaId === 'DK-2205' ? [62] : [103, 104];
  return !supportedWidths.includes(detectedWidth) || detectedType !== 'continuous';
}
