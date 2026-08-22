# Avora / MANARA — Security and Scalability Deep Dive

**41 issues, each with a ready-to-paste AI-agent remediation prompt**
Compiled 7 August 2026 · repository `IGCSE-OS-product-repositiry-` @ `a568533`

---

## What this is

A focused security and scalability audit of the Avora / MANARA "IGCSE-OS" codebase, run with six independent review passes plus direct verification. It is a **companion to `Weaknesses-and-Remediation-Prompts.md`**, not a replacement — that document is the general defect register (38 issues, 6 Aug). This one goes deeper on two axes only: **can it be attacked** and **what breaks as it grows**.

Roughly two thirds of what follows is new relative to the 6 August register. Where an issue restates one already recorded there, it is tagged `↔ AV-n` and the entry explains what is new — usually a precise mechanism, a quantified threshold, or a second instance of the same bug nobody had found.

### How the findings were produced

| Pass | Agent | Scope |
|---|---|---|
| Security | `ecc:security-reviewer` | AuthN/AuthZ, IDOR, uploads, secrets, prompt injection, invites, CORS, compliance |
| Scalability | `ecc:architect` | Single-instance ceiling, worker throughput, event loop, growth modelling, cost |
| Database | `ecc:database-reviewer` | Indexes, referential integrity, constraints, N+1, transactions, migrations, pooling |
| Backend | `ecc:python-reviewer` | Async correctness, silent failures, AI-output handling, validation, resource leaks |
| Frontend | `ecc:react-reviewer` | Token handling, XSS, streaming, lost writes, cache, unbounded rendering |
| Checklist | `ecc:security-review` skill | OWASP baseline sweep |

### Evidence tags

| Tag | Meaning |
|---|---|
| **VERIFIED** | I read the code and confirmed the defect and its mechanism directly. Treat as fact. |
| **AGENT** | Found by a specialist review pass with file:line and quoted code. Strong evidence; not independently re-confirmed line by line. |
| **DERIVED** | A quantified model (throughput, cost, growth) built from verified code constants. The arithmetic and its assumptions are shown; the assumptions are stated so you can disagree with them. |

Nothing here is speculative. Every issue points at specific code.

### Severity key

| | Meaning |
|---|---|
| **S0** | Exploitable now, or destroying/exposing real data now |
| **S1** | Security or integrity exposure requiring a plausible precondition |
| **S2** | Already degrading at today's scale (one tutor) |
| **S3** | Breaks at 10× (10 tutors / 400 students) |
| **S4** | Breaks at 100× (50 tutors / 2,000 students) |
| **S5** | Compliance, hygiene, latent risk |

### How to use the prompts

Each issue ends with a fenced prompt block. It is self-contained — it carries its own context and works in a fresh session with no prior conversation. Paste it as-is into a coding agent, or read it as a ticket description with acceptance criteria.

**Every prompt states its constraints explicitly**, because the most common failure mode of an agent on this codebase is fixing the named thing and silently "improving" three others. The constraints are load-bearing; do not trim them.

**Work one issue per branch.** `CLAUDE.md` requires a PR for anything under `backend/`, `frontend/`, or `alembic/versions/` — a one-character edit included.

> **Do not let an agent merge S0 or S1 unattended.** Issues tagged **grading integrity** change how student marks are computed. The prompts require a regression test precisely so a human has something concrete to review.

---

## Triage table

### Security

| # | Issue | Sev | Evidence | Effort |
|---|---|---|---|---|
| [S-1](#s-1) | Private tutor notes and parent-comms log returned to the student they're about | S0 | VERIFIED | S |
| [S-2](#s-2) | AI-extracted `max_marks` is unbounded → permanently corrupted readiness | S0 | VERIFIED | S |
| [S-3](#s-3) | Syllabus `weight` unbounded; a negative weight inverts a topic's contribution | S0 | VERIFIED | S |
| [S-4](#s-4) | `JWT_SECRET` insecure default, no startup guard, and the OAuth key derives from it | S1 | VERIFIED ↔ AV-10/11 | S |
| [S-5](#s-5) | Knowledge Base `body` unbounded → prompt-injection amplifier across a whole roster | S1 | AGENT | S |
| [S-6](#s-6) | Upload body fully buffered in memory *before* the 20 MB check | S1 | VERIFIED | S |
| [S-7](#s-7) | HEIC transcode has no pixel-count guard → decompression bomb | S1 | VERIFIED | S |
| [S-8](#s-8) | No AI spend cap on any surface except student chat | S1 | AGENT | M |
| [S-9](#s-9) | Resubmission is uncapped → uncapped marking spend and worker starvation | S1 | AGENT | S |
| [S-10](#s-10) | No rate limit on registration, join, or invite redemption; enumeration oracle | S2 | AGENT | S |
| [S-11](#s-11) | Unbounded syllabus tree recursion → `RecursionError` 500 | S2 | AGENT | S |
| [S-12](#s-12) | Client filename flows unsanitized into `Content-Disposition` | S5 | AGENT | S |
| [S-13](#s-13) | No account deletion or data-erasure path anywhere (UK-GDPR) | S5 | VERIFIED | L |
| [S-14](#s-14) | `admin` is a global cross-tenant superuser with no read audit trail | S5 | AGENT ↔ AV-8 | M |

### Data integrity and loss

| # | Issue | Sev | Evidence | Effort |
|---|---|---|---|---|
| [D-1](#d-1) | Tutor's typed marks and feedback silently discarded on window refocus | S0 | VERIFIED | S |
| [D-2](#d-2) | `DELETE /groups/{id}` raises a raw 500 for any group with real history | S0 | VERIFIED | M |
| [D-3](#d-3) | Syllabus editor PUTs the whole tree per keystroke → lost updates | S1 | AGENT | M |
| [D-4](#d-4) | Zero `ondelete=` on 109 FKs; zero `CheckConstraint` anywhere | S1 | VERIFIED ↔ AV-15/16 | M |
| [D-5](#d-5) | `past_paper_attempts` has no unique constraint and a read-modify-write race | S1 | AGENT | S |
| [D-6](#d-6) | Marking failure commits half-finalized marks alongside `ai_failed` | S1 | AGENT | M |
| [D-7](#d-7) | No per-job timeout — one hung job stalls the pipeline for every tenant | S1 | AGENT | S |
| [D-8](#d-8) | Classroom sync: unpaginated, serial N+1, and can orphan a submission | S2 | AGENT ↔ AV-6/20/21 | M |
| [D-9](#d-9) | Query cache never cleared on logout → cross-account data flash | S1 | AGENT | S |
| [D-10](#d-10) | Chat stream is uncancellable and bleeds across conversations | S2 | AGENT ↔ AV-34 | S |
| [D-11](#d-11) | Concurrent double-submit raises an uncaught `IntegrityError` → 500 | S2 | AGENT | S |
| [D-12](#d-12) | Failed fetches render as "0 due / all caught up" and as an empty review queue | S2 | AGENT | S |
| [D-13](#d-13) | SQLite tests structurally cannot catch FK or row-lock bugs | S3 | AGENT ↔ AV-29 | M |

### Scalability and cost

| # | Issue | Sev | Evidence | Effort |
|---|---|---|---|---|
| [X-1](#x-1) | Readiness synthesis runs on **Opus** by omission — 51% of all AI spend | S2 | VERIFIED | XS |
| [X-2](#x-2) | One weights-slider save fans out to N×M Opus calls inside one request | S2 | VERIFIED | M |
| [X-3](#x-3) | Connection pool unconfigured; worker holds one through a 45 s AI call | S2 | VERIFIED | S |
| [X-4](#x-4) | Job worker is strictly serial → 12.5-minute tail on a class of 30 | S2 | DERIVED ↔ AV-26 | L |
| [X-5](#x-5) | Readiness debounce doesn't debounce a class; misses `running`; races | S2 | AGENT | M |
| [X-6](#x-6) | 109 foreign keys, 5 indexes | S3 | VERIFIED ↔ AV-23 | S |
| [X-7](#x-7) | bcrypt, HEIC transcode and all file I/O block the shared event loop | S3 | VERIFIED ↔ AV-22 | M |
| [X-8](#x-8) | N+1 cluster across 15 confirmed sites; worst is 1+5A per page load | S3 | AGENT ↔ AV-24 | L |
| [X-9](#x-9) | Chat resends full history every turn + 50 CRM queries per message | S3 | AGENT | M |
| [X-10](#x-10) | 36 unbounded list endpoints, zero accept `limit`/`offset` | S3 | AGENT ↔ AV-25 | L |
| [X-11](#x-11) | No refresh coalescing, no `staleTime`, no virtualization, unconditional 5 s poll | S3 | VERIFIED ↔ AV-33 | M |
| [X-12](#x-12) | DB session held open for the full duration of a streamed chat reply | S3 | AGENT | S |
| [X-13](#x-13) | `factor_evaluations`, `jobs`, `chat_messages`, `ai_usage_events` grow forever | S4 | DERIVED ↔ AV-28 | M |
| [X-14](#x-14) | `/health/ready` full-scans `jobs` and will report a false outage | S4 | AGENT | XS |
| [X-15](#x-15) | The single-instance ceiling, and the forced order of lifting it | S4 | DERIVED ↔ AV-27 | XL |

---

# Security

<a id="s-1"></a>
## S-1 — Private tutor notes and the parent-communications log are returned to the student they are about

**S0 · VERIFIED · effort S**

`backend/app/api/students.py:104-173`, `backend/app/services/student_crm.py:147-160`

`GET /students/{student_id}/crm` is gated with `CurrentUser` — any authenticated role — and resolves access through `_viewable_student` (`students.py:38-68`), which deliberately admits three viewers:

```python
if viewer.role == UserRole.student:
    if viewer.id != student_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
    return student
if viewer.role == UserRole.parent:
    link = await db.scalar(select(ParentLink).where(...))
    ...
```

That is correct for readiness, enrollments and homework history. But the handler then serializes the full response with **no branch on `user.role`**:

```python
notes=[TutorNoteOut(id=n.id, tutor_id=n.tutor_id, tutor_name=..., body=n.body, ...) for n in crm.notes],
communications=[ParentCommunicationOut(..., body=c.body, ...) for c in crm.communications],
```

`TutorNote` is documented in `models/crm.py:41-43` as *"An append-only timeline entry a tutor writes about a student — context, observations, reminders."* `ParentCommunication` is the log of what the tutor said to the parent, privately, about the student.

**Exploit path.** A student authenticates normally and calls `GET /api/v1/students/{their_own_id}/crm` with their own bearer token. Every candid observation a tutor has ever written about them comes back verbatim — disengagement notes, safeguarding-adjacent remarks, notes about the family. A parent gets the same. Both are fully "authorized" by the role check.

The sibling write path `_tutor_student` (`students.py:71+`) is correctly tutor-only, and `assessments.py`'s `/students/{id}/observations` is correctly `TutorUser`-gated. This endpoint is the one that isn't. It is not currently called by the frontend, which is **not a mitigation** — `SEC-10` says exactly that.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (FastAPI + SQLAlchemy 2 async
+ React). Fix a data-exposure defect in the Student CRM endpoint.

THE DEFECT
`GET /students/{student_id}/crm` in backend/app/api/students.py:104-173 is gated with
`CurrentUser` (any role). Its access helper `_viewable_student` (students.py:38-68)
deliberately and correctly admits the student themselves and any linked parent, in
addition to the teaching tutor and admins. But the handler then serializes `notes`
(TutorNote — the tutor's private working observations about the student) and
`communications` (ParentCommunication — the private tutor-to-parent log) into the
response with no branch on `user.role`. A student calling this endpoint with their own
token receives every private note ever written about them. A parent receives the same.

WHAT TO CHANGE
In backend/app/api/students.py, return `notes` and `communications` as empty lists
unless `user.role` is in `TUTOR_ROLES` (imported from app.api.deps — it is
`(UserRole.tutor, UserRole.admin)`). Keep every other field exactly as it is: profile,
enrollments, readiness and homework are correct for all three viewer roles and must
keep working unchanged for students and parents.

Prefer filtering in the router over changing `get_student_crm` in
services/student_crm.py — that aggregation is also the source of the AI's grounding
context (services/student_context.py), and narrowing it there would silently change
what the AI tutor knows about the student. Do not touch it.

CONSTRAINTS
- Do not change `_viewable_student`. Student and parent read access to this endpoint is
  intended; only the two private collections are not.
- Do not add a new endpoint. Do not restructure the response model — `StudentCrmOut`
  keeps both fields, they are just empty for non-tutor viewers.
- Do not "improve" anything else in students.py.

TESTS (required, in backend/tests/test_crm.py)
Per the repo's QA-12 rule, a change touching authorization ships with a test asserting
the negative case. Add three:
1. A tutor who teaches the student GETs /students/{id}/crm and receives the notes and
   communications they wrote.
2. The student GETs their own /students/{id}/crm, receives 200, and gets `notes == []`
   and `communications == []` — while still receiving their profile, enrollments,
   readiness and homework.
3. A linked parent GETs the child's /students/{id}/crm and likewise gets empty `notes`
   and `communications` with the rest of the payload intact.

VERIFY
cd backend && .venv/bin/python -m pytest tests/test_crm.py tests/test_authorization.py
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .

Then update docs/volume-3-platform-engineering/07-security-architecture.md to record
the rule that private CRM collections are tutor-only, per the repo's GOV-1 rule that a
behaviour change updates the constitution document describing it in the same PR.
```

---

<a id="s-2"></a>
## S-2 — AI-extracted `max_marks` is unbounded, and it is the grading denominator

**S0 · VERIFIED · grading integrity · effort S**

`backend/app/services/extraction.py:28` vs `backend/app/schemas/homework.py:34`

Two paths write the same column. They validate differently:

```python
# extraction.py:28 — the AI path
max_marks: int = Field(description="Maximum marks for this question")

# schemas/homework.py:34 — the tutor-typed path
max_marks: int = Field(ge=1, le=200)
```

The AI path has no bounds at all. `extraction.py:143` and `:242` apply only a lower clamp — `max_marks=max(1, q.max_marks)`.

**Failure scenario.** OCR misreads a 5-mark question as 500 — a well-known failure mode on scanned exam booklets. The value is stored. `extraction.py:74-76` publishes the assignment immediately (*"so students aren't blocked on the tutor coming back for a second pass"*), so there is no mandatory human check between extraction and students submitting against it.

A student then answers perfectly and scores 5. `marking.py:293` correctly clamps the **numerator** to the max — `max(0, min(q.max_marks, draft.proposed_marks))` — so the mark is recorded as 5. But every downstream percentage divides by 500:

- `_upsert_attempt_rollup` (`marking.py:392-399`)
- Topic Mastery in `readiness_factors.py`
- the readiness percentage, and therefore `predict_grade()`

The student's mastery on that topic reads **1% instead of 100%**, permanently, and it looks like real data because the evidence chain is intact. This is precisely the class of thing `PROD-1` ("no metric exists unless MANARA can explain where it came from") exists to prevent, defeated by a missing `le=`.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (FastAPI + SQLAlchemy 2 async).
Fix a grading-integrity defect. Read this whole prompt before editing — the fix is small
but the blast radius of getting it wrong is student grades.

THE DEFECT
Two code paths write `assignment_questions.max_marks`, which is the denominator of every
downstream mastery percentage and therefore of every predicted grade.

  - The tutor-typed path validates it: backend/app/schemas/homework.py:34
    `max_marks: int = Field(ge=1, le=200)`
  - The AI-extraction path does not: backend/app/services/extraction.py:28
    `max_marks: int = Field(description="Maximum marks for this question")`

extraction.py:143 and :242 apply only `max(1, q.max_marks)` — a lower clamp, no ceiling.
extraction.py:74-76 publishes the assignment immediately with no mandatory tutor review.

Consequence: an OCR misread turning "5" into "500" is stored unchallenged. Marking
correctly clamps the numerator (marking.py:293) so the student scores 5, but every
percentage divides by 500 and that student's topic mastery reads ~1% instead of 100%,
permanently, with a fully intact and plausible-looking evidence chain.

WHAT TO CHANGE
1. In backend/app/services/extraction.py, bound `ExtractedQuestion.max_marks` to exactly
   the same range as the manual schema: `Field(ge=1, le=200, description=...)`. Keep the
   description text — it is part of the prompt contract with the model.
2. Pydantic will now raise on an out-of-range value, which fails the whole extraction
   job. That is worse than the status quo for the tutor, so also handle it: rather than
   letting one bad question kill the batch, drop out-of-range questions and record the
   fact on the Assignment so a human sees it. Follow the existing failure-surfacing
   pattern already in this file for extraction errors — do not invent a new one. If
   after filtering there are zero valid questions, that IS an extraction failure and
   should go down the existing failure path.
3. Check backend/app/services/extraction.py's past-paper extractor (the
   `extract_past_paper` path, around :242) — it shares `ExtractedQuestion`, so confirm
   the same fix covers it and that its own clamp at :242 is now redundant rather than
   contradictory.

CONSTRAINTS
- 200 is the number, because that is what the tutor-typed schema already enforces. Do not
  pick a different ceiling for the AI path — the whole defect is that the two paths
  disagree.
- Do not change marking.py's numerator clamp at :293. It is correct.
- Do not change the auto-publish behaviour at extraction.py:74-76. That is a deliberate
  product decision (ADR-0009 / the trust-first trade) and is out of scope here.
- Do not touch the prompt text in services/prompts.py. If you did need to (you should
  not), AI-7 requires bumping its `version`.

TESTS (required, backend/tests/test_homework.py or test_new_capabilities.py)
Use the `fake_ai` fixture and monkeypatch the CALLING module's `structured_complete`
(QA-7 — patching app.services.ai does nothing, services import the helper into their own
namespace). Drive the job with `process_one_job()`, never `worker_loop()` (QA-6).
1. Extraction returning `max_marks=500` for one of three questions stores the two valid
   questions and does not store the 500 one.
2. Extraction returning `max_marks=500` for EVERY question ends in the assignment's
   existing extraction-failed state, not a published assignment with no questions.
3. A regression test that pins the invariant directly: no AssignmentQuestion row can be
   created with max_marks > 200 via the extraction path.

VERIFY
cd backend && .venv/bin/python -m pytest tests/ -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .

Then update docs/volume-3-platform-engineering/09-ai-platform.md — it documents what is
validated between "the AI said it" and "we wrote it to the student's record", and this
changes that. GOV-1 requires it in the same PR.
```

---

<a id="s-3"></a>
## S-3 — Syllabus topic `weight` is unbounded; a negative weight inverts a topic's contribution

**S0 · VERIFIED · grading integrity · effort S**

`backend/app/schemas/syllabus.py:9-17`, used at `backend/app/services/readiness.py:219`

```python
class GradeBoundaryIn(BaseModel):
    grade: str
    min: int              # no ge=0, no le=100

class SyllabusTopicIn(BaseModel):
    code: str
    title: str
    weight: float = 1.0   # no bounds at all
    children: list[SyllabusTopicIn] = []
```

`api/syllabus_uploads.py:126,136,151` writes these straight into `Subject.grade_boundaries` and `Topic.weight` after only `SyllabusDraft.model_validate(...)` — a shape check, not a range check. The same schema serves both the AI extraction output **and** the tutor's manual `PUT /syllabus-uploads/{id}/draft` edit, so a typo is as dangerous as a hallucination.

`services/readiness.py:219` then uses the value directly as a weighted-average multiplier:

```python
results.append((result, topic.weight))
```

**Failure scenario.** A weight of `-5` on one topic makes that topic *subtract* from the subject's readiness in proportion to how well the student is doing on it. The resulting score contradicts the underlying evidence while every individual piece of evidence remains correct and auditable — the worst possible shape for a bug in a system whose entire premise is explainability. A grade boundary `min` of `-10` or `500` similarly breaks `predict_grade()` silently.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (FastAPI + SQLAlchemy 2 async).
Fix a grading-integrity defect in syllabus validation.

THE DEFECT
backend/app/schemas/syllabus.py declares:
    class GradeBoundaryIn:  grade: str;  min: int          # no bounds
    class SyllabusTopicIn:  code: str; title: str; weight: float = 1.0   # no bounds

These are written straight to Subject.grade_boundaries and Topic.weight by
backend/app/api/syllabus_uploads.py:126,136,151 after only
`SyllabusDraft.model_validate(...)`, which validates shape, not range.

backend/app/services/readiness.py:219 then uses `topic.weight` directly as a
weighted-average multiplier: `results.append((result, topic.weight))`.

A negative weight makes a topic subtract from subject readiness in proportion to how
well the student is doing on it, producing a score that contradicts its own evidence.
An out-of-range grade-boundary `min` silently breaks predict_grade().

This schema is shared by the AI extraction output AND the tutor's manual draft edit
(PUT /syllabus-uploads/{id}/draft), so both paths are affected and both must be fixed by
the same change.

WHAT TO CHANGE
1. backend/app/schemas/syllabus.py:
   - `weight: float = Field(default=1.0, ge=0.0, le=10.0)`
   - `min: int = Field(ge=0, le=100)`
   Pick these bounds deliberately: weight 0 must stay legal (it means "this topic does
   not count"), and grade-boundary minimums are percentages.
2. backend/app/services/syllabus_extraction.py declares a parallel `ExtractedTopic`
   model for the AI's output. Apply the identical bounds there so the AI path fails at
   parse time rather than at apply time.
3. Validation failure must not become a 500. In api/syllabus_uploads.py, a draft that
   fails `SyllabusDraft.model_validate` on apply should return a 422 naming the offending
   topic code and field, so the tutor can fix it in the draft editor. Check how the file
   already surfaces validation errors and match that shape — do not invent a new error
   format.

CONSTRAINTS
- Do NOT clamp silently. A weight of -5 must be rejected with a message, not coerced to
  0 — the tutor needs to know their draft is wrong. Silent coercion in a grading system
  is how you get a number nobody can explain, which is exactly what PROD-1 forbids.
- Do not change services/readiness.py. Its arithmetic is correct given valid input; the
  defect is that invalid input reaches it.
- Do not change the syllabus extraction prompt in services/prompts.py.

TESTS (required, backend/tests/test_syllabus_upload.py)
1. Applying a draft with `weight: -5` returns 422 and creates no Topic rows.
2. Applying a draft with `weight: 0` succeeds — zero is a legitimate weight.
3. Applying a draft with a grade boundary `min: 150` returns 422.
4. A valid draft still applies end to end exactly as before (regression).
5. The AI-extraction path rejects a hallucinated negative weight at parse time. Use the
   `fake_ai` fixture, patch the calling module's structured_complete (QA-7), and drive
   the job with process_one_job() (QA-6).

VERIFY
cd backend && .venv/bin/python -m pytest tests/test_syllabus_upload.py tests/test_readiness_engine.py -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

---

<a id="s-4"></a>
## S-4 — `JWT_SECRET` has an insecure default, no startup guard, and the OAuth encryption key derives from it

**S1 · VERIFIED · ↔ AV-10, AV-11 · effort S**

`backend/app/config.py:24,84`, `backend/app/services/google_classroom.py:84-87`

```python
jwt_secret: str = "change-me-in-production"
google_token_encryption_key: str | None = None
```

```python
def _fernet() -> Fernet:
    material = (settings.google_token_encryption_key or settings.jwt_secret).encode()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(material).digest()))
```

Nothing in `config.py`, `main.py` or `security.py` refuses to boot, or even warns, when `jwt_secret` is still the literal default — a string committed to this repository.

**What is new since AV-10/AV-11.** Both remain open at `a568533`, and the two compound in a way worth stating plainly: because the Google token key *falls back to* the JWT secret, one unset environment variable simultaneously (a) lets anyone forge a valid access token for any `user_id` and any role, and (b) makes every stored `google_accounts.encrypted_refresh_token` decryptable by anyone who obtains a database dump, since the derivation is public and needs only that same known string.

`render.yaml` does set `generateValue: true` for both, so the documented Render deploy is not exploitable. The defect is that the application provides no defence in depth for any other path — a bare `uvicorn`, a different PaaS, or a Render environment-variable reset.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (FastAPI, Python 3.11).
Make secret configuration fail closed instead of open.

THE DEFECT
backend/app/config.py:24 declares `jwt_secret: str = "change-me-in-production"` — a value
committed to this public repository. Nothing anywhere refuses to start when it is still
in use.

backend/app/config.py:84 declares `google_token_encryption_key: str | None = None`, and
backend/app/services/google_classroom.py:84-87 derives the Fernet key from
`(settings.google_token_encryption_key or settings.jwt_secret)`.

So a single unset environment variable means both that anyone can forge a valid JWT for
any user and role (app/security.py signs and verifies with settings.jwt_secret alone),
and that every stored Google refresh token is decryptable by anyone with a database dump.

render.yaml correctly uses `generateValue: true` for both, so the documented deploy is
safe. This is about defence in depth for every other path.

WHAT TO CHANGE
1. Add a startup guard that raises before the app serves any request if
   `jwt_secret == "change-me-in-production"`, or if it is shorter than 32 characters.
2. That guard must NOT fire in local development or under pytest — the test suite and
   `docker compose up` both need to run without ceremony. Look at how the repo already
   distinguishes those contexts (backend/tests/conftest.py sets DATABASE_URL to
   sqlite+aiosqlite before any app import; docker-compose.yml sets an explicit dev value)
   and pick the mechanism that fits what is already there rather than adding a new
   environment variable if one will do.
3. Stop `google_token_encryption_key` silently falling back to `jwt_secret`. Two
   independent secrets should be two independent secrets. Given the fallback is load
   bearing for existing deployments that never set it, the safe change is: keep the
   fallback working, but make it explicit and loud — log a warning at startup naming the
   variable, and document in .env.example that it must be set separately in production.
   Do NOT break decryption of tokens already stored under the derived key.
4. Update backend/.env.example so both variables are present with a comment saying they
   must be set and how to generate them.

CONSTRAINTS
- Point 3 is the one to be careful with. Any change that alters the derived key breaks
  decryption of every already-stored Google refresh token, silently disconnecting every
  tutor's Classroom integration with no error until they next sync. If you cannot make
  the change without that risk, do only the warning and the documentation, and say so.
- Do not change app/security.py's token signing or verification.
- A missing AI provider key must still degrade gracefully rather than block startup
  (AI-20 / INF-9). This guard is for the JWT secret only — do not extend it to the AI
  keys.

TESTS (required, backend/tests/test_security_hardening.py)
1. Constructing Settings with the placeholder secret, in a non-test context, raises.
2. The existing test suite still runs — this is the important one. If your guard breaks
   conftest.py, the mechanism is wrong.
3. A Google refresh token encrypted before the change still decrypts after it.

VERIFY
cd backend && .venv/bin/python -m pytest -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .

Then update docs/volume-3-platform-engineering/07-security-architecture.md (GOV-1).
```

---

<a id="s-5"></a>
## S-5 — Knowledge Base `body` is unbounded and injected verbatim into every AI call for the whole roster

**S1 · AGENT · effort S**

`backend/app/schemas/knowledge.py:11,17`, `backend/app/services/knowledge.py:22-49`

`body: str = Field(min_length=1)` — no `max_length`. `build_tutor_context` concatenates every entry into a system prompt used by marking (`marking.py:254`), extraction (`extraction.py:122`), readiness synthesis (`readiness_v2_ai.py:206`), reports, and chat (`chat.py:128`) — for **every** student and subject that tutor teaches.

One entry kind is `ai_instruction`, injected as a direct instruction to the model.

**Failure scenario.** A tutor — or a compromised tutor account — pastes megabytes into one entry. Every subsequent marking, extraction and readiness call for that tutor's entire roster re-sends and is billed for the payload, and can push prompts past the context window, causing `structured_complete` to fail simultaneously across marking, extraction and readiness. That is not the graceful "AI not configured" degradation the rest of the system is built around; it is three subsystems failing at once from one text field.

It is also the highest-leverage prompt-injection surface in the product: `ai_instruction` content is, by design, instructions, and it reaches the marking prompt for every student that tutor teaches.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (FastAPI, Python 3.11).
Bound the Tutor Knowledge Base so one text field cannot break every AI surface at once.

THE DEFECT
backend/app/schemas/knowledge.py:11,17 declares `body: str = Field(min_length=1)` with no
max_length. backend/app/services/knowledge.py:22-49 (`build_tutor_context`) concatenates
every one of a tutor's KB entries into a single system-prompt block that is injected into
marking (services/marking.py:254), extraction (services/extraction.py:122), readiness
synthesis (services/readiness_v2_ai.py:206), reports, and chat (api/chat.py:128) — for
every student and subject that tutor teaches.

A single very large entry is therefore re-sent and re-billed on every AI call across the
whole roster, and can push prompts past the model context window, failing marking,
extraction and readiness simultaneously.

WHAT TO CHANGE
1. Add `max_length` to `body` in backend/app/schemas/knowledge.py — both the create and
   the update schema. 4000 characters is a reasonable per-entry ceiling for the stated
   purpose (teaching methods, marking preferences, direct AI instructions); justify
   whatever you pick in a comment.
2. Add a total-size ceiling per tutor, enforced in services/knowledge.py where the
   context is compiled. If the compiled block exceeds the ceiling, truncate
   deterministically and predictably — highest-priority kinds first, oldest entries
   dropped last — and make the truncation visible rather than silent. Read the KIND_LABELS
   ordering already in that file and preserve its intent.
3. Return 422 with a clear message when an entry exceeds the per-entry limit, so a tutor
   pasting a long document learns why immediately.

CONSTRAINTS
- Do not change what the KB does or which surfaces it reaches. This is a bounds fix, not
  a redesign.
- Truncation must be deterministic. A prompt whose content depends on iteration order is
  unreproducible, and AI-6/AI-7 treat prompts as versioned artifacts.
- Do not change services/prompts.py. If the compiled block's structure changes enough
  that the prompt text needs editing, bump its `version` per AI-7 and say so in the PR.

TESTS (required, backend/tests/test_knowledge.py)
1. Creating an entry over the per-entry limit returns 422.
2. Updating an existing entry over the limit returns 422.
3. A tutor with many entries totalling more than the roster ceiling produces a compiled
   context at or under the ceiling, and the truncation is deterministic across two calls
   with the same data.
4. A normal-sized KB compiles to exactly what it compiles to today (regression).

VERIFY
cd backend && .venv/bin/python -m pytest tests/test_knowledge.py tests/test_chat.py -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

---

<a id="s-6"></a>
## S-6 — The upload body is fully buffered in memory *before* the 20 MB limit is checked

**S1 · VERIFIED · effort S**

`backend/app/services/storage.py:108-112`

```python
data = await file.read()
if len(data) > MAX_FILE_BYTES:
    raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Files must be 20 MB or smaller")
```

The limit is enforced *after* the allocation it is supposed to prevent. `file.read()` pulls the entire spooled upload into a single `bytes` object; the 413 is raised once the memory is already committed.

The API runs on Render `starter` (`render.yaml:18`) as a single instance with the job worker in-process. An unauthenticated-adjacent actor (any student account) POSTing a few hundred megabytes to any of the seven upload endpoints — `submissions.py:134`, `past_papers.py:144-145`, `classifieds.py:35,46`, `resources.py:81`, `syllabus_uploads.py:43` — can drive the process to OOM. Render restarts it, taking the in-process job worker and everything queued in it down with the API.

Note the contrast: `save_bytes` (`storage.py:126-143`) — the path for Google Drive attachments — gets this right, capping the source bytes before `_normalize`, with a comment explaining exactly why. The direct-upload path does not.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (FastAPI, Python 3.11).
Fix a memory-exhaustion defect in the upload path.

THE DEFECT
backend/app/services/storage.py:108-112 in `save_upload`:

    data = await file.read()
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(413, "Files must be 20 MB or smaller")

The 20 MB cap is checked AFTER the entire upload has been read into one bytes object, so
the allocation the limit exists to prevent has already happened. Any authenticated user
POSTing a large body to any of the seven upload endpoints (api/submissions.py:134,
api/past_papers.py:144-145, api/classifieds.py:35,46, api/resources.py:81,
api/syllabus_uploads.py:43) can OOM the process. The API is a single Render `starter`
instance that also runs the in-process job worker, so an OOM restart takes background
marking, extraction and readiness down with it.

The sibling function `save_bytes` (storage.py:126-143) already does this correctly and
its comment explains why. Match it.

WHAT TO CHANGE
In backend/app/services/storage.py's `save_upload`, read the upload in bounded chunks and
abort as soon as the accumulated size exceeds MAX_FILE_BYTES, rather than reading it all
and measuring afterwards. Starlette's UploadFile supports `await file.read(n)` for a
bounded read — loop it, accumulate, and raise the same HTTP 413 with the same message the
moment the total exceeds the cap.

Keep everything downstream identical: the mime alias resolution, the `_normalize` HEIC
transcode, the `content_matches_mime` magic-byte check, and `_write`. Only the acquisition
of `data` changes.

CONSTRAINTS
- The 413 status code and its exact message string must not change — clients and tests
  depend on it.
- Do not change MAX_FILE_BYTES.
- Do not change `save_bytes`. It is already correct and is the reference for this fix.
- Do not touch the magic-byte validation. It is correct and is a separate control.

TESTS (required, backend/tests/test_homework.py or a new test_storage.py)
1. An upload just under the cap succeeds and stores correctly (regression).
2. An upload over the cap returns 413.
3. The important one: assert the oversized upload is rejected WITHOUT the whole body
   being materialized. Test the chunked read directly rather than trying to measure
   process memory — e.g. feed a file-like object that raises if read past a bounded
   number of bytes, and assert save_upload raises 413 rather than that error.

VERIFY
cd backend && .venv/bin/python -m pytest tests/ -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .

Related but SEPARATE issue — do not fix it here: storage.py's disk writes and the HEIC
transcode are synchronous calls on the shared event loop. That is issue X-7 and has its
own prompt.
```

---

<a id="s-7"></a>
## S-7 — HEIC transcode has no pixel-count guard

**S1 · VERIFIED · effort S**

`backend/app/services/storage.py:35-45`

```python
def _to_jpeg(data: bytes) -> bytes:
    import pillow_heif
    from PIL import Image
    pillow_heif.register_heif_opener()
    with Image.open(io.BytesIO(data)) as img:
        buffer = io.BytesIO()
        img.convert("RGB").save(buffer, format="JPEG", quality=90)
        return buffer.getvalue()
```

The 20 MB cap bounds the *compressed* input. It does not bound the decoded bitmap. A validly-formed HEIC well under 20 MB can declare enormous dimensions; `img.convert("RGB")` then allocates width × height × 3 bytes. A 30,000 × 30,000 image is 2.7 GB.

Pillow ships a `MAX_IMAGE_PIXELS` guard (~89 M pixels) that emits a `DecompressionBombWarning` and raises above 2×, but it is a *warning* by default and nothing here configures it or converts it to an error.

Compounding: the decode is CPU-bound and synchronous on the shared event loop (see X-7), so a bomb blocks every other request while it inflates, and iPhone HEIC is the *default* upload format for the product's core student flow.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (FastAPI, Python 3.11).
Add a decompression-bomb guard to HEIC upload handling.

THE DEFECT
backend/app/services/storage.py:35-45 `_to_jpeg` decodes uploaded HEIC/HEIF images with
Pillow and re-encodes them as JPEG:

    with Image.open(io.BytesIO(data)) as img:
        buffer = io.BytesIO()
        img.convert("RGB").save(buffer, format="JPEG", quality=90)

MAX_FILE_BYTES (20 MB) bounds the COMPRESSED input, not the decoded bitmap. A valid HEIC
comfortably under 20 MB can declare very large dimensions; `img.convert("RGB")` then
allocates width * height * 3 bytes. 30000x30000 is 2.7 GB, which OOMs the single Render
instance — taking the in-process job worker down with the API.

Pillow's MAX_IMAGE_PIXELS default only emits a DecompressionBombWarning; nothing in this
codebase configures it or promotes it to an error.

This path is the DEFAULT for the product's core flow — iPhones photograph in HEIC and
students photograph handwritten homework.

WHAT TO CHANGE
In backend/app/services/storage.py:
1. Check declared dimensions before decoding pixel data. `Image.open` is lazy — it reads
   the header and gives you `img.size` before any bitmap is allocated. Reject an image
   whose width*height exceeds a stated maximum before calling `.convert("RGB")`.
2. Pick the limit from what the product actually needs: a page of handwritten A4
   photographed by a phone. 50 megapixels is generous for that; state your reasoning in a
   comment, as this file already does for its other limits.
3. Rejection must produce the same user-facing failure the existing corrupt-photo path
   produces — a ValueError that `save_upload` turns into a 415 with a message a student
   can act on. Read the existing `_normalize` error handling at storage.py:54-66 and
   match it; do not add a new error shape.
4. Set `Image.MAX_IMAGE_PIXELS` explicitly as a second line of defence rather than
   relying on the library default.

CONSTRAINTS
- Do not change MAX_FILE_BYTES or the magic-byte validation.
- The existing `except Exception: # noqa: BLE001` at storage.py:57 is deliberate and
  justified (its comment explains that Pillow raises across a wide surface on malformed
  input). Keep it. Your new check should raise the same ValueError it already converts.
- Do not make the HEIC path async in this change — moving blocking work off the event
  loop is issue X-7 and has its own prompt. Keep the two changes separable.

TESTS (required, backend/tests/ — a new test_storage.py is fine)
1. A normal phone-sized HEIC still transcodes to JPEG and stores (regression). If the
   suite has no HEIC fixture, construct one in the test rather than committing a binary.
2. An image declaring dimensions over the limit is rejected with the 415 path, and the
   test asserts no full-size bitmap was allocated (assert on the raised error, not on
   memory).
3. A corrupt/undecodable HEIC still produces the existing friendly 415 (regression).

VERIFY
cd backend && .venv/bin/python -m pytest tests/ -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

---

<a id="s-8"></a>
## S-8 — No AI spend cap on any surface except student chat

**S1 · AGENT · effort M**

The complete enumeration of every guard in the codebase:

| Guard | Location | What it actually bounds |
|---|---|---|
| `DAILY_MESSAGE_LIMIT = 50` | `api/chat.py:35` | Chat messages per student per rolling 24 h. **The only spend cap that exists.** |
| `MAX_FILE_BYTES = 20 MB` | `services/storage.py:13` | Input size, not call count |
| `MAX_ATTEMPTS = 2` | `workers/jobs.py:25` | A *failing* job to two AI calls |
| `readiness_v2_coalesce_seconds = 600` | `config.py:72` | A debounce per (student, subject) — not a cap, and see X-5 |

Everything else is unthrottled: `POST /past-papers` (full-paper Gemini extraction), `POST /assignments/{id}/retry-extraction` (re-runs extraction over the same document, no cooldown), `POST /groups/{id}/brief` (an Opus call, see X-1), and every resubmission-triggered marking pass (see S-9).

`ai_usage_events` is explicitly tracking-only — `models/ai_usage.py:20-22` says so, and `record_usage` (`ai.py:419-448`) writes a row and returns. **Nothing reads it before a call.**

Worse for observability: `AI_MODEL_PRICING` defaults to `{}` (`config.py:59`) and `render.yaml:76-77` marks it `sync: false`. If it was never filled in from the Render dashboard, `estimate_cost_usd` returns `None` for every model, every `cost_usd` is NULL, and `api/ai_usage.py:105-110` reports `total_cost_usd: 0.0` with everything in `unpriced_call_count`. That is correct behaviour per `AI-17` ("never invent a price") — but it means **the platform may currently be unable to tell you what it is spending at all.**

```
The repository is the Avora / MANARA "IGCSE-OS" platform (FastAPI, Python 3.11).
Add enforceable AI spend limits. Today there is exactly one, and it covers one surface.

CURRENT STATE (verified — do not re-derive, but do confirm before changing)
- api/chat.py:35 `DAILY_MESSAGE_LIMIT = 50` per student per rolling 24h. The ONLY cap.
- services/rate_limit.py contains only `login_limiter`.
- ai_usage_events is tracking-only by design (models/ai_usage.py:20-22); record_usage
  (services/ai.py:419-448) writes a row after the fact and nothing reads it before a call.
- Unthrottled AI-spending endpoints: POST /past-papers (Gemini full-paper extraction),
  POST /assignments/{id}/retry-extraction (no cooldown, re-runs over the same document),
  POST /groups/{id}/brief (an Anthropic call), and every resubmission-triggered marking
  pass.

WHAT TO BUILD
A per-organization daily AI-call budget, enforced BEFORE the call, not recorded after.

1. Extend services/rate_limit.py rather than adding a parallel mechanism. It already has
   the fixed-window counter shape and its module docstring explains honestly why it is
   in-process and when that stops being correct. Read that docstring first — your
   addition inherits the same single-instance constraint and should say so.
2. Add a check at the ONE choke point every AI call already goes through:
   services/ai.py. AI-1 says no other module constructs a client, so this is the only
   place the check has to exist. Raise a typed error when the org is over budget.
3. Callers must degrade the way a missing API key already degrades (AI-20 / INF-9): a
   clear message on that surface, never a 500, never a blocked startup. Find how
   AIUnavailableError is handled at each call site and follow it exactly.
4. Make the budget configurable per settings with a sane default, and exempt nothing
   silently — if a surface should be exempt, say so in a comment with the reason.

CONSTRAINTS
- Do NOT try to enforce a dollar budget. AI_MODEL_PRICING defaults to `{}` and may well
  be unset in production, which makes every cost_usd NULL — a dollar cap would silently
  never fire. Cap CALLS (and optionally tokens), which are always known. Note this
  explicitly in the code comment so the next person does not "improve" it into a dollar
  cap.
- Do not change the existing chat daily limit. It works; leave it.
- Do not change AI_MODEL_PRICING's empty default. AI-17 ("never invent a price") is
  deliberate.
- This is in-process state, so it is per-instance and multiplies by instance count.
  Say so in the docstring, exactly as rate_limit.py already does for the login throttle.

TESTS (required, backend/tests/test_ai_usage.py)
1. An org under budget makes a call normally.
2. An org over budget gets the typed error, and the AI provider is never invoked (assert
   on the fake_ai fixture's call count — QA-8: never call a real provider from a test).
3. Each affected surface degrades gracefully rather than 500ing when over budget.
4. The window rolls: an org over budget yesterday can call today.

VERIFY
cd backend && .venv/bin/python -m pytest tests/ -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .

SEPARATELY, and worth doing first because it takes five minutes: confirm whether
AI_MODEL_PRICING is actually set in the Render dashboard. If it is not, every cost figure
the platform reports is currently NULL and the AI-usage analytics page shows $0.00 with
everything counted as unpriced. That is correct behaviour, but it means there is no cost
observability at all right now.
```

---

<a id="s-9"></a>
## S-9 — Resubmission is uncapped, and each one re-runs a full marking pass

**S1 · AGENT · effort S**

`backend/app/api/submissions.py:114-140`

If a submission is not yet in `SETTLED_STATUSES`, resubmitting deletes the existing files and marks, resets status to `submitted`, and enqueues a fresh `mark_submission`. There is no counter and no throttle.

A student can resubmit 50 times before a tutor finalizes. That is 50 marking calls — each one a multi-second Gemini call over the booklet PDF, the mark scheme PDF and every answer image — and roughly 37 minutes of the single serial worker (X-4), during which nobody else's homework is marked.

This is both a cost vector and a denial-of-service against the shared job queue, reachable by any student account.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (FastAPI, Python 3.11).
Cap homework resubmissions.

THE DEFECT
backend/app/api/submissions.py:114-140 — when a submission is not yet in
SETTLED_STATUSES, resubmitting deletes the existing files and QuestionMark rows, resets
status to `submitted`, and enqueues a fresh `mark_submission` job. There is no counter
and no throttle.

Each marking job is a multi-second AI call over the booklet PDF, the mark scheme PDF and
every answer image. The job worker is strictly serial (app/workers/jobs.py:240-258), so a
student resubmitting 50 times consumes 50 AI calls and roughly 37 minutes of the ONLY
worker, during which no other student's homework is marked and no readiness recomputes.

Reachable by any authenticated student account against their own submission.

WHAT TO CHANGE
1. Add a resubmission counter to the Submission model, defaulting to 0, incremented on
   each resubmission.
2. Reject resubmission past a small ceiling (3 is reasonable — justify it in a comment)
   with a 429 and a message telling the student to ask their tutor. Read how this file
   already writes user-facing error messages and match the tone; the constitution's UX
   rules care about this.
3. Write the migration by hand as backend/alembic/versions/0022_*.py per DB-15:
   sequentially numbered, `down_revision` chained to 0021, with a working `downgrade()`
   (DB-16). Because this ALTERs an existing table, use
   `op.batch_alter_table(..., naming_convention=NAMING)` with the convention from
   0020_past_papers.py (DB-17 — SQLite rebuilds tables on ALTER and refuses unnamed
   reflected constraints). Add the column NOT NULL with a server_default of 0 — the file
   0010_user_token_version.py is the reference for that pattern in this repo.
4. Declare the column in the model too, not only in the migration (DB-12 — four existing
   indexes exist only in migrations and the test schema differs from production as a
   result; do not add a fifth divergence).

CONSTRAINTS
- Do not change SETTLED_STATUSES or the settle/finalize logic.
- A tutor must retain a way to let a student resubmit again — decide whether that is
  implicit (finalizing resets the counter) or explicit, implement one, and say which in
  the PR description. Do not leave a student permanently locked out with no path.
- Do not touch the marking service.

TESTS (required, backend/tests/test_homework.py)
1. A student can resubmit up to the cap.
2. The next resubmission returns 429 and enqueues NO new job (assert on the jobs table,
   not just the response).
3. The existing resubmission behaviour below the cap is unchanged — files replaced, marks
   cleared, job enqueued (regression).
4. Drive jobs with process_one_job(), never worker_loop() (QA-6).

VERIFY
cd backend && .venv/bin/python -m pytest tests/ -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
CI also runs an Alembic upgrade->downgrade->upgrade against real Postgres 16, so verify
your downgrade() actually works before pushing.
```

---

<a id="s-10"></a>
## S-10 — No rate limit on registration, join, or invite redemption; and an enumeration oracle

**S2 · AGENT · effort S**

`backend/app/api/auth.py` — `register_tutor` (63-88), `register_student` (207-235), `register_parent` (238-267), `join_with_invite` (270-293) attach no limiter. Only `/login` uses `login_limiter`.

Consequences:

- Unlimited account creation by an unauthenticated caller. Each **tutor** registration also creates an `Organization` row, so this inflates the tenant table too.
- The 409-on-duplicate-email response is a usable account-enumeration oracle. `/login` is defended against this with a constant-time dummy-hash comparison (`auth.py:118`); registration has no equivalent.
- Invite-code redemption is unthrottled, which weakens the 64-bit code entropy against sustained guessing far more than the entropy figure alone suggests.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (FastAPI, Python 3.11).
Add throttling to the unauthenticated account-creation endpoints.

THE DEFECT
backend/app/api/auth.py attaches `login_limiter` to /login only. These four endpoints
have no limiter at all:
  - register_tutor        (auth.py:63-88)   — also creates an Organization row
  - register_student      (auth.py:207-235)
  - register_parent       (auth.py:238-267)
  - join_with_invite      (auth.py:270-293)

Consequences: unlimited account and tenant creation by an unauthenticated caller;
the 409-on-duplicate-email response is an account-enumeration oracle (/login is
defended against this with a constant-time dummy-hash comparison at auth.py:118,
registration is not); and unthrottled invite redemption weakens the invite codes'
64 bits of entropy against sustained guessing.

WHAT TO CHANGE
1. Reuse the existing FixedWindowLimiter in backend/app/services/rate_limit.py. Read its
   module docstring first — it explains why the throttle is keyed per identifier rather
   than per IP (the API sits behind a proxy where one shared address would mean a global
   lockout, per SEC-14) and why it is in-process. Both reasons apply to your addition.
2. Apply a limiter to all four endpoints. Choose the key deliberately per endpoint and
   comment the choice: email for the register endpoints, code for join.
3. Return 429 with a message consistent with what /login already returns on throttle.

CONSTRAINTS
- Do not change the invite entropy, expiry, or single-use logic in services/invites.py.
  That code is correct — consume() resolves the double-redeem race with a conditional
  UPDATE ... WHERE used_at IS NULL and a rowcount check, which is the right pattern and
  is cited elsewhere in this audit as the reference. Leave it alone.
- Do not change /login.
- The enumeration oracle is a SEPARATE, smaller decision: closing it means registration
  stops telling an honest user their email is already registered, which is a real UX
  cost. Do NOT change that behaviour in this PR. Note it in the PR description and let
  the owner decide.
- In-process state means per-instance limits that multiply by instance count. Say so in
  the docstring, as rate_limit.py already does.

TESTS (required, backend/tests/test_auth.py)
1. Repeated registration attempts past the limit return 429.
2. A legitimate single registration still works (regression) — for all three roles.
3. Repeated invite-join attempts past the limit return 429.
4. The window rolls: blocked now, allowed after the window.

VERIFY
cd backend && .venv/bin/python -m pytest tests/test_auth.py tests/test_security_hardening.py -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

---

<a id="s-11"></a>
## S-11 — Unbounded syllabus tree recursion

**S2 · AGENT · effort S**

`backend/app/schemas/syllabus.py:13-17`, `backend/app/services/syllabus_extraction.py:21-29`, applied at `backend/app/api/syllabus_uploads.py:144-154`

`SyllabusTopicIn.children: list[SyllabusTopicIn] = []` is self-referential with no depth cap, and `apply_syllabus`'s `upsert()` recurses once per nesting level. A crafted or hallucinated draft with deep nesting raises `RecursionError` — an unhandled 500 — or creates an unbounded number of `Topic` rows in one request.

Reachable from the AI extraction path and from a tutor's manual `PUT /syllabus-uploads/{id}/draft`.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (FastAPI, Python 3.11).
Bound the syllabus topic tree.

THE DEFECT
backend/app/schemas/syllabus.py:13-17 declares a self-referential model with no depth or
size cap:
    class SyllabusTopicIn(BaseModel):
        code: str
        title: str
        weight: float = 1.0
        children: list[SyllabusTopicIn] = []

backend/app/services/syllabus_extraction.py:21-29 declares the same shape for AI output.
backend/app/api/syllabus_uploads.py:144-154's `upsert()` recurses once per nesting level.

A deeply nested draft raises RecursionError (an unhandled 500), or creates an unbounded
number of Topic rows in a single request. Reachable from AI extraction output and from a
tutor's manual PUT /syllabus-uploads/{id}/draft.

For calibration, the five seeded syllabi in backend/seed/syllabus/*.json have 17-49 topics
each and nest two or three levels — read them before choosing limits.

WHAT TO CHANGE
1. Cap nesting depth and total node count. Validate at the schema boundary (a Pydantic
   model validator on SyllabusDraft) so both the AI path and the manual-edit path are
   covered by one check.
2. Apply the identical cap to `ExtractedTopic` in services/syllabus_extraction.py so a
   hallucinated tree fails at parse time rather than at apply time.
3. Exceeding either limit returns 422 with a message naming which limit was hit. Match
   the error shape api/syllabus_uploads.py already uses.
4. Consider converting `upsert()` to an explicit stack rather than recursion. Only do
   this if it does not obscure the code — the validation cap is the actual fix, and a
   clear recursive function under a depth cap is better than an opaque iterative one.

CONSTRAINTS
- Choose limits from the real syllabi, not from round numbers. Whatever you pick, a
  comment must say why. The seeded files are the evidence.
- Do not change the extraction prompt in services/prompts.py.
- This overlaps issue S-3 (unbounded `weight` and grade-boundary `min` in the same file).
  If S-3 has not shipped, fix both in one PR — they are the same validator on the same
  models. If it has, do not revert it.

TESTS (required, backend/tests/test_syllabus_upload.py)
1. A draft nested past the depth limit returns 422 and creates no Topic rows.
2. A draft with more nodes than the count limit returns 422.
3. Each of the five real seeded syllabi still validates and applies (regression) — this
   is the test that proves the limits are not too tight.

VERIFY
cd backend && .venv/bin/python -m pytest tests/test_syllabus_upload.py -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

---

<a id="s-12"></a>
## S-12 — Client-supplied filename flows unsanitized into `Content-Disposition`

**S5 · AGENT · effort S**

`backend/app/services/storage.py:100-123,146-149` stores `file.filename` verbatim as the display name — only the on-disk *path* is server-generated. Six download endpoints then pass it to `FileResponse(..., filename=file.name)`: `submissions.py:493`, `past_papers.py:231-235,246-250`, `resources.py:116-120`, `classifieds.py:92-96`.

Starlette quotes and escapes this when building the header, which is why this is S5 rather than higher. But it is the one place in a codebase that is otherwise consistently suspicious of user input (magic-byte validation, server-generated paths, explicit prompt-injection guardrails) where a fully attacker-controlled string reaches an HTTP response header with no server-side normalization, and nothing tests that the framework's escaping holds.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (FastAPI, Python 3.11).
Normalize client-supplied filenames before they reach a response header.

THE DEFECT
backend/app/services/storage.py stores the client's original filename verbatim as the
display name (only the on-disk path is server-generated, via secrets.token_hex(16) at
storage.py:146-149). Six download endpoints pass it straight to Starlette:
  api/submissions.py:493, api/past_papers.py:231-235, api/past_papers.py:246-250,
  api/resources.py:116-120, api/classifieds.py:92-96
each as `FileResponse(..., filename=file.name)`, which builds a Content-Disposition
header from it.

Starlette does escape this, so this is defence in depth rather than a live exploit. But
it is the one place in this codebase where a fully user-controlled string reaches a
response header with no server-side normalization, and nothing tests that the escaping
holds.

WHAT TO CHANGE
In backend/app/services/storage.py, normalize the filename once, at the point it is
captured, so every one of the six call sites inherits the fix:
- strip control characters, CR, LF, and quote characters
- collapse path separators (a filename is not a path)
- cap the length to something sane
- fall back to a generic name if nothing usable remains

Do it in `_write` or immediately before it, where both `save_upload` and `save_bytes`
converge, so the Google Drive attachment path is covered by the same code.

CONSTRAINTS
- Keep filenames human-readable. Students and tutors recognize their own files by name;
  do not sanitize them into opaque strings. Unicode is fine and should be preserved —
  strip control and structural characters, not international text.
- Do not change the on-disk path generation. It is already correct.
- Do not change the six call sites. The fix belongs in one place.

TESTS (required, backend/tests/ — new test_storage.py is fine)
1. A filename containing CR/LF is normalized before storage.
2. A filename containing quotes and path separators is normalized.
3. A normal filename with spaces and unicode survives unchanged.
4. An empty or fully-stripped filename gets the generic fallback.

VERIFY
cd backend && .venv/bin/python -m pytest tests/ -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

---

<a id="s-13"></a>
## S-13 — No account deletion or data-erasure path anywhere

**S5 · VERIFIED · compliance · effort L**

Every `@router.delete` in `backend/app/api/` was enumerated. None deletes a `User`, purges a student's uploaded files, or removes PII. `groups.py:132` removes group *membership* only, leaving submissions, files, notes and CRM data intact. There is no `DELETE /students/{id}`, no `DELETE /auth/me`, no data-export endpoint, and no retention or expiry job in `workers/jobs.py`.

The platform stores minors' handwritten homework, contact details for students and parents, AI-generated assessments of children, and Google OAuth-linked data. Under UK-GDPR the right to erasure and the right to data portability both apply, and the data subjects here are children — which raises rather than lowers the bar.

This is not a vulnerability. It is a gap that a safeguarding or data-protection review will find, and it interacts directly with D-4: there are no `ondelete=` rules on 109 foreign keys, so building erasure on top of the current schema means deciding the cascade behaviour of every one of them first.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (FastAPI + SQLAlchemy 2 async
+ Postgres). This is a DESIGN task, not a code task. Produce a plan; do not implement it.

THE GAP
There is no account-deletion, data-erasure, or data-export path anywhere in the product.
Verified: every @router.delete in backend/app/api/ was enumerated — none deletes a User
row, purges uploaded files, or removes PII. api/groups.py:132 removes group MEMBERSHIP
only, leaving submissions, files, tutor notes and CRM data intact. There is no retention
or expiry job in app/workers/jobs.py.

The platform stores minors' handwritten homework, student and parent contact details,
AI-generated assessments of children, and Google OAuth tokens. UK-GDPR rights to erasure
and portability apply, and the data subjects are children.

WHAT TO PRODUCE
A written plan at docs/volume-3-platform-engineering/ (follow the existing volume's
document conventions — read one first) covering:

1. DATA INVENTORY. Every table holding personal data, what it holds, and for whom. Start
   from backend/app/models/ (52 tables) and be exhaustive. Mark each as: erase, retain
   anonymized, or retain intact with justification.

2. THE HARD CASES, each with a recommendation and its reasoning:
   - mark_override_audit is append-only BY DESIGN (models/homework.py:252-256) and is the
     tutor-authority audit trail. Does erasure empty it, anonymize it, or leave it?
   - evidence and factor_evaluations feed readiness for a whole class. Deleting one
     student's rows is fine; what about a tutor requesting erasure?
   - Submissions contain a student's handwriting — biometric-adjacent, arguably.
   - Google OAuth tokens must be REVOKED at Google, not merely deleted locally.
   - Uploaded files live on a Render disk (render.yaml:34-37) with no backup or
     reconciliation, so "deleted from the database" and "deleted from disk" are different
     claims. Which does the plan promise?

3. THE SCHEMA PREREQUISITE. There is currently no `ondelete=` on ANY of the 109 foreign
   keys (verified: zero matches across all 21 migrations). Erasure cannot be built until
   each one is decided. Note that this is separately tracked as issue D-4 and that D-4
   must land first. Your plan should say which FKs need RESTRICT (audit trails) and which
   need CASCADE.

4. RETENTION. How long does an inactive student's data live? There is no answer today.

5. EXPORT. Portability requires a machine-readable export of one student's record. Sketch
   the shape; note that services/student_crm.py already aggregates most of it.

CONSTRAINTS
- Write NO code and NO migration. This is a decision document.
- Do not invent a legal position. Where a decision needs the product owner or a DPO, say
  so explicitly and state the options with their tradeoffs rather than picking one.
- Follow docs/governance/change-process.md for how a new constitution document is
  proposed, and docs/governance/documentation-authority.md for the rule format.
- Cross-reference docs/governance/risk-register.md — this probably belongs there as a
  standing risk as well as a plan.
```

---

<a id="s-14"></a>
## S-14 — `admin` is a global cross-tenant superuser with no read audit trail

**S5 · AGENT · ↔ AV-8 · effort M**

Every ownership helper across the routers — `groups.py:39-44`, `lessons.py:35-51`, `submissions.py:60-72`, `past_papers.py:82-85`, `knowledge.py:22-27`, `syllabus_uploads.py:15-20` — bypasses the organization check with `... and user.role != UserRole.admin`. `deps.py:70` also makes `admin` count as a tutor everywhere a tutor is required.

**What is new since AV-8.** Two things narrow and sharpen it:

1. **No API path ever assigns the role.** `grep -rn "role=UserRole.admin" backend/app` returns nothing — it can only be set by direct database access. So this is not attacker-reachable through the product, which downgrades AV-8's severity considerably.
2. **Mark overrides are audited; reads are not.** `MarkOverrideAudit` gives an append-only trail for admin *writes*. There is no equivalent for an admin *reading* every organization's students, uploads, notes and grades. For a platform holding minors' data, unlogged cross-tenant read access is the part a safeguarding review will care about.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (FastAPI, Python 3.11).
Add an audit trail for cross-organization admin access.

CURRENT STATE (verified — confirm before changing)
Every ownership helper bypasses the org check for admins:
  api/groups.py:39-44, api/lessons.py:35-51, api/submissions.py:60-72,
  api/past_papers.py:82-85, api/knowledge.py:22-27, api/syllabus_uploads.py:15-20
each ending `... and user.role != UserRole.admin`. api/deps.py:70 makes admin count as a
tutor everywhere a tutor is required.

Two mitigating facts, both verified: no API endpoint ever assigns UserRole.admin (it can
only be set by direct DB access, so it is not attacker-reachable through the product),
and mark overrides are already append-only audited via MarkOverrideAudit.

The gap: there is NO audit trail for an admin READING another organization's student PII,
uploads, notes or grades.

WHAT TO CHANGE
1. Record cross-org admin access. When a request resolves through one of the admin
   bypasses above and the target row's organization_id differs from the caller's, write
   an append-only audit row: who, when, which endpoint, which organization, which
   resource id.
2. Put the write in ONE place. Those six helpers are the choke point; a seventh helper
   added later must not be able to skip it. Prefer changing the shared bypass into a
   single function all six call over editing six sites — this is the same convergence
   the codebase already did for the role check (BE-17 / SEC-11 / RISK-7), and the same
   reasoning applies: a check somebody has to remember to write is a check that will be
   forgotten.
3. New table, hand-written migration as backend/alembic/versions/0022_*.py per DB-15,
   with a working downgrade() (DB-16). Append-only, no update or delete API, mirroring
   how MarkOverrideAudit is modelled (models/homework.py:252-256) — read it first.
4. Declare any index in the model as well as the migration (DB-12).

CONSTRAINTS
- Do NOT change what admins can do. This is observability, not a permissions change.
  Removing the bypass would be a much larger decision and is not this task.
- Do not log the CONTENT that was read — only that it was read, by whom, and which
  resource. An audit table that duplicates student PII makes the problem worse.
- Audit writing must not be able to fail the request it is auditing in a way that loses
  the audit silently. Decide deliberately whether a failed audit write fails the request
  or is logged, and comment the choice.

TESTS (required, backend/tests/test_authorization.py)
1. An admin reading another org's resource writes exactly one audit row with the right
   fields.
2. An admin reading their OWN org's resource writes none.
3. A normal tutor reading their own org's resource writes none.
4. The audit table has no update or delete route (assert by walking the mounted routes,
   the way test_authorization.py already walks them).

VERIFY
cd backend && .venv/bin/python -m pytest tests/ -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .

Then update docs/governance/risk-register.md — RISK entry for the admin role should
record the mitigation, and docs/volume-3-platform-engineering/07-security-architecture.md
per GOV-1.
```

---
# Data integrity and loss

<a id="d-1"></a>
## D-1 — A tutor's typed marks and feedback are silently discarded on window refocus

**S0 · VERIFIED · grading integrity · effort S**

`frontend/src/tutor/SubmissionReviewPage.tsx:48-60` and `frontend/src/main.tsx:9`

```tsx
useEffect(() => {
  if (submission.data) {
    const next: Record<number, Draft> = {};
    for (const m of submission.data.marks) {
      next[m.question_id] = {
        final_marks: m.final_marks ?? m.ai_marks,
        final_feedback: m.final_feedback ?? m.ai_feedback ?? "",
      };
    }
    setDrafts(next);
  }
}, [submission.data]);
```

There is no dirty guard. Its sibling page gets this right — `AssignmentDetailPage.tsx:59` reads `if (assignment.data && !dirty)`.

And `main.tsx:9` is `new QueryClient()` with no `defaultOptions`, so TanStack Query's defaults apply: `staleTime: 0`, `refetchOnWindowFocus: true`.

**Failure scenario.** A tutor opens a submission with eight questions and types feedback into question 3. They alt-tab to check a message — an entirely ordinary action. On refocus, the query refetches, `submission.data` gets a new object reference regardless of whether the content changed, the effect fires unconditionally, and `setDrafts(next)` overwrites every draft with the last-saved server state. The typed feedback is gone with no warning and no undo.

For a product whose central promise is that the tutor has final authority over everything the AI produces, silently discarding the tutor's exercise of that authority is the worst available outcome.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (React 18 + TypeScript + Vite +
TanStack Query). Fix a data-loss defect in the tutor's marking screen.

THE DEFECT
frontend/src/tutor/SubmissionReviewPage.tsx:48-60 re-seeds the tutor's editable marks and
feedback from server state on every change of `submission.data`, with NO dirty guard:

    useEffect(() => {
      if (submission.data) {
        const next: Record<number, Draft> = {};
        for (const m of submission.data.marks) {
          next[m.question_id] = {
            final_marks: m.final_marks ?? m.ai_marks,
            final_feedback: m.final_feedback ?? m.ai_feedback ?? "",
          };
        }
        setDrafts(next);
      }
    }, [submission.data]);

frontend/src/main.tsx:9 constructs `new QueryClient()` with no defaultOptions, so
TanStack Query's defaults apply: staleTime 0 and refetchOnWindowFocus true.

Consequence: a tutor types feedback, alt-tabs to another window, comes back — the query
refetches, `submission.data` gets a new object reference, the effect fires, and every
typed mark and every typed feedback string is replaced by the last-saved server state.
Silent, no warning, no undo.

The sibling page frontend/src/tutor/AssignmentDetailPage.tsx:59 already solves exactly
this with `if (assignment.data && !dirty)`. That is the pattern to copy.

WHAT TO CHANGE
In frontend/src/tutor/SubmissionReviewPage.tsx:
1. Track dirty state and do not re-seed a field the tutor has touched. Prefer per-question
   granularity over a single page-wide boolean if it is not much more code — a tutor who
   has edited question 3 should still receive fresh server data for questions 1 and 2.
   If per-question turns out to be genuinely messy, a page-wide `dirty` flag matching
   AssignmentDetailPage is acceptable; say which you chose and why in the PR.
2. Clear dirty state after a successful save, so the next refetch seeds normally.

Consider ALSO setting a sensible `staleTime` in the QueryClient defaults at main.tsx:9 —
but treat that as a separate concern (it is issue X-11) and do not let it substitute for
the dirty guard. The guard is the fix; staleTime only narrows the window.

CONSTRAINTS
- Do not change frontend/src/tutor/AssignmentDetailPage.tsx. It is already correct and is
  the reference.
- Do not switch this page to uncontrolled inputs or a form library. The change should be
  small and reviewable — this is a grades screen.
- Do not change any backend code.
- Server data must still live in TanStack Query, not be copied wholesale into useState as
  the source of truth (FE-6). The `drafts` state is the tutor's in-progress EDIT, which is
  legitimately local; keep that distinction intact.

TESTS (required, frontend/src/test/ — there is an existing suite using Vitest + React
Testing Library; follow its conventions)
1. Render the page, type into a feedback field, trigger a refetch of the submission query
   with identical server data, and assert the typed text is still there.
2. Same, but with CHANGED server data — assert the typed text is still there (the tutor's
   in-progress edit wins over a background refetch).
3. After a successful save, a refetch DOES re-seed from the server (regression — the
   guard must not permanently freeze the page).
4. Untouched fields still receive fresh server data, if you implemented per-question
   granularity.

VERIFY
cd frontend && npm test
cd frontend && npm run build     # tsc -b && vite build — the only type check anywhere
cd frontend && npm run lint
```

---

<a id="d-2"></a>
## D-2 — `DELETE /groups/{id}` raises a raw 500 for any group with real history

**S0 · VERIFIED · effort M**

`backend/app/api/groups.py:116-120`

```python
@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(group_id: int, db: DbSession, user: CurrentUser) -> None:
    group = await _owned_group(db, user, group_id)
    await db.delete(group)
    await db.commit()
```

`Group` (`models/groups.py:31-36`) declares ORM cascade for exactly two relationships — `members` and `schedule_slots`. Five other tables carry a `group_id` foreign key with no ORM relationship and no database `ondelete=`:

| Table | Column | Declared at |
|---|---|---|
| `assignments` | `group_id` | `models/homework.py:53` |
| `lessons` | `group_id` | `models/lessons.py:19` |
| `invites` | `group_id` | `models/groups.py:65` |
| `group_resources` | `group_id` | `models/resources.py:21` |
| `classroom_course_links` | `group_id` | `models/classroom.py:44` |

**Verified: zero `ondelete=` clauses across all 21 migrations.** Every FK therefore defaults to Postgres `NO ACTION`.

So deleting any group that has ever had a lesson taught, homework assigned, a resource shared, or an invite minted raises `ForeignKeyViolationError` inside `commit()`, which nothing catches and which surfaces as a raw 500. In practice the endpoint is broken for essentially every real group — a group with zero lessons and zero assignments only exists in the moments after creation.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (FastAPI + SQLAlchemy 2 async
+ Postgres + Alembic). Fix a broken delete endpoint.

THE DEFECT
backend/app/api/groups.py:116-120:

    @router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_group(group_id: int, db: DbSession, user: CurrentUser) -> None:
        group = await _owned_group(db, user, group_id)
        await db.delete(group)
        await db.commit()

The Group model (backend/app/models/groups.py:31-36) ORM-cascades only `members` and
`schedule_slots`. Five other tables FK to groups.id with no ORM relationship and no
database ondelete=:
    assignments.group_id             models/homework.py:53
    lessons.group_id                 models/lessons.py:19
    invites.group_id                 models/groups.py:65
    group_resources.group_id         models/resources.py:21
    classroom_course_links.group_id  models/classroom.py:44

Verified: there are ZERO `ondelete=` clauses across all 21 migrations, so every FK is
Postgres NO ACTION. Deleting any group that has ever had a lesson, homework, a resource or
an invite raises ForeignKeyViolationError inside commit(), uncaught, surfacing as a 500.
The endpoint is effectively broken for every real group.

DECIDE FIRST, THEN IMPLEMENT
Two legitimate designs. Pick ONE, state the choice and its reasoning in the PR
description, and do not half-implement both.

  Option A — refuse to delete a group with history. Matches the repo's DB-8 stance that
  history is append-only and there are no soft deletes. Return 409 with a message telling
  the tutor what to remove first. Simplest, safest, and probably right for a product
  where a group's homework and lessons ARE the academic record.

  Option B — hard delete with explicit ondelete= on every one of the five FKs: RESTRICT
  where the history must survive (assignments, lessons), CASCADE where the data is pure
  convenience (invites, group_resources, classroom_course_links). More work, and it
  requires deciding what deleting a group means for a student's submitted homework — which
  is a product question, not a technical one.

Option A is recommended unless the owner specifically wants hard delete.

IMPLEMENTATION NOTES
- If Option A: use EXISTS checks, not COUNT(*) over five tables. Match the query style
  already in services/groups.py — `summaries()` at services/groups.py:68-108 is the
  reference implementation for efficient group-scoped aggregate queries in this codebase.
- If Option B: hand-write backend/alembic/versions/0022_*.py per DB-15 (sequential
  number, down_revision chained to 0021, working downgrade() per DB-16). Use
  `op.batch_alter_table(..., naming_convention=NAMING)` with the convention from
  0020_past_papers.py and name new ForeignKeys explicitly (DB-17). Set the same ondelete=
  on the MODEL as well as in the migration — DB-12 exists because four indexes already
  live only in migrations and the test schema diverges from production as a result.

CONSTRAINTS
- Do not change `_owned_group` or the authorization path.
- Do not add a soft-delete flag. DB-8 says no soft deletes; changing that needs an ADR,
  not a PR.
- Whatever you choose, the endpoint must never again return a raw 500 for a foreseeable
  input.

TESTS (required, backend/tests/test_groups.py)
1. Deleting a brand-new group with no history still succeeds (regression).
2. Deleting a group WITH an assignment behaves as your chosen option specifies —
   409 for A, or correct cascade/restrict for B. Never a 500.
3. Same for a group with a lesson, and for a group with an invite.
4. IMPORTANT — read this before trusting a green suite: tests run on SQLite, which does
   NOT enforce foreign keys (backend/app/db.py never issues `PRAGMA foreign_keys = ON`).
   Under Option B a passing test proves nothing about the real cascade behaviour. If you
   take Option B, you MUST also enable the pragma for the SQLite test engine, or the test
   is theatre. That is separately tracked as issue D-13; fixing it here is in scope and
   welcome.

VERIFY
cd backend && .venv/bin/python -m pytest tests/test_groups.py -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
CI runs Alembic upgrade->downgrade->upgrade on real Postgres 16 — if you wrote a
migration, that is the gate that actually tests it.
```

---

<a id="d-3"></a>
## D-3 — The syllabus editor PUTs the whole tree on every keystroke, losing updates

**S1 · AGENT · effort M**

`frontend/src/tutor/SyllabusUploadPage.tsx:150-156,251,262,276`

```tsx
function setTopicField(path: number[], patch: Partial<SyllabusTopicDraft>) {
  if (!upload!.draft) return;
  saveDraft.mutate({
    ...upload!.draft,
    topics: updateAtPath(upload!.draft.topics, path, patch),
  });
}
...
<input value={node.title} onChange={(e) => setTopicField(path, { title: e.target.value })} />
```

The input's `value` is bound directly to server state, and every `onChange` immediately PUTs the entire draft tree.

**Failure scenario.** A tutor types a multi-word topic title. Each character fires a full-document PUT. Because `upload.draft` in the render closure does not update until the mutation's `onSuccess` → `invalidateQueries` → refetch round-trip completes, several keystrokes typed before the first round-trip returns each build their payload from the *same stale base* and carry only their own one-character delta. Whichever response resolves last wins; the rest are discarded. The input also visibly "un-types" between round-trips.

Two defects in one: lost writes, and one full-document write per character typed across a syllabus with dozens of topics.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (React 18 + TypeScript +
TanStack Query). Fix a lost-update defect in the syllabus draft editor.

THE DEFECT
frontend/src/tutor/SyllabusUploadPage.tsx:150-156 and its inputs at :251, :262, :276:

    function setTopicField(path: number[], patch: Partial<SyllabusTopicDraft>) {
      if (!upload!.draft) return;
      saveDraft.mutate({
        ...upload!.draft,
        topics: updateAtPath(upload!.draft.topics, path, patch),
      });
    }
    <input value={node.title} onChange={(e) => setTopicField(path, { title: e.target.value })} />

The input value is bound directly to SERVER state, and every onChange immediately PUTs
the ENTIRE draft tree. `upload.draft` in the render closure does not refresh until
onSuccess -> invalidateQueries -> refetch completes, so keystrokes typed inside one
round-trip each build a payload from the same stale base carrying only their own
one-character delta. Last response to resolve wins; the others are silently lost. The
field also visibly un-types between round-trips.

Two problems: lost writes, and one full-document write per character.

WHAT TO CHANGE
1. Buffer edits in local component state so the input is driven by what the tutor typed,
   not by the last server round-trip.
2. Debounce or save-on-blur instead of saving per keystroke. Save-on-blur is simpler and
   more predictable for a tree editor; debounce is acceptable if you handle the unmount
   and navigate-away cases so a pending edit is not dropped.
3. Keep local edits authoritative while the field is focused — a refetch must not clobber
   an in-progress edit. This is the same class of bug as issue D-1 on the marking screen;
   if D-1 has already shipped, reuse whatever pattern it established rather than inventing
   a second one.
4. Show save state honestly. A tutor needs to know their edit persisted. Read how this
   page already surfaces mutation state and extend it rather than adding a new mechanism.

CONSTRAINTS
- Do not change the backend endpoint or its payload shape. PUT /syllabus-uploads/{id}/draft
  taking the whole draft is fine; the defect is the frequency and the stale base, not the
  contract.
- Do not switch the page to a form library. Keep the change reviewable.
- Server data still lives in TanStack Query (FE-6); the local buffer is the in-progress
  edit, which is legitimately local. Preserve that distinction.
- Note issue S-3 adds bounds validation to `weight` and grade-boundary `min` on the
  backend for this exact editor. If S-3 has shipped, make sure a 422 from it renders as a
  useful message here rather than a silent failed save.

TESTS (required, frontend/src/test/)
1. Typing a multi-character title results in ONE save, not one per character.
2. The typed value is preserved across a background refetch of the upload query.
3. A save failure surfaces visibly and does not silently discard the tutor's text.
4. Editing two different topics in sequence persists both — this is the regression that
   proves the stale-base bug is gone.

VERIFY
cd frontend && npm test
cd frontend && npm run build
cd frontend && npm run lint
```

---

<a id="d-4"></a>
## D-4 — Zero `ondelete=` on 109 foreign keys; zero `CheckConstraint` anywhere

**S1 · VERIFIED · ↔ AV-15, AV-16 · effort M**

Two counts, both verified directly:

- `grep -c ondelete backend/alembic/versions/*.py` → **0 in all 21 migrations.** Every one of the 109 foreign keys is Postgres `NO ACTION`.
- `grep -rn "CheckConstraint" backend/app/models/ backend/alembic/versions/` → **0 matches.**

The second is the more interesting one. `Submission` (`models/homework.py:135-148`) must have exactly one of `assignment_id` / `past_paper_id`; `QuestionMark` (`models/homework.py:207-217`) exactly one of `question_id` / `past_paper_question_id`. This invariant is load-bearing — `api/submissions.py:53-72`'s `_tutor_owns` branches on it inside an *authorization check*, and `CLAUDE.md`'s `API-20` rule exists entirely because reading `assignment_id` unconditionally raises there.

The unique constraints do nothing to help: `UniqueConstraint("assignment_id", "student_id")` only dedupes within whichever branch is populated. A row with both set, or neither, is currently legal at the database level.

Also found while checking this: `past_paper_attempts` has **no unique constraint** on `(past_paper_id, student_id)` despite `marking.py:381-387` treating it as a one-row-per-pair upsert — see D-5.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (SQLAlchemy 2 async + Postgres
+ Alembic). Add the database constraints that currently exist only as convention.

VERIFIED CURRENT STATE
- Zero `ondelete=` clauses across all 21 migrations. All 109 FKs are Postgres NO ACTION.
- Zero CheckConstraint declarations anywhere in models or migrations.

SCOPE OF THIS TASK — the polymorphic invariants only. Do NOT attempt all 109 FKs in one
PR; that is a design exercise (see issue S-13's data inventory) and a separate decision
per FK.

THE INVARIANTS TO ENFORCE
1. `submissions` must have exactly one of (assignment_id, past_paper_id).
   Model: backend/app/models/homework.py:135-148
2. `question_marks` must have exactly one of (question_id, past_paper_question_id).
   Model: backend/app/models/homework.py:207-217

Both are load-bearing today: api/submissions.py:53-72 (`_tutor_owns`) branches on the
Submission one INSIDE an authorization check, which is why CLAUDE.md's API-20 rule exists.
The existing UniqueConstraints do not help — they only dedupe within a populated branch, so
a row with both columns set, or neither, is currently legal.

WHAT TO CHANGE
1. Add CheckConstraint to both models, in __table_args__ alongside the existing
   UniqueConstraints:

     CheckConstraint(
       "(assignment_id IS NOT NULL AND past_paper_id IS NULL) OR "
       "(assignment_id IS NULL AND past_paper_id IS NOT NULL)",
       name="ck_submissions_exactly_one_parent",
     )

   and the equivalent for question_marks.
2. Hand-write backend/alembic/versions/0022_*.py per DB-15: sequential number,
   down_revision chained to 0021, working downgrade() (DB-16). Use
   `op.batch_alter_table(..., naming_convention=NAMING)` with the convention from
   0020_past_papers.py (DB-17).
3. BEFORE adding the constraint, check for existing violating rows and handle them. A
   CHECK constraint on a table with violating data fails the migration — which is correct
   (it means the invariant was already broken in production) but must be a deliberate,
   informative failure rather than a mystery. Add a guard query that raises a clear
   message naming the offending ids.
4. Name the constraints explicitly. DB-17 exists because SQLite refuses unnamed reflected
   constraints on ALTER.

CONSTRAINTS
- Do not change the application-level branching in _tutor_owns or marking.py. The
  constraint is defence in depth; the code that already respects the invariant stays.
- Do not add ondelete= to anything in this PR. That is a per-FK decision and belongs with
  the erasure design work (issue S-13) and the group-delete fix (issue D-2).
- Do not use a partial unique index instead of a CHECK. The invariant is "exactly one of
  two columns is non-null", which is what CHECK expresses.

TESTS (required, backend/tests/)
1. Inserting a Submission with BOTH assignment_id and past_paper_id is rejected.
2. Inserting a Submission with NEITHER is rejected.
3. Both legitimate shapes still insert (regression) — homework and past paper.
4. Same four for QuestionMark.
5. READ THIS BEFORE TRUSTING A GREEN RUN: tests run on SQLite. SQLite DOES enforce CHECK
   constraints (unlike foreign keys, which it ignores because backend/app/db.py never
   issues `PRAGMA foreign_keys = ON`), so these tests are meaningful. But confirm that
   yourself rather than assuming — the same suite would pass vacuously for an ondelete=
   change, which is issue D-13.

VERIFY
cd backend && .venv/bin/python -m pytest tests/ -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
CI's Alembic upgrade->downgrade->upgrade against Postgres 16 is the real gate here.

Then update docs/volume-2-application-engineering/06-database-design.md — it currently
records this as a Known Gap (DB-14). Close the gap entry rather than leaving it stale
(GOV-1, GOV-3).
```

---

<a id="d-5"></a>
## D-5 — `past_paper_attempts` has no unique constraint and a read-modify-write race

**S1 · AGENT · effort S**

`backend/app/services/marking.py:360-403` — `_upsert_attempt_rollup` reads a `PastPaperAttempt` by `(past_paper_id, student_id)` and inserts if absent, updates if present. No row lock, and no unique constraint to fall back on.

Two jobs settling the same submission's rollup in quick succession — the auto-finalize path in `mark_submission` racing a tutor's manual `finalize_submission` — can both see no existing row and both `INSERT`, producing two attempt rows for one (paper, student). The Past Paper Performance factor then double-counts, silently, producing exactly the kind of unexplainable number `PROD-1` exists to prevent.

The codebase already contains the correct pattern for this class of problem: `consume()` in `services/invites.py:84-109` resolves the double-redeem race with a conditional `UPDATE ... WHERE used_at IS NULL` and a rowcount check.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (SQLAlchemy 2 async + Postgres
+ Alembic). Fix a read-modify-write race that can double-count a past-paper attempt.

THE DEFECT
backend/app/services/marking.py:360-403 (`_upsert_attempt_rollup`) reads a
PastPaperAttempt by (past_paper_id, student_id), then INSERTs if absent or UPDATEs if
present. There is no row lock and — verified — no unique constraint on
past_paper_attempts(past_paper_id, student_id) to fall back on.

Two jobs settling the same submission's rollup in quick succession (the auto-finalize path
in mark_submission racing a tutor's manual finalize_submission) can both observe no
existing row and both INSERT. The result is two attempt rows for one (paper, student),
which the Past Paper Performance readiness factor then double-counts — silently, and with
an evidence chain that looks intact.

WHAT TO CHANGE
1. Add a unique constraint on past_paper_attempts(past_paper_id, student_id), in the model
   AND in a hand-written migration backend/alembic/versions/0022_*.py (DB-15, DB-16,
   DB-17 — see the conventions in 0020_past_papers.py).
2. BEFORE adding it, handle any existing duplicate rows. Duplicates would fail the
   migration, which is correct but must be an informative failure. Decide deliberately
   whether to deduplicate (keeping which row?) or to fail loudly and let a human look —
   for a grading system, failing loudly is usually right. State your choice in the PR.
3. Make the upsert atomic. Use Postgres `INSERT ... ON CONFLICT DO UPDATE`
   (sqlalchemy.dialects.postgresql.insert) keyed on the new constraint.
4. IMPORTANT PORTABILITY PROBLEM: the test suite runs on SQLite, and pg_insert is
   Postgres-only. SQLite has its own on-conflict support with a different import. Decide
   how to handle this and say which you chose:
     (a) dialect-aware branch in the service — explicit, slightly ugly, testable on both;
     (b) keep the read-then-write but wrap it in try/except IntegrityError with a re-read
         on conflict — portable, correct under the new constraint, and closer to the
         existing code.
   Option (b) is recommended: the constraint is what actually makes it safe, and the
   retry is portable. Do not pick (a) and then leave the SQLite path untested.

REFERENCE PATTERN
backend/app/services/invites.py:84-109 (`consume()`) already solves the equivalent
double-redeem race correctly, with a conditional UPDATE and a rowcount check. Read it
before writing your fix — it is the house style for this problem.

CONSTRAINTS
- Do not change how the rollup's values are computed. Only how the row is written.
- Do not change the readiness factor that reads these rows.
- Job handlers must remain safe to re-run on the same payload (BE-6 / BE-7 — delivery is
  at-least-once and the worker retries once). Your fix must preserve that: running the
  same rollup twice must produce one row with the correct values, not an error.

TESTS (required, backend/tests/test_past_papers.py)
1. Two sequential rollups for the same (paper, student) leave exactly ONE row with the
   later values — this is the idempotency BE-6 requires.
2. The unique constraint rejects a second manual insert.
3. Normal single-attempt flow is unchanged (regression).
4. Two DIFFERENT students on the same paper still get one row each.

VERIFY
cd backend && .venv/bin/python -m pytest tests/test_past_papers.py tests/test_readiness_v2.py -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
CI's Alembic round-trip on Postgres 16 is the real gate for the migration.
```

---

<a id="d-6"></a>
## D-6 — A marking failure commits half-finalized marks alongside `ai_failed`

**S1 · AGENT · grading integrity · effort M**

`backend/app/services/marking.py:71-85`

```python
try:
    await _run_marking(session, submission)
    submission.ai_error = None
except Exception as exc:
    submission.status = SubmissionStatus.ai_failed
    submission.ai_error = str(exc) or exc.__class__.__name__
    await session.commit()
    raise
```

`_run_marking` mutates and `session.add()`s `QuestionMark` rows across a loop (`marking.py:267-311`), setting `final_marks` and `auto_finalized=True` for scheme-backed confident questions, *before* calling `_settle_submission` (`:312`), which does further awaited work — `build_homework_evidence`, `enqueue(...)`, `enqueue_readiness_v2_debounced(...)`.

If any of those later awaits raises — a transient database error is enough — the `except` block's `session.commit()` flushes **everything pending in the session**, including the marks already set to final, together with the `ai_failed` status.

The submission is then left reporting `ai_failed` while some of its `QuestionMark` rows carry a final, auto-finalized mark that was never turned into readiness `Evidence`. It self-heals only if a tutor happens to notice it in the attention queue and manually finalizes, which re-runs `record_marks_as_evidence` for the whole submission. Until then the database is inconsistent and nothing says so.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (FastAPI + SQLAlchemy 2 async).
Fix a partial-commit defect in the marking failure path.

THE DEFECT
backend/app/services/marking.py:71-85:

    try:
        await _run_marking(session, submission)
        submission.ai_error = None
    except Exception as exc:
        submission.status = SubmissionStatus.ai_failed
        submission.ai_error = str(exc) or exc.__class__.__name__
        await session.commit()
        raise

`_run_marking` mutates and session.add()s QuestionMark rows in a loop (marking.py:267-311),
setting final_marks and auto_finalized=True for scheme-backed confident questions, BEFORE
calling `_settle_submission` (marking.py:312) which does further awaited DB work
(build_homework_evidence, enqueue, enqueue_readiness_v2_debounced).

If any of those later awaits raises, the except block's session.commit() flushes
EVERYTHING pending — including marks already set to final — together with the ai_failed
status. The submission reports ai_failed while carrying auto-finalized marks that were
never turned into readiness Evidence. It only self-heals if a tutor notices it in the
attention queue and manually finalizes.

WHAT TO CHANGE
Separate "record the failure" from "whatever partial work happened to be pending". The
failure marker must be the ONLY thing that commits on the failure path.

Roll back the in-progress unit of work before writing the failure state, then commit only
that. `await session.rollback()` before setting status and ai_error, then re-fetch the
submission (the rollback expires it) and commit the failure marker alone. A SAVEPOINT
around the mark-mutation section is an alternative; pick whichever is clearer in this
file's existing style and say why in the PR.

Then confirm the invariant holds: after a failed marking run, no QuestionMark for that
submission carries final_marks/auto_finalized from the failed attempt.

CONSTRAINTS
- Job handlers must stay safe to re-run on the same payload (BE-6/BE-7). The worker
  retries once after a 60s backoff. Verify your change keeps mark_submission idempotent —
  specifically that it still "updates existing QuestionMark drafts in place, never
  overwrites a tutor-finalized mark, and skips the AI call entirely when every question is
  already decided", which CLAUDE.md states as the current contract.
- Do NOT swallow the exception. The `raise` at the end is what drives the retry and
  eventually the give-up log; keep it.
- Do not change the auto-finalize criteria (AI-11/AI-12/ADR-0009 — a mark auto-finalizes
  only if scheme-backed AND high/medium confidence). Out of scope.
- Do not change _settle_submission's ordering to "fix" this by doing less work. The fix is
  transactional hygiene, not reordering.

TESTS (required, backend/tests/test_auto_marking.py)
1. Marking succeeds normally end to end (regression) — marks final, evidence written.
2. Inject a failure in the _settle_submission phase (monkeypatch build_homework_evidence
   or the enqueue to raise). Assert: submission.status == ai_failed, ai_error is set, and
   NO QuestionMark for that submission has auto_finalized=True or a final_marks from the
   failed run.
3. Re-running the same job after a failure produces correct final state (idempotency,
   BE-6). Drive it with process_one_job(), never worker_loop() (QA-6).
4. Use the fake_ai fixture and patch the CALLING module's structured_complete (QA-7).
   Never call a real provider (QA-8).

VERIFY
cd backend && .venv/bin/python -m pytest tests/test_auto_marking.py tests/test_homework.py tests/test_jobs.py -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

---

<a id="d-7"></a>
## D-7 — No per-job timeout: one hung job stalls the pipeline for every tenant

**S1 · AGENT · effort S**

`backend/app/workers/jobs.py:43,201-208`

```python
JOB_STALL_SECONDS = 900.0   # comment: "it is stuck — and a stuck job blocks the queue behind it"
...
async with async_session() as session:
    await handler(session, payload)   # no asyncio.wait_for
    await session.commit()
```

`JOB_STALL_SECONDS` is used only by `worker_status()` for health-check *reporting*. Nothing cancels or reschedules a hung job. The worker processes one job at a time (`jobs.py:240-258`).

`main.py:79-89` carefully supervises the case where the worker *loop* dies — that is RISK-4, and it is well handled. The uncovered case is a single job that merely hangs: an AI HTTP call with no application-level timeout, or the Classroom sync's serial round-trips (D-8). Marking, extraction, readiness synthesis, report generation and Classroom sync for every tutor's every student stop until it returns or the process restarts.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (FastAPI, Python 3.11, asyncio).
Add a per-job timeout to the background worker.

THE DEFECT
backend/app/workers/jobs.py:201-208:

    async with async_session() as session:
        await handler(session, payload)
        await session.commit()

There is no timeout. JOB_STALL_SECONDS = 900.0 (jobs.py:43) exists but is used ONLY by
worker_status() for health-check reporting — nothing cancels or reschedules a hung job.
The worker is strictly serial (jobs.py:240-258), so one hung job stops marking,
extraction, readiness synthesis, report generation and Classroom sync for every tenant
until it returns or the process is restarted.

Note what is ALREADY handled and must not be disturbed: backend/app/main.py:79-110
supervises the case where the worker LOOP dies, restarting it with a backoff and counting
restarts (that is RISK-4 and it is done well). The uncovered case is a single job that
hangs without the loop dying.

WHAT TO CHANGE
1. Wrap the handler call in `asyncio.wait_for` with a timeout.
2. Treat a timeout as an ordinary job failure so it flows through the EXISTING retry and
   give-up path — attempts increment, the 60s backoff via run_after applies, and
   MAX_ATTEMPTS still ends it. Read jobs.py:209-235 and route the timeout into that same
   code rather than adding a parallel failure path.
3. Choose the timeout deliberately. It must exceed the slowest legitimate job. Marking
   involves an AI call over several PDFs and images; JOB_STALL_SECONDS = 900 was chosen by
   someone as the "definitely stuck" threshold and its comment explains the reasoning —
   read it, and either reuse that constant or explain in a comment why the cancel
   threshold differs from the report threshold.
4. Log the timeout distinctly from other failures. "This job exceeded its timeout" and
   "this job raised" are different operational signals and the runbook reader needs to
   tell them apart.

CONSTRAINTS
- Do NOT make the worker concurrent in this change. That is issue X-4 and it depends on
  the S3 migration landing first. Keep this PR to the timeout.
- Preserve the existing supervision in main.py. Do not touch _supervised_worker.
- asyncio.wait_for cancels the coroutine, which raises CancelledError INSIDE the handler.
  Verify the session is cleaned up correctly and no half-written transaction is committed
  — this interacts directly with issue D-6 (partial commit on failure). If D-6 has
  shipped, confirm your timeout path benefits from its rollback; if it has not, do not
  fix it here, but note the interaction in the PR.
- Job handlers must remain safe to re-run (BE-6/BE-7) — a timed-out job WILL be retried.

TESTS (required, backend/tests/test_jobs.py)
1. A job that exceeds the timeout is marked failed with attempts incremented and is
   retried per the existing policy.
2. A job that exceeds it twice ends in the terminal failed state with the give-up log.
3. Normal jobs are unaffected (regression).
4. After a timeout, the worker picks up the NEXT job — this is the whole point; assert the
   queue is no longer blocked.
5. Drive with process_one_job(), never worker_loop() (QA-6).

VERIFY
cd backend && .venv/bin/python -m pytest tests/test_jobs.py -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .

Then update docs/volume-4-reliability-and-operations/11-reliability-sre.md and the
runbooks in 14-operations-runbooks.md — a new distinct failure signal needs an entry
(GOV-1).
```

---

<a id="d-8"></a>
## D-8 — Classroom sync: unpaginated, serial N+1, and it can orphan a submission

**S2 · AGENT · ↔ AV-6, AV-20, AV-21 · effort M**

`backend/app/services/google_classroom.py:288-387`

Three distinct defects in one job:

1. **No pagination.** `list_courses` (`:155-163`), `list_coursework` (`:166-173`) and `list_student_submissions` (`:176-185`) none follow Google's `nextPageToken`. Anything past the first page is silently dropped — coursework and submissions that can *never* enter the marking pipeline, with no error anywhere.
2. **Serial N+1 HTTP.** `_sync_submissions` does a separate `get_student_profile` round-trip per submission (`:335`), and `_download_attachments` a separate Drive metadata + download call per attachment (`:369-387`) — all sequential, each with its own `httpx.AsyncClient`, each up to a 20 s timeout. One course with 40 students turning in one assignment is 40+ sequential round-trips holding the single shared worker.
3. **Orphaned submissions.** `_download_attachments` silently `continue`s past any attachment over 20 MB or failing the magic-byte check (`:369-387`). If *every* attachment fails, a `Submission` row is still created — so the dedup at `:345-351` prevents it ever being re-imported — but `mark_submission` is never enqueued. `assignments_needing_attention` (`api/assignments.py:246-275`) surfaces only `extraction_failed`, `ai_failed`, `ai_marked` and `needs_review`; a bare `submitted` with zero files appears in no tutor list, and the student's own view renders it as a normal in-flight submission. The homework is lost with no error surfaced to anyone.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (FastAPI, Python 3.11, httpx).
Fix three defects in the Google Classroom sync job.

FILE: backend/app/services/google_classroom.py

DEFECT 1 — NO PAGINATION (data silently lost)
list_courses (:155-163), list_coursework (:166-173) and list_student_submissions
(:176-185) do not follow Google's `nextPageToken`. Results past the first page are
silently dropped, so coursework and turned-in submissions can NEVER enter the marking
pipeline, with no error raised anywhere.
Fix: follow nextPageToken to exhaustion in all three. Cap total pages defensively and log
if the cap is hit — an unbounded loop against a paginated API is its own hazard.

DEFECT 2 — SERIAL N+1 HTTP (blocks the single shared worker)
_sync_submissions does a separate get_student_profile round-trip per submission (:335),
and _download_attachments a separate Drive metadata + download per attachment (:369-387).
All sequential, each with its own httpx.AsyncClient, each up to HTTP_TIMEOUT=20s. One
course with 40 students turning in one assignment is 40+ sequential round-trips while
holding the ONLY job worker — every other tutor's marking and readiness queues behind it.
Fix: parallelize the independent per-student and per-attachment calls with asyncio.gather,
bounded by a semaphore so you do not hammer Google's rate limits. Reuse one AsyncClient
across the batch rather than constructing one per call.

DEFECT 3 — ORPHANED SUBMISSION (homework silently lost)
_download_attachments (:369-387) silently `continue`s past any attachment over 20MB or
failing the magic-byte check. If EVERY attachment for a turned-in submission fails, the
Submission row is still created at :353-366 — so the dedup at :345-351 prevents it ever
being re-imported — but mark_submission is never enqueued (the `if files:` guard at :366).
The submission sits in status `submitted` forever. api/assignments.py:246-275
(assignments_needing_attention) surfaces only extraction_failed, ai_failed, ai_marked and
needs_review, so it appears in NO tutor list, and api/submissions.py:198-203 renders it to
the student as an ordinary in-flight submission.
Fix: when no usable files were downloaded, record an explicit error state on the
submission so it surfaces to the tutor. Read how the codebase already represents a
submission that failed processing (SubmissionStatus, ai_error) and reuse it rather than
inventing a new status. Then verify it actually appears in assignments_needing_attention —
if the query needs widening, widen it.

CONSTRAINTS
- Do not change the magic-byte validation or MAX_FILE_BYTES. Rejecting a bad attachment is
  correct; silently losing the whole submission is not.
- Keep every Google API call going through the small individually-mockable functions at
  :155-185. That structure is deliberate — its docstring explains it mirrors
  services/ai.py's get_client() choke point so the flow is testable without real Google
  credentials. Do not bypass it when you parallelize.
- The feature must keep degrading gracefully when GOOGLE_CLIENT_ID/SECRET are unset
  (GoogleClassroomUnavailableError).
- Consider whether these three should be three PRs. Defect 3 is the data-loss one and is
  the smallest; shipping it alone first is reasonable. Say what you chose.

TESTS (required, backend/tests/test_classroom.py)
1. A paginated courses/coursework/submissions response is followed to exhaustion and every
   item is imported.
2. A submission whose attachments ALL fail validation ends in a visible error state and
   appears in assignments_needing_attention.
3. A submission with one good and one bad attachment imports the good one and still
   enqueues marking (regression).
4. Parallel fetching still produces the same rows as the serial version did.
5. Never call the real Google API from a test (the mockable functions exist for this).

VERIFY
cd backend && .venv/bin/python -m pytest tests/test_classroom.py -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

---

<a id="d-9"></a>
## D-9 — The query cache is never cleared on logout, and keys are not user-scoped

**S1 · AGENT · effort S**

`frontend/src/auth/AuthContext.tsx:34-40`, `frontend/src/main.tsx:9`

```tsx
const signOut = useCallback(() => {
  logout().catch(() => {});
  storeTokens(null);
  setUser(null);
}, []);
```

No `queryClient.clear()`, and no full page reload anywhere in the sign-out path. Query keys carry no user or organization identifier — `["my-readiness"]`, `["conversations"]`, `["submission", id]`.

**Failure scenario.** Two siblings share a family tablet, or a school machine is used back-to-back. Student A signs out, Student B signs in in the same tab. `staleTime` defaults to 0, but TanStack Query still paints from cache before the background refetch resolves — so Student B's first render of `/student` or `/student/tutor` can briefly show Student A's readiness tiles and AI-chat conversation titles.

Brief, but it is one minor's academic data and private chat titles rendered to another, on a platform whose users are children and whose devices are shared by construction.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (React 18 + TypeScript +
TanStack Query). Fix a cross-account data-leak on shared devices.

THE DEFECT
frontend/src/auth/AuthContext.tsx:34-40:

    const signOut = useCallback(() => {
      logout().catch(() => {});
      storeTokens(null);
      setUser(null);
    }, []);

signOut never calls queryClient.clear(), and there is no full page reload anywhere in the
sign-out path. frontend/src/main.tsx:9 is `new QueryClient()` with no defaults. Query keys
carry no user or org identifier — e.g. ["my-readiness"], ["conversations"],
["submission", id].

Scenario: two siblings share a tablet, or a school machine is used back-to-back. Student A
signs out, Student B signs in in the same tab. staleTime defaults to 0, but TanStack Query
still paints from cache before the background refetch resolves — so Student B's first
render of /student or /student/tutor briefly shows Student A's readiness scores and AI-chat
conversation titles. Minors' academic data and private chat titles, rendered to the wrong
child.

WHAT TO CHANGE
1. Clear the query cache on sign-out. `queryClient.clear()` inside signOut, before or
   after clearing tokens — but make sure it runs even if the `logout()` network call
   fails, since that catch currently swallows everything.
2. Clear it on sign-IN too, defensively. A user signing in over a stale cache is the same
   bug from the other direction.
3. AuthContext will need access to the queryClient. `useQueryClient()` is the idiomatic
   way; check the provider nesting in main.tsx (QueryClientProvider wraps AuthProvider, so
   the hook is available).

Consider ALSO namespacing query keys with the authenticated user id as defence in depth,
but treat that as optional — clearing on both transitions is the actual fix and is far
smaller to review.

CONSTRAINTS
- Do not change the token storage design. Access token in localStorage and refresh token
  in an httpOnly cookie is a deliberate, documented tradeoff (SEC-2/FE-2) and is correct.
- Do not add a full page reload as the fix. It works but it is a blunt instrument that
  costs the SPA its state on every logout.
- Do not change ProtectedRoute. Client-side role gating is UI-only by design (SEC-10) and
  the backend gates are the real control.

TESTS (required, frontend/src/test/)
1. After signOut, the query cache is empty.
2. Simulate A-logs-out-then-B-logs-in in one tab and assert no data from A's queries is
   present in the cache when B's session starts.
3. signOut still clears tokens and user state even when the logout() request rejects
   (regression on the existing `.catch(() => {})`).

VERIFY
cd frontend && npm test
cd frontend && npm run build
cd frontend && npm run lint
```

---

<a id="d-10"></a>
## D-10 — The chat stream is uncancellable and bleeds across conversations

**S2 · AGENT · ↔ AV-34 · effort S**

`frontend/src/api/chat.ts:35-95`, `frontend/src/student/TutorChatPage.tsx:59-127`

`streamMessage()` has no `AbortController` — zero matches for it anywhere in the frontend. The `for (;;) { await reader.read(); ... }` loop terminates only on a `done` event or a server error, never on the caller giving up.

Two consequences:

- **Abandoned streams.** A student sends a message then navigates away. The page unmounts; nothing aborts the fetch. The reader loop keeps running, the backend keeps generating and billing tokens for a reply nobody will see, and state setters keep firing against an unmounted component.
- **Cross-conversation bleed.** While `busy === true`, neither "+ New chat" (`TutorChatPage.tsx:103-108`) nor the sidebar conversation buttons (`:112-119`) are disabled. Switching conversations mid-stream swaps in the new transcript via `setMessages`, but the in-flight stream keeps calling `setStreaming(acc)` for the *old* conversation's reply — which now renders underneath the newly selected conversation, and on completion is appended into whatever `messages` array is current. One conversation's assistant reply visibly lands inside another.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (React 18 + TypeScript).
Make the AI chat stream cancellable.

THE DEFECT
frontend/src/api/chat.ts:35-95 (`streamMessage`) has no AbortController — there are zero
matches for AbortController anywhere in the frontend. Its `for (;;) { await reader.read() }`
loop ends only on a `done` SSE event or a server error, never on the caller giving up.

Two consequences in frontend/src/student/TutorChatPage.tsx:

(a) Abandoned stream. A student sends a message and navigates to /student/homework before
the reply finishes. The page unmounts, nothing aborts the fetch, the reader loop keeps
running, the backend keeps generating and BILLING tokens for a reply nobody will see, and
setStreaming/setMessages keep firing against an unmounted component.

(b) Cross-conversation bleed. While busy === true, neither the "+ New chat" button
(TutorChatPage.tsx:103-108) nor the sidebar conversation buttons (:112-119) are disabled.
Switching conversation mid-stream swaps in the new transcript via setMessages
(TutorChatPage.tsx:31-33), but the in-flight stream keeps calling setStreaming(acc) for
the OLD conversation's reply — which renders under the NEWLY selected conversation and, on
completion, is appended into whatever messages array is current (:86-89). One
conversation's reply visibly appears inside another.

WHAT TO CHANGE
1. Add an AbortController per send. Pass its `signal` into the fetch inside streamMessage
   in frontend/src/api/chat.ts.
2. In TutorChatPage, abort in a useEffect cleanup — on unmount, and on activeId change.
3. Disable the conversation-switch controls while busy, OR abort-and-switch cleanly. Pick
   one and say which: aborting on switch is better UX and is already required by point 2,
   so disabling may be unnecessary. Do not do both half way.
4. An aborted stream must not render as an error to the student. Distinguish
   AbortError from a real failure and handle it silently.

CONSTRAINTS
- streamMessage is one of only two sanctioned bypasses of api/client.ts (FE-1, alongside
  fetchFileUrl for blob downloads). Keep it a bypass; do not route it through client.ts.
- Note that chat.ts currently reimplements the "401 -> refresh -> retry once" logic
  independently of client.ts (chat.ts:55-58). Do NOT fix that here — it is part of issue
  X-11 (refresh coalescing). Just do not make it worse.
- Do not change the backend streaming endpoint in this PR. Whether an aborted client
  should stop server-side generation is a real question (it is where the token saving
  actually comes from) but it is a separate change; note it in the PR description.

TESTS (required, frontend/src/test/)
1. Unmounting mid-stream aborts the fetch and fires no further state updates.
2. Switching conversations mid-stream does not render the old reply under the new
   conversation.
3. A completed stream still appends the reply correctly (regression).
4. An aborted stream does not surface an error message to the student.

VERIFY
cd frontend && npm test
cd frontend && npm run build
cd frontend && npm run lint
```

---

<a id="d-11"></a>
## D-11 — Concurrent double-submit raises an uncaught `IntegrityError`

**S2 · AGENT · effort S**

`backend/app/api/submissions.py:109-121` — when no `Submission` exists, two concurrent `POST /assignments/{id}/submissions` (a double-click, or two tabs) both read `submission is None`, both construct a row, both flush. The second violates `UniqueConstraint("assignment_id", "student_id")` and raises an uncaught `IntegrityError` → 500.

Not data corruption — the constraint does exactly its job. But a student double-tapping "submit" on a phone gets a server error on the most important action in the product, and has no way to know whether their work was saved.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (FastAPI + SQLAlchemy 2 async).
Fix a 500 on concurrent homework submission.

THE DEFECT
backend/app/api/submissions.py:109-121 — when no Submission row exists yet, the handler
reads `submission is None`, constructs a new Submission and flushes. Two concurrent POSTs
to /assignments/{id}/submissions (a double-tap on a phone, or two open tabs) both observe
None, both construct, both flush. The second violates
UniqueConstraint("assignment_id", "student_id") and raises an uncaught IntegrityError,
which surfaces as a 500.

This is not corruption — the constraint works. But a student double-tapping submit on the
single most important action in the product gets a server error and cannot tell whether
their work was saved.

WHAT TO CHANGE
Catch IntegrityError around the create, and on conflict re-read the existing row and
continue as if this request had found it. The second request should then behave exactly as
a resubmission does — which is already implemented in this same handler for the
"submission exists" branch.

Read that existing branch first (submissions.py:114-140) and route the conflict into it
rather than writing a parallel path.

REFERENCE PATTERN
backend/app/services/invites.py:84-109 (`consume()`) is the house style for resolving this
class of race — a conditional UPDATE with a rowcount check rather than read-then-write.
Your case is slightly different (INSERT rather than UPDATE) so catch-and-reread is the
right shape here, but read consume() for the house approach to concurrent state changes.

CONSTRAINTS
- Do not remove or weaken the unique constraint. It is what makes the fix safe.
- Do not use a lock or a SELECT FOR UPDATE. The constraint plus a retry is simpler and
  correct, and FOR UPDATE is silently dropped by SQLite in the test suite anyway (see
  issue D-13), so a lock-based fix would be untestable here.
- Preserve the resubmission cap if issue S-9 has already shipped — a conflict retry must
  not become a way around it.
- The response for the losing request should be the same as a successful submit. From the
  student's perspective their work was submitted; that is true, and telling them otherwise
  would be wrong.

TESTS (required, backend/tests/test_homework.py)
1. Two concurrent submits for the same (assignment, student) both return success, and
   exactly one Submission row exists.
2. A single normal submit is unchanged (regression).
3. A genuine resubmission after settle still behaves as before (regression).

VERIFY
cd backend && .venv/bin/python -m pytest tests/test_homework.py -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

---

<a id="d-12"></a>
## D-12 — Failed fetches render as "0 due / all caught up" and as an empty review queue

**S2 · AGENT · effort S**

Two instances of the same anti-pattern, in the two places it matters most:

**`frontend/src/student/StudentHomePage.tsx:46,73-76,137-139`**
```tsx
const due = (assignments.data ?? []).filter((a) => a.submission_status === "not_submitted");
<StatTile label="Homework due" value={String(due.length)} tone={due.length === 0 ? "good" : "warn"} />
{due.length === 0 && <li>You're all caught up 🎉</li>}
```
If the request fails, `data` is `undefined`, `due` is `[]`, and the student sees a green **"0"** and "You're all caught up 🎉". A failure is indistinguishable from having no homework.

**`frontend/src/tutor/HomeworkOverviewPage.tsx:19,40-104`**
```tsx
{queue.data?.map((item) => ( ... ))}
{queue.data?.length === 0 && ( <li>Nothing to review…</li> )}
```
No `isError` branch. On failure `data` is `undefined`, so `.map` renders nothing *and* the empty-state check is false (`undefined !== 0`) — the panel renders completely blank. That queue is the mechanism by which a tutor catches AI-drafted marks needing a human decision before they count.

This directly violates the repo's own `PROD-2` / `UX-19`: *never render a missing measurement as `0`, `0%`, or an empty bar*. The codebase already does it right in `ReadinessTable.tsx:106-127` and `ActivityPanel.tsx:29-44`.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (React 18 + TypeScript +
TanStack Query). Fix two places where a failed request renders as good news.

THE DEFECT — TWO INSTANCES OF THE SAME ANTI-PATTERN

(a) frontend/src/student/StudentHomePage.tsx:46, 73-76, 137-139
    const due = (assignments.data ?? []).filter((a) => a.submission_status === "not_submitted");
    <StatTile label="Homework due" value={String(due.length)} tone={due.length === 0 ? "good" : "warn"} />
    {due.length === 0 && <li>You're all caught up 🎉</li>}
If myAssignments() fails, data is undefined, due is [], and the student sees a GREEN "0"
and "You're all caught up". A request failure is indistinguishable from having no homework.

(b) frontend/src/tutor/HomeworkOverviewPage.tsx:19, 40-104
    {queue.data?.map((item) => ( ... ))}
    {queue.data?.length === 0 && ( <li>Nothing to review…</li> )}
No isError branch anywhere in the file. On failure data is undefined, so .map renders
nothing AND the empty-state check is false (undefined !== 0) — the panel is completely
blank, indistinguishable from loading. This is the queue through which a tutor catches
AI-drafted marks that need a human decision before they count (AI-11/AI-12).

This violates the repo's own PROD-2 / UX-19: never render a missing measurement as 0, 0%,
or an empty bar. Absent data is shown as absent.

WHAT TO CHANGE
Add explicit error states to both pages. The codebase already does this correctly in two
places — read them first and match the pattern rather than inventing one:
  frontend/src/components/ReadinessTable.tsx:106-127
  frontend/src/tutor/today/ActivityPanel.tsx:29-44

For (a): gate the StatTile and the "all caught up" message on isError and isLoading. A
failed load must not render a number at all, and must not render in the "good" tone.
For (b): add isError branches to BOTH the review-queue and the needs-attention sections.

CONSTRAINTS
- Use semantic token classes (bg-surface, text-ink-700, border-line), never stock Tailwind
  palette names — UX-2 says bg-white is silently retargeted and is not white.
- Do not change any backend code or query logic. This is presentation only.
- Do not add a global error boundary as the fix. These two surfaces need specific,
  informative states, not a generic crash screen.
- While you are here, check whether the same `(data ?? [])` pattern hides errors elsewhere
  on these two pages. Fix what you find on THESE pages; do not sweep the whole frontend in
  this PR.

TESTS (required, frontend/src/test/ — TodayDashboard.test.tsx and the existing suite show
the conventions)
1. StudentHomePage with a failing assignments query renders an error state, NOT "0" and
   NOT "all caught up".
2. StudentHomePage with a genuinely empty list still renders "0" and "all caught up"
   (regression — the true-zero case must keep working).
3. HomeworkOverviewPage with a failing review-queue query renders an error state, not a
   blank panel.
4. HomeworkOverviewPage with a genuinely empty queue still renders "Nothing to review"
   (regression).

VERIFY
cd frontend && npm test
cd frontend && npm run build
cd frontend && npm run lint
```

---

<a id="d-13"></a>
## D-13 — The SQLite test suite structurally cannot catch FK or row-lock bugs

**S3 · AGENT · ↔ AV-29 · effort M**

`backend/tests/conftest.py:6,60-64` forces `sqlite+aiosqlite:///:memory:` and builds the schema from `Base.metadata`. Four things this hides, each verified:

1. **Foreign keys are not enforced at all.** `backend/app/db.py` never issues `PRAGMA foreign_keys = ON`, and SQLite disables FK enforcement per connection by default. This is stronger than "no FK declares `ondelete=`" — it means that **even after D-4 or D-2 adds real `ondelete=` rules, no test can verify they fire.** The suite would pass identically with `CASCADE`, `RESTRICT`, or nothing.
2. **`SELECT ... FOR UPDATE SKIP LOCKED` is silently dropped.** SQLite's dialect does not implement `for_update_clause` and SQLAlchemy's base compiler omits it rather than erroring. `workers/jobs.py:184` and `api/assignments.py:334` both compile to plain `SELECT` under test. The locking clause the job queue's correctness depends on has never been executed by any test.
3. **No migration is ever run by `pytest`.** The schema is generated fresh from current `Base.metadata`, so model/migration drift — like the four indexes that exist only in migrations — is invisible by construction. CI's Alembic job runs `upgrade → downgrade → upgrade` on real Postgres 16, but it runs no queries, only DDL.
4. **JSON column semantics differ.** `sqlalchemy.JSON` is `TEXT` with Python-side serialization on SQLite versus a validating native type on Postgres, across `jobs.payload`, `factor_evaluations.detail`, `readiness_snapshots.weak_topics`, `subjects.grade_boundaries`, `syllabus_uploads.draft`.

Enum handling is genuinely consistent — `Enum(X, native_enum=False, length=N)` becomes `VARCHAR(N)` + a `CHECK` on both.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (FastAPI + SQLAlchemy 2 async).
Close the cheapest gap between the SQLite test database and production Postgres.

CURRENT STATE (verified)
backend/tests/conftest.py:6,60-64 forces DATABASE_URL=sqlite+aiosqlite:///:memory: before
any app import, with a StaticPool shared connection, and builds the schema from
Base.metadata.create_all — so the suite never runs a migration. That is a deliberate,
documented tradeoff (CI runs Alembic upgrade->downgrade->upgrade on real Postgres 16
instead). Do not try to overturn it.

Four things it hides:
1. FOREIGN KEYS ARE NOT ENFORCED AT ALL. backend/app/db.py never issues
   `PRAGMA foreign_keys = ON`, and SQLite disables FK enforcement per connection by
   default. Consequence: even after real `ondelete=` rules are added (issues D-2 and D-4),
   NO test can verify they fire — the suite passes identically with CASCADE, RESTRICT, or
   nothing at all.
2. `SELECT ... FOR UPDATE SKIP LOCKED` is silently dropped. SQLite's dialect does not
   implement for_update_clause and SQLAlchemy omits it rather than erroring, so
   app/workers/jobs.py:184 and app/api/assignments.py:334 compile to plain SELECT under
   test. The job queue's locking has never been executed by any test.
3. No migration is run by pytest, so model/migration drift is invisible.
4. JSON column semantics differ (TEXT + Python serialization vs native validating type).

THIS TASK — fix #1 only. It is the one with a cheap, high-value fix, and it unblocks
testing issues D-2 and D-4.

WHAT TO CHANGE
In backend/app/db.py's `_engine_kwargs` (or immediately alongside it), register a
connect-time event on the SQLite path that issues `PRAGMA foreign_keys = ON`:

    from sqlalchemy import event
    # on the sync_engine, "connect" event -> cursor.execute("PRAGMA foreign_keys=ON")

Apply it ONLY to the SQLite path. Postgres needs nothing.

THEN — and this is the part that matters — run the full suite. Enabling FK enforcement on
a suite that has never had it will likely surface real ordering bugs in test fixtures and
teardown that were previously silent. Fix those. Do not disable the pragma to make the
suite green; that would defeat the entire change.

CONSTRAINTS
- Do NOT move the test suite to Postgres/testcontainers. That is a much larger decision
  with real CI-time cost, and the constitution already records the current arrangement as
  a deliberate tradeoff. If you conclude it is the only way, say so and stop — do not do
  it unasked.
- Do not change conftest.py's DATABASE_URL or its StaticPool arrangement.
- Do not attempt gaps 2, 3 or 4 in this PR.

TESTS
1. The entire existing suite still passes with FK enforcement on. This IS the test — a
   green run after the change is the deliverable, and any fixture you had to fix is
   evidence the change was worth making.
2. Add one test that proves enforcement is actually on: inserting a row with a
   non-existent FK target now raises.

VERIFY
cd backend && .venv/bin/python -m pytest -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .

Then update docs/volume-4-reliability-and-operations/12-quality-engineering.md — it
describes what the test database does and does not verify, and this changes it (GOV-1).
Note in the PR that gaps 2-4 remain open so they are not forgotten.
```

---
# Scalability and cost

> **On the numbers below.** Every quantified claim is derived from verified code constants, with its assumptions stated. Where an assumption is doing real work — AI call latency, submissions per week, topics per subject — it is named so you can substitute your own and redo the arithmetic. The topic counts come from the five seeded syllabi in `backend/seed/syllabus/*.json` (17, 26, 32, 39, 49 topics), so 33 is a real average, not a guess.

<a id="x-1"></a>
## X-1 — Readiness synthesis runs on Opus by omission, and is 51% of all AI spend

**S2 · VERIFIED · effort XS — five minutes, and it is the single highest-leverage change in this document**

`backend/app/config.py:50,52,54` set three per-surface models to the empty string:

```python
ai_reports_model: str = ""
ai_readiness_model: str = ""
ai_class_brief_model: str = ""
```

`backend/app/services/ai.py:83-85` resolves a blank to the provider default:

```python
model = getattr(settings, f"ai_{surface}_model", "") or (
    settings.gemini_model if provider is AiProvider.gemini else settings.anthropic_model
)
```

and `config.py:29` sets `anthropic_model: str = "claude-opus-4-8"`.

**Verified: `render.yaml` sets no override for any of the three.** It lists `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `GEMINI_MODEL`, the three *provider* keys, and `AI_MODEL_PRICING` — and nothing else.

So readiness synthesis — the highest-frequency Anthropic surface, triggered once per student per subject on every settled submission — runs on Opus to summarize forty numeric factor lines into a paragraph. Nobody chose this; it is what a blank string resolves to.

**Cost model.** Assumptions stated: 8 homework + 1 past paper per student per month, 3 subjects, 33 topics per subject, 5 chat messages/day × 22 days, 1 parent report/month. Prices: Gemini 2.5 Pro $1.25/$10 per M, Opus $15/$75 per M, Haiku $1/$5 per M.

| Surface | Calls/mo | $/mo | Share |
|---|---|---|---|
| **Readiness (Opus)** | 9 | **$1.44** | **51%** |
| Chat (Haiku) | 110 | $0.69 | 25% |
| Marking (Gemini) | 9 | $0.50 | 18% |
| Reports (Opus) | 1 | $0.17 | 6% |
| Extraction (amortized over a class of 20) | — | ~$0.01 | <1% |
| **Total** | | **≈ $2.80** | |

At 2,000 students that is **~$5,600/month**. Routing readiness to Haiku takes it from $1.44 to roughly $0.10 and the per-student total from **$2.80 to $1.46 — a 48% reduction, with zero code change and zero risk**, because `ai.py:83-85` already handles a per-surface override.

```
The repository is the Avora / MANARA "IGCSE-OS" platform. This is a CONFIGURATION change
plus a small code change to stop it recurring. Read the whole thing — the config part is
five minutes and should ship immediately.

THE SITUATION (verified — confirm, do not re-derive)
backend/app/config.py:50,52,54 declare:
    ai_reports_model: str = ""
    ai_readiness_model: str = ""
    ai_class_brief_model: str = ""

backend/app/services/ai.py:83-85 resolves a blank per-surface model to the provider
default:
    model = getattr(settings, f"ai_{surface}_model", "") or (
        settings.gemini_model if provider is AiProvider.gemini else settings.anthropic_model
    )
and config.py:29 sets `anthropic_model: str = "claude-opus-4-8"`.

render.yaml sets NO override for any of the three — it lists only ANTHROPIC_API_KEY,
GEMINI_API_KEY, GEMINI_MODEL, the three provider keys and AI_MODEL_PRICING.

So readiness synthesis — the highest-frequency Anthropic surface, fired once per student
per subject on every settled submission — runs on Opus to turn ~40 numeric factor lines
into a paragraph. Nobody chose that; it is what a blank string resolves to. It is roughly
51% of total AI spend.

PART 1 — IMMEDIATE, NO CODE
Set AI_READINESS_MODEL in the Render dashboard to a cheaper Anthropic model. Look up the
current model ids rather than trusting any id written here — model names change and a
wrong id will fail the surface at runtime. The mechanism already works
(services/ai.py:83-85 honours the override), so this is genuinely a one-variable change.

Consider AI_CLASS_BRIEF_MODEL too — a class brief is about ten lines of output.
Be more careful with AI_REPORTS_MODEL: reports are parent-facing prose where quality is
the product. Changing it is a judgement call, not an obvious win. Recommend, do not
decide.

PART 2 — CODE, SO IT CANNOT SILENTLY RECUR
The defect is not the model choice, it is that a blank string silently means "the most
expensive model we have". Make the resolution visible:
1. At startup, log the resolved (surface -> provider, model) for all seven surfaces. One
   line. An operator should be able to read the boot log and see what each surface will
   actually cost.
2. Add a comment at config.py:50-54 stating explicitly that a blank falls back to
   `anthropic_model`, which is Opus, and that this is a cost decision.
3. Consider giving the cheap surfaces explicit non-blank defaults rather than relying on
   fallback. If you do, changing a default changes production behaviour on deploy — call
   that out prominently in the PR description so it is a deliberate decision, not a side
   effect.

CONSTRAINTS
- Do NOT change `anthropic_model` itself (config.py:29). Other things resolve through it
  and changing it would move several surfaces at once.
- Do not change the routing architecture. Per-surface routing (AI-2, ADR-0006) is correct
  and call sites naming a surface rather than a model is exactly why this is a
  one-variable fix.
- Do not change services/prompts.py. A cheaper model may want a differently-tuned prompt,
  but that is a follow-up with its own evaluation, and AI-7 requires a version bump.

TESTS (required, backend/tests/test_ai_provider.py — it already tests surface resolution)
1. A surface with an explicit model override resolves to it.
2. A surface with a blank model resolves to the provider default (regression — this is
   current behaviour and must keep working).
3. The startup log line lists all seven surfaces.
NOTE: that test file monkeypatches via `monkeypatch.setattr(get_settings(), "attr", value)`
because get_settings() is lru_cached — monkeypatch.setenv silently does nothing. Follow
the existing pattern in that file.

VERIFY
cd backend && .venv/bin/python -m pytest tests/test_ai_provider.py tests/test_ai_usage.py -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .

SEPARATELY, worth five minutes: check whether AI_MODEL_PRICING is set in Render at all.
It defaults to "{}" (config.py:59) and render.yaml marks it sync:false. If it was never
filled in, every cost_usd is NULL and the AI-usage page reports $0.00 with everything as
unpriced_call_count — meaning there is currently no cost observability whatsoever. That is
correct behaviour per AI-17 ("never invent a price"), but you cannot manage what you
cannot see.
```

---

<a id="x-2"></a>
## X-2 — One weights-slider save fans out to N × M Opus calls inside a single request

**S2 · VERIFIED · effort M**

`backend/app/api/readiness_weights.py:64-73`

```python
students = (await db.scalars(
    select(GroupMember.student_id).join(Group, Group.id == GroupMember.group_id)
    .where(Group.tutor_id == user.id).distinct()
)).all()
for student_id in students:
    await enqueue_readiness_v2_debounced(db, student_id, None)
```

`subject_id=None` makes `compute_readiness_v2` (`readiness_v2_ai.py:293-308`) loop **every enrolled subject** for that student.

**One tutor with 40 students across 3 subjects, saving the sliders once:**

- 120 Opus calls ≈ **$19.20** (at the X-1 rate)
- ~10,700 queries and ~4,800 `factor_evaluations` rows
- 120 × 15 s = **30 minutes of serial worker time** during which no homework is marked
- The debounce scan (`readiness_v2_ai.py:71-79`) re-runs per student against a queue it is itself growing — **O(n²) inside one HTTP request**, holding a pool connection throughout

At 50 tutors each tuning once at onboarding: **6,000 Opus calls ≈ $960**, and roughly 25 hours of serial worker time. Two tutors onboarding on the same day stops marking platform-wide for a day.

**Sibling defect.** `api/preferences.py:51-59` enqueues `recompute_readiness` with no `subject_id`, and `services/readiness.py:146-149` then runs `select(Subject)` with **no organization or enrollment filter** — iterating every `Subject` row in the database. At 50 tutors with uploaded syllabi (~250 subjects), one preferences save is 40 × 250 = 10,000 queries minimum.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (FastAPI + SQLAlchemy 2 async).
Fix a fan-out that makes one slider save cost tens of dollars and half an hour of worker
time.

THE DEFECT
backend/app/api/readiness_weights.py:64-73, inside the PUT /readiness/weights handler:

    students = (await db.scalars(
        select(GroupMember.student_id).join(Group, Group.id == GroupMember.group_id)
        .where(Group.tutor_id == user.id).distinct()
    )).all()
    for student_id in students:
        await enqueue_readiness_v2_debounced(db, student_id, None)

`subject_id=None` makes compute_readiness_v2 (services/readiness_v2_ai.py:293-308) loop
EVERY enrolled subject. One tutor with 40 students x 3 subjects = 120 Opus synthesis calls,
~10,700 queries, ~4,800 factor_evaluations rows, and ~30 minutes of the strictly-serial
job worker during which no homework is marked for anyone.

Additionally, the debounce scan at services/readiness_v2_ai.py:71-79 loads every pending
v2 job's payload into Python on each call — so this loop is O(n^2) against a queue it is
itself growing, all inside one HTTP request holding a pool connection.

SIBLING DEFECT, same shape, fix it in the same PR:
backend/app/api/preferences.py:51-59 enqueues recompute_readiness with no subject_id, and
backend/app/services/readiness.py:146-149 then runs `select(Subject)` with NO organization
or enrollment filter — iterating every Subject row in the entire database.

WHAT TO CHANGE
1. The unfiltered `select(Subject)` in services/readiness.py:146-149 is a straightforward
   bug — scope it to the student's actual enrollments. Do this first; it is small and
   independently valuable.
2. For the weights fan-out, choose ONE approach and justify it in the PR:
   (a) Enqueue ONE job per tutor that iterates students and subjects internally, so the
       O(n^2) debounce scan happens once rather than per student, and the HTTP request
       returns immediately.
   (b) Do not recompute eagerly at all. Write the new weights, mark existing snapshots
       stale, and recompute lazily on next read. Cheapest by far, but changes when a tutor
       sees their new numbers — a product decision, so flag it rather than assuming.
   (a) is the safer default because it preserves current behaviour.
3. Fix the debounce scan itself: services/readiness_v2_ai.py:71-79 filters pending jobs in
   Python. Filter in SQL instead. The same Python-side filtering exists on the READ path at
   services/readiness_summary_v2.py:64-86, which runs on every readiness page view — fix
   both; they are the same mistake.

CONSTRAINTS
- Do not change the seven readiness factors or the weighting math. This is about how many
  times it runs, not what it computes.
- factor_evaluations is append-only BY DESIGN (models/readiness_v2.py:202-205 — a
  historical AI synthesis must stay reconstructable from its exact inputs). Do not "fix"
  the row growth by making it updatable. Retention is issue X-13.
- Keep the kill switch working: READINESS_V2_SHADOW_ENABLED (config.py:66) is a kill
  switch, not a shadow flag, and turning it off must still degrade to v1 rather than break.
- Job handlers must stay safe to re-run on the same payload (BE-6/BE-7).

TESTS (required, backend/tests/test_readiness_v2.py and test_readiness_v2_shadow.py)
1. Saving weights for a tutor with N students enqueues a bounded number of jobs — assert
   the exact count, and assert it does not scale as N x M.
2. The recompute still produces the same snapshots it does today (regression). This is the
   important one: the fan-out is the bug, the output must not change.
3. services/readiness.py no longer queries subjects the student is not enrolled in.
4. Drive jobs with process_one_job() (QA-6); use fake_ai and patch the calling module
   (QA-7); never call a real provider (QA-8).

VERIFY
cd backend && .venv/bin/python -m pytest tests/test_readiness_v2.py tests/test_readiness_v2_shadow.py tests/test_readiness_cutover.py -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

---

<a id="x-3"></a>
## X-3 — The connection pool is unconfigured, and the worker holds one through a 45-second AI call

**S2 · VERIFIED · effort S**

`backend/app/db.py:9-19`

```python
def _engine_kwargs(url: str) -> dict:
    if url.startswith("sqlite") and ":memory:" in url:
        return {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}}
    return {}

engine = create_async_engine(settings.database_url, **_engine_kwargs(settings.database_url))
```

For Postgres, `_engine_kwargs` returns `{}`. **No `pool_size`, no `max_overflow`, no `pool_timeout`, no `pool_recycle`, no `pool_pre_ping` is ever set**, and `config.py` has no pool setting to override even if someone wanted to. SQLAlchemy's defaults apply: 5 base + 10 overflow = **15 connections, ceiling on concurrent DB-touching requests**. The 16th blocks for 30 s and then raises.

The API and the in-process job worker share this one engine. `workers/jobs.py:201-203`:

```python
async with async_session() as session:
    await handler(session, payload)
```

`_run_marking` queries first (opening a transaction and checking out a connection), *then* awaits the AI call. **One Postgres connection sits idle-in-transaction for the entire multi-second marking call**, holding a snapshot open and blocking vacuum.

Two aggravating details:

- `pool_recycle=-1` with no `pre_ping` means a connection idled past the provider's timeout comes back dead and the request fails with a raw driver error.
- `/api/v1/health` (`main.py:205-219`) is deliberately DB-free, and that is what `render.yaml:26` polls. **A pool-exhausted instance passes its health check and keeps taking traffic.** The comment at `main.py:238-243` explicitly reasons about the 30 s `pool_timeout` default — while never setting it.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (FastAPI + SQLAlchemy 2 async
+ Postgres on Render). Configure the connection pool and stop the worker holding a
connection through AI calls.

THE DEFECT
backend/app/db.py:9-19 — for the Postgres path, `_engine_kwargs` returns `{}`. No
pool_size, max_overflow, pool_timeout, pool_recycle or pool_pre_ping is ever set, and
backend/app/config.py has no pool setting to override. SQLAlchemy defaults apply:
pool_size=5, max_overflow=10 (15 connections total), pool_timeout=30, pool_recycle=-1,
pool_pre_ping=False.

The API and the in-process job worker share this one engine (app/workers/jobs.py:20
imports async_session from app.db, the same object api/deps.py's get_db uses).

app/workers/jobs.py:201-203:
    async with async_session() as session:
        await handler(session, payload)
`_run_marking` queries first — opening a transaction and checking out a connection — and
THEN awaits a multi-second AI call. One connection sits idle-in-transaction for that whole
duration, holding a snapshot open and blocking vacuum.

Two aggravating facts:
- pool_recycle=-1 with no pre_ping means a connection idled past the provider's timeout
  returns dead and the request fails with a raw driver error.
- /api/v1/health (app/main.py:205-219) is deliberately DB-free and is what render.yaml:26
  polls, so a pool-exhausted instance PASSES its health check and keeps taking traffic.
  The comment at main.py:238-243 explicitly reasons about the 30s pool_timeout default
  while never setting it.

WHAT TO CHANGE — TWO PARTS. The second matters more than the first.

PART 1: explicit pool configuration
Set pool_size, max_overflow, pool_timeout, pool_recycle and pool_pre_ping explicitly for
the Postgres path in `_engine_kwargs`. Make them settings in config.py so they are
tunable without a deploy.

Choose the numbers against the actual database plan: render.yaml:11 says `basic-256mb`.
Look up its connection limit before picking, and leave headroom — the total is
(API instances x pool) + (workers x pool), and this must not exceed what the database
accepts. Comment the arithmetic. A pool_timeout well under 30s is preferable: failing fast
gives a usable error where waiting 30s gives a timeout nobody can diagnose.

PART 2: stop holding a connection across the AI call
This is the real fix — widening the pool only raises the ceiling on a problem that should
not exist. In services/marking.py, `_run_marking` already reads most of its input up front
(the _homework_source/_past_paper_source path) before the structured_complete call.
Restructure so the session is released between the read and the AI call, and re-acquired
for the write:
  - open a session, read what the AI call needs, commit/close
  - make the AI call holding NO connection
  - open a second session to persist marks and usage
Apply the same shape to the other long-running handlers — extraction, syllabus extraction,
and readiness v2 synthesis all have the same structure.

CONSTRAINTS
- Job handlers must stay safe to re-run on the same payload (BE-6/BE-7), and marking must
  keep its existing contract: update QuestionMark drafts in place, never overwrite a
  tutor-finalized mark, skip the AI call entirely when every question is already decided.
- This interacts with issue D-6 (partial commit on marking failure). Splitting the session
  changes what is pending when a failure hits. If D-6 has shipped, verify your split
  preserves its guarantee. If it has not, do not fix it here — but say in the PR how your
  change affects it.
- Do NOT change /api/v1/health to touch the database. Its shallowness is deliberate and
  correct — the comment at main.py:205-219 explains that a DB round-trip there would turn
  a database blip into a restart loop and a failed deploy. If you want pool exhaustion to
  be visible, add it to /health/ready, which already exists for exactly this.
- Do not change the SQLite/StaticPool test path.

TESTS (required)
1. Engine is constructed with the explicit pool settings (assert on the engine's pool).
2. A marking job completes correctly with the split-session structure (regression) —
   backend/tests/test_auto_marking.py.
3. The AI call is made while no session is open. Assert this directly, e.g. by having the
   fake_ai fixture check that no connection is checked out at call time.
4. Idempotency still holds: running the same marking job twice produces the correct final
   state (BE-6).

VERIFY
cd backend && .venv/bin/python -m pytest tests/ -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .

Then update docs/volume-3-platform-engineering/10-performance-engineering.md and
08-infrastructure-and-deployment.md (GOV-1).
```

---

<a id="x-4"></a>
## X-4 — The job worker is strictly serial: a class of 30 has a 12.5-minute tail

**S2 · DERIVED · ↔ AV-26 · effort L (blocked on X-15 step 1)**

`backend/app/workers/jobs.py:240-258` — `worker_loop()` awaits `process_one_job()`, which claims with `.limit(1)`. One job at a time, one asyncio task, and `main.py:110` creates exactly one.

**The model.** Assumptions: 30 students submit uniformly across 600 s; marking takes 45 s (Gemini over 2 PDFs + 4 photos, `max_tokens=32000` at `marking.py:249-256`).

```
interarrival = 600 / 29     = 20.7 s
service                     = 45 s
ρ = 45 / 20.7               = 2.17        → the server never idles after job 1

finish(30) = 45 × 30        = 1350 s
arrival(30)                 = 600 s
wait(30)   = 1350 − 600     = 750 s       = 12.5 minutes
```

Then the readiness layer lands on top — 30 `recompute_readiness` (v1, ~0.2 s) plus **30** `compute_readiness_v2` (~15 s each, because the debounce does not debounce a class — see X-5):

```
30×45 + 30×0.2 + 30×15 = 1806 s = 30.1 minutes of serial work
last readiness score visible ≈ 33 minutes after the lesson
```

**Break-even is 20.7 s per marking job. Real marking is 30–90 s. The queue is already unstable today, with one tutor.**

At scale the wall arrives earlier than the stated target. Assuming 2 submissions/week/student and 70% of load in a 5-hour after-school window: capacity is 300 submissions/evening, 1,500/week, **≈750 students** — not 2,000. At 2,000 the peak backlog reaches ~4.3 hours and drains overnight, so it never *fails*, it just becomes uselessly slow every evening. Daily average utilization is only ~40%, which is precisely why average-based monitoring will never show it.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (FastAPI, Python 3.11, asyncio).
Make the background job worker concurrent.

READ THIS FIRST — THERE IS A HARD PREREQUISITE
This change is BLOCKED until uploads move off the local disk to object storage (issue
X-15, step 1). Reason: render.yaml:34-37 mounts a persistent disk at /data, a Render
service with a disk runs exactly one instance, and services/marking.py reads uploaded
files via services/storage.py from that disk. A separate worker service cannot mount it.

If the S3 migration has NOT landed, stop and say so. Do not attempt a workaround.

WHAT IS ALREADY CORRECT (do not "fix" it)
app/workers/jobs.py:184 already claims jobs with SELECT ... FOR UPDATE SKIP LOCKED, so
multiple workers are safe by construction. That was built for this moment.

THE DEFECT
app/workers/jobs.py:240-258 — worker_loop() awaits process_one_job(), which claims with
.limit(1). One job at a time. app/main.py:110 creates exactly one task.

Modelled: 30 students submitting over 10 minutes, 45s marking, gives a 12.5-minute wait
for the last student's marking and ~33 minutes until their readiness score appears.
Break-even is 20.7s per job; real marking is 30-90s, so the queue is already unstable at
today's scale with one tutor.

WHAT TO CHANGE
1. Move the worker out of the API process into its own Render service. Same Docker image,
   `type: worker` in render.yaml, different start command. Remove the in-process worker
   startup from app/main.py's lifespan.
2. Run N concurrent job tasks within the worker process, N configurable via settings.
   Start at 4 and justify it against the database connection budget — each concurrent job
   holds a pooled connection (see issue X-3; if X-3 has shipped, jobs release the
   connection across the AI call and N can be higher).
3. FIX THE HEALTH REPORTING — this is the part that is easy to get wrong.
   app/workers/jobs.py:62-69 keeps _started_at, _last_loop_at, _job_started_at and
   _restart_times as MODULE GLOBALS. With a separate worker service, /health/ready on the
   API process has no visibility into the worker at all, and with N workers the globals
   describe whichever one you happened to ask.
   Replace them with a worker_heartbeat table, one row per worker id, that the API's
   /health/ready reads. The current health endpoint correctly reports a dead worker
   (that is RISK-4 and it was hard-won) — your change must not lose that. Read
   app/main.py:220-280 and app/workers/jobs.py:56-69 before touching anything.
4. Keep the supervision semantics from app/main.py:79-110 — restart with backoff, count
   restarts, log distinctly — in the new worker process.

CONSTRAINTS
- Do not change the job claim query. FOR UPDATE SKIP LOCKED is correct.
- Do not remove the /health/ready worker reporting. Degrading it would re-open RISK-4,
  which the codebase explicitly fixed.
- Job handlers must be safe to run concurrently with each other. Audit them: the readiness
  debounce (issue X-5) has a known read-then-insert race that is currently masked by
  serial execution and WILL fire under concurrency. Either fix X-5 first or fix it here —
  do not ship concurrency on top of a known race.
- Migrations run at API startup today (`alembic upgrade head` then uvicorn). Decide which
  service owns migrations now that there are two, and make sure the worker does not race
  the API to run them.

TESTS (required, backend/tests/test_jobs.py)
1. N jobs are processed concurrently — assert overlap, not just completion.
2. Two workers never claim the same job (this is what SKIP LOCKED buys; assert it).
3. /health/ready still reports a dead worker as degraded, via the new heartbeat table.
4. /health/ready reports correctly with multiple workers registered.
5. Drive with process_one_job() where possible (QA-6); the concurrency tests will need
   more than that, so keep them tightly scoped and deterministic.

VERIFY
cd backend && .venv/bin/python -m pytest tests/test_jobs.py tests/test_health.py -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .

Then update docs/volume-3-platform-engineering/08-infrastructure-and-deployment.md,
docs/volume-4-reliability-and-operations/11-reliability-sre.md, and
docs/governance/risk-register.md (RISK-1) — this changes the deployment topology, which
several documents describe (GOV-1).
```

---

<a id="x-5"></a>
## X-5 — The readiness debounce does not debounce a class, misses `running`, and races

**S2 · AGENT · effort M**

`backend/app/services/readiness_v2_ai.py:51-91`

```python
if any(p.get("student_id") == student_id and p.get("subject_id") == subject_id for p in pending):
    return
```

`main.py:62-64` states that *"a burst of auto-finalized submissions costs one synthesis, not one each."* That is true for **one student submitting many pieces**. It is not true for a class: 30 students is 30 distinct keys, so 30 syntheses and 30 Opus calls.

Three further defects in the same function:

1. **It filters `status == pending` only** (`:74-77`). A trigger arriving while a synthesis is `running` sees nothing and enqueues a duplicate. The window is roughly 15 s in every 600 s.
2. **Read-then-insert with no constraint or lock.** `finalize_submission` (`api/submissions.py:659`) runs in the API process concurrently with the worker's auto-finalize (`marking.py:357`). Under READ COMMITTED both see no pending row and both insert. `payload` is JSON, so no partial unique index is available to catch it. **This race is currently masked by the serial worker and will fire the moment X-4 lands.**
3. **It scans every pending v2 job in the database** and materializes payloads into Python on every finalization — O(n²) across a burst.

The same Python-side filtering is on the read path: `readiness_summary_v2.py:64-86` loads every pending/running v2 payload on **every readiness page view**.

Per-recompute cost, for context: ~89 queries and 40 `factor_evaluations` rows. Per class of 30: ~2,670 queries, 1,200 rows, 30 Opus calls ≈ $4.80.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (FastAPI + SQLAlchemy 2 async).
Fix three defects in the readiness-v2 debounce.

FILE: backend/app/services/readiness_v2_ai.py:51-91 (enqueue_readiness_v2_debounced)

DEFECT 1 — it only checks pending, not running
Lines 74-77 filter `status == pending`. A trigger arriving while a synthesis for the same
(student, subject) is already RUNNING sees nothing and enqueues a duplicate. Window is
roughly 15s in every 600s coalesce period.
Fix: treat running as also-in-flight.

DEFECT 2 — read-then-insert race, no constraint, no lock
api/submissions.py:659 (finalize_submission, in the API process) runs concurrently with
services/marking.py:357 (auto-finalize, in the worker). Under READ COMMITTED both can
observe no in-flight row and both insert. The job `payload` is JSON so no partial unique
index is available.
THIS IS URGENT IF ISSUE X-4 IS PLANNED: the race is currently masked by the strictly
serial worker and will fire immediately under concurrency.
Fix: make the check-and-enqueue atomic. Options, pick one and justify: a dedicated
debounce/coalescing table with a real unique constraint on (student_id, subject_id) that
the job reads from; or an advisory lock around the check-and-insert. A dedicated table is
probably cleaner and also fixes defect 3.

DEFECT 3 — O(n^2) scan
Lines 71-79 load EVERY pending v2 job's payload into Python and filter there, on every
finalization. Across a burst this is quadratic.
Fix: filter in SQL. The same mistake is on the READ path at
services/readiness_summary_v2.py:64-86, which loads every pending/running v2 payload on
every readiness page view — fix both.

NOT A DEFECT, BUT UNDERSTAND IT BEFORE YOU START
The docstring at app/main.py:62-64 says a burst of auto-finalized submissions costs one
synthesis rather than one each. That is TRUE for one student submitting many pieces, and
FALSE for a class — 30 students are 30 distinct keys, so 30 syntheses and 30 Opus calls.
That is arguably correct behaviour (they are genuinely different students' scores), but
the comment overstates it. Correct the comment as part of this PR; a comment that
overstates a guarantee is how the next person builds on a promise that was never made.

CONSTRAINTS
- Do not change the seven factors or the weighting math.
- factor_evaluations is append-only by design (models/readiness_v2.py:202-205). Do not
  make it updatable.
- Keep READINESS_V2_SHADOW_ENABLED working as a kill switch that degrades to v1
  (config.py:60-66), not as a shadow flag.
- If you add a table, hand-write the migration per DB-15/DB-16/DB-17 and declare any index
  in the model too (DB-12).
- Job handlers must stay safe to re-run on the same payload (BE-6/BE-7).

TESTS (required, backend/tests/test_readiness_v2.py, test_readiness_v2_ai.py)
1. A trigger arriving while a synthesis is RUNNING does not enqueue a duplicate.
2. Two concurrent finalizations for the same (student, subject) produce exactly ONE
   synthesis job. This is the race — write it as a real concurrency test, not a sequential
   one, or it proves nothing.
3. Two different students still get one synthesis each (regression — the debounce must not
   over-collapse).
4. The readiness summary read path returns the same results with SQL filtering
   (regression).
5. Drive with process_one_job() (QA-6); fake_ai patched on the calling module (QA-7).

VERIFY
cd backend && .venv/bin/python -m pytest tests/test_readiness_v2.py tests/test_readiness_v2_ai.py tests/test_readiness_v2_shadow.py tests/test_readiness_cutover.py -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

---

<a id="x-6"></a>
## X-6 — 109 foreign keys, 5 indexes

**S3 · VERIFIED · ↔ AV-23 · effort S**

The complete index inventory across 21 migrations:

| Index | Migration | Columns |
|---|---|---|
| `ix_evidence_student_topic` | `0004:44` | (student_id, topic_id) |
| `ix_factor_evaluations_run_student_subject` | `0016:169-173` | (evaluation_run_id, student_id, subject_id) |
| `ix_readiness_snapshots_student_subject` | `0016:194-198` | (student_id, subject_id, created_at) |
| `ix_jobs_status_run_after` | `0018:45` | (status, run_after) |
| `ix_mark_override_audit_question_mark_id` | `0019:51-55` | (question_mark_id) |

Plus ~14 `UniqueConstraint` declarations that Postgres backs with an index. Postgres does **not** auto-index foreign keys, so roughly **90 of 109 FK columns are unindexed**.

The queries that will table-scan, ranked by damage:

1. **`assignment_questions.assignment_id`** — `SUM(max_marks) WHERE assignment_id=?` at `submissions.py:150,241,303` and `student_crm.py:122`. Inside `my_assignments` this runs once *per assignment*: 60 assignments × a 75k-row scan = **4.5 M rows touched per page view.** The worst single query in the codebase.
2. **`ai_usage_events.organization_id`** — `WHERE organization_id=? GROUP BY ...` at `api/ai_usage.py:30,88`, full scan. At 1.2 M rows/year that is ~150 MB scanned per page load on a 256 MB database.
3. **`chat_messages.conversation_id`** — `WHERE conversation_id = ? ORDER BY id`, twice per chat message (`chat.py:74,120`), full scan.
4. **`evidence.source_ref`** — a targeted `DELETE` on *every* finalization (`services/evidence.py:80`).
5. **`readiness_history.(student_id, subject_id)`** — no index at all.
6. **`submissions.student_id`** — the trailing column of both unique constraints, so not usable alone.
7. **`users.organization_id`** — `resolve_org_tutor_id` (`knowledge.py:57-59`) scans `users` on every chat message and every readiness synthesis.
8. **`group_members.student_id`** — `Unique(group_id, student_id)` has the wrong leading column; this is hit in nearly every authorization check.
9. **`jobs`** — the `GROUP BY status` in `/health/ready` (`main.py:154`); see X-14.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (SQLAlchemy 2 async + Postgres
+ Alembic). Add the missing indexes.

CURRENT STATE (verified)
109 foreign keys. 5 explicit indexes across all 21 migrations, plus ~14 UniqueConstraints
that Postgres backs with an index. Postgres does not auto-index FK columns, so ~90 of 109
are unindexed.

THE INDEXES TO ADD, ranked by the damage they prevent. Verify each against the code before
writing it — do not add an index for a query you have not seen.

TIER 1 — add these
  assignment_questions(assignment_id)
      SUM(max_marks) WHERE assignment_id=? at api/submissions.py:150,241,303 and
      services/student_crm.py:122. Inside my_assignments this runs once PER assignment.
      The worst query in the codebase.
  ai_usage_events(organization_id)
      WHERE organization_id=? GROUP BY at api/ai_usage.py:30,88 — full scan.
  chat_messages(conversation_id)
      WHERE conversation_id=? ORDER BY id at api/chat.py:74,120 — twice per message.
  evidence(source_ref)
      Targeted DELETE on every finalization, services/evidence.py:80.
  submissions(student_id)
      Trailing column of both unique constraints, so unusable alone. Hit at
      api/submissions.py:246, services/activity.py:109.
  group_members(student_id)
      Unique(group_id, student_id) has the wrong leading column. Hit in nearly every
      authorization check.
  users(organization_id)
      services/knowledge.py:57-59 scans users on every chat message and every readiness
      synthesis.
  readiness_history(student_id, subject_id)
      No index at all. api/readiness.py:158-167, services/reports.py:96-105.
  assignments(group_id), groups(tutor_id), lessons(group_id), submission_files(submission_id)
      Every group page, every tutor home page, every submission detail view.

TIER 2 — judgement call, include if the query volume justifies it
  tutor_notes(student_id, created_at DESC), parent_communications(student_id, created_at DESC)
  assessment_scores(student_id), mistakes(student_id), schedule_slots(group_id)
  past_papers(organization_id, subject_id), reports(student_id)
  chat_conversations(student_id), group_resources(group_id)
  question_marks(question_id) WHERE question_id IS NOT NULL
  question_marks(past_paper_question_id) WHERE past_paper_question_id IS NOT NULL
      (partial, because both are nullable — the polymorphic split)

COMPOSITE ORDERING RULE: equality-filtered columns first, range/sort columns last. That
is why the CRM timelines are (student_id, created_at DESC) and past_papers is
(organization_id, subject_id) with the tenant boundary first.

CRITICAL MIGRATION REQUIREMENT — DO NOT SKIP
These tables have production rows; the default branch has been deploying since 0001. A
plain `op.create_index(...)` inside a normal Alembic migration takes a lock that blocks
writes for the entire index build.

Use `op.get_context().autocommit_block()` with `postgresql_concurrently=True`, ONE index
per transaction. Alembic cannot run CREATE INDEX CONCURRENTLY inside its wrapping
transaction otherwise. Note that all 5 existing create_index calls in this repo do NOT do
this — they were fine at the row counts those tables had when they shipped. Do not copy
them.

CONCURRENTLY does not work on SQLite, and the test suite is SQLite. Make the migration
dialect-aware so it still runs under test.

OTHER REQUIREMENTS
- Hand-write backend/alembic/versions/0022_*.py per DB-15 (sequential number,
  down_revision chained to 0021), with a working downgrade() (DB-16).
- Declare every index in the MODEL as well as the migration. DB-12 exists precisely
  because four existing indexes live only in migrations and the test schema diverges from
  production as a result. Do not add more divergence.

CONSTRAINTS
- Do not add an index you cannot point at a query for. An unused index costs write
  throughput and storage.
- Do not restructure any query in this PR. Indexes only. Query fixes are issue X-8.
- Tier 1 alone is a good PR. Tier 2 can follow.

TESTS
Indexes do not change behaviour, so the test is that nothing broke plus the schema
assertion:
1. Full suite passes.
2. Assert each new index exists after create_all (this is what catches a model/migration
   divergence, which is the whole point of DB-12).

VERIFY
cd backend && .venv/bin/python -m pytest -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
CI's Alembic upgrade->downgrade->upgrade on real Postgres 16 is the gate that matters —
it is the only place your CONCURRENTLY logic actually executes.

Then update docs/volume-2-application-engineering/06-database-design.md, which records the
missing-index gap (DB-11/DB-12). Close the entries rather than leaving them stale (GOV-3).
```

---

<a id="x-7"></a>
## X-7 — bcrypt, HEIC transcode and all file I/O block the shared event loop

**S3 · VERIFIED · ↔ AV-22 · effort M**

First, what is **not** a problem: the AI calls themselves are genuinely async (`services/ai.py:230,250` — `await client.messages.parse` / `await client.aio.models.generate_content`), Google Classroom and Gemini both use async clients, and there is no `time.sleep` anywhere. A slow AI call does **not** block HTTP serving.

Everything in this table does:

| file:line | Call | Blocked for | Reached from |
|---|---|---|---|
| `security.py:11` | `bcrypt.hashpw` (cost 12) | 250–500 ms | every registration |
| `security.py:16` | `bcrypt.checkpw` | 250–500 ms | **every login**, including the dummy-hash miss |
| `storage.py:42-44` | `Image.open` + `convert("RGB").save` | 0.5–1.5 s per photo | every HEIC upload — the iPhone default |
| `storage.py:148` | `Path.write_bytes` (≤20 MB) | 50–200 ms | 7 upload endpoints |
| `storage.py:162` | `Path.read_bytes` (≤20 MB) | ~100 ms/file | marking ×5, extraction ×4, syllabus ×1 |
| `ai.py:147` | `base64.standard_b64encode` of up to 60 MB | 40–80 ms | every marking/extraction job |
| `ai.py:174` | `base64.standard_b64decode` — decodes back what `file_block` just encoded | 40–80 ms | every Gemini call |

**Quantified.** Per marking job: ~0.5–1.0 s of contiguous loop block. At 80 jobs/hour that is a 1.7% duty cycle today; at 10× it is a visible p99 spike on every concurrent request.

**Logins are the real wall.** bcrypt is pure CPU and fully serializing, and Render `starter` (`render.yaml:18`) is 0.5 CPU. Throughput is roughly **2–3 logins/sec, each freezing every other request for its duration**. A 400-student Monday-4pm login wave is 400 × 0.4 s = **160 seconds of fully serialized CPU** with everything queued behind it.

Note that ruff has the `ASYNC` ruleset enabled (`pyproject.toml:59`) and catches none of this — the blocking calls live in *sync* helper functions called from async code, which ASYNC230/240 do not detect.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (FastAPI, Python 3.11, asyncio).
Move blocking CPU and disk work off the shared event loop.

WHY THIS MATTERS HERE SPECIFICALLY
CLAUDE.md's BE-13/PERF-1 rule states it directly: "the worker shares the API's event loop,
so one blocking call stalls request serving for every user." The API is a single Render
`starter` instance (0.5 CPU) running both HTTP serving and the background job worker in
one process.

WHAT IS ALREADY FINE — do not touch
The AI calls are genuinely async (services/ai.py:230,250 — await client.messages.parse and
await client.aio.models.generate_content). Google Classroom and Gemini use async clients.
There is no time.sleep anywhere. A slow AI call does NOT block request serving.

THE BLOCKING CALLS, in priority order

1. bcrypt — THE WORST ONE
   app/security.py:11 hash_password (bcrypt.hashpw, cost 12) — every registration
   app/security.py:16 verify_password (bcrypt.checkpw) — EVERY LOGIN, including the
   constant-time dummy-hash miss at api/auth.py:118
   250-500ms of pure CPU each, fully serializing. On 0.5 CPU that is ~2-3 logins/sec, and
   each one freezes every other request. A 400-student login wave is ~160 seconds of
   serialized CPU with everything queued behind it.

2. HEIC transcode
   app/services/storage.py:42-44 — Image.open + convert("RGB").save(JPEG). 0.5-1.5s per
   photo, on the DEFAULT path for the product's core flow (iPhones shoot HEIC; students
   photograph homework). 30 students x 3 photos = ~90 seconds of blocked loop.

3. File I/O
   app/services/storage.py:148 Path.write_bytes (up to 20MB) — 7 upload endpoints
   app/services/storage.py:162 Path.read_bytes (up to 20MB) — marking reads 5 files per
   job, extraction 4, syllabus 1

4. base64
   app/services/ai.py:147 standard_b64encode of up to 60MB, every marking/extraction job
   app/services/ai.py:174 standard_b64decode — decodes back what file_block just encoded.
   Worth looking at whether that round-trip is necessary at all rather than just
   offloading it.

WHAT TO CHANGE
Wrap each in a thread offload. The project already depends on anyio via Starlette, so
`anyio.to_thread.run_sync` is the natural choice; `asyncio.to_thread` is equivalent. Be
consistent and pick one.

Do it at the right layer: make the SYNC helpers stay sync and pure, and offload at the
async call sites — or provide async wrappers in storage.py/security.py that the async
callers use. The second is less invasive given how many call sites there are. Decide, and
be consistent.

Order of work, by value: bcrypt first (biggest and smallest change), then HEIC, then file
I/O, then base64.

CONSTRAINTS
- Do NOT reduce the bcrypt cost factor to make it faster. That is a security control.
- Do not change the constant-time dummy-hash comparison at api/auth.py:118 — it prevents
  account enumeration and it must keep running even on a miss.
- Thread pool size is finite (anyio defaults to 40). Offloading everything to threads
  moves the bottleneck rather than removing it. For the biggest offenders consider whether
  a bounded semaphore is warranted, and comment the reasoning.
- Note that ruff's ASYNC rules are already enabled (backend/pyproject.toml:59) and catch
  none of this, because the blocking calls live in sync helpers called from async code.
  Do not assume a green lint means you found them all — work from the list above.
- Issue S-7 adds a pixel-count guard to the same HEIC function. If it has shipped, keep it.
  If not, do not add it here; keep the changes separable.

TESTS (required)
1. Full suite passes — these are behaviour-preserving changes and the existing tests are
   the regression net.
2. Assert the offload actually happens for bcrypt and for the storage functions (e.g.
   patch the thread-offload helper and assert it was called).
3. Add a test that the event loop stays responsive during a large file write. Keep it
   deterministic — a flaky timing test is worse than no test.

VERIFY
cd backend && .venv/bin/python -m pytest -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .

Then update docs/volume-3-platform-engineering/10-performance-engineering.md (GOV-1).
```

---

<a id="x-8"></a>
## X-8 — N+1 cluster across 15 confirmed sites

**S3 · AGENT · ↔ AV-24 · effort L**

| file:line | Loop | Queries | Bites at |
|---|---|---|---|
| `services/readiness_v2.py:319-332` | per topic → `_marked_questions_for_topic` | **33** per recompute | already |
| `services/readiness_v2.py:162-185` | per assignment → 2 queries | 2F | already |
| `services/readiness_v2.py:191` | `_homework_assignment_rows` re-issued verbatim | duplicate | already |
| `services/readiness_v2_ai.py:197` | `select(Topic)` re-queried (already fetched at `readiness_v2.py:317`) | duplicate | already |
| `services/student_crm.py:119-134` | per assignment → 2 queries | 41 | already |
| `api/submissions.py:237-265` | per assignment → stats + submission + `_student_view` | **1+5A** | 10× |
| `api/submissions.py:424-433` | per queue row → count + `_open_remarks` | 1+2N | 10× |
| `api/assignments.py:202-215` | per assignment → 2 queries | 1+2A | 10× |
| `services/evidence.py:57-73` | **per question mark** → topic-ids query | ~15/submission | 10× |
| `api/past_papers.py:193` | `[await _out(db, p) …]` | 1+P | 10× |
| `api/lessons.py:98` | `[await _lesson_out(db, l) …]` | 1+L×k | 10× |
| `api/analytics.py:49-74` | per student → `db.get(User)` + readiness rows | 2+2S | 10× |
| `api/assignments.py:366-369` | `db.get(Topic, …)` in a nested loop | per topic | 10× |
| `services/student_crm.py:85-96` | per enrollment → `db.get(Subject, …)` | 1+E | 100× |
| `api/readiness.py:142-168` | per subject → 3 queries | 3S | 100× |

`selectinload` / `joinedload` appears in exactly seven places in the whole API. **Nowhere in the readiness engine, nowhere in `student_crm`, nowhere in `analytics`.**

**Worst offender: `GET /me/assignments`** (`api/submissions.py:221-266`) at 1+5A queries. A=20 today is 101 queries; at two submissions a week over 30 weeks, A=60 → **301 queries per page load**, ~600 ms holding one of 15 pool connections. A 300-student evening login wave is ~90,300 queries in a burst against `basic-256mb` Postgres.

The codebase already contains the right pattern: `services/groups.py:68-108` (`summaries()`) pulls per-group aggregates in one grouped query. That is the template.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (SQLAlchemy 2 async + Postgres).
Eliminate N+1 query patterns. Do this in SEVERAL PRs, not one — the list is long and each
fix needs its own regression test.

THE REFERENCE PATTERN — read this first
backend/app/services/groups.py:68-108 (`summaries()`) already does this correctly: it
pulls per-group aggregates in one grouped query rather than looping. That is the house
style. Every fix below should end up looking like it.

The general shape:
    totals = dict((await session.execute(
        select(AssignmentQuestion.assignment_id,
               func.coalesce(func.sum(AssignmentQuestion.max_marks), 0))
        .where(AssignmentQuestion.assignment_id.in_(assignment_ids))
        .group_by(AssignmentQuestion.assignment_id)
    )).all())
then index into `totals` inside the loop.

PR 1 — the readiness engine (highest frequency; runs on every settled submission)
  services/readiness_v2.py:319-332 — loops every Topic calling _marked_questions_for_topic
    (:83-99), one query per topic. Seeded subjects have 17-49 topics, so 17-49 extra
    round-trips per (student, subject) recompute. Batch into ONE query keyed by topic_id,
    grouped in Python with a defaultdict.
  services/readiness_v2.py:162-185 — _homework_points loops assignments issuing 2 queries
    each. Batch with the grouped-aggregate pattern above.
  services/readiness_v2.py:191 — _homework_assignment_rows re-issues an identical query.
    Reuse the first result.
  services/readiness_v2_ai.py:197 — re-queries select(Topic) already fetched at
    readiness_v2.py:317. Pass it through.

PR 2 — GET /me/assignments, the worst single endpoint
  api/submissions.py:237-265 at 1+5A queries. A=20 today is 101 queries; at two
  submissions a week over 30 weeks A=60 gives 301 queries and ~600ms per page load,
  holding one of only 15 pool connections. Batch the per-assignment stats and the
  submission lookup.

PR 3 — tutor-facing lists
  api/submissions.py:424-433 (review_queue, 1+2N)
  api/assignments.py:202-215 (list_group_assignments, 1+2A)
  api/assignments.py:366-369 (db.get(Topic) in a nested loop — batch with .in_())
  api/analytics.py:49-74 (per student: db.get(User) + readiness rows)

PR 4 — the rest
  services/student_crm.py:85-96 (db.get(Subject) per enrollment)
  services/student_crm.py:119-134 (2 queries per assignment)
  services/evidence.py:57-73 (a topic-ids query PER QUESTION MARK, ~15 per submission)
  api/past_papers.py:193, api/lessons.py:98, api/readiness.py:142-168

ALSO WORTH KNOWING
selectinload/joinedload appears in exactly 7 places across the whole API and NOWHERE in
the readiness engine, student_crm, or analytics. Several call sites avoid the lazy-load
trap by doing a manual db.get() instead — which is itself the N+1. Where a relationship
access is the natural expression, use selectinload rather than a hand-rolled second query.

CONSTRAINTS
- These are behaviour-preserving refactors. The output must be IDENTICAL. For each fix,
  the test that matters is a regression test asserting the same result as before.
- Do not add caching. The fix is fewer queries, not memoized wrong answers.
- Do not add pagination here — that is issue X-10 and changes the API contract.
- Do not restructure the readiness math. Only how the data is fetched.
- If issue X-6 (indexes) has not shipped, note in the PR that these fixes reduce query
  COUNT while X-6 reduces per-query COST. Both are needed; neither substitutes.

TESTS (required, per PR)
1. A regression test asserting identical output before and after. Snapshot the response
   for a realistic fixture and assert it is unchanged.
2. A query-count assertion. This is the test that actually proves the fix and prevents
   regression — count the queries issued (SQLAlchemy event hooks make this
   straightforward) and assert it does not scale with the collection size.
3. The existing suites for each touched area must stay green.

VERIFY
cd backend && .venv/bin/python -m pytest -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

---

<a id="x-9"></a>
## X-9 — Chat resends the full history every turn and runs ~50 CRM queries per message

**S3 · AGENT · effort M**

`api/chat.py:118-124` loads the **entire** conversation and sends it every turn. `api/chat.py:128` calls `build_student_context` → `get_student_crm` (`services/student_crm.py:76-170`) — roughly **50 queries per chat message**.

- 400 students × 5 messages/day × 50 = **100,000 queries/day** for chat grounding alone. At 2,000 students, 500,000/day.
- Conversation cost is quadratic: Σᵢ(i × ~150 tok) ≈ N²/2 × 150. At the 50-message daily cap that is **187,500 input tokens for one conversation**. There is no truncation and no cap on conversation *length* — only on messages per day.
- `chat_messages.conversation_id` has **no index** (`models/chat.py:36`), and both `chat.py:74` and `chat.py:120` are `WHERE conversation_id = ? ORDER BY id` — a full table scan, twice per message.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (FastAPI + SQLAlchemy 2 async).
Make the AI chat endpoint affordable at scale.

THREE COMPOUNDING DEFECTS

1. FULL HISTORY EVERY TURN — quadratic token cost
   api/chat.py:118-124 loads the entire conversation and sends all of it on every turn.
   Cost grows as N^2/2 x tokens-per-message. At the existing 50-message daily cap that is
   ~187,500 input tokens for one conversation. There is a cap on messages per DAY
   (api/chat.py:35) but none on conversation LENGTH, and no truncation anywhere.

2. ~50 QUERIES PER MESSAGE for grounding
   api/chat.py:128 calls build_student_context -> get_student_crm
   (services/student_crm.py:76-170), which is the full Student CRM aggregation. At 400
   students x 5 messages/day that is 100,000 queries/day for chat grounding alone;
   500,000/day at 2,000 students.

3. NO INDEX on chat_messages.conversation_id
   models/chat.py:36. Both api/chat.py:74 and :120 are
   WHERE conversation_id = ? ORDER BY id — a full table scan, twice per message.

WHAT TO CHANGE

Defect 3 first — it is trivial and helps immediately. Add the index (model AND
hand-written migration per DB-15/16/17, declared in both per DB-12). If issue X-6 has
already shipped this index, skip it.

Defect 1: send a bounded window of recent history rather than everything. Around 20
messages is a reasonable default; make it configurable and comment the choice. Preserve
conversational continuity — a hard truncation mid-exchange reads badly. Consider keeping
the first user turn (which usually carries the topic) plus the last N.

Defect 2: cache the student context. It changes on the timescale of homework being marked,
not on the timescale of chat turns, so a short TTL is safe. Options: an in-process TTL
cache (consistent with how rate_limit.py already handles per-instance state, and carrying
the same per-instance caveat — document it), or a lighter-weight context builder for chat
that queries only what the prompt actually uses. Read services/student_context.py to see
what is actually consumed before caching the whole CRM aggregation — it may be far less
than 50 queries' worth.

CONSTRAINTS
- Do NOT weaken the grounding. The point of build_student_context is that the AI and the
  UI never show different numbers (services/student_context.py's docstring says so
  explicitly). A cache with a short TTL preserves that; a reduced context might not.
  If you build a lighter context, prove it contains everything the prompt uses.
- Do not change the guardrails in services/tutor_chat.py or services/prompts.py. The
  "teaches and guides, never hands over complete homework answers" rule is a product
  requirement. If the prompt text must change, AI-7 requires a version bump.
- Keep the tutor Knowledge Base injection as its own cached system block — it is
  deliberately separate so provider-side prompt caching can work on it.
- Do not change the 50-message daily cap.
- Streaming must keep working. Note issue X-12: the endpoint currently holds a DB session
  open for the whole streamed reply. If you are already in this file, consider fixing that
  too — but say so, and keep the tests separable.

TESTS (required, backend/tests/test_chat.py)
1. A long conversation sends a bounded number of history messages, not all of them.
2. Replies still reference the student's real readiness data (grounding regression) —
   this is the test that proves the context change was safe.
3. The context cache returns fresh data after its TTL, and does not leak one student's
   context into another's request. Write the second one deliberately; a cache keyed wrong
   is a data-leak bug, not a performance bug.
4. Query count per message drops measurably — assert it.
5. Use fake_ai, patch the calling module (QA-7), never call a real provider (QA-8).

VERIFY
cd backend && .venv/bin/python -m pytest tests/test_chat.py -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

---

<a id="x-10"></a>
## X-10 — 36 unbounded list endpoints; zero accept `limit` or `offset`

**S3 · AGENT · ↔ AV-25 · effort L**

Confirmed exhaustively: across `backend/app/api/`, the only `.limit()` calls are `.limit(1)`, and the only `Query()` parameter in the entire API is `group_by` on `ai_usage.py:64`. **No endpoint accepts `limit`, `offset`, `page` or `cursor`.**

The five worst, by growth × frequency:

1. **`GET /readiness/students/{id}/trend`** (`readiness.py:143-155`) — every `ReadinessSnapshot` ever written, per subject. At 80 snapshots/student/year × 3 subjects × 3 years = **720 points**, rendered as a chart.
2. **`GET /me/assignments`** (`submissions.py:221`) — 1+5A queries and A rows, where A grows monotonically forever.
3. **`GET /submissions/review-queue`** (`submissions.py:400`) — 1+2N queries; N is the tutor's entire un-reviewed backlog, rendered without virtualization at `HomeworkOverviewPage.tsx:41`.
4. **`GET /assignments/attention`** (`assignments.py:262-280`) — every `ai_failed`/`ai_marked`/`needs_review` submission in the org, ever. Never shrinks unless the tutor works the queue to zero.
5. **`GET /students/{id}/crm`** (`student_crm.py:147-160`) — every `TutorNote` and `ParentCommunication` for the student's entire history.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (FastAPI + React + TanStack
Query). Add pagination to the list endpoints that will actually grow.

VERIFIED CURRENT STATE
Across backend/app/api/, the only .limit() calls are .limit(1), and the only Query()
parameter in the entire API is `group_by` on api/ai_usage.py:64. NO endpoint accepts
limit, offset, page or cursor. 36 endpoints return unbounded collections.

SCOPE — do the five that matter, not all 36. Most of the rest are naturally bounded
(a tutor has a handful of groups; a student a handful of subjects). Paginating those adds
API surface and frontend complexity for nothing.

THE FIVE, in order:
1. GET /readiness/students/{id}/trend  (api/readiness.py:143-155)
   Returns every ReadinessSnapshot ever written, per subject. ~80/student/year x 3
   subjects x 3 years = 720 points, rendered as a chart. A chart does not need 720 points
   — this one arguably wants time-window filtering (last 90 days) more than offset
   pagination. Think about what the UI actually needs before picking a mechanism.
2. GET /me/assignments  (api/submissions.py:221)
   Grows monotonically forever, and is 1+5A queries (issue X-8).
3. GET /submissions/review-queue  (api/submissions.py:400)
   N is the tutor's entire unreviewed backlog, rendered without virtualization at
   frontend/src/tutor/HomeworkOverviewPage.tsx:41.
4. GET /assignments/attention  (api/assignments.py:262-280)
   Every ai_failed/ai_marked/needs_review submission in the org, ever. Never shrinks
   unless the tutor works the queue to zero.
5. GET /students/{id}/crm  (services/student_crm.py:147-160)
   Every TutorNote and ParentCommunication for the student's whole history. Note that
   issue S-1 makes these tutor-only; if that has shipped, this is a tutor-facing
   pagination problem only.

WHAT TO CHANGE
1. Pick ONE pagination style and use it everywhere. Read
   docs/volume-2-application-engineering/05-api-standards.md first — if it specifies a
   convention, follow it; if it does not, establish one and ADD it to that document
   (GOV-1). Cursor-based is better for append-heavy feeds; limit/offset is simpler and
   fine for the rest. Do not mix.
2. Default limits must be sensible without a client asking, and there must be a hard
   maximum a client cannot exceed.
3. Update the mirroring TypeScript interfaces in frontend/src/api/*.ts IN THE SAME PR.
   FE-4/API-15 require this, and nothing checks the two agree (RISK-6) — so if you skip
   it, the failure is silent `undefined` in the UI.
4. Update the consuming components to handle paged responses. Do not leave a component
   silently rendering only the first page while looking complete — that is a worse bug
   than the one you are fixing.

CONSTRAINTS
- This CHANGES THE API CONTRACT. Every consumer of a paginated endpoint must be updated in
  the same PR. Grep for each endpoint's client wrapper before you start.
- Consider doing one endpoint per PR. Five endpoints x (backend + types + component +
  tests) is a large diff and a risky review.
- Do not add pagination to endpoints that are naturally bounded.
- Do not fix the N+1 patterns here — that is issue X-8. Pagination reduces rows returned;
  it does not fix 5 queries per row.
- Frontend virtualization is a separate concern (issue X-11). Pagination first; it makes
  virtualization unnecessary for most of these.

TESTS (required, per endpoint)
1. Default limit applies when no parameter is given.
2. limit and offset (or cursor) work, and the hard maximum is enforced.
3. An out-of-range or malformed parameter returns 422, not a 500 and not silently
   ignored.
4. The frontend renders paged data correctly and can reach page 2.
5. Existing callers still work (regression) — this is the one that catches a missed
   consumer.

VERIFY
cd backend && .venv/bin/python -m pytest -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
cd frontend && npm test && npm run build && npm run lint
```

---

<a id="x-11"></a>
## X-11 — No refresh coalescing, no `staleTime`, no virtualization, and an unconditional 5-second poll

**S3 · VERIFIED · ↔ AV-33 · effort M**

Four frontend scale defects, all cheap to fix:

**No refresh coalescing.** `frontend/src/api/client.ts:210-213` calls `refreshTokens()` directly on any 401, with no shared in-flight promise. `frontend/src/api/chat.ts:55-58` reimplements the same retry logic a second time, independently. `TodayDashboard.tsx:29-43` fires `lessons`, `groups`, `attention` plus one `groupAnalytics` per group via `useQueries` — all in parallel on mount. On a stale token every one of those 401s and independently POSTs `/auth/refresh`.

Today this is a 6× multiplier, not a correctness bug: `api/auth.py:129-147` does not rotate or invalidate the previous refresh token. **It becomes a correctness bug the moment refresh-token rotation is added** — which is a standard hardening step, and the direction the existing `token_version` machinery already points. The second and later concurrent refreshes would fail as revoked and log the user out on an ordinary dashboard load.

**No QueryClient defaults.** `main.tsx:9` is `new QueryClient()` — `staleTime: 0`, `refetchOnWindowFocus: true`. Every remount and every window focus refetches everything, including the 1+2N review-queue scan. Exactly one component sets `staleTime` (`TodayDashboard.tsx:41`). This is also the amplifier behind D-1.

**Zero virtualization.** No `react-window`, `react-virtual`, `virtuoso` or `useVirtualizer` anywhere in the frontend. Every list is a plain `.map`.

**Unconditional polling.** `AssignmentDetailPage.tsx:52` sets `refetchInterval: 5000` with no stop condition — one tutor with the tab open is 720 requests/hour against the 1+2N submissions endpoint.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (React 18 + TypeScript +
TanStack Query). Four frontend scale fixes. Consider one PR each — they are independent.

FIX 1 — COALESCE TOKEN REFRESH (do this one first)
frontend/src/api/client.ts:210-213 calls refreshTokens() directly on any 401, with no
shared in-flight promise. frontend/src/api/chat.ts:55-58 reimplements the same
"401 -> refresh -> retry once" logic independently, a second time.
frontend/src/tutor/today/TodayDashboard.tsx:29-43 fires lessons, groups, attention plus
one groupAnalytics per group via useQueries, all parallel on mount — so a stale token
produces N simultaneous POSTs to /auth/refresh.

Today this is a 6x multiplier, not a correctness bug: backend api/auth.py:129-147 does not
rotate or invalidate the previous refresh token, so parallel refreshes all succeed. It
BECOMES a correctness bug the moment refresh-token rotation is added — a standard
hardening step that the existing token_version machinery already points toward — because
the second and later concurrent refreshes would fail as revoked and log the user out on an
ordinary dashboard load.

Fix: a module-level in-flight promise in client.ts —
`let refreshInFlight: Promise<StoredTokens | null> | null` — so concurrent 401s await one
refresh. Then make chat.ts call that same coalesced function instead of duplicating the
logic. Clear the in-flight reference in a finally block so a failed refresh does not
poison every later attempt.

FIX 2 — QUERYCLIENT DEFAULTS
frontend/src/main.tsx:9 is `new QueryClient()` with no defaultOptions, so staleTime is 0
and refetchOnWindowFocus is true. Every remount and every window focus refetches
everything, including the 1+2N review-queue scan. Exactly one component sets staleTime
(TodayDashboard.tsx:41).
Fix: set sensible defaults. Choose staleTime per data volatility — readiness scores change
on the timescale of homework being marked, not seconds. Leave refetchOnWindowFocus on
where freshness genuinely matters and off where it does not; document the choice in a
comment.
NOTE: this is the amplifier behind issue D-1 (tutor loses typed marks on refocus). It is
NOT the fix for D-1 — the dirty guard is. Do not let this substitute for it.

FIX 3 — VIRTUALIZATION
No react-window / react-virtual / virtuoso / useVirtualizer anywhere in the frontend; every
list is a plain .map. The ones that will actually exceed a few hundred rows:
  frontend/src/tutor/HomeworkOverviewPage.tsx:41,83 (review queue)
  frontend/src/tutor/PastPapersPage.tsx:140-165 (grows every term, org-wide)
  frontend/src/student/TutorChatPage.tsx:145 (chat history)
Fix: prefer PAGINATION (issue X-10) over virtualization — it fixes the backend cost too,
where virtualization only fixes rendering. Add virtualization only where pagination is a
poor fit, e.g. chat history.

FIX 4 — UNCONDITIONAL POLL
frontend/src/tutor/AssignmentDetailPage.tsx:52 sets refetchInterval: 5000 with no stop
condition. One tutor with the tab open is 720 requests/hour against a 1+2N endpoint.
Fix: stop polling once the thing being awaited has settled (extraction complete, marking
done). Read what the page is actually waiting for and make the interval conditional on it.
Consider backing off, and stopping entirely when the tab is hidden.

CONSTRAINTS
- Do not change the token storage design (access token in localStorage, refresh token in
  an httpOnly cookie). It is deliberate and documented (SEC-2/FE-2).
- api/client.ts is the ONE HTTP entry point (FE-1). Its only sanctioned bypasses are
  fetchFileUrl() for blobs and streamMessage() for SSE. Fix 1 should REDUCE the
  duplication in chat.ts, not add more.
- Server data lives in TanStack Query, not copied into useState (FE-6).
- Do not touch backend code in any of these.

TESTS (required, frontend/src/test/)
Fix 1: N concurrent 401s trigger exactly ONE refresh call; all N requests then succeed; a
failed refresh does not leave the in-flight promise stuck.
Fix 2: defaults are applied; a component with its own staleTime still overrides.
Fix 3: a large list renders without mounting every row.
Fix 4: polling stops once the awaited condition is met.

VERIFY
cd frontend && npm test
cd frontend && npm run build
cd frontend && npm run lint
```

---

<a id="x-12"></a>
## X-12 — The DB session is held open for the full duration of a streamed chat reply

**S3 · AGENT · effort S**

`backend/app/db.py:22-24` — `get_db` is a `yield`-based dependency. FastAPI does not tear down a `yield` dependency until the whole response has finished sending, **including a `StreamingResponse` body**.

`api/chat.py`'s `send_message` takes `DbSession` and returns a `StreamingResponse`. So the request-scoped session — and one pooled connection — is held for the entire duration of the LLM's streamed reply, which can run for tens of seconds. The generator itself only needs `db` via closures created before streaming starts, and already opens a *second*, correctly short-lived session at the end of `event_stream` to persist the reply.

With the default pool of 5+10 (X-3) on a single instance, a modest number of concurrent chat sessions exhausts the pool and starts timing out unrelated requests — marking, dashboards, and the worker's own database access.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (FastAPI + SQLAlchemy 2 async).
Stop holding a database connection for the duration of a streamed AI reply.

THE DEFECT
backend/app/db.py:22-24 — get_db is a yield-based dependency:
    async def get_db() -> AsyncIterator[AsyncSession]:
        async with async_session() as session:
            yield session

FastAPI does not tear down a yield-dependency until the entire response has finished
sending — and that INCLUDES a StreamingResponse body.

api/chat.py's send_message takes DbSession and returns a StreamingResponse wrapping
event_stream(). So the request-scoped session, and one pooled connection, is held for the
whole streamed reply — tens of seconds. Meanwhile the generator only uses `db` via
closures created before streaming begins, and already opens a SECOND, correctly
short-lived session at the end of event_stream to persist the reply.

With SQLAlchemy's default pool (5 + 10 overflow; see issue X-3, nothing is configured) on
a single instance that also runs the job worker, a modest number of concurrent chat
sessions exhausts the pool and starts timing out unrelated requests.

WHAT TO CHANGE
In backend/app/api/chat.py's send_message: do not take DbSession as a dependency. Instead
open a short-lived session explicitly, read everything the stream needs (conversation
history, student context, knowledge base, the daily-limit check, the user message write),
close it, and only then construct the StreamingResponse.

The pattern is already in this file — event_stream's post-stream save opens its own
`async_session()`. Follow it for the pre-stream reads.

CONSTRAINTS
- The daily message limit (api/chat.py:35, DAILY_MESSAGE_LIMIT = 50) must still be checked
  and enforced BEFORE the stream starts. Do not let this refactor move the check after the
  AI call.
- The user's message must still be persisted before streaming, so a dropped connection
  does not lose it.
- AI usage metering must still work. services/tutor_chat.py fills a `usage` dict once the
  stream finishes, and the caller meters it with its own fresh session — that design
  exists precisely because the request session may be gone. Preserve it.
- Do not change the streaming protocol or the SSE event shape. The frontend depends on it.
- If issue X-3 has shipped (explicit pool sizing), this fix is still needed — widening the
  pool raises the ceiling, it does not stop a connection being held for 30 seconds.
- Check whether any OTHER endpoint returns a StreamingResponse while taking DbSession.
  If so, fix those too and list them in the PR.

TESTS (required, backend/tests/test_chat.py)
1. Streaming a reply works end to end and persists the assistant message (regression).
2. No session is held during the stream. Assert it directly — e.g. check the pool's
   checked-out count from inside the fake AI stream, or assert get_db is not a dependency
   of the route.
3. The daily limit is still enforced before the stream starts, and the 51st message of the
   day is rejected without an AI call.
4. AI usage is still metered for a streamed reply.
5. Use fake_ai; never call a real provider (QA-8).

VERIFY
cd backend && .venv/bin/python -m pytest tests/test_chat.py tests/test_ai_usage.py -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

---

<a id="x-13"></a>
## X-13 — Four tables grow forever with no retention

**S4 · DERIVED · ↔ AV-28 · effort M**

| Table | Rows per student/year | @2,000 students/year | Retention |
|---|---|---|---|
| **`factor_evaluations`** | 80 recomputes × 40 rows = **3,200** | **6.4 M rows ≈ 2–3 GB** (JSON `detail`) | **none** |
| `chat_messages` | ~1,100 | 2.2 M | none |
| `ai_usage_events` | ~600 | 1.2 M | none |
| `jobs` | ~300 | 600 k (with JSON payloads) | **none — `done`/`failed` never pruned** |
| `readiness_history` | ~100 | 200 k | none |
| `evidence` | ~400 | 800 k | none |
| `mark_override_audit` | ~300 | 600 k | none — **correct, by design** |

`factor_evaluations` is the one to watch: `readiness_v2.py:407-409` appends 40 rows per run (33 topic_mastery + 6 subject-level + 1) and never updates. The `PUT /weights` amplifier (X-2) alone can add ~4,800 rows per tutor per slider save.

The append-only design is **architecturally correct** — `models/readiness_v2.py:202-205` requires that a historical AI synthesis stay reconstructable from its exact inputs. The gap is that nothing archives it. On `basic-256mb` Postgres (`render.yaml:11`), 2–3 GB/year in one table exhausts shared_buffers and turns every query in the database into disk I/O.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (Postgres + Alembic). Add data
retention. This is a DESIGN-then-implement task: get the policy agreed before writing code.

THE GROWTH, modelled from verified code constants
  factor_evaluations   40 rows per recompute (readiness_v2.py:407-409: 33 topic_mastery +
                       6 subject-level + 1). ~80 recomputes/student/year = 3,200
                       rows/student/year. At 2,000 students: 6.4M rows, ~2-3 GB with the
                       JSON `detail` column. NO retention.
  chat_messages        ~1,100/student/year. At 2,000 students: 2.2M. NO retention.
  ai_usage_events      ~600/student/year. 1.2M. NO retention.
  jobs                 ~300/student/year. done/failed rows are NEVER pruned, and each
                       carries a JSON payload.
  readiness_history    ~100/student/year. NO retention.

The database plan is `basic-256mb` (render.yaml:11). 2-3 GB in one table exhausts
shared_buffers and turns every query in the database into disk I/O.

READ THIS BEFORE DESIGNING
factor_evaluations is append-only BY DESIGN. models/readiness_v2.py:202-205 states that a
historical AI synthesis must always be reconstructable from the exact FactorEvaluation
rows it was built from. That is a real product guarantee about explainability — PROD-1
("no metric exists unless MANARA can explain where it came from") depends on it.

So retention here is NOT "delete old rows". It is "how long must a synthesis stay
reconstructable, and where do the inputs live after that". Those are different questions
and the second one has an answer (archive) that preserves the guarantee.

STEP 1 — WRITE THE POLICY FIRST
A short document under docs/, per table:
  - How long must this data be reconstructable/queryable, and why?
  - What happens after that: delete, archive to object storage, or aggregate-then-delete?
  - Who decides? Some of these are product questions (how far back can a tutor see a
    student's readiness history?) and some are legal (see issue S-13's erasure work).
Do not guess on the product questions. State the options and their consequences and let
the owner choose.

STEP 2 — IMPLEMENT, once the policy is agreed
1. jobs is the easy win and needs no policy debate — prune done/failed rows older than a
   short window. Do this one first regardless. It also fixes issue X-14 (/health/ready
   full-scans this table).
2. factor_evaluations: monthly partitioning on created_at with old partitions detached and
   archived, OR archive-to-object-storage. Partitioning is the more invasive change but
   makes the drop free. Weigh both.
3. Retention runs as a job handler, registered in main.py like every other
   (BE-2 — every workflow is a job handler). It must be idempotent (BE-6) and must not
   monopolize the serial worker — batch the deletes and yield between batches.
4. Hand-write migrations per DB-15/DB-16/DB-17.

CONSTRAINTS
- Do NOT make factor_evaluations updatable. Append-only is the guarantee.
- Do NOT add retention to mark_override_audit. It is the tutor-authority audit trail and
  is deliberately permanent (models/homework.py:252-256, PROD-7/AI-12). Leave it.
- Deleting readiness or evidence data changes what the product can show a user. That is a
  product decision, not a cleanup task.
- Coordinate with issue S-13 (data erasure). Retention and erasure touch the same tables
  and should not be designed independently.
- A retention job that deletes the wrong thing is unrecoverable. Every delete needs a
  dry-run mode and a row-count log before it runs for real.

TESTS (required)
1. The retention job deletes exactly what the policy says and nothing else.
2. It is idempotent — running twice is safe (BE-6).
3. Data inside the retention window is untouched.
4. Dry-run mode deletes nothing and reports accurate counts.
5. Drive with process_one_job() (QA-6).

VERIFY
cd backend && .venv/bin/python -m pytest -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .

Then update docs/volume-2-application-engineering/06-database-design.md and
docs/volume-4-reliability-and-operations/14-operations-runbooks.md (GOV-1).
```

---

<a id="x-14"></a>
## X-14 — `/health/ready` full-scans `jobs` and will report a false outage

**S4 · AGENT · effort XS**

`backend/app/main.py:154` — `select(Job.status, func.count(Job.id)).group_by(Job.status)` is a full scan of `jobs`. Nothing prunes `done` or `failed` rows.

At ~600 k rows with JSON payloads this exceeds `READINESS_DB_TIMEOUT_SECONDS = 5.0` (`main.py:143`), and the endpoint returns `database: {ok: false, error: "TimeoutError"}` — a false database outage caused entirely by table growth. The irony is sharp: the 5-second bound was added specifically so a hung database would be *reported* rather than waited out, and it will end up reporting a healthy database as dead.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (FastAPI + Postgres).
Stop the readiness health check from becoming a false alarm as the jobs table grows.

THE DEFECT
backend/app/main.py:154 in _queue_snapshot():
    select(Job.status, func.count(Job.id)).group_by(Job.status)
This is a full scan of `jobs`. Nothing prunes done/failed rows, so the table grows without
bound (~300 rows per student per year, each with a JSON payload).

At roughly 600k rows the scan exceeds READINESS_DB_TIMEOUT_SECONDS = 5.0 (main.py:143) and
/health/ready returns `database: {ok: false, error: "TimeoutError"}` — reporting a false
database outage caused purely by table growth.

The 5-second bound was added deliberately so a hung database would be REPORTED rather than
waited out (read the comment at main.py:238-243). It will end up reporting a healthy
database as dead.

TWO FIXES — do both, they are complementary
1. Make the query cheap. `ix_jobs_status_run_after` on (status, run_after) already exists
   from migration 0018 and can serve a status-grouped count as an index-only scan, but
   only if the query lets it. Check the plan. If a count of terminal states is what makes
   it expensive, consider counting only the states the health check actually cares about —
   pending, running, failed — rather than grouping over everything including the millions
   of `done` rows.
2. Prune terminal jobs. This is the real fix and is part of issue X-13. If X-13 has not
   started, doing the `jobs` table alone here is entirely reasonable and needs no policy
   debate — a completed job row has no value after a short window. Say in the PR that you
   are doing the easy slice of X-13.

CONSTRAINTS
- Do NOT raise READINESS_DB_TIMEOUT_SECONDS to paper over it. The bound is correct; the
  query is the problem.
- Do NOT move this to /api/v1/health. That endpoint is deliberately DB-free because it is
  what render.yaml:26 polls, and a database round-trip there would turn a blip into a
  restart loop and a failed deploy. The comment at main.py:205-219 explains this; it is
  hard-won and must not be undone.
- /health/ready must keep reporting queue depth and oldest-pending age. Those are the
  signals that make a dead worker visible (RISK-4). Making the query cheaper must not make
  it less informative.
- If you add a retention job, it must be idempotent (BE-6) and registered as a handler in
  main.py like every other (BE-2).

TESTS (required, backend/tests/test_health.py, test_jobs.py)
1. /health/ready still returns correct queue counts.
2. It still reports degraded when the worker is dead (regression — this is RISK-4).
3. The pruning job removes only terminal jobs older than the window, and is idempotent.
4. Pending and running jobs are never pruned.

VERIFY
cd backend && .venv/bin/python -m pytest tests/test_health.py tests/test_jobs.py -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

---

<a id="x-15"></a>
## X-15 — The single-instance ceiling, and the forced order of lifting it

**S4 · DERIVED · ↔ AV-27 · effort XL**

Three constraints pin the API to one instance. `CLAUDE.md` and `rate_limit.py:1-8` both identify them correctly.

**But the ordering claim in `rate_limit.py:6-8` — that moving the rate limiter is "the same moment `services/storage.py` has to move to S3" — is wrong.** The order is forced, and storage must go first.

| Pin | Where | Why it pins |
|---|---|---|
| Uploads disk | `render.yaml:34-37`, `services/storage.py:94-97,146-166` | A Render service with a disk runs one instance, full stop |
| In-process worker | `main.py:110` | The *claim* is already safe for N workers (`jobs.py:184` uses `FOR UPDATE SKIP LOCKED`); what is not safe is `jobs.py:62-69`, where `_started_at`, `_last_loop_at`, `_job_started_at` and `_restart_times` are module globals — with 2 instances `/health/ready` reports whichever process the load balancer picked |
| Rate limiter | `rate_limit.py:29,71` | `_hits` is a process-global dict; with N instances the effective limit is `10 × N` |

### The forced order

**Step 1 — uploads to S3/R2. Must be first.** Nothing else is possible until this lands: a separate worker service cannot mount the same Render disk, and `mark_submission` calls `storage.read_file`. Rewrite five functions in `storage.py`; convert six `FileResponse` call sites to presigned URLs. **No row migration** — paths are already relative, and `storage.py:1-3` says that was the point. *2–3 days, ~$5/mo.* Bonus: presigned URLs take file streaming off the event loop entirely.

**Step 2 — worker to its own Render service.** This is where the throughput fix lives. Same image, `type: worker`, different command. Move the health globals into a `worker_heartbeat` table so `/health/ready` still means something. Run N=4. *1–2 days, +$7–25/mo.* Effect: the 30-student burst tail drops from **12.5 min → ~3 min**; evening capacity goes 300 → 1,200 submissions.

**Step 3 — rate limiter to Postgres.** A `login_attempts(identifier, window_start, count)` table with an upsert, preserving the per-identifier semantics `SEC-14` requires. *Half a day, $0.*

**Step 4 — scale the API.** Only now can `numInstances` exceed 1. Simultaneously set explicit pool sizing (X-3) and **upgrade the database** — `basic-256mb` will not accept 3 API × 15 + 4 workers × 15 = 105 connections. Larger plan, or PgBouncer in transaction mode. *1 day + $20–50/mo.*

**Total: roughly one week of engineering and $50–100/month**, taking the hard ceiling from 15 concurrent requests and 80 jobs/hour to roughly 45 concurrent requests and 320 jobs/hour.

```
The repository is the Avora / MANARA "IGCSE-OS" platform (FastAPI + Postgres, deployed on
Render with a mounted disk; frontend on Vercel).

THIS IS A MULTI-PR PROGRAMME, NOT ONE TASK. Read it all, then do STEP 1 only. Do not
attempt the whole thing in one branch.

THE THREE PINS holding the API to a single instance:
1. Uploads disk — render.yaml:34-37 mounts a persistent disk at /data, and a Render
   service with a disk runs exactly one instance. services/storage.py:94-97,146-166
   reads and writes it directly.
2. In-process job worker — main.py:110 starts it in the API lifespan.
3. In-process rate limiter — services/rate_limit.py:29,71, a process-global dict.

A CORRECTION TO THE EXISTING DOCUMENTATION, which you will otherwise be misled by:
the comment at services/rate_limit.py:6-8 says moving the rate limiter is "the same moment
services/storage.py has to move to S3". That is wrong. The order is forced and storage
must go FIRST — nothing else is possible until it lands, because a separate worker service
cannot mount the same Render disk. Fix that comment as part of step 1.

Also note what is ALREADY correct and must not be "fixed": jobs.py:184 claims with
SELECT ... FOR UPDATE SKIP LOCKED, so multiple workers are already safe. That was built
for this. What is NOT safe is jobs.py:62-69, where _started_at, _last_loop_at,
_job_started_at and _restart_times are module globals — with two instances /health/ready
reports whichever process the load balancer happened to pick.

=== STEP 1 — UPLOADS TO OBJECT STORAGE (do this now; the rest is blocked on it) ===

Move file storage from local disk to S3-compatible object storage (S3, or Cloudflare R2).

1. Rewrite the five functions in backend/app/services/storage.py: upload_root, _write,
   delete_file, read_file, absolute_path. Keep the module's public interface identical if
   at all possible — 20+ call sites depend on it.
2. NO DATABASE MIGRATION IS NEEDED. Paths are already stored relative to UPLOAD_DIR, and
   storage.py:1-3 says explicitly that this was the point: "the whole folder can move to
   object storage (S3) later without touching rows." Verify that claim holds before
   relying on it, then rely on it.
3. Convert the six download endpoints from FileResponse to presigned URLs:
   api/submissions.py:493, api/classifieds.py:93,110, api/past_papers.py:232,247,
   api/resources.py:117.
   Presigned URLs must be short-lived, and the authorization check must still run before
   one is issued — the URL is the capability, so issuing it IS the authorization decision.
   Do not let this become a way to bypass the ownership checks those endpoints perform.
4. Plan the migration of EXISTING files off the disk. Write it as a one-off script with a
   dry-run mode and a verification pass. Do not delete anything from the disk until the
   copy is verified.
5. Remove the disk from render.yaml only AFTER the copy is verified and deployed.

BONUS, worth calling out: presigned URLs remove file streaming from the event loop
entirely, which is part of issue X-7.

CONSTRAINTS FOR STEP 1
- Uploads must keep their existing validation: magic-byte checking, the 20 MB cap on
  source bytes, server-generated filenames (SEC-15/16/17). Do not lose any of it in the
  rewrite.
- Test-suite compatibility: tests must not require real object storage. Provide a local
  or in-memory backend for tests, selected the same way db.py selects the SQLite path.
- If issues S-6 (buffered read before size check) and S-7 (HEIC pixel guard) have shipped,
  preserve both.
- Do not change the worker, the rate limiter, or numInstances in this PR.

TESTS FOR STEP 1
1. Upload, retrieve and delete work against the storage backend.
2. All existing upload/download tests pass unchanged (regression) — this is the main net.
3. Presigned URL generation still enforces the same authorization as the FileResponse
   endpoints did. Write the negative case: a user who could not download before still
   cannot get a URL (QA-12).
4. The file-migration script is idempotent and its dry run reports accurate counts.

VERIFY
cd backend && .venv/bin/python -m pytest -q
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .

=== STEPS 2-4 — SUMMARY ONLY. Do NOT start these now. ===

STEP 2 — worker to its own Render service, N=4 concurrency. Move the health globals into a
worker_heartbeat table. This is issue X-4 and has its own prompt. Effect: 30-student burst
tail drops from ~12.5 min to ~3 min; evening capacity 300 -> 1,200 submissions.
~1-2 days, +$7-25/mo.

STEP 3 — rate limiter to Postgres. A login_attempts(identifier, window_start, count) table
with an upsert, preserving the per-identifier semantics SEC-14 requires (per-IP would mean
a global lockout behind the proxy). ~half a day, $0.

STEP 4 — scale the API above one instance. Requires explicit pool sizing (issue X-3) AND a
database upgrade: basic-256mb will not accept 3 API x 15 + 4 workers x 15 = 105
connections. Larger plan or PgBouncer in transaction mode. ~1 day, +$20-50/mo.

TOTAL: ~1 week of engineering and $50-100/month, taking the ceiling from 15 concurrent
requests and 80 jobs/hour to roughly 45 concurrent requests and 320 jobs/hour.

After each step, update docs/volume-3-platform-engineering/08-infrastructure-and-deployment.md
and docs/governance/risk-register.md (RISK-1), per GOV-1.
```

---

# Suggested sequencing

**Ship today — five hours total, and it removes the two largest cost drivers and three live data defects.**

| Order | Issue | Why first |
|---|---|---|
| 1 | **X-1** | One environment variable. Cuts AI spend 48%. Zero code, zero risk. |
| 2 | **S-1** | A student can read their tutor's private notes about them. Small fix. |
| 3 | **D-1** | Tutors are losing typed marks right now. Copy the pattern from the sibling page. |
| 4 | **S-2**, **S-3** | Two missing `Field(le=...)` bounds that silently corrupt grades. |
| 5 | **X-3** | Explicit pool config is two hours; the session-release refactor can follow. |

**This week**

S-6, S-7, S-9 (bounded input and spend), D-2 (the delete endpoint is broken today), D-7 (job timeout), X-6 (indexes — one migration), X-14 (prune `jobs`).

**This month**

S-4, S-5, S-8, S-10, S-11 (the remaining security bounds), D-4, D-5, D-6, D-9, D-12 (integrity), X-5, X-7, X-11, X-12 (the cheap scale fixes).

**The architectural work, in this order and no other**

X-15 step 1 (S3) → X-4 / X-15 step 2 (worker service) → X-15 step 3 (rate limiter) → X-15 step 4 (scale out). Then X-8, X-9, X-10, X-13 as capacity allows.

**Separately, and needing a human decision rather than an agent**

S-13 (erasure and retention policy) and X-13's policy step. Both are product and legal questions before they are engineering ones.

---

## Two notes on using this register

**On the S0/S1 prompts.** Every prompt that touches grading — S-2, S-3, D-1, D-6 — requires a regression test as a deliverable, not as a nicety. That is deliberate. It gives a human reviewer something concrete to check on a change whose failure mode is a wrong number on a child's record that nobody notices for a term.

**On what the agents were told not to do.** Each prompt lists constraints, and several of them forbid changes that look like obvious improvements — don't clamp silently, don't widen the pool instead of releasing the connection, don't make `factor_evaluations` updatable, don't put a database call in `/health`. Those constraints encode reasoning that already exists in this codebase, usually in a comment that is the only surviving record of a decision (`CODE-12`, `CODE-13`). An agent that removes one will produce a green test suite and a worse system.

---

## On the quality of what's here

Two things are worth saying plainly, because a 41-item defect register reads as an indictment and this one should not.

**The codebase is unusually disciplined.** The security pass found that essentially all of the "obvious" IDOR surface is correctly closed — every `{id}` path parameter resolves through a real ownership check, the polymorphic `Submission` branch is handled correctly inside authorization (`API-20`), past papers are scoped by `(organization, subject)` rather than subject alone, invite single-use is enforced with a conditional `UPDATE` that closes the check-then-act race, uploads are validated by magic bytes rather than by the client's `Content-Type`, the prompt templates explicitly instruct the model that student page content is data and never instructions, and `tests/test_authorization.py` walks every mounted route and fails if one loses its gate. None of that is common.

**Most of what is wrong here is a bound that was never set, not a control that was never built.** `max_marks` has no ceiling; `weight` has no range; the KB body has no length; the pool has no size; the lists have no limit; the tables have no retention. The mechanisms are right and the edges are open. That is a much better position to be in than the reverse, and it is why the sequencing above starts with five hours of work rather than a rewrite.

The one genuine architectural debt is the single-instance ceiling (X-15), and the codebase already knows — `FOR UPDATE SKIP LOCKED` was written for a worker that does not exist yet, and storage paths were made relative for an S3 migration that has not happened. The groundwork is laid. It just has to be walked in the right order, and the order is not the one currently documented.
