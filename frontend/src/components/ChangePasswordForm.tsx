import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { changePassword } from "../api/auth";
import { friendlyError } from "../lib/errors";
import { Button, Field, Input } from "./controls";
import { SectionCard, SectionHeader } from "./ui";

/**
 * Change your own password. Signs you out everywhere else and keeps this
 * session going (the server re-issues this session's token). Shown on every
 * role's account page; a username-only student has no email to reset by, so
 * this is their only way to choose their own.
 */
export default function ChangePasswordForm() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [mismatch, setMismatch] = useState(false);

  const save = useMutation({
    mutationFn: () => changePassword(current, next),
    onSuccess: () => {
      setCurrent("");
      setNext("");
      setConfirm("");
    },
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (next !== confirm) {
      setMismatch(true);
      return;
    }
    setMismatch(false);
    save.mutate();
  }

  return (
    <SectionCard>
      <SectionHeader
        title="Change password"
        description="You'll stay signed in here. Any other device or browser will be signed out."
      />
      <form onSubmit={onSubmit} className="mt-4 max-w-sm space-y-4">
        <Field label="Current password">
          <Input
            type="password"
            autoComplete="current-password"
            required
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
          />
        </Field>
        <Field label="New password" hint="At least 8 characters.">
          <Input
            type="password"
            autoComplete="new-password"
            required
            minLength={8}
            value={next}
            onChange={(e) => setNext(e.target.value)}
          />
        </Field>
        <Field
          label="Confirm new password"
          error={mismatch ? "The two passwords don't match." : null}
        >
          <Input
            type="password"
            autoComplete="new-password"
            required
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
          />
        </Field>
        {save.isError && (
          <p role="alert" className="text-sm text-risk-600">
            {friendlyError(save.error, "Couldn't change your password. Try again.")}
          </p>
        )}
        {save.isSuccess && (
          <p role="status" className="text-sm text-ink-700">
            Password changed. Other devices have been signed out.
          </p>
        )}
        <Button type="submit" disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Change password"}
        </Button>
      </form>
    </SectionCard>
  );
}
