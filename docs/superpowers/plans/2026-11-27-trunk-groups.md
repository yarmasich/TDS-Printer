# Leg/Trunk Groups in Projects Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admin → Projects shows each trunk discipline framed together with the leg disciplines that link it.

**Architecture:** A pure grouping function in `frontend/src/data/trunks.ts` turns a hall's discipline list into display groups; `ProjectsTree.vue` loops over groups instead of disciplines and frames those that have a trunk.

**Tech Stack:** Vue 3 + TypeScript, Tailwind, node:test (`npm test` in `frontend/`).

**Spec:** `docs/superpowers/specs/2026-11-27-trunk-groups-design.md`

## Global Constraints
- Frontend only; row contents (color, rename, bundle, trunk picker, template, delete) unchanged.
- Groups keep the hall's existing order, placed where the group's first leg stands.

## Review Focus
- A leg linking a trunk discipline in another hall of the project: the leg shows alone, the trunk keeps its "· for X" caption in its own hall.
- Two leg disciplines sharing one trunk discipline: both legs in one frame, trunk once, last.
- A trunk discipline listed before its legs: it moves into the group, it is not shown twice.
- Unlinking: the pair splits back into two plain rows (computed, no reload).
- Hall discipline count stays the number of disciplines, not groups.

---

### Task 1: `trunkGroups` and the grouped list

**Files:**
- Modify: `frontend/src/data/trunks.ts`
- Modify: `frontend/src/components/admin/ProjectsTree.vue` (discipline loop, ~line 514)
- Test: `frontend/tests/trunks.test.mjs`

**Interfaces:**
- Produces: `trunkGroups<T extends Pick<Discipline, 'id' | 'trunk_discipline_id'>>(list: T[]): { rows: T[]; trunk: T | null }[]`
  — `rows` are leg disciplines (or one unlinked discipline); `trunk` is set only for a group.

- [ ] **Step 1: Failing tests** in `trunks.test.mjs`:
  - `[A(legs→T), X, T]` → `[{rows:[A],trunk:T},{rows:[X],trunk:null}]`
  - `[T, A(→T), B(→T)]` → `[{rows:[A,B],trunk:T}]`
  - leg whose trunk is not in the list → `[{rows:[A],trunk:null}]`
  - every input discipline appears exactly once across the output.
- [ ] **Step 2:** `npm test` → FAIL (`trunkGroups` not exported).
- [ ] **Step 3:** Implement `trunkGroups`; in `ProjectsTree.vue` loop `g in trunkGroups(discByHall.get(h.id) ?? [])`, wrap a group in one frame, render `g.trunk` after `g.rows` indented with a `└` marker, show "· for X" only for a trunk outside a group.
- [ ] **Step 4:** `npm test`, `npx vue-tsc --noEmit`, `npm run build` → all pass; screenshot the Projects page.
- [ ] **Step 5:** Commit only if the user asks.
