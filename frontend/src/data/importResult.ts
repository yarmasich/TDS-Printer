/** Stats returned by `POST /api/import/upload`. Fields added after the first
 * release are optional so an older server still reads correctly. */
export interface ImportStats {
  rows: number;
  sheets: number;
  trunk_rows?: number;
  duplicate_legs?: number;
  replaced_imports?: number;
  labels_removed?: number;
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** Toast text for a finished upload: the counts in the summary, the
 * consequences an admin should act on in the detail. */
export function importResultToast(stats: ImportStats): { summary: string; detail?: string } {
  const parts = [`Imported ${stats.rows} rows · ${stats.sheets} sheets`];
  const detail: string[] = [];
  if (stats.replaced_imports) {
    parts.push(`Replaced ${plural(stats.replaced_imports, "earlier import", "earlier imports")}`);
  }
  if (stats.trunk_rows) {
    parts.push(`${stats.trunk_rows} trunk labels left out`);
    detail.push("Trunk labels in a leg workbook are not imported. They print from the trunk discipline.");
  }
  if (stats.duplicate_legs) {
    parts.push(plural(stats.duplicate_legs, "duplicate leg", "duplicate legs"));
    detail.push(
      `${plural(stats.duplicate_legs, "row repeats", "rows repeat")} a Trunk# and Leg # pair from earlier in the file. `
      + "Printing one of those legs by number finds more than one label.",
    );
  }
  return { summary: parts.join(" · "), detail: detail.length ? detail.join(" ") : undefined };
}

/** Explains what "Replace existing labels" will remove, for the checkbox hint. */
export function replaceHint(imports: { rows: number }[]): string {
  const rows = imports.reduce((sum, imp) => sum + imp.rows, 0);
  return `Removes ${plural(imports.length, "earlier import", "earlier imports")} `
    + `(${plural(rows, "row", "rows")}) of this discipline when the new file imports. Print history is kept.`;
}
