import { useCallback, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  dismissPrompt,
  listDismissals,
  restoreAllPrompts,
  type DismissalsOut,
} from "../api/dismissals";
import { friendlyError } from "./errors";

export const DISMISSALS_KEY = ["dismissals"] as const;

/** Said once after something is hidden, and read out by the page's live region. */
export const HIDDEN_NOTICE = "Hidden. You can bring it back from the bottom of this page.";

export const RESTORED_NOTICE = "Everything you hid is back.";

export type Dismissals = {
  isHidden: (key: string) => boolean;
  hide: (key: string) => void;
  restoreAll: () => void;
  hiddenCount: number;
  /** Polite announcement for the live region; empty until something is hidden. */
  notice: string;
  /** Set when a hide or restore failed and was rolled back. */
  error: string | null;
};

/**
 * What the tutor has hidden with "Not now" (owner decision 2026-10-06).
 *
 * Never blocks and never hides by guesswork: while the list loads, and if it
 * fails to load, nothing is hidden, so every prompt shows exactly as it did
 * before this existed. A hide is applied at once and put back if the server
 * refuses, with the failure said in words (`friendlyError`).
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

  const edit = useCallback(
    (change: (keys: string[]) => string[]) =>
      queryClient.setQueryData<DismissalsOut>(DISMISSALS_KEY, (old) => ({
        keys: change(old?.keys ?? []),
      })),
    [queryClient],
  );

  const hideMutation = useMutation({
    mutationFn: dismissPrompt,
    onMutate: async (key: string) => {
      await queryClient.cancelQueries({ queryKey: DISMISSALS_KEY });
      edit((k) => (k.includes(key) ? k : [...k, key]));
    },
    // Only this key is taken back: another hide may be in flight beside it.
    onError: (err, key) => {
      edit((k) => k.filter((x) => x !== key));
      setNotice("");
      setError(friendlyError(err, "Couldn't hide that. Try again."));
    },
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
    hide: (key) => {
      setError(null);
      setNotice(HIDDEN_NOTICE);
      hideMutation.mutate(key);
    },
    restoreAll: () => {
      setError(null);
      setNotice(RESTORED_NOTICE);
      restoreMutation.mutate();
    },
    hiddenCount: keys.size,
    notice,
    error,
  };
}
