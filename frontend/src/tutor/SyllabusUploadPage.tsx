import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  applySyllabusUpload,
  getSyllabusUpload,
  listSyllabusUploads,
  retrySyllabusExtraction,
  updateSyllabusDraft,
  uploadSyllabus,
  type SubjectLevel,
  type SyllabusChapterDraft,
  type SyllabusTopicDraft,
} from "../api/syllabusUpload";
import { ApiError } from "../api/client";

const STATUS_LABEL: Record<string, string> = {
  extracting: "AI is reading the syllabus…",
  extraction_failed: "Extraction failed",
  review: "Review the chapters, then apply",
  applied: "Applied",
};

const STATUS_CLASS: Record<string, string> = {
  extracting: "bg-amber-100 text-amber-700",
  extraction_failed: "bg-red-100 text-red-700",
  review: "bg-amber-100 text-amber-700",
  applied: "bg-green-100 text-green-700",
};

function UploadForm({ onUploaded }: { onUploaded: (id: number) => void }) {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);

  const upload = useMutation({
    mutationFn: () => uploadSyllabus(title || file!.name, file!),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["syllabus-uploads"] });
      setTitle("");
      setFile(null);
      onUploaded(result.id);
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (file) upload.mutate();
  }

  return (
    <form onSubmit={onSubmit} className="rounded-lg border bg-white p-4">
      <h3 className="font-medium text-slate-800">Upload a syllabus</h3>
      <p className="mt-1 text-sm text-slate-500">
        Upload the exam board's syllabus PDF and the AI drafts the chapters and their topics —
        review and edit them, then apply it to make the subject available for groups and homework.
      </p>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <div>
          <label className="block text-sm font-medium text-slate-700">Name (optional)</label>
          <input
            className="mt-1 rounded-md border border-slate-300 px-3 py-2 text-sm"
            placeholder="e.g. AQA GCSE Physics 8463"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700">Syllabus PDF</label>
          <input
            type="file"
            accept="application/pdf"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="mt-1 text-sm"
          />
        </div>
        <button
          type="submit"
          disabled={!file || upload.isPending}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {upload.isPending ? "Uploading…" : "Upload & extract"}
        </button>
      </div>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </form>
  );
}

const LEVELS: { value: SubjectLevel; label: string }[] = [
  { value: "igcse", label: "IGCSE" },
  { value: "o_level", label: "O Level" },
  { value: "a_level", label: "A Level" },
];

interface FlatRow {
  path: number[];
  node: SyllabusTopicDraft;
}

/** A chapter's topics with their sub-topics, depth carried by `path.length`. */
function flatten(topics: SyllabusTopicDraft[], prefix: number[] = []): FlatRow[] {
  return topics.flatMap((node, i) => {
    const path = [...prefix, i];
    return [{ path, node }, ...flatten(node.children, path)];
  });
}

function updateAtPath(
  topics: SyllabusTopicDraft[],
  path: number[],
  patch: Partial<SyllabusTopicDraft>,
): SyllabusTopicDraft[] {
  const [i, ...rest] = path;
  return topics.map((node, idx) => {
    if (idx !== i) return node;
    if (rest.length === 0) return { ...node, ...patch };
    return { ...node, children: updateAtPath(node.children, rest, patch) };
  });
}

function UploadDetail({ id, onBack }: { id: number; onBack: () => void }) {
  const queryClient = useQueryClient();
  const detail = useQuery({
    queryKey: ["syllabus-upload", id],
    queryFn: () => getSyllabusUpload(id),
    refetchInterval: (query) => (query.state.data?.status === "extracting" ? 2500 : false),
  });

  const [error, setError] = useState<string | null>(null);

  const saveDraft = useMutation({
    mutationFn: (draft: NonNullable<typeof detail.data>["draft"]) =>
      updateSyllabusDraft(id, draft!),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["syllabus-upload", id] }),
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });
  const retry = useMutation({
    mutationFn: () => retrySyllabusExtraction(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["syllabus-upload", id] }),
  });
  const apply = useMutation({
    mutationFn: () => applySyllabusUpload(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["syllabus-upload", id] });
      queryClient.invalidateQueries({ queryKey: ["syllabus-uploads"] });
      queryClient.invalidateQueries({ queryKey: ["subjects"] });
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });

  if (detail.isLoading) return <p className="text-slate-500">Loading…</p>;
  const upload = detail.data;
  if (!upload) return <p className="text-red-600">Not found.</p>;
  const editable = upload.status === "review" || upload.status === "extraction_failed";

  const draft = upload.draft;
  const topicCount = draft?.chapters.reduce((n, c) => n + flatten(c.topics).length, 0) ?? 0;

  function setChapterField(index: number, patch: Partial<SyllabusChapterDraft>) {
    if (!draft) return;
    saveDraft.mutate({
      ...draft,
      chapters: draft.chapters.map((c, i) => (i === index ? { ...c, ...patch } : c)),
    });
  }

  function setTopicField(chapter: number, path: number[], patch: Partial<SyllabusTopicDraft>) {
    if (!draft) return;
    setChapterField(chapter, { topics: updateAtPath(draft.chapters[chapter].topics, path, patch) });
  }

  return (
    <div className="space-y-4">
      <button onClick={onBack} className="text-sm text-blue-600 hover:underline">
        ← All syllabus uploads
      </button>
      <div className="flex items-center gap-3">
        <h2 className="text-xl font-semibold text-slate-800">{upload.title}</h2>
        <span
          className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_CLASS[upload.status]}`}
        >
          {STATUS_LABEL[upload.status]}
        </span>
      </div>

      {upload.status === "extracting" && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          The AI is reading the syllabus and drafting the chapters — this can take a minute for long
          documents. The page refreshes automatically.
        </div>
      )}

      {upload.status === "extraction_failed" && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          <p className="font-medium">Extraction failed: {upload.error}</p>
          <button
            onClick={() => retry.mutate()}
            className="mt-2 rounded bg-red-600 px-3 py-1.5 text-white hover:bg-red-700"
          >
            Retry extraction
          </button>
        </div>
      )}

      {draft && (
        <section className="rounded-lg border bg-white p-4">
          <div className="grid gap-3 sm:grid-cols-5">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                Exam board
              </p>
              <p className="text-sm text-slate-700">{draft.exam_board}</p>
            </div>
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Code</p>
              <p className="text-sm text-slate-700">{draft.code}</p>
            </div>
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Subject</p>
              <p className="text-sm text-slate-700">{draft.name}</p>
            </div>
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                Grade scale
              </p>
              <p className="text-sm text-slate-700">{draft.grade_scale}</p>
            </div>
            <div>
              <label
                htmlFor="syllabus-level"
                className="block text-xs font-medium uppercase tracking-wide text-slate-500"
              >
                Level
              </label>
              {editable ? (
                <select
                  id="syllabus-level"
                  className="mt-0.5 rounded border border-slate-300 px-1.5 py-1 text-sm"
                  value={draft.level ?? ""}
                  onChange={(e) =>
                    saveDraft.mutate({ ...draft, level: e.target.value as SubjectLevel })
                  }
                >
                  {/* The document may not state a level, and nothing guesses one
                      for the tutor (AV-7, PROD-2) — so "not set" is a real
                      option to sit in, and applying refuses until it is set. */}
                  <option value="" disabled>
                    Choose a level
                  </option>
                  {LEVELS.map((l) => (
                    <option key={l.value} value={l.value}>
                      {l.label}
                    </option>
                  ))}
                </select>
              ) : (
                <p className="text-sm text-slate-700">
                  {LEVELS.find((l) => l.value === draft.level)?.label ?? "Not set"}
                </p>
              )}
            </div>
          </div>

          <div className="mt-4 flex items-center justify-between">
            <h3 className="font-medium text-slate-800">
              {draft.chapters.length} chapters, {topicCount} topics
            </h3>
            {editable && (
              <button
                onClick={() => apply.mutate()}
                disabled={apply.isPending}
                className="rounded bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-40"
              >
                {apply.isPending ? "Applying…" : "Apply — make available for groups"}
              </button>
            )}
          </div>
          {error && <p className="mt-2 text-sm text-red-600">{error}</p>}

          <div className="mt-3 space-y-4">
            {draft.chapters.map((chapter, chapterIndex) => (
              <div key={chapterIndex} className="rounded-md border border-slate-200">
                <div className="flex items-center gap-2 border-b bg-slate-50 px-3 py-2">
                  {editable ? (
                    <>
                      <label className="sr-only" htmlFor={`chapter-code-${chapterIndex}`}>
                        Chapter code
                      </label>
                      <input
                        id={`chapter-code-${chapterIndex}`}
                        className="w-20 rounded border border-slate-300 px-1.5 py-1 text-sm"
                        value={chapter.code}
                        onChange={(e) => setChapterField(chapterIndex, { code: e.target.value })}
                      />
                      <label className="sr-only" htmlFor={`chapter-title-${chapterIndex}`}>
                        Chapter title
                      </label>
                      <input
                        id={`chapter-title-${chapterIndex}`}
                        className="w-full rounded border border-slate-300 px-1.5 py-1 text-sm font-medium"
                        value={chapter.title}
                        onChange={(e) => setChapterField(chapterIndex, { title: e.target.value })}
                      />
                    </>
                  ) : (
                    <p className="text-sm font-medium text-slate-800">
                      {chapter.code} {chapter.title}
                    </p>
                  )}
                </div>

                {chapter.topics.length === 0 ? (
                  <p className="px-3 py-2 text-sm text-slate-500">No topics in this chapter.</p>
                ) : (
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b text-left text-slate-500">
                        <th className="py-1.5 pl-3 pr-2 font-medium">Code</th>
                        <th className="py-1.5 pr-2 font-medium">Topic</th>
                        <th className="py-1.5 pr-3 font-medium">Weight</th>
                      </tr>
                    </thead>
                    <tbody>
                      {flatten(chapter.topics).map(({ path, node }) => (
                        <tr key={path.join(".")} className="border-b align-top last:border-0">
                          <td
                            className="py-1.5 pr-2 pl-3"
                            style={{ paddingLeft: `${12 + (path.length - 1) * 16}px` }}
                          >
                            {editable ? (
                              <input
                                aria-label="Topic code"
                                className="w-20 rounded border border-slate-300 px-1.5 py-1"
                                value={node.code}
                                onChange={(e) =>
                                  setTopicField(chapterIndex, path, { code: e.target.value })
                                }
                              />
                            ) : (
                              node.code
                            )}
                          </td>
                          <td className="py-1.5 pr-2">
                            {editable ? (
                              <input
                                aria-label="Topic title"
                                className="w-full rounded border border-slate-300 px-1.5 py-1"
                                value={node.title}
                                onChange={(e) =>
                                  setTopicField(chapterIndex, path, { title: e.target.value })
                                }
                              />
                            ) : (
                              node.title
                            )}
                          </td>
                          <td className="py-1.5 pr-3">
                            {editable ? (
                              <input
                                type="number"
                                aria-label="Topic weight"
                                step={0.1}
                                min={0.1}
                                className="w-20 rounded border border-slate-300 px-1.5 py-1"
                                value={node.weight}
                                onChange={(e) =>
                                  setTopicField(chapterIndex, path, {
                                    weight: Number(e.target.value),
                                  })
                                }
                              />
                            ) : (
                              node.weight
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

export default function SyllabusUploadPage() {
  const uploads = useQuery({ queryKey: ["syllabus-uploads"], queryFn: listSyllabusUploads });
  const [selectedId, setSelectedId] = useState<number | null>(null);

  if (selectedId !== null) {
    return <UploadDetail id={selectedId} onBack={() => setSelectedId(null)} />;
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-slate-800">Syllabuses</h2>
        <p className="mt-1 text-sm text-slate-500">
          Upload an exam board syllabus and the AI drafts its chapters and topics for you to review
          before they power teaching plans, readiness tracking and homework.
        </p>
      </div>

      <UploadForm onUploaded={setSelectedId} />

      <div className="rounded-lg border bg-white p-4">
        <h3 className="font-medium text-slate-800">Your uploads</h3>
        <ul className="mt-2 divide-y">
          {uploads.data?.map((u) => (
            <li key={u.id} className="flex items-center justify-between py-2 text-sm">
              <button onClick={() => setSelectedId(u.id)} className="text-blue-600 hover:underline">
                {u.title}
              </button>
              <span
                className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_CLASS[u.status]}`}
              >
                {STATUS_LABEL[u.status]}
              </span>
            </li>
          ))}
          {uploads.data?.length === 0 && (
            <li className="py-2 text-sm text-slate-500">No syllabuses uploaded yet.</li>
          )}
        </ul>
      </div>
    </div>
  );
}
