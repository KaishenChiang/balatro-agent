# MIT. Shared UI vocabulary; never translates game observations or stored notes.
Set-StrictMode -Version Latest

function Resolve-BalatroLanguage([string]$Language = 'auto', [string]$CultureName = [Globalization.CultureInfo]::CurrentUICulture.Name) {
    switch ($Language) {
        'en' { return 'en' }
        'zh-CN' { return 'zh-CN' }
        'auto' { if ($CultureName -match '^zh(?:-|$)') { return 'zh-CN' }; return 'en' }
        default { throw 'Language must be auto, en or zh-CN.' }
    }
}

$script:BalatroStrings = @{
    en = @{
        subtitle='Let AI take the next run'; checking='Checking the game'; preparing='Preparing components. Please wait.'
        deck='Deck'; stake='Stake / mode'; start='Start in Codex'; copy='Copy play prompt'; retry='Retry'
        path='Copy project path'; details='Details'; details_title='Balatro Agent · Preparation details'
        ready='Ready'; ready_detail='Start in Codex to close this window, or copy the full prompt.'
        open_hint='This window closes after the Codex project-link request succeeds.'
        open_sent='Project and prompt requested. Review and send the prompt in Codex.'
        open_failed='The Codex project link could not be opened.'
        paste='Full prompt copied. Paste and send it in a local Codex chat.'
        install_client='Install and sign in to Codex, then paste the copied prompt.'
        copied='Prompt with project path and play rules copied. Paste it in Codex.'
        clipboard='Clipboard unavailable. Try copying again shortly.'
        manual_client='Open Codex manually, then copy and send the play prompt.'
        path_copied='Path copied. Select this project folder in Codex if needed.'
        fixed='Unlocks are checked in-game. One run; keep the results screen open.'
        highest='Check unlocks in-game; try this deck at its highest unlocked stake.'
        climb='Start at the highest unlocked stake. Retry losses, advance on wins, stop after Gold.'
        incomplete='Preparation incomplete'; no_game='No unique Steam Balatro installation found. See Details.'
        close_game='Close Balatro normally, then retry.'
        unresolved='An earlier action is unresolved. See Details before continuing.'
        old_project='The old project is unavailable and its independent receipt is missing. See Details for its path.'
        conflict='Existing settings or installation need checking. See Details.'
        local_timeout='Local connection check timed out. See Details, then retry.'
        download_timeout='Download timed out. Check your network or system proxy, then retry.'
        failure='See Details for the cause, resolve it, then retry.'
        busy='Preparation is still running. Wait for it to finish safely.'
        already_running='Balatro Agent is already running for this project.'
        tools='Preparing bundled tools'; python='Preparing Python'; mod='Preparing Mods'; connection='Configuring MCP'
        elapsed='{0}/4 · {1} seconds elapsed'; connecting='{0} · Connecting{1}'
        resuming=' · Resuming {0}'; retrying='{0} · Retrying connection (attempt {1})'
        verifying='{0} · Verifying the complete file'; downloading='{0} · {1} · {2:N0} KB/s'
        activity_title='Balatro Agent · Play activity'; activity_hint='Close this window freely. It does not control the game.'
        activity_waiting='Waiting for play updates'; activity_last='Last update: {0}'
        activity_limit='Latest {0} summaries · Full local records are retained'; activity_follow='Follow latest'
        activity_copy='Copy visible log'; activity_folder='Log folder'; activity_preview='Synthetic preview · No game or model calls'
        activity_observation='Observation'; activity_decision='Decision rationale'; activity_action='Action'
        activity_plan='Plan'; activity_notes='Experience'; activity_lifecycle='Game window'; activity_connection='Connection'
        activity_notice='Notice'; activity_history='Historical feedback'; activity_requested='Requested; native submission unconfirmed'
        activity_calculation='Public arithmetic'
        activity_changes='Public changes'; activity_reroll_cost='Reroll cost'; activity_pack_choices='Pack choices'
        changes_compared='Compared with delivered observation'; changes_unavailable='Comparison unavailable'
        changes_changed='Changed'; changes_unchanged='Known fields unchanged'; changes_unknown='Unknown'
        changes_no_baseline='First observation'; changes_historical_receipt='Historical receipt'
        changes_historical_observation='Historical observation'; changes_historical_scope='Historical session/profile'
        changes_observation_conflict='Conflicting observation'; changes_action_uncertain='Action uncertain'
        changes_action_pending='Action pending'; changes_outside_actionable_run='Outside ready run'
        changes_run_setup='Run setup'; changes_session_changed='Session changed'; changes_profile_changed='Profile changed'
        changes_run_boundary='New run'; changes_run_setup_changed='Deck/stake changed'; changes_round_rollback='Round rollback'
        changes_delivery_gap='Delivery gap'; changes_invalid_observation='Invalid observation'
        section_phase='Phase'; section_hand='Hand'; section_jokers='Jokers'; section_consumables='Consumables'
        section_shop='Shop'; section_pack='Pack'; section_resources='Resources'; section_blinds='Blind constraints'
        section_poker_hands='Hand levels'; section_deck_composition='Displayed deck composition'
        activity_updated='Updated'; activity_read='Read'; activity_objective='Goal'; activity_priorities='Priorities'
        activity_recheck='Recheck when'; activity_references='Experience refs'; activity_revision='Revision'
        activity_none='Unconfirmed'; activity_hidden='Face down / undiscovered'; activity_selected='selected'
        activity_ready='Ready'; activity_not_ready='Waiting'; activity_ante='Ante'; activity_round='Round'
        activity_dollars='Dollars'; activity_chips='Chips'; activity_hands='Hands'; activity_discards='Discards'
        activity_deck='Deck'; activity_stake='Stake'; activity_blind='Blind'; activity_target='Target'; activity_reason='Reason'
        activity_rationale_recorded='Original rationale retained; English summary unavailable'
        activity_plan_recorded='Original plan retained; English summary unavailable'
        activity_notice_recorded='Update recorded; English summary unavailable'
        activity_item_generic='item'; activity_item_jokers='Joker'; activity_item_consumables='consumable'
        activity_item_shop_jokers='Joker'; activity_item_shop_vouchers='Voucher'
        activity_item_shop_boosters='Booster Pack'; activity_item_pack='pack card'
        activity_deck_unknown='Deck unconfirmed'; activity_stake_unknown='Stake unconfirmed'
        activity_action_generic='Game action'; activity_card_action='{0} {1} cards'
        activity_card_action_one='{0} 1 card'
        activity_state_line='State: {0}'; activity_state_pending='Waiting for a confirmed game state'
        activity_decision_line='Decision: {0} · {1}'; activity_done_line='Executed: {0}'
        activity_running_line='Executing: {0}'; activity_input_line='In-game prompt needs attention: {0}'
        activity_uncertain_line='Result unconfirmed: {0}. Further actions are paused.'
        activity_rejected_line='Not executed: {0} · {1}'; activity_plan_line='Plan updated: {0}'
        activity_note_saved='Experience saved'; activity_note_read='Experience reviewed'
        activity_note_failed='Experience could not be read or saved. See the log folder.'
        activity_note_uncertain='Experience save unconfirmed. Check the records before retrying.'
        activity_game_open='Game ready'; activity_game_opening='Opening the game'
        activity_game_closed='Game closed'; activity_game_closing='Closing the game'
        activity_game_uncertain='Game launch or close unconfirmed. Further actions are paused.'
        activity_recovery_checked='Previous session checked'; activity_connected='Game connection ready'
        activity_connection_failed='Game connection needs checking. See the log folder.'
        activity_blind_Small='Small Blind'; activity_blind_Big='Big Blind'; activity_blind_Boss='Boss Blind'
        activity_error_generic='The operation needs checking. See the log folder.'
        activity_error_stale_observation='The game state changed; a fresh observation is needed.'
        activity_error_not_ready='The game is still changing.'; activity_error_wrong_phase='Unavailable on this screen.'
        activity_error_invalid_target='The selected target is unavailable.'
        activity_error_selection_restricted='The game restricts this selection.'
        activity_error_button_unavailable='The game has disabled this button.'
        activity_error_insufficient_capacity='No space is available.'
        activity_error_unknown_profile='The active profile could not be confirmed.'
        activity_error_profile_mismatch='The active profile changed.'
        activity_error_session_changed='The game session changed.'
        activity_error_action_busy='Another action is still in progress.'
        activity_error_game_action_unknown='An earlier action is unconfirmed. Further actions are paused.'
        activity_error_log_unavailable='The required local record could not be saved. Further actions are paused.'
        activity_error_native_error='The game did not accept the operation.'
        phase_hand='Playing hand'; phase_shop='Shop'; phase_pack='Choosing from a pack'; phase_blind_select='Blind selection'
        phase_main_menu='Main menu'; phase_run_setup='Run setup'; phase_round_eval='Round results'
        phase_terminal='Results'; phase_transition='Transition'; phase_unsupported='Unsupported'
        region_hand='Hand'; region_play='Played cards'; region_jokers='Jokers'; region_consumables='Consumables'
        region_shop_jokers='Shop cards'; region_shop_vouchers='Vouchers'; region_shop_boosters='Booster packs'; region_pack='Pack cards'
        state_INTENT='Requested'; state_RUNNING='Running'; state_AWAITING_INPUT='Awaiting native input'
        state_COMPLETED='Completed'; state_REJECTED='Rejected'; state_UNKNOWN='UNKNOWN — query only'
        outcome_win='Run won'; outcome_loss='Run lost'
        act_play='Play'
        act_discard='Discard'
        act_select='Select cards'
        act_reorder='Reorder'
        act_select_blind='Select blind'
        act_skip_blind='Skip blind'
        act_buy='Buy'
        act_buy_and_use='Buy and use'
        act_sell='Sell'
        act_use='Use'
        act_select_pack_card='Take pack card'
        act_start_run='Start run'
        act_continue_run='Continue run'
        act_open_run_setup='Open run setup'
        act_next_setup_choices='Next choices'
        act_previous_setup_choices='Previous choices'
        act_next_setup_page='Next setup page'
        act_previous_setup_page='Previous setup page'
        act_select_setup_option='Select setup option'
        act_cash_out='Cash out'
        act_next_round='Next round'
        act_reroll='Reroll shop'
        act_skip_pack='Skip pack'
        act_close_menu='Close menu'
        act_main_menu='Main menu'
        act_continue_endless='Continue Endless'
        act_run_info='Run info'
        act_deck_info='Deck info'
        act_sort_rank='Sort by rank'
        act_sort_suit='Sort by suit'
        act_open_options='Open options'
        act_open_settings='Open settings'
        act_next_game_speed='Increase game speed'
        act_previous_game_speed='Decrease game speed'

    }
    'zh-CN' = @{
        subtitle='让 AI 接手下一局'; checking='正在检查游戏'; preparing='自动准备所需组件，请稍候。'
        deck='牌组'; stake='注级／模式'; start='在 Codex 中开始'; copy='复制游玩提示'; retry='重试'
        path='复制项目路径'; details='详情'; details_title='Balatro Agent · 准备详情'
        ready='准备就绪'; ready_detail='在 Codex 中开始后自动关闭，或复制完整提示。'
        open_hint='打开 Codex 项目后自动关闭此窗口。'; open_sent='已请求打开项目并填入提示，确认后发送即可。'
        open_failed='Codex 项目链接未能打开。'; paste='完整提示已复制，在 Codex 的本地聊天粘贴发送。'
        install_client='安装并登录 Codex 后，粘贴已复制的完整提示。'
        copied='含路径与操作规则的提示已复制，直接粘贴发送。'; clipboard='剪贴板暂不可用，请稍后再次复制。'
        manual_client='请手动打开 Codex，再复制游玩提示发送。'; path_copied='路径已复制。在 Codex 中选择此项目目录。'
        fixed='游戏内核验解锁；一局胜负后保留结算页面。'; highest='游戏内核验解锁；尝试该牌组的最高已解锁注级。'
        climb='从最高已解锁注级开始；失败重试，获胜升一级，金注通关后停止。'
        incomplete='准备暂未完成'; no_game='未找到唯一的 Steam 版小丑牌，请查看详情。'
        close_game='请正常关闭小丑牌，然后重试。'; unresolved='上一会话的操作尚未确认，请查看详情。'
        old_project='旧项目目录不可用，且缺少独立安装凭证；请查看详情中的旧路径。'
        conflict='已有配置或安装需要核对，请查看详情。'; local_timeout='本地连接检查超时，请查看详情后重试。'
        download_timeout='下载连接超时。检查网络或系统代理后重试。'; failure='请查看详情中的原因，处理后重试。'
        busy='准备仍在进行，请等待安全结束。'; already_running='Balatro Agent 已在此项目中运行。'
        tools='正在准备内置工具'; python='正在准备 Python'; mod='正在准备 Mod'; connection='正在配置连接'
        elapsed='{0}/4 · 已用 {1} 秒'; connecting='{0} · 正在连接{1}'; resuming=' · 续传 {0}'
        retrying='{0} · 正在重试连接（{1}）'; verifying='{0} · 正在校验完整文件'; downloading='{0} · {1} · {2:N0} KB/s'
        activity_title='Balatro Agent · 游玩状态'; activity_hint='可随时关闭此窗口，不影响游戏与模型操作。'
        activity_waiting='等待游玩反馈'; activity_last='最近更新：{0}'
        activity_limit='最近 {0} 条摘要 · 完整本地记录仍保留'; activity_follow='跟随最新'
        activity_copy='复制当前记录'; activity_folder='记录目录'; activity_preview='合成界面预览 · 未读取游戏或调用模型'
        activity_observation='读取观察'; activity_decision='决策依据'; activity_action='操作状态'
        activity_plan='局内计划'; activity_notes='心得'; activity_lifecycle='游戏窗口'; activity_connection='连接'
        activity_notice='提示'; activity_history='历史反馈'; activity_requested='已请求；原生提交尚未确认'
        activity_calculation='公开算术'
        activity_changes='公开变化'; activity_reroll_cost='重掷费用'; activity_pack_choices='可选张数'
        changes_compared='与已交付观察比较'; changes_unavailable='暂不可比较'
        changes_changed='已变'; changes_unchanged='已知字段未变'; changes_unknown='未知'
        changes_no_baseline='首次观察'; changes_historical_receipt='历史收据'
        changes_historical_observation='历史观察'; changes_historical_scope='历史会话／档位'
        changes_observation_conflict='观察冲突'; changes_action_uncertain='动作不确定'
        changes_action_pending='动作未决'; changes_outside_actionable_run='非就绪对局'
        changes_run_setup='开局选择'; changes_session_changed='会话变化'; changes_profile_changed='档位变化'
        changes_run_boundary='新对局'; changes_run_setup_changed='牌组／注级变化'; changes_round_rollback='回合回退'
        changes_delivery_gap='交付缺口'; changes_invalid_observation='观察无效'
        section_phase='阶段'; section_hand='手牌'; section_jokers='小丑牌'; section_consumables='消耗牌'
        section_shop='商店'; section_pack='卡包'; section_resources='资源'; section_blinds='盲注约束'
        section_poker_hands='牌型等级'; section_deck_composition='已展示牌组组成'
        activity_updated='已更新'; activity_read='已读取'; activity_objective='目标'; activity_priorities='优先事项'
        activity_recheck='重新核对条件'; activity_references='经验引用'; activity_revision='版本'
        activity_none='未确认'; activity_hidden='背面／未发现'; activity_selected='已选'
        activity_ready='可操作'; activity_not_ready='等待'; activity_ante='底注'; activity_round='回合'
        activity_dollars='资金'; activity_chips='筹码'; activity_hands='出牌'; activity_discards='弃牌'
        activity_deck='牌组'; activity_stake='注级'; activity_blind='盲注'; activity_target='目标'; activity_reason='原因'
        activity_rationale_recorded='原文已记录，暂无中文依据摘要'
        activity_plan_recorded='原文已记录，暂无中文计划摘要'
        activity_notice_recorded='更新已记录，暂无中文摘要'
        activity_item_generic='目标'; activity_item_jokers='小丑牌'; activity_item_consumables='消耗牌'
        activity_item_shop_jokers='小丑牌'; activity_item_shop_vouchers='优惠券'
        activity_item_shop_boosters='卡包'; activity_item_pack='卡包选项'
        activity_deck_unknown='牌组未确认'; activity_stake_unknown='注级未确认'
        activity_action_generic='游戏操作'; activity_card_action='{0} {1} 张'
        activity_card_action_one='{0} 1 张'
        activity_state_line='状态：{0}'; activity_state_pending='等待确认游戏状态'
        activity_decision_line='决策：{0} · {1}'; activity_done_line='已执行：{0}'
        activity_running_line='正在执行：{0}'; activity_input_line='游戏内提示待处理：{0}'
        activity_uncertain_line='结果尚未确认：{0}，后续操作已暂停。'
        activity_rejected_line='未执行：{0} · {1}'; activity_plan_line='计划更新：{0}'
        activity_note_saved='心得已保存'; activity_note_read='已复习心得'
        activity_note_failed='心得读取或保存未成功，可查看记录目录。'
        activity_note_uncertain='心得保存结果尚未确认，重试前需核对记录。'
        activity_game_open='游戏已就绪'; activity_game_opening='正在打开游戏'
        activity_game_closed='游戏已关闭'; activity_game_closing='正在关闭游戏'
        activity_game_uncertain='游戏启动或关闭结果尚未确认，后续操作已暂停。'
        activity_recovery_checked='已核对旧会话'; activity_connected='游戏连接正常'
        activity_connection_failed='游戏连接需要检查，可查看记录目录。'
        activity_blind_Small='小盲注'; activity_blind_Big='大盲注'; activity_blind_Boss='Boss 盲注'
        activity_error_generic='本次操作需要检查，可查看记录目录。'
        activity_error_stale_observation='游戏状态已变化，需要重新读取。'
        activity_error_not_ready='游戏尚在切换。'; activity_error_wrong_phase='当前页面无法执行此操作。'
        activity_error_invalid_target='所选目标不可用。'; activity_error_selection_restricted='游戏限制了此次选牌。'
        activity_error_button_unavailable='游戏内按钮暂不可用。'; activity_error_insufficient_capacity='没有可用空位。'
        activity_error_unknown_profile='无法确认当前档位。'; activity_error_profile_mismatch='当前档位已变化。'
        activity_error_session_changed='游戏会话已变化。'; activity_error_action_busy='前一操作仍在执行。'
        activity_error_game_action_unknown='前一操作结果尚未确认，后续操作已暂停。'
        activity_error_log_unavailable='必需的本地记录未能保存，后续操作已暂停。'
        activity_error_native_error='游戏未接受此次操作。'
        phase_hand='出牌阶段'; phase_shop='商店'; phase_pack='补充包选择'; phase_blind_select='选择盲注'
        phase_main_menu='主菜单'; phase_run_setup='开局设置'; phase_round_eval='回合结算'
        phase_terminal='对局结算'; phase_transition='转换中'; phase_unsupported='不支持'
        region_hand='手牌'; region_play='已出牌'; region_jokers='小丑'; region_consumables='消耗牌'
        region_shop_jokers='商店牌'; region_shop_vouchers='优惠券'; region_shop_boosters='补充包'; region_pack='包内牌'
        state_INTENT='请求中'; state_RUNNING='执行中'; state_AWAITING_INPUT='等待原生输入'
        state_COMPLETED='已完成'; state_REJECTED='已拒绝'; state_UNKNOWN='UNKNOWN — 只能查询'
        outcome_win='本局胜利'; outcome_loss='本局失败'
        act_play='出牌'
        act_discard='弃牌'
        act_select='选牌'
        act_reorder='排序'
        act_select_blind='选择盲注'
        act_skip_blind='跳过盲注'
        act_buy='购买'
        act_buy_and_use='购买并使用'
        act_sell='出售'
        act_use='使用'
        act_select_pack_card='领取包内牌'
        act_start_run='开始新局'
        act_continue_run='继续对局'
        act_open_run_setup='打开新局设置'
        act_next_setup_choices='下一页候选'
        act_previous_setup_choices='上一页候选'
        act_next_setup_page='下一页设置'
        act_previous_setup_page='上一页设置'
        act_select_setup_option='选择开局选项'
        act_cash_out='结算收入'
        act_next_round='下一回合'
        act_reroll='刷新商店'
        act_skip_pack='跳过补充包'
        act_close_menu='关闭菜单'
        act_main_menu='主菜单'
        act_continue_endless='继续无尽'
        act_run_info='对局信息'
        act_deck_info='牌组信息'
        act_sort_rank='按点数排序'
        act_sort_suit='按花色排序'
        act_open_options='打开选项'
        act_open_settings='打开设置'
        act_next_game_speed='提高游戏速度'
        act_previous_game_speed='降低游戏速度'

    }
}

function Get-BalatroText([string]$Key, [string]$Language = 'zh-CN') {
    $resolved = Resolve-BalatroLanguage $Language
    if (-not $script:BalatroStrings[$resolved].ContainsKey($Key)) { throw ('Missing UI text: ' + $Key) }
    return $script:BalatroStrings[$resolved][$Key]
}

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


# Display-only translations of the same public catalogue used by the launcher.
# No game observation, native identity, strategy, or stored note is rewritten.
$script:BalatroDisplayNames=@{}
$catalogue=Get-BalatroPlayChoices
foreach ($choice in @($catalogue.Decks)+@($catalogue.Stakes)) {
    $pair=@{en=$choice.EnglishName;'zh-CN'=$choice.Name}
    $script:BalatroDisplayNames[$choice.Name]=$pair
    $script:BalatroDisplayNames[$choice.EnglishName]=$pair
}
$script:BalatroDisplayPattern=New-Object Text.RegularExpressions.Regex(
    ((@($script:BalatroDisplayNames.Keys) | Sort-Object {$_.Length} -Descending | ForEach-Object {[regex]::Escape($_)}) -join '|'),
    [Text.RegularExpressions.RegexOptions]::IgnoreCase)

function Convert-BalatroDisplayNames([string]$Value,[string]$Language) {
    $replace=[Text.RegularExpressions.MatchEvaluator]{param($match) $script:BalatroDisplayNames[$match.Value][$Language]}
    return $script:BalatroDisplayPattern.Replace($Value,$replace)
}
function Test-BalatroDisplayLanguage([string]$Value,[string]$Language) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return $false }
    if ($Value -match '\[(?:en|zh-CN)\]') { return $false }
    if ($Language -eq 'en') { return $Value -notmatch '[\u3400-\u9fff\uf900-\ufaff]' }
    # Proper product names and public rank notation may remain unchanged.
    $words=[regex]::Matches($Value,'[A-Za-z]{2,}')
    foreach ($word in $words) {
        if ($word.Value -notin @('AI','MCP','Balatro','Codex','Boss')) { return $false }
    }
    return $true
}
function Get-BalatroDisplayProse([string]$Value,[string]$Language,$Translations=$null,[int]$Limit=120) {
    $candidate=$null
    if ($null -ne $Translations) {
        if ($Translations -is [Collections.IDictionary]) { $candidate=$Translations[$Language] }
        elseif ($Translations.PSObject.Properties[$Language]) { $candidate=$Translations.PSObject.Properties[$Language].Value }
    }
    if ($candidate -isnot [string]) {
        $tags=[regex]::Matches($Value,'\[(?:en|zh-CN)\]')
        $match=[regex]::Match($Value,'(?s)^\s*\[(en|zh-CN)\]\s*(.*?)\s*\[(en|zh-CN)\]\s*(.*?)\s*$')
        if ($tags.Count -eq 2 -and $match.Success -and $match.Groups[1].Value -ne $match.Groups[3].Value -and
            $match.Groups[2].Value.Trim() -and $match.Groups[4].Value.Trim()) {
            $candidate=if ($match.Groups[1].Value -eq $Language) {$match.Groups[2].Value} else {$match.Groups[4].Value}
        } elseif ($tags.Count -eq 0) { $candidate=$Value }
    }
    if ($candidate -isnot [string]) { return $null }
    # A narrowly matched legacy setup sentence can be rendered without guessing
    # arbitrary free-form reasoning. Everything else needs the submitted summary.
    if ($Language -eq 'zh-CN') {
        $match=[regex]::Match($candidate,'^(.+?) is visibly selected and enabled; verify its (.+?) option\.$')
        if ($match.Success -and $script:BalatroDisplayNames.ContainsKey($match.Groups[1].Value) -and
            $script:BalatroDisplayNames.ContainsKey($match.Groups[2].Value)) {
            $candidate=($script:BalatroDisplayNames[$match.Groups[1].Value][$Language])+'已选中且可用；核验'+
                ($script:BalatroDisplayNames[$match.Groups[2].Value][$Language])+'选项。'
        } elseif ($candidate -match '^Start exactly one native unseeded run with the verified(?:\s|$)') {
            $candidate='按已核验的设置开始一局原生随机对局。'
        }
    }
    $candidate=(Convert-BalatroDisplayNames $candidate $Language) -replace '\s+',' '
    $candidate=$candidate.Trim()
    if (-not (Test-BalatroDisplayLanguage $candidate $Language)) { return $null }
    if ($candidate.Length -gt $Limit) { return $candidate.Substring(0,$Limit)+'…' }
    return $candidate
}
function Get-BalatroDisplayName([string]$Value,[string]$Language,[string]$FallbackKey) {
    $translated=Convert-BalatroDisplayNames $Value $Language
    if (Test-BalatroDisplayLanguage $translated $Language) { return $translated }
    return (Get-BalatroText $FallbackKey $Language)
}
