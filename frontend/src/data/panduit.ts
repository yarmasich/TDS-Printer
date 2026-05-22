/**
 * PANDUIT R-series self-laminating wrap-around label catalog.
 *
 * SKU shape:  R<width-100ths>X<length-100ths>V<colourCode>T
 *   e.g. R200X225V1T  →  2.00" × 2.25", white
 *
 * The catalog row gives us a Print-On Area Height (the opaque white
 * strip where the printer actually lays ink); the rest of the
 * label length is the transparent tail that wraps around the cable
 * and laminates the print. The cable Ø range is the diameter window
 * for which the wrap lines up correctly.
 *
 * Data transcribed from PANDUIT's R-series datasheet — values in
 * inches and mm just as printed there.
 */

export interface PanduitColor {
  code: string;
  name: string;
  hex: string;
}

export const PANDUIT_COLORS: Record<string, PanduitColor> = {
  V1: { code: "V1", name: "White",      hex: "#ffffff" },
  V2: { code: "V2", name: "TIA Blue",   hex: "#0072c6" },
  V3: { code: "V3", name: "TIA Green",  hex: "#2e8b57" },
  V7: { code: "V7", name: "TIA Red",    hex: "#c8102e" },
  V8: { code: "V8", name: "TIA Yellow", hex: "#ffd400" },
};

export interface PanduitSpec {
  series: "R";
  /** Full label width, inches (the axis that runs along the cable). */
  width_in: number;
  /** Full label length, inches (the axis that wraps around the cable). */
  length_in: number;
  /** Height of the printable opaque area, inches. */
  print_area_in: number;
  color: PanduitColor;
  /** Compatible cable OD range, inches. */
  min_od_in: number;
  max_od_in: number;
  /** Human-readable wire spec from the datasheet. */
  wire_range: string;
}

// Lookup by (width_100ths, length_100ths) → (print_area_100ths, min_od, max_od, wire_range)
// Print-On Area Height and OD range come straight from the datasheet rows.
type Geom = {
  print_area_in: number;
  min_od_in: number;
  max_od_in: number;
  wire_range: string;
};
const R_GEOM: Record<string, Geom> = {
  // 0.50" width family
  "050x075": { print_area_in: 0.25, min_od_in: 0.12, max_od_in: 0.16, wire_range: "Cat 6 28 AWG / 18-14 AWG" },
  "050x125": { print_area_in: 0.38, min_od_in: 0.16, max_od_in: 0.22, wire_range: "Cat 3 UTP / 12-10 AWG" },
  "050x150": { print_area_in: 0.50, min_od_in: 0.22, max_od_in: 0.28, wire_range: "Cat 5e/6/6A UTP, 5e FTP / 10-6 AWG" },
  // 1.00" width family
  "100x075": { print_area_in: 0.25, min_od_in: 0.12, max_od_in: 0.16, wire_range: "Cat 6 28 AWG / 18-14 AWG" },
  "100x125": { print_area_in: 0.38, min_od_in: 0.16, max_od_in: 0.22, wire_range: "Cat 3 UTP / 12-10 AWG" },
  "100x150": { print_area_in: 0.50, min_od_in: 0.22, max_od_in: 0.28, wire_range: "Cat 5e/6/6A UTP" },
  "100x225": { print_area_in: 0.75, min_od_in: 0.28, max_od_in: 0.39, wire_range: "Cat 6 FTP / 6A FTP / 8-4 AWG" },
  "100x400": { print_area_in: 1.00, min_od_in: 0.39, max_od_in: 0.95, wire_range: "2-1 AWG" },
  // 1.50" / 2.00" width family
  "150x150": { print_area_in: 0.50, min_od_in: 0.22, max_od_in: 0.28, wire_range: "Cat 5e/6/6A UTP, 5e FTP / 10-6 AWG" },
  "200x150": { print_area_in: 0.50, min_od_in: 0.22, max_od_in: 0.28, wire_range: "Cat 5e/6/6A UTP, 5e FTP / 10-6 AWG" },
  "200x225": { print_area_in: 0.75, min_od_in: 0.28, max_od_in: 0.39, wire_range: "Cat 6 FTP / 6A FTP / 8-4 AWG" },
  "200x400": { print_area_in: 1.00, min_od_in: 0.39, max_od_in: 0.95, wire_range: "2-1 AWG" },
};

/**
 * Try to recognise a PANDUIT SKU at the start of a template name.
 * Accepts loose variants like ``R200X225V1T`` or ``R100x150V2T``;
 * everything after the matched prefix is ignored.
 *
 * Returns ``null`` if we can't make sense of it — caller should fall
 * back to a generic geometry view.
 */
export function parsePanduitSku(name: string): PanduitSpec | null {
  const m = name.match(/^R(\d{3})[xX](\d{3})(V[1-9]\d*)?/i);
  if (!m || !m[1] || !m[2]) return null;
  const w100 = m[1];
  const l100 = m[2];
  const key = `${w100}x${l100}`.toLowerCase();
  const geom = R_GEOM[key];
  if (!geom) return null;
  const colorKey = (m[3] ?? "V1").toUpperCase();
  const color = PANDUIT_COLORS[colorKey] ?? PANDUIT_COLORS.V1!;
  return {
    series: "R",
    width_in: parseInt(w100, 10) / 100,
    length_in: parseInt(l100, 10) / 100,
    print_area_in: geom.print_area_in,
    color,
    min_od_in: geom.min_od_in,
    max_od_in: geom.max_od_in,
    wire_range: geom.wire_range,
  };
}

export function formatInMm(inches: number): string {
  return `${inches.toFixed(2)}″ (${(inches * 25.4).toFixed(1)} mm)`;
}

// ─────────────────────────────────────────────────────────────────────
// Bitmap presets for SKUs we ship in default_templates.txt.
//
// These are the printer-layer parameters (raster dimensions and the
// text rectangles inside it) — the values that govern *where ink
// actually lands on the ribbon*. They're SKU-specific because the
// printer doesn't know what shape of label is on the roll; you tell
// it by configuring the raster.
//
// Typography (font / point size / alignment) is **not** part of the
// preset — the same SKU is used at 4pt, 6pt, 7pt etc., so the operator
// keeps choosing those.
// ─────────────────────────────────────────────────────────────────────

export interface TemplatePreset {
  bytes_per_row: number;
  height: number;
  left_top: number; left_bottom: number;
  left_left: number; left_right: number;
  right_top: number; right_bottom: number;
  right_left: number; right_right: number;
  gap_top: number; gap_bottom: number;
  gap_left: number; gap_right: number;
}

/** 4.25″×2.125″ Turn-Tell row @ 300 DPI (EasyMark ``Thermal`` page). */
const TURN_TELL_300_PAGE = { bytes_per_row: 160, height: 638 } as const;

/** EasyMark white print-on strip (margin 0.563″ + 0.5″ @ 300 DPI).
 * Server maps Y to printer feed in ``label_geometry.text_rect``. */
const TURN_TELL_EASYMARK_Y = { top: 169, bottom: 319 } as const;

/** Build left/right text rects from EasyMark page margins (inches). */
function turnTellRects300(opts: {
  marginLeftIn: number;
  labelWidthIn: number;
  gapIn?: number;
  offsetXIn?: number;
}): Pick<
  TemplatePreset,
  | "left_left" | "left_right" | "right_left" | "right_right"
> {
  const dpi = 300;
  const inch = (v: number) => Math.round(v * dpi);
  const gap = inch(opts.gapIn ?? 0.125);
  const offsetX = inch(opts.offsetXIn ?? -0.05);
  const left = inch(opts.marginLeftIn);
  const w = inch(opts.labelWidthIn);
  const leftRight = left + w;
  const rightLeft = leftRight + gap + offsetX;
  return {
    left_left: left,
    left_right: leftRight,
    right_left: rightLeft,
    right_right: rightLeft + w,
  };
}

// Keyed by canonical SKU. Colour code is ignored for lookup — geometry
// is identical across V1/V2/V3/V7/V8 of the same width×length.
const TEMPLATE_PRESETS: Record<string, TemplatePreset> = {
  // Legacy Android export (203 DPI page geometry)
  "R200X225": {
    bytes_per_row: 156, height: 862,
    left_top: 480, left_bottom: 670, left_left: 20, left_right: 600,
    right_top: 480, right_bottom: 670, right_left: 648, right_right: 1228,
    gap_top: 20, gap_bottom: 20, gap_left: 20, gap_right: 20,
  },
  // R200X150V1T / R200X150V1T_Legs — EasyMark Turn-Tell 2.0″×0.5″ print,
  // 2×1 on 4.25″×2.125″ page; margins top 0.563″ left 0.125″, OffsetX −0.05″.
  "R200X150": {
    ...TURN_TELL_300_PAGE,
    ...turnTellRects300({
      marginLeftIn: 0.125,
      labelWidthIn: 2.0,
      offsetXIn: -0.05,
    }),
    left_top: TURN_TELL_EASYMARK_Y.top,
    left_bottom: TURN_TELL_EASYMARK_Y.bottom,
    right_top: TURN_TELL_EASYMARK_Y.top,
    right_bottom: TURN_TELL_EASYMARK_Y.bottom,
    gap_top: 0,
    gap_bottom: 0,
    gap_left: 0,
    gap_right: 0,
  },
  // R150X150V1T — same page/row as R200X150; label width 1.5″, left 0.625″.
  "R150X150": {
    ...TURN_TELL_300_PAGE,
    ...turnTellRects300({
      marginLeftIn: 0.625,
      labelWidthIn: 1.5,
      offsetXIn: -0.051,
    }),
    left_top: TURN_TELL_EASYMARK_Y.top,
    left_bottom: TURN_TELL_EASYMARK_Y.bottom,
    right_top: TURN_TELL_EASYMARK_Y.top,
    right_bottom: TURN_TELL_EASYMARK_Y.bottom,
    gap_top: 0,
    gap_bottom: 0,
    gap_left: 0,
    gap_right: 0,
  },
  // From default_templates.txt: S200x400 (S-series, no PANDUIT R parser
  // hit, but the operator may still use it for a self-laminating tag).
  "S200X400": {
    bytes_per_row: 156, height: 1238,
    left_top: 550, left_bottom: 850, left_left: 0, left_right: 624,
    right_top: 600, right_bottom: 800, right_left: 624, right_right: 1200,
    gap_top: 10, gap_bottom: 10, gap_left: 0, gap_right: 10,
  },
};

/** Find a bitmap-layout preset for a template name like
 * ``R200X225V1T``, ``R200X150V1T`` or ``S200x400``.
 * Returns ``null`` if we don't have one — caller should leave the
 * form alone (no half-applied geometry). */
export function findTemplatePreset(name: string): TemplatePreset | null {
  const m = name.match(/^([RS])(\d{3})[xX](\d{3})/i);
  if (!m) return null;
  const key = `${m[1]!.toUpperCase()}${m[2]}X${m[3]}`;
  return TEMPLATE_PRESETS[key] ?? null;
}

/** SKU keys we have presets for — handy for UI listings. */
export const TEMPLATE_PRESET_SKUS = Object.keys(TEMPLATE_PRESETS);
