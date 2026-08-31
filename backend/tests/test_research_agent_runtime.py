"""Real LangChain graph tests: fake only the chat model and provider adapters."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field, PrivateAttr

from app.clients.research import build_research_chat_model
from app.clients.tavily import TavilyAuthenticationError
from app.schemas.learning_input import classify_learning_input
from app.schemas.research import ResearchConclusion
from app.services.research_agent import ResearchAgent, ResearchAgentFailedError

from .test_research_agent import ExtractStub, SearchStub, PUBLIC_URL
from .test_research_capabilities import research_settings


SEARCH = "adaptive_tavily_search"
EXTRACT = "adaptive_tavily_extract"


class ScriptedModel(BaseChatModel):
    steps: list[Any]
    seen: list[Any] = Field(default_factory=list)
    _index: int = PrivateAttr(0)

    @property
    def _llm_type(self):
        return "offline-scripted-tool-model"

    def bind_tools(self, tools, **kwargs):
        return self.bind(tools=tools, **kwargs)

    def _generate(self, *args, **kwargs):
        raise AssertionError("research must use the asynchronous graph")

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        names = [tool.name if hasattr(tool, "name") else tool.get("function", tool)["name"] for tool in kwargs.get("tools", [])]
        self.seen.append((list(messages), names))
        assert self._index < len(self.steps), "unexpected extra model request"
        step = self.steps[self._index]
        self._index += 1
        message = step(messages, names) if callable(step) else step
        if hasattr(message, "__await__"):
            message = await message
        return ChatResult(generations=[ChatGeneration(message=message)])


def tool_call(name, args, call_id="call_offline_001"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


def search_call(index=0):
    return tool_call(SEARCH, {"query": "高情商聊天", "max_results": 3}, f"call_search_{index}")


def extract_call(index=0, *, full_page=False):
    return tool_call(EXTRACT, {"urls": [PUBLIC_URL], "full_page": full_page}, f"call_extract_{index}")


def final_payload(messages):
    sources = {}
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        try:
            output = json.loads(message.content)
        except (ValueError, TypeError):
            continue
        for source in output.get("sources", []):
            sources[source["id"]] = source
    ids = list(sources)[:5]
    return {
        "status": "ready", "interpretation": "AI agent 的环境、约束、反馈回路工程",
        "source_ids": ids,
        "facts": [{"statement": f"资料支持的事实 {index}", "source_ids": ids[:1]} for index in range(3)],
    }


def finish(messages, names):
    assert "ResearchConclusion" in names
    return tool_call("ResearchConclusion", final_payload(messages), "call_conclusion")


def invalid_schema(messages, names):
    return tool_call("ResearchConclusion", {**final_payload(messages), "raw_content": "private-marker"}, "call_bad_schema")


def forged_source(messages, names):
    return tool_call("ResearchConclusion", {
        "status": "ready", "interpretation": "未取得的来源",
        "source_ids": ["src_ffffffffffff", "src_eeeeeeeeeeee"],
        "facts": [{"statement": "伪造事实", "source_ids": ["src_ffffffffffff"]}],
    }, "call_forged")


def setup_agent(steps, **kwargs):
    model = ScriptedModel(steps=steps)
    search = kwargs.pop("search", SearchStub())
    extract = kwargs.pop("extract", ExtractStub())
    assemblies = []

    def factory(**options):
        assemblies.append(options)
        return create_agent(**options)

    agent = ResearchAgent(model=model, search=search, extract=extract, agent_factory=factory, **kwargs)
    return agent, model, search, extract, assemblies


@pytest.mark.anyio
@pytest.mark.parametrize("is_url", [False, True])
async def test_real_graph_uses_response_tool_and_server_ledger(is_url):
    agent, model, search, extract, assemblies = setup_agent([extract_call(full_page=True) if is_url else search_call(), finish])
    result = await agent.research(classify_learning_input(PUBLIC_URL if is_url else "高情商聊天"))
    assert result.status == "ready"
    assert len(result.sources) == (1 if is_url else 2)
    assert len(assemblies) == 1
    strategy = assemblies[0]["response_format"]
    assert isinstance(strategy, ToolStrategy)
    assert strategy.schema is ResearchConclusion
    assert len(model.seen) == 2
    assert len(search.calls) == (0 if is_url else 1)
    assert len(extract.calls) == (1 if is_url else 0)
    assert assemblies[0]["middleware"][0]._budget.model_calls == 2


def test_grounded_chat_client_disables_implicit_sdk_retries():
    model = build_research_chat_model(research_settings())
    assert model.max_retries == 0
    assert model.extra_body == {"thinking": {"type": "disabled"}}


@pytest.mark.anyio
async def test_third_search_intent_keeps_evidence_and_converges():
    agent, model, search, extract, _ = setup_agent([search_call(1), search_call(2), extract_call(), search_call(3), finish])
    result = await agent.research(classify_learning_input("高情商聊天"))
    assert result.status == "ready"
    assert len(search.calls) == 2 and len(extract.calls) == 1
    assert len(result.tool_calls) == 3
    feedback = [m for m in model.seen[-1][0] if isinstance(m, ToolMessage) and m.tool_call_id == "call_search_3"]
    assert len(feedback) == 1
    assert json.loads(feedback[0].content)["status"] == "blocked"
    assert not {SEARCH, EXTRACT}.intersection(model.seen[-1][1])


@pytest.mark.anyio
async def test_four_tools_leave_structured_response_available():
    agent, model, search, extract, _ = setup_agent([search_call(1), extract_call(1), search_call(2), extract_call(2), finish])
    result = await agent.research(classify_learning_input("高情商聊天"))
    assert len(result.tool_calls) == 4
    assert len(search.calls) == len(extract.calls) == 2
    assert model.seen[-1][1] == ["ResearchConclusion"]


@pytest.mark.anyio
async def test_last_two_model_calls_are_reserved_for_conclusion_and_correction():
    agent, model, search, extract, _ = setup_agent([search_call(), extract_call(), finish], max_model_calls=4)
    await agent.research(classify_learning_input("高情商聊天"))
    assert len(search.calls) + len(extract.calls) == 2
    assert model.seen[-1][1] == ["ResearchConclusion"]


@pytest.mark.anyio
async def test_parallel_search_intents_cannot_overspend():
    parallel = AIMessage(content="", tool_calls=[search_call(index).tool_calls[0] for index in range(3)])
    agent, model, search, _, _ = setup_agent([parallel, finish])
    result = await agent.research(classify_learning_input("高情商聊天"))
    assert len(search.calls) == 2
    assert len(result.tool_calls) == 2
    assert len(model.seen) == 2


@pytest.mark.anyio
@pytest.mark.parametrize("broken", [invalid_schema, forged_source])
async def test_single_correction_reuses_graph_messages_and_evidence(broken):
    agent, model, search, _, assemblies = setup_agent([search_call(), broken, finish])
    result = await agent.research(classify_learning_input("高情商聊天"))
    assert result.status == "ready"
    assert len(search.calls) == 1 and len(assemblies) == 1
    assert len(model.seen) == 3
    assert model.seen[-1][1] == ["ResearchConclusion"]
    assert any(isinstance(item, ToolMessage) and item.tool_call_id == "call_search_0" for item in model.seen[-1][0])
    corrections = [item.content for item in model.seen[-1][0] if isinstance(item, ToolMessage) and item.status == "error"]
    assert all("private-marker" not in text for text in corrections)


@pytest.mark.anyio
@pytest.mark.parametrize("first,second", [(invalid_schema, forged_source), (forged_source, invalid_schema)])
async def test_schema_and_post_validation_share_only_one_correction(first, second):
    agent, model, search, _, assemblies = setup_agent([search_call(), first, second])
    with pytest.raises(ResearchAgentFailedError) as caught:
        await agent.research(classify_learning_input("高情商聊天"))
    assert caught.value.reason == "INVALID_RESEARCH_OUTPUT"
    assert len(search.calls) == 1 and len(model.seen) == 3 and len(assemblies) == 1


@pytest.mark.anyio
async def test_zero_tool_correction_can_complete_the_mandatory_first_call():
    no_tools = tool_call("ResearchConclusion", {"status": "insufficient"})
    agent, model, search, _, assemblies = setup_agent([no_tools, search_call(), finish])
    result = await agent.research(classify_learning_input("高情商聊天"))
    assert result.status == "ready"
    assert len(search.calls) == 1 and len(model.seen) == 3 and len(assemblies) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("status", ["ambiguous", "insufficient", "conflict"])
async def test_nonready_business_conclusion_does_not_trigger_correction(status):
    agent, model, search, _, _ = setup_agent([search_call(), tool_call("ResearchConclusion", {"status": status})])
    result = await agent.research(classify_learning_input("高情商聊天"))
    assert result.status == status
    assert len(model.seen) == 2 and len(search.calls) == 1


@pytest.mark.anyio
async def test_plain_json_is_not_accepted_as_structured_response():
    def prose(messages, names):
        return AIMessage(content=json.dumps(final_payload(messages)))
    agent, model, search, _, _ = setup_agent([search_call(), prose, prose])
    with pytest.raises(ResearchAgentFailedError):
        await agent.research(classify_learning_input("高情商聊天"))
    assert len(model.seen) == 3 and len(search.calls) == 1

@pytest.mark.anyio
async def test_schema_correction_explains_safe_field_constraints_without_echoing_values():
    def bad(messages, names):
        return tool_call('ResearchConclusion', {**final_payload(messages), 'source_ids':['sensitive-fixture'] * 6})
    def corrected(messages, names):
        feedback = '\n'.join(m.content for m in messages if isinstance(m, ToolMessage))
        assert 'source_ids:too_long' in feedback
        assert '最多 5 条' in feedback
        assert 'sensitive-fixture' not in feedback
        return finish(messages, names)
    agent, model, search, *_ = setup_agent([search_call(), bad, corrected])
    assert (await agent.research(classify_learning_input('高情商聊天'))).status == 'ready'
    assert len(search.calls) == 1 and len(model.seen) == 3


@pytest.mark.anyio
async def test_provider_failure_is_not_a_schema_error_or_research_retry():
    class FailedSearch(SearchStub):
        async def search(self, params, **kwargs):
            self.calls.append(params)
            raise TavilyAuthenticationError("Tavily 凭证无效")
    agent, model, search, _, _ = setup_agent([search_call()], search=FailedSearch())
    with pytest.raises(TavilyAuthenticationError):
        await agent.research(classify_learning_input("高情商聊天"))
    assert len(model.seen) == len(search.calls) == 1


@pytest.mark.anyio
async def test_real_async_middleware_stops_model_over_budget():
    agent, model, search, _, _ = setup_agent([search_call(), finish], max_model_calls=1)
    with pytest.raises(ResearchAgentFailedError) as caught:
        await agent.research(classify_learning_input("高情商聊天"))
    assert caught.value.reason == "MODEL_BUDGET_EXHAUSTED"
    assert len(model.seen) == 1


@pytest.mark.anyio
async def test_cancellation_releases_request_state_and_propagates(monkeypatch):
    from app.services.research_state import ResearchRunState
    states = []
    original_close = ResearchRunState.close

    def close(state):
        original_close(state)
        states.append(state)

    monkeypatch.setattr(ResearchRunState, "close", close)
    entered = asyncio.Event()

    async def waiting(messages, names):
        entered.set()
        await asyncio.Event().wait()

    agent, _, _, _, _ = setup_agent([search_call(), waiting])
    task = asyncio.create_task(agent.research(classify_learning_input("高情商聊天")))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(states) == 1
    assert states[0].closed and states[0].descriptor is None
    assert not states[0].evidence and not states[0].messages and not states[0].workspaces


@pytest.mark.anyio
async def test_insufficient_acquired_evidence_still_fails_acceptance():
    from app.clients.tavily import AdaptiveSearchOutput
    from app.services.research_acceptance import ResearchAcceptanceError, accept_research_bundle

    class EmptySearch(SearchStub):
        async def search(self, params, **kwargs):
            self.calls.append(params)
            return AdaptiveSearchOutput(results=[])

    descriptor = classify_learning_input("高情商聊天")
    agent, _, _, _, _ = setup_agent([search_call(), tool_call("ResearchConclusion", {"status": "insufficient"})], search=EmptySearch())
    result = await agent.research(descriptor)
    with pytest.raises(ResearchAcceptanceError) as caught:
        accept_research_bundle(descriptor, result)
    assert caught.value.code == "SOURCES_INSUFFICIENT"


@pytest.mark.anyio
@pytest.mark.parametrize("concurrent", [False, True])
async def test_same_topic_requests_do_not_share_state_or_history(concurrent):
    def respond(messages, names):
        if any(isinstance(message, ToolMessage) for message in messages):
            return finish(messages, names)
        return search_call()

    agent, model, search, _, assemblies = setup_agent([respond] * 4)
    descriptor = classify_learning_input("高情商聊天")
    if concurrent:
        results = await asyncio.gather(agent.research(descriptor), agent.research(descriptor))
    else:
        results = [await agent.research(descriptor), await agent.research(descriptor)]
    assert all(result.status == "ready" for result in results)
    assert len(search.calls) == 2 and len(assemblies) == 2
    states = [options["middleware"][0]._state for options in assemblies]
    assert states[0] is not states[1]
    for state in states:
        assert state.closed and not state.evidence and not state.messages
    assert all(options["middleware"][0]._budget.model_calls == 2 for options in assemblies)
    assert all(options.get("checkpointer") is None for options in assemblies)
    assert all(sum(isinstance(message, ToolMessage) for message in messages) <= 1 for messages, _ in model.seen)


@pytest.mark.anyio
async def test_unknown_tool_is_rejected_without_model_correction():
    agent, model, search, _, assemblies = setup_agent([tool_call("shell", {"command": "env"})])
    with pytest.raises(ResearchAgentFailedError, match="白名单"):
        await agent.research(classify_learning_input("高情商聊天"))
    assert len(model.seen) == 1 and not search.calls
    state = assemblies[0]["middleware"][0]._state
    assert state.closed and not state.messages and not state.evidence


@pytest.mark.anyio
async def test_response_tool_cannot_hide_a_parallel_unauthorized_tool_intent():
    def mixed(messages, names):
        response = finish(messages, names)
        return AIMessage(content="", tool_calls=[
            *response.tool_calls,
            {"name": "shell", "args": {"command": "env"}, "id": "call_forbidden", "type": "tool_call"},
        ])

    agent, model, search, _, _ = setup_agent([search_call(), mixed])
    with pytest.raises(ResearchAgentFailedError, match="白名单"):
        await agent.research(classify_learning_input("高情商聊天"))
    assert len(model.seen) == 2 and len(search.calls) == 1
