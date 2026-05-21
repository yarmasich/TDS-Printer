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
 * Accepts loose variants like ``R200X225+mirror`` or ``R100x150V2T``;
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
