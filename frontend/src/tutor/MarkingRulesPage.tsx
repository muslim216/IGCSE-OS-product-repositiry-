import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { listSubjects } from "../api/groups";
import { getMarkingRules, saveMarkingRules, MAX_MARKING_RULES } from "../api/markingRules";
import { ApiError } from "../api/client";
import { EmptyState, useToast } from "../components/ui";
import { ABSENT } from "../lib/labels";

/**
 * The AI marking agreement — the marking rules a tutor writes once for a
 * subject (`AV-75`, `AV-111`).
 *
 * Two things this screen must never imply. It does not decide **when a mark
 * counts**: auto-finalization stays scheme-backed and confident whatever is
 * written here (`AV-25`). And nothing marks with these yet — the marking
 * context assembler is a later phase — so the copy says so rather than
 * promising an effect the product does not have (`PROD-1`).
 */
export default function MarkingRulesPage() {
  const queryClient = useQueryClient();
  const { toast, showToast } = useToast();
  const subjects = useQuery({ queryKey: ["subjects"], queryFn: listSubjects });
  const [subjectId, setSubjectId] = useState<number | null>(null);
  const selected = subjectId ?? subjects.data?.[0]?.id ?? null;

  const rules = useQuery({
    queryKey: ["marking-rules", selected],
    queryFn: () => getMarkingRules(selected!),
    enabled: selected !== null,
  });

  // The draft the tutor is typing, which is a different thing from what is
  // stored — the server's answer stays in TanStack Query (FE-6).
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (rules.data) setDraft(rules.data.rules);
  }, [rules.data]);

  const save = useMutation({
    mutationFn: () => saveMarkingRules(selected!, draft),
    onMutate: () => setError(null),
    onSuccess: (saved) => {
      queryClient.invalidateQueries({ queryKey: ["marking-rules", selected] });
      showToast(saved.configured ? "Marking rules saved." : "Marking rules cleared.");
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });

  if (subjects.isLoading) {
    return (
      <div aria-busy="true">
        <span aria-hidden className="block h-24 w-full animate-pulse rounded bg-surface-muted" />
      </div>
    );
  }
  // "Could not load" and "you have none" are different facts (PROD-2): a retry
  // and a next step.
  if (subjects.isError || !subjects.data) {
    return <p className="text-sm text-ink-500">{ABSENT.loadFailed}</p>;
  }
  if (subjects.data.length === 0) {
    return (
      <EmptyState
        title="No subjects yet."
        hint="Marking rules are written per subject — add a syllabus first."
      />
    );
  }

  const tooLong = draft.length > MAX_MARKING_RULES;
  const unchanged = rules.data ? draft === rules.data.rules : true;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="font-display text-xl font-semibold text-ink-900">AI marking agreement</h2>
        <p className="mt-1 max-w-prose text-sm text-ink-500">
          How you want work in this subject marked, in your own words — method marks, units,
          working, the things you would tell a new tutor. Written once and applying to every chapter
          and piece of work in the subject, alongside the exam board's own conventions rather than
          instead of them.
        </p>
        <p className="mt-2 max-w-prose text-sm text-ink-500">
          These rules describe <strong>how</strong> work is marked, never <strong>when</strong> a
          mark counts — that stays as it is, and nothing you write here changes it. Marking does not
          read them yet; they are stored ready for when it does.
        </p>
      </div>

      <select
        aria-label="Subject"
        disabled={save.isPending}
        value={selected ?? ""}
        onChange={(e) => {
          // The draft belongs to the subject it was typed for; carrying it
          // across would save one subject's rules onto another.
          setError(null);
          setSubjectId(Number(e.target.value));
        }}
        className="rounded-md border border-line-control bg-surface px-3 py-2 text-sm"
      >
        {subjects.data.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name} ({s.exam_board} {s.code})
          </option>
        ))}
      </select>

      {/* The draft is only safe to save once the loaded rules are the selected
          subject's: between a switch and its response, `draft` still holds the
          previous subject's text, and saving then writes it to the new one. */}
      {rules.isLoading || (rules.data && rules.data.subject_id !== selected) ? (
        <span aria-hidden className="block h-40 w-full animate-pulse rounded bg-surface-muted" />
      ) : rules.isError || !rules.data ? (
        <p className="text-sm text-ink-500">{ABSENT.loadFailed}</p>
      ) : (
        <section className="space-y-3">
          <label htmlFor="marking-rules" className="block text-sm font-medium text-ink-700">
            Marking rules for {rules.data.subject_name}
          </label>
          <textarea
            id="marking-rules"
            rows={12}
            disabled={save.isPending}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="e.g. Award method marks even when the final answer is wrong. A missing unit costs one mark, once per question."
            className="w-full max-w-prose rounded-md border border-line-control bg-surface px-3 py-2 text-sm"
          />
          <div className="flex flex-wrap items-center gap-3">
            <button
              onClick={() => save.mutate()}
              disabled={save.isPending || tooLong || unchanged}
              className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-canvas hover:bg-brand-700 disabled:opacity-50"
            >
              {save.isPending ? "Saving…" : "Save"}
            </button>
            <p className={`text-xs ${tooLong ? "text-red-600" : "text-ink-500"}`}>
              {draft.length.toLocaleString()} / {MAX_MARKING_RULES.toLocaleString()} characters
            </p>
            {!rules.data.configured && !save.isPending && (
              // Skippable by design (AV-87) — say so, rather than leaving a
              // blank box that reads as unfinished setup.
              <p className="text-xs text-ink-500">
                Nothing set for this subject. Leaving it empty is fine.
              </p>
            )}
          </div>
          {tooLong && (
            <p className="text-sm text-red-600">
              That is longer than {MAX_MARKING_RULES.toLocaleString()} characters — trim it to the
              rules that change how work is marked.
            </p>
          )}
          {error && <p className="text-sm text-red-600">{error}</p>}
        </section>
      )}
      {toast}
    </div>
  );
}
