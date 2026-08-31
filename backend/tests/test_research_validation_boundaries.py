"""Reject internally inconsistent provider metadata before persistence."""
import pytest
from pydantic import ValidationError

from app.schemas.research import ResearchBundle, SourceReference, ResearchFact, ToolCallRecord, ResearchConclusion, GroundedGeneratedGame
from app.services.generation_strategy import GenerationResult
from app.clients.tavily import AdaptiveSearchInput
from tests.test_research_acceptance import bundle
from tests.test_generation_strategy import grounded_result
from tests.test_research_models import source, fact, tool_call
from tests.test_research_state import make_state, record, conclusion
from tests.fakes import generated_game


@pytest.mark.parametrize('field,value', [
    ('alternatives',['a','a']), ('interpretation',None), ('facts',[]), ('tool_calls',[]),
])
def test_ready_bundle_requires_complete_consistent_metadata(field,value):
    data=bundle().model_dump(); data[field]=value
    with pytest.raises(ValidationError): ResearchBundle.model_validate(data)

@pytest.mark.parametrize('missing', ['original_url','sources'])
def test_ready_url_requires_original_source(missing):
    original=source(1,method='extract')
    data=dict(input_type='url',original_url=original.url,status='ready',interpretation='test',
        retrieved_at=bundle().retrieved_at,sources=[original],facts=[fact(original.id)],tool_calls=[tool_call(original.id)])
    data[missing]=None if missing=='original_url' else []
    with pytest.raises(ValidationError): ResearchBundle.model_validate(data)

@pytest.mark.parametrize('kind', ['domain','fact_duplicates','call_duplicates','conclusion_duplicates','alternatives_duplicates','level_duplicates','source_id_duplicates','source_url_duplicates'])
def test_reject_inconsistent_or_duplicate_references(kind):
    with pytest.raises(ValidationError):
        if kind=='domain': SourceReference.model_validate({**source(1).model_dump(),'domain':'wrong.invalid'})
        elif kind=='fact_duplicates': ResearchFact(statement='valid fact',source_ids=['x','x'])
        elif kind=='call_duplicates': ToolCallRecord.model_validate({**tool_call('x').model_dump(),'response_source_ids':['x','x']})
        elif kind=='conclusion_duplicates': ResearchConclusion(status='insufficient',source_ids=['x','x'])
        elif kind=='alternatives_duplicates': ResearchConclusion(status='ambiguous',alternatives=['x','x'])
        elif kind=='level_duplicates':
            game=generated_game('fixture').model_dump()
            for level in game['levels']: level['source_ids']=['x','x']
            GroundedGeneratedGame.model_validate(game)
        else:
            data=bundle().model_dump()
            if kind=='source_id_duplicates': data['sources'][1]['id']=data['sources'][0]['id']
            else:
                data['sources'][1]['url']=data['sources'][0]['url']
                data['sources'][1]['domain']=data['sources'][0]['domain']
            ResearchBundle.model_validate(data)

@pytest.mark.parametrize('field,value', [
    ('retrieved_at',None),('source_input',None),('level_source_ids',[[],[],[]]),
    ('level_source_ids',[['src_aaaaaaaaaaaa','src_aaaaaaaaaaaa'],['src_bbbbbbbbbbbb'],['src_aaaaaaaaaaaa']]),
    ('level_source_ids',[['src_ffffffffffff'],['src_bbbbbbbbbbbb'],['src_aaaaaaaaaaaa']]),
])
def test_generation_result_rejects_partial_or_forged_metadata(field,value):
    data=grounded_result().model_dump(); data[field]=value
    with pytest.raises(ValidationError): GenerationResult.model_validate(data)

@pytest.mark.parametrize('content',[None,'','   '])
def test_evidence_ledger_rejects_empty_content_atomically(content):
    state=make_state(); item=source(1)
    with pytest.raises(ValueError):
        state.record_success(tool_name='adaptive_tavily_search',params=AdaptiveSearchInput(query='fixture'),
            sources=[item],evidence=[{'source_id':item.id,'content':content}],started=0)
    assert not state.calls and not state.evidence

def test_url_conclusion_cannot_drop_original_page_after_acquisition():
    from app.clients.tavily import AdaptiveExtractInput
    original,replacement=source(1,method='extract'),source(2,method='extract')
    state=make_state(original.url)
    record(state,[original],tool_name='adaptive_tavily_extract',params=AdaptiveExtractInput(urls=[original.url],full_page=True))
    record(state,[replacement],tool_name='adaptive_tavily_extract',params=AdaptiveExtractInput(urls=[replacement.url]))
    with pytest.raises(ValueError): state.assemble(conclusion([replacement]))
