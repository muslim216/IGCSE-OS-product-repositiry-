import { useState, type ReactNode } from "react";
import type { Subject } from "../api/groups";
import type { SubjectGroup } from "../lib/subjectGroups";
import { Field, Select } from "./controls";

const OTHER_LABEL = "Other subject";

/** "All subjects" plus one option per subject that has something in the list.
 *
 * A visually hidden status line says what is shown after the reader changes
 * the choice — filtering a list is otherwise silent for a screen reader. It
 * stays empty until then, so nothing is announced on arrival. */
export function SubjectPicker({
  groups,
  value,
  onChange,
  label = "Show subject",
  noun,
}: {
  groups: SubjectGroup<unknown>[];
  value: string;
  onChange: (id: string) => void;
  /** Distinct from any other "Subject" control on the page. */
  label?: string;
  /** What the list holds, singular and plural: ["paper", "papers"]. */
  noun: [string, string];
}) {
  const [changed, setChanged] = useState(false);
  const shown = groups.find((g) => g.id === value);
  const status = !changed
    ? ""
    : shown
      ? `Showing ${shown.items.length} ${shown.items.length === 1 ? noun[0] : noun[1]} in ${shown.subject?.name ?? OTHER_LABEL}`
      : "Showing all subjects";
  return (
    <div>
      <Field label={label} className="max-w-xs">
        <Select
          value={value}
          onChange={(e) => {
            setChanged(true);
            onChange(e.target.value);
          }}
        >
          <option value="">All subjects</option>
          {groups.map((g) => (
            <option key={g.id} value={g.id}>
              {g.subject ? `${g.subject.name} (${g.subject.exam_board})` : OTHER_LABEL}
            </option>
          ))}
        </Select>
      </Field>
      <p role="status" className="sr-only">
        {status}
      </p>
    </div>
  );
}

/** One subject's heading and its list. The level is the caller's: h2 directly
 *  under a page's h1, h3 inside a section that already has an h2. */
export function SubjectSection({
  subject,
  level: Heading = "h3",
  children,
}: {
  subject: Subject | null;
  level?: "h2" | "h3";
  children: ReactNode;
}) {
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <Heading className="font-medium text-ink-900">{subject?.name ?? OTHER_LABEL}</Heading>
        {subject && (
          <span className="text-sm text-ink-500">
            {subject.exam_board} {subject.code}
          </span>
        )}
      </div>
      {children}
    </div>
  );
}
