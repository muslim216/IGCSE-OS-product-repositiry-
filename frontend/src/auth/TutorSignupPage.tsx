import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { registerTutor } from "../api/auth";
import { useAuth } from "./AuthContext";
import { Button, Field, Input } from "../components/controls";
import { friendlyError } from "../lib/errors";
import { AuthAlt, AuthLayout, authLink } from "./AuthLayout";

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
      setError(friendlyError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout
      documentTitle="Create a tutor account"
      title="Create your tutor account"
      subtitle="Free during the pilot. Set up a class and invite your students in a few minutes."
      footer={
        <div className="space-y-2">
          <AuthAlt>
            Already have an account?{" "}
            <Link to="/login" className={authLink}>
              Sign in
            </Link>
          </AuthAlt>
          <AuthAlt>
            Students and parents don't sign up here — they join with an invite from their tutor.
          </AuthAlt>
        </div>
      }
    >
      <form onSubmit={onSubmit} className="space-y-5">
        <Field label="Full name">
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoComplete="name"
            required
          />
        </Field>
        <Field label="Email">
          <Input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            required
          />
        </Field>
        <Field label="Password" hint="At least 8 characters.">
          <Input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
            minLength={8}
            required
          />
        </Field>
        {error && (
          <p role="alert" className="text-sm text-risk-600">
            {error}
          </p>
        )}
        <Button type="submit" size="lg" loading={busy} className="w-full">
          Create account
        </Button>
        <p className="text-xs leading-relaxed text-ink-500">
          By creating an account you confirm you've read our{" "}
          <Link to="/privacy" className="underline underline-offset-2 hover:text-ink-900">
            privacy policy
          </Link>
          .
        </p>
      </form>
    </AuthLayout>
  );
}
