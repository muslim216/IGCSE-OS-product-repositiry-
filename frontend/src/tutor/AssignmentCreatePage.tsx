import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getGroup } from "../api/groups";
import { createAssignment, listClassifieds, uploadClassified } from "../api/homework";
import { ApiError } from "../api/client";

export default function AssignmentCreatePage() {
  const { groupId } = useParams();
  const gid = Number(groupId);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const group = useQuery({ queryKey: ["group", gid], queryFn: () => getGroup(gid) });
  const subjectId = group.data?.subject.id;
  const classifieds = useQuery({
    queryKey: ["classifieds", subjectId],
    queryFn: () => listClassifieds(subjectId),
    enabled: subjectId !== undefined,
  });

  const [mode, setMode] = useState<"existing" | "upload">("upload");
  const [classifiedId, setClassifiedId] = useState<number | "">("");
  const [newClassified, setNewClassified] = useState({ title: "" });
  const [file, setFile] = useState<File | null>(null);
  const [markScheme, setMarkScheme] = useState<File | null>(null);
  const [form, setForm] = useState({
    title: "",
    instructions: "",
    due_at: "",
    question_range: "",
  });
  const [error, setError] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: async () => {
      let cid = classifiedId as number;
      if (mode === "upload") {
        if (!file || !subjectId) throw new Error("Choose the classified PDF first");
        const uploaded = await uploadClassified({
          title: newClassified.title || file.name,
          subject_id: subjectId,
          file,
          mark_scheme: markScheme,
        });
        cid = uploaded.id;
      }
      return createAssignment({
        group_id: gid,
        classified_id: cid,
        title: form.title,
        instructions: form.instructions || undefined,
        due_at: form.due_at ? new Date(form.due_at).toISOString() : null,
        question_range: form.question_range || null,
      });
    },
    onSuccess: (assignment) => {
      queryClient.invalidateQueries({ queryKey: ["assignments", gid] });
      navigate(`/tutor/assignments/${assignment.id}`);
    },
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : String(err)),
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    create.mutate();
  }

  return (
    <div className="max-w-2xl">
      <Link to={`/tutor/groups/${gid}`} className="text-sm text-blue-600 hover:underline">
        ← {group.data?.name ?? "Group"}
      </Link>
      <h2 className="mt-1 text-xl font-semibold text-slate-800">New homework</h2>
      <p className="mt-1 text-sm text-slate-500">
        Upload a classified (question booklet) — the AI reads it and builds the question list
        for you to check before publishing.
      </p>

      <form onSubmit={onSubmit} className="mt-6 space-y-5">
        <div className="rounded-lg border bg-white p-4">
          <div className="flex gap-4 text-sm">
            <label className="flex items-center gap-1.5">
              <input
                type="radio"
                checked={mode === "upload"}
                onChange={() => setMode("upload")}
              />
              Upload a new classified
            </label>
            <label className="flex items-center gap-1.5">
              <input
                type="radio"
                checked={mode === "existing"}
                onChange={() => setMode("existing")}
                disabled={!classifieds.data?.length}
              />
              Reuse an uploaded one
            </label>
          </div>

          {mode === "upload" ? (
            <div className="mt-3 space-y-3">
              <div>
                <label className="block text-sm font-medium text-slate-700">
                  Classified PDF <span className="text-red-500">*</span>
                </label>
                <input
                  type="file"
                  accept="application/pdf,image/*"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                  className="mt-1 text-sm"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700">
                  Mark scheme (optional — skip if answers are inside the classified)
                </label>
                <input
                  type="file"
                  accept="application/pdf,image/*"
                  onChange={(e) => setMarkScheme(e.target.files?.[0] ?? null)}
                  className="mt-1 text-sm"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700">
                  Name this classified (for reuse later)
                </label>
                <input
                  className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                  placeholder="e.g. Atomic structure classified"
                  value={newClassified.title}
                  onChange={(e) => setNewClassified({ title: e.target.value })}
                />
              </div>
            </div>
          ) : (
            <select
              className="mt-3 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              value={classifiedId}
              onChange={(e) => setClassifiedId(Number(e.target.value))}
              required
            >
              <option value="" disabled>
                Choose a classified…
              </option>
              {classifieds.data?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.title} {c.mark_scheme_name ? "(with mark scheme)" : ""}
                </option>
              ))}
            </select>
          )}
        </div>

        <div className="rounded-lg border bg-white p-4 space-y-3">
          <div>
            <label className="block text-sm font-medium text-slate-700">
              Homework title <span className="text-red-500">*</span>
            </label>
            <input
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              placeholder="e.g. HW3 — Atomic structure Q1–15"
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700">
              Question range (optional — leave empty for the whole booklet)
            </label>
            <input
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              placeholder='e.g. "Q1-15" or "pages 3-10"'
              value={form.question_range}
              onChange={(e) => setForm({ ...form, question_range: e.target.value })}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700">Due date</label>
            <input
              type="datetime-local"
              className="mt-1 rounded-md border border-slate-300 px-3 py-2 text-sm"
              value={form.due_at}
              onChange={(e) => setForm({ ...form, due_at: e.target.value })}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700">Instructions</label>
            <textarea
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              rows={2}
              placeholder="Anything the students should know"
              value={form.instructions}
              onChange={(e) => setForm({ ...form, instructions: e.target.value })}
            />
          </div>
        </div>

        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={create.isPending}
          className="rounded-md bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {create.isPending ? "Uploading…" : "Create & extract questions"}
        </button>
      </form>
    </div>
  );
}
