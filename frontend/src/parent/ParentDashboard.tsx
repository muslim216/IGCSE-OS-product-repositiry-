import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { myChildren } from "../api/groups";
import { studentNarrative } from "../api/narrative";
import { studentReadiness, type SubjectReadiness } from "../api/readiness";
import { DirectionMark, EmptyState, SectionCard, StatusBadge } from "../components/ui";
import {
  ErrorState,
  PageHeader,
  PageSkeleton,
  SectionSkeleton,
  Skeleton,
} from "../components/page";
import { ReportsPanel } from "../components/ReportsPanel";
import CustomCriteriaPanel from "../components/CustomCriteriaPanel";
import AttendancePanel from "../components/AttendancePanel";
import { ABSENT } from "../lib/labels";
import { parentVerdict, provenance, whatYouCanDo } from "../lib/parent";

/**
 * The parent screen. One screen, no navigation — the role has exactly one
 * destination and that is correct, not an omission (experience-design §6).
 *
 * **Hierarchy: child state → narrative → evidence → detail.** The first
 * sentence answers the question, and is the page's title. The subject rows are
 * the objects. The paragraph explains. Earlier reports are the detail.
 *
 * **Predicted and averaging are both shown, and visibly distinguished.** This is
 * where the pair earns its place: a parent who sees only a predicted grade reads
 * it as a forecast the school is committing to. Beside the average of marked
 * work it becomes legible as an estimate that moves (§3.3).
 *
 * **No per-homework detail.** Aggregates and direction only. Per-piece results
 * turn this into a surveillance surface the student can feel, which damages the
 * relationship the tutor depends on.
 *
 * **`not enough data yet` is a first-class state here, not an edge case.** A
 * newly linked parent sees mostly that, and the screen has to look deliberate in
 * that condition rather than broken.
 *
 * The parent's own time-zone setting used to sit at the bottom of this screen
 * because the role had nowhere else to put it. It lives on the parent's
 * Account page now, one tap from the avatar.
 */

function SubjectRow({ subject }: { subject: SubjectReadiness }) {
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-1.5 py-3">
      <span className="min-w-36 font-medium text-ink-900">{subject.subject_name}</span>
      {subject.status === null ? (
        // No band. Distinguish "nothing marked yet" from "marked work exists but
        // the subject has no grade boundaries to map it through" — the two are
        // different facts and only the first is "not enough data yet" (CodeRabbit).
        <span className="text-sm text-ink-500">
          {subject.marked_piece_count > 0 ? ABSENT.noBoundaries : ABSENT.noEvidence}
        </span>
      ) : (
        <>
          <StatusBadge status={subject.status} />
          {/* Each grade says which grade it is. "predicted 6 · averaging 8"
              left a parent to guess what "averaging" meant, and which of the
              two numbers was the school's view. */}
          <span className="text-sm tabular-nums text-ink-700">
            Predicted grade{" "}
            <span className="font-semibold text-ink-900">{subject.predicted_grade}</span>
            {subject.averaging_grade !== null && (
              <>
                {" "}
                · Averaging grade{" "}
                <span className="font-semibold text-ink-900">{subject.averaging_grade}</span> in
                marked work
              </>
            )}
          </span>
          <DirectionMark direction={subject.direction} />
        </>
      )}
    </li>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <SectionCard>
      <h2 className="avora-label mb-2">{title}</h2>
      {children}
    </SectionCard>
  );
}

export default function ParentDashboard() {
  const children = useQuery({ queryKey: ["my-children"], queryFn: myChildren });
  const [activeChild, setActiveChild] = useState<number | null>(null);
  const selected = activeChild ?? children.data?.[0]?.id ?? null;

  const readiness = useQuery({
    queryKey: ["child-readiness", selected],
    queryFn: () => studentReadiness(selected!),
    enabled: selected !== null,
  });
  // Read, never generated here: the paragraph is written by a background job and
  // stored, so this screen renders it on open rather than waiting on a model
  // call (spec §8).
  const narrative = useQuery({
    queryKey: ["narrative", "student", selected],
    queryFn: () => studentNarrative(selected!),
    enabled: selected !== null,
  });

  if (children.isLoading) {
    return <PageSkeleton rows={3} label="Loading your child's progress" />;
  }
  if (children.isError) {
    return (
      <div className="max-w-3xl">
        <PageHeader title="Overview" />
        <ErrorState
          title="We couldn't load this right now."
          error={children.error}
          onRetry={() => void children.refetch()}
        />
      </div>
    );
  }
  if (!children.data || children.data.length === 0) {
    return (
      <div className="max-w-3xl">
        <PageHeader title="Welcome to avora" />
        <SectionCard>
          <EmptyState
            title="No child is linked to this account yet."
            hint="Ask the tutor for a parent link — it takes you straight to your child's page."
          />
        </SectionCard>
      </div>
    );
  }

  const childName = children.data.find((c) => c.id === selected)?.name;
  const name = readiness.data?.student_name ?? childName;
  const subjects = readiness.data?.subjects ?? [];

  // The child switcher sits beside the verdict, under the child's name — which
  // child this is about has to be settled before anything it says means
  // anything. It is object selection, not navigation.
  const switcher =
    children.data.length > 1 ? (
      <div role="group" aria-label="Choose a child" className="flex flex-wrap gap-2">
        {children.data.map((c) => (
          <button
            key={c.id}
            type="button"
            // The selected child is otherwise carried only by colour; aria-pressed
            // lets assistive technology announce which child is active (CodeRabbit).
            aria-pressed={selected === c.id}
            onClick={() => setActiveChild(c.id)}
            // An unselected chip's edge is its boundary, so `avora-control`
            // draws it, hover included: a `border-line-control` utility loses
            // to the unlayered `.border` rule in index.css and renders the
            // decorative hairline, under WCAG 1.4.11's 3:1. The selected chip
            // has no border to lose — its terracotta fill is the boundary.
            className={`h-8 rounded-full px-4 text-sm font-medium transition-colors ${
              selected === c.id
                ? "bg-brand-600 text-canvas"
                : "avora-control border bg-surface text-ink-700"
            }`}
          >
            {c.name}
          </button>
        ))}
      </div>
    ) : undefined;

  return (
    <div className="max-w-3xl space-y-6">
      {readiness.isLoading || !name ? (
        <>
          <PageHeader
            eyebrow={childName}
            title={<Skeleton className="h-8 w-80 max-w-full" />}
            documentTitle="Overview"
            actions={switcher}
          />
          <SectionCard>
            <SectionSkeleton rows={3} label="Loading subjects" />
          </SectionCard>
        </>
      ) : readiness.isError ? (
        <>
          <PageHeader eyebrow="Overview" title={name} actions={switcher} />
          <ErrorState
            title="We couldn't load this right now."
            error={readiness.error}
            onRetry={() => void readiness.refetch()}
          />
        </>
      ) : (
        <>
          <PageHeader
            eyebrow={name}
            title={parentVerdict(name, subjects)}
            description={provenance(subjects)}
            documentTitle={name}
            actions={switcher}
          />

          {subjects.length > 0 && (
            <Section title="Subjects">
              <ul className="divide-y divide-line">
                {subjects.map((s) => (
                  <SubjectRow key={s.subject_id} subject={s} />
                ))}
              </ul>
            </Section>
          )}

          <Section title="How it's going">
            {narrative.isLoading ? (
              <SectionSkeleton rows={2} label="Loading the summary" />
            ) : narrative.isError ? (
              // Before the absence below: a request that failed knows nothing
              // about whether a summary exists, and "nothing written yet" would
              // tell a parent there is nothing to read when we could not ask.
              <ErrorState
                title="We couldn't load the summary."
                error={narrative.error}
                onRetry={() => void narrative.refetch()}
              />
            ) : narrative.data?.text ? (
              <p className="max-w-prose text-sm leading-relaxed text-ink-700">
                {narrative.data.text}
              </p>
            ) : (
              // A stated absence, never an empty block. A blank space under a
              // heading reads to this reader as something withheld.
              <p className="text-sm text-ink-500">
                Nothing written yet — a summary appears once there is enough marked work to say
                something useful.
              </p>
            )}
          </Section>

          <Section title="What you can do">
            <p className="max-w-prose text-sm text-ink-700">{whatYouCanDo(subjects)}</p>
          </Section>
        </>
      )}

      {/* The tutor's hand scores for this child, beside readiness and never
          in it (owner decisions 6 and 18). */}
      {selected !== null && <CustomCriteriaPanel studentId={selected} />}

      {/* Beside readiness, never in it (AV-33). */}
      {selected !== null && <AttendancePanel studentId={selected} />}

      {selected !== null && (
        <ReportsPanel studentId={selected} audiences={["parent"]} canGenerate={false} />
      )}
    </div>
  );
}
