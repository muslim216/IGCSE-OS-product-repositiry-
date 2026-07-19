import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { WEEKDAYS, myLessons } from "../api/groups";
import { myReadiness } from "../api/readiness";
import { myAssignments } from "../api/homework";
import { SubjectReadinessCard } from "../components/ReadinessView";
import { ReportsPanel } from "../components/ReportsPanel";

function nextLessonLabel(weekday: number, start: string): string {
  return `${WEEKDAYS[weekday]} ${start.slice(0, 5)}`;
}

export default function StudentDashboard() {
  const readiness = useQuery({ queryKey: ["my-readiness"], queryFn: myReadiness });
  const lessons = useQuery({ queryKey: ["my-lessons"], queryFn: myLessons });
  const assignments = useQuery({ queryKey: ["my-assignments"], queryFn: myAssignments });

  const due = (assignments.data ?? []).filter(
    (a) => a.submission_status === "not_submitted",
  );

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-slate-800">How ready are you?</h2>
        <p className="text-sm text-slate-500">
          Based on your homework, mocks and your tutor's notes. Grades are estimates.
        </p>
        {readiness.data && readiness.data.subjects.length > 0 ? (
          <div className="mt-3 grid gap-4 lg:grid-cols-2">
            {readiness.data.subjects.map((s) => (
              <SubjectReadinessCard key={s.subject_id} subject={s} />
            ))}
          </div>
        ) : (
          <p className="mt-3 text-slate-500">
            No readiness data yet — it builds up as your homework and mocks are marked.
          </p>
        )}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-lg border bg-white p-4">
          <div className="flex items-center justify-between">
            <h3 className="font-medium text-slate-800">Homework to do</h3>
            <Link to="/student/homework" className="text-sm text-blue-600 hover:underline">
              All homework
            </Link>
          </div>
          <ul className="mt-2 space-y-1.5">
            {due.map((a) => (
              <li key={a.id}>
                <Link
                  to={`/student/homework/${a.id}`}
                  className="flex items-center justify-between text-sm hover:underline"
                >
                  <span className="text-slate-700">{a.title}</span>
                  <span className="text-slate-400">
                    {a.due_at
                      ? new Date(a.due_at).toLocaleDateString(undefined, {
                          day: "numeric",
                          month: "short",
                        })
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

        <div className="rounded-lg border bg-white p-4">
          <h3 className="font-medium text-slate-800">Next lessons</h3>
          <ul className="mt-2 space-y-1.5">
            {lessons.data?.slice(0, 4).map((lesson, i) => (
              <li key={i} className="flex items-center justify-between text-sm">
                <span className="text-slate-700">
                  {nextLessonLabel(lesson.weekday, lesson.start_time)}
                </span>
                <span className="text-slate-400">{lesson.subject_name}</span>
              </li>
            ))}
            {lessons.data?.length === 0 && (
              <li className="text-sm text-slate-500">No lessons scheduled.</li>
            )}
          </ul>
        </div>
      </div>

      {readiness.data && (
        <ReportsPanel studentId={readiness.data.student_id} audiences={["student"]} />
      )}
    </div>
  );
}
