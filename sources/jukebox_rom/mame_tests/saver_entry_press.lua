-- appui B (stop) pendant l'entree dans l'economiseur : il doit seulement le reveiller (la lecture continue)
if _G.reg then return end
_G.reg = true
local m = manager.machine
local mem = m.devices[":maincpu"].spaces["program"]
local F = {} for tag, p in pairs(m.ioport.ports) do for name, f in pairs(p.fields) do F[name] = f end end
local B = F["P1 B"] or F["P1 Button 2"]
local n, res, k = 0, {}, 0
local base = 900
emu.register_frame_done(function()
  n = n + 1
  local t = n - base
  if t < 0 then return end
  local cyc, off = t // 300, t % 300
  if cyc > 5 then print("ENTREE " .. table.concat(res, " ")); m:exit() return end
  if off == 0 then mem:write_u16(0x1000F0, 17755) end            -- l'economiseur s'allume au prochain passage
  if off == 1 + cyc then B:set_value(1) end                          -- appui a 1..6 images apres
  if off == 3 + cyc then B:set_value(0) end
  if off == 200 then res[#res + 1] = string.format("decalage %d: lecture=%d eco=%d", cyc + 1, mem:read_u16(0x100006), mem:read_u16(0x1000F2)) end
end)
