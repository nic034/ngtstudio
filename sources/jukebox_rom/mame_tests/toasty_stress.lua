-- Toasty (2.5.27) : rejoue le Toasty (et son cri) sans fin pendant 6 min d'economiseur et compte les sprites par ligne a chaque image
-- (limite materielle 96, tout compris). Cout de l'IRQ : seulement avec une ROM instrumentee (draw3.S : avant
-- "bsr toasty_vbl" : move.w 0x3C0006,0x1006CC ; apres : move.w 0x3C0006,0x1006CE ; apres "bsr saver_scroll" :
-- move.w 0x3C0006,0x1006D0), sinon ces lignes n'ont pas de sens.
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
local worst, wl, over, tf, sc = 0, 0, 0, 0, {[0]=0,[1]=0}
local imx, isum, icnt, imxT, isumT, icntT = 0, 0, 0, 0, 0, 0
local twl = {}
emu.register_frame_done(function()
  n = n + 1
  if n == 300 then mem:write_u16(R + 0xF0, 17700) end
  if mem:read_u16(R + 1720) == 3 or mem:read_u16(R + 1720) == 0 then mem:write_u16(R + 1720, 1) end      -- repasse sans fin
  if n > 420 and mem:read_u16(R + 242) == 1 then
    local running = mem:read_u16(R + 1720) == 2
    local cnt, y, sz = {}, 0, 0
    for sp = 1, 380 do
      local c = vr[0x8200 + sp] or 0
      if (c & 0x40) == 0 then y = (496 - (c >> 7)) & 0x1FF; sz = c & 0x3F end
      if sz > 0 then for l = 0, sz * 16 - 1 do local yy = (y + l) & 0x1FF; if yy < 224 then cnt[yy] = (cnt[yy] or 0) + 1 end end end
    end
    for l = 0, 223 do local c = cnt[l] or 0
      if c > worst then worst = c; wl = l end
      if c > 96 then over = over + 1 end
      if running and c > (twl[l] or 0) then twl[l] = c end
    end
    if running then tf = tf + 1; sc[mem:read_u16(R + 1100) & 1] = sc[mem:read_u16(R + 1100) & 1] + 1 end
    local a, t, b = mem:read_u16(R + 1740) >> 7, mem:read_u16(R + 1742) >> 7, mem:read_u16(R + 1744) >> 7; local dt = (t - a) % 264; if running and dt > (_G.tmx or 0) then _G.tmx = dt end
    local d = (b - a) % 264
    if d > imx then imx = d end; isum = isum + d; icnt = icnt + 1
    if running then if d > imxT then imxT = d end; isumT = isumT + d; icntT = icntT + 1 end
  end
  if n == 420 + 60 * 360 then
    local zone = 0
    for l = 120, 223 do if (twl[l] or 0) > zone then zone = twl[l] end end
    print(string.format("images avec Toasty anime : %d (texte %d, sphere %d)", tf, sc[0], sc[1]))
    print(string.format("SPRITES/LIGNE : pire %d (ligne %d), images-lignes > 96 : %d ; pire ligne 120-223 pendant le Toasty : %d", worst, wl, over, zone))
    print("Toasty seul (debut IRQ -> fin toasty_vbl), pendant son animation : max " .. (_G.tmx or 0) .. " lignes"); print(string.format("IRQ VBlank economiseur : moyenne %.1f, max %d lignes ; pendant le Toasty : moyenne %.1f, max %d lignes (retour de trame : 40)", isum / icnt, imx, isumT / icntT, imxT))
    m:exit()
  end
end)
