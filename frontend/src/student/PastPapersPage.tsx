import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { listPastPapers } from "../api/pastPapers";

export default function PastPapersPage() {
  const papers = useQuery({ queryKey: ["past-papers"], queryFn: () => listPastPapers() });

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-semibold text-slate-800">Past papers</h2>
        <p className="text-sm text-slate-500">
          Sit a full paper, then upload your answers to get it marked question by
          question.
        </p>
      </div>

      {papers.isLoading && <p className="text-slate-500">Loading…</p>}

      <div className="grid gap-3 sm:grid-cols-2">
        {papers.data?.map((p) => (
          <Link
            key={p.id}
            to={`/student/past-papers/${p.id}`}
            className="rounded-lg border bg-white p-4 hover:border-blue-400"
          >
            <div className="font-medium text-slate-800">
              {p.session_label} · {p.paper_number}
            </div>
            <div className="mt-1 text-sm text-slate-500">
              {p.total_marks ? `${p.total_marks} marks` : "Marks not set"}
              {p.duration_minutes ? ` · ${p.duration_minutes} minutes` : ""}
            </div>
          </Link>
        ))}
      </div>

      {papers.data?.length === 0 && (
        <p className="text-slate-500">
          No past papers have been added for your subjects yet.
        </p>
      )}
    </div>
  );
}
