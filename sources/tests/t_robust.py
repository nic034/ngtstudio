import runpy, random, os, struct, zipfile, io, glob, traceback
g = runpy.run_path(os.environ.get("NGT_STUDIO", "ngt_studio.py"), run_name="x")
R = random.Random(1)
ok = lambda c, m: print(("OK   " if c else "FAIL ") + m)
# 1. LZSS
bad = 0
cases = [b"", b"a", b"ab", b"abc", b"\xff" * 70000, bytes(range(256)) * 300, os.urandom(50000)]
for _ in range(200):
    n = R.randint(0, 5000)
    cases.append(bytes(R.choice(b"\x00\x01\x28\xc1\xc0\xff") for _ in range(n)))
for d in cases:
    if g["lzss_decompress"](g["lzss_compress"](d), len(d)) != d: bad += 1
ok(bad == 0, f"LZSS : {len(cases)} jeux de données, {bad} erreur(s) d'aller-retour")
d = os.urandom(20000); c = g["lzss_compress"](d)
ok(len(c) <= len(d) * 9 // 8 + 2, f"LZSS pire cas : {len(d)} -> {len(c)} octets (borne 9/8)")
# 2. modèle du driver Z80 : relit un flux et rend (tick, reg, val)
def z80_model(b):
    out, t, i = [], 0, 0
    while i < len(b):
        c = b[i]
        if c < 0xC0: out.append((t, c, b[i + 1])); i += 2
        elif c == 0xC0: out.append((t, 0x100 | b[i + 1], b[i + 2])); i += 3
        elif c == 0xC1: t += b[i + 1]; i += 2
        elif c == 0xC2: t += b[i + 1] | b[i + 2] << 8; i += 3
        elif c == 0xC3: out.append((t, "END", 0)); i += 1
        else: raise ValueError("opcode %02x" % c)
    return out, t
def check_track(regs, meta, label):
    intro, loop = g["z80_blocks"](regs, meta)
    a, ta = z80_model(intro)
    errs = []
    if loop is not None:
        if len(loop) == 0: errs.append("bloc de boucle vide")
        b, tb = z80_model(loop)
        if tb <= 0: errs.append("boucle de durée nulle (le 68000 tournerait sans fin)")
    else:
        if not a or a[-1][1] != "END": errs.append("pas de C3 final")
    if any(r in (0x24, 0x25, 0x26) for _, r, _ in a): errs.append("écriture timer non filtrée")
    ok(not errs, f"z80_blocks {label} : " + (", ".join(errs) or f"intro {len(intro)} o" + ("" if loop is None else f", boucle {len(loop)} o")))
k0 = 1000
base = dict(k0=k0, rate=55944, length_samples=200000, loop_start=None, loop_end=None)
regs = [(500, 0x24, 1), (600, 0x28, 0xF1)] + [(k0 + i * 997, 0x28, 0xF1) for i in range(150)] + [(k0 + 3_000_000, 0x28, 0)]
check_track(regs, dict(base, length_samples=3_100_000), "attente > 65535 ticks")
check_track(regs, dict(base, loop_start=k0 + 5000, loop_end=k0 + 5010), "boucle de 10 échantillons")
check_track(regs, dict(base, loop_start=k0 + 5000, loop_end=k0 + 5000), "boucle de longueur 0")
check_track([(500, 0x28, 0xF1)], dict(base, loop_start=k0, loop_end=k0 + 100000), "boucle sans aucune écriture")
check_track([], dict(base), "piste vide")
# 3. vraies pistes : le modèle relit exactement les écritures attendues
f = "./testdata/en_out/aof2/Art of Fighting 2.ngt"; data = open(f, "rb").read(); h = g["read_header"](data)
mism = 0
for i in range(len(h["tracks"])):
    m, regs, _ = g["unpack"](data, i, False)
    regs = g["_strip_nop"](regs)
    intro, loop = g["z80_blocks"](regs, m)
    a, _ = z80_model(intro); exp = [(r, v) for t, r, v in regs if r not in (0x24, 0x25, 0x26)]
    got = [(r, v) for _, r, v in a if r != "END"] + ([(r, v) for _, r, v in z80_model(loop)[0]] if loop else [])
    if loop is None and got != exp: mism += 1
    if loop is not None and got != [x for x in exp if True][:len(got)]: mism += 1
ok(mism == 0, f"AoF2 : écritures relues par le modèle Z80 = écritures d'origine ({len(h['tracks'])} pistes, {mism} écart)")
# 4. paquets / construction : cas dégénérés
for label, fn in [("sélection vide", lambda: g["build_cart"](g["jukebox_pack"]([]), "standard", "./testdata/neogeo.zip", "/tmp/claude-0/x_empty")),
                  ("BIOS absent", lambda: g["build_cart"](g["jukebox_pack"]([(f, [0])]), "standard", "/nonexistent.zip", "/tmp/claude-0/x_b")),
                  ("BIOS sans sfix", lambda: (lambda p: (zipfile.ZipFile(p, "w").writestr("x.bin", b"0" * 100), g["build_cart"](g["jukebox_pack"]([(f, [0])]), "standard", p, "/tmp/claude-0/x_c")))("/tmp/claude-0/fakebios.zip"))]:
    try:
        fn(); ok(False, f"{label} : accepté sans erreur")
    except Exception as e:
        ok(True, f"{label} : refusé proprement ({type(e).__name__}: {str(e)[:70]})")
# 5. fichiers abîmés
for label, mut in [("tronqué", lambda d: d[:len(d) // 2]), ("octet modifié", lambda d: d[:5000] + bytes([d[5000] ^ 1]) + d[5001:]),
                   ("vide", lambda d: b""), ("autre format", lambda d: b"RIFF" + d[4:200])]:
    p = "/tmp/claude-0/bad.ngt"; open(p, "wb").write(mut(data))
    try:
        r = g["check"](g["ngt_data"](p)); ok(not r[0], f"fichier {label} : check -> {r}")
    except Exception as e:
        ok(True, f"fichier {label} : exception propre ({type(e).__name__}: {str(e)[:60]})")
    try:
        g["jukebox_pack"]([(p, [0])]); ok(False, f"fichier {label} accepté par le jukebox")
    except Exception as e:
        ok(True, f"fichier {label} refusé par le jukebox ({str(e)[:50]})")
