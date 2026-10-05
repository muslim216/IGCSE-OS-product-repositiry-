import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { NavLink, Outlet, useLocation, useOutletContext, useParams } from "react-router-dom";
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
        // The active tab has no fill of its own: the sliding indicator behind
        // it is the fill, which is why the tab sits one layer above.
        `avora-press relative z-[1] flex items-center gap-1.5 whitespace-nowrap rounded-full px-3 py-1.5 text-sm font-medium transition ${
          isActive ? "text-canvas" : "text-ink-500 hover:bg-surface hover:text-ink-900"
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

interface TabBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

/* The tab bar that is on screen right now, if any. AppShell keys the page by
   pathname, so changing tab remounts this whole layout — without this the
   indicator would be a new element each time and could only appear, never
   slide. The replacement layout renders before the old one is torn down, so
   finding a live bar for the same class at render time means "the tab
   changed"; finding none means the reader has just arrived at the class. */
let onScreen: { groupId: number; box: TabBox | null } | null = null;

function carriedOver(groupId: number): { box: TabBox } | null {
  // A bar with no fill had no tab selected: that is the class's bare URL, on
  // its way to being redirected to a tab, and the reader has not seen the
  // class yet — so what follows is an arrival, not a tab change.
  if (onScreen?.groupId !== groupId || onScreen.box === null) return null;
  return { box: onScreen.box };
}

/**
 * The class tabs, with a fill that slides from the tab you were on to the one
 * you chose. The fill is measured from whichever link the router marks
 * `aria-current`, so the tabs stay ordinary links and this knows nothing about
 * which routes exist.
 */
function TabBar({ groupId, children }: { groupId: number; children: ReactNode }) {
  const navRef = useRef<HTMLElement>(null);
  const { pathname } = useLocation();
  const [box, setBox] = useState<TabBox | null>(() => carriedOver(groupId)?.box ?? null);
  // True from the first render when the fill is carried over from the previous
  // tab, so it travels; otherwise switched on a frame after it is first
  // placed, so it does not fly in from the corner.
  const [ready, setReady] = useState(() => carriedOver(groupId) !== null);

  useLayoutEffect(() => {
    const nav = navRef.current;
    if (!nav) return;
    function place() {
      const active = nav?.querySelector<HTMLElement>('[aria-current="page"]');
      const next = active
        ? {
            x: active.offsetLeft,
            y: active.offsetTop,
            width: active.offsetWidth,
            height: active.offsetHeight,
          }
        : null;
      // The observer reports once on attach and again on any resize; the same
      // box must stay the same object, or each report is a render.
      setBox((previous) =>
        previous &&
        next &&
        previous.x === next.x &&
        previous.y === next.y &&
        previous.width === next.width &&
        previous.height === next.height
          ? previous
          : next,
      );
    }
    place();
    // A tab changes width when the webfont arrives or its badge count moves.
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(place);
    observer.observe(nav);
    for (const tab of nav.querySelectorAll("a")) observer.observe(tab);
    return () => observer.disconnect();
  }, [pathname]);

  useEffect(() => {
    const frame = requestAnimationFrame(() => setReady(true));
    return () => cancelAnimationFrame(frame);
  }, []);

  // A layout effect, so the outgoing bar is cleared in the same commit that
  // mounts its replacement and the two never overlap.
  useLayoutEffect(() => {
    const mine = { groupId, box };
    onScreen = mine;
    return () => {
      if (onScreen === mine) onScreen = null;
    };
  }, [groupId, box]);

  return (
    <nav
      ref={navRef}
      aria-label="Class sections"
      className="relative mt-8 flex gap-1 overflow-x-auto border-b border-line pb-3"
    >
      {box && (
        <span
          aria-hidden
          data-ready={ready || undefined}
          className="avora-tab-indicator"
          style={{
            transform: `translate(${box.x}px, ${box.y}px)`,
            width: box.width,
            height: box.height,
          }}
        />
      )}
      {children}
    </nav>
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
  const { pathname } = useLocation();
  const id = Number(groupId);
  // A class URL whose id is not a whole number names no class at all. Asked
  // anyway, it came back a 422 and read as "This class didn't load" with a
  // retry that could never succeed, so it is answered here as not found.
  const validId = Number.isInteger(id);
  // Read once, on mount: by the next render this layout's own tab bar is the
  // one on screen.
  const [sameClassAsLastRender] = useState(() => carriedOver(id) !== null);
  const group = useQuery({
    queryKey: ["group", id],
    queryFn: () => getGroup(id),
    enabled: validId,
  });

  if (group.isLoading) return <PageSkeleton label="Loading class" />;
  if (
    !validId ||
    (group.isError && group.error instanceof ApiError && group.error.status === 404)
  ) {
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
  // The class's bare URL redirects to Homework (App.tsx), so Homework is the
  // landing tab. Matched on the path, ignoring a trailing slash.
  const onLandingTab = pathname.replace(/\/+$/, "") === `${base}/homework`;

  return (
    <div>
      {/* Changing tab re-shows the header and headline rather than arriving at
          them, so they hold still and only the tab's own content comes in. */}
      <div className={sameClassAsLastRender ? "avora-still" : undefined}>
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

        {/* The class's headline — verdict, WHY, NEEDS YOU — sits above the tabs so
          the first thing read answers "how is this class?" rather than "which
          tab?". It shows on the landing tab only: repeated above every tab it
          pushed the chosen tab's own content below the fold, so every other
          tab opens with just the class name line and the tabs. A class nobody
          has joined renders the empty room instead. */}
        {onLandingTab && <ClassOverviewPanel groupId={id} />}
      </div>

      <TabBar groupId={id}>
        <Tab to={`${base}/homework`} label="Homework" badge={g.awaiting_review_count} />
        <Tab to={`${base}/students`} label="Students" />
        <Tab to={`${base}/syllabus`} label="Syllabus" />
        <Tab to={`${base}/schedule`} label="Schedule" />
        <Tab to={`${base}/resources`} label="Resources" />
        <Tab to={`${base}/analytics`} label="Analytics" />
      </TabBar>

      <div className="py-6">
        <Outlet context={{ group: g, groupId: id } satisfies GroupContext} />
      </div>
    </div>
  );
}
