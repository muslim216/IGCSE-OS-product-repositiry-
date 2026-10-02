import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { myReadiness, type SubjectReadiness } from "../api/readiness";
import { DirectionMark, EmptyState, SectionCard } from "../components/ui";
import { ErrorState, PageHeader, PageSkeleton } from "../components/page";
import { ReportsPanel } from "../components/ReportsPanel";
import CustomCriteriaPanel from "../components/CustomCriteriaPanel";
import { ABSENT } from "../lib/labels";
import {
  GAP_REASON,
  GAP_SENTENCE,
  gradeGap,
  movementSentence,
  thinEvidenceNote,
} from "../lib/student";

/**
 * Progress: predicted beside averaging, the sentence explaining the gap, WHY per
 * topic, and the evidence behind it all.
 *
 * **The gap is the story** (experience-design §3.3). A predicted grade shown
 * alone reads as a promise. Shown beside the plain average of marked work it
 * becomes legible as an estimate that moves — and the sentences under them say
 * which way, how the two are worked out, and how much work the average rests
 * on, which is the only part a student can act on.
 *
 * **Nothing here is invented to fill a row.** A subject with no marked work has
 * no averaging grade; that is stated, not rendered as a grade equal to the
 * prediction, which would claim the record agrees with a forecast drawn from
 * nothing (PROD-2, PROD-1).
 */

const PROGRESS_DESCRIPTION = "How each subject is going, and the work it's based on.";

/** The marker on a topic whose score rests partly on the tutor's own starting
    judgement rather than marked work (PROD-8, UX-20). One wording, so the
    legend below can explain exactly the words the reader saw. */
const ESTIMATE_BADGE = "Includes tutor's estimate";

function EstimateBadge() {
  return (
    <span className="ml-2 inline-block rounded-md bg-surface-muted px-1.5 py-0.5 text-[11px] font-medium text-ink-500">
      {ESTIMATE_BADGE}
    </span>
  );
}

/** One of the two grades. A missing grade is words, never a dash or a zero:
    "not enough data yet" when nothing is marked, "no grade boundaries set" when
    there is a score but nothing to map it through (§3.2). */
function GradeTile({
  label,
  grade,
  absent,
  detail,
  children,
}: {
  label: string;
  grade: string | null;
  absent: string;
  detail: string | null;
  children?: ReactNode;
}) {
  return (
    <div className="rounded-lg border border-line bg-canvas px-4 py-3">
      <dt className="text-xs font-medium text-ink-500">{label}</dt>
      <dd className="mt-1 flex min-h-9 items-baseline gap-2">
        {grade === null ? (
          <span className="text-sm text-ink-500">{absent}</span>
        ) : (
          <>
            <span className="font-display text-3xl leading-none tabular-nums text-ink-900">
              {grade}
            </span>
            {children}
          </>
        )}
      </dd>
      {detail && <dd className="mt-1 text-xs tabular-nums text-ink-500">{detail}</dd>}
    </div>
  );
}

function pieces(n: number): string {
  return `${n} ${n === 1 ? "piece" : "pieces"} of work`;
}

function SubjectProgress({ subject }: { subject: SubjectReadiness }) {
  const gap = gradeGap(subject);
  const movement = movementSentence(subject.month_delta);
  const thin = thinEvidenceNote(subject.marked_piece_count);
  // Weak topics carry the WHY; the evidence count comes from the topic rows,
  // which is where it is recorded. A weak topic the engine flagged but that has
  // no evidence behind it says so rather than showing a score as if it were
  // measured.
  const evidenceByTopic = new Map(subject.topics.map((t) => [t.topic_id, t.evidence_count]));
  const anyEstimate =
    subject.topics.some((t) => t.tutor_estimate) ||
    subject.weak_topics.some((t) => t.tutor_estimate);

  return (
    <SectionCard className="space-y-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-display text-xl text-ink-900">{subject.subject_name}</h2>
        {subject.is_updating && (
          <span className="text-xs text-ink-500" aria-live="polite">
            {ABSENT.updating}
          </span>
        )}
      </div>

      <dl className="grid gap-3 sm:grid-cols-2">
        <GradeTile
          label="Predicted grade"
          grade={subject.predicted_grade}
          absent={subject.score !== null ? ABSENT.noBoundaries : ABSENT.noEvidence}
          detail={subject.score !== null ? `${Math.round(subject.score)}% ready` : null}
        >
          <DirectionMark direction={subject.direction} />
        </GradeTile>
        <GradeTile
          label="Averaging grade"
          grade={subject.averaging_grade}
          absent={subject.marked_piece_count > 0 ? ABSENT.noBoundaries : ABSENT.noEvidence}
          // Where the average came from travels with it (PROD-1).
          detail={
            subject.averaging_score !== null
              ? `Average mark ${Math.round(subject.averaging_score)}% · from ${
                  subject.marked_piece_count
                } ${subject.marked_piece_count === 1 ? "marked piece" : "marked pieces"}`
              : null
          }
        />
      </dl>

      {(gap !== null || thin || movement) && (
        <div className="max-w-prose space-y-1.5 text-sm leading-relaxed">
          {gap !== null && <p className="font-medium text-ink-900">{GAP_SENTENCE[gap]}</p>}
          {gap !== null && gap !== "equal" && <p className="text-ink-700">{GAP_REASON[gap]}</p>}
          {thin && <p className="text-ink-700">{thin}</p>}
          {movement && <p className="text-ink-700">{movement}</p>}
        </div>
      )}

      {subject.weak_topics.length > 0 && (
        <div>
          <h3 className="avora-label">Why</h3>
          <p className="mt-1 text-xs text-ink-500">
            These topics are below the level your tutor looks for in this subject.
          </p>
          <ul className="mt-2 divide-y divide-line border-t border-line text-sm">
            {subject.weak_topics.map((t) => {
              const count = evidenceByTopic.get(t.topic_id) ?? 0;
              return (
                <li
                  key={t.topic_id}
                  className="flex flex-wrap items-center justify-between gap-2 py-2"
                >
                  <span className="min-w-0">
                    <span className="text-ink-900">{t.topic_title}</span>
                    <span className="ml-2 text-xs text-ink-500">{t.topic_code}</span>
                    {t.tutor_estimate && <EstimateBadge />}
                  </span>
                  <span className="tabular-nums text-ink-500">
                    {count === 0
                      ? ABSENT.noEvidence
                      : `${Math.round(t.score)}% across ${pieces(count)}`}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {subject.topics.length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer font-medium text-brand-600 hover:text-brand-700">
            Every topic and its evidence
          </summary>
          <ul className="mt-2 divide-y divide-line border-t border-line">
            {subject.topics.map((t) => (
              <li
                key={t.topic_id}
                className="flex flex-wrap items-center justify-between gap-2 py-2"
              >
                <span className="min-w-0">
                  <span className="text-ink-900">{t.topic_title}</span>
                  <span className="ml-2 text-xs text-ink-500">{t.topic_code}</span>
                  {t.tutor_estimate && <EstimateBadge />}
                </span>
                <span className="tabular-nums text-ink-500">
                  {t.evidence_count === 0
                    ? ABSENT.noEvidence
                    : `${Math.round(t.score)}% across ${pieces(t.evidence_count)}`}
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-ink-500">
            {subject.topics_with_evidence} of {subject.topic_count} topics have evidence so far.
          </p>
        </details>
      )}

      {/* A label the reader cannot decode is not a label. The badge alone
          relied on a tooltip, which a phone never shows, so its meaning is
          stated once in words wherever it appears (PROD-8, UX-20). */}
      {anyEstimate && (
        <p className="max-w-prose text-xs leading-relaxed text-ink-500">
          <span className="font-medium text-ink-700">Tutor&apos;s estimate:</span> part of that
          topic&apos;s score comes from where your tutor judged you to be before much of your work
          was marked. It counts for less as your marked work comes in.
        </p>
      )}
    </SectionCard>
  );
}

export default function ProgressPage() {
  const readiness = useQuery({ queryKey: ["my-readiness"], queryFn: myReadiness });

  if (readiness.isLoading) {
    return <PageSkeleton rows={3} label="Loading your progress" />;
  }
  if (readiness.isError || !readiness.data) {
    return (
      <div className="max-w-3xl">
        <PageHeader title="Progress" description={PROGRESS_DESCRIPTION} />
        <ErrorState
          title="Couldn't load your progress."
          error={readiness.error}
          onRetry={() => void readiness.refetch()}
        />
      </div>
    );
  }

  const subjects = readiness.data.subjects;
  if (subjects.length === 0) {
    return (
      <div className="max-w-3xl">
        <PageHeader title="Progress" description={PROGRESS_DESCRIPTION} />
        <SectionCard>
          <EmptyState
            title="No progress to show yet."
            hint="It builds up as your homework, past papers and mocks are marked."
          />
        </SectionCard>
      </div>
    );
  }

  return (
    <div className="max-w-3xl space-y-6">
      <PageHeader title="Progress" description={PROGRESS_DESCRIPTION} />
      {subjects.map((s) => (
        <SubjectProgress key={s.subject_id} subject={s} />
      ))}
      {/* Beside readiness, never in it (owner decisions 6 and 18). */}
      <CustomCriteriaPanel studentId={readiness.data.student_id} />
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
