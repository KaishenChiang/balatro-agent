-- BalatroBot v1.5.2 / 9052d76, with reviewed player-visible execution boundaries.
-- Original attribution and MIT license accompany the transport modules.
-- Do not load upstream settings, gamestate, actions, save/load or debug tools.
BB_SETTINGS = {host='127.0.0.1',port=12346,debug=false,render_on_api=false}
BB_RENDER = nil
assert(SMODS.load_file('src/lua/utils/errors.lua'))()
assert(SMODS.load_file('src/lua/core/server.lua'))()
assert(SMODS.load_file('src/lua/core/dispatcher.lua'))()
BA_READER = assert(SMODS.load_file('reader/reader.lua'))()
BA_BINDING = assert(SMODS.load_file('reader/binding.lua'))()
BA_BINDING.attach(BA_READER)
BA_EXECUTOR = assert(SMODS.load_file('reader/executor.lua'))()
BA_EXECUTOR.install_hooks()
if not BB_SERVER.init() then return end
if not BB_DISPATCHER.init(BB_SERVER, {'reader/health.lua','reader/snapshot.lua','reader/act_submit.lua','reader/action_status.lua'}) then return end
local native_update = love.update
love.update = function(dt)
  native_update(dt)
  BA_BINDING.update(BA_READER)
  BA_EXECUTOR.update()
  -- Native UI update has completed. Each request executes synchronously here.
  BB_SERVER.update(BB_DISPATCHER)
end
sendInfoMessage('Balatro Agent adapter 0.2.0; upstream release 1.5.2 / manifest 1.5.1', 'BA.ADAPTER')
