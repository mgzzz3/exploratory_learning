from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.errors import AppError
from app.db.models import BattleParticipant, BattleRoom, User
from app.services.battle import set_battle_ready

from .conftest import login
from .fakes import FakeContentGenerator, FakeWechatClient


BATTLE_PREFIX = "/api/v1/battles"


async def wait_for_room_status(
    client: AsyncClient,
    headers: dict[str, str],
    room_id: str,
    status: str,
) -> dict:
    for _ in range(500):
        response = await client.get(f"{BATTLE_PREFIX}/{room_id}", headers=headers)
        assert response.status_code == 200, response.text
        room = response.json()
        if room["status"] == status:
            return room
        await asyncio.sleep(0.01)
    raise AssertionError(f"room did not reach status {status}")


async def create_ready_battle(
    client: AsyncClient,
    *,
    topic: str = "Python 基础",
) -> tuple[dict, dict[str, str], dict[str, str]]:
    host = await login(client, "host")
    challenger = await login(client, "challenger")
    created = await client.post(
        BATTLE_PREFIX,
        headers=host,
        json={"topic": topic},
    )
    assert created.status_code == 201, created.text
    room_id = created.json()["id"]
    room = await wait_for_room_status(client, host, room_id, "waiting")
    joined = await client.post(f"{BATTLE_PREFIX}/{room_id}/join", headers=challenger)
    assert joined.status_code == 200, joined.text
    await client.post(f"{BATTLE_PREFIX}/{room_id}/ready", headers=host)
    playing = await client.post(
        f"{BATTLE_PREFIX}/{room_id}/ready",
        headers=challenger,
    )
    assert playing.status_code == 200, playing.text
    assert playing.json()["status"] == "playing"
    return playing.json(), host, challenger


async def answer_all(
    client: AsyncClient,
    headers: dict[str, str],
    room_id: str,
    option: int = 0,
) -> list[dict]:
    responses = []
    for _ in range(3):
        response = await client.post(
            f"{BATTLE_PREFIX}/{room_id}/answers",
            headers=headers,
            json={"option": option, "attempt_id": str(uuid4())},
        )
        assert response.status_code == 200, response.text
        responses.append(response.json())
    return responses


async def force_expiry(engine: AsyncEngine, room_id: str) -> None:
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as db:
        await db.execute(
            update(BattleRoom)
            .where(BattleRoom.id == room_id)
            .values(expires_at=BattleRoom.started_at)
        )
        await db.commit()


@pytest.mark.anyio
async def test_battle_requires_authentication(client: AsyncClient) -> None:
    response = await client.get(f"{BATTLE_PREFIX}/missing")

    assert response.status_code == 401


@pytest.mark.anyio
async def test_battle_missing_room_returns_stable_404(
    client: AsyncClient,
) -> None:
    headers = await login(client, "host")

    response = await client.get(f"{BATTLE_PREFIX}/missing", headers=headers)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "BATTLE_NOT_FOUND"


@pytest.mark.anyio
async def test_battle_lifecycle_from_generation_to_settlement(
    client: AsyncClient,
) -> None:
    playing, host, challenger = await create_ready_battle(client)
    room_id = playing["id"]

    assert playing["started_at"] is not None
    assert playing["question"]["position"] == 0
    assert "correct_option" not in str(playing)

    host_answers = await answer_all(client, host, room_id, option=0)
    challenger_answers = await answer_all(client, challenger, room_id, option=1)
    assert [item["result"] for item in host_answers] == [
        "correct",
        "correct",
        "completed",
    ]
    assert [item["result"] for item in challenger_answers] == [
        "wrong",
        "wrong",
        "completed",
    ]

    settled = await client.get(f"{BATTLE_PREFIX}/{room_id}", headers=host)
    assert settled.status_code == 200
    assert settled.json()["status"] == "finished"

    host_result = await client.get(f"{BATTLE_PREFIX}/{room_id}/result", headers=host)
    challenger_result = await client.get(
        f"{BATTLE_PREFIX}/{room_id}/result",
        headers=challenger,
    )
    assert host_result.status_code == 200
    assert challenger_result.status_code == 200
    assert host_result.json()["my_result"] == "win"
    assert host_result.json()["opponent_result"] == "lose"
    assert challenger_result.json()["my_result"] == "lose"
    assert len(host_result.json()["review"]) == 3
    assert all(item["is_correct"] for item in host_result.json()["review"])
    assert all(not item["is_correct"] for item in challenger_result.json()["review"])


@pytest.mark.anyio
async def test_battle_generation_failure_marks_room_error(
    client: AsyncClient,
    generator: FakeContentGenerator,
) -> None:
    generator.error = True
    headers = await login(client, "host")
    created = await client.post(
        BATTLE_PREFIX,
        headers=headers,
        json={"topic": "咖啡拉花"},
    )
    assert created.status_code == 201
    room = await wait_for_room_status(client, headers, created.json()["id"], "error")

    assert room["error_message"] is not None

    join_response = await client.post(
        f"{BATTLE_PREFIX}/{room['id']}/join",
        headers=await login(client, "challenger"),
    )
    assert join_response.status_code == 409
    assert join_response.json()["error"]["code"] == "BATTLE_NOT_JOINABLE"


@pytest.mark.anyio
async def test_battle_join_rules(
    client: AsyncClient,
) -> None:
    host = await login(client, "host")
    challenger = await login(client, "challenger")
    created = await client.post(BATTLE_PREFIX, headers=host, json={"topic": "理财"})
    room_id = created.json()["id"]

    self_join = await client.post(f"{BATTLE_PREFIX}/{room_id}/join", headers=host)
    assert self_join.status_code == 409
    assert self_join.json()["error"]["code"] == "BATTLE_SELF_JOIN"

    await wait_for_room_status(client, host, room_id, "waiting")
    joined = await client.post(f"{BATTLE_PREFIX}/{room_id}/join", headers=challenger)
    assert joined.status_code == 200
    rejoin = await client.post(f"{BATTLE_PREFIX}/{room_id}/join", headers=challenger)
    assert rejoin.status_code == 200

    third = await login(client, "third")
    full = await client.post(f"{BATTLE_PREFIX}/{room_id}/join", headers=third)
    assert full.status_code == 409
    assert full.json()["error"]["code"] == "BATTLE_FULL"


@pytest.mark.anyio
async def test_battle_ready_starts_once_and_keeps_signal(
    client: AsyncClient,
) -> None:
    host = await login(client, "host")
    created = await client.post(BATTLE_PREFIX, headers=host, json={"topic": "理财"})
    room_id = created.json()["id"]
    await wait_for_room_status(client, host, room_id, "waiting")
    challenger = await login(client, "challenger")
    await client.post(f"{BATTLE_PREFIX}/{room_id}/join", headers=challenger)
    await client.post(f"{BATTLE_PREFIX}/{room_id}/ready", headers=host)
    first_start = await client.post(
        f"{BATTLE_PREFIX}/{room_id}/ready",
        headers=challenger,
    )
    assert first_start.json()["status"] == "playing"
    started_at = first_start.json()["started_at"]

    repeat_ready = await client.post(
        f"{BATTLE_PREFIX}/{room_id}/ready",
        headers=challenger,
    )
    assert repeat_ready.status_code == 200
    assert repeat_ready.json()["started_at"] == started_at


@pytest.mark.anyio
async def test_battle_ready_rejected_while_generating(
    client: AsyncClient,
    engine: AsyncEngine,
) -> None:
    headers = await login(client, "host")
    profile = await client.get("/api/v1/me", headers=headers)
    user_id = profile.json()["id"]
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as db:
        room = BattleRoom(host_user_id=user_id, topic="理财")
        db.add(room)
        await db.flush()
        db.add(
            BattleParticipant(
                room_id=room.id,
                user_id=user_id,
                role="host",
            )
        )
        await db.commit()
        user = await db.get(User, user_id)
        with pytest.raises(AppError) as exc_info:
            await set_battle_ready(db, room_id=room.id, user=user)

        assert exc_info.value.code == "BATTLE_NOT_READY"


@pytest.mark.anyio
async def test_battle_question_hidden_before_both_ready(
    client: AsyncClient,
) -> None:
    host = await login(client, "host")
    created = await client.post(BATTLE_PREFIX, headers=host, json={"topic": "理财"})
    room_id = created.json()["id"]
    await wait_for_room_status(client, host, room_id, "waiting")
    challenger = await login(client, "challenger")
    await client.post(f"{BATTLE_PREFIX}/{room_id}/join", headers=challenger)

    await client.post(f"{BATTLE_PREFIX}/{room_id}/ready", headers=host)
    room = await client.get(f"{BATTLE_PREFIX}/{room_id}", headers=host)

    assert room.json()["status"] == "waiting"
    assert room.json()["question"] is None


@pytest.mark.anyio
async def test_battle_answer_is_idempotent_per_attempt(client: AsyncClient) -> None:
    playing, host, _ = await create_ready_battle(client)
    room_id = playing["id"]
    attempt_id = str(uuid4())

    first = await client.post(
        f"{BATTLE_PREFIX}/{room_id}/answers",
        headers=host,
        json={"option": 0, "attempt_id": attempt_id},
    )
    assert first.status_code == 200
    assert first.json()["result"] == "correct"
    assert first.json()["question"]["position"] == 1

    retry = await client.post(
        f"{BATTLE_PREFIX}/{room_id}/answers",
        headers=host,
        json={"option": 2, "attempt_id": attempt_id},
    )
    assert retry.status_code == 200
    assert retry.json()["result"] == "correct"
    assert retry.json()["question"]["position"] == 1

    conflict = await client.post(
        f"{BATTLE_PREFIX}/{room_id}/answers",
        headers=await login(client, "challenger"),
        json={"option": 0, "attempt_id": attempt_id},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "BATTLE_ATTEMPT_CONFLICT"


@pytest.mark.anyio
async def test_battle_rejects_answers_after_completion(client: AsyncClient) -> None:
    playing, host, _ = await create_ready_battle(client)
    room_id = playing["id"]
    await answer_all(client, host, room_id)

    extra = await client.post(
        f"{BATTLE_PREFIX}/{room_id}/answers",
        headers=host,
        json={"option": 0, "attempt_id": str(uuid4())},
    )

    assert extra.status_code == 409
    assert extra.json()["error"]["code"] == "BATTLE_ALREADY_ANSWERED"


@pytest.mark.anyio
async def test_battle_result_rejected_before_settlement(client: AsyncClient) -> None:
    playing, host, _ = await create_ready_battle(client)
    room_id = playing["id"]
    await answer_all(client, host, room_id)

    response = await client.get(f"{BATTLE_PREFIX}/{room_id}/result", headers=host)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "BATTLE_NOT_SETTLED"


@pytest.mark.anyio
async def test_battle_settlement_prefers_correct_count(client: AsyncClient) -> None:
    playing, host, challenger = await create_ready_battle(client)
    room_id = playing["id"]

    await answer_all(client, host, room_id, option=0)
    await answer_all(client, challenger, room_id, option=1)

    host_result = await client.get(f"{BATTLE_PREFIX}/{room_id}/result", headers=host)
    assert host_result.json()["my_correct_count"] == 3
    assert host_result.json()["opponent_correct_count"] == 0
    assert host_result.json()["my_result"] == "win"


@pytest.mark.anyio
async def test_battle_settlement_breaks_tie_by_time(
    client: AsyncClient,
    engine: AsyncEngine,
) -> None:
    playing, host, challenger = await create_ready_battle(client)
    room_id = playing["id"]
    await answer_all(client, host, room_id, option=0)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as db:
        await db.execute(
            update(BattleParticipant)
            .where(BattleParticipant.room_id == room_id)
            .values(total_seconds=10)
        )
        await db.commit()

    await answer_all(client, challenger, room_id, option=0)

    challenger_result = await client.get(
        f"{BATTLE_PREFIX}/{room_id}/result",
        headers=challenger,
    )
    assert challenger_result.json()["my_result"] == "win"
    assert challenger_result.json()["my_total_seconds"] < 10


@pytest.mark.anyio
async def test_battle_settlement_declares_draw_on_exact_tie(
    client: AsyncClient,
) -> None:
    playing, host, challenger = await create_ready_battle(client)
    room_id = playing["id"]

    await answer_all(client, host, room_id, option=0)
    await answer_all(client, challenger, room_id, option=0)

    host_result = await client.get(f"{BATTLE_PREFIX}/{room_id}/result", headers=host)
    assert host_result.json()["my_result"] == "draw"
    assert host_result.json()["opponent_result"] == "draw"


@pytest.mark.anyio
async def test_battle_timeout_prefers_finished_player(
    client: AsyncClient,
    engine: AsyncEngine,
) -> None:
    playing, host, challenger = await create_ready_battle(client)
    room_id = playing["id"]
    await answer_all(client, host, room_id, option=0)
    partial = await client.post(
        f"{BATTLE_PREFIX}/{room_id}/answers",
        headers=challenger,
        json={"option": 0, "attempt_id": str(uuid4())},
    )
    assert partial.status_code == 200
    await force_expiry(engine, room_id)

    settled = await client.get(f"{BATTLE_PREFIX}/{room_id}", headers=host)
    assert settled.json()["status"] == "finished"

    challenger_result = await client.get(
        f"{BATTLE_PREFIX}/{room_id}/result",
        headers=challenger,
    )
    assert challenger_result.status_code == 200
    assert challenger_result.json()["my_result"] == "lose"
    assert challenger_result.json()["review"] == []


@pytest.mark.anyio
async def test_battle_timeout_voids_room_without_any_answers(
    client: AsyncClient,
    engine: AsyncEngine,
) -> None:
    playing, host, challenger = await create_ready_battle(client)
    room_id = playing["id"]
    await force_expiry(engine, room_id)

    settled = await client.get(f"{BATTLE_PREFIX}/{room_id}", headers=host)
    assert settled.json()["status"] == "void"

    result = await client.get(f"{BATTLE_PREFIX}/{room_id}/result", headers=challenger)
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "BATTLE_EXPIRED"


@pytest.mark.anyio
async def test_battle_waiting_expiry_voids_room(client: AsyncClient, engine: AsyncEngine) -> None:
    host = await login(client, "host")
    created = await client.post(BATTLE_PREFIX, headers=host, json={"topic": "理财"})
    room_id = created.json()["id"]
    await wait_for_room_status(client, host, room_id, "waiting")

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as db:
        room = await db.get(BattleRoom, room_id)
        assert room is not None
        room.expires_at = room.expires_at.replace(year=2000)
        await db.commit()

    voided = await client.get(f"{BATTLE_PREFIX}/{room_id}", headers=host)
    assert voided.json()["status"] == "void"

    join = await client.post(
        f"{BATTLE_PREFIX}/{room_id}/join",
        headers=await login(client, "challenger"),
    )
    assert join.status_code == 409
    assert join.json()["error"]["code"] == "BATTLE_EXPIRED"


@pytest.mark.anyio
async def test_battle_responses_never_leak_correct_option_before_settlement(
    client: AsyncClient,
) -> None:
    playing, host, challenger = await create_ready_battle(client)
    room_id = playing["id"]

    room = await client.get(f"{BATTLE_PREFIX}/{room_id}", headers=host)
    answer = await client.post(
        f"{BATTLE_PREFIX}/{room_id}/answers",
        headers=host,
        json={"option": 0, "attempt_id": str(uuid4())},
    )
    assert "correct_option" not in room.text
    assert "correct" not in str(answer.json()["question"])

    result = await client.get(f"{BATTLE_PREFIX}/{room_id}/result", headers=challenger)
    assert result.status_code == 409
