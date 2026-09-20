"""The tutor revising a mistake the tagging job proposed (4.3, `AV-38`).

Editable from the marked-work view, with no prompt, no queue and no blocking
step: the tag counts from the moment the job writes it, and a tutor who never
touches it changes nothing. What this file pins down is what happens when one
does — the row becomes theirs (E17), the change is on the record (`PROD-7`,
`AI-12`), and neither the job nor another tenant can reach past it.
"""

import pytest
from sqlalchemy import func, select

from app.db import async_session
from app.models import (
    Job,
    Mistake,
    MistakeRevisionAudit,
    MistakeSource,
    Mock,
    MockQuestion,
    PastPaperQuestion,
    QuestionMark,
    Submission,
    SubmissionStatus,
    WorkKind,
)
from app.models.base import utcnow
from app.services.work import create_work
from tests.factories import make_mistake_category, make_past_paper, make_subject, other_org_subject


@pytest.fixture
async def tagged(client, tutor):
    """A finalized past-paper submission carrying one AI-tagged mistake.

    A past paper because ownership of one is organization-level, which is the
    plainest way to put a submission in this tutor's reach; the revision path
    itself reads the work row, not the kind.
    """
    async with async_session() as session:
        subject = await make_subject(session, code="4BI1", name="Biology")
        org_id, subject_id = subject.organization_id, subject.id
        paper = await make_past_paper(session, subject_id=subject_id, organization_id=org_id)
        submission = Submission(
            work_id=paper.work_id,
            student_id=tutor["user"]["id"],
            status=SubmissionStatus.finalized,
            mistakes_analysed_at=utcnow(),
        )
        session.add(submission)
        await session.flush()
        question = PastPaperQuestion(
            past_paper_id=paper.id,
            position=0,
            number="1",
            text_summary="Define an isotope",
            max_marks=2,
            has_mark_scheme=True,
        )
        session.add(question)
        await session.flush()
        mark = QuestionMark(
            submission_id=submission.id, past_paper_question_id=question.id, final_marks=0
        )
        session.add(mark)
        await session.flush()
        careless = await make_mistake_category(
            session, organization_id=org_id, subject_id=subject_id, name="careless"
        )
        method = await make_mistake_category(
            session, organization_id=org_id, subject_id=subject_id, name="method"
        )
        retired = await make_mistake_category(
            session,
            organization_id=org_id,
            subject_id=subject_id,
            name="retired",
            archived_at=utcnow(),
        )
        mistake = Mistake(
            student_id=tutor["user"]["id"],
            question_mark_id=mark.id,
            category_id=careless.id,
            severity=1,
            source=MistakeSource.ai,
        )
        session.add(mistake)
        await session.commit()
        return {
            "mark_id": mark.id,
            "submission_id": submission.id,
            "past_paper_id": paper.id,
            "mistake_id": mistake.id,
            "careless_id": careless.id,
            "method_id": method.id,
            "retired_id": retired.id,
            "organization_id": org_id,
            "subject_id": subject_id,
        }


async def _audits(mistake_id: int) -> list[MistakeRevisionAudit]:
    async with async_session() as session:
        return list(
            (
                await session.scalars(
                    select(MistakeRevisionAudit).where(
                        MistakeRevisionAudit.mistake_id == mistake_id
                    )
                )
            ).all()
        )


async def test_a_revision_makes_the_mistake_the_tutors_own(client, tutor, tagged):
    """The whole of E17's enforcement. The job deletes `source="ai"` rows and
    only those, so flipping the column is what puts a tutor's judgement beyond
    the next run's reach — no second row, no extra flag."""
    resp = await client.patch(
        f"/api/v1/submissions/{tagged['submission_id']}/mistakes/{tagged['mistake_id']}",
        json={"category_id": tagged["method_id"], "severity": 3},
        headers=tutor["headers"],
    )
    assert resp.status_code == 200, resp.text

    async with async_session() as session:
        mistake = await session.get(Mistake, tagged["mistake_id"])
        assert mistake.category_id == tagged["method_id"]
        assert mistake.severity == 3
        assert mistake.source is MistakeSource.tutor


async def test_a_revision_is_on_the_record(client, tutor, tagged):
    """`PROD-7` and `AI-12`: a tutor override of AI output writes an
    append-only row, so "why is this tagged that" is answerable months later.
    Both sides of the change are stored — an audit that records only the new
    value cannot answer the question it exists for."""
    await client.patch(
        f"/api/v1/submissions/{tagged['submission_id']}/mistakes/{tagged['mistake_id']}",
        json={"category_id": tagged["method_id"], "severity": 3},
        headers=tutor["headers"],
    )
    rows = await _audits(tagged["mistake_id"])
    assert len(rows) == 1
    assert rows[0].old_category_id == tagged["careless_id"]
    assert rows[0].new_category_id == tagged["method_id"]
    assert rows[0].old_severity == 1
    assert rows[0].new_severity == 3
    assert rows[0].changed_by_id == tutor["user"]["id"]


async def test_saving_an_unchanged_tag_records_nothing(client, tutor, tagged):
    """A re-sent save or a double-click is not a decision. Without this the
    trail fills with `careless -> careless` rows and the one real revision in
    it stops being findable."""
    resp = await client.patch(
        f"/api/v1/submissions/{tagged['submission_id']}/mistakes/{tagged['mistake_id']}",
        json={"category_id": tagged["careless_id"], "severity": 1},
        headers=tutor["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert await _audits(tagged["mistake_id"]) == []
    async with async_session() as session:
        mistake = await session.get(Mistake, tagged["mistake_id"])
        # Still the AI's: nothing was decided, so nothing is claimed.
        assert mistake.source is MistakeSource.ai


async def test_a_revision_queues_a_readiness_recompute(client, tutor, tagged):
    """`AV-37`: a mistake counts immediately. Severity feeds the Mistake
    Analysis factor and the category is what it groups by, so a revision that
    never reached readiness would leave the score describing the AI's opinion
    after the tutor had corrected it — until the student's next piece of work
    happened to be marked."""
    await client.patch(
        f"/api/v1/submissions/{tagged['submission_id']}/mistakes/{tagged['mistake_id']}",
        json={"category_id": tagged["method_id"], "severity": 2},
        headers=tutor["headers"],
    )
    async with async_session() as session:
        queued = (
            await session.scalars(select(Job).where(Job.type == "compute_readiness_v2"))
        ).all()
    assert len(queued) == 1


async def test_an_unchanged_tag_queues_nothing(client, tutor, tagged):
    """The other half of the one above. A recompute is an AI call at the end
    of it, so a screen that re-saves on every render would pay for one each
    time and change nothing."""
    await client.patch(
        f"/api/v1/submissions/{tagged['submission_id']}/mistakes/{tagged['mistake_id']}",
        json={"category_id": tagged["careless_id"], "severity": 1},
        headers=tutor["headers"],
    )
    async with async_session() as session:
        count = await session.scalar(
            select(func.count(Job.id)).where(Job.type == "compute_readiness_v2")
        )
    assert count == 0


async def test_a_mistake_cannot_be_moved_onto_an_archived_category(client, tutor, tagged):
    """Archived categories are hidden from new tagging and from the editor, so
    arriving at one here would put a mistake on a word the tutor has retired
    and can no longer see in any list. Rows already tagged with one keep it and
    keep counting — archiving is not deletion — so this bars arriving, never
    staying."""
    resp = await client.patch(
        f"/api/v1/submissions/{tagged['submission_id']}/mistakes/{tagged['mistake_id']}",
        json={"category_id": tagged["retired_id"], "severity": 2},
        headers=tutor["headers"],
    )
    assert resp.status_code == 404, resp.text
    async with async_session() as session:
        mistake = await session.get(Mistake, tagged["mistake_id"])
        assert mistake.category_id == tagged["careless_id"]


async def test_another_tenants_category_is_not_found(client, tutor, tagged):
    """`SEC-8`: subjects are global, so a category is only ever this
    organization's. A 404 rather than a 403 — an integer key is enumerable and
    "that one exists but is not yours" is not a thing to confirm (`API-7`,
    `SEC-9`)."""
    async with async_session() as session:
        theirs = await other_org_subject(session)
        foreign = await make_mistake_category(
            session, organization_id=theirs.organization_id, subject_id=theirs.id, name="theirs"
        )
        await session.commit()
        foreign_id = foreign.id

    resp = await client.patch(
        f"/api/v1/submissions/{tagged['submission_id']}/mistakes/{tagged['mistake_id']}",
        json={"category_id": foreign_id, "severity": 2},
        headers=tutor["headers"],
    )
    assert resp.status_code == 404, resp.text
    assert await _audits(tagged["mistake_id"]) == []


async def test_a_mistake_on_another_submission_is_not_found(client, tutor, tagged):
    """The mistake is re-read against the submission the tutor was proved to
    own, never trusted from the path. Otherwise one owned submission would be
    a key to every mistake row in the database.

    The decoy is on **this same subject and organization**, deliberately. On a
    different subject the category lookup rejects the call first and the test
    passes whether or not the submission is ever checked — which is what it
    did until the discrimination run showed it passing against the unscoped
    query too.
    """
    async with async_session() as session:
        paper = await make_past_paper(
            session,
            subject_id=tagged["subject_id"],
            organization_id=tagged["organization_id"],
        )
        other = Submission(
            work_id=paper.work_id,
            student_id=tutor["user"]["id"],
            status=SubmissionStatus.finalized,
        )
        session.add(other)
        await session.flush()
        other_id = other.id
        await session.commit()

    resp = await client.patch(
        f"/api/v1/submissions/{other_id}/mistakes/{tagged['mistake_id']}",
        json={"category_id": tagged["method_id"], "severity": 2},
        headers=tutor["headers"],
    )
    assert resp.status_code == 404, resp.text


async def test_a_student_cannot_revise_a_mistake(client, student, tagged):
    """`QA-12`'s negative case. Mistake tags are tutor-facing entirely — what
    a student is shown about their own pattern is `AV-41`'s homework tab — and
    a student who could retag their own work could rewrite the evidence behind
    their readiness."""
    resp = await client.patch(
        f"/api/v1/submissions/{tagged['submission_id']}/mistakes/{tagged['mistake_id']}",
        json={"category_id": tagged["method_id"], "severity": 2},
        headers=student["headers"],
    )
    assert resp.status_code == 403, resp.text


async def test_severity_stays_on_its_scale(client, tutor, tagged):
    """`AV-69`: 1..3 is the whole scale and tutors define categories, not
    severities. Rejected at the schema so no reader downstream has to tolerate
    a 7."""
    resp = await client.patch(
        f"/api/v1/submissions/{tagged['submission_id']}/mistakes/{tagged['mistake_id']}",
        json={"category_id": tagged["method_id"], "severity": 7},
        headers=tutor["headers"],
    )
    assert resp.status_code == 422, resp.text


async def test_the_review_screen_shows_the_tag_it_lets_you_edit(client, tutor, tagged):
    """4.2 wrote these rows and nothing displayed them. The category name is
    on the row because the screen renders the tutor's own word for it, and
    `mistakes_analysed` is there so "no mistakes found" and "nobody has
    looked" cannot render identically (`PROD-2`)."""
    resp = await client.get(
        f"/api/v1/submissions/{tagged['submission_id']}", headers=tutor["headers"]
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mistakes_analysed"] is True
    assert body["subject_id"] == tagged["subject_id"]
    (tag,) = body["marks"][0]["mistakes"]
    assert tag["id"] == tagged["mistake_id"]
    assert tag["category_name"] == "careless"
    assert tag["source"] == "ai"


async def test_a_revised_mistake_survives_the_next_tagging_run(client, tutor, tagged):
    """E17, end to end. The job replaces its own rows on every re-run; a
    revision that the next run silently overwrote would make the tutor's
    authority (`PROD-7`) last only until the next time marks changed."""
    from app.services.mistake_tagging import _delete_own_mistakes

    await client.patch(
        f"/api/v1/submissions/{tagged['submission_id']}/mistakes/{tagged['mistake_id']}",
        json={"category_id": tagged["method_id"], "severity": 3},
        headers=tutor["headers"],
    )
    async with async_session() as session:
        await _delete_own_mistakes(session, tagged["submission_id"])
        await session.commit()

    async with async_session() as session:
        mistake = await session.get(Mistake, tagged["mistake_id"])
    assert mistake is not None
    assert mistake.category_id == tagged["method_id"]


async def test_every_tag_on_a_question_reaches_the_screen(client, tutor, tagged):
    """A question can carry more than one mistake — the tagging prompt asks the
    model for every category that genuinely applies, not just the first, and
    `_mistake_points_and_analysed` counts every row it finds. A projection
    keyed one-per-question would serve the last one and drop the rest:
    evidence counting against the student that no tutor could see or revise
    (`PROD-1`, `AV-38`)."""
    async with async_session() as session:
        session.add(
            Mistake(
                student_id=tutor["user"]["id"],
                question_mark_id=tagged["mark_id"],
                category_id=tagged["method_id"],
                severity=2,
                source=MistakeSource.ai,
            )
        )
        await session.commit()

    resp = await client.get(
        f"/api/v1/submissions/{tagged['submission_id']}", headers=tutor["headers"]
    )
    assert resp.status_code == 200, resp.text
    tags = resp.json()["marks"][0]["mistakes"]
    assert [t["category_name"] for t in tags] == ["careless", "method"]


async def test_severity_can_be_revised_on_an_archived_category(client, tutor, tagged):
    """Archiving is not deletion: the category stays on every mistake already
    tagged with it and keeps counting. So the tutor must be able to change
    that mistake's severity without being forced to move it onto a different
    category — which is the only other thing the screen can offer them."""
    async with async_session() as session:
        mistake = await session.get(Mistake, tagged["mistake_id"])
        mistake.category_id = tagged["retired_id"]
        await session.commit()

    resp = await client.patch(
        f"/api/v1/submissions/{tagged['submission_id']}/mistakes/{tagged['mistake_id']}",
        json={"category_id": tagged["retired_id"], "severity": 3},
        headers=tutor["headers"],
    )
    assert resp.status_code == 200, resp.text
    async with async_session() as session:
        mistake = await session.get(Mistake, tagged["mistake_id"])
        assert mistake.severity == 3
        assert mistake.category_id == tagged["retired_id"]


async def test_the_audit_outlives_the_mistake_it_explains(client, tutor, tagged):
    """A student replacing their work hard-deletes that submission's mistakes
    (`services/attempts.open_attempt`), so an audit row that referenced one
    with a real ForeignKey would either block the resubmission or be cascaded
    away with it. Neither is acceptable: the first stops a student handing
    work in, the second destroys the record `PROD-7` requires.

    **This suite runs SQLite with foreign keys off, so it cannot fail on the
    constraint itself** — that half rests on CI's Postgres job (`RISK-3`).
    What it does pin down is the other half: nothing here deletes the audit
    row alongside the mistake.
    """
    from app.services.attempts import open_attempt
    from app.services.submission_kind import PAST_PAPER

    await client.patch(
        f"/api/v1/submissions/{tagged['submission_id']}/mistakes/{tagged['mistake_id']}",
        json={"category_id": tagged["method_id"], "severity": 3},
        headers=tutor["headers"],
    )
    assert len(await _audits(tagged["mistake_id"])) == 1

    async with async_session() as session:
        # A settled submission cannot be replaced at all, so the reachable
        # case is work the tutor has already tagged but not yet finalized —
        # which `tag_mistakes` produces deliberately, tagging the decided half
        # of an auto-finalized submission while the rest waits.
        submission = await session.get(Submission, tagged["submission_id"])
        submission.status = SubmissionStatus.needs_review
        await session.commit()

    async with async_session() as session:
        submission = await session.get(Submission, tagged["submission_id"])
        _, settled = await open_attempt(
            session, PAST_PAPER, tagged["past_paper_id"], submission.student_id
        )
        assert settled is False
        await session.commit()

    async with async_session() as session:
        assert await session.get(Mistake, tagged["mistake_id"]) is None
    assert len(await _audits(tagged["mistake_id"])) == 1


async def test_categories_are_scoped_to_the_tutor_not_to_the_work_row(client, tutor):
    """`SEC-7`: the organization comes from the authenticated user, never from
    a row the request reached.

    The mock arm of `_tutor_owns` authorizes on `parent.tutor_id` alone, with
    no organization check — so a mock whose `assessable_work` row carries a
    different organization than its own tutor is a submission this tutor may
    act on while every tenant column on the work says otherwise. Scoping the
    category lookup on `work.organization_id` resolved *that* organization's
    categories; scoping it on the tutor's own does not.

    The drift is built by hand here because nothing in the product creates it
    today. That is the point: the check has to hold without depending on a
    copy staying in step with what it was copied from.
    """
    async with async_session() as session:
        theirs = await other_org_subject(session)
        foreign_category = await make_mistake_category(
            session,
            organization_id=theirs.organization_id,
            subject_id=theirs.id,
            name="theirs",
        )
        work = await create_work(
            session,
            kind=WorkKind.mock,
            organization_id=theirs.organization_id,
            subject_id=theirs.id,
            title="Mock",
        )
        mock = Mock(
            work_id=work.id,
            organization_id=theirs.organization_id,
            # The drift: their work, this tutor's name on it.
            tutor_id=tutor["user"]["id"],
            subject_id=theirs.id,
            title="Mock",
            paper_path="mocks/paper.pdf",
            paper_name="paper.pdf",
            paper_mime="application/pdf",
        )
        session.add(mock)
        await session.flush()
        submission = Submission(
            work_id=work.id,
            student_id=tutor["user"]["id"],
            status=SubmissionStatus.finalized,
        )
        session.add(submission)
        await session.flush()
        question = MockQuestion(
            mock_id=mock.id,
            position=0,
            number="1",
            text_summary="Q1",
            max_marks=2,
            has_mark_scheme=True,
        )
        session.add(question)
        await session.flush()
        qmark = QuestionMark(
            submission_id=submission.id, mock_question_id=question.id, final_marks=0
        )
        session.add(qmark)
        await session.flush()
        mistake = Mistake(
            student_id=tutor["user"]["id"],
            question_mark_id=qmark.id,
            category_id=foreign_category.id,
            severity=1,
            source=MistakeSource.ai,
        )
        session.add(mistake)
        await session.commit()
        submission_id, mistake_id, category_id = submission.id, mistake.id, foreign_category.id

    resp = await client.patch(
        f"/api/v1/submissions/{submission_id}/mistakes/{mistake_id}",
        json={"category_id": category_id, "severity": 3},
        headers=tutor["headers"],
    )
    assert resp.status_code == 404, resp.text
    async with async_session() as session:
        assert (await session.get(Mistake, mistake_id)).severity == 1
