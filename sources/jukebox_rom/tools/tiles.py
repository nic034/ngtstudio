"""Tuiles maison de la couche FIX (8x8, 4 bits) pour l'interface du jukebox + rendu de maquette."""
import os, sys, zipfile

# La police du BIOS (sfix.sfix) n'est lue que pour la maquette ; les tuiles maison n'en dependent pas.
BIOS = os.environ.get("NGT_BIOS", "neogeo.zip")
try:
    SFIX = zipfile.ZipFile(BIOS).read("sfix.sfix")
except Exception:
    SFIX = bytes(0x20000)
BASE = 0xC00            # premiere tuile maison : zone de remplissage de sfix (0xB69-0xFFF, jamais affichee).
                        # Surtout pas 0x200 : logo SNK et police double hauteur du splash BIOS / UniBIOS (AES : S-ROM de la cartouche)

def decode_tile(t):
    px = [[0] * 8 for _ in range(8)]
    for y in range(8):
        for pair, base in enumerate((0x10, 0x18, 0x00, 0x08)):
            b = t[base + y]; x = pair * 2
            px[y][x] = b & 15; px[y][x + 1] = b >> 4
    return px

def encode_tile(px):
    t = bytearray(32)
    for y in range(8):
        for pair, base in enumerate((0x10, 0x18, 0x00, 0x08)):
            x = pair * 2
            t[base + y] = (px[y][x] & 15) | ((px[y][x + 1] & 15) << 4)
    return bytes(t)

def from_art(rows, cmap):
    return [[cmap.get(ch, 0) for ch in r.ljust(8)[:8]] for r in rows]

T = {}          # nom -> (numero, pixels)
def add(name, px):
    """Le fond des tuiles maison est la couleur 2 (comme les lettres du BIOS) : la barre de selection reste pleine."""
    T[name] = (BASE + len(T), [[2 if v == 0 else v for v in row] for row in px])

# --- barres lisses : remplissage vertical (bas -> haut) 0..8 px, couleur 1 ; liseré couleur 2 sur les bords
for k in range(9):
    add(f"v{k}", [[(1 if (7 - y) < k and 0 < x < 7 else 0) for x in range(8)] for y in range(8)])
# --- barre de progression horizontale 0..8 px (couleur 1 plein, couleur 2 rail)
for k in range(9):
    add(f"h{k}", [[(1 if x < k and 1 < y < 6 else (4 if y in (3, 4) else 0)) for x in range(8)] for y in range(8)])
# --- crete maintenue : trait blanc (couleur 3) de 2 px dont le haut est a k px du bas (k = 1..8)
for k in range(1, 9):
    add(f"pk{k}", [[(3 if (7 - y) in (k - 1, k - 2) and 0 < x < 7 else 0) for x in range(8)] for y in range(8)])
# --- icones (couleur 1)
art = {
 "play":  ["        ", " X      ", " XXX    ", " XXXXX  ", " XXXXXX ", " XXXXX  ", " XXX    ", " X      "],
 "pause": ["        ", " XX XX  ", " XX XX  ", " XX XX  ", " XX XX  ", " XX XX  ", " XX XX  ", "        "],
 "stop":  ["        ", " XXXXXX ", " XXXXXX ", " XXXXXX ", " XXXXXX ", " XXXXXX ", " XXXXXX ", "        "],
 "note":  ["   XXXX ", "   X  X ", "   X  X ", "   X  X ", " XXX XXX", "XXXXXXXX", "XXX XXX ", "        "],
 "left":  ["        ", "     X  ", "    XX  ", "   XXX  ", "  XXXX  ", "   XXX  ", "    XX  ", "     X  "],
 "right": ["        ", "  X     ", "  XX    ", "  XXX   ", "  XXXX  ", "  XXX   ", "  XX    ", "  X     "],
 "loop":  ["        ", "  XXXX  ", " X    X ", " X   XXX", " X    X ", " X      ", "  XXXX  ", "        "],
 "auto":  ["        ", " X  X   ", " XX XX  ", " XXXXXX ", " XXXXXXX", " XXXXXX ", " XX XX  ", " X  X   "],
}
for k, a in art.items():
    add(k, from_art(a, {"X": 1}))
# --- boutons de la manette : disque couleur 2, lettre couleur 1
disc = ["  XXXX  ", " XXXXXX ", "XXXXXXXX", "XXXXXXXX", "XXXXXXXX", "XXXXXXXX", " XXXXXX ", "  XXXX  "]
letters = {"A": ["        ", "   ..   ", "  .  .  ", "  .  .  ", "  ....  ", "  .  .  ", "  .  .  ", "        "],
           "B": ["        ", "  ...   ", "  .  .  ", "  ...   ", "  .  .  ", "  .  .  ", "  ...   ", "        "],
           "C": ["        ", "   ...  ", "  .     ", "  .     ", "  .     ", "  .     ", "   ...  ", "        "],
           "D": ["        ", "  ...   ", "  .  .  ", "  .  .  ", "  .  .  ", "  .  .  ", "  ...   ", "        "]}
for k, l in letters.items():
    px = from_art(disc, {"X": 1})
    for y in range(8):
        for x in range(8):
            if l[y][x] == ".": px[y][x] = 3
    add("btn" + k, px)
# --- cadre : coins + bords (couleur 1)
frame = {
 "tl": ["        ", "        ", "        ", "   XXXXX", "   X    ", "   X    ", "   X    ", "   X    "],
 "tr": ["        ", "        ", "        ", "XXXXX   ", "    X   ", "    X   ", "    X   ", "    X   "],
 "bl": ["   X    ", "   X    ", "   X    ", "   XXXXX", "        ", "        ", "        ", "        "],
 "br": ["    X   ", "    X   ", "    X   ", "XXXXX   ", "        ", "        ", "        ", "        "],
 "hz": ["        ", "        ", "        ", "XXXXXXXX", "        ", "        ", "        ", "        "],
 "vl": ["   X    "] * 8,
 "vr": ["    X   "] * 8,
 "full": ["XXXXXXXX"] * 8,
}
for k, a in frame.items():
    add(k, from_art(a, {"X": 1}))
# --- ajoutees en fin de liste (les numeros des tuiles precedentes ne bougent pas)
# notes de l'entete, 6 rangees de haut : 3 poses decalees de 0, 1 et 2 pixels vers le bas (rebond de 2 px)
hn = ["   XXXX ", "   X  X ", "   X  X ", " XXX XXX", "XXXXXXXX", "XXX XXX "]       # double croche (jaune)
wn = ["    XX  ", "    X X ", "    X   ", "  XXX   ", " XXXX   ", "  XX    "]       # croche (blanche)
for k in range(3):
    add(f"hn{k}", from_art(["        "] * k + hn + ["        "] * (2 - k), {"X": 1}))
for k in range(3):
    add(f"wn{k}", from_art(["        "] * k + wn + ["        "] * (2 - k), {"X": 1}))
# case entierement transparente (couleur 0) : l'economiseur en remplit la couche fix pour laisser voir les sprites
T["clear"] = (BASE + len(T), [[0] * 8 for _ in range(8)])
# mode aleatoire (2.5.19) : deux fleches croisees
add("rand", from_art(["      X ", "XXX  XXX", "   X  X ", "    X   ", "    X   ", "   X  X ", "XXX  XXX", "      X "], {"X": 1}))
# mini vumetre de l'economiseur (2.5.39) : DEUX voies par case, fond TRANSPARENT (couleur 0, pas de add()) ;
# tuile m00 + 9 x a + b : barre de gauche (x 1..3, couleur 1) remplie de a px depuis le bas, barre de droite (x 5..7,
# couleur 5) de b px ; 81 tuiles.  La couleur 5 de la palette de la case = couleur 1 de la voie de droite (hud_vpal).
for a in range(9):
    for b in range(9):
        T[f"m{a}{b}"] = (BASE + len(T), [[(1 if 1 <= x <= 3 and 7 - y < a else 5 if 5 <= x <= 7 and 7 - y < b else 0)
                                           for x in range(8)] for y in range(8)])

def tile_px(n):
    if n >= BASE:
        for name, (num, px) in T.items():
            if num == n: return px
    return decode_tile(SFIX[n * 32:(n + 1) * 32])

def srom():
    """S-ROM de la cartouche : police du BIOS + tuiles maison a partir de BASE."""
    s = bytearray(SFIX[:0x20000].ljust(0x20000, b"\0"))
    for name, (num, px) in T.items():
        s[num * 32:(num + 1) * 32] = encode_tile(px)
    return bytes(s)

# --- rendu de maquette
class Screen:
    def __init__(self, bg=(0, 0, 0)):
        self.cells = {}
        self.bg = bg
    def put(self, col, row, tile, c1, c2=None):
        self.cells[(col, row)] = (tile, c1, c2)
    def text(self, col, row, s, c1, c2=None):
        for i, ch in enumerate(s):
            self.put(col + i, row, ord(ch), c1, c2)
    def icon(self, col, row, name, c1, c2=None):
        self.put(col, row, T[name][0], c1, c2)
    def render(self, scale=3):
        from PIL import Image
        im = Image.new("RGB", (320, 224), self.bg)
        for (col, row), (tile, c1, c2) in self.cells.items():
            px = tile_px(tile)
            for y in range(8):
                for x in range(8):
                    v = px[y][x]
                    if v == 1: im.putpixel((col * 8 - 8 * 0 + x - 0, (row - 2) * 8 + y), c1) if 0 <= (row - 2) * 8 + y < 224 and 0 <= col * 8 + x < 320 else None
                    elif v == 2 and c2 is not None:
                        if 0 <= (row - 2) * 8 + y < 224 and 0 <= col * 8 + x < 320: im.putpixel((col * 8 + x, (row - 2) * 8 + y), c2)
        return im.resize((320 * scale, 224 * scale), Image.NEAREST)
print("tuiles maison:", len(T), "de 0x%X a 0x%X" % (BASE, BASE + len(T) - 1))

def asm_equs():
    return "\n".join(f"        .equ    T_{k.upper()}, 0x{n:03X}" for k, (n, _) in T.items())


if __name__ == "__main__":
    # python tiles.py <dossier build> : ecrit tiles_equ.S (numeros des tuiles) et tiles.bin (tuiles maison)
    out = sys.argv[1] if len(sys.argv) > 1 else "build"
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, "tiles_equ.S"), "w").write(asm_equs() + "\n")
    blob = b"".join(encode_tile(px) for _, (n, px) in sorted(T.items(), key=lambda x: x[1][0]))
    open(os.path.join(out, "tiles.bin"), "wb").write(blob)
    print(len(T), "tiles ->", out)
