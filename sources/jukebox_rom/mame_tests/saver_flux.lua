if _G.reg then return end
_G.reg = true
local m = manager.machine
local mem = m.devices[":maincpu"].spaces["program"]
local n, hist, lastd, changes, frames = 0, {}, -1, 0, 0
local preva, spawn = 0, {[0] = 0, [1] = 0, [2] = 0, [3] = 0, [4] = 0, [5] = 0}
emu.register_frame_done(function()
  n = n + 1
  if n == 800 then mem:write_u16(0x1000F0, 35505) end
  if n > 810 and mem:read_u16(0x1000F2) == 1 then
    local a = mem:read_u16(0x100128); local c = 0
    for i = 0, 9 do if (a >> i) & 1 == 1 then c = c + 1 end end
    hist[c] = (hist[c] or 0) + 1; frames = frames + 1
    local d = mem:read_u16(0x10011E); if d ~= lastd then changes = changes + 1; lastd = d end
    for i = 0, 9 do if (a >> i) & 1 == 1 and (preva >> i) & 1 == 0 then local k = mem:read_u16(0x100156 + 2 * i); spawn[k] = (spawn[k] or 0) + 1 end end
    preva = a
  end
  if n == 810 + 60 * 300 then
    local s = {} for c = 0, 10 do s[#s + 1] = c .. ":" .. string.format("%.0f%%", 100 * (hist[c] or 0) / frames) end
    print("FLUX 5 min : boites en vol (part du temps) " .. table.concat(s, " ") .. " | diagonales prises : " .. changes .. " | departs : " .. spawn[0] .. " par planche (1 a 6) : " .. spawn[0] .. " / " .. spawn[1] .. " / " .. spawn[2] .. " / " .. spawn[3] .. " / " .. spawn[4] .. " / " .. spawn[5])
    m:exit()
  end
end)
