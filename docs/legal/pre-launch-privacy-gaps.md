# avora — Pre-launch privacy & AI compliance gaps

**Type:** Delivery checklist. **Status:** Open. **As of:** 2 October 2026. **Owner:** Founder.
**Derived from:** `privacy-law-register.md`. Each item names the laws behind it so a lawyer can check the
reasoning, and says whether it is **product work** (code), **paperwork** (contracts, filings, documents), or a
**decision** only the founder can make.

> The public privacy policy (`/privacy`) is written for avora **as it must be at launch**. Every item marked
> **Launch blocker** below is something that policy promises; avora must not launch in a market until the
> blockers for that market are closed, or the policy is changed to match. The policy page carries a visible
> "draft — pending legal review" notice until counsel signs off.

## Ranking

Ranked by legal exposure: children's data first, then automated decisions about children, then transfers.

| # | Gap | Type | Markets | Laws | Launch blocker? |
|---|---|---|---|---|---|
| 1 | **Parent/guardian consent before a student's data is processed.** Today a student joins by invite code with no age check and no consent. Build: ask age band at join; for every student under 18, hold the account "pending" until a parent completes the (already single-use, SEC-13) parent link with email verification and a guardianship attestation; stronger verification for under-13s; store consent records append-only (who, when, policy version, scope incl. AI processing and transfer abroad); one-step withdrawal that stops processing. | Product | All GCC; supports EU/UK | Saudi IR Art 13; Oman Art 6; Qatar Art 17; UAE CDS Law (under-13); ICO Code std 3 | **Yes** (GCC) |
| 2 | **Auto-finalized AI marks.** A mark counts with no human review when the AI is confident and a scheme exists. Make it a per-class tutor setting, **off by default**; label every AI-finalized mark to student and parent; keep remark requests as the human-review route; consider excluding unreviewed marks from predicted grades shown to students and parents. | Product + decision | All | GDPR Art 22 + Recital 71; UK Arts 22A–D; DIFC Art 38(4); UAE Art 18; Oman Art 14; AI Act Art 14 (Dec 2027) | **Yes** (EU, DIFC); strongly advised elsewhere |
| 3 | **AI disclosure in the product.** Students and parents must be told, where they see marks and reports, that AI drafted them. | Product | All | Anthropic AUP (minors guidelines); AI Act Art 50; GDPR Art 13(2)(f) | **Yes** (contractual) |
| 4 | **Export and deletion.** Per-student export (incl. AI reasoning and audit trail) and per-student/per-account deletion cascading to uploaded files; guardian requests on a child's behalf. Resolve the append-only override audit by pseudonymising audit rows at deletion, documented. | Product | All | GDPR Arts 15–20, 28(3)(e); Qatar Art 17(4); ICO Code std 15 | **Yes** |
| 5 | **Retention schedule + automated purge** matching the periods in the policy (§ "How long we keep it"). | Product | All | GDPR Art 5(1)(e); every GCC regime | **Yes** |
| 6 | **Transfers to the US.** Execute: EU/UK SCCs + transfer impact assessment for Anthropic (and Render/Vercel unless DPF certification is confirmed); **Saudi SDAIA SCCs + documented transfer risk assessment**; **Oman explicit transfer consent** (carried by item 1) + impact assessment; UAE contractual safeguards. Consider Render's Frankfurt region for EU tenants. | Paperwork (+ hosting) | All | GDPR Ch V; Saudi Transfer Reg; Oman ER Arts 37–38; UAE Art 23 | **Yes** (KSA, Oman, EU) |
| 7 | **Qatar special-nature permit** for children's data, or exclude Qatar-resident students at launch. | Paperwork / decision | Qatar | PDPPL Art 16 | **Yes** (Qatar) |
| 8 | **Legal entity, address, representatives, DPO.** Name the controller; appoint an EU representative (GDPR Art 27), UK representative, DSA legal representative; Saudi authorised representative and registration if required; DPO (Oman effectively always; Saudi/EU likely). | Decision + paperwork | All | GDPR Art 27, 37; DSA Art 13; Saudi IR Art 32; Oman ER Art 35 | **Yes** |
| 9 | **A monitored privacy contact address** published in the policy and footer (`frontend/src/lib/site.ts → privacyEmail`). | Decision | All | Every regime | **Yes** |
| 10 | **Tutor terms + Data Processing Agreement** (Art 28(3) contents; sub-processor list and change notice; tutor warrants its lawful basis), accepted before a class is created. | Paperwork + product | All | GDPR Art 28; GCC controller/processor rules | **Yes** |
| 11 | **DPIA** (avora's own + a template tutors adopt), **records of processing**, Children's Code best-interests assessment. | Paperwork | All | GDPR Arts 30, 35; Saudi IR Art 25; ICO Code std 1–2 | **Yes** (EU/KSA) |
| 12 | **Breach runbook** with 72-hour regulator clock and user/guardian notice templates; needs transactional email (scheduled as the next scope). | Paperwork + product | All | GDPR Art 33–34; Saudi IR Art 24; Oman; Qatar; ADGM | **Yes** |
| 13 | **Special-category guardrails in tutor notes** — warn tutors not to record health/SEN information, or add a structured field with explicit consent. | Product | EU/UK, UAE, KSA, Oman | GDPR Art 9; sensitive-data rules | Advised |
| 14 | **Minimise what goes to the AI** — send page images and question context, not student names or ids. | Product | All | GDPR Art 5(1)(c); UAE MoE AI guide (signal) | Advised |
| 15 | **Arabic version** of the privacy policy. | Paperwork | Oman (expected), all GCC (advised) | Oman PDPL practice | Advised |
| 16 | **Anthropic terms check** — current API retention (a September 2026 change was reported and could not be read), zero-data-retention eligibility, and compliance with the minors guidelines incl. age verification. | Paperwork | All | Anthropic AUP + commercial terms | **Yes** (contractual) |
| 17 | **Access token out of `localStorage`** into memory, or a tighter CSP. | Product | All | GDPR Art 32 (security) | Advised |
| 18 | **Terms of Service** incl. DSA points of contact and notice-and-action. | Paperwork | EU | DSA Arts 11–17 | **Yes** (EU) |
| 19 | **AI Act high-risk readiness** for 2 Dec 2027: QMS, technical documentation, logging, human-oversight design, conformity assessment, EU authorised representative, registration. AI-literacy material for tutors now. | Product + paperwork | EU | AI Act Arts 4, 9–17, 22, 43–49, 72–73 | By Dec 2027 |

## What is already in good shape

These are real strengths a lawyer will want to know about:

- **Predicted grades are never produced by a model** — they are read through tutor-entered boundaries (PROD-6).
- **Remarks always go to a person**, one per question, with the AI's reasoning attached (AI-15) — a working
  human-review route.
- **Every tutor override is an append-only audit row** with no API to edit or delete it (PROD-7, AI-12).
- **Low-confidence or scheme-less marks never count without the tutor** (AI-11, ADR-0009).
- **Missing data is shown as missing, never as zero** (PROD-2) — fairness and accuracy.
- **Tenant isolation** by organization on every query (PROD-4, SEC-7), 404-not-403 on others' records (SEC-9).
- **Passwords hashed with bcrypt**; refresh token in an httpOnly cookie; credential invalidation via
  `token_version` (SEC-1, SEC-2).
- **Uploads validated by content, not client claims**; server-generated filenames (SEC-15, SEC-16).
- **The marking prompt treats student pages as data, never instructions** (SEC-20) — prompt-injection defence.
- **No analytics, ads or tracking**, so no consent banner is needed.
