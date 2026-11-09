"""Integrate the "Aurelien - Toasty" picture into ngt_studio.py (constant JB_TOASTY_B85), already converted for the
Neo Geo: 112 px wide, transparent background, 4 palettes of 15 colours, each 16x16 tile using the closest palette.

  python tools/pack_toasty.py [art/toasty_frame.png] [path/to/ngt_studio.py]

Source: one frame of the sheet supplied by Nicolas (character drinking from a mug, magenta background), cropped
(picture: (c) Aurelien / Bouz, all rights reserved, NOT under the MIT License),
without loss: art/toasty_frame.png.  The 16 frames of the sheet are the same pose moved vertically (with small random
differences between frames): the jukebox moves this single picture itself (core.S, to_dy), which is smoother.

Format (then lzma/xz, then base85): columns (B), tile rows (B), palettes (B), first non-empty row of each column
(B x columns), palettes (16 H each, colour 0 unused = transparent), then column by column, from its first non-empty
row to the bottom: palette of the tile (B) + 16 x 16 pixels, 2 per byte (high nibble first), row by row.
Deterministic: same PNG -> same bytes.
"""
import base64, lzma, os, re, struct, sys
import numpy as np
from PIL import Image

here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
png = next((a for a in sys.argv[1:] if a.lower().endswith(".png")), os.path.join(here, "art", "toasty_frame.png"))
studio = next((a for a in sys.argv[1:] if a.endswith(".py")), os.path.join(here, "..", "ngt_studio.py"))
W, ROWS, NPAL = 112, 6, 4          # 7 colonnes de sprites, 6 rangees de tuiles (96 px), palettes 33..36 du jukebox

# 1. detourage (fond magenta bruite, pas exactement #FF00FF) et reduction : chaque pixel = moyenne des seuls pixels
#    du personnage de sa zone (aucune frange rose), transparent si la zone est a moins de 50 % dans le personnage
a = np.asarray(Image.open(png).convert("RGB")).astype(float)
r, g, b = a[..., 0], a[..., 1], a[..., 2]
fg = ~((r > 170) & (g < 110) & (b > 100) & (b < 230) & (r - g > 120))
ys, xs = np.nonzero(fg)
a, fg = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1], fg[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(float)
sh, sw = fg.shape
H = int(round(sh * W / sw))
if H > 16 * ROWS:
    sys.exit(f"picture too tall: {H} px for {16 * ROWS}")
img = np.zeros((16 * ROWS, W, 3)); opaque = np.zeros((16 * ROWS, W), bool)
for j in range(H):
    for i in range(W):
        Y0, X0 = int(j * sh / H), int(i * sw / W)
        Y1, X1 = max(Y0 + 1, int(np.ceil((j + 1) * sh / H))), max(X0 + 1, int(np.ceil((i + 1) * sw / W)))
        m = fg[Y0:Y1, X0:X1]
        if m.mean() >= 0.5:
            img[16 * ROWS - H + j, i] = (a[Y0:Y1, X0:X1] * m[..., None]).sum((0, 1)) / m.sum()   # cale en bas
            opaque[16 * ROWS - H + j, i] = True

# 2. palettes par tuile (k-means deterministe), couleurs a la precision Neo Geo (5 bits par composante)
def kmeans(X, k, seed):
    rng = np.random.default_rng(seed)
    C = [X[rng.integers(len(X))]]
    for _ in range(k - 1):
        d = np.min(((X[:, None] - np.array(C)[None]) ** 2).sum(-1), 1)
        C.append(X[rng.choice(len(X), p=d / d.sum())] if d.sum() > 0 else X[rng.integers(len(X))])
    C = np.array(C, float)
    for _ in range(25):
        lab = np.argmin(((X[:, None] - C[None]) ** 2).sum(-1), 1)
        for j in range(k):
            if (lab == j).any():
                C[j] = X[lab == j].mean(0)
    return C
q5 = lambda c: np.clip(np.round(c * 31 / 255), 0, 31)
cols = W // 16
tiles = [(c, r) for c in range(cols) for r in range(ROWS)]
px = {t: img[t[1] * 16:t[1] * 16 + 16, t[0] * 16:t[0] * 16 + 16][opaque[t[1] * 16:t[1] * 16 + 16, t[0] * 16:t[0] * 16 + 16]] for t in tiles}
used = [t for t in tiles if len(px[t])]
feat = np.array([px[t].mean(0) for t in used])
grp = np.argmin(((feat[:, None] - kmeans(feat, NPAL, 99)[None]) ** 2).sum(-1), 1)
for _ in range(8):
    pals = []
    for p in range(NPAL):
        X = np.vstack([px[t] for t, gp in zip(used, grp) if gp == p] or [np.zeros((1, 3))])
        pals.append(q5(kmeans(X, 15, p)) * 255 / 31 if len(X) >= 15 else q5(np.vstack([X] * 15)[:15]) * 255 / 31)
    err = np.array([[np.min(((px[t][:, None] - pl[None]) ** 2).sum(-1), 1).sum() for pl in pals] for t in used])
    if (err.argmin(1) == grp).all():
        break
    grp = err.argmin(1)
tpal = dict(zip(used, grp))

def word(c):                        # comme jb_box_frames : RGB 5 bits -> mot de couleur Neo Geo
    r, g, b = (int(round(v * 31 / 255)) for v in c)
    return ((r & 1) << 14) | ((g & 1) << 13) | ((b & 1) << 12) | ((r >> 1) << 8) | ((g >> 1) << 4) | (b >> 1)

first = [min([r for r in range(ROWS) if len(px[(c, r)])] or [ROWS]) for c in range(cols)]
out = bytearray([cols, ROWS, NPAL]) + bytes(first)
for pl in pals:
    out += struct.pack(">16H", 0x8000, *[word(c) for c in pl])
for c in range(cols):
    for r in range(first[c], ROWS):
        p = tpal.get((c, r), 0)
        blk, m = img[r * 16:r * 16 + 16, c * 16:c * 16 + 16], opaque[r * 16:r * 16 + 16, c * 16:c * 16 + 16]
        idx = np.where(m, ((blk[..., None, :] - pals[p][None, None]) ** 2).sum(-1).argmin(-1) + 1, 0)
        out.append(p)
        out += bytes((int(idx[y, x]) << 4) | int(idx[y, x + 1]) for y in range(16) for x in range(0, 16, 2))
b = base64.b85encode(lzma.compress(bytes(out), preset=9 | lzma.PRESET_EXTREME)).decode()
b = "\n".join(b[i:i + 100] for i in range(0, len(b), 100))
s = open(studio, encoding="utf-8").read()
s, n = re.subn(r'(JB_TOASTY_B85 = """\n)([0-9A-Za-z!#$%&()*+;<=>?@^_`{|}~\n-]*)(""")', lambda m: m.group(1) + b + "\n" + m.group(3), s)
if n != 1:
    sys.exit("JB_TOASTY_B85 not found in " + studio)
open(studio, "w", encoding="utf-8").write(s)
print(f"{W} x {H} px, {cols} columns (first rows {first}), {sum(ROWS - f for f in first)} tiles, {len(out)} bytes -> {len(b)} characters written into {studio}")
