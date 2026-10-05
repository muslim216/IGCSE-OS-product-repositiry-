import { memo, useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { usePresence } from "../lib/motion";

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
  level: Heading = "h3",
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  /** The heading level, for a page whose sections sit directly under its h1. */
  level?: "h2" | "h3";
}) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <div>
        <Heading className="text-[11px] font-semibold uppercase tracking-[0.14em] text-brand-600">
          {title}
        </Heading>
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
      className={`avora-card rounded-xl border border-line bg-surface p-5 shadow-[0_1px_2px_rgba(44,26,14,0.06)] ${className}`}
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

/**
 * Direction of travel, or nothing at all.
 *
 * `null` renders no arrow: one readiness point is not a trend, and "→" would
 * claim a movement that was never measured (UX-31, PROD-2). Shared because
 * three surfaces now pair a value with its direction — the class page, the
 * student's home and the parent screen — and a fourth copy of this rule is a
 * fourth chance for one of them to default `null` to "flat".
 */
export function DirectionMark({ direction }: { direction?: string | null }) {
  // The wire types direction as a string; anything but the three known values
  // renders nothing rather than defaulting to "flat" (PROD-2).
  if (direction !== "up" && direction !== "flat" && direction !== "down") return null;
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

/**
 * Holds its last render while `frozen`. Something animating out has usually
 * been closed by clearing the very state its contents were drawn from, so for
 * the length of the exit its parent is handing it "Remove undefined?" — this
 * keeps what was on screen when it started to leave.
 */
/* Something on its way out must not be operable. `pointer-events: none` in
   index.css stops the mouse, but focus is still inside: a second Enter on a
   dialog's confirm button during the exit would fire it again. `inert` takes
   the whole subtree out of focus and the accessibility tree. Spread rather
   than written as a prop because React 18 has no typed `inert`. */
const INERT = { inert: "" };

const Freeze = memo(
  function Freeze({ children }: { frozen: boolean; children: ReactNode }) {
    return <>{children}</>;
  },
  (_previous, next) => next.frozen,
);

/**
 * A panel that folds open and shut under a disclosure button. Its children are
 * mounted only while it is open (or folding shut), so a query inside one still
 * waits for the panel to be opened. `className` goes on the content itself,
 * inside the fold, so a top margin collapses with the panel instead of
 * lingering as a gap.
 */
export function Reveal({
  open,
  id,
  className = "",
  children,
}: {
  open: boolean;
  id?: string;
  className?: string;
  children: ReactNode;
}) {
  const { mounted, closing } = usePresence(open);
  if (!mounted) return null;
  return (
    <div
      id={id}
      className="avora-reveal"
      data-closing={closing || undefined}
      {...(closing ? INERT : null)}
    >
      <div>
        <div className={className}>
          <Freeze frozen={closing}>{children}</Freeze>
        </div>
      </div>
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
  // The latest onClose, read through a ref so the effect below runs once per
  // opening. Callers pass an inline function, so it is a new one on every
  // parent render; with it in the effect's deps, any background refetch above
  // the dialog re-ran the effect and pulled focus off the button the user was
  // on, back to the panel.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });

  useEffect(() => {
    if (!open) return;
    panelRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onCloseRef.current();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  const { mounted, closing } = usePresence(open);
  // Per dialog, not one shared id: a dialog that opens while another is still
  // fading out would otherwise be labelled by the outgoing one's title.
  const titleId = useId();
  if (!mounted) return null;
  // Rendered into <body>, not where it is written. Cards lift on hover with a
  // transform, and a transformed ancestor becomes the containing block for a
  // `fixed` descendant: a dialog left inside a card would shrink to that card
  // the moment the pointer — which is over the dialog, so over the card —
  // counted as hovering it.
  return createPortal(
    <div
      className="avora-overlay fixed inset-0 z-50 grid place-items-center p-4"
      data-closing={closing || undefined}
      {...(closing ? INERT : null)}
    >
      <button
        type="button"
        aria-label="Close dialog"
        className="avora-backdrop absolute inset-0 bg-ink-900/45"
        onClick={onClose}
        tabIndex={-1}
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="relative w-full max-w-md rounded-xl border border-line bg-surface p-6 shadow-lg outline-none"
      >
        <Freeze frozen={closing}>
          <h2 id={titleId} className="text-base font-semibold text-ink-900">
            {title}
          </h2>
          <div className="mt-4">{children}</div>
        </Freeze>
      </div>
    </div>,
    document.body,
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

  const { mounted, closing } = usePresence(message !== null);

  // In <body> for the same reason as Modal: a page may place `toast` inside a
  // card, and a hovered card would otherwise capture a `fixed` child.
  const toast = createPortal(
    <div
      aria-live="polite"
      className="pointer-events-none fixed inset-x-0 bottom-6 z-50 flex justify-center"
    >
      {mounted && (
        <p
          data-closing={closing || undefined}
          className="avora-toast rounded-lg border border-line bg-surface-muted px-4 py-2 text-sm text-ink-900 shadow-lg"
        >
          <Freeze frozen={closing}>{message}</Freeze>
        </p>
      )}
    </div>,
    document.body,
  );
  return { toast, showToast };
}
