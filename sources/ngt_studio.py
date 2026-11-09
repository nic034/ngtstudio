#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NGT Studio - extract and listen to the music of Neo Geo ROMs.  One file, one window.

  "Extract" tab : a ROM (.zip) or a folder of .zip files  ->  ONE .ngt file per game
                  (all tracks + a shared sample block, loops detected).
                  The music is obtained by emulating the Z80 and the YM2610 (built-in native engine).
  "Player" tab  : plays the .ngt files (replay identical to the emulation), track switching, automatic volume,
                  LED spectrum, voices, WAV export.
  "Cartridge" tab : builds a playable jukebox cartridge from .ngt files (MAME set, Darksoft folder, NeoSD .neo),
                  after a capacity check with a 5 % margin.

Dependencies (installed automatically on first launch): numpy; optional: sounddevice, Pillow, soundfile.
tkinter comes with Python (Linux: package python3-tk).
Command line: python ngt_studio.py --help        .ngt format: see the "FORMAT" section further down.

Copyright (c) 2026 Nicolas (Nic034).  MIT License, see LICENSE.  Third-party code: THIRD_PARTY_NOTICES.md.
SPDX-License-Identifier: MIT
"""
import argparse
import base64
import concurrent.futures as cf
import glob
import time
import hashlib
import json
import math
import os
import queue
import re
import atexit
import urllib.parse
import urllib.request
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import wave
import zipfile
import zlib


FROZEN = bool(getattr(sys, "frozen", False))      # exécutable Windows (PyInstaller) : modules déjà embarqués
_NOWIN = {"creationflags": 0x08000000} if os.name == "nt" else {}   # CREATE_NO_WINDOW : pas de console qui clignote

if FROZEN and os.name == "nt" and len(sys.argv) > 1 and sys.stdout is None:
    # exe sans console lancé avec des options depuis cmd/PowerShell : on écrit dans la console appelante
    try:
        import ctypes
        if ctypes.windll.kernel32.AttachConsole(-1):
            sys.stdout = sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace")
    except Exception:
        pass

for _s in (sys.stdout, sys.stderr):                 # console Windows en cp1252 : un caractère spécial ne doit rien planter
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass


def ensure_modules(required=("numpy",), optional=("sounddevice", "PIL", "soundfile")):
    """Installe automatiquement (pip) les modules Python manquants.  Les facultatifs ne bloquent rien s'ils échouent."""
    if FROZEN:
        return
    import importlib.util
    for group, hard in ((required, True), (optional, False)):
        missing = [m for m in group if importlib.util.find_spec(m) is None]
        if not missing:
            continue
        print("Installing missing modules:", ", ".join(missing), flush=True)
        for extra in ([], ["--break-system-packages"], ["--user"]):
            r = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", *extra,
                                *[{"PIL": "pillow"}.get(m, m) for m in missing]])
            if r.returncode == 0:
                break
        importlib.invalidate_caches()
        still = [m for m in missing if importlib.util.find_spec(m) is None]
        if still and hard:
            sys.exit("Cannot install: %s (try: %s -m pip install %s)"
                     % (", ".join(still), sys.executable, " ".join(still)))
        if still:
            print("Optional module unavailable:", ", ".join(still), flush=True)


ensure_modules()
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(sys.executable if FROZEN else __file__))   # exe : dossier de l'exe

# ---- Version (MAJOR.MINOR.PATCH): bump on every delivery and add a line to CHANGELOG.
VERSION = "2.5.28"
BUILD_DATE = "2026-11-09"
CHANGELOG = """\
2.5.28 2026-11-09  Jukebox ROM:
                   NEW  Toasty: THREE portraits instead of one.  Each screen saver draws one at random (never the
                        same one twice in a row) among the built-in portraits: Aurelien with his mug and two more
                        (68000: toasty_pick, one toastydata block per character, V_TOSP / V_TOSC).  Same animation,
                        same place (bottom right, in front), same rule: once per screen saver, at the next track.
                        Pictures: tools/pack_toasty.py (several PNGs, fitted to 112 x 96 px, noise specks removed),
                        art/toasty_frame.png, toasty_frame_2.png, toasty_frame_3.png; 89 C-ROM tiles in all
                   NEW  the Toasty sound is now BUILT IN (JB_TOASTY_SND_B85, tools/pack_toasty_snd.py: the clean file
                        supplied by Nicolas, 0.61 s, ADPCM-A, 5.9 KB, lzma + base85) and played by default with the
                        Toasty.  It is the Mortal Kombat II "Toasty!" shout, (c) Midway / Warner Bros., NOT covered
                        by the MIT License: embedded at the project author's decision (NOTICE.md, LICENSE).  Cartridge
                        tab: "Toasty sound" check box (untick = no sound) and optional file replacing it;
                        CLI: --no-toasty-sound, --toasty-sound FILE.  To remove it from the program: empty
                        JB_TOASTY_SND_B85 and set JB_TOASTY_SND_USED = 0
                   Tests: mame_tests/toasty_chars.lua (12 screen savers in a row: 3 characters drawn, never twice in
                        a row, 12 shouts for 12 apparitions); toasty_wake.lua (woken up: no portrait nor shout when the
                        track then changes, re-armed by the next screen saver); toasty_sfx.lua (built-in sound,
                        music voices untouched)
2.5.27 2026-11-09  Jukebox ROM:
                   CHANGED "Aurelien - Toasty": once per screen saver, at the first track change after the screen
                        saver starts (was: once per power-on, at the 3rd album or after 20 minutes, then a 10 s
                        wait).  Each new screen saver arms it again.  LOOP mode: the track never changes, no Toasty
                   NEW  Toasty sound (Cartridge tab "Toasty sound (your WAV)", --toasty-sound FILE): played with the
                        Toasty, over the music.  Your own file, never stored in NGT Studio: silences trimmed (36 dB
                        under the peak), mono, peak at -1 dBFS, resampled to 18518.5 Hz, ADPCM-A encoded, placed after
                        the albums' V-ROM.  The Z80 driver borrows the ADPCM-A voice the albums use least, for the
                        length of the sound only (FF 07): the music's writes to that voice are held and restored after,
                        all other voices untouched, end of track / pause spare the shout; if the music never set the
                        ADPCM-A master volume (0 at power-on = silent), the shout sets it and puts it back
                   NEW  custom screen-saver wavy text (Cartridge tab, --saver-text, 256 characters): capitals, digits
                        and punctuation (accents removed, the ROM font has no lower case); replaces both built-in texts
                   Measured in MAME, real BIOS (Europe/US/Japan MVS, AES Asia/Japan, UniBIOS 3.3): shout isolated
                        (same cartridge without the sound, deterministic emulation) vs the ADPCM-A decoder: correlation
                        0.962; music identical before the shout, shifted by 42 us for ~2 s after (inaudible); 6-voice
                        ADPCM-A album: no music trigger on the borrowed voice during the shout, the 5 others play;
                        6 min of Toasty + shout repeating: 89 sprites per line at most (limit 96)
                   Rights: "Aurelien - Toasty" picture (c) Aurelien / Bouz, all rights reserved (NOTICE.md, LICENSE,
                        jukebox_rom/art/RIGHTS.txt, README of each cartridge)
                   Tests: mame_tests/toasty_sfx.lua (replaces toasty_cases.lua); full_test.lua is out of date (same
                        9 MVS / 6 AES failures on the original 2.5.25 with the real BIOS: not regressions)
2.5.26 2026-11-07  Jukebox ROM:
                   NEW  build option "Aurelien - Toasty" (Cartridge tab check box, --toasty, off by default): a
                        portrait of Aurelien drinking from his mug pops up from the bottom-right corner of the screen
                        saver, in front of everything (text, objects, sphere, small text), and goes back down, like
                        the Toasty of Mortal Kombat II.  ONCE per power-on, at the first of: the first track of the
                        3rd album of the list starts (coming from another album), or 20 minutes of playback (pause
                        and stop not counted).  Only while the screen saver is on: if it is not on at that moment,
                        it comes 10 s after the screen saver starts.  A press during the animation hides it for good
                        (and is not passed to the player).  ~2.5 s: rise 0.5 s, hold 1.6 s, down 0.4 s
                   One picture (frame 8 of the supplied sheet; the 16 frames are the same pose moved up and down,
                        with small random drawing differences between frames) moved by the jukebox itself: 112 x 94
                        px, 7 sprite columns trimmed to their content (3 sprites on the top lines), 4 palettes of
                        15 colours chosen per tile (palettes 33-36), 30 tiles at 0x3F00, sprites 326-333
                   Measured in MAME (6 min of screen saver with the Toasty repeating, text and sphere scenes, objects
                        at their densest): 89 sprites per line at most (limit 96), its top never above line 130;
                        2 lines of the vertical blank, done first, before the rest of the screen saver.  Without the
                        option the ROM differs only by a 360-byte block of zeros and no tiles
                   Tools: jukebox_rom/tools/pack_toasty.py (picture -> JB_TOASTY_B85), tools/embed.py (assembles
                        and writes the binaries and offsets into ngt_studio.py, checked by reading them back)
2.5.25 2026-10-31  Jukebox ROM source (core.S):
                   FIXED the bouncing point sphere (new in 2.5.24): at the bottom of its bounce the lowest
                        projected point could reach up to 75 px below its centre (measured over all 96 points and
                        every possible rotation); the floor was set at 184, so the ball actually overlapped and
                        partly went under the small scrolling text at the bottom of the screen (SM_YB = 211) on
                        every bounce.  The floor is now 134: the lowest point reaches 209, 2 px clear of the text,
                        never under it, and the bounce uses more of the screen height (looks more centred).  Only
                        the floor changed; bounce height/speed are the same, so on the tallest bounces the sphere
                        now also grazes a little more off the top edge than before (clipped, not a bug, same kind
                        of hardware clipping that already happened at the bottom before this fix).

2.5.24 2026-10-30  Jukebox ROM source (core.S):
                   Screen saver, point sphere: it now BOUNCES like a ball across the bottom of the screen,
                        left to right, at varying heights, while still spinning on itself exactly as before
                        (sphere_step untouched). New sphere_bounce routine (called once per frame by
                        sphere_draw, right after sphere_step): gravity-based fixed-point simulation (<<6),
                        slow lateral drift bouncing off the screen edges instead of exiting them (always
                        visible for the whole scene), slow gravity for a deliberate, non-twitchy fall, a new
                        random upward speed drawn on every ground contact (capped so the ball never exits
                        the top of the screen by much). No new sprite, no new table: only the sphere's
                        projection centre moves, same 96 points, same rendering. Also SPED UP the handful of
                        per-frame multiplications by a fixed constant (screen-saver scrolling-text wrap, CD
                        icon fade, vumeter colour thresholds): replaced with shifts and additions, exact for
                        every value these ever take; everything else deliberately left alone (constant
                        divisions with a hand-tuned feel, or by a runtime value: no safe, exact replacement).
                        No behaviour change on the untouched routines (confirmed byte-identical where
                        unaffected); full MAME check frame by frame (screen saver text/wave/CD icon,
                        vumeters, and a full natural run of the text<->sphere transition with the new bounce).
                        Sprite budget unchanged: 325/381 used, margin 56.

2.5.23 2026-10-28  Jukebox ROM source (core.S/ui3.S/draw3.S):
                   CLEANED a handful of leftovers found unused by a full cross-reference of every symbol: 6 unused
                        .equ constants, a vumeter colour table superseded by the existing per-palette table, and an
                        unused " BANK(S) OK" string.  No behaviour change (confirmed in MAME: boot, screen saver,
                        checkerboard, floating objects, spinning CD all unaffected); 22 bytes smaller
2.5.22 2026-10-28  Jukebox screen saver:
                   NEW  spinning CD icon, fixed in the top-right corner: 16-frame rotation (built in as a 5th
                        sheet, your own artwork), continuous fade in and out.  Drawn above the checkerboard and
                        the floating objects but below the scrolling text, so it is never covered and never
                        covers the text.  The floating-object system cannot pick this sheet at random: it stays
                        fixed in its corner.
2.5.21 2026-10-26  Jukebox screen saver:
                   REMOVED the two chip objects (64-pin and 28-pin): they did not look good.  Four built-in sheets
                        remain: game box, Neo Geo console, Delta Island logo and triangle (four boxes for one object
                        of the three other sheets, which take turns).  jukebox_boxes3.png and jukebox_boxes4.png next
                        to the program now replace the logo and the triangle; jukebox_boxes5.png and 6 add sheets
2.5.20 2026-10-26  Jukebox ROM:
                   FIXED small coloured dots / dashes appearing at random on a real console (not in MAME): the
                        palettes were written during the active display (the rainbow title every 3 frames, and every
                        palette change when the screen saver starts or stops).  On the Neo Geo the CPU has priority
                        over the video, so each colour written then shows on a pixel.  All these writes now happen in
                        the vertical blank: the title colours are prepared in a buffer, the palette sets are computed
                        by the main loop and only copied by the interrupt (11 of the 40 lines at most).  The colours
                        themselves are unchanged (palette RAM identical in MAME)
                   FIXED a press during the two frames the screen saver takes to start (palettes being set) acted
                        as a normal command (stop, next...) instead of only waking it up
                   FIXED MVS: a coin inserted during those two frames could leave the dimmed screen-saver colours
                        on the player screen
                   Cartridge:
                   CHANGED a jukebox_boxesN.png next to the program now replaces only the built-in sheet N (it
                        replaced all of them: with the two sheets of 2.5.16 still there, the chips and logos were lost)
                   FIXED a sheet path containing "@" (Windows folder "name@pc") was cut: only a final "@number"
                        (enlargement) is read
                   Tested in MAME: MVS + AES, UniBIOS 4.0 and SNK BIOS (euro, us, japan, asia).
2.5.19 2026-10-26  Jukebox ROM:
                   NEW  RAND mode: SELECT now cycles AUTO -> LOOP -> RAND; RAND plays a random track of any album
                        (never the same twice in a row) and never stops.  AUTO already chained every album endlessly
                        (after the last track of the last album: the first album; checked in MAME)
                   CHANGED screen saver after 5 minutes without a press (was 10)
                   IMPROVED while the screen saver is on, the player screen animations are stopped (VU meters and
                        peaks, header notes, rainbow title, marquee); they resume on wake-up.  Only the voice levels
                        keep running (they drive the sine scroll)
                   NEW  four more built-in screen-saver objects: a 64-pin chip, a 28-pin chip, the Delta Island logo
                        and the Delta Island triangle (both enlarged ~25 %).  Four boxes for one object of the other
                        sheets, which take turns; up to 6 sheets (jukebox_boxes.png ... jukebox_boxes6.png, --boxes
                        a,b,...; "sheet.png@1.3" enlarges a sheet, capped at 46 px high).  Measured in MAME: 94 sprites
                        per line at most, 95 in the worst case (two logos on one line; limit 96), 35 of the 40 lines
                        of the vertical blank (unchanged: the rotation base no longer divides per sheet and frame)
                   Extraction:
                   IMPROVED a track that does not loop now ends 1 s after its last sound: the trailing silence
                        (up to ~3 s, the time the engine waits before deciding that a track has ended) is cut
                   CHANGED short tracks (under 45 s): by default the ones that LOOP are kept (short game music loops)
                        and the others skipped; it is also the choice without an answer or when not interactive (it
                        skipped them all).  Puzzle De Pon: 3 -> 10 tracks; Windjammers: 6 -> 8 tracks
                   FIXED ADPCM-A sample length: the chip stops when the low 20 bits of the address reach (end + 1);
                        NGT Studio read the end register literally.  Puzzle De Pon (driver that leaves the end at
                        0xFFFF): 16.8 MB of samples instead of 54 KB, too big for any jukebox cartridge (now 0.9 MB in
                        all); 2020 Super Baseball: one track slightly wrong (now identical to the original render)
                   Tested in MAME: MVS + AES, UniBIOS 4.0 and SNK BIOS (euro, us, japan, asia).
2.5.18 2026-10-23  Jukebox ROM, screen saver:
                   IMPROVED the checkerboard floats much more and follows the music: 3 px at rest up to 10 px when the
                        music is loud, and faster too (one wave in 8.5 s when calm, about 1.5 s when very loud); two
                        long crossing waves instead of a short one, so the 16-px columns stay close to each other.
                        Measured in MAME: screen always covered, 93 sprites per line at most (unchanged), 35 of the
                        40 lines of the vertical blank (was 32)
                   Tested in MAME: MVS + AES, UniBIOS 4.0 and SNK BIOS (euro, us, japan, asia).
2.5.17 2026-10-23  Jukebox cartridge:
                   NEW  the screen-saver objects (a game box and a Neo Geo console) are built in: no PNG file needed.
                        Your own jukebox_boxes.png / jukebox_boxes2.png next to the program still replace them,
                        --boxes "" still disables them.  The built-in pictures are SNK artwork, not covered by the MIT
                        License (see LICENSE).  The build result now says which objects were used
                   FIXED building the MAME format alone (without Darksoft / NeoSD) into a folder that does not exist
                        yet failed (bug added in 2.5.16)
                   Tested in MAME: MVS + AES, UniBIOS 4.0 and SNK BIOS (euro, us, japan, asia).
2.5.16 2026-10-23  Jukebox cartridge, MAME output:
                   CHANGED the MAME set is now a zip, ngjb.zip, with the ROM files inside (like any MAME set), instead
                        of a ngjb folder; same files, same contents.  Files of an older ngjb folder in the output
                        folder are removed (MAME would read the folder first).  Same command:
                        mame neogeo ngjb -hashpath hash -rompath .
                   Tested in MAME: MVS + AES, UniBIOS 4.0 and SNK BIOS (euro, us, japan, asia).
2.5.15 2026-10-23  Jukebox ROM, screen saver objects:
                   IMPROVED more sprite headroom: a console (wide object, 4 sprites per line) never shares its lines
                        with another object (nothing starts less than 63 frames before or after it), and the density
                        is 2 to 8 objects (was 2 to 10).  Measured in MAME: at most 93 sprites on a line (limit 96,
                        was 95), 32 of the 40 lines of the vertical blank (was 34)
                        A console that cannot start yet is waited for, never replaced: still exactly one console
                        for four boxes (measured 144 / 36 in 5 min)
                   Tested in MAME: MVS + AES, UniBIOS 4.0 and SNK BIOS (euro, us, japan, asia).
2.5.14 2026-10-23  Jukebox ROM:
                   NEW  Amiga-style screen saver (after 10 minutes without a press, was 15): a big outlined rainbow sine scroll ("NEO GEO JUKEBOX - ENJOY FINE MUSIC !"
                        while music plays, the wave swells with the music; "... THANKS FOR USING THIS SOFTWARE" when
                        stopped or paused; credits line) over a very faint isometric checkerboard that scrolls and
                        ripples like water, with album / track / elapsed / remaining time scrolling in small yellow
                        letters at the top and bottom.  Animated by the VBlank interrupt; the wave moves in half steps
                        and its height changes gradually (no jumps).  The C ROMs
                        now hold these graphics (Darksoft crom0 word-interleaved, NeoSD byte-interleaved)
                   NEW  the sine scroll follows the music much more: its height follows the total energy of the 7
                        voices (28 to 64 px; it used to stay near the maximum), the wave speeds up when the music is
                        loud, and the rainbow flashes on each drum hit (ADPCM-A).  Letters enlarged x5 (40 px)
                   NEW  rotating objects drift diagonally between the checkerboard and the text, in a continuous
                        stream (2 to 10 on screen, random starting points, 4 directions), with a light twinkling
                        outline.  The pictures are YOUR sheets, never shipped with the tool: jukebox_boxes.png and
                        jukebox_boxes2.png next to the program (or --boxes a.png,b.png); frames on a magenta
                        background, tall (box) or wide (console) detected automatically; one object of the second
                        sheet for four of the first.  Without sheets: no objects
                   IMPROVED screen saver within the hardware limits, measured in MAME: at most 95 sprites on a line
                        (limit 96) and 34 of the 40 lines of the vertical blank (the full text rewrite moved out of
                        the interrupt, checkerboard ripple cached, bottom yellow line offset by 4 px)
                   NEW  both header notes (yellow and white) bounce 2 pixels in counter-phase while music plays
                   FIXED the UniBIOS splash was altered on AES (SNK logo, double-height letters): the jukebox tiles
                        overwrote those BIOS tiles in the cartridge S ROM (since 2.5.2); they now sit in an unused area
                   FIXED waking the screen saver with UP/DOWN still held could move the cursor (auto-repeat)
                   FIXED the screen-saver delay counted main-loop passes, not frames: it could last a little longer
                   FIXED building a cartridge with more than 16 MB of samples crashed ("bytes must be in range");
                        it is now refused cleanly by the capacity check (V-ROM TOO BIG)
                   IMPROVED the 68000 relay to the Z80 no longer delays the display when the Z80 is well ahead
                   IMPROVED the capacity check counts the real size of the 68000 program (19 KB) instead of a fixed
                        64 KB reserve: about 45 KB more P-ROM for music, estimate within 150 bytes of the real image
                   IMPROVED ngt_studio.py is 13 % lighter: embedded engines compressed with xz, Linux engine without
                        debug symbols (output identical byte for byte)
                   IMPROVED scipy is no longer used: the 55.9 -> 48 kHz resampling is done with numpy (same filter,
                        same values within 1/100 of a 16-bit step, about 4x faster); the Windows version loses ~100 MB
                   FIXED --wav with --seconds/--start past the end of a track that does not loop crashed after
                        writing an empty WAV; it now says so and writes nothing
                   FIXED the jukebox shows game and track numbers on 2 digits: a game with more than 99 tracks (possible
                        with "keep everything") gave wrong characters; the build is now refused with the game named
                   FIXED --cart with the same file given twice packed it twice (the interface already ignored it; it
                        now also recognises the same file reached through another path)
                   NEW  extraction: at most 99 tracks per game (the jukebox numbers them on 2 digits).  Above that,
                        SFX, short tracks that do not loop, jingles, then short looping tracks are removed in this
                        order until it fits (logged); if 99 music tracks still do not suffice, the game is not
                        written and the result says why.  Below 99 tracks nothing changes (output identical)
                   FIXED jukebox: the rainbow of the title divided a 32-bit register whose upper half was not cleared:
                        depending on what was left in it, the colour rotation could freeze or jump
                   FIXED a .ngt whose track count is corrupted made the program try to allocate gigabytes (MemoryError)
                        instead of refusing the file (found by fuzzing 1900 corrupted files)
                   FIXED command line: --track out of range, a missing file or output folder printed a Python traceback;
                        now a one-line error and exit code 2
                   Tested in MAME: MVS + AES, UniBIOS 4.0 and SNK BIOS (euro, us, japan, asia), 2-bank P2, 5 min
                   screen-saver endurance.
2.5.13 2026-10-21  Jukebox ROM:
                   - the yellow note at the top left bounces (1 pixel, ~1.85 beats per second) while the music plays;
                     it stands still when stopped or paused
                   - a white note after "NEO GEO JUKEBOX" (erased by the screen saver with the title)
                   Tested in MAME: MVS + AES, UniBIOS 4.0 and SNK BIOS (euro, us, asia).
2.5.12 2026-10-20  Review of the engine and of the jukebox code:
                   - Windows: the engine now handles any character in paths (Unicode).  A Windows account name with
                     letters outside the system code page (e.g. Cyrillic on a French Windows) made extraction and
                     playback fail completely
                   - engine: the V-ROM is no longer copied for every command: about 3x less memory per engine process
                     (16 MB V-ROM: 68 -> 20 MB, x the number of processes); output unchanged, byte for byte
                   - jukebox Z80 driver: "silence" reset the ADPCM-B voice with its START bit (0x80) instead of RESET
                     (0x01), restarting the last sample for an instant at each stop (inaudible in MAME)
2.5.11 2026-10-20  Fixes found by a full code review:
                   - extraction: an engine that hangs on one command no longer aborts the whole game (time-out caught)
                   - extraction: an engine error on a previous game is no longer reported for the next one
                   - engine output read with a tolerant decoder (Windows code page)
                   - Cartridge tab: "Build" is disabled as soon as the selection changes (no build of the previous one)
                   - command line: --cli without --src (or with a missing path) and --stems out of range give a clear
                     message; --cli without --out writes to ngt_output next to the program
                   - oscilloscope view: a voice that fails to render no longer blocks the others
2.5.10 2026-10-20  Fixes found by code review:
                   - merged MAME sets (clones in sub-folders of the zip): only the parent's M1 / V-ROM are used (the
                     clones' V-ROMs were appended and shifted every sample address)
                   - duplicate detection: two tracks with the same notes but clearly different lengths are kept
                     (Magician Lord: an 11.7 s jingle and a 23.5 s tune were merged)
                   - sample-based music: sample length capped at the end of the track (measure was too generous)
                   - neogeo.zip search: a remembered ROM folder that no longer exists is looked at as a folder
2.5.9  2026-10-20  Extraction:
                   - loop detection for music made of long ADPCM samples (Pulstar...), checked on the audio
                   - duplicates recognised by their note sequence (pitch, sample, SSG notes; the loop of a tune with a
                     sound effect on top counts as the same tune): Crossed Swords 75 -> 32 tracks
                   - separate ADPCM-B ROMs recognised by their content (CRC from the MAME list), whatever the file name
                   - temporary folders left by an interrupted extraction are cleaned up (they could fill the disk)
                   Code clean-up (unused variables / imports).
2.5.8  2026-10-19  Extraction: music played with long ADPCM samples instead of FM notes (Pulstar, Breakers Revenge
                   and other Aicom / Visco games) is recognised as music; it was classified as SFX and skipped.
                   Jukebox ROM: on MVS, inserting a coin no longer restarts the jukebox (the BIOS calls the game again
                   in "title" mode: playback now simply continues).  The ROM % shown top right is now
                   (P-ROM + V-ROM used) / (P-ROM + V-ROM of the chosen format, standard or extended); also shown in
                   the Cartridge tab.  Tested in MAME on MVS (euro, US, japan, UniBIOS 4.0) and AES (asia, japan,
                   UniBIOS 4.0) BIOSes: START, SELECT, coins, every button, screen saver, random presses.
2.5.7  2026-10-19  Jukebox ROM: fixed the crash ("ILLEGAL INSTRUCTION at 00000128") when START is pressed on an AES / with
                   UniBIOS: the assembler had shortened the first jump of the cartridge header, shifting the BIOS
                   callbacks (PLAYER_START, DEMO_END, COIN_SOUND); they are now fixed 6-byte jumps to a plain return.
                   Cartridge tab: old .ngt files show the full game title instead of the MAME short name.
2.5.6  2026-10-19  Cartridge tab: progress bar for the stream compression with the estimated time left; the stream
                   compression runs in the native engine (about 25x faster, byte-identical result; Python fallback);
                   a change of selection cancels the computation in progress; "Build" is disabled until it is done.
                   Command line --cart: same progress with time left.
2.5.5  2026-10-19  Jukebox ROM screen saver: after 15 minutes without touching the pad, every colour drops to 50 %
                   (background included), the fixed title is hidden and a rainbow "NEO GEO" bounces off the screen
                   edges (one cell every 8 frames); the player display is frozen meanwhile, the music keeps playing.
                   Any press (D-pad or button) wakes it up and does nothing else.
2.5.4  2026-10-19  Extraction: early games now work (Magician Lord and other first-generation sets): the Z80 sound banks
                   start mapped like on the hardware (the driver jumped into a banked area before setting it up), and
                   separate ADPCM-B ROMs (v1x = ADPCM-A, v2x = ADPCM-B) are supported, merged into one V-ROM.
                   Short tracks: under 45 s (one loop included, adjustable, 0 = off) they are skipped by default and a
                   question is asked during the extraction, telling how many of them loop (game music with a short
                   loop); answer once for the whole extraction; no answer within 30 s = skipped.
                   CLI: --min-len, --short ask|skip|loops|keep.
                   Jukebox ROM: the 7 small VU meters, the panel frame and AUTO/LOOP moved away from the right edge
                   (column 38 was hidden by the bezel of some TVs: B meter cut); peak markers fall faster and are not
                   drawn for a silent voice (they looked like stray white lines).
2.5.3  2026-10-17  Windows executable (NGT_Studio.exe, everything included, no Python needed): files are read and
                   written next to the exe, no console window flashing for the engine, command-line options print
                   into the calling console; a special character can no longer crash console output.
                   Jukebox ROM: neogeo.zip is looked for automatically next to the program (exe or script) and in the
                   folder of the last ROM opened in the Extract tab, and checked (security block + font);
                   if it is missing or unusable, the GUI explains where it looked and asks for it, the command line
                   asks for its path (or tells you to use --bios when not interactive).
2.5.2  2026-10-17  Jukebox ROM: back to the 2.5.0 colourful theme (rainbow title, coloured VU meters).
                   Public source release under the MIT License (engine, 68000 and Z80 jukebox sources, tools).
2.5.1  2026-10-17  Jukebox ROM: calmer colour theme (night blue + cyan, one amber accent, grey help; title shimmer
                   instead of rainbow; VU meters cyan -> light cyan -> amber; softened pad button colours).
2.5.0  2026-10-17  Jukebox ROM redesign: custom fix-layer tiles (icons, smooth pixel-accurate bars, Neo Geo pad buttons
                   in their real colours, frame); "now playing" panel with smooth progress bar; yellow selection bar;
                   smooth VU meters with green-yellow-red zones and peak hold; rainbow wave title; scrolling
                   NOW PLAYING marquee; CRT-safe layout.
2.4.0  2026-10-17  Jukebox ROM: English interface; plays automatically from power-on and chains every track
                   (looping tracks: intro + 2 loops, then the next one; SELECT toggles AUTO / LOOP1);
                   START switches to a full-screen view with 7 giant VU meters and peak hold, every pad function
                   still working; play time follows the real frame
                   rate (VBlank); robustness: button presses are never lost, a silent Z80 no longer freezes the
                   screen, self-resynchronising STOP, empty selection and sub-tick loops refused/handled.
2.3.0  2026-10-17  Jukebox ROM interface, driven by the pad:
                   - track list with cursor (UP/DOWN, held = repeat), LEFT/RIGHT game, A play / pause,
                     B stop, C previous, D next; tracks without a loop chain to the next one (then next game)
                   - real pause on the Z80 side (notes released, time frozen, SSG volumes restored on resume)
                   - 7 live VU meters (FM1-4, SSG, ADPCM-A, ADPCM-B) fed by the notes the Z80 actually plays,
                     rainbow title, progress bar, elapsed / total time, blinking PAUSE
                   - global ROM occupancy shown top right (P-ROM + V-ROM + M1 used / capacity)
2.2.0  2026-10-17  Compatibility and cartridge formats.
                   - old NGT1 files (one per track, NGT Studio 1.x, and the earlier JSON prototype) are read
                     transparently: the tracks of one game in one folder appear as one game; --upgrade DIR writes
                     real NGT2 files (originals kept). NGT2 files from every released version are read unchanged.
                   - jukebox ROM exported directly for Darksoft (folder prom/srom/m1rom/vroma0/crom0/fpga) and
                     NeoSD (.neo), besides the MAME set
                   - ADPCM-A samples never cross a 1 MB boundary in the cartridge V-ROM (YM2610 hardware limit
                     that MAME/ymfm do not reproduce)
2.1.0  2026-10-17  Jukebox ROM (Cartridge tab, --cart): builds a playable Neo Geo jukebox cartridge.
                   - YM2610 streams compressed (LZSS, 32 KB window, decompressed by the 68000): about 5-7x smaller
                   - evaluation before building with a 5 % margin under each limit; the build is refused above it
                   - standard format P1 1 MB + P2 4 MB / V-ROM 16 MB (largest unprotected official layout) or
                     extended P2 8 MB (3-bit bank, homebrew only) with bank markers checked by the jukebox at boot
                   - output: MAME set + software list (mame neogeo ngjb -hashpath hash -rompath .)
                   Verified in MAME only (bytes received by the Z80, audio vs reference, P2 bank change mid-song).
2.0.1  2026-10-17  Note decoding: FM pitch now accounts for operator MUL (a x0.5 operator sounds an octave lower).
                   Checked against the rendered audio on 3 games: 517/520 FM notes exact; SSG exact on the measurable notes.
2.0.0  2026-10-17  Listening & visual features driven by the YM2610 registers:
                   - live mixer: click a voice = mute, right-click = solo; re-rendered and swapped in without restarting
                   - live piano keyboard (notes decoded from FM F-number/block and SSG tone periods)
                   - album listening: "Loops" = endless, or N loops + 8 s fade-out (works with Next track at end)
                   - full-screen views (V): pictures + spectrum in the game's own colour · per-voice oscilloscopes ·
                     piano-roll waterfall with ADPCM drum pads and a stereo stage (real panning bits)
                   - "Album / stems…": whole game as a tagged FLAC/WAV album, or one track split per voice
                     (stems add up to the mix); CLI --album / --stems / --format / --loops
                   - "⛶ Visuals" button
1.7.0  2026-10-12  Optimisation: playback preparation ~3x faster (periodic edge context instead of 3 loop copies, float32), prepared\n                   tracks cached + next track prefetched in the background (instant next / auto-next), volume-mode changes\n                   instant, libretro index cached for 7 days.\n1.6.0  2026-10-12  Double-click the screenshot: full-screen on black with the spectrum and the 14 voices drawn semi-transparent\n                   over the picture; double-click (or Esc) to come back. Space = play/pause, Left/Right = previous/next.\n1.5.0  2026-10-12  ROM short names are decoded into full titles (built-in table, then Arcade Database, cached in\n                   ~/.ngt_studio_names.json) in the Player list and at extraction; screenshots looked up by ROM name\n                   (clones use their parent), + Arcade Database in-game/title images.\n1.4.3  2026-10-12  Built-in table of ~190 Neo Geo MAME names -> titles (needed to find screenshots and nicer game names).\n1.4.2  2026-10-12  Screenshots now come from thumbnails.libretro.com (no key, no API, no GitHub): Neo Geo + Neo Geo CD sets,\n                   snaps + title screens, title matching on alternative names.\n1.4.1  2026-10-12  --probe-pics: tests the screenshot sources (libretro, Google Images HTML) from the user's machine.\n1.4.0  2026-10-12  Player: square screenshot slideshow right of the graphs (libretro-thumbnails, temp cache deleted at exit,\n                   own images from ./pictures). Needs Pillow (auto-installed). "Screenshots" checkbox.\n1.3.1  2026-10-12  "Next track at end" and "Auto-loop" are mutually exclusive (Auto-loop is forced off and locked while Next is ticked).\n1.3.0  2026-10-12  Settings saved to ~/.ngt_studio.json: window size/position, maximised/full screen (F11), last tab, last\n                   Player folder (reopened at start), Extract options, Cartridge limits and file list.\n1.2.0  2026-10-12  Player: folders load instantly (CRC check in background), Auto-loop and Next-track-at-end options,
                   working previous/next across games, elapsed time while computing, ngt_studio.log diagnostics,
                   engine timeout, old m1render_*.exe cleanup, scipy/engine warm-up. Version display.
1.1.0  2026-10-11  Full English interface.
1.0.x  2026-10     Extraction (embedded m1render engine), player tab, cartridge tab, --selftest, Windows JSON path fix.
"""
EXE = "m1render.exe" if os.name == "nt" else "m1render"
OUT_RATE = 48000                      # sortie carte son (le moteur travaille à 55944 Hz)
TARGET = 32767 * 10 ** (-1 / 20)      # crête cible de l'auto-normalisation : -1 dBFS
VOICES = ["FM 1", "FM 2", "FM 3", "FM 4", "SSG A", "SSG B", "SSG C",
          "ADPCM-A 1", "ADPCM-A 2", "ADPCM-A 3", "ADPCM-A 4", "ADPCM-A 5", "ADPCM-A 6", "ADPCM-B"]
FPS = 30
LOOP_CHOICES = ["∞ (auto-loop)", "1 loop + fade", "2 loops + fade", "3 loops + fade"]
LOOP_COUNTS = [None, 1, 2, 3]
FS_VIEWS = ["pics", "scope", "roll"]
# one distinct colour per voice for the full-screen views (FM blues/violets, SSG greens, ADPCM-A oranges, ADPCM-B pink)
VIVID = ["#4fc3f7", "#7986cb", "#26c6da", "#ba68c8", "#9ccc65", "#66bb6a", "#d4e157",
         "#ffb74d", "#ff8a65", "#ffd54f", "#ffa726", "#ff7043", "#ffcc80", "#f06292"]
VOICES_SHORT = ["FM1", "FM2", "FM3", "FM4", "SSG A", "SSG B", "SSG C", "A1", "A2", "A3", "A4", "A5", "A6", "B"]


# ======================================================================================
# FORMAT .ngt
# ======================================================================================
# Format .ngt (Neo Geo Track), version 2 : UN fichier PAR JEU = échantillons communs + table des pistes + flux de chaque piste.
# Pensé pour être porté dans une ROM Neo Geo : binaire à champs fixes, pas de JSON, pas de compression.
# Entiers de l'EN-TÊTE et de la TABLE en gros-boutiste (natif 68000). Le FLUX n'a que des octets (sauf l'extension de délai,
# petit-boutiste pour le Z80).
#
# EN-TÊTE (128 octets)
#    0  "NGT2"
#    4  u32 taille totale du fichier
#    8  u32 CRC32 de tous les octets de l'offset 12 à la fin   <- le seul contrôle (facultatif côté ROM)
#   12  u32 fréquence de sortie (55944)       16  u32 nombre de pistes
#   20  u32 offset de la table des pistes (128)       24  u32 taille d'une entrée (80)
#   28  u32 offset des échantillons (multiple de 256)  32  u32 taille des échantillons (multiple de 256)
#   36  u16 crête maximale du jeu (normalisation « jeu »)
#   72  8 octets : code du jeu (ASCII)      80  32 octets : titre du jeu (ASCII)      112  16 octets réservés
# TABLE : une entrée de 80 octets par piste
#    0  u32 offset (absolu) du flux      4  u32 taille du flux      8  u32 nombre d'écritures
#   12  u32 k0 : indice d'échantillon où commence la musique (avant : initialisation du driver)
#   16  u32 durée en échantillons (jusqu'à la fin de boucle s'il y a une boucle)
#   20  u32 début de boucle (absolu) ou 0xFFFFFFFF      24  u32 fin de boucle (absolu) ou 0xFFFFFFFF
#   28  u32 offset, DANS le flux, où reprendre à la boucle (0 si pas de boucle)
#   32  u32 attente (échantillons) après la dernière écriture avant de reboucler
#   36  u16 crête de la piste   38 u8 n° de piste   39 u8 commande son   40 u8 argument (0xFF = aucun)
#   44  32 octets : libellé de la piste (ASCII), ex. "Track 01" (nom complet = titre du jeu + " - " + libellé)
# FLUX : suite d'écritures de 3 octets  [A][reg][val]
#    A : bit 7 = bloc haut (registres 0x100-0x1FF) ; bits 0-6 = délai en échantillons avant l'écriture (0..126).
#        Si bits 0-6 = 127 : délai étendu, deux octets petit-boutiste suivent A ([A][dlo][dhi][reg][val]).
#    Rejeu : puce remise à zéro ; attendre le délai, écrire l'adresse (reg) puis la donnée (val) sur les ports du bloc.
# BOUCLE : après la dernière écriture, attendre `attente` échantillons, puis reprendre le flux à l'offset de reprise.
#    Une écriture inoffensive (registre 0x0F, ignoré par la puce) marque l'instant exact du début de boucle.
# ÉCHANTILLONS : UN seul bloc ADPCM pour tout le jeu (union des zones de VROM utilisées par toutes les pistes), pages de
#    256 octets ; les adresses écrites dans chaque flux sont déjà remappées sur ce bloc. À charger comme VROM
#    (ADPCM-A et ADPCM-B partagent le même espace sur Neo Geo). Changer de piste = rejouer un autre flux, sans recharger.
#

MAGIC = b"NGT2"
RATE = 55944                          # fréquence native du YM2610 émulé (ymfm, fidélité mini)
PAGE = 256
EV_DTYPE = np.dtype([("t", "<u4"), ("reg", "<u2"), ("val", "u1"), ("pad", "u1")])

GAME_TITLES = {
    # MAME short name -> English title. Written from memory: a wrong or missing entry only means "no screenshot"
    # (or the zip name as title); add your own in game_titles.json ({"shortname": "Title"}).
    "nam1975": "NAM-1975", "bstars": "Baseball Stars Professional", "bstars2": "Baseball Stars 2", "tpgolf": "Top Player's Golf",
    "mahretsu": "Mahjong Kyoretsuden", "ridhero": "Riding Hero", "alpham2": "Alpha Mission II", "ncombat": "Ninja Combat",
    "cyberlip": "Cyber-Lip", "superspy": "The Super Spy", "mutnat": "Mutation Nation", "kotm": "King of the Monsters",
    "sengoku": "Sengoku", "burningf": "Burning Fight", "lbowling": "League Bowling", "gpilots": "Ghost Pilots",
    "joyjoy": "Puzzled", "lresort": "Last Resort", "2020bb": "2020 Super Baseball", "socbrawl": "Soccer Brawl",
    "roboarmy": "Robo Army", "fatfury1": "Fatal Fury - King of Fighters", "fbfrenzy": "Football Frenzy", "kotm2": "King of the Monsters 2",
    "sengoku2": "Sengoku 2", "3countb": "3 Count Bout", "aof": "Art of Fighting", "samsho": "Samurai Shodown",
    "tophuntr": "Top Hunter", "fatfury2": "Fatal Fury 2", "ssideki": "Super Sidekicks", "kof94": "The King of Fighters '94",
    "aof2": "Art of Fighting 2", "fatfursp": "Fatal Fury Special", "savagere": "Savage Reign", "ssideki2": "Super Sidekicks 2",
    "samsho2": "Samurai Shodown II", "pspikes2": "Power Spikes II", "fatfury3": "Fatal Fury 3", "sonicwi2": "Aero Fighters 2",
    "galaxyfg": "Galaxy Fight", "quizkof": "Quiz King of Fighters", "ssideki3": "Super Sidekicks 3", "doubledr": "Double Dragon",
    "pbobblen": "Puzzle Bobble", "kof95": "The King of Fighters '95", "tws96": "Tecmo World Soccer '96",
    "samsho3": "Samurai Shodown III", "stakwin": "Stakes Winner", "pulstar": "Pulstar", "whp": "World Heroes Perfect",
    "kabukikl": "Kabuki Klash", "neobombe": "Neo Bomberman", "gowcaizr": "Voltage Fighter Gowcaizer",
    "rbff1": "Real Bout Fatal Fury", "aof3": "Art of Fighting 3", "sonicwi3": "Aero Fighters 3", "turfmast": "Neo Turf Masters",
    "mslug": "Metal Slug", "ragnagrd": "Ragnagard", "pgoal": "Pleasure Goal", "ironclad": "Ironclad", "magdrop2": "Magical Drop II",
    "samsho4": "Samurai Shodown IV", "rbffspec": "Real Bout Fatal Fury Special", "twinspri": "Twinkle Star Sprites",
    "kof96": "The King of Fighters '96", "wakuwak7": "Waku Waku 7", "breakers": "Breakers", "neodrift": "Neo Drift Out",
    "mslug2": "Metal Slug 2", "kof97": "The King of Fighters '97", "lastblad": "The Last Blade", "puzzldpr": "Puzzle De Pon! R",
    "rbff2": "Real Bout Fatal Fury 2", "mslugx": "Metal Slug X", "kof98": "The King of Fighters '98", "lastbld2": "The Last Blade 2",
    "neocup98": "Neo-Geo Cup '98", "breakrev": "Breakers Revenge", "shocktr2": "Shock Troopers - 2nd Squad", "shocktro": "Shock Troopers",
    "flipshot": "Battle Flip Shot", "ctomaday": "Captain Tomaday", "kof99": "The King of Fighters '99", "ganryu": "Ganryu",
    "garou": "Garou - Mark of the Wolves", "s1945p": "Strikers 1945 Plus", "preisle2": "Prehistoric Isle 2", "mslug3": "Metal Slug 3",
    "kof2000": "The King of Fighters 2000", "bangbead": "Bang Bead", "nitd": "Nightmare in the Dark", "sengoku3": "Sengoku 3",
    "zupapa": "Zupapa!", "kof2001": "The King of Fighters 2001", "mslug4": "Metal Slug 4", "rotd": "Rage of the Dragons",
    "kof2002": "The King of Fighters 2002", "matrimelee": "Matrimelee", "mslug5": "Metal Slug 5",
    "svc": "SNK vs. Capcom - SVC Chaos", "samsho5": "Samurai Shodown V", "kof2003": "The King of Fighters 2003",
    "samsh5sp": "Samurai Shodown V Special", "wjammers": "Windjammers", "wh1": "World Heroes", "wh2": "World Heroes 2",
    "wh2j": "World Heroes 2 Jet", "trally": "Thrash Rally", "janshin": "Janshin Densetsu", "viewpoint": "Viewpoint",
    "androdun": "Andro Dunos", "crsword": "Crossed Swords", "fightfev": "Fight Fever", "spinmast": "Spin Master",
    "karnovr": "Karnov's Revenge", "overtop": "OverTop", "ssideki4": "The Ultimate 11", "bjourney": "Blue's Journey",
    "maglord": "Magician Lord", "goalx3": "Goal! Goal! Goal!", "zedblade": "Zed Blade", "sdodgeb": "Super Dodge Ball",
    "panicbom": "Panic Bomber", "eightman": "Eight Man", "legendos": "Legend of Success Joe",
    "mosyougi": "Mahjong Shougi", "adkworld": "ADK World", "irrmaze": "The Irritating Maze", "diggerma": "Digger Man",
    "marukodq": "Chibi Marukochan Deluxe Quiz", "minasan": "Minasanno Okagesamadesu!", "popbounc": "Pop 'n Bounce",
    "pnyaa": "Pochi and Nyaa", "bakatono": "Bakatonosama Mahjong Manyuuki", "tpgolf": "Top Player's Golf",
    "strhoop": "Street Hoop", "sonicwi": "Aero Fighters", "fswords": "Fighters Swords", "kof2000n": "The King of Fighters 2000",
}


NAMES_FILE = os.path.join(os.path.expanduser("~"), ".ngt_studio_names.json")        # cache of decoded names (shortname -> info)
ADB_URL = "https://adb.arcadeitalia.net/service_scraper.php?ajax=query_mame&lang=en&game_name="
_names_cache = None
_adb_down = [False]                  # set after a network failure so that one offline run is not slowed down game by game
_CODE_PAREN = re.compile(r"\s*\((?:[A-Z]{2,4}-\d+[^)]*)\)")


def _names_load():
    global _names_cache
    if _names_cache is None:
        try:
            _names_cache = json.load(open(NAMES_FILE, encoding="utf-8"))
        except Exception:
            _names_cache = {}
    return _names_cache


def _names_save():
    try:
        tmp = NAMES_FILE + ".%d.tmp" % os.getpid()
        merged = {}
        try:
            merged = json.load(open(NAMES_FILE, encoding="utf-8"))
        except Exception:
            pass
        merged.update(_names_cache or {})
        json.dump(merged, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
        os.replace(tmp, NAMES_FILE)
    except Exception:
        pass


def clean_adb_title(t):
    """'Art of Fighting 2 / Ryuuko no Ken 2 (NGM-056)' -> ('Art of Fighting 2', ['Art of Fighting 2', 'Ryuuko no Ken 2'])."""
    segs = [_CODE_PAREN.sub("", x).strip() for x in t.split(" / ")]
    segs = [x for x in segs if x]
    return (segs[0] if segs else t), segs


def adb_lookup(short, online=True, timeout=8):
    """MAME short name -> {title, alts, cloneof, ingame, titleimg} from the Arcade Database (public scraper endpoint, no key),
    or None if unknown.  Results (also negative ones) are cached in ~/.ngt_studio_names.json.  Returns False on a network error."""
    cache = _names_load()
    if short in cache and (cache[short] is None or "manufacturer" in cache[short] or not online or _adb_down[0]):
        return cache[short]
    if not online or _adb_down[0]:
        return False
    try:
        data = json.loads(_http_get(ADB_URL + urllib.parse.quote(short), timeout))
    except Exception as ex:
        _adb_down[0] = True
        dlog(f"names: ADB unreachable ({ex})")
        return False
    res = data.get("result") or []
    if not res:
        cache[short] = None
    else:
        r = res[0]
        title, segs = clean_adb_title(r.get("title", short))
        cache[short] = {"title": title, "alts": segs, "cloneof": r.get("cloneof") or "",
                        "ingame": r.get("url_image_ingame") or "", "titleimg": r.get("url_image_title") or "",
                        "manufacturer": r.get("manufacturer") or "", "year": r.get("year") or ""}
    _names_save()
    return cache[short]


def _short_from_header(game, title):
    """The .ngt stores the ROM name in 'game' (8 chars max) and, for unknown games, again in 'title'."""
    return title if re.fullmatch(r"[a-z0-9_]{3,32}", title or "") else game


def decode_name(short, online=True):
    """Full title for a ROM short name: built-in table, then cache, then (if online) the Arcade Database.  None if unknown."""
    if short in GAME_TITLES:
        return GAME_TITLES[short]
    if len(short) == 8:                                      # may be truncated by the 8-byte header field
        c = [k for k in GAME_TITLES if k.startswith(short)]
        if len(c) == 1:
            return GAME_TITLES[c[0]]
    info = adb_lookup(short, online)
    return info["title"] if info else None


def game_title(shortname, overrides=None, online=False):
    """Titre affiché : table connue (ou fichier game_titles.json) ; sinon cache / base en ligne ; sinon le nom du zip tel quel.
    Une variante « nom_suffixe » reprend le titre de base suivi du suffixe entre parenthèses."""
    tab = dict(GAME_TITLES)
    tab.update(overrides or {})
    if shortname in tab:
        return tab[shortname]
    base, _, suf = shortname.partition("_")
    if base in tab and suf:
        return f"{tab[base]} ({suf})"
    d = decode_name(shortname, online)
    if d:
        return d[:32]
    return shortname


# ---------------------------------------------------------------- écritures brutes -> registres effectifs
def decode_registers(port_events):
    """Les 4 ports du YM2610 partagent UN registre d'adresse : on ne garde que les écritures de données effectives.
    Retourne une liste de (t, reg9, val)."""
    addr = 0
    out = []
    for t, off, val in zip(port_events["t"].tolist(), (port_events["reg"] & 3).tolist(), port_events["val"].tolist()):
        if off == 0:
            addr = val
        elif off == 2:
            addr = 0x100 | val
        elif off == 1 and addr < 0x100:
            out.append((t, addr, val))
        elif off == 3 and addr >= 0x100:
            out.append((t, addr, val))
    return out


# ---------------------------------------------------------------- réduction des échantillons
_A_START_LO, _A_START_HI, _A_END_LO, _A_END_HI = 0x110, 0x118, 0x120, 0x128
_B_REGS = (0x12, 0x13, 0x14, 0x15)


def _is_addr_reg(reg):
    if 0x110 <= reg <= 0x115 or 0x118 <= reg <= 0x11D or 0x120 <= reg <= 0x125 or 0x128 <= reg <= 0x12D:
        return True
    return reg in _B_REGS


def _sample_uses(regs, b_off=0):
    """b_off : position (octets) de la ROM ADPCM-B dans la V-ROM unifiée, pour les jeux à ROM B séparée (v2x)."""
    state, uses = {}, []            # uses : (indice dans regs, kind, canal, start_byte, end_byte)
    for i, (t, reg, val) in enumerate(regs):
        state[reg] = val
        if reg == 0x100 and not val & 0x80:
            for ch in range(6):
                if val >> ch & 1:
                    s = ((state.get(0x118 + ch, 0) << 8) | state.get(0x110 + ch, 0)) << 8
                    end = (state.get(0x128 + ch, 0) << 8) | state.get(0x120 + ch, 0)
                    # le YM2610 (ymfm, comme MAME) s'arrete quand les 20 bits bas de l'adresse atteignent (fin + 1) x 256 :
                    # octets joues = ((fin + 1) x 256 - debut) modulo 1 Mo.  0 = rien n'est joue (ex. Puzzle De Pon : debut 0,
                    # fin 0xFFFF laissee par le pilote) -> e = s - 1, echantillon vide (avant la 2.5.19, compte de 0 a 16 Mo)
                    n = (((end + 1) << 8) - s) & 0xFFFFF
                    uses.append((i, "A", ch, s, s + n - 1))
        elif reg == 0x10 and val & 0x80:
            s = ((state.get(0x13, 0) << 8) | state.get(0x12, 0)) << 8
            e = ((((state.get(0x15, 0) << 8) | state.get(0x14, 0)) << 8) | 0xFF)
            uses.append((i, "B", 0, s + b_off, e + b_off))
    return uses


def reduce_samples_multi(regs_list, vrom, guard_pages=1, base_page=0, bank_safe=True, b_off=0):
    """Réduction COMMUNE à plusieurs pistes : union des pages de VROM utilisées -> (liste de regs remappés, bloc, infos).
    Les écritures d'adresses de départ/fin sont supprimées et réinjectées, remappées, juste avant chaque déclenchement.
    base_page : numéro de page (256 octets) où le bloc sera placé dans la VROM de la cartouche.
    bank_safe : aucun échantillon ADPCM-A ne franchit une frontière de 1 Mo (le YM2610 garde les 4 bits hauts de
    l'adresse de départ : un échantillon à cheval relirait le début du même Mo).  MAME/ymfm ne reproduisent pas cette
    limite, d'où l'importance de la respecter ici ; au besoin un bloc est décalé (pages de remplissage)."""
    all_uses = [_sample_uses(r, b_off) for r in regs_list]
    pages = set()
    for uses in all_uses:
        for _, kind, _, s, e in uses:
            if s <= e and e - s < (16 << 20):
                hi = (e >> 8) + (guard_pages if kind == "B" else 0)
                pages.update(range(s >> 8, hi + 1))
    runs = []
    for p in sorted(pages):
        if runs and runs[-1][1] == p - 1:
            runs[-1][1] = p
        else:
            runs.append([p, p])
    a_spans = sorted({(s >> 8, e >> 8) for uses in all_uses for _, kind, _, s, e in uses
                      if kind == "A" and s <= e and e - s < (16 << 20)})      # chaque échantillon une seule fois
    import bisect
    a_starts = [ps for ps, _ in a_spans]
    newbase, pads, acc = {}, {}, 0
    for lo, hi in runs:
        pos = acc
        if bank_safe:
            inside = a_spans[bisect.bisect_left(a_starts, lo):bisect.bisect_right(a_starts, hi)]

            def fits(p):
                return all(((base_page + p + ps - lo) >> 12) == ((base_page + p + pe - lo) >> 12) for ps, pe in inside)
            if not fits(pos):                                   # plus petit décalage qui évite toute frontière
                pos = next((pos + d for d in range(1, 4096) if fits(pos + d)), pos)
        pads[lo] = pos - acc
        newbase[lo] = pos
        acc = pos + hi - lo + 1
    blob = bytearray()
    for lo, hi in runs:
        seg = bytes(vrom[lo * PAGE:(hi + 1) * PAGE])
        blob += bytes(pads[lo] * PAGE) + seg + bytes((hi + 1 - lo) * PAGE - len(seg))

    def remap_page(p):
        for lo, hi in runs:
            if lo <= p <= hi:
                return base_page + newbase[lo] + (p - lo)
        return base_page

    out = []
    for regs, uses in zip(regs_list, all_uses):
        inserts = {}
        for i, kind, ch, s, e in uses:
            ns, ne = remap_page(s >> 8), remap_page(e >> 8)
            if kind == "A" and e < s:
                ne = (ns - 1) & 0xFFFF                          # echantillon vide : il le reste ((fin + 1) = debut)
            if kind == "A":
                # au-delà de 16 Mo (65536 pages) l'adresse ne tient plus dans les registres : elle reboucle ici au lieu
                # de planter ; une telle cartouche dépasse forcément la V-ROM permise et evaluate_cart la refuse
                w = [(0x110 + ch, ns & 0xFF), (0x118 + ch, (ns >> 8) & 0xFF), (0x120 + ch, ne & 0xFF), (0x128 + ch, (ne >> 8) & 0xFF)]
            else:
                w = [(0x12, ns & 0xFF), (0x13, (ns >> 8) & 0xFF), (0x14, ne & 0xFF), (0x15, (ne >> 8) & 0xFF)]
            inserts.setdefault(i, []).extend(w)
        new = []
        for i, (t, reg, val) in enumerate(regs):
            for r2, v2 in inserts.get(i, ()):
                new.append((t, r2, v2))
            if _is_addr_reg(reg):
                continue
            new.append((t, reg, val))
        out.append(new)
    info = {"runs": [[lo * PAGE, (hi + 1) * PAGE] for lo, hi in runs], "bytes": len(blob),
            "vrom_bytes": len(vrom), "triggers": sum(len(u) for u in all_uses)}
    return out, bytes(blob), info



# ---------------------------------------------------------------- (dé)sérialisation
HEADER = 128
NONE = 0xFFFFFFFF
NOP = (0x0F, 0)            # registre 0x0F du bloc bas : non géré par le YM2610, sert de repère de boucle


def _encode_stream(regs, loop_start, loop_end):
    """-> (octets du flux, offset de reprise de boucle, attente avant reboucle, liste des écritures réellement codées)."""
    if loop_start is not None:
        i = next((k for k, (t, _, _) in enumerate(regs) if t >= loop_start), len(regs))
        regs = list(regs[:i]) + [(loop_start, NOP[0], NOP[1])] + list(regs[i:])
    out = bytearray()
    prev, loop_off, last_t = 0, 0, 0
    for k, (t, reg, val) in enumerate(regs):
        d = t - prev
        hi = 0x80 if reg >= 0x100 else 0
        if d < 127:
            out += bytes((hi | d, reg & 0xFF, val))
        else:
            out += bytes((hi | 127, d & 0xFF, (d >> 8) & 0xFF, reg & 0xFF, val))
            if d > 0xFFFF:
                raise ValueError("delay > 65535 samples between two writes")
        prev = last_t = t
        if loop_start is not None and (reg, val) == NOP and t == loop_start and not loop_off:
            loop_off = len(out)
    tail = (loop_end - last_t) if loop_end is not None else 0
    return bytes(out), loop_off, tail, regs


ENTRY = 80


def pack_game(tracks, blob, game, title):
    """tracks : liste de dicts {regs, rate, k0, length_samples, loop_start, loop_end, peak, track, cmd, arg, name}.
    -> octets du fichier .ngt du jeu."""
    streams, entries = [], []
    off = HEADER + ENTRY * len(tracks)
    for t in tracks:
        stream, loop_off, tail, coded = _encode_stream(t["regs"], t.get("loop_start"), t.get("loop_end"))
        streams.append(stream)
        e = bytearray(ENTRY)
        ls, le, arg = t.get("loop_start"), t.get("loop_end"), t.get("arg")
        struct.pack_into(">IIIIIIIIIH", e, 0, off, len(stream), len(coded), t["k0"], t["length_samples"],
                         NONE if ls is None else ls, NONE if le is None else le, loop_off, tail,
                         min(int(t.get("peak", 0)), 0xFFFF))
        e[38] = int(t.get("track", 0)) & 0xFF
        e[39] = int(t.get("cmd", 0)) & 0xFF
        e[40] = 0xFF if arg is None else int(arg) & 0xFF
        e[44:76] = ("Track %02d" % int(t.get("track", 0))).encode("ascii")[:31].ljust(32, b"\0")   # le titre du jeu est dans l'en-tête
        entries.append(bytes(e))
        off += len(stream)
    soff = (off + 255) & ~255
    blob = bytes(blob)
    hdr = bytearray(HEADER)
    hdr[0:4] = MAGIC
    struct.pack_into(">I", hdr, 4, soff + len(blob))
    struct.pack_into(">IIIIIIH", hdr, 12, tracks[0].get("rate", RATE) if tracks else RATE, len(tracks), HEADER, ENTRY,
                     soff, len(blob), max([min(int(t.get("peak", 0)), 0xFFFF) for t in tracks] or [0]))
    hdr[72:80] = game.encode("ascii", "replace")[:8].ljust(8, b"\0")
    hdr[80:112] = title.encode("ascii", "replace")[:31].ljust(32, b"\0")
    data = bytes(hdr) + b"".join(entries) + b"".join(streams) + bytes(soff - off) + blob
    return data[:8] + struct.pack(">I", zlib.crc32(data[12:]) & 0xFFFFFFFF) + data[12:]


def read_header(data):
    """Jeu + table des pistes, sans toucher aux flux ni aux échantillons.  Les entrées de `tracks` portent aussi les
    champs du jeu utiles au lecteur (game, game_peak, samples_bytes)."""
    if len(data) < HEADER or data[:4] != MAGIC:
        raise ValueError("NGT2 signature missing or file too short")
    total, crc, rate, n, toff, esz, soff, ssz, gpeak = struct.unpack(">IIIIIIIIH", data[4:38])
    game = data[72:80].rstrip(b"\0").decode("ascii", "replace")
    title = data[80:112].rstrip(b"\0").decode("ascii", "replace")
    tracks = []
    for i in range(n):
        e = data[toff + i * esz: toff + (i + 1) * esz]
        if len(e) < ENTRY:
            raise ValueError("track table truncated")
        so, ss, nev, k0, ln, ls, le, lo, tail, pk = struct.unpack(">IIIIIIIIIH", e[:38])
        tracks.append({"rate": rate, "stream_offset": so, "stream_size": ss, "n_events": nev, "k0": k0,
                       "length_samples": ln, "loop_start": None if ls == NONE else ls,
                       "loop_end": None if le == NONE else le, "loop_stream_offset": lo, "loop_tail": tail,
                       "peak": pk, "track": e[38], "cmd": e[39], "arg": None if e[40] == 0xFF else e[40],
                       "name": (title + " - " + e[44:76].rstrip(b"\0").decode("ascii", "replace")),
                       "game": game, "game_peak": gpeak, "samples_bytes": ssz})
    return {"file_size": total, "crc32": crc, "rate": rate, "game": game, "title": title, "game_peak": gpeak,
            "samples_offset": soff, "samples_bytes": ssz, "tracks": tracks}


def check(data):
    """Contrôle d'intégrité unique : signature, taille annoncée, CRC32.  -> (ok, message)."""
    try:
        h = read_header(data)
    except (ValueError, struct.error) as ex:
        return False, str(ex)
    if h["file_size"] != len(data):
        return False, f"size {len(data)} bytes, {h['file_size']} announced (file truncated or modified)"
    if zlib.crc32(data[12:]) & 0xFFFFFFFF != h["crc32"]:
        return False, "content altered (CRC32)"
    return True, "ok"


def decode_stream(stream):
    regs, p, t = [], 0, 0
    while p < len(stream):
        a = stream[p]
        d = a & 0x7F
        if d == 127:
            d = stream[p + 1] | (stream[p + 2] << 8)
            p += 2
        t += d
        regs.append((t, ((a >> 7) << 8) | stream[p + 1], stream[p + 2]))
        p += 3
    return regs


def unpack(data, idx=0, verify=True):
    """-> (meta de la piste idx, regs[(t, reg9, val)], bloc d'échantillons commun).  ValueError si le contrôle échoue."""
    if verify:
        ok, msg = check(data)
        if not ok:
            raise ValueError(msg)
    h = read_header(data)
    m = h["tracks"][idx]
    regs = decode_stream(data[m["stream_offset"]:m["stream_offset"] + m["stream_size"]])
    return m, regs, data[h["samples_offset"]:h["samples_offset"] + h["samples_bytes"]]


def regs_to_port_stream(regs, k0):
    """Écritures de registre -> fichier .stream de l'émulateur (adresse puis donnée, au même instant)."""
    arr = np.zeros(len(regs) * 2, dtype=EV_DTYPE)
    for i, (t, reg, val) in enumerate(regs):
        hi = reg >= 0x100
        arr[2 * i] = (t, 2 if hi else 0, reg & 0xFF, 0)
        arr[2 * i + 1] = (t, 3 if hi else 1, val, 0)
    return struct.pack("<I", k0) + arr.tobytes()



# ------------------------------------------------------------------ rétrocompatibilité : anciens fichiers NGT1
# NGT1 = UN fichier PAR PISTE (versions 1.x de l'outil), deux variantes :
#   - binaire gros-boutiste, en-tête 128 octets (taille, CRC32, k0, boucle, flux au même codage que NGT2, échantillons)
#   - prototype petit-boutiste : en-tête 28 octets + métadonnées JSON + flux zlib (varints) + échantillons + SHA-256
# Les fichiers NGT1 d'un même jeu et d'un même dossier sont regroupés en UN jeu NGT2 virtuel, construit en mémoire
# (échantillons dédoublonnés) : le lecteur, l'export d'album et la cartouche les utilisent comme un .ngt actuel.
# Rien n'est réécrit sur le disque sauf demande explicite (--upgrade).
NGT1_MAGIC = b"NGT1"
_NGT_VIRT = {}          # chemin virtuel -> [fichiers NGT1]
_NGT_BUILT = {}         # (chemin, signature des fichiers) -> octets NGT2


def _ngt1_read(data):
    """Un fichier NGT1 (l'une ou l'autre variante) -> (meta, regs sans repère de boucle, échantillons)."""
    if len(data) < 60 or data[:4] != NGT1_MAGIC:
        raise ValueError("NGT1 signature missing or file too short")
    if len(data) >= 128 and struct.unpack(">I", data[4:8])[0] == len(data):
        total, crc, rate, k0, length, ls, le, nev, soffs = struct.unpack(">IIIIIIIII", data[4:40])
        ssize, boff, bsize = struct.unpack(">III", data[40:52])
        if zlib.crc32(data[12:]) & 0xFFFFFFFF != crc:
            raise ValueError("NGT1 content altered (CRC32)")
        meta = {"rate": rate, "k0": k0, "length_samples": length, "loop_start": None if ls == NONE else ls,
                "loop_end": None if le == NONE else le, "peak": struct.unpack(">H", data[64:66])[0],
                "track": data[66], "cmd": data[67], "arg": None if data[68] == 0xFF else data[68],
                "game": data[72:80].rstrip(b"\0").decode("ascii", "replace"),
                "name": data[80:112].rstrip(b"\0").decode("ascii", "replace")}
        regs = _strip_nop(decode_stream(data[soffs:soffs + ssize]))
        return meta, regs, data[boff:boff + bsize]
    total, jl, n, cl, bl, crc = struct.unpack("<IIIIII", data[4:28])
    if total != len(data) or 28 + jl + cl + bl + 32 != total:
        raise ValueError("NGT1 file truncated or not recognised")
    if zlib.crc32(data[:24] + data[28:28 + jl]) & 0xFFFFFFFF != crc or hashlib.sha256(data[:-32]).digest() != data[-32:]:
        raise ValueError("NGT1 content altered")
    js = json.loads(data[28:28 + jl].decode("utf-8"))
    body = zlib.decompress(data[28 + jl:28 + jl + cl])
    regs, p, t = [], 0, 0
    for _ in range(n):
        x, sh = 0, 0
        while True:
            b = body[p]; p += 1
            x |= (b & 127) << sh
            sh += 7
            if b < 128:
                break
        t += x >> 1
        regs.append((t, ((x & 1) << 8) | body[p], body[p + 1]))
        p += 2
    args = js.get("args") or []
    meta = {"rate": js.get("rate", RATE), "k0": js["k0"], "length_samples": js["length_samples"],
            "loop_start": js.get("loop_start"), "loop_end": js.get("loop_end"), "peak": js.get("peak", 0),
            "track": js.get("track", 0), "cmd": js.get("cmd", 0), "arg": args[-1] if args else js.get("arg"),
            "game": js.get("game", ""), "name": js.get("name", "")}
    blob = data[28 + jl + cl:28 + jl + cl + bl]
    return meta, _strip_nop(regs), blob


def merge_track_samples(items, guard_pages=1):
    """[(regs, échantillons propres à la piste)] -> (regs remappés, bloc commun).  Chaque échantillon est copié une
    seule fois (dédoublonnage par contenu) ; un échantillon ADPCM-A ne franchit jamais une frontière de 1 Mo."""
    blob, placed, out = bytearray(), {}, []
    for regs, src in items:
        inserts = {}
        for i, kind, ch, s, e in _sample_uses(regs):
            if kind == "A" and s > e:                       # echantillon vide (fin + 1 = debut) : il le reste
                inserts.setdefault(i, []).extend([(0x110 + ch, 0), (0x118 + ch, 0), (0x120 + ch, 0xFF), (0x128 + ch, 0xFF)])
                continue
            if s > e or e - s >= (16 << 20):
                continue
            hi = e + (guard_pages * PAGE if kind == "B" else 0)
            content = bytes(src[s:hi + 1]).ljust(hi + 1 - s, b"\0")
            npages = (e >> 8) - (s >> 8)
            pos = placed.get(content)
            if pos is None or (kind == "A" and (pos >> 12) != ((pos + npages) >> 12)):
                pos = len(blob) // PAGE
                if kind == "A" and (pos >> 12) != ((pos + npages) >> 12):
                    pos = ((pos >> 12) + 1) << 12
                    blob += bytes(pos * PAGE - len(blob))
                blob += content
                placed.setdefault(content, pos)
            ns, ne = pos, pos + npages
            if kind == "A":
                w = [(0x110 + ch, ns & 0xFF), (0x118 + ch, ns >> 8), (0x120 + ch, ne & 0xFF), (0x128 + ch, ne >> 8)]
            else:
                w = [(0x12, ns & 0xFF), (0x13, ns >> 8), (0x14, ne & 0xFF), (0x15, ne >> 8)]
            inserts.setdefault(i, []).extend(w)
        new = []
        for i, (t, reg, val) in enumerate(regs):
            for r2, v2 in inserts.get(i, ()):
                new.append((t, r2, v2))
            if not _is_addr_reg(reg):
                new.append((t, reg, val))
        out.append(new)
    blob += bytes((-len(blob)) % PAGE)
    return out, bytes(blob)


def ngt1_to_ngt2(paths):
    """Fichiers NGT1 (un par piste, même jeu) -> octets d'un fichier NGT2 (un par jeu)."""
    tracks = []
    for p in paths:
        meta, regs, blob = _ngt1_read(open(p, "rb").read())
        tracks.append((meta, regs, blob, p))
    tracks.sort(key=lambda x: (x[0].get("track", 0), x[3]))
    new_regs, blob = merge_track_samples([(r, b) for _, r, b, _ in tracks])
    game = tracks[0][0].get("game") or os.path.splitext(os.path.basename(paths[0]))[0]
    try:
        title = game_title(game, {})
    except Exception:
        title = game
    infos = [dict(m, regs=r) for (m, _, _, _), r in zip(tracks, new_regs)]
    return pack_game(infos, blob, game[:8], title)


def _magic(path):
    try:
        with open(path, "rb") as f:
            return f.read(4)
    except OSError:
        return b""


def _ngt1_game(path):
    """Code du jeu d'un fichier NGT1 (sans lire les échantillons)."""
    with open(path, "rb") as f:
        head = f.read(128)
    if len(head) >= 80 and struct.unpack(">I", head[4:8])[0] == os.path.getsize(path):
        return head[72:80].rstrip(b"\0").decode("ascii", "replace")
    try:
        return _ngt1_read(open(path, "rb").read())[0].get("game", "")
    except Exception:
        return os.path.basename(path).split(" - Track")[0]


def ngt_group_files(files):
    """Liste de .ngt -> même liste où les NGT1 sont remplacés par un jeu virtuel par (dossier, jeu)."""
    out, groups = [], {}
    for f in files:
        if f in _NGT_VIRT or _magic(f) != NGT1_MAGIC:
            out.append(f)
            continue
        key = (os.path.dirname(f), _ngt1_game(f))
        if key not in groups:
            groups[key] = []
            out.append(key)
        groups[key].append(f)
    have = set()                                   # jeux déjà présents en NGT2 dans le même dossier (après --upgrade)
    for x in out:
        if not isinstance(x, tuple) and x not in _NGT_VIRT:
            try:
                with open(x, "rb") as fh:
                    h = fh.read(80)
                if h[:4] == MAGIC:
                    have.add((os.path.dirname(x), h[72:80].rstrip(b"\0").decode("ascii", "replace")))
            except OSError:
                pass
    res = []
    for x in out:
        if isinstance(x, tuple) and x in have:
            continue                               # la version NGT2 convertie remplace les pistes NGT1
        if isinstance(x, tuple):
            members = sorted(groups[x])
            try:
                title = game_title(x[1], {}) or x[1]
            except Exception:
                title = x[1]
            v = os.path.join(x[0], f"{title} [NGT1 x{len(members)}].ngt")
            _NGT_VIRT[v] = members
            res.append(v)
        else:
            res.append(x)
    return res


def _ngt_sig(path):
    members = _NGT_VIRT.get(path) or [path]
    return tuple((m, os.path.getmtime(m), os.path.getsize(m)) for m in members)


def ngt_data(path):
    """Octets NGT2 d'un fichier .ngt : lu tel quel (NGT2) ou converti en mémoire (NGT1, groupe virtuel)."""
    if path not in _NGT_VIRT and _magic(path) != NGT1_MAGIC:
        with open(path, "rb") as f:
            return f.read()
    key = _ngt_sig(path)
    if key not in _NGT_BUILT:
        if len(_NGT_BUILT) > 8:
            _NGT_BUILT.clear()
        _NGT_BUILT[key] = ngt1_to_ngt2(_NGT_VIRT.get(path) or [path])
    return _NGT_BUILT[key]


def ngt_size(path):
    return sum(os.path.getsize(m) for m in (_NGT_VIRT.get(path) or [path]))


def ngt_upgrade(folder, log=print):
    """Convertit les NGT1 d'un dossier (récursif) en NGT2, un fichier par jeu, à côté des originaux (conservés)."""
    files = sorted(glob.glob(os.path.join(folder, "**", "*.ngt"), recursive=True))
    n = 0
    for v in ngt_group_files(files):
        if v not in _NGT_VIRT:
            continue
        data = ngt_data(v)
        h = read_header(data)
        out = os.path.join(os.path.dirname(v), safe_name(h["title"]) + ".ngt")
        if os.path.exists(out):
            out = os.path.join(os.path.dirname(v), safe_name(h["title"]) + " (from NGT1).ngt")
        if os.path.exists(out):
            log(f"skipped (exists): {out}")
            continue
        with open(out, "wb") as f:
            f.write(data)
        n += 1
        log(f"{len(_NGT_VIRT[v])} NGT1 tracks -> {out} ({len(data) / 1e6:.1f} MB)")
    return n


def safe_name(s):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s).strip(" .") or "game"


def mute_regs(regs, muted):
    """Silences voices by rewriting their register writes (0-13 = FM1-4, SSG A-C, ADPCM-A1-6, ADPCM-B).
    FM: key-on slots cleared; SSG: level forced to 0; ADPCM-A: key-on bit cleared; ADPCM-B: start bit cleared.
    Everything else (pitches, timers, the other voices) is kept, so the timing of the music is untouched."""
    muted = set(muted)
    if not muted:
        return regs
    fm_sel = {1: 0, 2: 1, 5: 2, 6: 3}
    a_mask = sum(1 << c for c in range(6) if 7 + c in muted)
    out = []
    for t, reg, val in regs:
        if reg == 0x28 and fm_sel.get(val & 7) in muted:
            val &= 0x0F                                         # key-off: the channel never sounds
        elif reg in (0x08, 0x09, 0x0A) and 4 + reg - 0x08 in muted:
            val = 0
        elif reg == 0x100 and not val & 0x80 and a_mask:
            val &= ~a_mask & 0xFF
            if not val & 0x3F:
                continue
        elif reg == 0x10 and 13 in muted:
            val &= 0x7F
        out.append((t, reg, val))
    return out


def note_events(regs, meta):
    """Notes actually played, decoded from the registers -> dict of numpy arrays start, end (samples from the start of the
    music), midi (float, 69 = A4) and voice (0-3 FM, 4-6 SSG).  FM: key-on/off of reg 0x28 + F-number/block; SSG: tone
    period while the tone is enabled and the level is not 0.  A pitch change while a note sounds starts a new segment."""
    k0, n = meta["k0"], meta["length_samples"]
    fs = float(meta.get("rate", RATE))
    clock = fs * 144.0                                     # YM2610 master clock implied by the sample rate
    R = {}
    fm_regs = {0: (0xA1, 0xA5), 1: (0xA2, 0xA6), 2: (0x1A1, 0x1A5), 3: (0x1A2, 0x1A6)}
    fm_sel = {1: 0, 2: 1, 5: 2, 6: 3}
    on = {}                                                # voice -> (start, midi)
    out = []

    def midi_of(f):
        return 69.0 + 12.0 * np.log2(f / 440.0) if f > 8.0 else None

    fm_base = {0: 0x01, 1: 0x02, 2: 0x101, 3: 0x102}
    carriers = {0: (3,), 1: (3,), 2: (3,), 3: (3,), 4: (1, 3), 5: (1, 2, 3), 6: (1, 2, 3), 7: (0, 1, 2, 3)}
    slots = (0x30, 0x38, 0x34, 0x3C)                       # register offsets of operators 1, 2, 3, 4

    def fm_factor(c):
        """Heard fundamental / F-number frequency.  Each operator runs at MUL x f (MUL 0 = x0.5); the summed waveform
        repeats at the GCD of the audible operators' ratios, so e.g. a x0.5 modulator puts the note an octave lower."""
        b = fm_base[c]
        hi, ch = b & 0x100, b & 3
        alg = R.get(hi | (0xB0 + ch), 0) & 7
        g = 0
        for k in range(4):
            tl = R.get(hi | (0x40 + slots[k] - 0x30 + ch), 0) & 0x7F
            if k not in carriers[alg] and tl >= 0x50:      # a modulator this quiet barely shapes the waveform
                continue
            mul = R.get(hi | (slots[k] + ch), 0) & 0x0F
            g = math.gcd(g, 2 * mul if mul else 1)         # in half-steps of f
        return g / 2.0 if g else 1.0

    def fm_midi(c):
        lo, hi = fm_regs[c]
        fnum = ((R.get(hi, 0) & 7) << 8) | R.get(lo, 0)
        block = (R.get(hi, 0) >> 3) & 7
        return midi_of(fnum * fs * 2.0 ** (block - 1) / 2.0 ** 20 * fm_factor(c))

    def ssg_midi(i):
        tp = ((R.get(0x01 + 2 * i, 0) & 0x0F) << 8) | R.get(0x00 + 2 * i, 0)
        if not tp:
            return None
        lvl = R.get(0x08 + i, 0)
        if (R.get(0x07, 0xFF) >> i) & 1 or not (lvl & 0x1F):
            return None
        return midi_of(clock / 4.0 / (16.0 * tp))

    def stop(v, t):
        if v in on:
            st, m = on.pop(v)
            if t > st:
                out.append((st, t, m, v))

    def start(v, t, m):
        stop(v, t)
        if m is not None:
            on[v] = (t, m)

    for t, reg, val in regs:
        tt = t - k0
        R[reg] = val
        if reg == 0x28:
            c = fm_sel.get(val & 7)
            if c is None:
                continue
            if val >> 4:
                start(c, tt, fm_midi(c))
            else:
                stop(c, tt)
        elif reg in (0xA1, 0xA2, 0x1A1, 0x1A2):            # low F-number byte written last: the pitch is now valid
            c = {0xA1: 0, 0xA2: 1, 0x1A1: 2, 0x1A2: 3}[reg]
            if c in on:
                m = fm_midi(c)
                if m is not None and abs(m - on[c][1]) > 0.5:
                    start(c, tt, m)
        elif reg <= 0x0A and reg not in (0x06,):
            for i in range(3):
                v = 4 + i
                m = ssg_midi(i)
                if m is None:
                    stop(v, tt)
                elif v not in on or abs(m - on[v][1]) > 0.5:
                    start(v, tt, m)
    for v in list(on):
        stop(v, n)
    if not out:
        z = np.zeros(0)
        return {"start": z, "end": z, "midi": z, "voice": z.astype(int)}
    a = np.array(out, dtype=np.float64)
    return {"start": a[:, 0], "end": a[:, 1], "midi": a[:, 2], "voice": a[:, 3].astype(int)}


def visual_events(regs, meta):
    """Data for the graphic views, decoded from the registers:
    drums  : every ADPCM-A trigger (time, channel, sample start address) and ADPCM-B trigger;
    pads   : the most used ADPCM-A samples (start addresses), one pad each;
    pan    : for each voice, the times and L/R bits of its panning (FM 0xB4+, ADPCM-A 0x108+, ADPCM-B 0x11; SSG = centre)."""
    k0 = meta["k0"]
    R = {}
    hits, bhits = [], []
    pan = {v: ([0], [3]) for v in range(14)}                # default: both outputs on (centre)
    fm_pan = {0xB5: 0, 0xB6: 1, 0x1B5: 2, 0x1B6: 3}
    for t, reg, val in regs:
        tt = t - k0
        R[reg] = val
        if reg == 0x100 and not val & 0x80:
            for c in range(6):
                if val >> c & 1:
                    hits.append((tt, c, (R.get(0x118 + c, 0) << 8) | R.get(0x110 + c, 0)))
        elif reg == 0x10 and val & 0x80 and not val & 0x01:
            bhits.append(tt)
        elif reg in fm_pan:
            v = fm_pan[reg]
            pan[v][0].append(tt); pan[v][1].append(val >> 6 & 3)
        elif 0x108 <= reg <= 0x10D:
            v = 7 + reg - 0x108
            pan[v][0].append(tt); pan[v][1].append(val >> 6 & 3)
        elif reg == 0x11:
            pan[13][0].append(tt); pan[13][1].append(val >> 6 & 3)
    count = {}
    for _, _, addr in hits:
        count[addr] = count.get(addr, 0) + 1
    pads = [a for a, _ in sorted(count.items(), key=lambda kv: -kv[1])[:8]]
    pidx = {a: i for i, a in enumerate(pads)}
    h = np.array([(t, c, pidx.get(a, -1)) for t, c, a in hits], dtype=np.float64).reshape(-1, 3)
    return {"hit_t": h[:, 0], "hit_ch": h[:, 1].astype(int), "hit_pad": h[:, 2].astype(int), "pads": pads,
            "b_t": np.array(bhits, dtype=np.float64),
            "pan": {v: (np.array(a, dtype=np.float64), np.array(b, dtype=np.int8)) for v, (a, b) in pan.items()}}


# ======================================================================================
# Extraction (moteur natif, balayage des commandes, détection de boucle)
# ======================================================================================

# --------------------------------------------------------------------------------------
# Moteur natif
# --------------------------------------------------------------------------------------
def dlog(msg):
    """Diagnostic log (ngt_studio.log next to the script, else in the temp folder). Never raises."""
    import time as _t
    for d in (HERE, tempfile.gettempdir()):
        try:
            with open(os.path.join(d, "ngt_studio.log"), "a", encoding="utf8") as fh:
                fh.write(_t.strftime("%H:%M:%S ") + msg + "\n")
            return
        except OSError:
            continue


def _clean_old_engines(keep):
    """Remove stale m1render_<crc>.exe left by previous versions of the script (never the one in use)."""
    for d in {HERE, os.path.dirname(keep)}:
        try:
            for fn in os.listdir(d):
                if re.fullmatch(r"m1render_[0-9a-f]{8}(\.exe)?", fn) and os.path.join(d, fn) != keep:
                    try:
                        os.remove(os.path.join(d, fn))
                    except OSError:
                        pass
        except OSError:
            pass


def _embedded_engine():
    """Extrait le moteur intégré au script (à côté du script, sinon dans un dossier de cache) et retourne son chemin, ou None."""
    import base64
    data = _ENGINE_B64.get("nt" if os.name == "nt" else sys.platform.startswith("linux") and "linux" or "")
    if not data:
        return None
    import lzma
    raw = lzma.decompress(base64.b85decode("".join(data.split())))
    tag = "%08x" % (zlib.crc32(raw) & 0xFFFFFFFF)
    # d'abord À CÔTÉ DU SCRIPT ; repli sur un dossier de cache si ce dossier n'est pas inscriptible
    dirs = [HERE, os.path.join(os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".cache"), "ngt_studio"),
            os.path.join(tempfile.gettempdir(), "ngt_studio")]
    for d in dirs:
        try:
            os.makedirs(d, exist_ok=True)
            p = os.path.join(d, "m1render_%s%s" % (tag, ".exe" if os.name == "nt" else ""))
            if not (os.path.isfile(p) and os.path.getsize(p) == len(raw)):
                tmp = p + ".%d.tmp" % os.getpid()
                with open(tmp, "wb") as f:
                    f.write(raw)
                os.chmod(tmp, 0o755)
                os.replace(tmp, p)
                _clean_old_engines(p)
            return p
        except OSError:
            continue
    return None


def find_binary():
    """Moteur : celui intégré au script (toujours en phase avec lui).  Un m1render(.exe) externe n'est utilisé que si la
    variable d'environnement NGT_ENGINE le désigne, ou en dernier recours : un vieux exécutable oublié à côté du script
    peut avoir une autre interface et ne rien produire."""
    forced = os.environ.get("NGT_ENGINE")
    if forced and os.path.isfile(forced):
        return forced
    p = _embedded_engine()
    if p:
        return p
    for q in (os.path.join(HERE, "m1render", EXE), os.path.join(HERE, EXE)):
        if os.path.isfile(q):
            return q
    return shutil.which("m1render")


def build_binary(log=print):
    src = os.path.join(HERE, "m1render")
    if not os.path.isdir(src):
        return None
    if shutil.which("g++") is None:
        log("g++ not found: build m1render by hand (see README.md).")
        return None
    srcs = ["m1render.cpp", "ymfm/ymfm_opn.cpp", "ymfm/ymfm_adpcm.cpp", "ymfm/ymfm_ssg.cpp"]
    out = os.path.join(src, EXE)
    log("Building m1render…")
    try:
        subprocess.run(["gcc", "-O2", "-c", "z80/z80.c", "-o", "z80.o"], cwd=src, check=True,
                       capture_output=True, text=True)
        subprocess.run(["g++", "-O2", "-std=c++17", "-I.", *srcs, "z80.o", "-o", EXE]
                       + (["-static", "-lshell32"] if os.name == "nt" else []), cwd=src, check=True,   # Unicode argv
                       capture_output=True, text=True)
    except subprocess.CalledProcessError as ex:
        log("Build failed:\n" + (ex.stderr or "")[-1500:])
        return None
    return out if os.path.isfile(out) else None


# --------------------------------------------------------------------------------------
# Lecture des jeux
# --------------------------------------------------------------------------------------
_VROM_RE = re.compile(r"(?:^|[-_.])v(\d{1,2})(?:\.[a-z0-9]+)?$")
_M1_RE = re.compile(r"(?:^|[-_.])m1(?:\.[a-z0-9]+)?$")


# ROM ADPCM-B séparées (zone ymsnd:adpcmb de la liste MAME neogeo.xml) : CRC32 -> position dans la ROM B.
# Reconnues par leur contenu, quel que soit le nom du fichier (sets MAME « v21 » ou dumps « .rom »).
_ADPCMB_CRC = {0x04A733D1: 0x0, 0x069C71ED: 0x100000, 0x232CFD04: 0x80000, 0x2EFD5ADA: 0x0, 0x30F53E54: 0x100000, 0x365F9011: 0x0, 0x426CD040: 0x0, 0x4999FB27: 0x0, 0x4E2CD7C3: 0x80000, 0x55E670B3: 0x0, 0x586F4CB2: 0x0, 0x5BA0F501: 0x180000, 0x776FA2A2: 0x80000, 0x7ABF113D: 0x0, 0x89FBB825: 0x180000, 0x8ED20A86: 0x0, 0x94092BCE: 0x0, 0x9A5F58D4: 0x80000, 0x9F3B4EDA: 0x0, 0xAB0D8368: 0x80000, 0xAC44B75A: 0x0, 0xB3E7EEEA: 0x100000, 0xD34960C6: 0x0, 0xDF468E28: 0x100000, 0xDF5B4EEB: 0x0, 0xF94AB5B7: 0x0}


def load_game(zip_path):
    """Renvoie dict(name, m1, vrom, vnames, va, vb, b_off) ou None si pas de M1/VROM.
    Les premiers jeux (Magician Lord, NAM-1975, Baseball Stars…) ont une ROM ADPCM-B séparée : v1x = ADPCM-A,
    v2x = ADPCM-B.  On garde alors les deux (va, vb) pour le moteur, et vrom = va (complétée au Mo) + vb, une V-ROM
    unifiée où les adresses ADPCM-B sont décalées de b_off (comme sur une cartouche à V-ROM commune)."""
    name = os.path.splitext(os.path.basename(zip_path))[0]
    with zipfile.ZipFile(zip_path) as z:
        m1s, vs = [], []
        for i in z.infolist():
            if i.is_dir():
                continue
            base = os.path.basename(i.filename).lower()
            if _M1_RE.search(base):
                m1s.append(i)
            else:
                m = _VROM_RE.search(base)
                if m:
                    vs.append((int(m.group(1)), i))
        if not m1s or not vs:
            return None
        # jeu de ROM « merged » : les clones sont dans des sous-dossiers (kof98.zip -> kof98h/...) ; leurs M1/V-ROM
        # ne doivent pas être mélangés à ceux du jeu (V-ROM concaténée fausse) : la racine du zip a la priorité
        root = lambda i: "/" not in i.filename.strip("/")
        if any(root(i) for i in m1s) and any(root(i) for _, i in vs):
            m1s = [i for i in m1s if root(i)]
            vs = [(n, i) for n, i in vs if root(i)]
        vs.sort(key=lambda t: (t[0], t[1].filename))
        m1 = z.read(sorted(m1s, key=lambda i: i.filename)[0])
        bs = [(_ADPCMB_CRC[i.CRC], i) for _, i in vs if i.CRC in _ADPCMB_CRC]
        if bs and len(bs) < len(vs):
            va = b"".join(z.read(i) for _, i in vs if i.CRC not in _ADPCMB_CRC)
            vb = bytearray(max(off + i.file_size for off, i in bs))
            for off, i in bs:
                vb[off:off + i.file_size] = z.read(i)
            b_off = -(-len(va) // MB) * MB
            return {"name": name, "m1": m1, "vrom": va.ljust(b_off, b"\x80") + bytes(vb), "va": va, "vb": bytes(vb),
                    "b_off": b_off, "vnames": [i.filename for _, i in vs]}
        if all(n >= 10 for n, _ in vs) and any(n // 10 == 2 for n, _ in vs) and any(n // 10 == 1 for n, _ in vs):
            va = b"".join(z.read(i) for n, i in vs if n // 10 == 1)
            vb = b"".join(z.read(i) for n, i in vs if n // 10 == 2)
            b_off = -(-len(va) // MB) * MB
            return {"name": name, "m1": m1, "vrom": va.ljust(b_off, b"\x80") + vb, "va": va, "vb": vb, "b_off": b_off,
                    "vnames": [i.filename for _, i in vs]}
        vrom = b"".join(z.read(i) for _, i in vs)
        return {"name": name, "m1": m1, "vrom": vrom, "va": vrom, "vb": None, "b_off": 0,
                "vnames": [i.filename for _, i in vs]}


# --------------------------------------------------------------------------------------
# Appel du moteur
# --------------------------------------------------------------------------------------
ENGINE_STATUS = {"err": ""}      # dernier incident du moteur natif (affiché si l'extraction ne trouve rien)


def _vb_path(vp):
    """ROM ADPCM-B séparée, écrite à côté de la ROM ADPCM-A (v.bin -> v_b.bin) quand le jeu en a une."""
    return os.path.splitext(vp)[0] + "_b.bin"


def run_m1(binary, m1p, vp, lo, hi, pre, boot=1.5, idle=3.0, tail=2.5, cap=6.0, keep="none",
           outdir=None, ev=False, delay=0.6, timeout=3600, post=None, stream=False):
    cmd = [binary, "--m1", m1p, "--va", vp] + (["--vb", _vb_path(vp)] if os.path.isfile(_vb_path(vp)) else []) + [
           "--sweep", str(lo), str(hi), "--boot", str(boot),
           "--idle", str(idle), "--tail", str(tail), "--cap", str(cap), "--keep", str(keep),
           "--outdir", (outdir or tempfile.gettempdir()).replace("\\", "/"), "--pre-delay", str(delay)]
    if pre:
        cmd += ["--pre", ",".join(str(p) for p in pre)]
    if post:
        cmd += ["--post", ",".join(str(p) for p in post)]
    if ev:
        cmd += ["--ev"]
    if stream:
        cmd += ["--stream"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout, **_NOWIN)
    except OSError as ex:                # exécutable bloqué (antivirus, droits, mauvaise architecture…)
        ENGINE_STATUS["err"] = f"cannot launch the engine ({ex})"
        return []
    except subprocess.TimeoutExpired:    # moteur bloqué : cette commande est perdue, pas tout le jeu
        ENGINE_STATUS["err"] = f"the engine did not answer within {timeout} s"
        dlog(f"run_m1 timeout: commands {lo:02X}-{hi:02X}")
        return []
    if r.returncode != 0:
        ENGINE_STATUS["err"] = f"the engine exited with code {r.returncode}: {(r.stderr or r.stdout or '').strip()[:300]}"
    rows = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                # Windows : le moteur écrit les chemins avec des « \ » non échappés (C:\Users\…) -> JSON invalide
                rows.append(json.loads(line.replace("\\", "/")))
            except ValueError:
                pass
    return rows


def sweep_parallel(binary, m1p, vp, pre, workers, lo=0, hi=255, **kw):
    chunks = [(a, min(a + 15, hi)) for a in range(lo, hi + 1, 16)]
    rows = []
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(run_m1, binary, m1p, vp, a, b, pre, **kw) for a, b in chunks]
        for f in futs:
            rows += f.result()
    return [r for r in rows if not r.get("silent")]


# Préambules testés (commandes envoyées avant chaque code testé). Le bon dépend du driver.
PRELUDES = [[], [3], [7], [8], [3, 7], [3, 8], [1], [1, 3], [1, 3, 7]]


def find_prelude(binary, m1p, vp, workers, log=print):
    best, best_score = [], -1
    for pre in PRELUDES:
        rows = sweep_parallel(binary, m1p, vp, pre, workers, boot=1.0, idle=1.5, tail=1.0, cap=2.5, delay=0.3)
        score = len(rows)
        log(f"   prelude {pre or 'none'}: {score} audible commands")
        if score > best_score:
            best, best_score = pre, score
    return best, best_score


# --------------------------------------------------------------------------------------
# Détection de boucle (à partir du journal d'événements YM : t, reg, val)
# --------------------------------------------------------------------------------------


def _window_hashes(tok, K):
    B = np.uint64(0x9E3779B97F4A7C15)
    n = len(tok)
    pref = np.zeros(n + 1, dtype=np.uint64)
    acc = np.uint64(0)
    with np.errstate(over="ignore"):
        for i in range(n):
            acc = acc * B + np.uint64(int(tok[i]) + 1)
            pref[i + 1] = acc
        BK = np.uint64(1)
        for _ in range(K):
            BK = BK * B
        return pref[K:] - pref[:-K] * BK


MIN_LOOP_S = 15.0  # une 'boucle' plus courte est une répétition locale (note tenue, roulement), pas la boucle du morceau


def detect_loop(ev, min_events=64, K=48):
    """None, ou dict avec loop_start_t / loop_end_t / period_t (en échantillons)."""
    # registres de contrôle réécrits par l'IRQ du driver : ils dépendent de la phase du timer, pas de la musique
    keep = ~(((ev["reg"] >= 0x24) & (ev["reg"] <= 0x27)) | (ev["reg"] == 0x1C))
    ev = ev[keep]
    n = len(ev)
    if n < max(min_events, 3 * K):
        return None
    tok = (ev["reg"].astype(np.uint32) << 8) | ev["val"].astype(np.uint32)
    t = ev["t"].astype(np.int64)
    H = _window_hashes(tok, K)
    m = len(H)
    cands = set()
    for frac in (0.75, 0.6, 0.9, 0.5):
        a = int(m * frac)
        if 0 < a < m:
            for b in np.nonzero(H[:a] == H[a])[0]:
                cands.add(int(a - b))
    for P in sorted(cands):
        if P < K or P > n // 2:
            continue
        eq = tok[: n - P] == tok[P:]
        if not eq[-1]:
            continue
        bad = np.nonzero(~eq)[0]
        s = int(bad[-1] + 1) if len(bad) else 0
        if (n - P) - s < P:           # il faut au moins une période complète de confirmation
            continue
        dt = t[P + s: n] - t[s: n - P]
        if len(dt) == 0:
            continue
        spread = int(dt.max() - dt.min())
        period = int(np.median(dt))
        if period < MIN_LOOP_S * RATE:
            continue
        return {"loop_start_t": int(t[s]), "loop_end_t": int(t[s]) + period, "period_t": period,
                "timing_spread_samples": spread,
                "confidence": "good" if spread <= 120 else "fair"}
    return None


def detect_loop_onsets(ev, min_match=0.98):
    """Détection de secours, tolérante : on ne compare que les déclenchements de notes (key-on FM, ADPCM-A),
    pas les écritures de registres (enveloppes/vibrato logiciels dont la phase dérive avec le timer)."""
    sel = ((ev["reg"] == 0x28) & ((ev["val"] >> 4) != 0)) | \
          ((ev["reg"] == 0x100) & (ev["val"] != 0) & ((ev["val"] & 0x80) == 0))
    on = ev[sel]
    n = len(on)
    if n < 60:
        return None
    tok = (on["reg"].astype(np.uint32) << 8) | on["val"].astype(np.uint32)
    t = on["t"].astype(np.int64)
    for P in range(20, n // 2 + 1):
        L = n - P
        eq = tok[:L] == tok[P:]
        if eq.mean() < min_match:
            continue
        dt = t[P:] - t[:L]
        period = int(np.median(dt))
        if period < MIN_LOOP_S * RATE:
            continue
        # début de boucle : premier indice à partir duquel la concordance reste ≥ 99,5 %
        suf = np.cumsum(eq[::-1])[::-1] / (L - np.arange(L))
        ok = np.nonzero(suf >= 0.995)[0]
        st = int(ok[0]) if len(ok) else 0
        return {"loop_start_t": int(t[st]), "loop_end_t": int(t[st]) + period, "period_t": period,
                "timing_spread_samples": int(np.percentile(np.abs(dt - period), 95)),
                "confidence": "fair (note triggers)"}
    return None


def detect_loop_samples(ev, tol_s=0.05):
    """Musique faite de longs échantillons ADPCM (Pulstar, Breakers Revenge…) : peu de déclenchements, trop peu pour les
    autres détecteurs.  On cherche le plus petit motif de déclenchements (voie, adresses début/fin) qui se répète à
    l'identique et à intervalles réguliers jusqu'à la fin du rendu, au moins deux fois."""
    st, trig = {}, []
    for t, reg, val in zip(ev["t"].tolist(), ev["reg"].tolist(), ev["val"].tolist()):
        st[reg] = val
        if reg == 0x100 and val and not val & 0x80:
            for ch in range(6):
                if val >> ch & 1:
                    trig.append((t, ("A", ch, st.get(0x110 + ch, 0), st.get(0x118 + ch, 0), st.get(0x120 + ch, 0),
                                       st.get(0x128 + ch, 0))))
        elif reg == 0x10 and val & 0x80:
            trig.append((t, ("B", st.get(0x12, 0), st.get(0x13, 0), st.get(0x14, 0), st.get(0x15, 0))))
    n = len(trig)
    if n < 3 or n > 600:                                        # au-delà : musique à notes, autres détecteurs
        return None
    tol = tol_s * RATE
    for s0 in range(0, n - 2):
        for p in range(1, (n - s0) // 2 + 1):
            period = trig[s0 + p][0] - trig[s0][0]
            if period < MIN_LOOP_S * RATE:
                continue
            ok = all(trig[k][1] == trig[k + p][1] and abs(trig[k + p][0] - trig[k][0] - period) <= tol
                     for k in range(s0, n - p))
            if ok:
                return {"loop_start_t": int(trig[s0][0]), "loop_end_t": int(trig[s0][0] + period), "period_t": int(period),
                        "timing_spread_samples": 0, "confidence": "fair (sample triggers)"}
    return None


def find_loop(ev):
    """Combine les deux détecteurs : si les périodes concordent, on garde le début de boucle le plus précoce
    (le détecteur exact ne remonte la répétition que sur la fin du rendu, donc il peut situer le début trop tard).
    En dernier recours : boucle de musique faite d'échantillons longs."""
    a, b = detect_loop(ev), detect_loop_onsets(ev)
    if a and b:
        if abs(a["period_t"] - b["period_t"]) <= 0.02 * a["period_t"]:
            return b if b["loop_start_t"] < a["loop_start_t"] else a
        return a if a["period_t"] >= b["period_t"] else b
    return a or b or detect_loop_samples(ev)


# --------------------------------------------------------------------------------------
# Traitement d'un jeu
# --------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------
# Analyse : musique, jingle ou bruitage ?
# --------------------------------------------------------------------------------------
def track_features(regs, k0, dur_s):
    """Mesures tirées des écritures de registres (t absolu, reg, val) de la zone musicale [k0, k0+dur]."""
    end = k0 + int(dur_s * RATE)
    fm_on, ssg_on, a_trig, b_trig = 0, 0, 0, 0
    fm_ch, ssg_ch = set(), set()
    pitches = set()
    hi = {}
    ssg_vol = {8: 0, 9: 0, 10: 0}
    ssg_per = {}
    for t, reg, val in regs:
        if t < k0 or t > end:
            continue
        if reg == 0x28:
            ch, ops = val & 7, val >> 4
            if ops and ch in (1, 2, 5, 6):
                fm_on += 1; fm_ch.add(ch)
        elif 0xA4 <= reg <= 0xA6 or 0x1A4 <= reg <= 0x1A6:
            hi[reg] = val & 0x3F
        elif 0xA0 <= reg <= 0xA2 or 0x1A0 <= reg <= 0x1A2:
            pitches.add((reg & 0x103, hi.get(reg + 4, 0), val))
        elif 0x08 <= reg <= 0x0A:
            was, now = ssg_vol[reg], val & 0x1F
            if now and not was:
                ssg_on += 1; ssg_ch.add(reg)
            ssg_vol[reg] = now
        elif 0x00 <= reg <= 0x05:
            ssg_per[reg] = val
            pitches.add(("s", reg & 6, val, ssg_per.get(reg ^ 1, 0)))
        elif reg == 0x100 and not val & 0x80:
            a_trig += bin(val & 0x3F).count("1")
        elif reg == 0x10 and val & 0x80:
            b_trig += 1
    tonal = fm_on + ssg_on
    # musique en échantillons longs (Visco : Breakers Revenge…) : durée des échantillons ADPCM joués
    pcm_secs, pcm_long, dn = 0.0, 0, 0
    for i, kind, ch, st, en in _sample_uses(regs):
        t = regs[i][0]
        if t < k0 or t > end or en < st or en - st > (16 << 20):
            continue
        if kind == "A":
            sec = (en - st + 1) * 2 / 18518.0                   # ADPCM-A : 2 échantillons par octet, 18,5 kHz
        else:
            for tt, r, v in regs[max(0, i - 64):i]:             # Delta-N (débit) ADPCM-B
                if r == 0x19:
                    dn = (dn & 0xFF00) | v
                elif r == 0x1A:
                    dn = (dn & 0x00FF) | (v << 8)
            sec = (en - st + 1) * 2 / max(55555.0 * (dn or 1) / 65536.0, 1000.0)
        sec = min(sec, (end - t) / RATE)                        # pas au-delà de la fin du morceau
        pcm_secs += sec
        pcm_long += sec >= 2.0
    return {"dur": dur_s, "tonal": tonal, "voices": len(fm_ch) + len(ssg_ch), "pitches": len(pitches),
            "pcm": a_trig + b_trig, "rate": tonal / max(dur_s, 1e-6), "pcm_secs": round(pcm_secs, 1),
            "pcm_long": pcm_long}


def _trigger_tokens(regs, t0=None, t1=None):
    """Suite des déclenchements avec leur hauteur / échantillon : (key-on FM, voie, F-number, bloc),
    (ADPCM-A, voie, adresse de début), (ADPCM-B, adresse).  Sert à reconnaître deux commandes qui jouent le même
    morceau (la suite ne dépend pas du décalage dans le temps), sans confondre deux jingles au même rythme."""
    st, out, ssg = {}, [], {}
    for t, reg, val in regs:
        if (t0 is not None and t < t0) or (t1 is not None and t >= t1):
            st[reg] = val
            if 0x08 <= reg <= 0x0A:
                ssg[reg] = val & 0x1F
            continue
        st[reg] = val
        if reg == 0x28 and val >> 4:
            ch = val & 7
            base = (0x100 if ch & 4 else 0) + (ch & 3)                # A0+n / A4+n de la voie n (port B si bit 2)
            out.append(("F", ch, val >> 4, st.get(0xA0 + base, 0), st.get(0xA4 + base, 0)))
        elif reg == 0x100 and val and not val & 0x80:
            out.append(("A", val, tuple(st.get(0x110 + c, 0) | st.get(0x118 + c, 0) << 8 for c in range(6) if val >> c & 1)))
        elif reg == 0x10 and val & 0x80:
            out.append(("B", st.get(0x12, 0), st.get(0x13, 0)))
        elif 0x08 <= reg <= 0x0A and val & 0x1F and not ssg.get(reg):
            c = (reg - 8) * 2
            out.append(("S", reg, st.get(c, 0), st.get(c + 1, 0)))  # note SSG : volume 0 -> non nul, période
        if 0x08 <= reg <= 0x0A:
            ssg[reg] = val & 0x1F
    return out


KIND_EN = {"musique": "music", "jingle": "jingle", "bruitage": "SFX"}


def classify_track(f, looped=False):
    """-> 'musique' | 'jingle' | 'bruitage'.  Règles simples sur les mesures de track_features."""
    if f["tonal"] >= 24 and f["voices"] >= 2 and f["pitches"] >= 6 and (f["dur"] >= 20 or looped):
        return "musique"
    # musique jouée en échantillons longs (pas de notes FM/SSG) : les échantillons couvrent l'essentiel du morceau
    if f.get("pcm_long", 0) >= 1 and f.get("pcm_secs", 0) >= 0.6 * min(f["dur"], 300) and (f["dur"] >= 20 or looped):
        return "musique"
    if f["tonal"] >= 6 and f["voices"] >= 1 and f["pitches"] >= 3 and f["dur"] >= 2.5:
        return "jingle"
    return "bruitage"


def write_wav(path, pcm):
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.astype("<i2").tobytes())


def process_game(binary, zip_path, outroot, opts, log=print, stop=lambda: False):
    g = load_game(zip_path)
    name = os.path.splitext(os.path.basename(zip_path))[0]
    res = {"game": name, "tracks": [], "note": ""}
    ENGINE_STATUS["err"] = ""                       # un incident d'un jeu précédent ne doit pas être attribué à celui-ci
    if g is None:
        res["note"] = "no M1/VROM"
        return res
    if g["m1"][:1] != b"\xf3":
        log(f"[{name}] WARNING: the M1 does not start with DI (0xF3): possibly encrypted (CMC50), not supported.")
    workers = opts.get("workers", max(1, (os.cpu_count() or 2) - 1))
    keep_mode = opts.get("keep", "auto")            # auto : musiques + jingles ; music : musiques seules ; all : tout
    tmp = tempfile.mkdtemp(prefix="ngripper_")
    try:
        m1p, vp = os.path.join(tmp, "m1.bin"), os.path.join(tmp, "v.bin")
        open(m1p, "wb").write(g["m1"])
        open(vp, "wb").write(g["va"])
        if g["vb"]:
            open(_vb_path(vp), "wb").write(g["vb"])
            log(f"[{name}] separate ADPCM-B ROM: A {len(g['va'])/1048576:.1f} MiB + B {len(g['vb'])/1048576:.1f} MiB")
        log(f"[{name}] M1 {len(g['m1'])//1024} KiB, VROM {len(g['vrom'])/1048576:.1f} MiB ({', '.join(g['vnames'])})")

        if opts.get("prelude") not in (None, "auto"):
            pre = list(opts["prelude"])
        else:
            log(f"[{name}] looking for the driver unlock prelude…")
            pre, sc = find_prelude(binary, m1p, vp, workers, log)
            if sc <= 0:
                why = ENGINE_STATUS["err"]
                if why:
                    log(f"[{name}] ENGINE PROBLEM: {why}")
                    res["note"] = "native engine failed: " + why
                else:
                    res["note"] = "no audible command (driver not recognised or M1 encrypted)"
                return res
        res["prelude"] = pre
        log(f"[{name}] prelude selected: {pre or 'none'}")
        if stop():
            return res

        rows = sweep_parallel(binary, m1p, vp, pre, workers, boot=1.5, idle=3.0, tail=2.5, cap=6.0)
        cands = [r for r in rows if (not r["ended"]) or r["length_s"] >= 2.5]
        tasks = [(r["cmd"], ()) for r in cands]
        log(f"[{name}] 1-byte commands: {len(rows)} audible, {len(cands)} candidates to analyse")

        def render_one(task):
            c, args = task
            sub = os.path.join(tmp, "r_%02X_%s" % (c, "_".join("%02X" % a for a in args) or "x"))
            os.makedirs(sub, exist_ok=True)
            for cap in (150.0, 300.0):
                if stop():
                    return None
                out = run_m1(binary, m1p, vp, c, c, pre, boot=1.5, idle=3.0, tail=2.5, cap=cap, keep="all",
                             outdir=sub, ev=True, post=list(args) or None, stream=True)
                if not out:
                    return None
                info = out[0]
                rawp, evp = os.path.join(sub, f"cmd_{c:02X}.raw"), os.path.join(sub, f"cmd_{c:02X}.ev")
                stp = os.path.join(sub, f"cmd_{c:02X}.stream")
                if info["ended"]:
                    return {"cmd": c, "args": args, "info": info, "loop": None, "ended": True, "raw": rawp, "stream": stp}
                evs = np.fromfile(evp, dtype=EV_DTYPE)
                loop = find_loop(evs)
                if loop and "sample triggers" in loop.get("confidence", ""):
                    # contrôle sur le son : les 5 s après le début de boucle doivent revenir à l'identique après une période
                    try:
                        x = np.fromfile(rawp, dtype="<i2").reshape(-1, 2).mean(1)
                        a0, b0, w = loop["loop_start_t"], loop["loop_end_t"], RATE * 5
                        if b0 + w > len(x) or np.corrcoef(x[a0:a0 + w], x[b0:b0 + w])[0, 1] < 0.9:
                            loop = None
                    except Exception:
                        loop = None
                if loop:
                    return {"cmd": c, "args": args, "info": info, "loop": loop, "ended": False, "raw": rawp, "stream": stp}
            return {"cmd": c, "args": args, "info": info, "loop": None, "ended": False, "raw": rawp, "stream": stp}

        done = []
        with cf.ThreadPoolExecutor(max_workers=workers) as ex:
            for item in ex.map(render_one, tasks):
                if item:
                    done.append(item)

        def _dur(it):
            return (it["loop"]["loop_end_t"] / RATE) if it["loop"] else (it["info"]["length_s"])

        def _analyse(it):
            """Mesure et classe une piste d'après ses écritures de registres : musique, jingle ou bruitage."""
            raw = open(it["stream"], "rb").read()
            k0 = int(np.frombuffer(raw[:4], dtype="<u4")[0])
            regs = decode_registers(np.frombuffer(raw[4:], dtype=EV_DTYPE))
            it["feat"] = track_features(regs, k0, _dur(it))
            it["kind"] = classify_track(it["feat"], bool(it["loop"]))
            # empreinte musicale indépendante du décalage dans le temps : suite des déclenchements (notes FM,
            # échantillons ADPCM) ; deux commandes qui lancent le même morceau donnent la même suite
            toks = _trigger_tokens(regs, k0)[:400]                # à partir du début du son (sans le prélude)
            it["tok"] = hashlib.sha1(repr(toks).encode()).hexdigest() if len(toks) >= 12 else None
            # boucle : suite des déclenchements sur un tour de boucle (un bruitage joué au début par-dessus le même
            # morceau ne change pas la boucle -> doublon reconnu)
            it["ltok"] = None
            if it["loop"]:
                a0, b0 = k0 + it["loop"]["loop_start_t"], k0 + it["loop"]["loop_end_t"]
                lt = _trigger_tokens(regs, a0, b0)
                if len(lt) >= 12:
                    it["ltok"] = (round((b0 - a0) / RATE, 1), hashlib.sha1(repr(lt).encode()).hexdigest())
        for it in done:
            _analyse(it)
        if sum(1 for it in done if it["kind"] == "musique") < 3:
            # Certains drivers (ex. Windjammers) attendent un 2e octet (numéro de morceau) après la commande.
            # On les cherche si le mode 1 octet a donné moins de 3 morceaux de durée suffisante.
            if not stop():
                log(f"[{name}] fewer than 3 tunes: looking for 2-byte commands (command + tune number)…")
                hot, sig = set(), {}
                for arg in (1, 2, 3):
                    rr = sweep_parallel(binary, m1p, vp, pre, workers, lo=0, hi=63, boot=1.0, idle=1.5, tail=1.0,
                                        cap=3.0, post=[arg])
                    for r in rr:
                        if not r["ended"]:
                            hot.add(r["cmd"])
                        sig.setdefault(r["cmd"], []).append((arg, r["peak"], r["rms"]))
                hot -= {c for c, _ in tasks}
                # commandes équivalentes (masque de bits dans le driver) : on ne garde que la première
                uniq, seen_sig = set(), set()
                for c in sorted(hot):
                    k = tuple(sorted(sig.get(c, [])))
                    if k not in seen_sig:
                        seen_sig.add(k)
                        uniq.add(c)
                hot = uniq
                tasks2 = []
                log(f"[{name}]   argument-sensitive commands: {sorted('%02X' % c for c in hot)}")
                for c in sorted(hot):
                    if stop():
                        break
                    found = 0
                    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
                        futs = {a: ex.submit(run_m1, binary, m1p, vp, c, c, pre, boot=1.0, idle=1.5, tail=1.0,
                                             cap=4.0, post=[a]) for a in range(0, 128)}
                        for a, f in futs.items():
                            for r in f.result():
                                if not r.get("silent") and not r["ended"]:
                                    tasks2.append((c, (a,)))
                                    found += 1
                    log(f"[{name}]   cmd {c:02X} + argument: {found} long sounds")
                for item in (ex2 := cf.ThreadPoolExecutor(max_workers=workers)).map(render_one, tasks2):
                    if item:
                        _analyse(item)
                        done.append(item)
                ex2.shutdown()
                # les commandes c et c|0x20 (masque 5 bits) donnent la même chose : la déduplication audio s'en charge

        # pistes courtes (< min_len s, une boucle comprise) : par défaut ignorées, la question est posée pendant
        # l'extraction (interface : fenêtre ; ligne de commande : clavier).  Une musique qui boucle peut être courte
        # (AoF2 piste 5 : 58 s par tour) : la question le signale et propose de garder celles-là.
        min_len = float(opts.get("min_len", 45) or 0)

        def _wanted(it):
            return not ((it["kind"] == "bruitage" and keep_mode != "all") or (it["kind"] == "jingle" and keep_mode == "music"))
        short = [it for it in done if min_len > 0 and _wanted(it) and _dur(it) < min_len]
        policy = opts.get("short", "ask")
        if short and policy == "ask":
            ask = opts.get("ask_short")
            n_loop = sum(1 for it in short if it["loop"])
            policy = ask(name, len(short), n_loop, min_len) if ask else "loops"
            if policy not in ("skip", "loops", "keep"):
                policy = "loops"
            opts["short_last"] = policy
        if short:
            log(f"[{name}] {len(short)} track(s) shorter than {min_len:.0f} s: "
                + {"skip": "skipped", "loops": "skipped unless they loop", "keep": "kept"}.get(policy, policy))

        def _load(it):
            pcm = np.fromfile(it["raw"], dtype="<i2")
            if it["loop"]:
                return pcm[:it["loop"]["loop_end_t"] * 2], it["loop"]["loop_end_t"] / RATE
            n = trim_tail(pcm)                          # piste sans boucle : silence final retire (1 s gardee)
            it["trimmed_s"] = (len(pcm) // 2 - n) / RATE
            pcm = pcm[:n * 2]
            return pcm, len(pcm) / 2 / RATE

        def _plan(extra=()):
            """Pistes gardées (filtres + doublons), sans rien écrire.  extra : réductions supplémentaires quand il y a
            plus de JB_MAX_NUM pistes.  -> (liste de (it, lab, dur), messages du journal)."""
            seen, seen_feat, seen_tok, keep, msgs = {}, {}, {}, [], []
            short_lim = min_len if min_len > 0 else 45.0
            for it in sorted(done, key=lambda x: (x["cmd"], x["args"])):
                lab = "%02X" % it["cmd"] + "".join("_%02X" % a for a in it["args"])
                pcm, dur = _load(it)
                ft = it["feat"]
                fdesc = f"{ft['tonal']} notes, {ft['voices']} melodic voice(s), {ft['pcm']} samples played"
                if it["kind"] == "bruitage" and (keep_mode != "all" or "sfx" in extra):
                    msgs.append(f"[{name}] cmd {lab} : {dur:.1f} s, SFX / ambience ({fdesc}), skipped"
                                + (" (more than %d tracks)" % JB_MAX_NUM if keep_mode == "all" else ""))
                    continue
                if it["kind"] == "jingle" and (keep_mode == "music" or "jingle" in extra):
                    msgs.append(f"[{name}] cmd {lab} : {dur:.1f} s, jingle ({fdesc}), skipped"
                                + (" (more than %d tracks)" % JB_MAX_NUM if keep_mode != "music" else ""))
                    continue
                if min_len > 0 and dur < min_len and (policy == "skip" or (policy == "loops" and not it["loop"])):
                    msgs.append(f"[{name}] cmd {lab} : {dur:.1f} s, shorter than {min_len:.0f} s, skipped")
                    continue
                if dur < short_lim and (("short_once" in extra and not it["loop"]) or ("short_loop" in extra and it["loop"])):
                    msgs.append(f"[{name}] cmd {lab} : {dur:.1f} s, shorter than {short_lim:.0f} s"
                                f"{' (loops)' if it['loop'] else ''}, skipped (more than {JB_MAX_NUM} tracks)")
                    continue
                if opts.get("normalize"):
                    peak = int(np.abs(pcm.astype(np.int32)).max()) or 1
                    gain = min(32767 * 10 ** (-1 / 20) / peak, 32.0)
                    pcm = np.clip(np.round(pcm.astype(np.float64) * gain), -32768, 32767).astype("<i2")
                # même suite de notes : doublon seulement si la durée concorde aussi (deux pistes aux mêmes notes mais
                # de durées différentes, ex. Magician Lord E9 / EA, diffèrent par autre chose : instruments, enveloppes…)
                dup = next((seen_tok[k][0] for k in (it.get("tok"), it.get("ltok"))
                            if k and k in seen_tok and abs(seen_tok[k][1] - dur) <= max(1.0, 0.03 * dur)), None)
                if dup:                                         # même suite de notes / même boucle qu'une piste gardée
                    msgs.append(f"[{name}] cmd {lab} same as cmd {dup}: skipped")
                    continue
                fsig = (round(dur, 1), ft["tonal"], ft["pitches"], ft["pcm"])  # même musique appelée par deux commandes
                if fsig in seen_feat:
                    msgs.append(f"[{name}] cmd {lab} same as cmd {seen_feat[fsig]}: skipped")
                    continue
                seen_feat[fsig] = lab
                key = hashlib.sha1(pcm[: RATE * 2 * 20].tobytes()).hexdigest()
                if key in seen:
                    msgs.append(f"[{name}] cmd {lab} same as cmd {seen[key]}: skipped")
                    continue
                seen[key] = lab
                for k in (it.get("tok"), it.get("ltok")):
                    if k:
                        seen_tok.setdefault(k, (lab, dur))
                keep.append((it, lab, dur))
            return keep, msgs

        # 99 pistes au plus par jeu (numéros sur 2 chiffres dans le jukebox) : on retire dans l'ordre les bruitages,
        # les pistes courtes qui ne bouclent pas, les jingles, puis les pistes courtes qui bouclent ; sinon le jeu
        # n'est pas écrit.
        keep, msgs = _plan()
        extra = []
        for step, what in (("sfx", "SFX"), ("short_once", "short tracks that do not loop"), ("jingle", "jingles"),
                           ("short_loop", "short looping tracks")):
            if len(keep) <= JB_MAX_NUM:
                break
            n0 = len(keep)
            extra.append(step)
            keep, msgs = _plan(extra)
            if len(keep) < n0:
                log(f"[{name}] {n0} tracks, more than {JB_MAX_NUM}: {what} removed -> {len(keep)} tracks")
        for m in msgs:
            log(m)
        if len(keep) > JB_MAX_NUM:
            log(f"[{name}] STOPPED: {len(keep)} music tracks remain after removing SFX, jingles and short tracks; "
                f"a game can have at most {JB_MAX_NUM}. Nothing written for this game.")
            res["note"] = f"stopped: {len(keep)} tracks, more than {JB_MAX_NUM} even without SFX, jingles and short tracks"
            return res

        tno = 0
        pending = []
        gdir = os.path.join(outroot, name)
        os.makedirs(gdir, exist_ok=True)
        for it, lab, dur in keep:
            c = it["cmd"]
            pcm, _ = _load(it)
            peak0 = int(np.abs(pcm.astype(np.int32)).max()) if len(pcm) else 0
            if opts.get("normalize"):
                # normalisation numérique : gain unique par piste, crête ramenée à -1 dBFS, sans écrêtage
                peak = int(np.abs(pcm.astype(np.int32)).max()) or 1
                gain = min(32767 * 10 ** (-1 / 20) / peak, 32.0)
                pcm = np.clip(np.round(pcm.astype(np.float64) * gain), -32768, 32767).astype("<i2")
            if it.get("trimmed_s", 0) >= 1.0:
                log(f"[{name}] cmd {lab} : {it['trimmed_s']:.1f} s of silence at the end removed")
            tno += 1
            title = game_title(name, opts.get("titles"), online=True)
            trackname = f"{title} - Track {tno:02d}"
            stem = re.sub(r'[<>:"/\\|?*]', "_", trackname)
            if opts.get("raw"):
                pcm.tofile(os.path.join(gdir, stem + ".raw"))
            # flux de registres + échantillons réduits
            pe = np.frombuffer(open(it["stream"], "rb").read()[4:], dtype=EV_DTYPE)
            k0 = int(np.frombuffer(open(it["stream"], "rb").read()[:4], dtype="<u4")[0])
            nsamp = len(pcm) // 2
            pe = pe[pe["t"] < k0 + nsamp]
            regs = decode_registers(pe)
            nmeta = {"rate": RATE, "k0": k0, "length_samples": nsamp, "peak": peak0, "track": tno, "cmd": c,
                     "arg": (it["args"][-1] if it["args"] else None), "name": trackname, "regs": regs,
                     "loop_start": (k0 + it["loop"]["loop_start_t"]) if it["loop"] else None,
                     "loop_end": (k0 + it["loop"]["loop_end_t"]) if it["loop"] else None}
            pending.append(nmeta)
            meta = {"game": name, "title": title, "track": tno, "name": trackname, "cmd": c, "args": list(it["args"]), "prelude": pre, "format": "PCM signed 16-bit little-endian stereo",
                    "sample_rate": RATE, "channels": 2, "duration_s": round(dur, 2),
                    "source": "emulation Z80+YM2610 (M1 + VROM)", "normalized": bool(opts.get("normalize")),
                    "ends_by_itself": bool(it["ended"])}
            meta["kind"] = it["kind"]
            if it["loop"]:
                lp = it["loop"]
                meta.update({"loop_start_sample": lp["loop_start_t"], "loop_end_sample": lp["loop_end_t"],
                             "loop_start_s": round(lp["loop_start_t"] / RATE, 2),
                             "loop_end_s": round(lp["loop_end_t"] / RATE, 2),
                             "loop_confidence": lp["confidence"]})
            else:
                meta["loop"] = None if it["ended"] else "not detected (longer than the render cap)"
                meta["ends_by_itself"] = bool(it["ended"])
            if opts.get("raw"):
                json.dump(meta, open(os.path.join(gdir, stem + ".json"), "w", encoding="utf-8"), indent=2,
                          ensure_ascii=False)
            if opts.get("wav"):
                write_wav(os.path.join(gdir, stem + ".wav"), pcm)
            res["tracks"].append(meta)
            tag = (f"loop {meta['loop_start_s']}→{meta['loop_end_s']} s ({meta['loop_confidence']})"
                   if it["loop"] else ("ends by itself" if it["ended"] else "loop not detected"))
            log(f"[{name}] cmd {lab} : {dur:6.1f} s, {KIND_EN.get(it['kind'], it['kind'])}, {tag}")
        # un seul fichier .ngt pour le jeu : échantillons communs + flux de toutes les pistes
        title = game_title(name, opts.get("titles"), online=True)
        if not pending:
            res["note"] = "no track exported"
            return res
        regs_new, blob, red = reduce_samples_multi([p["regs"] for p in pending], g["vrom"], b_off=g["b_off"])
        for p, r in zip(pending, regs_new):
            p["regs"] = r
        ngt_bytes = pack_game(pending, blob, name, title)
        ngt_file = re.sub(r'[<>:"/\\|?*]', "_", title) + ".ngt"
        open(os.path.join(gdir, ngt_file), "wb").write(ngt_bytes)
        cat = {"game": name, "title": title, "format": "NGT2", "file": ngt_file, "ngt_bytes": len(ngt_bytes),
               "samples_bytes": len(blob), "rate": RATE, "channels": 2, "tracks": [
                   {"track": m["track"], "name": m["name"], "kind": m.get("kind"),
                    "cmd": m["cmd"], "args": m["args"], "duration_s": m["duration_s"],
                    "loop_start_s": m.get("loop_start_s"), "loop_end_s": m.get("loop_end_s")} for m in res["tracks"]]}
        json.dump(cat, open(os.path.join(gdir, "catalog.json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        res["note"] = f"{len(res['tracks'])} tracks in {ngt_file} ({len(ngt_bytes)/1e6:.1f} MB, shared samples {len(blob)/1e6:.1f} MB)"
        return res
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def scan_dir(src, outroot, opts, log=print, stop=lambda: False, on_result=None):
    binary = find_binary() or build_binary(log)
    if not binary:
        raise RuntimeError("m1render engine not found and cannot be built (see README.md)")
    log(f"Engine used: {binary}")
    # dossiers temporaires laissés par une extraction interrompue de force (plus de 6 h) : peuvent peser des Go
    for d in glob.glob(os.path.join(tempfile.gettempdir(), "ngripper_*")) + glob.glob(os.path.join(tempfile.gettempdir(), "ngt_lz_*")):
        try:
            if time.time() - os.path.getmtime(d) > 6 * 3600:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass
    zips = ([src] if os.path.isfile(src) else
            sorted(os.path.join(src, f) for f in os.listdir(src) if f.lower().endswith(".zip")))
    out = []
    for n, z in enumerate(zips, 1):
        if stop():
            break
        try:
            r = process_game(binary, z, outroot, opts, log, stop)
        except Exception as ex:
            r = {"game": os.path.basename(z), "tracks": [], "note": f"error: {ex}"}
            log(f"[{os.path.basename(z)}] ERROR: {ex}")
        out.append(r)
        if on_result:
            on_result(r, n, len(zips))
    return out


# ======================================================================================
# Lecture : rejeu, normalisation, boucle, voies
# ======================================================================================
# ------------------------------------------------------------------ moteur
def find_engine():
    p = find_binary()
    if not p:
        raise RuntimeError("m1render engine not found (no built-in engine for this platform; put m1render(.exe) next to the script)")
    return p


def load_track(path, idx=0):
    """-> (meta, regs, blob commun) de la piste idx (0-based) d'un fichier de jeu ; CRC vérifié."""
    return unpack(ngt_data(path), idx, True)


SIL_LEVEL = 64          # |echantillon| < 64 (environ -54 dBFS) : silence
SIL_KEEP = 1.0          # secondes gardees apres le dernier son (fin naturelle des notes)


def trim_tail(pcm, rate=None):
    """pcm int16 stéréo entrelacé (ou (n, 2)) -> nombre d'échantillons (par canal) à garder : jusqu'au dernier son
    (au-dessus de SIL_LEVEL) + SIL_KEEP s.  Le moteur s'arrête après plusieurs secondes sans activité : sans cela,
    une piste qui ne boucle pas finit par un blanc que le jukebox jouait avant d'enchaîner."""
    rate = rate or RATE
    a = np.abs(np.asarray(pcm).reshape(-1, 2).astype(np.int32)).max(1)
    nz = np.flatnonzero(a >= SIL_LEVEL)
    if not len(nz):
        return len(a)
    return int(min(len(a), nz[-1] + 1 + int(SIL_KEEP * rate)))


def render_track(path, idx=0, engine=None, loaded=None):
    """Rejoue une piste -> (meta, pcm int16 stéréo (n,2) à 55944 Hz)."""
    import time as _t
    t0 = _t.time()
    meta, regs, blob = loaded or load_track(path, idx)
    engine = engine or find_engine()
    secs = meta["length_samples"] / meta["rate"]
    with tempfile.TemporaryDirectory() as tmp:
        base = os.path.join(tmp, "t")
        open(base + ".stream", "wb").write(regs_to_port_stream(regs, meta["k0"]))
        open(os.path.join(tmp, "v.bin"), "wb").write(blob)
        dlog(f"render start: {os.path.basename(path)} #{idx} {secs:.1f}s engine={engine}")
        try:
            r = subprocess.run([engine, "--va", os.path.join(tmp, "v.bin"), "--replay", base,
                                "--replay-out", base + ".raw", "--replay-len", f"{secs:.6f}"],
                               capture_output=True, text=True, errors="replace", timeout=180, stdin=subprocess.DEVNULL, **_NOWIN)
        except subprocess.TimeoutExpired:
            dlog("render TIMEOUT (engine did not answer within 180 s)")
            raise RuntimeError("the m1render engine did not answer within 180 s (antivirus blocking it?)")
        if r.returncode != 0:
            dlog(f"render FAILED rc={r.returncode}: {(r.stderr or r.stdout)[-200:]}")
            raise RuntimeError("replay failed: " + (r.stderr or r.stdout)[-300:])
        pcm = np.fromfile(base + ".raw", dtype="<i2").reshape(-1, 2)
    dlog(f"render done in {_t.time()-t0:.2f}s")
    return meta, pcm[: meta["length_samples"]]


# ------------------------------------------------------------------ normalisation
def gain_for(mode, meta, pcm):
    """mode : none | track (crête de la piste à -1 dBFS) | game (gain commun à toutes les pistes du jeu)."""
    if mode == "none":
        return 1.0
    if mode == "game":
        pk = int(meta.get("game_peak") or meta.get("peak") or 0)
    else:
        pk = int(meta.get("peak") or 0)
    if pk <= 0:
        pk = int(np.abs(pcm.astype(np.int32)).max()) or 1
    return min(TARGET / pk, 32.0)


def apply_gain(pcm, g):
    if g == 1.0:
        return pcm
    return np.clip(np.rint(pcm.astype(np.float32) * np.float32(g)), -32768, 32767).astype("<i2")


def read_meta(path):
    """En-tête + table des pistes (sans lire flux ni échantillons).  Les anciens NGT1 sont convertis à la volée."""
    if path in _NGT_VIRT or _magic(path) == NGT1_MAGIC:
        return read_header(ngt_data(path))
    with open(path, "rb") as f:
        h = f.read(HEADER)
        n = struct.unpack(">I", h[16:20])[0] if h[:4] == MAGIC and len(h) == HEADER else 0
        if HEADER + ENTRY * n > os.fstat(f.fileno()).st_size:      # nombre de pistes corrompu : pas d'allocation géante
            raise ValueError(f"{n} tracks announced, the file is too short (truncated or modified)")
        return read_header(h + f.read(ENTRY * n))


# ------------------------------------------------------------------ rééchantillonnage + boucle
_RS_CACHE = {}


def _rs_blocks(up, down, B=125):
    """Filtre de scipy.signal.resample_poly (firwin, Kaiser beta 5, demi-longueur 10 x max(up, down)) découpé en
    petites matrices denses : la sortie r d'une période de `up` sorties lit les entrées b0[r] - m (m < M) avec le
    coefficient h[phase(r) + m x up] ; une période de `up` sorties consomme exactement `down` entrées."""
    key = (up, down, B)
    if key not in _RS_CACHE:
        mr = max(up, down)
        half = 10 * mr
        n = 2 * half + 1
        h = np.sinc((np.arange(n) - half) / mr) / mr * np.kaiser(n, 5.0)
        h = h / h.sum() * up
        pre = down - half % down
        h = np.concatenate([np.zeros(pre), h])
        M = -(-len(h) // up)
        bank = np.concatenate([h, np.zeros(M * up - len(h))]).reshape(M, up).T      # bank[p, m] = h[p + m x up]
        t0 = (np.arange(up) + (half + pre) // down) * down
        b0, ph = t0 // up, t0 % up
        blocks = []
        for r0 in range(0, up, B):
            r = np.arange(r0, min(r0 + B, up))
            lo = b0[r[0]] - (M - 1)
            W = np.zeros((b0[r[-1]] - lo + 1, len(r)))
            for m in range(M):
                W[b0[r] - m - lo, r - r0] += bank[ph[r], m]
            blocks.append((r0, len(r), lo, W.astype(np.float32)))
        _RS_CACHE[key] = (blocks, M, int(b0[-1]) + 1)
    return _RS_CACHE[key]


def _resample(x, ratio_num=2000, ratio_den=2331):
    """Rééchantillonnage polyphase, mêmes valeurs que scipy.signal.resample_poly (écart < 0,01 sur l'échelle 16 bits),
    en numpy seul (scipy n'est plus nécessaire : ~100 Mo de moins pour la version Windows) : chaque bloc de sorties est
    un produit de matrices (BLAS), plus rapide que resample_poly.  x : (n, canaux) -> float32 (ceil(n x num / den), canaux)."""
    from numpy.lib.stride_tricks import as_strided
    up, down = ratio_num, ratio_den
    x = np.asarray(x)
    n_in, ch = x.shape
    n_out = -(-n_in * up // down)
    blocks, M, span = _rs_blocks(up, down)
    P = -(-n_out // up)
    out = np.empty((P, up, ch), np.float32)
    for c in range(ch):
        xp = np.zeros(M + max(P - 1, 0) * down + span + 1, np.float32)
        k = min(n_in, len(xp) - M)
        xp[M:M + k] = x[:k, c]
        X = as_strided(xp, shape=(P, span + M), strides=(down * xp.itemsize, xp.itemsize), writeable=False)
        for r0, n, lo, W in blocks:
            out[:, r0:r0 + n, c] = X[:, lo + M:lo + M + W.shape[0]] @ W
    return out.reshape(-1, ch)[:n_out]


def _periodic_edges(loop, n):
    """The last n samples and the first n samples of the loop, repeating it if it is shorter than n."""
    reps = -(-n // len(loop)) + 1
    t = np.tile(loop, (reps, 1))
    return t[-n:], t[:n]


def prepare_playback(pcm, meta):
    """-> (intro, loop|None) en float32 stéréo à OUT_RATE.  La partie bouclée est rééchantillonnée dans un contexte
    périodique (ses propres bords, répétés) pour que le raccord reste continu.  Seuls 2331 échantillons de contexte sont
    nécessaires (la réponse du filtre est bien plus courte), au lieu de recopier trois fois toute la boucle."""
    k0 = meta["k0"]
    ls, le = meta.get("loop_start"), meta.get("loop_end")
    if ls is None or le is None:
        return (_resample(pcm) / 32768.0).astype(np.float32), None
    a, b = ls - k0, min(le - k0, len(pcm))
    intro, loop = pcm[:a], pcm[a:b]
    if len(loop) == 0:
        return (_resample(pcm) / 32768.0).astype(np.float32), None
    N = 2331                                                      # input samples of context = exactly 2000 output samples
    left, right = _periodic_edges(loop, N)
    r = OUT_RATE / RATE
    l0, ll = int(round(len(intro) * r)), int(round(len(loop) * r))
    rl = _resample(np.concatenate([left, loop, right])) / 32768.0
    if len(intro):
        ri = _resample(np.concatenate([intro, right])) / 32768.0
        intro_out = ri[:l0].astype(np.float32)
    else:
        intro_out = np.zeros((0, pcm.shape[1]), dtype=np.float32)
    return intro_out, rl[2000:2000 + ll].astype(np.float32)


# ------------------------------------------------------------------ activité des voies
def voice_activity(regs, meta, fps=FPS):
    """Matrice (14, frames) de niveaux 0..1 déduite des écritures de registres (déclenchements, volumes, durées
    des échantillons ADPCM).  C'est une estimation d'affichage, pas un mixage par voie."""
    k0, n = meta["k0"], meta["length_samples"]
    rate = meta["rate"]
    ch = []                                     # (t, voice, level)
    R = {}
    fmmap = {1: 0, 2: 1, 5: 2, 6: 3}
    for t, reg, val in regs:
        R[reg] = val
        tt = t - k0
        if reg == 0x28:
            c = val & 7
            if c in fmmap:
                ops = bin(val >> 4).count("1")
                ch.append((tt, fmmap[c], (0.55 + 0.45 * ops / 4) if ops else 0.0))
        elif reg in (0x07, 0x08, 0x09, 0x0A):
            mix = R.get(0x07, 0)
            for i in range(3):
                v = R.get(0x08 + i, 0)
                vol = (v & 0x0F) / 15.0 if not v & 0x10 else 0.85
                audible = not ((mix >> i) & 1 and (mix >> (3 + i)) & 1)
                ch.append((tt, 4 + i, vol if audible else 0.0))
        elif reg == 0x100:
            if val & 0x80:
                for c in range(6):
                    if val >> c & 1:
                        ch.append((tt, 7 + c, 0.0))
            else:
                for c in range(6):
                    if val >> c & 1:
                        s = ((R.get(0x118 + c, 0) << 8) | R.get(0x110 + c, 0))
                        e = ((R.get(0x128 + c, 0) << 8) | R.get(0x120 + c, 0))
                        nbytes = (e - s + 1) * 256
                        dur = nbytes * 2 / 18518.5
                        lvl = max(0.15, (R.get(0x108 + c, 0) & 0x1F) / 31.0)
                        ch.append((tt, 7 + c, lvl))
                        ch.append((tt + int(dur * rate), 7 + c, 0.0))
        elif reg == 0x10:
            if val & 0x01:
                ch.append((tt, 13, 0.0))
            elif val & 0x80:
                s = ((R.get(0x13, 0) << 8) | R.get(0x12, 0))
                e = ((R.get(0x15, 0) << 8) | R.get(0x14, 0))
                dn = (R.get(0x1A, 0) << 8) | R.get(0x19, 0)
                nib = (e - s + 1) * 256 * 2
                lvl = max(0.2, R.get(0x1B, 255) / 255.0)
                ch.append((tt, 13, lvl))
                if dn and not val & 0x10:      # sans répétition : s'arrête à la fin de l'échantillon
                    ch.append((tt + int(nib / (dn / 65536.0 * 55555.0) * rate), 13, 0.0))
    ch.sort(key=lambda x: x[0])
    frames = int(n / rate * fps) + 2
    out = np.zeros((14, frames), dtype=np.float32)
    cur = np.zeros(14, dtype=np.float32)
    i, spf = 0, rate / fps
    for f in range(frames):
        end = (f + 1) * spf
        mx = cur.copy()
        while i < len(ch) and ch[i][0] < end:
            _, v, lv = ch[i]
            cur[v] = lv
            mx[v] = max(mx[v], lv)
            i += 1
        out[:, f] = mx
    return out



# ======================================================================================
# Lecture audio
# ======================================================================================
class Player:
    """Lecture audio (sounddevice) : intro puis boucle infinie, pause, volume, déplacement dans la piste."""

    def __init__(self):
        self.intro = self.loop = None
        self.pos = 0
        self.in_loop = False
        self.playing = False          # un flux est ouvert et la piste n'est pas finie
        self.paused = False
        self.volume = 1.0
        self.loops = 0                # nombre de boucles terminées
        self.loops_max = None         # None = loop forever; N = play the loop N times, then fade out
        self.fade_s = 8.0
        self.fade_pos = None          # frames already faded (None = not fading)
        self.stream = None

    def load(self, intro, loop):
        self.stop()
        self.intro, self.loop = intro, loop
        self.pos, self.in_loop, self.loops, self.fade_pos = 0, False, 0, None

    def _cb(self, outdata, frames, tinfo, status):
        out = np.zeros((frames, 2), dtype=np.float32)
        filled = 0
        while filled < frames and self.playing and not self.paused:
            buf = self.loop if self.in_loop else self.intro
            if buf is None or len(buf) == 0:
                if not self.in_loop and self.loop is not None and len(self.loop):
                    self.in_loop, self.pos = True, 0
                    continue
                self.playing = False
                break
            take = min(frames - filled, len(buf) - self.pos)
            out[filled:filled + take] = buf[self.pos:self.pos + take]
            if self.fade_pos is not None:                          # album mode: fade out after the last loop
                fl = max(1, int(self.fade_s * OUT_RATE))
                env = 1.0 - (self.fade_pos + np.arange(take, dtype=np.float32)) / fl
                out[filled:filled + take] *= np.clip(env, 0.0, 1.0)[:, None]
                self.fade_pos += take
                if self.fade_pos >= fl:
                    self.playing = False
            self.pos += take
            filled += take
            if self.pos >= len(buf):
                if self.in_loop:
                    self.pos = 0
                    self.loops += 1
                    if self.loops_max is not None and self.loops >= self.loops_max and self.fade_pos is None:
                        self.fade_pos = 0
                elif self.loop is not None and len(self.loop):
                    self.in_loop, self.pos = True, 0
                else:
                    self.playing = False
        outdata[:] = out * self.volume

    def play(self):
        """Démarre la lecture depuis le début.  Retourne None, ou un message d'erreur lisible."""
        try:
            import sounddevice as sd
            self.pos, self.in_loop, self.loops, self.paused, self.fade_pos = 0, False, 0, False, None
            self.stream = sd.OutputStream(samplerate=OUT_RATE, channels=2, dtype="float32", callback=self._cb)
            self.playing = True
            self.stream.start()
            return None
        except Exception as ex:
            self.playing = False
            return f"Audio output unavailable ({ex}). Check the \"sounddevice\" module and the sound card."

    def swap(self, intro, loop):
        """Replaces the audio by another mix of the SAME track (same length and loop): playback goes on seamlessly."""
        if self.intro is None or (loop is None) != (self.loop is None):
            return False
        if len(intro) != len(self.intro) or (loop is not None and len(loop) != len(self.loop)):
            return False
        self.intro, self.loop = intro, loop
        return True

    def toggle_pause(self):
        if self.stream is not None:
            self.paused = not self.paused
        return self.paused

    def stop(self):
        self.playing = self.paused = False
        if self.stream is not None:
            try:
                self.stream.stop(); self.stream.close()
            except Exception:
                pass
            self.stream = None

    def window(self, n):
        """Dernières n trames jouées, en mono (pour le spectre)."""
        buf = self.loop if self.in_loop else self.intro
        if buf is None or len(buf) == 0:
            return np.zeros(n, dtype=np.float32)
        p = min(self.pos, len(buf))
        w = buf[max(0, p - n):p]
        return w.mean(axis=1) if len(w) else np.zeros(n, dtype=np.float32)

    def duration_s(self):
        """(durée de l'intro, durée de la boucle) en secondes."""
        return (len(self.intro) / OUT_RATE if self.intro is not None else 0.0,
                len(self.loop) / OUT_RATE if self.loop is not None else 0.0)

    def position_s(self):
        """Position depuis le début de la piste (intro + position dans la boucle courante)."""
        if self.intro is None:
            return 0.0
        base = len(self.intro) if self.in_loop else 0
        return (base + self.pos) / OUT_RATE

    def seek(self, sec):
        """Se place à `sec` secondes (dans l'intro, sinon dans la première boucle)."""
        if self.intro is None:
            return
        n = int(max(0.0, sec) * OUT_RATE)
        self.fade_pos, self.loops = None, 0
        if n < len(self.intro) or self.loop is None or not len(self.loop):
            self.in_loop, self.pos = False, min(n, max(len(self.intro) - 1, 0))
        else:
            self.in_loop, self.pos = True, min(n - len(self.intro), len(self.loop) - 1)


# ======================================================================================
# Cartouche jukebox : flux YM2610 compressés (LZSS) relayés par le 68000 au driver Z80, index NGJB, V-ROM relocalisée
# ======================================================================================
# Chaîne validée sous MAME (pilote neogeo, liste logicielle maison) : octets reçus par le Z80 identiques à la référence,
# audio conforme au rendu de référence (décalage constant ~80 ms, aucune dérive sur 60 s, passage en boucle correct),
# changement de banque P2 en cours de morceau (banques 6 -> 7), marqueurs de banques vérifiés au démarrage.
# NON testé : console réelle, Darksoft.
MB = 1024 * 1024
JB_TICK = 32                    # échantillons YM2610 par tick du driver (Timer A, NA = 992) : 0,57 ms
JB_FEED = 160                   # octets relayés au Z80 par image (boucle feed du 68000)
JB_TICKS_PER_FRAME = 30         # 55944 / 60 / 32 = 29,1 arrondi au-dessus
JB_NOLOOP = 0xFFFFFFFF
JB_HDR, JB_GAME, JB_TRACK = 16, 32, 32
JB_MARK = 16                    # marqueur au début de chaque banque P2
JB_MARGIN = 0.05                # marge exigée sous chaque limite avant construction
# Limites validées par les jeux officiels SANS puce de protection (liste logicielle MAME hash/neogeo.xml) :
#   P-ROM 5 Mo = P1 1 Mo + P2 4 Mo, banque de 1 Mo écrite en $2FFFF0 (kof97, rbff2, lastblad, lastbld2, shocktr2...)
#   V-ROM 16 Mo (29 jeux, dont lastblad et shocktr2 sans protection) ; M1 128 Ko (138 jeux).
# Étendu : banque sur 3 bits (data & 7 -> P2 8 Mo, P-ROM 9 Mo).  MAME l'accepte (write_banksel) et des homebrews s'en
# servent (etyphoon, violentv) ; aucun jeu officiel sans protection (kof99, garou, mslug3, kof2003, svc... passent par
# des puces SMA/PVC/K2K2 avec leur propre banque).  Le jukebox vérifie chaque banque au démarrage (marqueurs).
JB_PROFILES = {
    "standard": {"name": "Standard: P1 1 MB + P2 4 MB (like Last Blade, KOF '97)", "prom": 5 * MB, "vrom": 16 * MB, "m1": 128 * 1024},
    "extended": {"name": "Extended: P1 1 MB + P2 8 MB (3-bit bank, homebrew only)", "prom": 9 * MB, "vrom": 16 * MB, "m1": 128 * 1024},
}
JB_P2_SIZES = (1 * MB, 2 * MB, 4 * MB, 8 * MB)
JB_BOXDATA_OFF = 0x215c             # = boxdata de core.S (mis a jour avec JB_SECBLK_OFF a chaque modification du code)
JB_SECBLK_OFF = 0x629e      # où le bloc de sécurité du BIOS (122 octets) est recopié dans le programme 68000
JB_TOASTY_OFF = 0x227e         # = toastydata de core.S (Toasty, option du constructeur ; mis a jour avec les deux precedents)
JB_STEXT_OFF = 0x2c2b          # = t_custom de core.S (texte qui ondule personnalise, 2.5.27 ; tools/embed.py)

# Programme 68000 du jukebox (jukebox.S) et driver Z80 (m1drv.asm), assemblés, compressés zlib, base64.
JB_PROM_B64 = """
eNrtfHt8VNW972/vPdkzmQxhSGKIiDCEgAERhmSMEScwrySTEJIwCQ/R4gSSGUSr0zREoGmIGUrRy/FyPBwOUo/leLgerlpLLW0RkUJ4iIgQY0RE
XkaEgCiUIoZhYO5vPfaeHaRN+7n3c88//a1kP9Ze7+/vtdaevcD8Z4DtOhH/DfifjP9p+D9S8z8I/y03xSn/Y/5CvPY/B8B/FKBmLf3//vP8af+N
VF5YcU9xYYWQ+AKYAcC8HAwggpbKrwLGkKNxsPbI8xeXuuD/kua8xC8E+P9OITDfD+brb5iwk7Uy9my7zuN6C8zCUdciPJ4silogNwp6sINpylU8
Qup2sIKA6aWA2fQW7b9ZMAd0ftB32LeGoKAJ+6HLsetieGUBcep7sR771lY1XmhyPUFjI81QA2OHOK+SkQ9B/RLrdoyN5kZjMYwZkhuVLuI5Y3hU
qaMGkgdhWwSMLR/eI3jxPMaSL3iGb8erLIsjtxt0eJVZA8bqGpjlSo2CBMh9zYk1ANOnHoxFakC/qnQRSRM0YI1Yv7gQn02ogf43MFeIPrsU0GHc
nBqQemrAkFwD/U7VgO5QDSRk8+f7a2DaaT/E9pTeT9oe7HHRc/mCTPI8K2sUGD5qs8FXpR1t5QtGsri7wfRJm20UZHQ6vyo9hPGOM0XRu+joQ4Dm
D6SQY5BeB4tOpJJeVRsEEIJDbCRujc9lcoFUJzZAbhu5V8YC00DQMAl7M+2odWgaiCJiMySN4LqaXAetVaQNZU9kYw4yQmV+A16lkCsDMntQxv5G
/Ea8FoLYdyGZtqragDwRTMkh12JApufMKqc/A+Ol4FgW73O+ScezTqyH3B0khvAN6OixSGlh+QLMowvm0/GTgxaa10FzigFWg4ve6QgfiWVWWjaN
x3voxNwJQfKE1C0HM3k5abmEdxwkLb1ykfTYl7H+bZhO32e6kf7V5QtYXTVww8PqC+hyRsGgKiftjc5vUZ9nsefY40dhkNpfHYulrS+qlWlcEcWr
SHZB0puuOqPOCUYWHx8P75ntiFcCjvz1rfi/uewESDWQ5M8lqDtoahe9FlktNRBbQ1viwNRr+YhhO2pBwGfXX8xOPfwWkYfRd5O0uuey7wYDxcBn
WhpDCiaz57wFvuG78Gge/hWY8JxGU06w3g1pdMR8wWTTIppuTVDX/hhk0JZU4ojZsOx6XobMz16a20OPg+hRSVHuB90BKt/rCiMPfW4+EohWLc8q
aRiYPigom3dO3RfrwfhPWHwe7ZPP7d25LApGWQKreafXzc4NenMULJg+YjHoWkh5tEUv0trWli9AWd1Kr2XWlvg4m+0Qw6cHaL88gWS8l/hTj9+I
d7reOfwgvYx9F0lZgWqayxso47k9DAE2+kwmUSKFINzIwbMYHFkD126wp5xLkuvB59jIJSQEfrhhKF/QCAthMVgRp2vtm8kzR8AwQTpCrlyHMJfP
s5nlOGpyg1hXSmoXBgfMtPY5yMcC6b0wuAYGzrRJVa6WNq9jY2Gd6HPYsWRa7kLUNIO2uurkF10+j/+8VZcj++H6Cm378b6Jy4fav0nkSQY9etnI
iavwjFwqrsg9QWLpMYOWM5oiO71e7vLW6sxbocW3HPX35fIFPlKan5ZpCWbStH7RAZMC6XSsLbzkCXgmGjiHa1WAy6xENznOr5cbIM3cCOkDNrnn
6lJa/SZyPcM9X2yElPBDrvmoB81tvmewzsMhYLW0oMb3OkodgRzahtmkPKGL9nd2Q4LohKF5wiG3OwKnrX+ywiwnctR5RF4mlk5tpz7A+reWI/ci
QY7y21qGQA48T+JraVytyQnyXLFe5mM5ho9lVltU6v6ISoNp0Znx5Fxn1vEr2rpB/tPlC5QxJH1V+oQ9uoTWZdWSmCC2wJPtqRcE0bBcEBsuC+KS
fxbEJ8sF8ZEcPH8uiGlLMC526/8KT0VtxdIn1z+5q+Ly2MtjLj96OXi57rLtctZ3WVezrtmu22K2E2l/TPtl2hJbxbSKGRUPVgyuGFJRUfFI2SOl
Fd6KovIFWk+AYneJHi/WgLyQWO+R/hqoWKbIDu35vKAB7dAbfujZUAO+bXheR3WNYfhuPJpo/hx6tNFjviKjMJrxA2Ty+0F4FlD7p/B7Iq0i3ouM
swKz0+8n1l2UoAVtJV7l2weGBtG4wQmiDC1bpUDy1P2xb3j7LNgfmrMJn+fuIRxskEGevlssRIkirfOKRTDpbDl9llG+AH2cWAB7E1tJWoCILPee
iW3nOANsYe2K1bN2x+ZznSkjJ7800Q6/NBXDz+dYTIuw0VhebTpyD8rSN16TQ9hYZ8DjxTqABhMpD5/j9bxSoqNNgaJswmdmrrkBvKPJfRpeTVT1
cjrXUhPqTFj/Tqzfh2MzBO3U85S7JvhbcMxQR8QmoOfTiM+MOA5Ur5WdkGLlC4iUGYDKhi1ooR6Cjeq0/FXkOk90LYmhdzjegloLltJe5wRSsMzV
lO+tWJqBxNGcOV2Ej621xJNo9KP3BaEcQL9EH8jsLqlmttSGstX/c6+NYOxrcfkctJw8/7Mol0uUNPgsj6cZq0mDQLC2pbZYwOcibaM+UH4VHTH0
vMhTg4/cGSz0GkWnfywWSDe9xTx7MNQZ5bfoFUkjeJ3dJUH0Z6jlHhI00fqH4HFc7CLLK7eg/woWB46CuXwB90vtE/OFstx38WpiE2wtrrUit2AO
lGNM645My1uc+FtDIG3qB7HI1oyAKUMu0m3OCOh8Rf4Oyld2xb8tX0B7NCdPJOMtmHJ3kiPaEcNcsUFgfmEL9QWDY5nUMT0Z9DDP0RX3HNFbVPw5
9JHWc306+GOaq9bAa7xoWlT4MI1BX0zRPEzXhmRXhuv2qXtjkZs9eJONefC0BZfp8QrVB2lY42C8Q59a96x9a4tgtcPzBU39Y5h+b6wnNLWgSc+v
afpBVBcfCCW4ZmJclMZl02MWk09hJGunYMmNotibhcyb7R3yj0SvhrAW4qzidqz1LjqfwLbnRqMZ+HQ+P++hpe+i9T4eGqipdy897sN6LXjeT++O
8NrRepqPqOWvKmi6IoAYugtjHKw3BU3PPd07huZHy4uziDHNgk3/dam9tQls+irkU9DnyaIbpDOTO93oD54sQD+hoGkAqi1fkakIUuoO+4pRT9xe
R9ukK8M2IYfqytEX7K4B0zymgZuFGhhGPPPW4fi8fyeJq4E/t+J/M8Zu5RruUvkCPwybiGkn5EbFTHCImc7IgFbE2CH66xNC/XMOkzFwdoOZ2Jjc
aAuAY+gNdhZTcqNLLuLZxe/RJ6rwgEPKzI0+uQvPGP/oZTzPyY1mfYfn1tyoLYbnl3OjaUvw3JYbfbACz1250UfKwKETLdgjeRvW1k1aoLOEJrH6
uR6+hDLOLMFFYkssWbRv7axvJdbeViUAFbP8OIVRkUF+E8oU5FmJ8hZ6pJ6g3EZKy2wmLcgl80CzvLl8AZcgMznLmwMGVofyRN4aHMJK8J65AUy7
XyX+jx7PK9BDX4JSExlQVg8hsbQyiHMfZ7cwD+u/HIJpzrrB1U7uhezwUs9BbgsY0IdwKv6D3LY9KszDEowfbh++l7SMaBXWNjZWWCr1YOXNODaz
1LiynGwQq5zubjAUdkO2zT61hY9Dq3UUiDNLRpb6DQUPIWc9RMfjSuE5yEBucyDKx+1bny4K6eOSWb5AGcMwxsdHkLRd3mxCng4W4VFAK7aeWQx5
MxtdPlpbWbtYm2zZoLtQqpT4syLC37LLAFjzFVriFnckzYee23gAkwSxYKWPlsXKODQP5KnufLtwcY2blYfcYoi3z5ZhzQimnS31uDo9okuIXShd
6iA1+HV8DeFkfATRRmQ7I7c/VGoOZOA5hdtpA/PHgjpnZFAxGXWIhqA0I6jzOfw91Lr0MPQFQ9BIJRktvumwyitgMKLVP8naRHokYE5iNQX5TAli
q1vpZOUIOlSVKO+BtAlwegra/1VYDp9XCIYJNOfMQlsCS3N6Ci0LfecjDkz7DqbNyKNpbBLqC73HLbqxv5PtW5euKsBZwEyqSzwuNgoY+w4ZB8pv
l6uZR98zUfiq5ExFRzG2asJKJ+3bZVzxqMwiT6PoGXRtIrYwGkRPIIYMLoj+DJazDWdc/7KIxsgsH7MOuEZCPNOMdhexAbSXGehjb692IIckzBVD
CR9Si0Ct1UNk/UJIJ+sWQvpGYa6Be9ZpTdTLENKC5ipqOTqczshtq+xWMziJZhLdkW+nM1vYVVqvx34OzRMPua3jrdBSZN0+ndR9XjP+OKNCSzCU
tgYagOQUMpZGwZ8nVrs/ofq9q9Tn+pjqePb0dClKgwVt63y0rfPpOO/f5A6a5ojT3D43tbz7CyMZ9awV2AIhn6TZe6qM4rbv1BS7uD8KSYeL6Fm/
tohZlU5Xe1tzkl2HfmNscI4fvMuOFuWQeUYsJQfdyaePOj/YeXLZ6WUXyq3LZi6XPZCuK4Rk9McOEA2WA7JTiF4okZ2QwsprGJgnrJ5J8MaZyRVE
WciDQ26P+8LkhoEkVnajZOGTwkjSensK2g/dXLFJFwRpTHx8yPwEWyAFxp7yEo8LkTLU6Yx41e5wRtJGW63Axr05R65yWltQ4iwEXdpjnHvm7iJn
gw4gkFkPzGq7zyGvmVGXTSW6zLrdfRasOMMtqjtHER1JVswMzVSKLI8NpufsAKBFJ7mJjR2i2HarbiW1+Y+BYKBckd0ACULQRNe2jHWX0de82AjY
M7EuBT1cHbHgAQNF7IjPzXPPxz5NQn95j1XaHgVraT2uLaXzZ3v4s1dpP+bT455Sd5DO6bAMB+l1XCdjDPUSsK4Ecq6TmdfA2pawg3iFQnaO+GUJ
q8t9CQeX9OrFYc+YodNFr6ePD1vYSI0ev9SCtky/vSUqOL0OnQPW0fiJ41to/AYyv2wnNWS2e2j9WYshL+HLybIbfRlaZxKgn49c9GUJqyczhO51
AsoMLR97GTKzuiZORAmy2QV/afGT4qrija66LBsroZX4xkK2PUy0pPYfR7cnB4j89Z+eg7kN91PtNDQoe5wdj8JYLO3iKifTMZ2PApZAtAyuJYys
F6tcjxmYz6Nq329suHwCls5iLAd4OS7MN4aVILtFYCXQ0dQRrsS+NaKWjxiOvGmtBLQx86wJyJd0FG3ImWe8Xd6VhYzrULpCFkCe062c6u/ZfhZG
tz9KrI3sSgUyPig3t39dMhFblzcKsqvc9qcnSQXYPlKjzzH1/djlvKGYxoHydtpXaCpE/oIbq9yRxNGlU7Edu/KYtLshhussLXMN+Wjx17jzdKcn
433/uWJj/3zpq8lflq32FEYGiJ07i4nUdDX3yzuCJUaZrDEZU9pmsw9UvWezw/50vDXKFca32J+O32uftDrtT9vs55U7F+anV0tp/HLgdy5yt5Le
lVKfkcy4pSY/TpZZ3fnUKpyiq6iCuNmBfS2lciDS9emonep8n2OzIzBmIkljlIvBPUEnF5I1voQxNJ/RR3T8VFVOjH6yrljGVlqoFUiSHTAY0zjQ
DjALFNnonGuc7nzTMdeQA35dUOSrqBFcAR3cVRJK/PxR1LLJnTuckYEGVovsaHXbWygSl4mfbJUOuQ85uibTPlw57FnjttuF2N6iEDRXvkTkxmjO
cUBBCPlNfNiztwiRuMj6EMyoKkat6v7+c6Wmpb1qIlp1gl1UyyX69VAhpu/h5ZlJeUvd8fiyE3qcN5MSdOVV7vnZbPQDKczG68rQZxuSh2sB/mTm
y+P9BnJP7IuuPO53tbpDlXG/i8U2g1WP43n6a68dfbvEZERaj/KiJzz+eUmBEzmFzBP8dYdp2ZX06KPHanqcTo8z6XEWb9HDeE5D32gd99w25EaH
4eqp/DL154h3twzPr2hadjr0SG+PUPdwFZ2D6x6en4Nrdd1kHQ/bOYvFYcwhotFmsDQz8X6P5n4WLWEm4Q1d9UZnMPkJHb4/QL+ZcIWumj6dRZ9O
/97T6fRpZTvtIZYZoyVW0lgfjZ2uxvq497qOxMsbcGVlzJPJOD8Yw6yOvMGfgnya9rgJZ4tp6lgQj3wdqV1ezzx3+eV2p8kxrOWHGVb7MFw9ESK8
tws9jhwgcaRlOG4k58vnaR/J6KFnhW+HYs2FEbOVtToD16C8S4l9R42B3sAg4g38jLV9MHm2LP5sCHn2c2fEfLk4kmIm83GdvzCSIpszvC0pGd6n
0zK8rXnCzt2TxN27nnedd9qGvrtr9+5O93lXHux4F2P3tLvOOzB2z+53V5FY9L9h+462k45J0OVof4SOybqdbSedk4QuZ8cjHeT+FZtE5gedLlsO
vt9zoeaCC6W5RNdrLIDPldOKll7+zft1uMql8EjLaaKddbWhRwoq0RZ2owe/l/gqrSzef3P8UhY/p3c8+u1UI1Fra9TqJVYP6hkd6hhjFr5eaHZ7
/2sdWRF6qeyXkMA9BV0D+oFUJlbVnSQYQFlLVJzpdcgOcSbVWLgaD/lYht7rqHZkoRwK+Uu3Y15LrdhgoRYS3xRCOllVILM1YUiQ+r6ChXGTgEBd
KPktIn+ypIueP8cjX4nACXIMdQG2MkFp5cYitFNF/p56SMG5Dmo8C64MO8h7IqtwpqTd0eHocFmFDmeHA70+YKsERK4LmsxkNcB562u2TieBnc4W
tmAda7GOhdksP6mrUqnrEVKX7EwEljuFlFSIOcTF4CvGddAD5K0TXanC8gojgG88YRN7u8XnSrLyhumL/JHkLc0dylsa9jxgLIwISZir2T8b8+/B
q4Z89rbDQ1b88B3NuHx874DXtfh8E56r6XMS04Axv8azi8ZUrqEr4LUiWTWBmXyOZsA0/060KJ7fJNiwtz0Ss0C4btkfx5y9LSpfIC4lGJg8MHeu
uHDucvLOSIfvinZ5PeyspMAn9nHk/Vk7tm9C9lCvB2eKu5xlrmlTLBawWCz34H+1z+meHL8rmVKo3vgKpzhLykvKi9WYSue0qkKPcldVXVFZGb9F
NhP53z/oH/QP+gf9g/5f0w98JY788aOzhg4amGpONhkTDXq9LMt6JINCei3Jf520SQ19U6IxyZRsTk2/fbAla9TY3PyJnsm+B/3zYmhjMHwY64h9
hKEz9nHsEIZPYodjn8aOYPgsdjR2DMPx2InYydjnGLpiX8ROYfgydjp2BkN37GzsXOwrDOdjX8e+wXAhdjH2p9glDH+OXY59i+FK7LtYD4arsUjs
WiyK4XrsBnlTSH9Bhr/3waDD1Qx8t4m/2zJAIgYjJOEvPfphSIb+9A3YAHxflIqzgzS4DdJhIIYMuB0GYbgD3+vcCUMwDMX3I8MwZMJwyIIRGEbC
XZCNYRSMhrsxjIF7YCyMw2CF8fjmNQdywQb3Qh6G+yAf7scwAR7A9552KICJMAnXDxzgxF/guDF4oBCKoBiDF0qgFMNkKIMpGMqhAiphKgYfVEE1
hmkwHWbATAwPwix4CMPD8AOYjeERfEFZg++J5sBcqIU6DAFcQpkHj2KYD4/B4xh+CE/AkxhC8CP82dePMTTAAmjE8BS+uFmEP8dYDD+BJvgphmZY
Ai0YnoZWCMNSDD/DedLPMSyHZ+BZ+B8YVsA/wXMY/ieshH/G8Dz8C6yCf8WwGv4N1mB4AdbCL+BFDP8OL8EvMayD/4CXMfwnrIf/Ba9g+C/YAP8b
w6vwGrwOv8LwBvwaNmL4DbwJv8WwCX4Hv4c/YNgMb8EWDG/DVngHtmH4I2yHHRjaYCfswrAb9sC7sBfDe7AP3sewHz6AA3AQQzt8CB0YPoJO+BjD
IfgEDsOnGI7AZ3AUwzE4DieEAWKmziMHDMuNry7GkPT2T9427W/a3+/YT4/9NXkUBrDgwOAXQjjM5FiJAV/fD3Nm1qT8aICQOSxl/IABJFWKY0AN
PjdDao4rtz6zPtOZWzN8aiZJNyx1wIBMcZhQCWlut+fHuam5oifT5sNUKZlTh9ek1IvjBb9wW7VnWoMnzeOa5irMtaXmzhn+o6ypme7UqVi7XJcQ
uG2aZ5oUkKa7C+fi05R7M4enpTpT/IK+UX4qPVA33f2UO6ibnuaZa6vP8+V60lJSQoLh5/c9pX9qZNCzPGte7YzqabX31hf7bHW35aSMFxLX5C83
LNcvTHihdtGIeSOm31aYOnP4vXm3zUkdJg7asPCFec/MWF746ohnpy2cFqgr+vGDVYWB9Hp8dsdbi159dO3MF+S3C3+RtygvmD69av7cohkjU4cP
EwfvW/z2/NfuX1u0X379vmf1CwMzsh5Lm264S8oakHLnZz/Z/5O3J7ymP1b0zoxfzFiun+dp8szwZldlTU1JPm8/Nnh/6dbib+7aZng9/5mn5tX+
tGHGouwfZzlT+18v+ObOY5M/MMSCB+f9yrvWsCjhuYR5o0dljXCm4i9dLfhLV0vptMmFroqZ6KwWlpdWPGgpKikvtEyZVlXitgzDyPIStzXXZhln
8RSWVTstJVVlznKPhTq2/yD2g+CbBrLa6yyfXGUpqvBZcBRxnlDtLamyVFUUVc9w+gr/+pCKUoJsSCTWZEBqWvrAjEF33DnEMiwza8TIu0aNvnvM
PWPHWcfn5NruzbsvP//+CQ88YLcXFEycOHHSzYRxBQV2+wMPTLg/P/++vHttuTnjrePG3jPm7tGj7ho5IitzmGXInXcMyhiYnpY6AC1mUqJBTpBE
uHH9WqTnu28vX7p44evz5852n/7yi66TJ44f/ezIp58c+rjzo44P2w8e+GD/+/ve27sXFxh279q1c2dbW9uOHTu2xwnvMG7nzl24LrHn3b1739v3
/v4PDhxs/7Djo86PD33y6ZHPjh4/cbLriy9Pd589d/7rCxcvXf72u57Ites30B5cmZQoFnyTbE8580A04/4/9eQP+dN9XcPuNR2zJQ/IPWoaf9dn
1q/uHvvd6XtGRMZ0jBg99OAoMSv72I2RuSdGHL43S9+ZOdQ07P3BFuu+IRdsd3afG3zv+UHv2W6/Y09Gf0v6AeNt9va0zwpSrh0acA/0bxudPLat
XyQn6ci3xonHE/cV6Ae8K9+ZnrArQ3pgj/hlgfD1ydh9f76xw3Z9xI5rhlGRg+LVSZ3ffTTpinTw2+zEP7cNv5S780+X8i50ff3NhDPn38v/KuPd
c2mDu9/vf+b+g6dP3n/qyrEv7ol27R11cuR7J2LZx49eO3rv558dyjmS+PHhO/p98mH6obs7Oy+O/ujC1x3Zl9s/GX7wtiMfGNL3d+neH37mvXND
98bOv5sm7D6dvGvANzuvJ+3An2JDwoMJDyU8nPADebbsl2vkOXKtXCcHcKL+qDxffkz+ofyE/kn9j/T1+h/rG/SN+qf0C/WL9T/RN+mb9UsMLYan
DWHDUsPPDD83LDc8Y3jWsMLwT4bnDCsT/znx+cRVif+auDrx3xJfSFyb+IvEf098KfGXieuMLxv/07je+Irxv4wbjK8aXzO+bvyV8dfGjcbfJP02
aVPS75J+n7Q56a2kLUlbk95J2pa0PWlHUlvSTtNu0x7Tu6b3TPtM75v2mw6YDpraTR2mj0yd/Q71+6Tf4X6f9vus39F+x/qd6Hey3+f9vuh3qt+X
yaeTu5PPJp9LPp/8dfI3yReS/5R8KfnPyd8mX+n/Xf+r/SP9r/WP9r9B3lMBFF4lv1JYbPEn07WLlkKynmRZbHRHDh9vAlel9fbS4qAR3xkZa3El
HB4fjyvq1tvx6mG80lntS8ivxyrxWrbaxTy89uC1oX03/QWGuW4brhSK5PdGthb2qxipxU3rJb+XUAKug6XjutXF3HbSFnw7XBwQyXrKQnQhFhoa
kmvSFuoa+tUkL8QfdNUYrBL+WgB/4ZMD3Y/iGl//DmcCkN8LdJXQ32qLCTu7Ss4+usxZvuCcdDZ8VuoOd0tnwmek0+HT0pfhL6VT4VPSF+EvpK5w
l/R5+HPpZPikdCJ8QjoePi4dCx+TjoaPSp+FP5OOhI9In4Y/lQ6HD0ufhD+RDoUPSR+HP5Y6w53SR+GPpI5wh/Rh+EOpPdwuHQwflA6ED0gfhD+Q
9of3S++H35f2hfdJ74Xfk/aG90rvht+V9oT3SLvDu6Vd4V3SzvBOqS3cJu0I75C2h7dLfwz/UdoW3ia9E35H2hreKr0dflvaEt4ivRV+S9oc3iz9
IfwH6ffh30u/C/9O2hTeJP02/FvpzfCb0m/Cv5E2hjdKvw7/Wnoj/Ib0q/CvpNfDr0uvhV+TXg23ILW2Ll26dBnS8uXPPvvsihXPIa1cufL5559f
hbR69eo1a9asXfsioZdeemndunUvE1q/fv0rSBuQXqX0OtIbhDYyepPRJk6//3tIycTL4CXS0kk1rEJSNWkCtoS2CFuG7aPtXLsW24wtJx3AfmBv
SKdWrMD+LV9Ouoo9bm0lnW9ubm5qWrx48UKkxsaGhoZ6pFDoiSeeePzxx+cjzZs3LxAI1CLNmTPH7/fPnj37YUKzZs2aiTSdUjWSD6mSUDmjMkal
nLx/DymZeBm8RFo6qYZUxyomTcCW0BZhy7B92ErSWGwztpx0APuBvQmFSMewf42NpKvY46Ym7LsG/+U3w68Bfy2FXgE/Dr2CO0NeRV0L+GZOW/4e
UjJp2UHlBIULGB/0YgLGAoQJ1mpY4GYGWH5L/Bs5/KEQh18L/hwt+HHoFdwZ8irqWsCLOHn+HlIyadlB5QSFC1Q+iDOBygJztCzAGYCwAGWARi3+
rVr4VxD4FdnXgP+iBvr1KvQ3466irgV8K6dtfw8pmbTsoHLCzXygMsF6DRO82IsFFB2wgnBAnAFa/wL+ivBT+G+SfAY+F/qbkY8Dr8XcpZKjb4on
1vJCbzbQcgFXBd9nAcoBCgM8Thngb8W/l+xztX+z3PfCXkE+DrwW87ir2tY3xRNreaE3GzAu0PDA9/TAS5wDeumAW+LfpIWf6/5esh8Hv5fc90Je
gT2OuhbuiSrZ+6Z4Yi1D9OYExgcaLuitBzQs0EsHUBugZYAmLf7PKvA/z+Hn6HO1rwo+BZ9Dz6ReQV6LuxbuXSrt6ZviibUMoeWDOBdwTUCZIO4Q
EBZQfAHOAdwN4Azw7C3xb1Dhf4LBz9GPS75G7jn0iswz5LW4a+GeoFJ+3xRPrGUILR8wLtDoAsoEGj2g0QKcAwgDPKEyQMMt8GfG/zlF+onwc83P
Fb/G4CtiH5d6BXkt7nG496q0r2+KJ44zhJYP4lygagKuCDTugGIGuBXgNoA6AdwHvBl/pvxDivQT4eeKP672FYOviH1c6hXktbjH4c5TydY3xRPH
GULLB3EuUDUBVwSqOxA3BNwMUBWg2ADmA/bCf5ki/hT+VXH4NbKvaH0KPjP2itQrql4FXos6QrpfpQN9UzxxnBk4H3A2UIyCogmYS8BYQLEEGh2g
MsAqbgKYAlimwZ/7/oryf/xm+LnNp1pfEfybpJ7p+bi4q6gjpDkqWfumeOI4M3CtwNmAGYVemkBRA8wSaMyAhgEeV0wAnwPcAv/nqPZnul9R/Yrs
KyZfsfcUfK3UMz2vAK+ijpC2q9TRN8UTx5mBMwK3DkwVaHiAswDVAtwZUHSAagS4BlAUwPfxV8SfSX9c9ccVPzP5vcDXSj0DXhF3FXWEdKxKY/qm
eOI4M3BG4NaBqQJFE9zEAsQZ0JgB1QhwDaAoAC3+zPujxp+4/r2Fn3h9FP7e4FPBV7CPCz3X8IqkayHvJHSob6LptMygaAVuHeKqQOUBqgZ6swDz
A4gR0KoAOgkgLgDzADn+zPujxl+x/VT4qeEnml+RfQ34VPB7Y880PdXhiqRrIR9NKLtvoum0zKBoBW4dmEnoxQNUDWhYQNUBxAgQDqAqQPEBiAvA
PEAt/hrtz6U/LvxE9Wv0vir438eeS7wi61rIDxM60jfRdFpmUHQC1wa35AGmBjR2gPkBqgpQNYBiAb6Hv6r9VemPC78i+9TfY+BTwVc0fhx7LvGK
rGshH0koq2+i6bTMoOgErg20PMCsgaoGqEOIHKDqAFUFqBpAtQBa/Kn6p+JPXH/q97MZPzf81Odjok/dPQV8BXtF33ORj8u6FvKjhI73TTSdlhni
OoErA8UeqDygsAB1CJkSYH4AdwOoDSDzADYJoAqAGYCb8KfiT20/s/wUfur1UbOv6H1u8G+SexV6Lu4K5hz1TEKWvommi3MC5QWuEFQmuEkPcHdA
tQPMF6SeIPUDqRfAfACmAG6Jv2r8Kfwv8hk/N/xvxEWf6H1m8LVyz7DXQq9gzlE/Sairb6Lp4pxAeaE3E8R5gOsB6g7E7QBRAtwTfIWvBrxIGUDj
AvTCn5r/uPEPcPip1694fczfV/Q+U/pa7Jm6j6t5inpmZhz1IYQG9000XZwTKC9wJqDKgBmEXjxATUHcDlArwD1BNhNgDBDQuADcAeD4k7UfZeFH
sf2K7mcTvo3c5YuL/i4m+b2x55qeQs/lWUH9FKHTfRNNp3CCqhMUJiBscDMPMJcwrgTolJCvCKg2gPkAyjIQXQOK40/WfpSFHzrtnxPX/dzwE81P
RZ/pfT6908o9l3kVei7PCuqDCGX0TTSdwgmqTlCYgOmC3nqAuYSKHUAlUEZ1AHcDuA2YQxcClGUgugakxZ86/2zqR20/m/VR3U+EfyPV/Ez0tymi
v5e5elrs49Cr4q6g3k3oXN9E0ymcoFUIGiZQeIA5hXsVJbCNKQFqBTYyFUBtAFsKoPgTF4BOAW7Cnzr/qu+nzPpmUtVPDT9z+lS9T8Fnrp4W+zj0
qrgrqKcTSuubaDqFE7QKQcMEcR6gPqGiBBxMCXjZmgBVAXQ1gM0EVR+QTgFuxp+pfwo/W/TpJfxvKk4fdfn4LE+DPUGfYM+h79IAr6B+ntA3fRNN
p3CChg26VCYgPBC3BcgDfGbInEHuCr7ZSwXwpSBqAbgBuAn/eo4/d/0J/NzxY4bfy4SfunyK6CvYM/QJ9lroOfAK6imEzH0TTadwgsoGWiYgPMA8
As4DihKgHEBVgLeUqwDuBjL8KQM8zjzA7+PPF/6o77dOnfQz4d9END+z+6j5qejv10q+gj2Xego9B15B/SKhS30TTadwgsoGlAm4JojzgMIB+5kS
oNMBujpI3QDmBvKlgHUvKfgTC3AL/JWFP2L8ifLnsz4u/F7V7qPmp6LfS+sr2Guh58ArqCcTMvVNNJ3CCSobaJlAywPcEjAlQKcDzA/wchXAZ4LM
B6gNKMuAfwF/MvVTJn5U+TPHjxr+uN1XRT+OvYK+FnoOvIL6ZUJX+iaaTuEElQ20TMBNQZwHFCWg8QM2s5kAsQHEBCjTwDVsEeAv4T9fdf2Z4091
v2L4PYrdV0VfwT6OvhZ6DryCupHQ3/DjZppO4QSVDbRMoHCAygOKElD8AI/iBlAbwKYB6iRg/t+A/zru+HPHjxr+barqJ8JPRb+35BPstdBz4BXU
ewhF+iaaTuEElQ20TBDnAc4BVAnE/QCyPLyFzQSYDWA+wN+MP/H9mONPdb9i+F2OuN1not9b8gn2Wug58Arq9Ifuur6JplM4QWUDLRNoeYByAFUC
cT/A4VLcAO4GMh+A+oDfw5+s/lDvj/n+a9bGbb/q+FHDz8Dfy8Gnov997LXQc+AV1KOEbvRNNJ3CCSobaJngezygKIF9XAkQK8BmAtwNVH2AtWwR
YCX1AMkK0N+OPxN+xe5TxX8r9KnGp2LPZb4X9CKjW/6ulT/rxQRcF1BFQK3BLTmAmgHFD+Aq4G/En+yS2umUXSHAryHJfrE68i1n7BzuGJNB9yWV
/bij4DLyfWAp+RIbv1Wmx0YLSTX1ANnPphHydGTPSJvkdU+SGq2HXPjsAH777wYr+dZP+x2g8r0gptjXiPu+xl7hXwRuxRpvD+iqnqElr8SSL9Kv
Sicq+w/p59Or8iD9uhtwh6aE1/F/QnNCfQJ+K1wWkupxn6CYFb+BbsL98VpxJ8n6hQL/snIw3xUwjX796D9dJnpAwrZIAXGhEBLrce/PG1fydLJ7
xVgsY0gojcacahRXe2S3aTy2z0h2czOy3d/mkb1Q5VLNnpXT/9LOu/iNKit9TZ59xTg8t4V09H65M6LfsBjoOA+2JeDXwMbPS8+WLsOxu/ES3S1B
rutaDP7jvC0z8+wm/AL8Bu76ZCV7qJVi/oWhO+mzyvx8oRx7U1tnbByP9z4dXuN5XuMIsq8qHa9S+p20h4zujRylDLzOYE9p/KBGC+6QmTZJCEn4
XW9CUAzh7zKvH8+zNw3m44jf15cN4l+LpmCP7sCdJ8iOtjVBHX5pj2Vc77LqcwbiecOtv2zdMHtcYi7uaUzqbMJ0N4ys/sxHMN9QH34jjXkfd0bk
/8BzE0VLp5QR/9b1+nONOJbX57OvXa+30G/3+9F6reyLV/7FLP2+9XoLljcbz2MWQq+ycLeF67UhS87QGoj2YG+GYboCZYe/gBFjLBhj9afwvf7W
4E4o9hX3YtwwkoPu00VHMdqhjPFipQa2Z3BlMH0Cbc8W3At0gl0w++V9UcH8bFvTsLyEx4y4z4Vhrtxo8OOemrJ7DO6THH15aiHy/in6rTC2Pcr3
lMjR415PwpnSPN1q15PJNJ/YaEDeBH96XgLGmUjcHBljBvgRCxPYhE5Xp8sqkmOnw6o/693kqJPBjd+GpFv1Z7ztxSSwuBbceHNZEd335r3YWvzt
bEzZn24hbjYagr1t3Svo/fzFMAjv97V1/1OpJ4BfNjsjCQfs+qNFdpT08gX1g0Nk99PX+ejLTcP8cO1QbrSScSzdiZaOy9qmYZv43p4NRAasZHeW
a2t9Lux7d5xfo7tCQj0pcVae/UWyu+vSpky8Go1XizHlFby+C6+fwFT4y+NrNrzPxvNsNVU1TzUKr724Axty17VkvL8bz/khlI5rgHdj8Dza58Rv
uA11R0MZ9bfVQKSbaUNnRHfMHdGda5KJpC57kOUgnB7pwbLPo3TjL50jW1BGcK83He5WHV2LPDIcr1Px+jmUlyy8NuF1K9Y0Aq9RW0Ub8YzSVY/c
G3k+LtHSt3i/jPWf3y3UPP0a7+dhLtxVMuLNsz98J57rKSfbTR7cqRJ38gvRtJiGPMtitUVwV8fIw5j/Op6zldHFNCgvEeyNHXetjIwmGiCCO3dJ
qAEjYj7bXRplLZJJZO3qDRqDX+xHUkjKq99gPpSbq5fo3Ulll+b1zap0k1Eco9SmPp/dDDlkVw0j0S1XW+m+JUUdxXS3XjNL3ZSGT9bhXjmo39e7
VInKoDtFugJmykGOTWz3anGxwPbsg9LSwqBBqZ3vZo33ZmD6DZ+aUS4U7UVk5A6sZyRtP8q5SHppzL8bcI/Nq2PxHi1JTwTvSWsmklQ9kUaL6TX6
pZ+B5idxp5uQp3ou0Z0QknCfhiylx83QgN/qR7dY9e24JwJkeM8IUG9sJnEjUcJaaA593RHC51ePovVKx3Lqsd50d0Rc3CTnfkrKWawjfIdPmnFH
yyvIcedY+Yx3elyM74T/IDgxXhPW4XU64zXhBbw24nk1ph0b5yR6P0QtCfnpux7GTz2Z2HIdsahXcX94/F09XOux6nHnpYTpjgbJe2YY1BuaSewc
7MNS3OUHd/DlPenAPmBLv3sD64yg3F8mu7Nfb5mPe0GxPetRo90ge4MKR4OD2L6Kphay42DQQM+dAZ3FUb6S7lV0MpjFdr1FmdTXZrB9hMlXAYKr
ypmzBr8GoHtm8T3iktnO+DWwEffy/s3e8rdwF/1Suq/+vz1Nd+mk17+i10G6O+ucVGa7oewE7mRKdmXH/fXLf1zuiF/Tfe1YbO8PjsBXMcUCfMeC
YifdqmAc2ZwAnNOqK6CsoqISfPiFEVSWOR8cRzcrAHYkWxVApa9wOn7DNLMab52+agu4Soot06dh9rKSKowsLCt0V7OyxpGyxtGyiqaMt1iKpuSQ
Qy452HDng6pii8XpqXSSg8tSXjHDQqokn0CR5tyjbqtQiZuMWArwSzNfVbVlSkkV/UrKhV9NAfm4qcrpIjv80wiSkQYHfjvo/2/8yOv/AG01QgM=
"""
JB_TILES_FIRST = 0xC00       # tuiles maison de l'interface dans la S-ROM : zone de remplissage de sfix (0xB69-0xFFF),
                             # jamais affichee.  PAS 0x200 : logo SNK et police double hauteur du splash BIOS/UniBIOS,
                             # lus dans la S-ROM de la cartouche sur AES (pas de sfix sur la carte mere)
JB_TILES_B64 = """
eNrVlN0NwzAIhLsCMAHOBI4nqNT9ZyoOR2q7cRMpT+XlFD7wT3QmpUtBUIVynyeogjN3eYIqOIMjT1AFZ3DkCargDI48QRWcwZEnqIIzOPUBrMAc
edvn9fLLXFR9PvUXj9ue8dk6NP61oW7k434zHuvM+HTdGgW6QNc+X6AL+Lp2+f/FrbvTbt6P/z72jAgcdj2zb22Bfc2lvoR9u0d1+7DggzfLyCrp
AVW3vW3A/oyjLF4XnnfURcF+P/V2ybnkTF4X57HnlUWKCBm3CvnmpeJCVOp3OewXybU/T/ql9jezicb74yYxN8ZZNtP2L6Sh90r/7Dzfh7OIuTMd
vGfhdkiDPVLYI90soDhcc0JufX+z4HESVlqHtptPN7/Cl7YGa3oDXe3LDA==
"""
JB_M1_B64 = """
eNqVVE1sG0UUnh2vZzexu+v82GxANmO7kMU5YBYQYaU6FaK4RaKWQKIVPYQjnCgXsIMDuXAKByRuHJBAqjhuhYQswYE2pqiutQfXilWRA3KlrFSB
UYJpqPDThDe7KeKAhFhp37w38+a97735ZsajV5/YO2y/Sf7n135IDcdXXjhPDv/b+6zat/LkXoFAgUKekIIKhRR4ziw48+CkwcmCk4O8BSz+bjEF
DgNHA0cHxwDHBGcOKmlnCvxPKTtu3POblD1iEDksGmkcKpecaejrE39EXQYt+w9/W/FrVFwpr1VxrNXFIp9uBCcPZBDrttCXTZEoJ3bzOnz4Vlk5
/vYQg9SFzUuNYM/eagRaRhGKPZuhgtrJjCriNsvogvEv3Tn4CtG0ByRzUqS41m3wX6SREvqPAyISNwekETzMb+GcuGKb4qr9pNiyn/GwoPY1iSnE
438fsy1/k9ZbfAYjHGsEK7aOoQ94FBt9VjPE0uWI/7lxSYUFbNkE60K129wakObXNwbkHVkuv4Mn6EWdwg61fSL7YEDrumviql5R5MICvd+dnlzj
+x7OMt1NQU02csqdiZRpdxZqbVRsQ0HboFLEpWBSEKaH7qErCv+LGEtFngR37W6XCIwuUFj/lpvNb3giBPhzb4jVv19cbQrg9FFJg/d6w854R239
uU7rfbXRj08i8yM0WaOvTTpMM1ZkFj066b8zsg3jUCbepGpdfMx/Q6DS4d/Q/hMcis617V13Hjvwuoesc58ngt38LOa3YoysHWzUMCLO/aBXjZ9Q
zZ8iObWO1lk0iln+u5vFSpJMQVSbFHuaA0ZejNQ0jEtJmIwunCELhQxYp900ZnnuaDIDrdHL3SZ3PHSMMiDRc/EwsMwgg+dww4yHQcM0GqYhuDzs
Xe0wYnwn493YpAh17fHPa+0QaEZpXe8WTvBJB6uStZTPrNZbyDeFa4gpC9az9U+Wnz4XaLy8hpRfEo+VF03TPIHJI9aHKOc9ay5UEkfRgxWLHijD
XufurjyQrFpZ7KvuFPTjWE6xkISQPqmQh3YcT3RZXUJuDvcno5fuutMgLtnHdkhlo58cRy8Ldn2HVF1Ntq8uDvkbiE4D66KHEm37PCKekjcEKWy9
Jih/oEQBKRI9E5LYuIGBtSJiYWXo9RTexSRemOCDqodXxjotVM6kp/Wg0HgGnebBMjHMxeJ9ylE4YiYexlIziGn4VdexH2ZgXq6GF4N291wdft3A
d+dyP4m93x+d+gvWp+qq
"""


def _jb_bin(b64):
    return zlib.decompress(base64.b64decode("".join(b64.split())))


def _strip_nop(regs):
    return [r for r in regs if (r[1], r[2]) != NOP]


# ------------------------------------------------------------------ flux Z80
def _jb_wait(out, cur, target):
    d = target - cur
    while d > 0:
        if d <= 255:
            out += bytes((0xC1, d))
            d = 0
        else:
            n = min(d, 0xFFFF)
            out += bytes((0xC2, n & 0xFF, n >> 8))
            d -= n
    return max(cur, target)


def _jb_ops(out, ev, cur, end):
    for tk, reg, val in ev:
        cur = _jb_wait(out, cur, tk)
        if reg in (0x24, 0x25, 0x26):                   # timers : gérés par le driver
            continue
        out += bytes((0xC0, reg & 0xFF, val)) if reg >= 0x100 else bytes((reg, val))
    return _jb_wait(out, cur, end)


def z80_blocks(regs, meta):
    """Écritures YM2610 -> (intro, boucle|None) au format du driver Z80 :
    rr vv (port A, rr < C0) | C0 rr vv (port B) | C1 n (attente n ticks) | C2 lo hi | C3 (fin).
    Temps quantifié en ticks de 32 échantillons sur l'horloge absolue (pas de dérive) ; l'initialisation (avant k0)
    part d'un bloc et la musique est décalée du temps qu'il faut au 68000 pour la relayer."""
    k0 = meta["k0"]
    n_init = sum(1 for t, r, v in regs if t < k0)
    shift = -(-(3 * n_init) // JB_FEED) * JB_TICKS_PER_FRAME
    q = lambda t: max(0, (t - k0 + JB_TICK // 2) // JB_TICK + shift) if t >= k0 else 0
    ev = [(q(t), r, v) for t, r, v in regs if (r, v) != NOP]
    ls, le = meta.get("loop_start"), meta.get("loop_end")
    if ls is None or le is None or le <= ls:
        out = bytearray()
        _jb_ops(out, ev, 0, q(k0 + meta["length_samples"]))
        out.append(0xC3)
        return bytes(out), None
    tls, tle = q(ls), q(le)
    if tle - tls < 2:                                   # boucle plus courte qu'un tick : jouée sans boucle
        return z80_blocks(regs, dict(meta, loop_start=None, loop_end=None))
    intro, loop = bytearray(), bytearray()
    _jb_ops(intro, [e for e in ev if e[0] < tls], 0, tls)
    _jb_ops(loop, [e for e in ev if tls <= e[0] < tle], tls, tle)
    return bytes(intro), bytes(loop)


# ------------------------------------------------------------------ LZSS (décompressé par le 68000, fenêtre 32 Ko en RAM)
# Groupes : 1 octet de drapeaux (bit 0 d'abord ; 1 = littéral) puis 8 éléments.
#   copie courte : 0LLL OOOO oooooooo          longueur 3..10,  distance 1..4096
#   copie longue : 1LLL LLLL 0OOOOOOO oooooooo longueur 3..130, distance 1..32768
def lzss_compress(data, progress=None):
    """LZSS du jukebox (format lu par le 68000).  progress(octets traités) est appelé tous les 16 Ko environ."""
    n, out, heads = len(data), bytearray(), {}
    i, fpos, nb, fl = 0, None, 8, 0
    nextp = 16384
    while i < n:
        if progress and i >= nextp:
            progress(i)
            nextp = i + 16384
        bl, bd = 0, 0
        if i + 3 <= n:
            lim = min(130, n - i)
            for j in reversed(heads.get(data[i:i + 3], ())):
                d = i - j
                if d > 32768:
                    break
                if bl >= 3 and data[j + bl] != data[i + bl]:
                    continue                                    # ne peut pas faire mieux que la meilleure
                l = 3
                while l + 8 <= lim and data[j + l:j + l + 8] == data[i + l:i + l + 8]:
                    l += 8
                while l < lim and data[j + l] == data[i + l]:
                    l += 1
                if l > bl:                                      # candidats par distance croissante
                    bl, bd = l, d
                    if l == lim:
                        break
        if nb == 8:
            if fpos is not None:
                out[fpos] = fl
            fpos, nb, fl = len(out), 0, 0
            out.append(0)
        if bl >= 4 or (bl == 3 and bd <= 4096):
            nb += 1                                             # drapeau 0 : copie
            d = bd - 1
            if bl <= 10 and bd <= 4096:
                out += bytes((((bl - 3) << 4) | (d >> 8), d & 0xFF))
            else:
                out += bytes((0x80 | (bl - 3), d >> 8, d & 0xFF))
            end = i + bl
        else:
            fl |= 1 << nb                                       # drapeau 1 : littéral
            nb += 1
            out.append(data[i])
            end = i + 1
        while i < end:                                          # positions indexées (48 au plus par motif)
            if i + 3 <= n:
                k = data[i:i + 3]
                lst = heads.get(k)
                if lst is None:
                    heads[k] = [i]
                else:
                    lst.append(i)
                    if len(lst) > 48:
                        del lst[:16]
            i += 1
    if fpos is not None:
        out[fpos] = fl
    return bytes(out)


def lzss_decompress(comp, size):
    """Même algorithme que le 68000 (référence de test)."""
    out, i = bytearray(), 0
    while len(out) < size:
        fl = comp[i]; i += 1
        for b in range(8):
            if len(out) >= size:
                break
            if fl >> b & 1:
                out.append(comp[i]); i += 1
            else:
                b1 = comp[i]
                if b1 & 0x80:
                    l, d = (b1 & 0x7F) + 3, ((comp[i + 1] << 8) | comp[i + 2]) + 1; i += 3
                else:
                    l, d = (b1 >> 4) + 3, (((b1 & 15) << 8) | comp[i + 1]) + 1; i += 2
                for _ in range(l):
                    out.append(out[-d])
    return bytes(out)


def fmt_eta(s):
    """Durée restante lisible : « 12 s », « 3 min 05 s »."""
    if (s or 0) < 1:
        return "1 s"
    s = int(round(s))
    return f"{s} s" if s < 60 else f"{s // 60} min {s % 60:02d} s"


class Cancelled(Exception):
    """Calcul abandonné (la sélection a changé entre-temps)."""


def lzss_many(blocks, progress=None, stop=None):
    """Compresse une liste de blocs.  Moteur natif (m1render --lzss-batch, ~25x plus rapide, résultat identique
    octet pour octet) ; à défaut, la version Python.  progress(fraction 0..1) ; stop() -> True abandonne (Cancelled)."""
    total = sum(len(b) for b in blocks) or 1
    eng = None
    try:
        eng = find_binary()
    except Exception:
        eng = None
    if eng and blocks:
        tmp = tempfile.mkdtemp(prefix="ngt_lz_")
        try:
            ip, op = os.path.join(tmp, "in.bin"), os.path.join(tmp, "out.bin")
            with open(ip, "wb") as f:
                for b in blocks:
                    f.write(struct.pack("<I", len(b)) + bytes(b))
            proc = subprocess.Popen([eng, "--lzss-batch", ip, op], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    stdin=subprocess.DEVNULL, text=True, errors="replace", **_NOWIN)
            sizes, k, acc = [len(b) for b in blocks], 0, 0
            for line in proc.stdout:
                if stop and stop():
                    proc.kill()
                    proc.wait()
                    raise Cancelled()
                if line.startswith("P "):
                    acc += sizes[k] if k < len(sizes) else 0
                    k += 1
                    if progress:
                        progress(acc / total)
            proc.wait()
            if proc.returncode == 0:
                o, pos, outs = open(op, "rb").read(), 0, []
                while pos + 4 <= len(o):
                    n = struct.unpack_from("<I", o, pos)[0]
                    outs.append(o[pos + 4:pos + 4 + n])
                    pos += 4 + n
                if len(outs) == len(blocks):
                    return outs
            dlog(f"lzss-batch: code {proc.returncode}, Python fallback")      # moteur ancien ou erreur
        except Cancelled:
            raise
        except Exception as ex:
            dlog(f"lzss-batch: {ex}, Python fallback")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    outs, acc = [], 0
    for b in blocks:
        if stop and stop():
            raise Cancelled()
        outs.append(lzss_compress(b, (lambda x, a=acc: progress((a + x) / total)) if progress else None))
        acc += len(b)
        if progress:
            progress(acc / total)
    return outs


# ------------------------------------------------------------------ paquet (index + flux + V-ROM)
_JB_CACHE = {}


def _jb_game(path, idxs, base, progress=None, stop=None):
    """Un jeu : (pistes avec blocs compressés, bloc V-ROM, titre, nb pistes du fichier, octets bruts, déclenchements
    ADPCM-A par voie [6]) - en cache.
    progress(fraction 0..1 de ce jeu), étapes pondérées par leur durée mesurée."""
    key = (_ngt_sig(path), tuple(idxs), base)
    if key in _JB_CACHE:
        return _JB_CACHE[key]
    prog = progress or (lambda f: None)

    def chk():
        if stop and stop():
            raise Cancelled()
    data = ngt_data(path)
    ok, why = check(data)
    if not ok:
        raise ValueError(f"{os.path.basename(path)}: {why}")
    h = read_header(data)
    # parts mesurées du temps de chaque étape (compression native ~6 %, en Python ~60 %)
    try:
        native = bool(find_binary())
    except Exception:
        native = False
    w = (0.21, 0.40, 0.32, 0.07) if native else (0.09, 0.17, 0.13, 0.61)
    a1, a2, a3 = w[0], w[0] + w[1], w[0] + w[1] + w[2]
    loaded = []
    for k, i in enumerate(idxs):
        loaded.append(unpack(data, i, False))
        prog(a1 * (k + 1) / len(idxs))
    chk()
    new_regs, blob, _ = reduce_samples_multi([_strip_nop(l[1]) for l in loaded], loaded[0][2], base_page=base)
    keys = [0] * 6                                      # déclenchements ADPCM-A par voie (port B reg 0, bit 7 = 0) :
    for regs in new_regs:                               #   le cri du Toasty emprunte la voie la moins utilisée
        for _, r, v in regs:
            if r == 0x100 and not v & 0x80:
                for c in range(6):
                    if v >> c & 1:
                        keys[c] += 1
    prog(a2); chk()
    pairs = []
    for k, ((m, _, _), regs) in enumerate(zip(loaded, new_regs)):
        pairs.append((m, z80_blocks(regs, m)))
        prog(a2 + (a3 - a2) * (k + 1) / len(idxs))
    chk()
    flat = [b for _, bl in pairs for b in bl if b is not None]
    raw = sum(len(b) for b in flat)
    comp = iter(lzss_many(flat, lambda f: prog(a3 + (1 - a3) * f), stop))
    tracks = [(m, [None if b is None else (next(comp), len(b)) for b in bl]) for m, bl in pairs]
    try:
        title = game_title(h["game"], {})
    except Exception:
        title = h["title"]
    res = (tracks, blob, title or h["title"], len(h["tracks"]), raw, keys)
    if len(_JB_CACHE) > 64:
        _JB_CACHE.clear()
    _JB_CACHE[key] = res
    return res


def jukebox_pack(selection, progress=None, stop=None):
    """selection : [(chemin .ngt, [indices])] -> dict index / streams / vrom / games / raw.
    Offsets de blocs de l'index relatifs à `streams` (layout_prom les rend absolus).
    progress(fraction 0..1, secondes restantes estimées ou None, nom du jeu) ; stop() -> True : Cancelled."""
    vrom, streams, gtab, ttab, games, raw_total = bytearray(), bytearray(), [], [], [], 0
    akeys = [0] * 6
    sel = [(p, sorted(i)) for p, i in selection if i]
    total = sum(len(i) for _, i in sel) or 1         # poids d'un jeu = nombre de pistes choisies
    st = {"done": 0, "work_t": 0.0, "work_u": 0.0}

    def report(gw, f, name, t0):
        if not progress:
            return
        cur = gw * f
        el = time.time() - t0                       # temps passé sur ce jeu (les jeux en cache ne comptent pas)
        wt, wu = st["work_t"] + el, st["work_u"] + cur
        left = total - st["done"] - cur
        eta = (wt / wu * left) if (wu > 0 and wt > 0.8) else None
        progress(min(1.0, (st["done"] + cur) / total), eta, name)
    for path, idxs in sel:
        if stop and stop():
            raise Cancelled()
        base = len(vrom) // PAGE
        name = os.path.splitext(os.path.basename(path))[0]
        gw, t0 = len(idxs), time.time()
        cached = (_ngt_sig(path), tuple(idxs), base) in _JB_CACHE
        report(gw, 0.0, name, t0)
        tracks, blob, title, of, raw, keys = _jb_game(path, idxs, base, lambda f: report(gw, f, name, t0), stop)
        akeys = [a + k for a, k in zip(akeys, keys)]
        if not cached:
            st["work_t"] += time.time() - t0
            st["work_u"] += gw
        st["done"] += gw
        first, s0 = len(ttab), len(streams)
        for m, blocks in tracks:
            offs = []
            for blk in blocks:
                if blk is None:
                    offs.append((JB_NOLOOP, 0))
                    continue
                comp, size = blk
                offs.append((len(streams), size))
                streams += comp
                if len(streams) & 1:
                    streams.append(0)
            secs = int(round(m["length_samples"] / m["rate"]))
            lsecs = 0
            if offs[1][0] != JB_NOLOOP and m.get("loop_start") is not None:
                lsecs = int(round((m["loop_end"] - m["loop_start"]) / m["rate"]))
            # +24 : durée d'un tour de boucle (s) -> en mode AUTO le jukebox joue intro + 2 tours puis enchaîne
            ttab.append(struct.pack(">IIIIHHHHH", offs[0][0], offs[0][1], offs[1][0], offs[1][1],
                                    len(gtab), m["track"], min(secs, 0xFFFF), 1, min(lsecs, 0xFFFF)) + bytes(6))
        gtab.append(title.encode("ascii", "replace")[:24].ljust(24, b"\0") + struct.pack(">HHI", first, len(idxs), base))
        vrom += blob
        raw_total += raw
        games.append({"file": path, "title": title, "tracks": len(idxs), "of": of, "vrom": len(blob),
                      "stream": len(streams) - s0, "raw": raw})
    if progress:
        progress(1.0, 0.0, "")
    index = b"NGJB" + struct.pack(">HHII", len(gtab), len(ttab), JB_HDR, JB_HDR + JB_GAME * len(gtab))
    index += b"".join(gtab) + b"".join(ttab)
    return {"index": index, "streams": bytes(streams), "vrom": bytes(vrom), "games": games, "raw": raw_total,
            "adpcma_keys": akeys}


# ------------------------------------------------------------------ évaluation (avant construction)
JB_MAX_NUM = 99                 # jeux et pistes par jeu : numéros affichés sur 2 chiffres par la ROM


def evaluate_cart(pk, profile="standard", margin=JB_MARGIN):
    """Chaque mémoire doit tenir dans (1 - marge) x limite.  -> dict rows / ok / margin / profile."""
    P = JB_PROFILES[profile]
    m1 = len(_jb_bin(JB_M1_B64))
    code = len(_jb_bin(JB_PROM_B64))       # taille réelle du programme (layout_prom : programme, index, puis les flux)
    p1 = (code + 15) // 16 * 16 + (len(pk["index"]) + 15) // 16 * 16
    pused = p1 + len(pk["streams"]) + JB_MARK * (P["prom"] // MB)
    rows = [("P-ROM (program + index + streams)", pused if p1 <= MB else P["prom"] + 1, P["prom"]),
            ("V-ROM (ADPCM samples)", len(pk["vrom"]), P["vrom"]),
            ("M1 (Z80 driver)", m1, P["m1"])]
    out = []
    for name, used, lim in rows:
        allowed = int(lim * (1 - margin))
        out.append({"name": name, "used": used, "allowed": allowed, "limit": lim, "ok": used <= allowed})
    # l'écran du jukebox affiche les numéros de jeu et de piste sur 2 chiffres (put2 / b2d du 68000)
    why = []
    if len(pk["games"]) > JB_MAX_NUM:
        why.append(f"{len(pk['games'])} games, the jukebox shows at most {JB_MAX_NUM}")
    why += [f"{g['title']}: {g['tracks']} tracks, at most {JB_MAX_NUM} per game" for g in pk["games"] if g["tracks"] > JB_MAX_NUM]
    return {"rows": out, "ok": all(r["ok"] for r in out) and not why, "why": why, "margin": margin, "profile": profile}


def format_eval(pk, ev):
    P = JB_PROFILES[ev["profile"]]
    L = [f"Cartridge: {P['name']} - safety margin {ev['margin'] * 100:.0f} % under each limit"]
    for r in ev["rows"]:
        L.append(f"  {r['name']:34s} {r['used'] / 1024:8.0f} KB / {r['allowed'] / 1024:7.0f} KB allowed "
                 f"({100 * r['used'] / r['allowed']:5.1f} %)  [limit {r['limit'] / 1024:.0f} KB]  {'OK' if r['ok'] else 'TOO BIG'}")
    if pk["raw"]:
        L.append(f"  Stream compression: {pk['raw'] / 1024:.0f} KB -> {len(pk['streams']) / 1024:.0f} KB "
                 f"({pk['raw'] / max(1, len(pk['streams'])):.1f}x)")
    for g in pk["games"]:
        L.append(f"    {g['title'][:30]:30s} {g['tracks']:3d}/{g['of']:<3d} tracks  streams {g['stream'] / 1024:6.0f} KB  "
                 f"samples {g['vrom'] / 1024:6.0f} KB")
    L += ["  TOO MANY: " + w for w in ev.get("why", [])]
    L.append("VERDICT: " + ("the ROM can be built." if ev["ok"] else ("build REFUSED (too many games or tracks)." if ev.get("why") and all(r["ok"] for r in ev["rows"])
                                                                else "build REFUSED (at least one memory is above the margin).")))
    return "\n".join(L)


# ------------------------------------------------------------------ construction
def jb_bank_marker(n):
    return b"NGJB BANK " + bytes((n, n ^ 0xFF)) + b"\x55\xAA\x55\xAA"


def layout_prom(code, pk):
    """Programme + index en P1, puis les flux ; un marqueur au début de chaque Mo à partir de 1 Mo (le 68000 les
    vérifie au démarrage et les saute en lisant).  -> (image P-ROM, nombre de banques P2)."""
    d = bytearray(code)
    d += b"\xff" * ((-len(d)) % 16)
    idx_off = len(d)
    index = bytearray(pk["index"])
    d += index
    d += b"\xff" * ((-len(d)) % 16)
    st = len(d)
    if st > MB:
        raise ValueError("program + index do not fit in P1 (1 MB)")

    def phys(l):
        q, b = st + l, MB
        while b <= q:
            q += JB_MARK
            b += MB
        return q
    ng, nt, goff, toff = struct.unpack(">HHII", bytes(index[4:16]))
    for t in range(nt):
        e = toff + JB_TRACK * t
        a, al, b, bl = struct.unpack(">IIII", bytes(index[e:e + 16]))
        index[e:e + 16] = struct.pack(">IIII", phys(a), al, phys(b) if b != JB_NOLOOP else JB_NOLOOP, bl)
    d[idx_off:idx_off + len(index)] = index
    data, pos = pk["streams"], st
    while data:
        if pos % MB == 0 and pos >= MB:
            d += jb_bank_marker(pos // MB - 1)
            pos += JB_MARK
        n = min(len(data), MB - pos % MB)
        d += data[:n]
        data = data[n:]
        pos += n
    banks = max(0, -(-(len(d) - MB) // MB))
    struct.pack_into(">I", d, 0x144, idx_off)
    struct.pack_into(">I", d, 0x148, 0)
    struct.pack_into(">H", d, 0x14C, banks)
    return bytes(d), banks


def prom_split(img):
    """-> (P1 1 Mo, P2 à la plus petite taille standard qui convient, ou None)."""
    p1 = img[:MB].ljust(MB, b"\xff")
    rest = img[MB:]
    if not rest:
        return p1, None
    size = next((s for s in JB_P2_SIZES if len(rest) <= s), None)
    if size is None:
        raise ValueError("P-ROM larger than P1 1 MB + P2 8 MB")
    return p1, rest.ljust(size, b"\xff")


def _bios_parts(bios_zip):
    """Bloc de sécurité (122 octets, exigé par le BIOS pour lancer la cartouche) et police sfix, pris dans le BIOS
    fourni par l'utilisateur (neogeo.zip) : rien de SNK n'est embarqué dans NGT Studio."""
    z = zipfile.ZipFile(bios_zip)
    names = z.namelist()
    sig = bytes.fromhex("76004a6d0a14660000") + b"\x3c\x20\x6d"
    sec = None
    for n in names:
        d = z.read(n)
        for u in (d, bytes(b for p in zip(d[1::2], d[0::2]) for b in p)):
            i = u.find(sig)
            if i >= 0:
                sec = u[i:i + 122]
                break
        if sec:
            break
    if not sec:
        raise ValueError("security block not found in this BIOS zip")
    fix = next((z.read(n) for n in names if os.path.basename(n).lower().startswith("sfix")), None)
    if not fix:
        raise ValueError("sfix.sfix (BIOS font) not found in this BIOS zip")
    return sec, fix[:0x20000].ljust(0x20000, b"\0")


JB_FORMATS = ("mame", "darksoft", "neosd")
JB_SPR_TILE0 = 0x100            # = SC_TILE0 de core.S : tuile C-ROM du caractere 0x20, tranche 0
JB_SM_TILE0 = 0x900             # = SM_TILE0 de core.S : petite police (0x20..0x7E) des infos de l'economiseur
JB_CK_TILE = 0xE0               # = CK_TILE de core.S : damier isometrique, 32 tuiles (periode 128 x 64 px)


def _spr_put(region, tile, x, y, col):
    """Pixel (x, y) de 0..15 d'une tuile C-ROM 16x16, couleur col (format MAME : voir jb_sprite_region)."""
    off = tile * 128 + (0x40 if x < 8 else 0) + 4 * y
    for plane, k in ((0, 0), (1, 2), (2, 1), (3, 3)):
        if col >> plane & 1:
            region[off + k] |= 1 << (x & 7)


JB_BOX_TILE0 = 0xA00            # = BOX_TILE0 de core.S : boites animees, 6 tuiles par image (2 colonnes x 3 rangees)
JB_BOX_MAX = 96                 # images de rotation au plus
JB_BOX_FILES = ("jukebox_boxes.png",) + tuple(f"jukebox_boxes{k}.png" for k in range(2, 7))   # a cote du programme
JB_BOX_NP = 6                   # planches au plus (palettes 19..24 et boxdata de core.S : BOX_NP)

# Planches integrees (boite, console, logo et triangle Delta Island ; puces retirees en 2.5.21), deja converties par jb_box_frames : meme ROM, a l'octet pres, que les PNG
# poses a cote du programme (ceux-ci restent prioritaires).  Images SNK : PAS sous licence MIT (voir LICENSE).
# Regenerer : jukebox_rom/tools/pack_boxes.py.  Format (xz puis base85) : nombre de planches (octet) ; par planche :
# images (H), large (B), colonnes (B), rangees (B), palette (16 H), puis les images, 2 pixels par octet (poids fort d'abord).
JB_BOXES_B85 = """
{Wp48S^xk9=GL@E0stWa8~^|S5YJf5<0v%m{#^h9fCo=clitt|u0>6aMXlltnP+VOH$8`p*lVn1jF245sZ|NPs}*M}iI5lXZrvnu
r6Q(<j(+7_g*nAL(5efGR#QJX&ULC-GmF2ltq)fejRGX4Qw*2PnGiU}J%`RtqMk;6xsEYsQU!)gSEgetPO`;HwcoE-Kp-rPl6pAB
exj62NNV|F$4P|>6qxPhP^vl<q5_2bkPebC`aTvs8^s(jQ0#MgQXgmmsQxJC4BnHVvrrbnc%6O72<X<e)IReXW#F7E3dO=8DEnxB
EU^oe`aB**n@gu^^|-*A<P2=yILwN>-wVP&p?1lI=@;p>=rI377BvU|GwoF%fY}CXE7=rTAQg)eocmZnj=RG3xQ&$+XIzWz``h2Q
wn<t@Lqy>faV{FMY5K0x=o^x0w4*8LpgKEw44GXxjNxWMzh6V-(6c?p$UERPU*B(Ql~Xr*_eg0huQ&bmj!4XEMb&@Y>IjGPUgzVv
!RJT?JiHqo4|tIRkKb<<!@!_p6w17^mTT5Y?Wr3QiVg6zxsKq_w-1<W2#HFr2b^PNlBnzi)<_f0Qy@oxH@p(ImCfY_vtSA_P-4#y
>aBrd(m@wwY%(h@%2w*usH+xWZm`_IRF;*&bF(xn&F$0MU)qxj+d*Q6doof90qjEj3*h%n@Ex(V2R~dT779B=Qmt9(9!XfhLC42g
ZP9@+{cH<Q_ZSvR!gU7;8C~4$n+?DTsp%>Kl;}PN@cC-jifiP=jgQ4Jw8BY-eYV7z6WrNK3V>fEF_~Mr+-XHG?v^srO3jY&<uuL5
zYu|Yv3trx<Hjf}6S*+)08z9e*SXYX+sYycEu7s?lOr}X2z9wZ`Zu^<4}KlQ-_fL9!$1V^7NQMxg459h8l4oT2&<&dkwN&-P4kjq
v<uu4GwD>Rgj!&-+UFJudQs^ZxkOsG#ZsfM!%!4hUX&v<^aN(W+*i>&?!k~osjE?Au=q^;Q0D$Tp*^4Mm5CY@`TMYuN>zzXl7<$9
rNvV(K{<NrYRN%Ey5o))LgBS`I|_x7VYUsTr>KJ_(KV(=O7Ga&ApoIu+EXKZ6aCtJ%p-arKJ)F}JD*65EQkjDGx>fKger7yKs1C(
%uh2G;J<XCxP0D#MZ78heOk=v@uL4Z1=V64XFXx%&%(jVRHH}Zobit2E7F~hcLZoz_`#3Q10VLcb^{>sY<usVatD2wCa*7&e&>BJ
-$cC}<U>9YstFkFr75q1VCuj!jp=GK$N*Qe;{gLkOCmyBb~g%brXyqaN6eZ3<-?|FKJwT84b;&RgR&U_Qm`WmT-gRHT8#ixqMKBe
ODo99m8Bs9%)$CEYL_(8$*@99Y5%A?b>WuNQ|}dye2bf0wFgy~EvpR<6d+;RZl~rK3}R&}K-9pVk5z5$nUyF$srN!(2*O}OlPRUm
sxSgUf}&lS<u=y~>7Fyqi9@Zkt0ig=Bhh$93*ed@7yDu3ZF4YubiBP$Ar8f(s6D}?TcI6TTA!R(3j8R>?w*dgqVs)iI?k2N{ve6Q
0k=X&ZF(?h7T>-s@pTB0);0@(X575CCi_=h=Z41ilVmxFtysBA8<F$l)abp)5!dTU?JKQt6>R51Q$7hDLewi5NgFm!ds$dDs+|1t
ZD?H!5NbL_2CJ{L6JxpXK2JPDgy!Q&#+GIOOkU^f{5e&c$!b69EhIjT8}+voWv6MvER6_GpQWj<)g^b);t<6uvBlp`3NTQyNqYf<
Jr|V3{iY7G<;>t)D;3R(WVNoW8G>9!bv;e0Xx7Nzu#gGU9#U&buh?M`JUQ@N_~2%$M&B^$0!><7Hb`}ZZTXbn?|TQ`-pn)z0VNDU
cf-U7ADMu-Nlv+Qt1R8|Bkm|t*Zs3pjZyk~#*Iw@)ygt$-4~SU;P)|1<|dBR*9A&!6`9!AZ*Ep6@<)K|J5IP|rCz}RC+@XuhvZSx
`;Heb-DtpOm1!(YDyxE~mzgP|p%>6ykWa%gqf~%THIZ+hiHH~^ex+AK=6N3fhe;yT80p-YrwSZfoE99k0$siuSPs$<r8W__ikgDP
9g!TuH}*ABffV7IeZ^MHM)dY)a+dd#DYxXR)4px&$I;^>Jedz_MP<t8T%n@6{pjf!rE1>mY>{x|d49!%!fZ0h0mNzrFu~I&W1!SL
BAFO#&1`X2-g3Kb7|3D6S#@gic#jn=sSL*dNwFYX_0lc-WVtZp=9(xBu&#oL{}oR!J%G$JREo9u9T|lAitN}|w%hy>t}OO@q%}iB
%Plx%lPm#A@q<7{GLKy4{(mE?{TL<m2Qmn=X2<ziv4K7HPF&9J%2k{tbb{q&vVLbDECD7dqmPlg(H30JqVR4Ks8d*hhC%nNU5FRw
2Hf?HElRzu6l&om3&7c%Q(5w(PLXo@Rt`Y4Ty41;r{QTRh~YF1^>KE`f#}eI=t8noM7A_VNV&*{2!GG^q|UFV(Lk2`<(964T4S4C
EljuWkhv#NMdPWx_!&Kw<PX+GXF^p8Sh+jLWAVvK%NSFZef`F`Uu#VQgg~)=!cF%MtE7>n2B(DiVUkf~DK00kgIo{eB2P`c2<4dW
_TR%40BD}SOq_al?dJK&hO8G?XElAVw2N);B8=>EXv^Vd2c5`B1?yt2^7Ic#$42(^jrWRpF!u4cDV;IiSsqs2YDtBHpD(jWIHKQ=
7>@KB8(<PSd;W;VuTZ;xA{~c*bGwrr-4D<VJ;<xfEoi~g)GkEo*}PhBLb9vnizi@EaVn^d$=fZSfox@nGHOKG-~01qir48s?_a6{
Vp}&J2`F?iKI09b!X|Fcxjj>Gb-)yQFA=kSmz{m|K7k};U+uyt^33k;p;bp$cTcOeV~3`P)QCNaV5l6xo+~LPfdlpl1^#aj4KHEE
OglXJ7MSt(EPDGGXO(I-MO)SAs_Yo!Sfb}|mni(F%C*4N52$x-9FucqfEG%NOze!d6yjC`x4S7nridY3J5X)2r0yyZ&*5zVv0$gb
z!=W{tOUGxEU&YDy`O6?s*<qFut+I2hmTMdwk>{Kt~@tL0osUqgx2=XqTs<iEx83|L(3;QR1fdds<)K_z0dyU!47V-XN~LDB8nI^
`II2eMsc|?m;Q$2)yLH1{<J((vwr&Qu77-wmhEaQp27(Wwxv)lBa+`vG6f^1Y#BJS9D5;g${`6f{JTKEgTLkr^*z!V8ApsZ&U6`l
=0AZmBA&Ou%g)$IP|ESu+14eEqI5ly(T2Mu&Cmh~QDZ8ZSoNc{w_0atS?)2%{gM6<&etZ{F|u-~6S%ZJ$2Ye$n>6EjSw{A}OzW!=
i}DZ>&<w!=AXA45CVt(FVatqvAZD3VcC`0}f7|3xk<7W)Z|X-c7jAZ2We;CfL1uUJ9QnM^4;KOLN<zhZ-YwXBVWc?5x1ZI?-iBI)
C`nma*wAP|X}WkH59BKK#;Nbj4nUxg=mgy7A7}hY^&<+Z1B$5)J&O^cIN=)V?8@dxmw%2(5=fz-tzu+fBDpGOE1SNVfZX4Z%PJfT
N-Jg0O@H<Xwbq<CT4@u^aY~_3-)U;|dJS+8CBalZ;Oz300AxW!9GJ}S6Pcl)cftsS2BGIIP!LuKJOpLkt(k{wC6gifu8vp8UuHTw
st8#<8wQ$4EA`+V2&yutfy=rBh<zaeEu>__&Q35Hgq%*V#;^ga(5y$_Cm;@&G+o9H`!DtII97<l>i?5H;yO{(&K-95x<(^l*?LfV
Y$QB<9ym?^6F&l?03Id70mlem%G4D*#>4m|8N068Vzd;l%Q;8+9w_cdLT6vKPGCmXkv#{yk*Jup$>TXr%SmCV`_<8)x|ckBxQFCc
{!^^ZwGEe{Tdifc;$Hwi!~Gcmh<(9;u*|32pI(M5nco4EI(`TWUW>?WS?&6AT04144q3ud-{qrALlpNVR)``SF4%*OOro~D{XCZx
_{v=m*d8={pFTIxQ`$<uZ-hMO#p4|t46dgSs~U=is1N-vF<jgb8e&q4^NH5aQ@fP_R7Kq^i#lQ$d{8D=7lS)ExDzR|TdHK%hUz9~
A^Ld@fCSaxUJBXH@b4Mm=i|5LoT!ugisHBOqyOh>$BTRrmJ7so%qKxV&*lY62{g?!*tmiy@5W*p7&t8sYLuZU_c;*3bb1TlE#aBI
h|+)JPTJ2+Zyky2u%qWCAE*TZ&*SOQ)@1b-Rv|dOO3R`8M*Bd)6o{r7+cmym7k2wUMYt;tqN6ixn@odL#3r8ced_mtf!?(fzMd1&
d#Q=FELnhrn^nCsouoZ^y%Vu)5^l4IrO8gKWCP0PLZG`R_?VUV4`Qro10Qjk<lOolX+DL$IqyeC7)EEKHNUx?)tbu>?-$)<RlcE7
VhZ)(VPCV0nOA;EgE9h;_BudsK|F$Z4?gk{s^v62tzs%pVqcurAsDOFYnfR2?ZJTl<0|60%Lju^@B=LPL+?!U(sX%vab<^rw53`W
H{>%+k34+mpRaKs`oX6D-S8Tm#fQ3dt>FCf&?&-CK|$*h*;cR4E#z0P^6tN3MYeVz`)H2xR%z*P*`6b1E~b8J;7OM`S&~CxWGa^B
eQJ{M5%`6COy5D*Kz)pw>KmO`M;dFmW_eEEd)!gW2xfHBOiR-T@j_uW*^VxIc_Eqkv^s1UItH^WpQ?tskYSiQV|@}3x_6TXL7lOf
R?3X?R@&`I+-sF6q4G@zKekq8l=`c>!;g47TEx7)&`G{TuIk!r=n>g<rB~Mc)FZA3&X<8K=4kX(5ovXp5P5YS92bUwaYv*VW{E_I
PH!TBAXUD<8mNA`YpC>Mb&VQkUZ}#Ld2NTJTG|??!*K(uj`AKhg{dTTrFvM{dz&({L0Kc$WwLH)J`dM>HMg7De2CdW2|SJ8SOJbj
S#4V5#3dH{Ktmkz42R8l_We51pKgiSt}A{42AK3SnMmY)hZN;1@bv&Q_~7e^=?7ZVOdph$1i;HrPR3YP8rP}YKqCj(Ez!Hr$96-Y
Bo9+}#nce*`RGq%Xvxo)mP!Lw?gei*x0}@w!%<6)@r#w`5t*$MUCC#1(mw)AJB-Bx4sak&Z~vq}i;n`@haS$0@<5BA>3>bqvQsC*
y57}8Lug{10|z-Ab_CF4Npc_;%k83R_V}}Xp?pi@eE%Mzi8TXvVR3-ac<o&YeET=9sjF94V}Ziq5Tzx%-5=f7C^*NreTRNg-$(V3
myKi6g=sBRsd7s&hg}SDBd$dlQ)mDNZYN*eP75AA`_ui>fbm>-m)1H~I?ta$#S(}VMpH`uW4!?hG*K3=fp9{hOE}^$5DLm@9vIyf
Tv*$rWc6!j7f8sDJopm-eZh}g#fX1|LAv_kafIAccsA$GQp=)FGnp;o{K3YMy2q$-CepLF*a03ia<}jR{CF|KH)u0-<^8hG%Le%I
R+>1@`*wZ<(%|~CR*KXRs;@1pa|&l`#On^H)iO_#3;Te0*e2#{4tUHk062HP=8VEXskoE-UZc2pE=B=ymU78p7hsB4v6kPeb~AiQ
!u+@yrM$azWrzL#89%c)s@im5Qjw>LXN~y_{(KSsBJQu-6>XD)yee|=vHMxCmBD|n4+-?(JsEh*ifjhi1O_U_4Ku}W6IuP@6yKb3
p~ll`;0}1&Cj$uE)PG(XPig`zZNxN%Q?4FCyNFkP%<526QB3f)EU?5Dsi)Y(E~0bs2G%Kv67^#lF>@gA1q9;e#q)luvGDLq5+XgS
JxCVCc3=V0Yr@MoO%Vdcz|f|*?Orw$!<D}8P3^buon5T@T*IAk(edYlA=#7WE%30gAb>8it;@=?w<<--b)6|z)-+^Lc}Oe}>!w&9
3IECoO0LAQq+nTB;~g<&7+Mkf#d5+A&5C4lPT$G@08;WTw0hxp0X)wEVB)>BHX%@!fUO)CZKtdK6UxH(_)3&}6H@wKWp|bmID2Pt
yZ5pj0ao<QceFHlDMgk6{$efS<-b7J?isjQg1^!*IH=Zw<6mNN699t(1^04;1nP<!LMrA9tl-u(G#Gk9r>Mm#ff>hN9`rhH(+0Mu
6C$-An?Lo7BS&qavSL*hg@=%xQuDDQTtFuCIEKkQ%|M2i43F1Rj*=S(8ety;{Lhe}k~{jyt<fZQbGjh*wSp#PBuY6Fp2U(lMxVdE
!KF9f7=$mN5-+B%%NGDQb_!z`i(qu}S;1YP6nmIu9%2T^vYB?u@$cXi2qEwf(Pn2c3jp(c5~l0^<ztyr+oGsu@|x&wy!h8()28&w
OjRq=>a&cb<aQ1I!#|>QtP0!6NnbvLM?vzuwk@vmc@GnFBAr9mTC}#S*oR-i7E32`Y$|Cl$wpr{CIL&!Ow_IhH!&?F73(P!EmYnn
Q4<UJwLEKM0aAOFS~Fp?C{;E)Z)qkD=SO8(?(hrzx^?Kb)LLnK*J`2tDo;V^V?RjAcLi~lJ*Jc|So2Z<NV}h*!^-EHnHVIlXY%+B
!VGuP>$OKtqg0~+L@_jTZh~>zleB7)>ZxgJOy{5Ai`3729NW`NZOEsbUn|^Xp2cK=!2DMLQ3Sq=0orO2Rz$*DpHJZqL~pdSS<DrZ
0sLO9fUm;oQ?y@})WR*x*(y&74!~-n&j6fI(>#Y8J=t+hCIdf+28K8&Xft2l$<0*edx$Oa6FwyE?d-%#d}A-@rClMXL1vNxtlgd>
m=&I2d^;f_1}Kj<61@0eOEO}Z6SgF-GWJKu&<SKpAyPxTds@xH_Q*`It)p_4kW2))@qCqvi>C<xSc21_&Vf5X9ja?cwxD6CYoFS?
wGd>m{Bmiy40*@?n%7CqQ;;5cMs-|?qKgQ&XV6Ajgx<k+tLC6-rZ*co#<o+EQO+_(2uao7P7U9}X#A3|BT;z|r)Xa=ldUN;G%OGT
B1N5*voS^v$5^dY3dC^aKN!=U%r#T%dyXf0RtwgQ=OTJ;i|+{o$BrNkM)DpzgNj8CWH#!lTP*C3u%s-Q0&%WA=UXUf#a(>_!JxZJ
rPUtfHdw#j_z0L7kY@#$N)0wcS6_y4{rAcpbboiAY=g!;1Vn-^Vem4`I<>s^rAv_V)ptbsVA~WzW)!kL;DX&_N*5x*%*lo`5K?+!
mBjY8IpA{S$C0;ZB1temv_|jhX<WoYenc9&8ag(a&yU6&_JrM^&|b5vNk$X|iS(P7>kJ3sSXl>X<)tejcVEQvnyMj+Pk$yZpSDPr
5lG?$Tx`}0G*3^W+6#Q$(@{1gOAmyk<MF*e;D>~$2y6)Kpq}3Jme*wV1?9Jp^eAoNfZ@E-fF#W&Flx&R-}6?VF-oKxn0;c@Ygk<_
tZk)xTBP<KVwF*)wHbHjfDGT268d)~XecaU`{9gi_`B<aU-ZYpwU}h|qWZZNet<-R+Qun?p}FLTGYvC4h&>QS<dg$&ouY{p*O6Mq
<U!yvTnlIZX*;iewOE%6ulB<ZAZ>rtZ^td<wLt3zQN|@we4zB#ADMivA8UfQwxqVaiax7xK5r2n!lbz3EC6{3zuQ;BDPFD$a4WIc
O~L7c0$2Ev9*GF!cp4*JclIR_=~IBQ%X)#RGwHCNM+>2?+}uj0Fj9`2>0`Gl&g<n)WMR@Xw_VVtTLzrvO?{;xn+et7q8W7-mm6??
RZ+{(GB6bYfyYW_tahI)xx9w*RFt6hsjbAo^AEZHP^TKuf3%h4&<AK;`r@`VjJ-9z93r_B=3Hj$c};?X7xaJvuYDv%2Hf!b%h8E*
c5nj><!pcs4T!bt^&$|R!!mEpC9K`{Y@<f12;z*wk32aX-YF!Wup*J$@%4ykp$`^G`Hgu<a9{~#4nP?1a*F)0n(J@CbbOW?boD+t
75M}-iXh`kD~+N>u)=H!Ws1vbQmHSqGt=nCJ-@?U{<Cc%n!kCZ)UoY+zAJs#3PZS%*R9^~VG(Ph6`<uXR)6kSz?4u-fv{*j&XB0s
D4OVx-u-rS{u!7(+aOho#5GsIOoC7vh;{!iyt-6UGK1Ogv}Yeh+^>t-c=QEw#*`JC&=gB~7{m;RLg~|++xrW;w91(lB<4`_I5-Xs
9Tn=kZ6V9zalomyu4ib=Y9not|1=`bA3g=%SDPy8h5&$x5s|kriZ}FpL$2q^xRRqr)KMRfE{;k8#Ea?<q4MEds(S9Ya4Z<QFnXz9
nON9_7K5SyP;3`fPZl6{U5z@pV>yBZ4#<XYAQKR1l|77`44!YAD5Y$HjVlXlSQ1lzR?VMGphx+_S&U}`N8Ty@O&Ztk5Rlv0nKt5K
{qQOZqO8~@b_|hbvxn`e`euyO^0A8sSn1pxr$a@=3USpSM1nC1M{Sv@uT(pbC#ass=fIACesIGZB*&Ye()OPWw-dbP-^L~wf%j_6
m>c{9*2$lzBHL=y-%Ca2={`ndaKJ%csV~G%qp_ugUnO0hoo1yPGR>tg@1<S>?JAFWqvy1tTeBa*_hWM1jl>r_42zz?RdoFaY=SL#
7|06D;$J|eTo&7t%EQ)K)TAhVC_>rHjG-1m%FvW?l0+QWgVPaZ<;3&8<ZjPMlZJJ`&uUW;r1|w1Q{;()zi~k&i4?+Ujd0}Jxgt(M
__#9A%5EEwr}PBt+gBNn#cJ!W{%KqNU%WCGhu@N)ApD+sKwjnPSbBp6GyhPk^)(nwIfPzJZQFY&YO9{jYAs;C=1y$W2NP>kqX&Ny
*DUAFz4%w*FDSx}G==dFQJ#^zUyu&7lASj~@6L$nzB9VLyN=&UO*0~vjQ~{5G=dZP!@oe@;fyd_+TOZY^hY;2lkO_dXv?Ih$X3Y_
{?=Itpq}>U{K5Ap(cFm}{z(@Kx)K3!eI5`X^0#mBFubCr*ZsoO<r&FjY=}>bDwNrRSDI0r=Dq7{zSzwgNk@a=3r(wGQm!58YmO58
NHwF5YQ?jTP?W9tyzvpCz(cO9NpXq%$)-i4<y15U6nPqdZ&f;qy^F%wgYcv4clzLB4_*QY?Yxj(U$cO?x|2tKlo|a8_nF2)@dAd*
B}Q<6)#l%!FCJcwtiSH;X@%AcAZUd>NfTeQ*QFEs$>n4IC^EvqmeBAog+%9~dpDe%`e;2F9c{gMDL%D)E2G^OT}`1Qp`VDF=(67Q
BevE0SK2nT-=n!V4(TFLSzMtd?7BtfKf;6irZ$ADI}J4CMUuvij{I{S&-%IEc#zR-pFA{heVL<yL`<O+ZZGG4N&sbk1{nQ1s-by&
%T91iJNY3IQW1w~G7*pDV@<64<dGEN4d(;nEFvCN9-+=+Wcf$6c_>WlW|tD}2+@9HV^ppmY;v_MSkFKIfz>9+?NEc))~rKF7$2Lw
njy0fK4Y+12C~L{|I-ih)(}PYE(HdRyR${jLznISv!!nSll2hT>A;+_nXuWMu0F&Aojg%mW{r+mo$q?_%@-u?p?dF_=A@{xUhQ;b
EzQ@1k~xy~ZfiQ^vq*mVt%;tkkf>7=6W-YZfj=`6W3B#1=J9K*y2Y0vFRN@#&p3}iJ1EEA|L8c9p(XTjimMi>@yha1hQ0c*dL`au
!PryKd_nNwxn*;Oz^m{@F~v`DWuF}5Pav;E({xkEmOU(JpcPnKN1>MweFJF8K$G9#s9~1f4OmhWBP6pB_5+W8c1OZ4oet{)c?`I1
@b-)GZiHCMe#Dp&YMl}&DB;dgmVH>4D_XrnO6jinm_b93{`*m0S!*-i#=v9WM@e4Gf}08HPppwmWrpE8K#AQkZr((047!<<E<O!n
lVU=b%nk&Kj&Aur{?S}<8IdE6%r&HADSb7%GH4CaUp%10Sb#<(?9AqJ@ZqHs)n6xWEIrePtKZ(u0w-Ra(?c8m{!T1e*!)J1kv@!X
BGHL%R!-}+sA^YrVHi-VpUQ$<ktbz?t@AfS5EZO$lB<*sGLa`K^9ivUh@`PL;s)Gh&9)xgp1L|-im{q5BF1|?Eg9+*@xKZABIq0d
1LanfNMv)rXLqR|R-M`Y<KKiV0`Uzk7%1X=yuP6@#WA|{GXWSl8>JG9g<%@jgceJM8$DY@EEea7lChZBYhx7tdJ#c({_YO(dTH9o
M<OKsQ@>k=(kb$agp0F6kf=05yfbE<PC2ysF%v+Z3k%hZj#lgOX1_C(MVf{&fb>?YV%*{LXf)48MnVVDT6h}Uv=`e;bQqid-r2-h
t;|tZ11Qh7X4HSqR5JlpqQq5rC2h}-6N6n)Jo8GkXkvPD9vz5bBJy3L8Jcob1{7^E5>#KL0Ft+-?$H&Qlmt>h$foti38E+CS@+h2
e`l4>W9r1bGen3m1V!eeZS>^S6$2e5Bq0nL1>X3?RjuHJ<N0u=igvq+{t&Gl4$sARb(YE$qj&-9eNn_{^hu6XFA}GJjw=82+q-Bq
{XU*;Ze~Eh95RH`INd!dsX2(%EdPP7KFqQ2%Nqi$P54j@|A@PeRi?e1#P!{}nHv3(0IE3;eBRk8gWK9->i>z^O@fdL7M<hxCwF()
8rap+Ye#P4&Ig((;UcH}-eraU_n-mF>f0Iad;4G`i^doG$MiJSGs4us8+0-xKGgZVa-D+k6D`XB@dQxFEu(zM=1M|5y38Dsmv>nG
W1?v03*0gynt}9>jzbLkIaGHh;jn$&W~&&DGKJRdrC6eGIt)gHj>TdKGliOQmwuMlL@cgwuX2g{WN!B7(l`{&eT9ln2OZlNb^bcN
-T$dId%Xd*!Ur`{xFs?3i;A+4^t^xw)|Wq-&cQ|JJQhe8)p|;CJ3~zSgc)V@LYPkgCA?QH9!YHWIEqT@xOoqq3eH~qo_mTT(}Vtw
93rozVrLQo!C^GGSTp^==Yz#DZq|D35(`62B)PEb-V|=OWJdNH@tl5_WMxd#KKC6RuSvaUestdklRR~;2jYe1av4_J_P4p4!_j!#
BH)kQEvg%XLC7gEWT91}i9_&EBz7fu98t2-YS<dl&&rG^n8;64bTsSoeQ8Us&G0T+RtAg_W}vM;|Aj<CI<~&)wMOxQmf7GfZ80`S
7^_{a&Sv6NTsBXbd;v06eBFi*544>$km=ZpZ*^zG<a!A<;r9hVBv@GMwD4WM_BiY61mJFHM0EI6#Gv4i|2tukeK{qU_fq2CU}$WA
iax*AVEre~0z)^!-JUkoOMkPv*(Om2a;yFr!5%@}qCFwcjh?Z|!cH;FCsmw1FeXJEpN?D=(Eo&Bt{F04^oM)h+l+_nD=9*ByXIF`
qX4%HaxGq%7V~KteczG5`)kI*rS)LsG7{fTr;VUE(lxo#IK>@Zfu1gMa_7eT(IXwvG_2&-6N8}wBwQUe<6iC_2CdRGCGqLZE4DM!
9w{H;JF5fYn5_|rb8ghvPj1H0v>&K3ivBSpSr-tuQ!{mDgkKc~%S6&>xF+$&TaKVc>KsufKjDNxrM#{t^s&Oh{TomQ#U_-Do03(P
#CNA*3gUuQhuWs9)YN7urdOtCfhn<guXHitD(b^$bO2(KDgdpL)^S$X-y<(8AEbF6Nld~6$~>UucDB3|f&!Bq$kNO8JlACjmS?wO
l~@!KyZ!n0-o)7mvwt#&0)4&5C^#Ae^&aV~xPS;~;Nvb1pLS^*n9NiWv>T+q=J|csEzkb;e^{RJp!7gv6maAl%O@{{p@9i>Yq_H9
C1a?j14ZN$J#V#&MP|5jW*cSxwYGiJu;LjZmiuw)Jtt`uFA8ai;Bpky{%)=V_#BrJL#O-zV~B~PnF5!d$jl#H23CLH8W*B}EIb_d
@p^dYpbB3a97!1Ya(k;Ykty2eYbL@_FYGSK*wdKWkt;_w%M^DOWNH4!)`kMZdgYvk8duX->8*33=l|HoJ!bhmr4K3mUoS%Ec_!Ko
y}@$L+2q(uw$|%!);Uh<II#}_5ryy7{+dn(KjSkeqhx%P4|1CFuuk(v#5X>2V|^1b?bjlJDYMZZp=)$^A2g(EFsX@zlL5)QtL<Vo
YJ8rm`g6F6;6!$<8WMW@BM$Qe=4UvOKwNb0$!&nu=!$jQ_9~W+UPMU(rh*6G4y%*K;{~of6c=M@G@8SLBJQ`~=~yV2`cptqU{Nb(
!k>`j>U?hZmwR{wjYSukT2BLTsE%_(>i<Xm7Ye-!EDN>Bq`LugE%ykg<w2XWx{g51zJR+|$=-^_hxYhu5t+4-JSP{`(O$Kx6oBQ(
LV&u%`|5g!FP5Q=1k9iL&ceXWwctBEs;9RhW1|^LV=)l3%=N2nDP^4i@0Dc}m<UX0YY)RayJwg*_FoRWorF=XUSs6P=x9GnU8WVe
G2985&uA9i&US}gdrkB(Vg}KE#WFFEAu`NXy_bGN3rs*VecQNi^Gr{aNziy-%)GS=dS-#?SCp*r);4n+W`!JnOhDUNzJxCaQ83>M
jA;<gSYZuHdt=G3c@?x21I<kIY@4sIsh@;xb|7$ZZYmTUQ)q()Kf{^s>Hf-75+tO=^%bHh@66o5T5(z_fLS~6ytqDP(_L&^!CAq_
M(ZoLwg{yL=pv|9-WLRFMN1thy@1|E@`_n?15*iH0c_1yzCWUx@3R?^YzO|uZbY$CUunN<KtfX!r<V)A<om^+fPraQOGz%+msmuu
v55pcm|?XYB_t}MWl~%c$}LyFgDYAhSBk{@5qc$cJGPaVHHF)(<$v}INRPyS050zT#Yw%kR)uLOlNybmJnWHXk#{3M`~s{$#Y9q!
7~5J+hxg~2fpwFD|3OAG_txB`tjSM$60y3AR;%>{v;;>r<8`&^WMd1B!l((VHC2`|?b=a=G%)6X9lN0w<-guPFqHY4x?lN>H^I0U
64=B=g}{{+nd@o5BcTogoCwr8F;Q}#kiRh?UXxtwwTM)p4a1A3T|q7+MJO!<uW7=<3q%Dv;b$RRU=9anYol+wh=e>oBsSCI`mdSz
c}m^pyz<Xcg1#oL2p)3ujKO*YcQ&NX)o~3xC?P%^?C2%~f3HH_GfPJi_*%%##=1_2Gw~UdSR@ysUv9lX7)j|9*Y93zaQW<)s;S)u
&z)QAjOmNPv7)Da{~T1O*I>PIO0Qt{ih@)J0{#DQE&!9KlL4z&i;A%v86;7{$Dr`aJJQYwIm$`Vw@a$Hz`np<^Nk*!11dQhks91N
0j2UzMSqv<E2m=$DKis=hu{KU4BB=Haw{$02PQ)bLHm#L(hde?wVMaLY)SQI&WJ2D_>C8NdB8K?|6d6@wUZ@if%c*vT^z7R(o~he
ojj^C(J`oF9K`m(@FTZ=ci7Usm7jTaq^SNzhe+PS8*4=ZzRjyl-TgY2BnTaT<nxTxY+5JYua}*5F_P{uhS&S|K<A76pe-TNjad}q
!ruEqVmJ7~)u`H#0fWBs@Y-eaQl&cSUT}a2pL-XC%&gQFIZRW9bC7FVUg(-Ct{zwZ{NeWhs}G^Ny!~*w=Hw+&V=unIhp?cX!`#o4
Sx@GEhi#_!X)rzrelz8V+8s9jq;8@>?T9|FbTA~|wPV@0qjivGAxvD(97s-gB8+>zjbF;#AQh|lX{a1(8<oUc1!f^_XFTfQGzqp3
lIqGdIJi{lXY%!wn!azISWZbu<Y)7;w(p}ubLwyF#H;9cQ5(jr4_R3OAhdLA(LXgu@iriK8=4vzdkklhEff}wT+`=JZz(065`B2K
p$>k{a&69QPaP?zw`W%OoZ^xp83^=)$bTAC*Js7Z9|cw}R0jgkF`}7?;u3H^Tvb0eGD59h@Y2^38kQ&X3f=pRrIo|`RjcV~!1ixW
w?<6J59zMSTemLfzj!Hsm@7w#EWm<k$-G3r)p6{Apb&si6@5o5$06bvVl=_wI&SCoYJEcrx!+7pAt|`n^-9tNzmZ|_Yk~ay+|2?!
HyKTXng#tTFANruVX+t!z^OQd-V*$Z{$M<8IF4Y39J|PcQrW6|wc$<&X449VkCCkBa(ng}g_6}2tY2*v|JA?*DPPD3WT@%8)7fgt
Iy1Dp@m(bXFK=Rh(ovCgAtT@-aJuKT2n!5G5F1(->#`eDfmPiSJq%vkHblJK8>;FEdsm{RM5^-ud`NSC3XyQ$VBJ3lJ?Li-MoyLp
72#HGrwqYT_vkRIW~5urgW2{QPjd%Z7|K+PvSewP>uTBU6!`{pf5f|}|A|2ZlyD$Dp4C6dNGi4+dTCMh0Ib<#X5>$)Fv)^6+R_u|
Gw2x?)k|dhif4rO+$(R#!ls4V^7@<88m{w7Y)Q)&pq`9U0<S=ypN{e{01C+q4B$QYhKeE<3q3Hvcz!^FJRqu&X~jXTdjq*`rU}WQ
`dQ~Mh6CJCDen5==%STQ??z@GF5uYjp&&(L3CJ#`&f{sXE~=g%*}k?0e(2!)=S2y*t-NQ!<ZEL_5)2VfPPMC^DqWm9f-pPep!k?d
=Mk3r>WRYXIruf<&G>!Y^JAKd4l3+_VWQsN5`O91fOvF1;8V9k%bm`Ot+&m36UTL|m<Ynrh^;+;(}X~a60}LD1ebZ!%Or7KCL%C#
b1fNoFxY{@G-`JQThI`WgkV4#m#eXQwHDH@soq>@AVWxzkkg5PxDu%oNO2Khe5b~B=zp8MG&+nKbhwV#AhzCOj%3;pn+!)!7H*@E
=}9)7;$#4K_YZ*&HAeSJBcU{>N~M&Cs=H2Q1mEN2hDP-ac^`tmlJ6F@1i$#wN)g$%h2{4hG{UL279NuhFPh6KxDGgRUUE1NUyVj^
i^?pLh!_mz3zP&Gkwo9Yc}fn;iKz}v!+Nu)0D<YiKLvJ;WQ3`2v(3he3J+~|?^P!4&HN#Kj#%YbShKi(_}HiEp(HhvbBZ_)iJV{Q
BL&-0+vPHjSm@8Q^x9eMRDtw`Mk|ydYlMZ`9{aiXjj>bG2s7KWzdx9{nxx>_Q5J`t>;Op@VFSr3gohheX|jV)l{NO#N?gf$Su+H@
dt#YJyCLBJbxM7%oR%n|{uzTKo_vA-bI#!i%@nz+4*wH(w>k0Mc0hP}_zPQ2^p7Kg147~v*j)h(Hl^c7Sdq~+Z!!rl1VtcW`BJ4r
Tto6=;u`L|;zim%?06XwcMs7?TVNY3ZZ%emVA)lF*02(I#f}0aNNh01^0ARNyEB7_ltWtgMC-Awn4a0IWSmWtaq0Dor&>@HLaK<g
XOl{w`<aY8-5WlXM#{KS_;=(o9B8X8cHaG?rHz=_aYh*iFaKc4)Pcwv^B2+!g?EIjUAJ_dM_0=X10RJ_09o3q$v8EBXbljQ^JZ5!
5STGG^6JA*^1ytru$|_tO>0fWmt4J!XyKR<b_VS7>yX6cXk|FPa5-xvj(fy^rzi68Ov44D?VeL5i|Cv?CF!WXpXhruR=u~20wIId
k_6<~2<Yf|^^U^`oTjn^ur%xD#F=R@9Ia$7_lZhO@rldX$%raISl51q8+ACnzvkWQbG)szQrFY!0XvYSAWcv=WOxxnZ1G{3+LBo*
OvD@q<?_M6>|L3@=XGAHAmWFLAp8%?pO8PXXMl^)rCT0#b{>n~H@R$DP8}6Y<pjdspBjaxh-jX%x}PfZd3dJf1giy$&+5EV8H+;z
g!yCf63%%*%Uu{xKPPtni<QCs%qy+J+S9Q|ub=tNMq(DVD|QY=+OstdK3(?MXsC1BGLEjnv=Rw^G*=c*7G1C2572{j&94}WqI);4
GzDGf$&5Kt)=(39``t3czaWl2yn#5YEh$&2N5&a7vUPpm&Y7bIj{Kn@y;(XY&L};^{%)-LH$KuCI?R$r{PC%ET$5;d8X|I-)Xl+w
%nvJ0Ixq#vN09?3a>#~N<KlOKIjQYysly~<FoLC$azPza*2aYzzsdfL`OWSgJH68h;#)TkfW}@+6&$*h4=h7U=!mZa+mZG|R2z&u
#@ER$x&+~Ee8e<2ZQkg@KC{g2HI=`By$;7UPai*0peF%%epzw)CvEd2vKa%DeI??1aw{GwU+TLP&D_VyV8H$RV8`ZOffo5!A~ND+
0Y{xpQf)%@PtF6)Y{xv^zBsNccxn`<#LHbes!@>+<>cS<SG7vz=7-vKRR33Y?S@R#{I={$pUW^JIipR0#=DBCh%hf??@`$1Qa)<e
P)S>q!sR8t*?h_E;WD6dOIORGDmIrRdg@p`nSp8p@1%qCAh3z6J6L?UREu(zz>7la%5M>+`}!uZAAA-T2OSpsC+@$_y0mVAI)gR$
IrL=ipkeB(Qoi7)g&Bm|#p<(E5$|z?65|=H?6v`9tUEoWB&t$lY<td0WNHYu?MMzagd}<Ae7)D5#D-$+;ARv%o=7z57_d`Kn8EX)
50B%LAv0qg;Cr^~QKk$As(}EQHsc<Yt);Y_UKq$YN_lS+_W|WY{yw^pXTz;a|FUMXjh9@1-9XtiL#j7`?6&)t{KyMuG*VgORvF|K
46sK@e~`Ou!BQ2T&QV~CGiT--Z=gG;b0cB|CS^l$K!o2pgXVg3Nc<WV*X_*wJVkrSp)E_e61SH<(j#VkQ!**6$~jFE^j3w@;hSCI
cD5E_|Ce6Na7^8A5-oY$_P$d{5a3~L?%A?;*IKIef4g)7e#dAZmRjB0Bt6wmY1oSZ+<LfsqO@lqg7!L377~b*93>!|eb|r!Ocu~5
B!kLRAh=lU%@NyXU3j_<C$V=bfrXfmTw(^U4{Q_$PPcB)TXO&9tj0e3X=*ce;0*ZkV}Tr$=RP&QME`mlI4t8ewsTCQqHaDsPIk@E
dsT_Xkb4jMa9<MC)O(PZrFULVH1+%96<rqjJW!mey`gLPV#bw2_K{hCZLzQG#bYq14%UIN`*Beyu>7Rmj+hQMRCFC>q;5o21NGlh
LR0oN4~oN8{TCJ?`zNe~pDmnywto=&Q026@%JHCyX>C4zA~#0&o3%E&mOp07XzXWd*kC5`Q0I?*9gdVT%FlU-c+UF<RCr4##jkL^
Nkk+`OmS7i5LW({kzunISg<3#^RfqsAO^{Pz!h@c+_n8um+i$A)NB$hCnNojb(tN9_<Ngy5q>?AJqjxtVfpCvS`biDMs0@IBVKM)
Yimdk{hYH~xXUh$OIfH5E{V<Ooq)3i&-5jNZ^Qa*w=G^3H)*5ODgHa$Cz{v`FUP#V<nqIni?yjf)3OW0XBa^LD~N-qjUqlOEdSb+
M}dbS2`vc@ue<9z(v%9n`o=A3ZMIvtfz}_hYvClcsIwj$TjMa=L{4Jh)uS8<XpI5^?2t$Q+a=CTQ@<>OjotaZ!<jB-n>(Xl@x(oM
H(<vnNmr>)n5^6LLEPPo<gA$~<*#-se|`SB!Cwp6-BX4lYN07P%cTIBsR7;kFu}K(PjtU!KMVC3k3zHz{h?n;$mh>5M^pm{_<}X{
mrN>-4LZTj!XN0V>&QwRIrl~A#y8Jb3EvC0ePSgbe^EjrE#rr5)hC|eg&Cqhp&QIke2|cO8UW5X#D^q~T6E|aTfYM`PO{XW#`QO7
H<FABzTWF!pJw{w=_y&-`};AEhgf$^?plAK901>0V`THBgN0M!4(}shdf1;R&H@=3=3oukAWCtFH?+{~Fw215R)f~TKLD~8-Aq*L
d`P|}anJq8ip(3(>x55s(Zr>+4%M80Dmq+P!r!wLi&|PK45`x;n=mN=NBPJcyh=T^;4`}_i`Q?3^$qeU_4fBE%%5sv;=(>@21>pz
u)0GnGZKInD^LsZ&2)_op>(N47pt~tbe<!<9kgDm3SceD2h6$llE3$%3bTwiUP5`S-tB^+S`+^+H#9CsJN0TbBhlSA$A}71%KoHt
=ya?iwQN!KK>M(8S~6S`gX6af$TH70{?D<`*OehkW?%_IEss(8uVmwi?O3TKiexXQgt2nVc?Td*k0p)}+^e&E9hkH)P356B52mD+
?KLH}*!N)AmqlPfDAFshWy#ICT3nA}|Bsda!4n^FocFJuD>Pm>t&1IvZ|kB%Sf69@&EEEbhWgR>6+&T#g8v;t525sliMXb@nufN3
H+(j+w63Lq<(O0k@rq7R<zZVCuN>-PSkX8=_1d#ZK}@)jgrav!2O(<Oy5~D+=zz1RguQfWl=%hlbU+Xs@OXMZRrQ1ko2i4%3R*3v
{5vfXpCA_IoN)1DjD^7kR7R{EOa4})Njq$FrIb=aRs^&lyP3T)@!(7`iPg^2EdGQIO+zU9{1V_sl$X06UTXXi&c>wtj2SUg<K~jv
2r6g&30b;&MrK$brRo47{a?R4huDa&cuLUou0rpI6}h2*djfB1PKr*JZ%1}O6?I7DxOLinb)+w_zkUI<{ntOB6SFJo+WDo9V$F$=
pd!RD5e`yGC&H;)E{;{|jc(-;2EH*4ohx&1^<|VCH%9G(D$7p%B%mi|*?E%CQgUZJcSW48FhP_IeMMBs=>=zHW*gyHoa66@&PbH1
+7db!XF38`xkeMsVC%UFvpgjdrlpM*V%l~HCQ!>IWM5@O7XYa;9c{WQ4mGpfP!;5#PsZFu9lHfxC^Y$*wMUTC%U#=jMJ%Y~N<sh=
GSGqhK>mpR&!mJAF(HdRRvO`^!emD0c%<DM4rYp?$I13KfuaVY#sYf=_2j9dmj4pgU_QfJk~p9DQj0cz;E0Sfbgv|<P1if$WzOKO
c;}It(fQ|5!3t5v7Q09eA9LV>sFYDqamy$v8ANHV7k;L+e}J59QhOJ{p!}bQ&aLpuJyoC=IzH3&R#N&FefQC-p)4zMSILBl8dq8p
sqbWH$OEu`_db$W9WUtoTD*(nouB$__1ndiy7k>y=DvMgKi^RyCoQ)=%|ws(rxB(#bj}7<hGS*DzPyRd?|>vFRik%`GN9-5V@^Ir
Yaai9R}gKLdGQoFx~c2K(MPidd1=$f0WA6?G5y`WPDy)+FkF)tHp+TQiWW_cH6jn~qS^nTm9S8r1IAS0>sUZZIdX2`R&4icl#pZ#
`H%HRv?o!4Ce(n9GrWK0k!zmMhL@#j>(6cRNU72;xIoy!0ijg}W^0$H=Z<AjC1FhK%>th1cYBCiY-urkT&O;Zqp?A>2n6plFUOSC
V!=k|a8L$(?epZ@nhL*&uvzti{t4K1=hG}XldU`*Oe;w?k|D>#PwRix{XlYh1|~?iE^b-)DLsan=5oDg8{|9&vu>B8o=Ell49^c~
%eKNNdmnwPY2#9H`YQwoN~Wnfhr;ipRmDQ7atNxZ8+pK5d#o^4LZ{d(bQD5m_f8dFG0#&0R=;7+#JCuym=x}RdsrC7dTH9}c+>E!
#2hk#j>Z0M$iO_2o2bvkHqfAeh(ru@_mWYY6Pf0|iMX|S0AKtS9&li)7KLamx_qrsa31{@JfT?9X6v9^V{gC*xfKUQBEmIXXmzgc
gO1?pvwWFyTv<m<8AEKB#3i-0O2a<n!1=2}d{$#QJ-{I|y>fHN4hcV#6exSuILqYLTM<bhrKp<7D)>Hf11L<#scu}ThaPbXvlGWE
p_SDh$(C0lfI9yfCsR761-nOM&DQgxHT7#0xN)=_hop?;U}f$Lj3bXMJ;LOFo&_pzl1dr;I!R<YXRocA221bb*Xn&;6J-#-7uQq7
;WtYmVzreVKN~m5A6tUhCU9c>8nM5S8)U0hua)ZloZ>)4M!!(4vA2*J*pJM#(ZIiuJY~+h6re@Xigt*l+{X}F5vJE5n+%|I90UqC
;duVv2J%qnUn7uMv-?m!ABE5}&=yv8)=>hP^AA9|I9l|V!07-KrcUJg-$<*g!x|Q}l5OwAWNe5Us2AE$(aGoD{1A<d9Z?$Lsb$ih
c_k55NV+N>ATC>WoATzk495S!-*1zvRc*$r14NwvL>?<{uReoa*+vHvQD5*IzX7O5Fqiy^10uGo79I3v;842%^v5S68ne<=jU{j$
rxTJEIdK>$t8wEG0R-v^POoAV!EAO{^1TjVIl+i)NDDjfi4=RDcf)PmKkQ@o?*<(k<fvj0ybe#@;Z>J)EhIohPYk;{CfjCq#7Aq^
rA3f)J666R8#^&x+5IN$UT!y}oxwwG1Vl(F;->g4%`hd<6rR0AWv7~=LPLPO7>6CcqSGJ{VhXN-A9Z)ftr6K*LgNJd(?etCO%xEi
E%)-)vQkWA09~^u017o&FuNCGE=y^m%x8ohH9_I;3h6p1(V$Udc<MMmc(j?I;^VCOtZq23S)MB`H%~kUzF-`{r<F~{wFq0><7I>F
oRzlkYB4Wun_kgQNqz&+n`cWZgeJCk{mrbyspvio5)|#E0=BTUiHC%(Ls%+in+%q|T{|IFaHwy*+<^q-k)J}rW$#~Z_``6RKfT#g
8(VsDD;pIW!y-hyv#%Z@)`w{KqyyHEdXylj+*C3KG!<3;3mBx!6_N;)riEFsIGuFEF3@e6Q-N{y)wQ(*DCLY3D?1!H39XRItuj4<
g>F4QrcVG>f&0||W=sDjsDXeiov*SNXL1Z8bQ{}xN*;ICE_xu{VPFhOrOE?BP>xEaZ-NzPtb0XE$0||3QBG>x<wg|GlgR!8;5^?>
_pjy75;r#cZ{S~UeaW;7k}8261}U&DlBz2co9b*oh9;pS@+W<VZBp{gJ8gUETQ2>uus2C{U0C}HhIifPt&kWTx=}5Om8ma(^Jqb3
K)l!+zW}(A-7+zPDt@$!)B33qe|30c1_J54GEN3yXrzf@y|?M3A&e)LH|HprqKgd$%ZXXIR$~h4tiOJ$pD*8cd)MM05kk$mbVTcJ
<LU{FpK_DxN<q@w`seA_w%E`Yj5B*Mb?Ow)Gp>%x7^%Z<L$<>c>|DO~HwOMyQaL+6xoc8)qE!%?DK~>nX*`*k!rYDvXif9q$!{Z<
4=$Cg-7k|_@gs=f=-M+66_zfN((iMk>%^w0m5s#3^OM4`JYmGJ5QnHnmyY1S$YZrhnI>~wV#{JrS(pLaiI7pmX(P>sOoGvpZC)iM
6NIyR2M(^3*^NxI9Mq_kE?goi{K`|PFdpcOqEkX$$%`kM$#=s{E}M=^IdVYQT>y8!Ua;o;RP$BNWgp@?@tPx%HhrvQQ)@F?ytP-r
|M@Y63e=6m2X2!dd9;gOCB#X68lAwPP`J44&9&wLU-!9bS0)mWtk!HDd9sL^ef3)W$*?^p=7qDhb6?DhQ_)Xwuru6~2YtQjVN=yT
S7C=fyg%`q`bztZ>`uU?to<-T%2tOsWO5j<YuHJcLu^&F0(OOK)_jZ=07c3u;A@dq%LXrB>9DZrE%0K_^8gA%TT~y(vo_&ah)5Df
=hdblZ$p?pa@^a1K9zw9;1-vnmX$EJ+EImW^YnfdrYJz)5q<}@<=zqzXKP!-v;b+_TaapD5kpV2WwSkrOENyGUam?u#@w5`k>9?L
xrQ!JM?!s9ZViFkUU$6lLI)8x{A4{DrH4g}u4o3@Hx7F%kw>_tlU)ALdwt&5RgnqQ#dX|z+Zy`?p#_w9Z&m|NSmQNIuRG+PN&lLm
o~H+g(K#fPgY@@ppk7jBTI8*m9wsnTCP%JUuz-<EW=5d(AknliB7rouP>c_Fh2%3(G&ET*LGBa(cXx?0vzW3Ph;`L~?nl^IyK?B}
fhW3WaxpLN(9bDEnS3JIP%DBWNg-`bWkP1!2BPNJ{(F-8KP7E0r!1NyUvt{nU%0_qeBq>Jj}Sh%@JKV4BY5<%I-B})pRYl$c<?g<
)f^+zqk<Znqp(k42L-&p$>2PI^FSlRky)jl#=zUuW&^&a<^5IxCLmO!Eu{9yva;nZC-DUHQoD4-3TV4Z^`#-|U-E{Th6g)<Dky~q
?MvWSjtQ3TIN2T=f1+4~LYh(4<*nKOieK>eiL~T0l0$>!Zw<mB9Esq$46`fCKkp(TagLL-pH-#ZrUKT<)n-H)0OFF*V})QMdl`3Q
78^#G<*MQoe*&c1X&^8RtpZ3LpDzU~km{!2h@^6};H8`j9Ra*K98|@_Vs(!N;4vwuEPyUJG!SkX<kF+2vmnDBeoN|c!{@{mHV}er
ClQ6^1Blr_U2*iQn6#QBXOEX%MgOObvAJDu<zP*hl9U;jhqsL1$&-K*2r!2oNST)H`2hZm4sup&{=QJN?77kJV}b9gjYbuSKpFK=
0@p)xlc$8=uE+yBT7_&kDC$!Ky{HM8+8C-Ri;s-iCFlkVJBEn~4bw@;mNA08^GUZk0!0My#NY&gxG8^RQ98zAM020`D`_N8@7AM1
zF%I#0HVH)%L1zvK5GtTbKNM`EqUTSGj%6{FgLXI-=!?6QGNVTg9^VSm%}~ym&CG4J3nDjz;3SZq_d*x;5>2+#BTDwB^&6{#!euw
n43Q~l0#^j&xS!!6Lqsw6yK{lM#@N{&7jX`<q~x4_mM<H<a1g2)mVUSR_!ORtu#Yexe8f(+EQ`)-xUIW@mRAkRD`HbvYeVV%l5BM
C6uA&M_A-qmOr*4x=kBwcL+JfW#*mA%Q#Ig53rKMKVjZq6G$8#bzp(!_C=PW1^_E_K0C58A4K7D886-7cE}zk_8yEoa9Vot+VhM(
TW%w6n~W;U@Y)@;&zd3l;Of*lUzA{)Ia!eDHqj&W-;!(?9k_Hh_DK{f8nleKTce$l9R+z6+@qW<HCp9k^r`&{NTh94vlbPkb=Dwo
xCp4rL5L#3jf<ir^jDa<i=tuYNNK9}ffKu7PD@U`b&eM7uo^GaTM{{jfn0oVkgCS`sJqkB<54w-ax}iLH`j0kRcQvURijfmkWpwx
q998Dk<|<qvPp?mEQ?pDG&Q(n!#<jfpcsR1eo~1EdSd03UKd(;%CNITAb9|_2<LyhXI52$M+Une0`#5BNf|lIBNV!TtdGag9x1fu
JF#LycG(65HuCWPB3)q%bWm5~t*6|&okz77$5+nizObI$<HF;pLKqvuZZ)C-Ccn*{jl5<(-jKYTxnzyM4|)Weaw_+lf?hv?T!}-}
-0mAO8lswQ1xzsIT7ZQxK-6qpsfkv}hITe@Edoy&ABC8|Hn<HZ{Ial@f<G!#H1@n|3c=kO2Ei<jqT&OeB7kCj%PyWbW`zLa1IwU?
!MyS;Lhvl62xC;Z`yXU))+%O@V9u<rC7qw1dLeodGZ8y(T<wD%H=DI(+-<5Ro}{s$5`wlcUW#9k4NLo(3Ie5XHq*%w#02Jz5;)~?
Tp7x$A0|n;Md~NIJK5z5?1GGkCLy)I$LZzO`fS*2e~`d32>4Ffu4)lngt`<vV2Kklo1}7sQ!CQp8uBA1Q}YkWkbON&U8xdRSm~2k
*U^f3&r4l$T`^zb)g`<F>iHPqc4IHZz$hY#-83Zb{d5%eVF*vjyt2mFnNIiOu45xJq*%3|-~aEJDh0oyEXg_4$_Y9SePb_8U-F<z
K&wNdMU|z+CDEI>7#S*^k+TBPtbre-2`9?MRperImV1kFJMk6@>H9^2N45_kfN$6*ibpSWrNpZg&(#ZuuUr05r39^Bb(y8f5?X)t
MMAdp_fo^6-3emwJR`@t`U0?%c`=TGE+kk)AZ!Q(g2RB*msLZZHRM{vn#Iod!0@je|2rfninrpI6DcW`#q+N_cqF+g+%df6uD@}q
8EUM;cHi+}ZJ1Hm3w0Q>{cnah4qbwbCoC{~?3mu8U58*QUG^Q~o6my=in_?R1A6hQr#ggCXs+FSM;y%hu3WQlRT#5XlGZ)bB~8@5
gtD2@;&c`(KG(Po*AliQ@49%0!uK97pohN|?ykyrVc3t3Vs%W&RGl3;8>OK&RM6H<R)sySXWr4lU;m7XgpX%PGZZWeo%J!peT**X
Fct8>lgSn*;8?<1IOF!uKL>xmMo7nC7Jq16W9R3KrXxntCq&WE4P4JaK%Mc3SizkQ<sPYh*&xz~OUH)-wu9?&U?RO+d*jBrmCOdI
5^E*lU<9#%9#;{Fx<~!V82AGc`54tH)y&KH(i%$((W+7B@L8GcbdwG33eR{|cg*{ragc5%%L+~GXRjtZQg+9{fXTSH!k-DS)$_F0
vu_Rbf%{Uc6E1~5YHBuJ8aWwH%RT#6De$L#;f*+=>MCW!Kd{Ha|3G4Ul^yqFj+l$}WAydD!As;|z%wEzM@o}OGgr0Y-_wxY5-og2
tqlaLWTEet^Okd==ok(u64po9cD~GnU1CIR1#Z5^TrGFlZ5CXXnp^`$FpCB#Oe6_u31{hvbP@<r>){6X8=Y|=Jz=EK<-FicuQ*0F
v*UySz_|}v^`e_@3>#(_czkJadl%<$bdk3s82VZg+a6sBprpGSYZOk*Q$yl3w@S7`hHqlKDxZxJvNHFmKb6gK3F+6ph7T=7&4Jet
CPZ8PCekatNlWxHSQ<MOB36BvDTq&A&2ESPA5QHacE&x&siil(#pY=Ia8hU%wm(*P6K4kM%fYlGtTJ;cA+#ueGpo}}>S-Hn^wXYK
^r$^4{-e4xGC_DzLe~?0HkwFjWiOk7BMO93g61jj?e}Low3l%(9;je@&CP~v6Q5gg3YjQK+X3{f?^L+y0M=KTDPf>F5wye=jol$J
@Y6u|r>@4b^RfV_zN~q?OQL##5M?*cL?KtWrCiLNC|ogI`FgZbW7n>2g#qr&YBIl`W*kYwOq&i*(76P3w6q*T#Ah@7^@n0yU~Pvb
4a)0G`uS|_URCZ83{V3nf8e}a{_L1(6$6e`rea<$!1|IPv~*AA;!lAqFp^<<4S;NfGcwsDq|~WVQp|D0Z2Q<Edfq~suowM%qwK(U
0uukTtq;ID^!W>wd3fuh0ueuI$}L24J|>4AAz!UqsVt#0^%c3301)PW6JRw#zIFI}u<?ur0lfRviF;U#hE6qd7vVG@718}(G+I^E
)9--dVSAsjs{OmdF3{w09oR-k@6gp2bnQix0jIQ!=-Mv~QO_#8Mb$PigSBfbKRIqgD<ELA5A(r{yrV81C>QH<GfqgU@M6~@bLCV(
@UR2cb3aE48<ga6Hb<Sk+mAoMuptG}qEhT8_3pHsr)?x8o{`)DcY<xF{7j6MF<yW?h|qT8XsTDi5#t_BuY0}eT*Qg|PCtXWsvL)C
5zI!aAiPI0kMrp*wj3mSdoXJGY{5dCK@VjPkx(I<-i9#;w4!VySU!zac_z`mlrV}`SFEtF$(yA=BBME$*h79p@j@BgDZ2}xpD{*6
)7w`yUp5RkV9`2!eu3zoX1@9)!7B(yqo?)WFVfhJ_fttTJ)yInBF<ljKa97kdCH4&9q72LXbu3j;N0|t_lS`>*};?4qo&!f@wGEE
x4^{Lie|@$OWih5G_p@RpDI;lxK)1ntQ%nCOEdXV9r~v7&97%YDQ%Ktz&^7ECAdr#S2!3eBVT=NqiKy8fb%40NMexe_Ph^a?eP!U
2h{+K<G;R)(xh(Mg6^o;2AKM8qr^^xf?D%A0n6*E2&O%4&*LTij;IytH;9Xs+#3LKcR@0*ck~3<C)Mj2UNaG7IX;4%!6or8^>%`Z
&&SmW|7C+IlFh6cLjo68DWC=bbt-_!M}(lJ0I<wz;?bPgkEd=m3Aj7nhMzl1dAaf5ZGV3|&q-3KITkWm=4-Uo;@;~K@ZRoS6nbFN
S+}ocERoVNk3$Hul<GcieXfCBD5v#+rSE%7OIp~2?BbR@S%l2IvJeecETl}TFbfBFI^YVr2a~e9Do(0N+qEb+oQTd%UML}!X`?X)
XU2|mgX@oe;sXQ`Q*B*pr7xhVEa`rM(2WB=kA)U7Y+{MTcu?CN<YS@@!JF0J0$CE{si_|?FM#eqp20&cBaEhjVuE7H*)d2T^m(9l
0e}6L`li>AY*?OxhZpR;NGlg<*<HB2=`Ya0SfAI5>W+D+^GNnf5d9^Nj51smyp%aMzm(1kkX1kIDjsr;Wdt~V!jy>|;$Xls4^@$5
6l@oJA(P0Kuj&_;x{I?+<XBYN_;cM8|81v&Ev4R64MyL2eU8)5Kee8Kp~L8&U2am}C?j~Pm=VRJ>qI+74TO(Xa}d6n>$owC%p0xw
9)wraLUad9TA1`uvi}n5cY!KR7LX3z<vBduf(~Eyl7GQvdd^?gq17gal#$8yy_iMM9dHYsuKJZ;`2n8Gf^DG#RfzrskZ^d(hnY&L
ZW0Y&=}%7Xn-Fc!^sQ!EQI&UnYKZRkC#`%r-~3J@ZfjQw8I-<-O7Yv-KSR%#S(br))`d9e!RnUby2;&6y=Rw-0Xeod3-DFtlvwPY
J0*QCj>0MS$vk*XjQ_!#4^C?C`Ev7e@5RBa;2}+B2HL#_9fqqFXxd?1j=ZEvdL7cepDD<I6qE>M%E>e)YY{4ym{SmIQ{>ta_<(np
bqUnJco#o~i%ZoSa4UwoR7sl5B|Ow3*-tq0yW_vzFFBy!H!6%g>whyQMDXhtU>4d&xOa3_{k{Ric0w06IC9Vyk}8USKLZX0;WZI1
M*8-5<XKN#H2F;v{C&X#fT-@%JrCtiy{G%qV0hr@gVG3eTg~5=F~69i7Ly~TXjg94`L4;nM$YiXxpmy~vcxO<O*kSa{C30vBZ^>u
$f5O3lH_$~E%Q6{tH0m3hyPT*Ddp+N5c{3*A^zqE4x8o%j?y<Ie-H^{ALYbId(-w$!fQ5*>qv#P$|y`WBVSZ+Z-}${H~&^>-E^Pi
^eL}7HG^qkmuC6XQ$qRYiPz6ziCy!lbsyI&X;l$;X?Bf`DhprX7K16D(IRza7#^9IXKpVjMCZeAT7^n<{`;*yQq}jkCm<K<Wtu#^
VGQ*#aw_C~+~r(fCiq@4jfu*X`w<rZi!kW)zIkzS{S>u4s*#W%hqk^XFpLgE!3H4954}7h|9<+`-kFhYBWn|!Uo77iu4gAxB27lS
BUmoW*a9g%%NeepoVMIf65=ca@}(fq0Wy>E7OEUGym)QPAIc_rwqcNX9%j4@)vQL2d%Fv@F->C6TSU^$b$Q=pfN^${pWt!*O1`Xn
6M|v*<%J3RN@rt|Vw|v?3?~e_=9utKqc7hRUt1LmrLa3zD7Pc-UB(^_^K6wIp#=UUV~1?;s^JOg<_k%yq`K4@nA1LvG#7hQivBjw
-zp4nmX(>-sscy$B%JI1II4faGIBA+(FV$G{pD8_hm2*bVVbcBuCA$Ab<^Ds6&T*C#UD+U2uL2tm!cb<&pnkrVi(Sv^I9=RXTkB~
_o+Nv=CJv`6E;^##*%gRbS!$Z8%!9sCxDZ(DBUf`HGM5u8yDiIs<O^&T6~Hpit5yI5OD%u^$U}5UXFxtfxmG%-D`36qt-n*QbON@
H6UXAWBbMoBAAE0m%X`cY(I(v%PcLY$Kvt61&<e<dQLg$)w@NaTX#zIb%n!Ycv0oG=+eVf9Ooh|1nUtt4oUg3nG=UJq3kI$4d*BW
p!xhw6>wh-Jy_gZ3k=#(iaHC#6Al*NA*t;(=nqDsVn>`Qiu`X=<GVJGZ17UKrQe!+t#DPu8S8Xah9$Umtr2oRf>|O~%9{gsMXpbe
Sx3R1<EA7T{Y+&^cUL{S$p-Vj;43G|)X1Zb7o#M1`4BqLs!9J`^Pvohe6`u?BrF-G4V7NWQFEjRyiph+>Uao#qh;wtX-ft>7?nKH
@Q2RDp-~zrd#E16)Yn$qUDw@ZQ6^4x0&75($K@)UFPrex5iWE8#@Kbr`o4|Ti_1$?GofXQsuYw&xL9_a@>ZOhFs=2>Sdbx@kOg-C
DxmgQGi6~yYCQSAlUMtuXdVa*8(SStIcOQv@EmE<tcKy{k0uORQT^`7*;K|{^{hafP}MX=T}as@2x{T@5~WS{4(#UPeSF|)jo;$6
UXHeUI*7i-!UNc@AV+{CJOVr#`V-{1?X;IZs#i+@u5{WJ)e-IV@jn7!(EiP;BLwwu_fM`r@<78o0@!H0C-ZkWD)Gx+?A5Xzh^Y=Y
g3~@F-U+g{`^Np|n-1cQ;^@#+IyxY~P<SS_?q3>!jXgbbP3~E1VwacG@;1NWT`blpPFzeXD{eGx0nRAo47YKn)6Ou)p!AM$p3@oY
cQ#tu9hUP`Q8C{bFk#8tI0=I!+uwLXQk)tVtNmV957KLc>5ZdD#fz1_Z1Q#*|6sP=_&ZhtQZR4f`b>V{Y7UMsl_Y;@kT9Bf>G8-X
FVlv24oKLJU0c0=ca6nCdG5k;R6$(?tW9@1uEHq1t@lm5sMi6>@86Ac8`6oToH*uLASgsv)0uA(O#xP2-yTtd@mG+7*q&-5+G<=8
?SF^KSz#0~06cbBG~l8!w?h9Yq8;1`mNiHz)b;-zPkdJ{W`jPUZv}2|!B3aOiFx;ZC3UL6yGXz2;C~}|A47yl(~`|id#lUdv@^yt
ikjrc2{9432L^ES>|_9FblW}PaGwrTcRPncqB5n^?y<x)@we$VrMNMl$EXoYtdK=lK2HBS|8v2b*}p@KdjwzzI+Xu!*f}P%F>1YX
Xqy#mRa><`S6))g&?sY#Gc0nOu2rV(28p~v8fR*ZKSi7NQml%%bw>?iz6e=w!<5e|Dn&oyS}D*bpOAUg|D*9!4hNFx+6#n(T4bp%
OUMO-<vh?Ib?z!)td&-s`Q|Et-?vTD5v(uq=PMSbZRUCy;OFD{xvKelOg0I(-@@rdlxV96wZdV;CC5ra`=>gb@Is+~sogU+L9ED>
?YOo_qUa(%sCe7WD{7%<ND9RO@>?jMxUOQq;k?-0>DdQ%b35kY!1;f<5VM~Q2CfSe`q5EaeJl=Jj;{=Rxf6n?=$}wt>}Xb)7NqFY
OIR9p^v7(Eh!OU2L5>-qQfmqGY71KY(21F%M)KsAbwU3FHzo@({#MhVF<9@=!D-n*@i$BdK{b??WB)14A_EZ}lcGWhn4A=3kRlnZ
VAo@FK0sRA3MIvBlLC5&b>)~D7VI`XUGOMjCH_k|8Li-N2nhg0|G8v%#eE`a;CRkZfL3zjzh@yEtKI38G7A_0-JU2Dro$#l9nLxk
0bf*}p>>9xD}~IizSoKj|4Z##nnNl<u{?&VPimE^F)im!6<W?ytVPg(TtnE`Z7iEWDKQNQ6PaBienc7vCATfNz7f0cW3tcqwA23{
un!3}?{Rh2@AdpL{(=y5r&lOpl-eX93GuY)aPZ+Fo2B;0Wh7o?zHzBnI#TteLRpmvSu2ftium%_`KDtCaQ%r{R%2<F2#}bYZW;#M
-(!a%E=A)vXl2Z*vYFE|`7nOGdL{fL4v?~hu%S#`_WcxF-SCPg@QMA_K_3Hio}*FnTHPpf2Na^NNtpMPp2+PFU|Xx+b`rqRgG;WG
SUwVZOu<J(<q8wKqDe@j^yGH}njXf}7=UylPR#@SA4d_`-F6br@2BFUF6-kg_}4&bYMsPhmO)j{jGwWh7`2tFbKOGQ4@J&V`BwK?
+z#@;z*>(N&x<ps#@<wv2?VSrfQRLLS!UW3{uOW-hM=_XYsbEQX~9uwL~zdz*~s*)!W~w8!~lncBKW0k(psl@M#KbF+wxTg%6iQ`
y+(8HQI3WPURV~Iy~h5sqP35(ZxY`q=qLmzuQ5guQf1qR6bUeBHI<!zVzqZ6d=eU5ND&_R<w$CxZL?#gM58cS!mTVUMm6cK9Ox9<
W>u%rrjLq|DS_z}y6y*!DiRRhkbdE>RPXubDM*J}SSNTApJMkZJ_K80ivvc#5-*o>8@Q%zaMl*9ePODQ>w5!#UD#=3wcK28Ze+Xo
uaZp2A#6kat;l7uIN)A8^d(!iw-3A^rU(R5=1iw|`_O<Lf+@W#`>UI@hi3oR5Nxo`oR4XjUHsZH*RDqO-8?zt^}k~l!_I++1pb)$
sqxXuWv1^O427<oPV`0<U(bIxOtUr6vVV0$rZ{vymR#V06spTW92AuLekgQuN_Aw063jkrT}i2%lst_};%O7SLk;48_&o&fzmF@k
Ku-P%KrwP@2=gohqLrTm<4_kJCO@~tgp|W6=aE(BSVDCD#b5J8)!$!xXS&i^24aUHX@s^cO0l+Uvc*c-oJ+R!(7lt5ud`~Z?_L8w
N|C-98KABWr~xbXN+)yK@RSJay8>zmxO0j~>ehh(2<);=k`U_tC|h*=)LQK@>7+sMaO-*Nsr;wz+vRZb0HE;DCea}ic1qK63f`ld
$o3eLl%bJVxWvbxT!@=gthzD6^C>l#bq45O+IYz6H2#|`J?lYV+jII+N%5PtSCGwkIOK!thvjRA0TwcpS*I&8yL5|yV^a(q8Wb$9
ms|B~|IV|a^a6%vy1EM;*M+bD>+?Z17h%Ek2)K2AtCLR>`t6--w~rpVsB+WfHHa#G7iT)**(f)XS)#MI-u3Okifc+-xI{2!HOaWB
ntrco_i8f^mf1CQl4tI5ZRVt{A>o;;^vTNO^J2B0#QK`*?5-=kFG+?iB1!e@Lc>rIcw2#AfT4Vsz@N87ROVbU$I{)A7_V^)zrnZ=
He(HMH%ba+6KLtzvWAd)I2z}23F(kyQR7Vz{@Bo_G$<Ex0Qz7ji+S@1+CekOnf^upvmM{py(^QXh$K5*)ZS0fOFd!94~8M8VBYbg
W@TF#{hK%)<Kz@S(_tziQuf8u55|IK)){h;jze+#x3fdKG>8+cG)BHzvg(k*CS&{{)=w3NXCSuZt~N=<X52cIit|&&IhUa*xnC>J
Tgx#56zNtsNq_TB+<9&6lOUZ%K1T<x0<i?|$6gv>>9*iZSPdk}A>?%kxm!~6x)Q`WGCtLnrP>t|7DF#v4%Y`}7MrXiK{<sWbx}kE
Z|fs2lF)mXQ6fPAG``f?$*+z6rjc}&XlSE5l9UI5fT;1yyKRZu_Tgp?&bR4?9d+7LBL}0CV`3K%czZ%RZG|B6a+0qR1N?wOhSDaj
K*+fR)ft1njGCHuhW}5rcmHeVMC#tu_u`1EsqNqMwUaSN+}hBQG$A$O+yn*|06*Ww=nR9l%#N^+(P+jQ^E6FKk}TExWuqqkq=Pm3
%8~pfb*E?hUI^wNW?Po=#xgCRtPab97&Q^uYP!bUQ6tRrUW9|1o|52%EcMts{P#f`eX<cUol*lXhWP0fHt!M)Ekxe2mEU`t?}10=
%gAro_`2ZM(NKKsW0&T}630!o&Tv%fNUpTjMM#Bu8T!>7*gPQqR)c^w9+TTHT~KC=-m3qS3*j4RL<il55MAeReJpIA15>G<`^avr
-@`1J+}ExZ$V5V%o3G!{09FrS8G9VmqL{GX9lDkR6Nkr{<6;tM#hwzq<q01D(I|(8Vuw?PpaT_CW=F{*^Q-ZQ6wQOgVy31~T6S6}
GoaJI6|d;_1~m(%6{(?Bil(&57_1xEd6oG(R>P4@>r~xc7a4>_-Yu(<N2Lzzb$n8}0Ec=%%{7YD1SeS4&oW{2O!BjH*4Yjvk7#)F
A((f6<v!;i-#-^6<~Gy}r=NHfhGeML8hg>=f|DL^M>H~Px)u2G-)yjOh9=G6CA#&zj^-snMX<=0u(WX>jEW;3KX-Y^9rpD-;5jRn
;wid>8%9f9h(gpnvpYF*Sm3q9hkckV0r1OW>T=yn@?j+x?~dp!n+%iaGL_mzf@=ZQ_i$AW+lu%9u5i1NMh1{WAuj8Tu@k!*ZIA&h
3!g;B4~N@DV5h%x1T&_udR+(t-T#Y}z3X_EC7`Rsak|ltddkVFS?-T0!_BnQ72JyW8jSQGoscGLo!*=^stZg1tBn|UmN&9q_wqfA
F9BFlP5(I&hthlH!d93;xhme26g&RsgnNowz+^PPAK*GX9rZFPLq#Fw|6*fZv@qdvd9E-esvxBYF10U%Qk@Y%n(dls(erd!I}i9y
COZ%c*1wSWuTx}KJ+O+=Y_u{~)Jk}SfbMfuj|jgJFLsE0F?!Lz7Exq}d@PB_+c?LhlB&=Rs@R7Sl#V-;OsCa2iT{JS?}P1}j6*90
%wYT6Mlr<o<jK=UH!h8!2Ub}b+*J>|A&4PyPBnrw>nThkALG1zm_khDqKCC>$N$kax2wR^26@tN_g;GE3rHhc1haAwZq>XY0^~Px
;G=--1h<5Yg`71jZZHhWGNGJ38q_6hce2|Ey(2XY2bIAE)<qXe^gz1}>CIe}Uxo3btS`Y~V*crpqfRGFh98vf^CH>J#jnM0;VJaW
E1>&dA6uZt-6U1FbY5jJN3C9GBA5cNsEt{ZOQy~KM$t&kuvs#;i1rQZ_37DAi96C-9h%Sh0AGt@6vu%FXKs%G*FO4pohQ8uWHpc~
&Ws*w{-qH!ccNe66+i*E1lTqw=DGyE?JcM|#)-w;<Y&73C?`kdE>7*CV9_)l<OS>sEzq!;Hl$HeKdV7;jI$WO!5F`UoWS4x$;M_!
SL_|XtoH^CK(l(!|Lx+}j({USHualHSb{Ma)b|t`<^2BK1wHTXvD8So0|Dv%A9`nKh;}qoGLt1gIi*$zxz~O`z(b5Xwi}+<7UPd@
J+mH_Wsn=-l2-R=Iibs;E?{HqJFPL(;pXt<q}>b|toceZ%7hrbAM{(lW&e1(GJpqb$7DJCAn_Nihn-|CvzIcu!c$kyo34>P0P^pb
DAI`CroCF`zuxCc2*%S$g_u(UOF?E0t0y7x$3&u3Y%Pdz<YmFYj{;i%3lSBL=GAYdXNmc1q98&S`dli4PE$9H#oFcGNysSJvW<Z5
w*(Z8cs9p%3_<s09!^`EnolcZ0wlDWmd1OL7|nRm&FIf!V)5@*qG~2Z+v5)~IgC`uc0BLr-9GpbKluwEeaFt_3iVp4*j*imY6JTl
^VTH^IiVb9T+}r(u>sxqPs!QclOlxiI~)uo0Gh(H4)VN5JcnZH8S}7IrDYUI8m|<5)qHP;-hvtT<Bw;cRpRasfrE*Og6tuMb(Vm8
h#h5R3rf`n_L;q#9xDqDYySx*I8n>7BQ&8#H7}z>bEYr#R;#j;dGH0kWaQX($0drrzAi*W%^d-kCMQSFBn20G9y#*y#$ot1)rU`B
*+8s$EYbPL<IT3z1#Gz^K>OChH{n(r<EgUH8UYV)FU5cChl<g8N$WV*Xeyyso+3cp1Z415Ce^lF8R;TlJdZTD;lO!4uO4Y)U3x;~
+{?WvvXgiv>E1zDbgsw!5IY(ho=H5N5mntJ@R&&!n3ZR(j}sNFiby3S(;j}8Bqc1+m1uAHa}0$Eyk2~{dQki+J<G}VTV^c-6n&V)
SEYYU%ex;k@oVjA9-vW}=2|oZ)E*LtA&I@2_E<u26a^^P-IG8Ws#ER8w)<IFPfK<=1{IpYXBVmN!2t3iPxxn{5K58syKLo|)0?O$
heR4}_G22+l}o9Cx2_X~*UF;=TW3;aCm-O2^GYUW3sz5nFI-Al<p=N8_h0{K0Z7+wfJ}<U$NtM?$D1t-HdXw9-5A;pTqVZ)N}>DD
fy+h!j8isAGGjZxoS$p}$%A+ac5;HBM%{3j$N?J%prI0%y^pDL*ZGMZu_X5s(kxd7bVSHw^aK)4k`3M@qahqqmUo9oCq;0CM+<Ob
zKpuD!pC7yhdRm5uTN4=qmMCGqMo(Z7y9DsvQB)ZalzETnQ8bTV#6lsn1;;$tx)QzBne))A4-9^id^1smBT>U%5%?#wO^KH?gvG%
GUYrTtqm{`4VB^O&$qrC90ksG=rfvF8EFzQ9dXLlUKrh7X)H-#-uNUxC)d}GM2xOa%s6uxgR2FHoLKS*^jshYV&<QM98=^y&VDiT
S`ZqWrO(Bshm!%J{~NrWX?{^jXVpcUhGEv?%XmCTVJIcLemeA0teP2mLVGnn(@KP9&_8t|up{tBGtJo6{LkQhhJSC6u#-gcYFVLD
AKVs{isPn3;R3yeNmUl{8MB5F-w$ddc2r=4A3g4^j3L38fBtUK089*qwV1T()r|nc6*!qqqZS<GZeNWCQC-drdiF?hgwhW$gAnyQ
gog^KnX8EZ1C|OFXSi9Op*w&=?;fRVg~Yj(&8-n%-)OF4`lGi#N>I^%rG4IfSKj~S{&DN!Q~duI(+=PXpk<Pp>zw=8ade4T;O`-D
^cMUiq#jr13Pie4?buj$VLd1uLyw0ikiyXojt7j1(~;t~x5-NZ_xppom9S&M?tl$U?Kzx7xaNR0c(4Hk^fFG7TG$D}!Trs&tK6Bz
#zfHc(V0<5&vL}HgFChZndr^%s9py4V)6mZE#0sb*=YLNAU+o&tmP9vYbpK1V=tBELCiBgEp+Ml>{tM~5A#u%&W51AvB>_F1=l+t
ao89M;+d3M=YaE7m!myIWPt0;*Y?v|(Qc^YT4$Rz&;`eC5z3UKWjM&+1(%^KNbbNePQq|L(>#jJ-S1GPszNSbejZz9I_{{WU5BuL
2c+(i+*IW128_H!$C$OeHWX^dEqnxJ!0{~{UpSDcB(yiVU{X-g&)>C6kxK)Of;qsp1b$vfY-$QZF;xjQOAl9bXU&`$(?wAW3LvkY
3*glFZluQJ8AD=>d~h8YCl?7gpNd5j=sVDhyb}?uoa!om$suTJ=0of7d{t*?G+qv#Nj%LS+mrY!IqlOBC&#@bp!0z#X=Cx>Zvg6-
aI>|g6@Am(d*>Kp%}b*B;t0Q6B`wmlZdsOHXW+m4YnL2~pIBWb>A%I=Au57}XqP49C)|ZmX(?i-EP+F`e<{JG60lxa-WW}Le;jeg
nm5k^VU+j7v({G*Re|}|x7&Vlddn|t_R1iUX>DtF>X8Gh;O1+Xc<G;w2Ee?K4DT=<Cj;EZ3sTlJunt!vM9>&RV}YcOuM#*%!L;h{
rNVHsIXW|?#%g}=zZT>4#d&Vwo@OR-+W%C86frvk#)9CDlitO8v8m9o`_h<zhoiZO+*i2|_q{Uys-&pNR2>v)bR<Ze?@KfME&9m^
5<5I&crqYg2aS^^D<7GxZ$qca%JGrG^>=7KG%LcLlWOv$T|SqsST>g9Tb#<_e`ae2kYaJ?^4>XzB1l3dOFxe|r>JgzbIYpx06E;#
hY<4dWfkGiD+P4E%+2>@xxH3pP3fGIO!ma3@st5<$slTNE)F~@Ip0Y<QuY0{-o-C%aynitk9Jt)Cet^O=g{SaLCKPaSK+OcY8D*q
MWe_~+8k0%+Py*lV$EJ3`_KgeC>k6bI3JDv^(wn_#fsaV{(%h&5Aws8Py(4dX2t@N;M43E9<?5W#JKAYXSYR<YK)}6-SRV(@Z)9E
J>cp^Lr(`KdqrW<Sfib+9}7(1I8e5L>~xoxfUZVYRY7fIUCrVdVwF<*SD`W;C46j)zHDSpAs@063_puW`i_lo%Gm2G;$%b87Zux(
qbU;`)EdEg2;6PyA0fMXIA?OAwgq`wXZ>$^o2VpX2MT4kXMvW-)bnSUEAAW5SNdv_GR8AO@{{S47^d{^8Jv$nr7POFnOs$stw*Jd
7|Hh^hYL{HLp+hTs8)s8E>=Z>V7G5Xfj=RcAcYkZ?1{Av@I;g{m3{%)J5EsP*YVd&)sBlx@$3ie&Q#b=1?xIllR`I?3%g}22T3Yz
gQzI*%TZQt)p;}1`(@&OrN!dt0CK~5Wy5%nj}Cux*-eS72DAHH23See5-^Yk9v$HyFva&Z117Aa?^bbNoWEr>+n_>kS0v_s=}t9v
M|dimNhq0|`}8#1&HQ@OAD?fsAl=ityLNxPZZj3)$UkH5Q-c}Ae(Qy*p(ZM_-4Op9x2Y6OqDhY(5^($rm=TS45C)EPh$uZvdnp&0
9dv$=eE_npIOAX6FW><)6)iTC8rrGdTegFj9Uw;eILIV7(=8(^k25|Xg}SQPO^Z})kpO_-nM;aQO_%Ddo)Hxlxj8D^!PJ+K#)3*f
DC<rfsK!9ZWW~(=Bf2JL&82fS=7=B{Gzi<#M>ilq3YEp^d+bWUu>6t@yB2g(3tkw?>_D6c7ll(STk<&f0NCTAIY}dZ-`5_qpKkPW
X$HU?8i7JV@<6S>uUtin(-#SEN|h9_4BxC4t@6rP`!v4NVL#9u@A9quG<d9|EDJab#C)e8?U3s{eDAkQR*opS^V9>ndjYry#J6=m
S~aN}xOAE;3V_ijH2eYLh0ZKOtI$Yv5;v^0yEFOi9M~$0i!+X)@qV{DHgt2k><3rxWb-&)6tSDWcU{;LW2)Yv(zE}D`r(TBGv;Zv
1opSu#Rs)QI1MsvfsvUOXeor%sm&KsE86?wt|0*0p3B#?Qe0IP`Miaf{jKsDfsQIBWB?Hwt-Z1Gv3n82DqLCFUq}&j&;;KxjEI=L
r}22Y?di3=p9L_YvwFqb(Gu~;_0ic=_<zJCir#tv3f#L!d*3vZHuL?mr`tLUTXE!qJLCw56aFL`x|Gyhr?2XRq7jWz+FNbk{kapD
kPpas+CAffMBJJSRd@1m9gd@v)bYe^um~P-ZP8pVTL9u3zDDiWb})2mlidG3oH$AjN*>w3+*pl6N8T9QPk<S%&mYceAx{+SfY0<d
6Ucig8+4R(8AJY+UaKk`4c}1MeBs|dXFSyuGh#TP049brc}d&2ffWU#%d%Pk%vO=#<bwUgCxTIQpIuqc#yr6nZ^=&J6lRf9wofWK
^3@XRjpToNtQkDX{Mo+czW3|XbjVHbA=&**7pfX%k|}tN5TVRNu(AQ_x}&@F;BqM3nv2AlIL}lG9*+rU@t3lKD@cY}9jMM^c9qc=
7s7i@!C1nbvMQRdnJww-;c+#vEh%ZspoST7o0@g^Qh4@MKPeXxco)PE?5J^+VDm6hXSXBRViv@9nVt&PLeY%pi|LLrL9f69V^x~j
Yn>z`dP;8YjPsXfvLU6sWb9|<7aAN7U8tOGHZs1Bibm^5_K?Y756U7W_LpPmXi0`H$AbY_r}CILA}?Obwi=p=_P^7!F=ao>t`B|n
(Z25z`&e3(=SXikoIeDy1;+or5Nip4{EEzzZP$i)u2AHn+&X0?eZ->${&dBgncx}*aCaL2b7ZzFeZHVu5upB1Lwn*k>SAhTTr~5h
@Wwz3QhmC+`9>R2`VuyofGe4MEr9_Q+70_**h~SR*;u6OqBo$3svt9cV}?({!yGJ@Y@gtgiRrHi0Yh~}+$A#WpuX*Gf@Hs%L14Xy
$8(sPcSIF1?X5?jdE4{p_XcKso^_t}r}u4kg6-&MhA}DHG#>^WcF<Z<WqDIsbOPw~S`-eu-X9(<ToKjYS6U>U_5Zx1#`k?44RLb8
TP4`@g+pgV#qojYJE2N(m{+7eNQwS0(QmzEYcL-GuLC)|jo4k&4@Xbz5{b=phe!6#Mw;W&QbCf>Q5C!=%RGM1dQGzv{Jeu1%xj+Y
r0AAQrtW^HwYnPe0ZK-p<LhAnBbc@$%f}r2PD(k&yySj;$qv=|YZlqG#fX(j`$o_$DcE}s`U=&h7lpcs;0v@5ly<1%KdcdDm4MFW
acxQHrB=*F6DJpFBf<MCQHk*JfoOnyIS}3m(g)+J!bSFm?sD*+V5E<wIj<xkjB=E+s;5qZd?)!6X&7#IT9L?FzSQKV87C}_GrY+8
X%Rfe#%64jC&IO!PFHqx7KTc<=Qp!a6d07a9z2~UJu}|=oE&L}|AeW?0g%<pbUwWDq8aIh3MpdhnHAETJa6f?ck;?JOo|qP1DMJ?
!wA{I?p+N{N?#kO#}W4JN+eFhxd5-$j>MjcFtjxbtH1_aAS9eof=Fi>6bv+x9%ec4@V?|ZmpAEpis4vCr^x?KxNuUj?rw3fjC4sL
?3f%J(F2<#s%EiGzJfJWxjALwSx{nBTv%iK=W{!Oerha}O1QT;2jMnH9s%NJSxYG31l0Wj<aAD;{r6o%34l{#Oy5b3Zlt4vE){S3
G={GV&7s9pk|Id6hF=%AcDMSid+etqVtErpdhkspU-+zXkq(j$ncf5>76U$Oq$1=%>LG`^@iOnCzELR=5f~bTx#(Dio%P;@JX2!C
IzyTRuKexl=Y~0qnPWV5H>}6M=zF_zs-o&k@iJ%v2_j{Y85KOFUUzP9eFVqMnB(aZS!6sDPR|rjGkY+TrW|2VkjgNxbt)`j$BUe*
<ssq$-3{$dCiu}HupKdY9*oJ+lpI*9Mfrz*tFKIjJ6w#-rqkz$-vdl;z}~YH!uE8eAJ&j9MrOP8OV}@x{+0CMa`Qv1)&{-e*1k*g
MEoe4>QACQLx=?z62C#C;1&?EzOs6feLR@My+rtu=@6pX(XPC=XVPj2H;$a#EfkRTVJ58);n|uE3XxB(KhpUzFxHse5tL+4@irm2
tLjQ2&q7_RwpC`oc?z7tW1RCePlRKuAj<+VSuy@ps-4_gs2pW`-<^e10X$DOT&_WqL&!<WnkB15GDvugPb<OW*)sVmp7|xl^M&sY
S=wP6d>Rg!fIYIwm>2?cTap1>7~AHHtsfUWTxg+VCt)!|g#{m--49qiZP0LnY&?<qvDO+(*k@thjsqG7ORV8pa|7w-Gr--xF>~M}
jT1CijHonmTu-N{FjaQlI|)y2#CLspa}rF}t6W)BBGU19M_*&Ey7ZHU)pn|@LgFA+DF@ir>}Dq67WSQipL#=C_^c)qXP_O-Hz5n5
aQG<R#Fb0^9-(=-tEwSNkfEK{w<}%bBqrliaLW^Jsz(A*j)Rc~o+sJM{j6LKY@%t#O_PV&fuw;tGQoQ1!`^waILybIc~!t$NIN}l
?^-x?Sn_&o%Q)c}zTG_yC*vSgIg@WPR-jKgV&lmk@kyl#v;%ZJ=jV+`q<gczL!!xy@RHHkO7Ey*G37W!U?M;BvXh>hZ?g2Ppo`W1
H1o}Xl6l_ZQPXb85IXs1x@a`7_QA|8j}ut1YKkJ78<NZN>B%CUQAQD%<lN;QTfzjD0Q*=ykz^OeU%UkZC-=@vQHT@7wFNNhEi#ET
(g%%a()IdnhedrvC`jjc6Qa%3UYNNm_1rZ~5X68AAGK^Ccu-vX3sV7C@ZAg~>qklZD-i|MB9^lh>OI_hoKF4@RL8zG)haD1l62JE
JI?=HzKHeC?aa{_+gm#NxsZzOoJVDcP{zr1^e_(MT5pqZBQ>|iB`V^oF~fO-Y51-TbhAyF@^xKPuTcs~+|t5iP{iomU&$vrdeT_C
(jcV1`ysK>=?cE@64>7%bSLon|70c`mFT{?u3rBK=`2*4lePHxkCTj!i!dgs+lf9jCSMU=Cxw1Pl_XjG4c&lZZi)x{alaniadc42
=l3a&%fxbQ6|9S3@O7PIhkD=Q_giNUJuPZ?r{!#*5Q<G4dR+t+h%xv-dAC{s_^`VHHb-~DqJa14&Rsn+TUndo3)X$z$5qr7E5^;i
MqaA$t%+lLAYCQh5`(w<4diT?Rhq0~oRgH+_W?`q0S~Nlf*nr)b^19e1u-rYw682j+)|1<26l{hcMZ(h591|1>5EwZ#RFMK`i;L(
q9TJS5QX*vfJZd;kC`~f<-JI^55IAi&x`rwgHsIzR^m;qMQ-~5&jE_SW3x&V<1UgEx_{v_z21BfMgzinQDwekDSWD>W^k#t+5t$*
w?~)un(eAqleas!kvo`{BKDcwbmHw$YAIl4`?&JY-fu&;b>6%S$W+-af)YLby1_}^xz8QBRg%N-ta`jRKIDB#&;&u^eVVKYf{ny)
5gAVwPA!bM{5Uv1hgIeD_jNAxnU?DDvL!q<7bv)_ydg)IVh4m;NKGSWz52~s?a3wv?74A1aj*?=u(M=fe)!NfDK$dO*ANvHre4VI
6bK14<0@R?gp<%!oyiwngJ!iP%0aA@P%@fc356_E)t*ckLBsGFQV?Fo!uoXsetXmGCrPyIK(Ek!QuDmeEf<mLriA++B_MFmkDEVW
L!}}7SX|2$rWxZpQ?N;aj2jt%dmWY(<ZD5}#w~QEEW}G2*1Z};XII)%Elbowni;m$xDXhGyp@ctk{+EF#oyq>mquD#vRkxLuw35y
-rYGwr`6%1CwX{zB4h$OOmC8=67-mmaiIkHL88^7XuQwRxYVkXQDA1oB`WWf!{$ZQvm;FNRQSsJaw^QFqd-EsWojF*foX)5pBIIy
$a84=60$rvIwAK#Yr+_IvNI{8sPWcPg1(#<K*du~_}RVz4)BEu9VpWqHZ=3~&>F-Pste2%`un3NXePD1Lm)@VTIdQHM~O1~QG*F>
v?jLW?NPnpGHRrgpnAd7XAkRv2nv8^e;2yQ<GF3eRQYJyw~bO{HHqNdC_P$**U~vKYE}nr3OK!t{FN&;1{NiOGqKYH|M5zJE*wTx
)o0B9BNpyIPF~s4)^rgJ<d2BO1>embP{<>5?7RS{u-@xUO^W1<3U#s|IY9{9g%z?WAHkZO$gyxJY6>T(HAeX5e#N<v$g`+U6@=T)
Lol87fx~N(y8;H5L_=l8CuhEOHFYa^GXc{S`f&z?LPwQtq^Lv*Q@Ksv$9p6TlgaVRRO0uZ%NLK+W5DKLZr+%`cFpIc{NCoE**Elr
0=Fhw>ID~}7b+j#0VZu3n>m9t2QLg_IQVcpRsrax`g)mDHPKJ$2h1J(E$I5tgw*NDKl>6G<8l<MF}>4D?qtIBF#je`8T*$Cu9n!?
h;AXg$MVNDyor^QGx={j5G7#kbO#1MM(&HTh(7#BNlJen)P4P`bHtoj1H6~S7l>)c3}{km7+eTjI$iPfSvvo^4G#sX_3*c%gY4@A
F6HvakZb4w-->C~rgN=QAx1$BIjxkqX!l72JaCU4VC5SJpEwU*yQpfM>%G7b`94{?l4YVKOyOs!c7fryMc8K41%NH_dz0{=bgR`(
1X&)FBAO(q>og%9K%^Z(sO0$IZ%?YbCkziOY{J){N!4=*4$k5rNMP;C)Qz(}$wg>MimZ`J+p~tZEk>J@PYvi~Rgn)AT(78Nv5x)4
4JwaRewjaSlKs8Mk}Y7NKiGcf4P`38Sn|Vb-yzx!=cNdIE^_j_aKkNnTBIExRl4?-_>y-flCtG>I!;JS<iO&Qq2hi%UK*h%W*)Gc
OV&m;kTsiP6iBx<fnA+Q18`E+j5&1Xwb=?aicp$;lRLx8KgkgsZ@76~K=0ykflfA3<$|`2B_*z!`g8RYO!`qUsj~Pgby&F}*A;+9
1T2E!n-BO#XZXm2aYZYgRGisZ-qw%;Jz6yB5kYnn3Q1vZ?jMA}N)R!h?8|EJ4!cxU0P8-&pLNBbkdZ(wxBOJ^5DpNToeP{kD65iP
{-5m1@H6LUI8!aMk%-X>!|$&X0r@QK3s-K)=yskKD=m0dP!x&%M=Icy`Ul^KImlJiVX59LL@U+1W+QRB4|56hnTbUYdGX610C-lv
+`Ll#H^Q%fJA1XWSqfLf3yWfCOM2s%y#<mmc0&px=>V-@x0iXlZP5v}e-e3Fw8$EyfBxNS&l$AeJ6;cU8cm}eP!(N{9hnHo-u$9}
I8DXPFMG@<bo*wcBt%~MMKZ6>_8z6V-1*I+H%$TeB~HEhP~JPwtwK#YbP?ZHU*Zvmx?3F{KxF!0J>27VKxr&|=|<__B37h!vlQVA
<Xk^?Skf`OX?L0qPX)c>*{v%hY`X>o>kPxOjrm6c0>qGlY|6ygTA8t^goThy{zI-aq_kVYVsv8~L{)X4M?Z!N%$$FgKCEm0&##9F
g@DY`2!<wI@^E&veoD-Jmxzn`uIB<LOH)<F)E@K7s}+Et2ihpIJuj{-5iAYd-J^*rUgUY6=5&CC^nOgq4E*>G?aoH2=RqRo9?ciI
@d6G~dVU{4Q3r>I#nw<upCu2FVP~j8otk+1Yzr|g)7!hMlj?WtMi_HmHz6l?@vU?FR$;CW!Kverk25$a)hd=5PkTS6<iy2OurmZJ
1;?;u+L{dc%Q>dKRFVC9YMQ7*$iYWJFHc7uda^`1=mC;em?pesnT4^x`8NFyl`8iO7_&<`;?+%TJCg+eRr10-Texgh5m_oircn97
bYvTBcB(yi-`c|ZyF1z(c_ds#Pzyc>ea9?MLI)bTh7`1ziszRZPjBX`&1S9cdThQNOXxdS^~}xfrb@b%)?X@r4i)4SN8uTB*FY)i
$|VkLy!E|ibB&_LD}k3*j@O4vE=S}VyOjQ5{Vq`pDP4l4jww2z;MD7LRG!vLp~tCjm_VGY=h2qt%tgt!dXosX)40wx79}4MdJ_!{
?U;TZ??733;JaON`F?yM^CKKpAk>oL?-c1;(r)gRwgNyfO;X(gTrVw3CDKc9<@OeH;T5vOrfiO{rBs^&gB>twUl$lN7{Z&C_nt;+
xJ#%66He3@xh-{=c=o~bpf-Pmr*%`z%-4geEISWa^x^1Y{x^Y$re5(WJ}i7Apbh>$BgB}GHUO?%9rG=x?<($n731i#@FNOk5R;#m
c^Aq8pu$~LK{S%rhR!k(2R<oKC+dZu-ARs4y~otc=@Oc94mTmwfM=<T@<NGT1<61m{RYiwn2q#)fDm7u!I;7@7238DGJlhhUWrgV
2gXp|aA+w}%yTsyNh&{*^BffG>WeF1N5m_hwo!JGWb|LA#wK~G*glH|1H9zYowqQ2UpjDwx9`hG<rdRTTXW`@j7yHP<Zx9^@pXXZ
`Fh(ey9>y`m><L8I-8^f;W6QQx>U+Gpo`tQ-p?V)#)Nse>g_vl{j<w<3TqExg>q&^8a`j{t?NAUSXMy)5r6D_3!uv*-u1ta0+Zwb
7sra;4>Gp+;^BaPz-w_lHGi#8Xr21KdfWbjRl1-=w>2Wp8N;eS>=KjF<-^}slj{x{Z+sMio|9Vyv)rc;`D4|I(nS+_<9)Ag4xadd
6N;tISI(WJ(4*^P7JZ3v=}GHKv9|B(fn#CeE*;gFu^#L8%ughoyDscdSKKQCIW7dCvts^vgeaOt^Pq6o?{attb6+|O_ql;R(%9|?
)cuQB6~yat3j94vn#ZR4G6{WsIUhn(2RBGVlck-?#j<_NUonM!Jk!@Y>%BK18(R3+iFnODKf|yp<Gub4O?f>6=;p&2Kkf{6RI`c^
m0|N?^fNWZGvCL2*&+hOUR<ou&oV&^anl_BnIa$RQ(`oxqk$8NeS-7br>>upQ->W0bQZZ>d;<N(pDVSV_GHki2G)WD&4IQH>R>LT
ZZqSXGo*5^f*Z`~^rG`i*uiRiTZEILr)1U4XIWI1TiC3+BEkX#ZmSM))sQcRqrpqtGZo{bv3gPhciKw1(<30ar*`aWVo;2;l-X+z
5pVFqvPhJCj`nFv4*4;Z^F&N@pcVypn?qW>HCZyk^PFvf_kXA7ku!%hOyKf$;_QDKyFjb{hsWp;8eeH^sU#>mE!U!ZCu)Y<MK$#T
_sykRRqD~(ucrH9%I^2<RJ%!9FC!x#@0nAf7We;xDHlIwOc{a@M53WQY@8$wTn{H!^@g@eoA^SU9~kguW&MH&{s|fbz9spey*^jk
ZOM*~g0I3g>#zoO_3CC3lT^~tz@^L%f#KeaDMFk=OwRm<JR~E&Cbu6TJ8JK22-$RDQV~UT)$fb$1tyK}S%`K(pKqh61-;A^b^pn+
zx79RtDl}Ujj^nChA~HrN=VQUTl<LE;`r--`F0hw#43*o#krcflUXq0idPt&*f94x^0Tf1TkHW&y%mnbjfd@koQgI`?`GjS!cRJo
*#2bfJtd7YvW1BGSn~n}79>jDqHB$?I5WqLhYc@>t2Od4&v0B;B)%3saV!x?_VF%?h7aeM^AQAG?MqjX!vaNm+daiYzzV7NQiGFY
`9@-hN%-)x`bxT0WAy~6LrL#E3V621NVad?u5FXl;F=4|AddfvAWU6zQ}efXW3ulq!143wuidB#rJl}`8rTtYYL||>!+1`?<ermo
U?LP`08$ZUZ{qdb*xoqTmi>*eoWTk;^Pyj873Y(;fUrOG3$RqZ=vdSbSAc-{hy0Y!(iLQtLiURVe}O63s&j-xVqaV|`7~$S)fk5#
=FadE)>hhg-lgvhEFLkGc8sRZT!jIQ)Z^`4erLUgfp+TCl*=nb^z~^&3_`5jd+j0|m+T4wtYV@)x?d%D-r9^Vp#h}IEH4~b@T!L&
<J^7%(G^}lUvxghOPEG}1<lmch^#0_Lp6JYG^vAx5p~U38cYwux&}hj*7QK>!_eNRZz93U*yBP|&J-^1#uC&ESV#=m`gLxo+1H20
R%uE%M^~w@Jus7gf)+NF2`ra3i_vHA>W&`FOs1bU-K`n)l!GI(Uhh)86RAwaCw$ChK<G68*t`}(1^f6GO*V3hH1*ZhqifI{C{nes
s2!uY*MyRsPVPPZ(ub>1t-xnMr1L=`-f~FV)b=TVnV#;qCSZXD3yV3%tn(yCGP4=X>1H(yYEnS&%dH?`+2z7?C<zmCx=pE5*N0(w
&eSbVm53>$mIt!r>skNp+dH5N%~L$VgRZ&XSf_nuY=m**+Y-A#fjuwE)c~KdngQ^o1VlJ1x0{_RJu8q0Z;6Osp!$6tKjrDic~R3W
E;cmeq<{|t8Z?%{C8$|EqRZPYK;cp(wZIx>v(Up+*l=PBYZX@)PzqI5Euorjt0fW$2S<Y9ASnocuj89vFOh@vDIfbP#h~+KdQYRm
EtC_swbD4-^%2XJfAPW6SP1D5(qUPejq7)apy{D$tcFH6Cy((oF!gKbA;W%wtG$=5o!PYyyWOj#k*zgmSUzPCUTN??&TakS*3ukp
a#7JVJ8~}N;9uC^61x{(c&QnUAcF^4P}2_$k1|*3OX+Rh!yEEVEGzvQ>3OBxdJp#(r416Xt`kShpj1Fh$l-*m!Wi07#?xvCAl?lg
J*2N^ayajWg44%b&TThaNljq}iRajFTJ<3YDY6L4&o-GXso99Sq5VyJq~*!#292(Kg1Nr~3$^s3hEsf{NWaP#p|Xf$xq&r{fd^)x
F^qh6@=t<Ncd<`++8rY1J_FJQiR6^uhEORsJvU)VI;NP1_!9vUzy5((dAI3Lo;v#a!3ie!LcR-+kwW5A<;uZ&ReggWFX`S#J>9)g
b|esl;5LQ~tvLkcxr=zQo0^}l1Mr%m9&hx^I=gq&`0g0YFr`#<E+6QeLaQ9>c=sSxq<<ShoP)_EKn>M2212OC+_0iEfnDxJalez@
CW+nOWNrtUBYt-x64B~X(+<_>GQf*;2>!vbFqi1b>JgXF-H1V~MZibL_}FPh?zOA)MOL?G;_6$pwe6XFZL~8S+LqRLD0`cOA4M{{
9&KbuD`wpvv|{uKm8nG9S$}pxH;|GppofX54j!NWJuL5VH@D<16xJ0K$StYvVjzxRj}ET6E!7V9<i|E3GMt%JXb}>3@K6^wBE7{<
_7G^W#U<1q(w7BELJ8CZ1MxX2Vi{y;mgv?4|84?X*o&K{DAy>us*lw<#^hBGO(4WVamSPl9fvE1@hS^gY(uY``Cr6pj||gYS2%W@
i$y2tD#bAcv3Gc0%PHXnF?C^eKZsK}q%1xNy*xeeX$jxu{kLCt5&vI7%vDb|`cS>@NvoT!?+bQ0#XVRYK$A~V!Z>DWBS|p-fWvdi
HCXx9<g(5WBC}V@X2^>fkw-=9`z9bsS&U@)n1}QJYA<Q@kq1P4OfG$^sF88a%d~Q)q7Dj~hZr_;jkO>=&c=uc@QiCQ4)g*Gt%dPl
dcEx*x`~Whw=?otmv1B(@PcVs8d1+ZDBr!>f2CSsNk=>lsFWtRt)~bYNS@H#0cnk0W29C{|MC6p)SCp+v)s(BlcSp{0m!TYQi^|*
6FQ>0XZq9pI7cH1&D7;-<zGMu%DVWOWr*6NO%2S|)Jn124~1UAnW>maUItuU3$#8fMCVo4y@i!fwO~QrArda9f_W%tD07YzP*{sM
O+~SzZ#6;hwi#!=%W>We_OGZRNmkqF%pj>a2Rj~}H-etw2!v5+Jwfm0e|-Xnbw6}7T0vUf7oL#iOL@C}se)BaBl7<&$%$`?Q9ySz
$c;jeZL|3*4{uu*sWpnW_*sx0YZs$zhGV@roENlg3uz#;8k>#i$u8<GF}st+z1YAd9{ogz(?8YU-0WbR`MmAkIzU6VAVt1L`FEQ7
>Yo2>@P_fKPUtfH8#;0O?X5MxLWObji4Q$q)QR0}`C_%rYP_0|kPxUR=qPgC+8xNqtO>?FHZK3A|4Hw;KAS^vcJx^zk@RB|hQmbX
Q)rsBvWsC*G<N2fM`CR3R<_MN#(H4n!bQB#F@#H}RxS5&?-uR!xWb|Oc59Bpq2yaREExA&!;xH(pM4g#crK!9el<YtMmCdZ5&27n
&8PK9!7E7GFFSrM=X`MZMAc#w;sm!oNkY8b57dj%0VK&mjnJ{-m)Oam84E17dno>DmZVo%FEUa;OF)?{V1q&%9W)o3S7r~nav?D6
2v~Av;;u{k^W6T5A7x{qc1XYq|84E{X?_2xVqHG2w5&Tjj+SX?J|}NnwnF$zp!G{Y;TbQU&iBkj@^wJTJ5Lh^5IL7s59Brn=#KkW
dEB=MN|XwaWsOzN>-j~?872nAkAJbPn0$@T&0s0)@H14iK>><g;}{B^2`>AA0=;3#N#l1`2xnq<tFyCPz1Wyh&b9_1F;;eYzfS=P
_n%w=oS0TwU;--#=c_)Hezu}2#lM11XV~1e4ViBlRt+*AkF1Z&sv~QNUWH~pe(T3^{Fo(c&|Ri4P6D)u=(v6Sdj65@&dB5m7lp)q
N&7nM3PQcl{lI?c_0q@B$QYL>!mY5k?)K0V26b6`m<k`;ZPb_iSDrP|A{Ia^$0MgZVnJ{=_M)IE6EVSIBO$_i{ShJMe6j_k`D0?`
Myqe&iq;34F)uwef@kT*qu7W3OsOWruM81fA(U=Pm$7Ct|D3fAmBs7#2#m(#lZXT4!u*5{Yla639Oq$5p)9^&laXVl;^KdLfSMH9
o+CYcjp<0<b_M)L;_p21#I|`feA37UI$-n<oVC*4n!eZQf2*2{92~poN#q4o-4j;kdIghVF_Na)v$Pa=NJE<!s6pjd-=3FZ9NFyU
CqDok5R6oE5gt#jjitwRv=Or>%|DIquzDDdB5-tG&Cz>kG|e7NPFZr5a*7&0;SL8i%j7;MfGSLz6^?Wbk&v*5SWDR3SfJ(cKA%jQ
qf0Z4>`-|XM$>FNdm4Bj{2d=EE&r$my6vs_Ff7+@V?q%A;>N&s=j}#*S~xHQix0o-G~QTj$(=y4%Tk=u<Fx>>tTQ+N9ZS-YbrN+3
$ekLCFMsk`5bvN$#Dch&VF#%s=<st-tZi|c`uE?cb(#Y@hD}_054y${%aF+O8NwT<A?O`JUwt^dBq-ce`kGlMy`A~8-IF6GTrpDM
6I+jmEInY3z&Vc6WN?>VH8IpO?Z1V7QIy)v%z7ow4AfGeWOvD^s#?DLZarjW!npi4u$N#Guo2|Y&tY!%jMgW-G^>o`KZSJ1N<*#a
y}aJGv;-~isJ~XWslmI0xL-XjS3y>iNz=hc*h#T6b54$#Q{l!?injp!dEA%CHI3zTd=9qKsH-t!#few>|2EvRv8W<01Q8<%I5o{H
31jV)ZFFXSOx}8w$;2)5Ya~0jO&rx^yYAK0cbie4ULzm<ByVbTCDSuWK=^twHUJH-8tN;lCCKx4^>7Qj5u9u;{6H*b$(lCJkT-Ga
@eARyUfUPHHPm-WCyOJxjOcRq#Y*(mU(@Yu#wCBFD8E?x{RkWG0}v2ig9I+{VW!@{BB{@1{j73(5Bb$0U!(NaoIQ%s2+2h{ceSuF
?nf{mn3(HTgRI&{ub~(18&L1kOtSfbrBa(0ywhcX9J9W~ACfR+M)jHqBp(Hl@&)7M?um|u23wcVeZ)B850i>{#)sY@NTe3?s!J>T
ji=9i708!Dyq&zN1sGx1RWEVoH-t+rjFwlk0ONyGS(vXg#rEMAU}_QuJGcThqw0W;jgV;$g8A*;N$@Zc${!6JM+Mv-4<5PD6qw1%
^{pXQikUp1sW}gFmI1n)sDX8`iaS)^b{I}Ul9ClO<+v{*z1tNR1U5QK+Ap#jmb<e6*#Vp_dmpOq3cj8IrFBX~8?t$1%PA{{i3v0{
*p@QOxF1zU0AAK-5Jw>;JwylFj`z$5fC;d61Zd$)*&R;jpn6^??bjTR4Z>HnN$=zVXgK8|lPf$T(3d|7lr$M5;qIBL009*bi8TY`
g=Ib^7?6H#F3vcRfD0W5xst)HW~920RgN%gko?NsrqQPv*}$V+JO_c9+XqW|0rAWM)`kNPNHj+VB$V4!;d^JO!l6bjSOdKC(`$3N
>7JW{7U^5@49i*TUY6H$T2^JU)pL2MDpp#Wp+`|}+vHZvkAmww^+hXFdUWZG+Ih_Ei2-P%jgr3@yaq<>3*a#Rpu*$P-X124)43)<
73~Zgc%8HZkNuIRqtRV>l#}h5!ta}RWP|u1rfB9}Lic5Up>J~tWg}8&PSqjtE~Q*$K9@0J&o{nZ@zt4tK^E3(BpN_cw|h<ykRuLv
vb=t3#Mah-Dr5Ae9~=1q2ch;i1e65zp^A1Ib`+H{E5kCw2-aE9ErUZNz1aF1_0S3v3ydy0t#~iuR-<m#9#$aPEW0v>skbgAV>5EU
emcu5RG-;=<Dltlpkcgnv*DyR%Ib7A2WJGK=uYIIiJ?-;<h_Jn$4~#iD_m);9O-Zldz&cP(~uGCk6nc?9lRke_EeOcs8-=x)pPrJ
F_D_<%Gv#aCY0@hywr8F=A>Oi(l6|H_|dgBO+E#Uq6`1v+QMVU<fveM^A&@zm(IF%4BaP!9IFzwqn|cM=5$cM!3`A=j3vBfc~bPU
$Os4?VHlVx1=uSLQ&ULOAGxh<K<lt3oFz0}e|T&l@@zv|G=WHY?pkE`kPe@!hs!aQdNu!p${@3L{fx%Oh@0RKv&GdPN0*kjRnP8H
QaHJh8!R3lMR9E}Bf5Ib3K2uvNAUX&mC1y3#NLE&;&dHp8t&UIa_h8+-*5^e482JjGb!J^*@39z#u{3JFNUMe<xD&UpdPdHhVu#H
7H=aAc+pm4QO*$1=iFpz*TqFTY&?+t`hDDbce=@pX=ze3_Q9xj3+GX0{T_mwJ)XNU+t)Om+1qyuzv~Dc_HCD)Z+0y@+1j}GS{}eU
vYo4CcYtmvp@Wr>6_dC!wX}r6>^xBwB<}*W=iZw-J45*U%b|d5DhH@}nFgyNxzK?B+781LQ8=@XAVQ<MkwU2EnEqHrFcPE1JSVlo
ad}i<ZqF4I!Qm1sQbwqq+Dj<Lf$e#nr=jPipjcZ%*!(a#RNoSoSr@M#)cKBvk<gY9(f%E0pM$NsY6$ker<>MxF6KEM|6<T5e;G|2
<&%$30q4oD?9r_j)&$KO$eKg6+%B3E(0Ui%9B48SCZbJE$qMRA?V@upgw9fE(U(CXc7usJ^ZR|LtRgNm^PStPZVw#oGwm3Jt~}&(
{uqu~=dn59j5`&*pA`YsGonXUyi7h9P2(DN`SvMbjY_f4dPH0lPPt;-PQK^*s4NsNHTCe#&=_pv(q5eNU{&-YyIp`&4&Q!25a%c4
I5=Hph&sv_4Lm~i!W+V^Sy!xVqygU?Ju*t5P~E@PBQDg_wH^Io&#>E+Gz7aQl$&Y*ruy~<Stw6khQM1wTRB0BIo=5>3tP-9p^<`9
OKEEyUC6!tgl{I*b?Fv{yLPcyjK{**JEU23El=FqCII^O=`?kj3e04q&2yf$BF<#OL$brWI{!3ZC2d`UiA~KmrLb2Q(X9`pF*x)l
msVj_m0n>dA5wIPExJTSrH9P|))Oq*wAY6X3;g+{+%Wlj<~_B?KcTqy9lx`F0h}C`9I@im^=Kk6s4*ewWLPOo6JkeB=J@w4(_u9j
nNyvSDBIM#ATokpBoo7L(BLN_U~8!1Y)3;Y@>iJ_oW<5l-A5s_HkD~QRL>@Q+G=lbJ*O)M<y-Lf&X)L+IX?o}*kUF{Zqbb7<mQ`a
WLa{v_4Sr1M)$b_8)OJNbe$-K>P4?jKX9`hjJGTcU`nu6B<;!Y{U?YXBL>Y2)+AgzD>+?AZKGGjVn#-8qYnaixH1fruMa9KC^SZ~
sZt-0=;6WK0%mng%sNPSQL8!~+oMM_snd@iyoyoRg2@%!7_rEQeBcs2KX?)Ge>&IfyTAzr7xhJ6+W%Wa^eCcBj-0&ebv7E?Wt(1N
V0L)*pP@1uS%Nk+JeH=)e;UXLwJ*HmeIz+CBJGn4D9rF51CK>ALxuQ7z#+^d=7m|aDvuO3n#vq2J<WPF&e)0bX#PGin6`=TncBZ{
SP#KSmLUx^iqmZ(`_2x=Cw2N=sxJ)Rrj-Hn9a+Kn!SBt8pq*44Ud_kNo3KbVYqsx?CA<$cX<6{+)uuk6$5;vs=E?<T4o&Pb>|?;k
!8?+)=UjFE`L{z{f+=Zwcmd$UQ1ZcdNr;jCF;YRCfK387nZw{N?1Q(rK%1tkpeh0ZNqSX7%%E?y2SlbmNz{0`W~CpiD#Sf8TKrm*
UU-mV;#k<5q8kOM2N3i!QVr?9`qvRK?x1n=H7C=pGyaBPbbL{dkhY+l?zjBJlSmS06kqoUBWNLyWSt7;8oCvl_ta`H)BWp0kfg2z
jG0<gWlRPuSC{u_)TurAt$N)_WX55EwLNja;H%I+DA9F->RKLJcYt}KLSr7(u>^yZf_9^*WZ_WygG|m^LKq7exGb7vOHY7!#mAn5
KE7YWS*(pw1{`?yKT5a~3RIg81ZxN382sb?qb6!)*j%(Jx^@3Y@#e5*cv+k4U8J0GH25MLInJXdyyADudeMdYi}$dY416oi(ZQ)<
EycQwW|9WKUs4pa0EeVa!?B96!Lil(huayEHV`VM>3gf0ke2ziN)hee%zQrN^tR|y4p=JBRV;u5T@rto(Uy#+GsG-~aKOB9Z84VC
k+PpAdgTjQ#G({MJRN9{ts=J7B!P3*=zZCf{{*1fD&SUY<s+zmN9$Nm8DP;yU#}}AGXfl=Jw`PJF)g8GTkv!LD<mFW)f!J09O{tu
AVpRWDSQg&gx6Jj;8qt5DH}Zc^xO(ntW|6{PMT9C%W<XxT18SbxQz$l9!g&Qfdj$kD`MBlpSg}!;=O-M$IXi)ZAM8^(spXL6*V-B
b2J$atZff5h7Br5U<HNeT4M1{Iu)~<%T4h*wzeh%jmHY`g;U->S;ty;d-=P4LBfw0LxC=#W)_!4>NhT8*k*zK3}rY?c0d-v2br$4
i!57|cT&vJ^X)!Bc=FX2_dKdl=ZbjxM{|3Umob<L%~|&P20o5~y`<0(Hp)u1I*xMQr}lR?`{JN``uMqtH(`ZfE{-;?M~JM~l_T?l
mFRn7X3xuhe{y~4rSjwnC{n&mx3H!pi`LEt{~Sv02PD-Nljz@F<|+LKd!mT&Lh%+Wr=dzvMSR8pRJVYs`ismZ<OEaCn);q@srS?J
z$RS_KtO#i4Y=0G`U^9^ocE~v^|m^i&|TrrwtGZGw4vt=H|3zXb&yQni5W9(uqG;`aVR)*=1XUOb#Ki}|GfYHT5>kPS;XWWV>lZ|
`UTz)DI_uocm&(QT`S)Kr(9i0d}_mmAGWmDzX_32ZYIjBm$t~m2Y)thkR@#B<Xj+^<Vw!<azHIo1e2EX54aC>=rVqp9>P@Fn8~io
1|LDQ-QKYs7$6?~r*%cSwljX!FZ+-@{}r9Zwd!rk{W*KJ8-Cnx<lXz;qU(Y9s$1LV>6iqsR|5sP0H;y>ZwERhpeD`$@^A{-Q84wz
9#)uYMTvG2Vu<ap6-b26-KYa0{?_eXX7y~Xt9@lr51Hf%;hD^7noZD$LEq<|*HsEv`@BP&7r#iJAki$?<dn$&U-4rSjD{ANIE7Pr
W9>juM|Ug?Ph*WjzXZ$~RimmwgAWk8Saq&oXG8%TwN*yDpZSd&yV_CgoBf-sm+H0UGXSJQy6n#<XR2`iIQzVbrla3Anp(W-wh}78
biE$!zu{QBVguPw9u`QvBy+*KT!AX+TnHHmxBjTYW-&8PkugRViyB<yWh)FZSHs>NqY|Py1e<e8zrH@=yKEQy6@rzPdm$!W(je43
CT`}-L0Uv-H#imy>gp@soE6RTJp$;q%)W&8j@DM7+qF|Bsr<4Kr;h_}<{C<1{R^bc-!A*3`6g?f=_#B$>IXkH5`8<`CwK-4zrEE*
bN4&Sd$bPnGrD`8N-HjUb;SmW&b{-7o_JkqV9U=Wh3l9EKfZhSa&>#I%t7r3Tcq59g=RP)%swdrkJ+VUxs2{I2mE|vbf%Pj24dXi
*}ep9fjqip*iNYpUJplYU;l%WiH`dq=iPr@xSaC#B~P(foW05wvk+CBxHp{+|7R-XLSu0&<56&%ybtP9O}s-G-~n=|gJvwC>!mb*
|9r8|s%}=kOIQOp-sbPd%b?CMyfxjS8&&Ji0Ga><T%uCtGlD-5<PUvRxi(L8_;(eo3E8h9y{Kfk8va?EkH^fO+cAJPp(uo4(N<Q+
0WDuuPwqs1Q|jvQ?|Y+jWPlGP{D+eC;SVM#@|!cd3T@Q<25B#!j{#9fI~DD@=pZ0PHLo!<&U9gvQfl}MOZNqO^@+<5Ckad8ikjWd
q`$*LrScb-uMH%SR-Cd86gT~`m3rEPEH(pS6Vd+X!C7dg*i1=ap7<EmB@^&e)nogZ(bW=^Z;92M`~&?@-GZ)uhu1~u>{3up26PJi
n7MQu#NPCMy!`$blA~}F>z2@aicC>4tR@YOHX?R7`><4(Wz9WbOJ^)#_KONiO)hHg2@LCaJUXa}m23sgawhlpFn8t+B@AK1*C#aX
lg|wdwc^SwSIoAfWn(N&a2jn$skq%n``A<5gRKmj>$oJK76~IO<al`A`m%;ZmmQ)L@t1^qquK-ahuih0+HK#6SyEJp;5P;ADfAd<
3}NZGzewZGX;Dmz%GWY@nai=r6G62D&S1v^H;q9?dxTa7rYzCeI2^99)h=<s!04nP-%8}y5hjKfi!lG!$N;%C&tXePSstWJ4kF!<
i+=z2+Dl_iAB@d-Ud*ar8$R!otOyR92F6a8{|1SnE(~ZRLxf+AqPoV@?%=(D7J`$xCJ(PYZub?|t+>)AEI%+!393sy^D=mKB(Up1
n`dwO9W+|w%BPEnXQt8y##%7n%M&<tSKdG_4oCU9{;G)BVB6N}ys0hlei*YQhq)0Qc!Vpx)G{4M@e81yYrJ<=02{R;2v?-Bxw&mj
J#fedu7Bv#`2fgB9?j}Hr~FvoW;#uc>;)iFcKE}TkM+*V$R*Sq+vBDhAFaH7!(9guqx*oyxk;I{d~R3$oYU1hQlpJQZoI%CWAapa
fA<NV#x6XUI+szpdF6d!Zd<!5Uw#=BxL9o$axy`_IL#n0AGnSu^r3y737puR1etUg69OIC>5)g9cyNco6YKX~WDkdB;B9s3l;mY_
^y1a3lxCI-P>zZ`*6Xr3$+_}xf2TYAM53so_mWm45gIU*MIlYj5+!gpPy3m066oW?Eyd9#fb}kHt+rn@?JEZxYOtDIl^-M(#3~F;
#ubiV3n_N|nXnaeT?71>Qx7k@!5w|MDs59G47C-z+0U*`BQ-j;XeytFf841pq}#%!vl&lcyNF9d1h=meLPR?q4+0bs-@sb7aloAI
3>W{Z@V7+Bx}sP=X)2nu$MDI%V*3^O6MU(|Mc5tK3kSc3_jCK+@cdv;c%tnSSwK9$TPUAH&1a;8%{2~Ta+EGNC~9Yk&>1iG%GH8y
X{(Xq27owsOV2Fq3PP8<6|+c9njO?md*OQcAbY}|Vc0gxgs$<_1689o#S@y>5NRm8`>P00F%n<SWRo^XR8i@;Q)rp=y+v8jqIuvN
Ac`8^#gjm!TZ{%13%VW&4UH0j^*y53VcRrCS=l{%^+;DmPAshBr`PhmH$Di1{|BM=|8)E&qTf6a|Mngz1cwQ<FckKo%Mozz4*R`=
16sJX<c~{Is!~d`<)rN1hJ6j(muPNU@=9U^D9CTeub!de&u$^vkNcaH5luit;we*U)S#wiF`w$IZ`?4DtG6#Yf~*C$?D~=R(U11N
;pMIh+9IyGn72F5_7-Tf#jsHZaGi4RSeVDGd9Hthikr?2T>#h?PKong97&J8J=>bdA81X-y5S#IO6${ZAD%BL)l|&;y!l{***b__
u3cw-lafAaXkeqO)Sr0ydRlv0H{gfAy_7viOBF}T_!6=ROBPZbFw+YicLwC3q2{*mEx;<Qp;HXMFlp0E;gi~q>&_$sA|+?dD0sWh
rpx3$QZK=E*3{<Ga{jW4Dmf6`75(LgFN9z-FROi=h(EhHxP}jujohpI{4%5Hle2-A%|B!ct12`08sNdVZ;LLj(yP-L*_F7~t$88V
aO^SvG4H+ge7Yo}erbT&zn6^8>F)?m6tUP=WdR=Q$Ax~A&I$aIXO8_p{Rb#nZ-kzNcGdNRYA7J}gwJJ7at>N@VBy>vX85Q42-0{l
+MQC>d{-y;+7*3)Vo;<;?yMoe9i}^I+ppkkN>;XTnkCdWJ`CcOtg-Ka-liA;chAAmE>5l!vh^)wRCzKU)VY<j(JtedsF+SLzQ%<L
-y3xic?3X;cSn}l9g7uAH;iPJvtQ;9(2kXtbih0RM}{s_+vf^=sHmk3SDGSW0Mp#c=b1F?X@Ib?6t1<_512_!D2PXH=w$RKF_5HL
8#<?_<+1gF?GDr%&XEK3o~M`}*JO@kI#rSkpR17?*5R+#@UFTG!{cA$<^~a<mH0a={&_kD0yaMxrve0>T{q_Ap?Br-jwIN$-(67l
kv@|;xP#8$j)Z?}qmsZs(Io*Yz55<jioUm%?~2>^CB(RslXEeih<`-gXN`qwX2aU+7Vm3&6Pv9$jL}(9|4YaJPwymdvevn(1RUc{
Lxt$!7WwL7<5hD6og?AJIA(l}J??6{D=hajqu;of0CHnAcRL?Z(R<+Gk`8u<(?N1{@4XOS@$S7=Fe*fRv6Evw@tpc0Jr#G8`S90-
#3qp^`3f~{=%|}Ujb=dLC@Vhr^U7VNx>v4O%3ZNu&GWL1z!03K9|zVDmfJAA4!n1rsCu?(w#`PBkGh#lnmS-;J?Zq^aLlJ(LEv5V
O=zY$!G&WrFwVArK(bN#4*<$C7cHJq-pN7@sDSp55M(IJSZBUeP|(ybE(F)~!0xN3au7Dn!RDAKZ7s3p-#Nc<pCu?M<<Zy|4ixsF
i?2VXg7blN+d}dc1|sa;!AiT?h^TN>u!wGe_s5X~N4y~r)Nr$Z@TZtJU)C8P7*|4u(tc&1X<q&mQ=4zsB7zE2uA8(WByjFF$#o@Y
nHOKU8h>j=4GZbDeByy5zpMmG5hIECME%ywS~H5x6dZsLOQ8a?6sqSs2Ct##7;%JsMz-QIU$E+VwNBA!=)Z~zS^5_P@mNT^$P`-Z
*#8>i*a`KUFhVG}GZZ>I&wjY@gLbg)>qmq#GCVJ&ls)aaDxx1w8*V8Yh?{tPNbY>mUR$K(FGgrahvsCYJSRHst>8@TBO_%L)^Sgl
anp@Q(K}uQ>8aM)7>R~$GB0*Z0`kg4)4pHL@+^e6R3vrId%6z&r;Cu@yyl9XRk(2qnfgZzgSxkpVR$%pV|y9SdpXhB$FXMXoO6^v
6Uxp7sqp>4u?Qq-L<)eC?8j0Dmte<wc0D0d1E?74C|6b-bvOpgHy+7iu9y>)>V8d#lzI|Y$Tserf@^HSW(Ixn02dWPcwA^XkYU;c
n%WC&t#(We)iFj{$2LiVp-7c@M^&ykxdURd+Z^%*PGL1L#>E2YYNAD5igf;;0ac+oHaSz5;-0OvRfjrvdn(6P{g|qVzzIsd5Fl*v
tS1-NWwk%2<yhYLL!z1q^%$Hz&!dj-P<Zkxj@b|)dsZRR6O{qnR94elkw6rSpWceHbuDw-QKP`=9t@()dxyl~8Au@cX0C1BV;jFD
hB^=68x-MLV{Whd5Ey|Wr1@It`wj*B#>1y7`lHOX09o+f<`QKz$sZOD;W7>Kz1}T>qGp*W+hY6QeO5ZjtFTGU{WZ62O-`bLU%17N
d$Kn^07(Os2|r6)VI~=-`}Q(Fg2Jdp=4YeETxo?Mrk;>EBBB-qCy@XC6x|syZrxF-KEpK(hRB^_#O{5U9Bf5&9c;9Gt)v(Zf*is1
oCWANmBx;B_B%M5-Nk9zRv##RW}NyP*Y?Lu`7Wy4KUu>LLbd?Oa=3!fdy*UHS%sPF)3$e0<+(sXQ$)^2wsct)FPxFcrVu3IKYLm{
9tT71*v`B7eAn&yiKMsszD8JBvelblAZ$J*Y=qv1+@E+YR`x5RUH(xIJe7?nek}H3J3s#$1P`O!7DkD#8SGu~8XKZ5$%q*zd0-?v
Xi18@7gJGP@lhiCk?gHvX5ksR=?Vi(WT839TRKs@Xv<$CcMxvk=*{*Bas0h%zZd|;oY|%`7AlLEQ(M`g5DKSUI*dD;@xtYY(d*tC
+OhL4y;30(UO<C*P}DT7=`b!(cwx;`vfmlC8JIS16wUrsbXbh?b!ORwf1+S$Tft5CG}0U<F(wd%45@qi{3Oj$Bio1OFU~7!-&%{s
%{+YKEq~Kifrsphq1k~~5{gR}S#h)LLRyGw4SRK(jJMX|H)}8x?PP{>f5M0oOp1T7(!Ja?BJvvq_ycPXJ=Qrd%{Om#Nf=g*<HA$S
m`_(EL4X7TKdu&Nj8gj};J0$2UGg9nYcqd7tRG#paB;zVzcchw4TP2`6yGk_sbIzhd;Ejcj`pp!^$<w3i7E6)CD5U8=H)C<;x^}1
`am^>Sh${lRUfpwaOIsq7A$kgR#_sD`@jxMt`51U5C&iFn&NbFP4x~$9nnbT$T#7N^NQ(vl-Bf|2#az8qCB?QUf0@5UmDA!|9ZS(
^nshQC67J|tY(p>`DEbj_$<|=EQvJdN#U&J5`*>~FT?QseU~n&C|<Fq5zRheNkRAZ|L&;SKe|nf0C>(f34U+)HQrxwvfjz13ON-w
Ti~Nb!o_&nY{RILMgAW<y34fhv<v8=3Vv9q%fqLBSr?#w36V-*XG$N8%-6vCm*^NGrB0IIZkXt-!-TlU&z-R*&+D{Bjvl%s`n^Wg
akx#YJ!v*P%c6=HEl4rY|ISEtj!f;%SlaYx-)E9coS<gmvqM=piGr2)SwxNCvy;D>Jz&CeSNqz0p4ED;Ut5$IPM6E1oYU6v&Yo*>
9hOWp^PEsPFFN5oJerAcRCTZ_CzjZISf)5-vsR-4oUS%zD%@>&({;Cs3HXML_|ayq$*F${dtLTo6N^3tA5p%!a++p3VZ28Z!nR2?
AW&ry24yChH$Dsfz>K8PPjK~@F~RpsOED=|qe#ECM9{30ew&$ks&dQi`UQ!c24eQfHkdCHs<A(2v&@))#{f52?I|YTy?P}Re3}>4
Xt=*fzeM)lO&ZwN^58D+9F&p3_6BeJh9ldYu8(*VJTXh(2$cv}haM{PyFpb(6AnJ;MJ-;dhH-QUWP6JD;_uBpdzKVcMm+^@vc`xx
(had`*G<Sja>KbLCNtdUl(VCtg1~@tV#ez)je#yJxV!<NBm&xBB}7&C7Nvfj>NBT&P$yMWxAm%s)jHI)fD$^SYuNw-J%3x^$^#dp
iT9S)NtR5~^GUkb3vc*${z%K;G9c-Zkr<SZfxcPLmA*ejz{$s#Sqhv1jdEZc9eAmsBLPu+j~ivt#cQT)D0a{viy@fw{Ak~LOYuIy
lhj**oG*^(q(q*4Y-lFsLfEOV(W)zK&Uh|MzYP8;(ewQW#bQf4(m72{PKd0|f|4+VV0-|iEx7bLTgDNg4UbK^RW^_I-lgPmTkCqK
wcue5!cmCOz+KH2nG!~h#*PDT*Jv3s8dCRp*Yco9EjoowcxFj}tpnBlklH=G%GKWo8GV972^;5$ci_W-uOK|}`GI0r>}WbjSOfD+
pJrJRu;T9Y?R^VGO)QlE>6eG)c1F;2Af8VWOom5}zlA7eI|w_vYCyAGS*`86XQOW+FOw)72yF?vt%P0Qq#;>`$Z8c*JR%`_Dza-R
64^zL>Q~Y;Sy9MN4XK;2m9@B_hn(F5q2g_spnPT!Wd7myV3Mx~U+A@*bm&%<Ht#|^%-)L*8@B=h_QdsVB9b0SojPbPK;a*OE!6){
C5;bZl1%;VpF@#vsL~Md*p6rDSnrsyK{bRZs7G}~h_@OBod&-RByt<bx63{%Y!9i*WhN0f^mBOo-qfglz1H(%pzKE!GZ3+nPp=r;
G0@##>Y|`cvvN}i76V)O_pTFlkvcsf;)g?r{hayaEK)Mw6B=P$-*w*>;vpyd)TPxB!1stgbwnNU!wJ`F(EwEw1MoESJp7IOph#uL
LK*WGwWr3y&QE4X#rJyF@ND3dTqK|wneL`2_9WU;x#v+qyV~DK05;_DAfo(Uo<E5%_i>E$i31gXO$(pIB*l3VlKWHiQFPk=1#tJj
jm)0SS|_^~jU}>IDUW&_>nEUBO-F9AJ%d<kf&1O)d<@MND_+7{;g%|p5EcqW%h1h3@D|VLmUhzY1mmC)A_<70PIMY*PmwLuEfXp9
l@Zz&y7VEXjmv$Tl%0u)U3F6R=l6r*sY!EN&m~t`%Y|elnL$3vi5q$`N(<w!D|<5W?2HdSNZ?H6`Y=(D+mB^ER#3vwoWAzF(TIkf
Cg-(;zD_+k?+=@&lNJk_^3J6Mo=lM#=Pw*4W%7dIBP+=Ne~NyAskVyZhW^DK=2%j9u;~3u75sZQMPHIesacytF~1AX1WRUGQ4DPx
|K_i!@aCbaP$FcnG#Z#lSh{1?dCYSc^^g9djm;Wlij=p8@N2S&hw{I{QzGXuX&C&$!qOwPFappMY(O%Z1u#^od{^(SPdHI#-c@|I
FKOlo$|Lum^tlKORZct3ZecWd(gn-$Po|Kg%}-pNz$-1nl%(DQq~~wk{G0P0=o~WO^`oRNlRfYwrGp|@2E#9HR#Qpsi$wX=)JT&0
&8yU8R<kO{*@_eO?NH4+EYEm!-*eu-1n3J9y2ksuXf>|d1@rgjJyXvF+PcBbtQ;88;RNMyD6fc?f1_#E_|S0iruzEWgUi}PCcDI5
)t=7%4*bS8?mh<CrJ3CwF3?9`Xb?j=mwHgKdzqj5wWmCG%oh8UuZ#57ca#N-2_Ar~$*&;Z)yw)S57GcEpDCXOC_H`qi(K9(+v4@p
oa-bjrMSMB?eZXtt$23wrwTjL@qFmO@y$&L0@DPMV8~D6UWSxDq>oh7FQ#W6N3hB*+sYVA)sd3WFRh`3;2%-Rtw;&Dho{jfJ!**c
*3Jeg43-PJtM!n`#(+3DNgO7tP}XY1g!tS8Y^2%u%>wF!WWw2&`Fcj1L{oho^5>=Lu?8Ij2>FL3<4b=IJOP~(bedV<H`QkviBQDG
!0$+OIlc7OJ(gY3*1>M-we&+rN<s8ab(5H$Tjr#8TUKCTk06zDZs^7H%x)KNc{A=4?CFnGLlO}J0X+!%gXCJds>jxOXCDa&Iz&`d
L2fY;UZS4|O%$J3EXskLN%=`|^=LrrT6j|lY%kj3@iY745gSGg?datgn2`fNPZ}8|9nB;@X+CMhdxjD=6qeE%EBl$N6A`#gtxC=U
IHy$qylG(4OG>az<bk+(?oBSEJj$n2Zh{Ciy_R0_Q017?^=F<RvUnf$;nD7eAhTC%7)Yh(Nh=j>^efZ^+2+%9_vnAa1yA5_>(YE#
#hM#pcfr;XzhZZ|pOEJKG-{7-vBIBIoT&-u^y+iJyrg%CEI8GW_6^aCLw7f67+*`#>XM3b%u`#!@tV7>3Po6V_~MQPD|&r*#GoQM
(!WlFG4>+;3VJwgXC#g{j`hU$NI`pAj>K}vgmJ>JW+e!?4KB({KYo#nh6EURsrPBj*NV`(I~QIZVO+ttXw@!MDbY%Wq<4UcXv$79
?Cvb3C^%!HrG4$@W2TnU5%d;>Nk98V<J341ZLdD=eEbZ5e-?^`!xKhMMl4it<t#)*Pe1fpC=Z|3D`dM1oKqo%^GMcZg5en#>Iu3#
xofKV`-jYRVxQcy_@*-Mu9^HB(fpF9A>~c6dx#IP#X7G9%8gzl@V|o`4WaN9SrasqX=6;w)+}~z*~+j9Pmc(}uC>3yiYm2MkS_(>
TatTTm5aEN$`U5X@V0_h(uRYagaXc;A1QDR4PI2QgO4X4gtxxjx2e+yo9-(9eQsCY01PFPLQ<3EpWz(Chcxm!m6~*T%w@p+L?u7u
>)zDy@K5E!aAm-Z_yxE)mdwjf&%!{x;j`-Y!wd=@)W`V$6p|VnmOxd&gp8ckjT*ZS9m0Y(Sn^R{Br99XrgC6+-`Y{9Hipl;Dy6J8
nzIWm3)jx}`^W~JKe^=hgPFEFEYRz&W|N}Z4Mfb7M?z6Kc?>abcy5X$l`4-71O3z8$Y_(vI+6j_Io}C!Ys)@PN2s8@RC7Y16%Uum
H%&#UiBOS@lXoeFd&AF)c_(Cvz)KIlHXmvK5@BVkRbG9e_5Q>=xBX1tb^&)*0faj^ssLIw&tx>(Hjng0twpVcMAx{!1WkJC^n})?
pHP%?<R)`dWXOt{e@hH0SEnP95+$;}KJN(P-hSs`Lh33`jtf^Ibzll>*hPlLh8?qD1TM_aQ?6k1Mr3n>btZVE`Xl7yh`;1CV}Uc)
=OaSxe>bha1h2mpaCGS2*oNGX>93I{On!3S_C`OOOL<jhqg@ul$@vWFP-)Oh;Z?D=&p2Ba*^i`)jr|d53X+8}j_rn;A`^s@L=s{t
QRXPY>rgA_T&Dw=!u9b!h}*KFmrqM?SMpg^9Ub^OWs0D>BBae7mL9Yuh<DI0j5)*;n+)>9Z5c9MWPu?uGeF;p;QO~YK}YGE$0--l
jC7Dtst|;)QJ!oUl5c_kp9$dGuC0<T8m)d5WZxXFP*g-P4J0Z~R{YNNlKri$OX46|v&8!ZmI7fozZAFsARkmxn3#!<Zid<2)$iQU
XVdq314ur-;E%@Hx~=AlL+AfaVkxBDw!dJ4zmepaZ1(-LRmvWkuMBp{sol&_KS&LtKfD5gS+rD?LXYADXT?6}3G%l_eg9gA^yEo*
!>H}45mF++Aewk>I+BAVOcSZnf{G!ZZe0J1;l;_?wz%*2J?Uz6H^K&;gmY&(O=>{wN^J%zCP`|en2knqKK)VcmU&wLpiMrk8_O+*
1JO-=T}N<KG`&&W*Uo~(0?}CVQ1Qk=0>oH^kB}9)m$7JQ6;<R+$Jb-0sikRP>Tm-?fA*3?{MR`3_O=!-st+l_5I*qge%j^+iUa!A
<;#kxW<%W?!Bf>p3*7q7W5S!d!C}_@`WK1{P^JX6J2*@ABM4?`H9Mge0$jC-p)xP2ej9E-D-<>caP4<r+6@uWK`j~1g}Equ`p+X;
&~kga^jXe>rfzd!9qqffZb99G7#jo<u$|$BhWQF>2k+>}coS$rp$TU=|BRSfXa_}|8}M%dyVUXf9v*^*lttCUM2KRc@{5yb5e%vZ
`LCEsz^lh@K=_m{WcOWy4}UbFd{L-7kq>NRGT#gO8~44sWgs11#S*qE{)Zb+sf!(jdYxxu?JFFM);I7|J}x9d4mZn(=bM&aui70n
-wdPp__GC@l-_PbA&}Fm6MjpbDiiSL$77Jxyf}OSF~+(-TS1h&?aTE_M&2hKx8g!p2>f#Yl(E6ubkn`Hf9Ed+qSJP2Z7U{tBwEu^
+X;Rj9*@x5@$itblR_5P;gTo|lSzUAJ$o&I^T7haQEWPOI8nJG_9-&+sZD`Z$=n~-pyUAkhs>YS`OxPTovDWekb%S46#B-Pe(&B4
1J=TTq4ZUr?~@q``}utHiqqiHE0a{O6gI5@$)R{os#?$*CwFS^4rwk0u!XHn^Z#bY^{}R4{50+EiCTfSda=|TA&$aNPVFt`@V(W_
L@m*7EBvy%Y)v6sbJ0%FKaS@F2M{HHn(wg#Vdj%-Y7(>QIOsPNAK%zsvP@NkFy>k*c_&EUWEq1YL<wv?H34X>oZi2D7}KplW7NST
j(EgIH2655RH8khCVfd|>V{-DrMIA0)FwGcy|Fv>;*K2tK3v(S5AfJ)si`^uYm4D<GS?7e<4a0kW05>h$4TwAY%==ydnAP9fR5`s
<by<rndhzDe{2!$qpm{b*qZa*@QgV(?7g^)Jaj9r@^1l(*1pJs@CqRUznHeLciBqgeE;ol1xg46Lz@qiky7Ps9^YhAnsX(cVPLP(
%p@lxeAnpgC8hr?Xk(<lgI5WgvsFx4g2`{Z0<M7jH#0uTP3)$i=<~xqHsUEVhp~Zv0u7@c%9GVpvMYOUFbf@5(j4aUr(Uq-aTz>B
dF5y}6sc5|E<iDa;sDwLc**jTy0*fuwEp%Nck3s~-8*2Q!bZBu+1;}kA?$Z1Z8Nr_$iW9^Mj8SR^Gha5!&3%w|9B=*=e2l_81ThB
+Tqv#6qc&9baF=se=kTPQD?C&%bYS7%Q`Z6EbckEX*?V9f(U|L_7D<RVIRH{yVuVlFhU|A&6e%Tlv9}Iws%PM8mM|WM2)Dq<i-I;
$xlV*Q$a*m^z1vn04pLBCYbgTzia3U9%N*->qG$&SdchvSCxI<lRkF;WhTGSReI+9p$g|tuiIAQIDOspAlxwJ-Z;(O>dZm93CnI~
2hjecc)Q@5^f<W)!jS}WoKk{VWdRosp;qQ83@>1H3YHGZsS>>in_m-~3w;erQq4XVFUOl~(e8?0l6zmjk;GRu?KVv+rQKCroQDkf
#>a9s<dz_8M5Ah2&DDZ2sSEPk)u?Ne(ku!nV+#%*b6D`x#>R@^yNyA$LvS3uUjU&7<dQAiW)E$tm%gyoOs-8h&;7z>30@Fx{vVa5
T5=$&rj(a2Px|_|o5rTf{q5o|{*aQr3rx^ZVsMCR6XEnJ7Jn%DR1dg&#d}=Zf@^qyZISo7L34l~4k#Z*^>6KtFT^c|#Xu7Iu`Mbl
XiA8psq8Q5$I3R5n7L=;9u2U^ySWHJdN+&AGT~Yp&O3^hSi#Hdy=KhDa{#5@zQ9O9&A<VlCpG5LO}RbJ^%hd{OO?Nz&6CPMPK1g9
KFRbm5G5q1O}kIfu(8DWi|Yf}(0avPc1S!t_Viigl2UAuv6FrD!MSWI&?z1?@QuKgEbY;gKN(K!u4gMjJUB4ix2zKhhd4t>qVvkN
fIRhlyq;pLX;`k?Qen#R0GRBs{sdiU2#80vcJPIeX`Pwk57&R_puy4%dnUk42#E189K#O-JF<|sjr6sLoGIJk$XcJ;dkO`fz@+T{
PU(B_+BJZC+C%pEWfiCWMPb&p`5M2U8yxwyshE5byB#$z1qWaF<<j*B-?vsuv#oO|eOlg4Gc0&t(cGFodfTX|_C>*RCK>i=j6h)b
(E!|FuIBY1o*A^YxfqsVF}Km01|NN2Ix~r@DldpNw*Ow??$P}RqLucFDlHB$^RVDr*~uaAg>kUVpmT+?xrnLvu{9^r%m^RxHCz3!
&2-HL=7;?Jwo@eDnZw{3%wXOzh8pkVaBSE-DW!?5osb9UrIxxK;_}`c@wD42(e{8Tk|=_#C3OU!=({L+bUFpQmwpG#RJy-eVXig(
ZWQWK&<jkrjLUza`lqElf|t~>f#06izv0t%x(#oUtQ;XpUgMDTk>kx-`T2o8ndU@5*9JR)qdIk8AT>OM10zJv4>W;mD+chstC!TF
FOS~LM?Whp`6bn@3(I{wYNQ6>1=2o}WOfxf{1H3%ro-RL&xcU-x#)EnHy<kId_s)6P5LwzkvbG|_~1BiRXvr>hH(YkDUOXa*lHOO
AIS~@3}`3|>?lV$WHO;@|7RX+Ym~!#>D=U#3S`|e$flB*ioR_9K^#CVwWerqt;-ZO%%v`Dm+X}bj}Q3ms4J~I!k#?P_?!eIEWyx^
@itauf{kWR6JeF8GJAJQt3m6~`qiL5mBOW%jw5t0C3&xiTa?^jlO^^JBt*s(CjAROm1g^7F52nmh|;Rq#y##<5<rdO><$`nGl_%X
{@(q9E=cU=f>XqG4`c)t3-+`t5ffpBt%CQ@Jhb3;Ra`UZB*1?>EZ><q_w^&NV+@t~g>GC4DO^@!LwhD0`ka_kH1`!IW_KtyMC021
6-c*iGVI}*Ywr<DpMgV#_U)Edr2E$3!}0704MId<*?3~55K?NKz`31FhaYEmH(9*?#!;oX0Erq5Y{op7_S-`LTWrrz#n)D`PF}yr
_`o~uX-go(|4nAL-CSbt<i&-eyM(`*KAq9M-Uk+>y4{fxPzAd}6m<`cUN9#d$hpd(CKgu7oN{P2yq=>2SzXY*uKOMJWy*MJ@LMK=
%S_E@aSB4^Y|2jFygT&kYh2Flrpj`Pq{J|dR(o$PinM2i-)xV}b)Z)#bFT{;l?g4Ga+p=GKy&;K?K-?|41sET%Up^O$5%HTdv|z+
<tmiI@A)=I6{|RUtrOTlp4b>%$Ozn2>WNJ0{zSx`&C6Hp5gx1UW&qnmg3!gSy0;C-C9+v&h5QCPm)jjI4fXnoAxUB}*vK4rLXlFs
*{EBu$yCwlO%B@9<tK}dk*3mYrh=HmZVA(JP?HtsD(FXXBf7Of2mEHut?^6X>kDN`PD9wZvv8aR2^SeGn(6V+t1wOx-nv!cmh;yg
m#}O|j!;&3H|)x}VHXv~VC8V2mqiWLUAQ4Z2UDYyJ!|6|8hO<A29sJTSHa+*|BNouf29mx=j&Z3JHktcIc1Ot6>A5(_+sfjA3HR`
KxXz)d^PywJJqRZiuf_N>*&R4l)_YlijkF#z3>4PozwOMF0p59*PP-cF?SCl6Bnh){n=Fl!A+f&6Yq<KFWco`4#<TJH>BMd_|B$@
Rj3>#%SUQM>MLo?Dap{xnA@Y#<sm2zbHMj}zCRbas%}9w=W+I57PC#iL26Ajqg(q4oXoUBwNm-CNKd{r&BjJ^D_zGZ5r0|(&aom>
u-6{s=mGh96+I|6rCf57pPz#-*}ly7(4uF7#iS$ub%W3}-`Eauy}a~z%~QE5+XU5*{9}^+XSF3%h+xK<`Q6&}r~Pu-=xt0aWHFtq
9!CO=P~c2I>s;_Fy7`HEJg43(1jajW*+nIIpPGfthYh|a<lUNSivjx8b{hqZ{ww#68nQ2z?yipeJbg~g%&w+PKIcVPv#WoiHog(9
jf4Tw`Ihk$c<4colOR0S)fm9dYfa_^ib;+UFJjidlSc}oW$FS6?j@0Cw5mar3`L`KSny~9z!5`2U|6G;8=ti=+?5~f{DfZ(7U5W7
)99z}x^Ik`mi&G%yEwO!gvuHqu7h95I+`Yxln@S3vK=QO0<UiJ+3plP*^9$DsWpxxOu~`p_x3oW5_Y2O13^ydh_Tnm{eCzyYJT>i
Ao0-PEog^3=jGb0!qak9Vfspa$Ye%)Y!rC(Iv~j<XNiRDTqy~TunYi&NlBSWZl{0ska9~JH+xMOd~4A~e$7JePc)V=DSIUJP@jif
joZ1+K1b-%b+q{jmV#uRP;byy2!{*ou(tB^tbx?j;+YAovtMXjskBsn6Auc8PU%a+1Wp=|`JDZn>@bH8>H%_sEG)TyIGVZhtCH+E
$f{~s0BeDX@p-VbZ#1jgn6+XAs9I(9`f|AEmEHRK584ll&u$({41^j)mVLS_QOsS2vK#mum5vv3u_F4!sk{-6=|aSB^^bTg9TL2V
zyBI)Yb6imw$&abV*}`(WU*M{L@ra9!yEJ44_gmP)j*qFNlU*bX)J0V3Fu0#S>2CMFSvMP^9W@zzeNo>9z>T*z(*_aZIT;Gq=5xO
ZNCou5lJ0Ps-VGxJ4Q+Tty`peCdn?8mp72^fsqkxXUBJO(&tMTGG4oK%7De{XaojZ`SBW!b8z;OywY)nkH_^s?95G=Czrx3=#Z8`
kHBm4P&W}_G9&HotIR)!M-N|}qOnAAM%f8xQoaXOHabg}R?OAq7>AclSe*jkW(Vte2he43d)`YWg@j8~bFrz=1;Kgg_rMNHV^o-F
ODKd>zAejmJ25EHRf|=F-&b#QQUmt9d<@jDSpu6VuP|%HUa`^6BELW62i?Pr7ieirvgo5oI{Gx3uIbst*`{bv3g#_8I7bGKU8b!Z
`J?d5y!`2Et}9g<?j#6!oW?@~{<jQ$a?6+1F)d<`P?rjwAd)W`Q!-HN>?>cuupiJ>^OD#drT!+4?iYVRQDukz8zf6hUPVgS4|io(
4(hRa0*K3OaSC)K(AZudXq4OQLkuB|4alNdk6dav{C5jz)gk>g>;igS<SRx6EXlC-XB>W9j#BvpYuF%hushh=hbzlG<5iRi26U^;
p=GcMeZVHqiKIP7sl+z*OE^MO{RpVpdSqgAitaWDIZ16Rvk)*^--WYUZ@w)ghX*p(@WMi)T=YX#HM<<E>D;%))xjLVX9{#ug(6gq
D9GOKihR|}HuG#bjwF(cMt}3y7=ceZ(bgSGr$3i6F)OL;==9RRcjO^dG(QHbg&G>EA!s`K_o00Ww(+({J&I1~B3#S_wlJw|GR3jV
OB;EKK#5kS|8tAelal1)&1>)oB^nm@x+BW5W3|1eM*c;?u1R7y;gc3^JZ8_S8L?>lC`@=L5q(+bUT>Bq(@n6Z!Ht?)n0+R>(>Xhr
Xs^JCC_vz`#N=>(Bu_7&CNcvc;aJlwkXk|P&CX9~SzlthZD9oQOP8H~y#)6@MKASDI*}srC(5IN+n|5*K%Nf;L^P)-weNAKUQ?Nh
6_+BsA)+N>${CS((;IHtSVQmVMc?}aiQqQrA)+S0jg5}TF>Cia4J7-x!zTawa5+BX5i41Lg0X7;)*iA)xfW-JX&PVK0$&szH9$8Q
l3n!GL+D(@F0iwax?dn?ws?yYogGfkS-{ODPb@@FOsB$XF#R^n7mApww8&9l8px$0GofAD6WdB%CzW+{W#I-X>#_K1EIt7f3S|3X
`Y)&jWvgLXdAot<VRzV^HKGz`IFIEX>RvTEzqntLRGHX<v-$%K8TR*bB?bW73p@Dg0(8yG%Gk9&J3Vp*exjsWNS4xlPncG6&HL2L
LT-;EtMShf*&>{7TRcRV`gJY~wO`2tkJtwq0bD%EdvP)!Wth5NZjVcTp{t7C)PLjIiyAtLyhi_m%^Iy$T-*i2nfxRAt?I_V_2AaA
;dIXZDgqwnKRFK%cQY{i--WUok98puwN<7NpR+dwQ3oE2`~R=<Z*@cQGiH>*ef}@6jB@d^)Ky2?U-dXI6jxyvHp0d)nWN{i^4n&Z
E)dY_G@5SDK{hDULiGRIlf0>x$}g(L9^-J)1_A+3tRd>t`~b#&;vfmub_&*j5in8+^vJ+3F!wV?;iN%|USpMgVF3k_{}DCiT2YAd
orWap%y#bvFluKv+)CWuLRnl)2=kC=6P?GPh(}7%;|XvZk%_0_=sb}!)`3@4pR(>hSHb6@v21Zbfx&?j6Hh8wxCBedy|Ur#k}HJJ
Rd|>#7mB<IoP8v>^fkaQ6BZ875AJd-x0Fz){|vH}pl~5;+7^cf1*gbF0;QD7lbow%r`s+B2f#{+1A`OnkN4R-31^fpXYc#eL^4Ml
5Q2I0A17%GFpgta#Dl}B8GW`=^kdfDAon^`*qjw2q!~>j6eloBt+3uj7C{2qwR*oTKMoviyG`!pyKSnGdOwD7KC-Ah14~2J2uN>T
zXHypsM=gaTVr=*`I<VWwc$N81g#vkk0^i5vK->RJudZb2x9t8G62R;KN7fIUS_Is797#recJcaroYovW37cu)-SjD{9-hVBsOna
GQ$`12DaL-e{nDV?quL<MRS$cNlt~U=8}~2czA@@7+SODhfu431C_RgRL(-SG{XSj0PyrzsR<2oEO9u>qQz`)W!X+<>M2J)o?Hv?
|908lI|^#6i`lYNNr}V1ornhyuq%yzC2zFX=lw7aV5XyW=p<&sVvG^^t^1TsaT-;w+u>=wRbKX4D{LwY2BKN>_I^R=k2s6Dm)M_u
SzRrCt`)HyD%s?+J=_1u`g7+&DY(ir^U4k@$)|c}TaKmjRn8(MfMJ2>J8Ib7(8L9#<THrlEZgQd{Iu!2Nc>mMfX2=k2C;_5!c6OV
<e}vUMjosJb%u)lZljb-C)_)tU!gZ1(!azYm*^tm0sJ-f3SpA|;(sUl=YTn)X87p!Z}FG-^WJnvxo+ygcko7!&Ta>a(WUXu_Uua9
$%KUCcCEr;bs<n^w}EL<+18u8&yaje1ZCMiAl`TZ@{UXSTYqL8%!dqcLzQ$)X@a4~&Pn={K3{c*wly(lU-}Xp_nY)1yUVL$SW)xq
TSw#9Q~+0mRsL)JPCfa|<V-HXcgJ#nf|#<;#uBt%F)}mRyUFS8+&2U_(`sc;lSNwBtzWazRp|HnQvqcKTJ^toD2a3mg6Fv^91*Tw
d~q=7lo#YC(XmUQ0!c2hW}V^w5*V{e7>g+dshRvXH-~!MkqvE)9<sImgv9pEc|lIUpD#_$m-$jn<HBA0!Xxcc2TDB%AEAc_XPrVC
f&mfW*%NV<Y_`HV4a#nSSCaMl%L9jB1qkM!Q=!B7T708Dcyj&nqsxAqk>`xUmgMKERgllQZBtT=7j$FN^DftFI9cTI*d~LClbP=d
>a)*3&nTEwig_Gg#+*m%2bf?_>^i4HM+14!M=%bA8uRv8>WOvv4>mq8(1jYZGbaZB3azDg_a=pZt@;4_>FFj%24~x}1=3)tY*sK=
bzBnbLAUP1IMXfH!g2y1o<MjyHD$HwTwwl}Wy*S;OEE>O0l}w)C$o*$L@v~e^8k8H_Vkww#v1~!D4?y<VZ;$3h+RjUnNT9=rNiF?
Iu1hjk{*@1d(y2KGG(>WeK6?!y1%2$aY<!wnJY!x0pvM!Zn<2>E&&Tn!BXqzG|P>VdYNqJH5eW`dsG4Wc@37S^(uU5ERPW{r|VY4
ZiWjJKWtiiOPl^hC(w+yoT3M$tI+t;3_$*$6hdg?%Sm-QXZ%#o!Y~51XI?ih^hTv)ow*~QtS7rhN2sGPBu)b<RqD*YWAzio_dMI!
4!bPsb6TJw2d>2O!cOn^VRI_)As%aNQ`EjWAmYPu$-Xx(G#!-Wy0`5Sg8bqt<>&Qt2#*XuIiK0*Z(UHNEEC`>C4{iu@jN*!g+>Qc
vW?rr-DP%(mfNS%Uh*XGpx5|6>aDp_mEbrbM(9|h>m=qD&^YMBWtLL@J1>RBk5Kg|QbIpKViZT*kHw>aM-Xb*zVu<~n9gK+-g2!I
<@fg?vht^JNnSu;3xN($1|cl_UIbGnPg{Bo7|yM2bGlYF5Wy0s83AgRikmLpq&3xzhy942@>~qc9m$~9K?XRJwH*jm1-PHyrHK;G
2iAvOQ3w`$)MaMxL2R?ME1hGW7;7q<Dg58oJevxUwLfURq#Ey>?laO9m}uwycULQA#LDbbG1$rc0~_T=^rqOKsgc$B#>{{sYK`|#
ZQ?mb_Pq{`I2`3Z-L)L~&GORg|9uE8pLOD>Rwr!|xKKome!;sz>BQ^ALTe7t3kuR}e40g|z3QeBP<wSi3f-6Rk4C%r*_i8~%G>z)
{_kTZ`t2aleyUa+qR}b|b-B*i;T{VcAHAh%fnTgyxfj6EB+r2)pdc41eEnxOq{42Xs5G!41ykMt2VR@%<RV34<3kWo8B2|;?qPX6
xOhG+6*yL)=1OuUAnBu-<R1HF(h`c;QYQYSu%f0L)pbu6Z%@%X?uqzJLanAX3dU+0e(fGC4W?}Jg!OXE3`Ilj59hcau<gob@}9L@
JfuStTP+c42weB)|M#{g&kgp6vK}t%!?V@7_YUJmD>YPcgVGbJ7Zs9bbx8(%_`E;09}b6&&x@)<_K`tWyk|M_7+q_I>-;IrpG0W>
Lfr4(VlvcW--{?}KphbEYwy>$-AVhgH{)#(FxI%5cTEt_U4n}<%6Az|mo3L%_X`y_OmMweW!P}LI`ouBqu-m67KL1vJiaF3)u5{t
*ow#eY0Pp}isq1_aC7jsc4o1c8ZyQG(2zOSkB8b5<YUJGSmW4%OEe!g-YPsMXAi1*kI4$0^!I9Zp2Jv*P;W-7dqP#sEHfBe-p7)l
-&W7Wj|2?o@Uv2qpUH!OlubkFU8x=82-n=FKPy`gWpq78vQmj?8VgJK8UX9v?XOtlA)I){m3rOMR*V>^iZvzvODofbWm6QX{x_G0
0IUWUv6258u-gb4a7+~d(0l-zcr4`^<5X**u&RkJN5E>~p92vhA-RoRlIRjVOhonK9>D#0Se+<)Y+1j~)te(x{#^{o*oD7J7(_nH
%h)kOD(^b}$K)44fSp8Sq&j$FHX73q^fx<XKvWw3dS+@Z7-^%I2rkXPCVWfXc=kxoiy$gIb9^Cw-A`1K!(iYpKh&Pz7y4)chFwmh
zTAZkl2mhqW|`L5<rUb|NlpeekxFihkVD+<v>12Sltyzo$m53eKRO9e^q|#0hN*xkS{#K)05KQw9^=kNz6-i}5v#=L--aBpY8=j&
V3Qt<aD%3w9LwaPeMeASa=s|Ae%oR(qk;Umh*%3IMHZ8$w^oIKi-3s>d^F)8#a3uG1ld57dOzcDqK6=KKr3Y$Zla1X#Mc@kp&gdC
y{li9<|&&EXQd3sJ@QlQ-?!*VRH6KNWA>emE%+_ct>>oclVPkPwU+8QWlz(3T4~xk46P)}nVd1|K(;CyEbeU9r`A0YJ@ccIA@{=Y
p9NiQ!i%aq*gY|D(~KC;dODH<`mwKEyRKSE38c8xTO{F4ls4@7LS~^y5;xAI#&W8*H_t>M|6XX9MKF`!Jc#ZET_)1@6$;BE*h<hT
q*O@dKL0Jz-AukO;`i+o(bN@Vwh9Fh(%LEFUF%!9Rd80Q;{gvOFZpQnHYCaJU@_e);BwQA{t-&9t?+LWce6`q9sb-)@WH`h8B(gC
rmWtg^6jK*W9^3rpoi*TaxBJE=-p@tRAam^(~8u3O;(~62n}&S9k`Zha9|3?m8WyZ^;44M@9H1xR%85kmcPir+Nc5{N?ybBLO=}R
vpw4d4y<bgGBnBV;DI`UNBnw_(Kya#VmJ{c(r|F^x+}bK{jh&*_{ME{UWuE~oBHKbRpzG>d^@pPx0BjGM3g+6<MM<x`T4F=T&yPB
e<k)tm6#mnb!c-IHvcCp)!&J%r^o8oX)zK}VY0@*_!O;v$0~u}Sy6Gc^lhDQcHYF+z%tDkTS^}rp3RPUZU1r@6q=4X^MC#K|Hz`{
tXOc8wavQ4k!jWAx<2#5pfj+P6#yjPhJ?qK7uNO)?4LZq=v+;dMI%~fV~J;u>#nE;@rH|X6gJU#C5~4U$$6Flw-_1Q5BZkmdmEZP
LW;AFNrgI^bNPPJ@KqSx8f<gqzH_fK*HhMe8`x15+R9v$2kQi6;#cSgv};u>WQgnC<{b29ZJ+31BDp9@c{>ERk^?wY1W>aEoYu#m
X$$aq6s_coF%w}lF6_i#PP~wz_Ke$Fw`3+7RmJj%&O>n3{?g9bYf{Y{eV6dMP6{Kq;KE^qM8jfR`@kueKn3A-+l-9eKCSTF!4WL&
*y`ca+ihZC<;I4t*i0Hj$NqZH=<L)k8jFC|0&5#h7RmnJhAFnpg20_Ew(6lr5O-mnN$yyg$SPomFvbxFM}9WBlcaD-lMr?)6ceZ}
N!<AH+?gyy+vG8zXzvqPjd<m7T{8QjkKI)j5hMCVMGHyexaL^@*xF#%JP>2>Hk>@LCuL&f9`%PFD;v@GOkhcHfIM83!s%TRSx=`B
Q_l+-B;^;;Cq&5U|6UD$69sT&LdTR8XS)0&tl@>@ZuynB*<wpw9Z@0Oly|?{SX^-1^gv+yN{`a8TIIorQeRYunFH<|kMKq+74+cV
Yu7Aw?RYQ*2&24A431rKPd(U2`_l?pD;h+bL=mWORI}gOUmo2N4`4)^Ob1dz7lBut7r65PaB=+*opl5)r;&0c?x^z_MFJ{k1qstt
iK-Y_zNf5w*_<O1RI8xP);F4^`bkb{hgY=e`K{+yOj4g<yQo$b8)m;`^ral>WxieN^TDr=ZK8aH;Xd#8B26`bw8$pYtc2QHrQNEm
Ak*b{gVwpLj(moiu8?H|4RjhLAUPFRH)^+aj?=+;zw517E2}V6HHT6n>T)%}&@qc_&zyo&ZW4W_o(2}eTg<Lhd_gjP;D{&qZXKGM
CTwXs`wOUs`tCDCCc3^h-UFws2b<bS^NtwWwRCVkLFGw~$LyY-oiF>4o(VM<QODH<8G+HHyxAvqamoMTdjTL12iMtpGUrFAGA|}n
S8(nxRxY%>zpf<!!f-`JuRKR;dIV7vBS5sf!IDAbb94R;Nsso^0wbZ|cFqZK*aaC<hTQTjh4UY5VemmX2<pk(XKet@;x4IR@At-c
(QkuaVnNZ)@+ra6L2c-F%1&5*#UINE;G(`bA^W_Maq1>bw!?F4*m`Cg8RN%tP_Cw)Ir@P@Iqq(0B)DEgp?g66^TEIb%U%x~PF{d9
ETDp<!T5geGh2nFd~KS63Vbb>x0t_wn&jF&BJogWQaec^#;}xoH}AVn%Z||EbLCGfs@oIY6x^O$y&36$YJK*4S0~({GxsRqt=1BI
btw0T=U*2D4UcIk>4>{_{O*d=yzGG%P;dpj?c?C50av7nryH-KIn_D?IFD92D|7*M%eSM_k{JWR_;QQB>l%Wi*dPR*%A%G8Nw!jF
nZ*s0)lSg&5sb{%;$INdT~dlmX2ngLXXnfBkRUSf^sC(VB`*s$!W`1*O6w30;x(t}tC<gorStQZD}C~DZGuCv$?;L+mE6jMYczrA
)oBZ1Iv(Y}*-ZPURC@+Sq9JK(NO0>#o*zZeKUO>GAF!XZAopWmXcvq!C0KH9^RP~FdrNv;ux>FMohv(wwE9;NZ6R-rv;3PGb`H2u
1F42i;L=*_4_<EQ!U;9URWdjORgegnKfAo8@(Pv%GW6>lyq=o;0&_$|{Cq({q|#AO{&F-4?44DI*FSqxLx<xGH5FTiazM~r?qm>Y
-uVm>nDftR_AWAp`w5rw0oyAN292Y+#?bPOJvR8r#dpc23|STwOcjPhhCMhW0Voh1t1eb>C6bB*b}9+SPIdyz;!aNWML^Wq24Q89
?fVRLS;?4>mO0q+VCLG3-<G?;(ULBnVa9a;^EV;03GiNYk1zcqq8v#CPWT=u5OOB3a9XwXUerL{EE{tI{7H!e`D)TdVc%uQ(VsF9
yS{89(`8&f@^!C#y7nfk)5=rFLvN=unLZIZsdiwu8<=2hbtu5B!;EA_+1l%^J7(3<lw{1(kgYP}Q2K}#E|u_U{wOPnHcUMzc>sEP
cLw}oeRYK4d1u87F0g6@{`Z$W#>0XW1eZkHyams;VW*Y2pghl0oSm$JR?jKbSA1_#RJGODAi<tJa|hNdVdAeYzx9jd*n`TY93kD2
u}ynKr}?HUyGa*tANv&0(o~i_X=aE7EXfuR-t)CdKywCJo@BWCQ!!QE()i5G4Xb<SZxaGcP<xlY+0KS)J(o!2EglWgwg*H6M*4-$
PImUq@47D&m4%e-MKD~c(4pLh*8ZQsn;;Hsor|55p_M?JjXf{JH3%cMP}(1YY)tbMkzof6ZqqRu*X?d87jj4obX*$*R8jQ%_}46@
<CDiNWS0$5=i&N^caHz}iV)vS@Va#$g8bVJD=p#Pj~+uv4>B?3-J2bG)Iw6q<c^~7)uudem#R2WZ%DZyZsrOR=}5xI$Z%~K%-#E6
+k~Q1CR5b`MVn=}9#uescJA}{qqsL5L2H5515vr>S*J5zCc_yK%-yt~3x`Sv1IO=t`l2)T-FVL@QY`-f&hOP;Xz8zcd~X0Vw2{5@
sNNs*n3X7A%*u4e)JkN1WR%1VW<0iC`nB`}z{XX_g@hhRpFx>%8tgnLHDheOf}(+=eoEE6I*>m?fOI4VHtUOUmpFzS=ko%ZU;-EV
t<Oem|C2sn4qC6ywwG^4Mg#*t25-pR<;uwHRul|%KWTdEzM2BH$_u74iL->qzsnSil9OGaNksxF!1g6_v4(%i<tos%XQTOoRu+)2
n{u?}tf|qxdby*lbQaGwI9t!uDenm&6q-W_neDKfAh8fcW4jV!kLo6ZNOSDRK&He6_pSOifDnS0;{n>xk%yPOf<x(u;I&<lMWy;$
C_3+_!KPE5kT5R~9yEbju9ZmF#H0_#A<Fs8+Q8%n3jwtR>f+c<Ta$|Kyha^P5H17`M|xU|JwCjV@LbY&x`?e-7PVD%BnpsWn1-mn
Yt)jtjW^Lg@9=v%{j0}m-$*mg1wbBZ1=NxgF>Q}!8vDl!J1V@Luc)LJ(e1StH-I)&if>y9yM#Q%H=O;;k<AtyS~S3^W5^=+=luZ+
Y=e-F^Tzakixk=rsPF%}HQ!W0Qb&c0v{h-Cw2ql2X@Qrz^`8K=?x}7Fq5)7)e7d;Hz*_H=S!9V_onGrBY~jPUSa%KIMT8{Bh6iLJ
$k+3mXaFVuV_7i4(!~bpdlo_%#7y6JqQVOBJI%ryl8(DnHN9+Z+Z3WMv`xPFvtJ5G8Xlfr0cWWhi~w#eo{q<I{vG2CLD{hSX?`O3
9uiLs7gSxdePrvNDFlRr{>cRlgy3a=I$!<9z^bg3C`bZ)V12jelw-bVFGOIBeeE9gzd8+|&$fLI&M3(T#n|2%n!K&4IZH_ktw0O0
<x0S|yj?@P#0v*;JR>xxVg(HHb1wh(PB~#Z_x;7{*3pNx{Z_u4e^cMo`<nJW*Jo3W90;5IR};bZbHv`f<v^t;LmCTJ_rkbi$Er*;
cuVQJ9U>N7Dr@j(um~WN&Aq}reE-1IrZFOY9PeNmkXC(`GZBkN>jL&$<7sr}F%bbce9CE|s!+u~8)4!y#K_g;O%(fT2~QJr?BrC-
?c5qsL=<v_zR{ZfS-cnG@PdC>X~A%ULvZunf;9K>loe0OdQBCLSWJXkZAmY?FBj`vwJ+Rbn*S$<d3iekk;*V(`7G*3&924$n25@^
%loWo$<1*JV<P5O`j)}a{DL)OSu6M>iP2n(`_^eP)|f7uQP`(K%RAOZ0RS#GClNW{HUXob3Nsr<Q}K=Pvni=_az#Gd^NJ`}f79|r
Brn7Ag~pB~3oANB8WwsXkL@;N;O5=I+*4vX@w_XsGWO*>8W+M*z3@3!0VcAGtAv;)zi?QX40$AoEqK@jlO1mE(!4b^yC~wCyfa!1
S%-_n%R`~i{f7LcE)7amzsOSp_QwJ;6}AMPy5;4w6y3knB{;9XrtZ=2^kjx})Lna!pD+eQ<m}#QbqO!Xta9`d#(8%lqx5Z_tmocm
qMl8{n5{vm?D2PYyH6ET#(<dK7M@woo@DxY^~`h@<ma3ybdBaGu0aQrwugVDL@9DP<5e?)55G^&7jGTNaU!$hM~3Dk)jQ$Z8_9>*
19B+Nl=fG)D~6V-k<y<^x$QOI%S>C6p(wrWxfE|+AO)$k@*gii7$z^4y)-p`K%_>6fm>6_Q9h+or-vuWBNB~upGLvqxvceYS|j#9
UJo>^eE<#_;9>0z5!;el_WWGk{XBE?P>`4{Yqs9O5+~TTC1qZSsZg5+&}k2StKso;bH<T^#`lb_rj|I}4z$Gu8K;>P4>N3HAY=BD
Ny0yW9p1^Jvb8<yTgpzChQ$l7tHdLel$*<^DeiW)4_KeSRDBK4w;P2Tefr3cHp`pAi43Ux_}FasLuKDznQi)$FTvxBEoFp*S{)=k
woK2J=J4dg+PdmyqW3Fqqo0zVR+yC9ISx00lEB6*mVHKDO^R&Bk*W^!@hv&h4!1{Q>_pjGf>JrWm~?&$8hIjWW}flKvj+wFZK|-F
do>rHEjGzeh!||(!xnT}Q%m6P0Jdd73G*6%EfskMQ>(7Q!~#{2wczMnP9r(^%lmkI1A~bkjp8rEuQPGNKAijdY`DtQ*gB_6R(PaM
9qwLlHlR4*y;f+J_)-F|sV+|yd6H8(o!Ue-7I+IiWv7T;6u%8vI;}df!o#FfX&Jc$5cC$dMOy&?ISOtN-sz=G)YyGZO7E^UROcRX
?HZ^hb^;zwmaRf@z-}t#sJcNr`CVRKxJm@f(;2i-mO#0g=5%icsRP5cFS=$H-WZH65Sq>Wyx@l#;SUC#t-&+C>AWnXu&Bv@lbhUB
{*JtMb8=61UGISI<*t3Y!GP=M(<*xqePw03ZzdBA$T&nB4CGLP-;d2Vq-d2HJ-`4!Z{m_$kD)BaKY)z&kilaL{ST*8oJv)XF&`J+
E<J5)vwd;pib>36Wtc^bSS~YQi2Ml8*eBb0`8?zcTiLj8J$hsaja@cK{6kI(*&OHj^umg2{1eagz9k;rYAfNriY~zzF`mWw_3KIM
!+mjEvOo>>{d{mBbxl57#)UhF$@4fZMjljr;@Z%wcQg^>EE2XVp=Mtu#3yK^2PxvKF7TbjaZsa2$@y#&kP?PvDlqn>`1|#RUZxd`
2^W4Cgv1G}m({KEXbe2a_IR6t(6N+cFMmivaefX>SdQO)Di(vZ8MJJSy?#Z8_f_fF__OOiq0CR;6z81ME($^hU=_8y=Q%m(n}ChM
43j}R#@<t3;f4`$_*J97HpzN=4m|7JnS;({c9dUS)BsK5jJxTx*e8+n;ASqjgNc{%eYCfi!%TZF`S};NW=0l35`UH?mx8p*gtai`
iTQ58GwY6s^Ql1}9kdPX3JW|7OG?oeuUl14*_2)s$;|zKL!M~kjElSfWSc+rEEt3ju<GjH^s9=dxIhu^qk?<BXI}fkg9iW&Vx$3X
kQBl#lS3w-gCrR=_b$PwY^rA8R9MXy@|6O62t;-K&PD&YS{bemrgt?odz(>;kPT>ptAlqTCGNwb9MA<2`KLtBdsOi{ySX-SSrPg#
h-Xg&=-%3krW~H0=hJ0BHec^zB0saRo4YS_Pm+>L_&smO{^VV*QbKVW5nD5MU!7Vkk7&C4DV4qT9*svHjPP#H`FEY6*N<P@A4SY(
AhLqZ;Bx-}-PgIVv@uG93y8)@QfiiFc^@|KREth)93qt9hchPx7?;w<nka1S&J>_-7fQr`(>EOniwjypjk?i2?Z2#O)FLQRKZ}!X
+d>0K@tGQ)&R~!u%djv#G4JiDHx3%6zwx!)|1>6qh{p2bBu_cQG2fr3kC5}g>Q(hd)o25{@ne^sPOF~{Fqmx5L}1GUBtYB#&T9sD
-5{J)!7k~-u_<o_3l-604TJw^>wt_~L|G818HBLSy#0?Ay#9HFd&U>Fr@_7gAc|D)KP0!x*(;bcK)Gu`qRq%=8$C!V&@sh$ovYG8
sdXaN?uD{b;93lsoS1V5db--UM%w58P$nwJ8|p?L<L%;-q2?O@h7ZW&MZG%kF=D!%Fue+MGvWt$W(+|{#P&j)kkKxjC^ks+6PDU7
aIY`)u76>>@;Q8|#UrN7gT^xvA)cE^)vOFCha=z+D-^$x{tHuAcn1IOoVyW-6jbAJyRXE`@KQSxrgOwmA#}xr1^<*beu4>5u@QOT
-$KRX=Lhr13&s)QQ};37NtA;x!OudUC{?yQZBIA55HTAs35MYa_@2m`K=nrc)<(`Z88g%S-o5K5?yK=-bJ5WOSnnybpXi7>Tf_Vt
Yarh^Cs4z|h}$lgT^AYPY}hT+3M8i$e*PxdP}&@c$!t1zAauQX^3tON+h2|Vvhqr=5PrD#5kDi@ru217o%S@24PB6D=XWFMY9}N4
HGQ7$lkbelZWu3I6(mo|2q}!!!VCz}iNBOOqt0R2ue<1Vs3*yM=uX*nu+n{0E^?_h5)*NR1w5|E(ETmG4UMS>dP(oP0!fR!iIc(x
lPuqvJ)iE@3h5IIN#x(IcopHo|2ClqE{L;BK{w#Zar_u=`hoX@B3BwPR-VS|%3Y$AHde-@w+6kE^iHfoyQSK!*xVteE*cQ+_d|=1
KNbqbMwihM^BuwOfgD4W2D?heNn6Zh_x+c)4ZEQc0>)He0ZsOn26a&Lb3RLn!Cy@P!yL=TRZ9vDh#O@FGvAXDTLzkouclB;sq$$d
kfelX8RQF*6c}aRye?R7)G+J?2@Jy~L+GwEP)hQp!bI8&0@1Whu!)5j=g+U-Zl*DtrEjssyGo!?f8{s<IW$qx$XY!_ZDQza3(`y~
+5Y^ybw{9+kLr`JbIT(rWnv=}+5b;{Q9p^L@S_xxIdy+Fxn-J!_zVSfwj)(THMngt`^u0|9;s*(l1rU(b<Q2wcvl5j|1t-;hDR5=
ZplKj#?!mbS`B!XFOn2PO~##d^Dcmfyba0zUb0A<GEv_Ps?f@svRacj8^?e~U>SCrUlNfSXU4^Y${1+gWov!)#jfnI;Y{<w5|kEu
H(bRN5x=Ws11vbqCLR)PxKQ;<m8Fm9quT-%2rA{aGS*Xu)D_#+<P*?jN#~t;vay3sw?mO@AEC9qJLz7leVgc_df*<9Wg@e|93|qc
CmM~`f4?1JjCQ*9j)3Zl4N!Eb1!C|kWcdw{=?81I^fBfv^$SU}?To4g1hvuPl1`@jCgLiPT^$EE^Ie4GGZn>HJG|u^H9f7^R%Qcm
HVz~`bknyUEDL$5h92GR+<b0}(}W^%*Nr3;0HG|14soWkdt;krMARvnJCYx{Buc*9z2-)BSp*VUi0s-c2}1E;3L??=gLaFnf38<!
H-e~n6iS}>usMyPtt@yy^nyW2KzZ5HKQnteWIT&Hr8OzeH=Ye7Ag|0LKRv^kdN5}U_(7O12xF5-JU-HGpn%l`5mT4_9u2||=dZaz
bUtYcqZ%XRt1=9GfG46thHJD_)19Q!f;!*2c>f5sL|@58R$HeyIcsI<+9_Mmc~v`Q<Eo~8|BSX2-+k63KdAmLwsL?1lUIiKt<Wes
C18hRY~$_Si0XRRFJyKeG2NcvuqBo-S}gOrc6A33D3-}+jQ4WZziJ{;4dnTVM<gSgG|+*~9r}%TR0RFV#8KoV4z#92O#ziSWYFVz
&$G6c?CBLz&`KR-K*j#lEdw8PjJ?AfvxTZjm@J@2O?k77@JISybuzs6;vGVq{rQYUO3G>gSd3HJSHQ>TP}b+RwJ>Kr|M2_p=uwJR
_EYQBCrgE|8gdHvxQESZqxd?AQ}$ss!@j6oRCaz*aL{NI`+$?&tK5T>)4#sof$9LH)v|Cg_qk9*6Q0iu6|VGq;*h)wpre*-Bs($D
%B*SVQnfL@Sk@O*2hrn%dsBt<k~-xh7l}!yrlp`W=2euPYIN+im&PO!>|zX>;+jhfm@GX0U&o(PGv#3Tzs%O$JMmEZA6-ywS-Jr`
Mpl&}EL54*d*8>6bH(RyLj~)w!T6ELzd`6XH>H_Du5ovH(enB+2A-J3_5w$SsmWQvCjEhmTdY#)Q$W0ZYC^p8Mh5wQnw}0spKG@5
k`A{w8yy1`efA*@F?=SFAXhA&qn=Z;8r=Ig10qZ+g9j#s5M#xPDt?8+j2H2eT}tHX25v_0LZWlqr#0E|a!B&up*ixaFq&ZFcW;tN
kRs*NOKSYN^OF$fZwptq0~+z^L>ooGE2C`GC7h;w70=8nao|%vpBrV#jI=rG+ZKKQ+M~YmHhQpERAGXR`dGGlPe~c0@@1g$woH_l
j|qd0vR3>)V3Xubx8~Zy&1$yo1XD&!!e$|wsY;n%m{hdc1)?j3dY2$f5P{~^<wKuF-aY3q#<Q(mlG~Of*;%hW9N?0jw)&nEn-)@P
{v*g?b9EBC;Y}v#s}iAwdhubW79&E7y$rJ3>Be3G@nte5Yli>1>}pU^v<LQlfTe+HgE->+25+aR=3thyrI6D5W4Me$<Pvg9RpZgl
7#a?ylQ7t3B6Ulyz%TG&Db4Ps(k7Fh=7y*ZRhD7oHkCm^Do$5Z?4|$$rgbq*BN%B624K}>v!-}3*0j)_6-7HHHq++GqKX75H>}2{
jT@|;SHZe*a;{SSE~zJEiioejA@pFqnmcd%P46lWU6qfY{=<kBf4|h1Haifwu2C)jn_>PEa+o}LZ+K#&EzR9LslH^=5Ss9r&V@HZ
O|{lCZ?ukFW%x9`djt<917_i|a@w0x>@uT)OoHf+5vOWKqdw^))iM4Fc+U<(POSH5VfT>Qpw%Qz3}`7>%<9Ldine|OR@ls#C&_b8
o{wck%t@0axP0-dx*cc<AMp;c7xhswcn{4A_L!8-cQ(TBYYa&xpwMG<Hgk|!xx~O0Ic2R*&FY8dcHoeSKeT-T7md6H?&cKI3K{ru
o90oHKRA<Cwo5Pu<B+*K((EGk&RyU7lksPrH{wAqkcVm&^p?cl7+!lr>A8rbx!7f%8r7vgRXlf^Gk&i29=WQ=s}+~ppqSG%-Lao7
5hF6h_9RZlF-)?gE5029B)$U5;j2sfp=k894s;+X^A0o&`l(pS9n&R2mmb?6JyN1z>&X2&7T#D`Emh1Nfa+}wWrMSTh=bEqV0L(5
07g92F|Pn3@VX=%sd|x`KqnLBbD#$uT5wj3s9O><HFidwDoJL?+rjF7#A^%5e>OA8vl))_VpS~#jr`Tz)0pINNT04t4QX&JnNvuC
P5DhBM&suuM!vwK6oh=U9m=E;KTXQSNl+@%Gn51f!?r*@K_k|7GPB<Ge!WwX3?3Hp6U)H9alobtx_&-xdZ?Nd-QR2xl;N8YA=8O5
MDWT<mzcfd_n?@oj5{oWF{d7|NB8O!Vyb!QGR39eMsT2`KL{V+5g)S<I-nLOMWph(ou>L``(J5w#_o_v^eC&|d6t|rV@+=&cx%+H
bh(7Bh4X(4nwUQ&sA;R`XC8_zgs4#4?}}P@V1jgnW%U4l0e^FpGe<yx+<y~k1PAqhaAyk$j+TZ=ErM%|aEJJ0!w7LeB&gNQl7$g0
`E*q%Vqxn|Lli|ZsKahux)Vlk`zAlOmX^1Vt~qlHo>ugCC4*)zs!ND6vY+;_XPumOT35yo4wLv!Hp$Fs+Z6WMEmRw@6bB8;<{lUF
@QVGeo)=<m>j2Ny%LTSzkHjc0Le=!!L_k35<reQ*C8y$!&*W4%5(1N4C6iK~a&e!j&X+$TJNlsbcET5`&IHFh^r^l6^qiXB&KMmW
&)g6_s3Jv_wAT-Vso>`>yHJ5pP~&fUn{5E9D<FwF@al!stIE;&P4jCwrfII`E6)J2xfZQPrEgv{W<_30s{dN8CyM8Hf5@d+6X~i^
hTW-EP7)XB`9R;RMwLSUd2(2WS^j-7!$j31S2jHrLASKnbH8`T7$_>>=bbue^lKBD%oD?OSAgUNTS&q)*69Ausw9ZNdcZ%u-M5{7
TWE!OC5@3{0p@><(F&lQ5R|t6RGFJ)?#_s)^g4sdw#3UIRXb$uY&k0?JY<GPl7Y1a_C7XS#*-d~L}~MrjfbPK%=Ggt9uH&B3<k=q
D0?hFUspu-uNi<Mnre~=j3Q3+d#ClOM{w)_abNAdt&&XMH77IV;vr8ih0AZ?;ApCHahb9Q66n@m#FZIPUomJ9b5YCI<O&+RPB8-|
rPjH<;pRlLYQ2g>B^@cIf+39`qf=^UX6J&{+FKShphsYRq^j}>6Hm|pZt5|}ed`(00BZ1b#a}3rA|_Wlb?AF}?!{H7q2nwJK(Pod
i{qb$rwH12!J~_x^5s<T=lcLeCLT~yYW={P1ejetgpR=I*tZA}+&`rI{!<lvIRCI^PY=H`JQU=V{I#Em^KvC6jj%#dQ|Xwt868nR
xJxEu3cM$FGvDKM9E1*YYhs)#SBEe9Pq?2N=8Ndb2>xtYYNs$r4*<8@Z>NYllj4S*+d;(>2B1sKytlfWqi7NRU?mOYsU+%K5UpJo
S<fvEvAJR*XkH7Fqf<)#VKvu_8rnD7xHIgv7xFh6wbABVCE|IF5Xy)kiPj;<xC=tfk{a-RYPS9YLjBm6M*^=QrA@rZ;dtBGs1*zN
kKy&BIX?={lOaoOWAly1L}vG)+glvLv{jD#8W{^r{kVE2yn;F{R2<!Na!BNGJ86sv3nvWu4DUJhRRMjq-7c4flxuU<=K>YKz6&A1
1_d6-54s|3#)-E5)i=~d3!TF<RM-XcSi8P&B-@zDS|1gMW=rQVo{d7*RfqC%SHMS6xF<hoGW$OI9@5~oHyx43cvs=i#=xGdOg&kx
VNhKYH3Ml08KJOgc}RJs{?&A#a~0WY3Ve0>;(`MG*tntL`<UCUy45Mh({z>$4?3^GdW4jQ{9~Z{v)eHyxsO5aWG~(mH$-E;aHoQ1
xa=k%a$z_YYfg*m^>?Q$%E)N=&iYc`l^puZS<Di;fFR|P7;FrH#k|12p|{*gmR2-w|IYF?F2(lfHA6nh{KKQy7o-T}F2YRj`H-F6
h}Y9y9t+FSmB?LIoK_zOcWe%`+)9N`?D9gnf_#T<0!wAVb20hBQ0-sur=J-iAA%Be`njZ}acWdJ@RZiS^&7d?Gu<a9QMmNa8bJ76
G`Q>kA$|=t=w*Hp1NRSJqhSPpo1S2<i2n0558c4jlBEAHf(qLw$?UwcF6~+w%x{auIoMz)D(evLDu^JX8|9aAI<Kdj7-}$)@M&6O
*AD3<J(2{(QhibpYpR7!%#p;n1#zsA!Xq#jHJYg^Mm|{xZ#ZGsTAp~`vf$z51ypRdyI4;VT|Af73g-b7cU`{at<dLDhLFR2n?O_s
79Zw58F)@W*<~+W#>cjE2XgZr?*XgBDe3?fyR`2J=BLe0KnXi|-1&Je-{GpZDdqCZ(QU`B5Bb3TdRF+FEr$Z<vJ|DWCmb2^Z$$Mc
Aftg0Z@|&rAD;7-fb0Tq;Q|AKX^@^O1)L@`(FS@R3|ELS$!~&PUc=-C2=T-$*~MXVOnP9T*@ALnP(-Pq$B}xA4Zm_4pXarY{^(X7
wuv&=a>4=*j~sLX(-6A4jk5s7rR}1oA#Idv&YybJn(Djqw4bCt#URvs;9H?Dfg}^2eA4e2J&Wzdyy*QPL@kLQUa79|`%9n>TH8q6
`oNNJbM)l_Q*f{ieJ27Pj(ui7ymbjr$GuLZv^x<XsD!Iw0!+aE&znlwkIi0?iw_;4)AQHPknsQ)pdih>EU(*>70!W0MmIdw(-!jK
$n7v5OPTh1i8J`fMQrjUq*2zOV75(?f!LAz*6p23{83s^)xm)4L{0-n>%U_n_hUq5<#h&oL7p2p!^vKj+4ke!ZhQ@tHa)==Zo+At
*IQ<d>=H-sPvu0{|C^BxB0-pJwGb<|>EpK*{Gz+@!}_}MI;xKINvHnMjNoW-)^Al>-DStqnkmp#x|onnN@Qah1j80B5Ll;&_fBTR
m;o(!03_99$ovaf`#!%xPD^%_TQe`XwNr832yJy5Dj*=QWx8x{)6)Xjtm&M%L;{2BGnTW1O`#0x^f!@I6G^30_PEZg-@hZJht2&1
*t|oltsSezn8{@UqB-PiD5U^JZ;O+-7(Ict4qn4qs>^}G?O3hJB!2!zlpj7ftaX%qZ^-3KNQ3P~e3Y8HrLQ*CYM2~hWnV4P!_H5X
5=%)S5N&AXRvJ#62zjff;Dat!VCV&snaRpU^?y_5Gu%Bs*7Yp=CR_@3^qq`~4?>_>tcUy8m)<%pG~zlY?nU4Km<`f$6f7D91Jg}L
IgF>Su!st%*27Nsry7<0{>CuIB6yiiHz22Ejb*tn=GDzM=3vis8@*nGJ<f)s`vcoJ8c#=AoL!)lesnXWY=|f(Obj+}goF^VUc<19
g2h$i+EXf|weTFB*LNo5ry^UD>acLhxOB-59pRgM3xnhhMGu)uce^}AmqAa0-9P@IO@gC)LN-)_$AUB^+eKT-x^&$3DO_1T4`@wu
+w>D?hUvrX{iYeD{{k#tb%e6e3QS^%qn$OTR9(sob%+t8&XW_@>ctLdy~bI(I1$gLxkWm(>>&p#Tnw5EQzVqxDT$fu%ylt2AvR1)
kH)z1Zd4I}v~Y@-E=*BnUtI4d)y0={y>(@qY~&T~JC+RCbgH~dJ#m$I0U6vm7n&&Xdi-@9m;VAxI4;LbvN9PX?vgM><nWl{(nUnc
;H*Q**eptH!BwL-&P2i*ki=W$q;6*spa8Q*+!P;#V_|g{Iny?#ujgNxb9olBM$uD;uvLCoBb7BzmYH34Ri}>2zg4gE%eP|T)u_Zd
fbUcXxRoqeHb`!y!pAK!!`qjy-*d`j{I`!NCxN(vUSrMH2~2;hBdf?TKv%Bke4NK@wD`F&S*g8q?A&)~0C1S+>M*z$O87^74bE10
x9{1o7Cq^F7<*!Zb?eUO`YbO}a?CKH@L`2iPoF;c(J8J)vf_8<Jx4RZTj>CsJ(8b>Ok40$sjG`^4U!8gLt%Z;6#?)-uJq1#^mLda
br+4;z>eB{w4*luv=nwl6ZQA%fmcZi)erg5xe!7Pz}dC?8(uF@2ARBJV{8f7TodGg@O=F)lR&Dm)++-HX4A%mhFiWdQdaroFFmbf
;3$Yd?{)(#CY1Af^(Fn8Njmw=D5Z+Qa_N0jSj8Q>^^WvxDBLI;OeV2Esb*9V6ievf$adO^mkylYMo`3ZEZfvO38c-PmE{Y}WUWUZ
-?ctjM(k;RxjmikFxto`qKbmH(1EuJjWglXCk2eiLI%Tt6g`x}&JSnIyaiL3tGD5SVL$t;C@SjeTPLR4{lMAT0-|)?O=pYNKqkXt
!ret9W^0hn2DqxB?yB75yZRtqJg-_U^=p!EvYCCl-pEdL%LKER0v-S%&nkIh11HkFxqbYcD=pcI&=M@13b|Z~I`b}!<%0@&NKqHw
_#o7x!A3?K<7IjInM6dPTeTv$LQx->WnxCS%fHV)m)B{jZ*pBJ|NlbjxaiQ$+{h>nm>`NPV#$m$j~hXD^i2H2dLNw3N5mhW@W89a
8Ftm9yJ;`%?zTf)n27n-a!UD_P>&59SdW(pYBb3daUEi#i2zQ(>|?!zMC!Yl@31Zq{1taj7HR}rjuNf133L;t0OB~*0`VCm?WN;`
EMgr=@`XjS1`bElXaaiFotQ7Fbo9p95$;bPQ`|tt|J)_Fi7%x+<F-e=jrk#|EBb=(g`}8eQbY#Q@tjm(xWr9VM=z~Cwomyxt6Em%
^G{_3yhjOv{G7r+86uw5!Q7`wuJdg@?^`7Z)NEdQ;Lc=^GjkmxYN_9(atjGVvn62q5GiI7?K-_9I|lG?(i<-YN55=Qa-DVre9m@^
A#a^gYoViRdM!scVCC*^bz{KuN^GY2=qmvs3Lp`6_W96pVD!}ZCdr{mI<Ibye^i}Mo%kw#Ak&~O$*a+OR4T@v7BiM=!)I?+wf08+
5uJA^{nsm2J(SMumow~mC1Utw3BUP2B|XB&A%=>CNq`??6<Ar>tG!6*9NZ@`T4x|&m1q|mw;p=j_j@XoJBe|ZBHSu<AgFz%LAw^3
*$}NFOu9V~4IwyWKEs9khB6tVuzW0c0<1{@EA}YMB$TW@O&F!9GhxV+=n$WZctZb$#X>Y)8`WjqTPFV9k;gdVy&vUy0s2CQXu{Uv
Z9dGN%Y5&IPljN~scQhGfFW%HgJ*l^<(rWkt*pv&k(J4jKC9P%T4#ps6?}NF8*?{gUviCN)fz@aZ1LJ(o1HWc@%gkgr=X^Xl#C=*
Rc|YuTN+}Cf2b-;8Pj{H9U-fO|0(_q>pcY;ZnM{!7C4Cu@O+KDz<1?@y`anR6~XPyp^E|B^%;FsJeWn>*IriOCYxbLXp}+|KcmM4
H|hDq0zKy6w>79=1V9Ife|I5906DvOQ^19z-JYwB<s|CXZz~A^Z^DTLqv+<5xPZQRUWhzhcM&j_xewAM`+Z`d`zVf+nE?(MFrM@7
;PcR*&Oo^cB>}Wp|7bVa32qOx*pzB(ySmY<f&gXs$&Iv$OesR)PFl6|%XNZe38=U0os5BzqYP(Uzp>aX`yAY?6Chh;%|{dcv^4b`
2Y$b}(_WeJcI)GXL{#4$%*t5ewD;pIMRnn+!c<i@Pb+^AZKJsff-lHd{BTXe2Wb7_@+*p%3oNe*yvvPsLRvpW@=#!e8EiUJZYf)h
cDxw%<t|GpaXg;bvBLokr{#I3=jZlrJ|h;pm-<@&t3V}4pNwjeNIKbERIQIYH}EwlPKB+OeJMip^5E{)%jw<vHaneFI!@eX5!LgX
hQ+#mc1omsqJ!H~$2m3N(qghePiPjf<H`*x4DIaqv&f6;qh^mET*_8@SD)&V2(3}(fsQ1(PpOto<W&Il#i>4~0S^^RJI}NFxaKlL
9tofXOXvCQW=y&{`x<N=1U1<Be^As&7I(Jb^Wdqs$J-gFrR*9-$v~Cx@PVY*5awV&yJ7Nc>V$wY5IS{9S2MqVf74TobQI8kw?5H5
r=HPU9}+4g$eBV3(c^6~>onC2?<SgcSG@a&U`pdMG?{EPT+LK~5Wb3(WGlf!r*zVg#IND=+MNTET{Jt1IA`xYN+efkXp1U%V3#u=
9*bB{z%0!v-k?3>E-jFl>d_c9!0+<E5TE%qqTo@ORM610w5tsO!wC&2U8^nHjH|;cwFn1Xiw@6%Ro^#k@-inv?Byj?%a&RNmzE{y
?tJhae2-M_2JP7+x#o;v{eUE*(gY<5RMk{e=mH7RpNs;|{4ZvhXm;zyGoJ?no?mY&oj_ZIp2rk|;Ku8MJC*op{8o2_-aapbaysFF
t`nZ<Hft`~uZ-!o(e1Sw*H8jN*xCif>=FCJfO5%Xf*ejZlB(_G?sYLQJ27e&Metn1!tr7+N+-Z=GVh5M%2i!Vu=H=HI`OqmdHTxI
vg6_Kd>*6k8c2G#b;GY&JNK2|!=%lVTd;uY_8OGvp#W9)@&k--mc$PNj?;|Zg-LyHQXD3cW2J<<IVNmEaftv<mDWK&Mw@*{E9WGJ
nU9!dnpYdc44@8;5alN4ZV(5glL6NISijhugURkYJ<~FgkATu<DFUc(LHI~2-t+5GTn+X>Spj~!<g`rYDWu~6evhI7Ut*>aI9kIn
xpH}dd_@Mqx+pn6!|oxa{*V4$T6Q1m)BU8lNGtnm>=H3|axE|+a~hlj>qD`&k;|=7T7TBT{q}Qm6uPzz(3hH`M;z?Pi&&guKXvle
GNrLq+bXG#*Q$^o#@<N?+tVlSaH3Dtw1;CcwbVn`Su)~EZz|-^vDA}dh6)kh*KQ7iXF^3Zm7=}WqhPvpiU?%Oc)F`61%0WFR<RQ^
#dfxfNWQSE<7s3UWe~wLMPFbG4zUQs7htbx%v#ld1Ambd@{qmwHaqbBICQdSC4=s#Ggykmv&2v+-l<?3#%*lj@UCgO{$|VH);&{S
3ELN5M&)5GDpvIvyw(v}A1m$g2_yzysO*i*1;66gBy@DG)Os%MsZA-keHJtMEi$3se|JxH@_Mk@+X6F-YlRTllf|^_|4Qjzqf6sr
mc?U9br_#~feL>=B=p}uEl}3r62%d=ueG7t^18q@1t=+UL=gqiVdG7Y0AFNxq}sKUel<ojM=NmEMbi12@k+&lGO>v3@;*Ag5rvZc
q`>V#OCk!=e21D`gELQ9+!(AXx$aIvU3py*5)6~S3dkP*pW-QkR|t>;3E(C7Wy_^vO^|?;L<nsZRc*%@Zdp9*gS-Y|^;eN>bK&x2
y_UP6(Pr7`1#kY-=p{oozc#On*nmgH+3l*b1K~%n4d{0~<c;&U$JS%9Il(r9)bvtavkw%x7NX&TrF)E*k)}rXa5g%vFDl-m70NZZ
m5b#!EwnxJI~TWZ{p;lMG2{hVDxP_SYoV<t0e;@l#Ss>uOoNxME>bw?u_3E(dU*=ey;|Ovy1?%qH}E)V7Sv&?Q6uo2fo>6oxQ9qP
<h(}%Q13+wZu_P#K*+eU;sGiYQOM3=Crz*7eA8d@+_kqSKi}>Jn>U4{nbXVPtqw<>^7roJbc9K3t~{|DSdDo8XCd6*VRyV%ume9(
x+<zebwaKRPtiFVd?%<@CqsaxGi|0;%hIvBY4|K=G8zW`7w+pxtAcP{Y;&+00=DL3TKgO!r)S+JH*X9OJB7=!288aILft8z!mcwm
b#PYalO`!#H<`d5H9O|N8*5-C*`fB|eU)!<+<}2fcvTHArb~9<&#qoVP6Cw^gC%HdMu_CF0?DP8<_b;MVjnaCII4`hOI;dXFuLAa
&~6~|RZzBhp)HrAR{{^b%Df2b+?}ExRiVBrLrx~UWMTYR`_m+7?rOoNgwhN|NQVFI+@-sPl4FG1j9A_p=f%ej+GvaC_RbW6xM-CO
{#$z~Hzgtgh=+e+!xrK5cUd@JezbEkDzZDSD=s9{#M~A2j(X$}#|}Ljid0jb55#$|S(=-yb(_J4^jASSX-x$nriYCUAPy$dRO0wn
pfcxW1~{TA0=VZWW<_(VnF>Wy|9Q$T7IO4@Tb`M}mtf`mH^${~e9{RuJ0G}vNtD%}HI=i8@Pdod0ZtLc+_kt7>?E_2QT4%~2HtL`
gf>ad^0(;v#uZ+i8+34&`7lZK32#^!TtDk`zECWp25tR<Kmaqgrr;As#iQ;SUBXVZfSLCdWc7#Q+8YG#A$^A*1IErcjs~(R)LItS
4d)`%CGxMQlgXL=@(g@&wF_TtM!}d`cAgMK7IEsjMWl5qP!KsoJv$4ATLM5<K2p4p&pMzvQ`b54gT>DI#{qaREK?8(M;E6fC?6PQ
b`O$w*`<2Bwaf;M3P=p2NZlA^UZHGPN|>a+>ifu<>w^*J#h?$Ry{tf-b-Pwi`K3lt?+k8#Tp_m{-O0|h;s=UFfs%LFPgKv3ol1b5
bAQ^;Rc(uVD`RZbKIM4OcRS<2*oXoEN0s=!NYgZ!!&f&zV$#5`e?apEevuW=uwS=%(XQm=!6iN`$*VQxvzNIZ@-3o*69I$SKUauU
nA1)fi8y9dUs1%G$35o<w*Lqmt_g!PC2<doyybdGL81+RMUbAn0ojU~f6~OQCY2&UFp&i*8xVqY8b%!d&V|qE?av|G4-P72ZSeEV
F7SIrmC=qh;Yx`kV%Wv$9w`NGw_zL-Xpk1ch+7&e;FvS|hwDhs&HwnamCQuC#s8WLJjU>pqubvCiJgCKo5ka4=hyg&r0*|d){Wz?
lZ*YxQ6za<<W0N}?|#Eh5ul5BQzrqBtqCu!=%#X};i$<$GAqge1-BqBb^<9H0?y0ZwKT@dhO7Sb8U*D;S_@w+90YfbYisXUwIIqD
YK*LyN*;APp0OWLc;~6lqb|4P1&Ni)FHSl4p31UtJ>a=v41`=@itqki24<*STQx*vDhr9Vows|Gw`l;-Q=Y$08xcc=>cWhjMt7P7
%f0Sb+^W0-dP#kf9O7kXrsAJ=%@(Y#g7`nPRNVv@uwI=zTkO(mR6qC3dB|r$g6fd^J6(T6pg!wk4o9>vsR0c7Q{sE?vm<YjNKvoM
cHjRO1NuPQzQlwfMXEC_a?d<5?r)>w3-&5Z8aRiSzg0gxISlOSt=Gw6?n3^+38;HR2tzPp5IrlOx%uZ{SwGAm!SSYX%S^2wQxSzG
M$oIIM~yncOhI-W&1}qf3t02kxo0aCuSsPv6*lg^m2lLPgz>)GQ-b!q=$V{?kg{be(`s&b>Y`GIG1_27zV>P+;1&nnIqChk{^$g$
PPL5FPE+mJ!U$p`B>6j1#eO5qhCn&oWm9|;c#~5j*?f^6S2nPee&$w-LALJ1y3`P}d3ZgT#=3IQ!AFW>-I62a$3wOrOH-`oQ^FyP
3I^MJL?Ho!w^}}Vpr)+isbg)Ud+rpUR+|DANQ6}OqPGBLWunmV>MM6=z<|#uj=izRG?tR`jXNE_r(6qT_T&F!Wmm*lDj?u)gJIV*
cPM&F)6LgrmKhKjL~?-lhQ!E=G6X=$ib9osJ6XOm?oIi@ImEvFgv+0Bi+w7UHT{x|6lyKDf_+A4V9v!oMC1p1K>in;=<SNis-4nj
u}udGC4?pq7U)oKY=n9yp&iNi7C%L2^QfP8ha69Bt3rRolMsU@fgW4u#q9G6j82DF(;wk!p}J+%D<vC(2#zIvRII;lmVJf1$Uh7>
PR}6JA|exz@qD~22hkl<;DXe6+S<uPuvQdpy?PR*lngT<E=ugf&dhw0dO*^HrjO4UIFL*eLU6Di{r2RV^*+fNW?@(ZJxSTE!<{0f
R(t5G0~3A50S5SrSfLKhX8SOsW!z}ns&oG7B-8%5a-VypA1Dh!$PSs-3>i!ajaV8LVdkmP^!8H544P+}_=@lp8xy2DXDA<uf<%-l
?!2$-`po6^_tuU&ZH;=0E68kKC#Sz5jC~5|6gQ!M7d`9)Ya%4o#%5X_m7Fi+oE^Lk;+ZbbmfME2j%}Y4$AWMjtyc*9wg8;M<!J?y
xeAHU`D7F-XWo|Fi(nUd-~=&!%GF9(nlwFfS|ZT&fVwx^F<wRo{bqENgE<k_TuQ@unkdKF;h@ptDeX<_YR{^{SvY{^C^k!S?!-UI
kOp+R)-5C^xUF@Tg87prj(48nhS}m)9rN6r1g><?>ZxJ-1M(s*W}hdas+E0;za<y_x@)BMJx)?2>WFHcwhU1_;vThd(nHe@W=~^M
X33x(w&C_^^8W`{{)%($y+{Wmq6+QeEZf<0xu-SAf9|F&Wk@JMj*?3$HPN^WsE0tFp=}sx$BKmiNKR<h!F`-#fy1(CYG-dldOcc#
eyJGuyRLu*cJ0IVzZS?)S1*t^L<0U?Me2~s!)7}o0fHILE_78f^dsd=?r?^UB3iI%M$O7F;PraYW{h5ROKnMyBC01j@1#c(vhffp
l!eiCKtXbybWpZ?a%Z}d6(N_sun^EZKVi6db$iTEu2CIF(60}q#ZP+5IUUy6GqQJHD4Lv)g~ox#ZE~(he4gQlN#uJ!`caFfc01wE
c_7o`&#}xiDvM1TN8o~^J=vX5G1rG22X>3V^m-APwqr?*Lo8ETO{a0*MxWU7%L#||bZ^BGhx;HmPkeb%JV%Sdn&)F8(d>+*Dwnkb
=`pcqCALet7o|PivZ1%qT9klp4MJPEJQO3aC9?{YykhGdKC}0D7iZ~3JUhgrfxsjoTHRTjetT3LA+3O*LGkpBfsgu#<G+~@p2gfv
gWo|~Iujf)qP9Il%0>?x{)(Qw$KL{rXvZ?_xXXU)oBN@^-1|Ezur;9vOvGkt!&GifG-6N;F={rbri-T#bZdqPbL*$NBN*B@hVZza
3)vEZCK2#DwusBxYL>Wz*=1@gL<f>#)M^yF<re#Yk5B9ZrIY4Ml6d`1vC;o`P}iq}74((b1n=KGY>a0YnMWf8339~Of68&!6>qT^
jujsasAIhOCZIoMAYycdsG1N3PWxUxljYLsK8!QLl0GVgJZ8Z3f4*1w!^jjGBZiyMoO(7~RD8ySh?xr2Gk4ak8JN4KDdqfGrLm3y
*N`W3x<$&gx9V2Uz_oy0Z9zxgM_YSQ<>Bu5+U10v?6wJvd-^;Xb)MOTe}_TJjZ#@m{~j0Z!5AH{t}$=#&zb>iC=-NeSTSU8O{7!2
#mHsDAuDNu0x?4BX4fOef>Zm!)D4c1Sm<DG{;aegY|dmfd7xoXdYv=dvOY*z9i;6$90ssZF%kwyz`>k}@nu@le3ql?UM`!U6vQWp
0zOfoS5c|Xw#wyHfT<gkM|=W%$Z53BZyI*9NA+RyFxx?`2ceYoj-R~O6V=_sUWF#+W~<k=__P<j;*Lsh7Jxh(58ffv<iM-FY2N=x
yw7j0C?w*u+w2Rtx1q-ouHvGna~_D*SnFq>_-QeL{os<wfi>V2l#lXs+-aB$VmSMLF+OtO?!@CH*465&17fK6Jeg4sPffPZCMN@k
vty+-;?JPvebIDvQowvhs%<39$tKb}uTzdyoeqiScU0pCPQ@l(^J?~MVsk#u`r8B=U4Up$%_|?wz^lK7OsI`I3SavQj^99LX*hw<
R?{M4qLGy?X6?yNCnYQx_P@#28SD09-OC=Z&I{3Gw1jTOhI`P0j3X!&aV(fYkKNyEtX+6g9V{k`=OBPl78IdD!>z;R&SS*qn}w!c
^lUe}A9UL>;<+*-x!KouriIO?=p2`W36WO6y#hCe(sl)FFS|e8FPg(TJm~63$NmLfb)~A`UQR?<n%4sc)7*M+X{)r9vW;V`as)?I
uMSZfs!?%!ZVr`OxCiPXtVhXzmA}PhmMeex6P0+<hi*|2Op#zhhKd;iw0s7iueD#a0wi#((7i%3RS!5fy9S7Et@0RTqHk)Mxv-rm
KAqkgwxGAvhWDI<Ag-i?x?c*Hn4PPyPLzVce}#kMhdM9(`HibI64IuBN?3JJO*uJ2es4uU?9~weM-;9xD0LeJP`W0`ep)BGfJu_+
psUdEa_1b48N6Vt|LZ$ygt$KAU=P!J8Nlt32f5HAkj49GNm8L`G(6N6zAX1n?`Lo2$+N2RgFNCUp|f--l}MNydqVct=!RXrJLlNI
4V|DOiA7>Zl6+?rt>*%|vE7UhT^(uF5L1`=w!FAC+w8pubxc*ME>`_MD6SfRPhV~s#)q~75(PRPaTMLb@U0|1<V|_-g-HOj>))z)
ji_kRr!>`fj&eOfQ6KjiJ-lBOF(;7pG3Hic9IuB;H@0MY>S4Lwpz7q&85odAp)OV19M5S1rR;mTHnRDwUO03wCrwMPg|iC9za-8=
4|<k9Vi5YFg><<2FN1QaFGAOMZXYrLbOXZdxZ}@zr`>`xN}-lyy!=vC<%8tq96+`f7A*e8+nyEzsu=RwH8iSzMy;KQbsdO-xn5^f
x%(8N9J33WL@zG@-kO7<1h-_U6L`iOzDU#ot6rNJfN@(U(1m|e#axlE`4P-5-15*{Nd#>kCwbxn)Ir9wG=O7&9bPq;r9cjgmthX;
@h*?vqmPT^N#C77gX5O1rCP&CJO&kSDTCi)+q^IFf@z$dA*J#g$?E(xQA%!ECNJXggR<XKFY1tYEu%6Es}@b6NmGI?174G-0{ReZ
+>4)1?oQ^sYyCgl1Fi#u?JqzgK|{^&2G3{3t7xNFRgd-SVB_TOLMOrit|2AK)&$ht)^cO7Ymyx)`jo+*rR;2Ti35-5v8}Ww;a!=k
gX_~z-k*B&Mh7}tbcZObzVI;JKrw$UpDNd{&C-^^OEl`2I<(wx&SCKjpuz)bS=yZ9bc0l;aAnX>r42D$jKvQm3s71`nZrb(@-6uh
+qk<KX36)V3?0EUzp}`x1PKz{s-VOb9(*b_Or920BD!o8TyzZxFtA-k_labC6z#Ju_izbks4`@Cf3+Y78gJNhIh+BQlXv=R4-K(|
4rnTZr{@5oJG1_Mni?S<+2UKUHg`7g9}_O1<r@J|KdY{kz@KU_cF^yR?1`q~;psRGgxkLP#m)oqhs~gBDSt0l0IIaZGU~mTRjW{P
Bxj*v(OWP`%^Z9)83&?Qh+HztFv50|ueGrlb!bY-kBO~8TP0TArH6t+@S)F}x*W@`qjH25P>Zm!2b^*+&)u%xh)YmV+Q$23gA9>X
YXnnRHmo)cOr=@#1BsaJ^|@<BW0&l+=(6ER6V;3YwBGm`d7aGVlNeGlFu|a;4iP4{YA$<5iYiERG-H3b@#mKE3ljCL8oJV6htB}M
5X0B1ANY?V+>~EZu|zvm^K~xE;&09yU6ciNVFayJwHfUd6jnNUdM7cUTlD*Uhwk(*O*n0M?UwknEPhBu9=p&&PkQf^3shF55?nTz
PY;{0bH)+14UV$*UB5_;8A@$22XY(309d7|ttDW~EG;kmt3E3kyZiq{Z43IR?68vvjMDc>1eH>2QJjvl8#&lHVP|4vimPH0af4Qx
Mx4vhv>!MkUm`V1Vh+hXUSCH~L5qijx#0~P4EfIv&<6Z|Pf?Y1Wri!kcL0b&We&whZ&B%A^;~CO8BhEy<L@R8%QWJ|;N|Onx2AL>
?<!O@n<ax{-I@r$uL-k0+|=JU%^JP~x|u}xzx*bJ+Pdfn{c|!~)Q0yDb8|<EV{cWwE0S>ZowK;DNedqo3}T1VzkTZ_eD`o9K*}xb
OLa^%7@4RU?R+kbjRln#B;~-$LZ*0Xk?<Gro4@C6m6wrN=z?$+XAQZtA9vS?=wABGui6)DioHiP97K=T#6q*u!YE_{aIk-Wizm(p
;9({Aiy<a;>sfQiU%89ADO3+fq{rifA#TmgSha&u)wLO<%t%I#VPwZb0Y|vv!2_}lqBBzH-fJUpQ9|2T8<GXa4^(n?gFConwH1=2
--B2L_TC{nsr!sFOn<V2XYNVFu@!{`aD(4$!D?<c6p}ZiS1Uj8{zIuawEU+CWi32tmic5Q43Kl<b=zJnKq3olBG0MF2r4?f$YO3m
*IX0@UaxjsT@#oIog-%^dmv}Sdz`Qkmg?w6e}iHuq)O^DL;x-CUj_&dB1b{jPx(=H!;u>jQf{r?g(N#exr70)onNH+^(=V=K)CCe
_0m-1v~Qx+)LV*w-ok!R*Pr$0gg)5e*z5<@)>gSILr#s?L5(}JL9f#z)SLDS)3h`q`&X~O*&#OJ*Bp{>5N1KdN4nSS@6PC8Sj887
*+CZ`ec>rH&AISzi75kzP0L;Of95_GCmRAKy6@ip_1!b$=WRzutC@Mt(jU5s8P?~DRie5JDMmff!Gz2)@Quk#KB}`IWD4am=}p}U
Gd}4w_KMk}SU9kM9yC*6GhdKsvar?{+O!E>TJBb|{^BM=v;|e}Fd^C}Qu949V35AtG?XoO9s7TJO1H{6PsxeU004t?|9t=dU8$*W
n05VvmtoN?;`mfx0mv*vQhwDEvX@{D<D$S-oG9b4$aB6NYKkK^Ga`r8zq~WP?+WX7PhR&DSVkV=!NXuSC<$5#-A%;UR;fCe=(6=<
C$E+dfjJqF9%OR;HQA|PF=_LZs`!CB+Ct2*4Y|a;9J;xoJtWB9p{_&1D3N|uoWm24s0dQNG}LK!Dr94he1an;{;#Z53FdMl6O%n6
E$ZG6FCooRui3pE#_kyId{Ne^;d6(ZkGiEs%-wzhKFy5i1;xCnG*+YQB?(d>m{lpf_ClWq#Rsr##gX`t+A_c@tw2VXQ-`|#u$W~<
0lZY&nSW0X*NI>HN>hw@xB^9Man+Y-HCe{@>5n&=W4=U95E5ZduVBLAAD6HPI>UZ!UG__P!_BW)Lk{eur6M2^>aT*$iU+Dh1hQX?
828=v%MZWJZJrIk7>vtu|FvcZTS{pS`rd29D3G+?zqhoHWTZO!h{774W_3Aq^ZV40CTAN2SGu8>3qTtTz`SX<70NPbND`XZ3hDn^
FRP@s{ma&ZIen>fTp+2`@_xeg94ia;L9pGhn8OvnAM29!ISQ>Wc@buw&WW$99**UGS9MAw`Gi=H*uxVf8y&v!^OR3)l}kh_gQang
9zBiufR6)+JW!v`2wRC)9H!aJFjpr`Q8%<0+?wQM#{c>)aIZUUb7b^YVC!G^_#DAfS`0Lf%Wsq99<vXd+6B?aLaL+RHIg!}7nl;^
z--jg@_J8XTqE@d^teWG@Ce1$&~7Jzn63_NlC$i+bA3D}{zq6NU|~rl5f6O<i5e$Y_nLJDyP4#>@ohD%(2xs@37(7Loqw0IX?s58
6JMhFU1Sg9{1^(6R7%?hd#l(!=WD>{vL0RX{t@LK?KWDcz>y&fKgcbQS%V!cWKtBpy8wC0d$xx(yRv@3f)M(80Qbd`drA2oYuTb~
*7vTvx=1cz5Kk)p&&l4!PUQUxRO>tKr{LRv3Wf`+U#EJUQ_a7>QM#c^v&y+tPw}>9UEd$54>)wL#MKbGM!{B>QUuHdEYtV^9bWWz
LIWO*ZUP#*qYaqldc^bsz2C8R1I|ucyW>_rLuPb|Z3PXYy<HmW;(E()%zO-d;>-sU*)3>E)(!}p^Q+HQf=O}kmz<v=9tR#Ky&k05
BHtAPIO1k5#2+SeLbr52b<@dhaAVH_ie(J*H0u}5vC{OX>4@TN)szNU!ctugv-(X`0f&xg<Dj{}D!q4m#!t&nvtNi4LGvH}3&D6f
Ot}Fn?PdD3ozn)*6R-^Z%c5h#?3yOP#T7gRX=QQ5Fqt0V?p1X30ej)`Kx7Z+<#n|_IVwxNa=Z(r@kXky%l&7uq~|ypf^5i7D4d;v
AT^<ev5SwvOB|Z+fm>-gbMBdj5ls~K<ci;sq{|)jbUJ!`uTE~wp%UY#hxen>6FeTM8I020a`+zV1<&5<VTktA`?y)jm|Ljg;l2pq
y3r9=1I`Fb7l?(<c>z#Sn~{;cg$_z+3o<`9tacQ<E#B26jNqYq(Hde^&kA2@KiR)pCyG97YSGuRM$COd@RJsY{*5w16?mLoKFe0r
KYM~Q?4537vJ)|EY+;k0)}kwhigv_y684r3(J$94=Tv?yoMw1Tj`xVFRr8^c&ovuN5Ctv*S;?>PTFVR}_PA0fD8x(&H6}5yV|D&E
UNF*-3<xq$ewCbD=NU0=l|^sia<8O(N#ef;NfK*5nxezr=1lj;|IyeLl={C~OLF@|s-)JO@ib&U`VKhYc`41{>W5XJRS&^q0>)t@
z!2R4lo0i8lh8u|t#G!ws5U`lDB9@p@1<L_J@oECWNXR!#Gx>WBu)iVP&?NlkXK`i|L1C6Ol$W!+0@PL%r%bI;EaYep#=~jGL&xR
jS-I}uv3QRlzt3V#Bu${N-fYDd9bDCpCuWW_T5p4C0PpAimJl;D+}TAELLVd4yEK2$G=1z86n$g)@dsGRRi(aWeInvKArfL8jD%1
RvkXa+5$5sNr!*Gt=u9yiv;a0j+Xr%=`l{z-awL72mN8L>Z1AtTg0ga+;d~6lfN&h<$gmlqeDOnzbO23Zl#{E-kZx3rVD)oXL>(1
oBr|hIS9uZpu<(JF-+OO^nZ(<K{7{;(O9q^i&O}>>qVm1>e=H~v?NMCqvH3p0-dHXNk~?SYvQm|x!>Im<dH!>Qya8f7yNFN6}K+8
+W6haVP~#h#=FS@GhKTuPa$rxelo9)fk2&=#pQI>V+O6(&sAztoVfY1#mZ;i9FX5dlCVJxehx)<+fr{JPvF-?xq(J=oDl)8zi_bF
0@OKId_DaFWxf%7Hj@OW5m2HSUNB=*vQe*)rk}zmd)g4gzK0gl4D|{dr&BNqo3^0LYRQH<?qow)2`XqTP@MdvJjK4gZ9j}+Qj}c{
A#7D#+1UtbP0n4#ei~@C01{Bt*|j%V$(Hir)T<`-C(o?c!sARFM}vWz+UYg`bNn||=NJ~eR}%qy`iPOfMi8aeHYpEPhPd#ea1%VF
?xUiC!Z303lTl96NQSafsSQuPKDt09aJf^){`dI7W;ipXsyHRwNi?|lp}(|aB;up|QRaR|xGKn@lznabKzSGMFxlA*T#d*wjTa&Q
%-)Tq$s#KtY)2*$j(YFwf5Rq=yDy5=;USe8IsW<ii9)6S-9_=ErQ=Fzm^OP#K4W!^_8%QY4~9C%UxL7c3(coQ*g|X#BBlyIwdYt5
K|3+<2JZEH@j&L-<h!k@$9^*BAz64Lmyk+6znGeHHhZ>VRdaI;nNh^-7MD!j8ek&fD)paRqjPW@rr4RjdP{xAuCeA13tmG4I$SXL
(fu+M^E)O{#+Xt<eK1Z|s;=pRkWdsZY!chny0%Sdjfk{;(~$H#=5aksgr@%9<@^iwl~);wbpUvpHz8BrwoD{4LeEE7YE=@xZ!Czi
fDe_UF&3VPOgxr0LkSYp4hEMWe7mmTQ|WJ}>~ZTFoSn)J(YQ)XOL`TFy2LFqci?Wr`M6gXn2Nz%c%FVdpSu?49Mzxw@`ZT92>x(b
C1YAdL=-2)wtVA-ldH#rUM!owBRfl_0JS@jh1(X8ilfwYN_|GEJJH}g`98qgAj`i>eE)5_{3Jbbpvl-%I}beF(4+0u`u#Y<MvLZt
%F+OkmU{||ZCDfC!zLkY_4{w;Bz1(6OT*E>zW-q+8WO@C06uq%oE~_VR9dg^c5fY(1|VI*3&BUeWPNu9U~l`bq$_uYHRHa?8U(3E
iyL@w+!Q&+e6B$UK{>Bhd++;Hm4v~!*@SZ5XN|f#lScWNZ;0O6S=ruVI88Nu>$Q(a%g!sGbVIUj5O2HV<U~2=fial@#t;Y16S^qv
-|V3y+Iv_6aDdiT-Fs?<_4#?N0|~(^v!y{>@ny3uTQI}V8sWi}QxQa-jc<nbfjeCwhy^uZ5cc|w|MZNOg(a^xD;<0mgy_=#TDfz^
Vb1Ykm|BdCwGr$orBTouw@tikMo$Dj4_U&p0oF{|aM4q*6-`;58i^3|$3~7)RdpxPd>X&^E_kF^u%On`)c(bjgp4w6NF5D<1we(?
yNZEPGF<4k7A=@QUx=;C&`1{k8FGJ<{%6f8v}sA{xZ~8_&5n#YtJ2EKz4X;KWIrQ7fsqMO;aa!b;AO#EO73OU;GsJ*33*dLwS^yr
sSg?#N7r5ZDW3YA`PyGxUoN3P5$FSV4qnv*%DjOKPf{_3NGWVVMeOa2W)l&NH^UJkTPhB;U!+ez!uuLhD|cUlgT?szDynU<mV@|b
!l0Qg(NOGKEn00&Z}DY<!tU}vMc}DoTz(zI<>R_@K_5F+6M~ocQv(d?6v{KSO^6AxmQi*>+r8%>1kJoAc_Szo_a4&_69u=QaC_=N
z{2gb4E9(~@Zo+HInQ?8+)r==1}1@E!v2(4f3S-`ON}%)0=|4pI1_}<j(O5_^L2sN!G&o0(=h@iar|gL!bS~~Jw)ur%D(RDH9oTu
udKdgIdH~<rg8q<z7etl_#f{9k9FMBbZ;s7<U@P8zN1W945rtD*uVw`pEc<Bi~l>e7?`Y0S1QR6S4`bP+b9~2-t-WB&1&Wyqo26X
Z`5k}B(<w%NB$Xmj$;q>4X6z~nFCid4PV-OQ%M1*BXpzsKC|6+#H+(xn#|k*u(AXDr))tWFBMEb*a_;xmk9ALpQ;5xrYQ!G@uf)L
_h!`4uC15<aRD{qOoHWSu>}Oi0r?4#>X)D}=zcA3aGM?*2-z3}+PpiUa~qbWj+%rTb4c-xAY$^<LITiVCXp>D!b$SoPU=;URDJic
EfES!xN+MiP73p7nA{8hyb^qu=!jQSbu5k^@MxW-n$6kjE0mKwZb)_nKM2oIl|EVT+Q5W~*}wcHA1NY`JP8+jSM<u{&k%W5zSEeL
4K~YvuV8E(s6gN+8*%)oC&T`?JT_4C?eGRgvgbYNf%czZPn!G-u3vbtqVWA6=+lSun|G?_LEy$&SZ8A)BA||ZP#+)xw>G^G_NYb)
>5-%|UQz7#PtzI&#5d2L#&Xj74hOFU>nfz^MVPpEl}<fzfS}<fBWF0r0nbVfCvZz*XGq6ykC>}U;$Lo*5He%k{$WQSViIcgp4^!{
E84o`k>b*(g5n1{&j!CE>An4rVY%j#4*{Ke|9sPdgqH$f)ZJ6Z2{Afi?Qy4kZnmjKo`R-%8^|Pp0b?SnuJLJ{1~F|K_~95eA$lTn
R*-7!cpO_vR(r#ptWZdKzF1bXp_HeLqhUp`L<s>V18jZXV0ihae9Wa~j_kivC02e~Aexu)o^V#zBsuXQ87Agz<3VL|)f)s6W<Fa;
j9{`u^AfLWKd#GDlmbNI#!}-@gMg@RruyP=P-x*kPj>lql{oSO3{u()Dc~i1Q5;4?XPAE!su(}d&9J}EII^+O)p98fvc`@UE#w4m
c7Rb-B27NE<kzN$+sNv>hp(OaM({9I5!rIN9lF&Ysk?RU`kdz)dOGg$kaFqqUL<zglhFXd;Gw79V7Qq~xkQg~xJgm@18Z|gffb0~
s<F^$|M{_b_g^w)e|mfW&kx5XY1rMIfHIJLjQNPT2vLte7MxITi(_57YmDFt7C79ad^{z*;Qys>a)?f{eDrfhW{)3;hX4Dl$xEuv
GcDWSDUU@9RBS9`GTc`PAKaK4k?PO$tq{ho%Zii_2eSw4g=b^Q0JVtM;V`3GZT)-viOG6cV&NSHP{FmZ_vO{L{w%n#)o3`au$dwR
h-UcYl)Qh|x=QvPQ)6&Q@(Yn=+mDLMSi>IePWgg(Yi&!+&n{qq2)rgBv6z^>G$6glp{k^uJI6WuYwnsN;$z&SJLoc{@^s^hn5jlq
UHBlgNG8;u?1f_@fr5uW#!BJVZjXkLs+blf%qMZM?{KrNqfj9M?(XuxS@7I24K6lNfo+mQrr9b@3DQaLFyiqsjz_=%Omf?9LIAp0
oN5LcyCgj$UB<BZ_CPW<UQhR#bLu?k_(ME1PhrFgp4fHzd_&Oiw&n*7!oee6q=|rM59~f|S%W>cnhkdOB{OwhE{=o4<hvlppTr`>
mX$x)cZ0kM^RuXWI2E*zM2nZmNjeX;FjXCVb^N`294@dO_3qgxtJ_9Xi!B#9%iOe+=_suxyzAEa@S<v#=SJr?R))}V;7EgrF6HFe
G6=v)oMiJx#VMKiakZP$hmF0E)~G$RkoKq3-zv~yWRs+?Ke`l9n%Q5`R7(&~QJ2GN9MCc|DN*;t8+S@Q&6ZpR;Tu4=VfW|m_q?WR
jZ>T?SE&YJ*>I+Rb!B<S_-n0rAY|7^yu$5(N>QK<rwWFEN3Uq;X<GsI@vP*J7>>NXVZScUCf;pkNtzJsl|@~sJch9aV)Z&T4Qs>c
B-Gs_%}WohB~#3awexBzfD;%-+_C9J6sP<EMTDr&KW079QM-?UM2Xs?=Rp9Ae>(T~&^09k7q%&}(nS7KKP;OKhSKTaf$7Q}@rx^?
Ok|j$J#I}9el4Q#UbH*Sa8_T4Q@4;Y0F4hln-SgaC+wTqi<5y>+$5^n#CF+qL}Bd9GH6d%z$&?DDY%vg+Qr7gorUpxK1P~b;d+L2
KE=2Te}dlTo||9qBd>{FlDFoa{!oI4%ZR;F9yz0~$2Nt1iNXu-InY#{obMa4bJ;rZ6!9$|*8ny*F?N5E(w2u(^2=G>X-d%+pbJxF
uaYIFqA7c$;l>twgZrxvBRwLcD(8|Ug7$zM@vn5vkH*I7Om7)IPQX;Y-PoOBp`oOdm4TIXY8?X6#hLoC&jLYQRMmH2yJ%%b(jE-x
qhFXuu>kd8=%3t%p?!S19e6U2_f-SYefmji6;zT{5op3CI6g}AAl8VjH7c%b7X7(?KY;w!wZv;ZS&rTtV?3E51ry1_>e%7kI#^;h
eUbN&?IIB7ofq%{R~YZ>gB4<+X|qyY!I0m5Wt#Vr7YHh*IX-a~-WpA3B}^s8P#Nhd_-kLnhnIO=uaWMjJQS+zi#WeO#^jRjrOb`C
9OsWWAcXs`gpdAArs6J<P4i2KZ=BPs`c)q=vK9_ZLf6GwVPz4*I-Y&A89JDlu-+5v^T20zNUUJ3W4I!DwHCIx`~gvU!tgS%*AxgD
0)jVgWU*Q7ib2_gK2cGFN3_YBW@#uvIl~0pv{5<~faLq%gMk~GZBsH<X;&%G5Sr@{WseEaATQ*73;)R%X5urAoTW@SZUzDKrA908
ExU{lTjAi9qOGW=APesz=1z#BJj()?f}Yu-wLH|Zj2)9WPraKsS-Fo%ES8_$8k)y;!lvBWQQO?b8HxVP4{H3bz(e7+kxqjxua=%m
kd5}*r-V`Ztr-?7?Jy4E*Gl2?aN^9A8d{1>f{ek4V;<9Wk*dv6@Y$isfzRckP~g?kbF8RP=i|+Ru)5tMqoo8Pofh9(Hi2r&-EyG<
xvl*xu-iJRU9p+#va|oOCa~WwQX}3DE}U(9*3Ke%G+)09w8OdiNcCBdveOyZKMsT<UA_vRI^tY8>W3`C`p}twLDIKd(*M#qD<7U!
cVWeA5d*o{;`_<s%YKZrb+FYb!E_ZhG|LS5HyyVnQFR_HfUz=<)&o(}5q$2zFdeap46O<2((2@^=Syw)uQLNW$S`N&m>3x<G+Zam
`<G_5LfLSO*X`krujRPrNcaQSM5=5=(^gNYP*tTcbh*B&Zs`gFwc13i3wRS>|I4nkQC>zkDB@E%@Gd;%r>2;m=km!=uHxEmVbtL-
{WH&Jh#a2R)NeL8dpTHt^(=;&-IM=mUO@Q(y+O;U>LRH5UeQabnS)iEC_!fCYOl(=@WB`*7klwJ^GMJ{2(^My1!$p>mRI@WVw6xH
%3{W87#$l|!Wpsb?A4pJIKbR9?*#5;i_qpm;E*_a!S!dlmuSqT#j@D}c29G_^fDvSh6Xv-qd`=68<<JjZDp8I{x6rYkoxaWvXz3I
Bs7<oCN9QB24qCeO9lDL>UglPdANg_rN_l(Y+C5)_lrF#G?8%V^+s0UZ&E2O+bFV-!@^KF0>kLU%}qtqt59C4ifSocb-gH{sUUK=
Y~6+`YLmv#!MqXe3T~|?Pe<w}14S>-e(+{SJ@AMarPU&i^u;1CbXH)A)x3KZP;dD?rG4F1f25QH@@|mm9GPU7dy9a1SXyB00QeCt
%xg)7@M!Vs80eNekmb74IMjvsk`m?stXUn8VJAry&8O=wa+T|_TMXr2O|+zV<;=?Dj_${l(Y0Z~!!IX<Iauu%iDn9Xqhcto_q1OA
@}^`I6|nxVx<s*h>vV?9>I?KEUAijv%I%Yzr-yBOgsqRf*=7mn7yMrtc+NZY=K@&&hSM5FZ`?@Y{Lq3{h3<%vH6iyh(b*oei#Ht_
u8Jmd24czNTd@Z^+deIi!-Mr<q;-yXXwa|jpLB?=sE|cT<PZ(@$TEan83PA<w^=A-rA<3aAi87-^?V<D!;&-fs2gjmbyd401_Kvc
+!%m)StS9Bas9RH;lo<Ne;DpM{7=yg<Qi7(KswlD%B257vkI?T3ld_>(z4j_a(_A6u=|BkvNF}+fEcr}Y3tHL0hVx$_swg#8EFZa
;bx5&1D=u3AI@zc^i_AGLpVvD6JZr;Oo169|Brkijrs{}F!tNa?rsiQ75=31=H3_m-0k!No&`b{HdyJGahtEd2u!X*`~Pg4Ho-wF
JG?>^zi?^5>~Nw*iUwu$Xh%?Iy%&g1=%HTsfpxQGXb$2^{zw%%kWFC`u;E*gfjPrm%Y&X9BlW2|4{i&Iq77Xb-C=CQHf?&gCMDID
Q$m}q=YYpd9`dgI&z)OMsO6BJ(sP#wZ<B;wD}Wrk!!1Z%rP0qH-E#q;o7jXf%G@rA41sJbIX9GMs3reFO(<-^=XcQY43U;GeeE%b
>1B9;Jl*>?FC4^aZ{5aZlStip8D(%tw*4;`JvYbkUNB+n5!#;q{D7I;-o#-U1Q%H2SaTjb#Ixw1PHt$jt&u&TV-m_DhJas(Wqnds
>!un6ymMSqUl;{TBlkgjiF}hFAk-v;87}#?fp6)oA-SOmlb}sVb!hq;I-IS+Cn)r#9@s47V~x0h`-^s!Mq&EBhB#-u;>XJ{s5o)h
23<MUyeBdU00z29sx7Crv38>*UgdN{R7roB*Fg~@UF?!_zGUG8NyrLV_?#-bBF_#dsJB^nj76jUA%wnu4)Zo?`w<!X<a~0(oNO-l
7QUx9?f?ii^SsGLWt8NA>~d!3;mGo$er2l(4%LkL_C~8qngn&>sL7=#qqzJb3E|>l`sqM<TpIkC?vq+<0b2{$%2ZXV5K&Ubw~YzG
h8XFBardmW_e=AAo85!%#xLv6OoI(w|0cfRZU~}wt#n4(F<pY$#WTj<HwelD@#YHOsaVrHY$xsz)9dLT<3}~QuA)pP<y-RZ-`Icm
wU81@9pt)*3N9qYs*wer>=ieDKP9+fRQZ5Dh<m_HK3!vkyuyWG2SOT~$h@_IPCj*ymPUO1irm**01MC43b*8zd;B=R-0zjBdBHQX
mk|Fn;_-~mEW@Ze9!3$;&?DmhQLNvXmeOxI&mlw*#vL4rbTsK$5-o9F8Xoce3xGw@k5;%S&og*(wby*hGsV6Pc}fiG(i*c^KDC*1
s~zirg#ZnB;ad9~KA+XVz2`4D+A6R9??jtz3RdC_sRZ|TY+vES-uryel-Ft=;Asojp%BZ(VbD<*+-cOZ<PNDf>{3;~MRoy1&yD%z
w9`LL6G%n#+~lO#^-TM2%oW&ETu)9tH>c)PPfBIdd|XROK?w}%ams?PS6mY0f#Mg(KeO;^v5<r3jeAv|u+K3uvyqRw9S9#*+AIG(
_rCr;Mufo#_p&$VAkPyVQLnIwQqSLyq6%Qzs+k`1d{uzDpKP4Fc6q_w0(gqyAW36=atCP}PeBt&W39Pl@$UBYV3hR@?GxhRroF9o
yyRnenBM;W{EEZA-e_Jqr}j;<vvxM)RUAR_OG5gGnG0GM#;B7&Dae@=F7<)S7`Ynn?<Z^6dVui7vZb_BlN80%g?}p3iYl~!E0g}r
S=&3Q9R9h~)50%_E0dUY6ha0j6TmHs#nonzb`42Ps^}R5zt(zG-mq+5i=dSt3MVNBW5D-nu)~YGs`3(X&G}Wg+65D`0W&7$4T;bb
%;0+uh{=m}Ef-KcD6CC|RYOPXHcsT)k_Q>q3~AYoPE;;a1@l>C<VEPkyK9!?9*w1khzIMBQ0+yWJ3*%`N1u_CGO~ORNM+Qu!&6Q~
K>o*Y_xGlUUgH)Gyd^<U<uUM*+al-lr$R=s`1s(bWHD1lZ*bN-B4=Jj%P8Ylt5`ruxYzbMJdS5ZzNt>p;1*EuIXc}=-dG3-9_CR1
a7P(Zyd=JTaerj;2enGsXxzhnRueMIrMSY6AgH0tO$c9Q%WDYDFYi>G?r|_f;i%%UqR3mz${%4BbDr4b{l!i{yWwP6^k`dxk)@oQ
C%>0#?ZQt*DmJ+1Cs?_+JgQtcrgizfQ9Z}VP=omhb7v;otUXEiQ~$!F16NN)K!gTD3Dug|DdbbXw_WyCAefl<UEd3*Ql#`Y2e`VR
bM&%KrYBBd?8UWVkKd51T*qMU4;v7I81c54cHWAF5b?pFLdS>XhJyI&H%f0$xUG^*lEx<6L3vgQaz8HAJH3wj(hXeF_Ys^ZY4rT?
SxF1r=X9s91^ufUOuKYh1aKAfR?WczSRg0Y)(^5U<T&U2f}TA1CbznuacxC=VqD?64%^9i46#qBe@2UZ#h%32R+v!JNBl#i-|LeY
@>UcH&F<g}jaNIS^<NWi?kkzv0;sJ2KH2eXhf04pLgT9$_8&wY?T9>X?o5zs|8>chil7oJOzLnIK-bmd$&*~sR+``|AaRjXhsc*$
R9glkB|#J^+J#<hdL*_14scu-R0OV?!RNRKHTXN4ZT49d(y1v6H*(fq8ywC0Xyag<v%z&*I{HX|Vy-hvZ8c;_?JG0#8=60K9(RR0
61;O3h*BA{<FkYFTl=lePJQOhJ`Dd6-0rs!)H4a4xc9oIW_?VV2&aiH(O?+bt>0avf;1=mvX+m#UNOac?jB|?);QiGn_B7?E`s<k
qA7h{Ru+OPjBCkOJ7=rSoU8jZfhe3>PMk~eObp$9?Wi9|eu7a!h04Kvx^k6g!KB_lYeOAn&2<4NcFsEwexY20<~>ShMz!zahvqBv
k*kjxi4m23RFlj>Xu~RwQ}1BI@HiV&oxq+>caK^Ze@8(xIYqgSjb5_ISQl19_`Jrl^ur<#nJ*ev6`{eY0N|ZT3d<{PogV5pptnN&
LnzEyEcQ<#2)I$2$(UvmOk*U;Ph_YbHCYJn#`h>k;_f$#WR$`Z-l>w?Pxdr$(c`!-2(KBKJAeJd=YJf^%OMApEZDSblx=M=7lb;{
fe=f|Mb0MiJMIzC_1S>M66(T`2{t95D47qvLR!6`erL2rb{MDRb^vN$N-s~@&JxlLUYu!8%52`To@I7Le4+LJ5;M*~;Jufi>jc}9
y|J|;pG-3;T9+lSZp;o8`-)49vf;=P<EKiq1%4~ZS-Z-U&F;Lj&@^*hTzCIh8!kPYg=VskI*cgE9S$8PMnSCIuB)*~WJQTE#hH_T
R9#$IRfD9xzj3ODM*JCQa%=q^gQnc(g-lR|8ro-C5J%bxZh=1bffMj>tXYhNO@G)W6KHx^h}gETis@v+Z7B4m(?<M(Dj@=c@%qS(
)FdFLll-t|))ju?2nrt?ykju?)Wg>-I+UNW92Qqwo7Y}je7ZLeDmzu#$1*7cRWb|2kw+i}NGdJ45O$)FQd7yh;34SHT{cG7BMFMv
1m$iSlrG_8ih|N5jynt|2~mX~D8@uz$UJvp=E^tbFHgtOT5dH8Q~@1Ep9jGg6};tuP#)`4KKa9s&*JzAJx-n+(1$c^b|+0^PdHl|
dmMDRZWJ?YFqpYQ%FhP6Vp>P{SKIqniiu^w?BiY?p9y2m)9HAdNINn>QX+`<G-A#Dq^!>$rYT1WZsHp=74pu0`UnP;Mf;XjVuXxO
ozu8=zGikt-ZuKg)Qzo0IYq3HT1FYo&~k6Qa@c3!whQx=+_V0Z7Em>W6{|;0xt(i@B+baK&Jm^1y1qWXjkYs#80PVEVNy>3*BS-X
tr}3?UxZY)iBPR3MHnQdki32d>4qoyvXsAlaF8ih>Lmx^Lbc!*!0z5vre97V@pg@j^l#=8E&aTdszFsDuyIoe0qc8X!wvO}_Yid^
L<`wVhtyc=sYDS%`n;2_OiZN1X<1=v^LYc~|DzmSYvq1Pd5}Umm1FchhjoZ9<Pkw0Tcb?t`Iy-BHHlS5f#^+pStpJk%gI|Jys6MS
a7{!F|7F4-QmmHqRbjFMMA<Hh0!I)7sI(vZ6}GtmRvZTP579fU)zao*ly#}pf$1MaIHd68t!UxZZ^{PsF%KkEYR^OC3>oI%h>6+T
Xb^olo7RZ?v|Ux*1ju7ejJ9vu$4b|NB1;7ik&xDiqAyh_7XMSu>xqfxH-HB@y=&^nGi5ElV_e0LHC_k96CEl>A#9_{s;Tl)-P4k5
zMpi)glj0ZjKe>iPVLwlh(9!XEV^w^pfm34gKFH=_{zaRtk=V>#02P2{$15M>8hy69(U#-aW}RpG7H3Vtr4HVw#eKX-7FJ4A}H$B
tzw_8D!5uz*;HRkQTe%gR53T<N%K0NfZDhMkoh-(>YOVz#_bA|BLnHrtNBoyHzSp7m}e_8%$*Z(K8iy0?pI~lhx4SJ&jeLKaN_w>
FI(YQMJA9-%?^I1=VYR=hoF3Jipr{Tl9sR5IQa2$HHScpKQ)P7Cvq;Paj&2;SpCG|Edj}W!!$^J`{F?U1UBvLU9i&v-~^LHkuYU%
Q&RiwVgeze5A8mco>_dU9BmzE%~X3(n3H|C+9c`*GK9Mg6dt*8WR1W)ugYb#cgYQj`^{n9v(8=^aZB@rZMd=J{VLjrK*!zc5uEr#
*Fk>NiuH-Cr+?tH6rvJc2%J*{hZF8$1%LI2&}27NYK0l5-nt6Z(;m=bWPWppWGh{+VMs`R5nhYc%$eO|KWyX_%H{P9!%Sx_OlBag
Cz+ozvJ^^k+2i~0z32LUN9XSvtl8(9;%V7BCt(C}l7o^(zNR$M^lPBKw3!tEC~0bl=PqiAn17x%f^%!mZF>?`XTe(YEq8%!B)zT8
vMIHb4_Ngo0VBMz6<$FcY0+!%$Z%<4<ln~GT4NvGxohr?<qg0pLE$4CjJ0hk5ez1cTrV2y00U4-XdfoanMTd>7{g!yC9xT4Mbk*9
>DbR}P$Otn6k12f>WZrHD)TgJI+sm7F;>&Ky|sPxu1~hf@v(9o0stVf)9*aEN^~%qJX7Oqj1%li%izBujSMW1gFapvRIxMDcKe1g
uShd4q2v)NVOU(s=F)r+Od&KWZ>RHJLXa$t*aY9786Kf0ATy0mI~W{aNrA@=_!T#B_<sl9U#o)*b~u|fKr3YAPSqE$A-mp13>w)U
e+B(Xk)ej>J0;B*kO*ymLQ%0NK&naU<zAm7QhF;*i_do3zQqo8ow-IpD$g9~kFLt^vq^ivEA}|_(-HAD)#~GLHFF(AnYz)a3ZWG_
>c383`qJSH3el&YD6fABZ6rk_Y7XBvOad>%9+==l5KD@f_LfLhKk7JTvg~BhZvIji<(N9P82pB+wv{lu(umx0J{)I{BZW1#!liIb
u8(YPrJ^;2fG>8=Bk(Q2_CC#Lk{rxId}ak};Q8p7Kcp{c|1eB_6gUg<l{ex7H#I5!1lKspsAyabn0$FQTviSy8m)P>NO<ParcFy#
Jq6@FTpJKs59#keg1tq_F(?l^TF^6PpA?Ro`Nj*`BgFW!z$drm>mU0@ie^la8@j-3V5n=LcAy>r7j?dME%taQ{aZ>gOrUFQ{^LOl
pTv&cTOG27x8V}q0>x(59Jc4WSK3el{*=&Ooc;M7jePWp#>$w~%l(s@kMvNuY%002>NOz}mxDHa?__(<*j;2(B+JlwAq`i{dAujg
AY`ox3cLw81+LxqI;-IV<c)i(q)`)95ViV(YW(=fdLSJm;;!j7k?L5w*V+{$4R0|<t_Tn?OsO<Ks|<74Th7$*QJTFeE(Ar8<*}--
RLi`fB{H&bspz4-V`au|NXVUn((VsGp_w)G5sz6Jq>Jg`*OXsNjCV)=CI>oT<bP8S{nS?qYg(XWFc?vuORZCfCjxbUV#l8P#Rv)K
dCE#n5A#s<lm!{YGQMLTrH_&mr$A;fhtmDV*POsMCKluo>BlVIMAms3lEf<MBoYb<eL@n0XZko}_-N8r*lVp|mCD2(g^F%4^1TEg
VC?i{!LG5DVBRM$qMfVrMDR*zW07pnQs1i{nc!_Ts_9_NLOkLO^_}gY2Zf=f#@%qmL>IN85@VqUHPACnOwD<v3~InPM!E0Gl;9K-
<52G~b<fSE&jTqPOI=UX>_v)PWaVJxxIMQXcH%3e#zo}72y9v${Bn1#y{d2D)(kc{T}v^V+!XQzxBmfTJw?5Y`2E*N$W(QzG>&Xl
UHdVn#uk5f{BpIa-($Xg#Y)FlCA8uRZ(d2LWpe5uLobqV9VeNLh*Og<2*fKl-<=kyQ6I&zI0_w|y<vXd6k`(6R*^ZT$TUe*{Apmn
_Padurt(S|{-VYiY*&wUc!v^(n>5_ngusz2?{ZltH;Kb1+!|}Jtfy07KmLok;CN@R2_;{~$q{^pK_4?YmzaOwrR8#`W|DgDGETA1
j+3x*(9U$OZh-$MKN|^np6?odyc)vmIzH57NVE2ZXKWpidQkIU>v`)gX+Fx-&LmnH4HA8tx+b*2o+)-<Zy;4Qh9hv2U}}8T2jMC*
f}#wAhO*I7Fmn-8p`E*}$tHXc&p>$R1NpYM1@fd%!&+O%+Mk2SG!H1Jw;hjN{bnO4wrj!KbKI<%M<Gwhp}_g5cWRNE(U7msDKCh$
a+1UJ|3T9C=eK(~!EXmX4({hb(u!bvZ#h1RX4cEJB*6fuskA%<q@aw**4ek6gng2Y>UKpz3-mGcB<xsWIEiR<VT*$XtJg+6!W&Qa
9RWk)6(dYh0fMv*x9jdjN8sm=%3<V84p!-}amhrxS|L*LUDa{yVJ<RTF13H%*sXbpt$8KO3>2j@Qdqe4<zp?8kqRxjjmli|>dZ(g
-l@2k81Uw>T{IJIiBONY2tL7-s(^U}QxXqs^{?8PDISGSgTD6GcTSoox3Iv2*KdsWP#M;!&=|1+noWJRF{DEonY|K@B;mcPPjLaE
omBjM8LHy^HeUjz;OE1p4zwTaauczW47{$O|0m(wMXwti?2RP_lzUBT+t<x4^$UXL6pcQpzG{Eb3!;{&j>kr&cAhGQj8b0|iNp|q
J2Q~*Jp9qw&tDs9W5%F@62ENjZO|}yT0Sa83t~ob{$@)B@?=q|Kqh_utDV=$__-37zrNpV#Enr9&0-vp@5pN=y#A_Nrbd1sto{hl
BPt~}sK|DU-8^ZCw7$c`09O=f8<Tjwb^czG`2d#Ge4pP4Fcj0WsWy$+KsrwZAX04AW&P>X0UOVlt`Doq9*|&rj6jvX#Z^TgjcB%d
93ZfaD7Zs8f&-}CMju}+P^}b~x$-DRVt7huJ^1TSP`Iv2@7elHLhMA0eg)406d0?Tu&{STWMcCENBzmG*loz3O*n%MwqIr=6F>6q
x%SupN%2{@t(F*y4H44&q#Z{B0Dke+iFjsr$>H_BS@LK|N;I^viQ3?us~P6-Pf4uPhzL-GjYXdB?!5Y&u=<Lqc)r!x<t?RyFMmN4
RT|7fn`pSBDtgWhe1v&XhU{^PMG@N;Kmn+GRQZpKZzGNHudO`P(7Rxt$Ed+@(agU&BYhhMlNM5^mU-0y`@nxS10cjW9<qFX=pMV=
(gh&i9H%Y;td+~6SaudwuKbaW4Sa+X9{vj95iU)W`j&&9IHq<x+`}z%ynJ|zps{Cr;s>tU`eC$n<xcX!EGyrM;OKvp=CND?^H$X|
!x&Ak5X|YIX)Y0Xf6m1!cqc^d;_0mekzhRD$tjpc-e{aTlSuZhJMN1VvG({F6oZ|_(0_-TdNP62`)U7HkFt-@VZ1FfaI~zxW{F-4
I{{&<H+jKPt<WNt%S7II1u-JnP-A>pW*}U9r;B-iS!S2xpk&1ysW-_I^&Mpb7`^{WOpgcVi<giJy)c0zW19&8M0kCn_6}{~eG)`2
<PP1@{t~gXSYzpc{6zIe4t5HKF(S5BzxeY-7ws0%BHpYQn(`+TQ;~a<NQh4*-Ko7didcrBflntr0w6w?UNJKvS$4J?br7bh*A#x~
Pgz#{U%J5?O7oWazQ+4v&%8=LgeGoj3nAoUZ+ujF(Se4bA^d$uMm(9ege>~2GnFxjyHO(5IpXkGPQ{8-H9(~ZNTu2vJqT96(u2Ze
sd$#no<fYZpZ!Ofl6|HHFJfXKV4EXd{@mv?uy2)n96c&03qgM}`tZ(wri`4eYd$x+F{cxQdEKW~UyC(6LX;+kV)1trh@|N_F5>(_
;XD4Caa_}B%TChC;^n`htdDXoCIGc2Fq`7*fknq2#~{T6f_CHwK=-pA=%mpwY8Bpltu58Th->}<qZ+3{4NcLvz`7M=R9+|P5w1lB
Y`KRxolO19ZX~_{bwD~^dznrjL>f#8l%HVqKY`2;w`wQ)t2KEHeJsNLl)w8ku^?9}BFdJDOaDmic(#d2iImA6hebbphr<O(n$%)M
w_bxGn$tVR--Y6%A5<?J2sFr;83e1KUF&+-hc#`^5o<E)oJzIXDPEWk2M!h!%R1(`-=Vc*cPt8keYSHi(QD1l7yDt&AU3{)7ZU>4
M#1JV@0t6$JL5Q>T3gd)0-rJL?pe|)J|SlSg;Hj6Y9GS5u_Hk~O-#Nr0fE8K9^?oRM3;>#&UY5Xj0Iijx50O=FPYVZ^1>Jn<j>kE
C^D0aT(9cwA?>4Mp!8!=iRCs`XK>EU6+%$1dmIl)-jCsfZfh0|+U>@c+wTqRrzRi@O~l`_SM5E1+`?u7SL-#4<QFmrXD<~@zz%o;
A%ep?0?19#1F1JI2qqEqi^fBerwJ+!pO5!kid_CY`SZg|>}q-oi7|0iT^)Th#+b;dqB5?RiNa-!N{?bUq#$GE79o}+<PH#Cvt``>
AXjHzk6I(r32ZCTOo?G`Gs%q7LKHJRvrKg>gpHcKEgH91fzc{ebWEV9z#ecwfoFM`Ejw791gV{R181_%*?e`ecFbXSnKrBHy7F`u
#yBgdZj@&P2|h&@YS`(aEa)HK^=<&aJ$x%*9~&;~PjSSOvRioH8wR3rWJ|30Ut-vB0p)y~a_~|88|EjEY~$8iCpm%MqwJk1ks^Xp
T<z|<p6o14O1-SA*u^*~Gt~nn7XWJO*!s6vm{0)cjY_kch8Y(wyg?+>)<F!MbyGP+%V&;dGb20!=#7D9*8{HwovWq`e3V$b&#q7P
IYrAsd%QQyiHDS4?i&<gxBEWSwk0Qs6{6V>8M)iWjF4}fANgW7<y>H_8v!OwRLkJu2%0y{rh~~sXK3>J128z59!D(b=VxUzq7Yb{
a+h!^wT^pv_NK_Yb+tIr<A%|b6s)NPXt0QnLVie&!wU4v1jDJWu$hmA&n!%4H?OtG@>!}u{c)`+rWvZ{^aeM2bcnA6q1|e`J0oAs
_&!Cu`7R=8QZq!$GE~Y)$ckurK$E`9Cl#|<_h!#RNwV80H~*PNR>t;{t}*k-I%P@8u>@gj`#{`bxNJV4$FMa@_4jwi+*FNc$Jmui
R$N6Df-{nHc5kA*dZ5=VJnZP~Ta%>hvm~|F?%{NIF+$boVjkE{y>H*DC4SuzKvgFiyE}+@a*A*Aw53Es_4AI3&cy_tbO#aUm*j#s
glx5*8TT<-C@sMZ%3Ng7zx{J|lW<a30YAxXbUNHl<$J<0ja^k!!h*HDqpii<Teb)8!Dmy$QfxdV1j|)fDp#8st6U!x{^F#XS*#P$
QDxCDULL*L`2lv|UA7fw)OZ0CWgJb9$o?nEFO@r``%wC)LOxq9Sr81$w^7;maPcvm`T=aMA+uwr-gAJ|rlBfb{#X0{Oe#1I50<N)
Jq{%JQkOkmvt=+rPX#%hr>t%-Bp)EsqZQZS_UtIraM1Il8@+q^iZS`n6B%r#w!Wh-i&S2nqdSbk+GeZzw&UNt4NuP#N!`PV?!8x3
XfW>HdahhxOQ(4-p#RS(L6jMiQXMnO+VqhBpHfBKMS>N3!>cw#8p87RJ!oOL<~coXMw2y(1ltTbJCh^j;Eg~~aZI-MtNE5o7J8s`
D{fyoZUbVJkhPB7)OX!i9Q6?w9}-v`ZgY$FVm?&(!geXW_HBUW9em0&Y+NJgLI!_G3$+Igv~x&ErL#>gYj)@F2pJt_xA;NZy}W~j
Fa0_;xn}&(n8@_UsSJz9yYVs)BH-RcKWK6C$$j6ge%Il!IGxLY0*44%TPaR2mMr)aW})aAN|rqzV~o)8qj0T4rbBG5>!@SXxB4fB
Ii{YfVEQR#fuw5*v4^YY8`@@N`jVH3BL-*+q;fyU^$*oto77$eZp{!rs_>c4Q{}Y@r#4*1n)xP1?8ERZpEa_rD|x9!TX{NWnd2JD
%j6~y=@70{5`Jn*(;eL_km6JBlq$;xVxGXMoPhrvBE>%5OW}K$b2)GHG9d<7Xd%odC6si_$KB^`N6G<J7{wGv0MQ8qX*8*E*6DNP
Z^%Cy?Z9vs&iX4CpKbF`QOtCxpB;j4N+NKqXp)E9*-^ULFSHI|j&<`DTpS#_bebE|t|k`Wr~sQ0Pcv-NHN25*;=IF-=DBihVFv+-
^`T5UV{=`%4?p&i(Ra1~%({{e%(ZuFa?lc3g5=d~9v|c}VS-%rN85G}#&rL>mt)I}j7M$vM|A1_4vEpAPD}qdQe5ykQ7L|=xd(X7
>duJ<S)Oh^B<Fj8QXT~$F<9aff=X9;Es<b=tZIh>_11_N`RJVSyws$e2xN}X7Lm4hE}n0bSw(yNBG7Hh;3z9!l)zPeILFewI`iET
c=C_mF2oq<O6IjRQsT=iLRKo*$LU)<a+zr`@-5cAH>B_1u%y7liTp?NgToAHQ)_+4TOSCRt(vJnULRk13tTIO3UtL`nalz(hu>jW
%oPyr>U%v`iktK9IesiiBzPu8er_ek07H%&*@453i|YiL=vV8OA&rlB#qu9M#hicv<Bkc}PxVfYbCxi|R@>zRSqbfnxLQe`7H7V)
1p`ooTk6r*sbYdx;8`KefwhsyZ$g_F@k2}6Cf-c6`Q0NGv9<`TzGsC5)mD#yl!40w4@0YMw_H^MRj+R4Q8~!cYO^f+`D2$!+Q;+F
K)QxXt4n`x<?M$mXL1qL*|o!7NjuuO%+1LcP?lAO+o8yHc;s)tIeME?RLa<28zY1eZXGx}=AN4tEJgUiIs!>t5K&mMT}>YHc+5|4
;M1XspTSu?k=7vY!6C6%e1F6I0axCRV?UPBukEz2s*OsGsLMeI5*Bf_aex$Djw;i38dg6mNi^<Jl~*HO*G9M-Q+Db7yp>&-on1Y?
KFGjgt+)kYnk;D24SEr(LHF;EXkE{KZH?TV?hxX!Ps6l$L73}pug*W`Ep1xn*Ca()TN|6QMkyA;JGb@4`|EZxm>aTXmPRtp_Le@f
FpV-mpXuie3&{EJ>=-o7@3nDnK)97bYl;oWrjzsqMg;1~T(_8?APx(W8c$h+@B=X}GqD_WB23E{^ByN6@Z^k>`*)&M8V38PLkBFA
*YwRhBar(flVWnm8LvUrj6K+x&e2DY%gdUX6hyP`1Rp4%jHb#tLfzkB?`E?6sq0NNX<=_*ShU*N<h)J&NO0~g@X+C419!mtE9ekn
qWoUzm+faUyoUXovf-CdIBf{Ffd5mJ@X%d)l>lKHjx+4=?GEJRt%=BPN(25q59tVIQ<}f>P1vC7pr%xhp}CruxPh$FG{PdVvBc*f
gw)t_2`4q4E5}OkRamH_3st%OwLk{zLu_`DGHR&oa_Jl?Bb)UU@&v+}UbqM&mViWI=Ki3p@jDl9Q9x=`eDz_vj$Gv1qcjuYvA3mL
uT?Wk%Y`7lC=0eJ)Yl)ZRBe8VP|qbn%K=*8*T)n@DBL9QHsq#)@dK|6p1SC97hmz5r?2!ii1*{=!ylMu-l3Iavf*tY;IgB;z-aHe
gOj6G8vki(0SD1QI4<RUu$#X`H&B#CNnX{*q-rW{Dy`KE{!9Yn&UEKnMd}GQjv$+IC0Ac=#Ae6Q^Y#!cfZI3EK7u>o0<}_V_wQQc
jYt$xu;fBIyas<l`IkfUqstV1aQ?NX_d)*v{{-eRi+H1SHfOy$2IIoVWVmiuGu^WA3n%JdK&`Tljg-5r(?+nv<nsQ61>hkm>8ASw
ua>|Yrl{TQy1j#Hn$@xs9;+}(dGZs*ny-FIJ%BSN9pIGKC^iYMk8|ZUND_{z{zvVJ{QhL>e*h--J9z1Za)<m`Y1R+<78w>_dA*<l
z8aI1s`9PN&~nK%MO~TgF|DX}JJP$|xXFQwVg;00FSOXD>(#ig&|Cn(QE%u$b?g2h%8~;^2<|#vXN4IEcrMq%8Z#D%3ss?195w_w
P1nX1<%PGf_LbsrFL34~e|)q?!xFZcB6L~%@M{>!yrvM*zDG<vtz=b3Q53QZXPV>Rly(PZsPrDauviV58!dYY)#y*!r+A~Qc5z{F
^whjGsOS=sJ|KQFXHz1kRiM?U1i^FH6Ra2G5OJ0p{i=&m9BU+7Rrz9fhdG~{`R*rE%j_0=00000$r&CO@gci_00EV(1-iKw?h5S%
vBYQl0ssI200dcD
"""


# Images « Toasty » de l'economiseur (option du constructeur : « Aurelien - Toasty » + 2 autres portraits), deja converties par
# tools/pack_toasty.py depuis jukebox_rom/art/toasty_frame*.png (dessins fournis par Nicolas).  Portraits de personnes reelles :
# (c) leurs auteurs (Aurelien / Bouz pour le premier), tous droits reserves, PAS sous licence MIT (NOTICE.md, art/RIGHTS.txt).
JB_TOASTY_B85 = """
{Wp48S^xk9=GL@E0stWa8~^|S5YJf5;4XR^(_H`ogj2uB&180W$wa3h<BW_EMoD86t>u#3;6gEeK=Zt!K6_68V#FuDmzt~MTM{Pd
h}Z5VFjsfh&;mM>Wl0(B7;eH@xOB6)hZ+x^D?abRa+@~OjXjz*`rwM4L||d+hqC7LG4{b#J+NC=)2Jab_?xs0xjKnHF3URU)`g?0
1!Ft5BcTBNnBx~N^j}j_Cr~8;;#3VGzz-qbus3P|iy}o3kw!#`X@7Q$u3iKZFYMM{j4SNIT5hFY%+<gD5Q!?Z5~p!@GFCj{PR;Ne
xHR;YpSj%~x7nHR{sLK!oNE7D0@6yraSWvMHJx|Yl7Qo>Wr9`dGGTJXdunk0Zp`@zxEyLa^(k7qprNoISp3Z|zp)5{8BF?@O;S9b
WzoI}ARXgBvdMQ(a+BY)Pi_5B`B`-eg9zH3aTa+Vm&L?RZ57BswwtIGlm04xn?g9vvM1jRLODz-<JQV3YLqF_YIgUypDtwA2pYu=
1u@*~m%dg`McL*j#^bwsQA|%F^f7iQHbJRcJfPgpBri+rn%124d6gYl7~@L|OqCdw$;n7<+M)K}$lXM^RK#6?b+Ha@g(fbT{t?e-
J>uK*xIoolBNW<_-hfng%CL}ZI76ZSjQu~yO?%+>;@J>E_f4I+SD#gzieiS|jp8>L{L8#s#Z`hGi>nU96Y%|RlPBhlYT*5v*}iT-
LJvw_AQ_+}ZzHL0Wma@JEE<$z{@`{$Y^8!V-<_?BHHfx{%#fequCqzclw7t*EWpVUnB)2LJJ7R%MwpF@dH7X!9QhBYF$V4~b4-J3
7hfv3pQmS*6_pbh$QncNeX2sSy~J)LRnbpW%&`7Uu8nZOkVlY70!Tb{{s&seBY8a8NA`*i1u|ThiKdX<bGX64Ig-)%vooA_H_z`p
X9Ml6o4<5X?7s6wxb;)uOU>}sy1(jAL`mwQ){hrRSODap8|aHRfuLYX+M)^Md0%p^7G98+sL=*M9)#-6L=<b-bbZfzFoWWBCrb*L
KsBenx;QX)Y<AfBr4LPU7xq&AEBefu!qCi?TTVb)ve^cny`b0Lm$VE2G_CR;M6BLYCE{DY<@zRWmm4WejLRXI+F4WN?5>mT$me!l
n`~bNUO!z&O@}5cSM(iNhlPYif8y)P@W^v26gl%Za__v2Pf1GavM%nkr@$;z-@G5v9Ik5DA8_NEt;+-I@>OBjOUTXzdfwkm>5^_x
Sf3Mc%r&SwjF#~WljMt)qgdGy&M=zO`l@G=$QE$;5S5pp(?T#Q^@9Vq(W>NC+_0}_@c}I_FI}5ebLq|Nz_7WmRpXR8PTt?oJSDxz
e}7^)=EoP5Hn?b}d7G&IkkodxyiMK$2-7uowuOHau&sZ<vvKrTqC7mf>|Z`-mFb&ANaDEb2ML{#<UO0@2u>=Ojai|1#(>z(q+5f+
8hgZHte`V8nz;X~yq$%%ScjE2w@*1zWRsV7Wq3DH$ZEKIFu-de``vehO9R)IZ(&Y@ZTRaOE4q}-7^WIKHdHj=e36tl??M(L4dX?H
deJ8!I^W;z{cLvJ=5ML`t@!g@^7tR$N2rNp&LDWZLs~Z{0PXzR4TtA%K!Ti`-Lox5=TGU&x8qYUQj#FB|AuEZHTb{y5aeJ}YhfM|
Sp}A?KU<UP>hykly5`@;BHwDU(47mteRvq>MEZu-;sx46fa*$0W=P!C2KPo(HJ5lH`L^MrmNn??$Y2h+U)S!2Cd%41;OVQ^mI4kK
dckcx0Y&5>eKj@2YOTyxk}W*I)S}I|tUFN}0x9XGx0<6_MWTlpZASxSgjP}DuQD8=g1+4Ncb^o@S4?8qI~x#5My%5dfW}FpLT4=7
bx<<juurCyu{Yucj<iCWHb^9T#zE9(MBaK)%IEJ~kU|oV3u3`_S#1n}kcGF7s&@*8N(oHj0&8s=bh!i;ZPIoP5iP@55>pSG&OMKO
GBV082aDPhyl1B9fkkIuHhz&D&n;YKzk9%JIxw8HEczSUNc-x{v_sG^H0q90x#X^eLM%|ea)jo4pdA%HsurY(^V2>*j|{ua{=b&t
{RgbwG`iHtLPzKqo-S8Br=cowfTPq5P!D1*?~A8_T^K*6hA~+Vu?BpRjH2eVqx}CC4$z7QT-}d>Ezn@Apqc;{S+9d(=pqi#a6}HI
6d&-0Omsx&qk2ruE4jAeB(CYJDc-Q5(O$q!yn{;TxagJR?*<9PMnHsq-V8n<g<D8d)WisqLx^Kv8;L`@EX|M&<f9>a;1mvrz8MwV
?3am=l+8s4@*(pf>J;?c3BOR$7|@8%qc&C8g%G<Y&uJ{wSD?4CQ8zOyNo>DxX67(MITR9hrEY#|SB;<_a5UYS^1eHFMgD#Op~!yL
t&^*SYozlI>X@hYOeRM}D~0@!#<;uFFt~48>v&d%61rk8Kv7So^TzTnffxFf6W01vrs^ZkIs22X1D?sBBAv3A7ZAllbFiFyX48bs
wCglI8N`!9P}5!2PXjb}<`Q*wW{cl+CBQ)7gngaG^h0reSF5=5n%W<xuBiS3>A{&a%h-}6f}yZMZrTZ`VAf?#>(ZgLZ%hR>blLW1
j~NL+@3wuI)I3dXq|(Wvi=<#c)Aq&w**{3b28?Z;KMzp`HC15#RCBOyxv(87GVREEL3USJ+U_uug;O-9CG2S{y3nibL(%?HFm9wh
)iXvY7CU6;T6PC>47qe*`E^c@NsG$}5NcOY!NDujw)7Yc2}VUY`kQ}^P&crBjEr+@Yj}IH7!B&SNOue?a;6yz^R<X8t~`EZ_l49h
P9H@K*rD*81#?=GlPb8d9!zY)R<t%Dr2W1~fe$`Hzi5mU;K;NZ?P(WzMXzQWFxPP=aTU2a+wuP{gtcd&>`<SwBTW&=Jrbt`24J4;
!{}db5&xrt*=Pq1j^A3t)~-Y!2soc!#~edEq?@84S$?aA!8zIMvV5je1{~jpXNafJhlS{_gO!TY?WbE2PF^z)Q9chD5Vu1#$*uYE
Z}?mkhU9{&?oP-kDE#+`7%_G2!_Ne@Qbo(OSP#Q^xwb^@pdWt<f4)8;mVr)RYvOkWE>8+r{T%N=pG9_>M~7`R>}Pw-|N4ABnqA<S
Yv>zeSitZp`cze9-OMV7nDk63lCcuf|EvaMLe5A5+mA^*I5x^wJ;l!saAEf}WBT4{j6l%e|6HHRzT*XjgHWst%#y4jeq%4pj|O{*
FJ!I(t{xB*V0Yq|3OG(hUy8WtVt$q9Ys*Yy1&|y1n$14<y;y*WV8$5qH;NsK`7Y~15O~51<BfO&=IbaTg`8mCxK4IabBZs%>#!&G
ntdyHGYxE@5xB!(!jWrSm@2dHiN6s9?52HFs`ELtLo%Yri4hX;`bbt^Att|p@|$pcg`$*6m6B!fb#py8^xh<Yz|uwn<($w{=^~*Q
6tsMk4*d6Y7>lX?I~2n}EaGC0B7Q$6i^amDAu+c&OHP~`9+f(frMwcweVi13#!Mw#Mx;G^qgy*qkD;u#jzyF9GaGW*k*N|e{wN#X
`*I5I&)j_M$tKK*Rae{tSoy#gx^k4UM;B=`OC-o)qopR}_}8DNWFhd|`w<rmCHra@e&Y5)1$ORzNj(!Y4M5=$DHHKqi41Drt)0~P
H^^Dk5;YzQZET!sx~6p)&+@lS?R>~!iYLwJBE2T5-T@cID`OTRhiFp^DHIK#POp<OtP@Fi5LD1j3ig9gxB_=IJJNY1K(zaIvJq(@
899IWLVe*4ah~zeF)L}ncR<lL*)o?0)sG{WU>MGk`Jii`Ru)Z+r91t%xQv3_E0v6uL)@i4+ixk;axl|ODfC2HV##Pl`CR%eu}l+`
h(N=pHRUHZfWp?%c#P+?VY(V01(qwYRBgN}-aDU$i{Pto<UscMu<YLd06ZMeQQ%Srz>PUiwCP^Z@ZFT^7U%dwfaY0uS=L1za+C>E
<B8AJP?Ys~;=i)zF0IwISrssdd^;$fW;^2DB-GIvdkUw_8NpHKuIYfhw7sDZ<!>aQ|A*3nV%EZslraEI9|y3l+hU=SqWw19q$d$4
-}zfsw&qD1%kV^%A>qR?q)*M&9}KgW#@>;L1>WgSLdxf1g^<}0Ba<0(5i$5pD57xQ|C*A$R25Ou!HQJ2;X=0+A>JkP=h%Y1O%(;T
^j<ic<#P}wq?{|bz63~koXe)e;xAB$cDs=<)g5a8D|)Y5y(H0z1c#IkK3=$}{~<dbjlUujxQRiomxR?wa6T7Tg95<GE`sk%4YO@<
jZ5^ZPTZuhJUH$zfVF_QQ2MmeXa2<;VF%_&@5j1}$&8|UAfor<?x=D@?YO#xRi=|E`z-VrXOaAwrLpX>DG_4+z`hN4gv4~oa2;Xa
g|%1MRirvc848;52v15B$i4x?I;&#XeSxg?NyfJX8_-}Vvo;f;eeov<$luZ5UWlW{bq6IJ9wf&=MtrHnQ>#LJYqN=;Ckv;D2}%I<
-l$f|`so}gji8zSk;fa{XcDc9Q+(t_=ZERiX&1W}(ZjYq*44ap9ebOEdck#q{xBt6vPUF$Rk(i;!Lj}#7rCCr;{D71Fux+HMtmFQ
2TR^V`ZSxK6ahL<hCwGIDF(l&y5ONsDAb?(;`ZQy5!k%oDk>&3XyO6z_^_<Z$+;|tN%-or9DaJLw&}E}a=%CMi7B*$WV-LpuGuZH
qhd(ZNi#F<WYSf!Fy-J=m^!A3zJ`Wcb7E|_9JY*=vAv$pxgED;_5?{$MlY(rckfBf_^NugkkG9gL*##MVK)?vqocR~Hz2S{0OCGU
bjXRTLq1<H&8Q)w`(YB)pW)c4_+1)R6x~DCo%%RavUSUMo8tEXzzmcqM%|rPxFb#tJQmw4EQaQ|V}k*3vO%$M{;^<?>V>&@$tkxT
DbFZXS!SkIkpBUM&tQ^<e&Yjz(J_HCk@hW+8+ZEHPN)=y;W2^7Msvq0Yc+o(qmmo5JM)1}Fk9_i+*b6ta($Q)+~9AmsO(FKk*VBN
a;DrnNozt<v^U1Lir{W;2+r%$3zZ+eBzs<qdtW?$bfNo!l*7?aYT4H3N#%$%Cpzxyb$bFvApGwjf@zkP`#An1THK#{dSK$e`!>Y|
6425|9z$#>kJdZ23xNaq#GFr+OluA+PfAqtTG8*UQmAhKL9`7p9Y|tk|3cSXNq5=|r{$T=4(UTy>ZoBdCf^v*XfA6X=8-<v5_e}r
0`=LAEgQue;!5i@rifA@KJ6wtzl+1ECoO|uH#boLaS;DCgpIOn=*Ld<fz0E1K>P-&2hQ(Rma$p12iJ&sfp&WXY+L|l;Bu0F6!l}-
N&tg4e9v#BgsM^1oP7bH)mGp0OLD2MkAmztS&Ux_p5UZ1hG+>{V}~R@#rWhtYe9n&m#I-cpNY8f;%PoTQTwI5jz5T%B@ZX&=gCnQ
baBWOufPeh`$<*4%SbRsvU>}-Ix@BZ;MuABtH87(;VVTHf*aFJnZg5`sS`d)J!ZG0rj@Uhmv05luh6F)8om%0Ob7Eue&j5UFQ<_g
oJTAU2#|5_K?ej$!2F|luRE%Ioon1wHIRM|f{t^<Zi>cd1%Uud<SV<12AFQX<9S&0cfk8A?k>Ak4sD)wxmykgwPN&<UPSG}Lx%?R
h&(=T|A2t{LDB$N17%&b+P-6m2_AVz(PzOF_eJf9U|wZNbb^Flf*yFJSZy{aFQV-hX(8{T2ZGV%DFM)Kd)@8=-tyh`hIK_3>|X37
lYnQ-N1O>x`I~`%vO&cgH$op15kI8yUHdq-A|U<a+z}Yn7e$g^3!1`djr3%~2|9qJwL^HkmZDz5|A+WZC6q`qI)Z!nw}}V4h;R2}
m)Xy(D<&wH`4<h)OBz=iiiVE>bSA0^TNc9o@K@8>NE5{1)ckG(J%HONQ8!ybrB`3>FJ$aS^_?@WN$O;Zulk;B!(?;Y?X#_b#)Z`B
(eMES)3!z-z>0u6)L$hVy@;wXp@aZw7xj<U?SKdkgI$v6C?VV2&6`X&93qBj`@LL!yrquD036KJt_G!cTzkV!g@k$GPVdRm?bZUr
G`4nzk#r{^9ZE2O5^v0A7y_nxCf&5jk4;b;1bj{JbLzJ5a2VdwgzM65kMn0(Q_R)xUVc=U^t7vH_o2{Gu-+?M1!8jz>D$V+!3LZ{
O-O^v#sG6I3H)mu%Pa(es=_=R+`+orP-;g0mj)VnuRuWwQnhX4sD`vUY<J0}@biN>>b0hC&~8Q4bv)!s1v-^S5;>7<nE&YGBfpd_
>7*i;CT%pct8ZK{V#hXnwM#=0Kgq$l`~n@c_7Gt-9B7lUqig%C!cB_%XS*hIy0_Z~ikn&PbzW+iy7<$Q<ub*Msi5|N9bR+R2)I@1
UdKgrYcxO)yQ94E;lw=kb=M9N4>)v~1*qG=oYut+49&QD1($i_8%_KZS;r6$KB5Om%wyxeyj;csZZdC4X<{ISz4DE;nUlGyDB)y)
oF#Kg+YO~H$35BjZ-ID~A{6%FEYd)#<fB$Vz2hxKg^IqCBljI2^y@#26hB<57dZ)?jW0i=_FZFkc^RGh(XwJucAOO4dbM>h4lpDv
njSVMmHtv_|9BR+-gP<UunP?~s`2=8Gsi;zkd{r0ZHD65ofIr7to0gYmN`#SO<;dvIkvlK3g`-6LB{eC7dGB`vyAqp78o=eIt{u?
Y8azwh3^nG#h#I!Tzyidk4rEUj+&YpG^?f=#i^OnGB$=LH09U+Wmb|arg0E^FfqO3Gy{2|y%KTFf@YLL{`o|9{TU^;Kf@e6@Tc9!
@=GjK7Z<Ahp2y91!|`nT#ej>K>T55yj7Mv?>p_rKHP=IanFmKbpHO)nDHTep^7PjHg`+<jd0asXv0w&^?EtStxj4`cej?^Id~u*7
(@T(idC0lqtF>xDTbu2xS6ETqNO<TAn}k+o&gkkLD*TY$LO3(Kf2*t;-siJ(;1FttLF`cstRchCtENOv#h!0?JlbRQz6P`oc{_jB
jWv;JRTs6QL9%<u_R0)#ck(m+SqK2&YzMjWHYx%VWBFmE1JsTC=P2VTD;4XNm={w)mSG>m>>MphL12oIgvwY-5u>HwW1WiJf2vn{
w5xkvG<s&b3LVy2Unb9{(IsJV-@~eqgExpzklE>An`)(*dRJDky-$=90~#naTdg0=ZX#9i+X4sOk5^moj27AM-fJ^RKPGzDnzA4v
FDWuLsiXrGHf%!9RgF)~LO)XH6}EYg3hHR7D2+622siN1k+jKO1Dwd(v?3-`O~g8q0po@epRUZ_*M50TI_fa`zYF9sVspW+Id(;B
fjzxOM?0gS9<@m14Fr@7DyTHDrdv%NqH}vtn1V$e8)V-YnMW~WU?%<yRrjiHNM)7LZURt&lX=LmAxtF+<l<{R{fG)bZ*g;#8+*_i
7<68G{L#*2*t-1=Y3F*^ll%a~#FpdY+XHG9vnwnvbY_46=q4)%N>8}G*+~jMqTEaLt}L4OrgC6)oJuJw*wLdSvB7T8R+H6+vA#=L
?7oW_E={tih46S0m`p1<iM7ZHs*t#W@F^S0n3=$bCMOO<@gfyd2I!J!W*&U4RsiYur{%~?qs4TVlEdP3YjLTHteUF;<y5KW@H{9S
Tq0F=?enOfV#5@_85&uWf~g!n@T2c1g_tr%1d@VL2@p&u{t=~1JOp}zH~oyyb_MH;0K~HzRni(VznPqJ^h+D*Kk!zy#wD?+UrfqP
Z|d_h2hV-jrbVD4oLxG=S@XFwwtC;Jn0sedz(3_v<botQu=|@an44nypL%=^{K9{2^<o%mrUe|<8{u{?F7qevY*o&mK@zaUT2bF5
05|LfEd*V}OTBqddzaIM*HpDA1aTi30^U_=JD?CY3>Tn(235h9{EQ_lBeq|Oq<`pFA7|&i_`xsdmoq#S1twZ1UgrKas<hDMl3ElP
t^m*4jJVGl$L^G-v0g$d^|WhGtYB+xX5%KvOT>TXG;3oZW`$q5ENGvcYf=?0TDeytR48zvOdNLd7f<k@uV2xUTo>Z$cvxHB?qXF-
uecObyx<1ltT{&b*)yRFSGJDmgiCg(CIFaoEfu6lyplF48BS@TB`*V7F%YSx2a_7+5&@{#Wf2ziM<)P`Yq}}Nvt3p&Ka(x3e6t+7
*&MUB2{!ZO%62)7o}SP?3Ca^dHYuP`jHf$Y3q#s6Z-7Rn{G9QSFV+NS;>+yGdeV^67MC6&3myEb@HK%vb6bq7tKOc~?203GS@c)1
%B30S*@#3$Sp?5!0c*=5T73BB^}lk#!6SRJKWDc&<{$|*ik`GNd@f+6YCTL7@MU5j(AmC1QZ`@2hh8!{$3ozy&KN{rH_fvOI?0N!
OL<W4Cob87(rOpTztZiOvbL*UdToltNpTi;n2J<#Da3W{>j#SV`pXbR*Vke9lMrYe(>Xaw6*ooab+_z|E}k@p<~D%gItXe`Es#HV
l4IbM96Qc&lIh_9+f_&+?8QoGEX!47j1`$hl20RbXI$Xqa|yrtT73GC%=vd%3mkfgd+p7`g`!>n3}ade<5{%61PpjUfq`k!RiURJ
Fjs{ODCEzeC?%T)U%%RlVipJy!ImI)qpjRf9EvuM4PAQP?jD#KII-QQc1Oo>enY35#jT82(JD<MLB~kR*akGPox^}I>n<3CNm!)J
0e00dBr3|(pR#E&x^F7Ew_+TiMkJww!MWmo3R0!UQg9&b2$(_lu`K|dVgXq&9>w$RuWr~>qj?KTj$}Bip8m(slAFs5d9@qHzwlP2
S`Hyv?i~t(uCIAV6DEDH*^G%L<o|y~ZaThm3*e{}aF6%|?cJ0N_fpEn|8E{A<!+Vg{`DPR`lhuEWqp<7G5{^mjeY3;5rBhjq;-$-
DB?C-5{0#5fUT)r8S#v!E7f&m=xLlxeTGl(rJ(6nB8Zqq0W75+Hi5gK`ein)^X$M@V1>;NCpxs;1Ybw63RGn!SBkpaN_^Np7tJdj
_L{q-vVm_&6UqwW#=Vqe`v3p{5lq*OWveL600Hkc`&<A34h%<mvBYQl0ssI200dcD
"""


# Son « toasty » (cri de Mortal Kombat 2), deja traite et encode en ADPCM-A par tools/pack_toasty_snd.py depuis le fichier
# propre fourni par Nicolas : 0,6 s, mono, 18 518,5 Hz, lzma + base85.  ATTENTION : ce cri est (c) Midway / Warner Bros.,
# PAS sous licence MIT ; il est integre ici a la demande de l'auteur du projet, comme le portrait ci-dessus.
# Retrait : vider la chaine (""" """) et mettre JB_TOASTY_SND_USED a 0 ; la cartouche est alors sans son (ou celui de l'utilisateur).
JB_TOASTY_SND_USED = 11254
JB_TOASTY_SND_B85 = """
{Wp48S^xk9=GL@E0stWa8~^|S5YJf5;1>T9=3M{;XdE;FA)nQQMFz-8_U-VLsG2)KdrPp0yV`|#e3D^j5?g+gK`WMa23aDHU!?km
2Odp$d0E_u1EUcJv!aM!y}N+_yd1!IIG$vYQ~%wX9!p5z|14?)IyO|=?Lx_$6d3Gtx}-S<Hzxq>D><CR>cxveT*ZKSHfuv=ulI&B
RKM|16;@s0%w2Q)y$vWw{n%JjmuH!f<<F0#FM-#>$|O}pnN+RwtMwu`FaRYl@)n5EvOz&7@E4W)?VPNJ@$JaNSo<hBw1|8SV|7u(
hk})k1^JqXP2nX=^DC~Zyx_;v<tu^&gsNz5PP&lO(@SuBz(g&-uX8G<i3mvpxI;pVy@mpTnQjq?lhel@Fr@lNR3|8#_A8}4FJq*;
$HsTRMxR3`WRDGq{O+g6khQCLjf08GMuf1LF(;j-)?KPn9~gD#&1z|zO>(7G@54gIOc)qZXp3XvlJeWfnkKkeGWosyk8mMJty3cF
XXcp3SX%GVynA6RADC)Q2Z0<HD7Vl+|NbEsg+fX>vNnLxlUZ6f)1n(0%wGQ#Y|QL0ilV>!XzLG3h~;N9XNEavFx^U%GJ&b<{WXsw
AD9(th*+@=$q@c5lo?e2{ri_5r1z4qCK6$bM2M`(y#z{4c;^Jr|9rt(Dge*~{uVqKUjrVy-m0Zr2RSsZ0$^JE93EPEHWds36W@Nz
(Kq$KF@eEMYMS+{x;k!dNGm(lr>WxLb`NHXnxdeDPx!Qcnyf)_Sia7S(ZASgFNBw4gIj7#^WtZVZs;uMo&Bbzdk)4-Z%*J4bOJ1;
F|i{JHT-;lXTr9Z^2HEyTWA%3q4~?^J<B*}X6eG@z~ayey`#?Q;~%~QA*uf1dGS?;3@*TqN(0VHMukC(yP`BAw(oWhg?7JaT&WKl
mTF@!G_;=;Y$p6=anbzujWy%MsIRF3L!7WTkM)y8L`IZOeu#X43JTxDIpmV+j=&Sx4vz;Mn{(fnI^=t~%bgSNNke<lboDK2XkIuA
ob%)@r1q{4#sWTlMI8_brvI*M=R9Y}#9h!p9Oc{BTsQ6U+^PdWybiWX%0gxiut9=lnyFfQO&9qe9*#1e;3A?;pVbJEZ|~O?3u`ch
eop~D#6MQ}nzb4C>TC?_Wm9gqMp*Y@SoLY}qfsP?8g`yB`qpf^r0eT(&g?Ahw{Rb}(`=ZiXkRf8d6D!6YbWJ`Z5K2^Ekl8mySm)7
#>L4UAILAwEwV45wROmuJ(N;?`~j}xp1Y1&(6Y}_%Vsi@kf<z7p3piwwNYVaPY>CqbM+-nlM_{MyG%0I1g)R7jo|f~=oi3ti)>Sl
r*Y*=B__V&k6r42$MFEYye%<9wz`F?za5nDl)Kv@ylx&BX}tURfO(vmC!7&3#BaE9^ON^3p`F(27edCwwwCo5TzI@B#tbV@M>XO+
Wk(3nRny4yO|dH26ok-*i49dve(kMvZjS7eQd2)Po1&T!pxU#|m!~pPnS3cSz-xl12yq3_RBjS2GGV&kQEI~vT(3DJ3?6msiiJ6R
ZwD)Yh&H6Vz4BP%Zoh->0+7P7`mAFf)2B56cI+z7&iAktXNtE*tQ%$=;~*sQab*)_g%#gl!ha;pip#}#Rm%@7*V@}d($SfPNl?1y
ZKgWzsK-a7M|^bv+mR&LV*2)e;*_d3gG_EQ8}d>G8a;oG_%AiBYH9NL!yF?tdL76y@{dWsymZxQ7J+SP2-bLNC;$1nC<;h54NE<c
$zs4zmp{h2Y{hWPfDq3Wj-Z47*koC;1{S4SgxuO7l&4FB@7);rUEo1N3o>-q>6d4_bvqU7shy%WM?pVNH-5?ZrSgsY#_dF{1b#JT
t+VDFmSlK1-soYIopqK7XFnw|cCTaPg4~@yqFuYh`QFBivx)P$Q40BZ|0$`=Bcbzk$;P?N5Z!gBmF$mIt{{S8<*gYUR4S)5Prhfj
BFAYsuIlC`QHu9-Qm`ym2!kN}_7g~CAQE7V{cT>YgJPhKm*PJa8B<Gd2R$f#*@waNrsT6hi4>b74;fPp9Vj(*1UEg3#sR+|v79z@
Gv#f{+z_(+g|nl8F}`NMf#*P7yYvNC?cYDD$mm-BTAxlCzp)Kek#&5tF2}?>P<58g7Z!SJMuVe4b!wJsPigvsW*5G}$^tbhwjfm^
(=(XO+ofLJt_7YKHTP@rLcn{i&e8C~_s1Bh+8s8k(`qZ%iMHe9?M1y^f+?aYAA)CpH0arlXILb$vft=KWOFOrHCh>KNo8L<<*HQU
v%An7p@&Gbkf`Bi!b2FQ#m@QpS}S*S(k%6X-c(+#St~%eoXdVFqdj1EI4&GspY(U;2uGVsx()%bPk-K`YY?@)rV1SrxT^dGP@erD
saEkRjxheyJXf!gJcMDOET#-Ab6!j2-JGoUfL7MD+vp3#<G=DEwzHT5sdZ3g+nLF%xH9G3GKL*KHeUz*-f3dEhK84I*3_3#fm~a@
P4l$l0X9#>YOG>RS(jYoCh5g#(D9m3?B!t)7f(bz=*fG|N*s&hH}}w<<E*7FzeHkRgH}x3c1n1FRgZOz$LnZq9alq)D2$Q;sSlTh
$S4;aZ*9rSx<iWhmM_rx1^AZ1@l}cxK(l;DcCHi1%->00#D5??g?;`m9>L0NlY6ffiekcWIAkzn3nKc_>~XL`x*0KNvG_n4IHL)c
gGzZ<)Lh0}rME~a`WwMb($aP|JAY==C|Vuz6V@>Ev~=9mNt4ep#s8@eXe+J3$lFpH5WlxaSb2H^+I0gKpqa_aokakjR>%V7r@)(W
Fr#{uT}=%Uw>+_`_>1(CTFa<+>xGoOiKY^W2@H(#P8%O4^zdx^j~d3f;^?+FpDeknOab2E1N^f<!iMMmLdfmG`e*4>mu?jX$g3e`
WD-%GGJy6I1Z3s4JSZVm{-CIu%w(9ue3EfQP8z{uYAq{iAWpSka6wHu*zvaMeK`PT6#?rGB*Zg~j+AJL%!P0Q>ezp=;~Slvtr^x_
6evbF-~zLs-b;~<EODWID^)D~%#$nZ#hbhA*cH{kc$7E9A#kJ_8JiXO^8azJ(s<A3K8{1&5+90rxj4?iROG{`=a=6RI1-yaM5_4*
Nvd{(@D8=J5@eUZ`iA!38CduHut)KzY|l(!77XNxV}v{7$(}wjbHK98_aY}`!8T2oeVCXeFhGr1Y`Z0NlXnfNVTC6-);i;TWCNYK
AE=%iYTXVzJ@gipX@$A0k<>Q#p$1GDw;;ZL;vfIV*_}<rn4&~H=*gSW)$NBpMP{K9fF&g#Q(ko&0P0eo1*~?q5rExDboeWYs9D?w
{OkY<e%o5t+KELiG0n}S0_yVy-&8=UoL6`sCqNR-*VNG%U#?>55@-XoQ+{CXt(ClaI1eR7H|s5tRnlvP#kf5Fl-lWMoiW@pQ4qNa
v!+3`{gFw>+CK6-YvQ(11j$`Mls&5?bP0#SbCSkIXARpmz_`ajh>L(X2zVc&XZYJZyWqb>-un&hcKd^dU2ttAX_=r!Q?2(LOe))Z
PDfS1VlurZBpSEIE@Lky#GPR7Zr+=km_Bku)?@Agfljjd-Rh|_t~E`Nc!PCdrAV=jRjVstbgc5}4-6L`9RTGo+v5~^S$e@5>ERkc
@}5<~-%7F!u0(0={{)Gz0$(N1JiiL*K}6dh2mL)G>@$`8p}#~jZ|HNb)_J}?Zh*DD6;N*^2dE=g4z*(l^16zZ8NNeRiav`>FJlru
4Y<A;txe*zEsQ@1o64Hkgk6tPhnu#<Sl1nG9=YO|r>uQo%P)C0p6_egbzj`7X&+5hXOu4Tnc^U6XnNRpCq^p<4n5IMGcTY<8<?$o
chBG%Av2h15b<r0t;vFs_=!}R9U;2FET}|(m&#P;2M5Sx!Q<?Y;Eu17iJ{llxXS&bUr=l|eJpx6WVh){{{sy426Xx1RjCRxv~rZe
;)2<IXi)++u>wbd{9YTm`=`W!mcNmgR4=ERK)<(dhTPL#r`y-eex=all$%Km$%n))sN!^qa&A9|)j)Bx2V=x}n)7JS8**OM<pv9h
B#^ln4Xe=kf!4Ctp;&aAMn6<@{HLrzvX8bb@(fI-Jp7#7K}&*49nlN`^oiIj+fk~vxC~NHH^h!}(pN;xb`&*$EE>tdh&Rbh-QJmI
g<Zi{4C%u)chMl_9{tG35uv2c*xP<d;PK?IH8&9!@&&upO5~-a^EF$T3NGci0{bgL!4cXYcOB{;%KDTLF_%P4J7QdB31|A14u%}P
mG=k|&5o>L!GpLJH)0IG?|KXJ0SaL$Tf*M?)9Fi5!N3Mvoo^D<fpCM5`FNpX(kK@Nby)hlD#}V1)^$d?51bXBFGNhc2lD)K>w2S*
g7_xSLLiB@j9A@T$amy)0gp#*%l`s^T8@9*FTfh?#yvIJl=X}8R$zB8|Nm2Z`grz25tO{rkvxgbNPgD^2-Mr8I#qH1kV=yN>O;IH
0KEJOu)X#f&;NdO8P!3uCALd{H73-pXI<2xpQGf+m_eM`M=0X@sc}|rn$=J{Erc*4_zP<hG%go}Nx}dxnCVPN{>Y~J2ulmAXLQ%g
=8L{dlE7_bp2Z4aB!C-cjpKd0TJA}X$D(X*X$yM{d3;a$K$gYrn!ym1k4U20XMMQo`L_ZUpng+QPpG`JNCfYQp$Pmf&Kflktu<!~
Yb!9FHFaC${|Prh${hkOB>Qm2Pmd$--(VcvW=0$wQY)O@HV4_cF$cn>jZI&nd3Jvtc%#w=D5?Y93W3sx7=j>?qa<V7=f)K^34;RW
hjlFl4!98Sd$Zj59CgzzC#Gj|mMhenrWVl|+k(p7WDJF12jh0WhUO>rqLShv8jxI0LKy<#Oh<oKJEA{Vy6fv&tE;HOINcABa-UwU
eoR&-U)jN-F%NH<Qk=aJEfKhLavtN`Iw-pI>DKIe?*OB2OB_R1zUsdyl890*X{-^>am<h9)gnAxfDO{Jvg^|SUsWvCT6)y0#}jWC
DPj);4Cy*CTADp7$ayDJoF=^_)f%<yvC9drl*0Mbw&h@w{Opr`#ms@QY<R{mCzg4r!`t-~y0D%A%BQX|9Amle=;u!>+i(5#mn^x`
7K9l5)pV)?N>5G_R*jOO<u40Om{|;7YC}1yI6T45e$bq;;(8V|#82LgBjbpCb_4Kb*yL?Tr1-q2en(|6$;eGy7@mRl?9!2%-zU|S
f$D+JXI-XVcoF?H<d;K)<N70bui#(3uNVkpMz!(y<l1#onIlz9+mA^oAsB(z<hd*i%h8mmWHT11O~Ukwcx3*GgYSU%MKbP-s&K9@
5M(+CasJ(6t(`(0o_6HnZyy5(YHms1g&*wxnFELfq2%x?B^=S68Wd@xV43wT{EO;q-o2x2T?T@x6uB5S2iw*U&keVA561^0dst#T
>)qn8`mn~Gb9$2lyz!YKPCM#X6I>vu$5pTCTw#!Ya-$<E+GraB&Pi}!bi49@X*PI1`@iF6A{@Yva4etFs1ujzMfd`0Sq`woL;|zX
aexr#qL59VJpeLvcJf#{p&N*a<g+cSY=`==RkbaMQz1L>d!q}i<QHPKo(+mKN>7R;IH2sM?YI7968&jNih=Zy!XlB1&AWH|vK53J
vnR7%Riw2HmFBR9C|`K_pztLV%z62#ylhc-u-a`4X5FLW<+QpCF6V(v1B5`1#C<elRD9A`#yYODf4p5nqMQt!x67;<{yW}aA|9ie
?qUVZqPq`sX(*9WUiyai+blreq8Xy{$d(YEx$iayOx-swM{oWIc}xiR7Lri+8&zY8P}U-Fl;LDxY?Q82n|pfZ;PyUG85nJ=K+~TX
KJd4APcsB!h#FS<c8Yn<aEwxv8p0=HT!XNXaOiFvhJrdk0i*Rx@>oqAchMK<BiYg=zEjqOZ|^oy0fKm69JXCqm#Q}_;6IRW?o+Ts
`b2fVKasN2bx|w9OAiIi#%z4`B1s`X)KzYp3SG>T)8(yReSmRetPrhk?oDXzop9&?@%J1phbT<BT<}aqG_4$Wq&A9`*VXi+f48y0
Vz0S>vkJ&F!8_D=bT)6E&9Io*#t-Dj+1;kEjenCnEuS84d$45N3XrM1O^cxvDn|xOJz<DVkTa*|8cf>CZ4lHTDBq%iglh|uWuzGk
!<p8TLgs_m;{#|C#{)a@6|Fe}?V;AwwMnpG!x+3s9-0PT&W{LDm)UA;y_ubh5wx``JgrlDf;az$ulFD_;zFEFSK2A{_=#6Gp_5lk
4t5IvonI*3hGa~jU+AOAup%`{!*?B<8h(Q@;hT&vQ0?WqCeP4}<Eh(7v~2}6R~3BC0O2ov2JYSmFIy%`b=q_Q00000EI?ws7vBvK
00Dv~fGz+4duAp9vBYQl0ssI200dcD
"""


def _jb_builtin_boxes():
    """-> planches integrees, au format de jb_box_frames (liste vide si aucune)."""
    z = "".join(JB_BOXES_B85.split())
    if not z:
        return []
    import lzma
    d = lzma.decompress(base64.b85decode(z))
    out, o = [], 1
    for _ in range(d[0]):
        n, wide, cols, rows, *pal = struct.unpack_from(">HBBB16H", d, o)
        o += struct.calcsize(">HBBB16H")
        w, h = 16 * cols, 16 * rows
        frames = []
        for _ in range(n):
            im = []
            for _ in range(h):
                im.append([v for x in d[o:o + w // 2] for v in (x >> 4, x & 15)])
                o += w // 2
            frames.append(im)
        out.append((frames, pal, bool(wide), cols, rows))
    if o != len(d):
        raise ValueError("built-in screen-saver sheets: corrupted data")
    return out


JB_TOASTY_TILE0 = 0x3F00        # Toasty : tuiles C-ROM (fin de la zone de 2 Mo ; les objets s'arretent avant 0x2500)
JB_TOASTY_RIGHT = 312           # X ecran du bord droit du bloc de colonnes (X de la 1re colonne = 312 - 16 x colonnes)
JB_TOASTY_NCH = 3               # personnages au plus (= TO_NCH de core.S) : un est tire au sort a chaque economiseur
JB_TOASTY_BLK = 40 + 24 * 8 + 4 * 32   # octets d'un bloc toastydata (= TOD_SIZE de core.S)
JB_TOASTY_Y = 132               # Y du haut du bloc de 96 px au repos (bas en 228, sous le bas de l'ecran)
JB_TOASTY_NMAX = 8              # = TO_NMAX de core.S


def _jb_toasty_one(d):
    cols, rows, npal = d[0], d[1], d[2]
    first, o = list(d[3:3 + cols]), 3 + cols
    pals = []
    for _ in range(npal):
        pals.append(list(struct.unpack_from(">16H", d, o)))
        o += 32
    tiles = []
    for c in range(cols):
        col = []
        for _ in range(first[c], rows):
            pal = d[o]
            px = [[v for x in d[o + 1 + 8 * y:o + 9 + 8 * y] for v in (x >> 4, x & 15)] for y in range(16)]
            col.append((pal, px))
            o += 129
        tiles.append(col)
    if o != len(d) or cols > JB_TOASTY_NMAX or npal > 4:
        raise ValueError("built-in Toasty picture: corrupted data")
    return {"cols": cols, "rows": rows, "first": first, "pals": pals, "tiles": tiles}


def _jb_builtin_toasty():
    """Images des personnages integrees (JB_TOASTY_B85, tools/pack_toasty.py) -> liste de dict (au plus JB_TOASTY_NCH) :
    cols, rows, first (1re rangee non vide par colonne), pals (listes de 16 mots), tiles[colonne] = [(palette,
    pixels 16 x 16), ...] de sa 1re rangee au bas."""
    import lzma
    d = lzma.decompress(base64.b85decode("".join(JB_TOASTY_B85.split())))
    n, o, out = d[0], 1, []
    for _ in range(n):
        ln = struct.unpack_from(">H", d, o)[0]
        out.append(_jb_toasty_one(d[o + 2:o + 2 + ln]))
        o += 2 + ln
    if o != len(d) or not 1 <= n <= JB_TOASTY_NCH:
        raise ValueError("built-in Toasty pictures: corrupted data")
    if sum(sum(len(c) for c in t["tiles"]) for t in out) > 0x4000 - JB_TOASTY_TILE0:
        raise ValueError("built-in Toasty pictures: too many tiles")
    return out


JB_STEXT_MAX = 256              # texte qui ondule personnalise : caracteres au plus (+ 4 espaces de separation)
JB_SFX_OFF = 0x40               # bloc du cri dans le driver Z80 (m1drv.asm, sfxp) : "SFX" 0, voie, debut, fin, duree
JB_SFX_MAXSEC = 3.0             # cri du Toasty : duree maximale apres retrait des silences
JB_ADPCMA_RATE = 8_000_000 / 432    # YM2610 a 8 MHz : ADPCM-A a 18 518,5 Hz
JB_TICK_SEC = 32 * 144 / 8_000_000  # tick du driver Z80 (Timer A, NA = 992) : 32 echantillons FM = 0,576 ms
_ADPCMA_STEPS = (16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143, 157,
                 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724, 796, 876, 963, 1060,
                 1166, 1282, 1411, 1552)
_ADPCMA_INC = (-1, -1, -1, -1, 2, 5, 7, 9)


def jb_saver_text(text):
    """Texte qui ondule personnalise -> octets pour t_custom (core.S), ou None (textes d'origine).  Police de la ROM :
    0x20..0x5F (espace, chiffres, ponctuation, majuscules) : minuscules -> majuscules, accents retires (é -> E,
    œ -> OE), autre caractere -> espace ; espaces en trop retires ; 4 espaces ajoutes pour separer les tours."""
    import unicodedata
    if text is None:
        return None
    t = str(text)
    for a, b in (("œ", "oe"), ("Œ", "OE"), ("æ", "ae"), ("Æ", "AE"), ("ß", "ss")):
        t = t.replace(a, b)
    t = unicodedata.normalize("NFKD", t).upper()
    out = "".join(c if 0x20 <= ord(c) <= 0x5F else ("" if unicodedata.combining(c) else " ") for c in t)
    out = " ".join(out.split())
    if not out:
        return None
    if len(out) > JB_STEXT_MAX:
        raise ValueError(f"screen-saver text: {len(out)} characters, {JB_STEXT_MAX} at most")
    return (out + "    ").encode("ascii")


def adpcma_decode(data):
    """ADPCM-A du YM2610 (comme ymfm : quartet fort d'abord, accumulateur de 12 bits qui deborde en boucle, pas
    borne a 0..48) -> liste d'echantillons 12 bits signes."""
    acc, si, out = 0, 0, []
    for b in data:
        for n in (b >> 4, b & 15):
            d = (2 * (n & 7) + 1) * _ADPCMA_STEPS[si] // 8
            acc = (acc + (-d if n & 8 else d)) & 0xFFF
            si = min(48, max(0, si + _ADPCMA_INC[n & 7]))
            out.append(acc - 0x1000 if acc & 0x800 else acc)
    return out


def adpcma_encode(x):
    """Echantillons 12 bits signes -> ADPCM-A (2 par octet, quartet fort d'abord).  Chaque quartet : celui qui
    rapproche le plus le decodeur de la cible en regardant aussi l'echantillon suivant (le pas choisi decide du
    suivant), sans jamais faire deborder l'accumulateur 12 bits (le YM2610 boucle au lieu de saturer)."""
    acc, si, nib = 0, 0, []
    xs = [int(v) for v in x] + [0]

    def step(a, i, n):
        d = (2 * (n & 7) + 1) * _ADPCMA_STEPS[i] // 8
        return (a - d if n & 8 else a + d), min(48, max(0, i + _ADPCMA_INC[n & 7]))
    for k in range(len(x)):
        best = None
        for n in range(16):
            a1, i1 = step(acc, si, n)
            if not -2048 <= a1 <= 2047:
                continue
            e2 = 1 << 40
            for m in range(16):
                a2, _ = step(a1, i1, m)
                if -2048 <= a2 <= 2047:
                    e2 = min(e2, (a2 - xs[k + 1]) ** 2)
            c = 2 * (a1 - xs[k]) ** 2 + e2
            if best is None or c < best[0]:
                best = (c, n, a1, i1)
        _, n, acc, si = best
        nib.append(n)
    if len(nib) & 1:
        nib.append(8)
    return bytes((nib[i] << 4) | nib[i + 1] for i in range(0, len(nib), 2))


def _jb_builtin_sound():
    """Son « toasty » integre (JB_TOASTY_SND_B85) -> (ADPCM-A, echantillons utiles, texte) comme jb_toasty_sound, ou None
    s'il a ete retire du programme."""
    import lzma
    b = "".join(JB_TOASTY_SND_B85.split())
    if not b or not JB_TOASTY_SND_USED:
        return None
    adp = lzma.decompress(base64.b85decode(b))
    return adp, JB_TOASTY_SND_USED, (f"built-in Toasty sound: {JB_TOASTY_SND_USED / JB_ADPCMA_RATE:.3f} s, "
                                     f"{len(adp)} bytes of ADPCM-A")


def jb_toasty_sound(path):
    """Fichier son fourni par l'utilisateur (WAV PCM 8/16/24/32 bits, tout debit, mono ou stereo ; autres formats avec
    le module soundfile) -> (ADPCM-A complete a un multiple de 256 octets + 256 octets de silence, echantillons utiles,
    texte).  Mono, decalage continu retire, silences de debut et de fin retires (enveloppe sur 2 ms, seuil 36 dB sous
    la crete, 4 ms gardes avant, 6 ms apres, fondus de 2 / 5 ms), crete a -1 dBFS sur 12 bits, 18 518,5 Hz.
    Sert a remplacer le son integre (_jb_builtin_sound) par un fichier de l'utilisateur, et a tools/pack_toasty_snd.py."""
    from fractions import Fraction
    name = os.path.basename(path)
    if not os.path.isfile(path):
        raise ValueError(f"Toasty sound: file not found: {path}")
    try:
        with wave.open(path, "rb") as w:
            ch, sw, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
            raw = w.readframes(n)
        if sw == 1:
            a = (np.frombuffer(raw, np.uint8).astype(np.float64) - 128) * 256
        elif sw == 2:
            a = np.frombuffer(raw, "<i2").astype(np.float64)
        elif sw == 3:
            b = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
            a = ((b[:, 0] | b[:, 1] << 8 | b[:, 2] << 16) << 8 >> 8).astype(np.float64) / 256
        elif sw == 4:
            a = np.frombuffer(raw, "<i4").astype(np.float64) / 65536
        else:
            raise ValueError(f"{sw * 8}-bit samples")
        a = a[:len(a) // ch * ch].reshape(-1, ch)
    except (wave.Error, EOFError, ValueError) as ex:
        try:
            import soundfile as sf
        except ImportError:
            raise ValueError(f"Toasty sound {name}: not a PCM WAV file ({ex}); other formats need the soundfile "
                             "module (pip install soundfile)")
        try:
            a, rate = sf.read(path, dtype="float64", always_2d=True)
        except Exception as ex2:
            raise ValueError(f"Toasty sound {name}: {ex2}")
        a = a * 32768
    x = a.mean(axis=1)
    if not len(x) or not np.abs(x).max():
        raise ValueError(f"Toasty sound {name}: silent")
    w2 = max(1, int(rate * 0.002))
    env = np.sqrt(np.convolve(x * x, np.ones(w2) / w2, "same"))
    loud = np.nonzero(env > env.max() * 10 ** (-36 / 20))[0]
    a0, b0 = max(0, int(loud[0]) - int(rate * 0.004)), min(len(x), int(loud[-1]) + int(rate * 0.006))
    y = x[a0:b0] - x[a0:b0].mean()
    if len(y) > rate * JB_SFX_MAXSEC:
        raise ValueError(f"Toasty sound {name}: {len(y) / rate:.2f} s without its silences, {JB_SFX_MAXSEC:g} s at most")
    fi, fo = min(len(y), max(1, int(rate * 0.002))), min(len(y), max(1, int(rate * 0.005)))
    y[:fi] *= np.linspace(0, 1, fi)
    y[-fo:] *= np.linspace(1, 0, fo)
    r = Fraction(8_000_000, 432 * int(rate)).limit_denominator(2000)
    z = _resample(y.reshape(-1, 1).astype(np.float32), r.numerator, r.denominator)[:, 0].astype(np.float64)
    z *= 2047 * 10 ** (-1 / 20) / max(np.abs(z).max(), 1e-9)                # crete a -1 dBFS, sur 12 bits
    pcm = [int(v) for v in np.round(z)]
    used = len(pcm)
    pcm += [0] * ((-len(pcm)) % 512 + 512)          # complete a 256 octets + 256 octets de silence (fin incluse ou non)
    adp = adpcma_encode(pcm)
    dec = np.array(adpcma_decode(adp))[:used]
    ref = np.array(pcm[:used])
    snr = 10 * np.log10((ref ** 2).sum() / max(((dec - ref) ** 2).sum(), 1))
    info = (f"{name}: {used / JB_ADPCMA_RATE:.3f} s used ({len(x) / rate:.2f} s with its silences), "
            f"{len(adp)} bytes of ADPCM-A, signal/noise {snr:.1f} dB")
    return adp, used, info


def jb_box_spec(spec):
    """"planche.png@1.3" -> ("planche.png", 1.3) ; sans suffixe numerique final -> (spec, 1.0).  Seul un "@nombre" en fin
    compte : un chemin qui contient "@" (dossier Windows "nico@pc"...) reste entier."""
    path, sep, gr = spec.rpartition("@")
    if sep and path:
        try:
            g = float(gr)
            if 0.1 <= g <= 4.0:
                return path, g
        except ValueError:
            pass
    return spec, 1.0


def jb_box_note():
    """Une ligne : planches d'objets de l'economiseur utilisees par defaut (integrees, sauf celles remplacees par un fichier
    jukebox_boxes(n).png pose a cote du programme)."""
    found = [f for f in JB_BOX_FILES if os.path.isfile(os.path.join(HERE, f))]
    if not JB_BOXES_B85.strip() and not found:
        return "No screen-saver objects."
    if found:
        return "Screen-saver objects: built-in sheets, except " + ", ".join(found) + " (next to the program)."
    return "Screen-saver objects: built-in sheets."


def jb_box_frames(path, grow=1.0):
    """Planche d'animation des boites de l'economiseur (fichier PNG ; les planches par defaut sont integrees, deja
    converties, dans JB_BOXES_B85) : images
    sur fond magenta (#FF00FF), separees par du magenta, lues ligne par ligne.  Orientation deduite des images : haute
    (boite : 30 x 42 px au plus, grille de 2 x 3 tuiles) ou large (console : 62 x 38 px au plus, 4 x 3 tuiles).  Chaque
    image est reduite avec 1 px de marge (meme echelle pour toutes : la rotation reste centree), palette commune de
    14 couleurs, plus un lisere clair d'un pixel autour de la silhouette (couleur 15, scintillement par la ROM).
    -> (images : listes de rangees d'indices 0..15 (0 = transparent), palette : 16 mots couleur Neo Geo,
        large, colonnes de sprites, rangees de tuiles).
    grow : agrandissement (2.5.19 ; logo et triangle Delta Island integres : 1.3), plafonne a 3 rangees de tuiles (46 px
    + lisere : la ROM suppose des objets de 48 px de haut au plus) et 4 colonnes (62 px) ; un objet haut peut ainsi
    passer a 3 colonnes (deux sur une ligne : 6 sprites, 89 + 6 = 95 < 96)."""
    from PIL import Image
    im = Image.open(path).convert("RGB")
    a = np.asarray(im).astype(np.int16)
    mag = (a[..., 0] > 200) & (a[..., 1] < 70) & (a[..., 2] > 200)

    def runs(mask):
        idx = np.nonzero(mask)[0]
        if not len(idx):
            return []
        cut = np.nonzero(np.diff(idx) > 1)[0]
        return list(zip(np.r_[idx[0], idx[cut + 1]], np.r_[idx[cut], idx[-1]] + 1))
    rows, cols = runs((~mag).any(1)), runs((~mag).any(0))
    if not rows or not cols:
        raise ValueError("no frame found (frames must be on a magenta #FF00FF background)")
    cells = [(r, c) for r in rows for c in cols if (~mag[r[0]:r[1], c[0]:c[1]]).any()][:JB_BOX_MAX]
    cw = max(c[1] - c[0] for c in cols)
    ch = max(r[1] - r[0] for r in rows)
    wide = cw > ch
    k = min(62 / cw, 38 / ch) if wide else min(30 / cw, 42 / ch)
    k = min(k * grow, 62 / cw, 46 / ch)
    tw, th = max(1, round(cw * k)), max(1, round(ch * k))
    W, H = 16 * -(-(tw + 2) // 16), 16 * -(-(th + 2) // 16)     # grille de sprites (16 px) avec la marge du lisere
    rgba = []
    for (r0, r1), (c0, c1) in cells:                    # cellule commune centree sur l'image : pas de saut d'une image a l'autre
        x0 = (c0 + c1 - cw) // 2
        y0 = (r0 + r1 - ch) // 2
        crop = np.zeros((ch, cw, 4), np.uint8)
        sx0, sy0 = max(0, x0), max(0, y0)
        sx1, sy1 = min(a.shape[1], x0 + cw), min(a.shape[0], y0 + ch)
        sub = a[sy0:sy1, sx0:sx1].astype(np.uint8)
        crop[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0, :3] = sub
        crop[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0, 3] = np.where(mag[sy0:sy1, sx0:sx1], 0, 255)
        crop[..., :3] *= (crop[..., 3:] > 0)
        rgba.append(np.asarray(Image.fromarray(crop, "RGBA").resize((tw, th), Image.LANCZOS)))
    # palette : couleurs de la planche d'origine, chaque teinte pesee par la racine de son nombre de pixels (sinon les
    # aplats sombres prennent toute la palette et les touches vives - liseres, logo - disparaissent)
    src = a[~mag].astype(np.int32)
    u, cnt = np.unique((src[:, 0] << 16) | (src[:, 1] << 8) | src[:, 2], return_counts=True)
    u = np.stack([u >> 16, (u >> 8) & 255, u & 255], 1).astype(np.uint8)
    samp = np.repeat(u, np.maximum(1, (np.sqrt(cnt) / 8).astype(int)), axis=0)
    pal_img = Image.fromarray(samp.reshape(-1, 1, 3)).quantize(colors=14, method=Image.Quantize.MEDIANCUT)
    pal = (pal_img.getpalette() or [])[:42]                 # moins de 14 couleurs dans la planche : palette completee
    pal = np.array(pal + pal[-3:] * ((42 - len(pal)) // 3) if pal else [0] * 42, np.int32).reshape(14, 3)
    frames = []
    for f in rgba:
        out = np.zeros((H, W), np.uint8)
        ox, oy = (W - tw) // 2, H - 1 - th               # posee en bas (1 px de marge pour le lisere)
        rgb = f[..., :3].astype(np.int32)
        d = ((rgb[:, :, None, :] - pal[None, None]) ** 2).sum(3)
        idx = d.argmin(2) + 1
        out[oy:oy + th, ox:ox + tw] = np.where(f[..., 3] >= 128, idx, 0)
        m = out > 0                                      # lisere : voisins (4-connexite) de la silhouette
        edge = np.zeros_like(m)
        edge[1:] |= m[:-1]; edge[:-1] |= m[1:]; edge[:, 1:] |= m[:, :-1]; edge[:, :-1] |= m[:, 1:]
        out[edge & ~m] = 15
        frames.append(out.tolist())

    def word(c):
        r, g, b = (int(round(v * 31 / 255)) for v in c)
        return ((r & 1) << 14) | ((g & 1) << 13) | ((b & 1) << 12) | ((r >> 1) << 8) | ((g >> 1) << 4) | (b >> 1)
    return frames, [0x8000] + [word(c) for c in pal] + [word((190, 190, 200))], wide, W // 16, H // 16


def jb_sprite_region(fix, boxes=(), toasty=None):
    """Tuiles C-ROM de l'economiseur.  -> zone 'sprites' au format MAME (2 Mo : octets pairs = C1, impairs = C2) ; tuile
    de 128 octets : rangee y de la moitie gauche en 0x40 + 4y, droite en 4y ; plans 0, 2, 1, 3 aux octets +0..+3 ;
    bit x = pixel x.
    - Petite police (JB_SM_TILE0 + c - 0x20, c = 0x20..0x7E) : police du BIOS 8x8 en couleur 1, ombre en couleur 2,
      colonnes doublees (16 px) pour un affichage reduit a 8 px de large (SCB2 0x07FF, sprites colles).
    - Damier isometrique (JB_CK_TILE + colonne 0..7 + 8 x rangee 0..3) : losanges de 64 x 32, un sur deux en couleur 1, l'autre transparent.
    - Texte : caracteres 0x20..0x5F de la police du BIOS (sfix) agrandis x5 (40 x 40), coupes en 10 tranches de 4 px ;
      chaque tranche = 3 tuiles (haut, milieu, bas ; 8 lignes vides en bas), dans les colonnes 0-3 :
      JB_SPR_TILE0 + 3 x (10 x (c - 0x20) + tranche).  Couleur 1 + rangee x 8 // 40 (8 bandes de 5 px, palette 16
      animee), contour noir de 2 px (couleur 9)."""
    region = bytearray(2 * MB)
    for k in range(32):
        cx, cy = 16 * (k & 7), 16 * (k >> 3)
        for y in range(16):
            for x in range(16):
                X, Y = cx + x, cy + y
                u, v = (X + 2 * Y) // 64, (X - 2 * Y + 256) // 64              # X/64 + Y/32 et X/64 - Y/32 (decale)
                if (u + v) % 2 == 0:                                       # l'autre losange reste transparent
                    _spr_put(region, JB_CK_TILE + k, x, y, 1)
    for c in range(0x20, 0x7F):                         # petite police 8x8 (couleur 1) + ombre portee d'un pixel (couleur 2)
        t = fix[c * 32:(c + 1) * 32]
        px = [[0] * 8 for _ in range(8)]
        for y in range(8):
            for pair, base in enumerate((0x10, 0x18, 0x00, 0x08)):
                b = t[base + y]
                px[y][2 * pair], px[y][2 * pair + 1] = b & 15, b >> 4
        ink = lambda x, y: 0 <= x < 8 and 0 <= y < 8 and px[y][x] == 1
        for y in range(9):                              # colonnes doublees : le sprite est reduit a 8 px (une colonne sur
            for x in range(8):                          # deux gardee par le materiel) ; l'ombre de la colonne 8 tombe
                col = 1 if ink(x, y) else (2 if ink(x - 1, y - 1) else 0)
                if col:
                    _spr_put(region, JB_SM_TILE0 + c - 0x20, 2 * x, y, col)
                    _spr_put(region, JB_SM_TILE0 + c - 0x20, 2 * x + 1, y, col)
    for c in range(0x20, 0x60):
        t = fix[c * 32:(c + 1) * 32]
        px = [[0] * 8 for _ in range(8)]
        for y in range(8):
            for pair, base in enumerate((0x10, 0x18, 0x00, 0x08)):
                b = t[base + y]
                px[y][2 * pair], px[y][2 * pair + 1] = b & 15, b >> 4
        G = 40                                                                  # police x5
        ink = [[px[gy // 5][gx // 5] == 1 for gx in range(G)] for gy in range(G)]
        for gy in range(G):
            for gx in range(G):
                if ink[gy][gx]:
                    col = 1 + gy * 8 // G
                elif any(ink[yy][xx] for yy in range(max(0, gy - 2), min(G, gy + 3))
                         for xx in range(max(0, gx - 2), min(G, gx + 3))):
                    col = 9                                                     # contour
                else:
                    continue
                sl = gx // 4
                _spr_put(region, JB_SPR_TILE0 + 3 * (10 * (c - 0x20) + sl) + gy // 16, gx % 4, gy % 16, col)
    tile = JB_BOX_TILE0                                 # objets animes : colonnes x rangees de tuiles par image
    for frames, _, _, cols, rows in boxes:              #   (colonnes de sprites x rangees de tuiles, colonne par colonne)
        for px in frames:
            for y in range(len(px)):
                for x in range(len(px[0])):
                    if px[y][x]:
                        _spr_put(region, tile + rows * (x // 16) + y // 16, x % 16, y % 16, px[y][x])
            tile += cols * rows
    if toasty:                                          # Toasty : personnage par personnage, colonne par colonne, de sa
        tile = JB_TOASTY_TILE0                          #   1re rangee non vide au bas
        for ch in toasty:
            for col in ch["tiles"]:
                for _, px in col:
                    for y in range(16):
                        for x in range(16):
                            if px[y][x]:
                                _spr_put(region, tile, x, y, px[y][x])
                    tile += 1
    return bytes(region)


def bios_ok(path):
    """None si ce zip est un BIOS Neo Geo utilisable (bloc de sécurité + sfix), sinon le motif du refus."""
    if not path or not os.path.isfile(path):
        return "file not found"
    try:
        _bios_parts(path)
        return None
    except zipfile.BadZipFile:
        return "not a valid zip file"
    except Exception as ex:
        return str(ex)


def bios_places(last_rom=None):
    """Les deux seuls dossiers où neogeo.zip est cherché : celui de l'exe (ou du script ngt_studio.py) et celui de la
    dernière ROM Neo Geo ouverte dans l'onglet Extract (le dossier lui-même si c'est un dossier de ROM)."""
    dirs = [HERE]
    if last_rom:
        last_rom = os.path.abspath(os.path.expanduser(last_rom))
        is_dir = os.path.isdir(last_rom) or (not os.path.exists(last_rom) and not os.path.splitext(last_rom)[1])
        dirs.append(last_rom if is_dir else os.path.dirname(last_rom))
    out = []
    for d in dirs:
        if os.path.normcase(d) not in map(os.path.normcase, out):
            out.append(d)
    return out


def find_bios(given=None, last_rom=None):
    """-> (chemin d'un neogeo.zip valide ou None, [(chemin essayé, motif du refus)]).  Le chemin donné (champ de
    l'interface ou --bios) passe d'abord ; sinon recherche automatique dans bios_places()."""
    tried = []
    if given:
        why = bios_ok(given)
        if why is None:
            return given, tried
        tried.append((given, why))
    for d in bios_places(last_rom):
        try:
            names = [n for n in os.listdir(d) if n.lower() == "neogeo.zip"]
        except OSError:
            continue
        for n in names:
            f = os.path.join(d, n)
            why = bios_ok(f)
            if why is None:
                return f, tried
            tried.append((f, why))
    return None, tried


def bios_help(tried, last_rom=None):
    """Message expliquant où neogeo.zip a été cherché (pour l'interface et la ligne de commande)."""
    lines = ["The jukebox ROM needs YOUR Neo Geo BIOS: neogeo.zip (the one from your MAME set; it is not included,",
             "SNK's BIOS cannot be redistributed). Looked for neogeo.zip in:"]
    lines += ["  " + d for d in bios_places(last_rom)]
    for f, why in tried:
        lines.append(f"Rejected {f}: {why}")
    return "\n".join(lines)


def jb_occupancy(ev):
    """% affiché par le jukebox : (P-ROM + V-ROM utilisées) / (P-ROM + V-ROM du format, standard ou étendu)."""
    pv = [r for r in ev["rows"] if r["name"].startswith(("P-ROM", "V-ROM"))]
    return min(199, int(round(100 * sum(r["used"] for r in pv) / max(sum(r["limit"] for r in pv), 1))))


def build_cart(pk, profile, bios_zip, outdir, name="ngjb", formats=JB_FORMATS, boxes=None, toasty=False,
               toasty_sound=None, saver_text=None, toasty_sfx=True):
    """Écrit la cartouche dans outdir, dans un ou plusieurs formats :
      mame     : set ngjb.zip (fichiers ROM a la racine du zip) + liste logicielle hash/neogeo.xml
                 (mame neogeo ngjb -hashpath hash -rompath .)
      darksoft : dossier darksoft/ngjb/ (prom, srom, m1rom, vroma0, crom0, fpga) pour le Darksoft Multi
      neosd    : fichier neosd/ngjb.neo (TerraOnion NeoSD)
    boxes : planches des objets animes de l'economiseur (voir jb_box_frames), chemins separes par des virgules (2 au
    plus) ; None = planches integrees, chacune remplacee par jukebox_boxes(n).png s'il est a cote du programme ; "" = sans objets.
    toasty : True = « Aurelien - Toasty » dans l'economiseur, une fois par economiseur, au premier changement de piste
    (voir core.S) ; False = absent (bloc toastydata a zero, aucune tuile).
    toasty_sound : fichier son de l'utilisateur (jb_toasty_sound), joue avec le Toasty par-dessus la musique a la place du
                   son integre ; toasty_sfx=False : aucun son
    (voie ADPCM-A la moins utilisee des albums, empruntee le temps du cri) ; None = Toasty muet.
    saver_text : texte qui ondule personnalise (jb_saver_text, 256 caracteres) ; None ou vide = textes d'origine.
    Refuse si l'évaluation dépasse la marge.  -> (texte du rapport, liste des fichiers écrits)."""
    if not pk["games"] or not any(g["tracks"] for g in pk["games"]):
        raise ValueError("nothing to build: tick at least one track")
    ev = evaluate_cart(pk, profile)
    report = format_eval(pk, ev)
    if not ev["ok"]:
        raise ValueError(report)
    sec, fix = _bios_parts(bios_zip)
    bios_font = fix
    def load(bp):
        bp, grow = jb_box_spec(bp)                      # "planche.png@1.3" : agrandie de 30 % (voir jb_box_frames)
        try:
            return jb_box_frames(bp, grow)
        except ImportError:
            raise ValueError("the screen-saver boxes need the Pillow module (pip install pillow)")
        except Exception as ex:
            raise ValueError(f"screen-saver boxes, {bp}: {ex}")
    box = []
    if boxes is None:
        # planches par defaut : la planche integree n, sauf si jukebox_boxes(n).png est pose a cote du programme (il la
        # remplace, elle seule ; 2.5.20 : avant, un seul fichier present remplacait toutes les planches integrees)
        builtin = _jb_builtin_boxes()
        box_paths = []
        for k, f in enumerate(JB_BOX_FILES):
            fp = os.path.join(HERE, f)
            if os.path.isfile(fp):
                box.append(load(fp))
                box_paths.append(fp)
            elif k < len(builtin):
                box.append(builtin[k])
                box_paths.append(f"built-in sheet {k + 1}")
    else:
        box_paths = [p.strip() for p in boxes.split(",") if p.strip()]
        if len(box_paths) > JB_BOX_NP:
            raise ValueError(f"screen-saver boxes: {JB_BOX_NP} picture sheets at most")
        box = [load(bp) for bp in box_paths]
    tiles = _jb_bin(JB_TILES_B64)                       # police du BIOS + tuiles maison de l'interface
    fix = fix[:JB_TILES_FIRST * 32] + tiles + fix[JB_TILES_FIRST * 32 + len(tiles):]
    code = bytearray(_jb_bin(JB_PROM_B64))
    code[JB_SECBLK_OFF:JB_SECBLK_OFF + 122] = sec
    img, banks = layout_prom(bytes(code), pk)
    if len(img) > JB_PROFILES[profile]["prom"]:
        raise ValueError("P-ROM image larger than the profile allows")
    # occupation affichée en haut à droite du jukebox : (P-ROM + V-ROM utilisées) / (P-ROM + V-ROM du format choisi,
    # standard 5 + 16 Mo ou étendu 9 + 16 Mo) ; le M1 (driver fixe de 1 Ko) n'entre pas dans le calcul
    img = bytearray(img)
    struct.pack_into(">H", img, 0x14E, jb_occupancy(ev))
    struct.pack_into(">H", img, JB_BOXDATA_OFF, len(box))    # boxdata (core.S) : planches, puis pour chacune (48 octets)
    tile = JB_BOX_TILE0                                  #   images, large, 1re tuile, palette, colonnes - 1, rangees,
    for k, (frames, pal, wide, cols, rows) in enumerate(box):    #   tuiles par image, 320 - largeur, 224 - hauteur
        struct.pack_into(">HHH16H5H", img, JB_BOXDATA_OFF + 2 + 48 * k, len(frames), int(wide), tile, *pal,
                         cols - 1, rows, cols * rows, 320 - 16 * cols, 224 - 16 * rows)
        tile += cols * rows * len(frames)
    if toasty and not JB_TOASTY_OFF:
        raise ValueError("this jukebox program has no Toasty block (JB_TOASTY_OFF)")
    stext = jb_saver_text(saver_text)
    if stext:
        if not JB_STEXT_OFF:
            raise ValueError("this jukebox program has no custom text block (JB_STEXT_OFF)")
        img[JB_STEXT_OFF:JB_STEXT_OFF + len(stext) + 1] = stext + b"\0"
    m1 = bytearray(_jb_bin(JB_M1_B64))
    sfx_note = ""
    vrom = pk["vrom"]
    snd = (jb_toasty_sound(toasty_sound) if toasty_sound else _jb_builtin_sound()) if toasty and toasty_sfx else None
    if snd:
        if m1[JB_SFX_OFF:JB_SFX_OFF + 4] != b"SFX\0":
            raise ValueError("this Z80 driver has no Toasty sound block")
        adp, used, sinfo = snd
        start = -(-len(vrom) // 256) * 256              # aligne sur 256 octets, sans franchir une limite de 1 Mo
        if start // MB != (start + len(adp) - 1) // MB:
            start = -(-start // MB) * MB
        if start + len(adp) > JB_PROFILES[profile]["vrom"]:
            raise ValueError(f"Toasty sound: no room left in the V-ROM ({len(adp)} bytes needed)")
        vrom = vrom.ljust(start, b"\x80") + adp
        keys = pk.get("adpcma_keys") or [0] * 6
        ch = min(range(6), key=lambda c: (keys[c], -c))  # voie la moins declenchee (egalite : la plus haute)
        ticks = int(math.ceil(len(adp) * 2 / JB_ADPCMA_RATE / JB_TICK_SEC)) + 35     # + 20 ms
        struct.pack_into("<BHHH", m1, JB_SFX_OFF + 4, ch, start // 256, (start + len(adp)) // 256 - 1, ticks)
        sfx_note = (f"Toasty sound: {sinfo}; ADPCM-A voice {ch + 1} borrowed from the music for "
                    f"{ticks * JB_TICK_SEC:.2f} s (triggered {keys[ch]} times by the albums; all voices: "
                    f"{', '.join(str(k) for k in keys)}).\n")
    to = _jb_builtin_toasty() if toasty else None
    if to:                                               # toastydata (core.S) : un bloc par personnage ; bloc : actif, colonnes,
        t = JB_TOASTY_TILE0                              #   X, Y de repos, (1re rangee, taille) x 8, SCB1 (tuile, attribut)
        for k, ch in enumerate(to):                      #   x 6 x 8, palettes
            o = JB_TOASTY_OFF + k * JB_TOASTY_BLK
            struct.pack_into(">4H", img, o, 1, ch["cols"], JB_TOASTY_RIGHT - 16 * ch["cols"], JB_TOASTY_Y)
            for c in range(ch["cols"]):
                struct.pack_into(">2H", img, o + 8 + 4 * c, ch["first"][c], ch["rows"] - ch["first"][c])
                for j, (pal, _) in enumerate(ch["tiles"][c]):
                    struct.pack_into(">2H", img, o + 40 + 24 * c + 4 * j, t, (33 + pal) << 8)
                    t += 1
            for j, pal in enumerate(ch["pals"]):
                struct.pack_into(">16H", img, o + 40 + 24 * JB_TOASTY_NMAX + 32 * j, *pal)
    img = bytes(img)
    p1, p2 = prom_split(img)
    sw = lambda b: bytes(x for pr in zip(b[1::2], b[0::2]) for x in pr)     # format MAME load16_word_swap
    files = [(f"{name}-p1.p1", sw(p1), "maincpu", 0, "load16_word_swap")]
    if p2:
        files.append((f"{name}-p2.sp2", sw(p2), "maincpu", MB, "load16_word_swap"))
    files.append((f"{name}-s1.s1", fix, "fixed", 0, None))
    files.append((f"{name}-m1.m1", bytes(m1).ljust(0x20000, b"\xff"), "audiocpu", 0, None))
    nv = max(1, -(-len(vrom) // (4 * MB)))
    v = vrom.ljust(nv * 4 * MB, b"\x80")
    for i in range(nv):
        files.append((f"{name}-v{i + 1}.v{i + 1}", v[i * 4 * MB:(i + 1) * 4 * MB], "ymsnd:adpcma", i * 4 * MB, None))
    spr = jb_sprite_region(bios_font, box, to)          # sprites de l'economiseur (police du BIOS, sfix d'origine, objets, Toasty)
    files.append((f"{name}-c1.c1", spr[0::2], "sprites", 0, "load16_byte"))
    files.append((f"{name}-c2.c2", spr[1::2], "sprites", 1, "load16_byte"))
    written = []
    os.makedirs(outdir, exist_ok=True)                  # (2.5.16 : le format mame seul ne le creait pas)
    m1bin = files[[f[2] for f in files].index("audiocpu")][1]
    prom_mame = sw(p1) + (sw(p2) if p2 else b"")
    if "darksoft" in formats:
        # Format relevé sur des jeux convertis : P concaténées telles quelles (ordre MAME), S, M, V concaténées,
        # C1 / C2 entrelacées par mots de 2 octets (« word merge », dixit Darksoft ; non vérifié sur la carte), et « fpga » = numéro de configuration en texte.  On ne réutilise que des
        # configurations de vrais jeux : P 1 Mo -> "12" (comme aof2) ; P1 1 Mo + P2 4 Mo -> "10" (comme kof97,
        # lastblad, shocktr2) ; la P2 est donc complétée à 4 Mo.  P2 8 Mo (étendu) : "10" aussi, NON vérifié.
        dd = os.path.join(outdir, "darksoft", name)
        os.makedirs(dd, exist_ok=True)
        dprom = sw(p1) + (sw(p2.ljust(max(len(p2), 4 * MB), b"\xff")) if p2 else b"")
        c1, c2 = spr[0::2], spr[1::2]
        crom0 = b"".join(c1[i:i + 2] + c2[i:i + 2] for i in range(0, len(c1), 2))
        for fn, b in (("prom", dprom), ("srom", fix), ("m1rom", m1bin), ("vroma0", v), ("crom0", crom0),
                      ("fpga", b"10" if p2 else b"12")):
            open(os.path.join(dd, fn), "wb").write(b)
            written.append(os.path.join(dd, fn))
    if "neosd" in formats:
        # .neo (TerraOnion) : en-tête 4096 octets petit-boutiste "NEO" 1, tailles P S M V1 V2 C, année, genre,
        # capture, NGH, nom (33), éditeur (17) ; puis les zones dans cet ordre (P dans l'ordre des fichiers MAME,
        # C entrelacées octet par octet).
        hdr = bytearray(4096)
        hdr[0:4] = b"NEO\x01"
        cdata = spr                                     # C1 / C2 entrelacées octet par octet (ordre MAME)
        struct.pack_into("<6I", hdr, 4, len(prom_mame), len(fix), len(m1bin), len(v), 0, len(cdata))
        struct.pack_into("<4I", hdr, 28, int(time.strftime("%Y")), 0, 0, 0x0999)
        hdr[44:44 + 33] = b"Neo Geo Jukebox".ljust(33, b"\0")
        hdr[77:77 + 17] = b"NGT Studio".ljust(17, b"\0")
        nd = os.path.join(outdir, "neosd")
        os.makedirs(nd, exist_ok=True)
        fneo = os.path.join(nd, name + ".neo")
        with open(fneo, "wb") as f:
            for part in (bytes(hdr), prom_mame, fix, m1bin, v, cdata):
                f.write(part)
        written.append(fneo)
    if "mame" in formats:
        # set MAME = un zip ngjb.zip, fichiers a la racine (date fixe : meme zip d'une construction a l'autre sur une
        # meme machine ; entre Windows et Linux, contenu et CRC identiques, octets compresses differents selon zlib).  Les fichiers ngjb/* d'une construction anterieure (format dossier,
        # jusqu'a la 2.5.15) sont retires : MAME lirait le dossier avant le zip.
        romdir = os.path.join(outdir, name)
        if os.path.isdir(romdir):
            for fn in os.listdir(romdir):
                if fn.startswith(name + "-") and os.path.isfile(os.path.join(romdir, fn)):
                    os.remove(os.path.join(romdir, fn))
            if not os.listdir(romdir):
                os.rmdir(romdir)
        fzip = os.path.join(outdir, name + ".zip")
        try:
            with zipfile.ZipFile(fzip + ".tmp", "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
                for fn, b, _, _, _ in files:
                    zi = zipfile.ZipInfo(fn, date_time=(2026, 1, 1, 0, 0, 0))
                    zi.compress_type, zi.external_attr = zipfile.ZIP_DEFLATED, 0o644 << 16
                    z.writestr(zi, b)
            os.replace(fzip + ".tmp", fzip)
        finally:
            if os.path.exists(fzip + ".tmp"):
                os.remove(fzip + ".tmp")
        written.append(fzip)
    sizes = {"maincpu": MB + (len(p2) if p2 else 0), "fixed": 0x40000, "audiocpu": 0x20000,
             "ymsnd:adpcma": nv * 4 * MB, "sprites": 2 * MB}
    areas = []
    for area in ("maincpu", "fixed", "audiocpu", "ymsnd:adpcma", "sprites"):
        attrs = ' width="16" endianness="big"' if area == "maincpu" else ""
        roms = "\n".join(f'\t\t\t\t<rom name="{fn}" size="0x{len(b):x}" crc="{zlib.crc32(b):08x}" '
                         f'sha1="{hashlib.sha1(b).hexdigest()}" offset="0x{off:x}"' + (f' loadflag="{fl}"' if fl else "") + "/>"
                         for fn, b, a, off, fl in files if a == area)
        areas.append(f'\t\t\t<dataarea name="{area}"{attrs} size="0x{sizes[area]:x}">\n{roms}\n\t\t\t</dataarea>')
    titles = ", ".join(g["title"] for g in pk["games"])[:200].replace("&", "and").replace("<", "").replace(">", "")
    xml = ('<?xml version="1.0"?>\n<!DOCTYPE softwarelist SYSTEM "softwarelist.dtd">\n'
           '<softwarelist name="neogeo" description="NGT Studio jukebox">\n'
           f'\t<software name="{name}">\n\t\t<description>Neo Geo Jukebox ({titles})</description>\n'
           f'\t\t<year>{time.strftime("%Y")}</year>\n\t\t<publisher>NGT Studio {VERSION}</publisher>\n'
           '\t\t<part name="cart" interface="neo_cart">\n' + "\n".join(areas) +
           '\n\t\t</part>\n\t</software>\n</softwarelist>\n')
    if "mame" in formats:
        os.makedirs(os.path.join(outdir, "hash"), exist_ok=True)
        open(os.path.join(outdir, "hash", "neogeo.xml"), "w", encoding="utf-8").write(xml)
    readme = (f"Neo Geo Jukebox built by NGT Studio {VERSION}\n\n{report}\n\n"
              f"P-ROM: {len(img) / MB:.2f} MB used, {banks} P2 bank(s) of 1 MB, each starting with a 16-byte marker\n"
              "checked by the jukebox at boot (nothing shown if all are present, else a red line 'P2 nn = FIRST MISSING BANK').\n\n"
              + ("Screen saver: rotating objects from " + ", ".join(f"{os.path.basename(p)} ({len(b[0])} frames)" for p, b in zip(box_paths, box)) + ".\n\n" if box else
                 "Screen saver: no rotating objects (disabled).\n\n")
              + ("Screen saver: \"Toasty\" ON: one of " + str(len(to)) + " portraits (drawn at random, never the same twice in a row) shows up\n"
                 "once per screen saver, bottom right, in front of everything, when the next track starts (not in LOOP\n"
                 "mode, where the track never changes).\n"
                 "Pictures: portraits of real people, all rights reserved (Aurelien / Bouz for the first one).\n"
                 + (sfx_note if sfx_note else "Toasty sound: none" + (" (switched off)." if not toasty_sfx else " (no sound in this program, none given).") + "\n")
                 + ("The built-in Toasty sound is the Mortal Kombat II shout, (c) Midway / Warner Bros.: do not distribute this cartridge.\n" if snd and not toasty_sound else "")
                 + "\n" if to else "")
              + (f"Screen saver text: \"{stext.decode().rstrip()}\" ({len(stext.rstrip())} characters).\n\n" if stext else "")
              +
              f"MAME: the set is {name}.zip (ROM files inside, like any MAME set) with the software list hash/neogeo.xml.\n"
              "Test it (put neogeo.zip in the same folder as this file):\n"
              f"  mame neogeo {name} -hashpath hash -rompath .\n\n"
              "P ROMs are word-swapped like MAME sets (load16_word_swap). C ROMs: only the graphics of the screen saver\n"
              "(BIOS font enlarged x5, checkerboard, small font, boxes). S1 = BIOS font copied from your neogeo.zip; the security block of\n"
              "your BIOS is copied into the program (the BIOS refuses a cartridge without it).\n\n"
              "Darksoft Multi: copy the folder darksoft/ngjb into the games folder of the SD card (add it to the game\n"
              "list as you do for other games). 'fpga' holds the configuration number of a real game with the same\n"
              "layout (12 = P 1 MB like aof2, 10 = P1 1 MB + P2 4 MB like kof97 / lastblad).\n"
              "NeoSD: copy neosd/ngjb.neo to the SD card.\n\n"
              "Pad: UP/DOWN track, LEFT/RIGHT game, A play/pause, B stop, C previous, D next,\n"
              "START full-screen VU meters, SELECT AUTO (chains every track then every album, endlessly; default) /\n"
              "LOOP (repeats one track) / RAND (a random track of any album, never the same twice in a row).\n"
              "Plays automatically from power-on. MVS has no SELECT button: it stays in AUTO.\n"
              "Screen saver after 5 minutes without a press (sine scroll demo screen); any press wakes it.\n\n"
              "Only tested in MAME. NOT tested on a real console, a Darksoft or a NeoSD.\n\n"
              "These files contain parts of your SNK BIOS (font, security block): keep them for your own use,\n"
              "do not distribute them. Share NGT Studio and your .ngt albums instead.\n")
    open(os.path.join(outdir, "README_jukebox.txt"), "w", encoding="utf-8").write(readme)
    open(os.path.join(outdir, "capacity.txt"), "w", encoding="utf-8").write(report + "\n")
    return report, written


# ======================================================================================
# Lecture : exemple de 30 s tel que le lecteur le joue (intro + boucles, 48 kHz, normalisé)
# ======================================================================================
def playback_pcm(path, idx=0, norm="track", seconds=30.0, start=0.0):
    meta, pcm = render_track(path, idx)
    g = gain_for(norm, meta, pcm)
    pcm = apply_gain(pcm, g)
    intro, loop = prepare_playback(pcm, meta)
    total = int((start + seconds) * OUT_RATE)
    parts, n = [intro], len(intro)
    if loop is not None and len(loop):
        while n < total:
            parts.append(loop)
            n += len(loop)
    x = np.concatenate(parts)[:total][int(start * OUT_RATE):]
    return meta, g, np.clip(np.round(x * 32768.0), -32768, 32767).astype("<i2")


def save_wav(path, pcm, rate):
    w = wave.open(path, "wb")
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(rate)
    w.writeframes(np.ascontiguousarray(pcm, dtype="<i2").tobytes())
    w.close()


# ---------------------------------------------------------------- album / stems export
def render_final(path, idx, muted=(), loops=2, fade_s=8.0, gain=1.0):
    """A finished track like on a soundtrack CD: intro + `loops` loops + fade-out, int16 stereo at 48 kHz.
    `muted` voices are silenced at register level (stems = everything muted but one voice)."""
    meta, regs, blob = load_track(path, idx)
    if muted:
        regs = mute_regs(regs, muted)
    meta, pcm = render_track(path, idx, loaded=(meta, regs, blob))
    intro, loop = prepare_playback(pcm, meta)
    if loop is None or not len(loop):
        x = intro
    else:
        nf = int(fade_s * OUT_RATE)
        tail = np.tile(loop, (nf // len(loop) + 1, 1))[:nf] * np.linspace(1.0, 0.0, nf, dtype=np.float32)[:, None]
        x = np.concatenate([intro] + [loop] * max(1, loops) + [tail])
    return meta, np.clip(np.rint(x * np.float32(gain) * 32767.0), -32768, 32767).astype("<i2")


def save_audio(path, pcm, rate, tags=None):
    """FLAC (tagged, with the soundfile module) or WAV with a RIFF INFO chunk (title, album, artist, track, comment)."""
    tags = tags or {}
    if path.lower().endswith(".flac"):
        import soundfile as sf
        with sf.SoundFile(path, "w", samplerate=rate, channels=2, format="FLAC", subtype="PCM_16") as f:
            for k in ("title", "album", "artist", "date", "comment", "tracknumber", "genre"):
                if tags.get(k):
                    try:
                        setattr(f, k, str(tags[k]))
                    except Exception:
                        pass
            f.write(np.ascontiguousarray(pcm, dtype="<i2"))
        return
    info = b""
    for cid, k in ((b"INAM", "title"), (b"IPRD", "album"), (b"IART", "artist"), (b"ITRK", "tracknumber"),
                   (b"ICRD", "date"), (b"ICMT", "comment"), (b"IGNR", "genre")):
        if tags.get(k):
            v = str(tags[k]).encode("latin-1", "replace") + b"\0"
            v += b"\0" * (len(v) & 1)
            info += cid + struct.pack("<I", len(v)) + v
    data = np.ascontiguousarray(pcm, dtype="<i2").tobytes()
    fmt = struct.pack("<HHIIHH", 1, 2, rate, rate * 4, 4, 16)
    body = b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt
    if info:
        body += b"LIST" + struct.pack("<I", 4 + len(info)) + b"INFO" + info
    body += b"data" + struct.pack("<I", len(data)) + data
    with open(path, "wb") as fh:
        fh.write(b"RIFF" + struct.pack("<I", len(body)) + body)


def export_album(ngt, outdir, fmt="flac", loops=2, fade_s=8.0, stems_of=None, muted=(), progress=print, stop=lambda: False):
    """Every track of a game as a tagged album (or, with stems_of=track index, that track split into one file per voice).
    Loudness: one gain for the whole game (as 'Per game'), so tracks and stems keep their real balance."""
    h = read_meta(ngt)
    short = _short_from_header(h["game"], h["title"])
    info = adb_lookup(short) or {}
    album = h["title"]
    artist = info.get("manufacturer") or "Neo Geo"
    year = info.get("year") or ""
    safe = lambda x: re.sub(r'[\\/:*?"<>|]+', "_", x).strip() or "untitled"
    ext = "." + fmt
    peak = int(h["game_peak"] or 0) or 32767
    gain = min(TARGET / peak, 32.0)
    done = []
    if stems_of is None:
        os.makedirs(os.path.join(outdir, safe(album)), exist_ok=True)
        for i, m in enumerate(h["tracks"]):
            if stop():
                break
            progress(f"Album: track {i + 1}/{len(h['tracks'])}…")
            _, x = render_final(ngt, i, muted, loops, fade_s, gain)
            fp = os.path.join(outdir, safe(album), f"{i + 1:02d} - {safe(m['name'])}{ext}")
            save_audio(fp, x, OUT_RATE, {"title": m["name"], "album": album, "artist": artist, "date": year,
                                         "tracknumber": f"{i + 1}/{len(h['tracks'])}", "genre": "Game",
                                         "comment": f"Neo Geo sound command 0x{m['cmd']:02X}, replayed from YM2610 registers by NGT Studio {VERSION}"})
            done.append(fp)
    else:
        m = h["tracks"][stems_of]
        meta, regs, _ = load_track(ngt, stems_of)
        act = voice_activity(regs, meta)
        voices = [v for v in range(14) if act[v].max() > 0.01 and v not in set(muted)]
        sub = os.path.join(outdir, safe(f"{m['name']} - stems"))
        os.makedirs(sub, exist_ok=True)
        for k, v in enumerate(voices):
            if stop():
                break
            progress(f"Stems: voice {k + 1}/{len(voices)} ({VOICES[v]})…")
            _, x = render_final(ngt, stems_of, [u for u in range(14) if u != v], loops, fade_s, gain)
            fp = os.path.join(sub, f"{k + 1:02d} - {safe(VOICES[v])}{ext}")
            save_audio(fp, x, OUT_RATE, {"title": f"{m['name']} [{VOICES[v]}]", "album": album, "artist": artist,
                                         "date": year, "genre": "Game", "comment": f"Stem of one YM2610 voice, NGT Studio {VERSION}"})
            done.append(fp)
    return done


# ======================================================================================
# Spectre façon années 80 (barres à LED)
# ======================================================================================
SPEC_BANDS = 32
SPEC_N = 2048
_SPEC_EDGES = np.geomspace(40.0, 16000.0, SPEC_BANDS + 1)
_SPEC_FREQ = np.fft.rfftfreq(SPEC_N, 1.0 / OUT_RATE)
_SPEC_WIN = np.hanning(SPEC_N)
_SPEC_MASK = [(_SPEC_FREQ >= _SPEC_EDGES[i]) & (_SPEC_FREQ < _SPEC_EDGES[i + 1]) for i in range(SPEC_BANDS)]
_SPEC_CENTER = np.sqrt(_SPEC_EDGES[:-1] * _SPEC_EDGES[1:])


def spectrum_levels(mono, floor_db=-66.0):
    """Niveaux 0..1 de SPEC_BANDS bandes log (40 Hz–16 kHz) pour SPEC_N échantillons mono (float, ±1).
    Sinus pleine échelle ≈ 0 dB ; léger relevé des aigus (+3 dB/octave) pour un affichage lisible."""
    x = np.zeros(SPEC_N, dtype=np.float64)
    m = np.asarray(mono, dtype=np.float64)[-SPEC_N:]
    x[SPEC_N - len(m):] = m
    mag = np.abs(np.fft.rfft(x * _SPEC_WIN)) / (SPEC_N / 4.0)
    out = np.empty(SPEC_BANDS)
    for i in range(SPEC_BANDS):
        out[i] = mag[_SPEC_MASK[i]].max() if _SPEC_MASK[i].any() else np.interp(_SPEC_CENTER[i], _SPEC_FREQ, mag)
    db = 20 * np.log10(out + 1e-9) + 3.0 * np.log2(_SPEC_CENTER / 1000.0)
    return np.clip((db - floor_db) / -floor_db, 0.0, 1.0)


# ======================================================================================
# Interface graphique : une fenêtre, deux onglets (thème sombre)
# ======================================================================================
# Palette claire « normale » : tout l'affichage (y compris le spectre) en dérive.
PAL = {"bg": "#f0f0f0", "panel": "#e3e3e3", "field": "#ffffff", "fg": "#1e1e1e", "muted": "#6b6b6b",
       "accent": "#0f6cbd", "accent_hi": "#2b88d8", "on_accent": "#ffffff", "ok": "#2e7d32", "err": "#c62828",
       "line": "#c4c4c4",
       # affichage (canvas) : fond, LED éteintes, LED allumées bas/milieu/haut, crête, curseur
       "canvas": "#fafafa", "led_off": "#e4e7eb", "led_lo": "#2f9e55", "led_mid": "#e0a800", "led_hi": "#d6403a",
       "cap": "#2b2f36", "cursor": "#2b2f36", "prog_bg": "#d9dde3", "prog_loop": "#b9d4f0",
       "voice_bg": "#e9ecf0", "mute_bg": "#f6dada", "kb_white": "#ffffff", "kb_black": "#2b2b2b", "kb_line": "#b9bec6", "voices": ["#1e88e5"] * 4 + ["#43a047"] * 3 + ["#fb8c00"] * 6 + ["#d81b60"]}
FONT = ("Segoe UI", 10) if os.name == "nt" else ("DejaVu Sans", 10)
FONT_B = FONT[:1] + (FONT[1], "bold")
FONT_S = FONT[:1] + (FONT[1] - 2,)
MONO = ("Consolas", 9) if os.name == "nt" else ("DejaVu Sans Mono", 9)
SETTINGS = os.path.join(os.path.expanduser("~"), ".ngt_studio.json")


def load_settings():
    try:
        return json.load(open(SETTINGS, encoding="utf-8"))
    except Exception:
        return {}


def save_settings(d):
    try:
        json.dump(d, open(SETTINGS, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    except Exception:
        pass


def open_path(p):
    """Ouvre un dossier dans l'explorateur du système."""
    try:
        if os.name == "nt":
            os.startfile(p)                                                  # noqa: S606
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", p])
    except Exception:
        pass


def fmt_time(s):
    s = max(0, int(s))
    return f"{s // 60:d}:{s % 60:02d}"


def apply_theme(root):
    from tkinter import ttk
    root.configure(bg=PAL["bg"])
    root.tk_setPalette(background=PAL["bg"], foreground=PAL["fg"], activeBackground=PAL["line"], activeForeground=PAL["fg"],
                       highlightBackground=PAL["bg"], selectBackground=PAL["accent"], selectForeground=PAL["on_accent"],
                       troughColor=PAL["field"])
    st = ttk.Style(root)
    try:
        st.theme_use("clam")
    except Exception:
        pass
    P = PAL
    st.configure(".", background=P["bg"], foreground=P["fg"], fieldbackground=P["field"], font=FONT,
                 bordercolor=P["line"], lightcolor=P["panel"], darkcolor=P["panel"], troughcolor=P["field"],
                 focuscolor=P["bg"], insertcolor=P["fg"])
    st.configure("TFrame", background=P["bg"])
    st.configure("Panel.TFrame", background=P["panel"])
    st.configure("TLabel", background=P["bg"], foreground=P["fg"])
    st.configure("Muted.TLabel", foreground=P["muted"], font=FONT_S)
    st.configure("Title.TLabel", foreground=P["accent"], font=FONT_B)
    st.configure("TLabelframe", background=P["bg"], bordercolor=P["line"])
    st.configure("TLabelframe.Label", background=P["bg"], foreground=P["accent"], font=FONT_B)
    st.configure("TButton", background=P["panel"], foreground=P["fg"], padding=(10, 5), borderwidth=1)
    st.map("TButton", background=[("active", P["line"]), ("disabled", P["bg"])],
           foreground=[("disabled", P["muted"])])
    st.configure("Accent.TButton", background=P["accent"], foreground=P["on_accent"], font=FONT_B)
    st.map("Accent.TButton", background=[("active", P["accent_hi"]), ("disabled", P["line"])],
           foreground=[("disabled", P["muted"])])
    for w in ("TCheckbutton", "TRadiobutton"):
        st.configure(w, background=P["bg"], foreground=P["fg"])
        st.map(w, background=[("active", P["bg"])], foreground=[("active", P["accent_hi"])])
    st.configure("TEntry", fieldbackground=P["field"], foreground=P["fg"], padding=4)
    st.map("TCombobox", fieldbackground=[("readonly", P["field"])], foreground=[("readonly", P["fg"])],
           selectbackground=[("readonly", P["field"])], selectforeground=[("readonly", P["fg"])],
           background=[("readonly", P["panel"])], arrowcolor=[("readonly", P["fg"])])
    root.option_add("*TCombobox*Listbox.background", P["field"])
    root.option_add("*TCombobox*Listbox.foreground", P["fg"])
    root.option_add("*TCombobox*Listbox.selectBackground", P["accent"])
    root.option_add("*TCombobox*Listbox.selectForeground", P["on_accent"])
    st.configure("TSpinbox", fieldbackground=P["field"], foreground=P["fg"], arrowcolor=P["fg"])
    st.configure("TNotebook", background=P["bg"], borderwidth=0, tabmargins=(4, 4, 4, 0))
    st.configure("TNotebook.Tab", background=P["panel"], foreground=P["muted"], padding=(16, 7), font=FONT_B)
    st.map("TNotebook.Tab", background=[("selected", P["bg"])], foreground=[("selected", P["accent"])])
    st.configure("Treeview", background=P["field"], fieldbackground=P["field"], foreground=P["fg"],
                 rowheight=24, borderwidth=0)
    st.map("Treeview", background=[("selected", P["accent"])], foreground=[("selected", P["on_accent"])])
    st.configure("Treeview.Heading", background=P["panel"], foreground=P["muted"], font=FONT_B, relief="flat")
    st.map("Treeview.Heading", background=[("active", P["line"])])
    st.configure("Horizontal.TProgressbar", background=P["accent"], troughcolor=P["field"], borderwidth=0)
    st.configure("Horizontal.TScale", background=P["accent"], troughcolor=P["field"], bordercolor=P["line"], sliderthickness=14)
    st.map("Horizontal.TScale", background=[("active", P["accent_hi"])])
    for sb in ("TScrollbar", "Vertical.TScrollbar", "Horizontal.TScrollbar"):
        st.configure(sb, background=P["line"], troughcolor=P["field"], arrowcolor=P["muted"],
                     lightcolor=P["line"], darkcolor=P["line"], bordercolor=P["field"], gripcount=0)
        st.map(sb, background=[("active", P["muted"]), ("!active", P["line"])])


def _hue_hex(h, s=0.75, v=0.95):
    import colorsys
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


def _mix_hex(a, b, t):
    """Colour between a (t=0) and b (t=1)."""
    t = max(0.0, min(1.0, float(t)))
    ca, cb = (int(a[i:i + 2], 16) for i in (1, 3, 5)), (int(b[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(int(x + (y - x) * t) for x, y in zip(ca, cb))


def _dim_hex(c, f):
    return _mix_hex("#000000", c, f)


_AMBIENT = {}


def ambient_color(path):
    """A bright accent colour taken from the dominant vivid hue of the game picture (cached)."""
    if not path:
        return "#4fc3f7"
    if path in _AMBIENT:
        return _AMBIENT[path]
    col = "#4fc3f7"
    try:
        from PIL import Image
        hsv = np.asarray(Image.open(path).convert("RGB").resize((48, 48)).convert("HSV")).reshape(-1, 3).astype(np.float32)
        m = (hsv[:, 1] > 110) & (hsv[:, 2] > 90)
        if m.sum() > 20:
            hh, w = hsv[m, 0], hsv[m, 1] * hsv[m, 2]
            hist = np.bincount((hh / 256 * 18).astype(int), weights=w, minlength=18)
            b = int(np.argmax(hist))
            hue = float(np.average(hh[(hh / 256 * 18).astype(int) == b])) / 255.0
            col = _hue_hex(hue, 0.70, 1.0)
    except Exception as ex:
        dlog(f"ambient: {ex}")
    _AMBIENT[path] = col
    return col


def _led_color(s, n):
    r = s / (n - 1)
    return PAL["led_lo"] if r < 0.6 else (PAL["led_mid"] if r < 0.85 else PAL["led_hi"])


# Musique, jingle ou bruitage : l'outil l'analyse lui-même (notes jouées, voies, hauteurs distinctes, durée, boucle).
KEEP_PRESETS = [("Automatic: music + jingles (recommended)", "auto"),
                ("Music only (also drops jingles)", "music"),
                ("Keep everything (including SFX and ambience)", "all")]


class ExtractTab:
    """Onglet « Extraire » : ROM (.zip ou dossier) -> un fichier .ngt par jeu."""

    def __init__(self, root, parent, settings, on_done=None):
        import tkinter as tk
        from tkinter import ttk
        self.tk = tk
        self.root, self.settings, self.on_done = root, settings, on_done
        self.q = queue.Queue()
        self.stop_flag = False
        self.running = False
        self.out_dir = ""
        self.v_src = tk.StringVar(value=settings.get("src", ""))
        self.v_out = tk.StringVar(value=settings.get("out", ""))
        self.v_min = tk.StringVar(value=settings.get("sel", KEEP_PRESETS[0][0]))
        self.v_pre = tk.StringVar(value=settings.get("pre", "auto"))
        self.v_work = tk.StringVar(value=str(settings.get("workers") or max(1, (os.cpu_count() or 2) - 1)))
        self.v_wav = tk.BooleanVar(value=bool(settings.get("rip_wav", False)))
        self.v_norm = tk.BooleanVar(value=bool(settings.get("normalize", False)))
        self.v_minlen = tk.StringVar(value=str(settings.get("short_min", 45)))
        self.short_fixed = None
        self.v_info = tk.StringVar(value="Pick a ROM (.zip) or a ROM folder, then start the extraction.")
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(3, weight=1)
        parent.rowconfigure(4, weight=2)

        f = ttk.LabelFrame(parent, text=" Source and destination ", padding=10)
        f.grid(row=0, column=0, sticky="we", padx=10, pady=(10, 4))
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="Neo Geo ROM").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(f, textvariable=self.v_src).grid(row=0, column=1, sticky="we", padx=8)
        ttk.Button(f, text="A .zip…", command=self.pick_zip).grid(row=0, column=2, padx=2)
        ttk.Button(f, text="A folder…", command=self.pick_dir).grid(row=0, column=3, padx=2)
        ttk.Label(f, text="Output folder").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(f, textvariable=self.v_out).grid(row=1, column=1, sticky="we", padx=8)
        ttk.Button(f, text="Browse…", command=self.pick_out).grid(row=1, column=2, columnspan=2, sticky="we", padx=2)
        self.v_src.trace_add("write", lambda *_: self.count_roms())

        o = ttk.LabelFrame(parent, text=" Options ", padding=10)
        o.grid(row=1, column=0, sticky="we", padx=10, pady=4)
        o.columnconfigure(1, weight=1)
        ttk.Label(o, text="Tracks to keep").grid(row=0, column=0, sticky="w")
        ttk.Combobox(o, textvariable=self.v_min, values=[p[0] for p in KEEP_PRESETS], state="readonly").grid(
            row=0, column=1, columnspan=5, sticky="we", padx=(8, 0), pady=2)
        ttk.Label(o, text="Driver prelude").grid(row=1, column=0, sticky="w", pady=2)
        pf = ttk.Frame(o)
        pf.grid(row=1, column=1, sticky="w", padx=(8, 0))
        ttk.Entry(pf, textvariable=self.v_pre, width=9).pack(side="left")
        ttk.Label(pf, text="  auto = detection; otherwise e.g. 7 or 3,7", style="Muted.TLabel").pack(side="left")
        ttk.Label(o, text="Processes").grid(row=1, column=2, sticky="e", padx=(18, 6))
        ttk.Spinbox(o, from_=1, to=64, width=4, textvariable=self.v_work).grid(row=1, column=3, sticky="w")
        ttk.Checkbutton(o, text="Also write .wav / .raw / .json per track", variable=self.v_wav).grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Checkbutton(o, text="Normalize these .wav / .raw (peak -1 dBFS)", variable=self.v_norm).grid(
            row=2, column=3, columnspan=3, sticky="w", pady=(6, 0))
        mf = ttk.Frame(o)
        mf.grid(row=3, column=0, columnspan=6, sticky="w", pady=(6, 0))
        ttk.Label(mf, text="Short tracks: under").pack(side="left")
        ttk.Spinbox(mf, from_=0, to=600, increment=10, width=5, textvariable=self.v_minlen).pack(side="left", padx=4)
        ttk.Label(mf, text="s (one loop included) they are skipped by default; you are asked during the extraction"
                           " (0 = no limit)", style="Muted.TLabel").pack(side="left")
        ttk.Label(o, text="Every sound found is analysed (notes, voices, duration, loop) to tell music, jingles and SFX apart.", style="Muted.TLabel").grid(
            row=4, column=0, columnspan=6, sticky="w", pady=(6, 0))

        b = ttk.Frame(parent)
        b.grid(row=2, column=0, sticky="we", padx=10, pady=4)
        b.columnconfigure(3, weight=1)
        self.btn = ttk.Button(b, text="▶  Extract the music", style="Accent.TButton", command=self.start)
        self.btn.grid(row=0, column=0)
        self.btn_stop = ttk.Button(b, text="■ Stop", command=self.stop, state="disabled")
        self.btn_stop.grid(row=0, column=1, padx=6)
        self.btn_open = ttk.Button(b, text="Open output folder", command=self.open_out)
        self.btn_open.grid(row=0, column=2)
        self.pb = ttk.Progressbar(b, mode="determinate")
        self.pb.grid(row=0, column=3, sticky="we", padx=12)
        ttk.Label(b, textvariable=self.v_info, style="Muted.TLabel").grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))

        cols = ("pistes", "note")
        self.tree = ttk.Treeview(parent, columns=cols, show="tree headings", height=5)
        self.tree.heading("#0", text="Game", anchor="w"); self.tree.column("#0", width=220)
        self.tree.heading("pistes", text="Tracks", anchor="center"); self.tree.column("pistes", width=70, anchor="center")
        self.tree.heading("note", text="Result", anchor="w"); self.tree.column("note", width=640)
        self.tree.grid(row=3, column=0, sticky="nsew", padx=10, pady=4)
        self.tree.tag_configure("ko", foreground=PAL["err"])
        lf = ttk.Frame(parent)
        lf.grid(row=4, column=0, sticky="nsew", padx=10, pady=(4, 10))
        lf.columnconfigure(0, weight=1); lf.rowconfigure(0, weight=1)
        self.txt = tk.Text(lf, height=10, bg=PAL["field"], fg=PAL["fg"], insertbackground=PAL["fg"], relief="flat",
                           font=MONO, borderwidth=0, highlightthickness=0, state="disabled", wrap="word")
        tsb = ttk.Scrollbar(lf, orient="vertical", command=self.txt.yview)
        self.txt.configure(yscrollcommand=tsb.set)
        self.txt.grid(row=0, column=0, sticky="nsew"); tsb.grid(row=0, column=1, sticky="ns")
        self.count_roms()
        self.poll()

    # -- sélection
    def pick_zip(self):
        from tkinter import filedialog
        p = filedialog.askopenfilename(title="Choose a Neo Geo ROM", filetypes=[("Neo Geo ROM (zip)", "*.zip")])
        if p:
            self.v_src.set(p)

    def pick_dir(self):
        from tkinter import filedialog
        p = filedialog.askdirectory(title="Choose a folder of ROMs (.zip)")
        if p:
            self.v_src.set(p)

    def pick_out(self):
        from tkinter import filedialog
        p = filedialog.askdirectory(title="Choose the output folder")
        if p:
            self.v_out.set(p)

    def count_roms(self):
        if self.running:
            return
        s = self.v_src.get().strip()
        if os.path.isfile(s) and s.lower().endswith(".zip"):
            self.v_info.set("1 ROM selected.")
        elif os.path.isdir(s):
            n = len([f for f in os.listdir(s) if f.lower().endswith(".zip")])
            self.v_info.set(f"{n} ROM (.zip) found in this folder." if n else "No .zip in this folder.")
        elif s:
            self.v_info.set("Path not found.")

    def open_out(self):
        p = self.out_dir or self.v_out.get().strip()
        if p and os.path.isdir(p):
            open_path(p)

    def log(self, msg):
        self.txt.configure(state="normal")
        self.txt.insert("end", msg + "\n")
        self.txt.see("end")
        self.txt.configure(state="disabled")

    # -- exécution
    def worker(self, src, out, opts):
        try:
            scan_dir(src, out, opts, lambda m: self.q.put(("log", m)), lambda: self.stop_flag,
                     lambda r, n, t: self.q.put(("res", r, n, t)))
        except Exception as ex:
            self.q.put(("log", f"ERROR: {ex}"))
        self.q.put(("done", out))

    def start(self):
        from tkinter import messagebox
        src = self.v_src.get().strip()
        if not (os.path.isfile(src) or os.path.isdir(src)):
            messagebox.showwarning("Missing source", "Pick a ROM (.zip) or a folder containing ROMs.")
            return
        out = self.v_out.get().strip()
        if not out:
            out = os.path.join(HERE, "ngt_output")
            self.v_out.set(out)
        try:
            pre = self.v_pre.get().strip().lower()
            opts = {"keep": dict(KEEP_PRESETS).get(self.v_min.get(), "auto"), "wav": self.v_wav.get(), "raw": self.v_wav.get(),
                    "normalize": self.v_norm.get(), "workers": max(1, int(self.v_work.get())),
                    "prelude": "auto" if pre in ("", "auto") else [int(x, 0) for x in pre.split(",")],
                    "min_len": max(0.0, float(self.v_minlen.get() or 0)), "short": "ask", "ask_short": self.ask_short}
        except ValueError:
            messagebox.showerror("Invalid value", "Check the prelude (e.g. 7 or 3,7), the number of processes and the "
                                                  "short-track length.")
            return
        self.short_fixed = None
        self.settings.update(src=src, out=out, sel=self.v_min.get(), pre=self.v_pre.get(), short_min=opts["min_len"])
        save_settings(self.settings)
        self.stop_flag, self.running = False, True
        self.n_done = 0
        self.tree.delete(*self.tree.get_children())
        self.btn.configure(state="disabled"); self.btn_stop.configure(state="normal")
        self.pb.configure(mode="indeterminate"); self.pb.start(12)
        self.v_info.set("Extraction in progress… (several minutes per game, the Z80 and YM2610 are being emulated)")
        self.log(f"— Extraction: {src}  →  {out}")
        threading.Thread(target=self.worker, args=(src, out, opts), daemon=True).start()

    def stop(self):
        self.stop_flag = True
        self.v_info.set("Stop requested: the current game finishes first…")

    # -- pistes courtes : question posée pendant l'extraction (appelée depuis le fil d'extraction)
    def ask_short(self, game, n, n_loop, min_len):
        if self.short_fixed:
            return self.short_fixed
        ev, box = threading.Event(), {}
        self.q.put(("ask", game, n, n_loop, min_len, ev, box))
        while not ev.wait(0.2):
            if self.stop_flag:
                return "skip"
        if box.get("all"):
            self.short_fixed = box.get("p", "loops")
        return box.get("p", "loops")

    def short_dialog(self, game, n, n_loop, min_len, ev, box):
        tk = self.tk
        from tkinter import ttk
        w = tk.Toplevel(self.root)
        w.title("Short tracks")
        w.transient(self.root)
        w.configure(bg=PAL["bg"])
        f = ttk.Frame(w, padding=16)
        f.pack(fill="both", expand=True)
        title = game_title(game, None, online=False)
        msg = (f"{title}: {n} track(s) shorter than {min_len:.0f} s were found.\n\n"
               + (f"{n_loop} of them loop: that is game music whose loop is short (some stage themes loop "
                  f"in less than {min_len:.0f} s). Skipping them loses that music.\n\n" if n_loop else
                  "None of them loops: they are jingles or short stingers.\n\n")
               + "What should be done with them?")
        ttk.Label(f, text=msg, wraplength=460, justify="left").pack(anchor="w")
        v_all = tk.BooleanVar(value=True)
        left = {"s": 30}
        v_cd = tk.StringVar()

        def done(p):
            box.update(p=p, all=v_all.get())
            try:
                w.grab_release()
            except Exception:
                pass
            w.destroy()
            ev.set()
        bf = ttk.Frame(f)
        bf.pack(fill="x", pady=(14, 6))
        # defaut (2.5.19) : garder celles qui bouclent (musique a boucle courte : Puzzle De Pon, Windjammers...) ;
        # sans boucle, c'est la meme chose que les ignorer
        b1 = ttk.Button(bf, text=("Keep the looping ones (recommended)" if n_loop else "Skip them"), style="Accent.TButton",
                        command=lambda: done("loops"))
        b1.pack(side="left")
        if n_loop:
            ttk.Button(bf, text="Skip them all", command=lambda: done("skip")).pack(side="left", padx=6)
        ttk.Button(bf, text="Keep them all", command=lambda: done("keep")).pack(side="left", padx=(6 if not n_loop else 0, 0))
        ttk.Checkbutton(f, text="Same answer for the next games of this extraction", variable=v_all).pack(anchor="w")
        ttk.Label(f, textvariable=v_cd, style="Muted.TLabel").pack(anchor="w", pady=(6, 0))

        def tick():
            if not w.winfo_exists():
                return
            if left["s"] <= 0:
                done("loops")
                return
            v_cd.set(f"No answer in {left['s']} s: " + ("the looping ones are kept, the others skipped." if n_loop else "skipped."))
            left["s"] -= 1
            w.after(1000, tick)
        w.protocol("WM_DELETE_WINDOW", lambda: done("loops"))
        w.bind("<Return>", lambda e: done("loops"))
        tick()
        b1.focus_set()
        try:
            w.grab_set()
        except Exception:
            pass

    def poll(self):
        try:
            while True:
                m = self.q.get_nowait()
                if m[0] == "log":
                    self.log(m[1])
                elif m[0] == "ask":
                    self.short_dialog(*m[1:])
                elif m[0] == "res":
                    r, n, t = m[1], m[2], m[3]
                    self.n_done = n
                    self.tree.insert("", "end", text=r["game"], values=(len(r["tracks"]), r["note"]),
                                     tags=("ko",) if not r["tracks"] else ())
                    self.v_info.set(f"{n} / {t} game(s) processed…")
                else:
                    self.running = False
                    self.out_dir = m[1]
                    self.pb.stop(); self.pb.configure(mode="determinate", value=100)
                    self.btn.configure(state="normal"); self.btn_stop.configure(state="disabled")
                    self.v_info.set(f"Done: {self.n_done} game(s). The tracks are in the Player tab.")
                    self.log("— Done.")
                    if self.on_done and self.n_done:
                        self.on_done(m[1])
        except queue.Empty:
            pass
        self.root.after(100, self.poll)


# ======================================================================================
# Screenshots shown next to the graphs (slideshow in a square)
# ======================================================================================
PICS_BASE = "https://thumbnails.libretro.com/"            # official libretro thumbnail server: plain directory listings, no key, no API
PICS_PLATFORMS = ("SNK - Neo Geo", "SNK - Neo Geo CD")    # two independent sets of screenshots of the same games
PICS_KINDS = ("Named_Snaps", "Named_Titles")              # in-game screenshot, title screen
PICS_INDEX_CACHE = os.path.join(os.path.expanduser("~"), ".ngt_studio_pics_index.json")
PICS_PER_KIND = 2                                         # NGH/NGM variants of a game are near-duplicates: keep a couple
PICS_MAX_GAMES = 40


def _http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "NGT-Studio/" + VERSION})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _norm_title(t):
    t = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", t.lower())
    t = re.sub(r"[^a-z0-9]+", " ", t).strip()
    return re.sub(r"^the ", "", t)


class PicBank:
    """Screenshots + full names of the loaded games.  Sources: (1) your own images in the `pictures` folder next to the script
    (never deleted); (2) thumbnails.libretro.com (screenshots named after the games) and (3) the Arcade Database (which also
    decodes ROM short names such as 'kof98' into full titles), downloaded into a temporary folder that is deleted when the
    program closes.  No key, no scraping of search engines."""

    def __init__(self):
        self.cache = tempfile.mkdtemp(prefix="ngt_pics_")
        atexit.register(self.close)
        self._purge_stale()
        self.by_short = {}                 # ROM short name -> [image paths]
        self.decoded = {}                  # ROM short name -> full title (found online / in the cache)
        self.index = None                  # libretro listing
        self.lock = threading.Lock()
        self.stop = False
        self.queue = []
        self.worker = None
        self.state = "idle"                # idle | index | fetching | ok | offline
        self.pending = set()

    @staticmethod
    def _purge_stale():
        try:
            tmp, now = tempfile.gettempdir(), time.time()
            for fn in os.listdir(tmp):
                fp = os.path.join(tmp, fn)
                if fn.startswith("ngt_pics_") and os.path.isdir(fp) and now - os.path.getmtime(fp) > 3600:
                    shutil.rmtree(fp, ignore_errors=True)         # leftovers of a crashed run
        except OSError:
            pass

    def close(self):
        self.stop = True
        shutil.rmtree(self.cache, ignore_errors=True)

    def user_images(self):
        d = os.path.join(HERE, "pictures")
        try:
            return sorted(os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp")))
        except OSError:
            return []

    def images_for(self, short=None):
        with self.lock:
            if short and self.by_short.get(short):
                return list(self.by_short[short])
            allp = [p for v in self.by_short.values() for p in v]
        return allp + self.user_images()

    def request(self, items):
        """items: [(ROM short name, title)].  Runs in the background; safe to call again."""
        new = [it for it in dict.fromkeys(items) if it[0] not in self.pending][:PICS_MAX_GAMES]
        for it in new:
            self.pending.add(it[0])
        if not new:
            return
        self.queue.extend(new)
        if self.worker is None or not self.worker.is_alive():
            self.worker = threading.Thread(target=self._run, daemon=True)
            self.worker.start()

    def _load_index(self):
        """-> [(segments, name, platform, kind, filename)], from a 7-day local cache or the 4 directory listings."""
        try:
            c = json.load(open(PICS_INDEX_CACHE, encoding="utf-8"))
            if time.time() - c["t"] < 7 * 86400 and c.get("v") == 1 and c["e"]:
                return [(set(e[0]), e[1], e[2], e[3], e[4]) for e in c["e"]]
        except Exception:
            pass
        entries = self._fetch_index()
        try:
            json.dump({"t": time.time(), "v": 1, "e": [[sorted(e[0]), *e[1:]] for e in entries]},
                      open(PICS_INDEX_CACHE, "w", encoding="utf-8"))
        except OSError:
            pass
        return entries

    def _fetch_index(self):
        """Reads the 4 directory listings (Apache index pages) -> [(segments, name, platform, kind, filename)]."""
        import html
        entries = []
        for plat in PICS_PLATFORMS:
            for kind in PICS_KINDS:
                url = PICS_BASE + urllib.parse.quote(plat) + "/" + kind + "/"
                try:
                    page = _http_get(url, 40).decode("utf8", "replace")
                except Exception as ex:
                    dlog(f"pics: listing failed {plat}/{kind}: {ex}")
                    continue
                for href in re.findall(r'href="([^"?/][^"]*\.png)"', page):
                    name = html.unescape(urllib.parse.unquote(href))[:-4]
                    # "Art of Fighting 2 _ Ryuuko no Ken 2 (NGH-056)": " _ " separates alternative names of one game
                    segs = {_norm_title(x) for x in re.split(r" _ ", name)} - {""}
                    entries.append((segs, _norm_title(name), plat, kind, name + ".png"))
        if not entries:
            raise RuntimeError("no listing could be read from " + PICS_BASE)
        return entries

    def _match(self, title):
        """-> [(platform, kind, filename)] for the title: exact alternative-name match, else same words at the start."""
        key = _norm_title(title)
        if not key:
            return []
        hits = [e for e in self.index if key in e[0]]
        if not hits:
            kw = key.split()
            hits = [e for e in self.index if e[1].split()[:len(kw)] == kw
                    and not (len(e[1].split()) > len(kw) and re.fullmatch(r"\d+|[ivx]+", e[1].split()[len(kw)]))]   # not a sequel
            if hits:                                         # "Art of Fighting" must not pick "Art of Fighting 3": shortest name only
                plat = next(p for p in PICS_PLATFORMS if any(e[2] == p for e in hits))      # prefer the Neo Geo (cartridge) set
                hits = [e for e in hits if e[2] == plat]
                m = min(len(e[1]) for e in hits)
                hits = [e for e in hits if len(e[1]) <= m + 12]
        out, count = [], {}
        for e in hits:
            k = (e[2], e[3])
            if count.get(k, 0) < PICS_PER_KIND:
                count[k] = count.get(k, 0) + 1
                out.append((e[2], e[3], e[4]))
        return out

    def _save(self, url, short, tag):
        fp = os.path.join(self.cache, "%s_%s.png" % (re.sub(r"\W+", "_", short)[:40], tag))
        data = _http_get(url)
        if not data[:4] == b"\x89PNG" and not data[:2] == b"\xff\xd8":
            raise ValueError("not an image")
        open(fp, "wb").write(data)
        return fp

    def _run(self):
        online_ok = False
        try:
            self.state = "index"
            try:
                self.index = self._load_index()
                online_ok = True
                dlog(f"pics: index loaded, {len(self.index)} files")
            except Exception as ex:
                self.index = []
                dlog(f"pics: libretro unavailable: {ex}")
            self.state = "fetching"
            while self.queue and not self.stop:
                short, title = self.queue.pop(0)
                info = adb_lookup(short)                      # False = network error, None = unknown, dict = found
                if info:
                    online_ok = True
                    self.decoded[short] = info["title"]
                    keys = list(info["alts"])
                    if info["cloneof"]:                       # a clone/bootleg: its parent usually has the screenshots
                        par = adb_lookup(info["cloneof"])
                        if par:
                            keys += par["alts"]
                else:
                    keys = []
                keys += [GAME_TITLES.get(short) or "", title]
                hit = []
                for k in keys:
                    hit = self._match(k) if (k and self.index) else []
                    if hit:
                        break
                got = []
                for n, (plat, kind, fname) in enumerate(hit):
                    try:
                        url = PICS_BASE + urllib.parse.quote(plat) + "/" + kind + "/" + urllib.parse.quote(fname)
                        got.append(self._save(url, short, "l%d" % n))
                    except Exception as ex:
                        dlog(f"pics: download failed for '{short}' ({plat}/{kind}): {ex}")
                for tag, key in (("a_ingame", "ingame"), ("a_title", "titleimg")):
                    if info and info.get(key):
                        try:
                            got.append(self._save(info[key], short, tag))
                        except Exception as ex:
                            dlog(f"pics: ADB image failed for '{short}' ({key}): {ex}")
                if not got:
                    dlog(f"pics: no picture for '{short}' ({title}); tried {keys}")
                with self.lock:
                    self.by_short[short] = got
            self.state = "ok" if online_ok else "offline"
        except Exception as ex:
            dlog(f"pics: online source unavailable: {ex}")
            self.state = "offline"


def fit_square(path, side, bg):
    """Image file -> RGB PIL image side x side (letterboxed on the background colour), or None."""
    try:
        from PIL import Image
        im = Image.open(path).convert("RGB")
        k = min(side / im.width, side / im.height)
        im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS)
        out = Image.new("RGB", (side, side), bg)
        out.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
        return out
    except Exception as ex:
        dlog(f"pics: cannot read {path}: {ex}")
        return None


class PlayerTab:
    """Onglet « Lecteur » : liste jeux/pistes, lecture avec boucle, spectre à LED, voies."""
    BANDS = SPEC_BANDS
    STRIP_ROW = 4

    def __init__(self, root, parent, settings, player=None):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.root, self.settings = tk, root, settings
        self.player = player or Player()
        self.q = queue.Queue()
        self.files, self.meta, self.cache = [], {}, {}
        self.prep, self.key_locks, self.cache_lock = {}, {}, threading.Lock()
        self.muted = set()                # voices muted by the mixer (0-13)
        self.notes, self.notes_cache = None, {}
        self.kb_on = {}
        self.iid_ft, self.ft_iid, self.game_iid, self.load_gen = {}, {}, {}, 0
        self.cur, self.req, self.act = None, 0, None
        self.v_norm = tk.StringVar(value=settings.get("norm", "game"))
        self.v_vol = tk.DoubleVar(value=settings.get("vol", 80))
        old = settings.get("loops") or (LOOP_CHOICES[0] if settings.get("autoloop", True) else LOOP_CHOICES[1])
        self.v_loops = tk.StringVar(value=old if old in LOOP_CHOICES else LOOP_CHOICES[0])
        self.v_next = tk.BooleanVar(value=settings.get("autonext", False))
        self.comp_t0 = None
        self.v_pics = tk.BooleanVar(value=settings.get("pics", True))
        self.pics = PicBank()
        self.title_of, self.short_of = {}, {}
        self.decoded_seen = 0
        self.slide = {"cur": None, "prev": None, "t0": 0.0, "path": None, "list": [], "i": -1, "next_at": 0.0, "photo": None,
                      "side": 0, "cache": {}}
        self.pic_box = None

        def warm():                      # cold imports / first launch of the engine are slow on some PCs (antivirus)
            t = time.time()
            try:
                import sounddevice                             # noqa: F401
                _rs_blocks(2000, 2331)                         # filtre de rééchantillonnage (~0,1 s)
                find_engine()
            except Exception as ex:
                dlog(f"warm-up: {ex}")
            dlog(f"warm-up done in {time.time()-t:.1f}s")
        threading.Thread(target=warm, daemon=True).start()
        self.v_status = tk.StringVar(value="Open a folder of .ngt files (or extract a ROM in the Extract tab).")
        self.spec = np.zeros(self.BANDS)
        self.peak = np.zeros(self.BANDS)
        self.decay = np.zeros(14)
        self.ids = None
        self.img = None
        self.was_playing = False
        self.cfg_job = None
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=0)
        parent.rowconfigure(3, weight=1)

        top = ttk.Frame(parent, padding=(10, 8, 10, 2))
        top.grid(row=0, column=0, sticky="we")
        ttk.Button(top, text="Open a folder…", command=self.choose_dir).pack(side="left")
        ttk.Button(top, text="Open a .ngt…", command=self.choose_file).pack(side="left", padx=4)
        ttk.Label(top, text="   Auto volume:").pack(side="left")
        for txt, val in (("None", "none"), ("Per track", "track"), ("Per game", "game")):
            ttk.Radiobutton(top, text=txt, value=val, variable=self.v_norm, command=self.norm_changed).pack(side="left", padx=3)
        ttk.Label(top, text="    Volume").pack(side="left")
        ttk.Scale(top, from_=0, to=100, variable=self.v_vol, length=120, command=self.vol_changed).pack(side="left", padx=6)
        box = ttk.Frame(parent, padding=(10, 4))
        box.grid(row=1, column=0, sticky="we")
        box.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(box, columns=("duree", "boucle", "etat"), show="tree headings", height=7, selectmode="browse")
        for c, t, w, a in (("#0", "Game / track", 360, "w"), ("duree", "Length", 70, "e"), ("boucle", "Loop", 170, "w"),
                           ("etat", "Details", 170, "w")):
            self.tree.heading(c, text=t, anchor=a)
            self.tree.column(c, width=w, anchor=a)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.grid(row=0, column=0, sticky="we"); sb.grid(row=0, column=1, sticky="ns")
        self.tree.tag_configure("ko", foreground=PAL["err"])
        self.tree.tag_configure("game", foreground=PAL["accent"], font=FONT_B)
        self.tree.bind("<Double-1>", lambda e: self.play_sel())
        self.tree.bind("<Return>", lambda e: self.play_sel())

        ctl = ttk.Frame(parent, padding=(10, 4))
        ctl.grid(row=2, column=0, sticky="we")
        self.btn_prev = ttk.Button(ctl, text="⏮", width=3, command=lambda: self.step(-1)); self.btn_prev.pack(side="left")
        self.btn_play = ttk.Button(ctl, text="▶ Play", width=9, style="Accent.TButton", command=self.play_or_pause)
        self.btn_play.pack(side="left", padx=4)
        ttk.Button(ctl, text="■", width=3, command=self.stop).pack(side="left")
        self.btn_next = ttk.Button(ctl, text="⏭", width=3, command=lambda: self.step(1)); self.btn_next.pack(side="left", padx=4)
        ttk.Label(ctl, text="Loops").pack(side="left", padx=(16, 3))
        self.cb_loop = ttk.Combobox(ctl, textvariable=self.v_loops, values=LOOP_CHOICES, state="readonly", width=12)
        self.cb_loop.pack(side="left", padx=(0, 6))
        self.cb_loop.bind("<<ComboboxSelected>>", lambda e: self.opts_changed())
        ttk.Checkbutton(ctl, text="Next track at end", variable=self.v_next, command=self.opts_changed).pack(side="left", padx=2)
        ttk.Checkbutton(ctl, text="Screenshots", variable=self.v_pics, command=self.pics_toggled).pack(side="left", padx=(12, 2))
        ttk.Button(ctl, text="⛶ Visuals", command=self.fs_open).pack(side="left", padx=(10, 0))

        ttk.Button(ctl, text="30 s sample…", command=lambda: self.export(True)).pack(side="right")
        ttk.Button(ctl, text="Export as WAV…", command=lambda: self.export(False)).pack(side="right", padx=4)
        ttk.Button(ctl, text="Album / stems…", command=self.album_dialog).pack(side="right")

        self.cv = tk.Canvas(parent, height=400, bg=PAL["canvas"], highlightthickness=1, highlightbackground=PAL["line"])
        self.cv.grid(row=3, column=0, sticky="nsew", padx=10, pady=4)
        self.cv.bind("<Configure>", self.on_configure)
        self.cv.bind("<Button-1>", self.on_click)
        self.cv.bind("<Double-Button-1>", self.on_dbl)
        self.cv.bind("<Button-3>", lambda e: self.on_mix_click(e, solo=True))
        self.cv.bind("<Button-2>", lambda e: self.on_mix_click(e, solo=True))
        self.fs = None
        ttk.Label(parent, textvariable=self.v_status, style="Muted.TLabel", padding=(12, 0, 10, 8)).grid(row=4, column=0, sticky="we")
        root.bind("<space>", self.on_space)
        root.bind("<Left>", lambda e: self.on_key(-1))
        root.bind("<Right>", lambda e: self.on_key(1))
        self.vol_changed()
        lb = settings.get("loop_before")
        self.loop_before = lb if lb in LOOP_CHOICES else self.v_loops.get()
        self.opts_changed(init=True)
        self.tick()

    # ------------------------------------------------------------ fichiers
    def choose_dir(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(title="Folder containing .ngt files", initialdir=self.settings.get("ngt_dir") or None)
        if d:
            self.load_folder(d)

    def choose_file(self):
        from tkinter import filedialog
        f = filedialog.askopenfilename(title=".ngt file", filetypes=[("Neo Geo music", "*.ngt")])
        if f:
            self.load_files(ngt_group_files([f]))

    def load_folder(self, d):
        self.settings["ngt_dir"] = d
        save_settings(self.settings)
        self.load_files(ngt_group_files(sorted(glob.glob(os.path.join(d, "**", "*.ngt"), recursive=True))))

    def load_files(self, files):
        self.stop()
        self.files, self.cur, self.cache = list(files), None, {}
        self.prep = {}
        self.meta.clear()
        self.iid_ft, self.ft_iid, self.game_iid = {}, {}, {}
        self.load_gen = getattr(self, "load_gen", 0) + 1
        self.tree.delete(*self.tree.get_children())
        n_tr = 0
        for gi, f in enumerate(self.files):
            gid = f"g{gi}"
            try:
                h = read_meta(f)                      # header + table only: fast even for hundreds of games
            except Exception as ex:
                self.tree.insert("", "end", iid=gid, text=os.path.basename(f), values=("", str(ex), "unreadable"), tags=("ko",))
                continue
            self.game_iid[f] = gid
            short = _short_from_header(h["game"], h["title"])
            self.short_of[f] = short
            if h["title"] == short or h["title"].lower() == h["game"].lower():       # title is just the ROM name: decode it
                full = decode_name(short, online=False)                              # built-in table / cache, instant
                if full:
                    for t in h["tracks"]:
                        t["name"] = t["name"].replace(h["title"], full, 1)
                    h["title"] = full
            self.title_of[f] = h["title"]
            self.tree.insert("", "end", iid=gid, open=True, tags=("game",), text=h["title"],
                             values=("", f"{len(h['tracks'])} tracks", f"{ngt_size(f)/1e6:.1f} MB — checking…"))
            for i, m in enumerate(h["tracks"]):
                tid = f"{gid}t{i}"
                self.meta[f"{f}|{i}"] = m
                self.iid_ft[tid] = (f, i); self.ft_iid[(f, i)] = tid
                loop = (f"{(m['loop_start']-m['k0'])/m['rate']:.1f} → {(m['loop_end']-m['k0'])/m['rate']:.1f} s"
                        if m.get("loop_start") is not None else "no loop")
                self.tree.insert(gid, "end", iid=tid, text=m["name"],
                                 values=(fmt_time(m["length_samples"] / m["rate"]), loop, ""))
                n_tr += 1
        self.v_status.set(f"{len(self.files)} game(s), {n_tr} track(s). Double-click or Enter to play.")
        first = next(iter(self.ft_iid.values()), None)
        if first:
            self.tree.selection_set(first); self.tree.see(first)
        self.pics_request()
        # integrity check (CRC of the whole file) in the background, so the window never freezes
        gen, files_now = self.load_gen, list(self.files)

        def crc_job():
            for f in files_now:
                if gen != self.load_gen:
                    return
                try:
                    ok = check(ngt_data(f))[0]
                except Exception:
                    ok = False
                self.q.put(("crc", True, (gen, f, ok)))
        threading.Thread(target=crc_job, daemon=True).start()

    def on_crc(self, res):
        gen, f, ok = res
        gid = self.game_iid.get(f)
        if gen != self.load_gen or not gid:
            return
        try:
            vals = list(self.tree.item(gid, "values"))
            vals[2] = f"{ngt_size(f)/1e6:.1f} MB — " + ("intact" if ok else "ALTERED")
            self.tree.item(gid, values=vals)
            if not ok:
                self.tree.item(gid, tags=("game", "ko"))
                for t in self.tree.get_children(gid):
                    self.tree.item(t, tags=("ko",))
        except Exception:
            pass

    def sel_track(self):
        sel = self.tree.selection()
        if not sel:
            return None
        iid = sel[0]
        if iid not in self.iid_ft:
            kids = self.tree.get_children(iid)
            if not kids:
                return None
            iid = kids[0]
        return self.iid_ft.get(iid)

    # ------------------------------------------------------------ travail en arrière-plan
    def bg(self, fn, done):
        def run():
            try:
                self.q.put((done, True, fn()))
            except Exception as ex:
                import traceback; dlog("bg error: " + traceback.format_exc()[-600:])
                self.q.put((done, False, ex))
        threading.Thread(target=run, daemon=True).start()

    def _key_lock(self, key):
        with self.cache_lock:
            return self.key_locks.setdefault(key, threading.Lock())

    def get_rendered(self, key):
        with self._key_lock(("r", key)):                      # one render per track even if prefetch and user ask together
            if key in self.cache:
                return self.cache[key]
            f, idx = key[0], key[1]
            loaded = load_track(f, idx)
            if len(key) > 2 and key[2]:
                loaded = (loaded[0], mute_regs(loaded[1], key[2]), loaded[2])
            meta, pcm = render_track(f, idx, loaded=loaded)
            act = voice_activity(loaded[1], meta)
            with self.cache_lock:
                if len(self.cache) >= 6:
                    self.cache.pop(next(iter(self.cache)))
                self.cache[key] = (meta, pcm, act)
            return self.cache[key]

    def rkey(self, ft):
        """Cache key of a track as currently mixed."""
        return (ft[0], ft[1], tuple(sorted(self.muted)))

    def get_notes(self, ft):
        ft = (ft[0], ft[1])
        if ft not in self.notes_cache:
            meta, regs, _ = load_track(*ft)
            if len(self.notes_cache) > 8:
                self.notes_cache.pop(next(iter(self.notes_cache)))
            self.notes_cache[ft] = note_events(regs, meta)
        return self.notes_cache[ft]

    def get_prepared(self, key):
        """(meta, act, intro, loop, unit-gain peak data) at the output rate, cached: replays and normalisation changes are instant."""
        with self._key_lock(("p", key)):
            if key in self.prep:
                return self.prep[key]
            meta, pcm, act = self.get_rendered(key)
            dlog("prepare_playback start")
            intro, loop = prepare_playback(pcm, meta)
            dlog("prepare_playback done")
            with self.cache_lock:
                if len(self.prep) >= 3:                       # ~60 MB per long track: keep only a few
                    self.prep.pop(next(iter(self.prep)))
                self.prep[key] = (meta, act, intro, loop)
            return self.prep[key]

    def prefetch_next(self):
        """While a track plays, compute the next one in the background so that next/auto-next is instant."""
        order = list(self.iid_ft)
        cur = self.ft_iid.get(tuple(self.cur)) if self.cur else None
        if cur is None or cur not in order:
            return
        j = order.index(cur) + 1
        if j >= len(order):
            return
        key = self.rkey(self.iid_ft[order[j]])
        if key in self.prep:
            return

        def job():
            try:
                self.get_prepared(key)
            except Exception as ex:
                dlog(f"prefetch: {ex}")
        threading.Thread(target=job, daemon=True).start()

    # ------------------------------------------------------------ lecture
    def play_sel(self):
        ft = self.sel_track()
        if not ft:
            return
        self.req += 1
        req, mode = self.req, self.v_norm.get()
        self.player.stop()
        self.v_status.set("Computing the track (YM2610 replay)…")
        self.comp_t0 = time.time()
        self.btn_play.configure(text="…")

        rk = self.rkey(ft)

        def work():
            meta, act, intro, loop = self.get_prepared(rk)
            g = gain_for(mode, meta, self.get_rendered(rk)[1])
            self.get_notes(ft)
            if g != 1.0:                                      # gain is linear: applied after resampling, never clips
                gf = np.float32(g)
                intro = np.clip(intro * gf, -1.0, 1.0)
                loop = None if loop is None else np.clip(loop * gf, -1.0, 1.0)
            return req, ft, meta, g, act, intro, loop
        self.bg(work, "ready")

    def on_ready(self, ok, res):
        if not ok:
            self.btn_play.configure(text="▶ Play")
            from tkinter import messagebox
            self.v_status.set("Playback error.")
            messagebox.showerror("Cannot play", str(res))
            return
        req, ft, meta, g, act, intro, loop = res
        if req != self.req:
            return                                               # une autre piste a été demandée entre-temps
        self.cur, self.act, self.decay = ft, act, np.zeros(14)
        self.notes = self.notes_cache.get((ft[0], ft[1]))
        self.cur_name, self.cur_gain = meta["name"], g
        self.player.load(intro, loop)
        err = self.player.play()
        self.btn_play.configure(text="⏸ Pause" if not err else "▶ Play")
        self.v_status.set(err or f"{meta['name']} — gain ×{g:.2f}" + ("" if loop is not None else " — no loop"))
        self.build_strip()
        self.prefetch_next()

    def play_or_pause(self):
        p = self.player
        if p.stream is not None and p.playing:
            self.btn_play.configure(text="▶ Resume" if p.toggle_pause() else "⏸ Pause")
        else:
            self.play_sel()

    def stop(self):
        self.req += 1
        self.player.stop()
        self.btn_play.configure(text="▶ Play")

    def opts_changed(self, init=False):
        """'Next track at end' and endless looping exclude each other: with Next on, '∞' is not offered (2 loops + fade
        is used instead) and the previous choice comes back when Next is unticked."""
        nxt = bool(self.v_next.get())
        was = getattr(self, "next_was", None)
        if not nxt and not init:
            if was:                                                   # Next has just been unticked: restore
                self.v_loops.set(self.loop_before)
            else:                                                     # the user picked a value himself
                self.loop_before = self.v_loops.get()
        if nxt and self.v_loops.get() == LOOP_CHOICES[0]:
            self.v_loops.set(LOOP_CHOICES[2])
        self.cb_loop.configure(values=LOOP_CHOICES[1:] if nxt else LOOP_CHOICES)
        self.next_was = nxt
        self.player.loops_max = LOOP_COUNTS[LOOP_CHOICES.index(self.v_loops.get())]
        self.settings["loops"] = self.v_loops.get()
        self.settings["loop_before"] = self.loop_before
        self.settings["autonext"] = nxt
        save_settings(self.settings)

    def step(self, d):
        """Previous / next track (crosses game boundaries)."""
        order = list(self.iid_ft)
        if not order:
            return
        ft = self.cur or self.sel_track()
        tid = self.ft_iid.get(tuple(ft)) if ft else None
        if tid is None:
            return
        j = order.index(tid) + d
        if 0 <= j < len(order):
            self.tree.selection_set(order[j]); self.tree.see(order[j])
            self.play_sel()
        else:
            self.stop()
            self.v_status.set("End of list.")

    def norm_changed(self):
        self.settings["norm"] = self.v_norm.get()
        save_settings(self.settings)
        if self.player.playing and self.cur:
            self.tree.selection_set(self.ft_iid.get(tuple(self.cur), ""))
            self.play_sel()

    def vol_changed(self, *_):
        self.player.volume = (self.v_vol.get() / 100.0) ** 2          # courbe douce
        self.settings["vol"] = round(self.v_vol.get())

    def on_space(self, e):
        fw = str(self.root.focus_get())
        if "entry" in fw or "spinbox" in fw:
            return
        self.play_or_pause()

    def on_key(self, d):
        fw = str(self.root.focus_get())
        if "entry" in fw or "spinbox" in fw:
            return
        self.step(d)

    def export(self, sample):
        from tkinter import filedialog
        ft = self.sel_track()
        if not ft:
            return
        f, idx = ft
        stem = os.path.splitext(os.path.basename(f))[0] + f" - Track {idx + 1:02d}"
        out = filedialog.asksaveasfilename(title="Save the WAV", defaultextension=".wav",
                                           initialfile=stem + (" (30 s)" if sample else "") + ".wav",
                                           filetypes=[("WAV", "*.wav")])
        if not out:
            return
        mode = self.v_norm.get()
        self.v_status.set("Exporting…")

        def work():
            if sample:
                _, _, x = playback_pcm(f, idx, mode, 30.0, 0.0)
                save_wav(out, x, OUT_RATE)
                return "30 s sample saved (48 kHz)."
            meta, pcm, _ = self.get_rendered(self.rkey((f, idx)))
            save_wav(out, apply_gain(pcm, gain_for(mode, meta, pcm)), RATE)
            return "WAV saved (55,944 Hz, full render" + (", current mix)." if self.muted else ").")
        self.bg(work, "export")

    # ------------------------------------------------------------ dessin
    def on_configure(self, e):
        if self.cfg_job:
            self.root.after_cancel(self.cfg_job)
        self.cfg_job = self.root.after(60, self.layout)

    def layout(self):
        cv = self.cv
        w, h = max(cv.winfo_width(), 300), max(cv.winfo_height(), 240)
        self.w, self.h = w, h
        cv.delete("all")
        sr = self.STRIP_ROW * 14
        self.y_prog = 30
        y_spec = 52
        self.y_strip = h - sr - 8
        rest = self.y_strip - 34 - y_spec
        kb_h = 38 if rest >= 190 else 0                           # piano keyboard (live notes)
        spec_h = max(60, int((rest - kb_h) * 0.55))
        y_voice = y_spec + spec_h + 16
        voice_h = max(30, self.y_strip - 22 - y_voice - (kb_h + 12 if kb_h else 0))
        self.id_title = cv.create_text(12, 14, anchor="w", fill=PAL["fg"], font=FONT_B, text="")
        self.id_time = cv.create_text(w - 12, 14, anchor="e", fill=PAL["muted"], font=FONT, text="")
        cv.create_rectangle(12, self.y_prog, w - 12, self.y_prog + 6, fill=PAL["prog_bg"], outline="")
        self.id_loopzone = cv.create_rectangle(0, 0, 0, 0, fill=PAL["prog_loop"], outline="")
        self.id_played = cv.create_rectangle(12, self.y_prog, 12, self.y_prog + 6, fill=PAL["accent"], outline="")
        # spectre à LED
        side = min(spec_h + 16 + voice_h, int(w * 0.34)) if (self.v_pics.get() and self.pic_ok()) else 0
        side = side if side >= 120 else 0
        cw = w - 24 - (side + 12 if side else 0)                 # width left for the graphs
        self.pic_box = (w - 12 - side, y_spec, side) if side else None
        self.seg = seg = max(10, min(24, spec_h // 7))
        bw, sh = cw / self.BANDS, spec_h / seg
        self.led = [[cv.create_rectangle(12 + b * bw + 1.5, y_spec + spec_h - (s + 1) * sh + 1.5, 12 + (b + 1) * bw - 1.5,
                                         y_spec + spec_h - s * sh - 0.5, fill=PAL["led_off"], outline="")
                     for s in range(seg)] for b in range(self.BANDS)]
        self.led_on = [0] * self.BANDS
        self.cols = [_led_color(s, seg) for s in range(seg)]
        self.caps = [cv.create_rectangle(0, 0, 0, 0, fill=PAL["cap"], outline="") for _ in range(self.BANDS)]
        self.geom = (y_spec, spec_h, bw, sh)
        # voies
        vbw = cw / 14
        self.vgeom = (y_voice, voice_h, vbw)
        vcol = PAL["voices"]
        self.vcol = vcol
        self.vbars, self.vbg, self.vlbl = [], [], []
        for v in range(14):
            x = 12 + v * vbw
            self.vbg.append(cv.create_rectangle(x + 5, y_voice, x + vbw - 5, y_voice + voice_h, fill=PAL["voice_bg"], outline=""))
            self.vbars.append(cv.create_rectangle(x + 5, y_voice + voice_h, x + vbw - 5, y_voice + voice_h, fill=vcol[v], outline=""))
            self.vlbl.append(cv.create_text(x + vbw / 2, y_voice + voice_h + 10, text=VOICES_SHORT[v], fill=PAL["muted"], font=FONT_S))
        self.id_mixhint = cv.create_text(12 + cw, y_voice - 8, anchor="e", fill=PAL["muted"], font=FONT_S, text="")
        # piano keyboard, full width under the voices (C1 .. B7)
        self.kb = {}
        self.kb_on = {}
        if kb_h:
            y_kb = y_voice + voice_h + 22
            whites = [m for m in range(24, 108) if m % 12 in (0, 2, 4, 5, 7, 9, 11)]
            ww = (w - 24) / len(whites)
            for i, m in enumerate(whites):
                self.kb[m] = (cv.create_rectangle(12 + i * ww, y_kb, 12 + (i + 1) * ww - 1, y_kb + kb_h,
                                                  fill=PAL["kb_white"], outline=PAL["kb_line"]), PAL["kb_white"])
            for i, m in enumerate(whites):
                if m % 12 in (0, 2, 5, 7, 9) and m + 1 < 108:
                    x = 12 + (i + 1) * ww
                    self.kb[m + 1] = (cv.create_rectangle(x - ww * 0.32, y_kb, x + ww * 0.32, y_kb + kb_h * 0.6,
                                                          fill=PAL["kb_black"], outline=""), PAL["kb_black"])
            for o in range(1, 8):
                c = 24 + 12 * (o - 1)
                i = whites.index(c)
                cv.create_text(12 + i * ww + ww / 2, y_kb + kb_h - 7, text=f"C{o}", fill=PAL["muted"], font=FONT_S)
        self.id_pic = None
        if self.pic_box:
            bx, by, bs = self.pic_box
            cv.create_rectangle(bx - 1, by - 1, bx + bs + 1, by + bs + 1, outline=PAL["line"], fill=PAL["canvas"])
            self.id_pic = cv.create_image(bx, by, anchor="nw")
            self.id_pic_msg = cv.create_text(bx + bs / 2, by + bs / 2, fill=PAL["muted"], font=FONT_S, width=bs - 20, justify="center", text="")
            self.slide.update(cur=None, prev=None, path=None, side=bs, cache={}, next_at=0.0)
        self.id_img = cv.create_image(12, self.y_strip, anchor="nw")
        self.id_cur = cv.create_line(12, self.y_strip, 12, self.y_strip + sr, fill=PAL["cursor"])
        self.ids = True
        self.mix_visuals()
        self.build_strip()

    def draw_keys(self, t_samples, live):
        """Lights the keys of the notes sounding now, in the colour of their voice."""
        if not self.kb:
            return
        want = {}
        nt = self.notes
        if live and nt is not None and len(nt["start"]):
            sel = (nt["start"] <= t_samples) & (nt["end"] > t_samples)
            for m, v in zip(nt["midi"][sel], nt["voice"][sel]):
                if v in self.muted:
                    continue
                k = int(round(m))
                if k in self.kb:
                    want[k] = PAL["voices"][v]
        for k, col in self.kb_on.items():
            if want.get(k) != col:
                self.cv.itemconfigure(self.kb[k][0], fill=self.kb[k][1])
        for k, col in want.items():
            if self.kb_on.get(k) != col:
                self.cv.itemconfigure(self.kb[k][0], fill=col)
        self.kb_on = want

    def build_strip(self):
        if self.ids is None or self.act is None:
            return
        n_ = max(self.w - 24, 50)
        small = self.act[:, np.linspace(0, self.act.shape[1] - 1, n_).astype(int)]
        rgb = np.zeros((14, n_, 3), dtype=np.uint8)
        for v in range(14):
            base = np.array([int(self.vcol[v][i:i + 2], 16) for i in (1, 3, 5)], dtype=float)
            bgc = np.array([int(PAL["voice_bg"][i:i + 2], 16) for i in (1, 3, 5)], dtype=float)
            rgb[v] = (bgc[None, :] + (base - bgc)[None, :] * small[v][:, None]).astype(np.uint8)
        rgb = np.repeat(rgb, self.STRIP_ROW, axis=0)
        self.img = self.tk.PhotoImage(data=b"P6 %d %d 255\n" % (rgb.shape[1], rgb.shape[0]) + rgb.tobytes(), format="PPM")
        self.cv.itemconfigure(self.id_img, image=self.img)

    def in_pic(self, e):
        b = self.pic_box
        return bool(b) and b[0] <= e.x <= b[0] + b[2] and b[1] <= e.y <= b[1] + b[2]

    def on_dbl(self, e):
        if self.in_pic(e):
            self.fs_open()

    def on_click(self, e):
        if self.on_mix_click(e):
            return
        if self.ids is None or self.player.intro is None or self.in_pic(e):
            return
        if self.y_prog - 8 <= e.y <= self.y_prog + 14:
            ti, tl = self.player.duration_s()
            tot = ti + tl
            if tot > 0:
                self.player.seek(min(max((e.x - 12) / max(self.w - 24, 1), 0.0), 1.0) * tot)

    def tick(self):
        try:
            while True:
                kind, ok, res = self.q.get_nowait()
                if kind == "ready":
                    self.on_ready(ok, res)
                elif kind == "crc":
                    self.on_crc(res)
                elif kind == "remix":
                    self.on_remix(ok, res)
                else:
                    self.v_status.set(res if ok else f"Export failed: {res}")
        except queue.Empty:
            pass
        if self.comp_t0 is not None:
            if self.btn_play.cget("text") == "…":
                self.v_status.set(f"Computing the track (YM2610 replay)… {time.time()-self.comp_t0:.0f} s")
            else:
                self.comp_t0 = None
        if self.v_pics.get() and self.ids is not None and self.pics.state != "idle":
            self.apply_decoded()
        if self.fs:
            try:
                self.fs_tick()
            except Exception as ex:
                dlog(f"fs_tick: {ex}")
                self.fs_close()
        if self.ids is not None:
            self.draw()
            try:
                self.pics_tick()
            except Exception as ex:
                dlog(f"pics_tick: {ex}")
                self.slide["next_at"] = time.time() + 5
        self.root.after(40, self.tick)

    def draw(self):
        cv, p = self.cv, self.player
        live = p.playing and not p.paused and p.stream is not None
        if self.was_playing and not p.playing and p.stream is not None:
            self.btn_play.configure(text="▶ Play")                 # piste terminée
            self.v_status.set("End of track.")
            if self.v_next.get():
                self.root.after(150, lambda: self.step(1))
        self.was_playing = p.playing
        lv = spectrum_levels(p.window(SPEC_N)) if live else np.zeros(self.BANDS)
        self.spec = np.maximum(lv, self.spec * 0.80)
        self.peak = np.maximum(self.spec, self.peak - 0.012)
        y_spec, spec_h, bw, sh = self.geom
        for b in range(self.BANDS):
            n = int(round(self.spec[b] * self.seg))
            o = self.led_on[b]
            if n != o:
                for s in range(min(n, o), max(n, o)):
                    cv.itemconfigure(self.led[b][s], fill=self.cols[s] if s < n else PAL["led_off"])
                self.led_on[b] = n
            pk = min(int(round(self.peak[b] * self.seg)), self.seg)
            if pk > 0:
                y = y_spec + spec_h - pk * sh
                cv.coords(self.caps[b], 12 + b * bw + 1.5, y + 1, 12 + (b + 1) * bw - 1.5, y + 3.5)
            else:
                cv.coords(self.caps[b], 0, 0, 0, 0)
        pos = p.position_s() if p.intro is not None else 0.0
        ti, tl = p.duration_s()
        self.draw_keys(pos * RATE, live)
        if self.act is not None:
            fr = min(int(pos * FPS), self.act.shape[1] - 1)
            self.decay = np.maximum(self.act[:, fr] if live else 0.0, self.decay * 0.86)
            y_voice, voice_h, vbw = self.vgeom
            for v in range(14):
                x = 12 + v * vbw
                hh = float(self.decay[v]) * voice_h
                cv.coords(self.vbars[v], x + 5, y_voice + voice_h - hh, x + vbw - 5, y_voice + voice_h)
            x = 12 + (self.w - 24) * fr / max(self.act.shape[1] - 1, 1)
            cv.coords(self.id_cur, x, self.y_strip, x, self.y_strip + self.STRIP_ROW * 14)
        if self.cur and p.intro is not None:
            tot = max(ti + tl, 1e-6)
            W = self.w - 24
            cv.coords(self.id_played, 12, self.y_prog, 12 + W * min(pos / tot, 1.0), self.y_prog + 6)
            if tl > 0:
                cv.coords(self.id_loopzone, 12 + W * ti / tot, self.y_prog, 12 + W, self.y_prog + 6)
            else:
                cv.coords(self.id_loopzone, 0, 0, 0, 0)
            cv.itemconfigure(self.id_title, text=getattr(self, "cur_name", ""))
            state = "pause" if p.paused else ("loop %d" % (p.loops + 1) if p.in_loop else "intro")
            if p.fade_pos is not None:
                state += " · fading out"
            elif p.loops_max is not None and p.loop is not None:
                state += f" / {p.loops_max}"
            cv.itemconfigure(self.id_time, text=f"{fmt_time(pos)}   ·   {state}")

    # ------------------------------------------------------------ screenshots
    @staticmethod
    def pic_ok():
        try:
            import PIL  # noqa: F401
            return True
        except ImportError:
            return False

    def pics_toggled(self):
        self.settings["pics"] = bool(self.v_pics.get())
        save_settings(self.settings)
        self.pics_request()
        self.layout()

    def pics_request(self):
        if self.v_pics.get() and self.pic_ok():
            self.pics.request([(self.short_of[f], self.title_of[f]) for f in self.files if f in self.short_of])

    def apply_decoded(self):
        """Names found online (Arcade Database) replace ROM short names in the list."""
        dec = self.pics.decoded
        if len(dec) == self.decoded_seen:
            return
        self.decoded_seen = len(dec)
        for f, short in self.short_of.items():
            full, gid = dec.get(short), self.game_iid.get(f)
            old = self.title_of.get(f)
            if not full or not gid or full == old or old != short:
                continue
            try:
                self.tree.item(gid, text=full)
                for t in self.tree.get_children(gid):
                    self.tree.item(t, text=self.tree.item(t, "text").replace(old, full, 1))
                for key, m in self.meta.items():
                    if key.startswith(f + "|"):
                        m["name"] = m["name"].replace(old, full, 1)
                self.title_of[f] = full
            except Exception as ex:
                dlog(f"apply_decoded: {ex}")

    # ------------------------------------------------------------ full-screen screenshot with the audio graph on top
    def fs_open(self):
        if self.fs or not self.pic_ok():
            return
        tk = self.tk
        top = tk.Toplevel(self.root)
        top.configure(bg="black")
        if os.name != "nt":
            top.geometry(f"{top.winfo_screenwidth()}x{top.winfo_screenheight()}+0+0")
        try:
            top.attributes("-fullscreen", True)
        except tk.TclError:
            pass
        cv = tk.Canvas(top, bg="black", highlightthickness=0)
        cv.pack(fill="both", expand=True)
        fs = {"top": top, "cv": cv, "w": 0, "h": 0, "cache": {}, "key": None, "base": None, "photo_t": None, "photo_b": None,
              "id_t": cv.create_image(0, 0, anchor="nw"), "id_b": cv.create_image(0, 0, anchor="nw"),
              "id_txt": cv.create_text(24, 18, anchor="nw", fill="#d8d8d8", font=FONT_B, text=""),
              "id_msg": cv.create_text(0, 0, fill="#808080", font=FONT, text=""),
              "id_hint": cv.create_text(0, 0, anchor="se", fill="#8a8a8a", font=FONT_S,
                                        text="V: next view (pictures · oscilloscopes · piano-roll)   ·   Space: pause   ·   ← →: tracks   ·   Esc: back"),
              "mode": self.settings.get("fs_mode", "pics") if self.settings.get("fs_mode") in FS_VIEWS else "pics",
              "scope_items": {}, "scope_layout": None, "roll": None}
        self.fs = fs

        def cfg(e):
            if (e.width, e.height) != (fs["w"], fs["h"]):
                fs["w"], fs["h"] = e.width, e.height
                fs["cache"].clear(); fs["key"] = None
        cv.bind("<Configure>", cfg)
        for w in (top, cv):
            w.bind("<Double-Button-1>", lambda e: self.fs_close())
            w.bind("<Escape>", lambda e: self.fs_close())
            w.bind("<space>", lambda e: self.play_or_pause())
            w.bind("<Left>", lambda e: self.step(-1))
            w.bind("<Right>", lambda e: self.step(1))
            for k in ("<Key-v>", "<Key-V>", "<Key-o>", "<Key-O>", "<Tab>"):
                w.bind(k, lambda e: self.fs_mode())
        top.protocol("WM_DELETE_WINDOW", self.fs_close)
        top.focus_force()
        top.update_idletasks()

    def fs_close(self):
        fs, self.fs = self.fs, None
        if fs:
            try:
                fs["top"].destroy()
            except Exception:
                pass

    def _fs_fit(self, path, W, H):
        """Image -> uint8 array (H, W, 3), scaled to fit, centred on black."""
        c = self.fs["cache"]
        if path in c:
            return c[path]
        from PIL import Image
        arr = np.zeros((H, W, 3), dtype=np.uint8)
        try:
            im = Image.open(path).convert("RGB")
            k = min(W / im.width, H / im.height)
            im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS)
            y, x = (H - im.height) // 2, (W - im.width) // 2
            arr[y:y + im.height, x:x + im.width] = np.asarray(im)
        except Exception as ex:
            dlog(f"fs: cannot read {path}: {ex}")
        if len(c) >= 4:
            c.pop(next(iter(c)))
        c[path] = arr
        return arr

    @staticmethod
    def _tint(arr, x0, x1, y0, y1, rgb, alpha):
        """Alpha-blend a flat colour over arr[y0:y1, x0:x1] (arr is modified)."""
        if x1 <= x0 or y1 <= y0:
            return
        a = int(alpha * 256)
        sl = arr[y0:y1, x0:x1].astype(np.uint16)
        arr[y0:y1, x0:x1] = ((sl * (256 - a) + np.array(rgb, np.uint16) * a) >> 8).astype(np.uint8)

    def fs_mode(self):
        fs = self.fs
        if not fs:
            return
        fs["mode"] = FS_VIEWS[(FS_VIEWS.index(fs["mode"]) + 1) % len(FS_VIEWS)]
        self.settings["fs_mode"] = fs["mode"]
        fs["key"] = None
        for it in fs["scope_items"].values():
            for i in it:
                fs["cv"].delete(i)
        fs["scope_items"], fs["scope_layout"] = {}, None
        if fs.get("roll"):
            fs["cv"].delete("roll")
            fs["roll"] = None

    # ---- per-voice oscilloscopes: every voice rendered alone (same machinery as the mixer), then drawn with a trigger
    def scope_data(self, ft):
        """Starts (once per track) the solo renders of the voices that play; returns the dict that fills up meanwhile."""
        sc = getattr(self, "scope", None)
        if sc and sc["ft"] == ft:
            return sc
        try:
            meta, regs, _ = load_track(*ft)
            act = voice_activity(regs, meta)
        except Exception as ex:
            dlog(f"scope: {ex}")
            return None
        voices = [v for v in range(14) if act[v].max() > 0.01]
        sc = {"ft": ft, "voices": voices, "pcm": {}, "peak": {}, "stop": False}
        old, self.scope = getattr(self, "scope", None), sc
        if old:
            old["stop"] = True

        def one(v):
            try:
                one_voice(v)
            except Exception as ex:                       # une voix en échec ne bloque pas les autres
                dlog(f"scope voice {v}: {ex}")
                sc["peak"][v], sc["pcm"][v] = 256.0, np.zeros(0, dtype=np.int16)

        def one_voice(v):
            if sc["stop"]:
                return
            loaded = load_track(*ft)
            solo = mute_regs(loaded[1], [x for x in range(14) if x != v])
            _, pcm = render_track(ft[0], ft[1], loaded=(loaded[0], solo, loaded[2]))
            mono = pcm.astype(np.int32).sum(axis=1)
            mono = ((mono[0::2][: len(mono) // 2] + mono[1::2][: len(mono) // 2]) // 4).astype(np.int16)   # 27,972 Hz
            nz = np.abs(mono[mono != 0])
            sc["peak"][v] = max(float(np.percentile(nz, 99.5)) if len(nz) else 256.0, 256.0)   # robust scale: loud hits don't flatten the rest
            sc["pcm"][v] = mono

        def job():
            with cf.ThreadPoolExecutor(max_workers=max(1, min(3, (os.cpu_count() or 2) - 1))) as ex:
                list(ex.map(one, voices))
        threading.Thread(target=job, daemon=True).start()
        return sc

    def fs_backdrop(self, W, H, mode, level):
        """Darkened current picture as the background of the scope / piano-roll views (rebuilt only when it changes)."""
        fs, sl, cv = self.fs, self.slide, self.fs["cv"]
        key = (mode, sl.get("path"), W, H)
        if key != fs["key"]:
            base = self._fs_fit(sl["path"], W, H) if sl.get("path") else np.zeros((H, W, 3), dtype=np.uint8)
            dark = (base.astype(np.uint16) * level >> 8).astype(np.uint8)
            fs["photo_t"] = self.tk.PhotoImage(data=b"P6 %d %d 255\n" % (W, H) + np.ascontiguousarray(dark).tobytes(), format="PPM")
            cv.itemconfigure(fs["id_t"], image=fs["photo_t"])
            cv.itemconfigure(fs["id_b"], image="")
            cv.itemconfigure(fs["id_msg"], text="")
            fs["key"] = key
            fs["ambient"] = ambient_color(sl.get("path"))

    def get_vis(self, ft):
        ft = (ft[0], ft[1])
        c = getattr(self, "vis_cache", None)
        if c is None:
            c = self.vis_cache = {}
        if ft not in c:
            meta, regs, _ = load_track(*ft)
            if len(c) > 6:
                c.pop(next(iter(c)))
            c[ft] = visual_events(regs, meta)
        return c[ft]

    # ---- piano-roll waterfall + drum pads + stereo stage
    def roll_tick(self, W, H):
        fs, cv = self.fs, self.fs["cv"]
        self.fs_backdrop(W, H, "roll", 45)
        amb = fs.get("ambient") or "#4fc3f7"
        if not self.cur:
            cv.itemconfigure(fs["id_msg"], text="Play a track to see its notes")
            cv.coords(fs["id_msg"], W / 2, H / 2)
            return
        ft = (self.cur[0], self.cur[1])
        nt, vis = self.get_notes(ft), self.get_vis(ft)
        R = fs.get("roll")
        if not R or R["key"] != (ft, W, H):
            cv.delete("roll")
            R = fs["roll"] = {"key": (ft, W, H), "pool": [], "kb": {}, "kb_on": {}, "pads": [], "stage": {}}
            pad = 18
            R["xl"], R["xr"] = pad, int(W * 0.74)
            R["ytop"] = 56
            kb_h = int(H * 0.11)
            R["ykb"] = H - kb_h - 44
            whites = [m for m in range(24, 108) if m % 12 in (0, 2, 4, 5, 7, 9, 11)]
            ww = (R["xr"] - R["xl"]) / len(whites)
            R["kx"] = {}
            for i, m in enumerate(whites):
                x0 = R["xl"] + i * ww
                R["kx"][m] = (x0 + 1, x0 + ww - 1)
                R["kb"][m] = (cv.create_rectangle(x0, R["ykb"], x0 + ww - 1, R["ykb"] + kb_h, fill="#e8e8e8", outline="#555555",
                                                  tags="roll"), "#e8e8e8")
            for i, m in enumerate(whites):
                if m % 12 in (0, 2, 5, 7, 9) and m + 1 < 108:
                    x = R["xl"] + (i + 1) * ww
                    R["kx"][m + 1] = (x - ww * 0.32, x + ww * 0.32)
                    R["kb"][m + 1] = (cv.create_rectangle(x - ww * 0.32, R["ykb"], x + ww * 0.32, R["ykb"] + kb_h * 0.62,
                                                          fill="#202020", outline="", tags="roll"), "#202020")
            for o in range(1, 8):                               # octave grid in the waterfall
                x = R["kx"][24 + 12 * (o - 1)][0]
                cv.create_line(x, R["ytop"], x, R["ykb"], fill="#2c2c2c", tags="roll")
                cv.create_text(x + 3, R["ykb"] + kb_h + 4, anchor="nw", text=f"C{o}", fill="#909090", font=FONT_S, tags="roll")
            R["now"] = cv.create_line(R["xl"], R["ykb"], R["xr"], R["ykb"], fill=amb, width=2, tags="roll")
            # drum pads (2 x 4) + ADPCM-B
            px0, px1 = int(W * 0.77), W - pad
            R["t_pads"] = cv.create_text(px0, R["ytop"], anchor="nw", fill=amb, font=FONT_B, text="DRUM PADS · ADPCM samples", tags="roll")
            gw, gh = (px1 - px0 - 10) / 2, (H * 0.40) / 5
            pads = vis["pads"]
            for i in range(len(pads)):
                x0, y0 = px0 + (i % 2) * (gw + 10), R["ytop"] + 26 + (i // 2) * (gh + 8)
                col = _hue_hex(i / max(len(pads), 1))
                rid = cv.create_rectangle(x0, y0, x0 + gw, y0 + gh, fill="#1a1a1a", outline=col, width=2, tags="roll")
                cv.create_text(x0 + 8, y0 + 6, anchor="nw", text=f"sample {i + 1}", fill=col, font=FONT_S, tags="roll")
                R["pads"].append((rid, col))
            y0 = R["ytop"] + 26 + 4 * (gh + 8)
            R["bpad"] = (cv.create_rectangle(px0, y0, px1, y0 + gh * 0.7, fill="#1a1a1a", outline=PAL["voices"][13], width=2, tags="roll"),
                         PAL["voices"][13])
            cv.create_text(px0 + 8, y0 + 6, anchor="nw", text="ADPCM-B (long samples)", fill=PAL["voices"][13], font=FONT_S, tags="roll")
            # stereo stage
            sy0 = y0 + gh * 0.7 + 34
            sy1 = R["ykb"] + kb_h
            R["stage_box"] = (px0, sy0, px1, sy1)
            cv.create_text(px0, sy0 - 22, anchor="nw", fill=amb, font=FONT_B, text="STEREO STAGE", tags="roll")
            cv.create_rectangle(px0, sy0, px1, sy1, outline="#3a3a3a", tags="roll")
            for frac, lab in ((0.12, "L"), (0.5, "C"), (0.88, "R")):
                x = px0 + (px1 - px0) * frac
                cv.create_line(x, sy0, x, sy1, fill="#262626", dash=(2, 4), tags="roll")
                cv.create_text(x, sy1 - 4, anchor="s", text=lab, fill="#707070", font=FONT_S, tags="roll")
            for v in range(14):
                R["stage"][v] = (cv.create_oval(0, 0, 0, 0, fill=VIVID[v], outline="", tags="roll"),
                                 cv.create_text(0, 0, text=VOICES_SHORT[v], fill="#cfcfcf", font=FONT_S, tags="roll"))
            cv.tag_raise(fs["id_txt"]); cv.tag_raise(fs["id_hint"])
        p = self.player
        t = p.position_s() * RATE if p.intro is not None else 0.0
        live = p.playing and not p.paused
        look = 3.0 * RATE
        span = R["ykb"] - R["ytop"]
        cv.itemconfigure(R["now"], fill=amb)
        # ---- falling notes
        used = 0
        if len(nt["start"]):
            sel = (nt["start"] < t + look) & (nt["end"] > t)
            for st, en, m, v in zip(nt["start"][sel], nt["end"][sel], nt["midi"][sel], nt["voice"][sel]):
                if v in self.muted:
                    continue
                k = int(round(m))
                if k not in R["kx"]:
                    continue
                x0, x1 = R["kx"][k]
                yb = R["ykb"] - max(0.0, (st - t) / look) * span
                yt = max(R["ytop"], R["ykb"] - (en - t) / look * span)
                if used >= len(R["pool"]):
                    R["pool"].append(cv.create_rectangle(0, 0, 0, 0, outline="", tags="roll"))
                rid = R["pool"][used]
                used += 1
                sounding = st <= t
                cv.coords(rid, x0 + 1, yt, x1 - 1, yb)
                cv.itemconfigure(rid, fill=VIVID[v] if sounding else _dim_hex(VIVID[v], 0.5),
                                 outline="#ffffff" if sounding and live else "")
        for rid in R["pool"][used:]:
            cv.coords(rid, 0, 0, 0, 0)
        # ---- keys
        want = {}
        if live and len(nt["start"]):
            on = (nt["start"] <= t) & (nt["end"] > t)
            for m, v in zip(nt["midi"][on], nt["voice"][on]):
                k = int(round(m))
                if v not in self.muted and k in R["kb"]:
                    want[k] = VIVID[v]
        for k, col in R["kb_on"].items():
            if want.get(k) != col:
                cv.itemconfigure(R["kb"][k][0], fill=R["kb"][k][1])
        for k, col in want.items():
            if R["kb_on"].get(k) != col:
                cv.itemconfigure(R["kb"][k][0], fill=col)
        R["kb_on"] = want
        # ---- drum pads: flash on each trigger, decaying
        win = 0.6 * RATE
        if len(vis["hit_t"]):
            m = (vis["hit_t"] <= t) & (vis["hit_t"] > t - win)
            muted_ch = [c for c in range(6) if 7 + c in self.muted]
            if muted_ch:
                m &= ~np.isin(vis["hit_ch"], muted_ch)
            last = {}
            for ht, pi in zip(vis["hit_t"][m], vis["hit_pad"][m]):
                if pi >= 0:
                    last[pi] = max(last.get(pi, -1e18), ht)
        else:
            last = {}
        for i, (rid, col) in enumerate(R["pads"]):
            a = np.exp(-(t - last[i]) / (0.12 * RATE)) if (i in last and live) else 0.0
            cv.itemconfigure(rid, fill=_mix_hex("#1a1a1a", col, a))
        bt = vis["b_t"]
        bl = bt[(bt <= t) & (bt > t - win)] if len(bt) and 13 not in self.muted else []
        a = np.exp(-(t - bl.max()) / (0.25 * RATE)) if (len(bl) and live) else 0.0
        cv.itemconfigure(R["bpad"][0], fill=_mix_hex("#1a1a1a", R["bpad"][1], a))
        # ---- stereo stage: each voice where its panning puts it (L / C / R), size = its current level
        sx0, sy0, sx1, sy1 = R["stage_box"]
        groups = ([0, 1, 2, 3], [4, 5, 6], [7, 8, 9, 10, 11, 12], [13])
        rows = (0.18, 0.40, 0.64, 0.86)
        slot = {}
        for gi, grp in enumerate(groups):
            spots = {}
            for v in grp:
                lvl = float(self.decay[v]) if (live and v not in self.muted) else 0.0
                if lvl < 0.03:
                    continue
                times, codes = vis["pan"][v]
                code = int(codes[max(0, np.searchsorted(times, t, "right") - 1)])
                spots.setdefault({3: 0.5, 2: 0.12, 1: 0.88}.get(code, 0.5), []).append((v, lvl))
            for frac, vs in spots.items():
                for j, (v, lvl) in enumerate(vs):
                    slot[v] = (frac, j - (len(vs) - 1) / 2, rows[gi], lvl)
        step = (sx1 - sx0) * 0.085
        for v in range(14):
            oid, tid = R["stage"][v]
            if v not in slot:
                cv.coords(oid, 0, 0, 0, 0); cv.coords(tid, -100, -100)
                continue
            frac, off, ry, lvl = slot[v]
            x = min(max(sx0 + (sx1 - sx0) * frac + off * step, sx0 + 18), sx1 - 18)
            y = sy0 + (sy1 - sy0) * ry
            r = 4 + 11 * lvl
            cv.coords(oid, x - r, y - r, x + r, y + r)
            cv.coords(tid, x, y - r - 7)
        name = getattr(self, "cur_name", "")
        cv.itemconfigure(fs["id_txt"], text=f"{name}   ·   {fmt_time(p.position_s())}")

    def scope_tick(self, W, H):
        fs, cv = self.fs, self.fs["cv"]
        self.fs_backdrop(W, H, "scope", 60)
        if not self.cur:
            cv.itemconfigure(fs["id_msg"], text="Play a track to see its voices")
            cv.coords(fs["id_msg"], W / 2, H / 2)
            return
        sc = self.scope_data(tuple(self.cur))
        if not sc:
            return
        voices = [v for v in sc["voices"] if v not in self.muted]
        n = max(len(voices), 1)
        cols = 2 if n <= 4 else (3 if n <= 9 else 4)
        rows = -(-n // cols)
        lay = (tuple(voices), W, H)
        top, pad = 56, 14
        cw, ch = (W - pad * (cols + 1)) / cols, (H - top - 40 - pad * (rows - 1)) / rows
        if lay != fs["scope_layout"]:
            for it in fs["scope_items"].values():
                for i in it:
                    cv.delete(i)
            fs["scope_items"] = {}
            for k, v in enumerate(voices):
                x0, y0 = pad + (k % cols) * (cw + pad), top + (k // cols) * (ch + pad)
                col = VIVID[v]
                frame = cv.create_rectangle(x0, y0, x0 + cw, y0 + ch, outline="#3a3a3a")
                mid = cv.create_line(x0, y0 + ch / 2, x0 + cw, y0 + ch / 2, fill="#2a2a2a")
                lbl = cv.create_text(x0 + 10, y0 + 8, anchor="nw", fill=col, font=FONT_B, text=VOICES[v])
                line = cv.create_line(x0, y0 + ch / 2, x0 + cw, y0 + ch / 2, fill=col, width=2)
                fs["scope_items"][v] = (frame, mid, lbl, line, x0, y0)
            fs["scope_layout"] = lay
        p = self.player
        idx = int(p.position_s() * RATE / 2) if p.intro is not None else 0
        L = 1024                                                       # ~37 ms window
        npts = int(max(64, min(cw / 2, 400)))
        live = p.playing and not p.paused
        for v in voices:
            frame, mid, lbl, line, x0, y0 = fs["scope_items"][v]
            x = sc["pcm"].get(v)
            if x is None:
                cv.itemconfigure(lbl, text=VOICES[v] + "   (computing…)")
                continue
            cv.itemconfigure(lbl, text=VOICES[v])
            a = max(0, min(idx - L, len(x) - 2 * L))
            w = x[a:a + 2 * L].astype(np.float32)
            if len(w) < 2 * L or not live:
                w = np.zeros(2 * L, dtype=np.float32) if len(w) < 2 * L else w
            q = L // 2                                               # trigger: first rising zero-crossing after the
            z = np.nonzero((w[q:L - 1] <= 0) & (w[q + 1:L] > 0))[0]   # middle of the first half (window stays inside)
            s0 = (q + z[0]) if len(z) else q
            seg = w[s0:s0 + L]
            seg = seg[np.linspace(0, L - 1, npts).astype(int)] / sc["peak"][v]
            xs = x0 + np.linspace(4, cw - 4, npts)
            ys = y0 + ch / 2 - np.clip(seg, -1, 1) * (ch / 2 - 18)
            pts = np.empty(2 * npts)
            pts[0::2], pts[1::2] = xs, ys
            cv.coords(line, *pts.tolist())
        left = len(voices) - sum(1 for v in voices if v in sc["pcm"])
        name = getattr(self, "cur_name", "")
        cv.itemconfigure(fs["id_txt"], text=f"{name}   ·   {fmt_time(p.position_s())}" + (f"   ·   computing {left} voice(s)…" if left else ""))
        cv.coords(fs["id_hint"], W - 16, H - 10)

    def fs_tick(self):
        from PIL import Image
        fs, sl = self.fs, self.slide
        W, H = fs["w"], fs["h"]
        if W < 100 or H < 100:
            return
        fs["cv"].coords(fs["id_hint"], W - 16, H - 10)
        if fs["mode"] == "scope":
            return self.scope_tick(W, H)
        if fs["mode"] == "roll":
            return self.roll_tick(W, H)
        now = time.time()
        a = min(1.0, (now - sl["t0"]) / 0.7) if sl.get("path") else 1.0
        key = (sl.get("path"), sl.get("prev_path") if a < 1.0 else None, round(a, 1) if a < 1.0 else 1.0, W, H)
        if key != fs["key"]:                                           # picture (or fade step) changed: rebuild the base frame
            if sl.get("path"):
                cur = self._fs_fit(sl["path"], W, H)
                if a < 1.0 and sl.get("prev_path"):
                    prv = self._fs_fit(sl["prev_path"], W, H)
                    base = np.asarray(Image.blend(Image.fromarray(prv), Image.fromarray(cur), a))
                else:
                    base = cur
            else:
                base = np.zeros((H, W, 3), dtype=np.uint8)
            fs["base"], fs["key"] = base, key
            sh = int(H * 0.34)
            y0 = H - sh
            top_part = base[:y0]
            fs["photo_t"] = self.tk.PhotoImage(data=b"P6 %d %d 255\n" % (W, y0) + np.ascontiguousarray(top_part).tobytes(), format="PPM")
            fs["cv"].itemconfigure(fs["id_t"], image=fs["photo_t"])
            fs["cv"].itemconfigure(fs["id_msg"], text="" if sl.get("path") else "No screenshot for this game")
            fs["cv"].coords(fs["id_msg"], W / 2, H * 0.4)
        base = fs["base"]
        sh = int(H * 0.34)
        y0 = H - sh
        strip = base[y0:].copy()
        # ---- audio graph, drawn semi-transparent over the picture
        mx = int(W * 0.04)
        gw = W - 2 * mx
        vh = int(sh * 0.15)
        floor = sh - vh - 16                                           # baseline of the spectrum inside the strip
        full = int(sh * 0.66)
        nb = self.BANDS
        bw = gw / nb
        amb = ambient_color(sl.get("path"))                         # the game's own colour for the bars
        lo, mid, hi = (tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in (amb, PAL["led_mid"], PAL["led_hi"]))
        for b in range(nb):
            x0, x1 = mx + int(b * bw) + 2, mx + int((b + 1) * bw) - 2
            h = int(min(self.spec[b], 1.0) * full)
            if h > 0:
                for (f0, f1, col) in ((0.0, 0.6, lo), (0.6, 0.85, mid), (0.85, 1.0, hi)):
                    ya, yb = int(f0 * full), min(int(f1 * full), h)
                    if yb > ya:
                        self._tint(strip, x0, x1, floor - yb, floor - ya, col, 0.62)
            pk = int(min(self.peak[b], 1.0) * full)
            if pk > 2:
                self._tint(strip, x0, x1, floor - pk - 3, floor - pk, (255, 255, 255), 0.85)
        vw = gw / 14
        vcols = [tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in PAL["voices"]]
        for v in range(14):
            x0, x1 = mx + int(v * vw) + 4, mx + int((v + 1) * vw) - 4
            self._tint(strip, x0, x1, sh - 6 - vh, sh - 6, (0, 0, 0), 0.35)
            hh = int(min(float(self.decay[v]), 1.0) * vh)
            if hh > 0:
                self._tint(strip, x0, x1, sh - 6 - hh, sh - 6, vcols[v], 0.8)
        fs["photo_b"] = self.tk.PhotoImage(data=b"P6 %d %d 255\n" % (W, sh) + strip.tobytes(), format="PPM")
        fs["cv"].coords(fs["id_b"], 0, y0)
        fs["cv"].itemconfigure(fs["id_b"], image=fs["photo_b"])
        p = self.player
        name = getattr(self, "cur_name", "") if self.cur else ""
        fs["cv"].itemconfigure(fs["id_txt"], text=(f"{name}   ·   {fmt_time(p.position_s())}" if name else ""))

    def pics_tick(self):
        """Slideshow: a new picture every ~7 s with a short cross-fade; the current game's pictures first."""
        sl = self.slide
        if not self.pic_box or self.id_pic is None:
            return
        from PIL import Image
        now = time.time()
        bs = sl["side"]
        # state message while there is nothing to show
        if now >= sl["next_at"]:
            lst = self.pics.images_for(self.short_of.get(self.cur[0]) if self.cur else None)
            sl["next_at"] = now + 7.0
            if not lst:
                msg = {"offline": "Screenshots unavailable (offline?).\nPut your own images in the 'pictures' folder.",
                       "ok": "No screenshot found for these games.\nPut your own images in the 'pictures' folder."}.get(
                    self.pics.state, "Looking for screenshots…")
                self.cv.itemconfigure(self.id_pic_msg, text=msg)
                sl["next_at"] = now + 2.0
                return
            self.cv.itemconfigure(self.id_pic_msg, text="")
            sl["i"] = (sl["i"] + 1) % len(lst)
            path = lst[sl["i"]]
            if path != sl["path"]:
                img = sl["cache"].get(path)
                if img is None:
                    img = fit_square(path, bs, PAL["canvas"])
                    if img is not None:
                        if len(sl["cache"]) > 24:
                            sl["cache"].pop(next(iter(sl["cache"])))
                        sl["cache"][path] = img
                if img is not None:
                    sl["prev"], sl["cur"], sl["prev_path"], sl["path"], sl["t0"] = sl["cur"], img, sl["path"], path, now
        # cross-fade frame
        if sl["cur"] is not None:
            a = min(1.0, (now - sl["t0"]) / 0.7)
            if a >= 1.0 and sl.get("shown") == sl["path"]:
                return
            frame = Image.blend(sl["prev"], sl["cur"], a) if (sl["prev"] is not None and a < 1.0) else sl["cur"]
            sl["photo"] = self.tk.PhotoImage(data=b"P6 %d %d 255\n" % frame.size + frame.tobytes(), format="PPM")
            self.cv.itemconfigure(self.id_pic, image=sl["photo"])
            if a >= 1.0:
                sl["shown"] = sl["path"]

    # ------------------------------------------------------------ album / stems export
    def album_dialog(self):
        import tkinter as tk
        from tkinter import ttk, filedialog
        ft = self.sel_track() or (tuple(self.cur) if self.cur else None)
        if not ft:
            self.v_status.set("Select a track first.")
            return
        f, idx = ft
        try:
            import soundfile  # noqa: F401
            fmts = ["FLAC (tagged, smaller)", "WAV (tagged)"]
        except ImportError:
            fmts = ["WAV (tagged)"]
        d = tk.Toplevel(self.root)
        d.title("Album / stems export")
        d.transient(self.root)
        fr = ttk.Frame(d, padding=14)
        fr.pack(fill="both", expand=True)
        title = self.title_of.get(f, os.path.basename(f))
        v_what = tk.StringVar(value="album")
        ttk.Radiobutton(fr, text=f"Album: every track of « {title} »", value="album", variable=v_what).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Radiobutton(fr, text=f"Stems: track {idx + 1}, one file per voice (for remixing)", value="stems",
                        variable=v_what).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 8))
        ttk.Label(fr, text="Format").grid(row=2, column=0, sticky="w")
        v_fmt = tk.StringVar(value=fmts[0])
        ttk.Combobox(fr, textvariable=v_fmt, values=fmts, state="readonly", width=24).grid(row=2, column=1, sticky="w", pady=2)
        ttk.Label(fr, text="Looping tracks").grid(row=3, column=0, sticky="w")
        cur = self.v_loops.get()
        v_lp = tk.StringVar(value=cur if cur != LOOP_CHOICES[0] else LOOP_CHOICES[2])
        ttk.Combobox(fr, textvariable=v_lp, values=LOOP_CHOICES[1:], state="readonly", width=24).grid(row=3, column=1, sticky="w", pady=2)
        v_mix = tk.BooleanVar(value=bool(self.muted))
        ttk.Checkbutton(fr, text=f"Keep the current mix ({len(self.muted)} voice(s) muted)", variable=v_mix,
                        state="normal" if self.muted else "disabled").grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(fr, text="48 kHz, one loudness for the whole game, fade-out of 8 s.", style="Muted.TLabel").grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(8, 8))

        def go():
            out = filedialog.askdirectory(title="Export into which folder?", initialdir=self.settings.get("album_dir") or None)
            if not out:
                return
            self.settings["album_dir"] = out
            fmt = "flac" if v_fmt.get().startswith("FLAC") else "wav"
            loops = LOOP_COUNTS[LOOP_CHOICES.index(v_lp.get())]
            muted = tuple(sorted(self.muted)) if v_mix.get() else ()
            stems = idx if v_what.get() == "stems" else None
            d.destroy()

            def work():
                files = export_album(f, out, fmt, loops, 8.0, stems, muted,
                                     progress=lambda m: self.q.put(("export", True, m)))
                return f"{len(files)} file(s) written in {os.path.dirname(files[0]) if files else out}"
            self.v_status.set("Export started…")
            self.bg(work, "export")
        ttk.Button(fr, text="Choose the folder and export", style="Accent.TButton", command=go).grid(row=6, column=0, columnspan=2, sticky="we")

    # ------------------------------------------------------------ live mixer (voices)
    def voice_at(self, e):
        if self.ids is None:
            return None
        y_voice, voice_h, vbw = self.vgeom
        if not (y_voice - 4 <= e.y <= y_voice + voice_h + 18) or e.x < 12:
            return None
        v = int((e.x - 12) // vbw)
        return v if 0 <= v < 14 else None

    def on_mix_click(self, e, solo=False):
        v = self.voice_at(e)
        if v is None:
            return False
        if solo:
            others = set(range(14)) - {v}
            self.muted = set() if self.muted == others else others        # right-click again = un-solo
        else:
            self.muted ^= {v}
        self.mix_visuals()
        self.remix()
        return True

    def mix_visuals(self):
        if self.ids is None:
            return
        for v in range(14):
            m = v in self.muted
            self.cv.itemconfigure(self.vbg[v], fill=PAL["mute_bg"] if m else PAL["voice_bg"])
            self.cv.itemconfigure(self.vlbl[v], fill=PAL["err"] if m else PAL["muted"],
                                  text=("✕ " if m else "") + VOICES_SHORT[v])
        self.cv.itemconfigure(self.id_mixhint, text=(f"{len(self.muted)} voice(s) muted · right-click a voice = solo"
                                                     if self.muted else "click a voice = mute · right-click = solo"))

    def remix(self):
        """Re-renders the playing track with the new mix and swaps it in at the same position (no restart)."""
        p = self.player
        if not self.cur or p.stream is None or not p.playing:
            return
        ft, req = self.cur, self.req
        self.mix_req = getattr(self, "mix_req", 0) + 1
        mreq = self.mix_req
        self.v_status.set("Re-mixing…")

        def work():
            meta, act, intro, loop = self.get_prepared(self.rkey(ft))
            g = self.cur_gain
            if g != 1.0:
                gf = np.float32(g)
                intro = np.clip(intro * gf, -1.0, 1.0)
                loop = None if loop is None else np.clip(loop * gf, -1.0, 1.0)
            return mreq, req, ft, act, intro, loop
        self.bg(work, "remix")

    def on_remix(self, ok, res):
        if not ok:
            self.v_status.set(f"Re-mix failed: {res}")
            return
        mreq, req, ft, act, intro, loop = res
        if mreq != self.mix_req or req != self.req or ft != self.cur:
            return
        if self.player.swap(intro, loop):
            self.act = act
            self.build_strip()
            n = len(self.muted)
            self.v_status.set(f"{self.cur_name} — " + (f"{n} voice(s) muted" if n else "full mix"))

    def shutdown(self):
        self.fs_close()
        self.player.stop()
        self.pics.close()


class CartTab:
    """Onglet « Cartouche » : choisir des jeux/pistes (.ngt) et voir en direct ce qui tient dans la cartouche."""

    def __init__(self, root, parent, settings):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.root, self.settings = tk, root, settings
        self.q = queue.Queue()
        self.games = []                 # [{"path", "title", "tracks": [meta...], "on": [bool...]}]
        self.job = None
        self.busy = 0
        self.pack = None
        self.v_prof = tk.StringVar(value=settings.get("cart_profile", "standard") if settings.get("cart_profile") in JB_PROFILES else "standard")
        self.v_bios = tk.StringVar(value=settings.get("cart_bios", ""))
        fm = settings.get("cart_formats") or list(JB_FORMATS)
        self.v_fmt = {k: tk.BooleanVar(value=k in fm) for k in JB_FORMATS}
        self.v_toasty = tk.BooleanVar(value=bool(settings.get("cart_toasty", False)))
        self.v_tsound = tk.StringVar(value=settings.get("cart_toasty_sound", ""))
        self.v_tsfx = tk.BooleanVar(value=bool(settings.get("cart_toasty_sfx", True)))
        self.v_stext = tk.StringVar(value=settings.get("cart_saver_text", ""))
        self.ev = None
        self.v_info = tk.StringVar(value="Add .ngt files and tick the tracks to keep.")
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        top = ttk.Frame(parent, padding=(10, 8, 10, 2))
        top.grid(row=0, column=0, sticky="we")
        ttk.Button(top, text="Add .ngt files…", command=self.add_files).pack(side="left")
        ttk.Button(top, text="Add a folder…", command=self.add_dir).pack(side="left", padx=4)
        ttk.Button(top, text="Remove game", command=self.remove_game).pack(side="left")
        ttk.Button(top, text="Tick all", command=lambda: self.set_all(True)).pack(side="left", padx=(14, 2))
        ttk.Button(top, text="Untick all", command=lambda: self.set_all(False)).pack(side="left")
        box = ttk.Frame(parent, padding=(10, 4))
        box.grid(row=1, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1); box.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(box, columns=("duree", "flux", "ech"), show="tree headings", selectmode="browse")
        for c, t, w, a in (("#0", "Game / track  (click to tick)", 420, "w"), ("duree", "Length", 70, "e"),
                           ("flux", "Stream", 90, "e"), ("ech", "Samples", 110, "e")):
            self.tree.heading(c, text=t, anchor=a); self.tree.column(c, width=w, anchor=a)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.grid(row=0, column=0, sticky="nsew"); sb.grid(row=0, column=1, sticky="ns")
        self.tree.tag_configure("game", foreground=PAL["accent"], font=FONT_B)
        self.tree.bind("<Button-1>", self.on_click)
        lim = ttk.LabelFrame(parent, text=" Cartridge format (5 % safety margin under each limit) ", padding=8)
        lim.grid(row=2, column=0, sticky="we", padx=10, pady=4)
        lim.columnconfigure(2, weight=1)
        for r, k in enumerate(("standard", "extended")):
            P = JB_PROFILES[k]
            ttk.Radiobutton(lim, text=P["name"], value=k, variable=self.v_prof, command=self.changed).grid(row=r, column=0, columnspan=2, sticky="w")
            ttk.Label(lim, text=f"P-ROM {P['prom'] // MB} MB · V-ROM {P['vrom'] // MB} MB · M1 {P['m1'] // 1024} KB",
                      style="Muted.TLabel").grid(row=r, column=2, sticky="w", padx=10)
        ttk.Label(lim, text="Standard = the largest layout used by official games without a protection chip (MAME software list). "
                            "Extended = 3-bit bank, only homebrews use it: each bank is checked by the jukebox at boot.",
                  style="Muted.TLabel", wraplength=900).grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 6))
        ttk.Label(lim, text="Neo Geo BIOS (neogeo.zip)").grid(row=3, column=0, sticky="w")
        ttk.Entry(lim, textvariable=self.v_bios, width=60).grid(row=3, column=1, columnspan=2, sticky="we", padx=6)
        ttk.Button(lim, text="…", width=3, command=self.pick_bios).grid(row=3, column=3)
        gauge = ttk.Frame(parent, padding=(10, 2))
        gauge.grid(row=3, column=0, sticky="we")
        gauge.columnconfigure(1, weight=1)
        self.bars, self.labs = [], []
        for r in range(3):
            lab = ttk.Label(gauge, text="", width=34)
            lab.grid(row=r, column=0, sticky="w")
            pb = ttk.Progressbar(gauge, maximum=100)
            pb.grid(row=r, column=1, sticky="we", padx=8, pady=3)
            val = ttk.Label(gauge, text="", width=34)
            val.grid(row=r, column=2, sticky="w")
            self.bars.append(pb); self.labs.append((lab, val))
        pf = ttk.Frame(parent, padding=(10, 2))
        pf.grid(row=4, column=0, sticky="we")
        pf.columnconfigure(1, weight=1)
        self.v_prog = tk.StringVar(value="")
        ttk.Label(pf, text="Stream compression", width=34).grid(row=0, column=0, sticky="w")
        self.pb_comp = ttk.Progressbar(pf, maximum=100)
        self.pb_comp.grid(row=0, column=1, sticky="we", padx=8, pady=3)
        ttk.Label(pf, textvariable=self.v_prog, width=34).grid(row=0, column=2, sticky="w")
        ttk.Label(parent, textvariable=self.v_info, padding=(12, 2, 10, 2)).grid(row=6, column=0, sticky="we")
        sv = ttk.Frame(parent, padding=(10, 2, 10, 0))      # economiseur : texte qui ondule, Toasty et son cri (2.5.27)
        sv.grid(row=7, column=0, sticky="we")
        sv.columnconfigure(1, weight=1)
        ttk.Label(sv, text="Screen-saver text").grid(row=0, column=0, sticky="w")
        ent = ttk.Entry(sv, textvariable=self.v_stext)
        ent.grid(row=0, column=1, sticky="we", padx=8)
        self.v_scount = tk.StringVar()
        ttk.Label(sv, textvariable=self.v_scount, width=22, style="Muted.TLabel").grid(row=0, column=2, sticky="w")

        def stext_changed(*_):
            t = self.v_stext.get()
            if len(t) > JB_STEXT_MAX:                   # limite de saisie : 256 caracteres
                self.v_stext.set(t[:JB_STEXT_MAX])
                return
            self.settings["cart_saver_text"] = t
            try:
                b = jb_saver_text(t)
                self.v_scount.set(f"{len(b) - 4 if b else 0}/{JB_STEXT_MAX}" + ("" if b else " (built-in texts)"))
            except ValueError as ex:
                self.v_scount.set(str(ex))
        self.v_stext.trace_add("write", stext_changed)
        stext_changed()
        ttk.Checkbutton(sv, text='"Toasty" portraits (one at random, once per screen saver, at the next track)', variable=self.v_toasty,
                        command=lambda: self.settings.__setitem__("cart_toasty", bool(self.v_toasty.get()))
                        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Checkbutton(sv, text="Toasty sound, or replace it with your own file:", variable=self.v_tsfx,
                        command=lambda: self.settings.__setitem__("cart_toasty_sfx", bool(self.v_tsfx.get()))
                        ).grid(row=2, column=0, sticky="w")
        ttk.Entry(sv, textvariable=self.v_tsound).grid(row=2, column=1, sticky="we", padx=8, pady=2)
        sb = ttk.Frame(sv)
        sb.grid(row=2, column=2, sticky="w")

        def pick_sound():
            f = filedialog.askopenfilename(title="Sound played with the Toasty (over the music)",
                                           filetypes=[("Sound", "*.wav *.flac *.ogg"), ("All files", "*.*")])
            if f:
                self.v_tsound.set(f)
        ttk.Button(sb, text="Browse…", command=pick_sound).pack(side="left")
        ttk.Button(sb, text="Built-in", command=lambda: self.v_tsound.set("")).pack(side="left", padx=4)
        self.v_tsound.trace_add("write", lambda *_: self.settings.__setitem__("cart_toasty_sound", self.v_tsound.get()))
        bot = ttk.Frame(parent, padding=(10, 4, 10, 10))
        bot.grid(row=8, column=0, sticky="we")
        self.btn_build = ttk.Button(bot, text="Build the jukebox ROM…", style="Accent.TButton", command=self.build)
        self.btn_build.pack(side="left")
        for k, t in (("mame", "MAME set"), ("darksoft", "Darksoft folder"), ("neosd", "NeoSD .neo")):
            ttk.Checkbutton(bot, text=t, variable=self.v_fmt[k],
                            command=lambda: self.settings.__setitem__("cart_formats", [k for k, v in self.v_fmt.items() if v.get()])
                            ).pack(side="left", padx=(12, 0))
        ttk.Label(bot, text="   refused if a memory is above 95 % of its limit", style="Muted.TLabel").pack(side="left")
        self.poll()

    # -- liste
    def add_files(self):
        from tkinter import filedialog
        fs = filedialog.askopenfilenames(title=".ngt files", filetypes=[("Neo Geo music", "*.ngt")])
        self.add(list(fs))

    def add_dir(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(title="Folder containing .ngt files")
        if d:
            self.add(sorted(glob.glob(os.path.join(d, "**", "*.ngt"), recursive=True)))

    def add(self, files):
        for f in ngt_group_files(list(files)):
            if any(isinstance(f, str) and isinstance(g["path"], str) and os.path.normcase(os.path.realpath(g["path"])) ==
                   os.path.normcase(os.path.realpath(f)) or g["path"] == f for g in self.games):
                continue
            try:
                h = read_meta(f)
            except Exception as ex:
                self.v_info.set(f"{os.path.basename(f)}: unreadable ({ex})")
                continue
            title = h["title"]
            if not title or title == h.get("game"):                 # anciens .ngt : titre = nom court MAME
                try:
                    title = game_title(h["game"], {}) or title
                except Exception:
                    pass
            self.games.append({"path": f, "title": title, "tracks": h["tracks"], "on": [True] * len(h["tracks"]),
                               "samples": h["samples_bytes"]})
        self.refresh_tree()
        self.changed()

    def refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        for gi, g in enumerate(self.games):
            n_on = sum(g["on"])
            pid = self.tree.insert("", "end", iid=f"g{gi}", open=False, tags=("game",),
                                   text=f"{'☑' if n_on == len(g['on']) else ('☐' if n_on == 0 else '▣')}  {g['title']}   ({n_on}/{len(g['on'])} tracks)",
                                   values=("", "", f"{g['samples'] / 1024:.0f} KB"))
            for ti, m in enumerate(g["tracks"]):
                self.tree.insert(pid, "end", iid=f"g{gi}t{ti}", text=f"{'☑' if g['on'][ti] else '☐'}  {m['name']}",
                                 values=(fmt_time(m["length_samples"] / m["rate"]), f"{m['stream_size'] / 1024:.0f} KB", ""))

    def on_click(self, e):
        iid = self.tree.identify_row(e.y)
        if not iid or self.tree.identify_element(e.x, e.y) == "Treeitem.indicator":
            return
        if "#0" != self.tree.identify_column(e.x):
            return
        if "t" in iid:
            gi, ti = (int(x) for x in iid[1:].split("t"))
            self.games[gi]["on"][ti] = not self.games[gi]["on"][ti]
        else:
            gi = int(iid[1:])
            new = not all(self.games[gi]["on"])
            self.games[gi]["on"] = [new] * len(self.games[gi]["on"])
        opened = {i for i in self.tree.get_children() if self.tree.item(i, "open")}
        self.refresh_tree()
        for i in opened:
            self.tree.item(i, open=True)
        self.changed()

    def set_all(self, v):
        for g in self.games:
            g["on"] = [v] * len(g["on"])
        self.refresh_tree(); self.changed()

    def remove_game(self):
        sel = self.tree.selection()
        if not sel:
            return
        gi = int(sel[0][1:].split("t")[0])
        del self.games[gi]
        self.refresh_tree(); self.changed()

    # -- calcul
    def pick_bios(self, initialdir=None):
        from tkinter import filedialog
        f = filedialog.askopenfilename(title="Neo Geo BIOS (neogeo.zip)", filetypes=[("neogeo.zip", "*.zip")],
                                       initialdir=initialdir if initialdir and os.path.isdir(initialdir) else None)
        if f:
            self.v_bios.set(f)
            self.settings["cart_bios"] = f
        return f

    def selection(self):
        return [(g["path"], [i for i, on in enumerate(g["on"]) if on]) for g in self.games if any(g["on"])]

    def changed(self):
        self.settings["cart_profile"] = self.v_prof.get()
        if self.job:
            self.root.after_cancel(self.job)
        self.btn_build.configure(state="disabled")              # la sélection a changé : l'ancien calcul est périmé
        self.job = self.root.after(350, self.compute)

    def compute(self):
        self.job = None
        sel = self.selection()
        if not sel:
            self.busy += 1                                      # annule un calcul en cours
            self.pack = None
            self.show(None, None)
            return
        self.busy += 1
        ticket = self.busy
        self.v_info.set("Compressing the streams… (games already compressed are reused instantly)")
        self.v_prog.set("starting…")
        self.pb_comp.configure(value=0)
        self.btn_build.configure(state="disabled")              # pas de construction sur un calcul périmé
        prof = self.v_prof.get()
        last = {"t": 0.0}

        def prog(f, eta, name):
            now = time.time()
            if now - last["t"] < 0.1 and f < 1:
                return
            last["t"] = now
            self.q.put(("prog", ticket, f, eta, name))

        def work():
            try:
                pk = jukebox_pack(sel, prog, stop=lambda: ticket != self.busy)
                self.q.put((ticket, pk, evaluate_cart(pk, prof), None))
            except Cancelled:
                pass                                            # une sélection plus récente a pris le relais
            except Exception as ex:
                self.q.put((ticket, None, None, str(ex)))
        threading.Thread(target=work, daemon=True).start()

    def show(self, pk, ev, err=None):
        self.btn_build.configure(state="normal")
        if err:
            self.v_prog.set("error")
            self.v_info.set("Error: " + err)
            return
        self.pb_comp.configure(value=100 if pk else 0)
        self.v_prog.set("done" if pk else "")
        if not ev:
            for (lab, val), pb in zip(self.labs, self.bars):
                lab.configure(text=""); val.configure(text=""); pb.configure(value=0)
            self.v_info.set("Add .ngt files and tick the tracks to keep.")
            return
        for (lab, val), pb, r in zip(self.labs, self.bars, ev["rows"]):
            pct = 100 * r["used"] / max(r["allowed"], 1)
            lab.configure(text=r["name"])
            val.configure(text=f"{r['used'] / 1024:.0f} / {r['allowed'] / 1024:.0f} KB allowed ({pct:.0f} %)" + ("" if r["ok"] else "  TOO BIG"),
                          foreground=PAL["fg"] if r["ok"] else PAL["err"])
            pb.configure(value=min(pct, 100))
        nt = sum(g["tracks"] for g in pk["games"])
        comp = f" Streams compressed {pk['raw'] / max(1, len(pk['streams'])):.1f}x." if pk["raw"] else ""
        if ev["ok"]:
            pr, vr = ev["rows"][0], ev["rows"][1]
            avg_t = len(pk["streams"]) / max(nt, 1)
            avg_g = len(pk["vrom"]) / max(len(pk["games"]), 1)
            more_t = int((pr["allowed"] - pr["used"]) // avg_t) if avg_t else 0
            more_g = int((vr["allowed"] - vr["used"]) // avg_g) if avg_g else 0
            tail = f" Room for about {more_t} more tracks (P-ROM) and {more_g} more games of this size (V-ROM)."
        else:
            over = [r["name"].split()[0] for r in ev["rows"] if not r["ok"]]
            if ev.get("why") and not over:
                tail = " Does not fit: " + "; ".join(ev["why"])[:160] + ". Untick tracks or remove a game."
            elif "P-ROM" in over and "V-ROM" not in over and ev["profile"] == "standard":
                tail = " Does not fit (P-ROM): untick tracks, remove a game or choose the extended format."
            elif "V-ROM" in over:
                tail = " Does not fit (V-ROM, 16 MB in both formats): untick tracks or remove a game."
            else:
                tail = " Does not fit (" + ", ".join(over) + "): untick tracks or remove a game."
        self.v_info.set(f"{len(pk['games'])} game(s), {nt} track(s).{comp}{tail} Jukebox screen: ROM {jb_occupancy(ev)} %.")

    def poll(self):
        try:
            while True:
                m = self.q.get_nowait()
                if m[0] == "prog":
                    _, ticket, f, eta, name = m
                    if ticket == self.busy:
                        self.pb_comp.configure(value=100 * f)
                        self.v_prog.set(f"{100 * f:.0f} %" + (f" · about {fmt_eta(eta)} left" if eta else " · estimating…"))
                        if name:
                            self.v_info.set(f"Compressing the streams: {name}")
                    continue
                ticket, pk, ev, err = m
                if ticket == self.busy:
                    self.pack = pk
                    self.ev = ev
                    self.show(pk, ev, err)
        except queue.Empty:
            pass
        self.root.after(150, self.poll)

    def build(self):
        from tkinter import filedialog, messagebox
        if not self.pack or not self.ev:
            messagebox.showinfo("Nothing to build", "Add games and tick some tracks first.")
            return
        if not self.ev["ok"]:
            messagebox.showerror("Does not fit", format_eval(self.pack, self.ev))
            return
        last_rom = self.get_src() if callable(getattr(self, "get_src", None)) else self.settings.get("src")
        bios, tried = find_bios(self.v_bios.get().strip(), last_rom)
        if not bios:
            messagebox.showwarning("neogeo.zip needed", bios_help(tried, last_rom) + "\n\nPlease select your neogeo.zip.")
            while True:
                f = self.pick_bios(initialdir=(last_rom if last_rom and os.path.isdir(last_rom) else os.path.dirname(last_rom or "")) or HERE)
                if not f:
                    return
                why = bios_ok(f)
                if why is None:
                    bios = f
                    break
                if not messagebox.askretrycancel("Not a usable Neo Geo BIOS", f"{f}\n\n{why}\n\nChoose another file?"):
                    return
        if bios != self.v_bios.get():
            self.v_bios.set(bios)
            self.settings["cart_bios"] = bios
        d = filedialog.askdirectory(title="Output folder for the jukebox ROM")
        if not d:
            return
        try:
            fm = tuple(k for k, v in self.v_fmt.items() if v.get())
            if not fm:
                messagebox.showinfo("No format", "Tick at least one output format (MAME, Darksoft, NeoSD).")
                return
            snd = self.v_tsound.get().strip() or None
            if snd and self.v_toasty.get() and self.v_tsfx.get() and not os.path.isfile(snd):
                messagebox.showerror("Toasty sound", f"File not found:\n{snd}")
                return
            report, files = build_cart(self.pack, self.v_prof.get(), bios, d, formats=fm, toasty=bool(self.v_toasty.get()),
                                       toasty_sound=snd, saver_text=self.v_stext.get(),
                                       toasty_sfx=bool(self.v_tsfx.get()))
        except Exception as ex:
            messagebox.showerror("Failed", str(ex))
            return
        self.v_info.set(f"Jukebox ROM written to {d} ({len(files)} files). {jb_box_note()} See README_jukebox.txt.")
        open_path(d)


def ensure_admin():
    """Windows : relance l'interface avec élévation UAC (une seule fois).  Si l'utilisateur refuse, on continue sans."""
    if os.name != "nt" or "--no-uac" in sys.argv or "--elevated" in sys.argv:
        return
    try:
        import ctypes
        if ctypes.windll.shell32.IsUserAnAdmin():
            return
        params = subprocess.list2cmdline(([] if FROZEN else [os.path.abspath(sys.argv[0])]) + sys.argv[1:] + ["--elevated"])
        exe = sys.executable
        if exe.lower().endswith("python.exe") and os.path.isfile(exe[:-10] + "pythonw.exe"):
            exe = exe[:-10] + "pythonw.exe"                       # pas de console noire derrière l'interface
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, HERE, 1)
        if rc > 32:                                               # relancé en administrateur : cette instance s'arrête
            sys.exit(0)
    except Exception:
        pass                                                      # échec ou refus : on continue sans élévation


def make_app(folder=None, player=None):
    """Construit la fenêtre (sans lancer la boucle) -> (root, extract_tab, player_tab, notebook)."""
    import tkinter as tk
    from tkinter import ttk
    root = tk.Tk()
    root.title(f"NGT Studio v{VERSION} — Neo Geo music")
    root.geometry("1100x860")
    root.minsize(900, 720)
    apply_theme(root)
    settings = load_settings()
    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True)
    t_ext, t_play = ttk.Frame(nb), ttk.Frame(nb)
    nb.add(t_ext, text="  Extract  ")
    nb.add(t_play, text="  Player  ")
    t_cart = ttk.Frame(nb)
    nb.add(t_cart, text="  Cartridge  ")
    cart = CartTab(root, t_cart, settings)
    pl = PlayerTab(root, t_play, settings, player)

    def after_extract(out):
        pl.load_folder(out)
        nb.select(t_play)
    ex = ExtractTab(root, t_ext, settings, after_extract)
    cart.get_src = lambda: ex.v_src.get().strip()          # dernière ROM / dossier de ROM : où chercher neogeo.zip

    # ---- window state: size/position, maximised, full screen (F11), selected tab
    win = {"geo": None, "full": False}

    def valid_geo(g):
        m = re.fullmatch(r"(\d+)x(\d+)(?:([+-]\d+)([+-]\d+))?", g or "")
        if not m:
            return None
        w, h = int(m.group(1)), int(m.group(2))
        w, h = max(900, min(w, root.winfo_screenwidth())), max(720, min(h, root.winfo_screenheight()))
        if m.group(3) is None:
            return f"{w}x{h}"
        x, y = int(m.group(3)), int(m.group(4))
        if not (-50 <= x <= root.winfo_screenwidth() - 100 and -50 <= y <= root.winfo_screenheight() - 100):
            return f"{w}x{h}"                                   # saved on a monitor that is gone: keep size only
        return f"{w}x{h}{x:+d}{y:+d}"

    def is_zoomed():
        try:
            return root.state() == "zoomed" or bool(root.attributes("-zoomed"))
        except tk.TclError:
            return False

    def set_full(on):
        win["full"] = bool(on)
        try:
            root.attributes("-fullscreen", bool(on))
        except tk.TclError:
            pass

    def on_cfg(e):
        if e.widget is root and not win["full"] and not is_zoomed():
            win["geo"] = root.geometry()
    root.bind("<Configure>", on_cfg)
    root.bind("<F11>", lambda e: set_full(not win["full"]))
    root.bind("<Escape>", lambda e: set_full(False) if win["full"] else None)
    g = valid_geo(settings.get("geometry"))
    if g:
        root.geometry(g)
    root.update_idletasks()
    if settings.get("zoomed"):
        try:
            root.state("zoomed")
        except tk.TclError:
            try:
                root.attributes("-zoomed", True)
            except tk.TclError:
                pass
    if settings.get("fullscreen"):
        set_full(True)
    try:
        nb.select(int(settings.get("tab", 0)))
    except Exception:
        pass

    # ---- reopen what was open last time (Player folder, Cartridge files)
    def restore():
        last = settings.get("ngt_dir")
        if not folder and last and os.path.isdir(last):
            pl.load_folder(last)
        cf = [f for f in settings.get("cart_files", []) if os.path.isfile(f)]
        if cf:
            try:
                cart.add(cf)
            except Exception as ex:
                dlog(f"cart restore: {ex}")
    root.after(150, restore)

    def collect():
        settings.update(
            vol=round(pl.v_vol.get()), norm=pl.v_norm.get(), loops=pl.v_loops.get(), autonext=bool(pl.v_next.get()),
            src=ex.v_src.get(), out=ex.v_out.get(), sel=ex.v_min.get(), pre=ex.v_pre.get(), workers=ex.v_work.get(),
            pics=bool(pl.v_pics.get()), rip_wav=bool(ex.v_wav.get()), normalize=bool(ex.v_norm.get()),
            cart_profile=cart.v_prof.get(), cart_bios=cart.v_bios.get(),
            cart_formats=[k for k, v in cart.v_fmt.items() if v.get()], cart_toasty=bool(cart.v_toasty.get()),
            cart_toasty_sound=cart.v_tsound.get(), cart_toasty_sfx=bool(cart.v_tsfx.get()), cart_saver_text=cart.v_stext.get(),
            cart_files=[m for g in cart.games for m in (_NGT_VIRT.get(g["path"]) or [g["path"]])],   # NGT1 : vrais fichiers
            tab=nb.index(nb.select()), fullscreen=win["full"], zoomed=is_zoomed(),
            geometry=win["geo"] or root.geometry(), version=VERSION)

    def close():
        pl.shutdown()
        try:
            collect()
        except Exception as e:
            dlog(f"collect settings: {e}")
        save_settings(settings)
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", close)
    if folder:
        pl.load_folder(folder)
        nb.select(t_play)
    return root, ex, pl, nb


def run_gui(folder=None):
    try:
        __import__("tkinter")
    except ImportError:
        sys.exit("tkinter not found: it ships with Python (Windows/macOS); on Linux: sudo apt install python3-tk")
    make_app(folder)[0].mainloop()


# ======================================================================================
# Ligne de commande
# ======================================================================================
def probe_pics(title="Art of Fighting 2"):
    """Diagnostic of the screenshot sources, run on YOUR machine: python ngt_studio.py --probe-pics "Art of Fighting 2"."""
    print(f"NGT Studio v{VERSION} — screenshot sources for: {title}")
    # 0. name decoding (Arcade Database)
    for short in ("kof98", "mslug3h", "aof2", "wjammers"):
        info = adb_lookup(short)
        print(f"  decode {short:9}: {info['title'] if info else info}")
    # 1. thumbnails.libretro.com (the source the player uses)
    try:
        pb = PicBank()
        pb.index = pb._load_index()
        hit = pb._match(title)
        print(f"  libretro index : OK, {len(pb.index)} files; matches for the title: {len(hit)}")
        for plat, kind, fname in hit[:4]:
            data = _http_get(PICS_BASE + urllib.parse.quote(plat) + "/" + kind + "/" + urllib.parse.quote(fname))
            print(f"    {plat}/{kind}: {fname} — {len(data)} bytes")
        pb.close()
    except Exception as ex:
        print(f"  libretro       : FAILED — {type(ex).__name__}: {ex}")
    # 2. Google Images, plain HTML (unofficial: may be blocked, need JavaScript, or show a consent page)
    q = urllib.parse.quote(f'"{title}" Neo Geo MVS gameplay screenshot')
    for label, url, ua in (
            ("google udm=2", f"https://www.google.com/search?q={q}&udm=2&hl=en&gl=us", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"),
            ("google gbv=1", f"https://www.google.com/search?q={q}&tbm=isch&gbv=1&hl=en&gl=us", "Lynx/2.8.9rel.1 libwww-FM/2.14")):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Language": "en", "Cookie": "CONSENT=YES+; SOCS=CAI"})
            with urllib.request.urlopen(req, timeout=20) as r:
                body = r.read().decode("utf8", "replace")
                final = r.geturl()
            thumbs = re.findall(r"https://encrypted-tbn\d\.gstatic\.com/images\?q=tbn:[\w\-_]+", body)
            flags = [w for w in ("enablejs", "consent.google", "unusual traffic", "captcha") if w in body.lower() or w in final]
            print(f"  {label:13}: HTTP OK, {len(body)} bytes, {len(set(thumbs))} thumbnails found, flags: {flags or 'none'}")
        except Exception as ex:
            print(f"  {label:13}: FAILED — {type(ex).__name__}: {ex}")
    print("Send me this output (and ngt_studio.log) to decide what is worth building.")


def selftest(ngt=""):
    """Diagnostic de l'installation (lecture impossible, pas de son…).  Chaque ligne dit OK ou ce qui manque."""
    def say(ok, msg):
        print(("  OK    " if ok else "  FAIL  ") + msg)
    print(f"NGT Studio v{VERSION} ({BUILD_DATE}) — Python {sys.version.split()[0]} — {sys.platform} — script: {HERE}")
    try:
        import tkinter
        say(True, f"tkinter {tkinter.TkVersion}")
    except Exception as ex:
        say(False, f"tkinter missing ({ex}): the GUI cannot open")
    say(True, f"numpy {np.__version__}")
    try:
        import sounddevice as sd
        say(True, f"sounddevice {sd.__version__}")
        dev = sd.query_devices(kind="output")
        say(True, f"default audio output: {dev['name']} ({dev['default_samplerate']:.0f} Hz)")
        t = np.arange(int(OUT_RATE * 0.5)) / OUT_RATE
        x = (0.2 * np.sin(2 * np.pi * 440 * t)).astype("float32")
        sd.play(np.column_stack([x, x]), OUT_RATE)
        sd.wait()
        say(True, "0.5 s beep sent to the sound card (you should hear it)")
    except Exception as ex:
        say(False, f"audio: {type(ex).__name__}: {ex}")
        print("          -> pip install sounddevice  (or check the Windows audio output)")
    eng = find_binary()
    say(bool(eng), f"engine: {eng}")
    if ngt:
        try:
            meta, regs, blob = load_track(ngt, 0)
            with tempfile.TemporaryDirectory() as tmp:
                base = os.path.join(tmp, "t")
                open(base + ".stream", "wb").write(regs_to_port_stream(regs, meta["k0"]))
                open(os.path.join(tmp, "v.bin"), "wb").write(blob)
                r = subprocess.run([eng, "--va", os.path.join(tmp, "v.bin"), "--replay", base, "--replay-out", base + ".raw",
                                    "--replay-len", "3"], capture_output=True, text=True, errors="replace", timeout=120, **_NOWIN)
                n = os.path.getsize(base + ".raw") if os.path.isfile(base + ".raw") else 0
            say(r.returncode == 0 and n > 0, f"replay of {meta['name']}: code {r.returncode}, {n} bytes, {(r.stdout or r.stderr).strip()[:150]}")
        except Exception as ex:
            say(False, f"replay: {type(ex).__name__}: {ex}")
    return 0


def main():
    dlog(f"--- NGT Studio v{VERSION} ({BUILD_DATE}) Python {sys.version.split()[0]} {sys.platform}")
    ap = argparse.ArgumentParser(description="NGT Studio — with no option, opens the graphical interface.", formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", nargs="?", help="folder of .ngt files to open directly in the player")
    ap.add_argument("--cli", action="store_true", help="extract without the GUI (with --src and --out)")
    ap.add_argument("--src", help="ROM (.zip) or folder of ROMs")
    ap.add_argument("--out", help="output folder for the .ngt files")
    ap.add_argument("--keep", default="auto", choices=["auto", "music", "all"],
                    help="tracks kept: auto = music + jingles (default), music = music only, all = everything, SFX included")
    ap.add_argument("--prelude", default="auto", help="driver initialisation commands: auto, or e.g. 7 or 3,7")
    ap.add_argument("--min-len", type=float, default=45.0, help="with --cli: tracks shorter than this (seconds, one loop included) are short tracks (default 45, 0 = no limit)")
    ap.add_argument("--short", default="ask", choices=["ask", "skip", "loops", "keep"],
                    help="with --cli: what to do with short tracks: ask (default; when not interactive: loops), skip, loops (keep the ones that loop: short game music loops; skip the others), keep")
    ap.add_argument("--normalize", action="store_true", help="normalize the .raw/.wav written (peak at -1 dBFS)")
    ap.add_argument("--raw", action="store_true", help="also write, per track, the raw PCM (.raw) and a .json")
    ap.add_argument("--wav", nargs=2, metavar=("NGT", "WAV"), help="convert a track of a .ngt to WAV (options: --track, --norm, --seconds, --start)")
    ap.add_argument("--rip-wav", action="store_true", help="with --cli: also write one .wav per track")
    ap.add_argument("--seconds", type=float, default=0.0, help="with --wav: duration to simulate like the player (48 kHz, loops included); 0 = full render at 55,944 Hz")
    ap.add_argument("--start", type=float, default=0.0, help="with --wav --seconds: start point, in seconds")
    ap.add_argument("--norm", default="track", choices=["none", "track", "game"], help="automatic volume for --wav: none, track (per track) or game (per game)")
    ap.add_argument("--track", type=int, default=1, help="track number, 1 = first (for --wav and --voices)")
    ap.add_argument("--check", metavar="NGT", help="check the integrity (CRC) of a .ngt")
    ap.add_argument("--info", metavar="NGT", help="show the header and track table of a .ngt")
    ap.add_argument("--voices", metavar="NGT", help="summary of the voice activity of a track")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1), help="number of processes for the extraction")
    ap.add_argument("--cart", nargs="+", metavar="NGT", help="jukebox ROM: evaluate these .ngt files (all tracks); builds the ROM if --out and --bios are given")
    ap.add_argument("--upgrade", metavar="DIR", help="convert old NGT1 files (one per track) found in DIR into NGT2 files (one per game); originals are kept")
    ap.add_argument("--profile", default="standard", choices=sorted(JB_PROFILES), help="with --cart: standard (P1 1 MB + P2 4 MB) or extended (P2 8 MB)")
    ap.add_argument("--boxes", metavar="PNG[,PNG...]", help=f"with --cart --out: one to {JB_BOX_NP} picture sheets of objects rotating in the screen saver (frames on a magenta #FF00FF background, read row by row; the first sheet gives four objects out of five, the others share the fifth in turn); default: the built-in sheets, each one replaced by {JB_BOX_FILES[0]} ... {JB_BOX_FILES[-1]} of the same number if present next to the program; \"\" = none")
    ap.add_argument("--toasty", action="store_true", help='with --cart --out: a "Toasty" portrait (one of the built-in ones, drawn at random) shows up in the screen saver (bottom right, in front of everything), once per screen saver, when the next track starts, with the built-in Toasty sound')
    ap.add_argument("--toasty-sound", metavar="FILE", help="with --toasty: your own sound instead of the built-in one, played with the Toasty over the music (WAV; silences trimmed and level normalised automatically)")
    ap.add_argument("--no-toasty-sound", action="store_true", help="with --toasty: no sound at all (the built-in Toasty shout is (c) Midway / Warner Bros.)")
    ap.add_argument("--saver-text", metavar="TEXT", help=f"with --cart --out: your own screen-saver wavy text ({JB_STEXT_MAX} characters at most; capitals, digits and punctuation, accents removed)")
    ap.add_argument("--formats", default="mame,darksoft,neosd", help="with --cart --out: output formats, comma-separated (mame, darksoft, neosd)")
    ap.add_argument("--bios", metavar="ZIP", help="with --cart --out: Neo Geo BIOS zip (neogeo.zip), source of the security block and of the font; if absent, looked for next to the program (exe or script) and in the folder of the last ROM opened in the Extract tab")
    ap.add_argument("--no-uac", action="store_true", help="Windows: do not ask for administrator rights")
    ap.add_argument("--elevated", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--version", action="version", version=f"NGT Studio {VERSION} ({BUILD_DATE})\n" + CHANGELOG)
    ap.add_argument("--album", metavar="NGT", help="export every track of a .ngt as a tagged album into --out (FLAC if possible)")
    ap.add_argument("--stems", type=int, metavar="N", help="with --album: export track N (1 = first) as one file per voice instead")
    ap.add_argument("--format", choices=["flac", "wav"], default=None, help="with --album: audio format (default FLAC if available)")
    ap.add_argument("--loops", type=int, default=2, help="with --album: loops before the fade-out (default 2)")
    ap.add_argument("--probe-pics", nargs="?", const="Art of Fighting 2", metavar="TITLE", help="test the screenshot sources (libretro, Google) from this machine")
    ap.add_argument("--selftest", nargs="?", const="", metavar="NGT", help="diagnostic: Python, modules, sound card (beep), engine; with a .ngt, replays 3 s of its first track")
    ap.add_argument("--build", action="store_true", help="rebuild the engine from the m1render/ folder (C/C++ compiler required) then exit")
    a = ap.parse_args()
    if a.build:
        print(build_binary() or "failed"); return 0
    if a.album:
        n_tr = len(read_meta(a.album)["tracks"])
        if a.stems is not None and not 1 <= a.stems <= n_tr:
            print(f"--stems: track number between 1 and {n_tr}")
            return 2
        fmt = a.format
        if fmt is None:
            try:
                import soundfile  # noqa: F401
                fmt = "flac"
            except ImportError:
                fmt = "wav"
        files = export_album(a.album, a.out or ".", fmt, max(1, a.loops), 8.0, (a.stems - 1) if a.stems else None)
        print(f"{len(files)} file(s) written:", *files, sep="\n  ")
        return 0
    if a.probe_pics is not None:
        return probe_pics(a.probe_pics)
    if a.selftest is not None:
        return selftest(a.selftest)
    if a.check:
        ok, msg = check(ngt_data(a.check))
        print(("OK  " if ok else "ERROR  ") + msg); return 0 if ok else 1
    if a.info:
        h = read_meta(a.info)
        for t in h["tracks"]:
            t.pop("game", None); t.pop("game_peak", None); t.pop("samples_bytes", None)
        print(json.dumps(h, indent=2, ensure_ascii=False)); return 0
    idx = max(a.track, 1) - 1
    for f in (a.voices, a.wav[0] if a.wav else None):
        if f:
            nt = len(read_meta(f)["tracks"])
            if not 0 <= idx < nt:
                print(f"--track: track number between 1 and {nt}")
                return 2
    if a.voices:
        meta, regs, _ = load_track(a.voices, idx)
        act = voice_activity(regs, meta)
        for v, name in enumerate(VOICES):
            print(f"{name:10s} active {100*float((act[v] > 0.05).mean()):5.1f} % of the time   mean level {float(act[v].mean()):.2f}")
        return 0
    if a.wav:
        if a.seconds > 0:
            meta, g, x = playback_pcm(a.wav[0], idx, a.norm, a.seconds, a.start)
            if not len(x):
                print(f"{meta.get('name')} : nothing to write, --start is past the end of this track (it does not loop)", file=sys.stderr)
                return 1
            save_wav(a.wav[1], x, OUT_RATE)
            print(f"{meta.get('name')} : {len(x)/OUT_RATE:.1f} s at 48 kHz, gain x{g:.2f}, peak {int(np.abs(x.astype(int)).max())}")
        else:
            meta, pcm = render_track(a.wav[0], idx)
            g = gain_for(a.norm, meta, pcm)
            pcm = apply_gain(pcm, g)
            save_wav(a.wav[1], pcm, RATE)
            print(f"{meta.get('name')} : gain x{g:.2f}, peak {int(np.abs(pcm.astype(int)).max())}")
        return 0
    if a.upgrade:
        n = ngt_upgrade(a.upgrade)
        print(f"{n} NGT2 file(s) written")
        return 0
    if a.cart:
        uniq, seen = [], set()
        for f in a.cart:                                  # même fichier donné deux fois : une seule fois dans la cartouche
            k = os.path.normcase(os.path.realpath(f))
            if k in seen:
                print(f"{f}: given twice, kept once")
                continue
            seen.add(k)
            uniq.append(f)
        sel = [(f, list(range(len(read_meta(f)["tracks"])))) for f in ngt_group_files(uniq)]
        tty = bool(sys.stdout and sys.stdout.isatty())

        def cli_prog(f, eta, name, _last=[-1]):
            pct = int(f * 100)
            if pct == _last[0]:
                return
            if not tty and pct % 10 and f < 1:
                return
            _last[0] = pct
            msg = f"Compressing the streams: {pct:3d} %" + (f", about {fmt_eta(eta)} left" if eta else "") + (f"  {name}" if name else "")
            print(("\r" + msg.ljust(78)) if tty else msg, end="" if tty and f < 1 else "\n", flush=True)
        pk = jukebox_pack(sel, cli_prog)
        ev = evaluate_cart(pk, a.profile)
        print(format_eval(pk, ev))
        if a.out and ev["ok"]:
            last_rom = load_settings().get("src")
            bios, tried = find_bios(a.bios, last_rom)
            while not bios:
                print(bios_help(tried, last_rom))
                if not (sys.stdin and sys.stdin.isatty()):
                    print("Give it with --bios path/to/neogeo.zip")
                    return 2
                try:
                    f = input("Path to neogeo.zip (empty = cancel): ").strip().strip('"')
                except EOFError:
                    f = ""
                if not f:
                    return 2
                bios, tried = (f, []) if bios_ok(f) is None else (None, [(f, bios_ok(f))])
            for f, why in tried:
                print(f"Rejected {f}: {why}")
            print(f"BIOS: {bios}")
            fm = tuple(x.strip() for x in a.formats.split(",") if x.strip() in JB_FORMATS) or JB_FORMATS
            if (a.toasty_sound or a.no_toasty_sound) and not a.toasty:
                print("warning: --toasty-sound / --no-toasty-sound are ignored without --toasty", file=sys.stderr)
            if a.toasty_sound and a.no_toasty_sound:
                print("warning: --toasty-sound is ignored with --no-toasty-sound", file=sys.stderr)
            report, files = build_cart(pk, a.profile, bios, a.out, formats=fm, boxes=a.boxes, toasty=a.toasty,
                                       toasty_sound=a.toasty_sound, saver_text=a.saver_text, toasty_sfx=not a.no_toasty_sound)
            if a.boxes is None:
                print(jb_box_note())
            print(f"{len(files)} files written to {a.out} (see README_jukebox.txt)")
        return 0 if ev["ok"] else 2
    if a.cli:
        if not a.src or not os.path.exists(a.src):
            print("--cli needs --src: a ROM (.zip) or a folder of ROMs" + (f" (not found: {a.src})" if a.src else ""))
            return 2
        a.out = a.out or os.path.join(HERE, "ngt_output")
        pre = "auto" if a.prelude == "auto" else [int(x, 0) for x in a.prelude.split(",") if x]
        def ask_cli(game, n, n_loop, ml):
            if not (sys.stdin and sys.stdin.isatty()):
                return "loops"
            print(f"\n[{game}] {n} track(s) shorter than {ml:.0f} s, {n_loop} of them loop (game music with a short loop).")
            r = input("  l = keep the looping ones, skip the others (default), s = skip them all, k = keep them all, "
                      "add ! to answer the same for the next games: ").strip().lower()
            pol = {"s": "skip", "k": "keep"}.get(r[:1], "loops")
            if "!" in r:
                opts_cli["short"] = pol
            return pol
        opts_cli = {"min_len": a.min_len, "short": a.short, "ask_short": ask_cli, "keep": a.keep, "wav": a.rip_wav,
                    "raw": a.raw, "workers": a.workers, "prelude": pre, "normalize": a.normalize}
        res = scan_dir(a.src, a.out, opts_cli)
        print(json.dumps([{"game": r["game"], "tracks": len(r["tracks"]), "note": r["note"]} for r in res],
                         indent=1, ensure_ascii=False))
        return 0
    ensure_admin()
    run_gui(a.folder)
    return 0


# ======================================================================================
# Moteur d'émulation intégré (m1render : Z80 + YM2610/ymfm), compressé zlib + base64.
# Windows x86-64 (.exe) et Linux x86-64.  Source complète : dossier m1render/ de l'archive des sources.
# ======================================================================================
_ENGINE_B64 = {      # moteurs intégrés : xz + base85 (Windows x86-64 statique, Linux x86-64 sans symboles)
    "nt": """
{Wp48S^xk9=GL@E0stWa8~^|S5YJf5;#pSj{#^hjmX2@$7x(N1yXy4+lmRb9?|kO<2^mBJDgRT=*3lIHo?)DV74`{wtZTIGR1lsf
%5l%dM=QwdB1Qf|`m<S&as&y0Z#ryV#Z(2{s3#E$T%V6oxxDuCcPVs%x}#*U_~H*-yvYkRb&98nv}!5v{~S(#t(u^q7yk=<=nP_i
9SYwpX#r8Ujkg=f<deC^@QM9K>E^8_^HtLczzQ8}k`XU~zq4XLStM^zImTt%asY|vHsA;t>EAigyD<3l&<W^z?r+;M79%*(F&;g<
ryTJ#t9?+|jN4ss5Xrc_BHt>8RgZG#HAAq%{&-JxB798V3zt?%e@t|HZTgs@bX4@7xN27<aFnJ3TnD~Mx)Q26hqd<$7ve|GyVdud
ZBJ<UjYWUH29IlDkT?KMk23eng^UXquJgxt8Nk@L)C7KqS-hDF8&##*`a1(kq&zi!anFQpH2?34ukpp`S|*gKx%lp)WQ-+Jyf8Uq
S6pvF$yxHmK=RTUZR=UVxjsm{;5bbBP(g127BH2(YWsX4G0G7HrAJC*rT$;c#)o#{QmSeELH)^iZmk`~_w2FCZrycBL83&Grt$cO
<z7gdhtL0tYT&Qn0#{jDMy60bhf{fK4zEP2NI-kkl{$fA{Y};JbWTzLLF0_*!`=n{qid1jFy!b;hNJbMiQjl0HRWB;-<6YJyt?+#
exuqFLD8Z^wk0E<aYB@jZjyvWq|tyzHJoD80w)wXfgO6GWR{rg*Kv_IH!S@s|2=LT%VUoq{^hHU5l&%p?T)-YM5}yru={CYCfvo6
B08H=GLcC(y}mm<MxSjw7k`|r%Ac7w7-tc6zy;liNdhlMLc&MKuuJxDiDOOUIlzqin(eA9)~6EInKST%MWB!RyK26TCc3r+u%WLW
$XI7;qGHo5cp2`=b89L^-9oyTagFm|`SjvRN98C%UtE7$m>;x#+F=`mVjFywKKOvn*y(no6CZA_xR6<H*ZXIIW6$79R=xArFl^)8
3LSxigWvmXMj{cH8!upp3F~_iaxqk|j97YJKzXR0XZQLGF6fr>nYfsm0H`Li>s6HC@h3NJ<;dNuBCM=YnVUE}E-7b!<%g?#nQok*
Ct+G>`d6J|FK*21>;`5o3lZWN@8P2UPV@i{G4o=~kDZOEZCYQB9M$@g>vw=}rKnJcE!EWET&0VR;kIJbHs|*iU0_bG(Q=7p9;Vbk
$dfwT|A0J>cO)cI`BSi8`8mL4z94uMno+6vv}r0Odu_LcWQ;5q{&g3vlsK5u0ILUbZU_fg7Z*H5L4q{_toPJLNb`WM7E;RVxvG>K
NEk&#HK4iVgx`s!F50oL65qZB`CazA==B{2;(%m`5<H)vtO|6DZ<-M_41wm=Y1R|~yc?!6pRCxf93R_Yc63EF89{OGrk}urMo@B$
p9b1T|0-X@jv=N<+v{VE0eh7<?x9Ig=nuO#UM`c>SlQ}~r2~;!gOWx0qR0s|dN5#U2_|Z$qSa9XG6ZXfv~eo^Hhx`o7bMtPwsix9
dD4+~(0J%;amHe^0LU-=wJfaz`hjupBSx;=c_VVLqlx-6rCmVr5n@EPj{Y2{Edjy^5vj}nM4Cv9eNZy%uZV2T&wnyAs4YIdIEh2W
DaxnYJ+2l!eX6TV>i$`$;I880;*$U2ew8I&6!KyQNKRB`XrkrqPGaflx+MFGPn3Dq{A>MWem@H#Cm6J-b^&0s#)>Fo9aiJ3@!c!S
xEO41G1w|BLVQZ52OaL>N!5Qx^eO6oBYSUEa~ahK$1Hf~p+E%1xVdhY`!T?G;AJ5m0z%<7!jvcWQA{&;F|b<|W(F?+h{j6jWafaF
z`xRhlZ5<m7mk>qNw2I6ln7SD!9ii;UTyR=$?w*bG+#iTO{%hvRga!9cG2E^ddpa5<XuX$VePP~79;K$T5vDia6?CWH-G*JPrtIW
?kma-H(YsPvZxga$@GS%mdEG}*b2M^D@8i$wS|hV2ks{ZX-pM@yZb$j_jy0YTl@h0isR*!>gy41&L&Oj3s|I|>`xTY*A`KKAaSxE
0;Xk}LS=y@u+GUl5A>L5n?9MY$@F=VbxeiNrSqK|O@Ya}lU(2AQPgJ_yu-efJi0*Q(DXZ-eS!vD;oC6XRlG1n*Oz&=TzXEqyxMv>
!b&k|dZt`$l48SXc>a`ics-0j3h|3ep}N-r^=zv;a6ml+aAO2TY~bL=ptG*y>}RQ6ptauMuC{0VpG9gPur*50)6RZWVDay$&4gSt
XO$#zL|ieQL#kc^g%(!s<jH&c{MuSpWvH2l+T;}XADZr}b1;SCAYfRb)kKSC!e!9*LpD09URzf2(B7U>#Xp{k!QXik*Th|q;g_K_
;1J1~_7M9Hk8cQNS}%@Qu;K$U3u}UQM=$aFte|@bY6vEr15cLef3NSWFe<o~|HRhh_;L9+3r)cHNbJf&)8z=5oZQrmQf||h%nE=C
BsG96ZI6A~T7Ci|6_t*<2(I$YtamN3sRr_a%}O(=gf|0dl|V}$N2{98@|JH=Mh>_M8rb}@<mtLY%hB-5s+MGg3ILj~&lQfynWwCT
(s(D6At>aO_Abc2R|rYwM!sc%yShSnY5iou3kuVvC;iwthVT3?fW`@?N%%QjY@E5Z(n5`i&xK6v0&$$pgv_qICi6NDNlzCzUw~5W
g;jJh$xa7uX_p_g_EZF13<SN{lE!aXPr1iD@tn4K1U%i~3$`Zs<<9q+wRRdWx3F;L$|_a*4T6_+L=ni2#J^zt$wZJ2z`^@HAK_Q-
yvVi<M~5uOs`>hD3VcUEk)w~=!c8G^F@ei$Be<GCQkLal4|E5R!feq<wWrmNZuim(q(fY`Xz^W3%vxg~%+*%dk(t*k3Icag6(t6@
;;<B=Y8Nb@1oM}E&VHlpep#^gjemb7(N}PSIZY2I6|OJ9^nL-a!KF4a3hiUIbJtC-b+|EXrgzT>RnI*pgAi1=!+HGSa;Wd2c>N$Y
VQZDXL7x=%^u-7>Ds3aFtx%4@oqU^R!U8O{$G`$R*zlB(b$0-Uce93$Qu!<ZLC=}=kY(yGl2;$SZV^EM^+xZiCWG+dHFq{WVpEc^
IU3MCrRSR5N>YyVP@gK}at_R(SU`@9oWXdlx~;J;bZGOKTD@i#X<>KsG_|$*bl(-Nu+?x2yz-$SVGD!=Z<Ewmq|87^TG2TQH4)R`
+p?ffdqjm?1b7CKMc9^sMlHnuJf!ebWRhWlQJ-EIIj;D1*h*q!R%*fkbr&hsOIXTntp~cZCtOO?;I?f-d-}QXWZ=XmWIkxPM0P<U
&ouzOtZ%3AhBLjm4o5tWcDN9sXpn(?Z|VpU4t|enK;|LNuPYi}VFadgm&4HBp{iQhIL3k+B_F*5__dn$f_iS7h5c;`nkH0mb7Chu
uxK@w9HD|{yn2)yLum2o;XM5e;@VpHQLZON|68Nsn{k~tQGMp2>dK4TG_2deWhMYnI__B2oRcF=$$EIH1GGbZNc%?Ymn<3-AA+b>
-wNp{kvAT2OMhP<Gd!YpY06w<ttt6x{+}S|lM}Z$|CqS<`+wFVx5zmp;~bz%iP$f;g{UnbtBq-*t0pMAAYBY@J`BD&crq9QYO^D7
RcX*KZW?*dcthiAclL_53E8kxP0Y~@JCbEAskUs5>O`gvaVX_%n@<D!EbQRfD15B&uP`eaepFEw@F%a*$a%2T$%DV^etc-!oqIWe
xO(PLxQDx&GgCO;Z&R@5tx_^k0ASK|!@#7X;zaU;3~;!i`r_<MQ|9^<f3$?8qXR04p=kZMl&48c?j}{d>mc`ZD^3(9;^s<~#@%~#
RNdY~pc8;<_Z`25BQTf>3jshzaAb%q(4YHil1NS#Vmw^CAnhN)5uv=-aNE%YYB=zWq+G0hGrqXI`&QVG4q2P3$s&SIejP!0u4wgE
4yR9fUzYgc?1f*D$C+Ctsh;!SivzW2&E+@pF4|4)#zuG(A)BRobiJEaRRp&T?OF$j&06i=@qXFP&kAecuLUCk5VFDU0nP)_gh<Z1
*HEfhs7?b6rw^F8_81>OLCwta)njLjadG(KahOw}p2c4Z;WS$e;7~UU6iq{L!r!TsrRfw$2{y7)icvDjsJ`>$W|E_WvwpH2)Cyka
e3xj73rQ|(w2J+WHTw7#d|~Qr0#+F@N!EK^A4E<UmrNn{VP2u$3S7TUhzZTx`e=-K$UhY+uZD%kL&zbGtW{im#l0riM5%*uDoxGU
BL&vDtk2}VR8%i6q{!aX%|UE!(FcgL5YX1@#Fs6=l?$)>LkW+nsE1O!5zbzrW(Xg|@?vf=fxjQ23s=7xCxvbK0A;QPfZ7%cg-DI=
Y~hHR<~3B?wsMT#$Ckt+xV1Wx?ve%7ml8P-MQRx5?9m>Gpg+%fW!LkA%KI5h*puXq3y#7Jm~XA5Co~d+hSt%-)Dq-p-upFyW!l|E
m?oiRp)x!eSUN{Ed^O{ECpWbex_qNqI25_M-rn8N;wJ0BeBLPUb)1&cTM2>|)%a9lBErSiv<2#ev|U}XEr!Mna_nL^;1Od0u6b3X
epdk_Zc+JL4>L)Of+A>$eAhlUP**%YCNi`vt|udGI?XOVw+Wg2cMBYIyiOWqu~41?W2Iv}t<?n@j*?`o(D04*gO_3O`8$z;?Ph|(
t0-A2=L)p=Gk?u4by^J4+7AeH3i}x}{Udv&TXt}iWkz`B55)A0ShCgwgQKk#|6jV9cFxMjt_O!`^GShqGh6q`et)&$wk&Tr)iw;X
K&aeNyhjiIWT}9P%5Vg1Nmly1cYg_cV9tm6^F$0?ppqT}^j~n=9?#R)0q5GZyD3b`C1+FT0#^8YXH>K?P5iLz&h4PD09Kb6LG)vb
R<;Rgj0=*iG!^B?)iEI_MoiNGNX~w8da;mA5`fRa&jZfw2-s{d;Z2D(s=hHwe`V>!EW{&|_vy8LjO>RYflx(>h12kW?B)q`BTE^K
$E;HOAIHlpEz2^}MVoi^C?Q%PAW-bj{r{#Y;h3{Xif*g{C~~wnoH!0b_pzF=)(?MzNOfis$^c1qf+$IiC>$svkJA!vqrZLq;8%;P
%5W7C;ZKzKc;)m5><TFF8X`z4_$u$e;4)a6zdbJkF6&&6R(8rNIxf$WhK7#nZuwig`j%&FQW8+utnLN+3wx%NVGI4uZc$~&1G1RB
>%zC^O40$oHTH`97U<ZO5EN?jZW@)7y$N91XC&)Jg`VW|_S1s5gow9a6<~-`<83Mp`x%=Xn|vf$R9foJefOMbBg);&T~q5_Rn{<X
9wSflaYZAPb@O{hUT+cc>GVM$_lZ+VDT#&O{x`vs>?3F;6r&CSc&qk(yGCtt8UWjdNH`9AImj!bXnS5}xXss2R&G7J(X2V*PTa`g
f6d$T8-w&C@}bdBTtoZ;^)$6|Kp6S0B2fxG+4@Fa><ud#9Fq@PAzFXSFdBTdLV<IK+^1`gmKzZ<Xu!TKe9W;_FOoFSMq71!e7Wy!
2NsiN9{I0rwz1n^-vgb}V3|4Ea%q_x#pn)IyJS+9O%e-qEG#A`>b{k5j&BL-kML}}>2QKn)y4YfVBg~^&$RU$e5gHny`6tPRPLhP
)zk@cW|x3pT+Bn*sF^JX;YvQcl)X~HXpycxw*bfJUq($#RW`oLpud-|Xs0z11rErZSGhX*P-HwfJ4H^|hNNh9?&BfgcBiDkgSveK
j;lb_ndl4(5q#4+cPeanaA3)C))|BhGw*IH(USw%uqJFTh=;iLyvh<^mzModX-Wv<4c6F=!u-;pp55ISY3i&por3(*0aN<3b|ZfJ
c9PX#V?Teo2DvZ*n&x+=xMT7V^1~feDkz(oIA&5l5MA|`3P4X5ExxCL$Ya3&sHQ7=`hejMxaa6QVRaLr!s~V~l>BYgIWg9fT!CM{
T4-DpVh~G&=<s=<94!s(xcc)z)2t>U)tNkoTs@IJXrN@cB-9{QwrU*V1-C$Jboxh7VY0E&c+X_2Gj7tr`)=cIvSE|(vcxrU{57@g
0A`*fl$7~V-SRmEDe()!Ne=uLWtSfQ>j_ZIviEDtjg}=@YDI}xTLHNbEELf__psm9li=T|Hn!lJL{=Z6!r83yV#zAAFhLuNma)fo
)8MvRqkwZJ(+Sz0@Vl*lcH`*XS}2sCFdrAaGBm`>6!Y1T!=lQ<kOZMCu&G9r*di%Zk}a8#TCW<gOSbZ8PY9JMFgW{wkIxZm);S6U
+~C-yDK)HVl{-um<}~|RWNl{S9Fz2W=&hE756%?A&DVi?lH*%#1=>p=M+0({{SUt4Is;l}OY@M?%$%d>8@vVK0;Uky8<x@gRmGB(
I)T`yGh=T_9T_^Di&q>p>YhDWd!fk}ctHM*Um$N|&ZA_LE<vTw)P9Awkg^G_%K<=J3tXdBh>ENYv6WM}h$L}s7ch9%g&AO(Ib$3x
PnG?%=XI?TE)JCe<qw!VwCN+m^?e4Ta0US?oy}h@NTbSw{_dpG5LE#pD6?wpu?gj%+D*d%f6F7$I4-=&@@<uS7k~O(s+=+(Me^h)
|FSfMtjU**vq>xF7?Vg{y{|At<)StO-=o=@N;vP_dKX#qAG8deX^Uaw#1h<wEfVv+oE&q>K?fp~x<yBa9d3OCcn|o~r_^!E)CsV3
0l3AQB1?0XtGDyDu%a3Dq`DUlkgBomtEv4y+DGA3?_y<k6bQGjn-AI4tIdM2-<wEzNF`db{f>Gbg2lVs-=uy0Yrd<ZIjm(VE*&Um
R~)qA)@<Sc_)loOw|E}465rU0GPL<Njy<CP0(7tfUdKcL$@EAhDY$UR?sSR`*JG8820uA%_(Ouq^{rV%UPqvx!^_0M!FGbeq2Qr$
VNy8DROObO!k!#1H75_w2y=dY)oSSdMCE?E-=V?joh;xAI(X41-wf#w;?x~UI~Gx$?MCjJ6e<@ZP#qZ8*gCLDtc?n*bJ#KJOAUO#
0fhcl9zfq>K~6p+orBfqp)cu93h^Xy(dG*yg8kob!%m*?+kJnXsa}l{jOcSRPP0n((X)R#IwDPOgLH?l06g&AuCe10^5wz8hiKE^
Tq`JE?7}<Gz)b13#JbBN0yZM1GiFfpVRJ&j!j%dSa4M}2HD#FmnSik<oPwvsMA$)->#G=lzJdl7)#G2uYFb@&Z3)AV^@Le(K&dBT
pfj!0AjSon!3fuDGc)^{TuQp2lF4~LN*E;YhaOR1s8NH~rSHCKO2sLatdZStX?fM<P0ydADIK-Ww@>Q|Jaw8UqF2RQ60)ti5pkw<
m^$@c?H_WBpmt05`zey9iGu(xDc-lD`lZL}h&vt&dg1QSbtUo8Pq)?tn<Iq=e(~_!9N38~s<s$cqEldFqml5_Xjej<!>N%>u4iF<
6)397?FMmpY;`T-L{I`u>8vALh3S(sGkd~%(hhTl9f2qxyY{8w!7`DgRdtEYh~={Pg6r@_G|Ef@;kN9W5EBaivaaJC7GrZ&{}5c8
E4~Itq^{NU2|!%HIkW`T&owAhq5jZq)U#IB$#erNaNB#J7+CMmP38p+olI4&cdF%-$o-jeOag{JnuK-)!VW}f#~jGO^u5$2*)O0N
X5Wf{h^{EvmooJ6qt^tC6~nj*2xVw@dXKXRgFmOZ6tG)@c@hJfuVW8wxo+n?h0xkG`HRiSCBlNZ_Oui7`Q|$@IOb$~0iIom=E@*I
ucz1ax;><co;i%;A8#(WMlIQkXu>aOya}Kd0d_##1$~m=+}{h$ALXPI1=GnhDb@qlw(q<{I=*xm_K^f(AJoVaHY&hbS9LGT4KGJX
n@P+ggVD&0Q10l#Zn42puXZY}i8PFXjlXFpJfW8@d`ao1%hGiM5nnfc$~GlCpEhY~YaAU*6`#1hv~jQNchk%Ge>b_Sb5#F-w*yUM
*y5KFqm04B-xp*^Hd+H9bztA5#TJWvN3ZI6#FwQmDG?x8^FftoF#YMrP))j9L+*XDtB%z1!l))2nH&|ItoQD{L_gLJ`dosf#LgT=
Ax&VU4DY5PhlnF#_13^MYq0089ZsIM+TW;+5=o<i2uaPgiY7?0S4yVUU*32NvBPVCKS;?Lx@iVmCMX8egy8xvErmS$Yi-T5bH3(%
+Il@mhkaoPL7joZLqOLo^(nvFGXkAbqZDs#%%Xg%pt4XT(^BA9oimxZb4>|@PrR(USq~-~$ws)UK`xm!<o3shtB0Ivu|EKJ7{y6;
0Nj=v8yjXbIMu~QJB|JMN`1X)E(z4LIeai}JbF$?l-KBb_UhJQf$uzkhmLaz4Wp;!DM63ec9v-`|Ex2G=~=Z=HSuJY>4x(|L>IKE
t(zq?-3A?xhgRKjsBrOzUe{#qr(HW2f5XQH96!Zf8pav4AtZQA7x``*jwkm=g$a%jd-XAJA05B;GP{%x*mpk1+xi^cZj{~$H~1Qi
>L`4ZBNh&kU52C#LuQ+|xlV6AkUSsv*H<yL+)L6YO*}fNk8($qu)EZ+N9m_?bIIzqz%IgOmKn2H7SfgZSewuzJ<Qh`AL#~p*_G|n
e!SotPahnwZ7-fM8Wo3)t1j-D|C?1i>382MGwBHL#AwYLA};u`{G(WmUBNQ7NzNr1Nydf;#U3Wf-CBfo10F83QqoD>$0&zZ&5)$y
hz#x80bsU1vT#LF6b*VDnA<LBrNR0D#KmdOj9G<Dk^Hz^K%Rjg0=E%pnyomaX&8ywbWvIvb6PAi^@JFRt3^DTyG*7`fwI2}J}lr4
nGSu>KUz38)LY+9->-Ll=R4Rx01^W!RN33;(aoCVs!y}#T1jMqC9>+82F)Y8X{XJ-6yRfYLHOy$T^_S8DA|XZEn_ec)T&YW;tTbd
_o54!@jeOa&w7@v>JwZn;{4TZ=6bgV-~%7=PBYmYwDg~5?gRMtq6pW(sugFq%VCS++ooJhEA^k!`O@jih{=M&@FTB#FSj9?<K}mg
ZcNh>dJn(J0O&xk-A<ZK%56^m6>tA&{K~7z;w)qP12a1maqeOU*{||^agNU~nIC@Gwxm<Tk_1kTQdqyIUHNGU+FQoU5vI99&A+&>
y38k5*v$d(kjFbi)$VSv==ogQrPbnJj5l=~H*uIva|9jmOK(!PXpIHU!yW7QILWAd+!9}B?>xS>+jM@1dp3PfHw@?^uT_^dA0C{d
nBGd3kyU}<1K7G&Kg7jNA1cO^JbOI>jYKLx#Xs^FB0vQ_&6+;*X?K=*dn@T%u@$4V0+uF$hcXmdMiw`tsXCiv3Vwx_udK9YhF_#{
7pRXyYl=Jk833b3As0AB-Ys5F8@zrI${&HV4^EIYKBqp!i80KAG+*Y2L^U&<00_0g*Q?sibwQxdwma$u{p9uO%80j|aJ^35tg_j%
g5!ohW%QSN%}Mu%RdgW0SqSqJ>vHg9Z;ja8Zl6K}?|I&(6-GPeL!b+lUz>!X{+>QfNgomwJPyBNobrS`enGlr=W&P&HIjnNO;m-G
pr=U7q=biHX57N!2OWDn6|lCE7rO=vL(5$GIk-tv3Ou4i&rde44t9Rmz$X9D#>QT2?+kTNxT;3&lly(Uxe3(|I5!s=oCN9}xT;5{
&2v)0%!~s9y(3^PQGtFxHFYdSLG8wR<1z<>nQBa!4!yxA^JtE|vXEv^=Eg-D4sKx}1j1~xcip=-vLf{#Cf3U}S6Jmq1ZSmGSrzi(
fjTxI9jHQM_b4125bxb)_utX5Zm{5MZmwG8tP(utd}YPi296j-tWshw;!5xJW-OrLZfB#He_N!h-9D3jwTGiz<<qP`!&7kt4zFaB
xQ46WW>b&(#2WJ17UfLDG%WRS5D$M9!i|>Tr?$!e=JQjMbMRE){~*3va%%Y|ky_`+iZ;5_E@$rN5oevtAE9FvChh|H@t?j%(zOr_
2-=hjB#Akb$H<#Xk(;Q$L(4tWV8kY~j`PT{iaQv`oal51pOrkptt9K3__lutr+)A7%R<#ooKV2W1}0>boI^Q4#jdShwHSwEysN~b
BU=)(V3h$z{5PB65E=}US`g-}o{d%&UM&{T?+0zdN#9(KON|1IoMdJmn-8H~0yhQZ)jp1Erf727Awic9dbW%+UoC1omlmYSd>5kj
g8tI5)(w<*G2p{*h5R&dFWwTA7AZAn2gsC1W5^o)9V3JvsZVk}RIt7?*_s1f3+x~&W6<?}#rpq|Hdhnd)O26iZ5OTFtOB3N09F_G
aAHduPWFmR?f)TOVTscGl?15aMKC2*v4R9ccwb?f({~J9+enR_ZGG#fVorw5Ja<YwQWeHkS|0u|qlptLnxy`Ap1AFge{+8-_^)mb
88QMhjZANAOYYgZqMxvT=+L)nS-QM5X4A$W`vsL<MTep`Gye)W9GIW<fnnHNo8U*<C--q&^{`ZQCC`&}vl7={7g1AX9{wkxQuZ<N
xN#MDS2)UQVlZS`A_m~c!ST`frNv9%m>RGGGA_Snp2$r^{^K<14z$<YfoHN4h(eO+Gn0NG>?DT1P~KImEB{n5t4V46IDu`B)n`Pr
UXglo1*{LaUZ{#wpWjZjYw7zcShzhzT9*T^ht7L>OelZ_*sBC@ck8AAL|LiEwvCPt!T#0+%RRcDckMl*{>o9Dp*FjuHEyS4L)6!>
gVYQo)OQx{PwP~jOPMJ$f7YU+2A%)4lC2H5+~1NF=^-|bms)>ZzX{o=U0cDQxMz*~{%QG&V0^&PUAr;``))OP+T#}?jXHuAL5j`-
_Q3gwB<NE-_=~c^yHeTOWS06Nhfd&*;m3*w<Ct^)>Vx7+%sFrZs5oB0HnVYBZJ78>MGu^=vm$gj`<HBE3p%wTgp<LSO(mMyc%XB`
-F<2a6Bz`rj4u196>Uhb595n!$yWOtd|a5yC4S2GTrytg@oZ#|z(@b*yKUj%tGK8C{C;?z!&B6npbmMLT6eUA{_25TX?W*amELuh
-2dbZLz69NqnP%Dk-h~l^Rz62#m~|INM!y-o#n56+G|m{UB#THjAvvnQOF{FVx}}IJ`?r5Y{<buz`{+-wb!~E$BEyjPAsPfOty1p
)?eQNUDOuNZl{+tj1y*mKTN68FM9mD!IWOO(bbx!eV|9%!o&>OIh_6_jcyMF4k924>UI=W5Jrf9anG_>-RVY}THOq~ntZooa`Vx^
HZ<@yIBnLpLkZj0dYtYq6?#L*l1I4+-baDkz$(b~H(GVv0H-tYRouM^jJcPe%pWhG?T_vf@f{4LV>E8~;tz-2_mF)ti`UZrVU|m*
Zx!Fvj@_@GQBBv(H~9JzvN^1khyXgR<V`4$nKG>1^=c(M?=lVSWD!?nz>6x`d_DjRb$CfCVJcM4t@qrg#h2LKi2E692`7!K!`A-F
L%4u^MevU67*I|qc9;t5Pr;DOxf3)03GX)e4N%7<7|1*`8Uo)Fxjz|2a^JND`$fXKvq5E{e_p;-Xj|u8BQ)mY&JjWCaZ0{7j^zAc
J4I;a&}x9{{CwISyy9H7Io>PVSApTp?%>2e#*G{y`}wd5ruUgz(N`W}40wfD7A>sl=kd!^UZP%fpPorb>GluxVL{V!<<On_e|a#U
v)Al7a&2)*=&DQ$Aw!0S{ZIp#_bkyVp<)mBUP1N8ocP~M$Kp<ev=hhjeEtqNhgFon+K!wH!p8A(vFiSUsA-9)-}I5C?RZ{!Y)LbU
?-X-H<bMbW@NHqBxgpV=i^8A<l<Llm2X%X|MSp*O;tTT%i;UnlZv(+;+@wgl31hi~42$=C`Syfa@$;@8zkHRQg3Xv=YCFs*Xdc@6
>IgMu-@L)!Z7*n3_<`MRm$9oUsg(a>S(bPj_?A}gJmMxQqN{Q<eZ1tVtni(qRO*zlt_s6Kn>>urtf10$cgoDhSQs#+EyZ^$ms08a
5apzbb9^>#jLBn;sbrA~3BUU%U_Z=V-Yl^hSxZB3t8VRNH|YP_n<a}-Cp?FZY)GgopyCwHsy}&hF|`&JGjli({D4*oP_}-sswddy
CxyHHE4M0jGz6ie;&5>sM6(v5kJM!>`52G7(Y$4a?hzJSV8kWYdN^{=4-#<&(W#N@7)9=1VoLAxUC8oF&mcUto{e;?eZUCKK;UB^
TuVVj4mC|$G~tgsaWm!>bu%>JA=`j@W%Vg)%=Y8Hc+;N4q$an!L#ngv?eztEwI3s<GaN_xc9(?W#f!G8Z}vH>r752YH>>twRLaZm
45GBrAo4~zeX@yl*4y+I6caJJ_L`2m3m&;DWfR!xCt6#+#r=13)+0nAx8_XaDCCrvi1ABTuCo}h=~yAPY>?Q`QB*KBeZDX0)r73I
BG7<h#TNadYV?j8l~lz{K5RU!GF83QPD(|V6#VSNqlRy2T#+m4`B?FVd6lBCfTe-jBfZI%FfE6Xv=GBn2(gZ<i;0FX#ZbI?Ku*Vc
oX?k}#Abw5#>YD5MiGfsvSFl0{9-q^D(Q~*Yk{Bx(LUFpD3Y$o3<+#d>K>+MOG<m8ucj+I4~WewMG8e9qG=Ww5D@;^-eZVV^3Vz9
Tf+@9Q~ZVb{m{f%lDP79=41^r+N=xBP&D=-iQ^b)AK9i!Cw?0qWj5yinMyRA>q+CRRp}FiR&L+=p$NG`+MAzzN<;E4bbQ(8A>f!C
KNs5Qf-n3^#)0VCl<Z)lCJPRNj!K*-S)Jw`$M;g#Xef=umSeGSbYFMRIj!Dt{DYd9VNW{WjdQHFaW-RUNdWCKOC>xB-zeQOC6xf#
|Mc<>g785OCRQl@AeA*Sl_(RkI$Dd}ro+UD7NTHX5)1B_YZrTv79dF4CYEsBZg!IuM@Y@QWMgJ!Jsai4885)RJ07!||C6#D!Px9p
0nFvqkTu@rq%vlArSlai`)8bTP(|DE=!>L^WaG7rn&B~nuvm}0AR*?<CS7gbm%ws)GOh#+SaiGj{oOFMiG|i4#dA;TIXs1%04Kk(
65Szc(_9&M<f2y#fpOZoiaNCW#5261f(2cwN;MhL@qyqsp7h-I=@w`+{H-@!GTsd((_B5Yk7vM*?q<0S?72~FC|#EU3;aLN(gQH7
{rguH^OM+WDRR(q*OXyLu!Vi8=Ma)$i$IV7=Ef31fBR8Z87Ju%Ql(=E<65IVT#PG-gBZ9>IqsseCv+{WWG7?_s+U*EgVii|E$bN4
ktxVE`V_wisn)nW_MQn;q~XY1qrxC7WXjRSqUM)C!FT6omJjQB^($_qNYLSN+51MHlx~LKz_CTAkKKfTzGc1=)~rk2<)xh1pYRp{
IUkga{tZ;ucYoOxRl9Lwg*b)NC+I&GZ^}G45Zpz#`l)_)b2sFbLc|0F%V730+T8qGPYS2N)6?w|8ry7{gDhkEp^i@W3&;N4BO?ae
A6jdNC@QhlygSSsZ(LLv-d6q>ehtQV<}jnfTwO=e%p0_-iaBzB&$zSUZKt~}da6|e%kJ?*%9CbH3etN3w)8;;oR9e4XKpBF9m*#y
6H0<2&Sy>te8Jiz2>6Kseoo#Q^>UNdZ%;41v5@omtC$<K0^xe)vmHKBAXV}%Ys#W?09K6|I@ZlUWRT6H?^<c-&J3C&c1Y#18Uj7k
>e_Re_rt5}GFmP~yP)Zir6{xc%eRWPnwz@TXYz;O<14$m3)8jjDlGDaJQ96Vl0Qa#M2br6c$E_w9-{I4yze8E;W8nagJELm(oKk!
=QY?<!QSDb069wUv^}yWss;;P31Ejq9oI%m6HHlE4(}qjd*NLd2~AN-aLS&)$iAXbJW9y(0b*~Cr1{!4&0uQYuk(6k<3-9<x3LZD
wlr%d{fx7k{)$Zr77p!xFtF3<<~sJFdi7K9Z9D|WIIbiGwi)q;K-4|utXuc!Nl%zHtgsBEDq`c3X%QNkPe9Uc55k0P<dmv6Xj;0G
v9`$v)_OFqQmbWT218@<@Y~rD{p_|JoH2?X3(pt_fnchgP7$m+ZX}Y=0a9~!2xd4_4?{o^$0${ROp#OcW-;)5Wkleu-UO+ip~ZZf
49UsKAf>FTHPg_IZB|SA$rWGjZW~hym*q-uLY2Mf3OSi!o9d}hW)<Z8Ws7VP5yD+?LxCe1-9!gkhmv4Rp45YsvG>&!H)i`Gb*e2z
^~bCt-J6Vf2<^P7n~DV1$%NJbcL4xA4)|pCper=m7Yn|S06j;ffQ5?AIsN7aFPft>z-y0VHK6_3Kn`<%4=XFS#@(=5*x1Jtr}%1%
?ytDiyqJ0zOT1e&xcujk{+#l@SM@LES(f}Kc!?=kiaCE^4gwdaqvgTVqmNsts+IDQwm}J*n({WSUz^zpCBqm!snu8=YH(=CGTWD3
zL&qOm)}7%VY_Sd#iW&KDzF@e^uDjd1xEKS;!9X$p+8nZ$NF}IR`8sFFo+Gf1{kYx*&wnFZie!G!O!wpS-Rb@IyHXG2|zT)d)J&~
r*MnZe(;yKr+G?lrBt@2BLIbd6WrP7nu%v^lEr{3w?V|%b{^e0tfZa&Vp8_e@hZvd7FD`S9-ad8AjYb)=HNg-{%!KjHO8D%;)Z={
HtcxlD0hkZwmesL>y|)gw&+jdX8T&X*TQw6Yf}!f*o{Mltc0|E8dZ!7(|qQ%_ojpyV9v&3&AsGa89jtd%<oY41XEngFH)L^dBUL4
7R9I0TG_o*9mnLsp6)?qYOu?LivT4u=ks~?B6Q4CoaRVpB{c<>hs$&U$6xZtGQ>yD^Pf`_Ra=_}6!HmxcYvAF;)uxjP+EKer?S!P
XFB^wOVEzle6s}w_~^9C7Jh<$zZOzNbF2d$XEGDD<%@;b5m>cNp(siXek9Ewnn9o$jm+)IY|>aR$kk<0sl-mcfn4XPKcJ1ot;^*9
SdqH+q|Fn`tyQQdcQV_%Rko|&1hcMn?ESVQt>NW86RV8&sFrkf^LD!XrA-9C?TUhhwIGWFF>fJiD2Py7So&M~X>|yoD+Nc0&C2^N
pj%W#IZPa+h(_Hu*Ku5AkmF&|jJeRK8tit;rscH)!X7G3kbi;q6Vyv<*!0WZO$4xKY#=;ed7Gq+RZ`b+Y6q)(DUQ^pKgyTSYQJt=
%iH#{bK4K;0B$m&XkEHTQoWbY_2j(qgtWN~*BoAA+Le2MTgdBRQ-)~LA@WkX`G-iyZs0YE==iA*+vXMbHb>o~d6)$_JTg@>N8rwh
oEgZJ_#&$j><lhtLP9~dZ^(5@^`;&DX|ts9F$f&C!eD|4d0pQ3{Uvtj?=)}o7Oq<`v#=7gZAVglz>I94CXqsz&jcQ}LdR=oY7_C=
xN(JE>!V!jC>%&l)aez}S(}M@C)B!2P6;zEx0^)lyi?rE3Ydymt~%5_j)1p-FZX^x`Dj0O#n*_PUs#Un;IV<J=v4JwlfCRqQ#i8#
$1;hbYGSsdPIDErBZH`H+CX3Pk%lV-%`o5>Q>ebb!@k0~0-F%y*{}8|Y>u+%Hwy?QP=wlS`KIDKy}d%4>lO*uEyhq5s<S7-2VCmo
DrokhukRx)2pk-C@=72Ecq5=zj-Hq74)&=)oV$aTk_yZ8!Pfd(N1a3$W}=WLi=CWl_``2Myp0s$4u;KXNY~3?*?<3qt$PASTE*n=
DIJ7oZK(n7@<lZA%qJ!>C1gK>f~<(;SH~tfMjWP_BYlY2xOMfPdg0{mobJE+i|Mqr3EQYf31<%FXTRT72qzO{08rZnI`J{xgi5)n
ReQ_2waKU9{+%H|LOC7#gh~p}FP$%KZEbjZU&Y>zAZcFPfFrj>nW1V+gPWQ<R<3POhA*73<^Ix`yQ35#t5-9zyvfZI2ARh&of+zi
^n?0i2i%s0u4=>h;<5~jQ|5ZJkea$V7|>zt=e*X#FPqwPoLn*@0t5ljBK2qyLT_xG2_+6OVg7W^;(t<xMA;#W*h+SdyKOOD?@H;F
bN-n{UpHN(dGmnwKF`jPs!)O(kiJ-(4Q>M#O+E~8+>O5Zh%RLUr0AciD3?^}WDT4E#3WC6$Pu`F9mm#!33Mbj@Xv|+YH_Uk$nh5-
_uY5}CwQHly%ay9FDwtnMxZ)1qF(-9-61iIZI8ZW%xAs*Uy!Qd1}a2J>gxz7fsqXcx_OMH>fb%<^{ibJjJb+tLBQx>_)iT~9w=qY
1u%d3Jv?8e!R^*S9TsP3E{OzGKI7=vdEjgv_CBX`JubQvg10(gV+K{{UYWx|v|@Ffk7~B$wzPqyiY%5HIR0zE{OPeSZ6xcdiU#oc
AO(u?@4FJut^Q9vtOkhkBY>~BrE=$3jNw*R%RuFy7ml1SsYvMiVMCX-Rl~+t4o9C~V+cU*I*D_O6uqM2<o)U?lE!>+vL;&a9{Op$
oup*bUv0fVUzB%A4PTdx4RwV2nz72M2AaA9)jpt<+uRxYB;JiB?eDX}$5uVQL%+hJb5EegP7@Ryh)9{nQQxa?EH;bDEG(RNlf*hY
upg(J=THmbd5a0ML&63tBh`fTnzi5~keaA4AZj6`m|7JDT$~-duF4*WnBCF%dIFVBgB@9~1gJk1f;6rveR<;F=Be8SCKCRq>0fpt
=!9iJH#D8)?~C=u!K#2{Og@V!+%>k2R+MNe*!``skgD`$=;m)4^=ZB9^{6GxFvf+ucT5xVy)YwxvAd}H1c~V~DZ`XPgK&fNr6uNV
L2XUB7g@fMonP&K(B2s|1rN+1dA}_cIl{qZ%`^Z1g`wf368*(?ofdF-cb2h?AY0sID41PCI-GoZrTwHwb6bSslrw2vdZJ}}K;Yx(
S<-bO=(v5s%^^;Rud0henN%#rL%f0z2dmrFrV{v>!rkv+1)yU%Dw@{^myu5H4U^BeVfK;MYYP~U&5Y67o&5Uz#2b|omV{o*fa{8&
qfdN;*fN~hzE08c?+O+QN_VkB4OZo_D{{T{vOO3)A_TTZ_rcG(2*X?24(?<nA9d)=SGJc!vaJ5R=H4Ulq%}|WgMidCfJ0!mi%6LZ
_n1tOJPR_}H0<RpgFKpO=Jc_(8mT|y%i;GlQi;wu#HESUb`lOSn6aHp#=c+|i#&-0`1gV|>%kP12FUO@#3}49?=^=&uoL%PG7)2K
_ij|IDX^K<rdFQ#lPdp;4nFFlezGfNWkFjtANCaSYD<gWc>I_9*(RSRsDLcM&z!+xuk?A0yg{8nQUQmi)aj0Bcte|Ol?w}6B<M{l
K(l{-<6tp4u3D|@TD=K*0{)ctGR3s!OuFVF736@a{)9|p#W^Vor;WI$SZVF<HJGp1bYl`ubge-3mp-PwE}SCl<&dgU;mJ2<%FIwh
L{OR^L=z(W*GSX)wyDeHf+hv{>J<)Qn6LHQcs;fElwd>5ot^<&hCxb*2nq$I+d;^B9F@EaPKUglvN-tq$*$Z_mi4JiF}Of+*$~#D
i0@j5uo)bO5P5f<%_7R32{2|);3l}Y!0D{DVzOj|(dl=21;&0N4fuAKAU`5f>EDY7?>=DW(-gC2G^bvVJ8h~~p3=4$RMg^s`X{~-
rgd?Sz0F6R0UanuR7jx(S)E&X9(nHD{7)x!ZC=H2tm8GX5XlA2U^bi&+Z^aCY!*k}L*D<>8Z%~ImW)`9cvn{v2J~PpTy8d&a0w29
D$5~*MsvViHAwLm>-!|49}>1%LW4jtekK}jP_c`tZWX85)ZVGEOxcht^vZ|oUt$1%>&@^%=0%q8pw&@4CaQ3?l(aN_D31~T>avr+
E?-v;2>;Z(Qe&(C_x6?R$~A(Z4X5x6{0+2*yM$psS9~h^Bo|LifnwX7{LTL&D`zw>J}R9|pCv0<?5)G8XkJix5#g@xd|lSrxD>)?
ZtNU=AMTD3w#n(ppyHT8*36>nV0Q#A)iIP}+iixM=i+4(EC_w3Q*W6T{wzd?ZmgoYY2$|@#<rY#EF>4<Eb|(#V5-3A%7z;GU-wI5
Q=oqE<sZa_jr}E*nMFp%GG<0-x;e_PTnl^|{-JK;N6Gc)OLT!@L`ldC^3Aa*oY{2%7`<@y0XU@soERK<Z9Wn3EIFF~7*cs-{(G3g
wN@2rMxCe}RWJ6g{ZJ@1D#`haaC0s+)`yt~Po@FcLP^6qdtMOUDu2xjzX5~St8(5q=4tU`kQS{xK-vSPMsLT}rakJe2Ar_>i7mK?
7FY&F-y*Z+El%r+BJSjBW^J3B*LC)tw6RCYZ{17M-7!TwsczVi!W=O$ebb{hQl{k7T-%}7*2|+;P>K=N;d&jMg(LJ~O3ABdX&nN7
NR)=Knj}J|$7u}o$>m@N3{$qU{hle5zpJ$pEL*PFn%KZF%6yPG!`lNm2@Df{=MrG(dgJ=Trh&qq-2~d0B{Z3tiWAK1VTGGX^wOK4
$dk!uy(!J`)-I1k=Jguosf+UJQpHT4lW<pqr>GmPj<FS|n0>haLXZQ5J^cc;)XFT;CffU|iv>Jo+O<%6D24i)9VXhWBt~#C>;l(Z
A<><90Der4cfw{}Cy=ANEEgyWXG7;k;HW(r#2LL*Px0J|@^P#5hkh#kZ@>=wGS)WezX}MEyY^+dpofvi(EWbm_H?>4_iS|h<AX?c
uawHC0~tkXG2d#IlFs!$W?xXQk}RA3YKqVohTUp*9^Mjz-}uo)3tbUYu8|Lih}^`DWS_>CzT8g(N{iu{F$5yv()$2%`G)YOEK`>_
iLicG>wK5KDmUSs?kki5^F$7$Rd?aI1H`5Bylk~f1>(02bfXe>ayy$8YdOI&WN=8Ndnt=upouN>D9zh}U9-8K^zI^l8Q=8W`+Zu`
Q}hbLZpHyk62T{^^B4$d4%!)SGcG#11dB!(DC8TOLXtcatkKB-sLo6A039_BS-@jke={T>s=Xsx)|Q0Y=fcB8S_r|8OS`FmP|X_F
LD-|%elvlcpWERO#ozmmvju|esBs)kbn+12wz^<e%C2>dMX1iP{F{1HIWavyoME&|wA7eyiJh-e#??#MSjX6tG>z=>L695#OlOXo
B=cA<k`GTx{?(l<-}C;V0#sE_=Q4`N!!Y!reu5$9vMoK#y@3dh=&B|7gO(Z;%(k9MWmXhz+LgAo$l_9q+R?ML)f}5e35pqQ@8dJ`
Nt?$|aEbyg1;=AkVm)ExFHm1t5*<787(t^^7x?6D&pIRy&HMKKq-cq580K#j+H9QMNpX;UOvBd^;kxEpU%uX19S1)B{hDI8da&Rw
2>e}y-@;Mh3uM4JFeqI%=TT~#e_hy_gZrMcm+7UBce$+4axbC5i?)GFT0pSYqQ}Ju#F(MH|MjM;S6IuQt?nqcB2eHQ=HKWqHPSzR
uJsbw&UO)gc-GqXetaQ0<=d~PJ^M6TCmJt2TR`!Def?Cdbk`mQl!CF8CNLY4*lhw*yiHnsq8diz8ciQHtUl1)ePczV8`LfA>7&Jf
<q9rAPQQg?H72K20)B1z<9T`_qZtsCcf`>XFP9Zh^g+x0-fntQVvk2MbEehR!+3TRcqxAGNK&1rKkBa^WDJ7s56O6QUP4OS4fjr#
%wt(_7<z@m>geXVa0L@#BHlv^&*93B1)^^j^ApYbY2-p{gWhnF5|UW6PfXJqvCeWq?1hJCPNQWpCU%&Vbk5pM@TLMw3+m@?Zl!Lo
gGo9}pKWvnU(|B<^y;UBGLZS4p+olZ;-#O9)BhpumjN;-B9#6vr3S{8Ga2T(^Fe#BJUy^XhLs_fD?zf*O2^t5vmY!;t2kQCn$qQ9
xU&68idcL)o3tgnN^`J@7F+h7?eN|h9<d+kI;^L*-&&Z8q>}=SjAg)BWi8Rr!0{1$1A-UmqUA|uGZ=aXAp${G^|z7Ov9rWY<d-6t
6kwaEyFcP*zH2({%O7G$A*msCJTEu>1jW0K7E{`0t=boX&sm?8!oJsVymhzpu={4E2IE*L)Kxh_i_LVsnLP=D+ip_breF1YSnYAN
L8U#p)Mm=e>ac|&=<jqG3UWj0<-MWgtNcPx0u&|DYZ;$at?Pj2L7y|N%r0*VMi~*gZ7|+DxxV(`8LdqzIbBBL2NSajbjuhoeyx-`
zk8=vP%44CO`+jE<yC;HvLpE-b;u3{h{)rJJmjgV@e&wX+GMH6?sd9$Gq}4uJoAU#OKp3Ecrp>)kHX_=7AbvtMWJ^=Yx>32nx*@I
tkh2!SdA_2+0c9!$ko#&QTz%E6P(YO+ya|<nwh@H4b=+_P34gM<lvrp&9%rYwwsl+y966Pxro|tMC>GCbSn6-^=C8HXqAP-{-<t!
vR&|<<%S}hA29NF4}Xi=)iknyBW<mOR>Q6%0u|p7LiCOa+^1H`J=pV##N$$ds@kC7FpMeX;r^Ce+?S<e_Bto_H0woTlnVf)rxj4^
v1M(dnnnHEz7gBbfvy6T4o}<R@Q~;u>Aee;exdrfpf1`E{~;raapXJs*N`yn(WZPwAYw`vlH><wMj=H5JBr5GbDZIZ?8drqp3tI#
-R4@rr$%`P7{+FHGsDbs^YPE`IK*%cH(&%-T5?eUZ!n8x|8422m{fe6B&T$iYt{FxG?Fl%Ftx`1+J@lg+dX{G3!ir4kH~gL4@@#_
m@1t#U9N>$M`+7a5wJjREXXIiGgbz{Gz!6G80ioiOMgS{vJue9I2m+p>PX)5jHo%1w6{@GZG%71(k*59<N$DN#F-m{6J)d}^wmI)
by|Xcl<ZJ1EOe^)URLQJx+_i>H5jg}BAF<!QS9U^DVgACG7HQ*t!CXeBq;jwVZj#v(NixpS)2!@1uH($W!P>twWiRn10cr#o)yAj
)$;vx1}6D>{QSojt3vp`dQpU&fbl*Z8AUrbbev#wx9I){fhuNV)%H0VSBL(tyquthH2?Ox!PM@z5XRq|r~Q{DSFf57o_6_=Hha4R
s%(NFb}l>yqfjvJqczX~U{Whp<F~R<OOO_+4p51Fzq1wQ$irAnp|q6Kp0U6Iu5!eUYr(45e|ZzCGz^WQ^~JH*IJ*g6>qPQCeg@o5
85Cu~1nhaul|X)+hw8Ln$)$A@aTf1Z&|BYVO-wA~RjlCTg~1$+l7_42zR(?`B?-|A63sgw#;FFyI3fJG%kwVMTFZ7?Dpp+4mw{o~
Rtj4#p%SKHR~{=nSF`Yw=dVjHoeJyR1=M*(*p?Bgjoer)o%Z4(p=Ku+)P!`c|8O@veut8DxM*p`3N*MDVorW=l+vRg?e7Uc8spMA
$_j>IJ{lo%FZ4B5sSmVz`><%yBEck&Hh5j>^`wHbri1c;Tw}ouI(&SM`FUysQ$iy0be;7homd%q(6r`vP+2A&w4WJ^T<e^i(*9jp
1_LJMMea2LsC}D7&QD$o>)mj(pdjL0t3(2w5p0xVhJ(UH6R`Y{?&I7~W-8O<ZKG8Q5GcXVO6j5pKl%5g=0|w!_Xzpnc^1tYfza57
#@;XvL%_edR$5kVPT(;zO9Ko2um1IQah4rD$KSE2<QGsDnx6?|SuPhi%%k!ZEz%l8%=e4lb7VHT6126w&<e{a!g@V_(Uy=(K_HRZ
Sm55qNGuH~!>i2LQwdnV9VO|hS;vI$chq1SX!kACZnM<_PJ{-2$Fxf(5S2`yK6|6Gehc2O@yV_}2AkS@kTIs9v6AdR=mYOa3)F)P
&PEW~rUHx<wpLt6oav=rFGeYXS0a&DI%I(d>oR4FR#U6#K|@+AW-$oB4C!R+;2f*6Pr<@7Mvid6Tq(@fF=3e-rGy)?ap3ng=-PA#
5g}izUyc@E2ShCX*cAR@$<DWr)$4M?aS4D#F+4o|e}9;6f~U%I6Dr%6#9?x5z5Y4(7lc7_U=><kYi=;DQ=p;(GJFEqULa5y!<O{(
-#20aBy2K`XCG57s9_ACZ_%hRDg50s?3S(~{}j@!<Uw+@6IOmKAJqszWvEjw!bi9RAdjS(HQZn!)IODkU!W2kL5g(4tr~=2&wD5i
IpMTSvo-b<FboQoPsaFtbQp#ZmkDP8?<1X()mj<dx549@&|)2)1YCX!ve<zSCc}S=<i2rd<3~kc8+NH1YH^8wz&nY~In(Ogv`-Rz
iu?IV8Uf;oGVV51O`X2!mES2vWofbw51u|Woq%yf$gCU5cab$vtwB*c#=7oFsK;$tHwy%Ct6v77*8bod@aOTz`{=dDE1$dipil$4
n7}=etblz1VF~16;eTB`h7J$uZiN;5T*$5{Xpu2M5uI2hwPO2Lsk{-&lNx28<}v8^hoN^`DQQX9992z2y($uGZK&z&)7UHe0=Z7q
WsCpHlftDilFWmx_eMjofC_!2CBN+B-d>gRq=}s2igc9pP$dKtEJ6*WHlI`UzKy>GKovJhj<rXb(K-(1l^mIDN{=o5ik+xEfs8S#
sc&#CJUz(y-FA)DJ)t|@ypED^59fv>Uj<1|g-EyS6PH?1$FIxAX9QWJDt2l~`>fwMJ^YI+(;^mQ5YzO@c=0KzUpJGD4_nLo#EQp5
mv%imtkCD-2O>Fr+Ftad1s0NBul4_g6y5XwjyV~ZKTScGN-Aq-0E%;S$2n?ns@)&N5MuRKVKsu^#`}-k*r1#4HcdN|-L!F{69xh|
Rk;(;9fDlJaG>zY5!D<GiMzTRpSS#62luiIvd52uttP62t~*M-a5ezwWe+4`7ph(hN`>KvEqMo_ipvRtcJVDXyiAmenq8XPi^F0$
#k9>#Npg!?L9j+l1K*!&LClh;qsIp4F?BK(lkVxS1rm6s0=2}x6Q-a=nt+O112(h7b{Wpcdzj6LI6xNb#QgOoh1+(2;lmS4hDxvR
(q@$Xd7wz}7Q1@Kc>n`{(6n%*Uyg2;y(Y9m%j?w629eqmpg)#1Bt?gbdG2F17ESi)xpU&%*6N59l<S>r*ZJhx%NWiV9gtA?`QreQ
O;EAwB*)p_j^KR(PI!uYq|Kz8`t0gAuP}q_!*se=-G-CXuc%Dvtlf5M==Ltr=P;nT`r5+p5#j}VsF-&N^>q)1Xy^W*090;Nm5vZq
S7a^f(lPYfbdogKKC4QZ-2-LRYOOhtW#(n(F}_<YOh!@fFr8wXs$0){Z}oX$oSSITMxYF@e;@m|IzOw#vN5I?{6Kn*MytYj>{HN-
Y(zXCq4unh@TvlozR`Dmbj8lK0<Tl(#Rdi-M-r)$81P>UFcdOah*5U8+O+Gy{JLWp(>84O52GXdqKi5?L4G6^j5E<5(vNRVb4KAs
k{ln1cIU)rnbKYhw2w;lSe(8OKu|hkeXc0@s!gvp=4`TUtE)iT%ZGq0Lt}_S3Kty8spFa6k)x`lk`db=y+PEEk?}3yA{m&y)GC(F
qN)Ag*xy%9fBDmzKuLPkPEXc{>ZCTejfTNaF^zxkC~XCKU{%7y__@yFfK239|Dr@Fl8AJD9NLu<KAN)FB3*)~PU^aQm(*2f=c6lT
l$*tyL3CrGZ5>BNGh;l^a%0{?m!esb5;~icw#ctiXb)Z5_J-VHENA+V(CS);DSw@WDuX=ED4r8DY$5ETV?E{A{A$d6ra+QJ@U_FZ
;C+s$oa|K5+sy<@NtIuB!I_S1c3<cy8Kb3ax!I6mG?OLsZ3T3u_bhbN%q$!P*h|AMt@-fxBGLJ7OuWEAE5-8EBvK07@SBU1)I-8Y
-JUq{XYeB{hunb0IrV)#9ZzT|*`&POc8_8>1I<T!xVl=bVJbi~*+->|W0z#OH;Htn+7a@O{d&JYszQrWQJqKm1qCVh%f#W)9g`V-
aJnN_Ii~dY4#8&y;l!;<G9Vtj41@C9sU$40)?zWvz9&XqDTO9D?#639&E;>vW(>-g3^E^kC;*yh`JaJ!;+1N{=uZ(dBB>&`j$Tjp
BvQRwwN15P=@#y`;X4wRM<fqUHTN4cZ}#38co^2dHu@=<=Ivlvr%S0h>L^cmk<SkoBAhjl_Ds`EY4If3y=&$3Tc0S@6uHR^(L>&x
kfNCWFeJAQb;23*r4?7GOuC-;xi*R1ErWbNLF6DzRH?^>evMkZWC2PUvTgW`aN8~$J0Kk@B}aA1VW7$&B^j*Y8`%O=Cwv*$hn8g0
*cGljE)M1-srPF)9HmG1{Go||@XMjZYRKoSEpA##R?Ivi*YU?m?KuW9eKdaJJX!v(3W*FJrg5F3!Q8GUyPB>`X*NM%&FNvzJ+qmD
0ho=&1zl!+)TZ`L2mXXgg-kbdmSB1=m2z=2!a&rzBV7$bgN_Pk_wtfORAnuNQ+tvn1g*&=BiF_8GAa#UA;8|#Aan}70z}<TqzU9!
DErq$PV}2EY}>n)c8iwOF_Xptw?h_=j!%4Et`~3*%cMLBrx-AoPgIYl1pXGisT<yC;9$pR=I{1|=_Um5pGuS=gu+9_#5y5@BiSE~
tSw#mR(?4<szZo^W&L_Srj?)CKr+$iHrz5LGzIDd<|@b?lm<d%&q*j$8dm(a9b@?ZoEiNiW^4=cvXHH^vvP%T&F-l&y}Sh89LslU
l}o&UIb6qpgAzUE2hH8)M+EegIO!>fn%UEy#ui<jli$JNpfh!$0rCfxm!LU)iKTYYw>%Mio((7K_UGmQjxewrdu_uuww@@~a{{O1
0&XS=qtJNnIHYxY45E@xQ5y@llhfLtBuuD-jc3+kSF=XC&$U=Vuqb&$f^imyA)0o$NRs?8%_#}6y2pe;L!YPM+3UN#<IVdfk$sKS
r9gx2#^{R3=6!)wSQCy}g>NWPzguwq&`qBQu9q>uM8T%>mvub|>+81O^0nhHXgARfwllWv$mC?A_>42;(OXR^`SzuQOB!b%I^z*z
R?+EL(w?oY_HC^8dp;f@u=@lO5f@B5Y_UH?*jo2&?e`!dMLd~x8mfZIrNmnF`XQ|^R*5j@eW&In_=0rIS4qP9Dr+;*a1Anp94&6A
^D)CdTZjO#gab;QN=}a1AWxqq#n%eHhcMwBSp+^=APP~WFaDUar@iu<2s$F-ayByaxd;c2uZmH^^lNW8_?giI**_608S?t7)_6oJ
S-`U*qOcFe(QoEM?cM8^{+K<f5yNZKQj2-Jil$z%+>gLzT(d#+n8de)^2TkHl&J%HibfPw;`Fr=T6=my%hv)*rsiHmexOZeRHjJ?
A7;kZ0ARPu;meDosdhPLJlb%6;J9;FW)+D=M9otiw|oZzr_Mma{DQss_xS?UQrZX)+5d^^6a_*Ww`~2|hcCk&HE0qx`sC&$;9K86
;JhR&U1`pk>8sDbJBKa8ns2E<57F?CgGjlS;V%AnlBs-#={^+mdMFipsG6S!TMW}}KYB)S*O}>61^hVz20Lpe9lnIix%^p&?t$9m
b_xfTWh%xeA831?$haMov~fD>mB9Q`Cu`v%w%ig(DWcEfn>Kd~{Sl`-ln1&7%qN{Zep`HOkSw6by}HD7${;qOg5HgSLFzT6-(*o2
D*r9&G9$5Vll##qXjgX!rG5{oNy9LE2``<|*1SG;ZnhR(9LVcYCHCW&m>enY!VcsZ%~~EpDp(dc=<1wqL4-c$(7lB!W&M03gK!7T
c^-`)b^lg{0cXaa__~E5XONC-dzH(!8oVYVoiD>ayyFV6cQAIga{RfkJ@sZsK(1DQjNc$o3A<6I-)cmI@@#=Bsddc0)xEmHgN4Gr
vw_wvsVr>ivpMCQp{sB2{r+OYM0WEvA98aQN&X$Yb5e`#IQdLo+=;V44e9CM>mrhoN5A`VjyVYuejtZ-`EH0ts)Q8!zGD5V@dSov
cT$gcuDtHomC^UnGAh9+1zzwA4+9X84q0bwL(z&2NR)oOHDlcBYzgbJdre5#_x?EucAKi32_OhT?nLtjX%AD&dO(qlFK%(GZGL{-
XJS0EBq<zAeG+56?gwAQVr#NTmZ7V#^Xa*pTfKjfb%2FuDT%2KeP3nqZBkkd)$M#*m@!o5cr2iq<*GTP5+NGJUShyEbQGC%=9HK4
a%eOt^tpZNV|G~%&%x(da6)(AVQe~nS>VtcX-It0-oprJHE{83D4dOpH6HMaE&$gF-VGky*{pn!X4X-&YcEGgAdyRx1PRFlkcpZh
m82-sMV=X)dp_=r&#B^oUh}`-;%>UwYr*p*6W)b=%l9H`!sR~G9E$>UmK45|7{Zg`s-xw|qRL8*fRa&B&XFOKFIX>R%fi-}+|)6-
Xym0Sq`8c0-~cPh8%hsFIeBuV0KwkdcR+e@X|8W$mM<`5#_nsI!gk4-yKCU|CDcH-b8CY{;%@O~l=ITU4Zv%LZ}sC{#~p=;)aq><
ymk-T%mc{lgqRyXl|k4CnaS?U_*J#KWZgx%@M{rX%D4z74!BHU?HccI$mGja!r*%%nd*9%>;+C2)sVvn!DsjUV9&qsby-tIN23Nz
5|`6C!HEmM0;<r>3{((M=aeiHm5_zn&e=he^Pbb<FW}EVzQjb8A$Hqcf*CwyrB#hu5Ls&2XczcW*<$u@-rR98#kkPrZs130k}6XH
@SFdg_4B*y?2gtewQQCaCaxV5KNS2#!fjDQm8O1KKM9ANQ0f{VS*G2G%S(23VgUZZMuL)Fmb8bR%gZ8`G09)l%T1pHyHyTib^6g4
PLXBG8FaQbhDM2Jp`2R`tN-h}_W0qq4P76IlhLF^X@6_@^<8dj=$Kh_^eW6pOw#D!5Z8i`KU(4bf#8S<SAWZo78U2qs3XhIHu5|c
>6?OCoWLO4z*^c-?O0l=SfA<;LKqRGO>vA$H_&OCkTh#x{xj8_-_u`%Gc(3fxGjo`|B0gfy=3yJrNSEx54;6&Qx`Cwj2TaTQEcx4
vS&}P8@b6DN4P{2P9U|LmgRzOSiQclI)~Pr<|NFB6b{jf_=}}mL?I<ZwXFu=C{o9ua4qHF1?As{A+sdB;T$eZ(D`_9Jaj7DPV)S~
)AyY5N|g&h8(GpaGvPNf<drCcz$S27UqJ2MHipVn<OrUHu*mNG9R{gy{prt(z>hHAL4g{2-mp7d#j9f*yWv)#qF_~lri@Bg<JYcw
ImMX6+<l(;j4b9`OeO<*$iAG>5^l2z?k+!WP4tXhreN}sQ_m}k0i<8+&fLD$E@#zKSJ%3LXsH*hq6Z=A1kNt8oziUnm0@40Grd|(
hdXyKab5~d9RbRuD;)BL+6!iD!*0)A#K@Wt9q_`dea7A!!TBvMNY5wk;`j!by#jQmH#lB?DPx>_q7(lO`yv&LGS;RI6cSz`jldEl
JTG$)&o<#oyrucG;i*{uyso~4yDhx0ELRZXP#jBquC%y0cj0JY%as>b1GfC?UAL7b&uP`$H|q9*Lp;Qja|}pbNkq!gtjS6w3-C6d
Sz*n?l){J14+gCBZ(sbPXUnJHLil9o;^V@#r|wHnnJD`k4;3hmy~Rp;7BBpz;_!Ulafj+=>0w9UKzM6IrUdJ+OLTch$K2WyCqJnJ
q>CspQR&MLpM`mp#%EM|597oGjxrKFyxo0AVS^?$+nRu`coqgXUD4t|3b7Pfp?9$t?iv+MvXA$&8OA*M(C66I%d47$-X}ChPDun0
o^)fpRf&=mZ9W!w&(`_ZT0HfboEO1sX`Ew~W4D(<WxLalJI36@9d^1v1EGRcr5W-E-fR`0&?mIA_pszgIG>c$YN2twmSw>L?Bw#)
-$tgE>ZnplYruSLkSL4p+U@`M=~X=}_aFA$dg58Er!uucS!0%xf%T0t8J=8{cJ!&<Z5!OS3U(Ogff@;9h_V8y75p;E)<KJ28Q$?Z
LCujkygtU^s~T~byC$dnw5TGAQIszV-Axs(yW#3Z{NqRr`qQGx1D;Jj9E{BPAUT=Jq#HIo`_B7Qo*&zJTQ8!#)ti&J%OwSQjC&~H
7HhYdTN)*<^<Lv~QVSfgy)UAjN{WwDu<QvMM}cIUa>`_npx2oKIvXC&$3Wx730Z_F0yTNjsI5XatWI^e592+dxjMp>+|E<*2}P+N
Lk|PBR>SwV9P&F-GvrUSR3Pq9ziw`E>MgS8%0oFEO0#+meBbDHFjIxHn6*J8SnV8N2~eO8_F9>(Yqu3vNDxl8FG8Rih|IB8!0Nk2
(nP>9R2#1!sVdA`J!LNu@@-$jNX)_hLr;ENNn1CE!RQQ5Wvau(j1PZpd^08?k^p|>4dgqhv&*0bL})GttnfonkS=9FCU_zf&~UxS
$K?f;C83roUNE<=A__g=likFMRdI6ZP!#=_;CMWvSi!ggJ?=-F7Q>UQcn{JIlG3YPb63$!vGCKV@ll}<g1(qfZ$UFt8$#MfrI<?L
n&n@dmpoN7N$m+$T2qZAKc`L-$T+}S0o_uUsk6woyBBRm#An*26&ErvW$j|FvnJx*^N*qWOE30>vO8Ke(IF*9&jiFE^&j&ATS{y?
=rrJ9F^)-A<PpGNbtxwO;|ijK;kyo3q}Z?#u<Oo;YbuoGr%hiA_s%O7>}ZGonD!Q6F*>O~5fes9#muQZu2Z&-bl$htC~s+{4|A{o
vyW#>)xM|!V@CyY2=gx+WN!f#^XOzgt(joe9?HJ}onbK?LfdvorOrWd$nX+^CDq&NPB5jHXL2+`a8DHT_r$rt`d5p|TzHr`zpt}$
rwwaviBCu6a9-1Gi|5~&Fk2!|+adp4OH9ec6TW39*tRGo0z{@VeKHZnF5|qp5$P5&jwXG(8CMj;;)vv;_sYYxF0a4p4dRrxWI2%t
s+y{!*^K?e=Qi5>gsuV_Hi}Y0oaffJ{K;#ixusV?UYU*x-F(KSsvqp!=t*%fR$+4~clbFA#H^<Grx4+U$6<Lvhk+0JaHFvE^nWi4
MQ6fKg=>coVF4M@FIYV;1yI+nPrIQ@UgyooRCs=<QC|AyqF;Ym(-Fcn0YK=6M%5wtdHxR4V$>T?{3X2&;H}bgv_S+IHpCMH_|x*3
K_W-3YD_-r3?w#MXR33cnq`~iLa4fNe+qbXf&mKi1EGJH`*1ClzpBa6lfA|Xd@QQG_8-1Kn^Px$#bQurguty6j$c8NgmUw!7M<x1
f*`}X;y<TC;>AT7s8D~2`xSEZo(J`LW0|z|pPMqbu?tHnuomuLX!r%5Sam860c@&rr5A_5KHGug>3P~>P>SrrC?*TY)H8x98F|VB
7i@jJJxo1?JyXKzgAL>92WIT|Vf82JmF}K81JJBC$sPV<2;13X&v@&PYjCp!NLF9QdAr#Cn*({!dD?{%p0ZOLa|qg3bj6<(`3!~v
3>D5@3en$T7*?!GCzyozhj7jELy1QF2Zyv@P_3$$F`XN5ha=$Pw`Iq%>tVOr4+F*8pXv3_U3zRjo(x3+Wa9}NK`tfGLad;0Xa%_Q
4T*t|3Qtrwjs{^i-r6ZwHTA-<#&_L?3GC@RG&Cvd*+0T3NV>kC>YOVO_-jopp5Qbt$?Ma2o~<IQ-*&+lyBv->apner0Y_6Z>k?_F
78ev2>EFlMzZtgWK3|!ut~gjurDuMqkfBOtTg*Zs-X#@d86$1WC`rkWt>CFEj@Kaej<qJ=IsJY5_kBq=GI^ZNqm}iB6998~B%Sqy
u}Jk79;&|!q6OvzX-XSO*25VrU4riVL4QJ>r(5`d4pqAH039<qtZi6vMSZT96dQ~uMfYR*^R8XDbrz5NKM|~IBP$BFD-?33WaTpI
Gw&qZOa6FDg`oBo(fQnn%DlpxofI`lgi44$_i_HWbR?27&CR^>(sNpjAZk}(ou^>B?E!CDWk#8tnme=zt2sIC%GM#rDcCo+H4x8+
0G3s9mW$HbfCh+xQ7190{Md9?b&3OxKf2~G-hhjt@jq%}W(l|W!UpoHUfW#YZ|aJ!>Jjdy1OZ^up#<<|Nw*qI5!(GQeOtB${}N%D
c(<5Zlx*(t@GxFx;AO^6!Yn?n-Y{~Ckiq(zjN#npBaTm!)kMiOm*6%a4?aqd`0Bs1>siK>#{KrQQe2+BOFUjIzqF`C!#j1oNmnuQ
DMvIt@^TKEs`+TofnnHJwN`?v%mnNMy0RgGP}?ZBCVf>?eb#TE1%#&u|6{b#9HzkXAl4k;=%TEOi|_`XgXwfs@vJdwIB}$++1%it
aSOttdU>fIkTFkfda(i2ZW5mOWh-pEQ+)?D@>}Dpu6ZYa!As*}{E8%>`oIF0F6{2gieP{GYUkJA4dEo5{li11jD}lmsQi07^9h14
SaK(L;Da&6KA$WJ$phwT<NG%RlSO8Jo-?IVvVg1?a~u~ZBWso}Fwr@r!AOc}j5h2b^)8O%vN-@+Dm2(-a^kM^{<ZLo$Nw;{^GjEN
{b2sv*Y*^Z=clHhjZAw2`z2(cR71~{3l=Q37GYBH1w17Om%7#Mt^*0Ny#+vzJ)uYXdkjjut3C_MSZXCe8Eypx2?Hgep1rjHt&V+I
CX3B-BRc+aqgAAnpyH`bhTSt;QCvR4TB2A}Ca6)-)#-Kvb-jmbe7YWL{HxP7@0X`$O~<@=jF1feNZr$IT|wc<zMi*a4K4(p|I5%q
o-3#x^~O&)1W#s4U|{|Q_w8D8R{!GXG0tL6DY-*Kd;JV^Rs0Z@q~XQN+Lg18%dj6(j(7Ldo%Z?!r7VM<U33p5M?Hr_tDa`;db{;+
9{E?=#&A_lxXEqJr>_u8;ml4yxUD=(OJn&@qMW>>*p<m{HOhTWWHkn?nD4*IP9Xp+1$~8V-k+UtiZWy<9i79WF?%R15AshlKjDDg
whhXZ`Jrm>^(gJ1W7~+`*fP`XVG;=u%G{mpp~z&&qIOwzy*Fx+J2wMi>a_3pTf}OB>1Szus{oqe6{8)02&1H;5!Uqd2i$eqfQIxT
`G2BInXHhaR#t(FHoa$j4E`%ZQw7yeIVj`Ya!DersOohgA+ibKLOfPRaO(RD_sm|1DT!pVLw&9k{{YgFY|67WgmrUO&c7Dnte(qa
iLop13gTIkRS$jANO3ePn8ZBP4OfS8pq6Le+I8Ws%YymQLysoHV~u#yg`&opKf6qWR<eYJ?K^S(F*nM<jtyQ9fNl>aG9m4W2#Z%?
fwW-xWOA3YLHztVx6a7fX`&8%RP&cnj0_oSK8cIvlbX{>>mAhHZ>ddf0*R30l#_THMZG?pW&vW{c^&fHGACdE>)jF6J2<QBpAFu=
(Pmd*z77(I4L!`|17#c;DG^8p0$j$eqbr8{>yTMPG2doVjV;0>UsQ3jySNLPHdIWygEQ6fPK>=_>*dM#SynRW8Hj7zW`qkK1=vMq
|FBRjE>(~Ke&3y*<VaKOm#hWV#3?v*u_V|N6cY%__ldy6z0A&l1UrRp00)Czja`_ri0_)AE#VU@)8X+aIZ_bqh>}r%F_%cR<nG&M
^6SZ^a4H{@^_`TvnsFiR*5WF`5DKY%EQwtt4n)&MF!^_dk8ZGgRBXB9y8V8B{m1s-GT3Kl`%B<V|EUemG=`Sr-H4WcOChXKM^I2X
9NxnXMp40_7k1S0gI%Ow&l3B6tyz;FU`WG2&2*Vju#YB*H2-NZy+Lo6rM=9cItnuAeIosccMpc>(tR$oipp^G`K|AP<N@tH8nKB;
1^9Cnq;(m;wz+Xa967uJlhj+}ZQawU$c2r8RZ{&BNlRdO{vZ<v&Qa&ud_B)RsQgJ|I-UV#AtCx~%i1*0S0-h)j_#H!Zgc2fB`<f(
Oq(`0WWfo!EBq3J<$GQx{R3KHTrhtb&-|Qhnbc?k<$qW=@MF4WRMz1OtzV!>IJ1R&nTS*sH`(wzw;&nOVSK<5qhvyy)J)Hn@|Ta1
$Wg|8Mx*m)I4?P(BPO*Wy?j94ye*r9tm)G_?=U=9yLE?PUwAk77o<q?6u^trkYwg#n;g(YMrT5rKe0!DRO%D3(GQ?_fkO{N!QBES
Z>8{<EB@>))}UQ@w5SF7qlrv%sV(56IDI@XYEVJ@&XwkIR#SyS(R60K|53s8j-gxGS~$R&$3%X9``^R_1L<423^h~~yfvHh+o}6x
MOcmFx_Jqx$bHsotZ*@JDJVn6CL=8WlPVjbdUNo7vjY(o@7hn4S%S6_2y3KVw>i#D&Y6ks6|S_>c6!L8`lb<Sp%j*8ARVo;t5ab%
cn71kEl*)W`H<K|mavX5@?zRuG`#;Bet}1hG}T!r=jD;smTgJ4?xG3SQU8M(-fW#Do98U0^#FBQ(zRE-t*N5EOt=5ODD`az0tzLp
bU1FJO;Ne-)a;hha}o~mvYzQ5Vb%8!d^DiRVi^sW;?y#<GeU2NaI^@qEfW<c4+fyGln57HdGYjKm!l&TdQVD&?#?RQ*P{bt1l1*r
iKJZYXyL;*N}J$KP(@$&K!>ftBj{o#L6+OcQ;76XL^!D-Rs_!OaICl*XGN-H^K-(p7hOu&R6|r)h`~aZqnDk-yUaTMaRPDAC3GZH
3x}1ta1?-n8ew|Vu0Ex{L3FVlkxg&<w6PUB*Fw}b1ffJliyr-%{HV8%Y)8wLTIhG`kTa(W^FMpq5en=Gd?i7^MUJrV6*3z81~>|c
lx`WOtPHkYJfTpn66bRh9wQiZTbXgPIoGa>varAoLQdVY+5hm*rDzip92FLV<65+cO7|hAarq0FbHR%j&ijF0P~oR`wXUI*L3z>{
4^}P?bZckFE;MvnMhbGoEB7KtGx!^t%Hdn^?G4qH)Yk30V&I|zbyJkKXb6LWjXSN5%GwJU_UD~0UIiDksRNG8UM6QDUn@NCk3LqE
(Iei`Lic#mTZ5V77aPMnQqH>2NCy{hAQft|*bRjS05Uj(#(G?D=Wid(i?cBh^H3d+E+TmE{Ypl8lkf|<%{Dm4%l$WF>DwB?g30iQ
JX5@z0+>b3^}F1ITCO`4aOnn`aIguWUW_LD+(lr#^{usud*4gTEcPEPhy;?V|GEH(8v26Fm_Dqy-ruF4wC`@e*1#K!gFy$^8-o(E
p&@#89`i97Sb<s!h(O6Wui||M)@fXtav<4B7E5fQImWB;==gtvc=5m*P?xyM6!(YOwuZg&?XMiH3u>HR2I8-&U4BkCwD!Z9B^k96
<0-ph3ORhR9h@;Jldo+5h93%|Oc^C}urC(D>ZQHNOM%RnCM^TddHDmrF_(XGg!eGgDO#9$tWCbUk~HQs^g_8)p%q}yp98;l{5x&j
QbP+4NjTg7e3$g;N4o$@IVf-&{WzaGsH&qq@~hbMtDIEkm2z-hJ$j$FS2yg^d^XE$y6|Tx%=I|tGdjNBAv9EK(AH&e!a|rGfvWyn
`mqHO%?X4<H_^T;rqmHkg#(AJ<lx#$M1>}OVL0n8vIo|?&cy8Y<gs&Q1B#dpyBzE6h9=)676;KlbU`VQ6s76!$SBDs+Z}yq(An!u
a`($Ab9jBJ>qOG*$&NX`mL>H}N%>a#d3sXA5I1&*@{71&?4PA!%#Bag&_&C26PdlVo$=o9dd8rw@UQxApaAfbQCX8adzBNT(BQ<?
Z&@D!qm4(t`%Rk^%OJrc8}}x@Qx}?^J6nHirWA-O#+<n=kEs3Cj}Z^2by%)}P-fI|9J^xjF!dSI(|3a!<+uhD7K^~a3gr$gqct@G
0Pb}5kv?YxHS7Pt-vk+&9TL0SEHEeW<oK-9Gl5aD>wYM37hZcYu+^<KJ1e?wi9Csj<DH~Di!sNElO)N3VS#E(C$|g6aCa`lmtF}X
-kKw|EoZ4<n*tj5XFtj(-WeiAbzj;T{MPmhgI8#rU+LWV{HTGjxV(DfHm$eDNE|bq6KE8=1ySE1ma6G2V%FC$Qq#)*ZVrwv6#Jk_
Mka#kb61jnmNwt=Hv|GY9oxJ?)!<&*BS1K(t?elBMoXHY#b#?L$4E5z8a<(>0MwF?KOJzASLLQc>h|pm1m;~m3RcT_ab+h5W+gls
$xA;TqsN!m3=*5|k-u<tn@{*kBYxO#98dg@tTNAxvrEI?DlT@wQMJa(G3Du1My(&8Wj5I_74>rL79=H;rxqV&n2+PTab0_QIP@~R
_S_pW%^;UDo|ROVk279+mOjA3JwY?Qh91&%)Yf{sJf5VAzDuBYZ?cW<>U(s*=W>KF<>BEj*)9XT_;qoh0RMJy$U?lPTOYykBI%<l
M>x_Po;xMZgN~E7Oc3?cpv`$YG6nQkE3G<ZV3T&~IFb})9eaMoqmQTQ<=Y824{M&U)2j7lIpG)*_qT*%7A|hGa?-Kf(ViHD&nj12
*W`yp!K|vr&D3>U<>rzW*%?YRnYoCd2eUyzLD_;Nph^a9TBA&`#eTK;Go-Et=K-F%!Qj!8Kv|-lO{BiR+XUHSU<C07v~$%L9qJ)L
)Hi3d!O@|J<zhzfT}^Fyu53<4Sp6Ol4pxPloX=<h^~y47bu5qO=;(fnTDW8ZoDi%vn(V)~@}=h=R&;gA;k|$>4)bZ%J46ntsbbfV
bdJ|lmnd9dABVAs-VSUV8|ZSdLQH|$j606EH&t0aD#TR%bnt{HeC;Rd1c*~3-e}<N2ZuP%yhdNyOx^U3sp$gD;K0uD&ns$fG}Y|j
CtMt-?Z8%=Zk9IqC;DnID2wbWlZjb9OW2XsDA^pN-zVYZG?G`5hs2V`s*RPql;mm&%Z+G(bE~GdJGGpk1o>JKo%oGaot4T019}|5
0;UbZW4FX4d4Lkr8(G4++{#&rs>&kLvu^)~7H?AA5iv?UdK8&)hO*(KAtnvg>$3(q2xE+xdcv88rKn;`8pv`$M*?F>>37KB3MUfu
PL(o`RTjSwTo$`p6)(qgsHbw^Z4}(dT*H=Eef1I0QOiH}kWZts7)M0WHdTM5atpoz6hZ>j>c*=76!$@L$V0T?nf`Ug_cy0{nnr@f
MyDK?&cKr?!<3rLqUD0W?{@6q$U|`=e0jTYeP+v*C{%6IpJKnb$nTX(hN*w;!`L$kGjxYO=03ZwbGFqdG5HqNy%+I(HIl`=KdlZQ
2vn9;=9$KRn(h~kS?hqW7yrpa)g1o18}zBaCKui1w->@`QXiRMT4aelg9PxpiIs}A3df_%6{J1M@sgJpH7o;2&^!<Vay-Xrrf3~?
T6i0%EGmNFO~p2}Ms^WTdBEQ)BJ7I53-EU;j|3y$V3Eg3{iDUEC7320wSf`bt7AhQ`FfhEINKpf&mMC{f5m>G?LiLKFg{mf3@vL+
$i_BK?zayC8mCAhZ&Svmo5z9TKOE=2i<~JjB4(awBl#4fvRmP3P&0E-N;-wczL9GvV#>@NJFX1~R^QO$4`cUY>ri`b-W7TscaCA6
<us8k&H`OlSaAN`F6n`3u_Qb}qLZN_z)BrKElc?`loZwh0e`ss3UjsFec2KZNi!#^TS5f;JS-~*4Q4JCsI3KJ?dSK3seDM;H1uSq
=4lQ>jQ5VVY3Z3CP{R{3>1LKw0t(&dlkyy>ao+A%r7ao@7I^&@;<W_#Ln>QcPDMm9YHERtyI8k5Ic`F~Gtn6T%x;E<Bm_Sj6CaeO
LM+WHkDPb-2cmUC0l>ztbcb7dF6y!YFV}tGm)7PBq0c{KVfE-wQcaM@WQ<V7Dzd#4SoKiqA@oNyvSm;uy9hIkE9v8^B2Bj*uKA4+
-Gw>cA`APhd!4-UGf-@mCrvD`Y?3)*QNpNI4oew|)sPRvF%jszkuDVdsMz-UjgL=GU?Q*Nb4cf_A34Z&Y|Gc1Oh~N{Rkean3r1m*
qbUy?aZ2nx>rEkapmV&mq;a|0X)6}VJKnYHX+d7sep5#h^|2oe&U9g{naIJpaE2mne`Cvb)D6!fu>WZJWU5yTMNvt-i9JbE=3HY@
&Y=>1eU!d1^6f%N@nJw?u1+5Pq@TyjSUU#YQ$C^AiHqZ)Jg|v8CFk*0%!6fT9cAIY5p`v%Thq(ddwChqst6=3WDQ)&NJz>Gi-Htc
okis*9oHo)E*mhS;iLE;J~S0@uV2=KT(qEz6w8hGL!wA;UQ>mAU(gWU7<eM<j3&5wEF0+=gsAQ#7-pE}aEu6p%oJoAHL1Jz3(o$D
&k@uB0v$gMsTozGV4M5^Yxu;kzaIh7cPC+iPz?NIw&dGR=6jGmJHnDLa9~etfW)04LlGiy-N}bz|J#VTFtrx}EKRphFD6er9iFZR
Ig|8*jMHcj9T}vQ@4kY?35P=|Svd1ZYJ%KRxi$O-Zqr5}&>8Yxy>dbh$@hCT!3rFXZYEv6X5<5|NwGqj2W{NNXT_dpuzaVmr<k<^
#(8NCJ^t6nY}zEVeZka$MGaLa1SL5|w?})bvi(GgbxgTF^mr0sg)5$B@>w|7-B~+;qr%NkIec0j+2`Q$j-Da%KiUO>U4$t>W2{&P
pNhn3WF`H-M5%`B809VG_MYI*hKxF3U7YfDgJ_RqQN{$~vZs$a9!fm8=L6@u0?(5qy56@DPG+feX$n(1#jEgw{9daT_iE3g!)RIE
BG}#Ir60haS}^Vv|7}HV#h;=-Uwf2go-GUwf)!5a^#Jy5JCy0O<uz`V23%nany?lj@F9w&$+grG!N(isCKp_$-c!q`+*QGU4~$|K
s98MnxA&P_Dcw`nmR9Rn-Kz0mF9nK!l)|C;O`xHC+;IfN-(twPVeVRW4b;C*I-v!cLO0OV^~a!P(8TR^hF{tqj7#WnyYYVSN60SH
Ix#w|p@m7FWfY?YD53r%M`WWDGNvY$;Obe`JRRAik2wcB&n0-4?3UEQ^OJ?$3#$u`J_~qmU+Wm4Ow^Bsvo&6!-}8@L#I%5j;+2l)
l2K<&#?wJj2F%Duc$V)ZkQkE(l%Mz)mLy74{FNzRl35%6A5r|^K}Emjw+N;q2zZ;SSB1FTbR`rGNA`pD4|KD$DNMug6Pm7eRF{7L
n2L#G3NFY_X24jpkv|cpX)Z@rD>EvDPKMYlCRF;DY`Cjhqq>~n5iVdw`<g5`3m_Zi<~(F2cm^fBWg0e3Oi?st<troHbT1O#R-U+G
Nog5@J)nes>dnkUO-qLppVf3=YP#^m9z!@QIF|BYmbnD-G5!D-k#^+eU5AlxJEmhvm#!Cn)~J2YuDBl<uiUb5_sZ_s-B#F1tk+d?
O2hXQ(B%UQuwldJpZi+H!q#Wx0gnJB<WB)h(=~tc_R|pioym0A6bdHHM$C4^drP={Q<-7TWq&nvueee*7bH|eo>r9OHjO2#n!FO$
7*t<YbZ3W{0$gs=5+2Ke9-C3iYdXT8^?$plmicxOA^rzsMja0CB>i4p4X+EZ<GcrDRMC!XlP1CXd7RMSn$;Qmd>Kz1Ou_Sg3FoTZ
MqC?dBzA+q=F<{<+0O0Ky)pBuK_`Mk!J8L~o2WfyIN+!cBE@3nvpBM;ds3@Wt|k>E$Tl6Eo>F$V((|O>Z;PXg8Km+TrnLkDdiIeQ
qLks${b?YNS~cn96Rdo31EUj|ak_=v5_)muVY^#aHYQSt>FVD^JvgSxy}4r}UT*gi&^jj6?M@4y0`Rc9M1L6MBv5of*T1f~**Lp0
xjsp`Xp?TfGOO5_u80#eh!KzQh(^A>ABR58_N3D~6n*;peA{xG#M!|e&LL@?fIUsD0z9RQnT}o^$gsbIA(9#UVQ+KTzhFYLMR?rU
0+BAPXp>_TTC#TvYY2eFmrrNsSngTYA2PX7fZsie>H#!i`Z3W42?0{tZfvgeBk9pO9>%*JtF+MmR=PlRk(f@GlJEgLw^MP~((Bd<
_unCKk_dc+(SnyIFH{RGpJPjAkwU}&P?ZSck*y4j`k7pVD6PzaH7^dy*Za+vRAO-9P|*A_5;0jM{j>TcJ_D~TQXTGf2;Q%c%_Kv+
nbcnU(H-{{gLyW~G3RueQwyydyw({6{pr4@8!xDK@0D%%ZsN~tl8<NC;`A+D#KJ5($uSW-88t^3r-=}zr~*vdd?n}1Okn;)kN(St
cVEh2%xkcK!?f673wYnxMiOH{H|${9TXE)JxeX^-B>T+q^b9$xzfK}KId_^&#p{LLqYLns%3_f(_^>rW509FztbdarA8KQjT>79%
_ZJ)h?5Irf2&Z>mqmrYXerS%zC!1Yxp!B^pzp-rf=v%cG2K~ZjHtZ4)ZSG2s0y6BbLCZR*QWN5s7zHxZz=2k@^C&Sn`7(`7^oVc{
R#0m-+meCC?zBw>Lh%JtTAzF(o)Kad6cP}DCUL|>#7KVrnHQQp3_e+wTTz&eiIGBJ0uU#uB6$1K<K@4zg4NgiV?bICZ{gKo#HDTv
xfn;ypoeoZn}x>H!VX6b2*C_)FZsY5AM_&tzwcB)EdHMF#mSDXJy~Dp^X{FozoA|w{<@{6X1O=@4L|~SBUZXyi~<D%RCt7^7l_Z4
71gz}0P+{Gc&j13J=BR#;hzf6(g#nuJ4C|zI+<urvQx@^&)-`tHnkvLLUs1!Er`WdkyheTFF;W6VI<C&g-{!A0L?i0+}g<{94py;
Yswq^xE=z<m!&o|c;1RW+*>M{IlB>JQ4>B7FEW%gz1+n&UDeb~*2zk^nrMzTkaON!|MZ0b!wAsxDfqkVvUKpTF6^Ne85sXioQWEl
vgH@F>=Z;K@^ha8>Yi^sxzq>m?wKq}8^B$ZOgIQgb%JcE)S4pZQI7LN2X@VqB*iH-vQOy}j+oH;l-w&l1<cQDIq%I~X&W7NXC^>K
aj1xSaGqKYcI;H@CvFl^1g&^3i3Y&HD)NBb|I0UC=%Z-Fj#6nN{CvSPPUM{v+L3u&fWiPuj5P5?zvEumqhkaUj$T}&!HKw?py;^|
ccT|{C>awy9W4@V+r^f-Ga(`^=1$<cs-TfR{vcUc9OI0V53T{_2+{kGk{}qZW$+ccGsjXvv0Yq%hv96(7HXmMWFeEJ&1Qn#oR9~8
c)$sPXflUE+%R^fmcbeCh5_Ngf|<L#Q=J?U8r+ZRed2=UE559c9LqfTT#7xsHZfl58(fc4@MqQojqUqqlV@KBp6+vHks?!T`nw!D
gp?0fHk5KgkYM%hju^zEe$zWE(vJ(KjTdXO+%1PA70K%C=LB=RVDznMdm|CiDJv5t&HEUW*=)6P2v>=<kDGx}3>*xM2(<^C%#=|v
d;%`xtJ0h~$9jXwI><Xv$3L+w#qZ43pRtTUh%^gNm{<z^>9y2^b1qYf-e0-3KW^IWz9|OKApa@Fw>kOUO5#?L+>Oiz%CeRRzRP&f
fK|lhwY+9Y2yUb~EQZ?o-QHP5dTY9<6o&v5eUFbfh-&Y~jl-LZRo%d-)<h^W=0ghrh_&s|gLnMQTLyZer9-|HJtN0<ipWV1yDKqi
%5Jez&aq}ie;%1$ck|1kJ>hcQJ`LSk<nuFA&{ke4e^Eu}qUt27kHBmJ;~qCq5PO&=goo7#No+|=dlXdF*sBYdKQ4hD=6<kP)PNQ&
S)oP&k!Hg<J>Hw@sAk&z0}WUld?a$2j2~RS8k%XRI-vmW3RR8p)pSjkYsx6rK~QIccmU-=)oxB~V8L-QuW?6FC+LVrd$^-+MN3&l
4FobKsRrboqx6er1KC}2tGI!<H_Jk2u9QRwaT?!m1u`D?#}s*ZPU&%|3XoyYVW#r=an;DL(1HZ`{K_C7#3JYlcDD>#JhHHUBNUo_
U|5VN^vM7Ux>ltPh*3aPWREDd*e^V!_KNuIaqN943+`SME21C>=}J$Sdg(R31HFM0nsk*ky8&G(bR1o<b0mBCP~0Pri~En?{x3uv
L*bOJMUn_Y%SYaoP0U1z!;1Z>t`c*m0y8oF5RZdFb!q<tT-Y$>p`Fgev0=0UZHVOh<zh0xO}Apv?746Nj<pcba0E9B+~brylxG`z
x^x<zM8wGSUq3AfpaN7+>U9mQ`4+0pW_c|s(VE{tc<q@zBJM>Y^I%~E2dTdR@PgduT$si1to>tPlq>aKZ|vcUo4`WR{1ke>RH;5g
Q<TeKPgHD`*F2WEeC|r<x_H)v#*(=z^{;9JYWcSYEkNg1!#wiPe?rXY7-ExP%*<lD^-X1udP^2BMgIGUt3{U<(2W?QFt!x=qURHI
aVNeFt3<>?+2}+tDsxpWBqG0+Xg_yqjf}v#sI+E=rflntHT2^d3jCgS+8Mt@IE+_jPS#fcHU;Uzy9B66g~}2HhrTq*PssIy2z{FC
ziIz*oEoZ%4^1)|lvt%pEPj4;0d((BN;3kw25p&N37yMgI^01ME`~#&yL7I@^=vS}(3W9%ZLNfd@|^fd&4H{?a!>OrnczfN>f9u9
)Mu1|8qCFdL#pDTO2*}2ocvGG9R(NG73*pZZN|E6OT?cuqX*90o_o@w8?io{Xxc2vLVDfsn(5B+#awjBa=xfaxBDtmRtx-qp_B~5
rCIfQgHi3bl4ob%21oEm$t6I%PuaD=f%BqkeZWG^ji<r?)UYr3=y88HZScEk$0p%(I&5_Qo@q~;<<2I3(z9=RuW&(x=N=5j-8jIl
akvG!9Ju7H!z2CkIp;~X0b^^tsX9}NI&J93T-an?)E`-tpX~zE22!>*Qf2Wo84S2ANh`JxKJqlXHUpZe3GtgM;cz(E<sj*Z$GV(!
oZ^i+C}@oB$=oK2m@)1a2t(ySp%O^oF$eSXlh%Ac-BwhV01D1ed1>_z5k%w*uv#j)vcnPnSIsqvnb3{J%n!}s3Sto2%G|gBuqK>w
j^Fx3V!aLl@sp1xUHs*cnk#+T0^|@AwAyKAZ$dIR=R8H0JPY_ZP0eADaFlIAB~etCYDYRQSowK&79qsU0taE|X9VWUe7)Hp#)GNl
Q%I!cc;T%cGz2-m(R)N(;BFVUv(a1U*L{;6V+mc|Cm$cXh?ug(Kddl-IAl70DK8bLJ*$9xuv<O;?^r+HiX5~8Oz}(DEql(r8y$of
0Boh@V4s`6%f)!%(a7S*Y=aD;klt7hC6%cgG4H6;Fo}JwdUmsm6NyFoq%J^y=XVlNp{AOuFVR|6F1b(}UhR728<AHwh+KX(h2wbK
MjWeN)z<cl2sL(_OHhWLVtj7K(&wh!!}1NNt2Cl&x2=|4Okz75X176Y6rDu5kJs17hN%{4iT;g-HHN@m1+vc;rTM$wuOa#=va8lO
3}eeIKa~_+N5d4v#&oqZ&RgyPt)A`iXhcm-x~F9=P5S}~^A5hCV_*Fs24gy#)^ngio5`2s9azaYTN02WHrcZhro7fX^^~va;F95g
|9&8;jhhYBoGuB5;me6m^J|T6omudZy)U!Jn(j5tQQgR%+?B%^T&E0+^7}4Mzn=2Ke!(mMKgARTRJ>pHtLcYsD#OpuNB<{F8?C-h
Du@O_Q$AI)VcfDr6%X`rIhqtvK9pMCq3+;4B|{!k6+aXP>vKdKYJt%MVjIIWh0c#(7V{Q6u+<PJB`J7~hJ>}#`29JT>a~V5;OWHC
Bs&0U$O&GxfSX&shs$vkB(_7%LPc}|6-_w4nwpegbde9U-;@WBR<u?&jff@!>r`mXW9c`8lqjyu1RM#aOA%9_X&jHZM^ti0a=7Lm
R3=o>X0)ibVZ}s@b?L(1=i1lrIHtYJDk3v+@pdf)NmIFM@B%`oP2%?|4H`Z;(DTp`Ksffm-+3ob@GWkY5gQHPd+`Q()zAC|{fjnq
s@kahbUHvoa!aL{^fY8OQ_EjqaTNUbFKVylJh%+KH=VI1ENXM!<<d&SxDmq&-W5;8pLgqrftV#T$1-<yD7ufeyb#AC);{cQ5QP!I
vioz`N;j9+p7bSku6*BScB8$vfZ!eOqXu-et6dLvB!}>Ian@Y+!0m9hh<<*}_#1Xp)~|!tHr>V#KB_?SA`xJHFAf;44OV#9FXYsV
yu7J=3o31Z>wsuM9PI>;_ifPTS-(D!+4`A$sQP;+_Cwuzo7}0zDEQltOE6pznW^rz2K`cv+4b+7c!xexLH+~?R&V;MCro`m5g){o
$kCL#7<_G<2IN$jk3;Kq$9>3>uIZ7dS<8@n&heUZu-`6fW)n1*!X7b7S+gIh37s{K2@=y)?gbS$A9;0s_ee+eq7#9(|E$apLsg1M
Mn=l)l4V4T{;KqUx~#=lKIK7^e$qA&SvilR%}{HVYI+kmKc?+-ibb?NKO=*$+K&%j!3!*fK+BV<tm3mlobGO#e4E+MF|}#R(~Aac
mQJev*Eyz{#0Eu7rqIDmJ%P_vo-%siw^X;@2KukeGgfIaR1AaPWac{W0f~is@-HZkihiEpDGDs<^J-)oin`+AI#)m0zT!y>5O<$>
$W%D|ZMNrIqaiSS!TKeX$`8D?Poo5=RJX}X0cK|8*Zlb&uR&8(sS8qaBI&sh#S{TT*LIoX^04~9FDX;PK1%hod+l+-YCTm%OqP08
57rDp1~rVCxyg%f5x!Am2J1A{kz6RPts!a9!Ri<kU=@bmA!}`ID;Zw6)evD_*(Ir!VoEgF!h5&CBF{BA`#4Za)%j=BU9ke}P#N!`
ekVkI!31O8Rd3KMj{~izXqA`-N+(|;kon3co`@2Wjq`ZZ2#15|k<6@~GatJmB13hM887dJZ|D)r7?=v`R-!R|9iH32LM27>|Bg#z
w4&sD7y_ocrSzGO{FLy)6J18jYGq&8V|-j)n+AyFCF3!6bTL2=CSHy;#Tb|Eo*?joiHSdtUeW3Q$4U#bfzi$!S^K`GLCbbI6kyP?
YrZzL63IpFnIVKjy}&^`ri9|O!fh(ye8tjh+)hFYOmfLQ+)>G(#AEJMyD{DI)3H>G&%I*j?lo2G0Ep#6ApUdAn8EG_8i-}^60(4r
{|r=f{uP8N<{+Y-a?^Oz$1SyIY$$t+Nwj^bvJQqk-rZuzKgaPsNZsjz*H>N~z2;Ye(Mk4w{yDe<%%D0pXr3yi!V$9)LgG516dJ>{
xYtNUEIVL|#2UYp%cE?h)2Ovdf(^B-g*YHfMP#74>DT%{%^Enw%&mLW#54SWCXvj@i!9)C1Miwm$2k^qK7NtWIZIjyFNv(<yKrXF
AbgXiv^xS^;}90rmUL5+&yh$2B;JhMAqSPwP7XO>FE{Q9!8fp_kcY$ku?5eRb1p;r)5=h3!Fg1kJd!n&lx;+%QMp?haef{4_s*OK
kQ<f8TwlxhBu!LldR4k79aNnM>{vnbaaE}azFVTbRbmBoE1meiiNVKqinO}>R@Y7Ce;pRK0D%w(DcdXgPx)Df$KqfSJCTH?6qUk&
M_GH(MWOJ8e-rB`9DyOL8IYAA9Me84+dU~YGUA+00!(IGIIqBv==%=UCKb$;tr48P!Ew<z!yZ3mPm#TO)@ih)N7r75XBM<xAM!sC
Kaz)9MV~4cOse=u^Ehr>jgkKvR&9<zqKFb{2t~cX9^9M7a<`geWAfyeZl=f1{W$6TjIi+Bcel_@Jd_qBz@nNWk2lva-Y1@V)yXgQ
e?oF|zfE21z;_KhE`+U=YUQdhqOWZ`AFypGb`nLgZ*wFm8TWKy*J}d{9RmIQwM+Tq@Yt>nV_Vwm(By!nktfxCk!+=%Hkemo)_<D&
ld*Fb__FX1&FsfIMmwez(*G<fp&?!AcYx0>3W|~(SuZ$3*vo04*vwa^cI31K_u}Cj_{7`84KvecjjWLb-X%!e9Wt>arMa?S7s{T)
&gOe-sd)Oy#m{*wxVgy+QuOEH6+d{BhD9Ls(8KvVgG{cp%j?+rdOkSXcM8*&E(R?JebefSpBvq`KA(?cvKE2+g--GIr^ep4{y+>^
ZStk06dEmDMabwqkU=i6A4e1bXWAUWrHF$W=zza*xdVo*vbYte3S{vk<Q!!_>`inQPRFwF@ft(LCT6Z&2L_L-JYukslusU3u7-6b
lnJifUS=bnd*QvaA)O9oq#FN2V=-Riu5yp|=i%|&eVma4!%2Gl_=zdiYL_qgB%myY_T!&pW)Kj!ta9w|hn25sdSYp&xSdx)pT?z)
jOX##gtxWwMnC|Fyg<@lCAY{9Fr7bxFS*ohusbg5_D$(Vv@}$>N!RN3{@6c9b|BSq3h4^og*R-w*y0CkJwj2r#NR1rg8GLZKoe~&
d>TPm^=>tYZlJ)DMXR%j1alf|T3AkrV@nGd3yXUlg)8<Ppa<U7*8leS_21Bmk2l_e`7zMLWtMU5Y_uWA{(NX;GQM%SYLu`B<%J@+
m0urqngEsh&L+HvRwya+;uRmOUn0R@ss?-feWz??In2kZBcS=^iP7;m=Pg9I-CDTCB+T?8P9LM=nv-u@k9mBKClJT7+G_v-5BPfg
+Fd<+!}J%jP6B6HK0N_KMSk$dC>npq!0U4d#<;9kMM5rqOctbdi2BcNNQ1<lqX!Ik2S6tQ)*ukS>ZCId*~#62Azel2&Gsa-FU{f_
2V@Sbww-RtTsdaJ-*dKaNjndxB7eegH8Rsqb$h}2Vxs_8e}-JHjXdbP11U2AVfnf$ZnHM!`kPD1W>3<_&vtFok@9WCD*YaZ8jEao
wxp5GC5n6KDD?D8(@xx&J>OIz_mh#BxUJRAXiGK#xpg*G(9Pe;>m|t$2$`!P<#}F3<MH@r=$F+W2&=hSPG5tZ(b+SjZC>7NlmtHX
6fI&UH>>uf3uU*<ON!QkZL3Q~Ya8h-4gV)<TNkz*d}IWjEQVE3NLIHf0_3i&lPYCNR^vHV;unZaJ+9lLWPF6hb6^e&8l_DI=!P!6
5>N<W>y<>XpNbkOm^7I!(<-12&O(Ar?P@0!tx+oWHnK46Y|`30E$h43A3gbKv<pi}ogiOvH_v0t=cR$&3be$k?T8NcAPm6-GV#O~
&GPHX{vHJUX_GpO*=KeXUhB_OUbVUgDjsyDJWXu6zka0?cT&oAk<zdNGO}g)A2tLo&~{j4=|M!35tM^`1is^Wh`8NNeVFeyvrOuE
p%a(A`#z}C+(-M+6-Nf-Mh4@zf_r8JK)l-X)3(E@qEQh8*7#!}?SQ+sJ}%0TG$)=Fxx?vr)Ay|in3>BAV-R^qxlV%V6~TaWIvd~k
J1yS98@tmu`KfeP6`U+S<X*}pqzWJu-(Vv%bqN`gq+bBwyV$7@27pw2m?}O*sDG&qoJ;$Bx7M$&F>0KBUVWy`<2;Z{uT%d4tSm1H
J6zX>cIUP81k5V;u+^e10}Iha(ZEqj2=y;GD%kK>w8f!h=VHBZNr$f1t&t}~mjm}<-y_B}1FJ)#M5qXNL*!oJpxP7Q-7FJXZ^m3v
A^hR5HKy4Az)sz<{#!;3iJpwQ>f+5B<@FJYj;TPy9F}WE7?KXw%?u7UvGAg<y0pI{JsG1{?(B|gN`=If>YU#SnDTms|7M6ZQmY&k
*HGvq`96n?WL08uX-;6%w!%L<ARqDsA_b9E5^JavxG;HpdEE<#y0_p|8uHOPAD7@oTEz{cEe{3@l@|7nt9f`33CBT@HHQv9cK6tY
^6BE}ylDy7WHU{!8mTDrpaAYA+UceGHAm??{F`afAT`cR?v=X5pe+6xJ~RXjkiPQkI+FHJTs&Xm|BBJis3#^qDXrwmjqaDaT9DW`
Pccs31M1-zzU|yKqw5@04IGcy&S2j_X9HPp1T~(2La!6(n1wOXwuB8lrDSB3S>6#3Jmi~0+u_8+H<p!b)gXldgVF~Ps!!e6FGMG#
Z@h*<Mi!d{1yJHTVLGu~bg7Y-Sg5nhR}|gxRb~_5J%n`-f~DI=M7QII3%_#z9s|q5Kp3pF@o?EXkiYk;8;HxOnbI*sj)6HiOIQop
fs6FG&gdCwk7p-Xpv86B{OO?}%T4${&g$r?ZL`5VDJ4Z$<(CbqPpbXRpyMO`F$*DRT;KbAdBXS-Q5Z!<8IwG>pd2BHppLwX={cKm
a3d(hkH3!_AKGgkd|z?pU@=KM%`9_%4Vswv{Q1$vZ1tP14;u2x{-``w|DAGhU}Yjihf7^duWpBnqS&nJE<6iIBI(v~;z&>!3i!uj
U_d)Vtgq!)_6GXf(C^fx;YqySU<}<1`xHj0xX1>>a!6ZrttN5~zpjxx#N-S7fJ%n@w$c=5<5D=QxyZ<oIN^s=&gZjFUT-j_6LP<X
9T-H5(pa4SD~IBlI4qKSjyRxOs6xZK43JI}U;cXIS~py)Qia#e)K)sFw0ca2QZPHVh*A+-Qp;8GUZ7+SWk&L^#D~m<(D7G}?@~&5
6LwnviSh@5j7UKd00mHH^}3iecTLYeq4B<iAD^!z$yQ95CJD3}Na+qBFh$2j`cMRBc9r*H^|hq7y9q#i^XEA*%ggo3SqFUfWPUSN
XfiF`KJ#wysZCK9QbMizlT+noNm0KPlHjLz_^v7=eX*!{=_&Tw&dh&LTr#+J1=)=<Y_@idcgk-!G>bUs^}t}!D#;rax%#tnddx51
4qGJvuq$cE`<DiDuLfxJl$OeW@SS*7aZ?oB3h85)Iuskd4wtV7S^#{TvM19I2cHJ$MJ?7fXu%q&vM6?)aWoFtc2Khnm=G_<l<CY?
1{*G<`4}5f%-^48D|*H}OyrKY*azl^k-jRxUNt9yci1j>@C&)$CgCVBw5fz^l?ojs?sv&BNLaSjNphmUt_&8AdXwuI40^xYut6Yq
88>y%TG&5tR43u6t{;r$Gk13`eAoGaRyaCFR{DSL3x)^Hhwov-I5(!PhnY5(BUUq6@u>C@efnL{oC&2nI~3tT5kPgGCL3}U0|x>7
r@jq_Khm@qmewm;#}4$XxEc#ilY(uuSeli*JUcaE0SVIxTKwOXB8|G<ZPhz?L8Bs&$wBG5z!CuSHEUT^!S!7ecN&yR9uVq>Vo)$%
H4>F*nY8C46l%;z8q4<1yMrya_Hq7JWI9`x46i+XCE3v51X6u{X%Wbv4v<y|djtmE<J%l2@xtaI8KiPV?}&lgr1RiUqPZLu2-zNP
lD9p{ZSnU7$T2s4xIcHH=qSP>%FG?S+E4+#Oys!}Q=SUf`t*sMC;&7jT0$_A8Q&+CbR?V)KI)!L60iq!8}E>V^y15wk>Wgd$D8Ae
NmCmFSsdsh0J|kudjtd2Q|H?_PQeG3UO_x{R&?l(#;Bob<o%9?tgCcH8tMDOZ@yEqT#X5AoU=#J@l;aMS+X8;jiFe3lJM}-h%y`+
>(7{Hfm5FQFhoMBPmPdRq{ZsigB^XF1sufxH}J5!OB^58#=dEEM(aDLN9KD%gVZPX8|EJCq&l=}n@rNPr2VfWD0*stp|_%fhjOVk
-XjT60{ieTm<3oKW$zP~tG(kv6FjIc<xRYW31V=`YDQ&l%HczrA_Y-WZ!KYPOQ8#%A8yz9qo{NW>BFOvQo=aLPUqWE%Nh&(@lG#g
Yme|ewSvo&d+~~O8<kP6t+&Y94;6?XMl}UCff%13vzM(`hi|uR!g~)#N|(RsbQCGikd!<J)^%_nWGP7l!&n98D|4dR9$mskqUjn?
!hab;Fb<}tkG);kD^aOcM3a<iQ&)aPiun9WD=<u64H*ByaiNZyXT>fJ^Mh8<t~eT?1dc+s^tk=eGx4z9CAj9Fk?BJZO}?+c^WIL%
d+GJk9(@G6g3}#if=#JHH^f}!TVax74tmKN*?Zsx`qpInC``QeM?%JB9?lI)?U`1tez*zWnIP4NzGyfET)1)G{Ea4$(ezH-Xa>}B
cB(?f#>gA9bPJT(512{%`o_=+sg%J{Yj?^;K;*eE&M-#w0{2K#ulPqj$d@gY?;ZkUMl_ss@y^_JoS=ccSHS~NQF{x!+!9^(81#2`
cU9(>(W`93DKKsykTeKh+RQzgA9tO%NWdgC;mTx@6b;lzYv!<!&w$L&p(zQUGlw<-LCs+IAp33Ea_*;7QZ1I);ne_jUytDQw&%@C
`UQ&ObLur55m9T>9^Ua-q$5^;NjZ^+M|T~Wn+sVd?ixn?&|hVxzixWEq#BDyx*aEoMq-=oRv}<2{GOXayDURjDkl5(F<ZeLn^$OD
mbYIS{Fe~F=JvEVCcUzWYu&W>ch_4YQAs1PPObA1?1}W`#rDUZTKv*z;A|~ttAal29rZsEUK9a51lfWmxH=np$G2e9W>@Z^cxh_#
b>GF=rhb>aAYE+e=Wt(LKORddsp#3Y%%8xF(l(08+GT<8B_9hQB&O_RdZxlCt?YS%CaQ<QnQCmStBhWRh~GDc_<^4e6pokp2t2pQ
GrZ<DEgrIPrs!zXXhg`}SXiStEGt3>b&I+IjAMM$+8hge?T625+7P1nt3WSM!4Yj~AkU)5((v6_&YC&-s4-lx0hBEQu#HjJskD^p
BVSy-C*q<OvSqVH0K=N+tp>sB1=y;UC0|6o?kxq^VD@>=n(M^|W?aH+cw2aJL&~r4hd!&(%!S<#UvC8MO-`|z5DV|+Pn5YchB1D&
ce=Csj}%0~3Myw2j%kEj7<iDy7QV{c6{=vs=ITbmg*>BZwhZ!M%X>;R{_Y<~k109(KU^Q@UH^0#eWrDGC3$ot$FnjjM<M@4p(zR;
v%%^-Y-O|++Y7N3gAN(-U3CxrM$(W^!QQDn!(;XM+NfZSB$y^i4d;q<<5X&!8eb<F`2N)do$?4M^UnG${}pIXQA?<#%LF?IrrTk5
E(OEF@i-LKtAzWcfTi#_s8PL?eR#Up^hsE|BBG<9a2J<*vbX0PU&xwVP`OpX4H_C<O0cfS&TvcHt-i^B7;(X+SGsDe5;NBhh_VuD
4o%tBYOyxf=nPUjjGY?5@@szz;5U6&Nuv5=M-&@2Te2;C2!?K*??|3syozQfXxrm8D>NA+@0`1#%>UIv?7ZTAzJ-<<#Xbs>C|@w!
k4d(Z6cbUcXH!0|2Rh76N85ZoVie>sp_X(h;cn-jTWtV$86}eX@F{{Y>z~7vBYz+QonV}()mg-JD4M^^mEh9Ilf+N~4T5N*kb21X
hj^4k7wy_m1gc7rL2uh2674eNBH_;n5t$heq&Fg$hk_Om<L_5lZq^u9Trh-{-fw80T#aNSt#J;FP}Xbn-!kLYj`L|9)Y2sKI#A7`
>jm|cZ@5do9Iq51o&paWDRzk3nK8*W@iX(I_iBm)G*^b#9grFsvW)&Q^^2e{cM8nQQXOYB)%CTto6#Y1hoO1Igl}OtV6adrwgzOK
TK}3MT^$7_x^_1SZZ|mDZ%PS-VTPKgiGri-U+5bTR_NBQowX3F${M^}IbyW)T1A>fZ>&EAs9!@dH18>}oE*_o=anG6lWsVl9i!Tu
Zqc<ch}MSkO!Gf%e>cCy<^f)STju94jq1i_#4QIzl=N<3%~#u|4S5YQR|y~>%xPqP#ef{_GCtBVyLaQ{SXmyC9otccZB-{YkTSXp
?0K0X)GkEmauCu}^1>dM;%O_^7l|EjLiXb#JOP4Gw&df*`o8FOi>}yN$+4@Bp8L@P1D{i`ON7J{o~NHhQQG?x+DIqkH!RifqJ7dA
P96n>N6Jq$5`!aG1svh%%12&g`H|r!A}^WwmvdhaY!L3B=gp>g1Pb@M5WJq}wpSagRx$OLL0kqaw=$SDnPaW5>Xkc@ceTB6&)OVs
NpwT!U)UAy`3pOAc0B1OiYCHalFWK_<F366zWRa{^D~oAvAJLu?8zW=wz}8b-9kDKf6j+P$x*JXcUd2NIz-;>-C$+ryUF?hCMQex
7)(zFz16Uz;BOMjfE;-WZt=bu;R#Rejjul2+tERY5U3alWcF1V2Oli7xQ4qJ5h@#N-}vb}X{d>UGB@y8_ZRw<Ykf6{U5pTZl5T-^
5Cv&;A*?^cl~%`O2iFfN;jm^1h7zLNtink3L_;;rrD^c=Y^GdQTqB?nqy)-%WJ_fz?#nw;RpIxiKVH#DM%bc&BWPHWUwR_iSN;+z
zD)lguB$Rz9qz<DmkSngapCE33792Z7Bj>W|5MN+Hf;Keki#G98x;Mqer|Kw|Hvuf5KOVKsk{QhuP-%GCxqa}TcOOBa4@WccXM;_
AtMZ)q#;k?`<8&l(3p=Aw1m^S1)Q3BUAaCwWw(HUP!&b7yC%J$vQOh!Y5Umv(O~!<*8KA4_G>WmMkl5vx4|80HW@iUn-q;gCL7wd
OxLiLyLPCP;74A%0nIis+Y3Q`p_yGi^=2mQQ|kSYR)De%`{B)8*F^!eSSsxj)9a>ts9bKVcI|T*p+WZd!l}`DO52y6Q$W{ybj_aE
ZmBg-wN%ay92Mc1B%WF!)`{5Jr6Kkza;Cxion#2b=1vS6(KGTEY`gkzs~XE>r3C|wMq>!TRQFureZqWj$m`!qY^U=?Hjtd*CbPZ+
FOtsWF*jCTUpw((E3ei8GRgqetgE{e7()!Sa~T&FC+#1Nz;sBBknSFWB4d@$0-7b8PT;}udld@&n{kh13Y0Iy=ZYZN!>mf}F&)=3
vkpPiy9=!|K8y7o7cY975~u-+;<^iT1Z?j<b|Mmp1+uee=KvadV2-#g8*4POLC=|oAklcy73qWKU__eN!zPuf@u#8;5(bige^~q=
5j2*!6`s5slf`Rir#TsPoMG?5a#+Y(>u4Q?xdwa~8V@L*q1j3q6BfwhtjMptp(9V;?smQoM!8K6BwT$(S#us<jI7+<OD}^MD@lQ>
nE3?>n(snd+T~Q=98PFPSqWw-qdvTRFzMsMgOC-7X61k1?^9`4c$wbWVP8<`L18OHQ1zNr==!YqY&)!fkKoMK%_d(O7z1ei4XYU^
a6RoJI*(t26)*1*y*a054iX)XoTthgIt_d}Am@HXVaS&l*DrTG-AF5wQrmp*;nB^joYzO&`>;x%^bG|K)ziq2QV|-`q5Yzn0D4*r
H<7b5eqM3Cgg=k(1@+G#@Z*tMpae^~VYTOOIOd~1$`6$eG+03ucgG$>qZ<6#SR1YS8Q>ptK|N%n+!SZH;JP1#Q#V@bLLlir>>Ew-
V1trWvGOYM0857-(R<$^fvAcnnT7{5ITt=4Re#;ATwQd0M}-^z98b=JZH`{JGFm@pF8y^4b~)-B_`V`*;YjMQ+C?)XHa-yfT(DP?
+=W)?9wWrcko(V?l^W>~ltXAJ;$cL1m>!cYFH~us^{q4^n>I@yS@gj3^7iIU>rObOWfXnp<HX;m8a1*_jw{GnqB2~y|EPmCUiCRY
7@TX{7xv;$-#TU!AeRFr^&TY_T)lvV{9DpQM@wczz{F^^3*2HKv6HJUL_9v8nm>uA5(KbJKp=sYS#eAj0P^hMa{TO*SZi-mN!c)K
5z~ZlpR=zePoRvce_muP$dG5pP~bqzo3J4+N0hWmzr?`DY;n44_Bg2J!_>-vbAL9laL!N72?kE8ooba#3|>1!DYCIrdp_RKo9c!u
>^8_kLOdvAG|<={he_@dRP~gT{1XLr;c_vrXCbF3gcqdpTU>Et!C~{OR9BV;sy0jEwa8U1U;pFd&x}=pxxleUPrk2+Mgt9g<lq8q
FmVQj!!L38+)Eo~x+POVQ3?Y68CUE(jsD<{IQ@1CX9BS(i7dfE%#}1VYaU}ORZNhF!Yc1=l+cbMpLf-TY@ggA1-L$+*~dYESPPji
bCEUbgaqA_bEPfLZ-X<t+|sd@m3fn%!<w-32~HfuR?+Hm_PRm;&R)-@?-f|t7vH)NXA-D&PbxmI%mj4t_#uEfxiX%gik7D8I@MIL
Iw0yf$Vm3jcGxam;XK~0*l!8isODudf$58Tjq}y~egL*hf9MC{KOlaIs_Qe!QiYf_Upc9RH>in<Z7Xoerin{P<pG@f>V9S^t<q5p
<BNG0T9(q9s4|qzUiw{Jd{OTKrFh8(w)xfFyK%vCptRj}TystIceX}kFBYbwv^-@GXm_xKE_FRsd0r)jtn?(;Ax&4YghJ9~6TI3g
@G@jJ_oWU_DwY+Hz&}WHvVCSmyl)EdE8l~VZc^eWZl$t%{wKM_!KA3tLBan*!$|;gUOzbQe2Th7Fyx!^WCt#sm?{NC_`JtX^l4XJ
6AN@7$xY6W1IDT{{KIy>{;EMT81I=-AxHAQ&S>kSyMiRxH#S@L)0M0@%bzQG#ov&dLJ-$$E*rgewiNBHPp7b1fA+0|`|I(plezNZ
%Q@Lm=tSD-;9NsPplB1Tg->Wd<TbBN1*lmX0m(MZMz62>HLt+WQRlodIS_#C&SE*1**^v;{F!SHHHKn$Y00}KaEU-_aJX@f!r5?z
3P+WmvO8gnNwKAAq$0yJi}^GO<+fJ0NpF#@9f%L;oR%W9Gsu3JdQ1m+msWrNn%62-sXemeWPqyp)dWMW<9tgcKcL!yGI7E^q>$SW
FPV+*HaHftyaZbJI@r9)y}$TLu`C<=4f<cX?Z!S5aDT?5jBn5Z71@!12md3`@*dPqGGH7X8SDnRfsBDabn4dJ_gAj%_Ztktmx8@@
4@Q+&VM>XJ$P9!#*j<SX8+;Bc!3RjmS&#ef<5@uuJtrQe_gg^WDf?}ri#(iA)Xc*`5B&w2^ym8^Rg9fq-%WrBKZqg#XH;6p85<IT
k}`O!h-P<*ab<ZcOD*<hMyWj484Wm%g?`x}vx6q{{K0;vj?6$Nu#2rB1-TIhy3Zzad9LIZDVZNHWs54Igf$s6mDR|aZIfJJ+&ro#
^S=<Xg?l#!<ianx9Bq#a?qUAi6s%szIqAy?Np8G>3Hg%Lkd)3jJZ7#~H@MVApp`*r8I2xIcprE2Lm9&H%4+=4n!tG!BxiOvxg#Hu
>fMYtsl>D7T|6#BK;AcDjyP9JYuLQ{n~PDn<!ND^tX8^b$dQfEpRqGlZM~s3xjvIWKHPQ>F23UJK>WNi%BGZu4;<07y?51Bv@;L%
q{qHi4PD`#o1|Abw%U7g99|%Oc^TQX-}CBVPkn?#*5BU4d44`37#@b1NuBDD^0GF%1PLE`KjexL`%aZ~XKalW1&WC(-<i%vf-?ZW
jk<fPi^Y-`&UmXry}#LXIw?q=%ItsxpwHi>*YmlaK80FMoBon@9jt%e=qhZ(1Y`%l(3YfL+e<BSrq!vCbH;dV+tXw6JzL$5IP=s$
CUYyr$C0e?Nwg@q9=&ca=hKDIx+fOhTm*iQb;=K*@ns7-2RU1C{u>~Fx7|R6++irgjhAiKCwCOZ)NG2~N6(sy5)fUEW%q`cfgPke
*X>kc_>*i3v3pMmP80B~O|Vx5x2BqswkwLw!8~ZaOm+)&9*Pm<<G?){I*BZ!FNpp+8j+Yts*s`aFsh-BFPa_&P=h;^w)myO;d@?_
hG@bs9zg7W?N&W?<}<%ToeJ{tw4SRf=kBc(T&93#<P7gye240I_3v}Mw7;g80WMlFhj5#3O$+Jm$d{$n(zSq>=nsdZ@g_F>d`GMn
hJ^Ti8C{II@C+SiQ$=U!lFr-Uy_N%`=)J))<_gmyG0u&%q{_nR+uv)nj%Thr-kgFBFZRT~swTOWkMBR*_K2{SPFnW$4=<>^D9dWX
e=gE8$q#H<35GROQ3_(?wx*y}Pw~IUfF*Yi?ww-h5z|M08{DX4&Rk=IyJ}vh$a5g$I33nrWrol4J9#FJm*qUvs(E>`*IEQ@AqYjN
S0lTw1yXnpx_uy1`S&yv%F!<?w+)v+y89-E67}yo3(}AIA^Rr9R`tR9s_cLbamyCad&w|)au*}e3vMTe0|#hH9<WcTIZRqdGY4wh
+`Qq=1$&@Xz_roQG@&8-1TF-?2LFi*pcUTBR3`rr<EJeukovc5rH+!}jEz@36d#>s^p&?XZ7^#R7`IO*CYamrA5vRsNjc5sL0LAd
&;UDvt^3x9LN+}xAmN55z%s+XBR>L=;-!Lm2I;~v1mSZ|e|7;q=wmpRAZ?*q9g^72tKpax_LpSq%}jsc?a(g%#NFoppO*{szJ71Z
u8!%ZVq~XJ<s}4c6gMBjVkJ?TvpM=Bk7}Vy#;FU0oHs&M(N|FIt9S7GQcUj)R|V+?5C8Aznt#Sz$PC2?K1~MOyll;|w;Q%g{L1`&
ect$3d8e`o{SVLU${_gTy=iZybbYojR0LU{{-;13&U`+|K|Bqu**`2;b{0nO=heXr1#3zEcfLUY!5hUL4}k%XNyhS8OP<K!@mYkc
<0fpf!xq?^@bp4p^O9cxx{I?seamN>I|MdidbmAAW--cWs_@+;;*9()$b%Gu+KzNgptiy3QE!zr+7JkM=>1Z0QP2k1GaYot+U<zz
5&z5+b?AZ+x>&%zB9&NQ(g&|-@pug>0tDqt-46QeW-dm_4y@iy*aT@%YJwq7e6JkrOBZyc?l%YiBK-hJ7C;K)j6-HuyPGW8b30VF
eE$EkG0@YV2a{Hym|A(d52z0!UEJy_=6XYw+hir6hc@<?@qTx?y<7jpT&Z&^)Vwm0njfExLLcz=*!sK&LSG_Ib9?sa`)!`h$WP{L
(0cA5%N=aW(|J2{TX$LEWjS2%JC*(;Hh+#rq)leWCqp-xo8di++K+z|rcorT^E_7N??DqaZSTvdJSc>QIOV&;pB|GZck18sP*YPk
ay*e2nwyt=ik+Ss)9`0m1M%{!E86SwjHAQhB}(9F+i-ui`L{|zW)>88p)3Hcg74ptF~c>o!_&R2td%XOdYO?(v;s^$+I!da)`LO=
_^A&Ep3Vihf~gbE<=-9&ijr#xHOKQSA#*ztRc9)-z0bdm5M&f*T8%+(zy{k*hZyd``|K9GXBE5^q^1S!vUqjY053V0n7Lx6!cP{_
ma3?FL}7tuusk(Aq0JaO?vny14R!a%r*n)t3s7l<hb8C-{#W^o`xn#YZV><H1noi`Sjdu<8gf%t$-Z~fP4SJkaBY%J!uP5RE?Ki<
^_cjx-LD0Z)O~C5bYuiMF!jEfJkSu+%g~grx9o^Qn1|m1ogi#Uo$;1n9Wg(Q?@2SHXuvNlKilBX?KdjBoWIgL4EGbFe#VeJtMiZz
XniJ$iUqo+B!G(jN2RcE?Ze~+eWFQM@HTRd9?#3pLpljxot%36k@A6Byz3Vl-742UE{?wzy2O=Yx5jNJ!3=}zotr7v2w{>%>ze+n
<$=x~n4a{~uR(r)X<k_h<57v;8k4E$bByoV8RY<ruT_wEe`?AeE|BGsc<+<Zm!Pc=#{6JkmHo6&h!6wU<nGWD&2Z+7#Lzco<~GS9
h&Vx@<oM!Q68;tTDWdSozbNQIIC`X4>KbX3oS^P_XxYxef%;z#W;sKc3x!f1FKO~gpORX_x1^*_W05?Dkhx0#H9TrlE{-F)h=kaI
{3$A76}I6|55zf35lO|jKTFj`(w~Y?(c7Y$^Pqh9`vISC;*ig_n62fiUl$fnqSdGGik9Xb-R7JkE#R(5KT5kHY~Mlu_i&i-!N8H@
gnP(J`Dnef_HGnHA+XzAX5IBB9UZ==PBVO=(9H<d026F^jyN(`0XERxvc;uxcl7K6Z-=|HsoFg1S<-1|T5PzLd>o+hsF;(7JQvx3
=|3Rl8@@D8p{a<-R15ovz_|Zb4BCbCBuhXi2g&g?V#5a%k+c_j;{z+Dg9OI7NeKptyD#`~_Kv@;I$`<W-I*_DXRWfciV<z+bgTr=
l6ARSKJI?N+9dHm`>ASKe&9l_Z2E8P3S+KLLv@EKJ(ugJJ&novu%|Zqq-nH(!lMq7QIL0-Lfie*GWy!h1);Wv@s;!v#&9t|gwLdo
^L3cBPR%&P=7hmMJAjPEsHa;fUyb)5BZ7qIY4z5LdQY(nBiwW9Wmqm&rHFl~IdF;FCe6@+BrGo1^iGhfyU@+gftePEm_{ok89MR^
<R9{qe=j|iG&Bl5VgGnkDa8*JbQfVnYu@yr)d=A$ismJyslZO-BOXe%n<MO5?l8-YRoSGwIGDz6{%dbCBfEvfPZH`Zg_&6|_+1BZ
Q)Cd>IqW!Cv)QiWVWklCYy%T5H?F+q#bE@apiL6$>#zv6z?VeV#bx%bixlbv=fu1ZLzY6=gjZ#UX+XT}QAp|9H9cw2yXb6aOd!&)
_s<--L%M2g@!ScYCLt!(kW~dU>irh#bi4O?Zh5$4e|kc*eskE1FXbvjH?+v%kb}7j3xg%=dwoP6wYV^}FNM5GW6lMZH^oCYj^>wF
hHkijpIU`rREzsRv19LmJLN=SGZo9G*k-<hIs?N(w-xPo1Z=CMoBeHpYnx$q0lX%OCazc^I)>0l<Pm?seAsL~z(nMtdSZBr)%juf
zob@9siM-9EVpa1kVLc-iUsjD3`xi!*eZ;GANrsNQVD;}?`b3QFrg2DF5U{qB`Tt=0>QrE|Gz3$*e`#;?UX>?#g@Bw6}8zU?a|0)
3l=KgA#nD_Am1UsPKBoI3fpM1`?4VxS9DlQu8-ClU-C-Kw2zZ>s*vG8ABg<3Mg&9OKOz^s=33I{w<D#A5=8Vow;a-t;6vry+#9VC
Zv?nYENi+>catpVM?Ba06^cMxum+=bK_{7%4Ht8$r)QRQ;G=Er$3Q?7%Zlg*?E-eWKNss|76X`vH%VKIYsFZDoyscE0E+J7e3Tk*
^_z!vIs)z291xWoNLd?^3)N<Ovc>k9u-dCt)2cN3gH|oeU!@Ie5FOR+z|kOZ)~GPQjs$JUF0U}7BK;9RU&|R})-@M9YwuKLyWXFl
KYlxPCR`{q@tZG>%L;}AkZnW<JDKADcYhyQ?6r8F7B_>jW}qDi&d_*UI^xMEp{-6^9>y?qYhXGiQ=bHWl7>ppf^!yg$oOnwjv#t+
e>9xURbdH&3}=aBB<&EN$?^~Nq%6LkNUgj@U1rEOuOj&tArbcdHby1*a~Q6so(bg=y@QFMdNaX*kAsLOj|+f0y}v_%bIx2yIOGqs
Y~8A1Xvf)DASWb4h;n}`3Q7|EQo1MGDqS*bcOt!ch^`le(KCMH760pnu1-*3((vg1Q7tR~%GZ0e(6iH7$Lc$q&V5|_f#%LtdTC9W
o_}tYAxGlr-H%<WHOJ5w*3N^_uylT;TN`qQT=z;9QXuyXMjC+V!PgO884!P+4nbwXTr2Uomk^EDGU#@d13AyUnHO=N6qbI&(Tt6o
boo1GJ~TUc+q>0E3F{K7*<)9fQBlI<!c+I>{K|86*UoKVHIGl+HSTVBT3Y+hkYoDcbfwz^f1uBoagwSw4##QS5ykQ+(+)HL`ClCw
TY~qeJ$Hs@H8yKVJyX{`cbK0vUWR~2p9A2JJLW5DOA@T!MU2t%%ZV@6#~+_rYP)96$%K4#MULZL?3iCWw))?&kMEI-V|-=(PnQv_
Gy1aammP_ew<dcIz1A}TD5TKTzm_?;$xBimZ+tFE?roYA+l9XvUP9kng(IYcAHm`GUE>qroaz?bcZlzH84yp>jrRXv<R&~!TD8@y
vi=Q1l7gYz=$LGoLnW;;kl<Q+aV3Wr!bfaW(ckooKdT#9XRMyahUSA$4Lvr>dD=Yx9;7jKFmM=bippl-JwtQHOr!kioA(PFi$BO+
III3%cHy)#J3ADB7?ca05p0l*330yscbx7{Iov-hTQTqKZc%K5cFB#HSt5@;f%&kor7kdK%QNuY_R;sNXpv<G4BtW1J>3#<E^~VJ
HPq|6j8;9!WF_`SG`sf2yYNO|p2#%(g3qQxjnocb66uj!sS2;jgZPE1CJ3F%PI};z#=?61B|!gD3*`0nNqoC0!048M(kk|!dYuE_
=4F<JQwdpzP;@xS+XqASK6PC0xcq1qOsIcjLq}f*r8r@{@K(n!$6aj{!0*taS{n$uPa@C2X4E3fJgWRscH}k-XWu|1GTrm@{V{*&
?SYfBJnTq+1svK}`{_eT<e;`&!^hW?cxZpc6vvM%XhqHV5Jcf<8rbZuF1t!kRxc}5yX|{sY`p?~YxdCizygz<iUpho55I3-Nb+VM
25~|&l&Mt}m-ENfQp~KS#oz&L0X~11|Cl2zK6G4L`P^jPbO26<y+(12YNGwKLi{i4<9JIE)u5jAn-KZ1LSz1HA>)?xv_xSRi-99R
1*Ma%NN+hLJ3k+n)e$EY_l#K3OJDHqdUmc5Nc5hM93i*AA^8o=oO|^&HwxR#T|s&3M=!9H4}9$@r)lkVcuB#5esrE-!d~H5bEfci
iahcr$f+STj=D$(9M-1a`%1&#>2-Yf<zGEk$}4T1aF@3EIh-{<f&aKIDxrqrp-eyK(eG|N+5&X7N55V6PeGvkm*XJ#ufL)iZosy7
MpRGJ)*#ri42|<GPIye#zbZS|ZU+_5h9|4qY4zMtlqq#?vip&is&$#DH4`IHnXn$xbXf*B2zIbz8YuzXIl;$F(leu0!;?<OJ1qQd
{07RY{;_xle<wbAn-4mwy(%@Q6b%QnMvo0})dSpCBte##ZgR{s(_nLw&b5-Hs@V)<xwHZpXBAPIyR{YN@B8GDlK^4h=&eLjl?{T>
Drt8(a-$=wi+2UH7R28`HL9-$EMOoMq>$XjVrkqca9DXAEy1B4V_Yt=3}|8BKDb47QU8ChDj?gfXUQ&s8|+Zz)I34Lh4y~j!-t86
p~*~l^6w1ZGp;Kcg=g;>(n}LKXDdhJo4r}a+pbeij**{C^E;nLwNl=8$2-v6Y~x{{2YK0Sag><bpcZJYp_C6IMXz6K?-ufF+7>-w
vgM1cRF>2X<qn|KQV8Wn*vKu^MjG3kXZ^|<3OD2eg;VG_Npbba4yATW`n@jEDvOMc>}bdFzmpH{R9+V*&cK{x<`k+K@@^@~hPP>g
=5je$!^3|+R5{hFI8(urL@y;EaqpobTK|6ZeF2lg3X_hol$I6+K!O#O|J5N6*Yp&OqYszICGjZJcNz_ZhGdRLzb%EgP7_Lu!W>u2
z3dPmo2wK?AJ=1KmJWHATNR7e+qX)-usyeY8Vg#Mokr1(fFjaD<<*oX)}h9^Psyi#0_7ZNM9btzwW&5O7-FZHG!B`QM(C+OJRK(E
M`%q-v;(ltX5w$5LXPEn?KOT&wANBfqv>Qpy}UVX#*(<Qtfo{LWSQyCx0a@(Q2BJ-f_ND-Ep`lHevA6N->LRL9ux;)nhFGQb%LJ@
A4l+MvMn!9<w?<syyxmI+VU*1cqZKztUIzj;tlZ%_?I1~078-Iw0X%n&=`xEKp-OcLav)7G@mC9$2u(rWpe)8Jk+hpDPp~hv~g_~
EL{LYUxgQH?<Vq+$#+g&6r`1^M(5bLln4Np{--FQ5RObm^CL((=%D%%$o->glzvprsP#0%Hf}d(RBg=ph5hpHwomLRxq{x_&2U_a
9+go+k<vCs-ghqz3j>Z@>|Rps0Y@S2K5f0S@CRR`)Q?#S<y3AW{DJN%Qn0|Fp(flAB-=hmg`wx@sQRmxv<JP2HR}xMCFu@?U25hP
^M0;#$ah~!8yqX|>tow2$-8k&TR<NOK3X3Eu+z&>0_^YuEUngBn=HlHD_`jMNspIg4Zdhmx1$};nzwR%tNc&Q-2=%gT<B@`PYcFI
c{o1v#>#l{GU39vR+(%vfqWlvAll17Jq%<@32w!60`7l3eP_jgf+ynp9JMxq#ogfx5hcdG&=q?ljEuS&mSH0+Wm8c(4m1_&i%Acv
$XIz6<d-!Ue3Z@O`CLM-ZNM_<F70T&YyGLdZ$!nK2zJfQ7Y{S=!wN-u^(SBTCP@Jr5OD1j6Y~|1w23LN6`5CAgUn_*zytNKTHYRF
bFPM&nv|vd2GRXY*i_!@9eNlVcA{Pk6zrG_?rbr!X+m~XNLUKagDQzy>W2T}(px-Q%L1oPry*~X`o`K<l%YVbT0`gZDcAxjA7PFR
R|-0eHN59FwVZO8#o$p(g%SxA+|wT_&pEwDre+lV22}9s@}vnjPS$LxWW;jZ<CTG}z)8}Ad;+r8PwAdmP%#sdO2eZ4Jw+LBq~cA$
AYEgy6G_ptJLWiD1P(CUOP;Xk(#5^jX$|<ufZK}7tDdXvr6+<7*Rl$cyle$2;57<Aw)rlqg8;PYfmI`Y13rF9eV%bf_|dCP!42P-
)4K*S7XNrDvH!3r2E%4@Cl30pC(M|RvOsu$=G^ay*wn<7fQ`=6-M5&s;URbZgN6EWGFIqDXf93fYx{bNP4X`-kaSZw#$n1rJ)_mz
sZVIz%!4V3BhVmpexEXN!Ux%M`l5}+UOWI*k!$(FDSBq91=?j+0^-D3U)CKx#hiU|-~3cqXr>r5A`~k{^uI~QMS8+G&dc`F%<ODD
^^1n+9RyrzW`n!R#tNQX`4eUqrQ73|rDF_xj5P6ZUolVcH8R^GeeW|Fn%be@c5VXrI{7aEvu0XW_t@$(e&SWk&#$YM%`lf}GEoi(
4&D`u=tWdeTM**woRz;=W;~Y+OLDiit!P@3u=Ve*EBj0`7{sI?%HJM9f>k@5b;S<@RNHnH2m>g6-ILO_5K}Qe5r4I>VZV#!%T7<z
ejStwtq78Llc%{)+B*G^$bU8cP|Z5p@6$|`<8iW@3&^Cwf}ztoZ$Rn9caX~xp&Da+5gkx`cHrUt&bRr#ki16bc0M>N(j+ERnU?Rw
KJM(8FdO<lMZaKDt8YqIHbY{PoU>8)ijej(+!#;WkvJZE20>FIU=<k}a3OtcOU~XyDUzl|YL)CMJmiq@+#x+kNd%7v7C|v^|5D_f
GV(4akU%Ao=-=3yMk9-);%8Ky&L|5NC*^Pbonn;I(J)~!tMbt8>GXQ*^1QJ)hr}gIiUI4ptd`n$Ma8h(poYbx&stNREN#K`K6z?v
k5Tfyi`4iO8@mr-Y+7=69y(lyBBvIkT;j|OC4TyvWl}%>wHWc^aa|yF&o|Lc?OrL7FYC}q_pQ0k44ZY+tO+9<63CNyzd_$Z4ttay
+&}-Z{<nlAJ`2<&F6PFYdgwZa&%4!~4OG)3ljavubfr*ZclQV-kxO)cDUZ1wNMkO)i5KUP^$fA4k%c(5kFm;@c$JGU_x=3sv*EG>
{>W&UZ6KgOZnY9`e?<wB3MmO%mQe$x5Y*7X4RoHZ*bWL<nl?#G7pvht+jsY9_E;cGf!CT^vzAF1O;oQ<l7WlxoQs8WaU?7yQ0`07
ko^tJt5>|+k{E#WXEZ6kv@;p^FE8iX5Vom*XD}Ai<KOXy6W+HDipm*<^n-c$AP92_Gui<qJ^&A##0m)P=t(xo6zcr5Ae);@l1mbq
-QC}+EkguE>PGwUs|>P)9zpg8<*ls}##gGDcHYs5=OO8Ym<H>CcQf{+Cu0~>(0TI1lDOzVlp!}TxxK6I5}^|nvjgPVtFa%@v^tjq
jo&cAb$qeE4}H(gpd4D4k6LL}o<Br9H;h5>uwgQd-NHd=MRXQX0UUk*&?8(AenU%K47*E>+9j{BQ=pv)Ixlt5RK3!kRUv`+YD$v~
n`e=EY*nG=7x!jbSX(<VfZi@7qJZQD<P5)dRHzWg7~hnb;>?!HuenR>%%W)^Es}{hZb<lLS8emA+->a4)k^`M+gKqmDUjH)2K))u
N4gU{Je$?r6+&^6gbQy|i0Is}yVzw0;~u~<wz38NWSw6LETnQ<hhjD96{oxY#4SK+7(HBmOU!K@@i7Kb${Nd`dFIFsYp$moNI~t#
CG=H*B;Y$1Iw~A1Ud=v2lQE+#vGB^T17VQJL7-0{T@8O0Uu-@BLuz7}gznF^6~eGugfeDVYC@5@1d!GNarh!kkcs-V_ti9EQ23W8
TzZR}OK|uugUEJz#D3qBTT}gQS%$Ojnr30cW@4b{?Y6PkOtVM+FR9fom)#uvR;h_cyi+Tc6&?_6`A@YK!dpEM$cDq7>+>(~i_J|-
f64O{o&-8KRo_d$x{EJs$aEjccV}L%d@{F;86G|c>IIK%h|+A+!lZXqcuK~CC53PS7<bw|(@y|3BL4ODpF&+2-!T`eK<ZO0pRs?F
C3@z~*UgWxx)LScnYw+N^0Ok0sX_jb$f_d&$Yafqu*N|x<tm*`BT54QZrrX+oNP>CEk_8>Q5?yIU*_`P1ke;W37Rtb_~epilJ$>b
r3goVx~<)I<X9}+_~@ei+ckD@ri0p_@S5ZVtmiJ?|NO?zvCO>Z#@s{OY-`+ySG@*5#AsTh?svMT=s<KCvtc$ySD=0~#u(h2@lC>v
L=1#1^*$tEQz|sGsm_2c<PKEWT#WlJJI^i+xre!u!oU3~7J-BVHEo2<Sk5_A@NDJU^i3K>3~+)pm&F1u8!25Au4SZyx_Ch~rU*E^
0Jiez+cZx;8_?pnBA8AXh=Kxt{0-j7^#n1qQWGVqq)3Q8b&kB#L%-dyPk4mcZhlXYnmz4MT9Ipj8rpCXK*^W)uBR3A<4!qA_k?bj
-B+3f*d?IWdn}Zd5k}&@9smm$O-VN*&D~AxS-jbf&}#noeB5Nlnbm-qKDfv2Pc~uZSkD*(t%y$5lY}R$?L9)#OgZh{mvtx;39(B;
4xR^y7*_N(RLrmtts5;j5^b)hxpcP?&Z@t7EeETKao(OxIQV@De%Sksj!X{1E&Y2gYr5}#bJPvwkT2*QE-CD;Uhqwnd!2`faBuYn
UVPdDya<UY7MU{8zVVb#5HDB|JwsuLO-jsdr~RDk+8`rA{n3XML-wG3C-#m!vxBUF>;3PpLsF^_9!(6I7Zu(KRRf<jgXH%7+Z}av
x3DC(8wZ)fx8kRo+z@O+HXnXEo`AA^e1Ye3NVwuzCK?dCC8q~0dAzMWdOGxe_INDG$|<afS8WDp1dGht%B&uw=i><^9&94~*lpQV
I-Wq!wdcEna`cUQ6SBv3U6z2s)mlGmO8hR|x4317yi2rAJ2a6nHg(2C6U1f_M*_}Jbk-vzf;9FgR0oAddTiR6ztp5~o&>Jw;7fKk
EAc-chIyT>$wH!)*XhCIqg8ln)t!0|_6V1ylFfsuoArhe<`q{L;bn|^`ni3IPZx4#-j<#iRO_;J%D_xvmqYBbvE2-Alkb*}|9f1o
xZ1epP&(T~?GR{u=X-&ezuZ}*umbUezAG5|_Z+_>%*TJx`6GmOC^R4Q$!Q$1d}wjJwM9sXy+M*sMFjIE-@^JdaJRNbfT-)E-}h4d
H75r-sC33Asl7Qn*%3WXGp$jGaJi@sRt7KcR@bvuM{1K8K0;dz1vmd1Tf|HtfAsNLc$LjQEdy`_%q1p-DR;%>T*IHpRErlTlfvT>
BMTgcib`azMNL_J_lctb@%k%i#jyJtDvC1Od>+V^`gBX-Mzgw)E_LZMT;9Kz%OQd%I=$|q17WObUYTCtmL8M^Bj!H}ADh;aq6FF^
V<4<TO)cc$qB!yZ1LLT;E>NUzlW^_E5ESknHF~!ueb4hFudPfb$J)uuICPIE7c<SGu3=#wW%vIU=8bh>>%YnFC^XPL>`|i6D+LZc
BNM^lC&U9g!w=A(#r#vbg5Pmc*LAvVI6slqW$J-PYF`33N2l9j-b~wLx8k;?jWRZdoZ^bIL}@LkFJ6d;&JmRyZv1+hYdg{)KrFUj
z%7`;z<lW<oGRb|s{$!o4^y{Lsa;h&16}O?#PIy!`WeI8;4EC$d$|23w*GK^kc6Nt!$~PAH*RBr25v_zHx}Gu+Hn%dyh2iZmdxgB
Ui9kzwNUrM|IRR!lS&&t@nZPF7<vF<uJ4W`$F9B7x8n?9pr3e+!TWJw2jxzl?sgK?%>+4zC5#3v2hTH9JPc06->m<RtQz;OFR-x&
K|FF=di2en*rQkDNlAYa5+*3S90ad%(zwAA$s+BW&KK0S3#hkYuw-6=4){ef?8ebjZ9W=r!AX_7@HsLpziE=;I|(ddVmGist0oJf
a5g0NjQYxZ+0kKwjwhLkLV%E5YZS@(cSO<dbNtcLax@!~&VhSU;erH+(y3>Q`T`QgOnCrCb&FwCpMuvJeKh-~nOg7U!YV`=b8ZyK
$f36T&bt%AZ1|{%?Ui+)+W2g<&v_?Q-d>U*S+4AAxZ2fLtJoQvyO61ivwQbyVTi#w^)%VC`j&12R1a>%s8w{WW~UMGc*#^vE_PKp
d&2s@8o?yjKW(7vYWq=t7Wto;5^5{$0hZDNbhUILz)kJ6#$kIP{f#X0C?i?Qklvs$%t#Oa{M6Cn6VyAwCE$}m3xBv2Ozcrka*S=_
+|feMR}|YO7L^-w{IWbka5&cgnTk-=pbGwvoecENYIy<IWS5v$f8U_dH8=Y2e!e*qB}4N}sam|^fJyuv6<<5NMo6rKv5nFC7{<mX
djU&t6FRbQsNs7nkvvYs>km)t>~;~ZpV7;&l-vi#WIhQI@jWT_;7lJ|_o{^ylq>1KFRS|eDsWc#yAWU6&1ND-RigT2{&}`HSXEFf
kr@d$;o=FdHJ(5YKz|@xt=eNEw5+YDaNLYP^01soU9gWXIOPut-`2FPJ|keC3kD0OJJ>osDjRE~yNoX<6+QI~WgR+D$-2PdxfuD9
@+#voz5=h_vQy<Wy5fvxNy4171oG8Q`5^S|OCbeR(R*ea4Y_n|>oiTlibya>lRQmN?@NU^O(oA9+czh9KC?1`6P_e#^PF7xc}TpE
76S4fRs8>K172c?=ZZ_W{HsN%5iUKyxCG6JzwtbOG7Qi*&Y}!}EUs(W7`-}q_XGH?AlMUUn(x1UlrCb9#omPCh6B(zD`JF?PrlpP
jocV%Ayj!ZFPkdPh}+F%7qg|gT@Oz_eYO(Y=RP6vK8)RJ5*bD}YST)H8#?*T=Z|@GcY0>?{NwWKTUc$ZfQzt^qnp#nfvi6gln)sH
GMNtv7(~dBKB#S@i`{tnBo1%>4}KDHT=Z`84`6S^Kn_d_CmcO5_gUd$Kh49-meVW3f6kkxH|Hff-hj%q0B=tf%fR*Vp-_i+s&`HU
xW}z%YZNUx1E{2ci5@cnLP`q5KJtZ|%E1b`GQ=fX-6@pk^A*9rQe?#FQV>EFS#@@W<5>hWkAuLd))Qlve|TMndp;9})g}$SWH-V7
j_Zp*$4KoW?Dm7tipUdX+xk3|&wke|ujD300fZx^2Uh;$;);caJWr6pIPIYH`9>+%lyvcZKV+%FVC<)>s<jH89m6loR~mW(NC@gD
Izo;qkI*j+>=UCE#V+5~PJ@o>Z96#L@_3Z8Re4ep;6a9RzrMIQ?jODgHn+vwtFI&)#C)1s6S?PxEsyQjFJY2LSMRLe9iUj|xE2SU
?A4IEzLg<jV!N7^clrB=HY$TGh~D;Jr|(I9P6!8Z9!G+tfGzN|c%O0Z#V!5ixQVfXpO~Os#gK&x#72*7ZgO@bw8e1bhm2de)NN$x
ouD!3t{iOTSxf!!Xrm)W9pG9VGk7oyUr5k}ztxMvp_lf|=e!N^6}LRFP$d`5S;n@X`i`=-V+$F`0iT(xk)?)W%Y)Ky%b*r>CDXj@
`C`e+%3F2$W~^%O4okq+KqC7;ns^zQ104$yFK{L*(k5&uPQ_=#0LLmnSKYRb00&rj$cuWeSw+dNu8{V?)FF;KqAqYenOX2Rg{jcH
YX=V7FJ>zw+z(UbUN(HU!zK3cxFm(Wj;^jAs#dAd9$aQt0(%sKEY?d2M^|3qdg9UZcv8%^kuHvSa&Soc_LGJO8qL?GU2QH*8lF7q
07eiLZbi|b!vzAjL{MMC3i9KhMVGRCxt7{<JSH%%*>!FoDPqtuMJjoE(2zqqT^ZWRQp1sCFNcc`u<RC5cy2Oqd+xa@4Y7B>Nm%7r
o4|3K{t-o|8lgB`HTUq0kTIOZAI9cI;`d+_zS1h}7-|M~GkbQpX7;2l<LpV$-@$AOmsozcdmtndEyJ4&3d-^6?`>uSsk@~5d#!Hs
g3L~e!&!P=?C(P;mlf!Xi{zeb|A!9&aV0&lB*pIyZ@B%4#8Ay#{=O0p=xZpg>79hJ4HQ#sQu!NH<#lf4Ov4>GrJ)I^y64*Im%~mm
e)ds9rE|PbNf3Rss~<xzr!B2WIfq=|dD{;R#-@Ec^D;La-G}6<sR51}hRKWBXHM3=S1%ZszwFlRv)(&Xkl{5uyxFLByTJjkUlK>(
1XQh`O3Wm9D-R2=n#%ZxgtdWGO}Q2zPIa7L+X#5*PYrm_N1>>Wcd_pkW@S2!RwwEb)BYvT7$BPdJPTuc&w8?KTze5j<9(zSKZfBc
sO=dlL#4k}aM`>9R&1DUOFU<0aOmU;W|sODTQZR&3(#ufSXrzV5(sCPOysG~cjo^oNx=m&7t^9;(8kcr?7rJEI94OwtS__aU)*T=
FcIS4W7xs>=4c~ipJ7{9#fZHze3zu&;-=Bgx7x%!+pEu?`njMx26a^5Lo=^jNK63h4hS|#nowSKA-o$_AQfZd<oeAZQO)`X**gVO
0LWkh;!{)&BV3k06Uzscc%RYo78Gl(`O0{O&Kg9Qv*&Y8Bw{0IizioeJuIpHk#;wbXawj*g&0;cN1qoiqMK%rpS#klZLxgDI1fy!
EDz=!-Cp?(L_l3mAuy92c`pqJ8^1P?TzEWHbJ=RH#9sD*NnTVZHrz;V1VBLpzW?BmT;mmttDqmsyB>*F2FLRY>OoC&z|E`(m7_03
SqwtKpkjtrO5_L8a$1|2a|ooXaQ_A`{q=(sN|)h(xoH_kg*_G+rGixJ-$02*E?&JxL?=+1n&XAFoP^|ZNL@JhF{y&Ft%L{ecU-K6
O`1A0)!T7!T?x9WPsgRNur)l6vEz);WKSIfPS_*}(?*7($rKB)&C8U{wffucBMu`}QhAosiZjW!&1fEfE)1?Dq}Tftu-d$;W5hoA
BAeI{YomwEGAMs1Y=fh9?63MgA#K$+f9X8P)A1URCg1X7`N(7FsZGj=G9f0_s{J|2IpW;ma2mcqSIYyf1A=#<zQ4Qe{0{tYUXS!|
jUY`XF`-HmmdpT#_E&(t>nU^<9P7)KV#ZGeNTuAr(#npI?6#c?iKG=5TF@nWgya2TeJ9X+r047a;)fUU3tB=0zqW0&v>YgYN1}?J
pz{<y&>i1Jc@-mX|Bp`cgBWUJfWYNR<<ULLjfkM9)7}zFaV?<V20vxc@g(6_6&$~J6&F?7w|8b$&p9=7`yB57TWH%g!oanlJxM7t
dPhCuaj)zkXBBNgmLMY%esObDoj2CBmzJAkO@o-DS?cYmP9v*X=-wFkj$6pS*?0z=RS|e*5EX6+*(+hE&QnC>;?A24E`im(fHM}L
hxtE51;*t<L4}f`KoLQ!xcClOD2<}y<_L9#3!ioa<a{PSLau_)56Ri9_yqL@i#2L^i`YznfC!IdHx7PekBqEFq2?co5(3K`(YsbN
UgNb=C1bzaJU_-->H}<GlhYDz==n<Yh`y~B2E61XQyJr44^v2}v&zLEKMKkhjjs?$#<rrp;`vp_z<T5Ux-_(ikny|5GLM>(2}K%+
^H-h12f**W?nbg3Rnl>KSh;M>_P;-C-zsK&dIv~IDA5cF%D!Oa`@*s1HIxR;Na^=6It(oiflL6*G^6arwAT)S!CtzASV#?b!nc*G
kLPX;Yx|sw>&peMC`#mtheI81(l=||oY)h{0RBIz>wPO>4J-5xo00XJr9MSjuxGb-jkR1?Z_Z9F%1M*RFFiVlj)l-|7$*sQ&fD`f
*#aP}X5B%kEQyKY;r#4f`X-lE>$xFUPi;#kml%BH39wY2_9vqecl&IzT|agESX<YG8COZ`pmYx$A>dr$j205>MJ!gvAP1EAj1(PO
UKG$)JrAW$jZwcaO_2-csF(;tI2~Pq50Kx~5a!9pJJw*H4#2`ZG#1jDoqZlt0W5Ph5}G0iR^4foF*&x5Z<^?8jr9o}S3LWCdoc^l
5xfeI5DD9#KtbhTxTr|AtgcrN`xYu##|qpq+kq4kv4sHn4`4tVkpf$+81H;^Ks{+PK`cLb^UL9^HdQ|=4=4^Xe0b;3fXeT;Ers6?
{$MI&6EUfdX<^EZ6LJT<jTLkaK64!>EzX?<oh-uXx;{{8y`2_SVqL?366&equqHz3UxDuO#Jes#y_sf6avd>W8+CFsP%8xfn1jsK
3EKXber-pa;}c3;#j~$`7_rQQHPfJ9rL4>_nJ^htD)|Hlu}jN3u3-E1v_xYs<?@7lBZ!MhK=<r{g)+^~<aP1s6g4|(Nas#uswTL<
xzEn1Gst1sg!=;~ZsWAjG;fVp0kX_!C3Xr1|Cd-Ov4sd3YaC|aQ0PxVenr4@ZlcX(m)FigL??ve{*sX(mYUpA%L-Q^r<LM*_TZz|
YmsiQD67fnge)=3FP5E3llKDOy0kVW&7PC++v-U_OTG`jewY8*{9=$Y(^?M<D#5n0#GRC9C!Bw151<dQZ-pAMB)a{yg6DkO3(#^G
fgWjEr7Km2ybQk*Q@*M_(^sCXOSg5f1y62uzusE^;s=|l>-6x%mq$V=<~9*T6y{v+f3dkjAaVYY<D^=yHeTGp3=ZVZHiF`dO<I?g
rS8hmb;xaQv`7bxO{{TFV7E(5LWXnn#Q8u`0MhVDyAA4}#~iP6gNOf-@tAZi!Lw3IWC!(OQQL3wi){B+M1%)I!LEB;n@oy;Eax(n
+z$%1hZ7a}Wm=%OXFrv#T3T;H_jaVEdPWEA^~EpTNF=XYs*!q?X4;%MX#`>*Jeh*uX6Y*xES+I^bSDV&59BAG$tvS$DJM23rf*1j
EQTvm`Fjwcu~&*{q$N>$U4-BHsE9^&wuTWpv>AXK$G}0Aiv#l(4j>v*Gh9w}E2vKaw;fQZTm8>9^@a1=^&g;$ix%6IUw9@v)T_RS
TjLEJ0k71<d~-mf&YBXJ;p~fLkZB`ibG6t`XE%WTgdu($WA;tL!AvV~<Srt#DaaL_%6Q-3FV~ofNn;NC+2O~$qa0N@`5U(D47~Eh
#b8_(Wy9Xt^WtPxfo<V0Np79+qTe1=o!^t(8Y+oyJGmn$;T3UO9w@uKHM1z4kJWQnxruMea?SQNxUg>5*bMYdQNYc>UWZ4P6ONRB
bQB*bqllw=%QHvBcGLe!Yh9fD)<#>g6ui2dt_2kJLsa;!Qb{w*B2rbWUVXo+F^d<Ypae(eUBSW3MP{UKU#Gx)sYjg`2&Vt)<JNMg
IUqxvjp0=iq~V16VJ2BD>PfMb<e0<*<OK&pQ;|v4S@b97*FUyX%jJy53F->?e#i{_osA3S|G9Okb*-uLT3QyFuZ1NQoIsl67kWa!
cj^c>SKlxLQ6h#yQ(@Wr0aBkHR5{tBur5KGXpHdOY^k(m&I;=@(K!fBYP`uWW3(3Fpl;P3EvY41$aqt&8(~atvr!M<XBd;!-M<lu
*DIY44AZLjT)=C*er3?{0~WU_zAT2a85v+rTRz1h#EgW=raiTUs8*Mjt5@+o&2|gho()UQ{9as-S@4=Qr(>(CDPrikdLi-MFn+qk
KUMo&1U#5vO9+GgNQYPxci456WgTy?eIAAllOauVA#~wta;5KD039Jlc=JpreGOtv;Rqfd;~5@gg5%2q>|SK_rF}z(v0Ua!Xe>~$
=@W#jUO79Sm!=Lt6uy_LynDJ-;6W4;?=*P94XH59owwp`YdvTalJ$D^;cJV+g`01LjD9GMBc6PJ{*uzP*)0h{kCRVJLNsXTg_9#X
WJyzNY%u0xnFCCM1P5-_WI6i#Ru&fGXU`yq8|jte8(FhqxzS}3(#wU`20!044L_=s8$gfR_8dko0?(C2A$6d5oYFM26jh(1VvTvG
PkJYf(}yXo`mE}m{|Qn?nhTxW88<z7rw$?72IE6`Kj%^1b7MP?k6Rcy8XFAwoKC=`Hd1A`Ft6xk)0tC&S~4?v-O9#P@9X68<<3$`
&3s(T41H8}6!3geExKm-4i(B3?G`pk62rMVQECQs?yJLHS|ZbY98xbNe#-oIV(=m|2fbAGiAe1=36JAw)oUV^YS%p{)@m7flhSP^
^ewz$PM2D_!sy8=S{wzKVQB_#@kw2i$`$-f5^(G3&E|8dCHWrlY2qSfQv>VB;YWHBN4V9V^aS9G<&x!29(l0S-8yWd1jD<wa}o&;
uFv_v>WS7I9>rBR*mi_2+Wcmi>yax9Of?QTH0XG=T4IGzJ6I5OV{><&OEH-NG&IqoSr-B&js)Uppi_UMH00%@r~KgNaju_scD`O4
KM0N~xOD(izcQF9<6YE3yTUZ(sDF4|F+{1l*{A0WBK4r0)<jSoNZzVBa&xrTpF6*A9trda)v`{2@!egy!BRPs$Y80WrFUkg`^dtM
wf6_)00WYg^^)~By01<0`-jN=7^*)(#xC*_4MXz|&UbNCIpXSrGl8rFgc>g(8>eO1qwTeFC>|4u1n}0J)jBsnj!MvqH3f)5G#`3N
A>HKtaICnmE<K@Vw%ZO0J#71$BEkSOMT~?ITu=1S@fhTL0qaFS{WTbmAg=SVi}`bRtj{Ba-xn%bkLijO=Nvc0(ADoWqzwSl2wUn!
+n8`o8TpP#J_kBTczvETN7wuIRzhelaPFg+k$}lpJGgIz{ajD~0tXxglH#rq9T3FmNKDAm117litMblkvm*CaLTi)`IQptU;o{u1
2$L~v+GXNlFBj2i2!OAl?~W>1A=e}M`r<yWO-p*z2uTtqt7_kLo_?tf%{N_YQo#pj@hzo=Bf6Wy@FBxH@@!B@%JyDY{?_xE7Sqfq
Abn)m2HsZ4^&!WYv7gHoof(9E-iC^5&lN}|N~K%4dFOx0C5)oLtVcrDhkvczUCj^^s3pJtr|7(h@m2qFbDjS{nnjM{7Afz6f)vmU
jxSmg7_#>%!?hX?B@Y|2!O=S#O79%fv@Cuda9{G79Znwo5$uPG-*zy{v5xHDQokeLs#6LIHX%bH6%gYU`nx-(;IgOJsTf|TYV{0b
4M|d`4Q;%(alq-<prQyoiGtSlGSH4~`1Q(y$z#1{r|!-Zodtn@v+L=$j0u{pQ+>f(L+JZWF6!~B=2;O4<dHo)46v)PE-{vi^lmQ5
X;kAIOg_wCpoBz>pXH*{<LN0nvhEj?wI!v6ifnt9WHL_8af%Fg1`me>(p9Jh2R?ts1#>@fFT0~seY%=zAmJp=sy>EsRj%cq@Z?NR
4kz7V6)MK03_I_IYE^Zqn5A~b@;Q}%y~?OAe)rf@#<aw-oqK0dhPOj}c@21>y*{UA+hsLTbN`6xXCf1EDF)q-9{|$Lr;p`<wPg#y
Nw4D^jc~_NTaWi;od%@mw$lC@J=mm`DS_x5;<n_HVK<zDUWKmvcHiBbeduxg+vqI$m4~0xC(gU@G1Q6yg%GqVuY`-$DBEG@=X~d&
<?K@o*A8j>Uo8V)^vIgf^3H<Kcs-!M3O0}?R5{MKo3dRvt*Ul0vc--W9Va7hcRk;XNw%-oPm!s7`3RRKN>*Z7Y*APp@&GK?3m>97
*3F#M`eCc_q-PKrm+WO}9sg%UB%Vhw^V|nQBFv+=47Xa&Zr%du0eRB!Ch|s3AoR;F#I3RLX1X%ogRsq-IsveUtvBE_i#SMVhp7vu
jmGl%<0R2CiWK}w<Azd{iMq+O_5XdM@cC>gNeRZ0J?r7+iC@Zv!~N<WPR-nDrX~6#Cq<GL!r-?bH`i>4qmO^^<{Rqa$z&;+7a~ye
Bab<zIKkBVoPHb_>(8{TC*hvs3!atX`QI6rM>{@JD0@=kvn=FbuIAPOUo$pp=UDHPp^bklyLrerud>{&t9p&!1cdII99HvkwCqKu
_gwUujRoz;8x$^tmCFhia{U6f+~B=66(H98XdeVJt7b3;*V?fHgCD9PA111Rdl1;SO5L0CUT)*UCPrfXUIaNL&5BN^&zWAbLW5YU
@}3X{_95`@+DR$uFP^7m#=ZybH@7u*7`nwpa$*ZHj+<0`4x~BM{LY;dlHG9H=<!`%05{$y!T>%3;mzT4NsS<}=zoNcNwc^-=xFOX
7t%b2*yR;7w{Tp7$LUcy$%@cMNg{_7VuR6Q*~Ak|2@s<Q>?QRtmJuObV|z}RiJiEvFjssDO_c}zh*OlTvPJ-P#E>HuB7;SOynUtm
s^zsm&!WsN=&e$*Y&QYiLsfc7BICVWbbzo4@nDc<fh8m<AvqcaPvURkuz$I@1pPY{)$bZ`G=U-MCm@MT%OR`aa!if3P;i&cq&AGM
C*^4((e<vYjQ#Ky)dGYjOg^pOfmu*tC34{f`MX{3&NCkAKQmCNU&WpPJRbx(P#L7G&g|k|zILu;+J>j41w9+TXB~YpSDap(cvePy
2WxyG`w6cp4`pPgEjj22T9AB5XAf?WEy}*@7ga&$YdxLz9zE12U5{lUjRmG_<?08!>^s^<N;t3pDu;>0da%5(UeK4v{EfT*Q|8(_
&+XiemYJ43C)QDcjBUS;jAvt8e+9ld7|pmUu*ne>&>!3HL34PA<WaH7L)u_(nF1uz)DPGssY|U%jY5G2>s+0KO>F4*UlmMEVGlRE
II7kz147OL;U^jX5}0C>XmK*pbtY3}TC*#PU88sRYf?&ZkfAwuaY9};x|%0eg*dfVNV8Z>MGqAd%Gv9DbR^s=zKkWCA3e!ZKnfs(
K06`Th(l9~A|=4H`*SGcKRpZ5Fu3%mCLl);dL{%qw#36hB&}*3DqG8!c^o;#FOv%x`gh!M>UB7sR-Cj~d}(6;!8+K04ZhunzAqlV
V$-M^s2-W{bEz2vV%&7zOC!s;*U+e;I0sO-bS@Bc?tV?l)cq^-Lbeay7EFs&Gr^dUZaEDU>b}nhIIBYr-w|n2jQ3Z*#Ntp;Gg@+l
eh#q$!N3ipoz-78P|@x3|Jfll;E04o--tNH{!<HK8~?VC9lc@)wZnNrdqBU)-Q5Z8S8^(>uyt(tuKfHT(jmR3Tn&N5d31&``gN=t
;*QF(H2*-QQ*NN-Gejh8Ky~wYNE$D2^3sW<K9m(r|HRH47Q1(aAfI{2h*UDWekW!CE1~uoNaPUhq->ZDSSq>Q*S(k;m6K<N;-F^_
ZqsuLS3${e7p*p?&T8AvIS9=7?eA<f>}&v)B~wmGYEadBQk8o>BC3HyFLfs)U*irelu!T#C!5;j_x0&0EH}8B3W2N3mBoJNq5Y9l
!JA7QAiPsFKhSoEARs-4DnQENSU-u$+m7Uf@<j&e+ehM7RoJ5n{<W8sU?gj?!esyFtSQeLoAg2t;>o~ko&-Ek#i`gdHDBWJ)HZr?
e|E8q9lYdyzSxo7E}~+FLKE3tMn+~rI-|tiYx<2uiq;N0sCGC-u5<IbF6S2e1u-<kO;i___mLdXj6phqFOYJG?o}b)PvB$xV5U23
-x5rp+t7XDIe%z!8H|C*h<IcvS7BGq&CQW^`QtDPhChc=lY7E&cT5C4{gK2hpFFA3#T~GJ$ncOf-Yo+LV#Z+{WVR^Te(XL$@XQqY
8K4wTG6UA}31=Xc)rAhfqy{qSq-8k<To5snErPklk_3ZVM&p8@;(Z4Z8>llH%j0|l8?=^tN}f(%#+2}(SR_J8D{r`nJ5d$5^}DW3
^F7hhhi~?rEh6p{=}T6eEjOy~uBPS(*b&vUnqj9{Jl%BesONVoAFVL<_#KO>I9cKdto?920ZAm}5O|h`O`gi{Dw0ALyO4b?5|>et
g``kz_t!{AdMrag=eX87nqLIiUFxoa1%5Bks3@nUwu_y%HOz#@pbHj5P0h%+p-0fI^47X=sOgYnOv<l{eRU3)y(_q-5q;M)7~ysh
TlGrgcA0$Es=z*Baf-jC4H(lEo(oS`-EOco)4E9rj4n6GCdpd*M*Y1(70>%8Hm7Re1u-x(?rO<J35E*M9!nwKvhhvw%VTGWU|+Iv
Hc-7^^>Y$LGcDG2EF&}3IFy8?`cl1Fcn_A)qT#P66M#7}&(9n)=&q9)DysWe)Jly`N*ZL;5iPdpcOgwEiQ$Afahq=T5F`QNS5{5k
i6MP}L)_?>mW(5;nKJ&yv`{^oD6YVJcgGx4)-KCqH~$4QmWuc7{EKW$PF2$c6Ijm=kOPFo<S+t6j>hwUHyiPqzsB_f>EE1QIRTVf
MK5Iw_#JO~T)%;q7sv?}f-f?){uJi%j?H0-GFJq#`pTrZo);Tj%LTAzzy#=41A)Vk;iEGRbCs1Sa^Ra)ax`Bygd-NL=fXtWC!;+t
YUlq^dRwz?N>n!$*a@kbq(+s1EpZx>F6>NZm6GzKvZ|%%>tS8kGclF`W2lH7Gt(Ie*pXNB%Pcq*?dg<5iDXU+iyHhAeQ|=L`Sbig
cTsgW?N}3_hk~5J>xVDUEo*U)<l!gW&{lur0csum$o&jvN|-wbE4`!7WWZ8_D+8U#Xy243TG4HnB=E;me9&nj9bGnl`?`C1`1xR|
Z7RTFAc_|x7#?Be;Cw)AF&L)x>nM+D=H{E9oK345RbO1rwdNf}K};#3LQ<%$B%ifOTdMq?@)yBd;678MoNvPIf*H_X{iZg-lydm7
qjrd5)t&7%`j~sb)9G$c+d>lkwk5T6is)D0D?tgvi*3!BtW%lhog%hncGGuDw6m9J!soa%l$u^}_J--9CQjJ`mu5LNDN@&-iULkd
$N)}`r&5@W87fzVc~siFzaHc4AXRxbYWX%OPC%_n3dUzW6PQ$ZM93-Ig$maDWkZy!=-jFN$^Scw9}9D`kHuXYoTN1h07WV<Q$G?J
6e;RTbU`PlnKbxcfNL?cl7ElQxQBiW4A_x3BJ1{W5Z>fG$$y5whNJFOgEZH^gKw9)&JpHY8>@I!$(SnzbS#jpr_%#CC`*G7*Y}3!
0g4H!31~A-)mrPtww1u)ou;CP!k*`z#p>Oaj%#-Pi}I}U8#{zXlF#5L-rfN8Qg#pA@xy8q8u-+IiFob=cZs*TdKp<LY*$v?EhArg
cB?|5=<Y!W5eg_h9jqS$p3T2n`6wna<OXsO8km!5c#lFT_e~17N(3RDvX178V5vPRa2!{_DqAclE6VC<m}C#fJ6tt?Q~Q!0AhtcX
H}9Lr*0w~SDj;`E-{srCLA^}A*#|wQzY_A((PklPgS&WTD;OOy)6yY;j&)9tiwh^&v}ql47YT+!9onj%urWPA9gob<eqFY#In7bZ
p$hl1p>*Qc2w^ZA;=@$;w|{%&9BILWSALK%k{}o><AQbrRb{Y!?rEKtOFy5;vToTgs+!7Eb-_?ZULylvEOy(|aZ;b0e_YIJ+!eYx
@`-E6U^3iaO4q}t;C)C-OJown;9;WODarGmVfQ>13{(Yb9$3w3h6-ei?j-SDnIvl5HmG3pgQx0FF$ct`o&tbPyNS>AW8eB=qHt@n
AXU8eNvsMD;Ihh#3QEVpA6W}-|NL{qjtVtuR|YE(d82EToO8q+Wt31LF%SBJ2Fig|!xp(ZccKo*(op15gH4%ctG>zr;$w$Jn-_m1
$77fp%BHpGW#_ZXa&i~mhf|4Is9~w+)Bd8ng<{KOfiZ|m*7Htduu;i-t=+9JZ&npUA`M|`MGquI;&+shz$04pIRaGv<iW(MMuQ|J
fwz`2iPVB1E9U&2!3W7LnS~QwSeWxp*T0#GOx3P77HeWCsRL3LAo{A{L8VRt;cL!IqNg}Z@|st{9y_gQlx1mBcIz~mPsp>CJm5V%
szc#mK^P#Oo(6?QF~P+`bv`S9-+;3^#L1aySUv4pQ6EAZI2D5CAH?Oh2&0faMM`c5G)W>9i^1$)cY~j`cxJ*I)>raikfRu$R*|-T
NMhBi)(Mt3XD}Dxya_BLJOp)SUH^<n_DR|KYxEF<%Q3Vw%G)So){{|vtYGs98pgo#%WE~Ra)+Q5N?9O#e6-KO?EpcvDlwoJQsAKA
C?C(~Az++D8TF@2N>P{oQIm8|Jux3k+zD*nh@UNIjBjzxk`EY7cpbW~5QRQ3lJ|uToG$l2!$cVGNe!A~^S3~?UI8f~*i|H@lhdJH
umh*zl$h)~P<Y*yqV$rL6$c}ocooGTXF<zEJsURY`$n{;xF%m=XIxA%b{b?VPY+sXy#l^MG7(6ErU0Lj$dvr_tFVjr?W7<kO%=bT
`xh3xHQX#;?IzWtbS#4QnOVo!)IILCrS2!eWMGuFHKr6Wicwe*g;KQ!J_LRR*`=s8VO+$QFk)L}H}4ry-`~TPQ8$;TPb+>jzbvx>
QMb8I<^1gnoBmqK!eC4w|M@$zqjnqGwKC}m@Z_c756G5QjgWWqGIMFECP^jFxcczuabQO~Qxy>5a&;0;d_CLb_qJay`|Uy)g^K+n
I?hZ$N$B0J8T8&zJCXP!4YRIbvbht*EW}Yv8+^v>sjoqccsTnjB-InL#CYDc>#7745o}0uNnI;bd-tdriWdZH={QvZ23xleoOC=`
^Sq9OTYTqfY%O@cgWKQwLbXk<BKM_nd+EyxZDs4#fbz{ZiS<CeAwNrNEH&H5?b&SlV>l?k+L{AcWG?}ejykxZ4z>pgVF=@bGecWB
MgUsTVhgLl2luL}YUA<Ut0@<qdO6DBu7Trf1ATLQaj-_uNVRDk;4oK`BO2zZuT99};>EUpBQgk*dGGQN-`BR9Y>(|jz26d(g3DUb
C5}BEED0Dp1^tV-)4@=fi5WlmHGfL>%VgPdre=vk@Yx((c%oM#w@skt)+S%;rh!GmX>AVw#{|fo6?$e66=O0fHW?(Wh7IUlK%;a*
ayhM%L7>h)xoIG+?SoaIsxT6Ym=+P1W^3wVVFF@FjDg{4qMa0#cinzF7f0m)g%BQb+|~ZW@8!ivpCLy5*&!!CYWTsB+s}@_*zXg-
zO>C2B3ZdM`yAnW<yetpUH-aiAQ^s#S+LYpN`t1Yv+{e!BaIl(Ud}lZjV=bJ3C$b9ylHD+D_bC64W)G;X~<=cTe2jPGjCGzS%nWU
HD?mBb7m<`I{6LtF-pDv2?Y7QRkU4m^wW)IHoMNajg7Hu#r;y|M+pfyBY1knKBFRw<fc=~khl%RHS+Cy0oJq^3gX&kpQV@cq0WOT
`mN_7#%OpnxJ#6>8${^mf3%$gG)IkNtQFMtXB{tdTEd#lnzjEBOHz(2b)VgVqu8W|$Y(P@AmttQ4qIL=mK@R)Y|p>g+mSKUL}|6H
$Q=VT(HE~zL6hZ&ikS-dmXN594<Y<tW7=jYR|lagXuUfV<=Zn8TCW*c8tj--jRvuBh<S#x5WjS)8Jt%*(uu;fNYAX)bvo$WI+ej`
fll%F5QYyeG@JsFRCzX0Y`lK!JR{<_u>^_%$2(|^n$om%ym)_$rl<XQaMc8Eq5qO$HD@tV%}5WJn!OM|;W}K^kxVf_YHUY+T0W5e
1egS@9Xi1zRLUrI(JQ3to=ET25z>ELOgfF`<G@C>W=N0Y82o!^%C)hs_veBvw>J`)Xz-?y=5GsQg$>MG&%SoSG;$Tt+o_nXX!65*
JrxQH_|KUjHTBaVKUZ7fI7_Y`1NH`RzraiaBg68FtsZIe>AgUEO*UTQk_n+z31pwi3Aa{`Q<3g<<If^c{val18>gF@henLyWv!mz
PIvz@W}Y`G#ra|EOf{$1!3QSE@aT0A-y#!#;d|~|W2@|XKMTY97xm_}T{;9F%iQHAq&hc__GbUkb~YM|uQn6qZHRx|%M20OajSPm
f;Kl}WNdVx-Hx=sLdWScZnFJWwFr<okX4Uq*5>A`CV|OCB#CMBX<haT_y7wc7nkph+n6k1-=MxQgo6Ml;j8##Az7tp2GKdo8bUAj
-Wqx006=fR1vfDJxuF(jt1rw3d*%Z)@Z6yM>RO4<)lbf|McJ|P*$h1)0zI)bxnfD$bj1N8%{uZ}#C-~-0qW6@ppDFlNbi)Q`fwWb
b^>id5H%%`Rcq=}EhFF?+L(z`?!t4j8L1_8@FpSr6(Yx&e$ofvt09QB67sg};)R|S0TXI;%rcp{0B|P?ZTI=v%KZN|9Js|m*0ISj
U&1HB7RBQdForxd*yCAs4ZR3ED`n-CMoemMdU$GZ;#YU`hk9iOJHfzV8HY};9)rz$?Bl@7(^!Fs3dVU{M%M<cg*p*V*J(oWE+Tja
0E85KN*+fJqHIPC@$5(!1<ur{+YkJjJD~B_!=&Ey$-+CAk6x?Nkq(DEnbSQ)Gu!5M*rMJCm{t0MZ{e8h=p<?EMzBw};D+{f)GkyM
Lk#bYTc=EydA>jRrASukD;|;JHSMJH8c*b7`+%G_goR#gn`_x`b5;~3WR&Av(_P(X??m1bY|whl`2Xx5%RKCOtSeSq)ws@*^oKc`
S3PjA2(sJZ#RJg+r+Fr&+?DOeU1ON%^aG38k4$6~6?Ti2cig~Of+IYPA87on=mjhc_cNKI97q&{QsMcv<)^x<VpQoLVEk{Gr@3$M
&(yA2(8>t8aHvyqMZKhYg~aov03UIb*M0FX^Gf(gTNp;e8RUR;?~5~V`U?385%)fxOn8egk%ksAZkE8eWCz`&>Kjfa$uO&5sO}4a
h-wkQdxJH(|2V{k`txImpagdgMYKM}&L;KKZrIiyM)(5GqWxcx7AnS>*Aqfk708MMV&WJ&+(}hUSw1m$t)mDunSX0I{Mv{G1{VBC
OsEZ#|AV^0G67|GjK^>3E$a7B1%l|5mw36u6{NAG`>ZqHNz=trXd748(b3k}o$#`f&vn)y^M;bdcYExpb4_0hhpV=uXHGdP0J2>F
xH4*&e(1DfRx3Q+_N6t+79Cr}{~r%wBgXd@gQ+HrAlaIg$*>qD`a7^FGSpg++qE8^X>`KVE8W35&u(1XkIlm8a=&{&ZLI{*W9wQS
b=Za9t6==T%ApLNDp@KLh0=~|^v`OxY&p_@v=aKy*2uRy#_6o3R(F~NmH8ZR{(+r!Sqhk@=8H&>-NPEs^{%}6N(t<;KtwKNGr*-2
l|+xru6?Y${iY|2mkjrbN<TZQ>1A=4ZHhlX2)8e)9!U_Aj;0Io5S3!yd@XegYtMnZspu`ucXw&H*bNxXdnQb-US`lb`&NO`Q%$}_
KAHW@V24j_H8fdBnKotlV&}fRfmQsDGoZFga+$8wP;2BTV6Q<#+|Q2<duF`*q6>RFB5vunnr*Sa!K@JbV`979gge<#kg|pM^Kxv7
KGd=(+`q^ool=ji=iG8DR+}5ugbPTY;0i#xTCZ{)7h3i0KkC6$@n$wyCy+JW?c?ehM$awAz;1ov%{u$K`fto}!7!VN17JrMi%gHi
N`y#o#jPtp*$sU%*^do}Vu>M234w!F7GGPAMS{=MIJ3@bchzl^Q+_e4eGI#0D%LMg-ZVjf6%kUdiWg*w!(-+FT+%{;HrkYsGp8&C
NiqG+#}eE1V6neqfnSz)sOP<MUUnj<93kg)0Q^4S1J50q^X4gtP2OUE^dww&xMkS>ZPs&{emJi^Z-Jd5Y$D00Fy3x1UHY}UZ+AfP
*(fC8fd&e!*y|4W3B81WPq0>5&>olyji?<1W<sY^neBR0ms0ntuIPRHxEuWX#%~Qhb&9c4?Vaj38(_u#FO2$;K+YcKQ4j1CN+s}U
VmZDSbsM-OgIPv$)g!t6btj9Zp1O0&8$M!NgNdzrnMe+1eiXd_`mtaRqS`gxc{!nqFKyBW*nTo*^(`B`32DRh)D&6clsObf4cOay
KAV3+Y<1!JwHY05p)~?=aTYW3ejtCiO(@7&r3gU9?2HZ`-{LX{%4SW~u)X2}7iAf;Wad#r_CPDkx!(A!&L|exDVJT!m<@$!*thY)
*VAJRMFPdpiaW(zcr?_cSr16+ZBRV;6f6$AU2m1zSg=5^MaRL03K#;kh82}=RT>xX*%v8G=Ex*oA8I>Tni1mAe(RB>Ai8#Z$>L)y
(VCV6!Op8{wN?wL+@GgVc*tS7XY-h-H_JajJErz+UyV@GCsT#(E5n&l*edEFIqB($N+isXJxK@T=RW6QUKKRX9wHp_2CgYuFH$jJ
usr0emW%*b=^s#(r#A^@88E4u@Af5@I5YRbDS8DMA#8Xn?Lg6ke9&|EIg-slHUyStQwJZ2zf=3MYm*raG{<+HUge(y$~7y0u6z#i
kBb6bFK<$oYOF~2_Mblb8VeFPs|s#N;xSs82-qSl9GDi-S*leqoQuoID;tVju$tWdc^CZefF8}7PNJ@RbS|rDTO5r(&Qymx(3cLK
Rp{euM+7_Me#;ryRzqK@1kNQ<rooZ+sPaR;xDXZ~g_KP4_d!x}U4AKt>|9>^o6KjtCyH1Jd(%KK{c$Vn{4knTFVhr7GJr%l3~Oh=
b3ct1SFiw<#?A4JDJMPIHlix=a+luL*_ogptAp?z4HoKXs@B2inmiJNU?)|A-y^<lis);!=iBp&-qYq17uvU^8lK=iAN#(@ZU7ZE
bvm=;r&OWowu#ha>99giq({Y`a<#_J^MWCP#`GFm^gDz0$YG!uLKcR#09738BSCD}qXzk^n15{iVk#%<S?>{nUd8Ea^+Qm6QTbQ*
3h0})9P#)*E8?AyFoSH)nfSSQV0)k|7FOJ$FT?TKa_T{4QmrI6>~bKu#o5aCOOZC?6z>;M%`L|?`xn#1eiiJd&LCUM<=|J_hlT)$
fJ-5JGt*}yO8F4-7A;J=@^dDC>}D@eBkHLP$ofp9%5gt#G+>mAWw#8JL^xkauuz0wfUrl-`qMndS$hv=6rPT&bV0f=kR0%CoN_NC
CcVV%MZ6goqE9W6Du4``pwK2It`h7eZzF#nbQ7c?U_3TuLRY5QC3wVSd8QA6tQ3Wdy#8j(v`zm62qfrwsLdAk9DgFv>ozD=H0Y1x
1tx{Q$(zQ5VTt2*FvkDh==ix?9Isgl02yR}ORL=-@lVcfkuix0qzUW)7|4`meQqohvie28oyGksY6f-r_A-ZiXv}?QM;xHWh#|+{
sKw&w^B#TIe_gK+(1YAw+WhMBlSMFfRh0`2%ZCbcggP6yXG3<`sTV`~7!G;Xixpf^YQI7k)YTxMxQ6)H)1yKT7=&S&O}4u%#u1UA
aeL3&7MRr09vyavbo_dPeLh8!S)158s+h_OA%b+M#vuULt1Hx6YF{HQU}Fzsu+Ob0g#5T8P)#<FRdDDP@@)WvA}M?-ysgR+)jXYV
A|>Wr&O1T-dJIEPvh$^m`1bcEDQ?(fBZAuSu%lzoItZYLm)1w;osd_MgmUBk^p!a(^;mm5y_|qBEgF9*NTy<(fm1-W9?h~V9|1~^
A+qDTCpZphwqBxkxWv*NhPsR=YbMw-HV1~<P4e7wCPEm><dMY26nyY)$Lu7bjc^BJ>3t2kJBmcR9IAiMS)Po04!MdvNVh2Z$k4?6
d&=VnZ@w$$9%TGe-e(VHYhWZ~P=tj|>Qf5*)bcE~UD*`2ZfeRacl5sn6of9wmbpSN&;zS;>{Xqojx;sp7)W(QX^-259}9Q0#Hf0N
vIO<iNXc90EzB6CzDwX_-%2}k)&reHMr6CFmy&S~S7hNKRimE8)`?crmE6OPlY;>~Ed6r<p=eXN*ux7-rENurGnnwMV1sXZ4W+Rn
^g_}iFKsC7(MB+(%AB{{KWY3)d%C9)M0c$4Eq&Q4zx~MpL8alp{#lrjf*;&M!O%8)T!}yb+_>IAlyzEt4nV~(xCi+q!}a5pR|?u|
#LSU^t@t%48`daCwfZ>&5@ZL0g)wE$nRpoB;+SL9;Ag-md>c2g;2icf9oQ0%cdj8`M!V}k4`af;S&v8B<dIp-xW3&tEhILM0pF)c
P)IcOWoMA$k%rRAU1DD7*KAMuhTqyEoGPe(2SV*7#hMG&l_7w8OwWN^vK0j8za;pqf%zmu9vfflYsXFQIZPOWhn?%cS-o;OV+YT9
Ii+2iOu<G%oSJ4)Lj;4augHb-SZvvH9S#+7#!rQQYpa?10^SGu@&cqkJfEG5UvzN<6_R<dV7-`cfOI^{G@gNeLKC(gi+>#9jDx<^
STeb-w@(-)Qp}<y2wV_!D54Qtf3?m@(e-crsmVDOwSz|N%07j8XhqxDrSfTThmF)T+E3GA8SQyI23EiXL87|}iAZoh`to%L*k+O}
u{z(g=LYhGLg(aHq%i)qc6qT9VZvCdf5!({uIW_*`1HPDcn5HY!MO_o0=ht8%7Ff95~;PtCdB>jpW4TPNAo{?8o%$E=b=8sG@3HK
Usvc6$t1m<i)bz=Fn<ihN$)HEQyEoYw<;xvrgLrr%n_<+6%{dPm$_I_%Itf+Z{C7=>jHSIJqAB61?UVYKw702J@6bMDbF*Oh%}9_
F*=zNIw0wh8ql~?=S%!HeYc`FncuKj#FiTz8%g>}NK*b&t(Zm8tAe}o;>#0eat+bIcL{VP@Hc_HwUE@MXu#q&4)~vlSWG(n%c@ed
p2EpOo3v$7)V)6JpZ(Th%S>Fz#3fWcqT=-C<C`_$<p%g$?9CP`rSnz?^y}C2lH_^~ODyo<_|Y?kt_i+S5EVs`*C-d6<{kREV9ia{
zLXCrAlzW{&DaoE(YXB=Nn)s-(n=<@s`x<iIeFHp8{^iIJrMpYr4IYWy+2lh%u~$8!`nBC#mk|L36izf5qPZgGBUylV5{i?)o$tI
y_98=-9n&NUzO{RfNTSTHv&Wh5N*Cshn>&~q2MX?>BJ5+X&j6krPJc#!m}?0HKwP5#u@*hvq!_|Kk0M7D5ZpoO=fP=3ZmgoxXyre
LHQ!A?`U^azE@2&MpTY@mYMu8m2HdVz<p-p&Y<dv1bPEcH_(`n7EZ!#>1>fthh3rj=v)V$3d5-z@*%@f6G}({St$-9Om&%MEp)DI
4GD2XZuD0_M!E0{|1gL`|42Bw^KT*??mvI1_$;UU-=o};do^&ea{=$vuTk2%Rr6fz`Qp{+M@xq*TQjoyo2<Tz(H~OP9L`S|p);j6
cp4*zs1t2d%pY%31MlExC2p_hFjf1Xj!p?cw$%N@|1yeGJSvUWmzoH(%dij6wnWsQFi&nSFMR2MWZ#oX_CitH2&2b7IV3|ii|m&_
-_zJ|TRNW?xZbOpx*^la=-PL$S+5)3;1)_UQsWpT&=iQfc-K8hWqO3+ez*Kve4jRt-A81XO|juj@0(8`Jp_zzdK85r-T==_!;UBK
{AW%d?QfIGhfe$folzX~m?I8RbGbNhw7>xm&0hE*MLjy6!FWNb*q<h|y6JW-yAuD;T)pVx();j~vc~^~QMSWeOalHcTa*}K81_)h
N<xbyBB@x9+TOJAV71uRO`jo$>x*R7ay**LQ-hTrW%|X6fp*)zot@9xWPN+JNlCA$e$P=b(|dOE!<KVX+ihUQWSc>wtUY~pF^ws_
J+x6gkxUIbl$q6Pnk1y0r9rUsT~HvC*3V5==lhdKd4yCKm(Jv$`|KrS{k&x4Vd){Ne|)|_l}_f!r`XipDVT~@yQlNJR6=>r8F<^@
K=L|^P=X?%W7WICG5kSDOBq-S1vxQ;>O$B%l>lRw8HnOQ%gBh_qvik6wyehJ13+8FVZHS&otu#56pYrdgF1<I)J?OP5s!BHMgGk^
MpkhiHEGVP%dg9Z`L|i`WmBlv%OAlWX;^JNEN<{G8U<)TeTK*^i&b)wFOM~>PkwmsU5hNm9zeZQr*j<te~qj)UuZ|)zUpKq<KCqr
;wHc1*&tp1aJ>*uuaZ#~#$0UePi1<>Inx%ft0HuD1;)02<XEUL1!eRDhrI6Udt;$JTK?%yu4p+}uq`&v1;^~NrW2JT{qCw4L@rr2
O=9%K&>q*&16bv|i8k^}@@ak%Nfn0Zp->V|F~Af`WOP||X^x&0K0#{l-Y1qV%6G^~b2-!IF@j|9U$@LBy{30tL3no|2&cR4D`=mS
;o5%F6n#gMZ@c#D{a;aB{T*S7r2)frSaVyH9E6F~!JxHg63*dCm9GIF=aHFFnKhB@eGEcWGfqOLHmPsIo*vpXA8P=(a|(E9I&v&p
n6i5ApPS4`KR>(5dO#R0KW$OSj(0U>iMa9G4HpBm{Gc!KR)YWF0%(XlwWuBe7xpTo@;qalat)h1F{Na3pmNi{8+$TsTjmn6gXm_b
T@Z`$t3jKP(G{Jv&+aq2DnPxk6$8!sgdTy_%5;th^gEg|(@lc+x`ne5B{Jp5mNdYq9mswYhoNelK8~E~BZACC+pRQC-2hdfE8(gw
?KrX?q=GYz7=-mx;RNj{`;dExxm8@Hsh){*`@R6%4?0oGFd%f56Ht0}Y8eG#fx6c;O1&-SV%=l!jvbd+{75`Xr1La5`KFd)ZzAtb
NmD3QA!3BW!_Z`E1j@wBBe}SSKyuMH?na7QzZV5S_J6DK2<{R$21|!fC|(bIE`HJ428h+jU5DUcLHLW?4WvSBg@JM;j|_OW*`=BV
PFO!5n6jeac8H*nSh>?UEiQl{(An==U>8swQv;_p=#Q=ztX_`VZ=i$^<Y#8&3b)t?4FsNS@YaL!gG$KR*ZZdVU<pjMh*Ms>GXJp_
Nf)IB4<_r*-smsL+)aKzlw?LkyEF3m6EgX`i@c35+-*h2is!<3^9ww-2a-w42ZRq}ON@jNsFreCsC++QhB$7)x&IUc+F||5AOF+u
zM%Q!_c-?%{mP<9@H4CwgN^z9lS;K(^wzKd))^j^O78XJWGmFuL)E>!9P)f874LwKO=jpqK*^w;n!%2m5|6u5{H}ldY5pK?An6(a
GI<1@s!l6#;3s8%$Cz*CK(?9*6rB_TKO4BYo|GMUg+BI$;g>(?=e(y^RGwG>!WWx$zz(2+OlfJ4R{4r60vp9iuP80gx#I_g@J(;d
XaBI-Xu^cK`AFg__~k}Z`f3zSmU;daT~<4Wd|}4JbFGuY)gtq_Yl>jwj?>PYYR*qfKW1a@*LH>tbP)3LP-J)uwzm&~Tz5Ihi$2VS
vpCyk_2M+N*ut%aC&)hd5AuO==_3h`BT1U~d2b1^!41pmd%p4%b+8J<7#eIahn*=&y3Hl>&CK52D)Ws~SylvIAdgg8)p@(`j}wS}
k9+(O7`{KV#^(O2m|+oXwg43hed<kbi@NDLsfQKl{kWV2gCebBuqS2}aHt^$ymZgzH<P~^y08fYaP*w7S1~{Tm%aY>XABrbLqvBV
KLNQF`=H`e*{K{NA9UZ)%|v9{Y%-cvqEb`vfu*)-h{9P(@!hg!Y!h7&^zLx(eI2AEnkGrhLN0J*9br0+J%9c1)@)CdWO5u3@pfRM
MBOII$a3E=_%r&zkw|9LgQzCaf)3G>(|DNwpwilwP!uy)wt@%6hU;2BB&VP;%ReK5KzG<U-e9tnANgB}qr2-PFb~GvlHF}Y<8wej
LXa)Kr;NJc=_){9@4#C20f$3z_v*}<x#p#C6_>vs(>_w-YBs1t$vv<=ss{G|>y$*8?Q_KRx^qrtjoi7(Crj}r`?gEuJ8Fw7S6VpY
05v*5j(`5}5<}m`QY)o!iNG;~umv8Tf&M^Qe-6j2#g7S)^Qj{ML||-zbg@GYobq9xH1S#9Huh}Zs}NJZ&)5R>I<$sPM!C9U9JYU+
Aw@*5`R=0L;e>yc8O7n$T>>7n3hCkbJ@=kY?Gxn=umbu<`U>3Iwz(@~C7+B19FI?V_MYh;LM@p(&TSd1{CXdHdw48FUu@O)(EOXf
n7Vh1Rz2Zs$6Fw5|0&Inf$vBb?<I<0Zm+)u<P<_&cysm>%26psoV1WyHa_`iBMy5L*rs4}B>WfODBrfIsco~!S6p(P{SMy-$!9T!
AN!G~|Ft*Fy-{~=;Fb?0FDNUMHWfk=+4VgSk=^aZ3X@eihr_XSoi~VXyP67Y?#78C1m`vWeRy+5%o*@93oA$dB-KN?;_Qy_@`Znl
b(%Met9hv9BNHdN89dMybDi1fG|1S{?QF6;{;=#!1v?ONbx?L+2G&;+Ym?Vn`L--O<6p5j1MAq4&5dY1tFR3e$N}EbmR;(Cx*U8Y
fRxDMzQyeM<ogR(&Bo%AYM%<L!Sx>EMElKrH$K&^n0zbbWi3G?<i$e<8u$?Q4%w9~!^)IHMGKmH9E<Yqc2)?QAlm}z?m<6F*iDjg
gX_;JROeU{8ydB0h5(|#Mf>IG#USdQ+$4nMTC6Y0Nh2ch(K}Rrf>w}QS%2Sk^4$T*>lnkKPAmd^*+GDkcDo&(1ow)i(yec?$It6g
UYR5nfcZry3ai#i!WQ_LJ(yNQxs$l%5iIqoVu;g%ael`O8>zYif00+oD^MdT?9-lO)w%16hD<Y50F+--77VCf8}i~aF_x5ey5ifj
pO?1lWM}@1sQk3>`NV29>Z)c)?m7BdroF>Oa+;;E4)N}seiPj9l5lFxQyYUCdbhL~a(-7tJ8|c+B&N@dWy}O}b+DqSi02{r?S8Zo
^RS}XFPU&;hJx1e?di<Q-;(kpvKq^$ky?&@^eypcAv_$(<8o`SekVO{TSjC%<CZABP5#=ad{hAQUB0P#DvNzP$Z(-dJYW9SpJp!-
ttE#ok^PdukCoiC^R%Aqn&=NEz8YgpM)?LRVzF+jVlv3%+d+O2Jh-{t`NAcbP|G$Q=>{s+$JZNB{Y;O^VXGv2Eq4P=9u7`sSdb+S
K~VhrwKN91u2UhE@(yQRZE(RrvmSMBSXD`~^7P0y-PrjBwH10$GK01T_w7yAwv?%HQ4;Dm#^V6XuwG)_{@{285)$Dnk|(tNRqZvU
4W)Hy8lu7K@Tyko?kqECTn>Y0CnybvGq?|8>-Y6pe0DpfIMoMqT`qiTVyAl~RE@N711Orn8OTYL!44k^GC_ap3IZ9t2j#+@@G_J`
#O3?K)~Ua$IRQ%P@N_ydv!k@s$sYInXoj)m=t}SpI$j#V)AFxHQA2hsksVlT=8lRY`d=>l69$#1J>y9?pR!JF+i=IoRGH$N#3PRr
vgYbhY5a`_tp*cTc_WDJ2dl?s+b@R^<0N~fkQYGYfM>2|omkV?ljh5;=+6LU6f-bKj96dWX~?t|JevZMR0paFTJ-THJ<0Y?E~W*I
#>&eA?`{saBN~5%f(-&6mkZ-p%`EeXB8rzrZn(C=_ia#78n615?oX;>i<|M#qEz!fmjZR|`7y1s*mUGu6zxJM*laWrsUS#fQip>*
sJTV?Aneh!3n(L3zB$V7Ne%EV!wDUF7;#WrzhzKTb_zH!{;pkz*pOU@C2DzaG!y(b={Zy1(9Xo@z+XLP8f+@L0n}Q+oC~%@=0m`&
Dc!zsg|@!twUwsE4fHb*>s74DW<Qg%#R`hT>5;YTa`l(ZP0nQPXawZ%lFAPNmvKJw^jDkhOm@q4jm4Xm;7_)DsUGg+xgduO_{{R)
j#oTt8-Q`Rq(!i&ac1ZV2|$x0M|JB!WBuJkeLTWO{$QI$jevaHu{v89C3M67dXDX77=_1qe{^H}kO)EdE3bIL!9UG45RnrTTU}0e
tE#J<Ibt`zrT3eTP!q%v7>nCw$sB9L$u1}F-+Nag$59(;Tal)8U|i^KhEXM=n-K)bYTwYZctTH5=;5JEk(jHF757|Xn10CLXmO~^
NvQs%+?g3&jfx;0CRw5ad0w7-mUqW^>AYVXOD{4wA(ztO79`!kzqcA#E2@B7>VHf~Zbeg`b+t;=hloG^Ve1{dI}?}YQHN;Mm(r4%
sfg7;ThqYA%&mf<Y!x@lIHq9HD9C!mOoDIMkI8kI-q;4UZ@ZE`UyzE4r(3n+5kFXswGKTH@Gmd4(B_^tWa2e+G#aOP{Lh(KK%4Q3
qyMNE23_`7=`$PZVGy?P2D?Y#H}k@KvIIZ)XTe{(s%!4*mUqV@@AF!(Veytr<s5Rqo`Jt2wGy0Jtz&H5>3}>y?Z<%*$!}xdL)m)y
ty$07g>)#VVT+4Hmh0|*ATih#p^IY09P?;F9X0g&j<osZXfj~mij_T4mD9(9R5Z1Kd`QLeRmQD8p__6bqcxCX%7~izV}x~m{P!Hz
v~fd2F?$9P1dXi`tx5|$Kw3&(-Z@4dd#shpaT&8`2s@*b*ku3ec8AyK2238W)rud8%MuZaGIXxH=-jh2(&W2a*yUvV4ec;``*=HE
ZEYh_S|9TK+Y5!*f<9T)_OzTgiORfIA;g|U-Ms}PQkGmy-KcRiYy@qe^aKrSyy$OQxllq-6D@7k!y`i%5=I-87VD%>WRs6%THqFT
KJ?JWU;#Qz2q(|D(>8|MK(EpmH{M3dMsKQyILMwbQ7R`S#{7L0Z*42NaohR{`e>grJhK*61SwFefw*R*OrkNnAW|y`w3pyn+`u#C
@tHrs7;z`@l2-vz{SdtdZVwcn75_bB&`9Sau5$c3m~bObI-+Bqk)>KKn4fm1cGo85*Y)m7;~her0iGmh(mIa+q%KHNzoG`EE~5Tx
`(We!|5wp^B%9*^G`AP3iD<&;iH9pG0QK%o$S&_IhIW&7I|Irm{={p_iv2qpX+weW!c9Ni=q;L1Kd%S0yU6}xenkTEZy<kme)Gy@
!~GaiE94K)s@v3T`h~iKlb8(TMLV?W6S~n#s-dJB8CIR3EPq@ptGdXMZV*7#|Mm2R03D45`JFDLn}?2Nadj#-J(i^f=}NhWGc$bo
vEO@*Xa?$Vv4<7TQeE)wl5@FQ-K-|t$;1)GYU3NxwpkNHMT4J*XX?B{x#(e)^56hmgqcXWLuf^`_|J1MK-#hSPI)a!L-+Kb=us`K
GS@p0Bl^C)7&s{&J)3)IBQ>}G_hFr!e)L<B1J<}95ecI1L5EUT@3u>dVdvWc=OTHB*%kdHMWHm-cVoZ2ODtt!xaN6!`W0}&>UarG
2WD2GHg@}vFL>|Rs-xPb_4XPpC#6BU>-yYrwm(xfqSz{fFkvh0SiLReWb!4?kE|_fd>!$~MDd@S4{VdK;{nSH1m!+#{GupgT_?rk
hF6ho$PCG9I-)~JSMNUoCCB{w44QpK1$na{%B8%)NIY12?zXUJNB&;WokWmG@&#Jc4rGc}BW!QN5zKSQb4K^D0d*E~_H^D<=V;gF
2+``0UQoW_y4E|s#8z8jFMteg2!*@fp-H4^@+M_ne%94DzR&f|k>&S`bGzhS5~~fv%5s<jx=#%cpvqUS`3H{HRgH>K&^);eKCBB`
{u&+;vNw-|h1gZw)f%*mLQr+j$tyH9?1O1yBVx#<#7!pfM4|6@rp*rk1xa8ve`bDt{(aDTm8qtthfs>tyBX3FIc{SjM@2VZI?dew
J@#n-Sd!Qs>xmz@u^5V4d7X1{8grP$vWpIt5CrzztP$;yX1|cp^PwdT^)84|8W4;YG&mccMV&fk-4~ZF0agf3>-#I-HmKz}(RBE)
!~x;3NBK)4)5&-@D6@%M%Mu`96E#Ybla%+F6I1$mC}T^Tzny(@`43Jdj(tCN;pTx{%6xiN<wj~xbolYPMljTdVMf5-h&J`+o7g#i
xu`gtLg%j0W>U-65p3TOO^jHPF}qk@@a_uyJXRuq+^mkd_Ef=VOqn8w(9I2>*DTQjSSfOjP&)-eLDvV&jP7Ohk5bdbDhXW^ItH*h
^tv@X{0{Bj58bATq%|&6tt?AyA$h`LelG%wOrsdB8qir92Ner65#5VWk(l}&Ve3t6(`dffu<NZm0{s9b{<c)cfIBN5F7O!5-n-w%
F>hd1KcH`*7g<@b3?j+bKo~#7qho2RmAgK`JDoP@xFzzJ;Z^w&^&dubTwcmX=g4(`@mt?C*{<8D#<21R9Smgq{;Y~#lc!>n1u}^k
B$4af>~;ZJ6DGhT7ieQ9bW7DTo?(CwumUzKNZ69#(HZPfW?*^Y=J>|8yqH`7HWyu~0Driih;l8*)n8$YhO>c=uzwYFw4F*55I(>F
3Jls59+ZqWvq~3dcx`3&xNGT~i*k#8cTWy42AY%d<i7SP96{JvVCBB`?<)>9lsiM4Q%9W+OFxIdz5Lc+ylU-<Fx%Z|X58WT+os$*
EF;Am4V!iH!IgBwfie#|xkZQT%DOS)S<9S<Rcpk(29x`ps;h-b3Y=-is>57X1YMaao+%uMZTF75s%y*lT0CxIz*$V0+~tKA2ptmQ
^c--PBQ2o=$S%t^3daT5XQ<d{PFN*?Ixa&_y)j8h2`U3en``DL9VmcW7)3mf8%53;t%fD4EnXodk0qcjS18Lz+lp?cL8G<c(AJx`
v&TrtWa#s*ZbxX8#Nh0V<2t$#vR@EcH6x?HZv^jP=2kt+5qtNl9Q><6AqCc;C71uqOKdPZV;qX5-i$XUq`Y2YTE*mm=240Kayp0E
GGQ7uViA5)4jsr>8b@d<ERokP?;am0KS2^Fx{tYVy`5_X1A&cqnX(2I%xmRufC{LcG;jmeX4L4Bkl?s*M=;FPtw-x1D7|+v6(<k}
-^)#{tdnYtr5y{@Iu7YyQ0O*v1*x0uTq$+U+570h#vBSbUWOl~n_9qb(+y31$`pr$H(Hswcr&=2Y8xcAr}+j^8rl!D9I3$7Fc0eo
=^5)=?!u-kz$!qj{DdfAoYFZnL)MXjM+#xrWt3y!Iqwe~-zJb6L$$@`Zl;5FendbPf$c?wMvKYVzfq~{y|4550J=B0UD&*~V+_k`
DGfGqphG^7<TjHlN}W;dazfFe`ayNJg??pR8P_r|nUR6u9wNJSW{AJVQxC0LOgs9gBCLQ72V(=~A+YVw1`2u?jpx;3R;aK9IK%81
sY@1>fxTc=cidJYXr}G-%#EA_`@;2EtgAQvVe^fUN56F)*Oi)b0o#!rVKoDCZ1_`mX(oQ5zLgdg&*EE>&76g8cZ_}?tz;w=V$E6E
{mB;pNVGCRNB~A56tB!=Mvp!;c$L*=m6;0m3pj#o#}yV*)$9BwE-PtuD{}jY%am?HT*RasUw{Cw4%Ssjwee({c)u7>PeMjT4LUxe
^E9xegRg}(mqDeYGHl&Dv(Bb>NP=SEEGRyOl0V7!6)m$qX!z^lv@zov0g+!?QP8QJ-3Md$D->J7_(P{maq|~bXL8SC`wtswJtZPo
(U7auLw1a_HSo<M1{nho$g~z?!EUS%eWR`9oZLCg67C$^O?bQJ>1hVyX!m{N@Nq{REe)f6%F=d2M?&?D1}ipJQcF{B;=V;jFINKS
U+)+|FN(b9t}DB7vhGa5D<}mtYouNY-6=Teu;z<SZAEhpa;N>IvyYq~J{s!S)|M;NJ~1_Gl=w-Ev44mzF-Sz~Vo79eLC9#}EXiB2
(!tyerJ#VYHu`wf)aw2G8R@wlJJ1>+QWPFyN~eNiK63z#<c{N<lVI)%ju6~0O!Fb|7&kD>jP(}hVjK2p1`W2=O<B*HR+Dur%3Rjf
{b6}v$i&P{?c_-^D|GwP|B$G1MF?QF-hyr&(qB@ZLVHZs9JKRugXx8jiK(}?>n5vFa+XPeXxD)_lNVUQ`C^Trq&{HDi_A3UH(l~)
O6?0o;Q1UNp_vjGVU$WL2-rDx1{J`VA#7m#S{aE;TG%ixw_Y-XJa?;4g{yq=Z{&=A2^wIQJ3k-^(aiE$H;{))`ojoUDAd!VctgSx
R{*>qR~}k{0cYQRVkzX46sq3DKkVAt5=dz1#@HPAJP3F~#Ww*|hJHYK;&Ji$)uCb{jnK~|$@IW&wS99z8uA59Kw8Dd7SY0{?_$bw
hg0eYPbipgt3L+(pUW`*=~<_bk}HRWOWhjgvSr5=a;mUn`#?bccwWxPvT$ka5+Cw3kuM+Y+rug6tYaPjH}@o=Oo94j9HTC`rdH$G
zpQo_-xr-IjogJ5F^;yf6D2&k^whEXmq@FK);^YU8=le|5dP_wBv*R1>Q}<sLE{A)Bgk-l!7b2s?TJU!IwecRH4V=;_vsQ@Wc4HQ
%uudVx#E&nU-Zz-H@zOo`N1-)x0xT0B_+1M|5Wru(7<3L5SH*&o^|#nV};D5E+D<(|6@5Lu{H3;bUO@y(*bR97uORyiTBo;Qq@*u
%ZY_%9m(Ub)cHxljC|YGQNlEtFo+4C8=gyK4+V0jr9A^WxrLz8oSB0QpO5Szyq>T*d{B)#KzY400gK~gq#HT{u~&@Y3Z0jc*;ADW
O#0=xRCsW?p>%^S&YOR<vh+gD<Xchar#H}A+KrEg>Xbp$S<y&V@wc9kbmEW=3Y`h(EkNq~FJeo`A{n4~MUf-3qUfh$cCz#NqYsap
x=P8<le>-oy=fW`R0g4Gb^QkWO)+@sW@cHkPr5*SwWQ#M0<9M8h`%&uSYOfjOZVhI)Z49qYFpe5LPeB~o2rXGON%<NTvIEQEw-hZ
BI3h-oJ`Rt+D9r!Zvnq@jFmqKO|TMyia$X=ry7mwzBiKBl!8Vo(NUiPKQIP1oy#~I;ji5Goeessw&h>FSYp`WC7e8m9vRDqMMh&7
71S0#WTq^&LpvnK^VH+FYqzAb;JTd2{C$(RV`oc2`kwk==waYhPpWI)d7;+tPU}K|_U3No;sYKaOD0=N8u!ZWkmIhk`8XC!pY;W4
=mS|+=E`v(q{2=FS0xZl@AJ_DOw~aD-q?U8#=waX1k#WIhu-@K^k=H@^u+7H9bO6&6sUw+h$^x6Py-q|P?(K;zP>*Q-q!Xjt|V!a
r3Dmzka`!>x}Iqsy#r0!mY(xHVugLQij$dfDkW7U9THJc$5QDofH-3n=x|4*CcwteDVK9)hVUzvy7sM6S=;BAX?#0Y^b}(MsY@hz
HQU9m#t;ESlQnu4duQ-X%`Q~5&#+lqu8x)Gw<P#D8G%}<=T2QNk&cEb=;##xFOo{eY1pxR#nU5{a`O<40(h+N6steTpiQXxD{45z
mHtB{_li(H`>W&k@Qpv<ULi5MkQa<in}1fDeH_<5g)Q&5YCGweqUoaIXa5H%pYo(&!WSyopmqQo6RDO>8bs8@)^AWH%k{IuDf|Fq
6cH{+#Z;Tg?&!jAoErC+os1y|zDEsN<*->sr1ugRQrd$P(#*Wdiy>F64an(FAlw}L_~4`+9E9gt#08$-KPp#j+IL(UTX)TX^kdh2
3Swc}FezWfspdcW$QAq~aB^_aA*j?qL&;`-+L7h}|FkNBq}Fy_iAVi4fNVo7NrBX~gn5gkSUA~t$$!EF0c6ihmana{yAQ3Ifzp3D
mFW*4@)}0?W8oe6az>S1b4g@dY6W1Gpce+)S<*TE4*|J(RCgDX?v+nVRwe3dn&RkliNI{u?j)KcGRV@!d8PJlZ>#unS4O#tNGgMW
jd;vOm-rxYPF1~Fq);&^NRPuFWubVAyput$SHFT{H#to7p2>mD_x25(qM>d!!&+S%G?}vv7XJ9$W|9BC+}CImfQ|{#`slseu4ECP
l|+#z_b=IdS+3oy%UNJrO7c>tJ6S*X!@|pjuttkd=8PmM?4JYx@9)qArivVg!Ytl;)DH}`0*A_s2w0XO5YRo#w(7+hF)&$+XId%P
29ag$HIJmE3L9~2o>F*~rV^|$zKg!xbi}*D_TM*deg7+w&bPR>ZV=dmTD}Zl;i)5zpRw-<cMns;&-Fy;tw`TbyU1W(ry*T(z(2p5
k%(L@B#<#_$#4}Q^S3U|m-@lO)1bg=U+goLx{|I|T%a~tF3(EMDO7kfdeSY($(=-piumh6tEZ~-L2MAmKhs(*#^W|pl24ETw2b3A
y^(fY|J5r4c%w;J*{W^_4ynuWZre)0@Eg(oj;i^Z9l;Y_F^pag!SE6ryG6<P)XgTpjxb)s!3}X?sa_fm=`F|IbezF*B5G)U2E15c
ne7O}=39-%(Rf>Z>mGgWWe^;t&+fJ?ZsEBXb$M9YiDT^h>g$)>Twxl`jN!8+o>*K-YF@}k#+EJ+U4c2BZ7p{-5XOV_ZlY;<ohd9b
zNh}Knl2gWe<Tf1NIDYbJFEC23q^#x9DapeOnB*K2V-#zloqw+WO|g~*!pG~AEnYQSB4`sJ5p@ZEd<~Y=hEJN>iU)J`NM1ZopEs7
;o3(;N)E9n?2Yf6xOc+?%$)=HH*@3s*cHJmUu*zuKJW(53`CsBF~-MF*hp}u4IU@$KgPCF^ewiand7BGBX1bnvu*576vvC_!mOIk
umabg2FE?F=HEIKCL9&h947hc1;L!HRe$$*H~7&`GH|F{&;zZ*Pr1u;SIr`xcrQ4s#9k1D%;ja7Y7+XbYhT^%oH^_lSnp8lBJO9v
uL^1mGRoJQr6F|?(8@kj?EPasNKNb_gkJR%3DIv>NT5EOXn*;c@r+~YudZk!0h4VkfTcC%rsb$?BA)8E=qc@1qLP$qMy}Y0SNRGr
*oirOUTD@w5Ys-uT3JZ?JA!3H{4L0EGlYpeZfoP|2({~SrGu;(>=sI38LId{?>lKFDkWCyldQH~iq<^>jN0{(gUG(edvL3&oRcDW
Y6miOEQ}S%QqDPSM*VSf3p=N9n-bhe#llHY8{jSIRGc_G-j~reeZs8G5~$6SwEk%U8u9jMJBBCWU`_)J^s9WfH9)~r()=bB(z9&c
o8vt@xMmF&Xj{F{?xyGnV^=u5cX>tC9sZLm9uIE<dJz@LxGr$HOww0NZ_@(r#aJuqKZC2Yn<DbKnZgRrD}-2ly&<;gx!^Xn$?;i6
rBRi^(COEWa*c(&I}9E6Y`3f021%&bw`Y0RiEQNY5m(AwWfl_T#1d?Hi?F0IVCCKWP6#@p@Hb3DTc0JrBG7s}BAV-hP+ozN`aF>5
afE-XXvhu_ICVIII4(&YRi$-JR#>skYFOg&`dqX(>M16VIkt$QDTcW;JSBRLoZzP{rtn4e^X&hp7l}T99SLmsoxQN;-DBE=@(u2c
-9|V`oqw4j#c%f1(+_wFG%DgYN#aEo21@6_iGUzLmQT|Av?{c0*He!O21-8HLzI<NT6aIN*bG?Gbr=pGO`kFO0WfGdy8M&Kcsc?j
_|Xofxg_*!XZ4+O6?;9wtCb^i66IJ&uI+-=oqxawx*t^^0M8b;T*ozaGP2oHSPqs9+4~C+kS0Akoek1=!XBCh7e4l7_B@^tYL{6z
Jv1zIqmS59i}(I%TnoWuQ!VRC&_v+neDBS5x>51A=`AxAgdz{}2!`vUVrIk-LnuU&x`V${$PTazd`$ky3JsPL<eOkfeGvZNxenWV
TM1=IXuNg>pJr77b6n@%;z|jAi_01)I6zS^u;@cWNmQPkw2lT{8QP~1G!4aFPMU%L6a<c3N^F%vJ&@rv8L(%}JIAyfzoZijj{ckj
_vUFR;+GuPTv!TjHU==Q5Ap0gVsuT?NImeD>ogZOYGmHVuhw&49~+kb0QNOkdfHvy`9}+yP?NlGgRcT!C^o-p_mr`b2^Af*d9klJ
h7=#T7Oy-(!h9XDe7zlHtoAZEQCU=0r=5Do=TOo>p6ImhgeW+uqi@a5oc?h;Lq@`D2`ccfeP`#PXzfTb(07F=?)jb8a#VM0ENauk
<I~_!w-&-O1SoBbNZdDveZoW|7K^A9{g0$et)p=)`ftOr@VN-wc^!%Lz?Ro;b4E-YM?drRC2F>{GdwQ*=Pyu`m3Fjsu)DF8C6{}z
oGX)`_a`qy=EDKrthY1SXqa0;sfgpB{Bk!%Mqnkbo+-tJ3I680Ua#ivygdmY5)2W<B^#*msrZO`WHou^Lc0B;*enD%tM`K?G>V?Q
7auDaOk|PF1S3q)kW$!NTIX@sEF93lHo5H?{(iIYRDd(*&IYpe7Ry&8<_0;<2&^QR=^&jzAW9j+uP_8z(Aj|^79M|ne1K+YU?sHH
-kJEOGs<ucc1(`m@s+PrKKp9*c_p%^6!j{fvz`AFwZUVBcpAoC-m`1B^0pb%&$KE%4`ZOVyIpnL8a%Df^-?V({dc`!t6)GQ-2pzw
ot5zqo6|2={<sAZzW!jAu#Y_`g6O*ce3-zkPsq?LzuS1;)O<P#SK{M%C!S>et;}c9;c>)9y+$1GPeS8O?+EIIY)F=7^Y`15=N_I=
2e_c~gBT<-Q*-NE2F;M=Z!a>O;8LYU7gC&|J2^T`HZcA|w^`{N>Vps9J}>4C8jp4o7a4}aOf@ndgfUh2l6FI?FT0Eb(l$S;e-^@7
qcUT72F@i!`_Jq&|9N>YVx?r2L46+rW~KyzSQ`**C|}A@EwSJ0VeR_d@PxH-s?+;X`W)&so@wy&&1AcC|6{qt`24!VSD`ol$cfM%
DCCSgMi2%<H$Q>G&0-TU`md1NSDDUh@LilibaW0B>v*p}1=|xO(sNWh=V}ZJMG#%e2l=EET0%3rzbZ?vr6xH1(T_f7t}~>xo#$|j
Ra(~qV{rk!#X+3PSd%YN2%9L}(;;?yKk|gRN9mSXe66z<3Cq;H08y=lNPIY3Wmc=m`M5<c3JAvtapmvVdp$hiLk2RnJDdcUSgG3<
V|E6Sid&!)$SxF^*C&QFw#GwCxsxi7qEt>sRp-K#wY06X!_uoP>{?KX<E%@yG@z>^nmsI<aUvb@C}LujCu8QTM~Sk@IL`p&577y^
;Z_1Ly8{KrH>4)oPbxQkWr*HF1zOcC_aFo)tl;3ZK3o-q8e35X&O6|%kYc_k2XRubAO;A_hY+_~o%VcY!&GfL(^z*fZGDcB3Mkfv
GgIEd9w};|?Z<~m%Y@hH_2=8B)K`(oz_E~Mh#g==s-8|_C#5TA#D|{ClMJG?Zc@YOsBIJMi$6PAAzx~1S<+Wz1U_*82!x4b2`U(i
dbhE*!8$5zgTAPk!7<+z#?~i{+!+>eCqaf#N;rGJRM)`ChJ*V-NO9_j5A{o0uQ>ojxW>)4%ce^vt#d8}ASu*TQC&l<`UjJl<>y}B
G*I5rH$2M-<nI3xj-v$dj`}7Ci{KVwTJe+)ZHZ&^;yS7kJ4TVrnM}EylCawOdSWdI(7!|d>WR||U}F+HxJ&}c(9esV#qKo)jn-0m
n&5}S9f157Rzn3GE$~U{$Vqvgj<T~+c+j7V|G7j)F<u6x(=VcR{NJ}_Gsq>~-@vp(l_#F?^a2V*vxo>=b3v|amItzRCQcb#%kqh2
?E&mi-aI|aWC2BF^ru6wxnuC`WSK7kp$AXAp?%OK3BxHryU|<*1e<<&FSh0sEwT-8Ub;((5-eu-OCiWj9izE7>uT>z_<B@aj<^?Z
>R>`@vJsPoVfXU7q&r9)fvIU@@UC|#SL;y2CU#l!0};5f0wysJxVLHB)a-rcl6!d>#a%rzR7!WVXMtFfDIVj3)6eHGRz>~widqX3
+99MsaI+^^MCBGT)EmgOM5z=SLi^Sd+{GDYlO{fgscjtIQ@R(F4Ip2x<X65G46YIq5%cu)W7o|+4u<j@k5tWl@W&#lWo24OGZ4he
2_~ZhuMLV~(}UmjQT*o>fymMgAg2Mgs6IvxzmM#G<CzC7)n3s)$8%jer}D!3gLtP=sn4Uw`UF3ygyi)U9FirF0~IF~4&UlKunrcY
gV=6qcNv0XE%1F3H+z7{tI_673i6YZ*QlFmKNGcI?*X?GBGq&Rx7~;<K322)PJsdLcXCWx)A}=dpz&uXPxA)pIWfUsHaA4q48dQW
QA`kOG<PYgQZ<(@=Z?)12C`VsErc2S(E^u{d*uzTzqWqp78F#s23kagp^J3owA8<b-tH<)&>Pb)s#!Pl8)LiHG=ALZ@6R`$-)dMa
dW6|01i7hSYbZ%XbrNtdD?nO#P7e11V{=J0^JHEllpVwNB|1P!uigW9X=?!J!KqhnGnpv&)<q;8Fp-CUMT6+VZhQk1eOUceAW*3s
4ou?MiFU?MaV-l6fMg|)&<3>jfx3Jxb-GK>YhNkcv!eZX55po-8~raVZK$?0J1Ve-VNU>#{g<G*<=Y6sc+U937}n39{7LZmhq&s<
FSC{R9#?6tl`e63%qKfU<%T*Zm1x(7#-jO++iD(I*a|Kl)1-#|@>e~E*Qt-ewc1&m<&{S>lAsyr83vTbwCSJQAAif)dD=4R)V4}}
5s#-7SKWeLUhxPo5<3&R*Rz=q$=Ns4Y!<7h%zEJjB*Mm00V8(H!J~G)o-`r6!}*sNcxeb&o8Im^>`<CC$Zq+35GC*YFxr&HKReFO
LV`JI7IG+FLo)ZqVMs<u5QlY`S|GL9H-#YLvZ}M$Z>o@+)r#aHda$L=hCK|p?ZFBpa|Us<V;KA6&bZ$M#{^3d)X=hFY(Ctenv-l-
Vn5D63vB>{v9jr6XQh`@k=#wtU(k~1C2tk{UBq;!V9%<VD1seTKXGWKEdrhxM&iy8r1UF|C%O><K1N8p&_&o$$(i{YBYjQTq^7}d
S#?TMBu4o-=VAMcq%}oLK|H^UpZUCxE}DO6SLV*=QioV=APBiKP+cnX+5?auIoun>wd@Z1fJQH;*lWU3cj|9frM}6QCV4x1witp%
B#X<hgz|wWuOOP`X_Dd@cjz~l@ERBCV0z67Rec;pSWd`SC%KM<S8ELrDt}~XTyY7bIP&I|aCZr|0<5Ne76R(IWEwJyo{g)CrEHeg
ddC#i-CxI5nu<Qkf?7id4)qlpDNN2%<;Upl;{JCCssz>tlJtr!f^%FW3G!r0#mvBou54Q9qnHXH$|W?!0TfOJ%?7>Beq(f_$Rq5P
%wR?JvZrNyGtXm<_s#lQTeWP>`$P-YyzVZxjY61-YV>O=ft~-tu?PEv=-^eZy9SeThIgznu*D1#8I+hdOqLJvY48h=aH0g1L*&wb
<s$$@7pm2+%UTl`i7p45m5WK9VN@}0vKe%4yu@p7-Yd*XA{s>{hRHGaYuo}IKCzE)+U+mVHh^6h%^qEqb)y?kK1AHLKz+#XJ^?z!
_3zPW<Jj;`_cQybq)Du*L}Fz#^VjZL5YpkvuTn=WJ8})c>OYr2Zr+pkN?WBaUJw1oCVK43S=;FbTXb_Dv~Wi`*Ts`La%&Rv?X>$-
<kTG8m}}<Oq&Vj{0^zI~yzroOYAW-f8>gEHok!&|wT|!w1+3JN8YpTjHpJz<eZigifNzVSRgi~_m9to8GhjYH2{OMuPQU%yw`_kA
U+Arr$J5(|QzUS^_od(6@69+w1U7mFll$(D0GLejwWW8h+?dy~@ffOGGczqKBG&IT<rddv^E<$-41uq62|FT-`+L~ESJs)uA$4lb
WR8i*Rpr;09g9*G`MQ(i=T*!TKLG7)JA)_b4{tC`bA^9iA?;6|m|R+PZLNKKCRwv!#Cwh=J0}!vmD~sd9?ALbQDg<44ja`Xe{Ptm
ljCu3OtkzAuh(+1I%RTv$z(W;*<huU8mHxE_X$dqMIDB4QZHF~=`4~w9B2Fpg@zQ*7)>v26co{`U*()^MTfkmHzGu8efJfHG^K(t
v_MFQNQJ>#+!w4G^UkxF%B31b6b`_x2IN7bxR)0dg`oGAHoT%W=sdbK47o@BdrJF#(a}!qF*2rS*7E>59c}rdxtW>DKogLFA-DV^
KJvrPw&6a15dE@$Sl;f~->NzYCB`=DF0f*ZEi#BDZ_4}3LGfqjqvbI%E!9i9VoGFGLkULmx%Ko*pCgW8B~O4uhG+tI>+H!Rq7tu7
gO+QK)YV)Mjg%YVpz9Otk^sX8;y*VbuKt{9(GgC9*z)^;frCgjVHU)M{6nfEr&T1?%hV7(f$r_D2k?AJr_gsTvpyt5bpj}%VluPr
DXQ0*EXd2-L*OOslt?e8vq=-Gbp(+&trHQM{+&eK(Ge|(VxUG2JPr`m%qW-p^FWTRy;kYDy~%Pd8MZMpALF*~A6DdX$|-XzR^WXi
tTRd+POdCRjszF~B)gQGMFh>1eeVO2rV@K+6ko4{`4=svrg?nkBZL3zA#U#0Rk$Q9N~#@U*4<>tRWCS@i5{ND29ud*1-&-(s9OI;
zE}9!t!@hg?=xGK^Ql56ll`!O-~pKwm|7a4AdVLou)inwjE7xuSK@c@JMjU)L}sWmuYZob#!-=)YKRZR!$cRNHt!Jz{FH<?iH*cc
9!FYA8^;u+13NA~9#ZnS9OE4c@Goe)>!9F>sg=U7I@gp$rr#A+R~C8qLb28^Z~blC@z2;iVeF89IQdRi8SXF(Sr<HN03T^z>1=#w
N^q6ORUPpi^(MohAX($eLr~ml4|3SB(?Yxt6XEN^Z!s(1T&03YuQ$`urbsmb7W+`?6j1Z(slYy1P(TBtivGHR%u&$0szgeYI-!IP
c*2KDy;~2J5EzPrX(Rz5GaIN$k*cR+G>tc0Gk23duBDqKYeBsjChALRb`B9XIGr@#?H17)KuD-uKxs+(R%3TzF1E12s{PZGzJVGN
@+taJT&Ru?cHE$*2<<kGjMj2Zo58ng6D3i0m*7zU5n8X%=SF~*fMa56=GP)*D@rMPeFANS9BWu56%HeA+m8&dCEB13X$#$_^G#ZJ
=h5kbj?}KCxyg+28v0SOxhYoBYN%<hWd84R9N~`%H34vdJiSr|cj!OubD8@^n)3c<lJf?1L_LdL^m;iy2T$k2Xfxc^Y&jfp{JThc
>4y~I3AHN|TFJHeLH$wJ{Uqw;Y?S{agz$Iltjqrf-X+BIt}|C`G|wZ;^oDCuYgO`$Y5p1qR$=-{Cn?l(ZG(K@fcSpNp}^CiozEUq
3=mka@YV8RPVhyBDvr_uQ6kBg{qVmpeSsWcP;Ax`|1%`Vz&de@1#n{luxv<_*hi_8bEZDLS*FC5I+TXmy`t^WVxnv@OA7xc!KbaH
)9q~DJmsVFt!95{$i#v#?=If+X>DBen_s3w=4ZH_H12%%^UR73q<9SuUVLsyTCchf>-Xv=!#>vXCO6Jx3cDUAZ!kymMxOktK7ze?
?rYj4rLALt!lgGH@=uXn+i6g&I7o66ktp9luOVt97_#{oTx!S;{@i;X*v)5;$YjvT+?LlJ-w<vQ)CluvQ%p#^%YpT!I?(_S28U!|
c$jESAxxa0>opas)&c<muma%DkOV9L2Y_-Q3I~QmR9QhDPD>)umb-Q@8+oH045EwRW%AztTV{Aj2l=%$!gk4ZLpJbegoq2Oj+b?P
kE{JF%>4mMIo4R!Uo|zLLDkdTINLdnL`r16^3<6fy#Lqn8@4MtxrWUB8aB0xpBi$t|1@#6urA9ouz+b!)6*L4wE<c8)_>hwRA|I3
T7paJ{8PIdQ^?G2w{fZ)=91(kxPj+E7Qdh8>9@Cs?c)g#6HBWAh;?KyfQ<`ipd&D{Vfo@ZAZM$4>EbLC{m>5BW_ut8Xl5s>o;abI
=@wgds5WcsRf!n^Nwa7&XHGPN!DA5c3O{e3;$?8H;kz@X#RCZhh*2`pROTXI*-ouEF~e(@`c{F$wltB$^DZI;Nd`pO3&oiT^eeiG
M-DNlbw-F>UfdDu#(w88=3>I~ZqEqlvuDuZQ&f%lAI9v~HTdR^Ed0xwiEqr?Wp&x^R|EG(MMOv*CS6M$E`Y&1UK})cRj?h>{KqML
*A8->h((UQBexL4yBr(ptPg|QX^XGEmp1+dER^h2qxnY$q~XcHkw5j1htaT4yV6h8`$41>!q4e#^IrXZ1u9PhNWd&;-<{X)Vu<iv
+^KXV5Eg2_Y$)fV)>Bwh^H9bax;#EQI0JiCyu_RYK}f#%ah%*Y;>_3r)@<`B?~`G2fcZaRP0&nVe?wQt3Ph>PRj1aDdm|R7`EVCR
DN&(eXGw29V2DhKJ^Cqw-SgBZygdgM30z%5JK+~(R=W&+KoJ|rKN*qqdsS%Q*riamk3Wg=vJ5S?6_NCn+l8dT&eq>BTFz?AGI+?r
?!;8KtOYSLYZ3G!K{3v)-*8(CgCagw2;^hbN}+<kR^gE7FQruMiUkc#tk-6Gaj{WUH%3&J)R9UPHDh1#uXxy;5G`~odxiVL<aZK4
K|Hf>#^@RHvY`A?txbTBv4s_v3Y0y&;0*y?ewh0~nJ2PYGAJUI0UDQwmf|1(*_B_X^%Q=w5;$Q>F+2%zgx?#o;Mj}s*_5ZGhYf~}
mkj4@v_iAY^OMV{udX<#t%Y=`E++XwV8UP<nC!&{K0rt>ljVmhx+<L&zI`x4y@!f8O*H=UWE^}XyP8{}h$w%BlMKWpd>|b9v%9)p
hAl!6;v7tb3A~XOQ8yF7Y%Vn-7IqoQYOWv9gut5&mQui+(G%|R+Y&l+gwmRjH`_0Q(eJ?fI*bi|^|{9yDy(+#oTOcgZcS%scYfai
ewhodUP?(4qbNAn6}S*%ud9IV(;R`{G;l(xZ4?$AsqdQUdMa4`8hD!{Dqu%w@8HsdL-e!f6<0}LJiI+7RTVs4wkr-Pn)676nf>-z
B3o}IKVSc9OH!<&abye~?3lX2*l>SA>4}J<BDSJDpKz>Zm%i5@GuEP1@$J@nDbK_C5;$nO<JJsv{g5+BdzFojJ+r1{J*7NRiYt^w
3YEhJ?G?(qoP%<X-K`ct?>54JC5fJKY9MmO#1cz)_2Jp%c%Pw$*fY`#I{;HikzxhteSkn%cIq@F&qM^{F2ZA~-LY(B2V6uBn<B|N
v3wMT8zHMxFKqWbmioO4JIN8iBF!4vFsQn9x8WwT$o+053Hz~utN`eHfUulTuxySqWI#+<Xe?8JxZyGV$=nK}V#DDq!OW2v-2S6c
V!-wSI+Ssu0<{z07|ec8mi;r=V^|D1hB0l30INh5SMKo}`C8w;rTszK7YT!Hc9_8P3?nDv-uU*2--J9*7fhZ-V~{BQJW^KuI?SVP
%pJ#)PQ7bhAJPDWbIM44<O^t-$LTEYz9KfQ_n3)EJN3`X@%NUIG<LvJRYbx^`kb<j6zKgF>x_H(vlvOAUU?awl)qNoUmLx*#CUI1
$566PGe&CF3w6q;)Hm>NTGPq#EDUn#(iouv1B6Hn?a^YaaIHy<s<=tJ(Z^KRwKPmV_wYmAP&_s+G5PL3zUu=d0>|&Jndo#1MJs<X
;+fzb>+>CNRIc1SQ`0$}#d~f@=3L<3jV4RKr0r60UF1ql-q^meQj^Ihtk3pID`Xar@%cZ$^)yrcw~(}bnxuaD8EltmwbJ+6vD*<O
32PnAeG=G>2+%EPzzVe@<Y8=)6kj&z*1y6CywrBTlg!xKZMWsn_+|<N9ssPl<lcMg0bN+d-3O)Rx#td$1GLDCU2$=hw_gp5l7Z=?
6xoJxSiV|u(<vp#_BbAzF!N=rz9X=%F2H?ps~#-6dQo3isG)lD%2b1jF>8>@_!3k-fqsoopu;s3BqH5AKj!KZ34??PlmwnK7aLBI
7@!s8Hip)O=(dHN!2!CoqclbiqBf==FoP)ped^QPz~#UT+9CWYYl=e38<(7}i{^NIqF;?TO#ztzDEJqMi3d=<)jF0cV^FED*u}Nr
(8B8U_E5jE)Ol4c*DzJw5JeF_04SgI?zVG4uJ0W<IcS5YxET;cBcM$#mFPO-aYAV%{E`XLREuS)N`zQVmKPQmv>!N+ST>C0wkGY1
Ob)n5WPu++rmZ5}W{x1rm;fEhhX_=<;c$@*yy>&B|2Bsk02^TFpM3vAf_1Z4NZy0HQ0D^d&S#kg(LgL=i*M4hsjw^)@=1SNal)s!
xhwzGa@s_)u)AwnDi9HgAj~N~regk@I~tQ)b>SAJCOgr(qp1FUX9T@sVOMFNW#$#v{9rF)<7n$9ur%?qh8Gse*BJaXqzf*ygo(5f
Pm><2IWvxCo$g9iag;WBo1$Jd@Fxv_K=F+iC8j0U3NOUN;4#e|X&982UY~IZ5)vZpnCja1TEd5NYb4C7qc=J_{NKHqZv3oUK_{W%
QfeZc!&Bi~{%T%7)eknxYt~&RgI+?xMsB1;hJ`dRfDZ=p&u5X68$kV_i#ceXr})9L688}Fbts%`Tfq!+c9U{NWPU`WCu!n9%yfT&
Xf>+ytg1&(y@?=u6GZeFcwz7SnEjhXKhl=jNm=yo|ForqVjadue+y0yY|lw-(YNvx`qbGJL|@(NXclm($nwMAVvL@GE~~396*;7<
XJGa6UF~WJntsZui%+MlI%W%uVqnY-fc_+T(Ra$FKE<TIwyp!-7}6ot$XRc)n$;xP2&PM5ezTIdh;IxsP5Og3DQFQJuQk)6dhHXq
;8jRZJThwLRSdiZ>Y=-;g=i+&oez&;cHk4V;I+f{yBltKkAJDsZQyi9f_AK$q5R41-SsYx?~`?QQ;8vsma{0*4%jM}e`+R!14L_z
m6k@Z2u3%@j04RR!3OUxA5Nj}r%>7}^!m!Yd7t4_7yok7k0MiluHn^TDIzsdAIfPk*}Cp`BK))Zp)L(vC$yebBs3yHT@C$j-=hpa
qe6XT-(OS?t~IRsEY$+0I`B`rY5;u-LKUiI5Sc!V!gjtu+n?Nog04`ECCXoA^UTA-{SxVf%XAk!R7t286%W_7D1l3GHmAdb*g=ek
gXns+nv|fjQr8H-H{AwDMoe9-0(K}Cc5cBh@iT^2o0P5~kq?QVzcmn?B_r<vXxRfA%+^BO7sYA~H_V63O+t^>86Kl#N~bbno}1+d
l_46t!)a{BpVsiN57cjiyp`<N3+}TT3|Fk>QzM6Wcaoagh?GE5d8%U|Q!Yv4b`}k-ZT(|0EDX@q4!n*dRVU7^=l181?(AlqgKGby
MR$Wt{1zI>9E{q-ZnZak+1&Y5FmzSiVjewGbz?9NoHxKa=o!32v|B&l1VPox;UVR_&k+TNUf3zJMmJjPnMsRR_EP$}BRAeE%P>C?
LJ0>oU9K@=#p2X;@-#P`+d!*5bPU=9)ivBR=#~h{CnZ*!VJ)MK6EL^uIwyqC4$+wV%L>ro08p#?%I(+&o0RsO_On5F3>!0m&;-c!
B4=X{ely~f>PQ`fW%<m2MIJ=+A|o)G=%`C2z*p0>eJ<kKZ5xh_S}P1RZI}hhff=|L*iqMzhDUN?M16J>&^J9a8Qa%q`TOX*VPp;a
ewGg<KpACkSyQ8Bd)32Avo{KWR!#?jITr}KbYeD_NT!rbTI!jpW836}CKUU@+HU2f=I<6<RgTbfcAV&<9?x~QP~2|w7U*5V^-o-1
B4s#vW_z6@&4E3**-e9ew)>k36H6e%&IMM2vWFv}^(#0TCsF<05(|fg5O}ej1?6r@a>rc_AudyhJ%8Apbe3$!{BFGnbLb5+CaTM2
$Z_gl7iI0*L!4mTW>G{iSGZc5Q6P-!?sA&TirBQ8ayy<{)ecP_cceErz_SB2(!a_4ysZ_&O=hbx0HiEC1o(jJ`Cz53xdFZRO)k-w
Llzw$cO#5-GH=MJ$HmEd_Jh(DwOY-4d`dfyz^3RE`!4DYt;B>`2G-+f{Wb`=RAB_6ncsHbC;SQ$N5wLP0?{27hJycer^awU<H0bW
W8UmuE3<@miwgxbnR2r(V{wWG7s|@|5gT8_YP--0j&4sbhW>ndN^*kMU^yKA(<9v*zfnfi^;mb1op=$lq*UE-LP;6^?Cu1Lx;)hS
mJlcn<&`KybANk7E6EZ40~ig82P(cIr)oI>&OOoVCkBW@A~EC#06>I_lMGMJB|Kh_R!ywgpDXgO&bJGk?5aR12M5s0jAQ9F2=hAJ
=E7)_k9qzRc`4z>;m@<q3iE=TLCp`ADN2%`=+t2_?c7K(ls;VT&Fh(65v>s{)+<s7yu!MqL!HBX7n>aXLc^EJ8pZ*)$O~pD4fdLv
@`*lq_^oQA=Q$Bw>w5UN-`D@bTiK76zJAkR`uGuW<VWuPbi3YdcN_P9i%`v}kzE<!QPdRyg21ux_#v(`$isNQ;O8ZL2d93Gl2JG;
g@9Bz?eyW{U!2Kr&nE=IQ@p1((XT7ZHq<Tc=M=+S%?BA$Jr1i87e!^#7BPYPxvSa?Y|sc#V1`k0v)JMUGCN9EKa>Kz@OHnq!haR0
|0nZf7?^k31>3<a5BIpTMB=G*CnJ<lQ%98aPL-h@Gfh`~xaZ=Y+pI<k$z#x-7eW9Qk_<{EvMSWYW)*GFPS^3rI$>!`&`jszcd&2{
0zUsvt#*$AUeAO6ZSB5f6`B@))Co_4`}S&&V*mE3Q)I~WCrg#yS{d@jVf%>L1q*6PXT`e2gcK#~$0U%~g>vrH%6VT=vwv|2>L+U@
e<ccB?%2Qe_27GEa%754lc385*P!xa7Hjk{VfI<EHM#5>Rh=zC13iYL!P;YV*ABo9z`&Ekl;~Me`t1Ir*7*LQb6J5{i|PbV&M_#M
U0M8!cON3R3bB#6YnCa3eRU?fOq0Z&@`9}snf1$qvVi<AfXI0M{*;8Bm%5ciH};{;D*FW{ihQ67^xflUME#6bh|cjb1{a1K^<~c%
i~>2st>jx4&%2x!?k)GAj?OcQbZ-}+ecSW*@DeT{eeZO~G_$7$35|f>tGN({lIIzp@1l46s!>BZjP)3S<j>ke;}a_hVv4ft{6o?U
@~>88#oCD~1I(Zh+VF2tnK7si!j=d13q^uNJ(*I0S9%ocdSe4&2Bc1gS4kxLM*_sO`iX-{@uI#s=?FE~3slNsZL4){%${GJ=a>K2
e6akI&p)E{kAtrP-3g`|V@%g{Xf;mW>Yor6A=x>110=iHRjf4(c}D1d7Eg+^Rk})KAQSC6j2Bn}ZPF}Zp|K%EPJ}NT@3~*mw9$9w
i2xLNNIvEn1Z9?>%x`l>%YW^x#v70f7MazAF0`oh32HFo*Wr`Kz@#)kFk8l(JV$<W2F8UTPfy)X3(^bLvp;`3*515QH&@n9jj*4D
wxUHRVaBPK$Ts76QAyP;!Nwm)5d#9(hb-LCwF4qd#RPE_5RBv-X^d8T31$BTd9nMEc1zYKyuQign7glyj<c@^`9l(<b)}R_Hb&{5
YrLkRd7Z7jg0Gu9a2yy-_}vOsy>nRjgm2Zb%#gTz>08_e{P$wmt^7ka@*XwLot@?p&GG~`yv>8CC#2*OPjW!=b4!w<Hno_~9i)kg
QE7f^t=dcVSIb6eZB~-P-?Wr&2zNCkiy8-l1|8#0*(@^n1p+=yG;IEL?ftj@N{FfpvI$xuwF<AqOux+=&I1%D-Nn0zDlO2wjBEuE
&T2)KL?hwbmF{OFpyclht_}_v)2GRD)S~$1-*g?AYLvjEVV{%uqH6|T5c!MlIuu68?ayTHPDP3siBk%+vg~VST#u8goR^>iZHn$J
1D1v9Nyq5XDmM@pTmGPLKrd{}wtD~iWNSHUjJ?CV42x&mN{N}cj!qiAo+kGIhHbl|lMF{CSu8bQlh5t;wNI50V?*j5#uEH5)kURc
MgX%CiPO~Qgi&s!Ir<}J*m&Xh%fx*L!-Vm&R@tz23o(EW@+Dgy?%HA0WdL26bAfrY=2EOJ-T8c_?SAWyysWB6zfNSS(l{|B?^D4N
_nKzyo$Rd26$UFVoDLNQ*0L8z`bquX0{J&Zs&QR8`(uQrv?O*UpN%rqXtN9+b^;yaK%MEbF1t)*0fJgA?(^Gc@7{7Z!KSnSGXlCf
T><Hm$`aWDc?ta@L+Is?(mv35p}5&EEA%+>G7319h$MP)-0gERZPJy?EnOET&ItK@MZ4pH`iD@bEQ~oC7oCN!T8`Yn)9uPq@Ljo9
|F7GY3GFj!b&K@aDM<Uir(|Ax{Y^@_)i@DcD)O>lX|tWi2c{L@up7w)^2D5pM!E8DC62d_1FIreXHv^zboVKcuk$1rl*SdD-5To1
G|N_up%e<{t08|9r&suKJ}w~2roZ@bm_MX6dFZ#hE&kxv2Z1US3u!h&=7R*1Z3n&aq?C-}4fMsOa~oxYs>g=|D&_wI9^0SqNLe(0
ljsA2Y#r%24^P~@uDrBV*aC@HiUhi^=@q0d;)iu6jnt;@tENP<9^-%O`3lY?An(lg7fh_*+c-k6H-)EkU-Rj-{3Jwm_o>HlHisuT
fdE_vb!Mbr5e*~Apa`?pb1<5D_}n>%wjDPZOChqP{m=WelpA7FCYliAmRhS-CSN4;ej9g_#%t2vZ)RJiqeH5nv+q{23~tg!K=$P1
vOfr68~~cc2Tdm6--@W^2$5D2FtX%BM(%aTF~$)?qb#?vN5T=BL~{E~3lElw$Ne^JPbGPJzHVF7Sh<udlxOU){Rv3vEnTJw8AMP6
Q4=5@Rw|<jfZ7PN^%91rZm}nzoLncG`YIS&)_b_69ejrFuNS3ga>(&XwoH`%uHPu!_g2(!y$Bo@ptBdnp_f2%Z45KyIYl&qT=}8C
D7cbE+YY4PnKg7aYh`^KX>d?`xZW`{#2zD2*M99Da6GQ-fgx2}qDnS2*YMtjhAjgcd9};?`krJO_ait6F}x1oVzx;Gb(q1Z`N%Zb
kI3QYG!~J+KV^_Xm7y4g(ZTqh-UWw#h2I0z!bg-&mY@L)@o`?{+8=$^j<1=qI}xz8Jj)ir|3C>pk9o`3xB+p^6TAZRQ~Em73vkjG
B?AAqz{|k!GroUp^2~iE@Q~#AA9_Wq$xmSD0$Adb1dA-T@IW>Dc7YyCcO1PcvnoC$|F++ia9vXDScI&D=k+QhC(7TB7?dD}k;=+y
I>ZMgoC10?dLHN7Ll!bmhbCL&MYVB___$FQ6YIWgZ{&t}esfOrUZBfJW{~31*P}s>_P+NW`QdU2uY=`u%;=Y2GOXD0TIfaGIUzQ*
{n3lSJcjIVK;{IB1(0RAMWo99HjZV_jg~RdK$qHSQu&)cnldFiOu}`Q6eV^@obIk*H2a-B_M}n-qNd^^p8H5<{VRKC!)jZ;uw?Vq
c3zBxc~0cI_Ea8R?8!5S-=76iBm=tbyi4-FWZn6f(35IpLF6#s{geHjeQD0IaFr7Y7Wb)R6~tX4MO$xWJr#8ZmrW5Dm7W;FHCWio
cc}%OnszecE1h}}FO@`mA=0~LEY?lKj6Gygp&K-hgg=bkMu1(rrp|6>gyR=-Vyvv9p8i5-wqM`WNJBTincgPOKk$VvBzYk%&<s=$
pB3xa`|=}`v%*QEdu8W#*uE3$#a{m~xfb0Tfrxarq#MVQ9IRp?hcx!Q0^`N6bz#*vBV(3crasM#6nV@fAW`f%DL~bcbNfMZPD4ck
#vAoJ>V)Bq*S^n<fF2l@&3fzRP{90BU!?ki6UO~B*>F;^Q2(K@0qFpqUkG^I=}EDl9@RCMP@4vaoTw`@dN7YBOj0^1Bx@FSoD9jd
oWniGAAr8OV^ojOGroa+$n^jnXACvP!`InHlWlT-i0McBSHLk9v5{%rO?UFZt%{R2ub3M=5xYQ%`I_=HAqO*+M*Y!LxY420vmgU>
LB%CL!6+sM+gG49fc$y?rrXSV^}I2oe_sZ(?)c1?!O>oGkoNHk|FWC94J$#t0Q0NjrM!v}vA)??9%)JK(q6t7URVb*X6v{o*~tx{
Z;83bE4JSVD^x}OB8Pp{;QlW2aEb~T0@*fA(ahy|KAahj1K2_&B=}GvWtUN7aBm!08+C|iY}G|rpWeXKGhI`RxwUV70o`lag#ZFb
IRO|!zCwN1)RD39N~-+8U<7T;Ebqq30qGmqh-`mFgtfbmUEgclm^Q|a;pOWaLIb-ZZtO5E#)hzzhUsq%pY?<;%pA>$fz=3KSkpyO
@VoiDm5M$MWbBU4zr2UZjukiYNWV3TFS<5~xP5)luk;qZX>{lv6p{;2jRs)q7B<u#883oWn?FPSsjb><V2#HJ59sra-%Dal*a9D}
r;7sa^OC?fE5$d|iT$@HeT24N@NAw&C!?H~p@lXK?BKo2yAr|z`*@a7IU<<E3YaSr!76vL)8UYzli<KyXdNKTm@{(>z`C>RS%8Rb
r7KIjHZHCaB~d=3PAY7jO0_uwQwY5f5DF%?TjF<_e^G!g>2WSFA>QT^s5n$O-Nr=4be_lDn3=X+Um3|+!s>}mn(J$n@F5{JMOM9U
$&kPK)b2((0DufNs<=Wj>AZLSRNIsfs^s-AkBZSzL9Ac;11T5cR3}R-(3Y(p;Zke_lg=uU-X`A3QdsDiX~*Iu=q~~#Ly2f*%4F`T
{Vu1y2mv9awNKHmO~G33#H%=Sqp^>YAB#1aEM=F4U!dOqduAkTyD?ZIz>AQgPT?3I!KF<{VJZjnzoesC)dKZHqKYfn+W~~aa;Q*A
1&$(xNpdBtXp4WA9ij!VD?JW?lWvmqz{3=rdr&)94BUjAUzZQel1pZu9;7t<HT!36TQzO7*>DSjog^RM_cKzXalZc+4?T97=mhpx
JHjHH<bo!lC_H$JdD|HG7KIjZqtuijot36tQ6xcU_-zYfKBT!L$n91QPyov)|8J<_&HFg`S$_1Djf2CwKWi{YceAgNPzwr`Uz&<E
hC+j7ge^x0LkZkIZ`m8dB-0I1Y6T^l6<WdA`Vhvi?OB4mybp!Qa1)$nBl)V#(UYD95`3nN$sGYrR?O0&L0S*sz&>d$qSUnlJh?H>
=2LHNMD8hhVx*mlx1%Bo>C;4s<Up!R0yn__y4GdaaCmebS3VZ(1@F>cxWP;ycHFHaeY<mqrwqU?(ShPZos=6s{|U5|_H9z8V)8;Z
cOU(Q<bhcQU|4`E;AmdYl2;M_D^RFINqYGDxNz#w8P@63U$GhCTkcWwEyM2{nhY#`dP$CARh~%N>y>z-t<+#edK$}MI(_Ns^JygI
aKG_Lh^OvA;roqkUbddysq@SZ_l(nI9!?6O5SsUC6VF|^5n~PGJz))iM#%EqBrl*|&bd7wEZp^OBks&n#V`yp7i-kXe*A1HjW1VV
K|3Nc>e0kW=A%zlNgb)|kP)!j!r!Y(<5_25Ki^0I`jI513eN3b&HoH;EgxPRku}@Ri_I4(y&?NXO?CLvv3ky4z}rUuK|5e!pc^=M
fU@x&6G1<R2bZs<jS_vBQa|!X#X1|E|HXLAj&fmybl(~(B*Z{zFW<iHPk>-QDaVmb8>jC8r?*vPrqI6IxZz(w5q~WNq;I<&f_kxx
sK1w7L#>;M`@W$KZt09eh3F^m-yFkXP!}P7<gYDdZI5;bj@QtJK9(5}?F{QQ-5dmXLoNhsWXllB2FA4&h2;=zZv?*7u(JKwG;2I#
Cs(@PB1l5p9r?jwCgrE<jE>!)0CFgy3EE&wc_S`w&_dRUb+pp$QEv3jyglhgywA!kx7-s}mk}wYt#EMo4kW`Xk^|Ns5A(Xx3s7l;
6jQ_{LH9hdw}LJLJDpQol<A%BOy^Q1;JR6=P}w3ZB%<reLliTwQXbLoExOke`1chMeBZht_?i`!k}fB~v@k3<&7rcCK}qq|1Ahe-
h)aWLq(0TZp_&RdUGUq=bnu$LT4d-^moyiss&m%O4aolm79H!8q<CJr(GBYXi*n|ZMG4olf#_OVO-bF|?InH6le1jpbz?ZY;QPBV
NBAHzofuc5PiiHFo_BbwAgWcfrsL0MqSV$zuLCJbs>NiI<Hi))@Lv(1oAkO#LI0*`b%y=A&E844fQ1LA0}NGvT`rnGYP(oI39)Nx
O{*w_QwAjKT#CYd-<cyx0a;hq0}xZz%Ue==jq9=f(S0fFdl9L!@)^KrX9Z}n1Yv{zOw)Y2&fGVCp`hG6C!YD=jW=*90#lyVc;^Q+
!TXz__F#GgCvu}vZ)|-~jmLIG`@Qwj&U2+=+o5AD<9huqHKRzF5I#&wPdy@?o_}x;XaD>zhfy$sKz9k*DY!d5dk2$y;Yu40zu3O7
afc+Vy(c>VG@!v6EFnhXL@<!hh0Q<v!|ecde~U-7Zg>dZ#AC!_I97WeL{$O7(N_w_ng)oUl~ESUV;j(VkMMsCVpOcJ!*7-#r3cV*
Ih7Qgx%S)LJA%;~_PMgbggl|YuX%XZ=NMZTGr7hAW;eb_VtyEDsv*%hZxtigTSWb!93ceCc!J?`UcWrP^{WVz>{YH$;^u6sQ(PM~
TcQzqxC3=Au}%({VYjJNZU*5n!&iko!;<1kwA2sKef5$yA+h<tmjDP$cp^1o7|(v#nL}~R-SEEbx^5=g$nn8{V2;c_{0%hT;~<c(
dg~YQ;6nCOU_LmSEcZ@Xy^MTH=E$*j1H&AQfg!^TtS-W_r6c|34oO0`4Nk8D7HT8aaHx9y6qvvCDP#QPU^07kTb$pXr=I`nR7lr|
5;z;&7*|<QeE5jRZJ&@#Z0)twO+Pjjm>|EL-9&8#glRciu|IxvE!K#LN}-KUR8QCoA-7Cmv=MeL?b6BFzCE75y1dihCoZ9xTXKo<
J~347n!Yh!=53xmmWN2Lji0l#zNsl_3sOT&e91+bwUzf4=E(|&cjYm$+Pq2Bb76|7dOLs*x=Gt36F8Um36RobbqK|*-;KBs(~<M8
nrxczKZ#9E%s{XOi#0r!3~l+^<s0ckfJBj6TOTT+1ua&z@ZC1mSp!}XNfGzyTN#cBolojwO4KUAw`ln&n6SICa}8n2HO7Y#(IXvV
7xKdM>|kDo7Gg`?NB9^m6oXoY@x_gWw%XtlU{xiic?3E~Vv6Qbi{1mQ+O0L1+IQ0&u$L0-*|wanb0HE@3(bm)-9+6oZ(SsNkQ_jb
n$dzvFmz0W;s-rrM0TEHmv6K%eYn6Si3n_=m^Rm=!d1WCjf!5CDcaf9GpsimkIS{*SPJe}$in(`WnR#{w05s1?ct!X4~?Zj?NbJr
L0}RBW0GKe=z~;{&*#f}_N3LrEe^S|;>m-D+zRmJ9l2WDv+jI!tCkygBl2HTnC>G33%T3QuXwD8Mxio%2t$N9<ZJ#N<g@Ur3#W_-
vro#s@2V+=43;!HhrLfowhl}Nm%&r=UuV=DEn>s)xgP?bm;iW+!EEAe)DIjMf|DTzetyg#4Mc>?35SUi<I{EXqy}Cs`oc4WF|ax<
IUUO+3h$Zqo_ZGxC!W1=qB&>F>DDz&<4E&L(el-MDjRv+e!i*WvWEmSs_fnK*B(Dbm7F*dXPT0QL?JGL>@QX_z*pj*#U4+t@=7IX
UMbSRIGoEpJ3Dofv}w(B?&z=m*yfw#KeJl-6otW6>C~5!>nPNbf)7M&?7ZW6s-ZJZu$3n;wEQ_9`T+{|dy?#yFqG5)*WU3w5;3a@
x{t%HU`K5sq;c34v}IoM<%(#{aK;f)$s926S%n!K1Sil9TCT|0$asQTUDrn^TGl7Lu_|Tg&&*>iCum`(83()2I00_Z=P)R=rWyTh
%S&H2Sf${*{HY8wG~4Dj-hQnW{5v4r+F^TG|A37RSL!HZQX@>gzNyfs{+gu}@=q7IM;U9!VH5*_xK0-ddzYtMP*>Jkr(Mj`83Q`u
szPUt6y>%iGqaELsIl1MIPCL-avVe%;g`{P`cL0s)*)Z;QxuA)V(wa$V-z;7Jo~svkQFLS@4uh%=l)XBFN~(My?Sl0b?-=~gvCB3
78~a{;y@JiF<$yGElnm9N?YhsK_vQ~f0-ZP-c5le2ZBnxJTuwwTg7t`aNZtRoi$e+dwA)d;cg@|X8LaHR)EZB=yH~uW`A0}(wbgv
=|Rb~JA-v%h`x%6*VTt18OgX@@&%ZNRdvM5We+a@WG|oSbD-o!{3n|P-`0&!i_QR<_}if8+(=#ieqsuL7~sV?7Y>NC;%igev;EN;
e}a@5rRa5TCu^u}x2DrNICm8{^VuW~s!Nd_dfxgN;m9)EL!EXVWZ2exq4e3gI6hPP3RrSkg|(yI3cg3oHy6iKEmeeJ_hLmr58=}&
r9`nAm6wXy-F1gwYe@iFqwrS8#!`Ehtn*$<&kRvNem9;Al{R>Q1RHWlgxK3|Z_bBcn8P2x#tDX9F;`SC7eM9z&W8tzTQLfvW9Fly
-B+d1ZpQ+=*}0*CBkS(B0BdBt>#<q1+O^VEt3s;S2Jcxwfg@ldfiaEuNiju36!>Yct(InmJu77cLEzO~@<`}80Ej(_<ezSr-UO~H
0Wxz3IsQZR_1mc&0pE@?01<nmLsA$ggSUU6d2tR)-`gViqi6I<sK9aSoDvO&TEt1<w%RtPMC7jAaH_|V6{8Y*LOITbTm`e53ejvj
u#3>kWsZP)U-DwODexjjJ3IkC#H**&_a)knN(Zk<AWL;1J#*&|TxfBSfF`jGnhVbx(JN#rsJnTCbO<qfi8PU9inQQm_JeRLNPg_B
xkn>t7mrl;>d#_O!paI^w6?b@?sxYn11FIeZ{>gm{e@>@4G8yXFg>zQZf>M2pddD8!iu6{BX(43JFWiaKC5V>0R$gRVWxW~fMJrk
GeTmPlcj*%f`yuiaz;P3fVdSa&?n@_UkSkvOh^g(y5DjOiTl^2cuzC^pDGf7xFbGXy<Q;XdXrqu5=;O(KyU(3^U@$JxSVwf!+$6E
8A1W(&%^4L<nP5D^LsDXA$!JXu5I3>;n=#@e(QLpcE?}so<V2b%CqTUoGFQ>p{fabxH0$?^$29}rebZgmZg2@U|0+DaIG1ac*^Ac
$Zi2JDmVs4Orv6}xbX@-yqRy50>7B^2%$l8V$^)B9CNLlp1%HqKW+F6WhPzF<QZ2l+yabn_<(eW^QUZ;(<@!!pg&lfzuV>vl4UyD
ID5DhiD^J{rVfWuCj#5s#a~HCzALmhey?|dmx03-P(R&K$Xz>5P*9%-`Sxm=$i>@-rhg|IimJb6Ht4XkLxr?}ebk5;oyXPXzUFFq
*$m`+gdsohv!PE5Opq$`mU$y_;aysy2RcWbbdUGQbrhPY=RlwEsJXd&P|mw3p?Ps@S>X?y?F9ehweqY!DeLuNT?Pbtl&Lm?sv5BO
7m{3Ej>3y7uFj4^;rfFCP#4ZZnUAM>lqVhe@D?A9T7os_@Z??DuZ!(KGW~T0o>baWW#r%D-|lFX@I5#sAhS+!$o5l>s7!BPinn_8
2JQ%;9A!ScL6%2w`gWM`+~Wjcx4v`K)41!_joC_AY>bR=^t(lWbajX|f|j_8JW7a0z1Yu>dPV)#Q-Kg?jfn?r^-ifHnGAf|Yp|A|
6<sbZ%I_5S#UTAy+3z3iW3mAWoI*!M0<l<a*YEL6Ma&jwKTVLtM=i$jOC${vCzoj4|NWl<RRH2~B~oH}h`#pFD`)(qTBBXTTx@o9
-=qs+CkM#L7H*6Nn)l-8(jvOr%<Asiw>%|eN*Wz|f6vp1^0=kRbF`^0Rv|6vErhdHXrq2WDn7y|cuXnsnLpVnr(@=ocA96B|MM#+
kB)`b;E4z5XI9z(d%&1<4X`!2`EeIHIa@+T+j0vZyUhTcMFC_JDzKGL2f!Wq+e3WW3|_RPow`}0^It9Qi?Hw7@n;oF9pZ-z0U^G@
l0hYLo$gd}FTrSwj&{d#l>TGOD0OwYf>-ZSaGFqMIfR-Nf)1D5DzE&wpMh>U$glUfW_Hslk0j`<v_?B{*Tw|tiy&(tY^7Zk#OD{e
FZ{yq^ns#IiD>^iw(qXS2m0#Pu<YV5e^WCBq&YK1lBx9w#Ke^%VwuQ0=*gJBl-$mS@}^E>Qgf!@jmH$xy5S?gjdnIyklrHXpr^vl
dRBItghvHB6=`{2K1D9~k;Dq7!RFz89He#e>zq=9Of(Cj<uV1tK(U%>{t(3G=KCORJk2=YmqJ4ALFK@G<3>hPE!KQob(qdIT1q~?
hE?^IKC}Neu*I&YbHSCa7W8tx#7fiW<g2z&H^Dvb?Bj=k&F_<QXiyftBDkJN2X>Vb%U$}ZwnO~UEnv!*3+;~FU7S8ACH3q4DpYzz
;(!G4H0J}SyPBO)vb^Uj-FitM!(6z4Mz~27R~pv)n2@ww%+eH=lG@cyK~&*4m~+DDZd;ki2>yP_K*j`3Bk@UZPLA=EG5W4Qr}~2@
YUk`rQL+ya_CjZdn7qLbZ_(CEe*meNU@S;c$zd$eLftKSMe6!A)}FR_0$KC&N7al-@!{DJ)!cGxy=;@j$z2HM5D;3StArT?&Hthj
#`sQ}NCW;Ho$@_l%{%{XLoe;8A;F%DT}}tKsd_j{^h7#o^Y&ktknGD`--|6rhsi$`qnd#U=p)JpH=3RKLDCUF0hYRtvhtTH?4hH$
ZZxclBB%LgvY=N*lxnc>wC0_AzcF9wlfF73bW-Khw7*xm&zD@nnj={uc@>4fLt1UNS&N85*f(kEn*pB*+YkSw!6A2Cdf+x?;7#;G
bxHiB0A>C2>ZU|)G@c-ETShz<z$l>1P2KHu#<#PUZKM;jGyHZkaS_5A54Rd=w!1Kk=h^)*qhoJ!{CN+ki-(ezfY(={o4iEgwN0a7
$DFB<CAVf@N)nEuJ7HRs$BxH6Gp0!b4W6C(pXG-8RvT;G!Vp5*1ou>wX`@KH)-rZU^$SAUdY7lHBX82l9zs=7l(W<1_0tVb+q2wH
y_9tKA_Q>N2<-62A@%SH`XTZV#+RYLp$7B7O<Kyhzsn#Pc}Fttzb_C^dWt$^zN_hmXFhJwTY=2V9CNLS;ZNE4xlk+&Ir@>|mwjo7
5kpQ+RR@y}U|H5tU%w{8KLBjHq`%Zle)6x$s~*X!<DFiyu~WFY=n!)i_7Yi-@G@N$1r&$@=EvJIA7$Nbdb(`c$HKZcd;yu`(iUg?
i?mNnB`*C8GZQxaUNK%A^;%(sxYXn}q0X2C<x8_TYgcTQAO@+~xLm5+t!sb^mQT?V!@`6qd@wATnQ}V$ZPaMG7+^KX8xw}qd3um0
2F{O5*t|SI?xlajRC$2Mce{g2m4hF%Z5Ni1;KFvi++eUR<!@ayxjm~I{jXg0N40Bp?@DoDQk11-iOyF#mPs5!iDA|==O@dGc-u2o
pH-><%fF&2-<p4sAV6VxV6H^RI=hnin8+&8S+tI!*|lvsXJ(9+>Ht6MYEl7(X<~vf|4lb?PE-oY<@6x`-pxR_AV-N#&$GtHq;-Mm
r%2&HT{OE_-gdj3i<&3n^_0(%yQVPuh0c}q6WenXyNIs}_!vXE>T{$TM*O}Ljm^G0aqQCvd~KP|TYrT5*aLSim7a65U)7I%ki5=q
9nN+AnJhOVK>1X^;s7=6^hHq@5|-hp@mWH-c<Q)$5SGTD6@!)Xm8YBPHW{(`If0%0kivp&Jyx)colQ)l^^h<-M7+YSgZ@(~a)RN!
XA^d^Qe(8~#va6=!X75}a`ia{pWm=mB8LLN;cJ0%hz&(Xp90`Fjad5rD<~d~HYcmsF=53qcO6N*Ln{huIh7TEhQ9Z!WSK}N?*Ga+
s_J~rz*mtTC}P^&fm1U2jC|w(Ndh_J$GeaG!w|l}F!V&^^SQVqkU-S>`aF8|RPJgQp;<xT8y9OyiBB%a+Jtvso(B_ckkG1BnV3tR
;QmYI+*(g_hmv%E4020NEyOkkGfZTBa8Z4QI2BhpKXa1IoI30G^d~TbV<R1xlDGWm$CS5vRn5g|VZ?oXtCd%y=vMTHI|5L73+|ju
WZtfMuKt^bn-N4JbBY$hG(wWIPSC%>7ad&zuXk@m7BZ=sh|mve?vc$yA8*Y0vxflK`}@g&K5#*J1k#Y3p><B|tIx;uk#k-<Ol5sZ
ebK@gs7MNW%c8uOs$l-jy08$K@&N4StLrLy0>@aGgKHArf;^=lP<tX6pDAC*As`xir6(q(0nAlTpX%uswB)5lsqKG-CHR5Q{YURo
>x7U_%p!cDXRJ8_&_QkDya1JpbH2S8U(Xc!5&7g<Ka*7Na6ny8Z>ZxoZWsk%^omw&h?`eYZ_(Y|d^Db7U3pD(@GJcOTNv*?->`=~
8VJ2}C%&90(ODSXY350K&~CR)xo}Oc<@Ua#^caQ7ve{YlLN#FzrP&WX)e)=-u5*VpnkpdH?3c`au`2Ygm2d_y%*1S=CY;>hf|3C8
6?vS<SK^Qt!XGR2=3K@K6-OU{5Iv=6l{xo(B;UNi?W8$z9Iw_=ktM{ygDfV&-30ZXRSNR4W6`ODAOR=16ZSvK&VL0xsl96lj`xUr
ba3tH4qlC1bZ9edlGlZFM*2`s4_w{13v6}xstHR&xzBNm6~9%>{sNw5R0p>huhk<kP$&e@vA@H0a^4MTN>}N}rc04jS&b9`?2fJy
epdbl?laT)&FIJE56}z}1p)g*S->litc+VWL@*Sn1yp2oHo6J|&AeLT3_ER*z-m4Hbl<17;#C&AXw}d@u+GESiu`i3=gB>H;+3En
>vO21Ean&0MOPmb$WgOz(hES5v1FVvR^Z^I&HBEwi2ZfXHhuxT+7g#jGw%7(vD`-S)(kko1_+t!IaRk5an4cqWPVJ%V-7;PN}>;V
CqSw(QwCuG9BwuhL{e%|B@#(0H%~om8YhCiy15gFQ53)MN3)sHR?Fak?<rQ6v^m{9z8n}$9a!P$iHH`AQpwO)FRp1b#veziA8}2!
7@2kXWpSDOfNiEi|I729#xX+vwh7+_98-b+A&3j%yBa|}AY=rZIks$n1h6OXiYl~Mw6l5_SllUW$DKW)V7!IO8>|BIT>bg|#?q;<
MsmSPzIBKQw_PZ2R5lT*yTP+A;_Nur6KJi>dTD9A_Z=_$dC3`hy=X1gxSPBNGp^`JLzf3;1k5S&U_PR;?lVij!DGbXY7D#GDZ-rR
HB^x-^c-@#!UGX==QzT*o5LG7>y*3cFIf2`JI)~JAqwxfp7$<(&iCXf2hcu1%;Z=^yY>N7^lP;U9Kct8NSS1HKc9aAHFJD$oZj!^
TS-Ne!+n}U*#Nd~RK_17h`_eI!@-b4Iar2XI{A(cefdV-nBQK5m!}LBZq1q7kw0>q)Yb@%gr#2}Wy@h>YJzWqq;c=OMhTXIvZ;NT
m%+~XHn&ETy2iUlcSVgS+%^maOO`*Ex?Ffvj(?40>y8#ZdMWage#8p0^g}y(7cunoVMFi{stL?Yv*C+A4GDyJo*;D*0JikC3r!hw
A{={}N6NVoeVZ9C?I@Z=>rXTz$+Q*i)HeBcAnvjG4TnM?uT?<#qA<Hy4I0(#M#%RAPCly2>nqM9IS|5qYm((2jq`_+K^@T|?{I{+
OrA`op$3l<%C3n$ioOW1hKu=1<D<Nc9g{r~<|gA#Y9!IURdS6dcs7iE-mnzck*Xj;qeMBy#2OUu!7AR_)SnLOM*&F*q)_LCnl|ky
|9VaUs%VgpA7!QWifG_5qeeTJ-GJc?Wt}55F8;fV>|?lj?aRGnCtdH);z%l?*oTPyI|EDV?cQHDah~={H-)x~jyHNBB)N)HTEG@7
q)vF|o4{g_(C3I_sD$abQGTm!;OJBc1bOi;?1-;sX@M!WPMx}QRxSa&JXfwP*2Hvo&qsB8gXc(Bd1npN?|R)P-z^4w4UX}Ke~n_)
^Z`(>2`aXhJrUq|QnV_e=6qCbMaiK-e@FOa!GE={&(Hv;25q48>I|(|^4sypF#NQ-@(f1%G)<-cep29ylXHqw3a1<xPUG^8)X+KC
d;f}rCaphQ4N1x1_*{1r93y0}NxIZuGuf(|VA1Lg6Rq{_4-2uJ=!mlhM_^B+vBF(kVMs1>{o6w49l5f6?H*Nc=T)O9ADp<KKGx?_
*;kiLI%Dts1Lf^Ddx~__$kA!%=%^R^<qe|!Ez5)rv)h5p@h$t{u=O;A168+Huq{EXRjPVLk}h(B#zB&R#lhP#Me*SK5P3sr|0C_p
q$P&Vyalu}sxD^iL|saiVKlrLIe8C4eDf>Eva9jZwx%fC%y%I|M4qo40XweIO}jvzh#>9&JrD1XmNJvB6Q?786O;}aF(QmciBaiD
ou!m(g@=>6MHvM=4ju-{u=zFE1h%0#j5pnAQ*xhY5yWq~+>qGYa@Y;$q8~v28Jj-#=Jm#&h$@U>x;C<2#gY*?g=8q2=4z5C7kg4;
!P@<izrz>Kba^vs{5E6YykdHa#&yrhLhg9%iNk(x+sBYvKWxK3L?`*?oJl8>Z7T%XEtN-f47&`j$pf`81$-WBO;S6UVkf(K?2s*!
g6Fi>^U&+8!U3NQSi7?<_|WRc(!V?SI(=u3w$T2E7i#?AhYN-$#{x(U8coT5%`nT7b}{0YB<b!DOn@3yXW`DW|7a9Yvh_y^p3lD(
D^%-|=x2PQO9@1qm_e@7poF~LA?nv`>6xFj-t^kms#c8LsCpObz%X@B#QZ5raF=UrB<cWgL{JzZ5;jEmZIekIp^|l>VZ`Mc0yB(s
g!_ls{7bgjpR#6l_jx-=;p;5Bb|IG{M2BH~QmDMQw(!HuGSikq%}sj%d{V!uY__<<GM@@&EbQKD`k0x;qQ2TLT}Y4*L3$ntn};GR
`-l5*x`IuGRx1vf@KnK48}7B4qGCy*S8Vx|UeCy7*8+8Q2eiZp_KOgKQqueI-tGqz#OqC{bpI!>qx@}qJ37$SL@_1doD0PsXPwJc
HS*5`ohUv@)PNDLm#=3i_d95={#4>S5tLhlZ7IJ{BiT~Y@;yA>UuoJTH11Oe@9o`*3tg8Kj<i38gHd4J=bKIG^0BD<`!s$<aSjm$
Ncjb0>J?gr-i-qN7}9BQeU?~-aXx7xU(tjmzJDPIb)f=HKsEQ^Wjgz@l90S@F*fnS5LmjAah1;2M>Qb1r=I|n#V!44iWO*6O=L@1
(gOe|o5H5qKUF_?=FtpkQ8^R0ar?@&yf+O;1xT|EO{If8ITwWkXQHqbg0bZ50MuTjAzRgIQtf#F|E$yM=s#K+vvCeqnI|0|gYa+)
=CIN&Co)n^&5%+;EfbXnB0-F7Af5)no5Pf^KVG)h=-VryDXv$r;pv+dcC~et$y$n--4+rq6zrz(GVx~#(iG3ZHOJfJAkaS~sAOWb
!Ex%6xd$RoA!(W#rPq+YZ_P7*q)Q;1X&r^3m6-;4rtV;hX5g{~)lU_B?uRrdD@D)E$Eo#BJ1bB=u=ucEy){n0hyHPw1h>nfURhZI
5<u{r;bJ0mP8TT=iE{m2>c!ix8dee~XO}^Xc72(LhbikM7B5U>=NK^)d;}ccwX1SSXvP`?^*8_eUw(|WIbjLjZ|zbn8JOeAd>y-B
P76Zk&OD;Q#RpUAu9yndYtt5$3&F5s&!Vlki^@qA1A;B>+{(&XszeYtNpSslLt^D$k|72>S=pLSI(a%)X%jLo!m=oKR?{_&yzYJ-
3=QkMcnzSm)&<9g^nOj^=)a=oJMav$GzT=vV-y(p!^Hm;b;3ha>pb10f(uuBCySbguW?C)d-+!&=hJ-=n6!%9s}8i%N*NSe(;t?x
k*Z$6VS=5J$v(43ND~wB!qkn<LrP3BX-kie0cKYw-%9!I?`K3gCm1A55W?1{oba}oS1J6dCbyl__Vg82H$2@|Ye-ITNIiKjTB_gE
4%h;|91<@PB&k!V|CkhW2iDrW*jv=)h-`9rpvj(?^qx%|bu)DK!#0xm`&IoKRI}2r3ea4HkP55qrJO*<Tffrid((bD;&_>pNLYVW
N=*IcM`O^&$`>oK6eDU8YeO`<PqiC_56`#AdAWfTJEnn%$rxzn#QrcWa4OEBK36qpAaU(0wY!g19oqdCB%_OCw_I#t)FdrzMsjPH
#ZJe9Yeg$rLW*Tq?2k~XS~i-}X8oTjFMIq#0k>1wvLt(yhAs5nU|KVId4`n*Y2xx`{M%7_!RQmvB+rsO>K#Re^jtVRaJnpvibeN^
so_(&u_o2NvcYJngNZ9g197M8_I`4|VWATUmeE<W{JEWi>f?tiZpp&S_`oa$y8g1X7`T6j#r6{t4GvEI5&<;f&g5;>4pz1oaIKuu
yHlv=rDe15vNTpMZ5`8Gm+o4(KJqNS?lEbU@aYFdjZgndh?r*sZN&5R46}?OBOZa(K*h>EHSxjY3Ipm^WYq9#`x5#p1uS1INpGNZ
W)i8>mEfap*pbA7ZE+p9(=^~gg%=>q(51*L(6bQ3YwXPOE>|EE3t{^s+XP;s(kmW~G&r9Z5L!w32<4%#j=_4iqVf|8B5Z@fp*T4d
gl`D*@bx9c+4FzbW@d(U8-Vh%F6Y@?%)%a>p-rHxULwM6qJAsj*%7O%{5yld>7fF>+Pv49veP{2{SH?piVaCJww*dkyec>WJT>Xe
m`Y3<*^PM2;v$b=WmL5SHlL{%<#KVk3~c4(@N1E=H~oM{Q;L>5h?W^>aRNRN6*B<Uhk&e>b<>n-Hd+T7pIPcOP!}R1^NA^V@sHja
td;SHz><|HFea-vd(*HD)0L8M{PMo~BzK(9q=d0HKM~P~-mKD}W89?B+qDhbjzD2F;e_&&76fC!3oKI%JB)W$DzrtrCl2$Om*&0Z
wd^F1D}{4wm2gQHw;j2~#kn^E{K;Z=nBt()F+bl8AddN~b&$*f*SZSGk7n?K5+f45RStx|_dp41uVhC;xOZmIYM@n@Go`uFqJWES
xsL7BCINpC&F`n38M8k>@UH)SpuEZ+3GphFjtKOPa{YNTqA)kn7u2N&CTS9fM+P{#Ocr1T`E)em#9b$pPWt<&e1h`m$(Vo+#t|E6
j8nQ5XViYFBp|T}{_a-Tpm_C3-WR1lAiZoGTZ6M6Og0$uP=^HOE~VcKkz46E7Ft&1`S!t4(<k<7zShb~Cxv}4<?~Ld#PalY0AJ;^
jwRU1AeIYe`Q@XNr}z!TS#2sS^@oKB%$)Hl8udn#ea?PO$TOL96Uc`#V}I<s(mc-~>+3M|5V2fEvNIDY#2z~p8Y?fO*Y?5J!w{wz
n-!u-v{ZZ|^w=jZX`MkgiXYVjw-1)aArw(L)Vwn4z~*Gf@L~ISc=KZqS|ig5K204*4}lkjJL04G$og5X<{5M}d|jdPx(ll&U*huA
)n5437nu9B2ko}tCeqN3+wj89D`+W><eDN;aCprs1PvF@Iqzm^zVzAy^>I-f*;bEU<^)))kR+mvYVhOv@qhQ>qbP^&btWEA)JVa+
I}jrG&ioVs^R=3eK{wcWi^iBx<OpOVwuHQs)!OdbAtBG^C*X>}FgAbAtrAzct=UpcY}_oCdg#x1QFmh@z)KSTH$0wgbq=wB_%Pw+
)qMeU8~OI7L>((C$QQ|FEX<aD^F?lB2)Q`qL_}<9YYA*vB+-cAFEXiXHbG@V-6c65myG$-TM%`QjU=u27-|lSm=9A}OvJjIU&2F7
S&{yLG4i2Fp_Crkokl;;TkIFe2Qh-Tc=>1e!_8!ZG*U?g7SrC-sdH&WjmDNLK7Z5CD{$2^QV=0Xw|3)UQ|j+vHAGXx;Nv}BHKgZM
Tc2ryrutvgzmvn5gaxOgFh-CIW8d0;VI<{ZHO~;|mdCFh5#atW0#@0r!@O2)6D{%xsQHS;QN@kj;YzLp&hT#I&ezPX{!w=8y?%ZD
?V=W<=jm@rPCc@Wd;+!Q%?neo*M&8Ky0@-ZnpmC@&#t6<cM#g?h@5LX$0q<lNFSV{N+ta2)j!vebvRY$Nt~Xe?DkgI7{F%p${K@7
RiltpDh7Wrd{F7W)$rUB8On!vWR)K@=Ao#H_TYyA>4G+so>R3eS4LGe5#>MIoLTSD7v_PhZj(E6C3RmGeKgo!<dY(n(ko%7MscTO
OCf=heAqFMA`rWQvXYoPxlt_q77(18{W4Z`@w5MzAXe-QKbx{|*W3Nd*&|%HtokH-SsJ?gXAof^^;*%L167e;LOl=w!eo;fkf(c9
?0@=V6j7U74}baM_%g)g*$tc*$;>BpL&J3}Gvjg%An`SVRO{wQ6Tl8eNIQ}`9Hr-twyrhDnuYjcqPVgWtvQjcr+CWCF(SC&ew<tv
TQWT4L<X<YZWO`pUNI4N>25j7?z?ARIE95DAkgOU9y*P$pShq+O$G-orE|_tD0fSFVhQM2!ea-4SwMPuyW1>W%-ZCc(|hT)bYkKM
k*oTM4UMZ*X)}S(YN@{CGy80xYOr*R4~_eKEuvDx%w&RZFa0*^qa#N)++Wf{!3F4Y?avwNB5`70#JTMqpnQ!3`yA|%WWb(vYS*+A
dmFJutw_hnK^UHkK>1GatUx#;N4;!RjFcT;#-K1n_V5B!*42a!*!$bSjxMSz3Zx(g)9@tLj?#}SphHA#uMmxWtU%vGRVNJz$djds
d1V;XaW4@Wrg{NYkAI53ScQiezLcG;C^6ZMki;&-JcbLbGB}8#V@P-p3H-|;rCKRIYuuDOf1q3OzWAo49+di4508P*s3Rs7PQmni
oHJ_4G$+cAvK|5@_AFZDNO-fm;T8&0$9GN)f9`TfTIOqM%t4zx9u$wjFPG=HQAYuRB8?b6Z-~+%JDTp&HT!dW1GR;<rK(#1%ms9Z
S{dm8x9>W#LB#c4PX4Fc_ScWk2hU=UaMdIRh~*4SL39%@uq>J;a0}GHhSxnd0l{pZwy}8dO41oU2ATh<h#M1vI%ui;fF)LxxsW^O
gJ4=qg9A7-0}_IT>OTo;bf`pzng#dvYQh>fBk46ngc`NcAmKY_jo{JRFm+f+X71>do0iatg2`NSr$Iakdd)7@O#yVhB||5<I}_f}
UV0bY#7FF_TcXRQ2mWl|Q&XJc&@y6Gx2R(TQ9}g;J$Pm4jB<A$uA3aD8N&m1T;&#n@+?;U)B3&hp?pRaJ^nf!99UrusX;Ui!x29S
J8R#vPXt`Rn#;_3xA{&b!<<s)B+#ONu#b#&;t@JqO1Y-$6tF|W&v}QLWt5m2QTt?HcZwbs{GO=f;X64iaY>%S2pFEWUS{z6=k8HI
4N}c^61GF~SpiPTQ|T`U#(L72aRF97QVfm<poY}&e==Y9+3{87$@Vu=-)PgpC6d_Boa!)&xtbg7Q)0iEBHUk$7!p+Q_}xS{Xw1Rf
Hh(K-RvQm$UD3-dU5J8(HnIb$uaK@SC4Xe<x&_0FS|p0mqqGVzQUU}eNm`RlG=TbvVOwDf+L9R3GEZG}o>XR3Ds3OAp!u#K#Buki
rsvmyA`r}Qi^3N|Yq^ageKy8|MM$>yG_bY-Hd_swK9xu|+IB3K0dPX=t`v2K`=q{H=p#BTL3V5~@!cv-4E!}SLHA00%3I=wzv0WF
DZsp4#(rS^4bQ2ESdi4L6)SbIXOF`Viu?Q>*tyQ$-bA%M6i&D0k9pI`9?<Jr^#F$obnNa82iXYgpUChxs~VtjD%V7P$RT*+wt)U>
F1Su9&ISq7C7^L3sBb0(jzuw5jQ`m^K0?De?^kT!O1(3BTj53%onIQ!GPU;l)J_DqWqm(ISFRN<J}I6qgV+=w1JNvF^`38zDyP25
>D<8!Cwun7VOQ)}L!yEQ$HRbUyiPKD?T4{HL+*z!m7**hyS!0neGWuGNsDX28?e-aU*yR-rX@^$^C7afW1~|RB#J6~JJ8hq40%QM
Id$ygpSzf>3Y}PMhGL*QM6xhlmL-_3xD$2a>Z3QICSR(x+K~~z9b3PjDz<!gP$@jg4k!=|+>3M8<A(@lug1P}Wk~B^#A*gOtZpVn
<tb4<6iqD95Pf6ZKrAAsZUQMJGT_;gcMD#K{~=jn&TjO5TCqsr$EVRg8n&6QyT+_RFnW(IWH6pBUF6j@<B*%hO;(BR2NJ)CFFHIf
8qgC!`5T{BmOTsZxetvW@rrdwrWBFf>iys=nm}@piz%#R1NUF6wa*PJ*0R&Q3pDfY)#<I}bAG|-RihF9B|EYa!3kG5QyK=oocr0;
3t<0szqkx7%a>cyF_;3kKW#J^$e0BPt-UAj!yn;aKlxhdi&fi#A!vIf!MS#$O@GZ{-X|7=KcF3Du+!<%3ddf(v1&{No96b9ukhaS
aDzyOQf%|r3JV`g5>dkHmd{O3m2Cs~0YcA!Zoa0#w%P(Qkpf^u;jG-Mh9w<{^Nvf1jKW@^m{8BQGe4+zOUUDn=Ds`2K)mSXu-bXT
2!S}NeOv=gpJyZ+1*|la;wFi9xIDBDmzey&TmP^=;1tZ<9y1k~(>B`kGw2e-Yc10piQ25p6nJyQ4(W9}X>E&mMMD9WAD^qeQ6D@<
0}jl+dtCI6v9Z4(Pz?cHOcm~wAtDi3h0h2<=#H<C;9i#(lvH`@f`v>2V#qIh5ZyD_q7W3kp-Ci(6c;T@^n1j0%H33gzrK7S-4AYH
)R0dG^+iBcB*W_z9yqFNOrRqZ-5R?>Zrn7l!R?`C9DSZ-WnN{*W84}D*OfXQfoXMke_({D?^I3`l|7DEa!~Hv)Ww@oL7ZxVG+7DG
G%d6*Iz?E~+q?u6^8*kDFMoO(pap>WqfhQT0!XHN;vd_p4mu~&ElQ37ep+D1CbehsIb762r2y&0OW>!%bY~L$Xd|Wc1?&3qb9`X*
tWy?vXu>%E2?11|nYc0mo#%0)9V!{|WtRu9_y7b~J>6Ci1i-lKIx<lQQO0aY@$NHT`Kx&7a>$DooK~-CXU4qzbP9#QS&Q(S+o2uN
N7UIq(=Yr#nAYh~RjMqSq3+=Tj|g4%G1j<f$cR1Vl^cB^Hw=4^%}%MISSJ7WJ84%bBnvYLZ2CvtPm-8IsKBqwMiEqfLH;R?<p6-Z
0`;CWQLcEsy)WIutX;82@=AYSpx=8I2bXxHx%z^Rx4NszAa1#tyrBz=YQla=VR`aEY#IvdG2oIewql)g0Oyh>mSz|$B8Mheir+EZ
Bcg-m^V#rZLrs{#0_QS^t2-0|VXkCLy@6gUH*+(%(}owe4VVE(OikAc)B4aV*OIX|xZZxUhP0k=9GA=F;xDro?`!M`Gz7gUhaZ+@
N{JBq=O|dO2nGI&|22x1?LXjD0=W?Djx;P}v_13Yes$`n=w**sIt+7^LP9-tga(XQ=KZh%>+cXeOOpepK`~o(;6DP~R%;{}5(CT#
Cf>KmFE!wb+V7k(#XG(cd5M>mg3jS;>88{PDK2&Od#d+!VqU@dRa-#HT)j@oe??Tr;NsaZycCBDrA!i3+JZ$9a@}CUwC=XYKFQWR
Y8V}=g!Er}v2cUxQr{Tv_*D->H1qcUfW1Nw+LuM%gRw;u%)qLIUL<#kohHF70`Gy{zP6w-`RW1-_(>Q%akWI#(`T4(@5=^i_TKj_
HD`itfK4ryCHpNk=vszfwTwLRZwJ&<>d?7bLId>v8J7-2XoLdLKk}x09fz<UX#2|_!Xvc4|C5@+-jg?qhPPJ(n**52l0&O@#-O*L
6Y_a1x}HLnH_9~#cnx1S_}^ryvze8g>bkJraM|0Zp)=iedVjfx^V-g68(&W7ZMX_&!kFUJp~>$9yN4H<Py2Q{%AQzg&(sqCb4ajQ
kDE>WGR^nne;87aI#)3X)DiCwkH=_$Va;pDt`w_TKcgzdsz+R8k@0#2Yb?y3nNX??3&t$R!W^iL#t1__xkw}ekhDL5d>qXe;5zJO
+KiH_|G5e^IGZLuv8x=I3p6(kk46xSXm?+c@-yN~EBD%48Nc`nh~7mRk_P35vwxRX)EzYO1kW10&XEJOkOKg3h<Yj#ZteC4`mZk1
wnlaSj`$5F?cqcx#N{<23NMQ#h4HlD4CS7riLmlV>50#-0=zyAUXZ!aW~QO0mBJtn1Lcslh7^sp+?fc&{{Z{4j~zo_^QvsNy$yd$
KO;EavPU<^g`+SC3W@i;Ik4ZRIB0ssasD9}8s+g8aG!hvcWT4yl$sqwx1l;+dYjqO@x{6jxKL)ED8~_<ER)8(%6l$dece71-8_S5
K1FkCDHmn;P$%nBnWBlPGroZCFfPrJ7-75T8+y`JRZ$y@b<|&goRm!WADd%W(h_r_j5`iyY#O#Onjnjt?9Aah1T}>D-`gg{mS)^x
w5jh?!x+rz?@jD&2U9VTV1GwYQZbSkPmBS<sb2J$abyUq=L>^{IS0pMC`#{jwzUaTTqXUnIa0=424=Vq3j(pqM*gDrGm!tlb;PF`
sdNv8rBlCTsAGXlNy8FFrgOKXPROLd887nPP39;pkgr)h_Ke{i|4&%mW?oJXC^IyCR^shVu6t?)I)>3aLNt4B#C)gfoVUFrtAjSQ
NGGSvLLK4oN@rwVj!qjRcJJuVquFRyi923ojxg(Woe+}zTn%%xm}N#Z#x6~0NuUzACiJyhj7$gZ=BF$h?v5>Cnm@OlE#ZNuNphvS
u<G-3x<57Y{=3{}@|jEt%$$L-*QPF&iRO}{G{qMBW9B9tT8G}qdq7>(JXQX`O<iR`KQ{CM7o4OP3p&mkQ?*7@WZhl@6N=nDEqI9&
+BnlX=m-1Gx&XH>0LaBDulR)v&Zl}MH&wy@%pmj+hf;GLY*hg%_T{_<p|A`<RiHJZ@TbJUuo6t6ER5x`G2_4KKf;x-p*Y}S<;Vtc
t9g}DTxjj(31U}#GbaocKqj2sO>lL-iVBVcEgl<m4-$3w-7sM+euotk_8EGVijbTl;%kS=h`{Z)6JKAx7irD;&|PGVYsweJ*ARes
GL#T6G2Ye00K(l_8ayCk1}{bLmTyVs-|Jzf4jx(mmvS>`cfTxGT-s)mXXE%*fAwmmtb*9yB}i%QuhNqOf`Hf{jJvTXrL>5Qk$n&Q
51Wf-c-*LhE$QZr4ER}QL{(%dg#XOT6pbx+R_;9YHy9`L3SDGKLWLK9=J7)fl2d!82<jYkd_ftjiGZ|QF6=yo^Xcyq5x%IKv%;Ue
w@faCMQbexou2aGnAp+7V_Q7cen}c4S^tAZ<Oxy6PGZXqy7hItP@c!A%s_N@`6NEAN8bzGhuW98XL73WV}%X9H9^{;#g4;aQyaXq
&?(dK_SWrtX>~}$S%@Tm9ygM{=KtSj1H)!Fct&dhP}sI*W9y#KkcNpdOWc4{I_GPW9zF5z73DD#Q6;$maL_)tqv2(KnVNGt+0*O0
oa5%+^}mrI9K_B2B$*Tv@cp9L;<Kx~hiw?uGybL|ycB~2@AdV_ZR)VrLXL<gNTyhZUrAMP!YuEUlbb!<r={+oRa?dx`kT1X#Yz32
+BJE~;N@U%aUFX(nMdvq>$w6pKW(VVV0@OxE>t@w{=i`;=-(WuMj}?I3YuVX#XUPj2UTzj?;h?|dILb`ab#k)+OFTe{Y11j2Pc^B
T&GsArrYY`ud(s+JKT6})~RKKc(pIBasJkG>0Q+GEjVag_?Tr5+m=bfM#S6IWz~qH>y8JSK%TYIsHE^LoF(vbOAFW`SGh4Bb)({N
XKvb5=rWmdf~Ep4zxdIas^>Pxr$9E!I@rS+C~rX%sfwt<K3&MXvmA$o6Gsz)%WBOBg1v{>`2UjB;0gB5Er`Vii;*0gxqPCWc?Oq#
fN#7yzHUm-f5xu12%btdnj4U%KNooACMtv@9CI!PqwK6Y2iFb)KMIA|r>x%LTjjfqx^DSslnC&QI$LvsQ4?VKNkG<eK}TpnKjMb#
-qY9}*Huql8W(Y9$3>m{!M4O8EB30x1*2O)%)3IRy=-;B0JoXD6pUzIUBXru<rn83xH7ZxJ`#=`CnN%iNDN#c(0UDSzu3~on)3-w
kg82hO#3aBr2bMt|7%Cxh7F<~Xm>MagGcv67Tn>&Yb*=PXl0862~tgc0~SJ2{MnXs5-ZK}_=`90_|$f#JN(n0l1GKM`sjB`u#f#c
2!sd4TkADzOR(L%2}}?`1$%%p<}2qv)d==JZ15!^38V3zy?xumAIKjt9W|1nXH*ts%zs+^2;_*d8;L4&7+`*}JBC?aHsy{co0y8A
!2Jw3&X*wXOS{wUWs6oZE|n)(FQfU8T)_4EL=u4IG^huQu;v~690iu#EpRPtRt$K8oq^I$?BeolFRJKzxE<2IJ*GAfdXU(tI0dX#
gWZ6&04q_!X|ViED`F`EpK2kGhq-e}!?vRmZ!UQnTqOeH(<(}euyc}u#<B**H#uO=i7<pLM^Mw#okLt?LxPDUw5{v<s@uRv+ja1~
#W6kNH&=DkX?k~^ZtERj$%Vri>9EoJWxEU6PwuD9e>Qgs=7Va_owht7d4WGIC<+H#WLjk(BeB0iZ4u*?)m~qya4T?cBq?({GN&>@
v>?#lw}PPiMH)EmnetkbMpr(x^-~kyPW8F^YPhQ~$s)B@3kSIA-AwZ)fBKi`slit9#Bjll=R^Ewg@lfg63Cx{+X81x@W(uxB-u#c
8Jq=<#N5fJ{q>@uR51LLsbShxX=XDo5?`AC=WEXchZu%x&gk>whN3R%I|h7`;1p4gca{V2a)X$LAFI0vvkhOcU-z<^)AlKsAmox&
J6g%0J&*CsD4L@r8YvA07&Mwtotx_C(jf>1ojx1<&ZJ9`(674*EkRw@z=>Bw6Tmk#%8>U``$bLHFK{|BLTf*S;WZ759oGbK^n-E`
DR#R`Mt-Ylo;1;KJTq_Qnp*n;h4Dw86)D&T5d202;*3>Ji1ADe7;GV||8|X)6r>@`D>;$#RSt1Itq#pPP{egEPpZ+3*pkP8ODR~Z
F?t)?T^6&1`oz>`lktSDKhF8RG{E1vAwT8lg1vCD6nn7v_Y~V6#=u?eXTG7uXcHN=6q-#~{yJY?UZ&<qrwu1wqc}HUzFbxiTyKv^
R*&h{DUHx<!Ist;?J98)x~A9wQT#0EoMd>Zy|{<qE4IDWr6o0eyi>d_1IQ=SP-|dViE9mV={%s8iS2b{e;x{QC=2bcO~Hg{@8ILM
xamSRekca3RLMO)QUMBH|6j|ZD>%rG!uj_(a62chfJJ-NAF@EtVHtb(y(Cv+BDuS-i;<9ex{r^D>RV+iu4D{$e<to^w1JT1)h^d0
N}Uu7u3O5QGYCHS)NoIhpVz1N&UL)7J%U$lxL=V7MeTnnX>lxrGm^S}#JSuPS{{?FK%nTW<$FKEsWEux70P=oZ=*enXQr}M0jJpL
`vRS#o{&~1(;da0K-W;|*ksyuO%5pah>}&@oED%2)IkL-!}9FAa*5LZ5Z4)k^sVg=Fi?xLHEbKf?wwb?><R1;H6BWgXbVDrA7qI$
|L1*u7nBWEH0!*vJ!$NsgjkDWOqR#ak{d-H4%c6);2F_q3goSh<=2rvAh7Z5jrgQLU27koS@bi|;H{ABrMN8Bu1M}@;Q!teE}PC(
wbvDJ2XFE$kH&-$$MI&+M_hHR5kVL<XAY8WZ*PgLlQX+JX|)8yD`Q^HwjtaI&VKJjwSi3%pzF81M@t0~HO*$%**DDG3Qkby{k`Wk
T*s~IFs(6DFh0MvC{C|36}zlhd=m7z7}jVOqMAlfmrlXs7Oe%vcargc;qO8`{KG_*-Vf?C)dYG(9u?Wps6XN*yQNB({VhJFod~+B
Nmu4At`NYY_7}$y%NO6<7m#!yM}DFSIQRaL_^eazOS5{j1c#GkM%w6(Pqe1zTz7*6If#(ar`Gv5Y<}5z-=!i0O6Gs}5;vs_g6{NR
48;2Y{CCu*)9K;LT1PB~y7Lyau;%^=?>fh2M76W|rU|lX+4ND0M*<6<%&D_TZO(=a2AM0r=$>I8znL+S_C`eiKNi?A1&tHt+lNwX
0~wHdqFoqtc7&dzzwycT*V?Y)3>fFfV`6Y2u+>&j9o5Jctn;m?^sY*beU;Nrp^L2FnAkPIA^jd({|HQ6L$d)!u2)WS^E)j!SJ1xx
Z0mI4G3h-kp{GYii`KA}?*iZ*1Z9Nbcw-N;V)2La;8Gu0^;nE%nqF|uMG9&L5@WLQ(wzshukKmO-3#X`q47Zh#Ak$yRW}~Z3x7MR
C8H~dMoR^4PM4FAw|@#guAj0anj3Kw!wus?Gonp4OfSn_8LLk_tiRl$7;>jF7LFq8x>8nkoeJ7da~iLn`{wz?dsbjt<6Kc{fB~XW
?q!)jEY9jwL8>EwrnZgwGuR{1p@h-^`SuxMt^4T%`{APKtSLi&3)cb_z1&|Jl4IV5^1Xvj@}#BOmN~JpB?7PzvGaBuELExk(o9bi
yPTKhRV=6}?g%|THbvRc>NefRT1tAKOH6zFrelyqw*@Brou%772F{4m4Baiv`C6o^?baBS*`$!{2_p+VcK`yHiJCi@Md}?MpuU-T
I<OCU@Mv!iCp+-%dz5MVJY7=HfK}IwqDQ&e7Lzr6l_ot_>etZo`b^F%p|1LNGgc4GC?_}TW^tqsns4&qH|T6?lTk;612-wAaG?HH
_R|3ikuW{N8O;b{AP9wVM8NL#_?r18=rEoEg`R{<UUW3=zSTb_=8Poipf{H0{mESLSjuc-{XAlM2zxQWo9Z&Vwt~{{0PjXFr~AZJ
edQ!1A8=##&o$mu;C6P}P|f1KF!br8v9uvWPtr{_a=4%788~Ftu)!J|u7wqAT+1nkdz<fnzcqzwmGABa(GC`$N8B}POSjfJ_&dxu
Jm(N2WA@X?hR8P=p7n}wnl!z~qGPNPYIkU?9-nQN^2J+P&s!eeDpis6C^qi&KwKau0klcmGRXYn?!p1>o7IMV-ElqR3Fk!e@quNR
O2L9eIv&akgh8+}Qr8SixgaL6PXa}=h1VBc7}W1KNszh%XK9t+zgrXp#0S-A?a%dgxNC>SLWVOIu*#wkla^v%CY+^$d6<S_pWq@G
*=&cnVN_Q*WttHo-og2IpRTnY9Cw#kf_T_X%Pa!@cZQlke!DsSi}f<w?W$^IFk7}{YQ3#K>Sl9IXp!n!9*ovsj-x5=g^0EO_a$9d
2EYf+gOK+Z#AhH3Xur{u|9H4*Ob>$1Z`j&JA_{rpGqjj+9wvpfS#WRAgI%C6;QGqr^07h^E^ot=j$WRiciaPSbe^CY<G}LHOa|h5
ODBNT;zENTz3lh;GijW#8V_&txo>g%%&MPh71ip^cj=%cbA$_Lym=ZSi>86<EC?~uoTQwL!sm<tmmutVd4jog#qK!Is9sOvG)v(L
MOW(M?$KrK{nQV0ZBnB@?Sl+#w^=6pnq~!r61p)UEsThx_d>*s3AOHq+R4!Jxc+R?Tu#sV$C1Ct?ijg1>;jQbURz6+TjaP9HW~c!
pFKHVFY4REDr-jxj*`)cjtK$lJEU{7>O`f%qU+FB9-3x4{76MWH4}}12VZtD=T$^q)Bwe4*4ye{@2tXznG{A6WNzknE<-XJ0hP&6
P@P)UB;U{BV55PdQ9g%WM4M@Y!(OWi-H6ijA}a6!#eY9{C6I)c>2(R5ehve@4oEG3zBS&p=C6-3_sk`x)!99XGwhs(b7mUy+Tbf3
L8E1dRkmOPFOOy)?<;A41yKq8lu?M7oYrBLqJ(}6F=Px*<|1Oceg+S)3Ium6CPcUw+TLvV^jB+da}d^BR)T<SFlSamw|*xBc^@*9
fJ@0_O{Xe=7L`6)1CBzk9hn+yC-L}lEsv78?j~VvGpT82Em&w;1{Jf>9LvN*>j?(aI?g*WCOXX;150hi%efjQB#v@BcfgQ+vkW%E
fH<PV@K(jow0M6K%~>~7LL`wXCg8UIu$0xx#XkpZ&&L|cr@S3vv0&diO#hwPz`dK-L8-m)Ash8vYT7oM+X7E#+arLiV#f>EGB-_<
|GoylFV1v%_T+Im*!Sd10)<e;p7s?c;El+2yXOW@A3;ln$2&*nv=D5+a^NaB+%&GWfb;oEK}QK3{iEka_0n9O=6VwSNr!I)2R3A}
X^CmNr4GP}gIHO{DH<94N?<Es_?bnI{>nOMGXHd&gK=`bWKbBm;>z+Kqei%BKq>gaSAdjK|KUlp_YmQo*IvA&n9o4?*9~|R6UEIs
;n*4Ks0Mv^)VDtO6Hr5vEBDVZX3>oUGpi>Vr4HB6L9(|z@W1W|UpuZwL0%k6m|3~l&s<|IVZE1Sr<J7x*U+IY4{PZF!juE*E2ol4
YFRSl_C<kT+Xnr&0!z0)xDq;w0BwdT@0^G9IuCVKn)HB#lrZ>pi)XCVCiT7{TY!QmCpt)mpO<6yT#7=i`8I&QW!=H=own+T*sL$Z
_8X}hu`?S#$1?Or5XcygdvPH}Ak3F+ZT_f$^EqMT2uwBykt&e<Z;#)GtAGC2q>NdAjl-wh6#Mg+dT*k81fjg%+e**)X0nEA|F(*f
@0sxaW6Rd7G?VRWBnw1gM_XVCUErtFUGP(CbG|H-by%CLaDmUxV6k%F^t!%&#?!B;_J@U0#5$KkI%{G0{%V37_;Sloz8D;ld~vE4
s|t7%KuQo5V1cQdg1?d8X;y$cM;{x+F-$h7m%J~NM1M#5@O2K26u=c(K;{NQlk1Bw;j#Y@qdHSs9XFF}T4;DIzmp8(!_aJR-nYZ9
_0ik9n~_*DO>9V%0wx)H$;!d%seRQLsg}7Fue+A^MX{owIHCeY4o+L9RzdE$(c;eja=z_EmFVZ3l~U6L=(icvRMJ2P2k16<WuQd=
2c8|em`aER1$dgbC_~qP&8TF%J%&?R0Xmjs!RuD;k-9aSiKfk@F-xPYndck)IVWH<9=X3ah&4**^r_-PA4`qt!o-&id?k`KQ#GcC
VR@j4L-}kq(iHGTZE`ro_y(vD&&^qUmd<&EU83{VA<2b!g4i`V5)*hyx`5w5`Jol3koA0w!LcA<`7xAR%Ecy0C5hqzJAwfg?qtsQ
ajVZm?0)1JJ;yDP-JYKL`dHJ({PHHXaDY9@P^6Pg<mYrp4~NopbsmKzrl-R>62I<2?P-V?`o0xvVsg~kg&52oUJ>`x25m|8sHiEx
6OfvsC@cwd_0ZGy!sV@!;f$e{Ol>bp?xw%C@7+~C0D`>iPZ!WNBQ9XN>D%hJyO0)*J3m}x#+bRV9;><o<wvS>A21q2`mPd!zjTvK
iO8Vqz<^VP7ojC2`{lC+g57F&_MlLYMuvr=T!Gm0t4^pKFt$x$_|T@$+EEya#;Tz1Y3OfLj`dS>HYa0+)KnyHMwN=?*$1P@jB#=o
ja6{)@hgGtC0^Byj=J0b6pqJWIR^rShBzJPNX5H6yBrQE&E13Kkq<&7(36OvWp3KAmS}dhA-5o|u)s{;p=`+mzg$aad-z-3F3|ur
)i)rNT}Tk-tIz!m>dw@KzrptaPF`H-VBExxIhTBGS7efoiOVd82Nagv6IuinR!NMtPsXATg%x&78{Kf^9wXthgFBe=m<b6h(GQ%I
6OvAzEIfEXt<418@P-^~pT^9QAYAA&W6hvoV&d_X5HgXEGnrSn$v>#N-zcgxgj29KYuJON&V2fxP;IcTQ{;m_uEcI@Eb&zv<FQ(w
O`7&<A?suBbjYK?AcAi4LZ&mD8Vt*%kcT9+*<*b&FO*=!Fr6mo`tNDF;VHzXS<i`K&nu3kF2f*rBZG6|LSQ}EEbLCkKXaysY{1{H
iAjv{&&cIZ5^JzYBR<Ti8)_N&t}AKYwGW5W9(U3P4B|*BAUk|_okdMKk_5bpK_~K};2XQSWb2+LV*@SNDv2RHlqJDAKPrb_#iwl4
yU79yW4Mfp^WjV{bk~>uI0K9drX>N1W6ol59yzglN{ZP9h3>FEq1+if2BE~4^Qr~x`AuX7f31yd9xOdU&Qrk6nl0A8ye`%I=$%1G
x?DLHSDY)p`F~PPUk-a}l!A;m>;0+dJHZb}E$Q2FCM91c9$V&53bcd#f+Y1Gd?HihquP6aZW2dEI0*aEvWQoS0c!)AJ8eZ9CuFA@
Q)sA^Qfy>W1U(y`^3Gzr5iI`)<?gBeGx3M>=%UrdjHD2Ost6b5IvEHnv*&A<uFTA4GV;4NOW?BIJ?=_w63CE-0DY=B>)N^;^<&q%
?hAoq=g7yz&xlx^59xckm}y+glDm8vYoCf=Eo{QL^_83gG3MX5nDC$gA?B@M0mkeLF=}z$XieSC5dL*562sy+nusw}|7A1sjpK2E
1=cj<@VEH${VvWZp0CJY^wQJ}Ya4D)NE`qg$2CQCKw^U;Pc4@w1c|5iIi<M?`v>uj-tCZ4_pMYCN;YR-XuzPP3hgQXO!gwe=|dk6
NRBb4sHDAE_nhdKmi3!Ut9vY4eT#ABx;`vMhdSEpz;lu>qCUK8U_?_MYA+|2N9wv>ZwEz*8vDg6(6O`<d~AWL5rHi<B<6M2+cUDj
B*MK}Q&a`fownD|Ga&$v`3pgHF4j%}YdjV?6B2~m+nzFKJdm}4@)O`c3w|#tPQ{RQY=`XP7#5kS(ce+BtC9Or#Ps|kK#gxe0L}?d
-VCZ{;P)R#a){&-fY7$kb^1iJrt<)I75gi61FVvVb2b;{-aaLN2eD+i;G%*_Ky@w<o;L|}AKtm{ToWe4lxBccGCpt>{@Hw{I`<Tw
4QFX`)@*eyABgNec#czGm`zPUqKjNcPt%<5eI0LTS8RYTG3|AmA1Mp~!uh#df<m4<9r4frIbpCzLwLer`zKy%U)-7H;h(Bn+_c}s
ETgAl;t33s=r!-&WH<HY4m<_;xlKw-4por?{tM3l7+>eGd$Kufj}&=S_WJr?s~A5a)tbTQAX-5W4mLN@I~(cD?^1HIl^o6t7h3E8
c`P@F^(RdI8T-hHlD&)<rQ>IlRE|jbL_R)tM<((wV$%>KHEzeVw`UuUdKxj~dlTo=Livo)4SGM;Wj?FN5?$dkqpOK9^o`1?8D^nN
R&UoY$v<iu^Dm;%l?r)(hQIwjMfg6*?R@ym7nST!c1xvZx;5~@ZcALcfdVCPddf)!elo*yg84^Ug(6xeT~W$2{6W$-TyooN*j@^s
7pbUP3EV?W>MEmUnF}IKD{8S08};zTldcg?D<sC}&)F^|K}aSQRycv}Eq|<)@vA#cu8I|q-nvAVMGA-xA$2d06z-CLEj*^M;)1s*
VM8H{Mln)}o1RwZ9!Gp97-tHBNYzmTa_*kowQ%ZPNn>F-Ai@QH*|!$JR_b8@HjunR2V+g4Ef-|ab+vTfE>Q^kc(8#1UV7GX#dqKB
t=nQ^KBc@#Srpt=D?T+6)5xTRabS!HKBfF8?=%{>PMmn)mFX>%9&8^D5cuTLkn`0>D}O_}ov&K~4LM5+EeW#r)f5wWYxL=ev174K
4&vapp%!wAs({6bjL0n%rFi8tLyBy3d5D8$g_zL*Wu1^N@y#E3Lb2Ek_SZM9RY>z|!jAR;HH88VG|yB*{V3e+m)|qZ3u2|%i+k`C
+#B7ff#mV6toXa4S)?wj=o7xJ+=f$P&Er>t#QqeuT{6IO?jQmp><7|&5#XuU_`#uQYa(v8LG@XdXj0dOsO)S{y`+hYix?S#I-mOT
B-Q(9PHs;6se&RxW;kUUNSg9pj&`8Z-#Q2=lqySp3yWI|Wy#;b#2jXV4aP5C#O7uR1KYaaHs_kT`iwyv20NbwPYdh$Z0e;3c7HU`
A&SiEaq_bz87t05l9gvv5rXu`VT9T<*cCX5HC&Hh#XGyCZW$qhNl;V9zh1OgX2HTKSV02gmb!oXJGkDVTkivSZn}2@Xcp~yq^%lw
TS`Tu?x1sAl8c^RpphHxqxGd`LGoEGwA)LW=4*JD4y;9<;78Mt;T;U#g;MY?RK9x4kN&rgcOhWZ*V!yd1_E+gY7GebI+PU4U*&>g
VidiThCmDTiro%Qj;ns)>vaBZeWGEL;<zO4TV6V%#~@x`&z0=r<C(WJHGhHV+jBjDhcQTS*aL00m8;Q<cQ>y?>82&FhvfJP0t^`u
)3=ie8AbKZ)%@`ANxfd`f`=5o5WRpd`C2@Q@rdhS1HS==zUy=nngT6$#9Dj@h)s7b07qNa?n$3Hm1Z-Z9vy@GB`CV*1@s-Z#Zl7B
%93MezCBx=R?LGSuvyGVsWGX>f1IJmg34-VQ0CW}fJjUp)E?T^>uUt2?DqD#fIO-VI$mB&Kg$g}R>qrH<cK@GA5GMzR*4u{&b41U
LxgteQ$^wxqla@D?pRa=b--|taX84AGbY>E)`kE27Luh9;KNb&#jO@JoNvRdxIP#10VEzO_>z}NmTd#Yo`E{2UkbbR&#@j)?sFHQ
%I_Vd#anGR!6KvOjg}aDh+qZX`1QuSMT*U|)zgZBva;lZu*m_O>5lANfbkby65N~CFrA;|m(rp`hW-*=_8Mn$Bnm;9J_Y&`i?<Vz
&d4Xd4mUO0%Cgz65049r$^AH$Y}W#pd~IV4E>V12{7M$r9aY3Hd0e_r?K$Y;!DB^8#!3R~2Q}Rp`c`79DTVr20hLiT+wKtK^c^Ia
l6#&xv%YGH>T;zB5K`;KX785NX{crdJ1=X5Q!p#;JftSY9bUH<n}4cNNd<zu+@v}W2%9!zfr2F=yQ*I5d&~3+ve;o@K>aHxGmMzs
7%jWZtK!Kexcy}iE{4b7g+2U&(s@HeUlhT81cTts*ZeyN+V(1fD0QRKK1ri?#BJGeC!(<l?!oCbjjt4BDWAcaFN5Z!G4Y3e5wBgX
&9#@A!^Qe7tcTn-Hb6f3&1AQdk^=g%|ADA;rG|Mydj;0YRDTiHWaYU0g7c-!xDDnwE82MC7P-?8QWH`*3L2t>vWdazhVmCmY8LOa
W-m^1(VfTvlmCc6NL6R(D*h`Su^!D1Z|}T6l20R$66k`pT!tFQMD{t?z;#}+o?TK4GjdW|d9ojhLS*44hzmX;AK<AYB(;<Wg1~n^
ZnBrV;vmkdvHV%sJQX4Ka!FAhwX4vs_I)-$c4pQ!O0ZL2no7etKR5B@Bf;kd`q+p<!kM~uFxT|YCH(fnDjh}>qkt{7AFU3$octR`
gBRDF5fI-8M}gClqcH}@gdFs_l-GQo(>3s&7a~aYpZhvcE1C6mh-?hM;qv7vbF>md!YDWuS&sq#Zg+G9Bu!+$-ut~rH4sV}i$Jh1
c`Aq-rgI6G0Er$PkUseNUQ5y`oBE;K$2A-1aa27{QG4uS;6#><cmTw;#CS8T{G29t1gn;vdKmN~UmT_ZqHt0D<avTgmU^oD2agPu
Gp#+IW_mWfiPJ6`WN>N5n(-!eRC0o}->S96FA?Fu_`Fhmpm!D8HSHa>Ohq*(3Ly5y<jnvP-CZ35<A^7i5n4YdDGel#kKO&pS=1NU
5tjv896rfUkHwicex?~JaIl;0TSpK`t&ebp6v$oL_uY1S9$h>`{2qE+lvaEEj}=DDOO#~rBB!L;S@FeMc!A~;J!ALdysUAw-Z;!j
_U$>YoLqT{IL;2pkK`IUYF+POfCo|Da8=@5Z?dMN9+18Rlvoy@<PCUF$Ik$7(82`i+^Iv_kKc@&so&K80k(MuOd1zAeS}B5*9x;}
r8^!oU3vcSzCYVATd=viit2m~NWlyx;Dp*v-O>fk^c3OZC!>ZEbgzC=)uq&Tq@kI#s91?WPK2hA$b)aU*$zo!HU`F@5fv<F7RkzG
q<`Qo5IYV1->F9_69Wz+RVh^=ait`eK6TM)FNS2X+4cyyVFg)~8Ktf(C~ka%3Tm#ax|<AF--PNfk=}rrYfw*H@7hm@ra*BBz1yZj
_TMlyIKII`b!PWxd--4LvXAjI{XV-a&%`4jIrrlHhr)c_49_(Xo>h}rU-MUAQdoY7Lk+&chZ{^B{fp(1C|Ys~(dlkSv&ONvq~03C
@P08i<(Mc)J{ZWr#CXCHEXiaHsd<nGK5X-h`g09N(dlMZ{&?QEpa_9sr(1_7HJzbcA3rfP`dmGpl;GBjC{>3JYWEyK%oGyoL}OTX
Z{sL8!kDD^(jTnj^Hb2e5pndqzb2H78pTTKtbo2U*kV?)52xe3_`0|yT4CSlfVEGC+6Ss}cCTv1A)7$nO$P@42bM)Z>ovA%1yI^A
Rl}oOFs9PnOY2OXD9ZW5dFq#Oqzw`+pjt@S(yePbRiH+i^1d~}+A)4U9k$qrep7;gs0#8l2kN|1_EP0IqR1L{J|H}^HoJC39h`Q<
%005ZA6rCaN0gU@L?1_a%Vk1q^vLJpNOfH<m(q;iJ-ejeoXLEVI}@EBL-~TnJS!d33JO5bI@oz?NlHO!D9C6VfV%69YT8PJaRE9d
klR7%C_35s9={j3tAuDo#!qs(Oy1mXf=J%VSTmHeNK_=QP==$(x!2IG*cpPlAxXQF>@J?9&N}y;Ek%ks+uNa7W&oz*3(3hoUKQf=
ZtCV^LSwba|M#?2*l7ByqmwoBNA58k+tBTyD^xGi>8ki~v_V^tkIg~xC!*ER_oW}`54jFVu<nXm>DpCKdd|GwU+Zl)%X}H|x<9pf
^MNpw`8lpcX@xC``CS%H5#XdvJvSTvqLQk-v3RbyX64|J^-c53NQGIK(33+c+7<4#%&#<5DR@;UnOv4NPHQ&|d5;Hn3FytM%BA+K
t0tz_wHlM+2gxy>uGTk?w{y2TsiA%ioP2vv8d6%n_BRR^9k<0R{dYyVTd(Nk+jEJBg)my}zhHVxyPd|d$BTdBsye^&;D{dc@70ru
l46hZtxbJ2ZP8dUAl$arSY>Y#UQe{RuF^?<PCpx?rP`!gRXY<f&3mr{s|`$VA{|o~8B2#4Z+kgZZQ5OOJp?cocS@Rhu}hqZoJQjz
Od!n_SffV}NW8VA@2q88S0N5Q=O`cXBrD2ug+;4_K@J&M_|W+OB6#DRyFLKDg&LANO}>(BwbhJrnGDGq=Bm`<)c-Y4z;2Te7J4L-
{{^pvSfQ8yTAt{68GHUOEpL+OV4saK?=CD2wC`_%{pyT#^gF=J{TgGWawg{f3OvJ{uv(h9i-Rt0eue+Wfm-2ULZtenSfaY<ihw3C
Qvb(&#@rkJnnW-<=VctwAcKC=4QHkAi!TaW(2br_sv$_kkB5X;F;)zLw=m1Yc04JKI{h_P&%p(Un=PU^0}}__zo}c*@fsp}vth=B
GMu-GH3Fxcl68CidQw@f4JtNC<XrI1t`RMin>j1Av@{s~XyYU+XtDwA2KhG}tPdhWe+8gzf^T_xz#43bt0?0tcMKc8iu#)~u_{;}
s&Ycfpcbb%5Ah5}F207TxuB+nujF{Lbz{Td4ZnnS-9T|g+7AFYuGfb*Q#309D-zH&ARRLPV;aNl85~#T!fQ4*qo)CbaeQ?A2MB7I
?#qn$38=hx7x0K2a*EFhV5mz~NJ%f%lA{ozBuXIPqj2e$X$lCr2S`Vt3<e@}*p41Ixevm&K9R4puXFw0L!YJs0wGPEDjyWdFI{o3
>~%+S|EUuagWGQh+okC*z`R3`;b=f%WzF>PWqQwVaoT$(B_Ti$Y(_z(`2QAgj2Xvrw(eO`CzCiUTtK;{e~x%Pwk_7~6dWlHA8hIK
ijXoVxDI(wyx9AB62V%CfqAFGKC(1g?R2fsL#W$o5?~;aaeh#gA=A6j<ISjhHpE=GIVkMXX|eAAL`Rp6KpoSrK{qycx~x8(=&%ZC
-LmKuF!@@eBWn)obc6<DA9N_NBuXDlR(Bj3;Yrfgf0(a^f3?UhP~RkxCncdDznKPOO!Jjl;fZK^Vss3^*JnAm=8Wl2HE_xk&~OlD
qG2=*Vk&IkU-i9SSnXh|dhy}rP=<?PhOvllR@Wyt-I#F&66Z~3gLSChY-vLvIfMYYE3-7Hu!AD6Tmc4(r3d4?%~Z`!?!1s${%;=c
liThDYUd;ggMZ3af@zw9jiS(qUymeW?nj2i=d)>J9)O+L6VZjjGL1Pw#@M}frtAm~xBo*c73`r2Hix26V<JpsEd+at9<3$v^1e*$
u3-fAA*;B&xcz;(_lgCMF$`C%l2&69^Tb8z!qU*7i^){HVe~jf+KsOJIzqL3BC*{goqGU@V#V_4TLD%)xtaRYjS{VT+{O(u^u1Gn
aVIx3u=+V-T)GOIMFqRIUo`=r{Gz_T?07I&5iW0PhyNRgVxF5(sWFNR!JTBc*8hRL+wZDU?7nrM?D2H1`GKC6u>;}hJOHC!Eo<_|
#H~KYC;;oGEUEf^9mR0_ZcsfA%gDO#ecTRHG*Cwlmsd56qn!2+Gww)w)+435coHnwAuiITm%%H{GA7vJiAa|}7TC&Hq!e&=i|WRW
7$)L#YU6!4Fi$xt&0BO00j?ns?h(k#ow6pkxd}p(7SQRN3-X?qek>@QNpUw(qhFyEQY?8(fC^T8rCiy>bYuLQhhbEr?#gB(=|#eP
o_TwhTT>YSPZ3^|*})1%Q*G!<>gWMj805eLqJzimWiC=<tOhSfM}+i9D;F0zETj#_PzBWOte?d=?z@tgvV$bPslX24Bv`lABB+o&
$}gMWuTTr<k3|Dx9OLJ=rw`~UPe4I-g^1DLTOYHyv3=<)C}$kx)w0@tXSE|-m0%hd-^pPAgCyQ|a9_a_^1LW6PgZj2XNM@nz#<q8
g(qpc4!FBZErmCzt45&jv`1l$62X(qvbOX@abjCT;~qUC)A$(%NfAIqJ7SIj$_IF~b$fka8P`g}`ntFc)Dp__3As%sM05mj<8mQd
?9MG58l%>$2G;5MFx`IY)Ex;tBjkGMRF)6;)$?Snjijwnr(-yrKfD*WeDp!81c@$s9$^7b%uncJ&yJO~3K$H(D5#)xRyv+MJibVd
Fp-kswL|PRqZS*YW%$9v1#h6}NGPJ?c3P0ZG}kZU=}y+~QI^F<BP|00-7l#?Alt%PJ=VlrX+1UtdyA0G+rBhGT5v!S#^|D!2&hs!
eMVF|UE%cn@(DY%$9ju%D`0xcuM!^c-k&X!i$X*CTLRP&$5rd#6Ng9P)b47t=SZbjDC9Zg>jgsh+_@HaPl)V3Q|&x91~@xMYA`?V
JvUm~dyz7i=u!*ZJjbL4+Tn^fHaPu9c1-l>g)OdjoN-m$<Ce4!M60n_L!@E2vDYy3BhdcUVe8C1Y)svjo+K#5xs7qR<}2vnWu-F<
E{tx&QXS4}o*pFOCBo?g|FY`f75vAL)rMNn<^;)LF@&i^B13|;v9A^=BNsFlWctd9Yzz;vNPB?CX-M+b@JC^uJW3&BoGF%&mhM`6
XEbJTK5?+*x>yd7Q0ikE>x}$%2N0)}_}~jl8yYxgssEwxlv|3o57Ef*6rXCRe%RF7L*zzmRBNL%SA^87s4mi&g!b_s4mPX_MKwpu
)i%#s1h!QvSPn^0lB2G!r{cL72sph$CD=Y(lupZGw-~I}U)h+h1_p-Nt`?Oqq{^HqDQfsWOO<T1C_B=>ZF1iHfYjkL_(<&up?7hO
tOs2X^ma=@3!Cme+dN^^dLzhE;=+G~@~*D%ewUF?u;M7X=1N_#E$8%2K<IjBPB%WDGRTH^u1`y3P$$)ovfA+{yb^m5I5T;NMjX5P
&2eOeK;^ZSCd=2Wme_-BwTx>mkXxc;_G*qjsZ{#g%K|gTb~B%+`g0`Yzd{;Xs9-o4*)(7bMNhM_Ge+m=MTFvLDicnAr8;j;c{9>}
u+ZQ7Ykcs?6+B8VL5qI)yL$Ka$A8ZL6t`_sAI(>-xDpR9%KuA50kZe)t(ncW4H*!<Ifp(v-Z-pHV*;_IE$J%*-vHM6Kkf#{#Ejc#
g&zr%2z5}oMC%kx6QS0Rw*3}`2szOT8VD5GI&zBwfJlaV5;?C4%B9f0Q5YtZ!;Fe|8fWJ`mcDa9OZC;+Ek30+?yZ5%U-(5`zP%sa
XB(BBJY#T`F<I_a=zFl60SeNfw5;8^k%le@F)+!_OOucVQ0KYWi)$h?yco!vm#u9tm};$;!?5jyYhxWc4@Yu@7^7!NsUlQ0C35Vr
bXxT}JTOZE>CUdTF8Jj?!R1#JDjF|BGvXL?M);mPY6?fy)lxMR$=-%3JI}TjRmo~b&lIShGUyt8w{>dC&n(>t>;xGSuY#jFuH*9&
QfHFAC-PduGKhhbg=dDR+NUspRJ8BVUY;%khkC-1iiCuaxR%Q{gbIu!w49l1Z40{IAzK3P^S{2h25Qzcl#3eYSV{jm$uE|$g=pv(
sV*S?P9YbRe5>3728i78YSMEyGbu^f;m=|rh|yulE5w>ScSz-TG5XL!Yt1X@OnGkl%1`|p4CbVo0<=BATT~~hg&qArj{3f#a5|`%
)e6a+@Jf9-v0QzGX;ji->iSL1zMK|W757c|>)`F!>tZ3#WoWQ%k#j3?!xS`xy_ymi{Q?^S6-S*`LZ+_Z{}NQ)KZ;;Wya&Bkg{kYL
v|afM{HSAdY0PiJ<(B6FmlA&nK;8(5%Tg@jF|zA2N4wv^2crVJJ9<S=?Vs(ywPC+x+jnxeTA@SXB<G*YApm7f{Z(QWL7Kb0zc?)l
*0kI-KBF&_lcA{xd`1}o=Rl7aI)<SCxok+owpt={3(?)8Lll8poDHFMk&!a2-aC@3yUe9t5E;7J&w&xw^AqWcH0-dqY#zh}ZB4q#
QgCZlhJ4qqanQ`PGypZdPu~H>VF`-fGZ5me@F;N{0u|$d{9DlX%6DCLE*;kczzBhneDg^*K@W72W0as|CiMjm!0ro?jUCfm1GAW`
thI4TE|^hsq<UbC{a0gYlHj<X1jwL39X_>ZRBB`x)AWDm>{OA3NIsk)Nreqsyz^bzMx8G9l+4@=_<2szY9VsCN1@POA9Mm!@sPn$
j^p=2Qd0+8=xccfrwKbt1MRLUL1EsB$5kTVrLUBu=De93y|I?O>WF${H3Z3~Ng+zLFagn^>YYUFwp|zzIL5`S+dw9>^D)YuFc6P!
xNl>V6av{NPpIf9Hep;97O`r17Il-*NTG5qE9jb}sM(V)=J>GsEeyhhru_bB-(^#hj>JZ&$%GHoI^5s*G>Zf}ullc>Uv$;3iO3Z-
n9zb3{^@fh7OmzgquvgdZjkxRg%>-)NuVvZXpMSskM*V}l=kG+Ezmckdt>NQ^En22WZ@WqmWc*kT5>kmA7yCYoAGY$n2~|QH{5ah
uHGO&m)PwB=txU@AsH0^Fh+!|doZ~Gu0Ab@xR1HPR7IC@MF;SDIU<KT`^!wPZuS!X<$GLqa9yGwT*eEaCbS9bsfcjDA2k&tlN&^5
A0=Ic3u?KV)q6Dpf{9y0Um(-uaRGZ_#S7$KVT{5@tsQD*x2yIeU^8)-5;WXNo1W(E@!e=V%r0=3XbWcVl5#JCj|&;r8+n;J2<R2;
HL<o?CtzDV92=`T5o)J+*Uk@QAFK`qef6L5jkP7F`-dd)`!lwKU<kl@r?u*&rj}fedW{y&7wSsVbxRz+>@L@SJfZ^A!d8V5f=F#?
B+O_D9$UZ-_kN&#Q<LK$9;KkUYrfj}mfz%<>R-#s5KVe&Yup-d{&7i4J19N$k*8)fJMSpId}w+9kQbS*4qS^fM8oA{(OLD$AIi2i
APDE4rFDy;y6d`P@YmRwyHUce`uk_qkESOTUlC;OK%ey!x8VvB?fSPn09lm;+w&{a?JeAT=>pHZze`qcGPE)D(9l(@6-^pKwg#`o
Gf2F-{Kt_{69zlxh3t0~<ca%@uN_vm!->(pdqo%Q2vfRNm^E%ZPmS8n#rpUr$Qjpmz=lq-;QU6VGT$kP)~k3li0wo!D(}z%ksTn2
%HmXn{R-)Lqe>JxBCsVzajjNBYb8Uh!)olc$TS|PS!(L5@U)Gx*0!{i)t8b6&NoN7CeTf&tFVd8U}{$?)IUMci*g7pcJT^jEq!Rg
=B)h>y}RgeWvz^|EuNBuLopBBJ4R{{L3&om#_0+b$YtepL7gI1`<jO&ji=@f8Wvo+Xi10=?MUM8bl<dA8{}TBqbM)%E+SUnHn=7K
dKb|GSEiXtEdU8j9gYOByGm5GPdAQAP%^FG(`H`YqkhI^Gsl-^bQ?Z_djZ^DXdugtf+6FHel&WwJrBw+Sb3>KWxY!=1wxNX<NM-=
^ns*~=VRUD(gYKhUSvb+z0);OD(@M>F$Zi<(4bvCe&YmcbXH3FKk_`d&;T56a|7;*$MD|^alQ6;)>QoZRBIX|*29cD*VBkF68WfW
Iwe1sO(D1UaJ0)pJUI%!s7M-{l1<)6WxHaOu2vcXM__TlI~5vgvK<yJm<1D!RDAWEtyPV3av}TVf0XroEX@m3ioCUh{PM5<57yto
puPQk0E^a*FYr;Tz;HR$T@5eQl$H_<?!;;?kvrUy?*-WM#E2*14X^y7`di+yRYu-r&4yQjxuv&Y@Y5NqMaHe_jQ?$If%}BkzLK$R
!B!zv=7hliuz$s*#(>yp<x|~|<X|CQh+#)1^@1;2xZo*l!YC`haiL}XmA6eeY43@b{h^f9X{a<eGMSx{eC($E+I6YQCJjI)&BGY3
0Us>9m*E#wxi2WycBf;4xr{euegI}o?;11R8oU;PHUMSn-xbOVs{+flj;U)qCgC3OXG}z%<-nK_io>)B`-Sfy#<fuDUK6?W=RVAN
$rnf9!vO&^b*{R3+Um2=@&V=4mSTAFEpzQcU6d$}5s=4IRFggI$jO~LHG+uP?GE+GSJlb${{7&Ls_;h!h;w->b@N~%9FraEO>R!<
^}l6jr8xMt7!|u??^3(ZZ?YAHDXljtKNHkPexi5Mjm)B*O&=6OaS^=~RKSWTbw;Pw3iAV*zr~*(3IXnHW<fVvZYR*XxuH$f+iyPw
KK|v3DDdYg48#%-L>r7+ZHp75AHQzm8Yfama2Sxf+cJ^GjXPmF=@Iu^!bI3xmnKPh^fNQrA+)~YR3$Jm-F)&!vSoTd{;-vU?Bm&9
{miMnkApBs`GjxUyxGV5GCH`V@o?*VhCg$Dw<(C4F8>Uw6LUjB+>Rsl!OArig|ksTE3A-*9OiS+Fve9%(?vDQS>!#{|12ByeKu5H
Wn8@)N;mJfJRfSz24Ae3S$RzcvjWG{;X=pw6*yI!MptF7%x=#}L;(+<zfT_Z6VpllyNBIlZ$*S3obilyIG7<6eEKlj2Sl<>p!0xY
6)Z^9EE7!J?59j_Fm)mhNo9s@6Uq_zld^PJA9APD4Y_G)#k{jK%iWd*9<WV5oC!NeY!&Q<6<e%&dtX64Z8#MnmN!weL2x&8xmyxv
IB*sjQjzol(#Stz!T2SxSaSUWx}fc89=4>wCZk%ZSS!6qdSA#@1;VZm!`!D#H}g2XHCX0}TRdB~_`pN%_8wX)qeAf?KcBkHKlj8`
?EJi=0i~R?VI$@~qxwhRHpY=TPf;cSW0ufOwtGh9&|?f7;nXsprpu4;@7QYNqpNJtId~QNil4fq$czTGb7~W5j8to;g<7YW#S5|N
+Vx8U-qW!^3R+6oHYlL&L+>tjm!-z*gN$24laBWem(E1V+Ru%@nX&Ab8ncA2QG1`wqi9tX#JnXOP+y*(<0~Q!i83^H5x7e@D{b@^
B9j4ZE^J&EpQtaEW7Bj}E95P#N2Ce|9-8r?6VoDi<od!;gZ*j8jP>pftS>RE<lra}30NLmk}0h8nMG1dKB+c-)<vlL%h8#=K^yE6
@(WJpbh~>XosV8UWPk<R#%>#Hs#_x+7V#Mvfr{bSH!(3;-(IrJLL?9{Nydr6j6xi&<Bkb1!B9K5E|>U%!bpkIdNY#xfPcAx0o93e
wVXSu2TD0;7^C5b<)g*o2TKRxv7(n3L4p-`1(}4}hEf&glHH&^d*4G8*&?|u5=KhxsgeKzn2Nr}NxfKjWwZj{53y?%qO6gdBoK=y
HzlC!DF38@#aV$m&T9_CXHB+@RVf!vI|dfI^G-t{Hl+%XNj}s+DNu+WxxI<3zjn56E?JmJ3hYI|&4&ak$uz1eU_07d9Y;vPg$RE_
Pn~pRYf_!Njwn9b$4wUOtHu6uYU8e8N`YZyGrsS*9`Wrv$CXM$AnuS!_7#vAj$XfaP*+#JkmSgP+(h#0FFs&}I$a{r9ld2t8P^!V
Lb}`4nLC2=+_-wQ)?<ep*>m}3;KuZL>pymi4cK169hU0K*)YI)=wkkFzfgrD{*3u}o2jg)A&CkVR@^n>Nb)vnZGI-t4}G#vjF{!?
%n+fPozJ>xIxltjG5R6bSQD*_YpBW+v+$#J6Hrb5GCwi1SKYQO!$chIG=+%}u*(y7I|RgbDqJAmyU`6~E4!l2FloB%QxIg0A2-`I
+AZ5%qw^CU9wKT;9z8@#D2nEXb%+(zGLgl=ct3Jr*%$x-00000T8M1$6h7T100F`527sIshV#*BvBYQl0ssI200dcD
""",
    "linux": """
{Wp48S^xk9=GL@E0stWa8~^|S5YJf5;b|v|^j!cykwt`PJ&C5;is6GYPUUrf%>UQ5sJCP1C=Oj)K}n3o1q*D@+Hs-#VIB^^JLOGo
v)A^q#{jj!wHwPT1m7(R58)OvkHFwx=u}<3ikPh2sw9?dDS9eTFEsUM!vv!wC$UN&Wyg6jBt)EXjO;9sUP4ZP=9{GNM)_*XJI${L
)O&i%f0q^ar%p>i<97~sBeQ+SIp7>r9m)f_<t7i1mdgPeggb5+<_r6mVUJTha~;Be;&^L&$C-^kz@!J1#_o;yK)!Gtr{kE6*0A%j
ZV}$iSt_fw3Ef_DKy$SRx-+y+C4A4;p>d>?a|O)71dCIG){wQxWin3tUX>?H!4zlYa@?BhG}_oi$7MB>mX9FkIhwvD-FK#tT%pz*
i__D;KN)%QcYd<9wfBFYnf%H%DhC0RKoX#gQS>jci;se-%m%<HB0+4YBe}p|dQ!CY{;F_h1?~wr^(s>po(_WXK{2L*jLkH~ysE;_
nBXKG2VnLB|8RDFwK#|Wd+IUMmloguH$&wwTb}xvnU<pQL9FquLR7z6m$W+#?&uo-dEJ148g7nV4FC3r&jd0>R%Lb#Wo+A}7iFB`
FdAq;O^6Dqh9^Pja|{N=)U1u`0&J>2I=LQHDd3Po4wGsys)-sA+}<}Ky@xT5FJyb=mpWs60M$+XSf`8F`AwNCJ|o&_83T&(DGL#o
RhkOndJ%|o>HYy~OgjUxzKLJzWBV={m(gZ-w>f?|?xSN_YDmw=svqS*sn{FuCEZSKw+9N6x!MiFJR>Q$gP`nndf~64o~=(#_OXN|
f3XltnSf;Uc!!q_)7^W^t&f;*X`mCb<@Dc2kF>kic9h`)<frPO&>rLRK=?5Q3%kQ@dQ8G+r7<>&YIgp~X^<q{0nSZ+T@2wx$;-nj
C7S%-!*$2A#3V8{lcPe!8gobQq6KWPpMwaOz!w^QrB{q-kB?|V3~&Stm(nLpo~usGQ&46+l;1S?o?udeHzQqjDBML5H^$Y_smQ1P
7p3#l(#<#|y`}U~J?pZ8UF8`I8B|Z`NFM?!)TT`dmfk|<KaenaSeH%;Sn+u2iV%53l~eq>k}S*0>J{jcQT`_tg<5>QCC^49cL?4T
!3a$Q3?;J>Pnheg5cC!Y6|t%klUPwIyHJos!ksH<xh_qFr3$hcyV|lKDIkjTYU<zrIozBc|MLMk8%a(sl_uU8k}hWaKMJMv?z!(6
90yfDafWbCRYhP4hMNsqsBx)GJ`9nWSUT1hamJx(n3oEQB$%-hx*}wz9`K|&U*FU6NLyF+`nm;vRs}mz+n<?Xkr|V4&>Fs}ms;Q2
Bmc=hhXqZ@WsW1#^x(Oeio<C!2=l6SMDl~sJ2PLinAXh5T`2Yy`r)wzy11jfxG!`JZ&~1uXM7>UgDaLeyI8JS*`#A1x7-!B(>bg2
<Y}4)J*!VKO~*t#09aELm^4yV`@x9?py9us^(~3Uzh+VDDHEV7TsM!T5p_-DFCp5m8=$O;nuvjRf+#fT)sfIB6_`fWA<on8{>*E!
RMV-yCLt-}Id|w)T|5eOs7k3~j;L6?%)_ecWWi?Y>5j`&rFaIu%<x>8iI{BWpdAa(3%Q|MqfpCf1bwSMrzaQTE@fT(%!6#LR`Ig`
`yl*Ae8mqLOKc#(YVw$C{>CMmEAP>okfi#DLdXV*paUx~v}o<%Fx&y2Fa~lnA`P7Kkp^FQLG)1Ng=hk&zDK4FW1WG4?YoFqeehe?
G<X8{0DgLVH?GQ>-rng$%Fbo=RGuwj;u8EOnYJ}&B)~IzOn}I7XXGkw2b!&X<3qR19!=(N1F7f#=X19T(ERMy8^`atIdLQX%PmH8
Zg}J(`!6cS`~Tx52(8F8Puv!a<2|DWR?NeKv`1PzNEQc(lZWp=?t~PE3+=uNmF&#mBqW2mXMYLS&U{_#yV$~i>0spyb4DgCPq0aI
Ja)^E%%A5dJq1Llol>c}7OEZc84)v-Djg1PFH+%RkaPE!-t#=PngjNT&W@CvNF~R-8TX|MWtdyQq*^9t!$F?|EOk4PuhsnjtVmm1
=0)%Vq2-$LFj#e13Ce$|rJ`rfJ!BQ!oqpw~6xBSpU4w6pyI}fk!sbwL;jG$IwfofaPWveoZ5z*?zSa@UKVC@lbh@q~cXeFYemSsn
+tTY``?CCo&qWxfT=^~pg<+q6rXEF<rTnDSvHpvFDt=Z_<kV-I_Lw?8{)aRw7{S0z(YuuH+5WOoxN7cQz6_=(#I*74`&{O+6X@5l
Fbk}vf{H-3k`4Hv4q&G~>cce8`#Z=2Fp*+4Jn>?(e7r2nsR@dN^&6&rcyzf1SdgVkMHWLUwdV=lSTDy$4?$9SPevhPJ@X0J6;FZ+
vB3QGpKf=3Z5?jOz|L|e0;IrQx>4rgCl7nU@ze7?4{i@^Br}whKio`0F3b1Bh~JZEJMp40%;_B=slr>U#|`NsYm5?PEk;B_M0;NP
Dmxtp!^&a-7Tn~#1Q2pZJfz$cfayo1)boh=Lykejh-D#a)3pt+ZRjA+T})?Z&q$;d@aw(hjw^{Ex^2eggzr3E^(lInlduD?HvOXc
ypv6UL8IZiABuP#v%}!yLj<#2o+7(#IX;!1fLo?p#FJ1y&37T6yRAP81!>b;cVxz>v`8F=|AY`pZWj!g(MX}DPFgND)?xYc-T(Be
-MD_!Ras1kfK(EfBId_Ye{j&IYvcOY5~-o#Y~r+<CHt<*L0=r<GQ1^K2bXMAIbOt#=(0gMIV}D*&<NFGnCQFZh6RiHl5N`>kel8(
P%NIFxL?bHi|YoY7t8Me#TpSIL4%O%Dyx>Jm^McO&!R8!w6iVw2Q2E};TvY*N_$U-!kZqn3x8lBs;G&UqLmv4euEx8be~z3$<h`Q
F)PBCqFv&O=5L7!V0`;Ytjk=#5ieBi6U(eP5T5r;P%~Z^hZ|Ja*RsUM@v7H!e9C<E%GyPIB@6!syv}v0F2W*Lf)$W*HF(Y~9=P{_
TM&P!HCyjs`@F6S31U}>7o8YNL5YK*)hcz)<qbAr2c!Yjfqvl%&LA)YW}l}+%~6-wuhbu&Sr@xj`)~A*(wg!>+VTxvk4~#?2!D#>
>1)-itHX=qdrX1|b5t@OTq%2EWr|WWLJuGxnRe#ntt8Wq-u&;F5vjRBU15wkJ>E2wd{Qe-y~Wy;N}bbTC`a38Cz6?|n*#V8zN+L8
yjF9wd=XehFn{4t?r+Avdid^2bL5F_G2C4HLKU_y-?h<hvvML**{G+hSv5EZR(Snka1rEs;U27r84W@5<Ajknx2!S?He!h}Mm;>5
h6`?y8CKmAi-CnDs?ua!(-mi4mY#Brw=%^@YAyPX&=w~~0<J6wBkbltbF>^SwSuir<aW8scc=5fCV*&oUPW7z{tMZD(8xqsgD2ux
AdMus<344iERmw0&Gy~y?6#Vac5qQcW%a^m&4{Z`?x^(Wa<$aqM1^3K^rRkTxQ>^?EF2(5&~DcPCV_o>><K+iVOX+1CZTKH=JA14
BGH1P2|jqNORlCjAR2{uMSJI($&Rkd-19CYd{_h$QDa^iBGGAR@}2n~U{=Y&el*jzC(+@Af$Y@SM-F7ebeYR=ig310D;{PN&*DjB
(FM14^X~Dj(-N#D+0Fa{!AJh6CN@L*+~;L=%+ftti4fiZ!rk?MfLJ0;q;O1995p*+NW%^-*1|jiUsMq~TEVh@x^VwAI!5&4_mS$N
Kr)v9E_aa&tBCUL>m1_G^c}XICx-2b->*22@Y}}5kgMuHUD428ZYk$=wS6%b!1=yz;y@TmG<nuRE)x@FE!~ecDu(UM`#;XTRMP7B
2Qzv*Yp^frFq%-%+fif6KnTtKlUzD!WtQ~T!xtykA4{=DbJ+jOnrU8lcIMi4JNh92un+y`LnU}Y{ke5gmAo09pG;J8@x{egCaMvu
ltv#k{U$U-6FpxRry-n=3e>ZE11g&KYmedQHzde|4#vWOz-;~AIzO8!zc2gsOj5d6ix{)lU^3DD;FCqq)D3UAp)C3yz`$6?Jay4B
)w7?seb~ZyrLqECDr`-;>>oxva?NB6W$<iAmCr)7R1||*CLIIH#N!&H$!+`>eU)O!{VW_^<-mQMVjMJB>0KyWm@zJFHyJ#!=6kkU
AI;6QuYHCs(&uMf>xL2l?xQlf_G!Pqnec~CUlvn4`z>G|hf<V=S5maqmi}epRrPSGbZW?1PJBbu7WtijsTN0w=DT!kts1S!?t&}>
$h}XOV$bE)LCeMGMPxsmZtHW!)tN#z4VVql3Hc|^uuwf+Fg&tDN@Gm*=L@FVtO0`)4VP%h>F#R@;<)^sQ{g)^@v2u4Wt3vCn4Yd9
Egk*ukcsmBZx&^BECa;v(g=&GxY10`z=O*G!AN!vV`5lfz3_T#vm8Rer0y$>ifwP#^<3=_wh!>N3*&(3PCu<<1Qngr@8r&Tcnssu
@;=U7WDKoLoOkah9V*0HbG3?gbP&z{QKV{hH(Z$*guZIlKKZK)0*nTdEgU_+N}w)H-P7%OBZii$f9JSzcZ?q=X20zZU>@WXw23b*
02=*_IE><6^5WGZk4i+k;AYW&7ZO{B2^t9zK5fAmz}ti-7sWnesI>kq*mpB!fem^8s;qXK>hDpxWcU=f9y6_{*tzZSj|2C`D<*jp
SlwXF9L;F5`nhDO*T)(^*f^Vlawkj;(cQElMb+8K4u@|gLmCDvJjh3fTWGtWRLi5pFdbqYIW-QcgmQ!q;*C4-VV~HJOypy^_-0%d
Rbk8+=$bC}pQh27lEWOgJ5|s%Dr<qFjK!eCK@V!Rg$Ji1UqxE?b4%O2htFs97vmcy5JxnQX+2N6)%b1urycf(oo%qUMI2SXVq$RN
Dph#itvV5B4x#;PDoU%fHvv@{di3Ke?xu<ACygy|d+rs~!idbC(49DH?7jl5i)cLoHyDaDhog8Flc!D)AeI7}Fct_tFgg|r*}528
C+=X81iL&Bj(96jiQfb}WQ<oMG|oLCsy2u6-#!*=!dFYF1L$WOFOW=#6?gqivo?&eB=g||Y)vaV!Kw`Ek*|QzbsCdRvi{=zI18Yi
#kS!>F$yzPQ{vZe#E^AiJy|ePf$sx($yg9BnAnIE_Ma0}|H!M#vL7A1N;8vpovGm~XENN@W$D|E%oXy#bhE`lgx$6;1CI|QGJOxQ
Paxv9XV^Ho>!w3>eWbAh=4}G1yq`JbARL(wlblxU;HSW~M+SYda*EHOcP<YJ%_bb4Y>$DX32xW3Ab%Dd^6qW@_+X6Kz?OMX{!HhS
Se4dvUR)m9U2e5M9tqRRp0W}45@{l6K3*KT1@U&7VwjzAHuI=2-#DhVXRJ9!4~8Agz1#fd)Y}w9GL02}t6Gu`W^vpxiz@mC1vWTo
6$h4;tyG`Z&#x}Wqed1`y9W}xik_i^FpixMsQM(QH9U7}ND`fgFU0g%_Iyg%1Z1uE1uQSg4_}~bv~l!l&Mx)*!Rhk-p3_W2&IHh~
fdvNYOsuD#zX?_@E2a>=_)ljU@=L7Yqsuw}c1o2w1%q1keIaZ8YCjJ|!Zi&#Q1Fc#--5HNhd8PaJ{pX{?8>*LGF73LY|=K_sCYjC
)Yc?ZarPOidspe|sCDVjFC5{u{DpDztA%jsm3}QKm%o-3oZ_WMfs$RV!zgjwP3Rt3e$RHR-wBIRFQw*;uyrFS4xAo&$z1;aYgwx1
hU^Tk*EBPBs~j=j8-6PnWv?|LPayy)*X_x!6L6=NF3urPmiQ1u1t)wdkHuE!ZHQa9kV-84|Jp<VvC+AcSGjYN(=A^xHjz+bXNyn2
4~eQDCh?c`4dVLUvSr#2;|NJH^#Manj!lvxeVzb3bPmXQMyH21TrO_zA!F>Ge0n1I9zH(xhv{Rm4lS=o481lCoK8I1{9Wl+9mZgd
#f`YLu(vpmwf6B-X<GgMzB!vIuky=o)e&S=x)UxWzZ9u>npHlF0~@FP4qD*`K5sP7h*I#R<|=EO;J~D(kQ-R=r*1IN33+@e0O8mY
QVoyBm{L#*e6}J0Bbc~Goue4R0PSHz?OXtT9!lJ$F~PF;K~$!H@sCZtnSTazS~c<=LD6?h;#$uF4xJO0eXtMo>97+CSyL4_AX?}?
=6G^@199&Y-<P6QHZ6{(`bEg1`w=quP5ga$(UPv$gh4D)Qf=OaF<%`$(^7?6{`8b4{STjFFfWu{fNS1xn5E_r7JvC^Gh34w{FiD4
F@`kJzwP^A&6_!h=<cvxCH{DN!PPk@jjOV~L^`EWFD-*HM~_lVkUH+hmWj+8qml#v=7d^ANN6a0myy+03T`RkV*V=i!pe#)vfzhM
F3rsi;*v;O_$2OSld$laHEI3rm5=8lV!sTyXJO*(DDA=7K_FpNXTFN!#Rwcu!~tuXAz7Nx)&kRiZ<`uOnj^>+A5eC?mZ~#BSi{na
Wxl_#f9kM9p_+VC2Xb0CzdB>enHJ(&0-=gj<GX=zi!7h=uNB;D(xe%K@rjDG&T$?7uQ~7Qaix=I8()mwY^Y-U<NokrS>A+02S4e0
fKAx&CRS^nqL%LNeW{IOU*8v}_O<Gm`{uHBFC&hz2;z|lsFn!Zce{4o(DysJ5LMM!_S7G%rEpRhy*qYKagJk0{}U6d2E99cbn*;<
>D~bhgPZvf`N1R}`4iH{Cdx$+azN98Knu}f%Ob`=7;Btxa$pGOP262}z&%4vVMc1>-?Wp(u0{Ko4@sIND7u{NO?mX8y2M7Fgj2N{
l=^M|4nDAs%+Pb!CWLlZRGnb%r|pNG;}}@Et0P49w3v8FWN2xZ#xsrtO0;X2_P&Z*qoBN|WRSxfh<Bq;3kC_S>J%w=fFMe)TYm3j
hmQ})*?Omu^!6V^%|d?lIE8oQBc_U9CjJIbUyrUHzgJ&yE|o&2D5=1}ncx850`>m*-_|Y+X_|XW*z~y<&kKv%vy)9Z%=$s}SO4sa
URZo(I<+~*!JB&&F<`e48eE&jxqXhVI=i@t=CvCK`U3A6>hA5ZTXLess<pHJxZ#VvYK3d4xP73s3<<MB+(~%<zeinR8#k<T`O(IQ
Di2TY_=I5FBvUP1J7-SdwM1rad#za?)peCKoz2ga(WS(>Byf=>It=HBA@+=Gr+h2xI-7+$f_t)L*ISZex7`WAw<?wWZhGjws=4qN
HUF$yL4u<R;5~xDGv-}ZQ>W9p=x&p~MwC4A?Sqwwdvkbdyf2l`oP-`~Iia7KAV6s;6z972mnMv4<DPs{OId4gIuXZv7?6uyAv1TP
$39caim1nyoJZ<*Nj6b<&?t88=WflMr^}XzQU86oISXzl#9+IcJIw1+6BjkLg;=bF`Jnx?8Q)1C#l|LyF_#us9evsz#SzO<cZ`4R
+l`+?w)d-Cn_XOB30<`;u^?-bdi(g%+PhnS{nVc#L=18c#(4G_l2hYkhfZFJEh%*w*929fqaWNE^e+es0A7XJ0O#l{LvsM*^gU$;
x<QFI2fNhX8imj!Zjz_}oUtAWWsf0cmHd5^ru&N0u6mY2)G(d$c1M#|TcHz+6ulekyiLs87R&-vvr1}z;|I_qVaIj!PdzfVODnk@
jrxAH0;WnG7&+eQTa|JAJ`oK!SO+{r%D1OXI8JgY-E12deT^VtxSJIzk)jx&923c&jl(`Fw2mWL|Gdew08rvK16IoYbmBWhc<CDa
G;O#G=(T6<!eKIEtQ_k1=TwXi^P`L1W^V@7xC@uFwD)~BX+@YB*cmD5M!*i8Q)(NCTq8tG2*gad+PNU<U7P_+eq>d7G@pjygQx3>
WaDr21`XRNan;iqkPB6K<#<sF-Zw&OCq0}7`k#*D%@tXcRYlzfz`uf!<tYX9;|?B;Xi|f%uB<;6jo#7VfDW<15T}(5y`^9pgY6y>
mhM%)x05=Ri`EIrJ@A#+4oHC<?z4<T5iI#O0#S4zg`@q<aU0%|AzXVTsCAUBME_%gzY@OY&h&R6yM2Nq0IN5-J8G;B*LF=PX&Z2)
QCo2zkQG!ttu3GCH@^5!TPrm>UXdw`2w`e%8i+4WMs|zeBBWn=$P5hreG_7Lu|}Wl5t}yZj$W67NTu@=C9;I@1X`h}$!%KI6A320
WWSM=1%kvF)(|Ai;vZv3<_GU*RR35d)>NqgG*!x-`+!a`nJ#I1!hmPiswrA~RpGL|j<Z|#R7*37Ntl*an3UQn9XUkFPXV$AR4)jv
ku8X30F9)anK0&m+%l~tv2l4y^e*H5!I#jTE%2#gxU0=?GQn!V!xn~;X=uGn;-!V>O~#k+9dpJfQBAi*FJLqLf1_1lO?4NX^qoDR
o9~2ORGucgyf-PLi`-;J4Ct8ezxZu~b&x`mst9k>)FbxIBnwy~2}Y%FN<$H5blFAg6pDFy_J3f}b7yhV50a`Nv=jwF%lQN@Re)()
dV+iu!9cq97hOr(PKxd8wdCaH*q``oS;=nBCMGD5%psb1v}hU~?y-HHT0s)dFh9STcNl8URq$*Nc+316376KRZL6EJIu7IVEa=s_
Gf4S;_Liy@Ustdd36%aHI&>myjkU7rcLf>u2EP_<ZpLYz{p7R88|Yx(gC>{6`gHLMNVU{%oy<kRmCPgt-QUn5;S4;+ziwwJCL6g8
XbDzow<;PsdyRR&P1{4yLSl}$8n^qW<7CUqhFe8~*ky-5cD2lG$NPC8qtPD*?Z6}->-_O8<<=9$N?`A|5xMU^O03%ac$`NWRMGSE
mKf^(+DJJ1M48sotkm2}+J@|^SRRcPsTWj+czuz!l5>_z@G8MPuaU=fKcCww&B`qHBaCNpy)FK>RTFeBcng;jigJYfIy4p6(I1AX
{!#4oanKXPKZFWa-Gh%W1*+RC$|fKhX3mp6;gWmMb&HS?I7Air@Xw$YRw|!<v~H>fSC9E)-rWsJA!fg_)Og}9Gl&VefN7s>uvgTV
qsnOhgsetNs+q+~lsN7tSkrXU*vOi>7z;sA6%B?&M2<`+ZHuD9ur6~aB1r0Yk^S<&6SI4y9d&9>=2JZou4W+g%A@jwPpg**DOeOX
^$JrC$qecZS1e2f0j99VklK}97)FZRfHm3fZtBeYgLO-@&wWnYrTE@am*)kY8g~QFlHp}v+%I4_-6>pcQSSX#zzLKLy3l>hTS<l}
xx)@fbtgNO@H@3{N2~nMt>+e);%wTKfYT|nwT(`KWvwZlMGf9V(W0OvzqJW&VC@H>Z~xBT#9?iELwAzFD>Tj~1zW!ryo*XL6TV#2
w3#xixuiKMv+3d4^LMHQoE92-=uy*PRhocvib&=iE}(5dr&3F5oL~&!3z&;VwnIW^0ymg-MaIQ&U|f&J%t`NBCR9kYr$gM72$PCZ
K2DwA&dDf1^)B;BP9_6I6tc#IJ(1TCuQyffiOVG@Ge`A{e8HKcA?pLbQKM_58TM{++OUCsJ0#HuFvtqk`)O}!R{@eZ^J2X;tp@GF
t4$9L6UG9=eAEp1h!^?jVn3GH27lK%HAra}NCc}g=596mg>T{2qm!toPVho`g%XyvX%O`?9qbCYGC%X?lO^dpWMA2A2iEIe3gNtR
I7=M==1g@-Wh$<fVig~>DMo3;l+sF-Cfap>m4IFvdV}POFWGd3rBy&Pa0(p}Z>6nnAl}kE<SCyR<JtflEZCs^!DN)Re**?6p?OXX
C&<s2BXlc1eUrHP<d0%aXNfhH1lPe#pcgWEJ+9DBtr%A(RkC_A2wMm*v0TSg*Mc<^z2j|&iyvpoA*NY`B22Ym-hS>%i*Jcr37qnM
A3_@p)DLSTmy)yCnt{BX&A&1wLa{H>Efq9&m0eeq#jhI$EBkjS2F<O`wKv1XYV;an#%%P^V}(b!E;MRno@lAb_No&VaAIhmUVybx
prkrvtOd4_jjo9RPcit>CK$et5jfNy^%W0Y_H&7-fpxxvaBOb+QJ*m!M2e9BV0q3`Yu@{Ke$cK?_5It*1s>e0y(Al0iP~pef9cK=
FUQY6n<t7fM)61$ri$nfK5R*n+g^pBLUkpM=EG1^jDH74d>s%HjTwL6_WX&X12W>Rec3+3y66iv=a{TYZ>YnCO0enJ*l;!*ZLMNY
vZE24Ecq&<Rh}R+hLc#ZXgP<N0wJ>JKyrbdCtXf*ndl_W+(gdwEjpzbsN3hY4ga{-<J;TMtqvr8zH@Upy<7-O&M`LoB|GxO%47Bv
TG>`C8sC4_OaMtM<8uWONt-_2ghrUQY7iu#Avx5GTst5vO<5?m66Z%a_&rQ2Lpz?g_Cv|MynI*|PVNf4qx^lXn-&b8wD~3^JQQHd
w0PF2>$u};toKEE`!q<QD<9bqd;Z~rNHx;E__~reRh=&k03r*=kcL40CwGU*?u=(WL^R`{8Gf!MhZ#!O2Gl&7mtGnV>8{5>1ilED
0!Z{rO)S1bpGS}kBRZLTF9mE_(yGO89_Rx95IWR)RP{pW-D323-=PHBl1JCzJ+avEk_b|yztgz+oCU=CWQRWfw>%g?0Lk<rzAPd7
iI0LS)Smip_Uc^;Dp!kp<WRjWP_j9JH>231TNymP4<SFB&a2Y~6PX=Vd(S*ygJflHD(#JSSd&+)3xWkev1WVFfDgt649UoQ-Z*E!
$34AS_*k+51Mp!pp_xO$Qm96honYpZM~Bqjkz(V|F>jX*x<|2Fd*A!}Ov|t9i6$%pv!KjjjD5`0)z9c6P>5S-{i?!Sl{KM=&GtEY
NMTGi7Nw9v%&P$8Q=DbXmH+A0|K6GGeafoKaz>4c5;svEZoxL@bvGeCY7R(8>@}g}o|8D}*@8}w9}xt1(zi-=tt<|Qa6qXJOMCB3
+KE|?N+3=C*LUkM&ra|+!w$M!^`lmP7vx^CZ_xN@z)$!6TfhG9L+Lih6X8+^p);4|?V1WIPedZ{-5oO7n%0S)x^NKo=8hM%J-l4)
Q)6YgHVSl<^TOGn-rGMu{^8cV+KAsWZ|J3bsH|I^F}dJ*_@mBt-?f@j@lM!BZc^KqYQv&dXH>9;LJy)=tuLtGX)jq)Kgl#Z8z6jI
ry=9Mo)EDclOW<}D$0lMRvp@SEYyOv!Qq*DG6X!<0^rBCE<DnwiFD%iD@CI)F{W#a0im~(0d3{9zs9)&<D=eoirm|^##f<$`H?CA
LC!pcln$rJ7^%RaDaytLt%0T!F^D7jmL_>kPA4YSs);kwhFUik6b%Djb_aMiRdWZEMX*(*CmdB|S!TYd#1%W!m0h?G36DXl1o1dd
_l>H0`H%xsc3;-sa=#9_X?<14q^z0+*UPy-l~HVgz-Uwa+nG&a81K!A7puEE#XC0U99pP_%L$o%9?g&1D3xd^!7kY1_smw(CGP3M
eB3W7quu3X2f_FQKr2xy@9AsrL+J((a^r1eM8sHHG@;f1@o`4iGG5cs!xyls^cUOk4;*jkWubFE`g}2HJcX2crqxLJ{T4FD&ijio
cUxD$7ZO3X0M6UF`bPXK(T66Dr#@aH-Av8tf4sz8!<XS_y%smJOkLLClG;u9;+qgY!xPMYtC{Mk7`@@|TuNft6(U&^G`{inem?Ls
lz-Pan~eaPCq*Ph3)#FZQ9&6?QkGTb#32&1X(`~by#+Le)bGrwi#2fj)OiQQNYYUx3^^zX1wp}VU8x%3vUoU%knzBOPwZRrCz3^;
$+YtbObUg#%nyF&L2nv-!3No;L5dfv_iI%Hfi`w+nZD%LTb1)atKQU3LEY=8Q&}G)CVvQL1RsQP<N6`ZMbIx+6&VhUK<|fvYe}Dg
F+E%t28Wy%W0=&bh!sKgMO0_eb2B+fIJwTJ>5p7p{_Q3YZm?I7{qq(%3#yB!q2#64q&=tg7v!F|-`6$*5i@@zj2F<2vvFv$5-Ygy
)aq+G!wxIM<##>S!gOMMq!~L!(Wuq=Cs9(JFMO#FFR`^fQ2dZ*ZWh1;U^{9vKJ&hZGFeS%4;6x+uoY_W`{7;?YHzla{RAmoab*PV
297r8v~q0B?)ziF3)A&~=KULSY_BIy?mVL-`>{NvF3QX8m18cB&r#>8y$mTv#Ql))QF=TLz~N<sJrP$sFP+}6<PbbYXhqr9b($KU
zblhK<k(e{WFq%LbtJ;Dq!3nY429zXmS<<(<m=P}Op2i!E%5QH8RPpWQ<X+OUfE+jmTO8OY_{x;w6$iNt_NMJ%}n{f$F#3bBP^HT
lE5iw%pEtaUDO)vUGHaFu7{<OoLODpqpT#&mhpWB38XTT0Q;jhOlR)b#o`2Utph>iTOvc;P|<EbPiSPdY<a3!JDv!2^u;iKR1<6o
f<g|Y|63s(8vU8QMeRq__tP#2r#1I$q?YO-ZzUDyUt9~sguSOys#WdW5*6|!M<rRTHU|{u@`XKf;gvtCO{=May&uJ|R#r5<rE@1F
v@k&8i3tsOZ%uu9dzVU`ESW-n!4Q<RQE`<C7+eb^bDx1PH=8mtd!;Cx1aJb-GDSQtEBPv5;Ms?(p;JlCDX)m*ZpRnb#Z|s(ltLIf
s^PxxQ<mSBj30oh&Kn}+sl6cAc>irtMp`TUg#94kEJO%8`ecFcQVpq3e@`WAS$zmt?^ZBz$C&clb&L9l#9UIPFc%V%g?-<|l5buK
>;NGJtTv_x(uqWZjuHotxutsx`0n%OXNiSBvG<d{#8Sh?zPjT8^7==2#5<%ZBS6?lClV-%5Y-{*&lk?c*mF{|W|*Y}Qr5;Qq}>db
x`@g_BO8~`CAug9*n3rEy_AcO(+TxzRMmpbJK(T5|KJm+xKgCKZ8yz39R&u1#3D4+%Qv)|8?M``xAyeuV}Ymp7?=pIB@G%cPIVbA
=GNvet?rpg^SgS+N!OZb?5Q<zkJdwigEfeT%f_8A)^6$ryR_^9a`&!3MVkFNqtkI~)ShPWQuX~zVp5=DC~=>VbcLfl&2#qWELL*H
y^za7qaQjpd1znUP$5-nZZ=3c6#$FaHEPV*=s2Zr^-DI42LQ*Wj^<H{ta9pG*$O1U^uUVWu|_b+aMI03;{1-UlNwI1x74^!bd!6`
sj!#VW`*m~DJF!G>CR;6gsBzj1*gpEN=~io-X18iS4v&o5tia3>56xU3!4M0^PL5&(n$zu{&hN{4G_&5>}?9OfrqUCt=bvqEXjhk
KO^?_rT`BA*z~yQ3V0feF{FnhGGMhxaf+;&uT=P_97X!(&C(y2xn%VKGGA4t@T@ki^4hB>?mGORmeofRzTO^esg2Xr6oj@``CK!C
a%AKJ#rM!SFytXCCbDLh3AYNQ-nKbbsVT?s0cesq^&M+wYqJL;A{NlUZ~sYw_U1w?SXT-doL#tE$Ry8+X0{D*MPn2$kBKwu$G7g5
*j_UNi#FHkAS>Br-5p>s^nsm~)tXHzr0$VQu;Q1<tD&Lgw0NtcJ47F76v8Ley;=_Fi3Au+HT(^@QY7JJjzTs@pg|{DxKdPv2`)#v
vsXjC;u0{y4cn*(lqkZXP)1N<HhOcq3ZSOJHPdkp`NvR4!;*Bm0XS*ZXFH+P3CuF6AN2~mm$pp97R&pC;yOYl&sx3O?&@$ugLxLW
d$$iNuV{Rf!J?b(tGjJ|=t^PTP=!a7QvYQsorf!lkmtGa#=hqI35Hw`W0_S+W!u&u@e>oAqgYCeg7-}=9MNGs^#_=L0*VdONQ>gT
gNVn1oSMo~XxCEUYd5c^*BEdG3`C`(w|wzZC+w`A<j^nTj!1rL#Bi3S+e^5c2Nddhs*3R;u1$c#9)#SGu_SdX7$4plg}a@~S)PZm
Tde4i8PAC6@|x0E`~36SrWAQYY@#!6V7ngH_VDI}A*sCR<}I21qE_i}6~0p(0VtMgF-n@iu+qB7Gdq)Y4abHAS`ru{Go5;$T<xi~
x|$$YkeyzGHU*`Jg`)q6)n|beVOf6$HM3r@Zf*M0Zb_@vZ|6rWY18wiW5vX|cu<==;>vtgbP{4+mqqf^E;JO6?J_eeC#v71d`Z*O
>d6eL)IW#*1WHt2;xqYn+Qm+Okor87sry)1531OoT8Eet$e`VnipE9>f?7<XcKVU*soR9tMNS!RtU1mm)jsS-Sn13$;G8KYT84V4
K>j!exOiZEWhAXrV!~PsxwP~wZ@dU;5zkvSRI=x$ucY}@?dsoidbAjjTL&J4!>d1n>H#B<)Nqz&NuV^Kwu^UL+A4-jt;P{-8`SaE
y?K%RH|d9i<eGc?SRqZ$dP*_ACF;nKK{^}`P#)3m@S)@BzFo;?QO~rRpu5LJ{;4I2c9W|~{DDAo@BUU3g5f3v`W`mph<6#`cU)#e
86VI8$CB6P(awG1P&WU5s*j7IpS(;oO_?o(N^UIy!y1CelC0YK;RK4EP<xnPp6>FQJQys?#G^<zDFvQr=Px`K9=nlKQB;?1`7e94
RAD!X&?Q#@b;tFtd3E(f(>rV5c*ES(-IQ}NXt$=z-$dHRRhL^W=^Qo;nt(Hw9;JJ|e=HzZ5mQ^}BWA{6UnNAHfolNqM2fIN`uRVy
I~R<|2x-f^)Dc)JXxvBex((Z+#U#>P`+>K+pbINhi>BAjYb^$-$1W*}2S_VO+Yj`d@*DLxe_KF`prf&!1E}XIZ@o4{*+b;OEUbw^
lVQmibfC&yy@k;w$k>qQtg{k<PlxK$2cJ~=uU)eqhL3eHlgqTbqod`|f=9nLM`7>P?!=R4>;TVKfkFzYU+q;U&7aR|3X_K)2#Dtf
VLL>kR-L)&0~NaM+*JT4<(G*rlzIe+9xK2Eoa)Kem0*s``G1srEuKlCtK5cdcUqENV-s{}ZH{yM?OD0wEyH0Y>`C{*)u!aGmO^Ox
s;7m;;3p@chl!@Bj6DZ2oxYukM<3@8!>+IEA-$W^7RnFes64pL!ajEhvooP@j|Y<N@cixf0lPX#UN%ROe-OpSykbxBpyLgt@)yne
W!!c<zz*U?(Br@{){JTTLD{y;ztF6F<WxX@f?A9>Ttznl^a`~A>Q~EJe7YJeS~lSD-WfH^8THa)t758NpmTb#@|XGcB=P(PGq`BR
21E`3W|^fP7-MlVr1GY9T0sw2==&qVb{8-vzW=6As26_hnyYOjn-@>D9IHYF=Bw+-(gE~Dv!cbYX;{>Q3;d4RaT^7@m|TD;dJdj(
;f;Fg%>&@l?&8^wz@8y0QVj-^?w@b_(&`oj%4+4f{3i|jX(3eK8J{LxkykM5r+_Euaj3N%c(sEffDD~OcAY%8>CgX1$MV__7*+?3
^#_c$^-3tR!~W*p;nT6+zBR(#ZrtIO^kg~@RLTe_Kfc)hRUBHc^xBUc-wZX?`(;HFK0utYgE^Yo1Js;w!G`uq(d%P*AOK<yhJ#MZ
pERVWI_ZX0`Gnd3c_ImrJt&RBXe99Db`g<ZD15V@w5Glxl6Ib>i9j7c{`(Vx_K{SNop&vu#T0VjW*7Nu|5W~=X7&HUE9u-A&F#OT
4S<Ox_1=go_?+Lw!Slm^GA^I6M#+LVWEvv$^TMvbs4p#&V4IpX`r=JxI#qo5U$1yS8`#aADOYsd3KG9NVoOe(WT2Xm%xmeHSk*Le
!~tR}r=L119L_48>P`{8&h>mcBGvUd2LkX>Yt(OXa&)lxyx@nwHxL+Pm}yxixlngHnK}}sC@(#nZweLpl1fe)ys^t0+rG>ne$XRT
_RIg9L;;U)>|f9)_*r2UADDQSI9mNSt8V}*%zO`*t*m3VWK@Ctp1p5J@5<lEor!Ji1p)}u7|lSnt9w_iMB2fi09Isz#Dk9ogpc)K
p=xNx0bei(z`gFO**#<g?Rt}9!Qp3#e%=R%6XCidBO`ECHoy}(B9S-jbfBVz)uFYIhwB~h;63@e20X{~52_rD&xmRHF@X8|)!{aJ
D&F$txgX~w`{g>5$PM0P9NgE+E@D|AfaK=p3mTSXEyBg6AI;@dy(43ChXh?@79~bX_0fcnA9k?2(nCPCXsuY@$mUL~=~5t6hnpip
OfRaG4Roro6J11Q^U<T+DB$+vHMH*X-iUzLa*wZc<HLy{GsE4aEXu{#=4=<$E2^S#@UHl(;#fP^ZCzoz>$Xa+<Aw{1ac8Y~<YN|h
B?neu;(?YC$J$Kb43gf`FRuwTH?Qe0GZ)C?%ywJEjzcLzWg4)-w_v^!70dOpz4hnZhk+Lx$Z9-UGeBh3$}^@$h!pE~aM?EOnhXw&
ecp{{g=-mu8|GT(5P@yfN6{hv>wi6AoRET&Pa=?5P4b3vVcX=ubWRwF=flh>k{?05K1vcP4u!FnD!>#r!<$@_sllsrw_VBa37fx^
c40tL;FAdk?(o~XYc|P{pv<lKWh~Eb(<B;pU?l4zDxF5{HGdh(1y`wbZ*;2uqBX&&dmf~9rq6=sL?@7Rgc$Y8pNDiU<eMLP8I;|A
OPP&$Kb=QR?J6DZh}+fr1;R4Dr;$7l1aP0~Kle$G3Gps8FbGV7kcuUuG-Wf<CAEJ+2R0JITz^Dec~ccwb5hjXH~_3zM<q%`LA4rd
^$GdL>gD-$q^r7tB6M_NA!~NrtJZ5o=OX2;L;6NdZ+xQUf&XqUGGD==pYN?FwXmo$C1e)LoyuG%JZLxWK22D$8H48*qhae~31uIf
=OIM~wfJ5h3dx=a67IrTF?pNA0YuALJawFyqt8wZiTK8K-l$9?P`2~HtB^eMhjlS?ov>UP_)<iPU<B<Stp2`<h47XAXeaKfhOQQd
MSygB#(!}Su5_LQ?+`qnDVNzJ&|4I=eB1vZL~S`I>|qAC&HXugdCLp7y_ghkEb!hHx?EIA8$P8USCr2R?f<eip+{RYr8>fl+B{D#
W%f78`Woq?mb*fXTUfo8&z)p>d3Pble76hc6mIYNNAC$4`4*Ul{&YM{={bNWRt^$SC>dMw0U$N~nt(R2@?^8ZIU#N1h<y2tQ+;a|
@AmU2DfNu@@fmJ%_IMZ(<7V}mc}v`-<$s<<7^+zqfDBnqEr%J+?2u?j3wa&>=1K+7GdKhF)^OPirr)}d!8O=ECk=59)-WYI)19)W
&})?wov*f8(Qcg<Z6zx{^(}}A?}$x=Z2k8`$JjA$ZTHzP&`<GxJXmLhoXqLEbYW*CcM)_-#L~SZVSgz+T^!QxrXiiZD|ARtWItt{
vXb?Qw!4BUt8@xAExY9nMcuvu(*FratQ`7A-y;FHL-sYd=Ix4R=uGIl&~<Zdr&Rfjr4Vo2CIK^=D1)%yf^*%d$6ghM<D$H?Y_~Hw
DS8UA%fdX9(<D3*G!yu}KUIGVnxy1|Y<4Fabvf15SIPs{baCj;jID!$spa0`V7)*N2AOLG#cv7C#R#n!0C;l7j+3ewt&k}_xaQAv
*b1wq88E9=QSAvn1x$F5wOS`%Me9`=4VJ3Pw9{^0B(T>G)TA8LjdZQr%T|qY%R_rxvm>{&+r1mT=>yDB*R{fIBj8B|_8z=J;wVNA
lGQm~Z!+PP8STQDj`Nc10+S1<7)*-I0T(nLT;<>k1x(ZB0PA?Uk2Q6qWAI^;C;gFZhZH~Z1xBk52S5kQuQk4-@&^j1-P|X6+sMS4
_S9gwm@-TKC9~wp5k)KFf>g@s|J`;x)o!cje-%b#yhYVXr*Uy0e5Pm;Ew``+hX)=6JrLKp(`R)G>gaCAcpx~+GVG|jbl2E83-N*Q
)f7o%U-X1I=7*xBx9mOvAB1=IX%DNpj-pMdEdt>^G%ae_vN#GD2|{E!-U+IdGJ#rtt|@E+-8nFcUw3IvBO$U}gp<3&T4P?Ct?L<m
RIoRrHd4Mz<pa&%e1<cA;A}Pd%SxtN_6YD=if1^})1rtbs9Y&j_f4^B>jmCb$Txig2DEJy%+b*q=Jn-yK^qF3EELJb8_D_jqW1==
^*GP~@WY!$L%HVX%oj7b>83W$gp0Y{r!uF20AFR3@6G5-vRO}47?tF_ZWTH#$zLO6<^w1$+GJBkL)fhh(+ChHDy8i)B^)_3K$@AI
x=*gG?hfY0fqOu<G9K+6HBz6Ih(Q=^c+-aMyr@4RSq4Uro;r^m;i!)o286#Qr>kxS2#-r>7#6^1k&9@M=_9raqKLzbep(eUT;%q_
mz9W8M|xjA_A*e`%M&8q0ygcyySaF|pYL`gou_^3i!yPvd0JJ)tE<kvceNGm0Kp}ke-|`ApR|Z4@f2XJEKfhXN`F{}243@!6|VO-
Yjkf$hrmrjPOjZ#jGZIpY?01_d_o{HEr+3GL2Ly7xhQlf`^OIFi!A2HjNEtmrZUH{pJ^{DEmI6}<S?(^E8hLwir*`ZcTwaH7ZS(P
3kE?fA+wD59<DBjYjjda^!Zg8;8sn_1}G?ZmD9o5mf^%>CEfiC)&H$|Bc;4D-7)-+*GJcaR5!o{uW2mxRP(g$15EsTkHtKlqV=@P
!VZ!sic?k+Y$fj5>MQI8-OE@2XO<p`cM#&zJwDy(tqO^UHBdjEAn_taugZ{CgqJ7enLi3}+Q(|ADMaP`-$5a33vlV+{?)+Qz>b-c
MA`|S)Rl2jH4`WSo@yw^6jT!Or3BO(qUj!O7m{Ac>DK)y(}qi(mbmvT1+A^xcO@L>F;}ZmH0u+!{t6y&EYpkyomBh|i38daCYiMM
yk<L(D#^5_<;@)Ktp%`Vc04JCjy`C18xpz~;c|a95H{r|;{mF@5C^2ULA>Bc|9*2<+~-OYD~*u%S)~gMVgO?n@cyMMUMe+&v_o80
%_}=7W<g!?{rPgzrbD|q!2G(5C^dfX7|=|5l`rcBalW?PQ?{G)?N=s$cwCp}I-*lo3;5;*jRm2H$EP(ElCpM-bl11-Ib@MAI+FMi
G`IfoC6mi@Y!{dhln!CrDsY5T*{(Yrt0BmkEmWlIAqe!7A_W$1@wGJ-`TzvpycPzr{-QF^CW!_yW`f>F2_VngAULoYWx=1S2o`A|
88g9MbOdBvWOm#r%jey}w@>3bw-Ii9G3aJBzoPC=A1$lP65M@XoKr=1VrFi%loQXjV0k==u1iW1pV12ZNh46+Fgb>}yFjh}VC;BQ
1<_|ybykJSxts9}t%<V;7agdwpubwy3z3T70b>8(zQ%3LQ^tRn_?f5xRlv$+%Ob)45(;kHBK(t959OrS{_C}s19xHK`nt~`xvr*i
%-(@g*w|W3Re-zLI6}&r2M@xh)*G@`LER3V&9FgC{r7NH8;`%}NwHs73U+xl1Rx$1V!X=OvnI7){g6G$+<E4*lRyE03DT?S$(<9l
6D2}#PEBwBd<8r~>_3A+2=@_0t>6LT`|J!O>j%O3%&sTsk!Av@*-|P@BQOs688h@-2<TOeO2(Yw+q>6Gqxjca(A7%a92-|DhR^rm
CCoJyHD$#F;HR0MGVHp1KS0;|>XSc-#`c^CCVl>T!vFw@1m%R0GB?erSH$%4prIwmn@4q}!YF<bnr@JdbRcLij1B+5A{qdHIO|82
DqTa~S?J1BF5XsAhZJ!N6n+>y7_n#<%oU1EiwE~Xs}O}>gRTpKt)YVGEI2W=YCx1K^r~J!v|R^L?a$JUrfd-nm8v(MdfEXG?7a+m
ZlJKjB<P0lch?MHiy$b{x2}76MZUj}?{r^A!RaxhaT+6q%TlEp8)F9GbRR0x_V6~LqT+dHj(m232xpGM#d*iXbY>9Ai_DPAQqTOa
(`6x#?Gi>2!+T|^lT#Uq=j^fgHViTpud_-(zs+w52#R(`8JP2-kw~SQuoMQe{oOuJhVBUp__7w7=>1G%Ty*oSE(T$;DNmxOyxUk=
tS#lRufv6X7i7=kFWR+=JbF5}aYnZ#1VzBwuzLf9YUC=QYB+wgVm*<d2?HZIsSd!4|1@YJMj#P7*T>fdV;!#snLKrHLUtGP6iONt
8{p8^j+kW2YHUooTEj3~rnu}RQ~aI5cR24R<%grTGoepT|1;Vxr)#*7UTL=C!$S6KPET5p(`el|7aNv`o*7|ol*I4Cp}Sr_oq)5R
w7Af5CqPU}A(?lt9J;IhU7*Wqhg$C_!q6RNCQ?LE-(&Zx{(GIVIg}S;$-arzWIp2q#yg4GuG7bPYl7j-Q&B$eLNqXij5-Hcv<)Vc
gFwc==C^{j6Vg#|k56F%`ZEr4wH&tbqk~y7Z!ON*y_hR-yS=ynj-CU_hGCeXh;QtiAS%zF3f6E`)?uL62sDZ(MDYu8Y$`q}FYPCQ
XL=`1)SdP;%iu;Go>NgG6Dm0adN?^=k;RcjP0lr->}(AQrMK{En4|}YT&Q*StNkLG^+B%$1W9yni!4Te3Q(_+hXOq772X)?KSNW>
;YgH#bO*$uxJ4DKYBzR_qQSMPm(;|mB@=cjhxtpJa4&KXp$bC>IkrK$!?`%%&WYAWRpgxNDs$DuUYCRceHd^W!vr^F3`w=KbYB;g
l)4=KOMiQhLdNAx!E&6zZ;glfVcl?3%*~bY4?@2MZtmk)`&WlnAR`-~_JdXZ?G*)|10_%pfiBW1?0bn0i$OX;qY27h=KHl7K?YFV
6q635f6X&iHw^VN=<z?L4UpG-BZh<GNU!2p030DC`pUz*{|Qh7V=S8$)ty=g5uoUmZFuSh)w1~>M+7d)9`gVARZ4MhXKz41E1$5j
=gls4bj6~PAhb`XLZgf-cw@^#900Iw$gNx0k+ynaKYjzZvrz?Ae&rZTMhq8I_rU0aS?XlS3BB8>5L4LyDt-;}?l6@(Ne+(;%aDT8
#4hD>Y#+H*Fix`matk4LEN6;5?I@8qHAG8k;3Ohur!B^HXwE20iHpmSq^8zQI+O}}i{H&7pHRi^fn=AvzAyEZC8npJSOhzjQDMb#
Yg(dg$gx`c)aPjZAK+|s4yo9ve|55~S<`o;j|>>BB$eShyG6P@X~9VNq9Q0fV}#q&HKO*5N&hM5T8s(_!?TIBaR1m0>~qk7DS2tl
XO?5?V&8)`<he5QIfJ;x2?^ZSBV`JSt)%0?44-rJ#N2;bs3mAveF<AYJ|P?*5tg>D9p98^%7L%+&IA2q|4^hJi-LnEvW~<H1uzUu
Ccix@HJeOd3(wP)aW7G?Xin1iT%d>F3T<2)T2P5Zd}LC7=I<+d1*Qgg)GnDRpR{{VM0FucbN=ddzpy_~lvj7LA!B|G4@hbK)&b5w
CrOiO>jvhGvswJ8H6hgfN`N7akAhyEEt;Xi&Cn%oqdt7)$Sel$K%+ODdB;x;K&!}bAnK<=*G>!&c&fJGcc%^DTP(h$&oZ}zyV>Z0
@W;(xo0z&mxJ}6&Id))}uS(E8Do8OZlq^dVG^m`4TkE#lPXdN7?P#p62208mpu<#M(a+*;JIeDwl)3YAG{o$Tpm`t;R}5fxTdreD
s;it9QQud^Yb5z;xxCVBTxB-MKnmcVsntFU4L~G0YZdSzf<NPwZ?;oWV+EPs?Ob2{BLd*i+Gm5P%=!9i2`>Wlb$fp3R1AI;6Qlm1
%{3K0X;0uAg%V}EiP?alz@{Kj<GFLG%nl%>*`e2?U_(5UM`u=CDW#Ni$5n<<lpq5Hmn(|Zy~BfpUleWuZWh$^Qtg`8+eUza#iaes
0`1OkM;XQn9T!z=YfTl8{>L+$T9PHHd45((gR}$%C(Q<4M->Tn&IUZ69@YdeED+sGl~dEj*?|CL1-`XxwJogbjSn2is)Hsaul&gs
7KvuG(<bjHqNjEd@7*q6gyh(Fj5y&1uTnuU<Ys8oDfa=EM0RVqb&Uf?R*Bp5^>%EswKR97LMNumj85PNGyZq5!NTTC)9*Y=t6XMo
ALVuN%93;$^xa^koQ@@ChEJSF^@{HOP5>2S$l)ny64sQ0XOU+0A|?VgKcbob7b)w|QrN8H+|61705Gd@W;5?y)Y!A6{r`662ssL5
<y4V%emnCm*#KT}rxrsFPb+ScIyM@9p_zG+BQt`X7HS58zAYe6<o7kh`Rn(ioQ<wW6O(tSPR5Q25`*GU^L*n$(eFDF0fiotv<PtM
7~`Y^BxJT&)UoQQL+`OfbW_9WpZqlFe_F8w$@LfKuMJA;i-??dkaLvLP~<>3NRdk6Lac9jutl0$s4sj_O>m2YM(Km)-IM|_>Nm>i
HipE1lU&W97h#v%bJfk1$wHd4<j$VZ2WVbr{yxpnMX6p@TsGgk23LFf?IQ3tK;*}(mTYK#f9Zk09L^Gu=3*4pGPrisMfb;Qup-4C
!SYU1C|&4(bI<KKEG7{5YtWBV72M)pQOZ43-o9QN{!p=LDeTmCsq(!aRb=x0_9eFXVR+~<BdO=5xCp7hiAc)fQbYX}Lhd~kV}Y`g
l$UWW-@QSjnd{CqO|GlK-JK4Hy+~f?iXmeQB^{$^UXrckDH`f)_IJiFwq+P?(*;HNt<4ER+#bzui-ZeqIwy6~nvB2)f<5B<sL=oo
DQ)twT(9AwDI`+cEb}~E><Y!d7NOBItUy2tYg(m3#GrJo5{^~vn?w|6;T0eSQqR+(%*w`&2MzM!lP)_ORvMwyd#x_))5-YYYKO9B
h5`<f%!IOr-b2G!;4I<W;U>L-55HC(ycu>I%JPdUrNz#o6*YSqfVw+YOwUyyl2K2qYBqAYTuTK*|Bd;%%eHX~wf*XdhntGyTKON1
pb}YZG8nu}y$|j4x#V0j$mT=@SpW>lq&m1j4iFEGdTZiR*Lv#s<7>B|o`Eun`GEvQc0P%xWnKaZXp%56K0_0stJk9bLsS9oTQaj2
{Z^fiQpA1Fh<+ZQ28n)cFq?H1a9N6W5UxM9rZuciHQ?&A;4^()=E_n%UrvpwXn7-QBgH9IomRjwa-E*?b=D9?$T?m07qw(!tI_w|
e*#;7rmMNEFw54MD-B3P2tAJH@pKVet2i;>z*mk$$`7DTOb46r^w=RTm805rj=Ej07m<A0M|0hN$~Egd)Zr?Y-)WB%Fc)<!Sy3X5
fT1y=m!LziV{zDjmf*DN++dp`>{+R`a&Rffp7vy+G^pBr;frg)at$v@H5mD>;gQ7~NKDlYs-Sp%xwOrfSc(;BZMm4^d%Tjkd~bg_
H6I*|xS~Ti0J_mk)iODAYRlqKUK`_<31;W31*9;Q8WuxDH_-nBHI{8sk>Y--p#^K@K#Xcqmk*f@u3kxZ(q_GIPWrrP^ElGd#x#|8
#|#E-ZDaJ&AHq@0Xt0UMKyxxLTBwM64rovXPGxMxqn^=3UZI`GW42+t36JBom9W8P3=^9S0og$6iieTkDs;F^`l+xuqBWy0IbJTR
`XeTZ2G&98s`0c!;nt$A$7s$XD1CJXn>k3HEYAJdCG8PQc&=KG2CA)N`n>^i2IE~sKbf3Z&A$AScNm7txUUZZj5l^Qk|vhFXO^=h
@)U9a-1TY^6iQ(OFV&vv{^G|aC-840p{s*V1}Y^X5v6h-aD#{$F1?W|00!dxHO*`WpwwE`9*B$<v@p(H19G0%9z9H*1Yblo<0ndc
hILk=pJyuO`C^E@w-8uw!p?Pm3TCbK75}he&8;;Oa!}Vpe$QyJs_ar)Zs$T7o`!9(p2TJOq8I0;$UgkN&jykiwZ7Pd*{Jgg-0GQC
RfMKd7Q?n$vy7Q6jM;^*&nYKKXE3dV5%-I<K5TwBZfOt+!AZ<&keC*?l11Is0W3tBr8;(_sVuGQC!s;K6p#d<=`Z9Q0)87fk%1zj
jHj+(eU?cQ#qY@Fv%;!32P;qhMW{`MIti8}zXtD19|{sF>ZslK>jk*-qt^Ut@X|s84CZN4g+=ps9pEN9?uHhXJ~I`=lZY>~?S_WW
0>ed1hbk4oS6zVS9zAU~C1{|Xp*Ug(i!%;oQ-FmTmS<ren<OE1=-hzXgWhww8w7t5K_K?8KfW_5hlx3=04AfCx4@5X0VRyPj#P>K
V~FZ7vcSrUxPnyD<3aIH>?61A&%1H+(J6`CD?L&0i}GZ^J$^OXHpM691oYRbpgj`0`PxBd$mt5)x?-VPlx~MT29ZwW!aEYR9yZ>|
I2?HN8`_Lez+teaSsQ-F<1j+TGC_ao&MAMbExEUJK{dF&qgHBZ>8q&!YNM)&uUuhfh|J7!+;FA1RXJ%@Mu}b;EQt%!nbX8-O)dhG
UfUx)rfaDC5>}|##25j>&LxG|Hu^#aDz!;&=ydFqGss&X=iWC82?v3fXbGLdJ#tIIoMWoh^xhRDwl`gUD3u~4=L5QytDZrb850I)
DXk~9xWF^Rrggy45xlf~l1f0RAXt%U7L2^igPWJs3gdxE8dssDHMfUQnOJk3MJV!v9le1g9P6tSDC6#*K|6NPZVV=!m0j#9SaD2@
<^XpnSAABp+XBF0fL)A99sv_zd*5~PHB7B>=E%ZK2%Y>7X@)H_gDH%L*~Bu;V<ZA0qpTUCj^5=Zghj;Et3#;VSIskNWSuyAbn5_>
UQcP1dcE;)KHq^7_oANe)8T5W0UBb6%W?`2aY#E>G>JVM#azS@y2v8}g6Xsl6+<u5#YdK0WYmqa5>!}riCWNs;h7>oakOX!T2;R*
KRX2pH*>{UKbcusS^DgTu57QzWVjQHMuhUxXc421&<(8r8p97J5C;ZiR104wz43W0goi@awo*CxgVrL{lu)I_kl}@SF>EVRMwTuK
>6pqeU#b7b3Bb&KK-no(AH!d#>1iaX6z*(I%(4lox~1ZA2y`s!IIXXWUHrttY<a&u^5h|mRZx(wwO9*_ll1oKgLtPmPvFO;b}v_I
60@GiEIwlNU8{R7p6=EAUcixa;)a-Vx5Zo`E0+Cb4No)}sub(ozdMg(l|T<}UW}l?I8)BXZx>w(NqG?|MgC}N91pxZ9ol!;#5T_U
nod;v=yZp|f7q~&H}5oXB7_Jt7B!Y}Fqs{HsOAAm0vvB#ErBriu{@#=w2+3_xU44V-i`e2?hGTxcUU^ZM=x0Jpc-VkKlYG@(}s*r
m*%kCH)oj_I;+&Hy8SaSAoRL8gOYd^1bl-wWmcYmX_$k)r}N9xr0rlFMKSD}dMG)=gm|bZ&xhwy+8`=20teeGO9GcSmu6=5Sf8h5
ynpVVD)=SdL3j~Ic{WY^?{ODnt#ni4i%%jn0$o_-vp*hgf|@=Q#p%no``d%}p0$rb4gESq@l3QGUKpC5tC3}|f5Aoovt`1ZU&jRY
^dUap8w}@W`;u`&l>5IB30F~l%-0qx`KACcifE&T3NL)VyM=Qx%x}k5MAnn<OoZR?pE0Gcv{y<NHgj%bZs+a|!<FY+!7?)ra%xD)
zK^Uh=cA;E4rAfaxx$%ZAHRtCRv7!D)q!i3xo5qpptij4Lg#=)Yka;Ic9yN<p3|V}y>3{NUvBn$e*um&#h8HFg1I<_p&aq-LLrj_
N?fSmy^o%?cIZpRT(l#ALfXlRxZRp3R#IwYqPwQkrvXgB1iSqMK&1GR0@s`W>f96L*PrBmpE|rohPStYGSS<RVFY5jQ|FVMa2YGR
zG7*$)*0tC(Db6xmLdMYdlymceshkxe8MX2rZkz4!}J4b3k>9sLRs-uTC&V<33^+yGD3nEtGqMLvcZ3mA2h^F#E3_+70{BxXGh)^
e)<r@7J((4A8)2~Z6jWwpDd|l9!k3OeP#z3XCwUXymc&-fOYc5!eEVZC-7@f3|YzT;DB2{R?9}<s<sdeEwW8G-;_8_Jp3H#GJ#e0
O}xuQ@%MNROIf@cRW|QH#5nu9i5ZyXU2JsZ@xV^9^&j0rkLqjrjGxII8_jt75e-0~E?^#*?kUDN;Odb-@@K>;B8M$#G71^@2pRQB
Lr@mkC}`(s2I4l@DfEl2-!t<TA?w+}@(uP_3O>bNe)^3+AhZQ6hn?c+3c=6-X)b%(sawXFDA2fW@kOB-s8L@(i09?JCSUr&O4wy+
B3CPF2(EniqmW7uM0()}4Qb%m8(}QXMXYukirSdp_fEr~bFK0;=YHDm)UczAkHgOV>hb2@r}<_|cMwpEXw_jxu?lu*BT4R8+3!kn
5c{$_Y})kNYZ*}YzcsmK3=dN<u4w~jh&y3iYl@I;d?r?8)CJ-RWJ`_0Dzfa)ZeTCFyBK9?z-t8QB4B1{bKH`?wxt~v-gNkt=XsW-
!j3huW04&=snU4Pp>Q6>Uo(fC3kCG>_)JajGK%f3ORxTR{Uyh$IrsZi_9B=RCB-COGWr+gfw3Dcwf<odTNq4r-x0IciI^84rJ<#>
Z`bkHvtz$OS1PhIGcDtyV}|xc)(>A9W;Z(U)Jtc1`367Iff-ROG1-smaplfS=qZ1}i$^P%*E|+EkCZKZXG1afl*g>0u>u@2#u0D4
2-$!ux-Y%|(>l_3tnL6jrq=08Z-I&)U_Ps&#|r;349rjw<dWbcITX8Y+Gi26S>KWoTJ|Hfx#eg0Rn9Pd$Q@xU>q_JVJ0ogZ0x|gu
{;90l;}!k{z?}LO&#?)!Bb1rj;<(U+r61czmHDD9**m4leNIMRcDNNC#}%mgU8d0;Na1)n$&){0?;Tzkmr6;qcO58*2yh#oOP(i3
sJ;rkhxgwoE8j?u6-1Skxl=2gnl!pwl_W*dw-9}Zx0-GVwe?3W9aU?$BQtD*mBD^%1cqm_<SRxY6%n?k8|4YUf?UJvO&7TM&Egq`
T=Nb;VWTRSER7H3COZ-m#dzjT4MyDre!x*<YenrNl6%e>u)55T)j+QhpD@vTg5{XXIF#&k{CW@scHyQ3I~k)4zKm%+Okc-($F$p$
InFk8obZD$xzpz|z;-s#fM~G}n3zZkBmXQ%Su&3Y0~10=v`c|TwpDR%f)Uf+V#csnXaQ_jyXZrRUZSFVvESdOHg3C@f8sUQhD>Ah
hN4c!LzT_gfx8=irp$S<_vd}e-bY7R5qwyFlpvmO*-$oV@n_<()w{|!`~q)I{f94Wz7N{qF(GdUPc?A(Sx|jmccWc)q9WGO&4&xv
4bvVIHoxiOlrvx1?Z>0LzU%LP>oP6eZ32jFsb(BMnz&23EiYky9!YSMz@c;mtF}=R1Is1JJ7Fyzwm7_1k5G#e(Jrstw+wyG2I7;~
%m!6rZP(9uJp-){;3f5{J15a>{^ZEJHH^1rT6_*?JPx8>pjgVs5ad9sUjd#nF3jJjFG=aTvPv%yVR+9XIld(~;~*CYWEJQq2eLJc
{<WBka9*_-KK#Z6#xo}nRsVCw78)^|=e<C7lWz%0%!?*-vijHhF<J4-i873jd2D3dh0hRA?|V6pIt_>KPopkT?|CswG#Iul_T#SO
Tk!4e<d~@ch;=dPWxf~xBKfl}F$K2M(&t8$Phl6qs}hDiNKwzCT(9jj_qK0=z>uV56k*vmTaBY)JtgXZ>VG?eB>>mDia?4`*Q1Q<
$PO5uPQ|g40YM<>!A;kC*Wo%7C@zl6yU;OWi+ODTuI+<eU_oqyCyT-`+$u01&iQPMNfnX}9oR=$5rkTL`E#Jz9r$`W@r|Pzw*~1U
wR7s9G2i~Xelsg%vN;%>f$Qi-Gh0VNv`BrE^UJ77q+N!(?3o`8Y~Kh*T(BI+wJP1=Jas3|?<v0zm2|DtG)C#qfmFI6YDe&p3MM7c
Y>=LerepplR(-e1J=_cFao!h!mGV=$%_*C8WCv8cCGA3gilkqI@Ty!cfb{9C<Pyn~uKr#i$k~EF(QsD=aLDiRQr)F5ATgJnaq21s
RgF_Ijt80Ru0q|aF0AnXb2knbe2;f2|5hWWg<19fLx+Omnmx(W67PeG88!6L@FwVwI7oxy^H{EQVfY;c1CGR&Coxx>2vnoA!ruTO
My1pc+VSg-jT#?s?cT$0g$p-VaKiNBT*Y=j;0{VKS-L{RNFyWR_7t3-z4T7=hO<u$T62h?Y@wI}=h_nV0Qc4^?%x-ZCPF&KD>xJ@
IbWn7CXeU|aMWgb=OIWR-R{Flv$p*)T_>wz8MtS9t^}mvxjApeN9-{)83kuh5WNks5fx^|&Qkk`7x`8m_Tt(FI9D0zsd<?~`1{RG
7#2{4?M40mZg&ARa+HdTmD<v>j3=6;NV$n>S8(k<u%cF?`x8fqZqz|QpheOiPMoVx++DSJy9Tw@vQK6TelG4mTzYtUD*0)q87xfq
;SNK0MA4{ayc7<{DxKfg&0Z2wXP&mgH_*&P%Iru4TU#nzlHKz$?*;jk{5;^76n8+?`m~Q3#U`Ad$ok*!cvVJSFxZ`IQh1A-hl#IX
{!)U>D|nKc94aQpcI<3ba^3i6_P;u5+m!w3c8Q|OE~>^C+Z=N?9Je2sgE4Ah$^cMEm_Jt?x}0HDj~ECdOmP2b=t$rg3tdHw*|ftt
4_`p$k#|OaZniQ3c2amuV0Qk8mxu0y6qUyjNnR=GC$+O;#qFHo(N%op{N!3(Csa;0H-`L7rnL~QU)VF(KiPUd3wUcy=05Xj6p|1%
M4Uz8Fo)X0qP$j$ux?OxNUCVX@bS&hXu4jfzNIcc9l8zha<xiKWM{~j1PTB6T|N!3&!zZo4@vVD%N1*}`e4Us2UXyI98}K8=UjNV
#q1f%atZ?a8jXRkd*+nzrGNzs^QH2QghZ+QL<lWvu^<WpXDzPSTVC3o0C@A^ccU=@tP^xG81$gL&JObz8Rn##z}<u-6~}4No9#+>
LlnH!B_}e<k9=M!<zo;!UiQ^OUPS)v(iw4M4PvkGqkwS?!Z7_F&D3I~h@ET@r3C5eKLw0a*6W2@($@Gk!8FKc5xA5j8xI$pM={{-
nq)j1GBpNEXf*Lqec8FN6&F|zlPNPPZB(_P=e`#AIyH3|L|2e2@GXqBsm<kza>5&SKC@C>s%Fk(j{H&DLPPqGiJg2yfA_BSE}|N*
D!s>_qR>2(I2};e)aM35s`%QxZApVu^(CxPSu>qt<|I(3eX-IfJ`g=g(X*>@wwNcLF5J+p!pd0e?07FCGkYwcg8!qWs7yQ+n?(v(
E(fB5UFROlCHMTN!-&7T+OxRly(>}w<6I_%XA<n900-mKBac#()D>1FgKeYsF?T-<?ZV9>d7MJ0mRsZKYzMr!cgAt78-5G(H-f`#
4;wlfVy3!08Pzgv+h~u{S4Z{>sn7CjR}@v5{u^I+nLN{dsL>%SHUr@<b|c>Tt}Rj;aO5P;&~lyVu3Cx~+x%(o?JxTCZCIKJkxsjR
x>k#YjUto}BNll#nzPD}Su>2S0Guv{BA}<A9~<sZ4)ND#3{?rtd;0+*iGq!E*S`!4zJJ<ipcfI9-SWubosT(#!zH3YWK>-L(H=~*
#K{1upC~&vLOe*@Cv)EM_%DF(A<-$A7hSRrT^523Z@#_fvlYN6zwVuwh8=WcHWk$!-CdNfLvdHdi_N#bCl5MiW%go$KlQ;#xfXe4
M7btM24XHs0da7(I=%o$zpXSMkDq2ZGoMWQY>6?kcTWqd{X_S|VBrEz=4SH~sZT3zWELS%S~J!Yw4H(?syz=Pn0=+qgDxEjxjva4
w+u;nSt_5A@W#l5rLzO+opF*YjGU+J+>vx{a?4!&bViWVR!VC9+M)3S&%+YM0py=UokUiDrYjT%3W2xn#tGi}MqXmFS3bk=#An&|
$$wuy=7+}(G4?amqWgkqxRhO0*BNaS=odMNp%wFDiE~s5X@d`F^)^w~89tw;V)0%X7Om}R0ETJP7u}4vlH0`%rx0MhEQKY%s!k=p
mmn<OglEIo1F?>MPSioYM)Hre{?Y#v6BM)GPaDY3%q)sTdnwDnA-`FiAV0?In{LB{)oP?2Sb~eeh?zkKug#kPD?OlNiN|C+Cw><+
1Q9B6;TzsUV2Xo4r21GQ##68=>PE}t5boyC$pmPH0IZV=vW{$nS4a2s8$R__&DPU~5@VBSCeOUnl#dn`wZt+`qS!hr%IOCeeA3st
hRm_CaEf4&88hmrC7Bnd!6amctJhE18n1+H5Fo7~n;wbz(Y=qp5u9aUf-euuh^KhStS$2Rr*VBEp-sxS?YENpnq<1$S6BKBka7F0
p7MSAT>Ju+_&?&ocY|)cj-kaa=qDj#E^|P;jWXcQ(#==Q;s(bacuHw}G+ykgTjY?QJnbk<NSZ`I6=Jurxyb<ijZJBZe%_()wppF4
_U*-ZY<4vJZDh^Or@&Ow4}UIY=)UKgWCrPGC%yruJ@Qf5XO~WYCn}+S`O7?ekCFz*_d5bj=fO6>W+e&Oe(Iw~ESIDhkVc6r%LEi!
>aYY%e`a|<)|2RY#y2O@r2jr)Y&fEXB=Xd83o;SY<ir@>ceSdRSgbg1u}XZTn{S#_OL))B(jR1i>P&6G`->1R$mh2paX`s>CiQ+f
E;PHkhrM%v<pi+Zz9TArJUxcnYV<V%J7_3@Mc#Ax<hqz#A^_X2K*Fbyrj$QgzS`QMs*A--$k(74-_l+B#3}{VIR<~CZ}j3rc>pvn
p^r?))Ue9J*rB!44;}>Pj4Zc72oRhHN#l0Q(UMgX3pPg3njb$^4Rf>*5k&y=qXq|t4rj2FKxY*5b%&mA`bj+-q4&9$lG+awMz=|R
Nkog(QLPyAs~FKJR>PBw=pYcvHR~?`KJ|DA$eg0jUkt_ywwlHY))H~0>(qGJ1wA1I)!(tchPp`DMwQ1Qu8b8LkJPQ`dT}h?D@9CG
IeE0j<b+tYN>x@VEXtY<%Y7Y$eWT>?YV_9~XZ@rUPTxm%4G2)C52f0=5&<ut>?p-<C8dAi{W#4qvc;F=w6<$+VKTUHv2&0`hQlGA
_JaVYLk<U1z``aU#=_zt$(8J6ujjIzNa&b;{EQ+<kbmki68Z~a_Vjidbe_(b@HY4Nh4t1hvPp*ycwsw^b02gO4Km|c`q~8Oir9d?
hT&nq!P;45`N4-g5+2NoE%%!9TBQ?;Wl1f26Jp_5hlWGGQXjy;%Vd?5U*YfSJuh64em>-w2d&Et6%Y*X#4XG)f`%Gt=fS;RS>3B#
M5Xq0P5ltj?`m1ErM=f1%OMJOg-%D%<Rs%e2{P49rGIrGX{pS}=wKb&^s*v`)U$vB;b2}1Zkf8plDxcA?xm1|+^QxSGw_g+sV#Qq
to>nR|3F_8=)2Kt+Fd+y9hGaD)q3CeG9;{g<g>+}$^2XdT?jvP8B)T{k~6d?B)W+%u}=qvgs&+?^^@bGm%p5Jj9aEPVk!Q#A7Eax
7!%=BrW0#T-b+RlZb6#HmO2&|7W7CGDD5tO&{)KrumTpP!{Kx0gFz23LkF@SilnUNs(8dj6M%)1${(4dzs>BznG3HPs)aq~n!99H
(|0+)m~-MgVid@Gwak@`2F|F7K&IbYR>#(Qd8^r5ph5al-JpBQBoUW|IcIR}YH(`&HGk@!6}A0{P7v@J?6*>QEm=7f!7)@`FhRH%
ovGb982%12G7=ngY;d3M1~-EIc7bGhQ!m;P3xE0F+>HYDHB8SFH7KoDrHMu7Yt#3LzE0y!(eP*5DHhptWfyECJH9AZ&)a<S6|eHf
oJ{>R4~^mH&czoI9NIf^r;BAb_JoS;yWlx*np#eYjOn#$Apg0vyq%WQ*)NEV6(IV5b9UVjYO0Sm-7DO+*VnMT&%L^846x`ah4C}P
S=X0mMT|9X@Gds1H41;@NKD6Y)IjDXy=t&6;N&UwkK^gFtC3MJ;Fx$+wiJH8L3Y5b#u{BuJ``lueQn?GsP%(aF(uBLbLpk;?VMK&
i4fD!EoaPZVk>H{<;Lm98*dzOa|ZLEj0jMEnz-pX!BF^dY{69-ge%vXCl7Q*)guDab=J{Osd~HHQQdqF+h6QZ9&FxT_E|^{%k!am
-d5Ip()H7}t<!<=(uI}BC9PHD`VkHfDoyh|p9cL;L<^?7H~9xfw(SoUhq4)e9|!H`v9DgSEuZl^+})|(aNI>_jpa9Ko|Qgq-V*PO
`t|W5X&d_f*QNR0EtF{I7rQorRCWo`^!00(4rZ2t<mQ$OKmc6AK{A2ry6twd$@5LOJFk_fox`Eifc=o`C9i$A4}<T;I;kHTD2#k7
QJR3UW+UM9&?Myio1Lm1D9<G~?c~fDEOPJZ;}GZPSd}P;KQMU)g2!KWYvMC}^*CZ8C2D`BU~RH%wA#kI=MCcj88F?xOl~Jn6obyY
qBA&XLIivhL~cLZrNL488b%@$1a@K1I)f!uMM`paA)Uo!_qkn>$-UB?sPVpwti3GhYAr(_Dnw&AW66H~>latA<m|+gh86Z}!Aa$j
`G`n>N?bY|mV(%4cDBgIySvU-$KjJ#Mx;&Hffqly1g-X{28?L2VsKuGR$b64NkuUM6-;$24OLL#8`sQGmpf#jlUe6KRiV4Y!^}^;
%Z|~IN3?V&JdGEa+?Qy;E5M;d=TOFsT3wt>y%IT10sq8;m<0+(7-}54<w5hp*XsqLm4Dd;Dv(%cnbB}Dbtsc?DOE~&AM@{{%^9`{
m1!bu*u|~>t#e_2<~gZ79L)SOBG%+ri?G%)zo(K_mZoS=MM6MPNmdCbqG{P&XzOm>HZvFnjI!M!4#}gAS>&S+#FIWu`n6>t-ErCQ
5HQm+?JbWW!5|O*)yT+~j0GEgm|*6RoWI~sHV0QaypI?6Vu35L<Zn#P1W#fl@_)d#e*z1{O{zLOA8cg&>6V<V=nah{NcQ1FO6^;{
PudgQ*0f7dfmHa1r*L_1oqggq2md}ct6o0ZpWRvfO8sN&Tntkoo~Ju3tfNS~Z-1!rF$wUy-BiB&R@4ei`|<eqDIqm)3aUC{4kc_m
wOFw=1EOed$fVRw=ez(Rg~@%hZW4<rm~dM)k*EoyM>^@w_8)B2`_Vf7M4rcT1>fwdiIQM6&s0h?ye$fY)vXD5{ITt??qs}q5K{dS
z{8#&kcnS9az_~X`J%&gCT(RYZxtQHv1&R{q+u{uYg-v&GS-9}`CW^izDoT0x(oWvBsj=$)*Z;&VOLb8>ZBlf|7g+s>ic(bRou+Y
Cw<LiF#7T(@uLoqOBC5Z04;E|g7>ZP-z=S{T3#wAF0q5GzgYu+5GoYuX|}ncevd8egpA38z9A%oS2s+eX!)ZVHlFHY_2<C~SR~x3
+B}sv&fF7o6cFA{Mtq7yqUgHkn{S|y>MvDVM!Eh}?bq?|Pw=c$-5?+WK@Cc?yC`<;1ZSpZ4(*yMa<7pp+=i8PU4XTwFK9%Q8hfgC
r(G&`twCHyJ3>o<j#q~!dN*G-p`p#d3eD|hmslZK%TvSBCgR@-Zj%ey00Rh07;xvT;6B+NGrjw@qGb9Amzc#aJ@u}ox30g2`zs<C
sfQ?M_Q6ZKDt5Cyo_3B_iDo@|iq?eiW|9Zh^&CZ_sbQ%x6!VmN&z8i!_>vMJ$xs8Vg$20vRlHN=nH#zr<s!C`f?swkd>S^U_l|x6
wV~QmD}jAd@a$Z?mYl-}-1>$io&QM0b=d5W=7OelOwMisPS{yQ_vIRz=;2T4U}?H|kwtvXz@UII-;E47NTDvaQcLd&NG$$bUp^Qb
8IqCP=uHxd!Ko!23v8RT_2K5ulkW268|OqM>RqlXWq4|=D)ks+WOI$ZKFT2xI}M-A=t+^!N!AUZ5;A_6%>R7%CYs|-eZ?7!!R{Nq
oWy<kgv4D^maLy71BqisWjdD3pp!U@<0WEP2>dj0z-cpK*Q-Ce%C^HXn5ubfj`=oV+BMnu5>m6mVa$^&XbGOL5LHnI9;?JeGx4h(
#dfq&@TaZP965}#k(BewjAobm*T!0%I}JiJ3aVFD$Sw8zudXDC@AXo-zrSNe*YV?euZeh@7zgQUCRYdmStvyx&+m>bxmgtx3j!3a
*;*TT-Ho@%ju=MngXm1*(@<<s#TVY8phn#&<Zt&+RY-26r-%wCY4dl~Je*FS;!B!_HvXnro$hrPOqL6l2ASf78KnsfmvRT%L|9vv
(w^qj^QF1?({^TyCk@@_JM_HAW7@&U&7CZ)uG|+gR<Y8pI^qUq+U%k{eqAs(MWcq?iUt}?uPi-^<dl_Lfv$T(l)s-cZN2K(ElUu<
^sk{p;R#uR;ssDgC6Uh$l&+xG6<!3E0l09yH)&fsJzP8nWV#@w3t*JF=;&psyzvoE<JXfq(-Cz#Ws@+x$p|kNv}z04O4`6=h^xcO
{0zoPvobtb^wC0Uh%r-~e1tOtZN_V1yh7zVElA$K$v$0<pA@S!Qx35ND_x;VfqP|`deRBl&ijeENta=3L04h^h;_H4H)zl_I&X-E
;x8nEsswH0+i_@m4FIv@e@tduER*5n>TOE1#&9{ll5Tqqg#zJ#crA#K&V-kkZpoW?DG*u02uNUo_P>g6!6K<5P-rOBt7R#;Z@idl
yp|*%6kV%2Ch+G#0{}ivXMl6g4C~|S6;b;hARI&LvyX<J&S4<vSC1BeD-lDwMb=~;GB!>H#>XZ*_INPa?j8ppTQy~9XF=(QP+-cg
8fUeYrREl(L+(cGE5$5)VkQUXEb3YqgWwxan@=ZE9UL(kW8adTBX|h{qlJ<Of%@ou4}M|rK(MzQGbsh)h(n@7e8tnB_NNU%#B5D}
eq-3c4qw_bO>b>*2|F#PJ{5jK>4-rk7ZqMF#1^rc$(SQ83yK#zSVQ+{wm;KMwp@7q4<f5;n&b;Fk~g?kf5*QvF_Bq={emSY`k0k>
VRj%-ehP&ff$cOOZRQYHOzul!Ahxn{qT=xR%&O8JD3tq@`p93J>Fb5kmG{)m;tP%WDRGqE?b@LK;QxUP+#XQ&<Csy}#UFbFG_x42
$^BGs%-bglAu1cKMr?^}A^tzNk_ihYENF8;v?Gs5B}T|WP5u|k*|+g}#c39y`N%E5N;}IT6i?{1F7SqjAk7^+eh+$w8{<~@?gh<_
U||yL`o=Kn$akfu?wK#sRh1!(t&?<^6seCUO4ho)YDT(!MTdNFD@B)SuV`h(WgK(~B!=Q=>+=z+^9#ij@&!2(Q50@r5ZeTL&Jkjl
hRAsr!V*FB5&2Z$PHAoYG00B;JX}>7<=@|=y**arQkau~J!ev*g!N8q(UP1SKV}a9Lx+wLFxE93m0;u2*nfflNNKsm8qCov&$kRo
f=!v?$iK8}xz2>M6`Yg7I+;jj*43f_zUS^g`x^Go)3N%r3!Wnlj`$#qN-Fq1lT}6r)ihO3!1LYUiD5PiUIAj?iVLnj3xc5|?h97W
oGrVv5J-WlMeEOGirl3+rCn)8>Cng+G9-1PLxBZ_n07>=ooL!bHq`6*Z;kT31UvQ+K7B%zH&147#nyM@9T;~Q*ou)*cDX~xsj1=}
^lU|N0f&g=!%FwkQQY}FiCoZ#1oLHqf@<ZV88)1OYIrIdz675rI<qETdlUs*5})Ed%#m7Sx-HumluA_`#r-0}qaFQC$BX<|J(4`@
^M7jAqfNCvl37ubE&ADM_XmNiiVAfpeyKys%jWT-&3R{%qxDhY%SM#Y9?9bDD!1drt3IkTern#$8CaWI^NV$rTrI-^5=dbP(fw#M
5DDXAmN5Y{7Cd`!x0Q;5LLslr8ZP<&X*$ns8@wY%D0<j+G&Meu{mAItW56{4uHt3Q95q<2i&=J6pa8I~uLh>raDa=R?2YDp!zkEq
dwN*oN{w!9)c-pqY%g<zs{JtZ^sHLe6Vy@T0p%Awi3mB`)_3E9L@43>+`rN+F%C8*vSw<P?umuJ{W!!!vB8#9L$Z*)uEzeLD9(qg
1&kC_hzNBI)_$7R-OFtc0n7P3BG@WAO^|>XuRktPM{dv7_*Jv@M@5P)GNhO0wS479S{hC<3KFx2*JZb-3qLjFJr({`Y{SBGvTCi!
51AXJRmI+dl2olmwTeK-XFs)ZZ5@BGZIKD_qe_WRicZ{HGLyP7|J5u{jB&KA17S{(FNNO@1+5~z@pHr!+U-j#;i?SDSB*z1Au{tJ
)S<D)!u5ycnfux(ysD0~T4Ai71qlPEC_Ue8EMIz}0t~4*)9jNcfqD5FipC-IRmp-|#1mu`sKp$5+z(PqNwy{{U>!HE51tz#$gx$8
Q+h2AQ9MAQ_H~L*AI;|`us)NQEYAiFgJG3<wc_El;!6aw#$C?!YhI8%?MwC4Iw!46W!6uHcq%xK=S%2fx&^X8P=3iIOC|gac4<)v
3lA9rNEJHV$x)>QdFcL1us34yU@f&u^NdrL7wH1vaEr4m?O*?gyEoA)vMsZdWL=pktEq0}HW&swyp-rp8*eX1s~gNfV1Enwr{lN#
XU7k3Au3eHawF*R_JP7m+lzOo5;gNx=Ol}i%`kW2%OjN>$1j5?pvLgadOsU?pKwxVkTHk!<xc>eMSY8I`nK{#P!;=0!7UB{1r0zr
)D4x7?Fu5<NM(eJYA~SV(8x9&!XA6H^XG{0$KJ6pja_r+Wo{UA!N1m-s!)PS*#;tebq2}-HPT(zje*d*X*R5izdpH<jiORb3iS3B
$CQn}dis<r{cGT{91?ieETDwk9herEgGp+~PeQWGRlszu&{fe7##r5t!H&gM+I2U2<=tVFwAXR?{zZKvs}PS!?`~XV82bkDUOtd7
#dl4vFm&l`#9MwDFKZ_7_64xKd-xQb*Z9JdjaO*6j;kyu)O`&KW9-s17`nX!%xl8!sm<9h1k&2@6RV)mWy-Bo^k}UrG$B*K>P82{
cM3A=-wm{Nn3?=C1S|mnK}Vi(^Y#L9wm|VHa&?XOyczwqwRp1lYkg6Eu<Rh&mI`>lwu8JPVcD!v1@#?J|Ej0#X)73u*VyPE0}f$G
GF%QPhCgUNel3>E>(j(#78*gEKONZ9VfI)7bi*CZ;1|)fTK+D97XO0uzL53(W8|F>toh{9#8)_NX9N$C%<$&t5SN_55LdgbP6jHD
-a=HQ5G_THhVx+g2h!46Cie?mS}sM&dhy}7Ly-F)pUC#c1_2`%EIwM>5$YI*%P8f|qf<rl1R`3>i<<>nP?N^@i7MMKp-5;UQK|%&
Q1li)v_~Nr&Gw5%XQqy{xDZ*|sQ`vdw)FQ<Ba2jzgjnVeI@7$eM*vg3Li7OSu>LScntW<fJ6iT$Pyk})===3nY3~GOoxlJKT6anm
)#Pv41<7W{s7ZqQJkdd>gHtgmOwlEEx@^F}m1%K!!FeGCYeO{(rj1yF9-8JjF{uwD8rLCzgg1!QXjl=M*PvNgH;EGW8z%|Euc6bQ
Cp>{&qT{o+2HRE&=0|=F<QQ5=uTIlhuqw<cW1I6eq$OAKvwhz}0%a5Y2BCI*Iz$4%nCCA>XEui468Q&9CS$xE6`}m_Tr8FMLZLbU
ZkyBF&9&M{zz#Fs2Me*jiu~In#nh=|CTfC5Pt3}A#$M}#1rfH5Vv)VeMhHxmw?A$~`H`JMjy7h7F4wR%a3g!N>iq_iAyq3f`bef=
vnDPKRwAfeh0v9u6OJ_qlUwx|A2^Pj;{0ZVGZF!c*f>Wum<jj%$I?gnmJeg>hw>>DCw_X^hb<{Jpmjg2^Q<?k7|XQ*fqn2J8(C7y
;P2{m?{;MZZos7gP-c}l5~8C4G3Y}UFN$N~QPyq_vr>+8`u+}iYB1H&jV3~7*FrOLha=*H2MoV?VziYsVm90Te;P|0n*Kr<lw}V8
@zQ~nnm!-GRe`xQi1Fif0~2umc9vWWhD(1DQyXHsyl&|fn<A!ntB@}j2k}+EKhCi;zijc-y#dWfo}?Rr=g@OcQ6kmJvt1)-cB_-&
w*6M=fTsZZyO~9m@Ml_7)ms-&d0+VCCXPR=4`wHtVg|0ESPd)@kZ75=>{cx?Q9;9LVG=wx*s1)s)LqE<G{|lQRWi<eICA?K)Q?}=
$01QAi<9d1o(j|hlNdxGii_uwuu>)1z3P!5o5m;!nI$xr?A&ysW}PLZi12K8s@A?QiWP`%=Z#)Hz=T+yi@_S_-LtE>Jqg9y?QE)V
0Tvt%)>O*dl=Y}F=bxPUjZ}ydzqs-P_?g_RzGmWOd380O^VEy4`aj1!=*h#{Wbu{JwDR{phSANDC9$R5Srn^)?RUmS^EcF;K8Fau
I>&%x1xiv0jH)f6H*BjCVWf^zm=Vq2n(Q@~3@faxOE0k$ljzgnm~uVS>p?vR6aT_cF_zOy&OUfhX0sF%f`;jpMCMoqHs^w%#D85z
1C2HPpU-nDpFus3A}suDk$4jueG&l<;JtJVwJFqTZe}poH~*{Btl6TA{Mo#wl0KuBI7sLiy>ei`8zcvp^O{O}#{Usxi9t+j7Yk57
Ky0Y3mJu>q!kkb;K%AKGS1!@%j;|vH>=UV9mQAb57U02C<CDyHNQ@@Wh}K4>nwq2&P8GLEScUuD{o59H=03=y5^9^*Kgl5fBT+_c
4NqdTNf<!IrMOY%p|lGqOUS(p+iL9c2;CNl7aew-2fFgEzzm$-VlPFsidL(*8hAF8vjVkOf{h&4-h%Dg-4EZ%QQ-n_R~`p?({^>N
f*d4L{Zw#MRt3apWDpJvOYHs0&^jWEgB?`D72N<`wFRQ`w+P|ELh+V6a)~Y&p9Hpqv-5w=XZVSxNacY1c;o-%i4*FEHI{7==6nfm
{4%F5reHq(47e@%bPP|PqPhmgQg!z<Nm=c=QGQleHR!+ae(tynC^kv|qM{ew41CGcIB?H2nk2>BPCthF9+#7&QTqHw(21O+?3CE0
V26>)l84|XRgF28&$1~j6YLRqTqKuUCL$5H(cU0-T^Dx@n(M>ZLS3$RP8<Wvqz&yo#f7E^=x|8jdNNBZ+Mb~&aJVJ`!SYuNzd=Gy
$3rbYm~qGi*er<xN|6-3b&49C0)mg%Q-vR7NUJ<vAsX}L)KKvfJ5^RTm1Qe{VUYq0K`XngRX%b@$f@}#og!o5We;mZYr6^@C#Ag!
J8>^T3u&hs`S3n>T17V+$rDl>!3K;Gao3I>a=)I?loHQ>qC-)reO`0o1yzZib}GrVxqq0K#62!61j*?JMco&N5})v53MW9A^a<D%
BLzCXrc`!k5f*4H_v`LsjY<&yvU6nmYBDngF?E`XuR!R1;`~<7g@J)MAy)TS#XUcqQhNOTWKS4Eij0-|T90#nQ%NYaa5^0(Uh+k<
8pBa-MoRR>PsE^tjG@?QUCD8?Iu!U&-iZ3-a=f@Vvo_MCA1@vsEbZMb!3m9Ks$v_*mDXji3rHarms7w;IhA9f0TqCfXr-N+$5dOs
QWrWR6gd!$p&B>?y;a<tRx&Ic;$nep%d*DoRQR`EJtsgqxoZl4R#((=LKCyb5fAg)@Hp~_yMSeRq+iIx)wlJr=Z>#i&g-s_uOB`m
iX}b)o0OQ=Y+cFs>%SHuXzsdT>Q(yi2%`h9L@sUNS4NQYOXYV=SDBteV+}&DqSb@=DIIsZp5ytxm-T`D--BC#p7|~RxRA#m9QDkw
`CB<AK=fyspL2RgnN+eR57*#74EBOf$u|E%+!Z~1JKWs}xVf0bF1h6fTk)F`nPj%3*swsW%c1ZxfXUUZhKx+e#yKEKFPUn{4B^r!
>cH;DwXx?1V_D&QTQsYfcltKdK!TZKX8E-}42w8Bw{p`;!CjDzk8F;C46t1!wT)=?mXbGkVuyk*-B;#VrWTS2Y=tr6+Z$&)vvdY%
^M%Lsx-dMgMV+0+7|+97j?sl$nJU!qm&xZi<8RwX|2C*IUAz%sqF10-^&TOU2Rha{2_=BK2RMsSj1?6R426ZMNh5_-&P${u=jWt8
_OVK}3^>h=(5_wgq7L*Fu#yLH2EqqA{Y}U%cOWiia=$zYA@uz?2Urc8%JYHlT|<*W_}W=!o2W8?h#Q#D&BE#;B9#*x#<9hOC)X=c
ZL}EtU9nm_Te|Ds!rcz*<zG@QA8~<?0X9$KLzQTuyw9B1nlaUT@lL2E)-|NYh{CiJkZOIAVK-S*v{bQZ42}M03xghegM-9evHn`p
4XJ+8t{-*3(c<j%<WEK=SA{a4@Q8kM-T;0WlQzgK(L6_ti%EUdCc`P_1nHETLR>YCn)PUH6Bf;c;BGC6vLZNr3K62xAZJ3SLKRdY
?5wGMfWU~GNL&Jq?xdIlwI;m)P5ZVLMUDvTO4*YB`xa-)ZxaGX&IlU2Y0f$Wj6pw(FAmG=D1OC<F-aR7-*5<xojs(q;G>aQs@Nu?
a~Adtj}CP$Yd-1JJ)O1A`ZumHG|!&?kt<2E^^qufSl>#&gopn2vJNFmPU0@fiH@Onq8)>pK<T9~KtUUZ;I^CG&dU#E^D$*fE?M$w
3?7J5p0cSY5yn$@(zKM!k#5|)lLao^oVS5i4f}^SXv%5NnN@Jw_twM8S8<R&YM9NkkeH0U`|SY0beC7jTy|tPU0SDg=n1v-8j6?-
BMkTCWw_Qh@Z>BhYg_T#kX0G`6+FcLr#RC{BwF}fn~8*!qA4h8aK`cvkDBa*zd!FeiJ4;?Al+DPIu_AJXj$ZDpIt1R=sDfDT0CNf
-<A~)<<@NFa@(k6^Pbw)>QB$5D69#^iwjr#%M=5~gP2kMOOCrM=y720f|zz^@%61#{-f_<3R5k++lMILDP&k~&R+K;LmBMs@$Jp*
gz1TERz~$Ryv`iJMnxVvPnfP>>gl;4Ux|q@ivHCb9o$pH+EZ?du!0aR>O7+$G%MisY!H|^vuLfK9yj~+)JO7%WQBf)#Uw>S_S1Zu
fq>dE!mL*;pnrYM*EeamV^^=~(mWzHK&l~-FJh59#08OK*ppGl#ID@kd&J1x<eYYSWXF5dlyRwFWA=Hl;W`^ra0#8k`Sb|?ot+fn
D?Hzx@x7+agncI%eTBkqsgz3II1Nu}XJ|cyK!&}}DNq+S4G9|Gh+h`~_dRJWr}ju8b6)&dlwxxhFh7#clxUrs0eOMpau0!Eg#bAa
nHJr8<y2x$3!^v-?>Iod_RpL}c0KR|53$SJ^At`u{F1$Us`e={iI)U9$X+vMcL8!6VG*p+%pCYx(H1z>EQ~6?<b;P)X2tT+v~}w2
4T^6H*fvNql4m7%G8V`I^tywe#aP~%E_V4)Vo!L5(qiwLzDjmN8n_~d;tH?H(l~3<T<%|5xg^c9Jgxlz4)R6lTIMUq#@Vrq2?-+2
F=>zk^!ZT}B=L5iOnvLlTfuuxrR#3%;xCNqnQgSmTsMjSfrkDDZh`_pWpY%DQ5(TyftJ80*u1&jC$BLHHQ>-w)j%r<!!Nmg{MHlY
ArGww0Ph337H3*OKbAeGv?)crSw7CX5+`$lWmQ*|ZlU^M$Tc8al2thqf2ISV^%F6Dm@v{YwDqc#hpr;y7NwKnx{5`0VF}e5UsVF5
wx;2byR?W|S~<A*aF%_V-c^(Rx^6V6*s>CGx+O+)`zB?d2Xe>;Pf$EXqIvla<6vB3iPS_b?`zVUb1jNF+TNzzzTZ;18AUZ>)j)ww
p?cSqe-h$L|3!0>O@`jL-bx9a3w7KQ-fh{;F+4yAy&u_Z(rwbWFN@y&6!t|Md1XR8zr}4xU9cJcQEXmrool*`#TtfKKzFYjA)g$x
&q1~LzCO`x`A)J;dO_jE=AfxQb$;&d$5NuNBy8%$o=NalX0)YBQr5_$pxQ?O`7#&0AAfkj&uBP_o9ofMmn{h1U^yY(pAz9x9F)}D
_ct@AhKLqH>1keFDxgJE<ZAg4iN8_S`3#pAU(|ki+T`fqc5>rj6NW??DL@TXL#sq@_{=s*dV1y<hqRtKO{Wfv8LmtJ*veq;FU4H?
b`?2puH44yyiGR1ys%t|6O>U#1)Om3*9&b^%6OpA7x*8(#H?zkudyd_C7~TgV+~ecO@a7S=h5CNrG!qgAKk5^<XN(I$2v)*7KTYy
5vxIT<xwv_;A`?2d3nw2A?6x6@j*?8jYgSjT#ZI@D$6)H0DF|Z&MKHuXU)P@|0G8Td;68kNwsOp`|bT$Z;km{ZB%#q!SATBE#9lW
JI1o#U_RgF<0C=_9QzO4R<P^9d*LZ1z#Z<W0r|GC%tWPv)mx`hpSIAozZO@ZFq|eOJWcPuI)N5`B{Uq*5w%;HTLmG*t3M{FKpIzO
-{zt_LHoPWL0yKrxM1p%(_FDNP(B-*uOD}+KIJoq5!|j1yU`z1U5n=fBDoU6ev(Pv=w6n4AnBK@&<~FWG(}I+nj6&#AGC=MD;;hU
j9!Kq;YOg|m=E>q75o`Bhdto82H<dV`t8KTt8`MSsi9M{zl5be^9KUhv>kBezUIEHJBEjdf7XHOES8H7+Xw=7i<^14g)-l-pLZw@
R86(o%D@t5t25vlf&ER)n_{pQas7C4uoqBlKt^0vxJO84O!7SCa6wNUdV%WO<K~DarBkt~qd(vn>@DV29G2dR*-<W?Z@75dV!0kv
2AYvP4YTXgK~!%AhZCdXXH6hm>;S(F4VDZ;$&v#{gZa7n;S$k3`Qt@6PhZ}zo<KEF-W-Gr9#Int@S5k&K;`*>hnlAX755b0Kv5_L
iaDjM9*+dYMiUyV)$}ymmkjZJ2y7SMrZ0@EL-(@mF$pH^=geZHEFD#KN9GI<WX=i(V6UD@`;oTmqH=(dQYW{!{2yhlx2kdXS1Itq
h`B6$-;W`m&ZyuMu|_7ZQb@bqz?jQiv2Q5<d5jnt8cxBm*tmC+3|PQHbWUVQV&l(~FO?wh$wMtCv6U8J9XB;`8NZ_S8fZqpsh?yb
_dB4^<aD_iHC6K?umxNQ)GZq&sMT+$>9UtSpUgO(G!iD?A&{$Cyz7;ZrB%jpC@z5q@tR+~TigP|nV|&SmjlSVQI|dQFGs9+ncJ1Z
Vh2rGJ}{mh;%tJn-nT&TEAXZlEk}uWP`(V)+K?*K5<!L^JMXMY>w>6iOcs!cFFEJRuW%K8PYorWFq#<wL!5aH6D?QQdUwJO*NHB0
cXe}h=!%zj`N^@d0h?uL0Kkm}z^17s6fvJyb;gXnY^<B!kB>_r&?CODqYn<yS(@WF?ENfcAG_3)-Nx1<LUn&)gt;w62{B7CE#s)P
Hm+`Kb}&LSw0TsIG9op5bkpZ67SwQS2|Ikwy2yjltIyO!Vc`3-KlIF7{c3nMb+I*F&)P*@x-gu@`i8t-Q!LD~zP>o~14V>w^$f{#
&72|phh6LE)4)M+<FM1^uaCl9aV$wkJHFN<_p;@|3%K5|Uzt9)z5&^_4w_HrO12iJI%+$^A&Bn!YSAiqs-%sJH{+`<1Wf@B@ADXp
$7}7g^sDhVz?)ZOhi~-g=p+z-%j>$j%Y2Y#T*v)qCniOXGK{;t=ghlI4D8t*E-YTB4xnq$S!##0kU`C=x}EPNFkb27DT?&D{UF6W
(v=ZK-@qg40RY85bSck(VRr%ZDbK`WQuvgl3Yr`?rGJ#v<;1M8_&En#Ua)^)Zk{|q8&t<C!ED;Y@<dyf^DI)I%<xRO2a)6Ls3iEr
zY)5PEQRkMmth^kd$^oS2HN(RNwlCf2q=Z{v$Z1Xb#E`GS5hyP#N}HNt(?pbXWV``IeYpp%xXB`5&D^6&B}y4E6gU#T4%k<E7lZ)
woG+C2Sp`6YZvy53MJPbzYpx0pRE3A2M5M7t}@NLCi*yR#8Q^jSRNfV<6IbDY(y%HlyS3?kqbHga$y*LaI7O3ZQNUXbrJ)19It1u
9xfTi=AF)tAKcHwcy6wqnZs7ktjOetH+lXwNhIG>bI?(e`HAL2d^RYaKdO3>(IXw{3GB-hYbAl}I17@Iz%TzTx{zg~@8y*&=P~sl
N>PA-U5O|puZ*zcZ|x$DEYi>daiU0s{5VjotQ{Y9y_tmC7Yu%vIDvx&9Tu9i-HcO_H53OpwKw#!^ZgVb=}^hw|KS2CE~yGG-1^m2
``-8`!8NC@PCS2=N(^PWLRH3dr>sMZ)`IH2j@kM4rWlIRjN1{qFc^b|Bkvx{LS&xaqrZ$Ss>sX2Ch~b}m51Ea1|GV=oj0xUwF@Dt
w#*dOF@-P}Ck(wTKxwN8=9Y1}qefG9f4V91bPuTwu{*Ri5kzVt^%}6rM54AF)8{#Z+==6+jLGfaCTqQLNHwYSSM)CJii)^SCP_!a
_zS-iVm=^de-7KV+SSxK|Fhqvlr#Qc??WO|%i!am?;(|_ALw5fXTF*SbLk`Oeuzs+bmf~$3Siy6#ES|bdIBBgeWFE15!cqc1&GBe
injO4=(!U~byB}oc1Lrv836&#$H6Xdo@ii-=vXNGg(CsW<53_Yv?pEu7UtDS3a-KyjO}S)oD8w7<e2GHXQLf>3+H>D3emm3L+Y;=
2(i2|P|OGO9Bdr_PZ{4P(hqdLIK!`{1U5b_6D{zp;%sYs+!&%k@+bD+OP_^&)0m7G%jcMePmX>P-B2;!S}LY?bS{bef8Ma|s|8Ls
lqrsvj15&kD>i8uJ^k{*yUUt-mkioawKo3j{Fr<`Abnti0$|syb7=L=x;=viL;tAZRhGzm62qq4Yulwf@_G#G@-G<n;N%uh#+eZ)
LQ^#Hh3|^X|3nRb9THEYy|C=ml@>hdj_y7#8C9=PqzunAdSKmUlVJ%C9zJ8#7*!Yk@T8sC6Kea>W!nM$)|xNtjF%G$J9K-EIJ#`G
ON<tepL&`PhpZ&N0=4y5qKWoF?M6~ITju<vSH2EZewyR`Ee5i_gM_D7`COWqRfKq4`IqqE!V0J=_&gEg{QhiucS4oS`VS=<=>hzD
m*f#0duB^RF0X^nm`X{0Jv>E0e0mDK6S<%XIhBE*@<_BqGlCc%<n{zZAS)7BbW;;YV7_qJsL+`H)s3NWeFVQ>NNn(}fu)(frGG7P
lkxi!U%rH?NayTdc?p`VEK0E)QWK-X%tSpnvb)hDahwdMQFQuTf5@dXSJy}JDNnKR3T0r<&CT(7DNyuxo{z5BuJG6EtGc@~koiy4
GP`&Y_Ynvfbh<+jW8xgU$b&@7wFH{3cX0h?xBf?7Lq_-(bM7Sqo%|UyXSD@Rx7$$(yH($~W(4l6%|hVHXV+*VNEGFg*F#Km$M9h;
**+Jwi-xNeL{3|!CDH1&To4C$&_z55zo(bV1qOBP1$fQTE}~-<Z~Oa1!#xL}KUPxJk9c)~{-yxk`)c8sJQ^2ap0@AClxkH(v`CLR
HHrgtVx3aMi+DPW54RM|Pn*&+IOWwN(>{(u$Q8Dd$cnxfU^4kY#!Xm!f?-Uky4*+}t#x|(+45QMxwr+GMpvsnzy!P|BuAsbjEdJF
V$=Ff3cK%B%Y`XqL?G%bs<HtDph1EGPRbQ>ojE1awmjtQ7;fnSAsD*;_4YkybH4~HKj5-WxIh}7>Yh_gc(%W@X=%6kboBR)+Hq%l
9rz~^^QWMzQRq}pRkW24rVqQW*b#h5m%ANi{+|4S3|*ofATJk(Taa{gr@(7E?@ybjX9#*EM=EM=a45r8#z#83g_eCQs&1J$^3^<)
#*J<McY^U+@Wfv1sJ;OhRvgdEx1{+I=XN4Nj%xNas$fa7y7$-k5I*DEf$f+Jca<%2h&%Gbt<)TrgTr#_r^}Bps3^Q|Yacaa8Xb0D
rN*H+j*O|#oBy&J5-h6%+sL#^zMQ})ey0@vUhb!^R17mv^1;?Oun#1XH8cU@Hu2)gGqvQ>;uy<A0m)|~u^$Eg**yKs$@M8d-}Rnc
B}GI0U~UDzjH^Z%paw55L@743+`xB02Gxjg;W(;}(O@qJgF8Q{^WAP76M05rGV+&Xo}r}e@r~LY&xs&q^~bnd*20O)5|TRuhGut&
w>_LmY`PNpZHTL!!tpL7c#>UF83ec!dywizN%2oVuDqs_sd0;ASG62M?OCbaNqyY+eFkAeB6rm*W=tx_lNH8<WZ{zqCsKAS$UVNj
@`Lt^YNPZllA?$je5K}TWNQdaO<&?pnNqGo-rWq{IQuoUkV9b6Vlds5B+^HQSESt5g90yV@$HZ{Bg`jvwFmo5FHFtj=%=vTw;=#0
AX<qM)b`gp(#P|ej)oHEBvP3jHI6@TDGS{!X{FH`zj#?ug`t$gdLn_i47*9j0>3<snWB6*2mYM$1XhSNdunlrwB2Wr3Fm|jJ}OYN
<az&0N9F1|n6Q<g&+Qb$|Jl~O-5<3-Z0`P{NCaYp$$eZ+8@)^g+YW+LKhXO9aKnT=TmOgV7v@w6)Pynj<+947G#Sbk$muNCT%JFZ
cD2r|F4$biNjjAPd6o;sOJ}pvr8t^$HmDk>$EkOP4up$OKpG7Wt53YCqnXH;aFsU%fw5<?tN#dAUQ!Y!VA{P|U>+|V@HCxeZ1+xu
QD|*vWzB};{j=(KCVb)IjQGFIG+V#8z;u@DkSc{ZsJC!|Fr!y4ljt-wZ9XAMaVC}owV_&~oPzY*1G(TCw?pO_0GRaxnCg`Fg%b3@
<%cTSo4sayg#)*OZFtOBqo!$6FwRag!A+hugf+E;%r`kV0PtWK8Tt#g%7cLebvcq7W8#Wdvg2=ZG^7R%;B79FN+)s*alNtT9cN+K
OsD`?N5P}r>p(+oF};b8;@7iadG+}f5P?^X0IZD&sSouAVNsp%svVx^qG;d8u|;bfKf<9_D?P?FmtK_I&(?^Old@%G!k4cIEosnx
*dX&0ak7Kr`=Ye0QyEHd4&l4YB0uvIHk!T5A|%odMS8gszY5F>;+^94L#pcsrGCLN18J7WQ~=T8@=|bsd{Qc6M@zA(!i{w$eN)d}
$UuKn9=At6N{k0R<Vc)P@VS@zzp=LJ0mM*tIDb;-Huv;_>p?UzzrcSHx5J6#Oy94eTKz;p%xR$F74Llv5(gbT4p0_tM3+xYL-<3m
u9$iNx1pm5JHw=A00EGe0;tjjZ-;X}vBYQl0ssI200dcD
""",
}


def _main_cli():
    """Ligne de commande : une erreur de fichier ou de format s'affiche en une ligne au lieu d'une trace Python.
    L'interface graphique (aucune option) garde ses traces complètes, utiles au diagnostic."""
    cli = any(x.startswith("--") and x not in ("--no-uac", "--elevated") for x in sys.argv[1:])
    if not cli:
        return main()
    try:
        return main()
    except (OSError, ValueError) as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(_main_cli())
