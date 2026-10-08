-- Player-visible, read-only adapter. Native game source remains private.
-- No strategy, random generator, action callback or deck-order export.
local R = {}
local json = require('json')
local commit = '9052d76f14723293f6c6b2cecaa791a5c4ae68f3'

local function array() return setmetatable({}, {__jsontype = 'array'}) end
local function scalar(v)
  if type(v) == 'number' and v == v and v ~= math.huge and v ~= -math.huge then return v end
  if type(v) == 'string' and #v <= 8192 then return v end
end
local function text(v)
  local s = scalar(v)
  if s ~= nil then return tostring(s) end
end
local function issue(unknowns, code)
  if not unknowns then return end
  for _, existing in ipairs(unknowns) do if existing == code then return end end
  unknowns[#unknowns+1] = code
end
local function present(node)
  if not node or node.removed or (node.states and node.states.visible == false) then return false end
  return true
end
local function displayed(node)
  if not present(node) then return false end
  local t, room_node = node.VT or node.T, G and G.ROOM
  local room = room_node and room_node.T
  if t and room and t.x and t.y and t.w and t.h then
    -- Fixed native Node:translate_container adds ROOM.T.x/y at draw time.
    -- Children of that room store local coordinates; its screen padding is
    -- not their local visibility origin. Keep unknown containers conservative.
    local x, y = room.x, room.y
    if node ~= room_node and node.container == room_node then x, y = 0, 0 end
    if t.x + t.w < x or t.x > x + room.w or t.y + t.h < y or t.y > y + room.h then return false end
  end
  return true
end
local function clickable(node)
  local c = node and node.config
  -- Native UIElement:click keeps config.button after a one_press click.
  -- Inspect its current input gates without invoking a callback or changing UI.
  if not c or not c.button or not displayed(node) or not (node.states and node.states.visible)
     or node.under_overlay or node.disable_button then return false end
  if node.last_clicked then
    local last, now = node.last_clicked, G and G.TIMERS and G.TIMERS.REAL
    if type(last) ~= 'number' or scalar(last) == nil or type(now) ~= 'number' or scalar(now) == nil then return false end
    if not (last + 0.1 < now) then return false end
  end
  return true
end
local function walk(root, visit, seen)
  if type(root) ~= 'table' or (root.states and root.states.visible == false) or root.removed then return end
  seen = seen or {}
  if seen[root] then return end
  seen[root] = true
  visit(root)
  local function children(values)
    if type(values) ~= 'table' then return end
    -- UI children are ordered arrays; supplementary children use string keys.
    local keys = {}
    for key in pairs(values) do keys[#keys + 1] = key end
    table.sort(keys, function(a,b)
      if type(a) == type(b) then return a < b end
      return type(a) == 'number'
    end)
    for _, key in ipairs(keys) do walk(values[key], visit, seen) end
  end
  -- Native UIBox owns its element tree in UIRoot, outside supplementary
  -- children. UIElement also renders nested UIBox objects for tabs and menus.
  -- Follow only an actual UIBox on the rendered object node, never arbitrary
  -- config references or a stored definition of undisplayed content.
  walk(root.UIRoot, visit, seen)
  local object = root.config and root.config.object
  if G and G.UIT and root.UIT == G.UIT.O and type(object) == 'table' and UIBox and getmetatable(object) == UIBox then
    walk(object, visit, seen)
  end
  children(root.nodes)
  children(root.children)
  -- UIBox also renders these current UI elements explicitly. They are rendered
  -- surfaces, unlike its stored definition or unrelated object references.
  children(root.draw_layers)
end
local function visible_text(root, dynamic, unknowns, generated_tooltip)
  local parts = array()
  walk(root, function(node)
    local c = node.config or {}
    -- Rendered nested UIBox objects are handled by walk; DynaText contributes
    -- only its current string, never hidden alternatives or other references.
    if c.ref_value == 'seed' or c.ref_value == 'pseudorandom' then return end
    local s = text(c.text)
    if not s and c.ref_table and c.ref_value then s = text(c.ref_table[c.ref_value]) end
    local object = c.object
    if dynamic and type(object) == 'table' and
       (type(object.strings) == 'table' or (DynaText and getmetatable(object) == DynaText)) then
      -- Prefer the text actually rendered by DynaText. Steamodded can also
      -- attach config.text to the same node; reading both duplicates a phrase.
      s = nil
      -- Copied native tooltip text is newly constructed at (0,0), before a
      -- popup positions it. Room clipping applies to live UI, not this legal
      -- hover query; hidden/removed objects and inactive strings still vanish.
      if generated_tooltip and present(object) or not generated_tooltip and displayed(object) then
        local index = object.focused_string
        local current = type(object.strings) == 'table' and index and object.strings[index]
        s = type(current) == 'table' and text(current.string) or nil
        if not s then issue(unknowns, 'tooltip_unavailable') end
      end
    end
    if unknowns and s and s:find('ERROR', 1, true) then
      issue(unknowns, 'tooltip_unavailable'); s = nil
    end
    if s then parts[#parts+1] = s end
  end)
  return parts
end
local function lines(nodes, unknowns, prepare, generated_tooltip)
  local out = array()
  if type(nodes) ~= 'table' then
    if nodes ~= nil then issue(unknowns, 'tooltip_unavailable') end
    return out
  end
  for _, line in ipairs(nodes or {}) do
    local root = {nodes=line}
    if prepare then walk(root, prepare) end
    local parts = visible_text(root, true, unknowns, generated_tooltip)
    local s = table.concat(parts, '')
    if #s > 0 then out[#out+1] = s end
  end
  return out
end
local function cleanup(root, seen)
  if type(root) ~= 'table' then return end
  seen = seen or {}
  if seen[root] then return end
  seen[root] = true
  local object = root.config and root.config.object
  if type(object) == 'table' and type(object.remove) == 'function' and not seen[object] then
    seen[object] = true; object:remove()
  end
  for key, value in pairs(root) do
    if type(value) == 'table' and key ~= 'config' then cleanup(value, seen) end
  end
end
local function clone(value, seen)
  if type(value) ~= 'table' then return value end
  seen = seen or {}
  if seen[value] then return seen[value] end
  local result = {}; seen[value] = result
  for key, child in pairs(value) do result[key] = clone(child, seen) end
  return setmetatable(result, getmetatable(value))
end
local function caption(value, unknowns, generated_tooltip)
  local s
  if type(value) == 'string' then s = text(value)
  elseif type(value) == 'table' then s = table.concat(visible_text({nodes=value}, true, unknowns, generated_tooltip), '') end
  if s and s:find('ERROR', 1, true) then issue(unknowns, 'tooltip_unavailable'); return nil end
  return s and #s > 0 and s or nil
end
local function tooltip(card, unknowns)
  -- Misprint's UI generator reads an unrevealed deck card and constructs random
  -- alternatives. Do not even invoke that generator at this boundary.
  if card.ability and card.ability.name == 'Misprint' then
    issue(unknowns, 'dynamic_tooltip_omitted')
    return nil, array(), array()
  end
  if type(card.generate_UIBox_ability_table) ~= 'function' then
    issue(unknowns, 'tooltip_unavailable')
    return nil, array(), array()
  end
  -- Native tooltip code may set UI compatibility flags. Its receiver and
  -- ability/config data are copied so those writes do not alter the real card.
  local copy = {}
  for key, value in pairs(card) do copy[key] = value end
  copy.ability = clone(card.ability)
  copy.config = {}
  for key, value in pairs(card.config or {}) do copy.config[key] = value end
  setmetatable(copy, getmetatable(card))
  local ok, ui = pcall(card.generate_UIBox_ability_table, copy)
  if not ok or type(ui) ~= 'table' then
    issue(unknowns, 'tooltip_unavailable')
    return nil, array(), array()
  end
  local function prepare(node)
    local c = node.config or {}
    if c.func == 'blueprint_compat' and c.ref_table == copy then
      -- The native UI formatter localizes this already-public compatibility
      -- state on first draw. Materialize it only on the copied ability; never
      -- run callbacks, inspect another Joker or calculate a copied effect.
      local state = copy.ability and copy.ability.blueprint_compat
      local ok_label, label
      if state == 'compatible' or state == 'incompatible' then
        ok_label, label = pcall(localize, 'k_'..state)
      end
      copy.ability.blueprint_compat_ui = ok_label and caption(label, unknowns) and ' '..label..' ' or ''
      if not ok_label or #copy.ability.blueprint_compat_ui == 0 then issue(unknowns, 'tooltip_unavailable') end
    end
  end
  local ok_text, name, main, info = pcall(function()
    local name, main, info = caption(ui.name, unknowns, true), lines(ui.main, unknowns, prepare, true), array()
    for _, section in ipairs(ui.info or {}) do
      local title = caption(section.name, unknowns, true)
      if title then info[#info+1] = title end
      local body = lines(section, unknowns, prepare, true)
      for _, line in ipairs(body) do info[#info+1] = line end
      if #body == 0 then issue(unknowns, 'tooltip_unavailable') end
    end
    -- A true name is the native intentional nameless marker (e.g. Stone).
    if (ui.name ~= true and not name) or #main == 0 then issue(unknowns, 'tooltip_unavailable') end
    return name, main, info
  end)
  local ok_cleanup = pcall(cleanup, ui)
  if not ok_cleanup then issue(unknowns, 'tooltip_unavailable') end
  if not ok_text then
    issue(unknowns, 'tooltip_unavailable')
    return nil, array(), array()
  end
  return name, main, info
end

local function public_card(card, position, region, unknowns)
  local result = {position=position, selected=card.highlighted == true}
  if card.facing ~= 'front' or (card.sprite_facing and card.sprite_facing ~= 'front') then
    result.visibility = 'face_down'
    return result
  end
  local ability = card.ability or {}
  local center = card.config and card.config.center or {}
  local stone = ability.effect == 'Stone Card' or ability.name == 'Stone Card' or center.key == 'm_stone'
  local undiscovered = center.discovered == false and not card.bypass_discovery_ui and not card.bypass_lock and region ~= 'jokers' and region ~= 'consumables' and ability.set ~= 'Default' and ability.set ~= 'Enhanced'
  result.visibility = stone and 'stone' or undiscovered and 'undiscovered' or 'face_up'
  result.name, result.description, result.tooltip_info = tooltip(card, unknowns)
  if not stone and not undiscovered and (ability.set == 'Default' or ability.set == 'Enhanced') then
    result.rank = card.base and card.base.value
    result.suit = card.base and card.base.suit
  end
  result.debuffed = card.debuff == true
  result.forced_selection = ability.forced_selection == true
  if region == 'shop_jokers' or region == 'shop_vouchers' or region == 'shop_boosters' then result.price = scalar(card.cost) end
  if region == 'jokers' or region == 'consumables' then result.sell_price = scalar(card.sell_cost) end
  return result
end
local region_fields = {
  {'hand','hand'}, {'play','play'}, {'jokers','jokers'}, {'consumables','consumeables'},
  {'shop_jokers','shop_jokers'}, {'shop_vouchers','shop_vouchers'}, {'shop_boosters','shop_booster'}, {'pack','pack_cards'}
}
local action_map = {
  setup_run='open_run_setup', notify_then_setup_run='open_run_setup',
  run_select_start_run='start_run', run_select_quick_start='quick_start_run',
  start_setup_run='start_run', select_blind='select_blind', skip_blind='skip_blind',
  play_cards_from_highlighted='play', discard_cards_from_highlighted='discard',
  sort_hand_value='sort_rank', sort_hand_suit='sort_suit', cash_out='cash_out',
  buy_from_shop='buy', sell_card='sell', reroll_shop='reroll', toggle_shop='next_round',
  use_card='use', skip_booster='skip_pack', run_info='run_info', deck_info='deck_info',
  exit_overlay_menu='close_menu', continue_unlock='close_menu', go_to_menu='main_menu'
}
action_map.options='open_options'
action_map.settings='open_settings'
-- Native can_open/can_redeem rewrite their live callback to use_card. The
-- displayed resource gates identify paid shop transactions even when disabled.
local func_map = {can_play='play', can_discard='discard', can_reroll='reroll', can_buy='buy', can_open='buy', can_redeem='buy', can_buy_and_use='buy_and_use', can_sell_card='sell', can_use_consumeable='use', can_select_card='select_pack_card', can_select_from_booster='select_pack_card', can_skip_booster='skip_pack', can_start_run='start_run'}

local function ui_actions(roots, targets, ready, bindings)
  local out, seen_nodes = array(), {}
  for _, root in ipairs(roots) do
    walk(root, function(node)
      if seen_nodes[node] then return end
      seen_nodes[node] = true
      local c = node.config or {}
      local name = func_map[c.func] or action_map[c.button]
      -- A running game exposes New Run through its visible Options button.
      -- The executor opens both menus
      -- as one navigation action, checking each live button before clicking.
      local run_options=c.button=='options' and G.STAGE==G.STAGES.RUN and G.GAME
        and not G.OVERLAY_MENU and not G.deck_preview
      -- Steamodded 26.829.0 replaces New Run with a paged selector. Its live
      -- callback differentiates navigation from Play; never invoke the callback.
      if c.button == 'run_select_change_page' then
        if c.ref_value == -1 then name = 'previous_setup_page'
        elseif c.ref_value == 1 then name = 'next_setup_page' end
      elseif c.func == 'run_select_can_change_page' and c.id == 'next_selection' and c.button == nil then
        local label = visible_text(node, true)
        name = label[1] == localize('run_select_play') and 'start_run' or 'next_setup_page'
      end
      -- Play defaults to Continue while a native save exists, including a won
      -- run after restart. Bind only its rendered New Run tab to the fixed
      -- native/Steamodded definition, never Challenges or a hidden definition.
      if c.button=='change_tab' and G.SETTINGS.current_setup=='Continue'
         and type(c.ref_table)=='table' and c.ref_table.tab_definition_function_args=='New Run'
         and G.UIDEF and type(c.ref_table.tab_definition_function)=='function'
         and (c.ref_table.tab_definition_function==G.UIDEF.run_setup_option
              or c.ref_table.tab_definition_function==G.UIDEF.run_select_galdur) then
        name='next_setup_page'
      end
      if c.button=='cycler_default' and c.pass_through
         and (c.pass_through.key=='deck_choice_select_cycle' or c.pass_through.key=='stake_choice_select_cycle') then
        name=c.direction==1 and 'next_setup_choices' or c.direction==-1 and 'previous_setup_choices' or nil
      end
      if c.button=='option_cycle' and c.ref_table and c.ref_table.opt_callback=='change_gamespeed' then
        name=c.ref_value=='r' and 'next_game_speed' or c.ref_value=='l' and 'previous_game_speed' or nil
      end
      if not name then return end
      if c.button == 'start_setup_run' and G.SETTINGS.current_setup == 'Continue' then name = 'continue_run' end
      if c.button == 'exit_overlay_menu' and G.OVERLAY_MENU and G.OVERLAY_MENU.get_UIE_by_ID
         and G.OVERLAY_MENU:get_UIE_by_ID('you_win_UI') then name = 'continue_endless' end
      local target = targets[c.ref_table]
      if c.ref_table and c.ref_table.ability and not target then return end
      if target and target.hidden then return end
      out[#out+1] = {name=name, enabled=ready and clickable(node), blind_slot=target and target.blind_slot,
                    region=target and target.region, position=target and target.position,
                    label=visible_text(node, true)}
      if bindings then bindings[#bindings+1] = {node=node, action=out[#out]} end
      if run_options then
        out[#out+1]={name='open_run_setup',enabled=ready and clickable(node),label=visible_text(node,true)}
        if bindings then bindings[#bindings+1]={node=node,action=out[#out]} end
      end
    end)
  end
  return out
end
-- Used only to preflight a currently displayed play/discard node whose native
-- button is disabled because the requested hand has not yet been selected.
function R.selection_button_available(node)
  if not node or not displayed(node) or not node.states or node.states.visible~=true
     or node.under_overlay or node.disable_button then return false end
  if node.last_clicked then
    local now=G.TIMERS and G.TIMERS.REAL
    if type(now)~='number' or type(node.last_clicked)~='number' or not (node.last_clicked+0.1<now) then return false end
  end
  return true
end

local function terminal_marker(root)
  if not root or not root.get_UIE_by_ID then return end
  local win = root:get_UIE_by_ID('you_win_UI')
  if win then return 'win', win end
  local loss = root:get_UIE_by_ID('from_game_over')
  if G.STATE == G.STATES.GAME_OVER and loss and loss.config and loss.config.button == 'notify_then_setup_run' then
    return 'loss', loss
  end
end
local function current_phase()
  if not G or not G.STATES then return 'unsupported' end
  if G.OVERLAY_MENU and not G.OVERLAY_MENU.removed then
    if terminal_marker(G.OVERLAY_MENU) then return 'terminal' end
    return G.STAGE == G.STAGES.MAIN_MENU and 'main_menu' or 'menu'
  end
  if G.deck_preview then return 'menu' end
  local map = {MENU='main_menu', SPLASH='main_menu', BLIND_SELECT='blind_select', SELECTING_HAND='hand',
               HAND_PLAYED='transition', DRAW_TO_HAND='transition', NEW_ROUND='transition', PLAY_TAROT='transition',
               ROUND_EVAL='round_eval', SHOP='shop', TAROT_PACK='pack', PLANET_PACK='pack', SPECTRAL_PACK='pack',
               STANDARD_PACK='pack', BUFFOON_PACK='pack', GAME_OVER='terminal',
               -- The fixed Steamodded Booster API replaces all native pack
               -- states, and voucher redemption has a separate effect state.
               -- Retain the same displayed UI and processing gates below.
               SMODS_BOOSTER_OPENED='pack', SMODS_REDEEM_VOUCHER='transition'}
  for state, phase in pairs(map) do if G.STATE == G.STATES[state] then return phase end end
  return 'unsupported'
end
local function root_for(phase)
  if phase == 'main_menu' then return G.OVERLAY_MENU or G.MAIN_MENU_UI end
  if phase == 'blind_select' then return G.blind_select end
  if phase == 'hand' then return G.buttons end
  if phase == 'round_eval' then return G.round_eval end
  if phase == 'shop' then return G.shop end
  if phase == 'pack' then return G.booster_pack end
  if phase == 'menu' then return G.OVERLAY_MENU or G.deck_preview end
  if phase == 'terminal' then return G.OVERLAY_MENU or G.GAME_OVER_UI end
end
local function settlement_cash_ui()
  local result, seen = {}, {}
  if not displayed(G.round_eval) then return result end
  local function add(box)
    if seen[box] or not displayed(box) or not box.get_UIE_by_ID then return end
    seen[box] = true
    local button = box:get_UIE_by_ID('cash_out_button')
    if button and displayed(button) then result[#result+1] = {box=box, button=button} end
  end
  add(G.round_eval)
  -- Native add_round_eval_row renders cash-out in a separate registered UIBox
  -- aligned to this settlement. It is not a child of round_eval's UIRoot.
  -- Follow only that visible attached box, never every registered UI surface.
  for _, box in ipairs(G.I and G.I.UIBOX or {}) do
    if UIBox and getmetatable(box) == UIBox and not box.parent and not box.attention_text
       -- Native Moveable:set_alignment stores the live attachment in role,
       -- not alignment or the constructor's possibly stale config.major.
       and box.role and box.role.role_type == 'Minor' and box.role.major == G.round_eval then add(box) end
  end
  return result
end
-- Current rendered native notice only. References stay inside the Mod and are
-- never exported or used to inspect queued notices or their identities.
function R.unlock_notice()
  if not (G and G.SETTINGS and G.SETTINGS.paused and displayed(G.OVERLAY_MENU)) then return end
  local found, count = nil, 0
  walk(G.OVERLAY_MENU, function(node)
    if node.config and node.config.button=='continue_unlock' and node.created_on_pause==true and clickable(node) then
      found=node; count=count+1
    end
  end)
  if count==1 then return G.OVERLAY_MENU, found end
end
local function readiness(phase)
  if phase == 'unsupported' then return false, 'unsupported_state' end
  if phase == 'transition' then return false, 'processing' end
  if not G.CONTROLLER then return false, 'unknown_readiness' end
  local notice = R.unlock_notice()
  local overlay_input = notice ~= nil and (phase=='menu' or phase=='main_menu')
  -- Native Controller:L_cursor_press/release permit paused overlay input while
  -- a run/load lock is held. Frame gates and screen wipes still prevent clicks.
  if G.CONTROLLER.lock_input or G.CONTROLLER.locks and (G.CONTROLLER.locks.frame or G.CONTROLLER.locks.frame_set)
     or G.CONTROLLER.frame_buttonpress or G.screenwipe then return false, 'controller_locked' end
  if G.CONTROLLER.locked and not overlay_input then return false, 'controller_locked' end
  if G.CONTROLLER.dragging and G.CONTROLLER.dragging.target then return false, 'processing' end
  if not overlay_input then
    for _, lock in pairs(G.CONTROLLER.locks or {}) do if lock then return false, 'controller_locked' end end
  end
  if phase ~= 'menu' and phase ~= 'main_menu' and G.STATE_COMPLETE ~= true then return false, 'state_initializing' end
  -- The native terminal overlay pauses the run. STOP_USE gates card effects,
  -- not its navigation buttons; its decrement events can remain paused here.
  if (G.GAME and G.GAME.STOP_USE and G.GAME.STOP_USE > 0) and phase ~= 'main_menu' and phase ~= 'menu' and phase ~= 'terminal' then return false, 'processing' end
  local root = root_for(phase)
  if not displayed(root) then return false, 'ui_not_displayed' end
  if phase == 'terminal' then
    local outcome, marker = terminal_marker(root)
    if not outcome then return false, 'unknown_readiness' end
    if not displayed(marker) then return false, 'ui_not_displayed' end
    local usable = false
    walk(root, function(node)
      local button = node.config and node.config.button
      if clickable(node) and (button == 'notify_then_setup_run' or button == 'go_to_menu' or button == 'exit_overlay_menu') then usable = true end
    end)
    if not usable then return false, 'processing' end
  end
  if phase == 'hand' and (not G.hand or #G.hand.cards == 0) then return false, 'processing' end
  if phase == 'pack' and (not G.pack_cards or #G.pack_cards.cards == 0) then return false, 'processing' end
  if phase == 'round_eval' then
    local usable = false
    for _, entry in ipairs(settlement_cash_ui()) do
      if clickable(entry.button) and entry.button.config.button == 'cash_out' then usable = true end
    end
    if not usable then return false, 'processing' end
  end
  return true, phase == 'menu' and 'menu_open' or 'ui_operable'
end

local function actual_profile()
  local value = G and G.SETTINGS and G.SETTINGS.profile
  if type(value) == 'string' then value = tonumber(value) end
  if type(value) ~= 'number' or value % 1 ~= 0 or value < 1 or value > 3 then return nil end
  return value
end
local function envelope()
  local phase = current_phase()
  local ready, reason = readiness(phase)
  local compatibility = 'supported'
  if not G or G.VERSION ~= '1.0.1o-FULL' then compatibility = 'unsupported_game' end
  for id, mod in pairs(SMODS.Mods or {}) do
    -- Steamodded 26.829.0 registers the injector and native game as platform
    -- metadata entries. They are not additional gameplay Mods. Recognize only
    -- these exact built-in identities, never every entry claiming meta_mod.
    local platform_meta = (id == 'Lovely' or id == 'Balatro') and mod.meta_mod == true and mod.id == id
    if mod.can_load and id ~= 'balatrobot' and id ~= 'Steamodded' and not platform_meta then compatibility = 'unsupported_mods' end
  end
  return {schema_version='reader-2', visibility_policy_version='player-visible-1', adapter_version='0.3.0',
          upstream_commit=commit, upstream_mod_version='1.5.1', game_version=G and G.VERSION,
          profile=actual_profile(), phase=phase, ready=ready,
          ready_reason=reason, compatibility=compatibility,setup_selection_protocol='native-choices-v1',
          direct_hand_protocol='positions-v1',direct_target_protocol='native-target-v1',preferences_protocol='native-settings-v1'}
end

local function skip_tag_fields(node, key, unknowns)
  local tag
  -- The native blind UI binds its current Tag object here. Do not construct a
  -- Tag (that changes tallies/abilities) or call its hover/apply callbacks.
  walk(node, function(child)
    local c = child.config or {}
    local value = c.ref_table
    if c.id == 'tag_container' and displayed(child) and type(value) == 'table'
       and Tag and getmetatable(value) == Tag and value.key == key then tag = value end
  end)
  if not tag or tag.hide_ability or not Tag or type(Tag.get_uibox_table) ~= 'function' then
    unknowns[#unknowns+1] = 'tooltip_unavailable'
    return nil, array()
  end
  -- Fixed Steamodded's vars_only path returns the same public variables used
  -- by a normal tag tooltip before generating any UI. Copy the receiver so a
  -- UI helper cannot write into the real Tag, its ability or its configuration.
  local copy = {key=tag.key,name=tag.name,config=clone(tag.config),ability=clone(tag.ability)}
  setmetatable(copy, getmetatable(tag))
  local ok, vars = pcall(Tag.get_uibox_table, copy, {}, true)
  if not ok or type(vars) ~= 'table' then
    unknowns[#unknowns+1] = 'tooltip_unavailable'
    return nil, array()
  end
  local ok_name, name = pcall(localize, {type='name_text',set='Tag',key=key})
  local ok_desc, description = pcall(localize, {type='raw_descriptions',set='Tag',key=key,vars=vars})
  if not ok_name or not text(name) or name == 'ERROR' then name = nil end
  if not ok_desc or type(description) ~= 'table' or #description == 0 then
    unknowns[#unknowns+1] = 'tooltip_unavailable'
    return name, array()
  end
  for _, line in ipairs(description) do
    if not text(line) or tostring(line):find('ERROR', 1, true) then
      unknowns[#unknowns+1] = 'tooltip_unavailable'
      return name, array()
    end
  end
  return name, description
end

local function blind_choice_description(blind, key, unknowns)
  -- Match the fixed Steamodded blind-choice tooltip variables. Passing the
  -- most-played hand to every Blind produced e.g. "Two Pair/nil" for Wheel.
  -- This legal UI query never samples a probability or constructs a Blind.
  local target = {type='raw_descriptions',set='Blind',key=key,vars={}}
  if blind.name == 'The Ox' then
    target.vars = {localize(G.GAME.current_round.most_played_poker_hand,'poker_hands')}
  end
  if type(blind.loc_vars) == 'function' then
    local ok, value = pcall(blind.loc_vars, clone(blind))
    if not ok or type(value) ~= 'table' or (value.vars ~= nil and type(value.vars) ~= 'table') then
      issue(unknowns, 'tooltip_unavailable')
      return array()
    end
    target.vars, target.key, target.set = value.vars or target.vars, value.key or key, value.set or 'Blind'
  elseif key == 'bl_wheel' then
    issue(unknowns, 'tooltip_unavailable')
    return array()
  end
  local ok, lines = pcall(localize, target)
  if not ok or type(lines) ~= 'table' then
    issue(unknowns, 'tooltip_unavailable')
    return array()
  end
  for _, line in ipairs(lines) do
    if not text(line) or tostring(line):find('ERROR',1,true) or tostring(line):find('%f[%w]nil%f[%W]') then
      issue(unknowns, 'tooltip_unavailable')
      return array()
    end
  end
  return lines
end

local function add_blinds(public)
  local game = G.GAME
  if public.underlying_phase == 'blind_select' or public.phase == 'blind_select' then
    if not displayed(G.blind_select) or not public.ready then return end
    for _, slot in ipairs({'Small','Big','Boss'}) do
      local resets = game.round_resets or {}
      local key = resets.blind_choices and resets.blind_choices[slot]
      local blind = key and G.P_BLINDS[key]
      if blind then
        local name = localize{type='name_text', set='Blind', key=key}
        local description = blind_choice_description(blind, key, public.unknowns)
        local required = get_blind_amount(resets.blind_ante or resets.ante) * blind.mult * game.starting_params.ante_scaling
        local row = {slot=slot,name=name,description=description,required_chips=required,reward=blind.dollars,state=resets.blind_states and resets.blind_states[slot]}
        if game.modifiers and game.modifiers.no_blind_reward and game.modifiers.no_blind_reward[slot] then row.reward = 0 end
        local tag_key = game.round_resets.blind_tags and game.round_resets.blind_tags[slot]
        if tag_key and G.P_TAGS[tag_key] then
          local node = G.blind_select:get_UIE_by_ID(slot)
          row.skip_tag_name, row.skip_tag_description = skip_tag_fields(node, tag_key, public.unknowns)
        end
        public.blinds[#public.blinds+1] = row
      end
    end
  elseif (public.phase == 'hand' or public.phase == 'round_eval') and game.blind and game.blind.name ~= '' then
    local blind = game.blind
    local description = array()
    local loc_text = blind.get_loc_debuff_text and blind:get_loc_debuff_text() or blind.loc_debuff_text
    if type(loc_text)=='string' and #loc_text>0 then description[1]=loc_text end
    public.blinds[#public.blinds+1] = {slot='current',name=blind.loc_name,description=description,required_chips=scalar(blind.chips),reward=scalar(blind.dollars)}
  end
end

local function add_menus(public)
  local menus = public.menus
  -- Poker hand levels are queryable in the normal run menu; hidden hands stay
  -- absent until the game marks the row visible. Fixed display order, no hash.
  for _, key in ipairs({'Flush Five','Flush House','Five of a Kind','Straight Flush','Four of a Kind','Full House','Flush','Straight','Three of a Kind','Two Pair','Pair','High Card'}) do
    local hand = G.GAME.hands and G.GAME.hands[key]
    if hand and hand.visible then menus.poker_hands[#menus.poker_hands+1] = {name=localize(key,'poker_hands'),description=localize(key,'poker_hand_descriptions'),level=hand.level,chips=scalar(hand.chips),mult=scalar(hand.mult),played=hand.played} end
  end
  -- Read the actual native menu's already-created card copies. Never enumerate
  -- G.deck.cards or G.playing_cards, never call view_deck (it sorts native data).
  local cards, count = {}, 0
  walk(G.OVERLAY_MENU, function(node)
    local area = node.config and node.config.object
    if area and area.config and area.config.view_deck and displayed(area) then
      for _, card in ipairs(area.cards or {}) do
        if displayed(card) then
          local value = public_card(card,0,'hand',public.unknowns)
          value.selected = false
          local signature = json.encode(value) .. '|' .. tostring(card.greyed == true)
          if not cards[signature] then cards[signature] = {card=value,count=0,greyed=card.greyed == true} end
          cards[signature].count = cards[signature].count+1; count=count+1
        end
      end
    end
  end)
  local keys = {}; for key in pairs(cards) do keys[#keys+1] = key end; table.sort(keys)
  for _, key in ipairs(keys) do menus.deck_composition[#menus.deck_composition+1] = cards[key] end
  if count > 0 then menus.deck_scope = 'displayed_menu' end
end

local function setup_hover(card,kind,unknowns)
  local center=card.config and card.config.center
  local description=array()
  if not center then return nil,description end
  if kind=='stake' then
    -- Locked chips only expose the native lock label. Do not materialize the
    -- unavailable stake's full description or consult profile/save progress.
    if card.params.stake_chip_locked then return localize('run_select_locked_stake'),description end
    local name=caption(localize{type='name_text',set='Stake',key=center.key},unknowns)
    if G.UIDEF and type(G.UIDEF.stake_description)=='function' then
      local ok,ui=pcall(G.UIDEF.stake_description,center.order)
      if ok and type(ui)=='table' then
        description=visible_text(ui,true,unknowns,true); pcall(cleanup,ui)
      else issue(unknowns,'tooltip_unavailable') end
    else issue(unknowns,'tooltip_unavailable') end
    return name,description
  end
  -- This is the very Back tooltip constructed by the fixed selector's hover,
  -- without invoking hover, sound, RNG, or any action callback on the card.
  if not Back then issue(unknowns,'tooltip_unavailable'); return nil,description end
  local ok,back=pcall(Back,center)
  if not ok or not back or type(back.get_name)~='function' or type(back.generate_UI)~='function' then
    issue(unknowns,'tooltip_unavailable'); return nil,description
  end
  local ok_name,name=pcall(back.get_name,back)
  local ok_ui,ui=pcall(back.generate_UI,back)
  if ok_ui and type(ui)=='table' then
    description=visible_text(ui,true,unknowns,true); pcall(cleanup,ui)
  else issue(unknowns,'tooltip_unavailable') end
  if not ok_name then issue(unknowns,'tooltip_unavailable') end
  return ok_name and caption(name,unknowns) or nil,description
end
local function add_main_menu_setup(public, root)
  local nodes, selector_present, native_present, stake_name, deck_hover_name = {}, false, false, nil, nil
  walk(root, function(node)
    local c = node.config or {}
    if c.id == 'run_select' and displayed(node) then selector_present = true end
    if c.func == 'can_start_run' or c.button == 'start_setup_run' then native_present = true end
    if c.id == 'deck_preview_text_1' or c.id == 'deck_preview_text_2' or c.id == 'preview_text_1' or c.id == 'preview_text_2' then
      if displayed(node) then nodes[c.id] = node end
    end
    local area = c.object
    if node.UIT == G.UIT.O and area and area.config and area.config.run_select_deck_preview and displayed(node) and displayed(area) then
      -- This is a deck-type illustration with a normal Back tooltip, not a
      -- face-down playing card. Restrict the fallback to current preview cards;
      -- selection candidates and offscreen holding areas are not queried.
      for _, card in ipairs(area.cards or {}) do
        local center = card.config and card.config.center
        if displayed(card) and card.params and card.params.run_select_preview_card == 'deck_choice'
           and center and center.set == 'Back' and type(center.key) == 'string'
           and center.unlocked == true and center.discovered ~= false then
          local ok, name = pcall(localize, {type='name_text',set='Back',key=center.key})
          if ok and text(name) and name ~= 'ERROR' then deck_hover_name = name end
        end
      end
    end
    if node.UIT == G.UIT.O and area and area.config and area.config.run_select_stake_tower
       and displayed(node) and displayed(area) then
      -- These are the already-rendered stake chips from the native selector,
      -- not playing cards or a hidden holding area. Native draw_card_from
      -- removes the last holding chip first: the selected top chip is the
      -- first visible card, followed by its previously applied stakes.
      for _, card in ipairs(area.cards or {}) do
        local params = card.params and card.params.run_select_stake_tower
        local key = params and params[2]
        if displayed(card) and type(key) == 'string' and G.P_STAKES and G.P_STAKES[key] then
          stake_name = localize{type='name_text',set='Stake',key=key}
          break
        end
      end
    end
  end)
  if selector_present then
    local selector = SMODS.RunSelect
    local internals = selector and selector.Internals
    local current_page = internals and internals.pages and internals.pages[internals.current_page]
    local prefix
    if nodes.deck_preview_text_1 then prefix = 'deck_'
    elseif current_page == 'deck_choice' then prefix = '' end
    local parts = {}
    if prefix then
      for i=1,2 do
        for _, part in ipairs(visible_text(nodes[prefix..'preview_text_'..i], true)) do
          if #part > 0 then parts[#parts+1] = part end
        end
      end
    end
    local deck_name = #parts > 0 and table.concat(parts, ' ') or deck_hover_name
    public.setup = {availability=(deck_name or stake_name) and 'observed' or 'unknown',deck_name=deck_name,stake_name=stake_name,
                    page=(current_page=='deck_choice' or current_page=='stake_choice') and current_page or nil,options=array()}
    local kind=current_page=='deck_choice' and 'deck' or current_page=='stake_choice' and 'stake' or nil
    if kind then
      local seen={}
      walk(root,function(node)
        local area=node.UIT==G.UIT.O and node.config and node.config.object
        if not area or seen[area] or not area.config or area.config.run_select~=current_page
           or not displayed(node) or not displayed(area) then return end
        seen[area]=true
        local card=area.cards and area.cards[#area.cards]
        local choice=card and card.params and card.params.run_select_selection_choice
        if not card or not displayed(card) or not choice or choice[2]~=current_page then return end
        local center=card.config and card.config.center
        if not center or (kind=='deck' and center.set~='Back') then return end
        local enabled=public.ready and card.states and card.states.click and card.states.click.can==true
                      and not card.under_overlay and not card.disable_button
        enabled=enabled and (kind=='stake' and not card.params.stake_chip_locked
                            or kind=='deck' and center.unlocked==true and center.discovered~=false) or false
        local selected=SMODS.RunSelect.Setup and SMODS.RunSelect.Setup.choices
                       and SMODS.RunSelect.Setup.choices[current_page]==(kind=='stake' and card.params.stake or center.key) or false
        local name,description=setup_hover(card,kind,public.unknowns)
        local position=#public.setup.options
        public.setup.options[#public.setup.options+1]={kind=kind,position=position,name=name,description=description,
                                                       enabled=enabled,selected=selected}
        R.setup_bindings[#R.setup_bindings+1]={kind=kind,position=position,card=card,option=public.setup.options[#public.setup.options]}
      end)
    end
    if not deck_name or not stake_name then public.unknowns[#public.unknowns+1] = 'unconfirmed_field' end
    -- Never read the selector's full choices, seed, holding cards or next page.
    return
  end
  if native_present then
    local back=G.GAME and G.GAME.viewed_back and G.GAME.viewed_back.effect and G.GAME.viewed_back.effect.center
    if back then public.setup.deck_name=localize{type='name_text',set='Back',key=back.key}; public.setup.availability='observed' end
    local stake_names={'white','red','green','black','blue','purple','orange','gold'}
    local stake_name=G.viewed_stake and stake_names[G.viewed_stake]
    if stake_name then public.setup.stake_name=localize{type='name_text',set='Stake',key='stake_'..stake_name} end
  end
end

function R.health() return envelope() end
function R.snapshot()
  R.bindings = {}
  R.setup_bindings = {}
  local out = envelope()
  -- Reading a recognized native profile is allowed independently of the
  -- configured test profile. Future actions must keep their own commit gate.
  if out.profile == nil or out.compatibility ~= 'supported' then return out end
  local phase, ready, reason = out.phase, out.ready, out.ready_reason
  local public = {phase=phase,ready=ready,ready_reason=reason,resources={availability='not_applicable'},setup={availability='not_applicable'},regions=array(),blinds=array(),ui_actions=array(),
                  settlement_text=array(),menus={poker_hands=array(),deck_composition=array(),deck_scope='not_open'},unknowns=array()}
  local stable = ready or phase == 'menu'
  if not ready and phase ~= 'main_menu' and phase ~= 'menu' and phase ~= 'unsupported' then
    public.underlying_phase = phase; public.phase='transition'; out.phase='transition'
    public.unknowns[#public.unknowns+1] = 'transition_regions_suppressed'
  end
  local targets, roots = {}, {}
  local function root(node) if node and displayed(node) then roots[#roots+1] = node end end
  root(root_for(phase))
  -- A modal menu owns navigation input. The dimmed run HUD can remain drawn
  -- but is not another menu button surface (e.g. Settings Back vs Options).
  if phase~='menu' and phase~='main_menu' and phase~='terminal' then root(G.HUD) end
  if phase == 'round_eval' then
    for _, entry in ipairs(settlement_cash_ui()) do if entry.box ~= G.round_eval then root(entry.box) end end
  end
  if G.STAGE == G.STAGES.RUN then
    local game, round, resets = G.GAME, G.GAME.current_round or {}, G.GAME.round_resets or {}
    -- Stable HUD fields, including legitimate zero values. No 0 fallback.
    if displayed(G.HUD) then
      public.resources={availability='observed',dollars=scalar(game.dollars), chips=scalar(game.chips), hands_left=round.hands_left,
                        discards_left=round.discards_left,ante=resets.ante,round=game.round}
    else public.resources.availability='unknown'; public.unknowns[#public.unknowns+1] = 'unconfirmed_field' end
    if stable and phase == 'shop' then public.resources.reroll_cost=scalar(round.reroll_cost) end
    if stable and phase == 'pack' then public.resources.pack_choices=game.pack_choices end
    if game.selected_back and game.selected_back.effect and game.selected_back.effect.center then
      public.setup.deck_name=localize{type='name_text',set='Back',key=game.selected_back.effect.center.key}
      public.setup.availability='observed'
    end
    local stake = G.P_STAKES and G.P_STAKES['stake_' .. ({'white','red','green','black','blue','purple','orange','gold'})[game.stake or 1]]
    if stake then public.setup.stake_name=localize{type='name_text',set='Stake',key=stake.key} end
    if stable and phase ~= 'main_menu' and phase ~= 'terminal' then
      for _, field in ipairs(region_fields) do
        local name, area = field[1], G[field[2]]
        local allowed = (name=='hand' and (phase=='hand' or phase=='pack')) or name=='jokers' or name=='consumables' or (phase=='shop' and name:sub(1,5)=='shop_') or (phase=='pack' and name=='pack')
        if allowed and area and displayed(area) then
          local region = {name=name,capacity=area.config.card_limit,selection_limit=area.config.highlighted_limit or area.config.highlight_limit,cards=array()}
          for index, card in ipairs(area.cards or {}) do
            if displayed(card) then
              local value=public_card(card,index-1,name,public.unknowns)
              region.cards[#region.cards+1]=value
              targets[card]={region=name,position=index-1,hidden=value.visibility=='face_down'}
              for key, child in pairs(card.children or {}) do
                -- Native Card:draw renders these controls only when selected.
                -- Purchase removes buy_button but can leave its sibling object;
                -- a stale visible flag cannot make that sibling a displayed UI.
                local rendered = true
                if key == 'buy_button' or key == 'use_button' then rendered = card.highlighted
                elseif key == 'buy_and_use_button' then rendered = card.highlighted and displayed(card.children.buy_button) end
                if rendered then root(child) end
              end
            end
          end
          public.regions[#public.regions+1]=region
        end
      end
      add_blinds(public)
      add_menus(public)
      if phase=='blind_select' and G.blind_select.get_UIE_by_ID then
        for _, blind in ipairs(public.blinds) do
          local branch=G.blind_select:get_UIE_by_ID(blind.slot)
          walk(branch,function(node)
            local ref=node.config and node.config.ref_table
            if ref then targets[ref]={blind_slot=blind.slot} end
          end)
        end
      end
    end
    if phase=='round_eval' and displayed(G.round_eval) then
      public.settlement_text=visible_text(G.round_eval,true)
      for _, entry in ipairs(settlement_cash_ui()) do
        if entry.box ~= G.round_eval then
          for _, part in ipairs(visible_text(entry.box,true)) do public.settlement_text[#public.settlement_text+1] = part end
        end
      end
    end
  end
  if phase=='terminal' and ready then public.outcome=terminal_marker(root_for(phase)) end
  public.ui_actions=ui_actions(roots,targets,ready,R.bindings)
  -- The deck's top back is a normal clickable menu entrance; identity is not read.
  if stable and phase ~= 'terminal' and phase ~= 'main_menu' and phase ~= 'menu'
     and displayed(G.deck) and G.deck.cards and displayed(G.deck.cards[1])
     and G.deck.cards[1].states and G.deck.cards[1].states.click and G.deck.cards[1].states.click.can then
    public.ui_actions[#public.ui_actions+1]={name='deck_info',enabled=ready,label=array()}
    R.bindings[#R.bindings+1]={card=G.deck.cards[1],action=public.ui_actions[#public.ui_actions]}
  end
  if (phase=='main_menu' or phase=='menu') and ready then add_main_menu_setup(public,root_for(phase)) end
  public.preferences={availability='not_open'}
  walk(root_for(phase),function(node)
    local c=node.config or {}; local cycle=c.ref_table
    if displayed(node) and c.button=='option_cycle' and cycle and cycle.opt_callback=='change_gamespeed' then
      local speed=cycle.options and cycle.options[cycle.current_option]
      if speed==0.5 or speed==1 or speed==2 or speed==4 then
        public.preferences.game_speed=speed; public.preferences.availability='observed'
      end
    end
  end)
  out.public=public
  return out
end

return R
