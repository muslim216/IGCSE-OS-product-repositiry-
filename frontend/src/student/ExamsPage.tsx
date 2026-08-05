import { useQuery } from "@tanstack/react-query";
import { myAssessmentScores } from "../api/readiness";

function scoreColor(pct: number): string {
  if (pct >= 70) return "text-green-700";
  if (pct >= 50) return "text-amber-700";
  return "text-red-600";
}

export default function ExamsPage() {
  const scores = useQuery({ queryKey: ["my-assessments"], queryFn: myAssessmentScores });

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold text-slate-800">Exams</h2>
        <p className="text-sm text-slate-500">
          Your mock and test scores, as entered by your tutor.
        </p>
      </div>

      <div className="overflow-hidden rounded-lg border bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-slate-500">
            <tr>
              <th className="px-4 py-2 font-medium">Assessment</th>
              <th className="px-4 py-2 font-medium">Subject</th>
              <th className="px-4 py-2 font-medium">Topic</th>
              <th className="px-4 py-2 font-medium">Date</th>
              <th className="px-4 py-2 text-right font-medium">Score</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {scores.data?.map((s, i) => (
              <tr key={i}>
                <td className="px-4 py-2 text-slate-700">{s.title}</td>
                <td className="px-4 py-2 text-slate-500">{s.subject_name}</td>
                <td className="px-4 py-2 text-slate-500">{s.topic_title ?? "Overall"}</td>
                <td className="px-4 py-2 text-slate-500">
                  {new Date(s.date).toLocaleDateString(undefined, {
                    day: "numeric",
                    month: "short",
                  })}
                </td>
                <td className={`px-4 py-2 text-right font-medium ${scoreColor(s.pct)}`}>
                  {s.marks}/{s.max_marks} ({s.pct}%)
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {scores.data?.length === 0 && (
          <p className="p-4 text-sm text-slate-500">No exam scores recorded yet.</p>
        )}
      </div>
    </div>
  );
}
