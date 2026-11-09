-- Toasty 2.5.28 : plusieurs personnages, un tire au sort a chaque economiseur (toasty_pick, V_TOSC = dernier tire).
-- Fait NC economiseurs de suite (reveil par A entre chacun), note le personnage tire, la hauteur du bloc a la "tenue"
-- (V_TOSF = 55), garde une copie d'ecran a ce moment (snap/) et verifie : tous les personnages sortent, jamais deux fois
-- de suite le meme, l'animation va au bout, le cri part une fois par economiseur.
-- ex. : NC=14 mame neogeo ngjb -hashpath hash -rompath . -video none -sound none -nothrottle -autoboot_script toasty_chars.lua
if _G.reg then return end
_G.reg = true
local m = manager.machine
local mem = m.devices[":maincpu"].spaces["program"]
local F = {} for tag, p in pairs(m.ioport.ports) do for name, f in pairs(p.fields) do F[name] = f end end
local A = F["P1 A"] or F["P1 Button 1"]
local R = 0x100000
local NC = tonumber(os.getenv("NC") or "12")
local n, n0, st, t0, cyc = 0, nil, "idle", 0, 0
local picks, shots, seen, bad, anim = {}, {}, {}, 0, 0
local lastc = nil
local function lg(s) print(s) end
local zp = m.devices[":audiocpu"].spaces["program"]
local shouts, zon_prev = 0, 0
emu.register_frame_done(function()
  if not n0 then if mem:read_u32(R + 272) == 0x4E474A42 then n0 = true else return end end
  n = n + 1
  local zon = zp:read_u8(0xFC15)
  if zon == 1 and zon_prev == 0 then shouts = shouts + 1 end
  zon_prev = zon
  local s, sv, f = mem:read_u16(R + 1720), mem:read_u16(R + 242), mem:read_u16(R + 1722)
  if st == "idle" then
    if n >= 300 and n >= t0 then mem:write_u16(R + 0xF0, 17700); st = "saver"; t0 = n; anim = 0 end
  elseif st == "saver" then
    if sv == 1 and s == 2 then
      local c = mem:read_u16(R + 1730)
      if f == 55 then
        picks[#picks + 1] = c; seen[c] = true
        local sh = mem:read_u32(R + 1726)
        lg(string.format("economiseur %d : personnage %d (bloc 0x%X), cri %d", #picks, c, sh, shouts))
        if lastc == c and not _G.one then bad = bad + 1; lg("  !! meme personnage deux fois de suite") end
        lastc = c
        m.video:snapshot()
      end
    elseif s == 3 and sv == 1 and #picks > cyc then
      cyc = #picks; st = "wake"; t0 = n + 30; A:set_value(1)
    elseif n - t0 > 4000 then lg("  !! pas de Toasty apres 4000 images"); bad = bad + 1; st = "wake"; t0 = n + 30; A:set_value(1) end
  elseif st == "wake" then
    if n == t0 - 27 then A:set_value(0) end
    if n >= t0 then
      if cyc >= NC then
        local cnt = 0 for _ in pairs(seen) do cnt = cnt + 1 end
        lg(string.format("FIN : %d economiseurs, %d personnages differents, %d cris, %d anomalies", cyc, cnt, shouts, bad))
        m:exit()
      end
      st = "idle"; t0 = n + 30
    end
  end
  if n > 400000 then lg("TIMEOUT"); m:exit() end
end)
