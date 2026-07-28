import { Link } from "react-router-dom";
import type { Group } from "../api/groups";
import { formatDuration, formatSlot } from "../lib/schedule";
import { Badge, cn } from "../ui";

/**
 * Subjects get a stable accent so a tutor running several classes can tell them
 * apart at a glance. Keyed off the subject id so the same class always looks the
 * same, without needing a colour stored on the subject.
 */
const ACCENTS = [
  "from-brand-500 to-brand-700",
  "from-ready-500 to-ready-600",
  "from-accent-500 to-accent-600",
  "from-risk-500 to-risk-600",
  "from-caution-500 to-caution-600",
];

function accentFor(subjectId: number): string {
  return ACCENTS[subjectId % ACCENTS.length];
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="truncate text-sm font-medium text-slate-800">{value}</div>
      <div className="text-xs text-slate-500">{label}</div>
    </div>
  );
}

export function GroupCard({ group }: { group: Group }) {
  const { next_lesson: next } = group;
  return (
    <Link
      to={`/tutor/groups/${group.id}`}
      className={cn(
        "group flex flex-col overflow-hidden rounded-card border border-slate-200 bg-surface",
        "shadow-card transition-all hover:-translate-y-0.5 hover:shadow-card-hover",
      )}
    >
      <div className={cn("h-1.5 bg-gradient-to-r", accentFor(group.subject.id))} />

      <div className="flex flex-1 flex-col p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="truncate font-semibold text-slate-900 group-hover:text-brand-700">
              {group.name}
            </h3>
            <p className="mt-0.5 truncate text-sm text-slate-500">
              {group.subject.exam_board} {group.subject.code} · {group.subject.name}
            </p>
          </div>
          {group.awaiting_review_count > 0 && (
            <Badge tone="caution">{group.awaiting_review_count} to mark</Badge>
          )}
        </div>

        <div className="mt-5 grid grid-cols-3 gap-3 border-t border-slate-100 pt-4">
          <Stat
            label={group.member_count === 1 ? "student" : "students"}
            value={String(group.member_count)}
          />
          <Stat label="homework" value={String(group.published_assignment_count)} />
          <Stat
            label={next ? `next · ${formatDuration(next.duration_min)}` : "no lessons yet"}
            value={next ? formatSlot(next.weekday, next.start_time) : "—"}
          />
        </div>
      </div>
    </Link>
  );
}
