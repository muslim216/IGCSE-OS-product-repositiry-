import { useEffect, useRef, useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { renameStudent } from "../api/students";
import { Button, Field, Input } from "../components/controls";
import { SectionCard, SectionHeader } from "../components/ui";
import { friendlyError } from "../lib/errors";

/** The tutor corrects how a student's name is spelled. It changes everywhere
 * the student is named, so the cached views are refetched. */
export default function RenameStudent({
  studentId,
  name,
}: Readonly<{ studentId: number; name: string }>) {
  const queryClient = useQueryClient();
  const [value, setValue] = useState(name);
  // A refetch that brings a new name in replaces the field only if the tutor
  // has not changed it from the name we last showed; otherwise their edit
  // (typed before or during a save) stands.
  const shown = useRef(name);
  useEffect(() => {
    setValue((v) => (v.trim() === shown.current || v.trim() === name ? name : v));
    shown.current = name;
  }, [name]);
  const save = useMutation({
    mutationFn: () => renameStudent(studentId, value.trim()),
    onSuccess: () => {
      return queryClient.invalidateQueries();
    },
  });
  const unchanged = value.trim() === name || value.trim() === "";

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!unchanged) save.mutate();
  }

  return (
    <SectionCard>
      <SectionHeader title="Name" description="How this student is named across Avora." />
      <form onSubmit={onSubmit} className="mt-4 flex max-w-sm flex-wrap items-end gap-3">
        <Field
          label="Student's name"
          className="min-w-0 flex-1"
          error={
            save.isError ? friendlyError(save.error, "Couldn't save that name. Try again.") : null
          }
        >
          <Input
            required
            value={value}
            maxLength={128}
            onChange={(e) => {
              setValue(e.target.value);
              save.reset();
            }}
          />
        </Field>
        <Button type="submit" variant="secondary" disabled={save.isPending || unchanged}>
          Save name
        </Button>
      </form>
      {/* Mounted empty and filled after success, so it is announced. */}
      <output className="mt-2 block text-sm text-ink-700">{save.isSuccess ? "Saved." : ""}</output>
    </SectionCard>
  );
}
