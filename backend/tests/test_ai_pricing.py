"""Guard the AI price table against drift (task 0.10, AV-2).

AI_MODEL_PRICING is JSON keyed by model id, and the join between the two
sides is a bare string match. A model id that appears in config but not in
the price table silently records cost_usd = NULL (AI-17); a price-table key
that no longer matches any configured model silently prices nothing. Neither
fails loudly — usage analytics just quietly reports fewer dollars than were
spent — so the check has to be a test.

What is NOT asserted here: the numbers themselves. No test can know today's
rate; .env.example carries the provider page each was read from and the date
it was read, and re-checking them is a human step (see AV-124).
"""

import json
import pathlib
import re

from app.config import get_settings
from app.services.ai import estimate_cost_usd, model_pricing

ENV_EXAMPLE = pathlib.Path(__file__).resolve().parent.parent / ".env.example"

# Every setting naming a model. A blank per-surface model means "use that
# provider's default", so the defaults are what such a surface actually bills
# against — which is why anthropic_model and gemini_model are in this list and
# are separately required to carry a price below.
_MODEL_SETTINGS = (
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
)


def _configured_model_ids() -> set[str]:
    settings = get_settings()
    return {v for attr in _MODEL_SETTINGS if (v := getattr(settings, attr, ""))}


def _example_pricing() -> dict[str, dict[str, float]]:
    match = re.search(r"^AI_MODEL_PRICING=(.*)$", ENV_EXAMPLE.read_text(), re.MULTILINE)
    assert match, "AI_MODEL_PRICING is missing from .env.example"
    data = json.loads(match.group(1).strip())
    assert isinstance(data, dict), "AI_MODEL_PRICING must be a JSON object"
    return data


def test_example_pricing_is_valid_json_the_app_can_read():
    """Malformed JSON is swallowed by model_pricing() rather than raised, so a
    typo in the example everyone copies would surface only as permanently
    unpriced calls in production."""
    prices = _example_pricing()
    assert prices, "the example should price the default models, not ship empty"
    for model, entry in prices.items():
        assert isinstance(entry, dict), f"{model} must map to an object"
        for field in ("input_per_1m", "output_per_1m"):
            assert isinstance(entry.get(field), int | float), f"{model}.{field} must be a number"
            assert entry[field] > 0, f"{model}.{field} must be a real rate, not 0"


def test_every_example_price_key_names_a_configured_model():
    configured = _configured_model_ids()
    for key in _example_pricing():
        assert key in configured, (
            f"AI_MODEL_PRICING prices {key!r}, which is not a model id in config.py "
            f"(configured: {sorted(configured)}). A key that matches nothing prices nothing."
        )


def test_the_provider_default_models_are_priced():
    """A per-surface model left blank resolves to its provider's default, so
    those two ids carry almost all the spend — an unpriced default means the
    usage report is close to empty."""
    settings = get_settings()
    prices = _example_pricing()
    for default in (settings.anthropic_model, settings.gemini_model):
        assert default in prices, f"the default model {default!r} has no price in .env.example"


def test_estimate_cost_uses_the_table_and_admits_when_it_cannot(monkeypatch):
    monkeypatch.setenv(
        "AI_MODEL_PRICING",
        json.dumps({"test-model": {"input_per_1m": 5, "output_per_1m": 25}}),
    )
    # Both are @lru_cache'd — the same reason a price change on Render needs a
    # process restart, and the reason this test must clear them on the way in
    # *and* on the way out.
    get_settings.cache_clear()
    model_pricing.cache_clear()
    try:
        assert estimate_cost_usd("test-model", 1_000_000, 1_000_000) == 30.0
        assert estimate_cost_usd("unknown-model", 1000, 1000) is None
    finally:
        monkeypatch.delenv("AI_MODEL_PRICING", raising=False)
        get_settings.cache_clear()
        model_pricing.cache_clear()
