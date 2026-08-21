# ADR-0006 — AI providers are routed per surface, not globally

**Status:** Accepted · **Date:** 2026-08 (retroactive) · **Owner:** Architecture owner
**Supersedes:** — · **Superseded by:** —

## Context

MANARA uses AI for seven distinct jobs with genuinely different requirements: marking
handwritten pages against a mark scheme, extracting questions from a PDF booklet, extracting
a syllabus topic tree, synthesizing readiness, writing reports, streaming tutor chat, and
producing a class brief.

These differ in cost sensitivity, latency tolerance, document-handling ability, and
reasoning depth. Bulk document work is high-volume and cost-dominated; chat needs low latency
and streaming; readiness synthesis and reports are low-volume and quality-dominated.

A single `ANTHROPIC_MODEL` setting cannot express that.

## Decision

**A *surface* is the unit of AI configuration.** Each of `marking`, `extraction`,
`syllabus`, `reports`, `readiness`, `chat`, and `class_brief` resolves independently to a
provider and model via `resolve_surface()` in `services/ai.py`, reading
`AI_<SURFACE>_PROVIDER` and `AI_<SURFACE>_MODEL`.

Defaults: bulk document work (marking, extraction, syllabus) → **Gemini**; chat → **Claude
Haiku**; reports, readiness, class brief → **Claude Opus**.

**Call sites name a surface, never a model.** `services/ai.py` is the only module that
touches either vendor SDK. Three helpers cover every call — `structured_complete()`,
`text_complete()`, and `stream_complete()` (Anthropic-only; a Gemini-routed chat raises) —
and all three return a normalized `AiResponse`, so nothing downstream branches on vendor.

Anthropic's content-block shape is the **neutral wire format**; `_gemini_parts()` translates
it.

## Alternatives considered

**One provider for everything.** Simplest. Rejected on cost and resilience: bulk document
marking at frontier-model prices is the dominant spend, and a single provider outage would
stop the entire product.

**A generic abstraction library.** Would add a dependency, a translation layer, and a
lowest-common-denominator feature set that hides exactly the vendor-specific features being
used — prompt caching and streaming.

**Per-call provider choice at the call site.** Maximum flexibility, and it would scatter
model names through the codebase so that changing a model means finding every caller. The
surface indirection exists precisely to prevent that.

## Consequences

**Easier:** switching a surface's provider is an environment variable, with no code change —
which is also the incident response when a provider degrades (§14). Cost is optimized per
workload. No single provider outage stops the product.

**Harder:** two SDKs to maintain and two sets of failure modes. Capability differences must
be handled explicitly: `cache=True` is Anthropic-only and a no-op on Gemini; streaming is
Anthropic-only and raises otherwise. Seven surfaces × two settings is fourteen environment
variables.

**A real trap this creates:** a surface can be pointed at a provider whose key is unset, and
the failure appears as that feature being broken rather than as a configuration error. This
is why `GEMINI_API_KEY` became effectively required at deploy despite the app "running
fine" without it — marking and extraction default to Gemini, so without that key the
homework pipeline fails while everything else works.

## Revisit when

A third provider is added — the surface indirection scales, but the environment-variable
count is already the least pleasant part of this design and a structured configuration value
may become clearer.

## Amendment — 2026-08-21 (`AV-57`)

Not a reversal: per-surface routing stands exactly as decided. Two facts recorded above have
changed with the deletion of the student AI chat.

- **Streaming is gone.** "Streaming is Anthropic-only and raises otherwise" described
  `stream_complete()`, which existed for the chat surface alone and is deleted with it. The
  capability difference it documented is no longer a live constraint — but the reasoning
  behind it should survive: streaming was implemented for one vendor deliberately, because a
  second implementation was not worth the surface area for a single consumer. A future
  streaming surface must re-make that trade-off rather than inherit it.
- **Seven surfaces are now six**, so the environment-variable count in *Consequences* is
  twelve rather than fourteen. This makes the "Revisit when" trigger slightly less pressing,
  not differently shaped.

The decision itself is unchanged and remains Accepted. `tests/test_ai_provider.py` still
proves the core claim — a surface resolves to a provider *and* a model of its own — on a
surviving surface, since chat was only the example that happened to carry it.
