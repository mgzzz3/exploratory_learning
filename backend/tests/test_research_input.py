from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.game import GameCreateRequest
from app.schemas.research import InputDescriptor, classify_learning_input


@pytest.mark.parametrize(
    "topic",
    [
        "Harness Engineering",
        "Python 3.11 pathlib.Path",
        "example.com 的 DNS 是怎么工作的",
    ],
)
def test_plain_and_dotted_terms_are_keywords(topic: str) -> None:
    descriptor = classify_learning_input(topic)

    assert descriptor == InputDescriptor(
        input_type="keyword",
        original_input=topic,
        normalized_input=topic,
        display_topic=topic,
    )


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_complete_http_url_is_url_input(scheme: str) -> None:
    topic = f"{scheme}://example.com/articles/new-knowledge?lang=zh"

    descriptor = classify_learning_input(topic)

    assert descriptor.input_type == "url"
    assert descriptor.original_input == topic
    assert descriptor.normalized_input == topic
    assert descriptor.display_topic == "example.com"


def test_keyword_and_url_length_boundaries_are_mode_specific() -> None:
    assert classify_learning_input("知" * 80).input_type == "keyword"
    with pytest.raises(ValueError, match="80"):
        classify_learning_input("知" * 81)

    prefix = "https://example.com/"
    longest_url = prefix + "a" * (2048 - len(prefix))
    assert len(longest_url) == 2048
    assert classify_learning_input(longest_url).input_type == "url"
    with pytest.raises(ValueError, match="2048"):
        classify_learning_input(longest_url + "a")


@pytest.mark.parametrize(
    "topic",
    [
        "https://a.test https://b.test",
        "阅读这个页面 https://example.com/article",
    ],
)
def test_multiple_or_mixed_urls_are_not_single_url_mode(topic: str) -> None:
    descriptor = classify_learning_input(topic)

    assert descriptor.input_type == "keyword"
    assert descriptor.normalized_input == topic


def test_game_create_request_accepts_long_single_url_but_rejects_long_keyword() -> None:
    url = "https://example.com/" + "a" * 100

    assert GameCreateRequest(topic=url).topic == url
    with pytest.raises(ValidationError):
        GameCreateRequest(topic="知" * 81)
