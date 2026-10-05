import { useMemo } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { listSubjects } from "../api/groups";
import { Field, Select } from "../components/controls";
import { ErrorState, PageHeader, SectionSkeleton } from "../components/page";
import { EmptyState, SectionCard } from "../components/ui";
import GradeBoundariesPage from "./GradeBoundariesPage";
import MarkingRulesPage from "./MarkingRulesPage";
import MistakeCategoriesPage from "./MistakeCategoriesPage";
import PreferencesPage from "./PreferencesPage";
import { Section, SectionIndex, useFollowHash } from "./SectionedPage";
import SyllabusUploadPage from "./SyllabusUploadPage";
import { SubjectSetupContext } from "./SubjectSetupContext";
import TeachingGuidancePage from "./TeachingGuidancePage";

/**
 * Everything that belongs to a subject, in one place (9.3a, owner decision
 * 2026-10-05): the syllabus that creates it, its grade boundaries, teaching
 * guidance, marking rules, mistake categories and readiness preferences. These
 * were sections of Settings, each with its own "Subject" picker; the tutor now
 * chooses the subject once, at the top, and every section shows it.
 *
 * Each section is still its former page composed in whole (EmbeddedPageContext
 * turns its PageHeader into a section heading); they read the subject from
 * SubjectSetupContext. The choice lives in the URL (`?subject=<id>`) so a link
 * can open a given subject and a reload keeps it; an absent or unknown id means
 * the first subject. The Syllabus section is not filtered by it, because it is
 * how a subject is created.
 *
 * Sections are keyed on the subject so each remounts when it changes: an
 * unsaved draft, a chosen file or an open dialog belongs to the subject it was
 * made for and must not be carried onto another.
 */
export const SUBJECT_SETUP_SECTIONS = [
  { id: "syllabus", label: "Syllabus" },
  { id: "boundaries", label: "Grade boundaries" },
  { id: "teaching-guidance", label: "Teaching guidance" },
  { id: "marking-rules", label: "Marking rules" },
  { id: "mistake-categories", label: "Mistake categories" },
  { id: "preferences", label: "Preferences" },
] as const;

export default function SubjectSetupPage() {
  const navigate = useNavigate();
  const { hash } = useLocation();
  const [params] = useSearchParams();
  useFollowHash();

  // The same query and key every subject page already uses: one cached request.
  const subjects = useQuery({ queryKey: ["subjects"], queryFn: listSubjects });
  const list = subjects.data;

  const requested = Number(params.get("subject"));
  const subjectId =
    list && list.length > 0 ? (list.find((s) => s.id === requested) ?? list[0]).id : null;

  const context = useMemo(
    () => ({
      subjectId,
      // Replace, not push: stepping through subjects should not fill the
      // history. The hash is kept so the tutor stays on the section they are in.
      setSubjectId: (id: number) => navigate({ search: `?subject=${id}`, hash }, { replace: true }),
    }),
    [subjectId, navigate, hash],
  );

  // Failed and empty are different facts (PROD-2): a retry and a next step. In
  // both the subject sections have nothing to show, so only the Syllabus section
  // follows, which is where a subject comes from.
  const noSubjects = subjects.isError || (list !== undefined && list.length === 0);
  const sections = noSubjects ? SUBJECT_SETUP_SECTIONS.slice(0, 1) : SUBJECT_SETUP_SECTIONS;

  return (
    <div className="max-w-3xl">
      <PageHeader
        title="Subject setup"
        description="The syllabus, grade boundaries, teaching guidance, marking rules, mistake categories and readiness preferences for each subject you teach."
      />

      {subjects.isLoading ? (
        <div className="mb-6">
          <SectionSkeleton rows={1} label="Loading your subjects" />
        </div>
      ) : subjects.isError ? (
        <div className="mb-6">
          <ErrorState error={subjects.error} onRetry={() => subjects.refetch()} />
        </div>
      ) : list && list.length === 0 ? (
        <SectionCard className="mb-6">
          <EmptyState
            title="No subjects yet."
            hint="A subject is created by its syllabus. Add one in the Syllabus section below, then set up the rest here."
          />
        </SectionCard>
      ) : (
        <Field
          label="Subject"
          hint="Applies to every section except Syllabus."
          className="mb-6 max-w-sm"
        >
          <Select
            value={subjectId ?? ""}
            onChange={(e) => context.setSubjectId(Number(e.target.value))}
          >
            {list?.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.exam_board} {s.code})
              </option>
            ))}
          </Select>
        </Field>
      )}

      {sections.length > 1 && <SectionIndex label="Subject setup sections" sections={sections} />}

      <SubjectSetupContext.Provider value={context}>
        <div className="space-y-10">
          <Section id="syllabus" label="Syllabus">
            <SyllabusUploadPage />
          </Section>
          {!noSubjects && (
            <>
              <Section id="boundaries" label="Grade boundaries">
                <GradeBoundariesPage key={subjectId} />
              </Section>
              <Section id="teaching-guidance" label="Teaching guidance">
                <TeachingGuidancePage key={subjectId} />
              </Section>
              <Section id="marking-rules" label="Marking rules">
                <MarkingRulesPage key={subjectId} />
              </Section>
              <Section id="mistake-categories" label="Mistake categories">
                <MistakeCategoriesPage key={subjectId} />
              </Section>
              <Section id="preferences" label="Preferences">
                <PreferencesPage key={subjectId} />
              </Section>
            </>
          )}
        </div>
      </SubjectSetupContext.Provider>
    </div>
  );
}
