-- duree (lignes) des palettes posees par le VBlank (pal_saver / pal_norm) : entree / sortie d'economiseur repetees
if _G.reg then return end
_G.reg = true
local m = manager.machine
local mem = m.devices[":maincpu"].spaces["program"]
local F = {} for tag, p in pairs(m.ioport.ports) do for name, f in pairs(p.fields) do F[name] = f end end
local B = F["P1 B"] or F["P1 Button 2"]
local n, mx, cnt, last = 0, 0, 0, -1
emu.register_frame_done(function()
  n = n + 1
  local a, b = mem:read_u16(0x1003F0) >> 7, mem:read_u16(0x1003F2) >> 7
  local s = mem:read_u16(0x1003F4)
  if s ~= last and last >= 0 then
    local d = b - a; if d < 0 then d = d + 264 end
    if d > mx then mx = d end; cnt = cnt + 1
  end
  last = s
  local k = n % 600
  if n > 800 and k == 0 then mem:write_u16(0x1000F0, 17750) end
  if n > 800 and k == 300 then B:set_value(1) end
  if n > 800 and k == 305 then B:set_value(0) end
  if n == 800 + 600 * 12 then print(string.format("PALCOST : %d mises a jour mesurees, max %d lignes (debut de VBlank -> fin des palettes)", cnt, mx)); m:exit() end
end)
