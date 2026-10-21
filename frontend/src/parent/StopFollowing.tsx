import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { stopFollowingChild } from "../api/parentLinks";
import { Button } from "../components/controls";
import { ConfirmDialog } from "../components/page";
import { friendlyError } from "../lib/errors";

/** A parent ends their own access to one child. Asks first: getting back in
 *  takes a new code from the tutor. */
export default function StopFollowing({
  studentId,
  name,
  onDone,
}: Readonly<{ studentId: number; name: string; onDone: () => void }>) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const stop = useMutation({
    mutationFn: () => stopFollowingChild(studentId),
    onSuccess: () => {
      setOpen(false);
      // Everything read for this child now 404s; drop it rather than refetch.
      queryClient.removeQueries({ predicate: (q) => q.queryKey.includes(studentId) });
      void queryClient.invalidateQueries({ queryKey: ["my-children"] });
      onDone();
    },
  });

  return (
    <>
      <Button
        variant="secondary"
        onClick={() => {
          stop.reset();
          setOpen(true);
        }}
      >
        Stop following this child
      </Button>
      <ConfirmDialog
        open={open}
        title={`Stop following ${name}?`}
        body={
          <>
            <p>
              You will no longer see {name}&apos;s marks, reports or attendance. To follow them
              again you would need a new link from their tutor.
            </p>
            {stop.isError && (
              <p role="alert" className="mt-3 text-risk-600">
                {friendlyError(stop.error, "That didn't work. Try again.")}
              </p>
            )}
          </>
        }
        confirmLabel="Stop following"
        danger
        focusCancel
        busy={stop.isPending}
        onConfirm={() => stop.mutate()}
        onCancel={() => setOpen(false)}
      />
    </>
  );
}
