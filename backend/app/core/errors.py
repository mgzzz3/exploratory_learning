from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def error_payload(
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        from app.core.observability import note_failure, request_id
        note_failure(exc.code, (exc.details or {}).get("reason"))
        details = {**(exc.details or {}), "request_id": request_id()}
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(exc.code, exc.message, details),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        from app.core.observability import note_failure, request_id
        note_failure("VALIDATION_ERROR")
        known_fields = {"body", "query", "path", "topic", "fallback_token", "acknowledge_unverified", "code", "option", "attempt_id", "game_id", "event_id", "completed", "sound_enabled", "vibration_enabled"}
        details = {
            "request_id": request_id(),
            "fields": [
                {
                    "path": ".".join(str(part) if part in known_fields or type(part) is int else "extra" for part in error["loc"]),
                    "message": "字段值或格式不符合要求",
                }
                for error in exc.errors()
            ]
        }
        return JSONResponse(
            status_code=422,
            content=error_payload(
                "VALIDATION_ERROR",
                "请检查填写的内容",
                details,
            ),
        )
