import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { joinWithInvite, previewInvite, registerParent } from "../api/groups";
import { ApiError } from "../api/client";
import { InviteProblem } from "./InviteProblem";
import { useAuth } from "./AuthContext";

export default function ParentJoinPage() {
  const { code = "" } = useParams();
  const { user, signIn } = useAuth();
  const navigate = useNavigate();
  const preview = useQuery({
    queryKey: ["invite", code],
    queryFn: () => previewInvite(code),
    // A bad or expired code is a definite answer, not a blip — retrying just
    // leaves the visitor staring at "Loading…" before the explanation appears.
    retry: false,
  });

  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const [error, setError] = useState<string | null>(null);

  const link = useMutation({
    mutationFn: () => joinWithInvite(code),
    onSuccess: () => navigate("/parent", { replace: true }),
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : "Could not link — try again."),
  });

  const signup = useMutation({
    mutationFn: () => registerParent({ link_code: code, ...form }),
    onSuccess: (auth) => {
      signIn(auth);
      navigate("/parent", { replace: true });
    },
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : "Could not sign up — try again."),
  });

  if (preview.isLoading) {
    return <div className="flex h-screen items-center justify-center text-slate-500">Loading…</div>;
  }
  if (preview.isError || !preview.data || preview.data.kind !== "parent_link") {
    return (
      <InviteProblem
        title="This parent link isn't valid"
        detail="It may have expired, or been copied incompletely. Ask your child's tutor to send you a fresh link."
      />
    );
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    signup.mutate();
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-md rounded-xl bg-white p-8 shadow">
        <h1 className="text-xl font-semibold text-slate-800">
          Follow {preview.data.student_name}'s progress
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          Create a parent account to see readiness, progress and reports.
        </p>

        {user?.role === "parent" ? (
          <div className="mt-6">
            <p className="text-sm text-slate-600">
              You're signed in as <span className="font-medium">{user.name}</span>.
            </p>
            <button
              onClick={() => link.mutate()}
              disabled={link.isPending}
              className="mt-3 w-full rounded-md bg-blue-600 py-2 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              Link this child to my account
            </button>
          </div>
        ) : user ? (
          <p className="mt-6 text-sm text-slate-600">
            You're signed in as a {user.role} account — only parent accounts can use this link.
          </p>
        ) : (
          <form onSubmit={onSubmit} className="mt-6 space-y-4">
            <input
              className="w-full rounded-md border border-slate-300 px-3 py-2"
              placeholder="Your name"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              required
            />
            <input
              type="email"
              className="w-full rounded-md border border-slate-300 px-3 py-2"
              placeholder="Email"
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              required
            />
            <input
              type="password"
              className="w-full rounded-md border border-slate-300 px-3 py-2"
              placeholder="Password (min 8 characters)"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              minLength={8}
              required
            />
            <button
              type="submit"
              disabled={signup.isPending}
              className="w-full rounded-md bg-blue-600 py-2 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              Create parent account
            </button>
            <p className="text-sm text-slate-500">
              Already have a parent account?{" "}
              <Link to="/login" className="text-blue-600 hover:underline">
                Sign in
              </Link>{" "}
              then open this link again.
            </p>
          </form>
        )}
        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      </div>
    </div>
  );
}
