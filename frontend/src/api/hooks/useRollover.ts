import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "@/api/client";

/** Administration › Rollover (backend/app/routers/admin_rollover.py) */

export type RolloverStatus = "needs_source" | "in_review" | "approved" | "skipped";
export type MatchSource = "manual" | "file" | "remembered" | "rule" | "only_one";

export interface RolloverSettings {
  primary_code_pattern: string | null;
  course_column: string;
  part_of_term_column: string;
  /** Part-of-term value → length, e.g. FULL → SEM */
  lengths: Record<string, string>;
  /** Read only: Administration › Terms */
  section_code_pattern?: string | null;
}

export interface PrimaryShell {
  id: string;
  code: string;
  name: string | null;
  course: string;
  mode: string | null;
  length: string | null;
  lms_org_unit_id: string | null;
  origin: "import" | "file" | "manual";
  has_list: boolean;
}

export interface RolloverItem {
  id: string;
  section: string | null;
  lms_code: string | null;
  course: string;
  course_name: string;
  department: string | null;
  instructors: string[];
  part_of_term: string | null;
  length: string | null;
  mode: string | null;
  primary: PrimaryShell | null;
  match_source: MatchSource | null;
  file_primary_code: string | null;
  status: RolloverStatus;
  problems: string[];
  notes: string | null;
  decided_at: string | null;
}

export interface RolloverItems {
  term: { id: string; code: string; name: string };
  items: RolloverItem[];
  total: number;
  counts: Record<RolloverStatus, number>;
  problems: number;
}

export interface ItemFilters {
  status?: RolloverStatus;
  has_problems?: boolean;
  q?: string;
}

export interface Skipped {
  line: number;
  code: string;
  reason: string;
}

export interface SectionsImport {
  added: number;
  updated: number;
  skipped: Skipped[];
  matched: Partial<Record<MatchSource, number>>;
  needs_source: number;
}

export interface PrimariesImport {
  added: number;
  updated: number;
  skipped: Skipped[];
}

export interface Remembered {
  id: string;
  course: string;
  length: string;
  mode: string;
  primary: string;
  created_at: string | null;
}

const ROOT = ["admin", "rollover"];

function useInvalidateRollover() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: ROOT });
}

export function useRolloverSettings() {
  return useQuery({
    queryKey: [...ROOT, "settings"],
    queryFn: async () => (await apiClient.get<RolloverSettings>("/admin/rollover/settings")).data,
  });
}

export function useSaveRolloverSettings() {
  const invalidate = useInvalidateRollover();
  return useMutation({
    mutationFn: async (input: RolloverSettings) =>
      (await apiClient.put<RolloverSettings>("/admin/rollover/settings", input)).data,
    onSuccess: invalidate,
  });
}

export function useTryPrimaryPattern() {
  return useMutation({
    mutationFn: async (input: { primary_code_pattern: string; code: string }) =>
      (
        await apiClient.post<{ matches: boolean; error: string | null; course: string | null; mode: string | null; length: string | null }>(
          "/admin/rollover/settings/try",
          input,
        )
      ).data,
  });
}

export function useRolloverItems(termId: string | undefined, filters: ItemFilters) {
  return useQuery({
    queryKey: [...ROOT, "items", termId, filters],
    enabled: Boolean(termId),
    placeholderData: keepPreviousData,
    queryFn: async () =>
      (await apiClient.get<RolloverItems>(`/admin/rollover/terms/${termId}/items`, { params: filters })).data,
  });
}

export function usePrimaries(q: string, enabled = true) {
  return useQuery({
    queryKey: [...ROOT, "primaries", q],
    enabled,
    queryFn: async () => (await apiClient.get<PrimaryShell[]>("/admin/rollover/primaries", { params: { q } })).data,
  });
}

export function useImportSections(termId: string | undefined) {
  const invalidate = useInvalidateRollover();
  return useMutation({
    mutationFn: async (text: string) =>
      (await apiClient.post<SectionsImport>(`/admin/rollover/terms/${termId}/import`, { text })).data,
    onSuccess: invalidate,
  });
}

export function useImportPrimaries() {
  const invalidate = useInvalidateRollover();
  return useMutation({
    mutationFn: async (text: string) =>
      (await apiClient.post<PrimariesImport>("/admin/rollover/primaries/import", { text })).data,
    onSuccess: invalidate,
  });
}

export function useRematch(termId: string | undefined) {
  const invalidate = useInvalidateRollover();
  return useMutation({
    mutationFn: async () => {
      await apiClient.post(`/admin/rollover/terms/${termId}/rematch`);
    },
    onSuccess: invalidate,
  });
}

export interface ItemChange {
  id: string;
  /** With set_primary: the chosen primary, or null to let the rules decide again */
  set_primary?: boolean;
  primary_id?: string | null;
  remember?: boolean;
  status?: RolloverStatus;
  notes?: string | null;
}

export function useUpdateItem() {
  const invalidate = useInvalidateRollover();
  return useMutation({
    mutationFn: async ({ id, ...change }: ItemChange) =>
      (await apiClient.patch<RolloverItem>(`/admin/rollover/items/${id}`, change)).data,
    onSuccess: invalidate,
  });
}

export function useBulkStatus() {
  const invalidate = useInvalidateRollover();
  return useMutation({
    mutationFn: async (input: { ids: string[]; status: RolloverStatus }) =>
      (await apiClient.post<{ changed: number; refused: number }>("/admin/rollover/items/bulk", input)).data,
    onSuccess: invalidate,
  });
}

export function useRemembered(enabled = true) {
  return useQuery({
    queryKey: [...ROOT, "remembered"],
    enabled,
    queryFn: async () => (await apiClient.get<Remembered[]>("/admin/rollover/remembered")).data,
  });
}

export function useForget() {
  const invalidate = useInvalidateRollover();
  return useMutation({
    mutationFn: async (id: string) => {
      await apiClient.delete(`/admin/rollover/remembered/${id}`);
    },
    onSuccess: invalidate,
  });
}
