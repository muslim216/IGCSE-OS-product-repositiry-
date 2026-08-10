import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { login } from "../api/auth";
import { ApiError } from "../api/client";
import { useAuth } from "./AuthContext";
import { homePathFor } from "./ProtectedRoute";
import { AvoraGrain, AvoraMark } from "../components/brand";

export default function LoginPage() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const auth = await login(identifier, password);
      signIn(auth);
      navigate(homePathFor(auth.user), { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4">
      <AvoraGrain />
      <div className="w-full max-w-md rounded-xl border border-line bg-surface p-8 shadow-[0_1px_2px_rgba(44,26,14,0.06)]">
        <div className="flex items-center gap-2.5">
          <AvoraMark className="h-9 w-9 text-brand-600" />
          <h1 className="font-display text-4xl lowercase tracking-[-0.02em] text-ink-900">avora</h1>
        </div>
        <p className="mt-3 text-sm text-ink-500">Sign in with your email or username.</p>
        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <div>
            <label htmlFor="identifier" className="block text-sm font-medium text-ink-700">
              Email or username
            </label>
            <input
              id="identifier"
              className="mt-1 w-full rounded-md border border-line-control px-3 py-2 focus:border-brand-600 focus:outline-none focus:ring-2 focus:ring-brand-100"
              value={identifier}
              onChange={(e) => setIdentifier(e.target.value)}
              autoComplete="username"
              required
            />
          </div>
          <div>
            <label htmlFor="password" className="block text-sm font-medium text-ink-700">
              Password
            </label>
            <input
              id="password"
              type="password"
              className="mt-1 w-full rounded-md border border-line-control px-3 py-2 focus:border-brand-600 focus:outline-none focus:ring-2 focus:ring-brand-100"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </div>
          {error && <p className="text-sm text-risk-600">{error}</p>}
          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-md bg-brand-600 py-2 font-medium text-canvas transition hover:bg-brand-700 disabled:opacity-50"
          >
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p className="mt-4 text-sm text-ink-500">
          Are you a tutor?{" "}
          <Link to="/signup" className="text-brand-600 hover:text-brand-700 hover:underline">
            Create a tutor account
          </Link>
        </p>
      </div>
    </div>
  );
}
