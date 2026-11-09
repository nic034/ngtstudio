-- Toasty 2.5.27 : declenchement au changement de piste (une fois par economiseur), cri sur la voie empruntee.
-- Espionne les ecritures du Z80 dans le YM2610 (ports 4-7) : pendant le cri, aucun declenchement de la musique sur
-- la voie du cri, les autres voies continuent ; a la fin, ses registres sont reecrits.  2e economiseur : rearme.
-- A lancer avec -wavwrite pour l'audio.  ex. : mame neogeo ngjb -hashpath hash -rompath . -autoboot_script toasty_sfx.lua
if _G.reg then return end
_G.reg = true
local m = manager.machine
local mem = m.devices[":maincpu"].spaces["program"]
local io = m.devices[":audiocpu"].spaces["io"]
local F = {} for tag, p in pairs(m.ioport.ports) do for name, f in pairs(p.fields) do F[name] = f end end
local A = F["P1 A"] or F["P1 Button 1"]
local R = 0x100000
local n, n0, last = 0, nil, -1
local sfx_on, sfx_t0, sfx_frames = false, 0, 0
local ch = tonumber(os.getenv("SFXCH") or "5")
local latch_b, keys_during, other_during, keys_ch_during, regs_after = nil, 0, 0, 0, {}
local log = {}
local function lg(s) print(s); log[#log + 1] = s end
_G.tap = io:install_write_tap(0x0000, 0xFFFF, "ym", function(off, data, mask)
  local p = off & 0xFF
  if p == 6 then latch_b = data
  elseif p == 7 and latch_b then
    local r = latch_b
    if r == 0 and (data & 0x80) == 0 and (data & 0x3F) ~= 0 then
      if (data >> ch) & 1 == 1 then
        if sfx_on then keys_ch_during = keys_ch_during + 1 end
      elseif sfx_on then other_during = other_during + 1 end
    end
    if sfx_on and r >= 0x08 and r <= 0x2D and (r - ch) % 8 == 0 then regs_after[#regs_after + 1] = string.format("%02X=%02X", r, data) end
  end
  return data
end)
local wokeat, phase = 0, 1
emu.register_frame_done(function()
  if not n0 then if mem:read_u32(R + 272) == 0x4E474A42 then n0 = 1 else return end end
  n = n + 1
  local s = mem:read_u16(R + 1720)
  local sv = mem:read_u16(R + 242)
  if s ~= last then
    lg(string.format("image %d : V_TOST %d -> %d (economiseur %d, jeu %d piste %d)", n, last, s, sv, mem:read_u16(R + 64), mem:read_u16(R + 66)))
    last = s
  end
  -- Z80 : sfxon (0xFC15) via la RAM du Z80
  local zon = m.devices[":audiocpu"].spaces["program"]:read_u8(0xFC15)
  if zon == 1 and not sfx_on then sfx_on = true; sfx_t0 = n; keys_ch_during = 0; other_during = 0; lg(string.format("image %d : cri en cours (Z80 sfxon = 1), voie %d, volume general vu %d", n, m.devices[":audiocpu"].spaces["program"]:read_u8(0x0044), m.devices[":audiocpu"].spaces["program"]:read_u8(0xFC1D))) end
  if zon == 0 and sfx_on then
    sfx_on = false
    lg(string.format("image %d : cri fini apres %d images ; pendant le cri : %d declenchements musique sur la voie du cri (attendu 0), %d sur les autres voies", n, n - sfx_t0, keys_ch_during, other_during))
  end
  if n == 300 then mem:write_u16(R + 0xF0, 17700) end                    -- economiseur 1
  if phase == 1 and s == 3 and sv == 1 and n > 400 then phase = 2; wokeat = n + 1200 end  -- reste dans l'economiseur 20 s : pas de 2e passage
  if phase == 2 and n == wokeat then A:set_value(1); lg(string.format("image %d : reveil (A)", n)) end
  if phase == 2 and n == wokeat + 3 then A:set_value(0) end
  if phase == 2 and n == wokeat + 60 then mem:write_u16(R + 0xF0, 17700); phase = 3; lg(string.format("image %d : economiseur 2", n)) end
  if n == tonumber(os.getenv("NF") or "6000") then
    lg(string.format("FIN image %d : V_TOST %d, economiseur %d", n, s, sv))
    m:exit()
  end
end)
