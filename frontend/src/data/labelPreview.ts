import type { StockMaterial } from './labelStock';

export interface LabelPreview {
  image: string;
  template_only?: boolean;
  width: number;
  height: number;
  material_sku: string;
  areas: { label: 'Left' | 'Right'; x: number; y: number; width: number; height: number }[];
  material: null | { width_mm: number; height_mm: number; print_height_mm: number; color: string };
  /** Catalog stock for the physical label view; null without a known material. */
  stock?: StockMaterial | null;
}

/** Keep expensive raster rendering bounded across every visible result card. */
export function createPreviewQueue(limit = 2) {
  let active = 0;
  const pending: (() => void)[] = [];
  function drain() {
    while (active < limit && pending.length) pending.shift()!();
  }
  return function enqueue<T>(task: () => Promise<T>, signal: AbortSignal): Promise<T> {
    return new Promise((resolve, reject) => {
      const abort = () => {
        const index = pending.indexOf(start);
        if (index !== -1) pending.splice(index, 1);
        reject(new DOMException('Preview cancelled', 'AbortError'));
      };
      const start = () => {
        signal.removeEventListener('abort', abort);
        if (signal.aborted) { abort(); return; }
        active++;
        Promise.resolve().then(task).then(resolve, reject).finally(() => { active--; drain(); });
      };
      if (signal.aborted) { abort(); return; }
      signal.addEventListener('abort', abort, { once: true });
      pending.push(start);
      drain();
    });
  };
}

export const enqueuePreview = createPreviewQueue();
