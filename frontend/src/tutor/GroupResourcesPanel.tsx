import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createFileResource,
  createRecordingResource,
  deleteResource,
  isSafeHttpUrl,
  listResources,
  resourceFilePath,
  type Resource,
} from "../api/resources";
import { AuthFileLink } from "../components/AuthFile";
import { Button, Field, FileInput, Input, Select } from "../components/controls";
import { ConfirmDialog, ErrorState, SectionSkeleton } from "../components/page";
import { EmptyState, SectionCard, SectionHeader } from "../components/ui";
import { friendlyError } from "../lib/errors";

const KIND_LABEL: Record<Resource["kind"], string> = {
  file: "File",
  recording: "Recording",
};

/**
 * Keyed by class, so everything below starts over with each one. Moving from
 * one class's Resources tab to another's can keep this mounted — same route
 * element, and a class already in the cache never drops the layout to its
 * skeleton — and an open "Remove …?" dialog then carried over: confirming it
 * would delete a file from the class the tutor had just left.
 */
export function GroupResourcesPanel({ groupId }: { groupId: number }) {
  return <ResourcesPanel key={groupId} groupId={groupId} />;
}

function ResourcesPanel({ groupId }: { groupId: number }) {
  const queryClient = useQueryClient();
  const resources = useQuery({
    queryKey: ["resources", groupId],
    queryFn: () => listResources(groupId),
  });

  const [kind, setKind] = useState<"file" | "recording">("recording");
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  // Bumped after a successful add so the file picker remounts: clearing `file`
  // alone would leave the picker still naming the file just uploaded.
  const [pickerKey, setPickerKey] = useState(0);
  const [removing, setRemoving] = useState<Resource | null>(null);

  const create = useMutation({
    mutationFn: () =>
      kind === "recording"
        ? createRecordingResource(groupId, title, url)
        : createFileResource(groupId, title, file as File),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["resources", groupId] });
      // The Library lists the same rows across classes.
      queryClient.invalidateQueries({ queryKey: ["resources", "library"] });
      setTitle("");
      setUrl("");
      setFile(null);
      setPickerKey((k) => k + 1);
    },
  });

  const remove = useMutation({
    mutationFn: (id: number) => deleteResource(id),
    onSuccess: () => {
      setRemoving(null);
      queryClient.invalidateQueries({ queryKey: ["resources", groupId] });
      // The Library lists the same rows across classes.
      queryClient.invalidateQueries({ queryKey: ["resources", "library"] });
    },
  });

  // The file picker cannot carry `required` the way the old bare input did, so
  // the button stands in for the browser's own check.
  const ready = title.trim() !== "" && (kind === "recording" ? url.trim() !== "" : file !== null);

  return (
    <SectionCard>
      <SectionHeader
        title="Files and recordings"
        description="Shared with every student in this class."
      />

      <div className="mt-3">
        {resources.isLoading ? (
          <SectionSkeleton rows={3} label="Loading files and recordings" />
        ) : resources.isError ? (
          <ErrorState error={resources.error} onRetry={() => resources.refetch()} />
        ) : resources.data?.length === 0 ? (
          <EmptyState
            title="Nothing shared yet."
            hint="Add a lesson recording link or a file below."
          />
        ) : (
          <ul className="divide-y divide-line text-sm">
            {resources.data?.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center justify-between gap-3 py-2.5">
                <span className="flex min-w-0 items-center gap-2 text-ink-900">
                  <span className="shrink-0 rounded-md bg-surface-muted px-2 py-0.5 text-xs font-medium text-ink-700">
                    {KIND_LABEL[r.kind]}
                  </span>
                  <span className="truncate">{r.title}</span>
                </span>
                <span className="flex items-center gap-4">
                  {r.kind === "file" ? (
                    <AuthFileLink path={resourceFilePath(r.id)} label="Open" />
                  ) : (
                    isSafeHttpUrl(r.url) && (
                      <a
                        href={r.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-brand-600 hover:underline"
                      >
                        Watch
                      </a>
                    )
                  )}
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      remove.reset();
                      setRemoving(r);
                    }}
                  >
                    Remove<span className="sr-only"> {r.title}</span>
                  </Button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (ready) create.mutate();
        }}
        className="mt-4 space-y-3 border-t border-line pt-4"
      >
        <div className="grid gap-3 sm:grid-cols-[10rem_1fr]">
          <Field label="Type">
            <Select
              value={kind}
              onChange={(e) => {
                setKind(e.target.value as "file" | "recording");
                // The picker unmounts with the type and comes back empty, so a
                // file kept from before the switch would be invisible — yet Add
                // would still upload it.
                setFile(null);
              }}
            >
              <option value="recording">Recording link</option>
              <option value="file">File</option>
            </Select>
          </Field>
          <Field label="Title">
            <Input
              placeholder="e.g. Lesson 4 — Moles"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
            />
          </Field>
        </div>
        {kind === "recording" ? (
          <Field label="Link to the recording">
            <Input
              inputMode="url"
              placeholder="https://…"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              required
            />
          </Field>
        ) : (
          <Field label="File">
            <FileInput key={pickerKey} onFiles={(files) => setFile(files[0] ?? null)} />
          </Field>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={!ready} loading={create.isPending}>
            Add
          </Button>
          {create.isError && (
            <p role="alert" className="text-sm text-risk-600">
              {friendlyError(create.error, "That wasn't added. Try again.")}
            </p>
          )}
        </div>
      </form>

      <ConfirmDialog
        open={removing !== null}
        title={removing ? `Remove "${removing.title}"?` : "Remove"}
        body={
          <>
            <p>Students in this class will no longer see it. This can't be undone.</p>
            {remove.isError && (
              <p role="alert" className="mt-3 text-risk-600">
                {friendlyError(remove.error, "That wasn't removed. Try again.")}
              </p>
            )}
          </>
        }
        confirmLabel="Remove"
        danger
        busy={remove.isPending}
        onConfirm={() => removing && remove.mutate(removing.id)}
        onCancel={() => setRemoving(null)}
      />
    </SectionCard>
  );
}
