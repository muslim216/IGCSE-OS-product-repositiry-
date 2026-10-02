import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { login } from "../api/auth";
import { useAuth } from "./AuthContext";
import { homePathFor } from "./ProtectedRoute";
import { Button, Field, Input } from "../components/controls";
import { friendlyError } from "../lib/errors";
import { AuthAlt, AuthLayout, authLink } from "./AuthLayout";

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
      setError(friendlyError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout
      documentTitle="Sign in"
      title={
        <>
          Welcome back to <span className="lowercase">avora</span>
        </>
      }
      subtitle="Sign in with your email or username."
      footer={
        <div className="space-y-2">
          <AuthAlt>
            Forgot your password? If you're a student, your tutor can reset it for you.
          </AuthAlt>
          <AuthAlt>
            New tutor?{" "}
            <Link to="/signup" className={authLink}>
              Create an account
            </Link>
          </AuthAlt>
        </div>
      }
    >
      <form onSubmit={onSubmit} className="space-y-5">
        <Field label="Email or username">
          <Input
            id="identifier"
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
            autoComplete="username"
            required
          />
        </Field>
        <Field label="Password">
          <Input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </Field>
        {error && (
          <p role="alert" className="text-sm text-risk-600">
            {error}
          </p>
        )}
        <Button type="submit" size="lg" loading={busy} className="w-full">
          Sign in
        </Button>
      </form>
    </AuthLayout>
  );
}
