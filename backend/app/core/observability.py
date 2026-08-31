"""Content-free generation diagnostics. No optional research imports or storage."""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import uuid4

from starlette.responses import JSONResponse

MODES = {"grounded", "legacy", "basic"}
STAGES = {"request", "safety", "admission", "research", "generation", "validation", "persistence", "tool"}
OUTCOMES = {"success", "error", "cancelled", "blocked"}
EVENTS = {"request_finished", "stage_finished", "research_finished", "tool_finished", "admission_checked", "validation_checked"}
REASONS = {
    "OK", "INTERNAL_ERROR", "HTTP_ERROR", "REQUEST_CANCELLED", "CONTENT_BLOCKED", "WECHAT_UNAVAILABLE",
    "UNAUTHORIZED", "VALIDATION_ERROR", "BASIC_MODE_NOT_ALLOWED", "INVALID_PERMIT", "PERMIT_EXPIRED",
    "BASIC_TOPIC_NOT_ALLOWED", "BASIC_MODE_DISABLED", "INVALID_SOURCE_URL", "URL_REQUIRES_RESEARCH",
    "PERMIT_INVALID", "TOPIC_NOT_ELIGIBLE",
    "PAGE_EMPTY", "PAGE_UNSUPPORTED", "PAGE_TOO_LARGE", "PAGE_EXTRACTION_FAILED",
    "PROVIDER_AUTH_FAILED", "PROVIDER_RATE_LIMITED", "PROVIDER_NETWORK_ERROR", "PROVIDER_TIMEOUT",
    "PROVIDER_UNAVAILABLE", "PROVIDER_INVALID_RESPONSE", "PROVIDER_INVALID_REQUEST",
    "TOOL_BUDGET_EXHAUSTED", "MODEL_BUDGET_EXHAUSTED", "RESEARCH_TIMEOUT", "INVALID_RESEARCH_OUTPUT",
    "REQUIRED_TOOL_MISSING", "RESEARCH_MODEL_UNAVAILABLE", "TOOL_NOT_ALLOWED", "INSUFFICIENT_EVIDENCE",
    "CONFLICTING_EVIDENCE", "AMBIGUOUS_TOPIC", "GENERATION_TIMEOUT", "VALIDATION_TIMEOUT",
    "GENERATION_UNAVAILABLE", "VALIDATION_UNAVAILABLE", "INVALID_GENERATED_OUTPUT", "INVALID_VALIDATION_OUTPUT",
    "UNSUPPORTED_FACTS", "PERSISTENCE_FAILED",
}
COUNTS = {"model_calls", "tool_calls", "physical_requests", "retries", "source_count", "result_count", "body_characters", "validation_issues", "input_tokens", "output_tokens"}
ENUM_FIELDS = {"stage": STAGES, "outcome": OUTCOMES, "reason": REASONS,
    "admission": {"allowed", "denied", "not_applicable"}, "tool": {"search", "extract"},
    "content_mode": {"summary", "full"}, "depth": {"basic", "advanced", "fast", "ultra-fast"}}
BUCKETS = (0.05, 0.25, 1, 5, 15, 30, 45, 70, 85, 90, math.inf)
_context: ContextVar[Diagnostics | None] = ContextVar("generation_diagnostics", default=None)
logger = logging.getLogger("app.generation")


class GenerationMetrics:
    """Process-local bounded histograms; external collectors may scrape snapshots.

    Quantiles are bucket upper bounds, not exact observations. No per-request samples.
    """
    def __init__(self):
        self._histograms = defaultdict(lambda: [0] * len(BUCKETS))
        self._counts = defaultdict(int)

    def observe(self, event):
        if event["event"] not in {"request_finished", "stage_finished"}:
            return
        key = (event["mode"], event.get("stage", "request"), event.get("outcome", "error"), event.get("reason", "OK"))
        seconds = event.get("duration_seconds", 0)
        index = next(i for i, upper in enumerate(BUCKETS) if seconds <= upper)
        self._histograms[key][index] += 1
        for field in COUNTS:
            self._counts[(*key, field)] += event.get(field, 0)
        if event["event"] == "request_finished":
            self._counts[(*key, "admission_allowed")] += event.get("admission") == "allowed"

    def snapshot(self):
        rows = []
        for key, buckets in self._histograms.items():
            count = sum(buckets)
            def quantile(fraction):
                total = 0
                for bound, number in zip(BUCKETS, buckets):
                    total += number
                    if total >= math.ceil(count * fraction):
                        return bound if math.isfinite(bound) else None
            rows.append({"mode": key[0], "stage": key[1], "outcome": key[2], "reason": key[3],
                "count": count, "buckets": list(buckets), "p50_upper_seconds": quantile(.5), "p95_upper_seconds": quantile(.95),
                "counts": {name: self._counts[(*key, name)] for name in sorted(COUNTS | {"admission_allowed"})}})
        return rows


@dataclass(repr=False)
class Diagnostics:
    request_id: str
    mode: str
    metrics: GenerationMetrics
    parent_request_id: str | None = None
    reason: str = "OK"
    admission: str = "not_applicable"
    model_calls: int = 0
    tool_calls: int = 0
    physical_requests: int = 0
    retries: int = 0
    source_count: int = 0
    result_count: int = 0
    body_characters: int = 0
    validation_issues: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


def current_diagnostics():
    return _context.get()


@contextmanager
def diagnostic_scope(mode, metrics):
    diag = Diagnostics(request_id=uuid4().hex, mode=mode if mode in MODES else "grounded", metrics=metrics)
    token = _context.set(diag)
    try:
        yield diag
    finally:
        _context.reset(token)


def request_id():
    diag = current_diagnostics()
    return diag.request_id if diag else uuid4().hex


def note_failure(code, reason=None):
    diag = current_diagnostics()
    if diag:
        diag.reason = reason if reason in REASONS else code if code in REASONS else "HTTP_ERROR"


def record_counts(**values):
    diag = current_diagnostics()
    if diag:
        for key, value in values.items():
            if key in COUNTS and type(value) is int and 0 <= value <= 100_000_000:
                setattr(diag, key, getattr(diag, key) + value)


def note_admission(allowed, *, parent_request_id=None):
    diag = current_diagnostics()
    if diag:
        diag.admission = "allowed" if allowed else "denied"
        if isinstance(parent_request_id, str) and re.fullmatch(r"[a-f0-9]{32}", parent_request_id):
            diag.parent_request_id = parent_request_id
        emit("admission_checked", stage="admission", admission=diag.admission)


def emit(event, **values):
    diag = current_diagnostics()
    if not diag or event not in EVENTS:
        return
    safe = {"event": event, "mode": diag.mode, "request_id": diag.request_id}
    if diag.parent_request_id:
        safe["parent_request_id"] = diag.parent_request_id
    for key, value in values.items():
        if key in ENUM_FIELDS and isinstance(value, str) and value in ENUM_FIELDS[key]:
            safe[key] = value
        elif key in COUNTS and type(value) is int and 0 <= value <= 100_000_000:
            safe[key] = value
        elif key == "duration_seconds" and type(value) in {int, float} and math.isfinite(value) and value >= 0:
            safe[key] = round(value, 4)
    diag.metrics.observe(safe)
    logger.info("generation_event", extra={"generation_event": safe})


@contextmanager
def stage(name):
    started = time.monotonic()
    outcome = "success"
    try:
        yield
    except asyncio.CancelledError:
        outcome = "cancelled"
        note_failure("REQUEST_CANCELLED")
        raise
    except Exception as exc:
        outcome = "error"
        note_failure(getattr(exc, "code", "INTERNAL_ERROR"), getattr(exc, "reason", None))
        raise
    finally:
        diag = current_diagnostics()
        emit("stage_finished", stage=name, outcome=outcome,
            reason=diag.reason if outcome != "success" and diag else "OK",
            duration_seconds=time.monotonic() - started)


class SafeJsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps(getattr(record, "generation_event", {"event": "runtime_log_suppressed"}), ensure_ascii=False)


def install_private_logging():
    old_factory = logging.getLogRecordFactory()
    if not getattr(old_factory, "_generation_private", False):
        def factory(*args, **kwargs):
            record = old_factory(*args, **kwargs)
            if current_diagnostics() or record.name.startswith(("uvicorn", "httpx", "httpcore", "openai", "langchain", "langsmith", "tavily")):
                record.msg = "generation_event" if record.name == "app.generation" else "runtime_log_suppressed"
                record.args = ()
                # Uvicorn's AccessFormatter unpacks five fields even when a
                # custom message is used. Keep its shape, never its values.
                if record.name == "uvicorn.access":
                    original_args = args[5] if len(args) > 5 else ()
                    status = original_args[-1] if isinstance(original_args, tuple) and original_args else 500
                    if type(status) is not int or not 100 <= status <= 599:
                        status = 500
                    record.msg = '%s - "%s %s HTTP/%s" %d'
                    record.args = ("redacted", "REDACTED", "/redacted", "1.1", status)
                record.exc_info = record.exc_text = record.stack_info = None
            return record
        factory._generation_private = True
        logging.setLogRecordFactory(factory)
    if not any(isinstance(handler.formatter, SafeJsonFormatter) for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(SafeJsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    # Alembic's fileConfig can disable already-created named loggers.
    logger.disabled = False


class GenerationDiagnosticsMiddleware:
    def __init__(self, app, *, settings, metrics):
        self.app, self.settings, self.metrics = app, settings, metrics

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or scope.get("method") != "POST" or path not in {
            f"{self.settings.api_prefix}/games", f"{self.settings.api_prefix}/games/basic",
        }:
            return await self.app(scope, receive, send)
        mode = "basic" if path.endswith("/basic") else self.settings.question_generation_mode
        with diagnostic_scope(mode, self.metrics) as diag:
            started = time.monotonic()
            status = 500
            sent = False
            outcome = "error"
            async def safe_send(message):
                nonlocal status, sent
                if message["type"] == "http.response.start":
                    status, sent = message["status"], True
                await send(message)
            try:
                await self.app(scope, receive, safe_send)
                outcome = "success" if status < 400 else "error"
                if status < 400:
                    diag.reason = "OK"
                if status >= 400 and diag.reason == "OK":
                    diag.reason = "HTTP_ERROR"
            except asyncio.CancelledError:
                outcome, diag.reason = "cancelled", "REQUEST_CANCELLED"
                raise
            except Exception:
                diag.reason = "INTERNAL_ERROR"
                # Do not let ServerErrorMiddleware/Uvicorn print the original chain.
                if not sent:
                    response = JSONResponse(status_code=500, content={"error": {
                        "code": "INTERNAL_ERROR", "message": "请求未能完成，请稍后重试", "details": {
                            "request_id": diag.request_id, "reason": diag.reason, "fallback": {"available": False},
                        },
                    }})
                    await response(scope, receive, safe_send)
            finally:
                emit("request_finished", stage="request", outcome=outcome, reason=diag.reason,
                    admission=diag.admission, duration_seconds=time.monotonic() - started,
                    **{name: getattr(diag, name) for name in COUNTS})
