/** Where a piece of homework is in its life, in words a tutor would use.
 *
 * One map for every screen that names an assignment's status. The class's
 * homework list and the assignment's own page each kept a copy, and they had
 * already drifted apart on `review`. A screen that genuinely says one status
 * differently passes that label as an override, so the difference is a
 * decision written at the call site rather than a second copy. */

export interface AssignmentStatusLook {
  label: string;
  classes: string;
}

const STATUS: Record<string, AssignmentStatusLook> = {
  extracting: { label: "Reading the paper…", classes: "bg-surface-muted text-ink-700" },
  extraction_failed: { label: "Couldn't read the paper", classes: "bg-risk-100 text-risk-600" },
  review: { label: "Check the questions", classes: "bg-warn-100 text-warn-700" },
  published: { label: "Published", classes: "bg-ok-100 text-ok-700" },
  closed: { label: "Closed", classes: "bg-surface-muted text-ink-700" },
};

/** A status this map does not know yet — one added to the backend first —
 *  reads as work in progress, never as the raw enum. */
const IN_PROGRESS: AssignmentStatusLook = {
  label: "In progress",
  classes: "bg-surface-muted text-ink-700",
};

export function assignmentStatus(
  status: string,
  labels: Partial<Record<string, string>> = {},
): AssignmentStatusLook {
  const look = STATUS[status] ?? IN_PROGRESS;
  const label = labels[status];
  return label ? { ...look, label } : look;
}
