import { useEffect, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
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

function Section({ id, label, children }: { id: string; label: string; children: ReactNode }) {
  return (
    <section id={id} aria-label={label} className="scroll-mt-6 border-t border-line pt-8">
      {children}
    </section>
  );
}

export default function SettingsPage() {
  const { hash } = useLocation();

  // The browser only scrolls to a #fragment present at load; this page is
  // reached by client-side redirect, so do it by hand once the section exists.
  useEffect(() => {
    if (!hash) return;
    document.getElementById(decodeURIComponent(hash.slice(1)))?.scrollIntoView?.();
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
              <a href={`#${section.id}`} className="text-ink-700 hover:text-brand-600">
                {section.label}
              </a>
            </li>
          ))}
        </ul>
      </nav>
      <div className="space-y-10">
        <EmbeddedPageContext.Provider value={true}>
          <Section id="teaching-guidance" label="Teaching guidance">
            <TeachingGuidancePage />
          </Section>
          <Section id="marking-rules" label="AI marking agreement">
            <MarkingRulesPage />
          </Section>
          <Section id="boundaries" label="Grade boundaries">
            <GradeBoundariesPage />
          </Section>
          <Section id="mistake-categories" label="Mistake categories">
            <MistakeCategoriesPage />
          </Section>
          <Section id="preferences" label="Preferences">
            <PreferencesPage />
          </Section>
        </EmbeddedPageContext.Provider>
        <Section id="account" label="Account and integrations">
          <h2 className="mb-6 text-xl leading-tight text-ink-900">Account and integrations</h2>
          <div className="space-y-6">
            <TimezoneSetting />
            <MyTimezoneSetting />
            <CustomCriteriaSetting />
            <IntegrationsSetting />
          </div>
        </Section>
      </div>
    </div>
  );
}
