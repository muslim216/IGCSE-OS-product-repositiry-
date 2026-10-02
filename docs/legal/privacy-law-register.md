# avora — Privacy & AI Law Register (EU, UK, GCC)

**Type:** Research record (not legal advice). **Status:** Draft for counsel review. **As of:** 2 October 2026.
**Owner:** Founder. **Companion documents:** `pre-launch-privacy-gaps.md` (what must change before launch) and
the public policy at `frontend/src/legal/PrivacyPolicyPage.tsx` (route `/privacy`).

> This register records which laws affect avora, why, and what each requires, tied to avora's actual data
> flows as read from the code on the date above. It was compiled from primary sources where they could be
> reached and from law-firm commentary where they could not; every row says which. **A qualified lawyer in
> each launch jurisdiction must review it before launch.** Where a point is uncertain it says so — an
> uncertain point is listed as uncertain, never resolved by guessing.

---

## 1. The facts the analysis rests on

Read from the codebase on 2 Oct 2026. If any of these change, re-check the rows that depend on them.

| Fact | Detail | Where it matters |
|---|---|---|
| Who uses it | Tutors (adults) sign up themselves. Students (typically 13–17) join a tutor's class by invite code. Parents join by a single-use link and see only their own child. | Children's-data rules everywhere |
| Age | No date of birth or age is collected. No parental consent is captured. | GDPR Art 8, UAE CDS Law, Saudi IR Art 13, Oman Art 6, Qatar Art 17 |
| Data | Names, emails/usernames, bcrypt password hashes, role, time zone; student school, year group, parent name/email/phone; subject enrolments, target grades; **photos/PDFs of handwritten work**; AI-drafted marks, feedback, confidence; tutor-final marks with an append-only override audit; remark requests; categorised mistakes; tutor notes, observations, parent-communication logs; readiness scores, predicted grades; AI-written reports; schedules, shared files, recording links; AI usage/cost logs. | Every regime |
| Free text | Tutor notes and observations are free text and could contain health, SEN or family information. | GDPR Art 9; sensitive-data rules in UAE, KSA, Oman |
| AI | Student work is sent to **Anthropic's Claude API (USA)** for marking, extraction, reports and readiness synthesis. Google Gemini is configured but routes no traffic. | Transfers; automated decisions; AI Act |
| Auto-finalize | A mark **counts with no human review** when the AI is confident (high/medium) **and** an official mark scheme exists. It then feeds readiness and the predicted grade. Low confidence waits for the tutor. Students can request a remark (always to the tutor). Tutors can override anything. | GDPR Art 22; UK Art 22A–D; DIFC Art 38(4); UAE Art 18; Oman Art 14; AI Act Art 14 |
| Predicted grade | Computed from marks through **tutor-entered** grade boundaries — no model produces a grade (PROD-6). | Fairness; Art 22 effect analysis |
| Hosting | API, Postgres and uploaded files on **Render, region unset → US (Oregon)**. Website on **Vercel** (global CDN). | Transfers; Saudi/Oman transfer rules |
| Storage on device | One httpOnly refresh-token cookie scoped to `/api/v1/auth`; access token in `localStorage`. No analytics, ads or tracking. | ePrivacy Art 5(3); PECR |
| Rights tooling | **No self-service export or deletion**, no retention schedule, no tutor DPA, no records of processing. | Every regime |
| Entity | No legal entity yet; presents as "avora". | Scope, representatives, transfers — **re-run this register once the entity and its seat are chosen** |

---

## 2. Register

**Legend — Applies?** Yes / Likely / Unlikely / No. **Confidence** of the row: H = checked against primary text,
M = consistent secondary sources, L = single or unverified source.

### European Union

| Law | Applies? | Why | Key obligations for avora | Conf. | Sources |
|---|---|---|---|---|---|
| **GDPR** (Reg 2016/679) | **Yes** | Art 3(2): services offered to people in the EU and their behaviour monitored (readiness and predicted grades are profiling, Art 4(4)) with no EU establishment. | Art 27 EU representative (the "occasional" exemption cannot apply to systematic processing of children's data). Controller/processor split: **tutor = controller** of class data, **avora = processor** for it and **controller** of accounts, security and usage logs. Art 28 DPA with every tutor. Art 13/14 notices, child-appropriate (Art 12(1)). Arts 15–22 rights incl. **Art 22** (auto-finalized marks — see §3). **DPIA** expected (children + scoring + new technology). Art 30 records. 72-hour breach notice (Art 33). Chapter V transfers. Storage limitation. Art 9 for any health/SEN content in notes. | H | eur-lex.europa.eu/eli/reg/2016/679/oj; EDPB Guidelines 3/2018 (scope), 07/2020 (roles), 05/2020 (consent); WP251 (ADM), WP248 (DPIA), WP260 (transparency) |
| **GDPR Art 8** — child consent age | Narrowly | Only bites where **consent** is the basis for a service offered directly to a child. avora's primary basis for class data is not consent (see §3), but any optional consent-based processing triggers it. Ages: 13 (BE, DK, EE, FI, LV, MT, PT, SE), 14 (AT, BG, CY, IT, LT, ES), 15 (CZ, FR, GR, SI), 16 (DE, HR, HU, IE, LU, NL, PL, RO, SK). Spain: bill to raise to 16 pending. | Treat every student as a child; do not rely on a child's own consent. | M | euconsent.eu table (2021) — verify against national acts |
| **EU AI Act** (Reg 2024/1689) as amended by **Digital Omnibus on AI, Reg (EU) 2026/1744** (in force 27 Jul 2026) | **Likely, from 2 Dec 2027** | Annex III point 3(b): AI "intended to be used to evaluate learning outcomes". Art 6(3) derogation is unavailable where the system profiles people — readiness does. Open point: whether a private tutor is an "educational institution" (draft Commission guidelines reportedly read it broadly). | **Now:** Art 4 AI literacy (softened by the Omnibus), Art 5 prohibitions (never add emotion recognition), Art 50 transparency (applies since 2 Aug 2026). **From 2 Dec 2027 if high-risk:** risk management, data governance, technical documentation, logging, instructions for use, **human oversight (Art 14)**, accuracy, QMS, conformity assessment, CE marking, EU database registration, post-market monitoring, an EU authorised representative. Tutors as deployers: Art 26 duties incl. informing students, Art 86 explanations. | H (dates), M (scope) | eur-lex.europa.eu/eli/reg/2024/1689/oj; eur-lex.europa.eu/eli/reg/2026/1744/oj; independently confirmed by multiple trackers (e.g. euaiact.com/digital-omnibus-ai, praxikon.com) |
| **ePrivacy Directive** Art 5(3) | Yes — exempt | The auth cookie and the localStorage token are "storage" (EDPB Guidelines 2/2023 confirm localStorage). Both are strictly necessary for a login the user asked for. | **No consent banner needed.** Disclose both in the policy. Any future analytics needs consent. | H | eur-lex.europa.eu/eli/dir/2002/58/oj; EDPB Guidelines 2/2023; WP194 |
| **Digital Services Act** (Reg 2022/2065) | Yes — light | avora hosts user uploads (a hosting service). Content is shared in closed classes, not with the public, so probably not an "online platform". | Points of contact (Arts 11–12), EU legal representative (Art 13), clear terms (Art 14), notice-and-action (Art 16), statements of reasons (Art 17). Belongs in the **Terms of Service** (not yet written). | M | eur-lex.europa.eu/eli/reg/2022/2065/oj |
| **EU–US Data Privacy Framework** (Decision 2023/1795) | Relevant | Upheld by the General Court (*Latombe*, T-553/23, 3 Sep 2025); appeal C-703/25 P pending. | Use DPF only where a provider is certified; keep SCCs as fallback. Anthropic relies on SCCs, not the DPF (per its DPA). Render/Vercel certification **must be confirmed from their current documents** (not independently verified here). | M | eur-lex.europa.eu/eli/dec_impl/2023/1795/oj; anthropic.com/legal/data-processing-addendum |

### United Kingdom (adjacent market)

| Law | Applies? | Why | Key obligations | Conf. | Sources |
|---|---|---|---|---|---|
| **UK GDPR + DPA 2018**, as amended by the **Data (Use and Access) Act 2025** | Yes, if UK users | UK GDPR Art 3(2). Main DUAA data provisions commenced 5 Feb 2026 (SI 2026/82); complaints duty from 19 Jun 2026. | UK representative. New Arts 22A–D: solely automated significant decisions allowed with safeguards (information, representations, human intervention, contest). Children's "higher protection matters" in Art 25. Statutory complaints route (acknowledge within 30 days). | M–H | legislation.gov.uk/ukpga/2025/18; ico.org.uk DUAA summary |
| **ICO Age Appropriate Design Code** | Yes | Online service likely accessed by under-18s; not provided on a school's instruction. | Best interests, DPIA, age-appropriate application (assume all students are children), bite-sized transparency, no detrimental use, high-privacy defaults, minimisation, data-sharing care, **tell the child a parent can see their record**, profiling off by default unless justified (readiness is core — document the justification), no nudges, online rights tools. | M | ico.org.uk Children's Code + edtech guidance |
| **PECR** reg 6 | Yes — exempt | Same as ePrivacy. | Disclose only. | H | ico.org.uk storage-and-access guidance |

### GCC

| Law | Applies? | Why | Key obligations | Conf. | Sources |
|---|---|---|---|---|---|
| **UAE PDPL** (Federal Decree-Law 45/2021) | **Yes** | Art 2 reaches controllers outside the UAE processing data of people in the UAE. | Consent-led (no general legitimate-interest basis). Art 18 right to object to automated decisions with serious effect. Transfers: no adequacy list exists — contractual safeguards or express consent. DPO where high-risk new technology. **Executive Regulations still not issued** (breach deadlines, response deadlines, penalties pending). | M | uaelegislation.gov.ae/en/legislations/1972; DLA Piper; Chambers 2026 |
| **UAE Child Digital Safety Law** (Federal Decree-Law 26/2025) | **Likely** | Covers platforms operating in or targeting users in the UAE; in force 1 Jan 2026, enforceable ~1 Jan 2027. Edtech scope not expressly addressed. | Child = under 18. **Explicit, documented, verifiable parental consent before processing data of under-13s**; easy withdrawal; high-privacy defaults; no advertising use of children's data; age-assurance and parental tools. Cabinet decisions on methods pending. | H (existence/consent), M (scope) | uaelegislation.gov.ae/en/legislations/3912; Baker McKenzie, Clyde & Co, Hogan Lovells (Jan 2026) |
| **UAE age of majority** | Context | Civil Transactions Law (FDL 25/2025), in force 1 Jun 2026, lowers majority from 21 to 18. | Under-18 students lack capacity — guardian acts. | M | Tamimi |
| **UAE MoE AI-in-classrooms guide (2026)** | Unlikely (schools) | Addressed to schools; bans generative AI for under-13s in schools and uploading student personal data into AI systems. | Signal of regulator expectations: minimise identifying data sent to the AI. | L | Gulf News report |
| **DIFC DP Law 2020** (amended Jul 2025) + Regulation 10 (AI) | Unlikely | Applies to DIFC-incorporated entities or processing in the DIFC as part of stable arrangements. **Becomes Yes if avora incorporates in the DIFC.** | If in scope: Art 38(4) — the contract/law/consent exceptions to the automated-decision objection **do not apply to minors**; Regulation 10 notices for autonomous systems. | H | DIFC consolidated law (Jul 2025) |
| **ADGM DPR 2021** | Unlikely | Establishment-based. Becomes Yes if incorporated in ADGM. | GDPR-style; 72h breach notice. | M | ADGM consolidated regulations |
| **Saudi PDPL** (Royal Decree M/19, amended M/148) + Implementing Regulations + Transfer Regulation | **Yes** | Art 2 covers processing of data of people residing in the Kingdom by any entity outside it. | Guardian consents for minors, **guardianship must be verified** (IR Art 13). DPIA for large-scale processing of vulnerable groups (IR Art 25). **Transfers to the US: no adequacy list → SDAIA SCCs / binding rules / certificate + documented transfer risk assessment**, minimal and necessary. Registration on the National Data Governance Platform where processing is the core activity (draft 2025 amendments would extend to minors' data — not final). DPO where core activity is monitoring. 72h breach notice to SDAIA. 30-day responses. Fines up to SAR 5m. | M (SDAIA PDF not machine-readable; secondary article mapping) | sdaia.gov.sa Implementing Regulations; Mayer Brown, King & Spalding, Morgan Lewis |
| **Qatar PDPPL** (Law 13/2016) | Unclear → plan as Yes | Art 2 has no territorial limit; commonly read to reach services aimed at Qatar residents. | **Art 16: data "related to children" is special-nature — processing needs permission from the competent department.** **Art 17: a website addressing children must post a child-data notice, obtain explicit guardian consent, and give guardians access, a copy and deletion.** Fines up to QAR 5m for Art 16/17 breaches. Cross-border flow broadly permitted (Art 15). | H (text checked) | Law 13/2016 English text; NCSA |
| **QFC DPR 2021** | No | QFC-licensed firms only. | — | M | QFC guidance |
| **Bahrain PDPL** (Law 30/2018) | Unlikely | Foreign controllers caught where processing uses means in the Kingdom; avora uses none. | If in scope: US on the adequacy list (Res. 42/2022); 72h breach notice. | M–L | pdp.gov.bh; DLA Piper |
| **Oman PDPL** (RD 6/2022) + Executive Regulation (MD 34/2024) | **Yes** | Art 2 covers data of people in Oman processed inside or outside Oman. Fully enforceable since 5 Feb 2026. | **Art 6: no processing of a child's data without guardian approval.** Explicit consent is the core basis. **Transfer abroad: explicit consent + equivalent protection + transfer impact assessment**; unlawful transfer fines OMR 100–500k. DPO effectively required. 72h breach notice. 45-day responses. Arabic expected. | M | decree.om/2022/l20220006; MTCIT; CMS, Addleshaw Goddard |
| **Kuwait** (CITRA DPPR, Decision 26/2024) | No | Narrowed to CITRA telecom/ICT licensees; no general data-protection law. | Monitor. | M | Chambers 2026 |

### Contractual — sub-processors

| Instrument | Applies? | Why | Obligations | Conf. | Sources |
|---|---|---|---|---|---|
| **Anthropic Usage Policy** | **Yes** | avora's product serves minors through the API. | "Products serving minors … must comply with the additional guidelines": **age verification**, content moderation and filtering, monitoring and reporting, guidance for minors on safe use, **compliance with applicable child privacy laws, documented publicly**, and **disclosure to users that they are interacting with an AI system**. Anthropic audits and may suspend. | H (read 2 Oct 2026) | anthropic.com/legal/aup; support.claude.com article 9307344 |
| **Anthropic commercial terms / DPA** | Yes | Governs student work sent for marking. | Commercial terms: no training on customer content. API baseline retention reported as 30 days. A September 2026 change to retention was reported (CNBC, 1 Sep 2026) and **could not be read — confirm current retention and any zero-data-retention eligibility before launch.** DPA incorporates SCCs and UK/Swiss addenda. | M | anthropic.com/legal/commercial-terms; /data-processing-addendum |

---

## 3. The hard questions, analysed

### 3.1 Is auto-finalized marking an automated decision about a child?

**Probably treat it as one.** A mark that counts with no human review is "solely automated" — a later override
does not change that (WP251). It feeds a predicted grade; the CJEU held in *SCHUFA* (C-634/21) that a score can
itself be a decision where others rely on it strongly, and WP251 lists effects on access to education as
potentially significant. A predicted grade shared with a parent and used for exam-tier or school decisions could
qualify. GDPR Recital 71 says such decisions "should not concern a child"; DIFC Art 38(4) removes the usual
exceptions for minors outright; the UAE (Art 18) and Oman (Art 14) give a right to object; the AI Act's Art 14
requires human oversight from Dec 2027.

**Recommended design (in `pre-launch-privacy-gaps.md`, item 2):** make auto-finalize a per-class tutor choice,
**off by default**; label every AI-finalized mark as such to student and parent; keep the remark route as the
human-review right; consider excluding unreviewed marks from the predicted grade shown to students and parents.

### 3.2 Who is the controller?

The **tutor** decides why student data is processed (tutoring that student) — controller. **avora** processes it
on the tutor's instructions — processor — and is controller for its own purposes (accounts, security, usage
logs). The risk: avora designs auto-finalize and the readiness logic, arguably "essential means". The
arrangement holds if those are documented features the tutor chooses in the DPA, and avora never reuses class
data for its own ends (no training, no benchmarking, no analytics on student content). Any such reuse risks joint
controllership.

### 3.3 Which lawful basis for student data?

There is no single basis valid everywhere. Consent is the only basis that works in Oman, Qatar and (for children)
the UAE, and guardian consent is mandated for minors in Saudi Arabia, Oman and Qatar and for under-13s in the
UAE. The EU and UK prefer **legitimate interests or contract** for core processing and warn against relying on a
child's consent. **The unifying design:** for every student under 18, a **verified parent or guardian gives
documented consent before the student's data is processed**, recorded append-only with a one-step withdrawal —
while the tutor, as controller, records its own lawful basis (legitimate interests or contract with the parent)
for EU/UK purposes. This satisfies the strictest GCC rule without making EU processing hostage to consent.

### 3.4 Transfers to the United States

All data sits in the US. The strictest regimes are **Saudi Arabia** (SDAIA SCCs + documented risk assessment +
necessity) and **Oman** (explicit consent to transfer + impact assessment). The EU and UK need SCCs + a transfer
impact assessment for Anthropic, and DPF or SCCs for Render and Vercel. Options: execute the mechanisms per
region; host EU tenants in Render's Frankfurt region; or exclude a market at launch until counsel signs off.

---

## 4. Open questions for counsel

1. Seat of the legal entity (EU, UAE mainland, DIFC, ADGM, elsewhere) and its effect on every row above.
2. Processor vs joint controller, given auto-finalize and readiness design.
3. Whether a shared predicted grade has a legal or similarly significant effect (GDPR Art 22, UAE Art 18, DIFC
   Art 38, Oman Art 14), and whether any exception is usable for minors.
4. Whether a private tutor is an "educational institution" under AI Act Annex III 3(b); whether the Art 27
   fundamental-rights impact assessment applies.
5. Whether the UAE Child Digital Safety Law covers closed, tutor-to-student education software, and which
   age-assurance method the Cabinet will accept.
6. Status of the UAE PDPL Executive Regulations.
7. Saudi: whether SDAIA accepts SCCs signed only between avora and its US vendors; registration duty for a foreign
   controller; status of the 2025 draft amendments (minors' data, transfers).
8. Qatar: whether avora is a "website addressing children" (Art 17); how to obtain an Art 16 permit and how long
   it takes; whether Art 2 reaches a foreign service.
9. Oman: whether guardian consent can carry the transfer consent; whether the DPO must be in Oman.
10. DPO requirement (GDPR Art 37(1)(b), Saudi, Oman) and EU/UK representative appointment.
11. Anthropic's current API retention terms and zero-data-retention eligibility; compliance with its minors
    guidelines (age verification in particular).
12. DSA: confirm hosting-service-only classification; content of the Terms of Service.

---

## 5. Change log

| Date | Change |
|---|---|
| 2026-10-02 | First version, compiled from EU/UK and GCC research passes; key claims spot-checked (AI Act Omnibus dates, UAE CDS Law consent rule, Anthropic AUP minors requirements). |
