import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  classroomAuthUrl,
  classroomStatus,
  createClassroomLink,
  deleteClassroomLink,
  disconnectClassroom,
  listClassroomCourses,
  listClassroomLinks,
  syncClassroom,
} from "../api/classroom";
import { listGroups } from "../api/groups";
import { ApiError } from "../api/client";
import TimezoneSetting from "./TimezoneSetting";

/** Where the OAuth `state` is stashed between leaving for Google and coming
 * back to /settings/classroom/callback, so the callback can prove the redirect
 * belongs to this browser session. */
export const OAUTH_STATE_KEY = "classroom_oauth_state";

export default function ClassroomSettingsPage() {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const status = useQuery({ queryKey: ["classroom-status"], queryFn: classroomStatus });
  const connected = status.data?.connected === true;

  const groups = useQuery({ queryKey: ["groups"], queryFn: listGroups });
  const courses = useQuery({
    queryKey: ["classroom-courses"],
    queryFn: listClassroomCourses,
    enabled: connected,
  });
  const links = useQuery({
    queryKey: ["classroom-links"],
    queryFn: listClassroomLinks,
    enabled: connected,
  });

  const fail = (err: unknown) => setError(err instanceof ApiError ? err.message : String(err));

  const connect = useMutation({
    mutationFn: classroomAuthUrl,
    onSuccess: (data) => {
      sessionStorage.setItem(OAUTH_STATE_KEY, data.state);
      window.location.href = data.url;
    },
    onError: fail,
  });

  const disconnect = useMutation({
    mutationFn: disconnectClassroom,
    onSuccess: () => {
      setNotice("Google Classroom disconnected.");
      queryClient.invalidateQueries({ queryKey: ["classroom-status"] });
    },
    onError: fail,
  });

  const [groupId, setGroupId] = useState("");
  const [courseId, setCourseId] = useState("");

  const link = useMutation({
    mutationFn: () => {
      const course = courses.data?.find((c) => c.id === courseId);
      return createClassroomLink({
        group_id: Number(groupId),
        classroom_course_id: courseId,
        classroom_course_name: course?.name ?? courseId,
      });
    },
    onSuccess: () => {
      setGroupId("");
      setCourseId("");
      queryClient.invalidateQueries({ queryKey: ["classroom-links"] });
    },
    onError: fail,
  });

  const unlink = useMutation({
    mutationFn: deleteClassroomLink,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["classroom-links"] }),
    onError: fail,
  });

  const sync = useMutation({
    mutationFn: syncClassroom,
    onSuccess: () =>
      setNotice(
        "Sync started. Imported coursework and submissions will appear in Homework shortly.",
      ),
    onError: fail,
  });

  if (status.isLoading) return <p className="text-slate-500">Loading…</p>;

  return (
    <div className="max-w-2xl space-y-6">
      <TimezoneSetting />

      <div>
        <h2 className="text-xl font-semibold text-slate-800">Google Classroom</h2>
        <p className="text-sm text-slate-500">
          Import coursework and turned-in student work from Classroom. Anything imported goes
          through the same marking as work uploaded here — this adds a way in, it doesn't replace
          direct upload.
        </p>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}
      {notice && <p className="text-sm text-green-700">{notice}</p>}

      {status.data?.configured === false ? (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">
          Google Classroom isn't set up on this deployment yet. Ask your administrator to add the
          Google OAuth credentials.
        </div>
      ) : (
        <div className="rounded-lg border bg-white p-4">
          {connected ? (
            <div className="flex items-center justify-between">
              <div className="text-sm">
                <div className="font-medium text-slate-800">
                  Connected as {status.data?.google_email}
                </div>
                {status.data?.connected_at && (
                  <div className="text-slate-500">
                    Since {new Date(status.data.connected_at).toLocaleDateString()}
                  </div>
                )}
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => sync.mutate()}
                  disabled={sync.isPending}
                  className="rounded bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  Sync now
                </button>
                <button
                  onClick={() => disconnect.mutate()}
                  disabled={disconnect.isPending}
                  className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50 disabled:opacity-50"
                >
                  Disconnect
                </button>
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-between">
              <p className="text-sm text-slate-600">Not connected to Google Classroom.</p>
              <button
                onClick={() => connect.mutate()}
                disabled={connect.isPending}
                className="rounded bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
              >
                Connect Google Classroom
              </button>
            </div>
          )}
        </div>
      )}

      {connected && (
        <div className="rounded-lg border bg-white p-4">
          <h3 className="font-medium text-slate-800">Linked classes</h3>
          <p className="mt-1 text-sm text-slate-500">
            Each of your classes can be linked to one Classroom course.
          </p>

          <ul className="mt-3 divide-y text-sm">
            {links.data?.map((l) => (
              <li key={l.id} className="flex items-center justify-between py-2">
                <div>
                  <span className="text-slate-800">{l.group_name}</span>
                  <span className="text-slate-400"> ↔ </span>
                  <span className="text-slate-600">{l.classroom_course_name}</span>
                  {l.last_synced_at && (
                    <div className="text-xs text-slate-400">
                      Last synced {new Date(l.last_synced_at).toLocaleString()}
                    </div>
                  )}
                </div>
                <button
                  onClick={() => unlink.mutate(l.id)}
                  className="text-slate-500 hover:text-red-600"
                >
                  Unlink
                </button>
              </li>
            ))}
            {links.data?.length === 0 && (
              <li className="py-2 text-slate-500">No classes linked yet.</li>
            )}
          </ul>

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <select
              value={groupId}
              onChange={(e) => setGroupId(e.target.value)}
              className="rounded border border-slate-300 px-2 py-1.5 text-sm"
            >
              <option value="">Choose a class…</option>
              {groups.data?.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
            <select
              value={courseId}
              onChange={(e) => setCourseId(e.target.value)}
              className="rounded border border-slate-300 px-2 py-1.5 text-sm"
            >
              <option value="">Choose a Classroom course…</option>
              {courses.data?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
            <button
              onClick={() => link.mutate()}
              disabled={!groupId || !courseId || link.isPending}
              className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50 disabled:opacity-50"
            >
              Link
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
