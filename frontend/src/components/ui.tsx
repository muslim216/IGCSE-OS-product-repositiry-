import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

/* Shared Avora primitives. Generic by design: every component here takes its
   data via props so it can be reused across Students, Lessons, Homework,
   Assessments, Readiness, Reports and future organization-level pages. */

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}

export function InitialsAvatar({ name, size = "md" }: { name: string; size?: "sm" | "md" }) {
  const sizing = size === "sm" ? "h-7 w-7 text-[11px]" : "h-9 w-9 text-xs";
  return (
    <span
      aria-hidden
      className={`grid ${sizing} shrink-0 place-items-center rounded-full bg-brand-100 font-semibold text-brand-700`}
    >
      {initials(name)}
    </span>
  );
}

export function SectionHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <div>
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-brand-600">
          {title}
        </h3>
        {description && <p className="mt-0.5 text-xs text-ink-500">{description}</p>}
      </div>
      {action && <div className="shrink-0 text-sm">{action}</div>}
    </div>
  );
}

export function SectionCard({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-xl border border-line bg-surface p-5 shadow-[0_1px_2px_rgba(44,26,14,0.06)] ${className}`}
    >
      {children}
    </section>
  );
}

export type ReadinessStatus = "on_track" | "needs_attention" | "at_risk";

const STATUS_STYLES: Record<ReadinessStatus, { label: string; classes: string }> = {
  on_track: { label: "On track", classes: "bg-ok-100 text-ok-700" },
  needs_attention: { label: "Needs attention", classes: "bg-warn-100 text-warn-700" },
  at_risk: { label: "At risk", classes: "bg-risk-100 text-risk-600" },
};

export function StatusBadge({ status }: { status: ReadinessStatus }) {
  const { label, classes } = STATUS_STYLES[status];
  return (
    <span className={`inline-block rounded-md px-2 py-0.5 text-xs font-medium ${classes}`}>
      {label}
    </span>
  );
}

const BAR_FILLS: Record<ReadinessStatus, string> = {
  on_track: "bg-ok-700",
  needs_attention: "bg-warn-700",
  at_risk: "bg-risk-600",
};

/** Slim evidence bar. Decorative — the numeric score is always shown beside it. */
export function ReadinessBar({ score, status }: { score: number; status: ReadinessStatus }) {
  return (
    <span
      aria-hidden
      className="inline-block h-1 w-24 overflow-hidden rounded-full bg-canvas align-middle"
    >
      <span
        className={`block h-full rounded-full ${BAR_FILLS[status]}`}
        style={{ width: `${Math.max(0, Math.min(100, score))}%` }}
      />
    </span>
  );
}

/**
 * Direction of travel, or nothing at all.
 *
 * `null` renders no arrow: one readiness point is not a trend, and "→" would
 * claim a movement that was never measured (UX-31, PROD-2). Shared because
 * three surfaces now pair a value with its direction — the class page, the
 * student's home and the parent screen — and a fourth copy of this rule is a
 * fourth chance for one of them to default `null` to "flat".
 */
export function DirectionMark({ direction }: { direction: "up" | "flat" | "down" | null }) {
  if (direction === null) return null;
  const glyph = direction === "up" ? "↑" : direction === "down" ? "↓" : "→";
  const tone =
    direction === "up" ? "text-ok-700" : direction === "down" ? "text-risk-600" : "text-ink-500";
  // role="img" with an aria-label makes assistive technology announce the label
  // and ignore the glyph, which a screen reader would otherwise read as a symbol
  // name or skip entirely (CodeRabbit). The glyph is hidden as decorative.
  return (
    <span role="img" className={tone} aria-label={`Trending ${direction}`}>
      <span aria-hidden>{glyph}</span>
    </span>
  );
}

export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="py-6 text-center">
      <p className="text-sm font-medium text-ink-700">{title}</p>
      {hint && <p className="mx-auto mt-1 max-w-sm text-sm text-ink-500">{hint}</p>}
      {action && <div className="mt-3 text-sm">{action}</div>}
    </div>
  );
}

export function Modal({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    panelRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4">
      <button
        type="button"
        aria-label="Close dialog"
        className="absolute inset-0 bg-ink-900/45"
        onClick={onClose}
        tabIndex={-1}
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="avora-modal-title"
        tabIndex={-1}
        className="relative w-full max-w-md rounded-xl border border-line bg-surface p-6 shadow-lg outline-none"
      >
        <h2 id="avora-modal-title" className="text-base font-semibold text-ink-900">
          {title}
        </h2>
        <div className="mt-4">{children}</div>
      </div>
    </div>
  );
}

/** Subtle success confirmation: a small self-dismissing toast, never a banner. */
export function useToast(): { toast: ReactNode; showToast: (message: string) => void } {
  const [message, setMessage] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>();

  const showToast = useCallback((next: string) => {
    setMessage(next);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setMessage(null), 3500);
  }, []);

  useEffect(() => () => clearTimeout(timer.current), []);

  const toast = (
    <div
      aria-live="polite"
      className="pointer-events-none fixed inset-x-0 bottom-6 z-50 flex justify-center"
    >
      {message && (
        <p className="rounded-lg border border-line bg-surface-muted px-4 py-2 text-sm text-ink-900 shadow-lg">
          {message}
        </p>
      )}
    </div>
  );
  return { toast, showToast };
}
