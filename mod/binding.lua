-- Shared public decision binding. This is not a hash of native/hidden objects.
local B = {}
local json = require('json')
local session = string.format('%08x%08x', os.time(), math.floor((os.clock()%1)*4294967295))
local epoch, last_public, last_gate = 0, nil, nil

local function canonical(v)
  if type(v) ~= 'table' then return json.encode(v) end
  local meta=getmetatable(v)
  local is_array=(meta and meta.__jsontype == 'array') or v[1] ~= nil
  local out={}
  if is_array then
    for i=1,#v do out[#out+1]=canonical(v[i]) end
    return '['..table.concat(out,',')..']'
  end
  local keys={}; for key in pairs(v) do keys[#keys+1]=key end
  table.sort(keys)
  for _,key in ipairs(keys) do out[#out+1]=json.encode(key)..':'..canonical(v[key]) end
  return '{'..table.concat(out,',')..'}'
end
B.canonical=canonical
B.session=session

function B.invalidate() epoch=epoch+1; last_public=nil end
function B.update(reader)
  local e=reader.health()
  local gate=canonical{profile=e.profile,phase=e.phase,ready=e.ready,reason=e.ready_reason}
  if last_gate and gate ~= last_gate then B.invalidate() end
  last_gate=gate
end
function B.attach(reader)
  local snapshot=reader.snapshot
  reader.snapshot=function()
    local e=snapshot()
    local fingerprint=canonical{profile=e.profile,public=e.public,compatibility=e.compatibility}
    if fingerprint ~= last_public then epoch=epoch+1; last_public=fingerprint end
    e.game_session=session
    e.observation_id='obs-'..session..'-'..epoch
    return e
  end
  local health=reader.health
  reader.health=function() local e=health(); e.game_session=session; return e end
end
return B
