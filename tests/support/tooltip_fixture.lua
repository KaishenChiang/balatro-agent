-- Synthetic native-shaped tooltip UI. Not a real game or strategy example.
-- Covers native DynaText nodes and Steamodded's duplicate config.text shape.
DynaText = {}
TEST_TOOLTIP_CALLS, TEST_TOOLTIP_REMOVED = 0, 0
function tooltip_word(value, static)
  local object = setmetatable({focused_string=1, states={visible=true},
    strings={{string=value},{string='SECRET_UNUSED_ALTERNATIVE'}},
    config={string={'SECRET_STORED_DEFINITION'}}}, DynaText)
  function object:remove() TEST_TOOLTIP_REMOVED=TEST_TOOLTIP_REMOVED+1 end
  return {n=G.UIT.O, config={text=static,object=object}}
end
TEST_CARD = card('SECRET_FALLBACK_NAME')
TEST_CARD.ability={set='Joker',name='Synthetic growth joker',mult=8,extra={visible_tally=2}}
TEST_CARD.config.center={set='Joker',key='j_synthetic',unlocked=true,discovered=false}
TEST_CARD.bypass_discovery_ui=true
function TEST_CARD:generate_UIBox_ability_table()
  TEST_TOOLTIP_CALLS=TEST_TOOLTIP_CALLS+1
  self.ability.tooltip_ui_flag='COPY_ONLY'
  self.ability.extra.tooltip_ui_flag='COPY_ONLY'
  if not self.bypass_discovery_ui and not self.bypass_lock and
     self.config.center.discovered==false and self.area~=G.jokers and self.area~=G.consumeables then
    return {name={tooltip_word('Undiscovered')},main={{tooltip_word('Normal discovery text')}},info={}}
  end
  local ui={
    name={{n=1,nodes={{n=2,nodes={tooltip_word('Synthetic growth joker')}}}}},
    main={
      {{n=3,config={text='Current Mult +'}},tooltip_word(tostring(self.ability.mult),tostring(self.ability.mult))},
      {tooltip_word('Public tally '..self.ability.extra.visible_tally)},
    },
    info={
      {name={tooltip_word('Visible edition')},{tooltip_word('Extra Joker slot +1')}},
      {name='Visible sticker',{tooltip_word('Public remaining rounds 3')}},
    }
  }
  if self.ability.name=='Blueprint' or self.ability.name=='Brainstorm' then
    self.ability.blueprint_compat_ui=self.ability.blueprint_compat_ui or ''
    self.ability.blueprint_compat_check=nil
    ui.main[#ui.main+1]={{n=2,config={ref_table=self,func='blueprint_compat'},nodes={
      {n=3,config={ref_table=self.ability,ref_value='blueprint_compat_ui'}}
    }}}
  end
  return ui
end
