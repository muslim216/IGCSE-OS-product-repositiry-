# Phase 3 (Marking and evidence) — agent handoff

**Status: 3 of 6 tasks delivered. 3.4, 3.5 and 3.6 are not started.**

Written for the agent who picks this up, not for a human reader. It says what is
built, what changed underneath the plan while it was built, and what the three
remaining tasks will collide with if nobody reads this first.

Phase 3 is `AV-81`'s "settles before mistakes and readiness", so Phase 4
(mistakes) and Phase 5 (readiness) both build on what is recorded here.

> **Read `docs/av-9-phase-2-handoff.md` first if you have not.** Phase 3 consumes
> what Phase 2 stored: `Chapter`, `Subject.marking_rules`, `Subject.guidance_*`.
> Phase 2 called those "three things stored that nothing reads yet" — two of the
> three now have readers, and this document is where that is recorded.

---

## 0. The one thing that changed under the plan

**`AV-76` and `AV-94` were reversed by the owner on 9 Sep 2026.** They said the
official mark scheme was **absolute and never overridden**. They now say the
opposite:

> tutor wins marks are given but the fact that mark scheme contradicts is
> recorded, use this as a rule for all contradictory points between a tutor rule
> and a mark scheme

Plus, answering the question that left open: **a mark that overrode the scheme
still auto-finalizes.** The tutor's rule is the authority, so nothing waits for a
human.

Both entries are struck through and marked `SUPERSEDED` in
`docs/avora-new-state-august-16.md`. **The plan text elsewhere still reads as
though the scheme is absolute** — §3's summary tables, the 3.2 task body's
precedence diagram, and `AV-25`'s neighbours. Treat `AV-76`/`AV-94`'s own rows as
the current statement and the rest as stale prose.

`AV-25` is untouched and must stay untouched: auto-finalization still requires an
official scheme **actually attached** and confident output. A tutor rule can
change what a mark *is*; it cannot make an unschemed or low-confidence question
eligible to count without them.

---

## 1. Task status

| ID | Task | State | PR |
|---|---|---|---|
| **3.1** | Chapter-scope classifieds, add notes | ✅ delivered | #65 → `773fce0` |
| **3.2a** | Retire Gemini, move every surface to Claude 5 (`AV-124`) | ✅ delivered | #66 → `9f1f420` |
| **3.2b** | Marking-context assembler and precedence (`E16`) | ✅ delivered | #67 → `c9d7a94` |
| **3.2c** | Subject rules summarised, marking reads the summary | ✅ delivered | #68 → `c79dbd0` |
| **3.3** | Typed answers as a submission type | ✅ delivered | #69 → `892d3d8` |
| **3.4** | AI-marked mocks | ❌ not started | — |
| **3.5** | Past-paper booklets + AI extraction of the paper list | ❌ not started | — |
| **3.6** | Timed mocks, server-side clock | ❌ not started (after 3.4) | — |

**3.2 was split into three PRs.** As written it bundled the provider cutover with
the context assembler; the owner's ruling added contradiction-recording and rules
summarisation. One PR would have been ~2,000 lines, which is the size at which
the review bots stop finding real defects. `AV-124`'s "one PR" constraint is
about the *Gemini retirement*, and 3.2a is that PR.

Migration head: **`0038`**. Prompt versions: marking **v5**, marking_rules **v1**.

---

## 2. Invariants established this phase — do not regress

### I1. One function assembles the marking context

`services/marking_context.py::build_marking_context` (`E16`). Precedence spread
across call sites is precedence that drifts. `tests/test_classified_chapters.py`
carries an AST guard that fails if **any** `.notes` read appears under
`services/` or `workers/` outside that one function's line range. It is scoped to
the *function*, not the file — a second reader in the same module fails it.

### I2. The layer order, as the owner revised it

```
[1] chapter notes        Classified.notes          most specific tutor input
[2] subject rules        Subject.marking_rules     the tutor's standing policy
[3] official mark scheme attached document         reference, not final authority
[4] exam board and level Subject.*                 general convention
```

`[3]` is deliberately a gap in the assembler's numbering — the mark scheme is a
file attached to the request, not text the assembler builds. Closing the gap
would make every `[3]` in the prompt point at the exam context instead.

**The numbering is not the ranking, and the prompt says so.** An earlier draft
presented the section numbers as an order of authority and then ranked the scheme
above exam-board convention, giving that pair two answers.

### I3. What a test can prove about precedence, and what it cannot

No test in this repository can prove a model *obeys* the order. Proving it would
mean calling a real provider (`QA-8` forbids it) and would still sample one
answer. The tests assert what is determinable: the assembler emits the layers in
the right order, with the labels that identify them, present exactly when their
source has content — plus the prompt clauses themselves. **Do not write a test
that claims more than that.**

### I4. The trust boundary in the marking prompt

Three sets, and two of the three boundaries were got wrong once each:

- **The student's** — photographed pages *and* any typed answer. Data, never
  instructions.
- **This system's** — the booklet, the mark scheme, the MARKING CONTEXT block,
  the question list, these instructions. To be followed.
- **The markers** — `BEGIN/END STUDENT TYPED ANSWER` are labels this system
  applies, not a boundary the student can move or close.

Both directions are pinned by `tests/test_marking_context.py`. The failures they
prevent: telling the model its own question list is student text to ignore, and
telling it a photographed page is system-authored.

### I5. `scheme_conflict` is tutor-only

`QuestionMark.scheme_conflict` reaches `MarkRow` (tutor-gated through
`_tutor_submission`) and deliberately **not** `StudentMarkRow`. The prompt also
forbids putting the conflict in `feedback`, which does reach the student —
without that, the model could copy it across and defeat the whole separation.

It is **not** recorded where no scheme was attached: with nothing to contradict,
such a report is the model asserting a fact about a document it never saw.

### I6. The summary is absent or current, never stale

`Subject.marking_rules_summary` + `marking_rules_summary_of` (a SHA-256 of the
rules it was built from). Writing `marking_rules` clears both and enqueues the
job. The job **skips only when the hash matches** and **re-reads after the model
call**, discarding a result whose rules have since changed.

> 3.2c originally shipped claiming "clear on write" made staleness impossible. It
> did not: the job reads, awaits, then writes, so a save inside that gap left the
> older summary committed after it, and the newer job saw a non-null summary and
> returned early — stale forever. The fingerprint is the compare-and-swap that
> closes it. **Do not remove it on the reasoning that clearing is enough.**

`build_marking_context` falls back to the full text when the summary is absent,
so the gap between a save and the job marks correctly at full cost, and a
permanently failing summarisation degrades to that rather than dropping the
tutor's rules.

### I7. The deterministic scan is not a model call

`services/injection_scan.py` (`AV-93`, `E20`) is a pure function: no session, no
I/O, no settings. A hit sets `needs_review` on every mark in the submission **and
the AI's confidence is not consulted**. That is the design, not an oversight — it
is the only control in this path that does not depend on the model's judgement
about the attacker's text.

**"Set confidence to low" is the obvious refactor and it silently removes the
property.** There is a test whose only job is to fail if someone does that.

### I8. Typed answers auto-finalize like photographs

`AV-91`. The trust rule does not change by channel. A version that quietly queued
every typed submission would look like it worked and would move the whole feature
into the tutor's queue.

### I9. Declined controls stay declined

A second AI call to detect injection, a mark-value cap on auto-finalize, and
calibration metrics were all offered and **declined** by the plan. **Declining
calibration means there is no way to detect this being exploited.** Deliberate,
not an oversight. A test asserts no injection-detection surface exists; the other
two are absences recorded in prose, because a grep for the words trips on the
comments explaining the decline.

**Ask the owner before adding any of them back.**

---

## 3. Schema as delivered

| Migration | Table | Columns |
|---|---|---|
| `0034` | `classifieds` | `chapter_id` (composite FK on `(subject_id, chapter_id)` → `chapters(subject_id, id)`), `notes` |
| `0035` | `question_marks` | `scheme_conflict` |
| `0036` | `subjects` | `marking_rules_summary` |
| `0037` | `subjects` | `marking_rules_summary_of` (SHA-256, 64 chars) |
| `0038` | `submissions` | `typed_answer`, `typed_flag_reason` |

**The composite key on `classifieds` matters.** A single-column FK proves only
that the chapter exists, so nothing would stop a booklet being filed under
another subject's chapter and its notes then steering a mark for a different
syllabus. `topics` carries the identical key for the identical reason;
`resolve_chapter` in `api/deps.py` refuses the mismatch *before* the upload is
written, so it is a 404 rather than a constraint violation with a file already on
disk.

Caps: chapter notes **4,000**, subject rules **8,000** (Phase 2), typed answer
**20,000**. All trimmed *before* the cap is measured, through
`api/deps.py::_bounded_form_text` — `Form(max_length=...)` measures the raw value
and rejects a full-length body with a trailing newline. **That bug was written
twice in this phase.** Any new multipart free-text field goes through that helper.

---

## 4. Endpoints and surfaces as delivered

| Route | Who | Notes |
|---|---|---|
| `GET /subjects/{id}/chapters` | any role, enrolment-scoped | Ordered by `position` (teaching order), **not** `code` |
| `PATCH /classifieds/{id}` | tutor | Full replacement of `(chapter_id, notes)` — **both fields required**, no partial patch |
| `POST /classifieds`, `POST /assignments/upload` | tutor | Both accept `chapter_id` + `notes` |
| `POST /assignments/{id}/submissions` | student | Now accepts `typed_answer`; files became optional |
| `GET /submissions/{id}` | tutor | Gains `typed_answer: {text, flag_reason}` and `marks[].scheme_conflict` |
| `GET/PUT /subjects/{id}/marking-rules` | tutor | Gains `summary` |

AI surfaces: **eight**. Seven from before plus `marking_rules`. Routing after
`AV-124`:

| Surface | Model | Shape |
|---|---|---|
| marking, extraction, syllabus, readiness | `claude-opus-5` | blank — inherits `anthropic_model` |
| reports, class_brief, narrative, marking_rules | `claude-sonnet-5` | pinned |

**Blank is not "unset"** — it means follow the default, so the next model move is
one line. Pins exist so a later bump of `anthropic_model` cannot silently drag
those four onto Opus. `tests/test_ai_provider.py` fails if a new surface escapes
both groups; it caught `marking_rules` doing exactly that.

**`render.yaml` restates the providers and wins over `config.py` in
production.** 3.2a nearly shipped as a no-op because of it.
`tests/test_render_routing.py` now fails if the two files disagree, in either
direction, reading `Settings.model_fields[...].default` so no local environment
can move the result.

---

## 5. What the remaining three tasks must know

### 3.4 — AI-marked mocks (`AV-26`, `E6`)

- `Assessment` / `AssessmentType` / `AssessmentScore` exist in
  `models/readiness.py` as **hand-entered scores**. The marking pipeline exists.
  **Nothing connects them** — that is the task.
- No parallel code path (`PROD-9`, `ADR-0004`). `Submission` is polymorphic:
  **never read `assignment_id` unconditionally** (`API-20`).
- A new `EvidenceSource` member gets a weight in `SOURCE_WEIGHTS` **in the same
  change** (`PROD-10`).
- `_MarkingSource` now carries `subject` and `classified`. A mock source must
  populate `subject` (the assembler needs it for `AV-24`) and may leave
  `classified` `None`, as `_past_paper_source` does.

### 3.5 — Past-paper booklets (`AV-117`)

- Reuse `SyllabusUpload`'s draft → review → apply pattern. **Do not invent a
  second one.** `api/syllabus_uploads.py::apply_syllabus` is the reference,
  including how it registers newly created rows in its lookup dicts so a repeated
  code merges instead of tripping a unique constraint.
- New prompt surface in `services/prompts.py` with a `version` (`AI-6`, `AI-7`),
  and a new entry in `SURFACES` + `SURFACE_FEATURE` + two `config.py` settings.
  The routing-group test will fail until you place it in one of the two groups.
- Handler safe to re-run: **replace the draft, never append** (`BE-6`).
- A single-paper upload skips extraction entirely and behaves as today.

### 3.6 — Timed mocks (`AV-115`, `AV-116`)

- Server-side clock. A client timer is a suggestion, not a limit.
- Late submissions are **accepted and flagged, never blocked** (`AV-116`).
- `Submission.timed` / `time_taken_minutes` are **self-declared** and must carry
  that label wherever shown (`PROD-8`, `UX-20`). **A measured mock is not
  self-declared and must not carry it** — the UI has to tell the two apart, so
  this is a new field, not a reuse of `timed`.

---

## 6. What later phases must pick up

| Phase | What is waiting |
|---|---|
| **4 (mistakes)** | `MistakeCategory` is still a fixed five-member enum. `Mistake` rows are still created by **nothing** — the audit called this "the defect". 4.2's prompt must preserve the untrusted-input clause and bump the version; marking is now at **v5**. |
| **5 (readiness)** | **The owner's outstanding decision** — see §8. Also `RISK-5`'s remaining half: `analytics.py`, `reports.py` and `student_crm.py` still read v1 tables directly. |
| **6 (teaching plan)** | `Subject.guidance_*` (Phase 2) is still stored and read by nothing. `Chapter.position` is the teaching order the plan schedules against. **3.1's "start of chapter" entry point was deferred to this phase** — see §7. |
| **10 (usage)** | `marking_rules` has its own `AiFeature` bucket, so "did summarising pay for itself" is answerable. Nothing records the *surface* on a usage row; the bucket is the only grouping. |

---

## 7. Deviations from the plan, recorded

1. **3.1's upload flow did not move to "start of chapter."** The plan says it is
   reached from the plan or the chapter list. The plan is Phase 6 and there is no
   chapter-list page — 2.3 built the chapter editor inside the *draft review*, not
   a view of an applied subject. The picker went on the flow that actually creates
   classifieds today. Raised in the PR body before branching.
2. **`chapter_id` is optional, not required.** A subject whose syllabus was never
   extracted chapter-first has no chapter to name. Whether a booklet should be
   *unable* to exist without one is a product call nobody has made.
3. **3.2 shipped as three PRs.** See §1.
4. **The summary is read-only to the tutor.** If they dislike it they edit their
   rules and it is rebuilt. An editable summary would be a third body of text that
   could disagree with the rules above it. Raised in the PR body; no answer yet.

---

## 8. Open items this phase did not own

- **Readiness must show how much of a student's standing rests on overridden
  marks.** The owner decided this on 9 Sep 2026, choosing it over "leave it" and
  over "discount them". **Not built.** `scheme_conflict` stops at the tutor's
  review page. Overridden marks still count in full — that half does not change.
  Needs a count or flag carried through the readiness snapshot and shown on the
  readiness surface, with copy saying what it is (`PROD-1`).
- **`AI_MODEL_PRICING` in the Render dashboard.** `sync: false`, so the deployed
  value is whatever was typed there. If it still prices only `claude-opus-4-8`,
  every call after 3.2a deploys records `cost_usd = NULL` and reports as unpriced.
  Re-paste from `backend/.env.example`, restart (`@lru_cache`), and verify
  `GET /api/v1/ai-usage/analytics` reports money. Malformed JSON is ignored rather
  than raised, so a typo fails silently.
- **`seed/summarise_marking_rules.py` has not been run.** Subjects whose rules
  predate 3.2c have never been saved since, so nothing queued a summary for them;
  they keep sending the full text into every marking call. Correct, just costly.
  `python -m seed.summarise_marking_rules` after deploying.
- **Prompt caching** — the owner wants it, deferred as "a point for later".
  `services/marking.py` already passes `cache_extra_system=True`, so the mechanism
  is partly in place.
- **~18 stale local branches** from earlier sessions. `CLAUDE.md` says the repo
  should hold the default branch, whatever is in flight, and `archive/*`.

---

## 9. What review caught, and what it cost

~35 findings across five PRs, cubic finding nearly all of them. The ones worth
carrying forward as habits:

- **Fail-open tests, three times.** Each asserted something was *absent* from a
  response that was empty for an unrelated reason — a student view with no marks
  because the submission was still queued, a re-mark check against a value never
  written. **Establish the value exists before asserting its absence.**
- **A guard that could not fire.** 3.1's "nothing marks with these yet" checked
  the prompt *template* for a substring, but 3.2 injects at request time from a
  service — it would have passed on the exact change it claimed to catch. Guards
  must assert on the code that reads the field, not on the artifact you expect it
  to appear in.
- **The trust boundary, twice.** See I4.
- **A race called impossible in its own docstring.** See I6.
- **`Form(max_length=...)` measuring raw text, twice.** See §3.
- **Two SonarCloud duplication failures** from repeated test setup. Extract the
  sequence; four copies is how they stop agreeing.

**No ECC subagent reviewers were used this phase.** `CLAUDE.md` and the owner's
standing instruction both ask for them. Several of the above — the fail-open
tests especially — are what `ecc:pr-test-analyzer` and `ecc:security-reviewer`
exist to catch before a PR is opened. Use them.

---

## 10. Verification state at handoff

```
# backend/
.venv/bin/python -m pytest -q          # 682 passed, 15 skipped
.venv/bin/ruff check app tests seed
.venv/bin/ruff format --check app tests seed
.venv/bin/python -m mypy app/services app/schemas

# frontend/
npm test                               # 202 passed
npm run lint && npm run build
npx prettier --check "src/**/*.{ts,tsx}"

# the migration chain runs on CI's Postgres 16 (up -> down -> up).
# Docker is unavailable on the owner's machine; there is no local Postgres.
```

Every new test this phase was checked against broken code before being claimed as
coverage — revert the fix, watch it fail, restore. Three did not fail on the first
attempt; those are the three in §9.
