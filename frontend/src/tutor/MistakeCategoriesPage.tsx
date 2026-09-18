import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../api/client";
import { listSubjects } from "../api/groups";
import {
  getMistakeCategories,
  saveMistakeCategories,
  type MistakeCategories,
  type MistakeCategoryItem,
} from "../api/mistakeCategories";
import { EmptyState, useToast } from "../components/ui";
import { ABSENT } from "../lib/labels";

/**
 * The mistake-category editor — a per-(organization, subject) list the tutor
 * owns, replacing the old five-member `MistakeCategory` enum. A direct copy of
 * the grade-boundary pattern (`GradeBoundariesPage.tsx`): defaults are offered
 * on read and written only on save, so an organization that has never opened
 * this screen has no categories anywhere — not the published five quietly
 * standing in for a decision nobody made.
 *
 * **Draft vs server data (FE-6).** The saved list lives in TanStack Query.
 * `draft` is the row of inputs the tutor is currently editing — legitimate
 * local state, re-seeded from the server value whenever it changes.
 */

interface DraftCategory {
  id: number | null;
  name: string;
  description: string;
  /** Stable across renders, so React tracks a row rather than a position.
   *  Keying by array index means removing a row shifts every row below it onto
   *  a different key, and React reuses those inputs for the shifted content —
   *  which moves a half-typed IME composition, an autofill entry or an undo
   *  history onto the wrong category. A new row has no `id` to key on, so the
   *  key cannot come from the server. */
  key: string;
}

let nextDraftKey = 0;
const draftKey = () => `draft-${nextDraftKey++}`;

function toDraft(categories: MistakeCategoryItem[]): DraftCategory[] {
  return categories.map((c) => ({
    id: c.id ?? null,
    name: c.name,
    description: c.description ?? "",
    key: draftKey(),
  }));
}

function sourceNote(data: MistakeCategories): string {
  if (data.source === "organization") return "Your organisation's mistake categories.";
  // PROD-8/UX-20: nobody has confirmed this list yet. It is the published
  // starting point, pre-filled so the tutor is not made to invent five
  // categories from nothing — but it must never read as though it is already
  // in force, because until it is saved nothing is tagged against any of it.
  return "Nothing set yet. These are the published starting categories, not your organisation's own — save them to make them yours.";
}

export default function MistakeCategoriesPage() {
  const queryClient = useQueryClient();
  const { toast, showToast } = useToast();
  const subjects = useQuery({ queryKey: ["subjects"], queryFn: listSubjects });
  const [subjectId, setSubjectId] = useState<number | null>(null);
  const selected = subjectId ?? subjects.data?.[0]?.id ?? null;

  const categories = useQuery({
    queryKey: ["mistake-categories", selected],
    queryFn: () => getMistakeCategories(selected!),
    enabled: selected !== null,
  });

  // Local edit state, seeded from the server's answer. The server value stays
  // in TanStack Query (FE-6); this is the draft the tutor is typing, which is
  // a different thing from what is stored and is not server data.
  const [draft, setDraft] = useState<DraftCategory[]>([]);
  // Seeded once per subject, not on every query update — the same guard
  // `MarkingRulesPage` carries, and for the same reason it was added there: a
  // refetch is enough to copy the stored list over whatever the tutor has
  // typed and not yet saved, and a window regaining focus is a refetch. These
  // categories are shared by every tutor in an organization, so a colleague
  // saving the same subject in another tab is the ordinary way the server's
  // answer changes mid-edit.
  const hydratedFor = useRef<number | null>(null);
  useEffect(() => {
    if (categories.data && hydratedFor.current !== categories.data.subject_id) {
      hydratedFor.current = categories.data.subject_id;
      setDraft(toDraft(categories.data.categories));
    }
  }, [categories.data]);

  // Focus has to go somewhere deliberate when a row is removed: the button the
  // tutor just pressed stops existing, and a browser drops focus to <body>,
  // which puts a keyboard or screen-reader user back at the top of the page.
  const addButton = useRef<HTMLButtonElement | null>(null);
  const removeRow = (index: number) => {
    setDraft(draft.filter((_, j) => j !== index));
    addButton.current?.focus();
  };

  const save = useMutation({
    mutationFn: () =>
      saveMistakeCategories(
        selected!,
        draft.map((c) => ({
          id: c.id ?? undefined,
          name: c.name,
          description: c.description.trim() === "" ? undefined : c.description,
        })),
      ),
    onSuccess: (data) => {
      // The PUT reply carries the same shape as the GET, ids included — write
      // it straight into the cache rather than refetching.
      queryClient.setQueryData(["mistake-categories", selected], data);
      // And adopt it here too. The per-subject hydration guard deliberately
      // ignores query updates, so without this the rows just created would keep
      // `id: null` and the next save would present them as new again. A save is
      // an explicit action, unlike the refetch that guard exists to ignore, so
      // taking what was actually stored is right here and wrong there.
      hydratedFor.current = data.subject_id;
      setDraft(toDraft(data.categories));
      showToast("Mistake categories saved.");
    },
  });

  // Mirrors the backend's own checks (schemas/mistake_categories.py) so the
  // tutor sees the reason beside the field rather than a rejected save. The
  // server stays the authority: where the two disagree on something exotic —
  // JS has no exact equivalent of Python's `casefold`, so a pair like "ß"/"ss"
  // is one name to the API and two here — the API refuses and its own message
  // is shown, which is why that message had to stop being generic.
  const trimmedNames = draft.map((c) => c.name.trim());
  const emptyName = trimmedNames.some((n) => n.length === 0);
  const nameTooLong = draft.some((c) => c.name.length > 60);
  // Measured on what is actually sent: a description that trims to nothing is
  // sent as absent, so whitespace alone cannot be too long.
  const descriptionTooLong = draft.some((c) => c.description.trim().length > 400);
  const duplicateNames =
    new Set(trimmedNames.map((n) => n.toLowerCase())).size !== trimmedNames.length;
  const tooMany = draft.length > 40;
  const invalid =
    draft.length === 0 ||
    emptyName ||
    nameTooLong ||
    descriptionTooLong ||
    duplicateNames ||
    tooMany;

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
        hint="Mistake categories are set per subject — add a syllabus first."
      />
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="font-display text-xl font-semibold text-ink-900">Mistake categories</h2>
        <p className="mt-1 max-w-prose text-sm text-ink-500">
          The words used to sort what went wrong on a marked answer. These are your organisation's
          own — nothing forces every tutor of every subject to sort mistakes the same way.
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

      {/* The editor appears only once the loaded list is the selected
          subject's. Switching to a subject already in the cache renders its
          data synchronously, while `draft` still holds the previous subject's
          rows until the effect above runs — one render with Save enabled,
          pointed at the new subject, carrying the old subject's list. */}
      {categories.isLoading || (categories.data && categories.data.subject_id !== selected) ? (
        <span aria-hidden className="block h-32 w-full animate-pulse rounded bg-surface-muted" />
      ) : categories.isError || !categories.data ? (
        <p className="text-sm text-ink-500">{ABSENT.loadFailed}</p>
      ) : (
        <>
          {categories.data.source === "none" ? (
            <p
              role="status"
              className="rounded-lg border border-line bg-warn-100 p-3 text-sm text-warn-700"
            >
              {sourceNote(categories.data)}
            </p>
          ) : (
            <p className="text-sm text-ink-500">{sourceNote(categories.data)}</p>
          )}

          <ul className="max-w-2xl space-y-3">
            {draft.map((category, i) => (
              <li key={category.key} className="space-y-2 rounded-lg border border-line p-3">
                <div className="flex items-start gap-3">
                  <div className="flex-1 space-y-2">
                    <label htmlFor={`category-name-${category.key}`} className="sr-only">
                      Category {i + 1} name
                    </label>
                    <input
                      id={`category-name-${category.key}`}
                      aria-invalid={category.name.length > 60}
                      aria-describedby={
                        category.name.length > 60
                          ? `category-name-error-${category.key}`
                          : undefined
                      }
                      value={category.name}
                      onChange={(e) =>
                        setDraft(
                          draft.map((c, j) => (i === j ? { ...c, name: e.target.value } : c)),
                        )
                      }
                      placeholder="Category name"
                      className="w-full rounded-md border border-line-control px-2 py-1 text-sm"
                    />
                    <label htmlFor={`category-description-${category.key}`} className="sr-only">
                      Description for {category.name || `category ${i + 1}`}
                    </label>
                    <textarea
                      id={`category-description-${category.key}`}
                      aria-invalid={category.description.trim().length > 400}
                      aria-describedby={
                        category.description.trim().length > 400
                          ? `category-description-error-${category.key}`
                          : undefined
                      }
                      value={category.description}
                      onChange={(e) =>
                        setDraft(
                          draft.map((c, j) =>
                            i === j ? { ...c, description: e.target.value } : c,
                          ),
                        )
                      }
                      placeholder="Description (optional) — read by the AI that tags mistakes with this category"
                      rows={2}
                      className="w-full rounded-md border border-line-control px-2 py-1 text-sm"
                    />
                  </div>
                  <button
                    type="button"
                    onClick={() => removeRow(i)}
                    className="shrink-0 text-sm text-ink-500 hover:text-risk-600"
                  >
                    Remove<span className="sr-only"> {category.name || `category ${i + 1}`}</span>
                  </button>
                </div>
                {category.name.length > 60 && (
                  <p id={`category-name-error-${category.key}`} className="text-sm text-risk-600">
                    Name must be 60 characters or fewer.
                  </p>
                )}
                {category.description.trim().length > 400 && (
                  <p
                    id={`category-description-error-${category.key}`}
                    className="text-sm text-risk-600"
                  >
                    Description must be 400 characters or fewer.
                  </p>
                )}
              </li>
            ))}
          </ul>

          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              ref={addButton}
              onClick={() =>
                setDraft([...draft, { id: null, name: "", description: "", key: draftKey() }])
              }
              disabled={draft.length >= 40}
              className="text-sm font-medium text-brand-600 hover:text-brand-700 disabled:opacity-50"
            >
              Add a category
            </button>
            <button
              type="button"
              onClick={() => save.mutate()}
              disabled={save.isPending || invalid}
              className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-canvas hover:bg-brand-700 disabled:opacity-50"
            >
              {save.isPending ? "Saving…" : "Save categories"}
            </button>
          </div>

          {draft.length === 0 && (
            <p className="text-sm text-ink-500">Add at least one category before saving.</p>
          )}
          {emptyName && draft.length > 0 && (
            <p className="text-sm text-risk-600">Every category needs a name.</p>
          )}
          {duplicateNames && (
            <p className="text-sm text-risk-600">Each category name can appear only once.</p>
          )}
          {tooMany && <p className="text-sm text-risk-600">Up to 40 categories.</p>}
          {save.isError && (
            <p className="text-sm text-risk-600" role="alert">
              {/* The server's own reason, not a generic one. "Refresh the page
                  to try again" is wrong advice for a rejected save, and it is
                  the wrong advice precisely when the tutor most needs the real
                  message — a stale row, or a rule the checks below did not
                  mirror. */}
              {save.error instanceof ApiError ? save.error.message : ABSENT.loadFailed}
            </p>
          )}
        </>
      )}
      {toast}
    </div>
  );
}
