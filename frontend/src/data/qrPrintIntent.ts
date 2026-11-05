/** One immutable physical-label intent, including retries after lost HTTP replies. */
export type QrOutcome = 'sent' | 'error_not_sent' | 'uncertain' | 'unknown' | 'in_progress_or_unknown' | 'key_conflict';

export function qrOutcome(ok: boolean, result: unknown): QrOutcome {
  if (!result || typeof result !== 'object') return 'unknown';
  const body = result as Record<string, unknown>;
  const detail = ok ? body : body.detail;
  if (!detail || typeof detail !== 'object') return 'unknown';
  const code = (detail as Record<string, unknown>).code;
  if (ok) return code === 'sent' ? 'sent' : 'unknown';
  // HTTP status alone says nothing about an earlier attempt with this key.
  switch (code) {
    case 'error_not_sent': case 'uncertain': case 'in_progress_or_unknown': case 'key_conflict': return code;
    default: return 'unknown';
  }
}

export function newQrRequestKey(source: Pick<Crypto, 'getRandomValues'> | undefined = globalThis.crypto): string {
  // getRandomValues is available on HTTP LAN origins where randomUUID is absent.
  if (!source?.getRandomValues) throw new Error('Secure random generation is unavailable; use a supported browser.');
  return [...source.getRandomValues(new Uint8Array(16))].map(n => n.toString(16).padStart(2, '0')).join('');
}

export class QrPrintIntent {
  private attempt: { key: string; body: string } | null = null;
  private outcome: QrOutcome = 'unknown';
  constructor(private uuid: () => string = newQrRequestKey) {}
  get active(): boolean { return this.attempt !== null; }
  get requiresCheck(): boolean { return this.active && this.outcome !== 'error_not_sent'; }

  begin(body: unknown): { key: string; body: string } {
    const frozen = JSON.stringify(body);
    if (this.attempt && this.attempt.body !== frozen) {
      throw new Error('Start a new label before changing a submitted request.');
    }
    if (!this.attempt) this.attempt = { key: this.uuid(), body: frozen };
    // A lost response or interrupted request always remains unknown.
    this.outcome = 'unknown';
    return { ...this.attempt };
  }

  record(code: QrOutcome): void { this.outcome = code; }

  newAttempt(checked: boolean): void {
    if (this.requiresCheck && !checked) throw new Error('Check the physical label before starting another attempt.');
    this.attempt = null;
    this.outcome = 'unknown';
  }
}
