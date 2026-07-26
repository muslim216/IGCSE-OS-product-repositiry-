import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../auth/AuthContext";
import { WEEKDAYS, myLessons } from "../api/groups";
import { myReadiness } from "../api/readiness";
import { myAssignments } from "../api/homework";
import { listConversations } from "../api/chat";

function StatTile({ label, value, tone = "default" }: { label: string; value: string; tone?: "default" | "good" | "warn" }) {
  const color =
    tone === "good" ? "text-green-700" : tone === "warn" ? "text-amber-700" : "text-slate-800";
  return (
    <div className="rounded-lg border bg-white p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`mt-1.5 text-2xl font-semibold ${color}`}>{value}</p>
    </div>
  );
}

function firstName(name: string | undefined): string {
  return (name ?? "").split(" ")[0] || "there";
}

export default function StudentHomePage() {
  const { user } = useAuth();
  const readiness = useQuery({ queryKey: ["my-readiness"], queryFn: myReadiness });
  const lessons = useQuery({ queryKey: ["my-lessons"], queryFn: myLessons });
  const assignments = useQuery({ queryKey: ["my-assignments"], queryFn: myAssignments });
  const conversations = useQuery({ queryKey: ["conversations"], queryFn: listConversations });

  const subjects = readiness.data?.subjects ?? [];
  const scored = subjects.filter((s) => s.score !== null);
  const overall =
    scored.length > 0
      ? Math.round(scored.reduce((sum, s) => sum + (s.score ?? 0), 0) / scored.length)
      : null;

  const due = (assignments.data ?? []).filter((a) => a.submission_status === "not_submitted");
  const nextLesson = lessons.data?.[0];

  const weakTopics = subjects
    .flatMap((s) => s.weak_topics.map((t) => ({ ...t, subject_name: s.subject_name })))
    .slice(0, 4);

  const latestChat = conversations.data?.[0];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight text-slate-800">
          Welcome back, {firstName(user?.name)}
        </h2>
        <p className="mt-1 text-sm text-slate-500">Here's where things stand across the board.</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <StatTile
          label="Overall readiness"
          value={overall !== null ? `${overall}%` : "—"}
          tone={overall === null ? "default" : overall >= 70 ? "good" : overall >= 50 ? "warn" : "warn"}
        />
        <StatTile
          label="Homework due"
          value={String(due.length)}
          tone={due.length === 0 ? "good" : "warn"}
        />
        <StatTile
          label="Next lesson"
          value={nextLesson ? `${WEEKDAYS[nextLesson.weekday]} ${nextLesson.start_time.slice(0, 5)}` : "—"}
        />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-lg border bg-white p-4">
          <div className="flex items-center justify-between">
            <h3 className="font-medium text-slate-800">Focus on these topics</h3>
            <Link to="/student/readiness" className="text-sm text-blue-600 hover:underline">
              Full readiness
            </Link>
          </div>
          {weakTopics.length > 0 ? (
            <ul className="mt-2 space-y-1.5">
              {weakTopics.map((t) => (
                <li key={t.topic_id} className="flex items-center justify-between text-sm">
                  <span className="text-slate-700">
                    {t.topic_code} {t.topic_title}
                  </span>
                  <span className="text-slate-400">{t.subject_name}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-slate-500">
              No weak spots flagged yet — keep it up.
            </p>
          )}
        </div>

        <div className="rounded-lg border bg-white p-4">
          <div className="flex items-center justify-between">
            <h3 className="font-medium text-slate-800">Homework to do</h3>
            <Link to="/student/homework" className="text-sm text-blue-600 hover:underline">
              All homework
            </Link>
          </div>
          <ul className="mt-2 space-y-1.5">
            {due.slice(0, 4).map((a) => (
              <li key={a.id}>
                <Link
                  to={`/student/homework/${a.id}`}
                  className="flex items-center justify-between text-sm hover:underline"
                >
                  <span className="text-slate-700">{a.title}</span>
                  <span className="text-slate-400">
                    {a.due_at
                      ? new Date(a.due_at).toLocaleDateString(undefined, { day: "numeric", month: "short" })
                      : "no due date"}
                  </span>
                </Link>
              </li>
            ))}
            {due.length === 0 && (
              <li className="text-sm text-slate-500">You're all caught up 🎉</li>
            )}
          </ul>
        </div>
      </div>

      <div className="rounded-lg border bg-white p-4">
        <div className="flex items-center justify-between">
          <h3 className="font-medium text-slate-800">Your AI tutor</h3>
          <Link to="/student/tutor" className="text-sm text-blue-600 hover:underline">
            Open chat
          </Link>
        </div>
        {latestChat ? (
          <Link
            to="/student/tutor"
            className="mt-2 block truncate text-sm text-slate-500 hover:text-slate-700"
          >
            Continue: “{latestChat.title}”
          </Link>
        ) : (
          <p className="mt-2 text-sm text-slate-500">
            Stuck on a concept or planning revision? Ask your AI tutor.
          </p>
        )}
      </div>
    </div>
  );
}
