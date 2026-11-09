"""Integrate the "toasty" sound into ngt_studio.py (constants JB_TOASTY_SND_B85 / JB_TOASTY_SND_USED), already
converted for the Neo Geo YM2610 ADPCM-A (mono, 18518.5 Hz, silences trimmed, peak -1 dBFS, 256-byte aligned).

  python tools/pack_toasty_snd.py clean_toasty.(wav|mp3) [path/to/ngt_studio.py]

Source: the clean file supplied by Nicolas (0.68 s).  NOTE: the sound is the Mortal Kombat 2 "Toasty!" shout,
(c) Midway / Warner Bros., NOT under the MIT License - embedded at the project author's decision (see NOTICE.md).
Anything that is not a PCM WAV is converted first with ffmpeg (must be in the PATH).
Deterministic: same file -> same characters.  Removal: empty the string and set JB_TOASTY_SND_USED = 0.
"""
import base64, importlib.util, lzma, os, re, subprocess, sys, tempfile

here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = next((a for a in sys.argv[1:] if not a.endswith(".py")), None)
studio = os.path.abspath(next((a for a in sys.argv[1:] if a.endswith(".py")), os.path.join(here, "..", "ngt_studio.py")))
if not src:
    sys.exit(__doc__)
spec = importlib.util.spec_from_file_location("ngt_studio_mod", studio)
ns = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ns)
with tempfile.TemporaryDirectory() as td:
    wav = src
    if not src.lower().endswith(".wav"):
        wav = os.path.join(td, "in.wav")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-c:a", "pcm_s16le", wav], check=True)
    adp, used, info = ns.jb_toasty_sound(wav)
b = base64.b85encode(lzma.compress(adp, preset=9 | lzma.PRESET_EXTREME)).decode()
b = "\n".join(b[i:i + 100] for i in range(0, len(b), 100))
s = open(studio, encoding="utf-8").read()
s, n = re.subn(r'(JB_TOASTY_SND_B85 = """\n)([0-9A-Za-z!#$%&()*+;<=>?@^_`{|}~\n-]*)(""")', lambda m: m.group(1) + b + "\n" + m.group(3), s)
s, n2 = re.subn(r"JB_TOASTY_SND_USED = \d+", f"JB_TOASTY_SND_USED = {used}", s)
if n != 1 or n2 != 1:
    sys.exit("JB_TOASTY_SND_* not found in " + studio)
open(studio, "w", encoding="utf-8").write(s)
print(f"{info} -> {len(b)} characters written into {studio}")
