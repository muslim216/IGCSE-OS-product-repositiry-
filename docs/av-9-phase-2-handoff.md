# Phase 2 (Subjects, chapters, syllabus) — agent handoff

**Audience: agents, not humans.** Dense and declarative on purpose. Every assertion is either
(a) verified in-session against the merged code and marked `VERIFIED`, (b) sourced to a file path,
commit, PR or rule ID, or (c) marked `UNVERIFIED`. **Do not upgrade an `UNVERIFIED` claim without
testing it.**

This is the **phase-local** record: what Phase 2 delivered, the invariants it established, and what
it deliberately left for later phases to pick up. For where the whole programme stands, read
[`docs/avora-plan-handoff.md`](avora-plan-handoff.md). For Phase 1's invariants and concurrency
test constraints — all still binding — read
[`docs/av-82-phase-1-handoff.md`](av-82-phase-1-handoff.md); this document does not repeat them.

| Field | Value |
|---|---|
| Phase | 2 — Subjects, chapters, syllabus |
| Decisions implemented | `AV-6`, `AV-7`, `AV-8`, `AV-9`, `AV-10`, `AV-11`, `AV-75`, `AV-87`, `AV-111`, `AV-124` (partial), `E1`, `E14`, `E25`, `E26` |
| Status | ✅ **DONE** — 6 of 6 tasks merged |
| Landed | 4–8 Sep 2026, PRs #57–#62 |
| Head after the phase | `56840c0` on the default branch |
| Migration head | `0033_subject_marking_rules` |
| Suite at hand-off | backend **588 passed / 15 skipped**, frontend **188 passed** — `VERIFIED` |
| Unblocks | **Phase 3** (marking and evidence, `AV-81`) and **Phase 6** (teaching plan) |

---

## 1. Task status

| ID | Task | PR | Squashed as | Migration |
|---|---|---|---|---|
| 2.1 | `Chapter` model, migration, topic reparenting | #57 | `7bc2c0c` | `0029_chapters` |
| 2.2 | Tutor-owned subjects, `level`, delete the built-in syllabuses | #58 | `66c0380` | `0030_tutor_owned_subjects` |
| 2.3 | Syllabus extraction produces chapters | #59 | `110d7fd` | — (none needed) |
| 2.4 | Grade boundaries: one tutor-entered source | #60 | `ca4d7f3` | `0031_grade_boundaries_one_source` |
| 2.5 | Teaching guidance upload | #61 | `e27c70d` | `0032_teaching_guidance` |
| 2.6 | Per-subject marking rules | #62 | `56840c0` | `0033_subject_marking_rules` |

Every task was one short-lived branch and one PR, merged by squash with the branch deleted
(`CODE-16`, `CODE-17`). Nothing went to the default branch directly except documentation, which
under the owner's standing instruction is not committed at all (§9).

---

## 2. The single most important distinction

**Three things Phase 2 stores are read by nothing yet.** They are not gaps, and a later agent must
not "fix" them by wiring them up outside the task that owns that decision:

| Stored by | Column(s) | Consumed by | Guard that fails if it is wired early |
|---|---|---|---|
| 2.6 | `subjects.marking_rules` | **Phase 3's context assembler** (`E16`), under `AV-76` precedence | `tests/test_marking_rules.py::test_nothing_marks_with_them_yet` — asserts the marking prompt does not mention them **and** that its version is still `v3` |
| 2.5 | `subjects.guidance_path/_name/_mime/_uploaded_at` | **Phase 6**, to weight the plan by chapter difficulty (`AV-14`) | none — the document is served, never parsed; nothing to detect |
| 2.1 | `chapters` rows, `topics.chapter_id` | Phase 6 schedules chapters; Phase 3 scopes classifieds to them (`AV-20`) | the composite foreign key (§3.3) |

Both user-facing surfaces say so in their own copy, and that is deliberate: `PROD-1` forbids
implying an effect the product does not have. The marking-rules page states that marking does not
read the rules yet; the teaching-guidance page states the document is kept for a plan that does not
exist yet. **If you make either claim true, change the copy in the same PR.** CodeRabbit caught
exactly this wording on #61 before it merged.

---

## 3. Invariants established this phase — do not regress

### 3.1 A subject belongs to exactly one organization

`subjects.organization_id` is `NOT NULL` and identity is `UniqueConstraint(organization_id,
exam_board, code)` (`app/models/syllabus.py`) — `VERIFIED`. Before 2.2 subjects were global rows
shared by every tenant, which is why `SEC-8` exists. Two helpers, and only these two, resolve a
caller-supplied `subject_id`:

- **`api/deps.py::owned_subject`** — tutor-facing. Same organization or **404** (`API-7`, `SEC-9`).
- **`services/subjects.py::visible_subject_ids`** — for routes a student or parent reaches, scoped
  by *enrolment*, because a student may legitimately be taught a subject outside their own
  organization.

Do not hand-write either condition at a call site. `SEC-8` still stands and is now belt-and-braces
rather than the only guard: scope student-visible material by *(organization, subject)*, never
subject alone.

### 3.2 Nothing ships a subject

`seed/syllabus/*.json` and `seed/load_syllabus.py` are **deleted** (`AV-8`, task 2.2). A subject
exists only where a tutor created one. `seed/demo.py::build_subject` builds the demo tutor's own
Chemistry tree and is **shared with `tests/test_chapters.py`** rather than duplicated, so the tree
the tests assert on is the tree the demo actually builds (`E26`).

### 3.3 A topic's chapter must belong to the topic's own subject

`topics` carries a **composite** foreign key `(subject_id, chapter_id) → chapters(subject_id, id)`,
not a single-column FK on `chapter_id` (`app/models/syllabus.py`, migration `0029`). A single-column
FK would validate only that the chapter exists, so nothing would stop a topic being filed under
another subject's chapter and a chapter rollup silently summing across subjects. `ADR-0010` is the
full argument. `chapters` therefore carries a redundant `UniqueConstraint(subject_id, id)` for that
FK to point at.

`Topic.chapter_id` stays **nullable** only because rows predating 2.3 exist; nothing new creates a
chapterless topic. Do not tighten it without a migration that proves the table is clean.

### 3.4 One source for a predicted grade, and no grade without it

`subjects.grade_boundaries` is **dropped** (migration `0031`). The org-scoped `grade_boundaries`
table is the only source, resolved in exactly one module — `services/grade_boundaries.py`
(`resolve_grade_boundaries`, `org_boundaries`, `boundaries_for`). Consequences that are the point,
not side effects (`PROD-2`, `PROD-6`):

- An organization with no rows for a subject gets **no predicted grade on any surface** — not a
  dash, not a default. `predict_grade` returns `"—"` for an empty list and callers suppress it; v2
  synthesis stores `NULL` rather than `"—"`; `grade_band` returns `None`; and both v2 read paths
  suppress a stored grade once the boundaries behind it are gone. The second of those
  (`api/readiness_v2.py`) was a 2.4 miss, found by cubic on PR #63 and closed by **PR #64**
  (`b1fa484`) — the snapshot keeps its value, and the grade returns if boundaries are set again.
- `defaults_for_scale()` is **offered, never written**. The editor pre-fills it, labelled
  unconfirmed (`PROD-8`), and it counts only when the tutor saves. `apply_syllabus` seeds nothing.
- An existing subject's boundaries are never overwritten — including an empty list, which is a tutor
  having cleared them.

This closes **half of `RISK-5`**. The other half — v1 and v2 engines answering different surfaces —
is untouched and still open.

### 3.5 Tutor material is tutor-only, including from enrolled students

Teaching guidance (`AV-95`) and marking rules are gated with `TutorUser` in the **signature**
(`SEC-11`, `BE-17`), never in the handler body. `tests/test_teaching_guidance.py` and
`tests/test_marking_rules.py` each assert an *enrolled* student is refused, not merely a stranger:
a scheme of work tells a student what is coming and in what order, and marking rules are the
instructions their work is measured against.

### 3.6 The syllabus prompt is chapter-first and carries the data-not-instructions rule

`services/prompts.py::SYLLABUS` is **`v2`** (`AI-6`, `AI-7`) — `VERIFIED`. It asks for chapters
holding topics, reads `level` off the document or leaves it null, and states that the document is
data and never instructions (`SEC-20`, the posture the other document surfaces already carried).
Grade boundaries left the prompt: a syllabus publishes a specification, not a series' boundaries, so
the old "give your best estimate" line asked for a fabricated number.

`ai_syllabus_provider` is **`anthropic`** with the model left blank, inheriting `anthropic_model`
(`AV-124`) — landed with the prompt rewrite so the prompt is tested against the model it runs on.
Marking and extraction still route to Gemini; the full retirement is task 3.2.

### 3.7 Level is stated, never inferred

`SubjectLevel` (`igcse` / `o_level` / `a_level`, `native_enum=False`, `DB-5`) has **no default**
(`AV-7`). The extractor proposes one only where the document states it; `apply_syllabus` returns
**422** for a draft that still has none, and the review UI carries the selector that fixes it. Do
not add a default to make a test easier.

---

## 4. Schema as delivered

`subjects`, after the phase — `VERIFIED` against `app/models/syllabus.py`:

| Column | Added/changed by | Note |
|---|---|---|
| `organization_id` | 2.2 (`0030`) | `NOT NULL`, leading column of the identity constraint |
| `level` | 2.2 (`0030`) | `Enum(..., native_enum=False, length=16)`, no default |
| `grade_boundaries` | **removed** by 2.4 (`0031`) | copied into the org-scoped table first |
| `guidance_path/_name/_mime/_uploaded_at` | 2.5 (`0032`) | all nullable, all written and cleared together |
| `marking_rules` | 2.6 (`0033`) | `Text`, nullable — skippable by design (`AV-87`) |

`chapters` (2.1): `id`, `subject_id`, `code`, `title`, `position`, `weight`, with
`UniqueConstraint(subject_id, code)`, `UniqueConstraint(subject_id, id)` and
`Index(subject_id, position)` declared in the **model as well as** the migration (`DB-12`).

**Migration `0031` is the only one carrying data.** It copies each subject's boundary column into
the table for that subject's *own* organization — exact, because 2.2 had already made subjects
tenant-owned — and skips any (organization, subject) pair that already has rows, since those are the
tutor's and the column's are whatever the extractor seeded. Its `_bands()` helper tolerates a
scalar, `null`, malformed JSON and a non-numeric cut-off rather than aborting mid-migration; that
hardening came from review and is covered by a hostile-data rehearsal (§8).

---

## 5. Endpoints as delivered

`VERIFIED` from the running app's OpenAPI:

```
GET,PUT     /api/v1/subjects/{id}/grade-boundaries      # pre-existing; `source` is now 2-valued
GET,PUT     /api/v1/subjects/{id}/marking-rules         # 2.6
GET,PUT,DEL /api/v1/subjects/{id}/teaching-guidance     # 2.5
GET         /api/v1/subjects/{id}/teaching-guidance/file
```

Two routers are new — `api/teaching_guidance.py` and `api/marking_rules.py`, both mounted under the
`/subjects` prefix like `api/grade_boundaries.py`. The repo is now **27 routers, 25 mounted**.

Contract notes a caller must know:

- `GradeBoundariesOut.source` is `Literal["organization", "none"]`. The third value, `"subject"`,
  went with the dropped column.
- `GET .../teaching-guidance` **never 404s for "nothing uploaded"** — the subject exists either way
  and the screen has to say which. `uploaded: bool` is explicit rather than inferred from a null
  filename.
- `PUT .../teaching-guidance` replaces, and deletes the old object **after** the row commits. A
  failed commit rolls back and discards the *new* object; neither cleanup delete can turn the
  outcome into a 500 the client would retry against a write that already happened.
- `GET .../teaching-guidance/file` declares binary media types with `response_class=Response`.
  **The four older file routes in `past_papers.py` and `classifieds.py` still declare
  `application/json` for binary bodies** — a real gap, left alone rather than widening #61.
- `MarkingRulesIn.rules` is trimmed **before** the 8000-character cap is measured, so trailing
  whitespace cannot turn a storable body into a 422. Whitespace-only stores `NULL`.

---

## 6. What each later phase must pick up

**Phase 3 (marking and evidence, `AV-81`) — the next serial link:**

- `subjects.marking_rules` is yours. `E16`: marking context is assembled in **exactly one
  function**, applying `AV-76`'s precedence — mark scheme → chapter notes → subject rules → exam
  board and level. One test per conflict pair.
- `AV-111` bounds what those rules may do: they describe **how** the AI marks, never **when a mark
  counts**. `AV-25`'s auto-finalize rule (scheme-backed *and* confident) is not reachable from them.
- Bump the `marking` prompt version when the rules enter it (`AI-7`) — which is also what turns
  `test_nothing_marks_with_them_yet` from a guard into a failure you must update deliberately.
- Classifieds become chapter-scoped (`AV-20`); the `chapters` table and its composite FK are there.

**Phase 6 (teaching plan):** `subjects.guidance_*` holds the document; read it through
`services/storage.py`, never the filesystem. `Chapter.position` is teaching order,
tutor-controlled, **not** derived from `code` — a tutor may teach chapter 4 before chapter 3.
`apply_syllabus` assigns positions `1..N` from the draft's order and pushes chapters an updated
draft omits to the end, rather than leaving them colliding with a reassigned position.

**Phase 9 (onboarding, `9.1`):** steps 2–6 of the eleven-step flow are now all backed by real
endpoints — subject, syllabus upload and review, teaching guidance, grade boundaries, marking
rules. **Step 6 is the one named skippable step** (`AV-87`); every other step is enforced by what
the backend allows next, never by the screen alone (`SEC-10`).

---

## 7. Test-infrastructure notes — read before writing a Phase 2-adjacent test

- **`tests/factories.py::make_subject` writes the organization's grade boundaries** as well as the
  subject. Without them a subject has no predicted grade anywhere, which is correct behaviour and
  not what most tests are about. Ask for the absence explicitly with `grade_boundaries=[]`.
- **`subject_defaults(session)`** returns the two columns 2.2 made mandatory, for the ~30 fixtures
  that build a `Subject(...)` directly. A fixture that builds one *before* the `tutor` fixture has
  registered an account gets a second organization the tutor is not in, and every `owned_subject`
  lookup then 404s — depend on `tutor` first.
- **The suite still never runs a migration** (`conftest.py` builds from `Base.metadata`). CI's
  Postgres job is the only check of the chain, which is what keeps `RISK-3` live. Verify
  up → down → up on SQLite locally as a partial check; Docker is not available on this machine.
- Frontend stubs must **hold state**, not answer per verb. A stub whose `DELETE` returns "absent"
  while its `GET` still returns "present" cannot express any flow where a mutation invalidates and
  the component re-reads — which is all of them.

---

## 8. What review caught, and what it cost

Roughly **40 findings** across the six PRs, from `cubic-dev-ai[bot]` (the productive one, two waves
per push) and `coderabbitai[bot]` (skips this repo automatically; trigger with
`@coderabbitai review`). `kody-ai[bot]` reviews nothing — its trial is exhausted and it reports
`skipping`. Four were defects a user would have hit:

1. **A file picked for one subject could be uploaded to another** (#61) — the form posted the
   currently selected subject, and neither React state nor the browser's filename was cleared.
2. **Cached data outlived the session** (#62) — no query key carries an identity and the
   `QueryClient` is created once, so a second sign-in on the same device rendered the previous
   user's data until each query refetched (CWE-524). Fixed in `AuthProvider` for the whole app, not
   on the page that happened to expose it.
3. **`anthropic>=0.40` predates `client.messages.parse`** (#59) — a fresh resolve would have broken
   *every* Anthropic structured surface, not only the syllabus one 2.3 moved there. Floor raised to
   `>=0.125`.
4. **Stale chapter positions collided on re-apply** (#59), making `order_by(position)` arbitrary.

Two process lessons worth keeping:

- **Break the fix and watch the test fail before claiming it covers anything.** Three Phase 2 tests
  passed against both old and new code — React Query's structural sharing, a per-verb stub, and a
  guard the query key already made unreachable.
- **A scripted multi-test edit can delete a neighbour.** #60's cleanup removed
  `test_apply_upserts_existing_subject_by_exam_board_and_code` along with the three obsolete tests
  it targeted; cubic caught it. Diff the `^async def test_` list before and after.

Migration `0031` was additionally rehearsed against deliberately malformed legacy data — a scalar
`42`, `true`, `null`, malformed JSON and a `"90%"` cut-off — and completes, copying only the valid
band. `VERIFIED`.

---

## 9. Process constraints that applied, and one recorded deviation

- **Documentation stays in the working tree.** `docs/**` and `CLAUDE.md` are never staged,
  committed or pushed (owner, 2026-09-04). Stage by path; never `git add -A`. Expect a permanently
  dirty tree and do not tidy it.
- This collides with `GOV-1`/`CODE-21`, which require a PR to update the constitution document it
  changes. **Resolution used throughout Phase 2:** write the doc updates anyway, leave them
  uncommitted, and say so explicitly in the PR body so the deviation is recorded rather than
  silent. Every PR from #59 on carries that paragraph.
- Documents updated locally this phase: this file, `avora-plan-handoff.md`, `README.md`,
  `06-database-design.md`, `07-security-architecture.md`, `09-ai-platform.md`,
  `08-infrastructure-and-deployment.md`, `CLAUDE.md`, and `adr/0010-chapter-is-a-table.md` (new).
- `README.md` was also corrected for content 2.2 had already invalidated — it still advertised
  `seed.load_syllabus` and five built-in syllabuses. **It remains uncommitted, so the public README
  on GitHub is still wrong on those points.** That is a live decision for the owner, not an
  oversight.

---

## 10. Open items this phase did not own

| Item | State |
|---|---|
| `RISK-5`, second half — v1 and v2 engines answer different surfaces | Open. 2.4 closed only the two-boundary-sources half |
| ~~`GET /api/v1/readiness/v2/students/{id}` returned a stale predicted grade~~ | **Closed** — PR #64 (`b1fa484`), after the owner approved it. A task 2.4 miss found by cubic on #63: that endpoint returned `snapshot.predicted_grade` with no re-check. The snapshot is untouched and the grade returns if boundaries are set again |
| **Whose grade boundaries apply to a student taught by two organizations** | **Open, and a product question.** `visible_subject_ids` scopes by enrolment, so a student can be taught a subject owned by a second tenant — but a grade is synthesised under `student.organization_id` (`readiness_v2_ai.py:356`) and read back the same way. cubic proposed keying reads on the subject's owner; declined, because it would validate a grade against a list it was never mapped through. Answering it properly starts at synthesis, not at a read (comment in `api/readiness_v2.py`) |
| Binary media types on the four older file routes (`past_papers`, `classifieds`) | Open, one small PR |
| Public `README.md` stale about seeds and syllabuses | Open — blocked on the docs-stay-local rule, needs an owner decision |
| No AI evaluation harness | Open and growing. Phase 2 bumped `SYLLABUS` to `v2` with nothing measuring whether the output improved |
| `Topic.chapter_id` nullable | Deliberate; only pre-2.3 rows need it |
| Deployment still one instance | Deliberate (`AV-85`) until the Phase 11 concurrency audit. **Nothing in Phase 2 changed this** |

---

## 11. Verification state

Run from the merge commit `56840c0`, all `VERIFIED` this session:

```bash
# backend/
.venv/bin/python -m pytest -q                        # 588 passed, 15 skipped
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/python -m mypy app/services app/schemas    # 53 source files, clean

# frontend/
npm test        # 188 passed
npm run lint && npx prettier --check src/ && npm run build

# migration chain, partial check (SQLite; CI runs Postgres 16)
DATABASE_URL="sqlite+aiosqlite:////tmp/chain.db" .venv/bin/alembic upgrade head
DATABASE_URL="sqlite+aiosqlite:////tmp/chain.db" .venv/bin/alembic downgrade base
DATABASE_URL="sqlite+aiosqlite:////tmp/chain.db" .venv/bin/alembic upgrade head
```

After `python -m seed.demo`, the demo tutor owns one Chemistry subject with three chapters, nine
topics and its organization's grade boundaries, and **no** teaching guidance or marking rules — the
last two being states the surfaces must render as absent rather than as broken.
