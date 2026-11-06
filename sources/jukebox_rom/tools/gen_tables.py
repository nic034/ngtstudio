"""Genere les tables de l'economiseur dans src/parts/core.S (entre les reperes ; a relancer si SC_Y0 ou la table de
sinus changent) : sc_ytab = hauteurs du grand texte, 19 amplitudes (28..64 px, pas de 2 ; pas moins de 28 : sprites de 48 px, au plus 96 sprites par ligne) x 512 phases (demi-pas),
en octets 2 x (dy + 64), dy = sin x amplitude / 64 ; sc_ylut (128 mots) les convertit en valeur SCB3
(496 - (SC_Y0 + dy)) << 7 | 3 (3 tuiles de haut).  Octets au lieu de mots : 10,5 Ko de moins dans la ROM."""
import math, os, re
SC_Y0 = 92
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
p = os.path.join(here, "src", "parts", "core.S")
sin = [min(round(64 * math.sin(2 * math.pi * k / 512)), 63) for k in range(512)]
rows = ["sc_ylut:                                | 2 x (dy + 64) -> valeur SCB3 (hauteur 3 tuiles)"]
lut = [((496 - (SC_Y0 + dy)) << 7) | 3 for dy in range(-64, 64)]
rows += ["        .word   " + ", ".join(f"0x{v:04X}" for v in lut[i:i + 8]) for i in range(0, 128, 8)]
rows.append("sc_ytab:")
for k in range(19):
    amp = 28 + 2 * k
    vals = [2 * (((s * amp) >> 6) + 64) for s in sin]
    assert all(0 <= v <= 254 for v in vals)
    rows.append(f"| amplitude {amp} px")
    rows += ["        .byte   " + ", ".join(f"{v}" for v in vals[i:i + 32]) for i in range(0, 512, 32)]
block = "| --- debut des tables generees par tools/gen_tables.py ---\n" + "\n".join(rows) + \
        "\n| --- fin des tables generees ---\n"
s = open(p).read()
s = re.sub(r"(?:\s*\.balign 2\n)*\| --- debut des tables generees par tools/gen_tables\.py ---\n.*?\| --- fin des tables generees ---\n", "", s, flags=re.S)
s = s.rstrip("\n") + "\n\n        .balign 2\n" + block
open(p, "w").write(s)
print("sc_ylut + sc_ytab: 19 x 512 octets ecrits dans", p)
