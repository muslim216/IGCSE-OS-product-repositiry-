import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { listTopics, type Topic } from "../../api/syllabus";
import { groupAnalytics } from "../../api/readiness";
import { useGroupContext } from "../GroupLayout";
import { EmptyState } from "../../components/ui";

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

function scoreClasses(score: number): string {
  if (score >= 70) return "bg-ok-100 text-ok-700";
  if (score >= 50) return "bg-warn-100 text-warn-700";
  return "bg-risk-100 text-risk-600";
}

function TopicRow({ node, scores }: { node: TopicNode; scores: Map<string, number> }) {
  const score = scores.get(node.code);
  return (
    <li>
      <div className="flex items-center justify-between gap-3 py-2">
        <span className="min-w-0">
          <span className="mr-2 font-mono text-xs text-ink-400">{node.code}</span>
          <span className="text-sm text-ink-700">{node.title}</span>
        </span>
        {score !== undefined && (
          <span
            className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${scoreClasses(score)}`}
          >
            {Math.round(score)}% class avg
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

export default function SyllabusTab() {
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

  if (topics.isLoading) return <p className="text-ink-500">Loading…</p>;
  if (topics.isError) {
    return (
      <EmptyState
        title="Couldn't load the syllabus"
        hint="The connection may have dropped."
        action={
          <button
            type="button"
            onClick={() => topics.refetch()}
            className="rounded-md bg-brand-600 px-3 py-1.5 font-medium hover:bg-brand-700"
          >
            Try again
          </button>
        }
      />
    );
  }
  if (tree.length === 0) {
    return (
      <EmptyState
        title="No syllabus loaded for this subject"
        hint="Topic trees are seeded per exam board. Once loaded, this shows what the class is covering and where they're weakest."
      />
    );
  }

  return (
    <div>
      <h3 className="font-medium">
        {group.subject.exam_board} {group.subject.code} syllabus
      </h3>
      <p className="text-sm text-ink-500">
        Topics your class is scoring lowest on are flagged as evidence builds up.
      </p>
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
