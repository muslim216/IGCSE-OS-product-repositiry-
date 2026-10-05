import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText } from "lucide-react";
import { listSubjects } from "../api/groups";
import {
  deleteTeachingGuidance,
  getTeachingGuidance,
  teachingGuidanceFilePath,
  uploadTeachingGuidance,
} from "../api/teachingGuidance";
import { AuthFileLink } from "../components/AuthFile";
import { Button, Field, FileInput, Select } from "../components/controls";
import { ConfirmDialog, ErrorState, PageHeader, SectionSkeleton } from "../components/page";
import { EmptyState, SectionCard, useToast } from "../components/ui";
import { friendlyError } from "../lib/errors";
import SetupState from "./SetupState";
import { useSubjectSetup } from "./SubjectSetupContext";

/**
 * Teaching guidance — the scheme of work, the second document a subject is set
 * up with beside its syllabus (`AV-10`, onboarding step 4).
 *
 * One document per subject: uploading again replaces it, which is why there is
 * a Replace control and no list. Nothing reads it yet — Phase 6's plan is what
 * uses it to judge which chapters are harder or slower (`AV-14`) — so this page
 * says what it is for rather than implying an effect it does not yet have
 * (`PROD-1`).
 */
export default function TeachingGuidancePage() {
  const queryClient = useQueryClient();
  const { toast, showToast } = useToast();
  const subjects = useQuery({ queryKey: ["subjects"], queryFn: listSubjects });
  // Inside Subject setup the page-level picker owns the subject (see
  // SubjectSetupContext); standing alone the page keeps its own.
  const setup = useSubjectSetup();
  const [subjectId, setSubjectId] = useState<number | null>(null);
  const selected = setup ? setup.subjectId : (subjectId ?? subjects.data?.[0]?.id ?? null);

  const guidance = useQuery({
    queryKey: ["teaching-guidance", selected],
    queryFn: () => getTeachingGuidance(selected!),
    enabled: selected !== null,
  });

  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmingRemove, setConfirmingRemove] = useState(false);

  const upload = useMutation({
    mutationFn: () => uploadTeachingGuidance(selected!, file!),
    onMutate: () => setError(null),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["teaching-guidance", selected] });
      queryClient.invalidateQueries({ queryKey: ["onboarding"] });
      setFile(null);
      showToast("Teaching guidance saved.");
    },
    onError: (err) => setError(friendlyError(err, "That didn't upload. Try again.")),
  });

  const remove = useMutation({
    mutationFn: () => deleteTeachingGuidance(selected!),
    onMutate: () => setError(null),
    onSuccess: () => {
      setConfirmingRemove(false);
      queryClient.invalidateQueries({ queryKey: ["teaching-guidance", selected] });
      queryClient.invalidateQueries({ queryKey: ["onboarding"] });
      // The input is remounted by its key, but the file behind it would survive
      // — an empty-looking form that uploads on the next click (cubic).
      setFile(null);
      showToast("Teaching guidance removed.");
    },
    // Its failure is shown in the confirmation dialog, which stays open.
  });

  // Replace and Remove write the same one document, so letting both run leaves
  // the result to whichever commits last (cubic). One at a time.
  const busy = upload.isPending || remove.isPending;

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (file && selected !== null) upload.mutate();
  }

  const header = (
    <PageHeader
      title="Teaching guidance"
      meta={<SetupState item="teaching_guidance" />}
      description="Your scheme of work for a subject — the order you teach it in and how long each chapter takes. It's kept beside the syllabus, ready for the teaching plan to use when that arrives; nothing reads it yet. One document per subject: uploading again replaces it."
      back={{ to: "/tutor/subject-setup", label: "Subject setup" }}
    />
  );

  if (subjects.isLoading) {
    return (
      <div>
        {header}
        <SectionSkeleton rows={4} label="Loading your subjects" />
      </div>
    );
  }
  // "Could not load" and "you have none" are different facts and must not
  // render alike (PROD-2) — the first is a retry, the second is a next step.
  if (subjects.isError || !subjects.data) {
    return (
      <div>
        {header}
        <ErrorState error={subjects.error} onRetry={() => subjects.refetch()} />
      </div>
    );
  }
  if (subjects.data.length === 0) {
    return (
      <div>
        {header}
        <SectionCard>
          <EmptyState
            title="No subjects yet."
            hint="Teaching guidance is kept per subject — add a syllabus first."
          />
        </SectionCard>
      </div>
    );
  }

  return (
    <div className="max-w-3xl">
      {header}

      <div className="space-y-6">
        {!setup && (
          <Field label="Subject" className="max-w-sm">
            <Select
              // Locked while a write is in flight: the mutation captured the subject
              // it started on, so switching underneath it refreshes the wrong one and
              // clears a selection the tutor has just made (cubic).
              disabled={busy}
              value={selected ?? ""}
              onChange={(e) => {
                // A file chosen for Chemistry must not be uploaded to Biology: the
                // form posts `selected`, which has just changed (cubic, CodeRabbit).
                // The input itself is remounted by the key below.
                setFile(null);
                setError(null);
                setSubjectId(Number(e.target.value));
              }}
            >
              {subjects.data.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} ({s.exam_board} {s.code})
                </option>
              ))}
            </Select>
          </Field>
        )}

        {guidance.isLoading ? (
          <SectionCard>
            <SectionSkeleton rows={3} label="Loading teaching guidance" />
          </SectionCard>
        ) : guidance.isError || !guidance.data ? (
          <ErrorState error={guidance.error} onRetry={() => guidance.refetch()} />
        ) : (
          <SectionCard>
            {guidance.data.uploaded ? (
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-brand-50 text-brand-600">
                  <FileText aria-hidden className="h-5 w-5" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-ink-900">
                    {guidance.data.file_name}
                  </p>
                  {guidance.data.uploaded_at && (
                    <p className="text-xs text-ink-500">
                      Uploaded{" "}
                      {new Date(guidance.data.uploaded_at).toLocaleDateString(undefined, {
                        day: "numeric",
                        month: "short",
                        year: "numeric",
                      })}
                    </p>
                  )}
                </div>
                <span className="flex items-center gap-2 text-sm">
                  <AuthFileLink path={teachingGuidanceFilePath(selected!)} label="Open" />
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() => {
                      remove.reset();
                      setConfirmingRemove(true);
                    }}
                  >
                    Remove
                  </Button>
                </span>
              </div>
            ) : (
              // Absent is stated, never drawn as an empty row (PROD-2, UX-19).
              <p className="text-sm text-ink-500">No teaching guidance for this subject yet.</p>
            )}

            <form onSubmit={onSubmit} className="mt-5 space-y-3 border-t border-line pt-5">
              <Field
                label={guidance.data.uploaded ? "Replace it" : "Upload a document"}
                hint="A PDF or a photo of your scheme of work."
              >
                <FileInput
                  // Remounted on a subject change and after a successful upload,
                  // which is what clears the picker's own filename display —
                  // resetting React state alone leaves it reading the old file.
                  key={`${selected}-${guidance.data.uploaded_at ?? "none"}`}
                  disabled={busy}
                  accept="application/pdf,image/*"
                  prompt="Choose a document"
                  onFiles={(files) => setFile(files[0] ?? null)}
                />
              </Field>
              <Button type="submit" disabled={!file || remove.isPending} loading={upload.isPending}>
                {guidance.data.uploaded ? "Replace" : "Upload"}
              </Button>
            </form>
            {error && (
              <p role="alert" className="mt-3 text-sm text-risk-600">
                {error}
              </p>
            )}
          </SectionCard>
        )}
      </div>

      <ConfirmDialog
        open={confirmingRemove}
        title="Remove this teaching guidance?"
        body={
          <>
            <p>
              <span className="font-medium text-ink-900">{guidance.data?.file_name}</span> will be
              deleted for {guidance.data?.subject_name ?? "this subject"}. You can upload it again
              later.
            </p>
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
        onConfirm={() => remove.mutate()}
        onCancel={() => setConfirmingRemove(false)}
      />
      {toast}
    </div>
  );
}
