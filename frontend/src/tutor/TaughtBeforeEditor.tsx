import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getTaughtBefore, setTaughtBefore } from "../api/groups";
import { listChapters, listTopics, type Chapter, type Topic } from "../api/syllabus";
import { Button } from "../components/controls";
import { ErrorState, SectionSkeleton } from "../components/page";
import { friendlyError } from "../lib/errors";
import { subjectSetupPath } from "../lib/subjectSetup";

interface Row {
  topic: Topic;
  depth: number;
}

interface Group {
  key: string;
  code: string;
  title: string;
  rows: Row[];
}

/** Topics in tree order with their depth, whatever order the API sent them in. */
function treeRows(topics: Topic[]): Row[] {
  const children = new Map<number, Topic[]>();
  const known = new Set(topics.map((t) => t.id));
  const roots: Topic[] = [];
  for (const topic of topics) {
    if (topic.parent_id !== null && known.has(topic.parent_id)) {
      const siblings = children.get(topic.parent_id) ?? [];
      siblings.push(topic);
      children.set(topic.parent_id, siblings);
    } else {
      roots.push(topic);
    }
  }
  const rows: Row[] = [];
  const walk = (topic: Topic, depth: number) => {
    rows.push({ topic, depth });
    for (const child of children.get(topic.id) ?? []) walk(child, depth + 1);
  };
  for (const root of roots) walk(root, 0);
  return rows;
}

/**
 * The topics grouped by chapter, in teaching order. Chapters are the unit a
 * teaching plan is drafted in, and the drafter leaves out a chapter only when
 * every one of its topics is covered, so "all of this chapter" has to mean the
 * same set of topics here as it does there.
 *
 * Topics filed under no chapter come last, under their own heading: ticking
 * them still counts as coverage, but they can never take a chapter out of a
 * plan. A subject with no chapters at all is one group.
 */
export function buildGroups(topics: Topic[], chapters: Chapter[]): Group[] {
  const rows = treeRows(topics);
  const chapterIds = new Set(chapters.map((c) => c.id));
  const groups: Group[] = chapters
    .map((c) => ({
      key: `chapter-${c.id}`,
      code: c.code,
      title: c.title,
      rows: rows.filter((r) => r.topic.chapter_id === c.id),
    }))
    .filter((g) => g.rows.length > 0);
  const unfiled = rows.filter(
    (r) => r.topic.chapter_id == null || !chapterIds.has(r.topic.chapter_id),
  );
  if (unfiled.length > 0) {
    groups.push({
      key: "unfiled",
      code: "",
      title: groups.length > 0 ? "Topics not filed under a chapter" : "Topics",
      rows: unfiled,
    });
  }
  // Depth is relative to the shallowest row in the group, so a chapter whose
  // topics all sit under one parent filed elsewhere does not start indented.
  return groups.map((g) => {
    const base = Math.min(...g.rows.map((r) => r.depth));
    return { ...g, rows: g.rows.map((r) => ({ ...r, depth: r.depth - base })) };
  });
}

/** A checkbox that can show "some of these", which the platform only allows to
 *  be set from script. */
function GroupCheckbox({
  label,
  checked,
  mixed,
  disabled,
  onChange,
}: {
  label: string;
  checked: boolean;
  mixed: boolean;
  disabled: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2 text-sm font-medium text-ink-900">
      <input
        type="checkbox"
        className="h-4 w-4 accent-brand-600"
        ref={(el) => {
          if (el) el.indeterminate = mixed;
        }}
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      {label}
    </label>
  );
}

/**
 * "Where is this class up to?" (9.1d): the answer to a class's Required
 * "taught before" step. Ticked topics count as already covered, so coverage
 * starts right and the teaching plan drafts from what is left.
 *
 * This is the tutor's own declaration, not something taught in Avora, and the
 * copy says so (PROD-8). An empty list is a real answer ("starting fresh"), which
 * is why it is saved, not just left unticked: only a saved answer clears the
 * step. A failed save keeps what was ticked, so nothing has to be done twice.
 */
export default function TaughtBeforeEditor({
  groupId,
  subjectId,
}: {
  groupId: number;
  subjectId: number;
}) {
  const queryClient = useQueryClient();
  // Same key as the Syllabus tab's own read: one request between them.
  const topics = useQuery({
    queryKey: ["topics", subjectId],
    queryFn: () => listTopics(subjectId),
  });
  // Same key and fetcher as the plan and homework screens use.
  const chapters = useQuery({
    queryKey: ["chapters", subjectId],
    queryFn: () => listChapters(subjectId),
  });
  const answer = useQuery({
    queryKey: ["taught-before", groupId],
    queryFn: () => getTaughtBefore(groupId),
  });

  // The tutor's unsaved ticks. Null means "what the server has", so a refetch
  // is never overwritten mid-edit and a save needs no copy back into state.
  const [draft, setDraft] = useState<Set<number> | null>(null);
  const ticked = useMemo(
    () => draft ?? new Set(answer.data?.topic_ids ?? []),
    [draft, answer.data],
  );

  const groups = useMemo(
    () => buildGroups(topics.data ?? [], chapters.data ?? []),
    [topics.data, chapters.data],
  );

  const save = useMutation({
    mutationFn: (topicIds: number[]) => setTaughtBefore(groupId, topicIds),
    onSuccess: (saved) => {
      queryClient.setQueryData(["taught-before", groupId], saved);
      setDraft(null);
      // The step is done as far as the server is concerned, and coverage is read
      // from this answer.
      void queryClient.invalidateQueries({ queryKey: ["onboarding"] });
      void queryClient.invalidateQueries({ queryKey: ["analytics", groupId] });
      void queryClient.invalidateQueries({ queryKey: ["class-overview", groupId] });
    },
  });

  const toggle = (ids: number[], on: boolean) => {
    const next = new Set(ticked);
    for (const id of ids) {
      if (on) next.add(id);
      else next.delete(id);
    }
    setDraft(next);
  };

  if (topics.isLoading || chapters.isLoading || answer.isLoading) {
    return <SectionSkeleton rows={3} label="Loading where this class is up to" />;
  }
  if (topics.isError || chapters.isError || answer.isError || !answer.data) {
    return (
      <ErrorState
        title="Couldn't load where this class is up to"
        error={topics.error ?? chapters.error ?? answer.error}
        onRetry={() => {
          void topics.refetch();
          void chapters.refetch();
          void answer.refetch();
        }}
      />
    );
  }

  const saved = answer.data;
  const summary = !saved.answered
    ? "Not answered yet."
    : `Answered${saved.answered_at ? ` ${new Date(saved.answered_at).toLocaleDateString()}` : ""}: ${
        saved.topic_ids.length === 0
          ? "starting fresh."
          : `${saved.topic_ids.length} ${saved.topic_ids.length === 1 ? "topic" : "topics"} ticked.`
      }`;

  return (
    <div>
      <p className="max-w-2xl text-sm text-ink-500">
        Topics ticked here count as already taught, so coverage starts correct and the teaching plan
        drafts from what is left. This is your own account of where the class is, not something
        taught in Avora.
      </p>
      <p role="status" className="mt-2 text-sm text-ink-700">
        {summary}
      </p>

      {groups.length === 0 ? (
        <p className="mt-4 text-sm text-ink-500">
          There is no syllabus tree for this subject yet, so there is nothing to tick.{" "}
          <Link
            to={subjectSetupPath("syllabus", subjectId)}
            className="text-brand-600 hover:underline"
          >
            Add the syllabus in Subject setup
          </Link>
          .
        </p>
      ) : (
        <>
          <div className="mt-4 space-y-3">
            {groups.map(({ key, code, title, rows }) => {
              const ids = rows.map((r) => r.topic.id);
              const count = ids.filter((id) => ticked.has(id)).length;
              return (
                <fieldset key={key} className="rounded-xl border border-line bg-surface px-4 py-3">
                  <legend className="px-1 text-sm text-ink-700">
                    {code && <span className="mr-2 font-mono text-xs text-ink-500">{code}</span>}
                    {title}
                  </legend>
                  <GroupCheckbox
                    label={`All of ${code ? `${code} ` : ""}${title}`}
                    checked={count === ids.length}
                    mixed={count > 0 && count < ids.length}
                    disabled={save.isPending}
                    onChange={(on) => toggle(ids, on)}
                  />
                  <ul className="mt-1">
                    {rows.map(({ topic, depth }) => (
                      <li key={topic.id} style={{ paddingLeft: `${depth * 1}rem` }}>
                        <label className="flex items-center gap-2 py-1 text-sm text-ink-700">
                          <input
                            type="checkbox"
                            className="h-4 w-4 accent-brand-600"
                            checked={ticked.has(topic.id)}
                            disabled={save.isPending}
                            onChange={(e) => toggle([topic.id], e.target.checked)}
                          />
                          <span className="font-mono text-xs text-ink-500">{topic.code}</span>
                          {topic.title}
                        </label>
                      </li>
                    ))}
                  </ul>
                </fieldset>
              );
            })}
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button
              type="button"
              disabled={save.isPending}
              onClick={() => save.mutate([...ticked])}
            >
              {save.isPending ? "Saving" : "Save"}
            </Button>
            <Button
              type="button"
              variant="secondary"
              disabled={save.isPending}
              onClick={() => save.mutate([])}
            >
              Starting fresh
            </Button>
            <span className="text-xs text-ink-500">
              Starting fresh saves that nothing has been taught yet and clears any ticks.
            </span>
          </div>
          {save.isError && (
            <p role="alert" className="mt-2 text-sm text-risk-600">
              {friendlyError(save.error, "That didn't save. Your ticks are still here. Try again.")}
            </p>
          )}
        </>
      )}
    </div>
  );
}
