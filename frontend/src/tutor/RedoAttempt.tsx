import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { redoAttempt } from "../api/homework";
import { Button } from "../components/controls";
import { ConfirmDialog } from "../components/page";
import { friendlyError } from "../lib/errors";

/** Queries that list or total work across submissions, so they could still
 *  show the attempt that was just set aside. */
const LIST_KEYS = [
  "review-queue",
  "submissions",
  "assignment",
  "assignments-attention",
  "homework",
  "mocks",
  "past-papers",
  "today",
  "today-overview",
  "student-readiness",
  "student-mistakes",
  "student-redos",
  "class-overview",
  "analytics",
  "topic-evidence",
  "activity",
  "students",
] as const;

/**
 * "Let them redo this", on a submission whose marks are locked. A secondary
 * button that asks first, in words, because the marks stop counting and do not
 * come back: a record of the attempt is kept, but nothing here restores it.
 *
 * The server decides whether the button is offered (`can_redo`) and refuses with
 * its own sentence when that has changed since the page loaded; that sentence is
 * shown inside the dialog rather than swallowed.
 */
export function RedoAttempt({
  submissionId,
  studentName,
  onDone,
}: Readonly<{ submissionId: number; studentName: string; onDone: () => void }>) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const firstName = studentName.trim().split(/\s+/)[0] || "the student";

  const redo = useMutation({
    mutationFn: () => redoAttempt(submissionId),
    onSuccess: () => {
      setOpen(false);
      // Dropped, not refetched: the submission no longer exists, so asking for
      // it again would only come back as a 404.
      queryClient.removeQueries({ queryKey: ["submission", submissionId] });
      for (const key of LIST_KEYS) queryClient.invalidateQueries({ queryKey: [key] });
      onDone();
    },
  });

  return (
    <>
      <Button
        variant="secondary"
        onClick={() => {
          redo.reset();
          setOpen(true);
        }}
      >
        Let them redo this
      </Button>

      <ConfirmDialog
        open={open}
        title={`Let ${firstName} redo this?`}
        body={
          <>
            <p>
              They will be able to hand this in again. The marks from this attempt will stop
              counting toward readiness and cannot be brought back. A record of them is kept.
            </p>
            {redo.isError && (
              <p role="alert" className="mt-3 text-risk-600">
                {friendlyError(redo.error, "That didn't work. Try again.")}
              </p>
            )}
          </>
        }
        confirmLabel="Let them redo it"
        focusCancel
        busy={redo.isPending}
        onConfirm={() => redo.mutate()}
        onCancel={() => setOpen(false)}
      />
    </>
  );
}
