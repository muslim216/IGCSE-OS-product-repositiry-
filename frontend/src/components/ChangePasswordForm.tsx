import { useRef, useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { changePassword } from "../api/auth";
import { ApiError } from "../api/client";
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
  const [visible, setVisible] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const focusField = (name: string) =>
    (formRef.current?.elements.namedItem(name) as HTMLInputElement | null)?.focus();

  const save = useMutation({
    mutationFn: () => changePassword(current, next),
    onSuccess: () => {
      setCurrent("");
      setNext("");
      setConfirm("");
    },
    // A wrong current password is the one failure the person can fix at once;
    // put them on the field instead of leaving them to find it.
    onError: (err) => {
      if (err instanceof ApiError && err.status === 400) focusField("current");
    },
  });

  // Typing starts a fresh attempt, so the last attempt's message goes.
  const edited = (set: (v: string) => void) => (e: { target: { value: string } }) => {
    set(e.target.value);
    if (save.isError || save.isSuccess) save.reset();
  };

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (next !== confirm) {
      setMismatch(true);
      focusField("confirm");
      return;
    }
    setMismatch(false);
    save.reset();
    save.mutate();
  }

  return (
    <SectionCard>
      <SectionHeader
        title="Change password"
        description="You'll stay signed in here. Any other device or browser will be signed out."
      />
      <form ref={formRef} onSubmit={onSubmit} className="mt-4 max-w-sm space-y-4">
        <Field label="Current password">
          <Input
            type={visible ? "text" : "password"}
            name="current"
            autoComplete="current-password"
            required
            value={current}
            onChange={edited(setCurrent)}
          />
        </Field>
        <Field label="New password" hint="At least 8 characters.">
          <Input
            type={visible ? "text" : "password"}
            name="new"
            autoComplete="new-password"
            required
            minLength={8}
            value={next}
            onChange={edited(setNext)}
          />
        </Field>
        <Field
          label="Confirm new password"
          error={mismatch ? "The two passwords don't match." : null}
        >
          <Input
            type={visible ? "text" : "password"}
            name="confirm"
            autoComplete="new-password"
            required
            value={confirm}
            onChange={(e) => {
              edited(setConfirm)(e);
              setMismatch(false);
            }}
          />
        </Field>
        <button
          type="button"
          onClick={() => setVisible((v) => !v)}
          aria-pressed={visible}
          className="rounded px-2 py-1 text-xs font-medium text-ink-500 hover:text-ink-900"
        >
          {visible ? "Hide passwords" : "Show passwords"}
        </button>
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
