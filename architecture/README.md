# Avora — Architecture & Core Features

**A plain-English explanation of how the product is built and what it does**
Written 6 August 2026 · Based on a full read of the codebase

---

## About the name

The product is named **Avora** by OASIS AI — renamed from its working name, **MANARA**, across the codebase, docs and package names.

These documents use **Avora** throughout. Where older external material or the deployment identifiers still say IGCSE-OS, it is the same system.

## Who these documents are for

Anyone who needs to understand how Avora works without being able to read the code: a product manager, a founder, an investor doing diligence, a new hire on their first day, or someone building alongside it with AI assistance.

No prior technical knowledge is assumed. Where a technical term is unavoidable, it's explained the first time it appears. Real file names and numbers are included so a developer can follow the same trail — you can skip those safely.

## What's here

| Document | What it covers | Read it if… |
|---|---|---|
| [01 — How it all fits together](01-how-it-all-fits-together.md) | The big picture: the three pieces of the system, what happens when someone clicks something, where it's hosted | You want the map. **Start here.** |
| [02 — Core features](02-core-features.md) | The six things the product does, and what each looks like for a tutor, student and parent | You want to know what it actually does |
| [03 — The readiness engine](03-the-readiness-engine.md) | How a mark on a page becomes an exam-readiness score — the heart of the product | You want to understand the differentiator |
| [04 — The AI layer](04-the-ai-layer.md) | The eight places AI is used, which model does what, and the rules on when AI is trusted without a human | You want to know where the AI is and how it's controlled |
| [05 — Data and storage](05-data-and-storage.md) | What gets stored, how it's organised, and the deliberate design rules behind it | You want to understand the asset the company owns |

## Reading order

If you only read one, read **01**. If you read two, read **01** and **03** — together they explain both how the machine is put together and why it's worth anything.

A full pass through all five is about forty minutes.

## A companion document

The folder above this one contains **[Product-Overview-and-Weaknesses.md](../Product-Overview-and-Weaknesses.md)**, which covers what the product is commercially and where it's fragile.

These documents describe how Avora is built and are deliberately **not** a critique. Where a design decision has a known cost, it's noted honestly and pointed at the weaknesses document rather than argued here.

## The one-paragraph summary, if you read nothing else

Avora is an operating system for IGCSE tutoring. Tutors upload past-paper PDFs; AI pulls out the individual questions and sends them to students as homework. Students photograph handwritten work on their phones; AI marks it question by question against the official mark scheme. Every mark becomes permanent evidence behind a per-topic **readiness score** and a predicted grade for each student. Tutors see what to teach next, students see where they're weak, parents see plain-language progress. The defining rule is that **every number can be traced back to the specific work that produced it** — nothing is a black box, and a tutor can always overrule the AI.
