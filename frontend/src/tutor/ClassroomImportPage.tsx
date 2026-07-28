import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  courseRoster,
  getImportRun,
  googleAccount,
  linkCourse,
  listGoogleCourses,
  listGoogleCoursework,
  saveRoster,
  startImport,
  type ImportRun,
} from "../api/googleClassroom";
import { listGroupAssignments } from "../api/homework";
import { useGroupContext } from "./GroupLayout";
import { ApiError } from "../api/client";
import { Badge, Button, Card, CardBody, CardHeader, EmptyState, Select } from "../ui";

const OUTCOME_LABEL: Record<string, { tone: "ready" | "caution" | "risk"; text: string }> = {
  imported: { tone: "ready", text: "Imported" },
  skipped_unmapped: { tone: "caution", text: "Student not linked" },
  skipped_not_turned_in: { tone: "caution", text: "Not turned in" },
  skipped_no_attachments: { tone: "caution", text: "No attachments" },
  skipped_finalized: { tone: "caution", text: "Already marked here" },
  unsupported_files: { tone: "risk", text: "Files couldn't be used" },
  failed: { tone: "risk", text: "Failed" },
};

export default function ClassroomImportPage() {
  const { group, groupId } = useGroupContext();
  const queryClient = useQueryClient();

  const account = useQuery({ queryKey: ["google-account"], queryFn: googleAccount });
  const connected = account.data?.connected && account.data.status === "connected";

  const courses = useQuery({
    queryKey: ["google-courses"],
    queryFn: listGoogleCourses,
    enabled: !!connected,
  });
  const assignments = useQuery({
    queryKey: ["assignments", groupId],
    queryFn: () => listGroupAssignments(groupId),
  });

  const linkedCourse = courses.data?.find((c) => c.linked_group_id === groupId);
  const [courseId, setCourseId] = useState<string>("");
  const activeCourseId = linkedCourse?.course_id ?? courseId;
  const [linkId, setLinkId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [runId, setRunId] = useState<number | null>(null);
  const [mappings, setMappings] = useState<Record<string, number | "">>({});
  const [assignmentFor, setAssignmentFor] = useState<Record<string, number | "">>({});

  const link = useMutation({
    mutationFn: () => linkCourse(activeCourseId, groupId),
    onSuccess: (data) => {
      setLinkId(data.id);
      queryClient.invalidateQueries({ queryKey: ["google-courses"] });
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });

  const roster = useQuery({
    queryKey: ["google-roster", linkId],
    queryFn: () => courseRoster(linkId!),
    enabled: linkId !== null,
  });

  const coursework = useQuery({
    queryKey: ["google-coursework", activeCourseId],
    queryFn: () => listGoogleCoursework(activeCourseId),
    enabled: !!activeCourseId && !!connected,
  });

  const persistRoster = useMutation({
    mutationFn: () =>
      saveRoster(
        linkId!,
        (roster.data?.classroom_students ?? []).map((s) => ({
          google_user_id: s.google_user_id,
          student_id:
            mappings[s.google_user_id] === ""
              ? null
              : ((mappings[s.google_user_id] ?? s.mapped_student_id ?? null) as number | null),
        })),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["google-roster", linkId] }),
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });

  const runImport = useMutation({
    mutationFn: (courseworkId: string) =>
      startImport(linkId!, courseworkId, assignmentFor[courseworkId] as number),
    onSuccess: (run) => setRunId(run.id),
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });

  const run = useQuery({
    queryKey: ["google-import-run", runId],
    queryFn: () => getImportRun(runId!),
    enabled: runId !== null,
    // Downloading attachments takes a while; poll while it's in flight.
    refetchInterval: (query) => {
      const status = (query.state.data as ImportRun | undefined)?.status;
      return status === "pending" || status === "running" ? 2500 : false;
    },
  });

  if (!connected) {
    return (
      <EmptyState
        icon="🔗"
        title="Connect Google Classroom first"
        description="Once your Google account is connected you can link this class to a Classroom course and pull in work students hand in there."
        action={{ label: "Go to Google Classroom settings", to: "/tutor/integrations" }}
      />
    );
  }

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <Link
          to={`/tutor/groups/${groupId}/homework`}
          className="text-sm text-brand-600 hover:underline"
        >
          ← All homework
        </Link>
        <h3 className="mt-1 font-semibold text-slate-900">Import from Google Classroom</h3>
        <p className="text-sm text-slate-500">
          Pull work students turned in on Classroom into {group.name} for AI marking.
        </p>
      </div>

      {error && <p className="text-sm text-risk-600">{error}</p>}

      <Card>
        <CardHeader title="1. Pick the Classroom course" />
        <CardBody className="flex flex-wrap items-end gap-3">
          <Select
            className="max-w-sm"
            value={activeCourseId}
            onChange={(e) => setCourseId(e.target.value)}
            aria-label="Classroom course"
          >
            <option value="">Choose a course…</option>
            {courses.data?.map((c) => (
              <option key={c.course_id} value={c.course_id}>
                {c.name}
                {c.section ? ` · ${c.section}` : ""}
              </option>
            ))}
          </Select>
          <Button
            onClick={() => link.mutate()}
            disabled={!activeCourseId || link.isPending}
          >
            {linkedCourse ? "Re-link" : "Link to this class"}
          </Button>
          {linkedCourse && <Badge tone="ready">Linked to {linkedCourse.name}</Badge>}
        </CardBody>
      </Card>

      {roster.data && (
        <Card>
          <CardHeader
            title="2. Match students"
            description="Suggestions are pre-filled but never saved on their own — a wrong match would file one student's marks against another."
            actions={
              <Button onClick={() => persistRoster.mutate()} disabled={persistRoster.isPending}>
                {persistRoster.isPending ? "Saving…" : "Save matches"}
              </Button>
            }
          />
          <CardBody className="space-y-3">
            {roster.data.classroom_students.map((s) => (
              <div key={s.google_user_id} className="flex flex-wrap items-center gap-3">
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm text-slate-800">
                    {s.google_name ?? s.google_user_id}
                  </span>
                  {s.google_email && (
                    <span className="text-xs text-slate-500">{s.google_email}</span>
                  )}
                </span>
                <Select
                  className="max-w-56"
                  aria-label={`App account for ${s.google_name ?? s.google_user_id}`}
                  value={
                    mappings[s.google_user_id] ??
                    s.mapped_student_id ??
                    s.suggested_student_id ??
                    ""
                  }
                  onChange={(e) =>
                    setMappings({
                      ...mappings,
                      [s.google_user_id]: e.target.value === "" ? "" : Number(e.target.value),
                    })
                  }
                >
                  <option value="">Not linked</option>
                  {group.members.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name}
                    </option>
                  ))}
                </Select>
              </div>
            ))}
            {roster.data.app_students_not_in_classroom.length > 0 && (
              <p className="border-t border-slate-100 pt-3 text-xs text-slate-500">
                Not in Google Classroom:{" "}
                {roster.data.app_students_not_in_classroom.map((s) => s.name).join(", ")}. They can
                still submit here as usual.
              </p>
            )}
          </CardBody>
        </Card>
      )}

      {linkId !== null && coursework.data && (
        <Card>
          <CardHeader title="3. Import a piece of work" />
          <CardBody className="space-y-3">
            {coursework.data.map((cw) => (
              <div key={cw.coursework_id} className="flex flex-wrap items-center gap-3">
                <span className="min-w-0 flex-1 truncate text-sm text-slate-800">{cw.title}</span>
                <Select
                  className="max-w-56"
                  aria-label={`Homework to import ${cw.title} into`}
                  value={assignmentFor[cw.coursework_id] ?? cw.linked_assignment_id ?? ""}
                  onChange={(e) =>
                    setAssignmentFor({
                      ...assignmentFor,
                      [cw.coursework_id]: e.target.value === "" ? "" : Number(e.target.value),
                    })
                  }
                >
                  <option value="">Choose homework…</option>
                  {assignments.data
                    ?.filter((a) => a.status === "published")
                    .map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.title}
                      </option>
                    ))}
                </Select>
                <Button
                  size="sm"
                  onClick={() => runImport.mutate(cw.coursework_id)}
                  disabled={
                    runImport.isPending ||
                    !(assignmentFor[cw.coursework_id] ?? cw.linked_assignment_id)
                  }
                >
                  Import
                </Button>
              </div>
            ))}
            {coursework.data.length === 0 && (
              <p className="text-sm text-slate-500">No coursework in this course yet.</p>
            )}
          </CardBody>
        </Card>
      )}

      {run.data && (
        <Card>
          <CardHeader
            title="Import result"
            description={
              run.data.status === "running" || run.data.status === "pending"
                ? "Downloading attachments…"
                : `${run.data.imported} imported · ${run.data.skipped} skipped · ${run.data.failed} failed`
            }
          />
          <CardBody>
            {run.data.error && <p className="text-sm text-risk-600">{run.data.error}</p>}
            <ul className="divide-y divide-slate-100">
              {run.data.results.map((r) => {
                const label = OUTCOME_LABEL[r.outcome] ?? { tone: "caution" as const, text: r.outcome };
                return (
                  <li key={r.google_user_id} className="flex items-start justify-between gap-3 py-2">
                    <span className="min-w-0">
                      <span className="block truncate text-sm text-slate-700">
                        {roster.data?.classroom_students.find(
                          (s) => s.google_user_id === r.google_user_id,
                        )?.google_name ?? r.google_user_id}
                      </span>
                      {r.detail && <span className="text-xs text-slate-500">{r.detail}</span>}
                    </span>
                    <Badge tone={label.tone}>{label.text}</Badge>
                  </li>
                );
              })}
            </ul>
          </CardBody>
        </Card>
      )}
    </div>
  );
}
