-- empreinte de la RAM de palettes (palettes 0..24 + fond) a trois moments : lecture, economiseur, apres reveil
if _G.reg then return end
_G.reg = true
local m = manager.machine
local mem = m.devices[":maincpu"].spaces["program"]
local F = {} for tag, p in pairs(m.ioport.ports) do for name, f in pairs(p.fields) do F[name] = f end end
local B = F["P1 B"] or F["P1 Button 2"]
local n, out = 0, {}
local function dump(tag)
  local s = {}
  for p = 0, 24 do for c = 0, 15 do
    if not (p >= 10 and p <= 15 and c == 1) and not (p == 16 and c >= 1 and c <= 8) and not (p >= 19 and c == 15) then  -- couleurs animees exclues
      s[#s + 1] = string.format("%04X", mem:read_u16(0x400000 + p * 32 + c * 2)) end end end
  s[#s + 1] = string.format("%04X", mem:read_u16(0x401FFE))
  out[#out + 1] = tag .. "=" .. table.concat(s):sub(1, 0) .. string.format("%08X", (function(t) local h = 0 for i = 1, #t do h = (h * 31 + t:byte(i)) % 4294967296 end return h end)(table.concat(s)))
end
emu.register_frame_done(function()
  n = n + 1
  if n == 900 then dump("lecture") end
  if n == 950 then mem:write_u16(0x1000F0, 17750) end
  if n == 1100 then dump("economiseur") end
  if n == 1150 then B:set_value(1) end
  if n == 1155 then B:set_value(0) end
  if n == 1300 then dump("reveil"); print("PAL " .. table.concat(out, " ")); m:exit() end
end)
