export interface LabelPreview {
  image: string;
  width: number;
  height: number;
  material_sku: string;
  areas: { label: 'Left' | 'Right'; x: number; y: number; width: number; height: number }[];
  material: null | { width_mm: number; height_mm: number; print_height_mm: number; color: string };
}

export function stickerGeometry(preview: LabelPreview, area: LabelPreview['areas'][number]) {
  const material = preview.material;
  if (!material) return { width: area.width, height: area.height, band: area.height, top: 0 };
  const dots = 300 / 25.4;
  const width = material.width_mm * dots;
  const height = material.height_mm * dots;
  const band = material.print_height_mm * dots;
  return { width, height, band, top: (height - band) / 3 };
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
