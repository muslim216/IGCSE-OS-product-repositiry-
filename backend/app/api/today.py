"""One aggregate endpoint for the tutor's home.

Before this, the home issued three queries plus one `groupAnalytics` per class,
and each of those looped `db.get(User)` + a TopicReadiness select **per learner**
server-side (api/analytics.py). Eight classes meant eight round trips, each
internally N+1 — the exact shape PERF-1 exists to prevent.

Everything the home needs now arrives in one response built from a bounded number
of queries: the verdict inputs, the class strip with grade, band and coverage,
today's lessons in the organization's timezone, and the review count.

group_analytics is deliberately left in place — the class page still uses it. It
simply stops being on the home's path.
"""

from collections import defaultdict

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession, TutorUser
from app.api.me import my_today_lessons
from app.models import GradeBoundary, Group
from app.schemas.today import ClassStripRow, TodayView
from app.services.grades import grade_band, predict_grade
from app.services.groups import class_health
from app.services.groups import summaries as group_summaries

router = APIRouter(prefix="/today", tags=["today"])

#: Exceptions first. A tutor opening their home is looking for what needs them,
#: so the strip is ordered by how much attention a class wants, and the healthy
#: tail collapses to one line on the surface.
_STATUS_ORDER = {"at_risk": 0, "needs_attention": 1, None: 2, "on_track": 3}


@router.get("", response_model=TodayView)
async def today_view(db: DbSession, user: TutorUser) -> TodayView:
    # Scoped by the authenticated user's own classes — never by a path or body
    # parameter (SEC-7). The role gate is in the signature (SEC-11).
    groups = (
        await db.scalars(
            select(Group)
            .where(Group.tutor_id == user.id)
            .options(selectinload(Group.subject))
            .order_by(Group.created_at)
        )
    ).all()

    summaries = await group_summaries(db, [g.id for g in groups])
    health = await class_health(db, groups)

    # Every organization override in one query, not one per class — calling
    # resolve_grade_boundaries() in the loop would reintroduce exactly the
    # per-class round trip this endpoint exists to remove. The precedence is the
    # same one it implements: the organization's override if it has one, the
    # global Subject default otherwise (RISK-5).
    overrides: dict[int, list[dict]] = defaultdict(list)
    for row in (
        await db.scalars(
            select(GradeBoundary).where(GradeBoundary.organization_id == user.organization_id)
        )
    ).all():
        overrides[row.subject_id].append({"grade": row.grade_label, "min": row.min_percentage})
    for subject_id, bands in overrides.items():
        overrides[subject_id] = sorted(bands, key=lambda b: b["min"], reverse=True)

    rows: list[ClassStripRow] = []
    for group in groups:
        summary = summaries[group.id]
        score, _contributing = health.get(group.id, (None, 0))
        boundaries = overrides.get(group.subject_id) or (
            group.subject.grade_boundaries if group.subject else []
        )
        # No score means no grade and no colour — never a defaulted one (PROD-2).
        grade = predict_grade(score, boundaries) if score is not None and boundaries else None
        rows.append(
            ClassStripRow(
                group_id=group.id,
                name=group.name,
                subject_name=group.subject.name if group.subject else "",
                score=score,
                predicted_grade=grade,
                status=grade_band(grade, boundaries),
                boundaries_missing=not boundaries,
                member_count=summary.member_count,
                students_with_evidence=summary.students_with_evidence,
                awaiting_review_count=summary.awaiting_review_count,
            )
        )
    rows.sort(key=lambda r: (_STATUS_ORDER.get(r.status, 2), -r.awaiting_review_count, r.name))

    # Summed from the per-class counts rather than re-queried. Submission is
    # polymorphic and carries no group_id — a past-paper submission has
    # assignment_id None — so a naive "count submissions for this tutor's groups"
    # join would either raise or silently drop past papers (API-20). summaries()
    # already joins through Assignment.group_id correctly; reusing it keeps one
    # definition of "awaiting review".
    review_count = sum(r.awaiting_review_count for r in rows)

    # Reuses the today-lessons handler rather than restating its timezone rule:
    # "today" is the organization's today, and one copy of that logic is what
    # keeps the aggregate and the standalone endpoint from drifting apart.
    lessons = await my_today_lessons(db, user)

    return TodayView(
        classes=rows,
        lessons=lessons,
        review_count=review_count,
        class_count=len(rows),
        joined_student_count=sum(r.member_count for r in rows),
        classes_with_evidence=sum(1 for r in rows if r.score is not None),
    )
