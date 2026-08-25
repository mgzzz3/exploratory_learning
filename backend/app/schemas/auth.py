from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WechatLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=256)

    @field_validator("code")
    @classmethod
    def strip_code(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("登录凭证不能为空")
        return value


class AuthUser(BaseModel):
    id: str
    nickname: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: AuthUser
