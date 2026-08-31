from __future__ import annotations

import hashlib
import hmac
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import jwt

from app.core.errors import AppError
from app.schemas.learning_input import classify_learning_input
from app.services.basic_policy import NOTICE, POLICY_VERSION, eligible_topic, eligible_failure
from app.services.generation_errors import GenerationPipelineError


AUDIENCE = "basic-knowledge-fallback"
TOKEN_TYPE = "basic-fallback"
TTL_SECONDS = 300
RANDOM_ID = re.compile(r"^[0-9a-f]{32}$")
REQUIRED_CLAIMS = ["jti", "request_id", "iat", "exp", "aud", "type", "user_binding", "topic_binding", "policy_version", "failure_code", "failure_reason"]


def not_allowed(reason: str) -> AppError:
    return AppError(status_code=403, code="BASIC_MODE_NOT_ALLOWED", message="基础知识许可无效或已过期，请重新联网尝试", details={"reason": reason})


@dataclass(frozen=True, repr=False)
class BasicPermit:
    id: str
    parent_request_id: str


class FallbackPermits:
    def __init__(self, *, secret: str, mode: str) -> None:
        if len(secret) < 32:
            raise ValueError("许可签名需要强 JWT secret")
        self.mode = mode
        self._signing_key = hmac.digest(secret.encode(), b"basic-fallback/signature/v1", "sha256")
        self._binding_key = hmac.digest(secret.encode(), b"basic-fallback/binding/v1", "sha256")

    def _bind(self, purpose: str, value: str) -> str:
        return hmac.new(self._binding_key, (purpose + "\0" + value).encode(), hashlib.sha256).hexdigest()

    def issue(self, *, user_id: str, topic: str, request_id: str, error: AppError) -> dict:
        unavailable = {"available": False}
        if self.mode != "grounded" or not eligible_topic(topic) or not isinstance(error, GenerationPipelineError):
            return unavailable
        reason = (error.details or {}).get("reason", "")
        if not eligible_failure(error.code, reason) or not RANDOM_ID.fullmatch(request_id):
            return unavailable
        now = int(time.time())
        payload = {
            "jti": uuid4().hex, "request_id": request_id,
            "iat": now, "exp": now + TTL_SECONDS, "aud": AUDIENCE, "type": TOKEN_TYPE,
            "user_binding": self._bind("user", user_id),
            "topic_binding": self._bind("topic", classify_learning_input(topic).normalized_input),
            "policy_version": POLICY_VERSION, "failure_code": error.code, "failure_reason": reason,
        }
        return {
            "available": True, "mode": "basic", "notice": NOTICE,
            "token": jwt.encode(payload, self._signing_key, algorithm="HS256"),
            "expires_at": datetime.fromtimestamp(payload["exp"], UTC).isoformat(),
        }

    def verify(self, token: str, *, user_id: str, topic: str) -> BasicPermit:
        if self.mode != "grounded":
            raise not_allowed("BASIC_MODE_DISABLED")
        failure = None
        try:
            claims = jwt.decode(token, self._signing_key, algorithms=["HS256"], audience=AUDIENCE, options={"require": REQUIRED_CLAIMS, "strict_aud": True})
        except jwt.ExpiredSignatureError:
            failure = not_allowed("PERMIT_EXPIRED")
        except jwt.PyJWTError:
            failure = not_allowed("PERMIT_INVALID")
        if failure:
            raise failure from None
        if (
            claims["type"] != TOKEN_TYPE or claims["policy_version"] != POLICY_VERSION
            or type(claims["iat"]) is not int or type(claims["exp"]) is not int
            or not 0 < claims["exp"] - claims["iat"] <= TTL_SECONDS
            or not all(isinstance(claims[key], str) for key in REQUIRED_CLAIMS if key not in {"iat", "exp"})
        ):
            raise not_allowed("PERMIT_INVALID")
        if (
            not all(RANDOM_ID.fullmatch(claims[key]) for key in ("jti", "request_id"))
            or not all(re.fullmatch(r"[0-9a-f]{64}", claims[key]) for key in ("user_binding", "topic_binding"))
            or not eligible_failure(claims["failure_code"], claims["failure_reason"])
        ):
            raise not_allowed("PERMIT_INVALID")
        if not eligible_topic(topic):
            raise not_allowed("TOPIC_NOT_ELIGIBLE")
        normalized = classify_learning_input(topic).normalized_input
        if not hmac.compare_digest(claims["user_binding"], self._bind("user", user_id)) or not hmac.compare_digest(claims["topic_binding"], self._bind("topic", normalized)):
            raise not_allowed("PERMIT_INVALID")
        return BasicPermit(claims["jti"], claims["request_id"])
