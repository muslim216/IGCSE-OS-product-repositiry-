# Pricing

**Decided 2026-10-10 by the owner.** Supersedes the 2026-10-02 USD price ($19 + $5 per active
student). The landing page (`/#pricing` and the FAQ) still shows the superseded price until
`frontend/src/marketing/LandingPage.tsx` is updated in a separate PR.

## The price

| | Flat fee | Per active student |
|---|---|---|
| Standard (tutor 11 onward) | **300 QAR / month** | **30 QAR / month** |
| Pilot (first 10 tutors) | **150 QAR / month** (50% off) | **15 QAR / month** (50% off) |

| | |
|---|---|
| Customer | The tutor. Students and parents never pay — they join through their tutor |
| Currency | Billed in QAR. USD figures below use the peg, 1 USD = 3.64 QAR, and are approximate |
| Cap on the pilot rate | The first 10 tutors only, fixed in writing when they join |

**Active student:** a student with any activity in the billing month — submitted work, an
attended tracked lesson, or a report sent. A student who takes a month off costs the tutor
nothing.

Worked examples (standard, then pilot):

| Active students | Standard | ≈ USD | Pilot | Share of tutor revenue (standard)¹ |
|---|---|---|---|---|
| 30 | 1,200 QAR | $330 | 600 QAR | 10% |
| 60 | 2,100 QAR | $577 | 1,050 QAR | 8.75% |
| 100 | 3,300 QAR | $907 | 1,650 QAR | 8.25% |

¹ Assumes the tutor earns about 400 QAR per student per month (50 QAR per lesson, two lessons
a week), the typical online group rate in Qatar.

## Why this price

The price is set against the value to the tutor, not against cost. The target is a bill of
roughly 6–9% of what a tutor earns from the students on Avora, because tools that save a
professional time usually sit well below the 10–20% that marketplaces charge for bringing
customers. An earlier draft of this price took about 13% of tutor revenue (50 QAR per student);
that was judged too high for a first price, and is the ceiling to test later, not the baseline.

Per active student, because the tutor's bill should grow with the work Avora does for them. The
flat fee screens out tutors who will not commit and covers the fixed share of hosting.

## The cost model behind it (estimate — replace with measured numbers)

Marking runs on `claude-opus-5` ($5 input / $25 output per million tokens); reports on
`claude-sonnet-5` ($2 / $10).

| Item | Estimate |
|---|---|
| One marked submission (~20k input tokens: prompt, booklet, mark scheme, ~4 page photos; ~3k output) | $0.15–0.25 |
| Marking, ~8 submissions per student per month | $1.40–2.00 |
| Readiness recomputes (Opus) | ~$0.30 |
| Monthly report (Sonnet) | ~$0.05 |
| Assignment extraction, amortised across a class | ~$0.10 |
| **AI cost per active student per month** | **≈ $2–2.50 (about 7–9 QAR)** |
| Hosting (Render + Vercel), fixed | ~$30–50 / month total |

At 30 QAR (≈ $8.24) per student the gross margin on AI cost is roughly 70–76%. The pilot rate
of 15 QAR (≈ $4.12) leaves roughly 40–50%, and runs close to break-even on the heaviest users.
That is accepted only because the pilot is short and the rate is capped to ten tutors.

Widening "active student" beyond marked work means some active students cost almost nothing to
serve (a lesson attended, a report sent, no marking), which only improves the margin above.

**These are estimates.** During the pilot, fill `AI_MODEL_PRICING` so `ai_usage_events`
records a `cost_usd` per call (`AI-17`). That figure is computed from the call's measured
token counts and the configured rates — still an estimate of spend, not a bill — so reconcile
it each month against the Anthropic invoice before revisiting the price against cost per
active student. Moving marking to Sonnet would cut cost by about 60%, but only if an eval shows
marking quality holds.

## Competitor reference points (gathered 2026-09)

| Product | Price |
|---|---|
| Marking.ai | from ~£21 / month |
| Grade Direct | Free tier; Teacher Pro $25 for 6,000 credits |
| AI Buddy | SGD 96 / year per licence |
| Teach Space | Free up to 5 students, paid tiers above |

These are per-teacher marking tools. Avora covers the whole loop (plan, lessons, homework,
marking, student records, reports, follow-up), so the standard price for a 60-student tutor is
far above them. Expect tutors to make that comparison, and test the price against it in the pilot.

## Open

- Billing provider and invoicing (not built — nothing charges yet).
- Pilot discount duration. The previous plan was 12 months; a shorter fixed end date is safer
  given the pilot margin above. Not yet decided.
- Whether any free period precedes the paid pilot rate. Not yet decided.
- Whether a volume break is needed for large tutors (considered: 30 QAR for the first 50
  students, less beyond), or a multi-tutor centre plan.
- VAT: UAE (5%) and Saudi (15%) registration thresholds once revenue exists; confirm the
  position for Qatar.
- Whether Egypt gets its own price. Egypt is deferred; Qatar and UAE come first, Saudi next.
