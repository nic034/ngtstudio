-- Test economiseur sine scroll : textes, sprites caches au reveil, piece MVS pendant l'economiseur.  PASS / FAIL.
if _G.reg then return end
_G.reg = true
local m = manager.machine
local mem = m.devices[":maincpu"].spaces["program"]
local F = {}
for tag, p in pairs(m.ioport.ports) do for name, f in pairs(p.fields) do F[name] = f end end
local function find(...) for _, k in ipairs({...}) do if F[k] then return k end end end
local DOWN, B, A, COIN = find("P1 Down"), find("P1 B", "P1 Button 2"), find("P1 A", "P1 Button 1"), find("Coin 1")
local spr = m.devices[":spritegen"] or m.devices[":sprites"]
-- lecture de la VRAM : par l'interface de la puce (registres $3C0000/$3C0002), sans perturber : on lit via la memoire video MAME si dispo
local function vram(a)
  mem:write_u16(0x3C0000, a); return mem:read_u16(0x3C0002)
end
local n, pass, fail = 0, 0, 0
local function chk(c, w) if c then pass = pass + 1 else fail = fail + 1; print("FAIL f=" .. n .. " " .. w) end end
local function text() local a = mem:read_u32(0x1000FC); local s = "" for i = 0, 70 do local c = mem:read_u8(a + i); if c == 0 then break end s = s .. string.char(c) end return s end
local Q = {}
local function at(f, fn) Q[f] = fn end
local function press(k, f) at(f, function() F[k]:set_value(1) end); at(f + 5, function() F[k]:set_value(0) end) end
-- damier 1..24, objets 25..64 (nombre variable : ignores ici), texte 65..145, petit texte 146..227
local function vis_count() local c = 0 for i = 1, 227 do if (i <= 24 or i >= 65) and vram(0x8200 + i) ~= 0 then c = c + 1 end end return c end
local function all_count() local c = 0 for i = 1, 227 do if vram(0x8200 + i) ~= 0 then c = c + 1 end end return c end
at(700, function() mem:write_u16(0x1000F0, 53262) end)
at(760, function() chk(mem:read_u16(0x1000F2) == 1, "saver on (playing)"); chk(text():find("ENJOY") ~= nil, "playing -> ENJOY text: " .. text()); chk(vis_count() == 187, "187 sprites set (24 checkerboard + 81 text + 82 info): " .. vis_count()) end)
at(780, function() local a = vram(0x8201); local b = vram(0x8201); chk(a == b, "vram read stable") end)
press(DOWN, 800)
at(840, function() chk(mem:read_u16(0x1000F2) == 0, "DOWN wakes"); chk(all_count() == 0, "all sprites hidden after wake (boxes included): " .. all_count()) end)
press(A, 860)                                                   -- pause
at(900, function() chk(mem:read_u16(0x100044) == 1, "paused"); mem:write_u16(0x1000F0, 53262) end)
at(960, function() chk(text():find("THANKS") ~= nil, "pause -> THANKS text: " .. text()) end)
press(A, 1000)                                                  -- reveil (l'appui est consomme : reste en pause)
at(1040, function() chk(mem:read_u16(0x1000F2) == 0 and mem:read_u16(0x100044) == 1, "A wakes, consumed (still paused)") end)
press(A, 1060)                                                  -- reprise
press(B, 1100)                                                  -- stop
at(1140, function() chk(mem:read_u16(0x100006) == 0, "stopped"); mem:write_u16(0x1000F0, 53262) end)
at(1200, function() chk(text():find("THANKS") ~= nil, "stopped -> THANKS text: " .. text()) end)
if COIN then
  press(COIN, 1300)                                             -- MVS : piece pendant l'economiseur
  at(1500, function() local sv = mem:read_u16(0x1000F2); chk((sv == 1 and vis_count() == 187) or (sv == 0 and all_count() == 0), "coin: sprites shown <=> saver on (saver=" .. sv .. ", sprites=" .. all_count() .. ")") end)
end
local last, stall = 0, 0
emu.register_frame_done(function()
  n = n + 1
  if Q[n] then Q[n]() end
  local t = mem:read_u16(0x100060)
  if t == last then stall = stall + 1 else stall = 0 end
  last = t
  if stall == 120 and n > 500 then fail = fail + 1; print("FAIL f=" .. n .. " main loop frozen") end
  if n == 1600 then print(string.format("RESULT pass=%d fail=%d", pass, fail)); m:exit() end
end)
