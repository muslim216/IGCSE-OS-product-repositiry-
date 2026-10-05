"""What is set up, from the data — onboarding's server side (task 9.1a).

**Nothing here is stored except acknowledgements.** A Required step is done when
the rows that make it real exist (a chapter, a timetable slot, saved plan inputs,
an accepted plan). A Defaulted item is `set_by_you` when the code has persisted a
value the tutor must have chosen, `reviewed` when they acknowledged the default,
and `default` otherwise. The frontend gate is never the control (`SEC-10`); this
is what decides.

**Honesty about what the data can tell apart (`PROD-2`).** Some defaults are
written as ordinary rows (mistake categories by `ensure_categories`, an org's
timezone from the browser at signup) so "stored" does not mean "chosen". Where a
value provably differs from the default it is `set_by_you`; where it equals the
default it stays `default` unless acknowledged. A tutor who saved the unchanged
defaults is therefore shown `default` until they acknowledge — never the
reverse, never an unset value presented as set.

Decision logic is pure (`build_state`, dataclasses in, schema out, `BE-4`); the
loader runs a fixed number of queries however many subjects and classes there are
(`PERF-1`).
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ACCOUNT_ITEMS,
    Assignment,
    Chapter,
    GradeBoundary,
    Group,
    GroupMember,
    Lesson,
    MistakeCategory,
    Organization,
    ReadinessWeights,
    ScheduleSlot,
    SetupAcknowledgement,
    SetupItem,
    Subject,
    TeachingPlan,
    TeachingPlanStatus,
    User,
)
from app.models.base import utcnow
from app.schemas.onboarding import (
    ClassStatus,
    ItemState,
    ItemStatus,
    NextStep,
    OnboardingState,
    StepDone,
    SubjectStatus,
)
from app.services.mistake_categories import DEFAULT_CATEGORIES
from app.services.readiness_config import DEFAULT_WEAK_THRESHOLD

# The columns' own defaults (models/orgs.py): an org whose values still equal
# these has changed nothing, an org whose values differ certainly has.
DEFAULT_WEEKLY_SEND_WEEKDAY = 6
DEFAULT_WEEKLY_SEND_HOUR = 17
DEFAULT_AI_LANGUAGE = "en"

#: Fixed order, as the checklist shows them.
SUBJECT_ITEM_ORDER = (
    SetupItem.boundaries,
    SetupItem.marking_rules,
    SetupItem.mistake_categories,
    SetupItem.weak_threshold,
)
TEACHING_GUIDANCE = "teaching_guidance"

#: Class Required steps in flow order. `taught_before` ("where are you up to",
#: task 9.1b) sits before the plan steps because the drafter reads what has
#: already been taught, so the answer has to exist before the inputs and the draft.
CLASS_STEP_ORDER = ("timetable", "taught_before", "plan_inputs", "plan_accepted")


@dataclass(frozen=True)
class AccountFacts:
    differs_from_default: bool
    acknowledged: bool


@dataclass(frozen=True)
class SubjectFacts:
    id: int
    name: str
    chapter_count: int
    has_boundaries: bool
    has_marking_rules: bool
    has_guidance: bool
    categories_differ: bool
    threshold_differs: bool
    acknowledged: frozenset[SetupItem] = frozenset()


@dataclass(frozen=True)
class ClassFacts:
    id: int
    name: str
    subject_id: int
    has_slots: bool
    #: The tutor answered at all; "starting fresh" (no topics) is an answer.
    taught_before_answered: bool
    has_plan_inputs: bool
    plan_accepted: bool
    #: The class is already being run on Avora: it has a student, a recorded
    #: lesson or a piece of homework. The flow creates none of those, so a class
    #: that has one was not made by a tutor who is still setting up.
    in_use: bool = False


def categories_differ(rows: Iterable[tuple[str, str | None, bool]]) -> bool:
    """Whether a subject's category rows are anything other than the published
    defaults — (name, description, archived) per row, archived ones included.

    No rows is *not* different: nothing has been written, so the defaults are
    what would be used. Any archived row, rename, edit, addition or removal is a
    decision `ensure_categories` never makes.

    This compares stored rows with `DEFAULT_CATEGORIES` as it is *now*. Editing
    that list in a later release makes every subject seeded under the old text
    read as `set_by_you` though its tutor changed nothing: change the defaults
    and this comparison together.
    """
    rows = list(rows)
    if not rows:
        return False
    if any(archived for _, _, archived in rows) or len(rows) != len(DEFAULT_CATEGORIES):
        return True
    return {(name, description) for name, description, _ in rows} != {
        (c["name"], c["description"]) for c in DEFAULT_CATEGORIES
    }


def defaulted_state(set_by_you: bool, acknowledged: bool) -> ItemState:
    if set_by_you:
        return "set_by_you"
    return "reviewed" if acknowledged else "default"


def _class_steps(c: ClassFacts) -> list[StepDone]:
    done = {
        "timetable": c.has_slots,
        "taught_before": c.taught_before_answered,
        "plan_inputs": c.has_plan_inputs,
        "plan_accepted": c.plan_accepted,
    }
    return [StepDone(key=k, done=done[k]) for k in CLASS_STEP_ORDER]


def _subject_items(s: SubjectFacts) -> list[ItemStatus]:
    set_by_you = {
        SetupItem.boundaries: s.has_boundaries,
        SetupItem.marking_rules: s.has_marking_rules,
        SetupItem.mistake_categories: s.categories_differ,
        SetupItem.weak_threshold: s.threshold_differs,
    }
    items = [
        ItemStatus(
            key=item.value,
            kind="defaulted",
            state=defaulted_state(set_by_you[item], item in s.acknowledged),
        )
        for item in SUBJECT_ITEM_ORDER
    ]
    # Boundaries have no default in force: the published list is offered in the
    # editor and never written, and a subject with no rows has no predicted
    # grade anywhere (services/grade_boundaries.py, `PROD-2`). So without rows
    # this is "not_set" whatever was acknowledged — "default" would claim grades
    # are being mapped through something. It is not counted as reviewed.
    if not s.has_boundaries:
        items[0] = ItemStatus(key=SetupItem.boundaries.value, kind="defaulted", state="not_set")
    # Optional: never counts against completion, and never "default" — an absent
    # document is absent, not a default in force.
    items.append(
        ItemStatus(
            key=TEACHING_GUIDANCE,
            kind="optional",
            state="set_by_you" if s.has_guidance else "not_set",
        )
    )
    return items


def build_state(
    account: AccountFacts, subjects: list[SubjectFacts], classes: list[ClassFacts]
) -> OnboardingState:
    by_subject: dict[int, list[ClassFacts]] = defaultdict(list)
    for c in classes:
        by_subject[c.subject_id].append(c)

    out: list[SubjectStatus] = []
    complete = False
    # The class closest to finished among subjects whose syllabus is in: what
    # `next_step` points at (steps done, subject id, class id, first undone step).
    best: tuple[int, int, int, str] | None = None
    subject_without_class: int | None = None
    subject_without_syllabus: int | None = None

    for s in subjects:
        syllabus_done = s.chapter_count > 0
        items = _subject_items(s)
        defaulted = [i for i in items if i.kind == "defaulted"]
        class_out: list[ClassStatus] = []
        for c in by_subject.get(s.id, []):
            steps = _class_steps(c)
            class_done = all(st.done for st in steps)
            class_out.append(
                ClassStatus(group_id=c.id, group_name=c.name, steps=steps, complete=class_done)
            )
            if not syllabus_done:
                continue
            if class_done:
                complete = True
                continue
            score = sum(st.done for st in steps)
            if best is None or score > best[0]:
                best = (score, s.id, c.id, next(st.key for st in steps if not st.done))
        if syllabus_done and not by_subject.get(s.id) and subject_without_class is None:
            subject_without_class = s.id
        if not syllabus_done and subject_without_syllabus is None:
            subject_without_syllabus = s.id
        out.append(
            SubjectStatus(
                subject_id=s.id,
                subject_name=s.name,
                required=[StepDone(key="syllabus", done=syllabus_done)],
                items=items,
                reviewed_count=sum(i.state in ("reviewed", "set_by_you") for i in defaulted),
                review_total=len(defaulted),
                classes=class_out,
            )
        )

    next_step: NextStep | None = None
    if not complete:
        if best is not None:
            next_step = NextStep(key=best[3], subject_id=best[1], group_id=best[2])
        elif subject_without_class is not None:
            # The class itself is the first half of the timetable step: a class
            # that does not exist cannot have one.
            next_step = NextStep(
                key=CLASS_STEP_ORDER[0], subject_id=subject_without_class, group_id=None
            )
        else:
            next_step = NextStep(key="syllabus", subject_id=subject_without_syllabus, group_id=None)

    return OnboardingState(
        complete=complete,
        # The finish line is an accepted plan on any of the caller's classes. A
        # tutor already running a class is past it too, plan or no plan: the flow
        # arrived after they started, and taking their dashboard away to walk
        # them through setup would be a regression (owner, 2026-10-06). What they
        # still owe is on the checklist. "No class yet" alone would not do as the
        # test: the flow's own class step would end the flow three steps early.
        in_flow=not any(c.plan_accepted or c.in_use for c in classes),
        account=ItemStatus(
            key=SetupItem.account_basics.value,
            kind="defaulted",
            state=defaulted_state(account.differs_from_default, account.acknowledged),
        ),
        subjects=out,
        next_step=next_step,
    )


async def load_state(db: AsyncSession, user: User) -> OnboardingState:
    """The caller's organization's onboarding state, in a fixed number of queries."""
    org_id = user.organization_id

    org = await db.get(Organization, org_id)
    assert org is not None  # a user always has one
    acks = (
        await db.execute(
            select(SetupAcknowledgement.subject_id, SetupAcknowledgement.item).where(
                SetupAcknowledgement.organization_id == org_id
            )
        )
    ).all()
    acked: dict[int | None, set[SetupItem]] = defaultdict(set)
    for ack_subject_id, ack_item in acks:
        acked[ack_subject_id].add(ack_item)

    # Subjects are tenant-owned (task 2.2), so "this organization's subjects" is
    # exactly Subject.organization_id.
    subjects = (
        await db.scalars(
            select(Subject).where(Subject.organization_id == org_id).order_by(Subject.id)
        )
    ).all()
    subject_ids = [s.id for s in subjects]
    # The tutor's own classes, as `list_groups` / `today.tutor_groups` do — an
    # admin sees theirs too, not every class in the organization.
    groups = (
        await db.scalars(
            select(Group)
            .where(Group.tutor_id == user.id, Group.organization_id == org_id)
            .order_by(Group.created_at, Group.id)
        )
    ).all()
    group_ids = [g.id for g in groups]

    chapters: dict[int, int] = dict(
        (
            await db.execute(
                select(Chapter.subject_id, func.count())
                .where(Chapter.subject_id.in_(subject_ids))
                .group_by(Chapter.subject_id)
            )
        )
        .tuples()
        .all()
    )
    boundary_subjects = set(
        await db.scalars(
            select(GradeBoundary.subject_id)
            .where(GradeBoundary.organization_id == org_id)
            .distinct()
        )
    )
    # The subject's own row wins over the account row (key None), as in
    # `resolve_readiness_config`. The row is written whole by the weights editor,
    # so its existence says only that *something* was saved there: a tutor who
    # changed one factor weight has not chosen a threshold. Only a value other
    # than the default shows that they did.
    thresholds: dict[int | None, float] = dict(
        (
            await db.execute(
                select(ReadinessWeights.subject_id, ReadinessWeights.weak_threshold).where(
                    ReadinessWeights.organization_id == org_id
                )
            )
        )
        .tuples()
        .all()
    )
    category_rows: dict[int, list[tuple[str, str | None, bool]]] = defaultdict(list)
    for cat_subject_id, name, description, archived_at in (
        await db.execute(
            select(
                MistakeCategory.subject_id,
                MistakeCategory.name,
                MistakeCategory.description,
                MistakeCategory.archived_at,
            ).where(MistakeCategory.organization_id == org_id)
        )
    ).all():
        category_rows[cat_subject_id].append((name, description, archived_at is not None))

    slot_groups = set(
        await db.scalars(
            select(ScheduleSlot.group_id).where(ScheduleSlot.group_id.in_(group_ids)).distinct()
        )
    )
    plan_status: dict[int, set[TeachingPlanStatus]] = defaultdict(set)
    for plan_group_id, plan_state in (
        await db.execute(
            select(TeachingPlan.group_id, TeachingPlan.status).where(
                TeachingPlan.group_id.in_(group_ids)
            )
        )
    ).all():
        plan_status[plan_group_id].add(plan_state)

    in_use_groups: set[int] = set()
    for column in (GroupMember.group_id, Lesson.group_id, Assignment.group_id):
        in_use_groups.update(
            await db.scalars(select(column).where(column.in_(group_ids)).distinct())
        )

    account = AccountFacts(
        differs_from_default=(
            org.weekly_send_weekday != DEFAULT_WEEKLY_SEND_WEEKDAY
            or org.weekly_send_hour != DEFAULT_WEEKLY_SEND_HOUR
            or org.ai_language != DEFAULT_AI_LANGUAGE
        ),
        acknowledged=SetupItem.account_basics in acked[None],
    )
    subject_facts = [
        SubjectFacts(
            id=s.id,
            name=s.name,
            chapter_count=chapters.get(s.id, 0),
            has_boundaries=s.id in boundary_subjects,
            has_marking_rules=bool(s.marking_rules),
            has_guidance=s.guidance_path is not None,
            categories_differ=categories_differ(category_rows.get(s.id, [])),
            threshold_differs=thresholds.get(s.id, thresholds.get(None, DEFAULT_WEAK_THRESHOLD))
            != DEFAULT_WEAK_THRESHOLD,
            acknowledged=frozenset(acked[s.id]),
        )
        for s in subjects
    ]
    class_facts = [
        ClassFacts(
            id=g.id,
            name=g.name,
            subject_id=g.subject_id,
            has_slots=g.id in slot_groups,
            # Read off the rows already loaded; `taught_before.answered_group_ids`
            # is the same test for a caller that has only ids.
            taught_before_answered=g.taught_before_answered_at is not None,
            # A plan row of either status means inputs were saved: a draft only
            # exists once they are (`request_draft` refuses without one), and an
            # accepted plan was a draft.
            has_plan_inputs=bool(plan_status.get(g.id)),
            plan_accepted=TeachingPlanStatus.accepted in plan_status.get(g.id, ()),
            in_use=g.id in in_use_groups,
        )
        for g in groups
    ]
    return build_state(account, subject_facts, class_facts)


class AcknowledgementError(Exception):
    """A request that names the wrong shape of item/subject (422)."""


class SubjectNotFound(Exception):
    """No such subject in the caller's organization (404, `API-7`)."""


async def acknowledge(
    db: AsyncSession, user: User, item: SetupItem, subject_id: int | None
) -> None:
    """Record that the caller reviewed one default. Idempotent, race-safe."""
    if item in ACCOUNT_ITEMS:
        if subject_id is not None:
            raise AcknowledgementError("This item is account-wide; it takes no subject")
    else:
        if subject_id is None:
            raise AcknowledgementError("This item is per subject; a subject is required")
        subject = await db.get(Subject, subject_id)
        if subject is None or subject.organization_id != user.organization_id:
            raise SubjectNotFound
    existing = await db.scalar(
        select(SetupAcknowledgement.id).where(
            SetupAcknowledgement.organization_id == user.organization_id,
            SetupAcknowledgement.subject_id.is_(None)
            if subject_id is None
            else SetupAcknowledgement.subject_id == subject_id,
            SetupAcknowledgement.item == item,
        )
    )
    if existing is not None:
        return
    try:
        # A savepoint, so losing a race to the unique indexes rolls back only
        # this insert, not the caller's transaction.
        async with db.begin_nested():
            db.add(
                SetupAcknowledgement(
                    organization_id=user.organization_id,
                    subject_id=subject_id,
                    item=item,
                    acknowledged_by_id=user.id,
                    acknowledged_at=utcnow(),
                )
            )
    except IntegrityError:
        return  # the other request's row is the acknowledgement
