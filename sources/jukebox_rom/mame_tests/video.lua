if _G.reg then return end
_G.reg = true
local m = manager.machine
local mem = m.devices[":maincpu"].spaces["program"]
local F = {}
for tag, p in pairs(m.ioport.ports) do for name, f in pairs(p.fields) do F[name] = f end end
local ev = {}
local function press(name, at, len) ev[#ev+1] = {at, name, 1}; ev[#ev+1] = {at + (len or 6), name, 0} end
press("P1 Down", 380) press("P1 Down", 392) press("P1 Down", 404) press("P1 Down", 416)
press("P1 A", 440)                 -- Art of Fighting 2, piste 5
press("1 Player Start", 1040)      -- plein ecran apres ~10 s
press("1 Player Start", 1980)      -- retour a la liste apres ~16 s
local n = 0
emu.register_frame_done(function()
  n = n + 1
  for _, e in ipairs(ev) do if e[1] == n then F[e[2]]:set_value(e[3]) end end
  if n == 445 then print(string.format("PLAY f=%d pt=%d", n, mem:read_u16(0x100042))) end
end)
