"""Load/refresh syllabus subjects and topics from seed/syllabus/*.json.

Usage (from backend/): python -m seed.load_syllabus
Idempotent: existing subjects/topics are updated in place, new ones added.
"""

import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from app.db import async_session
from app.models import Subject, Topic

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

    async def upsert(node: dict, parent_id: int | None) -> None:
        topic = existing.get(node["code"])
        if topic is None:
            topic = Topic(subject_id=subject.id, code=node["code"])
            session.add(topic)
        topic.title = node["title"]
        topic.parent_id = parent_id
        topic.weight = node.get("weight", 1.0)
        await session.flush()
        for child in node.get("children", []):
            await upsert(child, topic.id)

    for node in data["topics"]:
        await upsert(node, None)
    return f"{data['exam_board']} {data['code']} {data['name']}"


async def main() -> None:
    async with async_session() as session:
        for path in sorted(SYLLABUS_DIR.glob("*.json")):
            name = await load_file(session, path)
            print(f"loaded {name}")
        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
