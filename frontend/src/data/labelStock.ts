import type { Template } from '@/api/types';
import { isTurnTellPreview, previewAreas } from '@/data/previewGeometry';

/** The catalog fields the label view needs (server Material, EasyMark data). */
export interface StockMaterial {
  rows: number; columns: number; page_height_mm: number;
  left_margin_mm: number; top_margin_mm: number; column_pitch_mm: number;
  print_width_mm: number; print_height_mm: number;
  label_width_mm?: number | null; label_length_mm?: number | null;
  print_on_height_mm?: number | null; label_kind?: string | null; corner_radius_mm?: number | null;
}
export interface StockRect { x: number; y: number; w: number; h: number }
export interface StockLabel {
  label: string;
  /** The die-cut label, in preview-image pixels (300 dpi design grid). */
  outline: StockRect;
  /** The opaque white area ink belongs on. */
  printOn: StockRect;
  radius: number;
  /** True when part of the label is clear film (self-laminating, Turn-Tell). */
  clear: boolean;
}
export interface LabelStock { labels: StockLabel[]; kind: string | null; warnings: string[] }

const px = (mm: number) => mm * 300 / 25.4;
const mm = (pixels: number) => pixels * 25.4 / 300;
// EasyMark prose is rounded to 0.001"; anything past this means it was misread.
const SHAPE_TOLERANCE = px(0.5);
// Text areas may be nudged by calibration; beyond this they miss the white area.
const OUTSIDE_TOLERANCE_MM = 1;

/**
 * Physical labels for the preview, or null when the catalog cannot describe
 * them. Shapes come from the material, never from the template: a template
 * whose text areas drifted off the white area must look wrong, not fixed.
 *
 * The label's top is the top of its page row; the white area is placed where
 * the catalog says. Turn-Tell previews are rotated 180°, so columns are
 * mirrored exactly as `previewAreas` mirrors the text areas.
 */
export function labelStock(m: StockMaterial | null | undefined, t: Omit<Template, 'id'>): LabelStock | null {
  return stockFromAreas(m, previewAreas(t), t.bytes_per_row * 8, isTurnTellPreview(t));
}

/** The operator card's view of `/api/labels/{id}/preview`, built the same way. */
export function labelStockForPreview(p: {
  material_sku: string; width: number; height: number; areas: PreviewArea[]; stock?: StockMaterial | null;
}): LabelStock | null {
  const turnTell = isTurnTellPreview({ material_sku: p.material_sku, bytes_per_row: p.width / 8, height: p.height, name: '' });
  return stockFromAreas(p.stock, p.areas, p.width, turnTell);
}

/** Text areas in preview-image pixels, already mirrored for Turn-Tell. */
export interface PreviewArea { label: string; x: number; y: number; width: number; height: number }

function stockFromAreas(m: StockMaterial | null | undefined, areas: PreviewArea[], width: number,
                        turnTell: boolean): LabelStock | null {
  if (!m || m.rows !== 1 || m.columns !== 2 || !m.label_width_mm || !m.label_length_mm || areas.length !== 2) return null;
  const columns = [0, 1].map((c) => {
    const printOn = { x: px(m.left_margin_mm + c * m.column_pitch_mm), y: px(m.top_margin_mm),
                      w: px(m.print_width_mm), h: px(m.print_height_mm) };
    const w = px(m.label_width_mm!), h = px(m.label_length_mm!);
    return { printOn, outline: { x: printOn.x + (printOn.w - w) / 2, y: 0, w, h } };
  });
  const inside = ({ printOn: p, outline: o }: typeof columns[number]) =>
    p.x >= o.x - SHAPE_TOLERANCE && p.y >= o.y - SHAPE_TOLERANCE &&
    p.x + p.w <= o.x + o.w + SHAPE_TOLERANCE && p.y + p.h <= o.y + o.h + SHAPE_TOLERANCE;
  if (!columns.every(inside)) return null;

  const mirror = (r: StockRect): StockRect => (turnTell ? { ...r, x: width - r.x - r.w } : r);
  const clear = !!m.print_on_height_mm && m.label_length_mm - m.print_on_height_mm > 1;
  const labels = areas.map((area, i) => {
    const column = columns[turnTell ? 1 - i : i]!;
    return { label: area.label, outline: mirror(column.outline), printOn: mirror(column.printOn),
             radius: px(m.corner_radius_mm ?? 0), clear };
  });
  const warnings = labels.flatMap(({ label, printOn: p }, i) => {
    const a = areas[i]!;
    const outside = Math.max(0, p.y - a.y, a.y + a.height - p.y - p.h, p.x - a.x, a.x + a.width - p.x - p.w);
    return mm(outside) > OUTSIDE_TOLERANCE_MM
      ? [`${label}: text area is ${mm(outside).toFixed(1)} mm outside the white print-on area.`]
      : [];
  });
  return { labels, kind: m.label_kind ?? null, warnings };
}
