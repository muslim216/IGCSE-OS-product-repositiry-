import { NavLink, Outlet, useOutletContext, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { CalendarClock, Users } from "lucide-react";
import { getGroup, type GroupDetail } from "../api/groups";
import { ApiError } from "../api/client";
import { formatSlot } from "../lib/schedule";
import { ErrorState, NotFoundState, PageHeader, PageSkeleton } from "../components/page";
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
          isActive ? "bg-brand-600 text-canvas" : "text-ink-500 hover:bg-surface hover:text-ink-900"
        }`
      }
    >
      {label}
      {badge ? (
        <span
          title={`${badge} to review`}
          className="rounded-full bg-warn-100 px-1.5 text-xs font-semibold text-warn-700"
        >
          {badge}
          <span className="sr-only"> to review</span>
        </span>
      ) : null}
    </NavLink>
  );
}

const ALL_CLASSES = { to: "/tutor/classes", label: "All classes" };

/**
 * The shell every part of a class renders inside: one header, one set of tabs,
 * and the group loaded once and shared. Tabs are real routes, so each can be
 * linked to and survives a refresh.
 */
export default function GroupLayout() {
  const { groupId } = useParams();
  const id = Number(groupId);
  const group = useQuery({ queryKey: ["group", id], queryFn: () => getGroup(id) });

  if (group.isLoading) return <PageSkeleton label="Loading class" />;
  if (group.isError && group.error instanceof ApiError && group.error.status === 404) {
    return (
      <NotFoundState
        title="We couldn't find that class"
        body="It may have been deleted, or the link may be wrong."
        back={ALL_CLASSES}
      />
    );
  }
  if (group.isError || !group.data) {
    return (
      <ErrorState
        title="This class didn't load"
        error={group.error}
        onRetry={() => group.refetch()}
      />
    );
  }

  const g = group.data;
  const base = `/tutor/groups/${id}`;

  return (
    <div>
      <PageHeader
        title={g.name}
        back={ALL_CLASSES}
        description={`${g.subject.exam_board} ${g.subject.code} · ${g.subject.name}`}
        meta={
          <>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-surface-muted px-2.5 py-1 text-xs text-ink-700">
              <Users aria-hidden className="h-3.5 w-3.5" />
              {g.member_count} {g.member_count === 1 ? "student" : "students"}
            </span>
            {g.next_lesson && (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-100 px-2.5 py-1 text-xs font-medium text-brand-600">
                <CalendarClock aria-hidden className="h-3.5 w-3.5" />
                Next lesson {formatSlot(g.next_lesson.weekday, g.next_lesson.start_time)}
              </span>
            )}
          </>
        }
      />

      {/* The class's headline — verdict, WHY, NEEDS YOU — above the tabs, so the
          first thing read answers "how is this class?" rather than "which tab?".
          A class nobody has joined renders the empty room instead. */}
      <ClassOverviewPanel groupId={id} />

      <nav
        aria-label="Class sections"
        className="mt-8 flex gap-1 overflow-x-auto border-b border-line pb-3"
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
