# Phase 9 — Onboarding and tutor home: status

**Built 2026-10-05 to 2026-10-06, PRs #135–#143. Closed 2026-10-06.** This records what shipped, the owner
decisions that changed the plan, what was decided on the owner's behalf, and what is still
owed. The plan is in `avora-new-state-august-16.md` (Phase 9); the handoff was
`phase-9-handoff.md`.

## Owner decisions (2026-10-05 and 2026-10-06)

| Decision | Effect |
|---|---|
| **Rebuild the tutor sidebar to AV-105's ten items**; student and parent sidebars stay as shipped. | 9.3c. The sidebar is Overview · Review · Homework · Classes · Students · Mocks · Past papers · Readiness · Reports · Library · Subject setup · Settings. |
| **A new tab, "Subject setup"** (the owner's name), holds everything that belongs to a subject. Settings keeps the account. | 9.3a. Settles the Settings question D3 left open; replaces the first answer ("keep one page, regroup"). |
| **"Where are you up to" is a separate "already taught" marker**, not a "before Avora" lesson. | 9.1b. `PROD-14` amended: coverage has two sources and no third. |
| **4 minutes per auto-marked question**, shown as "roughly" and labelled an estimate. | 9.2. |
| **Grade boundaries in onboarding are one tap, "use these for now"**; none are saved at subject creation. | With no rows a subject has no predicted grade and the checklist says "Not set", never "default". |
| **Library is filled** with classifieds and the files and recordings shared with classes. | 9.3b. A read-only record. |
| **Settings is the last sidebar item.** | 9.3c. |
| **Build the cross-class Homework and Students pages.** | 9.3c. |
| **"Every tutor without a teaching plan needs" the onboarding flow.** | 9.1c. `in_flow` is true while none of the tutor's classes has an accepted plan — tutors already running classes included. |
| **A tutor in the flow who already has a class keeps the dashboard underneath the guide.** (Yes to the sweep's proposal.) | 9.1c. With no class the guide is the whole page; with one it sits above the working dashboard, titled "Finish setting up", and the checklist card is left out. Nobody loses the agenda, lesson reminders, "Schedule a lesson" or the weekly-send link, and a class that cannot get a plan is not stranded. |

## What shipped

| Task | PR | What |
|---|---|---|
| 9.2 | #135 | Good-news line on the tutor home: "N questions marked for you this week — roughly H of marking. An estimate, at 4 minutes a question." `today.auto_marked_count`; `WeekGlance` gains three fields. |
| 9.1b | #136 | Migration **0067**. `taught_before_topics` and `groups.taught_before_answered_at`; `GET`/`PUT /groups/{id}/taught-before`; coverage readers union the marker; the plan drafter skips fully taught chapters and refuses with `all_taught` when nothing is left. |
| 9.3a | #137 | **Subject setup** at `/tutor/subject-setup`: syllabus, boundaries, teaching guidance, marking rules, mistake categories, preferences, under one subject picker held in the URL. Old setup URLs and Settings hashes forward. |
| 9.1a | #138 | Migration **0068**. `setup_acknowledgements`; `GET /onboarding` derives what is set up from the data; `POST /onboarding/acknowledgements` records that a default was reviewed. |
| 9.3b | #139 | **Library**: `GET /resources` and a page listing classifieds by subject and chapter, files, and recordings by class. |
| 9.1d | #140 | Setup checklist card on the home, the "where this class is up to" editor on the class Syllabus tab, and the four state labels. `TopicOut.chapter_id`. |
| 9.1c | #141 | The onboarding flow as the tutor's home: nine steps in order, driven by the server's `next_step`, alone for a tutor with no class and above the dashboard for one who has a class. The old three-card Welcome is deleted. |
| 9.3c | #142 | The twelve-item sidebar; `GET /assignments` and `GET /students`; the cross-class **Homework** and **Students** pages; the "Papers & mocks" hub retired. |

| sweep | #143 | A changed "taught before" answer marks the class's plan draft stale and refreshes the plan view. Three Phase 9 routes added to the shared tutor-only authorization list. |

## Rules this phase established

- **Onboarding state is read from the data, not stored.** A Required step is done when the rows
  that make it real exist. Only acknowledgements are stored. The server decides who is in the
  flow and what the next step is (`SEC-10`); the client only renders it.
- **Four states, never blurred** (`PROD-2`): "Avora's default, not reviewed yet", "Avora's
  default, kept by you", "Set by you", "Not set". A stored value that equals the default stays
  "default" until acknowledged — a default written as an ordinary row is not a choice.
- **Boundaries have no default in force.** No rows means no predicted grade anywhere, so the
  state is "Not set".
- **Coverage has two sources and no third** (`PROD-14`, amended): `lesson_topics` and the
  taught-before marker, read through `services/taught_before.py`.
- **A capped list says so.** `GET /assignments` and `GET /students` return
  `{items, truncated, limit}`.
- **The hand-in count is of current students.** "N of M handed in" tallies only students in
  the class now, so N cannot exceed M after someone leaves.

## Decided on the owner's behalf

Each was reported at the time; none has been objected to.

- The home's dashboard requests are not held back while the "in the flow?" answer loads. A new
  tutor makes one unused set of requests once; every other tutor's home loads no slower.
- The "Papers & mocks" hub page was retired with the sidebar split. `/tutor/papers` forwards
  to Past papers, and Booklets is linked from the Past papers page.
- "Today" was renamed "Overview" in the sidebar and page title, as AV-105 names it. Routes,
  components and "today" meaning the calendar day are unchanged.
- A submission page lights **Review** in the sidebar.
- On a phone the bar shows Overview, Review, Homework and "More"; the other nine sit in the
  More sheet, which now scrolls and closes with Escape. This uses the existing overflow rule.
- The cross-class lists are capped (200 homework, 500 students) rather than paginated.
- Not built, deliberately: overdue wording on the Homework page, search by class name on
  Students, a "create homework" action on the Homework page.

## Known gaps

| Gap | Where recorded |
|---|---|
| The three Phase 9 lists are capped, not paginated; `/resources` does not signal a cut-off. | `05-api-standards.md`, Known Gaps |
| A topic counted as covered through the taught-before marker is not labelled tutor-declared outside the editor (`PROD-8`). | `01-product-architecture.md`, `PROD-14` |
| The good-news count undercounts: saving a review clears `auto_finalized` on every mark in that submission. It is also organization-wide while the copy says "for you", and re-finalizing moves a piece into the current week. | `services/today.py` docstring |
| Switching subject on Subject setup discards unsaved drafts in every section. | here |
| **An admin with no classes of their own, or a second tutor joining an organization, is in the flow** and is steered to create a class, because onboarding counts only the caller's own classes while subjects are the organization's. `/assignments` and `/students` show an admin the whole organization; `/onboarding` and `/resources` do not. Found by the sweep; not fixed. | here |
| **A tutor whose class cannot get a plan stays in the flow indefinitely** (`all_taught`, or `not_enough_lessons` when the exam is too close). They keep the dashboard underneath, but the guide never closes and there is no "no plan needed yet" action. With two classes the guide may keep pointing at the one that cannot be drafted. | here |
| Saving "taught before" queues no readiness recompute, so the class report (live) and Readiness (last snapshot) can disagree until the next recompute. | `services/taught_before.py` docstring |
| A class created from the Classes page does not invalidate the onboarding and home caches; the guide shows its old step for a moment until the refetch lands. | here |
| The More sheet has no arrow-key handling despite `role="menu"`. | here |
| **No Phase 9 screen has been looked at in a real browser or on a phone.** Tests cover behaviour, not layout. | here |

## Still owed

1. **Owner:** confirm the Render deploys of migrations **0067** and **0068**.
2. **Owner:** look at Subject setup, Library, the checklist, the onboarding flow, and the
   Homework and Students pages on a phone.
3. Constitution updates for the Phase 9 endpoints and tables beyond the two rule changes made
   (`GOV-1`): §04 module and table counts, §05 endpoint list, §06 the two new tables.
4. Carried over, not Phase 9: an independent review of #131–#133; the Render deploy of
   0065/0066; constitution docs for Phases 7–8; the `/weekly/:id` deep link; invites by
   message; web push; the agent's v1 scope.
