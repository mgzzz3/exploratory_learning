from __future__ import annotations

from datetime import timedelta
import json
import time
from uuid import uuid4

import jwt
import pytest

from app.core.errors import AppError
from app.core.security import create_access_token, decode_access_token, InvalidTokenError
from app.services.generation_errors import public_generation_error
from app.clients.ai import ContentGenerationError


SECRET = "offline-permit-secret-at-least-32-characters"


def service(mode="grounded", secret=SECRET):
    from app.services.basic_permits import FallbackPermits
    return FallbackPermits(secret=secret, mode=mode)


def issue(permits=None, **kwargs):
    return (permits or service()).issue(
        user_id=kwargs.pop("user_id", "private-user-id"), topic=kwargs.pop("topic", "高情商聊天"),
        request_id=kwargs.pop("request_id", uuid4().hex),
        error=kwargs.pop("error", public_generation_error(ContentGenerationError("offline"))), **kwargs,
    )


@pytest.mark.parametrize("topic,expected", [
    ("高情商聊天", True), ("  高情商聊天\n", True),
    ("高 情商聊天", False), ("高情商聊天技巧", False), ("最新高情商聊天", False),
    ("2026 高情商聊天", False), ("高情商聊天 v2", False), ("Python 基础", False),
    ("Harness Engineering", False), ("https://example.com", False),
    ("高情商聊天 https://example.com", False), ("高情商聊天 最新版", False),
    ("", False), ("x" * 81, False),
])
def test_only_complete_reviewed_topic_is_eligible(topic, expected):
    from app.services.basic_policy import eligible_topic
    assert eligible_topic(topic) is expected


@pytest.mark.parametrize("code,reason,expected", [
    ("SEARCH_UNAVAILABLE", "PROVIDER_AUTH_FAILED", True),
    ("SEARCH_UNAVAILABLE", "PROVIDER_RATE_LIMITED", True),
    ("SEARCH_UNAVAILABLE", "PROVIDER_NETWORK_ERROR", True),
    ("SEARCH_UNAVAILABLE", "PROVIDER_TIMEOUT", True),
    ("SEARCH_UNAVAILABLE", "PROVIDER_UNAVAILABLE", True),
    ("SEARCH_UNAVAILABLE", "PROVIDER_INVALID_RESPONSE", True),
    ("RESEARCH_AGENT_FAILED", "MODEL_BUDGET_EXHAUSTED", True),
    ("RESEARCH_AGENT_FAILED", "RESEARCH_TIMEOUT", True),
    ("RESEARCH_AGENT_FAILED", "INVALID_RESEARCH_OUTPUT", True),
    ("SOURCES_INSUFFICIENT", "INSUFFICIENT_EVIDENCE", True),
    ("AI_GENERATION_FAILED", "GENERATION_TIMEOUT", True),
    ("AI_GENERATION_FAILED", "VALIDATION_UNAVAILABLE", True),
    ("GROUNDING_VALIDATION_FAILED", "UNSUPPORTED_FACTS", True),
    ("TOPIC_AMBIGUOUS", "AMBIGUOUS_TOPIC", False),
    ("SOURCES_INSUFFICIENT", "CONFLICTING_EVIDENCE", False),
    ("SEARCH_UNAVAILABLE", "UNRECOGNIZED", False),
    ("UNAUTHORIZED", "UNAUTHORIZED", False), ("CONTENT_BLOCKED", "CONTENT_BLOCKED", False),
    ("WECHAT_UNAVAILABLE", "WECHAT_UNAVAILABLE", False),
    ("CANCELLED", "CANCELLED", False), ("PERSISTENCE_FAILED", "PERSISTENCE_FAILED", False),
    ("INVALID_SOURCE_URL", "INVALID_SOURCE_URL", False), ("UNKNOWN", "UNKNOWN", False),
])
def test_failure_allowlist_fails_closed(code, reason, expected):
    from app.services.basic_policy import eligible_failure
    assert eligible_failure(code, reason) is expected


def test_permit_has_required_claims_no_plain_identity_or_topic_and_fixed_five_minutes():
    permits = service()
    original_id = uuid4().hex
    fallback = issue(permits, request_id=original_id)
    assert fallback["available"] is True
    assert fallback["notice"] == "未经联网核验"
    raw = jwt.decode(fallback["token"], options={"verify_signature": False})
    assert raw["exp"] - raw["iat"] == 300
    assert raw["request_id"] == original_id
    assert raw["aud"] == "basic-knowledge-fallback"
    assert jwt.get_unverified_header(fallback["token"])["alg"] == "HS256"
    assert not any(value in json.dumps(raw, ensure_ascii=False) for value in ["高情商聊天", "private-user-id"])
    permit = permits.verify(fallback["token"], user_id="private-user-id", topic=" 高情商聊天 ")
    assert permit.parent_request_id == original_id
    assert permit.id != permits.verify(issue(permits)["token"], user_id="private-user-id", topic="高情商聊天").id


@pytest.mark.parametrize("case", ["user", "topic", "expired", "tampered", "legacy", "rotation", "login", "policy", "audience", "type", "algorithm", "missing_id", "missing_parent", "missing_iat", "missing_exp", "missing_user", "missing_topic", "future_iat", "long_expiry", "invalid_parent", "unknown_failure", "unicode_binding"])
def test_permit_rejects_invalid_bindings_claims_and_modes(case):
    permits = service()
    token = issue(permits)["token"]
    user_id, topic = "private-user-id", "高情商聊天"
    if case == "user": user_id = "another-user"
    elif case == "topic": topic = "Python 基础"
    elif case == "tampered": token = "x" + token
    elif case == "legacy": permits = service("legacy")
    elif case == "rotation": permits = service(secret="rotated-secret-at-least-32-characters")
    elif case == "login": token = create_access_token(subject=user_id, secret=SECRET, ttl=timedelta(minutes=5))
    else:
        raw = jwt.decode(token, options={"verify_signature": False})
        changes = {
            "expired": {"iat": int(time.time()) - 600, "exp": int(time.time()) - 300},
            "policy": {"policy_version": "unknown"}, "audience": {"aud": "access"},
            "type": {"type": "access"}, "future_iat": {"iat": int(time.time()) + 600},
            "long_expiry": {"exp": int(time.time()) + 900}, "invalid_parent": {"request_id": "client-chosen"},
            "unknown_failure": {"failure_reason": "UNRECOGNIZED"},
            "unicode_binding": {"user_binding": "无效绑定"},
        }
        if case.startswith("missing_"):
            key = {"missing_id": "jti", "missing_parent": "request_id", "missing_user": "user_binding", "missing_topic": "topic_binding"}.get(case, case.removeprefix("missing_"))
            raw.pop(key)
        else: raw.update(changes.get(case, {}))
        token = jwt.encode(raw, permits._signing_key * 2 if case == "algorithm" else permits._signing_key, algorithm="HS384" if case == "algorithm" else "HS256")
    with pytest.raises(AppError) as caught:
        permits.verify(token, user_id=user_id, topic=topic)
    assert caught.value.code == "BASIC_MODE_NOT_ALLOWED"
    assert caught.value.status_code == 403
    assert caught.value.details["reason"] in {"PERMIT_INVALID", "PERMIT_EXPIRED", "TOPIC_NOT_ELIGIBLE", "BASIC_MODE_DISABLED"}


def test_permit_is_not_login_token_and_issue_requires_pipeline_failure():
    token = issue()["token"]
    with pytest.raises(InvalidTokenError):
        decode_access_token(token, SECRET)
    assert issue(service("legacy")) == {"available": False}
    assert issue(topic="Harness Engineering") == {"available": False}
    assert issue(error=AppError(status_code=502, code="AI_GENERATION_FAILED", message="non-pipeline error", details={"reason": "GENERATION_UNAVAILABLE"})) == {"available": False}
