"""Subject -> Chapter -> Topic, and the two paths that build it (task 2.1, AV-9).

The migration's backfill is tested here rather than left to CI's migrations job.
That job runs `upgrade head` against an **empty** Postgres, so the reparenting
loop never touches a row there — it would report green on a backfill that
silently did nothing. `RISK-3` is the named, already-realised failure of trusting
a migration nobody exercised.
"""

import importlib.util
import json
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import async_session
from app.models import Chapter, Subject, Topic
from seed.load_syllabus import load_file

MIGRATION = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0029_chapters.py"

SYLLABUS = {
    "exam_board": "Test Board",
    "code": "T100",
    "name": "Testing",
    "grade_scale": "9-1",
    "grade_boundaries": [{"grade": "9", "min": 90}, {"grade": "U", "min": 0}],
    "topics": [
        {
            "code": "1",
            "title": "Number",
            "weight": 2.0,
            "children": [
                {"code": "1.1", "title": "Integers"},
                # Third level: proves the reparenting reaches below the topics a
                # chapter directly owns, which is what `E1` keeps parent_id for.
                {
                    "code": "1.2",
                    "title": "Powers",
                    "children": [{"code": "1.2.1", "title": "Roots"}],
                },
            ],
        },
        {"code": "2", "title": "Algebra", "children": [{"code": "2.1", "title": "Expressions"}]},
    ],
}


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_0029", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def syllabus_file(tmp_path: Path) -> Path:
    path = tmp_path / "test_t100.json"
    path.write_text(json.dumps(SYLLABUS))
    return path


async def test_seed_promotes_top_level_nodes_to_chapters(syllabus_file: Path):
    async with async_session() as session:
        await load_file(session, syllabus_file)
        await session.commit()

        chapters = (await session.scalars(select(Chapter).order_by(Chapter.position))).all()
        assert [(c.code, c.title, c.position) for c in chapters] == [
            ("1", "Number", 1),
            ("2", "Algebra", 2),
        ]
        assert chapters[0].weight == 2.0

        by_code = {t.code: t for t in (await session.scalars(select(Topic))).all()}
        # Every topic in the subtree points at its chapter, at any depth.
        chapter_one = chapters[0].id
        assert by_code["1"].chapter_id == chapter_one
        assert by_code["1.1"].chapter_id == chapter_one
        assert by_code["1.2.1"].chapter_id == chapter_one
        assert by_code["2.1"].chapter_id == chapters[1].id
        # The root topic is kept, not moved: demo evidence hangs off it.
        assert by_code["1"].parent_id is None
        assert by_code["1.2.1"].parent_id == by_code["1.2"].id


async def test_seed_reload_does_not_duplicate_chapters(syllabus_file: Path):
    async with async_session() as session:
        await load_file(session, syllabus_file)
        await session.commit()
        await load_file(session, syllabus_file)
        await session.commit()

        chapters = (await session.scalars(select(Chapter))).all()
        assert len(chapters) == 2


async def test_a_topic_with_no_chapter_is_valid():
    """Nullable until extraction is chapter-first (task 2.3).

    Today's flat extractor has no chapter to point at, and inventing one would
    fabricate structure the tutor never approved (`PROD-2`).
    """
    async with async_session() as session:
        subject = Subject(
            exam_board="Test Board",
            code="T200",
            name="Unchaptered",
            grade_scale="9-1",
            grade_boundaries=[],
        )
        session.add(subject)
        await session.flush()
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
            maths = Subject(
                exam_board="Test Board",
                code="T400",
                name="Maths",
                grade_scale="9-1",
                grade_boundaries=[],
            )
            physics = Subject(
                exam_board="Test Board",
                code="T401",
                name="Physics",
                grade_scale="9-1",
                grade_boundaries=[],
            )
            session.add_all([maths, physics])
            await session.flush()

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
        maths = Subject(
            exam_board="Test Board",
            code="T500",
            name="Maths",
            grade_scale="9-1",
            grade_boundaries=[],
        )
        physics = Subject(
            exam_board="Test Board",
            code="T501",
            name="Physics",
            grade_scale="9-1",
            grade_boundaries=[],
        )
        session.add_all([maths, physics])
        await session.flush()

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
        subject = Subject(
            exam_board="Test Board",
            code="T300",
            name="Pre-chapter",
            grade_scale="9-1",
            grade_boundaries=[],
        )
        session.add(subject)
        await session.flush()

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
