import { useId, type ReactNode } from "react";
import type { Subject } from "../api/groups";
import type { SubjectGroup } from "../lib/subjectGroups";
import { Field, Select } from "./controls";

/** "All subjects" plus one option per subject that has something in the list. */
export function SubjectPicker({
  groups,
  value,
  onChange,
}: {
  groups: SubjectGroup<unknown>[];
  value: string;
  onChange: (id: string) => void;
}) {
  return (
    <Field label="Subject" className="max-w-xs">
      <Select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">All subjects</option>
        {groups.map((g) => (
          <option key={g.id} value={g.id}>
            {g.subject ? `${g.subject.name} (${g.subject.exam_board})` : "Other subject"}
          </option>
        ))}
      </Select>
    </Field>
  );
}

/** One subject's heading and its list. An `h3`: the page's h1 and its
 *  section's h2 sit above. */
export function SubjectSection({
  subject,
  children,
}: {
  subject: Subject | null;
  children: ReactNode;
}) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="space-y-1">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <h3 id={headingId} className="font-medium text-ink-900">
          {subject?.name ?? "Other subject"}
        </h3>
        {subject && (
          <span className="text-sm text-ink-500">
            {subject.exam_board} {subject.code}
          </span>
        )}
      </div>
      {children}
    </section>
  );
}
