import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getGroup } from "../api/groups";
import { createAssignment, listClassifieds, uploadAssignment } from "../api/homework";
import { ApiError } from "../api/client";
import { Button, Card, DropZone, Field, Input, Select, Textarea } from "../ui";

/** Strip the extension so the suggested title reads like a title. */
function titleFromFile(name: string): string {
  return name.replace(/\.[^.]+$/, "");
}

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

  const [file, setFile] = useState<File | null>(null);
  const [markScheme, setMarkScheme] = useState<File | null>(null);
  const [reuseId, setReuseId] = useState<number | "">("");
  const [showDetails, setShowDetails] = useState(false);
  const [details, setDetails] = useState({ title: "", instructions: "", due_at: "", question_range: "" });
  const [error, setError] = useState<string | null>(null);

  const suggestedTitle = file ? titleFromFile(file.name) : "";

  const create = useMutation({
    mutationFn: () => {
      const shared = {
        instructions: details.instructions || undefined,
        due_at: details.due_at ? new Date(details.due_at).toISOString() : null,
        question_range: details.question_range || null,
      };
      // Reusing a paper still needs the two-step call; a fresh upload is one request.
      if (reuseId !== "") {
        const existing = classifieds.data?.find((c) => c.id === reuseId);
        return createAssignment({
          group_id: gid,
          classified_id: reuseId,
          title: details.title || existing?.title || "Homework",
          ...shared,
        });
      }
      if (!file) throw new Error("Add the question paper first.");
      return uploadAssignment({
        group_id: gid,
        file,
        mark_scheme: markScheme,
        title: details.title || undefined,
        ...shared,
      });
    },
    onSuccess: (assignment) => {
      queryClient.invalidateQueries({ queryKey: ["assignments", gid] });
      queryClient.invalidateQueries({ queryKey: ["group", gid] });
      navigate(`/tutor/groups/${gid}/homework/${assignment.id}`);
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    create.mutate();
  }

  const ready = file !== null || reuseId !== "";
  const recent = classifieds.data?.slice(0, 5) ?? [];

  return (
    <div className="max-w-2xl">
      <Link to={`/tutor/groups/${gid}/homework`} className="text-sm text-brand-600 hover:underline">
        ← All homework
      </Link>
      <h2 className="mt-1 text-xl font-semibold text-slate-900">Set homework</h2>
      <p className="mt-1 text-sm text-slate-500">
        Add the question paper — the questions and marks are read from it automatically, and
        students can start as soon as that finishes.
      </p>

      <form onSubmit={onSubmit} className="mt-5 space-y-4">
        <DropZone
          label={file ? "Question paper added" : "Drop the question paper here"}
          hint="PDF or photos. Click to browse."
          accept="application/pdf,image/*"
          files={file ? [file] : []}
          onFiles={(files) => {
            setFile(files[0] ?? null);
            if (files[0]) setReuseId("");
          }}
        />

        {recent.length > 0 && !file && (
          <Field label="Or reuse a paper you've already uploaded">
            {(props) => (
              <Select
                {...props}
                value={reuseId}
                onChange={(e) => setReuseId(e.target.value === "" ? "" : Number(e.target.value))}
              >
                <option value="">Choose a paper…</option>
                {recent.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.title}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        )}

        <button
          type="button"
          onClick={() => setShowDetails((v) => !v)}
          className="text-sm text-brand-600 hover:underline"
        >
          {showDetails ? "Hide options" : "Add a title, due date or mark scheme"}
        </button>

        {showDetails && (
          <Card className="space-y-4 p-4">
            <Field
              label="Title"
              hint={suggestedTitle ? `Defaults to “${suggestedTitle}”` : "Defaults to the file name"}
            >
              {(props) => (
                <Input
                  {...props}
                  value={details.title}
                  onChange={(e) => setDetails({ ...details, title: e.target.value })}
                  placeholder={suggestedTitle}
                />
              )}
            </Field>

            <div className="flex flex-wrap gap-3">
              <Field label="Due" className="flex-1 basis-52">
                {(props) => (
                  <Input
                    {...props}
                    type="datetime-local"
                    value={details.due_at}
                    onChange={(e) => setDetails({ ...details, due_at: e.target.value })}
                  />
                )}
              </Field>
              <Field label="Only these questions" hint="e.g. Q1–15" className="flex-1 basis-40">
                {(props) => (
                  <Input
                    {...props}
                    value={details.question_range}
                    onChange={(e) => setDetails({ ...details, question_range: e.target.value })}
                    placeholder="All questions"
                  />
                )}
              </Field>
            </div>

            <Field label="Instructions for students">
              {(props) => (
                <Textarea
                  {...props}
                  rows={2}
                  value={details.instructions}
                  onChange={(e) => setDetails({ ...details, instructions: e.target.value })}
                  placeholder="Optional"
                />
              )}
            </Field>

            {!reuseId && (
              <div>
                <p className="mb-1 text-sm font-medium text-slate-700">Mark scheme</p>
                <p className="mb-2 text-xs text-slate-500">
                  Optional. With one, the AI can mark answers itself; without it, questions are
                  flagged for you to mark.
                </p>
                <DropZone
                  label={markScheme ? "Mark scheme added" : "Add a mark scheme"}
                  accept="application/pdf,image/*"
                  files={markScheme ? [markScheme] : []}
                  onFiles={(files) => setMarkScheme(files[0] ?? null)}
                />
              </div>
            )}
          </Card>
        )}

        {error && <p className="text-sm text-risk-600">{error}</p>}

        <Button type="submit" disabled={!ready || create.isPending}>
          {create.isPending ? "Uploading…" : "Set homework"}
        </Button>
      </form>
    </div>
  );
}
