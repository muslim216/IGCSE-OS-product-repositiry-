import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { login } from "../api/auth";
import { ApiError } from "../api/client";
import { useAuth } from "./AuthContext";
import { homePathFor } from "./ProtectedRoute";

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
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-md rounded-xl bg-white p-8 shadow">
        <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-gold-600">
          by OASIS AI
        </p>
        <h1 className="mt-1 text-2xl font-semibold tracking-[0.06em] text-slate-800">MANARA</h1>
        <p className="mt-1 text-sm text-slate-500">Sign in with your email or username.</p>
        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-700">Email or username</label>
            <input
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 focus:border-blue-500 focus:outline-none"
              value={identifier}
              onChange={(e) => setIdentifier(e.target.value)}
              autoComplete="username"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700">Password</label>
            <input
              type="password"
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 focus:border-blue-500 focus:outline-none"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-md bg-blue-600 py-2 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p className="mt-4 text-sm text-slate-500">
          Are you a tutor?{" "}
          <Link to="/signup" className="text-blue-600 hover:underline">
            Create a tutor account
          </Link>
        </p>
      </div>
    </div>
  );
}
