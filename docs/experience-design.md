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

**Navigation: Today · Classes · Review · Library.** Down from the nine in
`frontend/src/App.tsx:82-92`. Library absorbs past papers, mocks and syllabuses; Settings
absorbs Preferences and leaves the primary navigation.

### 4.1 Today — desktop

```
┌──────────────────────────────────────────────────────────────┐
│  Your classes are running well.                              │
│  Two lessons today · three pieces to mark when you have      │
│  a moment                                          Mark →    │
└──────────────────────────────────────────────────────────────┘

  Y10 Chemistry    🔴 At risk         predicted 4 avg   9/11 ●   Open →
  Y10 Biology      🟡 Needs attention predicted 5 avg   6/9  ◐   Open →
  Y10 Physics      ○  no grade boundaries set                Set them →

  On track 🟢   Y11 Chem 7 · Y11 Phys 7 · Y11 Bio 8 · Y9 Chem 7

TODAY
  16:00   Y11 Chemistry · Moles                    Before you teach ▾
  18:00   Y10 Biology · Transport in plants        Before you teach ▾

WHAT CHANGED
  Quiet day. Sara's chemistry has clicked — she's on track now, and
  six pieces came in overnight.

NEEDS YOU
  3 submissions waiting                                      Review →
```

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

### 4.2 Today — phone

Same order, cut to what one hand can act on. **Not a narrowed desktop:**

```
┌──────────────────────────────┐
│ Your classes are running     │
│ well.                        │
│ Two lessons today · three    │
│ to mark            Mark →    │
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

 [Today] [Classes] [Review] [Library]
```

Dropped relative to desktop: the full lesson list (next only), the per-class grade and
coverage detail (colour only), and any table. A phone glance that requires horizontal scanning
has failed.

> The bottom tab bar does not exist today. `frontend/src/components/AppShell.tsx:144` holds
> the only `md:hidden` in the codebase, rendering a horizontally scrolling strip of every nav
> item; `AppShell.tsx:159-165` maps the full `nav` array and ignores the `slot` split that the
> sidebar honours at `:85-86`. Safe-area handling does not exist and
> `frontend/index.html:5` has no `viewport-fit=cover`. §9 records all three.

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

STUDENTS  ·  HOMEWORK  ·  LESSONS  ·  SYLLABUS  ·  RESOURCES
```

**`NEEDS YOU` inside a class selects on direction, not level.** A student who has always sat
at grade 4 and is stable is not news; a student sliding from 8 to 6 is, and no threshold on
level would ever surface them. Yusuf is the case that justifies the product — invisible to a
tutor with eleven students and to any filter that sorts by grade.

Low-and-stable students are not thereby ignored: they are the reason the class carries 🔴 in
the verdict, and they are listed under **Students**. The distinction is between *what changed*
and *what is*, and only the first belongs in a section called `NEEDS YOU`.

### 4.4 A student

The same shape one level down — Verdict → subjects → why → evidence. A student's page is a
class page with a different object, and shares its components.

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

---

## 5. Student

**Two surfaces, as for the tutor, but split differently: a phone check and a laptop session.**
The phone answers *what do I need to do*; the laptop is where work is actually submitted, past
papers are sat, and progress is read properly.

Navigation keeps its existing destinations — Home, Work, Past papers, Exams, Files,
Recordings, Progress, Ask. Eight fit a sidebar. They do not fit a phone tab bar, which is why
the phone surface carries four plus an overflow.

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
└────────────────────────────────────┘
```

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

EVIDENCE ▾
```

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

---

## 6. Parent

**One screen. No navigation.** The parent role has exactly one route today
(`App.tsx:149-153`) and that is correct, not an omission — adding a navigation bar to a
one-screen role is decoration. The invite link is single-use and already identifies the child
(`SEC-13`), so the parent lands directly on the screen with no intermediate explainer.

```
Sara — Year 11

Sara is on track in 3 of her 4 subjects.
Based on 34 marked pieces · updated weekly

  Chemistry     On track          predicted 7 · averaging 6    ↑
  Biology       On track          predicted 6 · averaging 6    →
  Physics       On track          predicted 7 · averaging 7    ↑
  Maths         Needs attention   predicted 4 · averaging 4    ↓
  Geography     not enough data yet

HOW IT'S GOING
  Sara's chemistry has moved up steadily this month — moles and
  rates are both solid now. Maths is the one to watch: algebraic
  fractions have been the sticking point across three pieces of
  work. It's on her tutor's plan for this week.

WHAT YOU CAN DO
  Nothing is needed right now. We'll tell you if that changes.

Earlier reports ▾
```

**Hierarchy: child state → narrative → evidence → detail.** The first sentence answers the
question. The subject rows are the objects. The paragraph is the explanation. Earlier reports
are the detail.

**Predicted and averaging are both shown and visibly distinguished** (§3.3). This is where the
pair earns its place: a parent who sees only a predicted grade reads it as a forecast the
school is committing to. Seeing it beside the average makes it legible as an estimate that
moves.

**`WHAT YOU CAN DO` is required, including — especially — when the answer is nothing.** A
parent visits rarely, cannot act on most of what they see, and reads ambiguity as bad news
that then lands on the child. A screen that ends without saying whether anything is required
manufactures the anxiety it exists to prevent.

**No per-homework detail.** Aggregates and direction only. Per-piece results turn the parent
screen into a surveillance surface the student can feel, which damages the relationship the
tutor depends on.

**`not enough data yet` is a first-class state here, not an edge case.** A newly linked
parent will see mostly that, and the screen must look deliberate in that condition.

> **Proposed, not accepted — tutor review of the parent narrative.** The narrative is
> AI-written and carries no byline (§8). `PROD-7` establishes that the tutor has final
> authority over everything the AI produces. A paragraph about a named child, shown to their
> parent, with no human ever having read it, is the highest-stakes generated text in the
> product. The proposal is that the tutor sees it on the class page before the parent does,
> with one control to edit or suppress — a veto, not a writing obligation. **This has not been
> agreed and is recorded here as an open decision**, not as part of the design.

---

## 7. Onboarding and cold start

This is the surface that determines whether any of the preceding matters, because a tutor who
finds an empty product on day one does not return to see it fill.

### 7.1 The actual flow

Verified against the implementation:

```
1  Subjects, scales, boundaries
2  Create a class          →  invite code
3  Share the code
   ─────────── hours or days ───────────
4  Students join
5  Only now: optional seeding
```

**Tutors create classes. Students attach themselves to one.** `InviteKind.student_join`
carries a `group_id` (`backend/app/api/auth.py:181-184`), and student signup calls
`_add_to_group(db, invite.group_id, …)` at `:230`. A tutor cannot create a student record.

**Therefore no design may assume students exist when a tutor finishes setting up.** Any
onboarding step that asks a tutor about their students — rating them, entering their past
results, reviewing their readiness — cannot be part of steps 1–3. It belongs at step 5, after
the room has filled, and must be optional because it may never happen.

**Grade boundaries ship pre-filled** with published standard values per subject and scale, and
the tutor adjusts them. The alternative — requiring a tutor to type every boundary for every
subject before anything works — puts a data-entry wall in front of a stranger. Where defaults
have not been confirmed by the tutor, that is a fact the interface may state; it is not a
reason to withhold the grade.

### 7.2 The empty room

Between steps 3 and 4 the tutor has a configured class with nobody in it. **The correct
surface here is not a dashboard.** Readiness is computed from marked evidence; there is none;
every panel would honestly and correctly render "not enough data yet", and a screen of empty
circles reads as a broken product rather than a new one.

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
`HOW IT'S GOING` on the parent screen (§6).

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
| The mobile navigation maps the full `nav` array, ignoring the `slot` split the desktop sidebar honours at `:85-86`, and renders every item in one horizontally scrolling strip. | A bottom tab bar honouring `slot`. | §4.2; `components/AppShell.tsx:159-165` |
| `<meta name="viewport" content="width=device-width, initial-scale=1.0">` — no `viewport-fit=cover`, and no safe-area handling exists anywhere. | Both, before any fixed bottom bar ships. | §4.2, §5.1; `frontend/index.html:5` |
| `ClassReadinessPage.tsx` carries its own legacy markup and a duplicated copy of the readiness thresholds. | Converged onto the shared `ReadinessTable`. | `tutor/ClassReadinessPage.tsx` |

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
| **Parent** | Can understand **whether their child is okay without navigation** — the first sentence answers it, and the screen states whether anything is required of them. |

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
