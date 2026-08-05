"""RISK-7: the role check used to be eleven hand-copied functions.

Ten byte-identical `_require_tutor` definitions plus one `_require_student`,
called imperatively at the top of 35 handler bodies. Eleven copies of an
authorization check are eleven places to forget one, and a router that omitted
the call had no role check at all — no test, no linter and no type error would
have said so.

The convergence onto a single dependency is only half the fix. The other half is
here: these tests fail if a route loses its gate, so the twelfth copy can never
be quietly forgotten the way the eleventh could.

QA-12 requires a change touching auth to ship with negative cases, so the live
checks below assert the wrong role is refused rather than that the right one is
allowed.
"""

import pathlib
import re

import pytest
from fastapi.routing import APIRoute

from app.api.deps import get_current_user, require_student, require_tutor
from app.main import app
from tests.test_homework import (  # noqa: F401 - shared fixtures
    group,
    student,
    subject,
)

#: Everything reachable without a token. Registration and login cannot require
#: one, refresh carries its own httpOnly cookie instead, the invite lookup is
#: what a new student opens before they have an account, and the health
#: endpoints are polled by the platform. Adding to this list is a deliberate
#: decision to expose an endpoint to the internet — that is the point of making
#: it a literal the test compares against.
PUBLIC_ROUTES = {
    ("GET", "/api/v1/health"),
    ("GET", "/api/v1/health/ready"),
    ("GET", "/auth/invites/{code}"),
    ("POST", "/auth/login"),
    ("POST", "/auth/refresh"),
    ("POST", "/auth/register/parent"),
    ("POST", "/auth/register/student"),
    ("POST", "/auth/register/tutor"),
}


def _iter_api_routes(obj, seen=None):
    """Every APIRoute reachable from the app.

    Included routers are kept nested rather than flattened into app.routes, so
    this has to walk through the wrapper to reach the router that owns them.
    """
    seen = seen if seen is not None else set()
    for route in getattr(obj, "routes", []):
        if isinstance(route, APIRoute):
            if id(route) not in seen:
                seen.add(id(route))
                yield route
        elif hasattr(route, "original_router"):
            yield from _iter_api_routes(route.original_router, seen)
        elif hasattr(route, "routes"):
            yield from _iter_api_routes(route, seen)


def _dependency_calls(route) -> set:
    """Every dependency callable in a route's resolved tree, at any depth."""
    found = set()

    def walk(dependant):
        for sub in dependant.dependencies:
            found.add(sub.call)
            walk(sub)

    walk(route.dependant)
    return found


def _routes():
    return list(_iter_api_routes(app))


# --- The inventory ---------------------------------------------------------


def test_no_route_is_public_by_accident():
    """The failure this guards against is a whole endpoint reaching production
    with no authentication, which is what an imperative check makes possible."""
    public = {
        (sorted(r.methods - {"HEAD"})[0], r.path)
        for r in _routes()
        if get_current_user not in _dependency_calls(r)
    }
    assert public == PUBLIC_ROUTES, (
        "the set of routes reachable without a token changed; if that is "
        "intended, add it to PUBLIC_ROUTES deliberately"
    )


def test_the_api_still_has_the_routes_this_file_thinks_it_does():
    """A guard that silently stops finding routes stops guarding anything."""
    routes = _routes()
    assert len(routes) > 100, f"only found {len(routes)} routes — the walk is broken"


def test_role_gates_are_one_shared_dependency():
    """Identity, not shape. Two functions that both happen to check the role are
    exactly the situation this replaced."""
    gated = [r for r in _routes() if {require_tutor, require_student} & _dependency_calls(r)]
    assert len(gated) > 40, f"only {len(gated)} routes carry a role gate"


#: Resolved from this file, not the working directory. `Path("app/api")` only
#: works when pytest is invoked from `backend/`; run from the repository root it
#: matches nothing, and a scan over zero files reports zero offenders and passes.
#: A guard that can silently check nothing is worse than no guard, because it
#: reads as evidence.
API_DIR = pathlib.Path(__file__).resolve().parents[1] / "app" / "api"


def test_no_router_has_grown_its_own_copy_of_the_gate():
    """The private helpers are gone; this fails if one comes back."""
    sources = sorted(API_DIR.rglob("*.py"))
    assert sources, f"no modules found under {API_DIR} — the scan checked nothing"

    offenders = []
    for path in sources:
        source = path.read_text()
        # `\s*` and the optional `async` because a copy that comes back indented
        # inside a class, or written `async def`, is the same copy.
        if re.search(r"^\s*(async\s+)?def\s+_require_(tutor|student)\b", source, re.M):
            offenders.append(path.name)
    assert not offenders, (
        f"{offenders} defines a private role check again — use TutorUser / "
        "StudentUser from app.api.deps so the gate is in the signature"
    )


# --- Live negative cases ---------------------------------------------------

TUTOR_ONLY = [
    "/api/v1/ai-usage/summary",
    "/api/v1/assessments",
    "/api/v1/assignments/attention",
    "/api/v1/classifieds",
    "/api/v1/classroom/status",
    "/api/v1/groups",
    "/api/v1/knowledge",
    "/api/v1/me/today-lessons",
    "/api/v1/me/preferences",
    "/api/v1/readiness/weights",
    "/api/v1/submissions/review-queue",
    "/api/v1/syllabus-uploads",
]

STUDENT_ONLY = [
    "/api/v1/chat/conversations",
    "/api/v1/me/assessments",
    "/api/v1/me/assignments",
    "/api/v1/readiness/me",
]


@pytest.mark.parametrize("path", TUTOR_ONLY)
async def test_a_student_cannot_reach_a_tutor_endpoint(client, student, path):  # noqa: F811
    resp = await client.get(path, headers=student["headers"])
    assert resp.status_code == 403, f"{path} let a student in"
    assert resp.json()["detail"] == "Tutor account required"


@pytest.mark.parametrize("path", STUDENT_ONLY)
async def test_a_tutor_cannot_reach_a_student_endpoint(client, tutor, path):
    resp = await client.get(path, headers=tutor["headers"])
    assert resp.status_code == 403, f"{path} let a tutor in"
    assert resp.json()["detail"] == "Student account required"


@pytest.mark.parametrize("path", TUTOR_ONLY + STUDENT_ONLY)
async def test_no_token_is_refused_before_any_role_check(client, path):
    """401 and not 403: without a token there is no role to reject."""
    resp = await client.get(path)
    assert resp.status_code == 401


async def test_the_reports_endpoint_keeps_its_own_message(client, student):  # noqa: F811
    """One endpoint had a bespoke 403 message. Converging the mechanism must not
    quietly restyle what a user reads."""
    resp = await client.post(
        "/api/v1/reports/generate",
        json={"student_id": student["user"]["id"], "audience": "student"},
        headers=student["headers"],
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Only tutors can generate reports"


async def test_a_gate_carried_by_an_ownership_helper_still_refuses(client, student, group):  # noqa: F811
    """BE-18, proved rather than assumed.

    Nine groups.py handlers declare no role gate of their own and rely entirely
    on _owned_group()'s assert_tutor(). The parametrized cases above cannot
    reach them — they need a real group id — so the pattern that carries the
    check one layer down was the one part of the convergence with no test
    behind it. A reviewer reading class_brief() in isolation sees `CurrentUser`
    and reasonably concludes it is ungated; this is the answer to that.
    """
    resp = await client.post(f"/api/v1/groups/{group['id']}/brief", headers=student["headers"])
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Tutor account required"


async def test_the_analytics_a_helper_gated_handler_calls_is_gated_too(client, student, group):  # noqa: F811
    """class_brief() calls group_analytics() directly rather than over HTTP, so
    the callee needs its own gate — a route dependency does not protect a plain
    function call."""
    resp = await client.get(f"/api/v1/analytics/groups/{group['id']}", headers=student["headers"])
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Tutor account required"
