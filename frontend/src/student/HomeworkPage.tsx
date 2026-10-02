import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { myAssignments } from "../api/homework";
import { myMistakes, type MyMistakePattern } from "../api/students";
import { useMyTimezone } from "../auth/AuthContext";
import { ErrorState, PageHeader, SectionSkeleton } from "../components/page";
import { EmptyState, SectionCard } from "../components/ui";
import { ABSENT } from "../lib/labels";
import { formatDayMonth } from "../lib/timezones";

const STATUS_BADGE: Record<string, { label: string; cls: string }> = {
  not_submitted: { label: "Not started", cls: "bg-surface-muted text-ink-700" },
  submitted: { label: "Submitted", cls: "bg-brand-50 text-brand-700" },
  being_marked: { label: "Being marked", cls: "bg-warn-100 text-warn-700" },
  marked: { label: "Marked", cls: "bg-ok-100 text-ok-700" },
};

/** In the reader's own zone (AV-67), like every other date addressed to them. */
function dueLabel(due: string | null, timeZone: string | null): string {
  if (!due) return "No due date";
  return `Due ${formatDayMonth(new Date(due), timeZone)}`;
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/* The student's own mistake pattern (4.5).

   Categories only, and no severity — the server does not send it, and this
   file must not acquire a way to show it. Severity is how the readiness engine
   weighs a mistake; to the person who made it, a number attached to their own
   work reads as a verdict on them.

   Three conditions, three different sentences, which is the point. A subject
   nobody has checked is absence and says so (PROD-2, UX-19); a subject checked
   with nothing found is a clean record and says something else; a request that
   failed knows neither and says a third thing. Collapsing any two of them
   tells a student something about themselves that is not true. */

const countMistakes = (n: number) => `${n} mistake${n === 1 ? "" : "s"}`;
const countQuestions = (n: number) => `${n} question${n === 1 ? "" : "s"}`;

function SubjectMistakes({ pattern }: { pattern: MyMistakePattern }) {
  return (
    <li className="py-3">
      <div className="text-sm font-medium text-ink-900">{pattern.subject_name}</div>
      {pattern.analysed_questions === 0 ? (
        <p className="mt-1 max-w-prose text-sm text-ink-500">
          No one has looked through this work for mistakes yet — {ABSENT.noEvidence}.
        </p>
      ) : pattern.total_mistakes === 0 ? (
        <p className="mt-1 max-w-prose text-sm text-ink-500">
          No mistakes noted in the {countQuestions(pattern.analysed_questions)} looked at so far.
        </p>
      ) : (
        <div className="mt-1 flex flex-wrap items-baseline gap-2">
          <span className="text-sm text-ink-700">
            {countMistakes(pattern.total_mistakes)} across{" "}
            {countQuestions(pattern.analysed_questions)} looked at
          </span>
          {pattern.categories.map((c) => (
            <span
              key={c.category_id}
              // The visible chip reads "Careless 3", which takes its unit from
              // the sentence beside it. A screen reader landing on the chip
              // alone gets no unit at all, and this is a child reading a
              // judgement about their own work — the one place an ambiguous
              // number is least acceptable.
              aria-label={`${c.category_name}: ${countMistakes(c.mistakes)}`}
              className="rounded bg-surface-muted px-1.5 py-0.5 text-xs text-ink-700"
            >
              {c.category_name} {c.mistakes}
            </span>
          ))}
        </div>
      )}
    </li>
  );
}

function MistakePatternSection() {
  const mistakes = useQuery({ queryKey: ["my-mistakes"], queryFn: myMistakes });
  const d = mistakes.data;

  // Nothing at all while the student has no subjects: the list above has
  // already said there is no work, and a second empty-state sentence answers
  // the same condition twice.
  if (!mistakes.isPending && !mistakes.isError && d?.length === 0) return null;

  return (
    <SectionCard>
      <h2 className="font-display text-lg text-ink-900">The kinds of mistake in your work</h2>
      <p className="mt-0.5 text-sm text-ink-500">
        Spotted while your homework was being marked, grouped by subject.
      </p>
      <div className="mt-3">
        {mistakes.isPending ? (
          <SectionSkeleton rows={2} label="Loading your mistake pattern" />
        ) : mistakes.isError || !d ? (
          // Never an empty list and never the clean-record line: a request that
          // failed knows nothing about this work (PROD-2).
          <p className="text-sm text-risk-600">Couldn&apos;t load this. {ABSENT.loadFailed}</p>
        ) : (
          <ul className="divide-y divide-line border-t border-line">
            {d.map((p) => (
              <SubjectMistakes key={p.subject_id} pattern={p} />
            ))}
          </ul>
        )}
      </div>
    </SectionCard>
  );
}

export default function HomeworkPage() {
  const myZone = useMyTimezone();
  const assignments = useQuery({ queryKey: ["my-assignments"], queryFn: myAssignments });

  return (
    <div className="max-w-3xl space-y-6">
      <PageHeader
        title="Homework"
        description="What your tutor has set, where each piece is up to, and your marks once it's marked."
      />

      {assignments.isPending ? (
        <SectionCard>
          <SectionSkeleton rows={3} label="Loading your homework" />
        </SectionCard>
      ) : assignments.isError ? (
        <ErrorState
          title="Couldn't load your homework."
          error={assignments.error}
          onRetry={() => void assignments.refetch()}
        />
      ) : assignments.data.length === 0 ? (
        <SectionCard>
          <EmptyState
            title="No homework yet."
            hint="It will appear here as soon as your tutor sets some."
          />
        </SectionCard>
      ) : (
        <ul className="space-y-3">
          {assignments.data.map((a) => {
            const badge = STATUS_BADGE[a.submission_status ?? "not_submitted"];
            return (
              <li key={a.id}>
                <Link
                  to={`/student/homework/${a.id}`}
                  className="flex items-center justify-between gap-4 rounded-xl border border-line bg-surface p-4 shadow-[0_1px_2px_rgba(44,26,14,0.06)] transition-colors hover:border-brand-500"
                >
                  <div className="min-w-0">
                    <div className="font-medium text-ink-900">{a.title}</div>
                    <div className="mt-1 text-sm text-ink-500">
                      {a.subject_name} · {plural(a.question_count, "question", "questions")} ·{" "}
                      {plural(a.total_marks, "mark", "marks")}
                    </div>
                    <div className="mt-0.5 text-sm text-ink-500">{dueLabel(a.due_at, myZone)}</div>
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-1.5 sm:flex-row sm:items-center sm:gap-3">
                    {a.submission_status === "marked" && a.my_total !== null && (
                      <span className="text-sm font-medium tabular-nums text-ink-900">
                        {a.my_total}/{a.total_marks} marks
                      </span>
                    )}
                    <span className={`rounded-md px-2 py-0.5 text-xs font-medium ${badge.cls}`}>
                      {badge.label}
                    </span>
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
      <MistakePatternSection />
    </div>
  );
}
