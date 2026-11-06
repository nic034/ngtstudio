-- delai de l'economiseur mesure depuis zero (5 minutes = 17756 images a 59,185 Hz), puis textes en lecture et a l'arret
if _G.reg then return end
_G.reg = true
local m = manager.machine
local mem = m.devices[":maincpu"].spaces["program"]
local n, on = 0, nil
local function txt() local a = mem:read_u32(0x1000FC); local s = "" for i = 0, 120 do local c = mem:read_u8(a + i); if c == 0 then break end s = s .. string.char(c) end return s end
local F = {} for tag, p in pairs(m.ioport.ports) do for name, f in pairs(p.fields) do F[name] = f end end
emu.register_frame_done(function()
  n = n + 1
  if n == 700 then mem:write_u16(0x1000F0, 0) end                       -- inactivite remise a zero
  if n > 700 and not on and mem:read_u16(0x1000F2) == 1 then on = n; print(string.format("DELAI economiseur actif %d images apres idle=0 (attendu 17756 = 5 min)", n - 700)); print("TEXTE lecture : [" .. txt() .. "]") end
  if not on then if n > 700 + 20000 then print("DELAI : economiseur jamais actif") ; m:exit() end return end
  if n == on + 600 then F["P1 B"]:set_value(1) end                      -- reveil (consomme)
  if n == on + 605 then F["P1 B"]:set_value(0) end
  if n == on + 640 then F["P1 B"]:set_value(1) end                      -- stop
  if n == on + 645 then F["P1 B"]:set_value(0) end
  if n == on + 700 then mem:write_u16(0x1000F0, 17755) end
  if n == on + 760 then print("TEXTE arret : [" .. txt() .. "]") ; m:exit() end
end)
