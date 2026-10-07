# Small desktop interface; setup.ps1/project.py remain the preparation boundary.
[CmdletBinding()]
param([switch]$Preview, [string]$PreviewImage,
    [ValidateSet('Preparing','Downloading','Ready','Error')][string]$PreviewState = 'Ready')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$script:process = $null
$script:stdoutPath = $null
$script:stderrPath = $null
$script:progressPath = $null
$script:preparationId = $null
$script:desktopError = ''
$script:prepared = $false
$script:started = [DateTime]::UtcNow

function Read-SharedLog([string]$Path) {
    if (-not $Path -or -not [IO.File]::Exists($Path)) { return '' }
    $stream = [IO.File]::Open($Path, 'Open', 'Read', ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
    $reader = New-Object IO.StreamReader($stream, [Text.Encoding]::UTF8)
    try { return $reader.ReadToEnd() } finally { $reader.Dispose() }
}

function Read-PreparationReceipt([string]$Path, [string]$Id) {
    $value = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($value.schema -ne 'automatic-preparation-1' -or $value.preparation_id -ne $Id -or
        $value.prepared -ne $true -or $value.stdio_tools_verified -ne 11 -or $value.game_started -ne $false) {
        throw 'The preparation receipt does not match this launch.'
    }
    return $value
}

function Open-Codex {
    $apps = @(Get-StartApps | Where-Object { $_.Name -eq 'Codex' })
    if ($apps.Count -eq 0) { $apps = @(Get-StartApps | Where-Object { $_.AppID -like 'OpenAI.Codex_*' }) }
    if ($apps.Count -eq 1) {
        Start-Process -FilePath (Join-Path $env:SystemRoot 'explorer.exe') -ArgumentList ('shell:AppsFolder\' + $apps[0].AppID) -WindowStyle Hidden
    } else {
        Start-Process 'https://developers.openai.com/codex/app/'
        $detail.Text = '安装并登录 Codex，再选择本项目目录。'
    }
}

$ink = [Drawing.Color]::FromArgb(31, 49, 40)
$muted = [Drawing.Color]::FromArgb(114, 121, 115)
$accent = [Drawing.Color]::FromArgb(38, 91, 66)
$paper = [Drawing.Color]::FromArgb(249, 248, 245)
$form = New-Object Windows.Forms.Form
$form.Text = 'Balatro Agent'
$form.ClientSize = New-Object Drawing.Size(430, 278)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedSingle'
$form.MaximizeBox = $false
$form.AutoScaleMode = 'Dpi'
$form.Font = New-Object Drawing.Font('Microsoft YaHei UI', 9)
$form.ForeColor = $ink; $form.BackColor = $paper
$executable = Join-Path $root 'Balatro Agent.exe'
if ([IO.File]::Exists($executable)) { $form.Icon = [Drawing.Icon]::ExtractAssociatedIcon($executable) }

function Add-Label([string]$Text, [int]$X, [int]$Y, [int]$Width, [int]$Height, [double]$Size, [Drawing.Color]$Color) {
    $label = New-Object Windows.Forms.Label
    $label.Text = $Text; $label.Location = New-Object Drawing.Point($X, $Y)
    $label.Size = New-Object Drawing.Size($Width, $Height)
    $label.Font = New-Object Drawing.Font('Microsoft YaHei UI', $Size)
    $label.ForeColor = $Color; $form.Controls.Add($label)
    return $label
}
$mark = Add-Label '♦' 21 18 43 49 26 ([Drawing.Color]::FromArgb(180, 70, 56))
$heading = Add-Label 'Balatro Agent' 76 18 318 30 17 $ink
$heading.Font = New-Object Drawing.Font('Segoe UI', 18, [Drawing.FontStyle]::Bold)
$subtitle = Add-Label '让 AI 接手下一局' 78 51 308 23 9 $muted
$status = Add-Label '正在检查游戏' 25 100 375 28 11 $ink
$detail = Add-Label '自动准备所需组件，请稍候。' 25 133 375 39 9 $muted
$progress = New-Object Windows.Forms.ProgressBar
$progress.Location = New-Object Drawing.Point(25, 178)
$progress.Size = New-Object Drawing.Size(380, 5)
$progress.Style = 'Marquee'; $progress.MarqueeAnimationSpeed = 25
$form.Controls.Add($progress)

function Add-Button([string]$Text, [int]$X, [bool]$Primary) {
    $button = New-Object Windows.Forms.Button
    $button.Text = $Text; $button.Location = New-Object Drawing.Point($X, 203)
    $button.Size = New-Object Drawing.Size(183, 36)
    $button.FlatStyle = 'Flat'; $button.Cursor = 'Hand'
    $button.BackColor = if ($Primary) { $accent } else { [Drawing.Color]::White }
    $button.ForeColor = if ($Primary) { [Drawing.Color]::White } else { $ink }
    $button.FlatAppearance.BorderSize = if ($Primary) { 0 } else { 1 }
    $button.FlatAppearance.BorderColor = [Drawing.Color]::FromArgb(220, 222, 216)
    $button.Visible = $false; $form.Controls.Add($button)
    return $button
}
$open = Add-Button '打开 Codex' 25 $true
$copy = Add-Button '复制游玩提示' 222 $false
$open.Enabled = $false; $copy.Enabled = $false
$promptText = (Get-Content -LiteralPath (Join-Path $root 'prompts/first-use.md') -Raw -Encoding UTF8).Trim()
$copy.Add_Click({ [Windows.Forms.Clipboard]::SetText($promptText); $detail.Text = '提示已复制。在 Codex 选择本项目，粘贴发送。' })
$open.Add_Click({ try { Open-Codex } catch { $detail.Text = '请手动打开 Codex，并选择本项目目录。' } })
$retry = Add-Button '重试' 25 $true
$retry.Enabled = $false
$retry.Add_Click({ try { Start-Preparation } catch { Show-PreparationError } })

$path = New-Object Windows.Forms.LinkLabel
$path.Text = '复制项目路径'; $path.Location = New-Object Drawing.Point(25, 252)
$path.Size = New-Object Drawing.Size(180, 20); $path.LinkColor = $muted
$path.ActiveLinkColor = $accent; $path.VisitedLinkColor = $muted
$path.LinkBehavior = 'HoverUnderline'
$path.Add_LinkClicked({ [Windows.Forms.Clipboard]::SetText($root); $detail.Text = '路径已复制。在 Codex 中选择此项目目录。' })
$form.Controls.Add($path)
$tooltip = New-Object Windows.Forms.ToolTip
$tooltip.SetToolTip($path, $root)
$logLink = New-Object Windows.Forms.LinkLabel
$logLink.Text = '详情'; $logLink.Location = New-Object Drawing.Point(371, 252)
$logLink.Size = New-Object Drawing.Size(35, 20); $logLink.LinkColor = $muted
$logLink.ActiveLinkColor = $accent; $logLink.VisitedLinkColor = $muted
$logLink.LinkBehavior = 'HoverUnderline'
$logLink.Add_LinkClicked({
    $dialog = New-Object Windows.Forms.Form
    $dialog.Text = 'Balatro Agent · 准备详情'; $dialog.Size = New-Object Drawing.Size(640, 430)
    $dialog.StartPosition = 'CenterParent'
    $log = New-Object Windows.Forms.TextBox
    $log.Multiline = $true; $log.ReadOnly = $true; $log.ScrollBars = 'Both'; $log.Dock = 'Fill'
    $log.Font = New-Object Drawing.Font('Consolas', 9)
    $log.Text = (Read-SharedLog $script:stdoutPath) + [Environment]::NewLine + (Read-SharedLog $script:stderrPath) + [Environment]::NewLine + $script:desktopError
    $dialog.Controls.Add($log); $dialog.ShowDialog($form) | Out-Null; $dialog.Dispose()
})
$form.Controls.Add($logLink)

function Complete-Preparation {
    $script:prepared = $true
    $status.Text = '准备就绪'; $status.ForeColor = $accent
    $detail.Text = '打开 Codex，选择本项目，再发送游玩提示。'
    $progress.Visible = $false
    $copy.Enabled = $true; $open.Enabled = $true; $copy.Visible = $true; $open.Visible = $true
    $retry.Enabled = $false; $retry.Visible = $false
    $form.ActiveControl = $open
}

function Show-PreparationError {
    $script:desktopError = $_.Exception.Message
    $timer.Stop(); $progress.Visible = $false
    $status.Text = '准备暂未完成'; $status.ForeColor = [Drawing.Color]::FromArgb(173, 66, 51)
    $errorText = (Read-SharedLog $script:stderrPath) + $script:desktopError
    $detail.Text = if ($errorText -match 'No unique verified Steam Balatro') { '未找到唯一的 Steam 版小丑牌，请查看详情。' }
        elseif ($errorText -match 'Close Balatro normally|normally closed') { '请正常关闭小丑牌，然后重试。' }
        elseif ($errorText -match 'timed out|timeout|超时|stalled|HTTPS download|remote server|远程服务器') { '下载连接超时。检查网络或系统代理后重试。' }
        elseif ($errorText -match 'checkpoint|Unresolved|receipt|differs|existing|Existing') { '已有配置或安装需要核对，请查看详情。' }
        else { '请查看详情中的原因，处理后重试。' }
    $retry.Enabled = $true; $retry.Visible = $true
}

function Start-Preparation {
    $script:prepared = $false
    $copy.Enabled = $false; $open.Enabled = $false; $copy.Visible = $false; $open.Visible = $false
    $retry.Enabled = $false; $retry.Visible = $false
    $status.Text = '正在检查游戏'; $status.ForeColor = $ink
    $detail.Text = '自动准备所需组件，请稍候。'
    $progress.Style = 'Marquee'; $progress.Visible = $true
    $script:preparationId = [Guid]::NewGuid().ToString('N')
    $script:progressPath = Join-Path $root ('.artifacts/preparation-' + $script:preparationId + '.progress.json')
    $script:desktopError = ''; $script:started = [DateTime]::UtcNow
    $logs = Join-Path $root 'runs/checks'; [IO.Directory]::CreateDirectory($logs) | Out-Null
    $script:stdoutPath = Join-Path $logs ('prepare-' + $script:preparationId + '-stdout.log')
    $script:stderrPath = Join-Path $logs ('prepare-' + $script:preparationId + '-stderr.log')
    $setup = Join-Path $PSScriptRoot 'setup.ps1'
    $arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $setup + '" -Install -Automatic -PreparationId ' + $script:preparationId
    $script:process = Start-Process -FilePath (Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe') -ArgumentList $arguments -WindowStyle Hidden -RedirectStandardOutput $script:stdoutPath -RedirectStandardError $script:stderrPath -PassThru
    $script:process.Handle | Out-Null
    $timer.Start()
}

function Show-Progress($Value, [int]$Elapsed) {
    $stages = @('正在检查游戏','正在准备内置工具','正在准备 Python','正在准备 Mod','正在配置连接')
    $stage = [Math]::Min(4, [Math]::Max(0, [int]$Value.stage))
    $status.Text = $stages[$stage]
    $detail.Text = ('{0}/4 · 已用 {1} 秒' -f $stage, $Elapsed)
    if ($Value.state -in @('connecting','downloading','retrying','verifying')) {
        $size = '{0:N1} MB' -f ([double]$Value.received_bytes / 1MB)
        if ($Value.total_bytes -gt 0) { $size += ' / {0:N1} MB' -f ([double]$Value.total_bytes / 1MB) }
        $detail.Text = switch ($Value.state) {
            'connecting' { $Value.component + ' · 正在连接' + $(if ($Value.received_bytes -gt 0) { ' · 续传 ' + $size } else { '' }) }
            'retrying' { $Value.component + ' · 正在重试连接（' + $Value.attempt + '）' }
            'verifying' { $Value.component + ' · 正在校验完整文件' }
            default { $Value.component + ' · ' + $size + (' · {0:N0} KB/s' -f ([double]$Value.bytes_per_second / 1KB)) }
        }
        if ($Value.state -eq 'downloading' -and $Value.total_bytes -gt 0) {
            $progress.Style = 'Continuous'
            $progress.Value = [Math]::Min(100, [int](100.0 * $Value.received_bytes / $Value.total_bytes))
        } else { $progress.Style = 'Marquee' }
    } else { $progress.Style = 'Marquee' }
}

$timer = New-Object Windows.Forms.Timer
$timer.Interval = 300
$timer.Add_Tick({
    try {
        if (-not $script:process.HasExited) {
            $elapsed = [int]([DateTime]::UtcNow - $script:started).TotalSeconds
            $value = $null
            try {
                $candidate = Read-SharedLog $script:progressPath | ConvertFrom-Json
                if ($candidate -and $candidate.schema -eq 'preparation-progress-1' -and $candidate.preparation_id -eq $script:preparationId) { $value = $candidate }
            } catch { $value = $null }
            if ($value) { Show-Progress $value $elapsed }
            else {
                $output = Read-SharedLog $script:stdoutPath
                $stage = if ($output -match '4/4') { 4 } elseif ($output -match '3/4') { 3 } elseif ($output -match '2/4') { 2 } elseif ($output -match '1/4') { 1 } else { 0 }
                Show-Progress ([pscustomobject]@{stage=$stage;state='working'}) $elapsed
            }
            return
        }
        $timer.Stop(); $script:process.WaitForExit()
        if ($script:process.ExitCode -ne 0) { throw 'Preparation stopped.' }
        Read-PreparationReceipt (Join-Path $root '.artifacts/onboarding.local.json') $script:preparationId | Out-Null
        Complete-Preparation
    } catch { Show-PreparationError }
})
$form.Add_FormClosing({
    param($sender, $event)
    if ($script:process -and -not $script:process.HasExited) {
        $event.Cancel = $true; $detail.Text = '准备仍在进行，请等待安全结束。'
    }
})

if ($Preview) {
    switch ($PreviewState) {
        'Ready' { Complete-Preparation }
        'Downloading' { Show-Progress ([pscustomobject]@{stage=1;state='downloading';component='uv';received_bytes=12582912;total_bytes=21540977;bytes_per_second=2097152}) 7 }
        'Error' { $status.Text = '准备暂未完成'; $status.ForeColor = [Drawing.Color]::FromArgb(173,66,51); $detail.Text = '下载连接超时。检查网络或系统代理后重试。'; $progress.Visible = $false; $retry.Enabled = $true; $retry.Visible = $true }
    }
    if ($PreviewImage) {
        $form.ShowInTaskbar = $false; $form.Opacity = 0
        $form.Show(); [Windows.Forms.Application]::DoEvents(); $form.PerformLayout()
        $bitmap = New-Object Drawing.Bitmap($form.Width, $form.Height)
        $form.DrawToBitmap($bitmap, (New-Object Drawing.Rectangle(0, 0, $form.Width, $form.Height)))
        $bitmap.Save([IO.Path]::GetFullPath($PreviewImage)); $bitmap.Dispose(); $form.Hide()
    }
    $form.Dispose(); $timer.Dispose(); $tooltip.Dispose(); exit 0
}
$hash = [Security.Cryptography.SHA256]::Create()
try { $name = 'Local\BalatroAgentPrepare-' + [BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($root.ToLowerInvariant()))).Replace('-', '') }
finally { $hash.Dispose() }
$mutex = New-Object Threading.Mutex($false, $name)
$locked = $false
try {
    try { $locked = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $locked = $true }
    if (-not $locked) { [Windows.Forms.MessageBox]::Show('Balatro Agent 已在此项目中运行。', 'Balatro Agent') | Out-Null; exit 1 }
    $form.Add_Shown({ try { Start-Preparation } catch { Show-PreparationError } })
    $form.ShowDialog() | Out-Null
} finally {
    $timer.Dispose(); $form.Dispose(); $tooltip.Dispose()
    if ($script:process) { $script:process.Dispose() }
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
if ($script:prepared) { exit 0 } else { exit 1 }
