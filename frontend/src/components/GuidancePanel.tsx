import { Sparkles } from "lucide-react";
import type { ReactNode } from "react";
import { Markdown } from "./Markdown";

/*
 * Reusable surface for evidence-grounded guidance. The structure is fixed so
 * every recommendation in MANARA reads the same way:
 *
 *   Evidence  ->  Reasoning + Recommendation  ->  Next action
 *
 * Guidance is never framed as magic or detection: it is an experienced
 * academic mentor interpreting the educator's own evidence, and the educator
 * keeps the judgement. Callers supply the evidence note and the actions.
 */
export default function GuidancePanel({
  evidenceNote,
  body,
  pending,
  error,
  placeholder,
  action,
  secondaryActions,
}: {
  /** What the recommendation is grounded in, in the educator's own terms. */
  evidenceNote: string;
  /** Markdown reasoning + recommendation, once prepared. */
  body?: string;
  pending?: boolean;
  error?: string;
  /** Shown before anything has been prepared. */
  placeholder?: string;
  /** The single primary next action. */
  action?: ReactNode;
  secondaryActions?: ReactNode;
}) {
  return (
    <div className="rounded-lg border border-line bg-surface-muted p-4">
      <p className="flex items-start gap-2 text-xs text-ink-500">
        <Sparkles aria-hidden className="mt-px h-4 w-4 shrink-0 text-brand-600" />
        <span>{evidenceNote}</span>
      </p>

      <div className="mt-3">
        {pending ? (
          <div className="space-y-2" aria-hidden>
            <span className="block h-3 w-full animate-pulse rounded bg-line" />
            <span className="block h-3 w-5/6 animate-pulse rounded bg-line" />
            <span className="block h-3 w-2/3 animate-pulse rounded bg-line" />
          </div>
        ) : error ? (
          <p className="text-sm text-risk-600">{error}</p>
        ) : body ? (
          <div className="text-ink-700">
            <Markdown content={body} />
          </div>
        ) : (
          placeholder && <p className="text-sm text-ink-500">{placeholder}</p>
        )}
      </div>

      {(action || secondaryActions) && (
        <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2">
          {action}
          {secondaryActions}
        </div>
      )}
    </div>
  );
}
