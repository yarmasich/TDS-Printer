/**
 * Hand-written DTOs mirroring the Pydantic models in the backend.
 *
 * These are a stop-gap until ``npm run gen:api`` is run against a live
 * server — at that point `schema.d.ts` will be fully populated and we can
 * switch consumers to `components["schemas"]["X"]`. Keeping these as a
 * thin layer lets every page/store compile from a fresh clone.
 */

export interface Printer {
  id: number;
  name: string;
  ip: string;
  port: number;
  notes: string;
}

export interface PingResult {
  printer_id: number;
  ok: boolean;
  ms: number | null;
  error: string;
}

export type HAlign = "LEFT" | "CENTER" | "RIGHT";
export type VAlign = "TOP" | "CENTER" | "BOTTOM";

export interface Template {
  id: number;
  name: string;
  printer_id: number;
  bytes_per_row: number;
  height: number;
  left_top: number;
  left_bottom: number;
  left_left: number;
  left_right: number;
  right_top: number;
  right_bottom: number;
  right_left: number;
  right_right: number;
  gap_top: number;
  gap_bottom: number;
  gap_left: number;
  gap_right: number;
  left_text: string;
  right_text: string;
  left_pt: number;
  right_pt: number;
  h_align: HAlign;
  v_align: VAlign;
  font_name: string;
  font_style: string;
  left_offset: number;
  right_offset: number;
  mirror_mode: boolean;
}

export interface Project {
  id: number;
  name: string;
}

export interface DataHall {
  id: number;
  project_id: number;
  name: string;
}

export interface Discipline {
  id: number;
  data_hall_id: number;
  name: string;
  template_id: number | null;
  template_name: string | null;
  printer_id: number | null;
  printer_name: string | null;
  color: string;
  label_count: number;
}

export interface SearchHit {
  label_id: number;
  discipline_id: number;
  discipline_name: string;
  project_name: string;
  data_hall_name: string;
  sheet_name: string;
  row_idx: number;
  left_text: string;
  right_text: string;
  matched_left: boolean;
  matched_right: boolean;
}

export interface SearchResponse {
  query: string;
  expanded: string[];
  hits: SearchHit[];
  total: number;
}

export interface CartItem {
  id: number;
  label_id: number | null;
  discipline_name: string;
  project_name: string;
  data_hall_name: string;
  left_text: string;
  right_text: string;
  template_name: string | null;
  added_at: string;
}

export interface PrintAllResult {
  ok: number;
  errors: { item_id: number; error: string }[];
  log_ids: number[];
}

export interface Reason {
  id: number;
  text: string;
  sort_order: number;
}

export interface AuthName {
  id: number;
  name: string;
}

export interface ImportDTO {
  id: number;
  discipline_id: number;
  discipline_name: string;
  data_hall_name: string;
  project_name: string;
  filename: string;
  uploaded_at: string;
  sheets: number;
  rows: number;
  skipped: number;
}

export interface PrintLog {
  id: number;
  ts: string;
  template_name: string;
  printer_ip: string;
  operator: string;
  reason: string;
  left_text: string;
  right_text: string;
  status: string;
  error: string;
}
