import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  myParentLinks,
  removeMyParentLink,
  removeStudentParent,
  studentParents,
  type LinkedParent,
} from "../api/parentLinks";
import { Button } from "./controls";
import { ConfirmDialog, SectionSkeleton } from "./page";
import { SectionCard, SectionHeader } from "./ui";
import { friendlyError } from "../lib/errors";

/**
 * Who can read this child's marks, reports and attendance, with a way to cut one
 * off. A tutor passes `studentId`; a student passes nothing and sees their own.
 * Removal takes effect at once and the parent needs a new code to come back, so
 * it asks first and says so.
 */
export default function LinkedParents({ studentId }: Readonly<{ studentId?: number }>) {
  const queryClient = useQueryClient();
  const own = studentId === undefined;
  const key = ["linked-parents", studentId ?? "me"];
  const parents = useQuery({
    queryKey: key,
    queryFn: () => (studentId === undefined ? myParentLinks() : studentParents(studentId)),
  });
  const [target, setTarget] = useState<LinkedParent | null>(null);

  const remove = useMutation({
    mutationFn: (link: LinkedParent) =>
      studentId === undefined
        ? removeMyParentLink(link.id)
        : removeStudentParent(studentId, link.id),
    onSuccess: () => {
      setTarget(null);
      void queryClient.invalidateQueries({ queryKey: key });
      void queryClient.invalidateQueries({ queryKey: ["student-contacts"] });
    },
  });

  return (
    <SectionCard>
      <SectionHeader
        title="Linked parents"
        description={`These people can see ${own ? "your" : "this child's"} marks, reports and attendance.`}
      />
      {parents.isLoading ? (
        <div className="mt-4">
          <SectionSkeleton rows={2} label="Loading linked parents" />
        </div>
      ) : parents.isError ? (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <p role="alert" className="text-sm text-risk-600">
            The linked parents didn&apos;t load.
          </p>
          <Button variant="secondary" size="sm" onClick={() => parents.refetch()}>
            Try again
          </Button>
        </div>
      ) : (parents.data ?? []).length === 0 ? (
        <p className="mt-3 text-sm text-ink-500">No parent is linked.</p>
      ) : (
        <ul className="mt-3 divide-y divide-line">
          {(parents.data ?? []).map((p) => (
            <li key={p.id} className="flex flex-wrap items-center gap-3 py-2">
              <span className="min-w-0 flex-1 truncate text-sm text-ink-900">
                {p.name}
                <span className="ml-2 text-ink-500">{p.email}</span>
              </span>
              <Button
                variant="secondary"
                size="sm"
                aria-label={`Remove ${p.name}`}
                onClick={() => {
                  remove.reset();
                  setTarget(p);
                }}
              >
                Remove
              </Button>
            </li>
          ))}
        </ul>
      )}

      <ConfirmDialog
        open={target !== null}
        title={`Remove ${target?.name ?? "this parent"}?`}
        body={
          <>
            <p>
              They will stop seeing {own ? "your" : "this child's"} marks, reports and attendance
              straight away. To see them again they would need a new link from the tutor.
            </p>
            {remove.isError && (
              <p role="alert" className="mt-3 text-risk-600">
                {friendlyError(remove.error, "That didn't work. Try again.")}
              </p>
            )}
          </>
        }
        confirmLabel="Remove"
        danger
        focusCancel
        busy={remove.isPending}
        onConfirm={() => target && remove.mutate(target)}
        onCancel={() => setTarget(null)}
      />
    </SectionCard>
  );
}
