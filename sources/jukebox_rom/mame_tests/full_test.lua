-- Test complet START / SELECT / pieces / economiseur / boutons, pour tous les BIOS.  Sortie : lignes PASS / FAIL.
if _G.reg then return end
_G.reg = true
local m = manager.machine
local mem = m.devices[":maincpu"].spaces["program"]
local cpu = m.devices[":maincpu"]
local F = {}
for tag, p in pairs(m.ioport.ports) do for name, f in pairs(p.fields) do F[name] = f end end
local function find(...)
  for _, pat in ipairs({...}) do for k, _ in pairs(F) do if k == pat then return k end end end
  return nil
end
local START = find("P1 Start", "1 Player Start")
local SELECT = find("P1 Select", "1 Player Select", "Select")
local COIN = find("Coin 1")
local BTN = { up = find("P1 Up"), down = find("P1 Down"), left = find("P1 Left"), right = find("P1 Right"),
              a = find("P1 Button 1", "P1 A"), b = find("P1 Button 2", "P1 B"), c = find("P1 Button 3", "P1 C"), d = find("P1 Button 4", "P1 D") }
print(string.format("INFO start=%s select=%s coin=%s a=%s d=%s", tostring(START), tostring(SELECT), tostring(COIN), tostring(BTN.a), tostring(BTN.d)))
local R = function(a) return mem:read_u16(a) end
local V = { full = 0x100068, play = 0x100006, pause = 0x100044, repm = 0x100098, ticks = 0x100060, saver = 0x1000F2,
            idle = 0x1000F0, trk = 0x100004, game = 0x100002 }
local n, fails, passes = 0, 0, 0
local function check(cond, what)
  if cond then passes = passes + 1 else fails = fails + 1; print(string.format("FAIL f=%d %s", n, what)) end
end
-- file d'evenements : {frame, fonction}
local Q = {}
local function at(f, fn) Q[#Q + 1] = {f, fn} end
local function press(field, f, len) if field then at(f, function() F[field]:set_value(1) end); at(f + (len or 5), function() F[field]:set_value(0) end) end end
local t = 600
at(t, function() check(R(V.play) == 1, "autoplay at boot") end)
-- 1) START x12 en lecture : la vue doit basculer a chaque fois
for i = 1, 12 do
  local f0 = t + 40 * i
  local before
  at(f0 - 1, function() before = R(V.full) end)
  press(START, f0)
  at(f0 + 30, function() check(R(V.full) ~= before, "START toggles view #" .. i) end)
end
t = t + 40 * 13
-- 2) pause (A) en vue plein ecran, START pendant la pause, la pause doit rester
at(t, function() if R(V.full) == 0 then F[START]:set_value(1) end end); at(t + 5, function() F[START]:set_value(0) end)
press(BTN.a, t + 40)
at(t + 80, function() check(R(V.pause) == 1, "A pauses (full view)") end)
press(START, t + 100)
at(t + 130, function() check(R(V.full) == 0 and R(V.pause) == 1, "START while paused: list view, still paused") end)
press(BTN.a, t + 160)
at(t + 200, function() check(R(V.pause) == 0 and R(V.play) == 1, "A resumes") end)
t = t + 240
-- 3) STOP (B) puis START a l'arret
press(BTN.b, t)
at(t + 30, function() check(R(V.play) == 0, "B stops") end)
press(START, t + 60)
at(t + 90, function() check(R(V.full) == 1, "START while stopped -> full view") end)
press(START, t + 120)
at(t + 150, function() check(R(V.full) == 0, "START while stopped -> list view") end)
press(BTN.a, t + 180)
at(t + 220, function() check(R(V.play) == 1, "A plays again") end)
t = t + 260
-- 4) SELECT (si le systeme en a un) : AUTO -> LOOP -> RAND -> AUTO (2.5.19 : trois modes)
if SELECT then
  local r0
  at(t - 1, function() r0 = R(V.repm) end)
  press(SELECT, t)
  at(t + 30, function() check(R(V.repm) == (r0 + 1) % 3, "SELECT: next mode (AUTO/LOOP/RAND)") end)
  press(SELECT, t + 60)
  at(t + 90, function() check(R(V.repm) == (r0 + 2) % 3, "SELECT: third mode") end)
  press(SELECT, t + 120)
  at(t + 150, function() check(R(V.repm) == r0, "SELECT: back to the first mode") end)
else
  at(t, function() print("INFO no SELECT on this system") end)
end
t = t + 180
-- 5) piece puis START (MVS : le BIOS appelle COIN_SOUND puis PLAYER_START)
if COIN then
  local s0
  at(t - 1, function() s0 = R(0x10001A) end)
  press(COIN, t, 8)
  at(t + 50, function() check(R(V.play) == 1 and R(0x10001A) >= s0, "coin: playback continues (no restart)") end)
  local v0
  at(t + 59, function() v0 = R(V.full) end)
  press(START, t + 60)
  at(t + 100, function() check(R(V.full) ~= v0 and R(V.play) == 1, "coin then START: view toggles, still playing") end)
  press(COIN, t + 130, 8); press(COIN, t + 160, 8)
  press(START, t + 200)
  at(t + 240, function() check(R(V.full) == v0, "2 more coins then START: toggles back") end)
end
t = t + 280
-- 5b) MVS : une minute sans rien toucher apres les pieces (minuteur du mode titre du BIOS)
if COIN then
  local s1
  at(t, function() s1 = R(0x10001A) end)
  at(t + 3600, function() check(R(V.play) == 1, "1 min after coins: still playing (secs " .. s1 .. " -> " .. R(0x10001A) .. ")") end)
  t = t + 3620
end
-- 6) les 8 directions / boutons
local function cmp_change(field, addr, f0, label)
  local v0
  at(f0 - 1, function() v0 = R(addr) end)
  press(field, f0)
  at(f0 + 30, function() check(R(addr) ~= v0, label) end)
end
cmp_change(BTN.down, V.trk, t, "DOWN moves cursor")
cmp_change(BTN.up, V.trk, t + 40, "UP moves cursor")
cmp_change(BTN.right, V.game, t + 80, "RIGHT changes game")
cmp_change(BTN.left, V.game, t + 120, "LEFT changes game back")
press(BTN.d, t + 160); at(t + 200, function() check(R(V.play) == 1, "D next track plays") end)
press(BTN.c, t + 220); at(t + 260, function() check(R(V.play) == 1, "C previous track plays") end)
t = t + 300
-- 7) economiseur en vue liste, reveil par START (consomme : la vue ne bascule pas)
at(t, function() if R(V.full) == 1 then F[START]:set_value(1) end end); at(t + 5, function() F[START]:set_value(0) end)
at(t + 40, function() mem:write_u16(V.idle, 53260) end)
at(t + 60, function() check(R(V.saver) == 1, "screen saver starts (list view)") end)
at(t + 200, function() check(R(V.saver) == 1 and R(V.play) == 1, "saver still on after 140 frames, music playing") end)
press(START, t + 220)
at(t + 250, function() check(R(V.saver) == 0 and R(V.full) == 0, "START wakes saver without toggling view") end)
t = t + 280
-- 8) economiseur en vue plein ecran, reveil par la croix
press(START, t)
at(t + 40, function() check(R(V.full) == 1, "full view before saver") end)
at(t + 50, function() mem:write_u16(V.idle, 53260) end)
at(t + 70, function() check(R(V.saver) == 1, "screen saver starts (full view)") end)
local trk0
at(t + 199, function() trk0 = R(V.trk) end)
press(BTN.down, t + 200)
at(t + 230, function() check(R(V.saver) == 0 and R(V.full) == 1 and R(V.trk) == trk0, "DOWN wakes saver, consumed") end)
press(START, t + 260)
at(t + 290, function() check(R(V.full) == 0, "back to list view") end)
t = t + 320
-- 9) appuis aleatoires, START / SELECT / pieces compris
local rnd = 12345
local function rand(k) rnd = (rnd * 1103515245 + 12345) % 2147483648; return rnd % k end
local pool = {}
for _, k in pairs(BTN) do pool[#pool + 1] = k end
pool[#pool + 1] = START; pool[#pool + 1] = START
if SELECT then pool[#pool + 1] = SELECT end
if COIN then pool[#pool + 1] = COIN end
local FUZZ0, FUZZ1 = t, t + 9000
for f = FUZZ0, FUZZ1, 7 do
  local k = pool[rand(#pool) + 1]
  press(k, f, 1 + rand(5))          -- un seul bouton a la fois (pas de combinaisons de menu UniBIOS)
end
local END = FUZZ1 + 300
at(FUZZ1 + 200, function() check(R(V.play) <= 2, "still sane after fuzz") end)
table.sort(Q, function(a, b) return a[1] < b[1] end)
local qi = 1
local lastt, stall, maxstall, resets = -1, 0, 0, 0
emu.register_frame_done(function()
  n = n + 1
  while qi <= #Q and Q[qi][1] <= n do Q[qi][2](); qi = qi + 1 end
  if n > 500 then
    local tk = R(V.ticks)
    if tk == lastt then stall = stall + 1 else stall = 0 end
    if lastt >= 0 and tk < lastt and lastt - tk < 30000 then
      resets = resets + 1
      print(string.format("RESET f=%d ticks %d -> %d user_request=%02x mode=%02x", n, lastt, tk, mem:read_u8(0x10FDAE), mem:read_u8(0x10FDAF)))
      m.video:snapshot()
    end
    if stall > maxstall then maxstall = stall end
    lastt = tk
    local pc = cpu.state["CURPC"].value
    if stall == 120 then fails = fails + 1; print(string.format("FAIL f=%d main loop frozen 2 s (pc=%06x)", n, pc)); m.video:snapshot() end
  end
  if n == END then
    check(resets == 0, "no reset (watchdog / crash)")
    check(maxstall < 60, "main loop never frozen > 1 s (max " .. maxstall .. " frames)")
    print(string.format("RESULT pass=%d fail=%d maxstall=%d", passes, fails, maxstall))
    m:exit()
  end
end)
