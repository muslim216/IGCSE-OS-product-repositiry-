import type { ReactNode } from "react";
import { AlertTriangle } from "lucide-react";
import { PublicPage } from "../marketing/SiteChrome";
import { SITE } from "../lib/site";

/* The public privacy policy.

   Every statement here must stay true of the product. It is derived from
   docs/legal/privacy-law-register.md (which laws apply and why) and written for
   avora as it must be at launch: the items it promises that are not yet built
   are tracked as launch blockers in docs/legal/pre-launch-privacy-gaps.md. When
   the product or the law changes, change the register first, then this page,
   and bump POLICY_VERSION so consent records can name the version a guardian
   agreed to. */

const POLICY_VERSION = "draft-2026-10-02";
const LAST_UPDATED = "2 October 2026";

const SECTIONS = [
  { id: "short", title: "The short version" },
  { id: "students", title: "If you're a student" },
  { id: "who", title: "Who we are and who decides" },
  { id: "collect", title: "What we collect" },
  { id: "use", title: "How we use it, and why we're allowed to" },
  { id: "children", title: "Children and parents" },
  { id: "ai", title: "How AI is used" },
  { id: "share", title: "Who we share it with" },
  { id: "transfers", title: "Where it's stored" },
  { id: "retention", title: "How long we keep it" },
  { id: "rights", title: "Your rights" },
  { id: "security", title: "How we protect it" },
  { id: "cookies", title: "Cookies and storage on your device" },
  { id: "changes", title: "Changes and contact" },
] as const;

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-24 border-t border-line pt-10">
      <h2 className="text-2xl leading-tight text-ink-900">{title}</h2>
      <div className="mt-4 space-y-4 leading-relaxed text-ink-700 [&_li]:pl-1 [&_strong]:text-ink-900 [&_ul]:list-disc [&_ul]:space-y-2 [&_ul]:pl-5">
        {children}
      </div>
    </section>
  );
}

function Table({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-line">
      <table className="w-full min-w-[36rem] text-left text-sm">
        <thead className="bg-surface-muted text-ink-900">
          <tr>
            {head.map((h) => (
              <th key={h} scope="col" className="px-4 py-3 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line bg-surface align-top">
          {rows.map((r, i) => (
            <tr key={i}>
              {r.map((c, j) => (
                <td key={j} className="px-4 py-3 text-ink-700">
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Contact() {
  return SITE.privacyEmail ? (
    <a href={`mailto:${SITE.privacyEmail}`} className="text-brand-600 hover:underline">
      {SITE.privacyEmail}
    </a>
  ) : (
    <span>our privacy contact address (published here before launch)</span>
  );
}

export default function PrivacyPolicyPage() {
  return (
    <PublicPage title="Privacy policy">
      <div className="mx-auto max-w-6xl px-6 py-16">
        <p className="avora-label">Legal</p>
        <h1 className="mt-4 text-4xl leading-tight text-ink-900 sm:text-5xl">Privacy policy</h1>
        <p className="mt-4 text-ink-500">
          Last updated {LAST_UPDATED} · Version {POLICY_VERSION}
        </p>

        <div
          role="note"
          className="mt-8 flex max-w-3xl gap-3 rounded-lg border border-warn-700/30 bg-warn-100 p-4 text-sm text-warn-700"
        >
          <AlertTriangle aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            <strong>Draft — pending legal review.</strong> avora has not launched yet. This policy
            describes how avora will handle personal data when it does, and it will be reviewed by
            qualified lawyers in each country where avora launches before anyone relies on it.
          </p>
        </div>

        <div className="mt-12 grid gap-12 lg:grid-cols-[14rem_1fr]">
          <nav aria-label="On this page" className="lg:sticky lg:top-24 lg:self-start">
            <p className="avora-label">On this page</p>
            <ol className="mt-4 space-y-2 text-sm">
              {SECTIONS.map((s) => (
                <li key={s.id}>
                  <a href={`#${s.id}`} className="text-ink-700 hover:text-brand-600">
                    {s.title}
                  </a>
                </li>
              ))}
            </ol>
          </nav>

          <article className="max-w-3xl space-y-10">
            <Section id="short" title="The short version">
              <ul>
                <li>
                  avora helps tutors set homework, mark it with the help of AI, and track how ready
                  each student is for their IGCSE exams. Students see their own work and marks; a
                  linked parent or guardian sees their child's progress and reports.
                </li>
                <li>
                  <strong>Your tutor is in charge of the information about their class.</strong> We
                  hold and process it for them, and only to provide avora.
                </li>
                <li>
                  <strong>
                    We never sell personal data, never show adverts, and never use it to train AI
                    models.
                  </strong>
                </li>
                <li>Students under 18 can only use avora once a parent or guardian has agreed.</li>
                <li>
                  AI drafts marks and reports. Your tutor can change any mark, and you can always
                  ask for a person to look at a mark again.
                </li>
                <li>
                  Your data is stored in the United States. We use the legal safeguards your
                  country's law requires to protect it there.
                </li>
                <li>
                  You can ask to see, correct, download or delete your data at any time. We answer
                  within 30 days.
                </li>
              </ul>
            </Section>

            <Section id="students" title="If you're a student">
              <p>Here's what happens to your information, in plain words:</p>
              <ul>
                <li>
                  When you hand in homework, avora keeps a copy of your pages so your tutor can see
                  them and mark them.
                </li>
                <li>
                  A computer program called AI reads your answers and suggests a mark and some
                  feedback. Sometimes it is wrong. If you think a mark is wrong, press{" "}
                  <strong>Request a remark</strong> — your tutor will look at it, not the AI.
                </li>
                <li>
                  Your tutor can see your work, your marks and notes they write about how you're
                  doing. A parent or guardian linked to your account can see your progress and
                  reports.
                </li>
                <li>
                  Your predicted grade is an estimate worked out from your marked work. It is not an
                  official exam result.
                </li>
                <li>
                  Nobody else can see your work. We don't sell it, we don't show you adverts, and we
                  don't use it to train AI.
                </li>
                <li>
                  If you want to see everything we hold about you, or want something deleted, ask
                  your tutor or a parent, or contact us directly.
                </li>
              </ul>
            </Section>

            <Section id="who" title="Who we are and who decides">
              <p>
                avora ("we", "us") provides the avora service. The legal entity, its registered
                address and, where the law requires them, our representatives in the European Union
                and the United Kingdom and our data protection officer will be named here before
                launch.
              </p>
              <p>Data protection law gives two different roles, and avora has both:</p>
              <ul>
                <li>
                  <strong>Your tutor is the controller</strong> of the information about their
                  classes — student profiles, uploaded work, marks, notes, readiness and reports.
                  Your tutor decides why that information is used: to teach and support their
                  students.
                </li>
                <li>
                  <strong>avora is the processor</strong> of that information. We process it only on
                  the tutor's instructions and only to provide the service, under a data processing
                  agreement every tutor accepts.
                </li>
                <li>
                  <strong>avora is the controller</strong> of the information we need to run avora
                  itself: account and sign-in details, security records and records of how much the
                  service is used.
                </li>
              </ul>
              <p>
                If you are a student or parent, you can contact your tutor or us about any of your
                data — we will help either way.
              </p>
            </Section>

            <Section id="collect" title="What we collect">
              <Table
                head={["Information", "Examples", "Where it comes from"]}
                rows={[
                  [
                    "Account details",
                    "Name, email address or username, password (stored only as a one-way hash), role, time zone",
                    "You, or your tutor when they create a username for a student",
                  ],
                  [
                    "Student profile",
                    "School, year group, subjects, target grades; a parent's name, email and phone if the tutor adds them",
                    "Your tutor",
                  ],
                  [
                    "Homework and exam work",
                    "Photos and PDFs of handwritten answers to homework, mock exams and past papers",
                    "The student",
                  ],
                  [
                    "Marks and feedback",
                    "Marks per question, written feedback, how confident the AI was, any changes the tutor made and why, remark requests",
                    "The AI, the tutor and the student",
                  ],
                  [
                    "Progress information",
                    "Topic readiness scores, predicted grades, mistake types, progress reports, tutor notes and observations, records of messages to parents",
                    "Calculated by avora from marked work, or written by the tutor",
                  ],
                  [
                    "Lessons and resources",
                    "Lesson times, shared files and recording links",
                    "Your tutor",
                  ],
                  [
                    "Service and security records",
                    "Sign-in attempts (to stop password guessing), records of each use of the AI and its cost",
                    "Created by avora when you use it",
                  ],
                ]}
              />
              <p>
                <strong>We don't collect</strong> your location, contacts, photos other than the
                work you upload, or anything from other apps. Handwriting in uploaded work is used
                only to read and mark the answers — never to identify anyone from their handwriting.
              </p>
              <p>
                Please don't put health, medical or special-educational-needs information in notes
                or uploads unless it's needed to support the student. Tutors are asked not to record
                it.
              </p>
            </Section>

            <Section id="use" title="How we use it, and why we're allowed to">
              <Table
                head={["What we do", "Why we're allowed to"]}
                rows={[
                  [
                    "Run tutor accounts and the avora service",
                    "To perform our contract with the tutor",
                  ],
                  [
                    "Store and mark students' work, calculate readiness and predicted grades, write reports, and show students and parents their progress — for the tutor",
                    "On the tutor's instructions. The tutor relies on their contract with the family or their legitimate interest in teaching the student, and — for every student under 18 — on the documented consent of a parent or guardian",
                  ],
                  [
                    "Keep sign-ins secure and stop misuse",
                    "Our legitimate interest in keeping avora and its users safe, and our legal duty to protect data",
                  ],
                  [
                    "Measure how much AI the service uses and what it costs",
                    "Our legitimate interest in running the service; these records contain no student work",
                  ],
                  ["Meet legal obligations", "Where the law requires it"],
                ]}
              />
              <p>
                We do <strong>not</strong> use personal data for advertising, marketing profiles,
                selling, or training AI models — ours or anyone else's.
              </p>
            </Section>

            <Section id="children" title="Children and parents">
              <p>
                Most students on avora are under 18, so we treat every student as a child and design
                for that.
              </p>
              <ul>
                <li>
                  <strong>Parent or guardian consent first.</strong> A student under 18 can only use
                  avora after a parent or guardian has confirmed they are the child's parent or
                  guardian and agreed to this policy, including the use of AI and storage outside
                  their country. For children under 13 we use a stronger check. We keep a record of
                  who agreed, when, and to which version of this policy.
                </li>
                <li>
                  <strong>Withdrawing consent is easy.</strong> A parent or guardian can withdraw
                  consent at any time from their account or by contacting us. We then stop
                  processing the child's data and delete it, as described below.
                </li>
                <li>
                  <strong>Parents' rights.</strong> A parent or guardian can see a description of
                  what we hold about their child, get a copy, and ask for it to be corrected or
                  deleted.
                </li>
                <li>
                  <strong>Students are told who can see their record</strong>, including that a
                  linked parent can see their progress.
                </li>
                <li>
                  <strong>No adverts and no profiling for marketing</strong> — ever.
                </li>
              </ul>
            </Section>

            <Section id="ai" title="How AI is used">
              <p>
                avora uses an AI model provided by <strong>Anthropic</strong> to read students'
                uploaded work, suggest marks and feedback against the mark scheme, pull questions
                out of past papers, draft progress reports, and write the readiness summaries — each
                student's overall readiness, weaker topics and suggested revision, and a summary of
                the class for the tutor. Everywhere a student or parent sees a mark or report that
                AI helped produce, avora says so.
              </p>
              <ul>
                <li>
                  <strong>The AI suggests; people decide.</strong> If the AI isn't confident about a
                  mark, or there is no official mark scheme to check against, the mark waits for the
                  tutor. Whether any mark can count before the tutor has reviewed it is the tutor's
                  choice for each class, and is switched off unless they turn it on; any mark that
                  counted without review is labelled as AI-marked.
                </li>
                <li>
                  <strong>You can always ask a person.</strong> A student can ask for any question's
                  mark to be looked at again. That request always goes to the tutor, with the AI's
                  reasoning attached — the AI never decides a remark.
                </li>
                <li>
                  <strong>Tutors can change any mark</strong>, and every change is permanently
                  recorded with the original.
                </li>
                <li>
                  <strong>Predicted grades are not made by AI.</strong> They are worked out from
                  marked work using grade boundaries the tutor sets. They are estimates, not
                  official results.
                </li>
                <li>
                  <strong>No training.</strong> Our AI provider does not use the data we send to
                  train its models, and deletes it after a short period (currently up to 30 days)
                  unless it is needed to investigate misuse.
                </li>
                <li>
                  <strong>Minimal data.</strong> We send the AI only what each task needs, together
                  with the tutor's own guidance where it applies — their marking rules, their notes
                  on the paper and their teaching notes for the subject. To mark work: the student's
                  pages, the questions and the mark scheme, without the student's name. To pull
                  questions out of a paper: the paper itself. For readiness summaries and reports:
                  the student's name, the subject, and the scores avora has worked out for them
                  (from marked work and any estimates their tutor entered). Never students' contact
                  details.
                </li>
              </ul>
              <p>
                Where the law gives you the right not to be subject to a decision made only by
                automated means, or to object to one, you can use it by requesting a remark or by
                contacting your tutor or us.
              </p>
            </Section>

            <Section id="share" title="Who we share it with">
              <p>
                Inside avora, information is visible only to the people the tutor's class gives
                access to: the tutor, the student, and that student's linked parent or guardian.
                Each tutor's information is kept separate from every other tutor's.
              </p>
              <p>We use these service providers, who process data only on our instructions:</p>
              <Table
                head={["Provider", "What they do", "Where"]}
                rows={[
                  [
                    "Render",
                    "Hosts the avora application, its database and uploaded files",
                    "United States",
                  ],
                  ["Vercel", "Delivers the avora website to your browser", "Global network"],
                  [
                    "Anthropic",
                    "Provides the AI model used for marking, readiness summaries and reports",
                    "United States",
                  ],
                ]}
              />
              <p>
                We will update this list before we add or change a provider, and tutors are told in
                advance. We may also disclose information if the law requires it, or to protect
                someone's safety.
              </p>
            </Section>

            <Section id="transfers" title="Where it's stored">
              <p>
                avora's data is stored in the <strong>United States</strong>. When we move personal
                data out of your country, we use the safeguards your country's law requires — for
                example:
              </p>
              <ul>
                <li>
                  <strong>European Union and United Kingdom:</strong> the EU–US Data Privacy
                  Framework where a provider is certified, otherwise the European Commission's
                  standard contractual clauses (and the UK addendum), with a transfer risk
                  assessment.
                </li>
                <li>
                  <strong>Saudi Arabia:</strong> the standard contractual clauses issued by SDAIA
                  and a documented transfer risk assessment.
                </li>
                <li>
                  <strong>Oman:</strong> your explicit consent, given as part of parent or guardian
                  consent, together with a transfer assessment.
                </li>
                <li>
                  <strong>United Arab Emirates and other countries:</strong> contractual safeguards
                  that give your data equivalent protection.
                </li>
              </ul>
              <p>You can ask us for a copy of the safeguards that apply to you.</p>
            </Section>

            <Section id="retention" title="How long we keep it">
              <Table
                head={["Information", "How long"]}
                rows={[
                  [
                    "Student work, marks, readiness, notes and reports",
                    "While the student is in the tutor's class. Deleted within 90 days after the student leaves the class or the tutor closes their account, unless the tutor exports it first",
                  ],
                  [
                    "Accounts",
                    "While the account is in use. Deleted within 90 days after it is closed, or after 24 months without use — we warn you first",
                  ],
                  [
                    "Records of mark changes",
                    "As long as the mark they belong to. When the mark is deleted, the record is anonymised",
                  ],
                  ["Data sent to our AI provider", "Up to 30 days, then deleted by the provider"],
                  ["Sign-in protection counters", "Minutes to hours"],
                  ["AI usage and cost records (no student work)", "24 months"],
                  [
                    "Records of parent or guardian consent",
                    "As long as the law requires us to be able to show consent was given",
                  ],
                ]}
              />
            </Section>

            <Section id="rights" title="Your rights">
              <p>Depending on where you live, you have the right to:</p>
              <ul>
                <li>know what we hold about you and get a copy, including in a reusable format;</li>
                <li>have it corrected if it's wrong — including a mark you think is wrong;</li>
                <li>have it deleted;</li>
                <li>restrict or object to how it's used;</li>
                <li>
                  not be subject to a decision made only by automated means where the law protects
                  you from it, and ask for a person to review it;
                </li>
                <li>withdraw consent at any time, without affecting what was done before;</li>
                <li>complain to your data protection authority.</li>
              </ul>
              <p>
                Parents and guardians can use these rights for their child. You can ask your tutor
                or contact us at <Contact />. We answer within <strong>30 days</strong>, free of
                charge; we may need to check your identity first.
              </p>
              <p>
                You can complain to the data protection authority where you live — for example your
                national supervisory authority in the EU, the Information Commissioner's Office in
                the UK, SDAIA in Saudi Arabia, the UAE Data Office, the National Cyber Security
                Agency in Qatar, or the Ministry of Transport, Communications and Information
                Technology in Oman. We'd be grateful for the chance to put things right first.
              </p>
            </Section>

            <Section id="security" title="How we protect it">
              <ul>
                <li>All connections to avora are encrypted.</li>
                <li>Passwords are stored only as one-way hashes, never in readable form.</li>
                <li>
                  Every request is checked so people only see the classes and students they belong
                  to.
                </li>
                <li>
                  Uploaded files are checked to be the type they claim to be and stored under names
                  we generate.
                </li>
                <li>
                  The AI is instructed to treat everything in a student's work as content to mark,
                  never as instructions.
                </li>
              </ul>
              <p>
                If a breach puts personal data at risk, we will tell the relevant authorities within{" "}
                <strong>72 hours</strong> of becoming aware of it where the law requires, and tell
                the people affected — and, for students, their parents or guardians — without undue
                delay.
              </p>
            </Section>

            <Section id="cookies" title="Cookies and storage on your device">
              <p>avora stores only what it needs to keep you signed in:</p>
              <Table
                head={["Name", "Type", "Purpose", "How long"]}
                rows={[
                  [
                    "Sign-in cookie",
                    "Cookie, only readable by avora's server",
                    "Keeps you signed in between visits",
                    "Up to 30 days, or until you sign out",
                  ],
                  [
                    "Session token",
                    "Browser storage",
                    "Proves you are signed in on each request",
                    "Until you sign out",
                  ],
                ]}
              />
              <p>
                Both are strictly necessary for a service you asked for, so they don't need a
                consent banner. avora uses <strong>no</strong> analytics, advertising or tracking
                cookies.
              </p>
            </Section>

            <Section id="changes" title="Changes and contact">
              <p>
                If we change this policy in a way that matters, we will tell tutors and parents
                before the change takes effect, and ask for consent again where the law requires it.
                An Arabic version of this policy will be published before launch in the Gulf.
              </p>
              <p>
                Questions or requests: <Contact />.
              </p>
            </Section>
          </article>
        </div>
      </div>
    </PublicPage>
  );
}
