"""Load/refresh syllabus subjects and topics from seed/syllabus/*.json.

Usage (from backend/): python -m seed.load_syllabus
Idempotent: existing subjects/topics are updated in place, new ones added.
"""

import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from app.db import async_session
from app.models import Chapter, Subject, Topic

SYLLABUS_DIR = Path(__file__).parent / "syllabus"


async def load_file(session, path: Path) -> str:
    data = json.loads(path.read_text())
    subject = await session.scalar(
        select(Subject).where(
            Subject.exam_board == data["exam_board"], Subject.code == data["code"]
        )
    )
    if subject is None:
        subject = Subject(exam_board=data["exam_board"], code=data["code"])
        session.add(subject)
    subject.name = data["name"]
    subject.grade_scale = data["grade_scale"]
    subject.grade_boundaries = data["grade_boundaries"]
    await session.flush()

    existing = {
        t.code: t
        for t in (await session.scalars(select(Topic).where(Topic.subject_id == subject.id))).all()
    }
    existing_chapters = {
        c.code: c
        for c in (
            await session.scalars(select(Chapter).where(Chapter.subject_id == subject.id))
        ).all()
    }

    async def upsert(node: dict, parent_id: int | None, chapter_id: int) -> None:
        topic = existing.get(node["code"])
        if topic is None:
            topic = Topic(subject_id=subject.id, code=node["code"])
            session.add(topic)
        topic.title = node["title"]
        topic.parent_id = parent_id
        topic.chapter_id = chapter_id
        topic.weight = node.get("weight", 1.0)
        await session.flush()
        for child in node.get("children", []):
            await upsert(child, topic.id, chapter_id)

    # A top-level node in the JSON is a chapter (AV-9). It stays a Topic as well,
    # exactly as migration 0029's backfill promotes rather than moves: demo.py
    # hangs evidence off the first eight topics by code, roots included, and
    # deleting those rows to tidy the tree would take the demo's evidence with
    # them. Task 2.2 deletes these seeds outright.
    for position, node in enumerate(data["topics"], start=1):
        chapter = existing_chapters.get(node["code"])
        if chapter is None:
            chapter = Chapter(subject_id=subject.id, code=node["code"])
            session.add(chapter)
        chapter.title = node["title"]
        chapter.position = position
        chapter.weight = node.get("weight", 1.0)
        await session.flush()
        await upsert(node, None, chapter.id)
    return f"{data['exam_board']} {data['code']} {data['name']}"


async def main() -> None:
    async with async_session() as session:
        for path in sorted(SYLLABUS_DIR.glob("*.json")):
            name = await load_file(session, path)
            print(f"loaded {name}")
        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
