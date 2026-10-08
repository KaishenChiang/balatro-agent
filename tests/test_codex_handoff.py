"""Directory/prompt handoff and dispatch with no real client, clipboard or game."""
import json
import shutil
import subprocess
from urllib.parse import parse_qs, urlsplit

import pytest

from test_setup import ROOT, PS, quote


def run_ps(command):
    if not PS:
        pytest.skip('Windows PowerShell')
    result = subprocess.run(
        [PS, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command',
         "$ErrorActionPreference='Stop';[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);" + command],
        capture_output=True, text=True, encoding='utf-8', timeout=25)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize('name', ['project', "中文 空格 & # % + ' !", 'nested/path with spaces'])
def test_link_encodes_exact_project_and_short_prompt_without_sending(tmp_path, name):
    root = tmp_path / name
    prompts = root / 'prompts'
    prompts.mkdir(parents=True)
    for filename in ('first-use.md', 'bootstrap.md'):
        shutil.copyfile(ROOT / 'prompts' / filename, prompts / filename)
    command = '. ' + quote(ROOT / 'scripts/codex_handoff.ps1') + ';'
    command += '$short=Get-BalatroPlayPrompt ' + quote(root) + ';'
    command += '$full=Get-BalatroPlayPrompt ' + quote(root) + ' -InlineRules;'
    command += '$link=Get-BalatroCodexLink ' + quote(root) + ' $short;'
    command += '@{short=$short;full=$full;link=$link}|ConvertTo-Json'
    value = run_ps(command)
    link = urlsplit(value['link'])
    assert link.scheme == 'codex' and link.netloc == 'threads' and link.path == '/new'
    query = parse_qs(link.query, strict_parsing=True)
    assert set(query) == {'path', 'prompt'}
    assert query['path'] == [str(root)] and query['prompt'] == [value['short']]
    assert root.as_posix() + '/prompts/bootstrap.md' in value['short']
    assert root.as_posix() in value['full']
    assert (prompts / 'bootstrap.md').read_text(encoding='utf-8').strip() in value['full']
    assert '请阅读 ' not in value['full']
    assert 'UNKNOWN' in value['full'] and '缺少 MCP 工具时先报告' in value['full']
    assert '自动发送' not in value['link']
    assert not (root / '.artifacts').exists() and not (root / 'runs').exists()


@pytest.mark.parametrize('mode', ['supported', 'missing_protocol', 'failed_dispatch', 'missing_app'])
def test_launcher_uses_project_link_or_copies_full_prompt_without_real_dispatch(tmp_path, mode):
    source = (ROOT / 'scripts/launcher.ps1').read_text(encoding='utf-8-sig')
    begin = source.index('function Open-Codex')
    end = source.index('$ink =', begin)
    helper = tmp_path / 'dispatch.ps1'
    helper.write_text(source[begin:end], encoding='utf-8-sig')
    command = '. ' + quote(helper) + ';'
    command += "$codexLink='codex://threads/new?path=encoded&prompt=encoded';$promptText='complete rules';"
    command += "$detail=[pscustomobject]@{Text=''};$script:desktopError='';$script:copied=$false;$script:requests=@();$script:refreshed=$false;"
    command += "$fixtureProtocol=New-Object PSObject;Add-Member -InputObject $fixtureProtocol -MemberType ScriptMethod -Name GetValueNames -Value {@('URL Protocol')};"
    command += "function Update-PlayPrompt {$script:refreshed=$true};function Copy-PlayPrompt {$script:copied=$true};"
    command += 'function Get-Item {param($LiteralPath,$ErrorAction)'
    command += ('$null' if mode in ('missing_protocol', 'missing_app') else '$fixtureProtocol') + '};'
    command += "function Get-StartApps {"
    command += ('$null' if mode == 'missing_app' else "[pscustomobject]@{Name='Codex';AppID='fixture-app'}") + '};'
    command += 'function Start-Process {param($FilePath,$ArgumentList,$WindowStyle)'
    if mode == 'failed_dispatch':
        command += "if($FilePath -like 'codex:*'){throw 'fixture dispatch failure'};"
    command += '$script:requests+=@{path=$FilePath;arguments=$ArgumentList;window=$WindowStyle}};'
    command += 'Open-Codex;@{copied=$script:copied;requests=$script:requests;detail=$detail.Text;refreshed=$script:refreshed}|ConvertTo-Json -Depth 4'
    value = run_ps(command)
    assert value['refreshed']
    assert len(value['requests']) == 1
    request = value['requests'][0]
    assert request['window'] == 'Hidden'
    if mode == 'supported':
        assert request['path'] == 'codex://threads/new?path=encoded&prompt=encoded'
        assert not value['copied'] and '填入提示' in value['detail']
    else:
        assert value['copied']
        if mode == 'missing_app':
            assert request['path'] == 'https://developers.openai.com/codex/app/'
        else:
            assert request['arguments'] == 'shell:AppsFolder\\fixture-app'


def test_missing_directory_or_prompt_is_rejected_without_artifacts(tmp_path):
    command = '. ' + quote(ROOT / 'scripts/codex_handoff.ps1') + ';$rejected=0;'
    command += 'try {Get-BalatroCodexLink ' + quote(tmp_path / 'missing') + " 'play'}catch{$rejected++};"
    command += 'try {Get-BalatroCodexLink ' + quote(tmp_path) + " ''}catch{$rejected++};"
    command += '@{rejected=$rejected}|ConvertTo-Json'
    assert run_ps(command)['rejected'] == 2
    assert not list(tmp_path.iterdir())


def test_all_original_decks_and_stake_modes_reach_both_handoff_paths():
    command = '. ' + quote(ROOT / 'scripts/codex_handoff.ps1') + ';'
    command += '$choices=Get-BalatroPlayChoices;$rows=@();'
    command += 'foreach($deck in $choices.Decks){foreach($stake in $choices.Stakes){'
    command += '$short=Get-BalatroPlayPrompt ' + quote(ROOT) + ' -DeckKey $deck.Key -StakeChoice $stake.Key;'
    command += '$full=Get-BalatroPlayPrompt ' + quote(ROOT) + ' -InlineRules -DeckKey $deck.Key -StakeChoice $stake.Key;'
    command += '$rows+=@{deck=$deck;stake=$stake;short=$short;full=$full;link=(Get-BalatroCodexLink ' + quote(ROOT) + ' $short)}'
    command += '}};@{choices=$choices;rows=$rows}|ConvertTo-Json -Depth 5'
    value = run_ps(command)
    decks = value['choices']['Decks']
    stakes = value['choices']['Stakes']
    assert len(decks) == 15 and len({item['Key'] for item in decks}) == 15
    assert [item['Key'] for item in stakes] == [
        'white', 'red', 'green', 'black', 'blue', 'purple', 'orange', 'gold', 'highest', 'climb']
    assert len(value['rows']) == 150
    for row in value['rows']:
        for text in (row['short'], row['full']):
            assert '所选牌组：' + row['deck']['Name'] in text
            assert '所选注级／模式：' + row['stake']['Name'] in text
            assert row['deck']['EnglishName'] in text and row['stake']['EnglishName'] in text
            assert '心得' in text and '用时' in text and '未解锁' in text
        assert parse_qs(urlsplit(row['link']).query)['prompt'] == [row['short']]
        if row['stake']['Key'] == 'climb':
            assert '不设正常败局重试次数上限' in row['short']
            assert '紧接的下一注级' in row['short'] and 'UNKNOWN' in row['short']
        else:
            assert '不设正常败局重试次数上限' not in row['short']
            assert '只尝试一局' in row['short'] or '不自动重试' in row['short']


def test_unsupported_play_choices_are_rejected():
    command = '. ' + quote(ROOT / 'scripts/codex_handoff.ps1') + ';$rejected=0;'
    for deck, stake in [('b_secret', 'white'), ('b_red', 'rainbow'), ('', 'climb')]:
        command += 'try {Get-BalatroPlayPrompt ' + quote(ROOT)
        command += ' -DeckKey ' + quote(deck) + ' -StakeChoice ' + quote(stake) + '}catch{$rejected++};'
    command += '@{rejected=$rejected}|ConvertTo-Json'
    assert run_ps(command)['rejected'] == 3


@pytest.mark.parametrize('deck,stake', [('b_red','white'),('b_ghost','highest'),('b_erratic','climb')])
def test_actual_windows_selectors_refresh_prompt_and_link_without_game_or_dispatch(tmp_path,deck,stake):
    scripts=tmp_path/'scripts';scripts.mkdir()
    prompts=tmp_path/'prompts';prompts.mkdir()
    shutil.copyfile(ROOT/'scripts/codex_handoff.ps1',scripts/'codex_handoff.ps1')
    for filename in ('first-use.md','bootstrap.md'):
        shutil.copyfile(ROOT/'prompts'/filename,prompts/filename)
    source=(ROOT/'scripts/launcher.ps1').read_text(encoding='utf-8-sig')
    before='@{deck=$deckChoice.SelectedItem.Key;stake=$stakeChoice.SelectedItem.Key}'
    hook='$defaults='+before+';'
    hook+='for($i=0;$i -lt $deckChoice.Items.Count;$i++){if($deckChoice.Items[$i].Key -eq '+quote(deck)+'){$deckChoice.SelectedIndex=$i}};'
    hook+='for($i=0;$i -lt $stakeChoice.Items.Count;$i++){if($stakeChoice.Items[$i].Key -eq '+quote(stake)+'){$stakeChoice.SelectedIndex=$i}};'
    source=source.replace('if ($Preview) {',hook+'\nif ($Preview) {')
    output='@{defaults=$defaults;deck=$deckChoice.SelectedItem;stake=$stakeChoice.SelectedItem;'
    output+='deck_text=$deckChoice.GetItemText($deckChoice.SelectedItem);stake_text=$stakeChoice.GetItemText($stakeChoice.SelectedItem);'
    output+='deck_count=$deckChoice.Items.Count;stake_count=$stakeChoice.Items.Count;'
    output+='selectors_enabled=($deckChoice.Enabled -and $stakeChoice.Enabled);full=$promptText;link=$codexLink;mode=$modeDetail.Text}|ConvertTo-Json -Depth 4;'
    marker='$form.Dispose(); $timer.Dispose(); $tooltip.Dispose(); exit 0'
    assert source.count(marker)==1
    source=source.replace(marker,output+marker)
    entry=scripts/'launcher.ps1';entry.write_text(source,encoding='utf-8-sig')
    value=run_ps('& '+quote(entry)+' -Preview')
    assert value['defaults']=={'deck':'b_red','stake':'white'}
    assert value['deck']['Key']==deck and value['stake']['Key']==stake
    assert value['selectors_enabled'] and value['deck_count']==15 and value['stake_count']==10
    assert value['deck_text']==value['deck']['Name'] and value['stake_text']==value['stake']['Name']
    assert '所选牌组：'+value['deck']['Name'] in value['full']
    short=parse_qs(urlsplit(value['link']).query)['prompt'][0]
    assert '所选牌组：'+value['deck']['Name'] in short
    assert '所选注级／模式：'+value['stake']['Name'] in short
    assert not (tmp_path/'.artifacts').exists() and not (tmp_path/'runs').exists()
