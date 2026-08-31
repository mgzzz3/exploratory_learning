from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field


InputType = Literal["keyword", "url"]


class InputDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_type: InputType
    original_input: str = Field(min_length=1, max_length=2048)
    normalized_input: str = Field(min_length=1, max_length=2048)
    display_topic: str = Field(min_length=1, max_length=80)


def _is_complete_http_url(value: str) -> bool:
    if any(character.isspace() for character in value):
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme.lower() in {"http", "https"} and bool(parsed.hostname)
    except ValueError:
        return False


def classify_learning_input(value: str) -> InputDescriptor:
    original = value.strip()
    if not original:
        raise ValueError("学习主题不能为空")

    if _is_complete_http_url(original):
        if len(original) > 2048:
            raise ValueError("网页 URL 最长 2048 个字符")
        hostname = urlsplit(original).hostname
        if hostname is None:
            raise ValueError("网页 URL 缺少站点域名")
        return InputDescriptor(
            input_type="url",
            original_input=original,
            normalized_input=original,
            display_topic=hostname[:80],
        )

    keyword = " ".join(original.split())
    if len(keyword) > 80:
        raise ValueError("知识关键词最长 80 个字符")
    return InputDescriptor(
        input_type="keyword",
        original_input=original,
        normalized_input=keyword,
        display_topic=keyword,
    )
