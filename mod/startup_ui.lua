-- Built from fixed-path preferences; no game state or raw errors are logged.
local options = {hide_console = true, hide_loading = true}
local ui = {console_status = 'not_checked', loading_status = 'not_checked'}

local function apply_console()
  if not options.hide_console then ui.console_status = 'visible_by_preference'; return end
  if not (jit and jit.os == 'Windows') then ui.console_status = 'unsupported_platform'; return end
  local available, ffi = pcall(require, 'ffi')
  if not available then ui.console_status = 'ffi_unavailable'; return end
  local checked = pcall(function()
    ffi.cdef[[
      void* __stdcall GetConsoleWindow(void);
      int __stdcall ShowWindow(void* window, int command);
      int __stdcall IsWindowVisible(void* window);
    ]]
    local kernel = ffi.load('kernel32')
    local user = ffi.load('user32')
    local window = kernel.GetConsoleWindow()
    if window == nil then ui.console_status = 'no_console'; return end
    user.ShowWindow(window, 0)
    ui.console_status = user.IsWindowVisible(window) == 0 and 'hidden' or 'hide_not_confirmed'
  end)
  if not checked then ui.console_status = 'api_unavailable' end
end

function ui.apply_loading()
  if not options.hide_loading then
    ui.loading_status = 'visible_by_preference'
  elseif not (SMODS and SMODS.version == '26.829.0') then
    ui.loading_status = 'version_mismatch'
  elseif type(boot_timer) ~= 'function' then
    ui.loading_status = 'timer_unavailable'
  else
    local original = boot_timer
    boot_timer = function(...)
      if not (G and G.ARGS and love and love.timer and type(love.timer.getTime) == 'function') then
        return original(...)
      end
      G.ARGS.bt = love.timer.getTime()
    end
    ui.loading_status = 'hidden'
  end
  if type(sendInfoMessage) == 'function' then
    pcall(sendInfoMessage, 'Startup display: console=' .. ui.console_status .. '; loading=' .. ui.loading_status, 'Balatro Agent')
  end
end

apply_console()
return ui
