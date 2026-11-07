-- Toasty (2.5.26) : CASE = album (economiseur des l'image 300, puis passage AUTO au 3e album : albums courts), time (20 min
-- atteintes pendant l'economiseur), pending (atteintes hors economiseur), wake (appui pendant l'animation), off (ROM sans
-- l'option). Affiche les changements de V_TOST (RAM+1720 : 0 arme, 1 declenche, 2 anime, 3 passe) et l'etat final.
-- ex. : CASE=time mame neogeo ngjb -hashpath hash -rompath . -autoboot_script toasty_cases.lua
if _G.reg then return end
_G.reg = true
local m = manager.machine
local mem = m.devices[":maincpu"].spaces["program"]
local F = {} for tag, p in pairs(m.ioport.ports) do for name, f in pairs(p.fields) do F[name] = f end end
local B = F["P1 B"] or F["P1 Button 2"]
local A = F["P1 A"] or F["P1 Button 1"]
local R, n, last = 0x100000, 0, -1
local CASE = os.getenv("CASE")
local vr, addr, inc = {}, 0, 1
_G.tap = mem:install_write_tap(0x3C0000, 0x3C0005, "vram", function(off, data, mask)
  if off == 0x3C0000 then addr = data
  elseif off == 0x3C0002 then
    if addr >= 0x8000 and addr < 0x8600 then vr[addr] = data end
    addr = (addr & 0x8000) | ((addr + inc) & 0x7FFF)
  elseif off == 0x3C0004 then inc = data; if inc >= 0x8000 then inc = inc - 0x10000 end end
end)
local wokeat = 0
emu.register_frame_done(function()
  n = n + 1
  local s = mem:read_u16(R + 1720)
  if s ~= last then
    print(string.format("image %d : V_TOST %d -> %d (economiseur %d, V_TOSA %d, jeu %d)", n, last, s, mem:read_u16(R + 242), mem:read_u16(R + 1724), mem:read_u16(R + 64)))
    last = s
  end
  if CASE == "time" then
    if n == 300 then mem:write_u16(R + 0xF0, 17700) end
    if n == 1200 then mem:write_u32(R + 1726, 71000) end
  elseif CASE == "pending" then
    if n == 400 then mem:write_u32(R + 1726, 71000) end
    if n == 1400 then mem:write_u16(R + 0xF0, 17700) end
  elseif CASE == "wake" then
    if n == 300 then mem:write_u16(R + 0xF0, 17700) end
    if n == 1200 then mem:write_u32(R + 1726, 71000) end
    if s == 2 and mem:read_u16(R + 1722) == 60 and wokeat == 0 then wokeat = n; A:set_value(1) end
    if wokeat > 0 and n == wokeat + 3 then A:set_value(0) end
    if wokeat > 0 and n == wokeat + 40 then
      local vis = 0
      for sp = 326, 333 do if ((vr[0x8200 + sp] or 0) & 0x3F) ~= 0 then vis = vis + 1 end end
      print(string.format("apres reveil : economiseur %d, colonnes Toasty visibles %d, en pause %d", mem:read_u16(R + 242), vis, mem:read_u16(R + 68)))
    end
    if wokeat > 0 and n == wokeat + 100 then mem:write_u16(R + 0xF0, 17700) end
  elseif CASE == "off" then
    if n == 300 then mem:write_u16(R + 0xF0, 17700) end
    if n == 1200 then mem:write_u32(R + 1726, 71000) end
  elseif CASE == "album" then
    if n == 300 then mem:write_u16(R + 0xF0, 17700) end
  end
  if n == tonumber(os.getenv("NF") or "4300") then
    local vis = 0
    for sp = 326, 333 do if ((vr[0x8200 + sp] or 0) & 0x3F) ~= 0 then vis = vis + 1 end end
    print(string.format("FIN %s image %d : V_TOST %d, economiseur %d, colonnes Toasty visibles %d, lecture %d", CASE, n, s, mem:read_u16(R + 242), vis, mem:read_u16(R + 6)))
    m:exit()
  end
end)
