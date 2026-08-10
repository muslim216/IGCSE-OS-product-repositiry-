import { useEffect } from "react";
import { Bell, Plus, Search } from "lucide-react";
import { Link } from "react-router-dom";
import type { AssignmentAttention } from "../../api/homework";
import { REASON_LABELS } from "../../lib/labels";
import { greetingFor } from "../../lib/readiness";

function firstName(name: string | undefined): string {
  return (name ?? "").split(" ")[0] || "there";
}

export default function DashboardHeader({
  name,
  searchOpen,
  onSearchToggle,
  searchQuery,
  onSearchChange,
  notifOpen,
  onNotifToggle,
  notifItems,
  onCreateLesson,
}: {
  name: string | undefined;
  searchOpen: boolean;
  onSearchToggle: () => void;
  searchQuery: string;
  onSearchChange: (value: string) => void;
  notifOpen: boolean;
  onNotifToggle: () => void;
  /** Undefined while loading — the badge stays empty rather than showing a placeholder. */
  notifItems: AssignmentAttention[] | undefined;
  onCreateLesson: () => void;
}) {
  const now = new Date();
  const dateLabel = new Intl.DateTimeFormat("en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
  }).format(now);
  const count = notifItems?.length ?? 0;

  useEffect(() => {
    if (!notifOpen) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onNotifToggle();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [notifOpen, onNotifToggle]);

  return (
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wider text-brand-600">{dateLabel}</p>
        <h1 className="mt-1.5 text-2xl font-semibold text-ink-900">
          {greetingFor(now.getHours())}, {firstName(name)}.
        </h1>
        <p className="mt-1 text-sm text-ink-500">
          Here is the clearest path for your learners today.
        </p>
      </div>

      <div className="flex items-center gap-2">
        {searchOpen && (
          <input
            type="search"
            autoFocus
            aria-label="Search learners"
            placeholder="Search learners…"
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            className="w-44 rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink-900 placeholder:text-ink-500 focus:border-brand-500 focus:outline-none"
          />
        )}
        <button
          type="button"
          aria-label="Search learners"
          aria-expanded={searchOpen}
          onClick={onSearchToggle}
          className="rounded-md border border-line bg-surface p-2 text-ink-500 transition hover:border-line-strong hover:text-ink-900"
        >
          <Search aria-hidden className="h-4 w-4" />
        </button>

        <div className="relative">
          <button
            type="button"
            aria-label="Notifications"
            aria-expanded={notifOpen}
            onClick={onNotifToggle}
            className="relative rounded-md border border-line bg-surface p-2 text-ink-500 transition hover:border-line-strong hover:text-ink-900"
          >
            <Bell aria-hidden className="h-4 w-4" />
            {count > 0 && (
              <span className="absolute -right-1 -top-1 grid h-4 min-w-4 place-items-center rounded-full bg-brand-600 px-1 text-[10px] font-semibold text-canvas">
                {count}
              </span>
            )}
          </button>
          {notifOpen && (
            <div className="absolute right-0 z-20 mt-2 w-72 rounded-lg border border-line bg-surface p-3 shadow-lg">
              <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                Needs your review
              </p>
              <ul className="mt-2 space-y-2">
                {(notifItems ?? []).slice(0, 5).map((item, i) => (
                  <li key={i} className="text-sm">
                    <Link
                      to={
                        item.submission_id
                          ? `/tutor/submissions/${item.submission_id}`
                          : `/tutor/assignments/${item.assignment_id}`
                      }
                      className="font-medium text-ink-900 hover:text-brand-500"
                    >
                      {item.assignment_title}
                    </Link>
                    <span className="block text-xs text-warn-700">
                      {REASON_LABELS[item.reason] ?? item.reason}
                    </span>
                  </li>
                ))}
                {count === 0 && (
                  <li className="text-sm text-ink-500">Nothing needs review right now.</li>
                )}
              </ul>
            </div>
          )}
        </div>

        <button
          type="button"
          onClick={onCreateLesson}
          className="flex items-center gap-1.5 rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-canvas transition hover:bg-brand-500"
        >
          <Plus aria-hidden className="h-4 w-4" />
          Create lesson
        </button>
      </div>
    </header>
  );
}
