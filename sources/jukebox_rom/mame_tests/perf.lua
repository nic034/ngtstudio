if _G.reg then return end
_G.reg = true
local m = manager.machine
local mem = m.devices[":maincpu"].spaces["program"]
local F = {}
for tag, p in pairs(m.ioport.ports) do for name, f in pairs(p.fields) do F[name] = f end end
local n, lastt, st = 0, -1, 0
emu.register_frame_done(function()
  n = n + 1
  if n == 400 then mem:write_u16(0x100004, 3); F["P1 A"]:set_value(1) end
  if n == 406 then F["P1 A"]:set_value(0) end
  local t = mem:read_u16(0x100060)
  if n > 400 and t == lastt then st = st + 1 end
  lastt = t
  if n == 460 or n == 1000 or n == 1600 or n == 2200 then print(string.format("f=%d frames without main loop progress so far: %d  secs=%d", n, st, mem:read_u16(0x10001A))) end
end)
