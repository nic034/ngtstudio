-- Endurance economiseur : 5 min, la musique enchaine les pistes ; tampon Z80, gel, VBlank regulier
if _G.reg then return end
_G.reg = true
local m = manager.machine
local mem = m.devices[":maincpu"].spaces["program"]
local z = m.devices[":audiocpu"].spaces["program"]
local n, empty, minfill, lastv, vbad, lastpos, posbad, tracks = 0, 0, 99999, 0, 0, -1, 0, 0
local lastpt = -1
emu.register_frame_done(function()
  n = n + 1
  if n == 700 then mem:write_u16(0x1000F0, 53262) end
  if n > 760 then
    local fill = (z:read_u16(0xFC02) - z:read_u16(0xFC00)) & 0x3FF
    local pt0 = mem:read_u16(0x100042); if pt0 ~= _G.ptx then _G.ptx = pt0; _G.since = n end
    if z:read_u8(0xFC06) == 1 and n - (_G.since or 0) > 30 then if fill < minfill then minfill = fill end; if fill == 0 then empty = empty + 1 end end
    local v = mem:read_u16(0x100062)
    if ((v - lastv) & 0xFFFF) ~= 1 then vbad = vbad + 1 end
    local p = mem:read_u16(0x100104)
    if lastpos >= 0 and p ~= ((lastpos + 1) % (mem:read_u16(0x100106) * 8)) and p ~= 0 then posbad = posbad + 1 end
    lastpos = p
    local pt = mem:read_u16(0x100042); if pt ~= lastpt then tracks = tracks + 1; lastpt = pt end
    if mem:read_u16(0x1000F2) ~= 1 then print("FAIL saver stopped at frame " .. n); m:exit() end
  end
  lastv = mem:read_u16(0x100062)
  if n == 760 + 60 * 300 then
    print(string.format("ENDURANCE 5 min saver: track changes=%d  Z80 buffer min=%d empty frames=%d  vblank irregular=%d  small-text steps not +1=%d", tracks, minfill, empty, vbad, posbad))
    m:exit()
  end
end)
