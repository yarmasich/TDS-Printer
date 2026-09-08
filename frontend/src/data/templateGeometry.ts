import type { Template } from '@/api/types';
import { findTemplatePreset } from './panduit';

type Geometry = Pick<Template, 'name' | 'bytes_per_row' | 'height' | 'left_left' | 'left_right' | 'left_top' | 'left_bottom' | 'right_left' | 'right_right' | 'right_top' | 'right_bottom' | 'gap_left' | 'gap_right' | 'gap_top' | 'gap_bottom'>;

function fits(t: Geometry, width: number, height: number): boolean {
  return (['left', 'right'] as const).every(side => {
    const x0 = t[`${side}_left`] + t.gap_left;
    const x1 = t[`${side}_right`] - t.gap_right;
    const y0 = t[`${side}_top`] + t.gap_top;
    const y1 = t[`${side}_bottom`] - t.gap_bottom;
    return 0 <= x0 && x0 < x1 && x1 <= width && 0 <= y0 && y0 < y1 && y1 <= height;
  });
}

/** Offer a page-only correction when the SKU page fits all calibrated areas. */
export function pageSizeRepair(t: Geometry): { bytes_per_row: number; height: number } | null {
  if (fits(t, t.bytes_per_row * 8, t.height)) return null;
  const preset = findTemplatePreset(t.name);
  if (!preset || !fits(t, preset.bytes_per_row * 8, preset.height)) return null;
  return { bytes_per_row: preset.bytes_per_row, height: preset.height };
}
