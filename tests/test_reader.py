import asyncio
import copy
import json

import httpx
from mcp import Client
import pytest

from balatro_agent.contract import Envelope
from balatro_agent.policy import canonical, observation_id, project
from balatro_agent.reader import Reader
from balatro_agent.transport import GameClient, ReaderError


def client_for(settings, handler):
    return GameClient(settings.url,settings.request_timeout_s,transport=httpx.MockTransport(handler))


def reply(request,data):
    identifier=json.loads(request.content)['id']
    return httpx.Response(200,json={'jsonrpc':'2.0','id':identifier,'result':data})


async def test_observation_zero_unknown_whitelist_and_filtered_disk(settings,public_envelope):
    raw=copy.deepcopy(public_envelope)
    raw['seed']='SECRET_SEED'; raw['public']['internal']='SECRET_RESULT'
    raw['public']['regions'][0]['cards'][0].update(key='SECRET_KEY',id='SECRET_ID',future='SECRET_FUTURE')
    reader=Reader(settings,client_for(settings,lambda req:reply(req,raw)))
    result=await reader.observe()
    assert result['status']=='ok'
    assert result['observation']['resources']['dollars']==0
    assert result['observation']['resources']['ante'] is None
    assert 'SECRET' not in canonical(result)
    log=next(settings.log_dir.glob('*.jsonl')).read_text(encoding='utf-8')
    assert 'SECRET' not in log and json.loads(log)['result']==result


async def test_profile_changes_and_restart_are_freshly_checked(settings,public_envelope):
    client=client_for(settings,lambda req:reply(req,public_envelope))
    reader=Reader(settings,client)
    original=(await reader.observe())['observation']['observation_id']
    for profile in (1,2,3):
        public_envelope['profile']=profile
        public_envelope['observation_id']=f'obs-0123456789abcdef-{profile}'
        health=await reader.health()
        assert health['actual_profile']==profile
        assert health['profile_status']=='recognized' and health['profile_policy']=='current-native-v1'
        result=await reader.observe()
        assert result['status']=='ok' and result['observation']['profile']==profile
        assert (result['observation']['observation_id']==original)==(profile==3)
        waited=await reader.wait_until_ready(0.1)
        assert waited['status']=='ready' and waited['observation']['profile']==profile
    public_envelope['profile']=3
    settings.profile_file.write_text('{}')
    restarted=Reader(settings,client)
    assert (await restarted.health())['profile_status']=='recognized'
    result=await restarted.observe()
    assert result['status']=='ok' and result['observation']['observation_id']==original


async def test_unknown_actual_profile_is_not_replaced_by_test_configuration(settings,public_envelope):
    settings.profile_file.write_text('{}')
    public_envelope.pop('profile')
    reader=Reader(settings,client_for(settings,lambda req:reply(req,public_envelope)))
    assert (await reader.health())['profile_status']=='unknown_profile'
    for result in (await reader.observe(),await reader.wait_until_ready(0.1)):
        assert result['status']=='unknown_profile' and 'observation' not in result


async def test_missing_actual_profile_is_explicitly_unknown(settings,public_envelope):
    public_envelope.pop('profile')
    reader=Reader(settings,client_for(settings,lambda req:reply(req,public_envelope)))
    health=await reader.health()
    assert health['connected'] and health['actual_profile'] is None
    assert health['profile_status']=='unknown_profile'
    assert (await reader.observe())['status']=='unknown_profile'


@pytest.mark.parametrize('tool',['health','observe','wait_until_ready'])
async def test_log_write_failure_is_static_and_no_observation_is_delivered(settings,public_envelope,tool,monkeypatch):
    reader=Reader(settings,client_for(settings,lambda req:reply(req,public_envelope)))
    def fail(*args): raise OSError('SECRET_DISK_PATH')
    monkeypatch.setattr(reader,'_record_delivered',fail)
    result=await getattr(reader,tool)()
    assert result['status']=='log_unavailable'
    assert 'observation' not in result and 'SECRET' not in canonical(result)


async def test_actual_lua_deck_menu_survives_final_output_validation(settings,lua_reader):
    lua,snapshot=lua_reader
    lua.execute("local a=area({card('Shown Ace'),card('Shown Ace')}); a.config.view_deck=true; G.OVERLAY_MENU=ui({}, {ui({object=a})})")
    reader=Reader(settings,client_for(settings,lambda req:reply(req,snapshot())))
    result=await reader.observe()
    assert result['status']=='ok' and result['observation']['phase']=='menu'
    entry=result['observation']['menus']['deck_composition'][0]
    assert entry['count']==2 and 'position' not in entry['card'] and 'selected' not in entry['card']


async def test_actual_lua_other_profile_remains_filtered_and_profile_bound(settings,lua_reader):
    lua,snapshot=lua_reader
    lua.execute("G.SETTINGS.profile=1; G.hand.cards[1].facing='back'; G.hand.cards[1].sprite_facing='back'")
    reader=Reader(settings,client_for(settings,lambda req:reply(req,snapshot())))
    first=await reader.observe()
    assert first['status']=='ok' and first['observation']['profile']==1
    card=first['observation']['regions'][0]['cards'][0]
    assert card=={'position':0,'visibility':'face_down','selected':False}
    lua.execute("G.SETTINGS.profile=2; G.hand.cards[1].public_name='SECRET_CHANGED_PROFILE'")
    second=await reader.observe()
    assert second['status']=='ok' and second['observation']['profile']==2
    assert first['observation']['observation_id']!=second['observation']['observation_id']
    assert second['observation']['regions'][0]['cards'][0]==card
    assert 'SECRET' not in canonical(first) and 'SECRET' not in canonical(second)


@pytest.mark.parametrize('mutation,status',[
    (lambda data:data.update(schema_version='SECRET_VERSION'), 'version_mismatch'),
    (lambda data:data.update(adapter_version='0.1.0'), 'version_mismatch'),
    (lambda data:data.update(compatibility='unsupported_mods'), 'unsupported'),
    (lambda data:data['public'].update(phase='SECRET_PHASE'), 'invalid_response'),
    (lambda data:data['public']['regions'][0]['cards'][0].update(rank='SECRET_RANK'), 'invalid_response'),
])
async def test_validation_errors_never_echo_backend(settings,public_envelope,mutation,status):
    mutation(public_envelope)
    reader=Reader(settings,client_for(settings,lambda req:reply(req,public_envelope)))
    result=await reader.observe()
    assert result['status']==status and 'SECRET' not in canonical(result)
    assert 'SECRET' not in next(settings.log_dir.glob('*.jsonl')).read_text(encoding='utf-8')


@pytest.mark.parametrize('kind,status', [('json','invalid_response'),('rpc','adapter_error'),('id','invalid_response'),('disconnect','disconnected'),('timeout','request_timeout'),('redirect','invalid_response')])
async def test_transport_failure_paths(settings,kind,status):
    def handler(request):
        if kind=='disconnect': raise httpx.ConnectError('SECRET_SOCKET',request=request)
        if kind=='timeout': raise httpx.ReadTimeout('SECRET_TIMEOUT',request=request)
        if kind=='json': return httpx.Response(200,content=b'SECRET_NOT_JSON')
        if kind=='rpc': return httpx.Response(200,json={'jsonrpc':'2.0','id':json.loads(request.content)['id'],'error':{'message':'SECRET_NATIVE'}})
        if kind=='id': return httpx.Response(200,json={'jsonrpc':'2.0','id':999,'result':{'secret':'SECRET'}})
        return httpx.Response(302,headers={'Location':'http://evil.example/SECRET'})
    result=await Reader(settings,client_for(settings,handler)).observe()
    assert result['status']==status and 'SECRET' not in canonical(result)


async def test_wait_reports_ready_no_game_actions(settings,public_envelope):
    requests=[]
    def handler(request):
        requests.append(json.loads(request.content)['method'])
        public_envelope['public']['ready']=len(requests)>=2
        public_envelope['public']['ready_reason']='ui_operable' if len(requests)>=2 else 'processing'
        public_envelope['ready']=public_envelope['public']['ready']
        public_envelope['ready_reason']=public_envelope['public']['ready_reason']
        return reply(request,public_envelope)
    result=await Reader(settings,client_for(settings,handler)).wait_until_ready(0.3)
    assert result['status']=='ready' and requests==['reader_snapshot','reader_snapshot']
    lines=next(settings.log_dir.glob('*.jsonl')).read_text(encoding='utf-8').splitlines()
    assert len(lines)==1  # polling snapshots were never given to the model


async def test_wait_timeout_latest_observation_only(settings,public_envelope):
    public_envelope['public']['ready']=False; public_envelope['public']['ready_reason']='processing'
    public_envelope['ready']=False; public_envelope['ready_reason']='processing'
    result=await Reader(settings,client_for(settings,lambda req:reply(req,public_envelope))).wait_until_ready(0.03)
    assert result['status']=='timeout' and not result['observation']['ready']


@pytest.mark.parametrize('timeout',[float('nan'),float('inf'),-1,31,True,'SECRET_INPUT'])
async def test_wait_invalid_timeout_safe(settings,timeout):
    result=await Reader(settings).wait_until_ready(timeout)
    assert result['status']=='invalid_timeout' and 'SECRET' not in canonical(result)


async def test_parallel_http_reads_are_serial(settings,public_envelope):
    active=0; peak=0
    async def handler(request):
        nonlocal active,peak
        active+=1; peak=max(peak,active)
        await asyncio.sleep(0.01)
        active-=1
        return reply(request,public_envelope)
    client=client_for(settings,handler)
    await asyncio.gather(client.read('health'),client.read('reader_snapshot'),client.read('health'))
    assert peak==1
    with pytest.raises(ReaderError,match='method_not_allowed'):
        await client.read('gamestate')


@pytest.mark.parametrize('url',['http://0.0.0.0:12346','http://example.com/','http://127.0.0.1/proxy','https://127.0.0.1/','http://127.0.0.1/?method=act'])
def test_no_external_host_or_endpoint_forwarding(url):
    with pytest.raises(ValueError): GameClient(url,1)


async def test_malformed_hidden_identity_cannot_cause_error_side_channel(settings,public_envelope):
    card=public_envelope['public']['regions'][0]['cards'][0]
    card['visibility']='face_down'
    reader=Reader(settings,client_for(settings,lambda req:reply(req,public_envelope)))
    before=await reader.observe()
    card.update(rank={'secret':'SECRET'},suit=100,name='SECRET'*1000,description={'secret':'SECRET'},sell_price={'secret':'SECRET'})
    after=await reader.observe()
    assert before==after and after['status']=='ok'


async def test_mcp_tools_only_controlled_eleven(settings,public_envelope,monkeypatch):
    import balatro_agent.server as server
    monkeypatch.setattr(server,'reader',Reader(settings,client_for(settings,lambda req:reply(req,public_envelope))))
    async with Client(server.mcp) as client:
        tools=await client.list_tools()
        assert {tool.name for tool in tools.tools}=={'health','observe','wait_until_ready','act','action_status','read_notes','write_note','calculate','launch_game','close_game','recover_lost_session'}
        by_name={tool.name:tool for tool in tools.tools}
        assert set(by_name['launch_game'].input_schema['properties'])=={'operation_id','timeout_s'}
        assert set(by_name['close_game'].input_schema['properties'])=={'operation_id','observation_id','timeout_s'}
        assert all(tool.annotations.read_only_hint == (tool.name not in ('act','write_note','launch_game','close_game','recover_lost_session')) for tool in tools.tools)
        result=await client.call_tool('observe',{})
        assert result.structured_content['status']=='ok'
