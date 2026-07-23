"""organizations (multi-tenant backbone)

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-23

"""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

_meta = sa.MetaData()
organizations = sa.Table(
    "organizations",
    _meta,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("name", sa.String),
    sa.Column("created_at", sa.DateTime),
)
users = sa.Table(
    "users",
    _meta,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("name", sa.String),
    sa.Column("role", sa.String),
    sa.Column("organization_id", sa.Integer),
)
groups = sa.Table(
    "groups",
    _meta,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("tutor_id", sa.Integer),
    sa.Column("organization_id", sa.Integer),
)
classifieds = sa.Table(
    "classifieds",
    _meta,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("tutor_id", sa.Integer),
    sa.Column("organization_id", sa.Integer),
)
group_members = sa.Table(
    "group_members",
    _meta,
    sa.Column("group_id", sa.Integer),
    sa.Column("student_id", sa.Integer),
)
parent_links = sa.Table(
    "parent_links",
    _meta,
    sa.Column("parent_id", sa.Integer),
    sa.Column("student_id", sa.Integer),
)


def _new_org(bind, name: str, now: datetime) -> int:
    result = bind.execute(organizations.insert().values(name=name, created_at=now))
    return result.inserted_primary_key[0]


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("organization_id", sa.Integer(), nullable=True))
    with op.batch_alter_table("groups") as batch_op:
        batch_op.add_column(sa.Column("organization_id", sa.Integer(), nullable=True))
    with op.batch_alter_table("classifieds") as batch_op:
        batch_op.add_column(sa.Column("organization_id", sa.Integer(), nullable=True))

    bind = op.get_bind()
    now = datetime.now(timezone.utc)

    # One personal organization per tutor — auto-created going forward at
    # signup; backfilled here for any tutor that predates this migration.
    tutor_org: dict[int, int] = {}
    for tutor_id, tutor_name in bind.execute(
        sa.select(users.c.id, users.c.name).where(users.c.role == "tutor")
    ).fetchall():
        org_id = _new_org(bind, f"{tutor_name}'s Organization", now)
        tutor_org[tutor_id] = org_id
        bind.execute(users.update().where(users.c.id == tutor_id).values(organization_id=org_id))

    # Students inherit the org of the (first) tutor whose group they belong to.
    student_org: dict[int, int] = {}
    for (student_id,) in bind.execute(
        sa.select(users.c.id).where(users.c.role == "student")
    ).fetchall():
        tutor_id = bind.execute(
            sa.select(groups.c.tutor_id)
            .select_from(group_members.join(groups, group_members.c.group_id == groups.c.id))
            .where(group_members.c.student_id == student_id)
            .limit(1)
        ).scalar()
        org_id = tutor_org.get(tutor_id) if tutor_id is not None else None
        if org_id is None:
            # Orphan student with no group yet — give them a placeholder org so
            # the column can be made NOT NULL; they're re-parented on joining.
            org_id = _new_org(bind, "Unassigned Organization", now)
        student_org[student_id] = org_id
        bind.execute(users.update().where(users.c.id == student_id).values(organization_id=org_id))

    # Parents inherit the org of a linked student.
    for (parent_id,) in bind.execute(
        sa.select(users.c.id).where(users.c.role == "parent")
    ).fetchall():
        linked_student_id = bind.execute(
            sa.select(parent_links.c.student_id)
            .where(parent_links.c.parent_id == parent_id)
            .limit(1)
        ).scalar()
        org_id = student_org.get(linked_student_id) if linked_student_id is not None else None
        if org_id is None:
            org_id = _new_org(bind, "Unassigned Organization", now)
        bind.execute(users.update().where(users.c.id == parent_id).values(organization_id=org_id))

    # Anyone left without an org (e.g. admin accounts) gets a placeholder.
    for (user_id,) in bind.execute(
        sa.select(users.c.id).where(users.c.organization_id.is_(None))
    ).fetchall():
        org_id = _new_org(bind, "Unassigned Organization", now)
        bind.execute(users.update().where(users.c.id == user_id).values(organization_id=org_id))

    # Groups and classifieds scope through their tutor's organization.
    for group_id, tutor_id in bind.execute(sa.select(groups.c.id, groups.c.tutor_id)).fetchall():
        bind.execute(
            groups.update()
            .where(groups.c.id == group_id)
            .values(organization_id=tutor_org.get(tutor_id))
        )
    for classified_id, tutor_id in bind.execute(
        sa.select(classifieds.c.id, classifieds.c.tutor_id)
    ).fetchall():
        bind.execute(
            classifieds.update()
            .where(classifieds.c.id == classified_id)
            .values(organization_id=tutor_org.get(tutor_id))
        )

    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("organization_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key(
            "fk_users_organization_id", "organizations", ["organization_id"], ["id"]
        )
    with op.batch_alter_table("groups") as batch_op:
        batch_op.alter_column("organization_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key(
            "fk_groups_organization_id", "organizations", ["organization_id"], ["id"]
        )
    with op.batch_alter_table("classifieds") as batch_op:
        batch_op.alter_column("organization_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key(
            "fk_classifieds_organization_id", "organizations", ["organization_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("classifieds") as batch_op:
        batch_op.drop_constraint("fk_classifieds_organization_id", type_="foreignkey")
        batch_op.drop_column("organization_id")
    with op.batch_alter_table("groups") as batch_op:
        batch_op.drop_constraint("fk_groups_organization_id", type_="foreignkey")
        batch_op.drop_column("organization_id")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("fk_users_organization_id", type_="foreignkey")
        batch_op.drop_column("organization_id")
    op.drop_table("organizations")
