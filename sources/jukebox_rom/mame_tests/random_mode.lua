-- mode RAND : pistes tirees au hasard, jamais deux fois la meme de suite, lecture jamais arretee
if _G.reg then return end
_G.reg = true
local m = manager.machine
local mem = m.devices[":maincpu"].spaces["program"]
local n, cur, cnt, same, games, seen, stops = 0, "", 0, 0, {}, {}, 0
local nmax = tonumber(os.getenv("NRAND") or "120")
emu.register_frame_done(function()
  n = n + 1
  if n == 700 then mem:write_u16(0x100098, 2) end
  if n < 702 then return end
  if mem:read_u16(0x100098) ~= 2 then print("RAND : mode change !"); m:exit() end
  if mem:read_u16(0x100006) == 0 then stops = stops + 1 end
  local g, t = mem:read_u16(0x100040), mem:read_u16(0x100042)
  local k = g .. "/" .. t
  if k ~= cur then
    if k == cur then same = same + 1 end
    cnt = cnt + 1; games[g] = (games[g] or 0) + 1; seen[k] = true
    if cnt <= 12 then print(string.format("%7.1f s : jeu %d piste %d", n / 59.185, g, t)) end
    cur = k
  end
  if cnt > nmax or n > 59.185 * 3600 * 3 then
    local gs, ns = {}, 0 for gg, c in pairs(games) do gs[#gs + 1] = gg .. ":" .. c end
    for _ in pairs(seen) do ns = ns + 1 end
    print(string.format("RAND : %d pistes en %.0f min, %d differentes, images a l'arret %d | par jeu %s", cnt - 1, n / 59.185 / 60, ns, stops, table.concat(gs, " ")))
    m:exit()
  end
end)
