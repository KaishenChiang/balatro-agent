"""Independent disk process; compare with an actual Codex read/write result."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
import sys

from balatro_agent.local_audit import canonical, safe_path
from balatro_agent.notes import NotesStore

ROOT=Path(__file__).resolve().parents[1]


def matches_delivery(note, disk, view='full'):
    # content view omits Markdown, but retains the immutable revision identity.
    # The disk parser still verifies content, request hash and canonical rendering.
    fields = ('note_id', 'kind', 'revision', 'created_utc', 'write_id', 'content')
    expected_keys = set(disk) - ({'markdown'} if view == 'content' else set())
    return (view in ('full', 'content') and set(note) == expected_keys
            and all(note.get(key) == disk[key] for key in fields)
            and type(note.get('current_revision')) is int
            and disk['revision'] <= note['current_revision'] <= 100
            and note.get('source_validation') == disk['source_validation']
            and (view == 'content' or note['markdown'] == disk['markdown']))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind',choices=['experience','TEST'],required=True)
    parser.add_argument('--note-id',required=True)
    parser.add_argument('--revision',type=int,required=True)
    parser.add_argument('--evidence',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    evidence=(ROOT/args.evidence).resolve()
    output=(ROOT/args.output).resolve()
    assert evidence.is_relative_to(ROOT/'runs') and (evidence.name=='codex-mcp.jsonl' or evidence.name.startswith(('codex-mcp-experience-', 'codex-mcp-unlock-repair-')))
    assert output.is_relative_to(ROOT/'runs/checks')
    safe_path(ROOT,*evidence.relative_to(ROOT).parts)
    safe_path(ROOT,*output.relative_to(ROOT).parts)
    rows=[json.loads(line) for line in evidence.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    assert rows[0]['evidence_type'] in ('codex_actual_mcp_construction','codex_actual_mcp_formal_acceptance')
    disk=NotesStore(ROOT/'runs/local-experience',baseline_root=ROOT/'experience').read(args.kind,[args.note_id],args.revision)['notes'][0]
    matches=[]
    for index,row in enumerate(rows,1):
        result=row.get('result',{})
        if result.get('status') != 'ok':
            continue
        if row.get('tool') == 'write_note' and result.get('write_state') != 'COMMITTED':
            continue
        delivered=result.get('notes',[]) if row.get('tool')=='read_notes' else [result.get('note',{})] if row.get('tool')=='write_note' else []
        for note in delivered:
            parameters = row.get('parameters', {})
            # Historical defaults returned full; current read and write defaults
            # return content. Either has the same independently verified identity.
            # An explicitly requested view must still match its exact field set.
            view = parameters['view'] if 'view' in parameters else 'full' if 'markdown' in note else 'content'
            if matches_delivery(note, disk, view):
                matches.append(index)
    assert matches, 'No matching actual delivered note.'
    result={'evidence_type':'independent_process_disk_notes_verification','utc':datetime.now(timezone.utc).isoformat(),
            'pid':os.getpid(),'interpreter':sys.executable,'uses_mcp_process_memory':False,
            'note_id':args.note_id,'kind':args.kind,'revision':args.revision,'current_revision':disk['current_revision'],
            'markdown_sha256':hashlib.sha256(disk['markdown'].encode('utf-8')).hexdigest(),
            'content_sha256':hashlib.sha256(canonical(disk['content']).encode('utf-8')).hexdigest(),
            'actual_evidence':str(evidence.relative_to(ROOT)),'matching_actual_lines':matches,'disk_matches_actual_delivery':True,
            'counts_as_formal_experience':args.kind=='experience' and rows[0].get('formal_game', rows[0]['evidence_type']=='codex_actual_mcp_formal_acceptance')}
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__': main()
