-- Controlled native operations at the post-update submission boundary.
-- No upstream full state, strategy, debug writes or save/load endpoints.
local E = {}
local json = require('json')
-- The fixed loader clears current_mod after initialization. Capture ownership
-- now so profile/journal access never depends on another Mod's load context.
local mod_path = assert(SMODS.current_mod and SMODS.current_mod.path, 'Missing Mod path')
local records, active, scope, input = {}, nil, nil, nil
local notice_navigation={open_run_setup=true,continue_run=true,start_run=true,main_menu=true}
local bootstrap_body
local owner = setmetatable({}, {__mode='k'})
local regions={hand='hand',jokers='jokers',consumables='consumeables',shop_jokers='shop_jokers',
  shop_vouchers='shop_vouchers',shop_boosters='shop_booster',pack='pack_cards'}
local no_params={sort_rank=true,sort_suit=true,reroll=true,cash_out=true,next_round=true,
  skip_pack=true,open_run_setup=true,next_setup_page=true,previous_setup_page=true,start_run=true,continue_run=true,
  run_info=true,deck_info=true,close_menu=true,main_menu=true,continue_endless=true,
  next_setup_choices=true,previous_setup_choices=true,open_options=true,open_settings=true,next_game_speed=true,previous_game_speed=true}
local targeted={buy=true,buy_and_use=true,sell=true,use=true,select_pack_card=true}
local phases={sort_rank={hand=true},sort_suit={hand=true},play={hand=true},discard={hand=true},
  reroll={shop=true},cash_out={round_eval=true},next_round={shop=true},skip_pack={pack=true},
  buy={shop=true},buy_and_use={shop=true},sell={shop=true,hand=true,blind_select=true,pack=true},
  use={shop=true,hand=true,blind_select=true,pack=true},select_pack_card={pack=true},
  open_run_setup={main_menu=true,terminal=true,menu=true,shop=true,round_eval=true,blind_select=true,hand=true,pack=true},next_setup_page={main_menu=true,menu=true},
  previous_setup_page={main_menu=true,menu=true},start_run={main_menu=true,menu=true},continue_run={main_menu=true},
  run_info={hand=true,blind_select=true,shop=true,pack=true,round_eval=true},
  deck_info={hand=true,blind_select=true,shop=true,pack=true,round_eval=true},close_menu={menu=true,main_menu=true},
  main_menu={terminal=true,menu=true},continue_endless={terminal=true},
  next_setup_choices={main_menu=true,menu=true},previous_setup_choices={main_menu=true,menu=true},
  open_options={main_menu=true,menu=true,hand=true,shop=true,blind_select=true,pack=true,round_eval=true,terminal=true},
  open_settings={main_menu=true,menu=true},next_game_speed={main_menu=true,menu=true},previous_game_speed={main_menu=true,menu=true},
  select_blind={blind_select=true},skip_blind={blind_select=true}}
local function array() return setmetatable({}, {__jsontype='array'}) end
local function native_start_body(fn)
  -- Fixed Steamodded wraps this method twice before Mods finish loading.
  -- Follow only its two named function closures; never inspect game data.
  local wrappers={['=[SMODS _ "src/utils/run_select.lua"]']='start_run',
    ['=[SMODS _ "src/utils.lua"]']='game_start_run'}
  local seen={}
  for _=1,8 do
    if type(fn)~='function' or seen[fn] then return nil end
    seen[fn]=true
    local info=debug.getinfo(fn,'Su')
    if not info or info.what~='Lua' then return nil end
    local up=wrappers[info.source]
    if not up then
      if info.source=='@game.lua' then return info end
      return nil -- Unknown wrappers must not broaden the cosmetic exclusion.
    end
    local previous
    for i=1,info.nups do
      local name,value=debug.getupvalue(fn,i)
      if name==up and type(value)=='function' then previous=value; break end
    end
    if not previous then return nil end
    fn=previous
  end
end
-- Native main_menu resets REAL/TOTAL. UPTIME remains monotonic across menus.
local function clock() return G.TIMERS and (G.TIMERS.UPTIME or G.TIMERS.REAL) or os.clock() end
local function mark_callback(rec)
  rec.callback=true; rec.callback_at=rec.callback_at or clock()
end
local function valid_id(v) return type(v)=='string' and #v>=1 and #v<=80 and v:match('^[%w][%w_.:%-]*$') ~= nil end
local function keys(t, allowed)
  if type(t) ~= 'table' then return false end
  for k in pairs(t) do if not allowed[k] then return false end end
  for k in pairs(allowed) do if t[k] == nil then return false end end
  return true
end
local function integer(v) return type(v)=='number' and v==v and v%1==0 and v>=0 and v<=200 end
local function indices(t)
  if type(t)~='table' or #t>200 then return false end
  local seen={}; local count=0
  for k,v in pairs(t) do
    if not integer(k) or k<1 or k>#t or not integer(v) or seen[v] then return false end
    seen[v]=true; count=count+1
  end
  return count==#t
end
local function normalized(req)
  local fields={action=true,parameters=true,observation_id=true,action_id=true,reason=true,experience_refs=true,
    expected_profile=true,game_session=true}
  if not keys(req,fields) or not valid_id(req.action_id) or type(req.action)~='string'
     or type(req.observation_id)~='string' or not req.observation_id:match('^obs%-%x+%-%d+$')
     or type(req.reason)~='string' or #req.reason<1 or #req.reason>4096
     or type(req.experience_refs)~='table' or #req.experience_refs>30 then return nil,'invalid_request' end
  if not keys(req.expected_profile,{profile=true,policy=true})
     or not integer(req.expected_profile.profile) or req.expected_profile.profile<1 or req.expected_profile.profile>3
     or req.expected_profile.policy~='current-native-v1' then return nil,'invalid_request' end
  for k,v in pairs(req.experience_refs) do
    if type(k)~='number' or k<1 or k>#req.experience_refs or k%1~=0 or type(v)~='string' or #v<1 or #v>400 then return nil,'invalid_request' end
  end
  local p=req.parameters
  if req.action=='play' or req.action=='discard' then
    if not keys(p,{}) then
      if not keys(p,{positions=true}) or not indices(p.positions) or #p.positions<1 or #p.positions>5 then return nil,'invalid_parameters' end
      table.sort(p.positions)
    end
  elseif req.action=='select_setup_option' then
    if not keys(p,{kind=true,position=true}) or (p.kind~='deck' and p.kind~='stake') or not integer(p.position) then return nil,'invalid_parameters' end
  elseif no_params[req.action] then
    if not keys(p,{}) then return nil,'invalid_parameters' end
  elseif targeted[req.action] then
    if not keys(p,{region=true,position=true}) or not regions[p.region] or p.region=='hand' or not integer(p.position) then return nil,'invalid_parameters' end
  elseif req.action=='select' or req.action=='reorder' then
    local key=req.action=='select' and 'positions' or 'order'
    if not keys(p,{region=true,[key]=true}) or not regions[p.region] or not indices(p[key]) then return nil,'invalid_parameters' end
    if req.action=='reorder' and p.region~='hand' and p.region~='jokers' and p.region~='consumables' then return nil,'invalid_parameters' end
    if req.action=='select' then table.sort(p.positions) end
  elseif req.action=='select_blind' or req.action=='skip_blind' then
    if not keys(p,{blind_slot=true}) or (p.blind_slot~='Small' and p.blind_slot~='Big' and p.blind_slot~='Boss') then return nil,'invalid_parameters' end
  else return nil,'unknown_action' end
  local refs,seen=array(),{}
  for _,v in ipairs(req.experience_refs) do if not seen[v] then refs[#refs+1]=v; seen[v]=true end end
  table.sort(refs); req.experience_refs=refs
  return req
end
local function journal(kind,value)
  -- This dedicated journal contains only whitelisted requests/results.
  local ok=pcall(function()
    local f=assert(io.open(mod_path..'executor-journal.jsonl','a'))
    local written=f:write(json.encode{kind=kind,value=value}..'\n')
    local flushed=f:flush(); local closed=f:close()
    assert(written and flushed and closed)
  end)
  return ok
end
local function response(rec,duplicate)
  local timing
  if rec.started then
    timing={native_elapsed_ms=rec.completed_elapsed_ms or math.max(0,math.floor((clock()-rec.started)*1000))}
    if rec.callback_to_completed_ms then timing.callback_to_completed_ms=rec.callback_to_completed_ms end
  end
  return {state=rec.state,reason=rec.reason,action_id=rec.req and rec.req.action_id,
    observation_id=rec.req and rec.req.observation_id,game_session=BA_BINDING.session,
    submitted=rec.submitted,execution_profile=rec.profile,duplicate=duplicate==true,callback_confirmed=rec.callback==true,
    related_events_complete=rec.events_done==true,completion_signal=rec.signal,snapshot=rec.snapshot,timing=timing,
    required_action=rec.state=='AWAITING_INPUT' and 'close_menu' or nil,
    input_for_action_id=rec.input_for and rec.input_for.req.action_id or nil}
end
local function reject(req,reason)
  local safe={}
  if type(req)=='table' then
    if valid_id(req.action_id) then safe.action_id=req.action_id end
    if type(req.observation_id)=='string' and #req.observation_id<=80 and req.observation_id:match('^obs%-%x+%-%d+$') then safe.observation_id=req.observation_id end
  end
  return response({state='REJECTED',reason=reason,req=safe,submitted=false})
end
local function public_region(snapshot,name)
  for _,r in ipairs(snapshot.public.regions) do if r.name==name then return r end end
end
local function selected_matches(area, positions)
  local wanted={}; for _,i in ipairs(positions) do wanted[i+1]=true end
  for i,c in ipairs(area.cards) do if (c.highlighted==true) ~= (wanted[i]==true) then return false end end
  return true
end
local function selection_plan(req,snapshot)
  local p=req.parameters
  if snapshot.public.phase~='hand' and snapshot.public.phase~='pack' and snapshot.public.phase~='shop'
     and snapshot.public.phase~='blind_select' then return nil,'wrong_phase' end
  local r=public_region(snapshot,p.region); local area=G[regions[p.region]]
  if not r or not area or not area.cards or #r.cards~=#area.cards then return nil,'invalid_target' end
  if type(r.selection_limit)~='number' then return nil,'unsupported_rule' end
  if #p.positions>r.selection_limit then return nil,'selection_restricted' end
  local wanted={}; local visible={}
  for _,c in ipairs(r.cards) do visible[c.position]=c end
  for _,i in ipairs(p.positions) do if not visible[i] or not area.cards[i+1] then return nil,'invalid_target' end; wanted[i+1]=true end
  local changes={}
  for i,c in ipairs(area.cards) do
    if not visible[i-1] or type(c.click)~='function' or type(area.can_highlight)~='function' or not area:can_highlight(c) then return nil,'unsupported_rule' end
    if not c.states or not c.states.click or c.states.click.can~=true then return nil,'button_unavailable' end
    if c.highlighted and not wanted[i] then
      -- Back-card identity must not affect request/refusal or reveal hidden flags.
      if visible[i-1].visibility=='face_down' then return nil,'unsupported_rule' end
      if c.ability and c.ability.forced_selection then return nil,'selection_restricted' end
      changes[#changes+1]=c
    end
  end
  for _,i in ipairs(p.positions) do if not area.cards[i+1].highlighted then changes[#changes+1]=area.cards[i+1] end end
  return function(rec)
    for _,c in ipairs(changes) do c:click() end
    rec.selection_area=area; rec.selection_positions=p.positions
    mark_callback(rec)
  end
end
local function reorder_plan(req,snapshot)
  if snapshot.public.phase~='hand' and snapshot.public.phase~='pack' and snapshot.public.phase~='shop'
     and snapshot.public.phase~='blind_select' then return nil,'wrong_phase' end
  local p=req.parameters; local area=G[regions[p.region]]; local r=public_region(snapshot,p.region)
  if not r or not area or not area.cards or #r.cards~=#area.cards or #p.order~=#area.cards then return nil,'invalid_target' end
  local desired={}
  for _,i in ipairs(p.order) do
    local c=area.cards[i+1]
    if not c or not c.T or not c.container or not c.container.T or not c.states or not c.states.drag
       or not c.states.drag.can or c.pinned or type(c.drag)~='function' or type(c.stop_drag)~='function'
       or type(area.align_cards)~='function' then return nil,'unsupported_rule' end
    desired[#desired+1]=c
  end
  if not G.CONTROLLER.cursor_position or not G.TILESCALE or not G.TILESIZE or not point_translate or not point_rotate then return nil,'unsupported_rule' end
  return function(rec)
    -- Each insertion follows native pointer drag and area alignment. Do not
    -- replace cards arrays or touch shared card/center definition order fields.
    for i,c in ipairs(desired) do
      if area.cards[i]~=c then
        local anchor=area.cards[i]
        local px={x=G.CONTROLLER.cursor_position.x/(G.TILESCALE*G.TILESIZE),y=G.CONTROLLER.cursor_position.y/(G.TILESCALE*G.TILESIZE)}
        point_translate(px,{x=-c.container.T.w/2,y=-c.container.T.h/2}); point_rotate(px,c.container.T.r)
        point_translate(px,{x=c.container.T.w/2-c.container.T.x,y=c.container.T.h/2-c.container.T.y})
        local target_x=anchor.T.x+anchor.T.w/2-c.T.w/2-0.1
        c.states.drag.is=true
        local ok=pcall(function() c:drag{x=px.x-target_x,y=px.y-c.T.y}; area:align_cards(); c:stop_drag() end)
        c.states.drag.is=false
        if not ok then error('Native reorder failed') end
        area:align_cards()
      end
    end
    rec.order_area=area; rec.order_cards=desired; mark_callback(rec)
  end
end
local function space_available(card)
  local set=card.ability and card.ability.set
  if set=='Default' or set=='Enhanced' or set=='Voucher' or set=='Booster' then return true end
  local area=card.ability and card.ability.consumeable and G.consumeables or G.jokers
  local negative=card.edition and card.edition.negative and 1 or 0
  return area and #area.cards < area.config.card_limit+negative
end
local native_decks={b_red=true,b_blue=true,b_yellow=true,b_green=true,b_black=true,b_magic=true,b_nebula=true,
  b_ghost=true,b_abandoned=true,b_checkered=true,b_zodiac=true,b_painted=true,b_anaglyph=true,b_plasma=true,b_erratic=true}
local native_stakes={stake_white=true,stake_red=true,stake_green=true,stake_black=true,stake_blue=true,
  stake_purple=true,stake_orange=true,stake_gold=true}
local function random_native_setup(snapshot)
  local choices=SMODS.RunSelect and SMODS.RunSelect.Setup and SMODS.RunSelect.Setup.choices
  local back=G.GAME and G.GAME.viewed_back and G.GAME.viewed_back.effect and G.GAME.viewed_back.effect.center
  local deck_key,stake_key
  if choices then
    if choices.enable_seed or choices.challenge then return false end
    deck_key,stake_key=choices.deck_choice,choices.stake_choice
    back=G.P_CENTERS and G.P_CENTERS[deck_key]
  else
    if G.run_setup_seed or G.forced_seed or G.challenge_tab then return false end
    deck_key=back and back.key
    local names={'white','red','green','black','blue','purple','orange','gold'}
    local value=G.viewed_stake or G.forced_stake or 1
    stake_key=names[value] and 'stake_'..names[value]
  end
  if not native_decks[deck_key] or not native_stakes[stake_key] or not back
     or back.unlocked~=true or back.discovered==false then return false end
  local stake=G.P_STAKES and G.P_STAKES[stake_key]
  if not stake then return false end
  if choices then
    local page=SMODS.RunSelect.Pages and SMODS.RunSelect.Pages.stake_choice
    if not page or type(page.is_stake_unlocked)~='function' or not page.is_stake_unlocked(stake) then return false end
  elseif not G.PROFILES or not G.PROFILES[G.SETTINGS.profile] then return false
  else
    -- Native old selector has already materialized its selected unlocked stake.
    -- Higher stakes are supported through the fixed RunSelect gate above only.
    if stake_key~='stake_white' then return false end
  end
  local setup=snapshot.public.setup
  return setup and setup.availability=='observed'
     and setup.deck_name==localize{type='name_text',set='Back',key=deck_key}
     and setup.stake_name==localize{type='name_text',set='Stake',key=stake_key}
end
local function setup_selection_plan(req,snapshot)
  local p=req.parameters
  if snapshot.public.phase~='main_menu' and snapshot.public.phase~='menu' then return nil,'wrong_phase' end
  local page=p.kind=='deck' and 'deck_choice' or 'stake_choice'
  if not snapshot.public.setup or snapshot.public.setup.page~=page then return nil,'wrong_phase' end
  local target
  for _,binding in ipairs(BA_READER.setup_bindings or {}) do
    if binding.kind==p.kind and binding.position==p.position then target=binding end
  end
  if not target or not target.option.enabled then return nil,'invalid_target' end
  local card=target.card; local choice=card.params and card.params.run_select_selection_choice
  local center=card.config and card.config.center
  if not choice or choice[2]~=page or type(card.click)~='function' or not center then return nil,'unsupported_rule' end
  local key=p.kind=='stake' and card.params.stake or center.key
  if p.kind=='deck' and (not native_decks[key] or center.unlocked~=true or center.discovered==false)
     or p.kind=='stake' and (not native_stakes[key] or card.params.stake_chip_locked) then return nil,'unsupported_rule' end
  return function(rec)
    card:click(); mark_callback(rec); rec.setup_choice_page=page; rec.setup_choice_key=key
  end
end
local function ui_plan(req,snapshot)
  if not phases[req.action] or not phases[req.action][snapshot.public.phase] then return nil,'wrong_phase' end
  local found
  for _,binding in ipairs(BA_READER.bindings or {}) do
    local a=binding.action; local p=req.parameters
    if a.name==req.action and a.region==p.region and a.position==p.position and a.blind_slot==p.blind_slot and a.enabled then
      if found then return nil,'button_unavailable' end
      found=binding
    end
  end
  if not found then return nil,'button_unavailable' end
  local node=found.node; local native=found.card
  if node and (type(node.click)~='function' or not node.config or type(G.FUNCS[node.config.button])~='function') then return nil,'unsupported_rule' end
  if native and type(native.click)~='function' then return nil,'unsupported_rule' end
  local expected_speed
  if req.action=='next_game_speed' or req.action=='previous_game_speed' then
    local cycle=node and node.config.ref_table
    if not cycle or cycle.opt_callback~='change_gamespeed' or not cycle.options or #cycle.options~=4
       or cycle.options[1]~=0.5 or cycle.options[2]~=1 or cycle.options[3]~=2 or cycle.options[4]~=4
       or not integer(cycle.current_option) or cycle.current_option<1 or cycle.current_option>4 then return nil,'unsupported_rule' end
    local next_index=((cycle.current_option+(req.action=='next_game_speed' and 1 or -1)-1)%4)+1
    expected_speed=cycle.options[next_index]
  end
  local card=node and node.config.ref_table
  if req.action=='buy' and card and not space_available(card) then return nil,'insufficient_capacity' end
  -- Native Card.check_use produces an alert for full Ankh capacity. Detect
  -- that known gate before clicking; never run its side effect during validation.
  if (req.action=='use' or req.action=='buy_and_use') and card and card.ability and card.ability.name=='Ankh'
     and #G.jokers.cards>=G.jokers.config.card_limit then return nil,'insufficient_capacity' end
  if req.action=='play' or req.action=='discard' then
    local area=G.hand; local count=area and area.highlighted and #area.highlighted or 0
    if req.action=='play' and G.play and G.play.cards and #G.play.cards>0 then return nil,'not_ready' end
    if count<1 or count>(area.config.highlighted_limit or 5) or (req.action=='play' and count>5)
      or (req.action=='discard' and G.GAME.current_round.discards_left<=0) then return nil,'selection_restricted' end
    -- Forced selection is preserved by Card.click/remove_from_highlighted;
    -- do not inspect a face-down card's hidden ability to add a refusal.
  end
  if req.action=='start_run' then
    -- An enabled native New Run button may replace a saved/unfinished run.
    -- Observation/profile, pending-action and native setup checks still apply.
    if not random_native_setup(snapshot) then return nil,'unsupported_rule' end
  end
  return function(rec)
    rec.preference_speed=expected_speed
    -- Native continue_unlock removes this overlay and may synchronously show
    -- another queued unlock. Closing this one does not dismiss the next one.
    if req.action=='close_menu' and node and node.config.button=='continue_unlock' then
      rec.unlock_overlay=G.OVERLAY_MENU
    end
    if native then native:click(); mark_callback(rec)
    else
      local name=node.config.button; local original=G.FUNCS[name]
      G.FUNCS[name]=function(...)
        mark_callback(rec)
        return original(...)
      end
      local ok=pcall(function() node:click() end)
      G.FUNCS[name]=original
      if not ok then error('Native callback failed') end
      if req.action=='open_run_setup' and name=='options' then
        rec.setup_navigation=true; rec.options_overlay=G.OVERLAY_MENU; rec.options_game=G.GAME
        G.E_MANAGER:add_event(Event({blocking=false,blockable=false,func=function()
          if G.GAME~=rec.options_game or G.OVERLAY_MENU~=rec.options_overlay then
            rec.failed='native_error'; return true
          end
          local current=BA_READER.snapshot()
          if current.profile~=snapshot.profile then rec.failed='native_error'; return true end
          if not current.public or not current.public.ready then return false end
          local target
          for _,binding in ipairs(BA_READER.bindings or {}) do
            if binding.action.name=='open_run_setup' and binding.action.enabled
               and binding.node and binding.node.config.button=='setup_run' then
              if target then rec.failed='native_error'; return true end
              target=binding.node
            end
          end
          if not target then return false end
          local original_setup=G.FUNCS.setup_run
          G.FUNCS.setup_run=function(...)
            rec.setup_opened=true
            return original_setup(...)
          end
          local opened=pcall(function() target:click() end)
          G.FUNCS.setup_run=original_setup
          if not opened then rec.failed='native_error'; return true end
          return rec.setup_opened==true
        end}))
      end
    end
  end
end
local function hand_submission_plan(req,snapshot)
  if snapshot.public.phase~='hand' then return nil,'wrong_phase' end
  local p=req.parameters; local r=public_region(snapshot,'hand')
  if not r or not r.selection_limit or #p.positions>r.selection_limit then return nil,'selection_restricted' end
  if req.action=='play' and (G.GAME.blind.block_play or not G.GAME.current_round.hands_left or G.GAME.current_round.hands_left<=0
     or (G.play and G.play.cards and #G.play.cards>0)) then return nil,'button_unavailable' end
  if req.action=='discard' and (not G.GAME.current_round.discards_left or G.GAME.current_round.discards_left<=0) then return nil,'button_unavailable' end
  local apply,reason=selection_plan({parameters={region='hand',positions=p.positions}},snapshot)
  if not apply then return nil,reason end
  local node; local func=req.action=='play' and 'can_play' or 'can_discard'
  for _,binding in ipairs(BA_READER.bindings or {}) do
    if binding.action.name==req.action and binding.node and binding.node.config.func==func then
      if node then return nil,'button_unavailable' end
      node=binding.node
    end
  end
  if not node or not BA_READER.selection_button_available(node) or type(G.FUNCS[func])~='function' then return nil,'button_unavailable' end
  return function(rec)
    apply(rec)
    if not selected_matches(G.hand,p.positions) then error('Native selection failed') end
    -- Same update-thread scope, no intervening action or game update. Native
    -- input validation now sees the actual selected hand; never patch G.hand.
    rec.selection_area=nil; rec.selection_positions=nil; rec.callback=false; rec.callback_at=nil
    G.FUNCS[func](node)
    local current=BA_READER.snapshot()
    if current.profile~=snapshot.profile or not current.public or not current.public.ready then error('Input context changed') end
    local submit=ui_plan(req,current)
    if not submit then error('Native hand button unavailable') end
    submit(rec)
  end
end
-- Targeted actions still use the real rendered button. Preparing selection is
-- part of this same durable semantic action; no second request is replayed.
local function target_submission_plan(req,snapshot)
  local p=req.parameters
  if not phases[req.action] or not phases[req.action][snapshot.public.phase] then return nil,'wrong_phase' end
  local permitted=req.action=='buy' and (p.region=='shop_jokers' or p.region=='shop_vouchers' or p.region=='shop_boosters')
      or req.action=='sell' and (p.region=='jokers' or p.region=='consumables')
      or req.action=='buy_and_use' and p.region=='shop_jokers'
      or req.action=='use' and (p.region=='consumables' or p.region=='pack')
      or req.action=='select_pack_card' and p.region=='pack'
  if not permitted then return nil,'invalid_target' end
  local r=public_region(snapshot,p.region); local area=G[regions[p.region]]
  local card=area and area.cards and area.cards[p.position+1]; local public
  for _,value in ipairs(r and r.cards or {}) do if value.position==p.position then public=value end end
  if not card or not public then return nil,'invalid_target' end
  if public.visibility=='face_down' then return nil,'unsupported_rule' end
  if req.action=='select_pack_card' then
    -- Native use-only consumables never render can_select_card. Refuse before
    -- Card.click instead of waiting for a nonexistent take button. An already
    -- rendered, enabled can_select_from_booster was handled by ui_plan first.
    local set=card.ability and card.ability.set
    if not card.ability or card.ability.consumeable
       or (set~='Default' and set~='Enhanced' and set~='Joker') then return nil,'invalid_target' end
  end
  if req.action=='buy' or req.action=='buy_and_use' then
    if type(public.price)~='number' or public.price~=card.cost or type(G.GAME.dollars)~='number'
       or type(G.GAME.bankrupt_at)~='number' then return nil,'unsupported_rule' end
    local available=G.GAME.dollars-G.GAME.bankrupt_at
    if (card.cost>0 or p.region=='shop_vouchers') and card.cost>available then return nil,'button_unavailable' end
    if req.action=='buy' and not space_available(card) then return nil,'insufficient_capacity' end
  elseif req.action=='sell' then
    if type(card.can_sell_card)~='function' then return nil,'unsupported_rule' end
    local ok,allowed=pcall(card.can_sell_card,card)
    if not ok then return nil,'unsupported_rule' end
    if allowed~=true then return nil,'button_unavailable' end
  end
  if p.region=='pack' then
    if not snapshot.public.resources or type(snapshot.public.resources.pack_choices)~='number'
       or snapshot.public.resources.pack_choices<=0 then return nil,'button_unavailable' end
  end
  if req.action=='select_pack_card' and not space_available(card) then return nil,'insufficient_capacity' end
  if req.action=='use' or req.action=='buy_and_use' then
    if not card.ability or not card.ability.consumeable or type(card.can_use_consumeable)~='function' then return nil,'invalid_target' end
    -- This fixed native eligibility method has no use effect or RNG. Preserve
    -- the model's separately selected hand; never pick its targets for it.
    local ok,allowed=pcall(card.can_use_consumeable,card)
    if not ok then return nil,'unsupported_rule' end
    if allowed~=true then return nil,'button_unavailable' end
    if card.ability.name=='Ankh' and #G.jokers.cards>=G.jokers.config.card_limit then return nil,'insufficient_capacity' end
  end
  -- Already selected but disabled is a refusal, not an automatic retry.
  if card.highlighted then return nil,'button_unavailable' end
  local apply,reason=selection_plan({parameters={region=p.region,positions={p.position}}},snapshot)
  if not apply then return nil,reason end
  local validators=({buy={can_buy=true,can_open=true,can_redeem=true},sell={can_sell_card=true},
    use={can_use_consumeable=true},buy_and_use={can_buy_and_use=true},
    select_pack_card={can_select_card=true,can_select_from_booster=true}})[req.action]
  local original_game=G.GAME
  return function(rec)
    apply(rec)
    if not selected_matches(area,{p.position}) then error('Native selection failed') end
    rec.selection_area=nil; rec.selection_positions=nil; rec.callback=false; rec.callback_at=nil
    rec.preparing_target=true
    G.E_MANAGER:add_event(Event({blocking=false,blockable=false,func=function()
      -- Stop preparation after the native record is UNKNOWN. A Python request
      -- timeout alone is not cancellation; its record can still be RUNNING.
      if rec.state=='UNKNOWN' or rec.failed then rec.preparing_target=nil; return true end
      if G.GAME~=original_game or not area.cards or area.cards[p.position+1]~=card then
        rec.failed='native_error'; rec.preparing_target=nil; return true
      end
      local current=BA_READER.snapshot()
      if current.profile~=snapshot.profile or current.compatibility~='supported' or not current.public
         or current.public.phase~=snapshot.public.phase then
        rec.failed='native_error'; rec.preparing_target=nil; return true
      end
      if not current.public.ready then return false end
      local node
      for _,binding in ipairs(BA_READER.bindings or {}) do
        local action=binding.action
        if action.name==req.action and action.region==p.region and action.position==p.position then
          if node then rec.failed='native_error'; rec.preparing_target=nil; return true end
          node=binding.node
        end
      end
      if not node or not BA_READER.selection_button_available(node) then return false end
      local validator=node.config and node.config.func
      if not validators[validator] or type(G.FUNCS[validator])~='function' then
        rec.failed='native_error'; rec.preparing_target=nil; return true
      end
      -- Normal UI eligibility refresh on its actual selected/rendered node.
      G.FUNCS[validator](node)
      current=BA_READER.snapshot()
      local submit=ui_plan(req,current)
      if not submit then return false end
      rec.preparing_target=nil
      submit(rec)
      return true
    end}))
  end
end
local function observe_path(rec)
  if G.STATE==G.STATES.HAND_PLAYED then rec.saw_play=true end
  if G.STATE==G.STATES.DRAW_TO_HAND then rec.saw_draw=true end
  if G.STATE==G.STATES.NEW_ROUND then rec.saw_round=true end
end
function E.install_hooks()
  local add=EventManager.add_event
  EventManager.add_event=function(self,event,queue,front)
    local rec=scope
    add(self,event,queue,front)
    -- In fixed Game:start_run, the sole immediate/nonblocking/unblockable
    -- inline callback is the perpetual background spin updater. It has no
    -- return true and must keep running after gameplay is already operable.
    -- Scope + source span prevents excluding similarly shaped effect events.
    local info=bootstrap_body and debug.getinfo(event.func,'S')
    local cosmetic=info and info.source==bootstrap_body.source
      and info.linedefined>=bootstrap_body.linedefined and info.lastlinedefined<=bootstrap_body.lastlinedefined
      and event.trigger=='immediate' and event.blocking==false and event.blockable==false
      and (queue==nil or queue=='base')
    if rec and not cosmetic then
      -- Track only an event actually admitted by the native manager.
      for _,v in ipairs(self.queues[queue or 'base'] or {}) do
        if v==event and not owner[event] then owner[event]=rec; rec.events[event]=true; break end
      end
    end
  end
  local start_run=Game and Game.start_run
  if start_run then
    local body=native_start_body(start_run)
    Game.start_run=function(self,...)
      local previous=bootstrap_body; bootstrap_body=body
      local values={pcall(start_run,self,...)}
      bootstrap_body=previous
      if not values[1] then if active then active.failed='native_error' end; error('Balatro Agent initialization failed') end
      return unpack(values,2)
    end
  end
  local handle=Event.handle
  Event.handle=function(self,results)
    local rec=owner[self]; local previous=scope
    local previous_overlay=G.OVERLAY_MENU
    if rec then scope=rec; observe_path(rec) end
    local ok,err=pcall(handle,self,results)
    if rec then
      observe_path(rec)
      -- Preserve the overlay created by this exact native event, even while
      -- its slide-in VT is outside the room. Identify the rendered native
      -- unlock and apply every input gate later, when it is actually ready.
      if notice_navigation[rec.req.action] and G.OVERLAY_MENU~=previous_overlay
          and type(G.OVERLAY_MENU)=='table' then
        rec.notice_created=G.OVERLAY_MENU
      end
      if results.completed and results.time_done then rec.events[self]=nil; owner[self]=nil end
      if not ok then rec.failed='native_error' end
    end
    scope=previous
    if not ok then error(rec and 'Balatro Agent related event failed' or err) end
  end
  local clear=EventManager.clear_queue
  EventManager.clear_queue=function(self,...)
    local before={}
    for _,queue in pairs(self.queues) do for _,event in ipairs(queue) do if owner[event] then before[event]=owner[event] end end end
    clear(self,...)
    local remaining={}; for _,queue in pairs(self.queues) do for _,event in ipairs(queue) do remaining[event]=true end end
    for event,rec in pairs(before) do if not remaining[event] then rec.events[event]=nil; owner[event]=nil; rec.failed='events_cancelled' end end
  end
  for _,name in ipairs({'update_hand_played','update_draw_to_hand','update_new_round','update_round_eval','update_shop',
       'update_blind_select','update_arcana_pack','update_spectral_pack','update_standard_pack','update_buffoon_pack','update_celestial_pack',
       'update_smods_booster_opened','update_smods_redeem_voucher'}) do
    local original=Game and Game[name]
    if original then
      Game[name]=function(self,...)
        local previous=scope
        if active then scope=active; observe_path(active) end
        local values={pcall(original,self,...)}
        scope=previous
        if not values[1] then if active then active.failed='native_error' end; error('Balatro Agent related phase failed') end
        return unpack(values,2)
      end
    end
  end
  -- Fixed Steamodded dispatches opened-pack initialization directly through
  -- Booster.update_pack rather than a Game.update_* method. Native presets
  -- have copied this function, so wrap their current methods as well.
  local wrapped={}
  for _,center in pairs(G.P_CENTERS or {}) do
    if center.set=='Booster' and type(center.update_pack)=='function' and not wrapped[center] then
      local original=center.update_pack; wrapped[center]=true
      center.update_pack=function(self,...)
        local previous=scope; if active then scope=active end
        local values={pcall(original,self,...)}; scope=previous
        if not values[1] then if active then active.failed='native_error' end; error('Balatro Agent pack phase failed') end
        return unpack(values,2)
      end
    end
  end
end
local function after_conditions(rec,snapshot)
  if rec.setup_navigation and not rec.setup_opened then return false end
  local phase=snapshot.public and snapshot.public.phase
  local a=rec.req.action
  if rec.preference_speed then
    return snapshot.public.preferences and snapshot.public.preferences.game_speed==rec.preference_speed
       and G.SETTINGS.GAMESPEED==rec.preference_speed
  end
  if rec.setup_choice_page then
    local choices=SMODS.RunSelect and SMODS.RunSelect.Setup and SMODS.RunSelect.Setup.choices
    return choices and choices[rec.setup_choice_page]==rec.setup_choice_key
  end
  if rec.selection_area then return selected_matches(rec.selection_area,rec.selection_positions) end
  if rec.order_area then for i,c in ipairs(rec.order_cards) do if rec.order_area.cards[i]~=c then return false end end; return true end
  if a=='play' then return rec.saw_play and ((phase=='hand' and rec.saw_draw) or phase=='round_eval' or phase=='terminal') end
  if a=='discard' then return rec.saw_draw and phase=='hand' end
  if rec.unlock_overlay then return G.OVERLAY_MENU~=rec.unlock_overlay end
  local next_phases={select_blind={hand=true},skip_blind={blind_select=true,shop=true,pack=true},cash_out={shop=true},
    next_round={blind_select=true},skip_pack={shop=true,blind_select=true},start_run={blind_select=true},
    continue_run={hand=true,blind_select=true,shop=true,pack=true,round_eval=true},main_menu={main_menu=true},
    continue_endless={shop=true,round_eval=true},run_info={menu=true},deck_info={menu=true},
    close_menu={hand=true,shop=true,blind_select=true,pack=true,round_eval=true,main_menu=true},
    open_run_setup={main_menu=true,menu=true},next_setup_page={main_menu=true,menu=true},previous_setup_page={main_menu=true,menu=true},
    next_setup_choices={main_menu=true,menu=true},previous_setup_choices={main_menu=true,menu=true},
    open_options={main_menu=true,menu=true},open_settings={main_menu=true,menu=true},
    next_game_speed={main_menu=true,menu=true},previous_game_speed={main_menu=true,menu=true}}
  if next_phases[a] then return next_phases[a][phase]==true end
  if (a=='buy' or a=='use') and rec.req.parameters.region=='shop_boosters' then return phase=='pack' end
  return phase=='shop' or phase=='hand' or phase=='blind_select' or phase=='pack'
end
local function update_record(rec,snapshot,allow_notice)
  if rec.state=='COMPLETED' then return end
  observe_path(rec)
  if rec.failed then rec.state='UNKNOWN'; rec.reason=rec.failed; return end
  rec.events_done=next(rec.events)==nil
  if allow_notice and rec.state~='UNKNOWN' and rec.callback and snapshot.public and snapshot.public.ready
      and notice_navigation[rec.req.action] and BA_READER.unlock_notice then
    local notice=BA_READER.unlock_notice()
    -- A main-menu transition may have finished every event while its last
    -- notice still needs a native Continue. Input takes priority over phase.
    if notice and notice==rec.notice_created then
      rec.wait_overlay=notice; rec.snapshot=snapshot
      if rec.state~='AWAITING_INPUT' then
        rec.state='AWAITING_INPUT'; rec.reason='native_unlock_input'
        if not journal('input_required',response(rec)) then rec.failed='journal_unavailable'; rec.state='UNKNOWN'; rec.reason='journal_unavailable' end
      end
      return
    end
    if rec.state=='AWAITING_INPUT' then rec.state='UNKNOWN'; rec.reason='input_context_changed'; return end
  end
  local terminal_done=rec.req.action=='play' and rec.saw_play and snapshot.public and snapshot.public.ready and snapshot.public.outcome~=nil
  if rec.callback and snapshot.public and snapshot.public.ready and ((rec.events_done and after_conditions(rec,snapshot)) or terminal_done) then
    rec.completed_elapsed_ms=math.max(0,math.floor((clock()-rec.started)*1000))
    if rec.callback_at then rec.callback_to_completed_ms=math.max(0,math.floor((clock()-rec.callback_at)*1000)) end
    rec.state='COMPLETED'; rec.reason='completed'; rec.snapshot=snapshot
    rec.signal=terminal_done and 'terminal_confirmation' or 'callback_events'
    if terminal_done then for event in pairs(rec.events) do owner[event]=nil end end
    if snapshot.public.outcome then E.finished_game=G.GAME end
    if rec.req.action=='start_run' then
      -- Reproduction only: never return this seed, include it in journal/notes,
      -- or use it for decisions. No read endpoint exposes this separate file.
      local saved=pcall(function()
        local seed=G.GAME.pseudorandom and G.GAME.pseudorandom.seed
        local f=assert(io.open(mod_path..'executor-reproduction.jsonl','a'))
        assert(f:write(json.encode{action_id=rec.req.action_id,game_session=BA_BINDING.session,profile=rec.profile,seed=seed}..'\n')); assert(f:flush()); assert(f:close())
      end)
      if not saved then rec.state='UNKNOWN'; rec.reason='journal_unavailable'; return end
    end
    if not journal('result',response(rec)) then rec.state='UNKNOWN'; rec.reason='journal_unavailable'; return end
  elseif rec.state~='AWAITING_INPUT' and clock()-rec.started>60 then rec.state='UNKNOWN'; rec.reason='completion_timeout' end
end
function E.update()
  if not active then return end
  local ok,snapshot=pcall(BA_READER.snapshot)
  local error_reason = not ok and 'native_error' or (snapshot.profile==nil and 'unknown_profile'
     or snapshot.profile~=active.profile and 'profile_mismatch' or nil)
  if error_reason then
    active.failed=error_reason; active.state='UNKNOWN'; active.reason=error_reason
    if input then input.failed=error_reason; input.state='UNKNOWN'; input.reason=error_reason end
    return
  end
  if input then
    update_record(input,snapshot,false)
    if input.state=='COMPLETED' then input=nil
    elseif input.state=='UNKNOWN' then active.failed=input.reason end
  end
  update_record(active,snapshot,input==nil)
  if active.state=='COMPLETED' and not input then active=nil end
end
function E.submit(raw)
  local req,reason=normalized(raw)
  if not req then return reject(raw,reason) end
  local fingerprint=BA_BINDING.canonical(req)
  local previous=records[req.action_id]
  if previous then
    if previous.fingerprint~=fingerprint then return reject(req,'id_conflict') end
    return response(previous,true)
  end
  local function refusal(code)
    local rec={req=req,fingerprint=fingerprint,state='REJECTED',reason=code,submitted=false}
    records[req.action_id]=rec
    if not journal('rejection',response(rec)) then rec.reason='journal_unavailable' end
    return response(rec)
  end
  if req.game_session~=BA_BINDING.session then return refusal('session_changed') end
  local parent
  if active then
    if active.state~='AWAITING_INPUT' or input or req.action~='close_menu' then return refusal('action_busy') end
    parent=active
  end
  local snapshot=BA_READER.snapshot()
  if snapshot.public and snapshot.public.outcome then E.finished_game=G.GAME end
  if snapshot.profile==nil then return refusal('unknown_profile') end
  if snapshot.profile~=req.expected_profile.profile then return refusal('profile_mismatch') end
  if snapshot.compatibility~='supported' or not snapshot.public then return refusal('unsupported_rule') end
  if req.observation_id~=snapshot.observation_id then return refusal('stale_observation') end
  if not snapshot.public.ready then return refusal('not_ready') end
  if parent then
    if snapshot.profile~=parent.profile then return refusal('profile_mismatch') end
    local notice=BA_READER.unlock_notice and BA_READER.unlock_notice()
    if not notice or notice~=parent.wait_overlay then return refusal('input_context_changed') end
  end
  local perform
  if req.action=='select_setup_option' then perform,reason=setup_selection_plan(req,snapshot)
  elseif (req.action=='play' or req.action=='discard') and req.parameters.positions then perform,reason=hand_submission_plan(req,snapshot)
  elseif req.action=='select' then perform,reason=selection_plan(req,snapshot)
  elseif req.action=='reorder' then perform,reason=reorder_plan(req,snapshot)
  elseif targeted[req.action] then
    perform,reason=ui_plan(req,snapshot)
    if not perform and reason=='button_unavailable' then perform,reason=target_submission_plan(req,snapshot) end
  else perform,reason=ui_plan(req,snapshot) end
  if not perform then return refusal(reason) end
  local rec={req=req,fingerprint=fingerprint,profile=snapshot.profile,state='RUNNING',reason='accepted',submitted=false,events={},started=clock()}
  if not journal('intent',{request=req,state='RECEIVED'}) then return refusal('journal_unavailable') end
  records[req.action_id]=rec; rec.submitted=true
  if parent then
    rec.input_for=parent; input=rec
    parent.state='RUNNING'; parent.reason='accepted'; parent.started=clock()
  else active=rec end
  BA_BINDING.invalidate()
  local old_scope=scope; scope=rec
  local ok=pcall(perform,rec)
  observe_path(rec); scope=old_scope
  if not ok or (not rec.callback and not rec.preparing_target) then rec.failed='native_error'; rec.state='UNKNOWN'; rec.reason='native_error' end
  if not journal('submission',response(rec)) then rec.failed='journal_unavailable'; rec.state='UNKNOWN'; rec.reason='journal_unavailable' end
  E.update()
  return response(rec)
end
function E.status(args)
  if not keys(args,{action_id=true}) or not valid_id(args.action_id) then return reject(nil,'invalid_request') end
  local rec=records[args.action_id]
  if rec then return response(rec) end
  return response{req={action_id=args.action_id},state='UNKNOWN',reason='record_not_found'}
end
return E
