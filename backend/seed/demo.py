"""Create demo accounts and a demo group for manual testing.

Usage (from backend/): python -m seed.demo

Accounts created (password for all: demo1234):
  tutor:   demo-tutor@example.com
  student: demo-student@example.com  (email account)
  student: demo_ali                  (username-only account)
  parent:  demo-parent@example.com   (linked to demo-student)

Who they are: Layla Haddad (tutor, "Haddad Tutoring") teaches Year 10
Chemistry to six students — Sara Al-Mansouri (demo-student), Ali Rahman
(demo_ali), and username-only classmates demo_omar, demo_mariam, demo_noor and
demo_yusuf (same password) — and Huda Al-Mansouri is Sara's parent.

The people, class and work are fictional but realistic on purpose: this is
what a prospective tutor is shown, and named people in a class of six read
as a working practice where "Demo Tutor" marking "Sara Student" read as a toy.
"""

import asyncio
import random
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from sqlalchemy import distinct, func, select

from app.db import async_session
from app.models import (
    AiSynthesisStatus,
    Assessment,
    AssessmentScore,
    AssessmentType,
    Assignment,
    AssignmentQuestion,
    AssignmentStatus,
    Booklet,
    BookletStatus,
    Chapter,
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
    PastPaper,
    PastPaperAttempt,
    QuestionMark,
    QuestionTopic,
    ReadinessSnapshot,
    ReadinessWeights,
    ResourceKind,
    ScheduleSlot,
    Subject,
    SubjectLevel,
    Submission,
    SubmissionFile,
    SubmissionStatus,
    Topic,
    User,
    UserRole,
    WorkKind,
)
from app.security import hash_password
from app.services import storage
from app.services.grade_boundaries import (
    defaults_for_scale,
    resolve_grade_boundaries,
    set_org_boundaries,
)
from app.services.grades import predict_grade
from app.services.readiness_config import resolve_readiness_config
from app.services.readiness_v2 import evaluate_subject_factors
from app.services.readiness_v2_ai import _weighted_reference_score
from app.services.work import create_work

PASSWORD = "demo1234"

#: A photographed page of handwritten answers to HW2, so the review screen shows
#: the student's work beside the marks the way a real upload does. Rendered from
#: the OFL-licensed Caveat typeface. It is Ali's page and only Ali's: his marks
#: are set to match it, including question 2's missing "oppositely charged
#: ions" that the AI flags. Every other submission carries a placeholder file,
#: so no student is shown someone else's work as their own.
HANDWRITTEN_PAGE = Path(__file__).parent / "assets" / "ionic-bonding-answer.jpg"

# A minimal one-page PDF, valid enough to store and reference as a demo file.
FAKE_PDF_BYTES = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"trailer<</Root 1 0 R>>"
)


#: The demo tutor's own syllabus. Small on purpose — enough chapters and topics
#: for the evidence, lesson and assessment fixtures below, and no more. It is
#: data, not a built-in: `AV-8` deleted the five shared syllabuses, so nothing
#: ships a subject except the account that creates one.
CHEMISTRY = {
    "exam_board": "Edexcel IGCSE",
    "code": "4CH1",
    "name": "Chemistry",
    "level": SubjectLevel.igcse,
    "grade_scale": "9-1",
    "chapters": [
        {
            "code": "1",
            "title": "Principles of chemistry",
            "weight": 1.4,
            "topics": [
                {"code": "1.1", "title": "States of matter"},
                {"code": "1.2", "title": "Atoms, elements and compounds"},
                {"code": "1.3", "title": "Ionic bonding"},
            ],
        },
        {
            "code": "2",
            "title": "Inorganic chemistry",
            "topics": [
                {"code": "2.1", "title": "Group 1 and Group 7"},
                {"code": "2.2", "title": "Acids, bases and salts"},
                {"code": "2.3", "title": "Reactivity series"},
            ],
        },
        {
            "code": "3",
            "title": "Physical chemistry",
            "topics": [
                {"code": "3.1", "title": "Energetics"},
                {"code": "3.2", "title": "Rates of reaction"},
                {"code": "3.3", "title": "Electrolysis"},
            ],
        },
    ],
}


async def build_subject(session, *, organization_id: int, data: dict) -> Subject:
    """Create a Subject with its chapters, topics and grade boundaries, owned by
    one organization.

    Chapter-first, matching the tree `AV-9` settled: a chapter contains topics,
    and marks and readiness attach to the topics. Topics here are leaves — the
    old seed loader made each chapter a topic *as well*, which migration 0029
    preserved only so existing demo evidence survived that phase. Nothing needs
    to carry that forward into subjects built from scratch.

    Shared with `tests/test_chapters.py` rather than duplicated there, so the
    tree the tests assert on is the tree the demo actually builds.
    """
    subject = Subject(
        organization_id=organization_id,
        exam_board=data["exam_board"],
        code=data["code"],
        name=data["name"],
        level=data["level"],
        grade_scale=data["grade_scale"],
    )
    session.add(subject)
    await session.flush()

    # Grade boundaries are org-scoped rows, not a column on the subject, and
    # nothing writes them on a tutor's behalf (task 2.4, AV-11). The demo tutor
    # is standing in for one who set them, so the seed does what that tutor's
    # save would do — otherwise every predicted grade in the demo reads "—",
    # which is correct behaviour and a useless demo.
    await set_org_boundaries(
        session, organization_id, subject.id, defaults_for_scale(data["grade_scale"])
    )

    for position, node in enumerate(data["chapters"], start=1):
        chapter = Chapter(
            subject_id=subject.id,
            code=node["code"],
            title=node["title"],
            position=position,
            weight=node.get("weight", 1.0),
        )
        session.add(chapter)
        await session.flush()
        for topic in node["topics"]:
            session.add(
                Topic(
                    subject_id=subject.id,
                    chapter_id=chapter.id,
                    code=topic["code"],
                    title=topic["title"],
                    weight=topic.get("weight", 1.0),
                )
            )
    await session.flush()
    return subject


async def write_demo_snapshot(session, student: User, subject_id: int, now: datetime) -> None:
    """A v2 snapshot for demo data without calling a model (QA-8 in spirit).

    Layer 1 runs for real; the score is Layer 1's own weighted reference — the
    value compute_readiness_v2 clamps any AI answer to within ±10 of — so the
    demo shows the engine's deterministic answer. The rationale is rendered to
    tutors under the AI-summary label, so it says only what the evidence rows
    show — never seed internals, and nothing a model would have had to infer."""
    subject = await session.get(Subject, subject_id)
    run_id = str(uuid.uuid4())
    rows = await evaluate_subject_factors(session, student.id, subject_id, run_id, now)
    config = await resolve_readiness_config(session, student.organization_id, subject_id)
    # Switched-off factors are left out exactly as synthesis leaves them out.
    counted = [row for row in rows if row.factor in config.enabled]
    reference = _weighted_reference_score(counted, config.weights)
    score = round(reference, 1) if reference is not None else None
    boundaries = await resolve_grade_boundaries(session, student.organization_id, subject)
    # The rationale states facts read from the student's own evidence. The seed
    # never calls a model (QA-8 in spirit), so it must not write anything the
    # data cannot back.
    topic_count = await session.scalar(
        select(func.count(distinct(Evidence.topic_id))).where(Evidence.student_id == student.id)
    )
    session.add(
        ReadinessSnapshot(
            evaluation_run_id=run_id,
            student_id=student.id,
            subject_id=subject_id,
            status=AiSynthesisStatus.ready,
            score=score,
            predicted_grade=predict_grade(score, boundaries)
            if score is not None and boundaries
            else None,
            weak_topics=[],
            rationale=(
                f"Readiness is {score:.0f}% across {topic_count} topics with marked work, "
                "weighting each factor as this tutor has set it. The predicted grade reads "
                "that score through the tutor's own grade boundaries."
                if score is not None
                else "No evidence yet for this subject."
            ),
            recommended_revision=None,
        )
    )


async def main() -> None:
    async with async_session() as session:
        existing = await session.scalar(select(User).where(User.email == "demo-tutor@example.com"))
        if existing is not None:
            print("demo data already present — nothing to do")
            return

        pw = hash_password(PASSWORD)
        org = Organization(name="Haddad Tutoring")
        session.add(org)
        await session.flush()

        # The demo builds its own subject (AV-8, task 2.2). There are no built-in
        # syllabuses any more: subjects belong to the tutor who created them, so a
        # seed that installed five global ones would be seeding a shape the
        # product no longer has.
        subject = await build_subject(session, organization_id=org.id, data=CHEMISTRY)

        tutor = User(
            email="demo-tutor@example.com",
            password_hash=pw,
            role=UserRole.tutor,
            name="Layla Haddad",
            organization_id=org.id,
        )
        student1 = User(
            email="demo-student@example.com",
            password_hash=pw,
            role=UserRole.student,
            name="Sara Al-Mansouri",
            organization_id=org.id,
        )
        parent = User(
            email="demo-parent@example.com",
            password_hash=pw,
            role=UserRole.parent,
            name="Huda Al-Mansouri",
            organization_id=org.id,
        )
        session.add_all([tutor, student1, parent])
        await session.flush()

        student2 = User(
            username="demo_ali",
            password_hash=pw,
            role=UserRole.student,
            name="Ali Rahman",
            created_by_id=tutor.id,
            organization_id=org.id,
        )
        session.add(student2)
        # The rest of the class: username-only accounts, as a tutor creates them
        # for students without an email address.
        classmates = [
            User(
                username=username,
                password_hash=pw,
                role=UserRole.student,
                name=name,
                created_by_id=tutor.id,
                organization_id=org.id,
            )
            for username, name in [
                ("demo_omar", "Omar Khalid"),
                ("demo_mariam", "Mariam Youssef"),
                ("demo_noor", "Noor Siddiqui"),
                ("demo_yusuf", "Yusuf Benali"),
            ]
        ]
        session.add_all(classmates)
        await session.flush()

        group = Group(
            organization_id=org.id,
            tutor_id=tutor.id,
            subject_id=subject.id,
            name="Year 10 Chemistry",
        )
        session.add(group)
        await session.flush()
        today_weekday = datetime.now(timezone.utc).weekday()
        fixed_slots = [
            ScheduleSlot(
                group_id=group.id,
                weekday=1,
                start_time=time(17, 0),
                duration_min=90,
                title="Weekly lesson",
            ),
            ScheduleSlot(
                group_id=group.id,
                weekday=4,
                start_time=time(17, 0),
                duration_min=90,
                title="Problem solving",
            ),
        ]
        # A slot today so the tutor's "Today" tab has something to show
        # regardless of what day the demo is loaded — unless today already
        # coincides with one of the fixed slots above.
        if today_weekday not in (1, 4):
            fixed_slots.append(
                ScheduleSlot(
                    group_id=group.id,
                    weekday=today_weekday,
                    start_time=time(17, 0),
                    duration_min=90,
                    title="Today's lesson",
                )
            )
        session.add_all(
            [
                GroupMember(group_id=group.id, student_id=student1.id),
                GroupMember(group_id=group.id, student_id=student2.id),
                *[GroupMember(group_id=group.id, student_id=c.id) for c in classmates],
                ParentLink(parent_id=parent.id, student_id=student1.id),
                *fixed_slots,
            ]
        )
        await session.flush()

        topics = (
            await session.scalars(
                select(Topic).where(Topic.subject_id == subject.id).order_by(Topic.code).limit(8)
            )
        ).all()
        if not topics:
            raise SystemExit("Demo subject has no topics — check CHEMISTRY above")

        students = [student1, student2, *classmates]
        now = datetime.now(timezone.utc)
        rng = random.Random(42)

        # ~30 evidence rows per student across the first few topics, trending
        # upward over the last 90 days, so dashboards show real progress.
        # A real class has a spread: two students comfortably on track, one
        # struggling, the rest in between. A class where everyone carries the
        # same status reads as a fixture, not a group of people.
        level = {
            student1.id: 18,
            classmates[2].id: 14,
            classmates[0].id: -16,
        }
        for student in students:
            for topic in topics[: min(6, len(topics))]:
                base = rng.uniform(45, 65) + level.get(student.id, 0)
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
                            label=f"{source.value.replace('_', ' ').capitalize()} — {topic.title}",
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
        # Ninety days into term a tutor has taught most of the course. Syllabus
        # coverage is derived from lesson_topics (PROD-14), so a demo with one
        # recorded lesson scored every student at a few percent coverage and
        # dragged the whole class's readiness down with it.
        for weeks_ago, topic in zip(range(11, 1, -2), topics[1:6], strict=False):
            taught = Lesson(
                organization_id=org.id,
                group_id=group.id,
                date=date.today() - timedelta(weeks=weeks_ago),
                duration_min=90,
                notes=f"Taught {topic.title.lower()}; worked examples and an exit quiz.",
            )
            session.add(taught)
            await session.flush()
            session.add(LessonTopic(lesson_id=taught.id, topic_id=topic.id))
        session.add(
            LessonObservation(
                lesson_id=lesson.id,
                student_id=student1.id,
                topic_id=topics[0].id,
                body="Answered confidently in class — ready for harder questions.",
                rating=80,
            )
        )

        # One published assignment with a finalized submission per student.
        # The key is generated the same way a real upload generates one
        # (SEC-16) rather than a hardcoded literal, so demo seeding exercises
        # the real storage path under either backend instead of only working
        # against local disk.
        classified_key = storage.new_key(org.id, "application/pdf")
        classified = Classified(
            organization_id=org.id,
            tutor_id=tutor.id,
            subject_id=subject.id,
            title="Atomic structure — practice questions",
            file_path=classified_key,
            file_name="atomic-structure.pdf",
            file_mime="application/pdf",
        )
        session.add(classified)
        await session.flush()
        await storage.get_storage().upload(classified_key, FAKE_PDF_BYTES, "application/pdf")

        hw_work = await create_work(
            session,
            kind=WorkKind.homework,
            organization_id=group.organization_id,
            subject_id=group.subject_id,
            title="HW1 — Atomic structure",
        )
        assignment = Assignment(
            work_id=hw_work.id,
            group_id=group.id,
            lesson_id=lesson.id,
            classified_id=classified.id,
            title="HW1 — Atomic structure",
            status=AssignmentStatus.published,
        )
        session.add(assignment)
        await session.flush()

        question_defs = [
            ("1", "Define an isotope and give one example", 4, topics[0], "isotope"),
            ("2", "Explain how ions form from atoms", 6, topics[min(1, len(topics) - 1)], "ions"),
        ]
        questions = []
        feedback_keys: dict[int, str] = {}
        for number, summary, max_marks, topic, feedback_key in question_defs:
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
            feedback_keys[q.id] = feedback_key

        # Feedback a tutor would actually write, varied by how well the answer
        # did — the same sentence on every question read as placeholder text.
        # Keyed by question as well as band: a comment about protons and
        # neutrons under a melting-point question reads as nonsense.
        feedback_by_question: dict[str, dict[str, str]] = {
            "isotope": {
                "high": "Clear definition with a correct example — exactly what the scheme wants.",
                "mid": "Right idea. Name a specific isotope pair to secure the last mark.",
                "low": "Revisit the definition: isotopes differ in neutrons, not protons.",
            },
            "ions": {
                "high": "Well explained, with electron loss and gain both described.",
                "mid": "Good start — say which atom loses electrons and which gains them.",
                "low": "Show the electron transfer explicitly, then the charges it leaves.",
            },
            "nacl": {
                "high": "Correct outer shells and charges on both ions.",
                "mid": "Diagram is right; add the charges on each bracket.",
                "low": "Sodium should end with an empty outer shell — redraw its ion.",
            },
            "mgo": {
                "high": "Lattice, strong attraction between oppositely charged ions, and energy — complete.",
                "mid": "Say what the strong forces are between: oppositely charged ions.",
                "low": "Link the high melting point to breaking the lattice's ionic bonds.",
            },
            "cacl2": {
                "high": "Correct formula, with the electron transfer shown.",
                "mid": "Formula is right; show why two chloride ions are needed.",
                "low": "Calcium forms Ca²⁺, so it needs two Cl⁻ — check the formula.",
            },
        }

        def scaled(max_marks: int, low: float, high: float, student: User) -> int:
            """A mark out of max_marks, shifted by the student's level."""
            ratio = rng.uniform(low, high) + level.get(student.id, 0) / 100
            return max(0, min(max_marks, round(max_marks * ratio)))

        def feedback_for(question: str, marks: int, max_marks: int) -> str:
            ratio = marks / max_marks
            band = "high" if ratio >= 0.85 else "mid" if ratio >= 0.6 else "low"
            return feedback_by_question[question][band]

        for student in students:
            submission = Submission(
                work_id=assignment.work_id,
                student_id=student.id,
                status=SubmissionStatus.finalized,
                finalized_at=now,
                finalized_by_id=tutor.id,
            )
            session.add(submission)
            await session.flush()
            session.add(
                SubmissionFile(
                    submission_id=submission.id,
                    position=0,
                    path=classified.file_path,
                    name="answer.pdf",
                    mime="application/pdf",
                )
            )
            for q in questions:
                marks = scaled(q.max_marks, 0.55, 0.9, student)
                feedback = feedback_for(feedback_keys[q.id], marks, q.max_marks)
                session.add(
                    QuestionMark(
                        submission_id=submission.id,
                        question_id=q.id,
                        ai_marks=marks,
                        ai_feedback=feedback,
                        ai_confidence=MarkConfidence.high,
                        final_marks=marks,
                        final_feedback=feedback,
                    )
                )
        await session.flush()

        # A second homework, still in flight: most of the class handed in, one
        # answer the AI was unsure about waits in the tutor's review queue, and
        # one student has not handed in yet. This is the loop the product
        # exists for, so the demo should show it running, not finished.
        # HW2 has its own question paper: pointing it at HW1's atomic-structure
        # paper would make marking read the wrong questions. It carries a mark
        # scheme too, because marking.py only lets a confident mark count on its
        # own when a scheme was attached — without one, the auto-finalized
        # marks below would be ones the real pipeline could never produce.
        bonding_key = storage.new_key(org.id, "application/pdf")
        bonding_scheme_key = storage.new_key(org.id, "application/pdf")
        bonding_paper = Classified(
            organization_id=org.id,
            tutor_id=tutor.id,
            subject_id=subject.id,
            title="Ionic bonding — practice questions",
            file_path=bonding_key,
            file_name="ionic-bonding.pdf",
            file_mime="application/pdf",
            mark_scheme_path=bonding_scheme_key,
            mark_scheme_name="ionic-bonding-mark-scheme.pdf",
            mark_scheme_mime="application/pdf",
        )
        session.add(bonding_paper)
        await session.flush()
        await storage.get_storage().upload(bonding_key, FAKE_PDF_BYTES, "application/pdf")
        await storage.get_storage().upload(bonding_scheme_key, FAKE_PDF_BYTES, "application/pdf")

        hw2_work = await create_work(
            session,
            kind=WorkKind.homework,
            organization_id=group.organization_id,
            subject_id=group.subject_id,
            title="HW2 — Ionic bonding",
        )
        assignment2 = Assignment(
            work_id=hw2_work.id,
            group_id=group.id,
            lesson_id=lesson.id,
            classified_id=bonding_paper.id,
            title="HW2 — Ionic bonding",
            status=AssignmentStatus.published,
            due_at=now + timedelta(days=3),
        )
        session.add(assignment2)
        await session.flush()
        bonding = topics[min(2, len(topics) - 1)]
        hw2_questions = []
        for number, summary, max_marks, feedback_key in [
            ("1", "Draw a dot-and-cross diagram for sodium chloride", 3, "nacl"),
            ("2", "Explain why magnesium oxide has a high melting point", 4, "mgo"),
            ("3", "Predict the formula of the compound formed by calcium and chlorine", 2, "cacl2"),
        ]:
            q = AssignmentQuestion(
                assignment_id=assignment2.id,
                position=len(hw2_questions),
                number=number,
                text_summary=summary,
                max_marks=max_marks,
                has_mark_scheme=True,
            )
            session.add(q)
            await session.flush()
            session.add(QuestionTopic(question_id=q.id, topic_id=bonding.id))
            hw2_questions.append(q)
            feedback_keys[q.id] = feedback_key

        page_key = storage.new_key(org.id, "image/jpeg")
        await storage.get_storage().upload(page_key, HANDWRITTEN_PAGE.read_bytes(), "image/jpeg")
        placeholder_key = storage.new_key(org.id, "application/pdf")
        await storage.get_storage().upload(placeholder_key, FAKE_PDF_BYTES, "application/pdf")
        # Ali's marks are the ones his handwritten page earns (see
        # HANDWRITTEN_PAGE): full marks on 1 and 3, and a 3/4 on 2 that the AI
        # proposes but is unsure of.
        page_marks = [3, 3, 2]

        # Everyone but the last student handed in. Only Ali's submission carries
        # an answer the AI was not sure about: its feedback describes what is on
        # his handwritten page, and beside anyone else's placeholder file it
        # would describe work the tutor cannot see.
        unsure = {student2.id}
        for student in students[:-1]:
            waiting = student.id in unsure
            has_page = student.id == student2.id
            submission = Submission(
                work_id=assignment2.work_id,
                student_id=student.id,
                status=SubmissionStatus.needs_review
                if waiting
                else SubmissionStatus.auto_finalized,
                finalized_at=None if waiting else now,
            )
            session.add(submission)
            await session.flush()
            session.add(
                SubmissionFile(
                    submission_id=submission.id,
                    position=0,
                    path=page_key if has_page else placeholder_key,
                    name="ionic-bonding-page-1.jpg" if has_page else "answer.pdf",
                    mime="image/jpeg" if has_page else "application/pdf",
                )
            )
            for i, q in enumerate(hw2_questions):
                marks = page_marks[i] if has_page else scaled(q.max_marks, 0.5, 0.9, student)
                if waiting and i == 1:
                    session.add(
                        QuestionMark(
                            submission_id=submission.id,
                            question_id=q.id,
                            ai_marks=marks,
                            ai_feedback=(
                                "The answer mentions strong forces but does not say they act "
                                "between oppositely charged ions — unclear whether the scheme's "
                                "second point is met."
                            ),
                            ai_confidence=MarkConfidence.low,
                            needs_review=True,
                        )
                    )
                else:
                    # Confident and scheme-backed, so it counts now even when
                    # another question on the same submission waits — exactly
                    # what marking.py does per question. Leaving these blank
                    # would hand the tutor three questions to mark instead of one.
                    feedback = feedback_for(feedback_keys[q.id], marks, q.max_marks)
                    session.add(
                        QuestionMark(
                            submission_id=submission.id,
                            question_id=q.id,
                            ai_marks=marks,
                            ai_feedback=feedback,
                            ai_confidence=MarkConfidence.high,
                            auto_finalized=True,
                            final_marks=marks,
                            final_feedback=feedback,
                        )
                    )
        await session.flush()

        # One mock assessment with per-topic scores.
        assessment = Assessment(
            tutor_id=tutor.id,
            subject_id=subject.id,
            title="Term 1 Mock Exam",
            type=AssessmentType.mock,
            date=date.today() - timedelta(days=14),
        )
        session.add(assessment)
        await session.flush()
        for student in students:
            for topic in topics[: min(3, len(topics))]:
                marks = scaled(20, 0.5, 0.85, student)
                session.add(
                    AssessmentScore(
                        assessment_id=assessment.id,
                        student_id=student.id,
                        topic_id=topic.id,
                        marks=marks,
                        max_marks=20,
                    )
                )
        await session.flush()

        # Group resources: one file, one recording link.
        session.add_all(
            [
                GroupResource(
                    group_id=group.id,
                    tutor_id=tutor.id,
                    kind=ResourceKind.recording,
                    title="Lesson 3 recording — Atomic structure",
                    url="https://example.com/recordings/lesson-3",
                ),
                GroupResource(
                    group_id=group.id,
                    tutor_id=tutor.id,
                    kind=ResourceKind.file,
                    title="Revision notes — Atomic structure",
                    file_path=classified.file_path,
                    file_name="revision-notes.pdf",
                    file_mime="application/pdf",
                ),
            ]
        )

        # Readiness v2 factor weights (defaults), so the row exists to edit.
        session.add(ReadinessWeights(organization_id=org.id, tutor_id=tutor.id))

        # A past paper attempt — distinct from classifieds (see CLAUDE.md):
        # full past papers carry official grade boundaries and timed
        # conditions, and become the dominant evidence source later in the
        # IGCSE year.
        # Its booklet of one. Every past paper has a parent (task 3.5), and a
        # single paper is a booklet holding just it — `applied` because there
        # is nothing left to extract or review. Untitled for the same reason
        # the paper is titled: a booklet's title is read off the document by an
        # extraction the seed never runs (`PROD-2`).
        booklet = Booklet(
            organization_id=org.id,
            subject_id=subject.id,
            status=BookletStatus.applied,
        )
        session.add(booklet)
        await session.flush()
        paper_work = await create_work(
            session,
            kind=WorkKind.past_paper,
            organization_id=org.id,
            subject_id=subject.id,
            title=f"{subject.exam_board} {subject.name} {subject.code}/11 Paper 1 June 2026",
        )
        past_paper = PastPaper(
            work_id=paper_work.id,
            organization_id=org.id,
            booklet_id=booklet.id,
            booklet_index=1,
            subject_id=subject.id,
            # Set explicitly because the seed never runs extraction, and an
            # unnamed paper renders as "Untitled paper" everywhere the demo
            # shows it — the library, the activity feed, and the marking prompt.
            title=f"{subject.exam_board} {subject.name} {subject.code}/11 Paper 1 June 2026",
            session_label="June 2026",
            paper_number="Paper 1",
        )
        session.add(past_paper)
        await session.flush()
        session.add(
            PastPaperAttempt(
                past_paper_id=past_paper.id,
                student_id=student1.id,
                raw_marks=32,
                max_marks=40,
                timed=True,
                attempted_at=(now - timedelta(days=10)).date(),
            )
        )

        # Knowledge base entries — injected into every AI surface so the AI
        # behaves like this specific tutor.
        session.add_all(
            [
                KnowledgeEntry(
                    organization_id=org.id,
                    tutor_id=tutor.id,
                    subject_id=None,
                    kind=KnowledgeEntryKind.ai_instruction,
                    title="Tone with students",
                    body="Always be warm and encouraging, never sarcastic. Celebrate small wins.",
                ),
                KnowledgeEntry(
                    organization_id=org.id,
                    tutor_id=tutor.id,
                    subject_id=subject.id,
                    kind=KnowledgeEntryKind.marking_preference,
                    title="Chemistry equations",
                    body="Always require balanced equations with state symbols for full marks.",
                ),
            ]
        )

        await session.commit()

        for student in students:
            await write_demo_snapshot(session, student, subject.id, now)
        await session.commit()

        print("demo data created — sign in as demo-tutor@example.com / demo1234")


if __name__ == "__main__":
    asyncio.run(main())
