"""Schema only (P-3 part 1): the tables exist and a child has at most one pending request."""

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.db import async_session, engine
from app.models import (
    ErasureRequest,
    ErasureRequesterRole,
    ErasureRequestStatus,
    Organization,
    UserRole,
)
from app.models.base import utcnow
from tests.factories import make_user


async def test_tables_exist():
    async with engine.connect() as conn:
        names = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
    assert {"erasure_requests", "data_exports"} <= names


async def test_one_pending_request_per_student_until_cancelled():
    async with async_session() as db:
        org = Organization(name="o")
        db.add(org)
        await db.flush()
        kid = await make_user(
            db, organization_id=org.id, role=UserRole.student, name="Kid", email="kid@example.com"
        )

        def new_request() -> ErasureRequest:
            return ErasureRequest(
                organization_id=org.id,
                student_id=kid.id,
                requested_role=ErasureRequesterRole.tutor,
                scheduled_for=utcnow(),
            )

        first = new_request()
        db.add(first)
        await db.flush()

        db.add(new_request())
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()

        # Rolled back with the rest of the transaction; redo the first, cancel it.
        org = Organization(name="o2")
        db.add(org)
        await db.flush()
        kid = await make_user(
            db, organization_id=org.id, role=UserRole.student, name="Kid", email="kid2@example.com"
        )
        first = new_request()
        db.add(first)
        await db.flush()
        first.status = ErasureRequestStatus.cancelled
        await db.flush()
        db.add(new_request())
        await db.flush()  # allowed: the first is no longer pending
