# Phase 9 (Onboarding and tutor home) — agent handoff

**Audience: agents, not humans.** Dense and declarative on purpose. Assertions are either
`VERIFIED` (checked against the code at the commit below) or sourced to a file path or rule ID.
Anything unverified is marked `UNVERIFIED`. Do not upgrade an `UNVERIFIED` claim without
testing it.

| Field | Value |
|---|---|
| Phase | 9 — Onboarding and tutor home |
| Spec of record | `docs/avora-new-state-august-16.md` §"Phase 9" (~line 1550), **as revised by** `docs/tutor-structure-and-onboarding.md` (docs branch) — the revision wins where they differ |
| Decisions it implements | AV-56 (amended by D1), AV-60, AV-66, AV-67, AV-74, AV-47, AV-48, AV-101, AV-105–107; owner decisions D1–D6 |
| State as of | `3d1f93a` on the default branch (`claude/igcse-os-planning-q8be0t`) |
| Handoff written | 2026-10-05 |
| Migration head | `0066_weekly_sends` — Phase 9's first migration is `0067` |
| Previous phase | Phase 8 CLOSED — PRs #128–#134; see `docs/phase-8-status.md` |
| Tasks done | none |

---

## 1. Stop first — three owner questions

No code before these are answered. Ask them in one `AskUserQuestion` call.

1. **Navigation (blocks 9.3).** Two owner statements conflict.
   - 2026-10-04: AV-105's ten-item nav is unchanged (Overview · Review · Homework · Classes ·
     Students · Mocks · Past papers · Readiness · Reports · Library).
   - 2026-10-05, coherence pass: "keep the structure; fix the skeleton only", and the sidebar
     shipped as Today · Classes · Review · Readiness · Reports · Papers & mocks · Library ·
     Settings (`VERIFIED`, `frontend/src/App.tsx:103–115`).
   - Ask: keep the eight shipped, or rebuild to AV-105's ten? The student sidebar has eight
     items against AV-106's six, so ask the same for student and parent.
2. **Settings layout (blocks the checklist's links).** D3 (Account → Subject → Class) was
   rejected. Settings is one page with seven sections (`VERIFIED`, `tutor/SettingsPage.tsx:29–35`).
   Ask: is that the final shape, or does the owner want something else?
3. **How "where are you up to" is stored (blocks 9.1b).** Recommended: a "before Avora" lesson
   per class holding the ticked topics as `lesson_topics` — keeps `PROD-14` with no second
   coverage source. The alternative needs a `PROD-14` amendment.

Do not re-ask D1, D2, D4, D5, D6 or the phase order. They are settled.

---

## 2. Tasks and order

| ID | Task | Size | Depends on |
|---|---|---|---|
| 9.1a | Onboarding state: derived checklist endpoint + "reviewed this default" acknowledgements (migration 0067) | M | Q2 |
| 9.1b | "Where are you up to?" capture, and plan drafting that starts from it (coherence C.4) | M | Q3 |
| 9.1c | Onboarding flow UI: Required steps block, Defaulted steps are one-tap; replaces `Welcome` | L | 9.1a, 9.1b |
| 9.1d | Setup checklist card on Overview; "default" / "set by you" state on every defaulted value | M | 9.1a |
| 9.2 | Tutor home: the one good-news figure (AV-101) | S | — |
| 9.3 | Navigation rebuild (coherence C.5) — **only if Q1 says so** | M | Q1 |

**Waves:** `9.1a ∥ 9.1b ∥ 9.2` → `9.1c ∥ 9.1d` → `9.3` → phase sweep. 9.1c and 9.1d both touch
`tutor/today/TodayDashboard.tsx`; give each disjoint ownership or sequence them.

---

## 3. What exists today — `VERIFIED` at `3d1f93a`

- **No onboarding state is stored.** Nothing in `backend/app` models an onboarding step.
- **First run** is `Welcome` in `frontend/src/tutor/today/TodayDashboard.tsx:236`, shown only
  while `class_count === 0` (line 106). It disappears once one class exists, boundaries or not.
- **Completion is derivable** from existing data: subjects and chapters, `boundaries_missing`
  (`services/today.py:216`), `class_count` (`today.py:228`), org time zone, schedule slots, an
  accepted plan. Only "reviewed a default" needs new storage.
- **Org settings already exist** from Phase 8: `weekly_send_weekday` (6), `weekly_send_hour`
  (17), `ai_language` ("en"), edited via `PUT /me/organization` and `tutor/WeeklySendSetting.tsx`.
  Onboarding step A reuses these — do not add a second copy.
- **Plan drafting ignores taught topics.** `services/plan_drafting.py` has no reference to
  `lesson_topics`; `plan_lessons.py` writes them. A class taught for 90 days drafts from
  chapter 1.
- **Overview was reworked in the coherence pass (#123, #127):** week strip, agenda, per-class
  cards, needs-you with reasons. `services/today.py` (334 lines) + `today_overview.py` (819).
  So 9.2 is small.
- **The good-news figure is absent.** No auto-finalized-marks count in `today*.py`.
- **Library split is done (#121).** Settings left Library; do not redo it.

`UNVERIFIED`: line numbers quoted in `tutor-structure-and-onboarding.md` §4
(`plan_drafting.py:150`, `:180`, `today.py:209`) predate Phases 7–8. Re-locate before citing.

---

## 4. Task briefs

### 9.1 — Onboarding (revised)

Step table: `docs/tutor-structure-and-onboarding.md` §4. Summary:

| Step | Kind |
|---|---|
| A — time zone, AI language, weekly send day | Defaulted |
| S1 — board + level, syllabus upload, review tree | **Required** |
| S2 — grade boundaries | Defaulted, **saved explicitly, labelled unconfirmed** |
| S3 — teaching guidance | Optional |
| S4 — marking rules, mistake categories, weak threshold | Defaulted |
| C1 — class + timetable | **Required** |
| C2 — where are you up to (one tap for "starting fresh") | **Required** |
| C3 — exam date, pace, past-paper start, breaks | **Required** |
| C4 — accept the teaching plan — the finish line (AV-60) | **Required** |

- The backend decides what is complete (`SEC-10`). The frontend gate is not the control.
- Server-side and resumable: closing the browser mid-flow loses nothing.
- Inviting students is outside the flow (AV-60).
- A second subject or class later reuses the same steps; the checklist is per subject.
- Never render an unset value as if set (`PROD-2`); unconfirmed boundaries say so (`PROD-8`).
- New table carries `organization_id` (`PROD-3`); gate with `TutorUser` (`BE-17`); ship the
  negative auth test (`QA-12`).

### 9.2 — Tutor home

Add one figure: *"47 questions marked — roughly 3 hours of marking."* The count is
auto-finalized marks in the period and must trace to rows (`PROD-1`). The time is an estimate.
**"Roughly" is load-bearing — never drop it** (AV-101). Extend `today.py`; do not replace it.
Ask the owner for the minutes-per-question figure — do not invent it.

### 9.3 — Navigation

Per Q1's answer. Old URLs keep working (`also:` in `App.tsx` is the existing pattern).
`frontend/src/test/Nav.test.tsx` pins the current items.

---

## 5. Process

- Default branch is `claude/igcse-os-planning-q8be0t`. Nothing commits to it directly; one PR
  per task, branched off the latest default. Stage by path; never `git add -A`.
- Docs go only on `docs/phases-4-to-6`, never into the app branch.
- Prefix `gh` with `env -u GITHUB_TOKEN`.
- Owner delegated merging: push, read the review bots, fix, merge when CI is green on the head
  SHA.
- Subagents on Sonnet, orchestrator on Opus; two reviewers per task, orchestrator reads the
  diff, one sweep per phase. **Sonnet's weekly limit is hit until 2026-10-09 15:00 Qatar** —
  before then, no subagents: self-review and say so in the report.
- Run targeted tests locally; the full backend suite exceeds 10 minutes, so CI (~18 min) runs
  it. **Check the test result before pushing** — a piped `| tail` hid a failure in Phase 8.
- A response-schema or docstring change regenerates `frontend/openapi.json` and `schema.d.ts`
  in the same PR (`FE-4`).
- Before staging, delete iCloud duplicates: `find . -name "* 2.*"`.
- Never change the app's colours or motion. Use they/them for the owner.
- Tests never call real AI, Zoom, Google, WhatsApp or SMTP.
- Never make a product decision without the owner's approval; question the plan, then ask.

---

## 6. Carried over, not Phase 9

- Independent review of #131–#133 (self-reviewed only) once Sonnet returns.
- Render deploy of migrations 0065/0066 not confirmed green.
- Constitution docs for Phases 7–8 endpoints (`GOV-1`).
- `/weekly/:id` deep link lost through login; invites by message; web push.
- Avora agent v1 scope (read-only vs proposals) — unanswered, and after Phase 9.
