"""Genere les tables de couleurs des effets 2.5.37 / 2.5.38 de l'economiseur dans src/parts/core.S (entre les reperes) :
  th_gold / th_ui / th_fire / th_ice : 4 degrades cycliques de 32 couleurs pour le grand texte (meme forme que hues,
      le theme 0 : 8 rangees de lettres, pas de 3, defilement vertical) ;
  fd_w / fd_y : fondu des lettres de l'annonce de piste (blanc, jaune), 17 paliers 0..16.
Couleur Neo Geo : bit 15 = sombre, bits 14-12 = bits faibles de R, V, B, puis R, V, B sur 4 bits (5 bits par composante).

  python tools/gen_saver_fx.py        (a relancer seulement si les couleurs ci-dessous changent)
"""
import math, os, re
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
p = os.path.join(here, "src", "parts", "core.S")


def ng(r, g, b):
    """composantes 0..31 -> mot Neo Geo"""
    r, g, b = (max(0, min(31, round(v))) for v in (r, g, b))
    return ((r & 1) << 14) | ((g & 1) << 13) | ((b & 1) << 12) | ((r >> 1) << 8) | ((g >> 1) << 4) | (b >> 1)


def cyc(stops, n):
    """degrade cyclique : n couleurs reparties sur les points d'arret (le dernier rejoint le premier)"""
    out = []
    for i in range(n):
        t = i * len(stops) / n
        k, f = int(t), t - int(t)
        f = (1 - math.cos(math.pi * f)) / 2                    # passage doux d'un point d'arret au suivant
        a, b = stops[k], stops[(k + 1) % len(stops)]
        out.append(tuple(a[j] + (b[j] - a[j]) * f for j in range(3)))
    return out


def words(vals, per=8):
    return ["        .word   " + ", ".join(f"0x{v:04X}" for v in vals[i:i + per]) for i in range(0, len(vals), per)]


THEMES = (
    ("th_gold", "or / chrome", [(18, 9, 2), (31, 22, 3), (31, 31, 20), (31, 22, 3)]),
    ("th_ui", "couleurs de l'interface : cyan, magenta, jaune", [(4, 30, 31), (31, 9, 29), (31, 29, 3)]),
    ("th_fire", "feu", [(26, 2, 4), (31, 14, 0), (31, 30, 8), (31, 14, 0)]),
    ("th_ice", "glace", [(3, 9, 31), (5, 27, 31), (27, 31, 31), (5, 27, 31)]),
)
rows = ["| grand texte : degrades cycliques de 32 couleurs (theme 0 = hues, l'arc-en-ciel d'origine) ; un theme par passage",
        "| du texte (scene_pass)"]
for name, what, stops in THEMES:
    rows.append(f"{name}:                               | {what}")
    rows += words([ng(*c) for c in cyc(stops, 32)])
rows += ["| annonce de piste : fondu des lettres, paliers 0..16 (blanc casse, puis jaune de l'interface)"]
rows.append("fd_w:")
rows += words([ng(*(27 * k / 16,) * 3) for k in range(17)], 17)
rows.append("fd_y:")
rows += words([ng(31 * k / 16, 29 * k / 16, 2 * k / 16) for k in range(17)], 17)
A, B = "| --- debut des tables generees par tools/gen_saver_fx.py ---\n", "| --- fin des tables gen_saver_fx ---\n"
block = A + "\n".join(rows) + "\n" + B
s = open(p).read()
if A in s:
    s = re.sub(re.escape(A) + ".*?" + re.escape(B), lambda m: block, s, flags=re.S)
else:
    mark = "t_sc_play: .asciz"                                 # juste avant les textes : zone alignee sur 2 (cd_fade_tab)
    assert s.count(mark) == 1
    s = s.replace(mark, block + mark)
open(p, "w").write(s)
print("th_gold, th_ui, th_fire, th_ice, fd_w, fd_y ecrits dans", p)
