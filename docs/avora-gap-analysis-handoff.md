# Avora — gap analysis and build plan

## Context

A 39-domain functional specification was presented for Avora. This maps it against the actual
repo (52 tables, 21 migrations, 23 routers, 25 services, ~12,750 lines of Python + the React
app), then plans the work the owner has approved.

Messaging/Communication (spec §34) is dropped at the owner's instruction and does not appear.

**Headline:** the centre of the spec — the readiness/evidence loop — is built and is more
sophisticated than the spec describes. The edges are absent, and several are recorded
non-goals. One domain, the Mistake Engine, is half-built in a way that silently inflates
readiness scores.

---

## Scorecard (38 domains)

| # | Domain | State | Evidence |
|---|---|---|---|
| 1 | Auth & Identity | **Partial** | email/password + refresh cookie + `token_version`; Google OAuth is Classroom-only, not login |
| 2 | Organizations | **Built** | `models/orgs.py` — only `id` + `name`; no branding, no AI config |
| 3 | Student Management | **Built** | `models/crm.py`, `services/student_crm.py` |
| 4 | Parent Management | **Thin** | `ParentLink`; `ParentDashboard.tsx` renders readiness cards only |
| 5 | Tutor Management | **Partial** | tutor is a `User` role; no availability, no teaching history |
| 6 | Course Management | **Built as Subject** | `Subject` + `GradeBoundary` |
| 7 | Curriculum Engine | **Partial** | `Topic.parent_id` self-ref gives depth; no Unit/Chapter/Objective entities |
| 8 | Class Management | **Built** | `Group`, `GroupMember`, `ScheduleSlot` |
| 9 | Lesson Management | **Skeleton** | date, duration, notes, topics, observations — nothing else |
| 10 | AI Lesson Brief | **Built (shallow)** | `api/groups.py:238` — group-level, weak topics only, **empty system prompt** |
| 11 | Homework System | **Built** | `Assignment`, `AssignmentQuestion`, `Classified` |
| 12 | Submission Mgmt | **Built** | polymorphic `Submission`; no version history |
| 13 | AI Marking Pipeline | **Built** | `services/marking.py` + `extraction.py`, auto-finalize + review + `RemarkRequest` |
| 14 | Assessment System | **Partial** | manual tutor entry; no quiz engine, no timed runner |
| 15 | Past Paper Workspace | **Built** | `PastPaper*`, `SitPastPaperPage.tsx` |
| 16 | **Mistake Engine** | **⚠ Dead schema** | model + factor exist; **nothing writes rows** |
| 17 | Readiness Engine | **Built, best-in-repo** | two-layer: 7 pure factors → AI synthesis |
| 18 | Topic Mastery | **Built (no states)** | numeric only; no Learning/Practicing/Mastered machine |
| 19 | **Study Planner** | **Absent** | only `ReadinessSnapshot.recommended_revision`, a prose blob |
| 20 | Calendar | **Absent** | `ScheduleSlot` is recurring slots; no events, no sync |
| 21 | AI Study Coach | **Partial** | `tutor_chat.py` + 42-line `student_context.py` |
| 22 | Knowledge Base | **Different thing** | tutor's teaching prefs for prompts, not a student resource index |
| 23 | Files | **Partial** | 20MB, PDF/JPEG/PNG/WebP; magic-byte validated; no versioning/virus scan |
| 24 | **Attendance** | **Absent** | zero occurrences anywhere |
| 25 | Notifications | **Absent** | no channel, trigger, or model |
| 26 | Reports | **Built** | `Report` w/ student/tutor/parent audiences, `generate_report` job |
| 27 | Analytics | **Partial** | group-level only |
| 28 | Tutor Dashboard | **Built** | `tutor/today/` |
| 29 | Student Dashboard | **Built** | `StudentHomePage.tsx` |
| 30 | Parent Dashboard | **Thin** | readiness only |
| 31 | Search | **Absent** | no global search, no embeddings, no retrieval |
| 32 | AI Summarization | **Partial** | reports + class brief only |
| 33 | AI Recommendations | **Partial** | inside snapshots; not a surface |
| 35 | Integrations | **3 of 9** | LLM providers ✅, storage ✅, OCR ✅ (done differently — vision model, no OCR vendor), Classroom ⚠️ code-complete but no live credentials; Drive/Zoom/Teams/GCal/Outlook absent |
| 36 | Audit Logs | **Narrow** | `MarkOverrideAudit` only |
| 37 | Billing | **Absent (by decision)** | metering built; billing is a recorded non-goal |
| 38 | Admin Panel | **Absent** | `admin` role exists, no surface |
| 39 | AI Context Engine | **Seed only** | 42 lines reading one CRM aggregate |

Roughly **11 built · 13 partial · 14 absent**.

---

## The four findings that matter

### 1. The Mistake Engine is a dead schema — and it's inflating readiness right now

`Mistake` is defined (`models/readiness_v2.py:49`), queried
(`services/readiness_v2.py:266`), and scored (`readiness_factors.py:239`). The only code in
the repo that constructs a `Mistake(...)` is `tests/test_readiness_v2.py:115`.

Not a missing feature — a live bug. From `readiness_factors.py:242`: *"zero mistakes with
total_questions>0 is a clean record, not 'no data'."* So every student with marked questions
scores a **perfect** mistake-analysis factor, weighted into readiness as if it were evidence.
That violates `PROD-1` and `PROD-2`. `docs/manara-architecture.md` claims mistake tagging lives
in `services/marking.py`; the marking prompt (`prompts.py:31`) never asks for it.

### 2. Lessons are the spec's spine and the code's stub

`models/lessons.py` is 55 lines. Missing: objectives, status lifecycle, files, recording,
transcript, whiteboard, attendance, AI summary, follow-up tasks. The AI Lesson Brief is
group-level and its template is registered with an **empty system string** (`prompts.py:153`).

### 3. Attendance does not exist, and four domains depend on it

Zero hits in models, migrations, API, frontend. `LessonObservation` already models the
lesson×student join; attendance is a status column away.

### 4. Subtopic evidence never reaches its parent topic (confirmed live bug)

`seed/load_syllabus.py:39-49` builds a **nested** topic tree — `parent_id` set from
`children`, codes like `2.1`, `2.3`. But `services/readiness_v2.py:317` selects topics flat:

```python
topics = (await session.scalars(select(Topic).where(Topic.subject_id == subject_id))).all()
```

`parent_id` is ignored entirely. Every topic — parent and child alike — gets its own
`FactorEvaluation`, scored only from questions tagged *directly* to it. Since questions are
tagged to specific subtopics, **parent topics report `no_data` while their children hold all
the evidence**, and `syllabus_coverage` counts parents and leaves as peers, so a finely-split
chapter is over-weighted against a coarse one.

This is the same class of defect as the Mistake Engine: no error, no exception, just a score
that quietly means something other than what it claims (`PROD-1`).

### 5. Context is assembled ad hoc at seven call sites

| Surface | Tutor KB | Student context | Note |
|---|---|---|---|
| `marking` | ✅ subject-scoped | ❌ | `marking.py:247` |
| `extraction` (classified) | ✅ | ❌ | `extraction.py:115` |
| `extraction` (past paper) | ❌ | ❌ | **inconsistent with the line above** |
| `syllabus` | ❌ | n/a | |
| `reports` | ✅ | ❌ | facts assembled inline |
| `readiness` | ✅ | ❌ | factor evaluations only |
| `chat` | ⚠️ **not subject-scoped** | ✅ | `api/chat.py:130` omits `subject_id` |
| `class_brief` | ❌ | ❌ | `api/groups.py:238` |

Two surfaces get nothing and one passes the wrong scope. That — not the absence of a vector
store — is the Context Engine gap.

## Where the code is *ahead* of the spec

Not gaps; don't plan to "add" these. Readiness is two explainable layers (append-only
`FactorEvaluation` → AI `ReadinessSnapshot` carrying `evaluation_run_id` back to its exact
inputs; an AI failure preserves the deterministic layer). No model is ever asked for a grade.
Prompt-injection defence is already in the marking prompt (`prompts.py:53-64`). Auto-finalize
is gated on scheme-backed **and** confident. AI metering reports `unpriced_call_count` rather
than a fabricated `$0`.

## Spec items that contradict recorded decisions

`docs/governance/non-goals.md` is Active; each entry has a named revisit trigger. Billing (§37),
microservices/bounded contexts, full resource-based RBAC (§1), submission version history (§12),
and queue-backed notifications (§25) all currently sit on that list. The API is also **pinned to
a single instance** by the uploads disk, the in-process worker, and the in-process rate limiter
at once — notifications, search, and most integrations assume horizontal scale (`RISK-1`).

---

## Decisions taken

- **AI boundary:** the non-goal holds — Avora is not an AI tutor. **Amended:** the Study Coach
  *may* explain content within the student's enrolled subjects. It does not generate new
  assessment and does not produce grades. Needs an ADR recording the amendment, plus a `chat`
  prompt revision and version bump (`AI-7`).
- **Rename:** everything, everywhere — all 90 occurrences including ADRs, governance, and
  `docs/archive/`, plus the `docs/manara-architecture.md` filename.
- **Colours:** build **Light** (logo variant 2) and **Cream** (variant 4) as selectable themes
  alongside the current Midnight default.
- **Roles:** add **Assistant Tutor**. Can invite students and parents; cannot edit grade
  boundaries, readiness weights, the Knowledge Base, or Google Classroom.
- **Branding artwork:** the Figma logo system is MANARA-branded. The wordmark, the hand-drawn
  beacon SVG (`AppShell.tsx:15`, `LandingPage.tsx:4`) and `frontend/public/favicon.svg` need
  Avora replacements — **blocked on the owner**, so text renames ship first with the existing
  mark as a placeholder.
- **Tutor notes stay tutor-only.** `TutorNote` and `ParentCommunication` are never injected
  into student-facing AI context. `build_student_context()` already receives the whole
  `StudentCrm` object, so this needs an explicit guard **and a test**, or a future one-line
  change leaks candid notes to students.
- **Mistakes show the AI explanation and the correct mark scheme answer to the student**
  (owner's decision, taken after the mark-scheme-exposure concern was raised). Consequence to
  accept knowingly: mark scheme content becomes student-visible, which partially reverses
  `PastPaper.mark_scheme_path` being tutor-only. The *file* stays tutor-only; only the
  per-question answer text is surfaced.
- **Readiness gains a paper dimension.** Requires a topic→paper mapping, which does not exist.
- **Subtopic evidence rolls up into its parent topic** — see finding 4.

### Open items — proceeding on these defaults, override any of them

1. **Mistake answer release timing.** Default: **the answer appears once that mark is
   finalized** (auto-finalized marks release immediately). Reason: releasing on marking lets a
   student who submitted early hand mark scheme answers to groupmates who have not submitted
   the same assignment yet.
2. **Topic→paper mapping source.** Default: **AI proposes during syllabus extraction, tutor
   confirms** in the existing syllabus review UI — the same propose-then-confirm shape question
   topics already use, and it keeps `PROD-1` traceability.
3. **Roll-up shape.** Default: **parents aggregate descendants weighted by `Topic.weight`, and
   `syllabus_coverage` counts leaves only** so a finely-split chapter is not over-counted.

---

# Planned work

## A. Colour settings — three themes (do first)

### The brand palette, and where it already exists in code

| Brand name | Hex | Role | Already in `index.css`? |
|---|---|---|---|
| Midnight | `#0C1022` | primary dark ground | ✅ as `--color-canvas` |
| Slate | `#1C2543` | elevated dark surfaces | ✅ as `--color-surface` |
| Beacon | `#C9A55A` | signature amber accent | ✅ as `--color-brand-600` |
| Parchment | `#F1EBE0` | light text on dark | ✅ as `--color-ink-900` |
| Horizon | `#8A9BBE` | secondary text on dark | ✅ as `--color-ink-500` |
| Canvas | `#F7F3EE` | light section background | ❌ **new** |
| Ink | `#131A2A` | body text on light | ❌ **new** |
| Dusk | `#4A5670` | secondary text on light | ❌ **new** |

**Naming collision to fix first:** the brand calls the *light* background "Canvas"
(`#F7F3EE`), but the code uses `--color-canvas` for the *dark* ground (`#0C1022`, brand
"Midnight"). Leaving both is a permanent trap. Rename code tokens to brand names.

### Measured contrast (computed, not assumed)

**Cream theme** (Slate ground) — everything passes: Parchment 12.69:1, Canvas 13.63:1,
Horizon 5.39:1, Beacon 6.46:1.

**Light theme** (Canvas ground) — **two brand colours fail as text**:

| Token on Canvas | Ratio | Verdict |
|---|---|---|
| Ink `#131A2A` | 15.73:1 | ✅ body text |
| Dusk `#4A5670` | 6.66:1 | ✅ muted text |
| Slate `#1C2543` | 13.63:1 | ✅ |
| Horizon `#8A9BBE` | **2.53:1** | ❌ never text on light |
| Beacon `#C9A55A` | **2.11:1** | ❌ never text or links on light |

So the light theme needs two rules the brand sheet does not state:
- **Muted text is Dusk, not Horizon.** Horizon is a dark-mode-only token.
- **Beacon is a fill only, never text.** As a fill it is fine — Ink on Beacon is 7.46:1.
  For links and accent text the light theme needs a darker gold. **Proposed `Beacon Deep`
  `#7D6229` → 5.21:1 on Canvas.** This is a derived token, not from the brand sheet; flag it
  for approval.

### Implementation

- `frontend/src/index.css`: rename tokens to brand names; add Canvas/Ink/Dusk/Beacon-Deep;
  introduce **semantic aliases** (`--color-bg`, `--color-surface`, `--color-text`,
  `--color-text-muted`, `--color-accent`, `--color-accent-text`, `--color-on-accent`,
  `--color-line`, `--color-line-control`) and point every rule in the retarget block at those.
  Three theme blocks then set the aliases: `:root` (Midnight), `:root[data-theme="light"]`,
  `:root[data-theme="cream"]`.
- **`UX-1` is binding: the retarget block stays unlayered.** Attribute selectors on `:root`
  raise specificity without layering, so this works — do not wrap it in `@layer`.
- `color-scheme` becomes per-theme (`dark` for Midnight/Cream, `light` for Light).
- Status colours (`ok`/`warn`/`risk`) are currently tuned for navy and will need light-theme
  values; re-measure rather than reuse.
- **Storage**: `Organization` gains a `theme` column (migration; `batch_alter_table` +
  `NAMING` per `DB-17`, working `downgrade()` per `DB-16`). Tutor-only `PATCH`; students and
  parents inherit their org's theme. Default `midnight` so nothing changes for existing orgs.
- **Contrast validator** shipped as a test, not a runtime check: a unit test asserting every
  (text token, surface token) pair in every theme clears 4.5:1, and control borders 3:1.
  This is what stops a future palette edit from silently breaking AA — `index.css` already
  records that `--color-ink-400` was *deleted* rather than retuned for exactly this reason.

## B. Wire the Mistake Engine (the bug fix)

- `services/prompts.py` — extend `MARKING` to return `mistake_category` + `severity` for any
  question not awarded full marks. Bump `marking` to **v4**. **Keep the injection-defence
  paragraph verbatim** (`SEC-20`, `SEC-21`).
- `services/marking.py` — write `Mistake` rows in `_run_marking`/`_settle_submission`.
  **Idempotent by `question_mark_id`** (`BE-6`; `mark_submission` is re-runnable), and never
  create a mistake for a mark a tutor corrected upward.
- `Mistake` gains `explanation` (AI reasoning about this student's error) and
  `correct_answer` (mark scheme answer), plus `released_at` — null until the mark is finalized,
  so the student endpoint can withhold both fields until then (open item 1).
- Migration: the two text columns, `released_at`, and a unique constraint on
  `mistakes.question_mark_id`. `batch_alter_table` + `NAMING` (`DB-17`), working `downgrade()`
  (`DB-16`).
- Test: one wrong answer yields exactly one `Mistake` across two runs of the same job — drive
  with `process_one_job()`, never `worker_loop()` (`QA-6`). Plus a negative test that a student
  cannot read `correct_answer` before release (`QA-12`).

## C. Rename MANARA → Avora (everything, everywhere)

19 `MANARA` + 4 `OASIS` in code; 71 + 2 in `docs/`.

- User-visible: `frontend/index.html:8`, `AppShell.tsx:37,40`, `LoginPage.tsx:35,37`,
  `LandingPage.tsx:51,54,80,129`. Update `test/App.test.tsx:17` in the same change or the
  suite goes red.
- Identifiers: `ui.tsx:155,159` use `manara-modal-title` as `aria-labelledby` — rename together
  or the accessible name breaks.
- Comments/docstrings in `google_classroom.py`, `models/lessons.py`, `models/classroom.py`,
  `api/auth.py`, `api/readiness_v2.py`, `index.css` — edits, not deletions (`CODE-12`).
- `docs/manara-architecture.md` → `docs/avora-architecture.md`, updating references in
  `CLAUDE.md`, `api/auth.py:72`, `api/readiness_v2.py:8`.
- Add a line to `docs/governance/glossary.md` recording MANARA by OASIS AI as the former name,
  since ADRs and `docs/archive/` are being rewritten.
- No backend runtime string, no migration.

## D. Context engine per AI surface

New `backend/app/services/context/` — one builder per surface, composed from shared primitives,
replacing ad hoc assembly at seven call sites.

```
services/context/
  blocks.py        # shared: readiness, mistakes, recent lessons, observations,
                   # outstanding homework, KB entries
  marking.py       # tutor KB (subject-scoped) + prior mistakes on these topics
  extraction.py    # tutor KB — used by BOTH call sites, fixing today's inconsistency
  reports.py       # KB + readiness + trend
  readiness.py     # KB + factor evaluations
  chat.py          # KB (subject-scoped) + readiness + homework + mistakes + lessons
                   # + enrolled-subject list, so "explain content" stays inside the
                   #   student's own subjects per the amended AI boundary
  brief.py         # previous lesson + homework + mistakes + weak topics
```

- `PROD-2`: a block with no evidence is **omitted**, never emitted as `0` or "none".
- `BE-13`: every builder async, bounded queries — `blocks.py` batches, or this N+1s and adds
  latency to every AI call.
- Each builder takes a token budget; truncation by recency + severity, never arbitrary.
- `build_tutor_context` (`knowledge.py:22`) moves in unchanged; `student_context.py` folds into
  `context/chat.py`.
- Fixes in passing: past-paper extraction gains KB; `api/chat.py:130` gains `subject_id`.
- **Tutor-note guard.** `context/chat.py` must never read `crm.notes` or
  `crm.communications`. Enforce it structurally — have the student builder take only the fields
  it needs rather than the whole `StudentCrm` — and add a test asserting a note's body never
  appears in the student context block.

## F. Subtopic roll-up (finding 4)

- `readiness_v2.py:317` currently selects all topics flat. Change to build the parent/child
  tree from `Topic.parent_id`, compute leaf mastery from directly-tagged questions, then
  aggregate into parents weighted by `Topic.weight`.
- `syllabus_coverage` counts **leaves only**, so a finely-split chapter stops outweighing a
  coarse one.
- Keep `topic_mastery()` itself pure (`BE-4`) — the tree walk belongs in `readiness_v2.py`,
  not in the factor function.
- `FactorEvaluation` is append-only, so old rows keep the old meaning. New runs will legitimately
  differ from historical ones; that is a behaviour change worth noting in the readiness UI
  rather than hiding.
- Test: a subject with one parent and three evidenced subtopics scores the parent, and the
  parent no longer reports `no_data`.

## G. Paper-level readiness

- `Subject` gains a paper list (or a `SubjectPaper` table: subject_id, paper_number, label).
- Topic→paper mapping table, populated by the AI proposal in `extract_syllabus` and confirmed
  by the tutor (open item 2). Unconfirmed mappings do not feed scores — `PROD-1`.
- `FactorEvaluation` and `ReadinessSnapshot` gain a nullable `paper_id`. Null = subject-level,
  preserving every existing row's meaning; both tables stay append-only.
- `/readiness/*` returns paper-level entries only where a confirmed mapping exists. A paper
  with no mapping is **omitted**, never shown as 0% (`PROD-2`).
- This is the largest item here and depends on F — paper scores aggregate topic scores, so the
  roll-up must be right first.

## E. Assistant Tutor role

- `UserRole` gains `assistant_tutor` — no migration (`Enum(..., native_enum=False)`,
  `ADR-0007`). But per `DB-6` nothing forces an audit of `if`/`match` chains over `UserRole`;
  find every existing branch by hand.
- `api/deps.py` gains `AssistantTutorUser` (assistant *or* tutor) alongside `TutorUser`. Gate
  stays in the signature, never the handler body (`BE-17`, `SEC-11`).
- **Stated by the owner.** Assistant tutors **cannot** edit grade boundaries, readiness
  weights, the Knowledge Base, or Google Classroom. They **can** invite students and parents.
- **Inferred to fill the rest of the 38 routes** — correct any of these:
  - *Assistant may:* review and finalize marks, create and publish homework, create lessons,
    add observations and tutor notes, read student CRM and readiness.
  - *Tutor only:* student password reset, org theme (both follow the same line as the stated
    four — they change who can get in, or how the platform judges students).
- `tests/test_authorization.py` already fails if a route loses its gate; per `QA-12` each
  reclassified route ships with a negative-case test asserting an assistant is refused.

---

## Order

**A → B → F → C → D → E → G**, then attendance.

A (colours) is what was asked for and is self-contained. B (mistakes) and F (roll-up) are both
live bugs, both small, and both in the readiness path — do them back to back while that code is
loaded. C (rename) is mechanical and touches nothing the others do. D (context engines) wants
mistakes to exist first or its mistake blocks are dead code, and carries the tutor-note guard.
E (assistant tutor) is a pass over 38 route signatures and merges badly with anything else in
flight. G (paper readiness) is last of the seven: it is the largest, and it depends on F.

Attendance follows — small, and unblocks four domains. It must **not** feed readiness until
it is decided whether attendance is academic evidence; `EvidenceSource` and `SOURCE_WEIGHTS`
change together (`PROD-10`).

Deferred with reasons: notifications and search (single-instance constraint), billing and admin
panel (recorded non-goals), Drive/Zoom/Teams/Calendar (credentials projects; Zoom and Teams
also need Lesson depth first), study planner (wants mistakes + attendance as inputs).

## Verification

```bash
cd backend && .venv/bin/python -m pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
cd ../frontend && npm test && npm run build     # build is the only type check
```

- **A**: contrast test must pass for all three themes; switch themes in the running app and
  check the tutor dashboard, a form, and a status badge in each.
- **B**: seed (`python -m seed.demo`), submit a partially-wrong homework, drive with
  `process_one_job()`, assert `Mistake` rows exist, re-run the same job, assert count
  unchanged, confirm `mistake_analysis` returns a sub-100 score with non-zero `evidence_count`.
- **C**: `App.test.tsx` covers it; grep for stragglers before pushing.
- **D**: per-builder tests with `fake_ai`, patching the **calling** module's
  `structured_complete` (`QA-7`). Assert absent data is omitted, not zeroed.
- **E**: negative-case test per reclassified route.
- **F**: seed a nested syllabus, evidence only subtopics, confirm the parent topic scores
  instead of reporting `no_data`, and that coverage counts leaves only.
- **G**: a subject with a confirmed topic→paper map returns paper-level readiness; a subject
  without one omits papers entirely rather than showing 0%.
- Migrations verified up → down → up (`DB-16`); CI runs this on Postgres 16, which the local
  SQLite suite does not (`RISK-3`).

Every change goes through a PR into the default branch on `claude/avora-core-architecture-v5pfk6`
— only documentation-only edits may go direct (`CODE-16`, `CODE-17`).
