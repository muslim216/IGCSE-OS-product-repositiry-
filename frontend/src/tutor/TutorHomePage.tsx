import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../auth/AuthContext";
import { myTodayLessons, listGroups } from "../api/groups";
import { assignmentsNeedingAttention } from "../api/homework";

const REASON_LABELS: Record<string, string> = {
  extraction_failed: "Question extraction failed",
  ai_failed: "AI marking failed",
  ai_marked: "AI-marked — awaiting your review",
};

function StatTile({ label, value, tone = "default" }: { label: string; value: string; tone?: "default" | "good" | "warn" }) {
  const color =
    tone === "good" ? "text-emerald-400" : tone === "warn" ? "text-amber-400" : "text-slate-100";
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

export default function TutorHomePage() {
  const { user } = useAuth();
  const groups = useQuery({ queryKey: ["groups"], queryFn: listGroups });
  const lessons = useQuery({ queryKey: ["today-lessons"], queryFn: myTodayLessons });
  const attention = useQuery({ queryKey: ["assignments-attention"], queryFn: assignmentsNeedingAttention });

  const totalStudents = (groups.data ?? []).reduce((sum, g) => sum + g.member_count, 0);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight text-slate-100">
          Welcome back, {firstName(user?.name)}
        </h2>
        <p className="mt-1 text-sm text-slate-500">Here's what's happening across your classes.</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <StatTile label="Groups" value={String(groups.data?.length ?? 0)} />
        <StatTile label="Students" value={String(totalStudents)} />
        <StatTile
          label="Needs attention"
          value={String(attention.data?.length ?? 0)}
          tone={!attention.data || attention.data.length === 0 ? "good" : "warn"}
        />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-lg border bg-white p-4">
          <div className="flex items-center justify-between">
            <h3 className="font-medium text-slate-800">Needs your attention</h3>
            <Link to="/tutor/homework" className="text-sm text-blue-600 hover:underline">
              All homework
            </Link>
          </div>
          <ul className="mt-2 space-y-1.5">
            {attention.data?.slice(0, 5).map((a, i) => (
              <li key={i} className="flex items-center justify-between text-sm">
                <Link
                  to={
                    a.submission_id
                      ? `/tutor/submissions/${a.submission_id}`
                      : `/tutor/assignments/${a.assignment_id}`
                  }
                  className="truncate text-blue-600 hover:underline"
                >
                  {a.assignment_title}
                  {a.student_name && <span className="text-slate-500"> — {a.student_name}</span>}
                </Link>
                <span className="shrink-0 text-amber-400">
                  {REASON_LABELS[a.reason] ?? a.reason}
                </span>
              </li>
            ))}
            {attention.data?.length === 0 && (
              <li className="text-sm text-slate-500">Nothing needs attention right now.</li>
            )}
          </ul>
        </div>

        <div className="rounded-lg border bg-white p-4">
          <div className="flex items-center justify-between">
            <h3 className="font-medium text-slate-800">Today's lessons</h3>
            <Link to="/tutor/today" className="text-sm text-blue-600 hover:underline">
              Today
            </Link>
          </div>
          <ul className="mt-2 space-y-1.5">
            {lessons.data?.map((l) => (
              <li key={l.id} className="flex items-center justify-between text-sm">
                <span className="text-slate-700">{l.group_name}</span>
                <span className="text-slate-400">{l.start_time.slice(0, 5)}</span>
              </li>
            ))}
            {lessons.data?.length === 0 && (
              <li className="text-sm text-slate-500">No lessons scheduled for today.</li>
            )}
          </ul>
        </div>
      </div>

      <div className="rounded-lg border bg-white p-4">
        <div className="flex items-center justify-between">
          <h3 className="font-medium text-slate-800">Your groups</h3>
          <Link to="/tutor/classes" className="text-sm text-blue-600 hover:underline">
            All classes
          </Link>
        </div>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {groups.data?.map((g) => (
            <Link
              key={g.id}
              to={`/tutor/groups/${g.id}`}
              className="rounded-lg border bg-white p-3 hover:border-blue-400"
            >
              <div className="font-medium text-slate-800">{g.name}</div>
              <div className="mt-1 text-sm text-slate-500">
                {g.subject.exam_board} {g.subject.code} · {g.member_count} student
                {g.member_count === 1 ? "" : "s"}
              </div>
            </Link>
          ))}
          {groups.data?.length === 0 && (
            <p className="text-sm text-slate-500">
              No groups yet — create your first group to invite students.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
