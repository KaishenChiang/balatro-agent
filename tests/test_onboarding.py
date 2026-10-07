"""Automatic preparation against synthetic Steam/Mod/client paths only."""
import json
import os
from pathlib import Path
import sys
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import onboarding
import update_mod
from bootstrap_sources import digest
from test_distribution import install_layout, closed_backend
from test_setup import run_helpers, quote, PS


@pytest.fixture
def automatic_layout(install_layout, monkeypatch):
    root, steam, library, mods, config = install_layout
    manifest_path = root / 'mod/build-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    item = root / '.artifacts/built-mod/balatrobot/balatrobot.json'
    item.write_text('{"id":"balatrobot"}', encoding='utf-8')
    manifest['files'].append({'path': item.name, 'sha256': digest(item)})
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
    (root / 'pyproject.toml').write_text('[project]\nversion="0.6.3"\n', encoding='utf-8')
    monkeypatch.setattr(onboarding, 'runtime_ready', lambda root: True)
    async def tools(root): return 11
    monkeypatch.setattr(onboarding, 'list_prepared_tools', tools)
    closed_backend(monkeypatch)
    class Backend:
        def __init__(self, config): pass
        def find(self): return None
    monkeypatch.setattr(update_mod, 'WindowsGame', Backend)
    return root, steam, library, mods, config


def prepare(layout, **options):
    root, steam, library, mods, config = layout
    return onboarding.prepare(root, steam_dir=steam, library_dir=library,
                              mods=mods, config=config, **options)


def test_automatic_first_install_and_fast_reopen(automatic_layout, monkeypatch):
    root, _, _, mods, config = automatic_layout
    result = prepare(automatic_layout, preparation_id='first')
    assert result['prepared'] and result['stdio_tools_verified'] == 11
    assert not result['client_connection_verified'] and not result['game_started']
    assert not result['reused_installation'] and result['installed_files_verified'] == 5
    before = {p: p.read_bytes() for p in [config, *mods.rglob('*')] if p.is_file()}
    def unexpected(*args, **kwargs): raise AssertionError('Fast reopening must not install/update')
    monkeypatch.setattr(onboarding, 'prepare_installation', unexpected)
    monkeypatch.setattr(onboarding, 'update_runtime', unexpected)
    reused = prepare(automatic_layout, reuse_only=True, preparation_id='second')
    assert reused['reused_installation'] and reused['preparation_id'] == 'second'
    assert all(p.read_bytes() == data for p, data in before.items())
    assert json.loads((root / '.artifacts/onboarding.local.json').read_text())['preparation_id'] == 'second'


@pytest.mark.parametrize('damage', ['installed', 'partial', 'client', 'paths'])
def test_reopen_preserves_modified_files_and_incomplete_installation(automatic_layout, damage):
    prepare(automatic_layout)
    root, _, _, mods, config = automatic_layout
    if damage == 'installed': (mods / 'balatrobot/balatrobot.lua').write_bytes(b'user edit')
    if damage == 'partial':
        path = root / '.artifacts/portable-install.local.json'
        value = json.loads(path.read_text()); value['complete'] = False
        path.write_text(json.dumps(value), encoding='utf-8')
    if damage == 'client': config.write_text(config.read_text().replace('codex_config', 'other-client'), encoding='utf-8')
    if damage == 'paths':
        path = root / '.artifacts/portable-plan.local.json'
        value = json.loads(path.read_text()); value['library_dir'] = str(root)
        path.write_text(json.dumps(value), encoding='utf-8')
    protected = {p: p.read_bytes() for p in [config, *mods.rglob('*')] if p.is_file()}
    with pytest.raises(ValueError): prepare(automatic_layout, reuse_only=True)
    assert all(p.read_bytes() == data for p, data in protected.items())


def test_owned_update_uses_existing_backup_and_frozen_plan(automatic_layout):
    prepare(automatic_layout)
    root, _, _, mods, config = automatic_layout
    before = config.read_bytes()
    source = root / '.artifacts/built-mod/balatrobot/balatrobot.lua'
    source.write_bytes(b'-- newer project-owned runtime')
    path = root / 'mod/build-manifest.json'
    manifest = json.loads(path.read_text())
    next(i for i in manifest['files'] if i['path'] == 'balatrobot.lua')['sha256'] = digest(source)
    path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(onboarding.NeedsPreparation): prepare(automatic_layout, reuse_only=True)
    result = prepare(automatic_layout)
    assert result['prepared'] and result['reused_installation']
    assert (mods / 'balatrobot/balatrobot.lua').read_bytes() == source.read_bytes()
    assert config.read_bytes() == before
    reports = list((root / 'runs/checks').glob('automatic-update-*-applied.json'))
    assert len(reports) == 1 and json.loads(reports[0].read_text())['backup_verified']


def test_owned_update_cannot_bypass_unknown(automatic_layout):
    prepare(automatic_layout)
    root, _, _, mods, _ = automatic_layout
    path = root / 'runs/live/executor/checkpoint.json'; path.parent.mkdir(parents=True)
    path.write_text('{"pending":{"state":"UNKNOWN"},"input_pending":null}', encoding='utf-8')
    source = root / '.artifacts/built-mod/balatrobot/balatrobot.lua'
    source.write_bytes(b'-- updated')
    manifest_path = root / 'mod/build-manifest.json'
    value = json.loads(manifest_path.read_text())
    next(i for i in value['files'] if i['path'] == 'balatrobot.lua')['sha256'] = digest(source)
    manifest_path.write_text(json.dumps(value), encoding='utf-8')
    before = (mods / 'balatrobot/balatrobot.lua').read_bytes()
    with pytest.raises(ValueError, match='checkpoint'): prepare(automatic_layout)
    assert (mods / 'balatrobot/balatrobot.lua').read_bytes() == before


def test_missing_registration_adds_only_project_table_with_backup(tmp_path):
    root = tmp_path / '中文 project'; root.mkdir()
    config = tmp_path / 'Codex/config.toml'; config.parent.mkdir()
    original = b'model="keep"\r\n[mcp_servers.other]\r\ncommand="keep"\r\n'
    config.write_bytes(original)
    onboarding.ensure_client(root, config)
    assert config.read_bytes().startswith(original) and onboarding.client_ready(root, config)
    backups = list((root / '.artifacts/backups').glob('*/config-before.toml'))
    assert len(backups) == 1 and backups[0].read_bytes() == original
    onboarding.ensure_client(root, config)
    assert len(list((root / '.artifacts/backups').glob('*/config-before.toml'))) == 1


def test_foreign_registration_is_preserved(tmp_path):
    config = tmp_path / 'config.toml'
    config.write_text('[mcp_servers.balatro-agent]\ncommand="another-checkout"\n', encoding='utf-8')
    before = config.read_bytes()
    with pytest.raises(ValueError, match='differs'): onboarding.ensure_client(tmp_path, config)
    assert config.read_bytes() == before and not (tmp_path / '.artifacts').exists()


def test_equivalent_path_spellings_and_extra_settings_are_preserved(tmp_path):
    if os.name != 'nt': pytest.skip('Windows path equivalence')
    onboarding.ensure_client(tmp_path, tmp_path / 'config.toml')
    config = tmp_path / 'config.toml'
    original = config.read_text(encoding='utf-8')
    original = original.replace(json.dumps(str(tmp_path)), json.dumps(tmp_path.as_posix()))
    python = tmp_path / '.venv/Scripts/python.exe'
    original = original.replace(json.dumps(str(python)), json.dumps(python.as_posix()))
    original = original.replace('tool_timeout_sec = 45', 'tool_timeout_sec = 90')
    original += 'EXTRA_CLIENT_SETTING = "keep"\n'
    config.write_text(original, encoding='utf-8')
    before = config.read_bytes()
    onboarding.ensure_client(tmp_path, config)
    assert config.read_bytes() == before and onboarding.client_ready(tmp_path, config)


def test_game_detection_checks_steam_metadata_without_python(tmp_path):
    steam = tmp_path / 'Steam'; steam.mkdir(); (steam / 'steam.exe').write_bytes(b'fake')
    library = tmp_path / 'Library'; game = library / 'steamapps/common/Balatro'
    game.mkdir(parents=True); (game / 'Balatro.exe').write_bytes(b'fake')
    (library / 'steamapps/appmanifest_2379780.acf').write_text('"appid" "2379780"\n"installdir" "Balatro"', encoding='utf-8')
    result = run_helpers(tmp_path, {}, 'Find-SteamBalatro $root ' + quote(steam) + ' ' + quote(library) + ' | ConvertTo-Json')
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value == {'Steam': str(steam), 'Library': str(library)}
    assert not (tmp_path / '.tools').exists()


def test_missing_game_stops_before_bootstrap_download(tmp_path):
    if not PS: pytest.skip('Windows PowerShell')
    steam = tmp_path / 'Steam'; steam.mkdir(); (steam / 'steam.exe').write_bytes(b'fake')
    library = tmp_path / 'Library'; library.mkdir()
    result = subprocess.run([PS, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
        '-File', str(ROOT / 'scripts/setup.ps1'), '-Install', '-Automatic', '-Offline',
        '-SteamDir', str(steam), '-LibraryDir', str(library)], capture_output=True, text=True, errors='replace', timeout=30)
    assert result.returncode == 1 and 'No unique verified Steam Balatro' in result.stderr
    assert '1/4' not in result.stdout


@pytest.mark.parametrize('code', [0, 19])
def test_desktop_entry_handles_chinese_spaces_and_shell_punctuation(tmp_path, code):
    if not PS: pytest.skip('Windows batch launcher')
    root = tmp_path / '中文 path & bang!'; scripts = root / 'scripts'; scripts.mkdir(parents=True)
    entry = root / 'Balatro Agent.cmd'; shutil.copyfile(ROOT / entry.name, entry)
    (scripts / 'launcher.ps1').write_text(
        "[IO.File]::WriteAllText((Join-Path $PSScriptRoot '../called.txt'), $PSScriptRoot)\n" + f'exit {code}\n', encoding='ascii')
    command = f'"{os.environ["COMSPEC"]}" /d /v:off /s /c ""{entry}""'
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, errors='replace', timeout=30)
    assert result.returncode == code and (root / 'called.txt').read_text(encoding='utf-8') == str(scripts)


@pytest.mark.parametrize('reuse_exit', [0, 1, 2])
def test_automatic_bootstrap_orchestrates_one_prepare_and_reuses_early(tmp_path, reuse_exit):
    if not PS: pytest.skip('Windows PowerShell')
    root = tmp_path / '中文 project & bang!'; scripts = root / 'scripts'; scripts.mkdir(parents=True)
    steam = tmp_path / 'Steam'; steam.mkdir(); (steam / 'steam.exe').write_bytes(b'fake')
    library = tmp_path / 'Library'; game = library / 'steamapps/common/Balatro'
    game.mkdir(parents=True); (game / 'Balatro.exe').write_bytes(b'fake')
    (library / 'steamapps/appmanifest_2379780.acf').write_text('"appid" "2379780"\n"installdir" "Balatro"', encoding='utf-8')
    # An isolated interpreter stub shares only the installed stdlib, not a
    # copied dependency tree. No actual installer or uv process is executed.
    interpreter = root / '.venv/Scripts/python.exe'; interpreter.parent.mkdir(parents=True)
    shutil.copyfile(sys.executable, interpreter)
    (root / '.venv/pyvenv.cfg').write_text(f'home = {sys.base_prefix}\ninclude-system-site-packages = false\n', encoding='utf-8')
    (scripts / 'project.py').write_text(
        'import sys,json\nfrom pathlib import Path\n'
        'root=Path(__file__).resolve().parents[1]\n'
        '(root/"reuse-request.json").write_text(json.dumps(sys.argv[1:]),encoding="utf-8")\n'
        f'sys.exit({reuse_exit})\n', encoding='utf-8')
    config = root / 'config'; config.mkdir()
    shutil.copyfile(ROOT / 'config/dependencies.lock.json', config / 'dependencies.lock.json')
    source = (ROOT / 'scripts/setup.ps1').read_text(encoding='utf-8-sig')
    # Replace only execution helpers in this test copy. Exercise the actual
    # mode selection and automatic pipeline, with exact commands recorded.
    marker = "$scopedVariables = @('UV_PYTHON_INSTALL_DIR'"
    overrides = "function Install-LockedUv { return 'fixture-uv' }\n"
    overrides += "function Invoke-Checked([string]$Program,[string[]]$Arguments) { $Arguments | ConvertTo-Json -Compress | Add-Content -LiteralPath (Join-Path $PSScriptRoot '../requests.jsonl') -Encoding UTF8 }\n"
    assert marker in source
    source = source.replace(marker, overrides + marker, 1)
    entry = scripts / 'setup.ps1'; entry.write_text(source, encoding='utf-8-sig')
    environment = dict(os.environ); environment.pop('PYTHONPATH', None)
    result = subprocess.run([PS, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
        '-File', str(entry), '-Install', '-Automatic', '-Offline', '-SteamDir', str(steam),
        '-LibraryDir', str(library), '-PreparationId', 'fixture'], capture_output=True,
        text=True, encoding='utf-8', errors='replace', timeout=30, env=environment)
    args = json.loads((root / 'reuse-request.json').read_text(encoding='utf-8'))
    assert args[0] == 'prepare' and '--reuse-only' in args and 'fixture' in args
    if reuse_exit == 1:
        assert result.returncode == 1 and not (root / 'requests.jsonl').exists()
    elif reuse_exit == 0:
        assert result.returncode == 0 and not (root / 'requests.jsonl').exists()
    else:
        assert result.returncode == 0, result.stderr
        calls = [json.loads(row) for row in (root / 'requests.jsonl').read_text(encoding='utf-8-sig').splitlines()]
        assert len(calls) == 5
        assert sum('prepare' in args for args in calls) == 1
        assert all('install_portable.py' not in str(args) for args in calls)


@pytest.mark.parametrize('damage', ['id', 'not_prepared', 'tools', 'game_started'])
def test_window_cannot_accept_stale_or_incomplete_ready_receipt(tmp_path, damage):
    if not PS: pytest.skip('Windows PowerShell')
    receipt = {'schema':'automatic-preparation-1','preparation_id':'this-launch',
               'prepared':True,'stdio_tools_verified':11,'game_started':False}
    if damage == 'id': receipt['preparation_id'] = 'old-launch'
    if damage == 'not_prepared': receipt['prepared'] = False
    if damage == 'tools': receipt['stdio_tools_verified'] = 10
    if damage == 'game_started': receipt['game_started'] = True
    path = tmp_path / 'receipt.json'; path.write_text(json.dumps(receipt), encoding='utf-8')
    command = "$ErrorActionPreference='Stop';$tokens=$null;$errors=$null;"
    command += "$ast=[Management.Automation.Language.Parser]::ParseFile(" + quote(ROOT / 'scripts/launcher.ps1') + ",[ref]$tokens,[ref]$errors);"
    command += "if($errors.Count){throw 'Parse failed'};"
    command += "$ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Read-PreparationReceipt'},$true)|ForEach-Object{Invoke-Expression $_.Extent.Text};"
    command += 'Read-PreparationReceipt ' + quote(path) + " 'this-launch'"
    result = subprocess.run([PS, '-NoProfile', '-NonInteractive', '-Command', command],
        capture_output=True, text=True, errors='replace', timeout=30)
    assert result.returncode != 0 and 'does not match' in result.stderr


@pytest.mark.parametrize('case', ['ready', 'failed_worker', 'stale_receipt'])
def test_desktop_window_runs_helper_and_reaches_ready_with_matching_receipt(tmp_path, case):
    if not PS: pytest.skip('Windows Forms')
    root = tmp_path / '中文 desktop & bang!'; scripts = root / 'scripts'; scripts.mkdir(parents=True)
    prompts = root / 'prompts'; prompts.mkdir()
    (prompts / 'first-use.md').write_text('Read bootstrap and play. Report the result.', encoding='utf-8')
    interpreter = root / '.venv/Scripts/python.exe'; interpreter.parent.mkdir(parents=True)
    shutil.copyfile(sys.executable, interpreter)
    (root / '.venv/pyvenv.cfg').write_text(f'home = {sys.base_prefix}\ninclude-system-site-packages = false\n', encoding='utf-8')
    steam = tmp_path / 'Steam'; steam.mkdir(); (steam / 'steam.exe').write_bytes(b'fake')
    library = tmp_path / 'Library'; game = library / 'steamapps/common/Balatro'
    game.mkdir(parents=True); (game / 'Balatro.exe').write_bytes(b'fake')
    (library / 'steamapps/appmanifest_2379780.acf').write_text('"appid" "2379780"\n"installdir" "Balatro"', encoding='utf-8')
    config = root / 'config'; config.mkdir()
    (config / 'game-lifecycle.local.json').write_text(json.dumps({'steam_dir':str(steam),'library_dir':str(library)}), encoding='utf-8')
    shutil.copyfile(ROOT / 'scripts/setup.ps1', scripts / 'setup.ps1')
    # Only the maintenance worker is synthetic. Exercise the actual CMD-safe
    # desktop process creation, log redirects, timer and per-launch receipt.
    (scripts / 'project.py').write_text(
        'import sys,json\nfrom pathlib import Path\n'
        'root=Path(__file__).resolve().parents[1]; folder=root/".artifacts";folder.mkdir()\n'
        'proof={"schema":"automatic-preparation-1","preparation_id":sys.argv[sys.argv.index("--preparation-id")+1],"prepared":True,"stdio_tools_verified":11,"game_started":False}\n'
        + ('proof["preparation_id"]="old-launch"\n' if case == 'stale_receipt' else '')
        + '(folder/"onboarding.local.json").write_text(json.dumps(proof),encoding="utf-8")\n'
        + ('sys.exit(19)\n' if case == 'failed_worker' else ''), encoding='utf-8')
    source = (ROOT / 'scripts/launcher.ps1').read_text(encoding='utf-8-sig')
    hook = "$form.ShowInTaskbar=$false;$form.Opacity=0;"
    hook += "$fixtureTimer=New-Object Windows.Forms.Timer;$fixtureTimer.Interval=250;"
    hook += "$fixtureTimer.Add_Tick({if($script:process -and $script:process.HasExited -and $retry.Enabled -or $copy.Enabled){"
    hook += "$fixtureTimer.Stop();[IO.File]::WriteAllText((Join-Path $root 'window-result.txt'),$heading.Text+'|'+$copy.Enabled+'|'+$open.Enabled+'|'+$script:desktopError);$form.Close()}});$fixtureTimer.Start();"
    marker = '$form.ShowDialog() | Out-Null'
    assert source.count(marker) == 1
    source = source.replace(marker, hook + marker)
    entry = scripts / 'launcher.ps1'; entry.write_text(source, encoding='utf-8-sig')
    environment = dict(os.environ); environment.pop('PYTHONPATH', None)
    result = subprocess.run([PS, '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-File', str(entry)],
        capture_output=True, text=True, errors='replace', timeout=30, env=environment)
    value = (root / 'window-result.txt').read_text(encoding='utf-8')
    if case == 'ready':
        assert result.returncode == 0, result.stderr
        assert value == '准备完成，可以接入 AI|True|True|'
    else:
        assert result.returncode == 1
        assert value.startswith('准备暂未完成|False|False|')
