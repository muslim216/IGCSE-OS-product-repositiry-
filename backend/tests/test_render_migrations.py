"""Migrations run in Render's pre-deploy step, with the start command as backstop (T-052).

The API has a persistent disk, so Render stops the old instance before the new
one starts. A migration that fails in the start command therefore leaves the API
down. In `preDeployCommand` it runs on a separate instance before the swap, and a
failure cancels the deploy while the old version keeps serving. The start-command
run stays: it is a no-op after a good pre-deploy and heals a missing one.

Parsed with plain text matching, as in test_render_routing.py: PyYAML is not
installed and both shapes are a single line.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RENDER_YAML = ROOT / "render.yaml"
DOCKERFILE = ROOT / "backend" / "Dockerfile"


def _api_service_block() -> str:
    text = RENDER_YAML.read_text()
    start = text.index("name: igcse-os-api")
    nxt = re.search(r"^\s*-\s*type:", text[start:], re.MULTILINE)
    return text[start : start + nxt.start()] if nxt else text[start:]


def test_api_service_migrates_in_pre_deploy():
    assert re.search(
        r"^\s*preDeployCommand:\s*alembic upgrade head\s*$", _api_service_block(), re.MULTILINE
    ), "render.yaml's igcse-os-api must run `alembic upgrade head` as its preDeployCommand"


def test_dockerfile_still_migrates_before_uvicorn():
    cmd = next(line for line in DOCKERFILE.read_text().splitlines() if line.startswith("CMD "))
    assert "alembic upgrade head" in cmd, cmd
    assert "uvicorn" in cmd, cmd
    assert cmd.index("alembic upgrade head") < cmd.index("uvicorn"), cmd
