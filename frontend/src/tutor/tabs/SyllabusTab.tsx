import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { listTopics, type Topic } from "../../api/syllabus";
import { groupAnalytics } from "../../api/readiness";
import { useGroupContext } from "../GroupLayout";
import { Badge, Card, EmptyState } from "../../ui";

interface TopicNode extends Topic {
  children: TopicNode[];
}

/** The API returns a flat list with parent_id, so the tree is rebuilt here. */
function buildTree(topics: Topic[]): TopicNode[] {
  const nodes = new Map<number, TopicNode>(
    topics.map((t) => [t.id, { ...t, children: [] }]),
  );
  const roots: TopicNode[] = [];
  for (const topic of topics) {
    const node = nodes.get(topic.id)!;
    const parent = topic.parent_id === null ? undefined : nodes.get(topic.parent_id);
    if (parent) parent.children.push(node);
    else roots.push(node);
  }
  return roots;
}

function scoreTone(score: number) {
  if (score >= 70) return "ready" as const;
  if (score >= 50) return "caution" as const;
  return "risk" as const;
}

function TopicRow({ node, scores }: { node: TopicNode; scores: Map<string, number> }) {
  const score = scores.get(node.code);
  return (
    <li>
      <div className="flex items-center justify-between gap-3 py-2">
        <span className="min-w-0">
          <span className="mr-2 font-mono text-xs text-slate-400">{node.code}</span>
          <span className="text-sm text-slate-700">{node.title}</span>
        </span>
        {score !== undefined && (
          <Badge tone={scoreTone(score)}>{Math.round(score)}% class avg</Badge>
        )}
      </div>
      {node.children.length > 0 && (
        <ul className="ml-4 border-l border-slate-100 pl-4">
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
   * is a highlight rather than full coverage — topics without one simply have
   * no evidence yet.
   */
  const scores = useMemo(
    () =>
      new Map((analytics.data?.weak_topics ?? []).map((t) => [t.topic_code, t.avg_score])),
    [analytics.data],
  );

  if (topics.isLoading) return <p className="text-slate-500">Loading…</p>;
  if (tree.length === 0) {
    return (
      <EmptyState
        icon="🗂️"
        title="No syllabus loaded for this subject"
        description="Topic trees are seeded per exam board. Once loaded, this shows what the class has covered and where they're weakest."
      />
    );
  }

  return (
    <div>
      <h3 className="font-semibold text-slate-900">
        {group.subject.exam_board} {group.subject.code} syllabus
      </h3>
      <p className="text-sm text-slate-500">
        Topics your class is scoring lowest on are flagged as evidence builds up.
      </p>
      <Card className="mt-4">
        <ul className="px-5 py-2">
          {tree.map((node) => (
            <TopicRow key={node.id} node={node} scores={scores} />
          ))}
        </ul>
      </Card>
    </div>
  );
}
