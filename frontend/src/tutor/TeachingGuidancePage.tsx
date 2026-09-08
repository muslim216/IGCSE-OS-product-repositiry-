import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { listSubjects } from "../api/groups";
import {
  deleteTeachingGuidance,
  getTeachingGuidance,
  teachingGuidanceFilePath,
  uploadTeachingGuidance,
} from "../api/teachingGuidance";
import { ApiError } from "../api/client";
import { AuthFileLink } from "../components/AuthFile";
import { EmptyState, useToast } from "../components/ui";
import { ABSENT } from "../lib/labels";

/**
 * Teaching guidance — the scheme of work, the second document a subject is set
 * up with beside its syllabus (`AV-10`, onboarding step 4).
 *
 * One document per subject: uploading again replaces it, which is why there is
 * a Replace control and no list. Nothing reads it yet — Phase 6's plan is what
 * uses it to judge which chapters are harder or slower (`AV-14`) — so this page
 * says what it is for rather than implying an effect it does not yet have
 * (`PROD-1`).
 */
export default function TeachingGuidancePage() {
  const queryClient = useQueryClient();
  const { toast, showToast } = useToast();
  const subjects = useQuery({ queryKey: ["subjects"], queryFn: listSubjects });
  const [subjectId, setSubjectId] = useState<number | null>(null);
  const selected = subjectId ?? subjects.data?.[0]?.id ?? null;

  const guidance = useQuery({
    queryKey: ["teaching-guidance", selected],
    queryFn: () => getTeachingGuidance(selected!),
    enabled: selected !== null,
  });

  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);

  const upload = useMutation({
    mutationFn: () => uploadTeachingGuidance(selected!, file!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["teaching-guidance", selected] });
      setFile(null);
      showToast("Teaching guidance saved.");
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });

  const remove = useMutation({
    mutationFn: () => deleteTeachingGuidance(selected!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["teaching-guidance", selected] });
      showToast("Teaching guidance removed.");
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (file && selected !== null) upload.mutate();
  }

  if (subjects.isLoading) {
    return (
      <div aria-busy="true">
        <span aria-hidden className="block h-24 w-full animate-pulse rounded bg-surface-muted" />
      </div>
    );
  }
  if (subjects.isError || !subjects.data || subjects.data.length === 0) {
    return (
      <EmptyState
        title="No subjects yet."
        hint="Teaching guidance is kept per subject — add a syllabus first."
      />
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="font-display text-xl font-semibold text-ink-900">Teaching guidance</h2>
        <p className="mt-1 max-w-prose text-sm text-ink-500">
          Your scheme of work for a subject — the order you teach it in and how long each chapter
          takes. Kept beside the syllabus and read when your teaching plan is built. One document
          per subject; uploading again replaces it.
        </p>
      </div>

      <select
        aria-label="Subject"
        value={selected ?? ""}
        onChange={(e) => setSubjectId(Number(e.target.value))}
        className="rounded-md border border-line-control bg-surface px-3 py-2 text-sm"
      >
        {subjects.data.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name} ({s.exam_board} {s.code})
          </option>
        ))}
      </select>

      {guidance.isLoading ? (
        <span aria-hidden className="block h-24 w-full animate-pulse rounded bg-surface-muted" />
      ) : guidance.isError || !guidance.data ? (
        <p className="text-sm text-ink-500">{ABSENT.loadFailed}</p>
      ) : (
        <section className="rounded-lg border border-line bg-surface p-4">
          {guidance.data.uploaded ? (
            <div className="flex flex-wrap items-center gap-3">
              <div>
                <p className="text-sm font-medium text-ink-900">{guidance.data.file_name}</p>
                <p className="text-xs text-ink-500">
                  Uploaded{" "}
                  {guidance.data.uploaded_at
                    ? new Date(guidance.data.uploaded_at).toLocaleDateString()
                    : ""}
                </p>
              </div>
              <AuthFileLink path={teachingGuidanceFilePath(selected!)} label="Open" />
              <button
                onClick={() => remove.mutate()}
                disabled={remove.isPending}
                className="rounded-md border border-line-control px-3 py-1.5 text-sm text-ink-700 hover:border-line-strong disabled:opacity-40"
              >
                {remove.isPending ? "Removing…" : "Remove"}
              </button>
            </div>
          ) : (
            // Absent is stated, never drawn as an empty row (PROD-2, UX-19).
            <p className="text-sm text-ink-500">
              No teaching guidance for this subject yet. Your plan will be built from the syllabus
              alone until you add one.
            </p>
          )}

          <form
            onSubmit={onSubmit}
            className="mt-4 flex flex-wrap items-end gap-3 border-t border-line pt-4"
          >
            <div>
              <label htmlFor="guidance-file" className="block text-sm font-medium text-ink-700">
                {guidance.data.uploaded ? "Replace it" : "Upload a document"}
              </label>
              <input
                id="guidance-file"
                type="file"
                accept="application/pdf,image/*"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="mt-1 text-sm"
              />
            </div>
            <button
              type="submit"
              disabled={!file || upload.isPending}
              className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-canvas hover:bg-brand-700 disabled:opacity-50"
            >
              {upload.isPending ? "Uploading…" : guidance.data.uploaded ? "Replace" : "Upload"}
            </button>
          </form>
          {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
        </section>
      )}
      {toast}
    </div>
  );
}
