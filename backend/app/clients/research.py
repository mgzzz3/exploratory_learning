from __future__ import annotations

from typing import Any

from langchain_deepseek import ChatDeepSeek
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import Settings


class ResearchModelCapabilityError(RuntimeError):
    """研究模型不具备当前流水线所需能力。"""


class _CapabilityToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, description="能力检查查询")


class _CapabilityStructuredOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ready: bool


def validate_research_model_capabilities(model: Any) -> Any:
    bind_tools = getattr(model, "bind_tools", None)
    structured_output = getattr(model, "with_structured_output", None)
    if not callable(bind_tools):
        raise ResearchModelCapabilityError("研究模型不支持 Tool Calls")
    if not callable(structured_output):
        raise ResearchModelCapabilityError("研究模型不支持结构化输出")

    try:
        bind_tools([_CapabilityToolInput], tool_choice="auto")
    except Exception as exc:
        raise ResearchModelCapabilityError("研究模型无法绑定 Tool Calls") from exc
    try:
        structured_output(
            _CapabilityStructuredOutput,
            method="json_mode",
        )
    except Exception as exc:
        raise ResearchModelCapabilityError("研究模型无法启用结构化输出") from exc
    return model


def build_research_chat_model(settings: Settings) -> ChatDeepSeek | None:
    if settings.should_use_mock_research:
        return None
    model = ChatDeepSeek(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
        temperature=0,
        # DeepSeek V4 enables thinking by default. LangChain's ToolStrategy
        # sends tool_choice while producing the final structured response,
        # which DeepSeek rejects in thinking mode.
        extra_body={"thinking": {"type": "disabled"}},
        # Each actual model request must consume the request-local six-call budget.
        # Leave the independent legacy/Responses client's retry policy unchanged.
        max_retries=0,
        timeout=settings.research_total_timeout_seconds,
    )
    if model.model_name != settings.deepseek_model:
        raise ResearchModelCapabilityError("研究模型配置被意外替换")
    return validate_research_model_capabilities(model)
