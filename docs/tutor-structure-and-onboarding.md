# Structured Avora for tutors — onboarding and app structure

**Status:** DESIGN BRIEF — decisions marked *approved* are the owner's (2026-10-04); items
marked *proposed* await the owner. Revises Phase 9.1 of `docs/avora-new-state-august-16.md`
and parts of `docs/experience-design.md` §4 and §7. Nothing here is built.

## 1. Why

Tutors choose Avora for **structure and comfort**: one yearly loop — *teach → assign → mark →
readiness → iterate* — with everything in its place. The app's features work, but it does not
yet *feel* structured: setup is scattered across Library, there is no line between what the
loop **needs** and what is a **preference**, and several pages have no single job
(walkthrough findings: `docs/coherence-pass-after-phase-7.md`). The owner will not sell the
promise of structure until the app keeps it.

**The organising rule: every tutor page answers one question in the yearly loop, at one
level.** A page that answers two is split; a page that answers none is removed.

## 2. Owner decisions (2026-10-04)

| # | Decision | Status | Amends |
|---|---|---|---|
| D1 | **Core steps block; the rest is guided.** Only what the loop needs blocks onboarding. Everything else ships with a default, labelled *default — review*, and sits on a persistent setup checklist. | approved | AV-56 (all steps blocking) |
| D2 | **"Where are you up to?"** — onboarding captures the topics each class has already been taught, so coverage starts correct and the plan drafts from there. | approved | new; absorbs coherence C.4 |
| D3 | **Settings by level: Account → Subject → Class.** Each setting lives at exactly one level and is edited where it was first set. | proposed — owner unsure; decide from mockups | AV-110 |
| D4 | **Library holds material, not settings.** Settings leave Library (see §5). Whether Library remains a tab at all is open. | proposed (owner raised it) | AV-110, AV-111 |
| D5 | **Avora agent comes later and separately** (after Phase 8); it may later drive these same server-side onboarding steps. | approved | — |
| D6 | **No in-app person-to-person messaging.** The agent is rate-limited. | approved | confirms experience-design §2.3 |

## 3. Settings by level (D3)

| Level | Holds | Today lives in |
|---|---|---|
| **Account** | time zone (org + own), language for AI text, weekly send day, custom criteria, usage | Settings, Library → Settings |
| **Subject** | syllabus tree + document, teaching guidance, grade boundaries, marking rules ("AI marking agreement"), mistake categories, readiness weights + weak threshold | Library (6 items), Preferences |
| **Class** | timetable, exam date, where you're up to, teaching plan, students & parents | class tabs (Schedule, Students) |

Readiness weights are already stored as an account row plus optional per-subject override
(`readiness_config.py`) — the Subject level shows the override with "uses account default"
when there is none.

## 4. Onboarding (revises 9.1)

Two kinds of step. **Required** — the loop cannot run without it; the backend refuses to
mark onboarding complete without it (`SEC-10`: the frontend gate is not the control).
**Defaulted** — pre-filled; the tutor confirms with one action or leaves it on the checklist.

| # | Level | Step | Kind | Without it (code) |
|---|---|---|---|---|
| A | Account | Time zone · AI language · weekly send day | Defaulted (zone browser-detected at signup) | NULL zone → dates in UTC, "may be a day off" (`TimezoneSetting.tsx`) |
| S1 | Subject | Board + level, syllabus upload → review chapter/topic tree | **Required** | a subject exists only by applying an upload; plan fails `no_chapters` (`plan_drafting.py:150`) |
| S2 | Subject | Grade boundaries | Defaulted (`DEFAULT_BOUNDARIES`) — **saved explicitly, labelled unconfirmed** | no predicted grade anywhere (`boundaries_missing`, `today.py:209`) |
| S3 | Subject | Teaching guidance | Optional | only the plan drafter reads it (`plan_drafting.py:180`) |
| S4 | Subject | Marking rules · mistake categories · weak threshold | Defaulted / skippable | marking falls back to board/level/chapter notes; categories auto-written by `ensure_categories`; threshold 60% |
| C1 | Class | Class name + timetable | **Required** | no lessons, no plan pace pre-fill (`timetable_defaults`) |
| C2 | Class | **Where are you up to?** — tick topics already taught, or "starting fresh" | **Required** (one tap if fresh) | plan restarts at chapter 1; coverage under-counts |
| C3 | Class | Exam date · lessons/week · length (pre-filled from timetable) · past-paper start · breaks | **Required** | `request_draft` refuses without saved inputs |
| C4 | Class | **Accept the teaching plan** — the finish line (AV-60) | **Required** | no `behind_classes`, no next-lesson suggestion |
| — | Class | Invite students, link parents | outside the flow (AV-60) | the empty room (experience-design §7.2) |

Order follows the code's dependencies: subject → (boundaries, rules, categories, class) →
timetable → plan inputs → draft → accept. Account first because slots and plan dates mean the
org's zone.

**State.** Server-side and resumable. No onboarding state is stored today; completion of every
Required step is **derivable** from existing data (`GET /subjects`, `boundaries_missing`,
`class_count`, org timezone, schedule slots, `accepted_plan_for_group`). New storage is needed
only for "the tutor reviewed this default" acknowledgements.

**After onboarding** the setup checklist is a card on Overview, per subject ("3 of 5
reviewed"), until every Defaulted item is reviewed. It never blocks.

**Every defaulted value shows its state wherever it appears** — *default* or *set by you* —
the visible form of "structured" (`PROD-8` already requires unconfirmed boundaries to say so).

### Open design choice — how C2 is stored

- **(a) A "before Avora" lesson** per class holding the ticked topics as `lesson_topics`.
  Coverage keeps deriving from `lesson_topics` (`PROD-14`) with no second mechanism; plan
  drafting excludes covered chapters. *Recommended.*
- (b) A separate "already taught" marker — clearer in the data, but a second coverage source,
  which `PROD-14` forbids without amendment.

## 5. Library (D4)

| Today in Library | Goes to |
|---|---|
| Past papers, Booklets | **Past papers** tab (AV-105) |
| Mocks | **Mocks** tab (AV-105) |
| Class readiness | **Readiness** tab (AV-112) |
| Syllabuses, Teaching guidance | Subject settings |
| Grade boundaries, AI marking agreement, Mistake categories | Subject settings |
| Preferences | Subject settings (with account default) |
| Settings | Account settings |

**Left in Library:** classifieds (chapter question sets that homework is built from), syllabus
documents, files and recordings shared with classes. **Open:** keep Library as "my teaching
material", or move classifieds into each subject and drop the tab.

## 6. App structure — every page intentional

- **Navigation per AV-105**, with each destination's one-line job written in the nav spec.
- **The class page is the class's year**: where we are in the plan, what changed, what's next.
  The repeated readiness header on every tab goes.
- **Settings are three levels with breadcrumbs** (Account › Chemistry 4CH1 › Year 10
  Chemistry). Preferences and Library-as-settings dissolve into them.
- **One readiness format everywhere** (grade + status + %) — coherence C.6.

## 7. Sequencing (proposed — owner confirms)

Phase 7 → coherence pass → Phase 8 → **Phase 9 (this brief)**. Phase 9 absorbs coherence C.4
(plan from what's taught, via C2) and C.5 (navigation, Library split), since both are the
same work as D2–D4. The coherence pass keeps C.1–C.3 and C.6–C.8.

## 8. Next

Clickable mockups of: the onboarding flow; the Account → Subject → Class settings; the class
page as "the class's year"; Library kept vs. removed — so D3 and D4 can be decided by looking.
