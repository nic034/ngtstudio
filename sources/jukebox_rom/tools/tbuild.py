"""Assemble the 68000 jukebox program and the Z80 driver from src/, then (optionally) builds a test ROM
with them through ngt_studio.py, without touching ngt_studio.py.
Requires: m68k-linux-gnu-as/ld/objcopy (binutils for m68k) and z80asm.

  python tools/tbuild.py                          -> build/prom_nosec.bin, build/m1drv.bin, build/tiles.bin
  python tools/tbuild.py OUTDIR game1.ngt ...     -> also a MAME test set in OUTDIR (needs NGT_BIOS=path/neogeo.zip)
"""
import runpy, subprocess, base64, zlib, sys, os, shutil
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))          # jukebox_rom/
STUDIO = os.environ.get("NGT_STUDIO", os.path.join(here, "..", "ngt_studio.py"))

def asm():
    b = os.path.join(here, "build")
    os.makedirs(b, exist_ok=True)
    sys.path.insert(0, os.path.join(here, "tools"))
    import tiles
    open(os.path.join(b, "tiles_equ.S"), "w").write(tiles.asm_equs() + "\n")
    open(os.path.join(b, "tiles.bin"), "wb").write(b"".join(tiles.encode_tile(px) for _, (n, px) in sorted(tiles.T.items(), key=lambda x: x[1][0])))
    open(os.path.join(b, "sec.bin"), "wb").write(bytes(122))          # BIOS security block: filled in at build time
    subprocess.check_call(["m68k-linux-gnu-as", "-m68000", "--register-prefix-optional", "-o", b + "/jbz.o", "src/jukebox.S"], cwd=here)
    subprocess.check_call(["m68k-linux-gnu-ld", "-e", "0", "-Ttext=0", "-o", b + "/jbz.elf", b + "/jbz.o"], cwd=here)
    subprocess.check_call(["m68k-linux-gnu-objcopy", "-O", "binary", b + "/jbz.elf", b + "/prom_nosec.bin"], cwd=here)
    subprocess.check_call(["z80asm", "-o", b + "/m1drv.bin", "src/m1drv.asm"], cwd=here)
    nm = subprocess.check_output(["m68k-linux-gnu-nm", b + "/jbz.elf"], text=True)
    sym = lambda n: int(next(l.split()[0] for l in nm.splitlines() if l.endswith(" " + n)), 16)
    asm.boxdata = sym("boxdata")                 # objets animes de l'economiseur (rempli par build_cart)
    return open(b + "/prom_nosec.bin", "rb").read(), open(b + "/m1drv.bin", "rb").read(), sym("secblk")

if __name__ == "__main__":
    prom, m1, sec = asm()
    print("68000 program", len(prom), "bytes, security block at 0x%X, boxdata at 0x%X ; Z80 driver" % (sec, asm.boxdata), len(m1), "bytes")
    if len(sys.argv) > 2:
        g = runpy.run_path(STUDIO, run_name="x")
        enc = lambda d: base64.b64encode(zlib.compress(d, 9)).decode()
        G = g["build_cart"].__globals__          # run_path returns a copy: patch the real globals
        G["JB_PROM_B64"], G["JB_M1_B64"], G["JB_SECBLK_OFF"] = enc(prom), enc(m1), sec
        G["JB_BOXDATA_OFF"] = asm.boxdata
        G["JB_TILES_B64"] = enc(open(os.path.join(here, "build", "tiles.bin"), "rb").read())
        out, files = sys.argv[1], g["ngt_group_files"](sys.argv[2:])
        bios = os.environ.get("NGT_BIOS", "neogeo.zip")
        pk = g["jukebox_pack"]([(f, list(range(len(g["read_meta"](f)["tracks"])))) for f in files])
        rep, written = g["build_cart"](pk, "standard", bios, out, formats=("mame",))
        shutil.copy(bios, out)
        print(rep)
        print("MAME:  cd", out, "&& mame neogeo ngjb -hashpath hash -rompath .")
