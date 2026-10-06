import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import type { Subject } from "../api/groups";

export interface SubjectGroup<T> {
  /** The subject's id, as a string so it can sit in a URL and a select value. */
  id: string;
  /** Null when the subject list has no row for this id (not loaded, or not visible). */
  subject: Subject | null;
  items: T[];
}

/** Items grouped by subject, subjects alphabetical, items in the order given.
 *
 * A subject whose name is not known sorts last rather than being given a
 * made-up one (`PROD-2`). */
export function groupBySubject<T extends { subject_id: number }>(
  items: readonly T[] | undefined,
  subjects: readonly Subject[] | undefined,
): SubjectGroup<T>[] {
  const byId = new Map(subjects?.map((s) => [s.id, s]));
  const groups = new Map<number, SubjectGroup<T>>();
  for (const item of items ?? []) {
    let g = groups.get(item.subject_id);
    if (!g) {
      g = { id: String(item.subject_id), subject: byId.get(item.subject_id) ?? null, items: [] };
      groups.set(item.subject_id, g);
    }
    g.items.push(item);
  }
  return [...groups.values()].sort((a, b) => {
    if (!a.subject || !b.subject) return Number(!a.subject) - Number(!b.subject);
    return a.subject.name.localeCompare(b.subject.name) || a.subject.id - b.subject.id;
  });
}

/** Grouping plus the `?subject=<id>` filter.
 *
 * The choice lives in the URL so it survives a reload and back/forward. An id
 * that matches no group (stale link, subject since emptied) is treated as "All
 * subjects" rather than showing an empty page. */
export function useSubjectFilter<T extends { subject_id: number }>(
  items: readonly T[] | undefined,
  subjects: readonly Subject[] | undefined,
) {
  const [params, setParams] = useSearchParams();
  const groups = useMemo(() => groupBySubject(items, subjects), [items, subjects]);
  const raw = params.get("subject") ?? "";
  const picked = groups.some((g) => g.id === raw) ? raw : "";
  const visible = useMemo(
    () => (picked ? groups.filter((g) => g.id === picked) : groups),
    [groups, picked],
  );

  function setPicked(id: string) {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      if (id) next.set("subject", id);
      else next.delete("subject");
      return next;
    });
  }

  return { groups, visible, picked, setPicked, showPicker: groups.length > 1 };
}
