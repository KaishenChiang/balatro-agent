"""Persist a Codex client's already delivered MCP call. Never calls the game.

Input is a local JSON spool made by prompts/mcp-evidence.js. The complete public
DTO is retained; client timing excludes this append and belongs to call gaps.
"""
import argparse
import json
import os
from pathlib import Path
import re

from balatro_agent.local_audit import canonical, safe_path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = {'health', 'observe', 'wait_until_ready', 'act', 'action_status',
         'read_notes', 'write_note', 'run_plan', 'calculate', 'launch_game', 'close_game', 'recover_lost_session'}


def append_call(root, run_id, payload):
    if not isinstance(run_id, str) or not re.fullmatch(r'n5-[a-z0-9-]{1,70}', run_id):
        raise ValueError('Invalid run identity')
    folder = safe_path(root, 'runs', 'optimization', run_id)
    target = safe_path(folder, 'codex-mcp.jsonl')
    payload = safe_path(root, *payload.absolute().relative_to(root).parts)
    if payload.parent != folder or not re.fullmatch(r'\.call-[0-9]{4}\.json', payload.name):
        raise ValueError('Invalid evidence spool')
    row = json.loads(payload.read_text(encoding='utf-8'))
    if row.get('tool') not in TOOLS or type(row.get('step')) is not int or not 1 <= row['step'] <= 5000:
        raise ValueError('Invalid call identity')
    if not isinstance(row.get('parameters'), dict) or not isinstance(row.get('result'), dict):
        raise ValueError('Missing actual call data')
    if payload.name != f".call-{row['step']:04d}.json":
        raise ValueError('Spool identity differs')
    rows = [json.loads(line) for line in target.read_text(encoding='utf-8').splitlines() if line.strip()]
    if not rows or rows[0].get('evidence_type') != 'codex_actual_mcp_construction' or rows[0].get('run_id') != run_id:
        raise ValueError('Missing frozen registration')
    calls = [value for value in rows if 'step' in value and 'tool' in value]
    previous = calls[-1] if calls else None
    encoded = canonical(row) + '\n'
    if previous and row['step'] == previous['step'] and canonical(row) == canonical(previous):
        duplicate = True
    elif row['step'] == (previous['step'] + 1 if previous else 1):
        # One caller owns this run. No game operations occur in this utility.
        with target.open('a', encoding='utf-8', newline='\n') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        duplicate = False
    else:
        raise ValueError('Evidence sequence conflict; preserve the spool')
    payload.unlink()
    return {'recorded_step': row['step'], 'duplicate': duplicate, 'game_called': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--payload-file', required=True)
    args = parser.parse_args()
    print(json.dumps(append_call(ROOT, args.run_id, ROOT / args.payload_file)))


if __name__ == '__main__':
    main()
