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
import { friendlyError } from "../lib/errors";
import { SectionCard } from "../components/ui";
import { Button, Field, Input, Select } from "../components/controls";
import { SectionSkeleton } from "../components/page";

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
    <SectionCard>
      <h2 className="text-lg text-ink-900">Custom criteria</h2>
      <p className="mt-1 max-w-prose text-sm text-ink-500">
        Things you score each student on by hand, out of 100. Students and parents see them labelled
        as tutor-entered. They never count towards readiness.
      </p>

      <form onSubmit={submit} className="mt-5 border-t border-line pt-4">
        <h3 className="text-sm font-medium text-ink-900">Add a criterion</h3>
        <div className="mt-3 grid gap-4 sm:grid-cols-2">
          <Field label="Criterion name">
            <Input
              placeholder="e.g. Exam technique"
              maxLength={120}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          <Field label="Applies to" hint="This can't be changed after it's added.">
            <Select value={subjectId} onChange={(e) => setSubjectId(e.target.value)}>
              <option value="">All subjects</option>
              {subjects.data?.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} ({s.exam_board} {s.code})
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Description" optional className="sm:col-span-2">
            <Input
              maxLength={2000}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </Field>
        </div>
        <div className="mt-4 flex justify-end">
          <Button type="submit" disabled={!name.trim()} loading={create.isPending}>
            Add criterion
          </Button>
        </div>
      </form>
      {create.isError && (
        <p role="alert" className="mt-2 text-sm text-risk-600">
          {friendlyError(create.error, "Couldn't add the criterion. Try again.")}
        </p>
      )}

      <div className="mt-5 flex items-center justify-between gap-3 border-t border-line pt-4">
        <h3 className="text-sm font-medium text-ink-900">Your criteria</h3>
        <label className="flex items-center gap-2 text-sm text-ink-700">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(e) => setShowArchived(e.target.checked)}
            className="h-4 w-4 accent-brand-600"
          />
          Show archived
        </label>
      </div>

      {criteria.isLoading ? (
        <div className="mt-3">
          <SectionSkeleton rows={2} label="Loading criteria" />
        </div>
      ) : criteria.isError ? (
        <p className="mt-3 text-sm text-ink-500">{ABSENT.loadFailed}</p>
      ) : criteria.data?.length === 0 ? (
        <p className="mt-3 text-sm text-ink-500">No criteria yet.</p>
      ) : (
        <ul className="mt-2 divide-y divide-line">
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
          {friendlyError(update.error, "That change didn't save. Try again.")}
        </p>
      )}
    </SectionCard>
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
      <li className="grid gap-3 py-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)_auto] sm:items-center">
        <Input
          aria-label="Name"
          maxLength={120}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <Input
          aria-label="Description"
          placeholder="Description (optional)"
          maxLength={2000}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        <span className="flex gap-2">
          <Button
            size="sm"
            disabled={!name.trim()}
            loading={busy}
            onClick={() => {
              // Close only once it saved: a failed rename keeps what was typed.
              onUpdate({ name, description: description.trim() || null }, () => setEditing(false));
            }}
          >
            Save
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>
            Cancel
          </Button>
        </span>
      </li>
    );
  }

  return (
    <li className="flex flex-wrap items-center justify-between gap-2 py-2.5">
      <div className="min-w-0">
        <p className="text-sm font-medium text-ink-900">
          {criterion.name}
          {archived && (
            <span className="ml-2 rounded bg-surface-muted px-1.5 py-0.5 text-xs font-normal text-ink-500">
              Archived
            </span>
          )}
        </p>
        <p className="text-xs text-ink-500">
          {subject}
          {criterion.description && ` · ${criterion.description}`}
        </p>
      </div>
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="sm"
          aria-label={`Edit ${criterion.name}`}
          onClick={() => {
            setName(criterion.name);
            setDescription(criterion.description ?? "");
            setEditing(true);
          }}
        >
          Edit
        </Button>
        <Button
          variant="ghost"
          size="sm"
          aria-label={`${archived ? "Unarchive" : "Archive"} ${criterion.name}`}
          loading={busy}
          onClick={() => onUpdate({ archived: !archived })}
        >
          {archived ? "Unarchive" : "Archive"}
        </Button>
      </div>
    </li>
  );
}
