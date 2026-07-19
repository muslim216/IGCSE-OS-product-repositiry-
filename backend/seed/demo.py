"""Create demo accounts and a demo group for manual testing.

Usage (from backend/): python -m seed.load_syllabus && python -m seed.demo

Accounts created (password for all: demo1234):
  tutor:   demo-tutor@example.com
  student: demo-student@example.com  (email account)
  student: demo_ali                  (username-only account)
  parent:  demo-parent@example.com   (linked to demo-student)
"""

import asyncio
from datetime import time

from sqlalchemy import select

from app.db import async_session
from app.models import (
    Group,
    GroupMember,
    Lesson,
    ParentLink,
    Subject,
    User,
    UserRole,
)
from app.security import hash_password

PASSWORD = "demo1234"


async def main() -> None:
    async with async_session() as session:
        existing = await session.scalar(
            select(User).where(User.email == "demo-tutor@example.com")
        )
        if existing is not None:
            print("demo data already present — nothing to do")
            return

        subject = await session.scalar(
            select(Subject).where(Subject.code == "4CH1")
        )
        if subject is None:
            raise SystemExit("Run `python -m seed.load_syllabus` first")

        pw = hash_password(PASSWORD)
        tutor = User(email="demo-tutor@example.com", password_hash=pw, role=UserRole.tutor, name="Demo Tutor")
        student1 = User(email="demo-student@example.com", password_hash=pw, role=UserRole.student, name="Sara Student")
        parent = User(email="demo-parent@example.com", password_hash=pw, role=UserRole.parent, name="Demo Parent")
        session.add_all([tutor, student1, parent])
        await session.flush()

        student2 = User(
            username="demo_ali", password_hash=pw, role=UserRole.student,
            name="Ali Student", created_by_id=tutor.id,
        )
        session.add(student2)
        await session.flush()

        group = Group(tutor_id=tutor.id, subject_id=subject.id, name="Chemistry — Year 10")
        session.add(group)
        await session.flush()
        session.add_all([
            GroupMember(group_id=group.id, student_id=student1.id),
            GroupMember(group_id=group.id, student_id=student2.id),
            ParentLink(parent_id=parent.id, student_id=student1.id),
            Lesson(group_id=group.id, weekday=1, start_time=time(17, 0), duration_min=90, title="Weekly lesson"),
            Lesson(group_id=group.id, weekday=4, start_time=time(17, 0), duration_min=90, title="Problem solving"),
        ])
        await session.commit()
        print("demo data created — sign in as demo-tutor@example.com / demo1234")


if __name__ == "__main__":
    asyncio.run(main())
