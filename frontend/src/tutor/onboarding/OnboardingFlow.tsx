import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronUp } from "lucide-react";
import { createGroup } from "../../api/groups";
import type { OnboardingState } from "../../api/onboarding";
import { Button, Field, Input } from "../../components/controls";
import { EmbeddedPageContext, PageHeader } from "../../components/page";
import { SectionCard } from "../../components/ui";
import { friendlyError } from "../../lib/errors";
import { ITEM_NAMES, ITEM_SECTIONS, stateLabel } from "../../lib/onboarding";
import { subjectSetupPath } from "../../lib/subjectSetup";
import GradeBoundariesPage from "../GradeBoundariesPage";
import SetupState from "../SetupState";
import { SectionBoundary } from "../SectionedPage";
import { SubjectSetupContext } from "../SubjectSetupContext";
import SyllabusUploadPage from "../SyllabusUploadPage";
import TaughtBeforeEditor from "../TaughtBeforeEditor";
import TeachingPlanInputs from "../TeachingPlanInputs";
import TeachingPlanView from "../TeachingPlanView";
import TimetableEditor from "../TimetableEditor";
import TimezoneSetting from "../TimezoneSetting";
import WeeklySendSetting from "../WeeklySendSetting";

/**
 * A new tutor's home until the first teaching plan is accepted (task 9.1c). It
 * replaces the old three-card welcome, which linked out to pages and enforced
 * nothing; what that welcome got right is kept: the order (syllabus, boundaries,
 * class, as the experience spec's cold start fixes it) and that every step is a
 * screen that already exists, composed here rather than rewritten.
 *
 * The server decides everything that matters (`SEC-10`): `in_flow` says this
 * page is shown at all, `next_step` says which step is open, and each step's
 * "done" is read from the same state. This file knows only the order of the
 * steps and which earlier step each one needs, which is presentation: nothing
 * here is stored, so a reload or tomorrow's visit reopens at `next_step`. Which
 * step the tutor has opened by hand is the only local state.
 *
 * Nothing outside this page is locked: the sidebar and every other page keep
 * working. The finish line (an accepted plan) is what hands the home back to the
 * dashboard, by the query changing, never by a redirect here.
 */

type StepId =
  | "account"
  | "syllabus"
  | "boundaries"
  | "defaults"
  | "guidance"
  | "timetable"
  | "taught_before"
  | "plan_inputs"
  | "plan_accepted";

type Marker = "Required" | "Optional" | "Can wait";

const STEPS: { id: StepId; name: string; marker: Marker }[] = [
  { id: "account", name: "Account basics", marker: "Can wait" },
  { id: "syllabus", name: "Syllabus", marker: "Required" },
  { id: "boundaries", name: "Grade boundaries", marker: "Can wait" },
  {
    id: "defaults",
    name: "Marking rules, mistake categories and weak-topic threshold",
    marker: "Can wait",
  },
  { id: "guidance", name: "Teaching guidance", marker: "Optional" },
  { id: "timetable", name: "Class and timetable", marker: "Required" },
  { id: "taught_before", name: "Where this class is up to", marker: "Required" },
  { id: "plan_inputs", name: "Plan details", marker: "Required" },
  { id: "plan_accepted", name: "Accept the teaching plan", marker: "Required" },
];

const SUBJECT_STEPS: StepId[] = ["boundaries", "defaults", "guidance", "timetable"];
const CLASS_STEPS: StepId[] = ["taught_before", "plan_inputs", "plan_accepted"];
const DEFAULT_ROWS = ["marking_rules", "mistake_categories", "weak_threshold"] as const;

const LINK = "inline-flex min-h-6 items-center text-sm text-brand-600 hover:underline";
const ROW = "flex flex-wrap items-center gap-x-3 gap-y-1 py-2";
const BADGE = "rounded-full border border-line px-2 py-0.5 text-xs text-ink-700";

const stepName = (id: StepId) => STEPS.find((s) => s.id === id)!.name;
const isStepId = (key: string | undefined): key is StepId =>
  key === "syllabus" || CLASS_STEPS.includes(key as StepId) || key === "timetable";

function CreateClassForm({ subjectId, subjectName }: { subjectId: number; subjectName: string }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const create = useMutation({
    // The same call and the same rule GroupsPage uses: a name, and a subject.
    mutationFn: () => createGroup(name, subjectId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["groups"] });
      void queryClient.invalidateQueries({ queryKey: ["today"] });
      void queryClient.invalidateQueries({ queryKey: ["onboarding"] });
    },
  });
  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (name.trim() && !create.isPending) create.mutate();
  }
  return (
    <SectionCard>
      <form onSubmit={onSubmit}>
        <p className="text-sm text-ink-500">
          This class is for {subjectName}. Add its weekly lessons once it exists.
        </p>
        <div className="mt-4 max-w-sm">
          <Field label="Class name">
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Chemistry — Year 10"
              required
            />
          </Field>
        </div>
        {create.isError && (
          <p role="alert" className="mt-3 text-sm text-risk-600">
            {friendlyError(create.error, "Couldn't create the class. Try again.")}
          </p>
        )}
        <div className="mt-5 flex justify-end">
          <Button type="submit" loading={create.isPending}>
            Create class
          </Button>
        </div>
      </form>
    </SectionCard>
  );
}

export default function OnboardingFlow({ data }: { data: OnboardingState }) {
  const next = data.next_step;
  const subject = data.subjects.find((s) => s.subject_id === next?.subject_id);
  const klass = subject?.classes.find((c) => c.group_id === next?.group_id);
  const syllabusDone = data.subjects.some((s) =>
    s.required.some((r) => r.key === "syllabus" && r.done),
  );
  const subjectReady = !!subject && subject.required.some((r) => r.key === "syllabus" && r.done);
  const classDone = (key: string) => klass?.steps.find((s) => s.key === key)?.done ?? false;
  const nextId: StepId | null = isStepId(next?.key) ? (next?.key as StepId) : null;

  const isDone = (id: StepId): boolean => {
    if (id === "syllabus") return syllabusDone;
    if (id === "timetable" || CLASS_STEPS.includes(id)) return classDone(id);
    return false;
  };
  /** What an undone earlier step costs: the line shown instead of opening. */
  const needs = (id: StepId): string | null => {
    if (SUBJECT_STEPS.includes(id) && !subjectReady) return "Add the syllabus first";
    if (id === "taught_before" && !(klass && classDone("timetable")))
      return "Add the class and its timetable first";
    if (id === "plan_inputs" && !(klass && classDone("taught_before")))
      return "Say where this class is up to first";
    if (id === "plan_accepted" && !(klass && classDone("plan_inputs")))
      return "Enter the plan details first";
    return null;
  };

  const [manual, setManual] = useState<StepId | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const [focusId, setFocusId] = useState<StepId | null>(null);
  const headings = useRef<Partial<Record<StepId, HTMLHeadingElement | null>>>({});
  const previousNext = useRef<StepId | null>(nextId);

  // When the server moves on to a different step, follow it: drop any step the
  // tutor opened by hand, say so once, and put focus on the new step's heading.
  // A change inside one step (a class appearing under "Class and timetable")
  // moves nothing.
  useEffect(() => {
    const before = previousNext.current;
    previousNext.current = nextId;
    if (before === nextId || nextId === null) return;
    setManual(null);
    setFocusId(nextId);
    setAnnouncement(
      before && isDone(before)
        ? `${stepName(before)} done. Next: ${stepName(nextId)}.`
        : `Next: ${stepName(nextId)}.`,
    );
    // isDone reads the same data this effect is keyed on.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nextId]);

  useEffect(() => {
    if (!focusId) return;
    headings.current[focusId]?.focus();
    setFocusId(null);
  }, [focusId]);

  const open: StepId | null = manual && !needs(manual) ? manual : nextId;

  const subjectContext = useMemo(
    () => ({ subjectId: subject?.subject_id ?? null, setSubjectId: () => {} }),
    [subject?.subject_id],
  );

  const stateText = (id: StepId): string | null => {
    if (id === "account") return stateLabel(data.account);
    if (id === "boundaries" || id === "guidance") {
      const item = subject?.items.find(
        (i) => i.key === (id === "guidance" ? "teaching_guidance" : id),
      );
      return item ? stateLabel(item) : null;
    }
    if (id === "defaults") {
      if (!subject) return null;
      const reviewed = DEFAULT_ROWS.filter((key) => {
        const state = subject.items.find((i) => i.key === key)?.state;
        return state === "reviewed" || state === "set_by_you";
      }).length;
      return `${reviewed} of ${DEFAULT_ROWS.length} reviewed`;
    }
    if (isDone(id)) return "Done";
    return id === nextId ? "Next" : "To do";
  };

  const suffix = (id: StepId): string | null => {
    if (SUBJECT_STEPS.includes(id) && subject) return subject.subject_name;
    if (CLASS_STEPS.includes(id) && klass) return klass.group_name;
    return null;
  };

  const panel = (id: StepId): ReactNode => {
    const embedded = `onboarding-embedded-${id}`;
    switch (id) {
      case "account":
        return (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <SetupState account />
            </div>
            <TimezoneSetting />
            <WeeklySendSetting />
          </div>
        );
      case "syllabus":
        return (
          <EmbeddedPageContext.Provider value={embedded}>
            <SyllabusUploadPage />
          </EmbeddedPageContext.Provider>
        );
      case "boundaries":
        return (
          <SubjectSetupContext.Provider value={subjectContext}>
            {subject?.items.find((i) => i.key === "boundaries")?.state === "not_set" && (
              <p className="mb-4 text-sm text-ink-700">
                Nothing is saved until you press the button below. Without boundaries there are no
                predicted grades for this subject.
              </p>
            )}
            <EmbeddedPageContext.Provider value={embedded}>
              <GradeBoundariesPage
                key={subject?.subject_id}
                acceptDefaultsLabel="Use these for now"
              />
            </EmbeddedPageContext.Provider>
          </SubjectSetupContext.Provider>
        );
      case "defaults":
        return (
          <SubjectSetupContext.Provider value={subjectContext}>
            <ul className="divide-y divide-line">
              {DEFAULT_ROWS.map((key) => (
                <li key={key} className={ROW}>
                  <span className="min-w-0 flex-1 text-sm text-ink-700">{ITEM_NAMES[key]}</span>
                  <SetupState item={key} />
                  <Link
                    to={subjectSetupPath(ITEM_SECTIONS[key], subject?.subject_id)}
                    className={LINK}
                    aria-label={`Change ${ITEM_NAMES[key]}, ${subject?.subject_name}`}
                  >
                    Change
                  </Link>
                </li>
              ))}
            </ul>
          </SubjectSetupContext.Provider>
        );
      case "guidance":
        return (
          <SubjectSetupContext.Provider value={subjectContext}>
            <div className={ROW}>
              <span className="min-w-0 flex-1 text-sm text-ink-700">
                {ITEM_NAMES.teaching_guidance}
              </span>
              <SetupState item="teaching_guidance" />
              <Link
                to={subjectSetupPath(ITEM_SECTIONS.teaching_guidance, subject?.subject_id)}
                className={LINK}
                aria-label={`Add teaching guidance, ${subject?.subject_name}`}
              >
                Add
              </Link>
            </div>
          </SubjectSetupContext.Provider>
        );
      case "timetable":
        if (!subject) return null;
        return klass ? (
          <TimetableEditor key={klass.group_id} groupId={klass.group_id} headingLevel={3} />
        ) : (
          <CreateClassForm subjectId={subject.subject_id} subjectName={subject.subject_name} />
        );
      case "taught_before":
        return klass && subject ? (
          <TaughtBeforeEditor
            key={klass.group_id}
            groupId={klass.group_id}
            subjectId={subject.subject_id}
          />
        ) : null;
      case "plan_inputs":
        return klass ? <TeachingPlanInputs key={klass.group_id} groupId={klass.group_id} /> : null;
      case "plan_accepted":
        return klass && subject ? (
          <TeachingPlanView
            key={klass.group_id}
            groupId={klass.group_id}
            subjectId={subject.subject_id}
          />
        ) : null;
    }
  };

  return (
    <div className="max-w-3xl">
      {/* Always mounted so a change is announced. */}
      <p role="status" className="sr-only">
        {announcement}
      </p>
      <PageHeader
        title="Set up your first class"
        documentTitle="Today"
        description="Steps marked Required come first. The rest can wait, and stays on your setup list on Today until you do it."
      />
      <ol className="space-y-3">
        {STEPS.map((step, index) => {
          const locked = needs(step.id);
          const isOpen = open === step.id && !locked;
          const headingId = `onboarding-step-${step.id}`;
          const panelId = `${headingId}-panel`;
          const reasonId = `${headingId}-reason`;
          const state = stateText(step.id);
          const where = suffix(step.id);
          return (
            <li key={step.id} className="rounded-xl border border-line bg-surface">
              <h2
                id={headingId}
                ref={(el) => {
                  headings.current[step.id] = el;
                }}
                tabIndex={-1}
                className="text-base focus:outline-none"
              >
                <button
                  type="button"
                  aria-expanded={isOpen}
                  aria-controls={panelId}
                  aria-disabled={locked ? true : undefined}
                  aria-describedby={locked ? reasonId : undefined}
                  onClick={() => {
                    if (locked) return;
                    setManual(isOpen ? null : step.id);
                    // Closing the server's own step leaves it open: there is
                    // always exactly one.
                  }}
                  className="flex min-h-11 w-full flex-wrap items-center gap-x-3 gap-y-1 rounded-xl px-5 py-4 text-left aria-disabled:cursor-not-allowed aria-disabled:text-ink-500"
                >
                  <span className="font-display text-sm text-ink-500">{index + 1}.</span>
                  <span className="min-w-0 font-semibold text-ink-900">
                    {step.name}
                    {where && <span className="font-normal text-ink-500"> · {where}</span>}
                  </span>
                  <span className={BADGE}>{step.marker}</span>
                  {state && <span className="text-sm font-normal text-ink-700">{state}</span>}
                  <span className="flex-1" />
                  {isOpen ? (
                    <ChevronUp aria-hidden className="h-4 w-4 text-ink-500" />
                  ) : (
                    <ChevronDown aria-hidden className="h-4 w-4 text-ink-500" />
                  )}
                </button>
              </h2>
              {locked && (
                <p id={reasonId} className="px-5 pb-4 text-sm text-ink-500">
                  {locked}
                </p>
              )}
              <div id={panelId} hidden={!isOpen} className="px-5 pb-5">
                {/* One editor crashing must not blank the home. */}
                {isOpen && <SectionBoundary label={step.name}>{panel(step.id)}</SectionBoundary>}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
