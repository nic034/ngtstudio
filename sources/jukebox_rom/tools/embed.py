"""Assemble src/ (like tbuild.py) and write the binaries and their offsets into ngt_studio.py:
JB_PROM_B64, JB_M1_B64, JB_TILES_B64 (zlib level 9 + base64, lines of 112 characters), JB_SECBLK_OFF,
JB_BOXDATA_OFF, JB_TOASTY_OFF, JB_STEXT_OFF.  Then check that ngt_studio.py gives back exactly the assembled bytes.

  python tools/embed.py [path/to/ngt_studio.py]
"""
import base64, os, re, runpy, sys, zlib
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(here, "tools"))
import tbuild
studio = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "..", "ngt_studio.py")
prom, m1, sec = tbuild.asm()
tiles = open(os.path.join(here, "build", "tiles.bin"), "rb").read()
enc = lambda d: "\n".join((lambda b: [b[i:i + 112] for i in range(0, len(b), 112)])(base64.b64encode(zlib.compress(d, 9)).decode()))
s = open(studio, encoding="utf-8").read()
for name, data in (("JB_PROM_B64", prom), ("JB_M1_B64", m1), ("JB_TILES_B64", tiles)):
    s, n = re.subn(r'(%s = """\n)([0-9A-Za-z+/=\n]*)(""")' % name, lambda m: m.group(1) + enc(data) + "\n" + m.group(3), s)
    if n != 1:
        sys.exit(name + " not found in " + studio)
for name, val in (("JB_SECBLK_OFF", sec), ("JB_BOXDATA_OFF", tbuild.asm.boxdata), ("JB_TOASTY_OFF", tbuild.asm.toasty),
                  ("JB_STEXT_OFF", tbuild.asm.stext)):
    s, n = re.subn(r"^(%s = )0x[0-9a-fA-F]+" % name, lambda m: m.group(1) + "0x%x" % val, s, flags=re.M)
    if n != 1:
        sys.exit(name + " not found in " + studio)
open(studio, "w", encoding="utf-8").write(s)
g = runpy.run_path(studio, run_name="x")
ok = (g["_jb_bin"](g["JB_PROM_B64"]) == prom and g["_jb_bin"](g["JB_M1_B64"]) == m1 and g["_jb_bin"](g["JB_TILES_B64"]) == tiles
      and (g["JB_SECBLK_OFF"], g["JB_BOXDATA_OFF"], g["JB_TOASTY_OFF"], g["JB_STEXT_OFF"])
      == (sec, tbuild.asm.boxdata, tbuild.asm.toasty, tbuild.asm.stext))
print(f"68000 program {len(prom)} bytes (security block 0x{sec:X}, boxdata 0x{tbuild.asm.boxdata:X}, toastydata 0x{tbuild.asm.toasty:X}),"
      f" Z80 driver {len(m1)} bytes, tiles {len(tiles)} bytes -> {studio}: {'OK, read back identical' if ok else 'MISMATCH'}")
sys.exit(0 if ok else 1)
