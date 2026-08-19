# MANARA — Experience Design Implementation Plan

> ## ⚠️ Delivered. Do not execute from this document.
>
> **PRs 1–29 of the 30 in this plan have shipped.** It is kept as the record of *why the current
> code looks the way it does* — which is genuinely useful when you are reading a surface and
> wondering what decision produced it. It is no longer a to-do list, and nobody should pick a PR
> out of it and build it.
>
> **`docs/avora-new-state-august-16.md` supersedes this document wherever the two disagree.**
> Known disagreements: the tutor navigation (four items here, ten there) · homework folded into
> Review here, un-folded there · **`D6` gives Improvement its own destination in the student nav;
> the new plan deletes Improvement entirely** · `D2`'s narrative behaviour, which the new plan
> merges with a weekly send.
>
> **The decisions in this document still bind except where the new plan supersedes them.** `D3`
> in particular — *a student's name may appear on the tutor's home only in an improvement, never
> in a decline* — is a live constraint the new plan is silent on, which means it still holds.
>
> **Decision numbers are not shared between the two documents.** `D1`–`D6` here mean entirely
> different things from `D1`–`D6` as they were originally written in the new plan; that plan's
> decisions have since been renumbered `AV-1`–`AV-122` precisely so a citation can never be
> followed into the wrong document. **A bare `D`-number always means this document.**

> **This is the delivery plan for `docs/experience-design.md`.** That document says what the
> tutor, student and parent should see. This one says how the code gets there: every state each
> surface can be in, the exact words it says in each, the pull request that builds it, the test
> that proves it, and the way back if it is wrong.
>
> **Tier 2, like the spec it serves.** It makes no product decisions. Where it names a rule it
> is citing one that exists, or one the spec filed as Draft in its §12. Where it would need a
> Tier-1 change it says so and routes it through `governance/change-process.md`.
>
> **Every file path, line number and behaviour described as current was read from the working
> tree while this was written.** Where the spec and the code disagree, the code is quoted.

---

## Contents

**Part I — What changes**

- [1. Five decisions before code](#1-five-decisions-before-code)
- [2. Surface by surface, before and after](#2-surface-by-surface-before-and-after)
- [3. The state matrix](#3-the-state-matrix)
- [4. The copy deck](#4-the-copy-deck)
- [5. Edge cases](#5-edge-cases)

**Part II — How it ships**

- [6. Shape of the delivery](#6-shape-of-the-delivery)
- [7. Stage 0 — Land the documentation](#7-stage-0--land-the-documentation)
- [8. Stage 1 — Derivation foundations](#8-stage-1--derivation-foundations)
- [9. Stage 2 — Correctness already visible](#9-stage-2--correctness-already-visible)
- [10. Stage 3 — Design-system convergence](#10-stage-3--design-system-convergence)
- [11. Stage 4 — The precomputed narrative](#11-stage-4--the-precomputed-narrative)
- [12. Stage 5 — Tutor surfaces](#12-stage-5--tutor-surfaces)
- [13. Stage 6 — Student surfaces](#13-stage-6--student-surfaces)
- [14. Stage 7 — Parent surface](#14-stage-7--parent-surface)
- [15. Stage 8 — Cold start](#15-stage-8--cold-start)
- [16. Stage 9 — Promote the rules](#16-stage-9--promote-the-rules)
- [17. Dependency order](#17-dependency-order)
- [18. Getting each PR to production](#18-getting-each-pr-to-production)
- [19. Risk register](#19-risk-register)
- [20. Definition of done](#20-definition-of-done)
- [21. Review record](#21-review-record)
- [22. Delivery record — where the build differed from the plan](#22-delivery-record--where-the-build-differed-from-the-plan)

---

# Part I — What changes

## 1. Six decisions — all settled

Two were open questions the spec records. **Four were contradictions found while reviewing the
code and the design against the spec** — a control the design assumes and the system does not
have, or a rule the spec breaks in its own mock.

**All six are decided.** The rest of this document is written to these answers.

| | Decision | Answer | Binds |
|---|---|---|---|
| **D1** | Status labels | **Keep *On track · Needs attention · At risk*.** No code change. | PR 16 |
| **D2** | Tutor and the parent narrative | **The tutor may see it. There is no approval step.** No `reviewed_at`, no `suppressed`, no review queue. Surfaced only where it is relevant, never as a task. | PRs 14, 15, 19 |
| **D3** | Naming a student on the tutor's home | **Allowed when naming them is genuinely necessary to communicate something useful.** Not restricted to positives. | PR 13 |
| **D4** | Where "today" comes from | **Store the organization's timezone.** | PR 5 |
| **D5** | The grade-boundary editor | **Ship it** — against the org-scoped `GradeBoundary` table. | PR 26 |
| **D6** | The improvement leaderboard | **Build it, on its own dedicated tab.** Not on any home surface. | PR 23 |

Each is stated in full where it binds. D2 and D3 both carry a **residual risk the decision
accepts**, recorded with the PR rather than argued here. D6 is built in the form §13 specifies,
which is not the form spec §5.2 drew — the reasons are in PR 23.

### D1 — Status labels · settled: keep the existing three

The spec (§3.1) notes the product brainstorm used *Thriving · Needs Support · Needs
Intervention*; the system uses *On track · Needs attention · At risk*
(`frontend/src/components/ui.tsx:64-68`).

| If | Then |
|---|---|
| **Keep** *(recommended)* | No code changes. |
| **Change** | `STATUS_STYLES[].label` in `ui.tsx` only. The `ReadinessStatus` **union values must not move** — they are serialized into `readiness_v2` snapshot rows and would need a data migration. §02's rule text updates in the same PR (`GOV-1`). |

**Recommendation: keep.** The current labels are already the parent's and student's vocabulary,
and warmth is a Phase-2 concern the spec explicitly defers (§11). A rename is cheap; a rename
after Stages 5–7 have spread the strings is not — so decide it, either way, before PR 15.

### D2 — The tutor and the parent narrative · settled

Spec §6 proposed the tutor reviewing the AI-written paragraph about a named child before the
parent sees it, with a control to edit or suppress.

**Settled: the tutor may see it. There is no approval step.** Concretely:

- **No `reviewed_at`, no `suppressed`, no review state on the row.** Those columns are dropped
  from PR 14.
- **No review queue, no badge, no unread count.** A paragraph waiting to be read is a task, and
  this is deliberately not a task.
- **Surfaced only where it is already relevant** — on the class page the tutor has chosen to
  open, as context, read-only. Never pushed at them.
- **The parent's copy does not wait on the tutor.** It publishes on its schedule.

> **The residual risk this accepts, stated plainly.** `PROD-7` says the tutor has final authority
> over everything the AI produces. With no suppression, if a paragraph about a named child is
> wrong, there is no in-product control that stops it reaching that child's parent.
>
> **The mitigation that is not a workflow:** `POST /groups/{group_id}/brief` already exists as an
> explicit *Prepare again*. PR 15 extends it to the parent narrative, so a tutor who reads
> something wrong **regenerates** it rather than approving it. That is a correction, not a gate —
> it adds no state to the row, no queue, and no obligation. A tutor who never opens the class
> page never encounters it.
>
> This does not fully satisfy `PROD-7`: regeneration is after the fact, and a parent may have
> already read the original. **That is the accepted cost of not having a review workflow**, and
> it is recorded here rather than left implicit. `GOV-3` requires a PR that breaks an Active rule
> to fix the code, supersede the rule, or record a Known Gap — this records the Known Gap.

### D3 — May the tutor's home name a student? · needed before PR 13

**The spec contradicts itself.** §4.1 renders:

```
WHAT CHANGED
  Quiet day. Sara's chemistry has clicked — she's on track now, and
  six pieces came in overnight.
```

while `UX-30` (Draft, §12) states *"The tutor's home surface does not name an individual
student"*, with the rationale *"a surface designed to be opened many times a day must not be
able to ambush its reader with a named child they did not ask about."*

The narrative names Sara. The rule forbids it. Both cannot ship.

**Settled: `UX-30` is narrowed, and not to "positives only".** The rule becomes:

> **`UX-30` (revised)** — The tutor's home surface **names an individual student only where
> naming them is necessary to communicate something the tutor can act on.** A student is never
> named merely to fill a sentence, and never in a ranked or enumerated list of people.

The rationale `UX-30` was written for is *ambush* — being handed a named child you did not ask
about. A useful, specific sentence about one student is not an ambush; a roster of names sorted
by who is struggling is. **The line is usefulness, not valence.** A decline may be named if
naming it is what makes it actionable.

Where this binds:

- **PR 13** encodes it as a prompt constraint in `services/prompts.py`. `AI-7` — changing it
  later bumps the version and regenerates every stored narrative, which is why it is settled now.
- **PR 18** does *not* get a mechanical test for it. This is the honest consequence: *"necessary
  to communicate something useful"* is a judgement, and **no test can assert a judgement.** The
  test that was planned — *no student name appears outside an improvement* — is deleted rather
  than weakened into something that passes vacuously.
- What replaces it: `test_home_renders_no_enumerated_list_of_named_students`, which is the half
  of the rule that *is* mechanical, plus the prompt's own version lock. The judgement half is
  enforced by the prompt text and reviewed when the prompt changes — not by CI.
- **PR 29** files the revised wording, with this reasoning, rather than the original.

### D4 — Where "today" comes from · settled: store the organization's timezone

`backend/app/api/me.py:62` computes `today_weekday = datetime.now(timezone.utc).weekday()`.
**No timezone is stored anywhere** — not on `Organization`, not on `User`; `ScheduleSlot` carries
a bare `weekday` and `start_time` with no zone.

A tutor in Cairo (UTC+3) opening MANARA at 01:00 local sees **yesterday's** lessons, because in
UTC it is still 22:00 the previous day. This is tolerable on today's dashboard, where lessons are
one panel among four. It is not tolerable on a surface whose headline sentence is
*"Two lessons today"*.

| If | Then |
|---|---|
| **Store it on `Organization`** *(recommended)* | One nullable `timezone` column, `String(64)`, IANA name, captured at tutor signup from `Intl.DateTimeFormat().resolvedOptions().timeZone`, editable in Settings. **A second migration** (`0022_org_timezone.py`). Server-side jobs can also use it. |
| **Send it per request** | No migration, but the server's answer then depends on a request parameter — which this codebase deliberately avoids (`SEC-7` reasoning) — and the weekly parent-narrative job has no request to read it from. |
| **Leave it** | The verdict line is wrong for the first *n* hours of every local day, where *n* is the UTC offset. Not acceptable for a headline claim. |

**Recommendation: store it.** This plan is written assuming the column exists; it is PR 5.

### D5 — The boundary editor · settled: ship it, against `GradeBoundary`

Spec §4.1 renders `Y10 Physics ○ no grade boundaries set → Set them →`. There is **no control
behind that link**: `backend/app/api/subjects.py` exposes only `GET ""` and
`GET /{subject_id}/topics`, and `grade_boundaries` appears nowhere in `frontend/src/` except as
a type in `api/syllabusUpload.ts:20`. Spec §2.3 forbids exactly this — *"offering a loop with
nothing behind it is worse than not offering one."*

**Where the write goes is not a matter of taste, and the obvious answer is wrong.**
`Subject` has **no `organization_id`** (`models/syllabus.py:9-25`) — subjects are global, exactly
as `SEC-8` warns. A tutor-gated `PUT /subjects/{id}/boundaries` would let one tutor change the
predicted grade of **every student of every tutor in every other organization**. That endpoint
must not exist.

The correct target already exists and is already scoped:

> `GradeBoundary` (`models/readiness_v2.py:149-161`) — *"Per-organization grade boundaries,
> manually entered by the tutor per subject at onboarding (editable in Settings) — overrides the
> shared `Subject.grade_boundaries` default used by the v1 engine."*
> `UniqueConstraint("organization_id", "subject_id", "grade_label")`.

**And it is written by nothing.** Grepping the tree, `GradeBoundary` is *read* at
`services/readiness_v2_ai.py:142-144` and written nowhere — the "editable in Settings" its own
docstring promises does not exist. So the table is empty in production, and the v2 engine
silently falls back to the global default for every organization. That is also the practical
state of `RISK-5`: there are two sources, and today only one of them ever has rows.

| If | Then |
|---|---|
| **Build the editor against `GradeBoundary`** *(recommended)* | `PUT /organizations/me/subjects/{subject_id}/boundaries`, tutor-gated, writing the **org-scoped** table. No cross-tenant surface. Delivers the control the model's docstring already promises, and gives `RISK-5` a real precedence: org override if present, global default otherwise. |
| **Write `Subject.grade_boundaries`** | **Rejected.** A cross-tenant write disguised as a settings screen. |
| **Drop the link** | The row states *"no grade boundaries set"* with no action — honest, but leaves the tutor a broken subject and no in-product fix. |

**Recommendation: build it, against `GradeBoundary`.** Without it, PR 1 can produce a subject
that permanently shows no grade and no colour with nothing anyone can do about it — and PR 1 must
in any case state which of the two sources it reads.

---

## 2. Surface by surface, before and after

### 2.1 Tutor — Today

| | Now | After |
|---|---|---|
| **First thing read** | `Good morning, {name}` + a search box | One sentence answering *does anything need me* |
| **Structure** | Four stacked read-only sections: Teaching rhythm, Needs your review, Learner readiness, Evidence to action | Verdict → class strip → `TODAY` → `WHAT CHANGED` → `NEEDS YOU` |
| **Class health** | A learner table naming individual students, lowest score first | Class rows; healthy classes collapse to one line; **no student is named** (per D3, except in an improvement) |
| **The AI brief** | Behind a class picker and a *Prepare guidance* button; blocks on a model call; output discarded (`api/groups.py:237-282`) | Already written and stored; present on open |
| **Navigation** | Nine items, two of them settings (`App.tsx:82-92`) | Four: **Today · Classes · Review · Library** |
| **Empty sections** | Render as cards saying nothing | Not rendered; the day ends with a sentence |
| **Phone** | Every nav item in one horizontally scrolling strip (`AppShell.tsx:159-165`) | Bottom tab bar honouring `slot`, with safe-area insets |
| **Queries per load** | 3 + one `groupAnalytics` per group, each of which loops per student server-side (`analytics.py:49-58`, `TodayDashboard.tsx:37-43`) | One aggregate endpoint, bounded query count |

### 2.2 Tutor — Review

| | Now | After |
|---|---|---|
| **Traversal** | None. Breadcrumb returns to the assignment (`SubmissionReviewPage.tsx:117`) — six submissions cost six round trips | *Reviewing 1 of 6* · *Skip* · *Finalize & next* |
| **Mark total** | `got += drafts[m.question_id]?.final_marks ?? 0` — a deliberately blank question contributes a fabricated `0` (`:98-107`) | Unmarked questions excluded, and the total says how many |
| **Draft seeding** | AI proposal lands in the tutor's input so agreeing is one action (`:49-61`) | **Unchanged.** This is correct and is kept |

### 2.3 Student — Home

| | Now | After |
|---|---|---|
| **First thing read** | `Overall readiness 74%` — an unweighted mean across subjects with different scales, coverage and boundaries (`StudentHomePage.tsx:41-44`) | Per-subject values, each with direction: `Maths 48 ↓` |
| **Order** | Stats → weak topics → homework → AI tutor | Subjects → *"Two things to do today"* → `DO` → `YOU DID` → `NEXT` |
| **Reward** | Absent | `YOU DID` precedes every request for work |
| **Peer comparison** | None | Achievement events only, never a standing (`UX-32`) |
| **Styling** | `text-slate-*`, `bg-blue-600`, `bg-white` — legacy markup | Semantic tokens (`UX-2`) |

### 2.4 Student — Progress

| | Now | After |
|---|---|---|
| **Grades shown** | Predicted only | Predicted **and** averaging, with the sentence explaining the gap |
| **Ranking** | None | Your own position only, on a dedicated **Improvement** tab. No classmate's value is shown. Gated at ≥8 students with a full-period delta, plus coverage |

### 2.5 Parent

| | Now | After |
|---|---|---|
| **First thing read** | `{name}'s progress` and a paragraph of caveats | One sentence answering *is my child okay* |
| **Grades** | Predicted only, in subject cards | Predicted, averaging and direction per subject |
| **Narrative** | None | `HOW IT'S GOING`, stored, tutor-reviewed (D2) |
| **What's required of them** | Never stated | `WHAT YOU CAN DO` — present in **every** state, including "nothing" |
| **Per-homework detail** | Reports panel | Aggregates and direction only |

---

## 3. The state matrix

**Every surface, every state it can be in, and what renders.** This is the section to check a
finished PR against. A state that renders an empty panel, a `0` standing in for a missing
measurement, or a spinner where the previous value would do, is a defect (`PROD-2`, `UX-19`,
`UX-21`, `UX-29`).

Legend: **absent** = the section is not rendered at all.

### 3.1 Tutor — Today

| State | Verdict | Class strip | TODAY | WHAT CHANGED | NEEDS YOU |
|---|---|---|---|---|---|
| First load, nothing cached | Skeleton line, full width | 3 skeleton rows | Skeleton | Skeleton | absent until known |
| Load failed | *"Today couldn't be loaded."* + Retry | absent | absent | absent | absent |
| No classes yet | *"You haven't set up a class yet."* + **Create a class →** | absent | absent | absent | absent |
| Classes exist, none joined | *"No students have joined yet."* | Class rows with join counts | lessons if scheduled | absent | absent |
| Students joined, nothing marked | *"Nothing marked yet."* | Rows with `○ not enough data yet` | lessons | *"Nothing new since yesterday."* | absent |
| Partial evidence | Composed (§4.1) | Health rows + collapsed green line, each with coverage | lessons | narrative | count + Review → |
| Everything healthy, nothing due | *"Your classes are running well."* | one collapsed green line | *"No lessons scheduled."* | *"Nothing new since yesterday."* | absent — then *"That's everything. Enjoy your day."* |
| Narrative refreshing | unchanged | unchanged | unchanged | **previous text** + `Updating…` (`UX-21`) | unchanged |
| Tutor regenerated it (*Prepare again*) | unchanged | unchanged | unchanged | previous text + `Updating…`, then the new text | unchanged |
| AI key missing | unchanged | unchanged | unchanged | *"Guidance is unavailable right now."* | unchanged (`AI-20`, `INF-9`) |
| A subject has no boundaries | unchanged | that row: `○ no grade boundaries set` + **Set them →** | unchanged | unchanged | unchanged |

### 3.2 Tutor — Class

| State | Verdict | WHY | NEEDS YOU | Tabs |
|---|---|---|---|---|
| Zero students joined | *"{n} of {m} joined"* + code + **Share again →** | absent | absent | absent — **the empty-room surface replaces the page** (spec §7.2) |
| Students joined, nothing marked | *"not enough data yet"* | absent | absent | present |
| Evidence, nobody declining | status + grade + coverage | topic weaknesses | absent | present |
| Evidence, someone declining | status + grade + coverage | topic weaknesses + *"{n} students have declined over the last three weeks"* | direction-selected rows | present |
| Someone low but stable | as above — they are why the class carries its status | as above | **absent from NEEDS YOU**, present under Students | present |
| No boundaries for the subject | `○ no grade boundaries set` + **Set them →** | present | present | present |

### 3.3 Student — Home

| State | Subject strip | Line | DO | YOU DID | NEXT |
|---|---|---|---|---|---|
| First load | skeletons | skeleton | skeleton | absent | skeleton |
| Load failed | *"Couldn't load your subjects."* + Retry | absent | absent | absent | absent |
| Just joined, nothing marked | rows with `not enough data yet` | *"Nothing due yet."* | absent | absent | lesson if scheduled |
| Work due | values + direction | *"Two things to do today."* | due items, soonest first | recent wins | next lesson |
| Nothing due | values + direction | *"You're clear. Nothing due."* | absent | recent wins | next lesson, then `IF YOU WANT · Sit a past paper` |
| Nothing due, nothing done | values or `not enough data yet` | *"You're clear. Nothing due."* | absent | absent | next lesson |
| One subject has no evidence | that row: `not enough data yet`, no colour, no bar | unchanged | unchanged | unchanged | unchanged |
| One score, no history | value with **no arrow** — `null`, never `→` | unchanged | unchanged | unchanged | unchanged |
| Assessment upcoming | unchanged | second line: *"Chemistry mock in 12 days"* | unchanged | unchanged | unchanged |

### 3.4 Student — Progress

Per **D6** the ranking lives on its own **Improvement** tab (PR 23), not here. Progress shows the
student's own grades and topics only; no classmate's value appears in any state on either surface.

| State | Predicted / Averaging | Explanation | Your progress | WHY |
|---|---|---|---|---|
| No marked work | predicted if readiness exists; averaging *"no marked work yet"* | absent | absent | topics with `not enough data yet` |
| Marked work, predicted > averaging | both | *"You're tracking above your recent average…"* | this month's own delta | topic list |
| Marked work, predicted < averaging | both | *"Your recent work has been weaker than your record…"* | this month's own delta | topic list |
| Predicted == averaging | both | *"Your recent work matches your record."* | this month's own delta | topic list |
| Student joined mid-month | unchanged | unchanged | **absent** — stated as too new to compare, never a fabricated delta | unchanged |
| One month of history only | unchanged | unchanged | absent | unchanged |
| No boundaries for the subject | *"no grade boundaries set"*, no grade | absent | unchanged | unchanged |

### 3.5 Parent

| State | Verdict | Subject rows | HOW IT'S GOING | WHAT YOU CAN DO |
|---|---|---|---|---|
| First load | skeleton | 3 skeletons | skeleton | skeleton |
| Load failed | *"We couldn't load this right now."* + Retry | absent | absent | absent |
| Just linked, nothing marked | *"There isn't enough marked work yet to say how {name} is doing."* | rows, all `not enough data yet` | absent | *"Nothing is needed right now. We'll tell you if that changes."* |
| Some subjects have data | *"{name} is on track in 3 of 5 subjects."* | mixed, absent states shown as absent | narrative | composed |
| All on track | *"{name} is on track in all four subjects."* | rows | narrative | *"Nothing is needed right now…"* |
| A subject not submitted for weeks | as above | that row carries the gap | narrative names it | *"{name} hasn't submitted work in Maths for three weeks."* |
| Narrative refreshing | unchanged | unchanged | previous text + `Updating…` | unchanged |
| Tutor regenerated it | unchanged | unchanged | previous text + `Updating…`, then the new text — **never blank in between** | unchanged |
| Parent linked to 2+ children | child chips first, then the whole screen for the selected child | — | — | — |

**On the child switcher:** spec §6 says *one screen, no navigation*, and the current
`ParentDashboard.tsx:29-45` renders chips when there are several children. Both are right —
**the switcher is object selection, not navigation**, and it stays. It renders above the verdict,
because the verdict is a claim about one named child and must not appear to be about another.

---

## 4. The copy deck

Every user-facing string in the new surfaces, and the rule that composes it. Copy lives with the
component that renders it, except the shared absent-state strings, which go in
`frontend/src/lib/labels.ts` (created by PR 8) so the same condition never gets two wordings.

### 4.1 Composition rules

1. **Counts up to ten are words in prose sentences, digits in chips, tables and counters.**
   *"Two lessons today"* in the verdict; `9/11` on a chip; `Reviewing 1 of 6`.
2. **A clause whose count is zero is omitted, not rendered as "0".** If every clause of a line is
   zero, the line is omitted and the section's terminal sentence carries the meaning.
3. **No gendered pronoun anywhere.** No gender is stored on `User`, and inferring it from a name
   misgenders real people. Parent copy uses the child's name or a bare plural — *"on track in 3
   of 4 subjects"*, never *"3 of her 4 subjects"*. The spec's §6 mock uses *"her"*; that is a
   mock, and this rule governs.
4. **Absent is words, never a symbol or a zero** (`PROD-2`, `UX-19`).
5. **Every sentence ends in a full stop, including single-line verdicts.** A verdict without one
   reads as a label.

### 4.2 Tutor — verdict line 1

Evaluated top to bottom; first match wins.

| Condition | String |
|---|---|
| No classes | `You haven't set up a class yet.` |
| Classes exist, no students in any | `No students have joined yet.` |
| Students, no marked evidence anywhere | `Nothing marked yet.` |
| ≥1 class `at_risk` | `{N} class{es} need{s} attention.` |
| ≥1 class `needs_attention`, none at risk | `{N} class{es} could use a look.` |
| All classes `on_track` | `Your classes are running well.` |

### 4.3 Tutor — verdict line 2

Clauses joined by ` · `; each omitted when its count is zero.

| Clause | Zero | One | Many |
|---|---|---|---|
| Lessons | omitted | `One lesson today` | `{Word} lessons today` |
| Marking | omitted | `one piece to mark` | `{word} pieces to mark when you have a moment` |

Both zero → line 2 is omitted. The action button is `Mark →` when the marking clause is present,
otherwise absent.

### 4.4 Tutor — section terminals

| Section | Empty string |
|---|---|
| `TODAY` | `No lessons scheduled.` |
| `WHAT CHANGED` | `Nothing new since yesterday.` |
| `NEEDS YOU` | *absent* — the section is not rendered |
| Whole surface clear | `That's everything. Enjoy your day.` |

### 4.5 Student

| Condition | String |
|---|---|
| Work due | `{Word} thing{s} to do today.` |
| Nothing due | `You're clear. Nothing due.` |
| Assessment upcoming | `{Subject} {kind} in {n} days` · `tomorrow` · `today` |
| Cleared-state offer | `IF YOU WANT` / `Sit a past paper` / `Browse →` |
| Predicted above averaging | `You're tracking above your recent average — the last three pieces have been stronger than the ones before.` |
| Predicted below averaging | `Your recent work has been weaker than your record — the last three pieces pulled the estimate down.` |
| Predicted equals averaging | `Your recent work matches your record.` |
| Own progress, improving | `You're up {n} this month.` |
| Own progress, no change | `You're steady this month.` |
| Too new to compare | `You joined this month — there'll be a comparison next month.` |

### 4.6 Parent

| Condition | String |
|---|---|
| No data at all | `There isn't enough marked work yet to say how {name} is doing.` |
| All subjects on track | `{name} is on track in all {word} subjects.` |
| Mixed | `{name} is on track in {n} of {m} subjects.` |
| None on track | `{name} needs support in {word} of {word} subjects.` |
| Provenance, with data | `Based on {n} marked pieces · updated weekly` |
| Provenance, none | `No marked work yet` |
| Nothing required | `Nothing is needed right now. We'll tell you if that changes.` |
| A gap exists | `{name} hasn't submitted work in {subject} for {n} weeks.` |

### 4.7 Shared absent-state strings → `frontend/src/lib/labels.ts`

| Key | String |
|---|---|
| `noEvidence` | `not enough data yet` |
| `noBoundaries` | `no grade boundaries set` |
| `noBoundariesAction` | `Set them →` |
| `updating` | `Updating…` |
| `aiUnavailable` | `Guidance is unavailable right now.` |
| `loadFailed` | `This is usually temporary — refresh the page to try again.` |

And the four attention reasons, which today exist as two rival maps. The complete set is exactly
four, confirmed against `backend/app/api/assignments.py:255` (`extraction_failed`) and `:286`
(`submission.status.value`, filtered at `:270-278` to `ai_failed`, `ai_marked`, `needs_review`):

| Reason | Label |
|---|---|
| `extraction_failed` | `Question extraction failed` |
| `ai_failed` | `AI marking failed` |
| `ai_marked` | `AI-marked — awaiting your review` |
| `needs_review` | `Some marks need your decision` |

`DashboardHeader.tsx:7-13` has three of these — **`needs_review` is missing**, so the most common
reason renders on the tutor's home as the raw string `needs_review`.

---

## 5. Edge cases

Each row is a real condition reachable in the current data model, the behaviour required, and
where it is handled.

| # | Condition | Required behaviour | PR |
|---|---|---|---|
| 1 | Tutor has exactly one class | Strip renders one row, never a "1 of 1" summary line | 17 |
| 2 | Tutor has eight healthy classes | Three exception rows at most, plus one collapsed green line carrying every remaining class and its grade — nothing hidden | 17 |
| 3 | Class has zero students | The empty-room surface **replaces** the class page; readiness panels are not rendered as empties | 27 |
| 4 | Class has fewer than eight students **with a full-period delta** | No rank on the Improvement tab. The student's own delta and own months still render — a complete surface, not a degraded one. Eight *enrolled* including one joiner does **not** pass | 23 |
| 4b | Student is in the bottom half | *"in the second half this month"*, never a bare `11th of 11`. Boundary is `rank <= floor(n / 2)` | 23 |
| 4c | Two students tie at the top-half boundary | Both banded — the tie shares the better rank, and a tie spanning the boundary is banded for everyone in it | 23 |
| 5 | A student announces "I got the highest on that paper" to the class | Nothing on any surface corroborates or contradicts it — the achievement event is visible only to the achiever, and there is no board for it to be correlated against | 23 |
| 6 | Student enrolled in the same subject through two groups | One row; the **lowest** score wins — the existing rule at `lib/readiness.ts:43` and it is deliberate | 17 |
| 7 | Student has exactly one readiness point | `direction = null`; render **no arrow**. `→` would be a claim | 3 |
| 8 | Subject has no `grade_boundaries` | No grade, no colour, no bar; `no grade boundaries set` + `Set them →` (D5) | 1, 26 |
| 9 | Student joined the class mid-month | Their own progress line is absent and says so — too new to compare. No `joined this month` tag exists, because there is no shared board for it to mark them out on | 23 |
| 10 | Student leaves a class mid-month | The denominator drops (`of 11` → `of 10`). No row vanishes, because no rows are rendered — the denominator reveals only what the class list already shows | 23 |
| 11 | Parent linked to two children | Child chips render above the verdict; the verdict names the selected child | 25 |
| 12 | Parent linked today, nothing marked | Complete, deliberate screen: verdict, all rows `not enough data yet`, `WHAT YOU CAN DO` present | 25 |
| 13 | Narrative refresh in flight | Previous text renders, marked `Updating…`; the section never blanks (`UX-21`) | 15 |
| 14 | Tutor regenerates a parent narrative the parent has already read | The new text replaces it silently; the parent is not told it changed. **The old text is not recalled** — this is the accepted cost of D2 having no approval step | 15 |
| 15 | `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` missing | Narrative section states unavailability; startup is unaffected (`AI-20`, `INF-9`) | 14 |
| 16 | Tutor opens at 01:00 local, UTC+3 | Correct local weekday — requires D4's stored timezone | 5 |
| 17 | Submission has a deliberately blank question | Excluded from the running total; the total states how many are excluded | 7 |
| 18 | Past-paper submission in the averaging query | Contributes normally; `assignment_id` is `None` and must not be read unconditionally (`API-20`) | 2 |
| 19 | Review queue emptied on the last item | Terminal sentence, not a blank page or a bounce to the dashboard | 21 |
| 20 | Tutor with a bookmarked `/tutor/mocks` after the nav shrinks | Redirect, never a 404 | 16 |
| 21 | A student's name would appear in `WHAT CHANGED` | Allowed only in an improvement, per D3; never in a decline or a list | 13, 17 |
| 22 | Two grade-boundary sources disagree | `RISK-5`, still open. PR 1 documents which source it reads; converging them is out of scope | 1 |

---

# Part II — How it ships

## 6. Shape of the delivery

Thirty pull requests in ten stages.

```
Stage 0  Documentation                     1 PR    docs-only, direct to main
Stage 1  Derivation foundations            5 PRs   backend; one migration (D4)
Stage 2  Correctness already visible       3 PRs   small; ship first, in parallel
Stage 3  Design-system convergence         4 PRs   markup only; no IA change
Stage 4  The precomputed narrative         3 PRs   backend; one migration
Stage 5  Tutor surfaces                    5 PRs   the visible redesign
Stage 6  Student surfaces                  4 PRs
Stage 7  Parent surface                    1 PR
Stage 8  Cold start                        3 PRs
Stage 9  Promote the rules                 1 PR    docs-only
```

**Stages 1–3 are deliberately invisible.** They ship real value — three fix live correctness
bugs — but nobody sees a redesign. Stages 5–7 are thin presentations over derivations that must
already be correct; building them first means building them twice.

**Two migrations in the whole plan:** `0022_org_timezone.py` (Stage 1, D4) and
`0023_narratives.py` (Stage 4). Everything else is derived at read time or presentational.
Stage 8's new evidence source adds an enum member, which by `DB-5` and `ADR-0007` needs none.

**One kill switch,** on the only stage that adds a recurring model call (Stage 4).

**Sizes** are files-touched, not calendar: **S** ≤ 3 files, **M** 4–8, **L** 9+ or a migration.

---

## 7. Stage 0 — Land the documentation

### PR 0 — The spec and this plan · S

**Does:** Commits `docs/experience-design.md` (currently untracked), this plan, and the
already-modified `CLAUDE.md` and `docs/README.md` that index them.
**Does not:** Touch `backend/`, `frontend/` or `alembic/versions/`.
**Files:** `docs/experience-design.md`, `docs/experience-implementation-plan.md`, `CLAUDE.md`,
`docs/README.md`.
**Rules:** `CODE-17` — documentation-only, so it may go directly to `main`. It and PR 29 are the
only items in this plan that may.
**Tests:** None applicable.
**Rollback:** `git revert`. No deploy consequence — no build input changed.

---

## 8. Stage 1 — Derivation foundations

Five PRs producing the values Stages 5–7 render. None changes a pixel except PR 1.

### PR 1 — Grade band derives from boundary position · M

**Does:** Adds `grade_band(grade, boundaries)` to `backend/app/services/grades.py`, returning the
band from the **index** of the grade within `Subject.grade_boundaries` — positions 0–2, 3–4, the
rest — and `None` when the list is empty. Sets `status` on `SubjectReadiness` from it. **Deletes**
the frontend threshold derivation: `statusOf()` at `frontend/src/lib/readiness.ts:9-13`
(`>= 70` / `>= 50`) and its duplicate in `ClassReadinessPage.tsx`.

The most load-bearing PR in the plan. Every colour on every surface in Stages 5–7 comes from it.

**Does not:** Touch `ReadinessStatus`'s three members, change any stored score, or resolve
`RISK-5` — it documents in a comment which of the two boundary sources it reads and leaves the
convergence to its own change.
**Files:** `backend/app/services/grades.py`, `backend/app/schemas/readiness.py`,
`backend/app/services/readiness_summary.py`, `backend/app/services/readiness_summary_v2.py`,
`frontend/src/lib/readiness.ts`, `frontend/src/tutor/ClassReadinessPage.tsx`,
`frontend/src/api/readiness.ts`.
**Rules:** `UX-28` (Draft) — no literal grade or percentage threshold in any surface, style or
constant. `PROD-2` — no boundaries means no grade and no colour, never a defaulted one.
`FE-4` / `API-15` — the mirroring TypeScript interface changes in this same PR; nothing checks
the two agree (`RISK-6`). `BE-4` / `CODE-3` — `grade_band` is pure: list in, band out, no session.
**Tests — `backend/tests/test_grades.py` (new):**
- `test_nine_to_one_scale_bands_by_index` — `9 8 7` green, `6 5` amber, `4 3 2 1 U` red
- `test_letter_scale_bands_identically` — `A* A B` green, `C D` amber, rest red
- `test_short_scale_does_not_overflow` — a three-grade list yields green, green, green and no
  IndexError
- `test_empty_boundaries_returns_none` — not a defaulted band
- `test_grade_absent_from_list_returns_none`
Plus `frontend/src/test/readiness-lib.test.ts`: `test_statusOf_is_no_longer_exported`.
**Rollback:** Revert. No data changes; the fields are recomputed on read.
**Watch:** Colours shift for students who sat near the old 70/50 lines. That is the fix, but it
is visible on `ClassReadinessPage` the day it ships — tell the tutor first.

### PR 2 — The averaging grade · M

**Does:** Adds a mean-of-marked-work score and grade per subject — the one value in the spec
needing new derivation rather than new presentation (§3.3). New
`backend/app/services/averaging.py`: a pure function over finalized `QuestionMark` rows plus the
query that fetches them. Adds `averaging_score`, `averaging_grade`, `marked_piece_count`.
**Does not:** Render anything, or change how `predict_grade` is called.
**Files:** `backend/app/services/averaging.py` (new), `backend/app/schemas/readiness.py`,
`backend/app/services/readiness_summary.py`, `frontend/src/api/readiness.ts`.
**Rules:** `PROD-1` — traceable, so `marked_piece_count` travels with the value. `PROD-5` — only
finalized outcomes count: `SubmissionStatus.auto_finalized` and `.finalized` only, drafts
excluded. `PROD-2` — no marked work is `None`, never `0`. `PROD-9` — past papers go through the
same path. `API-20` — `Submission` is polymorphic; the query must not read `assignment_id`
unconditionally. `BE-1`, `BE-4`.
**Tests — `backend/tests/test_averaging.py` (new):**
- `test_no_marked_work_returns_none`
- `test_draft_marks_excluded`
- `test_past_paper_submission_contributes` — `assignment_id is None`
- `test_unmarked_question_excluded_not_zeroed`
- `test_marked_piece_count_matches_contributing_rows`
**Rollback:** Revert. Additive fields nothing reads yet.
**Watch:** An averaging grade disagreeing with the predicted grade reads as a bug. That is why
PRs 22 and 25 ship the explaining sentence in the same change — the pair never ships bare.

### PR 3 — Direction of travel · S

**Does:** Adds `direction: "up" | "flat" | "down" | null` to `SubjectReadiness`, from the trend
series `GET /readiness/students/{id}/trend` already serves. `null` when there are too few points
— the common case for a new student, and it must not read as flat.
**Does not:** Add a new endpoint or store anything.
**Files:** `backend/app/services/readiness_summary.py`, `backend/app/schemas/readiness.py`,
`frontend/src/api/readiness.ts`.
**Rules:** `UX-31` (Draft). `PROD-2` — insufficient history is `null` and renders as absent.
`CODE-12` — the constant separating `flat` from `up`/`down` lives in one named place with a
comment recording why that value.
**Tests — `backend/tests/test_readiness_api.py`:**
- `test_single_point_yields_null_direction`
- `test_rising_series_yields_up`
- `test_series_within_noise_band_yields_flat`
**Rollback:** Revert.

### PR 4 — Coverage · S

**Does:** Adds coverage counts — per class, students with confident evidence over students
enrolled; per subject, topics with evidence over topics that exist. The `9/11 ●` chips (spec
§4.1), and the honesty gate on any class-level claim: a status without coverage is a statement
about a class made from part of it.
**Does not:** Change what counts as "confident" — that stays `ReadinessConfidence.medium |
high`, as `readiness_summary.py:19` already defines.
**Files:** `backend/app/services/readiness_summary.py`, `backend/app/services/groups.py`,
`backend/app/schemas/readiness.py`, `frontend/src/api/readiness.ts`.
**Rules:** `PROD-2` — `12/12 ●` and `2/11 ◌` are not the same statement and must not look alike.
`SEC-7` — the enrolment count is scoped by the authenticated user's organization.
**Tests:**
- `test_class_with_no_evidence_reports_zero_of_n` — not an absent field
- `test_student_in_two_groups_not_double_counted`
**Rollback:** Revert.

### PR 5 — A stored timezone, so "today" means today · L (migration)

**Does:** Resolves **D4**. Adds `Organization.timezone` — nullable, `String(64)` (IANA names run
to the mid-thirties; 64 leaves room without inviting junk). Captured at tutor signup from
`Intl.DateTimeFormat().resolvedOptions().timeZone`, editable in Settings, and **validated
server-side against `zoneinfo.available_timezones()`** — it arrives from the browser, so it is
untrusted input, and an unrecognised value is rejected rather than stored and later crashing a
job. `api/me.py:62` stops computing `datetime.now(timezone.utc).weekday()` and uses the
organization's zone, falling back to UTC when unset — with the fallback stated in the UI, not
silent.
**Does not:** Add a per-user timezone, or change `ScheduleSlot`'s bare `weekday`/`start_time` —
those stay local-to-the-organization, which is what they have always meant implicitly.
**Files:** `backend/app/models/orgs.py`, `alembic/versions/0022_org_timezone.py` (new),
`backend/app/api/me.py`, `backend/app/api/auth.py`, `backend/app/schemas/`,
`frontend/src/auth/TutorSignupPage.tsx`, `frontend/src/tutor/ClassroomSettingsPage.tsx`.
**Rules:** `DB-15` — hand-written, `NNNN_short_name.py`, `down_revision` chained to
`0021_invite_single_use` (verified: it is the current head). `DB-16` — a working `downgrade()`,
verified up → down → up. `BE-15` — read through `get_settings()`, never `os.environ`. `PROD-3` —
organization-level is the right home for a setting shared by a tutor's whole roster. `SEC-*`
reasoning generally: a browser-supplied string is validated before it is stored.

> **`DB-17`, precisely.** The rule as written says a migration altering an existing table uses
> `batch_alter_table(..., naming_convention=NAMING)`. The convention exists because
> `0020_past_papers.py` adds **named** ForeignKeys and unique constraints to tables carrying
> unnamed legacy ones, and SQLite rebuilds the table on `ALTER` and refuses unnamed reflected
> constraints. **This migration adds no constraint** — a bare nullable column to a table with no
> FKs. The closest precedent is the current head itself, `0021_invite_single_use.py`, which does
> exactly that with a bare `batch_alter_table("invites")` and no `naming_convention`.
>
> **Use `batch_alter_table` with `naming_convention=NAMING` anyway.** It costs nothing, and the
> rule as written admits no exception. But note the divergence in the PR description: either
> `0021` breaks `DB-17` or `DB-17`'s scope is narrower than its text — and `GOV-3` says a PR that
> finds an Active rule broken fixes the code, supersedes the rule, or records a Known Gap. This
> one records the Known Gap and proposes narrowing `DB-17` to "a migration adding a constraint to
> an existing table", which is what it has always meant in practice.
**Tests:**
- `test_today_lessons_uses_org_timezone` — a slot on weekday *n* is returned at 01:00 local in
  UTC+3, and is not returned at 23:00 local the previous day
- `test_unset_timezone_falls_back_to_utc`
- `test_signup_captures_timezone`
CI's `migrations` job proves up → down → up on Postgres 16 (`QA-11`).
**Rollback:** `downgrade` one revision; the column is nullable and nothing else reads it.
**Watch:** This is the first of two migrations. Merge it alone.

---

## 9. Stage 2 — Correctness already visible

Three PRs fixing things wrong in production today. **No dependencies — ship these first, in
parallel with Stage 1.**

### PR 6 — A blank question stops contributing a fabricated zero · S

**Does:** `SubmissionReviewPage.tsx:98-107` computes
`got += drafts[m.question_id]?.final_marks ?? 0`, so a question the tutor deliberately left blank
contributes `0` to a number they are shown. Excludes unmarked questions and states how many are
excluded.
**Does not:** Change what is written on finalize — display only.
**Files:** `frontend/src/tutor/SubmissionReviewPage.tsx`.
**Rules:** `PROD-2`, `UX-19` — the exact case both rules exist for.
**Tests — `frontend/src/test/SubmissionReview.test.tsx` (new):**
- `test_blank_question_excluded_from_total`
- `test_total_states_how_many_are_unmarked`
**Rollback:** Revert. No mark is written differently.

### PR 7 — One reason-label map · S

**Does:** `REASON_LABELS` exists twice — three keys exported from `DashboardHeader.tsx:7-13`,
**missing `needs_review`**, so the most common reason renders on the tutor's home as a raw enum
string; and a rival four-key copy at `HomeworkOverviewPage.tsx:6-11`. Creates
`frontend/src/lib/labels.ts` with the complete set (§4.7) plus the shared absent-state strings;
both call sites import it.
**Does not:** Change the backend's reason values.
**Files:** `frontend/src/lib/labels.ts` (new), `frontend/src/tutor/today/DashboardHeader.tsx`,
`frontend/src/tutor/HomeworkOverviewPage.tsx`.
**Rules:** `CODE-3`. The `?? reason` fallback stays — a reason the map does not know must still
render something, and a raw enum beats a blank.
**Tests:** `test_every_backend_reason_has_a_label` — asserts all four of §4.7.
**Rollback:** Revert.

### PR 8 — Two mislabelled controls · S

**Does:** (a) The header search is `aria-label="Search learners"` but filters only the readiness
table — not lessons, not the review queue. Relabelled to what it searches. (b) The tutor sidebar
renders an "AI Guidance" link pointing at `/tutor`, the page the tutor is already on
(`AppShell.tsx:112-123`) — removed.
**Files:** `frontend/src/tutor/today/DashboardHeader.tsx`, `frontend/src/components/AppShell.tsx`.
**Rules:** §02 — an `aria-label` that misdescribes its control is worse than none, because a
screen-reader user cannot see the contradiction.
**Tests:** `Nav.test.tsx` → `test_sidebar_has_no_self_link`.
**Rollback:** Revert.

---

## 10. Stage 3 — Design-system convergence

Four PRs. **These land before Stages 5–7.** Two thirds of the product is unmigrated legacy
markup; rebuilding its information architecture on top would mean touching every line twice.

### PR 9 — Retarget purple and orange · M

**Does:** `frontend/src/index.css` retargets Tailwind's palette onto MANARA's tokens, but purple
and orange are absent, so five sites render raw palette colours on the navy surface with no token
and no contrast measurement. Adds the retargets and the contrast cases.
**Does not:** Add new palette families beyond what those five sites need.
**Files:** `frontend/src/index.css`, `frontend/src/test/contrast.test.ts`,
`student/SubmitHomeworkPage.tsx:151`, `tutor/SubmissionReviewPage.tsx:23,235,258`,
`tutor/HomeworkOverviewPage.tsx:64`.
**Rules:** `UX-2`. `UX-1` — **the retarget block stays unlayered.** It wins the cascade only by
being outside `@layer`; wrapping it silently breaks every colour in the app.
**Tests:** `contrast.test.ts` gains a case per new token pair. Note it reads tokens from disk
rather than importing the stylesheet, because the Tailwind plugin resolves `?raw` to an empty
string under vitest and every assertion would pass vacuously — do not "simplify" that.
**Rollback:** Revert. Wrong is immediately visible.

### PR 10 — Migrate the student and parent surfaces to tokens · M

**Does:** `StudentHomePage.tsx` and `ParentDashboard.tsx` still use `text-slate-*`, `bg-blue-600`,
`bg-white`. Migrates the markup.
**Does not:** Change any section, any datum or any order. That is PRs 22 and 25.
**Files:** `frontend/src/student/StudentHomePage.tsx`, `frontend/src/parent/ParentDashboard.tsx`.
**Rules:** `UX-2`. `bg-white` is retargeted to `--color-surface` at `index.css:108-111` and is
**not white** — a migration that "looks fine" beforehand may be reading a retargeted colour, not
a token.
**Tests:** The existing suites pass unchanged; that they do is the evidence the change was
presentational.
**Rollback:** Revert — one commit, which is why this is its own PR.

### PR 11 — `ClassReadinessPage` converges onto `ReadinessTable` · S  ·  **Shipped**

**Does:** The page carries its own legacy markup and a second copy of the readiness thresholds.
PR 1 deleted the thresholds; this deletes the markup and renders `components/ReadinessTable`.
**Files:** `frontend/src/tutor/ClassReadinessPage.tsx`.
**Rules:** `UX-2`, `CODE-3`. **Depends on PR 1.**
**Tests:** `ReadinessView.test.tsx` extended to the page.
**Rollback:** Revert.

### PR 12 — Mobile chrome: safe areas and a real tab bar · M  ·  **Shipped**

**Does:** Three things that ship together because each is unsafe without the others.
(a) `frontend/index.html:5` gains `viewport-fit=cover`. (b) Safe-area padding tokens are added to
`index.css`. (c) `AppShell.tsx:159-165` stops mapping the full `nav` array into one horizontally
scrolling strip and renders a bottom tab bar honouring the `slot` split the desktop sidebar
already honours at `:85-86`, with an overflow for roles carrying more than four destinations.
**Does not:** Change any nav item — that is PR 16.
**Files:** `frontend/index.html`, `frontend/src/index.css`, `frontend/src/components/AppShell.tsx`.
**Rules:** §02; spec §4.2, §5.1. A fixed bottom bar without `viewport-fit=cover` and safe-area
insets sits under the iOS home indicator — which is why this is one PR, not three. Touch targets
are ≥44×44 CSS px; the current `TabLink` at `AppShell.tsx:66-81` is `py-1.5` and does not meet it.
**Tests:** `Nav.test.tsx` → `test_tab_bar_shows_main_slot_only`,
`test_every_nav_destination_remains_reachable`.
**Rollback:** Revert.
**Watch:** The first change to touch every authenticated screen on phones. **Verify on a physical
iOS device and an Android before merging** — CI cannot catch a safe-area error.

---

## 11. Stage 4 — The precomputed narrative

Spec §8 is absolute for the tutor's home: *the narrative is present when the surface opens; no
primary surface waits on a model to render its primary content*. Today
`POST /groups/{group_id}/brief` blocks on `text_complete` inside the request handler
(`api/groups.py:267`), persists nothing but an `AiUsageEvent` (`:270-278`), and builds its prompt
inline (`:258-265`) while `services/prompts.py:153` registers `class_brief` with an **empty
system string**.

### PR 13 — The class-brief prompt moves to `services/prompts.py` · S  ·  **Shipped**

**Does:** Moves the instruction text into the registered template with a real version, leaving the
handler passing only grounding data. Encodes **D3**: the prompt states whether and how a student
may be named.
**Does not:** Change where the call happens — that is PR 14.
**Files:** `backend/app/services/prompts.py`, `backend/app/api/groups.py`.
**Rules:** `AI-6` — prompts live only in `services/prompts.py`. `AI-7` — the version bumps.
`BE-2` — prompt construction is service work. `SEC-20`, `SEC-21` — the marking prompt's rule that
page content is data and never instructions is the model to follow for any text derived from
student work.
**Tests:** `test_class_brief_system_prompt_is_not_empty`;
`test_handler_contributes_no_instruction_text`. Use the `fake_ai` fixture and monkeypatch the
**calling** module's `text_complete`, not `app.services.ai` — services import the helper into
their own namespace, so patching the source does nothing (`QA-7`). Never call a real provider
(`QA-8`).
**Rollback:** Revert. The brief is regenerated on demand and stored nowhere, so nothing migrates.

### PR 14 — Narrative storage and job · L (migration)  ·  **Shipped**

**Does:**

- **Model** — `backend/app/models/narrative.py`. Append-only; a refresh writes a new row and the
  read takes the latest. Re-exported from `models/__init__.py`.

  | Column | Type | Note |
  |---|---|---|
  | `organization_id` | FK → `organizations.id`, indexed | `PROD-3`, and the `SEC-7` filter |
  | `audience` | `Enum(NarrativeAudience, native_enum=False, length=16)` | `tutor_class` \| `parent_student`; 16 clears the 14-char member with room |
  | `group_id` | FK, nullable | set iff `audience == tutor_class` |
  | `student_id` | FK → `users.id`, nullable | set iff `audience == parent_student` |
  | `text` | `Text` | |
  | `prompt_version` | `String(16)` | which `services/prompts.py` version wrote it (`AI-7`) |
  | `model` | `String(64)` | so a bad narrative traces to what produced it |
  | `generated_at` | `DateTime(timezone=True)` | **timezone-aware.** `0012_organizations.py` carries the scar: a naive column compiles to `TIMESTAMP WITHOUT TIME ZONE` and asyncpg rejects a tz-aware bind |

  **No `reviewed_at` and no `suppressed`** — D2. The row carries no review state at all, because
  there is no review step. Adding them "just in case" would invite a workflow to grow around
  them.

- **Indexes** — named here rather than left to `DB-12`'s general instruction, because this table
  is **append-only and unbounded**: the class narrative writes on every evidence build and the
  parent narrative every week, forever. Without these, "latest row for this group" degrades from
  a seek to a growing sequential scan, and **nothing in CI would catch it** — the suite builds
  its schema from `Base.metadata` on SQLite and never runs a migration.

  | Index | Serves |
  |---|---|
  | `(organization_id)` | the tenant filter; every FK gets one |
  | `(organization_id, group_id, id DESC)` | latest `tutor_class` narrative for a group |
  | `(organization_id, student_id, id DESC)` | latest `parent_student` narrative for a student |

  **Order by `id`, not `generated_at`.** `generated_at` is set by the job, so a manual *Prepare
  again* racing the weekly job can produce two rows with equal or out-of-order timestamps. `id`
  is the only column that totally orders insertion. If `generated_at` must drive the display
  sort, index `(…, generated_at DESC, id DESC)` with `id` as the tiebreaker — never
  `generated_at` alone.

  Each index is **declared on the model as well as created in the migration** (`DB-12`). Four of
  the five existing indexes in this codebase exist only in migrations, so the test schema already
  differs from production — do not add a fifth.

- **The polymorphic invariant.** `group_id` and `student_id` are two nullable FKs selected by
  `audience` — structurally identical to `Submission.assignment_id` / `past_paper_id`, which
  `API-20` exists to guard because reading the wrong one raises *inside* an authorization check.
  Follow that precedent: **enforced in code, in one place**, not by a DDL `CHECK` — a single
  accessor on the model that branches on `audience`, and no caller reads either FK directly.
  PR 15's authorization path uses that accessor. A narrative silently attached to the wrong
  student is a paragraph about one child shown to another child's parent.

- **Retention.** The table grows without bound and the plan adds no pruning. That is acceptable
  at this scale — a row is a few hundred bytes and the write rate is bounded by evidence volume —
  but it is a deliberate choice, recorded here so the first person to notice a large table finds
  the reasoning rather than inventing a cleanup job. Revisit if `narratives` passes ~1M rows.

- **Migration** — `alembic/versions/0023_narratives.py`, chained to `0022_org_timezone`. A
  `create_table`, so no `batch_alter_table` and no naming convention are involved; nothing else in
  the schema holds an FK to `narratives`, so `drop_table` is a clean `downgrade()`.
- **Job** — a `generate_narrative` handler. The payload carries identifiers only; the handler
  re-reads current state. Re-running on the same payload with no new evidence writes nothing.
- **Triggers** — the class narrative enqueues when evidence lands for that class, at the tail of
  the existing evidence build, **not from a router**.

  The parent narrative refreshes **weekly, by sweep — not by a self-perpetuating chain.**
  A `sweep_parent_narratives` job selects the students whose latest narrative is older than seven
  days and enqueues one `generate_narrative` each, then re-enqueues *itself*.

  > **Why not have each narrative job re-enqueue its own successor?** That was this plan's first
  > design, and reading `workers/jobs.py:215-233` kills it. On failure the worker retries once,
  > then at `MAX_ATTEMPTS` sets `status = failed` — and the comment there is explicit:
  > *"Nothing watches the failed count yet, so this line is the only record that a piece of a
  > student's work stopped moving."* In a self-perpetuating chain the schedule **lives only inside
  > the job row**, so one transient outage — the AI provider down across the retry window — ends
  > that student's parent narrative **permanently and silently**. A parent would simply stop
  > getting updates, and nothing would say so.
  >
  > A sweep re-derives who is due from the `narratives` table on every run, which is the same
  > principle `BE-9` already states: payloads carry identifiers and handlers re-read current
  > state. A failed sweep costs one week and self-corrects on the next; a failed individual
  > narrative costs one week for one student. Neither breaks the schedule.
  >
  > Note the retry backoff also **overwrites `run_after`** (`:222`), so a chain's next-week
  > schedule and the worker's 60-second retry are the same field — a second reason the schedule
  > must not live there.

  The sweep's own re-enqueue has the same fragility in miniature, so **its failure is the one
  thing worth alerting on**; if the sweep row ever reaches `failed`, every parent narrative stops.
  Until something watches `jobs.status`, the sweep is re-enqueued idempotently at API startup in
  `lifespan` as a floor, so a restart heals it.
- **Kill switch** — one setting read via `get_settings()` that stops enqueueing. Default on;
  off leaves stored narratives readable and stops new ones.

**Does not:** Change any surface. Nothing reads these rows until PR 15.
**Files:** `backend/app/models/narrative.py` (new), `backend/app/models/__init__.py`,
`alembic/versions/0023_narratives.py` (new), `backend/app/services/narrative.py` (new),
`backend/app/workers/jobs.py`, `backend/app/services/evidence.py`, `backend/app/config.py`.
**Rules:** `BE-3` — re-exported from the barrel, or it silently gets **no table in tests**.
`BE-6`, `BE-7` — delivery is at-least-once; the handler is safe to re-run. `BE-9` — identifiers,
not objects. `BE-13` / `PERF-1` — no blocking call; the worker shares the API's event loop, so
one blocking call stalls request serving for every user. `DB-15`, `DB-16`, `DB-12`.
**`DB-5` / `DB-6` / `ADR-0007`** — `audience` is
`Enum(NarrativeAudience, native_enum=False, length=16)`, following `EvidenceSource` and
`ReadinessConfidence`. **Do not reach for a native Postgres `ENUM`**: the whole point is that
adding a third audience later needs no migration, which a native type would not give — and the
same non-native choice is what makes PR 28's new `EvidenceSource` member migration-free. The
flip side of `DB-6` applies too: nothing forces an audit of the `if`/`match` chains over the
enum, so a future member must be traced by hand. `PROD-3`, `DB-2` — a new top-level aggregate
carries `organization_id`. `AI-1`, `AI-2` — through `services/ai.py`, naming a surface not a
model. `AI-17` — an unpriced model records `cost_usd = NULL`, never `$0`.
**Tests — `backend/tests/test_narrative.py` (new):**
- `test_rerun_same_payload_is_noop` — driven with `process_one_job()`, never `worker_loop()`
  (`QA-6`)
- `test_sweep_enqueues_only_students_due` — a narrative written yesterday is not regenerated
- `test_sweep_reenqueues_itself_with_future_run_after`
- `test_failed_narrative_does_not_break_next_weeks_sweep` — the whole reason for the sweep
- `test_startup_reenqueue_is_idempotent` — a restart does not accumulate sweep rows
- `test_missing_ai_key_degrades_surface_and_does_not_block_startup` (`AI-20`, `INF-9`)
- `test_narrative_carries_organization_id`
- `test_prompt_version_recorded_on_row`
- `test_audience_determines_which_fk_is_set` — a `parent_student` row has `group_id is None`, and
  the accessor raises rather than returning the wrong one
- `test_latest_read_orders_by_id_not_generated_at` — two rows with identical `generated_at`
  resolve deterministically
- `test_generated_at_is_timezone_aware` — the `0012` failure mode, asserted
**Rollback:** **Flip the kill switch — instant, no deploy.** Then revert and `downgrade` one
revision if needed.
**Watch:** **The highest-risk PR in the plan.** It adds recurring model spend proportional to
evidence volume, and its migration runs on deploy — `alembic upgrade head` failing mid-chain
leaves the previous revision serving while `main` has already moved (runbooks R2, R4). Merge it
alone, on a day someone is watching, and watch `ai_usage_events` for a day before PR 15.

### PR 15 — Surfaces read the stored narrative · M  ·  **Shipped**

**Does:** `GET /groups/{group_id}/narrative` and `GET /students/{student_id}/narrative` return the
latest stored text with its `generated_at`, or a stated absence. `POST /groups/{group_id}/brief`
**stays** as an explicit *Prepare again* — it simply stops being the only way the text can exist.
The `"Not enough evidence yet…"` short-circuit at `groups.py:245-250` is correct absent-state
behaviour and is preserved. Per **D2** there is **no review or suppress endpoint**; instead
*Prepare again* is extended to cover the parent narrative, so a tutor who reads something wrong
regenerates it rather than approving it.
**Does not:** Render anything on the parent or tutor surface — PRs 18 and 25 do that.
**Files:** `backend/app/api/narrative.py` (new), `backend/app/api/groups.py`,
`backend/app/schemas/`, `frontend/src/api/`.
**Rules:** `SEC-7`, `SEC-8` — a parent reads only their own child's narrative, scoped by
organization derived from the authenticated user, never from a path or body parameter; and
student-visible material is scoped by (organization, subject), never subject alone —
`_enrolled_scope` in `api/past_papers.py` is the reference. `API-7` / `SEC-9` — `404`, not `403`.
`SEC-11` / `BE-17` — **the role gate goes in the signature** (`TutorUser` / `StudentUser` from
`api/deps.py`), never in the handler body; a dependency cannot be forgotten and an imperative
call fails **open**. `PROD-7` — the tutor's veto writes its append-only audit row. `UX-21`.
**Tests:** `QA-12` applies — this touches authorization, so it ships with the negative cases:
- `tests/test_authorization.py` gains both routes (the suite fails if any route loses its gate)
- `test_parent_cannot_read_another_orgs_narrative_returns_404`
- `test_parent_cannot_read_a_non_child_narrative_returns_404`
- `test_narrative_row_has_no_review_state` — D2, asserted so a workflow cannot accrete later
- `test_prepare_again_writes_a_new_row_and_the_parent_read_takes_it`
**Rollback:** Revert. Rows remain; nothing reads them.

---

## 12. Stage 5 — Tutor surfaces

### PR 16 — Navigation down to four · M  ·  **Shipped**

**Does:** Nine tutor nav items (`App.tsx:82-92`) become **Today · Classes · Review · Library**.
Library absorbs past papers, mocks and syllabuses; Preferences and Settings leave the primary
navigation. `/tutor/review` is a new route over `assignmentsNeedingAttention`. Every retired path
redirects.
**Does not:** Change any page's contents, or the student nav.
**Files:** `frontend/src/App.tsx`, `frontend/src/components/AppShell.tsx`,
`frontend/src/tutor/LibraryPage.tsx` (new), `frontend/src/tutor/ReviewQueuePage.tsx` (new).
**Rules:** Spec §4. **Depends on PR 12** — four destinations is what makes the tab bar work.
**D1 must be answered before this merges** if labels are changing.
**Tests:** `Nav.test.tsx` → `test_tutor_nav_has_four_items`,
`test_every_retired_route_redirects` (one case per retired path, asserting a redirect and not a
404).
**Rollback:** Revert.
**Watch:** Low mechanically, high in perception. This is the change a tutor will call "the
redesign" — tell them before it ships.

### PR 17 — One aggregate endpoint for the tutor's home · M  ·  **Shipped**

**Does:** `api/analytics.py:49-58` performs a `db.get(User, …)` plus a `TopicReadiness` select
**per student in a Python loop**, and `TodayDashboard.tsx:37-43` fans that out **per group** via
`useQueries` — eight classes, eight of them. Adds one endpoint returning everything the home
needs (verdict inputs, class strip with grade, band and coverage, today's lessons in the
organization's timezone, review count) in a bounded number of queries.
**Does not:** Delete `group_analytics` — the class page still uses it. It stops being on the
home's path.
**Files:** `backend/app/api/today.py` (new), `backend/app/services/groups.py`,
`backend/app/schemas/`.
**Rules:** `PERF-1`. `BE-1`, `BE-2` — aggregation is service work; the router stays thin.
`SEC-7`. **Depends on PRs 1–5.**
**Tests:** `test_query_count_does_not_grow_with_group_count` — the assertion that keeps the fix
from regressing. Plus `test_today_lessons_use_org_timezone` at the aggregate level.
**Rollback:** Revert. Additive; nothing reads it yet.

### PR 18 — Today, rebuilt · L  ·  **Shipped**

**Does:** Replaces the four stacked sections with spec §4.1 (desktop) and §4.2 (phone), in the
states of §3.1 and the copy of §4.2–4.4: verdict block as a single primary target, class strip
where healthy classes collapse to one line, `TODAY`, `WHAT CHANGED` reading the stored narrative,
`NEEDS YOU`. Sections with nothing in them are **not rendered**.
**Does not:** Change the review or class pages.
**Files:** `frontend/src/tutor/today/*`.
**Rules:** `UX-27`, `UX-29`, `UX-30`-as-narrowed-by-D3. `UX-19`, `PROD-2`. `FE-6` — server data
stays in TanStack Query, not copied into `useState`.
**Tests — `TodayDashboard.test.tsx`, rewritten:**
- `test_clear_day_renders_terminal_sentence_and_no_empty_panels`
- `test_eight_healthy_classes_collapse_to_one_line`
- `test_no_student_name_appears_outside_an_improvement` — the assertion that keeps D3's narrowing
  honest as the surface evolves
- `test_verdict_composes_correctly` — one case per row of §4.2
- `test_zero_count_clause_is_omitted_not_zeroed`
- `test_narrative_refreshing_shows_previous_text`
**Rollback:** Revert. Reversible in code, not in perception.

### PR 19 — Class page · M  ·  **Shipped**

**Does:** Spec §4.3 and the states of §3.2 — verdict with grade, band and coverage; `WHY`; and
`NEEDS YOU` **selected on direction, not level**, so a student sliding from 8 to 6 appears and a
stable grade-4 student does not. Per **D2**, this is the one place the parent narrative is
surfaced to the tutor — **read-only, below the fold, with no control except *Prepare again***. No
badge, no unread state, no indication that anything is expected of them.
**Does not:** Change the tabs beneath it.
**Files:** `frontend/src/tutor/GroupLayout.tsx`, new class-overview component.
**Rules:** Spec §4.3. `PROD-2` — a student with no direction yet is not "flat". `PROD-7`.
**Depends on PRs 3, 15, 17.**
**Tests:**
- `test_stable_low_student_absent_from_needs_you_present_under_students`
- `test_declining_high_student_present_in_needs_you`
- `test_class_with_zero_students_renders_empty_room`
**Rollback:** Revert.

### PR 20 — Review queue traversal · M  ·  **Shipped**

**Does:** Adds *Reviewing 1 of 6*, *Skip*, *Finalize & next*, with the breadcrumb returning to the
queue instead of the assignment (`SubmissionReviewPage.tsx:117`).
**Does not:** Touch the draft-seeding behaviour at `:49-61`, which lands the AI's proposal in the
tutor's own input so agreeing is one action. **That is correct and is kept.**
**Files:** `frontend/src/tutor/SubmissionReviewPage.tsx`, `frontend/src/api/homework.ts`, a
queue-order endpoint if none exists.
**Rules:** Spec §4.5 — this surface deliberately breaks the calm-layout rules the home follows,
because calm layout costs the tutor real time here. `PROD-7` / `AI-12` — every override writes its
append-only audit row; *Finalize & next* must not become a path that skips it. `AI-15` — a remark
request is never resolved by AI and there is one per question, ever. **Depends on PR 6.**
**Tests:**
- `test_finalize_advances_to_next_queue_member`
- `test_last_item_lands_on_terminal_state_not_blank`
- `test_audit_row_written_on_every_finalize`
**Rollback:** Revert.
**Watch:** It touches the finalize path, which writes marks that become `Evidence`. The audit-row
test is the gate.

---

## 13. Stage 6 — Student surfaces

### PR 21 — Student home, rebuilt · M

**Does:** Removes the cross-subject "Overall readiness" percentage at `StudentHomePage.tsx:41-44`
— an unweighted mean across subjects with different scales, coverage and boundaries, and the
first thing a student sees every day. Replaces it with spec §5.1, the states of §3.3 and the copy
of §4.5: per-subject values **each paired with direction**, then `DO`, `YOU DID`, `NEXT`.
**Does not:** Add peer comparison — that is PR 23.
**Files:** `frontend/src/student/StudentHomePage.tsx`.
**Rules:** `UX-31` — a score alone reads as a standing judgement of the person. `UX-27`, `UX-29`,
`PROD-2`. **Depends on PRs 3, 10.**
**Tests:**
- `test_do_precedes_you_did_in_dom_order`
- `test_no_cross_subject_aggregate_is_computed`
- `test_subject_without_evidence_renders_words_not_zero`
- `test_single_readiness_point_renders_no_arrow`
**Rollback:** Revert.
**Watch:** Removing a number students have seen daily. It is the right removal — the number was
arithmetically meaningless — but it will be noticed. Say so.

### PR 22 — Progress: predicted beside averaging · M

**Does:** Spec §5.2, states §3.4, copy §4.5 — predicted and averaging side by side with the
sentence explaining the gap, `WHY` per topic, evidence behind a disclosure.
**Does not:** Include the leaderboard.
**Files:** `frontend/src/student/StudentDashboard.tsx` or a new Progress page.
**Rules:** Spec §3.3 — the gap is the story, and the honest explanation of why a predicted grade
is not a promise. `PROD-1` — `marked_piece_count` travels with the averaging grade.
**Depends on PRs 1, 2, 3.**
**Tests:**
- `test_predicted_with_no_marked_work_states_averaging_absent` — not rendered as equal
- `test_explanation_matches_direction_of_gap` — one case per row of §4.5
**Rollback:** Revert.

### PR 23 — Improvement: the leaderboard, on its own tab · M

**D6 is settled: build it.** It gets a dedicated destination — **Improvement** in the student
navigation — and appears on no home surface, tutor or student.

**What it shows.** Everything on this tab is either the reader's own data or a count. No
classmate is ever an object on the screen.

```
IMPROVEMENT · CHEMISTRY                            March

  You're 3rd of 11 this month.
  ▲ +6        up from 7th in February

  YOUR MONTHS
  Feb  7th   ▲ +2
  Jan  9th   ▲ +1

  WHAT WOULD MOVE YOU UP
  Rates          3 of 8 marks recently
  Electrolysis   not enough data yet
```

**What it does not show — and this is the whole design.** No row list of classmates. No
classmate's delta, exact or banded. No `← you` marker inside a list of other people. No names, no
initials, no avatars. The ranking exists; the ranked do not appear.

**Why this shape rather than spec §5.2's.** A security review of the drawn design — anonymous
rows, each with its exact delta, reader marked `← you`, gated at ≥5 students — returned **do not
ship**. Eight de-anonymisation vectors; four decisive:

| # | Vector against spec §5.2's board | Closed by this design? |
|---|---|---|
| 1 | **Screenshot collusion.** One shared board where only the `← you` marker moves. Two classmates comparing screens label two rows; four label the class. **Works at any class size**, so no gate closes it. | **Closed.** There is no shared board. Two students comparing screens learn each other's *rank number* and nothing else — no delta, no score, no trajectory. |
| 2 | **Exact-delta fingerprinting.** Integer deltas rarely collide at N=5–15; a reader who knows roughly what one classmate scored matches them to a row by arithmetic. | **Closed.** No classmate's delta is transmitted, so there is nothing to fingerprint. |
| 3 | **Join/leave landmarks.** A `joined this month` tag or a vanished row **is** a name when exactly one student joined or left. | **Closed.** No rows, so nothing appears or vanishes. The denominator moves (`of 11` → `of 12`), which reveals only what the class list already shows the student. |
| 4 | **Achievement-event correlation.** The top scorer announces it themselves; whoever announced it is then attributable to the board's largest delta. | **Closed.** No largest delta is published, and the achievement event stays private to the achiever. |

The three compounding findings go the same way: the k-anonymity floor stops mattering when no
per-classmate value is released; the enrolment-vs-delta mismatch is fixed by the gate below; and
overlapping class membership has nothing to intersect.

**Three residual risks, accepted rather than solved:**

1. **The whole class comparing ranks reconstructs the full order.** The obvious version is two
   students sharing screens, which costs a position and nothing else. **The version that
   actually matters is the whole roster doing it** — a "post your rank" group chat, which in a
   class of eight is one message. That reconstructs the **complete ordinal ranking with real
   names on it**. Magnitude and attainment stay hidden, but *who improved least* becomes common
   knowledge — which is close to the harm the original board was rejected for.

   Nothing in the product prevents this, and nothing can: any ranking a student can see is a
   ranking a student can retype. What the design does is remove everything except the ordinal —
   no score, no delta, no trajectory — so the reconstructed artefact is an ordering, not a
   record. The floor below raises the coordination cost. **It does not close this.**
2. **Your own rank moving tells you about someone else.** A student who submitted nothing and
   still fell has learned that a classmate improved a lot this period. This is a genuine
   inference channel, distinct from collusion, and it is irreducible in any ranking: relative
   position is by definition information about other people. Bounded to "somebody, somewhere in
   this class, moved" — no identity, no magnitude.
3. **Low rank is still a message.** *"9th of 11"* discourages even with nobody named — the exact
   failure spec §5.1 warns about. **Mitigated by never rendering a bare bottom placing:** exact
   rank in the top half; below it the tab reads *"in the second half this month"*, with the
   student's own delta and month-on-month movement, which is what they can act on.

   The split needs a stated rule, because an off-by-one at the boundary renders the exact
   placing this design exists to avoid: **top half is `rank <= floor(n / 2)`**, so at n=11 ranks
   1–5 are exact and 6–11 are banded; **ties share the better rank**, and a tie spanning the
   boundary is banded for everyone in it. Both are tested.

**Rollout note for tutors:** the one cheap thing that closes the easiest version of risk 1 —
**do not ask students to share this screen**, and say so when the tab is introduced. A tutor
soliciting rank screenshots turns a voluntary leak into a compelled one, with the power asymmetry
that implies.

**Gates, both hard, both changed from spec §5.2:**

- **At least eight students with a delta for the full period** — not eight enrolled. A class of
  eight including one joiner has seven real data points and must not pass a headcount test.

  > **Why eight and not five.** Five was the spec's number and it was doing anonymity work.
  > Once no per-classmate value is released, k-anonymity stops being the question, so five would
  > be defensible purely as a statistical-validity floor. It is raised anyway for one reason:
  > **at five, organising the whole class to compare ranks is a five-message group chat.** Eight
  > raises the coordination cost and dilutes the result if it happens. **This is
  > defence-in-depth, not an anonymity mechanism** — do not let a later change treat it as one
  > and conclude the risk is closed.

- **Coverage above the threshold** (PR 4). Ranking within a class where three of twelve have
  evidence is not a ranking (`PROD-2`).

Below either gate: no rank. The student's own delta and their own months still render — that is a
complete surface, not a degraded one.

**Recomputed daily at most**, with no timestamp precise enough to correlate a rank change to a
single submission.

**Also in this PR:** the achievement event from spec §5.1's `YOU DID` — *"highest in your class on
this paper"* — shown **only to the student it happened to**, never broadcast to the class in any
framing.

**Files:** a new backend endpoint, `frontend/src/student/ImprovementPage.tsx` (new),
`frontend/src/App.tsx` (route + `STUDENT_NAV` entry — this makes nine student destinations, so it
lands in the phone overflow, not the four-item tab bar).
**Rules:** `SEC-8` — scoped by **(organization, subject)**, never subject alone, because subjects
are global; `_enrolled_scope` in `api/past_papers.py` is the reference. `PROD-2` — a gate not met
is a stated absence, never a zero or an empty board. `PROD-4` / `SEC-7`. **Depends on PRs 3, 4.**

> **`UX-32` must be amended by this decision, not quietly broken.** It reads *"peer comparison is
> shown to a student only as an achievement event, never as a persistent standing or rank"* — and
> a monthly rank is a rank. `GOV-3` allows exactly three responses; this takes the second.
> **PR 29 files the amended rule:**
>
> **`UX-32` (revised)** — A student is never shown another student's score, grade, delta or
> identity. A student may be shown **their own position** within an improvement ranking, on a
> surface dedicated to it, never on a home surface, and never as a bare bottom placing.
>
> *Rationale unchanged in substance:* the harm `UX-32` was written against is a standing whose
> disappearance becomes the message, and a board that publishes classmates to each other. Neither
> survives in this design.

**Tests:**
- `test_no_classmate_value_appears_in_any_response` — the assertion the whole design rests on;
  the response body contains the reader's rank, the reader's delta and a count, and nothing else
- `test_student_cannot_see_another_orgs_ranking` (`QA-12`)
- `test_gate_counts_full_period_deltas_not_enrolment` — eight enrolled with one joiner does not
  pass
- `test_coverage_below_gate_returns_no_rank_but_still_returns_own_delta`
- `test_top_half_boundary_is_floor_n_over_2` — n=11 → rank 5 exact, rank 6 banded; n=8 → rank 4
  exact, rank 5 banded
- `test_tie_shares_the_better_rank`
- `test_tie_spanning_the_boundary_is_banded_for_everyone_in_it` — the off-by-one that would
  render the bare placing this design exists to prevent
- `test_achievement_event_is_visible_only_to_the_achiever`
- `test_rank_absent_from_every_home_surface` — student and tutor
**Rollback:** Revert. The tab disappears; no data is lost and nothing else reads the endpoint.
**Watch:** **The highest product risk in the plan** — a ranking shown to children. Ship it to one
class first, and ask that tutor what their students said about it before it reaches everyone.

### PR 24 — Cleared state and first sign-in · S

**Does:** Spec §5.3's cleared state, whose only offer is a past paper — there is no practice, quiz
or revision generator anywhere in `backend/app/api/` or `backend/app/services/`, so any other
offer would be a control with nothing behind it. Plus spec §5.4: one orientation screen stating
what the AI assistant does and does not do.
**Files:** `frontend/src/student/StudentHomePage.tsx`, a new orientation screen,
`frontend/src/auth/JoinPage.tsx`.
**Rules:** Spec §2.3 — no surface offers an action requiring a person to respond, and the
assistant cannot use "ask your tutor" as an escape hatch. `UX-26` — stating the boundary once,
deliberately, beats letting a student meet it as a refusal at 11pm, because it then reads as
design rather than obstruction. **Depends on PR 21.**
**Tests:** `test_cleared_state_offers_exactly_one_action_and_it_is_past_papers`.
**Rollback:** Revert.

---

## 14. Stage 7 — Parent surface

### PR 25 — The parent screen · M

**Does:** Spec §6, states §3.5, copy §4.6 — verdict sentence, subject rows carrying predicted,
averaging and direction, `HOW IT'S GOING` from the stored narrative, **`WHAT YOU CAN DO` present
in every state including "nothing"**, then earlier reports. The child switcher stays, above the
verdict.
**Does not:** Add per-homework detail. Aggregates and direction only — per-piece results turn the
parent screen into a surveillance surface the student can feel, which damages the relationship
the tutor depends on.
**Files:** `frontend/src/parent/ParentDashboard.tsx`.
**Rules:** Spec §6. `UX-27`, `UX-29`. `PROD-2` — `not enough data yet` is a **first-class state
here, not an edge case**: a newly linked parent sees mostly that, and the screen must look
deliberate in that condition. `SEC-13` — the invite is single-use and already identifies the
child, so the parent lands directly with no intermediate explainer. Copy rule §4.1.3 — no
gendered pronoun; none is stored, and guessing from a name misgenders. **Depends on PRs 2, 3, 10,
15.**
**Tests:**
- `test_child_with_no_marked_work_renders_complete_screen` — no `0`, no empty bar, no empty panel
- `test_what_you_can_do_present_in_every_state`
- `test_no_gendered_pronoun_in_rendered_copy`
- `test_narrative_section_absent_when_none_exists` — stated absence, never an empty block
**Rollback:** Revert.
**Watch:** Read by people who cannot ask a follow-up question, and who read ambiguity as bad news
that then lands on the child. **Review the copy with the tutor before it ships.**

---

## 15. Stage 8 — Cold start

The surface that decides whether any of the preceding matters: a tutor who finds an empty product
on day one does not return to see it fill.

### PR 26 — Grade boundaries: defaults and an editor · L

**Does:** Resolves **D5**. Seeds published standard boundaries per subject and scale into the
global `Subject.grade_boundaries` default, and adds the control the spec's `Set them →` points at
— writing the **org-scoped `GradeBoundary` table**, which
`services/readiness_v2_ai.py:142-144` already reads and nothing currently writes.

**Does not:** Expose any write to `Subject.grade_boundaries`. `Subject` carries no
`organization_id` (`models/syllabus.py:9-25`), so a tutor-gated write there would change every
other organization's predicted grades — the precise failure `SEC-8` exists to prevent. Nor does
it silently backfill existing subjects: a tutor who deliberately left boundaries empty must not
find them filled in.

**Files:** `backend/seed/`, `backend/app/api/subjects.py` (or a new org-settings router),
`backend/app/schemas/`, `backend/app/services/grades.py` (precedence), a boundary editor under
`frontend/src/tutor/`.
**Rules:** Spec §7.1, §2.3. `SEC-8` — the reason the write target is `GradeBoundary`, not
`Subject`. `PROD-4` / `SEC-7` — the organization comes from the authenticated user, never from
the path. `SEC-11` / `BE-17` — the role gate is in the signature. `PROD-2` — a subject with no
boundaries in either source reports *"no grade boundaries set"* with the action that fixes it;
`services/grades.py:8-9` already returns `"—"`. `PROD-8` — an unconfirmed default is labelled.
`QA-12` — a write endpoint touching tenant data ships with its negative case.

**This PR closes half of `RISK-5`.** With a writer for `GradeBoundary`, the precedence becomes
statable and testable: **the organization's override if it has one, the global default
otherwise** — which is what the model's own docstring has claimed since it was written. PR 1 must
already have documented which source it reads; this makes that documentation true rather than
descriptive.

**Tests:**
- `test_seeding_is_idempotent_and_never_overwrites_a_tutor_adjustment`
- `test_boundary_write_targets_the_org_scoped_table_not_subject`
- `test_org_a_boundary_edit_does_not_change_org_b_predicted_grades` — the cross-tenant case, and
  the one that must fail before this PR is written
- `test_student_cannot_call_the_endpoint`
- `test_org_override_takes_precedence_over_global_default`
**Rollback:** Revert. Seeded rows persist harmlessly; the editor disappears.

### PR 27 — The empty room · S

**Does:** Between sharing the code and students joining, the tutor has a configured class with
nobody in it. A dashboard is the wrong surface — every panel would honestly render "not enough
data yet", and a screen of empty circles reads as broken rather than new. Renders spec §7.2:
joined count, names so far, code with *Share again*, and the sentence saying when readiness
appears.
**Files:** `frontend/src/tutor/GroupLayout.tsx`, class-overview component.
**Rules:** Spec §7.2, `PROD-2`. This state **changes between visits**, which is the whole
requirement — it gives a new tutor a reason to open MANARA tomorrow, in the exact window when the
product can otherwise show them nothing.
**Tests:** `test_class_with_zero_students_renders_empty_room_not_the_overview`.
**Rollback:** Revert.

### PR 28 — Seeding from tutor-supplied assessment · M

**Does:** Lets a tutor give MANARA a starting point once students have joined — recent mock
results, or their own assessment — rather than waiting weeks for evidence. Because students attach
themselves by invite code (`api/auth.py:181-184`, `:230`) a tutor **cannot create a student
record**, so this belongs after the room has filled and must be optional, because it may never
happen.
**Does not:** Add a mechanism the spec did not name. It states the requirement the existing
evidence mechanism must satisfy.
**Files:** `backend/app/models/readiness.py` (a new `EvidenceSource` member),
`backend/app/services/readiness.py` (`SOURCE_WEIGHTS`), an entry surface, frontend labels.
**Rules:** `PROD-10` — **added to `EvidenceSource` and given a weight in `SOURCE_WEIGHTS` in the
same change**, not a follow-up. `PROD-8` — self-declared, labelled **wherever shown**.
`DB-5` / `ADR-0007` — the enum is `native_enum=False`, so no migration; which also means nothing
forces an audit of the `if`/`match` chains over it, so audit them by hand here. Spec §7.3 — the
seed **loses weight as marked evidence arrives**, so the product self-corrects within weeks
rather than carrying a first impression indefinitely.
**Tests:**
- `test_seeded_source_decays_against_marked_evidence`
- `test_self_declared_label_reaches_every_rendering_surface`
- `test_every_consumer_of_evidence_source_handles_the_new_member`
**Rollback:** Revert. Existing rows keep an enum value nothing reads — acceptable, and the reason
`DB-5` chose non-native enums.
**Watch:** It feeds the Readiness Engine, which feeds every number in the product. The decay test
is the gate.

---

## 16. Stage 9 — Promote the rules

### PR 29 — File `UX-27` … `UX-33` as Active · S

**Does:** The spec's §12 opens seven rules as **Draft** because each needed code that had not
landed. By the end of Stage 8 it has. Moves them into §02 as Active — with `UX-30` carrying D3's
narrowing and its recorded reasoning — and closes the Known Gaps that spec §9 opened.
**Files:** `docs/volume-1-product-and-ux/02-ux-and-accessibility-standards.md`,
`docs/experience-design.md`, `docs/README.md`.
**Rules:** `GOV-1`, `GOV-3`, `CODE-21`, and the rule format in
`governance/documentation-authority.md`. Documentation-only, so it may go directly to `main`.
**Rollback:** Revert.

---

## 17. Dependency order

```
  PR 0   docs ───────────────────────────────────────────────── ship now

  PR 6   blank-question zero ──┐
  PR 7   reason labels ────────┼── no dependencies; ship first, in parallel
  PR 8   mislabelled controls ─┘

  PR 1   grade band ───┬──────────────────────────► PR 11  ClassReadiness
  PR 2   averaging ────┤                            PR 22  Progress
  PR 3   direction ────┤                            PR 21  Student home
  PR 4   coverage ─────┤
  PR 5   org timezone ─┴──► PR 17  aggregate ─┬───► PR 18  Today
                                              └───► PR 19  Class page

  PR 9   purple/orange ──┐
  PR 10  token migration ┼──► PR 12  mobile chrome ──► PR 16  navigation
  PR 11  ClassReadiness ─┘                                   │
                                                             ▼
  PR 13  prompt ──► PR 14  storage + job ──► PR 15 ──► PR 18, 19, 25

  PR 21 ─────────────────► PR 24  cleared state + orientation
  PR 3, 4 ───────────────► PR 23  Improvement tab    (own rank only — D6)
  PR 2, 3, 10, 15 ───────► PR 25  parent screen
  PR 26, 27, 28  cold start        (independent of the surface work)
  PR 29  promote the rules         (last)
```

**Critical path: PR 1 → PR 17 → PR 18.** Everything else moves around it.

**Decision deadlines:** D3 and D4 before PR 14 and PR 5 respectively — both are in Stage 1/4 and
both are expensive to change afterwards. D1 before PR 16. D2 before PR 14. D5 before PR 26.

**If the plan has to be cut, cut from the end.** Stage 8 is the highest-value remainder; Stage 6's
PR 23 is the most droppable single item. **Do not cut Stage 1** — everything later is a
presentation of it and has nothing to render without it.

---

## 18. Getting each PR to production

`main` is the only branch anything deploys from. Render builds the API from it; Vercel builds the
frontend. It is the sole *source* of what the user is running, not a guarantee of what they are
running: a deploy can fail or lag, and a failed one leaves the previous revision serving while
`main` has already moved. **Treat a commit as live only once its deploy is confirmed green**
(`INF-1`, `INF-3`).

For every PR:

1. **Branch off the latest `main`**, named `fix/…`, `feat/…`, `chore/…` or `docs/…`.
2. **Run everything locally before opening the PR:**
   ```bash
   cd backend  && .venv/bin/python -m pytest \
                && .venv/bin/ruff check . \
                && .venv/bin/ruff format --check .
   cd frontend && npm test && npm run build && npm run lint && npm run format:check
   ```
   `npm run build` (`tsc -b && vite build`) is **the only type check anywhere** — `npm test` does
   not type-check. **There is no Python type checker**, so every annotation in `backend/` is
   decoration nothing verifies; the tests are the only proof the backend works.
3. **Open a PR into `main`.** CI runs four jobs: the two linter pairs; `pytest`; `vitest` +
   `npm run build`; and Alembic `upgrade head` → `downgrade base` → `upgrade head` against a real
   Postgres 16. CI is a backstop, not a substitute for step 2.
4. **Merge once green and the tutor/owner approves.** The merge button is theirs, and a merge
   ships immediately with no further gate.
5. **Watch the deploy to green** before calling it shipped, and before starting anything
   downstream.
6. **Delete the branch.** A merged branch is finished — never reopen it or stack new work on it.

**Two PRs change the database** — PR 5 and PR 14. Their deploys run `alembic upgrade head` before
uvicorn starts; a failure there is a real outcome, handled by runbooks R2 and R4. **Merge each
alone**, on a day someone is watching.

**Four PRs warrant a pause after merge rather than immediately starting the next:**

| PR | Watch | For | How long |
|---|---|---|---|
| 5 org timezone | `/api/v1/me/today-lessons` across a UTC midnight | The weekday flipping at local midnight, not UTC | one day |
| 12 mobile chrome | A physical iOS device and an Android | Safe-area errors CI cannot see | before merge |
| 14 narrative job | `ai_usage_events` | Spend proportional to evidence volume | one day |
| 28 seeding | Readiness values on seeded students | The decay behaving as specified | one week |

---

## 19. Risk register

| # | Risk | Where | Mitigation |
|---|---|---|---|
| 1 | The narrative job's spend scales with evidence volume and nobody notices until the bill | PR 14 | Kill switch defaulting on; `ai_usage_events` watched a full day before PR 15 reads anything. `AI-17` — an unpriced model records `NULL`, never `$0`, so unpriced calls stay countable as `unpriced_call_count` |
| 2 | The improvement ranking exposes one child's academic trajectory to their classmates | PR 23 | **The board is not built; the ranking is.** Spec §5.2's anonymous-rows-with-deltas design was reviewed and rejected; the redesign releases only the reader's own rank, own delta and a denominator, and was re-reviewed to *ship with named changes* — all four applied. **Three residual risks are accepted and named in the PR**, the load-bearing one being that a whole class comparing ranks reconstructs the full order. Ship to one class first |
| 3 | PR 1 shifts colours for students near the old 70/50 thresholds, on a live surface | PR 1 | Correct behaviour. Tell the tutor before it ships |
| 4 | The averaging grade disagrees with the predicted grade and reads as a bug | PRs 2, 22, 25 | The pair never ships bare — the explaining sentence is in the same PR |
| 5 | A migration correct on SQLite is wrong on Postgres | PRs 5, 14 | The failure that has actually happened here (`RISK-3`). The suite never runs a migration; CI's `migrations` job on real Postgres 16 is what catches it. Both migrations use `DateTime(timezone=True)` — `0012_organizations.py` records the naive-column failure this repo already hit |
| 15 | `narratives` grows without bound and a missing index turns "latest for this group" into a sequential scan **that CI cannot detect** — the suite builds its schema from `Base.metadata` on SQLite and never runs a migration | PR 14 | The three indexes are named in PR 14 and declared on the model as well as in the migration (`DB-12`). Four of the five existing indexes exist only in migrations; do not add a fifth |
| 16 | `Narrative`'s two nullable FKs get read unconditionally, attaching a paragraph about one child to another child's parent | PRs 14, 15 | The `API-20` precedent: one accessor branching on `audience`, no caller touching either FK directly, and the authorization path in PR 15 goes through it |
| 6 | A response-schema change lands without its TypeScript mirror and nothing detects it | PRs 1–5, 15, 17 | `FE-4`, `API-15` — same PR, every time. Nothing checks the two agree (`RISK-6`) |
| 7 | Two grade-boundary sources — global `Subject.grade_boundaries` and the org-scoped `grade_boundaries` table | PRs 1, 26 | `RISK-5`, narrowed. The org table is **read** at `readiness_v2_ai.py:142-144` and **written by nothing**, so it is empty in production and v2 silently uses the global default for everyone. PR 1 documents which source it reads; PR 26 adds the writer and makes "org override, else global default" a real precedence |
| 17 | A settings screen writes `Subject.grade_boundaries` and changes every other organization's predicted grades | PR 26 | `Subject` has no `organization_id`. The write targets `GradeBoundary` only, and `test_org_a_boundary_edit_does_not_change_org_b_predicted_grades` must fail before the PR is written |
| 18 | The parent narrative schedule dies permanently on one transient AI outage | PR 14 | The schedule is a sweep re-derived from the `narratives` table, not a chain living in a job row. `jobs.py:229-233` is explicit that nothing watches `failed`, so a chain's death would be silent. The sweep is also re-enqueued idempotently at startup as a floor |
| 8 | v1 and v2 readiness disagree, so new surfaces contradict reports | Stages 5–7 | `RISK-5`. `analytics.py`, `reports.py` and `student_crm.py` still read v1 tables directly. Out of scope, but every new surface states which engine answered, as `/readiness/*` already does |
| 9 | The API is pinned to a single instance by the uploads disk, the in-process worker and the in-process rate limiter | PR 14 | `RISK-1`. The narrative job runs in that same worker, so adding load to it adds load to request serving (`BE-13`, `PERF-1`). **Do not let this plan become the reason someone scales out** — that is a correctness change, not a configuration change |
| 10 | The redesign lands on a tutor without warning | PRs 16, 18, 21 | Tell them. PR 16 is the one they will call "the redesign" |
| 11 | Stage 5–7 surfaces get built on unmigrated legacy markup and have to be rebuilt | Ordering | Stage 3 is a hard prerequisite, not a preference |
| 12 | D3 is answered after PR 14, so the prompt constraint changes | Sequencing | `AI-7` — a changed prompt bumps its version, and every stored narrative was written under the old one. Decide D3 first |
| 13 | The parent narrative reaches a parent before any human reads it | PR 15, 25 | D2's veto. If D2 is declined, this risk is accepted deliberately, not by omission |
| 14 | A student's failed login locks out every user behind the same proxy | pre-existing | `SEC-14` — throttling is per identifier, not per IP, and the counter is in-process and correct only while the API runs a single instance. Nothing in this plan changes that; nothing in this plan may break it |

---

## 20. Definition of done

The plan is complete when all three of the spec's §10 criteria hold, **verified by a person on a
real device, not by a test**:

| Role | Criterion |
|---|---|
| **Tutor** | Can determine whether anything needs their attention **immediately, without navigating** — from the first line of the home surface, on either device |
| **Student** | Can determine **what to do next immediately** — `DO` is above the fold on every supported viewport and never requires interpreting a score first |
| **Parent** | Can understand **whether their child is okay without navigation** — the first sentence answers it, and the screen states whether anything is required of them |

And the three structural checks hold everywhere:

1. **No surface renders a missing measurement as `0`, an empty bar, or an empty panel.** A
   section with nothing to report is not rendered. (`PROD-2`, `UX-19`, `UX-29`)
2. **No surface offers a control that requires a person to respond.** (spec §2.3)
3. **No surface, style or constant contains a literal grade or percentage threshold.** (`UX-28`)

### Final verification pass

Run against production, not a fixture, with one account per role:

| # | Check | Expected |
|---|---|---|
| 1 | Tutor with everything clear | Terminal sentence, no empty panels, no `0` |
| 2 | Tutor with a brand-new class | Empty-room surface, not a dashboard of absences |
| 3 | Tutor at 01:00 local | Today's lessons, not yesterday's |
| 4 | Tutor's home, any state | No student named except in an improvement (D3) |
| 5 | Student just joined | Complete home, every subject `not enough data yet`, no arrows |
| 6 | Improvement tab, any class | Your own rank and delta only. No classmate's name, delta or value in the rendered page **or the response body** |
| 6b | Improvement tab, bottom-half student | A band, never a bare last placing |
| 7 | Parent linked today | Complete screen, `WHAT YOU CAN DO` present, no gendered pronoun |
| 8 | Any subject with no boundaries | `no grade boundaries set` and a `Set them →` that works |
| 9 | Every surface, phone, iOS | Nothing under the home indicator; tab targets ≥44px |
| 10 | Every surface | `npm run build` clean; `contrast.test.ts` green |

Then Phase 2 begins from the baseline these criteria establish — introducing no new product
features, and not altering the information architecture settled here without an explicit new
decision recorded through `governance/change-process.md` (spec §11).

---

## 21. Review record

**This plan has been reviewed once, partially.** Recorded here so nobody mistakes an unreviewed
section for a reviewed one.

| Area | Status | Outcome |
|---|---|---|
| **Database & migrations** (PRs 5, 14) | **Reviewed** | Six defects found and fixed: the migration filename was inconsistent between D4 and §8; `DB-17` was over-applied to PR 5; PR 14 cited `DB-12` but named no indexes; `DB-5`/`DB-6` went uncited for the `audience` enum; the polymorphic-FK invariant was unstated; column types and lengths were unspecified. All six are folded into the text above. |
| **Architecture & sequencing** | **Not reviewed** | Whether every PR is genuinely independently shippable, and whether §17's dependency graph is complete, is asserted here and not yet checked by a second reader. |
| **Backend** — the job design | **Resolved by reading `workers/jobs.py`** | The self-re-enqueueing weekly job was a defect, not just a collision risk: at `MAX_ATTEMPTS` the worker sets `status = failed`, nothing watches that, and the schedule lived only in the job row — so one AI outage would have ended a parent's updates permanently and silently. Replaced with a sweep. |
| **Backend** — everything else (async correctness, DI, schema fan-out) | **Not reviewed** | PRs 1–5 add fields to `SubjectReadiness`, which `analytics.py`, `reports.py`, `student_crm.py` and `readiness_summary_v2.py` all consume. Nobody has checked those consumers. |
| **Frontend** (React, TanStack Query, the token migration) | **Not reviewed** | In particular: whether PRs 10 and 21/25 rewriting the same two files in sequence is one PR's worth of churn split into two. |
| **Security** — the boundary editor | **Resolved by reading the models** | `Subject` has no `organization_id`; the org-scoped `GradeBoundary` table exists, is read by v2, and is written by nothing. PR 26 now targets it, and the cross-tenant `PUT` this plan originally specified is rejected outright. |
| **Security** — the leaderboard | **Reviewed twice; both rounds applied** | Round 1 on spec §5.2's design: *do not ship* — eight vectors, the decisive one unaffected by any class-size gate. D6 then decided to build it, so PR 23 was redesigned to release only the reader's own rank, delta and denominator. Round 2: **ship with named changes** — floor raised 5 → 8 as coordination cost (explicitly *not* an anonymity mechanism), whole-roster collusion named as the load-bearing residual risk, passive rank-drift inference added as a third, and the top-half boundary and tie rule specified and tested. Three residual risks accepted, not closed. |
| **Security** — everything else (tenancy on the new endpoints) | **Not reviewed** | PRs 15, 17 add read surfaces over tenant data. The `SEC-7`/`SEC-8`/`API-7` requirements are stated per PR but not independently checked. |
| **Accessibility** (PR 12's tab bar, colour semantics) | **Not reviewed** | The plan states ≥44×44 touch targets and `viewport-fit=cover`. Focus order, `aria-current`, route-change announcement, live regions for `Updating…`, and the non-colour redundancy that must accompany the 🟢/🟡/🔴 banding are **not yet specified**. |

**Nothing in the unreviewed rows blocks Stages 0–3.** The two that must be closed before their PR
is written are the job-scheduling question (PR 14) and the two security questions (PRs 23, 26).

---

## 22. Delivery record — where the build differed from the plan

**PRs 0–29 are built, and PRs 0–20 are shipped.** "Shipped" on a heading means the work is
complete and verified against its own tests, not that it is serving traffic: `main` is the only
branch anything deploys from, and PR 12 additionally carries a merge gate CI cannot satisfy —
see the open items below. This section records only where the implementation *diverged*
from what the plan specified, so the next reader finds the reasoning rather than a silent
discrepancy (`GOV-1`, `GOV-3`).

| # | Plan said | Built | Why |
|---|---|---|---|
| 12 | A bottom tab bar honouring `slot` | As specified, plus a **More overflow sheet** | The student role carries eight destinations. Without an overflow the bar would either drop destinations or shrink below the 44px floor. `slot: "bottom"` items are never primary tabs — they fold into More, which preserves the split the sidebar already honoured. |
| 16 | Retire nine nav items to four | As specified; `/tutor/homework` **redirects to `/tutor/review`** rather than to a Library entry | The homework overview's two panels *were* the review queue; a redirect to a page that repeats them is what a bookmark holder actually wants. `HomeworkOverviewPage.tsx` is deleted rather than left orphaned. |
| 14 | `generate_narrative` re-runs are no-ops | As specified, plus a **`force` flag on the payload** | "Prepare again" (D2's correction) must produce new text even with no new evidence — that is the entire point of the control. Without the flag the explicit regenerate would silently no-op against its own staleness check. Ordinary re-runs are unaffected, so `BE-6` still holds. |
| 17 | Aggregate the home in bounded queries | As specified; grade-boundary overrides are **fetched once per organization** rather than via `resolve_grade_boundaries()` per class | Calling the shared resolver inside the class loop would have reintroduced exactly the per-class round trip the endpoint exists to remove. The precedence it implements (org override, else global default) is preserved verbatim. |
| 17 | Return a review count | Summed from the per-class counts, **not queried directly** | `Submission` is polymorphic and carries no `group_id`; a past-paper submission has `assignment_id` `None`. A direct join would drop past papers or raise (`API-20`). `services/groups.summaries()` already joins through `Assignment.group_id` correctly, so reusing it keeps one definition of "awaiting review". |
| 18 | Rebuild `tutor/today/*` | As specified; **four panels deleted** (`ActivityPanel`, `TeachingRhythm`, `DashboardHeader`, `EvidenceToAction`) | Their content is now inline in the rebuilt surface or superseded by the stored narrative. `DashboardHeader` carried PR 8's `aria-label` comment; the search control it documented no longer exists on this surface, so the reasoning no longer holds (`CODE-12`/`CODE-13` considered before removal, not after). |
| 18 | Verdict composed on the surface | Composition extracted to **`frontend/src/lib/verdict.ts`** | The copy rules (counts as words, zero clauses omitted, every verdict a full sentence) are §4.1–4.4 rules, not view code. Pure and unit-tested, they cannot drift as the surface evolves. |
| 20 | Queue traversal on the review page | As specified, **opt-in via `?queue=review`** | Arriving from an assignment page or a bookmark is a different task from working a queue. Gating the controls on the query parameter leaves that path exactly as it was and keeps "Reviewing 1 of 6" honest — it only ever counts a queue the tutor actually entered. |
| 21 | `DO` and `YOU DID` in spec §5.1's order | **`DO` first**, `YOU DID` second | §5.1 asserts both *"`DO` … is never below the fold on any supported viewport"* and *"`YOU DID` precedes any request for work"*. On a phone those cannot both hold. Its own mock puts `DO` first and this plan's test for the PR is named for that order, so `DO` leads. The reward-before-request intent is kept in the shape instead of the sequence: `DO` carries only what is due, so `YOU DID` is still above the fold on an ordinary day. |
| 21 | *"Chemistry mock in 12 days"* on the home | **Not built** | There is no student-visible source of *upcoming* assessments. `/me/assessments` returns scored ones only, and `/assessments` is tutor-gated. Building the line would have meant inventing a countdown from data that does not exist, which §2.3 and `PROD-1` both forbid. It needs an endpoint, and that endpoint is not in this plan. |
| 21 | *"Chemistry up 6 this month"* in `YOU DID` | As specified, from a new **`SubjectReadiness.month_delta`** | The obvious implementation reads a monthly delta from wherever a delta is cheapest, which is how a home surface ends up printing "up 6" beside a down arrow drawn from a different engine's series (`RISK-5`, `PROD-1`). `month_delta` is computed from the *same* points as `direction`, in the same function, so the two cannot disagree. |
| 22 | Progress compares predicted with averaging | As specified; the comparison is made on the **grades**, with the scores only deciding direction | Two scores four points apart inside one grade display as the same grade. A sentence claiming the student is "tracking above" beside two identical grades contradicts what the reader can see, so equal grades read as a match. |
| 23 | Rank computed from one score series | Each student is measured on **their own engine of record** — v2 where a scored snapshot exists, v1 otherwise | Ranking is on a *change*, not a score, so mixing engines across a class is not the hazard it first looks like: a student who gained a v2 series mid-window has no v2 point at the window's start, `period_delta` returns `None`, and they drop out of the ranking — which is exactly what the "full period" gate requires anyway. The payoff is that the reader's delta here is byte-identical to the one on their Progress page rather than a second number with the same label. |
| 23 | Months labelled `March`, `Feb`, `Jan` | **Rolling 30-day windows**, labelled *This month* / *Last month* / *Two months ago* | Calendar months are 28–31 days long, so the same progress scores differently in February than in March. The window is anchored to midnight UTC, which also satisfies the plan's "no timestamp precise enough to correlate a rank change to a single submission". |
| 25 | *"{name} hasn't submitted work in {subject} for {n} weeks."* | **Not built**; `WHAT YOU CAN DO` ships its two other states | The sentence needs a per-subject date of last marked work, which no parent-visible response carries. Adding it means a `max(Evidence.occurred_at)` per subject on the readiness read path — a query on the hottest surface in the product for one row of a copy table. The binding requirement (`WHAT YOU CAN DO` present in **every** state) is met without it and is tested. |
| 26 | Seed published boundaries into the global default | As specified for the five seeded subjects (already shipped with boundaries) and for **uploaded syllabuses**, which now fall back to the scale's standard split | Existing subjects are **not** backfilled: a tutor who deliberately left boundaries empty must not find them filled in. The editor offers the default pre-filled and labelled unconfirmed instead (`PROD-8`). |
| 26 | Precedence stated in `services/grades.py` | Moved to a new **`services/grade_boundaries.py`**, beside the writer | `grades.py` is pure decision math with no session (`BE-4`); resolving precedence needs a query. The resolver moved out of `readiness_v2_ai.py` — where it had put the rule governing every surface inside the module that talks to a model — and now sits next to `set_org_boundaries`, which is what makes the rule reachable rather than merely documented. |
| 28 | The seed "loses weight as marked evidence arrives" | A **relative** attenuation (`w / (1 + marked_count)`), not the existing time decay | The half-life discounts a seed and a real mark equally, so a topic that goes quiet keeps the tutor's first impression at full *relative* weight indefinitely. The seed row is never deleted — it is the record of what the score was built from (`PROD-1`) — only outweighed. |

**The open items:**

- **PR 12's device check.** ≥44×44 targets and `viewport-fit=cover` are implemented and the
  overflow is tested, but a **safe-area error cannot be caught by CI** — the plan's own
  instruction to verify on a physical iOS device and an Android before merging still stands.
- **PR 14's spend watch.** The narrative job adds recurring model spend proportional to evidence
  volume. `NARRATIVE_ENABLED` is the kill switch (instant, no deploy), and `ai_usage_events`
  should be watched for a day before the surfaces are relied on, exactly as §18 specifies.
- **PR 23's single-class rollout.** The plan calls the Improvement tab the highest product risk
  in the batch — a ranking shown to children — and asks for it to reach one class first, with
  that tutor asked what their students said about it before it goes wider. Nothing in the code
  enforces that; it is a rollout decision. The one cheap mitigation is a sentence to the tutor
  when the tab is introduced: **do not ask students to share this screen.** A tutor soliciting
  rank screenshots turns the voluntary leak documented as residual risk 1 into a compelled one,
  with the power asymmetry that implies.
- **PR 25's copy review.** The parent screen is read by people who cannot ask a follow-up
  question and who read ambiguity as bad news that then lands on the child. The plan asks for
  the copy to be reviewed with the tutor before it ships. The strings are in
  `frontend/src/lib/parent.ts`, in one place, for exactly that reason.

**The accessibility row above is still unreviewed and now has more surface to cover:** the
`Updating…` live region ships in PR 18's narrative section and PR 19's, and the 🟢/🟡/🔴 banding
now appears on the class strip. Non-colour redundancy and route-change announcement remain
unspecified.
