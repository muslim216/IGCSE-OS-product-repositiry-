"""render.yaml's AI routing must agree with config.py's defaults (`AV-124`).

`render.yaml` restates the per-surface providers so a surface can be moved from
the Render dashboard without a code change — and **those values win over
config.py in production**. That is the point of them, and it is also how a
routing change becomes a no-op: task 3.2 flipped marking and extraction to
Anthropic in `config.py`, and had these two lines been left saying `gemini`, the
retirement would have been complete everywhere except the only place it mattered,
with every test green.

This file exists so the two cannot drift apart silently. It is deliberately not
a test that the values are `anthropic` — that would have to be edited by anyone
legitimately moving a surface, which is exactly the edit that should not need a
test change. It asserts only that the two files say the same thing.

Parsed with a regex rather than PyYAML: the dependency is not installed, and the
shape here is a flat `- key: X` / `value: Y` list, so a parser would be more
machinery than the file warrants.
"""

import re
from pathlib import Path

from app.config import Settings
from app.services.ai import SURFACES

RENDER_YAML = Path(__file__).resolve().parents[2] / "render.yaml"

#: `- key: AI_<SURFACE>_PROVIDER` followed by `value: <provider>`. Entries with
#: `sync: false` carry no value and never match, which is correct — a
#: dashboard-supplied secret is not something this file can check.
_ENTRY = re.compile(
    r"^\s*-\s*key:\s*AI_(?P<surface>[A-Z_]+)_PROVIDER\s*\n\s*value:\s*(?P<provider>\S+)\s*$",
    re.MULTILINE,
)


def _render_providers() -> dict[str, str]:
    return {
        m.group("surface").lower(): m.group("provider")
        for m in _ENTRY.finditer(RENDER_YAML.read_text())
    }


def test_render_yaml_pins_at_least_one_surface():
    """A regex that silently matches nothing would make every assertion below
    vacuous — the failure mode this whole file exists to prevent, one level up.
    """
    assert _render_providers(), (
        f"no AI_*_PROVIDER entries parsed out of {RENDER_YAML}; the file's shape "
        "changed and the regex above no longer matches it"
    )


def test_every_provider_render_pins_is_a_real_surface():
    """A pin naming a surface that does not exist sets an environment variable
    `resolve_surface` never reads, so it looks like routing and is not."""
    unknown = set(_render_providers()) - set(SURFACES)
    assert not unknown, (
        f"render.yaml pins AI_*_PROVIDER for {sorted(unknown)}, which are not "
        f"registered surfaces {sorted(SURFACES)}"
    )


def _config_default(surface: str) -> str:
    """config.py's *declared* default for a surface's provider.

    Read off the field rather than through `get_settings()`, which layers `.env`
    and the process environment on top. This test is about whether two files in
    the repository agree; a developer with `AI_MARKING_PROVIDER` exported in
    their shell would otherwise fail it — or, worse, pass it — for a reason that
    has nothing to do with either file (cubic).
    """
    return Settings.model_fields[f"ai_{surface}_provider"].default


def test_every_surface_defaults_to_anthropic_in_config_py():
    """The hermetic half of AV-124's retirement.

    `test_no_surface_routes_to_gemini_any_more` asserts the same thing through
    `resolve_surface`, which is the behaviour that matters — but it reads live
    settings, so it proves nothing about the committed defaults on a machine
    with overrides set. This one cannot be influenced by an environment at all,
    and it covers all seven surfaces rather than only the three render.yaml
    happens to restate (cubic).
    """
    on_gemini = [s for s in SURFACES if _config_default(s) != "anthropic"]
    assert not on_gemini, f"{on_gemini} still default to a non-Anthropic provider in config.py"


def test_render_yaml_and_config_py_agree_on_every_pinned_surface():
    disagree = {
        surface: (pinned, _config_default(surface))
        for surface, pinned in _render_providers().items()
        if pinned != _config_default(surface)
    }
    assert not disagree, (
        f"render.yaml and config.py disagree about {sorted(disagree)} "
        f"(render, config): {disagree}. render.yaml wins in production, so this "
        "is a routing change that has not actually shipped."
    )
