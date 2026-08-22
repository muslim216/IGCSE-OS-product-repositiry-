# Documentation Authority

> **Governance layer.** Which document wins when two disagree, how a rule is written, and
> what a rule's classification and status mean.
>
> **Status:** Active · Part of Engineering Constitution v1.2
>
> **Audience:** every engineer and every AI agent working in this repository.

## Contents

- [The authority hierarchy](#the-authority-hierarchy)
- [Resolving a conflict](#resolving-a-conflict)
- [Anatomy of a rule](#anatomy-of-a-rule)
- [Rule classification](#rule-classification)
- [Rule lifecycle](#rule-lifecycle)
- [Rule identifiers](#rule-identifiers)
- [Document structure](#document-structure)
- [Constitution versioning](#constitution-versioning)

---

## The authority hierarchy

Seven tiers. A lower tier may clarify, illustrate, or add detail to a higher tier. **It may
never contradict one.**

| Tier | Artifact | What it is authoritative for |
|---|---|---|
| **1** | **Engineering Constitution** — `docs/governance/` and the 14 numbered documents | Engineering standards, principles, and the system as built. The final word. |
| **2** | **Architecture Specifications** — `docs/avora-architecture.md`, `docs/adr/` | Target design and the reasoning behind permanent decisions. |
| **3** | **`CLAUDE.md`** | Agent-facing operating brief: the binding rules an agent needs loaded at all times, and the map into Tier 1. |
| **4** | **`README.md`** | Product introduction, local setup, deploy walkthrough. |
| **5** | **Inline documentation** — docstrings, module headers | How a specific unit behaves. |
| **6** | **Comments** | Why a specific line is the way it is. |
| **7** | **Examples** — seed data, tests read as documentation, snippets | Illustration only. Never normative. |

Two clarifications that matter in practice:

- **Tier 1 outranks Tier 2 on questions of fact.** `docs/avora-architecture.md` describes
  what Avora is being built toward; the numbered documents describe what Avora is. Where
  they differ, the architecture document is not wrong — it is describing a different
  question. But if you need to know what your code will run against, Tier 1 answers it.
- **An ADR outranks a standard on the question "why".** Standards say what to do; ADRs say
  why a structural decision was made and what was traded away. A standard that contradicts
  an accepted ADR is a defect in the standard.

## Resolving a conflict

When two documents disagree, the conflict is a defect. Do not pick one silently.

1. **Determine which is higher tier.** Follow it for now.
2. **Determine which is true.** Read the code. Documentation drift is far more common than
   a genuine design disagreement, and the code is the arbiter of what currently happens —
   though not of what *should* happen.
3. **Record the conflict.** File it, or add it to the affected document's Known Gaps with a
   severity.
4. **Fix the lower-tier document in the same change** where you can. Where the conflict is
   substantive rather than editorial, take it through `governance/change-process.md`.

**Never resolve a conflict by deleting a rule.** See [Rule lifecycle](#rule-lifecycle).

## Anatomy of a rule

Every standard in this constitution is written in exactly one form, so that both a reviewer
and an agent can parse it:

```
**`PREFIX-N` — VERB · Class · Status**
The rule, stated as a single declarative sentence, plus any necessary qualification.
*Rationale:* one line on why this rule exists.
```

Worked example. **`EXAMPLE-1` is not a real rule** — the format is illustrated with a
fictional ID deliberately, so that this specimen can never drift from a rule's actual
definition:

> **`EXAMPLE-1` — MUST NOT · Critical · Active**
> No surface may render a missing measurement as a zero.
> *Rationale:* a fabricated zero asserts something the system does not know.

For the real version of that rule, see `PROD-2` in §01 — cited, not restated, per `GOV-5`.

**VERB** is RFC 2119:

| Verb | Meaning |
|---|---|
| **MUST** / **MUST NOT** | Binding. A reviewer may block on this alone. |
| **SHOULD** / **SHOULD NOT** | Strong default. Departing needs a stated reason in the pull request. |
| **MAY** | Genuinely optional; recorded so the option is known to exist. |

**Every rule carries a rationale.** A rule without one is unmaintainable: nobody can tell
whether a future change invalidates it. If you cannot state why a rule exists in one line,
it is probably not a rule — it is a preference, and belongs in §13 Coding Standards as
style, or nowhere.

## Rule classification

The verb says how binding a rule is. The class says how much damage breaking it does. They
are independent: a **Recommended MUST** is coherent (do it this way, but nothing burns if
you do not), and so is a **Critical SHOULD** (rare, and always explains itself).

| Class | Meaning | Consequence of breaking it |
|---|---|---|
| **Critical** | Protects security, data integrity, tenant isolation, or student trust. | Blocks merge. No exceptions without an explicit, recorded decision by the architecture owner. |
| **Important** | Protects correctness, maintainability, or operability. | Blocks merge unless the pull request states why, and a reviewer accepts it. |
| **Recommended** | House convention. Consistency has value; deviation has a cost but not a large one. | Reviewer discretion. Raise it, do not die on it. |

When classifying a new rule, ask: *if someone silently broke this and it shipped, what would
we find out, and when?* Critical rules are the ones you find out about from a user.

## Rule lifecycle

Rules are versioned artifacts. They are never silently removed.

| Status | Meaning |
|---|---|
| **Draft** | Proposed and being trialled. Not yet binding; a reviewer may cite it as advice. |
| **Active** | Binding, according to its verb and class. |
| **Deprecated** | No longer binding. Kept because existing code follows it and existing reviews cite it. Carries the date and reason. |
| **Superseded** | Replaced by a specific rule. Carries the replacing ID: `Superseded by API-14`. |

A deprecated or superseded rule stays in its document, struck through, with its ID
permanently retired:

> **`~~API-3~~` — MUST · Important · Superseded by `API-14` (2026-08)**
> ~~List endpoints return the complete result set.~~
> *Superseded because unbounded lists became a latency and memory risk; `API-14` requires
> cursor pagination on collections that can exceed 200 rows.*

**IDs are never reused.** `API-3` means one thing forever, so a review comment from two
years ago still means what it said.

## Rule identifiers

An ID is `PREFIX-N`, where the prefix names the owning document and `N` is allocated
sequentially within it and never reused.

| Prefix | Document | Prefix | Document |
|---|---|---|---|
| `PROD` | §01 Product Architecture | `INF` | §08 Infrastructure & Deployment |
| `UX` | §02 UX & Accessibility Standards | `AI` | §09 AI Platform |
| `FE` | §03 Frontend Engineering | `PERF` | §10 Performance Engineering |
| `BE` | §04 Backend Engineering | `REL` | §11 Reliability (SRE) |
| `API` | §05 API Standards | `QA` | §12 Quality Engineering |
| `DB` | §06 Database Design | `CODE` | §13 Coding Standards |
| `SEC` | §07 Security Architecture | `OPS` | §14 Operations Runbooks |

A rule belongs to exactly one document — the one that owns the subject matter. Other
documents **cite** it (`see SEC-3`); they do not restate it. A standard that appears in two
documents will be edited in one and not the other, and the constitution will start
disagreeing with itself.

Principles are numbered `P1`, `P2`, … within their document and are cited with their
document: `§01 P3`. Cross-document citation uses the section symbol: `§07`, `§06 DB-11`.

## Document structure

All 14 numbered documents follow the same nine-part structure, in this order:

| # | Section | Contents |
|---|---|---|
| 1 | **Header** | Title, volume, status, version, and a one-line statement of what the document governs |
| 2 | **Purpose** | Why this document exists and what question it answers |
| 3 | **Scope** | What is in, what is out, and the **non-goals** — what Avora deliberately does not do in this area |
| 4 | **Sources** | The real files this document was written from, so any claim can be re-verified |
| 5 | **Principles** | `P1`…`Pn`, the document's constitutional layer |
| 6 | **Current Reality** | How it works **today**, warts included, with file paths and line references |
| 7 | **Standards** | Numbered rules, in the format above |
| 8 | **Known Gaps** | What is missing or broken, with severity |
| 9 | **Review Triggers** | The events that oblige someone to update this document |

A table of contents sits between the header and Purpose. It is navigation, not structure.

**Sections 6, 7 and 8 are never mixed.** This is the single most important formatting rule
in the constitution. Current Reality describes what you will find when you open the code,
including things nobody is proud of. Standards describe what to do. Known Gaps describe the
distance between them. Blending them produces a document that reads as if the system
already works the way we wish it did — which is precisely how the previous documentation
came to describe an RBAC mechanism that nothing calls.

### Severity in Known Gaps

| Severity | Meaning |
|---|---|
| **`blocking`** | Costs correctness, security, or velocity now. Fix next. |
| **`before scale`** | Fine at current volume, breaks at the next order of magnitude. The trigger is named. |
| **`nice to have`** | Real, but leaving it costs nothing important. |

## Constitution versioning

The constitution as a whole carries a version. **This is Engineering Constitution v1.2.**

| Change | Version effect |
|---|---|
| A Critical rule is added, or any rule is deprecated or superseded | Minor bump (v1.0 → v1.1) |
| A document is added or removed; a principle changes; the authority hierarchy changes | Major bump (v1.x → v2.0) |
| Current Reality is updated to match code; a gap is closed; typos and clarifications | No bump |

The version and its changelog live in `docs/README.md`. Individual documents carry their
own status line but not their own version — the constitution is versioned as one artifact,
because its value is in being internally consistent at a point in time.

## Review triggers

- The authority hierarchy changes, or a new tier of artifact appears.
- The rule format, classification scheme, or lifecycle states change.
- A new numbered document is added and needs a prefix.
- Two documents are found to contradict each other in a way the hierarchy does not resolve.
