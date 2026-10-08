# Pure prompt/link construction. This file never starts a client or a game.
Set-StrictMode -Version Latest

function Get-BalatroPlayChoices {
    # Original public catalogue only. Unlocks are checked by the model in-game.
    $decks = @(
        @{Key='b_red';Name='红色牌组';EnglishName='Red Deck'},
        @{Key='b_blue';Name='蓝色牌组';EnglishName='Blue Deck'},
        @{Key='b_yellow';Name='黄色牌组';EnglishName='Yellow Deck'},
        @{Key='b_green';Name='绿色牌组';EnglishName='Green Deck'},
        @{Key='b_black';Name='黑色牌组';EnglishName='Black Deck'},
        @{Key='b_magic';Name='魔法牌组';EnglishName='Magic Deck'},
        @{Key='b_nebula';Name='星云牌组';EnglishName='Nebula Deck'},
        @{Key='b_ghost';Name='幽灵牌组';EnglishName='Ghost Deck'},
        @{Key='b_abandoned';Name='废弃牌组';EnglishName='Abandoned Deck'},
        @{Key='b_checkered';Name='方格牌组';EnglishName='Checkered Deck'},
        @{Key='b_zodiac';Name='黄道牌组';EnglishName='Zodiac Deck'},
        @{Key='b_painted';Name='彩绘牌组';EnglishName='Painted Deck'},
        @{Key='b_anaglyph';Name='浮雕牌组';EnglishName='Anaglyph Deck'},
        @{Key='b_plasma';Name='等离子牌组';EnglishName='Plasma Deck'},
        @{Key='b_erratic';Name='古怪牌组';EnglishName='Erratic Deck'}
    ) | ForEach-Object { [pscustomobject]$_ }
    $stakes = @(
        @{Key='white';Name='白注';EnglishName='White Stake'},
        @{Key='red';Name='红注';EnglishName='Red Stake'},
        @{Key='green';Name='绿注';EnglishName='Green Stake'},
        @{Key='black';Name='黑注';EnglishName='Black Stake'},
        @{Key='blue';Name='蓝注';EnglishName='Blue Stake'},
        @{Key='purple';Name='紫注';EnglishName='Purple Stake'},
        @{Key='orange';Name='橙注';EnglishName='Orange Stake'},
        @{Key='gold';Name='金注';EnglishName='Gold Stake'},
        @{Key='highest';Name='最高注级';EnglishName='Highest unlocked stake'},
        @{Key='climb';Name='爬塔模式';EnglishName='Stake climb'}
    ) | ForEach-Object { [pscustomobject]$_ }
    return [pscustomobject]@{Decks=@($decks);Stakes=@($stakes)}
}

function Get-BalatroPlayPrompt([string]$ProjectRoot, [switch]$InlineRules,
        [string]$DeckKey = 'b_red', [string]$StakeChoice = 'white') {
    $directory = [IO.Path]::GetFullPath($ProjectRoot)
    if (-not [IO.Directory]::Exists($directory)) { throw 'The project directory is unavailable.' }
    $portablePath = $directory.Replace('\', '/').TrimEnd('/')
    $bootstrapPath = $portablePath + '/prompts/bootstrap.md'
    $task = [IO.File]::ReadAllText((Join-Path $directory 'prompts/first-use.md'), [Text.Encoding]::UTF8).Trim()
    $task = $task.Replace('prompts/bootstrap.md', $bootstrapPath)
    $choices = Get-BalatroPlayChoices
    $deck = @($choices.Decks | Where-Object { $_.Key -eq $DeckKey })
    $stake = @($choices.Stakes | Where-Object { $_.Key -eq $StakeChoice })
    if ($deck.Count -ne 1 -or $stake.Count -ne 1) { throw 'Select an original deck and a supported stake or mode.' }
    $selection = '所选牌组：' + $deck[0].Name + '（' + $deck[0].EnglishName + '）；所选注级／模式：' +
        $stake[0].Name + '（' + $stake[0].EnglishName + '）。' + [Environment]::NewLine
    $selection += switch ($stake[0].Key) {
        'highest' { '最高注级模式：先选择所选牌组，再遍历游戏中公开显示的注级候选，选择该牌组已解锁的最高注级，只尝试一局。正常胜负后停止并保留结算页面与窗口。' }
        'climb' { '爬塔模式：从所选牌组已解锁的最高注级开始。正常失败后先报告本局并复盘，再重新开局重试当前注级；通关后重新核验解锁，升到紧接的下一注级继续，直到金注通关后停止并保留结算页面与窗口。允许连续尝试，不设正常败局重试次数上限；用户叫停即停止，故障、UNKNOWN、未解锁或无法确认状态不能当作败局来重试。不继续无尽模式。' }
        default { '单局模式：只游玩所选牌组与固定注级的一局。正常胜利或失败后停止并保留结算页面与窗口，不自动重试。' }
    }
    $selection += [Environment]::NewLine + '这些选择是本次任务授权，开始新局可通过原生菜单替换未完成旧局；本次目标局开始后不自行中途重开，未决动作与UNKNOWN仍先核验原记录。指定牌组或固定注级未解锁时明确通知并停止，不自行替换；无法确认解锁时报告未确认。每局报告实际牌组、注级、胜负、到达底注／回合、用时，以及心得已更新并读回、未更新或更新失败。'
    $context = '项目目录：' + $portablePath + [Environment]::NewLine
    if (-not $InlineRules) { return $context + $selection + [Environment]::NewLine + [Environment]::NewLine + $task }
    $rules = [IO.File]::ReadAllText((Join-Path $directory 'prompts/bootstrap.md'), [Text.Encoding]::UTF8).Trim()
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
