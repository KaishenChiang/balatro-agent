"""Development STDIO handshake with game transport blocked; never opens a game."""
import asyncio
import argparse
import json
import os
from pathlib import Path
import sys

from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]


def isolated_server():
    # Protocol/notes/calculation checks must not read an unrelated live game.
    os.environ['BALATRO_AGENT_CLIENT_CONTEXT'] = 'development'
    import httpx
    from balatro_agent import server
    from balatro_agent.transport import GameClient
    def blocked(request):
        raise httpx.ConnectError('development_transport_blocked', request=request)
    asyncio.run(server.reader.client.close())
    server.reader.client = GameClient(server.reader.settings.url,
        server.reader.settings.request_timeout_s, transport=httpx.MockTransport(blocked))
    server.main()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='runs/checks/stdio-smoke.json')
    args = parser.parse_args()
    output = (ROOT/args.output).resolve()
    assert output.is_relative_to(ROOT/'runs/checks')
    environment = dict(os.environ)
    environment['BALATRO_AGENT_CLIENT_CONTEXT'] = 'development'
    server = StdioServerParameters(command=sys.executable,args=[str(Path(__file__).resolve()),'--isolated-server'],cwd=ROOT,env=environment)
    async with Client(server) as client:
        tools = await client.list_tools()
        # English-facing metadata must not require understanding Chinese prose.
        assert all(tool.description and not any('\u4e00' <= ch <= '\u9fff' for ch in tool.description) for tool in tools.tools)
        assert {tool.name for tool in tools.tools} == {'health','observe','wait_until_ready','act','action_status','read_notes','write_note','run_plan','calculate','launch_game','close_game','recover_lost_session'}
        assert all(tool.annotations.read_only_hint == (tool.name not in ('act','write_note','run_plan','launch_game','close_game','recover_lost_session')) for tool in tools.tools)
        actions = next(tool for tool in tools.tools if tool.name == 'act').input_schema['properties']['action']['enum']
        assert 'view' in next(tool for tool in tools.tools if tool.name == 'read_notes').input_schema['properties']
        assert {'select_setup_option','next_setup_choices','previous_setup_choices','open_options','open_settings',
                'next_game_speed','previous_game_speed','play','discard'} <= set(actions)
        results = {}
        for tool in ('health','observe','wait_until_ready'):
            result = await client.call_tool(tool,{'timeout_s':0.01} if tool=='wait_until_ready' else {})
            assert not result.is_error and result.structured_content is not None
            # Only safe service results, no HTTP body or exception details.
            results[tool] = result.structured_content
            assert results[tool]['status'] == 'disconnected'
        assert results['health'].get('primary_experience_note') == 'EXP-GENERAL-GUIDE'
        assert results['health'].get('notes_policy') == 'local-over-baseline-v1'
        assert results['health'].get('notes_write_scope') == 'local_only'
        assert results['health'].get('notes_default_view') == 'content'
        assert results['health'].get('run_plan_protocol') == 'run-plan-v1'
        # Isolated development notes; never writes to the formal experience root.
        results['read_notes'] = (await client.call_tool('read_notes', {})).structured_content
        results['read_notes_content'] = (await client.call_tool('read_notes', {'view':'content'})).structured_content
        assert results['read_notes_content']['status']=='ok'
        assert all('markdown' not in note for note in results['read_notes_content']['notes'])
        results['read_notes_index'] = (await client.call_tool('read_notes', {'view':'index','kind':'experience'})).structured_content
        assert results['read_notes_index']['status'] == 'ok' and results['read_notes_index']['discovery_only']
        results['run_plan'] = (await client.call_tool('run_plan', {})).structured_content
        assert results['run_plan']['status'] == 'run_scope_missing' and not results['run_plan']['game_action_submitted']
        results['calculate'] = (await client.call_tool('calculate', {'operation':'quotient','inputs':{'values':[300,3]}})).structured_content
        content = {'sources':[{'run_id':'test-stdio','steps':[1]}], 'facts':['TEST：开发协议握手数据。'],
                   'interpretation':['仅验证持久化结构，不是游戏经验。'], 'conditions':['TEST隔离目录。'],
                   'counterexamples':['不计正式验收。'], 'confidence':'low', 'revision_reason':'TEST创建。'}
        import uuid
        results['write_note'] = (await client.call_tool('write_note', {'note_id':'TEST-STDIO-'+uuid.uuid4().hex[:8].upper(),
            'kind':'TEST','content':content,'expected_revision':0,'write_id':'stdio-'+uuid.uuid4().hex})).structured_content
        assert all(results[tool]['status']=='ok' for tool in ('read_notes','write_note','calculate'))
        report = {'evidence_type':'development_stdio_only','codex_actual_invocation':False,
                  'game_transport_blocked':True,
                  'tools':[tool.name for tool in tools.tools],'declared_actions':actions,'results':results}
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'stdio_handshake':'passed','tools':report['tools'],'statuses':{key:value['status'] for key,value in results.items()},'R3':'not_verified'},ensure_ascii=False))


if __name__ == '__main__':
    if sys.argv[1:] == ['--isolated-server']:
        isolated_server()
    else:
        asyncio.run(main())
