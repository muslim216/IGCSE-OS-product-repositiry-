import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  WEEKDAYS,
  createInvite,
  createLesson,
  createParentCode,
  createStudentAccount,
  deleteLesson,
  getGroup,
  listLessons,
  removeMember,
  resetStudentPassword,
} from "../api/groups";

function CopyBox({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="mt-2 flex items-center gap-2 rounded-md bg-slate-50 p-2 text-sm">
      <span className="text-slate-500">{label}:</span>
      <code className="flex-1 truncate">{value}</code>
      <button
        className="rounded bg-slate-200 px-2 py-1 text-xs hover:bg-slate-300"
        onClick={() => {
          navigator.clipboard.writeText(value);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }}
      >
        {copied ? "Copied!" : "Copy"}
      </button>
    </div>
  );
}

export default function GroupDetailPage() {
  const { groupId } = useParams();
  const id = Number(groupId);
  const queryClient = useQueryClient();

  const group = useQuery({ queryKey: ["group", id], queryFn: () => getGroup(id) });
  const lessons = useQuery({ queryKey: ["lessons", id], queryFn: () => listLessons(id) });

  const [inviteLink, setInviteLink] = useState<string | null>(null);
  const [parentCodes, setParentCodes] = useState<Record<number, string>>({});

  const invite = useMutation({
    mutationFn: () => createInvite(id),
    onSuccess: (data) =>
      setInviteLink(`${window.location.origin}/join/${data.code}`),
  });

  const [studentForm, setStudentForm] = useState({ name: "", username: "", password: "" });
  const addStudent = useMutation({
    mutationFn: () => createStudentAccount(id, studentForm),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["group", id] });
      setStudentForm({ name: "", username: "", password: "" });
    },
  });

  const remove = useMutation({
    mutationFn: (studentId: number) => removeMember(id, studentId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["group", id] }),
  });

  const parentCode = useMutation({
    mutationFn: (studentId: number) => createParentCode(studentId),
    onSuccess: (data, studentId) =>
      setParentCodes((prev) => ({
        ...prev,
        [studentId]: `${window.location.origin}/parent-join/${data.code}`,
      })),
  });

  const resetPw = useMutation({
    mutationFn: ({ studentId, password }: { studentId: number; password: string }) =>
      resetStudentPassword(id, studentId, password),
  });

  const [lessonForm, setLessonForm] = useState({
    weekday: 0,
    start_time: "17:00",
    duration_min: 60,
    title: "",
  });
  const addLesson = useMutation({
    mutationFn: () =>
      createLesson(id, { ...lessonForm, title: lessonForm.title || null }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["lessons", id] }),
  });
  const dropLesson = useMutation({
    mutationFn: (lessonId: number) => deleteLesson(id, lessonId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["lessons", id] }),
  });

  function onAddStudent(e: FormEvent) {
    e.preventDefault();
    addStudent.mutate();
  }

  function onAddLesson(e: FormEvent) {
    e.preventDefault();
    addLesson.mutate();
  }

  if (group.isLoading) return <p className="text-slate-500">Loading…</p>;
  if (group.isError || !group.data) return <p className="text-red-600">Group not found.</p>;

  return (
    <div className="space-y-8">
      <div>
        <Link to="/tutor" className="text-sm text-blue-600 hover:underline">
          ← All groups
        </Link>
        <h2 className="mt-1 text-xl font-semibold text-slate-800">{group.data.name}</h2>
        <p className="text-sm text-slate-500">
          {group.data.subject.exam_board} {group.data.subject.code} — {group.data.subject.name}
        </p>
      </div>

      <section className="rounded-lg border bg-white p-4">
        <div className="flex items-center justify-between">
          <h3 className="font-medium text-slate-800">Students ({group.data.members.length})</h3>
          <button
            onClick={() => invite.mutate()}
            className="rounded-md bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700"
          >
            Generate invite link
          </button>
        </div>
        {inviteLink && <CopyBox label="Invite link" value={inviteLink} />}

        <ul className="mt-3 divide-y">
          {group.data.members.map((m) => (
            <li key={m.id} className="py-2">
              <div className="flex items-center justify-between gap-2">
                <div>
                  <span className="font-medium text-slate-700">{m.name}</span>{" "}
                  <span className="text-sm text-slate-400">
                    {m.email ?? `@${m.username}`}
                  </span>
                </div>
                <div className="flex items-center gap-2 text-sm">
                  <button
                    onClick={() => parentCode.mutate(m.id)}
                    className="text-blue-600 hover:underline"
                  >
                    Parent link
                  </button>
                  {!m.email && (
                    <button
                      onClick={() => {
                        const pw = prompt(`New password for ${m.name} (min 8 characters):`);
                        if (pw) resetPw.mutate({ studentId: m.id, password: pw });
                      }}
                      className="text-slate-500 hover:underline"
                    >
                      Reset password
                    </button>
                  )}
                  <button
                    onClick={() => {
                      if (confirm(`Remove ${m.name} from this group?`)) remove.mutate(m.id);
                    }}
                    className="text-red-500 hover:underline"
                  >
                    Remove
                  </button>
                </div>
              </div>
              {parentCodes[m.id] && <CopyBox label="Parent link" value={parentCodes[m.id]} />}
            </li>
          ))}
          {group.data.members.length === 0 && (
            <li className="py-2 text-sm text-slate-500">
              No students yet — share an invite link or add an account below.
            </li>
          )}
        </ul>

        <form onSubmit={onAddStudent} className="mt-4 border-t pt-4">
          <h4 className="text-sm font-medium text-slate-700">
            Add a student without an email (username account)
          </h4>
          <div className="mt-2 flex flex-wrap items-end gap-2">
            <input
              className="rounded-md border border-slate-300 px-3 py-2 text-sm"
              placeholder="Student name"
              value={studentForm.name}
              onChange={(e) => setStudentForm({ ...studentForm, name: e.target.value })}
              required
            />
            <input
              className="rounded-md border border-slate-300 px-3 py-2 text-sm"
              placeholder="Username"
              value={studentForm.username}
              onChange={(e) => setStudentForm({ ...studentForm, username: e.target.value })}
              required
            />
            <input
              className="rounded-md border border-slate-300 px-3 py-2 text-sm"
              placeholder="Password (min 8 chars)"
              value={studentForm.password}
              onChange={(e) => setStudentForm({ ...studentForm, password: e.target.value })}
              minLength={8}
              required
            />
            <button
              type="submit"
              disabled={addStudent.isPending}
              className="rounded-md bg-slate-700 px-3 py-2 text-sm text-white hover:bg-slate-800 disabled:opacity-50"
            >
              Add student
            </button>
          </div>
          {addStudent.isError && (
            <p className="mt-1 text-sm text-red-600">
              Could not create the account (is the username taken?).
            </p>
          )}
        </form>
      </section>

      <section className="rounded-lg border bg-white p-4">
        <h3 className="font-medium text-slate-800">Weekly lessons</h3>
        <ul className="mt-2 divide-y">
          {lessons.data?.map((lesson) => (
            <li key={lesson.id} className="flex items-center justify-between py-2 text-sm">
              <span>
                <span className="font-medium text-slate-700">{WEEKDAYS[lesson.weekday]}</span>{" "}
                {lesson.start_time.slice(0, 5)} · {lesson.duration_min} min
                {lesson.title && <span className="text-slate-500"> — {lesson.title}</span>}
              </span>
              <button
                onClick={() => dropLesson.mutate(lesson.id)}
                className="text-red-500 hover:underline"
              >
                Remove
              </button>
            </li>
          ))}
          {lessons.data?.length === 0 && (
            <li className="py-2 text-sm text-slate-500">No lessons scheduled.</li>
          )}
        </ul>
        <form onSubmit={onAddLesson} className="mt-3 flex flex-wrap items-end gap-2 border-t pt-3">
          <select
            className="rounded-md border border-slate-300 px-3 py-2 text-sm"
            value={lessonForm.weekday}
            onChange={(e) => setLessonForm({ ...lessonForm, weekday: Number(e.target.value) })}
          >
            {WEEKDAYS.map((d, i) => (
              <option key={d} value={i}>
                {d}
              </option>
            ))}
          </select>
          <input
            type="time"
            className="rounded-md border border-slate-300 px-3 py-2 text-sm"
            value={lessonForm.start_time}
            onChange={(e) => setLessonForm({ ...lessonForm, start_time: e.target.value })}
            required
          />
          <input
            type="number"
            min={15}
            max={480}
            step={15}
            className="w-24 rounded-md border border-slate-300 px-3 py-2 text-sm"
            value={lessonForm.duration_min}
            onChange={(e) => setLessonForm({ ...lessonForm, duration_min: Number(e.target.value) })}
          />
          <input
            className="rounded-md border border-slate-300 px-3 py-2 text-sm"
            placeholder="Title (optional)"
            value={lessonForm.title}
            onChange={(e) => setLessonForm({ ...lessonForm, title: e.target.value })}
          />
          <button
            type="submit"
            disabled={addLesson.isPending}
            className="rounded-md bg-slate-700 px-3 py-2 text-sm text-white hover:bg-slate-800 disabled:opacity-50"
          >
            Add lesson
          </button>
        </form>
      </section>
    </div>
  );
}
