# MANARA — What It Is, and Where It's Weak

**A plain-English briefing for product and business decision-makers**
Written 6 August 2026 · Based on a full read of the codebase and its internal documentation

---

## A note on the name before we start

This folder is called **avora**, but the product in the repository is called **MANARA, by OASIS AI**. The word "Avora" appears nowhere in the code, the docs, the landing page, or the branding. If Avora is a rename you're considering, nothing has been renamed yet — the logo, the sign-in page, the marketing page and roughly forty documents all say MANARA.

That's a small thing to fix now and an expensive one to fix after customers have learned a name. I mention it first because it's the only weakness in this document that gets worse purely by waiting.

Throughout this document I'll call the product MANARA, since that's what everything is currently labelled.

---

## Part 1 — What the product is

### The one-sentence version

MANARA turns every piece of work an IGCSE student does into a live, explainable score of how ready they are to sit the exam.

### The slightly longer version

Private tutors teaching IGCSE have a real problem: they teach a student for a year and rely on gut feeling to answer the only question the parent actually cares about — *"is my child going to get the grade?"* Marking is slow, records live in notebooks and WhatsApp, and by the time a mock exam gives you a real answer it's often too late to act on it.

MANARA is a platform that runs the loop a tutor already works in — teach a lesson, set homework, mark it, review how it went, plan the next lesson — and keeps a running **readiness score** behind that loop. Every mark on every question feeds it. The score is per-topic, not just per-subject, so a tutor can see that a student is fine on algebra and quietly failing on trigonometry, six months before the exam tells them.

The company positions this as "an AI operating system for IGCSE teaching." That's fair. It's not a marking tool and it's not a chatbot — it's the system of record for a tutoring practice, with AI doing work at every layer.

### Who uses it

There are three audiences, and they see three different products:

**Tutors** — the paying customer. They create student groups, upload a PDF of past-paper questions, and the system pulls out the individual questions automatically. They publish it as homework, and when students submit, the AI marks it question by question. The tutor reviews only what the AI wasn't sure about. They also log mock exam results, keep notes on each student, and see analytics across their whole practice.

**Students** — they get homework on their phone, photograph their handwritten work, and upload it. They see their readiness percentage, a predicted grade, which topics are weak, what's coming up, and they can chat with an AI mentor that knows their actual record (it has guardrails against just doing the homework for them, and a daily message cap).

**Parents** — they get a plain-language view of their child's progress and written reports. Crucially, these are generated from the same underlying record the tutor sees, so there's no separate reporting for the tutor to maintain and no way for the two views to tell different stories.

### The idea that makes it defensible

The interesting part isn't the AI marking. Lots of products do AI marking. The interesting part is a design rule the team wrote down and actually enforced in the code:

> **No number exists unless the system can say exactly where it came from.**

Every readiness score traces back to specific marks on specific questions on specific dates. There's no black box. A tutor can dispute a number and follow it to its source. Two related rules fall out of this:

- **Missing data is shown as missing, never as zero.** A topic with no evidence says "not enough data yet." This sounds pedantic; it isn't. Showing a 0% because a student hasn't attempted something yet tells a parent their child failed something they never sat.
- **The AI never assigns a grade.** It produces a score; a separate piece of ordinary code converts score to grade using boundaries the tutor enters per subject. A grade is a factual claim about an exam board's published boundaries, not an opinion, so it isn't left to a model.

For a competitor to copy the marking is a weekend. To copy the explainability, they'd have to rebuild the data model.

### How it makes money (planned, not built)

The intended model: **tutors pay a subscription** covering the platform, student management, the readiness engine and an AI usage allowance. **Students who exceed their tutor's allowance buy more AI usage themselves.**

The measurement half of this is built — every AI call is metered and recorded. The charging half doesn't exist. There is no payment integration, no plans, no invoicing. Nobody can pay for this today.

### What actually works right now

Six phases are complete and working end to end:

| | |
|---|---|
| **Accounts & access** | Tutor signup, tutor-created student accounts, parent invite links, four roles |
| **Groups, syllabus, timetable** | Five built-in syllabuses (Edexcel Maths/Chemistry/Biology, Cambridge Chemistry/Biology), plus the ability to upload any exam board's syllabus PDF and have the AI draft the topic tree for tutor review |
| **The homework loop** | Upload booklet → AI extracts questions → student submits photos → AI marks → tutor reviews → finalized |
| **The readiness engine** | Evidence collection, topic scores, predicted grades, mock entry, dashboards for students and tutors |
| **AI mentor chat** | Grounded in the student's own record, with anti-cheating guardrails |
| **Parents & reports** | Parent dashboard, AI-written reports tailored to student / tutor / parent audiences |

Plus a Google Classroom integration that imports coursework and submissions.

**Designed but not built:** study planner, AI quiz generator, notifications and reminders, admin console, payments, cloud file storage, email delivery, mobile app.

### Scale, in plain terms

Roughly 12,700 lines of backend code and 9,800 of frontend, 52 database tables, 60+ screens, and about 7,300 lines of automated tests. This is a real, substantial application — not a prototype. It runs on two hosting services: the app users visit is on Vercel, and the engine and database are on Render.

---

## Part 2 — Where it's weak

**Important context before you read this list.** Most of what follows, I did not discover — the team wrote it down themselves in an internal risk register and a "known gaps" section on every document. That is genuinely unusual and it's a strength. Teams that write down their own weaknesses this honestly are rare, and it means these problems are known rather than lurking.

But writing a risk down is not fixing it. Several of these have been documented for months and are still open. I've ordered them by business consequence, not by how hard they are to fix.

### 1. Every file a student has ever uploaded could disappear, permanently

**Severity: highest. This is the one I'd act on this week.**

Student submissions, question booklets and mark schemes are stored as files on a single 10 GB disk attached to one server. The database only stores the *path* to each file — like a library catalogue that lists where a book is shelved but doesn't contain the book.

There is **no backup of that disk, no restore procedure, and nothing that checks the files still match the records.** If the disk is lost, or a deployment is misconfigured, every piece of student work ever submitted is gone — and the database will keep confidently pointing at files that no longer exist. Nothing monitors how full it is, either, so it can simply fill up one day and start failing.

For a product whose entire value proposition is "we keep a complete academic record," losing the record is not a technical incident. It's the end of the customer relationship.

The fix is well understood — move files to proper cloud storage (Amazon S3 or similar) and back it up. The code was designed to make this swap easy. It just hasn't been done.

### 2. You cannot legally sell this to a school in its current state

**Severity: highest for anything beyond individual tutors.**

MANARA stores named children's academic records, parent contact details, and photographs of student handwriting. For that data it has: no data classification policy, no retention policy, no deletion path, no data-processing agreement, and no stated legal basis for holding any of it.

The security *engineering* is genuinely good — proper session handling, revocable logins, upload validation, single-use parent invites. That's not the gap. The gap is the paperwork and process around it.

This matters commercially, not just legally. The first school or tutoring centre that considers buying will send a due-diligence questionnaire. The first parent who asks "delete my child's data" will expose that there is no mechanism to do it. Either event stops a deal cold, and both are foreseeable.

This is a founder-level task, not an engineering one, and it's on the critical path to selling to anyone larger than a solo tutor.

### 3. Two different screens can show the same student two different readiness scores

**Severity: high. Already happening.**

There are two versions of the readiness engine in the product, and both are running. The main readiness page uses the new one. Reports, analytics, and the student record page still read the old one.

So a tutor can look at a student's readiness page, see one number, open that student's report, and see a different number for the same student on the same day. Both are "correct" in that both were calculated properly — they just came from different engines.

The team's own register rates this as the highest-likelihood unresolved risk and notes it has *already materialised*. I'd rate its business impact higher than they do. The product's single differentiator is that its numbers can be trusted and explained. A tutor who catches this once will stop trusting the score, and once a tutor stops trusting the score there is no reason to pay for the product. It's not a bug in a feature — it's a bug in the value proposition.

The fix is finishing a migration that was deliberately paused. It's a known, bounded piece of work.

### 4. AI marks can be finalised and count towards a student's record with no human ever seeing them

**Severity: high, and it's a deliberate trade-off worth revisiting.**

When the AI is confident *and* has an official mark scheme to check against, the mark finalises automatically — it counts, the student sees it, and it feeds the readiness score without a tutor touching it. Everything else waits in a review queue.

This was a considered decision with sensible guardrails (marks are capped to valid ranges, blanks are never scored zero, tutors can override anything and every override is permanently recorded, students can contest any mark and a human always handles the appeal). I'm not arguing it's wrong.

Two things about it worry me:

**Nothing checks whether the AI's marking is getting better or worse.** There is no test set of known-correct marked questions run against the real AI before a change ships. So if someone edits a prompt, or the AI provider silently updates their model, marking quality can shift and nobody would find out except through students complaining. The team flags this themselves.

**Nobody is measuring whether the confidence threshold is right.** How often do tutors override an auto-finalised mark? How often do students contest one? Both numbers are sitting in the database already and neither is being calculated. Until they are, the decision to auto-finalise is running on faith.

There's also a subtler point the team handles well but which you should know exists: the student controls the piece of paper being marked. Someone could write an instruction to the AI on their homework page. The system is explicitly built to treat page content as data and flag anything that looks like an instruction — but that's a rule inside a prompt, and prompts get rewritten.

### 5. The product cannot serve more than one server's worth of customers

**Severity: medium now, high the moment growth arrives.**

Three separate design decisions each independently lock the system to exactly one server, and they'd all need fixing at the same time to grow past it: file storage is on a local disk, background processing runs inside the main application, and the login rate limiter keeps its counts in memory.

Today this is fine — the product serves a single tutor's practice. The concern is timing. This is the kind of ceiling you hit exactly when things are going well, and the work to lift it takes weeks. If a tutoring centre signs tomorrow, this becomes urgent tomorrow.

There's also no way to deploy an update without brief downtime, for the same reason.

### 6. There's no cap on AI spending

Every AI call is metered — that's the hard part and it's built. But there's **no limit, no per-customer allowance, and no circuit breaker.** A tutor who bulk-uploads a year of past papers spends whatever it spends.

Worse for planning purposes: the pricing table the system uses to calculate cost is **empty by default**, so the analytics currently report "number of unpriced calls" rather than an amount of money. As it stands, nobody can answer "what does an average customer cost us to serve" — which means nobody can price the product.

Given the business model is a subscription with an AI allowance, this needs solving before pricing does.

### 7. When something breaks, nobody finds out

The system knows when it's unhealthy. There's a health check that reports whether background work is flowing, and background jobs restart themselves if they crash.

But **nothing tells a human.** There's no alerting, no error notifications, no monitoring service watching. The system tells the truth to anyone who asks, and nobody is asking. A job that fails twice is recorded and forgotten.

In practice this means the first person to notice a problem is a student whose homework never got marked. For a product being sold on reliability of record-keeping, discovering outages via customer complaint is a poor position.

### 8. A known critical security advisory is sitting unfixed

The team ran a standard security scan on their own dependencies — apparently for the first time — and it reported **8 advisories: one critical, one high, six moderate.**

The honest mitigating context: both serious ones are in developer tooling, not in what customers actually use. They don't ship to any user. The exposure is limited to developers' own machines and the automated build system.

The reason it's still on this list: it's the only risk in their entire register whose trigger has actually *fired* rather than being anticipated, and the underlying situation is broader than two packages. There's no lockfile, so two builds of identical code can produce different results. The application container runs with maximum system privileges. Nothing scans for new vulnerabilities on an ongoing basis, which is why these two sat undiscovered for two major versions.

Adding an automatic scan is a few hours of work and would have caught this long ago.

### 9. Customer data is separated by discipline rather than by design

The system is built so multiple tutors could eventually share an organisation. Today, each tutor gets their own private organisation, and every database query is supposed to filter by it so tutors never see each other's data.

Every query currently does this correctly. The problem is *how*: there's a proper safety mechanism built for this — and it isn't used anywhere. Instead, each query filters manually, meaning the separation between one tutor's data and another's depends on every developer remembering to add one line, every time, forever. Nothing catches it if they forget.

Related: the team fixed exactly this class of problem for role permissions — moving the check somewhere it *can't* be forgotten, and adding a test that fails if anyone tries. They did the hard version and then didn't apply the same treatment one layer down.

Right now this is theoretical. If it ever stops being theoretical, it's one tutor seeing another tutor's students — the worst possible headline for this product.

### 10. The connection between the app and the engine can break silently

The visible part of the app and the engine behind it each keep their own description of what data looks like, maintained by hand, and nothing checks that the two agree.

The practical consequence: a developer renames a field, everything looks fine, all the automated checks pass, and a field on a customer's screen quietly goes blank in production. Nothing catches it before a user does. The team rates the chance of this happening as high.

### 11. The Google Classroom integration has never actually run

It's built and tested — but only against a simulated version of Google's system. It has never been connected to real Google credentials in any environment.

Nothing suggests it's broken. But "works against a mock" and "works against Google" are different claims, and only one of them has been demonstrated. It's also on-demand only: nothing syncs on a schedule, so imported work reaches readiness late or not at all unless someone presses a button.

Treat this as an unverified feature until someone connects it once.

### 12. Product gaps that will show up in the first sales conversation

Not defects — just things that aren't there yet, listed because each is a predictable objection:

- **No notifications or reminders of any kind.** No email, no push. A student is told about homework by their tutor, out of band. For a product about consistency and streaks, having no way to nudge anyone is a significant hole.
- **No mobile app.** Students photograph handwritten work on their phones — this is the single most-used action in the product and it happens in a mobile browser.
- **No payments**, as covered.
- **No admin console.** Any operational task — fixing bad data, helping a stuck customer — requires a developer with database access.
- **Single-tutor only.** A tutoring centre with six tutors cannot use this as a centre. The database is ready for it; the interface isn't.

### 13. Two operational details that look small and aren't

**Production deploys from a branch named `claude/igcse-os-planning-q8be0t`.** Both hosting services build from whatever the repository's default branch is, and the default branch is one with a name that reads like scratch work. Nothing is broken by this and the code on it is real. But there's no conventional "this is the released version" branch, which means the line between experimental and live is one settings page rather than an actual process. As soon as a second person can push code, this is how a half-finished feature reaches customers.

**A safety switch is misnamed.** A setting called `READINESS_V2_SHADOW_ENABLED` sounds like it merely turns off a duplicate background calculation. It actually reverts the entire product to the old readiness engine. Someone will eventually switch it off believing it's harmless, and silently change what every customer sees. It's a five-minute rename that nobody has done.

---

## Part 3 — What I'd do about it

If I were prioritising, in this order:

**This week — stop the bleeding**
1. Back up the uploads disk. Anything is better than nothing while the proper cloud-storage move is planned.
2. Point a free uptime monitor at the health check, so somebody learns about outages before a customer does.
3. Rename the misleading safety switch.

**This month — protect the value proposition**
4. Finish the readiness engine migration so no two screens can disagree. This is the one that protects the reason customers pay.
5. Move file storage to the cloud and back it up properly. Closes the data-loss risk *and* removes one of the three barriers to growth.
6. Add automatic dependency scanning, then fix what's outstanding.
7. Fill in the AI pricing table so you can answer "what does a customer cost."

**This quarter — before selling to anyone but individuals**
8. Write the data policy: classification, retention, deletion, legal basis, processing agreement. Founder work, on the critical path to any school or centre deal.
9. Build the AI spending caps. Needed before pricing is set.
10. Build a small set of known-correct marked questions to test AI marking against, and start measuring how often tutors override auto-finalised marks.
11. Lift the single-server ceiling — before you need to, not when.

---

## The honest bottom line

This is a well-built product with a genuinely good idea at its centre, and it is further along than most things at this stage — the feature set is complete through six phases, the code is substantial, and the documentation is better than most funded startups produce.

The weaknesses cluster in a specific and recognisable place: **everything that makes a product survivable in the world rather than impressive in a demo.** Backups, monitoring, spending limits, data policy, the release process. These are exactly the things that get deferred when one person is building fast and nothing has broken yet, and they're exactly the things whose absence stops a deal or ends a customer relationship rather than merely annoying someone.

None of them are hard. Several are hours of work. The main risk isn't any single item on this list — it's that the list is already written down, has been for a while, and hasn't been worked through.
