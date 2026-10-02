import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { joinWithInvite, previewInvite, registerParent } from "../api/groups";
import { useAuth } from "./AuthContext";
import { Button, Field, Input } from "../components/controls";
import { ErrorState, SectionSkeleton } from "../components/page";
import { friendlyError, inviteRefused } from "../lib/errors";
import { AuthAlt, AuthLayout, authLink } from "./AuthLayout";

export default function ParentJoinPage() {
  const { code = "" } = useParams();
  const { user, signIn } = useAuth();
  const navigate = useNavigate();
  const preview = useQuery({ queryKey: ["invite", code], queryFn: () => previewInvite(code) });

  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const [error, setError] = useState<string | null>(null);

  const link = useMutation({
    mutationFn: () => joinWithInvite(code),
    onSuccess: () => navigate("/parent", { replace: true }),
    onError: (err) => setError(friendlyError(err)),
  });

  const signup = useMutation({
    mutationFn: () => registerParent({ link_code: code, ...form }),
    onSuccess: (auth) => {
      signIn(auth);
      navigate("/parent", { replace: true });
    },
    onError: (err) => setError(friendlyError(err)),
  });

  if (preview.isLoading) {
    return (
      <AuthLayout documentTitle="Invitation" title="Checking your invitation…">
        <SectionSkeleton rows={3} label="Checking invitation" />
      </AuthLayout>
    );
  }
  if (preview.isError && !inviteRefused(preview.error)) {
    return (
      <AuthLayout documentTitle="Invitation" title="Parent invitation">
        <ErrorState
          title="We couldn't check this invitation."
          error={preview.error}
          onRetry={() => void preview.refetch()}
        />
      </AuthLayout>
    );
  }
  if (preview.isError || !preview.data || preview.data.kind !== "parent_link") {
    return (
      <AuthLayout
        documentTitle="Invitation not valid"
        title="This invitation isn't valid"
        subtitle="Parent links can be used once and expire. Ask the tutor for a new one."
        footer={
          <AuthAlt>
            Already have an account?{" "}
            <Link to="/login" className={authLink}>
              Sign in
            </Link>
          </AuthAlt>
        }
      >
        <span />
      </AuthLayout>
    );
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    signup.mutate();
  }

  return (
    <AuthLayout
      documentTitle="Parent access"
      title={`Follow ${preview.data.student_name}'s progress`}
      subtitle={"Create a parent account to see their progress, marked work and reports."}
    >
      {user?.role === "parent" ? (
        <div>
          <p className="text-sm text-ink-700">
            You're signed in as <span className="font-medium">{user.name}</span>.
          </p>
          <Button
            size="lg"
            className="mt-4 w-full"
            loading={link.isPending}
            onClick={() => link.mutate()}
          >
            Link this child to my account
          </Button>
        </div>
      ) : user ? (
        <p className="text-sm text-ink-700">
          You're signed in as a {user.role} account — only parent accounts can use this link.
        </p>
      ) : (
        <form onSubmit={onSubmit} className="space-y-5">
          <Field label="Your name">
            <Input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              autoComplete="name"
              required
            />
          </Field>
          <Field label="Email">
            <Input
              type="email"
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              autoComplete="email"
              required
            />
          </Field>
          <Field label="Password" hint="At least 8 characters.">
            <Input
              type="password"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              autoComplete="new-password"
              minLength={8}
              required
            />
          </Field>
          <Button type="submit" size="lg" loading={signup.isPending} className="w-full">
            Create parent account
          </Button>
          <p className="text-sm text-ink-500">
            Already have a parent account?{" "}
            <Link to="/login" className={authLink}>
              Sign in
            </Link>{" "}
            then open this link again.
          </p>
          <p className="text-xs leading-relaxed text-ink-500">
            You'll see only this child's record. Read our{" "}
            <Link to="/privacy" className="underline underline-offset-2 hover:text-ink-900">
              privacy policy
            </Link>
            .
          </p>
        </form>
      )}
      {error && (
        <p role="alert" className="mt-4 text-sm text-risk-600">
          {error}
        </p>
      )}
    </AuthLayout>
  );
}
