# Pricing

**Decided 2026-10-02 by the owner.** Published on the landing page (`/#pricing` and the FAQ).

## The price

| | |
|---|---|
| Pilot | Free, every feature |
| After the pilot | **$19 / month** platform fee **+ $5 per active student / month** |
| Founding offer | Pilot tutors: **40% off for their first 12 months** on a paid plan |
| Students and parents | Never pay — they join through their tutor |
| Currency | Billed in USD; AED shown as an approximate conversion (≈ AED 70 + AED 18) |

**Active student:** a student who had at least one piece of work marked in the billing month.
A student who takes a month off costs the tutor nothing.

Worked examples: 5 students → $44; 15 → $94; 30 → $169.

## Why per active student

Our main variable cost is the AI call behind every marked submission, so cost scales with
marked work, not with seats. A flat tier would lose money on the busiest tutors; pricing on
active students keeps margin roughly constant as a tutor grows, and the base fee covers the
fixed share of hosting.

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
| **AI cost per active student per month** | **≈ $2–2.50** |
| Hosting (Render + Vercel), fixed | ~$30–50 / month total |

At $5 per student the gross margin on AI cost is roughly 50–60%; the founding discount
($3 per student) runs close to break-even on heavy users, which is accepted for the first year.

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

## Open

- Billing provider and invoicing (not built — nothing charges yet).
- Whether a multi-tutor centre plan is needed.
- VAT: UAE (5%) and Saudi (15%) VAT registration thresholds once revenue exists.
