# First-use Windows bootstrap. No preinstalled Python, PATH edit or game launch.
[CmdletBinding()]
param(
    [switch]$Install,
    [switch]$Automatic,
    [string]$PreparationId,
    [switch]$Apply,
    [switch]$DependenciesOnly,
    [switch]$Offline,
    [string]$SteamDir,
    [string]$LibraryDir,
    [string]$ModsDir,
    [string]$CodexConfig
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-NoReparse([string]$Path) {
    $probe = [IO.Path]::GetFullPath($Path)
    while ($probe) {
        $entry = Get-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue
        if ($entry -and ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Links/reparse points are not accepted; existing files are preserved.'
        }
        $probe = [IO.Path]::GetDirectoryName($probe)
    }
}

function Get-Sha256([string]$Path) {
    Assert-NoReparse $Path
    $stream = [IO.File]::OpenRead($Path)
    $hash = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($hash.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $stream.Dispose(); $hash.Dispose() }
}

function Receive-LockedArchive($Item, [string]$Path) {
    Assert-NoReparse $Path
    $temporary = $Path + '.' + [Guid]::NewGuid().ToString('N') + '.part'
    $nativeCurl = Join-Path $env:SystemRoot 'System32/curl.exe'
    if ($Item.url.StartsWith('https://') -and (Test-Path -LiteralPath $nativeCurl)) {
        # Windows curl honors HTTPS_PROXY; WebRequest can miss a shell proxy.
        # Use the OS executable, HTTPS redirects only, and normal TLS checks.
        Assert-NoReparse $temporary
        $created = [IO.File]::Open($temporary, [IO.FileMode]::CreateNew)
        $created.Dispose()
        & $nativeCurl --fail --location --silent --show-error --proto '=https' --proto-redir '=https' --connect-timeout 30 --max-time 600 --max-filesize 150000000 --output $temporary $Item.url
        if ($LASTEXITCODE -ne 0) { throw 'HTTPS download failed; partial file retained.' }
        if ((Get-Item -LiteralPath $temporary).Length -gt 150000000 -or (Get-Sha256 $temporary) -ne $Item.sha256) {
            throw 'Archive hash or size mismatch; partial file retained. Nothing downloaded is executed.'
        }
        Assert-NoReparse $Path
        [IO.File]::Move($temporary, $Path)
        return
    }
    $request = [Net.WebRequest]::Create($Item.url)
    if ($env:HTTPS_PROXY -and $Item.url.StartsWith('https://')) {
        $request.Proxy = New-Object Net.WebProxy -ArgumentList $env:HTTPS_PROXY
    }
    $request.Timeout = 30000
    $request.ReadWriteTimeout = 30000
    $request.UserAgent = 'balatro-agent-first-use'
    $response = $null; $inputStream = $null; $outputStream = $null
    try {
        $response = $request.GetResponse()
        $inputStream = $response.GetResponseStream()
        $outputStream = [IO.File]::Open($temporary, [IO.FileMode]::CreateNew)
        $buffer = New-Object byte[] (1024 * 1024)
        $total = 0
        while (($count = $inputStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
            $total += $count
            if ($total -gt 150000000) { throw 'Download size limit exceeded; partial file retained.' }
            $outputStream.Write($buffer, 0, $count)
        }
        $outputStream.Flush($true)
    } finally {
        if ($outputStream) { $outputStream.Dispose() }
        if ($inputStream) { $inputStream.Dispose() }
        if ($response) { $response.Dispose() }
    }
    if ((Get-Sha256 $temporary) -ne $Item.sha256) {
        throw 'Archive hash mismatch; partial file retained. Nothing downloaded is executed.'
    }
    Assert-NoReparse $Path
    [IO.File]::Move($temporary, $Path)
}

function Install-LockedUv([string]$Root, $Item, [bool]$UseOffline) {
    # Restrict the bootstrap to the one locked Windows distribution.
    if ($Item.version -ne '0.9.21' -or $Item.archive -ne 'uv-0.9.21.zip' -or
        $Item.url -ne 'https://github.com/astral-sh/uv/releases/download/0.9.21/uv-x86_64-pc-windows-msvc.zip' -or
        $Item.sha256 -notmatch '^[a-f0-9]{64}$' -or $Item.destination -ne '.tools/uv') {
        throw 'Unexpected uv bootstrap lock.'
    }
    Assert-NoReparse $Root
    $cache = Join-Path $Root '.artifacts/sources'
    $archive = Join-Path $cache $Item.archive
    Assert-NoReparse $archive
    if (-not (Test-Path -LiteralPath $archive)) {
        if ($UseOffline) { throw 'Pinned uv archive absent from cache; offline setup stopped.' }
        [IO.Directory]::CreateDirectory($cache) | Out-Null
        Receive-LockedArchive $Item $archive
    }
    if ((Get-Sha256 $archive) -ne $Item.sha256) {
        throw 'Cached uv archive hash mismatch; original retained.'
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $bundle = [IO.Compression.ZipFile]::OpenRead($archive)
    try {
        $allowed = @('uv.exe', 'uvw.exe', 'uvx.exe')
        $names = @($bundle.Entries | ForEach-Object { $_.FullName })
        if ($names.Count -ne 3 -or (Compare-Object ($allowed | Sort-Object) ($names | Sort-Object))) {
            throw 'Unexpected uv archive entries.'
        }
        $plans = @()
        foreach ($entry in $bundle.Entries) {
            if ($entry.Length -le 0 -or $entry.Length -gt 150000000) { throw 'Invalid uv entry size.' }
            $target = Join-Path (Join-Path $Root '.tools/uv') $entry.FullName
            Assert-NoReparse $target
            $stream = $entry.Open(); $hash = [Security.Cryptography.SHA256]::Create()
            try { $expected = [BitConverter]::ToString($hash.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
            finally { $stream.Dispose(); $hash.Dispose() }
            if ((Test-Path -LiteralPath $target) -and (Get-Sha256 $target) -ne $expected) {
                throw 'Existing uv executable differs; preserve and inspect it.'
            }
            $plans += @{ Entry = $entry; Target = $target; Sha256 = $expected }
        }
        # Preflight every existing executable before adding any files.
        foreach ($plan in $plans) {
            Assert-NoReparse $plan.Target
            if (-not (Test-Path -LiteralPath $plan.Target)) {
                [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($plan.Target)) | Out-Null
                $source = $plan.Entry.Open(); $dest = $null
                try {
                    $dest = [IO.File]::Open($plan.Target, [IO.FileMode]::CreateNew)
                    $source.CopyTo($dest); $dest.Flush($true)
                } finally {
                    $source.Dispose()
                    if ($dest) { $dest.Dispose() }
                }
            }
            if ((Get-Sha256 $plan.Target) -ne $plan.Sha256) { throw 'Installed uv hash mismatch.' }
        }
    } finally { $bundle.Dispose() }
    return (Join-Path $Root '.tools/uv/uv.exe')
}

function Invoke-Checked([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw ('Setup stopped: ' + [IO.Path]::GetFileName($Program) + ' exit ' + $LASTEXITCODE) }
}

function Find-SteamBalatro([string]$Root, [string]$GivenSteam, [string]$GivenLibrary) {
    $locations = @()
    $local = Join-Path $Root 'config/game-lifecycle.local.json'
    if ($GivenSteam -and $GivenLibrary) {
        $locations += @{Steam=$GivenSteam; Libraries=@($GivenLibrary)}
    } elseif (Test-Path -LiteralPath $local) {
        Assert-NoReparse $local
        if ((Get-Item -LiteralPath $local).Length -gt 8192) { throw 'Invalid local installation metadata.' }
        $saved = Get-Content -LiteralPath $local -Raw -Encoding UTF8 | ConvertFrom-Json
        $locations += @{Steam=$saved.steam_dir; Libraries=@($saved.library_dir)}
    } else {
        foreach ($registry in @(@('HKCU:\Software\Valve\Steam','SteamPath'), @('HKLM:\Software\Valve\Steam','InstallPath'), @('HKLM:\Software\WOW6432Node\Valve\Steam','InstallPath'))) {
            $value = Get-ItemProperty -LiteralPath $registry[0] -Name $registry[1] -ErrorAction SilentlyContinue
            if (-not $value) { continue }
            $steamPath = [string]$value.($registry[1])
            $libraries = @($steamPath)
            $folders = Join-Path $steamPath 'steamapps/libraryfolders.vdf'
            Assert-NoReparse $folders
            if (Test-Path -LiteralPath $folders) {
                if ((Get-Item -LiteralPath $folders).Length -gt 262144) { throw 'Invalid Steam library metadata.' }
                $text = Get-Content -LiteralPath $folders -Raw -Encoding UTF8
                foreach ($match in [regex]::Matches($text, '"path"\s*"([^"\r\n]*)"')) {
                    $libraries += $match.Groups[1].Value.Replace('\\','\')
                }
            }
            $locations += @{Steam=$steamPath; Libraries=$libraries}
        }
    }
    $found = @{}
    foreach ($location in $locations) {
        $steamExe = Join-Path $location.Steam 'steam.exe'
        Assert-NoReparse $steamExe
        if (-not (Test-Path -LiteralPath $steamExe -PathType Leaf)) { continue }
        foreach ($library in $location.Libraries) {
            $manifest = Join-Path $library 'steamapps/appmanifest_2379780.acf'
            Assert-NoReparse $manifest
            if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) { continue }
            if ((Get-Item -LiteralPath $manifest).Length -gt 65536) { throw 'Invalid Balatro installation metadata.' }
            $text = Get-Content -LiteralPath $manifest -Raw -Encoding UTF8
            $app = [regex]::Matches($text, '"appid"\s*"([^"\r\n]*)"')
            $folder = [regex]::Matches($text, '"installdir"\s*"([^"\r\n]*)"')
            if ($app.Count -ne 1 -or $app[0].Groups[1].Value -ne '2379780' -or $folder.Count -ne 1) { continue }
            $name = $folder[0].Groups[1].Value
            if (-not $name -or $name -in @('.','..') -or $name -match '[/\\:\x00-\x1f]') { throw 'Invalid Balatro installation directory.' }
            $game = Join-Path $library ('steamapps/common/' + $name + '/Balatro.exe')
            Assert-NoReparse $game
            if (Test-Path -LiteralPath $game -PathType Leaf) {
                $key = [IO.Path]::GetFullPath($game).ToLowerInvariant()
                $found[$key] = @{Steam=[IO.Path]::GetFullPath($location.Steam); Library=[IO.Path]::GetFullPath($library)}
            }
        }
    }
    if ($found.Count -ne 1) { throw 'No unique verified Steam Balatro installation. Install Balatro with Steam, or supply its Steam/library directories.' }
    return @($found.Values)[0]
}

$scopedVariables = @('UV_PYTHON_INSTALL_DIR', 'UV_PROJECT_ENVIRONMENT', 'UV_PYTHON_CACHE_DIR')
$previous = @{}
foreach ($name in $scopedVariables) { $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
$previousTls = [Net.ServicePointManager]::SecurityProtocol
try {
    if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitOperatingSystem -or
        $env:PROCESSOR_ARCHITECTURE -eq 'ARM64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') {
        throw 'This setup entrypoint supports Windows x64 only.'
    }
    if (($SteamDir -and -not $LibraryDir) -or ($LibraryDir -and -not $SteamDir)) {
        throw 'Supply both -SteamDir and -LibraryDir, or neither for automatic detection.'
    }
    if ($Install -and $Apply) {
        throw 'Choose -Install for one-step setup or -Apply for a previously prepared plan.'
    }
    if ($Automatic -and -not $Install) { throw '-Automatic requires -Install.' }
    if ($PreparationId -and -not $Automatic) { throw '-PreparationId requires -Automatic.' }
    if ($DependenciesOnly -and ($Install -or $Apply -or $SteamDir -or $LibraryDir -or $ModsDir -or $CodexConfig)) {
        throw '-DependenciesOnly cannot be combined with installation options.'
    }
    $root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    Assert-NoReparse $root
    if ($Automatic) {
        Write-Host '0/4 Check the Steam Balatro installation and reusable preparation.'
        $detected = Find-SteamBalatro $root $SteamDir $LibraryDir
        $SteamDir = $detected.Steam; $LibraryDir = $detected.Library
        $prepareArgs = @((Join-Path $root 'scripts/project.py'), 'prepare', '--steam-dir', $SteamDir, '--library-dir', $LibraryDir)
        foreach ($pair in @(@('--mods-dir', $ModsDir), @('--codex-config', $CodexConfig), @('--preparation-id', $PreparationId))) {
            if ($pair[1]) { $prepareArgs += $pair }
        }
        $preparedPython = Join-Path $root '.venv/Scripts/python.exe'
        Assert-NoReparse $preparedPython
        if (Test-Path -LiteralPath $preparedPython -PathType Leaf) {
            & $preparedPython @prepareArgs --reuse-only
            $reuseExit = $LASTEXITCODE
            if ($reuseExit -eq 0) { Write-Host 'Prepared: reused verified installation. No downloads or installation needed.'; return }
            if ($reuseExit -ne 2) { throw 'Reuse verification stopped; preserve the output, installation and checkpoints.' }
        }
        if (@(Get-Process -Name Balatro -ErrorAction SilentlyContinue).Count) {
            throw 'Close Balatro normally, then open Balatro Agent again.'
        }
    }
    $lockPath = Join-Path $root 'config/dependencies.lock.json'
    Assert-NoReparse $lockPath
    $lock = Get-Content -LiteralPath $lockPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $uvItems = @($lock.sources | Where-Object { $_.name -eq 'uv' })
    if ($uvItems.Count -ne 1) { throw 'A unique uv bootstrap lock is required.' }
    [Net.ServicePointManager]::SecurityProtocol = $previousTls -bor [Net.SecurityProtocolType]::Tls12
    Write-Host '1/4 Verify pinned uv (no preinstalled Python required).'
    $uv = Install-LockedUv $root $uvItems[0] ([bool]$Offline)
    $pythonDir = Join-Path $root '.tools/python'
    $venv = Join-Path $root '.venv'
    $pythonCache = Join-Path $root '.artifacts/python-cache'
    $uvCache = Join-Path $root '.artifacts/uv-cache'
    foreach ($path in @($pythonDir, $venv, $pythonCache, $uvCache)) { Assert-NoReparse $path }
    $env:UV_PYTHON_INSTALL_DIR = $pythonDir
    $env:UV_PROJECT_ENVIRONMENT = $venv
    $env:UV_PYTHON_CACHE_DIR = $pythonCache
    $offlineArgs = @(); if ($Offline) { $offlineArgs = @('--offline') }
    Write-Host '2/4 Prepare project-local Python 3.13.11 and locked runtime dependencies.'
    Invoke-Checked $uv (@('python', 'install', '3.13.11', '--install-dir', $pythonDir, '--no-bin', '--no-registry', '--cache-dir', $uvCache) + $offlineArgs)
    Invoke-Checked $uv (@('sync', '--directory', $root, '--cache-dir', $uvCache, '--locked', '--python', '3.13.11', '--managed-python', '--no-dev') + $offlineArgs)
    $python = Join-Path $venv 'Scripts/python.exe'
    Write-Host '3/4 Download and verify the locked Mod sources.'
    Invoke-Checked $python (@((Join-Path $root 'scripts/bootstrap_sources.py')) + $offlineArgs)
    if ($DependenciesOnly) {
        Write-Host 'Dependencies prepared. Steam, Mods, client config and profiles were not changed.'
    } else {
        Write-Host '4/4 Build Mod and prepare/install the native Steam connection.'
        Invoke-Checked $python @((Join-Path $root 'scripts/build_mod.py'))
        if ($Automatic) {
            Invoke-Checked $python $prepareArgs
            Write-Host 'Prepared. Open Codex and send the short play prompt.'
            return
        }
        $installArgs = @((Join-Path $root 'scripts/install_portable.py'))
        foreach ($pair in @(@('--steam-dir', $SteamDir), @('--library-dir', $LibraryDir), @('--mods-dir', $ModsDir), @('--codex-config', $CodexConfig))) {
            if ($pair[1]) { $installArgs += $pair }
        }
        if ($Install) {
            # Freeze the normal plan, then apply that exact plan with all of
            # the existing drift, pending-action, backup and conflict checks.
            Invoke-Checked $python $installArgs
            Invoke-Checked $python ($installArgs + @('--apply'))
        } else {
            if ($Apply) { $installArgs += '--apply' }
            Invoke-Checked $python $installArgs
        }
        if ($Install -or $Apply) {
            Write-Host 'Installed. Reload the MCP client if needed, then use the current native game profile. No game was started.'
        } else {
            Write-Host 'Plan only: inspect .artifacts/portable-plan.local.json and portable-config-candidate.local.toml, then repeat with -Apply.'
        }
    }
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
} finally {
    foreach ($name in $scopedVariables) { [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process') }
    [Net.ServicePointManager]::SecurityProtocol = $previousTls
}
