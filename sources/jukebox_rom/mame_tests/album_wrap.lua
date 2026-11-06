-- fin du dernier album : la lecture doit repartir sur le premier (mode AUTO)
if _G.reg then return end
_G.reg = true
local m = manager.machine
local mem = m.devices[":maincpu"].spaces["program"]
local F = {} for tag, p in pairs(m.ioport.ports) do for name, f in pairs(p.fields) do F[name] = f end end
local A = F["P1 A"] or F["P1 Button 1"]
local n, last = 0, ""
local maxf = tonumber(os.getenv("MAXF") or "60000")
emu.register_frame_done(function()
  n = n + 1
  if n == 700 then
    local idx = mem:read_u32(0x100024)
    local ng = mem:read_u16(0x100022)
    local gofs = idx + mem:read_u32(idx + 8) + (ng - 1) * 32
    local nt = mem:read_u16(gofs + 26)
    local start = tonumber(os.getenv("FROMEND") or "1")
    mem:write_u16(0x100002, ng - 1); mem:write_u16(0x100004, nt - start)
    print(string.format("jeux=%d, dernier jeu %d pistes ; lance la piste %d", ng, nt, nt - start + 1))
    A:set_value(1)
  end
  if n == 705 then A:set_value(0) end
  if n > 705 then
    local s = string.format("jeu %d piste %d play=%d zst=%d", mem:read_u16(0x100040), mem:read_u16(0x100042), mem:read_u16(0x100006), mem:read_u16(0x100048))
    if s ~= last then print(string.format("%7.1f s : %s", n / 59.185, s)); last = s end
    if (mem:read_u16(0x100040) == 0 and mem:read_u16(0x100042) == 1) or n > maxf then m:exit() end
  end
end)
