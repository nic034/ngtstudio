"""Integrate the 4 "Down + Start while Toasty is on screen" sounds into ngt_studio.py (JB_COMBO_SND_B85 / JB_COMBO_SND_USED),
already converted for the Neo Geo YM2610 ADPCM-A (mono, 18518.5 Hz, silences trimmed, peak -1 dBFS, 256-byte aligned),
exactly like tools/pack_toasty_snd.py does for the Toasty shout.

  python tools/pack_combo_snd.py a.mp3 b.mp3 c.mp3 d.mp3 [path/to/ngt_studio.py]       (1 to 4 files, in this order)

Source: 4 Mortal Kombat 3 sounds (mk3-09440, mk3-09160, mk3-09150, mk3-09155) supplied by Nicolas.  NOTE: (c) Midway /
Warner Bros., NOT under the MIT License - embedded at the project author's decision (see NOTICE.md).
Anything that is not a PCM WAV is converted first with ffmpeg (must be in the PATH).  Deterministic.
"""
import base64, importlib.util, lzma, os, re, subprocess, sys, tempfile

here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
files = [a for a in sys.argv[1:] if not a.endswith(".py")]
studio = os.path.abspath(next((a for a in sys.argv[1:] if a.endswith(".py")), os.path.join(here, "..", "ngt_studio.py")))
if not 1 <= len(files) <= 4:
    sys.exit(__doc__)
spec = importlib.util.spec_from_file_location("ngt_studio_mod", studio)
ns = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ns)
blobs, useds, infos = [], [], []
with tempfile.TemporaryDirectory() as td:
    for k, src in enumerate(files):
        wav = src
        if not src.lower().endswith(".wav"):
            wav = os.path.join(td, f"in{k}.wav")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-c:a", "pcm_s16le", wav], check=True)
        adp, used, info = ns.jb_toasty_sound(wav)
        b = base64.b85encode(lzma.compress(adp, preset=9 | lzma.PRESET_EXTREME)).decode()
        blobs.append("\n".join(b[i:i + 100] for i in range(0, len(b), 100)))
        useds.append(used)
        infos.append(f"{os.path.basename(src)}: {info}")
text = "# COMBO-BEGIN\nJB_COMBO_SND_USED = %r\nJB_COMBO_SND_B85 = (\n%s)\n# COMBO-END" % (
    useds, "".join('"""\n' + b + '\n""",\n' for b in blobs))
s = open(studio, encoding="utf-8").read()
s, n = re.subn(r"# COMBO-BEGIN\n.*?# COMBO-END", lambda m: text, s, flags=re.S)
if n != 1:
    sys.exit("COMBO markers not found in " + studio)
open(studio, "w", encoding="utf-8").write(s)
print("\n".join(infos))
print(f"{sum(len(b) for b in blobs)} characters written into {studio}")
