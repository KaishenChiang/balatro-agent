-- Synthetic UI/state fixture only; not a real run and not strategy advice.
UIBox = {}
function ui(config, children)
  local value={config=config or {},children=children or {},states={visible=true}}
  function value:get_UIE_by_ID(id)
    if self.config.id==id then return self end
    for _,child in pairs(self.children) do
      if child.get_UIE_by_ID then local found=child:get_UIE_by_ID(id); if found then return found end end
    end
  end
  return value
end
function ui_box(config, children)
  local value={UIRoot=ui(config,children),children={},states={visible=true}}
  function value:get_UIE_by_ID(id) return self.UIRoot:get_UIE_by_ID(id) end
  return setmetatable(value,UIBox)
end
function card(name, rank, suit)
  local value={facing='front',sprite_facing='front',highlighted=false,states={visible=true},children={},
               base={value=rank or 'Ace',suit=suit or 'Spades'},ability={set='Default',name='Base',effect='Base'},
               config={center={key='c_base',discovered=true}},public_name=name or 'Public card',cost=0,sell_cost=0,
               sort_id='HIDDEN_SORT',playing_card='HIDDEN_ID'}
  function value:generate_UIBox_ability_table()
    self.ability.blueprint_compat_check='UI_WRITE'
    return {name={{config={text=self.public_name}}},main={{{config={text='Public effect'}}}},info={{name='Visible info',{{config={text='Visible extra'}}}}}}
  end
  return value
end
function area(cards, limit)
  return {cards=cards or {},config={card_limit=limit or 8,highlighted_limit=5},states={visible=true}}
end
G={VERSION='1.0.1o-FULL',STATE_COMPLETE=true,STAGES={MAIN_MENU=1,RUN=2},STAGE=2,UIT={O=5},
   STATES={SELECTING_HAND=1,HAND_PLAYED=2,DRAW_TO_HAND=3,GAME_OVER=4,SHOP=5,PLAY_TAROT=6,BLIND_SELECT=7,ROUND_EVAL=8,TAROT_PACK=9,PLANET_PACK=10,MENU=11,SPLASH=13,SPECTRAL_PACK=15,STANDARD_PACK=17,BUFFOON_PACK=18,NEW_ROUND=19,SMODS_BOOSTER_OPENED=999,SMODS_REDEEM_VOUCHER=998},
   SETTINGS={profile=3},CONTROLLER={locked=false,lock_input=false,locks={}},
   ROOM={T={x=0,y=0,w=20,h=20}},HUD=ui_box(),buttons=ui_box({}, {ui({button='play_cards_from_highlighted',func='can_play'}),ui({button=nil,func='can_discard'})}),
   hand=area({card('First'),card('Second','2','Hearts')}),jokers=area({},5),consumeables=area({},2),play=area(),
   deck={cards={card('HIDDEN_DECK'),card('HIDDEN_FUTURE')}},playing_cards={},P_BLINDS={},P_TAGS={},P_STAKES={},
   GAME={dollars=0,chips=0,round=1,STOP_USE=0,seed='HIDDEN_SEED',pseudorandom={state='HIDDEN_RANDOM'},
         current_round={hands_left=4,discards_left=3,reroll_cost=5,most_played_poker_hand='Pair'},
         round_resets={ante=1,blind_choices={},blind_states={},blind_tags={}},starting_params={ante_scaling=1},
         modifiers={},hands={Pair={visible=true,level=1,chips=10,mult=2,played=0},['Flush Five']={visible=false,level=99}},
         blind={name='Small Blind',loc_name='Public blind',loc_debuff_text='Public rule',chips=300,dollars=3}}}
G.STATE=G.STATES.SELECTING_HAND
G.hand.cards[1].area=G.hand; G.hand.cards[2].area=G.hand
-- Mirror the fixed real loader's built-in entries, including platform metadata.
SMODS.Mods={Steamodded={can_load=true,meta_mod=true},balatrobot={can_load=true},
            Lovely={id='Lovely',can_load=true,meta_mod=true},Balatro={id='Balatro',can_load=true,meta_mod=true}}
function localize(value, kind)
  if kind=='poker_hand_descriptions' then return {'Visible hand rule'} end
  if type(value)=='string' then return value end
  if value.type=='raw_descriptions' then return {'Visible blind rule'} end
  return 'Visible ' .. value.key
end
function get_blind_amount(ante) return 300*ante end
