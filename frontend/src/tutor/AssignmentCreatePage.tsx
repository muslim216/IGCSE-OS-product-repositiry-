import { useRef, useState, type DragEvent, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileUp } from "lucide-react";
import { getGroup } from "../api/groups";
import { createAssignment, listClassifieds, uploadAssignment } from "../api/homework";
import { ApiError } from "../api/client";

const ACCEPT = "application/pdf,image/*,.heic,.heif";

/**
 * Setting homework is one action: drop the paper in. The title falls back to
 * the file name, extraction publishes automatically, and everything else is
 * optional detail behind a disclosure.
 */
export default function AssignmentCreatePage() {
  const { groupId } = useParams();
  const gid = Number(groupId);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);

  const group = useQuery({ queryKey: ["group", gid], queryFn: () => getGroup(gid) });
  const subjectId = group.data?.subject.id;
  const classifieds = useQuery({
    queryKey: ["classifieds", subjectId],
    queryFn: () => listClassifieds(subjectId),
    enabled: subjectId !== undefined,
  });

  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [reuseId, setReuseId] = useState<number | "">("");
  const [showDetails, setShowDetails] = useState(false);
  const [markScheme, setMarkScheme] = useState<File | null>(null);
  const [form, setForm] = useState({ title: "", instructions: "", due_at: "", question_range: "" });
  const [error, setError] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: async () => {
      const instructions = form.instructions || undefined;
      const due_at = form.due_at ? new Date(form.due_at).toISOString() : null;
      const question_range = form.question_range || null;
      if (file) {
        return uploadAssignment({
          group_id: gid,
          file,
          mark_scheme: markScheme,
          title: form.title || undefined,
          instructions,
          due_at,
          question_range,
        });
      }
      if (reuseId !== "") {
        const chosen = classifieds.data?.find((c) => c.id === reuseId);
        return createAssignment({
          group_id: gid,
          classified_id: reuseId as number,
          title: form.title || chosen?.title || "Homework",
          instructions,
          due_at,
          question_range,
        });
      }
      // No paper at all: an empty assignment the tutor fills in by hand.
      return createAssignment({
        group_id: gid,
        title: form.title || "Homework",
        instructions,
        due_at,
        question_range: null,
      });
    },
    onSuccess: (assignment) => {
      queryClient.invalidateQueries({ queryKey: ["assignments", gid] });
      navigate(`/tutor/assignments/${assignment.id}`);
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });

  function pick(next: File | null) {
    setFile(next);
    if (next) setReuseId("");
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) pick(dropped);
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    create.mutate();
  }

  const canSubmit = file !== null || reuseId !== "" || form.title.trim() !== "";

  return (
    <div className="max-w-2xl">
      <Link
        to={`/tutor/groups/${gid}/homework`}
        className="text-sm text-brand-600 hover:underline"
      >
        ← All homework
      </Link>
      <h3 className="mt-1 font-semibold text-ink-900">Set homework</h3>
      <p className="mt-1 text-sm text-ink-500">
        Drop in a paper and you're done — the questions are extracted and it goes out to students
        automatically. You can still edit the question list until someone submits.
      </p>

      <form onSubmit={onSubmit} className="mt-5 space-y-4">
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`flex w-full flex-col items-center gap-2 rounded-xl border-2 border-dashed px-6 py-10 text-center transition ${
            dragging
              ? "border-brand-600 bg-brand-50"
              : "border-line-strong bg-surface hover:border-brand-600"
          }`}
        >
          <FileUp aria-hidden className="h-8 w-8 text-brand-600" />
          {file ? (
            <>
              <span className="font-medium text-ink-900">{file.name}</span>
              <span className="text-xs text-ink-400">Click to choose a different file</span>
            </>
          ) : (
            <>
              <span className="font-medium text-ink-700">
                Drop the question paper here, or click to browse
              </span>
              <span className="text-xs text-ink-400">PDF or photos — including iPhone HEIC</span>
            </>
          )}
        </button>
        {file && (
          <button
            type="button"
            onClick={() => pick(null)}
            className="text-xs text-ink-400 underline hover:text-ink-700"
          >
            Remove this file
          </button>
        )}
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          className="hidden"
          onChange={(e) => pick(e.target.files?.[0] ?? null)}
        />

        {!file && classifieds.data && classifieds.data.length > 0 && (
          <label className="block text-sm">
            <span className="mb-1 block text-xs font-medium text-ink-500">
              …or reuse a paper you've uploaded before
            </span>
            <select
              className="w-full rounded-md border border-line px-3 py-2 text-sm"
              value={reuseId}
              onChange={(e) => setReuseId(e.target.value === "" ? "" : Number(e.target.value))}
            >
              <option value="">Choose a previous paper…</option>
              {classifieds.data.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.title} {c.mark_scheme_name ? "(with mark scheme)" : ""}
                </option>
              ))}
            </select>
          </label>
        )}

        <div className="rounded-xl border border-line bg-surface">
          <button
            type="button"
            onClick={() => setShowDetails((v) => !v)}
            className="flex w-full items-center justify-between px-4 py-3 text-sm font-medium text-ink-700"
            aria-expanded={showDetails}
          >
            Optional details
            <span className="text-ink-400">{showDetails ? "−" : "+"}</span>
          </button>
          {showDetails && (
            <div className="space-y-3 border-t border-line px-4 py-4">
              <label className="block text-sm">
                <span className="mb-1 block text-xs font-medium text-ink-500">
                  Title (defaults to the file name)
                </span>
                <input
                  className="w-full rounded-md border border-line px-3 py-2 text-sm"
                  placeholder="e.g. HW3 — Atomic structure"
                  value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                />
              </label>
              {file && (
                <label className="block text-sm">
                  <span className="mb-1 block text-xs font-medium text-ink-500">
                    Mark scheme (skip if the answers are inside the paper)
                  </span>
                  <input
                    type="file"
                    accept={ACCEPT}
                    className="text-sm"
                    onChange={(e) => setMarkScheme(e.target.files?.[0] ?? null)}
                  />
                </label>
              )}
              <label className="block text-sm">
                <span className="mb-1 block text-xs font-medium text-ink-500">
                  Question range (leave empty for the whole booklet)
                </span>
                <input
                  className="w-full rounded-md border border-line px-3 py-2 text-sm"
                  placeholder='e.g. "Q1-15" or "pages 3-10"'
                  value={form.question_range}
                  onChange={(e) => setForm({ ...form, question_range: e.target.value })}
                />
              </label>
              <label className="block text-sm">
                <span className="mb-1 block text-xs font-medium text-ink-500">Due date</span>
                <input
                  type="datetime-local"
                  className="rounded-md border border-line px-3 py-2 text-sm"
                  value={form.due_at}
                  onChange={(e) => setForm({ ...form, due_at: e.target.value })}
                />
              </label>
              <label className="block text-sm">
                <span className="mb-1 block text-xs font-medium text-ink-500">Instructions</span>
                <textarea
                  className="w-full rounded-md border border-line px-3 py-2 text-sm"
                  rows={2}
                  placeholder="Anything the students should know"
                  value={form.instructions}
                  onChange={(e) => setForm({ ...form, instructions: e.target.value })}
                />
              </label>
            </div>
          )}
        </div>

        {!file && reuseId === "" && (
          <p className="text-xs text-ink-400">
            No paper? Give it a title under “Optional details” and an empty assignment is created
            for you to type the questions into.
          </p>
        )}
        {error && <p className="text-sm text-risk-600">{error}</p>}
        <button
          type="submit"
          disabled={create.isPending || !canSubmit}
          className="rounded-md bg-brand-600 px-4 py-2 font-medium hover:bg-brand-700 disabled:opacity-50"
        >
          {create.isPending ? "Uploading…" : "Set homework"}
        </button>
      </form>
    </div>
  );
}
