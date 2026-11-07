-- Economiseur, scene sphere (2.5.26) : sprites affiches, reveil par la croix / A / piece depuis la sphere, retour au
-- texte.  La VRAM est reconstruite en espionnant les ecritures LSPC ($3C0000 adresse, $3C0002 donnee, $3C0004
-- increment) : aucune lecture par les registres, le programme n'est pas perturbe.  Sortie : lignes PASS / FAIL.
-- Sprites : damier 1..24, objets 25..64, CD 65..66, grand texte 67..147, petit texte 148..229, sphere 230..325.
if _G.reg then return end
_G.reg = true
local m = manager.machine
local mem = m.devices[":maincpu"].spaces["program"]
local F = {}
for tag, p in pairs(m.ioport.ports) do for name, f in pairs(p.fields) do F[name] = f end end
local function find(...) for _, k in ipairs({...}) do if F[k] then return k end end end
local DOWN, A, COIN = find("P1 Down"), find("P1 A", "P1 Button 1"), find("Coin 1")
local V, va, vm = {}, 0, 1
_G.tapv = mem:install_write_tap(0x3C0000, 0x3C0005, "vram", function(off, data, mask)
  local r = off & 6
  if r == 0 then va = data elseif r == 4 then vm = data
  elseif r == 2 then V[va] = data; va = (va & 0x8000) | ((va + vm) & 0x7FFF) end
end)
local function vis(a, b) local c = 0 for i = a, b do if (V[0x8200 + i] or 0) ~= 0 then c = c + 1 end end return c end
local function snap() local t = {} for i = 230, 325 do t[#t + 1] = (V[0x8200 + i] or 0) .. ":" .. (V[0x8400 + i] or 0) end return table.concat(t, ",") end
local R = function(a) return mem:read_u16(a) end
local SAVER, IDLE, SCENE, PLAY, PAUSE, TRK, TICKS = 0x1000F2, 0x1000F0, 0x10044C, 0x100006, 0x100044, 0x100004, 0x100060
local n, pass, fail = 0, 0, 0
local function chk(c, w) if c then pass = pass + 1 else fail = fail + 1; print("FAIL f=" .. n .. " " .. w) end end
-- etapes : chacune attend sa condition puis agit ; un delai depasse = FAIL
local steps, si, t0 = {}, 1, 0
local function step(wait_fn, act, label, timeout) steps[#steps + 1] = {w = wait_fn, a = act, l = label, to = timeout or 4000} end
local hold = {}
local function press(k) if k then F[k]:set_value(1); hold[k] = n + 6 end end
local sx0, trk0
local function to_sphere(label)
  step(function() return n > 650 and R(PLAY) == 1 end, function() mem:write_u16(IDLE, 53262) end, label .. " : lecture, economiseur demande")
  step(function() return R(SAVER) == 1 and R(SCENE) == 1 end, function() sx0 = snap() end, label .. " : scene sphere atteinte")
  step(function() return R(SCENE) == 1 and n >= t0 + 60 end, function()
    chk(vis(230, 325) == 96, label .. " : 96 points de sphere affiches (" .. vis(230, 325) .. ")")
    chk(vis(67, 147) == 0, label .. " : grand texte masque pendant la sphere (" .. vis(67, 147) .. ")")
    chk(vis(1, 24) == 24 and vis(148, 229) == 82, label .. " : damier et petit texte affiches")
    chk(snap() ~= sx0, label .. " : sphere animee (positions changees en 1 s)")
    trk0 = R(TRK)
  end, label .. " : sphere stable 1 s")
end
local function woke(label, extra)
  step(function() return n >= t0 + 30 end, function()
    chk(R(SAVER) == 0, label .. " : economiseur eteint")
    chk(vis(1, 325) == 0, label .. " : tous les sprites masques au reveil, sphere comprise (" .. vis(1, 325) .. ")")
    chk(R(PLAY) == 1, label .. " : la musique continue")
    if extra then extra() end
  end, label .. " : reveil")
end
to_sphere("croix")
step(function() return true end, function() press(DOWN) end, "appui BAS")
woke("croix", function() chk(R(TRK) == trk0, "croix : appui consomme (curseur immobile)") end)
to_sphere("A")
step(function() return true end, function() press(A) end, "appui A")
woke("A", function() chk(R(PAUSE) == 0, "A : appui consomme (pas de pause)") end)
if COIN then
  to_sphere("piece")
  step(function() return true end, function() press(COIN) end, "piece")
  step(function() return n >= t0 + 200 end, function()
    local sv = R(SAVER)
    chk((sv == 1 and vis(230, 325) == 96) or (sv == 0 and vis(1, 325) == 0), "piece : sprites coherents avec l'etat (economiseur=" .. sv .. ", sprites=" .. vis(1, 325) .. ")")
    if sv == 1 then press(A) end
  end, "piece pendant la sphere")
  step(function() return n >= t0 + 40 end, function() chk(R(SAVER) == 0, "piece : reveil ensuite") end, "reveil apres piece")
end
-- sphere -> texte : la sphere disparait, le texte revient
step(function() return n > 0 and R(PLAY) == 1 end, function() mem:write_u16(IDLE, 53262) end, "retour : economiseur")
step(function() return R(SAVER) == 1 and R(SCENE) == 1 end, nil, "retour : sphere", 4000)
step(function() return R(SAVER) == 1 and R(SCENE) == 0 end, nil, "retour : texte apres la sphere", 4000)
step(function() return n >= t0 + 10 end, function()
  chk(vis(230, 325) == 0, "retour : sphere masquee (" .. vis(230, 325) .. ")")
  chk(vis(67, 147) == 81, "retour : grand texte affiche (" .. vis(67, 147) .. ")")
end, "retour : controle")
local last, stall, maxstall = -1, 0, 0
emu.register_frame_done(function()
  n = n + 1
  for k, f in pairs(hold) do if n >= f then F[k]:set_value(0); hold[k] = nil end end
  local tk = R(TICKS)
  if n > 500 then if tk == last then stall = stall + 1 else stall = 0 end; if stall > maxstall then maxstall = stall end end
  last = tk
  local s = steps[si]
  if s then
    if s.w() then if s.a then s.a() end; si = si + 1; t0 = n
    elseif n - t0 > s.to then fail = fail + 1; print("FAIL f=" .. n .. " delai depasse : " .. s.l); si = si + 1; t0 = n end
  else
    chk(maxstall < 60, "boucle principale jamais figee > 1 s (max " .. maxstall .. " images)")
    print(string.format("RESULT pass=%d fail=%d maxstall=%d", pass, fail, maxstall)); m:exit()
  end
end)
