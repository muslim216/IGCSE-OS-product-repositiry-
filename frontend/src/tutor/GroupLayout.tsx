import { Link, Outlet, useOutletContext, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getGroup, type GroupDetail } from "../api/groups";
import { formatSlot } from "../lib/schedule";
import { Badge, CountBadge, Tabs, type TabItem } from "../ui";

interface GroupContext {
  group: GroupDetail;
  groupId: number;
}

/** Read the class the surrounding layout already loaded, from any section or detail page. */
export function useGroupContext(): GroupContext {
  return useOutletContext<GroupContext>();
}

/**
 * The shell every part of a class renders inside: one header, one set of tabs,
 * and the group loaded once and shared. Sections are real routes, so a tab can
 * be linked to and survives a refresh.
 */
export default function GroupLayout() {
  const { groupId } = useParams();
  const id = Number(groupId);
  const group = useQuery({ queryKey: ["group", id], queryFn: () => getGroup(id) });

  if (group.isLoading) return <p className="text-slate-500">Loading…</p>;
  if (group.isError || !group.data) return <p className="text-risk-600">Class not found.</p>;

  const g = group.data;
  const base = `/tutor/groups/${id}`;
  const tabs: TabItem[] = [
    {
      to: `${base}/homework`,
      label: "Homework",
      badge: <CountBadge count={g.awaiting_review_count} tone="caution" />,
    },
    { to: `${base}/students`, label: "Students" },
    { to: `${base}/syllabus`, label: "Syllabus" },
    { to: `${base}/schedule`, label: "Schedule" },
    { to: `${base}/analytics`, label: "Analytics" },
  ];

  return (
    <div>
      <Link to="/tutor" className="text-sm text-brand-600 hover:underline">
        ← All classes
      </Link>

      <div className="mt-2 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-xl font-semibold text-slate-900">{g.name}</h2>
          <p className="text-sm text-slate-500">
            {g.subject.exam_board} {g.subject.code} · {g.subject.name}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge>
            {g.member_count} {g.member_count === 1 ? "student" : "students"}
          </Badge>
          {g.next_lesson && (
            <Badge tone="brand">
              Next {formatSlot(g.next_lesson.weekday, g.next_lesson.start_time)}
            </Badge>
          )}
        </div>
      </div>

      <Tabs items={tabs} className="mt-5" />

      <div className="py-6">
        <Outlet context={{ group: g, groupId: id } satisfies GroupContext} />
      </div>
    </div>
  );
}
