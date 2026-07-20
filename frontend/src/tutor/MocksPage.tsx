import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { listGroups } from "../api/groups";
import { listAssessments } from "../api/readiness";

export default function MocksPage() {
  const groups = useQuery({ queryKey: ["groups"], queryFn: listGroups });
  const assessments = useQuery({ queryKey: ["assessments"], queryFn: () => listAssessments() });

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-slate-800">Mocks &amp; quizzes</h2>
        <p className="text-sm text-slate-500">Enter mock/test marks for a group, or review past ones.</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {groups.data?.map((g) => (
          <div key={g.id} className="rounded-lg border bg-white p-4">
            <div className="font-medium text-slate-800">{g.name}</div>
            <div className="mt-1 text-sm text-slate-500">
              {g.subject.exam_board} {g.subject.code}
            </div>
            <Link
              to={`/tutor/groups/${g.id}/mock`}
              className="mt-2 inline-block text-sm text-blue-600 hover:underline"
            >
              Enter marks →
            </Link>
          </div>
        ))}
      </div>

      <div className="rounded-lg border bg-white p-4">
        <h3 className="font-medium text-slate-800">History</h3>
        <ul className="mt-2 divide-y text-sm">
          {assessments.data?.map((a) => (
            <li key={a.id} className="flex items-center justify-between py-2">
              <span className="text-slate-700">{a.title}</span>
              <span className="text-slate-500">
                {a.type} · {new Date(a.date).toLocaleDateString(undefined, { day: "numeric", month: "short" })} ·{" "}
                {a.score_count} score{a.score_count === 1 ? "" : "s"}
              </span>
            </li>
          ))}
          {assessments.data?.length === 0 && (
            <li className="py-2 text-slate-500">No mocks or tests recorded yet.</li>
          )}
        </ul>
      </div>
    </div>
  );
}
