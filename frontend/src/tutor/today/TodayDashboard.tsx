import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { todayView, type ClassStripRow } from "../../api/today";
import { listGroups } from "../../api/groups";
import { assignmentsNeedingAttention } from "../../api/homework";
import { EmptyState, StatusBadge, useToast } from "../../components/ui";
import { ABSENT, REASON_LABELS } from "../../lib/labels";
import { coverageLabel, isClearDay, verdictLine1, verdictLine2 } from "../../lib/verdict";
import ClassNarrative from "./ClassNarrative";
import CreateLessonModal from "./CreateLessonModal";

/**
 * The tutor's home, rebuilt: verdict → class strip → TODAY → WHAT CHANGED →
 * NEEDS YOU.
 *
 * The rule that shapes every branch below: a section with nothing to report is
 * NOT RENDERED (UX-29). It never becomes an empty card, a spinner where the
 * previous value would do, or a `0` standing in for a missing measurement
 * (PROD-2, UX-19). A completely clear day ends with a sentence, not a screen of
 * empty panels.
 */

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="avora-label mb-2">{title}</h3>
      {children}
    </section>
  );
}

function ClassRow({ row }: { row: ClassStripRow }) {
  const coverage = coverageLabel(row);
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-line py-2.5">
      <Link
        to={`/tutor/groups/${row.group_id}/students`}
        className="font-medium text-ink-900 hover:text-brand-600"
      >
        {row.name}
      </Link>
      <span className="text-sm text-ink-500">{row.subject_name}</span>

      {row.status ? (
        <>
          <span className="font-display text-[15px] tabular-nums text-ink-900">
            {row.predicted_grade}
          </span>
          <StatusBadge status={row.status} />
        </>
      ) : row.boundaries_missing ? (
        <span className="text-sm text-ink-500">
          {ABSENT.noBoundaries}{" "}
          <Link to="/tutor/library" className="font-medium text-brand-600 hover:text-brand-700">
            {ABSENT.noBoundariesAction}
          </Link>
        </span>
      ) : (
        <span className="text-sm text-ink-500">{ABSENT.noEvidence}</span>
      )}

      {coverage && (
        <span className="ml-auto text-xs tabular-nums text-ink-500" title="Learners with evidence">
          {coverage}
        </span>
      )}
    </li>
  );
}

export default function TodayDashboard() {
  const [createOpen, setCreateOpen] = useState(false);
  const { toast, showToast } = useToast();

  const today = useQuery({ queryKey: ["today"], queryFn: todayView });
  const attention = useQuery({
    queryKey: ["assignments-attention"],
    queryFn: assignmentsNeedingAttention,
  });
  // Only the lesson modal needs full Group objects; the surface itself renders
  // from the aggregate, so this never gates what the tutor reads.
  const groups = useQuery({ queryKey: ["groups"], queryFn: listGroups });

  if (today.isLoading) {
    return (
      <div className="space-y-6" aria-busy="true">
        <span aria-hidden className="block h-7 w-2/3 animate-pulse rounded bg-surface-muted" />
        <span aria-hidden className="block h-24 w-full animate-pulse rounded bg-surface-muted" />
      </div>
    );
  }

  if (today.isError || !today.data) {
    return <EmptyState title="Today couldn't be loaded." hint={ABSENT.loadFailed} />;
  }

  const view = today.data;
  const line1 = verdictLine1(view);
  const line2 = verdictLine2(view);
  const clear = isClearDay(view);

  // Before any class exists the only useful thing on this surface is the way to
  // make one — every other section would be an honest but useless absence.
  if (view.class_count === 0) {
    return (
      <EmptyState
        title={line1}
        hint="Create a class and share its code — readiness appears once learners join and work is marked."
        action={
          <Link to="/tutor/classes" className="font-medium text-brand-600 hover:text-brand-700">
            Create a class →
          </Link>
        }
      />
    );
  }

  const exceptions = view.classes.filter((c) => c.status !== "on_track");
  const healthy = view.classes.filter((c) => c.status === "on_track");

  return (
    <div className="space-y-8">
      {/* The verdict is the first thing read and the primary target. */}
      <div>
        <h2 className="font-display text-2xl font-semibold text-ink-900">{line1}</h2>
        {line2 && (
          <p className="mt-1 flex flex-wrap items-center gap-3 text-sm text-ink-700">
            <span>{line2}</span>
            {view.review_count > 0 && (
              <Link to="/tutor/review" className="font-medium text-brand-600 hover:text-brand-700">
                Mark →
              </Link>
            )}
          </p>
        )}
      </div>

      {/* Class strip. Healthy classes collapse to one line so the exceptions are
          what the eye lands on — nothing is hidden, it is summarised. */}
      <Section title="Classes">
        <ul>
          {exceptions.map((row) => (
            <ClassRow key={row.group_id} row={row} />
          ))}
          {healthy.length > 0 && (
            <li className="border-t border-line py-2.5 text-sm text-ink-500">
              <span className="text-ok-700">●</span>{" "}
              {healthy.length === 1
                ? `${healthy[0].name} is on track`
                : `${healthy.length} classes on track`}
              <span className="ml-2 text-ink-500">
                {healthy.map((c) => `${c.name} ${c.predicted_grade ?? ""}`.trim()).join(" · ")}
              </span>
            </li>
          )}
        </ul>
      </Section>

      <Section title="Today">
        {view.lessons.length === 0 ? (
          <p className="text-sm text-ink-500">No lessons scheduled.</p>
        ) : (
          <ul className="text-sm">
            {view.lessons.map((lesson) => (
              <li key={lesson.id} className="flex items-center gap-3 border-t border-line py-2.5">
                <span className="font-display tabular-nums text-ink-900">
                  {lesson.start_time.slice(0, 5)}
                </span>
                <Link
                  to={`/tutor/groups/${lesson.group_id}/students`}
                  className="font-medium text-ink-900 hover:text-brand-600"
                >
                  {lesson.group_name}
                </Link>
                <span className="text-ink-500">{lesson.subject_name}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      {/* WHAT CHANGED reads the stored narrative — present on open, never a
          surface waiting on a model call (spec §8). */}
      <ClassNarrative classes={view.classes} />

      {/* NEEDS YOU is absent entirely when nothing needs them (UX-29). */}
      {view.review_count > 0 && (
        <Section title="Needs you">
          <ul className="text-sm">
            {(attention.data ?? []).slice(0, 5).map((item, i) => (
              <li
                key={i}
                className="flex flex-wrap items-center justify-between gap-2 border-t border-line py-2.5"
              >
                <Link
                  to={
                    item.submission_id
                      ? `/tutor/submissions/${item.submission_id}`
                      : `/tutor/assignments/${item.assignment_id}`
                  }
                  className="font-medium text-brand-600 hover:text-brand-700"
                >
                  {item.assignment_title}
                </Link>
                <span className="text-warn-700">{REASON_LABELS[item.reason] ?? item.reason}</span>
              </li>
            ))}
          </ul>
          <Link
            to="/tutor/review"
            className="mt-3 inline-block text-sm font-medium text-brand-600 hover:text-brand-700"
          >
            Review →
          </Link>
        </Section>
      )}

      {clear && <p className="text-sm text-ink-500">That's everything. Enjoy your day.</p>}

      <div>
        <button
          type="button"
          onClick={() => setCreateOpen(true)}
          className="text-sm font-medium text-brand-600 hover:text-brand-700"
        >
          Create lesson
        </button>
      </div>

      <CreateLessonModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        groups={groups.data}
        onCreated={() => showToast("Lesson scheduled.")}
      />
      {toast}
    </div>
  );
}
