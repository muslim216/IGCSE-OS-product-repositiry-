import { useQuery } from "@tanstack/react-query";
import { WEEKDAYS, myGroups, myLessons } from "../api/groups";

export default function StudentDashboard() {
  const groups = useQuery({ queryKey: ["my-groups"], queryFn: myGroups });
  const lessons = useQuery({ queryKey: ["my-lessons"], queryFn: myLessons });

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-slate-800">Your subjects</h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {groups.data?.map((g) => (
            <div key={g.id} className="rounded-lg border bg-white p-4">
              <div className="font-medium text-slate-800">{g.subject.name}</div>
              <div className="mt-1 text-sm text-slate-500">
                {g.name} · {g.subject.exam_board} {g.subject.code}
              </div>
              <div className="mt-2 text-sm text-slate-400">
                Readiness tracking coming soon
              </div>
            </div>
          ))}
          {groups.data?.length === 0 && (
            <p className="text-slate-500">
              You're not in any group yet. Ask your tutor for an invite link.
            </p>
          )}
        </div>
      </div>

      <div>
        <h2 className="text-xl font-semibold text-slate-800">Weekly lessons</h2>
        <ul className="mt-3 divide-y rounded-lg border bg-white">
          {lessons.data?.map((lesson, i) => (
            <li key={i} className="flex items-center justify-between px-4 py-3 text-sm">
              <span>
                <span className="font-medium text-slate-700">
                  {WEEKDAYS[lesson.weekday]} {lesson.start_time.slice(0, 5)}
                </span>{" "}
                <span className="text-slate-500">
                  — {lesson.subject_name} ({lesson.group_name})
                </span>
                {lesson.title && <span className="text-slate-400"> · {lesson.title}</span>}
              </span>
              <span className="text-slate-400">{lesson.duration_min} min</span>
            </li>
          ))}
          {lessons.data?.length === 0 && (
            <li className="px-4 py-3 text-sm text-slate-500">No lessons scheduled yet.</li>
          )}
        </ul>
      </div>
    </div>
  );
}
