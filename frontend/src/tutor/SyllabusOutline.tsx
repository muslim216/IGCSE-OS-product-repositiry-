import { useState } from "react";
import { ChevronRight } from "lucide-react";
import type { SyllabusChapterDraft, SyllabusTopicDraft } from "../api/syllabusUpload";
import { Button, inputClasses } from "../components/controls";

const cell = inputClasses;
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
const toggleBtn =
  "inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-xs text-ink-700 hover:bg-surface focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600";

export const countDescendants = (topics: SyllabusTopicDraft[]): number =>
  topics.reduce((n, t) => n + 1 + countDescendants(t.children), 0);

const topicKey = (chapter: number, path: number[]) => `${chapter}:${path.join(".")}`;

/** A key for every topic that has sub-points, scoped to its chapter. */
function parentKeys(
  chapter: number,
  topics: SyllabusTopicDraft[],
  prefix: number[] = [],
): string[] {
  return topics.flatMap((t, i) => {
    const path = [...prefix, i];
    return t.children.length === 0
      ? []
      : [topicKey(chapter, path), ...parentKeys(chapter, t.children, path)];
  });
}

function Chevron({ open }: Readonly<{ open: boolean }>) {
  return (
    <ChevronRight
      aria-hidden="true"
      className={`h-4 w-4 transition-transform ${open ? "rotate-90" : ""}`}
    />
  );
}

function toggled<T>(set: Set<T>, value: T): Set<T> {
  const next = new Set(set);
  if (!next.delete(value)) next.add(value);
  return next;
}

interface Props {
  chapters: SyllabusChapterDraft[];
  editable: boolean;
  onChapterField: (chapter: number, patch: Partial<SyllabusChapterDraft>) => void;
  onTopicField: (chapter: number, path: number[], patch: Partial<SyllabusTopicDraft>) => void;
}

/** The draft as a summary first: chapters folded, sub-points folded under their
 *  topic, weights out of the row. Fold state is local and never saved. Each
 *  toggle is its own button, so opening or folding never takes focus from an
 *  input the tutor is typing in. */
export function SyllabusOutline({
  chapters,
  editable,
  onChapterField,
  onTopicField,
}: Readonly<Props>) {
  // Fold state is keyed by index (chapter index, topic path). That holds because
  // this page only edits fields in place and never adds, removes or reorders;
  // the parent mounts this with key={upload id} so state cannot carry across uploads.
  const [openChapters, setOpenChapters] = useState<Set<number>>(new Set());
  const [openTopics, setOpenTopics] = useState<Set<string>>(new Set());
  const [weightsShown, setWeightsShown] = useState<Set<number>>(new Set());

  const allParentKeys = chapters.flatMap((c, i) => parentKeys(i, c.topics));
  const allOpen =
    chapters.length > 0 &&
    openChapters.size === chapters.length &&
    allParentKeys.every((k) => openTopics.has(k));

  function setAll(open: boolean) {
    setOpenChapters(open ? new Set(chapters.map((_, i) => i)) : new Set());
    setOpenTopics(open ? new Set(allParentKeys) : new Set());
  }

  function renderTopics(
    chapterIndex: number,
    topics: SyllabusTopicDraft[],
    showWeights: boolean,
    prefix: number[] = [],
  ) {
    return topics.map((node, i) => {
      const path = [...prefix, i];
      const key = topicKey(chapterIndex, path);
      const subCount = countDescendants(node.children);
      const open = openTopics.has(key);
      return (
        <div key={path.join(".")}>
          <div
            className="flex items-center gap-2 border-b border-line py-1.5 pr-3"
            style={{ paddingLeft: `${12 + prefix.length * 16}px` }}
          >
            {editable ? (
              <>
                <div className="w-20 shrink-0">
                  <input
                    aria-label="Topic code"
                    className={cell}
                    value={node.code}
                    onChange={(e) => onTopicField(chapterIndex, path, { code: e.target.value })}
                  />
                </div>
                <input
                  aria-label="Topic title"
                  className={cell}
                  value={node.title}
                  onChange={(e) => onTopicField(chapterIndex, path, { title: e.target.value })}
                />
              </>
            ) : (
              <p className="min-w-0 flex-1 text-sm text-ink-900">
                <span className="mr-2 text-ink-500">{node.code}</span>
                {node.title}
              </p>
            )}
            {node.weight !== 1 && !showWeights && (
              <span className="shrink-0 rounded-md bg-surface-muted px-2 py-0.5 text-xs text-ink-700">
                Weight {node.weight}
              </span>
            )}
            {showWeights &&
              (editable ? (
                <div className="w-20 shrink-0">
                  <input
                    type="number"
                    aria-label="Topic weight"
                    step={0.1}
                    min={0.1}
                    className={cell}
                    value={node.weight}
                    onChange={(e) =>
                      onTopicField(chapterIndex, path, { weight: Number(e.target.value) })
                    }
                  />
                </div>
              ) : (
                <span className="shrink-0 text-sm tabular-nums text-ink-700">
                  Weight {node.weight}
                </span>
              ))}
            {subCount > 0 && (
              <button
                type="button"
                aria-expanded={open}
                aria-label={`${open ? "Hide" : "Show"} sub-points of ${node.title}`}
                onClick={() => setOpenTopics(toggled(openTopics, key))}
                className={toggleBtn}
              >
                <Chevron open={open} />
                {plural(subCount, "sub-point", "sub-points")}
              </button>
            )}
          </div>
          {open && renderTopics(chapterIndex, node.children, showWeights, path)}
        </div>
      );
    });
  }

  return (
    <>
      <div className="mt-4 flex justify-end">
        <Button
          variant="secondary"
          size="sm"
          aria-expanded={allOpen}
          onClick={() => setAll(!allOpen)}
        >
          {allOpen ? "Fold all" : "Open all"}
        </Button>
      </div>
      <div className="mt-3 space-y-3">
        {/* Keyed by index deliberately, against the usual rule: a chapter's
            code is what the tutor is editing, so keying on it would change
            the key on every keystroke and pull focus out of the input. The
            list is never reordered or filtered here. */}
        {chapters.map((chapter, chapterIndex) => {
          const open = openChapters.has(chapterIndex);
          const showWeights = weightsShown.has(chapterIndex);
          const subCount = chapter.topics.reduce((n, t) => n + countDescendants(t.children), 0);
          const counts =
            plural(chapter.topics.length, "topic", "topics") +
            (subCount > 0 ? ` · ${plural(subCount, "sub-point", "sub-points")}` : "");
          return (
            <div key={chapterIndex} className="overflow-hidden rounded-lg border border-line">
              <div className="flex flex-wrap items-center gap-2 bg-surface-muted px-3 py-2">
                {editable ? (
                  <>
                    <label className="sr-only" htmlFor={`chapter-code-${chapterIndex}`}>
                      Chapter code
                    </label>
                    <div className="w-20 shrink-0">
                      <input
                        id={`chapter-code-${chapterIndex}`}
                        className={cell}
                        value={chapter.code}
                        onChange={(e) => onChapterField(chapterIndex, { code: e.target.value })}
                      />
                    </div>
                    <label className="sr-only" htmlFor={`chapter-title-${chapterIndex}`}>
                      Chapter title
                    </label>
                    <input
                      id={`chapter-title-${chapterIndex}`}
                      className={`${cell} min-w-0 flex-1 font-medium`}
                      value={chapter.title}
                      onChange={(e) => onChapterField(chapterIndex, { title: e.target.value })}
                    />
                  </>
                ) : (
                  <p className="min-w-0 flex-1 text-sm font-medium text-ink-900">
                    {chapter.title}
                    <span className="ml-2 font-normal text-ink-500">{chapter.code}</span>
                  </p>
                )}
                <span className="shrink-0 text-xs text-ink-500">{counts}</span>
                <button
                  type="button"
                  aria-expanded={open}
                  aria-label={`${open ? "Hide" : "Show"} topics in ${chapter.title}`}
                  onClick={() => setOpenChapters(toggled(openChapters, chapterIndex))}
                  className={toggleBtn}
                >
                  <Chevron open={open} />
                </button>
              </div>

              {open &&
                (chapter.topics.length === 0 ? (
                  <p className="px-3 py-3 text-sm text-ink-500">No topics in this chapter.</p>
                ) : (
                  <div>
                    <div className="flex justify-end border-b border-line px-3 py-1.5">
                      <button
                        type="button"
                        aria-expanded={showWeights}
                        aria-label={`${showWeights ? "Hide" : "Show"} weights in ${chapter.title}`}
                        onClick={() => setWeightsShown(toggled(weightsShown, chapterIndex))}
                        className={toggleBtn}
                      >
                        {showWeights ? "Hide weights" : "Show weights"}
                      </button>
                    </div>
                    {renderTopics(chapterIndex, chapter.topics, showWeights)}
                  </div>
                ))}
            </div>
          );
        })}
      </div>
    </>
  );
}
