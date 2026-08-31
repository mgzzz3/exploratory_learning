from app.schemas.learning_input import classify_learning_input
from app.services.generation_errors import REASONS


POLICY_VERSION = "basic-knowledge-v1"
# Human-reviewed, complete topic names only; no model-driven expansion.
# Scope: general communication principles, not current events or versioned advice.
REVIEWED_TOPICS = frozenset({"高情商聊天"})
NOTICE = "未经联网核验"
ALLOWED_FAILURES = {
    "SEARCH_UNAVAILABLE": frozenset(REASONS["SEARCH_UNAVAILABLE"]),
    "RESEARCH_AGENT_FAILED": frozenset(REASONS["RESEARCH_AGENT_FAILED"] - {"TOOL_NOT_ALLOWED"}),
    "AI_GENERATION_FAILED": frozenset(REASONS["AI_GENERATION_FAILED"]),
    "SOURCES_INSUFFICIENT": frozenset({"INSUFFICIENT_EVIDENCE"}),
    "GROUNDING_VALIDATION_FAILED": frozenset({"UNSUPPORTED_FACTS"}),
}


def eligible_topic(topic: str) -> bool:
    try:
        descriptor = classify_learning_input(topic)
    except ValueError:
        return False
    return descriptor.input_type == "keyword" and descriptor.normalized_input in REVIEWED_TOPICS


def eligible_failure(code: str, reason: str) -> bool:
    return reason in ALLOWED_FAILURES.get(code, frozenset())
