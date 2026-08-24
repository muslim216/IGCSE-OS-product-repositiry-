# Avora by OASIS AI — Experience Design

> **This is a design specification: the target state.** It says what the tutor, student and
> parent experiences are being built toward and why. For the system **as built** — including
> where the code has diverged from this document — read the Engineering Constitution at
> `docs/README.md`. Where the two differ they are answering different questions, but only the
> constitution tells you what your code will run against. Authority hierarchy:
> `docs/governance/documentation-authority.md`.
>
> **This document is Tier 2. It cannot override Tier 1.** Where a design decision recorded
> here would contradict a numbered volume, this document says so explicitly and proposes the
> Tier-1 change rather than asserting it. One such case exists, in §3.

This is **Phase 1: information architecture** — what each role sees, in what order, and in
what states. Phase 2, which makes those flows faster and more pleasant, has not been written
and must not alter what is settled here without an explicit new decision (§11).

---

## Contents

- [1. The problem](#1-the-problem)
- [2. The shared design contract](#2-the-shared-design-contract)
- [3. Grades, scales and states](#3-grades-scales-and-states)
- [4. Tutor](#4-tutor)
- [5. Student](#5-student)
- [6. Parent](#6-parent)
- [7. Onboarding and cold start](#7-onboarding-and-cold-start)
- [8. The precomputed narrative](#8-the-precomputed-narrative)
- [9. Contradictions with the system as built](#9-contradictions-with-the-system-as-built)
- [10. Success criteria](#10-success-criteria)
- [11. Phase boundary](#11-phase-boundary)
- [12. Appendix: rules this design would add](#12-appendix-rules-this-design-would-add)
- [13. States and copy for the screens this phase changes](#13-states-and-copy-for-the-screens-this-phase-changes-d4)

---

## 1. The problem

The goal this document serves, stated so it can be tested:

> **A tutor should never think twice about opening Avora and checking.**

The tutor's home today (`frontend/src/tutor/today/TodayDashboard.tsx`) renders four stacked
read-only sections — Teaching rhythm, Needs your review, Learner readiness, Evidence to action
— and asks the tutor to synthesise them into a judgement themselves. The single most valuable
artifact, the AI class brief, sits behind a class picker, a button, and a blocking model call
whose output is then discarded (§8). Nine navigation items compete for attention, two of which
are settings.

Nothing there is broken. It is a competent dashboard. But a dashboard asks the reader to do
the analysis, and a surface that asks for analysis is a surface you open when you have time —
which is the opposite of the goal.

The student and parent surfaces have the mirror problem in different directions. The student's
home opens with a single cross-subject percentage (`StudentHomePage.tsx:41-44`) — a standing
verdict on the person, refreshed daily. The parent has exactly one route
(`frontend/src/App.tsx:149-153`), no navigation, and a screen that presents numbers without
saying what they mean or whether anything is required.

---

## 2. The shared design contract

### 2.1 The information hierarchy

Every primary surface in Avora is ordered:

> **Verdict → Object → Explanation → Detail**

| Layer | What it is | Rule |
|---|---|---|
| **Verdict** | One sentence answering the question this surface exists to answer. | Always present, always first, always in plain language. |
| **Object** | The things the verdict is about. | The user's primary object for this role — see §2.2. |
| **Explanation** | Why the objects are in the state they are in. | Present without interaction where it fits; otherwise one disclosure away. |
| **Detail** | The evidence underneath. | Always reachable, never volunteered. |

The hierarchy is not a layout. A surface may render Explanation beside Object rather than
below it. What is fixed is the **order in which meaning becomes available**: a reader who
stops after the first line has a true answer, and every further layer only refines it.

### 2.2 Object, defined

**The Object of a surface is the thing the user is deciding about on that surface.** Not the
thing the data is keyed by, and not the thing the route is named for — the thing a decision
gets made about.

| Role | Question the home answers | Object | Verb |
|---|---|---|---|
| **Tutor** | Does anything need me? | **Classes** | Decide |
| **Student** | What do I do next? | **The task** | Do |
| **Parent** | Is my child okay? | **The child** | Understand |

This is why the three homes are not variants of one screen. A tutor deciding, a student doing,
and a parent understanding need different first objects, and a shared layout would serve one
of them at the expense of the other two.

**Visit frequency inverts two of the design goals.** A tutor opens Avora several times a day,
so opening must be *cheap* — a boring answer still has to be worth the trip. A parent opens it
a few times a term, so their screen must be *complete* — speed is worthless and a thin screen
reads as neglect. These are opposite requirements and must not be reconciled into one pattern.

### 2.3 Every screen closes its own loop

**Avora has no person-to-person messaging, and none is planned.** There is no inbox, no
thread, and no notification addressed to a human. This is a product decision, not an omission.

Operationally, it means:

1. **No surface offers an action that requires a person to respond.** No "ask your tutor", no
   "message the parent", no "request a review from" — because nothing would carry it. Offering
   a loop with nothing behind it is worse than not offering one.
2. **Every surface has a terminal state, and the terminal state is a sentence.** A screen with
   nothing left to say says so: *"That's everything."* — never a blank region, never a
   scrollable void.
3. **Absent data is stated as absent** (`PROD-2`, `UX-19`). A factor with no evidence is
   omitted; a measurement not taken is words, not `0`.
4. **The student's AI assistant is the only help available**, so it cannot use "ask your tutor"
   as an escape hatch. It either helps within its boundary (`UX-26`) or says plainly that it
   cannot.

---

## 3. Grades, scales and states

This section is the shared vocabulary. Everything in §4–§7 is expressed in it.

### 3.1 Two independent axes

Avora already models both, and this design uses both rather than inventing a third thing.

**Status** — `ReadinessStatus`, defined in
[§02](volume-1-product-and-ux/02-ux-and-accessibility-standards.md) and rendered by
`frontend/src/components/ui.tsx:62-67`:

| Value | Label |
|---|---|
| `on_track` | On track |
| `needs_attention` | Needs attention |
| `at_risk` | At risk |

**Confidence** — `ReadinessConfidence` (`backend/app/models/readiness.py:53-57`):
`none | low | medium | high`. [§01](volume-1-product-and-ux/01-product-architecture.md)
establishes that a topic with no points is `ReadinessConfidence.none` and displays as
*"not enough data yet"*.

**The fourth visible state is not a fourth status. It is `confidence = none` suppressing the
status entirely.** A subject, student or class with insufficient evidence shows no colour, no
bar and no grade — an empty marker and the words. This matters because the alternative,
adding a fourth `ReadinessStatus` member, would put "we don't know" on the same axis as "at
risk", and they are not comparable claims.

```
🟢  On track            confidence: low | medium | high
🟡  Needs attention     confidence: low | medium | high
🔴  At risk             confidence: low | medium | high
○   not enough data yet confidence: none  → status suppressed
```

> **Proposed Tier-1 change, not adopted here.** The product brainstorm that produced this
> design used the labels *Thriving · Needs Support · Needs Intervention*. Those strings exist
> nowhere in the system, and Tier 2 may not rename a Tier-1 union. This document uses the
> existing labels throughout. If the warmer wording is wanted, it is a change to §02's
> `ReadinessStatus` definition and to `ui.tsx`, proposed through
> `governance/change-process.md` — not something a design document may assume.

### 3.2 Colour derives from position, never from a threshold

Health is **grade-based**. The mapping is:

> **The top three grades in the subject's scale are 🟢. The next two are 🟡. Everything
> below is 🔴.**

Stated as an implementation-independent fact: `Subject.grade_boundaries`
(`backend/app/models/syllabus.py:20`) is an ordered list, highest grade first — this is the
contract `backend/app/services/grades.py:5-14` already relies on. The band is therefore the
**index of the returned grade within that list**: positions 0–2, 3–4, and the remainder.

Two consequences, both required:

- **No surface, style, or constant in this design contains a literal grade or percentage
  threshold.** Not `7`, not `B`, not `70`, not `50`. A subject whose scale changes, or which
  uses a scale nobody anticipated, needs no code change.
- **Numeric and letter scales are the same rule.** `Subject.grade_scale`
  (`models/syllabus.py:18`) already carries which one a subject uses, and
  `services/grades.py` already returns whatever grade *string* the boundary list holds — so
  `9 8 7 │ 6 5 │ …` and `A* A B │ C D │ …` are one implementation, not two.

```
9-1 scale     9   8   7  │  6   5  │  4  3  2  1  U
A*-G scale    A*  A   B  │  C   D  │  E  F  G  U
              🟢  🟢  🟢 │  🟡  🟡 │  🔴 🔴 🔴 🔴 🔴
              └ index 0-2 ┘└ 3-4 ┘└──── the rest ────┘
```

Where no boundaries exist for a subject, there is no grade. `services/grades.py:8-9` already
returns `"—"` in that case, which is the `PROD-2`-correct answer and must reach the surface as
*"no grade boundaries set"*, with the action that fixes it.

### 3.3 Predicted and averaging

Two different grades, both shown, and **the gap between them is the story**:

| | Derived from | Direction |
|---|---|---|
| **Predicted** | The readiness score mapped through the subject's boundaries. Weighted, recency-aware. | Forward-looking: what they are heading for. |
| **Averaging** | The plain mean of marked work, mapped through the same boundaries. | Backward-looking: what they have been getting. |

A student predicted above their average is improving faster than their history suggests; below
it, the recent work is weaker than the record. That comparison is more actionable than either
number alone, and it is the honest explanation of why a predicted grade is not a promise.

> **`averaging` does not exist today.** Every caller of `predict_grade` passes the *readiness*
> score — `services/readiness_summary.py:72`, `services/readiness_v2_ai.py:252`,
> `services/reports.py:79`. No mean-of-marked-work grade is derived anywhere in `backend/`.
> This is the one value in this document that requires new derivation rather than new
> presentation, and §9 records it as such.

---

## 4. Tutor

**Navigation: Overview · Review · Homework · Classes · Students · Mocks · Past papers ·
Readiness · Reports · Library — flat, ordered by frequency of use, plus a small Settings area
for usage (`AV-105`, `AV-113`).**

This supersedes the four-destination nav this document previously specified here (Today ·
Classes · Review · Library, `TUTOR_NAV` at `frontend/src/App.tsx:94-99`), which was itself a
reduction from a nine-destination tutor nav this document once described — the nine that now
exist in the tree are `STUDENT_NAV` (`frontend/src/App.tsx:74-88`), not the tutor's.
**`Today` is renamed `Overview`** — no other screen answers the question §4.1–§4.2 describe,
and `AV-47`, `AV-48` and `AV-101` all describe this screen's
content under the new name. Six destinations return to the top level: **Homework un-folds from
Review** (`AV-108`) — reversing the fold this document's `9.1` contradiction-tracking recorded
as a deliberate information-hiding fix, which `AV-108` now overrides; **Students** is new
top-level ground for content that lives only inside a class today (`AV-114`); **Mocks** and
**Past papers** promote out of the Library shelf; **Readiness** and **Reports** each get a tab
of their own (`AV-112`). Library keeps the rest and gains scope it did not have before
(`AV-110`, `AV-111`). `AppShell.tsx`'s existing `MAX_TABS = 4` mobile behaviour (§4.2) already
folds anything past three primary tabs into a **More** sheet — ten destinations exercises that
path for the first time; no new mobile mechanism is required.

**Screen inventory (`D.1`), reconciled against task `0.0`'s audit — every nav position, what
already exists, and what this phase adds:**

| Nav position | Backs onto | State |
|---|---|---|
| Overview | `tutor/today/TodayDashboard.tsx` | Built — a rework, not a rebuild (`9.2`) |
| Review | `tutor/ReviewQueuePage.tsx`, `tutor/SubmissionReviewPage.tsx` | Built |
| Homework | Detail lives only in the per-class `tutor/tabs/HomeworkTab.tsx` today | Partial — the top-level detail page is new; the per-class tab narrows to metadata (`AV-108`) |
| Classes | `tutor/GroupsPage.tsx` | Built |
| Students | Detail lives only in the per-class `tutor/tabs/StudentsTab.tsx` today | Partial — same shape as Homework (`AV-114`) |
| Mocks | `tutor/MocksPage.tsx`, `tutor/MockEntryPage.tsx` | Built → extend: assignment and timed sitting (`AV-115`, `AV-116`) |
| Past papers | `tutor/PastPapersPage.tsx` | Built → extend: booklets (`AV-117`) |
| Readiness | `tutor/ClassReadinessPage.tsx` + `tutor/PreferencesPage.tsx`, merging | Built → merge and extend: custom criteria, switch-off, weak threshold (`5.4`, `5.6`) |
| Reports | `components/ReportsPanel.tsx`, currently embedded rather than routed | Built → promote to a tab, rework content (`8.6`, `AV-112`) |
| Library | `tutor/LibraryPage.tsx` | Built → restructure (`AV-110`, `AV-111`) |
| Settings (usage) | `tutor/ClassroomSettingsPage.tsx`, `tutor/PreferencesPage.tsx` exist; the usage view does not | Partial (`10.2`, `AV-113`) |

`tutor/GradeBoundariesPage.tsx` and `tutor/SyllabusUploadPage.tsx` already exist as routes
outside the nav (`0.0`) — both land inside Library below rather than gaining their own tab, on
the same basis as grade boundaries and the syllabus document (`AV-110`).

### 4.1 Overview — desktop

```
┌──────────────────────────────────────────────────────────────┐
│  Your classes are running well.                              │
│  Two lessons today · three pieces to mark when you have      │
│  a moment                                          Mark →    │
│                                                              │
│  47 questions marked — roughly 3 hours of marking.           │
└──────────────────────────────────────────────────────────────┘

  Y10 Chemistry    🔴 At risk         predicted 4 avg   9/11 ●   Open →
  Y10 Biology      🟡 Needs attention predicted 5 avg   6/9  ◐   Open →
  Y10 Physics      ○  no grade boundaries set                Set them →

  On track 🟢   Y11 Chem 7 · Y11 Phys 7 · Y11 Bio 8 · Y9 Chem 7

TODAY
  16:00   Y11 Chemistry · Moles                    Before you teach ▾
  18:00   Y10 Biology · Transport in plants        Before you teach ▾

  Y10 Chemistry is 2 lessons behind its plan             Re-plan →
  Chapter 7 starts Monday — no classified uploaded yet       Upload →

WHAT CHANGED
  Quiet day. Sara's chemistry has clicked — she's on track now, and
  six pieces came in overnight.

  This week's send is out.                              Read it →

NEEDS YOU
  3 submissions waiting                                      Review →

  Weak topics across your classes: Moles (Y10 Chem) ·
  Algebraic fractions (Y10 Maths, Y11 Maths)
```

**The good-news figure is exact about what it counts and honest about what it estimates**
(`AV-101`). The **count** — `47 questions marked` — is real and traces to the auto-finalized
marks in the period, the same way every other number on this screen must (`PROD-1`). The
**time** is a derived estimate and is labelled as one: *"roughly 3 hours of marking"*. The word
**"roughly" is load-bearing** — this is the most-viewed screen in the product, and the moment
that estimate reads as a measurement it becomes a claim `PROD-1` cannot back.

**Plan progress, upload prompts and weak topics are additions from `9.2`'s compact-overview
list**, not new sections — they extend `TODAY`, `WHAT CHANGED` and `NEEDS YOU` rather than
opening new ones, because a fourth top-level block competes with the verdict for the two-second
read this screen exists to protect. A class running behind its teaching plan (`6.6`, `AV-18`)
and a chapter about to start with no classified uploaded (`6.7`, `AV-20`, `AV-22`) are both
**non-blocking prompts inside `TODAY`**, not alerts — `6.7` states this explicitly. Weak topics
aggregated across classes (`5.6`, `AV-42`, `AV-43`) sit inside `NEEDS YOU` as information; they
are never generated, assigned or suggested as work (`AV-42`), so the line names topics and
links nowhere but the Readiness tab.

**This week's send is a link into the stored artifact, not a duplicate of it** (`AV-51`, `8.4`).
The weekly send and the on-screen narrative are written by the same generator (`AV-99`) but
remain two different objects — a scheduled artifact and an always-current paragraph — so this
line points at the send rather than trying to fold its content into `WHAT CHANGED`.

**The verdict block is the primary entry point.** The whole block is one target: reading it
answers the question, and acting on it requires no second decision about where to go.

**It names classes. It never names an individual student.** A tutor opening the app to check
is not asking to be handed a struggling child; they are asking whether their teaching day is
intact. Individuals exist one level down, on the class page, where the tutor has chosen to
look (§4.3). This resolves the tension between *"the home must be positive, not
overwhelming"* and *"nothing important may be hidden"* **structurally** rather than by tone —
the home surface has no vocabulary for naming a person, so it cannot ambush anyone.

**Every class is represented, but healthy ones collapse.** A tutor with eight classes sees
three rows and one line, not eight rows. Nothing is hidden — a green class is still on screen,
with its grade — but only the exceptions take vertical space, so the strip stays a glance
rather than becoming a list.

**Each chip carries its coverage** — `9/11 ●`, `6/9 ◐`. A health state without coverage is a
claim about a class made from part of it. `12/12 ●` and `2/11 ◌` are not the same statement
and must not look alike.

**`NEEDS YOU` is absent when there is nothing in it.** Not a card reading "0", not an empty
panel with a cheerful message — the section is not rendered. This is `UX-19` applied to
composition rather than to a value. The day that ends with nothing outstanding ends visibly:

```
TODAY
  No lessons scheduled.

WHAT CHANGED
  Nothing new since yesterday.

That's everything. Enjoy your day.
```

### 4.2 Overview — phone

Same order, cut to what one hand can act on. **Not a narrowed desktop:**

```
┌──────────────────────────────┐
│ Your classes are running     │
│ well.                        │
│ Two lessons today · three    │
│ to mark            Mark →    │
│                              │
│ 47 marked — roughly 3 hrs    │
└──────────────────────────────┘

 Y10 Chem  🔴  Y10 Bio 🟡
 6 others on track 🟢

 NEXT
 16:00 Y11 Chemistry · Moles
       Before you teach ▾

 WHAT CHANGED
 Sara's chemistry has clicked.
 Six pieces came in overnight.

 3 waiting            Review →

 [Overview] [Review] [Homework] [More]
```

Dropped relative to desktop: the full lesson list (next only), the per-class grade and
coverage detail (colour only), any table, and the plan-progress/upload-prompt/weak-topic lines
from §4.1 — the phone verdict stays to what one hand can act on, and those three are one tap
away inside the class or Readiness screens they name.

**The bottom bar now shows `Overview · Review · Homework · More`, not the four-item nav this
document previously specified.** `AppShell.tsx`'s `MAX_TABS = 4` (`:20`) keeps the first three
main-nav items as tabs and folds everything else — the remaining seven of `AV-105`'s ten
destinations — into the **More** sheet (`:126-134`) once the list no longer fits in four. This
is existing, shipped logic (`components/AppShell.tsx`, delivered as PR 12) applied to the new
ten-item nav; nothing about the mechanism is new here, only which items overflow.

> **Correction to this document's own prior record.** An earlier revision of this section
> stated the bottom tab bar, the `slot`-aware overflow, and safe-area handling did not exist,
> citing `AppShell.tsx:144,159-165` and `frontend/index.html:5`. Verified against the current
> working tree while writing this phase: all three now exist —
> `components/AppShell.tsx:20,126-134,212` (`MAX_TABS`, the fits/overflow split, `pb-safe`) and
> `frontend/index.html:5` (`viewport-fit=cover`) — delivered as PR 12
> (`docs/experience-implementation-plan.md` §12). §9.2's matching row is corrected alongside
> this one.

### 4.3 A class

Where individuals finally appear.

```
Y10 CHEMISTRY                    🔴 At risk · predicted 4 avg · 9 of 11 ●

WHY
  Algebraic notation and moles are weak across the class. Three
  students have declined over the last three weeks.

NEEDS YOU
  Yusuf      6    ↓ was 8 three weeks ago
  Omar       3    ↓ declining
  Layla      4    ↓ nothing marked since the 14th

HOMEWORK  ·  STUDENTS  ·  SYLLABUS  ·  SCHEDULE  ·  RESOURCES  ·  ANALYTICS
```

**`NEEDS YOU` inside a class selects on direction, not level.** A student who has always sat
at grade 4 and is stable is not news; a student sliding from 8 to 6 is, and no threshold on
level would ever surface them. Yusuf is the case that justifies the product — invisible to a
tutor with eleven students and to any filter that sorts by grade.

Low-and-stable students are not thereby ignored: they are the reason the class carries 🔴 in
the verdict, and they are listed under **Students**. The distinction is between *what changed*
and *what is*, and only the first belongs in a section called `NEEDS YOU`.

**The class's own tab bar is `HOMEWORK · STUDENTS · SYLLABUS · SCHEDULE · RESOURCES ·
ANALYTICS`** — the six sub-tabs `GroupLayout.tsx` already renders, unchanged in number, two of
them narrowed or widened in scope by this phase:

- **Homework here shows name and metadata only** — status, due date, submission count — **and
  links through to the top-level Homework tab (§4.6) for the questions, marking and management
  detail** (`AV-108`). This is the fold reversing itself in the other direction: the detail is
  no longer hidden inside Review, but it is not duplicated here either.
- **Schedule holds the teaching plan, the lesson list, and in-person attendance capture** in
  one place (`AV-109`) — the plan's slots, the tutor's accept/edit controls (`6.4`), lesson
  pre-fill and the 15-minute reminder's revise action (`7.4`), and the attendance register for
  in-person lessons (`7.1`). A `ScheduleTab.tsx` shell already exists to build this into (`0.0`,
  Phase 6 audit row); this document does not prescribe the plan's own screen layout beyond what
  `6.1`–`6.8` already settle, because the calendar-and-slot editing surface is Phase 6's to
  design in detail against a data model this phase does not have.
- **Students, Syllabus, Resources and Analytics are unchanged in scope.** The top-level
  Students tab (§4.7) is a second, class-grouped entry point onto the same roster data, not a
  replacement for the per-class view — the same relationship Homework now has to its top-level
  tab.

### 4.4 A student

The same shape one level down — Verdict → subjects → why → evidence. A student's page is a
class page with a different object, and shares its components.

**The tutor-facing mistake rollup is added here, per topic and per chapter** (`AV-40`, `4.4`)
— aggregated the same way the readiness evidence beneath it already is, on the same page,
below the existing evidence drill-down. This is the tutor's view of the pattern; the student's
own view of their own pattern is a different screen, on their Progress tab (§5.2), never this
one (`AV-121`).

### 4.5 Review

**This surface deliberately breaks the rules the home screen follows.** Home is optimised for
a two-second visit; Review is optimised for throughput across a marking block. Calm layout
would cost the tutor real time here.

```
Reviewing 1 of 6                     Y11 Chemistry · Moles, p.2

┌────────────────────────┬──────────────────────────────────┐
│                        │  Q1  ●●●○  3/4    AI · high      │
│   [ student's pages ]  │  Q2  ●●●●  4/4    AI · high      │
│                        │  Q3  ●●○○  2/4    AI · low   ⚑   │
│                        │  Q4     remark requested     ⚑   │
└────────────────────────┴──────────────────────────────────┘

                                  [ Skip ]  [ Finalize & next → ]
```

The existing draft-seeding behaviour (`frontend/src/tutor/SubmissionReviewPage.tsx:49-61`),
which lands the AI's proposal in the tutor's own input so that agreeing is one action, is
correct and is kept. **The missing piece is traversal**: there is no next/previous control
today and the breadcrumb at `:117` returns to the assignment rather than the queue, so
clearing six submissions is six full navigation round trips.

**This surface gains no new screen, only new inputs to the same one.** A typed answer (`3.3`,
`AV-73`) and an AI-marked mock (`3.4`, `AV-26`) both reach this page through the existing
polymorphic `Submission` path — `AV-91` requires a typed answer to auto-finalize exactly like a
photographed one, so nothing here may treat it as a different kind of review. Where the
deterministic pre-marking scan (`AV-93`) has flagged a submission, that reason is one more
value the existing reason badge already renders (`REASON_LABELS`, §9.1) — not a different
badge or a separate queue.

**The tutor's mistake revision (`4.3`, `AV-38`) is edited from this same marked-work view, not
a screen of its own.** The task is explicit that it needs no prompt, no queue and no blocking
step — a tutor who disagrees with the AI's assigned category or severity changes it here, the
same motion as revising a mark, and the change writes an append-only audit row (`PROD-7`,
`AI-12`) with no further UI implied.

### 4.6 Homework

**Shows:** every assignment across every class the tutor teaches, its status through
extraction → publish → marking, the extracted question list once it exists, per-student
submission status, and the entry point into each submission's review. This is
`AssignmentDetailPage.tsx` and the per-class `HomeworkTab.tsx`'s existing detail, promoted to a
tab of its own — **the detail; the per-class tab (§4.3) is now name and metadata only and
links through to it** (`AV-108`).

**Empty state:** no assignments across any class — the terminal state names the action that
fixes it (`UX-29`), not a blank list.

**Does:** publish a drafted assignment; open a submission (which hands off to Review, §4.5, for
the marking itself); start a new one from a class's chapter (`AssignmentCreatePage.tsx`,
unchanged — homework continues to be created from classifieds, `AV-23`).

**Connects to:** the per-class Homework tab it now supersedes for detail; Review, for anything
flagged; Classes, for the class an assignment belongs to.

### 4.7 Classes

**Unchanged in content and position within the flat nav's first half.** `GroupsPage.tsx`
already shows the grid of class cards — subject, schedule, member count, a review-count badge —
plus the create-class form. Nothing in `AV-105`–`AV-122` asks this screen to change; it moves
from a four-item nav into a ten-item one at the same relative position.

### 4.8 Students

**Shows:** every class's roster, grouped by class (`AV-114`) — the same grouping the class
picker elsewhere in this document already uses, applied here as the organising structure
rather than a filter.

**Does, per `AV-114`:** invite a student to a class; remove a student; open a student's full
record (§4.4); move a student between classes; link a parent to a student.

**Empty state:** a class with no students yet shows its invite code and share action — the
same empty-room state onboarding already produces (§7.2), reused rather than reinvented.

**Connects to:** §4.4 (a student's own page) for the record itself; the per-class Students
sub-tab (§4.3), which remains the roster scoped to one class rather than being replaced by
this class-grouped view of all of them.

### 4.9 Mocks

**Shows:** `MocksPage.tsx`'s existing per-class mark-entry links and list of past assessments,
now also able to hold work the tutor has **assigned** to students rather than only work they
have hand-entered scores for (`AV-115`) — small tests, big tests and mocks are the same
surface, not three.

**Does:** type scores in directly (`MockEntryPage.tsx`, unchanged); upload student work for AI
marking through the same pipeline homework uses (`3.4`, `AV-26`, `PROD-9`); assign a mock to
students the way an assignment is set. **An assigned mock is timed from the moment the student
first opens it, on the server's clock** (`AV-116`, `3.6`) — this document does not design that
sitting screen beyond what `3.6` settles (a server-side clock, late work accepted and flagged
rather than blocked) because the timing mechanism is Phase 3's to build.

**Empty state:** no mocks recorded for a class — names the two ways to add one (enter scores,
assign work), per `UX-29`.

**Connects to:** Review, for AI-marked mock submissions; Readiness (§4.11), where mock evidence
feeds the same factor set as homework.

### 4.10 Past papers

**Shows:** `PastPapersPage.tsx`'s existing library, extended to distinguish a **single paper**
from a **booklet** — one uploaded file holding many whole papers across sessions (`AV-117`).

**Does:** upload either kind. On a booklet, an AI job extracts the list of papers inside —
session, paper number, code, page range — **using the same upload → AI draft → tutor review →
apply pattern `SyllabusUpload` already implements** (`3.5`); this document does not invent a
second review-screen shape for it, because `3.5` is explicit that none should exist. When
assigning a paper to a student, the tutor picks one from that reviewed list; a single-paper
upload skips extraction and behaves exactly as it does today.

**Empty state:** unchanged from the existing library's empty state.

**Connects to:** Mocks and Homework, wherever a past paper is assigned as work; the student's
own Past papers tab (§5.3), which reads the same reviewed list.

### 4.11 Readiness

**Shows:** the class readiness view and the readiness setup **in one tab** (`AV-112`) —
`ClassReadinessPage.tsx`'s existing `ReadinessTable` (All / Needs attention / On track) beside
`PreferencesPage.tsx`'s existing factor-weight and half-life controls, merged rather than left
as two destinations.

**Does, added by this phase:** re-weight a factor; **switch a factor off**, which omits it from
the weighted set rather than zero-weighting it (`5.4`, `AV-34`); add a **custom criterion** —
name, description, weight, scope — hand-scored by the tutor with no AI and no derivation, and
labelled as tutor-entered wherever it is shown (`5.4`, `PROD-8`, `UX-20`); set the **weak-topic
threshold** (`5.6`, `AV-74`), captured first at onboarding (§7.1 step 8) and editable here
afterwards, on the same account-with-subject-override precedence as the rest of this
configuration (`AV-35`). This document does not lay out the custom-criterion form beyond the
fields `5.4` names, because no field beyond that list is settled anywhere in the plan.

**Empty state:** unchanged — a class or student with no evidence still reads *"not enough data
yet"* (`PROD-2`, `UX-19`), which `5.5`'s existing cold-start behaviour already produces.

**Connects to:** §4.3 (a class) and §4.4 (a student), where the same readiness values surface
in context; Library (§4.13), where grade boundaries — a different, tutor-entered input this tab
does not own — are set.

### 4.12 Reports

**Shows:** `components/ReportsPanel.tsx`'s existing generate/list/read flow, **promoted from an
embedded panel to a tab of its own** (`AV-112`), carrying the tutor's report — chapter and
topic breakdown, mistake patterns, plan progress and countdown, attendance — available on
demand and delivered weekly (`8.6`, `AV-53`). **This is a different document from the parent's
report** (§6.4): neither is built by filtering the other, and this tab does not attempt to
produce the parent's version.

**Empty state:** no report generated yet for a class or student — the generate action is the
terminal state, not a blank panel.

**Connects to:** a class (§4.3) or a student (§4.4), the objects a report is generated about.

### 4.13 Library

**Shows, restructured around `AV-110`'s definition of what belongs here** — every choice made
during onboarding, the uploaded material, and the classifieds — now that Mocks, Past papers and
Readiness have their own tabs and no longer sit on this shelf:

- The syllabus document and its chapter/topic tree, via the existing upload → review → apply
  flow (`SyllabusUploadPage.tsx`, extended per `2.3` to edit two levels).
- Teaching guidance, the second per-subject document (`2.5`, `AV-10`).
- Grade boundaries (`GradeBoundariesPage.tsx`, already built) — set here because they are an
  onboarding choice (§7.1 step 5), not because any `AV` decision names this tab explicitly.
- Classifieds, chapter-scoped (`3.1`, `AV-20`).
- **The "AI marking agreement"** — the per-subject marking rules, in the tutor's own words,
  read and edited here (`AV-111`). It describes **how** the AI marks, never **when** a mark
  counts (`AV-111` restates that `AV-25` is unchanged) — this tab has no control over
  auto-finalization.
- Mistake categories — the tutor-owned list seeded at onboarding (§7.1 step 7), accepted,
  edited or replaced here afterwards (`4.1`, `AV-39`).

**Does not** hold: usage (moved to its own settings area, §4.14, `AV-113`); Mocks, Past papers
or Readiness (promoted to their own tabs).

**Connects to:** onboarding (§7.1), where every item on this shelf is first set; the class and
subject screens that consume each one.

### 4.14 Settings and usage

**A small area, separate from Library** (`AV-113`) — account-level configuration that is not a
choice about a subject or a class: the organization and per-user time zone
(`TimezoneSetting.tsx`, `MyTimezoneSetting.tsx`, already built, `0.7`), and channel-level
notification opt-outs once push exists (`8.7`).

**Adds the tutor's own usage view** (`10.2`, `AV-2`): AI spend — rolled up per account from
`ai_usage_events`, which already meters every call — alongside students and classes, storage
used, and activity, each rolled up per account from its own existing source rather than from
`ai_usage_events`, which meters AI calls only. **Never invents a price** — a model with no
pricing entry reports as `unpriced_call_count`, never `$0` (`AI-17`); this tab shows exactly
that distinction rather than papering over it.

**Connects to:** nothing downstream — this is a leaf, consistent with `AV-113` describing it as
small and separate.

---

## 5. Student

**Two surfaces, as for the tutor, but split differently: a phone check and a laptop session.**
The phone answers *what do I need to do*; the laptop is where work is actually submitted, past
papers are sat, and progress is read properly.

**Navigation: Home · Homework · Mocks · Past papers · Progress · Materials** (`AV-106`) — six
destinations, down from the nine the current build actually renders: `Home`, `Progress`,
`Improvement`, `Homework`, `Past papers`, `Exams`, `Files`, `Recordings`, plus `AI Tutor` in the
bottom slot (`frontend/src/App.tsx:74-88`; this corrects an earlier revision of this line,
which named destinations — `Work`, `Ask` — the current build does not use). Reconciling nine
against `AV-106`'s six is forced, not chosen, once each of the three deletions and mergers this
plan already settles is applied:

- **`AI Tutor` is deleted** (`0.3`, `AV-57`, `AV-100`) — already gone from the target.
- **`Improvement` folds into `Progress`**, not dropped — this document's §5.2 already put the
  leaderboard inside Progress before `AV-106` existed to confirm it; the two were never meant
  to be separate destinations.
- **`Exams` and `Homework` map onto `Mocks` and `Homework`** — `Exams` is exactly the mock/test
  scores `AV-115` folds into the Mocks tab; `Homework` keeps its name and destination.
- **`Files` and `Recordings` merge into `Materials`** — the only pair left unaccounted for once
  the other seven are placed, and the only unclaimed name in `AV-106`'s list is `Materials`.
  This document records that mapping as the one forced reading of the settled list, not as a
  new decision about what belongs there: the merged tab's content is exactly the union of what
  `FilesPage.tsx` and `RecordingsPage.tsx` already show, grouped by class as they are today.

Six still do not fit a phone tab bar on their own once `More` is accounted for — the same
`MAX_TABS = 4` mechanism as the tutor's (§4.2) keeps `Home`, `Homework` and `Mocks` as tabs and
folds `Past papers`, `Progress` and `Materials` into the sheet.

### 5.1 Home

```
┌────────────────────────────────────┐
│  Chemistry 74 ↑     Biology 71 →   │
│  Physics   68 ↑     Maths   48 ↓   │
│                                    │
│  Two things to do today.           │
│  Chemistry mock in 12 days         │
│                                    │
│  DO ───────────────────────────    │
│  Chemistry · Moles, p.2            │
│  due tomorrow            Start →   │
│  Biology · Transport               │
│  due Friday              Start →   │
│                                    │
│  YOU DID ──────────────────────    │
│  ✓ Physics marked — 14/18          │
│    highest in your class on this   │
│  ✓ Chemistry up 6 this month       │
│                                    │
│  NEXT ─────────────────────────    │
│  Chemistry · today 16:00           │
│                                    │
│  This week's send is out.   Read → │
└────────────────────────────────────┘
```

**The weekly send appears here the same way it appears on the tutor's home** (§4.1, `AV-51`,
`8.4`) — a link to the stored artifact, not a duplicate of `YOU DID`. It is the student's own
week, written by the same generator as every other narrative in the product (`AV-99`).

**The home always answers "what do I do next?"** — `DO` is the object, and it is never below
the fold on any supported viewport.

**Every subject value is paired with its direction.** `Maths 48 ↓` describes a situation that
can be acted on. `Maths 48` alone is a label on a person. The pairing is not decoration; a
score rendered without direction is a different and worse message.

**The cross-subject average is removed.** `StudentHomePage.tsx:41-44` currently averages
subject scores into a single "Overall readiness" figure. It is an unweighted mean across
subjects with different scales, different coverage and different boundaries — arithmetically
meaningless — and it is the first thing a student sees every day. Readiness is a per-subject
concept and is presented as one.

**`YOU DID` precedes any request for work.** This is the reward-before-request ordering: a
student who opens the app is shown what they achieved before they are shown what remains.

**Peer comparison is an achievement event, never a standing.** *"Highest in your class on this
paper"* is a thing that happened on a particular day; its absence on an ordinary day carries
no message. A persistent rank — *"you are above the class average"* — inverts that: once a
student learns the app displays their standing, the standing's disappearance becomes the
message, and the students most affected are the ones the product most needs to keep.

### 5.2 Progress

```
CHEMISTRY

  Predicted     7      ↑ up from 6
  Averaging     6

  You're tracking above your recent average — the last three
  pieces have been stronger than the ones before.

CLASS PROGRESS — THIS MONTH
  1   ▲ +11    Student
  2   ▲ +9     Student
  3   ▲ +6   ← you
  4   ▲ +5     Student
  5   ▲ +4     Student

WHY
  Moles              5 of 6 marks recently
  Rates              3 of 8
  Electrolysis       not enough data yet

WEAK TOPICS
  Moles — below your tutor's threshold for this subject

ATTENDANCE
  11 of 12 lessons this term

YOUR MISTAKES
  Sign errors        4 times, mostly in Moles
  Missed units       2 times

EVIDENCE ▾
```

**This tab now carries everything `AV-121` names**: readiness, predicted grade, weak topics
and attendance, alongside the mistake pattern that supersedes `AV-41`'s original placement in
the homework tab. All four are additions to the existing Predicted/Averaging/WHY shape, not a
redesign of it.

**Weak topics are shown as information, never as assigned work** (`5.6`, `AV-42`, `AV-43`) — a
topic below the tutor's own threshold, named and nothing more; nothing here proposes practice
or generates a task.

**Attendance is not a readiness factor and carries no colour** (`AV-33`) — it explains gaps in
the evidence above it; it does not score them.

**The mistake pattern is the student's own view of the same rows the tutor sees rolled up on
their profile** (§4.4, `4.4`, `4.5`, `AV-40`) — the task names only "their own pattern" as what
the student sees; this document does not add or withhold any field beyond that, and any further
detail is left to whoever builds `4.5` against the rollup `4.4` produces.

**The leaderboard ranks improvement, not attainment.** An attainment ranking has one winner
and eleven losers, the order barely moves across a year, and the student at the bottom in
September is the student at the bottom in May. An improvement ranking resets monthly and can
be won by anyone — including, and especially, the weakest student in the room. This is the
same *progress-as-positive-reinforcement* principle the rest of the design rests on, pointed
at the mechanic that usually violates it.

Two conditions gate it:

- **Fewer than five students in the class: the leaderboard is not shown.** Below that,
  "anonymous" is a formality — students compare marks aloud and reconstruct the order within
  a day. The personal progress line is shown instead.
- **Insufficient coverage: the leaderboard is not shown.** Ranking the three students who
  have evidence out of twelve is not a ranking (`PROD-2`).

### 5.3 The cleared state

```
│  You're clear. Nothing due.        │
│                                    │
│  YOU DID ──────────────────────    │
│  ✓ 4 pieces marked this week       │
│  ✓ Chemistry up 6 this month       │
│                                    │
│  IF YOU WANT ──────────────────    │
│  Sit a past paper       Browse →   │
```

**The offer is a past paper, and only a past paper.** There is no practice, quiz or revision
generator in `backend/` — verified across `backend/app/api/` and `backend/app/services/`. The
only self-directed work a student can start is sitting a past paper
(`frontend/src/student/SitPastPaperPage.tsx`, routed at `App.tsx:144`). A cleared state that
offered "practise this topic" would be offering a control with nothing behind it, which §2.3
forbids.

### 5.4 First sign-in

One orientation screen, then the app. A student arrives by invite code into a class a tutor
has already configured, so there is nothing for them to set up — but there is one thing they
must be told before they meet it.

The screen states what the AI assistant does and does not do: it explains concepts and works
through method, and it does not supply answers to work currently assigned to them. `UX-26`
requires that framing on student surfaces; stating it once, deliberately, at the start is
materially better than letting a student discover it as a refusal at 11pm, because the
boundary then reads as design rather than as an obstacle.

### 5.5 Homework

**Shows:** `HomeworkPage.tsx`'s existing assignment list with status badges (Not started /
Submitted / Being marked / Marked) and due labels, unchanged in shape.

**Does, extended by this phase:** submit a photograph or PDF of an answer, as today, **or type
an answer directly** (`3.3`, `AV-73`) — the pipeline takes text wherever it takes images, on
the same submission screen (`SubmitHomeworkPage.tsx`). **No feedback is shown while the student
is still working**; marks and feedback appear only once they submit (`AV-92`) — this document
does not describe an in-progress feedback state because `3.3`'s security criteria explicitly
forbid building one. A typed submission auto-finalizes exactly as a photographed one does
(`AV-91`); nothing on this screen distinguishes the two once marking is complete.

**Connects to:** Progress (§5.2), where a finalized mark's evidence and any mistakes it
produced eventually surface.

### 5.6 Mocks

**Shows:** the merged Exams/Mocks content (§5's nav mapping above) — scores the tutor has
entered directly, and assignments the student is meant to sit.

**Does:** open an assigned mock and start it. **The clock starts on first open and runs
server-side** (`AV-116`); a client-side display is a convenience, not the limit. Submitting
after time is up is **accepted, not blocked**, and is flagged rather than hidden (`AV-116`) —
this document does not specify the exact wording of that flag, which belongs with the copy pass
for the screen that builds it (`3.6`).

**A measured mock is not self-declared and must not be labelled as such** — the past-paper
`timed` flag it replaces on that surface is self-declared and does carry that label (`PROD-8`,
`UX-20`); `3.6` is explicit that the two must not be visually conflated, so this tab's timer
state and a past paper's self-declared one are different UI, not the same badge with different
data behind it.

**Connects to:** Review, for AI-marked mock submissions; the tutor's Mocks tab (§4.9), where
assignment happens.

### 5.7 Past papers

**Shows:** `PastPapersPage.tsx`'s existing browsable cards (session, paper number, marks,
duration), and `SitPastPaperPage.tsx`'s existing sitting flow — booklet link, attempt log (date,
timed, minutes), answer upload, poll for marking. Both are unchanged by this phase; the booklet
extraction (§4.10, `3.5`) happens on the tutor's side before a paper reaches this list.

**Reasserts the existing self-declared labelling** (`PROD-8`, `UX-20`) that already applies
here: `timed` and `time_taken_minutes` on a past-paper attempt are the student's own account,
not a measurement, and must read as such — the distinction §5.6 draws against the new measured
mock timer applies in the other direction here.

### 5.8 Materials

**Shows:** the union of `FilesPage.tsx` and `RecordingsPage.tsx` — tutor-shared files and
lesson recording links, grouped by class, under the one name `AV-106` gives this destination.
Neither screen's content changes; they are presented together rather than as two tabs.

---

## 6. Parent

**Four tabs: Overview · Progress · Attendance · Reports** (`AV-107`) — this reverses what this
document previously specified here (one screen, no navigation) on the strength of a settled
decision that post-dates it. The invite link is still single-use and already identifies the
child (`SEC-13`), so the parent still lands directly on Overview with no intermediate explainer
— only the destinations after that first screen are new.

**Every field below already belongs to the parent role under `AV-46`, unchanged, and `AV-64`,
the parent-report content list — this phase distributes existing content across four tabs; it
adds no field to what a parent may see.** `AV-46` names exactly three things: the weekly send,
readiness and predicted grade, and attendance. `AV-64` names what the parent's *report*
additionally carries — an attendance and homework record — and, as pointedly, what it does
**not**: the chapter/topic breakdown and mistake patterns that appear on the tutor's and
student's own screens (`CLAUDE.md`'s "Deliberate difference — do not harmonise" callout exists
for exactly this gap). Because the weekly report itself is barred from topic-level or mistake detail,
no in-app tab may show the parent more than the report does; the split below is a
redistribution of the one screen's existing content, not new depth.

### 6.1 Overview

```
Sara — Year 11

Sara is on track in 3 of her 4 subjects.
Based on 34 marked pieces · updated weekly

HOW IT'S GOING
  Sara's chemistry has moved up steadily this month. Maths is
  the one to watch — it's been the sticking point across three
  pieces of work, and it's on her tutor's plan for this week.

WHAT YOU CAN DO
  Nothing is needed right now. We'll tell you if that changes.
```

**Hierarchy: child state → narrative → what you can do.** The first sentence still answers the
question the whole role exists to answer; the subject-by-subject detail that used to sit
between the verdict and the narrative moves to Progress (§6.2), where it has its own tab rather
than being read past on every visit. **The narrative itself names no chapter or topic** — `AV-99`
makes it the same generated text as the weekly send, and `AV-64` bars the send from the
chapter/topic breakdown, so the narrative stays at the level "chemistry" and "maths," never
"moles" or "algebraic fractions."

**`WHAT YOU CAN DO` is required, including — especially — when the answer is nothing.** A
parent visits rarely, cannot act on most of what they see, and reads ambiguity as bad news
that then lands on the child. A screen that ends without saying whether anything is required
manufactures the anxiety it exists to prevent.

> **Proposed, not accepted — tutor review of the parent narrative.** The narrative is
> AI-written and carries no byline (§8). `PROD-7` establishes that the tutor has final
> authority over everything the AI produces. A paragraph about a named child, shown to their
> parent, with no human ever having read it, is the highest-stakes generated text in the
> product. The proposal is that the tutor sees it on the class page before the parent does,
> with one control to edit or suppress — a veto, not a writing obligation. **This has not been
> agreed and is recorded here as an open decision**, not as part of the design.

### 6.2 Progress

```
  Chemistry     On track          predicted 7 · averaging 6    ↑
  Biology       On track          predicted 6 · averaging 6    →
  Physics       On track          predicted 7 · averaging 7    ↑
  Maths         Needs attention   predicted 4 · averaging 4    ↓
  Geography     not enough data yet
```

**The per-subject rows this document previously placed inline on the single screen, given a
tab of their own.** Nothing is added beyond what `AV-46` already grants — readiness and
predicted grade, per subject. **Predicted and averaging are both shown and visibly
distinguished** (§3.3): a parent who sees only a predicted grade reads it as a forecast the
school is committing to; seeing it beside the average makes it legible as an estimate that
moves. **No per-homework or per-topic detail** — `AV-64` withholds the chapter/topic breakdown
from the parent's report, so this tab, which may show no more than the report, withholds it
too. Aggregates and direction only; per-piece results turn the parent screen into a
surveillance surface the student can feel, which damages the relationship the tutor depends on.

**`not enough data yet` is a first-class state here, not an edge case.** A newly linked parent
will see mostly that, and the tab must look deliberate in that condition.

### 6.3 Attendance

**Shows:** the child's attendance record — the same fact `AV-46` already grants the parent day
to day and `AV-64` includes in their weekly report, given its own tab per `AV-107` rather than
folded into Progress. **Not a readiness factor and carries no colour** (`AV-33`); it explains
gaps in the Progress tab's evidence, it does not score them — the same relationship it has to
readiness on the student's own Progress tab (§5.2).

### 6.4 Reports

**Shows:** the parent's weekly sends — *"Earlier reports ▾"* from the original single screen,
now a tab of its own. **This is the parent's report in full, and it is one artifact, not two**
(`AV-63`): fixed facts (readiness, predicted grade, attendance, and — only here, not on
Progress or Overview — a homework record) plus the one AI paragraph, composed by the same
writer that produces the on-screen narrative (`AV-99`, `8.2`, `8.3`). **This is a different
document from the tutor's report** (§4.12); neither is built by filtering the other (`AV-64`).

---

## 7. Onboarding and cold start

This is the surface that determines whether any of the preceding matters, because a tutor who
finds an empty product on day one does not return to see it fill.

### 7.1 The actual flow

**Superseded by `9.1`: onboarding becomes a blocking, step-by-step flow the tutor must
finish**, reaching an accepted teaching plan before the product hands over to §4's screens
(`AV-56`, `AV-60`). This replaces the shorter flow this document previously verified against
the current implementation — subjects, a class, an invite code, everything else optional at
step 5 — which described the product before the phases below exist. The eleven steps, in the
order `9.1` fixes:

```
 1  Language, time zone, weekly send day        (pre-filled default)
 2  Subject — exam board and level
 3  Syllabus upload, then review the chapter/topic tree
 4  Teaching guidance upload
 5  Grade boundaries
 6  Per-subject marking rules              — offered, skippable
 7  Mistake categories — accept, edit or replace the suggested list
 8  Weak-topic threshold
 9  Class — one subject
10  Exam date, lessons per week and length, past-paper start, holidays
11  Accept the teaching plan                        — the finish line
```

**Server-side state, resumable, and not skippable up to step 11** (`9.1`) — a frontend gate is
never an authorization control (`SEC-10`), so what this list marks as required is enforced by
what the backend allows next, not only by what the screen shows. **Step 6 is the one named
exception**: per-subject marking rules are offered and may be skipped (`AV-75`, `AV-87`); every
other step is not.

**Tutors still create classes; students still attach themselves to one**, now at step 9 rather
than step 2. `InviteKind.student_join` carries a `group_id`
(`backend/app/api/auth.py:181-184`), and student signup calls
`_add_to_group(db, invite.group_id, …)` at `:230`. A tutor cannot create a student record.

**Adding students is optional and sits outside the flow** (`AV-60`) — this document's earlier
conclusion, that no design may assume students exist when a tutor finishes setting up, still
holds without amendment; only where it applies has moved, from step 2 to step 9, and the empty
room below now follows step 11 rather than step 3.

**Grade boundaries still ship pre-filled**, now named explicitly as step 5, with published
standard values per subject and scale, and the tutor adjusts them. The alternative — requiring
a tutor to type every boundary for every subject before anything works — puts a data-entry wall
in front of a stranger. Where defaults have not been confirmed by the tutor, that is a fact the
interface may state; it is not a reason to withhold the grade.

**This document records the order and what each step collects, not the interaction design of
getting through it.** Step 3's chapter/topic review is the existing `SyllabusUpload`
draft-then-review pattern, extended per `2.3`; step 7's suggested category list and step 8's
threshold value are `4.1`'s and `5.6`'s to specify beyond what §7.1 names. Eleven steps behind
one blocking flow is new ground for the product, and this phase does not draw the screen for
any one of them beyond what `9.1` and the phase owning that step's data already settle.

### 7.2 The empty room

Once step 11 is accepted and the invite is shared, the tutor has a configured class — with an
accepted teaching plan behind it — and nobody in it. **The correct surface here is not a
dashboard.** Readiness is computed from marked evidence; there is none; every panel would
honestly and correctly render "not enough data yet", and a screen of empty circles reads as a
broken product rather than a new one.

```
Y11 CHEMISTRY
  3 of 12 joined                    MNRA-4K7Q     Share again →
  Sara · Omar · Layla

  Readiness appears once you've marked their first work.
```

This is a state that **changes between visits** — which is the whole requirement. It gives a
new tutor a reason to open Avora tomorrow, during the exact window in which the product can
otherwise show them nothing.

### 7.3 Seeding and decay

Once students have joined, the tutor may give Avora a starting point rather than waiting
weeks for evidence to accumulate: entering recent mock results, or uploading already-marked
homework.

Where a tutor supplies their own assessment of a student rather than marked work, it is
**self-declared** and `PROD-8` requires it to be labelled as such wherever it is shown. It
seeds readiness and then **loses weight as marked evidence arrives** — the product
self-corrects within weeks rather than carrying a first impression indefinitely.

Any such input is an evidence source and is subject to `PROD-10`: it is added to
`EvidenceSource` and given a weight in `SOURCE_WEIGHTS` in the same change. **This document
does not name a new mechanism** — it states the requirement the existing mechanism must
satisfy.

---

## 8. The precomputed narrative

Two surfaces carry AI-written prose: `WHAT CHANGED` on the tutor's home (§4.1) and
`HOW IT'S GOING` on the parent's Overview tab (§6.1).

**One writer now produces both of these, plus the weekly send (§4.1, §5.1, §6.4)** (`AV-98`,
`AV-99`, `8.3`). The narrative was not deleted, and this phase does not introduce a second
generator for the weekly artifact — the send reads the same stored rows `WHAT CHANGED` and
`HOW IT'S GOING` already read, rather than composing its own text. This keeps `8.1`'s
requirement below true for a third surface at no additional cost: the weekly send is itself a
precomputed, stored artifact, never assembled at request time. `services/narrative.py`'s
sweep-not-a-chain shape survives the merge unchanged (`CODE-13`, `E24`); this document does not
name the mechanism, consistent with the rest of this section.

### 8.1 The UX requirement

> **The narrative is present when the surface opens. No primary surface waits on a model to
> render its primary content.**

That is the entire Tier-2 requirement, and it is not negotiable for the tutor's home in
particular: the surface's reason to exist is that opening it is cheap, and a model call in the
render path destroys exactly that property. It follows that the text is **generated in advance
and stored**, and that the surface reads stored text.

Refresh, stated as a requirement rather than a mechanism:

- The tutor's narrative refreshes **when new evidence lands** for that class.
- The parent's narrative refreshes **weekly**. A parent checking twice in one week should not
  see the wording shift for no underlying reason; a month is long enough that the screen goes
  stale between visits.
- A refresh in progress **shows the previous text**, marked as updating (`UX-21`). It never
  blanks the section.
- No narrative, no evidence: the section states that, and does not render an empty block.

**This document does not prescribe the storage, the job, or the trigger.** Those are Tier-1
engineering decisions, governed by `BE-6`, `BE-7` and `BE-9`, and belong in a later change.

### 8.2 What exists today contradicts this

`backend/app/api/groups.py:237-282` implements `POST /groups/{group_id}/brief`:

- It **blocks** on `await text_complete(surface="class_brief", …)` at `:267`, inside the
  request handler.
- It **persists nothing but metering** — `record_usage(...)` at `:270-278` writes an
  `AiUsageEvent`; the generated text is returned and then discarded. Every press is a fresh
  paid call at full model latency.
- It **builds its prompt inline** at `:258-265`, which `AI-6` forbids — prompts live only in
  `services/prompts.py`, where `class_brief` is registered with an empty system string.

The frontend matches: `frontend/src/tutor/today/EvidenceToAction.tsx` puts the brief behind a
class picker and a *Prepare guidance* button, with a pending state.

**This is recorded as a contradiction of the target, not as the target.** The on-demand
endpoint remains useful as an explicit *Prepare again*; what changes is that it stops being
the only way the text can exist.

The `"Not enough evidence yet…"` short-circuit at `groups.py:245-250` is the correct
absent-state behaviour and is preserved.

---

## 9. Contradictions with the system as built

Every citation below was verified against the working tree while this document was written.
**None of these is fixed here.** Each is a later, independent pull request.

### 9.1 Experience contradictions

| Current behaviour | Target | Rule / file |
|---|---|---|
| `REASON_LABELS` holds three keys — `extraction_failed`, `ai_failed`, `ai_marked` — and is missing `needs_review`, so that reason renders on the tutor's home as a raw enum string. A rival four-key copy lives in `HomeworkOverviewPage.tsx:6-11`. | One shared map covering every reason. | `frontend/src/tutor/today/DashboardHeader.tsx:7-13` |
| The running mark total does `got += drafts[m.question_id]?.final_marks ?? 0`, so a deliberately blank question contributes a fabricated `0` to a number shown to the tutor. | A question with no mark is excluded from the total, and the total says so. | `PROD-2`, `UX-19`; `SubmissionReviewPage.tsx:98-107` |
| No next/previous control in submission review, and the breadcrumb returns to the assignment rather than the queue — six submissions cost six navigation round trips. | Queue traversal with *Finalize & next*. | §4.5; `SubmissionReviewPage.tsx:117` |
| The student home opens with a cross-subject "Overall readiness" percentage: an unweighted mean of subject scores. | Per-subject values, each paired with direction. | §5.1; `StudentHomePage.tsx:41-44,65-71` |
| Header search is labelled `aria-label="Search learners"` but filters only the readiness table — not lessons, not the review queue. | The label describes what it searches. | `today/DashboardHeader.tsx` |
| The tutor sidebar renders an "AI Guidance" link pointing at `/tutor` — the page the tutor is already on. | Removed. | `components/AppShell.tsx:112-123` |

### 9.2 Visual and design-system contradictions

| Current behaviour | Target | Rule / file |
|---|---|---|
| Purple and orange are not retargeted in `frontend/src/index.css`. Five sites render raw Tailwind palette colours on the navy surface with no token and no contrast measurement. | Semantic tokens, with cases added to `frontend/src/test/contrast.test.ts`. | `UX-2`; `student/SubmitHomeworkPage.tsx:151`, `tutor/SubmissionReviewPage.tsx:23,235,258`, `tutor/HomeworkOverviewPage.tsx:64` |
| `ParentDashboard.tsx` and `StudentHomePage.tsx` are unmigrated legacy markup — `text-slate-*`, `bg-blue-600`, `bg-white` — so the student and parent halves of the product are visually a different application from the tutor's. | Migrated to the semantic token system. | `UX-2`; `parent/ParentDashboard.tsx`, `student/StudentHomePage.tsx` |
| `ClassReadinessPage.tsx` carries its own legacy markup and a duplicated copy of the readiness thresholds. | Converged onto the shared `ReadinessTable`. | `tutor/ClassReadinessPage.tsx` |

> **Two rows closed, per `GOV-2`.** The bottom tab bar ignoring the `slot` split, and the
> missing `viewport-fit=cover`/safe-area handling, were both verified resolved while writing
> this phase — `components/AppShell.tsx:20,126-134,212` and `frontend/index.html:5` — delivered
> as PR 12. Their entries are removed rather than left to describe a state that no longer
> exists; see the correction recorded at §4.2.

### 9.3 Technical contradictions

| Current behaviour | Target | Rule / file |
|---|---|---|
| Readiness status is derived from hardcoded score thresholds — `>= 70` → `on_track`, `>= 50` → `needs_attention`, else `at_risk` — duplicated again in `ClassReadinessPage`. | Position within the subject's ordered grade boundaries. No literal threshold. | §3.2; `frontend/src/lib/readiness.ts:9-13` |
| No averaging grade is derived anywhere: all three `predict_grade` callers pass the readiness score. | A mean-of-marked-work grade, shown beside the predicted one. | §3.3; `services/readiness_summary.py:72`, `services/readiness_v2_ai.py:252`, `services/reports.py:79` |
| The class brief blocks in the request handler, persists nothing but an `AiUsageEvent`, and builds its prompt inline. | Precomputed, stored, read by the surface; prompt in `services/prompts.py`. | §8; `AI-6`; `api/groups.py:237-282` |
| `group_analytics` performs a `db.get(User, …)` plus a `TopicReadiness` select **per student** in a Python loop; `TodayDashboard.tsx:37-43` then fans that out **per group** via `useQueries`. | The tutor's home must not depend on it. | `PERF-1`; `api/analytics.py:49-58` |
| Two sources of grade boundaries: `Subject.grade_boundaries` and a `grade_boundaries` table whose comment names Subject's as "the default used by the v1 engine" — so which boundaries produce a grade depends on which engine answered. | One source, or a documented precedence. | `RISK-5`; `models/syllabus.py:20`, `models/readiness_v2.py:152-154` |

---

## 10. Success criteria

These test the Phase-1 structure, and become Phase 2's baseline.

| Role | Criterion |
|---|---|
| **Tutor** | Can determine whether anything needs their attention **immediately, without navigating** — from the first line of the home surface, on either device. |
| **Student** | Can determine **what to do next immediately** — the `DO` section is above the fold on every supported viewport, and never requires interpreting a score first. |
| **Parent** | Can understand **whether their child is okay without navigating away from Overview** — the first sentence on landing answers it, and the screen states whether anything is required of them. The criterion predates `AV-107`'s four tabs (§6); it is now read as "without leaving the landing tab" rather than "the role has no navigation at all," since the parent still lands on Overview by default and the deeper tabs are optional. |

Three structural checks apply to all three:

1. **No surface renders a missing measurement as `0`, an empty bar, or an empty panel**
   (`PROD-2`, `UX-19`). A section with nothing to report is not rendered.
2. **No surface offers a control that requires a person to respond** (§2.3).
3. **No surface contains a literal grade or percentage threshold** (§3.2).

---

## 11. Phase boundary

**Phase 1 — this document.** Information architecture: what each role sees, the object of each
surface, the hierarchy, navigation, states, and the workflows connecting them.

**Phase 2 — not yet written.** Making those flows faster, clearer, more pleasant and
lower-friction: visual language, typography, motion, the seven frictions, the emotional
contract, the signature interaction.

**Phase 2 introduces no new product features, and does not alter the information architecture
settled here without an explicit new decision** recorded through
`governance/change-process.md`. Phase 2 makes the skeleton in this document better to use; it
does not replace it. Where Phase 2 finds a Phase-1 structure that cannot be made pleasant,
that is a finding to raise — not a licence to redesign around it.

---

## 12. Appendix: rules this design would add

> **Filed.** `UX-27` … `UX-33` are now **Active** in
> [§02](volume-1-product-and-ux/02-ux-and-accessibility-standards.md), which is where they are
> read from. Two changed on the way in, and the §02 text is the one that governs:
>
> - **`UX-30`** carries D3's narrowing — the tutor's home may name a student *where naming one
>   is necessary to communicate something actionable*, never in a ranked or enumerated list.
> - **`UX-32`** was superseded rather than broken (`GOV-3`). A monthly rank is a rank, and the
>   original wording forbade the Improvement tab outright; the revision permits a student to
>   see **their own** position on a surface dedicated to it, and still forbids ever showing
>   them another student's score, grade, delta or identity.
>
> The text below is kept as historical proposal context — what was drafted here, and why —
> from before the code landed. It is not the current status of these rules; §02 is (`GOV-1`).

Written in the form defined in `governance/documentation-authority.md`. At the time this
appendix was drafted, each rule below was opened as **Draft** because it required code that
had not yet landed, with the intent to file it into
[§02](volume-1-product-and-ux/02-ux-and-accessibility-standards.md) once that code shipped.
That filing has since happened — see the note above — so the `Draft` markings below describe
that earlier moment, not the rules' status now. `UX-26` was the highest allocated ID at the
time of writing; these begin at `UX-27`.

> **`UX-27` — MUST · Important · Draft** *(as proposed; now Active — see above)*
> A primary surface opens with a single sentence, in plain language, that answers the question
> the surface exists to answer.
> *Rationale:* a reader who stops after one line must still have a true answer, or the surface
> is asking them to do the analysis themselves.

> **`UX-28` — MUST NOT · Important · Draft** *(as proposed; now Active — see above)*
> No surface, style or constant may contain a literal grade or percentage threshold; a
> readiness band is the position of the grade within the subject's ordered grade boundaries.
> *Rationale:* subjects use different scales — `Subject.grade_scale` already carries which —
> and a hardcoded `70` or `B` is wrong for every subject that does not share it.

> **`UX-29` — MUST · Important · Draft** *(as proposed; now Active — see above)*
> A section with nothing to report is not rendered; the surface's terminal state is a sentence.
> *Rationale:* `UX-19` forbids a fabricated zero in a value; the same reasoning applies to a
> panel, and an empty panel is indistinguishable from a failed load.

> **`UX-30` — MUST NOT · Recommended · Draft** *(as proposed; now Active — see above)*
> The tutor's home surface does not name an individual student; individuals appear only within
> a class the tutor has opened.
> *Rationale:* a surface designed to be opened many times a day must not be able to ambush its
> reader with a named child they did not ask about.

> **`UX-31` — MUST · Recommended · Draft** *(as proposed; now Active — see above)*
> A readiness value shown to a student is shown with its direction of travel.
> *Rationale:* a score with direction describes a situation that can be acted on; a score alone
> reads as a standing judgement of the person.

> **`UX-32` — MUST NOT · Important · Draft** *(as proposed; now Active — see above)*
> Peer comparison is shown to a student only as an achievement event, never as a persistent
> standing or rank.
> *Rationale:* once a standing is displayed, its absence becomes the message, and it is the
> students the product most needs to retain who receive it.

> **`UX-33` — MUST · Important · Draft** *(as proposed; now Active — see above)*
> Generated narrative is present when the surface opens; no primary surface waits on a model
> call to render its primary content.
> *Rationale:* a surface whose value is that opening it is cheap cannot contain a model call in
> its render path.

---

## 13. States and copy for the screens this phase changes (D.4)

`docs/experience-implementation-plan.md` set the standard this task matches: every state a
surface can be in, and the exact words it says in each (§3, §4 there). That document is
delivered — its 30 PRs are shipped — and its own screens keep the states already recorded
against them; **this section covers only the surfaces §4–§8 above add or restructure**, so the
two documents do not duplicate or drift against each other.

**The governing rules do not change.** A missing measurement is words, never `0`, `0%` or an
empty bar (`PROD-2`, `UX-19`); self-declared data is labelled as self-declared wherever shown
(`PROD-8`, `UX-20`), and so is anything hand-scored by a tutor (`AV-34`); a section with nothing
to report is not rendered, and the terminal state is a sentence (`UX-29`). Every new empty state
below is an application of these, through the existing `EmptyState` component
(`components/ui.tsx:124-140`) and the shared `ABSENT` copy map (`frontend/src/lib/labels.ts`),
not a new mechanism.

### 13.1 Copy this phase's decisions fix exactly

Two strings are settled by the product manager, not composed here — quoted rather than
paraphrased, because a paraphrase would be this document inventing wording a decision already
gave:

| Decision | Exact string |
|---|---|
| `AV-101` — the tutor home's good-news figure | *"{n} questions marked — roughly {t} of marking"* — `{n}` is the real, traceable auto-finalized count; `{t}` is a derived estimate. **"Roughly" is not optional and may not be dropped.** |
| `UX-26`, first sign-in (§5.4) | Not a literal string, but a fixed requirement on one: the screen must state, plainly, that the assistant explains concepts and works through method, and does not supply answers to work currently assigned to the student. |

### 13.2 State matrix — the genuinely new operational states

Legend: **absent** = not rendered at all · **skeleton** = the existing hand-rolled
`animate-pulse` loading pattern already used throughout `frontend/src/`. Cells not listed follow
the same loading/error handling every other async surface in the product already uses
(`UX-23`) and are not repeated here.

**Overview (tutor), §4.1 additions**

| State | Good-news figure | Plan-progress / upload prompt | Weak topics line |
|---|---|---|---|
| No auto-finalized marks in the period | absent | as applicable | as applicable |
| Marks exist | *"{n} questions marked — roughly {t} of marking"* | absent unless a class is behind or a chapter has no classified | absent unless a factor is below the tutor's threshold somewhere |
| Nothing in any of the three | all three absent | — | — |

**Mocks (tutor and student), §4.9 / §5.6 — the timed sitting state**

| State | What's shown |
|---|---|
| Not yet opened | Assigned, not started; no clock shown |
| Opened, in progress | Server-side clock running; **no feedback or mark of any kind** (`AV-92`) |
| Submitted on time | Marking in progress → marked, exactly as homework |
| Submitted after the server clock elapsed | Accepted; **flagged**, not blocked (`AV-116`) — this document does not fix the flag's exact wording, which is not settled anywhere in the plan; it states only that the flag must be visibly different from the self-declared `timed` label a past-paper attempt carries (§5.7), because the two describe different kinds of evidence and must not look alike |

**Past papers (tutor), §4.10 — booklet extraction**

| State | What's shown |
|---|---|
| Single-paper upload | Behaves exactly as today; no extraction step |
| Booklet uploaded, extraction pending | The existing `SyllabusUpload`-pattern pending state, reused rather than redesigned (`3.5`) |
| Extraction complete, awaiting tutor review | The draft list — session, paper number, code, page range — editable before it is applied, matching `SyllabusUpload`'s review screen shape |
| Extraction failed | The existing `aiUnavailable` / `loadFailed` labels in `ABSENT` apply; this is not a new failure mode |

**Onboarding (tutor), §7.1 — the eleven-step flow**

| State | What's shown |
|---|---|
| Step 1–5, 7–11 incomplete | The current step is reachable; steps after it are not — enforced server-side (`SEC-10`), not only visually |
| Step 6 (marking rules) | Reachable and explicitly skippable — the one step this applies to (`AV-75`, `AV-87`) |
| Tutor leaves and returns | Resumes at the first incomplete step; nothing already entered is lost |
| Step 11 accepted | Onboarding ends; the tutor lands on Overview, which is now in the empty-room state (§7.2) if no student has joined yet |

**Readiness (tutor), §4.11 — configurable factors**

| State | What's shown |
|---|---|
| Factor at its default weight | Unchanged from today |
| Factor switched off | **Omitted from the weighted set**, not shown at zero weight (`5.4`, `AV-34`) — the same "omit, don't fabricate" rule as an evidence-less factor (`PROD-2`), applied to a tutor's own configuration choice rather than to missing data |
| Custom criterion, scored | Shown labelled as tutor-entered, wherever it surfaces downstream (`PROD-8`, `UX-20`) |
| Custom criterion, not yet scored for a student | *"not enough data yet"* — the same `ABSENT.noEvidence` string every other unscored factor already uses; a hand-scored criterion with nobody having scored it yet is absent data like any other |

**Parent, §6 — the four-tab split**

| State | Overview | Progress | Attendance | Reports |
|---|---|---|---|---|
| Just linked, nothing marked | verdict + *"not enough data yet"* | rows, all *"not enough data yet"* | *"not enough data yet"* | absent — no send has gone out yet |
| Steady state | as §6.1–§6.4 show | as §6.2 shows | the attendance record | the list, newest first |
| Narrative refreshing | previous text + `Updating…` (`UX-21`), never blank | unchanged | unchanged | unchanged |

This table does not repeat `docs/experience-implementation-plan.md` §3.5's existing parent
state matrix, which covered the single pre-`AV-107` screen; it adds only what four tabs change
— which tab a given fact now lives on — not the facts themselves.

### 13.3 What this section deliberately leaves open

Consistent with §7.1, §4.9 and §4.11 above: where the plan does not give an exact string and no
existing `labels.ts` entry already covers the situation by direct analogy, this document does
not supply one. Naming the gap is the honest version of "matching the standard" — inventing
copy to fill it would not be.
