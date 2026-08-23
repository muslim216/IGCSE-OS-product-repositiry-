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

# The models every surface routes to once AV-124 lands: Opus 5 for marking,
# extraction, syllabus and readiness; Sonnet 5 for reports, class brief and
# narrative. Hard-coded from the decision rather than read from config.py,
# because this table is deliberately priced ahead of the routing flip (task
# 3.2) and must not silently follow config back to Gemini.
AV_124_MODELS = ("claude-opus-5", "claude-sonnet-5")

# Configured today, deliberately not priced — both are on the way out under
# AV-124, and pricing a model being deleted is work that expires.
#
#   gemini-2.5-pro    the three Gemini surfaces AV-124 moves to Opus 5
#   claude-haiku-4-5  chat, which task 0.3 removes (0024_drop_chat)
#
# They are named rather than skipped so the guard below can be exhaustive:
# anything else configured and unpriced is drift, not a decision. If chat
# outlives 0.3, this entry is what has to be argued with.
DELIBERATELY_UNPRICED = {"gemini-2.5-pro", "claude-haiku-4-5"}

# Every setting naming a model. A blank per-surface model means "use that
# provider's default", so the defaults are what such a surface actually bills
# against — which is why anthropic_model is in this list and is separately
# required to carry a price below.
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


def test_every_example_price_key_is_a_model_something_resolves_to():
    """A key matching no model prices nothing. Both windows count: the ids
    config.py resolves to today, and the ones AV-124 moves every surface to."""
    allowed = _configured_model_ids() | set(AV_124_MODELS)
    for key in _example_pricing():
        assert key in allowed, (
            f"AI_MODEL_PRICING prices {key!r}, which is neither a model id in config.py "
            f"nor one of AV-124's targets {AV_124_MODELS}. Update the key or the routing."
        )


def test_the_models_av_124_routes_to_are_priced():
    """The whole point of the task. Once task 3.2 flips the routing these two
    carry every call in the product, and an unpriced one means the usage report
    is empty in exactly the state it was built for."""
    prices = _example_pricing()
    for model in AV_124_MODELS:
        assert model in prices, (
            f"AV-124 routes surfaces to {model!r} and it has no price in .env.example"
        )


def test_the_anthropic_default_is_priced_before_the_routing_flip():
    """Until 3.2 bumps anthropic_model, every surface with a blank per-surface
    model resolves to whatever it currently is. Leaving that unpriced would
    blind the interim window."""
    prices = _example_pricing()
    default = get_settings().anthropic_model
    assert default in prices, (
        f"anthropic_model is {default!r} and it has no price in .env.example — "
        "price it, or land task 3.2 so nothing resolves to it."
    )


def test_no_configured_model_is_unpriced_by_accident():
    """The other half of AI-17, and the half a per-setting check would miss.

    A blank per-surface model bills against its provider's default, so the two
    defaults cover most surfaces — but a *non-blank* one resolves straight to
    the id it names, and `ai_chat_model` is exactly that. Asserting only on
    anthropic_model leaves every such surface able to go unpriced in silence,
    which is the drift this file exists to catch: nothing raises, and usage
    analytics simply reports fewer dollars than were spent.

    Exhaustive by subtraction rather than by listing what to check, so a
    surface added later is covered the day it is added."""
    unpriced = _configured_model_ids() - set(_example_pricing()) - DELIBERATELY_UNPRICED
    assert not unpriced, (
        f"{sorted(unpriced)} are configured in config.py and priced nowhere in "
        ".env.example, so their calls record cost_usd = NULL forever (AI-17). "
        "Price them, or add them to DELIBERATELY_UNPRICED with the reason."
    )


def test_the_unpriced_exemptions_are_still_real_models():
    """An exemption for a model nothing configures any more is a stale excuse,
    and would hide a later id that happened to collide with it."""
    configured = _configured_model_ids()
    stale = DELIBERATELY_UNPRICED - configured
    assert not stale, (
        f"{sorted(stale)} are exempted from pricing but no longer configured — "
        "drop them from DELIBERATELY_UNPRICED."
    )


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
