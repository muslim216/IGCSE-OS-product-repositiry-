from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import DbSession, StudentUser, TutorUser
from app.models import (
    Assessment,
    AssessmentScore,
    AssessmentType,
    Evidence,
    EvidenceSource,
    Group,
    GroupMember,
    Subject,
    Topic,
    TutorObservation,
)
from app.schemas.readiness import (
    AssessmentCreate,
    AssessmentOut,
    MyAssessmentScore,
    ObservationCreate,
    ObservationOut,
    SeedReadinessIn,
)
from app.services.readiness_v2_ai import enqueue_v2_shadow
from app.workers.jobs import enqueue

router = APIRouter(tags=["assessments"])


async def _tutor_teaches(db, tutor_id: int, student_id: int, subject_id: int) -> bool:
    row = await db.scalar(
        select(GroupMember.id)
        .join(Group, Group.id == GroupMember.group_id)
        .where(
            GroupMember.student_id == student_id,
            Group.tutor_id == tutor_id,
            Group.subject_id == subject_id,
        )
        .limit(1)
    )
    return row is not None


@router.post("/assessments", response_model=AssessmentOut, status_code=status.HTTP_201_CREATED)
async def create_assessment(
    body: AssessmentCreate, db: DbSession, user: TutorUser
) -> AssessmentOut:
    subject = await db.get(Subject, body.subject_id)
    if subject is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subject not found")

    assessment = Assessment(
        tutor_id=user.id,
        subject_id=subject.id,
        title=body.title,
        type=AssessmentType(body.type),
        date=body.date,
    )
    db.add(assessment)
    await db.flush()

    occurred = datetime(body.date.year, body.date.month, body.date.day, tzinfo=timezone.utc)
    affected_students: set[int] = set()
    for s in body.scores:
        if not await _tutor_teaches(db, user.id, s.student_id, subject.id):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "You can only enter marks for students you teach this subject",
            )
        if s.topic_id is not None:
            topic = await db.get(Topic, s.topic_id)
            if topic is None or topic.subject_id != subject.id:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid topic for subject"
                )
        if s.marks > s.max_marks:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "marks cannot exceed max_marks"
            )
        db.add(
            AssessmentScore(
                assessment_id=assessment.id,
                student_id=s.student_id,
                topic_id=s.topic_id,
                marks=s.marks,
                max_marks=s.max_marks,
            )
        )
        score_pct = round(s.marks / s.max_marks * 100, 1)
        source_ref = f"assessment:{assessment.id}"
        if s.topic_id is not None:
            # Per-topic score → evidence on that topic.
            db.add(
                Evidence(
                    student_id=s.student_id,
                    topic_id=s.topic_id,
                    source_type=EvidenceSource.mock,
                    score_pct=score_pct,
                    max_marks=s.max_marks,
                    occurred_at=occurred,
                    source_ref=source_ref,
                    label=body.title,
                )
            )
        else:
            # Overall score → spread as evidence across every topic of the subject.
            topics = (await db.scalars(select(Topic).where(Topic.subject_id == subject.id))).all()
            for topic in topics:
                db.add(
                    Evidence(
                        student_id=s.student_id,
                        topic_id=topic.id,
                        source_type=EvidenceSource.mock,
                        score_pct=score_pct,
                        max_marks=s.max_marks,
                        occurred_at=occurred,
                        source_ref=source_ref,
                        label=f"{body.title} (overall)",
                    )
                )
        affected_students.add(s.student_id)

    for student_id in affected_students:
        await enqueue(
            db, "recompute_readiness", {"student_id": student_id, "subject_id": subject.id}
        )
        await enqueue_v2_shadow(db, student_id, subject.id)
    await db.commit()
    return AssessmentOut(
        id=assessment.id,
        subject_id=subject.id,
        title=assessment.title,
        type=assessment.type.value,
        date=assessment.date,
        score_count=len(body.scores),
    )


@router.get("/assessments", response_model=list[AssessmentOut])
async def list_assessments(
    db: DbSession, user: TutorUser, subject_id: int | None = None
) -> list[AssessmentOut]:
    query = (
        select(Assessment).where(Assessment.tutor_id == user.id).order_by(Assessment.date.desc())
    )
    if subject_id is not None:
        query = query.where(Assessment.subject_id == subject_id)
    rows = (await db.scalars(query)).all()
    out = []
    for a in rows:
        count = await db.scalar(
            select(func.count(AssessmentScore.id)).where(AssessmentScore.assessment_id == a.id)
        )
        out.append(
            AssessmentOut(
                id=a.id,
                subject_id=a.subject_id,
                title=a.title,
                type=a.type.value,
                date=a.date,
                score_count=count or 0,
            )
        )
    return out


@router.get("/me/assessments", response_model=list[MyAssessmentScore])
async def my_assessments(db: DbSession, user: StudentUser) -> list[MyAssessmentScore]:
    rows = (
        await db.execute(
            select(AssessmentScore, Assessment, Subject, Topic)
            .join(Assessment, Assessment.id == AssessmentScore.assessment_id)
            .join(Subject, Subject.id == Assessment.subject_id)
            .outerjoin(Topic, Topic.id == AssessmentScore.topic_id)
            .where(AssessmentScore.student_id == user.id)
            .order_by(Assessment.date.desc())
        )
    ).all()
    return [
        MyAssessmentScore(
            assessment_id=assessment.id,
            title=assessment.title,
            type=assessment.type.value,
            date=assessment.date,
            subject_id=subject.id,
            subject_name=subject.name,
            topic_id=topic.id if topic else None,
            topic_title=topic.title if topic else None,
            marks=score.marks,
            max_marks=score.max_marks,
            pct=round(score.marks / score.max_marks * 100, 1) if score.max_marks else 0.0,
        )
        for score, assessment, subject, topic in rows
    ]


@router.post("/observations", response_model=ObservationOut, status_code=status.HTTP_201_CREATED)
async def create_observation(
    body: ObservationCreate, db: DbSession, user: TutorUser
) -> ObservationOut:
    # The tutor must share at least one group with the student.
    shares = await db.scalar(
        select(GroupMember.id)
        .join(Group, Group.id == GroupMember.group_id)
        .where(GroupMember.student_id == body.student_id, Group.tutor_id == user.id)
        .limit(1)
    )
    if shares is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found in your groups")

    subject_id_for_recompute: int | None = None
    if body.topic_id is not None:
        topic = await db.get(Topic, body.topic_id)
        if topic is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Topic not found")
        subject_id_for_recompute = topic.subject_id

    observation = TutorObservation(
        tutor_id=user.id,
        student_id=body.student_id,
        topic_id=body.topic_id,
        comment=body.comment,
        rating=body.rating,
    )
    db.add(observation)
    await db.flush()

    # A rating on a specific topic feeds readiness as observation evidence.
    if body.rating is not None and body.topic_id is not None:
        db.add(
            Evidence(
                student_id=body.student_id,
                topic_id=body.topic_id,
                source_type=EvidenceSource.observation,
                score_pct=float(body.rating),
                max_marks=0,
                occurred_at=datetime.now(timezone.utc),
                source_ref=f"observation:{observation.id}",
                label="Tutor observation",
            )
        )
        await enqueue(
            db,
            "recompute_readiness",
            {"student_id": body.student_id, "subject_id": subject_id_for_recompute},
        )
        await enqueue_v2_shadow(db, body.student_id, subject_id_for_recompute)
    await db.commit()
    return ObservationOut(
        id=observation.id,
        student_id=observation.student_id,
        topic_id=observation.topic_id,
        comment=observation.comment,
        rating=observation.rating,
        created_at=observation.created_at,
    )


@router.post("/students/{student_id}/seed-readiness", status_code=status.HTTP_201_CREATED)
async def seed_readiness(
    student_id: int, body: SeedReadinessIn, db: DbSession, user: TutorUser
) -> dict:
    """A tutor's own starting assessment of a student, per topic.

    This is step 5 of the cold start (spec §7.1), and it deliberately cannot
    happen earlier: students attach themselves by invite code, so a tutor
    finishing setup has no students to rate. It is also optional, because for
    many classes it never happens — the product has to work when it does not.

    What is written is `Evidence` with `source_type=tutor_estimate`, which means
    it goes through exactly the same pipeline as every other source and needs no
    parallel code path (PROD-9's shape, applied to a new source). It is
    self-declared and labelled as such wherever it is shown (PROD-8), and it
    loses weight against real marked work as that arrives (§7.3).

    Re-seeding the same topic replaces the previous estimate rather than adding
    a second one: this is the tutor's current opinion, not a history of their
    opinions, and stacking them would let one topic be seeded into a score.

    **Known gap (RISK-5).** The estimate's numeric value drives the v1 engine.
    Readiness Engine v2 — the default served engine — computes topic mastery from
    marked questions and reads Evidence only as a "practised" flag, so it does
    not consume the estimate's percentage. This is not unique to seeding: every
    Evidence-only source (tutor observations, entered mocks) has the same limit
    under v2, and closing it means teaching v2 to score from Evidence, which is
    the RISK-5 convergence work, not a cold-start change. Until then the seed's
    number is fully honoured only where v1 answers.
    """
    # Which subjects this tutor actually teaches *this* student. Authorizing the
    # student once is not enough: topics are global, so a tutor who teaches Sara
    # Chemistry could otherwise seed a Physics topic onto her record for a
    # subject they have nothing to do with (Qodo). Every submitted topic's
    # subject must be in this set — checked in one query, not one per topic.
    taught_subjects = set(
        (
            await db.scalars(
                select(Group.subject_id)
                .join(GroupMember, GroupMember.group_id == Group.id)
                .where(GroupMember.student_id == student_id, Group.tutor_id == user.id)
            )
        ).all()
    )
    if not taught_subjects:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found in your groups")

    # The tutor's current opinion, so a repeated topic in one payload is the last
    # value, not two rows. Deduping here also bounds the work to the distinct
    # topics regardless of payload shape.
    scored: dict[int, float] = {e.topic_id: float(e.score_pct) for e in body.topics}
    topic_ids = list(scored)

    topics = {
        t.id: t for t in (await db.scalars(select(Topic).where(Topic.id.in_(topic_ids)))).all()
    }
    for topic_id in topic_ids:
        topic = topics.get(topic_id)
        # A topic for a subject the tutor does not teach this student is treated
        # as not found rather than 403 — a global integer key must not confirm
        # what it points at across an authorization boundary (API-7 / SEC-9).
        if topic is None or topic.subject_id not in taught_subjects:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Topic not available for this student")

    # Existing seed rows for these topics, in one read, so re-seeding replaces in
    # place without a per-topic SELECT.
    refs = {topic_id: f"tutor_estimate:{student_id}:{topic_id}" for topic_id in topic_ids}
    existing = {
        e.source_ref: e
        for e in (
            await db.scalars(select(Evidence).where(Evidence.source_ref.in_(list(refs.values()))))
        ).all()
    }

    now = datetime.now(timezone.utc)
    for topic_id, score_pct in scored.items():
        row = existing.get(refs[topic_id])
        if row is None:
            row = Evidence(
                student_id=student_id,
                topic_id=topic_id,
                source_type=EvidenceSource.tutor_estimate,
                source_ref=refs[topic_id],
            )
            db.add(row)
        row.score_pct = score_pct
        row.max_marks = 0
        row.occurred_at = now
        row.label = "Tutor's starting estimate (self-declared)"

    for subject_id in {topics[topic_id].subject_id for topic_id in topic_ids}:
        await enqueue(
            db, "recompute_readiness", {"student_id": student_id, "subject_id": subject_id}
        )
        await enqueue_v2_shadow(db, student_id, subject_id)
    await db.commit()
    return {"seeded": len(topic_ids)}


@router.get("/students/{student_id}/observations", response_model=list[ObservationOut])
async def list_observations(
    student_id: int, db: DbSession, user: TutorUser
) -> list[ObservationOut]:
    shares = await db.scalar(
        select(GroupMember.id)
        .join(Group, Group.id == GroupMember.group_id)
        .where(GroupMember.student_id == student_id, Group.tutor_id == user.id)
        .limit(1)
    )
    if shares is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found in your groups")
    rows = (
        await db.scalars(
            select(TutorObservation)
            .where(TutorObservation.student_id == student_id, TutorObservation.tutor_id == user.id)
            .order_by(TutorObservation.created_at.desc())
        )
    ).all()
    return [
        ObservationOut(
            id=o.id,
            student_id=o.student_id,
            topic_id=o.topic_id,
            comment=o.comment,
            rating=o.rating,
            created_at=o.created_at,
        )
        for o in rows
    ]
