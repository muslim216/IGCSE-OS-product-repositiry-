import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { cancelErasure, getErasure, requestErasure } from "../api/erasure";
import type { ExportAsker } from "../api/dataExport";
import { ApiError } from "../api/client";
import { Button, Field, Input } from "./controls";
import { friendlyError } from "../lib/errors";
import { formatDayMonth } from "../lib/timezones";

/** Same rule as the server: case-folded, runs of whitespace collapsed. */
const normal = (s: string) => s.trim().replace(/\s+/g, " ").toLowerCase();

function errorText(err: unknown) {
  if (err instanceof ApiError && err.status === 422) return "That name doesn't match.";
  return "Couldn't do that right now. Try again.";
}

/** Starts, shows and undoes the erasure of a child's data. Nothing is deleted
 *  for 14 days, and the child cannot sign in meanwhile. A tutor, admin or linked
 *  parent may ask. Mount it with `key={studentId}`. */
export default function DeleteChildData({
  asker,
  studentId,
  name,
}: Readonly<{ asker: ExportAsker; studentId: number; name: string }>) {
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const [typed, setTyped] = useState("");
  const key = ["erasure", asker, studentId];

  const pending = useQuery({ queryKey: key, queryFn: () => getErasure(asker, studentId) });
  const done = () => {
    setConfirming(false);
    setTyped("");
    return qc.invalidateQueries({ queryKey: key });
  };
  const request = useMutation({
    mutationFn: () => requestErasure(asker, studentId, typed),
    onSuccess: done,
  });
  const undo = useMutation({ mutationFn: () => cancelErasure(asker, studentId), onSuccess: done });

  const error = request.error ?? undo.error ?? null;
  const alert = (
    <div aria-live="polite" className="mt-2 text-sm">
      {error && (
        <p role="alert" className="text-risk-600">
          {errorText(error)}
        </p>
      )}
    </div>
  );

  if (pending.isPending) return null;
  if (pending.isError) {
    return (
      <p role="alert" className="text-sm text-risk-600">
        {friendlyError(pending.error, "Couldn't check on that. Try again.")}
      </p>
    );
  }

  if (pending.data) {
    const date = formatDayMonth(new Date(pending.data.scheduled_for));
    return (
      <div>
        <p role="status" className="text-sm text-ink-700">
          {name}&apos;s data will be deleted on {date}. They can&apos;t sign in until then.
        </p>
        <Button
          variant="secondary"
          className="mt-2"
          disabled={undo.isPending}
          onClick={() => undo.mutate()}
        >
          Undo
        </Button>
        {alert}
      </div>
    );
  }

  const label = asker === "tutor" ? "Delete this student's data" : "Delete my child's data";
  if (!confirming) {
    return (
      <div>
        <Button
          variant="secondary"
          className="text-risk-600"
          onClick={() => {
            request.reset();
            setConfirming(true);
          }}
        >
          {label}
        </Button>
      </div>
    );
  }

  const matches = normal(typed) === normal(name);
  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (matches && !request.isPending) request.mutate();
      }}
    >
      <p className="text-sm text-ink-700">
        Everything Avora holds about {name} — work, marks, notes, reports — will be deleted in 14
        days. Until then they can&apos;t sign in, and you can undo this. After 14 days it can&apos;t
        be undone.
      </p>
      <Field label={`Type ${name} to confirm`}>
        <Input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />
      </Field>
      <div className="flex gap-3">
        <Button type="submit" variant="danger" disabled={!matches || request.isPending}>
          Delete
        </Button>
        <Button
          type="button"
          variant="ghost"
          onClick={() => {
            setConfirming(false);
            setTyped("");
          }}
        >
          Cancel
        </Button>
      </div>
      {alert}
    </form>
  );
}
