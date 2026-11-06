-- Damier de l economiseur : verifie a chaque image que les 24 colonnes couvrent tout l ecran (lignes 0..223) ; amplitude et ondulation mesurees. STOPF=1 : a l arret.
if _G.reg then return end
_G.reg = true
local m = manager.machine
local mem = m.devices[":maincpu"].spaces["program"]
local F = {} for tag, p in pairs(m.ioport.ports) do for name, f in pairs(p.fields) do F[name] = f end end
local B = F["P1 B"] or F["P1 Button 2"]
local vr, addr, inc = {}, 0, 1
_G.tap = mem:install_write_tap(0x3C0000, 0x3C0005, "vram", function(off, data, mask)
  if off == 0x3C0000 then addr = data
  elseif off == 0x3C0002 then
    if addr >= 0x8200 and addr < 0x8600 then vr[addr] = data end
    addr = (addr & 0x8000) | ((addr + inc) & 0x7FFF)
  elseif off == 0x3C0004 then inc = data; if inc >= 0x8000 then inc = inc - 0x10000 end end
end)
local n, frames, gaps, tmin, bmax, bmin, amax, amin, cmax, cmin, tmaxv = 0, 0, 0, 999, -999, 999, 0, 999, -99, 99, -999
local stopat = tonumber(os.getenv("STOPF") or "0")
emu.register_frame_done(function()
  n = n + 1
  if stopat > 0 and n == 700 then B:set_value(1) end
  if stopat > 0 and n == 705 then B:set_value(0) end
  if n == 800 then mem:write_u16(0x1000F0, 35505) end
  if n > 830 and mem:read_u16(0x1000F2) == 1 then
    frames = frames + 1
    for s = 1, 24 do
      local c = vr[0x8200 + s] or 0
      local y = (496 - (c >> 7)) & 0x1FF
      if y >= 256 then y = y - 512 end
      local bot = y + (c & 0x3F) * 16 - 1
      if y > tmaxv then tmaxv = y end
      if bot < bmin then bmin = bot end
      if y > 0 or bot < 223 then gaps = gaps + 1 end
    end
    local a = mem:read_u16(0x1001CC)
    if a > amax then amax = a end
    if a < amin then amin = a end
    for j = 0, 23 do
      local v = mem:read_i16(0x10016C + 2 * j) // 128
      if v > cmax then cmax = v end
      if v < cmin then cmin = v end
    end
  end
  if n == 830 + 60 * 240 then
    print(string.format("COUVERTURE : %d images, colonnes avec trou : %d | haut le plus bas %d (doit etre <= 0), bas le plus haut %d (>= 223) | amplitude V_CKA %d..%d | ondulation %d..%d px", frames, gaps, tmaxv, bmin, amin, amax, cmin, cmax))
    m:exit()
  end
end)
