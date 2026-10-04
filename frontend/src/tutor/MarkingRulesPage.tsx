import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { listSubjects } from "../api/groups";
import { getMarkingRules, saveMarkingRules, MAX_MARKING_RULES } from "../api/markingRules";
import { Button, Field, Select, Textarea } from "../components/controls";
import { ErrorState, PageHeader, SectionSkeleton } from "../components/page";
import { EmptyState, SectionCard, useToast } from "../components/ui";
import { friendlyError } from "../lib/errors";

/**
 * The AI marking agreement — the marking rules a tutor writes once for a
 * subject (`AV-75`, `AV-111`).
 *
 * Two things this screen must never imply. It does not decide **when a mark
 * counts**: auto-finalization stays scheme-backed and confident whatever is
 * written here (`AV-25`). Marking *does* read them since task 3.2 — through
 * the context assembler, in the condensed form shown below — so the copy no
 * longer says otherwise (`PROD-1` cuts both ways: a page that understates its
 * effect is as wrong as one that overstates it).
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
    // The summary is written by a background job, so the save response never
    // carries it. Without this the panel sits on "not shortened yet" until the
    // page is remounted, which reads as a failure rather than as a wait
    // (cubic). Polling stops the moment there is a summary, or when there are
    // no rules to summarise.
    refetchInterval: (query) => {
      const data = query.state.data;
      return data?.configured && !data.summary ? 3000 : false;
    },
  });

  // The draft the tutor is typing, which is a different thing from what is
  // stored — the server's answer stays in TanStack Query (FE-6).
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  // Seeded once per subject, not on every query update. A refetch — a window
  // regaining focus is enough — would otherwise copy the stored text over
  // whatever the tutor has typed and not yet saved (CodeRabbit).
  const hydratedFor = useRef<number | null>(null);
  useEffect(() => {
    if (rules.data && hydratedFor.current !== rules.data.subject_id) {
      hydratedFor.current = rules.data.subject_id;
      setDraft(rules.data.rules);
    }
  }, [rules.data]);

  const save = useMutation({
    mutationFn: () => saveMarkingRules(selected!, draft),
    onMutate: () => setError(null),
    onSuccess: (saved) => {
      // The server normalizes — whitespace-only rules come back cleared — and a
      // save is an explicit action, so the box adopts what was actually stored.
      // The per-subject hydration guard deliberately ignores query updates, so
      // without this the editor would keep showing the whitespace it just
      // discarded, with Save still enabled (cubic).
      setDraft(saved.rules);
      queryClient.invalidateQueries({ queryKey: ["marking-rules", selected] });
      showToast(saved.configured ? "Marking rules saved." : "Marking rules cleared.");
    },
    onError: (err) => setError(friendlyError(err, "Your rules didn't save. Try again.")),
  });

  const header = (
    <PageHeader
      title="AI marking agreement"
      description="How you want work in a subject marked, in your own words — method marks, units, working, the things you would tell a new tutor. Written once, it applies to every chapter and piece of work in the subject, alongside the exam board's own conventions rather than instead of them."
      back={{ to: "/tutor/settings", label: "Settings" }}
    />
  );

  // A load failure always comes with a way out of it: telling someone something
  // broke and leaving them to reload the whole page is a dead end for what is
  // usually a transient error (cubic). ErrorState carries the retry.
  if (subjects.isLoading) {
    return (
      <div>
        {header}
        <SectionSkeleton rows={4} label="Loading your subjects" />
      </div>
    );
  }
  // "Could not load" and "you have none" are different facts (PROD-2): a retry
  // and a next step.
  if (subjects.isError || !subjects.data) {
    return (
      <div>
        {header}
        <ErrorState error={subjects.error} onRetry={() => subjects.refetch()} />
      </div>
    );
  }
  if (subjects.data.length === 0) {
    return (
      <div>
        {header}
        <SectionCard>
          <EmptyState
            title="No subjects yet."
            hint="Marking rules are written per subject — add a syllabus first."
          />
        </SectionCard>
      </div>
    );
  }

  const tooLong = draft.length > MAX_MARKING_RULES;
  const unchanged = rules.data ? draft === rules.data.rules : true;

  return (
    <div className="max-w-3xl">
      {header}

      <div className="space-y-6">
        <p className="rounded-lg bg-surface-muted p-4 text-sm leading-relaxed text-ink-700">
          These rules describe <strong>how</strong> work is marked, never <strong>when</strong> a
          mark counts — that stays as it is, and nothing you write here changes it. Marking reads
          them on every piece of work in this subject, in the shortened form below.
        </p>

        <Field label="Subject" className="max-w-sm">
          <Select
            disabled={save.isPending}
            value={selected ?? ""}
            onChange={(e) => {
              // The draft belongs to the subject it was typed for; carrying it
              // across would save one subject's rules onto another.
              setError(null);
              setSubjectId(Number(e.target.value));
            }}
          >
            {subjects.data.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.exam_board} {s.code})
              </option>
            ))}
          </Select>
        </Field>

        {/* The editor appears only once the loaded rules are the selected
            subject's. The query key carries the subject, so a switch already
            moves to a loading state with no data — this second condition is
            defence in depth for the day someone adds `placeholderData:
            keepPreviousData` and the previous subject's text starts showing
            under the new subject's id. */}
        {rules.isLoading || (rules.data && rules.data.subject_id !== selected) ? (
          <SectionCard>
            <SectionSkeleton rows={6} label="Loading the marking rules" />
          </SectionCard>
        ) : rules.isError || !rules.data ? (
          <ErrorState error={rules.error} onRetry={() => rules.refetch()} />
        ) : (
          <SectionCard className="space-y-4">
            <Field
              label={`Marking rules for ${rules.data.subject_name}`}
              error={
                tooLong
                  ? `That is longer than ${MAX_MARKING_RULES.toLocaleString()} characters — trim it to the rules that change how work is marked.`
                  : null
              }
            >
              <Textarea
                rows={12}
                disabled={save.isPending}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="e.g. Award method marks even when the final answer is wrong. A missing unit costs one mark, once per question."
                className="leading-relaxed"
              />
            </Field>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
              <Button
                onClick={() => save.mutate()}
                disabled={tooLong || unchanged}
                loading={save.isPending}
              >
                Save
              </Button>
              <p className={`text-xs tabular-nums ${tooLong ? "text-risk-600" : "text-ink-500"}`}>
                {draft.length.toLocaleString()} of {MAX_MARKING_RULES.toLocaleString()} characters
              </p>
              {!rules.data.configured && !save.isPending && (
                // Skippable by design (AV-87) — say so, rather than leaving a
                // blank box that reads as unfinished setup.
                <p className="text-xs text-ink-500">
                  Nothing set for this subject. Leaving it empty is fine.
                </p>
              )}
            </div>
            {error && (
              <p role="alert" className="text-sm text-risk-600">
                {error}
              </p>
            )}
            {/* PROD-7: the tutor has final authority over everything the AI
                produces, and since 3.2c a model sits between them and their own
                instructions. Showing the condensed form is how they can tell a
                rule went missing — the alternative is finding out from a mark. */}
            {rules.data.configured && (
              <details className="rounded-lg border border-line bg-surface-muted p-3">
                <summary className="cursor-pointer text-sm font-medium text-ink-700">
                  What marking actually reads
                </summary>
                {rules.data.summary ? (
                  <>
                    <pre className="mt-2 max-w-prose whitespace-pre-wrap font-sans text-sm text-ink-700">
                      {rules.data.summary}
                    </pre>
                    <p className="mt-2 max-w-prose text-xs text-ink-500">
                      Your rules, shortened by AI so they fit in every marking request. Edit the box
                      above if anything is missing — this is rebuilt each time you save.
                    </p>
                  </>
                ) : (
                  // Absent is a real, correct state — not an error and not a
                  // spinner to wait on. Marking uses the full text meanwhile
                  // (PROD-2: say what is true rather than showing nothing).
                  <p className="mt-2 max-w-prose text-sm text-ink-500">
                    Not shortened yet — marking is using your full text above. This usually takes a
                    moment after saving.
                  </p>
                )}
              </details>
            )}
          </SectionCard>
        )}
      </div>
      {toast}
    </div>
  );
}
