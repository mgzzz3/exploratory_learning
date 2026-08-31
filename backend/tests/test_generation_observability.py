from __future__ import annotations

import asyncio
import json
import logging
import re

import httpx
import pytest
from langsmith import get_tracing_context

from app.core.observability import (
    GenerationMetrics, diagnostic_scope, emit, record_counts, stage, current_diagnostics,
)
from app.clients.ai import ContentGenerationError
from app.clients.wechat import WechatClientError
from app.main import create_app
from .conftest import login
from .test_basic_endpoint import make_app, failed_request
from .test_grounded_persistence import FailingStrategy
from .test_research_agent_runtime import setup_agent, search_call, finish
from app.schemas.learning_input import classify_learning_input

PRIVATE = 'SENSITIVE_FIXTURE_INPUT_AND_PROVIDER_TOKEN'

def events(caplog):
    return [r.generation_event for r in caplog.records if hasattr(r, 'generation_event')]

@pytest.mark.anyio
async def test_original_failure_and_basic_have_safe_linked_diagnostics(engine, settings, wechat, generator, caplog):
    caplog.set_level(logging.INFO)
    app = make_app(settings, engine, wechat, generator)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        headers = await login(client)
        original = await failed_request(client, headers)
        result = await client.post('/api/v1/games/basic', headers=headers, json={
            'topic':'高情商聊天', 'fallback_token':original['fallback']['token'], 'acknowledge_unverified':True,
        })
        assert result.status_code == 201
    all_events = events(caplog)
    completed = [e for e in all_events if e['event'] == 'request_finished']
    assert len(completed) == 2
    failed, basic = completed
    assert failed['request_id'] == original['request_id']
    assert failed['reason'] == 'GENERATION_UNAVAILABLE'
    assert failed['mode'] == 'grounded' and failed['admission'] == 'allowed'
    assert basic['parent_request_id'] == failed['request_id']
    assert basic['request_id'] != failed['request_id'] and basic['mode'] == 'basic'
    assert basic['outcome'] == 'success'
    assert {'safety','generation','persistence','admission'}.issubset({e.get('stage') for e in all_events})
    serialized = json.dumps(all_events, ensure_ascii=False) + caplog.text
    for secret in ['高情商聊天', original['fallback']['token'], headers['Authorization'], 'openid-owner']:
        assert secret not in serialized
    metrics = json.dumps(app.state.generation_metrics.snapshot())
    assert failed['request_id'] not in metrics and basic['request_id'] not in metrics
    assert 'p50_upper_seconds' in metrics and 'p95_upper_seconds' in metrics

@pytest.mark.anyio
async def test_unknown_provider_error_does_not_escape_or_leak_exception_chain(engine, settings, wechat, generator, caplog):
    class BadStrategy:
        async def generate(self, descriptor):
            try: raise RuntimeError(PRIVATE)
            except RuntimeError:
                logging.getLogger('httpx').exception('provider response %s', PRIVATE)
                logging.getLogger('app.some_client').exception('full input %s', PRIVATE)
                raise ValueError(PRIVATE)
    app = create_app(settings=settings, engine=engine, wechat_client=wechat,
        content_generator=generator, generation_strategy=BadStrategy())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        headers = await login(client)
        response = await client.post('/api/v1/games', headers=headers, json={'topic':PRIVATE})
    assert response.status_code == 500
    assert response.json()['error']['details']['fallback'] == {'available':False}
    assert PRIVATE not in response.text + caplog.text
    assert all(r.exc_info is None for r in caplog.records)

@pytest.mark.anyio
async def test_success_after_bounded_recovery_does_not_keep_previous_failure_reason(engine, settings, wechat, generator, caplog):
    from tests.test_generation_strategy import grounded_result
    class Recovered:
        async def generate(self, descriptor):
            try:
                with stage('generation'): raise ContentGenerationError('fixture', reason='INVALID_GENERATED_OUTPUT')
            except ContentGenerationError: pass
            return grounded_result()
    app = create_app(settings=settings, engine=engine, wechat_client=wechat, content_generator=generator, generation_strategy=Recovered())
    caplog.set_level(logging.INFO)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        headers=await login(client)
        result=await client.post('/api/v1/games',headers=headers,json={'topic':'fixture'})
        assert result.status_code==201
    final=[e for e in events(caplog) if e['event']=='request_finished'][-1]
    assert final['outcome']=='success' and final['reason']=='OK'

@pytest.mark.anyio
async def test_validation_extra_fields_and_values_are_not_echoed(client):
    headers = await login(client)
    response = await client.post('/api/v1/games/basic', headers=headers,
        json={'topic':'高情商聊天','fallback_token':PRIVATE,'acknowledge_unverified':False, PRIVATE:PRIVATE})
    assert response.status_code == 422
    assert PRIVATE not in response.text
    assert re.fullmatch('[a-f0-9]{32}', response.json()['error']['details']['request_id'])

@pytest.mark.anyio
async def test_trace_disabled_in_actual_langchain_graph_even_if_outer_context_enabled(monkeypatch, caplog):
    from langsmith import tracing_context
    async def observed(messages, names):
        assert get_tracing_context()['enabled'] is False
        return finish(messages, names)
    agent, *_ = setup_agent([search_call(), observed])
    with diagnostic_scope('grounded', GenerationMetrics()) as diag:
        with tracing_context(enabled=True):
            await agent.research(classify_learning_input('高情商聊天'))
        assert diag.model_calls == 2 and diag.tool_calls == 1
        assert diag.source_count == 2 and diag.body_characters > 0
    assert current_diagnostics() is None

@pytest.mark.anyio
async def test_tool_parameter_categories_counts_and_token_usage_are_content_free(caplog):
    caplog.set_level(logging.INFO)
    call = search_call()
    call.usage_metadata = {'input_tokens': 25, 'output_tokens': 7, 'total_tokens': 32}
    agent, *_ = setup_agent([call, finish])
    with diagnostic_scope('grounded', GenerationMetrics()) as diag:
        await agent.research(classify_learning_input('高情商聊天'))
        assert diag.result_count == 2
        assert diag.input_tokens == 25 and diag.output_tokens == 7
    tools = [event for event in events(caplog) if event['event'] == 'tool_finished']
    assert len(tools) == 1
    assert tools[0]['tool'] == 'search' and tools[0]['depth'] == 'basic'
    assert tools[0]['content_mode'] == 'summary' and tools[0]['result_count'] == 2
    assert tools[0]['outcome'] == 'success' and tools[0]['duration_seconds'] >= 0

@pytest.mark.anyio
async def test_research_diagnostics_include_physical_retry_totals(caplog):
    from tests.test_tavily_search_adapter import adapter, RecordingSearchFactory, result_payload
    from tests.test_research_agent_runtime import tool_call
    search = adapter(RecordingSearchFactory([ConnectionError(PRIVATE), result_payload()]))
    agent, *_ = setup_agent([search_call(), tool_call('ResearchConclusion', {'status':'insufficient'})], search=search)
    with diagnostic_scope('grounded', GenerationMetrics()) as diag:
        result = await agent.research(classify_learning_input('高情商聊天'))
        assert result.status == 'insufficient'
        assert diag.physical_requests == 2 and diag.retries == 1 and diag.result_count == 1
    assert PRIVATE not in caplog.text

@pytest.mark.anyio
async def test_legacy_generator_discards_provider_exception_chain_and_counts_usage():
    from types import SimpleNamespace
    from app.clients.ai import DeepSeekContentGenerator
    from tests.fakes import generated_game
    client = DeepSeekContentGenerator(api_key='fixture', base_url='https://fixture.invalid', model='fixture', max_retries=2)
    class Responses:
        fail = True
        async def create(self, **kwargs):
            if self.fail: raise ValueError(PRIVATE)
            return SimpleNamespace(output_text=generated_game('fixture').model_dump_json(),
                usage=SimpleNamespace(input_tokens=40, output_tokens=60))
    responses = Responses()
    client.client = SimpleNamespace(responses=responses)
    with pytest.raises(ContentGenerationError) as captured:
        await client.generate('fixture')
    assert captured.value.__cause__ is None and captured.value.__context__ is None
    responses.fail = False
    with diagnostic_scope('legacy', GenerationMetrics()) as diag:
        await client.generate('fixture')
        assert diag.input_tokens == 40 and diag.output_tokens == 60

@pytest.mark.anyio
async def test_parallel_context_and_cancel_are_isolated(caplog):
    caplog.set_level(logging.INFO)
    async def run(cancel):
        with diagnostic_scope('basic', GenerationMetrics()) as diag:
            try:
                with stage('generation'):
                    record_counts(model_calls=1)
                    await asyncio.sleep(0)
                    if cancel: raise asyncio.CancelledError()
            except asyncio.CancelledError: pass
            return diag.request_id, diag.model_calls
    values = await asyncio.gather(run(False), run(True))
    assert values[0][0] != values[1][0]
    assert values[0][1] == values[1][1] == 1
    assert current_diagnostics() is None
    assert {e['outcome'] for e in events(caplog)} >= {'success','cancelled'}

def test_event_allowlist_rejects_content_and_high_cardinality_dimensions(caplog):
    caplog.set_level(logging.INFO)
    metrics = GenerationMetrics()
    with diagnostic_scope('grounded', metrics):
        emit('request_finished', stage='request', outcome='success', duration_seconds=0.2,
            reason=PRIVATE, topic=PRIVATE, url=PRIVATE, token=PRIVATE, request_id=PRIVATE,
            parent_request_id=PRIVATE, body_characters=100, model_calls=2)
    data = json.dumps(events(caplog)) + caplog.text + json.dumps(metrics.snapshot())
    assert PRIVATE not in data

def test_diagnostics_reenabled_after_migration_logging_configuration(caplog):
    from app.core.observability import install_private_logging
    diagnostic_logger = logging.getLogger('app.generation')
    diagnostic_logger.disabled = True
    install_private_logging()
    caplog.set_level(logging.INFO)
    with diagnostic_scope('basic', GenerationMetrics()):
        emit('request_finished', stage='request', outcome='success')
    assert len(events(caplog)) == 1

def test_redacted_access_record_remains_compatible_with_uvicorn_formatter():
    from uvicorn.logging import AccessFormatter
    from app.core.observability import install_private_logging
    install_private_logging()
    record = logging.getLogger('uvicorn.access').makeRecord('uvicorn.access', logging.INFO,
        __file__, 1, '%s - "%s %s HTTP/%s" %d', (PRIVATE, 'POST', PRIVATE, '1.1', 500), None)
    assert PRIVATE not in AccessFormatter('%(client_addr)s %(request_line)s %(status_code)s').format(record)

@pytest.mark.parametrize('logger_name', ['uvicorn.access','uvicorn.error','openai._base_client','httpcore.connection','langchain.callbacks','langsmith.client'])
def test_vendor_and_access_logs_never_dump_payload(logger_name, caplog):
    caplog.set_level(logging.DEBUG)
    try: raise ValueError(PRIVATE)
    except ValueError:
        logging.getLogger(logger_name).exception('POST /private?token=%s %s', PRIVATE, PRIVATE)
    assert PRIVATE not in caplog.text
    assert all(r.exc_info is None for r in caplog.records)
