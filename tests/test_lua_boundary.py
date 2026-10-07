import copy
import json
from pathlib import Path
import pytest

from balatro_agent.contract import Envelope, Observation, SCHEMA_VERSION, POLICY_VERSION
from balatro_agent.policy import project, canonical, observation_id


def public(snapshot):
    envelope=Envelope.model_validate(snapshot())
    result=project(envelope.public)
    Observation.model_validate({**result,'profile':envelope.profile,
                               'schema_version':SCHEMA_VERSION,'visibility_policy_version':POLICY_VERSION,
                               'observation_id':envelope.observation_id})
    return result


def test_real_lua_and_real_wire_json(lua_reader):
    lua, snapshot = lua_reader
    result = public(snapshot)
    assert result['resources']['dollars']==0
    assert result['resources']['chips']==0
    assert result['regions'][0]['cards'][0]['description']==['Public effect']
    assert lua.eval('G.hand.cards[1].ability.blueprint_compat_check') is None
    assert result['regions'][1]['cards']==[]
    assert 'HIDDEN' not in canonical(result)


@pytest.mark.parametrize('mutation',[
    "G.GAME.seed='OTHER_SECRET'; G.GAME.pseudorandom={state='OTHER_RNG'}",
    "G.deck.cards[1],G.deck.cards[2]=G.deck.cards[2],G.deck.cards[1]",
    "G.future_pack={card('SECRET_UNOPENED')}; G.shop_jokers=area({card('SECRET_UNDISPLAYED')})",
    "G.hand.cards[1].sort_id='OTHER_ID'; G.hand.cards[1].playing_card='OTHER_PERMANENT_ID'",
    "G.hand.cards[1].internal_new_field='SECRET_FUTURE_RESULT'",
])
def test_hidden_metamorphic_public_and_identifier_invariance(lua_reader,mutation):
    lua,snapshot=lua_reader
    before=public(snapshot)
    lua.execute(mutation)
    after=public(snapshot)
    assert canonical(before)==canonical(after)
    assert observation_id(before)==observation_id(after)


def test_face_down_never_invokes_identity_tooltip(lua_reader):
    lua,snapshot=lua_reader
    lua.execute("G.hand.cards[1].facing='back'; G.hand.cards[1].sprite_facing='back'; G.hand.cards[1].generate_UIBox_ability_table=function() error('SECRET_TOOLTIP') end")
    before=public(snapshot)
    card=before['regions'][0]['cards'][0]
    assert card=={'position':0,'visibility':'face_down','selected':False}
    lua.execute("G.hand.cards[1].base={value='King',suit='Clubs'}; G.hand.cards[1].public_name='SECRET_CHANGED'; G.hand.cards[1].cost=200; G.hand.cards[1].ability={name='Secret joker',set='Joker'}")
    after=public(snapshot)
    assert before==after


def test_sprite_not_yet_flipped_cannot_reveal(lua_reader):
    lua,snapshot=lua_reader
    lua.execute("G.hand.cards[1].sprite_facing='back'")
    assert public(snapshot)['regions'][0]['cards'][0]['visibility']=='face_down'


def test_stone_never_exports_base_rank_suit(lua_reader):
    lua,snapshot=lua_reader
    lua.execute("G.hand.cards[1].ability.effect='Stone Card'; G.hand.cards[1].ability.name='Stone Card'")
    before=public(snapshot)
    card=before['regions'][0]['cards'][0]
    assert card['visibility']=='stone' and card['rank'] is None and card['suit'] is None
    lua.execute("G.hand.cards[1].base={value='Queen',suit='Diamonds'}")
    assert before==public(snapshot)


def test_misprint_generator_not_called(lua_reader):
    lua,snapshot=lua_reader
    lua.execute("G.hand.cards[1].ability.name='Misprint'; G.hand.cards[1].generate_UIBox_ability_table=function() error('SECRET_DECK_READ') end")
    result=public(snapshot)
    assert 'dynamic_tooltip_omitted' in result['unknowns']
    assert 'SECRET' not in canonical(result)


@pytest.mark.parametrize('state', ['HAND_PLAYED','DRAW_TO_HAND','NEW_ROUND','PLAY_TAROT'])
def test_processing_is_not_ready_and_no_early_cards(lua_reader,state):
    lua,snapshot=lua_reader
    lua.execute('G.STATE=G.STATES.'+state)
    result=public(snapshot)
    assert result['phase']=='transition' and result['ready'] is False and result['regions']==[]


@pytest.mark.parametrize('mutation', ['G.CONTROLLER.locked=true', 'G.CONTROLLER.locks.use=true','G.CONTROLLER.locks.shop_reroll=true','G.STATE_COMPLETE=false','G.buttons.states.visible=false','G.GAME.STOP_USE=1'])
def test_initialization_effects_and_ui_locks_block_readiness(lua_reader,mutation):
    lua,snapshot=lua_reader
    lua.execute(mutation)
    result=public(snapshot)
    assert not result['ready'] and result['regions']==[]


@pytest.mark.parametrize('state,setup,phase',[
    ('MENU',"G.STAGE=G.STAGES.MAIN_MENU; G.MAIN_MENU_UI=ui()",'main_menu'),
    ('BLIND_SELECT',"G.blind_select=ui()",'blind_select'),
    ('ROUND_EVAL',"G.round_eval=ui({}, {ui({id='cash_out_button',button='cash_out'})})",'round_eval'),
    ('SHOP',"G.shop=ui(); G.shop_jokers=area({card('Shop public')},2)",'shop'),
    ('STANDARD_PACK',"G.booster_pack=ui(); G.pack_cards=area({card('Pack public')}); G.GAME.pack_choices=1",'pack'),
    ('GAME_OVER',"G.OVERLAY_MENU=ui_box({}, {ui({id='from_game_over',button='notify_then_setup_run'}),ui({button='go_to_menu'})})",'terminal'),
])
def test_supported_core_phases_schema(lua_reader,state,setup,phase):
    lua,snapshot=lua_reader
    lua.execute('G.STATE=G.STATES.'+state+';'+setup)
    result=public(snapshot)
    assert result['phase']==phase and result['ready']
    if phase=='terminal': assert result['outcome']=='loss'
    if phase=='main_menu': assert result['resources']['availability']=='not_applicable'


def terminal_ui(lua, outcome='loss'):
    # Native game-over pauses the run with an existing card-use counter.
    # Use its current UIRoot/buttons, not a stored or undisplayed UI definition.
    lua.execute("""
        G.STATE=G.STATES.GAME_OVER; G.SETTINGS.paused=true; G.GAME.STOP_USE=7
        G.OVERLAY_MENU=ui_box({}, {
            ui({id='from_game_over',button='notify_then_setup_run'}, {ui({text='New Run'})}),
            ui({button='go_to_menu'}, {ui({text='Main Menu'})})})
        G.FUNCS={notify_then_setup_run=function() error('ACTION_CALLED') end,
                 go_to_menu=function() error('ACTION_CALLED') end}
    """)
    if outcome == 'win':
        lua.execute("G.STATE=G.STATES.ROUND_EVAL; G.OVERLAY_MENU.UIRoot.config.id='you_win_UI'; G.OVERLAY_MENU.UIRoot.children[1].config.id='from_game_won'")


@pytest.mark.parametrize('outcome', ['loss', 'win'])
def test_paused_terminal_navigation_is_not_blocked_by_card_use_counter(lua_reader, outcome):
    lua,snapshot=lua_reader
    terminal_ui(lua, outcome)
    result=public(snapshot)
    assert result['phase']=='terminal' and result['ready'] and result['outcome']==outcome
    assert result['regions']==[] and result['menus']['poker_hands']==[]
    assert {a['name'] for a in result['ui_actions'] if a['enabled']} >= {'main_menu','open_run_setup'}
    assert lua.eval('G.GAME.STOP_USE') == 7 and lua.eval('G.SETTINGS.paused') is True
    before=canonical(result)
    lua.execute("G.deck.cards[1],G.deck.cards[2]=G.deck.cards[2],G.deck.cards[1]; G.GAME.seed='OTHER_SECRET'")
    assert canonical(public(snapshot))==before


@pytest.mark.parametrize('mutation', [
    'G.CONTROLLER.locked=true', 'G.CONTROLLER.lock_input=true',
    'G.CONTROLLER.locks.frame=true', 'G.STATE_COMPLETE=false',
    'G.OVERLAY_MENU.states.visible=false', 'G.OVERLAY_MENU.removed=true',
    'G.OVERLAY_MENU.T={x=0,y=100,w=5,h=5}',
    'G.OVERLAY_MENU.UIRoot.children[1].states.visible=false',
])
def test_terminal_still_requires_initialized_visible_operable_ui(lua_reader, mutation):
    lua,snapshot=lua_reader
    terminal_ui(lua)
    lua.execute(mutation)
    result=public(snapshot)
    assert not result['ready'] and result['outcome'] is None and result['regions']==[]


def test_new_run_menu_after_loss_does_not_republish_old_terminal_outcome(lua_reader):
    lua,snapshot=lua_reader
    terminal_ui(lua)
    assert public(snapshot)['outcome']=='loss'
    lua.execute("G.OVERLAY_MENU=ui_box({}, {ui({button='start_setup_run'}, {ui({text='Start'})})})")
    result=public(snapshot)
    assert result['phase']=='menu' and result['ready'] and result['outcome'] is None


def test_game_over_state_without_displayed_terminal_ui_cannot_confirm_loss(lua_reader):
    lua,snapshot=lua_reader
    lua.execute('G.STATE=G.STATES.GAME_OVER; G.GAME.STOP_USE=7; G.OVERLAY_MENU=nil')
    result=public(snapshot)
    assert not result['ready'] and result['outcome'] is None and result['regions']==[]


def test_deck_menu_multiset_never_native_order(lua_reader):
    lua,snapshot=lua_reader
    lua.execute("local a=area({card('Shown Ace'),card('Shown Ace')}); a.config.view_deck=true; G.OVERLAY_MENU=ui({}, {ui({object=a})})")
    before=public(snapshot)
    assert before['phase']=='menu'
    assert before['menus']['deck_scope']=='displayed_menu'
    assert len(before['menus']['deck_composition'])==1
    assert before['menus']['deck_composition'][0]['count']==2
    assert 'position' not in before['menus']['deck_composition'][0]['card']
    lua.execute("G.deck.cards={card('SECRET_NEW_DECK')}; G.GAME.seed='SECRET_NEW_SEED'")
    assert before==public(snapshot)


def test_native_profile_changes_are_reported_without_blocking_reading(lua_reader):
    lua,snapshot=lua_reader
    for value,expected in (('1',1),('2',2),('3',3),("'2'",2)):
        lua.execute('G.SETTINGS.profile='+value)
        result=snapshot()
        assert result['profile']==expected
        assert result['public']['regions'][0]['cards'][0]['description']==['Public effect']


@pytest.mark.parametrize('profile_value',['nil','true','false','0','4','1.5',"'BAD_PROFILE'",'math.huge','0/0'])
def test_unknown_native_profile_has_no_public_snapshot(lua_reader,profile_value):
    lua,snapshot=lua_reader
    lua.execute('G.SETTINGS.profile='+profile_value)
    lua.execute("G.hand.cards[1].generate_UIBox_ability_table=function() error('UNEXPECTED_IDENTITY_READ') end")
    result=snapshot()
    assert result.get('profile') is None and result.get('public') is None


@pytest.mark.parametrize('profile_value',[1,3])
def test_lua_reading_does_not_require_profile_attestation(lua_reader,profile_value):
    lua,snapshot=lua_reader
    lua.execute('G.SETTINGS.profile='+str(profile_value))
    lua.execute("io.open=function() error('UNEXPECTED_PROFILE_FILE_READ') end")
    result=snapshot()
    assert result['profile']==profile_value
    assert result['public']['regions'][0]['cards'][0]['description']==['Public effect']


def test_unsupported_mod_and_state(lua_reader):
    lua,snapshot=lua_reader
    lua.execute('G.STATE=997')  # 999 is the fixed Steamodded opened-pack state.
    assert public(snapshot)['phase']=='unsupported'
    lua.execute("SMODS.Mods.other={can_load=true}")
    assert snapshot()['compatibility']=='unsupported_mods' and snapshot().get('public') is None


@pytest.mark.parametrize('mutation',[
    "SMODS.Mods.other={id='other',can_load=true,meta_mod=true}",
    "SMODS.Mods.Lovely.meta_mod=false",
    "SMODS.Mods.Balatro.id='other'",
])
def test_only_exact_native_platform_metadata_is_allowed(lua_reader,mutation):
    lua,snapshot=lua_reader
    assert snapshot()['compatibility']=='supported'
    lua.execute(mutation)
    result=snapshot()
    assert result['compatibility']=='unsupported_mods' and result.get('public') is None


def test_native_ui_box_root_exports_actual_main_menu_button(lua_reader):
    lua,snapshot=lua_reader
    lua.execute("G.STATE=G.STATES.MENU; G.STAGE=G.STAGES.MAIN_MENU; G.MAIN_MENU_UI=ui_box({}, {ui({button='setup_run'}, {ui({text='PLAY'})})})")
    result=public(snapshot)
    assert result['phase']=='main_menu' and result['ready']
    action=next(action for action in result['ui_actions'] if action['name']=='open_run_setup')
    assert action['enabled'] and action['label']==['PLAY']


def native_click_fixture(lua):
    source_path=Path(__file__).resolve().parents[1]/'.artifacts/game-source/engine/ui.lua'
    if not source_path.exists():
        pytest.skip('Private fixed native source is not present in this checkout')
    source=source_path.read_text(encoding='utf-8')
    click=source[source.index('function UIElement:click()'):source.index('function UIElement:put_focused_cursor()')]
    lua.execute('UIElement={};'+click+"""
        G.STATE=G.STATES.SHOP; G.TIMERS={REAL=10}; G.ROOM.jiggle=0
        TEST_NATIVE_CLICKS=0
        G.FUNCS={reroll_shop=function() TEST_NATIVE_CLICKS=TEST_NATIVE_CLICKS+1 end}
        function play_sound() end
        TEST_CLICK_BUTTON=ui({button='reroll_shop',func='can_reroll'})
        G.shop=ui_box({}, {TEST_CLICK_BUTTON})
    """)


@pytest.mark.parametrize('mutation',[
    '', 'TEST_CLICK_BUTTON.disable_button=true',
    'TEST_CLICK_BUTTON.under_overlay=true',
    'TEST_CLICK_BUTTON.last_clicked=9.95',
    'TEST_CLICK_BUTTON.last_clicked=9.9',
    'TEST_CLICK_BUTTON.last_clicked=9.8',
    'TEST_CLICK_BUTTON.last_clicked=false',
    'TEST_CLICK_BUTTON.last_clicked=0; G.TIMERS.REAL=0.05',
    'TEST_CLICK_BUTTON.states.visible=false',
    'TEST_CLICK_BUTTON.states.visible=nil',
    'TEST_CLICK_BUTTON.config.button=false',
])
def test_button_enabled_matches_fixed_native_click_eligibility(lua_reader,mutation):
    lua,snapshot=lua_reader
    native_click_fixture(lua)
    lua.execute(mutation)
    result=public(snapshot)
    action=next((row for row in result['ui_actions'] if row['name']=='reroll'),None)
    reported=bool(action and action['enabled'])
    assert lua.eval('TEST_NATIVE_CLICKS')==0  # Reading cannot invoke a callback.
    lua.execute('UIElement.click(TEST_CLICK_BUTTON)')
    assert reported==(lua.eval('TEST_NATIVE_CLICKS')==1)


def native_room_container_fixture(lua, padding, position):
    native_click_fixture(lua)
    native = Path(__file__).resolve().parents[1]/'.artifacts/game-source/engine/node.lua'
    if not native.exists():
        pytest.skip('Private fixed native source is not present in this checkout')
    source = native.read_text(encoding='utf-8')
    translate = source[source.index('function Node:translate_container()'):source.index('--When this Node needs to be deleted')]
    cursor = source[source.index('function Node:put_focused_cursor()'):source.index('--Sets the container of this node')]
    lua.execute('Node={};'+translate+cursor+'''
        G.TILESCALE=1; G.TILESIZE=1
        TEST_TRANSLATION={x=0,y=0}
        love={graphics={
            translate=function(x,y) TEST_TRANSLATION.x=TEST_TRANSLATION.x+x; TEST_TRANSLATION.y=TEST_TRANSLATION.y+y end,
            rotate=function(r) assert(r==0) end
        }}
        TEST_CLICK_BUTTON.container=G.ROOM
    ''')
    lua.execute(f'G.ROOM.T={{x={padding[0]},y={padding[1]},w=20,h=20,r=0}}; '
                f'TEST_CLICK_BUTTON.T={{x={position[0]},y={position[1]},w=1,h=0.6}}; '
                'TEST_CLICK_BUTTON.VT=TEST_CLICK_BUTTON.T; Node.translate_container(TEST_CLICK_BUTTON)')
    assert (lua.eval('TEST_TRANSLATION.x'), lua.eval('TEST_TRANSLATION.y')) == padding
    cursor_position = lua.eval('function() return Node.put_focused_cursor(TEST_CLICK_BUTTON) end')()
    assert cursor_position == pytest.approx((padding[0]+position[0]+0.5, padding[1]+position[1]+0.3))


@pytest.mark.parametrize('padding', [(0,5), (5,0), (5,5)])
def test_room_container_padding_keeps_visible_native_button_enabled(lua_reader, padding):
    lua,snapshot=lua_reader
    native_room_container_fixture(lua, padding, (0.25,0.25))
    result=public(snapshot)
    assert next(row for row in result['ui_actions'] if row['name']=='reroll')['enabled']
    assert lua.eval('TEST_NATIVE_CLICKS')==0
    lua.execute('UIElement.click(TEST_CLICK_BUTTON)')
    assert lua.eval('TEST_NATIVE_CLICKS')==1


@pytest.mark.parametrize('position', [(21,6), (6,21)])
def test_room_container_padding_never_exposes_offscreen_click(lua_reader, position):
    lua,snapshot=lua_reader
    native_room_container_fixture(lua, (5,5), position)
    result=public(snapshot)
    assert not next(row for row in result['ui_actions'] if row['name']=='reroll')['enabled']
    assert lua.eval('TEST_NATIVE_CLICKS')==0


def test_unknown_container_keeps_existing_visibility_bounds(lua_reader):
    lua,snapshot=lua_reader
    native_room_container_fixture(lua, (5,5), (0.25,0.25))
    lua.execute('TEST_CLICK_BUTTON.container=nil')
    assert not next(row for row in public(snapshot)['ui_actions'] if row['name']=='reroll')['enabled']


def test_native_one_press_disables_button_without_clearing_callback(lua_reader):
    lua,snapshot=lua_reader
    native_click_fixture(lua)
    lua.execute('TEST_CLICK_BUTTON.config.one_press=true')
    assert next(row for row in public(snapshot)['ui_actions'] if row['name']=='reroll')['enabled']
    lua.execute('UIElement.click(TEST_CLICK_BUTTON); G.TIMERS.REAL=11')
    assert lua.eval('TEST_CLICK_BUTTON.config.button')=='reroll_shop'
    assert lua.eval('TEST_CLICK_BUTTON.disable_button') is True
    result=public(snapshot)
    assert result['phase']=='shop' and result['ready']
    assert not next(row for row in result['ui_actions'] if row['name']=='reroll')['enabled']
    assert lua.eval('TEST_NATIVE_CLICKS')==1
    lua.execute('UIElement.click(TEST_CLICK_BUTTON)')
    assert lua.eval('TEST_NATIVE_CLICKS')==1


@pytest.mark.parametrize('mutation',[
    'G.TIMERS=nil', 'G.TIMERS.REAL=0/0', "TEST_CLICK_BUTTON.last_clicked='unknown'",
])
def test_unknown_native_click_timing_does_not_claim_button_enabled(lua_reader,mutation):
    lua,snapshot=lua_reader
    native_click_fixture(lua)
    lua.execute('TEST_CLICK_BUTTON.last_clicked=9.8;'+mutation)
    result=public(snapshot)
    assert not next(row for row in result['ui_actions'] if row['name']=='reroll')['enabled']
    assert lua.eval('TEST_NATIVE_CLICKS')==0


@pytest.mark.parametrize('location,highlighted',[
    ('shop',False),('shop',True),('held',False),('held',True),
])
def test_card_controls_match_fixed_native_draw_conditions(lua_reader,location,highlighted):
    lua,snapshot=lua_reader
    source_path=Path(__file__).resolve().parents[1]/'.artifacts/game-source/card.lua'
    if not source_path.exists():
        pytest.skip('Private fixed native source is not present in this checkout')
    source=source_path.read_text(encoding='utf-8')
    draw=source[source.index('function Card:draw(layer)'):]
    controls=draw[draw.index('if self.children.price then self.children.price:draw() end'):draw.index('if self.vortex then')]
    lua.execute("""
        G.STATE=G.STATES.SHOP; G.shop=ui_box(); G.shop_jokers=area({},2)
        TEST_CARD=card('Public planet'); TEST_CARD.ability.set='Planet'
        TEST_RENDERED={}
        function control(button,func,name)
            local box=ui_box({}, {ui({button=button,func=func,ref_table=TEST_CARD})})
            function box:draw() TEST_RENDERED[name]=true end
            return box
        end
        TEST_CARD.children.buy_button=control('buy_from_shop','can_buy','buy')
        TEST_CARD.children.buy_and_use_button=control('buy_from_shop','can_buy_and_use','buy_and_use')
        TEST_CARD.children.use_button=control('use_card','can_use_consumeable','use')
    """)
    lua.execute('TEST_CARD.highlighted='+str(highlighted).lower())
    region='shop_jokers' if location=='shop' else 'consumables'
    if location=='shop':
        lua.execute('TEST_CARD.area=G.shop_jokers; G.shop_jokers.cards={TEST_CARD}')
    else:
        # The native purchase callback removes buy_button, retaining the sibling.
        lua.execute('TEST_CARD.area=G.consumeables; G.consumeables.cards={TEST_CARD}; TEST_CARD.children.buy_button=nil')
    result=public(snapshot)
    reported={row['name'] for row in result['ui_actions'] if row['region']==region}
    assert not list(lua.globals().TEST_RENDERED.keys())  # Observe cannot draw/change UI.
    lua.execute('local self=TEST_CARD;'+controls)
    assert reported==set(lua.globals().TEST_RENDERED.keys())


def test_native_ui_box_deck_menu_uses_only_displayed_card_copies(lua_reader):
    lua,snapshot=lua_reader
    lua.execute("local a=area({card('Shown Ace'),card('Shown Ace')}); a.config.view_deck=true; G.OVERLAY_MENU=ui_box({}, {ui({object=a})}); G.OVERLAY_MENU.config={object=G.deck}")
    result=public(snapshot)
    assert result['menus']['deck_scope']=='displayed_menu'
    assert result['menus']['deck_composition'][0]['count']==2
    assert 'HIDDEN' not in canonical(result)


def test_native_ui_box_settlement_text_has_only_current_dynamic_string(lua_reader):
    lua,snapshot=lua_reader
    lua.execute("G.STATE=G.STATES.ROUND_EVAL; G.round_eval=ui_box({}, {ui({id='cash_out_button',button='cash_out'}, {ui({text='$4'})}),ui({object={focused_string=1,strings={{string='$3'},{string='SECRET_FUTURE'}}}})})")
    result=public(snapshot)
    assert result['phase']=='round_eval' and result['ready']
    assert result['settlement_text']==['$4','$3']
    assert 'SECRET' not in canonical(result)


NATIVE_SETTLEMENT_ATTACHED_UI = """
G.STATE=G.STATES.ROUND_EVAL
G.round_eval=ui_box({}, {ui({text='Blind reward $3'}),ui({text='Remaining hands $2'})})
TEST_CASH_BUTTON=ui({id='cash_out_button',button='cash_out'}, {ui({text='Cash Out: '}),ui({text='$5'})})
TEST_CASH_BOX=ui_box({}, {TEST_CASH_BUTTON})
TEST_CASH_BOX.role={role_type='Minor',major=G.round_eval}
TEST_CASH_BOX.alignment={type='tmi',offset={x=0,y=0.4}}
G.I={UIBOX={G.round_eval,TEST_CASH_BOX}}
G.FUNCS={cash_out=function() error('ACTION_CALLED') end}
"""


@pytest.mark.parametrize('mutation',[
    'TEST_CASH_BUTTON.disable_button=true',
    'TEST_CASH_BUTTON.under_overlay=true',
    'G.TIMERS={REAL=10}; TEST_CASH_BUTTON.last_clicked=9.95',
])
def test_settlement_requires_native_clickable_cash_button(lua_reader,mutation):
    lua,snapshot=lua_reader
    lua.execute(NATIVE_SETTLEMENT_ATTACHED_UI+mutation)
    result=public(snapshot)
    assert result['phase']=='transition' and not result['ready']
    assert not any(row['enabled'] for row in result['ui_actions'] if row['name']=='cash_out')


def test_terminal_requires_native_clickable_navigation_button(lua_reader):
    lua,snapshot=lua_reader
    terminal_ui(lua)
    lua.execute('for _,node in ipairs(G.OVERLAY_MENU.UIRoot.children) do node.disable_button=true end')
    result=public(snapshot)
    assert not result['ready'] and result['outcome'] is None
    assert not any(row['enabled'] for row in result['ui_actions'])


def test_native_cash_out_in_separate_registered_attached_ui_box(lua_reader):
    lua,snapshot=lua_reader
    lua.execute(NATIVE_SETTLEMENT_ATTACHED_UI)
    assert lua.eval("G.round_eval:get_UIE_by_ID('cash_out_button')") is None
    result=public(snapshot)
    assert result['phase']=='round_eval' and result['ready']
    assert result['settlement_text']==['Blind reward $3','Remaining hands $2','Cash Out: ','$5']
    assert next(row for row in result['ui_actions'] if row['name']=='cash_out')['enabled']
    lua.execute("local other=ui_box({}, {ui({id='cash_out_button',button='cash_out'},{ui({text='SECRET_OTHER_UI'})})}); other.role={role_type='Minor',major=ui_box()}; other.alignment={major=G.round_eval}; G.I.UIBOX[#G.I.UIBOX+1]=other; G.GAME.seed='SECRET_CHANGED_SEED'; G.deck.cards={card('SECRET_CHANGED_DECK')}")
    assert result==public(snapshot)


def test_cash_out_attachment_runs_fixed_native_moveable_alignment(lua_reader):
    lua,snapshot=lua_reader
    source_path=Path(__file__).resolve().parents[1]/'.artifacts/game-source/engine/moveable.lua'
    if not source_path.exists():
        pytest.skip('Private fixed native source is not present in this checkout')
    source=source_path.read_text(encoding='utf-8')
    alignment=source[source.index('function Moveable:set_alignment(args)'):source.index('function Moveable:align_to_major()')]
    role=source[source.index('function Moveable:set_role(args)'):source.index('function Moveable:get_major()')]
    lua.execute('Moveable={};'+role+alignment)
    lua.execute(NATIVE_SETTLEMENT_ATTACHED_UI+"""
TEST_CASH_BOX.role={role_type='Major',offset={x=0,y=0}}
TEST_CASH_BOX.alignment={type='',offset={x=0,y=0}}
TEST_CASH_BOX.set_role=Moveable.set_role
G.round_eval.set_role=Moveable.set_role
Moveable.set_alignment(TEST_CASH_BOX,{major=G.round_eval,type='tmi',offset={x=0,y=0.4}})
""")
    assert lua.eval('TEST_CASH_BOX.role.major==G.round_eval') is True
    assert lua.eval('TEST_CASH_BOX.role.role_type')=='Minor'
    assert lua.eval('TEST_CASH_BOX.alignment.major') is None
    result=public(snapshot)
    assert result['phase']=='round_eval' and result['ready']
    assert result['settlement_text']==['Blind reward $3','Remaining hands $2','Cash Out: ','$5']
    assert next(row for row in result['ui_actions'] if row['name']=='cash_out')['enabled']
    assert lua.eval('TEST_CASH_BOX.role.major==G.round_eval') is True


def test_stale_alignment_or_config_reference_cannot_attach_cash_out(lua_reader):
    lua,snapshot=lua_reader
    lua.execute(NATIVE_SETTLEMENT_ATTACHED_UI+"""
TEST_CASH_BOX.role.major=ui_box()
TEST_CASH_BOX.alignment.major=G.round_eval
TEST_CASH_BOX.config={major=G.round_eval}
""")
    result=public(snapshot)
    assert result['phase']=='transition' and not result['ready']
    assert 'Cash Out: ' not in result['settlement_text'] and '$5' not in result['settlement_text']
    assert not any(row['name']=='cash_out' for row in result['ui_actions'])
    lua.execute("TEST_CASH_BOX.UIRoot.children[#TEST_CASH_BOX.UIRoot.children+1]=ui({text='SECRET_UNRELATED_UI'})")
    assert result==public(snapshot)


@pytest.mark.parametrize('mutation',[
    'TEST_CASH_BOX.role.major=ui_box()',
    'TEST_CASH_BOX.role=nil',
    "TEST_CASH_BOX.role.role_type='Major'",
    'TEST_CASH_BOX.role.major=TEST_CASH_BOX',
    'TEST_CASH_BOX.states.visible=false',
    'TEST_CASH_BOX.removed=true',
    'TEST_CASH_BOX.VT={x=50,y=50,w=1,h=1}',
    'TEST_CASH_BUTTON.states.visible=false',
    'TEST_CASH_BUTTON.config.button=nil',
    'G.I.UIBOX={G.round_eval}',
    'G.GAME.STOP_USE=1',
    'G.CONTROLLER.locks.use=true',
])
def test_cash_out_visibility_attachment_and_native_locks_gate_readiness(lua_reader,mutation):
    lua,snapshot=lua_reader
    lua.execute(NATIVE_SETTLEMENT_ATTACHED_UI+';'+mutation)
    result=public(snapshot)
    assert result['phase']=='transition' and not result['ready']
    assert result['regions']==[]
    assert not any(row['enabled'] for row in result['ui_actions'])
    assert 'SECRET' not in canonical(result)


def test_live_settlement_text_retains_screen_clipping(lua_reader):
    lua,snapshot=lua_reader
    lua.execute(NATIVE_SETTLEMENT_ATTACHED_UI+"; TEST_CASH_BOX.UIRoot.children[#TEST_CASH_BOX.UIRoot.children+1]=ui({object={focused_string=1,strings={{string='SECRET_OFFSCREEN_TEXT'}},VT={x=50,y=50,w=1,h=1}}})")
    result=public(snapshot)
    assert result['ready'] and 'SECRET' not in canonical(result)


RUN_SETUP_NESTED_UI = """
G.STATE=G.STATES.MENU; G.STAGE=G.STAGES.MAIN_MENU
G.GAME.viewed_back={effect={center={key='b_red'}}}; G.viewed_stake=1
local nested=ui_box({}, {ui({button='start_setup_run',func='can_start_run'}, {ui({text='PLAY'})})})
local tab=ui({id='tab_contents',object=nested}); tab.UIT=G.UIT.O
G.OVERLAY_MENU=ui_box({}, {tab,ui({button='exit_overlay_menu'},{ui({text='BACK'})})})
TEST_TAB=tab; TEST_NESTED_UI=nested
"""


def test_native_rendered_tab_ui_box_exports_run_setup(lua_reader):
    lua,snapshot=lua_reader
    lua.execute(RUN_SETUP_NESTED_UI)
    result=public(snapshot)
    assert result['phase']=='main_menu' and result['ready']
    assert result['resources']['availability']=='not_applicable'
    assert result['setup']=={'availability':'observed','deck_name':'Visible b_red','stake_name':'Visible stake_white','page':None,'options':[]}
    start=next(action for action in result['ui_actions'] if action['name']=='start_run')
    assert start['enabled'] and start['label']==['PLAY']
    lua.execute("TEST_NESTED_UI.definition=ui({}, {ui({button='start_setup_run'},{ui({text='SECRET_UNDISPLAYED'})})}); TEST_TAB.config.ref_table=G.deck")
    assert result==public(snapshot)


@pytest.mark.parametrize('definition', ['run_setup_option', 'run_select_galdur'])
def test_continue_menu_exposes_only_rendered_native_new_run_tab(lua_reader, definition):
    lua, snapshot = lua_reader
    lua.execute(RUN_SETUP_NESTED_UI)
    lua.globals().TEST_DEFINITION = definition
    lua.execute('''
      G.SETTINGS.current_setup='Continue'; G.UIDEF={}
      TEST_DEFINITION_CALLS=0
      G.UIDEF[TEST_DEFINITION]=function() TEST_DEFINITION_CALLS=TEST_DEFINITION_CALLS+1 end
      TEST_NEW=ui({button='change_tab',ref_table={tab_definition_function=G.UIDEF[TEST_DEFINITION],
        tab_definition_function_args='New Run'}},{ui({text='New Run'})})
      local challenge=ui({button='change_tab',ref_table={tab_definition_function=function() end,
        tab_definition_function_args='New Run'}},{ui({text='Challenges'})})
      table.insert(G.OVERLAY_MENU.UIRoot.children,1,TEST_NEW)
      table.insert(G.OVERLAY_MENU.UIRoot.children,2,challenge)
    ''')
    result = public(snapshot)
    tabs = [a for a in result['ui_actions'] if a['name'] == 'next_setup_page']
    assert len(tabs) == 1 and tabs[0]['label'] == ['New Run'] and tabs[0]['enabled']
    assert lua.eval('TEST_DEFINITION_CALLS') == 0
    lua.execute('TEST_NEW.states.visible=false')
    assert not any(a['name'] == 'next_setup_page' for a in public(snapshot)['ui_actions'])
    lua.execute("TEST_NEW.states.visible=true; G.SETTINGS.current_setup='New Run'")
    assert not any(a['name'] == 'next_setup_page' for a in public(snapshot)['ui_actions'])


@pytest.mark.parametrize('mutation',[
    'TEST_TAB.states.visible=false',
    'TEST_NESTED_UI.states.visible=false',
    'TEST_NESTED_UI.removed=true',
    'TEST_TAB.UIT=999',
    'setmetatable(TEST_NESTED_UI,nil)',
])
def test_run_setup_does_not_follow_hidden_or_unrendered_objects(lua_reader,mutation):
    lua,snapshot=lua_reader
    lua.execute(RUN_SETUP_NESTED_UI+';'+mutation)
    result=public(snapshot)
    assert result['setup']['availability']=='not_applicable'
    assert all(action['name']!='start_run' for action in result['ui_actions'])


SMODS_RUN_SELECT_UI = """
G.STATE=G.STATES.MENU; G.STAGE=G.STAGES.MAIN_MENU
G.GAME.viewed_back={effect={center={key='SECRET_STALE_NATIVE_DECK'}}}; G.viewed_stake=8
G.P_STAKES.stake_white={key='stake_white'}; G.P_STAKES.stake_red={key='stake_red'}
SMODS.RunSelect={Internals={current_page=1,pages={'deck_choice','stake_choice'}},Setup={choices={deck_choice='SECRET_DEFAULT',stake_choice='SECRET_DEFAULT',seed='SECRET_SEED'}}}
local preview1=ui({id='preview_text_1',object={focused_string=1,strings={{string='Red'},{string='SECRET_ALTERNATIVE'}}}})
local preview2=ui({id='preview_text_2',object={focused_string=1,strings={{string='Deck'}}}})
local tower=area({{states={visible=true},params={run_select_stake_tower={1,'stake_white'}}}})
tower.config.run_select_stake_tower=true
local tower_node=ui({object=tower}); tower_node.UIT=G.UIT.O
local page=ui_box({}, {preview1,preview2,tower_node})
local selector=ui({id='run_select',object=page}); selector.UIT=G.UIT.O
local next_button=ui({id='next_selection',ref_value=1,func='run_select_can_change_page',button='run_select_change_page'}, {ui({object={focused_string=1,strings={{string='Stake >'}}}})})
local quick=ui({button='run_select_quick_start'}, {ui({text='Quick Start'})})
local tab=ui({id='tab_contents',object=ui_box({}, {selector,next_button,quick})}); tab.UIT=G.UIT.O
G.OVERLAY_MENU=ui_box({}, {tab,ui({button='exit_overlay_menu'},{ui({text='BACK'})})})
TEST_SELECTOR=selector; TEST_NEXT=next_button; TEST_TOWER=tower; TEST_PAGE=page
"""


def test_fixed_smods_run_selector_reads_visible_names_and_callbacks(lua_reader):
    lua,snapshot=lua_reader
    lua.execute(SMODS_RUN_SELECT_UI)
    result=public(snapshot)
    assert result['setup']=={'availability':'observed','deck_name':'Red Deck','stake_name':'Visible stake_white','page':'deck_choice','options':[]}
    assert [(a['name'],a['label']) for a in result['ui_actions']]==[
        ('next_setup_page',['Stake >']),('quick_start_run',['Quick Start']),('close_menu',['BACK'])]
    assert 'SECRET' not in canonical(result)
    lua.execute("SMODS.RunSelect.Setup.choices={deck_choice='SECRET_CHANGED',stake_choice='SECRET_CHANGED',seed='SECRET_CHANGED'}; G.GAME.viewed_back.effect.center.key='OTHER_SECRET'; G.viewed_stake=7; SMODS.RunSelect.Internals.holding_area=area({card('SECRET_NEXT_PAGE')})")
    assert result==public(snapshot)


@pytest.mark.parametrize('button,label,expected,enabled',[
    ('run_select_change_page','Stake >','next_setup_page',True),
    ('run_select_start_run','run_select_play','start_run',True),
    (None,'run_select_play','start_run',False),
    (None,'Stake >','next_setup_page',False),
])
def test_run_selector_navigation_does_not_mislabel_play(lua_reader,button,label,expected,enabled):
    lua,snapshot=lua_reader
    lua.execute(SMODS_RUN_SELECT_UI)
    lua.globals().TEST_BUTTON=button
    lua.globals().TEST_LABEL=label
    lua.execute("TEST_NEXT.config.button=TEST_BUTTON; TEST_NEXT.children[1].config.object.strings[1].string=TEST_LABEL")
    action=public(snapshot)['ui_actions'][0]
    assert action['name']==expected and action['enabled'] is enabled


def test_run_selector_stake_page_uses_visible_deck_preview_not_stake_label(lua_reader):
    lua,snapshot=lua_reader
    lua.execute(SMODS_RUN_SELECT_UI)
    lua.execute("SMODS.RunSelect.Internals.current_page=2; TEST_PAGE.UIRoot.children[1].config.object.strings[1].string='White'; TEST_PAGE.UIRoot.children[2].config.object.strings[1].string='Stake'; table.insert(TEST_PAGE.UIRoot.children,ui({id='deck_preview_text_1',object={focused_string=1,strings={{string='Red Deck'}}}})); table.insert(TEST_TOWER.cards,1,{states={visible=true},params={run_select_stake_tower={2,'stake_red'}}})")
    setup=public(snapshot)['setup']
    assert setup['deck_name']=='Red Deck' and setup['stake_name']=='Visible stake_red'


def test_run_selector_previous_page_and_lock_follow_visible_ui(lua_reader):
    lua,snapshot=lua_reader
    lua.execute(SMODS_RUN_SELECT_UI)
    lua.execute("TEST_NEXT.config.id='previous_selection'; TEST_NEXT.config.ref_value=-1; TEST_NEXT.children[1].config.object.strings[1].string='< Deck'")
    assert public(snapshot)['ui_actions'][0]['name']=='previous_setup_page'
    lua.execute('G.CONTROLLER.locked=true')
    result=public(snapshot)
    assert not result['ready'] and all(not action['enabled'] for action in result['ui_actions'])


def test_run_selector_hidden_chips_and_missing_names_stay_unknown(lua_reader):
    lua,snapshot=lua_reader
    lua.execute(SMODS_RUN_SELECT_UI)
    lua.execute("TEST_TOWER.cards[1].states.visible=false; TEST_PAGE.UIRoot.children[1].states.visible=false; TEST_PAGE.UIRoot.children[2].states.visible=false")
    result=public(snapshot)
    assert result['setup']=={'availability':'unknown','deck_name':None,'stake_name':None,'page':'deck_choice','options':[]}
    assert 'unconfirmed_field' in result['unknowns']
    assert 'SECRET' not in canonical(result)


def test_native_rendered_draw_layer_is_read_without_stored_definition(lua_reader):
    lua,snapshot=lua_reader
    lua.execute("G.STATE=G.STATES.MENU; G.STAGE=G.STAGES.MAIN_MENU; local layer=ui({button='setup_run'},{ui({text='PLAY'})}); G.MAIN_MENU_UI=ui_box(); G.MAIN_MENU_UI.draw_layers={layer}; G.MAIN_MENU_UI.definition=ui({button='setup_run'},{ui({text='SECRET_UNDISPLAYED'})})")
    result=public(snapshot)
    assert result['ui_actions'][0]['label']==['PLAY']
    assert 'SECRET' not in canonical(result)


DECK_PREVIEW_HOVER_UI = """
SMODS.RunSelect.Internals.current_page=2
TEST_PAGE.UIRoot.children[1].states.visible=false
TEST_PAGE.UIRoot.children[2].states.visible=false
local preview=card('SECRET_PLAYING_CARD_NAME')
preview.facing='back'; preview.sprite_facing='back'
preview.params={run_select_preview_card='deck_choice'}
preview.config.center={set='Back',key='b_red',unlocked=true,discovered=true}
local a=area({preview}); a.config.run_select_deck_preview=true
local node=ui({object=a}); node.UIT=G.UIT.O
table.insert(TEST_PAGE.UIRoot.children,node)
TEST_DECK_PREVIEW=preview; TEST_DECK_AREA=a; TEST_DECK_NODE=node
"""


def test_selected_deck_preview_back_has_public_hover_name_not_card_identity(lua_reader):
    lua,snapshot=lua_reader
    lua.execute(SMODS_RUN_SELECT_UI+DECK_PREVIEW_HOVER_UI)
    before=public(snapshot)
    assert before['setup']['deck_name']=='Visible b_red'
    assert 'SECRET' not in canonical(before)
    lua.execute("TEST_DECK_PREVIEW.base={value='King',suit='Clubs'}; TEST_DECK_PREVIEW.sort_id='OTHER_SECRET'; TEST_DECK_PREVIEW.playing_card='OTHER_SECRET'; SMODS.RunSelect.Setup.choices.deck_choice='SECRET_FUTURE'; SMODS.RunSelect.Internals.preview_area_holding=area({card('SECRET_OFFSCREEN')})")
    assert before==public(snapshot)


@pytest.mark.parametrize('mutation',[
    'TEST_DECK_PREVIEW.states.visible=false',
    'TEST_DECK_AREA.states.visible=false',
    'TEST_DECK_NODE.UIT=999',
    "TEST_DECK_PREVIEW.params={run_select_selection_choice='deck_choice'}",
    "TEST_DECK_PREVIEW.config.center.set='Default'",
    'TEST_DECK_PREVIEW.config.center.unlocked=false',
    'TEST_DECK_PREVIEW.config.center.discovered=false',
])
def test_deck_hover_fallback_never_queries_candidates_hidden_or_playing_cards(lua_reader,mutation):
    lua,snapshot=lua_reader
    lua.execute(SMODS_RUN_SELECT_UI+DECK_PREVIEW_HOVER_UI+';'+mutation)
    result=public(snapshot)
    assert result['setup']['deck_name'] is None
    assert 'unconfirmed_field' in result['unknowns']
    assert 'SECRET' not in canonical(result)


NATIVE_SKIP_TAG_UI = """
G.STATE=G.STATES.BLIND_SELECT; G.GAME.hands_played=2
G.P_BLINDS.bl_small={mult=1,dollars=3}; G.P_BLINDS.bl_big={mult=1.5,dollars=4}
G.GAME.round_resets.blind_choices={Small='bl_small',Big='bl_big'}
G.GAME.round_resets.blind_states={Small='Select',Big='Upcoming'}
G.GAME.round_resets.blind_tags={Small='tag_handy',Big='tag_double'}
G.P_TAGS.tag_handy={}; G.P_TAGS.tag_double={}
Tag={}; Tag.__index=Tag; TEST_TAG_CALLS=0
function Tag.get_uibox_table(self,sprite,vars_only)
  assert(vars_only==true,'must query public tooltip variables only')
  TEST_TAG_CALLS=TEST_TAG_CALLS+1
  self.config.ui_write=true; self.ability.ui_write=true
  if self.name=='Handy Tag' then return {self.config.dollars_per_hand,self.config.dollars_per_hand*G.GAME.hands_played} end
  return {}
end
local old_localize=localize
function localize(args,kind)
  if type(args)=='table' and args.type=='raw_descriptions' and args.set=='Tag' then
    if args.key=='tag_handy' then return {'Visible payout $'..args.vars[2]} end
    return {'Visible next-tag copy','Visible exclusion'}
  end
  return old_localize(args,kind)
end
local handy=setmetatable({key='tag_handy',name='Handy Tag',config={dollars_per_hand=1},ability={},tag_sprite={private='SECRET_SPRITE'}},Tag)
local double=setmetatable({key='tag_double',name='Double Tag',config={},ability={}},Tag)
local handy_container=ui({id='tag_container',ref_table=handy},{ui({id='tag_desc'},{ui({object={private='SECRET_SPRITE'}})})})
local double_container=ui({id='tag_container',ref_table=double},{ui({id='tag_desc'})})
G.blind_select=ui_box({}, {ui({id='Small'},{handy_container}),ui({id='Big'},{double_container})})
TEST_TAG=handy; TEST_TAG_CONTAINER=handy_container
"""


def test_skip_tag_native_binding_and_public_dynamic_vars_are_read_without_writes(lua_reader):
    lua,snapshot=lua_reader
    lua.execute(NATIVE_SKIP_TAG_UI)
    result=public(snapshot)
    assert result['blinds'][0]['skip_tag_description']==['Visible payout $2']
    assert result['blinds'][1]['skip_tag_description']==['Visible next-tag copy','Visible exclusion']
    assert lua.eval('TEST_TAG.config.ui_write') is None
    assert lua.eval('TEST_TAG.ability.ui_write') is None
    assert 'SECRET' not in canonical(result)
    lua.execute('G.GAME.hands_played=5')
    assert public(snapshot)['blinds'][0]['skip_tag_description']==['Visible payout $5']


def test_skip_tag_hidden_mutations_do_not_change_public_output(lua_reader):
    lua,snapshot=lua_reader
    lua.execute(NATIVE_SKIP_TAG_UI)
    before=public(snapshot)
    lua.execute("G.GAME.seed='OTHER_SECRET'; G.GAME.pseudorandom={state='OTHER_SECRET'}; G.deck.cards={card('SECRET_FUTURE')}; TEST_TAG.ability.internal_future='SECRET_FUTURE'; TEST_TAG.tag_sprite.private='OTHER_SECRET'")
    assert before==public(snapshot)


@pytest.mark.parametrize('mutation',[
    'TEST_TAG.hide_ability=true',
    'TEST_TAG_CONTAINER.states.visible=false',
    'setmetatable(TEST_TAG,{})',
])
def test_unavailable_or_hidden_skip_tag_does_not_export_identity(lua_reader,mutation):
    lua,snapshot=lua_reader
    lua.execute(NATIVE_SKIP_TAG_UI+';'+mutation)
    result=public(snapshot)
    tag=result['blinds'][0]
    assert tag['skip_tag_name'] is None and tag['skip_tag_description']==[]
    assert 'tooltip_unavailable' in result['unknowns']
    assert lua.eval('TEST_TAG_CALLS')==1  # Only the visible Big tag was queried.


@pytest.mark.parametrize('failure',[
    "Tag.get_uibox_table=function() error('SECRET_NATIVE_ERROR') end",
    "Tag.get_uibox_table=function() return nil end",
    "local old=localize; localize=function(args,kind) if type(args)=='table' and args.type=='raw_descriptions' and args.set=='Tag' then return {'Unresolved ERROR'} end; return old(args,kind) end",
])
def test_skip_tag_failures_are_explicit_and_never_return_raw_errors(lua_reader,failure):
    lua,snapshot=lua_reader
    lua.execute(NATIVE_SKIP_TAG_UI+';'+failure)
    result=public(snapshot)
    assert result['blinds'][0]['skip_tag_description']==[]
    assert 'tooltip_unavailable' in result['unknowns']
    assert 'SECRET' not in canonical(result) and 'Unresolved ERROR' not in canonical(result)


TOOLTIP_UI = (Path(__file__).parent / 'support/tooltip_fixture.lua').read_text(encoding='utf-8')
TOOLTIP_SCENES = {
    'jokers': 'G.jokers.cards={TEST_CARD}; TEST_CARD.area=G.jokers',
    'shop_jokers': 'G.STATE=G.STATES.SHOP; G.shop=ui_box(); G.shop_jokers=area({TEST_CARD}); TEST_CARD.area=G.shop_jokers',
    'pack': 'G.STATE=G.STATES.BUFFOON_PACK; G.booster_pack=ui_box(); G.pack_cards=area({TEST_CARD}); G.GAME.pack_choices=1; TEST_CARD.area=G.pack_cards',
}


def tooltip_card(result, region='jokers'):
    return next(row for row in result['regions'] if row['name']==region)['cards'][0]


@pytest.mark.parametrize('region', TOOLTIP_SCENES)
def test_uncollected_public_joker_tooltip_numbers_and_extra_info(lua_reader,region):
    lua,snapshot=lua_reader
    lua.execute(TOOLTIP_UI+TOOLTIP_SCENES[region])
    result=public(snapshot)
    item=tooltip_card(result,region)
    assert item['visibility']=='face_up'
    assert item['name']=='Synthetic growth joker'
    assert item['description']==['Current Mult +8','Public tally 2']
    assert item['tooltip_info']==['Visible edition','Extra Joker slot +1','Visible sticker','Public remaining rounds 3']
    assert 'tooltip_unavailable' not in result['unknowns']
    assert lua.eval('TEST_CARD.ability.tooltip_ui_flag') is None
    assert lua.eval('TEST_CARD.ability.extra.tooltip_ui_flag') is None
    assert lua.eval('TEST_TOOLTIP_REMOVED')==6  # All temporary animated text removed.
    lua.execute('TEST_CARD.ability.mult=11; TEST_CARD.ability.extra.visible_tally=4')
    updated=public(snapshot)
    assert tooltip_card(updated,region)['description']==['Current Mult +11','Public tally 4']
    assert observation_id(result)!=observation_id(updated)


@pytest.mark.parametrize('region',[
    'jokers','shop_jokers','pack','shop_vouchers','shop_boosters',
])
def test_copied_legal_tooltip_text_precedes_popup_positioning(lua_reader,region):
    lua,snapshot=lua_reader
    scene=TOOLTIP_SCENES.get(region)
    if scene is None:
        native_area='shop_vouchers' if region=='shop_vouchers' else 'shop_booster'
        card_set='Voucher' if region=='shop_vouchers' else 'Booster'
        scene="G.STATE=G.STATES.SHOP; G.shop=ui_box(); G."+native_area+"=area({TEST_CARD}); TEST_CARD.area=G."+native_area+"; TEST_CARD.ability.set='"+card_set+"'"
    lua.execute(TOOLTIP_UI+scene+"; G.ROOM.T={x=5,y=5,w=20,h=20}; local original=tooltip_word; tooltip_word=function(value,static) local node=original(value,static); node.config.object.VT={x=0,y=0,w=1,h=0.4}; return node end")
    result=public(snapshot)
    item=tooltip_card(result,region)
    assert item['name']=='Synthetic growth joker'
    assert item['description']==['Current Mult +8','Public tally 2']
    assert item['tooltip_info']==['Visible edition','Extra Joker slot +1','Visible sticker','Public remaining rounds 3']
    assert 'tooltip_unavailable' not in result['unknowns']
    assert 'SECRET' not in canonical(result)
    assert lua.eval('TEST_TOOLTIP_REMOVED')==6
    assert lua.eval('TEST_CARD.ability.tooltip_ui_flag') is None


@pytest.mark.parametrize('visibility',['node.config.object.states.visible=false','node.config.object.removed=true'])
def test_generated_tooltip_title_still_excludes_hidden_or_removed_objects(lua_reader,visibility):
    lua,snapshot=lua_reader
    lua.execute(TOOLTIP_UI+TOOLTIP_SCENES['shop_jokers']+"; local original=tooltip_word; tooltip_word=function(value,static) local node=original(value,static); if value=='Synthetic growth joker' then "+visibility+" end; return node end")
    result=public(snapshot)
    assert tooltip_card(result,'shop_jokers')['name'] is None
    assert 'tooltip_unavailable' in result['unknowns']
    assert 'SECRET_FALLBACK' not in canonical(result)


def test_public_tooltip_never_enumerates_hidden_alternatives_or_calls_callbacks(lua_reader):
    lua,snapshot=lua_reader
    lua.execute(TOOLTIP_UI+TOOLTIP_SCENES['jokers'])
    before=public(snapshot)
    lua.execute("G.deck.cards={card('SECRET_CHANGED_DECK')}; G.GAME.pseudorandom={state='SECRET_RNG'}; G.GAME.seed='SECRET_CHANGED_SEED'; TEST_CARD.sort_id='SECRET_CHANGED_ID'; G.FUNCS={blueprint_compat=function() error('SECRET_CALLBACK') end}; local old=tooltip_word; tooltip_word=function(value,static) local node=old(value,static); node.config.object.strings[2].string='SECRET_CHANGED_ALTERNATIVE'; node.config.object.config.string={'SECRET_CHANGED_STORED'}; return node end")
    assert public(snapshot)==before
    assert 'SECRET' not in canonical(before)


@pytest.mark.parametrize('name,state,expected',[
    ('Blueprint','compatible',' k_compatible '),
    ('Brainstorm','incompatible',' k_incompatible '),
    ('Blueprint',None,None),
])
def test_copy_joker_current_native_compatibility_label_without_game_writes(lua_reader,name,state,expected):
    lua,snapshot=lua_reader
    lua.execute(TOOLTIP_UI+TOOLTIP_SCENES['jokers'])
    lua.globals().TEST_COMPAT=state
    lua.globals().TEST_JOKER_NAME=name
    lua.execute("TEST_CARD.ability.name=TEST_JOKER_NAME; TEST_CARD.ability.blueprint_compat=TEST_COMPAT; TEST_CARD.ability.blueprint_compat_ui='SECRET_STALE_UI'; TEST_CARD.ability.blueprint_compat_check='ORIGINAL_CHECK'; G.FUNCS={blueprint_compat=function() error('SECRET_CALLBACK') end}")
    result=public(snapshot)
    item=tooltip_card(result)
    if expected:
        assert item['description'][-1]==expected
        assert 'tooltip_unavailable' not in result['unknowns']
    else:
        assert item['description']==['Current Mult +8','Public tally 2']
        assert 'tooltip_unavailable' in result['unknowns']
    assert lua.eval('TEST_CARD.ability.blueprint_compat_ui')=='SECRET_STALE_UI'
    assert lua.eval('TEST_CARD.ability.blueprint_compat_check')=='ORIGINAL_CHECK'
    assert 'SECRET' not in canonical(result)


@pytest.mark.parametrize('failure',[
    'value.name=nil',
    'value.main={}',
    "value.main[2][1].config.object.focused_string=nil",
    "value.main[2][1].config.object.strings[1].string='Unresolved ERROR'",
    "value.info='SECRET_MALFORMED_UI'",
])
def test_incomplete_native_card_tooltip_is_explicit_without_identity_fallback(lua_reader,failure):
    lua,snapshot=lua_reader
    lua.execute(TOOLTIP_UI+TOOLTIP_SCENES['jokers'])
    lua.execute('local original=TEST_CARD.generate_UIBox_ability_table; TEST_CARD.generate_UIBox_ability_table=function(self) local value=original(self); '+failure+'; return value end')
    result=public(snapshot)
    assert result['unknowns'].count('tooltip_unavailable')==1
    assert 'SECRET' not in canonical(result) and 'Unresolved ERROR' not in canonical(result)


def test_intentionally_nameless_stone_tooltip_is_not_a_missing_title(lua_reader):
    lua,snapshot=lua_reader
    lua.execute("G.hand.cards[1].ability.name='Stone Card'; G.hand.cards[1].generate_UIBox_ability_table=function() return {name=true,main={{{config={text='Visible Stone effect'}}}},info={}} end")
    result=public(snapshot)
    item=result['regions'][0]['cards'][0]
    assert item['visibility']=='stone' and item['name'] is None
    assert item['description']==['Visible Stone effect']
    assert 'tooltip_unavailable' not in result['unknowns']


def test_genuinely_undiscovered_joker_keeps_native_public_discovery_text(lua_reader):
    lua,snapshot=lua_reader
    lua.execute(TOOLTIP_UI+TOOLTIP_SCENES['shop_jokers']+'; TEST_CARD.bypass_discovery_ui=false')
    result=public(snapshot)
    item=tooltip_card(result,'shop_jokers')
    assert item['visibility']=='undiscovered'
    assert item['name']=='Undiscovered' and item['description']==['Normal discovery text']
    assert 'Synthetic growth joker' not in canonical(result)


# Fixed Steamodded 26.829.0 lovely/booster.toml replaces Card:open's five
# legacy states with one Booster API state. Its live UI still owns pack_cards
# and skip_booster; selectable consumables can add a separate select button.
# Synthetic public cards below are deliberately unrelated to the real pack.
STEAMODDED_PACK_UI = """
    G.STATE=G.STATES.SMODS_BOOSTER_OPENED
    G.GAME.pack_choices=1
    G.pack_cards=area({card('Displayed first'),card('Displayed second')},2)
    G.pack_cards.config.highlighted_limit=nil
    G.pack_cards.config.highlight_limit=1
    for _, item in ipairs(G.pack_cards.cards) do item.area=G.pack_cards end
    local rendered_area=ui({object=G.pack_cards}); rendered_area.UIT=G.UIT.O
    G.booster_pack=ui_box({}, {rendered_area,
        ui({ref_table=G.GAME,ref_value='pack_choices'}),
        ui({func='can_skip_booster',button='skip_booster'}, {ui({text='Skip'})})})
    G.shop=ui_box({}, {ui({button='reroll_shop',func='can_reroll'})})
    G.shop_jokers=area({card('SECRET_SHOP_UNDER_PACK')})
    G.shop_booster=area({card('SECRET_UNOPENED_PACK')})
    G.future_pack={card('SECRET_FUTURE_CONTENTS')}
    SMODS.OPENED_BOOSTER={ability={extra=2,choose=1},config={center={
        update_pack=function() error('SECRET_UPDATE_CALLED') end,
        create_card=function() error('SECRET_CREATE_CALLED') end}}}
    G.FUNCS={can_skip_booster=function() error('SECRET_CALLBACK_CALLED') end,
        can_use_consumeable=function() error('SECRET_CALLBACK_CALLED') end,
        can_select_card=function() error('SECRET_CALLBACK_CALLED') end,
        can_select_from_booster=function() error('SECRET_CALLBACK_CALLED') end,
        use_card=function() error('SECRET_ACTION_CALLED') end}
"""


@pytest.mark.parametrize('card_set', ['Tarot','Planet','Spectral','Joker','Default'])
def test_fixed_steamodded_pack_shows_current_cards_and_native_buttons(lua_reader,card_set):
    lua,snapshot=lua_reader
    lua.execute(STEAMODDED_PACK_UI)
    lua.globals().TEST_PACK_SET=card_set
    lua.execute("""
        for _, item in ipairs(G.pack_cards.cards) do item.ability.set=TEST_PACK_SET end
        local item=G.pack_cards.cards[2]; item.highlighted=true
        local func=(TEST_PACK_SET=='Default' or TEST_PACK_SET=='Joker') and 'can_select_card' or 'can_use_consumeable'
        item.children.use_button=ui_box({}, {ui({ref_table=item,func=func,button='use_card'}, {ui({text='Displayed choice'})})})
    """)
    result=public(snapshot)
    assert result['phase']=='pack' and result['ready']
    assert result['resources']['pack_choices']==1 and result['resources']['reroll_cost'] is None
    region=next(row for row in result['regions'] if row['name']=='pack')
    assert region['capacity']==2 and region['selection_limit']==1
    assert [item['name'] for item in region['cards']]==['Displayed first','Displayed second']
    assert [item['position'] for item in region['cards']]==[0,1]
    assert [item['selected'] for item in region['cards']]==[False,True]
    assert all(item['description']==['Public effect'] for item in region['cards'])
    choice=next(action for action in result['ui_actions'] if action['region']=='pack')
    assert choice['name']==('select_pack_card' if card_set in ('Default','Joker') else 'use')
    assert choice['position']==1 and choice['enabled']
    assert any(action['name']=='skip_pack' and action['enabled'] for action in result['ui_actions'])
    assert not any(row['name'].startswith('shop_') for row in result['regions'])
    assert not any(action['name']=='reroll' for action in result['ui_actions'])
    assert 'SECRET' not in canonical(result)
    assert lua.eval('G.pack_cards.cards[2].ability.blueprint_compat_check') is None


@pytest.mark.parametrize('select_enabled', [False,True])
def test_steamodded_pack_separate_select_button_uses_native_enabled_state(lua_reader,select_enabled):
    lua,snapshot=lua_reader
    lua.execute(STEAMODDED_PACK_UI)
    lua.globals().TEST_SELECT_ENABLED=select_enabled
    lua.execute("""
        local item=G.pack_cards.cards[1]; item.ability.set='Tarot'; item.highlighted=true
        item.children.use_button=ui_box({}, {ui({ref_table=item,func='can_use_consumeable',button='use_card'})})
        item.children.select_button=ui_box({}, {ui({ref_table=item,func='can_select_from_booster',button=TEST_SELECT_ENABLED and 'use_card' or nil})})
    """)
    result=public(snapshot)
    actions={action['name']:action for action in result['ui_actions'] if action['region']=='pack'}
    assert set(actions)=={'use','select_pack_card'}
    assert actions['use']['enabled']
    assert actions['select_pack_card']['enabled']==select_enabled
    assert all(action['position']==0 for action in actions.values())


@pytest.mark.parametrize('mutation,reason', [
    ('G.STATE_COMPLETE=false','state_initializing'),
    ('G.CONTROLLER.locks.use=true','controller_locked'),
    ('G.GAME.STOP_USE=1','processing'),
    ('G.pack_cards.cards={}','processing'),
    ('G.booster_pack.states.visible=false','ui_not_displayed'),
    ('G.booster_pack.removed=true','ui_not_displayed'),
    ('G.booster_pack.VT={x=1,y=30,w=2,h=2}','ui_not_displayed'),
])
def test_steamodded_pack_init_and_effect_gates_suppress_early_cards(lua_reader,mutation,reason):
    lua,snapshot=lua_reader
    lua.execute(STEAMODDED_PACK_UI+';'+mutation)
    result=public(snapshot)
    assert result['phase']=='transition' and result['underlying_phase']=='pack'
    assert not result['ready'] and result['ready_reason']==reason
    assert result['regions']==[] and result['resources']['pack_choices'] is None
    assert not any(action['enabled'] for action in result['ui_actions'])
    assert 'SECRET' not in canonical(result)


def test_steamodded_open_pack_ignores_unopened_contents_and_hidden_order(lua_reader):
    lua,snapshot=lua_reader
    lua.execute(STEAMODDED_PACK_UI)
    before=public(snapshot)
    lua.execute("""
        G.future_pack={card('SECRET_OTHER_FUTURE')}
        G.shop_booster.cards={card('SECRET_OTHER_UNOPENED')}
        G.deck.cards={card('SECRET_OTHER_DRAW_ORDER')}
        G.GAME.seed='SECRET_OTHER_SEED'; G.GAME.pseudorandom={state='SECRET_OTHER_RNG'}
        SMODS.OPENED_BOOSTER.config.center.create_card=function() error('SECRET_OTHER_CREATE') end
    """)
    after=public(snapshot)
    assert before==after and observation_id(before)==observation_id(after)
    lua.execute('G.STATE=G.STATES.SHOP')
    shop=public(snapshot)
    assert not any(row['name']=='pack' for row in shop['regions'])
    assert shop['resources']['pack_choices'] is None


def test_steamodded_pack_face_down_identity_and_choice_remain_hidden(lua_reader):
    lua,snapshot=lua_reader
    lua.execute(STEAMODDED_PACK_UI+"""
        local item=G.pack_cards.cards[1]; item.facing='back'; item.sprite_facing='back'
        item.generate_UIBox_ability_table=function() error('SECRET_HIDDEN_TOOLTIP') end
        item.children.use_button=ui_box({}, {ui({ref_table=item,func='can_select_from_booster',button='use_card'})})
    """)
    before=public(snapshot)
    region=next(row for row in before['regions'] if row['name']=='pack')
    assert region['cards'][0]=={'position':0,'visibility':'face_down','selected':False}
    assert not any(action['region']=='pack' and action['position']==0 for action in before['ui_actions'])
    lua.execute("G.pack_cards.cards[1].public_name='SECRET_CHANGED_IDENTITY'; G.pack_cards.cards[1].ability={set='Spectral',name='SECRET_CHANGED_ABILITY'}; G.pack_cards.cards[1].base={value='King',suit='Diamonds'}")
    assert before==public(snapshot)


def test_steamodded_voucher_effect_is_processing_until_native_shop_returns(lua_reader):
    lua,snapshot=lua_reader
    lua.execute("G.STATE=G.STATES.SMODS_REDEEM_VOUCHER; G.shop=ui_box(); G.shop_jokers=area({card('SECRET_NOT_YET_READY')})")
    result=public(snapshot)
    assert result['phase']=='transition' and result['ready_reason']=='processing'
    assert not result['ready'] and result['regions']==[]
    assert 'SECRET' not in canonical(result)
    lua.execute('G.STATE=G.STATES.SHOP; G.shop_jokers.cards={}')
    result=public(snapshot)
    assert result['phase']=='shop' and result['ready']


def test_unknown_state_is_still_unsupported_with_steamodded_enums(lua_reader):
    lua,snapshot=lua_reader
    lua.execute(STEAMODDED_PACK_UI+'; G.STATE=997')
    result=public(snapshot)
    assert result['phase']=='unsupported' and result['ready_reason']=='unsupported_state'
    assert not result['ready'] and result['regions']==[]
    assert 'SECRET' not in canonical(result)


@pytest.mark.parametrize('card_set,region,gate,price', [
    ('Booster','shop_boosters','can_open',4),
    ('Voucher','shop_vouchers','can_redeem',10),
])
@pytest.mark.parametrize('affordable', [False,True])
def test_paid_shop_controls_use_native_definition_and_resource_gate(lua_reader,card_set,region,gate,price,affordable):
    lua,snapshot=lua_reader
    native=Path(__file__).resolve().parents[1]/'.artifacts/game-source/functions'
    if not (native/'UI_definitions.lua').exists():
        pytest.skip('Private fixed native source absent')
    source=(native/'UI_definitions.lua').read_text(encoding='utf-8')
    start=source.index('local t2 =',source.index('function create_shop_card_ui'))
    definition=source[start:source.index('local t3 =',start)]
    callbacks=(native/'button_callbacks.lua').read_text(encoding='utf-8')
    start=callbacks.index('G.FUNCS.can_redeem =')
    lua.execute('G.FUNCS={};'+callbacks[start:callbacks.index('G.FUNCS.HUD_blind_visible',start)])
    lua.execute(f"""
        G.C={{GREEN=1,GOLD=2,WHITE=3,UI={{BACKGROUND_INACTIVE=4}}}}
        G.UIT.ROOT=1; G.UIT.T=2; G.STATE=G.STATES.SHOP; G.shop=ui_box()
        G.GAME.bankrupt_at=0; G.GAME.dollars={price if affordable else 0}
        TEST_PRODUCT=card('Visible paid product'); TEST_PRODUCT.ability.set='{card_set}'
        TEST_PRODUCT.cost={price}; TEST_PRODUCT.highlighted=true
        G.{region}=area({{TEST_PRODUCT}}); TEST_PRODUCT.area=G.{region}
        if '{region}'=='shop_boosters' then G.shop_booster=G.shop_boosters end
        function native_definition_ui(def)
          local children={{}}
          for _,child in ipairs(def.nodes or {{}}) do children[#children+1]=native_definition_ui(child) end
          return ui(def.config,children)
        end
    """)
    lua.execute('local card=TEST_PRODUCT;'+definition+'; TEST_PAID_CONTROL=native_definition_ui(t2)')
    lua.execute(f'G.FUNCS.{gate}(TEST_PAID_CONTROL)')
    # Both real gates rewrite the displayed callback to use_card. The semantic
    # action remains buy, including a disabled button whose callback is nil.
    lua.execute('TEST_PRODUCT.children.buy_button=ui_box(); TEST_PRODUCT.children.buy_button.UIRoot=TEST_PAID_CONTROL')
    before_callback=lua.eval('TEST_PAID_CONTROL.config.button')
    result=public(snapshot)
    rows=[row for row in result['ui_actions'] if row['region']==region]
    assert len(rows)==1 and rows[0]['name']=='buy' and rows[0]['enabled'] is affordable
    assert before_callback==('use_card' if affordable else None)
    assert lua.eval('TEST_PAID_CONTROL.config.button')==before_callback
