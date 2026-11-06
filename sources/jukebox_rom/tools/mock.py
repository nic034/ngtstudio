import sys; sys.path.insert(0, ".")
from tiles import Screen, T
import colorsys
from PIL import Image
W, Y, C, G, R, O, M, GR, DK, BL = (255,255,255), (255,230,40), (60,220,255), (80,240,90), (255,60,50), (255,150,30), (240,80,230), (130,130,140), (40,40,70), (60,110,255)
def rainbow(s, x, y, ph=0):
    for i, ch in enumerate(s):
        r, g, b = colorsys.hsv_to_rgb(((i + ph) % 16) / 16, .7, 1)
        scr.text(x + i, y, ch, (int(r*255), int(g*255), int(b*255)))
def frame(x0, y0, x1, y1, col):
    scr.icon(x0, y0, "tl", col); scr.icon(x1, y0, "tr", col); scr.icon(x0, y1, "bl", col); scr.icon(x1, y1, "br", col)
    for x in range(x0 + 1, x1): scr.icon(x, y0, "hz", col); scr.icon(x, y1, "hz", col)
    for y in range(y0 + 1, y1): scr.icon(x0, y, "vl", col); scr.icon(x1, y, "vr", col)
def bar_h(x, y, n, frac, col, rail):
    px = int(round(frac * n * 8))
    for i in range(n):
        k = max(0, min(8, px - i * 8)); scr.icon(x + i, y, f"h{k}", col, rail)
def vu(x, y, h, w, lvl, col):           # lvl 0..1
    px = int(round(lvl * h * 8))
    for r in range(h):
        k = max(0, min(8, px - (h - 1 - r) * 8))
        hue = col if r > h * 0.45 else (Y if r > h * 0.2 else R)
        for c in range(w): scr.icon(x + c, y + r, f"v{k}", hue)
def buttons(x, y):
    for i, (b, c, t) in enumerate((("A", (230,40,40), "PLAY"), ("B", (240,200,0), "STOP"))):
        pass
# ------------------------------------------------------------- vue liste
scr = Screen((8, 8, 24))
scr.icon(2, 2, "note", Y); rainbow("NEO GEO JUKEBOX", 4, 2)
scr.text(29, 2, "ROM 34%", GR)
frame(1, 3, 38, 7, BL)
scr.icon(3, 4, "play", G); scr.text(5, 4, "Art of Fighting 2", C)
scr.text(5, 5, "TRACK 05/33", W); scr.text(18, 5, "00:23 / 01:58", W)
scr.icon(33, 5, "auto", Y); scr.text(34, 5, "AUTO", Y)
bar_h(3, 6, 34, 23 / 118, C, (50, 60, 110))
tracks = [("01", "00:07", ""), ("02", "01:21", "L"), ("03", "01:08", "L"), ("04", "01:02", "L"), ("05", "00:59", "L"), ("06", "01:04", "L"),
          ("07", "01:50", "L"), ("08", "01:03", "L"), ("09", "01:15", "L"), ("10", "00:41", ""), ("11", "02:42", "")]
for i, (n, d, l) in enumerate(tracks):
    y = 9 + i
    sel, play = (i == 6), (i == 4)
    fg, bgc = (W, None)
    if sel: fg, bgc = (0, 0, 0), (255, 220, 40)
    line = f"  TRACK {n}    {d}    "
    if sel:
        scr.text(2, y, " " * 23, fg, bgc)
    scr.text(2, y, line, (C if play and not sel else fg), bgc)
    if play: scr.icon(2, y, "play", G if not sel else (0, 0, 0), bgc)
    if l: scr.icon(22, y, "loop", (0, 0, 0) if sel else GR, bgc)
lv = [0.9, 0.55, 0.3, 0.75, 0.15, 0.85, 0.6]
cols = [C, C, C, C, G, O, M]
for i in range(7):
    vu(27 + i * 2 - 0, 9, 11, 1, lv[i], cols[i])
for i, ch in enumerate("1234SAB"):
    scr.text(27 + i * 2, 20, ch, cols[i])
scr.icon(2, 22, "left", GR); scr.text(4, 22, "GAME 1/3", W); scr.icon(13, 22, "right", GR)
scr.text(15, 22, "next: countb", GR)
hx = 2
for b, c, t in (("A", (230,40,40), "PLAY/PAUSE"), ("B", (240,200,0), "STOP"), ("C", (60,200,60), "PREV"), ("D", (60,110,255), "NEXT")):
    scr.icon(hx, 24, "btn" + b, (255, 255, 255), c); scr.text(hx + 2, 24, t, GR); hx += len(t) + 4
scr.text(2, 25, "START", W); scr.text(8, 25, "BIG VU", GR); scr.text(16, 25, "SELECT", W); scr.text(23, 25, "AUTO/LOOP", GR)
scr.icon(2, 27, "note", O); scr.text(4, 27, "NOW PLAYING  ART OF FIGHTING 2  T05"[:34], O)
a = scr.render(3)
# ------------------------------------------------------------- vue plein ecran
scr = Screen((8, 8, 24))
scr.icon(2, 2, "note", Y); rainbow("NEO GEO JUKEBOX", 4, 2, 5); scr.text(29, 2, "ROM 34%", GR)
scr.icon(2, 4, "play", G); scr.text(4, 4, "Art of Fighting 2", C); scr.text(23, 4, "TRACK 05/33", W)
scr.text(4, 5, "00:23 / 01:58", W); scr.icon(33, 5, "auto", Y); scr.text(34, 5, "AUTO", Y)
lv = [0.95, 0.6, 0.35, 0.8, 0.2, 0.9, 0.5]
for i in range(7):
    vu(3 + i * 5, 7, 15, 4, lv[i], cols[i])
for i, t in enumerate(("FM1", "FM2", "FM3", "FM4", "SSG", "ADPA", "ADPB")):
    scr.text(3 + i * 5, 22, t, cols[i])
bar_h(3, 24, 34, 23 / 118, C, (50, 60, 110))
hx = 2
for b, c, t in (("A", (230,40,40), "PAUSE"), ("C", (60,200,60), "PREV"), ("D", (60,110,255), "NEXT")):
    scr.icon(hx, 26, "btn" + b, (255, 255, 255), c); scr.text(hx + 2, 26, t, GR); hx += len(t) + 4
scr.text(hx, 26, "START", W); scr.text(hx + 6, 26, "LIST", GR)
b = scr.render(3)
out = Image.new("RGB", (a.width * 2 + 24, a.height), (60, 60, 60)); out.paste(a, (0, 0)); out.paste(b, (a.width + 24, 0))
out.save("jukebox_ui_mockup.png")
