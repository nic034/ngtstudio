if _G.reg then return end
_G.reg = true
local m = manager.machine
local mem = m.devices[":maincpu"].spaces["program"]
local F = {}
for tag, p in pairs(m.ioport.ports) do for name, f in pairs(p.fields) do F[name] = f end end
local ev = {}
local function press(name, at, len) ev[#ev+1] = {at, name, 1}; ev[#ev+1] = {at + (len or 6), name, 0} end
press("P1 Down", 420) press("P1 Down", 432) press("P1 Down", 444) press("P1 Down", 456)
press("P1 A", 480)
press("1 Player Start", 700)
press("P1 A", 1000) press("P1 A", 1100)     -- pause / reprise en plein ecran
press("P1 D", 1200)                         -- piste suivante en plein ecran
press("1 Player Start", 1400)
local shots = {[690]=1, [900]=1, [1050]=1, [1300]=1, [1450]=1}
local n = 0
emu.register_frame_done(function()
  n = n + 1
  for _, e in ipairs(ev) do if e[1] == n then F[e[2]]:set_value(e[3]) end end
  if shots[n] then m.video:snapshot()
    print(string.format("f=%d full=%d play=%d pause=%d pt=%d secs=%d", n, mem:read_u16(0x100068), mem:read_u16(0x100006), mem:read_u16(0x100044), mem:read_u16(0x100042), mem:read_u16(0x10001A))) end
end)
