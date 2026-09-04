"""Subject -> Chapter -> Topic, and the paths that build it (tasks 2.1/2.2, AV-9).

The migration backfill is tested here rather than left to CI's migrations job.
That job runs `upgrade head` against an **empty** Postgres, so the reparenting
loop never touches a row there — it would report green on a backfill that
silently did nothing. `RISK-3` is the named, already-realised failure of trusting
a migration nobody exercised.
"""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import async_session
from app.models import Chapter, Organization, Subject, SubjectLevel, Topic
from seed.demo import CHEMISTRY, build_subject

MIGRATION = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0029_chapters.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_0029", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _org(session, name: str = "Test Org") -> Organization:
    org = Organization(name=name)
    session.add(org)
    await session.flush()
    return org


async def _subject(session, org: Organization, code: str, name: str = "Testing") -> Subject:
    subject = Subject(
        organization_id=org.id,
        exam_board="Test Board",
        code=code,
        name=name,
        level=SubjectLevel.igcse,
        grade_scale="9-1",
        grade_boundaries=[],
    )
    session.add(subject)
    await session.flush()
    return subject


async def test_the_demo_subject_is_built_chapter_first():
    """`seed/demo.py` builds the tree the product now has (AV-8, AV-9).

    Replaces the old `load_syllabus` seeding test: the five built-in syllabuses
    and their loader were deleted in task 2.2, so the assertion moves to the path
    that replaced them rather than being dropped (`E26`).
    """
    async with async_session() as session:
        org = await _org(session)
        subject = await build_subject(session, organization_id=org.id, data=CHEMISTRY)
        await session.commit()

        assert subject.organization_id == org.id
        assert subject.level is SubjectLevel.igcse

        chapters = (await session.scalars(select(Chapter).order_by(Chapter.position))).all()
        assert [(c.code, c.position) for c in chapters] == [("1", 1), ("2", 2), ("3", 3)]
        assert chapters[0].weight == 1.4

        topics = (await session.scalars(select(Topic).order_by(Topic.code))).all()
        # Every topic is a leaf under a chapter — no root topic doubles as one,
        # which is what migration 0029 had to preserve for the old seeds.
        assert len(topics) == 9
        assert all(t.chapter_id is not None for t in topics)
        assert all(t.parent_id is None for t in topics)
        by_chapter = {c.id: c.code for c in chapters}
        assert by_chapter[topics[0].chapter_id] == "1"
        assert by_chapter[topics[-1].chapter_id] == "3"


async def test_a_topic_with_no_chapter_is_valid():
    """Nullable until extraction is chapter-first (task 2.3).

    Today's flat extractor has no chapter to point at, and inventing one would
    fabricate structure the tutor never approved (`PROD-2`).
    """
    async with async_session() as session:
        org = await _org(session)
        subject = await _subject(session, org, "T200", "Unchaptered")
        session.add(Topic(subject_id=subject.id, code="1", title="Loose"))
        await session.commit()

        topic = await session.scalar(select(Topic).where(Topic.code == "1"))
        assert topic.chapter_id is None


async def test_a_topic_cannot_be_filed_under_another_subjects_chapter():
    """The foreign key is composite — (subject_id, chapter_id), not chapter_id.

    A single-column FK validates only that the chapter exists, so a topic could
    point at a chapter belonging to a different subject and a chapter rollup
    would quietly sum across subjects. `ADR-0010` argues a table over `parent_id`
    precisely to make that class of mistake unrepresentable; this is the same
    argument one level down.

    SQLite does not enforce foreign keys unless asked, and the suite does not ask
    — so this test turns enforcement on for itself and back off afterwards,
    because `conftest.py` shares one `StaticPool` connection across tests.
    """
    async with async_session() as session:
        connection = await session.connection()
        await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        try:
            org = await _org(session)
            maths = await _subject(session, org, "T400", "Maths")
            physics = await _subject(session, org, "T401", "Physics")

            maths_chapter = Chapter(subject_id=maths.id, code="1", title="Number", position=1)
            session.add(maths_chapter)
            await session.flush()

            # A physics topic pointing at the maths chapter.
            session.add(
                Topic(
                    subject_id=physics.id,
                    code="1",
                    title="Forces",
                    chapter_id=maths_chapter.id,
                )
            )
            with pytest.raises(IntegrityError):
                await session.flush()
        finally:
            await session.rollback()
            connection = await session.connection()
            await connection.exec_driver_sql("PRAGMA foreign_keys=OFF")


async def test_migration_backfill_leaves_a_cross_subject_child_unchaptered():
    """A parent in another subject must not drag its chapter across.

    Nothing constrains `topics.parent_id` to the same subject. If the backfill
    copied such a parent's chapter, the composite foreign key would reject the
    row and abort the upgrade — and Render runs `alembic upgrade head` before
    uvicorn, so an aborted migration is an API that never starts. The row keeps
    `chapter_id = NULL`, which is legal and honest.
    """
    async with async_session() as session:
        org = await _org(session)
        maths = await _subject(session, org, "T500", "Maths")
        physics = await _subject(session, org, "T501", "Physics")

        maths_root = Topic(subject_id=maths.id, code="1", title="Number")
        session.add(maths_root)
        await session.flush()
        # A physics topic parented to a maths topic. Nothing forbids this.
        session.add(Topic(subject_id=physics.id, code="9", title="Stray", parent_id=maths_root.id))
        await session.commit()

        connection = await session.connection()
        await connection.run_sync(_load_migration().promote_root_topics_to_chapters)
        await session.commit()

        session.expire_all()
        by_code = {t.code: t for t in (await session.scalars(select(Topic))).all()}
        assert by_code["1"].chapter_id is not None
        assert by_code["9"].chapter_id is None


async def test_migration_backfill_promotes_root_topics_and_reparents_the_subtree():
    """Migration 0029's backfill, run against rows it actually has to move."""
    async with async_session() as session:
        org = await _org(session)
        subject = await _subject(session, org, "T300", "Pre-chapter")

        root = Topic(subject_id=subject.id, code="1", title="Number", weight=2.0)
        other_root = Topic(subject_id=subject.id, code="2", title="Algebra")
        session.add_all([root, other_root])
        await session.flush()
        child = Topic(subject_id=subject.id, code="1.1", title="Integers", parent_id=root.id)
        session.add(child)
        await session.flush()
        grandchild = Topic(subject_id=subject.id, code="1.1.1", title="Roots", parent_id=child.id)
        session.add(grandchild)
        await session.commit()

        connection = await session.connection()
        await connection.run_sync(_load_migration().promote_root_topics_to_chapters)
        await session.commit()

        chapters = (await session.scalars(select(Chapter).order_by(Chapter.position))).all()
        assert [(c.code, c.position, c.weight) for c in chapters] == [
            ("1", 1, 2.0),
            ("2", 2, 1.0),
        ]
        number_id, algebra_id = chapters[0].id, chapters[1].id

        # The backfill wrote through the raw connection, so the identity map is
        # still holding the pre-migration rows.
        session.expire_all()
        by_code = {t.code: t for t in (await session.scalars(select(Topic))).all()}
        assert by_code["1"].chapter_id == number_id
        assert by_code["1.1"].chapter_id == number_id
        # Depth 3: the loop ran more than once.
        assert by_code["1.1.1"].chapter_id == number_id
        assert by_code["2"].chapter_id == algebra_id
        # Nothing was deleted to tidy the tree.
        assert len(by_code) == 4
