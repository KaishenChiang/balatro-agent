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
    }
}

function Get-BalatroText([string]$Key, [string]$Language = 'zh-CN') {
    $resolved = Resolve-BalatroLanguage $Language
    if (-not $script:BalatroStrings[$resolved].ContainsKey($Key)) { throw ('Missing UI text: ' + $Key) }
    return $script:BalatroStrings[$resolved][$Key]
}
