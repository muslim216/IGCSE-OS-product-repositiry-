import type { AssignmentAttention } from "../api/homework";

/** Where an item on the tutor's to-do list is dealt with.
 *
 * One place, because the list renders on Today and on Review, and two copies
 * of this choice are two chances to send a past paper to an assignment URL. A
 * submission opens its marking review; a past paper the AI couldn't read goes
 * to the past-papers shelf, which holds the fix; anything else is homework.
 */
export function attentionHref(item: AssignmentAttention): string {
  if (item.submission_id) return `/tutor/submissions/${item.submission_id}`;
  if (item.past_paper_id) return `/tutor/past-papers#paper-${item.past_paper_id}`;
  return `/tutor/assignments/${item.assignment_id}`;
}
