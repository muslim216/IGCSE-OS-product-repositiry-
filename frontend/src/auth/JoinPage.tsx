import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { joinWithInvite, previewInvite, registerStudent } from "../api/groups";
import { useAuth } from "./AuthContext";
import { Button, Field, Input } from "../components/controls";
import { ErrorState, SectionSkeleton } from "../components/page";
import { friendlyError, inviteRefused } from "../lib/errors";
import { AuthAlt, AuthLayout, authLink } from "./AuthLayout";

export default function JoinPage() {
  const { code = "" } = useParams();
  const { user, signIn } = useAuth();
  const navigate = useNavigate();
  const preview = useQuery({ queryKey: ["invite", code], queryFn: () => previewInvite(code) });

  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const [error, setError] = useState<string | null>(null);

  const join = useMutation({
    mutationFn: () => joinWithInvite(code),
    onSuccess: () => navigate("/student", { replace: true }),
    onError: (err) => setError(friendlyError(err)),
  });

  const signup = useMutation({
    mutationFn: () => registerStudent({ invite_code: code, ...form }),
    onSuccess: (auth) => {
      signIn(auth);
      // A brand-new account goes through the orientation screen first: it is the
      // one moment a student can be told what the assistant will and will not do
      // before they meet the boundary as a refusal (UX-26, §5.4). Joining a
      // second class from an existing account skips it — they have read it.
      navigate("/student/welcome", { replace: true });
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
  // A failure that says nothing about the link is offered a retry, not told
  // the invitation is invalid (see inviteRefused).
  if (preview.isError && !inviteRefused(preview.error)) {
    return (
      <AuthLayout documentTitle="Invitation" title="Join a class">
        <ErrorState
          title="We couldn't check this invitation."
          error={preview.error}
          onRetry={() => void preview.refetch()}
        />
      </AuthLayout>
    );
  }
  if (preview.isError || !preview.data || preview.data.kind !== "student_join") {
    return (
      <AuthLayout
        documentTitle="Invitation not valid"
        title="This invitation isn't valid"
        subtitle="Invitation links expire. Ask your tutor for a new one."
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
      documentTitle="Join a class"
      title={`Join ${preview.data.group_name}`}
      subtitle={`${preview.data.subject_name} with ${preview.data.tutor_name}`}
    >
      {user?.role === "student" ? (
        <div>
          <p className="text-sm text-ink-700">
            You're signed in as <span className="font-medium">{user.name}</span>.
          </p>
          <Button
            size="lg"
            className="mt-4 w-full"
            loading={join.isPending}
            onClick={() => join.mutate()}
          >
            Join this class
          </Button>
        </div>
      ) : user ? (
        <p className="text-sm text-ink-700">
          You're signed in as a {user.role} account — only students can join a class. Sign out first
          if this link is for a student.
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
            Create account & join
          </Button>
          <p className="text-sm text-ink-500">
            Already have an account?{" "}
            <Link to="/login" className={authLink}>
              Sign in
            </Link>{" "}
            then open this link again. No email? Ask your tutor to create a username for you.
          </p>
          <p className="text-xs leading-relaxed text-ink-500">
            Your tutor sees the work you hand in, and a parent linked to your account sees your
            progress. Read our{" "}
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
