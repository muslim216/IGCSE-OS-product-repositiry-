import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { PenLine } from "lucide-react";
import { listGroups, listSubjects } from "../api/groups";
import { listAssessments, type Assessment } from "../api/readiness";
import { buttonClasses } from "../components/controls";
import { ErrorState, PageHeader, SectionSkeleton, Skeleton } from "../components/page";
import { SubjectPicker, SubjectSection } from "../components/SubjectGroups";
import { EmptyState, SectionCard, SectionHeader } from "../components/ui";
import { useSubjectFilter } from "../lib/subjectGroups";
import { formatDayMonth } from "../lib/timezones";

/** What the API's lowercase `type` means, said the way a tutor would. */
const TYPE_LABEL: Record<string, string> = { mock: "Mock", test: "Class test" };

export default function MocksPage() {
  const groups = useQuery({ queryKey: ["groups"], queryFn: listGroups });
  const assessments = useQuery({ queryKey: ["assessments"], queryFn: () => listAssessments() });
  const subjects = useQuery({ queryKey: ["subjects"], queryFn: listSubjects });
  const filter = useSubjectFilter(assessments.data, subjects.isSuccess ? subjects.data : undefined);

  const recorded = (items: Assessment[]) => (
    <ul className="divide-y divide-line text-sm">
      {items.map((a) => (
        <li
          key={a.id}
          className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2.5"
        >
          <span className="font-medium text-ink-900">{a.title}</span>
          <span className="text-ink-500">
            {TYPE_LABEL[a.type] ?? "Assessment"} ·{" "}
            {/* A calendar date with no time: read in UTC, or a reader
                west of Greenwich sees the day before it was sat. */}
            {formatDayMonth(new Date(a.date), "UTC")} · {a.score_count}{" "}
            {a.score_count === 1 ? "score" : "scores"} entered
          </span>
        </li>
      ))}
    </ul>
  );

  return (
    <div>
      <PageHeader
        title="Mocks and tests"
        description="Enter a class's marks from a mock or class test, or look back at ones you've recorded."
      />

      <div className="space-y-8">
        <section className="space-y-3">
          <SectionHeader
            title="Enter marks"
            description="Choose the class that sat it."
            level="h2"
          />
          {groups.isLoading ? (
            <div
              role="status"
              aria-label="Loading your classes"
              className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3"
            >
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-28 w-full rounded-xl" />
              ))}
            </div>
          ) : groups.isError ? (
            <ErrorState error={groups.error} onRetry={() => groups.refetch()} />
          ) : groups.data?.length === 0 ? (
            <SectionCard>
              <EmptyState
                title="No classes yet."
                hint="Marks are entered for a class, so create one first."
                action={
                  <Link to="/tutor/classes" className={buttonClasses("secondary", "sm")}>
                    Go to Classes
                  </Link>
                }
              />
            </SectionCard>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {groups.data?.map((g) => (
                <SectionCard key={g.id} className="flex flex-col">
                  <p className="font-medium text-ink-900">{g.name}</p>
                  <p className="mt-1 text-sm text-ink-500">
                    {g.subject.name} · {g.subject.exam_board} {g.subject.code}
                  </p>
                  <Link
                    to={`/tutor/groups/${g.id}/mock`}
                    className={buttonClasses("secondary", "sm", "mt-4 self-start")}
                  >
                    <PenLine aria-hidden className="h-3.5 w-3.5" />
                    Enter marks
                  </Link>
                </SectionCard>
              ))}
            </div>
          )}
        </section>

        <SectionCard>
          <SectionHeader title="Recorded so far" level="h2" />
          <div className="mt-3">
            {assessments.isLoading ? (
              <SectionSkeleton rows={3} label="Loading recorded mocks and tests" />
            ) : assessments.isError ? (
              <ErrorState error={assessments.error} onRetry={() => assessments.refetch()} />
            ) : assessments.data?.length === 0 ? (
              <EmptyState
                title="No mocks or tests recorded yet."
                hint="Once you enter a class's marks, they're listed here."
              />
            ) : (
              <div className="space-y-5">
                {filter.showPicker && (
                  <SubjectPicker
                    groups={filter.groups}
                    value={filter.picked}
                    onChange={filter.setPicked}
                    noun={["mock or test", "mocks and tests"]}
                  />
                )}
                {filter.ready
                  ? filter.visible.map((g) => (
                      <SubjectSection key={g.id} subject={g.subject}>
                        {recorded(g.items)}
                      </SubjectSection>
                    ))
                  : recorded(assessments.data ?? [])}
              </div>
            )}
          </div>
        </SectionCard>
      </div>
    </div>
  );
}
