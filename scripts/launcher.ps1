# Small desktop interface; setup.ps1/project.py remain the preparation boundary.
[CmdletBinding()]
param([switch]$Preview, [string]$PreviewImage,
    [ValidateSet('Preparing','Downloading','Ready','Error')][string]$PreviewState = 'Ready',
    [ValidateSet('auto','en','zh-CN')][string]$Language = 'auto')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
. (Join-Path $PSScriptRoot 'codex_handoff.ps1')
$script:language = Resolve-BalatroLanguage $Language
$script:statusKey = 'checking'
$script:detailKey = 'preparing'
$script:detailArguments = @()
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
        $value.prepared -ne $true -or $value.stdio_tools_verified -ne 12 -or $value.game_started -ne $false) {
        throw 'The preparation receipt does not match this launch.'
    }
    return $value
}

function Set-Detail([string]$Key, [object[]]$Arguments = @()) {
    $script:detailKey = $Key; $script:detailArguments = $Arguments
    $value = Get-BalatroText $Key $script:language
    $detail.Text = if ($Arguments.Count) { $value -f $Arguments } else { $value }
}

function Set-Status([string]$Key) {
    $script:statusKey = $Key; $status.Text = Get-BalatroText $Key $script:language
}

function Update-PlayPrompt {
    $deckKey = [string]$deckChoice.SelectedItem.Key
    $stakeKey = [string]$stakeChoice.SelectedItem.Key
    $script:promptText = Get-BalatroPlayPrompt $root -InlineRules -DeckKey $deckKey -StakeChoice $stakeKey -Language $script:language
    $script:codexLink = Get-BalatroCodexLink $root (Get-BalatroPlayPrompt $root -DeckKey $deckKey -StakeChoice $stakeKey -Language $script:language)
    $modeKey = switch ($stakeKey) { 'highest' { 'highest' }; 'climb' { 'climb' }; default { 'fixed' } }
    $modeDetail.Text = Get-BalatroText $modeKey $script:language
}

function Copy-PlayPrompt { Update-PlayPrompt; [Windows.Forms.Clipboard]::SetText($promptText) }

function Open-Codex {
    Update-PlayPrompt
    $protocol = Get-Item -LiteralPath 'Registry::HKEY_CLASSES_ROOT\codex' -ErrorAction SilentlyContinue
    if ($protocol -and $protocol.GetValueNames() -contains 'URL Protocol') {
        try {
            Start-Process -FilePath $codexLink -WindowStyle Hidden
            Set-Detail 'open_sent'
            $form.Close()
            return
        } catch { $script:desktopError = Get-BalatroText 'open_failed' $script:language }
    }
    Copy-PlayPrompt
    $apps = @(Get-StartApps | Where-Object { $_ -and $_.PSObject.Properties['Name'] -and $_.Name -eq 'Codex' })
    if ($apps.Count -eq 0) { $apps = @(Get-StartApps | Where-Object { $_ -and $_.PSObject.Properties['AppID'] -and $_.AppID -like 'OpenAI.Codex_*' }) }
    if ($apps.Count -eq 1) {
        Start-Process -FilePath (Join-Path $env:SystemRoot 'explorer.exe') -ArgumentList ('shell:AppsFolder\' + $apps[0].AppID) -WindowStyle Hidden
        Set-Detail 'paste'
    } else {
        Start-Process -FilePath 'https://developers.openai.com/codex/app/' -WindowStyle Hidden
        Set-Detail 'install_client'
    }
}

$ink = [Drawing.Color]::FromArgb(31, 49, 40)
$muted = [Drawing.Color]::FromArgb(114, 121, 115)
$accent = [Drawing.Color]::FromArgb(38, 91, 66)
$paper = [Drawing.Color]::FromArgb(249, 248, 245)
$form = New-Object Windows.Forms.Form
$form.Text = 'Balatro Agent'
$form.ClientSize = New-Object Drawing.Size(500, 425)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedSingle'
$form.MaximizeBox = $false
$form.AutoScaleMode = 'Dpi'
$fontFamily = if ($script:language -eq 'en') { 'Segoe UI' } else { 'Microsoft YaHei UI' }
$form.Font = New-Object Drawing.Font($fontFamily, 9)
$form.ForeColor = $ink; $form.BackColor = $paper
$executable = Join-Path $root 'Balatro Agent.exe'
if ([IO.File]::Exists($executable)) { $form.Icon = [Drawing.Icon]::ExtractAssociatedIcon($executable) }

function Add-Label([string]$Text, [int]$X, [int]$Y, [int]$Width, [int]$Height, [double]$Size, [Drawing.Color]$Color) {
    $label = New-Object Windows.Forms.Label
    $label.Text = $Text; $label.Location = New-Object Drawing.Point($X, $Y)
    $label.Size = New-Object Drawing.Size($Width, $Height)
    $label.Font = New-Object Drawing.Font($fontFamily, $Size)
    $label.ForeColor = $Color; $form.Controls.Add($label)
    return $label
}
$mark = Add-Label '♦' 21 18 43 49 26 ([Drawing.Color]::FromArgb(180, 70, 56))
$heading = Add-Label 'Balatro Agent' 76 18 318 30 17 $ink
$heading.Font = New-Object Drawing.Font('Segoe UI', 18, [Drawing.FontStyle]::Bold)
$subtitle = Add-Label (Get-BalatroText 'subtitle' $script:language) 78 51 308 23 9 $muted
$status = Add-Label (Get-BalatroText 'checking' $script:language) 25 100 450 28 11 $ink
$detail = Add-Label (Get-BalatroText 'preparing' $script:language) 25 133 450 39 9 $muted
$progress = New-Object Windows.Forms.ProgressBar
$progress.Location = New-Object Drawing.Point(25, 178)
$progress.Size = New-Object Drawing.Size(450, 5)
$progress.Style = 'Marquee'; $progress.MarqueeAnimationSpeed = 25
$form.Controls.Add($progress)

$deckLabel = Add-Label (Get-BalatroText 'deck' $script:language) 25 211 215 20 9 $muted
$stakeLabel = Add-Label (Get-BalatroText 'stake' $script:language) 260 211 215 20 9 $muted
$playChoices = Get-BalatroPlayChoices
function Add-Choice($Items, [int]$X) {
    $choice = New-Object Windows.Forms.ComboBox
    $choice.Location = New-Object Drawing.Point($X, 235)
    $choice.Size = New-Object Drawing.Size(215, 28)
    $choice.DropDownStyle = 'DropDownList'; $choice.DisplayMember = if ($script:language -eq 'en') { 'EnglishName' } else { 'Name' }
    $choice.DropDownWidth = 220; $choice.MaxDropDownItems = 10
    foreach ($item in $Items) { $choice.Items.Add($item) | Out-Null }
    $choice.SelectedIndex = 0; $choice.Enabled = $false
    $form.Controls.Add($choice)
    return $choice
}
$deckChoice = Add-Choice $playChoices.Decks 25
$stakeChoice = Add-Choice $playChoices.Stakes 260
$modeDetail = Add-Label '' 25 270 450 50 9 $muted
$deckChoice.Add_SelectedIndexChanged({ Update-PlayPrompt })
$stakeChoice.Add_SelectedIndexChanged({ Update-PlayPrompt })
Update-PlayPrompt

function Add-Button([string]$Text, [int]$X, [bool]$Primary) {
    $button = New-Object Windows.Forms.Button
    $button.Text = $Text; $button.Location = New-Object Drawing.Point($X, 334)
    $button.Size = New-Object Drawing.Size(215, 37)
    $button.FlatStyle = 'Flat'; $button.Cursor = 'Hand'
    $button.BackColor = if ($Primary) { $accent } else { [Drawing.Color]::White }
    $button.ForeColor = if ($Primary) { [Drawing.Color]::White } else { $ink }
    $button.FlatAppearance.BorderSize = if ($Primary) { 0 } else { 1 }
    $button.FlatAppearance.BorderColor = [Drawing.Color]::FromArgb(220, 222, 216)
    $button.Visible = $false; $form.Controls.Add($button)
    return $button
}
$open = Add-Button (Get-BalatroText 'start' $script:language) 25 $true
$copy = Add-Button (Get-BalatroText 'copy' $script:language) 260 $false
$open.Enabled = $false; $copy.Enabled = $false
$copy.Add_Click({
    try { Copy-PlayPrompt; Set-Detail 'copied' }
    catch { Set-Detail 'clipboard' }
})
$open.Add_Click({ try { Open-Codex } catch { Set-Detail 'manual_client' } })
$retry = Add-Button (Get-BalatroText 'retry' $script:language) 25 $true
$retry.Enabled = $false
$retry.Add_Click({ try { Start-Preparation } catch { Show-PreparationError } })

$path = New-Object Windows.Forms.LinkLabel
$path.Text = Get-BalatroText 'path' $script:language; $path.Location = New-Object Drawing.Point(25, 395)
$path.Size = New-Object Drawing.Size(180, 20); $path.LinkColor = $muted
$path.ActiveLinkColor = $accent; $path.VisitedLinkColor = $muted
$path.LinkBehavior = 'HoverUnderline'
$path.Add_LinkClicked({ [Windows.Forms.Clipboard]::SetText($root); Set-Detail 'path_copied' })
$form.Controls.Add($path)
$tooltip = New-Object Windows.Forms.ToolTip
$tooltip.SetToolTip($path, $root)
$tooltip.SetToolTip($open, (Get-BalatroText 'open_hint' $script:language))
$logLink = New-Object Windows.Forms.LinkLabel
$logLink.Text = Get-BalatroText 'details' $script:language; $logLink.Location = New-Object Drawing.Point(418, 395)
$logLink.Size = New-Object Drawing.Size(57, 20); $logLink.LinkColor = $muted
$logLink.ActiveLinkColor = $accent; $logLink.VisitedLinkColor = $muted
$logLink.LinkBehavior = 'HoverUnderline'
$logLink.Add_LinkClicked({
    $dialog = New-Object Windows.Forms.Form
    $dialog.Text = Get-BalatroText 'details_title' $script:language; $dialog.Size = New-Object Drawing.Size(640, 430)
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
    Set-Status 'ready'; $status.ForeColor = $accent
    Set-Detail 'ready_detail'
    $progress.Visible = $false
    $copy.Enabled = $true; $open.Enabled = $true; $copy.Visible = $true; $open.Visible = $true
    $deckChoice.Enabled = $true; $stakeChoice.Enabled = $true
    $retry.Enabled = $false; $retry.Visible = $false
    $form.ActiveControl = $open
}

function Get-PreparationFailureMessage([string]$Text, [int]$Stage = 0, [string]$Language = 'zh-CN') {
    if ($Text -match 'No unique verified Steam Balatro') { return (Get-BalatroText 'no_game' $Language) }
    if ($Text -match 'Close Balatro normally|normally closed') { return (Get-BalatroText 'close_game' $Language) }
    if ($Text -match 'checkpoint|Unresolved') { return (Get-BalatroText 'unresolved' $Language) }
    if ($Text -match 'Previous registered project is unavailable') { return (Get-BalatroText 'old_project' $Language) }
    if ($Text -match 'Mod/injector|receipt|differs|existing|Existing|adoption|registration') { return (Get-BalatroText 'conflict' $Language) }
    if ($Text -match '\btimed out\b|\btimeout(?:error)?\b|超时|\bstalled\b|HTTPS download|remote server|远程服务器') {
        if ($Stage -eq 4) { return (Get-BalatroText 'local_timeout' $Language) }
        return (Get-BalatroText 'download_timeout' $Language)
    }
    return (Get-BalatroText 'failure' $Language)
}

function Show-PreparationError {
    $script:desktopError = $_.Exception.Message
    $timer.Stop(); $progress.Visible = $false
    Set-Status 'incomplete'; $status.ForeColor = [Drawing.Color]::FromArgb(173, 66, 51)
    $errorText = (Read-SharedLog $script:stderrPath) + $script:desktopError
    $failureStage = if ((Read-SharedLog $script:stdoutPath) -match '4/4') { 4 } else { 0 }
    $script:failureText = $errorText; $script:failureStage = $failureStage
    $script:detailKey = 'failure_classified'
    $detail.Text = Get-PreparationFailureMessage $errorText $failureStage $script:language
    $retry.Enabled = $true; $retry.Visible = $true
}

function Start-Preparation {
    $script:prepared = $false
    $copy.Enabled = $false; $open.Enabled = $false; $copy.Visible = $false; $open.Visible = $false
    $deckChoice.Enabled = $false; $stakeChoice.Enabled = $false
    $retry.Enabled = $false; $retry.Visible = $false
    Set-Status 'checking'; $status.ForeColor = $ink
    Set-Detail 'preparing'
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
    $stages = @('checking','tools','python','mod','connection')
    $stage = [Math]::Min(4, [Math]::Max(0, [int]$Value.stage))
    Set-Status $stages[$stage]
    Set-Detail 'elapsed' @($stage, $Elapsed)
    if ($Value.state -in @('connecting','downloading','retrying','verifying')) {
        $size = '{0:N1} MB' -f ([double]$Value.received_bytes / 1MB)
        if ($Value.total_bytes -gt 0) { $size += ' / {0:N1} MB' -f ([double]$Value.total_bytes / 1MB) }
        switch ($Value.state) {
            'connecting' { $resume = if ($Value.received_bytes -gt 0) { (Get-BalatroText 'resuming' $script:language) -f $size } else { '' }; Set-Detail 'connecting' @($Value.component, $resume) }
            'retrying' { Set-Detail 'retrying' @($Value.component, $Value.attempt) }
            'verifying' { Set-Detail 'verifying' @($Value.component) }
            default { Set-Detail 'downloading' @($Value.component, $size, ([double]$Value.bytes_per_second / 1KB)) }
        }
        if ($Value.state -eq 'downloading' -and $Value.total_bytes -gt 0) {
            $progress.Style = 'Continuous'; $progress.Value = [Math]::Min(100, [int](100.0 * $Value.received_bytes / $Value.total_bytes))
        } else { $progress.Style = 'Marquee' }
    } else { $progress.Style = 'Marquee' }
}

function Set-LauncherLanguage([string]$Value) {
    $script:language = Resolve-BalatroLanguage $Value
    $family = if ($script:language -eq 'en') { 'Segoe UI' } else { 'Microsoft YaHei UI' }
    foreach ($control in $form.Controls) {
        $control.Font = New-Object Drawing.Font($family, $control.Font.Size, $control.Font.Style)
    }
    $subtitle.Text = Get-BalatroText 'subtitle' $script:language
    $deckLabel.Text = Get-BalatroText 'deck' $script:language; $stakeLabel.Text = Get-BalatroText 'stake' $script:language
    $open.Text = Get-BalatroText 'start' $script:language; $copy.Text = Get-BalatroText 'copy' $script:language
    $retry.Text = Get-BalatroText 'retry' $script:language; $path.Text = Get-BalatroText 'path' $script:language
    $logLink.Text = Get-BalatroText 'details' $script:language; $tooltip.SetToolTip($open, (Get-BalatroText 'open_hint' $script:language))
    $display = if ($script:language -eq 'en') { 'EnglishName' } else { 'Name' }
    $deckChoice.DisplayMember = $display; $stakeChoice.DisplayMember = $display
    Set-Status $script:statusKey
    if ($script:detailKey -eq 'failure_classified') {
        $detail.Text = Get-PreparationFailureMessage $script:failureText $script:failureStage $script:language
    } else { Set-Detail $script:detailKey $script:detailArguments }
    Update-PlayPrompt
}

$languageLabel = Add-Label 'Language / 语言' 365 3 115 19 8 $muted
$languageChoice = New-Object Windows.Forms.ComboBox
$languageChoice.Location = New-Object Drawing.Point(365, 25); $languageChoice.Size = New-Object Drawing.Size(110, 26)
$languageChoice.DropDownStyle = 'DropDownList'; $languageChoice.DisplayMember = 'Name'
foreach ($item in @([pscustomobject]@{Key='en';Name='English'}, [pscustomobject]@{Key='zh-CN';Name='简体中文'})) { $languageChoice.Items.Add($item) | Out-Null }
$languageChoice.SelectedIndex = if ($script:language -eq 'en') { 0 } else { 1 }
$form.Controls.Add($languageChoice)
$languageChoice.Add_SelectedIndexChanged({ Set-LauncherLanguage $languageChoice.SelectedItem.Key })


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
        $event.Cancel = $true; Set-Detail 'busy'
    }
})

if ($Preview) {
    switch ($PreviewState) {
        'Ready' { Complete-Preparation }
        'Downloading' { Show-Progress ([pscustomobject]@{stage=1;state='downloading';component='uv';received_bytes=12582912;total_bytes=21540977;bytes_per_second=2097152}) 7 }
        'Error' { Set-Status 'incomplete'; $status.ForeColor = [Drawing.Color]::FromArgb(173,66,51); Set-Detail 'download_timeout'; $progress.Visible = $false; $retry.Enabled = $true; $retry.Visible = $true }
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
    if (-not $locked) { [Windows.Forms.MessageBox]::Show((Get-BalatroText 'already_running' $script:language), 'Balatro Agent') | Out-Null; exit 1 }
    $form.Add_Shown({ try { Start-Preparation } catch { Show-PreparationError } })
    $form.ShowDialog() | Out-Null
} finally {
    $timer.Dispose(); $form.Dispose(); $tooltip.Dispose()
    if ($script:process) { $script:process.Dispose() }
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
if ($script:prepared) { exit 0 } else { exit 1 }
