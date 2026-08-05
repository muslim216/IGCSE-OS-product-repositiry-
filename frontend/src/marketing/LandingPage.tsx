import { Link } from "react-router-dom";
import { ClipboardCheck, Gauge, GraduationCap, Users } from "lucide-react";

/** The beacon: MANARA's mark — a guiding light over a tapering tower. */
function BeaconMark({ className = "h-9 w-9" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={`${className} shrink-0 text-brand-600`}>
      <circle cx="12" cy="5" r="2.6" fill="currentColor" />
      <path d="M8.5 10h7l2 9h-11z" fill="currentColor" />
      <path
        d="M9.6 14.5h4.8"
        stroke="var(--color-canvas)"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}

const LOOP = [
  {
    icon: ClipboardCheck,
    title: "Set homework in one step",
    body: "Drop in a past paper. The questions are pulled out automatically and it goes straight to your class — no second pass.",
  },
  {
    icon: GraduationCap,
    title: "Students submit from their phone",
    body: "Photos of handwritten work, marked question by question against the scheme. You review only what the AI wasn't sure about.",
  },
  {
    icon: Gauge,
    title: "Readiness updates itself",
    body: "Every mark becomes evidence behind a topic-level readiness score and a predicted grade. Nothing is a black box — each number traces back to the work it came from.",
  },
  {
    icon: Users,
    title: "Parents see the same picture",
    body: "Plain-language progress, drawn from the same record. No separate reporting to keep up with.",
  },
];

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-canvas">
      <header className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-y-3 px-6 py-5">
        <div className="flex items-center gap-2.5">
          <BeaconMark className="h-8 w-8" />
          <span className="leading-tight">
            <span className="block font-display text-[16px] tracking-[0.18em] text-ink-900">
              MANARA
            </span>
            <span className="block text-[9px] font-semibold uppercase tracking-[0.2em] text-brand-600">
              by OASIS AI
            </span>
          </span>
        </div>
        <nav className="flex items-center gap-3 text-sm">
          <Link to="/login" className="text-ink-500 transition hover:text-ink-900">
            Sign in
          </Link>
          <Link
            to="/signup"
            className="rounded-md bg-brand-600 px-4 py-2 font-medium text-canvas transition hover:bg-brand-500"
          >
            Start as a tutor
          </Link>
        </nav>
      </header>

      <main className="mx-auto max-w-5xl px-6">
        <section className="border-b border-line py-16 sm:py-24">
          <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-brand-600">
            An AI operating system for IGCSE teaching
          </p>
          <h1 className="mt-4 max-w-3xl font-display text-4xl leading-tight text-ink-900 sm:text-5xl">
            Every piece of work a student does, turned into a picture of how ready they are.
          </h1>
          <p className="mt-5 max-w-2xl text-lg text-ink-500">
            MANARA runs the loop tutors already work in — teach, assign, mark, review, plan the next
            lesson — and keeps an exam-readiness score behind it that you can always trace back to
            the evidence.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Link
              to="/signup"
              className="rounded-md bg-brand-600 px-5 py-2.5 font-medium text-canvas transition hover:bg-brand-500"
            >
              Start as a tutor
            </Link>
            <Link
              to="/login"
              className="rounded-md border border-line-strong px-5 py-2.5 font-medium text-ink-700 transition hover:border-brand-600"
            >
              I have an account
            </Link>
          </div>
          <p className="mt-4 text-sm text-ink-500">
            Students and parents join with an invite from their tutor.
          </p>
        </section>

        <section className="grid gap-6 py-16 sm:grid-cols-2">
          {LOOP.map(({ icon: Icon, title, body }) => (
            <div
              key={title}
              className="rounded-xl border border-line bg-surface p-6 shadow-[0_1px_2px_rgba(0,0,0,0.35)]"
            >
              <Icon aria-hidden className="h-5 w-5 text-brand-600" />
              <h2 className="mt-3 font-display text-lg text-ink-900">{title}</h2>
              <p className="mt-2 text-sm leading-relaxed text-ink-500">{body}</p>
            </div>
          ))}
        </section>

        <section className="border-t border-line py-16">
          <h2 className="font-display text-2xl text-ink-900">The tutor has the last word</h2>
          <p className="mt-3 max-w-2xl text-ink-500">
            The AI drafts, it never decides. Any mark it isn't confident about waits in your review
            queue instead of counting, every change you make to a mark is recorded, and a student
            can ask for anything to be looked at again. A score with no evidence behind it says so,
            rather than showing a zero.
          </p>
        </section>
      </main>

      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-6 py-6 text-sm text-ink-500">
          <span>MANARA by OASIS AI</span>
          <Link to="/login" className="transition hover:text-ink-900">
            Sign in
          </Link>
        </div>
      </footer>
    </div>
  );
}
