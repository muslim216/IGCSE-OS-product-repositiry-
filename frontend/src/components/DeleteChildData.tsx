import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { cancelErasure, getErasure, requestErasure } from "../api/erasure";
import type { ExportAsker } from "../api/dataExport";
import { ApiError } from "../api/client";
import { Button, Field, Input } from "./controls";
import { friendlyError } from "../lib/errors";
import { formatDayMonth } from "../lib/timezones";

/** `Button` styles only `disabled`; these buttons use `aria-disabled` to keep focus. */
const AWAITING = "aria-disabled:cursor-not-allowed aria-disabled:opacity-50";

/** Same rule as the server: Unicode-composed, case-folded, runs of whitespace
 *  collapsed. */
const normal = (s: string) => s.normalize("NFC").trim().replace(/\s+/g, " ").toLowerCase();

function errorText(err: unknown) {
  if (err instanceof ApiError && err.status === 422) return "That name doesn't match.";
  return "Couldn't do that right now. Try again.";
}

type FocusTarget = "input" | "notice" | "opener";

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

  // Where focus goes once the next render has put the element there: the panel
  // replaces the button, the notice replaces the panel, and so on, so without
  // this a keyboard user is dropped back at the top of the page each time.
  const want = useRef<FocusTarget | null>(null);
  const opener = useRef<HTMLButtonElement>(null);
  const form = useRef<HTMLFormElement>(null);
  const notice = useRef<HTMLParagraphElement>(null);
  // Set the moment a press is accepted, before React has re-rendered, so a
  // second press in the same tick cannot send a second request.
  const sending = useRef(false);
  const undoing = useRef(false);

  const pending = useQuery({ queryKey: key, queryFn: () => getErasure(asker, studentId) });

  useEffect(() => {
    const target = want.current;
    want.current = null;
    if (target === "input") form.current?.querySelector("input")?.focus();
    else if (target === "notice") notice.current?.focus();
    else if (target === "opener") opener.current?.focus();
  }, [confirming, pending.data]);

  const request = useMutation({
    mutationFn: () => requestErasure(asker, studentId, typed),
    onSuccess: (data) => {
      // The answer goes straight into the cache, so the notice appears in the
      // same render that closes the panel instead of after a refetch.
      qc.setQueryData(key, data);
      want.current = "notice";
      setConfirming(false);
      setTyped("");
      void qc.invalidateQueries({ queryKey: key });
    },
    onSettled: () => {
      sending.current = false;
    },
  });
  const undo = useMutation({
    mutationFn: () => cancelErasure(asker, studentId),
    onSuccess: () => {
      qc.setQueryData(key, null);
      want.current = "opener";
      void qc.invalidateQueries({ queryKey: key });
    },
    onSettled: () => {
      undoing.current = false;
    },
  });

  const error = request.error ?? undo.error ?? null;
  // Always mounted, so a message that arrives is announced.
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
        <p ref={notice} tabIndex={-1} role="status" className="text-sm text-ink-700">
          {name}&apos;s data will be deleted on {date}. They can&apos;t sign in until then.
        </p>
        <Button
          variant="secondary"
          className={`mt-2 ${AWAITING}`}
          aria-disabled={undo.isPending}
          onClick={() => {
            if (undo.isPending || undoing.current) return;
            undoing.current = true;
            request.reset();
            undo.mutate();
          }}
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
          ref={opener}
          variant="secondary"
          className="text-risk-600"
          onClick={() => {
            request.reset();
            undo.reset();
            want.current = "input";
            setConfirming(true);
          }}
        >
          {label}
        </Button>
        {alert}
      </div>
    );
  }

  // An empty name would be matched by an empty box: never.
  const matches = name.trim() !== "" && normal(typed) === normal(name);
  const awaiting = !matches || request.isPending;
  return (
    <form
      ref={form}
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (awaiting || sending.current) return;
        sending.current = true;
        request.mutate();
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
        <Button type="submit" variant="danger" className={AWAITING} aria-disabled={awaiting}>
          Delete
        </Button>
        <Button
          type="button"
          variant="ghost"
          onClick={() => {
            want.current = "opener";
            // A failed attempt's message would otherwise stay under the opener.
            request.reset();
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
