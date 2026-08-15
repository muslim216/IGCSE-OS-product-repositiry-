import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

/**
 * One orientation screen, then the app (experience-design §5.4).
 *
 * A student arrives by invite code into a class their tutor has already
 * configured, so there is nothing here to set up and this asks for nothing. It
 * exists to say one thing before the student meets it: what the assistant will
 * and will not do.
 *
 * `UX-26` requires that framing on student surfaces. Stating it once,
 * deliberately, at the start is materially better than letting a student
 * discover it as a refusal at 11pm over homework that is due — the boundary
 * then reads as design rather than as the product breaking when it matters.
 *
 * Shown by the join flow after an account is created, and reachable by URL
 * afterwards. It is deliberately not gated on a "seen it" flag: nothing here is
 * a task to be completed, and a student who wants to re-read it should be able
 * to.
 */
export default function WelcomePage() {
  const { user } = useAuth();
  const firstName = (user?.name ?? "").split(" ")[0];

  return (
    <div className="mx-auto max-w-prose space-y-6">
      <h2 className="font-display text-2xl font-semibold text-ink-900">
        {firstName ? `Welcome, ${firstName}.` : "Welcome."}
      </h2>

      <p className="text-sm leading-relaxed text-ink-700">
        Your tutor has set your class up already, so there is nothing for you to configure. Your
        homework, past papers and marks all arrive here.
      </p>

      <section>
        <h3 className="avora-label mb-2">About the assistant</h3>
        <p className="text-sm leading-relaxed text-ink-700">
          There is an assistant here you can ask about anything you are stuck on. It explains
          concepts and works through method with you — how to approach a titration calculation, why
          a step in an equation works.
        </p>
        <p className="mt-2 text-sm leading-relaxed text-ink-700">
          It will not give you the answers to work you have been set. That is deliberate: the point
          of the homework is what you learn doing it, and a marked answer you did not write tells
          your tutor nothing useful about where to help you next.
        </p>
      </section>

      <section>
        <h3 className="avora-label mb-2">What your tutor sees</h3>
        <p className="text-sm leading-relaxed text-ink-700">
          Your tutor sees your marked work and how your subjects are going. Your conversations with
          the assistant are not marked and are not graded.
        </p>
      </section>

      <Link
        to="/student"
        className="inline-block rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-canvas hover:bg-brand-700"
      >
        Got it — take me in
      </Link>
    </div>
  );
}
