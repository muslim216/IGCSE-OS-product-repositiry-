"""Every route that serves stored bytes must say so in the schema.

FastAPI documents a JSON body for any route it cannot see returning something
else, so a download route left undeclared advertises `application/json` for PDF
and image bytes — and the generated frontend client is entitled to try decoding
that (CodeRabbit, PR #61). This is the check that stops the next one being added
that way, since nothing else would fail.
"""

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


def test_a_module_that_serves_files_also_declares_them():
    """The list above only guards while it is complete, and a new download route
    would not be on it.

    Checked at the source level rather than by walking `app.routes`: the routers
    live under a mounted sub-application, so the top-level route list does not
    contain them and a walk that finds nothing would pass silently — which is
    how the first version of this test failed open.
    """
    api = pathlib.Path(__file__).resolve().parents[1] / "app" / "api"
    serving_modules = set()
    for module in sorted(api.glob("*.py")):
        if module.name == "file_responses.py":
            continue
        source = module.read_text()
        # Detected by the **call**, not the import: an alias, a parenthesised
        # multiline import or attribute access (`file_responses.proxied_file(`)
        # all evade a check on the import's shape, and a module that evades
        # detection passes by not being looked at (cubic).
        if "proxied_file(" not in source:
            continue
        serving_modules.add(module.name)
        # Count the declarations against the *call sites*, not merely that the
        # name appears: importing `FILE_RESPONSES` and forgetting it on one of
        # two decorators is exactly the regression this guards, and a presence
        # check passes straight through it (CodeRabbit).
        #
        # `proxied_file(` matches both helpers — `signed_or_proxied_file(`
        # contains it — and never the import line, which has no parenthesis.
        calls = source.count("proxied_file(")
        declared = source.count("responses=FILE_RESPONSES")
        assert declared >= calls, (
            f"{module.name} serves a stored file from {calls} route(s) but declares "
            f"{declared} of them — the rest advertise application/json for binary bytes"
        )

    # If this ever empties, the detection broke rather than the modules.
    assert serving_modules >= {
        "classifieds.py",
        "past_papers.py",
        "resources.py",
        "submissions.py",
        "teaching_guidance.py",
    }, serving_modules
