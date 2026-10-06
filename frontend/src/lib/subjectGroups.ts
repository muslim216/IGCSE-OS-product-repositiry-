import { useMemo } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import type { Subject } from "../api/groups";

/** The one group every item with an unknown subject goes into. */
export const OTHER_SUBJECT = "other";

export interface SubjectGroup<T> {
  /** The subject's id as a string, so it can sit in a URL and a select value;
   *  `OTHER_SUBJECT` for the collapsed unknown group. */
  id: string;
  /** Null for the unknown group: the subject list has no row for these items. */
  subject: Subject | null;
  items: T[];
}

/** Items grouped by subject, subjects alphabetical, items in the order given.
 *
 * Items whose subject is not in the list collapse into a single trailing group
 * rather than being given a made-up name (`PROD-2`). */
export function groupBySubject<T extends { subject_id: number }>(
  items: readonly T[] | undefined,
  subjects: readonly Subject[] | undefined,
): SubjectGroup<T>[] {
  const byId = new Map(subjects?.map((s) => [s.id, s]));
  const known = new Map<number, SubjectGroup<T>>();
  const unknown: SubjectGroup<T> = { id: OTHER_SUBJECT, subject: null, items: [] };
  for (const item of items ?? []) {
    const subject = byId.get(item.subject_id);
    if (!subject) {
      unknown.items.push(item);
      continue;
    }
    let g = known.get(subject.id);
    if (!g) {
      g = { id: String(subject.id), subject, items: [] };
      known.set(subject.id, g);
    }
    g.items.push(item);
  }
  const sorted = [...known.values()].sort(
    (a, b) => a.subject!.name.localeCompare(b.subject!.name) || a.subject!.id - b.subject!.id,
  );
  return unknown.items.length > 0 ? [...sorted, unknown] : sorted;
}

/** Grouping plus the `?subject=<id>` filter.
 *
 * Pass `subjects` as undefined until the subject request has succeeded: with no
 * names, every item would read "Other subject", so `ready` stays false and the
 * page renders its plain list instead.
 *
 * The choice lives in the URL so it survives a reload and back/forward. An id
 * that matches no group (stale link, subject since emptied) is treated as "All
 * subjects" rather than showing an empty page. */
export function useSubjectFilter<T extends { subject_id: number }>(
  items: readonly T[] | undefined,
  subjects: readonly Subject[] | undefined,
) {
  const location = useLocation();
  const navigate = useNavigate();
  const ready = subjects !== undefined;
  const groups = useMemo(
    () => (ready ? groupBySubject(items, subjects) : []),
    [ready, items, subjects],
  );
  const raw = new URLSearchParams(location.search).get("subject") ?? "";
  const picked = groups.some((g) => g.id === raw) ? raw : "";
  const visible = useMemo(
    () => (picked ? groups.filter((g) => g.id === picked) : groups),
    [groups, picked],
  );

  function setPicked(id: string) {
    const next = new URLSearchParams(location.search);
    if (id) next.set("subject", id);
    else next.delete("subject");
    const search = next.toString();
    // Navigated by hand because `setSearchParams` drops the hash, and a link to
    // `#paper-<id>` must survive a change of filter. Replaced, not pushed: a
    // history entry per filter choice would make Back step through them.
    navigate(
      { pathname: location.pathname, search: search ? `?${search}` : "", hash: location.hash },
      { replace: true, state: location.state },
    );
  }

  return { ready, groups, visible, picked, setPicked, showPicker: ready && groups.length > 1 };
}
