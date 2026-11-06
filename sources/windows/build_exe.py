"""Builds the Windows release folder dist/NGT_Studio (NGT_Studio.exe + _internal + licences), as distributed.

Run on Windows 64-bit with Python 3.12 (python.org installer, tkinter included), from the sources folder:
    python windows\\build_exe.py
The official 2.5.21 build used exactly the versions pinned below (numpy 1.26: it also runs under Wine,
which is how the release was built and tested).
"""
import glob, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PINS = ["pyinstaller==6.22.3", "numpy==1.26.4", "sounddevice==0.5.6", "pillow==13.0.0", "soundfile==0.14.0"]


def run(*cmd):
    print(">", " ".join(cmd), flush=True)
    subprocess.check_call(cmd, cwd=ROOT)


run(sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *PINS)
run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed", "--name", "NGT_Studio",
    "--icon", os.path.join(HERE, "ngt.ico"), "--version-file", os.path.join(HERE, "version.txt"),
    *[a for m in ("scipy", "matplotlib", "IPython", "pytest", "setuptools", "pkg_resources", "numpy.array_api")
      for a in ("--exclude-module", m)],
    "ngt_studio.py")

dist = os.path.join(ROOT, "dist", "NGT_Studio")
# PortAudio: keep only the 64-bit DLL without ASIO (the ASIO SDK has its own licence terms)
for f in glob.glob(os.path.join(dist, "_internal", "_sounddevice_data", "portaudio-binaries", "*")):
    if os.path.basename(f) not in ("libportaudio64bit.dll", "README.md"):
        os.remove(f)

# licences of everything shipped in the folder
lic = os.path.join(dist, "licenses")
os.makedirs(lic, exist_ok=True)
base = sys.base_prefix
shutil.copy(os.path.join(base, "LICENSE.txt"), os.path.join(lic, "Python_LICENSE.txt"))
tk = glob.glob(os.path.join(base, "tcl", "tk8*", "license.terms"))
if tk:
    shutil.copy(tk[0], os.path.join(lic, "Tk_license.terms"))
site = next(p for p in sys.path if p.endswith("site-packages"))
for pkg in ("numpy", "pillow", "sounddevice", "soundfile", "cffi", "pycparser", "pyinstaller"):
    for di in glob.glob(os.path.join(site, pkg + "-*.dist-info")):
        for f in glob.glob(os.path.join(di, "LICENSE*")) + glob.glob(os.path.join(di, "COPYING*")) + \
                glob.glob(os.path.join(di, "licenses", "*")):
            if os.path.isfile(f):
                shutil.copy(f, os.path.join(lic, pkg + "_" + os.path.basename(f)))
sf = os.path.join(site, "_soundfile_data", "COPYING")
if os.path.isfile(sf):
    shutil.copy(sf, os.path.join(lic, "libsndfile_COPYING_LGPL.txt"))

shutil.copy(os.path.join(ROOT, "LICENSE"), os.path.join(dist, "LICENSE.txt"))
shutil.copy(os.path.join(HERE, "README_WINDOWS.txt"), dist)
shutil.copy(os.path.join(HERE, "THIRD_PARTY_NOTICES_WINDOWS.txt"), os.path.join(dist, "THIRD_PARTY_NOTICES.txt"))
shutil.copy(os.path.join(ROOT, "CHANGES.txt"), dist)                                 # changelog court (version par version)
print("\nDone:", dist, "- zip this folder to distribute it.")
