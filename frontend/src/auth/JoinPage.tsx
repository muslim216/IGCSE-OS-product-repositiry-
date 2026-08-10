import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { joinWithInvite, previewInvite, registerStudent } from "../api/groups";
import { ApiError } from "../api/client";
import { useAuth } from "./AuthContext";
import { AvoraGrain, AvoraLockup } from "../components/brand";

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
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : "Could not join — try again."),
  });

  const signup = useMutation({
    mutationFn: () => registerStudent({ invite_code: code, ...form }),
    onSuccess: (auth) => {
      signIn(auth);
      navigate("/student", { replace: true });
    },
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : "Could not sign up — try again."),
  });

  if (preview.isLoading) {
    return <div className="flex h-screen items-center justify-center text-ink-500">Loading…</div>;
  }
  if (preview.isError || !preview.data || preview.data.kind !== "student_join") {
    return (
      <div className="flex h-screen items-center justify-center text-ink-700">
        This invite link is not valid. Ask your tutor for a new one.
      </div>
    );
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    signup.mutate();
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4">
      <AvoraGrain />
      <div className="w-full max-w-md rounded-xl bg-surface p-8 shadow-[0_1px_2px_rgba(44,26,14,0.06)]">
        <AvoraLockup className="mb-6" />
        <h1 className="text-xl font-semibold text-ink-900">Join {preview.data.group_name}</h1>
        <p className="mt-1 text-sm text-ink-500">
          {preview.data.subject_name} with {preview.data.tutor_name}
        </p>

        {user?.role === "student" ? (
          <div className="mt-6">
            <p className="text-sm text-ink-700">
              You're signed in as <span className="font-medium">{user.name}</span>.
            </p>
            <button
              onClick={() => join.mutate()}
              disabled={join.isPending}
              className="mt-3 w-full rounded-md bg-brand-600 py-2 font-medium text-canvas hover:bg-brand-700 disabled:opacity-50"
            >
              Join this group
            </button>
          </div>
        ) : user ? (
          <p className="mt-6 text-sm text-ink-700">
            You're signed in as a {user.role} account — only students can join a group. Sign out
            first if this link is for a student.
          </p>
        ) : (
          <form onSubmit={onSubmit} className="mt-6 space-y-4">
            <input
              className="w-full rounded-md border border-line-control px-3 py-2"
              placeholder="Your name"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              required
            />
            <input
              type="email"
              className="w-full rounded-md border border-line-control px-3 py-2"
              placeholder="Email"
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              required
            />
            <input
              type="password"
              className="w-full rounded-md border border-line-control px-3 py-2"
              placeholder="Password (min 8 characters)"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              minLength={8}
              required
            />
            <button
              type="submit"
              disabled={signup.isPending}
              className="w-full rounded-md bg-brand-600 py-2 font-medium text-canvas hover:bg-brand-700 disabled:opacity-50"
            >
              Create account & join
            </button>
            <p className="text-sm text-ink-500">
              Already have an account?{" "}
              <Link to="/login" className="text-brand-600 hover:text-brand-700 hover:underline">
                Sign in
              </Link>{" "}
              then open this link again. No email? Ask your tutor to create a username for you.
            </p>
          </form>
        )}
        {error && <p className="mt-3 text-sm text-risk-600">{error}</p>}
      </div>
    </div>
  );
}
