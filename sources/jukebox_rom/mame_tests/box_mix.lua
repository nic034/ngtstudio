-- Objets volants de l'economiseur : repartition par planche (departs), nombre d'objets en vol (moyenne / max) et
-- sprites par ligne (limite materielle 96), pendant NMIN minutes d'economiseur (defaut 5).
-- ex. : NMIN=5 mame neogeo ngjb -hashpath hash -rompath . -video none -sound none -nothrottle -autoboot_script box_mix.lua
if _G.reg then return end
_G.reg = true
local m = manager.machine
local mem = m.devices[":maincpu"].spaces["program"]
local vr, addr, inc = {}, 0, 1
_G.tap = mem:install_write_tap(0x3C0000, 0x3C0005, "vram", function(off, data, mask)
  if off == 0x3C0000 then addr = data
  elseif off == 0x3C0002 then
    if addr >= 0x8200 and addr < 0x8600 then vr[addr] = data end
    addr = (addr & 0x8000) | ((addr + inc) & 0x7FFF)
  elseif off == 0x3C0004 then inc = data; if inc >= 0x8000 then inc = inc - 0x10000 end end
end)
local R, n = 0x100000, 0
local NMIN = tonumber(os.getenv("NMIN") or "5")
local prev, dep, sum, cnt, mx, worst, over = {}, {}, 0, 0, 0, 0, 0
local pop = function(v) local c = 0 while v > 0 do c = c + (v & 1) v = v >> 1 end return c end
emu.register_frame_done(function()
  n = n + 1
  if n == 300 then mem:write_u16(R + 0xF0, 17700) end
  if n > 420 and mem:read_u16(R + 242) == 1 then
    local a = mem:read_u16(R + 296)
    for s = 0, 9 do
      local on = (a >> s) & 1
      if on == 1 and prev[s] ~= 1 then local k = mem:read_u16(R + 342 + 2 * s); dep[k] = (dep[k] or 0) + 1 end
      prev[s] = on
    end
    local c = pop(a); sum = sum + c; cnt = cnt + 1; if c > mx then mx = c end
    local cntl, y, sz = {}, 0, 0
    for sp = 1, 380 do
      local cc = vr[0x8200 + sp] or 0
      if (cc & 0x40) == 0 then y = (496 - (cc >> 7)) & 0x1FF; sz = cc & 0x3F end
      if sz > 0 then for l = 0, sz * 16 - 1 do local yy = (y + l) & 0x1FF; if yy < 224 then cntl[yy] = (cntl[yy] or 0) + 1 end end end
    end
    for l = 0, 223 do local v = cntl[l] or 0; if v > worst then worst = v end; if v > 96 then over = over + 1 end end
  end
  if n == 420 + 3600 * NMIN then
    local t = {}
    for k = 0, 5 do t[#t + 1] = string.format("planche %d : %d", k, dep[k] or 0) end
    print(string.format("OBJETS EN VOL : moyenne %.2f, max %d (images %d)", sum / math.max(cnt, 1), mx, cnt))
    print("DEPARTS : " .. table.concat(t, " | "))
    print(string.format("SPRITES/LIGNE : pire %d, images-lignes > 96 : %d", worst, over))
    m:exit()
  end
end)
