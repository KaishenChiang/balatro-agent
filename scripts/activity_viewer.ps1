# MIT. Independent read-only activity viewer; no MCP, game, model or save access.
[CmdletBinding()]
param([string]$EventDirectory, [ValidateSet('auto','en','zh-CN')][string]$Language='auto',
      [switch]$Preview, [string]$PreviewImage,
      [ValidateSet('Preparing','Downloading','Ready','Error')][string]$PreviewState='Ready')
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'localization.ps1')
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
if (-not $EventDirectory) { $EventDirectory=Join-Path (Join-Path $PSScriptRoot '..') 'runs/live/activity' }
$EventDirectory=[IO.Path]::GetFullPath($EventDirectory)
$script:activityLanguage=Resolve-BalatroLanguage $Language
$script:rows=New-Object 'System.Collections.Generic.List[object]'
$script:visibleRows=@()
$script:seen=New-Object 'System.Collections.Generic.HashSet[string]'
$script:tails=@{}
$script:lastUpdate=$null
$script:seenOrder=New-Object 'System.Collections.Generic.Queue[string]'
$script:summaries=@{}
$script:actionDescriptions=@{}
$script:files=@()
$script:nextDiscovery=[DateTime]::MinValue
$script:version=0
$script:renderedVersion=-1
$script:viewVersion=-1
$script:renderedViewVersion=-2
$script:headerRow=$null

function Field($Object,[string]$Key) {
    if ($null -eq $Object) { return $null }
    $property=$Object.PSObject.Properties[$Key]
    if ($property) { return $property.Value }
    return $null
}
function AT([string]$Key) { Get-BalatroText $Key $script:activityLanguage }
function Caption([string]$Prefix,$Value) {
    if ($null -eq $Value -or [string]::IsNullOrWhiteSpace([string]$Value)) { return (AT 'activity_none') }
    $key=$Prefix+[string]$Value
    if ($script:BalatroStrings[$script:activityLanguage].ContainsKey($key)) { return (AT $key) }
    return [string]$Value
}
function Brief($Value,[int]$Limit=240) {
    if ($null -eq $Value) { return (AT 'activity_none') }
    $valueText=([string]$Value -replace '\s+',' ').Trim()
    if ($valueText.Length -gt $Limit) { return $valueText.Substring(0,$Limit)+'…' }
    return $valueText
}
function Known-Caption([string]$Prefix,$Value,[string]$Fallback) {
    $key=$Prefix+[string]$Value
    if ($script:BalatroStrings[$script:activityLanguage].ContainsKey($key)) { return (AT $key) }
    return (AT $Fallback)
}
function Remember-Summary([string]$Key,[string]$Value) {
    if ($script:summaries.ContainsKey($Key) -and $script:summaries[$Key] -eq $Value) { return $false }
    $script:summaries[$Key]=$Value
    if ($script:summaries.Count -gt 256) { $script:summaries.Remove(@($script:summaries.Keys)[0]) }
    return $true
}
function Display-Data([string]$Kind,$Data) {
    # Keep only fields required to retranslate a visible line. Inventories and
    # audit references remain on disk; the GUI never retains their full trees.
    $keys=switch ($Kind) {
        'observation' { @('phase','outcome','deck','stake') }
        'decision' { @('action','action_id','reason','reason_i18n','card_count','target_name','target_region','blind_slot') }
        'action' { @('action','action_id','state','status','reason','card_count','target_name','target_region','blind_slot') }
        'plan' { @('objective','objective_i18n','priority_i18n') }
        'notes' { @('status','committed','write_state') }
        'lifecycle' { @('state','status','reason') }
        default { @('status') }
    }
    $small=@{}
    foreach ($key in $keys) { $small[$key]=Field $Data $key }
    foreach ($key in @('reason_i18n','objective_i18n','priority_i18n')) {
        if (-not $small.ContainsKey($key)) { continue }
        $translations=@{}
        foreach ($language in @('en','zh-CN')) {
            $translation=Field $small[$key] $language
            if ($translation -is [string] -and $translation.Length -le 121) { $translations[$language]=$translation }
        }
        $small[$key]=[pscustomobject]$translations
    }
    if ($Kind -eq 'observation') {
        $resources=Field $Data 'resources'; $small.resources=[pscustomobject]@{
            ante=(Field $resources 'ante');round=(Field $resources 'round');dollars=(Field $resources 'dollars') }
    } elseif ($Kind -eq 'decision') {
        if ($null -eq $small.card_count) {
            $positions=Field (Field $Data 'parameters') 'positions'
            if ($null -ne $positions) { $small.card_count=@($positions).Count }
            elseif ($null -ne (Field $Data 'targets')) { $small.card_count=@(Field $Data 'targets').Count }
        }
        if (-not $small.target_name) { $small.target_name=Field (@(Field $Data 'targets') | Select-Object -First 1) 'name' }
        $small.blind_slot=Field (Field $Data 'parameters') 'blind_slot'
        if (-not $small.target_region) { $small.target_region=Field (Field $Data 'parameters') 'region' }
    } elseif ($Kind -eq 'plan') {
        $small.priorities=@(Field $Data 'priorities' | Select-Object -First 1)
    }
    return [pscustomobject]$small
}
function Action-Description($Row) {
    $data=Field $Row 'data'; $action=[string](Field $data 'action')
    $cached=$script:actionDescriptions[[string](Field $Row 'session')+':'+[string](Field $data 'action_id')]
    if (-not $action) { $action=[string](Field $cached 'action') }
    $description=Known-Caption 'act_' $action 'activity_action_generic'
    if ($action -in @('play','discard','select')) {
        $count=Field $data 'card_count'
        if ($null -eq $count) { $count=Field $cached 'card_count' }
        if ($null -eq $count) {
            $positions=Field (Field $data 'parameters') 'positions'
            if ($null -eq $positions) { $positions=Field (Field $cached 'parameters') 'positions' }
            if ($null -ne $positions) { $count=@($positions).Count }
            elseif ($null -ne (Field $data 'targets')) { $count=@(Field $data 'targets').Count }
        }
        if ($null -ne $count) {
            $key=if ($count -eq 1) { 'activity_card_action_one' } else { 'activity_card_action' }
            $description=(AT $key) -f $description,$count
        }
    } elseif ($action -in @('buy','buy_and_use','sell','use','select_pack_card')) {
        $name=Field $data 'target_name'
        if (-not $name) { $name=Field $cached 'target_name' }
        if (-not $name) {
            $target=@(Field $data 'targets') | Select-Object -First 1
            $name=Field $target 'name'
        }
        if ($name) {
            $region=Field $data 'target_region'
            if (-not $region) { $region=Field $cached 'target_region' }
            $key='activity_item_'+[string]$region
            if (-not $script:BalatroStrings[$script:activityLanguage].ContainsKey($key)) { $key='activity_item_generic' }
            $description+=' '+(Brief (Get-BalatroDisplayName $name $script:activityLanguage $key) 48)
        }
    } elseif ($action -in @('select_blind','skip_blind')) {
        $slot=Field $data 'blind_slot'
        if (-not $slot) { $slot=Field $cached 'blind_slot' }
        if ($slot) { $description+=' '+(Known-Caption 'activity_blind_' $slot 'activity_blind') }
    }
    return $description
}
function Activity-Message($Row) {
    $data=Field $Row 'data'; $kind=[string](Field $Row 'kind'); $tool=[string](Field $Row 'tool')
    switch ($kind) {
        'observation' {
            $phase=Known-Caption 'phase_' (Field $data 'phase') 'activity_state_pending'
            $outcome=Field $data 'outcome'
            if ($outcome) { $phase=Known-Caption 'outcome_' $outcome 'activity_state_pending' }
            $parts=New-Object 'System.Collections.Generic.List[string]'
            $parts.Add($phase)
            $resources=Field $data 'resources'
            foreach ($key in @('ante','round')) {
                $value=Field $resources $key
                if ($null -ne $value) { $parts.Add((AT ('activity_'+$key))+': '+$value) }
            }
            if ((Field $Row '_showSetup') -eq $true) {
                foreach ($key in @('deck','stake')) { if (Field $data $key) { $parts.Add((Brief (Get-BalatroDisplayName (Field $data $key) $script:activityLanguage ('activity_'+$key+'_unknown')) 48)) } }
            }
            if ((Field $data 'phase') -eq 'shop' -and $null -ne (Field $resources 'dollars')) {
                $parts.Add((AT 'activity_dollars')+': '+(Field $resources 'dollars'))
            }
            return (AT 'activity_state_line') -f ($parts -join ' · ')
        }
        'decision' {
            $reason=Get-BalatroDisplayProse (Field $data 'reason') $script:activityLanguage (Field $data 'reason_i18n') 120
            if (-not $reason) { $reason=AT 'activity_rationale_recorded' }
            return (AT 'activity_decision_line') -f (Action-Description $Row),$reason
        }
        'action' {
            $action=Action-Description $Row
            switch ([string](Field $data 'state')) {
                'COMPLETED' { return ((AT 'activity_done_line') -f $action) }
                'RUNNING' { return ((AT 'activity_running_line') -f $action) }
                'AWAITING_INPUT' { return ((AT 'activity_input_line') -f $action) }
                'UNKNOWN' { return ((AT 'activity_uncertain_line') -f $action) }
                'REJECTED' { return ((AT 'activity_rejected_line') -f $action,(Known-Caption 'activity_error_' (Field $data 'reason') 'activity_error_generic')) }
                default { return (Known-Caption 'activity_error_' (Field $data 'status') 'activity_error_generic') }
            }
        }
        'plan' {
            $priority=@(Field $data 'priorities') | Select-Object -First 1
            $goal=Get-BalatroDisplayProse (Field $data 'objective') $script:activityLanguage (Field $data 'objective_i18n') 90
            $priority=Get-BalatroDisplayProse $priority $script:activityLanguage (Field $data 'priority_i18n') 70
            if (-not $goal) { $goal=AT 'activity_plan_recorded' }
            if ($priority) { $goal+=' · '+$priority }
            return (AT 'activity_plan_line') -f $goal
        }
        'notes' {
            if ((Field $data 'write_state') -eq 'UNKNOWN') { return (AT 'activity_note_uncertain') }
            if ((Field $data 'status') -ne 'ok') { return (Known-Caption 'activity_error_' (Field $data 'status') 'activity_note_failed') }
            if ((Field $data 'committed') -eq $true) { return (AT 'activity_note_saved') }
            return (AT 'activity_note_read')
        }
        'lifecycle' {
            $state=Field $data 'state'
            if ($state -eq 'UNKNOWN') { return (AT 'activity_game_uncertain') }
            if ($state -eq 'REJECTED') { return (Known-Caption 'activity_error_' (Field $data 'reason') 'activity_error_generic') }
            if ($tool -eq 'launch_game') {
                if ($state -eq 'COMPLETED') { return (AT 'activity_game_open') }
                return (AT 'activity_game_opening')
            }
            if ($tool -eq 'close_game') {
                if ($state -eq 'COMPLETED') { return (AT 'activity_game_closed') }
                return (AT 'activity_game_closing')
            }
            return (AT 'activity_recovery_checked')
        }
        'connection' {
            if ((Field $data 'status') -eq 'ok') { return (AT 'activity_connected') }
            return (AT 'activity_connection_failed')
        }
        'notice' {
            $status=[string](Field $data 'status')
            if ($status -match '\s|[^\x00-\x7f]') {
                $message=Get-BalatroDisplayProse $status $script:activityLanguage
                if ($message) { return $message }
                return (AT 'activity_notice_recorded')
            }
            return (Known-Caption 'activity_error_' $status 'activity_error_generic')
        }
        default { return (AT 'activity_error_generic') }
    }
}
function Format-Activity($Row) {
    return [string](Field $Row '_time')+'  '+(Activity-Message $Row)
}

function Add-ActivityRow($Row) {
    if ((Field $Row 'schema') -ne 'activity-v1' -or [string](Field $Row 'session') -notmatch '^[0-9a-f]{32}$' -or
        ((Field $Row 'sequence') -isnot [int] -and (Field $Row 'sequence') -isnot [long]) -or [long](Field $Row 'sequence') -lt 1 -or
        [string](Field $Row 'kind') -notin @('observation','decision','action','plan','notes','lifecycle','connection','notice','calculation','changes')) { return }
    try { $time=[DateTimeOffset]::Parse([string](Field $Row 'utc')) } catch { return }
    $id=[string](Field $Row 'session')+':'+[string](Field $Row 'sequence')
    if (-not $script:seen.Add($id)) { return }
    $script:seenOrder.Enqueue($id)
    if ($script:seen.Count -gt 2048) { $script:seen.Remove($script:seenOrder.Dequeue()) | Out-Null }
    if ($null -eq $script:lastUpdate -or $time -gt $script:lastUpdate) { $script:lastUpdate=$time }
    $script:version++
    $Row | Add-Member -NotePropertyName '_order' -NotePropertyValue $time.UtcTicks
    $Row | Add-Member -NotePropertyName '_time' -NotePropertyValue $time.ToLocalTime().ToString('HH:mm:ss')
    $data=Field $Row 'data'; $kind=[string](Field $Row 'kind'); $session=[string](Field $Row 'session')
    switch ($kind) {
        'observation' {
            if ((Field $data 'historical') -eq $true -or
                ((Field $data 'ready') -ne $true -and (Field $data 'phase') -notin @('terminal','unsupported'))) { return }
            $resources=Field $data 'resources'
            $setup=@((Field $data 'deck'),(Field $data 'stake')) -join '|'
            $showSetup=Remember-Summary ($session+':setup') $setup
            $Row | Add-Member -NotePropertyName '_showSetup' -NotePropertyValue $showSetup
            $state=@((Field $data 'phase'),(Field $data 'outcome'),$setup,(Field $resources 'ante'),(Field $resources 'round')) -join '|'
            if (-not (Remember-Summary ($session+':observation') $state)) { return }
        }
        'decision' {
            $data=Display-Data $kind $data; $Row.data=$data
            $key=$session+':'+[string](Field $data 'action_id'); $script:actionDescriptions[$key]=$data
            if ($script:actionDescriptions.Count -gt 256) { $script:actionDescriptions.Remove(@($script:actionDescriptions.Keys)[0]) }
        }
        'action' {
            $state=[string](Field $data 'state')
            if (-not (Remember-Summary ($session+':action:'+[string](Field $data 'action_id')) ($state+':'+[string](Field $data 'status')+':'+[string](Field $data 'reason')))) { return }
            if ($state -eq 'RUNNING') { $Row.data=Display-Data $kind $data; $script:headerRow=$Row; return }
        }
        'plan' { if ((Field $data 'updated') -ne $true) { return } }
        'connection' { if (-not (Remember-Summary ($session+':connection') ([string](Field $data 'status')))) { return } }
        'changes' { return }
        'calculation' { if ((Field $data 'status') -eq 'ok') { return } }
    }
    if ($kind -ne 'decision') { $Row.data=Display-Data $kind $data }
    $Row | Add-Member -NotePropertyName '_line' -NotePropertyValue (Format-Activity $Row)
    $Row | Add-Member -NotePropertyName '_language' -NotePropertyValue $script:activityLanguage
    $script:rows.Add($Row); $script:headerRow=$Row
    if ($script:rows.Count -gt 500) { $script:rows.RemoveAt(0) }
    $script:viewVersion++
}

function Read-ActivityTail($File) {
    $key=$File.FullName
    if (-not $script:tails.ContainsKey($key)) {
        $offset=[Math]::Max(0,$File.Length-1048576)
        $script:tails[$key]=@{offset=[long]$offset;pending=[byte[]]@();drop=($offset -gt 0)}
    }
    $state=$script:tails[$key]
    if ($File.Length -eq $state.offset) { return }
    $stream=$null
    try {
        $stream=[IO.File]::Open($key,[IO.FileMode]::Open,[IO.FileAccess]::Read,([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
        if ($stream.Length -lt $state.offset) { $state.offset=0L; $state.pending=[byte[]]@(); $state.drop=$false }
        $stream.Position=$state.offset
        $count=[int][Math]::Min(131072,$stream.Length-$state.offset)
        if ($count -le 0) { return }
        $buffer=New-Object byte[] $count
        $read=$stream.Read($buffer,0,$count); $state.offset+=$read
        if ($read -le 0) { return }
        if ($read -ne $count) { $buffer=$buffer[0..($read-1)] }
        $combined=[byte[]]($state.pending+$buffer)
        $last=[Array]::LastIndexOf($combined,[byte]10)
        if ($last -lt 0) {
            $state.pending=if ($combined.Length -le 16384) { $combined } else { [byte[]]@() }
            if ($combined.Length -gt 16384) { $state.drop=$true }
            return
        }
        $state.pending=if ($last+1 -lt $combined.Length) { [byte[]]$combined[($last+1)..($combined.Length-1)] } else { [byte[]]@() }
        $start=0
        if ($state.drop) { $start=[Array]::IndexOf($combined,[byte]10)+1; $state.drop=$false }
        if ($last -lt $start) { return }
        $content=[Text.Encoding]::UTF8.GetString($combined,$start,$last-$start+1)
        foreach ($line in ($content -split "`n")) {
            if ($line.Length -gt 16384 -or -not $line.Trim()) { continue }
            try { Add-ActivityRow (ConvertFrom-Json -InputObject $line) } catch { }
        }
    } catch { } finally { if ($stream) { $stream.Dispose() } }
}

function Refresh-Activity {
    if ([IO.Directory]::Exists($EventDirectory)) {
        if ([DateTime]::UtcNow -ge $script:nextDiscovery) {
            $script:files=@(Get-ChildItem -LiteralPath $EventDirectory -Filter 'events-*.jsonl' -File |
                Where-Object { $_.Name -match '^events-[0-9a-f]{32}\.jsonl$' -and -not ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) } |
                Sort-Object LastWriteTimeUtc | Select-Object -Last 20)
            $active=@{}
            foreach ($file in $script:files) { $active[$file.FullName]=$true }
            foreach ($key in @($script:tails.Keys)) { if (-not $active.ContainsKey($key)) { $script:tails.Remove($key) } }
            $script:nextDiscovery=[DateTime]::UtcNow.AddSeconds(3)
        }
        foreach ($file in $script:files) {
            $file.Refresh()
            if ($file.Exists -and -not ($file.Attributes -band [IO.FileAttributes]::ReparsePoint)) { Read-ActivityTail $file }
        }
    }
}

$form=New-Object Windows.Forms.Form
$form.Text=AT 'activity_title'; $form.Size=New-Object Drawing.Size(980,620)
$form.MinimumSize=New-Object Drawing.Size(780,420); $form.StartPosition='CenterScreen'
$form.Font=New-Object Drawing.Font('Segoe UI',9)
$form.BackColor=[Drawing.Color]::FromArgb(249,248,245)
$top=New-Object Windows.Forms.Panel; $top.Height=80; $top.Dock='Top'; $form.Controls.Add($top)
$hint=New-Object Windows.Forms.Label; $hint.Location=New-Object Drawing.Point(16,12); $hint.AutoSize=$true; $top.Controls.Add($hint)
$recent=New-Object Windows.Forms.Label; $recent.Location=New-Object Drawing.Point(16,43); $recent.AutoSize=$true; $top.Controls.Add($recent)
$languageLabel=New-Object Windows.Forms.Label; $languageLabel.Text='Language / 语言'; $languageLabel.AutoSize=$true
$languageLabel.Location=New-Object Drawing.Point(780,6); $languageLabel.Anchor='Top,Right'; $top.Controls.Add($languageLabel)
$languageChoice=New-Object Windows.Forms.ComboBox; $languageChoice.DropDownStyle='DropDownList'
$languageChoice.Location=New-Object Drawing.Point(780,29); $languageChoice.Size=New-Object Drawing.Size(170,25)
$languageChoice.Anchor='Top,Right'; $languageChoice.DisplayMember='Name'
foreach ($item in @([pscustomobject]@{Key='en';Name='English'},[pscustomobject]@{Key='zh-CN';Name='简体中文'})) { $languageChoice.Items.Add($item) | Out-Null }
$languageChoice.SelectedIndex=if ($script:activityLanguage -eq 'en') { 0 } else { 1 }; $top.Controls.Add($languageChoice)
$bottom=New-Object Windows.Forms.Panel; $bottom.Height=52; $bottom.Dock='Bottom'; $form.Controls.Add($bottom)
$follow=New-Object Windows.Forms.CheckBox; $follow.Checked=$true; $follow.AutoSize=$true
$follow.Location=New-Object Drawing.Point(16,16); $bottom.Controls.Add($follow)
$copy=New-Object Windows.Forms.Button; $copy.Location=New-Object Drawing.Point(160,11); $copy.Size=New-Object Drawing.Size(140,30); $bottom.Controls.Add($copy)
$folder=New-Object Windows.Forms.Button; $folder.Location=New-Object Drawing.Point(312,11); $folder.Size=New-Object Drawing.Size(120,30); $bottom.Controls.Add($folder)
$summary=New-Object Windows.Forms.Label; $summary.Location=New-Object Drawing.Point(450,19); $summary.AutoSize=$true; $bottom.Controls.Add($summary)
$body=New-Object Windows.Forms.TextBox; $body.Multiline=$true; $body.ReadOnly=$true; $body.ScrollBars='Vertical'; $body.Dock='Fill'
$body.Font=New-Object Drawing.Font('Segoe UI',10.5); $body.BackColor=[Drawing.Color]::White; $body.BorderStyle='None'
$body.WordWrap=$true; $form.Controls.Add($body); $body.BringToFront()

function Render-Activity([switch]$Force) {
    if (-not $Force -and $script:renderedVersion -eq $script:version) { return }
    $form.Text=AT 'activity_title'; $hint.Text=AT 'activity_hint'
    $follow.Text=AT 'activity_follow'; $copy.Text=AT 'activity_copy'; $folder.Text=AT 'activity_folder'
    $summary.Text=(AT 'activity_limit') -f $script:rows.Count
    $recent.Text=if ($script:lastUpdate) { (AT 'activity_last') -f $script:lastUpdate.ToLocalTime().ToString('HH:mm:ss') } else { AT 'activity_waiting' }
    if ($script:headerRow -and (Field (Field $script:headerRow 'data') 'state') -eq 'RUNNING') { $recent.Text+=' · '+(Activity-Message $script:headerRow) }
    if ($Force -or ($follow.Checked -and $script:renderedViewVersion -ne $script:viewVersion)) {
        if ($follow.Checked) { $script:visibleRows=@($script:rows | Sort-Object _order,session,sequence) }
        if ($Force) {
            foreach ($row in $script:visibleRows) {
                if ($row._language -ne $script:activityLanguage) {
                    $row._line=Format-Activity $row; $row._language=$script:activityLanguage
                }
            }
        }
        $lines=@(foreach ($row in $script:visibleRows) { $row._line })
        $rendered=$lines -join "`r`n`r`n"
        if ($body.Text -ne $rendered) {
            $body.Text=$rendered
            if ($follow.Checked) { $body.SelectionStart=$body.TextLength; $body.ScrollToCaret() }
        }
        $script:renderedViewVersion=$script:viewVersion
    }
    $script:renderedVersion=$script:version
}
$languageChoice.Add_SelectedIndexChanged({ $script:activityLanguage=$languageChoice.SelectedItem.Key; Render-Activity -Force })
$follow.Add_CheckedChanged({ if ($follow.Checked) { Render-Activity -Force } })
$copy.Add_Click({ try { [Windows.Forms.Clipboard]::SetText($body.Text) } catch { } })
$folder.Add_Click({ if ([IO.Directory]::Exists($EventDirectory)) { Start-Process -FilePath (Join-Path $env:SystemRoot 'explorer.exe') -ArgumentList ('"'+$EventDirectory+'"') -WindowStyle Hidden } })
$timer=New-Object Windows.Forms.Timer; $timer.Interval=500
$timer.Add_Tick({ try { Refresh-Activity; Render-Activity } catch { } })

if ($Preview) {
    Refresh-Activity; Render-Activity -Force; $hint.Text=AT 'activity_preview'
    if ($PreviewImage) {
        $form.ShowInTaskbar=$false; $form.Opacity=0; $form.Show(); [Windows.Forms.Application]::DoEvents()
        $bitmap=New-Object Drawing.Bitmap($form.Width,$form.Height)
        $form.DrawToBitmap($bitmap,(New-Object Drawing.Rectangle(0,0,$form.Width,$form.Height)))
        $bitmap.Save([IO.Path]::GetFullPath($PreviewImage)); $bitmap.Dispose(); $form.Hide()
    }
    $form.Dispose(); $timer.Dispose(); exit 0
}
$hash=[Security.Cryptography.SHA256]::Create()
$mutexName='Local\BalatroAgentActivity_'+[BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($EventDirectory.ToLowerInvariant()))).Replace('-','')
$hash.Dispose(); $mutex=New-Object Threading.Mutex($false,$mutexName); $locked=$false
try {
    try { $locked=$mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $locked=$true }
    if (-not $locked) { exit 0 }
    $form.Add_Shown({ Refresh-Activity; Render-Activity -Force; $timer.Start() })
    $form.ShowDialog() | Out-Null
} finally {
    $timer.Stop(); $timer.Dispose(); $form.Dispose()
    if ($locked) { $mutex.ReleaseMutex() }; $mutex.Dispose()
}
