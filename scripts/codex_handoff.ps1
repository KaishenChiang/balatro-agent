# Pure prompt/link construction. This file never starts a client or a game.
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'localization.ps1')

function Get-BalatroPlayPrompt([string]$ProjectRoot, [switch]$InlineRules,
        [string]$DeckKey = 'b_red', [string]$StakeChoice = 'white',
        [ValidateSet('en','zh-CN')][string]$Language = 'zh-CN') {
    $directory = [IO.Path]::GetFullPath($ProjectRoot)
    if (-not [IO.Directory]::Exists($directory)) { throw 'The project directory is unavailable.' }
    $portablePath = $directory.Replace('\', '/').TrimEnd('/')
    $rulesFile = if ($Language -eq 'en') { 'bootstrap.en.md' } else { 'bootstrap.md' }
    $taskFile = if ($Language -eq 'en') { 'first-use.en.md' } else { 'first-use.md' }
    $relativeRules = 'prompts/' + $rulesFile
    $bootstrapPath = $portablePath + '/' + $relativeRules
    $task = [IO.File]::ReadAllText((Join-Path $directory ('prompts/' + $taskFile)), [Text.Encoding]::UTF8).Trim()
    $task = $task.Replace($relativeRules, $bootstrapPath)
    $choices = Get-BalatroPlayChoices
    $deck = @($choices.Decks | Where-Object { $_.Key -eq $DeckKey })
    $stake = @($choices.Stakes | Where-Object { $_.Key -eq $StakeChoice })
    if ($deck.Count -ne 1 -or $stake.Count -ne 1) { throw 'Select an original deck and a supported stake or mode.' }
    if ($Language -eq 'en') {
        $selection = 'Selected deck: ' + $deck[0].EnglishName + '; selected stake / mode: ' + $stake[0].EnglishName + '.' + [Environment]::NewLine
        $selection += switch ($stake[0].Key) {
            'highest' { 'Highest stake: select this deck, inspect the complete visible stake catalogue, and play exactly one run at its highest verified unlocked stake. Stop after the win or loss and keep the results screen and game window open.' }
            'climb' { 'Stake climb: start at this deck''s highest verified unlocked stake. Report and review each normal loss before retrying the same stake. After a win, recheck unlocks and advance to the immediately next stake. Stop after beating Gold or when the user asks to stop. Normal losses have no retry limit; faults, UNKNOWN, locked options and unconfirmed states are not losses and must not trigger retries. Keep the final results screen and game window open. Do not continue into Endless.' }
            default { 'Single run: play exactly one run with this deck and fixed stake. Stop after the win or loss and keep the results screen and game window open. Do not retry automatically.' }
        }
        $selection += [Environment]::NewLine + 'These choices authorize this task. A requested new run may replace an unfinished old run through native menus; do not restart the target run once started. Resolve pending actions and UNKNOWN by querying the original records. Report locked or unconfirmed choices and stop without substituting a deck or stake. Report actual deck, stake, outcome, ante / round, elapsed time and whether experience was updated and read back, unchanged, or failed. Reply in English; preserve original game text and note history.'
        $context = 'Project directory: ' + $portablePath + [Environment]::NewLine
    } else {
    $selection = '所选牌组：' + $deck[0].Name + '（' + $deck[0].EnglishName + '）；所选注级／模式：' +
        $stake[0].Name + '（' + $stake[0].EnglishName + '）。' + [Environment]::NewLine
    $selection += switch ($stake[0].Key) {
        'highest' { '最高注级模式：先选择所选牌组，再遍历游戏中公开显示的注级候选，选择该牌组已解锁的最高注级，只尝试一局。正常胜负后停止并保留结算页面与窗口。' }
        'climb' { '爬塔模式：从所选牌组已解锁的最高注级开始。正常失败后先报告本局并复盘，再重新开局重试当前注级；通关后重新核验解锁，升到紧接的下一注级继续，直到金注通关后停止并保留结算页面与窗口。允许连续尝试，不设正常败局重试次数上限；用户叫停即停止，故障、UNKNOWN、未解锁或无法确认状态不能当作败局来重试。不继续无尽模式。' }
        default { '单局模式：只游玩所选牌组与固定注级的一局。正常胜利或失败后停止并保留结算页面与窗口，不自动重试。' }
    }
    $selection += [Environment]::NewLine + '这些选择是本次任务授权，开始新局可通过原生菜单替换未完成旧局；本次目标局开始后不自行中途重开，未决动作与UNKNOWN仍先核验原记录。指定牌组或固定注级未解锁时明确通知并停止，不自行替换；无法确认解锁时报告未确认。每局报告实际牌组、注级、胜负、到达底注／回合、用时，以及心得已更新并读回、未更新或更新失败。'
    $context = '项目目录：' + $portablePath + [Environment]::NewLine
    }
    if (-not $InlineRules) { return $context + $selection + [Environment]::NewLine + [Environment]::NewLine + $task }
    $rules = [IO.File]::ReadAllText((Join-Path $directory $relativeRules), [Text.Encoding]::UTF8).Trim()
    if ($Language -eq 'en') {
        $task = $task.Replace('Read ' + $bootstrapPath, 'Follow the play rules below')
        return $context + $selection + [Environment]::NewLine + [Environment]::NewLine + $task + [Environment]::NewLine + [Environment]::NewLine +
            'The complete rules are included. Paste this into a local Codex chat with balatro-agent MCP loaded. The path identifies the project; it does not change the chat working directory or grant file permissions. Report missing MCP tools before continuing.' +
            [Environment]::NewLine + [Environment]::NewLine + $rules
    }
    $task = $task.Replace('请阅读 ' + $bootstrapPath, '请遵循下方操作规则')
    return $context + $selection + [Environment]::NewLine + [Environment]::NewLine + $task + [Environment]::NewLine + [Environment]::NewLine +
        '操作规则已包含在此提示中，可直接在已加载 balatro-agent MCP 的本地 Codex 聊天发送。路径用于标明项目，不改变当前聊天的工作目录或文件权限；缺少 MCP 工具时先报告连接缺项。' +
        [Environment]::NewLine + [Environment]::NewLine + $rules
}

function Get-BalatroCodexLink([string]$ProjectRoot, [string]$Prompt) {
    $directory = [IO.Path]::GetFullPath($ProjectRoot)
    if (-not [IO.Directory]::Exists($directory) -or [string]::IsNullOrWhiteSpace($Prompt)) {
        throw 'A local project directory and prompt are required.'
    }
    # Encode each query value separately: spaces, Unicode, &, # and % remain data.
    return 'codex://threads/new?path=' + [Uri]::EscapeDataString($directory) +
        '&prompt=' + [Uri]::EscapeDataString($Prompt)
}
