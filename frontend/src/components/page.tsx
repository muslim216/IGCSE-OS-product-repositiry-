import {
  Component,
  createContext,
  useCallback,
  useContext,
  useRef,
  useEffect,
  type ErrorInfo,
  type ReactNode,
} from "react";
import { Link, useNavigate } from "react-router-dom";
import { AlertTriangle, ArrowLeft, Compass, RefreshCw } from "lucide-react";
import { Button, buttonClasses } from "./controls";
import { Modal } from "./ui";
import { AvoraGrain, AvoraLockup, GhostMark } from "./brand";
import { friendlyError } from "../lib/errors";

/* Page-level primitives: the title every screen opens with, and the states a
   screen can be in besides "loaded" — loading, failed, not found, crashed. */

const PRODUCT = "avora";

/** Names the browser tab after the page, so six open tabs are not six "avora"s. */
export function useDocumentTitle(title: string | null | undefined) {
  useEffect(() => {
    if (!title) return;
    const previous = document.title;
    document.title = `${title} · ${PRODUCT}`;
    return () => {
      document.title = previous;
    };
  }, [title]);
}

/**
 * Inside this provider a PageHeader is a section heading, not a page title: an
 * <h2>, no back link, no tab title. It lets a page that stands alone at its own
 * URL also be one section of a longer page (Settings) without a second copy of
 * its body and without two <h1>s. The value is the h2 id, so the host section
 * can name itself with aria-labelledby.
 */
export const EmbeddedPageContext = createContext<string | false>(false);

/**
 * For a page that already titles the embedded one itself (an onboarding step's
 * own h2): the embedded PageHeader leaves out its title when it is exactly this
 * text, and shows any other title (an upload's name) as an h3, one level below
 * the step's heading. `null`, the default, changes nothing anywhere.
 */
export const EmbeddedTitleOmittedContext = createContext<string | null>(null);

/**
 * The top of every page: an optional way back, the page's one <h1>, a sentence
 * saying what the page is for, and its primary actions. Also titles the tab.
 */
export function PageHeader({
  title,
  description,
  eyebrow,
  back,
  actions,
  meta,
  documentTitle,
}: {
  title: ReactNode;
  description?: ReactNode;
  eyebrow?: string;
  back?: { to: string; label: string };
  actions?: ReactNode;
  /** Badges or facts that belong beside the title (status, counts, dates). */
  meta?: ReactNode;
  /** Tab title when `title` is not plain text. */
  documentTitle?: string;
}) {
  const embedded = useContext(EmbeddedPageContext);
  const stepTitle = useContext(EmbeddedTitleOmittedContext);
  useDocumentTitle(embedded ? null : (documentTitle ?? (typeof title === "string" ? title : null)));
  if (embedded) {
    const omitted = stepTitle !== null && title === stepTitle;
    const Level = stepTitle !== null ? "h3" : "h2";
    return (
      <header className="mb-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div className="min-w-0">
            {!omitted && (
              <Level
                id={typeof embedded === "string" ? embedded : undefined}
                className="text-xl leading-tight text-ink-900"
              >
                {title}
              </Level>
            )}
            {meta && <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">{meta}</div>}
            {description && (
              <p className="mt-2 max-w-2xl text-[15px] leading-relaxed text-ink-500">
                {description}
              </p>
            )}
          </div>
          {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
        </div>
      </header>
    );
  }
  return (
    <header className="avora-enter mb-8">
      {back && (
        <Link
          to={back.to}
          className="mb-3 inline-flex items-center gap-1 text-sm text-ink-500 transition-colors hover:text-brand-600"
        >
          <ArrowLeft aria-hidden className="h-3.5 w-3.5" />
          {back.label}
        </Link>
      )}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          {eyebrow && <p className="avora-label mb-2">{eyebrow}</p>}
          <h1 className="text-[1.75rem] leading-tight text-ink-900 md:text-[2rem]">{title}</h1>
          {meta && <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">{meta}</div>}
          {description && (
            <p className="mt-2 max-w-2xl text-[15px] leading-relaxed text-ink-500">{description}</p>
          )}
        </div>
        {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </header>
  );
}

/** A placeholder shape in the colour of a raised row. */
export function Skeleton({ className = "" }: { className?: string }) {
  return <span aria-hidden className={`avora-skeleton block rounded-md ${className}`} />;
}

/**
 * What a page shows while its data loads: the outline of a header and a few
 * rows, announced once to assistive technology. Replaces the bare "Loading…"
 * text that most screens used to show.
 */
export function PageSkeleton({ rows = 4, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div role="status" aria-label={label}>
      <Skeleton className="mb-3 h-4 w-28" />
      <Skeleton className="h-8 w-72 max-w-full" />
      <Skeleton className="mt-3 h-4 w-96 max-w-full" />
      <div className="mt-10 space-y-3">
        {Array.from({ length: rows }, (_, i) => (
          <Skeleton key={i} className="h-16 w-full" />
        ))}
      </div>
    </div>
  );
}

/** A smaller loading block for one section of a page. */
export function SectionSkeleton({
  rows = 3,
  label = "Loading",
}: {
  rows?: number;
  label?: string;
}) {
  return (
    <div role="status" aria-label={label} className="space-y-2.5">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className={`h-5 ${i === rows - 1 ? "w-2/3" : "w-full"}`} />
      ))}
    </div>
  );
}

/** A failure the reader can do something about: what happened, and a retry. */
export function ErrorState({
  error,
  title = "This didn't load",
  onRetry,
}: {
  error?: unknown;
  title?: string;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex flex-col items-center rounded-xl border border-line bg-surface px-6 py-10 text-center"
    >
      <span className="grid h-10 w-10 place-items-center rounded-full bg-risk-100 text-risk-600">
        <AlertTriangle aria-hidden className="h-5 w-5" />
      </span>
      <p className="mt-4 font-display text-lg text-ink-900">{title}</p>
      <p className="mt-1 max-w-sm text-sm text-ink-500">{friendlyError(error)}</p>
      {onRetry && (
        <Button variant="secondary" size="sm" className="mt-5" onClick={onRetry}>
          <RefreshCw aria-hidden className="h-3.5 w-3.5" />
          Try again
        </Button>
      )}
    </div>
  );
}

/**
 * A designed "not found" inside the app: says plainly that the thing is gone
 * and offers a way back, instead of an endless "Loading…" or a silent bounce.
 */
export function NotFoundState({
  title = "We couldn't find that",
  body = "It may have been removed, or the link may be wrong.",
  back,
}: {
  title?: string;
  body?: string;
  back?: { to: string; label: string };
}) {
  useDocumentTitle("Not found");
  return (
    <div className="flex flex-col items-center px-6 py-16 text-center">
      <span className="grid h-12 w-12 place-items-center rounded-full bg-brand-50 text-brand-600">
        <Compass aria-hidden className="h-6 w-6" />
      </span>
      <h1 className="mt-5 text-2xl text-ink-900">{title}</h1>
      <p className="mt-2 max-w-sm text-ink-500">{body}</p>
      {back && (
        <Link to={back.to} className={buttonClasses("secondary", "md", "mt-6")}>
          <ArrowLeft aria-hidden className="h-4 w-4" />
          {back.label}
        </Link>
      )}
    </div>
  );
}

/** The public 404 — a whole page, with the brand around it, for any unknown URL. */
export function NotFoundPage() {
  useDocumentTitle("Page not found");
  const navigate = useNavigate();
  return (
    <div className="flex min-h-screen flex-col overflow-x-hidden bg-canvas">
      <AvoraGrain />
      <header className="mx-auto w-full max-w-5xl px-6 py-5">
        <Link to="/" aria-label="avora home" className="inline-block">
          <AvoraLockup />
        </Link>
      </header>
      <main className="relative mx-auto flex w-full max-w-5xl flex-1 items-center px-6">
        <GhostMark className="-right-24 top-1/2 -translate-y-1/2" />
        <div className="relative py-20">
          <p className="avora-label">Error 404</p>
          <h1 className="mt-4 max-w-xl text-4xl leading-tight text-ink-900 sm:text-5xl">
            This page doesn't exist.
          </h1>
          <p className="mt-4 max-w-md text-lg text-ink-500">
            The link may be old or mistyped. Nothing is lost — everything else is where you left it.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link to="/" className={buttonClasses("primary", "lg")}>
              Go to avora
            </Link>
            <Button variant="secondary" size="lg" onClick={() => navigate(-1)}>
              Go back
            </Button>
          </div>
        </div>
      </main>
    </div>
  );
}

/** A yes/no question in the product's own dialog, never the browser's grey box. */
export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel,
  danger = false,
  busy = false,
  focusCancel = false,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  body: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  busy?: boolean;
  /** Start with Cancel focused, so an Enter on opening cannot confirm. For
   *  actions that cannot be undone from the app. */
  focusCancel?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  // After Modal's own effect, which puts focus on the panel: a parent's effect
  // runs after its child's, so this one wins.
  useEffect(() => {
    if (open && focusCancel) cancelRef.current?.focus();
  }, [open, focusCancel]);
  // Escape and the backdrop are ways to cancel too, so they are shut while the
  // action is in flight: closing then would read as "cancelled" while the
  // request carries on and the action happens regardless.
  const dismiss = useCallback(() => {
    if (!busy) onCancel();
  }, [busy, onCancel]);
  return (
    <Modal open={open} onClose={dismiss} title={title}>
      <div className="text-sm leading-relaxed text-ink-700">{body}</div>
      <div className="mt-6 flex justify-end gap-2">
        <Button ref={cancelRef} variant="ghost" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <Button variant={danger ? "danger" : "primary"} loading={busy} onClick={onConfirm}>
          {confirmLabel}
        </Button>
      </div>
    </Modal>
  );
}

type ErrorBoundaryProps = {
  children: ReactNode;
  /** A new value clears a caught crash, so the children get another render. */
  resetKey?: unknown;
};
type ErrorBoundaryState = { failed: boolean; resetKey: unknown };

/**
 * Catches a render crash so one broken component shows a recoverable message
 * instead of a blank white page. AppShell passes the current navigation as
 * `resetKey`, so moving anywhere — another page, or the same page with a
 * different query — clears it.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { failed: false, resetKey: this.props.resetKey };

  static getDerivedStateFromError(): Partial<ErrorBoundaryState> {
    return { failed: true };
  }

  // Reset during render rather than after it (componentDidUpdate): when the
  // navigation that changed the key is itself the one that crashes, a reset
  // after the fallback commits would render the crash a second time.
  static getDerivedStateFromProps(
    props: ErrorBoundaryProps,
    state: ErrorBoundaryState,
  ): Partial<ErrorBoundaryState> | null {
    return props.resetKey === state.resetKey ? null : { failed: false, resetKey: props.resetKey };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Kept for the browser console until error reporting exists (see the
    // operations runbook); never shown to the reader.
    console.error(error, info.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div role="alert" className="flex flex-col items-center px-6 py-20 text-center">
        <span className="grid h-12 w-12 place-items-center rounded-full bg-risk-100 text-risk-600">
          <AlertTriangle aria-hidden className="h-6 w-6" />
        </span>
        <h1 className="mt-5 text-2xl text-ink-900">Something went wrong on this page</h1>
        <p className="mt-2 max-w-sm text-ink-500">
          Anything you had already saved is safe. Reload the page, and if it happens again let us
          know what you were doing.
        </p>
        <Button className="mt-6" onClick={() => window.location.reload()}>
          <RefreshCw aria-hidden className="h-4 w-4" />
          Reload
        </Button>
      </div>
    );
  }
}
