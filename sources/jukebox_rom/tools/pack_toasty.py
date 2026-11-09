"""Integrate the "Toasty" pictures into ngt_studio.py (constant JB_TOASTY_B85), already converted for the Neo Geo:
at most 112 x 96 px, transparent background, 4 palettes of 15 colours, each 16x16 tile using the closest palette.

  python tools/pack_toasty.py [art/toasty_frame*.png ...] [path/to/ngt_studio.py]

Pictures (default: art/toasty_frame.png, toasty_frame_2.png, toasty_frame_3.png, toasty_frame_4.png, in that order; at most JB_TOASTY_NCH):
one frame of each sprite sheet supplied by Nicolas (character on a magenta background), cropped without loss
(portraits: (c) their authors, all rights reserved, NOT under the MIT License - see art/RIGHTS.txt).
The 16 frames of a sheet are the same pose moved vertically (with small random differences between frames):
the jukebox moves a single picture itself (core.S, to_dy), which is smoother.
Each picture is scaled to fit 112 x 96 px, flush bottom right of its block of 16-px columns.  2.5.33: all the heads
have the same width on screen (HEAD_ROWS: rows of the source where only the head shows): the largest width that
fits for every picture (the others are scaled to it); a picture without HEAD_ROWS entry is just fitted.

Format (then lzma/xz, then base85): number of pictures (B), then for each: length (H) + stream =
columns (B), tile rows (B), palettes (B), first non-empty row of each column
(B x columns), palettes (16 H each, colour 0 unused = transparent), then column by column, from its first non-empty
row to the bottom: palette of the tile (B) + 16 x 16 pixels, 2 per byte (high nibble first), row by row.
Deterministic: same PNGs -> same bytes.
"""
import base64, glob, lzma, os, re, struct, sys
import numpy as np
from PIL import Image
from scipy import ndimage

here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NCH_MAX = 4                         # = TO_NCH de core.S / JB_TOASTY_NCH
pngs = [a for a in sys.argv[1:] if a.lower().endswith(".png")] or sorted(glob.glob(os.path.join(here, "art", "toasty_frame*.png")))
studio = next((a for a in sys.argv[1:] if a.endswith(".py")), os.path.join(here, "..", "ngt_studio.py"))
if not 1 <= len(pngs) <= NCH_MAX:
    sys.exit(f"1 to {NCH_MAX} pictures expected, {len(pngs)} given")
WMAX, ROWS, NPAL = 112, 6, 4        # 7 colonnes de sprites au plus, 6 rangees de tuiles (96 px), palettes 33..36 du jukebox


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


def word(c):                        # comme jb_box_frames : RGB 5 bits -> mot de couleur Neo Geo
    r, g, b = (int(round(v * 31 / 255)) for v in c)
    return ((r & 1) << 14) | ((g & 1) << 13) | ((b & 1) << 12) | ((r >> 1) << 8) | ((g >> 1) << 4) | (b >> 1)


# Taille de la tete : meme largeur de tete a l'ecran pour tous les personnages (2.5.33).  Plages de rangees de l'image
# source ou seule la tete (cheveux / casquette / oreilles compris, ni epaules ni mug) est presente : sa largeur mesure la tete.
HEAD_ROWS = {"toasty_frame.png": (30, 130), "toasty_frame_2.png": (20, 190), "toasty_frame_3.png": (35, 80),
             "toasty_frame_4.png": (88, 275)}


def load(png):
    # detourage (fond magenta bruite, pas exactement #FF00FF) ; les petites taches isolees du fond (bruit) sont retirees
    # (seul le plus gros objet et ce qui le touche reste), puis recadrage sur le personnage
    a = np.asarray(Image.open(png).convert("RGB")).astype(float)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    fg = ~((r > 170) & (g < 110) & (b > 100) & (b < 230) & (r - g > 120))
    lab, nl = ndimage.label(fg)
    if nl > 1:
        size = ndimage.sum(fg, lab, range(1, nl + 1))
        keep = [i + 1 for i, v in enumerate(size) if v >= 0.02 * size.max()]
        fg = np.isin(lab, keep)
    head = None
    if os.path.basename(png) in HEAD_ROWS:
        r0, r1 = HEAD_ROWS[os.path.basename(png)]
        xs = np.nonzero(fg[r0:r1].any(0))[0]
        head = int(xs.max() + 1 - xs.min())
    ys, xs = np.nonzero(fg)
    a, fg = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1], fg[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(float)
    sh, sw = fg.shape
    return a, fg, sh, sw, head


def fit(sh, sw):                    # echelle maximale qui tient dans 112 x 96 px
    return min(WMAX / sw, 16 * ROWS / sh)


def pack_one(L, scale):
    # reduction : chaque pixel = moyenne des seuls pixels du personnage de sa zone (aucune frange rose), transparent si la
    # zone est a moins de 50 % dans le personnage
    a, fg, sh, sw, _ = L
    W, H = max(1, int(round(sw * scale))), max(1, int(round(sh * scale)))
    if W > WMAX or H > 16 * ROWS:
        sys.exit(f"picture too large: {W} x {H} px for {WMAX} x {16 * ROWS}")
    cols = -(-W // 16)
    WT, xoff = cols * 16, cols * 16 - W                   # colle au bord droit de son bloc de colonnes
    img = np.zeros((16 * ROWS, WT, 3)); opaque = np.zeros((16 * ROWS, WT), bool)
    for j in range(H):
        for i in range(W):
            Y0, X0 = int(j * sh / H), int(i * sw / W)
            Y1, X1 = max(Y0 + 1, int(np.ceil((j + 1) * sh / H))), max(X0 + 1, int(np.ceil((i + 1) * sw / W)))
            m = fg[Y0:Y1, X0:X1]
            if m.mean() >= 0.5:
                img[16 * ROWS - H + j, xoff + i] = (a[Y0:Y1, X0:X1] * m[..., None]).sum((0, 1)) / m.sum()   # cale en bas
                opaque[16 * ROWS - H + j, xoff + i] = True
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
    return bytes(out), W, H, cols, first


loaded = [load(p) for p in pngs]
scales = [fit(L[2], L[3]) for L in loaded]
heads = [L[4] * sc if L[4] else None for L, sc in zip(loaded, scales)]       # largeur de tete a l'ecran au plus grand
if all(heads):                                                           # meme largeur de tete pour tous : la plus grande
    target = min(heads)                                                  #   qui tient pour chacun
    scales = [target / L[4] for L in loaded]
streams, infos = [], []
for p, L, sc in zip(pngs, loaded, scales):
    st, W, H, cols, first = pack_one(L, sc)
    streams.append(st)
    hw = f", head {L[4] * sc:.1f} px wide" if L[4] else ""
    infos.append(f"{os.path.basename(p)}: {W} x {H} px{hw}, {cols} columns (first rows {first}), {sum(ROWS - f for f in first)} tiles")
out = bytes([len(streams)]) + b"".join(struct.pack(">H", len(st)) + st for st in streams)
b = base64.b85encode(lzma.compress(bytes(out), preset=9 | lzma.PRESET_EXTREME)).decode()
b = "\n".join(b[i:i + 100] for i in range(0, len(b), 100))
s = open(studio, encoding="utf-8").read()
s, n = re.subn(r'(JB_TOASTY_B85 = """\n)([0-9A-Za-z!#$%&()*+;<=>?@^_`{|}~\n-]*)(""")', lambda m: m.group(1) + b + "\n" + m.group(3), s)
if n != 1:
    sys.exit("JB_TOASTY_B85 not found in " + studio)
open(studio, "w", encoding="utf-8").write(s)
print("\n".join(infos))
print(f"{len(out)} bytes -> {len(b)} characters written into {studio}")
