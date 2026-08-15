import { useQuery } from "@tanstack/react-query";
import { myReadiness, type SubjectReadiness } from "../api/readiness";
import { DirectionMark, EmptyState } from "../components/ui";
import { ReportsPanel } from "../components/ReportsPanel";
import { ABSENT } from "../lib/labels";
import { GAP_SENTENCE, gradeGap, movementSentence } from "../lib/student";

/**
 * Progress: predicted beside averaging, the sentence explaining the gap, WHY per
 * topic, and the evidence behind it all.
 *
 * **The gap is the story** (experience-design §3.3). A predicted grade shown
 * alone reads as a promise. Shown beside the plain average of marked work it
 * becomes legible as an estimate that moves — and the sentence between them
 * says which way and why, which is the only part a student can act on.
 *
 * **Nothing here is invented to fill a row.** A subject with no marked work has
 * no averaging grade; that is stated, not rendered as a grade equal to the
 * prediction, which would claim the record agrees with a forecast drawn from
 * nothing (PROD-2, PROD-1).
 */

function GradeLine({
  label,
  grade,
  score,
  children,
}: {
  label: string;
  grade: string | null;
  score: number | null;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-baseline gap-3 border-t border-line py-2.5">
      <span className="w-24 text-sm text-ink-500">{label}</span>
      {grade === null ? (
        <span className="text-sm text-ink-500">{ABSENT.noEvidence}</span>
      ) : (
        <>
          <span className="font-display text-xl tabular-nums text-ink-900">{grade}</span>
          {score !== null && (
            <span className="text-xs tabular-nums text-ink-500">{Math.round(score)}%</span>
          )}
          {children}
        </>
      )}
    </div>
  );
}

function SubjectProgress({ subject }: { subject: SubjectReadiness }) {
  const gap = gradeGap(subject);
  const movement = movementSentence(subject.month_delta);
  // Weak topics carry the WHY; the evidence count comes from the topic rows,
  // which is where it is recorded. A weak topic the engine flagged but that has
  // no evidence behind it says so rather than showing a score as if it were
  // measured.
  const evidenceByTopic = new Map(subject.topics.map((t) => [t.topic_id, t.evidence_count]));

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-baseline gap-3">
        <h3 className="avora-label">{subject.subject_name}</h3>
        {subject.is_updating && (
          <span className="text-xs text-ink-500" aria-live="polite">
            {ABSENT.updating}
          </span>
        )}
      </div>

      <div>
        <GradeLine label="Predicted" grade={subject.predicted_grade} score={subject.score}>
          <DirectionMark direction={subject.direction} />
        </GradeLine>
        <GradeLine
          label="Averaging"
          grade={subject.averaging_grade}
          score={subject.averaging_score}
        >
          {/* Where the average came from travels with it (PROD-1). */}
          <span className="text-xs text-ink-500">
            from {subject.marked_piece_count}{" "}
            {subject.marked_piece_count === 1 ? "marked piece" : "marked pieces"}
          </span>
        </GradeLine>
      </div>

      {gap !== null && (
        <p className="max-w-prose text-sm leading-relaxed text-ink-700">{GAP_SENTENCE[gap]}</p>
      )}
      {movement && <p className="text-sm text-ink-700">{movement}</p>}

      {subject.weak_topics.length > 0 && (
        <div>
          <h4 className="avora-label mb-1">Why</h4>
          <ul className="text-sm">
            {subject.weak_topics.map((t) => {
              const count = evidenceByTopic.get(t.topic_id) ?? 0;
              return (
                <li
                  key={t.topic_id}
                  className="flex flex-wrap items-center justify-between gap-2 border-t border-line py-2"
                >
                  <span className="text-ink-700">
                    {t.topic_code} {t.topic_title}
                  </span>
                  <span className="tabular-nums text-ink-500">
                    {count === 0
                      ? ABSENT.noEvidence
                      : `${Math.round(t.score)}% · ${count} ${count === 1 ? "piece" : "pieces"}`}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {subject.topics.length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer text-brand-600 hover:text-brand-700">Evidence</summary>
          <ul className="mt-1">
            {subject.topics.map((t) => (
              <li
                key={t.topic_id}
                className="flex flex-wrap items-center justify-between gap-2 border-t border-line py-1.5"
              >
                <span className="text-ink-700">
                  {t.topic_code} {t.topic_title}
                </span>
                <span className="tabular-nums text-ink-500">
                  {t.evidence_count === 0
                    ? ABSENT.noEvidence
                    : `${Math.round(t.score)}% · ${t.evidence_count} ${
                        t.evidence_count === 1 ? "piece" : "pieces"
                      }`}
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-ink-500">
            {subject.topics_with_evidence} of {subject.topic_count} topics carry evidence so far.
          </p>
        </details>
      )}
    </section>
  );
}

export default function ProgressPage() {
  const readiness = useQuery({ queryKey: ["my-readiness"], queryFn: myReadiness });

  if (readiness.isLoading) {
    return (
      <div aria-busy="true">
        <span aria-hidden className="block h-32 w-full animate-pulse rounded bg-surface-muted" />
      </div>
    );
  }
  if (readiness.isError || !readiness.data) {
    return <EmptyState title="Progress couldn't be loaded." hint={ABSENT.loadFailed} />;
  }

  const subjects = readiness.data.subjects;
  if (subjects.length === 0) {
    return (
      <EmptyState
        title="No progress to show yet."
        hint="It builds up as your homework, past papers and mocks are marked."
      />
    );
  }

  return (
    <div className="space-y-8">
      {subjects.map((s) => (
        <SubjectProgress key={s.subject_id} subject={s} />
      ))}
      {/* Written reports are the last rung of the hierarchy — detail, under the
          numbers and their explanation. They moved here with the rest of the
          student's backward-looking view when the old Readiness page was
          replaced, rather than being dropped. */}
      <ReportsPanel
        studentId={readiness.data.student_id}
        audiences={["student"]}
        canGenerate={false}
      />
    </div>
  );
}
