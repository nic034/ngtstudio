-- economiseur actif : titre (V_HUE), bandeau (V_MQPOS) et cretes (V_PK) figes, niveaux (V_LVL) vivants ; reprise au reveil
if _G.reg then return end
_G.reg = true
local m = manager.machine
local mem = m.devices[":maincpu"].spaces["program"]
local F = {} for tag, p in pairs(m.ioport.ports) do for name, f in pairs(p.fields) do F[name] = f end end
local B = F["P1 B"] or F["P1 Button 2"]
local n, hue0, mq0, pk0, lvlchg, frozen, s_on = 0, nil, nil, nil, 0, true, nil
local function pk() local s = 0 for i = 0, 6 do s = s + mem:read_u8(0x10006A + i) end return s end
local function lvl() local s = 0 for i = 0, 6 do s = s + mem:read_u8(0x100056 + i) end return s end
local lastl = -1
emu.register_frame_done(function()
  n = n + 1
  if n == 900 then mem:write_u16(0x1000F0, 17750) end
  local sv = mem:read_u16(0x1000F2)
  if sv == 1 and not s_on then s_on = n end
  if s_on and n == s_on + 10 then hue0, mq0, pk0 = mem:read_u16(0x10005E), mem:read_u16(0x10009A), pk() end
  if s_on and n > s_on + 10 and n < s_on + 900 then
    if mem:read_u16(0x10005E) ~= hue0 or mem:read_u16(0x10009A) ~= mq0 or pk() ~= pk0 then frozen = false end
    local l = lvl(); if l ~= lastl then lvlchg = lvlchg + 1; lastl = l end
  end
  if s_on and n == s_on + 900 then B:set_value(1) end
  if s_on and n == s_on + 905 then B:set_value(0) end
  if s_on and n == s_on + 1100 then
    local h1, m1 = mem:read_u16(0x10005E), mem:read_u16(0x10009A)
    print(string.format("ANIM economiseur : titre/bandeau/cretes figes = %s, niveaux vivants (%d changements) | apres reveil : economiseur=%d, titre repart=%s, bandeau repart=%s",
      tostring(frozen), lvlchg, mem:read_u16(0x1000F2), tostring(h1 ~= hue0), tostring(m1 ~= mq0)))
    m:exit()
  end
end)
