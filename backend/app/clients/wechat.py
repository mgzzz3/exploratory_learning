from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

import httpx


class WechatClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class WechatSession:
    openid: str
    unionid: str | None = None


class WechatClient(Protocol):
    async def code_to_session(self, code: str) -> WechatSession: ...

    async def check_message(self, openid: str, content: str) -> bool: ...


class WechatApiClient:
    def __init__(self, *, app_id: str, app_secret: str, base_url: str) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.base_url = base_url.rstrip("/")
        self._access_token: str | None = None
        self._access_token_expires_at = datetime.min.replace(tzinfo=timezone.utc)

    async def code_to_session(self, code: str) -> WechatSession:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{self.base_url}/sns/jscode2session",
                params={
                    "appid": self.app_id,
                    "secret": self.app_secret,
                    "js_code": code,
                    "grant_type": "authorization_code",
                },
            )
        try:
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise WechatClientError("微信登录服务连接失败") from exc
        if payload.get("errcode") or not payload.get("openid"):
            raise WechatClientError(payload.get("errmsg", "微信登录失败"))
        return WechatSession(
            openid=payload["openid"],
            unionid=payload.get("unionid"),
        )

    async def _get_access_token(self) -> str:
        now = datetime.now(timezone.utc)
        if self._access_token and now < self._access_token_expires_at:
            return self._access_token
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self.base_url}/cgi-bin/stable_token",
                json={
                    "grant_type": "client_credential",
                    "appid": self.app_id,
                    "secret": self.app_secret,
                    "force_refresh": False,
                },
            )
        try:
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise WechatClientError("微信内容安全服务连接失败") from exc
        access_token = payload.get("access_token")
        if not access_token:
            raise WechatClientError(payload.get("errmsg", "获取微信 access_token 失败"))
        expires_in = int(payload.get("expires_in", 7200))
        self._access_token = access_token
        self._access_token_expires_at = now + timedelta(seconds=max(60, expires_in - 300))
        return access_token

    async def check_message(self, openid: str, content: str) -> bool:
        access_token = await self._get_access_token()
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self.base_url}/wxa/msg_sec_check",
                params={"access_token": access_token},
                json={
                    "content": content,
                    "version": 2,
                    "scene": 3,
                    "openid": openid,
                },
            )
        try:
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise WechatClientError("微信内容安全服务连接失败") from exc
        if payload.get("errcode", 0) != 0:
            raise WechatClientError(payload.get("errmsg", "微信内容安全检查失败"))
        return payload.get("result", {}).get("suggest") == "pass"


class LocalWechatClient:
    _blocked_words = {"赌博", "毒品", "色情", "诈骗", "暴力教程"}

    async def code_to_session(self, code: str) -> WechatSession:
        digest = hashlib.sha256(code.encode("utf-8")).hexdigest()[:24]
        return WechatSession(openid=f"local-{digest}")

    async def check_message(self, openid: str, content: str) -> bool:
        del openid
        return not any(word in content for word in self._blocked_words)
