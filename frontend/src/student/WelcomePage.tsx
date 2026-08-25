import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

/**
 * One orientation screen, then the app (experience-design §5.4).
 *
 * A student arrives by invite code into a class their tutor has already
 * configured, so there is nothing here to set up and this asks for nothing. It
 * exists to say what the student will find and what their tutor sees.
 *
 * This used to also frame the AI chat assistant's boundaries (`UX-26`), before
 * 0.3 (AV-57) deleted that surface — there is no assistant on the platform any
 * more, so this page no longer promises one.
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
        <h3 className="avora-label mb-2">What your tutor sees</h3>
        <p className="text-sm leading-relaxed text-ink-700">
          Your tutor sees your marked work and how your subjects are going, including which topics
          need more practice.
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
