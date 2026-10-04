import { useEffect, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import TimezoneSetting from "./TimezoneSetting";
import CustomCriteriaSetting from "./CustomCriteriaSetting";
import IntegrationsSetting from "./IntegrationsSetting";
import TeachingGuidancePage from "./TeachingGuidancePage";
import MarkingRulesPage from "./MarkingRulesPage";
import GradeBoundariesPage from "./GradeBoundariesPage";
import MistakeCategoriesPage from "./MistakeCategoriesPage";
import PreferencesPage from "./PreferencesPage";
import MyTimezoneSetting from "../components/MyTimezoneSetting";
import { EmbeddedPageContext, PageHeader } from "../components/page";

/**
 * Everything the tutor configures lives here, as sections of one page. It used
 * to be five separate pages parked on the Library shelf beside the teaching
 * material; the owner wanted setup in one place and material in another.
 *
 * Each former page is composed in whole, not rewritten: EmbeddedPageContext
 * turns its PageHeader into a section heading, so its body is unchanged and the
 * old URL (which now redirects to `/tutor/settings#<id>`) has one implementation.
 *
 * This was `ClassroomSettingsPage` until 0.5 (AV-58) hid the Google Classroom
 * surface; the account half (time zones, criteria, integrations) stays last.
 */
export const SETTINGS_SECTIONS = [
  { id: "teaching-guidance", label: "Teaching guidance" },
  { id: "marking-rules", label: "AI marking agreement" },
  { id: "boundaries", label: "Grade boundaries" },
  { id: "mistake-categories", label: "Mistake categories" },
  { id: "preferences", label: "Preferences" },
  { id: "account", label: "Account and integrations" },
] as const;

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

/** A section labelled by its own heading, which the embedded page's PageHeader
 *  renders with the id given through context. */
function Section({ id, children }: { id: string; children: ReactNode }) {
  const headingId = `${id}-heading`;
  return (
    <section
      id={id}
      tabIndex={-1}
      aria-labelledby={headingId}
      className="scroll-mt-6 border-t border-line pt-8 focus:outline-none"
    >
      <EmbeddedPageContext.Provider value={headingId}>{children}</EmbeddedPageContext.Provider>
    </section>
  );
}

export default function SettingsPage() {
  const { hash } = useLocation();

  useEffect(() => {
    if (!hash) return;
    return followTarget(decodeURIComponent(hash.slice(1)));
  }, [hash]);

  return (
    <div className="max-w-3xl">
      <PageHeader
        title="Settings"
        description="How marking, grades and readiness work for you, and the time zones, criteria and integrations behind your account."
      />
      <nav aria-label="Settings sections" className="mb-8">
        <ul className="flex flex-wrap gap-x-5 gap-y-2 text-sm">
          {SETTINGS_SECTIONS.map((section) => (
            <li key={section.id}>
              <Link to={`#${section.id}`} className="text-ink-700 hover:text-brand-600">
                {section.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      <div className="space-y-10">
        <Section id="teaching-guidance">
          <TeachingGuidancePage />
        </Section>
        <Section id="marking-rules">
          <MarkingRulesPage />
        </Section>
        <Section id="boundaries">
          <GradeBoundariesPage />
        </Section>
        <Section id="mistake-categories">
          <MistakeCategoriesPage />
        </Section>
        <Section id="preferences">
          <PreferencesPage />
        </Section>
        <section
          id="account"
          tabIndex={-1}
          aria-labelledby="account-heading"
          className="scroll-mt-6 border-t border-line pt-8 focus:outline-none"
        >
          <h2 id="account-heading" className="mb-6 text-xl leading-tight text-ink-900">
            Account and integrations
          </h2>
          <div className="space-y-6">
            <TimezoneSetting />
            <MyTimezoneSetting />
            <CustomCriteriaSetting />
            <IntegrationsSetting />
          </div>
        </section>
      </div>
    </div>
  );
}
