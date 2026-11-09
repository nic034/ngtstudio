-- Toasty 2.5.28 : economiseur arme (V_TOST = 0), reveil par A, puis changement de piste ecran de lecture affiche :
-- ni personnage ni cri (V_TOST ne passe pas a 1 ou 2, Z80 sfxon reste 0).  Puis 2e economiseur : il se rearme et joue.
if _G.reg then return end
_G.reg = true
local m = manager.machine
local mem = m.devices[":maincpu"].spaces["program"]
local zp = m.devices[":audiocpu"].spaces["program"]
local F = {} for tag, p in pairs(m.ioport.ports) do for name, f in pairs(p.fields) do F[name] = f end end
local A = F["P1 A"] or F["P1 Button 1"]
local R = 0x100000
local n, n0, st, t0, tracks0 = 0, nil, "idle", 0, 0
local bad, pistes, shout = 0, 0, 0
local lastpiste = nil
local function lg(s) print(s) end
emu.register_frame_done(function()
  if not n0 then if mem:read_u32(R + 272) == 0x4E474A42 then n0 = true else return end end
  n = n + 1
  local s, sv = mem:read_u16(R + 1720), mem:read_u16(R + 242)
  local piste = mem:read_u16(R + 64) * 100 + mem:read_u16(R + 66)
  if st == "idle" and n == 300 then mem:write_u16(R + 0xF0, 17700); st = "armed" end
  if st == "armed" and sv == 1 and s == 0 then lg(string.format("image %d : economiseur arme, reveil (piste %d)", n, piste)); A:set_value(1); t0 = n; st = "woke"; lastpiste = piste end
  if st == "woke" then
    if n == t0 + 3 then A:set_value(0) end
    if piste ~= lastpiste then pistes = pistes + 1; lg(string.format("image %d : piste %d -> %d (economiseur %d, V_TOST %d)", n, lastpiste, piste, sv, s)); lastpiste = piste end
    if (s == 1 or s == 2) and sv == 0 then bad = bad + 1; lg("  !! Toasty hors economiseur") end
    if zp:read_u8(0xFC15) == 1 then bad = bad + 1; lg("  !! cri hors economiseur") end
    if n == t0 + 2500 then
      lg(string.format("RESULTAT reveil : %d changements de piste sans economiseur, %d anomalies", pistes, bad))
      mem:write_u16(R + 0xF0, 17700); st = "second"; t0 = n
    end
  end
  if st == "second" then
    if s == 2 and shout == 0 then shout = 1; lg(string.format("image %d : 2e economiseur : Toasty parti (V_TOSC %d)", n, mem:read_u16(R + 1730))) end
    if n == t0 + 4000 then lg(string.format("FIN : 2e economiseur Toasty %s, anomalies %d", shout == 1 and "OK" or "ABSENT", bad + (shout == 1 and 0 or 1))); m:exit() end
  end
end)
