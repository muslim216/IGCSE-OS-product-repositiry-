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
  // State rather than a ref, because the editor below is gated on it. A ref
  // would record which subject the draft belongs to without being able to keep
  // the wrong subject's rows off the screen while it catches up.
  const [hydratedFor, setHydratedFor] = useState<number | null>(null);
  useEffect(() => {
    if (categories.data && hydratedFor !== categories.data.subject_id) {
      setHydratedFor(categories.data.subject_id);
      setDraft(toDraft(categories.data.categories));
    }
  }, [categories.data, hydratedFor]);

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
          // Trimmed, so the 400-character check below measures what is
          // actually sent. Sending the raw string let a description of 400
          // content characters plus a trailing newline pass on screen and come
          // back rejected by the API (cubic). The API trims too; agreeing with
          // it is what keeps the two bounds the same bound.
          description: c.description.trim() || undefined,
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
      setHydratedFor(data.subject_id);
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
  const folded = trimmedNames.map((n) => n.toLowerCase());
  /** Why this row's name cannot be saved, in the tutor's words, or null.
   *
   *  Per row rather than per page: a list of forty categories with one page
   *  footnote saying "every category needs a name" does not say which one, and
   *  a screen reader reaching a disabled Save has nothing tying it to a field.
   *  Each message is attached to its own input with `aria-describedby` (cubic).
   */
  const nameError = (i: number): string | null => {
    if (draft[i].name.length > 60) return "Name must be 60 characters or fewer.";
    if (trimmedNames[i].length === 0) return "Every category needs a name.";
    if (folded.some((n, j) => j !== i && n === folded[i]))
      return "Each category name can appear only once.";
    return null;
  };
  // Measured on what is actually sent, which is the trimmed string.
  const descriptionError = (i: number): string | null =>
    draft[i].description.trim().length > 400
      ? "Description must be 400 characters or fewer."
      : null;

  const tooMany = draft.length > 40;
  const invalid =
    draft.length === 0 ||
    tooMany ||
    draft.some((_, i) => nameError(i) !== null || descriptionError(i) !== null);

  if (subjects.isLoading) {
    return (
      <div aria-busy="true">
        <span aria-hidden className="block h-24 w-full animate-pulse rounded bg-surface-muted" />
      </div>
    );
  }
  // A failed load is not an empty list. Telling a tutor whose subjects simply
  // did not arrive that they have none sends them off to add a syllabus they
  // already have, and hides the fact that anything went wrong (PROD-2, UX-19).
  if (subjects.isError) {
    return <p className="text-sm text-ink-500">{ABSENT.loadFailed}</p>;
  }
  if (!subjects.data || subjects.data.length === 0) {
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

      {/* The editor appears only once the *draft* belongs to the selected
          subject — not merely once the query's answer does. Switching to a
          subject already in the cache renders its data synchronously, while
          `draft` still holds the previous subject's rows until the effect above
          runs: one render with Save enabled, pointed at the new subject,
          carrying the old subject's list. Gating on the loaded data's
          `subject_id` passed in exactly that render, because the data had
          already arrived and only the draft was behind (cubic). */}
      {categories.isError ? (
        // Before the hydration gate, not after: a failed load never hydrates,
        // so testing it second would leave the skeleton pulsing forever with
        // nothing saying the request had failed.
        <p className="text-sm text-ink-500">{ABSENT.loadFailed}</p>
      ) : categories.isLoading || !categories.data || hydratedFor !== selected ? (
        <span aria-hidden className="block h-32 w-full animate-pulse rounded bg-surface-muted" />
      ) : (
        <>
          {categories.data.source === "none" ? (
            // <output> rather than a div with role="status": it carries that
            // role implicitly and is announced by assistive tech that does not
            // honour the attribute on a generic element (SonarCloud).
            <output className="block rounded-lg border border-line bg-warn-100 p-3 text-sm text-warn-700">
              {sourceNote(categories.data)}
            </output>
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
                      aria-invalid={nameError(i) !== null}
                      aria-describedby={
                        nameError(i) !== null ? `category-name-error-${category.key}` : undefined
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
                      aria-invalid={descriptionError(i) !== null}
                      aria-describedby={
                        descriptionError(i) !== null
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
                {nameError(i) && (
                  <p id={`category-name-error-${category.key}`} className="text-sm text-risk-600">
                    {nameError(i)}
                  </p>
                )}
                {descriptionError(i) && (
                  <p
                    id={`category-description-error-${category.key}`}
                    className="text-sm text-risk-600"
                  >
                    {descriptionError(i)}
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
          {/* Empty and duplicate names used to be reported here, as page
              footnotes that never said which row was wrong. They are on the
              rows now. This one stays: it is about the list, not a field. */}
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
