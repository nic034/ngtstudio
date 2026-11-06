-- Fuzz manette + economiseur : appuis aleatoires, economiseur force toutes les 600 images ; gel, reset, Z80, transitions
if _G.boots then _G.boots = _G.boots + 1; return end
_G.boots = 1
local m = manager.machine
local mem = m.devices[":maincpu"].spaces["program"]
local z = m.devices[":audiocpu"].spaces["program"]
local F, keys = {}, {}
for tag, p in pairs(m.ioport.ports) do for name, f in pairs(p.fields) do F[name] = f end end
for _, k in ipairs({"P1 Up", "P1 Down", "P1 Left", "P1 Right", "P1 A", "P1 B", "P1 C", "P1 D", "1 Player Start", "P1 Start", "P1 Select"}) do if F[k] then keys[#keys + 1] = k end end
math.randomseed(1234)
local n, last, stall, maxstall, ons, offs, held, zdead, empty = 0, 0, 0, 0, 0, 0, {}, 0, 0
local prev = 0
emu.register_frame_done(function()
  n = n + 1
  if n < 700 then return end
  for k, t in pairs(held) do if n >= t then F[k]:set_value(0); held[k] = nil end end
  if n % 600 == 0 then mem:write_u16(0x1000F0, 35505) end
  local sv = mem:read_u16(0x1000F2)
  if sv ~= prev then if sv == 1 then ons = ons + 1 else offs = offs + 1 end; prev = sv end
  if math.random() < (sv == 1 and 0.01 or 0.06) then local k = keys[math.random(#keys)]; F[k]:set_value(1); held[k] = n + math.random(2, 20) end
  local t = mem:read_u16(0x100060)
  if t ~= last and stall >= 120 then _G.after = n + 30 end
  if _G.after == n then print(string.format('APRES MENU f=%d ticks repartis, saver=%d play=%d', n, mem:read_u16(0x1000F2), mem:read_u16(0x100006))); m.video:snapshot() end
  if t == last then stall = stall + 1; if stall > maxstall then maxstall = stall end; if stall == 120 or stall == 1200 then print(string.format("GEL f=%d stall=%d systeme(10FD80)=%02x saver=%d play=%d pause=%d req=%02x", n, stall, mem:read_u8(0x10FD80), mem:read_u16(0x1000F2), mem:read_u16(0x100006), mem:read_u16(0x100044), mem:read_u8(0x10FDAE))); end else stall = 0 end
  last = t
  if mem:read_u16(0x100020) ~= 0 then zdead = zdead + 1 end
  if n == 700 + 60 * 360 then
    print(string.format("FUZZ 6 min : economiseur active %d fois, reveille %d fois | plus long gel boucle=%d images | redemarrages=%d | images Z80 muet=%d | lecture=%d",
      ons, offs, maxstall, _G.boots - 1, zdead, mem:read_u16(0x100006)) .. " | economiseur actif a la fin=" .. sv)
    m:exit()
  end
end)
