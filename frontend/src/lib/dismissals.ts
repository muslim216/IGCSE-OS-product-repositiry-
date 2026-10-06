import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  dismissPrompt,
  listDismissals,
  restoreAllPrompts,
  type DismissalsOut,
} from "../api/dismissals";
import { friendlyError } from "./errors";

export const DISMISSALS_KEY = ["dismissals"] as const;

/** Said after something is hidden, and read out by the page's live region. It
 *  names what was hidden so a second hide is a text change and is read again. */
export const hiddenNotice = (what: string) =>
  `Hidden: ${what}. You can bring it back from the bottom of this page.`;

export const RESTORED_NOTICE = "Everything you hid is back.";

export type Dismissals = {
  isHidden: (key: string) => boolean;
  /** `what` names the thing for the announcement. */
  hide: (key: string, what: string) => void;
  restoreAll: () => void;
  /** Keys that are hiding something the page would otherwise show right now. */
  hiddenCount: number;
  /** A section says which of its stored keys are hiding one of its items. A
   *  stale key (a lesson that has passed) is never reported, so is never counted. */
  report: (section: string, keys: string[]) => void;
  /** The list has loaded or failed to: decisions that depend on it can be made. */
  settled: boolean;
  /** Polite announcement for the live region; empty until something is hidden. */
  notice: string;
  /** Set when a hide or restore failed and was rolled back. */
  error: string | null;
};

/** Reports a section's hidden keys for the footer's count, and withdraws them
 *  when the section goes. A no-op without `dismissals`. */
export function useReportHidden(
  dismissals: Dismissals | undefined,
  section: string,
  keys: string[],
) {
  const joined = keys.join("|");
  const report = dismissals?.report;
  useEffect(() => {
    if (!report) return;
    report(section, joined ? joined.split("|") : []);
    return () => report(section, []);
  }, [report, section, joined]);
}

/**
 * What the tutor has hidden with "Not now" (owner decision 2026-10-06).
 *
 * Never blocks and never hides by guesswork: while the list loads, and if it
 * fails to load, nothing is hidden, so every prompt shows exactly as it did
 * before this existed. A hide is applied at once when there is a list to apply
 * it to, and put back if the server refuses, with the failure said in words
 * (`friendlyError`). With no list (still loading, or failed) the request is just
 * sent: inventing one would un-hide everything else until the next read.
 *
 * One instance per page. The live region and error line live with whoever calls
 * this, so a section that disappears because its last item was hidden cannot
 * take its own announcement with it.
 */
export function useDismissals(): Dismissals {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: DISMISSALS_KEY,
    queryFn: async () => {
      const data = await listDismissals();
      // A body of the wrong shape is a failed read, not "nothing hidden".
      if (!data || !Array.isArray(data.keys)) throw new Error("Unexpected dismissals response");
      return data;
    },
  });
  const keys = useMemo(() => new Set(query.data?.keys ?? []), [query.data]);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [reported, setReported] = useState<Record<string, string>>({});

  const report = useCallback((section: string, sectionKeys: string[]) => {
    const joined = sectionKeys.join("|");
    setReported((prev) => {
      if ((prev[section] ?? "") === joined) return prev;
      return { ...prev, [section]: joined };
    });
  }, []);
  const hiddenCount = useMemo(
    () =>
      new Set(
        Object.values(reported)
          .filter(Boolean)
          .flatMap((j) => j.split("|")),
      ).size,
    [reported],
  );

  // Only ever edits a list that exists.
  const edit = useCallback(
    (change: (keys: string[]) => string[]) => {
      if (!queryClient.getQueryData<DismissalsOut>(DISMISSALS_KEY)) return;
      queryClient.setQueryData<DismissalsOut>(DISMISSALS_KEY, (old) => ({
        keys: change(old?.keys ?? []),
      }));
    },
    [queryClient],
  );

  const hideMutation = useMutation({
    mutationFn: ({ key }: { key: string; what: string }) => dismissPrompt(key),
    onMutate: async ({ key }) => {
      await queryClient.cancelQueries({ queryKey: DISMISSALS_KEY });
      edit((k) => (k.includes(key) ? k : [...k, key]));
    },
    // Only this key is taken back: another hide may be in flight beside it.
    onError: (err, { key }) => {
      edit((k) => k.filter((x) => x !== key));
      setNotice("");
      setError(friendlyError(err, "Couldn't hide that. Try again."));
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: DISMISSALS_KEY }),
  });

  const restoreMutation = useMutation({
    mutationFn: restoreAllPrompts,
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: DISMISSALS_KEY });
      const before = queryClient.getQueryData<DismissalsOut>(DISMISSALS_KEY);
      edit(() => []);
      return { before };
    },
    onError: (err, _v, context) => {
      if (context?.before) queryClient.setQueryData(DISMISSALS_KEY, context.before);
      setError(friendlyError(err, "Couldn't bring them back. Try again."));
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: DISMISSALS_KEY }),
  });

  return {
    isHidden: (key) => keys.has(key),
    hide: (key, what) => {
      setError(null);
      setNotice(hiddenNotice(what));
      hideMutation.mutate({ key, what });
    },
    restoreAll: () => {
      setError(null);
      setNotice(RESTORED_NOTICE);
      restoreMutation.mutate();
    },
    hiddenCount,
    report,
    settled: !query.isLoading,
    notice,
    error,
  };
}
