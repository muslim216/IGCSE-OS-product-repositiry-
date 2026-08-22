# 04 — The AI Layer

*Where AI is used, which model does what, and the rules on when it's trusted without a human.*

---

## The positioning, first

Avora is deliberately **not an AI tutor and not an AI marker.** The internal statement of this is blunt: *the platform is the product; AI enhances every layer.* A feature that's impressive AI but strengthens none of the six product surfaces isn't an Avora feature.

That's a product boundary with real architectural consequences. It's why AI output is a *proposal* rather than a decision, why the tutor's authority is built into the pipeline rather than being a setting, and why no model is ever asked for a grade.

---

## The seven places AI is used

| Where | What it does | Which model |
|---|---|---|
| **Marking** | Marks submitted work against the scheme | Gemini |
| **Extraction** | Pulls the question list out of a booklet | Gemini |
| **Syllabus** | Turns a syllabus PDF into a topic tree | Gemini |
| **Reports** | Writes progress narratives | Claude Opus |
| **Readiness** | Synthesises the seven factors into a score and plan | Claude Opus |
| **Chat** | The student's AI mentor | Claude Haiku |
| **Class brief** | A pre-lesson summary for the tutor | Claude Opus |

### Why two providers

This is a deliberate three-way split, not indecision:

- **Bulk document work** — reading PDFs, marking pages — goes to the cheaper provider, because it's high volume and the quality bar is "read this accurately."
- **Quality-dominated, low-volume work** — reports, readiness synthesis — goes to the most capable model, because these are read by parents and shape what a tutor teaches next.
- **Chat** goes to the fastest model, because a student waiting on a reply notices every second.

There's a resilience benefit that falls out for free: **no single AI provider going down stops the product.** If one is unavailable, the surfaces routed to it fail with a clear message and everything else keeps working.

### One switchboard

Every AI call in the entire system goes through a **single file**. Nothing anywhere else talks to an AI provider directly.

That's the design's most valuable property, for four reasons:

1. **Every call is automatically metered.** No feature can spend money invisibly, because there's no path to spending that bypasses the meter.
2. **Switching models is a config change**, not a code change. Code says "this is a marking task" — never "use this specific model." Which model answers is configuration.
3. **Adding a third provider is one translator**, not a change at every call site.
4. **Every AI-produced record is stamped** with which provider, which model, and which version of the instructions produced it.

That last point is what turns "the AI marked some things wrong last week" from a guess into a query. You can find the exact affected records instead of estimating.

---

## Prompts are versioned like code

The instructions given to each model — the **prompts** — live in one file, each with a version number. No instruction text is scattered through the codebase.

Every version is stamped onto every record it produced. So if the marking instructions change and something goes wrong, you can identify precisely which marks were produced by which version.

Current versions: marking is on **v3** — bumped when marks began counting without tutor review, which is exactly the kind of change that should force a version bump. Extraction is on v2. Everything else is on v1.

**Two prompts carry rules that are safety controls rather than style preferences**, and they must survive any rewrite:

**The marking prompt** states that the content of a student's page is *data, never instructions*, and that anything on the page addressing the marker directly must be flagged for a human rather than acted on.

**The chat prompt** carries the anti-cheating rules: never give a complete answer to the student's own homework, teach the method instead, use a worked example on a *different* problem, ask guiding questions. It also forbids presenting internal readiness percentages to a student as if they were official grades.

---

## The trust model — the most important decision in the product

**When does an AI mark count without a human looking at it?**

A mark is accepted automatically — it counts immediately, the student sees it, it becomes evidence — if and only if it is **both**:

1. **Checked against an official mark scheme**, and
2. **Confident** (high or medium).

Everything else waits in the tutor's review queue with the AI's suggestion already filled in.

### Why both conditions, not just confidence

This was considered carefully and it's the sharpest reasoning in the system:

> A high confidence score without a mark scheme is confidence in an **interpretation**, not confidence in a **mark**.

The mark scheme is what makes the judgement *checkable*. Without it, the model is marking from the syllabus and comparable questions — a reasonable thing to do, but a fundamentally different act. So having a scheme is a separate requirement, not an input to a confidence score. In practice, marking without a scheme is always flagged as unsure.

### What was rejected

**Tutor finalises everything** — the original model. Safe, and it doesn't scale. It also delays feedback to the student, which is where most of the learning value lives.

**AI finalises everything** — maximum leverage, rejected outright. It puts a model's guess on a child's record with no human accountability.

### The four guardrails

1. **Marks are capped** to what a question is actually worth. Even a perfectly executed manipulation of the AI can't award marks that don't exist.
2. **A blank or unreadable answer is never silently scored zero.**
3. **The tutor can override anything**, and every override is written to a permanent log with no way for anyone to edit or delete it.
4. **Students can contest any finalised mark** — automatic or tutor-set. It routes to the tutor with the AI's original reasoning attached, and is **never** re-decided by AI. One appeal per question, ever, enforced by the database.

### The honest cost of this decision

Two things follow from letting marks count automatically, and the team names both:

**The student controls the page being marked.** Someone could write an instruction to the AI on their homework. The prompt is explicitly built to treat page content as data and flag anything that looks like an instruction — but that protection is a rule inside a prompt, and prompts get rewritten. If that rule is ever lost in an edit, the protection goes with it.

**Prompt and model changes now alter marks that count**, and there is no test set of known-correct questions run against the real model before a change ships. So marking quality can drift — from an edited prompt, or from an AI provider silently updating their model — and nobody would find out except through students complaining.

There's also nothing measuring whether the confidence threshold is set correctly. How often do tutors override an automatic mark? How often do students appeal one? Both numbers already exist in the database and neither is being calculated. Until they are, the threshold is running on judgement rather than evidence.

Both are in the [weaknesses document](../Product-Overview-and-Weaknesses.md) as weakness #4.

---

## Grounding — why the AI isn't generic

Every AI feature is fed real context rather than being left to its general knowledge:

| What's injected | Into |
|---|---|
| The tutor's knowledge base | Marking, extraction, reports, chat, readiness synthesis |
| The student's full academic record | Chat, reports |
| The seven deterministic factor scores | Readiness synthesis |

The student's record is read through the **same code the tutor's screen uses**. Not an equivalent query — the identical one. That makes it structurally impossible for the AI and the interface to be working from different pictures of the same student.

Readiness synthesis is the strictest case: the factor scores and tutor weights are **mandated inputs the model isn't allowed to contradict**, and it's forbidden from producing a grade.

---

## Cost

Every single AI call records: which organisation, which tutor, which student, which feature, which model, how many tokens in and out, and a computed cost — which is `null`/unpriced rather than a guessed number until that model's pricing is configured (see the two gaps below).

Because this happens at the single switchboard, **metering has no holes.** There's no way for a feature to spend money without being recorded.

Two cost optimisations are already built in:

**Shared documents are cached.** A mark scheme used across a batch of thirty submissions is sent once, not thirty times. This is the single largest avoidable cost in the product.

**Bursts are collapsed.** Five submissions in an hour trigger one readiness synthesis, not five. Synthesis uses the most expensive model, so this matters.

### Two gaps, and they're commercially significant

**The price list is empty.** The system knows how many tokens each call used but hasn't been told what tokens cost. So spending reports currently say *"we made 4,000 unpriced calls"* rather than a figure in dollars.

The system is being honest — it deliberately refuses to record an unknown price as $0, on the principle that a fabricated zero in a spend report is a wrong number presented as a right one. But the practical effect is that **nobody can currently answer what a customer costs to serve** — which means nobody can price the subscription.

**There is no spending cap.** No per-tutor allowance, no limit, no circuit breaker. A tutor who bulk-uploads a year of past papers spends whatever it spends.

Given the business model is a subscription that *includes an AI allowance*, both need solving before pricing is set. The measurement foundation — the hard part — is built. The enforcement isn't.

---

## When AI is unavailable

The system runs fine without either provider's credentials. Surfaces routed to a missing provider fail with a clear message naming exactly what needs configuring; everything else works normally.

Failures are recorded where the *tutor* can see them, not just in a log file. A failed extraction, a failed marking run, a failed report each write their reason somewhere the interface displays it.

One configuration trap worth knowing: chat is the only streaming feature, and only one provider supports streaming. Routing chat to the other provider is accepted at configuration time — provider resolution only validates the provider name, not whether it can stream — and fails later at runtime, on the one feature users interact with live. Rejecting an unstreamable chat route up front, at startup or at resolution, is the obvious hardening and hasn't been done.

---

## What Avora deliberately does not do with AI

| Not done | Why |
|---|---|
| **No training or fine-tuning on user data** | The data is minors' academic records. Student work is never contributed to any model. Reversing this would need explicit informed consent and legal review — it's not an engineering decision. |
| **No model produces a grade** | A grade is a claim about published exam board boundaries, not a judgement. |
| **No AI resolves a dispute about AI output** | An appeal is exactly the case where a human is required. |
| **No autonomous AI agents** | Every call is a single request with a bounded response. Nothing loops, nothing takes actions on its own. |
| **No streaming except chat** | Everywhere else, a complete checked answer beats a fast partial one. |

That first row is worth dwelling on for anyone selling this product. "We do not train on student data" is a clean, unambiguous answer to the question every school and every parent will eventually ask, and it's true by construction rather than by policy.
