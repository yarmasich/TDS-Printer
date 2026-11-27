# Leg and trunk disciplines grouped in Projects

## Intent
In Admin → Projects a hall lists its disciplines flat, in database order. A leg
discipline and the trunk discipline it links (`trunk_discipline_id`) sit apart
unless they happened to be created one after the other, and the pairing shows
only through the Legs / Trunks badges and "· for X". The user wants each pair
seen as one unit.

## Approaches
- **Framed group, trunks under legs (chosen).** Leg rows, then their trunk row
  indented, inside one frame. No extra clicks; the order follows the link, not
  the names.
- Collapsible group: an extra click to reach the trunk row's template/bundle.
- Sort by name: breaks on names that differ (`16K-NS-LS` / `16K-NS-LS_trunk`).

## Design
- A group is one trunk discipline plus every leg discipline linking it; legs
  first (in their current order), trunk last, indented with a "└" marker.
- Groups and unlinked disciplines keep the hall's existing order, placed where
  the group's first leg stands.
- Row contents are unchanged (color, rename, bundle, trunk picker, template,
  delete). The "· for X" caption goes: the frame says it.
- Linking or unlinking regroups at once (computed from the loaded list).
- Frontend only; the grouping is a pure function in `src/data/trunks.ts` with
  node tests.

## Non-goals
No collapse, no server change, no change to operator-side discipline lists.
