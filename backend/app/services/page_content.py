from __future__ import annotations

import re
from dataclasses import dataclass

from app.clients.tavily import PageUnreadableError


HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
TOKEN_PATTERN = re.compile(r"[\w\-]+", re.UNICODE)


@dataclass(frozen=True)
class PageContext:
    url: str
    title: str
    section_index: list[str]
    selected_content: str
    total_page_chars: int
    context_chars: int


@dataclass(frozen=True)
class _Section:
    title: str
    content: str
    position: int


class PageContentWorkspace:
    def __init__(self, *, page_char_limit: int, context_char_limit: int) -> None:
        self._page_char_limit = page_char_limit
        self._context_char_limit = context_char_limit
        self._retained_pages: dict[str, str] = {}

    @property
    def retained_chars(self) -> int:
        return sum(len(content) for content in self._retained_pages.values())

    def add(
        self,
        *,
        url: str,
        title: str,
        raw_content: str,
        relevance_query: str | None = None,
    ) -> PageContext:
        if not raw_content.strip():
            raise PageUnreadableError("网页没有可读取正文", reason="PAGE_EMPTY")
        if len(raw_content) > self._page_char_limit:
            raise PageUnreadableError("网页正文过大，超过处理预算", reason="PAGE_TOO_LARGE")

        sections = _split_sections(raw_content, self._context_char_limit)
        section_index = list(dict.fromkeys(section.title for section in sections))
        index_text = "\n".join(f"- {item}" for item in section_index)
        if len(index_text) >= self._context_char_limit:
            raise PageUnreadableError("网页章节索引过大，无法安全处理")

        available_chars = self._context_char_limit - len(index_text)
        selected = _select_sections(
            sections,
            available_chars=available_chars,
            relevance_query=relevance_query,
        )
        selected_content = "\n\n".join(
            f"## {section.title}\n{section.content}" for section in selected
        )
        context_chars = len(index_text) + len(selected_content)
        if context_chars > self._context_char_limit:
            raise PageUnreadableError("网页上下文超过处理预算")

        self._retained_pages[url] = raw_content
        return PageContext(
            url=url,
            title=title,
            section_index=section_index,
            selected_content=selected_content,
            total_page_chars=len(raw_content),
            context_chars=context_chars,
        )

    def close(self) -> None:
        self._retained_pages.clear()

    def __enter__(self) -> PageContentWorkspace:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _split_sections(content: str, context_char_limit: int) -> list[_Section]:
    raw_sections: list[tuple[str, str]] = []
    current_title = "正文"
    current_lines: list[str] = []

    def flush() -> None:
        body = "\n".join(current_lines).strip()
        if body:
            raw_sections.append((current_title, body))

    for line in content.splitlines():
        heading = HEADING_PATTERN.match(line)
        if heading:
            flush()
            current_title = heading.group(2).strip()[:120] or "未命名章节"
            current_lines = []
        else:
            current_lines.append(line)
    flush()

    if not raw_sections:
        raw_sections = [("正文", content.strip())]

    max_chunk_chars = max(32, min(6_000, context_char_limit // 2))
    sections: list[_Section] = []
    position = 0
    for title, body in raw_sections:
        for chunk in _split_body(body, max_chunk_chars):
            sections.append(_Section(title=title, content=chunk, position=position))
            position += 1
    return sections


def _split_body(body: str, max_chars: int) -> list[str]:
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", body) if item.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        pieces = [
            paragraph[index : index + max_chars]
            for index in range(0, len(paragraph), max_chars)
        ] or [paragraph]
        for piece in pieces:
            candidate = f"{current}\n\n{piece}".strip() if current else piece
            if current and len(candidate) > max_chars:
                chunks.append(current)
                current = piece
            else:
                current = candidate
    if current:
        chunks.append(current)
    return chunks


def _select_sections(
    sections: list[_Section],
    *,
    available_chars: int,
    relevance_query: str | None,
) -> list[_Section]:
    if not sections:
        raise PageUnreadableError("网页无法形成可读章节")

    if relevance_query:
        tokens = [item.lower() for item in TOKEN_PATTERN.findall(relevance_query)]

        def score(section: _Section) -> tuple[int, int]:
            haystack = f"{section.title}\n{section.content}".lower()
            relevance = sum(haystack.count(token) for token in tokens)
            return (-relevance, section.position)

        candidates = sorted(sections, key=score)
    else:
        candidates = _structural_order(sections)

    selected: list[_Section] = []
    used_chars = 0
    for section in candidates:
        rendered_chars = len(section.title) + len(section.content) + 5
        separator_chars = 2 if selected else 0
        if used_chars + separator_chars + rendered_chars > available_chars:
            continue
        selected.append(section)
        used_chars += separator_chars + rendered_chars

    if not selected:
        raise PageUnreadableError("网页正文无法放入模型上下文预算")
    return sorted(selected, key=lambda item: item.position)


def _structural_order(sections: list[_Section]) -> list[_Section]:
    if len(sections) <= 2:
        return sections
    order: list[int] = [0, len(sections) - 1]
    left = 1
    right = len(sections) - 2
    while left <= right:
        middle = (left + right) // 2
        order.append(middle)
        left = middle + 1
        if left <= right:
            order.append(left)
            left += 1
    order.extend(index for index in range(len(sections)) if index not in order)
    return [sections[index] for index in order]
