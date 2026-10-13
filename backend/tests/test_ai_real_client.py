"""The real Anthropic SDK client, driven against a canned in-process server.

Every other AI test swaps out `structured_complete` with `fake_ai`, so none of
them ever builds the SDK client. That is how a marking call that the SDK refuses
before sending (`max_tokens=32000` on a non-streaming request) went unnoticed.
Here the real `AsyncAnthropic` is built, wired to a transport that answers with
server-sent events, so the request-building, the SDK's own guards and its stream
parsing are exercised for real. Nothing leaves the process and no real key is
used (`QA-8`).
"""

import asyncio
import contextlib
import json

import anthropic
import pytest
from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.services import ai as ai_service
from app.services.ai import (
    AICallFailedError,
    AIKeyMissingError,
    AIOutputTruncatedError,
    AITimeoutError,
    AIUnavailableError,
    get_client,
    structured_complete,
    text_complete,
)
from app.services.extraction import (
    BookletExtractionResult,
    ExtractionResult,
    PastPaperExtractionResult,
)
from app.services.marking import MARKING_MAX_TOKENS, MarkingResult
from app.services.marking_rules import MarkingRulesSummary
from app.services.mistake_tagging import MistakeTaggingResult
from app.services.plan_drafting import PlanWeightingResult
from app.services.readiness_v2_ai import ReadinessSynthesis
from app.services.syllabus_extraction import SyllabusExtractionResult
from tests.ai_stream_fakes import (
    VERDICT_JSON,
    CannedServer,
    Trickle,
    dropping_transport,
    http,
    sse_message,
)

CONTENT = [{"type": "text", "text": "mark this"}]


class Verdict(BaseModel):
    mark: int
    comment: str


@pytest.fixture
def anthropic_key(monkeypatch):
    # Not a working key: the transport below never reaches the network.
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-ant-canned", raising=False)


@pytest.fixture
def serve(monkeypatch, anthropic_key):
    """Point the real client at a CannedServer answering with `body`."""

    def _serve(body: bytes) -> CannedServer:
        server = CannedServer(body)
        monkeypatch.setattr(ai_service, "_transport", http.MockTransport(server))
        return server

    return _serve


async def _structured(max_tokens: int = 500):
    return await structured_complete(
        surface="marking", content=CONTENT, output_format=Verdict, max_tokens=max_tokens
    )


async def _text(max_tokens: int = 400):
    return await text_complete(surface="narrative", prompt="write", max_tokens=max_tokens)


# --------------------------------------------------------------------------
# The request: streams, carries the limit, and matches what `parse` would send
# --------------------------------------------------------------------------


async def test_marking_call_with_the_real_limit_reaches_the_transport(serve):
    server = serve(sse_message(VERDICT_JSON))

    response = await _structured(MARKING_MAX_TOKENS)

    assert len(server.requests) == 1
    assert server.sent["stream"] is True
    assert server.sent["max_tokens"] == MARKING_MAX_TOKENS == 32000
    assert response.parsed == Verdict(mark=3, comment="Correct method, arithmetic slip.")
    assert response.input_tokens == 123
    assert response.output_tokens == 45
    assert response.model == "claude-canned"
    assert response.truncated is False


@pytest.mark.parametrize("max_tokens", [400, 2000, 16000, 32000, 64000])
async def test_no_max_tokens_is_refused_client_side_structured(serve, max_tokens):
    server = serve(sse_message(VERDICT_JSON))

    response = await _structured(max_tokens)

    assert server.sent["max_tokens"] == max_tokens
    assert response.parsed is not None


@pytest.mark.parametrize("max_tokens", [400, 2000, 16000, 32000, 64000])
async def test_no_max_tokens_is_refused_client_side_text(serve, max_tokens):
    server = serve(sse_message("A short paragraph."))

    response = await _text(max_tokens)

    assert server.sent["max_tokens"] == max_tokens
    assert server.sent["stream"] is True
    assert response.text == "A short paragraph."
    assert response.input_tokens == 123
    assert response.output_tokens == 45
    assert response.truncated is False


@pytest.mark.parametrize(
    "output_format",
    [
        Verdict,
        MarkingResult,
        MarkingRulesSummary,
        MistakeTaggingResult,
        SyllabusExtractionResult,
        ExtractionResult,
        PastPaperExtractionResult,
        BookletExtractionResult,
        PlanWeightingResult,
        ReadinessSynthesis,
    ],
)
async def test_the_schema_sent_is_exactly_what_messages_parse_sends(serve, output_format):
    # We build `output_config` ourselves (so the answer can be parsed after the
    # stop reason is known); this pins it to what the SDK's own `parse` builds
    # from the same type, for every model a real call site passes, so the API
    # sees the same constraint as before. The canned answer is not valid for most
    # of these models, which does not matter: only the request is compared.
    server = serve(sse_message(VERDICT_JSON))
    with contextlib.suppress(ValidationError):
        await structured_complete(
            surface="marking", content=CONTENT, output_format=output_format, max_tokens=50
        )
    ours = server.sent

    with contextlib.suppress(ValidationError):
        await get_client().messages.parse(
            model=ours["model"],
            max_tokens=50,
            messages=[{"role": "user", "content": "x"}],
            output_format=output_format,
        )
    theirs = server.sent

    assert theirs.get("stream") is None  # it really was the non-streaming call
    assert ours["output_config"] == theirs["output_config"]
    assert ours["output_config"]["format"]["type"] == "json_schema"
    assert ours["output_config"]["format"]["schema"]["properties"]


# --------------------------------------------------------------------------
# The answer: read the stop reason first, then parse
# --------------------------------------------------------------------------


async def test_a_thinking_block_before_the_text_still_parses(serve):
    serve(sse_message(VERDICT_JSON, thinking="Let me check the working."))

    response = await _structured()

    assert response.parsed == Verdict(mark=3, comment="Correct method, arithmetic slip.")


async def test_structured_answer_cut_off_mid_json_raises_truncated(serve):
    serve(sse_message(VERDICT_JSON[:20], stop_reason="max_tokens"))

    with pytest.raises(AIOutputTruncatedError, match="cut off at the output limit") as caught:
        await _structured(MARKING_MAX_TOKENS)
    assert caught.value.input_tokens == 123
    assert caught.value.output_tokens == 45
    assert caught.value.model == "claude-canned"


async def test_structured_answer_with_max_tokens_stop_raises_even_if_json_is_whole(serve):
    # The model hit the limit at the last token: the JSON happens to parse, but
    # "stopped because it ran out of room" is not an answer to trust.
    serve(sse_message(VERDICT_JSON, stop_reason="max_tokens"))

    with pytest.raises(AIOutputTruncatedError):
        await _structured()


async def test_a_refusal_raises_with_its_own_message(serve):
    serve(sse_message("", stop_reason="refusal"))

    with pytest.raises(AICallFailedError, match="declined to answer") as caught:
        await _structured()
    assert not isinstance(caught.value, AIOutputTruncatedError)
    assert (caught.value.input_tokens, caught.value.output_tokens) == (123, 45)


async def test_context_window_exceeded_is_not_reported_as_an_output_limit(serve):
    serve(sse_message("", stop_reason="model_context_window_exceeded"))

    with pytest.raises(AICallFailedError, match="too large") as caught:
        await _structured()
    assert not isinstance(caught.value, AIOutputTruncatedError)
    assert "cut off" not in str(caught.value)

    with pytest.raises(AICallFailedError, match="too large"):
        await _text()


async def test_a_stream_with_no_closing_message_is_interrupted(serve):
    serve(sse_message(VERDICT_JSON, stop_reason=None))

    with pytest.raises(AICallFailedError, match="interrupted"):
        await _structured()
    with pytest.raises(AICallFailedError, match="interrupted"):
        await _text()


async def test_a_200_with_an_empty_body_is_interrupted(serve):
    serve(b"")

    with pytest.raises(AICallFailedError, match="interrupted") as caught:
        await _structured()
    assert caught.value.model is None  # nothing arrived, so nothing to report
    with pytest.raises(AICallFailedError, match="interrupted"):
        await _text()


async def test_an_empty_text_block_that_ended_normally_is_not_a_cut_off(serve):
    serve(sse_message("", stop_reason="end_turn"))

    with pytest.raises(AICallFailedError, match="no structured result") as caught:
        await _structured()
    assert "cut off" not in str(caught.value)
    assert not isinstance(caught.value, AIOutputTruncatedError)

    with pytest.raises(AICallFailedError, match="empty answer") as text_caught:
        await _text()
    assert "cut off" not in str(text_caught.value)


async def test_a_schema_mismatch_is_still_a_validation_error(serve):
    # A real model fault, not a transport problem: it propagates unchanged.
    serve(sse_message(json.dumps({"mark": "three"})))

    with pytest.raises(ValidationError):
        await _structured()


async def test_text_cut_off_with_partial_text_is_returned_flagged(serve, caplog):
    serve(sse_message("The class did well on algebra but", stop_reason="max_tokens"))

    with caplog.at_level("WARNING", logger="app.services.ai"):
        response = await _text(400)

    assert response.truncated is True
    assert response.text == "The class did well on algebra but"
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "narrative" in warnings[0].getMessage()
    assert "400" in warnings[0].getMessage()


async def test_text_cut_off_with_no_text_raises(serve):
    serve(sse_message("", stop_reason="max_tokens"))

    with pytest.raises(AIOutputTruncatedError):
        await _text()


async def test_text_refusal_raises_even_with_partial_text(serve):
    serve(sse_message("I cannot", stop_reason="refusal"))

    with pytest.raises(AICallFailedError, match="declined to answer"):
        await _text()


async def test_whitespace_only_text_is_no_result_for_both_helpers(serve):
    serve(sse_message("  \n "))

    with pytest.raises(AICallFailedError, match="no structured result"):
        await _structured()
    with pytest.raises(AICallFailedError, match="empty answer"):
        await _text()


async def test_two_text_blocks_together_form_one_json_document(serve):
    serve(sse_message([VERDICT_JSON[:15], VERDICT_JSON[15:]]))

    response = await _structured()

    assert response.parsed == Verdict(mark=3, comment="Correct method, arithmetic slip.")


# --------------------------------------------------------------------------
# The error types
# --------------------------------------------------------------------------


def test_a_failed_call_is_not_a_not_configured_error():
    # This is the whole point of the hierarchy. `narrative.py` catches
    # AIUnavailableError ("not configured") and quietly stores nothing, with no
    # retry. A timeout or cut-off must NOT be caught by that: it has to fail the
    # job so the job is retried.
    assert not issubclass(AICallFailedError, AIUnavailableError)
    assert not issubclass(AITimeoutError, AIUnavailableError)
    assert not issubclass(AIOutputTruncatedError, AIUnavailableError)
    assert issubclass(AITimeoutError, AICallFailedError)
    assert issubclass(AIOutputTruncatedError, AICallFailedError)
    assert issubclass(AIKeyMissingError, AIUnavailableError)


# --------------------------------------------------------------------------
# A failure partway through the answer
# --------------------------------------------------------------------------
# The SDK wraps transport errors only while it sends the request. Once the body
# is being read they escape as the HTTP library's own classes, which is the most
# likely real failure of a long marking answer (the silence timeout fires).


def _mid_answer_errors():
    return [
        (http.ReadTimeout("no bytes for 600s"), AITimeoutError, "did not answer in time"),
        (http.RemoteProtocolError("peer closed"), AICallFailedError, "dropped mid-answer"),
        (http.ReadError("connection reset"), AICallFailedError, "dropped mid-answer"),
    ]


@pytest.mark.parametrize("which", [0, 1, 2])
@pytest.mark.parametrize("helper", ["structured", "text"])
async def test_an_http_error_mid_answer_becomes_one_of_ours(
    monkeypatch, anthropic_key, which, helper
):
    error, expected_type, message = _mid_answer_errors()[which]
    body = sse_message(VERDICT_JSON if helper == "structured" else "A paragraph of text.")
    monkeypatch.setattr(ai_service, "_transport", dropping_transport(body, error))

    call = _structured if helper == "structured" else _text
    with pytest.raises(expected_type, match=message) as caught:
        await call()

    assert caught.value.__cause__ is error
    assert type(caught.value) in (AITimeoutError, AICallFailedError)
    if expected_type is AICallFailedError:
        assert not isinstance(caught.value, AITimeoutError)


def test_the_http_stack_is_recognised_by_module_name_only():
    assert ai_service._from_http_stack(http.ReadError("x"))
    assert not ai_service._from_http_stack(anthropic.APIError("x", request=None, body=None))
    assert not ai_service._from_http_stack(ValueError("x"))
    assert not ai_service._from_http_stack(TimeoutError("x"))


async def test_other_errors_pass_through_the_mid_answer_translation_untouched():
    for exc in (ValueError("x"), TimeoutError("x"), KeyError("x")):
        translator = ai_service._http_errors_as_ai_errors()
        with pytest.raises(type(exc)) as caught:
            async with translator:
                raise exc
        assert caught.value is exc


# --------------------------------------------------------------------------
# Time limits
# --------------------------------------------------------------------------


async def test_a_stream_that_trickles_past_the_deadline_is_cut_and_closed(
    monkeypatch, anthropic_key
):
    trickle = Trickle()
    transport = http.MockTransport(
        lambda request: http.Response(
            200, headers={"content-type": "text/event-stream"}, stream=trickle
        )
    )
    monkeypatch.setattr(ai_service, "_transport", transport)
    monkeypatch.setattr(get_settings(), "ai_call_timeout_seconds", 0.1, raising=False)

    with pytest.raises(AITimeoutError, match="did not answer in time") as caught:
        await _structured()
    assert isinstance(caught.value.__cause__, TimeoutError)
    assert trickle.closed is True


async def test_text_calls_use_their_own_shorter_deadline(monkeypatch, anthropic_key):
    transport = http.MockTransport(
        lambda request: http.Response(
            200, headers={"content-type": "text/event-stream"}, stream=Trickle()
        )
    )
    monkeypatch.setattr(ai_service, "_transport", transport)
    # The structured limit is long; only the text limit may stop this call.
    monkeypatch.setattr(get_settings(), "ai_call_timeout_seconds", 3600.0, raising=False)
    monkeypatch.setattr(get_settings(), "ai_text_call_timeout_seconds", 0.1, raising=False)

    with pytest.raises(AITimeoutError):
        await _text()


async def test_a_caller_can_ask_a_text_call_for_the_long_cap(monkeypatch, anthropic_key):
    # The report writer is a long document written in a job, not a short line.
    transport = http.MockTransport(
        lambda request: http.Response(
            200, headers={"content-type": "text/event-stream"}, stream=Trickle()
        )
    )
    monkeypatch.setattr(ai_service, "_transport", transport)
    monkeypatch.setattr(get_settings(), "ai_text_call_timeout_seconds", 0.05, raising=False)
    seen: list[float] = []
    real_deadline = ai_service._call_deadline

    def spy(surface, limit):
        seen.append(limit)
        return real_deadline(surface, 0.1)  # still end the test quickly

    monkeypatch.setattr(ai_service, "_call_deadline", spy)

    with pytest.raises(AITimeoutError):
        await text_complete(
            surface="reports", prompt="write", max_tokens=2000, timeout_seconds=840.0
        )
    with pytest.raises(AITimeoutError):
        await text_complete(surface="narrative", prompt="write", max_tokens=400)

    assert seen == [840.0, 0.05]


async def test_the_report_writer_asks_for_the_long_cap(monkeypatch):
    from app.services import reports

    seen: dict = {}

    async def fake_text_complete(**kwargs):
        seen.update(kwargs)
        raise RuntimeError("stop here")

    monkeypatch.setattr(reports, "text_complete", fake_text_complete)
    monkeypatch.setattr(get_settings(), "ai_call_timeout_seconds", 840.0, raising=False)
    monkeypatch.setattr(get_settings(), "ai_text_call_timeout_seconds", 120.0, raising=False)

    with pytest.raises(RuntimeError, match="stop here"):
        await reports._write_report(
            reports.ReportAudience.parent,
            "facts",
            None,
            organization_id=1,
            tutor_id=1,
            student_id=1,
        )

    assert seen["surface"] == "reports"
    assert seen["timeout_seconds"] == 840.0


async def test_the_sdks_per_request_timeout_looks_the_same_as_the_deadline(
    monkeypatch, anthropic_key
):
    def silent(request):
        raise http.ReadTimeout("no bytes", request=request)

    monkeypatch.setattr(ai_service, "_transport", http.MockTransport(silent))
    monkeypatch.setattr(get_settings(), "ai_max_retries", 0, raising=False)

    with pytest.raises(AITimeoutError, match="did not answer in time"):
        await _structured()
    with pytest.raises(AITimeoutError):
        await _text()


async def test_a_timeout_error_from_inside_the_call_is_not_relabelled(monkeypatch):
    # Only our own deadline is converted; a TimeoutError raised for another
    # reason keeps its identity.
    deadline = ai_service._call_deadline("marking", 60.0)
    foreign = TimeoutError("someone else's")
    with pytest.raises(TimeoutError) as caught:
        async with deadline:
            raise foreign
    assert not isinstance(caught.value, AITimeoutError)


async def test_gemini_calls_have_the_same_total_time_limit(monkeypatch):
    class _Models:
        async def generate_content(self, **kwargs):
            await asyncio.sleep(3600)

    class _Aio:
        models = _Models()

    class _Gemini:
        aio = _Aio()

    monkeypatch.setattr(get_settings(), "ai_narrative_provider", "gemini", raising=False)
    monkeypatch.setattr(ai_service, "get_gemini_client", lambda: _Gemini())
    monkeypatch.setattr(get_settings(), "ai_text_call_timeout_seconds", 0.05, raising=False)

    with pytest.raises(AITimeoutError, match="did not answer in time"):
        await _text()


# --------------------------------------------------------------------------
# The client
# --------------------------------------------------------------------------


async def test_empty_key_still_raises_key_missing(monkeypatch):
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "", raising=False)

    with pytest.raises(AIKeyMissingError):
        get_client()


async def test_key_is_checked_on_every_call_not_cached(monkeypatch, anthropic_key):
    assert get_client() is not None
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "", raising=False)

    with pytest.raises(AIKeyMissingError):
        get_client()


async def test_client_is_reused_within_a_loop_and_carries_the_configured_limits(
    monkeypatch, anthropic_key
):
    monkeypatch.setattr(get_settings(), "ai_request_timeout_seconds", 42.0, raising=False)
    monkeypatch.setattr(get_settings(), "ai_max_retries", 3, raising=False)

    first = get_client()

    assert get_client() is first
    assert first.max_retries == 3
    assert first.timeout == anthropic.Timeout(42.0, connect=5.0)


async def test_changed_settings_build_a_fresh_client(monkeypatch, anthropic_key):
    first = get_client()
    monkeypatch.setattr(get_settings(), "ai_max_retries", 0, raising=False)

    assert get_client() is not first


def test_a_client_is_never_handed_to_a_different_event_loop(monkeypatch, anthropic_key):
    async def grab():
        return get_client()

    first_loop = asyncio.new_event_loop()
    second_loop = asyncio.new_event_loop()
    try:
        a = first_loop.run_until_complete(grab())
        a_again = first_loop.run_until_complete(grab())
        b = second_loop.run_until_complete(grab())
    finally:
        first_loop.close()
        second_loop.close()

    assert a is a_again
    assert b is not a
