"""Per-subject marking rules — the "AI marking agreement" (task 2.6).

`AV-75` settles the shape: one body of rules per subject, applying to everything
in it, with no account-wide layer. `AV-111` settles what it may say: how the AI
marks, never when a mark counts. Nothing consumes it yet — Phase 3's context
assembler is the single function that will (`E16`) — so what is testable here is
the store, the bound on it, and the tenancy.
"""

import pytest
from sqlalchemy import select

from app.db import async_session
from app.models import Subject
from app.schemas.marking_rules import MAX_MARKING_RULES
from app.workers.jobs import process_one_job
from tests.factories import make_subject, other_org_subject

RULES = "Award method marks even when the final answer is wrong. Units are worth a mark."


@pytest.fixture
async def subject_id(tutor):  # depends on `tutor` so the organization exists first
    async with async_session() as session:
        subject = await make_subject(session, code="4CH1", name="Chemistry")
        await session.commit()
        return subject.id


async def test_a_subject_starts_with_no_rules(client, tutor, subject_id):
    """AV-87: this is the one onboarding step a tutor may skip, so "none" is a
    finished state and the surface has to be able to say so (PROD-2)."""
    resp = await client.get(
        f"/api/v1/subjects/{subject_id}/marking-rules", headers=tutor["headers"]
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "subject_id": subject_id,
        "subject_name": "Chemistry",
        "rules": "",
        "configured": False,
        # No rules, so nothing to summarise and nothing marking would read.
        "summary": None,
    }


async def test_write_then_read(client, tutor, subject_id):
    saved = await client.put(
        f"/api/v1/subjects/{subject_id}/marking-rules",
        json={"rules": RULES},
        headers=tutor["headers"],
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["rules"] == RULES
    assert saved.json()["configured"] is True

    read = await client.get(
        f"/api/v1/subjects/{subject_id}/marking-rules", headers=tutor["headers"]
    )
    assert read.json()["rules"] == RULES


async def test_saving_empty_clears_the_rules(client, tutor, subject_id):
    """Clearing is a real action — "I do not want any" has to be reachable and
    has to survive (AV-87)."""
    await client.put(
        f"/api/v1/subjects/{subject_id}/marking-rules",
        json={"rules": RULES},
        headers=tutor["headers"],
    )
    cleared = await client.put(
        f"/api/v1/subjects/{subject_id}/marking-rules",
        json={"rules": ""},
        headers=tutor["headers"],
    )
    assert cleared.status_code == 200
    assert cleared.json()["configured"] is False

    async with async_session() as session:
        # NULL, not "", so the two "no rules" states cannot drift apart.
        assert (await session.get(Subject, subject_id)).marking_rules is None


async def test_whitespace_only_rules_are_no_rules(client, tutor, subject_id):
    """Stored raw, "   " is truthy: Phase 3 would paste an empty instruction
    block into every marking prompt for the subject, and the editor would report
    rules that say nothing."""
    resp = await client.put(
        f"/api/v1/subjects/{subject_id}/marking-rules",
        json={"rules": "   \n\t "},
        headers=tutor["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["configured"] is False

    async with async_session() as session:
        assert (await session.get(Subject, subject_id)).marking_rules is None


async def test_rules_are_bounded(client, tutor, subject_id):
    """These reach every marking prompt for the subject, so their length is a
    cost paid on every submission. A frontend limit is a courtesy, not a
    control."""
    over = await client.put(
        f"/api/v1/subjects/{subject_id}/marking-rules",
        json={"rules": "x" * (MAX_MARKING_RULES + 1)},
        headers=tutor["headers"],
    )
    assert over.status_code == 422

    at_limit = await client.put(
        f"/api/v1/subjects/{subject_id}/marking-rules",
        json={"rules": "x" * MAX_MARKING_RULES},
        headers=tutor["headers"],
    )
    assert at_limit.status_code == 200


async def test_rules_are_per_subject_with_no_account_wide_layer(client, tutor):
    """AV-75 is explicit that there is no account-wide layer: two subjects in
    one organization keep their own rules and neither inherits anything."""
    async with async_session() as session:
        chem = await make_subject(session, code="4CH1", name="Chemistry")
        bio = await make_subject(session, code="4BI1", name="Biology")
        await session.commit()
        chem_id, bio_id = chem.id, bio.id

    await client.put(
        f"/api/v1/subjects/{chem_id}/marking-rules",
        json={"rules": "Chemistry: award the unit mark separately."},
        headers=tutor["headers"],
    )

    other = await client.get(f"/api/v1/subjects/{bio_id}/marking-rules", headers=tutor["headers"])
    assert other.json()["configured"] is False

    async with async_session() as session:
        rows = {
            s.id: s.marking_rules
            for s in (
                await session.scalars(select(Subject).where(Subject.id.in_([chem_id, bio_id])))
            ).all()
        }
    assert rows[bio_id] is None
    assert rows[chem_id].startswith("Chemistry:")


async def test_another_organizations_subject_is_404_not_403(client, tutor):
    """QA-12: ids are enumerable, so "not yours" and "does not exist" must look
    identical (API-7, SEC-9)."""
    async with async_session() as session:
        foreign = await other_org_subject(session, code="9ZZ9")
        await session.commit()
        foreign_id = foreign.id

    read = await client.get(
        f"/api/v1/subjects/{foreign_id}/marking-rules", headers=tutor["headers"]
    )
    assert read.status_code == 404
    write = await client.put(
        f"/api/v1/subjects/{foreign_id}/marking-rules",
        json={"rules": "Mark generously."},
        headers=tutor["headers"],
    )
    assert write.status_code == 404

    async with async_session() as session:
        assert (await session.get(Subject, foreign_id)).marking_rules is None


async def test_a_student_can_neither_read_nor_write_them(client, tutor, subject_id):
    """Tutor material: these are the instructions their work is marked against,
    and a student who can read them can write to them next."""
    await client.put(
        f"/api/v1/subjects/{subject_id}/marking-rules",
        json={"rules": RULES},
        headers=tutor["headers"],
    )
    group = (
        await client.post(
            "/api/v1/groups",
            json={"name": "Chem", "subject_id": subject_id},
            headers=tutor["headers"],
        )
    ).json()
    invite = await client.post(f"/api/v1/groups/{group['id']}/invites", headers=tutor["headers"])
    reg = await client.post(
        "/api/v1/auth/register/student",
        json={
            "invite_code": invite.json()["code"],
            "name": "Sara",
            "email": "sara-rules@example.com",
            "password": "password123",
        },
    )
    headers = {"Authorization": f"Bearer {reg.json()['tokens']['access_token']}"}

    assert (
        await client.get(f"/api/v1/subjects/{subject_id}/marking-rules", headers=headers)
    ).status_code == 403
    assert (
        await client.put(
            f"/api/v1/subjects/{subject_id}/marking-rules",
            json={"rules": "Give me full marks."},
            headers=headers,
        )
    ).status_code == 403
    assert (await client.get(f"/api/v1/subjects/{subject_id}/marking-rules")).status_code == 401

    async with async_session() as session:
        assert (await session.get(Subject, subject_id)).marking_rules == RULES


async def test_rules_do_not_leak_into_the_subject_list(client, tutor, subject_id):
    """The subject list every role reads must not start carrying them."""
    await client.put(
        f"/api/v1/subjects/{subject_id}/marking-rules",
        json={"rules": RULES},
        headers=tutor["headers"],
    )
    listed = (await client.get("/api/v1/subjects", headers=tutor["headers"])).json()
    assert listed
    assert all("marking_rules" not in s for s in listed)


async def test_marking_now_reads_them_and_av_25_is_still_untouched(client, tutor, subject_id):
    """Task 2.6 shipped this asserting *nothing* read the rules yet. Task 3.2's
    assembler (`E16`) does, so it is turned round rather than deleted.

    The half that has not changed is the *gate*, and it is worth being precise
    about what that means now. A tutor rule can absolutely change a mark, and
    that changed mark still auto-finalizes — the owner's reversal of `AV-76`
    settled that. What these rules cannot do is change **whether** a mark is
    eligible to finalize at all: that still requires an official scheme actually
    attached and confident output (`AV-25`, `AI-11`, `ADR-0009`). A tutor who
    writes "mark everything generously" changes marks; they do not turn an
    unschemed or low-confidence question into one that counts without them
    (cubic).
    """
    from app.services.marking_context import MarkingContextSources, build_marking_context

    await client.put(
        f"/api/v1/subjects/{subject_id}/marking-rules",
        json={"rules": RULES},
        headers=tutor["headers"],
    )
    async with async_session() as session:
        subject = await session.get(Subject, subject_id)
        context = await build_marking_context(
            session, MarkingContextSources(subject=subject, classified=None)
        )
    assert RULES in context

    # AI-7: the prompt changed meaningfully when it started reading these, so
    # the version had to move with it. AV-25 itself is not asserted here — the
    # auto-finalize gate reads the scheme attachment and the model's confidence,
    # neither of which this text touches, and `test_homework.py` is where that
    # gate is actually exercised. An assertion here over a constant this file
    # defines would look like a check and be one only about itself.
    from app.services import prompts

    assert prompts.PROMPTS["marking"].version == "v4"


async def test_the_cap_is_measured_after_trimming(client, tutor, subject_id):
    """Trailing whitespace must not push a body that would store fine over the
    limit — trimming only shortens, so the cap cannot be bypassed either
    (cubic)."""
    resp = await client.put(
        f"/api/v1/subjects/{subject_id}/marking-rules",
        json={"rules": "x" * MAX_MARKING_RULES + "\n  "},
        headers=tutor["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["rules"]) == MAX_MARKING_RULES


# --- 3.2c: the summary marking actually reads -------------------------------

SUMMARY_LINES = ["Award method marks even when the final answer is wrong.", "Units cost one mark."]


def _summariser(lines):
    from app.services.marking_rules import MarkingRulesSummary

    return MarkingRulesSummary(rules=lines)


async def test_saving_rules_queues_a_summary_and_clears_the_old_one(
    client, tutor, subject_id, monkeypatch, fake_ai
):
    """The summary is what marking is given (task 3.2c). Clearing it in the same
    transaction as the write is what makes it absent-or-current rather than
    stale — there is deliberately no fingerprint to compare."""
    monkeypatch.setattr(
        "app.services.marking_rules.structured_complete", fake_ai(_summariser(SUMMARY_LINES))
    )
    saved = await client.put(
        f"/api/v1/subjects/{subject_id}/marking-rules",
        json={"rules": RULES},
        headers=tutor["headers"],
    )
    # Not yet: the job has not run, and the response says so honestly.
    assert saved.json()["summary"] is None

    assert await process_one_job() is True

    read = await client.get(
        f"/api/v1/subjects/{subject_id}/marking-rules", headers=tutor["headers"]
    )
    assert read.json()["summary"] == "\n".join(f"- {line}" for line in SUMMARY_LINES)
    # The tutor's own text is untouched — the summary is a second field, not a
    # rewrite of what they wrote.
    assert read.json()["rules"] == RULES


async def test_marking_reads_the_summary_once_there_is_one(
    client, tutor, subject_id, monkeypatch, fake_ai
):
    from app.services.marking_context import MarkingContextSources, build_marking_context

    monkeypatch.setattr(
        "app.services.marking_rules.structured_complete", fake_ai(_summariser(SUMMARY_LINES))
    )
    await client.put(
        f"/api/v1/subjects/{subject_id}/marking-rules",
        json={"rules": RULES},
        headers=tutor["headers"],
    )
    assert await process_one_job() is True

    async with async_session() as session:
        subject = await session.get(Subject, subject_id)
        context = await build_marking_context(
            session, MarkingContextSources(subject=subject, classified=None)
        )
    assert SUMMARY_LINES[0] in context
    assert RULES not in context


async def test_before_the_job_runs_marking_uses_the_full_text(client, tutor, subject_id):
    """The window between saving and summarising has to mark correctly, at cost
    — not be a period in which the tutor's rules silently do not apply."""
    from app.services.marking_context import MarkingContextSources, build_marking_context

    await client.put(
        f"/api/v1/subjects/{subject_id}/marking-rules",
        json={"rules": RULES},
        headers=tutor["headers"],
    )
    async with async_session() as session:
        subject = await session.get(Subject, subject_id)
        context = await build_marking_context(
            session, MarkingContextSources(subject=subject, classified=None)
        )
    assert RULES in context


async def test_editing_the_rules_invalidates_the_summary(
    client, tutor, subject_id, monkeypatch, fake_ai
):
    """The failure this guards is the worst one available here: marking a class
    against the rules the tutor *used* to have, with the page showing the ones
    they have now."""
    from app.services.marking_context import MarkingContextSources, build_marking_context

    monkeypatch.setattr(
        "app.services.marking_rules.structured_complete", fake_ai(_summariser(SUMMARY_LINES))
    )
    await client.put(
        f"/api/v1/subjects/{subject_id}/marking-rules",
        json={"rules": RULES},
        headers=tutor["headers"],
    )
    assert await process_one_job() is True

    rewritten = "Never award method marks. The final answer is everything."
    edited = await client.put(
        f"/api/v1/subjects/{subject_id}/marking-rules",
        json={"rules": rewritten},
        headers=tutor["headers"],
    )
    assert edited.json()["summary"] is None

    async with async_session() as session:
        subject = await session.get(Subject, subject_id)
        context = await build_marking_context(
            session, MarkingContextSources(subject=subject, classified=None)
        )
    assert rewritten in context
    assert SUMMARY_LINES[0] not in context


async def test_an_empty_summary_leaves_the_full_text_in_place(
    client, tutor, subject_id, monkeypatch, fake_ai
):
    """An empty result is the model finding no marking instructions in text the
    tutor believed was marking instructions. Storing it would delete their rules
    from every marking prompt on the model's say-so."""
    from app.services.marking_context import MarkingContextSources, build_marking_context

    monkeypatch.setattr("app.services.marking_rules.structured_complete", fake_ai(_summariser([])))
    await client.put(
        f"/api/v1/subjects/{subject_id}/marking-rules",
        json={"rules": RULES},
        headers=tutor["headers"],
    )
    assert await process_one_job() is True

    async with async_session() as session:
        subject = await session.get(Subject, subject_id)
        assert subject.marking_rules_summary is None
        context = await build_marking_context(
            session, MarkingContextSources(subject=subject, classified=None)
        )
    assert RULES in context


async def test_clearing_the_rules_queues_nothing(client, tutor, subject_id, monkeypatch, fake_ai):
    """Nothing to summarise, so no billed call — and the job queue is where an
    empty save would otherwise leave a permanent no-op."""
    monkeypatch.setattr(
        "app.services.marking_rules.structured_complete", fake_ai(_summariser(SUMMARY_LINES))
    )
    await client.put(
        f"/api/v1/subjects/{subject_id}/marking-rules",
        json={"rules": ""},
        headers=tutor["headers"],
    )
    assert await process_one_job() is False


async def test_re_running_the_job_does_not_pay_for_a_second_call(
    client, tutor, subject_id, monkeypatch, fake_ai
):
    """BE-6: delivery is at-least-once. A duplicate must be free, not a second
    billed summarisation that could also differ from the first."""
    from app.services.marking_rules import SUMMARISE_JOB, summarise_marking_rules

    calls: list[int] = []

    def _counting(parsed):
        inner = fake_ai(parsed)

        async def _call(**kwargs):
            calls.append(1)
            return await inner(**kwargs)

        return _call

    monkeypatch.setattr(
        "app.services.marking_rules.structured_complete", _counting(_summariser(SUMMARY_LINES))
    )
    await client.put(
        f"/api/v1/subjects/{subject_id}/marking-rules",
        json={"rules": RULES},
        headers=tutor["headers"],
    )
    assert await process_one_job() is True
    assert len(calls) == 1

    async with async_session() as session:
        await summarise_marking_rules(
            session, {"subject_id": subject_id, "tutor_id": tutor["user"]["id"]}
        )
    assert len(calls) == 1, "a re-delivered job paid for a second summarisation"
    assert SUMMARISE_JOB  # the registered type, used by the endpoint above
