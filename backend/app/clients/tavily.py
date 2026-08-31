from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal, Protocol, TypeVar
from urllib.parse import urlsplit

import aiohttp
import httpx
from langchain_core.tools import ToolException
from langchain_tavily import TavilyExtract, TavilySearch
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from app.schemas.research import ExtractedPage, SearchResult
from app.services.url_safety import InvalidSourceUrlError, normalize_public_url


class TavilyToolError(RuntimeError):
    code = "SEARCH_UNAVAILABLE"
    reason = "PROVIDER_INVALID_RESPONSE"

    def __init__(self, message: str, *, reason: str | None = None) -> None:
        super().__init__(message)
        if reason is not None:
            self.reason = reason


class TavilyAuthenticationError(TavilyToolError):
    reason = "PROVIDER_AUTH_FAILED"


class TavilyParameterError(TavilyToolError):
    reason = "PROVIDER_INVALID_REQUEST"


class TavilyRateLimitError(TavilyToolError):
    reason = "PROVIDER_RATE_LIMITED"


class TavilyUnavailableError(TavilyToolError):
    reason = "PROVIDER_UNAVAILABLE"


class TavilyResponseError(TavilyToolError):
    pass


class PageUnreadableError(TavilyToolError):
    code = "PAGE_UNREADABLE"
    reason = "PAGE_EXTRACTION_FAILED"


class ToolWindowClosedError(RuntimeError):
    """The request's exploration window closed, not a provider failure."""


@dataclass
class TavilyCallContext:
    deadline: float | None = None
    clock: Callable[[], float] = field(default=time.monotonic, repr=False)
    sleep: Callable[[float], Awaitable[None]] = field(default=asyncio.sleep, repr=False)
    logical_calls: int = 0
    physical_requests: int = 0
    retries: int = 0

    def remaining(self) -> float | None:
        return None if self.deadline is None else max(0.0, self.deadline - self.clock())

    def require_window(self) -> None:
        if self.remaining() == 0:
            raise ToolWindowClosedError("研究检索窗口已结束")


_Output = TypeVar("_Output")
_RETRY_BACKOFF_SECONDS = 0.05
_RETRYABLE_REASONS = {
    "PROVIDER_NETWORK_ERROR", "PROVIDER_TIMEOUT", "PROVIDER_UNAVAILABLE"
}


async def _within_tool_budget(
    operation: Callable[[TavilyCallContext], Awaitable[_Output]],
    *,
    execution: TavilyCallContext | None,
    timeout_seconds: float,
    transient_retries: int,
) -> _Output:
    context = execution if execution is not None else TavilyCallContext()
    context.logical_calls += 1
    context.require_window()
    try:
        # This includes URL validation, network waits, normalization and backoff.
        # The outer timer owns window cancellation; inner expiry is provider timeout.
        async with asyncio.timeout(context.remaining()):
            for attempt in range(min(1, max(0, transient_retries)) + 1):
                context.require_window()
                try:
                    async with asyncio.timeout(timeout_seconds):
                        return await operation(context)
                except InvalidSourceUrlError:
                    raise
                except ToolWindowClosedError:
                    raise
                except Exception as exc:
                    error = _normalize_tavily_exception(exc)
                # Never retain provider exceptions or their sensitive traceback chain.
                error.__cause__ = None
                error.__context__ = None
                error.__traceback__ = None
                if (
                    error.reason not in _RETRYABLE_REASONS
                    or attempt >= min(1, max(0, transient_retries))
                ):
                    raise error from None
                remaining = context.remaining()
                if remaining is not None and remaining <= _RETRY_BACKOFF_SECONDS:
                    raise error from None
                await context.sleep(_RETRY_BACKOFF_SECONDS)
                context.require_window()
                context.retries += 1
    except TimeoutError:
        raise ToolWindowClosedError("研究检索窗口已结束") from None
    raise AssertionError("unreachable tool retry state")


class AdaptiveSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    content_mode: Literal["summary", "full"] = "summary"
    search_depth: Literal["basic", "advanced", "fast", "ultra-fast"] = "basic"
    max_results: int = Field(default=5, ge=2, le=8)
    topic: Literal["general", "news", "finance"] = "general"
    time_range: Literal["day", "week", "month", "year"] | None = None
    start_date: date | None = None
    end_date: date | None = None
    include_domains: list[str] = Field(default_factory=list, max_length=20)
    exclude_domains: list[str] = Field(default_factory=list, max_length=20)
    country: str | None = Field(default=None, min_length=2, max_length=80)
    language: str | None = Field(default=None, min_length=2, max_length=50)
    filter_by_language: bool = False

    @field_validator("query")
    @classmethod
    def clean_query(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("搜索 query 不能为空")
        return cleaned

    @field_validator("include_domains", "exclude_domains")
    @classmethod
    def validate_domains(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip().lower().rstrip(".") for item in value]
        if any(not item or "://" in item or "/" in item for item in cleaned):
            raise ValueError("搜索域名必须是不含协议和路径的域名")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("搜索域名不能重复")
        return cleaned

    @model_validator(mode="after")
    def validate_combinations(self) -> AdaptiveSearchInput:
        if self.content_mode == "full" and self.max_results > 3:
            raise ValueError("全文搜索最多返回 3 条结果")
        if self.country and self.topic != "general":
            raise ValueError("country 只支持 general 搜索")
        if self.filter_by_language and not self.language:
            raise ValueError("严格 language 过滤必须同时设置 language")
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("搜索开始日期不能晚于结束日期")
        if set(self.include_domains) & set(self.exclude_domains):
            raise ValueError("同一域名不能同时包含和排除")
        return self


class AdaptiveSearchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    results: list[SearchResult] = Field(max_length=8)
    response_time: float | None = Field(default=None, ge=0)
    usage: dict[str, Any] | None = None


class AdaptiveExtractInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    urls: list[str] = Field(min_length=1, max_length=3)
    extract_depth: Literal["basic", "advanced"] = "basic"
    full_page: bool = False
    query: str | None = Field(default=None, min_length=1, max_length=500)
    chunks_per_source: int | None = Field(default=None, ge=1, le=5)

    @field_validator("urls")
    @classmethod
    def validate_unique_urls(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("提取 URL 不能为空")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("提取 URL 不能重复")
        return cleaned

    @field_validator("query")
    @classmethod
    def clean_extract_query(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("提取 query 不能为空")
        return cleaned

    @model_validator(mode="after")
    def validate_extract_mode(self) -> AdaptiveExtractInput:
        if self.full_page and self.query:
            raise ValueError("整页提取不能携带相关性 query")
        if self.chunks_per_source is not None and not self.query:
            raise ValueError("chunks_per_source 只用于相关性提取")
        return self


class AdaptiveExtractOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pages: list[ExtractedPage] = Field(max_length=3)
    failed_urls: list[str] = Field(default_factory=list, max_length=3)
    response_time: float | None = Field(default=None, ge=0)
    usage: dict[str, Any] | None = None


class SearchTool(Protocol):
    async def ainvoke(self, payload: dict[str, Any]) -> dict[str, Any]: ...


SearchToolFactory = Callable[..., SearchTool]
ExtractToolFactory = Callable[..., SearchTool]
UrlNormalizer = Callable[[str], Awaitable[str]]


class AdaptiveTavilySearch:
    def __init__(
        self,
        *,
        tavily_api_key: SecretStr,
        tool_factory: SearchToolFactory = TavilySearch,
        normalize_url: UrlNormalizer = normalize_public_url,
        timeout_seconds: float = 8,
        transient_retries: int = 1,
    ) -> None:
        self._api_key = tavily_api_key
        self._tool_factory = tool_factory
        self._normalize_url = normalize_url
        self._timeout_seconds = timeout_seconds
        self._transient_retries = transient_retries

    async def search(
        self, params: AdaptiveSearchInput, *, execution: TavilyCallContext | None = None
    ) -> AdaptiveSearchOutput:
        async def operation(context: TavilyCallContext) -> AdaptiveSearchOutput:
            raw = await self._invoke_once(params, context)
            return await self._normalize_response(raw)

        return await _within_tool_budget(
            operation, execution=execution,
            timeout_seconds=min(8, self._timeout_seconds),
            transient_retries=self._transient_retries,
        )

    async def _invoke_once(
        self, params: AdaptiveSearchInput, context: TavilyCallContext
    ) -> dict[str, Any]:
        tool = self._tool_factory(
            tavily_api_key=self._api_key.get_secret_value(),
            max_results=params.max_results,
            topic=params.topic,
            include_answer=False,
            include_raw_content=(
                False if params.content_mode == "summary" else "markdown"
            ),
            include_images=False,
            include_image_descriptions=False,
            auto_parameters=False,
            country=params.country,
            include_usage=True,
        )
        payload: dict[str, Any] = {
            "query": params.query,
            "search_depth": params.search_depth,
        }
        if params.time_range:
            payload["time_range"] = params.time_range
        if params.start_date:
            payload["start_date"] = params.start_date.isoformat()
        if params.end_date:
            payload["end_date"] = params.end_date.isoformat()
        if params.include_domains:
            payload["include_domains"] = params.include_domains
        if params.exclude_domains:
            payload["exclude_domains"] = params.exclude_domains
        if params.language:
            payload["language"] = params.language
            payload["filter_by_language"] = params.filter_by_language

        return await _invoke_official_tool(tool, payload, context=context, extract=False)

    async def _normalize_response(self, raw: dict[str, Any]) -> AdaptiveSearchOutput:
        results: list[SearchResult] = []
        for item in raw.get("results", []):
            if not isinstance(item, dict):
                raise TavilyResponseError("Tavily 搜索结果格式无效")
            try:
                normalized_url = await self._normalize_url(
                    str(item.get("url", ""))
                )
            except InvalidSourceUrlError:
                # Search results are untrusted individually. Keep the strict
                # SSRF boundary, but do not let one unsafe result discard the
                # other independently validated public sources.
                continue
            try:
                results.append(
                    SearchResult(
                        title=item.get("title", ""),
                        url=normalized_url,
                        content=item.get("content", ""),
                        score=item.get("score"),
                        published_date=item.get("published_date"),
                        raw_content=item.get("raw_content"),
                    )
                )
            except Exception as exc:
                raise TavilyResponseError("Tavily 搜索结果无法解析") from None
        if raw.get("results") and not results:
            raise TavilyResponseError("Tavily 搜索没有可安全使用的结果")
        return AdaptiveSearchOutput(
            results=results,
            response_time=raw.get("response_time"),
            usage=raw.get("usage"),
        )


class AdaptiveTavilyExtract:
    def __init__(
        self,
        *,
        tavily_api_key: SecretStr,
        tool_factory: ExtractToolFactory = TavilyExtract,
        normalize_url: UrlNormalizer = normalize_public_url,
        basic_timeout_seconds: float = 12,
        advanced_timeout_seconds: float = 25,
        transient_retries: int = 1,
        page_char_limit: int = 120_000,
    ) -> None:
        self._api_key = tavily_api_key
        self._tool_factory = tool_factory
        self._normalize_url = normalize_url
        self._basic_timeout_seconds = basic_timeout_seconds
        self._advanced_timeout_seconds = advanced_timeout_seconds
        self._transient_retries = transient_retries
        self._page_char_limit = page_char_limit

    async def extract(
        self, params: AdaptiveExtractInput, *, execution: TavilyCallContext | None = None
    ) -> AdaptiveExtractOutput:
        async def operation(context: TavilyCallContext) -> AdaptiveExtractOutput:
            normalized_urls = [await self._normalize_url(item) for item in params.urls]
            raw = await self._invoke_once(params, normalized_urls, context)
            return await self._normalize_response(raw)

        timeout_seconds = (
            min(25, self._advanced_timeout_seconds)
            if params.extract_depth == "advanced"
            else min(12, self._basic_timeout_seconds)
        )
        return await _within_tool_budget(
            operation, execution=execution, timeout_seconds=timeout_seconds,
            transient_retries=self._transient_retries,
        )

    async def _invoke_once(
        self,
        params: AdaptiveExtractInput,
        normalized_urls: list[str],
        context: TavilyCallContext,
    ) -> dict[str, Any]:
        tool = self._tool_factory(
            tavily_api_key=self._api_key.get_secret_value(),
            format="markdown",
            include_images=False,
            include_favicon=False,
            include_usage=True,
            chunks_per_source=params.chunks_per_source,
        )
        payload: dict[str, Any] = {
            "urls": normalized_urls,
            "extract_depth": params.extract_depth,
            "include_images": False,
        }
        if params.query:
            payload["query"] = params.query
        return await _invoke_official_tool(tool, payload, context=context, extract=True)

    async def _normalize_response(self, raw: dict[str, Any]) -> AdaptiveExtractOutput:
        pages: list[ExtractedPage] = []
        for item in raw.get("results", []):
            if not isinstance(item, dict):
                raise TavilyResponseError("Tavily 网页结果格式无效")
            normalized_url = await self._normalize_url(str(item.get("url", "")))
            content = item.get("raw_content", "")
            if not isinstance(content, str):
                raise TavilyResponseError("Tavily 网页正文格式无效")
            if not content.strip():
                continue
            if len(content) > self._page_char_limit:
                raise PageUnreadableError("网页正文过大，无法安全生成课程", reason="PAGE_TOO_LARGE")
            title = _extract_page_title(content, normalized_url, item.get("title"))
            try:
                pages.append(
                    ExtractedPage(
                        url=normalized_url,
                        title=title,
                        raw_content=content,
                        response_time=raw.get("response_time"),
                        usage=raw.get("usage"),
                    )
                )
            except Exception as exc:
                raise TavilyResponseError("Tavily 网页结果无法解析") from None

        failed_urls: list[str] = []
        for item in raw.get("failed_results", []):
            candidate = item.get("url") if isinstance(item, dict) else item
            if candidate:
                try:
                    failed_urls.append(await self._normalize_url(str(candidate)))
                except Exception:
                    continue
        if not pages:
            raise PageUnreadableError(
                "网页无法读取或没有足够正文",
                reason="PAGE_EXTRACTION_FAILED" if raw.get("failed_results") else "PAGE_EMPTY",
            )
        return AdaptiveExtractOutput(
            pages=pages,
            failed_urls=list(dict.fromkeys(failed_urls)),
            response_time=raw.get("response_time"),
            usage=raw.get("usage"),
        )


def _extract_page_title(content: str, url: str, supplied_title: Any) -> str:
    if supplied_title and str(supplied_title).strip():
        return str(supplied_title).strip()[:500]
    for line in content.splitlines():
        cleaned = line.strip().lstrip("#").strip()
        if cleaned:
            return cleaned[:500]
    return (urlsplit(url).hostname or "网页资料")[:500]


async def _invoke_official_tool(
    tool: SearchTool,
    payload: dict[str, Any],
    *,
    context: TavilyCallContext,
    extract: bool,
) -> dict[str, Any]:
    if isinstance(tool, (TavilySearch, TavilyExtract)):
        # Official tools otherwise turn ToolException into a string containing
        # queries/URLs. Keep that payload out of the agent and error responses.
        tool.handle_tool_error = False
    context.require_window()
    context.physical_requests += 1
    try:
        raw = await tool.ainvoke(payload)
    except ToolException:
        if extract:
            raise PageUnreadableError("网页无法读取或提取失败") from None
        return {"results": []}
    except Exception as exc:
        raise _normalize_tavily_exception(
            exc, extract=extract, allow_fixed_status=True
        ) from None
    if not isinstance(raw, dict):
        raise TavilyResponseError("Tavily 响应格式无效")
    if "error" in raw:
        error = raw["error"]
        if isinstance(error, Exception):
            raise _normalize_tavily_exception(
                error, extract=extract, allow_fixed_status=True
            ) from None
        raise TavilyResponseError("Tavily 返回无效错误载荷")
    if not isinstance(raw.get("results"), list):
        raise TavilyResponseError("Tavily 响应缺少合法结果列表")
    if "failed_results" in raw and not isinstance(raw["failed_results"], list):
        raise TavilyResponseError("Tavily 失败结果格式无效")
    return raw


_OFFICIAL_HTTP_ERROR = re.compile(r"Error ([1-5][0-9]{2}): [^\r\n]*")


def _normalize_tavily_exception(
    exc: Exception, *, extract: bool = False, allow_fixed_status: bool = False
) -> TavilyToolError:
    if isinstance(exc, TavilyToolError):
        return exc
    status: int | None = None
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
    elif isinstance(exc, aiohttp.ClientResponseError):
        status = exc.status
    elif (
        allow_fixed_status
        and type(exc) in (Exception, ValueError)
        and len(exc.args) == 1
        and isinstance(exc.args[0], str)
    ):
        # Approved compatibility boundary for langchain-tavily 0.2.18. Only
        # parse the official numeric status prefix, never the free-form reason.
        match = _OFFICIAL_HTTP_ERROR.fullmatch(exc.args[0])
        if match:
            status = int(match.group(1))
    if status in (401, 403):
        return TavilyAuthenticationError("Tavily 凭证无效")
    if status in (400, 422):
        return TavilyParameterError("Tavily 搜索参数无效")
    if status == 429:
        return TavilyRateLimitError("Tavily 请求频率受限")
    if status == 415 and extract:
        return PageUnreadableError("网页类型不受支持", reason="PAGE_UNSUPPORTED")
    if status == 408 or isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return TavilyUnavailableError("Tavily 请求超时", reason="PROVIDER_TIMEOUT")
    if status in (500, 502, 503, 504):
        return TavilyUnavailableError("Tavily 服务暂时不可用")
    if isinstance(exc, (ConnectionError, OSError, httpx.NetworkError, aiohttp.ClientConnectionError)):
        return TavilyUnavailableError("Tavily 网络连接失败", reason="PROVIDER_NETWORK_ERROR")
    return TavilyResponseError("Tavily 搜索响应无效")
