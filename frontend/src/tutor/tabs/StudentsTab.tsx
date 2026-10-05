import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link2 } from "lucide-react";
import {
  createInvite,
  createParentCode,
  createStudentAccount,
  removeMember,
  resetStudentPassword,
} from "../../api/groups";
import { useGroupContext } from "../GroupLayout";
import { EmptyState, InitialsAvatar, Modal, SectionCard } from "../../components/ui";
import { Button, Field, Input, inputClasses } from "../../components/controls";
import { ConfirmDialog } from "../../components/page";
import { friendlyError } from "../../lib/errors";

/**
 * Masked by default so a password isn't left on screen in a classroom, but
 * revealable — the tutor invents these and has to read them out to a student
 * who has no email, so typing one blind is worse than useless.
 */
function PasswordField({
  id,
  value,
  onChange,
  placeholder,
  autoFocus,
  "aria-describedby": describedBy,
}: {
  id?: string;
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
  autoFocus?: boolean;
  "aria-describedby"?: string;
}) {
  const [visible, setVisible] = useState(false);
  return (
    <span className="relative flex items-center">
      <input
        id={id}
        type={visible ? "text" : "password"}
        className={`${inputClasses} pr-16`}
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        minLength={8}
        required
        autoFocus={autoFocus}
        aria-describedby={describedBy}
      />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        className="absolute right-2 rounded px-2 py-1 text-xs font-medium text-ink-500 hover:text-ink-900"
        aria-pressed={visible}
      >
        {visible ? "Hide" : "Show"}
      </button>
    </span>
  );
}

function CopyBox({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="mt-3 flex items-center gap-3 rounded-md border border-line bg-surface-muted px-3 py-2 text-sm">
      <span className="shrink-0 text-ink-500">{label}</span>
      <code className="min-w-0 flex-1 truncate text-ink-900">{value}</code>
      <Button
        variant="secondary"
        size="sm"
        aria-label={`Copy ${label.toLowerCase()}`}
        onClick={() => {
          navigator.clipboard.writeText(value);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }}
      >
        {copied ? "Copied" : "Copy"}
      </Button>
    </div>
  );
}

export default function StudentsTab() {
  const { group, groupId } = useGroupContext();
  const queryClient = useQueryClient();
  // Every mutation here reports failure — a silent no-op reads as "it worked".
  const [actionError, setActionError] = useState<string | null>(null);
  const onError = (err: unknown) => setActionError(friendlyError(err));

  const [inviteLink, setInviteLink] = useState<string | null>(null);
  const [parentCodes, setParentCodes] = useState<Record<number, string>>({});
  // Real dialogs instead of window.prompt/confirm.
  const [removing, setRemoving] = useState<{ id: number; name: string } | null>(null);
  const [resetting, setResetting] = useState<{ id: number; name: string } | null>(null);
  const [newPassword, setNewPassword] = useState("");

  const invite = useMutation({
    mutationFn: () => createInvite(groupId),
    onSuccess: (data) => setInviteLink(`${window.location.origin}/join/${data.code}`),
    onMutate: () => setActionError(null),
    onError,
  });

  const [studentForm, setStudentForm] = useState({ name: "", username: "", password: "" });
  const addStudent = useMutation({
    mutationFn: () => createStudentAccount(groupId, studentForm),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["group", groupId] });
      // The cross-class Students and Homework lists count this class's members.
      queryClient.invalidateQueries({ queryKey: ["students"] });
      queryClient.invalidateQueries({ queryKey: ["homework"] });
      setStudentForm({ name: "", username: "", password: "" });
    },
    onMutate: () => setActionError(null),
    onError,
  });

  const remove = useMutation({
    mutationFn: (studentId: number) => removeMember(groupId, studentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["group", groupId] });
      // The cross-class Students and Homework lists count this class's members.
      queryClient.invalidateQueries({ queryKey: ["students"] });
      queryClient.invalidateQueries({ queryKey: ["homework"] });
      setRemoving(null);
    },
    onMutate: () => setActionError(null),
    onError,
  });

  const parentCode = useMutation({
    mutationFn: (studentId: number) => createParentCode(studentId),
    onSuccess: (data, studentId) =>
      setParentCodes((prev) => ({
        ...prev,
        [studentId]: `${window.location.origin}/parent-join/${data.code}`,
      })),
    onMutate: () => setActionError(null),
    onError,
  });

  const resetPw = useMutation({
    mutationFn: ({ studentId, password }: { studentId: number; password: string }) =>
      resetStudentPassword(groupId, studentId, password),
    onSuccess: () => {
      setResetting(null);
      setNewPassword("");
    },
    onMutate: () => setActionError(null),
    onError,
  });

  function onAddStudent(e: FormEvent) {
    e.preventDefault();
    addStudent.mutate();
  }

  const count = group.members.length;

  return (
    <div className="space-y-6">
      {actionError && (
        <p role="alert" className="rounded-md bg-risk-100 px-3 py-2 text-sm text-risk-600">
          {actionError}
        </p>
      )}

      <section>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg text-ink-900">Students</h2>
            <p className="text-sm text-ink-500">
              {count} {count === 1 ? "student" : "students"} in this class
            </p>
          </div>
          <Button size="sm" loading={invite.isPending} onClick={() => invite.mutate()}>
            <Link2 aria-hidden className="h-4 w-4" />
            Create invite link
          </Button>
        </div>
        {inviteLink && <CopyBox label="Invite link" value={inviteLink} />}

        {count === 0 ? (
          <SectionCard className="mt-4">
            <EmptyState
              title="No students yet"
              hint="Share an invite link, or add an account below for a student without an email."
            />
          </SectionCard>
        ) : (
          <ul className="mt-4 divide-y divide-line rounded-xl border border-line bg-surface">
            {group.members.map((m) => (
              <li key={m.id} className="px-4 py-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-3">
                    <InitialsAvatar name={m.name} />
                    <div className="min-w-0">
                      <Link
                        to={`/tutor/students/${m.id}?group=${groupId}&subject=${group.subject.id}`}
                        className="block truncate font-medium text-ink-900 hover:text-brand-600"
                      >
                        {m.name}
                      </Link>
                      <span className="block truncate text-sm text-ink-500">
                        {m.email ?? `@${m.username}`}
                      </span>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      loading={parentCode.isPending && parentCode.variables === m.id}
                      onClick={() => parentCode.mutate(m.id)}
                    >
                      Parent link
                    </Button>
                    {!m.email && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setResetting({ id: m.id, name: m.name })}
                      >
                        Reset password
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={`Remove ${m.name} from this class`}
                      onClick={() => setRemoving({ id: m.id, name: m.name })}
                    >
                      Remove
                    </Button>
                  </div>
                </div>
                {parentCodes[m.id] && <CopyBox label="Parent link" value={parentCodes[m.id]} />}
              </li>
            ))}
          </ul>
        )}
      </section>

      <SectionCard>
        <form onSubmit={onAddStudent}>
          <h3 className="font-medium text-ink-900">Add a student without an email</h3>
          <p className="mt-1 text-sm text-ink-500">
            They sign in with a username and a password you choose.
          </p>
          <div className="mt-4 grid gap-4 sm:grid-cols-3">
            <Field label="Student name">
              <Input
                value={studentForm.name}
                onChange={(e) => setStudentForm({ ...studentForm, name: e.target.value })}
                required
              />
            </Field>
            <Field label="Username">
              <Input
                value={studentForm.username}
                onChange={(e) => setStudentForm({ ...studentForm, username: e.target.value })}
                autoComplete="off"
                required
              />
            </Field>
            <Field label="Password" hint="At least 8 characters">
              <PasswordField
                value={studentForm.password}
                onChange={(password) => setStudentForm({ ...studentForm, password })}
              />
            </Field>
          </div>
          <div className="mt-4 flex justify-end">
            <Button type="submit" loading={addStudent.isPending}>
              Add student
            </Button>
          </div>
        </form>
      </SectionCard>

      <ConfirmDialog
        open={removing !== null}
        title={`Remove ${removing?.name ?? ""} from this class?`}
        body="They keep their account and their marked work, but lose access to this class's homework."
        confirmLabel="Remove from class"
        danger
        busy={remove.isPending}
        onConfirm={() => removing && remove.mutate(removing.id)}
        onCancel={() => setRemoving(null)}
      />

      <Modal
        open={resetting !== null}
        onClose={() => setResetting(null)}
        title={`New password for ${resetting?.name ?? ""}`}
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (resetting) resetPw.mutate({ studentId: resetting.id, password: newPassword });
          }}
        >
          <Field
            label="New password"
            hint="At least 8 characters. Resetting signs the account out everywhere — share the new password with the student directly."
          >
            <PasswordField value={newPassword} onChange={setNewPassword} autoFocus />
          </Field>
          <div className="mt-6 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setResetting(null)}>
              Cancel
            </Button>
            <Button type="submit" loading={resetPw.isPending}>
              Reset password
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
