async function recordMcp(tool, parameters) {
  // Used only inside the host's functions.exec. The caller supplies every
  // decision; this wrapper calls exactly one actual project MCP tool.
  const ctx = load('balatro_evidence_context');
  if (!ctx || !/^n5-[a-z0-9-]{1,70}$/.test(ctx.runId)) throw Error('Register evidence first');
  if (typeof ctx.workspaceRoot !== 'string' || /[\r\n]/.test(ctx.workspaceRoot)) throw Error('Missing workspace root');
  if (load('balatro_evidence_pending')) throw Error('Persist previous delivery before continuing');
  const allowed = ['health','observe','wait_until_ready','act','action_status','read_notes',
    'write_note','calculate','launch_game','close_game','recover_lost_session'];
  if (!allowed.includes(tool)) throw Error('Unsupported tool');
  const method = 'mcp__balatro_agent__' + tool;
  if (typeof tools[method] !== 'function') throw Error('Actual MCP tool is not loaded');
  const started = Date.now();
  let raw;
  try { raw = await tools[method](parameters); }
  catch (error) {
    raw = {isError:true}; // Host exception text is not a public game DTO.
  }
  const ended = Date.now();
  let dto = raw.structuredContent;
  if (!dto && Array.isArray(raw.content)) {
    const block = raw.content.find(value => value.type === 'text');
    if (block) { try { dto = JSON.parse(block.text); } catch (error) {} }
  }
  if (!dto && !raw.content && !raw.isError) dto = raw;
  const hostError = !dto;
  if (hostError) dto = {status:'external_tool_error',isError:true};
  const step = (ctx.step || 0) + 1;
  const row = {step,tool,parameters,result:dto,
    client_started_utc:new Date(started).toISOString(),client_finished_utc:new Date(ended).toISOString(),
    client_tool_ms:ended-started,inter_call_gap_ms:ctx.finishedAt == null ? null : started-ctx.finishedAt,
    current_chat_id:ctx.threadId || 'not_exposed',formal_game:false};
  if (hostError) row.evidence_type = 'host_tool_error_not_mcp_delivery';
  store('balatro_evidence_pending',row);
  store('balatro_last_delivery',dto);
  const file = 'runs/optimization/' + ctx.runId + '/.call-' + String(step).padStart(4,'0') + '.json';
  const patch = '*** Begin Patch\n*** Add File: ' + ctx.workspaceRoot.replace(/\\/g,'/').replace(/\/$/,'') + '/' + file + '\n+' + JSON.stringify(row) + '\n*** End Patch';
  const staged = await tools.apply_patch(patch);
  if (staged && staged.isError) throw Error('Evidence spool failed; stop and preserve delivery');
  const written = await tools.exec_command({cmd:'.venv/Scripts/python.exe scripts/client_evidence.py --run-id ' + ctx.runId + ' --payload-file ' + file,workdir:ctx.workspaceRoot,max_output_tokens:100});
  if (written.exit_code !== 0) throw Error('Evidence append failed; preserve delivery and spool');
  store('balatro_evidence_context',{...ctx,step,finishedAt:ended});
  store('balatro_evidence_pending',null);
  return dto;
}
