import { useEffect, useRef, useState, type DragEvent, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ChevronDown, FileUp } from "lucide-react";
import { getGroup } from "../api/groups";
import {
  MAX_CLASSIFIED_NOTES,
  createAssignment,
  listClassifieds,
  updateClassified,
  uploadAssignment,
} from "../api/homework";
import { listChapters } from "../api/syllabus";
import { friendlyError } from "../lib/errors";
import {
  Button,
  Field,
  FileInput,
  Input,
  Select,
  Textarea,
  buttonClasses,
} from "../components/controls";
import { Reveal } from "../components/ui";

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
  // A classified belongs to the chapter the tutor is starting (AV-20). A subject
  // whose syllabus was never extracted chapter-first has none, and the picker
  // simply does not render — nothing here invents structure the tutor never
  // approved (PROD-2).
  const chapters = useQuery({
    queryKey: ["chapters", subjectId],
    queryFn: () => listChapters(subjectId!),
    enabled: subjectId !== undefined,
  });

  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [reuseId, setReuseId] = useState<number | "">("");
  const [showDetails, setShowDetails] = useState(false);
  const [markScheme, setMarkScheme] = useState<File | null>(null);
  const [form, setForm] = useState({ title: "", instructions: "", due_at: "", question_range: "" });
  // The classified's chapter and its marking notes (AV-20, AV-21). They describe
  // the paper, not this piece of homework, so on the reuse path they are the
  // chosen classified's existing values and saving them is an edit of it.
  const [chapterId, setChapterId] = useState<number | "">("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);

  const reused = reuseId === "" ? undefined : classifieds.data?.find((c) => c.id === reuseId);
  // Seeded from the chosen classified, and cleared when the choice is cleared.
  // Keyed on the id rather than the row so a background refetch of the list
  // cannot overwrite what the tutor has typed since (the same guard the
  // marking-rules editor needs, for the same reason).
  const hydratedFor = useRef<number | "">("");
  useEffect(() => {
    if (hydratedFor.current === reuseId) return;
    if (reuseId === "") {
      hydratedFor.current = "";
      setChapterId("");
      setNotes("");
    } else if (reused) {
      hydratedFor.current = reuseId;
      setChapterId(reused.chapter_id ?? "");
      setNotes(reused.notes ?? "");
    }
    // A chosen id whose row has not arrived yet is left unhydrated on purpose,
    // so the render that does have it seeds the fields.
  }, [reuseId, reused]);

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
          chapter_id: chapterId === "" ? null : chapterId,
          notes,
        });
      }
      if (reuseId !== "") {
        // Save the classified's chapter and notes first, and only when they have
        // actually changed: they are marking context the AI will act on, so a
        // correction must land before work is set from it. Ordered this way on
        // purpose — homework created against stale notes would be marked
        // against them.
        if (reused && ((reused.chapter_id ?? "") !== chapterId || (reused.notes ?? "") !== notes)) {
          await updateClassified(reuseId, {
            chapter_id: chapterId === "" ? null : chapterId,
            notes,
          });
          queryClient.invalidateQueries({ queryKey: ["classifieds", subjectId] });
        }
        return createAssignment({
          group_id: gid,
          classified_id: reuseId as number,
          title: form.title || reused?.title || "Homework",
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
      // An uploaded or re-filed classified also changes the Library's record. By
      // prefix: every key under it is a plain classifieds list, safe to refetch.
      queryClient.invalidateQueries({ queryKey: ["classifieds"] });
      navigate(`/tutor/assignments/${assignment.id}`);
    },
    onError: (err) => setError(friendlyError(err, "Couldn't set the homework. Try again.")),
  });

  function pick(next: File | null) {
    setFile(next);
    if (next) setReuseId("");
    // The mark-scheme input only renders while a paper is chosen, so a leftover
    // one would be invisible — and would attach to whatever paper came next.
    setMarkScheme(null);
    // Same argument, and it matters more here: the chapter and the notes
    // describe *this paper*, and swapping the file after typing them would
    // quietly carry marking instructions written about one classified onto
    // another. Retyping them is an annoyance; inheriting them steers a mark
    // (cubic). Clearing the reuse selection above does not reach these — the
    // hydration effect below only fires when the chosen id changes.
    setChapterId("");
    setNotes("");
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
      {/* Rendered inside the class layout, whose header already carries the
          page's one <h1> — so this screen opens on an <h2>. */}
      <Link
        to={`/tutor/groups/${gid}/homework`}
        className="inline-flex items-center gap-1 text-sm text-ink-500 transition-colors hover:text-brand-600"
      >
        <ArrowLeft aria-hidden className="h-3.5 w-3.5" />
        All homework
      </Link>
      <h2 className="mt-2 text-xl text-ink-900">Set homework</h2>
      <p className="mt-1 text-sm text-ink-500">
        Drop in a paper and you're done — the questions are extracted and it goes out to students
        automatically. You can still edit the question list until someone submits.
      </p>

      <form onSubmit={onSubmit} className="mt-6 space-y-5">
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
              : "border-line-control bg-surface hover:border-brand-600 hover:bg-brand-50"
          }`}
        >
          <FileUp aria-hidden className="h-8 w-8 text-brand-600" />
          {file ? (
            <>
              <span className="font-medium text-ink-900">{file.name}</span>
              <span className="text-xs text-ink-500">Click to choose a different file</span>
            </>
          ) : (
            <>
              <span className="font-medium text-ink-900">
                Drop the question paper here, or click to browse
              </span>
              <span className="text-xs text-ink-500">PDF or photos — including iPhone HEIC</span>
            </>
          )}
        </button>
        {file && (
          <Button variant="ghost" size="sm" onClick={() => pick(null)}>
            Remove this file
          </Button>
        )}
        {/* Backs the drop zone's click-to-browse; the zone is the visible,
            focusable control, so this stays hidden rather than a FileInput. */}
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          className="hidden"
          onChange={(e) => pick(e.target.files?.[0] ?? null)}
        />

        {!file && classifieds.data && classifieds.data.length > 0 && (
          <Field label="Or reuse a paper you've uploaded before" optional>
            <Select
              value={reuseId}
              onChange={(e) => setReuseId(e.target.value === "" ? "" : Number(e.target.value))}
            >
              <option value="">Choose a previous paper</option>
              {classifieds.data.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.title} {c.mark_scheme_name ? "(with mark scheme)" : ""}
                </option>
              ))}
            </Select>
          </Field>
        )}

        <div className="rounded-xl border border-line bg-surface">
          <button
            type="button"
            onClick={() => setShowDetails((v) => !v)}
            className="flex w-full items-center justify-between rounded-xl px-4 py-3 text-sm font-medium text-ink-900 hover:bg-surface-muted"
            aria-expanded={showDetails}
          >
            Optional details
            <ChevronDown
              aria-hidden
              className={`h-4 w-4 text-ink-500 transition-transform ${showDetails ? "rotate-180" : ""}`}
            />
          </button>
          <Reveal open={showDetails} className="space-y-4 border-t border-line px-4 py-4">
            {showDetails && (
              <>
                {(file || reuseId !== "") && chapters.data && chapters.data.length > 0 && (
                  <Field label="Chapter this paper belongs to" optional>
                    <Select
                      value={chapterId}
                      onChange={(e) =>
                        setChapterId(e.target.value === "" ? "" : Number(e.target.value))
                      }
                    >
                      <option value="">Not set</option>
                      {chapters.data.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.code} — {c.title}
                        </option>
                      ))}
                    </Select>
                  </Field>
                )}
                {(file || reuseId !== "") && (
                  /* Says what it does and what it does not: these notes never
                   reach when a mark counts (AV-25), and nothing marks with
                   them until task 3.2 — so the copy does not promise an
                   effect the product does not have yet (PROD-1). */
                  <Field
                    label="Marking notes for this paper"
                    optional
                    hint="Kept with the paper and reused every time you set work from it. The official mark scheme always wins. Marking does not read these yet."
                  >
                    <Textarea
                      rows={3}
                      maxLength={MAX_CLASSIFIED_NOTES}
                      placeholder="Anything unusual about how work from this paper should be marked"
                      value={notes}
                      onChange={(e) => setNotes(e.target.value)}
                    />
                  </Field>
                )}
                {/* Optional only when there is something to name the homework
                  after — the file, or the reused paper's own title. With
                  neither, the title is all an empty assignment has, and
                  `canSubmit` already requires it. */}
                <Field
                  label="Title"
                  optional={file !== null || reuseId !== ""}
                  hint={
                    file
                      ? "Leave it empty to use the file name."
                      : reuseId !== ""
                        ? "Leave it empty to use that paper's title."
                        : undefined
                  }
                >
                  <Input
                    placeholder="e.g. HW3 — Atomic structure"
                    value={form.title}
                    onChange={(e) => setForm({ ...form, title: e.target.value })}
                    required={file === null && reuseId === ""}
                  />
                </Field>
                {file && (
                  <Field
                    label="Mark scheme"
                    optional
                    hint="Skip this if the answers are inside the paper."
                  >
                    <FileInput
                      // Remounted per paper: pick() clears the chosen mark scheme
                      // when the paper changes, and the picker must not keep
                      // showing the old file's name over an empty selection.
                      key={`${file.name}-${file.size}-${file.lastModified}`}
                      accept={ACCEPT}
                      prompt="Choose the mark scheme"
                      onFiles={(files) => setMarkScheme(files[0] ?? null)}
                    />
                  </Field>
                )}
                <Field label="Question range" optional hint="Leave it empty for the whole paper.">
                  <Input
                    placeholder='e.g. "Q1-15" or "pages 3-10"'
                    value={form.question_range}
                    onChange={(e) => setForm({ ...form, question_range: e.target.value })}
                  />
                </Field>
                <Field label="Due date" optional>
                  <Input
                    type="datetime-local"
                    className="sm:max-w-xs"
                    value={form.due_at}
                    onChange={(e) => setForm({ ...form, due_at: e.target.value })}
                  />
                </Field>
                <Field label="Instructions" optional>
                  <Textarea
                    rows={2}
                    placeholder="Anything the students should know"
                    value={form.instructions}
                    onChange={(e) => setForm({ ...form, instructions: e.target.value })}
                  />
                </Field>
              </>
            )}
          </Reveal>
        </div>

        {!file && reuseId === "" && (
          <p className="text-sm text-ink-500">
            No paper? Give it a title under “Optional details” and an empty assignment is created
            for you to type the questions into.
          </p>
        )}
        {error && (
          <p role="alert" className="text-sm text-risk-600">
            {error}
          </p>
        )}
        <div className="flex items-center gap-2">
          <Button type="submit" size="lg" loading={create.isPending} disabled={!canSubmit}>
            {create.isPending && file ? "Uploading…" : "Set homework"}
          </Button>
          <Link to={`/tutor/groups/${gid}/homework`} className={buttonClasses("ghost", "lg")}>
            Cancel
          </Link>
        </div>
      </form>
    </div>
  );
}
