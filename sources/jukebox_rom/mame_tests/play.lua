if _G.reg then return end
_G.reg = true
local m = manager.machine
local mem = m.devices[":maincpu"].spaces["program"]
local TRK = tonumber(os.getenv("JB_TRK") or "0")
local fld
for tag, p in pairs(m.ioport.ports) do for name, f in pairs(p.fields) do if name == "P1 A" then fld = f end end end
local n = 0
emu.register_frame_done(function()
  n = n + 1
  if n == 400 then mem:write_u16(0x100004, TRK) end
  if n == 420 then fld:set_value(1) end
  if n == 430 then fld:set_value(0) end
  if n == 600 or n == 1500 then m.video:snapshot() end
  if n % 60 == 0 then
    print(string.format("f=%d play=%d zdead=%d reply=%02x free=%d left=%d inloop=%d soff=%x",
      n, mem:read_u16(0x100006), mem:read_u16(0x100020), mem:read_u16(0x10002A) & 0xff,
      mem:read_u16(0x100018), mem:read_u32(0x10000C), mem:read_u16(0x10003A), mem:read_u32(0x100008)))
  end
end)
