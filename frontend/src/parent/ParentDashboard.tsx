import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { myChildren } from "../api/groups";
import { studentNarrative } from "../api/narrative";
import { studentReadiness, type SubjectReadiness } from "../api/readiness";
import { DirectionMark, EmptyState, StatusBadge } from "../components/ui";
import { ReportsPanel } from "../components/ReportsPanel";
import { ABSENT } from "../lib/labels";
import { parentVerdict, provenance, whatYouCanDo } from "../lib/parent";

/**
 * The parent screen. One screen, no navigation — the role has exactly one
 * destination and that is correct, not an omission (experience-design §6).
 *
 * **Hierarchy: child state → narrative → evidence → detail.** The first
 * sentence answers the question. The subject rows are the objects. The
 * paragraph explains. Earlier reports are the detail.
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
 */

function SubjectRow({ subject }: { subject: SubjectReadiness }) {
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-line py-2.5">
      <span className="min-w-32 font-medium text-ink-900">{subject.subject_name}</span>
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
          <span className="text-sm tabular-nums text-ink-700">
            predicted {subject.predicted_grade}
            {subject.averaging_grade !== null && <> · averaging {subject.averaging_grade}</>}
          </span>
          <DirectionMark direction={subject.direction} />
        </>
      )}
    </li>
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
    return (
      <div aria-busy="true">
        <span aria-hidden className="block h-24 w-full animate-pulse rounded bg-surface-muted" />
      </div>
    );
  }
  if (children.isError) {
    return <EmptyState title="This couldn't be loaded." hint={ABSENT.loadFailed} />;
  }
  if (!children.data || children.data.length === 0) {
    return (
      <EmptyState
        title="No child is linked to this account yet."
        hint="Ask the tutor for a parent link — it takes you straight to your child's page."
      />
    );
  }

  const name = readiness.data?.student_name ?? children.data.find((c) => c.id === selected)?.name;
  const subjects = readiness.data?.subjects ?? [];

  return (
    <div className="space-y-8">
      {/* The child switcher stays, above the verdict — which child this is about
          has to be settled before anything it says means anything. */}
      {children.data.length > 1 && (
        <div className="flex flex-wrap gap-2">
          {children.data.map((c) => (
            <button
              key={c.id}
              type="button"
              // The selected child is otherwise carried only by colour; aria-pressed
              // lets assistive technology announce which child is active (CodeRabbit).
              aria-pressed={selected === c.id}
              onClick={() => setActiveChild(c.id)}
              className={`rounded-full px-4 py-1.5 text-sm ${
                selected === c.id
                  ? "bg-brand-600 text-canvas"
                  : "bg-surface text-ink-700 hover:bg-surface-muted"
              }`}
            >
              {c.name}
            </button>
          ))}
        </div>
      )}

      {readiness.isLoading || !name ? (
        <span aria-hidden className="block h-16 w-full animate-pulse rounded bg-surface-muted" />
      ) : readiness.isError ? (
        <EmptyState title="This couldn't be loaded." hint={ABSENT.loadFailed} />
      ) : (
        <>
          <div>
            <h2 className="font-display text-2xl font-semibold text-ink-900">
              {parentVerdict(name, subjects)}
            </h2>
            <p className="mt-1 text-sm text-ink-500">{provenance(subjects)}</p>
          </div>

          {subjects.length > 0 && (
            <ul>
              {subjects.map((s) => (
                <SubjectRow key={s.subject_id} subject={s} />
              ))}
            </ul>
          )}

          <section>
            <h3 className="avora-label mb-2">How it's going</h3>
            {narrative.data?.text ? (
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
          </section>

          <section>
            <h3 className="avora-label mb-2">What you can do</h3>
            <p className="max-w-prose text-sm text-ink-700">{whatYouCanDo(subjects)}</p>
          </section>
        </>
      )}

      {selected !== null && (
        <ReportsPanel studentId={selected} audiences={["parent"]} canGenerate={false} />
      )}
    </div>
  );
}
