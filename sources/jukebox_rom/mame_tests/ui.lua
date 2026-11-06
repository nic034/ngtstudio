if _G.reg then return end
_G.reg = true
local m = manager.machine
local mem = m.devices[":maincpu"].spaces["program"]
local zm = m.devices[":audiocpu"].spaces["program"]
local F = {}
for tag, p in pairs(m.ioport.ports) do for name, f in pairs(p.fields) do F[name] = f end end
local ev = {}
local function press(name, at, len) ev[#ev+1] = {at, name, 1}; ev[#ev+1] = {at + (len or 6), name, 0} end
press("P1 Down", 400) press("P1 Down", 412) press("P1 Down", 424)
press("P1 A", 460)
press("P1 A", 760)           -- pause
press("P1 A", 900)           -- reprise
press("P1 D", 1100)          -- suivante
press("P1 Right", 1400)      -- jeu suivant (la lecture continue)
press("P1 Down", 1500, 60)   -- maintenu : repetition
press("P1 B", 1700)          -- stop
press("P1 Left", 1800)       -- retour jeu 1, curseur piste 1 (jingle court sans boucle)
press("P1 A", 1820)
local shots = {[300]=1, [700]=1, [800]=1, [1300]=1, [1450]=1, [1600]=1, [1750]=1}
local n = 0
emu.register_frame_done(function()
  n = n + 1
  for _, e in ipairs(ev) do if e[1] == n then F[e[2]]:set_value(e[3]) end end
  if shots[n] then m.video:snapshot() end
  if n % 50 == 0 or shots[n] then
    print(string.format("f=%d game=%d trk=%d top=%d play=%d pg=%d pt=%d pause=%d zst=%d secs=%d | z80 state=%d paused=%d",
      n, mem:read_u16(0x100002), mem:read_u16(0x100004), mem:read_u16(0x100046), mem:read_u16(0x100006), mem:read_u16(0x100040),
      mem:read_u16(0x100042), mem:read_u16(0x100044), mem:read_u16(0x100048), mem:read_u16(0x10001A), zm:read_u8(0xFC06), zm:read_u8(0xFC0E)))
  end
end)
