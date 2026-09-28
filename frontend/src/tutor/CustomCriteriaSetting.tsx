import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { listSubjects } from "../api/groups";
import {
  createCustomCriterion,
  listCustomCriteria,
  updateCustomCriterion,
  type CustomCriterion,
  type CustomCriterionUpdate,
} from "../api/customCriteria";
import { ABSENT } from "../lib/labels";

const INPUT = "rounded-md border border-line-control bg-canvas px-3 py-2 text-sm text-ink-900";

/**
 * The organisation's own criteria — "Exam technique", "Confidence" — that a
 * tutor scores by hand on each student's profile (task 5.4b). They sit beside
 * readiness and never feed it (owner decision 6). A criterion's subject is
 * fixed at creation, because every score was given against that scope; the
 * API refuses a change, so the form says so up front.
 */
export default function CustomCriteriaSetting() {
  const queryClient = useQueryClient();
  const [showArchived, setShowArchived] = useState(false);
  const criteria = useQuery({
    queryKey: ["custom-criteria", showArchived],
    queryFn: () => listCustomCriteria(showArchived),
  });
  const subjects = useQuery({ queryKey: ["subjects"], queryFn: listSubjects });
  const subjectName = (id: number | null) =>
    id === null ? "All subjects" : (subjects.data?.find((s) => s.id === id)?.name ?? "One subject");

  // A criterion edit changes what every student panel lists.
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ["custom-criteria"] }),
      queryClient.invalidateQueries({ queryKey: ["student-criteria"] }),
    ]);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [subjectId, setSubjectId] = useState("");
  const create = useMutation({
    mutationFn: () =>
      createCustomCriterion({
        name,
        description: description.trim() || null,
        subject_id: subjectId === "" ? null : Number(subjectId),
      }),
    onSuccess: async () => {
      setName("");
      setDescription("");
      setSubjectId("");
      await refresh();
    },
  });
  const update = useMutation({
    mutationFn: ({ id, body }: { id: number; body: CustomCriterionUpdate }) =>
      updateCustomCriterion(id, body),
    onSuccess: refresh,
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (name.trim()) create.mutate();
  };

  return (
    <div className="rounded-lg border border-line bg-surface p-4">
      <h3 className="font-medium text-ink-900">Custom criteria</h3>
      <p className="mt-1 text-sm text-ink-500">
        Things you score each student on by hand, out of 100. Students and parents see them labelled
        as tutor-entered. They never count towards readiness.
      </p>

      <form onSubmit={submit} className="mt-3 flex flex-wrap items-end gap-2">
        <input
          aria-label="New criterion name"
          placeholder="Name, e.g. Exam technique"
          maxLength={120}
          value={name}
          onChange={(e) => setName(e.target.value)}
          className={INPUT}
        />
        <input
          aria-label="New criterion description (optional)"
          placeholder="Description (optional)"
          maxLength={2000}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          className={INPUT}
        />
        <select
          aria-label="Applies to"
          value={subjectId}
          onChange={(e) => setSubjectId(e.target.value)}
          className={INPUT}
        >
          <option value="">All subjects</option>
          {subjects.data?.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name} ({s.exam_board} {s.code})
            </option>
          ))}
        </select>
        <button
          type="submit"
          disabled={!name.trim() || create.isPending}
          className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-canvas hover:bg-brand-700 disabled:opacity-50"
        >
          Add criterion
        </button>
      </form>
      <p className="mt-1 text-xs text-ink-500">The subject can't be changed after it's added.</p>
      {create.isError && (
        <p role="alert" className="mt-2 text-sm text-risk-600">
          {create.error.message || ABSENT.loadFailed}
        </p>
      )}

      <label className="mt-4 flex items-center gap-2 text-sm text-ink-700">
        <input
          type="checkbox"
          checked={showArchived}
          onChange={(e) => setShowArchived(e.target.checked)}
          className="accent-brand-600"
        />
        Show archived
      </label>

      {criteria.isError ? (
        <p className="mt-3 text-sm text-ink-500">{ABSENT.loadFailed}</p>
      ) : criteria.data?.length === 0 ? (
        <p className="mt-3 text-sm text-ink-500">No criteria yet.</p>
      ) : (
        <ul className="mt-3 divide-y divide-line">
          {criteria.data?.map((c) => (
            <CriterionItem
              key={c.id}
              criterion={c}
              subject={subjectName(c.subject_id)}
              // Only the row being saved waits; the rest stay usable.
              busy={update.isPending && update.variables?.id === c.id}
              onUpdate={(body, onSaved) =>
                update.mutate({ id: c.id, body }, { onSuccess: onSaved })
              }
            />
          ))}
        </ul>
      )}
      {update.isError && (
        <p role="alert" className="mt-2 text-sm text-risk-600">
          {update.error.message || ABSENT.loadFailed}
        </p>
      )}
    </div>
  );
}

function CriterionItem({
  criterion,
  subject,
  busy,
  onUpdate,
}: {
  criterion: CustomCriterion;
  subject: string;
  busy: boolean;
  onUpdate: (body: CustomCriterionUpdate, onSaved?: () => void) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(criterion.name);
  const [description, setDescription] = useState(criterion.description ?? "");
  const archived = criterion.archived_at !== null;

  if (editing) {
    return (
      <li className="flex flex-wrap items-center gap-2 py-2.5">
        <input
          aria-label="Name"
          maxLength={120}
          value={name}
          onChange={(e) => setName(e.target.value)}
          className={INPUT}
        />
        <input
          aria-label="Description"
          maxLength={2000}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          className={INPUT}
        />
        <button
          type="button"
          disabled={!name.trim() || busy}
          onClick={() => {
            // Close only once it saved: a failed rename keeps what was typed.
            onUpdate({ name, description: description.trim() || null }, () => setEditing(false));
          }}
          className="rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-canvas hover:bg-brand-700 disabled:opacity-50"
        >
          Save
        </button>
        <button
          type="button"
          onClick={() => setEditing(false)}
          className="text-sm text-ink-500 hover:text-ink-700"
        >
          Cancel
        </button>
      </li>
    );
  }

  return (
    <li className="flex flex-wrap items-center justify-between gap-2 py-2.5">
      <div className="min-w-0">
        <p className="text-sm font-medium text-ink-900">
          {criterion.name}
          {archived && <span className="ml-2 text-xs font-normal text-ink-500">Archived</span>}
        </p>
        <p className="text-xs text-ink-500">
          {subject}
          {criterion.description && ` · ${criterion.description}`}
        </p>
      </div>
      <div className="flex items-center gap-3">
        <button
          type="button"
          aria-label={`Edit ${criterion.name}`}
          onClick={() => {
            setName(criterion.name);
            setDescription(criterion.description ?? "");
            setEditing(true);
          }}
          className="text-sm font-medium text-brand-600 hover:text-brand-700"
        >
          Edit
        </button>
        <button
          type="button"
          aria-label={`${archived ? "Unarchive" : "Archive"} ${criterion.name}`}
          disabled={busy}
          onClick={() => onUpdate({ archived: !archived })}
          className="text-sm font-medium text-ink-500 hover:text-ink-700 disabled:opacity-50"
        >
          {archived ? "Unarchive" : "Archive"}
        </button>
      </div>
    </li>
  );
}
