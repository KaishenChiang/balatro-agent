"""Read safe evidence only; match actual construction/formal calls with logs."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from balatro_agent.local_audit import canonical, safe_path
from balatro_agent.actions import ActionRequest
from balatro_agent.recovery import RetirementResponse
from balatro_agent.run_plan import PlanWrite

ROOT=Path(__file__).resolve().parents[1]
LIFECYCLE={'launch_game','close_game'}
TOOLS={'health','observe','wait_until_ready','act','action_status','read_notes','write_note','run_plan','calculate','recover_lost_session'}|LIFECYCLE
HEALTH_WRAPPER_METADATA = {
    'unlock_input_protocol': 'native-overlay-v1',
    'session_recovery_protocol': 'lost-session-v1',
    'primary_experience_note': 'EXP-GENERAL-GUIDE',
    'notes_policy': 'local-over-baseline-v1',
    'notes_write_scope': 'local_only',
    'notes_default_view': 'content',
    'run_plan_protocol': 'run-plan-v1',
}


def host_error(row):
    return (row.get('evidence_type')=='host_tool_error_not_mcp_delivery'
            and row.get('result',{}).get('status')=='external_tool_error'
            and row['result'].get('isError') is True)


def json_numeric_value(value):
    """JSON clients may spell 50.0 as 50; never round or coerce booleans."""
    if isinstance(value, dict):
        return {key: json_numeric_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_numeric_value(item) for item in value]
    if isinstance(value, float) and abs(value) <= 9007199254740991 and value.is_integer():
        return int(value)
    return value


def comparison_value(tool, value):
    # Older server wrappers appended fixed protocol identifiers AFTER the
    # reader journal. Compare all state fields exactly; label these constants
    # separately rather than claiming they were present in the old journal.
    if tool=='health':
        value=dict(value)
        for key,expected in HEALTH_WRAPPER_METADATA.items():
            if key in value:
                assert value.pop(key)==expected
    return canonical(json_numeric_value(value))


def retirement_receipt(root, row):
    """Validate the durable archive; retirement never proves completion."""
    request=row['parameters']; recovery_id=request.get('recovery_id')
    try:
        # Validation constrains the ID before it becomes a file name.
        response=RetirementResponse.model_validate(row['result']).model_dump()
        assert response['recovery_id']==recovery_id
        path=safe_path(root,'runs','live','executor','retired-sessions',recovery_id+'.json')
        archive=json.loads(path.read_text(encoding='utf-8'))
        assert archive['request']==request
        saved=RetirementResponse.model_validate(archive['response']).model_dump()
        assert not saved['duplicate']
        assert {**response,'duplicate':False}==saved
        before=archive['checkpoint_before']; pending=before['pending']
        assert archive['checkpoint_sha256']==hashlib.sha256(canonical(before).encode()).hexdigest()
        assert pending['action_id']==request['action_id']
        assert pending['observation_id'].split('-')[1]==response['old_session']
        assert response['old_session']!=response['current_session']
        observation=archive['current_observation']
        assert observation['profile']==2 and observation['ready']
        assert observation['observation_id']==request['observation_id']
        assert observation['observation_id'].split('-')[1]==response['current_session']
        queried=archive['queried_status']
        assert queried['state']=='UNKNOWN' and queried['reason']=='record_not_found'
        assert queried['action_id']==request['action_id']
        assert queried['game_session']==response['current_session']
        return {'file':path.relative_to(root).as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()},None
    except (OSError, ValueError, TypeError, KeyError, AssertionError):
        return None,'missing_or_inconsistent_retirement_receipt'


def read(path):
    for index,line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(),1):
        if line.strip(): yield index,json.loads(line)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence',required=True);p.add_argument('--output',required=True)
    args=p.parse_args()
    evidence=(ROOT/args.evidence).resolve();output=(ROOT/args.output).resolve()
    assert evidence.is_relative_to(ROOT/'runs') and output.is_relative_to(ROOT/'runs/checks')
    safe_path(ROOT,*evidence.relative_to(ROOT).parts)
    snapshot=evidence.read_bytes();source=list(read(evidence))
    assert source[0][1]['evidence_type'] in ('codex_actual_mcp_construction','codex_actual_mcp_formal_acceptance')
    attempts=[(line,row) for line,row in source if row.get('tool') in TOOLS]
    host_errors=[{'line':line,'tool':row['tool'],'counts_as_mcp_delivery':False}
                 for line,row in attempts if host_error(row)]
    wanted=[(line,row) for line,row in attempts if not host_error(row)]
    assert wanted
    deliveries=defaultdict(list);intents=defaultdict(list);note_intents=defaultdict(list);plan_intents=defaultdict(list);lifecycle_intents=defaultdict(list)
    paths=list((ROOT/'runs/live').glob('reader-*.jsonl'))+list((ROOT/'runs/live/executor').glob('actions-*.jsonl'))+list((ROOT/'runs/live/local').glob('local-*.jsonl'))
    for path in sorted(paths):
        for line,row in read(path):
            if row.get('client_context')!='codex_config': continue
            ref={'file':str(path.relative_to(ROOT)),'line':line,'utc':row.get('utc',row.get('delivered_utc'))}
            kind=row.get('kind');tool=row.get('tool')
            if kind=='intent' and tool=='write_note': note_intents[canonical(row['value'])].append(ref)
            elif kind=='intent' and tool=='run_plan': plan_intents[canonical(row['value'])].append(ref)
            elif kind in ('intent','existing_window_intent') and tool in LIFECYCLE:
                lifecycle_intents[(tool,row['value']['operation_id'])].append(ref)
            elif kind=='intent': intents[canonical(row['value']['request'])].append(ref)
            elif kind in ('delivered_act','delivered_action_status'):
                action_tool = 'act' if kind == 'delivered_act' else 'action_status'
                deliveries[action_tool].append((ref,comparison_value(action_tool,row['value'])))
            elif kind=='delivered' and tool in TOOLS: deliveries[tool].append((ref,comparison_value(tool,row['value'])))
            elif tool in TOOLS and 'result' in row: deliveries[tool].append((ref,comparison_value(tool,row['result'])))
    for stream in deliveries.values(): stream.sort(key=lambda pair:pair[0]['utc'])
    offsets=defaultdict(int);matches=[];missing=[];missing_intents=[];missing_receipts=[]
    first=wanted[0][1]
    anchors=[ref for ref,result in deliveries[first['tool']] if result==comparison_value(first['tool'],first['result'])]
    assert anchors
    anchor=min(ref['utc'] for ref in anchors)
    for tool in deliveries: deliveries[tool]=[(ref,result) for ref,result in deliveries[tool] if ref['utc']>=anchor]
    for line,row in wanted:
        tool=row['tool'];expected=comparison_value(tool,row['result']);available=deliveries[tool]
        match=next((i for i in range(offsets[tool],len(available)) if available[i][1]==expected),None)
        if match is None: missing.append({'line':line,'tool':tool});continue
        offsets[tool]=match+1
        item={'evidence_line':line,'tool':tool,'delivery':available[match][0]}
        if tool=='health':
            item['fixed_wrapper_metadata_checked_separately']={k:row['result'][k] for k in
                HEALTH_WRAPPER_METADATA if k in row['result']}
        if tool in ('act','write_note'):
            request=json.loads(canonical(row['parameters']))
            if tool=='act':
                if request.get('view') in ('compact', 'full'):
                    request.pop('view')
                try:
                    normalized=ActionRequest.model_validate(request).model_dump()
                except (ValueError, TypeError):
                    # Inputs rejected before the executor journal have no valid
                    # normalized request; retain exact input for the audit.
                    normalized=request
                if canonical(normalized)!=canonical(row['parameters']):
                    item['request_normalization']='ActionRequest'
                request=normalized
            if tool=='write_note':
                request.setdefault('kind','experience')
                if request.get('view') in ('content', 'full'):
                    request.pop('view')
            candidates=(intents if tool=='act' else note_intents)[canonical(request)]
            required=row['result'].get('submitted') is not False if tool=='act' else row['result'].get('write_state')=='COMMITTED'
            if candidates: item['intent']=candidates.pop(0)
            elif required: missing_intents.append({'line':line,'tool':tool})
        elif tool=='run_plan' and row['parameters'].get('mode')=='write':
            request={key:value for key,value in row['parameters'].items() if key!='mode'}
            try:
                request=PlanWrite.model_validate(request).model_dump()
            except (ValueError,TypeError):
                pass
            candidates=plan_intents[canonical(request)]
            required=row['result'].get('write_state')=='COMMITTED' and not row['result'].get('duplicate')
            if required and candidates: item['intent']=candidates.pop(0)
            elif required: missing_intents.append({'line':line,'tool':tool})
        elif tool in LIFECYCLE:
            result=row['result'];operation_id=row['parameters'].get('operation_id')
            candidates=lifecycle_intents[(tool,operation_id)]
            required=not result.get('duplicate') and (result.get('submitted') is not False
                      or result.get('reason')=='already_running')
            if required and candidates: item['intent']=candidates.pop(0)
            elif required: missing_intents.append({'line':line,'tool':tool})
        elif tool=='recover_lost_session' and row['result'].get('write_state')=='COMMITTED':
            receipt,error=retirement_receipt(ROOT,row)
            if error: missing_receipts.append({'line':line,'tool':tool,'reason':error})
            else: item['retirement_receipt']=receipt
        matches.append(item)
    assert evidence.read_bytes()==snapshot
    result={'evidence_type':'actual_codex_safe_delivery_comparison','utc':datetime.now(timezone.utc).isoformat(),
            'evidence':str(evidence.relative_to(ROOT)),'sha256':hashlib.sha256(snapshot).hexdigest(),
            'tool_attempts':len(attempts),'host_errors':host_errors,'actual_calls':len(wanted),'matches':matches,
            'missing_deliveries':missing,'missing_required_intents':missing_intents,'missing_retirement_receipts':missing_receipts,
            'comparison_passed':not missing and not missing_intents and not missing_receipts,
            'scope':'Exact public JSON values and durable intent/receipt comparison; safe integral float spelling normalized, booleans distinct; fixed health wrapper protocol constants checked separately.',
            'proves_game_strategy_or_formal_completion':False}
    safe_path(ROOT,*output.relative_to(ROOT).parts)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:result[key] for key in ('actual_calls','comparison_passed','missing_deliveries','missing_required_intents')}))
    return 0 if result['comparison_passed'] else 1


if __name__=='__main__':raise SystemExit(main())
