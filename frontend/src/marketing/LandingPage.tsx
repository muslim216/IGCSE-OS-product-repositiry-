import { Link } from "react-router-dom";
import { ClipboardCheck, Gauge, GraduationCap, Users } from "lucide-react";
import {
  AvoraGrain,
  AvoraLockup,
  AvoraWordmark,
  GhostMark,
  SectionOrnament,
} from "../components/brand";

/* The work that isn't teaching — the pain Avora exists to remove. Each line is
   grounded in the actual product: the homework-marking pipeline, the readiness
   engine, the traceable predicted grade, and the shared parent record. */
const PAIN = [
  {
    title: "Marking eats your evenings",
    body: "Every set of homework is a stack of photos to work through by hand, question by question, against the scheme. It has to be done, and it is always you who does it.",
  },
  {
    title: "You can't see who's slipping until it shows",
    body: "Readiness lives in your head and a spreadsheet. There's no topic-level picture of which student is quietly falling behind, or in what.",
  },
  {
    title: "Predicted grades are a gut feeling",
    body: "Boundaries in one place, marks in another, and an estimate in between that you can't really show your working for.",
  },
  {
    title: "Parents need updating — separately",
    body: "Another report to write each time, drawn from information you already hold but have to reassemble by hand.",
  },
];

/* The loop, run for you — the four cards answer the four pains above in order. */
const LOOP = [
  {
    icon: ClipboardCheck,
    title: "Set homework in one step",
    body: "Drop in a past paper. The questions are pulled out automatically and it goes straight to your class — no second pass.",
  },
  {
    icon: GraduationCap,
    title: "Marking comes back done",
    body: "Students submit photos of handwritten work from their phone, marked question by question against the scheme. You review only what the AI wasn't sure about.",
  },
  {
    icon: Gauge,
    title: "Readiness and grades keep themselves",
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
      <AvoraGrain />
      <header className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-y-3 px-6 py-5">
        <AvoraLockup />
        <nav className="flex items-center gap-3 text-sm">
          <Link to="/login" className="text-ink-500 transition hover:text-ink-900">
            Sign in
          </Link>
          <Link
            to="/signup"
            className="rounded-md bg-brand-600 px-4 py-2 font-medium text-canvas transition hover:bg-brand-700"
          >
            Start as a tutor
          </Link>
        </nav>
      </header>

      {/* One <main> landmark spans everything from the hero through the closing
          espresso panel; the espresso section is full-bleed, so the width
          wrapper lives on an inner div rather than on <main> itself. */}
      <main>
        <div className="mx-auto max-w-5xl px-6">
          <section className="relative overflow-hidden border-b border-line py-16 sm:py-24">
            <GhostMark className="-right-16 top-1/2 -translate-y-1/2" />
            <div className="relative">
              <p className="avora-label">An AI operating system for IGCSE tutors</p>
              <AvoraWordmark className="mt-5 block text-ink-900" />
              <h1 className="mt-6 max-w-3xl font-display text-4xl leading-tight text-ink-900 sm:text-5xl">
                You became a tutor to teach. The marking, tracking and reporting became the job.
              </h1>
              <p className="mt-5 max-w-2xl text-lg text-ink-500">
                avora runs the loop you already work in — teach, assign, mark, review, plan the next
                lesson — and turns every piece of work into an exam-readiness picture you can trace
                back to the evidence. The busywork stops being yours; the teaching stays yours.
              </p>
              <div className="mt-8 flex flex-wrap items-center gap-3">
                <Link
                  to="/signup"
                  className="rounded-md bg-brand-600 px-5 py-2.5 font-medium text-canvas transition hover:bg-brand-700"
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
            </div>
          </section>

          {/* Pain before resolution: the reader has to feel the problem before the
            loop below can read as the answer to it. */}
          <section className="border-b border-line py-16">
            <p className="avora-label">The work that isn't teaching</p>
            <h2 className="mt-4 max-w-3xl font-display text-3xl leading-tight text-ink-900">
              A good tutor's time disappears into everything around the lesson.
            </h2>
            <div className="mt-10 grid gap-x-10 gap-y-8 sm:grid-cols-2">
              {PAIN.map(({ title, body }, i) => (
                <div key={title} className="border-t border-line pt-5">
                  <div className="flex items-baseline gap-3">
                    <span className="font-display text-lg text-brand-600">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <h3 className="font-display text-lg text-ink-900">{title}</h3>
                  </div>
                  <p className="mt-2 text-ink-500">{body}</p>
                </div>
              ))}
            </div>
          </section>

          {/* The four cards answer the four pains above, in the same order — the
            one-to-one mapping is the argument, so keep them parallel. */}
          <section className="py-16">
            <p className="avora-label mb-2">What avora does instead</p>
            <h2 className="font-display text-3xl leading-tight text-ink-900">
              The loop, run for you — and always traceable.
            </h2>
            <div className="mt-10 grid gap-6 sm:grid-cols-2">
              {LOOP.map(({ icon: Icon, title, body }) => (
                <div
                  key={title}
                  className="rounded-xl border border-line bg-surface p-6 shadow-[0_1px_2px_rgba(44,26,14,0.06)]"
                >
                  <Icon aria-hidden className="h-5 w-5 text-brand-600" />
                  <h3 className="mt-3 font-display text-lg text-ink-900">{title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-ink-500">{body}</p>
                </div>
              ))}
            </div>
          </section>
        </div>

        <section className="avora-espresso">
          <div className="mx-auto max-w-5xl px-6 py-20">
            <SectionOrnament className="mx-auto max-w-xs" />
            <h2 className="mt-8 max-w-2xl font-display text-3xl leading-tight text-surface">
              The tutor has the last word.
            </h2>
            <p className="mt-4 max-w-2xl text-lg leading-relaxed text-line">
              The AI drafts, it never decides. Any mark it isn't confident about waits in your
              review queue instead of counting, every change you make to a mark is recorded, and a
              student can ask for anything to be looked at again. A score with no evidence behind it
              says so, rather than showing a zero.
            </p>
            <div className="mt-8">
              <Link
                to="/signup"
                className="inline-block rounded-md bg-brand-600 px-5 py-2.5 font-medium text-canvas transition hover:bg-brand-700"
              >
                Start as a tutor
              </Link>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-line bg-canvas">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-6 py-6 text-sm text-ink-500">
          <span>avora</span>
          <Link to="/login" className="transition hover:text-ink-900">
            Sign in
          </Link>
        </div>
      </footer>
    </div>
  );
}
