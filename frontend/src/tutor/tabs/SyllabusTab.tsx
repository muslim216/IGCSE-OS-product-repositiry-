import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { listTopics, type Topic } from "../../api/syllabus";
import { groupAnalytics } from "../../api/readiness";
import { useGroupContext } from "../GroupLayout";
import { EmptyState, SectionCard } from "../../components/ui";
import { Button } from "../../components/controls";
import { ErrorState, SectionSkeleton } from "../../components/page";
import { PlainSection, useFollowHash } from "../SectionedPage";
import TaughtBeforeEditor from "../TaughtBeforeEditor";

interface TopicNode extends Topic {
  children: TopicNode[];
}

/** The API returns a flat list carrying parent_id, so the tree is rebuilt here. */
function buildTree(topics: Topic[]): TopicNode[] {
  const nodes = new Map<number, TopicNode>(topics.map((t) => [t.id, { ...t, children: [] }]));
  const roots: TopicNode[] = [];
  for (const topic of topics) {
    const node = nodes.get(topic.id)!;
    const parent = topic.parent_id === null ? undefined : nodes.get(topic.parent_id);
    if (parent) parent.children.push(node);
    else roots.push(node);
  }
  return roots;
}

function TopicRow({ node, scores }: { node: TopicNode; scores: Map<string, number> }) {
  const score = scores.get(node.code);
  return (
    <li>
      <div className="flex items-center justify-between gap-3 py-2">
        <span className="min-w-0">
          <span className="mr-2 font-mono text-xs text-ink-500">{node.code}</span>
          <span className="text-sm text-ink-700">{node.title}</span>
        </span>
        {/* Every score here is one of the class's weak topics — analytics only
            returns topics at or below the tutor's own weak threshold — so one
            colour says "weak" truthfully. Banding them by a literal 70/50 cut
            would be a threshold this subject never set (UX-28). */}
        {score !== undefined && (
          <span className="shrink-0 rounded-full bg-warn-100 px-2 py-0.5 text-xs font-medium tabular-nums text-warn-700">
            {Math.round(score)}% class average
          </span>
        )}
      </div>
      {node.children.length > 0 && (
        <ul className="ml-4 border-l border-line pl-4">
          {node.children.map((child) => (
            <TopicRow key={child.id} node={child} scores={scores} />
          ))}
        </ul>
      )}
    </li>
  );
}

/** The class's Syllabus tab: where the class is up to, then the coverage below it. */
export default function SyllabusTab() {
  const { group, groupId } = useGroupContext();
  // The Setup checklist links to #taught-before; follow it so the section scrolls
  // into view and takes focus.
  useFollowHash();
  return (
    <div className="space-y-8">
      <PlainSection id="taught-before" label="Where is this class up to?">
        <TaughtBeforeEditor groupId={groupId} subjectId={group.subject.id} />
      </PlainSection>
      <SyllabusCoverage />
    </div>
  );
}

function SyllabusCoverage() {
  const { group, groupId } = useGroupContext();
  const subjectId = group.subject.id;

  const topics = useQuery({
    queryKey: ["topics", subjectId],
    queryFn: () => listTopics(subjectId),
  });
  const analytics = useQuery({
    queryKey: ["analytics", groupId],
    queryFn: () => groupAnalytics(groupId),
  });

  const tree = useMemo(() => buildTree(topics.data ?? []), [topics.data]);

  /*
   * Analytics only reports the topics the class is weakest on, so a score here
   * is a highlight rather than full coverage — a topic without one simply has
   * no evidence yet, and is never rendered as a fabricated 0.
   */
  const scores = useMemo(
    () => new Map((analytics.data?.weak_topics ?? []).map((t) => [t.topic_code, t.avg_score])),
    [analytics.data],
  );

  if (topics.isLoading) return <SectionSkeleton rows={6} label="Loading the syllabus" />;
  if (topics.isError) {
    return (
      <ErrorState
        title="Couldn't load the syllabus"
        error={topics.error}
        onRetry={() => topics.refetch()}
      />
    );
  }
  if (tree.length === 0) {
    return (
      <SectionCard>
        <EmptyState
          title="No syllabus loaded for this subject"
          hint="Once a syllabus is loaded, this shows what the class is covering and where they're weakest."
        />
      </SectionCard>
    );
  }

  return (
    <div>
      <h2 className="text-lg text-ink-900">
        {group.subject.exam_board} {group.subject.code} syllabus
      </h2>
      <p className="mt-0.5 text-sm text-ink-500">
        Topics your class is scoring lowest on are flagged with their class average as marked work
        builds up.
      </p>
      {/* Without this, a failed analytics call is indistinguishable from a
          class that has no evidence yet — every flag would simply vanish. */}
      {analytics.isError && (
        <div
          role="alert"
          className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-md bg-risk-100 px-3 py-2 text-sm text-risk-600"
        >
          <span>Class averages didn't load, so no topics are flagged below.</span>
          <Button variant="secondary" size="sm" onClick={() => analytics.refetch()}>
            Try again
          </Button>
        </div>
      )}
      <div className="mt-4 rounded-xl border border-line bg-surface px-5 py-2">
        <ul>
          {tree.map((node) => (
            <TopicRow key={node.id} node={node} scores={scores} />
          ))}
        </ul>
      </div>
    </div>
  );
}
