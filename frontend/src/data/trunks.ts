import type { DataHall, Discipline, SearchHit } from '@/api/types';

/** Which labels an add or print means: the leg, its trunk too, or only the trunk. */
export type TrunkMode = 'none' | 'with' | 'only';

/** A leg links to its trunk only through the workbook's Trunk# column, and
 * only when its discipline names the discipline holding the trunk labels. */
export function offersTrunk(
  hit: Pick<SearchHit, 'trunk_no'>,
  discipline: Pick<Discipline, 'trunk_discipline_id'> | null | undefined,
): boolean {
  return !!hit.trunk_no && !!discipline?.trunk_discipline_id;
}

export function trunkCaption(hit: Pick<SearchHit, 'trunk_no' | 'leg_no'>): string {
  if (!hit.trunk_no) return '';
  return hit.leg_no ? `Trunk ${hit.trunk_no} · Leg ${hit.leg_no}` : `Trunk ${hit.trunk_no}`;
}

/** Disciplines that may hold `d`'s trunk labels. Mirrors the server rule:
 * another discipline of the same project, and trunks one level deep. */
export function trunkTargets(
  d: Pick<Discipline, 'id' | 'data_hall_id'>,
  all: Pick<Discipline, 'id' | 'data_hall_id' | 'trunk_discipline_id' | 'name'>[],
  halls: Pick<DataHall, 'id' | 'project_id'>[],
) {
  const project = (x: Pick<Discipline, 'data_hall_id'>) => halls.find((h) => h.id === x.data_hall_id)?.project_id;
  if (all.some((o) => o.trunk_discipline_id === d.id)) return [];
  return all.filter((o) => o.id !== d.id && project(o) === project(d) && o.trunk_discipline_id == null);
}

/** The discipline choices an operator sees: a trunk discipline linked to a
 * leg discipline is reached through the legs (its search covers the trunks),
 * so listing it too would double the list. `keepId` stays listed so a
 * remembered choice does not silently vanish. */
export function operatorDisciplines<T extends Pick<Discipline, 'id' | 'trunk_discipline_id'>>(
  all: T[], keepId?: number | null,
): T[] {
  const linked = new Set(all.map((d) => d.trunk_discipline_id).filter((id) => id != null));
  return all.filter((d) => !linked.has(d.id) || d.id === keepId);
}

/** Admin's view of a hall: each trunk discipline framed with the leg
 * disciplines that link it, trunks last, placed where the first leg stands.
 * A leg whose trunks live in another hall, and anything unlinked, stays a
 * plain row (`trunk: null`). */
export function trunkGroups<T extends Pick<Discipline, 'id' | 'trunk_discipline_id'>>(
  list: T[],
): { rows: T[]; trunk: T | null }[] {
  const byId = new Map(list.map((d) => [d.id, d]));
  const grouped = new Map<number, { rows: T[]; trunk: T | null }>();
  const out: { rows: T[]; trunk: T | null }[] = [];
  for (const d of list) {
    const trunk = d.trunk_discipline_id != null ? byId.get(d.trunk_discipline_id) : undefined;
    if (trunk) {
      const group = grouped.get(trunk.id);
      if (group) group.rows.push(d);
      else {
        const created = { rows: [d], trunk };
        grouped.set(trunk.id, created);
        out.push(created);
      }
    } else if (!list.some((o) => o.trunk_discipline_id === d.id)) {
      out.push({ rows: [d], trunk: null });
    }
  }
  return out;
}
