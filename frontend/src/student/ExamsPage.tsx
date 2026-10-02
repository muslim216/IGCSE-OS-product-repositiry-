import { useQuery } from "@tanstack/react-query";
import { myAssessmentScores } from "../api/readiness";
import { ErrorState, PageHeader, SectionSkeleton } from "../components/page";
import { EmptyState, SectionCard } from "../components/ui";
import { formatDayMonth } from "../lib/timezones";

/* Scores are shown in one neutral colour. They used to be coloured green /
   amber / red against a literal 70% and 50%, which UX-28 forbids: a band is a
   grade's position in the subject's own boundaries, and a single assessment
   score has no grade to place. The number and its percentage carry the meaning. */

export default function ExamsPage() {
  const scores = useQuery({ queryKey: ["my-assessments"], queryFn: myAssessmentScores });

  return (
    <div className="max-w-4xl space-y-6">
      <PageHeader
        title="Exams"
        description="Your mock and test scores, as entered by your tutor."
      />

      {scores.isPending ? (
        <SectionCard>
          <SectionSkeleton rows={3} label="Loading your exam scores" />
        </SectionCard>
      ) : scores.isError ? (
        <ErrorState
          title="Couldn't load your exam scores."
          error={scores.error}
          onRetry={() => void scores.refetch()}
        />
      ) : scores.data.length === 0 ? (
        <SectionCard>
          <EmptyState
            title="No exam scores recorded yet."
            hint="When your tutor enters a mock or test score, it will appear here."
          />
        </SectionCard>
      ) : (
        // `p-0!`, not `p-0`: SectionCard always carries `p-5`, and the two set
        // the same property in the same layer, so whichever Tailwind emits
        // last wins — `p-5` — and a plain `p-0` left the table inset from the
        // card's edges. The important modifier is the override that holds.
        <SectionCard className="overflow-x-auto p-0!">
          <table className="w-full text-sm">
            <caption className="sr-only">Your exam scores</caption>
            <thead className="border-b border-line text-left text-xs text-ink-500">
              <tr>
                <th scope="col" className="px-4 py-2.5 font-medium">
                  Assessment
                </th>
                <th scope="col" className="px-4 py-2.5 font-medium">
                  Subject
                </th>
                <th scope="col" className="px-4 py-2.5 font-medium">
                  Topic
                </th>
                <th scope="col" className="px-4 py-2.5 font-medium">
                  Date
                </th>
                <th scope="col" className="px-4 py-2.5 text-right font-medium">
                  Score
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {scores.data.map((s, i) => (
                <tr key={i}>
                  <th scope="row" className="px-4 py-2.5 text-left font-medium text-ink-900">
                    {s.title}
                  </th>
                  <td className="px-4 py-2.5 text-ink-700">{s.subject_name}</td>
                  <td className="px-4 py-2.5 text-ink-700">{s.topic_title ?? "Whole paper"}</td>
                  <td className="whitespace-nowrap px-4 py-2.5 tabular-nums text-ink-500">
                    {/* A calendar date, not an instant: read in UTC so a zone
                        west of Greenwich does not show it as the day before. */}
                    {formatDayMonth(new Date(`${s.date}T00:00:00Z`), "UTC")}
                  </td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-right tabular-nums text-ink-900">
                    {s.marks}/{s.max_marks} marks
                    <span className="ml-2 text-ink-500">{s.pct}%</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </SectionCard>
      )}
    </div>
  );
}
