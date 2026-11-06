if _G.reg then return end
_G.reg = true
local m = manager.machine
local mem = m.devices[":maincpu"].spaces["program"]
local zm = m.devices[":audiocpu"].spaces["program"]
local F = {}
for tag, p in pairs(m.ioport.ports) do for name, f in pairs(p.fields) do F[name] = f end end
local names = {"P1 Up","P1 Down","P1 Left","P1 Right","P1 A","P1 A","P1 B","P1 C","P1 D","P1 D","1 Player Start"}
math.randomseed(7)
local n, nextp, held, rel = 0, 500, nil, 0
local lastt, stalls, resets, dead, plays, lastplay, maxgap = -1, 0, 0, 0, 0, 0, 0
emu.register_frame_done(function()
  n = n + 1
  if n > 450 and n < 21000 then
    if held and n >= rel then F[held]:set_value(0); held = nil end
    if not held and n >= nextp then
      held = names[math.random(#names)]; F[held]:set_value(1)
      rel = n + math.random(3, (held == "P1 Up" or held == "P1 Down") and 50 or 8)
      nextp = rel + math.random(2, 40)
    end
  end
  if n > 450 then
    local t = mem:read_u16(0x100060)
    if t == lastt then stalls = stalls + 1 end
    if lastt > 100 and t < lastt and t < 50 then resets = resets + 1 end
    lastt = t
    if mem:read_u16(0x100020) ~= 0 then dead = dead + 1 end
    local p = mem:read_u16(0x100006)
    if p == 1 and lastplay == 0 then plays = plays + 1 end
    lastplay = p
  end
  if n == 21000 then  -- fin : on lance une piste et on verifie que ca joue
    for _, nm in ipairs(names) do F[nm]:set_value(0) end
    mem:write_u16(0x100002, 0); mem:write_u16(0x100004, 3); F["P1 A"]:set_value(1)
  end
  if n == 21006 then F["P1 A"]:set_value(0) end
  if n % 3000 == 0 or n == 21500 then
    print(string.format("f=%d ticks=%d stalls=%d watchdog_resets=%d zdead_frames=%d plays=%d | play=%d pause=%d game=%d trk=%d | z80 magic=%02x state=%d",
      n, lastt, stalls, resets, dead, plays, mem:read_u16(0x100006), mem:read_u16(0x100044), mem:read_u16(0x100002), mem:read_u16(0x100004), zm:read_u8(0xFC0A), zm:read_u8(0xFC06)))
  end
end)
