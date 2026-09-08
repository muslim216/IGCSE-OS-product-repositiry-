"""Every route that serves stored bytes must say so in the schema.

FastAPI documents a JSON body for any route it cannot see returning something
else, so a download route left undeclared advertises `application/json` for PDF
and image bytes — and the generated frontend client is entitled to try decoding
that (CodeRabbit, PR #61). This is the check that stops the next one being added
that way, since nothing else would fail.
"""

import ast
import pathlib

import pytest

from app.main import app

#: Every route serving a stored file. Adding one here without declaring
#: `response_class=Response, responses=FILE_RESPONSES` on it fails this test.
FILE_ROUTES = [
    "/api/v1/classifieds/{classified_id}/file",
    "/api/v1/classifieds/{classified_id}/mark-scheme",
    "/api/v1/past-papers/{past_paper_id}/booklet",
    "/api/v1/past-papers/{past_paper_id}/mark-scheme",
    "/api/v1/resources/{resource_id}/file",
    "/api/v1/subjects/{subject_id}/teaching-guidance/file",
    "/api/v1/submissions/{submission_id}/files/{file_id}",
]


@pytest.fixture(scope="module")
def spec():
    return app.openapi()


@pytest.mark.parametrize("path", FILE_ROUTES)
def test_a_file_route_declares_binary_and_not_json(spec, path):
    content = spec["paths"][path]["get"]["responses"]["200"]["content"]
    assert "application/json" not in content, path
    assert "application/pdf" in content
    assert content["application/pdf"]["schema"] == {"type": "string", "format": "binary"}


#: The two helpers in `api/file_responses.py` that write a file to the response.
SERVERS = {"proxied_file", "signed_or_proxied_file"}


def _serving_handlers() -> list[tuple[str, str, bool]]:
    """Every handler that serves a stored file, and whether its own decorator
    declares `responses=FILE_RESPONSES`.

    Parsed, not grepped. Counting occurrences in the text compares aggregates:
    a helper named in a comment inflates one side, an extra declaration on an
    unrelated route hides a missing one on a real route, and a handler that
    calls the helper twice fails a module that is correct (cubic). The AST
    answers the question actually being asked — *this* route, *its* decorator —
    and ignores comments and docstrings by construction.

    An attribute call (`file_responses.proxied_file(...)`) is matched on the
    attribute name, so the guard does not depend on how the module imports it.
    """
    api = pathlib.Path(__file__).resolve().parents[1] / "app" / "api"
    found: list[tuple[str, str, bool]] = []
    for module in sorted(api.glob("*.py")):
        if module.name == "file_responses.py":
            continue
        tree = ast.parse(module.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
                continue
            called = {
                call.func.attr
                if isinstance(call.func, ast.Attribute)
                else getattr(call.func, "id", "")
                for call in ast.walk(node)
                if isinstance(call, ast.Call)
            }
            if not called & SERVERS:
                continue
            declares = any(
                any(
                    kw.arg == "responses"
                    and isinstance(kw.value, ast.Name)
                    and kw.value.id == "FILE_RESPONSES"
                    for kw in decorator.keywords
                )
                for decorator in node.decorator_list
                if isinstance(decorator, ast.Call)
            )
            found.append((module.name, node.name, declares))
    return found


def test_every_route_that_serves_a_file_declares_it_on_its_own_decorator():
    """The parametrized check above covers the routes that exist today. This is
    what catches the *next* one added without the declaration, since nothing
    else would fail."""
    handlers = _serving_handlers()
    undeclared = [f"{mod}::{fn}" for mod, fn, declares in handlers if not declares]
    assert not undeclared, (
        f"{undeclared} serve a stored file but do not carry `responses=FILE_RESPONSES`, "
        f"so they advertise application/json for binary bytes"
    )


def test_the_detection_itself_still_works():
    """A guard that finds nothing passes silently, which is how the first
    version of this test failed open: it walked `app.routes`, which does not
    contain the mounted sub-application's routes.

    One handler per path in `FILE_ROUTES`, so the two halves of this file cannot
    drift apart without one of them failing.
    """
    handlers = _serving_handlers()
    assert len(handlers) == len(FILE_ROUTES), sorted(f"{m}::{f}" for m, f, _ in handlers)
