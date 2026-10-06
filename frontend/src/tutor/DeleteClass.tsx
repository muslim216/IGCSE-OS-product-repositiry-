import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { deleteGroup } from "../api/groups";
import { Button } from "../components/controls";
import { ConfirmDialog } from "../components/page";
import { friendlyError } from "../lib/errors";

/** Queries about this one class. They are dropped, not refetched: asking for a
 *  class that no longer exists would only come back as a 404. */
const CLASS_KEYS = [
  "group",
  "class-overview",
  "plan",
  "lessons",
  "taught-lessons",
  "taught-before",
  "resources",
  "analytics",
  "next-lesson",
  "narrative",
] as const;

/** Queries that list across classes, so they could still show this one. */
const LIST_KEYS = [
  "groups",
  "today",
  "today-overview",
  "today-lessons",
  "onboarding",
  "homework",
  "students",
  "review-queue",
  "assignments-attention",
  "lesson-reminders",
  "mocks",
  "student-attendance",
] as const;

/**
 * "Delete class", kept quiet with the class's own settings at the foot of the
 * page. It asks first, in words, because the app has no way back: the data is
 * kept, but nothing here brings the class back.
 */
export function DeleteClass({ groupId, name }: { groupId: number; name: string }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);

  const remove = useMutation({
    mutationFn: () => deleteGroup(groupId),
    onSuccess: () => {
      // Leave first, so the class page is gone before its queries are.
      navigate("/tutor/classes", { state: { notice: `${name} was deleted.` } });
      for (const key of CLASS_KEYS) {
        queryClient.removeQueries({
          predicate: (q) =>
            q.queryKey[0] === key &&
            (q.queryKey[1] === groupId || (key === "narrative" && q.queryKey[2] === groupId)),
        });
      }
      for (const key of LIST_KEYS) queryClient.invalidateQueries({ queryKey: [key] });
      queryClient.invalidateQueries({ queryKey: ["resources", "library"] });
    },
  });

  return (
    <section aria-labelledby="class-settings" className="mt-10 border-t border-line pt-6">
      <h2 id="class-settings" className="text-sm font-medium text-ink-700">
        Class settings
      </h2>
      <div className="mt-3">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            remove.reset();
            setOpen(true);
          }}
        >
          Delete class
        </Button>
      </div>

      <ConfirmDialog
        open={open}
        title={`Delete ${name}?`}
        body={
          <>
            <p>
              {name} will disappear for you and for its students. Its lessons, reminders and
              messages will stop.
            </p>
            <p className="mt-3">
              Marks and history are kept, and your students&rsquo; readiness does not change.
            </p>
            <p className="mt-3">This can&rsquo;t be undone from the app.</p>
            {remove.isError && (
              <p role="alert" className="mt-3 text-risk-600">
                {friendlyError(remove.error, "The class wasn't deleted. Try again.")}
              </p>
            )}
          </>
        }
        confirmLabel="Delete class"
        danger
        focusCancel
        busy={remove.isPending}
        onConfirm={() => remove.mutate()}
        onCancel={() => setOpen(false)}
      />
    </section>
  );
}
