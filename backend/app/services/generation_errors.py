"""Safe public error contract, independent of optional research packages."""
from app.clients.ai import ContentGenerationError
from app.core.errors import AppError


CONTRACTS = {
    "URL_REQUIRES_RESEARCH": (422, "当前服务暂不支持网页学习，请改用知识关键词", "URL_REQUIRES_RESEARCH"),
    "INVALID_SOURCE_URL": (422, "这个网页地址不安全或无法公开访问", "INVALID_SOURCE_URL"),
    "PAGE_UNREADABLE": (422, "这个网页暂时无法读取，请换一个公开页面", "PAGE_EXTRACTION_FAILED"),
    "TOPIC_AMBIGUOUS": (422, "这个主题可能有多种意思，请补充说明", "AMBIGUOUS_TOPIC"),
    "SOURCES_INSUFFICIENT": (422, "联网资料不足，请换个更具体的主题", "INSUFFICIENT_EVIDENCE"),
    "RESEARCH_AGENT_FAILED": (502, "联网研究没有完成，请稍后重试", "INVALID_RESEARCH_OUTPUT"),
    "GROUNDING_VALIDATION_FAILED": (502, "题目事实校验未通过，请重新生成", "UNSUPPORTED_FACTS"),
    "SEARCH_UNAVAILABLE": (503, "联网搜索暂时不可用，请稍后重试", "PROVIDER_INVALID_RESPONSE"),
    "AI_GENERATION_FAILED": (502, "这次没搭好关卡，请重新生成", "GENERATION_UNAVAILABLE"),
}
REASONS = {
    "PAGE_UNREADABLE": {"PAGE_EMPTY", "PAGE_UNSUPPORTED", "PAGE_TOO_LARGE", "PAGE_EXTRACTION_FAILED"},
    "SEARCH_UNAVAILABLE": {"PROVIDER_AUTH_FAILED", "PROVIDER_RATE_LIMITED", "PROVIDER_NETWORK_ERROR", "PROVIDER_TIMEOUT", "PROVIDER_UNAVAILABLE", "PROVIDER_INVALID_RESPONSE", "PROVIDER_INVALID_REQUEST"},
    "RESEARCH_AGENT_FAILED": {"TOOL_BUDGET_EXHAUSTED", "MODEL_BUDGET_EXHAUSTED", "RESEARCH_TIMEOUT", "INVALID_RESEARCH_OUTPUT", "REQUIRED_TOOL_MISSING", "RESEARCH_MODEL_UNAVAILABLE", "TOOL_NOT_ALLOWED"},
    "AI_GENERATION_FAILED": {"GENERATION_TIMEOUT", "VALIDATION_TIMEOUT", "GENERATION_UNAVAILABLE", "VALIDATION_UNAVAILABLE", "INVALID_GENERATED_OUTPUT", "INVALID_VALIDATION_OUTPUT"},
}

class GenerationPipelineError(AppError):
    """Raised only before persistence, after content safety succeeded."""


def public_generation_error(exc: Exception) -> AppError | None:
    code = "AI_GENERATION_FAILED" if isinstance(exc, ContentGenerationError) else getattr(exc, "code", None)
    if code not in CONTRACTS:
        return None
    status, message, reason = CONTRACTS[code]
    candidate = getattr(exc, "reason", None)
    if candidate in REASONS.get(code, set()):
        reason = candidate
    original = getattr(exc, "details", None) or {}
    if code == "SOURCES_INSUFFICIENT" and original.get("reason") in {"sources_conflict", "CONFLICTING_EVIDENCE"}:
        reason = "CONFLICTING_EVIDENCE"
    details = {"reason": reason}
    if code == "TOPIC_AMBIGUOUS":
        alternatives = original.get("interpretations")
        if isinstance(alternatives, list):
            details["interpretations"] = [value[:500] for value in alternatives[:3] if isinstance(value, str)]
    return GenerationPipelineError(status_code=status, code=code, message=message, details=details)
