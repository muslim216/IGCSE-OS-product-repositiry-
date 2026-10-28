import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { listGroups } from "../api/groups";
import {
  getMock,
  mockMarkSchemePath,
  mockPaperPath,
  mockResults,
  retryMock,
  setMockClass,
  type MockResult,
} from "../api/mocks";
import { AuthFileLink } from "../components/AuthFile";
import { Button, Field, Select } from "../components/controls";
import { ConfirmDialog, ErrorState, PageHeader, SectionSkeleton } from "../components/page";
import { EmptyState, SectionCard, SectionHeader } from "../components/ui";
import { friendlyError } from "../lib/errors";
import { formatDuration } from "../lib/schedule";
import { formatDayMonth } from "../lib/timezones";
import { mockStatusLine } from "./MarkedMocks";

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** The server's status words, said the way a tutor would. */
const RESULT_STATUS: Record<MockResult["status"], string> = {
  not_started: "Not started",
  in_progress: "Sitting it now",
  handed_in: "Handed in",
  marked: "Marked by the AI",
  final: "Marked",
};

/** A mark is shown only when it is final. Anything else says why there is
 *  none, and never as 0 (PROD-2, UX-19). */
function marksCell(r: MockResult): string {
  if (r.status === "final" && r.marks_awarded !== null && r.marks_awarded !== undefined) {
    return r.marks_available ? `${r.marks_awarded}/${r.marks_available}` : String(r.marks_awarded);
  }
  if (r.status === "marked") return "Waiting for your review";
  if (r.status === "handed_in") return "Being marked by the AI";
  return "Not handed in";
}

function Results({ mockId }: { mockId: number }) {
  const results = useQuery({
    queryKey: ["mock-results", mockId],
    queryFn: () => mockResults(mockId),
  });
  return (
    <SectionCard>
      <SectionHeader title="Results" level="h2" />
      <div className="mt-3">
        {results.isPending ? (
          <SectionSkeleton rows={3} label="Loading the results" />
        ) : results.isError ? (
          <ErrorState error={results.error} onRetry={() => results.refetch()} />
        ) : results.data.length === 0 ? (
          <EmptyState
            title="No students to show yet."
            hint="Open the mock to a class and its students are listed here."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-ink-500">
                <tr>
                  <th scope="col" className="py-2 pr-4 font-medium">
                    Student
                  </th>
                  <th scope="col" className="py-2 pr-4 font-medium">
                    Status
                  </th>
                  <th scope="col" className="py-2 pr-4 font-medium">
                    Handed in
                  </th>
                  <th scope="col" className="py-2 pr-4 font-medium">
                    Marks
                  </th>
                  <th scope="col" className="py-2 font-medium">
                    <span className="sr-only">Review</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {results.data.map((r) => (
                  <tr key={r.student_id}>
                    <th scope="row" className="py-2.5 pr-4 font-medium text-ink-900">
                      {r.student_name}
                    </th>
                    <td className="py-2.5 pr-4 text-ink-700">{RESULT_STATUS[r.status]}</td>
                    <td className="py-2.5 pr-4 text-ink-700">
                      {r.submitted_at ? (
                        <>
                          {formatDayMonth(new Date(r.submitted_at))}
                          {r.measured_minutes != null && (
                            <span className="text-ink-500">
                              {" "}
                              · {formatDuration(r.measured_minutes)}
                            </span>
                          )}
                          {r.submitted_late && (
                            <span className="ml-2 rounded-full bg-warn-100 px-2 py-0.5 text-xs font-medium text-warn-700">
                              Late
                            </span>
                          )}
                        </>
                      ) : (
                        <span className="text-ink-500">—</span>
                      )}
                    </td>
                    <td className="py-2.5 pr-4 tabular-nums text-ink-900">{marksCell(r)}</td>
                    <td className="py-2.5">
                      {r.submission_id != null && (
                        <Link
                          to={`/tutor/submissions/${r.submission_id}`}
                          className="font-medium text-brand-600 hover:text-brand-700"
                        >
                          Review<span className="sr-only"> {r.student_name}&apos;s work</span>
                        </Link>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </SectionCard>
  );
}

export default function MockPage() {
  const { mockId } = useParams();
  const id = Number(mockId);
  const queryClient = useQueryClient();
  const mock = useQuery({
    queryKey: ["mock", id],
    queryFn: () => getMock(id),
    enabled: Number.isFinite(id),
    refetchInterval: (query) => (query.state.data?.status === "extracting" ? 3000 : false),
  });
  const groups = useQuery({ queryKey: ["groups"], queryFn: listGroups });

  const [changing, setChanging] = useState(false);
  const [picked, setPicked] = useState("");
  const [confirming, setConfirming] = useState(false);

  function refresh() {
    queryClient.invalidateQueries({ queryKey: ["mock", id] });
    queryClient.invalidateQueries({ queryKey: ["mocks"] });
    queryClient.invalidateQueries({ queryKey: ["mock-results", id] });
  }

  const open = useMutation({
    mutationFn: () => setMockClass(id, Number(picked)),
    onSuccess: () => {
      setConfirming(false);
      setChanging(false);
      setPicked("");
      refresh();
    },
    // The 409 ("already has submissions") is shown inside the dialog; the page
    // behind it is refreshed in case it was simply out of date.
    onError: refresh,
  });

  const retry = useMutation({
    mutationFn: () => retryMock(id),
    onSuccess: refresh,
    onError: refresh,
  });

  if (mock.isPending) return <SectionSkeleton rows={4} label="Loading the mock" />;
  if (mock.isError) return <ErrorState error={mock.error} onRetry={() => mock.refetch()} />;

  const m = mock.data;
  const back = { to: "/tutor/mocks", label: "Mocks" };
  // Only the tutor's classes teaching this subject (the server refuses others).
  const classes = (groups.data ?? []).filter((g) => g.subject.id === m.subject_id);
  const current = groups.data?.find((g) => g.id === m.group_id);
  const chosen = classes.find((g) => String(g.id) === picked);
  const untagged = m.questions.filter((q) => q.topics.length === 0).length;
  const choosing = m.group_id === null || changing;

  return (
    <div>
      <PageHeader
        title={m.title}
        back={back}
        description={
          mockStatusLine(m) +
          (m.duration_minutes ? ` · ${formatDuration(m.duration_minutes)} allowed` : " · Untimed")
        }
      />

      <div className="space-y-6">
        {m.status === "extraction_failed" && (
          <SectionCard>
            <p role="alert" className="text-sm text-risk-600">
              Couldn&apos;t read this paper.
            </p>
            {m.extraction_error && (
              <p className="mt-1 text-sm text-ink-500">{m.extraction_error}</p>
            )}
            {retry.isError && (
              <p role="alert" className="mt-2 text-sm text-risk-600">
                {friendlyError(retry.error, "That didn't start. Try again.")}
              </p>
            )}
            <Button
              className="mt-3"
              variant="secondary"
              size="sm"
              loading={retry.isPending}
              onClick={() => retry.mutate()}
            >
              Try again
            </Button>
          </SectionCard>
        )}

        <SectionCard>
          <SectionHeader title="What the AI read" level="h2" />
          <div className="mt-3 space-y-3 text-sm">
            <div className="flex flex-wrap gap-4">
              <AuthFileLink path={mockPaperPath(m.id)} label="Paper" />
              {m.mark_scheme_name ? (
                <AuthFileLink path={mockMarkSchemePath(m.id)} label="Mark scheme" />
              ) : (
                <span className="text-ink-500">No mark scheme</span>
              )}
            </div>
            {m.status === "extracting" ? (
              <p className="text-ink-500">Reading the paper…</p>
            ) : m.questions.length === 0 ? (
              <p className="text-ink-500">No questions were read from this paper.</p>
            ) : (
              <>
                <p className="text-ink-500">
                  The questions can&apos;t be edited here. If the AI misread the paper, upload it
                  again as a new mock.
                </p>
                {untagged > 0 && (
                  <p className="text-warn-700">
                    {plural(untagged, "question isn't", "questions aren't")} linked to a topic, so{" "}
                    {untagged === 1 ? "its marks count" : "their marks count"} towards no topic
                    score.
                  </p>
                )}
                <ol className="space-y-1.5">
                  {m.questions.map((q) => (
                    <li key={q.id} className="flex flex-wrap gap-x-2 text-ink-500">
                      <span className="font-medium text-ink-700">Q{q.number}</span>
                      <span>{plural(q.max_marks, "mark", "marks")}</span>
                      <span>
                        ·{" "}
                        {q.topics.length > 0 ? q.topics.map((t) => t.title).join(", ") : "No topic"}
                      </span>
                    </li>
                  ))}
                </ol>
              </>
            )}
          </div>
        </SectionCard>

        {m.status === "published" && (
          <SectionCard>
            <SectionHeader title="Open to a class" level="h2" />
            <div className="mt-3 space-y-3 text-sm">
              {m.group_id !== null && !changing ? (
                <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                  <p className="text-ink-900">Open to {current?.name ?? "a class"}</p>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => {
                      open.reset();
                      setChanging(true);
                    }}
                  >
                    Change class
                  </Button>
                </div>
              ) : (
                choosing && (
                  <>
                    <p className="text-ink-500">
                      {m.group_id === null
                        ? "Not open to a class yet. Students don't see this mock until you open it."
                        : "You can change the class until a student has started."}
                    </p>
                    <div className="flex flex-wrap items-end gap-3">
                      <Field label="Class" className="min-w-[14rem]">
                        <Select value={picked} onChange={(e) => setPicked(e.target.value)}>
                          <option value="">Choose a class</option>
                          {classes.map((g) => (
                            <option key={g.id} value={g.id}>
                              {g.name}
                            </option>
                          ))}
                        </Select>
                      </Field>
                      <Button
                        disabled={!picked}
                        onClick={() => {
                          open.reset();
                          setConfirming(true);
                        }}
                      >
                        Open to class
                      </Button>
                      {changing && (
                        <Button variant="ghost" onClick={() => setChanging(false)}>
                          Cancel
                        </Button>
                      )}
                    </div>
                    {classes.length === 0 && groups.isSuccess && (
                      <p className="text-ink-500">You have no class for this subject yet.</p>
                    )}
                  </>
                )
              )}
            </div>
          </SectionCard>
        )}

        {m.group_id !== null && <Results mockId={m.id} />}
      </div>

      <ConfirmDialog
        open={confirming}
        title="Open this mock to the class?"
        body={
          <>
            <p>Students in {chosen?.name ?? "the class"} will see this mock now.</p>
            {open.isError && (
              <p role="alert" className="mt-3 text-risk-600">
                {friendlyError(open.error, "That didn't work. Try again.")}
              </p>
            )}
          </>
        }
        confirmLabel="Open to class"
        busy={open.isPending}
        onConfirm={() => open.mutate()}
        onCancel={() => setConfirming(false)}
      />
    </div>
  );
}
