import { Link, NavLink, Outlet, useOutletContext, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getGroup, type GroupDetail } from "../api/groups";
import { formatSlot } from "../lib/schedule";
import ClassOverviewPanel from "./ClassOverview";

interface GroupContext {
  group: GroupDetail;
  groupId: number;
}

/** Read the class the surrounding layout already loaded, from any tab. */
export function useGroupContext(): GroupContext {
  return useOutletContext<GroupContext>();
}

function Tab({ to, label, badge }: { to: string; label: string; badge?: number }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `flex items-center gap-1.5 whitespace-nowrap rounded-full px-3 py-1.5 text-sm font-medium transition ${
          isActive ? "bg-brand-600 text-canvas" : "text-ink-500 hover:bg-surface"
        }`
      }
    >
      {label}
      {badge ? (
        <span className="rounded-full bg-warn-100 px-1.5 text-xs font-semibold text-warn-700">
          {badge}
        </span>
      ) : null}
    </NavLink>
  );
}

/**
 * The shell every part of a class renders inside: one header, one set of tabs,
 * and the group loaded once and shared. Tabs are real routes, so each can be
 * linked to and survives a refresh.
 */
export default function GroupLayout() {
  const { groupId } = useParams();
  const id = Number(groupId);
  const group = useQuery({ queryKey: ["group", id], queryFn: () => getGroup(id) });

  if (group.isLoading) return <p className="text-ink-500">Loading…</p>;
  if (group.isError || !group.data) return <p className="text-risk-600">Class not found.</p>;

  const g = group.data;
  const base = `/tutor/groups/${id}`;

  return (
    <div>
      <Link to="/tutor/classes" className="text-sm text-brand-600 hover:underline">
        ← All classes
      </Link>

      <div className="mt-2 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-xl font-semibold">{g.name}</h2>
          <p className="text-sm text-ink-500">
            {g.subject.exam_board} {g.subject.code} · {g.subject.name}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="rounded-full bg-surface-muted px-2.5 py-1 text-ink-500">
            {g.member_count} {g.member_count === 1 ? "student" : "students"}
          </span>
          {g.next_lesson && (
            <span className="rounded-full bg-brand-100 px-2.5 py-1 font-medium text-brand-600">
              Next {formatSlot(g.next_lesson.weekday, g.next_lesson.start_time)}
            </span>
          )}
        </div>
      </div>

      {/* The class's headline — verdict, WHY, NEEDS YOU — above the tabs, so the
          first thing read answers "how is this class?" rather than "which tab?".
          A class nobody has joined renders the empty room instead. */}
      <div className="mt-5">
        <ClassOverviewPanel groupId={id} />
      </div>

      <nav
        aria-label="Class sections"
        className="mt-6 flex gap-1 overflow-x-auto border-b border-line pb-3"
      >
        <Tab to={`${base}/homework`} label="Homework" badge={g.awaiting_review_count} />
        <Tab to={`${base}/students`} label="Students" />
        <Tab to={`${base}/syllabus`} label="Syllabus" />
        <Tab to={`${base}/schedule`} label="Schedule" />
        <Tab to={`${base}/resources`} label="Resources" />
        <Tab to={`${base}/analytics`} label="Analytics" />
      </nav>

      <div className="py-6">
        <Outlet context={{ group: g, groupId: id } satisfies GroupContext} />
      </div>
    </div>
  );
}
