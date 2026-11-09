-- 2.5.36 : enregistrement audio (-wavwrite) du combo : meme chronologie avec (COMBO=1) ou sans (COMBO=0) l'appui Bas + Start.
-- La difference des deux enregistrements = le son MK3 (moins la voie de la musique qu'il remplace).  Affiche le son tire
-- (sfxsel du Z80) et la duree de l'emprunt de la voie (images) = duree du son + 20 ms.
if _G.reg then return end
_G.reg = true
local m = manager.machine
local mem = m.devices[":maincpu"].spaces["program"]
local zp = m.devices[":audiocpu"].spaces["program"]
local F = {} for tag, p in pairs(m.ioport.ports) do for name, f in pairs(p.fields) do F[name] = f end end
local DN, ST, B = F["P1 Down"], F["1 Player Start"], F["P1 B"]
local STOPMUSIC = os.getenv("STOPMUSIC") == "1"      -- B = STOP : seule la voix du Toasty / du combo reste (difference = le son pur)
local R = 0x100000
local COMBO = os.getenv("COMBO") == "1"
local n, n0, ph, t0, z0, sel, dur = 0, nil, "init", 0, 0, nil, nil
emu.register_frame_done(function()
  if not n0 then if mem:read_u32(R + 272) == 0x4E474A42 then n0 = true else return end end
  n = n + 1
  local zon = zp:read_u8(0xFC15)
  local sv, tst, tsf = mem:read_u16(R + 242), mem:read_u16(R + 1720), mem:read_u16(R + 1722)
  if STOPMUSIC and n == 120 then B:set_value(1) elseif STOPMUSIC and n == 126 then B:set_value(0) end
  if ph == "init" then if n >= 300 then mem:write_u16(R + 0xF0, 17700); ph = "enter"; t0 = n end
  elseif ph == "enter" then if sv == 1 and tst == 0 then mem:write_u16(R + 1720, 1); ph = "wait" end
  elseif ph == "wait" then if tst == 2 and tsf >= 70 then ph = "press"; t0 = n end
  elseif ph == "press" then
    local rel = n - t0
    local P = tonumber(os.getenv("PRESS") or "2")
    if COMBO and rel == P then DN:set_value(1); ST:set_value(1) end
    if COMBO and rel == P + 6 then DN:set_value(0); ST:set_value(0) end
    if zon == 1 and not z0 then z0 = nil end
    if rel > 3 and zon == 1 and not sel then sel = zp:read_u8(0xFC1F); z0 = n end
    if sel and zon == 0 and not dur then dur = n - z0 end
    if rel == 400 then print(string.format("COMBO=%s sfxsel=%s emprunt=%s images (%.3f s)", tostring(COMBO), tostring(sel), tostring(dur), (dur or 0) / 59.185)); m:exit() end
  end
end)
