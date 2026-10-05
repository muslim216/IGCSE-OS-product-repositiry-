import { Link } from "react-router-dom";
import type { ClassAttention, ClassCard, ClassStripRow } from "../../api/today";
import ReadinessFigure from "../../components/ReadinessFigure";

function planLine(card: ClassCard): string {
  switch (card.plan_state) {
    case "behind":
      return `${card.plan_missed} ${card.plan_missed === 1 ? "lesson" : "lessons"} behind`;
    case "on_track":
      return `Chapter ${card.plan_chapter_code} · on track`;
    case "complete":
      return "Plan complete";
    default:
      return "No teaching plan yet";
  }
}

/** Which way readiness moved; the figure itself sits in the card's header,
    written the one way readiness is written everywhere (coherence C.6). */
function readinessDirectionLine(row: ClassStripRow, card: ClassCard | undefined): string | null {
  if (row.score === null) return null;
  switch (card?.readiness_direction) {
    case "up":
      return "Readiness up since last week";
    case "down":
      return "Readiness down since last week";
    case "flat":
      return "Readiness steady since last week";
    default:
      return null;
  }
}

function lastLessonLine(card: ClassCard): string {
  const last = card.last_lesson;
  if (!last) return "No lessons held yet";
  const total = last.present + last.absent + last.not_taken;
  if (last.present + last.absent === 0) {
    return total === 0 ? "Last lesson: no students" : "Last lesson: attendance not taken";
  }
  const missed = last.not_taken > 0 ? ` · ${last.not_taken} not taken` : "";
  return `Last lesson: ${last.present} of ${total} present${missed}`;
}

/** Where the attention item is dealt with — the fix, not the class page. */
export function attentionLink(groupId: number, a: ClassAttention): { to: string; label: string } {
  switch (a.kind) {
    case "weak_topic":
      return { to: `/tutor/groups/${groupId}/analytics`, label: "Open topic →" };
    case "readiness_drop":
      return a.student_ids.length === 1
        ? { to: `/tutor/students/${a.student_ids[0]}`, label: "Open student →" }
        : { to: `/tutor/groups/${groupId}/students`, label: "See students →" };
    case "behind_plan":
      return { to: `/tutor/groups/${groupId}/schedule`, label: "Review the plan →" };
    default:
      return { to: "/tutor/review", label: "Review marking →" };
  }
}

function Card({ row, card }: { row: ClassStripRow; card: ClassCard | undefined }) {
  const attention = card?.attention ?? null;
  const fix = attention ? attentionLink(row.group_id, attention) : null;
  const direction = readinessDirectionLine(row, card);
  return (
    <li className="relative rounded-xl border border-line bg-surface p-4 hover:border-brand-600">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {/* The stretched link makes the whole card open the class while the
            attention link below stays its own, separate link. */}
        <Link
          to={`/tutor/groups/${row.group_id}/students`}
          className="font-medium text-ink-900 after:absolute after:inset-0 hover:text-brand-600"
        >
          {row.name}
        </Link>
        <span className="text-sm text-ink-500">{row.subject_name}</span>
        {/* Raised above the stretched link so the "set them" hint stays clickable. */}
        <span className="relative z-10">
          <ReadinessFigure
            score={row.score}
            grade={row.predicted_grade}
            status={row.status}
            boundariesMissing={row.boundaries_missing}
          />
        </span>
      </div>
      <ul className="mt-2 space-y-0.5 text-sm text-ink-700">
        {card && (
          <li>
            {card.plan_state === "behind" ? (
              // The re-plan lives on the class's schedule tab, whichever
              // attention item the card is showing.
              <Link
                to={`/tutor/groups/${row.group_id}/schedule`}
                className="relative z-10 font-medium text-brand-600 hover:text-brand-700"
              >
                {planLine(card)} →
              </Link>
            ) : (
              planLine(card)
            )}
          </li>
        )}
        {direction && <li>{direction}</li>}
        {card && (
          <>
            <li>{lastLessonLine(card)}</li>
            <li>
              {card.homework_out === 0
                ? "No homework out"
                : `${card.homework_out} homework out · ${card.homework_missing} ${
                    card.homework_missing === 1 ? "hand-in" : "hand-ins"
                  } missing`}
            </li>
          </>
        )}
      </ul>
      {card &&
        (attention && fix ? (
          <p className="relative z-10 mt-3 border-t border-line pt-2.5 text-sm text-warn-700">
            {attention.message}{" "}
            <Link to={fix.to} className="font-medium text-brand-600 hover:text-brand-700">
              {fix.label}
            </Link>
          </p>
        ) : (
          <p className="mt-3 border-t border-line pt-2.5 text-sm text-ink-500">Nothing flagged</p>
        ))}
    </li>
  );
}

/**
 * One card per class, in the strip's order. Each carries its plan position,
 * readiness, last lesson's attendance, homework still out, and the single most
 * important thing to act on — with its reason (C.2), never a bare "needs a
 * look". Cards render from the home aggregate alone while the overview loads.
 */
export default function ClassCards({
  rows,
  cards,
}: {
  rows: ClassStripRow[];
  cards: ClassCard[] | undefined;
}) {
  const byId = new Map((cards ?? []).map((c) => [c.group_id, c]));
  return (
    <section aria-labelledby="classes-heading">
      <h2 id="classes-heading" className="avora-label mb-3">
        Classes
      </h2>
      <ul className="grid gap-3 md:grid-cols-2">
        {rows.map((row) => (
          <Card key={row.group_id} row={row} card={byId.get(row.group_id)} />
        ))}
      </ul>
    </section>
  );
}
