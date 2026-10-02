import { useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText } from "lucide-react";
import { generateReport, getReport, listReports, type Report } from "../api/reports";
import { friendlyError } from "../lib/errors";
import { formatDayMonth } from "../lib/timezones";
import { useMyTimezone } from "../auth/AuthContext";
import { Markdown } from "./Markdown";
import { Button, Select } from "./controls";
import { ErrorState, SectionSkeleton } from "./page";
import { EmptyState, SectionCard, SectionHeader } from "./ui";

type Audience = "student" | "tutor" | "parent";

const AUDIENCE_LABEL: Record<Audience, string> = {
  student: "Student report",
  tutor: "Tutor report",
  parent: "Parent report",
};

const STATUS: Record<Report["status"], { label: string; classes: string }> = {
  ready: { label: "Ready", classes: "bg-ok-100 text-ok-700" },
  generating: { label: "Writing…", classes: "bg-warn-100 text-warn-700" },
  failed: { label: "Couldn't be written", classes: "bg-risk-100 text-risk-600" },
};

/**
 * Reusable reports panel. `audiences` are the report types the current viewer
 * may generate/see (tutor: all; parent: parent; student: student).
 */
export function ReportsPanel({
  studentId,
  audiences,
  canGenerate = true,
}: {
  studentId: number;
  audiences: Audience[];
  canGenerate?: boolean;
}) {
  const queryClient = useQueryClient();
  const myZone = useMyTimezone();
  const selectId = useId();
  const reports = useQuery({
    queryKey: ["reports", studentId],
    queryFn: () => listReports(studentId),
    refetchInterval: (query) =>
      query.state.data?.some((r) => r.status === "generating") ? 3000 : false,
  });
  const [openId, setOpenId] = useState<number | null>(null);
  const [audience, setAudience] = useState(audiences[0]);

  const opened = useQuery({
    queryKey: ["report", openId],
    queryFn: () => getReport(openId!),
    enabled: openId !== null,
    refetchInterval: (query) => (query.state.data?.status === "generating" ? 3000 : false),
  });

  const generate = useMutation({
    mutationFn: () => generateReport({ student_id: studentId, audience }),
    onSuccess: (report) => {
      queryClient.invalidateQueries({ queryKey: ["reports", studentId] });
      setOpenId(report.id);
    },
  });

  // Who writes the reports, in the reader's own terms. A student and a parent
  // cannot generate one, so they are told where new ones come from instead.
  const description = canGenerate
    ? "Written summaries of progress for the student, their parent or you."
    : audiences[0] === "parent"
      ? "The tutor writes these. New ones appear here."
      : "Your tutor writes these. New ones appear here.";

  return (
    <SectionCard>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <SectionHeader title="Reports" description={description} />
        {canGenerate && (
          <div className="flex flex-wrap items-center gap-2">
            {audiences.length > 1 && (
              <>
                <label htmlFor={selectId} className="sr-only">
                  Who the report is for
                </label>
                <Select
                  id={selectId}
                  className="h-8 w-auto"
                  value={audience}
                  onChange={(e) => setAudience(e.target.value as Audience)}
                >
                  {audiences.map((a) => (
                    <option key={a} value={a}>
                      {AUDIENCE_LABEL[a]}
                    </option>
                  ))}
                </Select>
              </>
            )}
            <Button size="sm" loading={generate.isPending} onClick={() => generate.mutate()}>
              Generate report
            </Button>
          </div>
        )}
      </div>

      {/* The API refuses with a plain sentence when there is nothing to report
          (409), and friendlyError passes a 4xx sentence through. A mutation's
          error resets on the next mutate(), so a retry clears this without any
          state of our own. A student or parent, who cannot generate, is told
          where reports come from in the header instead. */}
      {generate.isError && (
        <p role="alert" className="mt-3 text-sm text-risk-600">
          {friendlyError(generate.error, "The report couldn't be started. Try again.")}
        </p>
      )}

      <div className="mt-4">
        {reports.isPending ? (
          <SectionSkeleton rows={2} label="Loading reports" />
        ) : reports.isError ? (
          <ErrorState
            title="Reports didn't load"
            error={reports.error}
            onRetry={() => void reports.refetch()}
          />
        ) : reports.data.length === 0 ? (
          <EmptyState
            title="No reports yet"
            hint={
              canGenerate
                ? "Generate one to summarise this student's progress."
                : "When one is written, it will appear here."
            }
          />
        ) : (
          <ul className="divide-y divide-line border-t border-line text-sm">
            {reports.data.map((r) => (
              <li key={r.id} className="flex items-center justify-between gap-3 py-2.5">
                <button
                  type="button"
                  onClick={() => setOpenId(r.id)}
                  aria-expanded={openId === r.id}
                  className="flex min-w-0 items-center gap-2 text-left font-medium text-brand-600 hover:text-brand-700"
                >
                  <FileText aria-hidden className="h-4 w-4 shrink-0" />
                  <span className="truncate">{r.title}</span>
                </button>
                <span className="flex shrink-0 items-center gap-3">
                  <span className="text-xs tabular-nums text-ink-500">
                    {formatDayMonth(new Date(r.created_at), myZone)}
                  </span>
                  <span
                    className={`rounded-md px-2 py-0.5 text-xs font-medium ${STATUS[r.status].classes}`}
                  >
                    {STATUS[r.status].label}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {openId !== null && (
        <div className="avora-enter mt-4 rounded-lg border border-line bg-canvas p-4">
          {opened.isPending ? (
            <SectionSkeleton rows={4} label="Loading the report" />
          ) : opened.isError ? (
            // A way out as well as a retry: only the loaded report carries the
            // Close button below, so a report that kept failing held the panel.
            <div className="space-y-2">
              <ErrorState
                title="This report didn't open"
                error={opened.error}
                onRetry={() => void opened.refetch()}
              />
              <div className="flex justify-end">
                <Button variant="ghost" size="sm" onClick={() => setOpenId(null)}>
                  Close
                </Button>
              </div>
            </div>
          ) : (
            <>
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm font-medium text-ink-900">{opened.data.title}</span>
                <Button variant="ghost" size="sm" onClick={() => setOpenId(null)}>
                  Close
                </Button>
              </div>
              <div className="mt-3">
                {opened.data.status === "generating" && (
                  <p className="text-sm text-ink-500" aria-live="polite">
                    Writing the report… this usually takes under a minute.
                  </p>
                )}
                {/* The stored error is a diagnostic for the operator, not a
                    sentence for this reader — it is never shown raw. */}
                {opened.data.status === "failed" && (
                  <p className="text-sm text-risk-600">
                    {canGenerate
                      ? "This report couldn't be written. Generate it again in a minute."
                      : "This report couldn't be written. Your tutor can try again."}
                  </p>
                )}
                {opened.data.status === "ready" && opened.data.content && (
                  <Markdown content={opened.data.content} />
                )}
              </div>
            </>
          )}
        </div>
      )}
    </SectionCard>
  );
}
