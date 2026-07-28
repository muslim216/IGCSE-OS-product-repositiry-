import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  createInvite,
  createParentCode,
  createStudentAccount,
  removeMember,
  resetStudentPassword,
} from "../../api/groups";
import { ApiError } from "../../api/client";
import { useGroupContext } from "../GroupLayout";
import { EmptyState, Modal } from "../../components/ui";

/**
 * Masked by default so a password isn't left on screen in a classroom, but
 * revealable — the tutor invents these and has to read them out to a student
 * who has no email, so typing one blind is worse than useless.
 */
function PasswordField({
  value,
  onChange,
  placeholder,
  autoFocus,
}: {
  value: string;
  onChange: (next: string) => void;
  placeholder: string;
  autoFocus?: boolean;
}) {
  const [visible, setVisible] = useState(false);
  return (
    <span className="relative inline-flex items-center">
      <input
        type={visible ? "text" : "password"}
        className="w-full rounded-md border border-line py-2 pl-3 pr-14 text-sm"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        minLength={8}
        required
        autoFocus={autoFocus}
      />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        className="absolute right-2 text-xs text-ink-400 hover:text-ink-700"
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
    <div className="mt-2 flex items-center gap-2 rounded-md bg-slate-50 p-2 text-sm">
      <span className="text-ink-500">{label}:</span>
      <code className="flex-1 truncate">{value}</code>
      <button
        className="rounded bg-slate-200 px-2 py-1 text-xs hover:bg-slate-300"
        onClick={() => {
          navigator.clipboard.writeText(value);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }}
      >
        {copied ? "Copied!" : "Copy"}
      </button>
    </div>
  );
}

export default function StudentsTab() {
  const { group, groupId } = useGroupContext();
  const queryClient = useQueryClient();
  // Every mutation here reports failure — a silent no-op reads as "it worked".
  const [actionError, setActionError] = useState<string | null>(null);
  const onError = (err: unknown) =>
    setActionError(err instanceof ApiError ? err.message : "Something went wrong. Try again.");

  const [inviteLink, setInviteLink] = useState<string | null>(null);
  const [parentCodes, setParentCodes] = useState<Record<number, string>>({});
  // Real dialogs instead of window.prompt/confirm.
  const [removing, setRemoving] = useState<{ id: number; name: string } | null>(null);
  const [resetting, setResetting] = useState<{ id: number; name: string } | null>(null);
  const [newPassword, setNewPassword] = useState("");

  const invite = useMutation({
    mutationFn: () => createInvite(groupId),
    onSuccess: (data) => setInviteLink(`${window.location.origin}/join/${data.code}`),
    onError,
  });

  const [studentForm, setStudentForm] = useState({ name: "", username: "", password: "" });
  const addStudent = useMutation({
    mutationFn: () => createStudentAccount(groupId, studentForm),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["group", groupId] });
      setStudentForm({ name: "", username: "", password: "" });
    },
    onError,
  });

  const remove = useMutation({
    mutationFn: (studentId: number) => removeMember(groupId, studentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["group", groupId] });
      setRemoving(null);
    },
    onError,
  });

  const parentCode = useMutation({
    mutationFn: (studentId: number) => createParentCode(studentId),
    onSuccess: (data, studentId) =>
      setParentCodes((prev) => ({
        ...prev,
        [studentId]: `${window.location.origin}/parent-join/${data.code}`,
      })),
    onError,
  });

  const resetPw = useMutation({
    mutationFn: ({ studentId, password }: { studentId: number; password: string }) =>
      resetStudentPassword(groupId, studentId, password),
    onSuccess: () => {
      setResetting(null);
      setNewPassword("");
    },
    onError,
  });

  function onAddStudent(e: FormEvent) {
    e.preventDefault();
    setActionError(null);
    addStudent.mutate();
  }

  return (
    <div>
      {actionError && <p className="mb-3 text-sm text-risk-600">{actionError}</p>}

      <div className="flex items-center justify-between">
        <h3 className="font-medium">Students ({group.members.length})</h3>
        <button
          onClick={() => invite.mutate()}
          className="rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium hover:bg-brand-700"
        >
          Generate invite link
        </button>
      </div>
      {inviteLink && <CopyBox label="Invite link" value={inviteLink} />}

      <ul className="mt-3 divide-y">
        {group.members.map((m) => (
          <li key={m.id} className="py-2">
            <div className="flex items-center justify-between gap-2">
              <div>
                <Link
                  to={`/tutor/students/${m.id}?group=${groupId}&subject=${group.subject.id}`}
                  className="font-medium text-blue-600 hover:underline"
                >
                  {m.name}
                </Link>{" "}
                <span className="text-sm text-ink-400">{m.email ?? `@${m.username}`}</span>
              </div>
              <div className="flex items-center gap-2 text-sm">
                <button
                  onClick={() => parentCode.mutate(m.id)}
                  className="text-blue-600 hover:underline"
                >
                  Parent link
                </button>
                {!m.email && (
                  <button
                    onClick={() => setResetting({ id: m.id, name: m.name })}
                    className="text-ink-500 hover:underline"
                  >
                    Reset password
                  </button>
                )}
                <button
                  onClick={() => setRemoving({ id: m.id, name: m.name })}
                  className="text-red-500 hover:underline"
                >
                  Remove
                </button>
              </div>
            </div>
            {parentCodes[m.id] && <CopyBox label="Parent link" value={parentCodes[m.id]} />}
          </li>
        ))}
      </ul>
      {group.members.length === 0 && (
        <EmptyState
          title="No students yet"
          hint="Share an invite link, or add an account below for a student without an email."
        />
      )}

      <form onSubmit={onAddStudent} className="mt-4 border-t border-line pt-4">
        <h4 className="text-sm font-medium text-ink-700">
          Add a student without an email (username account)
        </h4>
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <input
            className="rounded-md border border-line px-3 py-2 text-sm"
            placeholder="Student name"
            value={studentForm.name}
            onChange={(e) => setStudentForm({ ...studentForm, name: e.target.value })}
            required
          />
          <input
            className="rounded-md border border-line px-3 py-2 text-sm"
            placeholder="Username"
            value={studentForm.username}
            onChange={(e) => setStudentForm({ ...studentForm, username: e.target.value })}
            required
          />
          <PasswordField
            placeholder="Password (min 8 chars)"
            value={studentForm.password}
            onChange={(password) => setStudentForm({ ...studentForm, password })}
          />
          <button
            type="submit"
            disabled={addStudent.isPending}
            className="rounded-md bg-brand-600 px-3 py-2 text-sm font-medium hover:bg-brand-700 disabled:opacity-50"
          >
            Add student
          </button>
        </div>

      </form>

      <Modal
        open={removing !== null}
        onClose={() => setRemoving(null)}
        title={`Remove ${removing?.name ?? ""} from this class?`}
      >
        <p className="text-sm text-ink-500">
          They keep their account and their marked work, but lose access to this class's homework.
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <button
            onClick={() => setRemoving(null)}
            className="rounded-md border border-line px-3 py-1.5 text-sm hover:bg-slate-50"
          >
            Cancel
          </button>
          <button
            onClick={() => removing && remove.mutate(removing.id)}
            disabled={remove.isPending}
            className="rounded-md bg-red-600 px-3 py-1.5 text-sm font-medium disabled:opacity-50"
          >
            Remove
          </button>
        </div>
      </Modal>

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
          <PasswordField
            placeholder="At least 8 characters"
            value={newPassword}
            onChange={setNewPassword}
            autoFocus
          />
          <p className="mt-2 text-xs text-ink-400">
            Resetting signs the account out everywhere — share the new password with the student
            directly.
          </p>
          <div className="mt-4 flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setResetting(null)}
              className="rounded-md border border-line px-3 py-1.5 text-sm hover:bg-slate-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={resetPw.isPending}
              className="rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium hover:bg-brand-700 disabled:opacity-50"
            >
              Reset password
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
