import { Link } from "react-router-dom";
import {
  BookOpenCheck,
  Camera,
  ClipboardCheck,
  Eye,
  Gauge,
  GraduationCap,
  HeartHandshake,
  ScrollText,
  ShieldCheck,
  Users,
} from "lucide-react";
import { AvoraGrain, GhostMark, SectionOrnament } from "../components/brand";
import { buttonClasses } from "../components/controls";
import { useDocumentTitle } from "../components/page";
import { SITE } from "../lib/site";
import { SiteFooter, SiteHeader } from "./SiteChrome";

/* Every claim on this page has to be true of the product as built — a
   marketing line the code cannot back is the fastest way to lose a tutor's
   trust. Where a line names a behaviour (auto-finalize only when confident,
   remarks always go to a person, missing data is never a zero), it is the
   behaviour CLAUDE.md binds the code to. No customer logos, counts or quotes
   appear until real ones exist. */

/* The work around the lesson — the pain avora exists to remove. Each line is
   grounded in the actual product: the homework-marking pipeline, the readiness
   engine, the traceable predicted grade, and the shared parent record. */
const PAIN = [
  {
    title: "Marking eats your evenings",
    body: "A set of homework is a stack of phone photos to work through question by question against the scheme. It has to be done, and it's always you who does it.",
  },
  {
    title: "You can't see who's slipping until it shows",
    body: "Readiness lives in your head and a spreadsheet. There's no topic-by-topic view of which student is quietly falling behind, or in what.",
  },
  {
    title: "Predicted grades are a gut feeling",
    body: "Boundaries in one place, marks in another, and an estimate in between that you can't show your working for.",
  },
  {
    title: "Parents need updating, separately",
    body: "Another message to write each time, built from things you already know but have to put together again by hand.",
  },
];

/* The loop, run for you — the four steps answer the four pains above in order;
   the one-to-one mapping is the argument, so keep them parallel. */
const LOOP = [
  {
    icon: ClipboardCheck,
    title: "Set homework in one step",
    body: "Drop in a past paper. avora pulls out the questions and sends it to your class.",
  },
  {
    icon: Camera,
    title: "Marking comes back done",
    body: "Students photograph their work on their phone. avora marks each question against the mark scheme. You review only the marks it wasn't sure of, or every mark when there's no official scheme to check against.",
  },
  {
    icon: Gauge,
    title: "Readiness and grades keep themselves",
    body: "Every mark becomes evidence behind a topic-level readiness score and a predicted grade, read through the grade boundaries you set.",
  },
  {
    icon: Users,
    title: "Parents see the same picture",
    body: "Plain-language progress from the same record. No separate reporting.",
  },
];

const FACTS = [
  { icon: Camera, text: "Marks handwritten work from a phone photo" },
  { icon: ScrollText, text: "Checks each answer against the mark scheme" },
  { icon: Eye, text: "Asks you when it isn't sure" },
  { icon: Gauge, text: "Every number traces back to the work" },
];

const FAQ_BASE: { q: string; a: string }[] = [
  {
    q: "Does the AI decide my students' grades?",
    a: "No. A mark only counts on its own when the AI is confident and there is an official mark scheme to check against. Everything else waits in your review queue. You can change any mark, every change is recorded, and predicted grades come from the grade boundaries you set, never from the AI.",
  },
  {
    q: "What if a student thinks a mark is wrong?",
    a: "They can ask for any question to be looked at again. The request always comes to you, with the AI's reasoning attached. The AI never settles it.",
  },
  {
    q: "Which subjects and exam boards does it work with?",
    a: "Any IGCSE subject. Upload your exam board's syllabus and avora drafts its chapters and topics for you to check; homework and readiness are then tracked against that topic list.",
  },
  {
    q: "How do students and parents join?",
    a: "You share a class code with your students. Parents join through a private link you send them, which shows only their own child.",
  },
  {
    q: "Who can see my students' work?",
    a: "You, the student, and that student's linked parent. Each tutor's data is kept separate from every other tutor's. Our privacy policy explains what we store, where, and why.",
  },
  {
    q: "What does it cost?",
    a: "Nothing while avora is in its pilot. After it, $19 a month plus $5 for each student who had work marked that month. A tutor with 15 students pays $94. Pilot tutors get 40% off for their first 12 months, and students and parents never pay.",
  },
];

/* The contact entry is added only once SITE.contactEmail is set, the same guard
   the footer uses, so the page never points at an unmonitored inbox. */
function faqItems() {
  return SITE.contactEmail
    ? [
        ...FAQ_BASE,
        {
          q: "Can I talk to a person?",
          a: `Yes. Email ${SITE.contactEmail} and you'll get a reply from the person building avora, not a bot.`,
        },
      ]
    : FAQ_BASE;
}

/** A real screenshot of the product in a quiet browser frame. */
/* Both shots carry their intrinsic size so the browser reserves the space
   before the image arrives; without it everything below the hero jumps down
   once the screenshot loads. */
function ProductShot({
  src,
  alt,
  className = "",
  eager = false,
}: {
  src: string;
  alt: string;
  className?: string;
  /** The hero shot is above the fold: load it straight away, not lazily. */
  eager?: boolean;
}) {
  return (
    <figure
      className={`overflow-hidden rounded-xl border border-line-strong/70 bg-surface shadow-[0_24px_60px_-20px_rgba(44,26,14,0.25)] ${className}`}
    >
      <div
        aria-hidden
        className="flex items-center gap-1.5 border-b border-line bg-surface-muted px-4 py-2.5"
      >
        <span className="h-2.5 w-2.5 rounded-full bg-line-strong" />
        <span className="h-2.5 w-2.5 rounded-full bg-line-strong" />
        <span className="h-2.5 w-2.5 rounded-full bg-line-strong" />
      </div>
      <img
        src={src}
        alt={alt}
        width={2560}
        height={1600}
        className="block h-auto w-full"
        loading={eager ? "eager" : "lazy"}
        decoding="async"
      />
    </figure>
  );
}

function PhoneShot({ src, alt, className = "" }: { src: string; alt: string; className?: string }) {
  return (
    <figure
      className={`overflow-hidden rounded-[2rem] border-[6px] border-ink-900 bg-ink-900 shadow-[0_24px_50px_-16px_rgba(44,26,14,0.45)] ${className}`}
    >
      <img
        src={src}
        alt={alt}
        width={780}
        height={1560}
        className="block h-auto w-full rounded-[1.5rem]"
        loading="lazy"
        decoding="async"
      />
    </figure>
  );
}

export default function LandingPage() {
  useDocumentTitle("Marking, readiness and reporting for IGCSE tutors");
  return (
    <div className="min-h-screen bg-canvas">
      <AvoraGrain />
      <SiteHeader />

      <main>
        {/* Hero */}
        <section className="relative overflow-hidden">
          <GhostMark className="-right-20 top-10" />
          <div className="relative mx-auto max-w-6xl px-6 pt-16 sm:pt-24">
            <p className="avora-label">For IGCSE tutors</p>
            <h1 className="mt-5 max-w-3xl text-balance text-[2.5rem] leading-[1.08] tracking-[-0.02em] text-ink-900 sm:text-6xl">
              Hand back marked homework without spending your evening on it.
            </h1>
            <p className="mt-6 max-w-2xl text-lg leading-relaxed text-ink-500">
              Students photograph their handwritten work. avora marks each answer against the
              official mark scheme and asks you only about the ones it isn't sure of. Every mark
              adds to a readiness picture that you, the student and the parent all see.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Link to="/signup" className={buttonClasses("primary", "lg")}>
                Start free as a tutor
              </Link>
              <a href="#marked-paper" className={buttonClasses("secondary", "lg")}>
                See a marked paper
              </a>
            </div>
            <p className="mt-4 text-sm text-ink-500">
              Free during the pilot, no card needed. Students and parents join with an invite from
              you.
            </p>

            <div className="relative mt-16 pb-10 sm:mt-20">
              <ProductShot
                eager
                src="/product/class.jpg"
                alt="A tutor's class page in avora: each learner's predicted grade, readiness status and handed-in homework."
              />
              <PhoneShot
                src="/product/student-phone.jpg"
                alt="A student's home screen on a phone: marked homework, the next lesson and what to do next."
                className="absolute -bottom-2 right-4 hidden w-44 sm:block lg:-right-6 lg:w-56"
              />
            </div>
          </div>
        </section>

        {/* What it does, in four facts */}
        <section aria-label="At a glance" className="border-y border-line bg-surface">
          <ul className="mx-auto grid max-w-6xl grid-cols-2 gap-px px-6 lg:grid-cols-4">
            {FACTS.map(({ icon: Icon, text }) => (
              <li key={text} className="flex items-center gap-3 py-6 pr-4 text-sm text-ink-700">
                <Icon aria-hidden className="h-5 w-5 shrink-0 text-brand-600" />
                {text}
              </li>
            ))}
          </ul>
        </section>

        <div className="mx-auto max-w-6xl px-6">
          {/* Pain before resolution: the reader has to feel the problem before the
              loop below can read as the answer to it. */}
          <section className="border-b border-line py-20">
            <p className="avora-label">The part of tutoring nobody signed up for</p>
            <h2 className="mt-4 max-w-3xl text-3xl leading-tight text-ink-900 sm:text-4xl">
              Good tutors lose their evenings to everything around the lesson.
            </h2>
            <div className="mt-12 grid gap-x-12 gap-y-10 sm:grid-cols-2">
              {PAIN.map(({ title, body }, i) => (
                <div key={title} className="border-t border-line pt-5">
                  <div className="flex items-baseline gap-3">
                    <span className="font-display text-lg text-brand-600">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <h3 className="font-display text-xl text-ink-900">{title}</h3>
                  </div>
                  <p className="mt-2 leading-relaxed text-ink-500">{body}</p>
                </div>
              ))}
            </div>
          </section>

          {/* How it works */}
          <section id="how-it-works" className="scroll-mt-20 py-20">
            <p className="avora-label">How it works</p>
            <h2 className="mt-4 max-w-3xl text-3xl leading-tight text-ink-900 sm:text-4xl">
              The same loop you run now, with the busywork taken out.
            </h2>
            <ol className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
              {LOOP.map(({ icon: Icon, title, body }, i) => (
                <li
                  key={title}
                  className="rounded-xl border border-line bg-surface p-6 shadow-[0_1px_2px_rgba(44,26,14,0.06)]"
                >
                  <div className="flex items-center justify-between">
                    <span className="grid h-10 w-10 place-items-center rounded-lg bg-brand-50 text-brand-600">
                      <Icon aria-hidden className="h-5 w-5" />
                    </span>
                    <span className="font-display text-sm text-ink-500">Step {i + 1}</span>
                  </div>
                  <h3 className="mt-5 font-display text-lg text-ink-900">{title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-ink-500">{body}</p>
                </li>
              ))}
            </ol>

            {/* The hero's secondary button lands here. */}
            <div
              id="marked-paper"
              className="mt-16 grid scroll-mt-20 items-center gap-10 lg:grid-cols-[1fr_1.4fr]"
            >
              <div>
                <h3 className="font-display text-2xl leading-snug text-ink-900">
                  This is what a marked paper looks like.
                </h3>
                <p className="mt-3 leading-relaxed text-ink-500">
                  Each answer arrives marked against the scheme, with the reasoning and how sure
                  avora was. Confident marks count straight away. The rest wait for you. Change any
                  mark and both versions are kept. Yours always wins.
                </p>
              </div>
              <ProductShot
                src="/product/review.jpg"
                alt="A submission in avora: the student's uploaded work beside each question's mark, feedback and the AI's confidence."
              />
            </div>
          </section>
        </div>

        {/* A plain note from the builder. No card, no logo, no quote: the page
            has none to show yet, and says so. Wording is the owner's to confirm. */}
        <section id="note" aria-labelledby="note-heading" className="bg-surface-muted/60">
          <div className="mx-auto max-w-6xl px-6 py-20">
            <div className="max-w-[60ch]">
              <h2 id="note-heading" className="avora-label">
                A note from the person building avora
              </h2>
              <div className="mt-6 space-y-5 font-display text-xl leading-relaxed text-ink-900">
                <p>
                  avora exists because marking by hand is the part of tutoring that eats the
                  evening. It is built around how a tutor actually works: a phone photo of
                  handwritten work, the exam board's mark scheme, and a parent who wants a straight
                  answer.
                </p>
                <p>
                  It's in its pilot, and free while it is. There are no logos or testimonials on
                  this page because there aren't any yet. When there are, they'll be real.
                </p>
                <p>
                  Everything on this page is something the product does today.
                  {/* Asks for contact only when there is an inbox to send it to. */}
                  {SITE.contactEmail &&
                    ` If you use it and something is wrong or missing, email ${SITE.contactEmail}. That is what the pilot is for.`}
                </p>
              </div>
              <p className="mt-8 font-display text-xl italic text-ink-900">Anas</p>
              <p className="text-sm text-ink-500">Building avora</p>
            </div>
            <div className="mt-14 border-t border-line pt-8">
              <h3 className="avora-label">What the pilot is</h3>
              <ul className="mt-4 grid gap-4 text-ink-700 sm:grid-cols-3">
                <li>Free, every feature, for every class you teach.</li>
                <li>Open to any IGCSE tutor, in any subject.</li>
                <li>Paid plans come later, with 40% off a pilot tutor's first 12 months.</li>
              </ul>
            </div>
          </div>
        </section>

        {/* Students and parents */}
        <section id="students-and-parents" className="scroll-mt-20 border-t border-line bg-surface">
          <div className="mx-auto grid max-w-6xl gap-12 px-6 py-20 lg:grid-cols-2">
            <div>
              <p className="avora-label">For students</p>
              <h2 className="mt-4 text-3xl leading-tight text-ink-900">
                Know what's due, how you did, and what to work on next.
              </h2>
              <ul className="mt-6 space-y-3 text-ink-700">
                <li className="flex gap-3">
                  <GraduationCap aria-hidden className="mt-0.5 h-5 w-5 shrink-0 text-brand-600" />
                  Hand in homework by taking a photo. No scanning, no printing.
                </li>
                <li className="flex gap-3">
                  <BookOpenCheck aria-hidden className="mt-0.5 h-5 w-5 shrink-0 text-brand-600" />
                  See every mark with feedback, and ask for a second look at any question.
                </li>
                <li className="flex gap-3">
                  <Gauge aria-hidden className="mt-0.5 h-5 w-5 shrink-0 text-brand-600" />
                  Watch your predicted grade move as your marked work comes in.
                </li>
              </ul>
            </div>
            <div>
              <p className="avora-label">For parents</p>
              <h2 className="mt-4 text-3xl leading-tight text-ink-900">
                A clear, honest picture, without chasing anyone for it.
              </h2>
              <ul className="mt-6 space-y-3 text-ink-700">
                <li className="flex gap-3">
                  <HeartHandshake aria-hidden className="mt-0.5 h-5 w-5 shrink-0 text-brand-600" />
                  Plain-language progress in each subject, updated as work is marked.
                </li>
                <li className="flex gap-3">
                  <Eye aria-hidden className="mt-0.5 h-5 w-5 shrink-0 text-brand-600" />
                  Only your own child's record, through a private link from their tutor.
                </li>
                <li className="flex gap-3">
                  <ShieldCheck aria-hidden className="mt-0.5 h-5 w-5 shrink-0 text-brand-600" />
                  When there isn't enough marked work yet, avora says so. It never guesses.
                </li>
              </ul>
            </div>
          </div>
        </section>

        {/* Trust */}
        <section id="trust" className="avora-espresso scroll-mt-16">
          <div className="mx-auto max-w-6xl px-6 py-24">
            <SectionOrnament className="max-w-xs" />
            <h2 className="mt-8 max-w-2xl text-3xl leading-tight text-surface sm:text-4xl">
              You have the last word.
            </h2>
            <div className="mt-10 grid gap-8 sm:grid-cols-3">
              {[
                {
                  t: "The AI drafts. You decide.",
                  b: "Any mark the AI isn't confident about waits in your review queue instead of counting.",
                },
                {
                  t: "Every change is on the record.",
                  b: "When you change a mark, the original and your decision are both kept. Nothing is silently overwritten.",
                },
                {
                  t: "No evidence, no number.",
                  b: "A score with nothing behind it says so, rather than showing a zero or a guess.",
                },
              ].map(({ t, b }) => (
                <div key={t} className="border-t border-surface/20 pt-5">
                  <h3 className="font-display text-lg text-surface">{t}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-line">{b}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Pricing */}
        <section id="pricing" className="scroll-mt-20">
          <div className="mx-auto max-w-6xl px-6 py-20">
            <p className="avora-label">Pricing</p>
            <h2 className="mt-4 text-3xl leading-tight text-ink-900 sm:text-4xl">
              Free while we're in pilot.
            </h2>
            <div className="mt-10 grid gap-6 lg:grid-cols-[1.2fr_1fr]">
              <div className="rounded-xl border-2 border-brand-600 bg-surface p-8">
                <div className="flex items-baseline justify-between gap-4">
                  <h3 className="font-display text-2xl text-ink-900">Pilot</h3>
                  <span className="rounded-full bg-brand-50 px-3 py-1 text-xs font-medium text-brand-700">
                    Open now
                  </span>
                </div>
                <p className="mt-4 font-display text-5xl text-ink-900">
                  Free<span className="ml-2 text-base text-ink-500">during the pilot</span>
                </p>
                <ul className="mt-6 space-y-2.5 text-sm text-ink-700">
                  {[
                    "Every feature, for every class you teach",
                    "Marking of handwritten homework and past papers",
                    "Topic readiness and predicted grades for each student",
                    "Student and parent accounts included",
                  ].map((f) => (
                    <li key={f} className="flex gap-2.5">
                      <ShieldCheck aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ok-700" />
                      {f}
                    </li>
                  ))}
                </ul>
                <Link to="/signup" className={buttonClasses("primary", "lg", "mt-8")}>
                  Start free as a tutor
                </Link>
              </div>
              <div className="rounded-xl border border-line bg-surface-muted/60 p-8">
                <h3 className="font-display text-2xl text-ink-900">After the pilot</h3>
                {/* Priced per active student because that is what costs us money:
                    every marked submission is a model call, so a flat tier would
                    lose money on the busiest tutors. AED is shown as an approximate
                    conversion; billing is in USD. */}
                <p className="mt-4 font-display text-4xl text-ink-900">
                  $19<span className="ml-1.5 text-base text-ink-500">/ month</span>
                </p>
                <p className="mt-1 text-ink-700">+ $5 per active student each month</p>
                <p className="mt-1 text-xs text-ink-500">≈ AED 70 + AED 18 per student</p>
                <dl className="mt-6 space-y-2.5 text-sm text-ink-700">
                  {[
                    ["5 students", "$44 / month"],
                    ["15 students", "$94 / month"],
                    ["30 students", "$169 / month"],
                  ].map(([k, v]) => (
                    <div key={k} className="flex justify-between gap-4 border-b border-line pb-2">
                      <dt>{k}</dt>
                      <dd className="tabular-nums text-ink-900">{v}</dd>
                    </div>
                  ))}
                </dl>
                <p className="mt-4 text-sm leading-relaxed text-ink-700">
                  An active student is one who had work marked that month. Students who take a month
                  off cost you nothing.
                </p>
                <p className="mt-4 rounded-lg bg-brand-50 p-3 text-sm text-brand-700">
                  Pilot tutors get 40% off for their first 12 months on a paid plan.
                </p>
                <p className="mt-4 text-sm text-ink-500">
                  Students and parents never pay. They join through their tutor.
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* FAQ */}
        <section id="faq" className="scroll-mt-20 border-t border-line">
          <div className="mx-auto grid max-w-6xl gap-10 px-6 py-20 lg:grid-cols-[1fr_2fr]">
            <div>
              <p className="avora-label">Questions</p>
              <h2 className="mt-4 text-3xl leading-tight text-ink-900">What tutors ask first.</h2>
            </div>
            <div className="divide-y divide-line border-y border-line">
              {faqItems().map(({ q, a }) => (
                <details key={q} className="group py-5">
                  <summary className="flex cursor-pointer list-none [&::-webkit-details-marker]:hidden items-center justify-between gap-4 font-medium text-ink-900">
                    {q}
                    <span
                      aria-hidden
                      className="text-xl leading-none text-brand-600 transition-transform group-open:rotate-45"
                    >
                      +
                    </span>
                  </summary>
                  <p className="mt-3 max-w-2xl leading-relaxed text-ink-500">{a}</p>
                </details>
              ))}
            </div>
          </div>
        </section>

        {/* Closing call */}
        <section className="border-t border-line bg-surface">
          <div className="mx-auto flex max-w-6xl flex-col items-start justify-between gap-6 px-6 py-16 sm:flex-row sm:items-center">
            <h2 className="max-w-xl text-3xl leading-tight text-ink-900">
              Get your evenings back this term.
            </h2>
            <Link to="/signup" className={buttonClasses("primary", "lg")}>
              Start free as a tutor
            </Link>
          </div>
        </section>
      </main>

      <SiteFooter />
    </div>
  );
}
