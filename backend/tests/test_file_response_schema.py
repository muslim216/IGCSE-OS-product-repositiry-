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

#: Decorator methods that make a function a route. `api_route` and the verbs
#: this app does not use today are included deliberately: a route registered
#: with one of them would otherwise be misread as a helper and fail the guard
#: while being perfectly correct (cubic).
HTTP_METHODS = {
    "api_route",
    "delete",
    "get",
    "head",
    "options",
    "patch",
    "post",
    "put",
    "trace",
}


def _server_names(tree: ast.Module) -> set[str]:
    """The local names in this module that refer to a serving helper.

    An `as` alias would walk straight past a name check, so the import is
    resolved rather than assumed (cubic). Attribute calls
    (`file_responses.proxied_file(...)`) are matched on the attribute instead and
    need no entry here.
    """
    names = set(SERVERS)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("file_responses"):
            names |= {alias.asname or alias.name for alias in node.names if alias.name in SERVERS}
    return names


def _calls_a_server(node: ast.AST, local_names: set[str]) -> bool:
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        if isinstance(call.func, ast.Attribute):
            if call.func.attr in SERVERS:
                return True
        elif getattr(call.func, "id", "") in local_names:
            return True
    return False


def _route_decorators(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Call]:
    """The `@router.get(...)`-shaped decorators on a function, if any."""
    return [
        d
        for d in node.decorator_list
        if isinstance(d, ast.Call)
        and isinstance(d.func, ast.Attribute)
        and d.func.attr in HTTP_METHODS
    ]


def _scan() -> tuple[list[tuple[str, str, bool]], list[str]]:
    """Route handlers that serve a stored file, and any *non-route* function that
    does.

    Parsed, not grepped. Counting occurrences in the text compares aggregates: a
    helper named in a comment inflates one side, an extra declaration on an
    unrelated route hides a missing one on a real route, and a handler calling
    the helper twice fails a module that is correct (cubic). The AST answers the
    question actually being asked — *this* route, *its* decorator — and ignores
    comments and docstrings by construction.

    Only router-decorated functions are judged as routes. A private wrapper that
    serves a file on a route's behalf has no decorator to check, so it comes back
    separately and fails loudly rather than being scored as if it were a route,
    or silently taking its callers' coverage with it (cubic).
    """
    api = pathlib.Path(__file__).resolve().parents[1] / "app" / "api"
    routes: list[tuple[str, str, bool]] = []
    wrappers: list[str] = []
    for module in sorted(api.glob("*.py")):
        if module.name == "file_responses.py":
            continue
        tree = ast.parse(module.read_text())
        local_names = _server_names(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
                continue
            if not _calls_a_server(node, local_names):
                continue
            decorators = _route_decorators(node)
            if not decorators:
                wrappers.append(f"{module.name}::{node.name}")
                continue
            declares = any(
                any(
                    kw.arg == "responses"
                    and isinstance(kw.value, ast.Name)
                    and kw.value.id == "FILE_RESPONSES"
                    for kw in decorator.keywords
                )
                for decorator in decorators
            )
            routes.append((module.name, node.name, declares))
    return routes, wrappers


def test_every_route_that_serves_a_file_declares_it_on_its_own_decorator():
    """The parametrized check above covers the routes that exist today. This is
    what catches the *next* one added without the declaration, since nothing
    else would fail."""
    handlers, _ = _scan()
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
    handlers, wrappers = _scan()
    assert not wrappers, (
        f"{wrappers} serve a stored file outside a route handler. This guard only inspects "
        f"router-decorated functions, so a wrapper hides the routes that delegate to it — "
        f"teach the guard about it rather than deleting this assertion"
    )
    assert len(handlers) == len(FILE_ROUTES), sorted(f"{m}::{f}" for m, f, _ in handlers)
