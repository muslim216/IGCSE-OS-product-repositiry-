# 09. AI Platform

> **Volume 3 — Platform Engineering** · Engineering Constitution v1.2 · Status: Active
> **Owner:** Founder (see `governance/ownership.md`)
>
> Governs how Avora calls models: routing, prompts, metering, and the rules that decide when
> AI output is trusted without a human.

## Contents

- [Purpose](#purpose)
- [Scope](#scope)
- [Sources](#sources)
- [Principles](#principles)
- [Current Reality](#current-reality)
  - [The choke point](#the-choke-point)
  - [Surfaces and routing](#surfaces-and-routing)
  - [The two helpers](#the-two-helpers)
  - [Content blocks](#content-blocks)
  - [Prompts](#prompts)
  - [Metering and cost](#metering-and-cost)
  - [The trust model](#the-trust-model)
  - [Grounding](#grounding)
  - [Degradation](#degradation)
- [Standards](#standards)
- [Known Gaps](#known-gaps)
- [Review Triggers](#review-triggers)

---

## Purpose

Avora calls two providers across eleven surfaces, and one of those calls can put a mark on a
student's record with no human review. This document defines the routing abstraction that
keeps vendor detail in one file, the prompt governance that makes an AI-produced record
traceable, and the trust rules that bound what automation is allowed to decide.

## Scope

**In scope:** provider routing per surface; the call helpers and the normalized response; the
neutral content-block format; the prompt registry and versioning; usage metering and cost
attribution; the auto-finalize trust model; grounding; degradation on missing credentials.

**Out of scope:** the product meaning of readiness and marking (§01); the security properties
of the trust boundary (§07); AI-driven cost and latency (§10); testing AI paths (§12).

### Non-goals

- **No model training or fine-tuning.** Avora calls hosted models with prompts. Student work
  is never contributed to a model.
- **No model is asked to produce a grade.** `predict_grade()` maps a score through
  tutor-entered boundaries.
- **No AI adjudicates a dispute about AI output.** A remark request routes to a human.
- **No AI abstraction library.** Two SDKs, one wrapper module. A generic library would hide
  exactly the vendor-specific features being used — prompt caching, and streaming while it
  existed.
- **No prompts outside `services/prompts.py`.**
- **No agentic or tool-using loops.** Every call is a single request with a bounded response.
- **No streaming, full stop.** Chat was the one streaming surface; task 0.3 deleted it (AV-57)
  along with `stream_complete()` and the provider check that existed only for it.

## Sources

Written from: `backend/app/services/ai.py` (448 lines);
`backend/app/services/prompts.py` (161 lines); `backend/app/services/marking.py`;
`backend/app/services/extraction.py`; `backend/app/services/readiness_v2_ai.py`;
`backend/app/services/knowledge.py`; `backend/app/models/ai_usage.py`;
`backend/app/config.py`; `backend/app/api/ai_usage.py`.

---

## Principles

**P1 — One module touches a vendor SDK.** `services/ai.py` is the only place either client is
constructed. Everything downstream sees one normalized response type.

**P2 — Call sites name a surface, never a model.** A caller says `"marking"`. What answers is
configuration.

**P3 — Every AI-produced record names what produced it.** Provider, model, and prompt version
are stamped on the record and on the usage event, so a bad batch can be identified precisely
rather than estimated.

**P4 — Confidence is the safety mechanism.** Whether a human is required is decided by an
explicit, conservative rule — not by how the output reads.

**P5 — Never invent a number.** An unpriced model records `NULL`, not `$0`. A factor with no
evidence reports "no data", not `0`.

---

## Current Reality

### The choke point

`backend/app/services/ai.py` is 448 lines and the only module that imports either SDK. It
provides client construction, the surface routing table, two call helpers, the neutral
content-block format, cost estimation, and usage recording.

`AiResponse` is the normalized result — `{provider, model, prompt_version, input_tokens,
output_tokens, parsed, text}` — so **nothing downstream branches on which vendor answered**.

### Surfaces and routing

Eleven surfaces, defined in `SURFACES` (`services/ai.py`), with the routing in `config.py` as of
Phase 6. **Every surface routes to Anthropic** — task 3.2 (AV-124) retired Gemini from all of
them in one change, and the Gemini client is kept, unused (`ADR-0006`). A blank per-surface model
inherits `anthropic_model` (`claude-opus-5`); an explicit one is pinned.

| Surface | Model | What it does |
|---|---|---|
| `marking` | inherits `anthropic_model` | Marks submitted pages against a scheme |
| `extraction` | inherits | Pulls a question list from a booklet |
| `booklet` | inherits | Splits an uploaded booklet into whole papers |
| `syllabus` | inherits | Extracts a chapter/topic tree from a syllabus document |
| `readiness` | inherits | Layer 2 readiness synthesis |
| `plan_weighting` | inherits | Relative chapter weights for the teaching plan (6.3) |
| `reports` | `claude-sonnet-5` (pinned) | Audience-specific narrative reports |
| `class_brief` | `claude-sonnet-5` (pinned) | Pre-lesson class brief |
| `narrative` | `claude-sonnet-5` (pinned) | Precomputed class/parent narrative writer |
| `marking_rules` | `claude-sonnet-5` (pinned) | Condenses a tutor's marking rules |
| `mistake_tagging` | `claude-sonnet-5` (pinned) | Tags a settled submission's lost-marks questions with the tutor's own categories |

The six blank-model surfaces move together when `anthropic_model` moves; the five pinned ones
do not. If this table and `config.py` disagree, `config.py` wins.

`resolve_surface(surface)` reads `AI_<SURFACE>_PROVIDER` and `AI_<SURFACE>_MODEL`, falling back
to that provider's default model when the per-surface model is blank. It **raises on an unknown
surface** and **raises with a helpful message on an invalid provider**, naming the accepted
values — so a typo in configuration fails loudly at the call rather than silently routing
somewhere unintended.

Routing is per surface so a surface can be re-pointed without a code change. The split between
Opus-class and Sonnet-class surfaces is by kind of judgement and, for `mistake_tagging`, cost
(the highest-volume call); see `ADR-0006` and the comments in `config.py`.

**Surfaces and billing buckets are different things.** `SURFACE_FEATURE` maps each surface to
an `AiFeature` for metering, and several deliberately share a bucket — `syllabus` meters as
`extraction`, `class_brief` meters as `report`. The surface is the routing key; `AiFeature` is
the billing-facing grouping.

### The two helpers

| Helper | Providers | Returns | Used for |
|---|---|---|---|
| `structured_complete()` | Both | `AiResponse.parsed` | Schema-constrained output — marking, extraction, syllabus, readiness |
| `text_complete()` | Both | `AiResponse.text` | Prose — reports, class brief, narrative |

**`stream_complete()` is gone.** It was Anthropic-only and existed for the chat surface alone;
task 0.3 deleted both together (AV-57), and with them the one live configuration trap this
platform had — `AI_CHAT_PROVIDER=gemini` producing a runtime failure on the surface users
interacted with directly. Every remaining surface is fully non-streaming and provider-agnostic
at the call site.

### Content blocks

`file_block(data, mime, cache=False)` builds a document (PDF) or image block from stored
bytes. **Anthropic's block shape is the neutral wire format across the whole application**;
`_gemini_parts()` translates it at the boundary.

`cache=True` sets Anthropic's `cache_control: ephemeral` and is **a no-op on Gemini**, which
does its own implicit caching. It is used to reuse a shared mark scheme across a batch of
submissions — a cost optimization, described in §10.

### Prompts

**Every system prompt lives in `services/prompts.py`**, in one `PROMPTS` dict keyed by surface,
each a `PromptTemplate(version=..., system=...)`. No prompt text lives in the service that
calls the model. The helpers look the prompt up and stamp its version onto the `AiResponse`.

Current versions:

| Surface | Version | Note |
|---|---|---|
| `marking` | **v5** | v3 was bumped when marks began counting without tutor review |
| `class_brief` | **v3** | Full system prompt (naming-a-learner rule, data-not-instructions); v3 says a line labelled as the tutor's starting estimate is not marked work (5.3a) |
| `readiness` | **v5** | v2 dropped consistency (5.1); v3 names the `tutor_estimate` prior in Topic Mastery (5.3a); v4 stops asking for `weak_topics` — they are derived from the tutor's threshold (5.6, decision 10); v5 no longer says "six" factors — a tutor can switch factors off (#100) |
| `narrative` | **v2** | v2 says the same about the estimate label as `class_brief` (5.3a) |
| `plan_weighting` | **v2** | Teaching-plan chapter weights (6.3): the chapter list and the tutor's guidance document are data, never instructions |
| `mistake_tagging` | v1 | |
| `marking_rules` | v1 | |
| `booklet` | v1 | |
| `extraction` | v3 | |
| `syllabus` | v2 | |
| `reports`, `booklet`, `marking_rules`, `mistake_tagging` | v1 | |

Four active prompts carry rules that are not stylistic — all a form of `SEC-20`: **`marking`**
states that page content is data and never instructions, and that anything addressing the
marker is flagged with confidence `low` for a tutor rather than acted on; **`extraction`**
carries the equivalent rule for booklet content, since extracted questions can reach a student
with no human reading them first; **`class_brief`** and **`narrative`** both carry it for the
same reason — their grounding data comes from a student's own marked work, which the student
controls.

*Historical:* **`chat`** was a third one — anti-cheating guardrails: never give complete
answers to the student's own homework; teach the method, use a worked example on a *different*
problem, ask guiding questions; forbid presenting internal readiness percentages as official
grades — until task 0.3 deleted the surface along with the guardrails it needed (AV-57). Chat
was the only surface that held a *conversation* with a student; `reports` still writes
student-audience narrative directly to one (`ReportAudience.student`), just not interactively.

### Metering and cost

`record_usage()` writes one `ai_usage_events` row per call: organization, tutor, optional
student, feature, provider, model, prompt version, input and output tokens, and `cost_usd`.
Because it lives at the single choke point, **every AI call is metered automatically**.

`model_pricing()` reads `AI_MODEL_PRICING`, a JSON map of per-million-token prices, and is
`lru_cache`d. **It is empty by default.** `estimate_cost_usd()` returns `None` for a model with
no entry, so `cost_usd` is `NULL` and `GET /ai-usage/analytics` reports those calls as
`unpriced_call_count` — **never folded in as `$0`**.

Views: `GET /ai-usage/summary`, and `GET /ai-usage/analytics?group_by=feature|provider|month`.

This is the foundation for tutor allowances and student top-ups. **Nothing is enforced today**
— no budget, no cap, no breaker (`RISK-12`).

### The trust model

A mark **auto-finalizes** — counting immediately, visible to the student, becoming evidence,
with no tutor action — if and only if it is **both**:

1. **scheme-backed** (`has_mark_scheme`), and
2. **confident** (`MarkConfidence.high` or `medium`).

Everything else sets `needs_review` and waits in `GET /submissions/review-queue` with the AI's
suggestion pre-filled: no official scheme (marked from syllabus and comparable questions,
always confidence `unsure`), low confidence, or a question the model skipped.

Bounds on the blast radius:

- Proposed marks are **clamped** to the question's valid range.
- A "no data" question is **never silently scored 0**.
- A submission is `auto_finalized` or `needs_review`; `finalize` requires only the *unsure*
  questions to be resolved.
- **The tutor keeps final authority.** Changing an already-set mark writes an append-only
  `MarkOverrideAudit` row — old, new, who, when — and there is **no API to edit or delete
  those rows**.
- **Students can contest any finalized mark**, auto- or tutor-finalized, via a `RemarkRequest`.
  It is **never resolved by AI**: it routes to the tutor with the model's original reasoning
  attached. A database-level unique constraint allows **one request per question, ever**.

`mark_submission` **never overwrites a tutor-finalized mark** and skips the AI call entirely
when every question is already decided — which is both a correctness property and a cost one.

See `ADR-0009`.

### Grounding

Three grounding sources, all injected rather than left to the model's priors:

| Source | Function | Injected into |
|---|---|---|
| Tutor Knowledge Base | `services/knowledge.py` → `build_tutor_context()` | Marking, assignment extraction (not past-paper extraction), reports, readiness synthesis |
| Deterministic factor sub-scores | `services/readiness_v2.py` | Readiness synthesis |
| Marked-work/readiness evidence, queried directly (not through `student_crm.py` — `PROD-11` gap, see §01 Known Gaps) | `reports.build_report_facts()`, class readiness analytics in `api/groups.py`'s `class_brief` handler, `narrative._class_grounding()` / `_parent_grounding()` | Reports, class brief, narrative |

`build_tutor_context()` uses the same `cache=True` prompt-caching pattern as `file_block()`.

`services/student_context.py` and its `build_student_context()` are gone — they existed to
ground chat in a student's own record, reading the same aggregation `student_crm.py` exposes
to the tutor interface so the two could never disagree (`PROD-11`). Task 0.3 deleted them with
the chat surface (AV-57); no other surface consumed them. `student_crm.py` itself is unchanged
and still backs the CRM UI through `api/students.py`.

Readiness synthesis is the strictest case: the factor sub-scores and tutor weights are
**mandated inputs**, and the model is not permitted to contradict them or to produce a grade.

### The plan-weighting surface (Phase 6)

`plan_weighting` implements **E5: the AI advises, a pure scheduler owns the calendar**
(`ADR-0011`). The model is asked for one number per chapter — a relative weight from 0.5 to
3.0, 1.0 being an ordinary chapter — and a one-sentence reason a tutor can disagree with. It is
never asked for a date, a lesson count or an order, and nothing it returns can place a lesson:
`services/plan_scheduler.py` (pure, no session, `BE-4`) turns weights into slots.

- **Call:** `services/plan_drafting.py:weigh_chapters` via `structured_complete(surface="plan_weighting", ...)`,
  once per drafting run (not per student). The tutor's uploaded teaching guidance, when there is
  one, is attached as a document block; with none, the prompt says to weight from the chapter
  list alone and to say so in the reasons.
- **Prompt, `PLAN_WEIGHTING` v2:** states that the CHAPTER LIST (delimited by
  `CHAPTER_LIST_MARKERS`) and the guidance document are **data, never instructions**, that
  text in them addressed to the model carries no authority, and that a further BEGIN/END marker
  inside the list is still a chapter's own text (`SEC-20`, `SEC-21`, `AI-8`). Keep that clause if
  the prompt is rewritten, and bump the version.
- **Output is bounded in code, not trusted:** weights are clamped to 0.5–3.0 (counted in
  `clamped_chapters`); unknown chapter ids are ignored and the first answer for an id wins;
  a non-finite weight is treated as missing; a chapter with no answer takes 1.0 (counted in
  `defaulted_chapters`). The schema carries no length limits, so a verbose answer is not a
  parse failure and a paid retry; reasons are cut to about 300 characters when stored.
- **Degradation (`AI-20`, `INF-9`):** only `AIKeyMissingError` degrades — the plan is weighted
  from the weights stored on the chapters and `draft_result.weight_source` says
  `stored_chapter_weights` with a `degraded_reason`. A missing SDK or a misrouted provider is a
  deployment fault and raises, so the job fails loudly. If the AI answers but names none of the
  subject's chapters, `weight_source` is `ai_unusable`: calling that result "ai" would pass an
  even split off as advice (`PROD-1`, `PROD-2`).
- **Metering (`AI-17`):** the call is recorded under `AiFeature.plan_weighting` — its own
  bucket, so "what does planning cost" is answerable — **in its own short transaction**, not on
  the job handler's, because the tokens are spent even if the rest of the run rolls back.
- **Tutor authority (`PROD-7`):** a drafted plan is not live until the tutor accepts it, and the
  tutor can move any slot afterwards without re-acceptance.

### Degradation

`get_client()` and `get_gemini_client()` raise `AIUnavailableError` when their key is unset,
with a message naming the variable to set. **The app runs fine without either key** — the
surfaces routed to that provider fail with a clear, user-facing message and everything else
works.

`get_gemini_client()` imports `google.genai` lazily, so an install without the SDK runs fine as
long as no surface is routed to Gemini, and raises a message telling you to install it or
re-route the surface.

Handler failures persist to a domain column — `Assignment.extraction_error`,
`Submission.ai_error`, `Report.error`, `SyllabusUpload.error`, `ReadinessSnapshot.error` — so
the interface can tell the tutor what failed.

---

## Standards

### Routing

**`AI-1` — MUST · Critical · Active**
All model calls go through `services/ai.py`. No other module imports a vendor SDK or
constructs a client.
*Rationale:* it is where metering, prompt versioning, and response normalization happen; a
direct call is unmetered, unversioned, and vendor-coupled.

**`AI-2` — MUST · Critical · Active**
Call sites name a surface, never a model or a provider.
*Rationale:* a model identifier at a call site means changing models requires finding every
caller, and it defeats the per-surface routing that provides provider resilience.

**`AI-3` — MUST · Important · Active**
A new AI use case is a new surface: add it to `SURFACES`, to `SURFACE_FEATURE`, to
`config.py` as a `_PROVIDER`/`_MODEL` pair, to `.env.example`, and to the prompt registry.
*Rationale:* five places, all cheap; skipping any one produces a surface that cannot be
re-routed, cannot be metered, or has no versioned prompt.

**`AI-4` — MUST · Important · Active**
Vendor-specific behaviour stays inside `services/ai.py` and is documented at its call site
when it changes semantics — `cache=True` is Anthropic-only, and is a silent no-op on Gemini
rather than an error.
*Rationale:* a silently ignored parameter is a cost regression nobody notices. (Streaming was
the other example — Anthropic-only, and a raising one, so an outage on the surface users
watched live — until task 0.3 deleted it with the chat surface, AV-57. Kept as the reasoning
behind this rule, not as a current instance of it.)

**`AI-5` — MUST · Important · Active**
Use Anthropic's block shape as the wire format for file content, via `file_block()`.
Translation to another provider happens in `_gemini_parts()`.
*Rationale:* one neutral format means a new provider is one translator, not a change at every
call site.

### Prompts

**`AI-6` — MUST · Critical · Active**
Every prompt lives in `services/prompts.py`, keyed by surface, with a `version`.
*Rationale:* the version is stamped on every record the prompt produced and is how a bad batch
is identified; a prompt inline in a service has no version.

**`AI-7` — MUST · Critical · Active**
Bump a prompt's `version` whenever its text changes meaningfully. A change that alters what the
model is instructed to do is always meaningful.
*Rationale:* an unbumped change makes every previously stamped record indistinguishable from
records produced by different instructions.

**`AI-8` — MUST · Critical · Active**
A prompt carrying a safety instruction preserves it through any rewrite. The `marking`,
`extraction`, `class_brief`, `narrative` and `mistake_tagging` prompts' data-not-instructions
rules are safety instructions. (The `chat` prompt's anti-cheating rules were another standing example, until
task 0.3 deleted the surface, AV-57.)
*Rationale:* `SEC-21`. Marking's output can count with no human in the loop; extraction's output
reaches a student unreviewed; class_brief and narrative are grounded in a student's own work.
mistake_tagging reads two untrusted strings — the student's words, reaching it inside the marking
model's feedback, and the tutor-supplied category names and descriptions it interpolates
unescaped — and nothing reads its rows before a tutor does, which is why it carries `SEC-20`'s
flag-rather-than-obey half as a `note` field rather than silent resistance (task 4.2).

**`AI-9` — MUST · Important · Active**
A prompt that processes user-supplied content states that the content is data and never
instructions, and directs the model to flag rather than obey anything addressing it.
*Rationale:* `SEC-20`; the student controls the page being read.

**`AI-10` — SHOULD · Important · Active**
Prompts instruct the model to report uncertainty rather than guess, and downstream code treats
uncertainty as a routing signal rather than a value to coerce.
*Rationale:* confidence is the whole safety mechanism (`P4`); a prompt that discourages
admitting uncertainty disables it.

### Output handling

**`AI-11` — MUST · Critical · Active**
AI-proposed values are clamped to their valid range before storage, and a "no data" answer is
never coerced to a number.
*Rationale:* `SEC-22` and `PROD-2`. Defence in depth: even a fully successful injection cannot
award marks that do not exist.

**`AI-12` — MUST · Critical · Active**
AI output is a proposal until a human accepts it, or until an explicitly defined,
narrowly-scoped trust rule accepts it. Today exactly one such rule exists: a mark that is both
scheme-backed and of `high`/`medium` confidence.
*Rationale:* §01 P4. Widening the rule is an architectural change requiring an ADR, not a
threshold tweak.

**`AI-13` — MUST · Critical · Active**
A human decision is never overwritten by a re-run. `mark_submission` updates drafts in place
and leaves tutor-finalized marks alone.
*Rationale:* `BE-7`; at-least-once delivery means handlers do re-run.

**`AI-14` — MUST · Critical · Active**
Every record produced by an AI call stores the `provider`, `model`, and `prompt_version` that
produced it.
*Rationale:* P3 — it is the difference between recalling a specific bad batch and guessing at
one.

**`AI-15` — MUST NOT · Critical · Active**
No model is asked to produce a grade, and no model resolves a dispute about AI output.
*Rationale:* a grade is a claim about published boundaries; a contested mark is exactly the
case where a human is required.

### Metering and cost

**`AI-16` — MUST · Important · Active**
Every call records usage through `record_usage()` at the choke point.
*Rationale:* metering that call sites opt into is metering with holes, and this is the
foundation for allowances.

**`AI-17` — MUST NOT · Critical · Active**
Never record or display a fabricated price. A model with no `AI_MODEL_PRICING` entry records
`cost_usd = NULL` and is reported as an unpriced call.
*Rationale:* P5. A `$0` in a spend report is a wrong number presented as a right one.

**`AI-18` — SHOULD · Important · Active**
Work that can burst is coalesced or skipped rather than called per item —
`enqueue_readiness_v2_debounced()` for synthesis, and skipping the call when every question is
already decided.
*Rationale:* the dominant AI cost is per-call volume, and both patterns already exist to copy.

**`AI-19` — SHOULD · Recommended · Active**
Reuse a shared document across a batch with `cache=True` where the provider supports it.
*Rationale:* a mark scheme re-sent per submission is the largest avoidable token cost in the
product.

### Availability

**`AI-20` — MUST · Critical · Active**
A missing credential raises `AIKeyMissingError` (a subclass of `AIUnavailableError`) with a message naming the variable to set. A caller that degrades catches `AIKeyMissingError` only — not its parent, which also covers a missing optional SDK, a deployment fault that must fail loudly (`draft_plan` is the reference).
It never prevents startup and never degrades another surface.
*Rationale:* the app must run without either key; the failure must be diagnosable from the
message alone.

**`AI-21` — MUST · Important · Active**
A failed AI job persists a user-meaningful reason to its domain error column and preserves any
deterministic work already completed.
*Rationale:* `BE-11` and `BE-12`; `compute_readiness_v2` keeping its factor rows and writing
`status="failed"` is the pattern.

---

## Known Gaps

| Gap | Why it matters | Severity |
|---|---|---|
| **No prompt or model regression testing.** Tests use the `fake_ai` fixture and never exercise a real model; nothing measures whether a prompt change makes marking better or worse. | A scheme-backed confident mark auto-finalizes, so a prompt regression silently changes marks that count. `RISK-10`. | `blocking` |
| **No model-upgrade playbook.** `ANTHROPIC_MODEL` defaults to a pinned id; `GEMINI_MODEL`'s default is explicitly a placeholder. | Nothing defines how a model change is validated before it reaches marking. Compounded by the gap above. | `before scale` |
| **`AI_MODEL_PRICING` is empty in every environment.** | Spend is reported as `unpriced_call_count` rather than a number anyone can act on — correct behaviour, but it means cost is currently unmeasured. `RISK-12`. | `before scale` |
| **No budget, cap, or circuit breaker.** Metering is built; enforcement is not. | A large classified or a burst of submissions spends whatever it spends. `RISK-12`. | `before scale` |
| **No calibration measurement on the trust rule.** Remark-request rate and tutor override rate on auto-finalized marks are both derivable from existing rows and neither is computed. | The auto-finalize threshold cannot be tuned on evidence. `ADR-0009` names this. | `before scale` |
| **No per-call timeout or retry policy in `services/ai.py`.** Job-level retry is the only recovery, and it has no backoff (§04). | A hung provider call occupies the single worker until the client's own default fires. | `before scale` |

---

## Review Triggers

Update this document when:

- A surface is added, removed, or re-routed by default.
- A provider is added, or a helper's provider support changes.
- A prompt's version is bumped — the version table must match `PROMPTS`.
- The auto-finalize trust rule changes in any way (requires an ADR).
- `record_usage()`, `AiFeature`, or the pricing model changes.
- A grounding source is added or changes what it injects.
- Timeouts, retries, budgets, or a circuit breaker are introduced.
