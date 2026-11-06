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

### Extract

- Reads a MAME romset (`.zip`) and finds the music, including games whose music uses FM, SSG or long ADPCM samples.
- Detects loops and removes duplicate tracks (by note sequence, not only by name).
- Cuts the trailing silence of tracks that do not loop; keeps short looping tracks by default.
- Asks what to do with short tracks (under 45 s): keep the looping ones, skip them, or keep everything. Command line: `--short`.
- Up to 99 tracks per game, so the jukebox can number them; the extra tracks are dropped first (SFX, jingles, short tracks).
- Handles early Neo Geo games, separate ADPCM-A / ADPCM-B ROMs, and merged MAME sets with clones.
- Exports each game as an `.ngt` file: small, numeric only (no audio is stored, no game code).
- Exports albums and stems: a whole game as a tagged FLAC or WAV album, or each track split per voice (`--album`, `--stems`).

### Player

- Plays `.ngt` albums with an emulated Z80 and YM2610 (FM, SSG and ADPCM), so the music is rendered from its own data.
- Live mixer: click a voice to mute it, right-click to solo it. The sound is re-rendered on the fly.
- Live piano keyboard and piano-roll waterfall, with ADPCM drum pads and a stereo stage.
- Per-voice oscilloscopes and a full-screen view with the spectrum and game screenshots.
- Album listening: endless loop, or N loops with a fade-out; "Next track at end" option.
- Game screenshots and title images from libretro thumbnails, shown as a slideshow (no API key needed).
- Remembers your window, last folder and options in `~/.ngt_studio.json`.

### Cartridge

- Builds a **playable jukebox ROM** from several albums, with a capacity check and a 5 % safety margin.
- Output formats: MAME set `ngjb.zip`, Darksoft Multi folder, and NeoSD `.neo`.
- Standard layout (P1 1 MB, P2 4 MB, V-ROM 16 MB) or an extended 8 MB P2 layout (homebrew only).
- Music streams are compressed (about 5 to 7 times smaller), decompressed by the 68000 program.
- Screen-saver pictures can be replaced with your own sheets (`--boxes`).

### Jukebox ROM (what runs on the Neo Geo)

- Pad controls: A play / pause, B stop, C / D previous / next, UP / DOWN track, LEFT / RIGHT game.
- SELECT cycles **AUTO** (chains every track of every album, endlessly), **LOOP** (repeats one track) and **RAND**
  (a random track of any album, never twice in a row). MVS has no SELECT, so it stays in AUTO.
- START opens a full-screen view with seven large VU meters and peak hold.
- Plays automatically from power-on.
- **Amiga-style screen saver** after 5 minutes without a press: a rainbow sine scroll that reacts to the music,
  a rippling isometric checkerboard, a spinning CD icon, drifting objects and a point sphere that bounces across the bottom of the screen.
  Any press wakes it up. The player animations stop while it is on and resume on wake-up.
- Works on MVS and AES, with the original BIOS and UniBIOS 4.0 (tested in MAME with several BIOS versions).
- Hardware limits are checked in MAME: sprites per line and the vertical blank.

## Changelog highlights

The full history is in [`sources/CHANGELOG.txt`](sources/CHANGELOG.txt). Recent versions:

- **2.5.25**: fixed the bouncing sphere overlapping the bottom text.
- **2.5.24**: the sphere bounces across the bottom of the screen while it spins.
- **2.5.22**: spinning CD icon in the screen saver.
- **2.5.19**: RAND mode; screen saver after 5 minutes; fixed ADPCM-A sample lengths (Puzzle De Pon).
- **2.5.20**: fixed random coloured dots on a real console (palettes written only during the vertical blank).

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
