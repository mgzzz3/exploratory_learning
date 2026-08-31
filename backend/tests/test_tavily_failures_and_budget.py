from __future__ import annotations

import asyncio
import traceback

import httpx
import pytest
from pydantic import SecretStr

import app.clients.tavily as tavily

from .test_tavily_extract_adapter import extract_payload
from .test_tavily_official_contract import provider_status, recorded_http
from .test_tavily_search_adapter import RecordingSearchFactory, result_payload


async def identity_url(value: str) -> str:
    return value


def make_adapter(kind, factory=None, **kwargs):
    shared = dict(tavily_api_key=SecretStr("offline-placeholder"), normalize_url=identity_url)
    if factory is not None:
        shared["tool_factory"] = factory
    shared.update(kwargs)
    if kind == "search":
        return tavily.AdaptiveTavilySearch(**shared).search, tavily.AdaptiveSearchInput(query="test")
    return (
        tavily.AdaptiveTavilyExtract(**shared).extract,
        tavily.AdaptiveExtractInput(urls=["https://example.com/guide"], full_page=True),
    )


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["search", "extract"])
@pytest.mark.parametrize(
    "provider_status,reason,attempts",
    [
        (400, "PROVIDER_INVALID_REQUEST", 1),
        (401, "PROVIDER_AUTH_FAILED", 1),
        (403, "PROVIDER_AUTH_FAILED", 1),
        (422, "PROVIDER_INVALID_REQUEST", 1),
        (429, "PROVIDER_RATE_LIMITED", 1),
        (503, "PROVIDER_UNAVAILABLE", 2),
    ],
    indirect=["provider_status"],
)
async def test_official_http_status_maps_to_safe_error_without_unbounded_retry(
    kind, provider_status, reason, attempts, recorded_http
):
    invoke, params = make_adapter(kind)
    execution = tavily.TavilyCallContext()
    with pytest.raises(tavily.TavilyToolError) as caught:
        await invoke(params, execution=execution)
    assert caught.value.code == "SEARCH_UNAVAILABLE"
    assert caught.value.reason == reason
    assert execution.logical_calls == 1
    assert execution.physical_requests == attempts == len(recorded_http)
    assert execution.retries == attempts - 1
    assert "offline test response" not in "".join(traceback.format_exception(caught.value))


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["search", "extract"])
@pytest.mark.parametrize(
    "message",
    [
        "Authentication 401; rate limit 429; timeout 503",
        "prefix Error 401: secret-marker",
        "Error 4010: secret-marker",
        "Error 999: secret-marker",
        "Error 401: secret-marker\ntrailing",
        "Error 404: secret-marker",
    ],
)
async def test_unknown_error_format_fails_closed_without_guessing(kind, message):
    factory = RecordingSearchFactory([Exception(message)])
    invoke, params = make_adapter(kind, factory)
    with pytest.raises(tavily.TavilyToolError) as caught:
        await invoke(params)
    assert caught.value.reason == "PROVIDER_INVALID_RESPONSE"
    assert len(factory.invoke_calls) == 1
    assert "secret-marker" not in "".join(traceback.format_exception(caught.value))


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["search", "extract"])
async def test_structured_status_wins_and_error_body_cannot_spoof_category(kind):
    error = httpx.HTTPStatusError(
        "Error 401: secret-marker",
        request=httpx.Request("GET", "https://example.com"),
        response=httpx.Response(429),
    )
    invoke, params = make_adapter(kind, RecordingSearchFactory([error]))
    with pytest.raises(tavily.TavilyToolError) as caught:
        await invoke(params)
    assert caught.value.reason == "PROVIDER_RATE_LIMITED"
    assert "secret-marker" not in "".join(traceback.format_exception(caught.value))


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["search", "extract"])
@pytest.mark.parametrize("failure", [ConnectionError, TimeoutError])
async def test_retry_tracks_physical_requests_and_backoff_in_original_window(kind, failure):
    now = [100.0]
    delays = []

    async def sleep(delay):
        delays.append(delay)
        now[0] += delay

    success = result_payload() if kind == "search" else extract_payload()
    factory = RecordingSearchFactory([failure("secret-marker"), success])
    invoke, params = make_adapter(kind, factory)
    execution = tavily.TavilyCallContext(deadline=101.0, clock=lambda: now[0], sleep=sleep)
    await invoke(params, execution=execution)
    assert execution.logical_calls == 1
    assert execution.physical_requests == 2
    assert execution.retries == 1
    assert len(delays) == 1 and 0 < delays[0] <= 0.25
    assert execution.deadline == 101.0


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["search", "extract"])
async def test_tool_window_cancellation_is_not_a_provider_timeout_or_retry(kind):
    cancelled = asyncio.Event()

    async def blocked(_):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    factory = RecordingSearchFactory([blocked])
    invoke, params = make_adapter(kind, factory)
    execution = tavily.TavilyCallContext(deadline=asyncio.get_running_loop().time() + 0.02)
    with pytest.raises(tavily.ToolWindowClosedError):
        await invoke(params, execution=execution)
    assert cancelled.is_set()
    assert execution.physical_requests == 1
    assert execution.retries == 0


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["search", "extract"])
async def test_expired_window_makes_no_physical_request(kind):
    factory = RecordingSearchFactory([])
    invoke, params = make_adapter(kind, factory)
    execution = tavily.TavilyCallContext(deadline=100.0, clock=lambda: 100.0)
    with pytest.raises(tavily.ToolWindowClosedError):
        await invoke(params, execution=execution)
    assert execution.physical_requests == 0
    assert factory.init_calls == []


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["search", "extract"])
async def test_exhausted_provider_retries_keep_timeout_reason(kind):
    factory = RecordingSearchFactory([TimeoutError("secret-marker"), TimeoutError("secret-marker")])
    invoke, params = make_adapter(kind, factory)
    execution = tavily.TavilyCallContext()
    with pytest.raises(tavily.TavilyToolError) as caught:
        await invoke(params, execution=execution)
    assert caught.value.reason == "PROVIDER_TIMEOUT"
    assert execution.physical_requests == 2
    assert execution.retries == 1


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["search", "extract"])
@pytest.mark.parametrize("payload", [{"error": "secret-marker"}, {"results": "secret-marker"}, {}])
async def test_error_payload_and_invalid_structure_are_not_evidence(kind, payload):
    factory = RecordingSearchFactory([payload])
    invoke, params = make_adapter(kind, factory)
    with pytest.raises(tavily.TavilyToolError) as caught:
        await invoke(params)
    assert caught.value.reason == "PROVIDER_INVALID_RESPONSE"
    assert len(factory.invoke_calls) == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    "payload,reason",
    [
        (extract_payload(raw_content=""), "PAGE_EMPTY"),
        (extract_payload(raw_content="x" * 120_001), "PAGE_TOO_LARGE"),
        ({"results": [], "failed_results": [{"url": "https://example.com/guide", "error": "secret-marker"}]}, "PAGE_EXTRACTION_FAILED"),
        ({"error": Exception("Error 415: secret-marker")}, "PAGE_UNSUPPORTED"),
    ],
)
async def test_page_failure_reasons_are_safe_and_not_retried(payload, reason):
    factory = RecordingSearchFactory([payload])
    invoke, params = make_adapter("extract", factory)
    with pytest.raises(tavily.PageUnreadableError) as caught:
        await invoke(params)
    assert caught.value.reason == reason
    assert len(factory.invoke_calls) == 1
    assert "secret-marker" not in "".join(traceback.format_exception(caught.value))
