# NGT Studio

**Neo Geo music: extract it, listen to it, build a jukebox cartridge.**

NGT Studio is a Windows / Linux / Python utility (GUI + command line) that extracts the music of Neo Geo games from
**your own MAME romsets** (`.zip`). A built-in player emulates the original sound hardware (Z80 + YM2610) and plays
the music with visualisations. Albums are saved as small `.ngt` files that contain only numeric data for the YM2610 / Z80
(indexes, streams, samples): no audio recording, no game code.

It can also build, on the fly, a **playable jukebox ROM** for MAME, Darksoft Multi and NeoSD Pro cartridges, so you can
carry your favourite music on a real Neo Geo.

> ## ⚠️ You need your own files
>
> - **Game romsets**: not included, they remain the property of their owners.
> - **`neogeo.zip` (Neo Geo BIOS)**: not included and never will be (SNK's copyrighted BIOS). It is **required to build a
>   jukebox cartridge** (the build reads the cartridge security block and the system font from it) and to test it in MAME.
>   Extracting and listening do **not** need it.
> - A jukebox ROM you build contains these two small BIOS items: **share the tool, not the built ROMs.**

## Features

- **Extract**: finds the music in a romset, detects loops and duplicates, cuts trailing silence, keeps short looping tracks.
- **Player**: plays albums with an emulated YM2610, VU meters, keyboard and piano roll, game screenshots.
- **Cartridge**: builds a jukebox ROM (MAME set `ngjb.zip`, Darksoft Multi folder, NeoSD `.neo`) from several albums, with a capacity check.
- **Jukebox ROM**: pad controls (A play/pause, B stop, C/D previous/next, SELECT AUTO / LOOP / RAND), full-screen VU meters,
  Amiga-style screen saver after 5 minutes. Works on MVS, AES, original BIOS and UniBIOS.

## Quick start

Requirements: Python 3.8 or later with tkinter (Linux: `python3-tk`). The other modules (`numpy`, optionally `sounddevice`,
`Pillow`, `soundfile`) are installed from PyPI on first launch.

```
python ngt_studio.py                                                     # GUI: Extract / Player / Cartridge
python ngt_studio.py --cli --src roms/aof2.zip --out albums              # extract from the command line
python ngt_studio.py --cart albums/aof2.ngt albums/samsho3.ngt --out jukebox   # build a jukebox cartridge
python ngt_studio.py --help
```

Test a built jukebox in MAME (put `neogeo.zip` in the output folder):
`mame neogeo ngjb -hashpath hash -rompath .`

The `hash/neogeo.xml` produced by the build must be the one MAME reads, otherwise MAME shows
`P2 00 = FIRST BANK MISSING`. Use `-hashpath hash` from the output folder.

**Windows executable**: it is not stored in this repository. To build it yourself on Windows with Python 3.12, run
`sources\windows\build_exe.bat`. A self-built executable is not code-signed, so SmartScreen may warn.

Full documentation (options, formats, controls, screen saver, rebuilding the ROM and the engine): [`sources/README.md`](sources/README.md).

## Repository layout

| Path | Content |
|---|---|
| `ngt_studio.py` | The whole application in one file (same file as `sources/ngt_studio.py`). The engine, the 68000 jukebox program, the Z80 driver and the tiles are embedded in it. |
| `sources/` | Complete sources: C++ engine (`m1render/`), jukebox ROM (`jukebox_rom/`), tests, Windows build files, changelogs, licences. |
| `LICENSE` · `NOTICE.md` · `LEGAL_NOTICE.md` · `sources/THIRD_PARTY_NOTICES.md` | MIT licence · what it does not cover · legal notice · third-party licences. |

## Status

- The jukebox cartridge was tested **in MAME** (7 BIOS: MVS and AES, original and UniBIOS) and boots and plays on a
  Darksoft Multi-AES (UniBIOS 4.0). It has **not** been verified on every real hardware / flash cartridge: use it at your own risk.
- Latest version: **2.5.25**. Version history: [`sources/CHANGELOG.txt`](sources/CHANGELOG.txt) (short version: [`sources/CHANGES.txt`](sources/CHANGES.txt)).

## License and legal

- Code: **MIT License**, © 2026 Nicolas (Nic034), see [`LICENSE`](LICENSE).
- **Not covered by the MIT License**: the built-in screen-saver pictures (SNK artwork, author's artwork), and of course every
  game, BIOS and music. Details in [`NOTICE.md`](NOTICE.md).
- Third-party libraries (ymfm, z80, and the components of the Windows build): [`sources/THIRD_PARTY_NOTICES.md`](sources/THIRD_PARTY_NOTICES.md).
- Legal notice (publisher, host, trademarks, network access, privacy, liability): [`LEGAL_NOTICE.md`](LEGAL_NOTICE.md).
- NGT Studio is an independent fan project, **not affiliated with, endorsed by or sponsored by SNK**, MAME, Darksoft, NeoSD or any game publisher.
  Neo Geo and SNK are trademarks of their owner.
