"""The demo seed shows v2 readiness without ever calling a model (5.3a).

With no AI key the real `compute_readiness_v2` job writes `failed` snapshots, so
a demo seeded that way would show nothing; with a key it would spend money on
every demo load. The seed therefore writes Layer 1's own deterministic answer.
"""

import pytest
from sqlalchemy import func, select

import app.services.readiness_v2_ai as readiness_v2_ai
from app.db import async_session
from app.models import AiSynthesisStatus, AiUsageEvent, ReadinessSnapshot, Subject, User, UserRole
from app.services.readiness_summary_v2 import build_summary_v2
from seed import demo


async def test_demo_seed_writes_ready_v2_snapshots_without_ai(monkeypatch):
    async def _no_model(*args, **kwargs):
        raise AssertionError("the demo seed must not call a model")

    monkeypatch.setattr(readiness_v2_ai, "structured_complete", _no_model)

    await demo.main()

    async with async_session() as session:
        # Every seeded learner, the username-only demo_ali included.
        students = (await session.scalars(select(User).where(User.role == UserRole.student))).all()
        chemistry = await session.scalar(select(Subject).where(Subject.name == "Chemistry"))
        assert students and chemistry is not None

        for student in students:
            snapshots = (
                await session.scalars(
                    select(ReadinessSnapshot).where(
                        ReadinessSnapshot.student_id == student.id,
                        ReadinessSnapshot.subject_id == chemistry.id,
                    )
                )
            ).all()
            assert [s.status for s in snapshots] == [AiSynthesisStatus.ready]

        main_student = next(s for s in students if s.email == "demo-student@example.com")
        summary = await build_summary_v2(session, main_student, [chemistry.id])
        [entry] = summary.subjects
        assert entry.score is not None

        assert await session.scalar(select(func.count()).select_from(AiUsageEvent)) == 0


@pytest.fixture(autouse=True)
def _no_ai_key(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "", raising=False)
