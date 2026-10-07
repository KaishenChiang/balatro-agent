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

function Write-PreparationProgress([string]$State, [string]$Component,
        [long]$Received = 0, [long]$Total = -1, [double]$Speed = 0, [int]$Attempt = 1) {
    if (-not $env:BALATRO_SETUP_PROGRESS) { return }
    $progressPath = $env:BALATRO_SETUP_PROGRESS
    Assert-NoReparse $progressPath
    $value = @{schema='preparation-progress-1';preparation_id=$env:BALATRO_SETUP_ID;
        stage=[int]$env:BALATRO_SETUP_STAGE;state=$State;component=$Component;
        received_bytes=$Received;total_bytes=$Total;bytes_per_second=$Speed;attempt=$Attempt;
        utc=[DateTime]::UtcNow.ToString('o')}
    $temporary = $progressPath + '.' + [Guid]::NewGuid().ToString('N') + '.tmp'
    [IO.File]::WriteAllText($temporary, ($value | ConvertTo-Json -Compress), [Text.UTF8Encoding]::new($false))
    if ([IO.File]::Exists($progressPath)) { [IO.File]::Replace($temporary, $progressPath, [NullString]::Value) }
    else { [IO.File]::Move($temporary, $progressPath) }
}

function Receive-LockedArchive($Item, [string]$Path, [int]$TimeoutSeconds = 20, [int]$Retries = 1) {
    Assert-NoReparse $Path
    $uri = [Uri]$Item.url
    if ($uri.Scheme -ne 'https' -and -not ($uri.Scheme -eq 'http' -and $uri.IsLoopback)) {
        throw 'Only HTTPS dependency downloads are allowed.'
    }
    if ($TimeoutSeconds -lt 1 -or $TimeoutSeconds -gt 60 -or $Retries -lt 0 -or $Retries -gt 2) {
        throw 'Invalid bounded download options.'
    }
    $component = [IO.Path]::GetFileName($Path)
    $directory = [IO.Path]::GetDirectoryName($Path)
    $prefix = [regex]::Escape($component) + '\.[a-f0-9]{32}\.part$'
    $partials = @(Get-ChildItem -LiteralPath $directory -File | Where-Object {
        $_.Name -match ('^' + $prefix) -and $_.Length -gt 0 -and $_.Length -le 150000000
    } | Sort-Object Length -Descending)
    $resume = if ($partials.Count) { $partials[0].FullName } else { $null }
    for ($attempt = 1; $attempt -le $Retries + 1; $attempt++) {
        $temporary = $Path + '.' + [Guid]::NewGuid().ToString('N') + '.part'
        Assert-NoReparse $temporary
        $offset = 0L
        if ($resume) {
            # A prefix is untrusted. Preserve the original, append only to a
            # new copy, and require the complete fixed hash before execution.
            Assert-NoReparse $resume
            [IO.File]::Copy($resume, $temporary, $false)
            $offset = (Get-Item -LiteralPath $temporary).Length
            if ((Get-Sha256 $temporary) -eq $Item.sha256) {
                [IO.File]::Move($temporary, $Path)
                return
            }
        }
        $response = $null; $inputStream = $null; $outputStream = $null
        $clock = [Diagnostics.Stopwatch]::StartNew()
        $request = [Net.HttpWebRequest]::Create($uri)
        # HttpWebRequest uses Windows' configured proxy by default. An
        # explicit process proxy takes precedence; no system settings change.
        if ($uri.IsLoopback) { $request.Proxy = $null }
        elseif ($env:HTTPS_PROXY) { $request.Proxy = New-Object Net.WebProxy -ArgumentList $env:HTTPS_PROXY }
        $request.Timeout = $TimeoutSeconds * 1000
        $request.ReadWriteTimeout = $TimeoutSeconds * 1000
        $request.UserAgent = 'balatro-agent-first-use'
        if ($offset -gt 0) { $request.AddRange($offset) }
        Write-PreparationProgress 'connecting' $component $offset -1 0 $attempt
        try {
            $response = $request.GetResponse()
            if ($uri.Scheme -eq 'https' -and $response.ResponseUri.Scheme -ne 'https') {
                throw 'Dependency redirect must remain HTTPS.'
            }
            $total = [long]$response.ContentLength
            if ($offset -gt 0 -and [int]$response.StatusCode -eq 206) {
                $range = [regex]::Match($response.Headers['Content-Range'], '^bytes (\d+)-(\d+)/(\d+)$')
                if (-not $range.Success -or [long]$range.Groups[1].Value -ne $offset) {
                    throw 'Invalid resumed download range; original partial retained.'
                }
                $total = [long]$range.Groups[3].Value
            } elseif ($offset -gt 0) {
                # A server may ignore Range. Start a new file, never concatenate
                # a complete response with the old prefix or overwrite it.
                $temporary = $Path + '.' + [Guid]::NewGuid().ToString('N') + '.part'
                Assert-NoReparse $temporary
                $offset = 0L
            }
            if ($total -gt 150000000) { throw 'Download size limit exceeded; partial file retained.' }
            $inputStream = $response.GetResponseStream()
            $mode = if ($offset -gt 0) { [IO.FileMode]::Append } else { [IO.FileMode]::CreateNew }
            $outputStream = [IO.File]::Open($temporary, $mode, [IO.FileAccess]::Write, [IO.FileShare]::Read)
            $buffer = New-Object byte[] 65536
            $received = $offset
            $lastUpdate = -1.0
            $windowStart = 0.0; $windowBytes = $offset
            while (($count = $inputStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                $received += $count
                if ($received -gt 150000000) { throw 'Download size limit exceeded; partial file retained.' }
                $outputStream.Write($buffer, 0, $count)
                $elapsed = $clock.Elapsed.TotalSeconds
                if ($elapsed -gt 600) { throw 'Download exceeded 10 minutes; partial file retained for retry.' }
                if ($elapsed - $windowStart -ge 30) {
                    if (($received - $windowBytes) / ($elapsed - $windowStart) -lt 1024) {
                        throw 'Download stalled below 1 KB/s; partial file retained for retry.'
                    }
                    $windowStart = $elapsed; $windowBytes = $received
                }
                if ($elapsed - $lastUpdate -ge 0.3) {
                    $outputStream.Flush()
                    Write-PreparationProgress 'downloading' $component $received $total (($received - $offset) / [Math]::Max(0.1, $elapsed)) $attempt
                    $lastUpdate = $elapsed
                }
            }
            $outputStream.Flush($true); $outputStream.Dispose(); $outputStream = $null
            if ($total -ge 0 -and $received -ne $total) { throw 'Incomplete download; partial file retained for retry.' }
            Write-PreparationProgress 'verifying' $component $received $total 0 $attempt
            if ((Get-Sha256 $temporary) -ne $Item.sha256) {
                throw 'Archive hash mismatch; partial file retained. Nothing downloaded is executed.'
            }
            Assert-NoReparse $Path
            if ([IO.File]::Exists($Path)) { throw 'Archive appeared during download; preserve it.' }
            [IO.File]::Move($temporary, $Path)
            return
        } catch {
            $failure = $_
            if ($attempt -gt $Retries -or $failure.Exception.Message -match 'hash mismatch|size limit|redirect|range|appeared') { throw }
            $resume = if ([IO.File]::Exists($temporary)) { $temporary } else { $resume }
            Write-PreparationProgress 'retrying' $component 0 -1 0 ($attempt + 1)
            Write-Host ('Retrying download: ' + $component + ' (attempt ' + ($attempt + 1) + '). Partial files are retained.')
        } finally {
            if ($outputStream) { $outputStream.Dispose() }
            if ($inputStream) { $inputStream.Dispose() }
            if ($response) { $response.Dispose() }
            $request.Abort(); $clock.Stop()
        }
    }
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
    $bundled = Join-Path (Join-Path $Root 'vendor') $Item.archive
    Assert-NoReparse $bundled
    if (Test-Path -LiteralPath $bundled) {
        if ((Get-Sha256 $bundled) -ne $Item.sha256) { throw 'Bundled uv archive hash mismatch; original retained.' }
        if (-not (Test-Path -LiteralPath $archive)) {
            [IO.Directory]::CreateDirectory($cache) | Out-Null
            [IO.File]::Copy($bundled, $archive, $false)
        }
    }
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

function Install-LockedRuntime([string]$Root, [bool]$UseOffline) {
    # The bundle contains original upstream archives and wheels, never a copied
    # venv or machine configuration. Verify the complete plan before extraction.
    $manifestPath = Join-Path $Root 'config/runtime.lock.json'
    Assert-NoReparse $manifestPath
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { return $null }
    $componentLock = Join-Path $Root 'config/dependencies.lock.json'
    Assert-NoReparse $componentLock
    $link = (Get-Content -LiteralPath $componentLock -Raw -Encoding UTF8 | ConvertFrom-Json).offline_runtime
    if ($link.manifest -ne 'config/runtime.lock.json' -or $link.sha256 -ne (Get-Sha256 $manifestPath)) {
        throw 'Bundled runtime manifest differs from the component lock.'
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.schema -ne 'balatro-offline-runtime-1' -or $manifest.platform -ne 'windows-x86_64' -or
        $manifest.python_version -ne '3.13.11' -or $manifest.uv_version -ne '0.9.21' -or
        $manifest.archive -ne 'runtime-windows-x64.zip' -or $manifest.sha256 -notmatch '^[a-f0-9]{64}$' -or
        $manifest.uv_lock_sha256 -ne (Get-Sha256 (Join-Path $Root 'uv.lock'))) {
        throw 'Bundled runtime lock differs from this project.'
    }
    $archive = Join-Path (Join-Path $Root 'vendor') $manifest.archive
    Assert-NoReparse $archive
    if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) {
        if ($UseOffline) { throw 'Bundled runtime absent; offline setup stopped.' }
        return $null
    }
    Write-PreparationProgress 'verifying' 'Python + MCP'
    if ((Get-Sha256 $archive) -ne $manifest.sha256) { throw 'Bundled runtime hash mismatch; original retained.' }
    $expected = @{}
    $records = @($manifest.python) + @($manifest.wheels)
    if ($records.Count -lt 2 -or $records.Count -gt 80 -or $manifest.python.path -ne
        'python/20251217/cpython-3.13.11+20251217-x86_64-pc-windows-msvc-install_only_stripped.tar.gz') {
        throw 'Unexpected bundled runtime members.'
    }
    foreach ($item in $records) {
        $relative = [string]$item.path
        if ($relative -match '(^/|\\|:|\x00|(^|/)\.\.(/|$))' -or $expected.ContainsKey($relative) -or
            $item.sha256 -notmatch '^[a-f0-9]{64}$' -or $item.bytes -le 0 -or $item.bytes -gt 150000000 -or
            ($relative -ne $manifest.python.path -and $relative -notmatch '^wheels/[^/]+\.whl$')) {
            throw 'Unsafe bundled runtime member.'
        }
        if ($relative -ne $manifest.python.path -and
            ($item.name -notmatch '^[a-z0-9][a-z0-9-]*$' -or $item.version -notmatch '^[a-zA-Z0-9][a-zA-Z0-9.+!-]*$')) {
            throw 'Invalid bundled wheel requirement.'
        }
        $expected[$relative] = $item
    }
    $destination = Join-Path $Root '.artifacts/offline-runtime'
    Assert-NoReparse $destination
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $bundle = [IO.Compression.ZipFile]::OpenRead($archive)
    try {
        if ($bundle.Entries.Count -ne $records.Count) { throw 'Bundled runtime member list differs.' }
        $plans = @(); $seen = @{}; [long]$size = 0
        foreach ($entry in $bundle.Entries) {
            if (-not $expected.ContainsKey($entry.FullName) -or $seen.ContainsKey($entry.FullName)) {
                throw 'Unregistered bundled runtime member.'
            }
            $seen[$entry.FullName] = $true; $item = $expected[$entry.FullName]; $size += $entry.Length
            if ($entry.Length -ne $item.bytes -or $size -gt 150000000) { throw 'Bundled runtime size differs.' }
            $target = Join-Path $destination $entry.FullName
            Assert-NoReparse $target
            $stream = $entry.Open(); $hash = [Security.Cryptography.SHA256]::Create()
            try { $actual = [BitConverter]::ToString($hash.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
            finally { $stream.Dispose(); $hash.Dispose() }
            if ($actual -ne $item.sha256) { throw 'Bundled runtime member hash mismatch.' }
            if ((Test-Path -LiteralPath $target) -and (Get-Sha256 $target) -ne $item.sha256) {
                throw 'Existing extracted runtime differs; preserve and inspect it.'
            }
            $plans += @{ Entry = $entry; Target = $target; Sha256 = $item.sha256 }
        }
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
            if ((Get-Sha256 $plan.Target) -ne $plan.Sha256) { throw 'Extracted runtime hash mismatch.' }
        }
    } finally { $bundle.Dispose() }
    $requirements = Join-Path $destination 'requirements.txt'
    Assert-NoReparse $requirements
    $lines = @($manifest.wheels | ForEach-Object { $_.name + '==' + $_.version + ' --hash=sha256:' + $_.sha256 })
    $text = ($lines -join "`n") + "`n"
    if (Test-Path -LiteralPath $requirements) {
        if ([IO.File]::ReadAllText($requirements) -cne $text) { throw 'Existing bundled requirements differ; original retained.' }
    } else { [IO.File]::WriteAllText($requirements, $text, (New-Object Text.UTF8Encoding($false))) }
    return @{ Mirror = ([Uri](Join-Path $destination 'python')).AbsoluteUri;
              Wheels = (Join-Path $destination 'wheels'); Requirements = $requirements }
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

$scopedVariables = @('UV_PYTHON_INSTALL_DIR', 'UV_PROJECT_ENVIRONMENT', 'UV_PYTHON_CACHE_DIR',
    'UV_PYTHON_DOWNLOADS_JSON_URL',
    'UV_HTTP_TIMEOUT', 'UV_HTTP_RETRIES', 'HTTPS_PROXY', 'BALATRO_SETUP_PROGRESS', 'BALATRO_SETUP_ID', 'BALATRO_SETUP_STAGE')
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
        if (-not $PreparationId) { $PreparationId = [Guid]::NewGuid().ToString('N') }
        if ($PreparationId -notmatch '^[A-Za-z0-9_-]{1,80}$') { throw 'A safe preparation ID is required.' }
        [IO.Directory]::CreateDirectory((Join-Path $root '.artifacts')) | Out-Null
        $env:BALATRO_SETUP_ID = $PreparationId
        $env:BALATRO_SETUP_PROGRESS = Join-Path $root ('.artifacts/preparation-' + $PreparationId + '.progress.json')
        $env:BALATRO_SETUP_STAGE = '0'
        Write-PreparationProgress 'working' 'game'
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
    # Mirror only an already-configured Windows proxy into this worker for
    # uv, which otherwise receives no Explorer-launched shell proxy setting.
    if (-not $env:HTTPS_PROXY -and [Net.WebRequest]::DefaultWebProxy) {
        $target = [Uri]'https://github.com/'
        $configuredProxy = [Net.WebRequest]::DefaultWebProxy.GetProxy($target)
        if ($configuredProxy -and $configuredProxy -ne $target) { $env:HTTPS_PROXY = $configuredProxy.AbsoluteUri }
    }
    if (-not $env:UV_HTTP_TIMEOUT) { $env:UV_HTTP_TIMEOUT = '30' }
    if (-not $env:UV_HTTP_RETRIES) { $env:UV_HTTP_RETRIES = '1' }
    $env:BALATRO_SETUP_STAGE = '1'; Write-PreparationProgress 'working' 'uv'
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
    $env:BALATRO_SETUP_STAGE = '2'; Write-PreparationProgress 'working' 'Python 3.13.11'
    Write-Host '2/4 Prepare project-local Python 3.13.11 and locked runtime dependencies.'
    $runtime = Install-LockedRuntime $root ([bool]$Offline)
    $pythonArgs = @('python', 'install', '3.13.11', '--install-dir', $pythonDir, '--no-bin', '--no-registry', '--cache-dir', $uvCache)
    $syncArgs = @('sync', '--directory', $root, '--cache-dir', $uvCache, '--locked', '--python', '3.13.11', '--managed-python', '--no-dev', '--link-mode', 'copy')
    if ($runtime) {
        Write-Host 'Using bundled Python and runtime wheels; no network download needed.'
        # uv 0.9.21 --offline refuses even uncached file:// archives. A verified
        # local mirror with built-in metadata and --no-config reads only this
        # checkout. Disable a custom metadata URL in this worker, then restore it.
        [Environment]::SetEnvironmentVariable('UV_PYTHON_DOWNLOADS_JSON_URL', $null, 'Process')
        $pythonArgs += @('--mirror', $runtime.Mirror, '--no-config')
        # find-links on `uv sync` changes resolution sources and re-resolves all
        # groups. Install the hash-locked wheels first, then sync with unchanged
        # registry settings and the pinned local build backend already present.
        $syncArgs += @('--offline', '--no-build-isolation')
    } else { $pythonArgs += $offlineArgs; $syncArgs += $offlineArgs }
    Invoke-Checked $uv $pythonArgs
    if ($runtime) {
        $python = Join-Path $venv 'Scripts/python.exe'
        Assert-NoReparse $python
        if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
            Invoke-Checked $uv @('venv', $venv, '--python', '3.13.11', '--managed-python', '--no-python-downloads', '--offline', '--cache-dir', $uvCache)
        }
        Invoke-Checked $uv @('pip', 'install', '--python', $python, '--require-hashes', '--no-deps', '--no-index',
            '--find-links', $runtime.Wheels, '--offline', '--cache-dir', $uvCache, '--link-mode', 'copy', '-r', $runtime.Requirements)
    }
    Invoke-Checked $uv $syncArgs
    $python = Join-Path $venv 'Scripts/python.exe'
    $env:BALATRO_SETUP_STAGE = '3'; Write-PreparationProgress 'working' 'Mod'
    Write-Host '3/4 Verify the bundled or cached Mod sources.'
    Invoke-Checked $python (@((Join-Path $root 'scripts/bootstrap_sources.py')) + $offlineArgs)
    if ($DependenciesOnly) {
        Write-Host 'Dependencies prepared. Steam, Mods, client config and profiles were not changed.'
    } else {
        $env:BALATRO_SETUP_STAGE = '4'; Write-PreparationProgress 'working' 'MCP'
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
