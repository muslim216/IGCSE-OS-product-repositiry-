# Coherence pass — scoped for after Phase 7

**Status:** SCOPED, not started. Owner decision 2026-10-04: *"lets scope this for after phase 7"*.
Runs after Phase 7 (attendance) merges and before Phase 8 builds on these screens.

**Audience: agents.** Findings come from a hands-on walkthrough of the demo seed on 2026-10-04
at `8c67313` (local SQLite, no AI key — so AI-written sections were empty; those are **not**
findings). Each finding names the screen and what was observed.

## Why

Every feature works; the seams between them don't. Avora is organised around features (plan,
lessons, readiness, marking). A tutor's day is organised around moments — before a lesson,
after it, when work comes in, when a student slips. Nothing here is a new feature; it is wiring
to decisions already made (AV-105–AV-112) and to `docs/experience-design.md`.

## Findings — what a user hits

### Across roles (the biggest gap)
- **One student, three stories, same day.** Sara: tutor sees *Grade 6, Needs attention*;
  student home says *"You're clear. Nothing due."* with *70% ready*; parent sees *"Sara needs
  support in Chemistry"* followed by *"Nothing is needed right now. We'll tell you if that
  changes."* — and nothing can tell them anything until Phase 8.

### Tutor
- **Today:** *"One class could use a look"* never says why — which students, which topics.
  Clicking the class, or today's 17:00 lesson, lands on the Students tab (invites / password
  resets). 5 of 6 demo students read *Needs attention*, so the status stops discriminating.
- **Recording the lesson just taught:** the Schedule tab's *Record a lesson you taught* is
  pre-filled with the plan's next slot (Tue 6 Oct, future), not today's lesson.
- **Class tabs:** every tab repeats the full header (grade, all students, class summary); the
  chosen tab starts below the fold.
- **Readiness in three shapes:** class header = grade + status; Analytics tab = % only;
  Library → Class readiness = % + status, no grade.
- **Teaching plan ignores what's been taught.** `plan_drafting` / `plan_scheduler` never read
  `lesson_topics`; the demo class has 90 days of lessons over 1.1–1.3 and the plan restarts
  Chapter 1. Mid-year adoption is the normal case. Plan view is ~40 near-identical rows
  (chapter only, no topics, no "you are here"); plan-input fields are blank while a plan is
  accepted.
- **Student page** answers "how is she scoring", not "what's going on": no homework list, no
  recent marks, no lessons.
- **Navigation:** 4 items (Today · Classes · Review · Library) vs AV-105's ten. Library holds
  11 items mixing content, analysis (class readiness — the product's core) and setup.
- **Vocabulary:** "Upload a classified" (jargon; links to *set homework*); *Record mock or test
  marks* lives on Schedule; *AI marking agreement* in both Analytics and Library.

### Student
- Home tells what's **due**, not what to **work on**; weak topics are behind a collapsed
  disclosure on Progress.
- **Mocks** ("none set yet") and **Exams** (a *Term 1 Mock Exam* at 95/100/70%) are separate
  tabs for what a student reads as one thing.
- Files and Recordings are separate tabs; AV-106 has one *Materials*. 8 nav items vs 6.

### Parent
- One screen; no homework record (data exists), no attendance (Phase 7 provides it).
  *"Updated weekly"* with nothing sent weekly (Phase 8).

### Demo seed
- Never runs mistake tagging and generates no reports, so Phase 4 is invisible in every demo.

## Tasks (proposed — sizes are estimates)

| ID | Task | Layer | Size |
|---|---|---|---|
| C.1 | **One verdict per student** shared by tutor, student and parent — same status, same reason, same next step, worded per role | backend + frontend | M |
| C.2 | Every *needs attention* names why and links to the fix (students, topics) | frontend (+ small API) | S |
| C.3 | The lesson moment: today's lesson → one click to record it, dated today | frontend | S |
| C.4 | Plan drafting starts from what has been taught (`lesson_topics`); plan view shows topics and "you are here"; inputs show the accepted plan's values | backend + frontend | M |
| C.5 | Navigation to AV-105 / AV-106 / AV-107; Library split (readiness top-level, setup → Settings); Mocks+Exams, Files+Recordings merged | frontend | M |
| C.6 | One readiness format (grade + status + %) everywhere; class tabs drop the repeated header | frontend | S |
| C.7 | Vocabulary sweep (item list above) | frontend | S |
| C.8 | Demo seed exercises mistakes and reports | seed | S |

**Owner questions before C.1:** what drives the shared verdict (readiness status vs. grade
position vs. trend), and does the student see the same status word the parent does?

## Interaction with Phase 7

Phase 7 builds on the Schedule tab (attendance register, 7.1/7.2) and the parent screen (7.2).
Build those to the current layout; **do not pre-empt C.5/C.6** — the pass moves them.

## Status — CLOSED 2026-10-05

Owner scope (2026-10-05): change the skeletons, not the full structure; keep Classes as they are;
split Library; make the Overview informative; no mockup. C.1: the verdict is driven by readiness
status, and the student sees the same verdict in kinder wording. C.6: the full class header shows on
the landing tab only.

| PR | Item | What shipped |
|---|---|---|
| #120 | C.8 | Demo seed exercises mistakes (labelled example data), reports, attendance |
| #121 | A | Sidebar: Today · Classes · Review · Readiness · Papers & mocks · Library · Settings; old setup URLs redirect to `/tutor/settings#…` |
| #122 | C.1 | One `student_verdict()` for tutor, student, parent (neutral next step, AV-42) |
| #123 | B, C.2, C.3 | Overview: week at a glance, today's agenda, class cards, needs-you with reasons |
| #124 | C.7 | "Set homework for this chapter"; mock entry lives under Papers & mocks; "Marking rules" vs "How often you agreed with the AI" |
| #126 | C.1 | Class page learner rows show the shared verdict |
| #125 | C.6 | One readiness figure (grade · status · %) everywhere; class header on the landing tab only |
| #127 | sweep | Overview weak topics use the tutor's threshold + `weak_topic_rows`; hand-ins missing = overdue only; Readiness page keeps unbanded learners |

Deferred to Phase 9: C.4 (plan starts from what has been taught) and C.5 (full navigation rebuild).
