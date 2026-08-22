# 03 — The Readiness Engine

*How a mark on a page becomes "this student is 68% ready and heading for a grade 6."*

This is the centre of the product. Everything else exists to feed it or display it.

---

## The problem it solves

A tutor teaches a student for a year. The parent asks the only question that matters: *"is my child going to get the grade?"*

Traditionally the answer is a mock exam, three months before the real thing, and gut feeling before that. The mock is a good signal but it arrives late, and it's one snapshot of one day.

Avora's answer: every piece of work the student has already done is a signal. There have been dozens of them. Nobody was adding them up.

---

## Step one — evidence

Every settled piece of academic work becomes a permanent **evidence** record: what topic it was, how the student did, when, and where it came from.

Five kinds of evidence, and they are explicitly not equal:

| Source | Weight | Why |
|---|---|---|
| **Full past paper** | 1.8 | A whole paper under exam conditions — the strongest signal available |
| **Mock exam** | 1.5 | Supervised and whole-paper, but not the real format |
| **Homework** | 1.0 | The baseline everything else is measured against |
| **Quiz** | 0.8 | Narrow and short |
| **Tutor observation** | 0.5 | Genuine expertise, but subjective |

So a past paper counts for a bit more than three times what a tutor's impression counts for. That ratio is a real product decision, visible in the code, and adjustable.

### The rule that protects the whole thing

**Only finalised work becomes evidence.** Never a draft. Never an AI suggestion the tutor hasn't accepted or that hasn't passed the automatic-acceptance test. Nothing provisional ever moves a readiness score.

The reason is commercial as much as technical. Readiness scores are shown to parents. A score that moved because of a draft mark the tutor later rejected is indefensible in a conversation with a parent — and that single conversation would cost the customer.

There's exactly one piece of code in the entire system allowed to create evidence. Everything routes through it. That's what makes the rule enforceable rather than aspirational.

---

## Step two — decay

Evidence gets **less important as it ages**, on a 45-day half-life.

That means a mark from 45 days ago counts half as much as one from today. From 90 days ago, a quarter. It never disappears entirely, it just fades.

This is what makes the score *current* rather than cumulative. A student who struggled in September and has been solid since October should read as ready — because they are. A simple average would hold September against them all year.

It cuts the other way too: a student coasting on strong early results sees their score slide if they stop producing new work. That's the honest signal, and it's the one that prompts a tutor to intervene.

---

## Step three — confidence

Separately from the score, the engine tracks **how much it trusts the score.**

A topic with three recent pieces of evidence has high confidence. A topic with one piece from two months ago has low confidence. A topic with nothing at all has **none** — and displays as *"not enough data yet."*

This is treated as a hard rule across the entire product: **absence of data is a fact, not a zero.** A topic never renders as 0%, and never as an empty progress bar that reads as zero.

The reason is worth stating plainly. If a student hasn't attempted trigonometry yet, showing 0% tells them — and their parent — that they failed something they never sat. That's not a display bug, it's the product lying. So it's enforced inside the engine itself rather than left to each screen to remember.

---

## Step four — the seven factors

Readiness isn't one calculation. It's seven separate ones, each answering a different question:

| Factor | The question it answers |
|---|---|
| **Topic Mastery** | Do they actually know the material, across easy *and* hard questions? |
| **Past Paper Performance** | How do they do on whole papers under conditions? |
| **Homework Performance** | Accuracy, quality, completion, timeliness |
| **Assessment Performance** | Quizzes, topic tests, mocks |
| **Syllabus Coverage** | How much of the syllabus has been taught, practised, mastered? |
| **Mistake Analysis** | Are the same mistakes recurring? |
| **Consistency** | Do they hand work in, on time, reliably? |

Each is calculated by ordinary, predictable code from stored records — no AI, no judgement, fully reproducible. Run it twice on the same data and you get the same answer both times.

**Tutors can weight these themselves.** A tutor who thinks consistency predicts exam results better than mock scores can say so, and every student they teach is recalculated.

Two subtleties in there that show the domain thinking:

**Topic Mastery buckets questions by difficulty.** Getting every easy question right is familiarity. Mastery means holding up across the tiers. A single average would score those two students identically.

**Syllabus Coverage is derived, never declared.** It comes from what lessons actually recorded as taught. There's no manual checklist, deliberately — see [02](02-core-features.md).

---

## Step five — synthesis

The seven factor scores, the tutor's weightings, and the tutor's own knowledge base go to an AI model, which produces:

- an overall readiness score
- the weak topics to focus on
- a written explanation of *why*
- a revision plan

**The AI's job here is narrow and it's important to be precise about it.** It isn't asked to judge the student. It's given seven numbers and *instructed* not to contradict them, then asked to weigh them and explain the result in language a person can act on. That constraint lives in the prompt, not in a check the backend runs on the response afterward — today nothing compares the model's synthesized score against the factor rows before saving it.

It cannot decide a student is stronger than the evidence says. It's a translator from numbers to guidance, not a judge.

### The grade is never the AI's

The model returns a *score*. Plain, predictable code converts that score into a *grade*, using boundaries the tutor entered for that specific subject.

A grade is a factual claim about an exam board's published boundaries. It isn't an opinion, so it isn't left to something that forms opinions. And 70% genuinely can be an A\* in one subject and not another — a model has no way to know that, and would be guessing.

---

## What happens when it goes wrong

Three failure behaviours worth knowing, because they show the engineering standard:

**A failed run keeps its work.** If the AI step fails, the seven factor calculations that already succeeded are kept, and the run is marked failed. The expensive deterministic work isn't thrown away because the last step didn't land.

**"Updating" is honest.** While a recalculation is running, the app shows the last known score labelled as updating — rather than showing a stale number as if it were current, or blanking the page.

**Bursts are collapsed.** If a student submits five pieces of work in an hour, that's *one* recalculation ten minutes later, not five. This is a cost control — the synthesis step uses the most expensive model in the system.

---

## The part that's genuinely broken

**There are two readiness engines, and both are running.**

An older one and a newer one. The main readiness screens use the new engine. Reports, analytics, and the student record page still read the old one.

Which means a tutor can see one readiness number on the readiness page, open that student's report, and see a **different number for the same student on the same day.** Both were calculated correctly. They just came from different engines.

This is a migration that was started deliberately and paused deliberately — the new engine is better and the intent is to retire the old one. Nothing about it is accidental. But it hasn't been finished, and every day it isn't finished is a day a tutor might notice.

It matters more than a typical piece of unfinished work because of what the product sells. Avora's differentiator is that its numbers are trustworthy and traceable. A tutor who catches the same student showing two different scores doesn't file a bug report — they stop trusting the number. And once the number isn't trusted, there's no reason to pay for the product.

It's covered as weakness #3 in the [weaknesses document](../Product-Overview-and-Weaknesses.md).

---

## The rule that makes all of this defensible

> **No number exists unless the system can say where it came from.**

Every readiness score traces to specific factor calculations, which trace to specific evidence records — and, where that evidence is a marked question (homework, quiz, mock, past paper), to specific marks on specific questions on specific dates.

Two of the six evidence sources are deliberately not question marks: a tutor's `observation`, and the `tutor_estimate` a tutor enters before any work has been marked. Both are weighted lowest precisely because they aren't marks on a piece of work, and the estimate loses weight as real evidence arrives. The syllabus-coverage factor is different again — it's derived from which topics lessons actually covered, not from evidence rows at all. So the guarantee isn't "every number came from a question mark"; it's that every number came from a specific, named, queryable record.

This constraint shaped the entire database. It's why each factor calculation is written as its own permanent record rather than bundled into a blob — because a blob can't be queried, and a number you can't interrogate is a number you can't defend.

The practical consequence: when a tutor says *"why is this student only 60%?"*, there's an actual answer. Not "the model determined it," but a list of the work that produced it.

That's the difference between a product a tutor trusts with a parent conversation and one they quietly stop opening. Competitors can copy AI marking in a weekend. Copying this means rebuilding the data model.
