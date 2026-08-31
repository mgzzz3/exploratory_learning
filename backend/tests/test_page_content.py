from __future__ import annotations

import pytest

from app.clients.tavily import PageUnreadableError
from app.services.page_content import PageContentWorkspace


def test_markdown_headings_and_paragraphs_build_a_section_index() -> None:
    workspace = PageContentWorkspace(page_char_limit=120_000, context_char_limit=40_000)
    context = workspace.add(
        url="https://example.com/guide",
        title="指南",
        raw_content=(
            "# 总览\n\n总览内容。\n\n"
            "## 环境\n\n环境与约束。\n\n"
            "## 反馈回路\n\n反馈回路与验证。"
        ),
    )

    assert context.section_index == ["总览", "环境", "反馈回路"]
    assert "环境与约束" in context.selected_content
    assert "反馈回路与验证" in context.selected_content


def test_page_over_processing_limit_fails_closed() -> None:
    workspace = PageContentWorkspace(page_char_limit=100, context_char_limit=80)

    with pytest.raises(PageUnreadableError, match="过大"):
        workspace.add(
            url="https://example.com/huge",
            title="超大页面",
            raw_content="x" * 101,
        )


def test_relevant_section_can_be_selected_from_end_without_prefix_truncation() -> None:
    sections = [
        f"## 第 {index} 章\n\n" + (f"普通内容 {index}。" * 700)
        for index in range(1, 9)
    ]
    sections.append("## 最终结论\n\nUNIQUE-FEEDBACK-LOOP 是最重要的结论。")
    workspace = PageContentWorkspace(page_char_limit=120_000, context_char_limit=8_000)

    context = workspace.add(
        url="https://example.com/long",
        title="长文",
        raw_content="\n\n".join(sections),
        relevance_query="UNIQUE-FEEDBACK-LOOP",
    )

    assert context.context_chars <= 8_000
    assert "UNIQUE-FEEDBACK-LOOP" in context.selected_content
    assert "最终结论" in context.section_index


def test_long_page_without_query_samples_structure_including_last_section() -> None:
    content = "\n\n".join(
        f"## Section {index}\n\n" + (f"content-{index} " * 500)
        for index in range(1, 8)
    )
    workspace = PageContentWorkspace(page_char_limit=120_000, context_char_limit=12_000)

    context = workspace.add(
        url="https://example.com/structured",
        title="Structured",
        raw_content=content,
    )

    assert context.context_chars <= 12_000
    assert "Section 1" in context.selected_content
    assert "Section 7" in context.selected_content


def test_workspace_releases_retained_page_content() -> None:
    workspace = PageContentWorkspace(page_char_limit=120_000, context_char_limit=40_000)
    workspace.add(
        url="https://example.com/guide",
        title="指南",
        raw_content="# 标题\n\n临时正文",
    )
    assert workspace.retained_chars > 0

    workspace.close()

    assert workspace.retained_chars == 0


@pytest.mark.parametrize("content,reason", [("", "PAGE_EMPTY"), ("x" * 101, "PAGE_TOO_LARGE")])
def test_workspace_preserves_page_failure_reason(content, reason):
    workspace = PageContentWorkspace(page_char_limit=100, context_char_limit=80)
    with pytest.raises(PageUnreadableError) as caught:
        workspace.add(url="https://example.com", title="页面", raw_content=content)
    assert caught.value.reason == reason
