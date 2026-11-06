-- Cout de l'economiseur dans l'interruption VBlank (lignes). Necessite une ROM instrumentee : dans draw3.S, entourer
-- 'bsr saver_scroll' de 'move.w 0x3C0006,0x1003F0' et 'move.w 0x3C0006,0x1003F2' (compteur de ligne avant / apres).
if _G.reg then return end
_G.reg = true
local m = manager.machine
local mem = m.devices[":maincpu"].spaces["program"]
local n, mx, sum, cnt = 0, 0, 0, 0
emu.register_frame_done(function()
  n = n + 1
  if n == 700 then mem:write_u16(0x1000F0, 53262) end
  if n > 702 and mem:read_u16(0x1000F2) == 1 then _G.on = (_G.on or 0) + 1 end
  if n > 702 and (_G.on or 0) > 2 then   -- seulement economiseur actif (2.5.20 : il demarre 2 images apres la demande)
    local a, b = mem:read_u16(0x1003F0) >> 7, mem:read_u16(0x1003F2) >> 7
    local d = (b - a) % 264
    if n > 704 then local k = "tout"; _G.mx = _G.mx or {}; if d > (_G.mx[k] or 0) then _G.mx[k] = d end end; if d > 40 then print("image " .. n .. " : " .. d .. " lignes") end
    if b < 0x100 and a >= 0x100 then d = (b + 264 - a) % 264 end
    if d > mx then mx = d end; sum = sum + d; cnt = cnt + 1
  end
  if n == 702 + 60 * 240 then print("max sur 4 min : " .. (_G.mx.tout or 0)); print(string.format("IRQ saver cost: mean %.1f lines, max %d lines (frame = 264 lines, vblank = 40)", sum / cnt, mx)); m:exit() end
end)
