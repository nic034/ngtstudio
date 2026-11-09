"""Integrate the screen-saver picture sheets (1 to 6) into ngt_studio.py (constant JB_BOXES_B85), already converted
(frames reduced, 16-colour palette, outline) exactly as jb_box_frames() does at build time: the built-in sheets give
the same ROM, byte for byte, as the PNG files placed next to the program.

  python tools/pack_boxes.py box.png console.png delta_logo.png@1.3 delta_triangle.png@1.3 [path/to/ngt_studio.py]
  (2.5.21: the four built-in sheets; the two chip sheets of 2.5.19-2.5.20 were removed)
  (file.png@1.3 : that sheet 30 % larger, capped at 46 px high / 62 px wide, see jb_box_frames)
  2.5.32: a sheet can also be an animated GIF on a magenta background (art/jukebox_cartridge.gif@1.2), and
  keep:K re-uses sheet K (0 = first) of the sheets already in ngt_studio.py, whose PNG are not in the repository:
  python tools/pack_boxes.py keep:0 keep:1 keep:2 keep:3 art/jukebox_cartridge.gif@1.2 keep:4
  = box, console, logo, triangle, cartridge (5 flying objects), then the CD (last sheet, fixed, top right)

Format (then lzma/xz, then base85): number of sheets (1 byte), then per sheet:
  frames (H), wide (B), sprite columns (B), tile rows (B), palette (16 H), then the frames, 2 pixels per byte
  (high nibble first), rows of 16 x columns pixels, 16 x rows rows per frame.
"""
import base64, lzma, os, re, runpy, struct, sys

here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
g = runpy.run_path(next((a for a in sys.argv[1:] if a.endswith(".py")), os.path.join(here, "..", "ngt_studio.py")), run_name="x")
pngs = [a for a in sys.argv[1:] if a.startswith("keep:") or g["jb_box_spec"](a)[0].lower().endswith((".png", ".gif"))]   # "planche.png@1.3" : agrandie de 30 %
old = g["_jb_builtin_boxes"]()
studio = next((a for a in sys.argv[1:] if a.endswith(".py")), os.path.join(here, "..", "ngt_studio.py"))
if not 1 <= len(pngs) <= 6:
    sys.exit(__doc__)
out = bytearray([len(pngs)])
for p in pngs:
    frames, pal, wide, cols, rows = old[int(p[5:])] if p.startswith("keep:") else g["jb_box_frames"](*g["jb_box_spec"](p))
    out += struct.pack(">HBBB16H", len(frames), int(wide), cols, rows, *pal)
    for im in frames:
        for r in im:
            out += bytes((r[i] << 4) | r[i + 1] for i in range(0, len(r), 2))
b = base64.b85encode(lzma.compress(bytes(out), preset=9 | lzma.PRESET_EXTREME)).decode()
b = "\n".join(b[i:i + 100] for i in range(0, len(b), 100))
s = open(studio, encoding="utf-8").read()
# corps = caracteres base85 et sauts de ligne seulement (jamais de guillemet) : ne peut pas deborder sur la suite
s, n = re.subn(r'(JB_BOXES_B85 = """\n)([0-9A-Za-z!#$%&()*+;<=>?@^_`{|}~\n-]*)(""")', lambda m: m.group(1) + b + "\n" + m.group(3), s)
if n != 1:
    sys.exit("JB_BOXES_B85 not found in " + studio)
open(studio, "w", encoding="utf-8").write(s)

print(f"{len(pngs)} sheet(s), {len(out)} bytes -> {len(b)} characters written into {studio}")
