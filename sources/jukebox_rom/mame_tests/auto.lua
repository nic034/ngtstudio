if _G.reg then return end
_G.reg = true
local m = manager.machine
local mem = m.devices[":maincpu"].spaces["program"]
local F = {}
for tag, p in pairs(m.ioport.ports) do for name, f in pairs(p.fields) do F[name] = f end end
local n = 0
emu.register_frame_done(function()
  n = n + 1
  if n == 1400 then mem:write_u16(0x100004, 16); F["P1 A"]:set_value(1) end   -- piste 17 (boucle de 16 s)
  if n == 1406 then F["P1 A"]:set_value(0) end
  if n == 4000 then mem:write_u16(0x100098, 1) end                              -- LOOP1 (SELECT n'existe pas sur MVS)
  if n == 4000 then m.video:snapshot() end
  if n % 300 == 0 or n == 1450 then print(string.format("f=%d play=%d pg=%d pt=%d secs=%d tlen=%d inloop=%d mode=%d", n,
     mem:read_u16(0x100006), mem:read_u16(0x100040), mem:read_u16(0x100042), mem:read_u16(0x10001A), mem:read_u16(0x100050), mem:read_u16(0x10003A), mem:read_u16(0x100098))) end
end)
