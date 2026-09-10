# ADR-0010 — A chapter is its own table, not a parent topic

**Status:** Accepted · **Date:** 2026-09 · **Owner:** Architecture owner
**Supersedes:** — · **Superseded by:** —

## Context

`AV-9` sets the syllabus shape: **Subject → Chapter → Topic**. Marks, mistakes and readiness
attach at *topic* level; a chapter's score is rolled up from its topics.

`topics.parent_id` already existed and already held that shape in practice — the five seeded
syllabuses store "1. Number" as a root topic with "1.1 Integers" beneath it. Task 0.0's audit
recorded it precisely: *"`Topic.parent_id` exists but is read only for display, never for
rollup."* So the cheap answer was available: declare the root level to *be* chapters, add a
rollup that walks `parent_id`, and ship no migration at all.

## Decision

**`Chapter` is a separate table.** `Topic.parent_id` is kept, unchanged, and continues to mean
"genuine sub-topic beneath a chapter's topic".

`chapters` carries `subject_id`, `code`, `title`, `position` and `weight`. `topics` gains a
nullable `chapter_id`.

## Why not `parent_id`

Three things happen to a chapter that cannot happen to a topic, and each one breaks if the two
are the same row:

1. **The teaching plan schedules chapters** (Phase 6, `AV-14`). A slot points at a chapter. If a
   chapter is a topic row, every scheduling query has to carry "…and only the ones with no
   parent", and one place forgetting that clause schedules a sub-topic.
2. **A classified belongs to a chapter.** Material is filed against the unit being taught.
3. **Chapter readiness is stored, not computed on read** (`E7`). A stored rollup on a row that is
   *also* a markable topic gives that row two scores with the same name — its own evidence-based
   score and its children's rollup — with no type distinction between them.

The deciding argument is the second-order one. A parent topic is **markable**: nothing stops
evidence, a `QuestionTopic`, or a `LessonTopic` pointing at it, and the seeds prove that is not
hypothetical — `seed/demo.py` attaches evidence to the first eight topics by code, which
includes roots. A rollup that sums a chapter's topics would then double-count the chapter's own
evidence. Making the container a different table makes that mistake unrepresentable rather than
merely discouraged.

The cost is one table and one migration, paid once, against a "…and `parent_id IS NULL`" clause
that every future chapter-aware query would have to remember.

## `chapter_id` is nullable, deliberately

Syllabus extraction stays flat until task 2.3. A topic drafted by today's extractor has no
chapter to point at, and inventing one would fabricate structure the tutor never approved
(`PROD-2` — a value must be traceable to what produced it). The column tightens when 2.3 makes
the draft chapter-first.

## The backfill promotes rather than moves

Migration `0029` gives every root topic a `chapters` row copying its code, title and weight, and
points the whole subtree — the root row included — at it. **The root `topics` rows are kept.**

Deleting them would have been tidier and would have cascaded away demo evidence, lesson topics
and question topics attached to those rows. `E25` is explicit that "no production users" makes
destruction *safe*, not *reversible*. Task 2.2 deletes `seed/syllabus/*.json` outright and
rebuilds subjects per tutor, which is the right place for that removal.

For one phase, a seeded subject therefore has a chapter "1 Number" *and* a topic "1 Number".
That redundancy is temporary and visible, which is preferable to a migration that silently
destroys the demo account every later phase verifies against.

## The foreign key is composite

`topics(subject_id, chapter_id) → chapters(subject_id, id)`, not a plain key on `chapter_id`.

A single-column key validates only that the chapter *exists*. Nothing would stop a topic being
filed under a different subject's chapter, and a chapter rollup would then sum across subjects
— silently, and in the readiness numbers that drive every surface. That is the same failure this
ADR rejects `parent_id` to avoid, one level down, so it gets the same answer: make it
unrepresentable in the schema rather than discouraged in review.

Both columns sit in the constraint and `chapter_id` is nullable, so the default `MATCH SIMPLE`
skips the check entirely while `chapter_id` is `NULL` — exactly the "no chapter yet" state above.
`chapters` carries a redundant `UNIQUE (subject_id, id)` purely as the key's target.

The cost is that `Chapter.topics` and `Topic.chapter` are `viewonly`: the composite key shares
`subject_id` with `Subject.topics`, and two writable relationships claiming one column is what
SQLAlchemy warns about. `Topic.subject` owns `subject_id`; a topic joins a chapter by setting
`chapter_id`, which is what both build paths already do.

## Consequences

- `models/syllabus.py` gains `Chapter`; `Topic` gains `chapter_id` and a `chapter` relationship.
  Both new indexes are declared in the model as well as migration `0029` (`DB-12`).
- `seed/load_syllabus.py` creates chapters from top-level JSON nodes, mirroring the backfill so
  a freshly seeded database and a migrated one have the same shape (`E26`).
- Nothing reads `chapter_id` yet. Task 2.3 fills it from extraction, Phase 5 rolls readiness up
  through it, Phase 6 schedules against it.
- CI's `migrations` job runs `upgrade head` against an **empty** Postgres, so it cannot exercise
  the backfill. `tests/test_chapters.py` calls `promote_root_topics_to_chapters()` directly
  against rows three levels deep — the migration takes a connection rather than reaching for
  `op.get_bind()` for exactly that reason (`RISK-3`).

## Alternatives considered

**Root topics are chapters (`parent_id`, no new table).** Rejected above — free today, and it
makes a chapter both a container and a markable unit forever.

**A `kind` enum on `Topic` (`chapter` / `topic`).** One table, one discriminator. Rejected: it
does not stop a chapter-kind row being pointed at by `Evidence` or `QuestionTopic`, so it buys
the naming without the guarantee, and `DB-5`/`DB-6` note that nothing forces an audit of the
`if`/`match` chains over a non-native enum when a member is added.

**Chapters as a JSON column on `Subject`.** Rejected: a chapter is scheduled by the plan and
carries a stored readiness row, so it needs a stable identity a foreign key can reference.
