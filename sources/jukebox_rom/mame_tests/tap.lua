if _G.reg then return end
_G.reg = true
local m = manager.machine
local mem = m.devices[":maincpu"].spaces["program"]
local fld
for tag, p in pairs(m.ioport.ports) do for name, f in pairs(p.fields) do if name == "P1 A" then fld = f end end end
local out = io.open("tap.bin", "wb")
local n, on = 0, false
_G.tp = mem:install_write_tap(0x320000, 0x320001, "t", function(off, data, mask)
  if on then
    if mask & 0xff00 ~= 0 then out:write(string.char((data >> 8) & 0xff)) else out:write(string.char(data & 0xff)) end
  end
end)
emu.register_frame_done(function()
  n = n + 1
  if n == 400 then mem:write_u16(0x100004, 3) end
  if n == 415 then on = true end
  if n == 420 then fld:set_value(1) end
  if n == 430 then fld:set_value(0) end
  if n == 700 then out:close(); on=false end
end)
