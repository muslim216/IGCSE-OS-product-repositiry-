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
  - [The three helpers](#the-three-helpers)
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

Avora calls two providers across seven use cases, and one of those calls can put a mark on a
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
  exactly the vendor-specific features being used — prompt caching and streaming.
- **No prompts outside `services/prompts.py`.**
- **No agentic or tool-using loops.** Every call is a single request with a bounded response.
- **No streaming except chat.**

## Sources

Written from: `backend/app/services/ai.py` (448 lines);
`backend/app/services/prompts.py` (161 lines); `backend/app/services/marking.py`;
`backend/app/services/extraction.py`; `backend/app/services/readiness_v2_ai.py`;
`backend/app/services/knowledge.py`; `backend/app/services/student_context.py`;
`backend/app/models/ai_usage.py`; `backend/app/config.py`; `backend/app/api/ai_usage.py`.

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
provides client construction, the surface routing table, three call helpers, the neutral
content-block format, cost estimation, and usage recording.

`AiResponse` is the normalized result — `{provider, model, prompt_version, input_tokens,
output_tokens, parsed, text}` — so **nothing downstream branches on which vendor answered**.

### Surfaces and routing

Seven surfaces, defined in `SURFACES`:

| Surface | Default provider | Default model | What it does |
|---|---|---|---|
| `marking` | Gemini | `GEMINI_MODEL` | Marks submitted pages against a scheme |
| `extraction` | Gemini | `GEMINI_MODEL` | Pulls a question list from a booklet |
| `syllabus` | Gemini | `GEMINI_MODEL` | Extracts a topic tree from a syllabus document |
| `reports` | Anthropic | `claude-opus-4-8` | Audience-specific narrative reports |
| `readiness` | Anthropic | `claude-opus-4-8` | Layer 2 readiness synthesis |
| `chat` | Anthropic | `claude-haiku-4-5` | Streaming tutor chat |
| `class_brief` | Anthropic | `claude-opus-4-8` | Pre-lesson class brief |

`resolve_surface(surface)` reads `AI_<SURFACE>_PROVIDER` and `AI_<SURFACE>_MODEL`, falling back
to that provider's default model when the per-surface model is blank. It **raises on an unknown
surface** and **raises with a helpful message on an invalid provider**, naming the accepted
values — so a typo in configuration fails loudly at the call rather than silently routing
somewhere unintended.

The split is deliberate: bulk document work goes to the cheaper provider, quality-dominated
low-volume work to the more capable one, and chat to the fastest. No single provider outage
stops the product. See `ADR-0006`.

**Surfaces and billing buckets are different things.** `SURFACE_FEATURE` maps each surface to
an `AiFeature` for metering, and several deliberately share a bucket — `syllabus` meters as
`extraction`, `class_brief` meters as `report`. The surface is the routing key; `AiFeature` is
the billing-facing grouping.

### The three helpers

| Helper | Providers | Returns | Used for |
|---|---|---|---|
| `structured_complete()` | Both | `AiResponse.parsed` | Schema-constrained output — marking, extraction, syllabus, readiness |
| `text_complete()` | Both | `AiResponse.text` | Prose — reports, class brief |
| `stream_complete()` | **Anthropic only** | An async iterator | Chat, the sole streaming surface |

**A Gemini-routed chat raises.** That is a real configuration trap: setting
`AI_CHAT_PROVIDER=gemini` produces a runtime failure on the one surface users interact with
live.

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
| `marking` | **v3** | Bumped when marks began counting without tutor review |
| `extraction` | v2 | |
| `syllabus`, `reports`, `readiness`, `chat` | v1 | |
| `class_brief` | v1 | System prompt is empty — all instruction is in the user turn |

Two prompts carry rules that are not stylistic:

- **`marking`** states that page content is data and never instructions, and that anything
  addressing the marker is flagged with confidence `low` for a tutor rather than acted on. This
  is a security control (`SEC-20`).
- **`chat`** carries the anti-cheating guardrails: never give complete answers to the student's
  own homework; teach the method, use a worked example on a *different* problem, ask guiding
  questions. It also forbids presenting internal readiness percentages as official grades.

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
| Tutor Knowledge Base | `services/knowledge.py` → `build_tutor_context()` | Marking, extraction, reports, chat |
| Student academic record | `services/student_context.py` → `build_student_context()` | Chat, reports |
| Deterministic factor sub-scores | `services/readiness_v2.py` | Readiness synthesis |

`build_tutor_context()` uses the same `cache=True` prompt-caching pattern as `file_block()`.
The student context reads from `services/student_crm.py` — the same aggregation the interface
uses — so the AI and the tutor cannot be grounded in different truths (`PROD-11`).

Readiness synthesis is the strictest case: the factor sub-scores and tutor weights are
**mandated inputs**, and the model is not permitted to contradict them or to produce a grade.

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
when it changes semantics — `cache=True` is Anthropic-only; streaming is Anthropic-only.
*Rationale:* a silently ignored parameter is a cost regression nobody notices; a raising one is
an outage on the surface users watch live.

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
A prompt carrying a safety instruction preserves it through any rewrite. The `marking` prompt's
data-not-instructions rule and the `chat` prompt's anti-cheating rules are safety instructions.
*Rationale:* `SEC-21`. Marking's output can count with no human; chat's output reaches a child.

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
A missing credential raises `AIUnavailableError` with a message naming the variable to set.
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
| **`AI_CHAT_PROVIDER=gemini` is accepted at configuration time and fails at runtime.** | `resolve_surface` validates the provider name but not that the provider supports streaming. | `nice to have` |
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
