import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { myActivity } from "../api/me";
import { cn } from "../ui";

function relativeTime(iso: string): string {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

/**
 * Header signal for "what changed since I was last here". Polls on the same
 * interval convention ReportsPanel already uses, rather than adding sockets.
 */
export function ActivityBell() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const activity = useQuery({
    queryKey: ["activity"],
    queryFn: myActivity,
    refetchInterval: 60000,
  });

  useEffect(() => {
    if (!open) return;
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [open]);

  const count = activity.data?.count ?? 0;
  const items = activity.data?.items ?? [];

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-label={count > 0 ? `Activity, ${count} needing attention` : "Activity"}
        aria-expanded={open}
        className="relative flex h-9 w-9 items-center justify-center rounded-full text-slate-500 transition-colors hover:bg-surface-muted hover:text-slate-900"
      >
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.7}>
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M15 17h5l-1.4-1.4A2 2 0 0 1 18 14.2V11a6 6 0 1 0-12 0v3.2c0 .5-.2 1-.6 1.4L4 17h5m6 0a3 3 0 1 1-6 0m6 0H9"
          />
        </svg>
        {count > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex min-w-4 items-center justify-center rounded-full bg-brand-600 px-1 text-[10px] font-semibold leading-4 text-white">
            {count > 9 ? "9+" : count}
          </span>
        )}
      </button>

      {open && (
        <div
          className={cn(
            "absolute right-0 z-20 mt-2 w-80 overflow-hidden rounded-card border border-slate-200",
            "bg-surface shadow-pop",
          )}
        >
          <p className="border-b border-slate-200 px-4 py-2.5 text-sm font-medium text-slate-700">
            Activity
          </p>
          {items.length === 0 ? (
            <p className="px-4 py-6 text-center text-sm text-slate-500">Nothing new right now.</p>
          ) : (
            <ul className="max-h-80 divide-y divide-slate-100 overflow-y-auto">
              {items.map((item, i) => (
                <li key={`${item.kind}-${i}`}>
                  <Link
                    to={item.link}
                    onClick={() => setOpen(false)}
                    className="block px-4 py-2.5 hover:bg-surface-muted"
                  >
                    <span className="block text-sm text-slate-800">{item.label}</span>
                    <span className="mt-0.5 block text-xs text-slate-500">
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
