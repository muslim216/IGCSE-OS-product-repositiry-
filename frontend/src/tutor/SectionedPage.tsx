import { Component, Fragment, useEffect, type ErrorInfo, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { EmbeddedPageContext, ErrorState } from "../components/page";

/**
 * The machinery shared by the tutor's long, sectioned pages (Settings and
 * Subject setup): the in-page index, hash following with focus, a crash
 * boundary per section, and the labelled section wrapper. It lived in
 * SettingsPage until Subject setup became the second page built this way.
 */

/** How long after arriving the page keeps correcting its scroll position. The
 *  sections above the target load and grow after first paint, so the spot the
 *  browser scrolled to at mount is not where the section ends up. */
export const SETTLE_MS = 1500;
const POLL_MS = 100;
const USER_INPUT = ["wheel", "touchstart", "keydown", "pointerdown"] as const;

/** Scroll the hash target into view and keep doing so while it moves, until the
 *  settle window passes or the reader takes over by scrolling, touching or
 *  typing. Focus goes to the section once, so keyboard and screen-reader users
 *  land where the page scrolled to (WCAG 2.4.3). Returns a cleanup. */
export function followTarget(id: string): () => void {
  let lastTop: number | null = null;
  let focused = false;
  const started = Date.now();

  const stop = () => {
    window.clearInterval(timer);
    for (const type of USER_INPUT) window.removeEventListener(type, stop);
  };
  const align = () => {
    const el = document.getElementById(id);
    if (!el) return;
    const top = el.getBoundingClientRect().top;
    if (top !== lastTop) {
      lastTop = top;
      el.scrollIntoView?.();
    }
    if (!focused) {
      focused = true;
      el.focus({ preventScroll: true });
    }
  };
  const tick = () => {
    align();
    if (Date.now() - started >= SETTLE_MS) stop();
  };

  const timer = window.setInterval(tick, POLL_MS);
  for (const type of USER_INPUT) window.addEventListener(type, stop, { passive: true });
  align();
  return stop;
}

/** Follow the URL's hash to its section for as long as the page is on it. */
export function useFollowHash() {
  const { hash } = useLocation();
  useEffect(() => {
    if (!hash) return;
    return followTarget(decodeURIComponent(hash.slice(1)));
  }, [hash]);
}

/** The in-page index. `to` keeps the search string, so a link to a section does
 *  not drop the page's `?subject=`. */
export function SectionIndex({
  label,
  sections,
}: {
  label: string;
  sections: readonly { id: string; label: string }[];
}) {
  const { search } = useLocation();
  return (
    <nav aria-label={label} className="mb-8">
      <ul className="flex flex-wrap gap-x-5 gap-y-2 text-sm">
        {sections.map((section) => (
          <li key={section.id}>
            <Link
              to={{ search, hash: `#${section.id}` }}
              className="text-ink-700 hover:text-brand-600"
            >
              {section.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

/** One section crashing must not take the others down with it: they used to
 *  be separate pages, each with the page boundary to itself. The fallback keeps
 *  the section's heading (the section is labelled by it) and offers a retry that
 *  remounts only this section. */
export class SectionBoundary extends Component<
  { headingId?: string; label: string; children: ReactNode },
  { failed: boolean; attempt: number }
> {
  state = { failed: false, attempt: 0 };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(error, info.componentStack);
  }

  render() {
    if (this.state.failed) {
      return (
        <>
          {this.props.headingId ? (
            <h2 id={this.props.headingId} className="mb-6 text-xl leading-tight text-ink-900">
              {this.props.label}
            </h2>
          ) : null}
          <ErrorState
            title="This section didn't load"
            onRetry={() => this.setState((s) => ({ failed: false, attempt: s.attempt + 1 }))}
          />
        </>
      );
    }
    return <Fragment key={this.state.attempt}>{this.props.children}</Fragment>;
  }
}

const SECTION_CLASS = "scroll-mt-6 border-t border-line pt-8 focus:outline-none";

/** A section labelled by its own heading, which the embedded page's PageHeader
 *  renders with the id given through context. */
export function Section({
  id,
  label,
  children,
}: {
  id: string;
  label: string;
  children: ReactNode;
}) {
  const headingId = `${id}-heading`;
  return (
    <section id={id} tabIndex={-1} aria-labelledby={headingId} className={SECTION_CLASS}>
      <SectionBoundary headingId={headingId} label={label}>
        <EmbeddedPageContext.Provider value={headingId}>{children}</EmbeddedPageContext.Provider>
      </SectionBoundary>
    </section>
  );
}

/** A section whose body is not a former page, so the wrapper draws its heading. */
export function PlainSection({
  id,
  label,
  children,
}: {
  id: string;
  label: string;
  children: ReactNode;
}) {
  const headingId = `${id}-heading`;
  return (
    <section id={id} tabIndex={-1} aria-labelledby={headingId} className={SECTION_CLASS}>
      <h2 id={headingId} className="mb-6 text-xl leading-tight text-ink-900">
        {label}
      </h2>
      <SectionBoundary label={label}>{children}</SectionBoundary>
    </section>
  );
}
