-- 2.5.36 : Bas + Start pendant le Toasty = un des 4 sons MK3 (au hasard), puis l'economiseur s'arrete ; jamais dans une
-- autre condition.  Scenarios positifs et negatifs ; observe le Z80 : sfxon (0xFC15) et sfxsel (0xFC1F : 0 = cri du Toasty,
-- 1..4 = son MK3) a chaque depart de son, et l'etat du 68000 (V_SAVER = RAM+242, V_TOST = RAM+1720, V_TOSF = RAM+1722).
-- ex. : mame neogeo ngjb -hashpath hash -rompath . -video none -sound none -nothrottle -autoboot_script toasty_combo.lua
if _G.reg then return end
_G.reg = true
local m = manager.machine
local mem = m.devices[":maincpu"].spaces["program"]
local zp = m.devices[":audiocpu"].spaces["program"]
local F = {} for tag, p in pairs(m.ioport.ports) do for name, f in pairs(p.fields) do F[name] = f end end
local A, DN, ST = F["P1 A"], F["P1 Down"], F["1 Player Start"]
local R = 0x100000
local rw = function(o) return mem:read_u16(R + o) end
local lg = print
-- evenements : { frame relative, champ, valeur } ; "pre" : toasty (portrait a l'ecran, cri fini), armed (economiseur, Toasty pas
-- encore parti), ended (economiseur, Toasty fini), awake (ecran de lecture)
local S = {}
local function add(name, pre, ev, snd, saver_off) S[#S + 1] = {name = name, pre = pre, ev = ev, snd = snd, off = saver_off} end
add("A  Bas+Start ensemble",              "toasty", {{0, DN, 1}, {0, ST, 1}, {6, DN, 0}, {6, ST, 0}}, true,  true)
add("B  Bas puis Start 8 images plus tard","toasty", {{0, DN, 1}, {8, ST, 1}, {14, DN, 0}, {14, ST, 0}}, true,  true)
add("B2 Start puis Bas 10 images plus tard","toasty",{{0, ST, 1}, {10, DN, 1}, {16, DN, 0}, {16, ST, 0}}, true,  true)
add("C  Bas seul",                         "toasty", {{0, DN, 1}, {6, DN, 0}}, false, true)
add("D  Start seul",                       "toasty", {{0, ST, 1}, {6, ST, 0}}, false, true)
add("E  Bas relache avant Start",          "toasty", {{0, DN, 1}, {4, DN, 0}, {12, ST, 1}, {18, ST, 0}}, false, true)
add("F  A (autre bouton)",                 "toasty", {{0, A, 1}, {6, A, 0}}, false, true)
add("G  Bas+Start, economiseur sans Toasty","armed", {{0, DN, 1}, {0, ST, 1}, {6, DN, 0}, {6, ST, 0}}, false, true)
add("H  Bas+Start, Toasty fini",           "ended", {{0, DN, 1}, {0, ST, 1}, {6, DN, 0}, {6, ST, 0}}, false, true)
add("I  Bas+Start, ecran de lecture",      "awake", {{0, DN, 1}, {0, ST, 1}, {6, DN, 0}, {6, ST, 0}}, false, false)
-- tirage : 12 combos a des instants differents (instant de l'appui = V_TICKS)
for k = 1, 12 do
  local d = (k * 5) % 11
  add("R" .. k .. " Bas+Start (decalage " .. d .. ")", "toasty", {{d, DN, 1}, {d, ST, 1}, {d + 6, DN, 0}, {d + 6, ST, 0}}, true, true)
end
local n, n0, si, ph, t0 = 0, nil, 1, "init", 0
local started, hist, bad, picks = false, {}, 0, {}
local cur = {sound = nil, sawsnd = nil}
local zon_prev, sel_at = 0, nil
local function release() DN:set_value(0); ST:set_value(0); A:set_value(0) end
emu.register_frame_done(function()
  if not n0 then if mem:read_u32(R + 272) == 0x4E474A42 then n0 = true else return end end
  n = n + 1
  local zon, sel = zp:read_u8(0xFC15), zp:read_u8(0xFC1F)
  local rising = (zon == 1 and zon_prev == 0)
  zon_prev = zon
  local s = S[si]
  if not s then
    local ok = {}; for k, v in pairs(picks) do ok[#ok + 1] = k .. "x" .. v end
    table.sort(ok)
    lg("TIRAGE des 12 combos : sons " .. table.concat(ok, ", "))
    lg(string.format("FIN : %d scenarios, %d anomalies", #S, bad)); m:exit(); return
  end
  local sv, tst, tsf = rw(242), rw(1720), rw(1722)
  if ph == "init" then
    if n >= 300 then release(); ph = (s.pre == "awake") and "run" or "enter"; t0 = n; cur = {}
      if ph == "enter" then mem:write_u16(R + 0xF0, 17700) end end
  elseif ph == "enter" then          -- economiseur affiche, Toasty arme
    if sv == 1 and tst == 0 then
      if s.pre == "armed" then ph = "run"; t0 = n
      else mem:write_u16(R + 1720, 1); ph = "wait" end
    elseif n - t0 > 3000 then lg("  !! pas d'economiseur"); bad = bad + 1; si = si + 1; ph = "init"; t0 = n end
  elseif ph == "wait" then           -- Toasty a l'ecran ; "pre" toasty : apres le cri (image 70 de l'animation) ; ended : apres la fin
    if s.pre == "toasty" and tst == 2 and tsf >= 70 then ph = "run"; t0 = n; cur.f0 = tsf
    elseif s.pre == "ended" and tst == 3 then ph = "run"; t0 = n end
    if n - t0 > 3000 then lg("  !! Toasty pas vu"); bad = bad + 1; si = si + 1; ph = "init"; t0 = n end
  elseif ph == "run" then
    local rel = n - t0
    for _, e in ipairs(s.ev) do if e[1] + 1 == rel then e[2]:set_value(e[3]) end end
    if rising and sel >= 1 then cur.sawsnd = sel end                -- depart d'un son MK3 (1..4) ; le cri du Toasty = 0 n'est pas compte
    if rel == 120 then
      release()
      local snd = cur.sawsnd ~= nil
      local good = (snd == s.snd) and ((sv == 0) == s.off or not s.off)
      if snd and s.snd and (cur.sawsnd < 1 or cur.sawsnd > 4) then good = false end
      if snd and s.snd then picks[cur.sawsnd] = (picks[cur.sawsnd] or 0) + 1 end
      local zst = zp:read_u8(0xFC06)                                  -- Z80 : 1 = piste en cours (la musique continue)
      if zst ~= 1 then good = false end
      lg(string.format("%-42s son=%s  economiseur=%s (V_SAVER %d)  V_TOST=%d  musique=%s  %s", s.name,
        snd and ("MK3 #" .. tostring(cur.sawsnd)) or "aucun", sv == 0 and "arrete" or "actif", sv, tst, zst == 1 and "continue" or "ARRETEE", good and "OK" or "!! ANOMALIE"))
      if not good then bad = bad + 1 end
      ph = "settle"; t0 = n
    end
  elseif ph == "settle" then          -- retour a l'ecran de lecture, attente de la fin du son, puis scenario suivant
    if sv == 1 then if n - t0 == 5 then A:set_value(1) elseif n - t0 == 11 then A:set_value(0) end end
    if n - t0 > 330 then release(); si = si + 1; ph = "init"; t0 = n end
  end
  if n > 600000 then lg("TIMEOUT"); m:exit() end
end)
