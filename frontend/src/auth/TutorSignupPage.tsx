import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { registerTutor } from "../api/auth";
import { ApiError } from "../api/client";
import { useAuth } from "./AuthContext";
import { AvoraGrain, AvoraLockup } from "../components/brand";

export default function TutorSignupPage() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const auth = await registerTutor(name, email, password);
      signIn(auth);
      navigate("/tutor", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4">
      <AvoraGrain />
      <div className="w-full max-w-md rounded-xl bg-surface p-8 shadow-[0_1px_2px_rgba(44,26,14,0.06)]">
        <AvoraLockup className="mb-6" />
        <h1 className="text-2xl font-semibold text-ink-900">Create a tutor account</h1>
        <p className="mt-1 text-sm text-ink-500">
          Manage your students, homework and results in one place.
        </p>
        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-ink-700">Full name</label>
            <input
              className="mt-1 w-full rounded-md border border-line-control px-3 py-2 focus:border-brand-600"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-ink-700">Email</label>
            <input
              type="email"
              className="mt-1 w-full rounded-md border border-line-control px-3 py-2 focus:border-brand-600"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-ink-700">
              Password <span className="text-ink-500">(at least 8 characters)</span>
            </label>
            <input
              type="password"
              className="mt-1 w-full rounded-md border border-line-control px-3 py-2 focus:border-brand-600"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              minLength={8}
              required
            />
          </div>
          {error && <p className="text-sm text-risk-600">{error}</p>}
          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-md bg-brand-600 py-2 font-medium text-canvas hover:bg-brand-700 disabled:opacity-50"
          >
            {busy ? "Creating account…" : "Create account"}
          </button>
        </form>
        <p className="mt-4 text-sm text-ink-500">
          Already have an account?{" "}
          <Link to="/login" className="text-brand-600 hover:text-brand-700 hover:underline">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
