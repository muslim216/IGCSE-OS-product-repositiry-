import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { generateReport, getReport, listReports } from "../api/reports";
import { Markdown } from "./Markdown";

/**
 * Reusable reports panel. `audiences` are the report types the current viewer
 * may generate/see (tutor: all; parent: parent; student: student).
 */
export function ReportsPanel({
  studentId,
  audiences,
  canGenerate = true,
}: {
  studentId: number;
  audiences: ("student" | "tutor" | "parent")[];
  canGenerate?: boolean;
}) {
  const queryClient = useQueryClient();
  const reports = useQuery({
    queryKey: ["reports", studentId],
    queryFn: () => listReports(studentId),
    refetchInterval: (query) =>
      query.state.data?.some((r) => r.status === "generating") ? 3000 : false,
  });
  const [openId, setOpenId] = useState<number | null>(null);
  const [audience, setAudience] = useState(audiences[0]);

  const opened = useQuery({
    queryKey: ["report", openId],
    queryFn: () => getReport(openId!),
    enabled: openId !== null,
    refetchInterval: (query) =>
      query.state.data?.status === "generating" ? 3000 : false,
  });

  const generate = useMutation({
    mutationFn: () => generateReport({ student_id: studentId, audience }),
    onSuccess: (report) => {
      queryClient.invalidateQueries({ queryKey: ["reports", studentId] });
      setOpenId(report.id);
    },
  });

  return (
    <div className="rounded-lg border bg-white p-4">
      <div className="flex items-center justify-between">
        <h3 className="font-medium text-slate-800">Reports</h3>
        {canGenerate && (
          <div className="flex items-center gap-2">
            {audiences.length > 1 && (
              <select
                className="rounded border border-slate-300 px-2 py-1 text-sm"
                value={audience}
                onChange={(e) => setAudience(e.target.value as typeof audience)}
              >
                {audiences.map((a) => (
                  <option key={a} value={a}>
                    {a} report
                  </option>
                ))}
              </select>
            )}
            <button
              onClick={() => generate.mutate()}
              disabled={generate.isPending}
              className="rounded-md bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
            >
              Generate report
            </button>
          </div>
        )}
      </div>

      {!canGenerate && (
        <p className="mt-1 text-sm text-slate-500">
          Your tutor generates reports — new ones appear here.
        </p>
      )}

      <ul className="mt-3 divide-y text-sm">
        {reports.data?.map((r) => (
          <li key={r.id} className="flex items-center justify-between py-2">
            <button
              onClick={() => setOpenId(r.id)}
              className="text-left text-blue-600 hover:underline"
            >
              {r.title}
            </button>
            <span
              className={`rounded-full px-2 py-0.5 text-xs ${
                r.status === "ready"
                  ? "bg-green-100 text-green-700"
                  : r.status === "failed"
                    ? "bg-red-100 text-red-700"
                    : "bg-amber-100 text-amber-700"
              }`}
            >
              {r.status === "generating" ? "generating…" : r.status}
            </span>
          </li>
        ))}
        {reports.data?.length === 0 && (
          <li className="py-2 text-slate-500">No reports yet.</li>
        )}
      </ul>

      {openId !== null && opened.data && (
        <div className="mt-4 rounded-lg border bg-slate-50 p-4">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-slate-600">{opened.data.title}</span>
            <button
              onClick={() => setOpenId(null)}
              className="text-sm text-slate-400 hover:text-slate-700"
            >
              Close
            </button>
          </div>
          <div className="mt-3">
            {opened.data.status === "generating" && (
              <p className="text-sm text-slate-500">Writing the report…</p>
            )}
            {opened.data.status === "failed" && (
              <p className="text-sm text-red-600">
                Could not generate this report ({opened.data.error}).
              </p>
            )}
            {opened.data.status === "ready" && opened.data.content && (
              <Markdown content={opened.data.content} />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
