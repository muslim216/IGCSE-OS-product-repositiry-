import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "../../components/controls";
import { friendlyError } from "../../lib/errors";
import { ITEM_NAMES, ITEM_SECTIONS, useAcknowledge, useOnboarding } from "../../lib/onboarding";
import { subjectSetupPath } from "../../lib/subjectSetup";
import type {
  AcknowledgeableItem,
  OnboardingClass,
  OnboardingState,
  OnboardingSubject,
} from "../../api/onboarding";

// inline-flex with a minimum height so the target size is not left to line height.
const LINK = "inline-flex min-h-6 items-center text-sm text-brand-600 hover:underline";
const ROW = "flex flex-wrap items-center gap-x-3 gap-y-1 py-2";

/** Where each class step is done. The teaching plan lives on the class's
 *  Schedule tab, so both plan steps point there. A step this client does not
 *  know is still outstanding, because the server counted it. */
function classStep(group: OnboardingClass): { label: string; to: string } | null {
  const step = group.steps.find((s) => !s.done);
  if (!step) return null;
  const base = `/tutor/groups/${group.group_id}`;
  switch (step.key) {
    case "timetable":
      return { label: "Add a timetable", to: `${base}/schedule` };
    case "taught_before":
      return { label: "Say where this class is up to", to: `${base}/syllabus#taught-before` };
    case "plan_inputs":
      return { label: "Enter the plan details", to: `${base}/schedule` };
    case "plan_accepted":
      return { label: "Accept the teaching plan", to: `${base}/schedule` };
    default:
      return { label: "Finish setting up this class", to: base };
  }
}

function itemState(subject: OnboardingSubject, key: string) {
  return subject.items.find((i) => i.key === key)?.state;
}

/** What still needs something in a subject. The card's visibility follows from
 *  these; the optional teaching guidance is listed but never makes a subject
 *  outstanding by itself. */
function subjectNeeds(subject: OnboardingSubject) {
  const syllabusMissing = subject.required.some((r) => r.key === "syllabus" && !r.done);
  const defaults = subject.items.filter((i) => i.kind === "defaulted" && i.state === "default");
  const boundariesNotSet = itemState(subject, "boundaries") === "not_set";
  const guidanceNotSet = itemState(subject, "teaching_guidance") === "not_set";
  const classes = subject.classes
    .map((c) => ({ group: c, step: classStep(c) }))
    .filter((c) => c.step !== null);
  // A subject with a syllabus and no class has nothing to teach yet.
  const noClass = !syllabusMissing && subject.classes.length === 0;
  const outstanding =
    syllabusMissing || defaults.length > 0 || boundariesNotSet || classes.length > 0 || noClass;
  return {
    syllabusMissing,
    defaults,
    boundariesNotSet,
    guidanceNotSet,
    classes,
    noClass,
    outstanding,
  };
}

function anyOutstanding(data: OnboardingState): boolean {
  return data.account.state === "default" || data.subjects.some((s) => subjectNeeds(s).outstanding);
}

/**
 * What is still open in setup, on the tutor's home (9.1d). Shown only while
 * something is outstanding and gone entirely when nothing is. The server's
 * onboarding state is the only source of what is done (SEC-10): this filters and
 * words it, and never works out completion itself.
 *
 * Nothing here blocks anything. While the query loads it renders nothing, so the
 * most-viewed page does not flash a skeleton; a failed load says so in one line,
 * but only when there is nothing to show: a failed background refetch keeps the
 * card the tutor was reading.
 */
export default function SetupChecklist({ onAcknowledged }: { onAcknowledged?: () => void }) {
  const onboarding = useOnboarding();
  const acknowledge = useAcknowledge();

  const headingRef = useRef<HTMLHeadingElement>(null);
  const goneRef = useRef<HTMLParagraphElement>(null);
  // Focus moves once the acknowledged state has actually replaced the old one:
  // moving it to the heading first would lose it again when the card goes.
  const dataAtPress = useRef<unknown>(null);
  const wantsFocus = useRef(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const data = onboarding.data;

  useEffect(() => {
    if (!wantsFocus.current || data === dataAtPress.current) return;
    wantsFocus.current = false;
    (headingRef.current ?? goneRef.current)?.focus();
  }, [data, acknowledged]);

  if (!data) {
    if (onboarding.isLoading) return null;
    return (
      <p role="status" className="flex items-center gap-2 text-sm text-ink-500">
        Setup checklist couldn&apos;t be loaded.
        <Button type="button" size="sm" variant="ghost" onClick={() => onboarding.refetch()}>
          Retry
        </Button>
      </p>
    );
  }

  if (!anyOutstanding(data)) {
    // Only after the tutor has just cleared the last thing: somewhere for focus
    // to land that is not a button that no longer exists.
    return acknowledged ? (
      <p ref={goneRef} tabIndex={-1} className="sr-only focus:outline-none">
        Nothing is left in the setup checklist.
      </p>
    ) : null;
  }

  const pressedItem = acknowledge.variables;
  const matches = (item: AcknowledgeableItem, subjectId: number | null) =>
    pressedItem?.item === item && pressedItem.subjectId === subjectId;
  const pending = (item: AcknowledgeableItem, subjectId: number | null) =>
    acknowledge.isPending && matches(item, subjectId);

  const keepButton = (item: AcknowledgeableItem, subjectId: number | null, what: string) => (
    <Button
      type="button"
      size="sm"
      variant="ghost"
      // aria-disabled, not disabled: a disabled button drops keyboard focus. One
      // request at a time, so the whole card ignores presses while it is in flight.
      aria-disabled={acknowledge.isPending || undefined}
      className="aria-disabled:cursor-not-allowed aria-disabled:opacity-50"
      aria-label={`Keep the default${item === "account_basics" ? "s" : ""} for ${what}`}
      onClick={() => {
        if (acknowledge.isPending) return;
        dataAtPress.current = data;
        acknowledge.mutate(
          { item, subjectId },
          {
            onSuccess: () => {
              wantsFocus.current = true;
              setAcknowledged(true);
              onAcknowledged?.();
            },
          },
        );
      }}
    >
      {pending(item, subjectId)
        ? "Saving"
        : item === "account_basics"
          ? "Keep the defaults"
          : "Keep the default"}
    </Button>
  );
  const rowError = (item: AcknowledgeableItem, subjectId: number | null) =>
    acknowledge.isError &&
    matches(item, subjectId) && (
      <p role="alert" className="w-full text-xs text-risk-600">
        {friendlyError(acknowledge.error)}
      </p>
    );

  return (
    <section
      aria-labelledby="setup-checklist-heading"
      className="rounded-xl border border-line bg-surface p-5"
    >
      <h2
        id="setup-checklist-heading"
        ref={headingRef}
        tabIndex={-1}
        className="text-lg text-ink-900 focus:outline-none"
      >
        Setup
      </h2>
      <p className="mt-1 max-w-2xl text-sm text-ink-500">
        None of this blocks anything. Anything left on Avora&apos;s default keeps working.
      </p>

      {data.account.state === "default" && (
        <ul className="mt-4 border-t border-line">
          <li className={ROW}>
            <p className="min-w-0 flex-1 text-sm text-ink-700">
              Time zone, AI language and weekly send day are on Avora&apos;s defaults.
            </p>
            <Link to="/tutor/settings" className={LINK} aria-label="Review account settings">
              Review
            </Link>
            {keepButton("account_basics", null, "account settings")}
            {rowError("account_basics", null)}
          </li>
        </ul>
      )}

      {data.subjects.map((subject) => {
        const needs = subjectNeeds(subject);
        if (!needs.outstanding) return null;
        const headingId = `setup-subject-${subject.subject_id}`;
        const name = subject.subject_name;
        return (
          <div
            key={subject.subject_id}
            role="group"
            aria-labelledby={headingId}
            className="mt-4 border-t border-line pt-3"
          >
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 id={headingId} className="font-medium text-ink-900">
                {name}
              </h3>
              <p className="text-sm text-ink-500">
                {subject.reviewed_count} of {subject.review_total} settings reviewed
              </p>
            </div>
            <ul className="mt-1 divide-y divide-line">
              {needs.syllabusMissing && (
                <li className={ROW}>
                  <span className="min-w-0 flex-1 text-sm text-ink-700">No syllabus yet</span>
                  <Link
                    to={subjectSetupPath("syllabus", subject.subject_id)}
                    className={LINK}
                    aria-label={`Add a syllabus for ${name}`}
                  >
                    Add a syllabus
                  </Link>
                </li>
              )}
              {needs.boundariesNotSet && (
                <li className={ROW}>
                  <span className="min-w-0 flex-1 text-sm text-ink-700">
                    No grade boundaries saved, so this subject has no predicted grades
                  </span>
                  <Link
                    to={subjectSetupPath("boundaries", subject.subject_id)}
                    className={LINK}
                    aria-label={`Set boundaries for ${name}`}
                  >
                    Set boundaries
                  </Link>
                </li>
              )}
              {needs.defaults.map((item) => {
                const label = ITEM_NAMES[item.key] ?? item.key;
                return (
                  <li key={item.key} className={ROW}>
                    <span className="min-w-0 flex-1 text-sm text-ink-700">
                      {label}
                      <span className="text-ink-500">: Avora&apos;s default, not reviewed yet</span>
                    </span>
                    <Link
                      to={subjectSetupPath(ITEM_SECTIONS[item.key] ?? "", subject.subject_id)}
                      className={LINK}
                      aria-label={`Review ${label}, ${name}`}
                    >
                      Review
                    </Link>
                    {keepButton(
                      item.key as AcknowledgeableItem,
                      subject.subject_id,
                      `${label}, ${name}`,
                    )}
                    {rowError(item.key as AcknowledgeableItem, subject.subject_id)}
                  </li>
                );
              })}
              {needs.guidanceNotSet && (
                <li className={ROW}>
                  <span className="min-w-0 flex-1 text-sm text-ink-700">
                    Teaching guidance (optional)
                  </span>
                  <Link
                    to={subjectSetupPath("teaching-guidance", subject.subject_id)}
                    className={LINK}
                    aria-label={`Add teaching guidance for ${name}`}
                  >
                    Add
                  </Link>
                </li>
              )}
              {needs.noClass && (
                <li className={ROW}>
                  <span className="min-w-0 flex-1 text-sm text-ink-700">
                    No class yet for this subject
                  </span>
                  <Link to="/tutor/classes" className={LINK} aria-label={`Add a class for ${name}`}>
                    Add a class
                  </Link>
                </li>
              )}
              {needs.classes.map(({ group, step }) => (
                <li key={group.group_id} className={ROW}>
                  <span className="min-w-0 flex-1 text-sm text-ink-700">{group.group_name}</span>
                  <Link
                    to={step!.to}
                    className={LINK}
                    aria-label={`${step!.label} for ${group.group_name}`}
                  >
                    {step!.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </section>
  );
}
