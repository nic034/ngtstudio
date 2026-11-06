-- Copie des SCB2..SCB4 par espionnage des ecritures LSPC ; a chaque image : sprites par ligne (limite materielle 96)
if _G.reg then return end
_G.reg = true
local m = manager.machine
local mem = m.devices[":maincpu"].spaces["program"]
local F = {} for tag, p in pairs(m.ioport.ports) do for name, f in pairs(p.fields) do F[name] = f end end
local B = F["P1 B"] or F["P1 Button 2"]
local vr, addr, inc = {}, 0, 1
_G.tap = mem:install_write_tap(0x3C0000, 0x3C0005, "vram", function(off, data, mask)
  if off == 0x3C0000 then addr = data
  elseif off == 0x3C0002 then
    if addr >= 0x8200 and addr < 0x8600 then vr[addr] = data end
    addr = (addr & 0x8000) | ((addr + inc) & 0x7FFF)
  elseif off == 0x3C0004 then inc = data; if inc >= 0x8000 then inc = inc - 0x10000 end end
end)
local n, worst, over, frames, wl = 0, 0, 0, 0, 0
local stopat = tonumber(os.getenv("STOPF") or "0")
emu.register_frame_done(function()
  n = n + 1
  if stopat > 0 and n == 700 then B:set_value(1) end
  if stopat > 0 and n == 705 then B:set_value(0) end
  if n == 800 then mem:write_u16(0x1000F0, 35505) end
  if n > 820 and mem:read_u16(0x1000F2) == 1 then
    frames = frames + 1
    local cnt = {}
    local y, sz = 0, 0
    for s = 1, 381 do
      local c = vr[0x8200 + s] or 0
      if (c & 0x40) == 0 then y = (496 - (c >> 7)) & 0x1FF; sz = c & 0x3F end
      if sz > 0 then
        for l = 0, sz * 16 - 1 do
          local yy = (y + l) & 0x1FF
          if yy < 224 then cnt[yy] = (cnt[yy] or 0) + 1 end
        end
      end
    end
    local mx, ml = 0, 0
    for l = 0, 223 do if (cnt[l] or 0) > mx then mx = cnt[l]; ml = l end end
    if mx > worst then worst = mx; wl = ml end
    if mx > 96 then over = over + 1 end
  end
  if n == 820 + 60 * 240 then
    print(string.format("SPRITES/LIGNE : %d images d'economiseur, pire ligne %d sprites (ligne %d), images au-dela de 96 : %d", frames, worst, wl, over))
    m:exit()
  end
end)
