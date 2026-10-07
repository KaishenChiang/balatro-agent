"""Mechanical target selection preserves native transactions and uncertainty."""
import pytest
import tomllib

from test_executor import ROOT, game, request, native_start_wrappers


def purchase_scene(game, price=5):
    lua, _, _ = game
    source = (ROOT / '.artifacts/game-source/functions/button_callbacks.lua').read_text(encoding='utf-8')
    lua.execute(source[source.index('G.FUNCS.can_buy ='):source.index('G.FUNCS.can_buy_and_use =')])
    lua.execute(source[source.index('G.FUNCS.check_for_buy_space ='):source.index('  G.FUNCS.toggle_shop =')])
    lua.globals().TEST_PRICE = price
    lua.execute('''
      reroll_scene(); attach_native_area(G.shop_jokers)
      G.shop_jokers.config.type='shop'; G.shop_jokers.config.highlighted_limit=1
      G.GAME.current_round.jokers_purchased=0
      G.GAME.round_scores.cards_purchased={amt=0}; G.jokers.cards={}
      G.jokers.emplace=function(self,c) self.cards[#self.cards+1]=c; c.area=self end
      G.C={UI={BACKGROUND_INACTIVE='inactive'},ORANGE='orange'}
      TEST_PRODUCT=G.shop_jokers.cards[1]; TEST_PRODUCT.ability.set='Joker'
      TEST_PRODUCT.config.center.set='Joker'; TEST_PRODUCT.cost=TEST_PRICE
      TEST_PRODUCT.is=function() return true end; TEST_PRODUCT.add_to_deck=function() end
      TEST_PRODUCT.calculate_joker=function() end
      TEST_BUY=ui({button='buy_from_shop',func='can_buy',ref_table=TEST_PRODUCT})
      TEST_BUY.click=UIElement.click
      TEST_PRODUCT.children.buy_button=ui_box({}, {TEST_BUY})
      TEST_PRODUCT.children.buy_button.remove=function(self) self.removed=true end
      G.FUNCS.can_buy(TEST_BUY)
    ''')


def finish(game, req):
    _, call, tick = game
    for _ in range(20):
        result = call('action_status', {'action_id': req['action_id']})
        if result['state'] != 'RUNNING':
            return result
        tick()
    return call('action_status', {'action_id': req['action_id']})


@pytest.mark.parametrize('price', [0, 5])
def test_direct_purchase_uses_one_request_and_native_effect_once(game, price):
    lua, call, _ = game
    purchase_scene(game, price)
    assert not any(a['name'] == 'buy' for a in call('reader_snapshot')['public']['ui_actions'])
    req = request(game, 'buy', {'region': 'shop_jokers', 'position': 0}, 'direct-buy')
    started = call('act_submit', req)
    assert started['state'] == 'RUNNING' and not started['callback_confirmed']
    assert lua.eval('TEST_PRODUCT.highlighted') and lua.eval('G.GAME.dollars') == 10
    assert call('act_submit', req)['duplicate']
    result = finish(game, req)
    assert result['state'] == 'COMPLETED' and result['callback_confirmed'] and result['related_events_complete']
    assert lua.eval('G.GAME.dollars') == 10 - price
    assert lua.eval('#G.jokers.cards') == 1
    assert lua.eval('G.GAME.round_scores.cards_purchased.amt') == 1
    assert call('act_submit', req)['state'] == 'COMPLETED'
    assert lua.eval('G.GAME.round_scores.cards_purchased.amt') == 1


@pytest.mark.parametrize('gate', ['money', 'capacity', 'profile', 'stale', 'hidden', 'click', 'invalid', 'selected_disabled'])
def test_direct_purchase_preflight_refuses_without_selection_or_spending(game, gate):
    lua, call, _ = game
    purchase_scene(game)
    if gate == 'money':
        lua.execute('G.GAME.dollars=1')
    elif gate == 'capacity':
        lua.execute('G.jokers.config.card_limit=0')
    elif gate == 'hidden':
        lua.execute("TEST_PRODUCT.facing='back'; TEST_PRODUCT.sprite_facing='back'")
    elif gate == 'click':
        lua.execute('TEST_PRODUCT.states.click.can=false')
    elif gate == 'selected_disabled':
        lua.execute('TEST_PRODUCT:click(); TEST_BUY.disable_button=true')
    position = 99 if gate == 'invalid' else 0
    req = request(game, 'buy', {'region': 'shop_jokers', 'position': position}, 'gated-buy')
    if gate == 'profile':
        lua.execute('G.SETTINGS.profile=1')
    if gate == 'stale':
        req['observation_id'] = 'obs-' + req['game_session'] + '-0'
    before = call('reader_snapshot')
    result = call('act_submit', req)
    assert result['state'] == 'REJECTED' and result['submitted'] is False
    assert call('reader_snapshot') == before
    assert lua.eval('#G.jokers.cards') == 0


@pytest.mark.parametrize('break_context', [False, True])
def test_uncertain_target_preparation_never_executes_later(game, break_context):
    lua, call, tick = game
    purchase_scene(game)
    lua.execute('TEST_BUY.disable_button=true')
    req = request(game, 'buy', {'region': 'shop_jokers', 'position': 0}, 'uncertain-buy')
    assert call('act_submit', req)['state'] == 'RUNNING'
    if break_context:
        lua.execute('G.shop_jokers.cards={}')
        tick()
    else:
        tick(61)
    assert call('action_status', {'action_id': req['action_id']})['state'] == 'UNKNOWN'
    lua.execute('TEST_BUY.disable_button=false')
    for _ in range(4):
        tick()
    assert lua.eval('G.GAME.dollars') == 10 and lua.eval('#G.jokers.cards') == 0
    assert call('action_status', {'action_id': req['action_id']})['state'] == 'UNKNOWN'
    assert call('act_submit', request(game, 'reroll', {}, 'blocked-new'))['reason'] == 'action_busy'


@pytest.mark.parametrize('eternal', [False, True])
def test_direct_sale_checks_native_eligibility_and_callback(game, eternal):
    lua, call, _ = game
    purchase_scene(game)
    source = (ROOT / '.artifacts/game-source/card.lua').read_text(encoding='utf-8')
    lua.execute(source[source.index('function Card:can_sell_card'):source.index('function Card:calculate_dollar_bonus')])
    source = (ROOT / '.artifacts/game-source/functions/button_callbacks.lua').read_text(encoding='utf-8')
    lua.execute(source[source.index('  G.FUNCS.can_sell_card ='):source.index('  G.FUNCS.can_skip_booster =')])
    lua.globals().TEST_ETERNAL = eternal
    lua.execute('''
      G.shop_jokers.cards={}; G.jokers.cards={TEST_PRODUCT}; attach_native_area(G.jokers)
      G.jokers.config.type='joker'; G.SETTINGS.tutorial_complete=true
      TEST_PRODUCT.ability.eternal=TEST_ETERNAL; TEST_PRODUCT.can_sell_card=Card.can_sell_card
      TEST_SELL=ui({func='can_sell_card',ref_table=TEST_PRODUCT}); TEST_SELL.click=UIElement.click
      TEST_PRODUCT.children={use_button=ui_box({}, {TEST_SELL})}
      G.C.GREEN='green'; G.FUNCS.can_sell_card(TEST_SELL)
      TEST_SALES=0
      G.FUNCS.sell_card=function()
        G.E_MANAGER:add_event(Event({func=function()
          TEST_SALES=TEST_SALES+1; G.jokers.cards={}; G.GAME.dollars=G.GAME.dollars+2
          return true
        end}))
      end
    ''')
    req = request(game, 'sell', {'region': 'jokers', 'position': 0}, 'direct-sale')
    before = call('reader_snapshot')
    started = call('act_submit', req)
    if eternal:
        assert started['state'] == 'REJECTED' and call('reader_snapshot') == before
        assert lua.eval('TEST_SALES') == 0
    else:
        assert started['state'] == 'RUNNING'
        result = finish(game, req)
        assert result['state'] == 'COMPLETED' and lua.eval('TEST_SALES') == 1
        assert lua.eval('G.GAME.dollars') == 12


def use_scene(game, action, targeted_hand=False):
    """Actual native eligibility/selection; isolated delayed effect is a fixture."""
    lua, _, _ = game
    purchase_scene(game)
    source = (ROOT / '.artifacts/game-source/card.lua').read_text(encoding='utf-8')
    eligibility = source[source.index('function Card:can_use_consumeable'):source.index('function Card:check_use')]
    # Apply the exact fixed Steamodded booster-state patch to the native method.
    patches = tomllib.loads((ROOT / '.artifacts/upstream/smods-26.829.0/lovely/booster.toml').read_text(encoding='utf-8'))['patches']
    matches = [item['pattern'] for item in patches if item.get('pattern', {}).get('target') == 'card.lua'
               and item['pattern']['pattern'].startswith('if G.STATE == G.STATES.SELECTING_HAND or')]
    assert len(matches) == 1 and eligibility.count(matches[0]['pattern']) == 1
    eligibility = eligibility.replace(matches[0]['pattern'], matches[0]['payload'])
    lua.execute(eligibility)
    if action in ('use_pack', 'select_pack_card'):
        from test_lua_boundary import STEAMODDED_PACK_UI
        lua.execute(STEAMODDED_PACK_UI)
        lua.execute('TEST_PRODUCT=G.pack_cards.cards[1]; attach_native_area(G.pack_cards); G.pack_cards.config.highlighted_limit=1')
    elif action == 'use_owned':
        lua.execute('G.shop_jokers.cards={}; G.consumeables.cards={TEST_PRODUCT}; attach_native_area(G.consumeables)')
    source = (ROOT / '.artifacts/game-source/functions/button_callbacks.lua').read_text(encoding='utf-8')
    lua.execute(source[source.index('G.FUNCS.can_buy_and_use ='):source.index('--Checks if the cost of a voucher')])
    lua.execute(source[source.index('  G.FUNCS.can_use_consumeable ='):source.index('  G.FUNCS.can_sell_card =')])
    lua.globals().TEST_HAND_TARGET = targeted_hand
    lua.globals().TEST_USE_ACTION = action
    lua.execute('''
      G.C.RED='red'; G.C.GREEN='green'; G.C.SECONDARY_SET={Voucher='voucher'}
      TEST_PRODUCT.ability.set=TEST_USE_ACTION=='select_pack_card' and 'Joker' or 'Planet'
      if TEST_USE_ACTION=='select_pack_card' then TEST_PRODUCT.ability.consumeable=nil
      else TEST_PRODUCT.ability.consumeable={hand_type='Flush'} end
      if TEST_HAND_TARGET then
        if TEST_USE_ACTION=='use_owned' then G.STATE=G.STATES.SELECTING_HAND end
        TEST_PRODUCT.ability.consumeable={min_highlighted=1,max_highlighted=1,mod_num=1}
      end
      TEST_PRODUCT.can_use_consumeable=Card.can_use_consumeable
      local func=TEST_USE_ACTION=='buy_and_use' and 'can_buy_and_use'
        or TEST_USE_ACTION=='select_pack_card' and 'can_select_card' or 'can_use_consumeable'
      TEST_USE=ui({button='use_card',func=func,ref_table=TEST_PRODUCT}); TEST_USE.click=UIElement.click
      local box=ui_box({}, {TEST_USE}); TEST_USE.UIBox=box
      if TEST_USE_ACTION=='buy_and_use' then
        TEST_PRODUCT.children.buy_and_use_button=box
      else TEST_PRODUCT.children={use_button=box} end
      TEST_USES=0; TEST_HAND_AT_USE=nil
      local function effect()
        TEST_HAND_AT_USE=G.hand.highlighted[1]
        G.E_MANAGER:add_event(Event({func=function() TEST_USES=TEST_USES+1; return true end}))
      end
      G.FUNCS.use_card=effect
      if TEST_USE_ACTION=='buy_and_use' then G.FUNCS.buy_from_shop=effect end
    ''')
    return ('shop_jokers' if action == 'buy_and_use' else 'consumables' if action == 'use_owned' else 'pack')


@pytest.mark.parametrize('action', ['use_owned', 'use_pack', 'buy_and_use', 'select_pack_card'])
def test_direct_use_retains_native_button_events_and_dedup(game, action):
    lua, call, _ = game
    region = use_scene(game, action)
    semantic = 'use' if action.startswith('use_') else action
    req = request(game, semantic, {'region': region, 'position': 0}, 'one-use')
    assert call('act_submit', req)['state'] == 'RUNNING'
    assert lua.eval('TEST_USES') == 0
    assert call('act_submit', req)['duplicate']
    assert call('act_submit', request(game, 'reroll', {}, 'parallel'))['reason'] == 'action_busy'
    result = finish(game, req)
    assert result['state'] == 'COMPLETED' and result['callback_confirmed'] and result['related_events_complete']
    assert lua.eval('TEST_USES') == 1
    assert call('act_submit', req)['state'] == 'COMPLETED' and lua.eval('TEST_USES') == 1


@pytest.mark.parametrize('selected', [False, True])
def test_direct_consumable_never_chooses_hand_target(game, selected):
    lua, call, _ = game
    region = use_scene(game, 'use_owned', targeted_hand=True)
    if selected:
        lua.execute('G.hand.cards[2]:click()')
    before = call('reader_snapshot')
    req = request(game, 'use', {'region': region, 'position': 0}, 'hand-use')
    started = call('act_submit', req)
    if not selected:
        assert started['state'] == 'REJECTED' and started['submitted'] is False
        assert call('reader_snapshot') == before and lua.eval('TEST_USES') == 0
    else:
        assert finish(game, req)['state'] == 'COMPLETED'
        assert lua.eval('TEST_HAND_AT_USE==G.hand.cards[2]')
        assert lua.eval('#G.hand.highlighted') == 1


@pytest.mark.parametrize('action', ['use_owned', 'use_pack', 'buy_and_use', 'select_pack_card'])
@pytest.mark.parametrize('break_context', [False, True])
def test_direct_use_timeout_or_changed_target_never_has_late_effect(game, action, break_context):
    lua, call, tick = game
    region = use_scene(game, action)
    lua.execute('TEST_USE.disable_button=true')
    req = request(game, 'use' if action.startswith('use_') else action, {'region': region, 'position': 0}, 'late-use')
    assert call('act_submit', req)['state'] == 'RUNNING'
    if break_context:
        area = {'pack': 'pack_cards', 'consumables': 'consumeables', 'shop_jokers': 'shop_jokers'}[region]
        lua.execute('G.' + area + '.cards={}')
        tick()
    else:
        tick(61)
    assert call('action_status', {'action_id': req['action_id']})['state'] == 'UNKNOWN'
    lua.execute('TEST_USE.disable_button=false')
    for _ in range(4):
        tick()
    assert lua.eval('TEST_USES') == 0


@pytest.mark.parametrize('gate', ['money', 'selected_disabled', 'capacity', 'zero_choices', 'ankh_capacity', 'hidden'])
def test_direct_use_preflight_preserves_public_state(game, gate):
    lua, call, _ = game
    action = 'buy_and_use' if gate == 'money' else 'select_pack_card' if gate == 'capacity' else 'use_pack'
    region = use_scene(game, action)
    mutations = {
        'money': 'G.GAME.dollars=1',
        'selected_disabled': 'TEST_PRODUCT:click(); TEST_USE.disable_button=true',
        'capacity': 'G.jokers.config.card_limit=0',
        'zero_choices': 'G.GAME.pack_choices=0',
        'ankh_capacity': "TEST_PRODUCT.ability.name='Ankh'; TEST_PRODUCT.can_use_consumeable=function() return true end; G.jokers.config.card_limit=0",
        'hidden': "TEST_PRODUCT.facing='back'; TEST_PRODUCT.sprite_facing='back'",
    }
    lua.execute(mutations[gate])
    req = request(game, 'use' if action == 'use_pack' else action, {'region': region, 'position': 0}, 'use-gate')
    before = call('reader_snapshot')
    result = call('act_submit', req)
    assert result['state'] == 'REJECTED' and result['submitted'] is False
    assert call('reader_snapshot') == before and lua.eval('TEST_USES') == 0


@pytest.mark.parametrize('card_set', ['Tarot', 'Planet', 'Spectral'])
def test_use_only_pack_rejects_take_before_selection_and_allows_use(game, card_set):
    lua, call, _ = game
    use_scene(game, 'use_pack')
    lua.globals().TEST_PACK_SET = card_set
    lua.execute('TEST_PRODUCT.ability.set=TEST_PACK_SET')
    before = call('reader_snapshot')
    req = request(game, 'select_pack_card', {'region': 'pack', 'position': 0}, 'wrong-pack-semantic')
    result = call('act_submit', req)
    assert result['state'] == 'REJECTED' and result['submitted'] is False
    assert result['reason'] == 'invalid_target' and result['callback_confirmed'] is False
    assert call('reader_snapshot') == before
    assert not lua.eval('TEST_PRODUCT.highlighted') and lua.eval('TEST_USES') == 0
    # A wrong semantic must not leave an active UNKNOWN or block the right one.
    correct = request(game, 'use', {'region': 'pack', 'position': 0}, 'actual-pack-use')
    assert call('act_submit', correct)['state'] == 'RUNNING'
    assert finish(game, correct)['state'] == 'COMPLETED'
    assert lua.eval('TEST_USES') == 1


@pytest.mark.parametrize('selected', [False, True])
def test_pack_tarot_use_preserves_separately_chosen_hand_targets(game, selected):
    lua, call, _ = game
    use_scene(game, 'use_pack', targeted_hand=True)
    lua.execute("TEST_PRODUCT.ability.set='Tarot'; TEST_PRODUCT.ability.name='The Hanged Man'; TEST_PRODUCT.ability.consumeable={min_highlighted=1,max_highlighted=2,mod_num=2}")
    if selected:
        lua.execute('G.hand.cards[1]:click(); G.hand.cards[2]:click()')
    before = call('reader_snapshot')
    wrong = request(game, 'select_pack_card', {'region': 'pack', 'position': 0}, 'hanged-take')
    assert call('act_submit', wrong)['state'] == 'REJECTED'
    assert call('reader_snapshot') == before
    correct = request(game, 'use', {'region': 'pack', 'position': 0}, 'hanged-use')
    result = call('act_submit', correct)
    if not selected:
        assert result['state'] == 'REJECTED' and result['submitted'] is False
        assert call('reader_snapshot') == before and lua.eval('TEST_USES') == 0
    else:
        assert finish(game, correct)['state'] == 'COMPLETED'
        assert lua.eval('TEST_HAND_AT_USE==G.hand.cards[1]')
        assert lua.eval('#G.hand.highlighted') == 2
        assert lua.eval('G.hand.cards[1].highlighted and G.hand.cards[2].highlighted')


@pytest.mark.parametrize('card_set', ['Default', 'Enhanced', 'Joker'])
def test_native_playing_card_and_joker_pack_take_remains_available(game, card_set):
    lua, call, _ = game
    use_scene(game, 'select_pack_card')
    lua.globals().TEST_PACK_SET = card_set
    lua.execute('TEST_PRODUCT.ability.set=TEST_PACK_SET')
    req = request(game, 'select_pack_card', {'region': 'pack', 'position': 0}, 'pack-take')
    assert call('act_submit', req)['state'] == 'RUNNING'
    assert finish(game, req)['state'] == 'COMPLETED' and lua.eval('TEST_USES') == 1


@pytest.mark.parametrize('enabled', [False, True])
def test_selected_consumable_pack_take_requires_actual_extra_button(game, enabled):
    lua, call, _ = game
    use_scene(game, 'use_pack')
    lua.globals().TEST_SELECT_ENABLED = enabled
    lua.execute('''
      TEST_PRODUCT.ability.set='Tarot'; TEST_PRODUCT:click()
      local node=ui({ref_table=TEST_PRODUCT,func='can_select_from_booster',button=TEST_SELECT_ENABLED and 'use_card' or nil})
      node.click=UIElement.click
      TEST_PRODUCT.children.select_button=ui_box({}, {node})
    ''')
    before = call('reader_snapshot')
    req = request(game, 'select_pack_card', {'region': 'pack', 'position': 0}, 'explicit-pack-take')
    result = call('act_submit', req)
    if enabled:
        assert result['state'] == 'RUNNING'
        assert finish(game, req)['state'] == 'COMPLETED' and lua.eval('TEST_USES') == 1
    else:
        assert result['state'] == 'REJECTED' and result['submitted'] is False
        assert call('reader_snapshot') == before and lua.eval('TEST_USES') == 0
