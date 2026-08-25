from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from app.clients.ai import (
    ContentGenerationError,
    DeepSeekContentGenerator,
    LocalContentGenerator,
)
from app.clients.wechat import LocalWechatClient, WechatApiClient, WechatClientError

from .fakes import generated_game


def patch_http_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    original = httpx.AsyncClient

    def factory(*args, **kwargs):
        del args
        kwargs.pop("timeout", None)
        return original(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr("app.clients.wechat.httpx.AsyncClient", factory)


@pytest.mark.anyio
async def test_wechat_api_login_and_message_check(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("jscode2session"):
            return httpx.Response(200, json={"openid": "wx-user", "unionid": "union"})
        if request.url.path.endswith("stable_token"):
            return httpx.Response(200, json={"access_token": "token", "expires_in": 7200})
        return httpx.Response(200, json={"errcode": 0, "result": {"suggest": "pass"}})

    patch_http_client(monkeypatch, handler)
    client = WechatApiClient(app_id="id", app_secret="secret", base_url="https://wx.test")

    session = await client.code_to_session("login-code")
    first = await client.check_message(session.openid, "Python")
    second = await client.check_message(session.openid, "Python")

    assert session.openid == "wx-user"
    assert session.unionid == "union"
    assert first is True and second is True
    assert sum(item.url.path.endswith("stable_token") for item in requests) == 1
    check_body = json.loads(requests[-1].content)
    assert check_body["version"] == 2
    assert check_body["openid"] == "wx-user"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("path", "response"),
    [
        ("login", httpx.Response(200, json={"errcode": 40029, "errmsg": "bad code"})),
        ("login", httpx.Response(502, text="gateway")),
        ("token", httpx.Response(200, json={"errcode": 40013, "errmsg": "bad app"})),
        ("token", httpx.Response(502, text="gateway")),
        ("check", httpx.Response(200, json={"errcode": 45009, "errmsg": "busy"})),
        ("check", httpx.Response(502, text="gateway")),
    ],
)
async def test_wechat_api_errors_are_normalized(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    response: httpx.Response,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if path == "login":
            return response
        if request.url.path.endswith("stable_token"):
            return response if path == "token" else httpx.Response(200, json={"access_token": "ok"})
        return response

    patch_http_client(monkeypatch, handler)
    client = WechatApiClient(app_id="id", app_secret="secret", base_url="https://wx.test")

    with pytest.raises(WechatClientError):
        if path == "login":
            await client.code_to_session("bad")
        else:
            await client.check_message("openid", "topic")


@pytest.mark.anyio
async def test_wechat_check_returns_false_for_risky_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("stable_token"):
            return httpx.Response(200, json={"access_token": "ok"})
        return httpx.Response(200, json={"errcode": 0, "result": {"suggest": "risky"}})

    patch_http_client(monkeypatch, handler)
    client = WechatApiClient(app_id="id", app_secret="secret", base_url="https://wx.test")
    assert await client.check_message("openid", "topic") is False


@pytest.mark.anyio
async def test_local_clients_are_deterministic_and_safe() -> None:
    wechat = LocalWechatClient()
    assert (await wechat.code_to_session("same-code")) == (
        await wechat.code_to_session("same-code")
    )
    assert await wechat.check_message("local", "Python 基础") is True
    assert await wechat.check_message("local", "赌博教程") is False

    game = await LocalContentGenerator().generate("Python 基础")
    assert game.title == "Python 基础"
    assert len(game.levels) == 3


class FakeResponses:
    def __init__(self, outputs: list[object]) -> None:
        self.outputs = outputs
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.outputs.pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(output_text=item)


@pytest.mark.anyio
async def test_deepseek_uses_strict_schema_and_retries_invalid_json() -> None:
    expected = generated_game("Python 基础")
    responses = FakeResponses(["not-json", expected.model_dump_json()])
    generator = DeepSeekContentGenerator(
        api_key="test-key",
        base_url="https://deepseek.test",
        model="deepseek-v4-flash",
        max_retries=2,
    )
    generator.client = SimpleNamespace(responses=responses)

    actual = await generator.generate("Python 基础")

    assert actual == expected
    assert len(responses.calls) == 2
    call = responses.calls[0]
    assert call["model"] == "deepseek-v4-flash"
    assert call["reasoning"] == {"effort": "none"}
    assert call["text"]["format"]["type"] == "json_schema"
    assert call["text"]["format"]["schema"]["title"] == "GeneratedGame"
    assert call["max_output_tokens"] == 4000
    assert call["store"] is False


@pytest.mark.anyio
async def test_deepseek_normalizes_empty_and_provider_failures() -> None:
    generator = DeepSeekContentGenerator(
        api_key="test-key",
        base_url="https://deepseek.test",
        model="deepseek-v4-flash",
        max_retries=2,
    )
    generator.client = SimpleNamespace(
        responses=FakeResponses([RuntimeError("network"), ""])
    )

    with pytest.raises(ContentGenerationError, match="完整关卡"):
        await generator.generate("Python 基础")
