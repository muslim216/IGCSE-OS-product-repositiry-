import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { User } from "../../api/client";
import {
  createInvite,
  createParentCode,
  createStudentAccount,
  removeMember,
  resetStudentPassword,
} from "../../api/groups";
import { useGroupContext } from "../GroupLayout";
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  ConfirmDialog,
  Dialog,
  EmptyState,
  Field,
  Input,
} from "../../ui";

function CopyBox({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="mt-2 flex items-center gap-2 rounded-control bg-surface-muted p-2 text-sm">
      <span className="shrink-0 text-slate-500">{label}:</span>
      <code className="min-w-0 flex-1 truncate">{value}</code>
      <Button
        size="sm"
        variant="secondary"
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
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["group", groupId] });
    queryClient.invalidateQueries({ queryKey: ["groups"] });
  };

  const [inviteLink, setInviteLink] = useState<string | null>(null);
  const [parentCodes, setParentCodes] = useState<Record<number, string>>({});
  const [removing, setRemoving] = useState<User | null>(null);
  const [resetting, setResetting] = useState<User | null>(null);
  const [newPassword, setNewPassword] = useState("");
  const [studentForm, setStudentForm] = useState({ name: "", username: "", password: "" });

  const invite = useMutation({
    mutationFn: () => createInvite(groupId),
    onSuccess: (data) => setInviteLink(`${window.location.origin}/join/${data.code}`),
  });

  const addStudent = useMutation({
    mutationFn: () => createStudentAccount(groupId, studentForm),
    onSuccess: () => {
      refresh();
      setStudentForm({ name: "", username: "", password: "" });
    },
  });

  const remove = useMutation({
    mutationFn: (studentId: number) => removeMember(groupId, studentId),
    onSuccess: () => {
      refresh();
      setRemoving(null);
    },
  });

  const parentCode = useMutation({
    mutationFn: (studentId: number) => createParentCode(studentId),
    onSuccess: (data, studentId) =>
      setParentCodes((prev) => ({
        ...prev,
        [studentId]: `${window.location.origin}/parent-join/${data.code}`,
      })),
  });

  const resetPw = useMutation({
    mutationFn: ({ studentId, password }: { studentId: number; password: string }) =>
      resetStudentPassword(groupId, studentId, password),
    onSuccess: () => {
      setResetting(null);
      setNewPassword("");
    },
  });

  function onAddStudent(e: FormEvent) {
    e.preventDefault();
    addStudent.mutate();
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
      <div>
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-slate-900">
            Students ({group.members.length})
          </h3>
          <Button variant="secondary" onClick={() => invite.mutate()}>
            Generate invite link
          </Button>
        </div>
        {inviteLink && <CopyBox label="Invite link" value={inviteLink} />}

        {group.members.length === 0 ? (
          <EmptyState
            className="mt-4"
            icon="🧑‍🎓"
            title="No students yet"
            description="Share an invite link with students who have an email address, or create a username-only account for those who don't."
            action={{ label: "Generate invite link", onClick: () => invite.mutate() }}
          />
        ) : (
          <Card className="mt-4">
            <ul className="divide-y divide-slate-100">
              {group.members.map((m) => (
                <li key={m.id} className="px-5 py-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="min-w-0">
                      <Link
                        to={`/tutor/groups/${groupId}/students/${m.id}`}
                        className="font-medium text-brand-700 hover:underline"
                      >
                        {m.name}
                      </Link>
                      <span className="ml-2 text-sm text-slate-400">
                        {m.email ?? `@${m.username}`}
                      </span>
                    </div>
                    <div className="flex items-center gap-1">
                      <Button size="sm" variant="ghost" onClick={() => parentCode.mutate(m.id)}>
                        Parent link
                      </Button>
                      {!m.email && (
                        <Button size="sm" variant="ghost" onClick={() => setResetting(m)}>
                          Reset password
                        </Button>
                      )}
                      <Button size="sm" variant="ghost" onClick={() => setRemoving(m)}>
                        Remove
                      </Button>
                    </div>
                  </div>
                  {parentCodes[m.id] && <CopyBox label="Parent link" value={parentCodes[m.id]} />}
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>

      <Card className="h-fit">
        <CardHeader
          title="Add a student"
          description="For students without an email address."
        />
        <CardBody>
          <form onSubmit={onAddStudent} className="space-y-3">
            <Field label="Name">
              {(props) => (
                <Input
                  {...props}
                  value={studentForm.name}
                  onChange={(e) => setStudentForm({ ...studentForm, name: e.target.value })}
                  required
                />
              )}
            </Field>
            <Field label="Username">
              {(props) => (
                <Input
                  {...props}
                  value={studentForm.username}
                  onChange={(e) => setStudentForm({ ...studentForm, username: e.target.value })}
                  required
                />
              )}
            </Field>
            <Field label="Password" hint="At least 8 characters.">
              {(props) => (
                <Input
                  {...props}
                  value={studentForm.password}
                  onChange={(e) => setStudentForm({ ...studentForm, password: e.target.value })}
                  minLength={8}
                  required
                />
              )}
            </Field>
            <Button type="submit" disabled={addStudent.isPending} className="w-full">
              {addStudent.isPending ? "Adding…" : "Add student"}
            </Button>
            {addStudent.isError && (
              <p className="text-sm text-risk-600">
                Could not create the account — is the username already taken?
              </p>
            )}
          </form>
        </CardBody>
      </Card>

      <ConfirmDialog
        open={removing !== null}
        onClose={() => setRemoving(null)}
        onConfirm={() => removing && remove.mutate(removing.id)}
        title={`Remove ${removing?.name ?? "student"}?`}
        description="They lose access to this class's homework. Their account and past work are kept."
        confirmLabel="Remove"
        pending={remove.isPending}
      />

      <Dialog
        open={resetting !== null}
        onClose={() => setResetting(null)}
        title={`Reset password for ${resetting?.name ?? "student"}`}
        description="They'll sign in with this new password from now on."
        footer={
          <>
            <Button variant="secondary" onClick={() => setResetting(null)}>
              Cancel
            </Button>
            <Button
              disabled={newPassword.length < 8 || resetPw.isPending}
              onClick={() =>
                resetting && resetPw.mutate({ studentId: resetting.id, password: newPassword })
              }
            >
              {resetPw.isPending ? "Saving…" : "Set password"}
            </Button>
          </>
        }
      >
        <Field label="New password" hint="At least 8 characters.">
          {(props) => (
            <Input
              {...props}
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              minLength={8}
              autoFocus
            />
          )}
        </Field>
      </Dialog>
    </div>
  );
}
