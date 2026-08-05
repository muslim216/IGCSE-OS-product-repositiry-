import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import { myActivity } from "../api/activity";

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const minutes = Math.round((Date.now() - then) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return days < 7 ? `${days}d ago` : new Date(iso).toLocaleDateString();
}

/**
 * One place to see what's waiting. The count is derived from live rows rather
 * than a read/unread flag, so it falls as the work is dealt with — there is
 * nothing to mark as seen.
 */
export default function ActivityMenu() {
  const [open, setOpen] = useState(false);
  const wrapper = useRef<HTMLDivElement>(null);
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
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const count = activity.data?.count ?? 0;
  const items = activity.data?.items ?? [];

  return (
    <div ref={wrapper} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-label={count > 0 ? `Activity, ${count} waiting` : "Activity"}
        aria-expanded={open}
        className="relative rounded-md p-1.5 text-ink-500 transition hover:bg-surface hover:text-ink-900"
      >
        <Bell aria-hidden className="h-4 w-4" />
        {count > 0 && (
          <span className="absolute -right-0.5 -top-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-brand-600 px-1 text-[10px] font-semibold text-canvas">
            {count > 9 ? "9+" : count}
          </span>
        )}
      </button>

      {/* Anchored right and clamped to the viewport: the sidebar this sits in
          is only 240px wide, and the mobile header narrower still. */}
      {open && (
        <div className="absolute right-0 z-20 mt-2 w-[min(20rem,calc(100vw-2rem))] overflow-hidden rounded-xl border border-line bg-surface shadow-lg">
          <p className="border-b border-line px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-ink-500">
            Activity
          </p>
          {items.length === 0 ? (
            <p className="px-4 py-6 text-center text-sm text-ink-500">
              Nothing waiting on you.
            </p>
          ) : (
            <ul className="max-h-96 divide-y divide-line overflow-y-auto">
              {items.map((item) => (
                <li key={`${item.kind}-${item.link}-${item.occurred_at}`}>
                  <Link
                    to={item.link}
                    onClick={() => setOpen(false)}
                    className="block px-4 py-3 transition hover:bg-surface-muted"
                  >
                    <span className="block text-sm text-ink-700">{item.label}</span>
                    <span className="mt-0.5 block text-xs text-ink-500">
                      {item.sublabel ? `${item.sublabel} · ` : ""}
                      {relativeTime(item.occurred_at)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
