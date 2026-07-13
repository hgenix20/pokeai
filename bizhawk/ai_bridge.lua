-- ai_bridge.lua — lets the Python pokeai brain read RAM and press buttons in
-- BizHawk (EmuHawk) over a local socket. Load in BizHawk's Lua Console
-- (Tools > Lua Console > Open Script) ALONGSIDE CrowdControl's connector: it
-- uses port 51055 (CrowdControl uses 23884), so the two coexist.
--
-- BizHawk plays FireRed natively (smooth video + audio); this script only sets
-- the joypad to Python's decision each frame and answers memory reads. Socket
-- pattern mirrors CrowdControl's connector (socket.core). Text protocol,
-- newline-delimited:
--   R a1 s1 a2 s2 ...   -> "v1 v2 ..."   (read u8/u16/u32 at each addr)
--   M addr len          -> "<hex>"       (byte block, hex)
--   I b1,b2,...         -> "ok"          (hold buttons; empty = none)
--   T b1,b2,... frames  -> "ok"          (tap buttons for N frames)
--   S <path>            -> "ok"          (save a PNG screenshot to <path>)
--   K <path>            -> "ok"          (save game state to file <path>)
--   L <path>            -> "ok"          (load game state from file <path>)
--   P                   -> "pong"

if client.getversion ~= nil and tonumber(client.getversion():sub(1,1)) >= 2
   and tonumber(client.getversion():sub(3,3)) >= 9 then
  -- 2.9+: nothing special needed for memory.* here
end

local socket = require('socket.core')
local HOST, PORT = '127.0.0.1', 51055
local DOMAIN = 'System Bus'

local conn = nil
local rxbuf = ''
local held = {}
local tap = {}
local tap_frames = 0
local frame = 0
local last_try = -1000
local last_cmd = 0          -- frame we last heard a command (for stale-link detection)

local function try_connect()
  if frame - last_try < 60 then return end   -- retry ~once/sec
  last_try = frame
  local c = socket.tcp()
  local ok = c:connect(HOST, PORT)
  if ok then
    c:settimeout(0)
    conn = c
    rxbuf = ''
    last_cmd = frame
    console.log('ai_bridge: connected to pokeai on ' .. PORT)
  else
    c:close()
    conn = nil
  end
end

local function read_val(addr, size)
  if size == 1 then return memory.read_u8(addr, DOMAIN) end
  if size == 2 then return memory.read_u16_le(addr, DOMAIN) end
  return memory.read_u32_le(addr, DOMAIN)
end

local function handle(line)
  local op = line:sub(1, 1)
  if op == 'R' then
    local nums = {}
    for tok in line:gmatch('%S+') do nums[#nums + 1] = tok end
    local out, i = {}, 2
    while i + 1 <= #nums do
      out[#out + 1] = tostring(read_val(tonumber(nums[i]), tonumber(nums[i + 1])))
      i = i + 2
    end
    return table.concat(out, ' ')
  elseif op == 'M' then
    local addr, len = line:match('^M%s+(%S+)%s+(%S+)')
    addr, len = tonumber(addr), tonumber(len)
    local parts = {}
    for k = 0, len - 1 do
      parts[#parts + 1] = string.format('%02x', memory.read_u8(addr + k, DOMAIN))
    end
    return table.concat(parts)
  elseif op == 'I' then
    held = {}
    for b in (line:match('^I%s+(.*)') or ''):gmatch('[^,]+') do held[b] = true end
    return 'ok'
  elseif op == 'T' then
    local btns, frames = line:match('^T%s+(%S*)%s+(%S+)')
    tap = {}
    if btns then for b in btns:gmatch('[^,]+') do tap[b] = true end end
    tap_frames = tonumber(frames) or 0
    return 'ok'
  elseif op == 'S' then
    local path = line:match('^S%s+(.*)')
    if path and #path > 0 then
      client.screenshot(path)
      return 'ok'
    end
    return 'err'
  elseif op == 'K' then
    local path = line:match('^K%s+(.*)')
    if path and #path > 0 then savestate.save(path); return 'ok' end
    return 'err'
  elseif op == 'L' then
    local path = line:match('^L%s+(.*)')
    if path and #path > 0 then savestate.load(path); return 'ok' end
    return 'err'
  elseif op == 'P' then
    return 'pong'
  elseif op == 'B' then
    -- power-cycle to the title screen (FIXLIST FL-1: "New Game" must not
    -- run against a loaded save)
    client.reboot_core()
    return 'ok'
  end
  return 'err'
end

local function pump()
  if not conn then try_connect(); return end
  local data, err, partial = conn:receive('*a')   -- non-blocking: grabs all available
  local got = data or partial
  if got and #got > 0 then rxbuf = rxbuf .. got end
  if err == 'closed' then conn:close(); conn = nil; return end
  while true do
    local nl = rxbuf:find('\n')
    if not nl then break end
    local line = rxbuf:sub(1, nl - 1)
    rxbuf = rxbuf:sub(nl + 1)
    -- pcall so one bad command (e.g. an invalid screenshot path) can NEVER kill
    -- the bridge mid-session; reply 'err' and keep serving.
    local ok, resp = pcall(handle, line)
    if not ok then resp = 'err' end
    conn:send(resp .. '\n')
    last_cmd = frame
  end
  -- pokeai polls constantly (<1s); a long silence means the process died/restarted,
  -- so drop the half-open link and reconnect (no manual toggle needed).
  if frame - last_cmd > 480 then conn:close(); conn = nil end
end

console.log('ai_bridge: waiting for pokeai on 127.0.0.1:' .. PORT)
while true do
  frame = frame + 1
  pump()
  -- NB: no controller index. Passing one makes BizHawk prefix button names with
  -- "P1 " (e.g. "P1 Start"), which do NOT exist for the single-controller GBA
  -- (its buttons are unprefixed: "Start"/"A"/...), so input silently no-ops.
  if tap_frames > 0 then
    joypad.set(tap)
    tap_frames = tap_frames - 1
  else
    joypad.set(held)
  end
  emu.frameadvance()
end
