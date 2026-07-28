import { Link } from "react-router-dom";
import { ButtonLink, Card } from "../ui";

/*
 * The root path used to bounce straight to a login form, so nobody could tell
 * what the product was before signing in. Everything claimed here is something
 * the app actually does today.
 */

const ROLES = [
  {
    icon: "🧑‍🏫",
    title: "Tutors",
    points: [
      "Set homework by dropping in a past paper",
      "Review AI-drafted marking — you always decide the final mark",
      "See which topics the class is weakest on",
    ],
  },
  {
    icon: "🧑‍🎓",
    title: "Students",
    points: [
      "Photograph handwritten work and submit it",
      "See exam readiness and a predicted grade per subject",
      "Ask an AI tutor that knows what you're working on",
    ],
  },
  {
    icon: "👪",
    title: "Parents",
    points: [
      "See how your child is doing in plain language",
      "Read progress reports written for you, not for teachers",
      "Know which topics need work before exams",
    ],
  },
];

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-surface-sunken">
      <header className="border-b border-slate-200 bg-surface">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
          <span className="text-lg font-semibold text-slate-900">IGCSE Student OS</span>
          <Link to="/login" className="text-sm text-slate-600 hover:text-slate-900">
            Sign in
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4">
        <section className="py-16 text-center sm:py-24">
          <h1 className="text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
            Know exactly how ready each student is
          </h1>
          <p className="mx-auto mt-4 max-w-2xl text-lg text-slate-600">
            Every piece of evidence — homework, mocks, your own observations — feeds a
            topic-level readiness score, so nobody finds out what they didn't know in the exam
            hall.
          </p>
          <div className="mt-8 flex flex-wrap justify-center gap-3">
            <ButtonLink to="/signup" variant="primary">
              Start as a tutor
            </ButtonLink>
            <ButtonLink to="/login" variant="secondary">
              Sign in
            </ButtonLink>
          </div>
          <p className="mt-4 text-sm text-slate-500">
            Students and parents join with an invite link from their tutor.
          </p>
        </section>

        <section className="grid gap-4 pb-16 md:grid-cols-3">
          {ROLES.map((role) => (
            <Card key={role.title} className="p-6">
              <div className="text-2xl leading-none">{role.icon}</div>
              <h2 className="mt-3 font-semibold text-slate-900">{role.title}</h2>
              <ul className="mt-3 space-y-2">
                {role.points.map((point) => (
                  <li key={point} className="flex gap-2 text-sm text-slate-600">
                    <span aria-hidden className="text-brand-500">
                      •
                    </span>
                    {point}
                  </li>
                ))}
              </ul>
            </Card>
          ))}
        </section>

        <section className="border-t border-slate-200 py-10 text-center">
          <h2 className="font-semibold text-slate-900">How marking works</h2>
          <p className="mx-auto mt-2 max-w-2xl text-sm text-slate-600">
            The AI reads the paper, drafts a mark and feedback for each question, and flags
            anything it couldn't read or had no mark scheme for. The tutor reviews the draft
            side by side with the student's work and decides the final mark — nothing reaches a
            student until they've signed it off.
          </p>
        </section>
      </main>

      <footer className="border-t border-slate-200 bg-surface py-6 text-center text-sm text-slate-500">
        IGCSE Student OS
      </footer>
    </div>
  );
}
