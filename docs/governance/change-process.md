# Constitution Change Process

> **Governance layer.** How engineering standards are proposed, changed, deprecated, and
> versioned — and when a decision needs an ADR instead of a rule.
>
> **Status:** Active · Part of Engineering Constitution v1.0
>
> **Depends on:** `governance/documentation-authority.md` for rule format, classification,
> and lifecycle states.

## Contents

- [Why there is a process at all](#why-there-is-a-process-at-all)
- [Roles](#roles)
- [Proposing a new rule](#proposing-a-new-rule)
- [Changing an existing rule](#changing-an-existing-rule)
- [Deprecating and superseding](#deprecating-and-superseding)
- [When an ADR is required](#when-an-adr-is-required)
- [Documentation update obligations](#documentation-update-obligations)
- [Reviewing a constitution change](#reviewing-a-constitution-change)
- [Scheduled review](#scheduled-review)

---

## Why there is a process at all

A standard that anyone can change silently is not a standard. A standard that nobody can
change becomes a lie the moment the code moves. This process is the narrowest thing that
prevents both.

It is deliberately lightweight. MANARA is a small team. The process scales down to "the
owner decides in a pull request" and up to a review board without changing shape.

## Roles

Ownership today is concentrated; the structure exists so that it can be distributed without
being invented under pressure. See `governance/ownership.md` for the current holders.

| Role | Responsibility in this process |
|---|---|
| **Architecture owner** | Approves Critical rules, principle changes, and all ADRs. Final say on conflicts the hierarchy does not resolve. |
| **Document owner** | Owns one numbered document. Approves Important and Recommended rules within it, and keeps its Current Reality section true. |
| **Proposer** | Anyone — human or AI agent — may propose. Carries the burden of stating the problem and the rationale. |
| **Reviewer** | Any engineer on the pull request. Checks the change against [Reviewing a constitution change](#reviewing-a-constitution-change). |

While one person holds every role, the process still applies: the discipline is in writing
the rationale down, not in the number of approvers.

## Proposing a new rule

1. **Establish the problem.** A rule needs an incident, a repeated review comment, a bug
   class, or a decision made three times. "It would be tidier" is not a problem.
2. **Check it does not already exist.** Search the rule registry in `docs/README.md`. A
   duplicated standard is worse than a missing one, because the two copies will diverge.
3. **Pick the owning document.** Exactly one, by subject matter. Other documents cite it.
4. **Allocate the next free ID** in that document's prefix. Never reuse a retired ID.
5. **Write it in the standard form** — verb, class, status, statement, rationale.
6. **Open it as Draft** if it needs trialling; open it as Active if it merely codifies what
   the team already does.
7. **Update `docs/README.md`** if the change affects the registry or the version.

A rule that codifies existing practice can go straight to Active. A rule that requires
changing existing code opens as Draft, names the code it would invalidate, and becomes
Active when either the code is converged or the gap is recorded in Known Gaps with a
severity. **Do not make a rule Active that the codebase broadly violates without recording
that as a gap** — otherwise the constitution starts describing a system nobody built.

## Changing an existing rule

| Kind of change | Process |
|---|---|
| Clarifying wording, without changing meaning | Direct edit. Note it in the pull request. |
| Strengthening (SHOULD → MUST, Important → Critical) | Treat as a new rule: state the problem, get the owner's approval, record affected code. |
| Weakening (MUST → SHOULD, Critical → Important) | Requires the architecture owner. Record why the original reasoning no longer holds. |
| Changing what the rule requires | Do not edit in place. **Supersede it** — see below. |

The distinction matters because review comments cite IDs. If `SEC-3` silently changes
meaning, every past citation of `SEC-3` now says something its author did not say.

## Deprecating and superseding

Rules are never deleted.

**Deprecate** when a rule is no longer binding and nothing replaces it — the problem went
away, or the practice is now enforced by tooling. Mark it `Deprecated`, strike the
statement, add the date and the reason.

**Supersede** when a different rule now governs the same subject. Mark the old rule
`Superseded by <ID>`, and have the new rule name what it replaces. Both stay in the
document.

```markdown
**`~~DB-4~~` — MUST · Important · Superseded by `DB-17` (2026-08)**
~~Foreign key columns are indexed only where a query demonstrably needs it.~~
*Superseded because "demonstrably" was never demonstrated and the schema ended up with one
index; `DB-17` requires an index on every foreign key that is filtered or joined.*
```

Both operations are minor version bumps.

## When an ADR is required

**Standards say what to do. ADRs say why a structural decision was made and what it cost.**
Do not bury architectural reasoning inside a rule's rationale line — the rule will be
edited, and the reasoning will be lost.

Write an ADR when a decision:

- **is expensive to reverse** — a schema shape, a storage engine, a deployment topology, an
  auth model;
- **rejects a reasonable alternative** — and the next engineer will otherwise re-propose it;
- **creates a constraint other work must live within** — single-instance deployment,
  polymorphic submissions, deterministic scoring;
- **is a trade-off rather than a best practice** — something a competent engineer might
  legitimately have decided the other way.

Do **not** write an ADR for: choosing a variable name, adopting an obvious library, or
anything a rule already covers completely.

ADRs are approved by the architecture owner and are immutable once accepted. A decision that
changes gets a **new** ADR that supersedes the old one. See `docs/adr/README.md`.

## Documentation update obligations

These are the obligations that keep the constitution true. They are stated here once and
cited from everywhere.

**`GOV-1` — MUST · Critical · Active**
A pull request that changes behaviour a constitution document describes updates that
document's Current Reality section in the same pull request.
*Rationale:* documentation that drifts is worse than none, because it is trusted.

**`GOV-2` — MUST · Critical · Active**
A pull request that closes a Known Gap removes that gap entry in the same pull request.
*Rationale:* a stale gap list makes the honest gaps unbelievable.

**`GOV-3` — MUST · Important · Active**
A pull request that breaks an Active rule either fixes the code, or supersedes the rule
through this process, or records a Known Gap with a severity. It may not do none of these.
*Rationale:* silent divergence is how the previous documentation set failed.

**`GOV-4` — MUST · Important · Active**
A new rule cites the file or incident that motivated it. A new Current Reality claim cites
the file it was read from.
*Rationale:* every claim in this constitution must be re-verifiable by someone who does not
trust it.

**`GOV-5` — SHOULD · Recommended · Active**
Prefer citing a rule ID over restating its content. A standard restated in a second
document will be edited in one place only.
*Rationale:* duplication is the mechanism by which a constitution starts contradicting
itself.

**`GOV-6` — MUST · Important · Active**
Terminology defined in `governance/glossary.md` is used with that meaning throughout the
constitution. A document that needs a different meaning defines a different term.
*Rationale:* "readiness", "snapshot" and "assessment" each already mean something specific;
reusing them loosely makes precise documents read as approximate ones.

## Reviewing a constitution change

A reviewer checks:

- [ ] Is the problem real and stated?
- [ ] Is there a rationale, in one line?
- [ ] Is the rule in exactly one document, with a fresh ID?
- [ ] Are verb, class, and status all present and consistent with each other?
- [ ] Does it contradict an existing rule, principle, or accepted ADR?
- [ ] Does it restate an existing rule instead of citing it?
- [ ] Does existing code violate it? If so, is that recorded as a gap or converged?
- [ ] Does it belong in Current Reality, Standards, or Known Gaps — and is it in the right
      one?
- [ ] If it is a structural trade-off, should it be an ADR instead?
- [ ] Does the version and changelog in `docs/README.md` need updating?

## Scheduled review

Beyond change-triggered updates, the constitution gets a deliberate pass:

| Cadence | Activity |
|---|---|
| **Every release of significant scope** | Document owners confirm their Current Reality sections still hold. |
| **Quarterly** | Review Known Gaps: re-rank severities, close what is closed, promote `before scale` items whose trigger has arrived. Review the risk register. |
| **Annually** | Review principles, non-goals, and Deprecated rules. Consider a major version bump. |

The quarterly pass is the one that matters most. Gaps recorded and never revisited become
folklore.

## Review triggers

- Ownership becomes distributed across more than one person.
- The team adopts a formal architecture review forum.
- The ADR process changes.
- `GOV-*` rules are added, changed, or retired.
