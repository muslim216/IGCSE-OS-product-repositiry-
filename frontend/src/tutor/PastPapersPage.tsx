import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  deleteExaminerReport,
  examinerReportPath,
  listExaminerReports,
  listPastPapers,
  pastPaperBookletPath,
  pastPaperMarkSchemePath,
  uploadExaminerReport,
  uploadPastPaper,
  type ExaminerReport,
  type PastPaper,
} from "../api/pastPapers";
import { listSubjects } from "../api/groups";
import { AuthFileLink } from "../components/AuthFile";
import { ApiError } from "../api/client";

/**
 * The examiner report for one paper sitting.
 *
 * The library is shared across tutors — one upload of "Chemistry 5070 Paper 2,
 * June 2022" serves everybody — so a report someone else added shows as
 * present and readable but not removable. `can_manage` carries that.
 */
function ExaminerReportRow({
  paper,
  report,
}: {
  paper: PastPaper;
  report: ExaminerReport | undefined;
}) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["examiner-reports"] });

  const upload = useMutation({
    mutationFn: (file: File) =>
      uploadExaminerReport({
        subject_id: paper.subject_id,
        paper_number: paper.paper_number,
        session_label: paper.session_label,
        file,
      }),
    onSuccess: () => {
      setError(null);
      invalidate();
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });

  const remove = useMutation({
    mutationFn: () => deleteExaminerReport(report!.id),
    onSuccess: invalidate,
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });

  return (
    <div className="mt-2 border-t pt-2 text-xs">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-slate-500">Examiner report</span>
        {report ? (
          <>
            <AuthFileLink path={examinerReportPath(report.id)} label={report.file_name} />
            {report.can_manage && (
              <button
                type="button"
                onClick={() => remove.mutate()}
                disabled={remove.isPending}
                className="text-slate-500 underline hover:text-red-600 disabled:opacity-50"
              >
                Remove
              </button>
            )}
          </>
        ) : (
          <label className="text-slate-500">
            <span className="sr-only">Add the examiner report for this paper</span>
            <input
              type="file"
              accept="application/pdf,image/*"
              disabled={upload.isPending}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) upload.mutate(file);
              }}
              className="block text-xs"
            />
          </label>
        )}
      </div>
      {!report && (
        <p className="mt-1 text-slate-400">
          Shared with every tutor once added, and used when marking this paper —
          it tells the marker how the board read its own scheme.
        </p>
      )}
      {error && <p className="mt-1 text-red-600">{error}</p>}
    </div>
  );
}

export default function PastPapersPage() {
  const queryClient = useQueryClient();
  const papers = useQuery({ queryKey: ["past-papers"], queryFn: () => listPastPapers() });
  const subjects = useQuery({ queryKey: ["subjects"], queryFn: listSubjects });
  const reports = useQuery({
    queryKey: ["examiner-reports"],
    queryFn: () => listExaminerReports(),
  });
  const reportFor = (p: PastPaper) =>
    reports.data?.find(
      (r) =>
        r.subject_id === p.subject_id &&
        r.paper_number === p.paper_number &&
        r.session_label === p.session_label,
    );

  const [subjectId, setSubjectId] = useState("");
  const [sessionLabel, setSessionLabel] = useState("");
  const [paperNumber, setPaperNumber] = useState("");
  const [duration, setDuration] = useState("");
  const [booklet, setBooklet] = useState<File | null>(null);
  const [markScheme, setMarkScheme] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);

  const upload = useMutation({
    mutationFn: () =>
      uploadPastPaper({
        subject_id: Number(subjectId),
        session_label: sessionLabel,
        paper_number: paperNumber,
        booklet: booklet!,
        mark_scheme: markScheme!,
        duration_minutes: duration ? Number(duration) : null,
      }),
    onSuccess: () => {
      setSessionLabel("");
      setPaperNumber("");
      setDuration("");
      setBooklet(null);
      setMarkScheme(null);
      queryClient.invalidateQueries({ queryKey: ["past-papers"] });
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });

  const ready = subjectId && sessionLabel && paperNumber && booklet && markScheme;

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (ready) upload.mutate();
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-slate-800">Past papers</h2>
        <p className="text-sm text-slate-500">
          Upload a full paper once and every student taking that subject can sit
          it. Their answers are marked question by question, feeding both topic
          mastery and their past-paper score.
        </p>
      </div>

      <form onSubmit={onSubmit} className="space-y-3 rounded-lg border bg-white p-4">
        <h3 className="font-medium text-slate-800">Add a paper</h3>
        <div className="grid gap-3 sm:grid-cols-2">
          <select
            value={subjectId}
            onChange={(e) => setSubjectId(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1.5 text-sm"
          >
            <option value="">Subject…</option>
            {subjects.data?.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.exam_board})
              </option>
            ))}
          </select>
          <input
            value={sessionLabel}
            onChange={(e) => setSessionLabel(e.target.value)}
            placeholder="Session, e.g. November 2026"
            className="rounded border border-slate-300 px-2 py-1.5 text-sm"
          />
          <input
            value={paperNumber}
            onChange={(e) => setPaperNumber(e.target.value)}
            placeholder="Paper, e.g. Paper 1"
            className="rounded border border-slate-300 px-2 py-1.5 text-sm"
          />
          <input
            type="number"
            value={duration}
            onChange={(e) => setDuration(e.target.value)}
            placeholder="Time allowed (minutes)"
            className="rounded border border-slate-300 px-2 py-1.5 text-sm"
          />
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-sm text-slate-600">
            Question paper
            <input
              type="file"
              accept="application/pdf,image/*"
              onChange={(e) => setBooklet(e.target.files?.[0] ?? null)}
              className="mt-1 block w-full text-sm"
            />
          </label>
          <label className="text-sm text-slate-600">
            Official mark scheme <span className="text-red-600">*</span>
            <input
              type="file"
              accept="application/pdf,image/*"
              onChange={(e) => setMarkScheme(e.target.files?.[0] ?? null)}
              className="mt-1 block w-full text-sm"
            />
          </label>
        </div>
        <p className="text-xs text-slate-500">
          The mark scheme is required — a full paper contributes to a predicted
          grade, so its marks can't rest on the AI's judgement alone. Students
          can open the question paper but never the mark scheme.
        </p>

        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={!ready || upload.isPending}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {upload.isPending ? "Uploading…" : "Add past paper"}
        </button>
      </form>

      <div className="rounded-lg border bg-white p-4">
        <h3 className="font-medium text-slate-800">Your papers</h3>
        <ul className="mt-2 divide-y text-sm">
          {papers.data?.map((p) => (
            <li key={p.id} className="py-3">
              <div className="flex items-start justify-between">
                <div>
                  <div className="font-medium text-slate-800">
                    {p.session_label} · {p.paper_number}
                  </div>
                  <div className="text-slate-500">
                    {p.question_count > 0
                      ? `${p.question_count} questions${p.total_marks ? ` · ${p.total_marks} marks` : ""}`
                      : "Reading the questions out of the paper…"}
                    {p.duration_minutes ? ` · ${p.duration_minutes} min` : ""}
                  </div>
                  {p.extraction_error && (
                    <div className="mt-1 text-amber-700">
                      Couldn't read the questions: {p.extraction_error}
                    </div>
                  )}
                </div>
                <div className="flex gap-3 text-xs">
                  <AuthFileLink path={pastPaperBookletPath(p.id)} label="Paper" />
                  <AuthFileLink path={pastPaperMarkSchemePath(p.id)} label="Mark scheme" />
                </div>
              </div>
              <ExaminerReportRow paper={p} report={reportFor(p)} />
            </li>
          ))}
          {papers.data?.length === 0 && (
            <li className="py-2 text-slate-500">No past papers yet.</li>
          )}
        </ul>
      </div>
    </div>
  );
}
