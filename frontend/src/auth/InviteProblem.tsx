import { ButtonLink } from "../ui";

/**
 * A bad invite link used to be a dead end: one line of grey text with nowhere
 * to go. It says what probably went wrong and leaves a way out.
 */
export function InviteProblem({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-sunken px-4">
      <div className="w-full max-w-md rounded-card border border-slate-200 bg-surface p-8 text-center shadow-card">
        <div className="text-3xl leading-none">🔗</div>
        <h1 className="mt-3 text-lg font-semibold text-slate-900">{title}</h1>
        <p className="mt-2 text-sm text-slate-600">{detail}</p>
        <div className="mt-5 flex justify-center gap-2">
          <ButtonLink to="/" variant="secondary">
            What is this?
          </ButtonLink>
          <ButtonLink to="/login" variant="primary">
            Sign in
          </ButtonLink>
        </div>
      </div>
    </div>
  );
}
