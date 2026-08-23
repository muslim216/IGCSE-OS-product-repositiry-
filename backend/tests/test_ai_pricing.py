"""Guard the AI price table against drift.

AI_MODEL_PRICING is JSON keyed by model id. A model id that appears in
config but not in the price table silently records cost_usd = NULL
(AI-17); a price-table key that no longer matches any config model
silently pays for nothing. Both are deploy-time mistakes — this file
fails the suite when they happen.
"""

import json
import pathlib
import re

from app.config import get_settings
from app.services.ai import estimate_cost_usd, model_pricing


def _known_model_ids() -> set[str]:
    s = get_settings()
    ids: set[str] = set()
    for attr in (
        "anthropic_model",
        "gemini_model",
        "ai_marking_model",
        "ai_extraction_model",
        "ai_syllabus_model",
        "ai_chat_model",
        "ai_reports_model",
        "ai_readiness_model",
        "ai_class_brief_model",
        "ai_narrative_model",
    ):
        v = getattr(s, attr, "")
        if v:
            ids.add(v)
    return ids


def test_env_example_pricing_keys_match_known_models():
    """The JSON in .env.example must be keyed to real model IDs, not stale ones."""
    env_example = pathlib.Path(__file__).parent.parent / ".env.example"
    text = env_example.read_text()
    # Find the AI_MODEL_PRICING= line (allow JSON on same line).
    m = re.search(r"^AI_MODEL_PRICING=(.*)$", text, re.MULTILINE)
    assert m, "AI_MODEL_PRICING not found in .env.example"
    raw = m.group(1).strip().strip("'").strip('"')
    # .env.example stores the JSON bare (no surrounding quotes) — strip once more
    # if the line used quoted JSON for YAML compat.
    if raw.startswith("'") and raw.endswith("'"):
        raw = raw[1:-1]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:  # pragma: no cover
        raise AssertionError(f"AI_MODEL_PRICING in .env.example is not valid JSON: {exc}") from exc
    assert isinstance(data, dict), "AI_MODEL_PRICING must be a JSON object"
    # Empty is allowed in dev, but the example file should be populated so a new
    # deploy has a price for every default model.
    assert data, ".env.example AI_MODEL_PRICING should not be empty — copy it to render.yaml too"
    known = _known_model_ids()
    for key in data:
        assert key in known, (
            f"AI_MODEL_PRICING key {key!r} in .env.example does not match any model id in config.py "
            f"(known: {sorted(known)}). Update the key or the model id — a mismatched key prices nothing."
        )
    for mid in known:
        # Default-surface models (chat etc.) are intentionally left blank when they use the
        # provider default — but the provider defaults themselves must be priced.
        if mid in (get_settings().anthropic_model, get_settings().gemini_model):
            assert mid in data, f"Default model {mid!r} is not priced in .env.example"


def test_render_yaml_pricing_matches_env_example():
    """render.yaml's AI_MODEL_PRICING value must stay in sync with .env.example."""
    env_example = pathlib.Path(__file__).parent.parent / ".env.example"
    render_yaml = pathlib.Path(__file__).parent.parent.parent / "render.yaml"
    if not render_yaml.exists():
        return
    import json as _json

    env_text = env_example.read_text()
    m = re.search(r"^AI_MODEL_PRICING=(.*)$", env_text, re.MULTILINE)
    assert m
    env_data = _json.loads(m.group(1).strip().strip("'").strip('"'))

    ytext = render_yaml.read_text()
    # Find the AI_MODEL_PRICING value in render.yaml (quoted JSON string).
    my = re.search(r"AI_MODEL_PRICING.*\n\s+value:\s*'(.*)'", ytext)
    if not my:
        my = re.search(r'AI_MODEL_PRICING.*\n\s+value:\s*"(.*)"', ytext)
        if my:
            env_data_render = _json.loads(my.group(1))
        else:
            # sync:false with no value — skip if still placeholder
            return
    else:
        env_data_render = _json.loads(my.group(1))
    assert env_data_render == env_data, (
        "render.yaml AI_MODEL_PRICING does not match .env.example — update both together"
    )


def test_estimate_cost_uses_pricing_table(monkeypatch):
    """estimate_cost_usd must go through the table and return None when unpriced."""
    # Monkeypatch the settings-backed pricing via env var and clear the lru_cache.
    monkeypatch.setenv(
        "AI_MODEL_PRICING",
        json.dumps({"test-model": {"input_per_1m": 5, "output_per_1m": 25}}),
    )
    # get_settings is lru_cached — bust it so it re-reads the env.
    get_settings.cache_clear()
    model_pricing.cache_clear()
    try:
        assert estimate_cost_usd("test-model", 1_000_000, 1_000_000) == 30.0
        assert estimate_cost_usd("unknown-model", 1000, 1000) is None
    finally:
        # Restore defaults for other tests in the same process.
        monkeypatch.delenv("AI_MODEL_PRICING", raising=False)
        get_settings.cache_clear()
        model_pricing.cache_clear()
