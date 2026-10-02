import { useEffect, useRef, useState, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Bell, CheckCircle2, ClipboardCheck, FileText, type LucideIcon } from "lucide-react";
import { myActivity } from "../api/activity";
import { useMyTimezone } from "../auth/AuthContext";
import { formatDayMonth } from "../lib/timezones";
import { SectionSkeleton } from "./page";

/** An icon per kind of item, so the list can be scanned without reading every
    line. Unknown kinds fall back to the bell rather than failing. */
const KIND_ICON: Record<string, LucideIcon> = {
  submission_awaiting_review: ClipboardCheck,
  homework_marked: CheckCircle2,
  report_ready: FileText,
};

function relativeTime(iso: string, timeZone: string | null): string {
  const then = new Date(iso).getTime();
  const minutes = Math.round((Date.now() - then) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return days < 7 ? `${days}d ago` : formatDayMonth(new Date(iso), timeZone);
}

/**
 * One place to see what's waiting. The count is derived from live rows rather
 * than a read/unread flag, so it falls as the work is dealt with — there is
 * nothing to mark as seen.
 */
/** Where the panel goes, from where the bell is on screen.
 *
 * The bell lives in two places: the foot of the desktop sidebar, and the
 * top-right of the mobile header. A panel that always dropped down and right
 * opened off the bottom of the screen from the first, and was clipped by the
 * 240px sidebar's own scroll container. `fixed` escapes that clipping (the
 * sidebar is sticky, which creates no containing block for it), and the panel
 * opens towards whichever side of the screen has room. */
function placementFor(trigger: HTMLElement): CSSProperties {
  const r = trigger.getBoundingClientRect();
  const gap = 8;
  const edge = 16;
  const style: CSSProperties = {};
  if (r.top > window.innerHeight / 2) style.bottom = window.innerHeight - r.top + gap;
  else style.top = r.bottom + gap;
  if (r.left + r.width / 2 < window.innerWidth / 2) style.left = Math.max(edge, r.left);
  else style.right = Math.max(edge, window.innerWidth - r.right);
  return style;
}

export default function ActivityMenu() {
  const [open, setOpen] = useState(false);
  const [placement, setPlacement] = useState<CSSProperties>({});
  const wrapper = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const myZone = useMyTimezone();
  const activity = useQuery({
    queryKey: ["activity"],
    queryFn: myActivity,
    refetchInterval: 120_000,
  });

  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: MouseEvent) {
      if (!wrapper.current?.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setOpen(false);
        trigger.current?.focus();
      }
    }
    // The placement was measured on open; a resize moves the bell (sidebar to
    // header and back), so close rather than float somewhere stale.
    function onResize() {
      setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", onResize);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", onResize);
    };
  }, [open]);

  const count = activity.data?.count ?? 0;
  const items = activity.data?.items ?? [];

  return (
    <div ref={wrapper} className="relative">
      <button
        ref={trigger}
        type="button"
        onClick={() => {
          if (!open && trigger.current) setPlacement(placementFor(trigger.current));
          setOpen((v) => !v);
        }}
        aria-label={count > 0 ? `Activity, ${count} waiting` : "Activity"}
        aria-expanded={open}
        aria-haspopup="true"
        className="relative grid h-8 w-8 place-items-center rounded-md text-ink-500 transition-colors hover:bg-surface-muted hover:text-ink-900"
      >
        <Bell aria-hidden className="h-4 w-4" />
        {count > 0 && (
          <span className="absolute -right-0.5 -top-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-brand-600 px-1 text-[10px] font-semibold tabular-nums text-canvas ring-2 ring-surface">
            {count > 9 ? "9+" : count}
          </span>
        )}
      </button>

      {/* Clamped to the viewport: the sidebar this sits in is only 240px wide,
          and the mobile header narrower still. */}
      {open && (
        <div
          style={placement}
          className="fixed z-50 w-[min(22rem,calc(100vw-2rem))] overflow-hidden rounded-xl border border-line bg-surface shadow-lg"
        >
          <div className="flex items-baseline justify-between gap-3 border-b border-line px-4 py-3">
            <p className="font-display text-base text-ink-900">Activity</p>
            {count > 0 && <p className="text-xs tabular-nums text-ink-500">{count} waiting</p>}
          </div>
          {activity.isPending ? (
            <div className="px-4 py-4">
              <SectionSkeleton rows={3} label="Loading activity" />
            </div>
          ) : activity.isError ? (
            // A failed request knows nothing about what is waiting, so it must
            // not read as "nothing waiting on you".
            <p className="px-4 py-6 text-center text-sm text-ink-500">
              Activity couldn&apos;t be loaded. It will try again shortly.
            </p>
          ) : items.length === 0 ? (
            <div className="px-4 py-8 text-center">
              <CheckCircle2 aria-hidden className="mx-auto h-6 w-6 text-ok-700" />
              <p className="mt-2 text-sm font-medium text-ink-900">You&apos;re all caught up.</p>
              <p className="mt-0.5 text-xs text-ink-500">Nothing is waiting on you.</p>
            </div>
          ) : (
            <ul className="max-h-[min(24rem,55vh)] divide-y divide-line overflow-y-auto">
              {items.map((item) => {
                const Icon = KIND_ICON[item.kind] ?? Bell;
                return (
                  <li key={`${item.kind}-${item.link}-${item.occurred_at}`}>
                    <Link
                      to={item.link}
                      onClick={() => setOpen(false)}
                      className="flex gap-3 px-4 py-3 transition-colors hover:bg-surface-muted"
                    >
                      <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full bg-brand-50 text-brand-600">
                        <Icon aria-hidden className="h-3.5 w-3.5" />
                      </span>
                      <span className="min-w-0">
                        <span className="block text-sm text-ink-900">{item.label}</span>
                        <span className="mt-0.5 block text-xs text-ink-500">
                          {item.sublabel ? `${item.sublabel} · ` : ""}
                          {relativeTime(item.occurred_at, myZone)}
                        </span>
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
          {/* The count covers everything outstanding, which can be more than
              the list carries — say so rather than let the two disagree. */}
          {!activity.isError && count > items.length && items.length > 0 && (
            <p className="border-t border-line px-4 py-2.5 text-xs text-ink-500">
              Showing the latest {items.length} of {count}.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
