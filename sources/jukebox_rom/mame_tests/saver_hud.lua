-- Economiseur 2.5.37 a 2.5.39 : mini vumetre (2.5.39 : 4 x 4 cases, 2 voies par case, fond transparent), annonce de piste, themes du grand texte ; damier reste gris.  PASS / FAIL.
-- Copie de la couche fix tenue par espionnage des ecritures LSPC (aucune lecture qui derangerait le registre d'adresse).
--   mame neogeo ngjb -hashpath hash -rompath . -video none -sound none -nothrottle -autoboot_script saver_hud.lua
-- Dure ~4 min 30 de jeu : attend un tour complet des 5 themes et au moins un changement de piste (il faut un album dont
-- la 1re piste dure moins de 3 min 30), puis une annonce refermee, quel que soit le BIOS (l'AES demarre plus vite).
if _G.reg then return end
_G.reg = true
local m = manager.machine
local mem = m.devices[":maincpu"].spaces["program"]
local F = {}
for tag, p in pairs(m.ioport.ports) do for name, f in pairs(p.fields) do F[name] = f end end
local A = F["P1 A"] or F["P1 Button 1"]
local R = 0x100000
local V_SAVER, V_PT, V_THEME, V_ANN, V_ANNT, V_ANNB = R + 242, R + 66, R + 1760, R + 1762, R + 1764, R + 1766
local ANN_W, ANN_COL, ANN_ROW, VCOL, VROW = 22, 9, 6, 2, 5
local T_M00, T_NOTE, T_CLEAR = 0xC36, 0xC1D, 0xC34
local fix, addr, inc = {}, 0, 1
_G.tap = mem:install_write_tap(0x3C0000, 0x3C0005, "vram", function(off, data, mask)
  if off == 0x3C0000 then addr = data
  elseif off == 0x3C0002 then
    if addr >= 0x7000 and addr < 0x7500 then fix[addr] = data end
    addr = (addr & 0x8000) | ((addr + inc) & 0x7FFF)
  elseif off == 0x3C0004 then inc = data; if inc >= 0x8000 then inc = inc - 0x10000 end end
end)
local function cell(col, row) return fix[0x7000 + col * 32 + row] or 0 end
local n, pass, fail = 0, 0, 0
local function chk(c, w) if c then pass = pass + 1 else fail = fail + 1; print("FAIL f=" .. n .. " " .. w) end end
local function row_text(row)
  local s = ""
  for c = ANN_COL, ANN_COL + ANN_W - 1 do
    local t = cell(c, row) & 0xFFF
    s = s .. (t == T_NOTE and "#" or (t >= 0x20 and t < 0x7F) and string.char(t) or "?")
  end
  return s
end
local function banner_clear()
  for c = ANN_COL, ANN_COL + ANN_W - 1 do
    if cell(c, ANN_ROW) ~= T_CLEAR or cell(c, ANN_ROW + 1) ~= T_CLEAR then return false end
  end
  return true
end
local seen, themes, last_theme, vu_bad, vu_live, floor_bad = {}, {}, -1, 0, 0, 0
local ann_states, banners, t0, T = {}, {}, nil, nil               -- T : image ou les controles sont faits
emu.register_frame_done(function()
  n = n + 1
  if n == 600 then mem:write_u16(R + 0xF0, 17700) end                       -- V_IDLE : economiseur dans ~1 s
  local sv = mem:read_u16(V_SAVER) == 1
  if sv and not t0 then t0 = n end
  if sv and n > t0 + 8 then
    local st = mem:read_u16(V_ANN)
    ann_states[st] = true
    if st == 4 then
      local t = mem:read_u16(V_ANNT)
      if t == 100 then banners[#banners + 1] = {row_text(ANN_ROW), row_text(ANN_ROW + 1), mem:read_u16(V_PT), mem:read_u16(0x400002), mem:read_u16(0x400102)} end
    end
    local th = mem:read_u16(V_THEME)
    if th ~= last_theme then themes[#themes + 1] = th; last_theme = th end
    for c = 0, 3 do                                                        -- vumetre : 4 x 4 cases, tuiles m00..m88
      local fl, fr = 0, 0                                                  --   (m00 + 9 x gauche + droite)
      for r = 0, 3 do
        local k = (cell(VCOL + c, VROW + r) & 0xFFF) - T_M00
        if k < 0 or k > 80 or (c == 3 and k % 9 ~= 0) then vu_bad = vu_bad + 1 else fl = fl + k // 9; fr = fr + k % 9 end
      end
      if fl > 0 then vu_live = vu_live + 1 end
      if fr > 0 then vu_live = vu_live + 1 end
    end
    for c = 4, 6 do for r = 0, 3 do                                        -- rien a droite du vumetre (colonnes 6..8, ancienne largeur)
      if (cell(VCOL + c, VROW + r) & 0xFFF) ~= T_CLEAR then vu_bad = vu_bad + 1 end
    end end
    if sv and n > t0 + 30 then                                             -- couleur 5 des cases = couleur 1 de la voie de droite
      local function pc(p, i) return mem:read_u16(0x400000 + p * 32 + i * 2) end
      if pc(2, 5) ~= pc(2, 1) or pc(4, 5) ~= pc(5, 1) then vu_pal_bad = (vu_pal_bad or 0) + 1 end
    end
    if mem:read_u16(0x400222) ~= 0x0222 then floor_bad = floor_bad + 1 end  -- damier : gris fixe d'origine (2.5.38)
  end
  if not T and sv and #themes == 6 and #banners >= 2 and mem:read_u16(V_ANN) == 0 then T = n end
  if not T and n == 30000 then print("FAIL no full theme cycle + track change + closed banner after 30000 images"); print("RESULT pass=" .. pass .. " fail=" .. (fail + 1)); m:exit() end
  if n == T then
    chk(ann_states[2] and ann_states[4] and ann_states[5] and ann_states[0], "banner went through open / shown / close / idle")
    chk(#banners >= 2, "banner at saver entry, then one per track change: " .. #banners)
    for i, bn in ipairs(banners) do
      chk(bn[1]:match("%S") ~= nil and not bn[1]:find("?", 1, true), "banner " .. i .. " title row: [" .. bn[1] .. "]")
      chk(bn[2]:find(string.format("# TRACK %02d/", bn[3] + 1), 1, true) ~= nil, "banner " .. i .. " track row: [" .. bn[2] .. "] for track " .. (bn[3] + 1))
      chk(bn[4] == 0x7DDD and bn[5] == 0x6FE1, string.format("banner %d letters at full level (white %04X, yellow %04X)", i, bn[4], bn[5]))
    end
    for i = 2, #banners do chk(banners[i][3] ~= banners[i - 1][3], "banner " .. i .. " is for another track than banner " .. (i - 1)) end
    chk(banner_clear(), "banner cells transparent again after closing")
    chk(vu_bad == 0, "mini VU: 4 x 4 cells of two-bar tiles, 7th voice alone, nothing beyond: " .. vu_bad .. " bad")
    chk((vu_pal_bad or 0) == 0, "mini VU: colour 5 of the cells = colour 1 of the right-hand voice: " .. (vu_pal_bad or 0) .. " bad images")
    chk(vu_live > 1000, "mini VU moves with the music: " .. vu_live .. " lit bar-frames")
    local s = table.concat(themes, ",")
    chk(s == "0,1,2,3,4,0", "text themes in order, one per text pass, wrap to 0: " .. s)
    chk(floor_bad == 0, "checkerboard keeps its fixed grey 0x0222: " .. floor_bad .. " images with another colour")
    A:set_value(1)
  end
  if T and n == T + 5 then A:set_value(0) end
  if T and n == T + 60 then
    chk(mem:read_u16(V_SAVER) == 0, "A wakes the saver")
    chk(mem:read_u16(0x400002) == 0x7FFF and mem:read_u16(0x400102) == 0x6FE1, string.format("palettes 0 / 8 restored after wake (%04X, %04X)", mem:read_u16(0x400002), mem:read_u16(0x400102)))
    chk((cell(ANN_COL, ANN_ROW) & 0xFFF) ~= T_CLEAR or (cell(VCOL, VROW) & 0xFFF) ~= T_CLEAR, "player screen redrawn over the saver HUD")
    A:set_value(1)                                                          -- pause, puis economiseur : pas d'annonce
  end
  if T and n == T + 65 then A:set_value(0) end
  if T and n == T + 130 then chk(mem:read_u16(R + 68) == 1, "paused"); mem:write_u16(R + 0xF0, 17700); ann_states = {}; t0 = nil end
  if T and n == T + 500 then
    chk(mem:read_u16(V_SAVER) == 1 and not ann_states[2] and not ann_states[4], "paused: saver without banner")
    print(string.format("RESULT pass=%d fail=%d", pass, fail)); m:exit()
  end
end)
