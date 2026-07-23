"""Create demo accounts and a demo group for manual testing.

Usage (from backend/): python -m seed.load_syllabus && python -m seed.demo

Accounts created (password for all: demo1234):
  tutor:   demo-tutor@example.com
  student: demo-student@example.com  (email account)
  student: demo_ali                  (username-only account)
  parent:  demo-parent@example.com   (linked to demo-student)
"""

import asyncio
import random
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select

from app.db import async_session
from app.models import (
    Assessment,
    AssessmentScore,
    AssessmentType,
    Assignment,
    AssignmentQuestion,
    AssignmentStatus,
    Classified,
    Evidence,
    EvidenceSource,
    Group,
    GroupMember,
    GroupResource,
    KnowledgeEntry,
    KnowledgeEntryKind,
    Lesson,
    LessonObservation,
    LessonTopic,
    MarkConfidence,
    Organization,
    ParentLink,
    QuestionMark,
    QuestionTopic,
    ResourceKind,
    ScheduleSlot,
    Subject,
    Submission,
    SubmissionFile,
    SubmissionStatus,
    Topic,
    TutorPreferences,
    User,
    UserRole,
)
from app.security import hash_password
from app.services import storage
from app.services.readiness import recompute_student

PASSWORD = "demo1234"

# A minimal one-page PDF, valid enough to store and reference as a demo file.
FAKE_PDF_BYTES = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"trailer<</Root 1 0 R>>"
)


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
        org = Organization(name="Demo Tutor's Organization")
        session.add(org)
        await session.flush()

        tutor = User(
            email="demo-tutor@example.com", password_hash=pw, role=UserRole.tutor,
            name="Demo Tutor", organization_id=org.id,
        )
        student1 = User(
            email="demo-student@example.com", password_hash=pw, role=UserRole.student,
            name="Sara Student", organization_id=org.id,
        )
        parent = User(
            email="demo-parent@example.com", password_hash=pw, role=UserRole.parent,
            name="Demo Parent", organization_id=org.id,
        )
        session.add_all([tutor, student1, parent])
        await session.flush()

        student2 = User(
            username="demo_ali", password_hash=pw, role=UserRole.student,
            name="Ali Student", created_by_id=tutor.id, organization_id=org.id,
        )
        session.add(student2)
        await session.flush()

        group = Group(
            organization_id=org.id, tutor_id=tutor.id, subject_id=subject.id, name="Chemistry — Year 10"
        )
        session.add(group)
        await session.flush()
        today_weekday = datetime.now(timezone.utc).weekday()
        fixed_slots = [
            ScheduleSlot(group_id=group.id, weekday=1, start_time=time(17, 0), duration_min=90, title="Weekly lesson"),
            ScheduleSlot(group_id=group.id, weekday=4, start_time=time(17, 0), duration_min=90, title="Problem solving"),
        ]
        # A slot today so the tutor's "Today" tab has something to show
        # regardless of what day the demo is loaded — unless today already
        # coincides with one of the fixed slots above.
        if today_weekday not in (1, 4):
            fixed_slots.append(
                ScheduleSlot(group_id=group.id, weekday=today_weekday, start_time=time(17, 0), duration_min=90, title="Today's lesson")
            )
        session.add_all([
            GroupMember(group_id=group.id, student_id=student1.id),
            GroupMember(group_id=group.id, student_id=student2.id),
            ParentLink(parent_id=parent.id, student_id=student1.id),
            *fixed_slots,
        ])
        await session.flush()

        topics = (
            await session.scalars(
                select(Topic).where(Topic.subject_id == subject.id).order_by(Topic.code).limit(8)
            )
        ).all()
        if not topics:
            raise SystemExit("Subject 4CH1 has no topics — check seed/syllabus data")

        students = [student1, student2]
        now = datetime.now(timezone.utc)
        rng = random.Random(42)

        # ~30 evidence rows per student across the first few topics, trending
        # upward over the last 90 days, so dashboards show real progress.
        for student in students:
            for topic in topics[: min(6, len(topics))]:
                base = rng.uniform(45, 65)
                for i in range(5):
                    days_ago = 90 - i * 18
                    trend = base + (90 - days_ago) / 90 * rng.uniform(15, 30)
                    score = max(20, min(98, trend + rng.uniform(-8, 8)))
                    source = rng.choice(list(EvidenceSource))
                    session.add(
                        Evidence(
                            student_id=student.id,
                            topic_id=topic.id,
                            source_type=source,
                            score_pct=round(score, 1),
                            max_marks=20,
                            occurred_at=now - timedelta(days=days_ago),
                            label=f"Demo evidence ({source.value})",
                        )
                    )
        await session.flush()

        # A taught lesson covering the first topic, with a per-student
        # observation — exercises the new Lessons core entity end to end.
        lesson = Lesson(
            organization_id=org.id,
            group_id=group.id,
            date=date.today() - timedelta(days=7),
            duration_min=90,
            notes="Covered atomic structure basics; assigned HW1 for practice.",
        )
        session.add(lesson)
        await session.flush()
        session.add(LessonTopic(lesson_id=lesson.id, topic_id=topics[0].id))
        session.add(
            LessonObservation(
                lesson_id=lesson.id, student_id=student1.id, topic_id=topics[0].id,
                body="Sara answered confidently in class — ready for harder questions.",
                rating=80,
            )
        )

        # One published assignment with a finalized submission per student.
        classified = Classified(
            organization_id=org.id,
            tutor_id=tutor.id,
            subject_id=subject.id,
            title="Demo classified — Atomic structure",
            file_path="demo-classified.pdf",
            file_name="atomic-structure.pdf",
            file_mime="application/pdf",
        )
        session.add(classified)
        await session.flush()
        storage.absolute_path(classified.file_path).write_bytes(FAKE_PDF_BYTES)

        assignment = Assignment(
            group_id=group.id,
            lesson_id=lesson.id,
            classified_id=classified.id,
            title="HW1 — Atomic structure",
            status=AssignmentStatus.published,
        )
        session.add(assignment)
        await session.flush()

        question_defs = [
            ("1", "Define an isotope and give one example", 4, topics[0]),
            ("2", "Explain how ions form from atoms", 6, topics[min(1, len(topics) - 1)]),
        ]
        questions = []
        for number, summary, max_marks, topic in question_defs:
            q = AssignmentQuestion(
                assignment_id=assignment.id,
                position=len(questions),
                number=number,
                text_summary=summary,
                max_marks=max_marks,
                has_mark_scheme=True,
            )
            session.add(q)
            await session.flush()
            session.add(QuestionTopic(question_id=q.id, topic_id=topic.id))
            questions.append(q)

        for student in students:
            submission = Submission(
                assignment_id=assignment.id,
                student_id=student.id,
                status=SubmissionStatus.finalized,
                finalized_at=now,
                finalized_by_id=tutor.id,
            )
            session.add(submission)
            await session.flush()
            session.add(
                SubmissionFile(
                    submission_id=submission.id, position=0,
                    path=classified.file_path, name="answer.pdf", mime="application/pdf",
                )
            )
            for q in questions:
                marks = round(q.max_marks * rng.uniform(0.6, 0.95))
                session.add(
                    QuestionMark(
                        submission_id=submission.id,
                        question_id=q.id,
                        ai_marks=marks,
                        ai_feedback="Good understanding, minor detail missing.",
                        ai_confidence=MarkConfidence.high,
                        final_marks=marks,
                        final_feedback="Nice work — see the marked-up notes.",
                    )
                )
        await session.flush()

        # One mock assessment with per-topic scores.
        assessment = Assessment(
            tutor_id=tutor.id, subject_id=subject.id,
            title="Term 1 Mock Exam", type=AssessmentType.mock,
            date=date.today() - timedelta(days=14),
        )
        session.add(assessment)
        await session.flush()
        for student in students:
            for topic in topics[: min(3, len(topics))]:
                marks = round(20 * rng.uniform(0.5, 0.9))
                session.add(
                    AssessmentScore(
                        assessment_id=assessment.id, student_id=student.id,
                        topic_id=topic.id, marks=marks, max_marks=20,
                    )
                )
        await session.flush()

        # Group resources: one file, one recording link.
        session.add_all([
            GroupResource(
                group_id=group.id, tutor_id=tutor.id, kind=ResourceKind.recording,
                title="Lesson 3 recording — Atomic structure",
                url="https://example.com/recordings/lesson-3",
            ),
            GroupResource(
                group_id=group.id, tutor_id=tutor.id, kind=ResourceKind.file,
                title="Revision notes — Atomic structure",
                file_path=classified.file_path, file_name="revision-notes.pdf",
                file_mime="application/pdf",
            ),
        ])

        # Tutor preferences (defaults, just so the row exists to edit).
        session.add(TutorPreferences(tutor_id=tutor.id))

        # Knowledge base entries — injected into every AI surface so the AI
        # behaves like this specific tutor.
        session.add_all([
            KnowledgeEntry(
                organization_id=org.id, tutor_id=tutor.id, subject_id=None,
                kind=KnowledgeEntryKind.ai_instruction,
                title="Tone with students",
                body="Always be warm and encouraging, never sarcastic. Celebrate small wins.",
            ),
            KnowledgeEntry(
                organization_id=org.id, tutor_id=tutor.id, subject_id=subject.id,
                kind=KnowledgeEntryKind.marking_preference,
                title="Chemistry equations",
                body="Always require balanced equations with state symbols for full marks.",
            ),
        ])

        await session.commit()

        for student in students:
            await recompute_student(session, {"student_id": student.id})
        await session.commit()

        print("demo data created — sign in as demo-tutor@example.com / demo1234")


if __name__ == "__main__":
    asyncio.run(main())
