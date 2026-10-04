import { Link } from "react-router-dom";
import type { AssignmentAttention } from "../../api/homework";
import type { RemarkItem } from "../../api/today";
import { attentionHref } from "../../lib/attention";
import { REASON_LABELS } from "../../lib/labels";

const SHOWN = 6;

/**
 * Work waiting on the tutor: re-mark requests, marking, and unreadable
 * homework. Every row says why it is here and links straight to it. A
 * submission a student asked to have re-marked is listed once, as the request
 * (the queue row alone would only say "some marks need your decision").
 * Renders nothing when empty (UX-29).
 */
export default function NeedsYou({
  items,
  remarks,
}: {
  items: AssignmentAttention[];
  remarks: RemarkItem[];
}) {
  const remarked = new Set(remarks.map((r) => r.submission_id));
  const rest = items.filter((i) => !i.submission_id || !remarked.has(i.submission_id));
  if (remarks.length + rest.length === 0) return null;
  const shownRemarks = remarks.slice(0, SHOWN);
  const shownRest = rest.slice(0, SHOWN - shownRemarks.length);
  return (
    <section aria-labelledby="needs-you-heading">
      <h2 id="needs-you-heading" className="avora-label mb-3">
        Needs you
      </h2>
      <ul className="text-sm">
        {shownRemarks.map((r) => (
          <li
            key={`remark-${r.submission_id}`}
            className="flex flex-wrap items-center justify-between gap-2 border-t border-line py-2.5"
          >
            <Link
              to={`/tutor/submissions/${r.submission_id}`}
              className="font-medium text-brand-600 hover:text-brand-700"
            >
              {r.assignment_title}
              <span className="font-normal text-ink-500">
                {" "}
                · {r.student_name} · {r.group_name}
              </span>
            </Link>
            <span className="text-warn-700">
              Asked for a re-mark{r.reason ? `: “${r.reason}”` : ""}
            </span>
          </li>
        ))}
        {shownRest.map((item, i) => (
          <li
            key={i}
            className="flex flex-wrap items-center justify-between gap-2 border-t border-line py-2.5"
          >
            <Link
              to={attentionHref(item)}
              className="font-medium text-brand-600 hover:text-brand-700"
            >
              {item.assignment_title}
              {/* Two students' work on the same homework would otherwise be two
                  identical rows. */}
              {item.student_name && (
                <span className="font-normal text-ink-500"> · {item.student_name}</span>
              )}
              {item.past_paper_id && (
                <span className="font-normal text-ink-500"> · past paper</span>
              )}
            </Link>
            <span className="text-warn-700">{REASON_LABELS[item.reason] ?? item.reason}</span>
          </li>
        ))}
      </ul>
      <Link
        to="/tutor/review"
        className="mt-3 inline-block text-sm font-medium text-brand-600 hover:text-brand-700"
      >
        Open the review queue →
      </Link>
    </section>
  );
}
