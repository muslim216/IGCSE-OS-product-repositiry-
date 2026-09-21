import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { myAssignments } from "../api/homework";
import { myMistakes, type MyMistakePattern } from "../api/students";
import { ABSENT } from "../lib/labels";

const STATUS_BADGE: Record<string, { label: string; cls: string }> = {
  not_submitted: { label: "Not started", cls: "bg-slate-100 text-slate-600" },
  submitted: { label: "Submitted", cls: "bg-blue-100 text-blue-700" },
  being_marked: { label: "Being marked", cls: "bg-amber-100 text-amber-700" },
  marked: { label: "Marked", cls: "bg-green-100 text-green-700" },
};

function dueLabel(due: string | null): string {
  if (!due) return "No due date";
  const d = new Date(due);
  return `Due ${d.toLocaleDateString(undefined, { day: "numeric", month: "short" })}`;
}

/* The student's own mistake pattern (4.5).

   Categories only, and no severity — the server does not send it, and this
   file must not acquire a way to show it. Severity is how the readiness engine
   weighs a mistake; to the person who made it, a number attached to their own
   work reads as a verdict on them.

   Three conditions, three different sentences, which is the point. A subject
   nobody has checked is absence and says so (PROD-2, UX-19); a subject checked
   with nothing found is a clean record and says something else; a request that
   failed knows neither and says a third thing. Collapsing any two of them
   tells a student something about themselves that is not true.

   Written with semantic tokens (UX-2). The rest of this page predates them and
   is left alone. */

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
    <section className="mt-8 rounded-lg border border-line bg-surface p-4">
      <h3 className="font-medium text-ink-900">The kinds of mistake in your work</h3>
      {mistakes.isPending ? (
        <p className="mt-1 text-sm text-ink-500">Loading…</p>
      ) : mistakes.isError || !d ? (
        // Never an empty list and never the clean-record line: a request that
        // failed knows nothing about this work (PROD-2).
        <p className="mt-1 text-sm text-risk-600">Could not load this. {ABSENT.loadFailed}</p>
      ) : (
        <ul className="mt-1 divide-y divide-line">
          {d.map((p) => (
            <SubjectMistakes key={p.subject_id} pattern={p} />
          ))}
        </ul>
      )}
    </section>
  );
}

export default function HomeworkPage() {
  const assignments = useQuery({ queryKey: ["my-assignments"], queryFn: myAssignments });

  return (
    <div>
      <h2 className="text-xl font-semibold text-slate-800">Your homework</h2>
      <div className="mt-4 space-y-3">
        {assignments.data?.map((a) => {
          const badge = STATUS_BADGE[a.submission_status ?? "not_submitted"];
          return (
            <Link
              key={a.id}
              to={`/student/homework/${a.id}`}
              className="flex items-center justify-between rounded-lg border bg-white p-4 hover:border-blue-400"
            >
              <div>
                <div className="font-medium text-slate-800">{a.title}</div>
                <div className="mt-1 text-sm text-slate-500">
                  {a.subject_name} · {a.question_count} questions · {a.total_marks} marks
                </div>
                <div className="mt-1 text-sm text-slate-400">{dueLabel(a.due_at)}</div>
              </div>
              <div className="flex items-center gap-3">
                {a.submission_status === "marked" && a.my_total !== null && (
                  <span className="text-sm font-medium text-slate-700">
                    {a.my_total}/{a.total_marks}
                  </span>
                )}
                <span className={`rounded-full px-2.5 py-1 text-xs ${badge.cls}`}>
                  {badge.label}
                </span>
              </div>
            </Link>
          );
        })}
        {assignments.data?.length === 0 && (
          <p className="text-slate-500">No homework yet — check back after your tutor sets some.</p>
        )}
      </div>
      <MistakePatternSection />
    </div>
  );
}
