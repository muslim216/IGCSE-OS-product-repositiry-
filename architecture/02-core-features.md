# 02 — Core Features

*What the product actually does, surface by surface.*

---

## The six surfaces

Avora is built as six connected areas. The internal shorthand is that **the platform is the product** — AI improves every one of these, but none of them *is* the AI.

| Surface | In one line |
|---|---|
| **Student CRM** | The complete, always-current academic record of one student |
| **Lessons** | The dated teaching event — what was taught, to whom, and what the tutor noticed |
| **Readiness** | How ready each student is for the exam, per topic, with a predicted grade |
| **Knowledge Base** | The tutor's own teaching knowledge, fed into every AI feature |
| **Homework** | Booklet → questions → submission → marking → review → evidence |
| **Reports** | Written progress narratives, tailored to who's reading |

The rest of this document walks through each.

---

## 1. Homework — the workhorse

This is the feature tutors use daily, and the one that generates almost all the data everything else depends on.

### Setting homework

A tutor uploads a PDF — typically a **classified**, which in IGCSE tutoring means a compilation of past-paper questions grouped by topic. They can optionally upload the official mark scheme alongside it.

In the background, AI reads the document and pulls out the individual questions: question number, marks available, which syllabus topic it belongs to, and how difficult it is. The tutor reviews the list, adjusts anything wrong, and publishes it to a class.

That's the whole flow. Drop in a PDF, publish. No manual typing of questions.

Homework can also be created without a PDF at all, for a tutor who just wants to set something quickly.

### Submitting

Students open the assignment on their phone, photograph their handwritten work — several pages if needed — and submit. PDFs work too.

This is intentionally the lowest-friction part of the product. Students already do their work on paper; the product doesn't ask them to change that.

### Marking

AI marks the submission **question by question**, comparing each answer against the official mark scheme where one was uploaded. For every question it produces a mark, a short piece of feedback, and — critically — **how confident it is.**

What happens next depends on that confidence. This is the most consequential design decision in the product, and it's covered in detail in [04 — The AI layer](04-the-ai-layer.md). The short version:

- **Confident, and checked against an official mark scheme** → the mark counts immediately. The student sees feedback within minutes.
- **Anything else** → it waits in the tutor's review queue with the AI's suggestion already filled in.

So a tutor with thirty students doesn't review three hundred questions. They review the twenty that were genuinely ambiguous.

### Review and appeal

The tutor sees the student's work and the AI's marking side by side. They can change any mark. Every change is permanently recorded — old value, new value, who changed it, when — in a log that **has no way to be edited or deleted, by anyone, including the tutor.**

Students can contest any finalised mark. The request goes to the tutor with the AI's original reasoning attached, and is **never** re-decided by AI. One appeal per question, ever, enforced by the database itself so the queue can't be spammed.

### Past papers

Full past papers work through the *exact same pipeline*. No separate code, no parallel system — a past paper is treated as the same kind of thing as homework, so marking, review, appeals and evidence-building all apply automatically.

The only difference is that students self-report how they sat it: when, whether it was timed, and how long they took. The platform can't observe any of that, so **wherever those figures appear they're labelled as self-declared.** That's a deliberate rule — presenting a self-reported "timed" attempt as if it were observed would misrepresent the strongest evidence in the entire scoring system.

The distinction between classifieds and full past papers matters more than it looks. Classifieds are what students practise on for most of the year; full papers start late. So early in the year, readiness legitimately runs on classifieds alone, and the past-paper component honestly reports "no data" rather than dragging the score down.

---

## 2. Readiness — the differentiator

Every mark a student ever gets feeds a **readiness score**: a percentage and a predicted grade, calculated per topic, per subject.

Students see where they're strong, where they're weak, and what to revise. Tutors see the same for their whole class, so they can spot that four students are all struggling with the same topic and teach it again.

This is the reason the product exists and it has its own document — [03 — The readiness engine](03-the-readiness-engine.md).

Two things worth stating here:

**The AI never assigns the grade.** It produces a score. Ordinary, predictable code converts score to grade using boundaries the tutor enters per subject — because 70% can genuinely be an A\* in one subject and not another, and no model can know a specific exam board's published boundaries.

**A topic with no evidence says so.** It reads "not enough data yet," never 0%. Showing a zero would tell a student they failed something they never attempted.

---

## 3. Student CRM — the record

Everything known about one student, in one place: their profile and school, which subjects they're taking and their target grade for each, their lesson history, their homework history, their readiness, the tutor's private notes, and a log of every parent communication.

There's an architectural detail here that's more valuable than it first appears. **The AI reads a student's record through exactly the same code the screen uses.** Not a similar query — the identical one.

The consequence: it's structurally impossible for the AI mentor to be working from a different picture of a student than the tutor is looking at. If the two used separate queries, they'd drift apart, and the AI would eventually tell a student something that contradicted their own dashboard.

---

## 4. Lessons — the spine

A lesson is a dated teaching event: what was taught, which topics were covered, notes, and per-student observations.

Marking a topic as covered in a lesson makes it **taught** for every student in that group, as of that date. That's the entire basis of syllabus coverage tracking — and there is deliberately **no way for a tutor to manually tick a topic off.**

That restriction is the point. Two sources for the same fact will eventually disagree, and when they do, the one you should trust is the one with a date and a real lesson behind it. So only that one exists.

Observations a tutor records during a lesson feed into readiness as their own kind of evidence — weighted lower than exam results, because a tutor's impression is valuable but subjective.

Homework can be attached to the lesson that set it, which is what lets the system connect "I taught this" to "and here's how they did on it."

---

## 5. Knowledge Base — the tutor's fingerprint

A tutor can record how *they* teach: preferred methods, the way they like problems solved, marking preferences, specific instructions for the AI, general notes, and reference files.

All of it is compiled into a block of context injected into **every** AI feature — marking, question extraction, reports, and student chat.

The purpose is that the AI behaves like *that tutor*, not like a generic marker. A tutor who insists on a particular method for solving simultaneous equations gets marking that respects it.

Commercially, this is the strongest retention mechanism in the product. A tutor who has spent six months teaching the system how they work has built something they'd have to rebuild from scratch to leave.

---

## 6. Reports — the parent-facing surface

AI-written progress narratives, generated strictly from the student's stored record, and **tailored to who's reading**: a report for the student, a report for the tutor, and a report for the parent are three genuinely different documents from the same underlying data.

Parents get plain language and no jargon. Tutors get detail.

Only tutors and admins can generate reports; students and parents can read them. That was tightened deliberately — report generation is one of the more expensive AI operations, so it isn't left open to every user.

---

## What each user actually sees

### Tutors — nine areas

| Area | Purpose |
|---|---|
| **Today** | The daily starting screen — today's lessons, what needs attention |
| **Classes** | Groups, each with tabs for homework, students, syllabus, schedule, resources and analytics |
| **Class readiness** | Readiness across every student, for spotting patterns |
| **Homework** | Everything set, and what needs reviewing |
| **Past papers** | Upload and manage full papers |
| **Mocks** | Enter mock exam results |
| **Syllabuses** | Upload any exam board's syllabus PDF and have the topic tree drafted |
| **Preferences** | Tune how readiness is weighted |
| **Settings** | Google Classroom connection |

### Students — eight areas

Home, Readiness, Homework, Past papers, Exams (their own results), Files, Recordings, and the AI Tutor — deliberately pinned separately at the bottom of the menu.

### Parents — one screen

A single dashboard showing progress for each linked child. Deliberately minimal.

---

## Two features that support everything else

**Syllabus upload.** Five syllabuses ship built in — Edexcel Maths, Chemistry and Biology; Cambridge Chemistry and Biology. Beyond those, a tutor can upload *any* exam board's syllabus PDF, have AI draft the topic tree, review and edit it, and apply it as a new subject.

This is what stops the product being locked to five syllabuses forever. It's the mechanism by which Avora expands to new boards, and eventually beyond IGCSE, without engineering work for each one.

**Google Classroom.** Tutors already using Classroom can link a class, then coursework and turned-in submissions can be imported into the normal pipeline whenever the tutor triggers a sync. Import is on demand today — there is no scheduled/background synchronization that pulls new Classroom work in on its own.

Two deliberate restrictions: only PDFs and images are imported — other file types are skipped rather than guessed at — and submissions are matched to students by email, with unmatched students skipped rather than guessed. Guessing wrong here would attach one student's work to another's record.

Classroom is a friction reducer, never a replacement for direct upload. Both feed the same pipeline. *(It has never been run against real Google credentials — see the weaknesses document.)*

---

## What doesn't exist yet

Designed but not built: study planner, AI quiz generator, notifications and reminders of any kind, admin console, payments, cloud file storage, email delivery, mobile app.

The absence of **notifications** is the one most likely to be felt first. For a product built around consistency and habit, there is currently no way to nudge anyone about anything.
