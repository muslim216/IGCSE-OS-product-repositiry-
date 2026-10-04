import { useEffect, useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { getAttendance } from "../api/lessons";
import {
  getLessonMeeting,
  importAttendance,
  listIntegrations,
  PROVIDER_LABEL,
  resolveParticipant,
  setMeetingLink,
  type LessonMeeting,
  type MeetingParticipant,
} from "../api/integrations";
import { Button, Input, Select } from "../components/controls";
import { friendlyError } from "../lib/errors";
import AttendanceRegister from "./AttendanceRegister";

/** An online lesson's attendance: the meeting link, an import from Zoom or Google
 *  Meet, the register it fills in, and everyone it could not match to a student.
 *
 *  Matching is by exact email only. Anyone else is listed here for the tutor to
 *  pick a student — nothing is guessed from a name. An import that fails says why
 *  instead of leaving an empty register. */
export default function OnlineAttendance({ lessonId }: { lessonId: number }) {
  const queryClient = useQueryClient();
  const meetingKey = ["lesson-meeting", lessonId];
  const meeting = useQuery({
    queryKey: meetingKey,
    queryFn: () => getLessonMeeting(lessonId),
    // Follow a queued import until the worker has finished it.
    refetchInterval: (q) => (q.state.data?.last_import?.status === "queued" ? 2000 : false),
  });
  const integrations = useQuery({ queryKey: ["integrations"], queryFn: listIntegrations });
  const register = useQuery({
    queryKey: ["attendance", lessonId],
    queryFn: () => getAttendance(lessonId),
  });

  // A finished import has written marks: show them.
  const status = meeting.data?.last_import?.status;
  const previous = useRef(status);
  useEffect(() => {
    if (previous.current === "queued" && status !== "queued") {
      queryClient.invalidateQueries({ queryKey: ["attendance", lessonId] });
    }
    previous.current = status;
  }, [status, lessonId, queryClient]);

  const start = useMutation({
    mutationFn: () => importAttendance(lessonId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: meetingKey }),
  });

  if (meeting.isLoading) return <p className="text-sm text-ink-500">Loading attendance…</p>;
  if (meeting.isError || !meeting.data) {
    return (
      <p role="alert" className="text-sm text-risk-600">
        {friendlyError(meeting.error)}
      </p>
    );
  }
  const data = meeting.data;
  const provider = data.provider;
  const label = provider ? PROVIDER_LABEL[provider] : null;
  const integration = (integrations.data ?? []).find((i) => i.provider === provider);
  const unmatched = data.participants.filter((p) => p.matched_student_id === null);
  const importing = data.last_import?.status === "queued";

  return (
    <div className="space-y-4">
      <MeetingLinkRow lessonId={lessonId} data={data} />

      {provider && label && (
        <div>
          {integrations.isLoading ? null : !integration ? null : !integration.configured ? (
            <p className="text-sm text-ink-500">
              {label} attendance isn't set up for Avora yet, so it can't be imported here.
            </p>
          ) : !integration.connected ? (
            <p className="text-sm text-ink-500">
              <Link to="/tutor/settings" className="text-brand-700 underline">
                Connect {label}
              </Link>{" "}
              to import attendance for this lesson.
            </p>
          ) : (
            <Button
              size="sm"
              variant="secondary"
              loading={start.isPending || importing}
              onClick={() => start.mutate()}
            >
              Import attendance
            </Button>
          )}
          {start.isError && (
            <p role="alert" className="mt-2 text-sm text-risk-600">
              {friendlyError(start.error)}
            </p>
          )}
          {importing && (
            <p role="status" className="mt-2 text-sm text-ink-500">
              Importing from {label}…
            </p>
          )}
          {data.last_import?.status === "failed" && (
            <p role="alert" className="mt-2 rounded-md bg-risk-100 px-3 py-2 text-sm text-risk-600">
              Couldn't import attendance. {data.last_import.message}
            </p>
          )}
          {data.last_import?.status === "succeeded" && data.last_import.message && (
            <p role="status" className="mt-2 text-sm text-ink-700">
              Imported from {label}. {data.last_import.message}
            </p>
          )}
        </div>
      )}

      <AttendanceRegister lessonId={lessonId} online />

      {unmatched.length > 0 && (
        <div>
          <h4 className="text-sm font-medium text-ink-900">Not matched to a student</h4>
          <p className="mt-1 text-sm text-ink-500">
            These people joined but couldn't be identified for certain. Say who they are and they'll
            be marked present. Until everyone is identified, nobody is marked absent.
          </p>
          <ul className="mt-2 divide-y divide-line">
            {unmatched.map((p) => (
              <UnmatchedRow
                key={p.id}
                lessonId={lessonId}
                participant={p}
                students={(register.data ?? []).map((r) => ({
                  id: r.student_id,
                  name: r.name,
                }))}
              />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function MeetingLinkRow({ lessonId, data }: { lessonId: number; data: LessonMeeting }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const save = useMutation({
    mutationFn: (link: string | null) => setMeetingLink(lessonId, link),
    onSuccess: () => {
      setEditing(false);
      queryClient.invalidateQueries({ queryKey: ["lesson-meeting", lessonId] });
      queryClient.invalidateQueries({ queryKey: ["attendance", lessonId] });
      queryClient.invalidateQueries({ queryKey: ["taught-lessons"] });
    },
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (draft.trim()) save.mutate(draft.trim());
  }

  if (data.link && !editing) {
    return (
      <p className="text-sm text-ink-700">
        {data.provider ? PROVIDER_LABEL[data.provider] : "Meeting"} link:{" "}
        <span className="break-all text-ink-900">{data.link}</span>{" "}
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            setDraft("");
            setEditing(true);
          }}
        >
          Change
        </Button>
      </p>
    );
  }
  return (
    <form onSubmit={onSubmit} className="flex flex-wrap items-center gap-2">
      <label htmlFor={`meeting-link-${lessonId}`} className="text-sm text-ink-700">
        {data.link ? "New meeting link" : "Add the Zoom or Google Meet link to import attendance"}
      </label>
      <div className="min-w-[14rem] flex-1">
        <Input
          id={`meeting-link-${lessonId}`}
          type="url"
          value={draft}
          placeholder="https://zoom.us/j/…"
          onChange={(e) => setDraft(e.target.value)}
        />
      </div>
      <Button type="submit" size="sm" loading={save.isPending} disabled={!draft.trim()}>
        Save link
      </Button>
      {editing && (
        <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(false)}>
          Cancel
        </Button>
      )}
      {save.isError && (
        <p role="alert" className="w-full text-sm text-risk-600">
          {friendlyError(save.error)}
        </p>
      )}
    </form>
  );
}

function UnmatchedRow({
  lessonId,
  participant,
  students,
}: {
  lessonId: number;
  participant: MeetingParticipant;
  students: { id: number; name: string }[];
}) {
  const queryClient = useQueryClient();
  const resolve = useMutation({
    mutationFn: (studentId: number) => resolveParticipant(lessonId, participant.id, studentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["lesson-meeting", lessonId] });
      queryClient.invalidateQueries({ queryKey: ["attendance", lessonId] });
    },
  });
  const minutes = Math.round(participant.duration_seconds / 60);
  const suggestion = students.find((st) => st.id === participant.suggested_student_id) ?? null;

  return (
    <li className="py-2">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm text-ink-900">{participant.display_name}</p>
          <p className="text-xs text-ink-500">
            {participant.email ?? "No email shared"}
            {minutes > 0 ? ` · ${minutes} min` : ""}
          </p>
        </div>
        <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
          {suggestion && (
            <Button
              size="sm"
              variant="primary"
              disabled={resolve.isPending}
              onClick={() => resolve.mutate(suggestion.id)}
            >
              Confirm: {suggestion.name}
            </Button>
          )}
          <div className="w-full sm:w-52">
            <Select
              aria-label={`This is… (${participant.display_name})`}
              value=""
              disabled={resolve.isPending}
              onChange={(e) => {
                if (e.target.value) resolve.mutate(Number(e.target.value));
              }}
            >
              <option value="">This is…</option>
              {students.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </Select>
          </div>
        </div>
      </div>
      {suggestion && (
        <p className="mt-1 text-xs text-ink-500">
          The email they joined with matches {suggestion.name}, but the meeting service doesn't
          verify it, so it needs your say-so.
        </p>
      )}
      {resolve.isError && (
        <p role="alert" className="mt-1 text-sm text-risk-600">
          {friendlyError(resolve.error)}
        </p>
      )}
    </li>
  );
}
