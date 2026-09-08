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
    servers = ("proxied_file", "signed_or_proxied_file")
    api = pathlib.Path(__file__).resolve().parents[1] / "app" / "api"
    serving_modules = set()
    for module in sorted(api.glob("*.py")):
        if module.name == "file_responses.py":
            continue
        source = module.read_text()
        if any(f"import {fn}" in source or f", {fn}" in source for fn in servers):
            serving_modules.add(module.name)
            assert "FILE_RESPONSES" in source, (
                f"{module.name} serves stored files but never declares them — its download "
                f"route(s) will advertise application/json for binary bytes"
            )

    # If this ever empties, the detection broke rather than the modules.
    assert serving_modules >= {
        "classifieds.py",
        "past_papers.py",
        "resources.py",
        "submissions.py",
        "teaching_guidance.py",
    }, serving_modules
