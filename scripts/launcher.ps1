# Windows desktop entrypoint. Preparation stays in setup.ps1/project.py.
[CmdletBinding()]
param([switch]$Preview, [string]$PreviewImage)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$script:process = $null
$script:stdoutPath = $null
$script:stderrPath = $null
$script:preparationId = $null
$script:desktopError = ''
$script:prepared = $false

function Read-SharedLog([string]$Path) {
    if (-not $Path -or -not [IO.File]::Exists($Path)) { return '' }
    $stream = [IO.File]::Open($Path, 'Open', 'Read', 'ReadWrite')
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
        $status.Text = '请安装并登录 Codex，再用它打开下方项目目录。'
    }
}

$form = New-Object Windows.Forms.Form
$form.Text = 'Balatro Agent'
$form.ClientSize = New-Object Drawing.Size(660, 470)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.Font = New-Object Drawing.Font('Microsoft YaHei UI', 10)
$form.BackColor = [Drawing.Color]::White

$heading = New-Object Windows.Forms.Label
$heading.Text = '正在自动准备 Balatro Agent'
$heading.Location = New-Object Drawing.Point(26, 22)
$heading.Size = New-Object Drawing.Size(610, 36)
$heading.Font = New-Object Drawing.Font('Microsoft YaHei UI', 17, [Drawing.FontStyle]::Bold)
$form.Controls.Add($heading)
$status = New-Object Windows.Forms.Label
$status.Text = '检查游戏、下载所需组件、备份并配置工具，请稍候。'
$status.Location = New-Object Drawing.Point(28, 70)
$status.Size = New-Object Drawing.Size(600, 66)
$form.Controls.Add($status)
$progress = New-Object Windows.Forms.ProgressBar
$progress.Location = New-Object Drawing.Point(28, 142)
$progress.Size = New-Object Drawing.Size(600, 18)
$progress.Style = 'Marquee'
$form.Controls.Add($progress)

$prompt = New-Object Windows.Forms.TextBox
$prompt.Location = New-Object Drawing.Point(28, 183)
$prompt.Size = New-Object Drawing.Size(600, 112)
$prompt.Multiline = $true
$prompt.ReadOnly = $true
$prompt.Text = (Get-Content -LiteralPath (Join-Path $root 'prompts/first-use.md') -Raw -Encoding UTF8).Trim()
$prompt.Visible = $false
$form.Controls.Add($prompt)
$copy = New-Object Windows.Forms.Button
$copy.Text = '复制游玩提示'
$copy.Location = New-Object Drawing.Point(28, 308)
$copy.Size = New-Object Drawing.Size(180, 42)
$copy.Enabled = $false
$copy.Add_Click({ [Windows.Forms.Clipboard]::SetText($prompt.Text); $status.Text = '提示已复制。在 Codex 打开本项目，粘贴并发送即可开始。' })
$form.Controls.Add($copy)
$open = New-Object Windows.Forms.Button
$open.Text = '打开 Codex'
$open.Location = New-Object Drawing.Point(224, 308)
$open.Size = New-Object Drawing.Size(180, 42)
$open.Enabled = $false
$open.Add_Click({ try { Open-Codex } catch { $status.Text = '请手动打开已登录的 Codex，并打开下方项目目录。' } })
$form.Controls.Add($open)
$retry = New-Object Windows.Forms.Button
$retry.Text = '重新检查'
$retry.Location = New-Object Drawing.Point(448, 308)
$retry.Size = New-Object Drawing.Size(180, 42)
$retry.Enabled = $false
$retry.Visible = $false
$retry.Add_Click({ Start-Preparation })
$form.Controls.Add($retry)
$path = New-Object Windows.Forms.LinkLabel
$path.Text = '复制项目路径：' + $root
$path.Location = New-Object Drawing.Point(28, 369)
$path.Size = New-Object Drawing.Size(600, 38)
$path.Add_LinkClicked({ [Windows.Forms.Clipboard]::SetText($root); $status.Text = '项目路径已复制。在 Codex 的项目入口选择此目录。' })
$form.Controls.Add($path)
$logLink = New-Object Windows.Forms.LinkLabel
$logLink.Text = '查看准备日志'
$logLink.Location = New-Object Drawing.Point(28, 425)
$logLink.Size = New-Object Drawing.Size(160, 24)
$logLink.Add_LinkClicked({
    $dialog = New-Object Windows.Forms.Form
    $dialog.Text = 'Balatro Agent · 准备日志'
    $dialog.Size = New-Object Drawing.Size(740, 500)
    $log = New-Object Windows.Forms.TextBox
    $log.Multiline = $true; $log.ReadOnly = $true; $log.ScrollBars = 'Both'; $log.Dock = 'Fill'
    $log.Text = (Read-SharedLog $script:stdoutPath) + "`r`n" + (Read-SharedLog $script:stderrPath) + "`r`n" + $script:desktopError
    $dialog.Controls.Add($log); $dialog.ShowDialog($form) | Out-Null; $dialog.Dispose()
})
$form.Controls.Add($logLink)

function Complete-Preparation {
    $script:prepared = $true
    $heading.Text = '准备完成，可以接入 AI'
    $heading.ForeColor = [Drawing.Color]::FromArgb(24, 120, 60)
    $status.Text = "打开 Codex，选择下方项目目录，再粘贴并发送游玩提示。`r`n若工具尚未加载，按客户端支持的方式重载后继续。"
    $progress.Visible = $false
    $prompt.Visible = $true; $copy.Enabled = $true; $open.Enabled = $true; $retry.Enabled = $false; $retry.Visible = $false
    $form.ActiveControl = $copy
    $prompt.SelectionLength = 0
}

function Start-Preparation {
    $script:prepared = $false
    $copy.Enabled = $false; $open.Enabled = $false; $retry.Enabled = $false; $retry.Visible = $false; $prompt.Visible = $false
    $heading.Text = '正在自动准备 Balatro Agent'; $heading.ForeColor = [Drawing.Color]::Black
    $progress.Style = 'Marquee'
    $progress.Visible = $true
    $script:preparationId = [Guid]::NewGuid().ToString('N')
    $script:desktopError = ''
    $logs = Join-Path $root 'runs/checks'
    [IO.Directory]::CreateDirectory($logs) | Out-Null
    $script:stdoutPath = Join-Path $logs ('prepare-' + $script:preparationId + '-stdout.log')
    $script:stderrPath = Join-Path $logs ('prepare-' + $script:preparationId + '-stderr.log')
    $setup = Join-Path $PSScriptRoot 'setup.ps1'
    $arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $setup + '" -Install -Automatic -PreparationId ' + $script:preparationId
    $script:process = Start-Process -FilePath (Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe') -ArgumentList $arguments -WindowStyle Hidden -RedirectStandardOutput $script:stdoutPath -RedirectStandardError $script:stderrPath -PassThru
    # Hold the native process handle while it is running, so ExitCode remains
    # available even when the worker finishes before the next timer tick.
    $script:process.Handle | Out-Null
    $timer.Start()
}

$timer = New-Object Windows.Forms.Timer
$timer.Interval = 500
$timer.Add_Tick({
    try {
        if (-not $script:process.HasExited) {
            $output = Read-SharedLog $script:stdoutPath
            $status.Text = if ($output -match '4/4') { '正在构建、备份、安装并核验工具…' }
                elseif ($output -match '3/4') { '正在下载并校验所需 Mod…' }
                elseif ($output -match '2/4') { '正在准备 Python 与隔离依赖…' }
                elseif ($output -match '1/4') { '已找到游戏，正在准备下载工具…' }
                else { '正在检查 Steam 游戏与已有环境…' }
            return
        }
        $timer.Stop()
        $script:process.WaitForExit()
        if ($script:process.ExitCode -ne 0) { throw 'Preparation stopped.' }
        Read-PreparationReceipt (Join-Path $root '.artifacts/onboarding.local.json') $script:preparationId | Out-Null
        Complete-Preparation
    } catch {
        $script:desktopError = $_.Exception.Message
        $timer.Stop(); $progress.Visible = $false
        $heading.Text = '准备暂未完成'; $heading.ForeColor = [Drawing.Color]::Firebrick
        $errorText = (Read-SharedLog $script:stderrPath).Trim()
        $status.Text = if ($errorText -match 'No unique verified Steam Balatro') { '未找到唯一的 Steam 版小丑牌。请先用 Steam 安装游戏，再点击重新检查；多份安装请按维护说明指定路径。' }
            elseif ($errorText -match 'Close Balatro normally|normally closed') { '请正常关闭小丑牌，再点击重新检查。' }
            elseif ($errorText -match 'checkpoint|Unresolved|receipt') { '已有安装收据或未决动作需要核对。请保留现场，按维护说明恢复；详细原因见准备日志。' }
            else { '请查看准备日志中的原因，处理后点击重新检查。已有文件和配置保留。' }
        $retry.Enabled = $true; $retry.Visible = $true
    }
})
$form.Add_FormClosing({
    param($sender, $event)
    if ($script:process -and -not $script:process.HasExited) {
        $event.Cancel = $true; $status.Text = '准备仍在进行，请等待完成后关闭窗口。'
    }
})

if ($Preview) {
    Complete-Preparation
    if ($PreviewImage) {
        $form.ShowInTaskbar = $false; $form.Opacity = 0
        $form.Show(); [Windows.Forms.Application]::DoEvents(); $form.PerformLayout()
        $bitmap = New-Object Drawing.Bitmap($form.Width, $form.Height)
        $form.DrawToBitmap($bitmap, (New-Object Drawing.Rectangle(0, 0, $form.Width, $form.Height)))
        $bitmap.Save([IO.Path]::GetFullPath($PreviewImage)); $bitmap.Dispose(); $form.Hide()
    }
    $form.Dispose(); $timer.Dispose(); exit 0
}
$hash = [Security.Cryptography.SHA256]::Create()
try { $name = 'Local\BalatroAgentPrepare-' + [BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($root.ToLowerInvariant()))).Replace('-', '') }
finally { $hash.Dispose() }
$mutex = New-Object Threading.Mutex($false, $name)
$locked = $false
try {
    try { $locked = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $locked = $true }
    if (-not $locked) { [Windows.Forms.MessageBox]::Show('Balatro Agent 已在此项目中运行，请使用已有窗口。', 'Balatro Agent') | Out-Null; exit 1 }
    $form.Add_Shown({ try { Start-Preparation } catch { $heading.Text = '无法开始准备'; $status.Text = $_.Exception.Message; $retry.Enabled = $true } })
    $form.ShowDialog() | Out-Null
} finally {
    $timer.Dispose(); $form.Dispose()
    if ($script:process) { $script:process.Dispose() }
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
if ($script:prepared) { exit 0 } else { exit 1 }
