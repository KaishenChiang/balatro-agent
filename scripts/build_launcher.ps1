# Build only this project's small WinExe, using Windows' existing .NET compiler.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
function Get-Digest([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { [BitConverter]::ToString($hasher.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $stream.Dispose(); $hasher.Dispose() }
}
function Assert-Plain([string]$Path) {
    $probe = [IO.Path]::GetFullPath($Path)
    while ($probe) {
        $item = Get-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue
        if ($item -and ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Launcher build does not follow links.' }
        $probe = [IO.Path]::GetDirectoryName($probe)
    }
}
Assert-Plain $root
$source = Join-Path $root 'windows/Launcher.cs'
$appManifest = Join-Path $root 'windows/app.manifest'
$output = Join-Path $root 'Balatro Agent.exe'
$receiptPath = Join-Path $root 'windows/launcher-build.json'
foreach ($path in @($source, $appManifest, $output, $receiptPath)) { Assert-Plain $path }
$ownedHash = $null
if (Test-Path -LiteralPath $output) {
    if (-not (Test-Path -LiteralPath $receiptPath)) { throw 'Existing executable has no build receipt; preserve it.' }
    $previous = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $ownedHash = Get-Digest $output
    if ($ownedHash -ne $previous.sha256) { throw 'Existing executable differs from its build receipt; preserve it.' }
}
$compiler = Join-Path $env:SystemRoot 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw 'Windows .NET Framework C# compiler is unavailable.' }
$build = Join-Path $root ('.artifacts/launcher-build/' + [Guid]::NewGuid().ToString('N'))
Assert-Plain $build
[IO.Directory]::CreateDirectory($build) | Out-Null
$candidate = Join-Path $build 'Balatro Agent.exe'
$iconPath = Join-Path $build 'app.ico'
Add-Type -AssemblyName System.Drawing
Add-Type 'using System; using System.Runtime.InteropServices; public static class LauncherIconHandle { [DllImport("user32.dll")] public static extern bool DestroyIcon(IntPtr handle); }'
$bitmap = New-Object Drawing.Bitmap(64, 64)
$graphics = [Drawing.Graphics]::FromImage($bitmap)
$graphics.SmoothingMode = 'AntiAlias'
$graphics.Clear([Drawing.Color]::FromArgb(32, 58, 47))
$paper = New-Object Drawing.SolidBrush([Drawing.Color]::FromArgb(255, 250, 242))
$red = New-Object Drawing.SolidBrush([Drawing.Color]::FromArgb(184, 67, 52))
$graphics.FillRectangle($paper, 15, 6, 34, 52)
$diamond = [Drawing.Point[]]@((New-Object Drawing.Point(32, 18)), (New-Object Drawing.Point(42, 32)), (New-Object Drawing.Point(32, 46)), (New-Object Drawing.Point(22, 32)))
$graphics.FillPolygon($red, $diamond)
$handle = $bitmap.GetHicon()
$icon = [Drawing.Icon]::FromHandle($handle)
$stream = [IO.File]::Open($iconPath, [IO.FileMode]::CreateNew)
try { $icon.Save($stream) } finally { $stream.Dispose(); $icon.Dispose(); [LauncherIconHandle]::DestroyIcon($handle) | Out-Null; $graphics.Dispose(); $bitmap.Dispose(); $paper.Dispose(); $red.Dispose() }
$sourceHash = Get-Digest $source
$manifestHash = Get-Digest $appManifest
& $compiler /nologo /codepage:65001 /target:winexe /platform:x64 /optimize+ /debug- "/win32icon:$iconPath" "/win32manifest:$appManifest" /reference:System.Windows.Forms.dll "/out:$candidate" $source
if ($LASTEXITCODE -ne 0) { throw 'Launcher compilation failed; previous executable preserved.' }
if ((Get-Digest $source) -ne $sourceHash -or (Get-Digest $appManifest) -ne $manifestHash) { throw 'Launcher inputs changed during compilation.' }
Assert-Plain $output
if ($ownedHash) {
    if ((Get-Digest $output) -ne $ownedHash) { throw 'Existing launcher changed during build.' }
    [IO.File]::Copy($output, (Join-Path $build 'previous.exe'), $false)
    [IO.File]::Replace($candidate, $output, [NullString]::Value)
} else { [IO.File]::Move($candidate, $output) }
$version = [Diagnostics.FileVersionInfo]::GetVersionInfo($output).FileVersion
$receipt = [ordered]@{schema='self-authored-launcher-1';source='windows/Launcher.cs';source_sha256=$sourceHash;
    app_manifest='windows/app.manifest';app_manifest_sha256=$manifestHash;
    build_script='scripts/build_launcher.ps1';build_script_sha256=(Get-Digest $PSCommandPath);
    executable='Balatro Agent.exe';sha256=(Get-Digest $output);version=$version;subsystem='windows_gui';
    byte_reproducible=$false;compiler='Windows .NET Framework csc';license='MIT'}
[IO.File]::WriteAllText($receiptPath, ($receipt | ConvertTo-Json) + "`n", [Text.UTF8Encoding]::new($false))
$receipt | ConvertTo-Json
