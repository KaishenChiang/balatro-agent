"""Localization boundaries: synthetic public state and actual Windows UI/argv."""
import json
import shutil
import subprocess

import pytest

from balatro_agent.contract import Envelope
from balatro_agent.policy import canonical
from test_setup import ROOT, PS, quote
from test_codex_handoff import run_ps
from test_executor import game, native_start_wrappers


@pytest.mark.parametrize('culture,expected', [('zh-CN','zh-CN'), ('zh-TW','zh-CN'), ('en-US','en'), ('en-GB','en'), ('ja-JP','en')])
def test_windows_display_language_fallback_and_explicit_override(culture, expected):
    command = '. ' + quote(ROOT / 'scripts/localization.ps1') + ';'
    command += '@{automatic=(Resolve-BalatroLanguage auto ' + quote(culture) + ');'
    command += 'english=(Resolve-BalatroLanguage en ' + quote(culture) + ');'
    command += 'chinese=(Resolve-BalatroLanguage zh-CN ' + quote(culture) + ')}|ConvertTo-Json'
    result = run_ps(command)
    assert result == {'automatic':expected, 'english':'en', 'chinese':'zh-CN'}


def test_all_english_deck_stake_requests_use_english_rules_in_both_handoff_paths():
    command = '. ' + quote(ROOT / 'scripts/codex_handoff.ps1') + ';$choices=Get-BalatroPlayChoices;$rows=@();'
    command += 'foreach($deck in $choices.Decks){foreach($stake in $choices.Stakes){'
    command += '$short=Get-BalatroPlayPrompt ' + quote(ROOT) + ' -Language en -DeckKey $deck.Key -StakeChoice $stake.Key;'
    command += '$full=Get-BalatroPlayPrompt ' + quote(ROOT) + ' -Language en -InlineRules -DeckKey $deck.Key -StakeChoice $stake.Key;'
    command += '$rows+=@{deck=$deck.EnglishName;stake=$stake.EnglishName;key=$stake.Key;short=$short;full=$full;link=(Get-BalatroCodexLink ' + quote(ROOT) + ' $short)}'
    command += '}};@{rows=$rows}|ConvertTo-Json -Depth 4'
    rows = run_ps(command)['rows']
    assert len(rows) == 150
    rules = (ROOT / 'prompts/bootstrap.en.md').read_text(encoding='utf-8').strip()
    from urllib.parse import parse_qs, urlsplit
    for row in rows:
        for text in (row['short'], row['full']):
            assert 'Selected deck: ' + row['deck'] in text
            assert 'selected stake / mode: ' + row['stake'] in text
            assert 'Reply in English' in text and 'UNKNOWN' in text and 'locked' in text
            assert 'elapsed time' in text and 'experience' in text
        assert '/prompts/bootstrap.en.md' in row['short']
        assert rules in row['full'] and 'Read ' + ROOT.as_posix() not in row['full']
        assert parse_qs(urlsplit(row['link']).query)['prompt'] == [row['short']]
        if row['key'] == 'climb':
            assert 'no retry limit' in row['short'] and 'immediately next stake' in row['short']
        else:
            assert 'no retry limit' not in row['short'] and 'one run' in row['short']


@pytest.mark.parametrize('language,state', [('en','Ready'), ('zh-CN','Ready'), ('en','Downloading'), ('en','Error')])
def test_real_windows_language_switch_preserves_choices_and_preparation(tmp_path, language, state):
    scripts = tmp_path / 'scripts'; scripts.mkdir()
    prompts = tmp_path / 'prompts'; prompts.mkdir()
    for name in ('codex_handoff.ps1', 'localization.ps1'):
        shutil.copyfile(ROOT / 'scripts' / name, scripts / name)
    for name in ('first-use.md','bootstrap.md','first-use.en.md','bootstrap.en.md'):
        shutil.copyfile(ROOT / 'prompts' / name, prompts / name)
    source = (ROOT / 'scripts/launcher.ps1').read_text(encoding='utf-8-sig')
    hook = '''
    for($i=0;$i -lt $deckChoice.Items.Count;$i++){if($deckChoice.Items[$i].Key -eq 'b_ghost'){$deckChoice.SelectedIndex=$i}}
    for($i=0;$i -lt $stakeChoice.Items.Count;$i++){if($stakeChoice.Items[$i].Key -eq 'climb'){$stakeChoice.SelectedIndex=$i}}
    $before=@{deck=$deckChoice.SelectedItem.Key;stake=$stakeChoice.SelectedItem.Key;prepared=$script:prepared;status=$status.Text}
    $languageChoice.SelectedIndex=if($languageChoice.SelectedIndex -eq 0){1}else{0}
    $middle=@{deck=$deckChoice.SelectedItem.Key;stake=$stakeChoice.SelectedItem.Key;prepared=$script:prepared;language=$script:language}
    $languageChoice.SelectedIndex=if($languageChoice.SelectedIndex -eq 0){1}else{0}
    @{before=$before;middle=$middle;deck=$deckChoice.SelectedItem.Key;stake=$stakeChoice.SelectedItem.Key;
      prepared=$script:prepared;status=$status.Text;language=$script:language;deck_text=$deckChoice.GetItemText($deckChoice.SelectedItem);
      stake_text=$stakeChoice.GetItemText($stakeChoice.SelectedItem);full=$promptText;mode=$modeDetail.Text;
      start=$open.Text;copy=$copy.Text;details=$logLink.Text;detail=$detail.Text}|ConvertTo-Json -Depth 4
    '''
    marker = '$form.Dispose(); $timer.Dispose(); $tooltip.Dispose(); exit 0'
    assert source.count(marker) == 1
    source = source.replace(marker, hook + marker)
    entry = scripts / 'launcher.ps1'; entry.write_text(source, encoding='utf-8-sig')
    value = run_ps('. ' + quote(entry) + ' -Preview -Language ' + language + ' -PreviewState ' + state)
    assert value['deck'] == value['before']['deck'] == value['middle']['deck'] == 'b_ghost'
    assert value['stake'] == value['before']['stake'] == value['middle']['stake'] == 'climb'
    assert value['prepared'] == value['before']['prepared'] == value['middle']['prepared']
    assert value['status'] == value['before']['status']
    assert value['language'] == language and value['middle']['language'] != language
    if language == 'en':
        assert value['deck_text'] == 'Ghost Deck' and value['stake_text'] == 'Stake climb'
        assert value['start'] == 'Start in Codex' and value['copy'] == 'Copy play prompt' and value['details'] == 'Details'
        assert 'Reply in English' in value['full'] and 'Gold' in value['mode']
    else:
        assert value['deck_text'] == '幽灵牌组' and '所选牌组：幽灵牌组' in value['full']
    assert not (tmp_path / '.artifacts').exists() and not (tmp_path / 'runs').exists()


@pytest.mark.parametrize('language', ['en', 'zh-CN'])
def test_exe_forwards_explicit_language_without_console_or_preview_requirement(tmp_path, language):
    if not PS: pytest.skip('Windows WinExe')
    scripts = tmp_path / 'scripts'; scripts.mkdir()
    executable = tmp_path / 'Balatro Agent.exe'; shutil.copyfile(ROOT / executable.name, executable)
    stub = '''param([string]$Language)
Add-Type 'using System; using System.Runtime.InteropServices; public static class LangConsoleProbe { [DllImport("kernel32.dll")] public static extern IntPtr GetConsoleWindow(); }'
@{language=$Language;console=[LangConsoleProbe]::GetConsoleWindow().ToInt64()}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $PSScriptRoot '../called.json') -Encoding UTF8
'''
    (scripts / 'launcher.ps1').write_text(stub, encoding='utf-8-sig')
    result = subprocess.run([str(executable), '--language', language], cwd=tmp_path, timeout=25)
    assert result.returncode == 0
    assert json.loads((tmp_path / 'called.json').read_text(encoding='utf-8-sig')) == {'language':language, 'console':0}
    assert not (tmp_path / '.artifacts').exists()


# Small player-visible labels, not private localization files or strategy text.
NATIVE_LOCALE = r'''
local previous_localize=localize
local names={b_red='Red Deck',b_blue='Blue Deck',stake_white='White Stake',stake_red='Red Stake',
 stake_green='Green Stake',stake_black='Black Stake',stake_blue='Blue Stake',stake_purple='Purple Stake',
 stake_orange='Orange Stake',stake_gold='Gold Stake',run_select_play='Play',run_select_locked_stake='Locked',
 k_compatible='Compatible',k_incompatible='Incompatible'}
function localize(value,kind)
 if type(value)=='table' and value.type=='name_text' and names[value.key] then return names[value.key] end
 if type(value)=='string' and names[value] then return names[value] end
 if kind=='poker_hands' and value=='Pair' then return 'Pair' end
 if kind=='poker_hand_descriptions' then return {'2 cards with the same rank'} end
 return previous_localize(value,kind)
end
G.SETTINGS.language='en-us'
'''


def test_english_visible_text_survives_reader_contract_without_hidden_state(lua_reader):
    lua, snapshot = lua_reader
    lua.execute(NATIVE_LOCALE)
    lua.execute("G.GAME.blind.loc_name='Small Blind';G.GAME.blind.loc_debuff_text='No special effects'")
    result = Envelope.model_validate(snapshot()).public.model_dump()
    assert result['blinds'][0]['name'] == 'Small Blind'
    assert result['menus']['poker_hands'][0]['name'] == 'Pair'
    assert result['menus']['poker_hands'][0]['description'] == ['2 cards with the same rank']
    assert 'HIDDEN' not in canonical(result) and 'en-us' not in canonical(result)
    lua.execute("G.hand.cards[1].facing='back';G.hand.cards[1].sprite_facing='back';G.hand.cards[1].public_name='SECRET_IDENTITY'")
    masked = snapshot()
    assert 'SECRET_IDENTITY' not in canonical(masked)


def test_english_joker_tooltip_keeps_current_values_and_visible_compatibility(lua_reader):
    lua, snapshot = lua_reader
    lua.execute(NATIVE_LOCALE)
    lua.execute((ROOT / 'tests/support/tooltip_fixture.lua').read_text(encoding='utf-8'))
    lua.execute("TEST_CARD.ability.name='Blueprint';TEST_CARD.ability.blueprint_compat='compatible';G.jokers=area({TEST_CARD},5);TEST_CARD.area=G.jokers")
    before = Envelope.model_validate(snapshot())
    joker = next(region for region in before.public.regions if region.name == 'jokers').cards[0]
    assert joker.name == 'Synthetic growth joker'
    assert joker.description == ['Current Mult +8', 'Public tally 2', ' Compatible ']
    assert joker.tooltip_info == ['Visible edition', 'Extra Joker slot +1', 'Visible sticker', 'Public remaining rounds 3']
    assert lua.eval('TEST_CARD.ability.tooltip_ui_flag') is None
    assert lua.eval('TEST_CARD.ability.blueprint_compat_ui') is None
    assert 'SECRET' not in canonical(before.public.model_dump())
    lua.execute('TEST_CARD.ability.mult=11;TEST_CARD.ability.extra.visible_tally=4')
    after = Envelope.model_validate(snapshot())
    current = next(region for region in after.public.regions if region.name == 'jokers').cards[0]
    assert current.description == ['Current Mult +11', 'Public tally 4', ' Compatible ']
    assert after.observation_id != before.observation_id


def test_english_joker_purchase_uses_native_callback_and_confirmed_result(game):
    from test_executor import native_purchase_fixture, request
    lua, call, tick = game
    lua.execute(NATIVE_LOCALE)
    native_purchase_fixture(lua, 5)
    lua.execute("TEST_PRODUCT.public_name='English Joker';TEST_PRODUCT.generate_UIBox_ability_table=function(self) return {name={{config={text=self.public_name}}},main={{{config={text='Current Mult +4'}}}},info={}} end")
    initial = Envelope.model_validate(call('reader_snapshot')).public
    product = next(region for region in initial.regions if region.name == 'shop_jokers').cards[0]
    assert product.name == 'English Joker' and product.description == ['Current Mult +4'] and product.price == 5
    req = request(game, 'buy', {'region':'shop_jokers','position':0}, 'english-joker-purchase')
    submitted = call('act_submit', req)
    assert submitted['state'] == 'RUNNING' and submitted['submitted']
    assert lua.eval('#G.jokers.cards') == 0
    for _ in range(20):
        tick()
        if call('action_status', {'action_id':req['action_id']})['state'] == 'COMPLETED': break
    done = call('action_status', {'action_id':req['action_id']})
    assert done['state'] == 'COMPLETED' and done['callback_confirmed']
    assert lua.eval('G.GAME.dollars') == 5 and lua.eval('#G.jokers.cards') == 1
    assert lua.eval('G.jokers.cards[1].public_name') == 'English Joker'
    repeated = call('act_submit', req)
    assert repeated['state'] == 'COMPLETED'
    assert lua.eval('G.GAME.dollars') == 5 and lua.eval('#G.jokers.cards') == 1


@pytest.mark.parametrize('kind', ['deck', 'stake'])
def test_english_native_setup_clicks_and_locked_candidates(game, kind):
    from test_progression import setup_scene
    from test_executor import request
    lua, call, tick = game
    lua.execute(NATIVE_LOCALE)
    setup_scene(game, kind)
    initial = call('reader_snapshot')
    setup = Envelope.model_validate(initial).public.setup
    # This fixture renders candidate cards without a selected-deck preview.
    # The adapter must not invent the missing selected names.
    assert setup.deck_name is None and setup.stake_name is None
    assert setup.options[0].name == ('Red Deck' if kind == 'deck' else 'White Stake')
    locked = [o for o in setup.options if o.enabled is False]
    assert locked and all(not o.selected for o in locked)
    if kind == 'stake': assert locked[0].name == 'Locked'
    response = call('act_submit', request(game, 'select_setup_option', {'kind':kind,'position':1}, 'english-choice'))
    assert response['state'] in ('RUNNING', 'COMPLETED') and response['submitted']
    for _ in range(12): tick()
    done = call('action_status', {'action_id':'english-choice'})
    assert done['state'] == 'COMPLETED' and done['callback_confirmed']
    denied = call('act_submit', request(game, 'select_setup_option', {'kind':kind,'position':2}, 'english-locked'))
    assert denied['state'] == 'REJECTED' and denied['submitted'] is False
    assert 'b_hidden' not in canonical(denied)


def test_game_language_change_invalidates_an_old_observation_without_submitting(game):
    from test_progression import setup_scene
    from test_executor import request
    lua, call, _ = game
    lua.execute(NATIVE_LOCALE)
    setup_scene(game, 'deck')
    old = request(game, 'select_setup_option', {'kind':'deck','position':1}, 'before-language-change')
    lua.execute("local previous=localize;function localize(value,kind) if type(value)=='table' and value.key=='b_red' then return '红色牌组' end;return previous(value,kind) end")
    rejected = call('act_submit', old)
    assert rejected['state'] == 'REJECTED' and rejected['reason'] == 'stale_observation' and rejected['submitted'] is False
