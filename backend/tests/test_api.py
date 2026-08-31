from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from .conftest import login
from .fakes import FakeContentGenerator, FakeWechatClient


@pytest.mark.anyio
async def test_health(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_wechat_login_creates_and_reuses_user(
    client: AsyncClient,
    wechat: FakeWechatClient,
) -> None:
    first = await client.post("/api/v1/auth/wechat", json={"code": "same"})
    second = await client.post("/api/v1/auth/wechat", json={"code": "same"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["user"]["id"] == second.json()["user"]["id"]
    assert first.json()["token_type"] == "bearer"
    assert wechat.login_calls == ["same", "same"]


@pytest.mark.anyio
async def test_wechat_login_provider_failure_has_stable_error_contract(
    client: AsyncClient,
    wechat: FakeWechatClient,
) -> None:
    wechat.login_error = True

    response = await client.post("/api/v1/auth/wechat", json={"code": "broken"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "WECHAT_UNAVAILABLE"


@pytest.mark.anyio
async def test_game_creation_requires_authentication(client: AsyncClient) -> None:
    response = await client.post("/api/v1/games", json={"topic": "Python 基础"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.anyio
async def test_invalid_auth_and_invalid_request_have_stable_errors(
    client: AsyncClient,
) -> None:
    unauthorized = await client.get(
        "/api/v1/me",
        headers={"Authorization": "Bearer broken"},
    )
    invalid = await client.post(
        "/api/v1/auth/wechat",
        json={"code": "   ", "unexpected": True},
    )

    assert unauthorized.status_code == 401
    assert unauthorized.json()["error"]["code"] == "UNAUTHORIZED"
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.anyio
async def test_blocked_topic_never_reaches_model(
    client: AsyncClient,
    wechat: FakeWechatClient,
    generator: FakeContentGenerator,
) -> None:
    headers = await login(client)
    wechat.blocked_topics.add("违规主题")

    response = await client.post(
        "/api/v1/games",
        headers=headers,
        json={"topic": "违规主题"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CONTENT_BLOCKED"
    assert generator.calls == []


@pytest.mark.anyio
async def test_content_safety_outage_does_not_bypass_check(
    client: AsyncClient,
    wechat: FakeWechatClient,
    generator: FakeContentGenerator,
) -> None:
    headers = await login(client)
    wechat.safety_error = True

    response = await client.post(
        "/api/v1/games",
        headers=headers,
        json={"topic": "Python 基础"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "WECHAT_UNAVAILABLE"
    assert generator.calls == []


@pytest.mark.anyio
async def test_generation_failure_has_safe_details_without_echoing_topic(
    client: AsyncClient,
    generator: FakeContentGenerator,
) -> None:
    headers = await login(client)
    generator.error = True

    response = await client.post(
        "/api/v1/games",
        headers=headers,
        json={"topic": "Python 基础"},
    )

    assert response.status_code == 502
    error = response.json()["error"]
    assert error["code"] == "AI_GENERATION_FAILED"
    assert error["message"] == "这次没搭好关卡，请重新生成"
    assert error["details"]["reason"] == "GENERATION_UNAVAILABLE"
    assert len(error["details"]["request_id"]) == 32
    assert "topic" not in error["details"]


@pytest.mark.anyio
async def test_game_response_hides_answers_and_explanations(client: AsyncClient) -> None:
    headers = await login(client)

    response = await client.post(
        "/api/v1/games",
        headers=headers,
        json={"topic": "Python 基础"},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["hearts"] == 3
    assert data["current_level"] == 0
    assert data["level"]["tier"] == "novice"
    assert len(data["level"]["options"]) == 3
    assert "correct_option" not in data["level"]
    assert "wrong_explanation" not in data["level"]

    detail = await client.get(f"/api/v1/games/{data['id']}", headers=headers)
    assert detail.json() == data


@pytest.mark.anyio
async def test_missing_game_is_not_exposed(client: AsyncClient) -> None:
    headers = await login(client)
    response = await client.get("/api/v1/games/missing", headers=headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "GAME_NOT_FOUND"


async def create_game(client: AsyncClient, headers: dict[str, str]) -> dict:
    response = await client.post(
        "/api/v1/games",
        headers=headers,
        json={"topic": "Python 基础"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def answer(
    client: AsyncClient,
    headers: dict[str, str],
    game_id: str,
    option: int,
    attempt_id: str | None = None,
):
    return await client.post(
        f"/api/v1/games/{game_id}/answers",
        headers=headers,
        json={"option": option, "attempt_id": attempt_id or str(uuid4())},
    )


@pytest.mark.anyio
async def test_correct_answer_advances_and_duplicate_is_idempotent(
    client: AsyncClient,
) -> None:
    headers = await login(client)
    game = await create_game(client, headers)
    attempt_id = str(uuid4())

    first = await answer(client, headers, game["id"], 0, attempt_id)
    duplicate = await answer(client, headers, game["id"], 0, attempt_id)

    assert first.status_code == 200
    assert first.json()["result"] == "correct"
    assert first.json()["game"]["current_level"] == 1
    assert first.json()["game"]["hearts"] == 3
    assert duplicate.json() == first.json()


@pytest.mark.anyio
async def test_wrong_answers_stay_on_question_and_pause_at_zero(
    client: AsyncClient,
) -> None:
    headers = await login(client)
    game = await create_game(client, headers)

    results = [
        await answer(client, headers, game["id"], 1),
        await answer(client, headers, game["id"], 2),
        await answer(client, headers, game["id"], 1),
    ]

    assert [item.json()["game"]["hearts"] for item in results] == [2, 1, 0]
    assert results[0].json()["result"] == "wrong"
    assert "贴纸" in results[0].json()["explanation"]
    assert results[0].json()["game"]["current_level"] == 0
    assert results[2].json()["result"] == "paused"
    assert results[2].json()["game"]["status"] == "paused"

    blocked = await answer(client, headers, game["id"], 0)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "GAME_PAUSED"


@pytest.mark.anyio
async def test_ad_revive_restores_hearts_and_is_idempotent(client: AsyncClient) -> None:
    headers = await login(client)
    game = await create_game(client, headers)
    for _ in range(3):
        await answer(client, headers, game["id"], 1)
    event_id = str(uuid4())

    revived = await client.post(
        f"/api/v1/games/{game['id']}/revives/ad",
        headers=headers,
        json={"event_id": event_id, "completed": True},
    )
    duplicate = await client.post(
        f"/api/v1/games/{game['id']}/revives/ad",
        headers=headers,
        json={"event_id": event_id, "completed": True},
    )

    assert revived.status_code == 200
    assert revived.json()["hearts"] == 3
    assert revived.json()["status"] == "active"
    assert duplicate.json() == revived.json()


@pytest.mark.anyio
async def test_incomplete_ad_does_not_revive(client: AsyncClient) -> None:
    headers = await login(client)
    game = await create_game(client, headers)

    response = await client.post(
        f"/api/v1/games/{game['id']}/revives/ad",
        headers=headers,
        json={"event_id": str(uuid4()), "completed": False},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "AD_NOT_COMPLETED"


@pytest.mark.anyio
async def test_active_game_cannot_be_revived_or_shared(client: AsyncClient) -> None:
    headers = await login(client)
    game = await create_game(client, headers)

    revive = await client.post(
        f"/api/v1/games/{game['id']}/revives/ad",
        headers=headers,
        json={"event_id": str(uuid4()), "completed": True},
    )
    share = await client.post(
        f"/api/v1/games/{game['id']}/share",
        headers=headers,
    )

    assert revive.status_code == 409
    assert revive.json()["error"]["code"] == "GAME_NOT_PAUSED"
    assert share.status_code == 409
    assert share.json()["error"]["code"] == "GAME_NOT_PAUSED"


@pytest.mark.anyio
async def test_unknown_assist_token_is_rejected(client: AsyncClient) -> None:
    headers = await login(client)
    response = await client.post("/api/v1/assists/unknown", headers=headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ASSIST_NOT_FOUND"


@pytest.mark.anyio
async def test_friend_assist_requires_another_user_and_is_single_use(
    client: AsyncClient,
) -> None:
    owner_headers = await login(client, "owner")
    helper_headers = await login(client, "helper")
    other_headers = await login(client, "other")
    game = await create_game(client, owner_headers)
    for _ in range(3):
        await answer(client, owner_headers, game["id"], 1)

    share = await client.post(
        f"/api/v1/games/{game['id']}/share",
        headers=owner_headers,
    )
    assert share.status_code == 201
    token = share.json()["token"]
    assert token in share.json()["path"]

    self_assist = await client.post(
        f"/api/v1/assists/{token}",
        headers=owner_headers,
    )
    assert self_assist.status_code == 409
    assert self_assist.json()["error"]["code"] == "SELF_ASSIST_NOT_ALLOWED"

    assisted = await client.post(
        f"/api/v1/assists/{token}",
        headers=helper_headers,
    )
    assert assisted.status_code == 200
    assert assisted.json()["hearts"] == 3

    reused = await client.post(
        f"/api/v1/assists/{token}",
        headers=other_headers,
    )
    assert reused.status_code == 409
    assert reused.json()["error"]["code"] == "ASSIST_ALREADY_USED"


@pytest.mark.anyio
async def test_three_correct_answers_complete_game_and_update_profile(
    client: AsyncClient,
) -> None:
    headers = await login(client)
    game = await create_game(client, headers)

    for expected_level in (1, 2):
        response = await answer(client, headers, game["id"], 0)
        assert response.json()["game"]["current_level"] == expected_level
    completed = await answer(client, headers, game["id"], 0)

    assert completed.json()["result"] == "completed"
    assert completed.json()["game"]["status"] == "completed"
    assert len(completed.json()["game"]["summary"]) == 3

    profile = await client.get("/api/v1/me", headers=headers)
    assert profile.status_code == 200
    assert profile.json()["completed_games"] == 1
    assert profile.json()["learned_points"] == 3

    answered_again = await answer(client, headers, game["id"], 0)
    assert answered_again.status_code == 409
    assert answered_again.json()["error"]["code"] == "GAME_COMPLETED"


@pytest.mark.anyio
async def test_profile_settings_can_be_updated(client: AsyncClient) -> None:
    headers = await login(client)

    response = await client.patch(
        "/api/v1/me/settings",
        headers=headers,
        json={"sound_enabled": False, "vibration_enabled": True},
    )

    assert response.status_code == 200
    assert response.json()["sound_enabled"] is False
    assert response.json()["vibration_enabled"] is True
