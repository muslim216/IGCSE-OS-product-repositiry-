import {
  ArrowRightCircle,
  FileCheck2,
  Lightbulb,
  PenLine,
  Presentation,
  type LucideIcon,
} from "lucide-react";

/* The MANARA learning loop, rendered as a quiet process strip. Reusable on any
   page that needs to place the educator inside the workflow. Descriptive only —
   it never asserts anything about a particular learner's data. */

const STEPS: { label: string; icon: LucideIcon; emphasis?: boolean }[] = [
  { label: "Teach", icon: Presentation },
  { label: "Practice", icon: PenLine },
  { label: "Evidence", icon: FileCheck2 },
  { label: "Insight", icon: Lightbulb, emphasis: true },
  { label: "Next step", icon: ArrowRightCircle, emphasis: true },
];

export default function LearningLoopStrip() {
  return (
    <ol className="flex items-start overflow-x-auto pb-1">
      {STEPS.map((step, i) => (
        <li key={step.label} className="flex shrink-0 items-center">
          <div className="flex w-24 flex-col items-center gap-1.5">
            <span
              className={`grid h-9 w-9 place-items-center rounded-full border ${
                step.emphasis
                  ? "border-brand-600 bg-brand-100 text-brand-500"
                  : "border-line bg-surface text-ink-500"
              }`}
            >
              <step.icon aria-hidden className="h-[18px] w-[18px]" />
            </span>
            <span
              className={`text-xs ${step.emphasis ? "font-medium text-brand-500" : "text-ink-500"}`}
            >
              {step.label}
            </span>
          </div>
          {i < STEPS.length - 1 && <span aria-hidden className="mt-4 h-px w-6 bg-line sm:w-10" />}
        </li>
      ))}
    </ol>
  );
}
