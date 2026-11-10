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
VERSION = "2.5.38"
BUILD_DATE = "2026-11-09"
CHANGELOG = """\
2.5.38 2026-11-10  Jukebox screen saver: the checkerboard is back to its fixed dark grey (0x0222, as in 2.5.36).
                   REMOVED the slow tint drift and the brightening on drum hits added in 2.5.37: tiring for the eyes.
                        The three other 2.5.37 additions stay (mini VU meter, track banner, 5 colour themes)
                   core.S: hud_pal only fades the banner letters; fl_tab removed (tools/gen_saver_fx.py).
                        68000 program: 27632 -> 27080 bytes
                   Measured in MAME 0.264 (real BIOS, Art of Fighting 2 album).  Vertical blank, text scene, 5 min:
                        mean 29.1 lines (2.5.36: 28.1, 2.5.37: 29.3), worst image 36 of 40 as before
                   Tests: saver_hud.lua now checks that the checkerboard colour never changes: 19/19 (MVS euro).
                        Existing scripts against 2.5.36, same album: same output to the character for saver_test
                        (12/12), saver_perline (92 sprites at worst), saver_fuzz, saver_entry_press, saver_cover,
                        saver_delay, saver_anim, album_wrap, toasty_combo, toasty_sfx, toasty_wake, toasty_stress.
                        Not identical, by a few images of main-loop timing: box_mix 94 -> 95 sprites at worst (no
                        sprite added; 2.5.36 already reaches 95 with other start times), saver_endurance (Z80 buffer
                        minimum 10 -> 6 bytes at a track start, never empty), fuzz and random_mode (no reset, no
                        silent Z80, same tracks).  Other BIOSes and AES not run again for this version (they passed
                        on 2.5.37).  NOT tested on real hardware
2.5.37 2026-11-09  Jukebox screen saver: four additions, palettes and fix layer only (not one sprite more):
                   NEW  mini VU meter, top left, the counterpart of the spinning CD (7 voices, 4 cells high, x 16..71,
                        y 24..55): same bar tiles and colours as the VU meters of the player screen (at the 50 % of
                        the screen-saver palettes), on the fix layer, in front of the sprites
                   NEW  track banner: when the screen saver starts while music plays, and at every track change during
                        the screen saver, a 2-line banner (album title, then "TRACK nn/nn" between two notes) opens
                        from its centre (11 images), its letters fade in, stay, fade out, and it closes again (4.4 s
                        in all).  Not shown when stopped or paused.  Fix layer, columns 10..31, rows 6..7
                   NEW  big wavy text: 5 colour themes instead of the rainbow alone, the next one each time the text
                        comes back after the sphere: rainbow (as before), gold, the cyan / magenta / yellow of the
                        player screen, fire, ice.  The switch happens while the text is off screen
                   NEW  checkerboard: its grey now drifts slowly (grey, night blue, violet, blue-green: 35 s per
                        cycle) and brightens a little on drum hits (the flash of the big text); it stays very dark
                        (components 2..7 of 31 at rest, 11 at most)
                   core.S: hud_pal (palettes, with the others at the start of the vertical blank), hud_fix (fix layer:
                        banner and VU meter), ann_build (banner text, main loop), th_tab; RAM+1760..1809 (V_THEME, V_ANN,
                        V_ANNT, V_ANNB); tables by tools/gen_saver_fx.py.  68000 program: 25858 -> 27632 bytes
                   Measured in MAME 0.264 (real BIOS, Art of Fighting 2 album), before -> after.  Vertical blank,
                        text scene, 5 min: mean 28.1 -> 29.3 lines, worst image 36 -> 36 lines of 40 (the VU meter is
                        never redrawn in the heaviest image, the one where the small text is rewritten: each voice
                        is redrawn 15 times a second); the 7 images above 40 lines (big text rewritten when the
                        track ends) are the same.  Sphere scene: still far above the vertical blank, as before
                        (145 -> 147 lines; known since 2.5.26, not fixed here).  Sprites per line: nothing added
                        (89 to 95 at worst depending on the moment the screen saver starts, same values on 2.5.36)
                   Tests: mame_tests/saver_hud.lua (new: banner states and text, VU cells, themes in order, floor
                        colours, palettes restored on wake, no banner when paused): 19/19 on MVS (euro, us, japan,
                        UniBIOS 3.3) and AES (asia, japan).  Existing scripts, 2.5.36 against 2.5.37, same album:
                        saver_test (12/12; AES 11/11), saver_fuzz, saver_entry_press, saver_cover, saver_delay,
                        saver_anim, album_wrap, box_mix, toasty_combo (22 cases), toasty_sfx, toasty_wake: same
                        output to the character.  Not identical, by a few images of main-loop timing (the music
                        does not unfold on exactly the same images): saver_perline 92 -> 93 sprites at worst,
                        toasty_stress 93 -> 94, fuzz and random_mode (no reset, no silent Z80, same tracks).
                        Z80 buffer over 12 min of screen saver: mean 984 / 919 bytes (text / sphere) on both,
                        never empty.  The calm theme does not link since 2.5.36 (STCURNT missing in ui3_calm.S):
                        not fixed here.  NOT tested on real hardware
2.5.36 2026-11-09  Jukebox screen saver (Toasty Delta Island):
                   NEW  DOWN + START (player 1) pressed together WHILE the Toasty portrait is on screen: one of 4
                        Mortal Kombat 3 sounds (files mk3-09440, 09160, 09150, 09155 supplied by Nicolas, 2.0 to 2.7 s)
                        is played at random, then the screen saver stops and the player screen comes back, the music
                        goes on.  Never played in any other situation (no Toasty on screen, other buttons, normal screen).
                        While the portrait is shown, DOWN or START alone is held for 20 images (0.33 s) to leave time
                        for the other button, then wakes the screen saver as any button does (any other button wakes
                        it at once).  Built only with the "Toasty Delta Island" option, like the shout.
                        Sounds: JB_COMBO_SND_B85 / JB_COMBO_SND_USED (tools/pack_combo_snd.py, ADPCM-A, 95 KB of text in
                        this file), played on the same borrowed ADPCM-A voice as the shout.  Z80 driver: commands
                        FF 08..0B, block sfxx (4 x start / end / duration) after sfxdur; 68000: toasty_keys
                        (core.S), V_TOSW, V_TOSND 2..5.  (c) Midway / Warner Bros., not MIT (NOTICE.md)
                   Tests: mame_tests/toasty_combo.lua (22 cases: together, staggered, one button, other button, no
                        Toasty, Toasty over, normal screen, 12 draws: 0 anomalies); toasty_combo_audio.lua (the 4
                        sounds recorded and compared with their ADPCM-A decoding: correlation 0.996 to 0.999 over the
                        whole length, nothing after the end)
2.5.35 2026-11-09  Jukebox screen saver (Toasty Delta Island):
                   CHANGED the 4 Toasty characters now all have the same HEIGHT on screen: 94 px (the tallest that
                        fits for all: the mug portrait is limited by the 112 px width).  Replaces the equal head width of
                        2.5.33 / 2.5.34 (the portraits are not cropped the same way, so the two cannot both hold:
                        the heads of the bald man and of the man with the cap are now bigger than the other two:
                        head width 47 / 44 / 67 / 70 px).  Pictures 112 x 94, 68 x 94, 90 x 94, 79 x 94 px
                        (30 + 27 + 32 + 29 = 118 C-ROM tiles of 256).  Measured on screen: the tops of the 4
                        characters are on the same line.  tools/pack_toasty.py: HEIGHT = min(fit heights)
2.5.34 2026-11-09  Jukebox screen saver (Toasty Delta Island):
                   NEW  a 4th Toasty character (art/toasty_frame_4.png, one frame of the sprite sheet supplied by
                        Nicolas: bearded man with a cap and a hoodie).  Now 4 portraits, one drawn at random per screen
                        saver (never the same twice in a row), same animation, same sound.  Same head width as the
                        three others (45 px; picture 52 x 61 px, 14 tiles; 83 C-ROM tiles in all, of 256 available).
                        core.S: TO_NCH = 4 (toastydata grows by 360 bytes, the P-ROM program is 25666 bytes),
                        JB_TOASTY_NCH = 4, tools/pack_toasty.py takes up to 4 pictures (HEAD_ROWS has the 4th)
2.5.33 2026-11-09  Jukebox screen saver (Toasty Delta Island):
                   CHANGED the 3 Toasty characters now appear at the same size: the HEAD width is equal for the three
                        (45 px on screen; before 47 / 45 / 68 px, the bald portrait was much bigger because his
                        source picture is a tighter bust).  tools/pack_toasty.py measures the head of each portrait
                        (HEAD_ROWS) and scales them to the same head width, limited by the tallest portrait fitting
                        96 px.  Pictures now 108 x 90, 69 x 96 and 61 x 64 px (27 + 27 + 15 tiles, fewer than before)
2.5.32 2026-11-09  Jukebox screen saver:
                   NEW  a flying NEO GEO CARTRIDGE (animated GIF of 72 frames supplied by Nicolas, art/jukebox_cartridge.gif,
                        built in as the 5th flying object, 64 x 48 sprite grid, picture 53 x 42 px: about the size of the
                        console / triangle).  jb_box_frames reads animated GIFs on a magenta background; pack_boxes.py
                        takes GIFs and keep:K (re-use a built-in sheet)
                   CHANGED the objects now fly in equal shares, in turn: box, console, logo, triangle, cartridge
                        (before: the game box 4 times out of 5, the other objects 1 in 20 each).  Measured in MAME over
                        5 minutes: 42 / 42 / 42 / 41 / 41 departures (was 168 / 14 / 14 / 13); objects in flight at
                        once: average 3.5 (3.65 before), at most 7 (9 before); sprites per line: 91 at most, 89 in
                        the Toasty zone (limit 96)
                   FIXED  with exactly 4 picture sheets (now 5) no object flew at all, and with none the object
                        drawing was not skipped (the sheet-count test followed the wrong comparison); tested with
                        0, 1, 4, 5 and 6 sheets
                   CHANGED the spinning CD (fixed, top right) is now the 6th sheet (slot 5, palette 24).  With your own
                        sheets (--boxes / jukebox_boxes(n).png): sheets 1..5 fly, sheet 6 is the CD; before, sheet 5 was
                        the CD
2.5.31 2026-11-09  Jukebox ROM: Toasty apparition slightly shorter: 138 frames (2.3 s) instead of 150 (2.5 s), the
                   hold at the top is 12 frames shorter (to_dy); rise and descent unchanged.  The sound is untouched
                   and complete: measured in MAME (same ROM with / without the sound, recordings subtracted):
                   correlation 0.96 with the decoded sound over its whole length (0.61 s + tail), plays to the end
2.5.30 2026-11-09  Jukebox ROM build, ONE option: "Toasty Delta Island" (check box / --toasty).  Ticked = the 3 portraits
                   AND the Toasty sound (built into this program) are included in the cartridge; unticked = none of
                   them.  Removed: the separate "Toasty sound" check box, the sound file field (Browse / Built-in),
                   --toasty-sound and --no-toasty-sound (old settings keys ignored).  Verified: the 68000 program,
                   Z80 driver and tiles embedded here are byte for byte what src/ assembles to (tools/embed.py)
2.5.29 2026-11-09  Cartridge tab: the Toasty check box is now called "Toasty Delta Island" (label only; README of the
                   cartridge says "Toasty Delta Island" too; no change to the ROM)
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
JB_BOXDATA_OFF = 0x256c             # = boxdata de core.S (mis a jour avec JB_SECBLK_OFF a chaque modification du code)
JB_SECBLK_OFF = 0x694e      # où le bloc de sécurité du BIOS (122 octets) est recopié dans le programme 68000
JB_TOASTY_OFF = 0x268e         # = toastydata de core.S (Toasty, option du constructeur ; mis a jour avec les deux precedents)
JB_STEXT_OFF = 0x32db          # = t_custom de core.S (texte qui ondule personnalise, 2.5.27 ; tools/embed.py)

# Programme 68000 du jukebox (jukebox.S) et driver Z80 (m1drv.asm), assemblés, compressés zlib, base64.
JB_PROM_B64 = """
eNrtfQt0FEW+d3X3pGcyGUJIYowYYQgBw0MckhgjTmBeSSYh5jEJDxVhAskMogtjDBHYLAkMy6If14teLhdZ12W9fl4+dRVZdi8iuhAeIiLEGCMi
CEReIgrLIoZhYO6//lXd0wH2Zvd853z3fOdYlemurqqu1+//quruCkn4KyFbdSL8DPCLh18y/IZqfv3hZ74uTvmN/Bvx2l8WIf7lhMwswd+N6XkT
/gddWUH5XUUF5ULsCySBEJKwjBiISLSu7DKBGHo0pmmP/P6iEgf5v3SPlvGAQP6fuwBJuI8kXH3TBJ2slaFnW3UuxzskQTjkmA/Ho4VhM8kOEz2x
EtMDl+FIkrYSCxEgv+RLML2D/U8QEnw6L9G3W7cESH4T9EOXZdVFIGQmYuWHkW7rlsVqvNDkmI2xoYWkhuTss1+mIx8g9c2WrRAbzg5HIhAzIDss
nYdz6uCwUkcNib8AbREgtmxwt+CG80hznuAavBVCGWZb9mmig1B6DTFW1xDvhaQwkQhQ38LYGkImVu6PhGqIfmXJfJrHb4AaoX5xHqSNqSEJ5+Gu
AKZd8OkgbnoNkbpriCEeat1TQ3SdNSQmk6fvrSFTVnlJZFfJfbTt/m4HnsvmptP0jIxhxPBpaw75tqS9tWzuUBY3gpg+b80ZRlI77N+WdEK87VRh
+E4cfeLD+32J9OjHsL/wSBLtVbVBIIJ/QA6NW+1xmBxEqhMbSHYrvVbGAvIQv2Ec9GbKcsvAZCKKgM2AZIrrKhr2W6poG0pnZ8IddIRKvQYIJdKQ
AYjdL0N/Q14jhAU/9F2Ix1ZVG4Am/IlZNCz6ZDynV9m9qRAv+UexeI99A45nnVhPsrfRGEo3RIfHQqWFZXPhHp0/D8dP9pvxXhveKfpYDQ680lE6
EkstWDbGwzXpgLtj/DSF1i3703k5ydmUdmw0L4YcND/0ZZT3fcin7zXfUO+qsrmsrhpyzcXq8+myhpH+VXbsjc5rVtMzWDr0+FHSX+2vjsVi6wtr
ZYwrRLwKZQeJ2+CoM+rsxMjio+PhPrUV8IqBkb+6BX6bSo8QqYaYxmZT1G2Y24FhkdVSQyKrsSU2yL2Gjxi0o5YIkHb1xcykA+9Qfhg+gubVPZs5
ghgQA49pSQScP56l8xZ4Bu+AY8Lgb4kJzsmYc4xlBEnGEfP4403zMd9qv67tMZKKLamAEcuBsut5GTI/u/FuFx7741HJUeYlOsbfawtC059LOOgL
Vy3LKG64NaW/X07YXrkn0g3xv2Lxudgnj9O9fWmYGGWJWBK2u53s3KBPCBMz5A+ZDboWWh626EWsbU3ZXODVLRiWWVui45xgJRFI3Yf9cvni4Vri
qS6vEa50Pe/wEull6LtIy/JV411uXym/28UQYKPPeBI4UvCTa1lwFv1Da8iVayyVU0l8PfHY1nMOCRAvuWYom9tI5pEFxAI4XWnbRNNsPsMY6SAN
OTrhLo9rE7vjkMlJxLoSWruQ5kvA2qcDHQu090JaDbl9Zo5U5WhpddvWF9SJHpsVSsZy54Gk6b/FUSe/6PC4vGctuizZS64u17Yfrps4f6j9G0dT
UvHoZiMnroQzUKm4PPsIjcVjKpYzHJGdWC93uWt1CVtIi2cZyO+LZXM9tDQvlmn2p2Ner2gj43wpONZmXvIYOFMJnMWlKiEXWYlOepxVLzeQ5IRG
ktJvo3OGLnGx10TDk5yzxEaSGHzYMQvkYEKr52mo80CAsFpaQOK7bSU2Xxa2YSotT+jC/k5tiBHtZGCu0Ol0hshJy18s5CE7UNRZQF6mmk5tp97H
+reGI/ciRQ7pbQ1DIIs8T+NrMa7WZCfyDLFe5mM5ko9lRmtYOv0pcoNp/qnR9FyXoOMhbF1/78myucoY0r4qfYIeXQDtsrI5IogtZE5b0jlBNCwT
xIaLgtj8nCDOKRPEaVlwPiaIyc0QF7n5r9xVXlu+ZM4rc3aUXxx1ceTFRy/6L9ZdzLmY8WPG5YwrOVdzIjlHkv+c/Nvk5pzyCeWTyh8sTysfUF5e
Pq10Wkm5u7ywbK7WEkDsLuARdKW+gmrvu0AnT8xVeAd7PtNvAD001Uu619WQB2fDeS3KGsPgnXA04f1ZeMzBY57Co2Q4oweSzq/7w1kA6Z/Irym3
inAtMsryTU25j2p3USItoCshlGe9NdAf49JiRJm0bJF88ZV7I9/z9pmhP3hnE6Rn76IUbJCJPHGnWAAcRVvnFgvJuG/KMC21bC7YOBEf9CaygrYA
EFnmPhXZynEmZDNrV6SetTsyi8tMGSj5pbFW8ltTEfnVdLNpPjQayqtNAeoBXvrebbIJ6+sMcDxfR0iDiZYH6XXUPKYy2uQrzKR0lsAlNyHu4fQ6
GUJjVbmcwqXUmDoT1L8d6vfA2AwAPfU8UtcYbwuMGciIyBiwfBohzQjjgHKt9IgUKZtLucxAkDdy/Ga0EHJQpuWtpOFc0dEcAetwtBmkFlmCvc7y
JUKZq5DuLVCagcbhnVldlI4ttdSSaPSC9UUCWQTsEr0v/XRxNdOlOcBbfY+5cyjGnhaHx4bl5HqfAb5sVvJAWi7PM0qTB4BgbUtqMROPg7YNbaC8
KhwxsLxoqsFDrwxmDAPr9I1EfCmmd5hlTwx1RvkdDNE8gtt+utgP9gxq7gF+E9Y/AI53R86ze+UWsF+J2QajkFA2l9ul1rF5Qmn2BxAa20S2FNVa
gFrgDuBjyOsMPXxyQewfDL7kyo8joS2pPlOqXKjblOrTeQq97UhXVsW+LZuLPZqeK9LxFkzZ2+kR9IhhhtggMJnoNzGU5U2AfS2zFVvQPvSPYpzI
87mYNemIWpNgQSo2Hui0mVzGpn2Gd9UaeCvOm+YXTMEYoFngRI0dmkI562qqIOrItaU632QwFEURrNEWwZ/JahPvI1dpfjhfYzXSWuQdPmpdJtMQ
u/bbDPdRqr26ym+EECBw9Q1f6r9i2vQMB55ZbwDnvFwmh51EqnbSMZG3eA8pcpJphoDsSHXcVrk7Erp+vmHKYfMNLO0iHi+h9EqGFqXBFcwAdPus
W1oEi5U8n9/UNwL5d0e6A5X5TXoexvz9UXPsC8Q4JkNcGOMy8ZjBpIkwlI2gYM4Og5BKENKv185A7RKGBrAWwhzoNqj1Tpz9QNuzw+FUSJ3Fz7uw
9B1Y7+OBWzX17sbjHqjXDOe9eHWQ1w66Ptmqlr8yv+mSQMTAnRBjY73Jb3p2Uc8YvB/shBqS+OxCIUf/XYl1cRPJ0VcBVxF9rkxH/tT4DidYr0fz
warJb+oHyHsKTYUkse6Apwik2m112CYZdYJ8HI9dXC4mcP1nYOMkd9FUXSlcAe66shrS1wy/tUyzLBRqyNBDMONYNRjSE96gcTXkwmvwexVi27jk
vlA210vuTKkhdyZmh8V0YhPT7aHkzUANNtFbHxPom3WAjpb9NEmgujM73EKIbeA1dhbhnubzcHbwa7D1yl3EJqVnh+fsgDPEP3oRztOzwxk/wnlx
djgnAueXs8PJzXBuzQ4/WA7nruzwtFJi04lm2t/3obbTtAU6c2Acq5/rlwsgu5iGO0915JAw9m0d61u5oae29JEJWV7iKVQxBMoUShUaYSXKm/G4
Jcopcistc+iztB3ZdJYLEqJsLpcFqcrII/dtUpHgOeQt/gwqeXh5W9yngHlRk3WvSxCnQIu718JspBl4LpQcqCcBqaTCD/M8+2lhJrTpYoBMsNel
Vdu5xbXNjVaS3OozgL1kV2wluXVrWJgJJYz6ZOvg3bSdvC87lPayUYSy0WaXN8GoPaTGlWZlErHK7jxNDAWnSWaOtbKFj9BiyzAiTi4eWuI15D8M
1PkwjtSlgjMkFSjWBvh/Zd2yqDCgj3J32VxldIMQHx1b2gN5kwn4wl8IRwH09itMR8qb2LjzkdvC2sXalJNJdOdKlBJ/WUh5RHYYCNR8CUvc7Ayl
HgBbdTQhJolE/BUeLIuV0TmTyJXOPKtwfrWTlQd0ZIi2LyfVkupP/qbE5ehwiQ4hcq5kiY3W4NXxVZOjVBOxEQRpmWkPDbytJMGXag8NaOMcaGAc
6NfZQ+YYOvYkHCAlqX6dx+btRn0KI8LsCLmLrnXEnsQZhsFvRNkAFk/f0yo1Ef1ZsHqOshbS/glQDrUaBPlUMeCtW2FnpQo6EL4gQXzJY8jJB8D+
WQnlVHNpaRiDd04uyIlheU4+gGXB3OGgDfK+B3kzczFPjgQSSO9yik7o/XjrliUr82EWNBmlk8vBxgRi36OjgjR4sZrNaLrHCt8WnypvL4JWjVlh
x55ehFWdkgyaGgbLqGMjtQXCfrCEIkD0guhNZXe2wozzX+ZjjMzuY/oG1oioZZ7a5qBaBXuZCnOMrdU2oJeYGWIg5hPUMag3H6Z6U0ih6zZCynph
hoHPLJKb0MoSkv0JVaiL2u32UH9itSQAr8kr7VSKibTv8tET452h2KXpT1gIsw26Sur10O+BuWKn0zLaQloKLVsn0rac1eABM0zQNQOxdaQB7xRS
l4SJN1esdn6OGqSrxOP4DLUISz1ZArxiBltjFtgas3Dc9250+k3TxQlOD2pdYW9BaEAiawW0QMijeXYfL0Uc9xx/wCruDZO4A4V41q8pZHqrw9HW
ujDOqgM7OpIGcs299FBhFp13RRKzwLxedMj+8fajS08uPVdmWTp5mewiKboCEg/26T4q+bKIbBfC54plO0lk5TXcmiusmkzxh5naJUBdyCWdTpfz
3PiGW2ms7AS+g5SCUPwr1kTQUIBJU0xJoZ+I3dERojM2aIPkG3XcTW1QwM5QpzNCqM1mD6UusVgIQRQWZslVdksLcKSZ4o19htl49g56NugI8aXX
E2YZOM8A9SWAxKukEs+y1fkNscCcv7DuDGI8lPJVHM6vBfNjaXjOBPlyga4/CVSPD1DsB4tuBdoVj8E6F9JJZgOJEfwmXO0z1l0E63sLInQQ882C
1o+DucI6i7Q1TCwl9bCulsLL2MXTlmOLZ+FxF9LIQWhpoSKbhYOsnpht1OYVMrPEE8WsNOcFGCjawhcHPZ1AOhwYnjg6aGa9Hj56iRlo1nihJSzY
3TadjazF+LGjWzD+IJ09t9GWpLe5sKaMBSQ35sR42Qm2D9YZR8CSBZo4UczqSQ/A5CEGOALLh37ANStzLPBHjlXwlhTNEVcWrXfUodaCEhZTy1/I
tAapRNT+YKS6swjlrqTjWXA3szqFgX7ZZW9/lIyC0s6vtDMJ0vEogRKoDIGVkqH1YpXjMQOzkVRJ+30OLA4Rc0cRs1mxHAfcN5KVIDtFwkrA0dRR
CoO+NYJED5lMGywVBPCeaYkBGsNRzAEqO+Xucq8oYBQEvBIwE6Af3YpKb/fWb8jwtkepZpEdSYSOD3DBbd8Vj4XW5Q4jmVVO66JxUj60j9bosVV+
FLmYOxDy2IB7TnoKTAVAK+TaSmfItLykEtqxI5fxrpNEYBWpZYYhD3T8ameu7uR4uO47Q2zsmyd9O/5E6SpXQeiWFR3bi4ADJHFhn9yDUGKY8Q3j
F6VtOdZU1dpOsFkXRVujhCC+xbooeq1NWWy3LsqxnlWuHHA/hpZg/DLCrxz0agVegQV4oQStR7qmIL/mheUAVn8eyv3juE4siJts0N8SpHYRV+DD
VpTqHtsmm2/kWJrHKBcR5xidXEBXMQ0P4X1GD5XilSpXGL3As/oFbC0J5XycbCNpkMcGkp7pmNB6+wzjRPsG2wxDFvHq/CJfJw7BGm9aV3Eg9tij
BaE7DnVss4fSOlktsm2x09qCaFyktrVF6nR22rrGYx8uHXCtdlqtQmR3YYAsrHiJ8o4xIctG8gNAc+IU1+5CQOM864M/taoI5KTzxnSlpiU9aqJy
coxVVMulErOzAPJ38/ISaHlLnNH40iP6CLeLutAuGgtHnW8m7bt83IN9lY/Ditf5ugRm+4OOi6G5vS6ITZiRAccjdXkuO1DmOV8KSDu4n3IVDQkQ
EsSyuZRDb/kq+zxMyyEFwhdZmKZFpTZvgYdqWuCkJawNFuFbt2x7otDawmZ77Bi4ZYX9ZvGaFsfV2dg8xZtH+U8+iRr3eMC4wgmW5/pAXBs9r2Pa
D+5wwh3xah919E4+Bw2VmgpCwgRmC9FZnn92m60oJOxcQPpnw9MmWEQggiWGtidQYG2pJ4kgC6AFLTOAb0gLyIlw0QVYLAHJkAM2ouww0adwt7c5
KK/89yEPRenVsrlZ5FuQD9DbRbR0WH1KybcTEcMpNUZibyH0Gqw8WFmB5xlW0x30iUP3edbzwAhcTQcbWHmicMINFuJo+hQJeSKl7kKJzZ9hGg0z
zohPV2Xznq9Ped7WVczub9s2tLjKlvAlzrloTATKa/YsKwiRPODTQB5bAXdB+HFIuTsP1qIh7PUso/nUMaV2dlfpkb4Dy+ZWe+zO8WaieQxKn8FK
8AOlCwQGowQ/PfzguY5An0vRZ1D0mRJ9MkSfCdHnPfAzGCAZnuDCT4KfDn4x8JPhp4efwWCAZAMkGyDZAMkGSDZAsgGS0cGqhxBDWxB7iJDRE+G3
Cn6dMKVLoRSjK6tyzhrLpJIvkVm3ulL6ZCQXVgG9GWy2C9fvIw0fxfGMUWdFR2kuSmG6suisZLEzUBGdlbDYhcSiB+lz8js3pejYeJCNeqAcPdUK
x4opujgT99YdwBor8OjBYzUeJ+JxMh4f4u2cwtdl1vJ5zbrs8CB4miK/jJjQuc9SOL+qadnJwLSe8yXdlCpck9NNmZUFa/en6bo+tPMhFgcxndQG
mMTyTIbrXZprlLu6yZSTddXr7f742Tp4nsi5VFeNqQ9h6sQbUidiakUb9hDKjGCJFRjrwdiJaqyHy7C1NF5eByutI+fEw7x6JLO55HXeREAl+XET
rMckq2NB8VmLUuYVNruVX26zm2yDWn6WarEOgtVUIcR7O89lyyI0DqXLK3jny2exj3T0YKYBT4sjCwtCiW2s1amwJu1eQu1bsDLBGu5PreFfsran
0bSl0bQBNO1XYMOsLAolr6crXjpvQSj51YRUd0tiqntRcqp7ca6wfec4ceeO5x1n7TkDP9ixc2eH86wjl2z7AGJ3tTnO2iB2184PVtJYmJ2Srdta
j9rGkS5b2zQck7XbW4/axwld9vZp7fT61RyJzp47HDlZ8LzfAbqenCvJptaRxmbyOLIWg50rv/1RHax6KzTScpLKAF1tYFp+BUjz0zC/3U1t9cUs
3nt9/BIWP71nPMxqUX/jDNSo1eKsHtDKOtDIxgx43LjQ6f6PtXSF+KXS35IYbifrGmAehDyxsu4oxYCUtoTFyW6bbBMno36Hp3MkD8rQu23Vtgzg
QyFvyVa411wrNpjRpoQ3B0gKleh0RUMY4Me5oGBm1CQAUOeK/wDIHy3uwvMxOPK1PlhYioDmhFbGKK0Ee1u3otDbDVIZJCvYB2aQxjb63NginCpu
s7Xb2h0Wod3eboNZD2HrcJSv85sS6Hqb/eZhtm4vESvOnjdDHWugjnmZ7H5aV4VS1zRal2yPJezuRFpSAdwhLiCeInguso/qBFy5hvJAdl+D3m9k
T7v5SoKs6IcjmUPpU9vblae2LN1nBD0YB3ct9E6F+3dBqCEq+0kgKvtJLaRvhHM1ptOYBoh5C84OjKlYjU/EakW6Lkkm8xUMA+T5DVwPgPMGig17
+isxew2eY/SFMWdPj8vmiksoBiYXmTFDnDdjGX2GrINnxzvcLnZWckCK9W76PL0N2jcmc6DbBesoO+yljgkPmM3EbDbfBT+ukJSr4gcK1AtPwQP2
4rLisiI1psI+oarApVxVVZdXVEQvgcxE/veT+8n95H5yP7mf3P+f7hFPsS1v9PCMgf1vTUqINxljDXq9LMt6cAbF6bVOvtFpkw29u1hjnCk+ISnl
tjRzxrBR2XljXeM9D3pnRkB/g/8k0h75FHxH5LNIJ/jPIwciX0QOgv8ycihyGPxXkSORo5Fj4LsiX0eOgz8RORk5Bf505JvImci34M9Gvot8D/5c
5HzkL5EL4P8auRj5AfylyI+RbvCXI6HIlUgY/NXINfpWBk5T4d1K8DqYoMJ7JDA9NZBY8EYSB2/V9QEfT/ri2wb94Dl8Esy8ksktJIXcCj6V3Eb6
g78dnkrfQQaAHwhz7UHg08lgkkGGgB9K7iSZ4IeR4WQE+JHkLjKK3A3eQkbDWy5ZJJvkkHtILvh7SR65D/wYcj+8Y2Il+WQsGQerKzZih7cdneBd
pIAUkiLwblJMSsCPJ6XkAfBlpJxUkErwHlJFqsFPIBPJJDIZ/IPkIfIw+CnkETIV/DR4GaQGnnJPJzNILakD74MF3ZnkUfCzyGPkcfA/I7PJHPAB
8gS8Yvsk+AYylzSCfwoeO8+HV98WkJ+TJvIL8AtJM2kBv4gsJkGyBPwvYQ76K/DLyNPkGfK/wC8n/0SeBf/PZAV5Dvzz5F/ISvKv4FeRfyOrwb9A
1pBfkxfB/4a8RH4Lfi35HXkZ/L+TV8j/Jq+C/w+yjvwf8K+R18kb5Pfg3yRvkfXg3yYbyB/AbyR/JH8i/wl+E3mHbAb/LtlC3iPvg/8z2Uq2gW8l
28kO8DvJLvIB2Q3+Q7KHfAR+L/mY7CP7wbeRT0g7+E9JB/kMfCf5nBwgX4A/SL4kh8AfJl+RI0I/MV3nkn2GZcbXFoCPe/fn75r2Nu3tc/gXh/87
HhT6MW8D7xUCMMz0WAEeXpUaZE+vSXyin5A+KHF0v340V6KtXw2kJ5CkLEd2fXp9uj27ZnBlOs03KKlfv3RxkFBBkp1O15PZSdmiKz3HA7kS0ysH
1yTWi6MFr3BLtWtCgyvZ5ZjgKMjOScqePviJjMp0Z1Il1C7XxfhumeCaIPmkic6CGZCaeE/64OQke6JX0DfKT6X46iY6n3L6dROTXTNy6nM92a7k
xMSAYPjVvU/pnxrqdy3LmFk7qXpC7T31RZ6culuyEkcLsavzlhmW6efFvFA7f8jMIRNvKUiaPPie3FumJw0S+6+b98LMpyctK3htyDMT5k3w1RU+
+WBVgS+lHtJuf2f+a4+umfyC/G7Br3Pn5/pTJlbNmlE4aWjS4EFi2p4F7856/b41hXvlN+59Rj/PNynjseSJhjuljH6Jd3z5870/f3fM6/rDhe9N
+vWkZfqZribXJHdmVUZlYvxZ6+G0vSVbir6/833DG3lPPzWz9hcNk+ZnPplhT+p7Nf/7Ow6P/9gQ8e+f+Xv3GsP8mGdjZg4fljHEnjTMPsw+vHJE
jWnRI89N/d20t6e9Xb6hecOcHdM+m3aq/HLz5Tmh5svllyHcOWdH84byDTTH1N898pxp0Yia4ZXD7IkRTyTpXPUReX/mW8P/eWTzI7OnTm0uay4r
nzrnkebHyp+Zs7r8T8075nxa3tV8rPnYwq5ffD3yxPBThsvyFdfVpGuOSJ/EPomPDBowOt4+tWKgtzxQHpgTmNYy57nyDXO2T/t6zvHyi3OOw3k7
XD8H8QGaY6B3akW8fcDoRwb1SXyivHJa5Zys5sTfZr3l2e85Un8k+0jyuZRzeef6R9Ii+ZFfwC8t0j+SB3HJ57Ih3XPEsz/rLcjfXDmnchql0if6
1ac/ma1zxUyQffqnnnpq3rL5LxiByimNUwoXEkTzYHOG5R5bbsW93tTA5JYHVzy0dvzbpdt+tm32J3OOwZcZZvgyw1wyYXyBo3wyTKYKykrKHzQX
FpcVmB+YUFXsNA+CyLJipyU7x3y32VVQWm03F1eV2stcZpx4/eTYByzXDWS12142vspcWO4xwyjCPLbaXVxlriovrJ5k9xT890MqSjGyIZZq5H5J
ySm3pva//Y4B5kHpGUOG3jls+IiRd4262zI6Kzvnntx78/LuG3P//VZrfv7YsWPHXe8gLj/far3//jH35eXdm3tPTnbWaMvdo+4aOWL4sDuHDslI
H2QecMft/VNvTUlO6geWRlysQY6RRHLt6pVQ948/XLxw/tx3Z898c/rkia+7jh756tCXB7/4vPOzjk/bP2nbv+/jvR/t+XD3blgA27ljx/btra2t
27Zt2xp1cAVx27fvgHWzXR/s3v3hno/2frxvf9sn7Z92fNb5+RcHvzz01ZGjXV+fOHn6mzNnvzt3/sLFH37sDl25eg106qVxsWL+9/HWxFP3h1Pv
+0t33oC/3Ns16B7T4Zz4ftmHTKPv/NLy7YhRP568a0hoZPuQ4QP3DxMzMg9fG5p9ZMiBezL0HekDTYM+SjNb9gw4l3PH6TNp95zt/2HObbfvSu1r
TtlnvMXalvxlfuKVzn53kb6tw+NHtfYJZcUd/ME49qvYPfn6fh/Id6TE7EiV7t8lnsgXvjsaufev17blXB2y7YphWGi/eHlcx4+fjrsk7f8hM/av
rYMvZG//y4Xcc13ffT/m1NkP875N/eBMctrpj/qeum//yaP3Hb90+Ou7wl27hx0d+uGRSOZXh64cuufYl51ZB2M/O3B7n88/Sekc0dFxfvin575r
z7zY9vng/bcc/NiQsrdL99HgUx+eGbg7cvaDZGHnyfgd/b7ffjVuG3w6RGIejHk4ZkrMI/JU2SvXyNPlWrlO9sFC0qPyLPkx+WfybP0c/RP6ev2T
+gZ9o/4p/Tz9Av3P9U36hfpmQ4thkSFoWGL4peFXhmWGpw3PGJYb/snwrGFF7HOxz8eujP3X2FWx/xb7Quya2F/H/ib2pdjfxq41vmz8d+MrxleN
/2FcZ3zN+LrxDePvjW8Z1xvfjvtD3Ma4P8b9KW5T3Dtxm+O2xL0X937c1rhtca1x2007TbtMH5g+NO0xfWTaa9pn2m9qM7WbPjV19Ons83mfA32+
6PNln0N9Dvc50udon2N9vu5zvM+J+JPxp+O/iT8Tfzb+u/jv48/F/yX+Qvxf43+Iv9T3x76X+4b6Xukb7nuNvkVASMFl+vbZArM3HtfWWgroeqd5
gdEZah/VRBwVlttKivxGeFvBWAvPNcnjo+HJjuU2CE2BkM5ibaZvO1dAWLZYxVwIuyBsaNuJ7+Al1L0PK9kifT82p4W9Fym1OLFe+h6c4mGdNgXW
Vc9nt9G2wNs8RT6RrvfNAzNsnqEhviZ5nq6hT038PHgBucZgkeCNrwH0udLpR2ENum+7PYbQd766ivHbIjFme1fxN48utZfNPSN9E/xGOh08LZ0K
npJOBk9KJ4InpOPB49LXwa+lrmCXdCx4TDoaPCodCR6Rvgp+JR0OHpYOBQ9JXwa/lA4GD0pfBL+QDgQPSJ8HP5c6g53SZ8HPpI5gh/Rp8FOpPdgu
fRL8RGoLtkn7g/ulfcF90sfBj6W9wb3SR8GPpD3BPdKHwQ+l3cHd0gfBD6RdwV3SzuBOaUdwh7Q9uF1qDbZK24LbpK3BrdKfg3+W3g++L70XfE/a
EtwivRt8V9oc3Cy9E3xH2hTcJP1n8D+lPwX/JP0x+EdpY3Cj9IfgH6QNwQ3S28G3pfXB9dJbwbekN4NvSr8P/l56I/iG9Hrwdem1YAu4xYuXLFmy
FNyyZc8888zy5c+CW7FixfPPP78S3KpVq1avXr1mzYvUvfTSS2vXrn2ZuldeeeVVcOvAvYbuDXBvUreeuQ3MbeTuT/+IU27iZfASsXRaDauQVk2b
AC3BFkHLoH3YzjVroM3QctoB6Af0hnZq+XLo37JltKvQ48WLaecXLlzY1LRgwYJ54BobGxoa6sEFArNnz3788cdngZs5c6bP56sFN336dK/XO3Xq
1CnUPfTQQ5PBTURXDc4DroK6MuZKmSvhzv2POOUmXgYvEUun1dDqWMW0CdASbBG0DNoHraSNhTZDy2kHoB/Qm0CAdgz619hIuwo9bmqCvmvwX3Y9
/Brw1yD0CvhR6BXcGfIq6lrAN3G3+R9xyk1aclApQaECRgc9iICRACWCNRoSuJ4Alt0U/0YOfyDA4deCP10LfhR6BXeGvIq6FvBC7lz/iFNu0pKD
SgkKFah0ECUClQSma0mAEwAlASSARi3+i7XwL6fwK7yvAf9FDfSvqNBfj7uKuhbwLdy9/4845SYtOaiUcD0dqETwioYIXuxBAooMWE4pIEoAi/8G
/grzI/zXcT4DnzP99chHgddi7lCdrXcXzaylhZ5koKUCLgpuJAGkAIUAHkcC+Hvx78H7XOxfz/c9sFeQjwKvxTxqqrb27qKZtbTQkwwYFWho4AY5
8BKngB4y4Kb4N2nh57K/B+9Hwe/B9z2QV2CPoq6Fe6zqrL27aGYtQfSkBEYHGiroKQc0JNBDBqAO0BJAkxb/ZxT4n+fwc/S52FcZH8Hn0DOuV5DX
4q6Fe4fqdvXuopm1BKGlgygVcEmARBA1CCgJKLYApwBuBnACeOam+Deo8M9m8HP0o5yv4XsOvcLzDHkt7lq4x6gur3cXzawlCC0dMCrQyAIkAo0c
0EgBTgGUAGarBNBwE/yZ8n9W4X7K/Fzyc8GvUfgK20e5XkFei3sU7t2q29O7i2aOEoSWDqJUoEoCLgg05oCiBrgW4DoAjQBuA16PPxP+AYX7KfNz
wR8V+4rCV9g+yvUK8lrco3Dnqi6ndxfNHCUILR1EqUCVBFwQqOZAVBFwNYAiQNEBzAbsgf9Shf0R/pVR+DW8r0h9BJ8pe4XrFVGvAq9FHSDdq7p9
vbto5igxcDrgZKAoBUUSMJOAkYCiCTQyQCWAlVwFMAGwVIM/t/0V4f/49fBznY9SX2H867ieyfkou6uoA6RZqrP07qKZo8TApQInA6YUekgCRQww
TaBRAxoCeFxRAXwOcBP8n0Xpz2S/IvoV3ldUvqLvEXwt1zM5rwCvog6QtqmuvXcXzRwlBk4IXDswUaChAU4CKAW4MaDIAFUJcAmgCIAb8VfYn3F/
VPRHBT9T+T3A13I9A15hdxV1gHSU6kb27qKZo8TACYFrByYKFElwHQlQY0CjBlQlwCWAIgC0+DPrD5U/Nf17Mj+1+hD+nuAj4yvYR5meS3iF07WQ
d1DX2bvDfFpiUKQC1w5RUaDSAIqBniTA7ACqBLQiACcB1ARgFiDHn1l/qPwV3Y/Mj4qfSn6F9zXgI+P3xJ5JepThCqdrIR9OXWbvDvNpiUGRClw7
MJXQgwZQDGhIQJUBVAlQCkARoNgA1ARgFqAWf43059wfZX4q+jVyX2X8G7HnHK/wuhbyA9Qd7N1hPi0xKDKBS4Ob0gATAxo9wOwAVQSoEkDRADfg
r0p/lfujzK/wPtp7DHxkfEXiR7HnHK/wuhbyodRl9O4wn5YYFJnApYGWBpg2UMUAGoRAAaoMUEWAKgFUDaDFH8U/sj81/dHuZzN+rvjR5mOsj+ae
Ar6CvSLvOctHeV0L+SHqvurdYT4tMURlAhcGij5QaUAhATQImRBgdgA3A1AH0HkAmwSgAGAK4Dr8kf1R9zPNj/Cj1YdqX5H7XOFfx/cq9JzdFcw5
6unUmXt3mC9KCUgLXCCoRHCdHODmgKoHmC2IliDagWgFMBuACYCb4q8qf4T/RT7j54r/zSjrU7nPFL6W7xn2WugVzDnqR6nr6t1hviglIC30JIIo
DXA5gOZAVA9QIcAtwVf5asCLSAAaE6AH/qj+o8rfx+FHq1+x+pi9r8h9JvS12DNxHxXziHp6ehT1AdSl9e4wX5QSkBY4EaAwYAqhBw2gKojqAdQC
3BJkMwFGAD6NCcANAI4/XftRFn4U3a/IfjbhW89Nvijr72Cc3xN7LukRes7PCurHqTvZu8N8CiWoMkEhAkoG19MAMwmjQgCnhHxFQNUBzAZQloFw
DSiKP137URZ+cNo/PSr7ueKnkh9Zn8l9Pr3T8j3neRV6zs8K6v2pS+3dYT6FElSZoBABkwU95QAzCRU9AEKgFGUANwO4DpiOCwHKMhCuAWnxR+Of
Tf1Q97NZH8p+yvzrUfIz1n9fYf3dzNTTYh+FXmV3BfXT1J3p3WE+hRK0AkFDBAoNMKNwtyIE3mdCALXAeiYCUAewpQDEn5oAOAW4Dn80/lXbT5n1
TUbRj4qfGX2q3EfwmamnxT4KvcruCuop1CX37jCfQglagaAhgigNoE2oCAEbEwJutiaAIgBXA9hMULUBcQpwPf5M/CP8bNGnB/NvUIw+NPn4LE+D
PUWfYs+h79IAr6B+lrrve3eYT6EEDRl0qURAaSCqC4AG+MyQGYPcFNzQQwTwpSDUAFwBXId/Pcefm/4Ufm74McXvZsyPJp/C+gr2DH2KvRZ6DryC
eiJ1Cb07zKdQgkoGWiKgNMAsAk4DihBACkAR4C7hIoCbgQx/JIDHmQV4I/584Q9tv7XqpJ8x/0Yq+ZneB8mPrL9Xy/kK9pzrEXoOvIL6eeou9O4w
n0IJKhkgEXBJEKUBhQL2MiGA0wFcHUQzgJmBfClg7UsK/lQD3AR/ZeGPKn8q/PmsjzO/W9X7IPmR9XtIfQV7LfQceAX1eOpMvTvMp1CCSgZaItDS
ANcETAjgdIDZAW4uAvhMkNkAtT5lGfBv4E+nfsrED4U/M/xQ8Uf1vsr6UewV9LXQc+AV1C9Sd6l3h/kUSlDJQEsEXBVEaUARAho7YBObCVAdQFWA
Mg1czRYB/hb+s1TTnxn+KPsVxe9S9L7K+gr2UfS10HPgFdSN1P0dL4hjPoUSVDLQEoFCASoNKEJAsQNcihmAOoBNA9RJwKy/A/+13PDnhh8q/vdV
0U+ZH1m/J+dT7LXQc+AV1LupC/XuMJ9CCSoZaIkgSgOcAlAIRO0Aujy8mc0EmA5gNsDfjT+1/Zjhj7JfUfwOW1TvM9bvyfkUey30HHgFdfxYQNe7
w3wKJahkoCUCLQ0gBaAQiNoBNodiBnAzkNkAaAPegD9d/UHrj9n+q9dEdb9q+KHiZ+Dv5uAj69+IvRZ6DryCepi6a707zKdQgkoGWiK4gQYUIbCH
CwGqBdhMgJuBqg2whi0CrEALkK4A/f34M+ZX9D4K/puhjxIf2Z7zfA/oReZu+l4rT+tBBFwWoCBAbXBTCkA1oNgBXAT8nfjTXb077LIjQOBrXbq/
uY5+axw5A/t9peI+2rIXdsBdSr9fLaH7asC39HhsNNNclfvobmSNJFdH9zjOkdzOcVKjpdMBaftgNxcnsdBvUbXfqSrfs0KOPY2wT3nkVf7F6hao
8TbYm+FpLHkFlHwev3oeq+wrp5+FoTI/7mJBYOe9mDfgN2ZhTH0MfMteGpDq9XCnBb7Rb4LdGRbDLpH18wT+5W8a38UvGb/O9Z4sFV1EgrZIPnGe
EBDrYa/qa5dydbJz+SgoY0AgGWOON4qrXLLTNBraZ6S7jxrZbqUz6d7dcolmj+WJf2unePiGmpW+Ote6/G44twZ0eL3MHtKvW0BwnNNyYuBrdeOx
km9KlsLYXXsJ97+R67oWEO9XvC2Tc60m2KHgGuzmZ6F7fpbA/fMCd2BaRV6eUAa9qa0zNo6Ga48OwnCe2TiE7gOO41WC3/G76Ohey1LKgHAqS8X4
/o1m2NE5eZwQkOC78xi/GID3Mq9+lWttSuPjOCDXWtqff82cCD26HfYSojuw1/h1sBMElHG1y6LPuhXO627+5fXv3rw7Nhv24Kd1NkG+a0ZWf/o0
uG+gB77hh3sft4fk38G5CdHSKWVEv8W++mwjjOXVWexr7KstuLdEH6zXwr7I5l904/fXV1ugvKlwHjmP9CgL9s65WhswZw2sIeFu6M0gyJev7Ejr
M0KMGWIssLsC25t2tc8AcfdA3CB6B+6/iKMYblfGeIFSA9vjvsKfMgbbsxn2rh5jFRK88p6wkPBMa9Og3JjHjLAri2GG3Gjwwh7QsnMk7Osffrmy
AGj/OH7LDm0P8x2CsvSwU59wqiRXt8oxJx7vExsNQJvEm5IbA3EmGjddhph+XsDCRHKEDkeHwyLSY4fNov/GvdFWJxMnfF+TYtGfcrcVUc/iWmCD
0qWFuC/Zh5E18O5sRNmhdB5sjh0gu1tPL8frWbAnDFzvaT39TyUuH3x5bw/F7LPqDxVagdPL5tanBehu3W/w0ZebBnnJlc7scAWjWNw5HcdlTdOg
jXwv6gbKAxa639aVNR4H9P10lF7DOwJCPS3xoVzri3Q38iVN6RAaDqEFkPMShO+E8GzIBW8eX4E9S17MhPNUNVc1zzUMwm7YWROo60o8XI+Ac14A
uOMKgauRcB7uscMeA4a6Q4HU+ltqSOg0k4b2kO6wM6Q70yRTTl36ILuDUnqoG8o+C9wNbzqHNgOPwB6eOvjvCuE1QCODIZwE4WeBXzIgbILwYqhp
CIRBWoUb4QzcVQ/UG3o+ytHSD3C9lPWfX83TpH4H1zPhLtgFOeTOtU65A871SMlWkwt2Voa9XAOYF/LQtAxWWwh2IQ5NgfuvwjlTGV3IA/wSgt5Y
YZfl0HAqAUKw76IEEjAk5rH/hgC8FkqnvHb5GsbAjhKhRJrz8vdwH/DN5Qt4dVT5rwK/2adyNx3FkUptavqbC0kW3fXFSGXL5cW4C1VhexHuLp/A
cjclQ8pa2P0M5Ptvnlc5KhV3Nnb4EpCCbBvZf1sQFwhsL1ZSUlLgNyi18/++ANcJhMk3SE0AvlCkF+WR26Geodh+4HOR9tKYN4LAntCXR8E1aJLu
EFzT1oylubpDjWbT6/i1pAHvp3Enm4Cmui/gTh1xsI9IhtLjhaQB9pIIb7bo22DPDpLqPiWQeuNCGjcUOKwF79DXHaR0fvkQaC/YD7a7HupNcYbE
BU1y9he0nAU6SneQshB2YL4EFHeGlc9op9vB6E74HcWJ0ZqwFsIpjNaEFyBshPMqyDsqSkl4PUAtCejpx25GT93p0HId1aiX4f+ZwHv15Eq3RQ97
6cVMtDVI7lODSL1hIY2dDn1YAvu2wY7zvCft0Ado6Y9vQp0h4PuL9L+JXG2ZRchr7H+sgES7RveyFg75+7P9ck1UgK7zG/D8hk9ntpWtwN3njvoz
2C7twJP62lS27z39KkBwVNmzVsPXALijId/TM579J5ca8hrs+fFGatk78F9fSvD/wPzbItwBGsO/x7AfdxOfnsR0Nyk9Ajtv0/2w4P/BlD1ZZouG
cVdSFtvzgyPiKX/ATPiOGkV23Erjbrp5BrFPqC4npeXlFcQDXxiRilL7g3fjZhqEHelWGqTCUzARvmGaXA2Xdk+1mTiKi8wTJ8DtpcVVEFlQWuCs
ZmXdTcu6G8sqfGC02Vz4QBY9ZNNDDuzMUVVkNttdFXZ6cJjLyieZaZX0EyjanLvUbT8qYBMccz58aeapqjY/UFyFX0k54KspQj9uqrI76H+kwQh6
I3obfH/p/R/8yOu/ADrDxew=
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
eNqVVF2IG1UUvjOZ3JndZGeyP4mzYLI3SXXH5ME4Iq4Dmy1ijW3RQItWKLjPgmh90WRNd/Pi6yr47IMPxacyVdCAPthuUDYNgaZhS9N9kAgJFI3s
NnYt5nDXc2e2xQdBnJB7zj333HO+83dHwzee2Tusv03+51c/qXj07MtvksP/1q4oHTNJHqQIpGRIEpJSIBUB154Bew7sBbCjYMfBTkDSBBr8MB0B
m4Ktgq2BrYNtgD0L+ag9Aa3PZXpMf9DakOkTOhFkUY8iyV+yJ6GjjVt7skOhZv3Zui21zsj8am6tgLRY4otssjw4fiCMmL9wbcngoVyon9Tg4/dy
0rH3e2ikxC2WKQ/2rK3yQI1JXLJmYjKXrXBM4UGLxjRO2ZfOLHyNaOpdEjvOI0xtltlvYhPh2p0u4aGbXVIeLLDbKONXLYNfs57lW9bzLgZU3xaY
PDytewHLbG3KpRqbRgtT5cGKpaHpA+bbRp3VGDE1QfF/bpRRYB6zNsa4kG1Wtrqk8s31LvlAhMvuYhFdP1OYofoNIvKgQ23bMfBUy0vi4HH5YXba
4oztuyilmhOBokjkhDPtM5PODBTryFi6hHtdFktQLFQshGqeuqeKS+tGgEZ8TYK3+jsZAsPzMlz8nhmV71jIA/hru4fRr6dXKxyY/KTohI/avcZo
V6n9VZVLHaXcCY797Se4peWOOm5QVV8RXjS/0o880qp+KBxvykqJf8ruIVCh8G9o/wkOl8aPO31nDjPwjouN57xEOL15OdDqByhZO6gW0SLKftIK
+s/Itr4K3LkcSCglFLyG+3Sc/bFuM0iv20lw4hhVmEqIcFPG/CaAklM+G4VRJgzj4XmGJYuB+YoTRY8vHgljUBueaVaY7aKi7w2bPhH0PAhX6MVJ
4IVpF416blR0Q/C4177W2EmeIM4CHqvTlMwvM1hPfyt+2Wy2fUtqUKL/INxdR/j9wNrTXxTrXkwxqbbdTC2zcQMTIMLOnVwt1bA1JaYi5DiYL5Q+
W3ru3EBluTWcjix/KrdoGMYyYvMHxAtizjVnPSZ0ZH2wYsoHUq/duN8XtTut5Bc7ijMBnSBGm06Fweu0iNeyVhCLv6RksY17++Phq/edSeCXrKld
kq92wiP/HcIC7ZKCo+KtqRI/ZBuIToV6LugiQYH1LkKeENOE7W5e4DJ7LCMDtpP/qoghwBsUzNd5wAsNtU7h3IZxuAYbBRfHy3yLK4wKTTPHVRZy
8QFCxTkwk7dUK86DuflHEgONX0g/bFoZjnobS5itDAIqfoWLmCZjYFwpeKMlN/ccDX6v4st1pRPGiu0PT/wNVMkJKA==
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
{Wp48S^xk9=GL@E0stWa8~^|S5YJf5<0(k*{#^hA00&P`litt|u0>6aMXlltnP+VOH$8`p*lVn1jF245sZ|NPs}*M}iI5lXZrvnu
r6Q(<j(+7_g*nAL(5efGR#QJX&ULC-GmF2ltq)fejRGX4Qw*2PnGiU}J%`RtqMk;6xsEYsQU!)gSEgetPO`;HwcoE-Kp-rPl6pAB
exj62NNV|F$4P|>6qxPhP^vl<q5_2bkPebC`aTvs8^s(jQ0#MgQXgmmsQxJC4BnHVvrrbnc%6O72<X<e)IReXW#F7E3dO=8DEnxB
EU^oe`aB**n@gu^^|-*A<P2=yILwN>-wVP&p?1lI=@;p>=rI377BvU|GwoF%fY}CXE7=rTAQg)eocmZnj=RG3xQ&$+XIzWz``h2Q
wn<t@Lqy>faV{FMY5K0x=o^x0w4*8LpgKEw44GXxjNxWMzh6V-(6c?p$UERPU*B(Ql~Xr*_eg0huQ&bmj!4XEMb&@Y>IjGPUgzVv
!RJT?JiHqo4|tIRkKb<<!@!_p6w17^mTT5Y?Wr3QiVg6zxsKq_w-1<W2#HFr2b^PNlBnzi)<_f0Qy@oxH@p(ImCfY_vtSA_P-4#y
>aBrd(m@wwY%(h@%2w*usH+xWZm`_IRF;*&bF(xn&F$0MU)qxj+d*Q6doof90qjEj3*h%n@Ex(V2R~dT779B=Qmt9(9!XfhLC42g
ZP9@+{cH<Q_ZSvR!gU7;8C~4$n+?DTv?Z^Xc1e50$@!R28BKUO`586nA0;{Tw=r1y0Ws;ECcAa@ry?t9O9{Rfp89tIZgYQYXTWob
s3#;KjtU84MXBgYn9_5G9e$nI+^fN87d#NnP`k@k<p&+6qNQZd-%F&dsuX~L{}1yA6*{z?srLy|9H=+&UFOf+ElBXx1WVc<nOg$(
NejPLe!spwBZ3x#kcMF^Wf8lOm#ZOF7}G2E$x8=p2uExVHfBh%_BoA*O!)FR5aP7B0=0v6i4w<-djKKJz7H0W{}%BzhRB90N|qr>
mx+gQqAWw2D5c82>ScaOf1zO*%_P)o$!!uf6Ta;h1p49Ed*C#2%Q^!%eUfx-q3O0WE&s93DbnC^boymjV42m6t%_0^i$o~nuRs|Z
dWK}^I%j)~GArHypK)&nNF<rswMoAkFv3bVr1oHV#B9f{ef+i9Z=l(Ik;gjRwLK329c&KUBvYHc!v`e+MwJH+e(C9S7og7jLVh;q
hdf*J=Fan<>l|u8B#InLs9^?%3smQ7{{q#ac{xy}d6nu8;KqW(+Rg|p4qg*ArtOI{)~2)kv-<RZSxRc&IKO$e6u^sa1>5}5sAoV<
KR_oz^iP*M_DS*_2hIEr@V)+XtIEJ0@Se$aoaW28Vemu*D4fMidNy(n?F+A80f=t+G;XdaWo-Vk4p9gB)l!)$3$wo?fFmqi^hh_2
6>M9o;p|3=5euP4-2<Z$um$y&%XqFa7z9!;?7m|Wl7ojm7G5|9?>WlDN`>grWwNwiwq`=qSjH04HAFag*PG&d-&;hu=&Q5X!l67o
rg`-)Py6_8EwRoj(7k1by8FBO(xP}Y9tGEmG*@9}jc;w}4OJ>`Zuh7>Wtj$3DJ2bv1m0jWv(T50ThY$J8Zib<sauo+PfN=kE)v`F
St1fF-+JbaDqaDZVSH%C)jBP7D>nmlP1ukcWZ)*=#e)dWj70Cuh^kH?!gtYc_Nn^j$h9%4a$*qsf?B?=N|&)CggPLL->Q9^A(K3L
(vP`q>T#GwHBhHrI%VyIH0WCm)wA)y8_S9B$hMD%gd4=$;s%r>Mn25+h~UCJ)REozsi7k3CTVM%<IhVPWt8)YS&2Z}b|F4G%>Wtr
I6q>HpMz@sj49{$v+vSzmgo{3JKy|(L^#dFRtN<g=a<>nl;oi0_<W{8hWuuSUzKw^Noq|mJ!2f~jBLShnY6826-yqR5w(8jxaN5R
)Iw+5OeSCJl4N;Av2cq<){A&uG1%&f1rGnW!TP!fT8k?gPfbvj?JSrt=bj32P?jA->tyN@s9AMYC#&W+DET&DUxQ8@A#hn3F@;8q
5!(WohghLg0*ETYzu96T{I*a6z!zkh1NWofHHv@+!M2A+Ro9<DlUwscI0h-_Pq5s*S+1+O&xz!@uSJh@?Z6C_Ad(tzG-iJ!gnF`*
758{iCUPv=HQuDCX%D?}ASnS<RdmN>kEC|t8?QK^(~w4DbA|m;qaX<~;vN}0@raNXPPXh=_}^NTtY0bYvj*P5Efd9!0vbO%d_&%k
O8Su(XTrG>8-r3_jsaf+oR`T9<u+vd(oe5hG%>Hp<)%_x$2GnRn*R4lymLl?X=?3jYdojX5puIZqtf_1#w1WML;LKjP%MIu4+o&J
BZgNiW2#^=6nD>$mdOuOA;|ytI;hP@rPu4$rq7KS+7U*^=sYn~05Mk_{q*g{S(Bxo3-V$EqAh%LcjqOXxQIKuxXu|sZfjFTisv2=
AYu<3aDH?Q#W1OWhrb?0{$XIj+d!lYlnHB-P;JY)n?#2iO;cyiLjG7(0?J7IL$(sEQP++4(p>t8`K1%tkO0uhIG$yNPy5}7k|Zwm
_@kii^61~20KnKnTbIc245C7AU@k69%MSlBJ|DmHX`R}Ol^T#Hu5eLSQ#KAGU85Eh!ARwR9b1XmxvVRhFyl-Te%$Lk&!5H`6UEoM
p5@J)=LbmT&*peG^a#eXIi~F9e+#W*vJr|U$uv_FLh>H(G_qRp(e%p1TsYZV0?D!@UMNH|+)@~Q{5pvNE4Hw4XfXiFNIm+k*xT-~
*xFx+TU4^^vim+;T5*U3^<mar(p2WQ52h()7D#p{evClf#|)b?D2Si7sJNfdW}%TuTMAXLq1hP_5=kP_N-l{Lp02$QNd7kHU<U8f
TIB>16Dy=JUJw2lL=*TZ#Y}f^(e%+Z+QYh5vr3D!o30~|dN|bz=SZxwlW^0;4z$P*55d}e(Jhod{>)7{-QOy*GLGE*|Dx<g%KurV
^ei0>x5-i^qT)hIdQP<cPe9_}net{o>6W|L*%Q`|grGTk2NL^ftQ`<wYPtI_t;2=St=U70?0V2QJb5eMQQ>9%7Z|>xnww$97-1U`
^HM;?d_ugKSU2OlD{O+Ux4>PQ3)({N2uJnlVyDbZ6&bS2nfs_vZ=(4N&UUcHh-Vew&*{l@8)S?dId;jAfizZebxn+W9d)s~0mK^t
Fhb#tY_23CiPu}1Gx#XA1R2Jf@c521X7v45pWG1KHSpg{xicN%Pd9`>GbKWas=|m}AsWA9ZL8}o;Tg=du)H9Au&6G-7d7TLoP(8<
y$BZ9Q=jp*N=Q1oz?(i6GRe71>Re%$Yt*<G2e3l-fBx;5tJZXjAiuIF*=v!AP?14`7Sg3cvdJqX-ZHzgu9enwOPf5cKl;j!Ic<<d
wrN<~J(iEqwUnSRa?SPWp~k#Ll{YN5Pn<+IQebo@_&65I{Eg2p;5|JQUNJes7t4yvOo`Nuu{JwuQ3Kq)&v}%7gArY6806m_SKG70
(zI0PUxJ)`QaAWcks!249t$R8Nh5Jva@SK&P#wUwR)83%{q-p1@M`xwL48sW>JzTW)7wGEjyLT3$UcLU7z`dr#wO-{1VO68*)8Br
(qmoE#TIra9s6R_hRWNn#?p|52B>hD#G2r<Ap=+qpLx8@YI8L^K%Nl!s06v9@U%zh6R4((cZtNUBGyDi%I~Q6_27xo!N0@u2gW$3
Y5+EAtPlSCWKJ)DfdYT<`k<_xCdOxDfI++9gE$dait&G$wM`6(k$w~H4Y7F4_CP_|2zfTS(e9z8TrLeyfZzRHzf50i8?Is6FA(~@
<1r8cOjK#6@{|DU<`a>=sYehm>g=RH5@dK<$QtdQKzurCmea@bqr(_QGIKe%tdO`zU4p{<<b4d&K!P%~?_rAd7$dC@d1({AzPDOT
N`=@-;E14@MT~ygvKv6MJrTnn6)WvBnh+RXK>{Z+v8JS%?an^3#Uueg?7^k-`EE6)#IHq>PV@gEBTAz5;%q_lf-~h;rRM%ruZ;R3
uk2j{066%0ir^nFN)2Tah;#+Jy9%E{fq@;aFF7d7^><?3w{GV7!J6E*kNF)VqGZpVKSHdEN~C?5GOWxQ2?G@B^Z){lXhVtF92DG7
h!sN&XEA)7Bqv`oXg*LL=V+P!1{#O!slo!zNS*rp#i!L;mj-JAY9IM~rDuoWJEV$Sz^feZ7X>r}wNjdr9aguOtv{6DG%u=xD;(jI
zr{DMtNXVFtZ$Os7L?Gg#{?s;9{r1@a<XiwEWzSV1R}ioIFsSxm5jFg3pV(6K?&aEGEdd)f#dH|9xmTwRzCedYzJ0TQyt0Z4rBGu
7|UzWx-hjn!__G-z>-@qZc{VC9|jOb`Z`m>{ts$okuHBLXXw+QH$^aMlJyayboTA`LdvD)PQ<gscW^REhUc7ixtRSql<`cW(ZHNb
Ec0QG!raEb4j0<saQp2@mk1O3H%iCCFbbi_S8dZmnZ5orb00UO?W*BQyU?g&H=Ib_H-;y+GN^E3j@P|1)Pe#lhn@A$f%BGs7+jKh
#ukk25Ou2z+d{8>L0kh8KT6VWYFHsas%``7`{kNASUYN~<;*((s{NVtWS*PTXlUi0FL;NKJa)V{Gp2yR!FQraee_RU6q00^n5Zkj
{U@9-SFph5Zt*3{^`azX!F0zrR>y#Olfz9`9>HuvU5pLUcFlA~EJ%0kdw@XM8bswRP?x-QJ8!fNujtTpJ}5n&-Zk;u$_mD%FrNdZ
Z=I%!tZGTdE3&}*C=2;H_Q%<^VI`OKF^C{Lj4|Yq`~zDsz<nNbi8Of!<zc5Z5w{CZ4SM%S8Zk?SZ6V<qH-=3E#B3n7uuk_3;aT#R
NSZk4zf{~yX(3ZwQx9P_=uPg}k6#VRV-I#GImj$MAzC`ygtkR%P?z%VVJTcl=kkO9qQidm`-6okKbR0>4_NY>G6*cyEpSmvGIEYu
)5`<-TSAA(wE=ChXU8s4*|bs!hZ&&Q7gLr0J$<EsbzGF%{Qi%o^}@MpegG`WHdT?9=*6W^pL=Pqw`!(Nw{Z4U*J<0>usw_QIhv78
zob6>xb9i7s`+aR6~i9BLYOGmF?hpxqXTKe?rG+TZhe}^;D)C}wt^P8m8W4c#oz2@B!Maop6!Glhe?&TfoebDi=3geyS5b^l)?f5
eiUOsjL}xcerBk`Z^aawZce?vwMj27B!QWfAV0pv)4GTVSL9n0K}QyTI8kUxp0bcK1q$CF5iy$n0_KD~>F<0Ebi--<IKuK>k&yW`
FXx{I%a~C^0q>DlD*21IhZ6o|coSR;%u&RyZ(Ohzb=Sl`hlEl89*STJS)uzU?6bj(fURm0urVrBua9qKQNgnz3bo?BjW7cGQ;_FV
2ET`ggh5F<)dc&I+WSks|5E*)a}S9tD@7{uV`xgkohzb3Lsquqe~O;!;NKoc>K5#{P2Ww$o>WkuE9Rfg5My}TSCo8g)k6%MZ>puI
ASD?u4rhy;%PMA&L2;8aF-nF|Fi-#Yxlebff%U4WlJSUCW7JPz)E%>UBSjFb-Vq!;(OkWG)9IW2YbfhSKaZucaW#Fhn7%U~9VU^+
`qA=lC&KqXU?*K`>YSIh|0EVT)To~N;u92a<a~ZP<S?D9_F-ZF9B_KT#(Lsw>ne1Y>(f6t5Qd-xcX2TwvKO~Sa4O5P2S0{;k-(qX
tiO@PcbfHkvNV8KQEJ`Eo^)AxgufJR)0G}Zf_eSC#9q2abIEBz5PJ5vfJlikb+8B<En8rbCbyl*HS$2kcN&JXy-7dwN!efzFi6Wc
sJ%#8l_K80E6xs}!MnU5k&m&$=ZWK&W~R*T<?Peu154VfOU4lM(lv=18(*MJW`#_+$BI|vMbzwCLD6n9c{CAKGCT6T;_hFn*X{}m
PV908)Yit6uO_B$bDze?J(#GJNtxW4nOyO%g5LBmiFI+-+{q}^Z!OTmEnT`)_CRfzK7CZ~X@%WXzh(;}FQAcbw}QmGiTQEhC}r1<
z$)8FdpUO_8M}QCP|N4siEDpEQ4&Pm-ASe25bcIy(UwhH=w(UhiT*t9-%LDG))e7f!Z%>~dh4uf5E3R{nK1twkXH(dlN8R-_q`7w
ZeXg81U}TNN)5^+iScBU`&VB%g8xs8K+nDJEsVr};2U=!?SIzcz~p*R3qSn>dGw9+Ck38nn*c2yqPPM%+F%N_Y__4HSGDjv<fhP!
WV8kD5OGN(Z=~;zj1bYqwXAkvrFH8cs1A1Him52DMnSPjA<wG3Nbgk_HxdYdsQGHgkpauSPasH(>1HaFiS7(%*l#q!AoYRmT8x(L
IaCpWxO}t*(iNt4XvTkqI5-4uT=GFxN-3>8_(p9J0=Kn@=3f0|jgiX?2N_wQoF0)@SV0l7R&s_8H5gA+xahXyBk@`p0iTR*!(qxv
;j3<@7Q_5V+lI4Ze{@5oA(Z|cqo$_P-3CiZ9i_xR(LU3}(Z<Zxi{2*8(UBKGG{^yT6CB0Havg#9L)L};d^IECe<|l=AQ_}1Ci)XI
M0E1`L_=CUyb8w#gYl8lnX?P|_W>J+E7dt)P8CSNDXm*dxSWVl(tKl&aq7pXQR!+>f+4#6P5P7e|2m`_E1}=}<L?XYOuhGjjT>X_
>Y5<=d)?jY_SV238q^^_goQy3YRh^diIiEPfFJ~gU>Cn!1{q{a*yz8>O1{HBcupJE)KON5hh-VHTPO@$Ujej#qB3q-l7yAg2Xwjy
ns(>%)In$g7xSuEYVwk?WXfdy#k{&F#ktbgKHj2ZE=|JfdqENJ#1VJn@nXdUvVffeilO=sRku!>EKb!_KX+vVg`*t!e8!BWq%8EP
qD>xu^uS|utmU^?Cf4~RP?$df4<PK2I#a!zdJa`t4%=;awJx?<5rk9^vRDnEvHI=t0Gay}#s#3Zb8ejNp1mAu8OC?ag7IT!Xeviy
gwf5j2Z;u_B?NQ6f(C+q)HDQY0(J(4VmCBs9>6XKZ6^ZsRS2u>GB&t4kP0~^OduV*I-*N|nuUQEY&>(2#-n7DKi(2FBJJZGj5HV3
4_XHaD_4U9-iC_~ke$?mPg~D3b_YS&U~$nO@6vCBv(8*$gc%b{o}SxAD;8y%iy5#PYWX;+xh%N(Pc;C#GPk#uDPrOQ5q^$$+wGP{
SvHhA)*xI6n<8g4>Ui2HDRA9A;RbCNS_st#K!U>^62E1-TuAhq@3&K*f~FCO+OTd}vj&xqr*)oFcI3?^8`c@i!mc+4CvNp%947=G
47VA3@Rs;KF!~#VMxs~vp=sPd1u_*fJrj{uT2fG!u&N`wAd8-7i4}iSd}ZP5YSu574}yU9{sNKoEn2}>FJMhYyr%H?BzlLc85<v;
vSKJ030zxNxzU2v0u6lwkA-l20u$|D0fWwT0ze6=n*WKmi9p{ydw3s5;9T>FwrH8@RsyucM^VW+N&N?_=HYm0JJVWNUFImct~4$R
m1UQMfdo<xTLb7Y3|5>jM)(RKq{NwNTgrjNxEttC__9dqg+~qN0Tkc&_`@#Fa}TU&{@xzYx(Q5!g>#P2B7TdI)A}h_Y8Z9HyWYCP
9_b#>J;(5Y>zpecF5OgCgYW^r9HUHxmH1+r14}9K@hgYh{f98DW)e#FAtd%)?UY|bsN*`?)_$779><4vQj}Jbxv-PO>;V*zFcUno
`0&Jq&SQ^mAlU%PCceQVCCh}7a8BO{^|p+KqRbQ2(FJrWoG`UEP&IQh_a^J-p5;J>AYoK)Z0HO;z78h-f<IfPSp3MQm1d??GU1Jq
Jzq5S#mBi2jn6IwLxA;m7(WX^u*&2>e{mna39V?*s`z+%Zd_-k&CC(%5e1H0qkDX1SI4rUQ67Z9a1G=^wVbHZ4JsulC7?urDMdiE
Q6Mq~AhX!dl&IQ;RSO)V6cfcYrlvxaNHh|DznR8hy-52A8ShPw0~u#9e&)0T`nxn(Dxgu-eI@vt(@s#Gul-Ql-<87+QMh(|c7->u
s1y4vt9VH4EFf0#Vus;O{BmrcxDK%^#HdLYj%*GIJA;V<R}L2>cL;)8&DW0RgNjz0mzEzrMcLL;)Pi5Biv0=gK*FGTrH2+^e|e|A
4TtsjXnUp5Oq?D0Eseb8BCr`0%ufx+TnOI)G6ONl#k9pB+BU2t1D*pAy7v>mv(k}^;N`FnO)iq=mvt{QMR7--Ihl-OVZEt2y7jG7
1<^=M3c5*`kxN!igL00}y)zT6Um6po-%D5aDQWs3n2RLR|HMtz`I6C~`WFFncz^}^E`JI6XC&pNTK)-;xf#aNIv?G|5$bN|dQUG~
1t8ES2ox<)SHWb#y0SgHi97T$T1Ql8nN!zXZoSakF72^qZ%QGEID+m{sHSi*P(oWH`5(&x!bAu$*vW0^LAjo~_xX#^GhFy-!7Gq}
({h5lK$j_02T6k@Je(tuRO*0qs7P4E?i1V55f{()M3eFp2)Y<Uvr5UO$zG#1!;`&ttct)<wAp$w8|la-*L^GO?u{xu;Db}t-I?l-
k3#bUGDeTJ-h6}X5XZ?$rw(jrKCR`KCVaj?yln+Yk6SCIicCy0?Y^b#iT1KYtH9aiS1ZFrqxpu03td<uZ`zL|t?xPwu)~WB><N6W
=q~)$doQkE25HAItJd9SbC|{sQpB3GSQ5cx#$01A!|)Q#+1{l`5DJHcX_JJG6SzpWW;wgv4-@6Ey;ec_kI-l5VaXPhnA76(+L!H*
ROs7$KOO#QZ^Z5hp>#V|y4M5i<1H~))=nUx7eIrt`qHVjxz|EPq?G6$^-!jLN{wFdhqHC^RDaO;aMz5SLP!+s*BeYk!jh7=h^tZ-
>E_d{O*1~m7(=)X+<TzVJY#qrYpDC_C#C_xGJ+;|`-^|h55-V5Tlto+yT9e_HK@}sJ!AXOJTCjC-zUMH6fY1dHS0}&Z2=?csAfKZ
`n7xgJn-V0&$=pas7zSf(dwP$GU_E`jj36K36;$s;|<aQi7im<IKkgm1E50A+|}NxbTS8oWP7&uuD}sSw>O;C|IGlTGQBq%LeozR
d$v9#J?d<5xzi;Z(bh4q@RF;M5wc#HuuL?ePx2c0E!?o~s3}P<)iT@YL|G@~1qR(<=|VcERb}zt-WCHur$srt%V=JKTEl$T`~X97
-0Bl)VGYSoD#!n~KIa{Q9z8yTx|n-{9FzOZ_~(dhXo{ZO7xB6j_5j%dv~VK6SBUYqGKaOymyUTBO+{Fs=(PMH$Chn-{hoX-n%(MO
#+cOmGtUVNw9c~<V+6sloCJ(F9jk>9N6EBV6$`4h;ei(I%_~u}E!po0p=XGEgZ&vZNU$j@7YGN^M~>$3?>o?oxjs)tT(<K<yZ)(o
ybkAZ$I~}cT8#)sS%kS%n;Q};=NI@&`vJ3343y^Aiag@H)mire3ZOmFh)mgU^O(C7(=%4AF_LK@#(Dm3I!yMGNTD{3w2YlrVT}QT
?-mk9)C(F##15ixlmDoTT|yOx$33`Yo*|uq>Q9S(f2nUZy%&JK3H3@)Vfm?<FNpDs^DQ(O#$@^QgW|7_QIKpbav0+=b~W1js+9K;
sQ5o4H9My;=O<DcXt`){jVmZ(XBg4l(rcJ`-ZSChs={sCX5+5YZY$smYw`sYO{aAB#!H_G1&l|!_8TZ0h+WMJI)g~C!ze-a(PeCd
3U#A`Fn^GUu=>_YkYIuD|FYX!M7mo3{8QNT$l!V|+A6kx@Ff#)hg|-YXKrL(Za*P`LS(!L1r;Al=I#~sZP@ib@BUfk{zq1TU<=#Z
)sh;I9<m~rOr_21o-IP}ool{V%))n{GQ5VKbSnDtQDU!KboC@Kg`}3j>^(4LI)x5puUtS8Brd*RHCXiD+YT_S5CXJPRk@N=Z^fmI
GL$04=#NajyhCl_ch}99l}}>DPu!~OufK^D(1jvQ$X4@iDJu(-1|I<*O&R(YN$Bfrkx&QuS^6~DJvS7PRn(>0TAuxNN;IyjwbD7T
Y!9!DO#7%3H-_e??Vm>VflZwAiTv?E7jhH$RNE^VV!zhi*O1J`P*2GwQ<`dkaf3^dHx^J}F&ksWZX5;!>%R`QTsJ5Q=)rev0>z&S
$(9o>{OUGoj6pKt<AH~ese<Luv@z`!8m=j=gY<FTFphFl9!b}!+-Dk+m2CIpj)8<VcXFz!EUJgLRd4Sf0w5X-LZ<YN4O|nXi*K~h
ZPag?zo{}Of+%QJzILQix;*P|fxf}69lh=um0!rkaj34)=YO0xh77WD?ng|!rGj8%<8Ioy)uT6~Bk)F{*YYmJLHWJLyH5j9-0E2w
wFvl5hDBSI7f2g32<N5r{R~+Geg37UGKpF`0uI8{%V~DIPZ#Qo$GK>|k%+FUJc#;qkd<E$kBR(LWl<i;^!wU?McSL2HmwqbAqmp;
>$|k@)nmsplxdvd06mVWmh8qmNOxb?YG!YD{ns|CZfKNL)%U!aKJBYXKw)ab`*sK(%Ayh|^6*)}+SygqC{gD5nhT`UA7(BQ*tO8_
_4f*07LS89sq<}frIbQCumo!^mIacX>em9eQ+s%@{jz{Y8T>C;+7GiAUc+nqk2&2*L0``I-+1|4GgjWp^z!QKnRV}j9?Viz_UF&+
T`h`OJrN}nS%JZnlfK9z3Aa|7O0fhXm~+`s2XA^W(^w9z16E19B^gw|0N!AjH>frTPh<xHf<J%6F2h);er4)Cuho7E8AX5B(=7Ij
SJcb5tZn7W?nK6m|M`0j`ZfQs%OfJlqD#_t6js=BIxXGDDbQpGOJ`Bjs!&1AYWscjPZ~&~AGyn^8#rC0-QC#3<t9}{$u+<wjaZw?
chiE*_BH+-j`y2m_cx5NuX&W#Q0P%eItB>E6*mE2vQXqeR1-#tN<o!&%=nu;9r?(PO-|WyUuRx?L1?u@i%sqh7cW1$5pEjOcQ7G4
DF8_bNnRT8Hd=AEAZNR{L(4O1=lX2~kbhQggXlUQkCS!kBg_E--Qh`@qy99yp{Brda@Q>HTdrSkX{}vp6(~sK@+O>O&iXKi%$lps
^$V-{WstMOcFy*oLX=ASc0`;BijAWH8x{$8DUFgIND+wJk1^$YMBDsw`D~ORG-CG=wAx)=IvwSDIIwQ3)zKtZaN{Z0htDkR|5u)!
C=<P;uqm)H7CCXJRSEP#H776Tqi8^ML|i$pUCDYT!;6T5Z>}>@vu!jaK;s}o4HeX+XefV3U{)_XCuDdlsPWvOU?0XT?Hitpq%_hf
Jyq(nt_4mMi0;r=AAb>b2$EL(n&h!L+UybP2}<x|kgwjmEQaERZ!6JjQ}8WesSmD7lu6FY)dRfkJ9~kyy<L}iE(~mJH-QZv(4Y@~
JB=tdplXoOr*8us9yk>4U2=6-8H80%v0RnJ{>j?qKZxcg2|jpIBGQK27_kVxK&P}~(vpnq!A?A4((C|IvdY=|0XF4w1k{yd_=o)Z
3@`k)(;W_w8y2Alxlus}nn7VQeaCY4O`N!njv?0?tN!PPURy_@P(Z`^2-ob*_0)04lh$INc5?Xl;7J&zk8RH!P24bQFf`*j*U;}i
s{x1y;&B<{YzbtjOVuZZo39OiZVVwj?S+EH7Ml|$=q?0-nObET5hqnMBT=CM@}HFsLBU&gMq`D&KE2=?xF4rNw4Wm(W%`L|VLSUd
V(O0m-%}ypJ%BRJJQK0(_k2^hRSSTPH4>}>;4OP@C71aaT5{V_3TH(KXP-_J(e9rkEV+&o3)o0c&OrNeM34sOeB{6mT2l|Lu)Ic$
3L2#KujsV-HoNOdVGkL5gR9Ef1#O69&?->mYTd5%8qFz>fLwimFBPx@JNDnZDe33Ue-iW6TEBhyMsi!jvV&Tn4Ty8#NPtS{^$t|I
c#fHWnQbZhC|Sjt-pWj`{uQ|G2~e1jrSQ-?cAM0?6<a+|ma{}aXu_QXnXx7JJT#^n>))&mMOyj+ADS|uX!~G%?H6v(FnzvrFM5sN
-AXe%#QX~Ym(a&;FiwX<KkgIKP+2Swej8braD&pTJw^~_i{T%*^%!KB82(9qDe20H`V64rHQt20+`)(*0T_f7w1+)(03u`L9;cqT
K#@mgw+WKH^YisvxG373CM0guOsBL40bv5BVxThXB&kng<KPcZS;j^L;{r9jsXdG*BR?3ClLp;}`@y7XzI%HF24{UyGk${x*KSvo
>gUALNo7DrEk`#xuc4;jCNRxy70?!#KL*wIQAOt40%*<PG!1mc$SK@3BV!_2!ZNepJ1;O0D86*EM`m%-+21noVoB|7fV;4%lW2&&
H(_^OQwu!Yi}2L>TwwcjZ9%2HF$8?h%TH}RtaJOhq*Fv`9(|Zr_BIW9!POg=`FN_Oe63sRrm7A}`KZ|-^qeP{3KA);_va*i4ai_z
^d9FX6KRHB+-G^X6QoL;+aTja95)vR-gr(?F9s^a1V)P|1b&a{z|uW12=XMY=)9ssM-m&erExh)n8_lmkpU_EcCHp-_~M1YkYX7S
XU<Lti2GVb)%h?22rn;7$}4zK@H5dTCC2q_6Wm{_CIMP->RK|$m^*o?*8kp6jTjCjEvE$x+DokU3M#6$QtOo`jN#UhIV6?7qZBaF
N*`54S{>+w_5-ae;W#^!z!S=p^toEYaf4?Ihh(bEaMz6m5m8Fgo~-F{VXo0XYQbL5kj3{!P{y|{S57(Q@gra0lD}+R{*ZWM!u_%Q
;3_C4AGinJq&gqkx66x?p;8+iALc<eo>?DYcb=_rHZP*LsA*AR@`CIeckny35KQ8EEu|XSKUs%>3j?%EAbKcn4#CnCEAGB8lzT%z
X5|#b#qm}4d!SB{QTb2f3bFD^+rQTrN?9~DJ6$GW!H9O>T-gxNTOC0XG=VCK#!cOAyI^W2@c+TL5re^~UrF~+<wGeWJ_gl8G(?F3
%h^-hS>d%Z<^3H3-$DEhryEy8XBsa|w@ievs(?|1nhSzalEiKPA5Dey6L0!(0F?QmP<q~sq%$HAFpp8dK~=1nq-MnZV`kh35URT(
c;`!HqpWSMn9kq?Jn|+Vh9^P#XFaH&dGYlyf(R2kQT48j8FL7ITNPe7?1xGe8K#@KVowcri5$a|g4N}-(<8QTVUw$_N_1wV(#jru
t1^4jbHhPrlXUVcrHYeA{8L~y8Z9d3J#`yCvn>kY=4*F1)Ei^^`)*PSGu;g`xRa^=apFi2g<HJhr<UfAoK#UKB4!UOb#@_-w$HO$
ftQb%a9B+ev0^l11IEQGxqZg}o0K>qrUJ8*p9L(03lUams%?9+ZeSk{xSaXv#S>k%guzbY5zy|g01vclFxp@`=Bq>-;ZF+O$P0Y)
mrdd&f`f5MWhAgaMsOkTMX}fTLPRT`JsVvRL+_5_p>cpq^#k1u=0~FV<G&B8&YTF^y5S)(Il;A$A@r*?>HebA>SyD1y4ARfkAx^0
Y^(AYCrtFZ)TQcoEdAniYTS%2%Qed6*viZPrQVXV$F#JbvtqcRFWpzWHM``eqD-jjoxAAg>6KUIU`R`TUepANX<BnxKZh*gi~oZa
Ttq@y@Un(ngQ%BoU1A+#4pUI)zsREPTObvcuS84;Djc7+!d+siplYua^3-Jb&hH4#sNx?4Tdl!M%rx=B&T=g}1X3y%(dziPEi#Uh
pL<a-4AZCo(p+ti8hqa5s&)>L?<oE->4PZ_3Z^9msz+WaDevWsQZym_Ixwtd;bGf{b{fIt-2-`-JV3s#Fo|~<DLv6xk`Z;lHw~n6
jmr*?0cOu{m1$-7DbND?0{Kol(;P6oDonT86JL8VQE{~EZy|Wq-rY4a^~z5gp75P7N~5F=Ds1SqCNCm1`DC-}_J3H|<uizBTx|wH
eV|FRx_!3uX(WIILk9pIs?t57X|Jn&G|wr9yr%GL5Jt=c`b5&tqa_<;7?kY8V9@}O2+s>%<EO46m!B80ie5}yHi~NBDdQ=yj@!1#
<C@oA{pN40GcbENh_9HcdwAW1X$y_$^L<PB>?_I{bqjdY{95tHh3@Dm<7GXo#WV=iI|wbv>nopYEb8xBB!|sOabJJuN%C1ZA9B6(
)vD03ZR=xA-$1>=qhP0LH^4<5JCAImJwQ>yEOLRuOD~VdYG{l)$PC9~TDNDScj#FNa%epXan*!~b%D!1k%iNMEr!KEMFi){Ggmd>
Kn8Xs*L>H;Gx1TmqNCN%1w5OjyYG-(z8YLM;&U^l)$iOoagDg-oy|PjmdUh_TSx0ny%CBRAP{~Q6{$i*P4@mSBqrUK_S+wlc_fqe
Uwm2nb0Z&1B8Wfq8cd-Wn6y)60alm)p~IB{6g3Q+ewxlk;~du{!A%GyGiHDO`Z^i_@O*!k(uw(l7;Xgi-x8QXf3C6HK?!`pkyR;5
UbNO&re@roEP&nxtJbUjjXlaClU;N=>P35fiTn4BY?9inT#TbK5m_ZbJAWecnVN3t)44jWljLdonh=TY8+$T*D__Rz^O)=nsUCr+
fpU0>$LZA)oy8gzIe%%-+GQ`SE;8TtA4?$w%Ewp2sopU`x>J`-!M6j%*#^jS=5!f?QiK~Pjk_$^#Rv&)wuc%Cr87gkh`t3bZ%<2N
lFj)IfA0f`4pHT>V%Y->N~Set`llB0d$l&lw(}hz;{PBn)8)kyvL-sGWLC2g(Xj3!>NdR;p`#j{^z*v>7IKm)BQd~`Tam3Lsq=Qp
WM4Am^3yF``wL<@qt5z)Kwg_5SF7T}ef|$v>^e^4l4H8lPr^=-{i1RlcfWwzA;A!}!H7YZFspO9nh7G9%q}W(!8pol49Vl3^Th+V
@>7a2U^n=cWbhSEgNcKq3!l{G<76oTRWCOy>ay@<RdW7t^5Di)@hbk0aaVau>d-D@D5+t1Wi<+|!T!2J=h4C0!+aIG<859eiCwlZ
h1t<$ArZ)geW?TR-7&!*4_RyEfT5B5X$}vab#JJt^;gHf6&9Z0KG`SOHRq{p$GLl_^oA|`@K#v8ufN*rUIiD;Bv!AJQ9t`bRL}J}
5`TDpR9t5pbodZ8*+E`ieQz5d%H(M3k8KL14~x`YI?E@i!t&}Y`)khJ0s4QC(rnZn%hw-RV;f7F=_@X=Q``6|R?ePLo&JVC8yc;{
9?nOY04|551@DB|Bny`E!q;m~BNv`%|A=o#(TA3lA9W|`M_|Y_zv5xy)eZjB!rKO>!xjGGi4?jxVB7TRm6&t33~cp>^V&tF+iXZv
0$`~Ry}*~D2W={yMB>kg5JiVd3+%V>pk{E#GY*14ndTmkIh(0B2F`{=9Du7Pt!(kjpnXL%*q{d5FGEKu;Qh&J#|ZpqmyPG#*+Q#T
p@oQ}ZeG|Zn7R-Z-u(U&AW@f2zlTFmali}x{snzg)sfaXPx=ZVqGaNXU*}VS6pAxBV%Uq-(&IMNh}^zMhW07;XWO$XR^$tE6uh4K
@=n}fU`m8PRY$(#ghA(geri0`sG{sgcY*OUz|~KVNl%t9qWf%icZ(%cWOlyXNaf1m&J=Wy$(eO7FzofVZ?>7r#pEzN-HiEMO86Rb
2F#*HGc=^jM^>4Xr!1YPP+XHFMC=g{)~<ZqvN3$WUVqgQ&O-y?FPifD<tN568EkgnDR$ThD?(fcz4uT+jVwjuO%Po+P}+K9v|fIf
+Lx^&{HuEROmesT+~4TWNhL7M6xf?>0-tUUgxXXtVj-j`PZl40B1fxyG#4&6KkI8}I*cV!GG}5v^hkt!5oKBE#ei<)l)Jvx;u}lI
(jQbFmfaO^z7)e)HVpg5)3;V*ie)XnrRG}Ff(J$LWo!YaNas=qFl7?3PA>@Dnk;zD+@W6opIlX??bA}(kk^YRiI->1q@41VB{*Mi
3n7FwWjN|fd7;56GSRDrjAF=^4CCZBaK|)C*cP6`rO2$MpB!jJA5v9EupclKcw_(~LZR_qqpP7fd&`@)>>Dd0xN7)~E1`m#*K0fP
zd>=Pms_ISzN2ntr;@c6iW?y^h#k(O{=52%YwNW`CGwSe<j!D$YF5FERIyZURcnLjaSbtWz#Ha+HqPU0c1-2pm7iEJQ1}3Go%=J^
&0bW@(})1D5bjK#254jIvhdL$OmsQ=N8IL|S9N_y^`%V3j5c*yt6Z29ww&ylG#E^d<Q{xt&8f?@?t#%I19tb`0{M{iQClXr$5YJ%
-`M$jx*B)RYy2JAr`+x?P}jR?^dH9jdjCzAd-p0@2+hVCoi6iTi6<lOUF39@BpRmJ2&kA^!VipAiRFhQE_Vz(SI3ls5>cwYGNRrc
xt36e0qc>Ffoyj9z-q=Jv?SpsTHOQXRclc!Q0_b$OfpAXGQwS8)q}=eE5i>Chbh*PReO?WOhFczhR4EtHwu6-2jI|t$+j*>7Q3+f
XE$M#1iYRO(BKc109Wa|rxr65Vj;p!*C_V6(4rcl#tuE%jkF!^j86lUV{!WCk+C`p2t_-uao1=ETyr>wk^_r4fG77pl)0Q|jA07%
){b~E&z3aIpM#dyvj?%2LD4t2b2c(*pW8N|J$01tA9Jih$J5N4-PyzKc%;?oP<(3hD&o%eB&v*BW2hbh*EQ440(fdhJ4SF<iR-#a
&w-BAiX00@Xua7j4Y68f;8+KSFsIw}v%)Zw2WOR^y#>=p5r9t?A((4Otd!mU1E>YC!@vGfhI+#JpvfPlf4D0=>1kdf(aGw+zOXPv
_T~M4Uum5@l#Ib-H~<Gryl-F#IilWAoK)_@i>6J<-+E)X=m!lRffBdi4Uu^B0WXn$?mx-0qOPq`5T8jI7NHaUR`>`@bkGnaPbA=r
rpekG_fWI22;$wLW{?Q!N;J<zZKw4a|2(&-yZkZK9kDP4^F(+XeQvV^1bbUem|7M;=3)*1bD75;siox_Kjs1N!?fb_R`+v!)g*+d
Ea0R-{NJfi@>=!|pyiY*;In_Z;~+-S0+svvx5?n(xsEIr(Z&5!MGrxV*p^C`7|Jo*vl{^!nYY|FgGscIbxMNY40HN+3W_rBlQBlj
WH6!aI7Dy;oz&S_xG)(R0k%ti2oRsMAe%oo&1SW9eUc60jasm*Bcmd!grIn20Lp~|NwfcPj7_3GF-W>g_g<?&1S={Imdf}gU;Qb=
o)Naz7n~2TiO1m0rDFn{=iQ4xI;hRx&Q8r(Ra<O^12_PhF`KXi>Y;V|c(&5w78v%{Tr@g{GV2P>HOEnL%A=@j*FOB-4OWVT_}Rj$
UqF)$aQYEK8QY+TuBIx2nS9X#Qe)IDFX;`_PJ)1IYc%YAr?cK`S#`;o=j(&~rHb^al~w9Oay}VkQ5Wwk57`3JO!GH>tVa;KoMb;B
j9C6JwMl|WlKvsmj=Ht4u(-xTf~COWDUZp36cixv6`KB<=dEe?MvDj;lAOnh`}Xj}<})?|x|$*=C=;@f=PlpK+7~oV<7pE4SPJ*Z
2rkj<<2svLo_ud^6Xht#ZRQD*?*P#|-EZA>^6DfD|Dw}_@hvtbrOHyoVUr0>tO}~-c1)Jup)}z5cL6$MY|@~8s3@({zDF;{x7GdM
f(-#soH&^!oZ|~(X_95u@VIbUiFS~NS@QrM3V`J4q~ff3_a@g#9@fd+Zg4*ZBZH)WT8E^yGEX9Ns8){L_M)sj>}R0#d`IOP%8aMn
6=2SYommzT2C2_H-XUZ=yIeOn0KE|DsoeQ(k8)x|^A#-oR1mZDe*4Q@-=VTHdC*`|j+SrI;EnCoCjjHt7Mb`yHx~-nL-nZ=*-kGX
7zc|6@u0v%Qn4$r$69DRIkW}(ldZ@Y0Fcp|lYAcene=ZH73In<*nOcjKc*19C;4(J9Q~NQ&3JT^kHT5*2ii_b$TmL{gdd5)1Tt8;
)C*o*qzcGUYP4~6o9c#(A`D4M<bulY<%rO-q^)V9ltfL{=3Zti9YFgL0A%2-YR$;5lH@0yvI1!3=6^4=5+`;nr&LGH@Mc_$3k22E
z)6z%fMuD;8Q;_@?He7oiQWFSh%aB3qu~AQa8|*sb`Wn&oes8Ak*bN^5lxd7_cqJszJ)IN#9XyzOc;vrtl^(2@9A&Vj7Ij&Rizs3
V?k)u`fpPtLIeajo)`h8u#KiJHoX9(#A1a)IuhwsYw)2WJkulF#`c@%|CO*^TYr<>0NRp}1<I>JdQi3L-)BDug|Dm9*J{WE6~*Pc
o=00-!JW9D8G58)+LONtl7D+x*N)r6)t;4@@K0)Xc#nD<uvi3+7D}1$A8~0|Pbw4Q;WOW-y4}Mshvq{#9O=5>{_BFt=G_6`H$ac@
f4!1c9qrWPp&rQjP)-!Ra;cR>*57%osT95;H-1uG2u;hlTyc^}Q1YXUrmDb-@fPQ@)Qb{j!l~e)Dr19F;<$jiezlODbEs&sjzK!9
RT6_&I3&7?lot?AlLm*o!0=q1FfZ-h@X*zFP;dSlzD|HV!m(Xrp!1Aw#Rm+KP$Y*~SWZJd4udPvC#Wh<ImBHL3Gj`Oh*~4$8dX2y
HVhuydl(hiQ;*B+Q<7psU&xA;n>udZZZ*bo&^y~JiJ4<cn$1su?puS(O%E}nls*>1sYSp_lV@$^2la1lUOty-6_X2k&vPelbpn+@
@!fGx!o8Rsz8FyiLOWd!Xewoe_x0Y_DeUfMGLms_VgA&+k$}(a&B=VV!O~Kk@DY;gL#$e)nBJ62%gZ2}4Fm|1LKBjhw79B)A0xj`
LRgpQc=c$HrGoImh+^7FB<@Mj6)AS_Ref+xY$v@(tYF}F3soaM?4X)#uKlYZs#h}Pqj35|FY%caOZL^O@+_^gSw)RJu!?bvGN7_r
28y#Xq#2??nBt3Z`ZKn=b4yb$+(c<9hQ%OlyTC8@Qa)e@K=Opqxg^!Ci9bcJYptI)R=kkz`2wi66+7D?39t1Vl6uZYrsy}-3B>qW
?x=NXYdspK;O#e81=Nfny5r(G7~DpeSmWiuxd-Ja#|Qef$>~{xd3F8J?eH`{XtTD1dp`{m-$Q!>L=*@H!G%8v3j36)NaAS}ps5+g
%PUL#)kt)6rkRlVIE$QJjm7=jQWS)lz_|mvU}cw4mm=iTW$k#5G9HQb!j~B}|D<DKbvCUS)ahtfjqo_NQReM*Q<vnmn@sbFi87=A
su^t%x!um3#%~$7ay4OWCi5}}qU|RA>q$opD~3gT<7;87vdQM$-2Of10eKYYNP!a`vQbTU!_?hOatRTV6Nb@m)J0Q_L>-01W6aPH
U23KSrKs-?5CU2b#h|Y+j27?^e~!?!nEW)5H6EJ4^3iTGQbxVU%s~2)Y|AZo-&~T_D~ND$UsaYKlsaGG6cw|jpeZJk*PUGL2ojMj
gV?Ip5x*5()}hS!y?q>&G~=wyg?6@ZnvnV*eK+_Ew$U0>p>24JMC9n(!1snYQ9Q+Ef$AbxxhF!-o{UVs_-=Qxt6H9)`ws?FSIh0Z
{PqI&^agY4hk6N?yaDFPt%6f9oDg~+&JFKIn-axgP<%VU@Sj+(Cz#ZY-$fyI6~rYn2%O)~{TAV50#Skz$_97TTHlln)V_^ca_VC7
6j(2Mv)gxu0=8ndASUBMh|mqQVTN$j5kNY6D{@drs65hS--nJO{#LuaWBT<oFI|+H2VZNvtHA0)9M{wm!S1qCt|?I<sWwYMIk*|U
7yigJpf@PBg~Ts)HLX#$fNX+O)#fgCHzjQ@0PoP;nqQ#*&kh|~MLcFF$P&jyUCh!IB3t{6iJ0VV(fAuXal(J%{qIdi84Kw(wSEv9
1kQ(dRxAAhQM#aZFLReo@U#*g!cr7BrT=I!I07wK;7p{JfumhtR=)yjIgJr=Poj=rA+I-A%3>cY#n}7jYv2s`z=p?N(r}^AKD_|6
+UFWW@k^C8pAK@cVUJ`Oq<7;?4<k{Nho0vIRyGYclh&qF4Ws;6J!#`6z2)O^iKb<`d<1TVGRe0syUUTXdvWR@<@;&JCIt<c_`C%m
!6s(mUus6FhRDXIBQrBem<6rQ(hpsEhK2ShEyfVY+B#-DQ-YVj(Y+~$Dg+_@LL#BfJ=kUXcHc@MA!^aq$ir9c1^9rcg5nA#p#mG#
V?smS!^)p8Q3=}n&{yqQs6WKP(jW&(t{<4K5&!`LcwGF}UVK1U+LajPd2RKr{Qs6Fj;EM9Q=FYvZX>pgPA<Nh5UD<;IqFLiHMm4e
lhAqQS);+Cp#mVENk9O-+aCOL;kdwkxRtjz4fU_A4tN`w0>Jq2piq1=TP{14gkeOlwTCfTD7zyZ>2e(!WWtRbN4P+r%gM7}2QBjd
`BJDM^L)iU^i3`0J*<7(qesT^_B5`UMFuWlRIZG@Nvx6GauoOxBsW7n&?NL!d2Gh9Bx!{#WKCvu+uAb2CVlpb3ME@r0Ue@5J9};)
HsjcG2Yv*3@_1QsBk9N9Cta(BY4X*_SX!-o)6j_GO=IijNq%WTvzuUrFpE{b;Lj(Ex$+t7dGC_A*WQZ&gFFk%2Rs`94DQDPWQ^>p
%QMGNS0JyOevgheo?E_iVo(p2eVA>@=@Awj<P%A$L-3GBkMD;NBO}g2uImLOam*=YX1w@znB^PO#gN8HfTQJnBH=ajwb<H{njLej
CwTG62ZD@V(+@8UGQ8YJj6BN}b$7HVQ<^L{-%r+Vs1>Aeg0O{qZ2Yi>gEm?FcjN0nN`2ByxK8(uIQ>=KmFMw96OyK?obCnS(?J``
mu{+@$rq8d4gM<@wa)#zjA*4V$I$j_a|`|C_THW1SRS-q&9VA=JRNLdDV<Nsnk-&&E>WKC<0g00-V$@OtUFZ;#<1C5(Z$x?1b|6V
(JG6KvY!MiSx6kJaK&M^2q$sfCGwE-`S(jaQF6hIqZ@B!!By?q9++4v>Y0Q_9^N*s8fLJ{gjCxooF-X|s`!)wW0nXTg|oRio9?m|
vvR%_t_V1hod4yd^Ne7?wp`&CtGxV>EzWWa=w9IpQViz@<@A3270w?{gNpgg6e%Yx^L4)$SK~cX&F2AQVMEcfWQTK8DQrg6d#{gq
h(c@!N>fs_UvGuyi4mXb>F@5Ne8!VHs8Yn`GFd)?en_-zHL_gRQCDs=l#rz@AY$8<%k*VlDR(Vr1l-6p_PnT_UzN0p-6QAbPIDQi
Db5xCdD{w=NyT^SV{z%TmJm((CiqkUs0W3k;{f)rEI-wC@iGo%eQkC6%K6I%(Nf49Z<=z$^%GZ7U^-mI%Z<JU?y~K&lbCq6Axtn)
Sx~;#Jo$~9R@pq`r(`9b|JCmPXn7SRJMpW2#s1bY^T1uiPUtx!n$5Ht00YU!Un?<_)raFpH@ER;|1Q~aJz<X@dfpG@lSaP-xZL^g
-(X1Jn<^LsNicUnwzEnJ+sXcYCRW4IrGmR+yeT#Wcx@(Ek7?jh9708rn=t!=6NdGM<8T+<7>!i}zPv1lC%iP)nUP+y{rDUux2zzb
Er*mSSO+p>wxay_^?2f@i_WPY#W%c=R}1V@^Z~tR$cNS9I`$yih`1jU)5$d2xE|r=HJW_HNmd-Iy+9%?i?)C8J}&sft#QS7*HO86
t5Exme$A8RejfiT<@A;Fq+>);J6W6?(;8>-tl=$Q9WL!I9pRAz2c^X}XNe6{{0?sbib_;t5Js}S^it_NLaxoFJB<4vxE+_$05H_C
$Ux5|I|??IW&__>9NO32+yV>Q0B=2_%fRx+)!%uFkpALEVVD8OEPB|g<^}6f#9?#T^O*Hfw_A!@!6{Ah7C=BO_ka0)B7e07pX<2O
S&a`<q6li6pIR>Y?XAKxykl5Wq8DRMn)Rh)Pdh^q#ZxginqF;i4axYz-BM_=9H%c5xIcLV1j=<8++3IElNy{pB5R{=|7HO(NRT$@
>3Pt-xWT?pzraOuH55yz3lY5StU2JZT-jrT!>YpcmZTeGr!UPF*A~wpxnBu@O@wMW&d=l@FFsr4m$?6?WF^*Sf&nDN=Is`eys+<7
)tUjj+zs?h7$i~57e$p!kSEN_<*CVwFn*JvYlgR|npT{g%eFEkFd-?72a=G-k(o_lWdWpSnIH{uU(C8?@FOgJ-{eR8?E=tUNt!%T
@`v)2iiPNJd*^wQJt2XSGt8*syK;v+*3`*uzn@b^@p5&_Qq-jdt3f5~ZuC4J#E2BX>JL?QF>!DoOh=0HQJ<^o2uJdgH93Lebk=Z_
s?*kEWJ2zKI8T_~Z3(J}p)EX8&nUcIHDCx?`hlH7UD_W;_pn{=XXpt?#KLw&wBP?#)GdUyh`&-AEvX%SE7s`#^)MTh!gpeBll*U~
2a;&A6P^v|;`T<jy9LDABX4f^jZG)Be#;((>LYXLlds;ZccV>0x;lcJ+&vZf9){&ysNTpn#A?|TWbo5R?&G$^RVYD!Q~M~eRY&5F
U%K95;K4>kET&#EKEgnD;(dU^icoTZ2<EPNiXy`6gjV16qDRw4PYo6BkOi6&oSK?`#{AEt&bPG&+scd<i{%jD%1hXf-+R!c;<5uS
<YbIg4p>o4{@D8JjA3+ZBN8K44YxQ~D<e<uVa*W1rN2yG!)J&h^Pw@i!rs<A)Gys2#(I$<OE+3*zwO^JLO5%To(|~l`9-y#ff1!h
6w?2wC8G1F?_Ix-g3mcVe7{D}|InL>B{b!@OSIrU#sbk#{-#anZ<TCWUGBwycO!?u-#;rljLr?+0GXp`m#CATUou!?Pc7!V`z>Vg
_?>~4Wl;#8UBJ*ut)-XO8I5Y?<%UXK)i;*8p1IfL=iG;ok{+<L4xY_!3~aaFaxFMZO`LO6SPhsF@}y~pO{!ftJu^_9<)<JfdZNVk
MWj0q6rZznpjM=QHT?oE!hgP{$d&J*I@`$8=^<-a$j+?V<EGeFY6i$7gc;4OAxq@M8QB;BxwdrLI_<Y(&Z^+{-wfl$5iOpk>|Q1u
9~*4zW%8hMutWGftG|EkB1(&ky=W@4N`PCC?|!;Ogd0GaVmt`~O7f4T&&S@`_AVp*SqR=Qa2q`cCtJjGUwDo;`Zd3<i`YAjQ2B?(
m90OCo~Rd&!9x7noTSfBzrWDh0=A)=wFTyx!Ag4FVg8UUHB*~TqA`=FCoae~K{Z25cpKr4GhSvg@s0*-loFqa@dqhlWpM3UF^S2l
<D{~mztfBx_@4++Jt`z%N;th50o_|Y@s@7WGjHkAlOlrQ82Q^akKm)7$z}#LFZC!;PgB<Lt@==Q+~#E4YSilX#A>(t+uqH_cLS!2
@0$>;NgC{5dDbS6oT>B<Rn7RzL8uRbFjDeEfvn7wtF1U_@Pr)tzN5`pdwI&&o87JB{)JCQ=o#tSH)WwSCBq-t{=uf-tHK*SRb#z^
=|4^)^*KLEC&fBPn>6N;WGvAhPcgim&e$zGD@w_GxW-6x^r_6Q_cTsx_9Ovdx<opqf`_Bb6R!u4=z>=g)n>+9@ko=KZ0!~#y5eh|
=ctqNUI(rP0>YlL<Y>!yle-(NTF91af}|7W?k7~8#+<2!yV~(BT1y7Wc82JT)LLe2nBH~;Ezy0ytSw^sfhLE{yC#_L1+MQJo)!!3
k8PJmYsZ~B*LnoxPsgl&mUC6UaNCwVw8Tw$eig(APY<UVnuK#Rvyin=8+5W6J@e7|7pNI>aOt{8>2t%EcC^rOXPa<Rc{H8IlC@pr
F(R~n9?UmEuT9CjV7k!i_-e;t!~QNRo(<s>VvDk#NDNM&v&Yv2E4BX(45sDV2O^IAm}$ZvZnm{_j4&!h%Rny=jxcuvto9-ug@3fM
Q9mCU?hxpq-={9s3%q!S-S=t;f3Y>vPaCWcqUJpb*s3|M_)o!?5mD8uMu3{Sq7heyAjDWh0KDfPakg*7WRT)J3~>-<uydXa$J;t4
hbo4O&}5JrABm6drv&1(S(%LP4Bx3$OfgML^eo?UG$td~%8v6t41FbJc-_M5r1w0c{z*L<l0%5hKVYL<zF<<%XX1vCo|~bgav6aD
Kn5O>>llu|z)o3=OnMgqY4PBGR4ec4bf>=*H{F=FU1Di`a4wdY;ObAJL7wF5ipgIw^_y!%=2Jq$^rWPb>*4T&n@!<KRidO^BsFOg
@#+B_)Z?+$qa@IOw-I(_u#Ivqme3(LH&g@AY_*IE*0zE|aEJA8+wuF(D{@bwx@7XhLSX2|-k2s2+ycT3UQ}gvm{3*-_(|f~q1iYI
{ri$@p|JAtf~##&U(3}@%a;njdSr!<aG1W8fKXgEIz3xhUU#NlG>5+N3?!iLw?{1>v9cjOUf=iJkKdW+KW3_>-YcN$SWM)yTEDF`
UlNWm7*=4b#!}TZ><94mh)-X4&CrbJMBOLawS!I;`GY>673Y7~rFJ1PgDX;o;~OLaIs$aNFW$j{pvRk9_5Ww7uj@MxG~Gldiaw<6
A5F;*p$gkfAS~3ps%AGhOp}`?Sw$ngt7A^sa7aN$<-Bq(zeuDh?$q8Bk>@<<v)d%D)GJFZlsO8@F?u|!IA|>scg0({dGpYJa8r1#
@7&YQ@)qajcw`<lLmTkP%KKpQ6T?fG<R?FMUFXGyi`k4<PfHe<cSk3na_R$nKTvNsm{$KK)D;;T7@w$18r!4=c2pE(bL>j{M|@(V
`&fM}r@Obb^|wt2a7<x#eh1*W=OWiTZ|5sUCvIOw`9bm)AdNP)Tfb>o%Z-d<v8l|!ZemI@uhWDwTh`O|@!qzl+leHG0sb3!S<Hz&
bnWPWnFEWO4ML<z^dW9@7mjzvNo{pel>yR?6-!P1{W(qdT_adv3iwt5!I5`ro771-pEvaH=7U&HlzNaJHo&e%+P95E=}ik;r;yKr
BL$f}(_YMPE|wNnKdDNd9r6j^m$I!E-k73%W~|<a4x$}?^ExS-1S1h{ToAFT%_s-1RaclE$YSuf9YPYqF9gI~Sz(pJnLS%1az<|#
fqJaxhiRF~i-Lc6Eb!>7K0Gbm#gJf4BqS~DN8A6Se@LZC9ET+Ix*<Cuna$p@<z?o=68O)2uQeENNvg%i@aYJ-#P+Ol(p-<xTod|<
6}>Usp7t|(mNx6pPJD9tm4A4?!t_>#Pk;Obkt}ood*cEZSL+Z6*&1ut!7x%<YV(X{0ZB~P1jNC}uvb{eKisZoTf?vHOWVj*C_wA&
9^Y6>2gk}F@;yFvjKLLioy*{;2BrbH>>8B-es%lEBIGS+9Vy2wF5ypX7O0c)aTYvd;7Y*yWYEMrwwjuMfZ?w~mW?kf5h-ltcbwgy
VGgga0j!`M76}ALqG8U{BZ#1JQ#6x#7dmZSg|JF<rGa5(4ESM)P%w0bgZCd5lk>Uw?Kd+LJ>>MZJ6KD5K&N}m*Qq&$1CTi2L5^Sz
i3<#RgTT&8#(84183B%_l3j1K&M$B4jSW&6_g(kZi@BbiO>1Y_qIRRi6!CP_o}JK4idtTf?Zx><rr$i_eaVgHzZ?~{=Ovm-r$T;H
5iPtGU&&e6a%?`BZg~=Cuz}n61|X;zC9OtxB5FQb^P{^}`u*UGF}WewS%OJJ`3z+)ggN^^U)GtmAO+u4neo40#q392)V|7$Vf%=1
M0U*A#^#MI%Hd9^*LRN|PGy<Dwd#7jw$4YYdkHi&{{%a0zZXzRai!cyG2zy>#?5r?r0dHbGuGft50b!c9-mGZBcp|<UK=Oc)?I<w
uldxynkz#kI+=>MZ=^(C=D>X}o(NugaHBv3$MbBcY$y%7+l7Nb_EM((!D95KCem6X<(5q8jI$yTTAE2Otkj9l-5Au|*X0?77vGol
U(}fmNIxY}_pLc$utv~*n6=iPn7JUxY%KRD4sRA35|BWUp*MbFRP~EtJ|(;0=v7&PG=47F$bi-rw6ACk9z=-BS0vX263!Yhisf>w
z0;^nSQR>i|4FUv_BC;DBuV14eY9iJt2t|GXHSZxa;KKDEa)T}>-ld_0IpCND|YPs`oQhUzbN5T>C_BnLLrUYrs{rZ53S{@a`(0C
q#(vx03y)<TC2HF@#{y#+3OPp8@WR^Wk*e4?K<dd&mzdsrPgeUf0AZl%21Q@g<HMTo<+aT%u^#QJ}`sFAIjA8))taoo)Wr*jLQ%1
2L-KWVPs_cf9h>y?#X%t4a=oC@IH3iVqpIyautL<JQ6pLR99=^B{o9C^<Qh5De)6RA+OWBkKxj*U9v(;)~l=D6qSz*i~hDVR~ds;
6M!6=aPRb$i_LouGXTFP8%1VjGtmzY?5nnKkFw085I&XFkmoO$Y(5^{DC$@+nc9YaN(kQ}Ln5Bi<L(g^3GwP#bu?{_&v3X@v)TTk
lR{Jaa2d#%j^A`$;MHZX>n`-6kzn<esy+P!YZk2Gf{eMx<$4*MWZ{$VoLD9b0t%O>6Db?4(jaPJUZY6INXA~~BP&GbXee)b7$w+l
jAd$DG_S?*pHDh%ow*}n!F<60j5Y?d)G1goR3HAk-jv7-=#F8u{VFElLaod`M{$FO{9hsOoR+fa?P3+;;=6U4+*!IJA+A@jS!-+Z
j^BY<9H7-I)<F=&P^aYKnIlpZ%X(pROKiXqMv65A5PIi&?PLADbGGb%5(BNd7(KcS%xQhfP-sI(S0pE4^@*2`yx|v;jul}mS%U#W
uo^;L_AI7b2-?Mw9Wv!Z0ijvY1sO$y(>oTG9-!6*l?5Tw8}a|afOf_DZ1Ba3d`p;own@Am5a4ow*g9KfF*WVHq_fS%)LQcJ$Szz3
6!lQ1XQBpE+A>^JBW`NOR`0M`sFdBnAAP9MBqqw8?-^Pvscm_PH+vKNVlHri>6-ne3((q@!@&Ku`eOlmH4$9eBk|NJ_#7|=$oOxa
PzZgAKT{>NKPo#yp#IShg^ueDpG(5_392t;+F=0A*sP5Gd7>=_hottFPz%q-Ke6v^@|@{lVb+M7u|<5&8<h?ajav(gOlZ9t(7NbA
kol9qo8k5(&@cO(cG1b7VapRNr4g_7J)NU3N*}HI?0yDx_yg0fFDP3*z$^OD@v+KGKn$D9cg6t7&gFpWi>dx8-R(VVh<w@>+$**d
U3yb{_4b+WoTtZ+i~6K^3qh10X2&^9Svl)7Nsc}Ob|X!t8=+6atmq=abIv@YN)5z<@dK?z8t0#OKqsPA2s8RIsCbmM4xHt-O`*m}
5A@s8Uj!az<Nj*|X<ykE9HS-g35ZN>WlUg3gw0}<)k9SpL8Dw_6v@N`*!E91vK?$ocfzhh#owgBC66nFf5>$5GG4MWD(Ri#|JRl=
hv8MYIn$7{1p~5O5^jX5L1(B~ih-e%_*`2pOB@|SLdD0htS!)WcH+eF<3IgB*{3KHrh3mLXp1Jn4f@rLtP&UzsOcmdhuQEU!vs4Q
hGdoZN66^aFB5YTzhEeJ-V}Z9@64`JIv44cw4Qh?sO9<97!u1s$Ko)08|7pV-PwcTB5sT*Etv`rP$RyfL9r1N8FvLnz@92nNw|h-
O0~j1CE0hJ7GB9FMeokFQ~URW&=yN|@FgRT=dSpr1ZkpE_)DP3A=<0?&wtNaHqeD~7quF_Ns<Y$IIP+qLd<CC;vu)$Aj+fe1maO7
uRnY)d*9qEFZ}sG9=j}VP~9RyY;It)l379u50yFx`<e?3(gJF9kmjK-9Q4BoaMJU0Q6a0aqa{%|u+R5$mz7*KOH0ukD|-g&^M>C>
2^6D0A(f%108z-1N;~*b<EhIK>#Oi&9oZmAP1-1zl*Z?G^GjL3$(PRyo^m%eIpC4!;k;5}4o5U`jOj_7^-`5_^5309sK>F?xH+8i
qe<7rj9C4k!CnnDKAL5^!$d?RF|#;^><RpHgTB}1z&kSIh|A6jz99RZnD3bUkL~=Rs9>B|e$jccp9IMlM#)6~IJ0v#A)GW1aAhao
sIYN%^y*OMlcr$t<05kQbnz!AYeZA4C_h`-6{REh8M@zE&hs9o@qoo}xxvLRUC`wjtI=$Kd?oZ~_EL96^q}<AeRnHGm8&jP4`)xM
#A-0ji3b2%)a@RoJX{PFY7x*ip7DBIhFb__stdebF#Yn3N?1`Ap|}tV9-j3mNa5QL)XXG38q!({e*ZZ;FI|;u#c;NFEPXrgI402M
0i@NM1oVV*P+?yk1U9{p^N%FoOdW5(4c_q-92$Gc3b*Vn=7vWgt^D{8{K@FPjtg^l4Lf74pMXR_%gO{TdxktDIlq3E4FC{E7+JIK
r9UJa2g=IFXC_mqQ?nbjvk7H8%apyIa;GsB;)wRwrTIeSji`q=(wm9X@*O#r=83i7w}6Xs;aYFwH@*Hs_zi4DQn4ObLu1JVE399Y
o*m?MGoJMc{7<i>x2bE|^qp)nuGLJhgvQy$0jy?9F#|V_$M0xSCuz>Dtk*s;n51gZz}$p-b3bWzw)jFmZ4~oLy%bC9xdaO5Bb0$p
toQbuZB!qv7FaEOhbx5>08%X$Z4ntTJA!5N<AbGZO_OJ!z2h(MnZ{7G^gd|fv!VlhyUvW-B!d!2b#T<R^3}Cp2%8OQW9v~3@ZK~i
(i>Diz<gAw!|@yx6Y?!)D59JEy?OF}L*hc824jV(4c2k&9CY_Wx$*f*h~@rn8Iof6L+9uFl@6B3-&EBvKC4rFI<E$ZDz?PllMr1N
>-tqsp*iycF_wa^-=n)!#^nRSdI!p!<v#Ym&+DhVr^6{zvpe=wup;5f;_cWeO47h#e`<S-ddeUP3!hMO3?Xi!S2nY$#Kz@JFZmQ5
yR{9`XzM`kqoMy9=iE=u>g#Df9FfdUBf|PBp`T~}%bHch*%EOf0*<x2!7(ee9)^CwE>#P}3af)xm8T(@H&Gg^17wE~2e4FAjntBV
oC9G-VV@!)1lASYsd#S|#By4GEo3K`vKW{iR;p&#R#BEB=GI%Z<Nq));=Ix;hN)(;LZ|2-xvQ%orR0#y<9+b2dd&x;e9ovE*G$n`
EN~j~lRMr_^tzH&{8!JNgd(z0_!;4*iK2M_m5$fdYLGSuui2~&)~lCbDJnerj$)POhI=4FU0j;^!n<fRpvuYz^=*_H3-Hb!*mmy(
6nF1{zG?0)k+)$;4lWgO`HX*He^05uv1{miTC++nv>%S>xh=61<@0m@Trj;gp?Z{B5nAi3a-Rnv6{MVE9M@SkI9f{|eC)<qkntz^
o<QCE-{I*tOeC?m%5~MRXBXOA*E?$Q#KLmVewWofgq+9G3Ph7+>{+Kf;O~un2aFTpW)38XwBV@L2W9`{Q)zgNhFDia2>gvMQ36F*
7o1SYJ%6vta;uSc>si{#bVOCbUx@KnQw=xnQelb*7DD1NcMu?zfo4TtJvYG=EY!=UJ9<DiF!ylcL?Ak~;zC70d%NKE)_&W?lsUth
`4BjSstgAe=lTMcHSUb~;lSh^{k+jk=)d*RfSf?RN2sTvSm%Adhn{9HI~wA{&O;8Ag#_MfJn=ny8|YL`S58_X)o+lR8lCDWgt8*{
j>yOT(HF=7QL+u$RUlBeij4FamO!4RFZSnzEvOb?>SXt}m7p6Ca6g;0u7ZEqCfI_di1ClsWG@2a_jedAsaNAyj}w>rJ)b-lJAM?V
#||v1SX|pnBq`KXEfbjm<E=Cgj|&!|z7dyc#OR8xjsGd05B&gW&6{d^fvdiv`v$VD=|?DqQDjXn&rg9=oGYI10!!F@BMM63TXeuS
qT;e>z{D`iE9BsSsnsx|^$q&bP?eUfwZC<ce`2d0T-dl63M;s)H9`)c|I)WkSM!T(vFfG7E=$yxr|3C4;<Gr?#2TQYgQ|}iRT{t!
MHlAN3c$pg3``SfteYoPe8s?fLKf}qzbbgj>4c8;-2lXMbzMV5?TVelPmwjMDbAMp#UZKLQFg`iTNL<1+NPZxVL4BN*Gwd|N3+&}
b>bNZ?BH5(nmAn2H5#iyfsFaK5J@Mkb!`UI#+8>=3&Ah~Y-g{kVvSM^``t4jJr3j-BGZC@jq#lbD4y^3?qS7T|D12d)V^sLO@hyn
dg<VR1+zTo?gE68po!^t8BwM>V@o>DiIpr$Yjm&w0X2q&GR4u_ub{kwdPESRXs5iLtOSvL+Z0-BtRXB@HNGIv2Rcj&_aL)4P&}r&
1jj2x%X1P`W9?<_o5*zDV8KJoo`f+F4s|~nF6`C3M3izK^-4Ca6(F2qRV}--*wkXv3v~0yHL@W<;jWRZsJO<3r2j&>KwvJL0c(i9
ZB92>$!w(Qt`U7(SZ0s%+fi2o8qi}yMd>^{#lkrUxRSC4(O>O6gks8hwEL8We*PebjHw8}LR4p+w%#o}b{}X-fVqIMC@B7;-@XIx
%-({{xhNsSo<M&ID9#PX)PPQ_4S)*euY(hqdHR$FrPb|`lGEyE1+nT#mH`I}d2<7Nkd#y#4p%#cD7^>C)~a&@Ffw!p)xXa1$T`H^
7BklcwU=whlCutcpSw>@*;p$rre5sG(~w0OI*_Kk{C`6HQ5A&h$KnS4TNbOZxgzX0vzTsKZk>UV|60JHDq9QER*d|HFivT*&Zy!d
0CqdSZ~!(b#HHkxJp<cm7c}E}bw}%&$FxLf{&t!~zk~!y;%B@r7p&1xk)iy}q)%B+gX=i{;dQs|f?5|ZAEQ?DD6`|vY`zv4PeqqZ
`GBb0q7@o@TNp`(5?Viz8d7$Cbaa@qm(gfD%V7J68AYzsRp6<ZE~DrNUoQ|(P4fNYpQ^L&^^>2pPNLK6jk~(Go%w(~y)Uh_%oFWi
LD#@x^ylV;Io@O$?;WXNHrra%I5YVnTjpGT+JG8pKcTAQr;;EPAnxj^3%!Es9E^+*`5RV@oFkU{kFj_Z9-sHArBsuJZt0(TfaX0+
C+Rt0a(X#adaey)vTA503Y*E~&t_C_Jx&P^fECiBK`Ck;PZ<yem_^=(+ar5dBnD)#^3n$9h<yqtux^524%!Y`7eIH-bl4DIK}3}Q
N*XTHv5jdiYp4X=fa8~DEPLrR7HN%VER_0?b<^gM_|C@Ft`##v?{L}7nW?WBlmKjfQZ|S0jp&L$u4(mto}hZ_^&p%M0tOPKH0gmo
_liH$$)qHa`RuohvXr|XXTo_EGYsP6YCu6!U)i!I6DFj2Un?$}a7Srcn^B8`C$Ys$(hFyfe?cnAuhL;LwIIhn`<%DH$lyS3UjW6s
=Ouutu&&y9*u~OE%&ssqd;|Mo|9b`^`wE3Z_{Bc|?5l489tQ!hoM;GyYfQ1fLnU3v`G^QqLN4Si(d%!&y{UDl8$c>TrTo8+<g57Q
ots%!uQ9wNM-|f`{79+J(KHKXINF_A=@6p^bE8~GPsE^n)$T5_7?aFD;;{7^s#5<29@fK<z^NvHV<^<UJ0Pu0L&~9|>=krlGVV*Q
8$~V`2k}--5$B~N>|($jmNN4~$68)qcgMvewF)L~kY@~grM#ck)o#R>-z8ojto>KleAuc?GxyCD#7gIlTp*%p?hLR)p--;~q;MBd
cz#V+_*Nv-hb7{09gK5{ePxn`q8%^tvCoRW=l{?@uKJJh_9z!<c)=lkS~|sEtKG#LVl0OMSu@PLKd~jvifUkJil~T-kN_mF)l>OA
)yF<x7lxDPr~_)l3xOzNf;dr6*=NFl_zesU<jvlFbS}+w$6h$MYEp`&g~V=WSquAAyoC6zQMI?Qz=~4$5a*Au=)r8po7Xx2h7b~G
(I|Q_1aUY=288lLl(ddg_kc|TophOZT}W5snciY0mO3WoUb)=gt!{8uvoP@R*b%(g{oXoB#kz_#c|Y$v;Ba_I+U^v=FrLY7Yn*+O
Uwnz0qV|7OO&e>X+d;asc0tq2>{8%?92<E%cHm(E&uTS_WnU&^MlO$V1l!9-y1`*3BMyLhraBjny@E7Xjkq-JTF%3^O<xw??o`W5
++<7kbw3hc`(N=A0o9l$1NcO4gxHf$2YGC#N8-5aH^OokXguF`YW&&iJ2ucr9=nsf>PBaT&jzbk3yqfPefGNHFgn^W)iD8O_ErSg
dOl2X^=S$w!v)3nb;evIjwtZN(CpFqB38E#*MJO->}yI}k0Utd4D>pK^>26p0AcLf(9kdd!1GdLR)E@|yM+HKwbZ;YPvBW>!|`{r
?VpCk);_{uF0IAl!ujq~wCZh#ME87tt&E`++QPGpinMTq=x!RYeA`2FYUxnNYfPG;JMq|uWovwHppFD2f=_8mfy7@2#`BxmC02Bb
TzA}$drTn50M!P(Si~!Uqm**4Y)U^oY{bh;t`QLBsy*uhw%B3wJTxAwp4383mmDKTwrevn_Bak}rdYEv)Co6bm-_N5I{feD|6(A*
HCpYzekX^~G3iSme*o-)U%|Gs^*ut$UnvWnSO$DXS<c;ft#kf@<|QBiRZsDGy+Edpb;G2*;>V@AzujmgTD4;J-sIrgB5fr*;jsmx
-b-G&5H7;Yrow*}03}SiXq+|gZ0{vy2|I6iJir<s>ezMzl<i>1WlsRpLyG0;W=2TmNb~%QN|kiCowt32jBQJt*=+LP;w}1Y@zdd{
5Nrv5DMY%fN&~i^4GQ3|t<?A!G_T2o%2>G6C5g_11L(8e`7HVOgfz~<E!TSFXN#e@yLofu#i~8uaUZg1&o}pRwKV*9Ky$A(CH5E9
UIKdNOO?^z32{5+lBNtd;WhB0Rp6tdL_F3kyHFNG?p8Z0yqL3<qd;eXL;W;KjXY{lzz}H;OVyF@-EmT>#}E`mbs0bd?}hrFNOq;B
bK)uc$M253qjjdcTK6mj=T0gW6wZR{e{Fu@g+SZh5$mOA(8&>>`aUPrySp{rRLUd#+@0o9(DEcT>`e11SnR9OHJbRI4o9JGq_?Gy
csPX3kKAJLUx|s`0d`n!TQ90P^7gO>Ae5riGxHcZ#Kgs~ZjSOT?Yk^OPYS$$y!Y~oJ-bV7QkGa;vNX%%q2<<i-mx!LgFbeyRGN2Z
q5!lw_TQWD=TARR%gL2?AR%pIE}7G!DiBV2S~bk1Qb`?3af}}DH`S#6@1%wrH&+#zAH8er<W^%bzVt(<9(IaCx;qI(oaswTSfMWD
<S=BDKcPPjpr;WfYh-MbI!3}e90YQ11YKcy@5&{CAoO2l4nDwc`pY77I?@FkmkeKDz<7%&mlOxRS7Qn~%T&L9Vpg3<IUw6ic?-Q&
0$&$W>f+|w9&j_pG04P(E5#vM0Gc64a3<hlwo7kD(8LsdM+1?ZQRV$HoLpq83k*dBB7Oi@YDGiXkzD1-LRn9(OY~ZTwaU47Aki`6
?O)o-OG(n&cJx4faWh7f3a-tNm>Co+it8hJR{`yXWeb`tEpDp2+B8Vn&S|3Q{XPjj<DhA>oU6GzO{#ygQx|F?Z`07}5V}~AuRD$G
L>WHI$zbtfbH;rq<>H%ElE5D<NU(6Y2zy*zd%?+Bw|ysQdus2BQ2W}PS{~*MGZjdYD12#YWPt(6C}!NT0{GK&@-;O^80pMCr~H-d
COFgp5ba0Fgs_rBrFI2j?CjmX8VMyC#rFOF`Wt28?7XhP&bLk2iwmvj-ru}^um^_j;#&Qj#9GQKNgU~gOozM8z&cOF-~=81oBw;X
HLzYER>G>N_JL?92N$Ci3|+(<A#c_?0}=36BLmv&eA)f1sP2=};D?1jP+P@~xMWv%?wFn~2}a5Car#SiB&WjzOktL~daWbkgM)qx
(4MRa%j0piZ!ouVUX@%h208Hi(YPkhXHvZ3GCL3eAy7=1IQ&JBsE<s&ea%N+&T!uqp_OtR?DfTp3lJj`7pIN~v)h;3&0T8+W|P$j
S5lSv2BSs}s{T&Ox2tX|YV*#Mm-kRpBM>uQ2MP|Q5Qv$ZOOJ$8fF2|mR61p-@MrN9(O2nN2VYHklRnnfzKy9TE^OMAS49+=@jC0w
Vd_=+_dW_4X;h^M9K<%DF2Q%3i)Q4r!U46w)2ZPfndki(Qeq+WXO7lDZ4T5}IfM{BcGcSC6ft1jLAvWr6K;0gT(HHlNL5tXup=5a
yzigm51`l%=peUaMV;ymtRmhC_JQkh?+077|4^G~BqOXI%w!UWZ~)p0Z_zJx;hzM#VqvNT2LWhR`I@>`p6|ujYZGqKvX+pbeIu0*
N{oXt=WZr^WeVS@Mh#R$<%fZj&^a%n%1IQNaPvLO!6yvRkr0!=B!OJC$sLagIbz(D`M8RGVgNU<m*B(J{!w&HazP|BVR9cM0D!5Y
$4erm1LM#|aQ+fgbKaDU98E99$nYD{tLqFFdaJ#$Cu*=uz8sP2YW#68%@Ad`fj?K-x3fjc`V(W4yXJ8d1S)-5n4hBqRc!JjPvtND
_1E)Gq=gIUS)l!iE(}?nee`Ukc4n8Xu#)9kwzYVn@dCvmCq@ea)}I-WVu04m)+S(Zmlv&UG{j4by<yEi1c|JjRfSyCc&@R$d+My%
YkLh~12$|)O|*u1qtr@pLn<UJ9T8mwb3n-C^8ZAgO}8)^I+SQpQx`=ZZP>7NurXY%QfR~ES!iR<Oua|y==gyzN4F(`Q9-p*86K7q
2?gW_N2pVu<DtSsuJhkt|4f}JLg4YO*|Bj4mPAH9@SsygK+raVFRx6?Yaq#jZ!WODX%-=m&<>l3l{aD%?$+u?m+d4Q9LF}csUsYU
h8p_;MoBrrRC>hj){C9L7yu@Xj^*z6PSwA8w;Q;_w2umgPrn`Xl;NzAZiN_pIde1MtE4&3{jc&mp#E8Op1?`#Wb@Et0YdA2YK3~|
W}S|93C4Lo*hfPq?Hvj;U<U~#MvO6D<MAq<g9PW^liC&1`Rv%ZC5rKrxk^5_`}1jT&z-v)Vj_>7lS?AMq@pj*L%6)Lj+*l9DW|h+
Eg3}W?ltSVX0{%T)Y?fmM=Oi=tFK#>mv^C_(&SkM*Ei>oUn@IGb}1SX0Z_JB)1LpSvyui|HhqN`8{xiMa28_ya(jL7ha@DrXabnM
^M{_vqZFvxY$3r#eO{=rwrTm(=a#%+svr0|qzT^Ar<7-pIVfUE&Vhx{Xw%ZuBimN|fXaoowGTt%Db%S{m2QA(dZ1s&nIkEs4HeV>
9YzY`@62Wl1gBNUzuH>#S=RaAbfi|KAjgXO1QSjL{$Y|8ER4ERDVAUELBu&C`cYS;pqmrBS3n3~D^|WUlTri^-f^k5%qv7|02@EH
zpVYTpAiGoK&c|u-Jy8nh9}H>Uul`p#&2|Vk3R42=s}j=*1n<o8>=Eu)6lH7v90;<S6i$Y&OOhnP6ElM-Y(xnp@at|^PS1nSPz&x
{h+59e!8uHhbVmW@6qH2dk22H1B3<@LWEU7ip}`tjffYO^l+T#6JCA12Ig+x8CYicelo*-f2ya?rSU$WwgbF1DiJI)QmKT!-FG;M
1QI+#9zwm$+}&?^zZ(By_kPk4ku@YW=~Q5Da3}7ks#C3zKmhbX$$?b6-{lLAv{#|gu7!n`8u?whskC%&vWr6|*}TdKOIgE{DL1`X
ZRl$IEuc5XeY3KOHkTT;n_oCgBVYB?EQ=s(pSf?#<Uz*agiN8m)p88Ie}l1GO$9fSRz+rRq*M=p5u;4kt*kDhF91jCCb%-jfN3AB
&G2euvtzJ_lwnIPU<!_Fx?o!cyuxx$h}yZ2iYDj+bW~a_nz@^!cne}!AEJO8%TE(5Np&^eV{&H1>xVBbZ(mOLt~p-j!*F0~-5Ho<
Wf$3n*qu%VQ0}LGhyUA1rw6w%u_9o)cgVXkf^gqV;mTs!tBR`F$UXBhCcFRe-joM$S^^4a^h%R1%&a=E(&fe_Wk(G`qw3ufyS&&t
nN-=zoytZ<VAj89>lFnI+DvgdJfbV(-c=duMLF!Mh88KrrbIRl*ewTf^O_EM&=3F!tdMl1)|qo1P6hl?O}Xov`2mof4et%BbRLAg
V7o-zsWY5>(hQajv%g9v)_#yEuMcjmPXJ<2nhx;`Gw|A$V%?=quCPZ6iqaCg^ENFf|1e#fEv63uGF6a+i<3lf=n@;x?daMzVX|bv
Ecl2G!e(<%R_O;Q64UwYG)+;|s`K)}oR=Yj0K^wK5Jz;Gix=-EnJ<4y;9zob7=FbW-$RiI0BE>Hm%~b$4GON(U3c$?PQ<=2NAxpP
zR<+3a4-P%b0K^8=scUl^|5s=2RQU}q1!!0tVY_!MoS|Qv`_3Ot0|hyj!5M6ckwjFLi*L^!xISpRX7-Sy*#|>S!VM)TiQKaFwK+4
`|hc+B`?n)bkLkX1Cc8<8EL_nYt_gzL(2Q}?2%9oe?6f)nL7CJ_82n)nZmb{?GvSMwiDj}cB*Ix8hK<Nrh3;U;<5EdQns5hKWsha
$c{zJ$ea%0_KKYZO2lf;QICZ>4v*~rK@A!mk}#p=chVUm`!14yUMpF6d+Gg1M@)b!80E{nYE6zZMy`j#UK?2MeXq}hA|=?rj3!+0
+*ya2zw!OOmd;g~Rf|u@J7Q8%H<Rq$i1hZwLc=1=p*G({<$S;93>69es-OJ)1XI6*3joTptAnkHcwnKQS4clZk3VOio-t4)a&mC{
_0%$u$lw~pwGlKC-TkM`WVg{5+&yV$&wB*CgI7=IkCQ^tGGkc<$yCWqBc#lTnQvb;V1@rRm}&!J8NNdhFWIU9Z|fQvi@zD65>4GJ
8W-lH5gThtEQ|@KxC$j9Gv))Y+mU(EEjCaVTtCM(d#~v{<huskfq3o0r%8y@lqC)Kmwww|5_taPmJnWEdkI^xVs6p`cy(*^k9PKe
kwvG1iygcOHVTc)xh>|=c_@378r_9=x6DF7y5dhSMK9tUlP{tyEJU9OVw|Dr2zm=KD|!<=GHNvDS-WNUT=Ky!?OZ_1XXDXRce(w~
DQcK6zEQ+c#S1#*oF5Zt&~9%MzcvZ61J;4r!DBQzHK?Q)PWkcYqk|#qsiOZg!fBRD@AZ#qsHg-L9IEEfTNL-u6R%@7qS8dXje+=A
66!eU#uh_9Tm=V7Y$Vo$WF)4EGgLSV3d($q{C$a(%l@+UNdREVJuLB?rpW2qC*4V@)Y#^B<~Hd0AO5$GuUIr@ss#J;gHWfUZN|o|
^g^8MVwR*IehNCQX*GukEs@49N-1A*=6mcm%wv+F)Zb%_DR7=Yzc0Heyqscz=$2bq@Hh12jU^l|R5ibz?B9%&f>?ru67p)ca;T~c
91AJ8|3r7gQZ=s-7&K5;a2S8_SZ6s%$uq-i`)_h=w-d82{K>pZ_dQ;u0%n!zX$=QbhtX&L<J9Kow{NINS>N3)d`ddpX3~8aPdPt>
I2ywL|MjJ&cu0au34h)B{gmlljowvLT5(_vYe7i~*lWEWcZ?l>cgc5iEjrqEumEepZ9i~tF_Zv+22-1)>g8J;S-R>5=Yq|fHVyiO
-{?TK=&-9q>6|9*-#Qb#z#7_r$3~=ki@EQ)q+_PoFFSSJcWA^zE_3TH#UOsz7Mm@O`XiWrXc&;Mf4hK7nE5cS%`oqQK>O@y6TIq&
?p^SZ?~(v=p!|t`R_*&XJtGxA5M54`a<P~4`-}afBvHUCC+=}T66((1*s-C_y07BqWYI$($9~-UVQWRkfuEp4FBsX+5iNTD376W2
SvGf@Fr;}ZYN`NcL<7UdDXQ|A%JA|KMb9lMn0CuiWn?w8bq?mK_C4P9folNOPehF*{D6uAXa)4cOY_?Gv+NU1@V-E8-FH%ibE4^Z
23JOwuI89Ao7m5nl#Y99<a>$f`m1D(^PVx%D@Jb;Bh=Z(yG6Z3C@_6gxS0wYPon>|l5VM>j;f9=XutyKsf%b3&ur>lD5%<LhDj9H
^kGvTMK^7qK?X7uqzP5@l}bi$4v+T|YY@T;<_f#{7kYEpL4t)u-;pB9%8YFvkS?10DBVu{Ni<Z&-`0o0jcn~Ur)K~qcyuF>y8%yY
laG;<b2BzofE;WaoM2Ab1ibz`;zZ+!{5f>c1l8(30{Z3Z1zL#HvFkluiVI~wcKPvTFDi2=UYJk8ta-+8mGaHUg#Pub-aMm?sM|RH
+lEyWQ+NU#KJ5M4MdgIJv*LjPE<}wP&z)zCT4;6)xdQ&5;Bx)L3~|93SaB|$gKvIiVHvsw4LK0ptjSDI|2!v3ppt9l8{7_Bb{RYv
C>zfIl%dJ&T20a*B}5RtT6e;xX38}HZc~R@st=1Y^S8XaR@M=TmndRq_V7KAGX&?2r8MQh-S@FQ+YP+vKJ}G%gGY4QMRcymDVNu|
Uw1u^N7b5v+j)FzB6dUQH?bi8p&L!<Cc{~4<mO?yI%1%dM=pMQEl1dGptMOP@IqU_A-A-C&a0ADH~Sv|V4MpTE-m^9^rmQ~Liw?u
eC#uk)>2RckPcEXdO<EZ_&g~?bi1%|pai1jd*L1gB?AN1YsC|k4s}d3lQ(k>EL(6r#}|>&+}6|&SyZ-Zg{k7l>%z(4fuHu@7X?l}
FKi6>!%_tn4RQhPDLq8^nA_w=bQ?w_l37xr>Ne$RGA=o9p26}?-5N<()*mS<nAy%v%0yAhERvr`T9!|Qf7HzO801n}meUk#1$-4s
XBb!BtT5Mnwmu@3_8D1D<sNG3#8l%jO9%m|p(gqQb^*72d$~T&y2sf5uz!L}WvW6%u{YRXCfzkxm)V0$D7c^z1`_;9JN+-DVSEe6
$WM-b9AIbwQ9c{!olm~PxyN*)h^n*mx~D-AVJW<DfX9y^his#C5XJcPNc7r7+QnKI=q`n#T79Otlh>52Ck7inRk{QsTywC6eJ?^E
>#G)zr){RGK_EQTfQQp7u+}$WK_gWG>xj#MtCR2c%ws_C^t#*+nS@%tr?l1urvi{|C=S#8%Ah^CR2Z?ssHYre8j5mAiAYP_zfjG9
u=0kcH`AtKz6bE!C*vvm@%9Ee&((%~xx@QD)lyhlrE+v2J1T_kX9*?~i}4%?ApeSnY&0ESxv5r%#)KtEE^5a7kor#DNAc^+&tmSE
)n*R|cK%L8098T`lJ2#P-sUZrB7EwA`A|rUcFu=U-r_P&H)+*SdKF;?)4oFr0}kp>jO0J4P_s3y6!xr-6f0tgvUr+W!^`a-=|H(2
{AQ5f>SL_i{hKcSYJE2PIbwB<_S0BY$zr%EJn63|<^l9250;&d0j??nwJE%orJ%7^5x|RI@F9dn@%1b~Qx~5cyzMXk;N7Z>YAcT2
(@H}6Plj&Zb_lSn;#A@?&^1im{$#t8&!8-^rm`RO`||Cc>O>BhLUt~MT^M4vaH<^7fax9Cw}HDtZTlmlP>hW}*(<vTt5=DPF{C}-
R3P^BZ1OPb1(xXudhdKXvY=S1SQUk4qeAzYG%4Ru3GsdDDg0Xx0#0}QHT0a^4hGveSvp-(EBV#A^^{f`13O?FDI*V!wPg10&h*Qy
w2ja276HoNHlLuAeO0_+!EODc!xM+I3phqn|0;X_>FziDo}I-rTBllhSfT8ViwTaC(Gv?2h%9Jb1hQnxWHrm|$)1{{NEKzxoj<go
HWfWZGd&p-ucL^<0Td%OXsLi{C_{t|(t?OJh6jAmSu!vQqj+wpu6a6`PE5Lzca@#Q(vv=Anke^mZ~tB7%luDaoA)H@QaF2`U0U+Y
D1Vpg*s@5*=iv4N9=-1O+^%>}aO$emQ9q@x@0kHHGB;#hp$?6F&QQa^0#DC}T<_8i+2{d3$gVm=P6&3Gen(FSqjIk0`gnLp=5JY7
`DH@Fml;?_|G{m#$bnY*#Dq2*l&0d;phk3WaqjvU<&{g@<dgDj+z@160?u<Zr8=~8>M6-Se>M`*LC{$ApcD#5k8Oa{iVo>MW0vuk
ILv{5y0T*P1;S92-xV+$l~KI+Q!|`8ekcvFOnCB;7hzbjSTx-;2~eQxJ=2~^;1pPM6Z@~7#fokVSsBVu_O>S*MfvPJ@vNV~kSf@$
c+jW`RtxmeD59RF6dh(5%T<27XZ9k9IzKprec4Xr$ljvVjZWof&cC(NCUDJbQ1R#7$=&ek%|F4V&)<<ve+tSh8KRj1J+8g?8$3}G
F^g*x-A09QV`<Ron@kLBlJxwQ;-e|#pv2MLKBP(_>Zm<E0b|-E>nQ3%G4oDa6aSTn5*u@W(kkNN?51n|*+*buon~Xwoq`S&k1Hn0
1ORt;62qyM{;<2tHA|-uK)t9wgLk~Sr)u?b)ro59j_AJ&C7PoL`Llelvab<_B2pP)p6=&eWz@^)af~kq9k-dB2TjV&&$EZS<!)w3
t~J4+`q+u$5SrnsHIsL4=N<?zDI3)w*wp+Rfso4@=W0wYOl_n`-2jg}Pd4h#!Kpv?PnCfW<287`p6hj?HUx7{btHj7B6Td12U*)8
;dVc2?Y9|lA0h}m#Gk-pjUtarpWE*uTAHxNOlQkls=^nL&&=-Jk(EX*%Ym!vvt6H*J}{Y<@%oTZ=I0$F@F%{*#j$v#OUzB)*2&ZH
^^-z%VyMTfAbCF_9`0%o!nEXXy7-^QN&>7cS#69DeW0u^@{SIbvIHZ9@U6+#;aX#s=1JoXuXl?uRWIKJ%7vpKzwi7Z%o{<V(Hr>^
!3PA(6+~UJT)aIkC~khz0tPUQ0SFAziA!j!9I^lv^9swevO><@H`KqNl0|xb-`lj6T)(&!l_cTwG|gryOE8m+^)YA7GQxjdyjTN}
0(`~v*J!BT*j3e!mq7v|Jz_+p8RM}2V1GD3&pW<Mf13c}mtirp)5!Uq<v1@WdPp9tuR~;x$IuIz0ZpW`9(3Oxh^zb2%%ImOOS`Zo
xNWQ5PlqPWrq&?VtKz4|q7AdgkN13?M*X!G=MJ{3KR;?DDi+)A$zUkMl;KvNS24myf-wv__|6E`3tW8wyCTP}M6Fn{o+=7TKSP1B
MrkihR5zV5O}wDUeBol44>J}~%Y^GZa}NpaYBQs4dxp;QbU$U9b`dBvlQ$yeWW{(4<{IprHr~jvuhUZ|{)RH#Es>dP>W!-1q9Q&k
zZnDX6WFjuxN5j)%qL9B1ZV0)Fut1I3CAA5h3r*+9ng9cA5zSsyM1~Iiz$=PNEUn!TeOmZyIQ$jxoYiOUjZpqE!XT}f@_6kd%j20
);&-rhY1KO3Eul5SysTr_CUj!8Ou!Z?hDvN_2*ghEFT$eIk6(0prGA-_Q?MlxvNKHc>mw^fo*`=bjcJXR06d+)FtJo?2vh3=dQf@
CZK=O&w2|Q4efLGYe`N=6P@)REf=#tUpBpo)W}id=%xpP(FOad!+@79{1u2?u@Uw(hC&V{D7mMxSg|2aNO=$<_P|kQ2z4x3iHeS~
If#*%LTak)PV>jZZ@;5P`PAfXA-Bl7F#%_akEeucBYt-ZZdV-z4CKRr{gg%?5HB5jYjC`zY2+<4_1EN5rJFSUGN~^i!jdZszuUm6
S?x>$|B*SFA>(X1zWgzT&>%=4M&>gGY(`G><)L$iwniw0Z52layeL4LBGs?rx+Fx~UC2t(iM^G5?xE|9|1kDFIYRs!P<@Lv62LUH
98;%^OxPa}!I1);2U81<2ZHkDoL55X9zS;Rp37vOADeu7xt^};<wdx3;$WsoB5V=K(oZYdPqj9Cf$DxrIA$3Aew|2%tSh8Fe-UEO
;>nhUYcrT?uLarYcM=>nVm(o~SE{RLUvhE(>CK?lVOufL%hIHY>to>jb1OfQ9$w;)2=1J5X&3C#9w4CGunmJ##^ejwO}>f0hBH6!
4$DA3&|%3dr%cgc1Id}cbT1g*Z<YD-iQdEcJR&vT-)>`}MkeRcg2qaQA8l!SCzVAXh=YP22%|kfLYw+%i~iH<mNwcYOG<)dVyu_g
GrcPBnnmxJtL`|gE9J1a9lr!|Q?G|WOGR0b)#Wed1k0KC2u@3X5oP@~2oic_8!OZ<a8zNd#((kzcS2p5xr5r9$YFJmCl)__tGLTI
vDu|bHR@jI{-2$rla;_n8=FvO6`nJIBEbiGaII+^Z%gVrG0i>lKI5*+&aF;4ti4%6sqFk>O2jSC<#TYmaZK*8BymLEMQR$xaMrA9
BtdiZgp9tY#VFeu7Y=fw+`Oi>+1-0x08O=YOW-lt?C>R=?P%2NAxD%5iZU26)E$~BUXfSihc%y5<%0Kv_6PV#W5i+8Dz4~6D#N6>
tYfey;AGd!7C9p}+U?`pMWW3K3{VLr59>NLJzD)qI*g>;B@VjHUFCXbGY%v%$&xOG_8&EfD*C1qdUpX18$s0kBsAu0+JqG^Oqh%G
qbD&GwWF6=RoD0O>I?_59LNGVaRKf}s31=)I9uSEqPDzlXrMH!Yw*1Ki246}PnHYiSKbH6Bq^{7gMal<gR{Qv-B(1iMK3DUB^nYH
w+LU1au%h1=l;xV$k|EEFO3!RpPe=@p>mz)-y#f+L&5}rik~_<vGe|9MQR+c=3SQTO8r#wE%o{05~-B~`Jdof^QaYEdw^-_7`b0a
1TkS;(C1qv&AZBp0;4;>@5)~tfBW-d<CQC$h&s)l_W`v?zt03{(QWZP@x+U3xF5Ry&jo4IYr3X$66>AW5JQ>C_358;@Y+(x*a^J1
UhAtCj-=bU{$?b7AEtG&FAQ!dZ)i#|zw+5Im#P;Jz7&}!e`mP?)v(r=;wSR%SDDd}g(!MgNUZPXpNO{Jw%{rv9gm8CGYXi;IBlHx
y8D^J=e)Vk9Gln9N83=X<{vP+&WmqNn&-|6s+B+*8D7xdq-P!}#fl8d?Hw5Jz!aWn*f+3_2~ZXTv=$WnePD^brjy3=FvznvU;E%-
DNs5%cTKQ5K3$;~lG;giqN!(+VoqKZS=F^*>dP<6<Aa#pck+laI!k3`aV(^kX@a?3fY7%<d<=fEC}9s(Y}Pow5v=#<XOt#>CF1=V
6+I=p>d1k*XR-5}gK-?DG5<6O_2Ekm;O~Zak@~c1-p^f&u{fwJ2KLas!Vy*{X+A!OlklVG;(g#`Rk(x%1ZxziqP;HYd4X}TVwGYa
|B|TPN^Tfxo^<iB9xkI<!Nxedi-y-*!1#mLN8v#Q!A_fjK18ml(v;IrfX8+xp3=v=6C69SWE{T3HEvZ*00a$gBylA8V+@K*wjIEB
{4J+Cyy;6<Y|c8tTHEG3XMKKsCM|~-;`zJIpg!|WgvGuYuOH<ZVf5K88bACd?Wd%s4kfCAMxt;IWl^0|x%8nW_yYF$Bq7Z27;q*1
boziRX77RLJ!lb}-X~#`{4(5LXsKKnvS+rl`F!`(yC0_6y0(aM-{k=O3UVo7R}YT9<TES0O*l%6_wbzKY!YKC^`A$C7^-}CX<yu(
OtF%AlV62!`M^^}>vWI{Vo_3=h#+22o^P3>0hf^j%N7wn1k%0cK_X!L1P+NUJJf8o#yDM8_omc4oYbGN0=xiWl)^|@bT2Ts?_Zn=
R>MDh-hoc`J9$JMND`dIN<dt`M=+BTW2Zi8EXWUp0$vdow1+v5|M5ob-hSr1hxT>^8kAGPwR)w8n5ML=9(fOL1dlm72+K~edG{gY
)}BJFg@mi+{~kLg=MR|fs=kU0%Aa#<e!<xe&q(0_MQ?gN2D`XkU><t8RY?)|l<PL$+4WDu6YG`*2@s0yktnr;&HrN@@E~I|8%os*
SRDhSp2=?S<ONWggY8=U6MGWB0XCy9ld%TPgCw*%=|J1ccUfYQ=h+Ux`9fA4HI-GIGTf0`KQ5B@PQ@K-T|ZUhKj>F#)ck<2<jTl8
VC3)#DhB+9m#C<aln%^aRQ^wlwhcnRdEO2{N|0QlP)9gyTfJ8ai<=bdqYj3Sn-2H=Z##5Ad8G}Wu?I_@2?4*rg24Wja1WJf&HC6E
5m^`~c+N+R?%To)jlLyxw^T!K>+)|H<*ZHGsmOT~7D<nhQ1T?n+}mxNTsawTarz0_ypF524JTMoQuQ^Moe3mx0nHZvIwDI%=jy2d
vde-VT5aYWLK#sgCQ|aO!#{575e6spp#k<_@eJs4cvp5>FBL#M5&1elELJCk+tNLwxL=dueK%s;ITpMzhIU2N@IJ&8L^|LmNb?>Q
)Al1~zQMh#CQ$Z&1fXfc&3zX%6Mjj^9PkomPe$!=koc*cRxJ-FjqWO_Tb_}sbM2@zzS3Inek0v4UF&8p*r<EKHk`)~L}%C@Mdg=d
%JEN-Rv}MH08E~D{@7G?6Lh4VhB}0Y_v<qW&N1Meq_pk9-<9k22I18}NV?|LsoB~BczHH!XgZUhqsfAC+;w|;%Lo7SEa_@m)4vLm
o<{7?O7Xwn_m8}+&9A&0-F0Wf#H8Vr5JcbLNzorzx<CShq7?57plnUi?_oh~JgfZZ-SKR-Ipz>MI6|TQ{LEv~<M<G~lGNpN=zv`y
O%sXQM+S6tstsx8t5WL3<1gYjoJFYF*5ZrRM!?`lnXS8yF<;vF=$>hrn_{{lIorq9rUp@5OuiR<_ab&l4M|s}Tj!4J)gl|7s#-{y
N>o0mH(^J@-wE)Cy(>3fM`GQ>_8+m2Lw|o&s1EpP2ufM!CXQj7mMXDBOZ55MQCh;Xde8ibDPNKdrsIy5T1}7uNCSF|`{njcT1o;V
Tt6EFEz``to#|uFkaO1I`N1|oj}5SYf9yXQ!>dwkst4EIp9&SWphd9v=k;KVmOLjT<n#z6mQWmf9N5fX<@QXh{rU+r>b=ezYzlwp
g5bY(@Zyz@68{BW<*5f3(?m0+d;@e}aIo??eE&26v^a#$Kz00kmf096qQ?XHpp}R)M`js@GU#geur)~%I_phP4MuRan%Va(k7&vj
pez3rAD8sNa`WY%79`k>TjCETevkD0r#AE2n-7d3TyB-<+c|v5O^Jba1r?+jjL!(*lYu$id=r2X#=KG5tKCmdKynI^hgnZnWZ;nB
{iOP19XUlFvPA3IX5x!3xI9$5|J6jL(975m#I-<7ayq6zpeGte(Z|r9`b$Xv!fR8TclZVC3RVo$PbSZ0Zr;bsLu+nbQb}9NCnu>;
mIQG+Mb(!hWOaT5OTPGSc|s~uMoyD7d|v`z*i;XG`}Z1G{na;e*TJ>Wh5{fkH|?kMyl2GY^;girq}Wpz$wpPQj3%4fde6$iUE2YP
A)mcgb}h5pdJ2GK$aYqS|Axjd@NSm5IA-E&Ux+ocxU5a~AHh{J!V^kQS_%9I!cHw^*E&7UTE*EY--J4)T6-JFrDWyTqe4&BIvv!K
o83-)?Dj~63qb7B)pJHC;|n=RBf5S`CZbID8(AO>tP$_BoYuV)y~Ie8vRYu}KeZVAev2ct^eBy`VB4%4`r>wU&>2BQCCJRZgt2}C
u~0>tlYsFy$Atlm&tB1Q6DI9EFPV#%P7;}+=p9hpWsn$3u_Qj%a74b>Wp0m`6BCSv2&4W&u@J%Q>Dzi3qu_X#;@al%$laH&(EHgG
A!MIkuP_7UuHonmL-<p;95d13+g7zSA3WjVPNEc1**U&*mu6x}^_ak4DR2Ih;Ah@5R{0)sX|tgwkRn!xo!?e?%MjdS(Sf-7z8_51
E;_-phEYrhcpau@$(gk6H^X1&raGLlR)QP!5R$f4-tUAjbIERv20q$VxK1I{&ZNvp(L9J|LLn$amv(6KkCe4+<eDd|oP_XwM|r_8
x_B#5jcKzKpgPdFqrXQPC5p)lo1vda`}JH>9;qb#HZkKTMB2#)mio!cAMbFMZdN<l$YC??4t}#e&q0nrayY7T)l)ez(QIR1+UDt!
Wq|=aW?g_wr#XdT;YGBiEy?e+km6<KR@*UY6}e~kyw4?ET0gJyTY?-q8A1ag;(~xIv!f$zm*6%t@1zA9fS?L=CxNqGewtoaU<?Q%
BF-;E55F8h#rp2jk4#Qd*4dKKFID|rP3X7ZN@eHt7Mn-uH%dfLJekcmm7EuUcF*XhD%a%uDd;G`wX%#$-40aHpUlOuSbtd9^NY%2
^X|$CXVs8<>pmiRx#2`s5XM777!GMeh^iuH@%4_6HcRKD7qKp+*NqfrGDw;*rNh68+m5$F>E-G;)Cdlrgt>sgj(gHceEz?jRA~d@
_>l$-b$|)W(^FzO6E`w+hNr<)a?PRDkq-`m$lKjxNz+3i62#Jn3bwY^uP4it;@~!zZ1r>Q5;|fQCYgPaZ4*7$;v%Rh*_q!S7e9fb
d4s0Qu2~wa8`}uLfa<xwqw1W8-_`469JqMk{c4{LQKp1=Y-1aedZ|VW9*a!K(zR1&pfEsg&k)=dLihAwKt7|XR9AnE)4%yr)`w^g
{tuGIC2O0woTBqZx>Ws{6`*R}?hO*ck6iHv-}Eh6EFqOisbv^Wny21E9cT)f>%cD(V{*d<??`x&hG*zWyn1%DWo2orjo)6;aQ?pG
;`%m${g<~QApUVvalFKx%8XX(_hgxXi|Ec;yOB8oOyJ6`>${GCR9h<OU2Ue`M`HWE=0u9pg>fHm5&*JQ_oFMcviwl73)`oGPYJNX
WqdUIrL{lRH4dTOnPh9o2YL8W029R)RrzLuFB@mE$vh$kr2=`P#W?#?=85GJe;x5J4(ES4TG4gS(g_SW(Pfp~(@27Y9#|ZbNzP@x
>6x#!%|m<F8k9~YZ|@tOOaD*{P*#@I7(p6j>I$g7!c>9D()TK>9`zI^x_r8V(qn~u*V2kFFn8VH)E)6EZJ%p9)VB7Fp!%+{qO%@#
hOc4YR#t>FCwArfZZnt_ofal>?BZg&H2e$@>fVw1<8!!E#}_Uz($;0DiWeMK-eUITxj)&0c#Yf^L)jY==-5II+gMJom8$Zo9Yppw
=c@bJJ8}RlL<=c&S*BN-6Z|D^luvQ$+%Ai5ZN*++{U-!9V7(Ou$pbS{ray#jm{Qqw_q?4J+-dv*LLQ{4lc%`i7j+g<-@mRID`T4S
9eO|RU`$cno+J7rssk#XZm_5qM$2K&z#UR0tyP^Gw%S2pXChSG^@`O38@Oz{(HDffV=S-Nc?8%AfX!TTO8rV!&s9q+XWEEN-cUXp
3^x16zB=J~Dd?$ey7WpgSuRMr`C3Wl1onzMPYQ9M>;2N#RzqPDKu9pHQN*v7s7vzN6BeTHPcB$EZABtX<>9?-4l7=C42bnqDvLR%
v8BXF<oU3A5gY&~1~2ZZ*nGdorzm__qNNYNla)Xt@Q-bMkfS{L50V=rJ%F$Iy-)3;vfRtI{fh7pohSugI>dIE`;K@Z@nZEF_N)C#
!p0!32e`kj6Z&)QO`eWUrSkfut@qj09(I+HaXX{U;e9K?4KmPK9tmG4*}V`jkljz}q}Gk}3cZy9oed9(aD5gF7WuXnCnSY;U52@g
@~<ETPf~}dwRfey$pE3>J&4_k!?d|`HK>M(ntT;Eh^#5uliypUgrM*aW=9=6ZmCz@s^JQOF{yWVSgoTeS$|m%N$sc_$gFRpwVt|9
9g>kD&Y9w}(UULd_o->82#T16u7pz&)q*Z>&;~o~H-^2+5I395@EJ6zAK%icuU!?M-s!V1@t4mH4}5E!L~0GbC!5m07#e_gw1Ij5
)rAMbbiXG<c#Z9|X_iT+r}lk&+Rkt0i-(IFK;2x2L%ibo)PdP?B!(b;lp~q?oiF)wW|+$#?2*y?gnIn0{MJ1A<d~;wVQ@SkDj!xj
-uPZJQBs4yd%}&;Z)}AV(mLnDCl|wxUP~H)7R|{CY$jyR6I77Jk#4Wj`ny-Vr7IS}fc?1hjail(7xT;TFiO!?y9pSYWK{0BsZ`i;
rv=>#VmUPnHi&4cQmWHCg0uvIPkwe7J;8Pg@ayPtJosfe1cuWK6>~HaNncp7O`FG1V3NXdh5Nj+eWn)^%ID*Z@Tf6$O_^wjl%B4H
>~3&aVz5ic9Oz6hY7^|RTsg@bYQ)1$CPKalbe}}ZFI(}IV1NV2YnJy6qA2rY9efl<vdip=A@_-v77XJ&DLfSXjfPnePo?I-QFAsv
Q)*h}r2;O1P(a>r^;2($^DGfy1|5q@!>)XqcG4Le+mOZw4t6h+Ya=R!p}Wrp($C}Pq$3rA!7r$%v1NG3{U43PqCpCAD-oEAr&XZ$
tqvFgZ6$_E+};V^z5a8CIg3a~iw|f1-Ftc?!bC&>_%PF>&W%K03*uc_SK@)mo0Hp{HWYBClbE65Xr5D5r&muEw^R%Vx-O1e%lem+
6eYYSd8W4)dbtcNgJ7+vnCmyQ7|a_@8wSZpV(-LQ+xU_up-L+NBanorg0daE1b3E1Fl)qLb`cGHPNX*QF3l)ZUuzf}k5BjyPoxuD
mz^E6>hNJ~h~Y=%oPwqPd{z3!#p&^wQQ8}{_T5v?4ynga%^L1lxZq?MHYMgQU%<q5<c_6A6Dj;rog0iT1cgjVReC5TO_gCq&($YU
;u&kYcr)hOro^%tO6?GE7jop8A;E#dhaGtQ6u7WeOagJb-m-D>E_#Z*nJze}J5_os7a(f2fjUaEkdApzvXnom=2zX;c0D3_uHbMo
yW#%rNL#r+U8BiDB)>ALmV`l$R;OJVUyeuC@FXY%;Ss$-HuwFYT?KmpZfS9f5_FOPGhrg7b>kwKs#Xi|PO_ab2yQ|@0Xd=gE>)*E
*@MG}%gp)#cUd=WM%Zvyu@ea*n?^T9k7cwGlAX#)xFAc@In;dF3a5NfFBj38U_p%~xZ=zzX248OwCafA8h>Xunenjy>cx)W5jMI8
b8RfAQ-iA+-uvhZ!b6gz^lgIs5npV5FWxPZDyo`3E0L|0FkiD;kaynm94J0{`#_`w?V^Ioa-|x*oh2!Pr#z}xt4MzzocrosIZbwh
MECqv%v@%Wqy=7OSpx}$gWU`CV#1KDHqU3{z;HBZftErWJwH#>@>$Oy&dOkr9WjguN%^K^-&CfN+f;WB;s3dRS_uz@3EHML)?~Gc
K?};R<9|cimacNc7LJqQ0#``v5K!Wokowr{<Cqoizk4-H^n49WdraQlQ5Qv?{9Hir!*>!tI!F#rI=g~tyHmKv{e;sn%?pE=KPpso
sr`I)w2a#h5phjK@vCvLK5{2EPtRX+RFo<TO8Iy;AZ}=2Vmw6SOyBn<H3ZStvMhl(knICH6r?G$y|wPqh3G`9JV^f;U|cCZ<-|9N
j5y<j8BIhBXK)Kspq%vV^qQ3%zeHOyj(c;*fJF<A%hJr8X6GDuEv{<y;J{IZm|^5GIN+%g<;-^IipHNQ7TAzm=t3r-{PlVl{Y-8a
GKHUo%E<FHvnT6gbHDYio78aZC0E-Kwg#eyO?IP@t)~j4qwVv+2xOgfZQ_(F>9Z^CiKR<kRkgW-o|#<_zFehb+zFcIJjli(&Qdyx
@-U{|wiRlH9%|@lwT*`j|35i_6UpWPB!K{=Ni&w0Vwt^VM!(-m<{2;x-w03teHD$=?R>)=r80R$E#OmR$qF5{i2(imD|%tQ^neep
5q+^lJTSU(jMW41t!Kk;XT~YszfWcxwh2fCJ979E8by5G1tho6Xb=mv8ny=<;|vC<achsSi<L_s<Dz~>G7;3iIwhZ%f+Fzqz|vQf
%qaM86o1zpv^gY$2e!*EUJs;BwpRgzSl&a#1%pl}EoHq+nu)MIkF(^L62X=K-^wmp^~&UV&xmK=tzm!znLGQH1~$7Ae?f}AIbAtr
RIOG{HyT!k>{neqYu0AxHi$nd3%N^Nodyjd{5Pn!@D9Fp$*^2UL>r77%kE8wmMwYxVc!jVliztXI)iTaq%e%0k4)v9PBfUfCKgCH
8kf}g@GXS&>vPek^5fvotCx4wEY-gf?G4)Y71p+C?~+Xdrrb1YDmEP36SClls7y+TQToQJ`<ip)4PcjW`mCwy-l=4cURmF5GAU16
XiS-pwWi1DLqPp4Bkq){Wu5d!^0ap8#mRfYw+{49I?b#NePw8^9r%Av9ej|@)0No_T*c-LqO)j7cL{b)CO7-!tzRcjS(krJ!@gU9
iZ0w~wXxb|Ocf%);EsV^tB^-4>@vVPO0pm72%7d~dgGKL&hF8j-Oqe6y36`xKxtN*e4L6y2}fQ7I8K}J&KqjWlX+deaqn)VW1+5D
dLBPS2W>p)-I0`H+9(*g+IR;^8>#FuTIcs&NXbKcsPpU}&_sYLuBmYGnG_u7)vvx7A-_}nGT!Nuk4Mi|cJt~7_tDG`#sLnA)`U8=
4th~;WP)-Bna`4HmdLHkF+9{auREOwR%Z4<tT51)1Bb4_zYL^QwBP|X&m6d;GlaG|$6sA`!deEaHfhj6LQ6s5&CkztXr7Lz5)kh8
(C-&0;t~<09B@&uI+=ERn*y9VP61(oTEyoQo3Dqv0vm%SaC};<1|GYnG7U6)ezK>%h{&ih2YIIKV8}u2(h(mG;Vqo&Grc#-)!E54
fl_uH`I8zXQ?xkdPSYk7PU8`*T-VSeOwswV;v?$)fzHu%wR6mkD(b@_UNFoC9y5RGBn1dDwK=M7W?Sx0cq2=O#uZ42Mmr#3WGnPl
DuDKZ9gbaAWfBq+)VK<t4WTo{kgAUvu$E)J!|+>`%t`~u>sC_)K|3{cTjTe$0TovY<Q7Pwg&Y6!G^%|tnoR4M?*v1sDWiXZ%4~`2
f)-tC_O7d|i$2yYMKIvOA0f+O(qW&#)0Py|KKquzkPS%|Qbio0!cpr+TMxl^Bz~wd;(?WUZY=azR4q|t)0;~&u7M69qj2_e*j~E*
-)2dOcgTrCI$qqQQl$N;V(P!JOZbgCbMpRcPTaw49vOYU<reEFfYsvO3m)g_xLqK!x+wnd{q3qLxhy^Qvmc2J;#JcGRy7w>a_S#n
ltP)?to0<{zjFfhYOf*N;`)!wC(mt5loaqlsVyYb4W}{OA54Ejku2HVL1`{)TVaOp;Xs+NjzfmPSy2hm(6Rv&JvRK6A5*Ux*z9$w
CaTCvw{)U}J!loSBrb{&CWm!vEW)LDcL#2lXgNv5v}-VQ-(Olk#(UqfhY3t&_NPup9{1KRWciX{AP6Xu!D=-|xBZx`9nsl)kHMCz
g(Do@kbyGlfcklyHTclh(~BRavWL}akTCYx9-#;CJx7V=1Z5W_WXHDn(2gESTFcx$=d~tGkOISBsBkscue(W}8D`?F;}WXAwyzM)
^QoXvgp?8Rc%U+3hyW<*MzU?*T+YUL)NALT2@*f&CS73C`&HCHwY?fQY%RNU>x5vz92NPtogu*ZVzp+`ugV_bo`F<}HS>y5c+C~@
T}**i3mh}LnE~K+{!+G7Qnr5v7%7$dYTxqK*9$vqha5|0E0n$e1xVbC?dM!dyYwv9`ChENua!g$w>8&+_i3BYYW|V0h$D-f?eqZ9
4X$-MqkkcFhx(qMe4IP+7s2n8C{z)<I@=9Uh4+iJ_DbndL@feE!^63(ZkuqkH1UeWQV;osebpyUwd%}74tBJi(I&ilRx7bD%Ni2o
!q%Hw*0Z(K(_x=yAhRm`))}RWWGiQti`78iDyw~`T+xL9v7nK*l3vrq5KVsW7p9UuS??n}#S2gSY0lD)+-Zlg!&&iOEz}1c0C=AY
lFPxX0AKh5Q1(hS*&k^`Dk_M{rN`i)j?@=pt?n>y{!SSKP!0&O@x~?d{}?p8*qnfMZ)<rIpIx(1U;>b1IJ4@JyJLIz=9}P-fOEfg
8YB2dG;ar3URa9IIdm+Uc>s0>;cRHIi_3>RREV$%%V0LELT|<RM<B20B=p)h9tNJi9I-w_<R|o82MZw8*ObYMLC>hEMQwh4l^rA?
GyL)JH;&vN$lGbM52Yw%!0WN(J`e^aJ~6yGX%I+pW33)LSfS{~kxn4PVIwK)g!7F0DJjYJ7fa^oSaueGUqWU3p*)ohT1Dx4_%!Bh
^DdYEW`BWtmKt#0C$`y(rC~n2>FE*nzm&Qvqdiz9n=-i@<)@t;2ZiU?mnvu!P^bOcgrvE^ucA7q3cGQqby;Kc@1Vkq<(^MP@;*Cb
1m31&)XNkXp47-%>1T8Ba*8telC4x;XvO~Uncv%gPp<prVTx4f4P_M?Hte3>q~KjpLShDR@4F~RBX5K8+ZNivfZy)3U=le%kR658
YY;kHKlXhVS8C8R=QOuj-?1Byc*^{!utv;99OGS5z~BG<mInUO;q~Mg4EOUq;l~;+ZTboP!1^~iVV+nM)s~HWp08K?I5o}=I5sH&
)!5vN=h;s%UX+Zcz4b+-yb*0H1CNUGS7qf*3Rp6j?JOEpy{CMArK)ZMem3*puC?><WD%&5Mm*HTF#O8zWRv0LkQQQs0}Bw(rz`vy
U;M40bp>eEqEc&pr9f2~bxj9RC<}+rdnn^X)QttGw2QLU;)~92cq%?ubiJe{U6GkJ`JdQ9YyO5XTe7FV3s3SLZKY!obF!0Ky^2&C
srUt<S^fWj%8k}*-AuoYnqY`CXwlC!V)U8y=vTl8WAmQ-?0@{=LqynTqEIAo#}NQFrWl2p5vxYg{Z69~+#v2Mwi}Ah*nB?_bV|d?
(`bH&qtw!06A6gGyLYqIWUeg2yM$gF3cMZpq)&s#xUcHS&>#1_Sd(#Uz(1K5#xt;&!*u~#5r{oU9&jUC&Zw7DQ-hlC;L<+*R2C<|
*3(F+CP15p@2`|bKXV_>fydO_V4oC|(ER0ib>wL;?XgJ<c#p!|lgj{`GslfH;FoE^er9(nXP4yhJxEw}1YfZTc+{kTG*pJzgSAUZ
*&sFx@4Y%&eRg<omTz>AV6<r3Nz75Ek{FJ?*IPq(9YBi~lg@Vi4c?Sx<ERojovafBo`l<zSP06rinf1gdQf{b5Jo=l+BR4xv7dKN
8_rg8F{lGK%i;Oovg3_!Mz<?;%!@(2+`Hdsw*U!zrw1VQ-In1{t*UU0iACB5dBE8#$otkuN@u`oX^jZk#QrFeC380Qh<{T2#7U9(
CTiLRLdgbcVbyqz6gO88PFH$!89y>{8E@CB_w@P>R^9Yk9utIl6{dpJN=eSa^9IKs;l`kuu_(S5DUj~a^dnkiljco)srtA1{F1rz
BB~9MXW|F~^dYf^iRJlydt&zZe?_rFZp_Y-peYBcLgN`<y0FK)@vZUSJ`=6DtkM)Bvlq#KIGr283CN%HI8(~F*G~NsyxC`nxT-Fk
Yz)zy<_b;A&%Ki57|5Y5=THxOB?EJ=7nTh+EaGXyV%#g+6u1dwNR+@q^uSAAL>qeJxU5d?4+Yr8^@=(-sKc*YV06OY+_44^gIYOW
hxam?F$YBMAt~s3UmJ)oSeY-EhN+9!x~PY}Sy$}7WvKx&u84w%iRcto-ja#xN5PLMvk8`YJf$%YO_uN>QE79z^?N~m!2_$3S#g=~
%p=@$I7O|YE7t00cYH=jOn&zYe-Pn&rHi}$;0DDUv67=eBXR?T&Rp;g`CVD&(H{0C6@f_RV!H0%QBO@;YqGpjNx!DFP^wHp&{qM|
?4Z)Vy!h{)V6mFPFgAq-bDdDPxP7#iwotdEgLc6Z&MsT9ldjyjwJ)}1OtVYD(>FWF;x?n2+G@aJ)Z+zORm8YY&iZ=dwBJ{bgtOnh
7KNfyWq@LyFnb|ilLZJ0>%c2--jL72*VHt*3j%mkFwjw$dZ&COJ(qvUndC~$X`)h3PGr7N%d2$>uUN7}#!Da)Lq3`iO{B5JbJyx&
D|ealHlqrNxG%3!JTuqBA;a|0<`Ap+_#@$ncDl(H5u=X+BR>}UR&LH0`9p+=oJNwKL^{x*h@Ee3v+p-}>L*s^!u;rB(aUT<9sQA_
erh?bHHx2C9Fuy>?~fqPQYi$5mLy}-S;-5iX(Vm69A$hcOp3qq#1b_Mk(KsvX`!QlTqcBq8)a1`xl6<b6eYOE<F0p8&whmGSaEI#
o|N|9s0L=37(lIfXr&#%{Jk3aDsTyF#k)v>z8)R2&xRsWExBR6&5oO5_C$w3woydRB@T-IvypnH%`+e$DtkD~E~<WS^c0zn^l`$r
oGgL<R_Oaiea;tPA(y`m$<d;23K+IVdCVWX8?TSP)4FwbFHc1?7s(eKiF~0iIgu1UG+qy7oyNmXp=c_${j+c5OtEcS7CD6wrY&Fz
!|uGV(5JZFo9cQYR<#px&z@WYUAc?j2$Z85UqIuR;V+v|JS7i^-V5*36ocZKD*M1}=APz1YJ*b73Q*Kf3fzY)B@lwVdQWArMH#*1
DUJP$i~oR`+<B?H>oO4%<hIV4Wb?H&#aO+wRQR4nOBCBv0EZ(LuKB~7`4DgrSQa&-2EZI~=HR}P-u)`n@nTbV{?-!onPY7tOFK<N
Xg`}mX{JDsX>KLA>tmnKQOM9M=QPxrGVqXYS>V<;em<xcJbIivo*LhUfu-LFQs}Zk`57fGl6>uR_oTis0pckvp~!1V<`0?)mz;$K
_bfTfYuUVA3Qwx3nQBJ0x=K#8J0$xX_cEq1fz`oO$SSQCyH`n=>Orwv;!pQwe|Gz3UmfW3(!@vAoRXH$Ss?8YK8YFwI5i6I%7K=m
lH1ax?#LR;W-eK~iOc@RG+t!ouI2C+O1)L!_CHENefpsT_$Ld1z)&xmiK=AJ4=t%LwwxT#?7(CKK(Ps1{6{nGLS?5KsEAbFE7v`!
wVyZ)<GV&#-AE2}DF0BZj6_LHzifA2I%tAB)Ym!+kUxCHyc<<@U+e=weU;SQ=Pr@IVV@rJGZIuP=R`(3uK%hr{}>#%X)+}Ywkq4*
E!jp6`d$y7;kCuB1DtIvK0?X4H5KmVuz#0QB_d(bbft4lvV8Zd1vm;X!Of<8a9Z!v=elNX*MqG}%`t_IIRf_Z|BanAa{sth-GFm{
JCsx8{~f{CPe0_?tjP2%CzC1J+wNKIRVl)}!*Zu#)s6GqVy80XTPZK()mxl+wd!yQPKr24oOhiA7{vAXEc;-?7up<bImyLshKq}O
T;KNg>igiTlmd>cSg-+Nue0$?UygwfXH|704AlnOWkC@9e0Y5v(=>xEhc>nnAXXqTw#KMw(E>dpqbTETRxSzoZmT5gv~AQIdiXLB
12~bAwm#aY=C#D5pKXcwA~D*}$v{^oC>Y<vHvK()BHSpQ>?uFPdgJZtX-oWj94AIzcB3Ua+`pY|3!d!y1*1X7c14TjI>7M0vq?LS
yVit{mgyA#nc&3_;L<2FIzVk7H5W<p%5=;RJZ^k$UtT^>>cfn{^F92c9TVtR@a2hB#e{8tp=rz;aF%Y8DWfuf*?a4Tx#$#BD5Ytg
%SwAC<%yUjihEf?tnKQyZ={sMjrTIdbjH0u82ic%pH|lKFCP$?#+doo#^V?m*9<Ls)ABk$5@BdGIuRDJIH?aVHAP(7OD4IiftSb}
z$0cM)N(_V6&$to0Yi9?xacCe1JK;G)zCInI|R5S{y#&@ER8MO&L;=WZEVLf++!x6)r!ZWTI)xj`_>M6gkU)v_SuAHAoEJHV$OWD
m@TYIZi+t6)hxa)ex*#m%2g{hj`yUz8yM=*-DDXu<b62pezPlS!EdE1SSn0XnaqRz*NPd=!)H6^@Sto;U+3Q=Z<6-ap!#;HScQ{}
hBUSEXsk~!{L+Y`Z>TpI1N&l2New#)z34lLDW?-VYrwFYH9A(dR{!ydSICv}qXCGbh41j9;M+?)q<!Dby1`b?ntip&xm<EiNW9_j
P=BNiR^nlgTJD$oIT{y61RU)>5Umps_{JhPHLrl{QKZlZmtWq4HX|J5)hPnC+J2<1E@eE=1in^9649&Qn_R<<_v;!v536>^AYHe8
sbyEoYY=-ti5@RSdD8zC?a)h}sjCn9trU--5hUbHp53*^WxB)w0C{=G>rrt>-eNC@c7T$!SaW1VeeWPM(-#Sv4V?(}g;nG}9FVHt
cVxLK!=Ipj(I3*~XTur#QdRF@QiFjl=jE4F=l=Q%o-zy+9e|*j#<T9-+&e0g>|eB3M?fQ*5BBUf4xt}iZm7HjDzKDhpF6f`XZL=v
DjNZqyYzz&ppgL+BeZQ_!6_Z0s2B!fM3@?b++0zZyH_V-b2DwIFwTT4+h883qS3q5H`!-&;6GXeKmf)Y$ODXIA;vXio0YMBd4yGD
KPCI1p%l}d6T5I_WQ{9>hz<{nUhS!e9Uh9EbFRx*xoRk(;nnk0XP3~a$F)!E|L_^_Q1hzrY3sPbFtV2Qr#<lvp<foF{<QshFjO?9
&4D}6XO5^%f^;DVDN^!GyF(~vho=M3!lav4=YO0R*WdVUM__`k;-XgBI{ms_44pQY`3UDTYWD|FL9zcBqS`0~%i27L=&`MepTTmA
0g9Fzq<?)h#Ec3URbUST^C2nITs36taxU*Die6a6=Y$+gIg|`Q{D#S;hf-l}R`2O#7g!e)aNN^9eSZ*dH6YhyqY4sNOXqvSdvMh=
sYA@>TMcVGRk&&y+=IY(oS1<`QB)qwDzW=GCcF}jT0R<hZy2wFh^0uW806{~RO)lIYtB-HB8wpXj_5P<m=l+=O+C*rff<}ga2ia6
l$7`wY$FV7l?|hxP_AgnUcf!AGeWOdsmb#G?oymQVNBrWEDO4K15)f0rT#JFDKCqJpEQ4QAV^pYJhh2{W_04NyXmE6>h{dpgIkzr
@_74X;|C}G>Em@yF}kIuy>WTnvW%0C5|qK|WEyy-0(x*cHB`(;E#6%~wD-Lg;zf&y1|4x$>6@8QKbRS+4^=*qzM(6s3`Ar3@U2L&
)wm_@;FNB^45DWigkh7_vY0>D+9h55x%P3yOS=_TW5H3$^@79EY3mHFMw_^lr|T^<S!1Vv3wDb#(3^ev%6W|u3~=+TsT&IFI~^6#
%g==^>%Tgz7uWxdt5^arn1?JFnz9-XTRrS<=T|vs$Ls=9c^3=Y+n$fP!h~Bhe7UYa5n!G60!)mevv>Yz@keox&p@4ZhbS2f<rukw
wp`O<FqLqI2~Q!|793eV{9AAJw03RR0^sBWI1$aV86pf3!w)ePw(oB)Y)Y?gCJ^{0_aD*(MomU*{rwKb^0qt`q=LiQ7avZ!tZ=0J
h&Jh7oW3pzwUnT;&>cn?J!T6qwsQ8*fQMCL6h6IT)mBouwl6U6=fZ8tVE6eTrbw<8E|<yYrTET(j#h^C#<b_OUWLqb5jZ_*v&abr
If9Tj3|vUYw<K|&{}2l3ONxLj94aJ3S9xuh3_P%V>BEJOSulW8Ag@+PH|?@4W2T*qEy`xYK0_F&d9-41Bgwru^V$Bp9KQaiX7NH+
3^dN;v0L74Co}}Q_8kqwPRCJ_j=PV6KewF?FzECE?&)BadX;<W&mIdpZ$=-L(W+MkVnY?D+xl$rO!ktFw%6$Rk>TFy_+23$0u2M$
;$TzUkUlCvXK}QeD2T9km)t|&;2_8J;Rq5~!5j_s5>Lm$<{-)7hCnqUZr@+lLum4QV_0XBxI8g8Y-aMhQfw}PDMe9k5?pJ`md5Q6
w=jcRL~@m1P>z}O^~^TC=U-IR!lsVX87a=wu0TGS3J?HR`-ByW^_=PU9H^EJWAaF;D+|D1Eh}fhU-Z$VpSk0=;t5AIkRmTcNn+Jz
whAB`a#P?(5jV;If?HvLM}Zwb_?TjIU?n2~zEyDeYAQQ@(C3;uOf^0w;8tM~L3OrBJLc}m_$<o30uR^#Wee^(UP$ZWannyf62$RI
i;?=QGTIocPcVfGavCrsLGdw~u2n#(g~$|QFJ_#EDp{T9{ifc`!qq#bvdTEDZvfJwT3WHo8IbdFe5suXK66#qDJwpJk^J0*JckMZ
uU`05$!^c94uD2cch(*8d|FeibRu>mE}_Oy;FS<SbXU^gf%#?0kEGUGjhx3vTEPxRX9ywPBHsYGW2~o-LUV#JB<NV2?I#jswKt!@
_w)qlz&gYO7fV|cDT*-<40o)!?n(grDcUe3>H-K|08Qfr^RME_f{g`X^fDs5CuO|ej)upf_(*-h)ZMzTog0n-J-{P95bcg4Jz&z$
gG&b{Pz85*zEb^amm%Z$pg%_O+^}p)Tfa>y<<34R4SePnOii|gydLO4!4BFqPG1fmo@&HWj=+Z!zGm@^J*1?!jdi5TKRP>0Ns%K?
Mh_a<R`id0-drk>VPI6<YdO$q_IP<J3_~%?(j12~Uwu}rT#$M8q4ZknV+Y3kab4w)-2cyR%krZ@NgWKT-Mgd4O?Nes#@~QV22xm5
kpf`5>ITdSvs-=O+mx*xv5?q38LfU_(^DA*Mu)Q}4eS|OlCli#xeZtqrbqwyiWzTN`>Zp>Z3A(P9dB-t?4&q#Ni+iGg^1XIGLp_2
qtGN_3_dQ9PMTp#Bj1VkcmRR;kVkeVs0@4vy(GStpkqXkzE{c~S7=|~GC!?7w~_=SLOpBtCey`!m}FnPj4n->#sCxXFE^^0mcC>^
Pq(~S{{tQ?acOh17>S|dn^aF>ctx*ePww#9*Hxc?wteC}C$TMfh>_KY!XxQ54lxuR@KBbwhzj=BJvKSjKF2ed>t`LDth5fx1s#WQ
lOTjr80UyD(lTCIedNOx=v-1zd8aIbT#x}_lQ@G#B_Uo_E^rJ`-BbsS>l}uZRl-2wP3U}vE;ggClbZ@Z5nD!nImVaVelRZ@n|L$a
P0NY)oed9`=x7c-Mz%2BEj1!i9=f(zNI@<2su@<-!&5osJtK8x!e+9WpD3<I=?-82|NJbO+m|3(;4WKwaa#7sHUSiQKK4$y4CiYu
w-jprX!xQ)_yt5rxIZoT4n~(5bi-r3L<Ym4poQpEq)3WS)oYoJUyBp(e#X;#?5x+y;}y<SQfncqzfkHyVdMICTX(m5d5@3t?h-(U
z-^N{j6I94t;WnP_nh<TJ)u>uMeGmv$fakYtsn}ANY@r8tgva)rf61uX=8p!YUn>#B@RKBodk2|`X_Ecx@}tw{&uN(Q4)J6zmT`e
Y^E_!pE0}pEb|tC3>0J@G!Uc#c-;$E9fI7DJmQ3>tmfISB9a+?mjxxI+thKM<cs`a0w<kZymq;H^5?q8s|&Od9Jg_QF>WEcl17uM
Pi<xpq$(V?M)4quR+XuWQT$Ypk`?;;9?F;&@tuZ<_Xx2tXhY&@vgj#_yq`QO4-5D|jcXY-Uix(|k4n%AZGe3Y(<2)ZJt_0;*$#hi
Cb!THV7Y)&z9(aNUNNOm=F&`*_DVE44vFaz{s<tUsTKSUfdE8uy~jB_DY0V19RS4FswSL*u>uxB5;}czlbg!R7BpnohV3`@`a<N9
p2aRS8skKj3r5d2r4A4$jhd|4RsA?Afom~_N*$mjiwH<>U^?aFS7~4wz&lDVbd`+4`}e=%68iU>jrcG~T90JDjoEdTNO|4ClJ%dw
y9>EjblhmNDNI@j%)w`}`mtVnJJZ#pW=gxESrJEXJ-+bc^h;Rr1>zfy^s9gk^B>7%RZzB<cL$3wtSqW_6;Iw<8S4Y}8?yj2Y)R36
b0u*(_vHS<%#a6l_n)G`E7<sm`GDQm6;_FtQO;-DSti|-ddgg7bu(L8%J4^XGWTj()4r-zr2ueE4ge5=F1xem^}XkGXx5tw*2m!M
BHxvF*WPQ4(8I1gYA#rRi=HBeb~)Z$FJ&3-hc}kQUem{r63<)CvNtrlIa5^vhZ0Cz*hyk#SGuXfrkR4bRM30AD^3Lxx5jA*`>TKZ
CrA<w<WfX=eng)0W3Xc?)&WX=!>Vk|<^YNIAY@ul-IE?2dZ>cQ|9&A~llry@f>EXySC|@;4E*!n%6#FVd$dydUF@`sryEj_#Sq71
ya~Wxv%hXSfY#V=K0eCu$-oc+3s?)K27lr#9Ly{sA5e^fh=BWzMyYvFi0nyoq2wnHw}vh2K>tAUjk8;tY<<?|*UKKra1@<#@rxy_
*pD}*+5S68ZzP$~ZJaH%)^IIt*9ZE#bhse*GtgW)Iuy3`%-@nida8;M&=xnat0PIFsbMTLJm_e9`Se|bN;h*Kx<JcfkE(r#mBiVU
qGycqs_(=zkv<Ns&KK{nZu%)YE31;*w(uaO)lrx8f$!-eC-h~y?-cU0-dqk;B-~8yWAcCOT43Eq`ADh#fsMKaMJ~hTN3}|$BrryB
TPW^^Wa_-_`{yRca1@yQ6QaBA8&SzGaQgElL<avWs4Z2T9wvMlP&z``?IF6X8UCS1u!%>UVFL;Tf-d<Zx1i8K4OD;)z*)6|@M&`=
EWQs=ru@h|x|g?61tk@)j6HD7T{!cW1dWmT+x5Q;yQx-&9BJhK-uL&gU#6TY6@GY!aF4eN4poS<KM-SqKT!**VRBHp${N$w3aX)=
_0cXSkhLI;Q>T56q20O_7LHNK0I+{0?~IHFMOZ^P{y0cuGZJ>n)ro-o&%e_7bI&_g?z(WXWosJZr93`Hk?6lRYNvsr-*53&5{kRj
vl)!yYscJggPq@u%Rcj_)8k<MFsSWg*@W&RSY3g%j`1c7ml8oz;J4VR6^;6mX^JDemsKTqCFLXeHc)~w=oMl@hdOAWebVOaj^68-
>#&gXcVxb&eD=X(+w_kZF~c1cdTDk>SgdOH&eC{+@0o-%mKC?k?9#wdW1z47b?p}*p0#anV5x(y)T3@$;cGqb8H!QxzMAZ&wDSKo
rF3n@X{Y~>OLfdH&OEw_!w(Db!{_YL52Sb)n?>2uv;8y7tA9+xW*Jmj>o%T_b!wui2IDDyQohIf+DWOy5t+CXZzK*u4J4zG@mIe-
q=wgwx3AuqWx^oww{_xInS>JxRe?59)l{_l*1}U(k6mCLMD=*>l>E)eP!v8|AR8LhAKpU?v3({pa)a&Xq<M#%i^PqRgoc1BbI#<O
ood+#kaS>J%Ni(6OZQwQXo1HXxIBc#0$Fe27Xm=i(==ky3QW7~-_W~&vuAuNZ**1|6l)jC&vpN<D%>QAZUg>cE7-VfVFUN@kYnKp
0tWuP=Z}N*JQ<(=8QW~)cZet*Qb5N11v%b6Zw|wWIL!VH^;3N8gcY`{Z~AbMrn<fi!a$N=SM{XmL*Prd^RbhOE|Z>#j{B}{Fah9_
$V=eLplP%Y{C+%{!$D%YF=Rf1840$lWznZ;C4Yk?em-;k!x-Z8BU6_TrNIymsoK}$mCh|7;m~O66!=F_Uj6|i%`QNGP>ys#8e_5d
ASr_@@982jv^T_Y@$GnSIUK=PvQ=W|DZP!=Fx-dVi7)QXj`zdN%t-Hv8foAz9i37DP__?$=P(#jPRs1G-bB%mg*>3+_@AAMSKVYC
@*Yl5-i8PE4syqJGW5T-$SJ(Bd0B{!$Z2haBFmn!Jf1=CJ*)+`2T>d<t){m-332q2r-elDeJcyg_mF{6&Q>@6pVdOy_ALoz%al6>
6D)N8_l;vWjPzm5-8=t$Ql4O%shAG;$N5Vfth-2rckUU(qg{DiC>Gy`K;d{%3bY(C*?zR1;RPk)h<-ZA)g8P@(v62<nEz)f?Kx;O
2PcGMTLE!65E8OfdMRZE*{PT2*!N{G##)1)5b^T1w!|Z41i-NCy!7Qj2J`Xh00O*N=2c|~=QBFF2|Joj-+U=7RiLoFQ72NH8k3hv
wA!-2hruQWdI{#U7sE~jbvM+{<3+)O_Kg}Z1%3!-U-FEh9c*`;JG*QVWW%+NruE&U<Qb#j<-JUbh4_mvC9I+p?ONIyYb^sA?sKxq
R{>UfP7S81gDeK$IF)}p)k?8Io{Wbx3%6X}f-S~QhKtHzy;;OaS3ojdpeWdW$y(JPTLN9hl4B4Oc)*$V_j*DK#(rM8jgQ-4lDOQd
8iT<Zx(ZE;1H`>m-Pa*IDLp$Wv%0*DB8?Wu5^j1^gEf}8%E?P*VZtnIvTgc0FmKKDhj2D8o9x~JO!>JX6$eSX#l;rKMKevVuap$K
qf<1ZFY+3pi%RUo??oWKfmhes0sZ*dyDc{(j&Ogr<FS1sq1L7e5oln=@JREBiHMH!)%9zyr!#hOw&xup_jQI+0&=xyAW#i0<a+>%
H){n$1I7dKqzk`Q3$I_)-6Q*(ZojFzl=ZzG)*wTND1jOCNW~@Qx*MQld2#jH{WI@q9!4==7PIff0ay7zbh0<Tlz+u}M_`#e?SZXw
q9D6G8Z$V_ZvwuV;P(WGFM8MST$Pdq>MWyU&(3&o{b(l<ULEsGzfKB*1y$0O2E?%U*1jbO-fy^|iF&iytbE)rdz7`oq#j@8$=}0z
0($glK+*o!Y&+Gj53S~z*8$|JMdUJmPZ6|wRL|11AIVLB>WIyQsjMJVEetr}8z7kbBN{0fH)XZmitau&ej#VA<R5O*WY$T_h_->P
DvYyfVGYRD!zRs|+q@U;Zma&Do_Hedbz^f~h-)4O8~|LtEp{SV;}leDebUs1<2WW0TX^g@kNt3zaPM;V3q!ytw;MY>KdGOo68;cB
0YblODQA?ERL|Y7(Vn$N*jU4;M?-?3j?l&R#|(jV$#V>Znl+p_&L(y%Q=j~ezLiub%8fRG3J=JAAGy7lTC+C?I_%b5qJgoLvw4XP
5CEle(f23-xPpTGo0j0u(_h(HisAMjjxyo#XhR4w6#@aGH|&x5tugFvZRG^1#qTL+1bJv}+7@>+TxikF3Et^ugWwXeZh-Asd}kzz
zTo=DXHe$yZ_Pj+n=__)Qg+B%@h<=Cf(wMpAOf9WID*Jlj|8?By)JYCv3S6e1amHCcC%}BxMZQJXE*Qo(8jlXMK5ynRqbIhl6@hH
euKG?`2(B0Zc6Ul|G0|{VX#ypaon9GjIUwdBCUyIzowD5NVuU=j7VC5pT2DOHOL{`rh28>`rFNnEvRN)Z|X@hB{P?hiqJ?0uA=Mh
)1;x<%@3q{wT~L&oMhMgXo9qX3od-Q>{1>K<T|dV#os7r+VZmJrg_KIaEe6DrqrX7ewY%TCX@2@D?ja4XQ*yJ;@)^0a!XuNs;VGq
0V=7WpB<trlvuN24-gZD5hoo@by$`g#D$zFdP`6K?1n(pHvbtidT15@b%vHe<gp9tA!mfM4&a-tkJl8AbBT1wGD=<HH{lSvaxIGq
eS0BIS47QX!Fhm>Ql|Tt)XShj$VAn5A|w8mq`(+55tFA)1DH74shN??YU5cP3y4lgFs15|ULkYSF?l`;${Y2P=&dKQW7-)UIs{i-
JU9fzhwgt)l{hQkdi%DlQK17l-X@Y)=6TE-JDMKU0)3l1og9X>K;{(JkcM}_#Q)98I!eRMMOA2dUWN)yhZTTy;vvs*{_7i~z^oBe
1M=7?M4S1}+Isfoo$0auuPH~{KKrh(XsYQh2|(Ss9X+`BIITg&h17A3hwe_Zf<y6+57hJrJ%9H;`b%Vz9)bV?I_~GHnE?YXUCmOH
(odP9XiNd;4STWbT$xTr0eh;uO0`LV&b66Wp>;o?6@!Gae<x)GTlIh>{6=np(y9qL_>gZ^*>o3H)aF%fUoKxopu_8$$aYACbP@JC
opPUfh~EZlIcUdI#K4cnH9(Nk%)2tFIRtK)-j6ABq9sHRdnnqw$~WuJFzIr6iJ%c&T+ykKC=Z;59@b3Vl0eQkr3TlJopF!fXRmS5
myQH(tU9C0nQAJ(InrhHd=)-~>z4?4U5@La>o6BI^=E1-%1zBNvEV8?!HK(dxKlIRZq@jSOYlmFC_C!LMDjkZ>bJLQ`t&NWZR3D)
p#nHLa!)CrR{eP4vN17(l8IG)+@mlr#~^ch?fTzv(?HZWt^Z-Ea1OpY2zXrUM)s<xg?z<bYYVwOl~8XROy%b`7<B6<*6vA}B@Xo8
38k$8%;CD7N(=r%$f`~efU2;_I~n<_1t}?t7HqzySYg3vj9ktApE8!rs~Y^#O9Ai<92#(Q&jn`?BpldaC8=(-qT-Q6CpAjZ05Rmp
b8+jTJ;1_52TF>n-&P!uez+n`);dA-vZ5#7aMfOMnS|_Y<C~@-)I#8KY%qe+{)}MgJ&K<-Z(Fk+2I-|#PG-z=M9b1)ZZ%J{Ir)qr
x4WAHP1OBB@x3Ax{hQeKlBPptsK?~3@ZcY-;MyFp4G|k2QK%H$a_Xc4*AI7qH8D~FmWI3$t>UmXus72Dj=m5T-p-qU5Xt<b@0lgD
+hg!GxV)1>q4$dvsJ-)A#*nL(DD}+`G_YZttNui9xnf>z5=DT8h#!4I-IR4nlf}8EMpr#O9O1(DRO~ekhcR?)M)dhkpH|}s?lPzm
u3gD}djFSf=#=GD2uj(`=>iS}Ep;FzRjiIMou<m#*yGA&oBjPuuMU|llwO{)p~Jr~7n#s)>ik#%afoN4svQmY=YzPZH&$%XkNM}(
c9IS21$>?I6US>L%C=X{m+hVEQeP}t{g(v)o8YYGMxIQ6onR~OMQPyg+jaPcTV8JN+=Z2hZ199F9&Bn?WcWBmDQkgxxa-uQ@5Z!~
jizy(Vc#4!VTbi6ALGF<U#3otx7T4A#2j&U942GjhtfLGDAMgeSMP{EWRlfOhHm;MGuuZynEc8#o(iv;=Hu80wrFm9#R(gg$J7k;
9QVlQ14#rzg>JW&EX(NPM`N$MBNk;}&4n&_j83ZP>S4>QXfK$Oso2W|s9A%Uu6xxPs?dhs56M>vQgdqm73$ktq-bl9hIhi2lr<y7
tso4<`IHfoMr&*R2;;ta2HrEf>&!FL%J&!d8Bk*RKUX%wdefcA$Tc(1()0uv-pG+hre9o}0WQPCi5Et&?8p(!HSNyX;e_|)rWKa%
dDHQs#FqVp&1mMx_YF?wDkOgJ=CwNqfmD4cJIaj)-Q4XcMAfLOUY=a@8N>uMMm!++nCm+N*77Ek>)X|6U|j4#SmI-Pd$iSwjq7r`
(Q(WK5spI-^QdoTJ&C)gZ7~CQk?b$HhJl%LFUWFX5mkE+3t8WC8&x2he1PISYrG1wHvhHzzk08&C2PTtLPaK`2egh>Xh*=?^EyT+
Xf)l6`=p25kaM+9!2NSb5V=#)?{W_j7)Irv#A<nq5|ZnxaM~zKE-~%eUCiQJCbj#z{Q?T?iQ#=kt@l=r6flW}Cu40C>@;hxf1cE7
P<6D{&WyD~+F=0BYM_w1WS&N1+S7{7NIPNP{pjMe#!!`0vX=(k&J@`a9k)@f`i7}?Sk3flt<rq?(8j>0Xu2swWepDEl>`^@{K6)c
+7Zg^-iitZ@gebpsYH7(uWs6ZEuh8aLG0-i1rhVT%nc(R4$ZPCfE%DTO!laBCQd|%c1E-NbJ(z0hADC#K$8l_F+%^H%GB`XI;s@l
+Xmmn;bEt&i#elJb>xzwcME;uOCjEr(Q~I*m9>esVhGT5h!RVn?Yiui`#v7oQF|P=xOJ?^=esr1*$<~qO(0xd7ReBfH1l8MTi`C_
f0P3jGV)4+K^Ak>aK7Uh-OiG$Lsm?F@m40T_AX14;I&9p{YQwKai}XLgw72SeSj90>odIiMJY*J<6B+=cm8_q8S9tEl+rjK$pQdP
@UnS<H8s=TnN~jj1zM=&H*H_bCsXUL6-{|hu;2KP(lY~>2oHgRY?QCUn9l3z4H(c1%qf)<e8WeuMmS7&aYDmHYiwo>!CMaZodbC{
$^_1nXzQmu$?bbjt(w3(+A~t>1wzBph8vLT)Bs%{g;+=A3w5AD>U-<Hy}MeeYWuG@1V2l-vSfK#;+$ikSJk9M<awNf-$>qq0YcmF
!POew&SlqwlSh&ZPAqyfA4CdoD6JW~5A{A|_lEnJj4_Y&uAWP6xc2}SlyWknKmHy}Z)t=IH*s~DT=zCHI8Bg=@NpxS0j=ZeVs3<Y
iKfdBp-VCTptv9|MKI7sT(oSsJ^G|7`Hn065-{Cozc`v05&JvVO1hFNm`37IqF?xLx$pMwZhk!?577oDJZP7D+;Yt`xDAjgeMa|W
$%%t?SN-<*^AXXovq(RPU<Yv1HQ~2Xm@s{{W(M?=tB}xH15pY8d4NHJn{!#4jzIW?LhY3BbD{h@0s#3-1nA7O*5PvWQMK6gBI2|a
WYumO#89?UI$^rQLkK`LMFf?LV8+6W&8#!6{c9YL*$Yj;>57Y}<q?Qb_-OSn9{()>;`LB~2}0^8;VEC(35)&m;0x<lFyunlS>3qB
8}kI0PX8}M@)@&`4VA|Rylei>Njp;`I6Ous*0>l@vmIi)j>tvXx0IfY?X7IFP0IJUd4m|nh1!D2gHf@*<eh)c!kAH~kI@}Pc}Mz{
ug%H0LfQgb&dmfAXszbqTY&<!^tJ$~VR8ir_0oC<KhJj7#7?|UTcoJ35p8e3L$<qTujfK<xVkjjVe5lwi^5_h6=rKRchCQv!RQmM
W1EM^_%7BwM5Wa#$4nbAg!7jzx}@G$nIA%STtVv%)sf(Zk+@JwTb7v_ehJe?I6Qs+l<Z*$R&>WcU*rkY{?0bpecbo7FQ~ljBzFWb
(hlvrvR2Ri?_b{TjPzu9Geb|%oAbp_wDPGn8B^sQqWlz$1&3FU8`@6YKBRl<&E(3r;a2{H82nYHY3s*v@D(rVv3O1HBPiCQF=xdU
P+HAO8zCTRmb=IH+6U*`BK;3jGm5?8BRJLi&?1-zE9R_>z<Y~L&L;LQzLpd&D;T+x2L?)ya*k~YwC^Gnf<9=UDYv8HRt>O{kZbU{
FEBc+xa=ul7(=1}x^s+EYw0;15{9A?44)wGt0)%-FxvHrnz4>&g$Qs=reaeSbz1kqqaqbWTp98Aa)}r_eRL_9pjXl-+`*IHQLPWQ
!-zXqif4x>n!5-&{*9!&@a@<dvNMo1KpH3rR+SO{exm|}-BCv2yR@O|o)-dNJJifld$BM>JHQsUI*lS!luE=J>fkGaRFLGhN;;NJ
q>)S@0zBsgI^pj>jX*&xJb~fe-Mw_O6LdOlT0}&Z(c#Xut*1Z6_A5`AH&rWiNPKYJ`e9#?ey@KYxD-8^*gp~g`R<V6RS}@-0`h{-
gPYSP=j?|IN)EM{_5rvl3fj<sam^I^@b2p1a8aH1hEuH&i?&&Qs?$S3@x|HAc)$9eQ8Y)b`C5n|$LTr@{mwP63;a-OiHQS=+(C=f
g1snYVBYfu?~s}QUARQizyN1_LzFK%ZK6|i%ON%Kv|k5>Hv_cs|6wbY_*FD-pu5WB(9>9i85-@Jrk=7Cbp@b~54Q~Sd5o(}?5ADb
pkxPdd^+8y=Jxh%>~z)vLsGV61&>)lp|h&f(BDNtlnUPMc+tsq5m&LGIjc<DR%12v8Q}BrF`r7a!SbY~2TH3MO=xu&Gb$y+JTQN(
9bdc{V7R|W)<arT{Po74E)WU!Lq1`%uiT}loz0AS;JZDItd8v`Q-$L(h@)85!@cj__2cb#N9~=M&JOyfEgXsR0_)sJ5(pkbg*ff}
kFJYNZ&7SJnmaP%tFdtvrql_unNM>DumW=8<B+QX#>D{oV)*s4`kp1b7XF<{|6B-=JPL-K6{x{HuGv>^qw*5GDL1Yxf6x`ei)_}h
V|YKpeYZ7YL(|LnP+ZDfrZ6FL8_L<lrLJ*3^v!X#{io=?S|hpIL3zfSZ6O92v8q~Q9I}<55|SNF_xD8q!td@QuIDP-0Q^`~;scSi
`e#2ed;ZY9iDBW#u-T%S5LZ`HEGKRlj<PbmkyU6{Y0rsjsMLdCQpB{Zq6+=lYk@qg0UnyMKXm3@V*hvT&8V!?Zx8fq6y>to#-|Iq
EkL}7aGT>`b;&whCNJZr;He#EEoN6#{nbOqxLtJYCf;0VaWbg3I>A$VSXIG!PjE_W#Tca=Kx|57%}Ffz_n{4zjuj$9Xu|v-Zl83o
c;v-XG*Ca7aDE{Tc$#&PA>R@B36$D)Fq>0@!0M?IdEqrraA66LSl<e$dL!U|Cr;0~=m9jU%uyTi8N!rXy(198Jxl+EktRVJUm1_b
P}j`174-Zj?f+jK9tZCjYQm}S0}Mh8PGH(Hp6`f+`9%vG?<d|x5hzdJ?{QHqknAe6q2BCZJwP__0v!=*4CIR0J4hK1+}ohg9id=*
D+MToW(v{m$_>3keEBYD-#W)CJStwt*caBcF3wDUU@HGXz|wzm3AJC{)Zl_%p#HL5a~4HnF2Q_nD%7GLpDsP?&yKB~OU@SQib}kv
|FI#O0FqNqcCsa|^1nMxIQ!XawB~e1IZ%pfEP8q7NMe>{4uEZO?*N`*_si!4h`Z1BqNIS>cr2BvZo8-)NP6DlVdxUMR+7?2ON4Um
WndjZ*ubJJ3eCx3BT<G}+1RdX>(-EtM2P-?-~A8>%oBVMc=}X(c~4zYC@4~j59)#k>AFHQMJyr~#qo&zrzxv2*U|zR3SiLrN~Eve
yKM<BDU?ac_12aXRGqM*a0o<y&GdZAgpKe&aAC%(lniQFTa4m&cBlJ6el)?W(F}J4iov1UXC2=yK#?hA0dd|D<h!}~-lzu^J;sVj
=Zt}KcTs|J^WFO=L%%6|sj=fK)vAZ!jKAsJ_V>Alfb(PVU<AQFw1uMnBvOLt-k!+hicHT_JqIAr=tUHk>OhosiR|_ynN!BO2DEgb
Dfo#mt209E6XGYw6LERb4aYAl(KJEe+0UUmi?Y_)nPzRsuj-5#kzMtP`rm&hwHNNoC<bNgYG^dlkaX{Bs-;knfAO8)g=TzsZ#m(+
zde5J-vyb&DST8Pod6w(%b>?>-VivwuTLa`?O@6xvTymOe%;T6zWB_5Kw7WWs!AL*10Lrl;I_f?9^f*WW$}87B)7&2dw)|RFq5U~
{q68aE<SoXF@Wa$H4X)tc{zQ_A3lV`?4r#aY)c9uOu|MhuiMWG$(SaXC?pLLIpWf6tt)b&4y2znIZx0zXsDEo#u_QA8P|0hQeVsQ
>PYrtSpQEi>?a19@JEQxAwRX3u6#$hoR6byLs{iEgBpL!<l(O>(>zCw#q;KsAwC;0!~TBNpKsb1)(vZg9|z70K8C;M>H?!yje-<r
=Da};`fc$LrTh=#91Aa&w<vyT2%AcM!P2eq96y<KSV0P8d8e9DaN|J--QM(GRnm-==zClK6yTt_Z(=un_~ftJ9c@(6Y{8ZmbqE*)
uc8QGy20Oi&5)ks!T~)BB_gwl>Rhq{5^%O(FTznkrxn)%t`rg4sPV^+k#v<kKL^#roHRU(xQk!%Gqt}RW1J%uU+^3V!`T`ZB^xQk
$ZO$1JQFwMVQ3jLe+d`on!Q`kecgRrKZwo<kf{MZA^S3Eo~ChP6k*)8DZ5TVPX7oRDt)b<m#k>(s20AFQ;Es_SVGg1V!>3kjwR@v
U1slo$3|<yaHsT|n0UnHNzl~%==rJ94UU23iRN`t2>1*<g4PIh$kPT3`+f+xu=1t8wg{YncftmLVKN`ZZ!^|=HIB9LHEZw11v4n1
6UtXKX>Cq<9Lw2Az-vx`0e0ELm7mN(2)JMBC}v?*Zg=p#L4eCZTHWH3q9z|j1sl{Dn-Y>bcNe{>6{ZdM;3<iFy*`?>#HV9wJ!%@;
^CFurz&TrRysd5}UU9{+g1)`^C2o1J4nmWSauTfM8z0VF+-cNTV|>Ap5$`T*A|=x4VLkm<AvbV}fdM7Z@>ofAg0w6k!J25ysH$CY
ymy&ISH9K`>9I<`J(&RgO>td0-$X>+ciMV%-R;Pm0Ch)2hP;?Q^JgwxKO1A_^zzpz)eJQ*N&4tk(ZA}l!uwDK+*T{tsVdQ{y0_*)
Ogo8`-u#u;tC5Sp8bwG|hxdD<G}F5ppE#F&stm=}B#U-<c416s+pV2cA9;nY97mIQHc<RUjvr1;KqxaW>@WIAf=io{O4(ZQgfK^C
7Ys?;nQ8_G7@zYbu}(bk<D0V~k>YIJ2?+_KNbc7P{g*ubLJsV*=LtnNEc5}<F3SnRA-6knE@c>mbzI~vd>ydC1WLEMuVw%P#P6a!
N0!n>UINE0-~7)sIqE@oE;bysLQ5P=I>l(KOVaP^o|ay_%f7Vses#P+iwtUvL<rl~ZC@p3Aby$F))34%J+lF$iCEukDjupl)mrGF
^oGj+L`|)>N2!`(tX=6*rO^`vHBCppZu79=0l7!6BXU~4fjW=h^6yLtV5}RLG2I&iym`<%zr#gHmOR`@Mtezccv5tF`d*$4kS&h<
)eiX!^9H@=BS+ws!{U!zr85YDs@63rWFFqAR7n>N5k0$hAl+Wgx!i|ez}T=ANWqy}9Fv8)$~70`m?18W$LE~p1iMeKV=Y)DfHaau
O6`wa74%nRa~$~*7R7=$j4I@185eb(mMiDFFYjhl@m}~l@W35hzLyo^l+*KzM=kJe-v9}HWIyX4mZE_qouO$}tCdAN+Y6<nV0Rjl
A0kP0K%}=nUsej>5@1wc<bpA5A=XJIQM5Q-!_F<o8NtV?W3pKeXg3!U33W^B-|6a6A|1#0YazW8f|#7tWw&v=iR-qwd*uqaOfKUU
W@K?;DJK^s*r>wu>>+HdP-h*@XjUY)_Icz!GLf|>D3v77?S~!F)gZ}NH63GTgoOna<}S}hZ!^1WVZ~x^t6K&W-kIZUa7BbK+duZm
qe7tWYg2fha3O!DAS6WGTQ1`SW|KwnWbPVDF#YH|x3LvCg<jRYsnVK~D*}XiF{iov*MtwD+m!#UyhA*%KdM*lLVVER$XH#?5|Bby
G7pMU6yvQ!d5#=kg(3o3iZC9u>wBtWI(yq7wT&>6869>0AY5PT9is<v15Je|7pT`SLO~7RXI6qjyr;!<cn!OWQ*BJbQo;dQLWb4W
Ezid*t}q8_&Y~52Z_pd`1<C;%??~`_^ZX976YY_5SK#5boG~gojHcWy#5KQqPpSg{&lUPR{InZU((GR`LOcMTm1#4{g@Ak*8-{`2
TaQp)aUtj~{T;KpC7y89;3#xE<T#vQa~-*(pU<LV;oM(s{sWzvy3;y3{!lCU(V2F5fq|dH!5O5OTww7EpU$wG_fl({c4bbd0s7c~
oweFhJ2qn?#tl7wSYzyn`aYW2^u~*)#DYIx^<5eoNo|E_&E44Mg&ZUcF_gXA_^cbOnp;&6D1?f|TLy!m;GAC49fcWGI;~g76^btV
#K@zzi1ccXv>U;6m_%UZ(@x(@UEp;BbNCsb<~57QqSuwEpJBg<*sCTI1jAQ7+i&8a*TAI!NQ%en^&@|CgsX=eB+09k(da3t7K&~k
{iO57pWPoVsf*XEAn066@?<;Q91f$u%>+gn{K@cQ+D7}FV}NIENb8($)W_5#%~$;v_g_LfV%@sCCG4N#xIVoLUtN<7m3?R2YiWAh
a|B%msnCdTuJxv+&ERwyJJpw{#HhQjKqoAb1@l`;B9jXbA%@QH`I6Zae_sAgPD)7nkFGSWRy}N&^9_`VFDtsr?T*n%OM5bSoW8t&
LlaS_<g2y~LOU}NGI(ZP9Whs2DPQzRJIiXJ>$Z-A@{IWCd6CSOVmroyi;hK6>iMCR*=uSXAyI{AR_-IYa#4)p5k<3=%Sx;5J4)9i
iuV6gXikjE8fR`9e3CzXn}fMbmN4v3p}iM@f<je#9<x!7cIxrnB0x1OzCgE-S=BrbNglR>W2e$CNtHr-OWP+G0egRJ-xp~D&5`s?
tF@UPR?1N4@PKv@ra-s~E|-OS(La&Jm7dL-RpnpPj?K2^xqs%VI?O=)!JHylA}p0jo3K4BbvoO!i8H(L!TaSIhLVnx#6v+Smp$5<
+kZN_i&OZ<uV;)jIcYKKZ@-P<r#rnWG$1RJsG9Zw92?E|`V*W35J7%693TjmVyCGbbe9N>WG}WzQ3b4SV*?D?^E^`8q4;evI(8Z~
c4WHSWs(-%R+8jMnbh>;B?_BV<uT_x7N@cZXD@NG8=pchhC{#Ne6k@9%N_>!EOO5G!(T|LMswsy?k;I8B|fqTqC4(zV%qWkt0yxT
pK|VhI=aM>#DaAHU9@Atx}a7{X{}4rU>4g@x{BHl+DeFwd$^ZaL-bQVZ{C=j#kf+C?EOm8&L8SWhOW>Z&#}DA$VL)KB~kGX1v&m|
QiCkVKtNNo6*msFizQkrfAG1B0DvaxsiUTy$#rla>5+qM0n{&Go0os*oYiB(NRI{F9D((v;+5#UHsOxfw&;28NfS)c{OKEf=nU>*
$t-NUAIR5<O5rDOW&$L3To*6FTX`W|FzbKWil3pYfx$+|*bMY16;l;K?6^M&SL2zLB|tJWvZOSs(zUfUXNqmTN6|(X(An%uF7exQ
^RSNbq^0%bM3Zc36s;ar>|b_jwtCp;-<~{=Y)Q>f=FGAAYbGbYMWnUYBC-22r)(0O)N#a3T~6iLP6}luq%zl@r~sQWd*BLn!vU{u
jk03K#$})Me%{IFLDBnT^#b1cG-&Rd9J%=lu21EPBOr}Z-Nc7oTrTn4N>rNLPwFMbWsHLD2~T2yxj3a_J3*g9t)4~dEC17Tsjj}(
;f7DG#d+*&oGhBlPCjjX|BhdYsO<-`<>t+qNMt|m2uxax>tAe0$!(uk;h(HKUkRi`J>1PVdf!cSU~292V$`u(%O!jG&gfZX5fMz;
tXrvUAGU>O&fdhG<3;A1a|NiFd{%=;lI=u+#INxTp1OS(5>Js2Iv{3O*uqjXjYMlz>!mp8oqGEe0oV<Jr7KQdSu{OFcOm<kym47l
&u*k%r2#m>3_wNwr0Je7U;*oWFpv4u=EobSE8&0&Sb?YG*dBdBmKbZQr5c_g>-AMtmtLFh1DiSu(y7{8TVC|g;7Z{A&5$;qRR$Ny
1v%GzkpE)1Z22Jh$Q8q-<Z4?n718&enOjrj=K`m61<a@4hj^`DeGT7#hyGo+2eokRjen2&dlXd=R_Lr{ZpMn5jPh`ec!K2Pu(s7h
il9UYo;oCWTXah)%DN|vj*+%{=!GA-!rgi3*pgquTm$Hbu)n6CaX(B`cnF<I(5g96h`zYIJYi~!{TrQF3M6MCMh8TlaMIfX#CT4o
aaFoL)O4+SO9e__+||hVu2pb&k+)HHTKClF;MlV6kL1wGVbpiAA+t(<bN#Oo;`=ovH4}Xd-IE6$B$aQTkgiN^Ux`mY5Ba;p-OI5s
Y+HbWZ*zw*jKblKgE8(k1IU<8m3TowY<?I~>ck`CVvjHLeHD@Pc#+{_X3w73p;*N?A=kJ!Pk;$}Cvs&$<(Xs(uhUActk1b>Y^*Yo
@|hlR1v`^LmXe`w3chd2f6eG0p(Y>%_n9E_+AC*fNG#<M$>@ibwsB7*_eJu<=p=W4Qw{J74wJ4916#a!sBcqfzVS|QGL&`<Om!|8
`;cRQvvuGm4V)8|pODiwS8)M;Lp3}|TVI6@T>@-hAAcm5<VIF-OKYIdk0MXWt>0rvJbe<5yD9=`(6xo2{sW!FTel4WptYHEUgAbP
5;cH;9Ph<*L%>F*6NGenOGlp^;VnR9?^2+4*eA1gTgSQA0ZsGMr~tN0HcXT1B2sHuy~)_8u;OT;n-Y9pEdj}^{|OU80K^Myzv*dz
dN&G7$?H-*>lwUezO5(MJedpz))3gAE~*uk5@2rG2M-X_S?+oAgylO5bD;Z~uchSZb?x&WqXm?8rrjgx9`OwD*C$Wuw#C5ZHs-9i
V_7OW11D^<q+C)y|7m$a24mb+aMqw-SsfA<bhxE|jrS?c$#THB8--MLx;n72qCS<F4R?~gIeDZRNEr!EIOoafYTH!^`pUYLKInrp
b2D|y`8=&NIvn59n`i?K3my=;6%{+4e66wx2{p{bvg_vJP!+B38O?u0kDlAUA+W$=m0dy!!USEIO^(}UVuJ`ctldIOLS_E&xa2jG
31ETs;{|{yl$fIJh4X2UI!8oVJ-kGui8dxU4l19@!N%_)GSNAImZ1Xc>*#wJG)f_2K)wne^Byf+t*JL9m-5o{sa8-a-7)M>ssl`}
L=*gulkb4#M<3m@uGg%x+sJGH^r+fc@tf=MGc;k)Sl+jQ>8!#511W64wzpKIUv5rZ+h=rsml?7B;BW07yp0=pE3W|bVsh^HN4$@k
*s;9H#7_|kA#W`=6Mo5nC3J1gE6vp@kb0am^u`7avEIr};s@<Yu&XDRO^%bvwiFl>3TP>aA>~U7lsID7)Kn|LsU!>H$lzBnZs9rk
cG>U&gBgvUx;zsKYjoYT>OXl-Vgq@uW$w1T*K`_Wb)3&OY@CXmwCf6z&3=jo8q)V>ZOeO<jEcSGp6|LSS(q#=PG>RY0GSdn;16;-
`s)IF2HvbsEza_*<Hl%dbl&ZlB%Sj(T~~aHrazGiwTNK`H$@(=i5~YExlHBUO_9<-vFWOT7;$W~MB5=8cFIzY^2^+JDOaSGC_jsS
$8uwb5=|6?Xz**q%0O*4OcYO{SsJ*==P>;g93Q(f#@gmr1VU*0#<D2+ODl9b0`1$@4qLmK&)+i=(VHh!cEFmsCOM5LuTv!;X|8IP
abwM0-Ins-jht7e+X-y;jIE0sKCse7C}35dcN`^zk^3Y96Ch^p-GOBk2gmn62IKfzQ*vdI7x<Hc{bG6Eqg`VrhmpY+_+dq1klXld
H~<xm$S02W?Ff}R0A)WT(_1};9L%Maa~XBzy?vORRCRRWWDW6g-uH%J6QM#Tq~AEkv&{AXS}`ln+QGB5jb+J92Z$KYH3@oyr!`O3
T9V62Pg}RBav6R4)_dXgv`XK3+2+{#jLVFFrt?y3BFck4D>sLI9J*aJJVVm&t^$Vo2mv9W{+8}aelFT@>O3wzs48$V4a)OTcrZc9
>F9V!&!*%BC7LegPa?Rx->I+zm7zu2gpB$zB-aO=knLy0Tid5u`j~mjZqvodJ@x&eW52@?w0o>hw9W@!1P31CbDA6J9hU#DOJ~d(
N$0*x?Rm69pt4wkwI(tJYz_O_mNdFV$%u6>RkY$83cuf7`n%I2+p+`~5P<(H6vDy2Zb!5D_%<GS{36}U4prBI0J#qONVic>_s3TO
586A_E&~i7LD}R-_T|bz&U83wPj1>;nqB{-g!@K3c;z+<9xs2>RX|6-9=>k84-TwZ6U%z4&m|040dZr@+EY}m$Uukh&FgWXAe6;C
DmyXfe)50{D!KrjZQu<Ui2<Jt*gBXyLHnl8Vs^9~!l&I5>(Xx)T2#=h*{ExxX#Rb_*3U|0w|W^BBzf{j4kXB8i)(p!L||W_J*#Il
?gP|%%9%Z4H3tGRS7-jaD{v7@<B069osoF``NC$>-r@ZnwFT`w0$@1Lc9cSdA6lTwAvLlM7UlMcj|TltTovtz0AzAZ>bq~p*Gu2+
%)5Asv;l^;LPEL~lY(*-v1fub2hB{p43w6JDo6ie8GGA?nLO)-R2p;|FBC9HlVo7=q22P4MJsPGJG`R-!4cQOoJq(;A>tM_Qg!&=
U?-@UE5?Y}S1L>SvmR8{3+ol?0YtvP-s1>^M3}qUbm!0F+WXQ3Iun6SOffW_XE-FAkG3B#vTJ|@h+oQQ4HP6HWkMvy(0Na#e<L8%
QNFvG-IMq+-$bHGUQXFYbJNNq_yQs7UX*2YTtX(E4>MJ2Uu%ykARoe08f{3=PN0<LKU&U*#7J65E&Z2-^vw8gcG2PfeuB*y`f`u{
!1Lii?C%iC+GyLPUKQPK@t7{G;b`932ina|3DCp^Rod*?A?q2}$Y`^ZNZ&h}e|YB1k0|D6SOi7Cgp(X+o%{1%(pGqYxt4HlXTOG9
vY2gYL&5E5)aDzliL(Q)-Cv5-s>8b)a~S??^lossc>f1rtbWqGtcZETZf;|0qahA@gXtw)dy6Og)pX{8RT?V6CaB8>=9x7|HK#S`
<9T?nruqk6af0_eVWMQ)V}>?TWBA-^&EXfjN(o~=zVNc_&9~fS8J+xXat%@5cz}$CfR}9(UvFJCT%%qcblvn~D&M>;g|J=Kjgxfa
qAEIk<P9H@FqhK2K#zC`;<O~0MQX-6Yj|#C!LX`O!MB-Xiv^2kKl%#C?Z0GHuWrGYQU{ola~ipo)9E0?)dSKYq><x`02D0d;k(71
EEja2VRXNKNettjJLlOM6<Q4U%f{||)M#spgPG!KUi+N4o|9D*PaaU(dP7(VOB!bwZ_G|R?vyXe+jN*ns;<E9-VMwD4xO6l8w;Kt
nv+I(ee(pPpvUTj&qkGcL1X+`%18Acj5suP*8T{lXc5&jc+i2RhFSCw^nXk?d#d#XhHo%saRnc8b6s3~Lh2MhRSxFL`ta;OvIAJM
lHvm7y-kzk|2$gY589uM+zA2@l<@Vc3gz%@jqqX>jC#*a<0&S<ZLTY=yjj)V_ahX}4N~RX@uZO3S_aEjcJ&!l^J|X92+{;G5ZZr>
f=c-DR8BJPr_hhLGoxy@7^0BQ-X_B>eJJ4cAK1&*7{QTk4d+{F1PJ67$c~;BkusZ6s0+_oX0Vz~R5#A0b%HV<Gs<C_chN`1p{R`e
9LjV~`}s>S*>zv;gj9kgb)0$GCkxC39&Nqv1k2pdEQ`5-UFq<q(*RH@*LqsAL7-J`C4R*p5%gF9(`O|#w5*dD5nG`AG?cf8@FncP
wW1h8Vl;Vp_R%{ABY&&#hTi{`fX=8&S?k1`pX6aj(_)I|A}RWt8W+92f`W%&M;f?qX-qzD0<|g8`~u<LpV|wvn$E>l?77<(^qs<1
mpTd5gi((aKhu*Xq~c4u-jb*gEMa;&Riuh6sB~@p#dvt7;|=Fq)7>DU2jSf;5d6|HqwF7MHLR${8=WTvgfo^7=*Ga&$Cm4d^ZyL}
uV13<w+gw~YJ>sz>OmYk0sN5}d(QbHWFoPVu5TF>2Dl7|J=b)6%z<WUoZGL(Oi%X@+*E{`A@E_2Eed5HPmW*ZTWTG#WC2zGMdt>?
1tejP0*$%kT0j|(81#1h(av?9dj_s=X{1i?LRRLc4G|+WO%*0?4wowG?0ZDOi&ZNB9?#pPhEXM0DqOzxBH{kR3|ILBa&yONb9QEs
-Vi#GIH;Hn|Amn$2GqK?TVr8}rqe6;F=OSr0<L(8<6&EDr)mHWIOI!8g3d`xuD~5&SY*#4oi4~M7OuB;M|A5kk({dC61AsSe!09v
Q<?~`6q?cS!3JZ-f<CpKQsu-D=-+L0V^HW1bYZ16kMraQDA`iyibtX}U1zk4DzJj&|Lx%v7*Dfwa~ivE*V#5-QVbPvFb&I#kwG7;
(CjA!oojZWm3ftPXx4B<Twa_7>W#izR_v|dhCeRNUAxaI_o=srtp}4&@I7;4r0F4;#V11yjK9ju>ecqPawWCEd1=qrT(ZRF&t6P%
heEy9Q$@#3=dp;Ue)VX(wv{`AO(w(b%V<F++E_UpGWwmmOQn(}{7`=%-b_s3(tW&_Km*C#;7WKkLo=5z8=}+I5f#&tgLb^Rr$3eM
b+{Q~L#)v)VDc++60Yq?+OjU{AYMqQ+cqZWbv8nDLKC{cIZ|R-N-ayv2cmm2QCHfo1)%94eey!`i_7iI;*PO4OkmMsG#7Z@@o(B=
Lc{!2+D5P|XrLy!2#vq2xT_KGv%h<4NF}7wp>IMFWRz>t2W|f-VYlHlyoWww1-Gh4fOF6BiR7LR(E|wpEi2r>**vQ_M706MDO;Oq
e6qjAHVBLx4;gD6zo)`i&l=fD&W^<|TO86^O=mQAHTla~p-7KkBZ8<TOo{sq6sj*)cPFkow4711pyo!#{mbTDi<t-Z&~e%g8d1ZA
a>)&>8>8IJ;xY7(nAxOHK*s7Io#&I+7Un<z)7(Lge4W7n{M<`k$d0<!`EA8eFFFVx4?#lG2oX}aAD0tWM4yV>&|ijw*4oFXnvjo-
H>xl50Kz}^Rh~#F8~65L_8vPOrR00txNNP(*UHFjI$8qk_2WOdwIX{oC#kBr(ztPd&2+{RAzITl!0q%))PddcLcC=3ozLx}qEND|
;wJ>s`EvG=2-4+((W#AAz$v-zFJ101I@SKuj*KLaXN#-^?phaCWex`rQ=QUCP1qN?lMe89&244B9Tk38k_zO@U~XYtt~?L>N~xZd
iM^=18sOP#Uq8@Q5mV{}b%|0Dg=Q}im6A$X9{H=<2r^=y!Yv;lh6a}XaKI8HE_E#v3$L6NIs4n;{pn0%6Vv|wS;r5{$c3qhrrDxH
ZCg^Zy)b4c^!!=O7&?*!bfJZ)<>qS}Y|>}XhW_9Gw2LwAs)f4JwsojArpG-p){f$v0Yf~A!oUDTV<!&Dd2t(#@V{LOt+h0lfn5+z
K$xn9*b<s)o5Nc7wByo~e^o=$j}0+0hkp}Dp*X?J{$9<4pRJp&^}Zp~^qZ?DtEgdUG;#B6<^F2+o^b)<Dz)}kSCorsG$Dey+w`?T
RrcxhX%Ca}k><FEyoEPD7J34&RZEu#0CFZ2=4avQwEq~r@{z3{vdKn}Em|TYBty$F_*Fji*|Vj??4xxwv#DL=G&Fgj?9f4`9cT#j
y8y8pRY)k)W0XV^$oyKJkwvtBn89iu#0c{Qi#rUc0uwM;Rrw@4bpiF$<A-dk$DY_y%60y3t~3E$P8X3SJ7{8bFJs1(>?)NL%H*wp
vawRzWc+(7{9Tu7(qZSAv<^q!89=re_ZFX_%VnoJO>}sf?v6gm;n?q#tZVoV;mCr4xNh~F)qGf+<x*LZJw4J1Q1@Jy;4$#{>KZp_
HG;DFo0T@=u)d$yjRsR6(Sr5bnK<bGET>M+Trc8)enDUEMX}6=Djdf^Fc;7lV=oGuuaG}&lN4B(sIMH+{;utZ(|9IaY@v>$oWHc|
59Q{}Gw!A{{zSX7@iTgIbOog`AQt+2kPW-uM5_+DP;oW45A55)Eh&!!)9zsec$>E4Y3dghtqZlvEqxirg2Z)7jgg9Q3|&8xXB-EJ
7uUWGC>By^GV0aE#PTgb@$)obUHSB&Vq<lQ!7mkw4-IPTA#zdXo!-k2gK+>kh_p=Kz&A*{HArv}JregDT!P<9HAC@pGHgN_|LjBh
CE;=Pp@>Ug;|j_c*csuA)wdJrUIMY{@kKIWjw?&XLm%M0EL%RBs>dk`crdImN+ECX3OJ+@{etSc(vZ+h3tl`6yjnYhh*Xa_7m+U%
(64YwSQgxq5X0N|!SHlWgyL7v7M1s<A4_c*h!I#%Owh-{^=Kud7QR7cMDpbI+17-Rh?>8ETHEnOcXyP_p<*6;q%AKl@SMef$Qed_
0x@H$EQpBJYZvJVV4XzzD$K_^Xi6Re<dgD0TH_b-1JSOzyn?-@d`5<E#q5ByNiRw{tgRuFLydli!2Il`+3|qll5HUd_&qP1`~7;p
F*+yG694!57LFRwfq+`kF!#3U56=o*XcsF4RP)`JB1^O<n!*WX<RvQI!_O)kMfpKn!juMKd5uFflp3zG(2)ukFXNQ@ymATZLW@#P
@GiI&qQ1Sf#YHfF3QdGUPEHaT2BWo)1><xj($Eah8WbJts)=0WF)OTWip@0`C#o|;i>n*hFmN>8JN_Q#clb*Zu|*>@UEYWr6q-l4
KNb<b#0aKLFtvk}N<s6k{E_J-FDwh;;)rf-Hu}#2)2?*%pBkmBk|AM8M)#js<uakOW~8YvPj`Ffw=&o~T8^<b%mX-TZ2*XJKP)Le
b9!xpBN|J6sclh+iHKxF{kfgo@v76RKSqSGn>K=<gqyu>lO28tOT%`rcSQllAOq&no9_6198T%g^HJl?ZMBEb2d@Mq8byNa+Hd8r
X$10om~{BMnksc<efs2$pmMywi9m4U<5(X`gXG@pc8<HFjFF5{eR;UBfzc25Khc?^-5BhT>icxwjAPTZ#yO=;F;A~8NC<4Gu0U(Y
dg7F#Rium_?*t5d)F|FvNz)3|I~IiCzx^;G5|8hNjC{3tFvlF@B%`Gv6yxI$`O+E9_DI<5>&~y<0=y>OV>I37k*QOBk>DM%>Psd+
tWe(CMAu5~NtEXOMWOWzoMzdba@27w>yzB|&(KM&{d$n0MhnA;wbqPF9Ey)FA^}KsY;S@$`Uor)fgm*Ze#W^QfqDl-+z+W;8ChT6
ZOP7udbqZkY?89GmImDhEgIY!9>{^kq83fp6{;z_)Sa>gdj5t6{&G;9p_po4!s>cnq%BWp21AHE9j|}BrYSdX`xMrs*=+IaCc{Tl
JdzC@8T`H--sYZAq1*p+!g!)v{DF{nGMs6^(;v@1(!s#?dy`LCfg>2YCI*F!PxS1WS=y9b0JhMJ75{d*lU@Coa;)jQt^#*}a!&T@
INntAS!Eg!$^i!q-39J~xL=pY9fw8Lr*!Mv`Xpm6xW$qY${t+<oxB#V1zZ9M<TUK9I=o*F`ROx`UM3Dt-9g5J{AWns@Cx-WC|E8x
6lT^xRINIxmazZ&#q(?~BuM~|-GeewGwIpXN9V(*C2_o&x5j5J3o`_fk6hvXwh1qsCqR;^uk9@3%1D&58jJFHa#~Xq>@M&IhFx%)
;ZK?)Z6qBT4PW)M)Nk)^9P7cvl5)qbZN#F7LZW7zLJd05s!4~WMH3^Ut)u=$Y(ExdDo+GD00@G=u;wOniQ$kmu_9#-vNHhajVsqg
C=x_flO=Ukjak6n{di_CJI=9eb0huy>w$CKC7?~~WaUYMu4d{}9HGTG0Mz{TT(l1s-If?5I@)O^12oU~!lzW}+%As=6jzT!ctm@a
hY4Eb_b`(YGz@Pkt=J=<Qqs-6p3PsD6e=xe0~!vv5i)2}PvWkc{woFee&`eOfu##D?*h>P*_3mvOJmP@90NAciazi&G*q2c#9aGi
ex{B8(|gbfhr&zw<8&q+l^D8}9oGVDVrM7VxV*b{`XQM$v&@}dh{0ZSd}G`K+*%7Z{9{sGI@VEipt#X=IB3}iSZ89A3C+S1{0_3R
m_TG*tAclyEWEb=x4RJ3=Wf}RFccLr7Lzp09fTv5=&%6il}3~>cH-*dA8QN6w{)b}dT^N>7MZ^L2jmJkzpD$KD>Oqvj5-mhbp$3b
{&X6GgI#3|CW8H*Z;5~?-9#tQd9fkSWi(qe;`Ul$5qS)PrmW9Y1QBT^znc9i)M4t>h7c$&u=P!WRc2}05*O@j&w%7Cn}4>!US+Lh
9GcIA9;xU2gdTHj;%qi%sX)pI_f2){Vym&2Q4n+uAQUYC>+q|$TB1LOCof@_vcPx{;VCAoE%GDpIM}_*UL{+kL(slmV*vVu<oaTM
Ak+Z^URS>YP}t&OYg~EdPU+kVz#(qg^{ZJbBQbGG8xJS0JEE3PJG8H=r6D`r$?nffWj)-t|BPou>E`OK@0k}Bz3MQ?^a-Ktehh>2
O+}Gbj0_R^O~2-2M}KGe_*5osWV`Q?ZH~an&dcIar;1Ywl}6L8i2>0TP19^`4|I>;cx%cYx*as6aLmzA;E~-(xevY`hgX;vha@?}
7sO&1b$|ygraku;`c$K>+<_LB!C8XM#L~3*OA8O<_gG$D`t%M=>&!$MBoPVpeOiYY00va<9#&wt2}!NH{i(W^T}lq$fbSAf!lNXy
FRklI<P0U|zVc;f9}#EXm)|PKW7K<TJ#U8E>zNRs9&vV}v+*YDsgEMBXv;Wymi*)hNDvp2UiXG}G?TvTJ3hjwBbjHYqvckm@Gp2$
K|VVdnh3&{`=UjJ4BHX7p5Xuwoy9kukeY>kF7xSydkKJYOpz`r$(=c5i)$W4mGWdIHxF+$UxxQB)M|oLf>UR~74$4W+$=k4vN%6%
6l*+Rb~{-Rj?y^fz5fEsYG#~~RBUqjjv_>wX45vqRxoj_3d$+{t<bpLDk>Ns=>T~)@BmR<<T0nLaAmfEMX?9B!(-F0mX|)nc~i6}
CQ9H%;OC*jEpF!>q{eq7BH%E42aY>1t3x@O&^6pqgYZu3U&xef<CBgge@bdbuo4u(I%+kP(@ImL>ec(jUlkgj*~dzx$?U$?E3p(U
xs|N>z3@vQF9L7)*Q(<SBc4h;e6G3mIA;lal!RuFiSCTMs~<#hl!&L<;jr$fTDc27(FJ!w%(3?aPwkb9hKf<7iQKX*F+Mf>coI=V
bWG6C*oz;!)w18vlAF1siMu<|iJ&H|0_iDWs$YszvbOdr{%4hRC}T9l&>Ze66PDc&ue+fv^~5!4<PUe!%e&*;3B`^bGq`x9K{)YZ
I@Y_8;0&2#slG{_X<)l9L!yrAmzft@Z!^Aw4K#gloQImr(3yG9%~ygZxwak-P}kQ{{;^jb=V(HvFp&a0ryX-Wg@_q&jAMF1g9Hmg
EX7;xxYl=vJ(3Z%8XiAM;aZj~*GZL{1&BLX_#XTCWUdg_qvzaDyFvTJ*Od-HQ={nK-Zn>Prd$Ruvr;urZX+$U73Aj6()6kM*jUDE
v?dJ1?S-eJW-t2)QDa+R_ett60k@NlYWu9;{Aa?PRlpb3{p<h!!Ui7}208GZD>)qu`VD&Ijl>H_ly5y`NAuizhQG&gYB)hAq{^j>
<~>h-U7Z@@FKx`1+f**T(f4c8(~9m9UDm9BOnh~HHU^N5lohGjilC8GS~Yn7SSyTMhPeL_pji}kkY%e#Z+a_b0z`P*er1J(0FPWs
dc=aFovO<O5M{2OG(0iR2mPONgI`wwfCwfjnmp_*-L!QVJC=3N#%}7)wn<vP8a6i-3z#V%>G!2G7BA-G>2<#4DzkNhyD0q|1gJDg
_m`JeYM=p(tT-?r&R%0}e$p4QH&P|qcG>Ic=Sdwfqlqz`WPR?@F*_u4oSc0w6amyv#-D0e?&Sl}qBy4Tq9|=>H&Zr<T}XN>K3aa6
rr6|sg}9a1`Kt1<oQ0IzO7GeDUZXI*OT?u#1d0(5Ur$_DG?pZ4X2y>{U|Q(_oRSA#6{<YP{6_M|e}vWbn==4zSO`tG+Fb;$H?&t=
CrS946&F!Zjqe7t(RjNlzm0q2^6<e!4Uw%Qk06n*cQ8hKih8NTk6zUg{-l9CjbuY8OEqJHJOc^-SkwhE@fEn~EIePk+uSv_vUIt#
SJmw4UrKspT*8G&<+BVm5~WPiC(jv5OBw(#Glxo<{vOdl$^+Dc`rct)P_n~boE_|L>*XSx;WI6RwGcu^q}%b@rnN1EZ2$2lH#3<1
Ao|2gNMTjA;>GIbMB@Hkbfvfc#G%pTuj_tGU$vSEIX0#1g@|*Vibm}dyjdj}X@7k-)Om`y(!`d+_!x~JEpw$%7O3WI{yJwq4-VRT
d}BICHv*XuW-E)}_TN#~?J)94afYIPhVH-QnZ#>|*I)TSLs~7T&AM}0sT%WDjIZC3x*-e5d?wJ_UoR!AgjJ9oYdhP+Z&=sqgU1O%
k{veOvLmj%mFyC+rC2FF`j@isOKI5Z;TAwnHMZBw<HN6{M}mQ5&sMZYN~^8>hX43Ol@D2)diyH1^SOsx7#;O{vK&6NqC>C=pTS;b
KgQ+J8~tD?5EYFBfq>-H+3L04`w<jE%uW(6@oHcDNH$nM-gGyYtJ~!BBSyv<yzUIHnuXl7=t~;n0R+$Vaov<vdQKMA&jh#3@W&`C
_TkHFlAhFmrk=wxMi(G?4+wNPH-4_9*w&RJaLBaI3PeWdjsb=ByPC_3Thp{s1FK3<ZqA$iAUBd#Ph!wsFwqip?|W~%ip6cq>yruI
egX1?S3IS%nk2M!*`+}?+ccOcuaf$+KeSol_m8NqJ#RoAL-0wow-$*PuqcepITFZY@gfbdeT}X$?N@l2Htx86bh%v{Xm=sTB`{?C
f}GNal2A?M8w#3VJJv5duO2O_1)QlRFX5xNTk+X*WgVR4*)uyi4bXDa1b*>*ENiE3wz3r9VUY4Ap}fRCku>jKNvkkL%A2No%9HTS
(5Ofc5zf>kK+)DGlp(Ba%5p7FkJ&es+4bZVAAa57y@u7hjdQ{m4<(2$S3hAda9%wLk0g|{=%d7yPyz`~+)X6_nkQ(n$O1^M-?Xzn
`6*<TxAEx97hgffp+Q75uYV408)PsO+OEMTe5;2TG<nO=8%WS$A@iUYV(!)pd1a)~HD3);>+}%s9<*!4_cTm7B}b3*=#%(%K@dfS
BheRaPpPswz{8=hb8t;~<Vhb}`{}R!O}enE@;eSZ_?7|al75x5BsUcuLytYSw)b1iJfhQ+-`QC_CyQoRp64e`X@T?(VtifUtShXq
H4*>;nuDPFDQHYeq4d7Xq7NKT(n6R2WW5NknGybTij@nKIdaPJ^Mn0$l*srEBfi2d9swk<I6eq@Z?GFO`@up|vOxZ_ZO+x5lB*4Y
3am^J9xDCM4V#L27Dtigi~$5)D%up@pK%ycE1fM_W##bJBCT{hQMXJn6g%DIsmZC1{^@~k*EeXmY=-;~Z9PKLWYrm(3eEBFo(Rf?
xBz=BzSDZ|E^J<N?GLXOHbVH4gW-PdE0j>m&cs0?YG-C&{}zpepk0MbvZYoE>`^A7*Hn(RS}EyY>S3IYwop0&1ANxV(+KFRV<Q#h
rk>+gK#FqhotQ00Ul$Ilj~8|&<ClfJpr_ohBSqgMseQ)lO=mW>;)K-S&P1rHaXqjFkjC)dp<At?{VsATm5rd79NQloBJ4P6C9CBx
nU>!Cvy%)Xt2{GVu%CS_z)DBf({!g%FR1)kFd#e!;W~^McBYZ)RE1ldO3p`@=397$QPp-OlB)fqOdk@+<59b&K<KobV_SP#=B?D=
AOQ$#wK*#I@YhKFPg8W3-d%i^%?TcE_DZdpAS%i|2KZ&J{N-Rpela@Vv^fKrR5%!@1J-%Paer|r2*%$TkW7fQ@5h$*n6bGPr(RID
!p?E;r*s21j?mz4*axQ(h~^XB6*ze~uR1cdBS;#Fnhz^*JMH6lPg{WA-VoW1$f`<=SNRVS`K7<$=@>?^Qcawo1NY3}-k`x2W$xgN
bbiQ!a9jWq2i!#ZnKJ8odB>W*pU6gPt7@s5<U+N~x+c^_uk6K{A4|>+umfYe`B<z7?TB_}KSL{-IS#9=QvOG!rx0-sr^{joc*i+t
n)yaFt4*~foDtY3>~<{7-*%i$L#vmY<!3b(p4V2Mg^{d4yZZjfB<rO^OhvidgQ;7~*2gF`{@(^g#f&i3|6UMvJa+v?O<yLXp7d8$
AGD>L_LZ)8&Mey-D3k5*VadJlg~V{TR;bMYl4-3^dvl9o){WoG5Ayd|(iFlI%Ri2D8-*zhl@CoPA+uzMgZmVqpj<(iAp9$c*a6`E
^;qMnSL_MVOls!q`%A7zjRRh(;Dsgu;=KC-YsaRbVtC1)3ZnU1TeqtLx<nhWVlX~-ZeDwiWHO4R$k%P538keQFiTMZYQ1h$eMVbs
PPBW3n?YPxBeUjbosXf(kUA2d)$l#U!-c)9`(S^L+%3!{sZHH6(w4VL-`INf$Zb0IIdfX9PL)#a{F5J$qX?avP*yXPT?#>nrrfHK
4S>0dD-9vY|E`_(>G$59=y0;Htph?{kj52A%R|uS4=47_V!)JJTk@ts`%*vgg*AobZ~|YS=u>cN4D8!oy}wPshxZ%4yxEdt!+J59
i+1G><y3|N#7JBo_Y);!QbKXtXG~4>B{rh)<JiNDA}N|)l&te7lzydV9k-PxI&~zTxD!CPm6y@Fjjv6hIPz<ypAW4qvrEx)KF%6&
3V90gf|3#?yxudWGvlGSKw9n`_N}XfP!f|qBV1VgzG=i#N?eP-&{b4-!!`+Vgh}kX2K=V|N|z{HAZ@KpC2(m7hCa2|JZpI-p^I9x
neP0>f!=&Q>fLE-@$X<cM>JIR;Kip)U6&;`93Ab5@YD<|a@<2h`4RFB0h3N7<>kk~Y63~3H6IHIp=@Aj)UZd!WoU872He9ArR<?g
ULsxj^uIkULxo-CT!a@u5S10o^9y(KHi;`L>oSPLi6d86i*AFv?GaP9+x5NqF+!e$6CQ!^>V!nv!LC9334PnXz$;KL=G198>ji;e
Iu5^ybM_(O0W{JV4GPg7P|luuQP20KK<>(^80kX#HK&nhT}YG{ykwy;lD-gzRY{JG<9(N}1Oa0M)R;WAong)g6auxig~)forI^eO
Lr}kwG;08P0_X^?bc1u6ou`-R`GULQ07B*kFLUf+Zm_TWnzu(vyBZIW_6x##mu&DU+6ji-kYhx4!y07`cz?y0TH<OUt%s~!Yhfn&
%@|z4!cC9^%nkeH%CfIkfGF_$kI!+!etnPLMo-(8vl1kZ;_dAS1{C|42adPh7-Zz>{mo^Gr2~P>Yb!uDz&?Lg^e{i}*s}!(pT;D^
+qg5yu=m@^YT|yVc+4_xo7`J^BAtrL_$$2VhaX=&ZPmW8oLyllQ%(H>aQK+$M&yxvY(>t)LFQV0d~5)9gu?xh{lGkjxiIcao-1&9
Frc-<uZqq<%(|zjht+CTDHc)hI?kfPg7Q2BSZA51i;F<(j6+CbSC`8DkD|REl6$}R`>3Uys7k3VfT<jw7M5OUr)s5M0>~%r>f6_F
%HWh~>$I(A1<lBi`i@aJzG`F!&FDw2u-vX#w1{KJ5m?+s)z)8jl1+EvkNBGE4%3JEh#cAiBsTr#V-iv2g_pg;WJw-qG1XJ0)LuK6
2_XOlkRfsMS{C$AMgL;^cBV^s@RUWWNTu@xbVzB<P-_YC_})%QG60z=8oXSR^l$}z8Hwlr*#rPo_^j-Ls^)V<FG@YVQ|CF6mN2<f
(MZo-;_oHSUi*r<GFkDMOH{@Me~|Qa2j>Q)%4YDVYywU4828zbZ5Chm+Wgn4Se;CdrAI9spl@>i6wdg&fe^ps>4wp0Sw#sQqgoLp
m^VMZQqFoCEZ%WlLRo{R3u^~hnwq~GkaInrVSu^PeFfeni3xAnD8I?NV(zh^^xcd4adax7(D34nR@U2$oHOL$co8b^Pj7)yPGGRV
oTOy)67$c8h3LX^w*;<Ac+H8LRG-R{3o1|K#pI?jP)4{*bom*z2XcB8ACj&<1b7CR9GJ{%vklthdVzYqsX^l%n=Es?3L3f%im)hM
7|5h7s;)Pjmj;!b|3RabPUB~Fo?sfs)0IzweSjxXwIjp9P<aXM`D+mVX2%=)*n{z=m;o_F0dh%3B>w1K-_1omN<Ml@f$=$rWWC$g
BhtD=&N^a*Wi$NkLb!QbGtrFcnR|Xm^i0pWF2tEM+&Fx9eX}d3sB<7NFK_S**N6oKyTHlNY`oXil=K$XDda69SH%JMf=@x<OqxDh
)IU&kN=sTRTIt*dgin^>w#@+bXx61Jj<mR5F2}$qoCb_~B;XYViVeXr6Q?V69&O+fK0igQFdnkG_v4)^^-C@qkxpBn50F~0d9Z7$
WHH8$Glw$1z7TAVx~Fl)>s(q1H(0S5m+~M0agrQM8<Z5Cx1U&-NLdp#O_yfbGMXhy#;b)JiuInXNaa^CU$Dm{2-a@Pcb0=B+z3wR
rpzPh7!O&bhY4fVyaCZsSZNRgSvL<0eD1Z5=3^5Nzxa#$gh*J8L442)5r4mxR3T{Rgp(Hik@M$#vIcD8(SwNGO|5dn<QJQiER$M-
(9<YDy#SH`?uZ4c&@&BSwhCx+aDYsDPAvTK3N8N5Oh|g?wnjk9<e@=An|()9L3>`@J6yWO^eQ`WqlTR@M>gjTYS?Do{cOT4dl~%e
k{}mL;K0WKQ)5cmy4=1&;R0o4=R<@F%-6OVvY*^sz3I3$t1|}czVTZRdvgzMTIc$0m!o$$fKk{HEdxV@Y*>dH$(JO!hw7ZA<SVNk
SqNxJazZvTA&cFvUB9iqJMOPGAlgUQF(4=w&;}&b#hPc2X)9T0$B3MMKZwciB=+j{2<)~!0kuVYfKPo}IeF{5sNmST?8`nfZuV}K
Ffo4RvbO?MO}TD*&Uj(M&Pf`mY{zo_y)~q+?%YVeJt0BUadXDzaP>v20=9}{eQfHB09poWX_Fa*WU3g5TIhim4xOCn5I{{sc{<xB
PaJTfX-SJ?=YJmar&_Q`y`cxrR_}ltsd2m*LIKN?jv{52^eA8M!9Okc8VwWZ&4ZSgR0twVlVmmgD>9$MqDt4Bg`#v1D(ANq;^d=;
N?Mcz@tnpg?D?3|SPXJu&z3_&43HaUNMPK2g?E(D3d2%474g)g<0}l8r{CX_i|sm_gX@lUqdCvp%*JXaz4w9_BGO}iNOUtLmIeHT
lKMHAbP&9F5kMqYSXI5ZU4jl2q}8!uTP!m}MVs49q(HP@M^9BQob;4E_=`ob=}VtXv6-;WpP8ug-2KhIOfAtDdQ;A4OXSLB+z>Cf
UPcgoU?>;^aZj}wlg%YH+j5x_^1mSUqk@4C#rO3xN0hxiQEuocWwVUl0z(g5%o<&z{yFem?I=!iRmY<*-!lA`;YCII{mOnB^<)bg
<8Y}wytZX=IlS$sy2$0lsuncw`M&3Fa3Wx{RRpn5$)d#(_jM3iHwq@7JB=YDyx$!*I%Ub_RVxDk7w$eMdr};v@FJe4AA2wT)3w-2
84k>9$2Oj+pqOITOAK86a&bULpOu;j<!&n4=X3wT2N_G}<3~J2oGgTmPY>qI-rUN6-X59v6~m;S;3#~i&f*e13_=UzSyR*$CMoXK
v1Nl6Wv6%8Q)$NMcY&fP9;e2{r=y-KiR{)RZI+xTg$^z&bc$=P9^}mR6b(AeM>5pd?wrmP;NCS=OPZ(#-f1n-V!xkmQT{HtW>-=E
R&S(}+SCJIz}2oi7No|>2NR#kt@s}(booLO@;~cV5uK#%o$UT4slaC1igCgHkOmeg>>?V`dlA)okJf4>77#w<nM)~Ls-|IXUJYE9
EPeXu!t4N8Q(Uk=tLjnC;OnCZw~RW3oZ<A7_b|iXY$rACvX<!ThOBmaLhF>8;un#V!t0!GK=^0IevJ;WGxoCn>pB3`&_1#|SM2v(
ihR&PKH`pGOQ>9dE4vR~$pn_^$kY0r<pTuHDq;dtrIZ{Y_d)et4B3`;C>;_bGkb7^d3ycsl$eV$E*13*W;0SpDJ^_}7784cX(PvF
0zlvv?x2JVZB`{&@?2=)Wght}8PHkNOFP{w6y$K%Sm0K@E7d#?LU7z#<aUDa*rMIi>r)qmP0W($yiMgyStgJW7dAgom!NO?SwAMR
t7ARgx-gxF1794-`Nctir!k#-umpM%F<LGh{Fgr_Bw#9p2N;p9`S6V_mG%mjNdtQ*a>rsRJ0b=8Qzg}yO+q9-8lj3uJLr{8m^n=6
?y};_+V=D;e5G#zYe>-19YWyBeabt6Syz{S#p3oF_%`RZ0FeK<c4ErO&%L6;J44V&Rk-S(JNel$*!el;aX&-LEZ2iS3_tp;1IZt{
Jw7K4c_uzwa;pz8$!~AEhY{ew=LpBJ<#efGSsLso^C^E*{=}M*Yziw)79PUbfxS)PFfTXLngSidcuvSOY3DrsSPpW?n}dUs!^JoV
gV3YPSeINBgsIuT+RNiiwEM}($7ORSFTu!U>qO^)iT?0BrF%NXJ3APHPamMLgo|ja018xsIEFgOMIPX(O4CTNH@6Bn2;Z@rr*m+g
N<C(x&vkGPnK9-0y8N6yJgD#D{YjNV@hRKh-W-}ULldOnmX1qPqRIhNuNIy6ia=Qs${l}Hn%Qj;TMwb@gO+G|p~1_A+I^((Xnktl
e5++@uAVx9tp-<jauURWq%-i=d_T>%NEwGt;Tj&q0Go~c4!V!hu~4&!kRbwGuwnP_bBTg?A7t*G>2_d@028RV&#1;rPEd#z-YM2O
q&guB(T_J0v*TG%=X!?g7VvG%Nd8(xeTzlf^o43<QEWC@88b2EU-0B?@yZkm1Uuoq{I+gzZU)Hc)ei?TMSg5}`JlfmU@0)^ex#U+
zH^3XQ+w55R_dMVYy`4lKY^xE<HdC_4!1^P67+lNvV!V*L6%H2Bk#SeIDV!nF%8M{cn0@9om<`9Q>*5BmJyUH8dFk+zdFXXz~hjr
Nd10eUPHCECKt3aa<%NCfG4`vXVrwKiRDz&<2aK!KDCr8l=8F#K1=WkO3gyTyJQX^NfQ7umyC2g`%tS@3NQkz+>Yi_T_q<u8t_+2
{T)b~itnx{du{w}eU5{~vv|%H%x49taGwyn+MV>Ov&wkKEhOK#DpHV<bAuPD)a4c)ZHyRc?L#MQZJH_nG1izKZ(X~@IZk&WI4;hu
#eqTL8*2$i=v2gXLA9ck6zO$^3`N;5Ltjpk;@(z#?7spSU*+3U&HyRHK?H=4!0?ARr1yr?jXx~PMospt5)-mYz__7U8C%aKqITvD
+iIxL{JzL2VBM6Znw7DxpXXfP)9S4}oNi<5c|5lsu9+&-?dCdeaujos@Y`e(%pFwqZQI@aW0toBkc*%Vu{Q*)T%dvhw-_)xz}5@(
9FX6le0HI=(WnQ69Pfp*aN&J=`MjV&y=+yP{^rH~s!K#6>Kre0_(yRl5Db@kGqeDTYq5zQNp?K4j}X&lGi_O<NqPyWOA}$00wfTX
oG|VElh@NO8L^38H|-eQSsc-1c`LC5lSiGHqKAg~*cAxF4V6J^QWk&_hwQ1PLLDNi36zj&CSQ{A0Ic{jotDW&-Z#)CV5pZ$0kj4O
8<4>WBknZ=sjcOfW%ToW1|E6;GgSA<X;|8Q2l<paaE-viXy`K}$5+4_ye70p_oSHc2_yHq^`j6_1!N8DnxoZjSN<MCwF;NtB-&(s
=nEvU(iIy%m%w#Ms$|6}pp(nhi7Z#Cz=pOxv3TV>7UYjSf1_C*d_|xG9X*vS(yvQN9jwFHGr%hQ>p;~8k^wz}Fs~B;jnw+d?`FPn
+F?_OJtr`5Wc&U$*|*7Ua@o?|V(1-|0>_E5#!8S&pi2P_j^tahaRC`8jp-?}Pvp+`tOg`Q=9^mNoxD2x6mhkL#m-(2@G|FR+!uR~
aqmoF?wsh{O3yUm_N-o&OB>P)l@E;L$AF0_FO}MUFD?95@A2gQI)EzISs4P<KJAKrKet7wtyDWd`&x)~qNVaDs&P1^+#@~EYc{7|
&SIzEN%NbBuo5kxiWn%~xx;8&qLijwRJ60-BH@J9(4KMKqCv@0bA6Ve)8ZYK+)EjYO6{RxGbq!*%2|$<*NG5}9USB3t2K5fC4#70
2#r&rr~`dB*5WL_APflJ=BUr<z$=^?7J|;5E&_LMGmxH8c>wYzuO%;{`+5ND`;jaigaXO`|9?`;wMN;TY})Zj(1+mK%)>)m8Dny9
6cipdh7p>s&KewCAFRI7ZBf9Vw1}0G_e%@##_pFA=MOW4Zq0B(1+ohDI_8291wY7)StNbid(`J^??s6bzluOqL}4CU+asV?2YV6*
x3@_4chlSo-{|Gw8^pc&c#gZzzs&_&(nrudLy27)<5<vxJHux3zmwuzeHn3}0hHlrNWAn+a^Tb<FNPK&LUnkaTEFtz)X92Yv*D+8
Y^$P`B?d4GU{v5csuz<H44ZxLoXGnxN%Hlbr$!+5XTXv}Isn6P7CRzNda`BrzJSIEh9--~9W%O`{83?y$`M?WDv*vds@jE!w+XK5
@0(;z8QAW~kaf@oG-jxi);3(C`-3dVBaA<%yZ{*F^rhvHwC~cT1)KEIK8THGEfR>epFWoCXcf^%pVfdj>Dy$pQ-|gHo=9{DLw$hq
QdGr{b)^+I>(<7lf%7_$Yd$u3mSK8Jn!tL(h2Y6@7NPkFdHUr<QR7#{Rh&s<nK8+%z~~6lS+F{ki?d7;MV2A?Tb0qhezu#|JeP}w
)0p-TL`BT%iV(gmQLp-JFDpDev4U>G;#9p)D0Llu%^D$%M>E;rlH;zxboQ3gKhWkY9nV5B$n2=upel#vQ3V$S*X41#N3h9|%h2#C
Z?N@fsDjN{{Nk@2*~i7zlTiCu()S!<Y;*VIu43z$fpe58*|8r5ii$(TIcgC|`7q>p5gTS;mqr>&64V!tvH11UwAq(o^HZ+6^)r7v
ohA(b4K~Mq4WSP_(_cbkq1TVcXA7EJOyd{VcMQ&S*>G3K6rj}hq9n%h#<gREe<_0`_zWVRG=JL(1IkNdftXU1gpM@qZzV>%j@9Hh
%k6`XPw5dmv^$Jat3NN&BmJ&VP2kN#6pUnyy#5kAR1OEC-cc}9#eb)dVyFfsT@|I%(-P`U_|j2F0x!O<E1c<%%@qhTCK67LrKX0V
jJ%XyBCeneBeTZ<rKA8syvao;eBAOwdaB)9;Bk9J!})PnCjhQX(1u#CJQrN%$78i|?Vx;Qj#Dw)GCr2o7s-LZ$0q8ZM9C5FK?Cgq
-wP`T2H5ffnSQ|SoxPQEBt}?<f2hRHx(#I32Al+WqLe!EpQJtaSMp>gp6aGebQsBzY&@^8Q)&1bQanb7Doo>bgV2`ksr8xNAr_)~
f6R+;yxbtBT1{QSwkoDs$zoF*>OW2%&I*L}U!yz<@skfPm&YAZBPSze&nJ^`-L4ZKy1=|z6PC|W)zvsbvHM;7#>8Qd_}!$YOLC5W
LqW_WX)!4eb5rN;);$Ad2Y_J7#AJ-v&6wMYgeDL|fJn#}X2OMbsJnwqvutLRV#duLVk6j(<iGtUuqpdu%^iB586`KvUkpt;sHElY
`ulLOj!H}u>Q}UAym_dEI;dXH_6uL~3wNE6ho+?@`sFJ=ahr&aV*<gGFNg+7S#y-H*aY9P6z*frl}3|dw;vjwUd|t7<Vfx7Q+Lf_
E<iP+wuFmH;X4GnteP&g4MCqC2L#@TC@+`ofoY*Oi9;3+2nV(hAM^fj?fH<4o+AFu!t`9i@joElj$IDiq>1m<<W2)SG_rkZvB-Mh
p3r1}lpKUOhnyMP8>{PQGjoDay+3cWu^u6{$+Qqb^lXTqt5e?wzT0`xd1$XFbJB*p#yjhes$5jXfLHlh24J@#KSP1lGa3?&jrdX@
Ax^q|Ha-L0pUB3$UY|KW<03+whFUh7e){*a5&p2Jc=seTl9As|pLZqTitJ@0I&_i7NB^K=6uGv>z;`QB^YdpB6Y}PW$|xz{s5tc+
E5Tq94;%0p^t<5;2E}&`jfnM5OfbNhhF!?$pQd%9PC-~RY^x;7B`eyxiooHN)7&VP5sGs(^hc#5XjPHeeK^^NGQ?`ye!fI?xziOC
G$&SOKl*U#&RWSeWFh&F53sN2@ypjmIgW`~-_%i;NX=Ni=KIK#*o%%-Jk>M!2rhr^^z=^Bx}+;cN+yx_#t;4&nW-&M$7`K~a+-=E
m-oc+hj405rSc3Iig{_|s|tY^diV0>7NA%!)kuiJyuT=+#2~05S{1bnvt;Xopn__uus7&W58Er2*z3tgxPv;cEOUvf0b>8H&J+0`
PvZZ3Kb|^BX3a*S2HR?n8Cef`Q~MVowx%GJo&)C`oBVjXxmCJrrpa#^P`ehIyv`A79QIZuTU};h{#>gbDkFw&>y-8674hqPExiY9
pm%`1m~Uw{Y(KDO6G?c;9B{g{hO*6aXd>%rQ>JCZ98TQsfc=&ovrWYI`x*mEv|)aCT+XhUIqWt57gnA8UbDVK!51(CFXD)_hYZ-V
>nTe82yUc>xU9uPB1_$|37KX6$hck^U)qua`Hcu4=j$S;jWU;0q~KSumCQ?e>Sqa<HFF}Y6ru@w_D`8hf}veFykZK5$GaL&@j4FL
GQ<2{wGWaYHB#h)$ynPi#y~7j^zuVuG$zO(lctaK0Z$iyV|OQBxSZBr*Z+WxIgiiodtI*0J;dd$_hqMlWHoscq9-`o0yg@iYQjw^
`z)y+GMtPAo)oZT{VTOH5!ILE$G<Q<%m=lvLii#X&G-P=hG`$*O=R$&>!5w*Mk}qUvKv}YL0`mifaQX;<dRwU`w+ah_0JfTI4maE
Kk;mqbCsuwsHer6KbLu`ewvk$Nw{mJf1x;lt2U`u$1}CbGrKQp4q_ZnKe(sFBS?vUUYEc|b8Tr9OEd+=RzDtP8~3gzD*Vel(-GDR
B@AVEV4$X3K}82NhB?al<y??WOE4}0Eh>jwJC2ZMnWvy8yeZ;KYZr(jGaIFiGtPaB8K;PYFzLhfIu{orm$GZMWnlt4Ba8nyCg+lY
@Zoy7jFqCBh0;m}Z~v2=QDy^Gf50RWaHaC1=FL8Mv24B2VmT;XThE*-;wafNzRtgv{xT>5(S^l6$+phDz110_?A$TG*HB()w{a8E
%}UP0>)`)<$xai9WCbwYQo?0&jH{uq$py)bPL48d<2IU*dOj<lq4oj{Iq|4q($qAjiH2Tftdt!hj->74jMJ5i*|$orA0R&6Ql<$v
8zOz7vW{KMSn$9-C{=!|%?h>QugV<-!H_n?4;qfNu>Fx=>q91}FW+|q){VfgaKU2oj6&iR&yK+gLKt3Bix3BE9tMyNNv^GxyY29{
R8CP0(h?vo03+@99~CJ{d3w*`RB(MOYHos@4HL!a_E+0dE0-g<tYJ2XYqCh#vNEjbnd*TK5@8q&fM&0LY+2FygN`g&A$cuC&u&52
2+aOK$q~IrN8S6>7vna6N5A<x<ugz<tIiBvQp&th#)eV8_>c>kM+<F~(Gn2=WUIYfdP*R&=D}b3%!({ZW)VC>plk00Lc3rAQSB^Y
AWUTH-<&8Nj6Q$T2U)*69)GFB=C*~(ymQUu(^|fNGl*eT>Wt1-mX5b%v*ln)=FDI*)jYJS@`7{g{jT;80=q3XFnR&`U%Grp9EPW|
)4Gptu`>!qEm&t1xf5E+6C}Z$$bS;}6hJ!7ff?^XsfVC={A+>V{aKl}Jpy-ORfm{zz6K`Jtp!ZQfen32@}Me|J`<OGU0SG)8s|x}
iu4;-2z7nRRow3^+quBKzyiUXE7KuT=H?i5oF`CvY?wlqPe`%Ood4%NCYd5GnUmD`sQjAY(fwwD9p3S@!Y`e96g6Z54PV=`Y;Ao3
h4qLPZvEbIn@<4Ldss{td@AiUOE&)EJ_pX-m=R3FGmJ4XHa>IN2%MzpLT0|^LS_FX$)en@+J=2pW?&_%2e&z<<;H_X`1a_4^j*-Z
jmOQ-5nW+@^O=8Ro+nq?OA;nSt5fC)hC)Y`L*e8XtOOi*G;^l#8EXM5n*Vng7?<Id<P6W?90Ux1w5Qu3H{MhL=ja#+Xe(>JuJ}VK
cl+>*xP}bE6e#IrR<a4CYxomIeo~NdYt=<@aqRQ$Y-e|uI=n82oxeCoT!!x7&^=)jWeyq#LX)zi;`JI2J`923B9ss4p!?yL>Cj|j
Ya(6$q`jkmMSFKM4}M`Yx|5)zczz9=yN4nK@wJN&pfHTwpi(b;!rq3(F8~n*w~Q;392Ha5IyNtA;X(O*);%O2tuqqCSg<;f1*-FK
vcW{(eMPJlo4!Ta*R#B=a3>y(?NXJ2nI2~}a2L?6h9M9F+Ye7FXA&6FtCbK`^QA{r61S%2F_LD-zY@rVFCyjo29%RLKf8@G(n^Ox
)=2+qFCPZRo8)mCj0nr2#dOD;TQCKPVY7M&WriI9l-(B>`{+WD<3t@ROP&iX_GQ$s($v%g2>Y(y-UnIUo(P=Gu73b=1lIpLS{xJy
cLZz4cj!=vjP8{h^oD2tCZlzF!vrkxSqHvm7GGGzd}Y?itS~*>)K$4it$_cNdasscP53xolU~gU%nVGoJ*d}?RSvK4GjD0)_&R&4
3i^4sxw(bo0i!imDx$J590zpt{4*(g^Z0{JZ}&uuj7&e+#A;4~(LYsIB(aG*4L>cptX^Qn-bmLf6^7b5FrS8|BT3RkR-1Zx?qHo0
RhhFmuX_i5q^5NTYUY#c_pw-8r@dV$9nRm;jO}!9#vro)L(^9^^oIzxAv2qEI#I8YXw>KEPy|e#_zYLuJkArggWDsj_5VjSqu*B0
rVQS|5JH`7P7+Z3wVz(qh#zW|0V4k~oXdCp6NZL=JlZ<2+_Pf+sj2mheKhe@Cx=^M;ik*!P*p}v`AJ&QWZs*f;t@sNciM}Hey0PZ
T;3Lb49;w!A!1^353!fT`q%FbiRmH19muN^USh2Mr%8hgIZbNz2+u+Yo015Ue!I=*SIhKQe7HWpL9qd40yrb3TZde@PKj9kxq^iX
s1d%0d#?~tfH9Z-aAYfQEbZPWe6a!n5&z?Z+tQm@K9w&Q7?SDiMBs}Rf#8s<G4n)j^k(qL%GHot@A<;@k3YuyrS~4iPdqg5q1&Re
IlW6F?pkWXo2_X^{d+Eujv&>tZwVvKYi+O<vU;=Mt&$4GR4*nej_Au)3@pv7;#04o@z|GFDxjp^f@-Fl->qm7joVFuIw$dp7iD=7
LfKyBC{XHFJOTjLrUS3~Wb3FTA?gNY;Kq$#?I?%5x`pYC+xZ9{7amO6+_A9@7`wNmxslmy{>7X;1n0~fJ|`DN3Qjk$v6nzCgI%L9
u})$5(<Z^Kb|_QTRz5r7^^NjlF-)nMbmL8|2es&$6!E#E&=z#=_AuS8xIm}$wJ$jJs@)~8diL7ztoZBTENG^xmE7My%2vxDT&Ph0
nu$_dECjK~f>GYe9?h7RT0r&I64}xpL~XT(=U!J(Wp=0_%|e((67hpDP<v`=4n7FfGBMyf;N6eaj9EWqr}=JD<?Kg2OwmRdP{nTm
7Trc@$ocfT{i2;Ly!f-7Ay<9quX(tehOS{lGl6?FITkCBp_`}_GTgzYd>e@DOkY+@9F3#Bz`+zZ%Rr`2w!{>8Q}OrFV-fGyiwrp{
C9)%ypm9x`ZNE})T2%bfg+?4UpFAC6%|xxIjvk0Ca4;AS-Nc;m{<1hu7_!xeY3nMi7JqbBB-0_IyYPkGvTfx80kMTt@A7F8M?`Ql
i@+}WgEp+A^PgV1zQYzS&^=dKoOVs{rea+Wowd6b+O}2!2(D)MUPF1)gE|`_<sI&$<C@7cC`4d+ctniI3xlw(_dA_VM=A#vUiCUr
Sa-kVGDm+X+?0;msE*Rtjjv6^Gsy@@hZ|@aVc}nvg^q)uO&F3Eo?*=!@#eXQX@q@@of&;bY{XR04xSU!#_)rC@2%;3K%hpxa!J=*
3oL?ud@>@PYB<qZ>!X$82VHud8kalrK$-y5ey7(fK08fRjJ!@*U1nI~C4ZAUlvtdY=P<Ssev=*c5zcOpP{?Y4SAXCwuJbSWE~DkG
Rc11|8ozHrh*C~52VZIGjmNblaNT7sg^EE5UV1ecwQ0v#EX6oBqkoo9w2}Up-KC&QT77nVD0ZL7hG!&IwF!gs+0b8Qoqy01|1gCJ
DH5PYv1H`lXyqmp7^^5w0GWJwNYHRjlu_9}*CS8-72CV?)7ga={u8+(QB1rd;Y|jaskLTnUZsE@*6=g76e*4`8Z3{N%h7$^4<Gd1
-|1C8&P#28!u>d&r-1hn!;TGW{Q6Om+~?d>k4m*S+rgu6_aeT<Qx^fl^{um#D#Dfcsp0-TdCUyWK!q$JQIdO<Yc%ktRBy051N{@8
0dgEf?@u9j-Tstqu4f4b>ME39byXf2K%bvVr*gaBV(oWP^RY$5`f4yZ;CY6s<ryT+5O#;o^p69%qH;Tvj9TLtl7<k;_xh@TLtHpb
x3+MGNO)w_G`+ET$P8cG{hw)wKQQEHWB{W~;mq*Z@zx(N;}9e2IEZ`#?70IvrgIFZl8%F2K8Fz@KSyr@xIzS|HW42o^h3>o&&R>{
vs1N(1&29@YMts-nw$_P_v#RgnMo|`p`-#C+RU_}2(kp!uF6|^c7$#<-88MM_7U$XcLd5T&vG9i%??P3dU(rHz0zatX@QM|@O)cG
V>%silwk%)|NO{lxy%c}`4rFTg|y{m`9E_NLW23Xu+l9tY%yOYZG1`5au0<UuOheOGn>(_v7inp^2UIeiM9#g|9(4cFJ9NUy8h!L
zuu#_Tk}e}yw3?XZw#xLnFo;`@p;PaW^6s0A^a2Bk$v&{zb`gKA1l$hG^*h>GxMg!LW=cofsRpHmEB(viklo9EE>$8WikdwXTI@@
RPu{VO4uCDfRKc6vjI^T7gQdfQHTc|`aJQa&X(<}|MOQ1dHTA5J|?6*id&}|zE7~?81zzZuaX-pGB>Gz(_`#kc^LB7;HIrFens52
YSAo#-~|51oT*;Lb-Mv93WrjeVARVIwa05&cA=)Tdz8`6Z$^e<q5+GF=r&Sx$$>&u<^mpD`D=g_R*~P%#!#D4euC*K%2vC61=Z1q
Vh$f~kB%p*qVqE&EG`wa&tMjP?bJH5B$pY7|E&k=&^GDkW4{}6xnED?yEQ?A{Jl{FUp(~8v$xKBm3@Y0GwMWG4tQZp<n@Q#c?%{}
_JB3OlpX0Nj3aI$e5pdc<#jhY#z!dan7ppPXXuf}1B^B-W?q%bd58bpi<Oef#YAv~9a1t`x?j4DcsyycXF^*R@aMe3x9;PkEsB~|
!+|Y)Vmh47QNkUsoL(}*H%iR2m|4J>(UyfGAmfb!2&ME0;zBzi5ZX?45+Nv}6NA{IA;3@Nl~1mb?hmTH&gPZ6C6G}6MMnjVun!Bp
OuL4WfBKG@kxq=M-Wr)ozarzpR?5M?w?G9AD1&1#rM1tk7xoey+O;c7Q9v%#8Jz+siy#gUZJ+Klhnmz}yHzgi^407c`goyhX@vq!
H1<7qYYs55et-4T3RIgEv+eRe(ZOnxi$QuAbI&oIq0a8$5#6<6F!jGOWr_<&1itdB3BpIB6w0EkEZjDByM+|zL2e}Kx@G24j4vrJ
lQxzpP`N{O79($qbp=j|@iS16jOe&tcM+_PGhW1cnl^H6E`iAk&uOZW(vMQ3phpW{7;N_}Mdu3Jh(%`>HF0yod|VX#hs|?}@X!M2
L*^=)Yq+sIcO{>?W(tKZjK0*)bWU9do6j4gZq9v|Gj3c_kIqT(%5Zg%Y;-lMj|=vx%}}EZ%G2S6n!1xNX6U%o;dE2a_55i>gaNJ2
kC{<8@&|r+AVWz5ee!`j5ri@<t3$XPBKo|LFt3NyW%JNe734|!xIF~+wo`;+Sp$ZmKnvxk=Emw@doewZ;XCbB7%Po|cd6kHe!0^P
Wm}=yVV{k?5kj(cLr5Vy;TUg?Xdy-A^Qh4vfX~0ZKPHcwFKmeB(_RguP&ib(K0V5662mZ^k|8&OC`r9`?$U4@@%L)--A5BTAmv%c
#6V9_;j)cCq^Z$f{0tug$}?{pnaN6<kYt{Y=A7nr<<(^|Jj((49aq!^%Rp;wl^iIl`Ay&5Vo7`NRys9+$1lc}yjJn9bGEU;_!mxz
KicK1_R$mUW;J7MWsq+zHL_a7#52e6=fs9qV)!m-tYmc?yVnk#D$T|v@no61?8qskiGuMo%*?j3JH&vA?Z}LEUADNZ)N624mJhvL
Q?xl;ZJadu{|q&F$Z86dxdQz@%Ufy5tOj<JM17>gIqAkE2aGaiQjl!1SmTCPUKBeH`-YGN!JDC@Q5pqP3h8&}Z7OPjl-bOD|DD#`
jRe?WGlTDwqzi6a#Z_z{J+cX^7m?C&Dz@aMcVS=fSL-Dw2!H*e^p^Gas2^?m)E1qgegAW`I1U4>I{4nptjK%)h1(3wUl&^wvsrU^
m$Ld*<Vv6TPeM|u*f_>M;1fqTe64+aXk`g=dt+Kiem6uCH-z|mzuz<6FMUDz%BL}{rmepjU+&p0AB-FE6Q(31l*G!^P=bPyvgu)S
6WlgR34Gv`y)2%r;29`!c1ZH+Ud@De%LF&Hi`>{R$J>()$#2tcIc2oV3V3tspE(oJcA19j@7|VlIpxrg<)VtU$tr#5?>CB~Kf1wP
^uGLRM$E_*X3kd`t-@TCq+6F&7w8qN^cP$z$vfi|>&4YTKy8JS%fX5r2gb%fiW=Js@lD>#?ku1@ezPg4Qx8D(mpuiuYdXEM&(Cn{
4tgz%G>R{AYu>R&aFO?ZPPi>Ae3&FC1LW5M7rIpBhDbp~s*R;wBX=lJ!<<Q=+Agl((+-3uRu?|$nQpxZmJPDXg5NBOw?vU2DeP@=
j4YQ4ZIBl^WxLLqXEde<3;@N~z*nrX&ZYtspN)vDbI1P5*wQ4O&J4S%8MzsqBI_9Iqre7g!vWw_KoqSk?WAZ-(W0?RHUJ-s!--9}
Kvjt^#6*{eNA{}2#5UFbIiXHr-od>O$QgW68;0EDCrNX`lFbE3Zz!3N%4^q&U6>+l#Rz=o96D-=KM28;qI?M)Z)fSHEk$=oLC+l7
1$v<Vc7q9e7L5A<@1++1JQGXU-Jj4?F!nGRzO~D8t}MXif;dfgHkr0uvuTgUc4|;A01PZUKjm`hd<g{b3ZYOV>4@O|87sI$XsHpO
!=DaWcg-_#(;mp)q{mK)P=&MP-5?s%0{Td}Y<wDnHt4+{jaUk$@85E7fm|gOW(>0t=OksE>gjDif%;n&npOz&Ui4ysz9Z&aM<tz?
cMz#2gqu1$0-S+4T)A{iVwrPrGga(J6sjj(=Ny`dQ+DiJ&uq@$L75{8VT`SgbFu)Lz#1F-Kuskua21RLH6Y55r9-8t|NlO~Z)Asc
Vx#4IIDy7VgLY<0gg<p}XUX*N=s6XKuE2Fg+L5nns`F(r>MBr_#D7WE@#gYJ39#2I3^q?Hm9w=}3gOUQXw6)uvWJb8n+1ayLC!hA
=uxwJ7}-&SWHy5wUvsstC2$eU!eh-)*acJL8}i+!4_4bjtA&How$b7xqk%g70wLi7V#7-VlK&T#CQ)6(DaF`SsOgb;)~3SXvO!mY
y<>`w-C7T3coJgTFf3%R0TAWwca-19J;t-(dPIXci>!a9s)NOMA>H20^vNQx*93zc)>-!GjzBqWUr8ushvErZ?DI7f2YS7t!NECX
1MR<BX^@DxMB6>DX%r&K)Ffv1FgQm5hbyD<?%ps!vBeY$|5;xZ>|5-X^1wicBkA0EZwmP~%)4q@zUi=iI;?$kv)C$_3=i^LNir6_
4{cZ~;lsBdw}VM*v-DD%dsa4Jjt{uXNy4jkw9Crl1R*;~)|(OamaG%G)gQitu{}^uS8@)>aI_?R{|U?ZsWAp_w{UaIMOk`eebBtv
u=c0Nd&SN8=bopE^??_N!(FBPm>BVF3~X{u_$sN#Wu*K3v=GQcahFYnWoCG?2^tbr%LGA6?}lB2-q7H7OK}ta5F4btk+JcFEt6z9
*bVk_EU-Wod^0L<<Yj$9XLxer`3iHKyXX+9yox3=-#um<qlAXQuN&;r)O+E^zM-C!h1`Awks1{j17$Rf%-~k6-oomI@c^$gOTy6F
gD-Bi+ZG)j``+S?ZClKW^2@NGQu@Lv9WY1QSBv?H*iB`kdp#d|-fPYT{p4vX3Jm6N;p+HbmPf$K_SO34F@KL?d5#Aa0@eC6@WKaq
b8!@)Ufm2Cd|$u11TRx!qXgpN(6;mjbp9MFrJ-#Sb_N`{F|3^&@-&OxmtZz~qAw`jB@m7TG5cQ1Y<Wy0&zNCviU2<7-43O5WV#BU
`2&bWy0csIv+ae(ME3|K-?f~7=+6^aL%L3QMW_L@XE*Djp)!{mpKX1|VTC)|c$kAuR_E1cNN376P}>K@YukjVtdf?w00GWh!P;!j
SI(!?Vpng&xd-Z;=vH%M5E!h%VXN_a=>iVpDi$LNzXm1+v@)?06aG6?4P!A;O4I;6rk2d8OTA%~b+zmRA4UdMGRT2rcD>G&a%Vp~
tkInjveHt$7uzU!0~zjBteEfs7CJA-7pz$zR8+|Kx;28!zrACB)*94G?nkRpLMhX`yCQs`*qp;=&`t7s*(3F^H_A)&K~GU!xVWUV
zuZ}SI@;sJ?!A84#c@5)u&MeKKzpEup&EF5ccxKUI?3+s%V_Y&{c7W8CO5PO&{&mfL&d=sB9^V<jeJF3MbMH0^>-+T*Z!cpoqI5D
?D<geRe8nYS~_S)k&i({AUVUw8-bdJLCuK9FE<dzhaT$`_Q!Xyq83Gd1v95=tW6XP{{744hFpWyjl*mH@${VweJVD!$<ut7woojQ
xzI-pkI39i7weNPVd=3=a}n!LtMh5U96&z_m_D_02L{GU5oHl!C!YLlD4>)w%;PN&U@elUiv6e_KW~Y+>T!bdIXeRL<~`?=%DPPB
OVA?*I$W~Y{1D!@d>Thuf&}zhOXl{5G9|5oTdBfdn3*>fey+6RC}gF(b<wNrbkuP0$lqc{cmv!#SB1p)JRQVH*aFcuSJ<whp#b31
CFFb58yUALi6n<ZtPmZGsM_Tr4VpjiP~CM{5${G6$L`D!Mk8#Gxt^LS()h(@`CTEtlU<b_Wa0~Lj@KgtA^dE|RrmK4LFc0O?=->#
S#FqRx9x3{DmfPrPmPj)i0k?w!a1%6C>21??ftHvc+hN&tP^>kjxKCp(_PMMHQb11A4YPMxEos&dm5<tDH~Fi+zgD$HQ#1`03rC#
2xT2)CoE)}A%m4__|2_E67OYbNO`krYj7gz*PJ640Z5+uFX=DD1zAI;3`Nf!UsT`N|E66BBuTL8EM5`I%_-G!zodq7Jh67Ie8pEI
rIqOO8!?{ExNxPUhV{nfnUMnks%6?nXUF3B%k92=a6?N+ucdRNVDLEISzL~f2^0v<3Z~mUY^wpF0CKT<h?Y~=Kt&p}Fc6NRd8r%o
<k{z8xg0Zbm`VF^NbAGqyH-YLv)I9r!H4JK!Y@PDT^E1+>oV(p)}7_^^C8?+-fH{rr-tb(KWT4GaGVgZ4=4dUa8<AVPIJn9AC3wQ
gaNlJ<y<V`z9nqEBRf~D#HQr4rdCN~mDAmP<AdKoicY*&UhdEu*LdO(KgWIO`4Q*Dc?H7Qcbb)$XG>}|3YVVaeYyMaEMRr?!AuN?
g8~eYBFj*TlOAR6Sh<-W&A^*SvR+{f3Dseg#M(8U0R~%fO(q$s0ZFT+4``T{s06$yU(U$i7Ijp4+WTt6$8u2Wtw0w{0=q}EoQ5GR
D(0Yz%5Fz>oK1>j>)9a$ECM)n+4+`YgUAPXW6EgD*<>g@FKzj@0`n0yP!uV3a}P3wYK!&xQUN;MlJ5u*Itn$xB?jK(OIGz^IWbWC
9&-a*ZZ>nIT>}2ngq!3EvgkewSBmW;O~yboVd#(AuKHyFHNMm+io}YNmY<t$GLM~}3u>QsXS6&OORFWe{<d5|Fr`>^bw%JB4Z(CE
<pywb;AfD(M`9_w{zO&1bO>yFuIcA)Jn#2Tda{{;Z&<i78-3Tc9ER^TV~XQb*C-=V00*$lpW8oKzj5@=xa2$y`~{weF~LlnPiqG!
skq42Tx=l${Iy|`uZ+m#@j?L!X@#Z0b<(I5zFQi^o3uBo+jv^(y`!`C!eVnnquR0NwX393DFx1ZTI=&JnMSn<$>o}a*|O<;#Cq+e
b6&!cv&tEMexNppL9!rlc@7Guf<0BkfnA~Fa|9X9FMmg-A|5WF0nJgWg+VQbYV9vXC_QkaIFFL`oLkbipiU)RIF{s%)BRbuxAheo
GknRv2EW~iS#3;vQY&Fa4yne4hI^_M9{0s*1v-ofGNI=$=gC9h$(tx=MbvnINoIg?`l;Eo@CrGjB&?67b()MpZn{fta6@%ZD=~;I
Tw<+{KJP8?_!#)ikB@PjWcuP(RSaqBN*vFeq}wCv!1_3Cq*VxZHe39M8cO~zB6k;{2r;N-iR9_+V)X3CkjuTz>YBcg4%aq<@;{nN
aeoZPyA|dSU8nx8dyH@9leO5XW=ROc^W}f{guc3qynX727|9qv13zZ!koVdc?gdygXnurk&KZl4J}P;ctn)_1)Rljb?z6p!P92_N
pNl&cnfQ{GUJPiRB@Le@A8MYZUD=0_mFZ_O_08;K(Lt>KIDJztkKZq6%+k$S`((}7zHW$XY3iyc&Ne_k2p+at#`_k~qhK5$U2Z>J
@<YUE?TT3wAfhx?W)ZCCh98`#1Ol?!`E#wn1t50Nfp<jnX`Z;aN=D$V9J%ogTR2o?ehz!IXW4~Ge-%f-Xpq(k${zRVRGK1*r!VLV
id#s4*sfoHE4JVTT4{^nBPHJ=e1nMNMITdPOG$@acvg0B=#>6Xh0xGcuYOJDY#@qB2&XW6;5PUm)}ZWuUA(xwXqh712!x*(;2|l5
^_<AC3eWNJ3Gd^Y8J9xM1bg3ztU|eX{|dVq18Lwm<kGa3m+Xrk>mUBuM=S;bJ%*sQgr`W1KvtX*`~JcPL@^qXkS4@iBx`_X*i>HZ
li&n+=e&@7jPFixu%paPv!B$GHq>J)W~lIttoa@nSM|DMZAUc*ZaQ-b*$JP(kCHktOt@tBPdE$CXP=agSDOQy)T!-jV7najTz&GQ
Ap0@`7)ORLB?P*Q^+61`_`d<If7E27AMQHbzM-nureIfOcY0G7RzoQ>$L0Sf@X^O>2Rh0Ki_eV264phps-ygB0*pwPqyR9O=H~ra
$*M{?$YUyV$>VjX+zIX?aSfq7(6LyFYHqU4xF{%2*sc@9H46m-%U%1ng6MJCs{RJUJ~w4n9$U}X-Wnv%X5r%+f<2QBVGFGI0-_lH
(~wRtIKDM@H7?(|L$AiBB4T0A)Vdh2WvY|ic}f!)aYSw9dG8qTxo>KynX!(GfaUqcVP#C-#u|L?wY-9om{7jOy@ux3JshZNN0-ai
KIW5l*%JX@p2wO@#V!d0#ZNgdikZ;&1T(@9f#1ZHJkzvJb>F+y&gt*X`0KSU=~?4ol#!BRy5e-Q*weekR>Za=O|Lh60ve;51tW8u
+<$O5l@4mZq^H7djgaMy2+V^2(mJ6SLj+nbG(zz4lyh|2ncyq_?r4P+rVioN`kvMw(^RUEeM33_WtHMlvKQoXkYR&wd4n12-Rj^{
dz)C<zb+|1OW$494z*lFqzL^lgq&ryzLq+1vs2)t)VXHCylit4;eBwA1#QUyfzU0F*hQuD%wxEY{Yv0p8HWsy0>2R7n2obBb(DY!
WI-Go&c-mBD6?mjqRt%zW5G{`@b$8Z6rZJ6FNLZO%=r&sOW8u~Kv+O?YQdq6PrIh#hgUDU;@|}Ee7)qRyMOg;iG7x)vuer~QaPc7
==A1@*Wn7<`40`ml+(z~>q9edk9tOi1*N5AtRNgg<En@e0utmjg-8BA$I_D{CrjjAWU?7trdT$^B%>9w_EBIPuMj#v>Ex#gP(7!Q
J0-J_Ho+e_66^ah<Y7MGNqDsIR0o*%O;*4nhhIXV!HIxwnJ5D+#Ap{m#J;>f`bi)~9`f8j2N=Y)wN1Mejxo!;uECLtt5<KZCwY6l
2SH=$)=UdfDySYE>6&Y+371h&Vvb>fEv;z!>j;vybf#g)|Lj}vOEEUqAv+>leV}{-{up*7$k#2DXa4r*vT;?K>G5y>Yr!~poH`T&
`&PuvP}LUk;s+SgTu>~vKAR2P@_(#tIDG^~ViPI@=_nHiYwUGOz4)Bt<Sm^;6uH8Zvi~L9C?_I(5DY>Z6aO+QYiFNXi$TdkB*tY4
=l3Fxm}b_YHf99IBX>u2Hs3@OYZS^Laz3?+`~F9>4@IRm!1Jvbg2kfgpt~+G2uWp4f(eB4EUGt7O<B9LtrI7JAsSy*ExK1V1Two?
3349`Zo}W9Gk&Tp7?>pOx0&H@fo(O0;Ram&8dUtUuu}m6;}SyiS6FCtZw;R>#E)7wd<ubh(f>8j1$4MMICjzF5d4EC;+b*8p9#zn
=y+Ny(;Fu47y$$3;jx}I@1_j~nz<}BUvH_l_so&gE6mUw@8bdSAef~3swx@BB}I^+n#h*2UNn+x(yHintUbiD{-0=n=9r~3^^Lwt
kFk5v_bC~~7mtF!nybQQ@(W!xzM_BA2RcF1O2V~Wj9XpfcP$Jy1~S?20WHet2O9-ZSA58g8tfEE4XU+M)ysv7nd&w#Xdv%+E?D_l
fUB!!d`Xy2{yThN>DnoNX=NnK79#`Era^AeN48d>CH)ARwWcb_vK&>1Ej`<VvWIL;i*HS_Ox}rlhp3>+5y7NCVP)xs2ZQbTKtlfb
y?MI>c<CYvwB40|LZvZtx}v?DeZ0sp?3pcl7{Kvq@-k%2-qb{#KYPm}$ba0yzO-^LSRYu|$>qXZOUnk^oc(pV`T;K}*t@ymCiF~a
E?6lb{!<m!9Bl}#R2#JjmIxt$794pLyQSN<cY1pba8jvQ^xsII0X|}1Ze7t_>yTd8^O}ykgSon<7GV}w2;o#QMfRmQUfO$${Am3d
z{Kt?=<Ld~_l!t0SSw$-Ry9~}^HeFL+LXg8SXVpJA+c>%6Q^kN!_uVCEx66-UH?sn@jUpTHh(d=LEGU*c39J!D<=7yb?p6xjfHmi
2Pfg^Kn9WWn>7llI{q~pZbw8aU!kRV)+MLjZK$RAI(H{9lfj1Cj{_9IS$YB}u3;u1$1lqX5g%NCk<P4w^J&DZm31RcvJ*`|VqVMA
d?N+$^IUW)4n8p%sA-v_9E{Whr&OGN2xX^djIH_Eo6yJVNb$OdJ2ViqQbly)zo0h=LW2KD%*&~E;L`6&2R%4gV5w*G6s&unpXwoR
<%A;NA$a9J<wI)G(H>mcUVpi4dpotrvE-2&Sl2b3bx<V%kJ0hjyMl0Q(FO&%{dXrlN=oPs?Hi9I8&jvXb2FyirYWmCvGIa`Z^p7^
L?I=B$(0+nD<3&PTw4`RLq3!*kr2@<xX7Dd0WqZr2GGZ*iKjk|%H1F5eaAg(**K$C;+|8&5SxEZQ<{*7gNmiTvYugqK^#59^%=b$
SIn+H=4=MC5dB{4^jxOH5sRUu$zgx#V|2L@m_41Tw2Pa=(K~hp{!}VT)WeJr!nqU3zx}+ZvXsb3UJGNR<^<;w9O-%N$PFRNuIs>e
q(G0yVZJOGyL}@F8$F?^tC%~q25UOyJnbS2Wl{gA-`l2W+W@5bnGucd{{i<~_A)@p1iyuo!B8j8f-3~e;-CERxWAgHy@;>yk?C%p
bg=BN3<Io=rr|!OtW_|e9fK5V&2KO-g7sK9-_;U*5ul70<ziCo(Lq@THNahX6%c-Jb>(x4b>m)-KqSWOi_jWzP-hdlR@Dq-*jg&u
0a2iPco-P9fjvzQEyN>5XkVr*HF-G*uq>v46v>SWU}!1p6b^%^Xhymq;YYk^fee_Xy<;$=RIgm)9w-Wr>(Kh;YppyV>Ay_gmo+Mh
KN8#njjyQgp_<rTf}(`G@~N90Jk-=GVOHwuo~8quR<j!LNSwk+AbU(=hIW`3d>S2F%iY2Jg6SOw{xz6H@~?d38qKkO0hNo{<c(HG
)$CwD2N$rK8|Z8A-@27+9eRPSp8O31RGhkb{{kF^GQ$=eMt?fPw?hYm(9PbG2hT^CM^x?;4n}4?^GCGmnT74_)XFbAcoyHZ6e`$b
unyL0U}mzjL?-Iig2q7QMo&y3E;)0?+sMIgI#20V>DZ9gHTq;0I}M+5p-}Xt(WboLKtA(>mTv+gx#QOs^TpqkmJloJ(j+cgo{=qI
7B$e-Gzaz1n0`v7Ae}V~TW`i9!?NHYq_MeQOD>O`t%qSQt;hu`KfPT}2bbqyum`j08pmN5RK}dsoyyIP33$90kQ&?CDgBi*ObQyr
z6zTUc3C!(r42N^<)VYZm}?prZs9Y?b{6tS0FD?Ri>cM;48A4<NaLO-#drCgP~igkK%nw-XF#Q<mPd#KVM&<uz)yTP;t6b0S3@Ng
qMFIu6!x+fiUw&@q*CyC6H1ULEKxa5zX6L=#vkbYEt2z`7lqt@dEyx-_i_tM2ygcorjSUP@RD`lYm`YyRy>JIk+K+6axosS%RQ9S
LrH2fpxh`u|7O3nlodiwOMk(Q8Q(8xwxGlm<be^Ww@Ofnnb!ZZ0|<@kaOV37sd*pg;@=U3qZ-Vqc2hz);Pu$?LrbPmZ=E4W7$E7e
cfO*9zP_Fp6+w%(-;Aut!SIoM@=U)qT`m0$DdN6QH9_9N_|XFWVR-4rD3J*T@5olZfa4|m86pIzs`EIN#4gZqw+`m9I3Q8W2FS{g
z>}%4r9#jd6`S25p`GE;-VH9h)CMa1Z@x>CsHp3XMUV$;LlC6uF6NFLg;{tG8j5`2Y9sFKpaL8!`Q{e*P~Wd28fsdLuQUnDV(bNW
JnNSfhvn>MMe(HDcCH?SPBzhii9AS~ss1=qgO2V|sS|z-*7%<<CB(H~+TKkJpw?<GoUYpP#e{Jsgr--FfFEt~^tgA7-5uo99A^uA
HCh5&&;IC9*zj*M+51Qks;_!aEX6sE6f+@tC3Ik-GHSdwn`O$BbyO+l&aB12(P3-MGtMYq-1G_vF(=I#W|qhEGP<->ieh(}#x_zm
_n#kQ^u5+oU_4}*L$p)~wbtDcU01~R-49>o6zL$9Xc{(EXx}Fu5Tg7K%?JNQ3Nxe)9fcgyUC44GvKCU*B}hqAOUiT_vH9(}`VYeW
Z8{XbpEu<X63UvD6Djs67@!_|ibZx`AQqmT2n2fSuhlg_(*H4aHgGuIu`k^o%r9p7Zx0RIOh)-PLki-Uti9{HHHj@_;hhK+WY8uo
Dwn*gXhsdlG>EV=W=8k2w@|JY8{-O<I@b;w+y##8#!>W<&@VG+R@5LjK#4@V43$9=gIHiktPB{eCtRg)E?X{veMi_^q#3~0cgZ3^
mYlw=vq*1I9^W!m!R-4;Ak+t=Au&OIIZ(}oNf#_t@U@ON)*?Hk_J081-2s(270fT^Z0Q;XTM{$`=T?0HPuNaX1wT>rKkSpuhT0L7
kqcH<K{HnZS-z0v!X~J*Bx69ae~R)LLfak;N-DGUJ&fuCNYfmE?ryjGW;+l0%|KK`cC31>fcYi))8?&e9%_y^Ne#?)@3CjJ*26e8
5urYe`4Eve_uZiLRGe;h4J2{+Ps_6vfEdWSvh`ZGsE@4@rOBV_^3XwR`TQFR<P_M$TG0_5RY{})xV5Q(0svh_LqF|*;qk;k8Knln
dQ<NCkSfm_BZkBkuGLlyM5SuDgFp?BvpQalEdqP3tcoSgk^vK1$RfPcKVtY<4grX{5#q+nhv+R+P6H6Pe*6<|i^*x@Wq0kDV<CMU
qPHA3=|g67`4De=7?J@_jHY&3UaH2?pYSlIvi5XBZn`<>2EhSxK@$x4J*q6yRtYPN-^t$nnn4bziZ=>9i)?;JB-#=_x-VBugGOy=
ei%pm@nhg$r4VEdb;$9q=&`T2H|!gk;9iJ?YE38GOU-_dGYSMPLx}YGYz2hE``bRwRKXrq4yuI*LJWaZ)>0ESb2_!#@6lF7;n*K|
uvadLtze-7#p>ek==^z2vy=bEg58Fw7K8!QJ8N@H1GzQcjslB&wos)R*uVi4S`{GD$N@tJClb&?*bJ`ZU7?jRFXV{@+Px%0_NuNW
cpOOwtSBBccZ(em!{l&VZgf)$uQoKB1Bex3il1o|Nj~>it#MK&`gDW!l3Ti#5o^cC<G7~w;UOD35Tn(0*Einx;v*Z%=~&d&wZ9-o
A(&yg@4QE~(F!R%I=7@GYSZSK00mm9{t`DSqP2+h0Zn^b9ZX8a9}H61e~f*n^TO}XR!hF|gj=qp=fiLE_BMNd7>ntcE70X}6mzTE
c`*ct?jM+lHoGgZEH9k-bU9}X#z4!%&r_W)_h0HtFCUJ#41TTLO&|KDI<P!>t81rYI>uO~O|1n0IZk+-VJqpWsul|5%9CDXk8K-#
(c=tPXRknDPXEw($CmCCS3c?5+lf3|55AVmx$LL`^JlczF3lsReBK(bCG9H#IPc?Rd{@%Rg%->_72F;aC5L}`UBU3_a|wMsC#o5a
ut!1uiK71v1jb^Nf8?zg2vugWkk<|kj3Vc{G!sgChK$Se^_O@ia!*n*z0=1Qf;oTTJ*A;75otlYR@#0!0Jo>9`4|RCg6(yG%wV2Z
_gkscWkCJoqnzM#)&+~Y58Sn&@XE-EsSHfwNnVl*Z_c}2Z)4mE_=6ybSJ<$X16uwXyidk4SY0C@Rtw+7jKs@+qUzOP-WrVgr+cn9
Jvjl3dab|)EI-Zm+MM^H7b6L!-oY;I0*s6)<SAi{vCE~tP*DkM!<epoE*U&G=$uxNUD$q0=UdJ~Gbr7*^G0{9_Vi@8s)<hU+uZ8c
(L4fBc(PLZN+Nc02qI7-hQNWfNO4|%Fr*V1F;oo!Rx+T{E*mzcsd2Q&GF?js@ZNcXDO46hE)Co7-k{dQYZ5}(+3}|CnwGP<W(Ql}
wl^n8Y-(XsW4;_Pu`HOG+c>jJ1XT0UQPveS+#pbykyjz*@p5ncMAxRo1`i|U=?X&p?dl|lQiqPi9DHU&?k@Jl)hBWtZb9^VjxvAn
KwQ@RH^N|v(lnN>%(hm}>fJx@E6cpkz!A_c1<N#^#BWmW#j}XSo$sAHuI&qM5puG|?J;@dM_+q9Sj!?Fg+$i$EG%$!#uxE?o9ie4
*PIv8-_)%3vmW%|5OJR!>;Er!GkK`GJ73E^-KM)GX{tLFR$Ej8mG~fQaK|>%^$1;0&fIjVQ{sNt0C1W_t2K*HwWzmB4bck(7n%;G
5dr(Aqf{H+pFcNOV*x=Sr6Mlwl<=Mv7euTzZq7+c&|=_R_FbDpQOo-0uDg-YR5%pqg%p#e5}-yEYeuP`jzMOJH+itjCQaNsmvPYL
yT9RRbS<G<>S%MSK`$c+{B|#dUN#0tVfWYxp;uskK?{DuG3N3KSKqq~*t*0+L%94n8vaGU)Gi#szL}#7joAVQ{9%`U6TR&hK0;Vd
qXqJ%aCElK@-+rlcKyb}Ii>O4Elvh*L|b8S%+zVuLZ@sz&ra}FJNQua>k!68PU0*&?Sn}u?Yx5cFwLyh6@7DMFUMf36*3Y@*CPsY
=BIf{%SAK}*JMy?asF4U&*R8kKJN!2)=p9X%komy`Y^_95(o1^KIn!hy<pxAX^l*WDZ7uF1{TiJr;cb#xq16)A(GtWjR^$s!nyPj
7%RABUS(G1s(Ymmr7=Z8l*i^}8N$r=xES})x4^Ns{{f{+yrHSR!Oj3i7VHpufpjRM-IOAb15@|G+K&9IguD3RmnZ~Oh!AKNNtoDQ
IQdblBeGMPE_<c+FcAxW+9)ZDeWTd3??olN3teViuXw69bM)*GCwG{!`yc@u&lhY(rfTBsO*TzrgX+Y+=C1+EhrpQv^{3<hMHc~<
wP&c*O`xM~Gol6+L2<WdDkgUFv#w=6)T=a6IwXbW7C?PbOZvgCn%u3DD(>D1DN5*J6u;`&#T7AaAVE}PctX<0{*35tq*!8B@QFba
_vls@7DmfQnXNlQQUmszs?4o`;$IhoYMKgUqJg(8hAAgFPtOe%Lfm4G2FM9&Y(CHLwtoj|Ul3Xm)88*uO<y*V0h15OGDQDCXG$0A
vaYbO?+M?nI0cnFCOv1TBlHKHgy=AcrSti9fRkSC=XXqtrw~e1WaK8oY*`Dtl1G|91$$pRrzhNVIraesHn&4ICzOM1TRQRm(Dp%c
)^+4voMa;(urLnP4nu#t-Cc4!jyV_4j-s7bM_1US+za1KLZYnLe-c*PuU6A#BqUd>NBOAL9p&VbVlxa($c<P>t?t|3-li#BBujKD
wb=@UeoT3Mz!JD;)J5Msaohu})0TxeW4kX(;|H#DD<x+XJAh$o%dXnwuy-r9Tq>vAsNYz1J|aHG>I!V%_nq+@fXxpJbQ`35e!t%I
SHYsIl54r<hTVh0{~~Md9rn~ZM6RWLkQ^JjGiBTfZ$hs%^XXoUN#7h=3p%f+$Z0MI!h)6hQsGWhg%9pJvKeO(7j1Ei=<bT$h>9CN
5a&oT=hG$fyCKVwA!siT7s{{yOX@`{ut~yV4mEY$9@QTN9EK0U{>&`NSkq#0M3={qkNy*|_RGAeb4)dUD*UxgJ(t3@!}ZC7xM=7C
mbv7?fHQ7c$5Ci+DP=URxTq!Y?FujlV^E@}#&hsyF*yc0gayWY*=mnPDpe~3+E%RM%=7TdIH%UJ=gxJ_7|WUWY|g+4@npD)Fu|xX
^2uf6KskN{|9Q=ci>4a|^zBY@QGAWi^l7O!Xd$xjWYK&P?_Y2~SEf`OpiJ?o@fxzJegSKXNIf!L^7TAA-f60h9V#(N6IbV3GDlXC
lHQN1RWK<jZYgaVTT&coBXb=T<ZTA}PN>G6iK9lOqoz`YQ~0;y_IfqL#bcc;&Sv$QDUH5szZ0W_C(a9h7`8$MWcB*aT0g<2x#a(p
DIBz(7$xBCUXD;^pavQoQ*`xB4bq*~4QKjMjL7qYZVyqrAN~#XOv6jRTW!T7ai<cDwm)EFy6W>uKekMZ)(=j9k-=XCOV2*v=|`*?
#BEk;BT+Bgr1-AeE41hg)dI&HL^39rC?LUr-9Bx}Ltv)|B0ZY6>y4epf0cDz6<kE^kA9fb11~@E?gJTU#vVe&-aXPe;s#I^+N|Kw
K$)9%)|%lW_sK<^ewsvC-_f`81Yrd@-DyBbtN@6h0?H@zKn$uuu|Pj_g%AR+{&4gb>q#xw0Z@9O3&<pCYw^^FQDv2Zc!_0;-vngw
nwHnjqCbq-szQD`o&BsgNr?W^-yd4F9jOUeOCdLw`VzFiL&Js%g!vCu*v)yP#VUAn!}97c<3wGq;272v=AmJslqWoPr%};$19{_}
f&xs@J8F<^GXjbVBU7W-<<`4>KndS=+!Szi1VxVdqnTr<ZKAhgM}Y;pjMq^jwkHr}sfBFMT^Bq{2A6srL*DESu<QlKW95426cjbo
&L}n^L{4O21#Z*OPY{g7_Q6wN+gj+%DQBTuqXTU99ai>mW@Y9+L0~!ecM_bcrS8%2Q`%c9p~(fXCaC`j5s%&12Q|#NRg!l(QC0G1
$0DedU`GSg*qKTxuQD3OCe8Ng8<;ETeUres!dd4W#hh>js!`}5Kf*rg7D#^GuWgfRNj-NUmd~5NOh;_7VNCN!JX<dUD0C2BjcJWX
VK;NRtL_Ii;UA*EqMvGDh`J`1@t^6|EG<#w0V&mYAINfyk9u_IDTJJq^o+}W_Cok=Cf^N!7w%Ee>DIwzQhln%^Z%0nbV_EcZ02us
*e3HH051Qr7j%bzKLee|ZQ^aCT3Cr=UX0?BQl)cfo$_`iO;s-k%~Wf8mY2WU5-jfFSa@3uOa0Wv#N+Yh4Kb@kWAbhxP6W?<8QkLy
d;9b4IQJ`We4qcu00nBzLGV5B^E}y0hDU#QgE6hgb;jhj(_2Y*uiEJ>@6dQzJl`>XB(Nzyx7G!C;QL#YN>hM!q=Ti*GsjyL7$En#
+53svL#DgFJ@?uR6kjh8O2(T@GWm>Y+IzAvfT%WHTQ7{L^$XU|@fTK8KE(y*8is#|{v#+mfI%@hz}b9#!Wu>&Sn_yN!sE}f5*?OD
%7!ZH0Q~~>XY2#bq8LX1BqpkJfB{eb<nY4xv?AZdLoovbI5}VZoebW3T;)e~W)t+DN;^B0gL)?%d-F++>yvy>LPVa$+7(oOnToMr
r@1ehsK$k=LhXKGXxlQ<$&>n=Mm$&bYoTA+hC}b2=JPS&B(-x&rlt?XhE|c%@Ig6HXL_e`fG`b5$Ai!r6P=1w960@L1X(_vZ_RWQ
Y2_3K<)yIRshQJmg|M^$Z{#&b#mywiC<JQThwqwy`HTg`4m%WJW$>{xFo}e87_o%hb*lxgWNOihFR5$7y-N7ohqsG@*@Fp32RsLt
wh<4D^o2{Qc;-4?MBNsKP|XfESY)`#E|%l_lJe%K#KUC_;~=D!&UYn`uQ#ZU!`igp_tHL($4w}|v~EG3T9MkJw48$l8sCTspmT_m
8Oop=f2p%JgTZ-?rz|lk;;pfVc;t&cRC4@;upi3f>U0(-i;5u~cDCF^>%&_-s6h3u9q?7A2k?s$ZHoAS<Ef#<6h&1&eSWXy9hw!4
7BmkW)BjZH2l32KW$5i3f_rFEBp0w%&#co{L!L;vMtr7EBvp0NobYxpf5+&{<NFTE9!uT|D=Nggy`rgx_TSzM*A0~jBmcJv8o?`0
#v%lN&G+!>ZD+bxLRwxfj$F3(aE7zR?%t+Eb>F!Nh+&;3<iVG{ttkDe57*`|izm6O+WsPNoy(_2cD-}>u+A`@3j<z993bzap%Ei6
ZcOn=z$Uhwm`nkTh+Rqjn*dnwmUTz24DKa-Py<<Ry>KE>ufe03$!`Atc^(~e$DR4f(Xru=UvYa~!Uf#gYs4(RDUJ<$V|lHk|CVsg
e4yr05MMqci+Vfym8xm048B(4V`2p{bU)W{=%M%4qb+}8txSk=L=2b$cytQ!vVfgeBl43yN=y2Tc%XPoZrd}IxC<5B8RvG%XD@DR
?aNqs!E{1?`PxG)%wJ?GDV}$+VqpH-k78jV(X0#Sf@o!TgqLC3ggnktSme3S&&Y<6A)7jJ?SH;Oxl$+5u$9h6AVQmjKR+5LXXucU
_kS7t4xe_z5-ERj$(3hm#0%en!HLMxNYr865D|Kr%##rSK=_cCXO`1sR(CxAiXR}F0BS#ecLgpGF)!o7nze<7+Gk)Y!ghN51J{qt
9a;XmPU39sy30w;I0`Mwi6as5RWsWG5fQdeY4VklVNzod#+98oHU^t|4riVvEizk4NqeQ#IgK%L<cR`H{{L4c`c3k@_<98o;=~H1
Ub}dKZMN#-@??in(=y{eX~b!v>=FKCk>{NkLcO9u1nX%YT+4ACyVA;K@#?`0=Hj{Jzk}lE<reP}69Yl)1R%)|@F<%C_r=40Ix?RC
I{(#{MO56E`9H6%DvKsixl7kMTEl|@{_s-2bgT{MR6fDT)jZax5@?CXN0+NWgF`Lo3$u-8lW?30MKPV`NZQAIS$Iq+ZGt1Js}3ov
!li_hch4+OJf~zp?Bk#CS&;i2iF6@!O}~+;4Dh)cH~2b;lsUSdk(_a*(Y%e={3B1=1mLl?&G>|$D?=v3O|?2V8@AeH<%vX_&u1lT
+i}Z{EC;~%`2gDEwrj28C134Y1(YbT+z=tgPHueE%%(&JN7>^`cQhv*VHDhEvc~_76ri6SEP*AoArb_%1U2NK2Nl>6&Px;I+Cy@E
Y@XX8VQX<4NA?YD>gVM1J>;vjjx@(Ezl}PpQ4tS0w5qfAS7T}t8QK<mEMPB7d#H@7PP%U3OWosdh-9)69Lq<VGf7lTH7}-wDV22K
g{bQW?$1XxifHx$c%P=YGr)@Dgn;ph<eRNju;6wZg-Id~jk-DT#|?nz69mC*r{LlfK$HjAldY+QMJ!(xTw;-^=Vb=bL1;w?Pm#;^
RKAe8-sR$or>Wq8;1LXA0I|r5ca`Yvvo@&R$gfKRdn0;WxYo<!ZLXZS(Z}mkMqE166`>;1@VsM=e6NgqK{0VMKjwS9187UgK!XFP
=H4^}c_0E``q;*Bzd=54U2$3D_zlZNOpK_facT+ZUZ_BradncPf$K&jvd0MFvV2HW5A={0d24IYwUyJ5f$&<%(0tGfvlX~-(lX(Z
B>PM0rb6EQ`>HsIVbb9VL$XbHvpn$+fvicL!TW8|K#v7-#*5G)=A3IN(O+pZN}yy0vpwTOj9WE^l!s*lIwgL8p=NpJRU#@3d)%$I
=_wCX1k|`G#$~!Q_v_j|3i>&^C*s6e!rSwO8uKs@Uy)>*nYPlEcaU(8=<#?j8){}-yEWIQid<I54$M5#t)xyw+W0t|m~ugScZd<4
#8{Whb2%E^pRc`8HVlDt&BQo~&v-w7zog`vO`$<eN>R7*eM?E8RsaolTJiJX^~kN1^{3xT1{yt`B%}<K(-Xz3-5x`q9BsJSC3%yM
?iAXri@;<y)0RI*-<l5oP9c##B^8+G`r4m(T7W+&Ry1U$$#0w|+wV0$>t?pn9%7c8e|~^mVLGlpz<|<se;ezG5^lDK5uY!0x74Yj
+i0t#3tJZD0`W&+PzoGVbps|%t4kU^R>N4;_HzxlR3aj8q)F#%u(C~{IP)Mn^1HGg{(n@sJTi;DktUJyy-937f^YqJWH_2g&r*Ec
MSI8pU&m`#XX$GaoT-u5LhYD<tJgDi4sGe-gootX477+BSg^R13_UvnI9{3HHt5uz!?hoAp^>#>Y4aEhX;~Q)z>lXQ;Z{QORfFBz
z-XEA2P`qRnJoYT9E48@y5E9=5x8_^4vAvmx0)5A=g3EKQ8I)T%EE}rr~0jxx&#sZH1-tTX%}sK5p}^HtPLEp;Uxa_xH^vU%;7nY
A8q*9Yz5>6s^`fOvmEj#vm$9gq~i(a{@Qb*;Hm~?!_r9bs=S!rER*G}eKIHu+RwP{&Vi@Bj15b(@!fnF;_P-w>s3?-p7>6v*hbm=
JTbu#k<rF%gmGj=m+#{+ojXfZ5964}e0@oaSJboGtzRUb(f<S*2fYR(JkqJiItf!2zAMYy$D1`F^2OQr#7PNDW+e1>MP^9$JUY#2
Pbck#*l-!v0scUZ2w<U=v6%Md_K4c_vBsjQN62RHIgN~#vaC}eb>o^6ihx0m0couXaxBwN-VQ0QDb|=zkIC$@ls(c@?6e~88xBTj
#eDG@7>1TG9)mz~7fSBd`XcKN5bT>ZEP)&T?VC~!3b$nw&^A_ETsroBERbnj2Uhmq7NzIh1%EZXoSZzztzjxH10F(~O&-G6lfM2r
i-YSLL?N2wc(jrs#qFY-MJ1aK6YskGT6rn$z6AIq*M4)G#nzaW#zX<l5ujC<d{PomRVE?wwY73Q|ECF25Ifx{LO*|)*l4qRi)L6{
zR(ptDao%JPH_qcq(Tk3<OSQSa)vz<D|y^*k}Gcu?oE9>rv499o<u<7F48~PK_$nl*M%T|9JBDeD{+4H!|J0Fu0~0tyu)t%zCN@O
n~I4*bWJ+SR7e#D4r0b#U>Gf#eJwoIqm0wrs8F0%)7T@TBrZzUXE6BeNx5%xLzNkHZ24(;`vi&Ng{LNyX&WNzXpO4`jk#TMoRc6?
L%UbIJPuZbu1?AE#z%R-p+P0k`@<EXc|<pMw|xAMmy!#_|LsqxYDX<R*E^;WLCf{$E8!2IRO3T0ARynzvDJ&ST95vQ<8IP6*GuHY
RFZ0$Bm>4$T&Ntt2M*a7HSUw_I+XhncM}gt`K0VlnDy6-gj4&}YUK7#!7u0qA%<H&&vd?HV-{}w&TQP{^wseXOTmeT!pU2x!^;oY
#8$4X$IkBa-PWtmsG9IoEKQV=Z5Tilb+;;~BBh+8@*xARL%itw)hL}H3%m*vUFfCSp@?NO?P*XSXo`1nYKMc22moir!33>OT|#25
YU8<;s<x=IPct{}y0nljmZ#~m1gfHo;OQc=8L`lNjb&}7x-%!9Z}lYM^UXG3G)+j#*}W!za0zpU?=iqG0{<J1(%8*h?VPyU4Wl=4
4}fsB)VVX}zS6(cLiuLS6aB2>>d6^9`9YhwP@W}OJt0%DX{_2S_s2mcIq7_aG`T(}9u9dg&VxdP$NpsaU6XB07OT|H772k|W-H+E
>1?SY3A>9Ju@>Y1{aMN7ESOvxQkxX4Pu8+Vy^-6{BZ<w83^TdvJ3eWJ4mr(ayIW);DEIC%p~%87x?f0i&l?V1-@$_OH;!~DA*CYc
d+NU-2BK!@2{4Rjy^0x=WrFeM8>oa$Ex_{iwX*J{*M)ydwa=J)Y01~$hHh?b5Cy>%E>XRhRtww3&q$ufs5z1d@jf)`TrbMqGIOEe
f>+k7g%Wu&N(2z+B&YW!7tcAo5>SzMq!kaUq4fH$)*N&Br{h?zd-)x0#bSwmRu$|}w>>Bw#WusT==GUGYfY2xY0}sRHcmFZIyuG1
=danbKCp@Wa~jKFn7iVLB&6%3FpYzCV5|1$4cXuK75%4CkQjM!Xt{U741v(4E*AY);JiF&1SnYZbM|(2mQf?VTUbf-AQd-`k)fnc
=8vUUC@>{F#O_Mp-@@*a#*y?A-8Mjgl&l}xDvE*S_`&X@?>#rUf$!@Z)WrAjx|p-DXmcZfU&latd^l)+;Xx@i+C~@RINza#l1#34
q}N4FgyH5l8*D08|H4MWaZo;}`@DV3MlZr2>p9n7@b>l@xTXOKsiYCNcTNKAuu$~gB*ANjL5&wrccFK1wgn$HFwG5>ScK$JgCbSA
L3`~d?;JLs{r?pJ=03=H<L&B%kZP#CIq%3K$N}O@xUWA+Hl3(ycxs7JV>H4AOxM7p-n~Ths9YlC<V|Q+b3phVbkDgrRFJH)=J5{$
cGdSvOWIBLRKfaMiJ+v^MT?QJ{uA&xb=6<eLkS{QTNcCqF_>XYhpb_1rdouqDN~L^&SKsPVx#2umN#+KeAj3r(+n_plD6c0W&l22
w_?_9{u9D1jsh)OB);l9ge%b(n3U;Qa`Wp6D`ZX_?QKqrATN2)w4mi5Qe_qrhbdM?_Dx$IyirjT%gfIXPDP^F@xoJfexiv_ZiiH8
>%wHXQ~+WdVu`!NJQK36+}B#X`;>@5fY?GvhAPA&4!>1E^wm`Nd$1R|KCV|Ai3<Cn+NlB83;!ME=2zOV_m}5B)$t@!w6Tx{aAzez
TLfhnY)^eH1c$(^DB`LoEtB(45JW84S6xg<6JkF%IMqEGuz?bA83L~Y^1F41YWYs$v-o)UUfE3u9R4(5FWU!0XK#F4?X;I`dA@kE
rdDw_u@S@t#r-I71>73n%u>f|x9$bUFtT!CGm>Sy?5{rpwT}GKSE&AJwbOtK>0>AdGg=-fp;x;>Se48n(-RT$7};Q8tv+f9E=I&4
x&eYIb(lvypw23e-@GLtAJSt-e1%aJLuO^EM-(NGQ;%AIYkp=WZ~k)J{^$yeki~KagP(8k_?SS)2nemu%3A2U!!W~KRk+%~SX2UQ
qRPs?&eZsketxo2lkM4LSf+xSDnH+zj)Pzb){QYkC`xI`3KUM!P>hr}OMFL1i@l`XC`zLz_%o@oTG;rvJvz6c)g_t(L%$E#(D3cF
3y6T47it74=IBBwohTFq*GKo&{5C!|U3M!%m)(b9$7LgU{D#Ixaogo)EAFE}GCM0^I4RAI-v+3A2Q>xQwxHC2dq#Fa<&0c>6UkH_
oF(#Z2@#$kyU~Xi$_%YHfpy?|M+8>Fy%4=lo-h@>K(U+mE6BHQPOO)4ShPe`Em>b-pl94T4y*exs79O#Ca9koGG&vK*?-RMHd3U+
4pJ|<g?kH*y^L2O=vPml{4kt&Q)W&=hSduzq@lepEBVwIW>bQ0Wm+Me#X+B2oGoi|B?sBOLqr#^)>g#N%%q?YMtuc}hSMgKA#j$Y
XLvQsY5t*d2EGU9_HTjnza%66$=WY1CD_Ze4O#QyC>))R{#wSdm?UoieZr8>MzRbe2Op>nU`A$(JuoXAeya&irv>P6%~C7<b@|Qv
#Zo6_Yy6M%mh;2<Ck^O4k6EB+hdoQg5VX>_$1lMxc@l`aK5+B;(yggwmrA~e_Sqo)HEOQon2pZ&v+T99iY(*f8C1XBA)1o_x-)38
*Hcysk%sWs0zR^S{Pr5h$_b<J(L7|On_h|j02B5ZYZ`5_A=&9U<#ziG{PAPpL%kzTrlp}PRrH*nIu>P4LU_j^wi|BDe=N_}m|NXc
y1RRttuIYfJHO}MQFeP=5s)AvY}pI$sh|a_ovY~1RF3;=8ycOb-M4BRm(Ul$5<Xg1t94aJp%0%ye2v2-5ya4+0OkdHuK<3O{WP1a
?~g9k_{(H(4zhy9?4@5z$biXjKbx`wblnZ&9b^33@o=9FAQFb9K#0`bZ%co(fvBVOi0Kxu7DUN@tYWPuFclbuL$XkX+FZa~@J$*7
F}|5_9PkbL<Hnz{*iCG>9u)A~C}=->Qb8@O@WS1@4#SP`1IsYfmNQT@QL^i_&{Do~vj^9<xSA+<kO7=LXKE=y=o2mR;up6m8;3!;
g%AMb!_#pZeF#1xPry?`9J6|@uTI&+%%@wuN3jy#rn3d#xzd|my3@Z^L>q7F=ay=b))c95I<ojm=2m<IFu(i!(yjI|X(s&~d0*N4
#*l6OvL+9t*yqJRtR0;$>|K4R!&wsvSUd(?>y=405T<`9n|X??mr>lcV49GntE)C1=xM{|quIY(6#-oXtz~%TxS5OhnN!#IY`xl;
mH!~<ej(bUr}eU@m|3tSZr$~ggMljfVLG7*QTzU-pa2&n3sPKStO)(CO1f(T=@O|>#hf{1Cm=5k8Aagmd}G*-pcaPFJc{Rw<F>`s
0Nh5jiQGxybo{v-+W(<o*si4#g5y|D9h53tySJ4=scy5sU>#+2`ji@}0tp&qg@`u=SVULt*fPYqzeiN^ixf@2O?dh;fOD|RnS~^b
gcc&X(siBzmj>Zr!FbOXG|xP-1!RgIVB6_G)h1J?ve?AO)Kbwlt>5!@Ma%QIcr2^U@%frAemA%Osm;tznzX}>*F>K#1%Lr)E&}G1
<Tjl(lk#3>SB_+&pXjaZ6)(Lsk5c?y?xEFcV$h(ldNw%Lkn6)2rcUt$2PR##`XPc3cQp9CqhmrD!cvN+kOl2-<EbBjY**p;xs_BA
iB}PHY;pZFSg#pTN_qWc7XI^c`*xU1B10KH`tG}zFZCD~8#Q4Juj3cXIfp;ugUNYZ%f_?Dn430TjNddJxI-nNIY3Z`aKd=!I*OK8
^Q1td^aC$H2kaJG0G3mHsNrC93j@_waRGW0!_KIX5p1YDm2Hp@<+aCb7?=X;$?5zo<=dnu^<Bx(<?bwTnPRn#hql+{;(eu8?zb@U
TYL|tS%;ZxW<xgr^q+!}WxiuZBft%p%lE0CVMGA>#FB)^>^pz8wKB3ZPGFP1p}mRRM4Riqg``{)?p0gy7I5g1J@}fzvf!NbIJm3J
dp<tBn)*d);ICQNi>xwv^XBzh!?s{zI$f>>zJ0#()aM2`%n}Hvv6f5%X~n+9>YCYL#OArsbI%X9>?xDEXbi4>qz|os^;q=2k`Zi{
v;IRd-u^T-G~TR3*3xo!@4_FIh<3?<?2+BA-O9nazLTO$kh7z#n!WA9cf(-7xvnO5lIfY)C7cVHW)cgY+N4Nr%oaJg)ZiE``!xfp
^Nz*M{=u?XKDuw~2$|ExDo2|wu5t$;YBZtyKAw6TeUytuVXBDrwmy?;{HvZzcOM^>4`xY~ZZ#(n!x=Q7JhP`;^HA(g#q5!u&pHz<
MhwY}SjWC+q!#xG6k>lQ;&Z>u)xkcxQ8y6mC8BmB<ioDYr~Y{kBziuUczboUv5oxRF00I{QhYBx5>e>If@&MS1;1!0Yyufjy^T{N
*;n~`qsgD{{UO)b^w1k6fv|nMuQ_vlkbboTX07esFvHceH;2;6;(JajSfdkzhN(M>we!I<PGe+4J7^uxXUT#(+O66<fkiUJfI`e2
!#zN#MQ;>C!%!2UEosewo=xKDJOV7--dGb-k@xK+)rwg;h5DnL6+W9^JQiz)3o2L1Cj7zy$f>xz37;e<;2d@Kq_37pdlt5nT$=!K
;>GU+6a#!-*~*K)0}_EC&?at)G58vaz1iKFyNjKa6Az1>#xHsbx{=*d11q+cp97~{+e@^f>s^z1B_3NT)x1v4C_~Mz|9%sl^>r0I
|A^=c$EUhy0@65_M~dwM)=J6#VANej%&Vk-2_@lyF5WLxy7ZFD%^3t7aira74?ROziHMtx=~fwhiF;qQ7M*e;7}a%9j^@`d(;{gv
vOf6_7nNw4c#d;$A7f^vbk5q^7y=s~EfTN_0My_XOuh-Ekv)(_!i5oVlTR4@7x5qRcw6)Vo7?fc>t@ARzt2>AVtVvETh0=<yiN^d
*jXm|Uwc-5!9N;!F*4XL)B*O*$&(tpg4u|IjQh3h<m=LlbvDUa<BJaNvk*FTzf|g>$jGJBTb=vQ$LSeg1-r7GL5E+_>M6H#qrYrE
XN*k8nYI2tbQI;v#&{FQEKW;U+1A=YBU*layk{iZ|Bh--1Yd(c9%**3>yB4<?RS7vVm1bVDjI*o0qsOe>pG+QXla85S^vPy&>Ew~
c=_>V?I1Gn?~Wz9o9D|eot7~ep!@TktsD^f3lkxY43~xPsgD)A!gui(bkuWefcYL`m?@~Wj-1SKay}oe4KMOi;mH$BaPplhj+t`6
#N=G;Kn=<s>I&B3#&CgU;YU|;S)m}00JEU(l0>cMdJ$k6G)nh#4p7#<z7Ak*kF)Bn3C(5`Rg&j)l{yT__<fg+s4}VFX|SPEgz1eo
sZVhO;{vZ9MKjUZHB>_|+-Lf8Vgkjn8j}(X{)z<O1`VW>TL(;@LTD^&rMA}X4Q1A%nm($HkQV>Ta+QVcmB!niBI?i+;L7hq*m+Rd
vKvlOus_hW-h*Ak_^d}RwrieuO-7Z6)`!p}jldfnO$~5OLyJByJa!Av#t*R?mu*IDE&y$&-4+`52?0LW%jj4cHTP#UltOC*0S{EZ
j-iS`ljGlRZgHzPAN~99%4qrI=2;G(t3gCM9-n>XNY+8O0K^`Kmx|(ao2QVPdeoEc50;?4yfAi@s(!uJWTe%j25bufZMgh~$vu(3
;{DVS%lB=6DG|SUDsB%yYTHizMaloZ-C_@;f$N>kvGsTZ5K(iyJm??eE2fQX?X=TDU|KfzW~^JCb<U-@v)eDpI|@(Lcr!iej6}B?
M^Hy64E?O4lx;y7FDH2Hf6<{CeDqi26yW9JT1lo+Ut$(#CnkoM?cKS(xOEzPETtKiJh*!7hOJQG41p&MreQk6P1%p8tGoRI_BqQ*
DoE1nx-Thbe?Gt4l;rtenTX}!J)H2zTa@NGnKJlj1E)^70>$43{l5YnZ^8GAP`D?DwfB#QYvFoPz%4FC*U$_8wH!RBjhE#qd-05;
Tv@EKKSfW<K^Z@@<#z&9kPM`b)F4?SxaNt)aH@DI%3YJW?jG)sVktA01@={tX*aeEJlGEx6ir?PE*QF2MnQYn$iltvdY*P$Z$!@D
VnH`=waIt70}e%xvoFm*GI1@;h$;>C&B37s>VZdCGdYZn<%&^{Op)bNa{V0$7!y>#*b~THb0RmHH4*M75LTc!D)U=YAosGZ7J++)
$}v19AOLmqDcL*rI6iWto2x~QTT#Y#p8-O4Y0Y9%%>I_Pb-RJ36L2W_d(FD8<}(v;9;3^ZQq$kU5nb_Cw*I7FS(d>L{$d!2CGnPx
0I^S&F^wgoL&}E&-tKL~UL|PsA0qjG-2YhSs*(p<8slnA+@W3za<`hiRQaA?Pa7qv4XudBxoyDOD=NWQ!B5JwmAOtM!sEP~dtVp<
wt$>$!ie$LA=GplD~M9%pRx@p%pWb<8a*}>@0p|xq&7cX6L89SJ1MukJHAiKBZw~RJe$lg4c~Q-)goj_+j72lMlJh->PjFBjJ;)1
MVoFB9)AD<jZKRUpJwDPvE65k?V#=(sM9^3x2z=Xa2y3@nd=%H#+hbQju=L&O(BF38+F-F2wpxhC@{<H!6LBr&!<--TAfHlwU8&f
dV24EZ@QCPbkBSB=ovm8nigsp2y%QyLW0L7o<ONmUe#+V_uD=d4+(J4^n;62I=z#{1QKL?N}s{Xu$syZ_<Bb{2K%3~B_iX6d1`H0
T7l@Pl2ulgqbW{z6a+R5kC4Ku_-V4^JA2?k00mmfIfBIS=dtDkgRjw=_~1f;Yokw*ibbbA7MaJ#rv(2yEfEyV(i2G{(SB4+nS(8h
gjgb51SGMM1+d#PcEto()=q65W%mCfn`i3H%@?5UbY0@?eE6kq+<SQrg(BTm!nqhBv+?OerB_uaH~Rs7wgdFdwG@|Fle;X2`-xnG
CF$z1B)4~L3e@o7fMUQZXw<R<zGj8Y>WMmbJ2h16u4oD?EXPH5X=(*Xed6?o1I~rpl?A-p-tSi<-GWh~g0PJ!Ey{1&rKNBDa&q_n
pX6*Z1^n2<-fONDoPMD&dF*;Qnt4aq+;}hqndC{Aum1W%9J;?Z#wouOSv+k2Y%nb?f5dml2z6bY6e+>_UWq?{P3b6_BG)#&{J`(Y
kc<iiWOuJH1AqhN3V=(c%Fg915X_eJt9Ee_<d4!=pCJi)bG(ej4pG2DczTxEX_l8Ci@TPI+liZHfa6w}5Nwfd0{h>Yca;y}fK?u2
8|8%u)S8okpEgM3rnjdb-zjD^mRvH+ehxg9qRxZ=pq#NSc@$WkQdPY&$Uq;UR_1q?0uev-QsYcowKHd{c_nC{oC}po0C%<X_Z=t{
h)wr9^%m#(f6d228eTN*F->l5g`FE)BRrlR2V`O<sY*$OI^9b%S@y*?qz}mi*)sv;5Es3Ke_BD}f~+dOS}w|9s+J`FZQc!*8rYU*
)jIp<gcnPJ4xJ6QUyRZME><564A~#-6JMc`A~Wix>KUgG6{FLW!c>19vk<3imZzxCKhq4TT`kFr%*0g}yf+6Z-s8uJl3E7d8N{i+
$pii!&_8!#igL4)fh;Ad6kcxbu#3SOT*zg-rZu-9!Ob8}&9(V*@0=~CVy71d>!qhA;Q{Q3neT>?^~p6H7s?2Q*1@ZSzdMZW6ZW{G
pcsV|Gb}bYvu_=LMOfls%}j&CXawSO_}0jsVhZ8kIH%jUO7u~w8Ow>aAQ_~@U#m($+D>1wL1`$1;m{xfn>Ue)@Y4&*sm7b3Rb&xU
oS+!%E6A`;mUFuCb0R{&q|FHK={+^`PHZaanCzVg33p=oP0J2`wFvTcCv0eH&}KAlX1ObPSOf=Cbt)%>LZxpj{(N4d9=Lk7LU=iY
{R=B*XHB!QbM`oxpmSG2vRt1IH<%MS1WP)Kk}dXN4~`s}9W;LsW<0!OF1dDmNeQpWJ4|718%XQ8XsRyY>2V(lHM+?4e|lGdizz`h
v2)Xn(PV)L^<OqmTGh86$0gkfsepAVt2%-mYW|Mz3_v;<JtA#-g#nn28C<$@?#;O*pA;T7*E+KiVwO(+w=l=ZIIwsu8UlVsZ!j|r
*~@5_H(+guU`c!!#&r7NmsI0cMYE;aEY=-J#i?X}dI(w=n8&~inZn#-icJ)ba=$Q?;SVEn=kVltj%KPVe~Z)^?dNSv28*mE6{!g&
0p!-u-{w6ZElwejl50_PEp0dn#DpNs-Jpnu)KiSoIx;{N#}Bu8xV&s!XD0QPTWOj(>@B1@Pkynab6bJ*%3w}SK~lNP@%W}^|0{iu
8Ks+z3MZuDd?OX9e1UMWZl4EMr()mHbiHRO7{+`8NO2p68UcuL4g?dV=9!1*ni1?ZVF6dGkc&01I_H<d*8M``@J#9kouS=4)&e7y
9s>a}(IYeliK8{$J)!YpaWcl5#CEhDfwMV?e`Hl4wY$F;=&g!Ad}3GWSEU1K$OH(}t0H^x`b`mQ>d|903Ddl+M`u)VdarDWrqM%#
9f<5{H&NuNwvUlM{Ss!FbW*03J?f5J>^aiSbW7SH>n30xY&-W;XNk6n+Q8amzgfxSjnD(=KiVWw6OB^5I&1_cyYk^yiBG2fO9U67
)egRJX+_0u>z&aW#3-NZY|&L$6Y&DWJOkk0!jQG!0=!<ll<+S0H`6-*hwltKbR5zgQCYvsuV52=F_;im7#flvJnUd0{U{2rV$vWG
2vx|FWCVa010O_xSl&4^%$hc`y3cA+wXM7-=4|O?Zzm02VkEP4QI1UAs2hYjEQ%IaORJb1W3VkByCwCGAB}ru|748NUufXIB@XG_
(0=w=c1fX48GF$;6rGYJ2PVv@;Jbk2Uz2rLzg`rzpX8K2e4J6%!F^6c*lcsKEVGGCto$UGMW&msh!cL#A%xPUbf~o6cubjc`sbHv
RAW;1|ADCAQAc=${qrGhP4GiJ*e3mZvFrQ-@nLDHn=+&4Z@GS|NK4(^h-&OIgzgCKO@ucJ%q+vkMm>58JwO$J?4RnGyugu%5{GAY
iy`)+d$cy86l1xEi+;`<%=}CP{6F@Hc(!iBf$>QDHoPv#d&bHhWTw4QeB_sI@B}b}t6#K<i9R7`0b?2<(@c0-cD7h2>mjZr=(Aou
Nt}2-N_2oHoVlhF+8X!DmkjZGsfE+;%9l%?`_Mv>mJi-MX$X(GQvZsKZCVYnHpFlpmeN&aX0@fN4HhB~m5Ho)z*RAr1eMI9ld%+$
p}N_1W>&Z$eL{D5wdkt|^o=`BVm(GXHg<)?x7$BsF#hL~%HlV{MKV^6*`bTv!}wKq>r@35-1O%5NKz<LLB31dNZHkc<|z9v<nYB^
EB6kXw~}gWVw~oB=R)Fglkw#LIzao+5jo_I?MYVqQ8+z?n4*wX!(+h!TjL5Qx1-N9R1fpma=y-JTn(TMN0N1Z8lBWK87u8ru`mpI
-ek?3^u<3(qwB8^Za_m6y?qGP`VTZ9u@8mC-<BxkxJG8g!KP6B@SCrKnSN}w(E~A-@|C<Yn@vnip%TI1XqY2t)IGsj#~i#Odi4$_
luGk&_HDebXO{2P(m%TxrSH#F?}MuE9d4b!(Oagi8dl^V_?43-HokVpXrkF#N?Ry=FH!gyXFf27nyn&IW6iH3KotW-qV)WG!kCg?
-nLe>^cRgQ(x~J_;f6jEP^sr=_zF}B_IN&hp$noa$pt>ySd~Ul5f*yfKOPMJUgu~9QtzULW`dX|Ug&_zmMA=#H!Z+jUG$L6>vmp5
8sVcbI5J<k2Znj`s86{}qO?;8lPEF9fqCbGbfb!0$85UwpiU}9-lW>>e@VYTsSRvPH0IHxi{$;^W_)oZ!#VdpwNbV15)^O|I{12`
<_zD%>ec~o#A_eTT_$iUBq@SQbW1X9oEg@y`QKa0Is+pPbU+4D?(Ia|5TvOsJl=Mve|VCBVa|C9<WmF7vxAgglh=tQZt*PlJc_VL
h3|24gL17mBt>vF?bgtnP`(8U>`UYb_=ft$z@auDhF=w!#!*CpG#k+-ON<wQxa3|6;CVK<yAa_bK9>kgbORt5LPY6w!uE6n6*i4(
7~uSti%l;%4ZPOYr?unNH%O)TTwOx4)OP!lcV1Z1*~NITqzm+riN;y&-b;H!vmZ`8LUBXXNwLdohr)8di_Nc&n(Wz{b2c+#Nk%4(
`iUt3pQ=@f(4jFMB-rlx-ooUBhLQ;7_F@uXCi+9K0Ng%aE^C|u`5zVq?L~S409(leb21blWCrA4|8l2+&Qj*37<<0me=Yy2*3XHJ
axpO0w~3z_UNw-*>2twEp}m)j+*wG0iHHzVgO4i(s!7>zw38Z<`8M8uxzv(Y&sp<6g%nkU!y2qhsVJLO-R+98V%JqP%A;YAJuTWP
7(bfIO}2@HOuw4=e>3h7q=QR=I+vBf@K_tUEUy$Js(pzNVhQfRX18;Oqr-?-&SLU0L|2r9g+?Sj^Q(D%ck|mltHM`VY3^ZG!N!vZ
k4T7JhZ_qR-m7$~ZqE|K&);ATbnr1$8o`$<|0g*QK*jl*+tvKMrQ*V-r$u{|kc<+lyxWsbXa|rnN_?kFJ?r*fdG4`#E~BAma82k`
&9e97kn+F8hzN#rb0virndz{Jrzq;~_p^;6kSHUcl)XF~P_n+di>w?5jqOupZ`|0WJ9jm&RM<<2%Zl#T8EYxf$l6Hk;J#_qnI?7<
-23j0hq6KXc8sdB7G%mEF8d+GDPb2SH#Ojv`N4S_xdjdqGyF6Yu2nUkN%krQ6q%2tJ1yk8XFVt){3>RO|FtUJ8<3*bcM75CxWlFj
x5_SULF>`>>!?Fmf7&E&OrU#mbT+vw-)HC$16&@E!eMOCMvY>BX&1oHrm<7JtTbG5Wy5LS@d<XqzaTKcq2UGx8-{Y07<h4QTC3#g
uib<J?xPpl%X<d^1L~ULG--a)Ir8_yIOJeyO&OpQ1CdW2qthSbvw&G$B1y%`Xgybw4rCMD!`h|U<!-Os7b@8l=xGG>^>0yEr{&CG
BfHk09FFkRb74lgzO*~1KV>8N9al~I?QR3}3j3?Gv!QG;ndYHo+52d?qQiOCI9)N0lXyh}`m!V8>CgFr_d3$Ud$e$mNj;spOlTr8
CIr)T<|AxN@&t7&PUO}<NQooa$WXDIZU8>g?6V^ima2%<w;ApJMN?B_T%~PLtsyG0ksW#$D|o^J%B!u)v0(3366@H}vg$<9F&lTk
dfAd=%5YR-+A0^>@PiA!=<m~W>Xav2-+PwO<NKC*sl7v9c0p@mlRE|na8#6NORzpU5$s@;x?v|{EE_AQFcOmOVyQU|G#RT`3Ty?l
249X+z$_|y7ti+d?6<`?I8p#?yv<Nu=v#YBwhko(EM8&cG9h5f<3HA@B>s9!@%tyiH5_u?3^{|rpx!#8nonC{MSWo7bdw!~#PAV_
wK1*YWo`x=Kz%aMO$8#LV1O~0@bxjfYyR`d1AyoN+3>SZB$t7!q^};%#ph3ZrL)TA<5rd3MJcHlpJOc#`wu-S55&+s_Xhp%V-|6o
P&B=%7iWaYvTxSQ2H{No)1#ONg0qvtbE)<D|8&mrz#KmivWpNgOH^NvVxAlOt%khLlK%HA&C1PSBx&L`^qvF1->`}tU&-ddP$FJH
2^?IVeqG1WuN+jpcMEkO!|s&`VL}Fe<9ALBLy)4HA)q3y<I{ZDXgg;RJ?`t!@QtP$9y9G{uacwgbt+L767!daB^c8ZCtPY}g@mu#
YU;sJF$S@t#1Pl)#?%%w($0A+#Dmb*=EqHCfgAgF;^()bIab4cD+W-O{+%$ZB3H6@M%#j2*d(QTjk%2#HnD|acuxFQv2mk(Ttg(e
>4aF}yLaujw5aAe*z%Tiyd_v3rSdXujDI9E@W77s5~H_`sAJX#OF=mMa(!2GM=ED*_DMK0k9)a*GcS6_#$tV&+}FLwjw?I|i_}ii
7-?uV2oTJvdCbjIk!LX+o{Mk&^g0>?uEF(1Ap&cK@qjB0C2lOD#g-_*N$wV@kV6=hi!d#U>{`90m(KV9j^J0Zww2vNBwxmeFp6g7
x~G@MTh-+2dA2(2So~!Uhpmw<r*a=x9bX=(b;tumc9dJBnDm|sXHjXSL7Y=x%x%1*&qmIPU0ulFQ-VnWg1%47k9gN+JOL0qXE$3;
2QnI(G4W2~%0N$fsfCX4&6#NrIw8cpONU6~W{z*g7v1PfVJb`lnIy&r6J<M#W_6b9Izb4(RVOJE3NoT$zJgS9M_Es#<D(mD2Z0mM
qxie6sm}7$zLO6!rdAb97EvZ)efiL{X@EDzgyY?=kOq3)H)u~*P@}PECyn3kJ3>}&D5E_Q5t6sAov)DJH`sltj@MYW6qE6RK%(xJ
JiTi?9#^4MfFB=CBVu;gJ}!fmDrSR^oA@EKS7E%Mf|LxQvZax?DwT8!_^6rvlE{ieplmA$aaKp_tFDA>__akMK~Bh$4oM<`1XRP)
1oL^F<RO^4Kl72I(?3<wW*{nIDO*+m%^tOM&BPLGJq708q=XChPn9pDnYR7XnqGR8=fku-vnNT8nGG?-U+NO>%qm3rM!VG;<thke
&2AqH2L^WH%bv=Euik0Y0%+m`hwe_8=;25N1HhErsu(8vCRyJlrh*IPmrZ!zL8)4a@7;@1d@`r8hcL6UoDpJIPyz*MJg7qsi6chT
no+K|UQ}?>qK#H?>@L56sZg=ssGZ3!-qa|?BHUfFM=40LRD3`0#=vH#9Yw_Vf$k-_iR|0`pf8F!<l!}iJ##ikiu9WjN*Q|k8T*%p
Nb-d7hcrr(&5FufV*byyw@-T}U<NYd$^?g+rickKVJHX~caNqorVk(Le<~E5%F|?lr1LQ5cCX}(gs}{0nQq_p2!EY>)zf&g;s9QI
HW(O}xRtF1GN69Xs^I{)iC~5^>L`($JF*?P+AEk_JVXU>2lWVwv2U!cAoXJyxUGqE*BAp$>o7508)|Zj5NwDD`5#-X1zZ19+0fA3
VJFVm=U24HbN+m<{~*#D`Y5`NtR4FW!fYra$wvt?Z@<)#YQOA#*|I4`$!&U&41CLIIkg`ty0PWt`gBKTMEy%Bz=4t??6HPbXxIPb
-Yof1h9v<P#xyA%t@sUEDJV?j$;xEXQz}B0#piX9=Gq{`L|Go$X`+ZXp#W?4EiA%Vh^`$B<3E9B%S`hSWdjzBJ>*blBN0MYQl4|X
L5gj=niq^BHDyt^?125->LIKQ@;Lvpi7n(0hs+3x=TOR?JO=U`=1?$rFg^W&BNw}ce<Q)g9AHT`4qEojebC^i_9I7n1Q0GU+WD5B
d~$c1dPvNxuyAw<9ApJqPD9`;ylT3ECSMNS0|?AR&i3231-F#q{6<gwu)eRNqcSLxoIxd!nXjx|S+digkYB1@eB+4Bs=|<DF?*G;
X}2RS_q7yLz9V&y@Ty2)yPzxIZUnbXLI|DoE?jR^;AxyZC#fTFabhdLDtRr=RU--yu^cae;apnoHZ;;iJRmf!xu)jks<t+_9vF)I
l^x6S;U<|MGWfI@lM9QsF2RgIvebxBxf2C{o3bIM4S=m4&IXD)twtx#aDtI3vyNBq_cx>)t~QO_ld>NagQ74(D)mT+_xr4^w4HCt
gi%?PK|=8$A$)t^M{G5^+aH3JPomtnwm~wx3dqh&Wm9}$)^6tG$D&O7fIWq+r0_TCU(7JyB9pOTtHbfI=XX~PK$8^!cz>*3$HQXZ
VBmPz@2<mW>;^Rwsl-sjXv1hhTt>TAD56yoU_ly*2>f&Z-^K3|ovt>tYS_GA!$^pX<A6~`!YTD~$^^Ey=-&GirlFD;%;00AF6A5Z
AQF3rc*-9jOzz&4h>8d+J63S)?%Kh`;HEm-YX~90@X~z#fW!t%CYS7cxJTLHo=?kk_@*o!Srcmadf7*4=?(=4*@SPhLc<hcnZ`FY
&oWyS!G&2IuA<sIXeDJiPYM-aaM{EZq!t3mMgd8Nj1}Hf<;LuD><QV@B-dDnho~V?o3DT%L|~bSE4Rh}L`4@7m6+oz#(TpcuAhHx
Sej%xP)#F+LWiiCyKJV!d`MHc1c>W4c&f)w2cZW)&iW3!deTI5ONIF@@CK(6OCypbpRS-DI$F*S=(iugOkbwZN;f*=14$3XbORMT
I5~YAs1fQk5X@>Ov}zy{^%MxwL$~mr;3&v$#g>K_soFlbYRfi}odZA$3Wjn|Ej3i>yx*(9F&UXg2CHTd2cH1+m;YN{_D}#=;w-!Q
D114fyRgrnI$0e)^utosac5J60dTJlInIpDecs$gVj>b(l+r5PxA6G==N9AE6Iu?n?+2CLPwh7Xv2WF%2Jg!RLSw9_VlRB@E6di+
rTW=^ozR!rbqwHI!*^c9;*W^xTRIe$h7>`K>s(7om5rV4Ty0Hit!#=~KhtoQHLu?CPo6$#zomDT;#q--!#HS!Y1Bb6^cJu0!m|H~
QYJTbj}at@Zd<(fp_4LiCN0((Sg{Fs)hY`DQ3>W{*hz!pI#`dOUG6zeZ=E%qE!qM%0WT3+G3p;cpiu$S9X9;hhRuCk!H_$lAbo*}
b-#JVO!f56iW2n)9eo3im9&tDckW$a?TUz1OC9J1sHus{1o#otCh5Y1Q7-A!>=p{J&0C45kV|jyNblI8<zc;BJJFLZPU`^sC`AUv
FN1(_po*-w?yp&7Gs`A25e;<I_(_V;?2y#%$IS%uz^XO*XycKl(j}lO7j}0U7>K*qyyfbzy$~=`JE8wbU8Glj+llJI3_stt@%FZ_
HyOLSpS~G)i9+$Mm`3rsT9les|7s53#bU==f@Zw#G3Q&n)h7mYhCMsJS4B_$+zbble$W0*Z*yzEP1e`=uU61c#gS@Xixc(CJ*W#V
cWLW-w0k~PLS%9<YBj^aN6O=md+0&O|7~|bA0aW6VtFR>kaS|TQQ&t8av*o(0;MxNQRKiK$%)N}^MH3H=p`2X-Z+j3pCbo{gkJwk
SM6evh%fi;@($8+J2vF`j8EJV20?(Ga&R@480C#1On28-Cayp|mQq^qW%m-cQXRYL)=B1QV(%rxA-y7I%zG|y1GB6SS_!7XGQEv6
#891JLvH+0klQ_I%-&WUG{YEY;^(kAddi@)BTcbAuc~OT3Ti(ZdQcG7HxE5y=GX{Nwl}|wyyKnItJ#=jm9F`ozYLCO`KvwiY_o~=
?91Gk-QQrQdT0U*-OlShFhgo>=@HMc*;Buj!#4X>Wx0IzUISw*UlkkT-ngcZXKU?A<MRTD1gMP#*2L{JJ80L^TfrNTLFB}l0t)X0
WsEb+WpqI9yc}cf)&utXvHpk#qx~j+kKqX%;JV9xY+FJm0qCVqS&>i5!&B(`W9_23shN?h(4aV&233a;G1H|UjkE(9KwdTFxuV1^
ki92008S@l-)pL6sLnx6?_?d(EOJ6&mjnZm$J}hs9lno=b(G&1;Vc#I9Pm>H-Y+U2j6`>z&JL(pm-%ese2&N!FMbt!bG<Fw4h}cN
yps+{DD<DXIuMkk`(pi}d~n{Z^KzSW^zaZN^oIw2H)j_M;;Nwqe~y!vEu#)FkJFfF8{I;dAgSzzs0aaYuh2V&?lStS{Q*_+Mu8(D
|Ctp{S?#akGwgo1C|#vU7p$q@H><67_m~bIG#d!m`GI}nAxwa9;iwya4KY8G(l?vcw4OjNm2m$DoH$O43^EVE=fOylBz);27>DOD
vDOHFO#do26ZrgxyS@?eJJ_8COY&H7uP|84=Ro9<@00W_2AE)_jGe}a&W3`V-GL<hEJaPOqJ;u}HnRgoRlS}}YC;3c{9?A69u@&N
_11OrgVGg^1`cvZebxBBw#IpOEJ}H*?q2>liugeB9JqvUZ@#?3Dzq-M(0=<IsMb-icKn`e&F*DRRVUogZjqPSTS=o3+~KC*^Q)~@
cS=M$!kHQf1zh@p1LgU9W=(;waqU+r8+ZMwda@b>NUyrtO-{I7z%T@}4DCgeN}NaK7(m(|0ww#>0BvHiB&xl|3`MoV?!)f-6a{*~
_nyTlYnvvcZ)pkO>nQ;v&g*xKiNWv#SA2k-v*G>SM%3oZX~Jf1)EVQAVY~+zRlF6KRqY`!O3!wP`S|_k{p*aVQV-~Q%u9B0j(**>
kU3xLun4h5!)z*ZnNwZ3Jk}BoXKU9G^xbE>F<8Txf~pf4h;h(YopH!|o&<DAdtDA<*TG+<w$C+oa}0KibCbbMF|)}K6c9D7T=HH^
OU12L>31Y2;)^S`*<3oA5zV@5fx_n<(9}a|Eshv)y3{Lp@30)!l;Hzr<~c4;Bx@0}ryJT@#8PF=TiBk3rpexCyEqnYmbzZbQxzHs
_?EBkpzGF5n<JJ<J5PsSzW&BUR6_&XeUs{efzdxl@ynH#A&@YdW+mYB4eX!PD;*G0GfPSy!+8Q3R^@2<B_rCY!W+YY)D9`69qH!q
SGqt5*wuiPEf?Kh48IK|`K(ZpgJxe!BjetZ6t7<Nkx~Hw3p;kT+Q$1wsEm&l07wG~zR7VZb;Ai%jsZ%ntm+dlxnHSXEdc8Si<J?~
ohQLU!X;zQ@{>@t^PhU9sWE0SYeZo*aeJkuoF`{=8w;05#R4yvu%~lKIa->XnK9>RjK^<ZT6JlwVA9w^#WWPF-44_%aNOB7ANt{k
13xf+;6;rF2njG4#LX(|k}iR3(ZL#;-Y}e1DlQvfcgYTG!r?bj9J8dnR+FGs!@qmN#MSSF)BDh4fz9HU#|le&ft8?i!^=I&479R|
UkrORhYmnIEg(^2a-<{8F>Qc_>IJ|~ck4gZvJq<SEyoixAKJWE9($`UaT5rf7(N|Kvq(>Un1^Y9415x{mYw+^Uu2~I-qF1&Lgr8_
IlJbimno%LYbfReXzmXK9XTZz+%%k7G>7Q)e$jKB1U@ABC(2<5RyOgL<@KC=oR}XA<K|krqz+de8DX6u^Q*h_Du0mT3;l?>`PnbN
*VjWu8;L=Tf<p2#-81`oL3!PaXsf6nfSa?aS<vyrG4@B&Trs;>_ccxhozJCjDR02>GUH);30zkmms9pe$n5`Hz@Q~N*a#HS2cX=v
LBF3IyCz%pnby(Fz|cDG?)3HD?vB6iVxJbqf8kJz#~0BFZ&&LOQ0#**M>_3Ws0lFyV&8ldN+;+!Na)aMUJdJw^JH5i+D3H>>FEoY
dDi8x`mj7ed0YkaJMy!ge6pnu1eB*rgm7g{$NL-WzKl|91IZ!OshW!A7uO&`9I9K^g?{Av-z~6&^-Uki2vW7WBPBhjV&R+(`4gar
9m*0`#pEuyhJOpx8lwnlandJlEXe8#6e=xI|Hr^XehR+PC6_SH8ot#$n6|r~{*_|o*5bFp{r!`T2cPdV;W}AP(SA`_;N-(~+X5Ik
<(Dt;GRGwQRCFfd1bR*;ILSjQ9j4RBi40D1H8O#(9dpW>OkmGBRWCm-b6CoysM3^&Br<4XAjB`qK+b1EM_9x6aM=CH&!MJZ&w8?=
4X>&qI8&gHf$${)$3R4$13=C(W{fQ!%%X=v;in$8dS2Uk!x0aW6W7p;sUopm65M+$+hXcAE7bMBfUu|2D7GWP;Y;odeBK*ai5_jt
vJl^i%;em8cd)w*P?I8_;M(G}QEzx;;g6S=)^&fjN(99+WknTCd`Dk(<(nfLrjP_?kojuV%EYh`2!-_$a55?ylPn2<C*!jbYssom
{rQhVzFKIUr3euhe{|9wwPjbiK+)JmvjC0VLU|Wr^(nu4mB_k504M}leXiaoay(sfqhV#o?)`^bx#%@|<rlr)gBA22rfd%)x%tke
)p7yw({&Ch-Jgk7?X&#ZubpI_I0uQ==G%oz%iU_xJHKXFM&$GH**vVN8B>K&?|zrCLBl)T#=o)RS!3A|w`EVQsgJRlhzO32y(}5i
zwPQKm&X`*5o(?=8CE||rV-{e<fl6-2@3{7_!0pW<2_$<CVJD$Ik1o0KEkw~JS4$vD-SerxL6i0Et%5WK{}R(1nG-x84kI9B^$-B
)IQO8Ci}SyPl>!4^Wwf`2{>^UFxf%vFLf43EFQ#7&U+)cnBLc=(XED<nhw8>#du=^CtZP!UCD!`;&LUfE*w%314PVuXTg#nw}(^O
2$3X^FGo6oP?yejm>bMldax!8dYANSjP;u1X*l^?u}Cx@&AbKTU=_F|QGwby4aK}Vt{0#=3{a3XF2hk+ZdK^rjKVzH+Lr@)X`%Rj
WiE+u^Ps)if!(RPA7|WhwFcZmF)Bf8a1LjkWvL?@4AIjNUR!7@@3v(Dk7a>u!27_`lV1Uc#nTCVQ9cQQ@h~fm09>JwZ^&-a`?N;T
#b@ARMf(bLudJ+RuMCR=cV$zuw{Y$gMbauGjd<7V<*%j{f~C<z6Ewy@#ZyKw`F9nwP|JqRhYxA7#Oh<87sS@y8a5TCmLt8+Yw`m>
D?HQ&2d7DCuTpRSL$e`oUDNgSK%od)byGs77T@oQu4V&U6*HN(*2zt#Lhvr-UYzgOQ(2;;5B}g7jgfMA=cRb$ZwbLJi`-Grhm+$J
em=T{vcp<nw$k15?fO>Eso*`tfDclhOW^tzA@5#c+CAc`tmq)}-Z-ike3`~b&lvL_gP1quQUIOs--;r{us8n#w{#0Fgm3-U5~rT<
CvT6x0-BJStL{!&b98rBOR5>xLyv>md4w};ca0OWe0g}NtYsTR9texvY{dBTEpjqWU_~s@wT~t^X-Y_M!c=X52BzJtDETizK;1_<
gK(Ye`Ro8@_a7YGw~9S+PmC7~HkmE}ZpY!xav!Cmf3D_-hh4(OW4G&j9E#gY2}~?yj*3_Q2=FxXEzau9&xbdXF7kC{Do5AepuSRt
>jD^3|8|W&nMusz<qq#WU_ZtX3-g{<EW*XsaE|}^KC_GvW~T;YXNZh65y;O+Zdq<y3-b^x?$w2I%F98Xw*iY*6G(GFd?H<yx?6^4
v9hQ^y6b2^R<!32MrqJxs}Qt#dO=Z=C{oODSh5SmItrFCwpjo;<UQaoC?lPM3IX=dT93C*NRXtHX!gAw|K*aoasn^vA<F|+YHmdr
gvhR{S5y59Tv={f6yL=vZFkQEx2@nmxD`me3^sngTW8qL*JFg4n4nPGz5!?XeE0(`M<lm8IWWG~#>#IC{(C?vzsNH}v9yN_u{U8<
wBn_&{(Hw?Fgz|gX0Uf!f<^IFRz;aE;`B-I&v;vb-vIi#iY&Ba<-@t$DwhP<P64nuU4c&m=W*mo+^VG^`4d~19cLPK(LqNC7Yc=F
J=A`2(O@S*sq#YKdx?RVFRl^D2)C<cPU;g1OH`h<Ps;YSr7!|A>j<?l(i`JfB+s`kk2z8%64Ei1Aj&oUiu^p<Mzdz1<bNJK#stxW
61O$ojGOh`aQAZ-JuoXxxaW)?9X$5Em3vUl;5L)7VypKibu1}}9Cs!r@VYUS87}n~f|cEE0nC7Zp~%$E2YufKK6HyY9M>r;D_>6X
22a&vpNvLCbKF1$|CTCO2QQXHLNRxa3ukI(7xNBQ8v3VhD>?LZ_9xMs>lj4dxlgmX%_F|@|3oAF*F`)-ch-)%_XeApj??9rn!}~H
e`TC{Ezv^ipl|W0P@Q8uZpEN}+j^d>4}&t3zpr?|pg<W?74sbRc8hch1@yZ|?6Wn^tJK7Au?$xJ)eH`uz<$Mkg241mlEzkG^^gvU
p1o<rZ8#LVtn|hK$+@G9_HBu1eE?!wY-h6=1~aXj46vK^0lw-Iu^%9y`dHkK4sdN&(w1DCO^4fuEjE4sZHd(v;}JlZdUbaPk=>~F
)(j3pGBnj}2cbqUptz7n^uN4!XW61PRwB5a1zJ@EP8qOh$uY=rT-AtAx;HP=Egj0<Z!Yf_RN<Y@EM>n20j(F(|AYO0pB(ZiA%tdQ
ImmL614a7Rg+pQ9nHsixNjgV3w=_)me_i88ym>}#iC9P{+WNAFsJMYl5iTlQKni}7an=wW@B()TjumcL>3F<hRi|pY!+$n_h0wGE
0^wiw&;#SNgPOJdhCP7HF>iDj=t#{5CLvGL6H7$Dn(YrLsxdYo{k?LI_$^MT-$k_vRT@9`{RXF3AU%cR3xpR>x_Vd+5!dNRW`_1W
MK8G$g>%t)jF^t31-O?{wBP6an=HbftD=bk`Hy{ZJGj%Q7HH7ai3$YU*0(e>F%`Hm?$89wzHzdM?xF%#x?8k09irUe&@xBXH5YCU
B~-@S(45k`%)gUM`^J4#DE^9wGCer|!rpl=@qgCe5?=ub`k@Qv9^`!2<03{%DK*y>@l5@K2z9S}W!-!)qVpIAMgEv+7o}H^V4rK9
Y{h)Bux;{JuxKvb1;w}vuxOMK?oi<)ZSR;SCp6icb04efDJg$7k|pb{y~M1D%#=0${d=V$5~4@AGZS19BCD*PLK9-a01V$0<DLQD
RTAZ5dGT(KvQYq9;pp<~qb=oF@Cp`Pi&;kDW+9J8I7Xc+to-duH__<_op8vk!gj}%{>}!`_00Hg;;Ig(m;z}gT?^^^#rXa#Xrpb2
TsT_Wje@DL!)Rt)mOms4JYFtCrU7*lt)OBE2eUVBc#ew1(VFe8+X!vE+KfhgVoRC?e45#>WuYMlTCn23gn<X#?RDu(r*LX=Ghr*p
UQ$s2?XCJ$k<bii53cjzI8lT|P@4orZlQgH<?9;~hfSngf;hA$gwD($TX=J-*Fv*UT(i?+;!((=2rb49#^b!XXP~}0f-iwkr$xwN
lG|_=)H|O1p9Rlp8(Gl2Q1G8mjW_vODa9>3h6}0czl!Lhw1cgzoOkY&L;L72@(j180`_tGFt~R&X*#j>-Ul!IygUBo)+1JSjDn(=
k(se?Cx(kkD)zY2UzDRnD%@R>nwdydh?t)Eud1125=2m07VuC$IQ>O36|7L-Q?t_|8X+cyY-`=NF$mFTtB1H<1!m~ft@VGA0VhbU
VO-kaB1o50SF3busy64pL!-(l@zuy_7iX$Ns5l!-IG^I10#W1O*nQaywV1?0c+>?voja(Vf36S@0Al?gT~Qsq`B6^tsZJsuB!~Qh
s#1y~NZT@t#CaYC3_>2MK+^0r@Vwb<+y|>O&1jU(h-1e)inyH`7S}Nk06@Pkp;RW_w&#9}aX>Z%MC1_@IKV2(WywD&lV*&vYjKsu
0{%uzx2iYMM{;wnB*^fXe62-v71=@@YHTq^P1rqMyOwH$v>d5NjWeHkj1s1k=Xg^d@krsvj#28Va6Z(D>K+*8S38j}yyun>Nt43z
4wIi6XLa`ked$yrBZriWu3|dMX{jVxIom2NKQ;70<Me5`jl^2U>Ok!?!Ek-$e0e@}Zz_ra{R+;i&#DNXLI3?iXB~K*zY$^z2F`n!
1P@gCU2FkuTUIwhB#jXxyNM<^hBu^y#^WmJ-Z*li?x5Fb;6yPLs>U^vfg9mY3b4EY%6w;sC<{S0XITE7kE2CR1ujpI-J4vs1Ng@U
Aw0#G90H`sqV~$ggV*ni(G1H)5i=3e{SkOJ{YG3c;RS?b#MRFohFu1;`w5>sykS3<957#D5m+2!G{?xk)-B))=q>^A9+wR^2@vw>
6wb64>L1Lr0j_V;MijO}ae$YSC8B}=Yc0&NiPr85E_D$=lA)5rev2@}mZ#d<M$eJC0bMEuJL!vsuVI?8w)?O`44tH~RPi1Y*4wW}
s+%ZyXZkAVB}SS+L;AN{0J4JOcl~gT-;0DY(D3_{#=S1XgG@>{AfENY$++u<o0#&QYion2U~8)Qmo^W_81{Sj@7lw=M$;rmu96*&
zIEpDk2I7rt4EFrat$U1D6MiO*$xjD9<VymWP1rZCq2SFK683zr@lomVBx)R@AR<2TnEJ_6h(p8H%L$o?J+H%?G%A=BMO2K58X2<
xfEU(A9ynXg8pm`e_9JrK4X4@-Q9|a#59<FY@n#`V#VAyqeKUHgki3&s%#lkCz|uD9~Fmw6~?Zm$?5?vne<{PW@(mwyEeXi6#ZO#
Mkm;yY^H&`zWQA;UhPcw$!&iiJ~7sK7T$z|GI%(ZOu6<u>hxH~%bmrvFCt!H^@y9<d=GtWHIPK`(LSyBo-u;Xiw@Nv?^ssn^cR<~
4LVPDJ-E*#z-lGs)1EIFHg!|pu(E}MWX+CYE6qGz{=a?Uo$-K=-kf)@3rvz6M}A!7kz$$FBW{iM^MEj$!k8a6*Faz0fB5k5%CV<x
oHVkva|%TxM4Qc;uDjchxY-T<v;H>Gm|~CAhuCCGFHVP(W#GHhutnE}!H&al>QAEZuR{3;Z}6MDO(Jn8$3K^2CxGzF?>sOBm3jFq
Cj1ZOEtnysCN@;qwV4oTCYPttJCL+&5K<iT5ix;r44Ix>%H{uO?85Hn5yf$vB)nQ#R^ZzGXNfEa`?sZn6v9g>{+BZ%F;U|R^=8B~
23+caO9M#T`V>tEErd`IM|M-`lpx*fepL3tPUi~CUHot>FluJV2GacSb^bZ5<^%ybDc2{&mpjS}3{4>tsM73pB_z#&?{#HiavuiJ
7*T!QU_8hJ83G@gUD^pnAuW)Uy>Rt2%kBbN^#+6Dz9mT&>f~#bbxCg<{g12|mhz&8Z_d;{2$t=Yzh?>X3@PK5z@WhUC&%Q*I|ksK
K6I96nnTbF_rEv|NRFogjx~x9cnRUr?=ZU5Y}UL=wUCwai?Pkw>>Ki%h3c7wLWsqRRo*7`fhupdhAGIyF|B%+b>^UH<LTNHu#q5Z
V#0}KF4AS?M}4UY?|-6f8@7POu^?aI<ks?7S#6|Sd9^lkntH}CtOOp=>nttF|0Llxj+~pH>AQ)sVLtI+g*z#=GBr=!w6b*G5ss@j
4X<somp%QUMjdVVoT8dLP7dLftOFK>mB+9?(7^*nemt>KA~z>NEyX;tkhb4oCF0jwULM`O8<W}oU&-<j7KeWH3oW-^W|mC7&0MJz
_qC1=9#E4<N2k8Dbr9e(WEEnX3Wi*0K=+`Y=PmkF`U3kM?fag~iZ4aj>kNRuq66UPi+(t)MvHaV9>8XB9oAz0-)hFuCm92}Z80+-
f7%(n`(@CA?!WkO_uqqS>?Y!$rB1g+e9vR(!4TXv@6RY7)&P4ADDNz~)dPqf1aRxah526;`>cPPhs?4J8PC(mv?X)I3*k!s?qJ<1
^IfYvSxlf#9(@HSoY{aISH|$>hA6>5c!a{HIoQb7eAMMmK|{0)Sjf@183zuto}_mn4f||^KU7vj(pC%@D}2BZg=`^fgK=JlwH);9
gD*9%!)#yiL@x5Hv=FANrCoedVTh(fp{Gt|GVi9I<Z>QO2{#}+j!ORdnTvFI4MFU1qt7CgJNPDGwW<9$4tyE8+igy#Z6s=giTgT@
l`;-uC<}-|NhYn2;c75>%;aFTe}{yw$_nl~3sVDeku-@5*|s{%Vi&H6zT@>Vb_Irdznc#Y*A`izC;BI`kirU&yZb_#c#Omz<IRXa
w2Fc<=g)z-lr@_P`(bAt(eA*gK_IuDrUDxm7;8}WzflvmLtHfR*mfqesFLbdO2UN{-atQE5M6p`EMMm^R)okjpyFRithQH0{7dLS
ath82%dGBi{!al21ZAjZfgYv^+0~a0JDB*YC&Y?p=#AO}Mo~FQUfdcTwbAFlwOrfQ{<?wx$;OU!q_j>t9R71hzreBINWk)ug)Q1I
3lbd2{yXYcAo<Es@-i3~2kb*e3Y9`|3v;$t8t($rIgO<{OvuAneKWEhOQW?S>dQ>ziHN=wpH_+8*Rk`mlv(dsxOgw?U$Pw~<Ju_c
d17839lp8KJM|>|iC`?O{coI~V}j31Ai&QJ=(9=DwJJDPtKnR4iiso!frO>GjAO8tl?yqNF6j?uPpu}i=Gk*-C4(J8Kd7U;^@!tq
zU87{L&9FtA>pdH?rTWK!i!Mj%LYoou#VSrv;%MXODE%!FWl~d>r=IYn@6hrp?^#>`Q)8DHBRvg=4KJ565?Zb^-%D5tTa=7$xH;f
ZCY^?rfLiYHWe`KDgw;++;rf>)ero1UH<F>JS(&eQ2ypjQmA3~b-sfPO!HSEcQ`r>dZ(~B9O^$%(EfYHXAA$|)M|H^Fy04G7vSe+
Z|cUI8w^>%*BgDhKzO`Mfo*#Cv%61YDp+nv-%Psa@PeEAhuS~7M+<9#kZYZQT!yF{W7S)Tc+@3O=l_LNc1KjK6NJ@-&Y|>^s<s1F
U_r@^v}rLoy6LEJ!P#w8p5>8oCs0$mpXdKtD*2%%s&;mQvi`P{C5UqMKtcZd&wv{C3j7z!@ppDc%i~2r-x-a>W;zu<z*k=iAkI(K
os`_r_2HWGX}X^#zqfLcMRP=8d*}j*e7)iU&$|1R{Z&rt`S}9j9;09iBS)t|5D9loaA+`v^E?JYH5D^R81T)f<}o$V8I#+v;bhh7
<3JFthLW}(U!s;ZLm2XzxKEA>fSc+Io`$+Vk{64)s~4~|%a?K%{QX?FUayHfMq4|~{Nr3^>OXi5Z7dI%$+ix4H<q>CGhzMWe3y;;
YY*w3pGC3)aF5Sxokb(HJ))_IYOYSlfzlrChhn8AsA%YXSFsMr9@-tvZ+){r>%ooRa9BGlJ*ZN~3!!C(u+k}^d#cxLPQYPRAmwrG
!}280Y(}wOu?5R#Z&vFGfOCN+d}BV$95P_*^}4k)bOjt64)5$&ed=F6cI}1%-YbL>Y2G8`_Al=1pxM|?JjE>vAY#C~&a?Wl?PACm
%O;sYHwQU){2P8r1a<^y95aosN9ybU9O2{7ISiYW`-5sf)L~wOhukTPYjAY7AS+{)*m7N?j{$tC4Oi3`0kTv;pj<m3>n*+#T|bc6
RaeG_BOnDZ{F5z?mPZi`=2h$B!!fv9kD=QQn#R@GaHQJSxiAlJ0q))fNfk2Du1db<+L~}IP@O>&L-SCNZnU7es6gWH&W385I0lW&
?vDWD+6ItS+UbxIUw2#v!mQgDcmeVM?^GqcoAlYyQdqh&eHrF&((T$_<E-7m{IfK=uv{7k&ko39+6%XmI48%IFsR6N-zkX616eZ5
v`3$qJ|n(>C{e{BvuX9Nt?8gI`4iWxye+Z3A`5?bSQK7=qOKd07l{mq1%={$N}`J<KQzL{OX#)969st-S`w4*8678Onrvd@v@bsy
<POzR%!v;ngcANsqX6w>OYE&z+$2uOaBKuAsE+%P5KWZ)954_})<TEoRpMdB-FX2&>THEevoMJYm@ICTqYos$^rY?Y-@Chp%5Agx
{enXq0GTpsfm>bzk;~TD@YA@^>J;*O<ecJC#=3FAi}@_LeW?OkCC6`X->TvTh(Cyok=qFW$cOo+2=ce_-4-IpVa_u&J7%7S(3#pc
fi3@kcl)SFz|CjjiJ+3!_iC?M-h<t7--Gjj?c@$p0Ydx>kiPpL=%#k2Jyz#Zze>TxS64)UVBfr835e`i5YSY_-m!j0u-^*<B$AW$
tp{S6FQdKE*G-%lP{iOOpf`F-GbtW(=Wn3q(EUO)2tWGQ`vsBBQV|2-X_ZlIsC!_{DwTH#A#ft=5emm>dXVHby@7a%oFMdt@-qeY
er?;|Q)bfAX0rFo@D3-}EG2|Z<%^WFFrq&Mm@YM$DyNb=xAUwqif(dE_d$(wvdDo3C#xq>*o28u_SrA_WM5nG{D(NxL3KRD{q8QE
Zh;g%>ARxtDO}kVdycbZebD{P@_1Bw&H<;Gv~2)?1O$A(Nz3UiO81N|f($nTSrs#p);$F}poB3zg!IG!87Q?>lff(HVEa<Q-rSA*
dV*Zhql7by6iSpXIETTIxo?rwl3zeYW_Jd2SkIO};OOja<-?#L#cH{?S{R*w0eW=q+2uw{d2SJkK)0>WA?TcfON4+K2)}_~1u}nP
Gp7cV57|=~Qw6FtkyZBoo2pXENvFL{AR*FdW8$Qwo{3u90kEH5aP?o^sJ3x9Rp{51CQp&J`o0#W3mT~kIpv-*la>+|lkqYXSFtVZ
lrYXz0E$9Y(Lf=2w*!=nMs5%u5@8P&vbc$qKOD<an198;J(J;79X-ek0Z`Wj6Zz;O#!ub)PNKPbwQo`)8KT|7>RA{EMn?{nf4EEb
gL$42p^b+mJ8R;`Vw)Z5%tKlG5=W>HI~OI`Et@wgIVsPsUEbCsHs+yf$hw3rR4MdvZ6367TWRR^dG_v8z?;#j(OhH!ONTF%tchSO
=Gk0+1q^Xq1*j{R#_zETVpl4VK7xvC`|8_+cgGeBq{?`brOrOU?x88WNo=^}+F-x-wf@D-m==EA`NLd+<piCP0eXQ~{k*t@H`E>-
^7<?7HoG)nUfu(>$1bkYQzOdku&G*!rBNW+9hi&PzG?$8WH;un&lI>JyoKzptI16&rc^YnHbzs1;@gm8P#Gm`8$d#Qbpm1nD97rq
>)h{I%9k?-uJlp^CKg2qOc85qO-UM#(!Q-SnYc?^Cd>0}x{JL6A^+YffpOO+Ujn=%<d%jXYY<paC=`YWc_snQsjS+ND8y{tE4LyV
6^Kt~0}FCDUI<y9v~>~iTEuHMNN)d`7oLv(dl{R~OBm90Br0`C6yOW!GRs3)LU*4`n-e^CzPB}g#Hec$R1cX;M=KaK?l+}Vhv|2U
Ir0Gf&gPqi%9Ld$2TM;}aDX2Y&nGdStN`a+ZQKI*)FVLAXb?dZT$}v$OL<RZV2o60HXWyLi&~^oE<L`Dv6UCy|GXi=E|c2BZHfRb
Os<jPvv-D^>W!LSScodAy|sk}c*rVZlIp>pi5P9U3Bktt_=uXF{g4-U110~o^Ei4UC!Ze=@tN&SX|*DB6y-4-ZIuGp>B`fr21A&{
iB4Cz3YCaK{6e+99nKIaaN7zlDX%<HK;e<&WB^)??H~n#l=yS&lC9c+&um9SU3Cx=z=K;kTM{$2kGJ93=lK?-?Yvv_mEPWNd*^=z
h)(|rJ4(NbP!bHmp`MCR2O>|v0}q}7x>RMRRk~n18obV761z?sdkTi74?I6F-xBdrv@&po8O?)A2H-@#LOP93VE^2k&$Z~iPD4Tv
W-G2x-i`>;?0QeA0^vkpw>&!D<-C_lGO*3Bl8#Yff3OyhSY95MMWM<NFjU8anhdQHYe<K%FdP+^U{F_ceP+#Ap)cI(sRnkkk%ff^
u^tb<4_vgmD;v#0eZDl7coubGJnqgZv&d~gdd*~a*od<b(+HnzN5c}lU9RKQhgoGsQB6q>W<yn@Mnu3oXrfY!seGKT;V;Xf9}Lga
F4%90nx?)Ec)lldwBTvwKW>n1{^L8lj^OGQfzkLG9pgnoumj26I|LQwYJal9bIXL;`A1|c39ZV1aJ=e)_8x54mn1m=67^6eHN_^V
rtf!76xskS$M}~6`VXU(5G(s(_0!?B{OUf+54f&vy2Y3aK3L0RR`8fA@!C?vJOTnuIkGeTpUs+yY{J7L*KRtZJx{1x)vDSZX_<@0
zt9f8F(8)q|H@6rGaOBGP$&cr7$n`oBRCM)RBS8_nGApuJ_K|ee}JBZf8$!LFEl899>WM#p@U+QNDAoxyZq|o-Ss^yS+G%==`c)q
=aBZl8EmPC6Ay;UT@c_hpo})K_6)1eJ6vP^Wsvs}+3TmF`9x9xX~b`V!jiIn=6Y@2Yh@Pa$XRPw&QMEg+xyWF(i|m6#zF$toc#NJ
oVCFzN<$$ME%6C(kmvFOKl2nYc1h9$0ug{q`aZ>fg=Rt{JHe%BaqlpodqptLhTcN8E`yMfg}c3#6E^OF8`EOy=Mp<k{pkaMa)!f!
-V>UFC{fF7qS@$RHtV>pGl$U<yWi!Yf^(u3%z*Pig1T*j&#6E142PxdB@%!h@{!%ku;|6{XY1ou`F{k-<;fzt)Vm(+|HPPbhG@S<
n5>2*|F;5;GP4G^yq_CIQXI4b1C03Hf9Q3ZPP+!Zv~vS6Y$%-_EC-if0lF9gKK?vL3RR^GI_s?V(C9Scyz?r`XVCSGcnkRd*}X$j
VOauZy!~h3JO`{{F;Fzxh-q}1yO^7jyC|KPS_s>wUd4B1QiJ$w4(N@C%}7@&$!J7_&<v|C)_N#kdN3!zR3Vo#oxoc|+9$APBb=_}
pXS7|nvHl`nb9(DLd=mBwQbI&hnwUo2DBnnzdtxP@)VJ=&632K;pNf$5Y$IenV_c4u&NP<<V6&IVl~rCwq)d-fJ+!Yu<7KJ@quzm
zf<%UMPXdY+0p=uHJqFK?h>kBDv56;i_<)+wAMNPg_j?w1{QC$_l-s}8AOgMoKAU=sGA;u%f8imco&sFFq{=0L>su^?4rr6B1NYZ
ko`|@Qkwh;@t#W1hYKJI^a2VpA~Cn?XW}{-_V2g3sVTm(ZOsrW3oDuCJDdwc%0KpTOMnj=e)>Ka2f1L$<a-h=DvX34%{sIPIPxA#
ca+T2(X_g9?IJM)>?W0MpJ<#Zg2GDIk_`|bZ7QZvc^sUlI2@*EhOlLa|4zf!uY2<JEU3;boXR6svi}7EiXJFH_~0(};WW8fstEhe
(oM)7Ku{i0!dycU=^?H4<G#E!dHR~Hx&&%*VAX>Lbd3Gk?8rSZgNZt+v>MbqA)WpxuAth=pCZQVnykg%ziyfRZ;U^*ch3b%XN11R
9(Ra9T_~b?9)Y;rrmo>b5kArVs#0+Um}d7&<(n=POa2aLF*d11fL^ESOL3fX>G<Hnr+is1z-QY2K~<j%kDr@iUiD@q1Xw!}FkEo*
c4mW0n#mXbmR!3_7}96Xmy68}lGwjS$;0-VK7&6d0KJa30VD_x(`vpuE&e)|v*jJR%i?l(EojyRPM;d^y8%qsu4s?2Lx9mCK6+H^
sG_>E3xc_WvjLm+rbVQa?pwi`++=?R?pmslsfnxSvFU>re>pDpqh>3=!Uh)o6og0*RM-%o<?u)pN)gn{5N4&E^-B7aca^#XOR{+c
h2qEwW~fKXX;u$tC}|0tjlF8ePH|=M$T7N<O)EH3o3@v+)Kf$-mMWE>todB2e`Di4MwkeR-l0nP($BT0y4k39{X7gz<TL0c<JqfU
kA&$@&9Q1teBqFM@wE|Vd_zL<MJJ9U5q-w($td>hHq!&r5O3)xorcVWFhao>RmZUSQAc~mL#2*i<ukzqR(o9rE0lo9U&-+fsSpbJ
b#WeRu1o~5UGxMdyD(6(0y^Jt*RS7bWfpR_e+4W_o2=86=#i2eohu&Cp{c=BI2r6@F9`dxB7MaOzhs(0g%H6(kGKafKf)Tl<lUpl
twm<t0oJ+1NQL6TiM>W3r}seqscSINeVI*AO;KnY?Dhh7w>MeMOZo&1fe2}9YKU;9Y?TAlWUn40YGs2XyFeKCpO|mOo-QTASTAzu
NSZ!;1mw)H3oo|3AmpUiW3EH0lC~@gr|b13vQD=)IQ<$|1Ixv9e-p{gcmoxg(f*jNt9M~B>Vzkc#o0zMW-?H}1&dFqPSZtN!Fh7R
c?n50XEZf`f@259%ug9tUwRZRdGE3x2b;|(0m4@xSQRwHi7eoBcFrInFKh34byv8PjX&)}?`@Mz=LKMM4dEW!1`0pdL$KkH7-uxk
R<C0Xxr)&W{4i4%4`XJYxT@0Gfu<vi+dXfLP-8D%wS?~g;nk))3z}iX3PCmR%@7^?9-(B$x`rQ~R^rYcZxD`}oR?Q4B$@rg6wH^z
m=fqsQu+$(h?Uh-fk~oSyQ@#rKl9CO^e3v08pW3?^&uywq03yd!yb)KKleRpG_kYzBjwc_EGU|>n`*tmic%PGSOApio*S!ozP$No
X704I*nS!{HEQd!lXG;+91?Yy={M@8pTV(~0)HRKVYiT}AxE^I1vroS=)gm|P{@EIZTvb=`XD|~@CobSqEI9h{n$1--8No3yy1!B
3=kHbAY>lEEWMmrvT69$_e3{_6OmY!yZUL~aX&Q<i4LDaA0F;R3n&9wT`jC(GwHJPVvo~r409n>?wL_z^=w{NY5z1}EOHJ9Dpd4I
m=Jne!)R@LM&AMMmGcEy1(4GM^?d`4$K>pyhS}%t<6-|RiB#0V;>1%zh5<8=np0Vb+X65UdL9Q0K)8*Wd}O?6a7#x8S0>ml^Bp@i
QO3Oxr@#D&Y{sSC3vcYfBJ{LbnnT&++9MO5Tia+1m`3+-=GSR#TG(zkqd%5_f@FQiQ>j+!g{@r{ZLYcOevU=XXaqOVcFPk>ZR+~b
`-8j6tNwI4;`2smS^wFTd`9P!`knB<rlCxSl)GaI)3YC;txbT_%>^r$MR`#D4$VxA2PQ@W1#~I+SJ<qdWkSlQPg|~f^B+mmb9&}<
zB8)8;V+`0#s6Bh22h|6T%9f_D59epRM(TsJ}3XBH*d`MhrKjVeTdszgI`A{L)B5ixp$HoE<ouo-y}6w3<I`NQ0)9QG{tTt=ic^Q
QApC6hT9iw43BZ=_v|$Xe&Z1GqGyHemRu!Jl+gePraxY~VT6bdAaBYR2aY-OZ9RXnjpVZ7Vb0uOqf$jv!lh9tJQDKTFcM`?YXEvn
<*9#nXwaffR+C{M(F~Cbs$lm9xDwriA$%*;oQj-}aFyIlH=nR?Ni0l;YAnv1%6xf7*h|P&?=XaEprGRe2h~NdA0O59_1w$WU&BB<
b(a91@9+U&$<lAM@q+EE0zDU$noW{uZa<hjP~f9DYR_X%M=ruxLgLFS?N~9;6<#mBDWy<qD?fpDh*oRH5dQ5iJ5EhD1-qSO)}ERw
9(J%<_Wp&pEF1Z5hh&^;8%JwpI3!MvJE-K0ACTX^r0$D!Iy2o>)nfk{MYmY_p2cgTSZ-(C1w1IV1*I!!sUKnR+2@t5k558KT+D2|
X?j+oGm!YVZ6(k#c^HSFO}7UVZ&^OFCU&Eab>yG6EC*0qV+*zOVsNPOzWU5hmbt6I8=%C(q>#f;76MtM2H9%INh^2-MZ7+%mQ^M;
-XH|796lq^=!-Agr4_9v)nwSe`u-0x2p)sZB<sdAaI-T&2V|0^Z91-sT%;x?2{Gy$Z|;So@k=RE)_b1k(*mXnP9ZXNnr#rku->(&
$nDKpV5se4MQLGPbmky$wxN6A^P~0ntf__<7v`J^S>FAf<g7_NVB#9~QoJf+v6LQ9axO0uZ%C(7;t2p32c7pHqRvH4m;dnJgLmGT
)7Ja4g6ZWoD@V)8p1E2qV7a*6<Gd8j6tb$(#j-d5RL=*W`W|)HWd}Hd%mqd|7%L*J5i;6){84`4zngjd<JuLA@QRm|Txh*Tk5jdf
G|d|0;W@uNaIZFexHn+FW{_N*-|-U;NUe!717($vj<T*a$PEFIT#{<OOJ;aRv7E?rTz3T+i2^_IO;uDTjAsoN{&+`ZGX|(QApKY0
*WO-Jfo>nMD%JuPj&4r9;l^{RUfc}4Vq=Uk<QQ<ALWRHwkH48g8upt(za5yxT8fbX+86F}PZzoB6-?BNcB62Hq{tez{J}6N#@s9D
mGh#{L~5Czw-R&Iu&I<#J0GW=EDkGU0O?5#2=voZaTVJmjljNn6)0=7D#@k=<?Igmf#;!_TbH~aHN&zDZ$)Qj+(hDM*z@M%QBA#;
u+nF4`6-$l%2l6-^C~TH2XlEMjkM@+eN=9^f;y*+(Q3SYZJO{e{)3~QRTQ|F2X1#t9*K570J~o3!iCQC-DQ7WBTAI~wPn;#_wxP*
>s&V3i^Qz93(?My{CZI$z^qU?PXTP2vohsY5%m&NCBb@~+8fN+k)K2E%bw*N4IIBj5)>>hSfVV3iI40{w}syhz+Q>=+w5A%Fvx4|
Lm!tG&(tE0clfUAD};d|ZO?20ZtvT?+kWBerp-e~`(i)%nMm1=xgGH4Sa#`K#O{@q9~b#xV4$IuA6IxFAq?+K3nD$rIH9I+GEgHE
`XPz(m(2EIS35v<hV_p>&F^vwk**hylS235u$y?f1v{xLc}Lj+U)VYc2M-Ae(bni$vREy9x8NuE3hWZAWZ=YVrV%^*i;=#3M^sa$
W@oFPaB0e&zKE#IvN9SsKqN#AZl8n1Mv(I${*37Wl9i(85gPY{_r1U8XTG)uJuF^>Se(|nCb32TUS^UDI#X8kz#R*lTcHmw$!A!2
LXW4WoVLB1I)@5KH<u^qw$92m`R#2aLHiQJav^YJgcrgkII7qEQ<ta>j^8J%=EffGoa1GYdjaI;i4GrSnxocdN)eW_W0iK%-d1<`
^ChufoMZ`q#C-`%g!yk{=%y}q`tKCVil6m8B^Hcq?{crSw>2w)PfWC}>kQt4Cxcj%Y7gm{cYV*GiU|ID^jAK7b(LB!TsiNIfq;o|
&hldXbk$MXIkI+%v0#uUJNYXw(aQ$H2e95tUAFGKCL{B3$|(;dXIM`~k&X=7I{)rw%rd_zK$v;-mmca&y_+1%nb|k)GYtPRL2yRF
Q8r3Lwt!yOO{p&K$}EMOT=AlFkIz)Y_9V~APZ~~I4%&6nxCria08^R1MWp%~j`cbT_1wT2tQSbeX0OxJklWaNCqKuv#Ba|I*)qiV
!gj*F*y~nv!w3|esnH>dd;3-&LQR;M0NV`)@bLz{m8OGooxZKr<~m~~MQ9;0^?^;Q&6wrnk=t0dGWmxE%pCl*m@@cZ%81|WoXoR%
9>9)4kK-HH)f-ri719KBWnm(1`t>^8{6y+P@u7yNKAeR0@;?ZQl^>p)Vsk`0!5;An^OPe4Y-9sw28;*$TZm@bg>53PRU_Bo_v%mU
yRocASQ}zsj{*WG@+3E=30Vvnu>?(EezBqyF3lNV1D!`{D`u=9C#JRsL)`S^DEFTR+k-bhmwQ_}3j1qw)n>{10RS27)T5`IFyD+Y
ulZcoa;`*_V?E2a8Zw<N;cVrCeA|j-&~Sqi60DuaFHZ`}X64#C3J>s=dHp{PGjK(4(a=uM1#&bs#?2gieu!Kf+@DoHLgC?<#Vczm
i#p%gZP$1ZBmIzOtMf2&<!f776T)8`c;nW&L{$!LhmD->0N&|<*%Ukw;60Saaa2FgodTgjp-T0BH0`(Ma1EtC84KZ`IO;v-w7VX@
TGV+=Ph#}9=&n0)TW3-SFPWH;?`(u8yKPl6J)l)a3tShuc_{&<Loo`5h5HHH0*ZRqlg@@7pC|E-0`ttiz6bL-^kuGfE#o1xe6CH3
)`Q4_ni*5)N(z74k_fozJW<rz$L|gYf*QkF=@X<X6XP5&L`6qkz0NQ*yEWeV7?&M<+=_xhES$k@1~>%n@*^!+hMI|hOM{g#TKe!R
od|+HDe|f-l}IRM@+dJSMqs(|oUKWMya@}7vV@7%UjNRC2D=CH?sKsGM(ZA2Km}R1NwJJDpI~IF@5g<)ZMS6K)Xuy{5ge5jKzW_G
Ae4o4wyfbao<EbdjGhfsP$U%LiVOc+l1?BwbS!-nxcL(UOL&nmWt2Dl{a6#iCWH^B#i4OIxJ~qk`0ZOOY47n7${Te<go0&hc!6x8
*v2Skg&*;x=z{#nZ5T`gW+zp=Eq$4V_HK07-{Jk~&MK!g9XLFAQtNSg@TeddWKD3)l4s>tSjR+c{W5V(4y6^YrGIL4jpivK1u~X!
+~hzrVRM1vwRD!TwcR76z0Ejw|M#F{P20_SVySqnT}o{O_M@zr0K>Y{uc%fik*$UzwjQ%R6`c5EAB;S2F`WKGsVE~*&CeU4p^I$g
m4-ly5<+nyy4u9GCMLgY(wMU10LdZUl87o?u{65S)KG71w3jO6wugUINfY<f5Gj#Vjwv!uBh%}mBnZ+IxxX5B7IPBmoBW1jPu(qZ
QgwG3^!n9;g#&&c<&%;ts`cFb@6^)|zEYBJhcjYf+yO1N4-<G02RMIov({<}zk;0NIuGx%>zG>wFeB2uASIW8a7xtOTq*OK<SDsL
!rwUq<RkE9BwXrdweE_^ZRM^X0{_&u14Q@o(-^^_WnB}asxc=#%$sq#xS=MYbHQ~8Fb<p^9Oc32#Iv?})YJ2fTFC)~`J8}&@~_1*
qV>2bP_8)Fh>A%o92jgGgS0RJnO2a0`WC>7Q!`$5MVet_B8tEVZt;$(P%ys`QWD({=mGk0NAJ}oj;$!Ky&|-dE35~mrA=ScKJ=S3
6?CltST@4G?1WGW%dJ$xrUgk?x3sU#$+jT^gvs<}2-|fU+$%K(h->9&AW0boUM`7^7u2E)=MU~8-q$HI;5?RTLB-U66-OlVurGEw
iReg%s)y7}h8bvPAi?kle7plk&tgK|@JZ|672WBZ#Fh@6)w2R^KiR4QMlAj*HPP%tz(gvPXhh_1K8l{byCdN4Imozd_=-Z9R*$Dd
_Ka8~5ci4Micvfbs~EY_(K~zb#X!MKq4if_YQL$Ksh{g7u^?kjfMuDIjwlQe>+&-@ZVK$PEVR`(JPePf0_3sYdBi5d;lzEz%hG!0
*y=aO^LbJYZPMcVF8r_2WNJq8^g{1d+24-GRDG)IK(~HxgRN17S)pWav%cN%D@hMDP@|eyghvhkZkF-5P&p~o{>lql1ZEGiUu3lW
aKgq*(j9ZK>M$n&fbnjo&u66AF}VZn|LW3{7mbV$09p|{=g?$3L7asr9-+6H(nm+c&Q_m6%UxG00UImyN!>CcHH^5m&x%L>U$uKu
7W8lCo#okQD}C0MLztVt_ILJ#F%ei{0+cOEo=TfS!*S2TH<U-I0*XZ&W6p6IIeC777f-Nw8XDmf(i{M;_c%?2y&~$Dus3IK;M4q#
J)>7y(}Q7I0DT19<7E4VabDytUctRyR2ij{ZSs~qBVkkk+B@Ca9f4e+PnyWKf`h{fPS+}@&h$2KKI>tojKkcAIP>~iV$AO$Pp7Ti
)4AZwOxG@IJ*n`$VP9m1;tOoFH}9-$zv5}Pn80W5Z3m>qTSZJ5jkDI2rooZ*AoD;ee>M2Z8A)i{`=|}AP7yVXh44EWjNFhkBNg|x
VT1b~O~PAFR$H*(k@cnQ5i8lsi0@^il=BEUehn$U^-J+w4IfD2L<d$;OM7J=>kmfT=h*WKGa&jfvl=6r?&OwGS?QI+|3U(n%3&`}
9O!?jE&~rJs`RK~-d84ygNCXDh=Ox+$M+nXmRQd)6jf7JP?*sBDVaN#A|~1hO=?u84TM41=O4=f{$mH#M()dMa*`SXJjCTJbY>u$
L~Gc9FQ^j}OMgDn1AeSWWZv-)kR>6av%JEEM^V)w%<fk8d&ycJjRjE6ez-ELtRmm}nCyHUJEV8cLtavgMqiZVnFEX(wJ5^pf=$Gk
wSJeukgzC<pok+(IChTgq+a57+=n(*jf;P^<PF+mwIMfu|3dt>V{3{!Wzu^8(tE)Uwm;~DasPC~0F`MwB$|n~+<5^>pc}v?@0cyJ
PYM&s#ge#`{~YRkK!asKVysawsL;SreP5V4I>z@lu8|$G)2~V2+%-vHV%%0q7{mfPobyYEbz*_@DTFgF$qoxL_bmx|!RycI>7s9S
UAlB2yCab}q|y`<L4wX7U~;5ZmIb;O0>(50z6gVr`86@SBI?Tw+&RhQRm0sC{(W^5gUmU4$bHHUd++_EAI|eb3;HZ0P6+l+DBnyS
PG=pMc8;}eD`tMcnr@<m8U4dwkx$sAmd=TPp~s@<^NlFtFnG*{kh(UFw<jPL=Tw<S`myYFZ69szgq!@HAJSn}M5T4iE&I7+5<`FO
c(J+{FNj)4hY!b|S?W+4hmDYST^WZ8Hx{l=dFWSa)iO_7YVAVuJDj&|S&#H`-CCj|H)za_Rai=}x)!gpkKSxMI$wn{5q_B4SHn8s
n`Q_0!(;ex!1&_~GTmy!U?E9&H9B~&Xv}47U@km)Au|SvgnGM<pC0!nu%0I~PH6KAA`GbtRmOqO0)kw8^efIm_;rP&4nreVb+X~+
ZkZ?e=oHzR?Byx=Gr7e@buuql9Gh%~f3Xrs6p;=g)_9`qw7ZYym#Nlw+_eSSa4v&YCfALb0j)si&pA&NRn!2+0D>LzRu?`t{ogMT
KF|`k^=RkWYoB8x38nn2{L&|8I3BS}YO8bek5$4Y!g!z^wVZz{jKUs)*UkBL27ePg@VAp*S<LQDNO~RS(Ans^iDL+UAuZBLDD6>^
b|jd0{yC-$`G4`T<a9xp=Y_x0qT@{M+_&~%vU)mMmphHvJHGlrMX1;ESwTPE4a_|?a~<IOALd`Gjh}ApN-!J`V&l(*MP*onoMfUg
gt~^kTOB32qe$F=A~%cd@;k=2t<uU&eQu$b05n;jBZ<#t;{R9L<%W_q8EDxk9D~Uk>BgNBzvXK2E0|YfNB|MPYAa8?TW&NWy_t>F
y3N!FtaEe?BcS8TJ|mL2fpnwe+6B=MmbFtgFz!80=FsjK^9;F{7jZb(L>Btcy|HO1U2WPOXGLGeX6H)hu5f(9p6CJnP)c;aH&;Hv
z4ZBiB>$I&C#RZXgWiuYKWf$TLun3#5Sdd0k90FD8FO4c*mzhT+hzs4pshdu)i;=lf#(;naRX<Pj;cOq6jufIfeGyy`8Zs-zfkfP
1^T$XY!b@Iyi@PmJ0Y*r1nOfo;1OV7)DHwZg1xQ5$=i>hDA}0Cy&4!7DYKyR)l^<c8)6*i>C}J~J1j)ndCk)ZIn#d8BoO>M@0xJC
)rGsbBWAYJ+@TFGx~KABF}D#ycTbv<RS`VHFp(u9z^y#MD7>c?r8ge^GexQTLryD<$TpXbCBrr@m(A4t?vpe9WVR`1Y6}UQ=G6w1
oKCDr4(Fi|F=VU<XMb}f<o*VKwCJ1=DyIJIN@lN(Ba7wM!k;rq_3)zVv7*P>^fA%iL+cSjk~H<NX+EE~b>4sg4ZWuSTVC7;{_@M9
QO58t0x;{%SeY8d%D<okhEJtA8F%brH1g>6_4^i0494D^rt@0s_x`_T)BK3%>{bs$G_(;ThLgExUSdo~ANq(3#*Qry-hj@|_)k`t
``x|@J-<c?3DZ5ktZ=*+uuO~50X73t!Js1$8Wj##p@Y_j<7?^s?!%>KKFrzvIjXCd_d9-K0A6uW;=gR^GGyzA1z?^tNRXs6jnO{j
o@BuAnk^Ld@4O*YZg3moV_qzUg{7XRa+EC~+QXA96&N74q!jHyONa-3C6dB9#StZkzPRAC^RU4Z<qcoLD^L{lwKUAyeF*%SrcHgn
(q2#-q}7=0t7idi7A#nlS)YJA1LIh3S+0|G*#^7P;EAHrr^qC-S;T|5WsVk)`~04IU2c_BOgZWYNcyDep*HXMV8ERKt*e0Egq3!3
Wq*n+cVLrk68Uhc_$%7jR00)NYevSbZl+=z<5K!sx<~8e)#BGG>>kY3Fq_A9YV*RP#}c`37>?JxCS@ig1C)AdZ9JLITY1aqMf`N(
YnR2!?O9aE5hG5#r7+7hyvVwGL>cCuH>2Senj)MOM+PHpP29Y(Fd&l*w4%;9As38I&;rIM1;jHA2DqA%%NQFsGy{EYOyzPQXhQ-c
FtQfeq5)A7x_I5~D8RsUh0Ii$hS|>A>#GG-%2QydbK_I@Gtt@!pT-`U+>=r*6baN2jp@$*USWzW(<*NkW*sTw-!M&E4kj0OiKoVi
K)&B#&s!;S-M=Cn72X+}+t?7`Y0s5mcMwM^9}Yjk>i!{#$RHGP7Wa3FqEiM}ET9+9`k#Hjk`ppN!hH@je|;RcbrX5?Ms&b8w2iqF
swbeujNB(YP<BGsqh3g+Btzmzuv-M<X0?^RR}>OMrF2Qn8Z=8ZqKoGDoTtfPwvXCe70|_vOTLECI3Nu(`m|mG<n*(=>60H4+OIEU
8rzv?jhVlJ+R?y15gCvOHl5dhYg<A{s$AxPTB5?fy%%Jd9e(QDVvX3VdVjwvvr|C(WqNLG#9R|rZKM3Yn0+<IGJ5;8gT+5{si%`L
Es2Cpt;5@u$F!V{1X>NTI)(Z4*|Wc~lVJxO)_?TPiR|I{F;(TJc8XaDks!N25|J(1DsEq6eoXh*KXt_sA}=WEJ}l%U(gAnHi?A}<
tZJUAHy&b}iFv{Kz8|dvERJSz+hyHd(!lBBs!K1Y8Irq#L|Dx-9Lm?5M@rooyz)r|z~m2@HFu;<zJ|`HRaC_>AX)06XfOv9vSnfl
m=U>>QN9fZMAp`X?1e;0f$gF#%42I&%3VTh{PX8{#Z*Q8xk{3}{lpkTT2*dYK3b4L_)-#M4_>EuS}@e66kv&!W(S~TPf5k=I_t5E
q#rsj)P}JFszzqF%(>ZzaT%;qBiE_dzOk5igNG1I145JdnI{oQ^C977Af<!zpy>hGSgV;gv(#-IO1j`ky{}v9h|GRy*gC9(>4Bg`
?d?=-%I5+@wQiSHsUyoy!}Tu9d?b@5Z49v(Fk$<SHSj*IlEQwbKd?{SV0QRAgAmSNf$>(zLAhgUrod^*rBhiAC|~6PPh688rG}Bg
`Z$(`Un1Mj%VnKH?$_G_vVL;xyYp~*fH<028g#CBu8*Ho3`3pohJ2S(Txt~7%<)aV7+K~^jjToF6!z21LKHcTDZ<1s_6u2)n`bq}
ZdrF2ayXbAsa4gLd9509m51X>$^E5x`+;uO*<#mjzXNw)Twu@D3;dNqd&USd!=#9hyE_zO1~k@3Nq|~(OhW6^@?X2?$q9GIV?H)9
9@8{bb~bwhX)SY5ByX&xMMJxr-OD5LB%)v;>Mvr{N!?sjZvcir*?sjO0$d`KbzvCKv|K)SN?7OK+2X)WMFa@$w#QBCb7D2-L9W|_
H5C3o+e7|Tv4aR6f)9&ll4V(nQ@ZvmSY>wf|D^a5qmBjprp8a><{9>j`z6ft?H|+;Rrp0nQ`cVCek|388m<G*EMJ?D2zi}%Pp0_j
t-ik-29l-*QuL)hFH}*6;L;;`cR?^C{<e>U%aRu^nIPQGnz-$|dt1HBA~oX32L@m<-nW2|oi>!H2QEjNq_5{PbMGkG=Yjz>O@BJu
TVEu<)ycTFOXyFiA7SG51lM&+5;Un~tps;)FLAdiELTUxUmt?wStsv{N443gw<eIkKndIPyTPz_Mv5t|HbuTDYH|Mw-E|pHU(<-<
xpJCdJm)5fJ1&2!Sjt49skQZV8PE~(AxFovOer?VBpx4X?6DF?nG)q}!JVlj$8M_$jQl7Rv|9DHL9u~`V0uVDi@8ED7{lIqZa_P$
xTzJY(XHCb$~l;KZ0O<k!}>4ceCJ0T;U$}~?V5Uxf1K;yDE?aoI|SJw_~n`rYc5uGW-Urf(>ZWMu&b?G@G6AUT8>#G^B?U<p4EcO
z4wERqiqSDFqs4@tVm3Pbm>|&THk(4p!X|4^2F4{P-;)#J4j|^CL`cr&qIuJk|b)n9nDhj7TH1X|J6g0zQ#R@8S#oair+Z}RbHP_
+Wq5mh+Ls7;!2S<=Q2xf$0_JAio$WXgQr;&rv_u4Xfs}pOuQo0GMWv`+-OGSaF;jPgsYup;aW99R1IH4(3QL*$U!I$yt!+hyV#4|
aUr+LC@QEvtVc<t&bX&NF0bZK5B!m(KRg4_3<cvWS(SBi4|^kd2v$p3%g;$wfCJ$A;Y-DY$1x2lZIten8+-SCn|#^VVfR?#WNaet
<*p>~7tHWPfC~z&u3i>wXfj;JJttMs469-gGj&6Jy9PUJm!guKLj&b?M@B(q(uAlL1(3Y*JsCwu>SE>T6m$oRl(f*(^LUb;99puL
v31n%1wV+-USx~dx`Pu4wWaNVV<>>IPeYF#7H2$!9PVe$i0$RL4=TKFzrcXg_K=?N=MG?2Hvg?iGI3t9Dh~{AZ-9#4`y1K*$Z$z*
{v#<tBiyNHY#=^7yZ@$j_3+CmC`Aet+W`<oSldmYY-;h$07(OH@B_4gRlI&xpP?D*K|_6R{6W_T=u#WyXWj7dm>4sImFtf2vhj7r
3oi|zmQ54AJZs8*BDsTwt?_Nos>R1+;iaSM$3~G6BqjmdMBsY_EYUpOTlaX0-jk~h^!EHMd8d8R>a=~sqLJ33nhtSu#wGl-lw}-V
$ZK2&f4Ch}g9w0wmH=X}O{37y`u@GP(@Yik{BQ2D<x)NyhJjXN7%XJ>+9OH?Sgf+Bf>Xkmqf?PcPnO`Mw?e5arHc}yCivQ1;sT>Y
+BaA%8a_H5t`gP`#7ikACW7bWCcBc;aK|o=)9EQXb6J%jOy^oI<g?Z|{wgF@h??J-VA#cIEb3Kqe9}0@zy@dp&Ex?JyY{b(=}sdA
4o9cJ`X;CDY}Y+jBMsByhijSClOw{6?}VAH?ThW@W4Z_D_}j6D`?ew04Ke^^m3qGO=|Nplf6A_+Q(|U6zDhO~Y%Wz23LOeH6zzBX
Q`A2o?`deQwcm#XxaZU|oWAh&{ayuY)tlAo$p6agTL2bUw#AZP{BNu#%v~2>$tNPoo&CjXfXPN<90yGk83!ZA1J|h@1A0tb>47cI
jOXm$Qp$yKwHMh*<vkq-gPX|J-b&@l-00m4+PVjkfKfEnKxyctt;>=Cd7QKh9v-B5*6zFm(s5n@s7eQwaRhm9(s)?ghaD=auq_E}
`Hjd950CW6v-Vmt4Z-otxxwc_$<B%ZxpfGaAiF91kr4}L1YOCZk8$}GK%oQdXzzbO7A%HY51?e7aN*G^<oE{1(DI$Ys~*X11KWKg
4)3X?^Q~nyN4$J%*N@rT7XrGVMv#<3qt4<WgS#tgByUD&y^5pS8ut8#vTCp0F!AAM2)O(hpk{h6zTvfm63g`_ht>}WoY#PIc{LJb
?^@7ZEbjbg`^f$huO<Ug>I?ux6LYi`O%fRWfeiy$ej$fYI_iMu4AbCo5qrz&(cN_bZLhnki&ckHFi4H1%}$_WM|QzBrU?hey=mRR
pD0`5@`?#?!ES#;G^%K-nfUyG4CXkcy-xo|kOSmWwg;TdV=MiGy;*=$XKr^YEirk8Hz@j_xK7G7RwLOZf&wVZhP%`J2rZa|jOdat
2P8#rd=Njj9k52MzBQ%85r%0L8ZoC6PH)`;SyQ3XPHU*Pden(<SdLAq3w2kc!R8K8*@?Vgv+$6j(grj-hGXPt?@l(K{mm^ibg8K%
Q=5)8bEkjE+rK?tv$>_S0~PgW@{wR+!{V}-jypcjj|uk&7)io!TzvqJSII8&wOqWU%@r<U@%p1OPX@OtnuZZ(*bx`y7l?x}*%4=J
WQ;xH(IqYWvC605VSl{Iyq$RDTK5+iEj*^5{rv}7IL|;Q;IwI;ndH3Z_?q_+?15xHYZ}^$ABsN7Lh#=Gufq(6Fd3i8Qgmv9Lue18
nf{sv<HT!q*T_#?p7;7N;&a+pOfiHL7lKlu;k5?^%z+A^X;@Hb$u80)rgK+RzVPY26b?-)XBM8Q>{dQqqkM8FEOA&L{_G02N7x(0
{*%G5qI^MHP=gGVNKbJDkqH>0P;O|6O!hTKSTNA^K*36@_yI^Z=lCx;Z(zJIpS&>oAs%zPi<Khez)<+Nyq1g?SJ><#_{{mmUrOwn
<~&FhfYOl~9KV5Ps@MD9m(L*nmrpe}pBO9U2EBn|!|re1vjPtut@)>`@pEHhsalmi%vnPd&ujl>#{;TAeQm!b%NkWMcsiZ0-?%~u
a@wi!J&zI8q7ZWdgWnIs#dIgE3)*H3+fl7`w|;8M?3)X0_c2ww0cxFzt7e_#5PG>id9#EIS0<~NEIDVqH#hty;N3KR<aYQie6s2F
fY-e@BUxI@J;O7^<};!`WNs7!Gv;r6O$~JoF+avZLHD-5bQOsYX>cB)1c!9A-sggxpL>bfKH<QGG<9@kIUM5dKqe6N<<)!d7b$`Q
l9{M`t-Hom|1OGqn8u4k&O_McJ>cCq$$6`1LJDX}kaJ#ne@WcNFD2Y!GhO3lxhwxl$#6nn{i6c*9@Q|eZj%Sb%@S_35fx+=C)y}$
m?Uk1c%=A^v3#yQ+9lSMlrHc$n-3ya=gUQ-9yFfa;jcTO=Sjr>o~aJH*0$vQ7r`sVJZN?_x)r7Q#o_WopP(xEgXG<81pN!eiua_l
(8A<=7%k2@`rL>Tf?@v<BqZa*4G?)RgVknkrrp&kPreTe!N~dH9^0UsNF5Lh+U8<?SX~KX-KK9=@9u!jh`S<%ODg(NPBnbqHqH9D
J*GUBgA0{$pJ~87@+B#pw-$Uo!J-KIDkv3Bgd9bZGk2z}pR#^Vh$U6QAW`9XR8`uoYpU~5)kJ_6%9488+4kfJ3VSgw6Rwt$Hae4x
G=khM7%=8`fRa>W>*%sKGl6Uqeg};S*m8r%<)+Zvbeg(D#$kT%X^Yi}l5PBnz{O)d<5f>N26~&qw--{k&h7`DF{Y3$q8V53J;zrt
jf|64p96E!o<GT|uFnLA3PlD^_8xIE4hIQGQzL_zTb5-$2L|yGe03!R_}+JptVPAs|I#^WnhzS!re#|`et#IPl++UTw6k4S0pjQw
^$#BaodWRR<17z@00Gdk2j7_;X#PtivBYQl0ssI200dcD
"""


# Images « Toasty » de l'economiseur (option du constructeur : « Aurelien - Toasty » + 2 autres portraits), deja converties par
# tools/pack_toasty.py depuis jukebox_rom/art/toasty_frame*.png (dessins fournis par Nicolas).  Portraits de personnes reelles :
# (c) leurs auteurs (Aurelien / Bouz pour le premier), tous droits reserves, PAS sous licence MIT (NOTICE.md, art/RIGHTS.txt).
JB_TOASTY_B85 = """
{Wp48S^xk9=GL@E0stWa8~^|S5YJf5;60%unOy(^1XI7r%)+yCDU0u9)Y~jh<ey^cWC~)>>71d^8<k2Ol9FM1ZyW)1v%_(THV5>|
^V|gitrPepAidr39C;r&W`S%nw{`RbKix%+tbX1yIJr@@AkC_o(*ImF$vn{!jX-Y|3neI}x_!r;O{&Yj$mAsLAL{C3)Bq(kVPD3M
B+!55vs!A=?#R7jG2;f;nRE=tB(xnXdAU*V@<vlI`4WDv1YOx+RNxM*Aqy(^y=BXw-My~!H#nJhQIQ95Q`eeXk^_|-zb;vUM<Us6
wxi01DYsCJ%|+*e@=w?nz1+~UnDmXE;*qBQl6E?2&Xj-rPOfrnjjN+XI<g1WXnI>CvOVssFeXr)M12vqA*s~<gPG#2;cr6=^X!EC
N=5T12<eC!7Sht@-Bsg=ujHoGT9U+UcyA&hIO`*jq8#UjO_;<h%5KLF?O2COMj@)UMnq(6(4{{>tcw9F9wZ;O{r&`%8b_7>X%6gc
>9z_!_)!!LUrlTT?gV8G78Ry6gaw}+K0@$bWczhWnP0OOPZ|z}xL?jyESVn&mP8Z-jJrN?7_Jx3F)7+Vi(PREp|?otP)}Qth&-Ec
Az+pC;!+8l92<>8ib=Oymjb;HU&#8c!$pm1yrhX22=&PKorPoPO87jv8Un4$XO)xYYxQV^{F7|BFd1NaAP8lX>~)t~#o$e0HfS1s
=AAC~Z65M){oH`;=pv3-<d@PX_T$fu7qQgzIsn$F5Zd0;?}(SJ{O;2O<LwPjAJXEjUW$#2U3H$=L??Sam(O}-)4JIt-I+=H72#47
v+cU@Za_<5*Z05f5XaICogBM_QC_}!Lz+S3Xtsq3Om#tkhP=vP*in2wJE*<yFh{bHrWu{2CZqIxju*|9u+{&SvvUKTh{xUm<Xd9p
JbRKNbHu9=KAVg#iywn+`DpJ-a4BRm&S>jd-0=eN)W^Mm?36Y>;q`y{70E6KsWdQbs|@Ei23j}lv!5-pho>Khmf(`iWRIdKcpV)=
_Xt;dyb*atpM63mD~n7bOsbnMKt4%j{$;FyLN$UGAtMQ9olVgd>X>z*evT3zcVRX=Gn>(W6mC%9;4Umb7vGym#%?Cl|Kp!P+>>4A
@)tk{wMG5~Inv~VYx)9dO$3+Wy^^<yPWk!<1kOhfDak=e`t+B5mmb|*TG25b;|~SU&tH|A7rG+v(Y*_*t|BxkFdvu=h_E4FqWpDU
5bNG#L)iw@9VOz4SkPz0b+Q)@N;T@3vCeNtXl3XjAIXWN%K+S{3{+6AgVvzl8=$@bYDG&P1rGerrraVsuI$F5$eS(%P``~q(uJyl
soC*aN56cnl)6lY$w#5VL&5&q8$ssBr0$7($FvRU?X{qv(13T9`|)dcN>U9}Kl{bJfaHyRr+)l*JXtMxhAn5R59`l~2B&1)<PZcC
_~`@>SrJ31-2B4>Bbnycy1`ASKQx?Cu}2W(JCcq|Rj7><lC>N8uJJYElt;XMLxwQd4i%e^UZs65AJYUAbRIh`?gXsAKzt{rSHgc6
g3^ZjKy#3J_7^2c@A%z$&;AFD4#j|6WDL>J)JAl-d#P6giu0|xyCoJD%bQ(UU8UJ@<tx%M_T}*9ZNNYad?!=u!G=cm`vj!k9$0F0
BaoqGdC7W7`mO~64Q2^@v8t)u5%R6|58o2+20(10N5>v6e0Tj!w=fXx4xCx{d}7V`P4%@(CGQaUg5G`&?8`UAY0v08?fA(n=sYb$
nt1H^7ALu+g=*JADIn67<eE1n%9U%x|Hjo=sfsJ@9I_YdiXXj%OV1q0R$sA|j7see!)xy0OFfNdb+YmW!mS1*@}h_wXgQ#x*<ulm
upRLeDFh&KQzxn;O;;6^w`tBLZWSozulK(Vg#F>@2mvz(9yX@6o8qJv9CEvqaXhSRnbXHMd0_AbTGHNdrS;}kJo$L!`3?){a1`sC
7|`req}fOjZJcXwOX?2LUm}-8FO?v;c~$5E*0(^}^ZJ*UQcbx&wuHv{za+$A59FPvbq}yIugk-URW&EBJ+P5g_I-a$MvA2i+N(TC
A}Ep&3Y~}nebH!ATc}^=-KI3LS%9G{_U?!cc*%IG5uprA`Cm#xI*oQfkU;MLmX+sHjnj{x<<T{ag?TrQkgp(H7~|c;wtsm70^5Yn
CuMLapn4HiU%#93>6)`Cy0JXd-x%ZMD1;fu$kphDB8Hvo#hVUEs43&8%->B*UlK+|H{<hlY$^E%HaI@yuLyUQcUk$aUvDWqyxuR0
s)gavcG#MgV`e?xU4MA_WiuIabu`)uyhu~A(O^!84i&7m`t5j3$}O$#9!3IWY^5(yS@(djH1_a102cm4CJV+6#v0qHF~)f&vJNRw
k3hnSVx}l&%$gX>#abv2ZZ4ug-!{c^K_^fsjuhk9HZqNW%2QB;T5UUvm{d20(mk37*VZDNe*{M0>at2oLg{!DxoP7gSpn=g6EXr3
X)@eF0_Co<_I|~HKtWnRl5!w8w01mJ_y+LmeYS3)6J|>&^bJ2Q*?t%hPy82#K0s!hc-4=4IZ&mo7THr^K<zzDK<GWFN4snbxYB&7
*V5?1kTk%9qH<$RAogBZ`|cZ;l%Shs!{dQqBpdF$opiHytK%Czr!wRbGFX%FF;xlNGdTpx<sd!Dgj}NZTfRf5mVmy4c?;Vu$270g
O4r!cse0KSEM{F-qA@R5Ix^>7bCRY*@whIFj!D@0f26AxYQ@jM)e6EwtHjux?1Ja;t`bRHdp`-(OSQTTwc_QXJC-J?>Tx#a5nm5>
m-BZ{f5yqlM+@B7aAC#Q3%va<z2>{YxE1hd@zl>jPs<g#1Z@?c9sC|V_Ci%9c`W~~GYP8=(>o6R{eBG8C=|$@#q+S8LZ_5J^Wb$B
8}>nkXa{=|P~?Y2hc$-ho5_33^*b8Df<>o^oDk^Rnc?9O-Bt@n$-|~(caiu`GYe4kSby10@jv`%G4m6k9OJhqWK*{ME(g%ELE+wT
(#h3^*&Md3@0Bj(A9gOeZd(E!*}3(K>$14kV&0QT)jx(?i5JNFS0w<5L*=561PVsmy^f}H^64YhTbFl6kgC9xF>#>0*!<OFlSAbi
sFTUj{J!<070!tfuro{j{BMM`DP@B*guq<tvryW$k?TrRsIlWci3%IRY`ncN7gT@Ng;WjX8^liBX#S7U6#U?f9;8)Fl;a}A=m7!r
s2QR1t`C(g9^891-@<*0QHdGV#l4mD8TgTRpcJKARPG%=p;KVP+z9#YsdI5#_GyB1Uiq96Ba}j=uDTHJ0B;21c-rDeltKRlO(CDB
wyMK7&wuT17|Q6fpt{T5{=Vbp(z>e{jUSCS>e<x)bCN*TL28e4|L;j~ecp^j^JNks5H%}Rj$N~95*6fcGzsdA;^?e~bFvx?o?=d9
9$2o5Y6W?XZllwd0<?QCr|3>Ba>8ynFYwuqzvLH`et|6VS)wn8mmNc3(~GP0qFaodL!`c0ymi<^U5lOI7Z|+`+KFRdxw74CauMl6
o!s+t>9s@nvdll$?Jn8m5Ip9l0k48ZIE;#lCl$e`VM3^q1pyBLEiy&~5b%ZWZY^k$3(HkRS7B^yT~lfycNV1&&JRD5g37;%*o0|g
9UsTpI8+XiEMWIFkkP7dy--Z{Z~+vE+pT(r=c~WHuUigV&e|qjj`9#)-tT=E4N{<iKlho=Z4I_{?FTi0^x?sMinvz30niCcvT7w6
tJ&Kk@`FTLp9Z-#YCFrBsc0liJ2_h8SZ-emOFc%h?<M~O|5^YAE^H3vZdLtDSdTH=^x_4ePdZFLRsHKKRXUjWEitB`wC3Rxmcyr*
6`Y_dAl236$)^emBJ5eBpp`h|(UDHq00m0vE}}T!+QYHfnklnSFW*)4`;4gp=SYmkleKi(Z7@R9*4_imZaO`-g<w|J;sb**$?UFP
%+yI$%@u7xAR_|%GNHOPohyb52hGNONbFP9qzJqtFn{Tar#6>-Br=hX`&x5Dg|^HVkQf3Z@!Bo(yeALkJBKZO%|HYJ`=OYARO}NC
0O3Wan8s<9a=9*tsCI9H3x`VG9ISZuE%Z2ol+Mge9j-&y{OCDFX?(@OjXORncGZHlX>(dI^G(q(2ywLh=DIg**P=b30b7B`<VOnS
gj|p_mk}d+LKh}Mk_Llwwt+l(UkJAgr=zKp>R5ne2dOPCE}!+&V(z|VDn<#Exa@7_T|`{y=mjQ!p>wLPwAelu;Ue~9we~WSdjHK8
#-Ce)IXpDO#ZWHf7FNdahXSqUyZ_Cg&HgG!bFRH%`fwc==q=5ooLrwn=DsGNy}uW^8y2J2x17*K)D8q?S712!ICu%X_ayWLnM{&i
Z)S?=Y~s~Cw5Dn&qgRb>LwE2P5P7_4r=q|2y?R7)rE_|ktB-7@QR@POVnZ$6&JG)lyrQs;uVlP1qu_Yb&fFzd^l?WcOd7-)>@%E0
(4l#jZg1|QMI0(QN$n=j0bTzl=~vAZ(evXhcQh+op+H*6w4Wow<ykq1%VEx0as^X=E94n}tT82J+~#7~MF*dx^uy&rE_dDSpywC#
>IBvHVQ9_Cw7X)@#v9_<!u%a~@?<Z7eoO(i5QLGa0*eB!M28A4Cn2aE)RQasD-xhbpsV~dQq1DJh?nbLD#@kxla{YYz(<5c<n)x1
{i2Uz_0;fYm<tYZgHd(3XNOgFNKMlHbi8yo|Nj*51VL#b6YY3ZJkr9^^<*0w3NZ2Yh@%C&F5@;*X6gAT+(3Vb7Lg7!*OD%*oZCle
o$kIhPpt$fJ^Vv~J(sobIDQznA;0Bs2^q1FkL`-K)04yw!r581sTEneBta7{dv|!ZDX!j)n%6LNY6C?dA#9~bRTXN0)JHR#zltaR
zY^#rC!=>qsW4=B%)|hLT~k-)f;UC{P{lx*Fn(i)!TFq9wzTbA>=fY<t2W|Fcrk#F?5=U}h24~`-V?3rij(MSr^y}lbm{3_6N2|9
)dANg)3CKR`vBBIjz$J90;-lxFc|$OM|*yv`HIe>N14ZuYH!Ml^}*3iujbwo_fsG%Dw471O+3{LRb}^URijymnY#A_w)i><suLrg
Cj<Ok;<Ux9B|hSb<@`=dW<Yi)1Quxb$k8XG-m+{Vv+72wK>4DnI=$i51*^VSW74GA=wH{iORB7p#QWD50&g_CzF_$458!ff_Sq!6
s6M)#TcE;(whBb*b(wZT7FiRNmp=zmke~ztc4*Z?CYJ$WAiRzrX1(j#J||D4<~-}o``8+{Pcx`=riqa01LrEX_=Het)o=49Vr4sl
^t4E7q2Z+@T)_dT`z~rSq!%a<L!V3C=c?+XE-q(*NqzH*FA6$ju5eV-;ww}C`vMiicFBUhFl7j4c_=SSke~Gh_wfR~4Z}}9)!V^g
0rOGZ7I2scjxykZDNdcQhW$3Hq6X3oe7{{Bx9SAix`D@R>&$}Q2c>0dOAAHG{FX$)^Yl^Z;d8E;6M^7R3F3GEqa(dpB0IY{Nw-aL
b+dyf9y+}^(K?(2PTZe!-GXt9%lD=LGhS*5a0;Rix+mlnocj{p3~*>K|2~61tGkTHwu0qv+!xLI+BWAdFcf`>>oBi-g9fI~AQwJd
l?dP^?;gW6*~e;qvS_>h1CS((?JDOTBtaU+Q*OAJlpu1NB^dtiz@DjNxZ+YsGgnBcty0)=GNz86mo|23JdmL?O(+XuQ`Px9#c^H^
*emkYL0v^2I#-2s((e-%^qXHu=BeHF@##Tg9J_6WXuduX_6^KCTXSS$S67{JzS-}Ka}nI(sBm=oQ;ud{o_E;dD7i`~iu^?jOiShP
Qihx?M|GP=4!M5}KgfS{zNQATX@O61fb@~79oB%}5W!)ut2vYU2rQLmWiGfX5We^*1o8gDY(KCOEuTi-2X*NHVxIl%zG4v>H2V(|
WqxfrxTVjHzFlt75n#XTfFa+U@q9<wpq2L!@ciK^XCQ4qvlW#B!l5GXaK+ah^#un95;}r9%c;QC`@ZiA@c(1h;Mh?$gv@6^@#U~D
Z8p9iu*&!n*2>yHv}5p1Y~uAkT+t*3b9O5e<rcU<*bpUQ^O<SY8P2qvRHJG*c8u7!r1)3Zas6|8{eQ<Da7>8yi^Og^c{Tj~1Nwv#
`lcFAm~}S<0l&e1sY+qgi9XZu@U~3sb+$2xYTl;!fh=**bwXs)px427mn@+8jwBm(K!5_k;8|ezdP>HT2!HHpYV6%W2R~kG$4q(>
@|&C67!Stm>&cbt-ms9e$x7B`jIRtHf^Fc{4NO^^Zr`VyX0fF3`3yl!bxaG<O7_}k0)oP=vLdENBp}awkf$6-vEQ!x<xp|OoHwXZ
aHT@Xg!|aCr4KpyB~^Lnaqfyy3P3bR-@Hr-0l-Ls=F*+@D;lZ&=S`y{LREW{v@!MSqd4URHsJWBVdHGX?lFkIUOye0zfn}4-uDHM
Pl0&a3|F}z0ZF^??vLwI{)p>W1##Er^CUsy_XE3Haa8hKEK@=3x+d#YuV5C|wT(2Jj8A+$_xHEBJ75w&ajr+vaY<i{K2_x<sU2r9
5eEfpz3=#;SR<$_auGkbXzt*%%d`w2jWh7?I$?`!fqIk>kpZtvk)ZejSQe|mIgk8U0Ob46jvRn!wh}0b%R?3GlQ@WJaY~weg!&tl
@p}GSx84CMi=o!b6KsxuEII3E%amjd5rWFL{8}yZkC8$>xo;MP?|{NrV()k2P(TWfn&my^y@?MEQ@2l2Nbyb3KhLP+A>wlbv$r=U
bqucxx*@C7p@g>bQl~f7N{piT_FuM2GufHyVt=(X$iDS!`ZZjz1*Wr?>`S<4<O0Q1^xBw`;hNVF3MIlYI!Ra1fvpXOdNTNz`*ND8
)Bkm%7ro?uLcK7S_hjVB0NK<Gi<a${miL_3Q~P3>bgHXSIY1B7d(q=lIgX_bH?Rzs{};c?R!wMe9xD9E72Wo8$OgXPuVEE<xb^=7
v`K#Tyfq|>$TTJXE1zcGb&nDbH?KYB_!+{nc8Ea4Z=6d2r07oFgromGwn2*??Fcxz2X!=sv>kqvx(Y=Ls@WtW5()IJikMWu#Rh$O
**{2Ay)tND`oan{I8axN3O!HIv&WnX)E;`uzziifUKkIH6(6U~UHqFm?3|Pk!-p&DNqwdh$rr@?(iGQM9|>enk#Z!j9*#}O5A-{*
r(pxzcuJuMyyS^>PzC(TDHv(jJAwTg^tp@<L##>|E9WbfIBF(h1ocs=EX#yJ8Zl<u82b{e^<O7+46eubeCSRNJfCVeCgc<EP8H;^
dS>O{J>&p6H_|M7BsL^Pgr3o!K34I+1sRRkF3@ys@maLfw|Q>mhoFoehTnXtxkK&CeXFs=4x{$v9KE(X?#9b;m0?tz9L~<%K32&k
2-z%k;{rI4jqT$#=q?C-`cx)#Xr*9H8BSdi>Grv}lOZC^PV?;=nzVu{i<#Z-Xt~TzJASv0w`YBs5v~OB+K-XDqw%yLN7}oEtI241
I3knJTD=?<c=bipzAV+ttBCXn1?V8wSqs|JT}poI=o`1z_V`%GaSJ22o-BYe>G!k*;QSNIrn&jh=maJBBZEAfeo$NRLjLqrcr8V|
#nn<4e#fOL5C>VhkZCtStSIK1!}-!Ff^(34-{G)1f|*;QurFO-{WZ?UodL@_jIi*%s9(lQ7qkw^PKKE}k_%Ra){cfKwULbP<!v|k
navW;8xfEk%pT8=^8tGf<_a>8xcv35iEZL$Xd+x0Br3Sh+-+WG9Odpska-*4LMBpmg+b{6wZ6T!DJ>k1dm20fwmA~3L2xjhjU-s?
4m;NW(5|fo1gWPCplMd6Yc1>QD8q35eM{(`0b62qTL2#T;%NU#Ymdb=#IJ9C+ks)-%()I6?Hf!i&|NVm)fJ@(&z{O`tr&I2Wi6*K
2>V;xb9m<<pwUQ`J52c`a5|6)%q0i~76(v!kgq(MF4)6h^xA2GhaO<iB%?}vem{9+J_pFXcxE}d$LgD@>_2J>L4cWWLUY!XjfWiM
yXT_Jxi25FEwdg;DQX)BSoabKUF!*sSdPPD;3RPp@RPow;8Gv&_2ozrxvG~{h{5saCLdTyo6r*j^BnQCSS2{)$^;f;QV&gv@PMP{
47=>qW(7&U!8~C<-oNjN7#pi7gQQOm$4S{tncNB@*%>-p1!Rp6yAX|_m<5Axv9RYNXGN`o$&F`lLnRIa`eVZn#3ZMqU-Pd%hz$Ja
--v2P^WfyzS4~?T)6`&Jjsf6+9R_m+Zv3<Ry;my){dDD7=<dkhs8;RXp6F>e1QclW3L2=O7fwA}5bP6W>VK{cre^_~32Jo14Lzs)
!uy4!H^b-qCb9tT?z`yh=}qPCcxM8&?3!5(PSf!xS(V_nXp*dU>tspSu7aSwqHnY8$UZJ5^{Cu&2vH@NDl>X(LIMk|v+&I;_`jE0
_F<v`zH5qbPQe2=*R?bL;n&w-(L?>1*)vW^QPfH@ijNGsu4Xd;IX}V~RZFDHKakwf54AN!!Zz8P891V%rZ6{I=A-)!5b5QMCa>7-
n*O`8pj#88beMD6AwmM$%&1_%+Rw2Epk%e|dUABxANt-ysQtcG%5{5!)zPF4v4+~ODYJ*s3xb4i9_yBfOZl{*Rkab@mgXqevD=3P
7ae;jGaFwUQOiey0@5sPiPX+Vh0A(~6<XL6N}+5j#M?fwa0YPyFw|L#-C@-D{D0s9x7CZIW>&6sR$c<H27*s?@%oL)8Zz*&m8X$@
t|?&3NQ=t%>`I3Q3$zZ`Bw0`x=3+e%<(uz=2N#$e*`zz_2&m0?$DRojI&g9F_bb{gWvCG60g$Guk&w8;ixBYfpHVC`d^l}yGHFZz
cZ?;7**f{FbMtcRy-etYQZ4jvtt$bl?6qc_1Y!=j+7u8tZ&Mgm#QJ9l{@KV{p->`j*Mn<i;m;KxO~~Pqf)**`Uq+CSfvT{i^mGqX
^#h}F;I(tI+2b^^ZTV%4wNe=yVu9wpVB!#SKxAB{6}ysvi)q~DDUKHd1?3|n*vfBPTv>LqxX?l%m6Rs-tT%?L>iX+f*rMf~FUN_*
zBmh>S^YVHo2;iEagC5c*a$IBOC&sZ=uH0kgmolTV$fVtI?$?<aEWxfH^r$NA)W$hSM}*F`y_H(jRBq__ph=;DP(Zn;2=0-3w~R<
<FUai5>L@N*b7G0e?c&o`zhUbY<^v2LmZD)@|$g(y;CgV+mQ2yi#86pjno)h%Pvysqrf2j7Q4Uc0l;cZBRjd7L}WqqukJE)_q~V%
#HsLutV+sZcC&NOSN9@~uJmK9+|rkcwltaK@bL5FQ$!3P;btSDUBuH^t*$8G=1X2p>sO$;7S{G519B5|tv%mo*1P!%tw_(*Ya2C|
30u<%G&3{+?udGT3}m|CQf2r#CMC!V+c7hsjGK>fUOd=M@2ad$4RSfyR=;yCZL3^DnScf+u~m*H739&VD7*kuOgPTfNLoO?w#c(m
q%G-I;RaL@u2n;JNYP4k)Aei)OHtmwKfq?*=)pG9KSzE#SHzd6`l!;pc$1ZvXN))1bOWRS{P9rJXUeguSHXi%w6Tf!n`<>dWRVgf
%+|N}I7?qN%`yAy{-)ba4s{oODb}KvAXhn4@!82;=YC!$o(in+eZ=v;KD5ldu|AJ+#q2`^Qy6|FL(S*!`*-Dk3v=d4>An)_D-l!m
DAb7BkT1MnS2Q-xM1ne}T7q8Khsi}Uikw8Ds1rq}hAGd(%SIj4nMx4mZrZJeCl&^gdmFjN!$z~LHKl#|&)Ue%LvB;1>VAn6?7@go
DGs?JzJlLcPdRAK_*Zz&T{Lfr=rXgt;*@{>nCWm7c?1n@TbJ0BOI(Ltcq@$K>j6vv*MN7w-$2Z*Jlj~QibD?mBx=yd6_^AC=Z#@?
3HgMl2%x`Nw_^iDjvc203`=nb&6s1_W1ZbiATy4-wpo;UnGZZ~{Cp3ZL&@dy;Gc=;({*J~mst2G0BU?1a)_%f?_qNX{t7hkU?2JC
Gs}uh7_@H!0}@P#1i&iUL*5<hlak3l*sqd|Q!Fd@xMS=vVw5BEtYe#s=!K?(%dC(5UIHZ4L>Xa&;^N52OZT<f-8QqyYIS3!v~_m|
r_;Oo5n(5hw;!R%k(!xJQFriH4{{bnZ!apK!>9^^v3ZqNWn+S$#%T32dnV&3g0rAGyCWVU1p1}0yS)NGMZ`QlBG;ec_&5KsMuoOR
PMt#mrODYMtSsj)Q<*U-mUmCi-J;;CqY^g3ZlQicC`6SrhmmrV{|94$H3<v+B}tbwbE8+9X4p}H_Kf`j<e}>=p{HJ0V<%7HIV7AZ
^^=rtCi~eS4iJ2AlO4jHK0@q;-NO7{5e}Lh{#AdgMJFyUcYHv|l_IWO{|y0QjS-%ccj~+<@c3fo(Tnm!2+l}5+K!GrfH{;Vxt87t
P$p;C_I>e9s6vq6=4s)F&R>$Ol!wYc8oGmPpg(U%iw)cQ889$2pAJNp2{S8CH2Ivx8cEF9?eH}?>#>6)bp?Ss`1he^Jw~O_O7S!8
Dx8Ou9PAU^RBV5PVtk`9JgdlI4Ugj~JZi0l9<r6ygJwXGLkP-QX}bt9oSU+%Qw3K?k+uXmo@zA#-jCZI=EYC0)ei*T5VC8s`!Uxr
YSkTn*sa)csJ>}$V;gCuyW1ZP2-P^8H}cLn$c_^_Bd4wdR37j_Y!)(4{^f}CrQXb?@IFu6kwtMYtr1OXF?W-%Q`A$@O=RU`8jU@5
Kal4bO(`>Ultl<aJ<^#qx{#~_2Qr>jF2yhJlQ2@LjzBMWp~k$s%|7+DE-e-#58Y~HGWh`J1p_~QaifgIRshy)#zWAc(a2)z#{Ep%
M1>~0<te16WNl?bp*4T=_O-9BJqyJ_mLx~A!Vf&2yybOm=G5;hZI?)z7t2h;Iy|yCo-ws)tnLe>QtRm-3%qxUjA6<tb&}3qR1>BN
@>D)$(`HOuTk9gT54ayeAI{KWhnK7{vJ)huv(4L@iYoD3e5yc1Z#!^}M;~lFVz!2m$8A1I`!Z(G&25p4DH9~0fKs)V9Dba7&lB|5
)u5pN%1C$G8&e+HbI%$83lP@#${^_KHL?CUS18}WNpm~(Z8?XBSx8VTAs?^gwD<IS=xpi(`~2?GHBM@P*mmgHW47o_hSj9dBn=ss
yki}K29*0XPL#Ih;oWMCK*V3kJM|;@3;4NVxjPJiJFXZu<>1O_Usi0Pr|(I;PfUZjeZhg)*(ODX;Roj^dDCezi&Ras8T{*jo-LlS
WB|kW))myYXLkHZUF<<3(&VC?z@?RoI2(fHt7Y5IA3{ZJVu4)EF@2M`3cQ8v5RnUo@UJukZ@HnMaYu#Gg<1#1y=|}cgC7ervSojt
ceM!fPMcZcY2BSc%RW)EO)bW`%WSh9GFiDmX#<$?@~^UO+O{eDgXuP86c99TkYWMqHm~MVX)iJsQzSx$d6+g~oF=I@9F~K>rVUGe
6@h<hcJGvqt?Qx@p4UnXJB@~3V_C416|R>J-<lEnCh)#%)Na@^Wx&X>pj*)2!}ai=LAH@vIhMloel45O(<+VukeA;N2Y5|0R(v_Z
BabkmFuQ&53Rn0yB^0P}VBz-3ztTp^@>Eqco13?vxjKc{LFM~vjtx^-3MmTK=s%(ffdCIFRN;Yc>ySs@75RY-L$={fq?lGIcb&~Y
m6QAacj~n;(L~C)5Vf9=AE#mjsEe&B;F#|#lYLf(pdO)-f)@RV$s1M>{U7^g#j}#%JApU)!hl2ow6(;IocT`~RW@eM!-SgGbER2Z
mb-V<lC*D}cjw>NEZLzFaPR~@%hb0>@e<76Lcksac|seaF}i5#)wngf)WN$`r;Dr*{<n&sXoq!nyM<ucOGo*E)sz>h`IR&)po5;3
HGsd?taWfH$1Wg>kU;X<3GDyb9}f%w00000fwjei??dc=00Ff}qI&=UeS}BcvBYQl0ssI200dcD
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

# Sons du combo « Bas + Start pendant le Toasty » (2.5.36) : 4 sons de Mortal Kombat 3 (fichiers mk3-09440, 09160, 09150, 09155
# fournis par Nicolas), deja traites et encodes en ADPCM-A par tools/pack_combo_snd.py (comme le cri : mono, 18 518,5 Hz,
# silences retires, 256 octets d'alignement).  (c) Midway / Warner Bros., HORS licence MIT, integres a la demande de l'auteur
# du projet (voir NOTICE.md).  Retrait : vider la liste (JB_COMBO_SND_B85 = ()) et JB_COMBO_SND_USED = [].
# COMBO-BEGIN
JB_COMBO_SND_USED = [37627, 49985, 50859, 42412]
JB_COMBO_SND_B85 = (
"""
{Wp48S^xk9=GL@E0stWa8~^|S5YJf5;7b2Kom~I~X`C?;2!trHDrADFcX*5X`>*Z3EVP+Mp^3_T=|&FW622h*n63t1riWUUzge8v
lI0>jjUX$@Zkj)_v2RO<mW#I+ysQZdIf#wRv5~CUk*5CH80|yHA6}#b3YhaTfX3{V!mxQ<axjJR?r43oH^8!1)JqJ{_X9X6Na;J6
^}AE)CoTsb2a_S^@u_+XQ-0`=Oa9v}q(!n{w-qV7Bc$tVTX6}cGrDPi0kmjL6z^_LrZDJY$<na3oTQhYBg23&eF4|iAj%jJf5tu3
84zC0F(V=aJIHw$gIeVO?*#-FrGrP6$AIxWFVmFjp@<vFQ)w6aV~Thy`mWH6_q#X?Fmpvt#{Ii5uH)YHL<YeI+f;5IQ3=DDc;I!`
%G1Z<5J|U#BaS`bQU``o=`{ABC`nkaCg<^1>#!|VWh61=pIg*Ak(rx0_7NNV9Y04Dj98-|jS1(bFJ2tA$Rpc0+pjZLlA<p~I#~D<
;k5Hj|Ezgy1x9BeeoSL8FWu_hzowA&o|dqXR*1vvCBK&TefCUpFZC-VJXDZZmIzz#S<hV)k8FLQI+D7_uXaCmF_DBRhAQ|ZiterU
>?8>jJ9n@?La^Pk;3O0F%&8HSMplX1t{T>ij!3?&0x!4;(uc?G7rL-(ni<Z2A$Gc4=*+&@zK3(LdVaEgUUA|TNb0U<GAr=5m67?d
NAb-w*f*|u*72_tM9@L10L3Kg2Xn7J${c6h4lod)#I(iv)btFjC<hE+<$KB?X^7C!BX~jfelMp06Kynn6h26lqsy1#(BKK>|DV>C
f>o{exhsZ#+FwT(fBapO-N#0kl0Upx6>Y(4IrB1PH}Y)4OvNB%JwQw|J}9j#Z+wTVCiUb?CmVdmFhS{O-FF`@IMaUqJ<c$zSyU8R
7Js}?MYlqK)4S6=+Ibq2P}`!+3UZk+?quuY?}e7pC#xUym#h}da0juSbd|q$&>lw8_NkNG8c{_b_Hdmrp@|o<73BG`1^uWph5F-_
O_J{MecGO_L1-W*4^4{y<P}EODp0sT`hG{zWMk2)>4j*VU2#mj3w4k*YLP{ArPLfu(V<KmJutZYmNN_HH|X+4t+}r@D<HHKz^OBo
dKRdlq7{gF-S6YQNsNoR&UIdeH5PP+SY&oxN~#>ZK%YfgUsEFklN_KS-7SfBaxZoy5R_qw*}<l0ebAVdh0R%*+7D0<g7WL+iEViH
v_ylhFLa?Px`?d(AUYa}kA8<eF)SDY#D@{=T|G`=FHKYQw@}^Mt|6O)Js(jGnP6<fRb6|!WrM~0)iSxB08oM)r{kAcPS`?ZcrSVg
``EC&aZB^f;a1jvpb=$i&c?x~oI1AE&%cz$d@_7N5#F%mG}vcV*BIt+Ov3YGm@OHezG<F#F*`+<)UgBanqb{{C=xv0Yd6dahxAf3
=83O%y<*XB<rfd&N#Wwp_$Pjn1Y3D15W<zIlSlvc1v^6LO%`j@G}N)8ay)U6WctbS7(Wxupu<DNz->ic!%?6W;S>1@Ec!(^AaF}C
a&WZ&Z|5w+rjOij()-_sZl<x6bmVhRHz{RG30BOS><#rIScG?vX9@IZwf*o|j+htGd4}Qm&;f=u<=APS0`Ej+WhJwtVq(iPe+Fzo
?~Kk`{-hSMGhlpp6Nf6q;auHES8A=(_VlU;PgS34>{0uWpR{Li`u)0#sIE6>mKF)liqXpq*J~B(Y@zu#>N}=LekoFnMUhERvHgWe
Tq@&J;qI-(Qw;>t9xELKnx9h<$steeclSeVm=#oCShR~{yDw#i{pKC@YdLE-pW>ixb-X76Pi+MUvAJ&B>-3czd7~ZEv{;pGT0TX{
>fVB>5+pYRpk0c2kClVy#G+Groh@^>L_21NJ;CK(Qj6ObE)hKd`mmId_{Wo!=Tc2kWByUqOBiEWPBz_e3&7k=wiDH5vgR<m>Q`r`
&|%r&On9NkbL=ol*$O#eZ%;W4vg%@fx2cz_q5s6CT@A;t-u#w}14a`;B*%eC)}oA|vi>Vj0Zj0|mm~5mJM<SsdB>@y@SD90z$g$t
tY=tUvV^BZko*!QT$}w%Lgmgqz_^m&tKEqnbjMXD2b_{_kJSv>-*+s<4{dSU76|2H0czf;-Z}qrC1}prae1<hdGyWHQ__WZz2mtw
pRq6>U?b7E4nbNAZ)MUnZFeChSfY!Of_)vd#iH3;9dx`F=j4kaha=i$;9?}MGEbY{beF?=dytW)yxI%D8wTn%exrB#oS`qC`(e+H
101%hHO8QFO%{nH85TS_a{j2jkL5R+hd0TwT0B%RIDYbhs4@KN`wfY`R75Z@^${r!P-yC0-yAX(c0SiJ^JciEA;0znc$<{lj1IY`
Sr8P^H0y_mV_Kb~9@(~ChVV!47)2gJ$ERCJ?YCfJxR>7X{D~ui_7i+K$Dd-y7Q|=u&Y?m8?Nq*>PgNAG4_X==cq1X61bp(DeU;!1
+vR^A&#14g=V&tF+|jYoHg+x`6<21h#+6gLk$lGz5cm>L(*=$VgyHQJT^3!FS*7^*mRUY)fr~Vix2|-<*RvI5aHnn;<JjjiXQ}*S
l)ugwikYG+R@ek9L0G`ekVLJ%x3jF#<df3gwGg8QC@@(yd2JTSs=xY#4lsp<sy<StV*fiKeF-Ij(bvIZLh_tUt!E3U4IXRT;}I$c
();K&E;olBi6BQwfb{1%i3k$n@dISDR*wxryeiZ)CW!hHv6_4de5z_B{cYc-Xo)3R`{%hCZ2pCJssk$PK!sb~L`_p5x{Im1cL#u4
mzMO<=yv-QAge+R$>O)T$bD<!1C;BklR{I1?a`VE!$ahrgW3fk<mnbW_p^#;X-=-I;w`Dg`^mrWe}GfYW&t{#?E*`sX&^$U<5-ba
(~^I;`f!?w0smEW__8UIEp)^AD<Ej54e&}BpD@VY{9G`|P(UPOKT#0d=fOQ-4nFu2QttyG+Ufz=_I#spB~jRNtr8xwea)rdV&KZ&
=>Z&FaaPmV%K0C0dyjKUD`#)oM<bP8b1xaU&iLw3T)sOO`KPKZCh@aOEvF>b<G^wFtFtZl=kO|?tGj~;IyhBG{;|NFuGJ)0djPdS
OfpwE634@bNI@y024EGtQ!!h!z;huX{}DiJJ&qa2O|v1-A77+@3UvHu)9{L$<XCqo3U2vnA#IKd`UK6c2tLDU_z!VY{$ecYzI`|;
YgAe2inG$dT9>(4ake2`;oP19EKG_|0nk7j0tbes4iRdPi8b5vj5AH)kn2-w%vWUwd)peW{X)(?d({O~tvHx7i^mb|3Z|3D@+kuD
fp6(-Rdi`2dYaWkyF~JONxl9jg1)y$R1!9v4C-RP^+<^Bd{ik(piz!ZM)2AwW27{e9Ms5D++cc7Q!X1O`*1}_`aRgTP|m{GLeNm2
V#4sjb=f<1S}=H8ieCALfls{+%MshO$F?I^&zy0$=1@7)4|cdjvr?z4R96UTkH;eCz=zn1GD2aPIGYcm<g6`|%m1!fh)Pf#sBnaX
MyRt$jehVdB?lLI(8@z#IK{T!C48HJMhtU1-mM+Ff3|o(y#;T~iT6*7sKhV}jJolm%vwgL_Vu%j?raOwv{OEebO1O{sRnzu?l;IW
!ho6#UqkCM{3Ui}KFUgWP}Cc1qRem2Jr4=Xx1y0CM_`bHZB$VM@Om?Y@10gO>8oswa^3N=S2?$bgr{B2U?V=1$D;5NE2j4%E3U=v
lHKRn#1A|p%{?CsYJ>$w^Va~jQm*1yrvO}}Nsr+4vGN}nd(kr1rE6o+P6=S4wp#$Ckj#tRMfzD-7>(3hRu)N}B{3lT5x$eGZ|$hj
*BlSs`9x=`kB1NK^jMCoyi`>pzWcqmY(_vZmWEHpZ1nT<fzjP6b>_YR48F3e<ymT6hp(6xzmmXjO^Oj%!3q`Nk+x>B#5$N211pA1
gg<i<D?5n|pw?5p<#qF&^XlZ9vTd7^-c=I+BMkA-!miy7KWML8L65p2sIlTh1BsaK^!$Y7MWM`hrAKH54t&W>;!hQnu})CH4nw~>
+1o;<rI<lR-G<ggRk0K=L5^5_2H>*udMW2d4=R>LVwa=!)CEpODoVU6Ix%j#bXb?_r8Hm<##(L@#0Xf~jqGC^&iYL9UI#BHJf&DA
cu(66BLIqpcYL06$f|skRIS<Ct|LpY8&^0ym`*-GwYbS*C{=+GY@Ics)lu-$ZRWX0HNf=$=%veSGM?pktHl}gNTXg`t(P#)h8&n3
z~d5E@6R_9;qt_<5O9ZOcEeI4G%hu!rGPk|uw(2{@a+P-e6uT3M*9KjuGw?!dy2@@r2mKOg!!;5#8Nmy@-_oe;%zg`T#SH}7IJro
wnE>J<NAY7%vulcREcyNje<oep9>fIIO&*G?^VVAYVq%*DR~;ES*jn+`g(2$j-5YIoT<xNa&G6kL{PoOw0U0I=C*2ed#XF15EaS{
mu`sUWd&GxgU7QoIXt4Ii&)<WNZ1^a*mitfp|ZkG7;q{b<s+?;RfG}NFllY`8i8jXkq;G}EhpCErbMw->Khn6O@xWjZ?Fl6Hf_Lt
gWwdvv*ymqhsSSTE!FZ2+59LDf@9Y0%1h3y;-RBng;%yy?Uy14(qJ`r-2LPFWDGl;@ygh>Ogq<4wJ%QGH$A8@6M}?~rL)P_E<Tu?
teYf@K#^wL2_Qttp5%2?zCw6l!=HhyuzCORkS}E5e)pAryVGnZcM!)EO=o4Fv0?PWZ?SA8bs*Ev0|a(^=yEgp`>uAJ{!g&j2>V@e
`QFBv+Y+dKRu6bn)(3Cj013zP*xAMgIU_kMx=w}16-ynp0`2I8=Dh>y>p%Vu{daW|bt0veH^;er1Q`SprVC$CC0ii1Vw9SZ20p$c
Df$mz#M!WW(b!+}wx`P}uIfyt&WUBtKP6D~$`JQ{L{r8{&rWG3D6o6O{7U^DcGi@qR6g8ZcZ{2!Xz=J_twrzS(vQk%3nJ7SZ_H(l
_a(roYO$R_=vHGRNwoVl)^f1@9FvivZdYI|8ow8*VOV@;ZTeuOn|GvH`*HwfFXBSji8xKqQ)o>7&{RWfp7fU5<&-ZG%$TC)Wq0Jb
rOc5yDby^!=U1X`Zh4jGv5e%3-o;^Vo_nV`0BVm}H85SjaIE6P7R(SLrmxrZl@or!a@@|&Ao<~+ag<M7fY@V_2xlt}hk6nxuU1e{
i-klf5JdOA#nISA1o&w)2XM(^#zp3q`-0`<it)#clLq>W_A~0CbR}3+>D~LAcd@@#ewExPNk3nOXYq$O$Q*m}L`xDAfML%#vd_80
fI~fi6o&n0o)}e70*DtMJs`o}tOTE5(hDkKU0kKS=UaNU7Dn{sQCrRV*JPX5)`ITuc?An2>3$F?!Be{b{En$>dClafzFy8umACv)
TO*?)_Fom_qJRcxZUWW4;&^L!4P}T^v{yPO_{PV&4ZF<~E(|C>I%lz-6uu5wBYu$7J4V=#jLus&bO)fJ(foJ=Y3J03$87K3JasWc
+<=AN;?8GGcdQ$SZ4&smW@j{yntB1U0W=E@<tR-mrWb`^(P~HgB5t+By;f8yieY5#zpJq;WtnOrs2^~doBdcF&~*YIji{@5HeX9z
LtsL+z-bx~z%!t*NoqiPb-w88_xTm<?KHw&5AH{{gM=D~A*un4iUVGJD{KX$8(~r2u8i>qhwpoN`p-L?gYpXrxw5TqMwV;b8uvaK
_JDMvkMIhvGe#r-1b#Qsl+JZrhT^xnldv+oT4=U=so@Mmw`dU7n6(i<$yuDC@yc+_t6!zYd7jJb++4*>XANdycqAHDECeMv+k!&B
tM->RXi?{4xiFyRaTNIBj!V>D;gnxcLT<1pT8^*Ve$A`SVeUeGv@wN=g(m-#`@KjUYFAPHpE6)2af<>1v5oT2E*IzB!I^dooAckk
7BAIW@~Jg&v}>IYJI8-P(9McAQzRBs&Bo-Y`{D#};(^{MXTpH`@|2QH%?Dmkl`8MM_7p60W1XC(qu02xibco@FA&c=`E<yZ1sz#2
!3>d7yp!_7xq1`C;jBSPeX-rQ9^p1=ORSfjKpV>tL!b;{AWJGsf9JJ0fGADVb>&5|^023I#fHR2!HUb0)GY;;r$5>8_31VsUX9S}
D`obupP|bwiN!vSwL@oDVctK5YtaCAR}EpQ`uq`-XXaK|Uarot8--xq!KtM1v*;YGVc3PcJg+NZ`>GDKvRuWjJT&DF{_~#ibz`E;
S~bRbl|~afy%AN<%b;`_Rt1LSwXndow5d@cDvA5ngIE$eN;N36#}t#LY=%zWXk|Erd_wEqrTY8ux1GvDWUil-oWz_AUC-gcRL)ZG
0-J<Zzs8Dk2ebc7H(W(YvGMo?<1V7$YF+qZ^m)O?is0<_eqduOO9O+DUZC@P43^!k&MVBd7?FhXDW@PDKLzS6N0s?V4(cJ!QR1C)
`lg2V1ZX>h&8{xziRIb7LPz)d{i{lXyWRrcK?MtOx$DP%o4S)mQ5yAH!Da$IIRBKxwx>yZw(p8dz>9wAsOMACiO=@dRpCg0XB*gv
R%{%_ns@faJGs9I6r#$eo!0})lANE}eZMC>k{zdGk<3Ey8EvmWO#P6&V1{FaL%ykM--I&}pv8o52%4|SNs*Lp>6fC%zbUDEIU5jc
PRH}+dsIr=6}VGIE+ZX1Z%Tn`4yrk`%Mh9!<DcVpb%?JZAn#2e4U#=P>IkrG-)#RiX(0|VdIn3PqY7^|;1b{|uNhWF%Udg6Uys0m
u7e8nqi<^uRtO5^963TMG|Ki8NDVONhz2ph|IMYVgq7t;wPJXZE94r`_ts3(0!~4KMhB-~q0LDtu{w#$MT=5eN78ZiSOa;y?2MMV
PIFY<>YSx=dt;smoI}>3#t6D^kJWn+MNj?eY%fT}#V&_!KET4~{kf285<b(^$W4(O_Zr6oH}1N*Hc9qP7GOz*iy>Q;V72Z~6<6Uu
LIsyPIM(-|H+(ZS72Z<4gZ>4Ft*E1%kOsedV~?<bn}j(If2Vjf+GFp`P%zgzA?TD?3028T-qq;O^9Dv_Ho{C0z&ZHY2*3cPiLr_(
K9X+x^Hr$<AcPe5hUV4YexbY^qJGc|nIQ%Ec>@fa0o~N_wlN#IARSs?ztrtlMgFGJ&N8{swpatRp}mP*_f)M)XLM6%RZJ^L0(6~!
=2&sF>@B>0hZ0y2g>a(-0s08E*2+%wY;bp_&_dq!w^~=NcPBHoy=+k+-LSGMB}|O{3Kg&87&R7|#iP>R2h(Au<c~lv3rrt?Y3DSh
qDWvG^{v&x#dyLGovVOW11Ij@!6p7f%4^Za>@d7Ti}$uO@7oD;Q8Sab6l9;o(YL$teDa4x1d!__g|rP=ah==f?gC)UAS$3cze*Nt
+`Ql&%O{IM3$O2IX_rXxjmr-iy%1(BER3FZSB3V;h@RV(Ky|IoZwuqDtz8+G(+%h4@xT=2Ko2`&5`NAH(}OVdT>>+6WK;3|aIaW4
exOzR=>HONYRQ6V81UJQuY-o;{}iXy)M_6q-SRh{!`N!(0kh?O$yaOb^k-yMz!<99hMyZF-km@I;q<gw;ZfpOORhxa8XA==q_id!
JAhYH`ffDKHwM^y+!bbq6E2DSK)9g{vjV}Mq=M3vG^^09rqG@!C-zD9bP&M4T3U37DT?VtLNE<OlY8x5S+L5xV7Cc7^iYP*Rwx~}
?|~OAT`>)6eSj{7t>odQv01x<PuZ8c2DQ#0(mUcJY)Fw{J?NWa*N<mws&+eW)g*Kw_{&EOC)8KRJJhv0Y6e_+lMC|j?}2a*iG$0I
`CWj*tZST8BMX7uG7ynN<Eweg7Dx&lDwTnKj08j=qA~sl3MP3wTr3?^VXfM?EtM64<9ZwSG=wKzD?nTOH}E?>CyIG77Fb{ES*e86
x1eE6C5`h=CqJr5^#vXkyHG=l+&+*mDeJ_I+(Q?(NS1Hn81v)x^qLtBvb7msX`T8>)0_rY2kgqte>9AAu`B@vnVA6N_{n@*dju)7
yV?i%NQacJmV`f9yiZxn`3@jF|CfBWZ~Z>UB%-h>=J3$utb2uM+Hg%R56>u8#JK}pmg7U7U(^6r2IXo^PNxr~BNnF~5{(T6p<Y57
s6Sl#!_c+gWMSK*MW$W<wQ~n;L!HP-<kfLst-UMFSWo_B)WKg4um*&Bn7KYLCgi889?>ATz%Yx*?yf`acrd^O+XHovuYp>*w<$0G
p1*Z;C}I?WWB||i1)e_X9X6VkSj4S!@i4`zf5D=Os!C5@_9fs$5tZqEUa=IM2<7&)SFY1osxe0#U8blr<Fpt|u;Q{o=o%uE15dR?
IH(@gQ;fEG-Y-);#^Ozn?p00HNuTSoR9bB>4mxICF}GF|cEvV1qE+Li!AIN_WT!TY1I}91M4=|(tlzsS^UNmaoeoJRLH|RAxC#<1
c@OtlnoWZ=vX*(%2^2v@VK05DHB(`c|2O!aJ~C0=PhLoo7Eh=7oggBl_39Y&uPDf*&u-_PXIV3UN=?&C8%-YX0D0*OfMa@s5;!xu
!HP&Xmpg)M@r4r?!10LyiIjt65cj)^Lib<8-!Z8Lpz>Uu0aJM3C$Y3kd>URKsCvDjJR@J<Zc^>Ov}ap(iE^pwRWN?y3f2rv6G1n&
)6@Pvp%kyE5zI}1>&pIZNuGCQ-6GfdP7<F)n4?*@wOxv?&G?S^^wV<<+eY_xVDtl?+kYM>1*b+KI$^4nz@hB-EvSm;Pp1jo`jgmC
9i_IP!k%~av|XToJ>^k6+)_78`XILMoO3S#XNahS7#oPCW?`Y|NT>+Gy7M_9utHvh_vDvl88$ckIaM3lTpBq?{2{W+Yzj)S1aP^-
rDIqQG1zYA#a1g1_PPQAx!h&6jIOA94K>iI*kHVK{$vQ8wA1VY1UOi!Bw*f}E`j%54H4+eazW6F97Oi{_Yyl81J2OEzScEy3hnN6
Hmn~&m^t)q?VC9#S6{wf-y)4Irb8P_fB<mSIDG_kzg{`c;;BiaEEF!l%flo75&=gW0zVoX{cV|>9ttb|Q+{4-kC}Js31Tp(qXg^1
HN3CyjK$W1UZ#XEMyvC})P_?tbF0C6&5Sp_Qr*TvkZ`Q^*8?3q1(^P&R*V2BU|V&;sUNUm8Bj_x-&{uo-I;q9S1n6<!ZQyKH}$2p
-fxJ)o7h3q`1CH8^cP8o!$rV`!YQ<|Fd4uK-tQVNi0P%dpKV~UAA7p~iwYEbQH8`95OCm}MzVJ~lU1A{wq2EX@C1OKj)YJT`@vZy
a59ofUcxge1Fnk<`ZzYQ3qd%tB2;LNC6Awq22I0a%tm|lgpf3MV&7V>ZdZ>ueve0XZe%stPO{*e`C9V49&{nv7ONTA8KYsMPEAC8
S^gv6Wrb~ph~W|&e#blW3p{`<v}!g=QB4>+qjK`KGc;<taExfEN9c)ar&5A*G$t;d`gE1xtb0hQt%_P0iuIR6pGM0$qpFCb8%YFF
r`g5G)rrv1&*3-_@sq2mixXR*0s+ylfTWWEP@kx^?Dh*_)V^3QoAHW`0|-yn@w=`+8hVx{eamyc;yF*XU)N+Wj$o`|-l-V5_>ig*
?h1~BB9~>{&1!c@hVIceoEcJWO+x4OGv{Qg6FFeu-i}jECP;PU3ecz5K7cD)4MHZ=xiKwwdRzl+AS`q;4_w`en+ufCn1Ewo8iliG
5Ef3C7-<*N|C!K!C}jE;Lr=LsO@!s=brJZ<Dsz1J!*A^KB}4in)U>ZX(1Pfo_YJk|WNaJFSa~|Y_*Q~2RCG%gEp$EP^s{Ox2Zjdc
AN7n|?xtHEZbhD33C;Ga6f$d3A!|DrJjFn9c3_gD6kTT6AMyXV`e}MdGZs&MXkcY<`1UZ!o!UBAqv*<zc*8<YJmz<B%8GFRl)lAQ
V8tlshn&g%kG=gF7{z6yY!n*yPE{#|J>yMjl|*gmrGP{mM2Em>V*Mkd81w{ULM1w(zK^?jh(m*MN|#7u@$sP@Dfy;r7n8G-cd4m*
-bG_-2tS~PqK!CKZh5OD_Dg@!ojHq*4S2y2asSi`%*7BaF<r#Aj*c)ncStg2k?^6`(ArjykP?8HFA8N#whE?qk)OZcsQj@23Dl_=
Lt$cqyaG?LI9B=KVKscXTdF3xyPt|C&j(Dq)Nmq@JZ??3M2yxcqc5YV!&-RmgTA8N2cED%dr-?=#?O8JBT*eFI=5+@$j&-ih~j?k
iqLDL0Rvu%E4V`KdYGK9N{icTMh$+ic1dIGKH7yOP?rDe<{k}nN#*`$**xiPjYaSJ#d(2&62%W-J1%K1%DN{yQja08-mNYauU?w>
OCvMVP=wW?K7EL1O!TYtkj^rAJE+$+qnA6Spk&ZiqxDPkqjvz`4S$NBT_2gMh}0&m9r1i9+$0X=?Ip*Hr8>e0>uKmr2mXxXA`i0w
`01(~JqxDgBrc4+N9ccJAO8LNN#Iq8>Jl^GkzMYzou%iFv3<C*u2m|p?GI-0yRWAULLZk~dbS%gsKOU*a}u63+NOsVwDEGyt*<gh
)T_EhEX-)svN6+4CKx71kR+hw<<>b=f_IM;@Je6fbll^I<Yy)*%13NEH0d}#K0QTLENk>l(XDDMW+k{o9ldAFV+~=a+n3*44amWE
hjkT083PIPaM;z+#Qps=CBC+*bLVcGYL^XD$BYy9oaFa5uO@yk?j+O%{c>~IcqZlIaS^x<M5=ZQ_#v(X<0GcTX`h)c;-mR}AsZNs
*Fo?By{NR8s5bZ$1jNCRHy@NUV<-C5;4|8mcia+LFtqZ3H#oT=0;p$tUiFwm;TH>kS*21|I+tp4=QbPFgc1qQ5R;y2`9QI-NbG&y
R3=~;eVzrdGG!VbeC-Y6556^tQMlVHs-Bp`aKFVSlPKGM%BKT#VCVgAG0ko>Zu%uu(;s41A+$$T7HhZNwoZ=`4}*GbZv{(puFz?l
66E0d!X%Dsgg|*Nz9w(NL8&+XfoH4|bU;sbZE_YVB&7L|)>(X#zvGX*RL@$GrQV~9ewwsoS>SmCBzf-kuj&h~rMk>Uy9);LSF@*N
t~y}!@dvYx(mfkR<pKtD$13Wm(et8xhBAhKyS$(D+vr_+t+S!#;gWn@Vuc8xzv5@0h;2T@bEzt<W+BYfXfHX-E1)2qTky58Wuf<G
h>^p)u4Ij*tn<Bn*Hnu*OQw7U)MvlyZksY7+Oq9b&*FVjfSTM6KkwC^vUD)%=Wzt@gC}04)B0Pj7X)>xkh+ZPH$sMP*e8YacdHLE
80=ca&$DO~hd?ncgVh=*N{Nn1fYvBV3l#2TGG9(It;twTKYY>jbvTQ%!~cI_DJX2>ffn)2YNACt1K)EMz2@H4Yop5i)4Xofhl7-j
A$|5kL0=p-Y=<sH6Cm|aXj0T?qsJK2PZh+)V$-#{dp)cDk73fWi63~8izUU9;B1~(4k{<=rH=*M4kJ)GXy;DUL>6W`$mn{YO$Z^~
pVcJeQ;v8b`cD@s-+mZ@&{XV}IT4(>PK`xzEiNV&b~RLs)9^=#y&;vm-#uIFhINhfBfkq@d&tpQPQm{!4~2+9VqghgWpoR40U-7k
KrD4?yXPeSh=u{w(WAy{jbhv}6ts<;z1)9llxP^J)JoGA_eHd?P@QY~-FO&O=`~YRyaQ|dQ{#^#-V>A2Y@P#avM4{l`vn{{QYd^R
fd<jsMb!!UXNeKMlj&ow=B`zaS*JLDeb~CcRu6W-w>|fXGe5i{3O37wx4J1TkLdGe)@D_yr*El$GtiGODb74w)nkGM7R_1;3Vuf;
QSgE}?Q298D#vsqgZzL^i8;&!g^2N39>2Wq(n`PdO9140#34LClA0Ug*o$%Z(lVb$v^ZWUa;Ih-BqM5!`D8dhi90OCZ+!$L^R%<$
8mqDgPZDbcR$j1FcN9nP@8f5<rBm`}z`VJ3482mcrz!Y6DFT(jUpP#?$HJKy7cZ-L1PH10=%skER&z&S8p+>}^2=R8VEMN2QuFlX
TQtcd9J-_zJ%4<N<x<p1OJ5|Uk%L-6(-xnqMjl%sZ>##FR=f7y)?%~fe0$tIypRK2V>7J1%j&rUwSN%|#Kq|R45?TU*f1c@?K_?W
1TAamFZ{&QZm(Wk$8=x*H0Z%)%J-*#Ylffp0yN#FC|&NdwHlnKcV?>12C0_*sQl^m30;`{ViA#ev{Lw)PNWWFKdhv&LRiGMq)VHv
2&62XW)N%T3z3R__o&uvu4o?5SyFU=tKCxm0#71s;{;FPrveSIlKVtkN0@||ZOqV{h;q!~yhd7jvs&->5KDwf9n8V18ntHG*U(Ov
7KJdoR@_39%T$d$Uj8OGK{AgW;gWl_|8^L5e(E|mS=qmnF^Q}eDFYO+C>D=t>!TPjKz5hs=Jjz7qWFU>QTj_R`&Yi-Oq$3Oyc4)K
Lg?B9xRg|Oo*k(5L=#(zurK&I)*+rL&=3Z`jaRwKG}CZ+X)|oi#MJOg`zq=ky9Yt&P4SMa{mYvUwu;!>_glXUQHl<|L7j#GrJhQ*
30{J@B1i6^tiL2uYRRU`XHA64fb4E$t8ZTO4>@V3?JWE5<~qmf!Wws#kDz%h><?QD`NF72Wes$<K6^6nH&k3he%kEpGX$D{!Qidd
uOQ&DGrYXwB~lCn;6GX)NNlIGUoA84(U*|^P8!*Zx|96K`F3fBt2bfaiXI-UX|a=Zx-~6E0kSoPY)>lo?xX?PH88qZ?1dEwBE>f@
ljs@J(EYx<5j=3$*4d?Mq05LP7A;2%J3;M}VgW2pK#I{A7d9ZVV)4}lw9kIti$<b>ZdX=^nufHRtYvKjD4T0Z#Z|_W#<(L`HuZ)?
7b$qZ`J#>I&oN4D@Z!Jwh<lefRaZz6w3YcMvvb|6k@1@2J?+^```98KAV_k4@j$bG&@v)eFGiA(#$)8_a2T3tdVVoERIvNIMvT?T
X%E=eS+Q@u1mNHz=-Iub4{j9?J17q#;oizzhpMloEe1W!b9SXFj-hA-_l8rWEIx}cT#BF}qQe8B!+;05XwW**{V=HT>^LK{IJtvE
qc}r6g?q7R4k%M<<sZ5lbAX_6%Iy#dc6+4yU6gWJc^o+HJY*A3Qx5e)hf0XsNGM#7Nx4eJLPHReCy28#Mk)#4;>kqQUxe-(+k}X%
fK6Kp@`(6M*@kCJ&BLkI0$+?zT!Ebfy7zK3MWJeDG0MKOaAq&c?ijjuu0)?&eq07`)3?;by85Z97`XFmMs)W}Ucc-98ow$cgW}MQ
J7m1BKB1D!SxFCY8tdmje7|eGex1WQ<7@^Mp>I`&;VI%txa(HqMSoFQ33K#z{Zdto+$ns5OvZ;_xuX<xdRkio3eDM6BwsqToN$I@
T@S6$1kU=l)FVm4g#>47Bt4sv?Ef}TMfk%Ftn8<5YHno?!@Fja+Hs5@=n-n*WDzbU%T2!*Z58iFa&qNwz}2eqmfvJ>v*4fMInHLS
2a_7%z#KrOTIBaK4?+3%=4sSY3lv+5NjdUX&629hYf<6%wf@wmV48lk&rKoK(tFLos!<P-iNOCfQn&*5nM>e%(GWjQ^zlC2ZsFn;
E9)TOJ^~F}yN{?W-0euT@NurOM^O={eumZAeu`Ypbg)PjY9)wGB>mm?ecVb~t^$rRq&p1s%CuS5hGPe@DCQyLTa`xwd5V@}F{V(K
w->*O=MQlE|8>geczPvzSWb*5*f(FDj(1Rs7Ri4dF9D6gB)bGqNIj+3i-@t05?&17y0J8j*mMFC?9kW4A%!`h?*ZIWL3C#5icIr<
!f%HNK#6^OP36T5`ed)Ty=ZlCE)NISS=Gx8&#`O+Kn6!Z@)YArhHgESu1ELFb_UwprkN(~6<OGucj(1Ql;5O&+NaLcZXu5T=EP)n
cf%bCTLCojb0->))FkI62rC*Z4dzvJaO0^fY|1rD{dg?VH27<!DyB;{XQcU#ExpYze|GfYa{56`o~(PJ^f^2PTt#(!+N!H#dO*Qz
Z*6ma*#?kc<ueOhci*n%-GcCBK4eB_^t%sEZsz;@iXdB&erY!UjeP}0$pxNegDbVVpYft!$kWc@`i=dFGT#u0hqUAm>asW@V${uc
;UQ(1k>4pO;xm>h&?7TO`g;eU_BVkIc2O7v-SS0X(KdK@I0Vwb86BAmEq4tHa(^X+DDz5Fz=(<gpHS<K<bqJdG<M`~I`jLued`wi
B`W8n7i|LY2#ssYLTRI?&2Qf7XBN1eI<~78oOsiJh7yK7A-J+!#eoF=(gChmO&f7T*gY|U&|KQwA_!q+;tyh{YITgt=P3$}9O0Wa
hY0q@z(iyt_Q{nw_W#gYcR(SJ#Y7=imt@HhPMRu^&mp5B5&pbrQu{`3Ic0zCw^)$7cQOuZQ!C*XRCK=6l=^24-Tks7p0^dDX8BHQ
wFmxQ^Sco%<dT)I$pAY{ed>2H#I!PB7u>qyf#)4tCu{Wr8P*4v7IDr4Gm0`laius(bZC9`Q;6uZ)Puqf7DWuz94Z?=WCq~I7Rvrm
=-oMK^0-N&0(~2_)=hpAY~5@T<Yy);q<-=eXQY_6B`S?(r~9_zPA#W84Q9jD;;uBHW~g({LH7wVP6x}1@F87@$@{Z+!n2FqQcjxb
HSO#aAy6XxR7+P0+`aa&U;M;?!HOX9?o!Oe$`tij7YOeUuA|IEzTKC4JapOFFuFlcSdS_^vVSG$05D*I8ckf%INmRtdpaAl*NUM9
!vMMndAsn+F2`_Uy6x4NY4mr=O~&<&t7*S}z_;4?^G_(oWwO>Mt9v!kkjCD4qV#g+sgxpXAy?Hltb3dWPra)@_0y{-K|F>S<hslQ
Rre&>8-0vVN2!e5<^02=>5KoYjg<)_!3zGl6k8V{0fku-yYw!Ui!Zm3g}tL5pMYYg2X+W{NzO?91Y}dymhBDJi7uDaE&F7p^h(xv
AhNLPU18vdUgoq^FYfrLOX8wS%e`qg&_2;JX%VFe6T|E@qI+N-gEIs>9_vEEHBvO{sXwui!HsO6WLaj^;c3vrZ3C;Bhka>jbt2TV
s(8*N>-GKAOQwY4^T>3m@Ddp6YePcneYGYj5-U>`SqUPUkt<hfiWX`~?EHU%y)`}8K!-cGw-OMBLfR}gT&ZkY@G!{gx1$U1&F~FW
u|{@3)`Ss^d+(3#gupz98T+UlO<vPxl>W#I0m;XSZa@A^XdMtXe<&;Mh>NvC6)TF#zZP{}?yT0CUbT*Z@GRtiq>K}#M3q@5UPKNC
Xm}T4*WJ&G3FtZ1mQxi*#)fO$7vM$qd1znQx4w72jcQ&BjF|2#x7Ks5TbjZsmFm&f_<|{E7Zp$3)$|O;rVJF;$!7C*Q!bJ@v>Qtw
{?PRBrPPLM7R<!U@1l84JwaT7O@7zM89v$a$_<}THICmQ>D7O+>_!K%^|W3D5ssKz_b*M~v$P(gD%I%d^jjB@;4>7Iv!>9Y!z0pO
E^3b;$qjwnSP{&~we~0T(6Vzd{cL&X3&C{%=+O9+1?D}85-bu1!nj_?_Mgpg<>$RluW-;4?AzKKSo%OekCrb2+V8eIDuSAYBpVgW
W$<_UEjMarcot=NK11GJEiAtm!Z}zca|mqDNsBzIdWVaUxBu?2)w5@dq0te%iEiQ?BO8}woqpnp>sgP7n*eLZfL8`*6oQ_RTdGq@
kf@S&FR1Mn<2-N)sE$aW4bFIato7`Jcv*iAiHGi(Un<sY*5$Px$CwO8IV{EpWf+ga((f|nSnC`<*vebry$2*E-ko((<tl*d<*4%D
He#y?*ZP)>V=|L|#ylPVv-KuPC&{bX<UgYM!G)&RQp}@KmUD*zF`>R-xk5mHb{q7_0V9C^k8^etQ^i5MG^%TClPZ0+QD+55`JicD
#%b*HKTfUU+t2jLMZ0|dZH}Mv^J`?Q_^YfwS-Kyp6;M}#e7OQ@4dZ`KtG=K*{qi24m^$L?b+9#y(OVs+dUf*fq2mCBQ|}D5SsY_l
YCN*03O!VP=a!Blmw!R8tAqO#YjWs*Oosw3(#-RWL+Tc#KVry8QCZ$Q|B5wen7o}|N+>cI$X-8S49u98-B>oj08Y6TnmIKq275u)
5(&9ubCg690k26g*3}KRSGC2FFj&zUB&U4(7YG`@bA(Cmffp5V-C*H<cw*((`@z;2N_)T--3i_7-R&{%UlJ(-?>a@;f!h|&{uXhS
sOMP1?=Tfq5OASgO*Wi4!*E~=CT~EB*rtdg?7T3vI!Pf2zfm;rh3f+<#N55xRTyR+8pEb)Om>d`^7T!xWc}$G-feRN@^q*|ddiN1
LEqS|GZ$VS4P!smv!6{nUPzpvO>GSvYWcp|Tb^;u>!j{SBS6y09osh!z`wiS*V37!S5(`!DM6G}ZvW|c#(pkVDTA%NwwiY+oMLmi
7=;x74|C8N;4F2%`90%cs}Vz2&K`3{Fx{(r0C4<-&y`58s!CRzG;MzG@AfMK#D=l-6U^-9pU6{8NFYBts2zjJVoxmLxv={Uj+kMS
i}+6bSf}P1ft76}M2C#So-8<s^6zD$RbzL)E6u?OnzWgPiE3TF!w~8Rwte6_s<<GC9$;=eDGnRR!aJBRsrU+=PPNIxQNaz?9z$8I
c6HYroHYH?lkx3TCRGxsqDV`;%5LsQs`E?I7@*A4o;rg4#-MEIMogNZuHVVHw6^4C^e{+7N~gKS4W`N2USu<rHdL!hr+=8Tu?nLZ
S3qwswMO_OJD@F9)&yE=6rkQ;29UAK$&GM0xNWnOqss>hm0HZ%>FHk+zP??el5Yq8_c58K2}YU@oIHB@rnCc1GkdtV?DK4JtADpp
VM0RPOJT#_K#DB%)R<%XtX0VwAWW=*6*)?$2g;vYecF9Irbv)*@Cf5?S%OPRhMpx}+S7rR!s0GI3KBU+;H<x$(eStR9XoC;VV}`f
Y#g^}0n3c*14yIh)2ou@PcZx8nA-N!?LUF=q7yok-jgB`(`$#KI?pN@O+K6?LXy@Gf7|K0CqFs*%8^5aqNWWf+LHGe?)Szy$GyHE
qUhl=H$Ev{#{muTs0t&adDfsG3GQ=jC4{W2Uu`nopQxkIYu6;2>M77eX;6yxFi!6(kdwGUz|O}_3^uZnAf?13OzV-xf9-|29%~A)
HtzqAl}3v%GU3|5VpjcWbm&bQ<Am$XO!89c2*L?1WPBg5fiQpo&RsDqeGRgu;$}em@<va?b>R(&EjPTGf{(o_nQR2C-YZy*LROOw
+0DNuLbNDWX103g-4IjP2fzv3&;gw@+i*2>;BLWs<`mb`YH0*6G5HfT4#P5Q#}C)lH*+fU6_?2<*zSTNobPN?!HBYl0<Q4An(WJe
XEJsyX_idwebqBlZZOfiXDY9`TLir6X5Qn(!v>})j(-Bb`_~jAe8flE9`pVRpI`j5F#Wbi9U)r5j(o+nkjk^Oa}fc<@6SU1Uor!x
-NE^q$y;<+rw&nRL<J4${Wx-^No=tE)m<;-HC>}INextW>^tXw4k1RCtAr>Ub{91U<O6xF=KrhhB`}FIw)Li~0g7OE5ZbfW)j38O
{7Nt=Lbca%_1DSnf~SCq%N%rtzd**U2j?ckU}kgW9f+MrYaEf(q{*ew`hzM#9<cGU9cZnp=aT8vN0E{QLDK8|j06tK6~Wj&*pT|{
eMbva;bQnqBFk75Lzg1~c&PA0=gPHSEe8~djxN8ueLlB@SH)`OcKe<4s|CpnG`AM)YXiU_`70=+OC`kt$w29$>iPcAMPb0z{^iME
{sUh&YB%V;>=(Q!-l$gqdevD8x;J#dYN@?`Gdcp`$_}zB3v4uIUa?=E+k4gQK3g%No+t(;ADtJ9)K95o2P1yhG1e=QJ|>YO{d2O4
RI&`6DP59~OVjzvn1j``LhvkXDkca?gv}cA>QgKPrn=tak`3Gvnmd9uj$<<lEI#kw{9{9B0pewcicZUIwPGO;@jMFyv~gJI9`eB)
#}AP)iIlL|pPdvW8**KY4#aG3U^42E3s2Kp1JPqrI{-%X=Jr{ldNH@DJkoO}XAeg>{%2o%Z`R?MieUf7_*{vIQ$Tg)p23o->B36q
Jv#V}v%Q2N(6R0bQ3$c02Caxqd%p<;&>V{?wa5=aM#}U+1s~wIM|MIW%qJ>3VYS40j><F@vnrHEP!6fe(_WT=QZVvTXxjvUT<fYF
o()nO(XDQKSuEm4&G!@sI}}#j*4uwi0KATd1q5IcR)YFsQpW@fI+sRhookCMFm3Q>niL*OtSZ+vuvBZq=`gL=wnJo73y7%K&2<7o
CQ!!8(77MTd5{{k<F;moHEd{GNrK@=^I%`bx2nN>9&FB$S5&QRpo8gB3U<Z3eE&FFB~*0hvOhH2#I-{KFZ++^i7IHEo5lZ9h}44-
@Sxs2UJgb;R6EBAxQc(uX~okEqT{yuKOj_5N{@nptjwfYmFC{zvO+}1s(E6w*-Qo#pOg?mELQQ>No+U{oKKM`xvSf%34^oH2CLou
)5i%b<wklHC6@8Z@}m#za31}$>aI%U0ErSc3##rYc35QQ9_*xyG=Qlxc1yi73XTT9sIdZ9C3yoFK_iB&Yc?~ko2N^a7EJVaZri@k
<a1(<2K}tXh2p`fJHwtn`s;yz6_(U2%x8D{PyI2S-)!Emh9sVAuDMH_?WfO&4IoGjmk5&q)e{3(Uh?hCtBI?2a72bOd+GQHv^Ch^
Z8=_Ulj!X$UzXk7aWm^<XNmG^Avf0ebGpp>i~Mo3rNpqMIyjFqf7cR)9`xRSe;R--)yO5z>&|q8<|1l61pn~HgmR^*G!d7v%>7f2
mC{zpUe)*`W$nM*e(g@G(s07vO*`dFU{g=RAgU%APh>X_=}}XQ9`_TZ?>(JGe?_iPX6rM{gRBK1dTH@4k=O;;7~%*@U6FiVL@PMM
9nSr!ouQ6q9uxa^a6Gwjn~R_L40c(bg^yYaPsIma3OPmdo81Q9FfSU5A!=#STm~4~m{T$KSD_c9<;6@sAETmN_(U<jRf|CRS$lSV
1WNi&HiaPoP=jx^nbXY6__WVuQd<y^x7e7$Q;CmuR1k+l-Z%rte-s|7MNX=kCGOkPaSck9Bg7nWau2O;b*2Ncs)KaF@9Rwx{<{oF
6un@5w+vb=9J3JiNC+@dVa_LnRwaLd(+)W(AT<pwLps)1?lhY-i@rM|Z;Ne%pZEH7zJ$u?MjxVKPV@e^fx|;0yy&{J4{>Td3)UkQ
B7>GG7=GG$bJbrluZTvab#Yx4MMpBM`+zg8pDf-{cdD@OCZ8vP1TTbacS6Ign$)YmJnr~c`-o!4@rJSg{gu($(e%3+m)WwV0_EpW
ciCD7{KQ{|PAaZ;L5FNpqpg5;{2%N#z8r`Wtf6GwUwC3P!t(PK4btxVYbcMkW^dISq$MY;w7tyN-cUOjFS_2JV^P4^993#=wcWF>
!!|Gil_2I=B#DNm+S!@&iwF6VgEL}CBA>0}IJ-?ZXPAS>sHF9?{u(Li^X9M%o3ILM&|pb{I`{0N!dl-b2r1+Ni8;&n7zm~FWGOX$
9*;;F6WeTV;-Mq;vr$!1niF<kkMLYMuSp^HXV8V*sm?fE|EG6X7TegJd?TRVtyL8YJ5I4v0Eef1@3qeN_3WDugIVg?Xn_jGXDJ_B
_nB(Qx-Wr8%UOp+5K#!mZ<Rxe-i?WDLWtsiC5&#-8_uzn_2n!@Fc}8-LAW&|qM8|+GnPGgD0!VD?HHKJLb%^rTkka^{=?WX_u)AL
_Uk1Ifos>(8ha1s3D-A|WTS&hg;DkRgTQb81ob#Ff_CThbn00k_oOIQk6iiA<S?g~%mHEhSwVgqK_-o&;+>8Tzde#RUm2aSKYQB*
Y6)RbxKj|`0i{n%_l=-G87jkPLyRWs0+-&{8n^O0(El7@WBfd5zvyhkr|e^nEnn_^F$0F{h2z^H7Qu^se5{;~Wjq#fzUJRiz@ce}
zW10bUpTc7mLPa_A5IIJ#bwU7J!1-`X8`LdYe)39v*^=(6hN&GwyWq`o3F_h)$lctMV^nrl6(BK*GQ!Y3rO=$r@`&NHrBi_7Dkx*
<3ltw*C52PZHiZa!Dpr(8n*CooChW<2}@{HMj8vSVHfra1S|^44w#N6+zkqVN1`f1SiD~MMlRwAd>Ma5uUeqv6Fd(cy3tp1x42nH
un&$xB2t*&CH!Ortzz6_h7d#5JL5)#0LC7v9+uVLXT6CFK5{IOMVAJ{LB3Jz`nI`9P%y0(Bu;{3hn+x1G^((f(Su@6V!OYeyaszG
*O5~4U1#Ritg93Vb0Uy5?vERbd=c6ZvGHARmA{~o&l#_Al2LZCZJ<shg4TYI`<6dvouE0M2+A`oXn6^jAoR-){-mc^a@$}Bi~-}O
4-s2SI^>FP90^TzkPjHFhMfQ`Tk@+prEKfBlqyGPCvdQa>NIb#**xDo>Yw*iUL0W|RO<t^$4jSc^Bx@brNVH1{LB)~?W%(mFeG>b
)`fi(!tz;A;ri5L!yH`5FP>M)ru48;)+g7QTr1!d8zU61UdNANT(W1}pGJW!-&Lls<uHw1@<&-iv-9@T2oVBCFJK-~nG^vXoA`De
R;*XU5U(-4*Vd7l@Q4okXGT|T*z^#`IYxJ4A`2aPmU}xfshP242{^LKZ^qZ@cop8o;vAMwh&4mhMQdnhRZnt>@_e2Tc5CzeL5uUt
BZ!Qq8v|>ZHgm5R`qo#F3625O656zAxfIgz89?gjmbj{e_l7s2(atPbq<nPyic5N74u;{#@X->9X&vzP5+88l_nR9bL$}HU-e*hw
(!5b7(deJd=+-69L~3Fjwa|;h*qgohvgu{7)5G{VjeX1NBMNd0`Y+R_&r!EI^hi1J*QjQkMSJtp@I|JA4@T3DUk;zNMSQ%bF<+;2
FJ`cb99e|#WrIsG`w*7qC5>s^u-*Xo^&R(<{?`mWv2hkok(QmJ1B&%-?jqKMzQjhM{ij@Vf5ZR)00000cPgI2+H{o=00FsufR+IO
Ch-pPvBYQl0ssI200dcD
""",
"""
{Wp48S^xk9=GL@E0stWa8~^|S5YJf5;9~z#vRwcKYJ3oxP=H@w#Z_m5Krt9x(0g)6-C?+0DwEH>{!eFV51lu%zpCEFXpRAIcc%>l
Uxn(&3BpXT&p7cLZ!$E}Ng*t>{`Y6rOPbyY+?mm+VQWY7LhXBCG{5+SRUMj<&jXQ0hN6`etuHfB4DAGCh5HVT8|*CdR23uDR_hu{
^&BbcfTur_{isCMWL}SNKktwN+-nKnKaQ^@#$xyA;4boyEGbTM{Efa;qD??AYBg<4Vat9RTgnVC9TGhJJ;+xd_P8A|@#%N*p_Xm@
-}vW3CG7he%CQ$EfkN~<Gy~aq1&{KNdJoEs>B>|V<zGO4TuEl)*zH>VVTO;4+oWJ1a;Fj-593&Z?EtC+`-Ls=5?J>3x6yeIg86%4
ClmQ=JLVM918NH^aUn!ThXb`9_j|U4>+c-i$2%=d8N-_zb}6A>(hZ4b$GmZ`1U$`!X$n?A{l)J4706M0Ax4WC8aoz|L-<c?)UP~L
H}S63&JaXod^su$MOOM;IVM0c-U2#LZTg)UL?wZKJ6vW@g6}`@tBiM~_{5D|o7Tb<=Z^|QSJV$$V<`;L^QF@Y40-?T?C;mP7#l>*
J*8^<t-PWuEgMielHB1Z@wJHz%~76ul?t1@Pp~}4Io|!f^8&&65kOUJiWq7f5?7Dg<*2{UI#N7g>j=7yL#Q#4RfwsUl?QZl+UcRy
>fn19_sLEW34h&?%quTqk@f!jFIVsHf(tS~1-i{Rt5#;Sp&(_xKr&Rx%2g_lnS_8PkXLYleCl`7k^L=|h#9x4eR`ID61X~>g=14k
WPCJf7B3%64jg>sbij*XyD5K0fZg_D)bbLj97fWkC8DYQy$RP0)cvtgaj0nhe9!gVB5yND0!dg@bml$2*Ly<zA2)0V-x!Nipg~Vu
^?;5iVPYeeFyxaSqs!ph0T^a?^+=D}+k7hxCPo@7N7%Gh=$GmG9G$I`<8*i2JstL#b?Q!-x#ml$4-lE^TVhdyAbw8WKz-{&ft{po
diQ3V*b>TsV2Pr;b!cTxZ5U+XnK2+;ghW`fX4S_)#XJlIkSd7kKbwJO`^5#snBzUz?M@qCl0lfTudY)|p6s@AQTy3;kepcAa#BVR
1I(&!dF79ID{`1XKf9GCZ}r{2yi`zjYQ_Vw{a1k1;QnMWOug$L5cr@!yq*ZN3tD9!*k|#?Znf|v)yx^ElT1#plL=#l%~a~4@mAUN
BE1rUM`W^5D%Z&ypu8i1ut<FEX3bPbQo1Umty8xO#!>2~I+cp`${)2a0+qR#M$bDWrkxr{5-gO3lIQ}b_2LAR%(o*7zlg?k0)ytu
D`OQ`?AxS?c*MLC0UlUbPJ0<|(k`8b+PDqBun}P{CMT4H4$cb@>swi4lIY791M#s=Lx^BuTu&HdV-3@UIFttb*sMSkND)p2`k!nk
YlFIb(zk+swH`&fOCBg=+d$C4(In{*J@+Kh?L|XBIK)F5%q*}+EHZ~W=>)*RU7>IALn45FX#=kvo^QQfnfeS4YmI}NowyR{<RGCI
%KuuoqNvQ`)J2wFke`A7l@tpr=^E2w&lxkec6GGPw7-=N>*uqPm>W9PF@35nkAZNPJ!3_{l2<BytwJ_~y|d|^vyEvDz30@zl*N}E
Cv};>#)0RD`~;Az@c4aYL566m@#skzMFX$g6!2KAsBb)o5aRcdKSdNK^%_(Z92o%2xNdPKDo)*O8?K}aFIUDnbmA$vgOp4sE5<sO
+qg-~1^cUPG7vYHH(mIgu^_B%SdQ&s7-?Ejy~Ymu$Dgd7d073|G+PX*Vag%ux!pVm2<gs7<t*r%-i?Azh8d`bn>OHFhUWj{@%eK%
vBxc()!Y&FN4NC$to%gDKPZsVVK`C?r2oV#-BZzDKpXyv#lHLK;hbrow!H76QL}BSRs=&|LY(HX8tQ6BK{H->2e<lFM7F;uus&%3
Ni$Y65Tz4IA8I*31Xdl-!xfyKSMy5J7^2}FJFp#l+q6yM+}$l}ulv<PL??CYuDf0*bNnGX(fv`$Z09kbPldj`%DnWMnktv+<zWjH
Og$3^(F{?J89PFX<E*-x$9l%yD%mI^w*JD-GrzuzHM1Z(-0LznN>vZ3WQ!iE(buBPFKqL23T=a_MW27^>>2mpUJp~PVcNiI+!b1V
N+wHqH<*K=;)V^QFj`U_?I9iRk*rOoxC3=RKMFWmQ&CeF{q&X|LV^5)?pdFEB`G@S9KrhH(n}umEX`YiH2AsCIkGUcTp+_dY&_e>
bflCq%+xU_7@HEr>Q|tk&rm4KNKih~VbvETI7eOtEILCv#s@o;NRAL<9n(@iL(2Ymxg(1Q{+V&auOt%xV~eK+|6t^7>7Xd;!yj)3
R3tG*wKF2H!a0H=&_+t*;2b_Z-r<EXM1Z~`BxkhayM<BwE{PHE0HNo5qpcg&zfn296@&Q+&NV9ECsOK~6F<P&s(iU8`fmJ}wSs<q
o=1ZWswk8o*E(Dua#xe5v|eecy=pq@>ge~hq?0B<xSRnE2$4(AEf~Se%j~>(%f+L&#;mM%U&yPBJr#opGgb>8nrPdfLK>ifuB6$!
Z%bn;$^QkJLK}sJ*#sHmn?M`EIPW|#3zF0g4p(JPf&euG2KGk5q{A@dOAcJknNcu~*Sx3v`g(Vul2R--NNUKPTA<;Fm#Ef32c56{
UI>O`ME<wAA-qs^=@dNh+|<?3XgI}k7Q0Q_zS9d}P2Bbpn>lOr;=Ca>@8{038(S=jUo!iF#fP=<4%ftbo%`AR4Il)!9~X;fCXvQh
%pb%lBWYS3pXhR%ZJw5L3#q4+UF~zdp-CSfg5nA6YM5Gw+eRH{=5N@X<`!);$a#jh!NT0Pb(_+#E!8EcS0!7<Q)d8%M0suKpKJv~
bnyiXDb&+gZPA!LqmH?4%hUP3a`Qi-rlJne^Q)a?n+BPx0svhNzdTAS`>yk@0=~!J4H51*3Z(8=>d(m&1pFj+Bxk#no>TfojxTOB
(WvL~Is`~{;Un+mr`0}$?fpS1Ot;|9rZlm1v#F1{utKr(0$g-0JzAunMGo4l5kM@7?zBAx{DZL-fi=`8=>OA7r;kHg_mw-9>6%pB
%BkYcJXfb%eU6!}iJpCC#xfkdDFAf>ht7Z@hX0!W|DLBD+PlDp5Co(fShc?_`EKE=GI87m{F)78@~{K66gtX$Bx(ioYzfURwz#s3
E)>tgli2>hRDv?obMTzo<(HpG>yolgF{23D$(Z;`t`llHhZ_a~Wlb>~&*X_&Bj?d+17vHy5>Wr#BU`Sv)bz|?7RvB*Xx4Hy4&i#r
h&{nngc0%#O<GfguEaT^6ptlAHj`A>pP8KDs~5WNh6^pI_3l6!7FG|V-P9ooB4uWjeCL>^oizlc7?W3EIYy_N@9?p7dzK^F^cfon
Zm0I*qtX4@uI2}tW4ryj%QYPiFTKATe;@BLaT!gpGN>Ohz_w<+*8xuB<ai8J6gu4{_fP{Zg<J8nZ`3U7uC0RWHztq#<Yc~$goLj_
X$<(`k)YF1-vzSjn1iN)7iG-N0qiab0aFYS?H-^|q`5t)`4+|u1mRxwFGL!B2-I0)!&=T-=_{d-y9J8+(X9^MuZRR>+dVm}mOo;?
P*Z~pU=GQRUP;7#q%`s0kv8NhxnPKO2Ct!2A4R)luc!D@H;vD&`#TM8|D4Sw6uKS3?6mq{`8%dq+T%h$0Y+*ySJcIVkIFGT`hJ<V
8nUZnd5_VzkQ*m=$jV)i)q0akMYg-{r|RuimAO>dS!x|B={pA*+amQgw1I7z+W9zcwSN3#(t?%?Z=yPj>EOcnSEHK}Rls`?vUEkO
g7^MP;roAR&K`$@9WDa8z2F_0if}kBkVB7b_r5Q2SnGGJRdz&FdlI1^&gLU9S$BP~L+P^ITN-FljvvVRo4yOr{9Z4-O|4PRXkR%&
dDNXJPn|i|leoF~ZvgfbNTXpW1&=Lb!}B}n^M_`FDN;FGj>jU4oxeJyJukd24k#^f6T#mpIlz;iJwE-ZQAev(ty)8|rmjt%a6^MY
w5aqeEh<o%6=}VCMy$b$N3eT;H@Fh-Y1A=@MWIf&X&=TqRTV;_V5d-%k`T=0%MP7F)sox%M~|{<g6z(LNb_u$jW`o1mQPzjHfzky
7tT!pP-tf4qI^dtwFBWg_QwoxLH;r<l!@g>_5u<tPd596S^}38r2_AK^`&dFCDii*R*Wg8WObyR>0LNI!(RH*-L>rOV{3RRovBxW
C&i~{OuVEz-}SSiJLS4ITP>4K*u>2?@Hqjol($i^p+A`+zCiP+&Xe?Z#3yR=R7;BKTuR8TZN&RQcQ3dJbO7&R2p-U3gGJ3wtU>Ab
vlERX&X35rI0F1}gf+?dQ?Aq(hi7GAfK``KX`XEvF!ygUX{*%7L58lg<)o!q;}A6A?5raRc7%aDLg=4jZyUX-WDG<(oh9s-BV%%g
VG?|X9$4`0Cucu*Zl{CRWDKWr#z5e&F@Rd4f&235H34QhB0~ngf4iSEtEIOiWosc8fp7=Z1+{u_R|t4(?CiRKbX&+6ZU|&}$&rDK
1TIUeDr;SfXi)H{5;J2HnKHeBKq20AO-QbDCv*nP)tsw3M1V3}__cRYNxmVyN}9NFt)sLr8!Si+{R#qiS1S*j{7-(yoiVtFKb8g&
+U9}J*jnQVlNxrI!8ab}^>-oVtkAf9ggecX=s~4gk+_gj=5Vr0S<HuMvmAUM1-vfn3UMX?Kh4zVmX=K@=M_T|zMMO%)RhxZW^A|c
_g`s!!{U)}G%=}2r2>40S<*epkC_Hyh3{95+C*DoPw8+g`-`!&kD+9I@pX{$N+C``^;jVClTp54(6ox*nulqoQH+(?_@WYSOoA7)
Uk1=_2S9e{dHYnvMTRe$6c$N3su``yJ~;`h@j?-^z58srzOU7VGO8X5JGf7|m|GYi9X;@xbYYlA&-Nj^U$!V-UWIYmc_0x{n9$u4
dL#k3BDZpCZ6SssXt%6;PcO<Mu#`m)(|icz4gdF%=9ALa`c-LXhueKP<9?mgtUcGwb!v7dzgYZub02(X;cq|0GbzFY$O@_RK+Hb@
J8BFBX8~{6B!jwU_c0+Qm<c<xDifIyOAj$n`;9!@MjY~e?!l<2Q9^uesq=H8(5Iv$LGp0))F=FRSxk{~>ZUeKDOFPfq#9~lJ@#iO
MNjqNJQTL}Ku7BxYS!w1bx=e{ey+0d$WW5%d84S@l8U1M^y|ZM$X&fi27AnHx(v`BODX|upuh1v^uFT2U5f}|T48ibpfU&>_P|vu
5qSH!cS&%rBx<2a$IEqHK{CxTj+|e)$}d|vc5^8E=h@2IT<3+)!CrO1s(pVsIYAqn&?|R$S3vWzQ#1L|DDq`gw-nEqVdNtSnGZ~)
R_;o&MkIe`_H8o~M#6e>0{Dj1jSb{H6VmC0-ULeg{XEaj$x|X>c55|K<7wzaSlee7<ESk~aXCCGJk?BB9ygS{q!`-|uAl^fm<!UE
TVkg0+h={T*}_55>u}9>TZXwkeI-+x07l4G)Oc$pX8_AhBQ*+Oi866xd=jic=e}<i%9}1O*V0*x@ZTl?ZCEL5(8>o5Lh9vIe1~d4
AI6ZQNM_ct{AmTo+x{tRNdY%gH^U$HsQ9|#4XTa@@{-s&Fo^!=*nXn+(J4VFO6H)|IC>YoM*{Y6vYRAtXOT`ai=wNFrR|G<`>Jf>
g^TG15u~XT<JhM>eCGO7loKxPl?^S#4Nw7UL!wb%BJ-oi7juyZz!Q@CZ)K?`u}aSccnF=K>l5&6S)9kuDKgO!lXR#b7{*VuFj!Jn
^<VcPJgULzahNtAahwNT9dz-STdrPW3P0LLQUb0h|Es=kH#J_%<2cgPO7$O?P(ng$4v%v?%ty@hc?_*Dkou`>B0ttJ>PlokW!MJ9
=Q<G?08ha<THia=$$>i)dco8->PQvGK))K~7}!?;E&f7Z;<vn)iwOa<FMhF9L&GyL0_&A=tv)Bh13%Qsuz~9K3}g5gLtc;y96b<)
vk8TfMm?L&W{&+lJa<2D1*K;}+C7Ok{1$vT|BC>9ajDahpT+NlV^fv>shS=q3zlcS*C(E+5GvYg(rZu{lq|U@GFP>}C^~u)Co=L6
p^w(HY?VZZIq%TGKeZuug#)dkqhjIuq!P7)8q{=KBJB0%jVUAt0MYDdiW65$O46M)j^>_*w!Om7d-Er|Dn5)%AwhD}4$zT-`(rDL
AqTI&hKhkc(3_=lQ3(hlXu}pTgKY(~lIE9<v2BHy>GfvripKE01Wp6n4HS$lO}&X73oUQ#o}J<vt=_@eh&i)Em!vN55eAOGm%q;V
uh8~U3pXbP!{<<K$YyCnSllzXQz{C?LEf8m5rtYI=QtS4gJO=#$3EJ&Uq1>^9B78qBJ&Ft87ycF#;LLGT5Pjpy=iDt%QL=1(eC=-
N@j4dL7Cu|odkVn6b(o`Tahf0SKVf7t``oi>=y;cpMZ0kNNuWpB%Qk_67+l-HpJ$k$0NqourwWi9bwN8fk#UF5>%b647}+`m)uS+
>wL9);lHJ(p__Ua?TG?Fx`Umz-dbzQh<a~0Jcr#+Sa=Q%=H<yFQ+Z!{(;%bYfx~vy0m{F|usTfM*P`(7Z7Jfk6bP{4FPNB=PF}lr
<F`jMqn^hD19-9;ez40B#co=+oc-fnHeL1bHjTnNJdLBM&4z5Tfzh}gv@P_aPyvhG7YRv_4>o{#L&l+f0k=sjRZ%$&b|>?<R|kaB
#0n{r7H@c@;t5paxX^H<%F_TSuxReK)?{hj87uxNTCf)QrWP&Wp!Z7S(-`;9dIYr4HVyAEoxI?pC&BA&+m{JWa>or<*hbC(LPAbs
J{9I%<GbK>N{ISL!xLSJ*EwxF4v5r%I$C*i8wljKE~*7=D$F_ozz>2VZ*A#U@4Trm<31t7w#irh7<%yFrnb2B*(*kCL0XkQqzyi`
7tvh*kKOW(Th4aZkJknir4tEiR9)@YunhqW2?an7%_-6ev?}XxiE&>vrXW~qPGzmH+i<qubHq%w3VD0seD1+H3jhI<=?;i(su^b_
)nR2eO;GVU@;}Sj4hr)}N%UX<YpGg`lQz2<%@CVXkol!yRd%6yWKY1;pyu9Hy19~VVL#sC;bcHJNd=VQBrg7|QF>`FFzvm6ul4AX
2wn^;a$DYpMioee%nkzBMz{`;m<7?je4ZmG!0mlyG&DSinOE4lk(B|Qe-ix)-sNx5vk<CW#aTD}<Jfp5Z~CIy+pdEoE#I735M)5g
Akn)QfKY#U<eR7Xmb{?ANaNKN>$2>s_@45Lnolp+aE202+i2H4Rv}m|d3e@h`VelJ7+VCaJpU`#l*;p8x!a%aPMurjmUS6Q#S1w~
uyw7x>_MRLaKqZ>EUcc3UFda9*orp&m>^aL`SA0E-I^lP<g1q`vFJ-o$p~z69pOxpSVn#+k&(`IUw%gAqU1;r)dF+9qf#^gjWr0U
!DS3~Xm_v}xiaHivsPJa53`W?K_lhc$<1C*$^Ja4T)W+S$(4HvJzUSO-ayz*E+op$!(Zxx>1~yI9yyZ!m?1r&%ML0%;4Fgf1C5pS
yb~z37slx+G0%S9ut0(z65m4+pOqWU<BDTC;q8=|f;6uc19eE}z8in}^}Anx4%mm-5zco!?b|1e_y5zJo3}eUd7r~~(E^&C6Hr?{
syVdSk{KFr2k24vTlyQTHN!J|KM1?S(d>iQW<kh)N7bSVt#UXD#s<~e$&&Zy@gea6{9UzqzzRZD3!GB^J)L&yLmAW=jSY9isG~4A
FlivMp3MOq{2EwvqwC~i{NEYCQB-}R_!-IVzY2fx4-tFiioio>UDXx6tKj*UWOqOvbN{yN49P{BV^@)5jNv~ehk?bxnjnaPe?Dh4
?Ad*bVL^wrmG?NyW@WmlM7n2VtEgd&DfT*r!G8<;-YBuawz-Q&h^iO%9+i<Z`3<|XUg`AoseCvWn4+0Pu@V*_0q0KxysX|8R~!Lh
26msZuuW9-0T%Y9LcAhCr^I>A_CCf)lowZC18_z!_Z?NflYzw~jCW)Gxy1_V{!6|T)}V@qBCDMZH$wE+CNiFYseALjM0;TEI=G3f
j9!QqD2OBZj{SD-^mgxE5qsL&AzO8eB}^w9o0Z#N-njtI?=>Sn<i=7rBaWuNLl<8WC5D%LFM|vdLDD^%OSDUWVrJF^A7ZI!(4Xzs
1=5`Kc$>^{YCj!FuNlDMo?XF2ja{mpE>8?4eX%;egey~V9fH-k86cdewk&e!mD2mwy+~d<+YFW6RfI6(t}Atheto~D_*XCutHK=y
S)KoiqBBoIO<}cQQK^yE8*@ej12{y*M@b%oIlSbYM*A0aC=?N7j`kfP$-MZUCiZ(xzvCEKDOG9(7V!Rf^RHlM+DrS_NWq0iNs*<?
1vCkvgJTQ}m?>s*K!M!LZ_pS!Xri_b%em(YQ0KJu88Vj^9St_1(H@bg=%gD?K;>J$b!RY(|7%ms-yl+005@yHMpwdLyXY+tI+U*p
@naoWex;iDLlYh7s9Stk{QsX@Ii;q<;I{zNuNaugL%@rfX4(~#4`DR-x=-Nq679Myo0qI_B>|S$^6|8Xm8^2dify+ZV3`7ost<aj
yIClU8<<H?D)Xbh=U3Rl*x)J9Z0O;BuRPG)w~N)nwGmq~UB~MC?9d0IRWD8ASi`>lB5|^9Fa#`x!Gn|-=u>2p4tG}{jTPaU%CwU;
<{GqzEzvh+@lFpO3zg8BSQ$_3(wDZP3b0IwClVib^vSj^&zU=ws=vraTvz#3GbwhVuWAfdsv8uvpe<SpE;UvxQT`7_ewC1%AM&T1
Nc`}G$;zH2quiS~Yr}N5C@6SZBl9+<@h5i?#(ea!Hq%Wp$l6s9oM+EggXLVJT<2$?Wp%7^4R6qnV-BE#5iQ!(izaieZ-;2qxeFS^
8os0$m=}7MLvgcG=L%YHgOXhY(TN*rHEKknjXXHq1p?9N8@ovuXVRk?wvf1~c3^}TxO>k5ag73<c;xn9O7I0Rmza1WauCHIn?of;
6^YrJ`eaiPuK33f_Mn%s<xZvb3U{G96+~ZrT|;XWsppi512UX8=7Z8Ck|Wx=-#^kBs?GS9szCrBsp~c4W&xG~GI8D5jk7z#Ai+c~
O<t%okL^D%HZn=ZBUaW>2-LY)hpQNdinel$AtoxG@&sY(68?rCi>S&2Kt3)YhSnPwn!~!J=RD)T?{W`ndRwwv#I^kF86}8`q?*(t
*kc@}8@MIN?g_euL;}o84#u2JlO^rIv9tQ+ug`Ww8YGvsvODy!>=;2H_%9(zB+<MReXzM@0#-RZz};O9S&;C91Y7rMDhDKP%0-hp
r?LO8w((h@-x`|Yu(C@1u^3K%r#QXjLvbtuLRhBi^NhY~>RR7q3r;sh*?ReNkbhX|YIpntN#=T{e$2PZ!AncP<D>*O_u-o$PIVm^
gERPM0QHL+)`Of}?Sz6nWDz&u)We_le~VHNr*YGDws5onlz%k56o1!iad^}W?(W92Y-7X}9+PQv$zsw|VD%dKjH}&waDxThy95oh
eq_=tKzyr?s>T%IGqb^fi?v6{y;`;DzD1<Q`PPSLx*_U?4?zpKTNZt_kfTP(VmbO!3tQ2oT{DhebIERF7OF~N&!kOeDL?_bsas=-
7}@Um(=aBF5Yhf-Rrr6=2!^0q0|#j3Pj4}KhM15wuk+1YQ4e8C!hyO%E(OpkT+0u#<gSN?0-GPXPt#+?%b65Fp!t&jU}$=lI>*p;
#I5^|K_DIq8pKFY<B#Z08A>OU-6xlOIANV<ORBm0y^fwpw{01w{28$jAgw{A1~VnlS61Khqs#ptddyt5azgO$M}n}aGAmAA8}a<d
kz9+{CyEEq;*NLF8ZCB|wDPBZ0ag<9Y}SJSw+&L39VAO<RKT#KS#%OYCO^HuIb5>2)-<*eUgCY$q~!o_w8?Ojb=tR2-EsuzD*4b7
mD4ziYaGsKoBfWZ4MdPML79pC92xbyO%_|rhZNpC!Cge!LgGilr%KMw_VY0ItBMiPN#jcnt0p4hTXdUFE&FpfU>f(#JMObQzYc~M
u=7++H4*pHI3W1YTvpUhEsYo+Lm0qi8GsZCyQt?3L=EN9*T%oMPptKg_1g7r9Cy_x0S~4V>Gfh_T3vGYq$i+aU!j*4kO7~X^;%hC
`dCt$6)PvlP=$=-3h1<D6_^oxT)}njYE?*et616IckHnrZ_LREtuf|cV13m-qk6hoF$Z%cH-MDHLtUTK{!KBf^f0T+#152JY7Nvm
*U>Q%QonrGntj_JmfJ)`?z<osG&ZdEJO-ZK&HJiz5;UR>lH)L&TNrbdKu2e`Fv68+s-Txha3Nlwds7Pfz^QR0Pc0K7M`A7aZIlaB
JT)KSrQ1H^6U+}xE<xZ!k(MGi_-k>N40i%67ncM@F2Ly5l~}eJAx?KX^_FCITu_OCX(MOR;qUMwVi_z67Psi`VLASE=yvn$c(!ph
UWJv<<dtYxTOd{?Zqsv*UwJ65*<Y=KU)&@_CxmPeX6*V2DorqolL64r7y!E*_L`prS1qyyK4K0iA`*qPi7=)pk-{3CI>TJ%7U&fX
A|CiD3H5TCi|=6A`TaodT=PpP_vHYENuX3DDA(8{fp`Ucqft^do{(W;U2^2HxTn$xiPPX0qZcvmw7cKOqJ#yrhAiwXV6K&SD4GKr
rhKs<TIiz_Xu0&(DxfCi?a|HsJ&8p&7<C&g4ZPfye}{)K^A<`QZI2DnLu5$Y-?!+$j?TP)t@~Ux=bW(sih;N%p9}fM%}$cI5G_lz
d(=Ae<;&VU$Ghh$0DQ8*JUnUVJK)<iOS8=?LdVe0FU<(b7z(!gagQcw|DWzKFhf8b9<OySlH@Bug6_P90!lf+{-B$QPddji5S48*
tRIh)B>~ZsQYt2$eloMrH2d6>mjV_8PBd+opbJgmNpcsi8k$_S*YSkF9ZsM6iB8A%ANcUFs5FYe<yo=PdF9IFT0hasP_$f6N!0cB
eelM*#PY$%;#foT^#TG)pV$|OpXq|_6E>UYaRpM=EK}N4p5``W4*1}XhKTCF4t1gGLQYsY1w?pr#M0on#@+a1_xS(wZrfO!r<xti
YWxdW-FM`>ph7GqXIQ|$L~(-4+h^C;hf6hl%3S%SUY{{-Z{+@;GO$3n_?5e-OcqvwXBt$ox*w1i*s#`N!BK6UmI}17pUjT<S05({
vwNV?rCb+c_J$i{sA^XYDj`><>;WZ&F6f&uO`G`LylCja<6rcSC&D|fq%f>iJBJgu6F?TzPGC>A$h4bg2uyLPJ>)+khC(g9J<qB*
qD!WoQ*ol-)J-v^y20d-q`QCjlg)cAA@iak?fF;PBn&NK@K9PTW4Syeu81UFkB;ukH0CLwZv}TDf{ao0C@HIl7$F{>xuCH^10sKg
-XZisp$fqVDikkhz<RRo0EmBOQiGGySc~(to^I8zj46<_@#}BS$WS{b5Ng`WfsKP3wd5)0=Vx(LtDBf&&&KXxtHGtfNL&=Qc;U*d
`IX_VH1rgl9;^Nkm^Md524u#EzNsVA+JW)FMr>70jE3vWgY7`arhz^QcDdLl1xX-jtBmpP6${|Cfs5Cnx+iB*8=!!DGo%3xf^6=7
SpkaREAqZ+y5c%4my-OI>hbDO*U+ki&5A3CudOlLQ_q|{?o#8`2xf2;&vHzveS>qcJ^VGkKB=x4M0ZC0V%%Zb_)m1QsiK|gnqWOq
GV^MO8W2kSO2EyoHbyz44{E3DG0fCj&cMZNi{i7OMfME-3YXL<OId|Vi0m{?LbgfuK!4HT#3FBbIsHU25sMkx@PlEy4Ym>l!>|MT
TR}o%z_g>gwv$}ZCjxyWG&2!Zw@HXnph0O26^_|v;pr38j>)mKi_ZKIG%YQ_6efJC5e=4dsG$Fo4NJCS))`5e?=<EZXB19uL6wHm
k)JY$i%_7kh1YHB?+{vrldr5R?I73HE}ELI6)PP#u_IJuEFq}(-$NBv{pf%>vrXd_HqKAMk`d5uDM>#B+*8Bue34qN!5-)ch9dt+
dm|r(vEo$+l8$d%9f(P~dSp^$Tz!jp_@eHrnfp6Pqx(>az7WvEG;JULqDEE>FMBQn6&fkW6^SU4l!yBod{&rRI`~sh5F9^EIK~2v
LAz!3k<Juj9NW!Kg>{G-=*_Jf!f716n+|WgB|N$YpJb6JvOdxcl}3pN&SM_M=GyAgl2O84vgQuesUTd4Mq$f3lIIK;Er!yY{THZ+
b!F;dNwuGpPkc7dh#SywU!;b^AZ+>`qAnY^M@>?oF9I1^;Y{tp06A+9$Sgv%At}~1y6t+FN3_bz!?_oDZ2bfrtU&}gzju!_#GWLw
BW_MSp@4i+0zpqbV`h%Rc-LS`y+$eEmtg<knDhFwDii+Jn)PA`29G|wKh>YPLP0*}*{SKHPEm?UkagSVUh{=fVg9We6&2aUI*zN%
6f?B|QSchdP3lym{0&E|77Z+9<lb!$)>+Zay=lb)?thR`WSCT;(X}Fgt$|Zf4UoTv#|yXT><;X;5h0XQLB?y&QhEa#P~DzCctqt~
$~sy<yEGeuDg14y1XU1%gU92Z4MTfdKsmm9stiIw*pr76BptR8SeX(Go&vVqH{Q6Zt$0vIHpqk;GlDiG{XL=Ky(=eui((E#)wbh-
DMEWTF7iZiqK8+Z;8G%mui!(^3&uP<pIlodvP^7|SwWosbMd}XiW9kxm*&(Gc^Phvef=f;YE%{n^n3Obr@n_d)DjmlKF>Nj?7#C+
S66GVx1s@H>8ppawy5c1lf|ugC==<A1y-e08jCHeNE&;RI;D!s9cu~t%4G{D!XqA%Rnv?nf0j!Bd+HKl@GUu4IUot*a~MJ;W1Ize
`T}?jh_gLZ>+}*4WwtZyXd*T;AYdYQy0`n#;|bgVY$#{I3GZ94UDX4XKnI4BBavRxYu(9MvIsI%12_j;w+DpitAI@>Q1LVIsI5sq
`*rkqLw{{-VH`LxK%8nwdQmQzhP~Vg+T5Pd;Qv)vL;5-KpetRJY93G5JxQgRmYZdC%n>MThj)21n&`_Jx?LlzG$3rMxWR*y1oFg8
vwM8Mb`4cd#Lu{{uspo}p|1P0wRiWN>LyOyjwVUFTyO0pA$p&(c_~L#thBa^fUkOa%X8{l@PPBvXVt)IwhI{z(zQJ=EX)`^LE`4J
D6HhN?Y$dD{`>*s6U-$MY!D$h`zdN@>dcmo<Yj9lWPx%e$6sI8)tigJG(Qu3sf$P)o$Lu82*-D3YKN0Cz4Pc<c4E+nCUXUO6;8Pl
p_XbeI$yW{-?vWCzsk#%Vjmwb@p>L1c$2~I^yM_p39uj;v7OfR=$~ehIG6a&;LZAQrP&}V-z~!l>6JREEE?b5gYY!0A*uo}wts}4
v>?B2sGZ(p*iz?+2v>@};a6r;LAj#q&(G5<IYBbQh)vhU8{OmXJrj*5@&t<nd`Wff4*tK5IzsT;Y&r*mTe-xhaRn;e$)}(ME-HIN
K)6qz-5@33!+Ifcnb+mpZZcQ%WAlPLn5$DxB;~z7XoA&u1nb5pLh9cS&*s2$uic}_BS$$RpS)g$lflw9(Pe)?$%@Gk@;11vsCu)6
VBll+bWm3liOtsZ_ml`vZG1aFjYdhWP2XRx<1i!fax4l6e9lZ$#uE_gS)^MS1_&-bqU;q850$g%Zm@^=##FsU{^)x;OsKxY*Bbf%
$i}*A8<geY(}w(#y;akw${$URJ7s5J>T`q@;<jnawa%sWPVSC2n)&#7kCKd}3PQUfd5Skh0pLR9h%+gTqOc=m$o_N-AZ2?)TKol!
(4~P?-_s%kT8Yq_psRcTZc8cqQ*R<Pt=l-MRI66vhp`V@=0B>(Vg_S0L>pQUbsW8Fa`o0kxyVqbB67m|j4u|6l^4QH3%<tcZHNqy
3+1@q%F(aCz57@cc?x9-kW>p)Kz-wscbA9nuoQ1JtQtylb*8NDgfE{*j)c-~><m##ObYqox<9;to<5rB8RecU-$cthb^dtYe<br%
0j-t?xfgf%D%XT8$ul@e!M~*Xcppr%5E<Emee+EtOlMb0OO}1mxsq;>cYPl#Bkq!h=YN=L0EHORjt9I|6;x@I{xS>yUGq4us{nK#
?8I=58e6O|S_=NdZJ7G%muOJOLRYRgQ{LA7sNMZ=EGzs!$OjA@a{KllD$O-H3;R9)Dz8;j^F@^X&>!{kPD?#n!HfL0OHNfy`4*Wx
ppJU*#pOZ1!p6JN0>`MXQ~^73TK79&fro9#9as`!tn2}y>YKdW<iW{v|FtF5q2*TWPKrxAZ%9Oo4cd9{KbrXizAuujVI-G8dBpH<
zUI!kL(8PfXvKCdSFC#h_2E$Y@?^Oq0Du_4Bk#5SuUYLySPYLqBRWBSj8p$${iM^ET9|#@PKDLO-TZbOncnbX0bDDby9osp7(>S^
w7JkKhGKiEe$EKGlo!*2;Yp&0LqbyOW%XuyDC?DEx1@%wf`vZ1inA|rd%-9K)9TFNW{m`eY9k5gn9<KVr`JPjt_m_O-$n;IY$2zE
Mq_K^m)xDa(7ErD*XE&*Rr@!5bY7p(!j<$^f;2Tbsu6rWx^o^S0i)=zO8<qXnJdo7TshO3lU8LT)yK3NVCM%yR=~u#jle?HK4&^6
$#IiGj>Qx5Ng)?q+TsoLy}TZa860(JU}{oB)KFT*bFPsJ-+tF?7-yFgB)!7r%%T;XZi5B0()jtatp;ldXmf5_*ky}zB;79Gj@8O6
%VD=uCsc|eQr>{68M8x|t>XC+jp82ZB30WnVxG$FCppXv#~)rq^<?BMY&hIizTr&p%+6j5ufB7&S@}A<P`pZTyJ#7|)}Mp>c32e4
a_}s~fAY47Szi?L9#=gMGgU1ki&%b{?GHL?<hwgqY}Vgd$Y%({5a9@#K);_z%flAb7}~Cm=Z@J6I>~vP52$x!->2Qwzy>Y(bkjci
Kk^X2QG@B%Csk#|nN7y<NCnZj=in29s6Cn)ttCoYd_nU+^dno5Zl9J4b(a+UhzAddF*_c$siDlf;?SelR!V4fSavZ7B;1F+2W8k6
h5Ju9Q8))hNlssD_dE3;RQbL2K98>cg7r4l`f4HbULf~s6v+~f?t0))ERZx_-?iA_*v=&|i11JahQG8&(I)2S5PGM;tgFE3Z>m&x
-}aXGWBBjES<$`jQ^Aph<S$<@qdsm+m_pX4^CafhLlD#{ndAEn*cm#7`sQWuxxYzC6hC=JRxb-Yo&32igP~B0k4kPikAJc+MHu?k
u8PEhIDZ!=NNK17z}7K0o`+7-_*s3oE9?$h0EPCBlowtP0fgauqIXq8&Wg_766;*^ZK!vK*Z&3SENp<G!n+AN?GOaxo($Vi3$pE8
1r`w<+}81oppNm?(psTewoB#7Xh1DOx=iE?G1yIV^V{Sf!VvxGtuuOrjj#+P10IU!6^ER6fGPnx>rYoo=^Rw5dg5A}DU@|2X<3ko
Fw6hP&e>;-$G2ADir>2Vo+3$8>B}MiqQcrvZFq{}Vf2!*%l^sV#Bk>C;1>*PK%1TJk{I^Eq5@)9+jo_4@>3DD{jIeU%+acStelx7
$d_kzD;l0|Bn|nt{Rm6zGWW3tk6wYQK}fQ&hk@nVS!c^#{E#$?&g9pf_j{)GVpg)zUaV1p1z-VnW>Sl~|4ziQzGue9%1Q8uO~4Re
UOBd=b1gXsCIA83ioFh{==%TWmmH&Y9|l?tI-p$*a`8p83$6u=Cj#4VCQ}djtqPRSo59pHFXecc9DI;ca*T_UQ5d00{-;tB*#)^4
u<pNd85Tzvhv5;$@6zyLZHL($R89fW0^?;-qC0C4*UU!OtELmO&BjDL8l~;7w+E4J%Z@z>OujCwrqr-neRo_2UPZ)&%(A!5=l>qT
ckNrFCoaBD$F0tqQu7K8B;-}FSx1uVO%e712ze~O){H##m3@k){<-%*YZ)!Ze@U|;;bOpvZQMX6o9B;-a-1H<z;=RvZR4q`5^;0^
eGqNdACqFl=QiZEQ2^r}F-k=_CEb?j`v<I^_<y}X+O8Z;ppL9c&b%c}6B+Pp1U=TXFqQ({0;b@^)z#{ZP7R^r6rx`<8M>-2-z}|p
t;S*+<W6jwnI+ovXiz3gYM7(|d=B6-v%0$(y&D=exM_~jK^MsF4m?Xnb<dd=CBa-z*VI;QhSm&0OGoB~&QQLKoW}tpSd{ur|9p35
Xdd^h_@Tt?t-yq)w;fL!FTg|X;psp*&)>L_H~trc64Lhp1Rw+FuMOAO?f@kkkz_*q47l$R?(j+E0{V3W5ePA+;00d)!$EQsbPd~0
>IH47uS0pH(o!Hp(kDbWFSZH?NeNvRk9KsKLefgEf+v3DuOqQN4!3AEDHs1iKscbS%Aarf9ON3n&ZO7Y<G)^t=uvB`@^$DK`DSP#
dc=!$jQtKmnSMQjrL$Ua;k$6OVJQ@(xvBv|eC#<~IiojRRbxaHr8qjYA7>02jl4v12Q{LAiTLK}*TQ8Rl<?MTpX`Cy?A0E^Y17zh
F7(G#X;jCb|8n|^e)&ryJkRSCv~eLzI$R&$mbsw`aiklXHh!c(!eNa&L@;IP;^b0FJl(bQUydImUT6ioY|ZA+7fz5Dk@j^mHL;gs
$s)roxTgYDBARDEoBaP!L6ltCA?b?qW(pzackNx5VvgeYJ&UQh?J%1>A}(n+_;J)R<IzCA4Gr|i`XPt~8bhw@GX5&#zGRHnbF~O;
3bbA3c8Aq5miNmQTG3ZsR-1m%RC<2SK>{W>4-cEtwi6)l+Eq@~%OO(QT%2Ln8Tu`mVKK1`gYFnk6C++5PzkbvJ7TaAt+43uMh_}s
Q^{uHn!oFvKUwh$`${tZyYhR~8E=PhZ)`%%xC;0H38wnZK|E34k08uTZV|GZ_$yI(j!$bld#GIilD?!EmpLLG=ndhn4lpd&q4<6r
7S}|9sB(%g2xdMWe_$kUx`Klt!ym)h?7>{jMo6?UM?5{67f;4-Jz(C=FsS!%rOc(*nLL}D<rD#(^K|9rw+d;SR%bU!njHgxK$yYH
7-uynC;1OL8*e|w*`58jPv^<$MrPC(2!yt%21&SMgEUWbzBOJojisJ3KjB}L4=R>qj+&ytzJ|n)wS5njJ&k8mD21E<VQ?hlHh81>
W-)+#OO8i@yJfdzp1ntvcRF3LFmk*A4IVkUkobJ1{k<H;RQ@s~oR=#SDRXqa+oR7f+Y=$xBD6<MT|+2rKJJMx*`tmFuJkmds_0lO
N}mmE5zeZGO6UN+o#^B?HSMfb0-3W&<=<5*HVqWuea>un+>R_{MNoX=vH*F$7|?49<U_eGQSkbb1ykzbiQm+|x;j@~45X_{oCL6*
5BZ6Gu1WyHiyR$`h1u3@>dGs^k9R5B+b#=L0Ob0gF<D{_9kq2KRhN?U<pu8^QL4xxUm;P$xY?qg;LgDfpFS7pU|X?oHLDYZ!xDz)
MCgAH0j*=2>pHbh0q@GN1rx*?nj^^cAO<b3cUSrtHbs==>r!bO(kH^~+Iaf`ulR`DaRKM4`?6^q7wnpnLb-rxhqx6+jSHL0OoB&p
;xj7$oj@QLox2-`yQWDR|LX@u+xM08!@=%#;XJ}{rE>A?*)2;l`ZgetZwPY9n?lQjCCXx;i%pTta12!0<-^T=mSqn7PqAYj;qiz6
gv%1NE@2ut$ndOzm8GQ11_C<k+qATo7Nc9qx*g{#rsbSyNeCv3(6~s067s-=Ro#H1V8FtP28KQak+B&G*{g&9uttGeiF+<OCJ*hM
Y%X#Qe4bEY$I7{XGoBn}UP>XTz<k|a<X;rv5r9lXSjIcWA*x{D7SD|t!P~aXTe;*-G|tw&coQ2{Dr6B~h>RxY&^bpQkQ}XS0dMBX
_iu%vIjLeF0=@4K3h8AGP)be#$%_Y{*~e@8`KR@+E-9Yz!;Gccre>ixAYndKQQVSl+Aqc=QVY+=lDY?9odsMoOZmJ>*y(5tBBACf
BNeV{)Dn?aMqr)U>mQ7t^a+hestV{v1$6yF#QwQjoWnE2xYSVW5jUeVX1x!I;|(1=cc0T0mB2J2Z1dZx<3W(P9btxw47ojH7al^x
TGUCZvAa9;{{6!E1*PYQ+PW;RmFPo?ZQ;%YM1;_^Ah2Vj{3COKvD<fUD)-L`|0n)NcIUJ{gqaquyD9gX?(Bi)a@2oCRx5ZL?y33q
yD?O9Wk9};hp(;WI%D2|#ozEQ`aV<gQ!r^&Of)Rco|WLVLl!|b|9N)|j@K?W4TRzgon@VR5GrN=A?U~g)o+sHJa}Vr`%Pk*4{G+4
d<!T%<+Y-MQQj@t6}tPOj+jZ}mb4SGmg-<{A-R)_C2~k@3nc-OR1v%PY{J-Oo}~t(SR#qk<5UY|6mfgGe(_Ic#xKF|j60nfh0#gT
1qK735cxL$oSYCh=}r9u@rKnj2R3p7;Mzt!#m!Vsz+KXs)d8k5KUJy3Hk3T+o}Caa@m?9hm~^;i{`)fmxj5J~p*8qV%zKJ*zhUoK
%*mbW<##)XV*fF{ou?treRd+wWrLq4IM=*MfGuY<s-#Ti6Bcq%gwLljDizDqs$SlwpG0?eNv!jcu_OL3LbiY#6sFrVt;5eoJ4K_k
d4_9Fe!-KjK5OTj9dU?}$>Lne245AcXBjf6dP33vm5LXA>x@lm|6vF}h}SP1UMLuX?IF7&JSBx%oA^EzF;TD>G9v|c5|sCF)hKJO
q5W4dhwmLM=cPN$S4kJR;m=q|d}??dm*7y7Q-umQ+Kh(=@VTfy<$Eovy!BqSDO|I9TdA%|bqKuOB|%tJn$t!V{QeAX85oo|<-L4v
Kmv-*sJj(m=MlYyF5apitY<3|y9nG9sr!MUa$A`Qt0=7r&b`X;hjU`&f`13Z>&K1rhGWPoxLI8I*#8?fbu)aEe)U5EIx2Q}U!6=S
N4+iWji5lPQ6-M**#tj7UZ$6&$u08Ow*iuV;K}6sV*32s--{eW3%R;}Q^qaDg`@`|lKdB_)ccr<jP6DSDt)AcjND=*U_@P$9>$*$
j?CsT0|J9QP~(XBM;)q<z%QjZ_L&1`khYWk{leyXmYo_#lRd%tr&6W^sm*#J>HCez9uEZ0(SGIb+?F^!AhH=&->d!ZzIl@dZG>r&
LRS~FM8CHvd?BUpxaPhLuhi=i;P-7HM-ol<%5`JW=*jGq0eOfFux1A^!PmB}Wx9z+;g8xg4QUjFkxnj_j7HGx<m3)T70V;+9|XP4
cr-*%`<b;fm7`Q%z630YRx5^RD5$pLFjpu!xfGw4oi2j)#agidS{}JkQ~b8QVimqRXrvgx#F2BH9F?cII((HhzaiOH+3E!sqTHJn
me$s|rR0(FAeRYU7Nltzu7`qy?x`=<<kE&EX)RCL$NgPNtYb-i0hVR2|00UHtdz3Blz~l|J*Q5DYuw8GSw;4Sc$$zhcIS`L9BAS_
z`q{aa98j(6Qe_T47&8X-4jH}B2c@K2IL1<`N#xV($03lTTfazhS>)gWAKl7v+upg*Tt%W)@YNE8FfVFcb!4>YQzOZEr*Nt!C=fG
CMh+9-|I}9HmM~MPEx6-Ke-N0`1UeltL7#rjNZvXoqrT)=6ZpFizRq}?4goTyQCbJEOecu&Xd{vnK<Rh+mB)g{OVOmj}DQ?GYH!n
75XcEKGPJ>1wxn`Gv?CIH5|zHc2$2UIhIIa&WDNfLLa(lR-7c0|3^wVaNBx`(SB4xv0yZx^FCLYZ4j<qC}Ap!P6EyH1!Ay6hNb)k
`3NCCA4TFk@Zr)TqwsNk+jybcAIFQyDQk3I_SnyIJPcH2P?$nNr1xU|fOnonj%a8<S9;*`Jf_=&6F<y^51~Fp*{Zkb0on}Hy--q|
-qB41IMZIN98Fo$AkTlKnQ<uemmMr{wFbUYoKxa4%%QLf!RR1r_0NtJN4eF0*ye+^!f_aRK;iTnZTj9o99s(GVo{8)D1T-R*L6q~
kSmMd|G-zS<=zEsybom?&`ltyzvuG4j!~u3RqTn<Lh5F8>Em1osdlpIq$j{~@rI}iKN6M@dow_IZ+4^xPLumXykI)#!Os7laRJQ3
>sJ3Ni8{bO#q3~mXQi8~&f@jv!eSTL%HT8Na1|I`4ViA{izFnD5YHFN;ZvgYM9-r?hNiL*UlGDqc`tYqfPxK2HAR<Tu+%gEZz3y+
Ie4a>RVDP~WYQf-ff8v0rQy^a^!mRaT~^P7!8kU_5-Cb>O*ygeO)$mM_ayrlv8n)~<A?{QWkChq@5ZQ?az-{PdGag?%aW=i$Lq?H
>T>n~y{623wl!<Ftb^(swk~SVd&50UfHplP%i;+o!Q-4p#zw`ad5r!TN55Hw_49j$wD>#yNZz66<SQDEctf=ubF?_*fWlY<MaWtK
gK*!0{WXqvTRy1YByi^^AtL7gC7TWuQR=_9y{l(}Cm9QUw$ZYtxc{M&wBX6oBt!CaK*APvCNeThSinWv<{%IUEwF1=cSNq3iIjcJ
r(DK3^PcP?{rPuSh0LQ%-ndFWq`Y-5Qchj;6Aq$^li;vb?-@leqde@Dg<&RW63jR5(~lBSnswYeS$z^cHw(d#J(BC0)cl6Jx;DbR
<;@wzd^x%@i{<)ke(a9FwF|LHOEICT#I9Ed#Yf(6n_xnv5MBej01Ne6k)Zp`iw6!ws%deO<7@9C1vr_8E1}(Z4F7n^LpVCAAg!*G
5l5vN_>&jngrm}OwI*^5Y=YvfG)Q95#rBfvTVo!!fK$Xofnr7?L%vm@2T8B6*Zp*C3PU9+r?Yxbuc*vc>p27>-@X3uDGKIu#o^!Y
VC|>a*KHq9#`bz`i&Ba!+UNty^~rWrqdFEiBc8DxS3I_a&V%ZNNGCQ7aZWtptEfz5{^*M>Fs?~x+|z_xGqN9wf|E=NoETvBQPK!%
D-X`}+$V#&j3bd<!sw5hywz|@OFa-jv1%A8L$kmlLfxB;xK%BrK3gtIFvLFMgb_O;^ULX-H$3QR|H({{^$WJijhK@Oha$A98x^^I
F0TsXD(0#9sTL?(ghgRR=TS+9on>TA^lQ(VnhvYA{p)st=qFjHV|M1Msm}Z3N_4I#%+?DnFuSB!_IRTqr~`>6O}e0qarl?KUt{>t
)B@myV;hH%C{j<3YAKs`@j?TZ<NAddNtS`ae|vq2@@s7}u2zt}-DqWpt8WB2q=-~)`GVGj7|>U$>Pnnb2s+dq84(k!)7nL(IM@Di
Y#hyb*31Sn6i5yeMmXnpPNv&l>CJkV?fT@xVU6nr=a(Unn>vtUDaFx&Vx&gF)oQlNIDKkMXC~ga6R2+k%M7MFT-813C9Dz-+Qi~p
&XA@65wy67T8)AMklfVV{N@X-tspmJzd3Y`XiRd`z<!MaVoC#_kbIG-6V8F;#u+HrZ>{FALIHeO@dqMY%<_e|sI@ELopQSVb4T^z
wc`flNB{fo5=_kvD-Ka2%>Ub!M!D6(#lpywi8Q%)UIC2C1e2(z?mVY1P6J2^3$<??9B|dg`ba0WKjgH<u@Oc?!aK`agmABqVrJda
;;bb}7Vma7SQfQm-pRpqY$Rb3uU!^I@p>EGkn23vm@t=SU>iJ7fiUE7X1;VZ42$*dx|$FL;e6qa$~y>s)9OfcSi(8@Hlt6SYf9f-
R(fT617=(k=!vIbcX9|MGMsZJlV*^OQMuJVaif$^anm~iK+TwaZ}ziQ{zy|0DpQd1G}@9F9E~1lnqQ3m<C3B1u>>d|*C<jbs5oyV
W%qZz_%JIxLY)&);X{mBrm;kWR3%Rk%8Ip`T?%GF_0I6eNZ2K#=;%QQ1be>(yFl3KsdlIXGRp>fZU$ZHqZ|?yAw57^#aLAS(x%ir
=VlYTSSmjVOoAZx%|67yMGBJ9A8%bm7`-=&^K_!gl$G-3hQ8WR!eN~^vcD9sbta=beW|8rvq9=)@coB)Zf|0y9yzvRy7w<U{(j`R
rL_?{GYjCW{oU<_>9uQ%X?Lg|_s~j8sHAo6a3>=ob}cFysIVJZ|0+8G$7v>v6S5LzhIKp)WV?#y_1U_?q2c4B+jbKDn^&h86^<wk
k`L{bffI_-e3B%4bzDR>SIsOiM;F-w`ugZ`%3w||Ohg80JRHRZ?+cjgm;N<DNKkJtq*yU;9o;AYy#h5{+8<q480MfIgVl{7hX3)B
<hQkn>|Sdee@~(wIfEi4>&I5&{lPY^KR}anUiyq&;wlEu-)&$c(cq)4o%Ys(N>`|6-@0okL*cw-9Ndn^!t)vyKvF+{$*~JP;I3|*
zV|H4;}MrTJ%KH5%qON+&7%HV5iEOWvKN{C<-W+}k}3!o)lu&Az5tH_=$J<4d~o@^FF>hfZ6wAc>QrMxUNOWCq_PeOQ)bCv5;YQ$
ztYFadJCLC*E}U99@{ft6gdtge3iIy>0APO4Ko{UVdo#T`d8BV^_Xr)XJjRiE8Rrv#QMlzPSF7skW)2U0EU$HW7uRf0m9lH<hbZy
;?p7CqW@&Q6t{}Qfb@3vb`A!IxAn^imm+AaCU@3|M|&c=nT8^y=Db<DYh$;HaD*3R5z%qmb}d}J5(>rEDlTXEh@l>&%kONZ0(|%$
#Eb$v{?Zylk3KDwWl!AwUT|y*lE>%$KxDUAec(`X$<ZgC3Jqgy_`!trtBtjZt2$r75TmGS0@*IO<qATYQsGsR7x)La+!S;&`BcnM
G=js-0d&ZY&zpcTd@my6D~T!HPi8s$gE;d@b<&2uT7w{0T}mA!r@BnMFl$fcPiFv4V_POqfj=6XgM{4rGvmrM`!0`YUTCSwO7$pJ
d}47ZAr6Eh;%-`#lSMmkaFdg&(${n<<G_HN%8rtyx6h%!MdZz{KA5{uxmK2mAfBOC4i0=s--~ZO33LBuAk_qOYtWM;(rrvD`*@UW
_<Kj6CR|rkoT@=CZp3vDjl{5x@o$4Ur%s(+&=DpsKR{v?2syTb`j*DyAit#mZ1F%Q#_Q1fX=bK-pQh1kFPTlgO2-?FuGkw;3pXs_
w7BW&$kP*@xWS5HB3crNOIO_?R<l@BCUn8nxzO=prKBT~fuWuO@jEa^c7UwJb4S&xMqj{AImE8cNAdA!$y<;bP;LO%QI17N%>yhd
f;iBL0dW%)pRH@T$1bk5txZuB5{`(LUc~`>uNilxDz-4zm!s9Q;J2Yr@yCT)Q@84I8*sdz2vQ4K41hafN2{-AiAD$x&M45TG64!2
ventU-rV7z>XW)07$R9W{&7BJeV(7?#(uS4`u+i0V8UrKWdGu00MtO8v)yB-SOf9rx+@jX)Y4TT@LE$}KvTWoLyD^=>-U?z<Mo8?
=0My6p!FO}3K(d-#j&M)2ZN@6+4Ij0iu2R*k~p-3hK5f4|6rncs4Ol6;u*ItM;wBF-&y->pa70AXv9JsZO<ps%&TYj^2NuqIT2cL
^wh`}Pm0rT&@NOcN?MIf7_bJl&B1f#XP(!gllS?8yBlI>in6aTKg{Vr_^8v`SYV`(D<zPwdho<DW}fS$JN<S%c2E&ifPiEf$`dwN
`S>#+t!IYp=Huk(Q%4h*25?TE*jc9rP)&DiyCR<4F-l6Ntsn~sw;)0G3M0ZiEljmA|M&3~8jtR~`!$aQ`eybILg2dEfqa0ULQVpf
*QH}3kkY_&O>OUj5~Ah+&zG|&3yF_DRJ#JcBj7%es^{Q3seh%DOU>BnY27VOmJj-<QOO#3B&UfH&PqQy??FPI6YpLyh^1`-+wha8
IGMw)H`3ApYS0;ys1k@w71IUg2E%djloAI2&A2#|t);aMOJxD<mlf$9>_`)Ryz`Hf#U?bNC2w#j3~7Bd{QO~3oWb>t#|sr^NVjVi
UsPC>h%mKviq!(l)Ig4=6|Vu=We86(&Cv7c0=!zhuIY6Pv$gmLZQKq#C`~J})6Seh$Cp`yGuO8{W#-7Gsi6etyw;pWa+>DyM75~K
I2l!(-TyV;u5l6w=2;+m1a@=`d{b0Y9}O_+%&Y-!b}+y08-KEenQq1xZdBc7R3;@n@UJUTaMo~cBoMw7V;sg%G~K3l2jj$cmXC?P
3OOoOnE=!5dZja$Qp=)>+}kRpPA8yE0UvHGWzn9IUTC(mdzQXHA-wG^0(_TID5ifmQ1PCi#7ElWv?n0u*29lt34IBl6sQTDb<ytM
jJ8|`;IZ{}o|Otln8uknkI5hF^ONwbEIT?ei33pzGQ*(@3a@pX_)w2eJU^SR|9iwZ*G?x0+*7wid}v|kN~QSVy|E?~){^=FV&|wN
JOUmWCVC002f_N~Nio^)k<Dsl6I4|bz{0ZBSv_Rzo9sCyqs*N+5~7*)!;RNZ=S|W!DkR8@R5H2^rd;6GX;9s{O%?wzIKVx9Dzn%`
Gp+J0GpoC%ActPtH@V@(>eg0jZBlK~H@D^Fy9F7kZ3n(;)VgJ9gC=lC%RM+T0aK(A7bi$C)7*!0Nd-ZYTgf69g7eRci}4J3y}?vy
<g{z@K0SzfoC&%;SXEH5#FCWA;m`it`?O&`!ObgUn8zdT{RdJ6LR@SwC4MqWX2=uzM1MBoN@&X@A6=G`8xRY^R(`(x#7!r{cUPRd
H=ESbso<SzR;6xNd|at~IVj4}b9M1@m6`gDm>Cd1qlf^c<jKI@ALW66|5HzLSGs>-Lj|)Bmpb|b(Z^0?B*~+Hcf`;uo0MZ@V@!5)
ll8rYQIOct(R!ekRecbi_FP_8(!Ih&5A(P^+%9du)I8NHE$Rcm0b%aK_7E(XC>6f`RRt5uz+1*Y^h!eORJ|?Rx}_|0ANTj)BcYUn
pyvVR>{OI;F@*?O&5*Nj2e<X#J5R>@=-vCrYPa?NR$kd35YLR@NdG3d1GJbV@v%<Aa<wJc(q{<4@3B5aDrXTr2ensD4<TW%g!WpJ
r29|PwjdqXR+B76n?x?n@zW1vp6e%z9VjPt6L-sdJZmC55yF!UI9U>{vMs?vFF}#!3PWQ|5CuzoW7dB=PF-S%JUBtCXFdQaOB(e?
>UJkEyhd2$#^SG+^u9*()0Qu~8Q7P@HqB?hBV$!W*@(XQK{G3x?3$<0oxP+vV1lc`o=84piZ-A6@0qnBUof!)Ktag$%Oz>{3;D#;
$Fij*<I=5@O>@&4W|&IM7mr#WO6F&=F`G1LEM(Z@zjTF<Y!OX1^2T;%P*^p-UB>sPlecP6pdZ8RJNHJBiBV>-se%(4Y_v~vd&%Jt
oX3#EIkhcfls0qyP(=}rHSA%{=_2n>@!E=K7U`}E-Tzt?x!(!u(gc0!I!V4Q546-t!Fb7FDptk@|95cm(~&@f`&u1}s3XKw@i!M5
RxEvOxesDH1_4Z&A}XSN0&w87FOt4eCFFK>77|6-_!xP@Ri|5;E{+`!+`$nHoKY3IPQVU*Er67@vl)h;>>1;Kq2=N2K7BnIPlMCK
j6~c~u;+QZA;WSTTUkG2(4TO?B@kfLjhKn($=L<Njc)Ft*+;>TU!(-haur5l>FDKLVZ^Kn$P6C(fc0aDPHBt!Sl>a0XBAlIuJ*>8
%Pmu=4+Ijnv~bf)7A<PKfinAlYqnP6jXZd?rs(E27G^e|+lyZ}Hb6d&o<Wc~rpdxm7~2UapX_EBD<VD96f#G#M5vHt=!foq^l3_p
3E5RfjdO5NaiFTO)U@vt5>DdU2D*xIlxe=6+XJEg;ENrkYn;?LO7~qpx4xO^VM=P#!~k}2fEI9($>8r95e~zk9weFC=(eYo>(jGB
YSf6&3?xRZ=E4u%;%B6%9=*`m7=-7~suVXZVSExPaenKc2=V2nJcj1QwC!F|sCsT%Y^bs+%<jIyJ}vH6!t|86j}-mgh5`2B@Xa5z
u*s$zHf#Z`GtjHkEDj&|#CNi@f+^xauXdnAY<df=zWC1vSDqF#lvP^!R^%Qd7!LQo*2)`L#5e)}ZAZ0QJ4rz-nCDvdwfG?qd)4{n
ye}klAOea%;F~XHlK!}~0Ux_)E<#8SC)%mDV!Zg|HA(cLVZQEitD9WAu_A)9P<uy^;i#Q;IW~)`1@+nBy#L<)Nl!hxP$sY;<W5{#
>{7k^DbYSSaSH7E3g=k<IV5pwm9Zf)geH-g9TNVE_%>O>ddv!aefqpQ6!(t5EGBDi-qLe2V&aMb@z})zL6{>~B(x~X4IJH@Cs=CA
)eru9Wg5yxuYbap<(ldB!Qc+?v|2@H<%8t2aPkf!aq7M;Nla>P(NWTW9F~$rBxZ!VQ(f1g-~SMH{foYsMc*e>L1ePSraQb_ErB3I
aas{xiSxXwm3wnqc58TE6V(pAs%IN5EQRLe6|9XD62+#c3&_Ypu6ax~HV{aNArL}p@IQhHTv(2cKX;k6)*udHYeIiwu<k;#j@cTT
uFXONogn#z4XJX2$0hzEOK@3TlJXi|#q}z@gk2h8W8;c)x4k2+?3(DaV)H~YKgEsQw;FLMCY*6nL+VB5=l+MGsR3H|YH_2n`riI*
m}4vVnnEF|0n#ZH=&I`NTa2c*5_^%6;Y8-aD6QY(eN2jfP=a+d7uGn3U&l!&QgH`hhRw;nkaWg<%01&QgPOPkxwLMk!8B}Sxv+xB
PLAiKPOh>mxA@)ir88b3F4C5Yx%B8wrV1l-(n(Grj`NBhs0~Hyx~Kgu=u#b=_WO6lw#+`|1PB(Xh5$lPmI@;NZmJvYp{y`5_-^{U
y}+x);%}rn=aja%Loa`JGdo|-SnN=<iukF)9QLrDgu7%u9mGucrplb$JQaJP-x=bUrQL9K#XowO@pB0qWkKSDHq-e!9C^Ac7Thrk
!raVdZ6u-jfa>Hk`yhnpnIgFCLt}gi4-bjxAE(Uck<gO~JcHy@k~0B^%>GOWecpI+k2SR$HB8cqLR_K4?8N-!;Ib8S_*rm<{|r>>
@>m(RQq>m0g#jlb{Yi41evKZI#Pzl=5$I@$p>=ecQpw4e-{+Gq1XPfJ0@ILArDR!fOj7)kQjDj76>9eVbPA9J&Idm`Sg)|BqoHVa
*(O`4!T4SzUW2w5!`X**Y8^9sgg2zOEM1d8d(Zag-Uubze;3vEm)3f3o@%O~4A=18FuG~P?{I>{M#)Kiu)CLI+VJK!ei;!L(otpo
>bKu)Hi%i=qA#_r5LsL2u^8YFJsSfqI6Q$Rx@-0@2SCPc15B4%tn*e~U`#BqOFy65&l|X5O*&ek$~K$4uD}ep*8qhQWwu&Q?VCCh
Y!uMp(_#s+f}q<euNehGGVND?-&kSY<op}Y%PKq_5JCz|sIcHlt2<4>@I7$QHFakR-&?W&#w_vw7k7IA00000&O6Ubc&Z>300GXU
0f5E<<Z>QtvBYQl0ssI200dcD
""",
"""
{Wp48S^xk9=GL@E0stWa8~^|S5YJf5;AH<%w_N}PX&g5RJMSL=waEvn@m>^KfaLOme}@`BpbLB>-YTQ+84`b-c1C6kU#R_cqnxEi
C97Zi&1NLJ*PR+90RZTHu_12ggi7o}N^QdeXDX;496@IlSbL;-67&byfMidRfu7HDhN{kDN|j|6VoM*L<zq&^X|BGEQQ2wrrFA>r
`F$cJXe%N}=Y`c7-9;gox12;-21qw{6|1P2`2vgz+CfPOClzLg)Ri%nat|)OCX`%axQZM8Vdq@Zq!F43p+wPO3Y-TtUGaK-{28w+
fh^tuSZ3yibZEN8VZ5XH$tMwtZ?zETg1rQzM6rv*G;rk!HpUY+teVi?`3LGnT3X%<7UT2YW6IsNs=^y(cDePjxQJrM8;rkt9o_Jg
N!_|m5%L&Eqd-%5BDM7Qjf25Cm5#WLT8lyTWfUn-56Twt+D4ZOHlbzCjEYsR-a6_AUFO<Ca}d$6`Va7@DN@)hEs#eqCIBRLHXm0k
(*(Ma{j%ElJ%jMNvD+{4{<p*tH)(<Y-wCliDByDH=jgDN4<6pHmazRwyPNYK<G0rsZ=uy*NkY4VvXneF%@fs^+@1`;Q~|{Bh#b*a
w(2{+O1qM@$egY3pa~B1V$r64V2|~h?|SgTX`FrMA73qSL{(@gLIU@KA$tdtDjfTbML95`S4uE$gZkXUE2%m23Dx|m(ZYy0p*qkc
QQLmwA6M7DHLzx2Ap@N-2iII#OKo()H@w%f1QIg=vyc%S`2yH;o7w&fVG-)5wFbV=Su{Ac<s;BK8lCx%8#)d3ts&4!j0^s7R!BhH
$hifSX+@hr(KprUnjVT&?GM!hSZN9ZcIwt@u+>(Ac_^Q2{Rvw51JFlWT%?`%WSB&b@H9~@8yDr`@RnU*6GudeyGysMF!Km~U0o_4
j%hwDd##^0#$?af_u`-34ZHNZodTqXwFyW1GIP38G9(=wkA31}T-yTM+iaV$+G$c=lhF)?KS9xU&~A6H;n2{*u@Z09A!kpME5CX|
axYLWzNrfeN&iSl2m_k-KQ>UXN`WhsNPidf?z7M$zre!M@yS^`liUlpOUdcSlvAO16M0RxrNmD2`%_0+G;B%a?ZXiOqM|922T-)g
Mw)-rKvmbzvQBIfR3Pd=y;Lq8QsopZfOHy++uc{^F)h^^UD)c9G0lT)F>w%InS*A_njlp#$ub6&Abj@ih#GB+0%HnFGx)di#Tq%P
-=&4nNb6DX^I#DpnG2GHan@6*pw{329l$-mgRpuSP`9^NJqTQa*{m2je}*FE7GOf2=eP9Oi%R+Od@zX?UP>yi!73?+H{=~V{azB(
m~%xxo80+IIFf}$)_gd#CH>j$4WC0A6(vo=7;;9Af;sL2mi1Kkck0oB-U#<qR9}0wP6>49tVLlv)AS&Dc^-C!7B}GJDK=Ih;eouc
B32rmpVz<HZ!fAub%ri1lu8gHr~?=hg-D~F9#Vwk2MH1E0L2OLs<X{_ZY6UWU;T}dz4)0he?)<uoz!mLgsQHMWJ%Js-2MygU9Ab(
EP!e;69;m%rmjwQJuU<k`AV<D?_;~J3r)OZseBd(b84Q>-IBz~6+8lxYXaa{g!GjjXd7+)cOD1;Y82iyClthX)`5GtnDws`d%o5k
-><3Ct>)W9xN#Tfwn`56&bA5c(gkUxQx>PU?dr22ue@!OaQuImA~{N^TZbme8pPn)v=u!6l^SHUHNizRp#(niQ<}AwaDdYFLlTH!
%z(tMBXFDh9;Bd7n4H60;6aE_XK8v{-nGH(rBSN`bF%KIoDc)}Zv&^%{pa&Ly7J!$Wa}hZUwF+tQ0Iz3nB^S%VyP9#V_t?wU4g7)
@%-`*rJw6JC3;+L^~-ZNs)W!mO30ljnr=wyU$=uKtq4ORTu>Vy^+k+ZFeI6b!qZk;g%ZYd-P!Kkk;hARe#i`qEkPE&kHMMiJey7k
<HZO5)Bu3Eynepz4BSa(4Zhd5D=5tU7d2)(KQ(|q3db>&L(Vg3xTO<+W&W3R2*78YD}5+O+vi^(J`ZPy_xh27W?+aEOuF1K<mCy8
Az0zzMitLy_oq>oL~zCbs^<s)V`ez+7BC;7)WR|AtQV<u<yurtN~G&F|G5;F@^q<;4rMtNLb%M(ZZvGndVGBcW$^)s4m!W%`r^J|
`0(?z0>O{gGxphD9(-ay<u=t(&R*ti-3i_-9ph`})M%N$tb?qc5b*=@+aMNf<8CT#=m_&WW*oSFGHM}BpIqaeZul~u35P_HJMv(E
0jpY^9?@hGVum<g>U1nYhaQy^qt$*Mfw5Sgw+f%4Pll@7wm5!TLgmy%Z$A>|SMDk%vP}o}2|sLixktML*5#LsF)xgeQ~Y+s*C)vs
ZTyybJ?H?o2q2%W5g$s#R_J8kv2;z%OYr$*KI#32jrV+DmgFY%D2-{z=kLEChSaUEl`}p7^yx2HQXMsU;*CWMyw(xOktF_inX4}8
VQcjiLU}7Qlc*8iB0Di2r<cc1q~CxrVlDLY2!n4b-Iyyx@N*+lp1>13v(K1IR_G!Aehi8la6Y+)DE2x;3lRYx0%rCY8co6r*9P(n
eD=&qIL9<HC_Dm=sqraWRMKM?2NrH&8?0_+7d722pkkxMICLFj|2y|Mv~D|ZL$xrW7RkRt9-)JJouQ0;#42fiwFila#zR(6pmlL^
{*@Nqop?>>FNG6@&jH1^V+^}GoKZ0ojvrq}jhH5hDA-X<>Se2rBLq7<?(=<+0ew6a(mgeq1V^t#5tj3-l-doxjgSX2A0AY^_2wn@
b0?8(oxdm`(V^C>wlb_5Or2Pxfg0{Bs%ZgWzTsQyU=dpF#Ov-jG6T05*_*|w4G8;<VNnT`7Zn)Tlw5DRm;v6rqg5;HHL*i93NaSK
@WQnk$Z?^?l?8{`Z8DbP(#L2|=cScSxVUsnYcB^X^=9<B9Sp8d;@;GU?K<yt<t!H&KtA!k8n()a$kN=u==f08YKPP26gYs{!a$Vc
q8JG?8tCs+a2D99ya`hJU@AA)LzsA#Nv0JU4L@XZ+r`(lhm%?QUvZ7mj4fD-9I}^L@b9Yacm3l9VeB&y4X~F$^YiAj={(-~0-BZ|
qYDG%Y=q$`Y?&xh02sclTH7^>6~kgk!PZvlapm0y{JJ?DThuwS991Z;^&rtdoLIQsvyC<efTK~G`ZD>;<NJ8vo+@*3#}RqOkpTpb
aK%`+4w5^k3VIugj?Yf8%Qb^n(W-JW;D0DQ#)AHyp$BigZ6v`asN*c4aZsP~9(sc`wl@*cyMbyh*<VksF__sm1kR<xiz{8hrV*Xr
`YF62wg_{7)8Q=c8GF-Ka>_gIj>AxA_*;ltIbKl`?-!U%R;V17HlFxl=Hz_moHxDEYK)28KM3)ooDiA&q1s`ITokV$ITGR~*HeAD
#tWoL={K~OPJW!e?Y6VVS7p3R!x%+pLK`C1N)#EG0+;a{z2u->fI6)6NRQ=Wt_SkGBQ+_m-WptMQfi39+ngZ#tQl2SrgUu58X=s*
?QCVL)~YMt^;wAlqgG7+10wc~6O=BbI0SxDX4=DUjazC|`$enbG?IAb8DFz-l}}5R_#Jm5R=pH|wS|N0l{F$w$M)OZuRpb!bHRyf
diMK;v+2|q*qggf^b_<3dP`yapK6dEhB~cU-2a;~5q6MG_V`M@sm6u;!yP%T>k%r8P5YCCn#=u;{MfVgVzae`HpS_jR5JbON~p2k
PX_z3DE<o)+pd;w@49|x#m3svB5AOVS|9en_(P}a6Y~Oo)kGi@Gx|g`kgnJ-910lV$~g*`wwFAJ6z?zZ?YQ%qviKIC7!S!?4Q2vL
R&{j9K1SwfZJgWA3xoB1vIg@HsHl#u5>IuZs0tU);W-d!S=W86f;H$`#HeZkA8zykqWZknrc2y2W%u#Ai}NeUYrt|gX9c_;Rr80$
mZMd_zq=L$ZJEbW!134Yz$c>7<Fz<hr$4lBhI~K{e1x(GdtNd0zzole3-^uF%sfF{Ihg>)l%o-!@UpfwFpz@?g2p^ccWq5eM!4pO
{QqMF-ZCDdcO%zy(<cPxg*Z)l>K?p}-WMwWx_dt`U9K5rtP_1g3Ok{aOtq}xw!?%&dB=w%45@pxsCO=DY9r9>fNM*oY#m={o!1fo
9Of`MyDc2|yBLdN0MKmt@TEA~@V>f^!ERev!nB(}BY=)*5<(%7VDe{T#jWjnNdi=_<)9xKjq8r$?t7)%s@`#Q7*7bc)NmVgv{D4i
7CL6k=u-@yS|T8cjk;~7k2D{n&>|<)MN-&~Syy+~Fluu%3eZNVGCs{bZ7DV!Zd0d-XLSpotY{EO!`WFk8B3<uFkeW4M?Q|wa2L!;
zV9KB4$Tq2VwP;*cq8q5o=~iQoR^%}-pOGZg0!d7Hq1jt5DM&U&!+7HjH*SzpZB{mnXZW@w}-H+Tp41m;jTt1DO?N`nj%~Q_z?Dd
V~RYu<RTL}eujn2Munthi>?Que@L_D!f+Lvm<GUVw6W+@lOJ4mpWO}Z!hfHLhonp&$dMO#k+mQJ5=Y)GDrzq{=9iHQ=lc#x!_EB0
)a~J0Z^4so2JM!E7oLWzm<YaKwa4G@qpEy(33lACOkmIebLU?)VkKb>UW98WUCP;;AfD&4`aP1`t3dfIXC|On_r`Nwz8>FQ&Ts5d
AWQ-SY1Ls$(|u~>w&(_u!{k}_tO*KBzKXHALqu5>`S#r4X*PtwD?}*Op1?#3Y=g})L(Ch$KE=LqXp2(~cyimy=Mt4{02Oe)XW{kW
kNA)@U(fdtikJc*b-aO~+miY4_wDDMVn?kP+B$GFj{{>c28-DyPR#uxK+Q@oOpE3za_I!O88A#ot*>cAcqClY)9xDj&tRarAh}e|
XQ@q+wSbH{E*sX0IPFMz_W5K&YKDKO5o)w6xR@&mly=a}5eW><02Gv=Sz5=7&D_A-BDvZV1tWf|!)c)>PJgXZx<7@;WWLA(9cX@j
#{0B(TBQoOLQ+HG?0hQ~mWhufkKOet8WwFk0w9zO+@XWbJcq4jeVC82cbwwk_~RCi1zkBf6J#+=+twuW-<2-l6=W_(O`;B7uWZ_~
?lV^+-iZRn0gg!S@Q?;5311MaZ9JmYH^(n~$n65Of4t?TOxc;mA4rbhS0uN9(?%vd?nJ-94m$S;-1E5+St7qos*#4PB4snp0>rcp
cXGW<X)P<mF>^<|`;LNZL`D)_O^tNI$LjZMz35Hl?{M#9QoeU|E{9*zVzLB}BErnVGR+jrE}v7>t~g#I4X&Z!#std0u=yqWv+?e;
L&S|J2RA5*6undoFeLaFX(qm#(8v;`44~d#FPT;In?p;8MoTu1EXUa?F(mv}2uPl*QqT?-?PPt%P!DfFc4zT;;K?iVAl|u5clh&}
<$X?f2ck9gYFqSo>D0$^T_kYEw51_<K8V^{=-UIwu}MNQD+8y$CE1;?&V$!_0NXUdysjiJwMW`y0^xzP!%36pbD7$sc)PNfGQz+5
I{NxiHDAz4pMvuD_buKauu}**FwF_Q6W!k#r%Mg1$jk_)<VYXnLe;o8wjSuWCtDum(UG0#3n@0BmWzv2<gG|c`RC<W3|r@8_3cQ2
Ef5#NPz1})Pw#}7UJG)A-BX$%)j*`1O|3~5_SEL5JrUu)0_t}91N^$5SOBRfg!DcQD&#*q4RQ;yN1H!c#!MCIMSFMsK6Pk?kwSg#
Kd!~C7Lq>#|E}JA$x?G2>+9wCU9G5kNVxLNG_|{kLAxcHj&2`#S;E}3mT;v!uaox=kp#1LCZ>;_C}u3VGIP>8e$u)?7&4@Se&kP0
?Pfp%IR%-IEZG;#N)l3O@8jIf(iW&*6N}ipIVF|FLn$Xm42azb$m4AOE83C9G6|z1k4E3<%C~XNnFR*+ZHJl$RQjgWGh08PI95~!
nH0$X0ki@mz^&_7A@!5+OR?xsl=9ci*1Vb@C!ilbDNi)r3z^`}N1>5tHpFJVGW1T9`+N-La6XK3mu^iJ2tYcQfp8J>PH(j!5~DG&
XZmctnsiGZ)WaE-SPp~J#A<Ua&k^4lm0Zp;$&BB~!tWahfWU*RdIuQ~-fW`F3>_CQ@jxMqK*uG6qA|Dl_o7I8t;I|qNJ9AL)FmR*
KaQJ{_>1#{?P+3LNr_Uq1wOP;7Vct@fL9IX!ii}`*5de}%B!|dmy>V&%Bce;YvDe2wCamE)8IPG`b~V-sMdZ9l`nW6KC==^hf@qb
lVZWOUz&cPhqU?<7}D#ZIwZA%*9lZt;-3O>J+P>$5zmQwpW?gW;jM%H_8qW%2f*5Rvv%&fB18@UE7uR0pFmI0`7SNijJ;rIqaWSl
CBLy2H<B|-ex&038L1^!-_b=sGm;u95CB24qkk8$OWXpV3??|k{HAWxf*7`evTQmYqvVuD`fSQ>zl^-|uE%Z%?`lotf93Ai;6YH(
sAnQGV-k7Qq5z&f_M)(4EMw8U)qmCptj?>|?A*g0Frx|?590M&nwgv6c3#S+_@~Jv0iPE+wi^LN8zUK`y9mNYGkf*y1V%T)I_!rW
Qzx&fAbjkLEv5R^(R2lPe$di>tA?s`Qtap!cVx8M9-;PG8q-_C<<e*5b({8=V2^ZI7Ck)YsO*z#NY()ns}JI2uAeUeudxxFVuLsj
x$h9P!KqsJlX$0-W&79|dPv6gx}R8>7C_nDHgzqm41^;*eE@|4g;L}FdHhewBE<3y(W_AK1H94aWlw*NfLZPc_%kIrreGA{N>KZD
-mDB$44jOsv7Y4gen2!dhNlW<7hF7+c`(_H`S|Uyh<b-IaiaXz=gv%79@}$(d~#CcRj2RYEi#($(~8{76#c%xf8c3}KWMzijh>W$
i(*;kQ%5Lpb;$a_+;B*EFaTY6D9`>p!ippMfh;=zkD0A*J~izBT$nOxu^GCP#B0@h%pX@0ePZSb*BwWWp8Zif`~y8Zn(IiRwo5_a
VrMF={_(xS6@L&-jb?c95|4y1|6ukf<TW+5lb6nYiqxK>a>T{jZeev-iV41PEo$n!({1&IP=_YKh+W>K^dy@;?aLXQtc>4J)E!iq
-gPzmklq}l{wfa%+nffU91;ZL*6LhiaCf~@lWVI@YHwcsqYqN3aOnfirg5SQ>Oao5ufg`Y=hfwn2^LXdB~%6K`1o~GTy_#2vClRq
A?UgQho`OFtm}FU6WOWcP7jN)4PX1e5IHl1HR9RAC4<pB$W1+l$oL4nu1yswJYuB>g&pfMjd#sqYM)J^978b*?0)+^w@YPH_7zF~
qUCxqc-EP+JBLv6y7vJR=rwL#)Exf<CTyIS-j~_c0)T~mD6f-Z#9-3C7yp!2EKkhA)&ixVWBUocp~D|=q34onJ14;H8aikQq=|6K
>6$(2;xc8d3V4TLo{iI%^})Ix&aToVl~PLLF;-`*#n8#MNX0e&8|3dmga<>P7Uu14Y_&2dF~~<LYt31zG3%bC9i#>%Fk3J%!u}gF
fN1zyYTmCH;zX1~fQE;Fk^aJ=vsXw<qKM-?dM-;Um6o<LD@`2f*E{@Ai`tf^aaECfK9)RTOybiV+Sbk>U}FXH41=#@<o^AoP9+Ky
Tn<r&@@?+11a9C`>80Pr$Qb4t&bJ=UW?D%7>s*eCr9d<d*V}HVo|X8UE_u7?39nCb&!iAr@4ja9;y$+>T*2i=(@CH-C_u8#gqIob
49qC^W?f+qbAoRm#9z~cVoC>lmQH$=l7u0>_W%VbEOT2(^OjxnlvA;u*WxtzCQJ;iQ#X>rZ6wA=b9Wg3OA|hEMFtA`ptd%8Tj{f5
m_7|OrdYGkD?*$hI#wK<`TZ8K(Tp>^L{ot)-x~)QBMQa^Cv})5+N#p#5-_{fR^VAMW8>=fg_+6P``v=BU5bxDLI#Js{X2`D6D^$s
p0u>X)w@h5R?PxA(G5+MT*wdWHc*2+EKGHPN-l&qD2iqiZ&kHAdt_YTQ}u(58w;$f-0&nA2rEZWsd&(9qq!-Ff6rH6RHo3p;chfA
K;1Da$(+@+gr#FOimGW68A{9R8_1kHHXblIJ_rz5)}(Q=tk3)qUBh$#5kSac!`O3P8EQO_n49uiiUB5}&i{F~MjiwfLR2t%>c$I%
2>dz29Pb4e*Nz_a01AvT?=Kwt*=$$0^Jlspg62NJ_G#MN>9VqE;u!;~op9=aAV$A9mxdx|An6sMcPJ+wjRE=F6xr>-QNhK4f}`pa
k973!s7J=bF^}E1`WvT=KiZaL_{1%qr+P(V0ul|<TicjwDU0R3n&d=Dmza7ir{X8I{@Al!@LK3%N50jOSs@O;U8@x*4m>$lHKV3@
^d**LQ7B}_e_O|t1TBjTjFV#|n$zBZLsDBFkth2*dj;-KVEorTs$0G$07(Y2>wuAy+aYFt=E2lNVfbuwNqM?>WWmQ}G%0-9y5SP=
W<lbp{5cn+sMqh|)4T=(379MT%tuwq@7DsAyUU!&L&@Fv_R6*HD<&X(*Oen|QOUQ{v%1C|={II6f!Efrjw>&WM3DXEdrk;!)rI@b
10udgv#vu`HYix2jNsxG^YL^qZsU}kVD%ERgB2!}*lmpZXx<KTilVBz>iVGCASUC<8XXmG$*!6nEIzmWu7Pa#@A!F1+42aK6acmh
LTkevKQ|6+xn{H!hoQa+wQ~~;+oaEq@~v+L^1)7FsW3MKWxa^&d@liem7|!Fv8j=~kS3>wkFH#7sr$opkIF$gVx3qy7hm07ps!|N
qM^s<Rq&Rmxs<yFhkxEtv@9LqU9#rmL4~y4Hk7^Uel1Ty6WBS|1hLX>o&nF6h-@sna}}kIcbfVhT+B&Vh!}s{&pf9sy3_*z`V4i!
(cb*Nx0z693UTR7^U_-ehk+aFl^qCXVF&W-^RfR&$n{*J(#7=(t$(pHVWpdbY@vW#3>UPtBZWqJM2^>_c;~wv3p>e>rKsxpyt<8(
BEFg@XlU2_BB%m#CfGl&+xSiSRS$1y*pB(QzX30NSip#c>Y*2kR^L{eDz#z5{M3mFkSoRm-qb2SzQz40ttHowX5zg!fwJN=Wv~Ax
D)qm9TOZrE#}<x(Z&(Ke;+RvUesF^^qKMS~C<JwF&o;*Et~{qQd2(Oth&QP{Yk)NnhG1X4i_4bIp^pYra~KnjVjrtUMXd2CTK&}s
wvGs;*Bdt9EX7{A()&xySzX}TP52ec4WP4TX`O}id)XR6O2$-8&CBI|iZF=NSW6)_9Q$DH#^nk%z@G#XCQ7Wz-158BLbHl$7fk#Y
!D<Q)@KI|*kDyt<O=a`1|50U`m2$}E?o*JcC=*gNL-8l$r-+6kxNRS`DXD+<J;i<KTRdYarKGnxx}`#i50rg>z@LM*{N0dWo&c|#
o(A>l5Sdv6J+;IR;gKJn$zGJ>Tn>Z%Bg8sKAkJjb^{jK1aG$=oKnyyNxzWZV<gJ>GFV&`@HeN2iDQz=|bs=3O4%Oms&fMF<*iZK|
ePx~edegmm7r-DAQn$d~xoakI+Zqwwr()H%Q%SS+q_q|eZa8vumv4FS!Ji<pc@Fr41-z3IHP>E&ahQ+^X2!gYHbXlYDF-ysT7LNu
5h@>Ws98Wz{2H;tQcAn(84O@AP9Q?yAIA5>)C6|jm`#m|eew@gqh_qClRf?DY1eDuB{K+h1S`C)RpB5;@Upi?--B_I337HGz=LA_
Q{Z5NoIHH*9drB>jvnvWe*5hRIvA~<ia3cEH--BA2V_8~EW~mSGCI?R6iP3;j)X>OQGPO5Y9%APE}7oUl#FP?Xb$QSizxE^k2e{M
<f=F%0_4hK4(Gg>o%I!)0TNdLV3ka|*h_FBIR7`CnBkd=uI8!$Tj@aSN*P_ZFzL4;Kq9|a2>AgzOm~2j(nh`iaAA5fCVBlLQH8}9
IMVpF=ILIAV`NgPt+8*C+?T$J#fV^eKC{5)m`iV~#IT?@0hAu||CfWpScM2}E0|57rAobk-ljDfdNt_0T0g+G0dRuLV^w<cQ=8%*
Imhnu1O7O6UISAGV`X1yX+f}+051Cnyo!EE3ir|Im!GbE1)#3z4VEn&(jdkb`Y6^c1o@(#%a*^ZEunSL1o=|#+E^nP!NNPIu|riG
@^WxY6xbNiq6B#}xVg{ezfH!zI$}*1hDIxyE)Qq5ZKEx-cBxmJG=4#XPH7KO)oo>`q%Tky_h-M*0TG=wMahEpA2Q}J<I9DW5y~1-
E7Sl_^61*|YCXw}-#Mi;Vp0_&cm_SwN_MzD|9+)Z6V-)|Cm-{cO8I&|0=>p^?X@Gk!!@#FsH&otl-&MN%pzr+>Pw5sRkJ8wIbSM~
>yO+%RYQqePHChEMbN=u#vxGhsBKmCBh4V6%w^3N4Zku1-67abx5KQe&=>&Z)jkh&8zGWMl$y+O`fKA$^i8!{3ua-~bv6SxV`<{K
=}I^=Y;_IU6pM!nKGL38NOoI<1R$5t32*=HAnnjL53e3dX?iF<l`9944<&YM<iO*cf+JH-6j%4zCMz-$d7(1nAjvX?>SFi4)jq58
Jhx;0lgRO8f_%(56_9aS0BQ2OSh6({l#;;BB|{9P5KN~&h>w1)&WuZ~HFgW5%~^c$*r`uTk<%;c4_&4mv7R7UOIHV(norzQ`K4{#
XcEjIgAomp8a=sf3F<5{m`X%apdto#juoaMd{}Woj@T%K4*eD{k7^I2aydCrIrQm#WWHGcW~>9Fx#aQ#Ub$wxZv@4C$-0Q{RqKUN
^0H!@U{zRus&eOhsmN71A^<J@{3jz8;uxe|XJs51afz>|ov!Yy{ZQQTupeRUc&lf*X>F?Co)_A4I-3g*{BYwK?3z<KpR|xjia0dM
b;CIhKh}PDsFiQ2SWPkLx&5V%PYy96{#ow=f2Y2QSvWx<_CE7rp-NGo`amM%aX9P>c~fiY0m%Vd>ly_VsE5kO8W6Zg7<K45d&Vfv
Aoww(qct~&6yl%Bi4UORB(RWO#X|+Tf;1!A0;p(I<$Ra%H!5SE=on9Z)`jb+Jz@$<bJv0RoAonB98B;ClfRB43f((ezz3%i;9Cxz
N5%}_p~-GIwo{-e#<SfgPY)=Sr>5O#>>1%QXF@gf54>;w69OHVX^2~GTzzg!&IRrJ!V#_PiD{0&a@E9sesn`*a=z^H50=tT(uLd2
MJqWOI-Y6Iv|_jHrhSk*qAF~xK|DMRQ?mig7&r?I1g8$EMb0+p_tqm`F<gd5he+$lLM`D$8jbm!O21cfxKp>5wz0Y+tam1lXp{F5
?Sw5weeUtMf20#0XPRBRZ{p5c^5q-dkI%3O$^}N{A6c0AvW*JpV;A#vv{F~JLp>RG+<udorFP)(eRyH+|Hl597_P|;cK~XJHUFMY
`w!{+6F}QmIEYcuTm%jUMi8sNeb~|GY$Y@gHa4A5D4f}xnQ{*T>b3=<1rV+!?K!1;vl7Yv4Gre){s3t05Awji7+XmF1rrLMvLaNQ
@Nnh7lC$ZqQb`E*oNIFNTXKlsKu6fydHjAro@|jV_qbVWP#8#M#p$oE$`BD<n0u&!{=q|(^I5*!h3w_ZNCWG>b}iw0Y0nN?>qW~O
<@}}~a0e6duiZqB9XlZTMnq>o!r2p|0vYxz$VJcAD}f{OiT(+<cXlBD>7o{|iXpn*Gb3!p7|XZszUpPnn9H_c^-Oigp7VnHtqpsA
ay0d!R~Xl{NeTAH;j0Xfi+DJo|0PPKE$V~-^vKPvbT)cO!jhxhkmC!>Pc=GL76;j2BHRRq!|`Xq#;fgU-+UGu?rwLK!~edhQy$zL
E#Ox{Yem?><MwRN@IRv8&^EC%3^j8M0-&&rxvr0Cm;N=`b(zV@3aUsvyAH;R4HEe<@30h1C$lS=nO23FyslU4YWhA=FZ98t!I2M!
n=xa2%5*C$@&4t!_CI6&i<d^MvP$~1EVO=FuBR;WN&ID#{~K~2Bqd(&TwL*nf!c)$4QpshEIXlo-*m~*0hT*@S-}R-%q6(n^%%yD
RzN8q%L+o{xR(<A)+Bb}!HFUlR*adW_e@vU$xwPRkl9G;EYb#MJJoe_JsQL_8m!J2C7fZ7T?CUj$aPgeN1vmFPufAVitQ=r3QQo)
9ZlaRAZYsQ`K`shoS-C{zCY7;707FM6=1s}mqhqk{6RX>M8ADAtIzc2vx>79BM5Wib~nPh3h8*U-e#=d#I09Q8jK>a{~;^KVjuA+
(<Gu%ZyH`!n2A9Ec$=ldmrOU_l+D$b*~|Ei9=)IA;19sbPmi;@>x3ZfZoTx<n+TCP+fG<m8A$=%e8rvkb`%E*ykevbC-G>fvA937
Ys@%Tvj8vPdIpSX&~=K{Y9mde=qaYAtQR<H?LKC5*8+J{Vdo(R_Nm$A7$_Rfc$TQ8ogwTDLx>>$+<HfhBtOX%snGk63iFB%$)?Lo
Kn2{a0?TyH@}*QfX&g|6$o4ZT@E1fSHIzz|h@>bBQn<wv`qqe}SMZU4W8nvK#4csV=_AFW>sype8$(68#PfMZ_}ul$_rQ99q7|k;
=U`g`DFnH(dY2~4JIMOP5n_#Gi@@jD0|3m-H1HN|YaZR!HqMh<&TI_3!w&a%e(aO^G=r2N+S?-_w_i>4iSZz*$B`}}c<wpd<S(E*
ZxGHWK`-QAX2VvSA4kk2^3n_u!6l85t}gOu8--DB=(i0AoJ!GMBr5sR5EJORY=BuC$=paRFEPaqO9QNAHL>U}Dmrp+5G{3Lp45Pj
<IV@~?<f?(=hxDJaMrY}Q}vv!Jk&ydo`bd(8P=Ngn!o{f4HHAk|91e0y$@)jvwoj<Lv2iap?fw2j2luIQK8Kg@}fqN(Ao4X(H;(R
HXB@hG!5<XR;!7hdcc)-rAg{aF6Hi<I@Ylm9{W09T{AgjPDR!F_PY6Jod)+8+)IGZZcNz`kRi9Ntl=Nq^{cqYqjF=YfuCNjFd1Pp
NwBjr=i%P>REs48ieK&fG^^b`8R~5l$Bi&5xvdHiK$tgl3jX~!O;n5c3htf|uEEirhu(g1Jual!vI;Dj1%?i_4d}or0c3H|8NEDE
#=#7RI^Q#e>X0O%)cQZ*<BqmppRmjOok)XJ0(;V%e;w5S9bfWgpxu+R{-c_p`>eY9ISodFPq>hY42KWi0QI(Sx4|mZm!*JYG3ncl
Kcl-{o#I_-`tJAD?qa5#od>B>^Ktb3*O+e|)WnFqN5TYVh+@OG08I}<{~cy~2B7mqLs@~<R@K{x`#~=yvDw#8)wSBvLZ0@F)(nN6
(na;s^te4JaL(p3F~9k9FQH%vFcs(nyJ_b&>}bXPzDwbkmF^;ek>92B6=23RghG_|9XMrBsFZa>gQ;%ywT(<hU6V@J3Oh8d={Cpl
l~yT@OohtmybJhf-TTphj9lKIsyZ$B&%ul(h!CokIzzof5()v3VZaWG6tI!^uW`h*Or@y*_A9t$&cZ;WGL^Gj%TJEcHVw9bJq8*e
!SENOc#OollOMe$P1m9wfoS1vbGMS5E4vuBs{b3|u#v|F&PG07=7eWJk&)MClm5e07rWgb^*#l+Uby2u<YKQDvBu~!ZbnT2Ymp~C
YIHsZ&yyt~yJ6Ea$tyHn^dI3Drddh@H@HV7|8zo~dalYuM{ktMKME9YSOi|OJaR`HD2lkLMpO>Vj$EHe1XMkoJ+vOj*&p8q^uK_z
7`z3#<6QFOPql>=H!;Z2343kHHgwl>IPx`L2ngr_fF}l2x9^SejyB3^Rb((D$rUvV&9#}cexO3sIa8#;<{}q-9fqH9TU&52;{X=n
`|0zwrHSK}fXXwAm|c0y-LV?l3dgU0I$<nh49pA(6!e|?CkspCFnW+`kg6I($AnfbK*I%3#*!Kzz}kQxpuY$weS|iL6e;>dGTD(k
`m6}pX3OgIi)M?FyCMpF%pf;oc73Iog(e)+UCm4>N=9l);&fs$I%%e6RJ7Lak^0qlMUrF$v&rs3A{8CJ1z}kL%aB&^u&qV7<TS!f
H&}NvrIw+Ai^2*^duXhA#$9L>QN4g*Aq8!jyz-{nX7Gg3Gi1F(^Ck>2bCc%ewZ50V5C6Ap8^7;C)gHnfsIZp2Vs1Rgyhq$@xjmBx
f*P1rYbfc|8_!JhKHo7gcPhed<U~x<Bi+k<zlwe+Q-wC~O3!Ln=0S=@S+Q2AT#7EuS{0d`Ls6hS=}I7687Xo~{IK582c3nYhrKug
d^LYW9oP5>xD?8NG+#gm`nBp2ttARP^11_5!<YRdbVf6!qu_YW<+~(#w)-Q*&jC-Qg-J^ulcwkL|9U*Rs8q`Y9i``;x8qo^d~gT#
Ah)vp(|lbn^ma*QC1-x4fF$wQYb(C_QL1S-AF1X`W4g$KlIcW&&^$MnQ0#9p`?vrQ4LU{Nbo-axSwdXMwe(1iRzRy5pW!;cG!-A)
%*M%}P}&L=e0Qk+r>lN;D9s>aS_L$U52IzQHZKgtegv!>cmufD5V$~Z%!9fINA$!akg1$wnuI^`JQN#2gX7=N?}H^g7rSYdI1i2{
{USQYmTwCpl*0xj=Lp4{d*plGPF_P*o;TM1%2VL%#2{%mjhBzczQQHXyI#gqS;lqZ4RY*Wx6EjlF#v2ps|UI#_i&1ps+xKs5L<N!
m*eP}h3BVeqvUP-Yc$d*ru5~^C=RscZ`5t8!5R4azhV%EtpFM9!XnHU#xA>Q=cf2`J2FFnl)e|!=|XqmFzYa76m+#_$7tk)iVxP$
GAq_QpLCqo2DBm)<d#v02Y&i1^8Obb3%iE3hUZ;@+hbPAU2CDa^<6rJhfCrQlGB@dp%`fCC!RN^UqDbqy-Isg+mY;CHU=wN<fyUz
-Yh}(ZGJtbl#_~r_YK{#w%w;0xnX?8Evq9b5Nfc{06E@tevz2+`KlibxQo8FmFBE&R@|N7l7wL>0xib_WHGUo&;J~?8UoThNXwVW
J%ms*Zly>p=GQRtu4LpFLA@}u2d{j60`<Rhkq5N*+-VrCW9W<{5-?jXBD(FxI~M7PAPY}no4*(lLxM`SR^sAapGNoX{-Rzo(Ys}q
>sP8fO*)-?EE!rTHB>OLy_QP0Xa+dt9><>AXkOn`Lm%C>lQicxQlo2V9tj)~AH>En@m4q#L|iY56=d^P>^%4Quc`1-#ViVZt0kBw
82*7|{C(5&13XQ1C|!H22e<P_bk_mFe09<yYMieztG^2@k9g>dxO>X320blUSr$rjkdK}LSP8-3cR;C2sruxLsI|NCkrwXpc@hoq
wOu$qkT9W{qV5@scb_q-wZ!$jNTzUsRCgM58BE@_9VpJTo&ObR(LmdV(=Vpnp&+cTM>ftdjOOoAAd$7l)yk(LX*x9V>8YsWV0EL;
gEpL%Vr7<(6H3oU5qV{yl)mnH<v2aFaEL8?+A4;fB@Y;-v)=LT^|w{{HAsjHG-Ud}{6S3tZ-TNf8ekMTR+LK6CfKV1=6VyvXH1;y
KNq)BkV~36eO|cezRM2&k~i4)O{C*{>9#{t?tZCH8+qWWUf@5DYZ$ie3TbNxWq~b|(XYDzIe>CK%UZ7tI)&e7d{?B@20Zwh<m~}F
aui)03?1Rl?pQi%PGt99DM|#T-og<KX2Su$XkJK5IM`Fvo5gauWFN6wUQrC#US5FDdbY#bbgT!;7~Sm^c{Fm;6Y+y(Up{!0&PNzL
5k3|Y+15hBnjMlEiQYV-^nG@#jlTcU1?G<s84^lDf5cn@<JzmPI!Khknj)S<TZ(txR#`2N$m2bXutn!Tn?lQ3ZPtJ#wYgi{mOFX4
7!$e_f0Q1KRctG*X}@HjH`eMyHWVYoa!?sUj;!61|4a>#9X7G-IhHN@FrOmJSVgVbTz(KZwA1>Ug4F`lS10)+U2IutqG}oAz|e5>
>uCl8DOaS#u~LU~n8<8u@jTndJj9O+5eNz9Ar+Uy@>^1-;!b!Kx?T8oLC_zBMJk&vAe%L~5YH-z2DwnEyW>GVN3MQs-lC|L?LZ<~
sGQ4x<IK&=wr2v4Nqch*cZ98^K@@3Gj|~8=)#?w=(i;uZS5}0qB8|a?9?O~G;rC}$#cAb@P)enw?0L0;yj-uR!fspU;LP?Sg$V!G
>f;!`4#U={MU>rc`bbRfo4*}+?*9-Cs<G$XpNCq)ZaV_IiMy>?cjpi!JRPwh<}X5KG%ydA)-VNK4z6IM!Hq|i%<Cg`7)AHJ^-EEL
2*Z*ve+s2lX@#5mkYfZ9k7|3c99G{jdwdwgCBSRozcizZ+W$V}AqnYv{Uta}N;ek|@M)OXxy8GAbgrbUN>yQ2L2{g+Ni27qx>@qZ
JB{O9jj%pCyVfI4Jst5b9T)9G?O9)+{_0l59r#j`SPf7__V&3M?Q>vr>L%?(9Wwt(b@tr;P|JNKo=H_@k^d=IL*z|e4kpHX@W>-A
5JX4xV^YQK=T#5juq2j|V(U4V$(oOR4Hxf-bR@&uCGXnYj~LPglH#2=7Vq$ksSzkv|K+WWXx<AOHDt0vQ|M<NA9M}TevZe`wc#xW
$bWmwdZl&|Zse}dyKrPDWP_34-2Cw{UFB>DakDC;QC0vg$u){b3PYXbe9!4K3zZTCXY}Qp2`tSs`AhDQT(A7VNec5BQ~Mi5?!7ho
zOQWvpCB-3)*RbasfTye?TY~!iA>u5M^!^@(LAhR6hHu1hLy6oi#P*<a%1FzbA8sIN9dLPIk0$hP&4J-jWdfiI`qQ!y1r6@<G}w{
dMqy^(D-aeI?3)H6W^rC1ncMvzr;TW#D9`p@lpn0V1H&eW}V~N)ACJJpmhwssXy1y(fC{AR|enmgejEyK-PacV}4F$v4?{#Qn!*l
E2B;XWu+u=!wJXS#N;Qm0=~?C&2>UL@OYp-wWAqNf;rq4lDK*S+ufGK>R^L21CC0*wDYJN+~EW%b3I|ZlejoHkkUO2B_r#oWF5;b
ZE`hWnb8*1OjTm+W~#Z~gTT-l68x2tn`JzZURxEROiU<Y`TS977N7fWL#2BYSH91uf`g>pv)Y<lYIDmE5{{wZOYnLtypR0-kF1U{
NLZK-`dg98*L&&Ksnkmn98er<dY%5BEdhlB#YK658fOUx-2|iSb?LLoiV6eA3rjeM)e;^Yl*#`Ylv^^fc%}NuL~Qswto=0m44N*E
2!-<Qzbv>7Em=(~i}YQ}nz85p_tLK3(cZuT%6BY30~xt3G8z&-B9Zk+-8MBpFTl7!yrwXMHvxATTXzCV#hwF8NbG4;LVkjYT@=vS
tHH#hwo*#&%PvzsuvcI@5OTo8D}oMt-~U)H19Fb-9dMgVl5p&r2%JGz@CfMmQoskCokEN-ZVZHETdQ-La>}`96xbSXr=nE{Kv5W#
y-Q;(PK8F`O(2Cny5H|ZD_|WM;~AuBWyQK8b}u#bZ2)&2Amu8P+_E4*ZtH!F+gT5H`SU*-N>4o_ncNQpoa5ds(XH2Un7SLlT&$>}
`KS_46Rqn6Q3-85a0X=>^^yY4l7RnMnA}0072q4T^cS8$9#rxvrFfh^>d(Sw#h9v!KIxnjZhxu-2qZ<Z-TKu|+e%a!gxSV@bo_9*
iEB89@EYNIEJi6>5q7R*8!^SZYer?5Ph)(VQCiuV26JF~oWSF{m76*6>}ix~vNBX;02e{AEY2TH$_jqqx?FEtR^OaKZXZg;DMw;v
vuO0S@YNM$u_8Z(&oLM^0!dOcXWe0=cS@b56DSC~<vA%dLpPF22hnG*Nat_+qr+F8mfW{YwQTXV4D@(3tVxi^o~|Fj;lgq3c*0YJ
HTQ=Dxe7V>N4S9{2*Kn>&+<gPFfDBG0QzP8z}tQr$HPul4Qa_GOYU}sFNE^K|F5><57KAwun&U(hGR`iN0~-ej-&8RtmX;Q@=AC-
tKWgDB}iDmpF*`W2==9K{Z<H%cmzfGUZATBgSX_Hm?|rnb-F6OJsRe31JaL6`URE1G(QpMJGZ3mjhYslC;eLpC<C0Iuaco$0su8>
1wR)3KO6|h9dES2-*`JZk4o8azt1jw{xI<;6jCiod4hNp4WqoX=sU>DZ}@pCJA&)jgD3+yo#{Dxuczh17pzl^Ip>ZP92-dBIWfdD
YuDciK5vGw%|+fHj^g9S4vL8P;qVMYe)~NZK#MC2H^pS1bTrDhx<-E?CjTq`@x&G-&_~L$7A$eW1vj?&V)rAxh#qGo4`___0BSU7
?ZnoSr&a3+&(ZO;=@sb8D@JG?=L15T#stR?wreVgX`MH#3SnGsa^H5^0J4{8;jLz{;F{~r0vp;>m0Ehrt&*SmAh&0189?V_ZPX`E
g#R~PhIOCozFlwNvAzU|=-?~%N`}R{szy0mIHdXlxZ<lDW$&BeL8pybQo)|Z&j6a|q9S?7u}Mojjv0SNNu}70vLDQNfH|_vF>E_<
wWJRF0qW*_cy5GG>+kVK@DC9p3DYpS^Rp4}{%AntL|`LL!Mai~Iw-PC?qqCW^!=4V9?2FY_yl7{L&W|mKr@Nn<gn{o_XvB=vs*C-
c7#29?qL?(x4bV?K43Sl(Cx&(pQVz%{1-6fE+>V614@5p6sB<9J<WJCb@RlzL?fXGa%h_QRZ4_I;&}IW5(*SQw#@>BoClh*JjwI)
mJFH>=Kw{9d`P@9YK5PEL0er@K#pz-s)ySSxq)xzSYx3rKt}kV!`@cAf?WVbrj%k_|5VRCl5PcY387D*5-AE}SW7EYztWh$-eRoe
E-F$+u)z;@3hA$uT4v)NVZ7uG(mz@r?zM{ki?x)n!8BwGrQC8L|7CA#{rd6@%E(jbZc4DhWQ*PmzMRD0PVV}bqO8aBj7zLGQ0RAa
PCk=5a<*#=W{N|Sb^8@)cORTwf*cD7TcIA4gtUmSj6~DKl3{WSr#LYwfka=Sbw5n}%%rL;VccWDFgR)YuTRMd*p&L;Hv1uy<0{o!
<M3t4fx4P`D7n21Sp*24)dm!_d47G+LO?nC{uxML`NO#%AGab@1Ujv@pFUdR&j)PW+k@I}hj*(e?6*Az%Ji)rzi0cKhnOp<K^S<Q
_d(KVze;W`^O%)PR->5$>K4}A3N**jK<CvL>zM6M7hb^!zi2w@L2UHkJDqQ6R58E*f82qivy0j#Zg22zOdatO;hphD3V*op#e%If
79~j!;-u&L@yBq}2p?*M>&wHYJTE6bjvwF#0|LB)_(9P3-SJ>*z#9jTIKb^wtUM{<1)Xq?ey06e_$9Er<D0a5*)1d12^fvZM{?|P
+G1>7H)bGNKAiryFMis<a7utxF45Qktu7;t%DGD(N``u#FF)Cl))kjEF;Oy-9vgO1KE!N6yK)r@v0CIwxK-pn*G2tI5_R&fWVGwC
mf7~8Y)UoT*gXESEN{BsCIuu+i@{yf---AHGrR%D1cSE<?+WP$%Q1m>l!|dXiLvbvkiHE?=<{C1nsv`4p*4K^vw|_u?WbRJ`ker5
A_`gT>%8kaq;wU51rmq+QX#DDpYdWpOPjYBP|NvW8fY<~%Sb!dg%g6ckf8p4!gdEve-!RYJ7pi;!kfm>OQ^Yw-H%!K!_OL?^IT^H
kVFw3dTEEj5s(v`pXnMK*=?0ON2dN#Awf~qTnM!huwapmVBeL5=o7IU+*jPVQTAH&$x12eRo?E?pZS$etq6uPGSC*-4Y8d``!Zlg
=6`IOAaa|VkD`mPyRz0p*|+;!*JxjBQE=)VF*QJmn>nKchp}cgw)BDCK9l3pr3-GlUz4DzXtRZjB8Jd?mv5CPB@9w)7?>EjV(4Vo
)5#FxP~9?m;q<BOQC;`dXyzO_ZrRSgwS=2di%OIkRn)lySWzl*K6mw-F^W=V`rg7tj=^s17#SH85iPXa6012)`%~AB@6H_MMe$}c
%aRG9#kx(x<0e(EvZk{B-G$E1E~rFucu(8OFgv@N^ozYGNdj@|!tAD~3U1ab(eyF18qC%RgHO~e`U-6m4ZyfWQ#z8SeUH=LqbQbi
t}m0+FWUQT<(IXUy3jSd3&S4H;?e(yMJ)P3OS#5M!Zxvksp$X~$bgHFo5(t)&ME&E#y!40#2X4hi7>z({PagiOo!qO$dDiCZRd}0
y>VQMCkrM2yQAW=<@}R1`pEif%x}Y2*9B#`IC62xdn)D&tz+kZyq;lSSwuEa@T(XYs_f5Zg2Vnx^)tre?GldY7n};K*Bnv$$r3@S
1JeOlyGB~LvZTIjrhk5_fV}-)rw#$h7Dc0xweu6XK^n?7(oVaT^)|ycqViG<e?fPkeeV4qUpHn9M0cZqG$@6}k^4`dyY}Fvldhv1
4_TGW27ga=hl0?Rk>Mch9<xmM#5M*^d1HYBiC#6L8EF-{jXklmPe;!AFadoGVBPI>ocr1*dNmDFc5*K#ww%(aEMzaMWI!_?rE@FC
*!UswOEwbH;6=3QxITM!OoO<TR)v*4=jb)b)G)QrnI&yP>rkIT%lX_H@GjN1A6a71cZkq1(g>u-YUrEKlp|M$cx9M9vO?(($2rIw
*GN5`7GUFf|4;LP<p~J?&)nU!@*z31++!>o)_WaV^A3^iSle4eBVoGs=`l^H+1NQ)-z}_4SOe?m5ea7Wb0TLPgoB53b?6*cp13=r
R$d<kxQ%4|^Exq(?cFa=wTx{=>MK3(-}T(oOeTe<Qkw-lwRTB%ugOyf$QVDgp_Nv^u-8^1-yTJ+WY$ODQ3;$i3bwejhHqTH=#@4O
QRDtP9K#5Muy3p<nv)faL0iTnkXP(JdB*Gd4!8-^*)}a&5t}UNyo3%B^?B_oLCC`Gb$9hHO|5yj(h;(dmvDp(RX!-V41G<3r*5N`
u%kUnXi(8lZo{$&J7h)~9f1yhH4Qv2EfdB(=Y1DizEcZlmNN@Mx{`op;UFxsaUjxPm!m&^XidJy14hm_da73JdqHIZr<ufS2D;0D
uXfQDXnbhb(p7&6w1g(Q8xaD4X8r<wI9>QbGM`COD*6I|2PB{`2TU(-?ZIpLs97%cC_}pz{&p@0nv0QqwefZlu5p9ocW`#AR8Z>a
N&i6X-Tc|8x5Yp{0obnrSd*_zyZ}9CQdUzl#HubJhLP`U;8uh$Q<ny;hUhKHt^QAQf`=-0ENG#$o)-TOIx(Fhsa#_JGgWNDN8qA?
x~(J;$+h9!t2MyYZ5D&Kqqvg#3fVv(SsE>;N++kF_<3U$#i^W>LzC<>+$V$E)&4VThLHlklO*ElTp>_N`PfxuI6ZNyy#}6<;^z?%
bQHH8l~y>ow%kvN&c=ad2CUf{d}=va{TBoa$391uQbVlHTxTH-f`qvbpqiO1)R^iLZUvJ0Ef62!yLH}L531d)!(^r)B!1xp;Wzc^
g9X0vQ+fhH=Y-?cAQQwCM3!bDLr@7$?|4f$9^}=A<xhP2r%go^a`Uu~iEslx!%%+K1C)Qf6Wl9+kU!0PD!_f`HV!{tDT1!pTm(<;
##@FbD8F)_@6C_9dY?c(g2{>Nc4yK|16j3yc07Qx@7-W1tBxYkoqAN7&s2=a*6e9C_-_rYSW(MZp{ZzT*aZH5?cmuIJYN|G(;365
>X$T?6?S&6==eZJc;|R44G!oSEQq1upX#m0MV7iP9SjDad&{i#cEALB8gqQv-R9?)tOXp~S3cr}{I7`^6PyeHeg>jE=HM&s5v8m$
EB$AlDyf-DOe9;rumES?Cr}K*BH2Sxso;YHB)&M09-kexpqS3xp1pT>#;UT@LK`OcniCnKrB?%)<`_Tm8{?PYt7)DgP&s*-W?j04
pjM)PdT>VL>C3zYx1C0f*Sb@Wb+a}{|4H7GIr$V#!a?Aiji?v8ve(%VmMjRC@Vkf4FI3w<McfoZ&%v#eQ~~YV9WEO$902Evjg@Ik
)zqiJY2X%5-MTU;+iq%={#nC{%StKa+}5^Gw}D8ot9fo3ZGEi2Uc=_39)?{;OQ|I#eH#Z?ZrxDQM}z!2V(z)GnHerRn9+E`qjo|s
F@egbE1CCdz+KN?rJYj|@Xz?wwv&B_cduB2S?YfEL-E~mWYPlYel`2n(9)Nw0|L%o*hL@tNia98Mhi9=<Y@OJ48~b#GwvH~gXf9N
y{Lf7P^lGTAl`d(cJw2J5w{LCNg`zolO>K0^E^7m3W}#-7J@WS{bzUs1<saN!{(;EB28;_SF!LYQ1AwLi7W6q(Zoo=*q4W@(5PZ?
#e%<&*)H?qy3M)~uJ>w$d_*cSlpLmQMeYwMg~kl0JQBq4p4Vtf^3nvu?XTy3=`(-=qSWRz@S7QF=00)uyO!z1zK|e$<WtTCX}Zgv
N#fe=aH4Sc7q<$JSQQyDvxs##-a-n^k_Zg{1}py#bLc*pviauz3qT;$y?gtbiU|8~D6}*<IJ!6oqUR#D16^UzvD@DuJBO>}7Vt81
!@);S#llfT8$&A&zyY55w4+-k5K9tD_A2Gay2|k;+>GH+<{){o^=<N*843o^^Rp#Rc?%*oZCxRW-(Gy%xJDlHPBqa{l(E=Y=a~4-
C`1d@=0EMObW&c(u2i#;EBwizm8b&U4O$#Czn|p}b1D-r9uDK4ch>LXVJ-zhv@4pH_U~k(d8JgmMFp!W*z|IWU)#Z3qO_opB9zLS
pgm)){$O7$qKYNC45w#mIl*JGjvp1+kl7iQ9%M{=zz{v?Q%*ZFUQJ>x>d@$nS=uCwk!^g`8Sys##{Anp_O0VSfm1i4r_~|V!6fM|
KCCn+f(g<g<^urj>VUAH47x`u%MwH#WlulRgoziAxakzz<Jv%w?-F%L7fFppnMDi9;*swP!ZUSsW1KBd+@>JzpT$L!{6J;a^#W*J
>%YcYE3VXGEvB0%QPg#3TMU&6>GodzCmzl=yS>2z;|F~bqTdHT8hP?1fQ%-^k)e(1x*z2I?GpSHb_&pY`WWplb`<Fca^ibL%t5JZ
jSun@&$bQczXe!R;aV7}x7?LTFHELi{Q^>bZ^`bwS5L8w2rg=`KSAFHt5!5eq=O9LK0$)h+RL+{xa52ksqagzma$e18Q`8?eK+>3
DKxQgKoa^=t)<HFDR89zW><oJc1PoY<G)R2Q!KOGA!!qXIjFp5qYV8K5ZxeUnw%}mpR63*IH)@T1TafC=`2d5VVr@0DB+jVYO@wS
AUbJ#zM5KMv1atjiK-|A!<ba)gMC9C)~a2K<X#41Qe&`Sg@r!|j&HpXGhZZRv4{&z`z}61uzv*1C{#gwQ&VYWkj7HZ&4;M9)@9S4
meuQER|8y=Duk1ob((?eZoKTcPQNSGQ;=Si3N^`PBKb*4Gq_%Tn;CK{tf4(lNrBxhD~J_@9;GNT$x<6X2z-UcC+1+U9tl~GRt<Km
&CC=0XYz^5hnL?B1d*R%Pfxyz4n@|Olxk*IJJj}v8aTOAhAtHYPhJWbRgazm)`uWZ0KlTZ!_mh*U~^>1i=vLpsrCQ4t*TPJDM{)*
N&C+(Oq)MzJf(6i50w+yNiORBYg^*-&zL0VBbL9%o_Odmg9lc2G*rO({;VUaAOxJjsI}h8a#@mTL8t31kEUtGJZZYoE&@5tr^?ho
PsILLtQ-m&5PjOaJv7L!<aeffaDQctzOV9WTU-bSOs01wA>=>Sw(Q{=BXVUAzY-+%XK6i@H?&7OqwDHQ$AhNLr<eO2l8~Ont5n0D
Ni$Z0m+>cwVaS<~#f|n!F#-AOM$E{vM2QzdUpeSlLgBliT*gWW(%v&Ds$?>;sR{mmPwU>hOQ+$0Nv{$*!lqsJn^_!T{aK-_)0W@(
Ms1;F-Z{IxUg(8wbtLK;GTid00#}3i^_0pd=aNO&93)wqz;_b0Z0_g@8bvj{jS?BjWGFh8+|3>qyFfjIUY&=~z$Cg~KIoK}?IS4}
3~Zqsu9r;IT=4nKJ-phYU)DE9ThY!JqD}5RgYoAO)7|DS3GingS4p-xhQ+t*$XTcw{R1HiAdn|;Y*M7JoswwAo4`iFG_Ob1LB>N=
z%ZSK#ti96g+c%YRbKq1Vx+t2HuV~eKNarM|BuyDu(_a8inIb*m8fx%jpQ+EumohfmG`t6EG%LwN8a0k|9kKJqc{}H$R{Vy9@3+s
Hfy}~$||+e^-vbYtr1vlQq5s4GH3P3rq~57)bD021x+2Y%qd~xbtMtX%r|F~FsL5;@-ACB@##mH=;b|XH%t=@i>@BwZ?Yl{oFE1-
)*fxz+;<;@RhnNxW<B%P$Ujc~<cj^QmI_4)8gfq?Dnt$t_en<vflyAZJb(w@FZ`*1R>(#K>nIhC&;U5?<9x(1mzI>BQWycw#<~}Z
bBChrlGQZ=9v=alZHmj>S6Yh+`vyPmJX&RaQoIx6Nx?+mEy5cI@4tflk1KiS6L+Gy@eRo&Vj-@Gc&?bUKbPVeIX}Z794EE38Xvkv
!$Ac!=IsQC$2*e*t4<)~8Kpm@yqIsY?9q5eQSeSVOXNK`^I^vcNR86j2CANyum3d2z`s~S92i*rz#*PU8*G;tlu^o92=w{Z?#!Mq
=U&$iV)pnIS7D}($Af(cf0t>Jr)}bBHd-LtVPY*`7?_}nW*4Ki>Zb&^YN<MK6OqVST+3ROsAOg2Ljoi!AcMR%z###b{?TH)b5E^V
ytMvlEq-FPDK(qWxP3&Oo60l3`o*!@#^7dPy*N8}miSG7+3*w7IsZ5{G&w;i*)$#!%DrQSl4k*|zm_tXm{^y9p#wyem=bwDj0-6?
jSeS!_sjj)f^8GOp2C}w-xJGU3_KhYD~mKTk-Hj&u|)5JGaF3=mvVok*dY(toxZ=y6JS5KTY=Ec#Qr${lJ*mp8*XZQSn0;A-CjV-
M|K~_OjX07P67DLCB4-Ss5yUHQb?BW?ON)aQ<z_LW4?6=mYMjL)C<n4h~@MgGR`wvM&e66KMauzo>A%_b+V*PIlq3jII-G^jfB2=
M}hiO)!`v$(XOEDz{Q=GcyxN0elhu>A<LtObXw8#fFa2WJ<r~O8M8K#2F#bd3MZmy6ZwH{*XwpUJaF)&=@w&bDX5T}7(^*)Op#)D
s({uKS_$WwJ62^rb#;0P(KT_Npl9N{ohf$Y-=nJiJnP7RoP~fuRuxueKokua{@+VcVUr*A1`R`+<Ba%DD7xoox}psbP9|e1lZ3)9
0mLM0@`un3>eyz3$j68Q9D45wvKgVIss?9VAgJMjdDBer0t{_)0Uga$PF1BcYmK+l0P1ftS0fPQ#H_D%>m=NRaf+8z@q^BpVugE<
y~Lm<gu#|Pl!Vgb9mYgtjpm~qMWiY@1mN(zbu^>bdFH%;p%*mNBB@z3Q?7p_A!GXGJo6ZRstJFYbb}wykeBVpN7%zBtOVG2a4C?K
IsRu@$#)wky8$MBrwSRtW@5N`_f`=bI$3+AgsgwWdzj}O-KdMT_eSI=t!eWAyPqH|xa#ZVzR(8WlQr<rcLP(Q#FUpIlO0$+>P1N-
n`V!?1s^K=0sGPg#8!%w=`t*Zo88z)xuZ4+pBkjoltB|6-k6%}?4}>{rIstT{HBwAs{4erW1^sYT!q&8t=5(uXIyYXU9xUEL<Rxm
9WmGzdrIpZaj3U%E!g$Qv@Q7yy4pTUxH^Pd<Q^qz)F+F9bBcOo8WfgsTR(m&N?t>Hk^Czw;z7Adk11nhJS#D{pG%@_(>qeG6@Ke@
7J+j-hm(ma{9zIX$l|`)yQa)?V8fa=%nTTyC|gS(f)(>1c^9oTo9STn*DNX5O3_zyP6btk9r<ZrW35lpMGkx1ThqYe%r@%bvd5fy
!vQ0J3cUL2(#(=rk)^7=)=BYsDhsE?y>LD;Kgxo$aT~U%e-HcUi?BMo?>#K;xzpN;3GaS9+k2t7ldeXp+Q7&KqYsoRw>x63BRPM)
qwidB(@rC<!)Bc`UNNc`MIapBaBIZI9vfXIGw_-5YB@GtLnJMu7EWz{U6Sd3G8C`%B`&A>ujl$A3J7{~TYhb<7AQkbXTTNXg&jGV
{FN&O>TQW;U&|bje5nx&83&%;E59y$)zp>^S%`Si>)RCl7G~P`5TeB`K}2Mviqg+}07b6r;@oTG8p#$|g%?>yQ1G>R(&)Y(P!OBd
>VcErB;cBOqU|sRe1BscEE=0pEQ%0IfvIu-z-~wkyOw;%hHP&-hTy0WCld43JHictuY@Q5&6(x%N#;Ul%LY=fz`sRJ%r>H>y3qi%
Mt6f;s!&5Yf335}#&SkMv5~m81|&PlDflL)RI+}=7ncT_BK_Pk07uyPQH+zqY$*wP3MyVStThdjUYfHS?yYEhlTS!}Q^Z8F_>GF3
3E25|4f}!PKj*J4H=~_zo71L~U!3`9;^FHYrv6fInOv(>aD;_?A4dX0ObX2k<H!iHsZ&P%980p_Y}M#2%RAND?!SKbu-Hjpfb5R%
lWLP{mkbVHz538SoELB?ppLSQELRaZfz&!%Zv2BDzc9VDXGj+ilQiQDW?@XS7Yef=U>)Do)&V+MUDijs<>ziQYbZ>B#bIFKGTn*-
f2-f88v^;O$0zbZL7&d1&$Jvr6k<E2!)C<$0sffJLnAyn+K`0SH~HqlsGM%|F&-<qFtIRghL-&m#y$-~x;p5rGFx>R``gPp5W+!Q
?b2M(k0ijm$m-z22&E1oxm_MKq+7k7>QUh&&JQ=F_382L4T_kUnU?*y)Z(@O4!Cb|1Hicy)Y@C#EaGh@iyT5PkN&-H?_%^_kL|($
hDK2<0*WSv7wu?xl<4~LyU}(~vbyBca1E)30AnwioFpuYsIj`0g#tPJ8*z((?%%9UO4(+=9t1ychf(SLnN_JgH8{L4D<Zzx!i1)m
Ho4pT7Zy3hcx8iSPXh$LdjARb;nzj42|a|qff%&DMNF|y$9<`WmFriHH9x#`L8Cbxn!7_kKKoJ3g%2|Ra?6!vrfWk%Q0$h&y36$L
6~mYgnI2}Jrd%&#_}3r1+yfDhaOb6JLvWzzeHo}FZt&vmy;Ulh`6FDae+xQOgLd}wN89GUJ*}WJ{0=jNL*pBtm6a<Vvvki}!xZvA
(}vj@Blsf)*&=*3j%Hba?e0afge&vIrXq^9!UEFg&X<{Ptsi_KFxu_QOFlo2H@3`+UC3WIT@~N((_k*xbv!4J6%~G*X!G5k%)3G&
2$;P`*ttXdVz2k$$&$U@^t3SmL>_%G`kV_->JZep!6PH|Fl;WkM7BOKpL%7VkcMi3xU+6qtfrdUi>Xer#rr$jNUdbkIW`Ge`N#~)
Jdq8a|9HMu^2Q^?%MSUI5hW#L>??XdPC(XCQUpM+?UsR7q(;Y_Pln_`Doe1<JTz>Q4?AeaVJ-$C>~WZJltQI$TNtCB_y8_yR5Uzs
sQgDDXER5seT_L@S8c%@Us=<PfP$GRD?vPEvi0Qc!z&)hQQ(BC%IGCNu~lHRl%u;%DzqVt>z@DN`cMs7Ht1!IfB*mhVBgnc#(72f
00GmZ0f5Q@tt{hzvBYQl0ssI200dcD
""",
"""
{Wp48S^xk9=GL@E0stWa8~^|S5YJf5;8XuZmR$e@XdE=A9k8as9Wn*S0UU=XLtHL?d_r5{!6jA3{ETQXC$W7>uZPVr4-RjikJ7L2
ZZRzlA|foW@mwTt6;clEJKX!|M-b8UgL|KqUIcNVo$0_d@SYUOeKwdl`3R?fG0wYh`&<<|0LI)c6KBxR<ll<;J(H~5g7@h^ntr0^
Y0cprR$;Q}qddFbP-J}aEj_~R&mqOU<(36ym05uNENT+J73N8I&+s}6IsBhDNBa;ed1XY3%6pL!qOhWUgcW<R0{BPZRGc2+>swI|
mQ(3*nxB<dpPGij#8eQGxiTxJiB2Ka9c7{pv_y=g=R#r_e~LB+2s5&flnUcO4$(TDA7X-e5<JIgu-VP`Q+OcYxV#*&FrDZcGx<6v
??0ss$OrD@JNW-eNC=&Gi5Hun270z611x&_4pAS;8!HUI<h}@qlrcjrrX;$SmK)P<kJ%K<azRs?%$h?^y;(7z%LsBzS>-iB5<FKK
N#6GGYudkdCi2$s;>Q}mPt=0fkKPHcLqjbzD=n@G;W(}3+Zwkx2#QiKU=c)QsJw8AI~$&WTahdB!hf0(P%%P{b59Bl5|H!)6m4=2
e7d!M89(LzEhaYZXlGYKq559>w8t6T(Ek|3dLBUj3e)e#;6^?UAd>9fB_rYJo=r1!3`I!qLS^i}Nz{9_<*SX3u5HH|=1EE~apK)t
0=vQW1=dD-o!2at%>Zh0@oR_OEO!MtPc)NA*r)gzh=jFClCfqoq|-A1Mp;d+u-ZI?D}OGY@;^S!-7rUkbRWu^OzNaRapkARubC>q
>c_MI{^_g49xIrrl?eQwJ2XLhJlbu1dzgkW2-Z|IF`JHxk91RzS%%xzrsxXk1GIX-);wk1Rkw{V0Ts+`OwHc>jj3iy-)&gfrBZk;
bV`>#p{rK0Y2G}tZjA4l<U-!CDuuYOjq?wbJ{3vRak!q2M)?4EmEcA#X7e=d_C|&wG5mxT<@#WUyFB%Bpi?g{<RN5$i^0V?4l2Ef
gRLT`kt_BKHoU1<K^(vT4bTi%>8tmEq$jc3qS=WNn*rpwK4%05-iUbhXh9>u0z_|1-zhX*m-I@L2Av8P_1$M8a*sHj|IfMivEk(J
Pp>YbnwG=9QU9z~U4|+EIpBOaed-y;pE1o_$UmNV-F!MNekWtJ(VQz>KbO+%g(>cX4L$NxL5pF3+Z(WR(D~g(e_I!S4UdZ#-wf|d
D>;57LS_w3y4@Z}t+JojI()-gabs*()aj7#$((%fj=gPrf`3P<QvXwk%{Femgwj`inIqaU%1*lSekk2)G1w}He8A$=bjNd)d7Rec
6R?apn`_^AOsgLfP?MO7I@qzal9wXmPk5oW)0_+8Q##!E0~@;VApK@A;ba^)D>ACE30VOagL)AZZ-y4pkUkKvtAH62#4oV*I`Z;w
AWAmG?7mjOWR&L-`wHH<q8TPt4eFX@=k!R<e7)&&N9~ee?1SGYwWxdJ5xalZhkm-;fU5O7nZxTBO@l|Ur@KlC12?toyIcF&7B^fR
HG_y(!)J3e#Nor2P7&S$Ly@m17HYRnO<>Fv?x%lq${#vYS;vOtMh-qxD^hm!0;!}ksvz=1szf0N=<XJNS?!ARj5a9Rn9|k^#4c*6
ky12bo<CJPRnR)DzzhoUDbJlu&Q0s9+kUS1g(C*p?eY$D4XMezW%<8Q7Y}OCJR2pbl03fUNX^W=5HbN;0-e$DrUnd>2p`PvjGHAj
ofc|^ALMyVmd~|A4FRk%G>cQVK4ECO2mf|D$<iek*AyEswIJGA+NPa0an*frPgaT^?IJBjBeCwB#KevmbrJOlmn-pJ+@pMLu?8M8
OtPChs(hK{;s4Zroq+iIzn@A0N=Fz(dil0<*)I{wa7x1T(@6f+8R|nb6c_Kk-8t?zoNbMi+%d@nD}i_t^<Cm(+{w|Y9>bn;Nc9Qf
IcJin=R1n<+-?Zju&EjoW?zLD?y87qIVb1~lL;^1=<s!Bm^X*>khZF#Q(dzm8qF<}Gpqn;8=C_(1&rNEW(t%3v+8`b0n+izfI|x^
*;G51x);{AGfo8x*NT`V5WyH{f<Gmh5hiDxfnq=(r1G;ER<#S5E&K4}A6g%Vw}U>n*LHo5<DG9(3x?b=f2sh*CW}K(==S573VInh
s^v)m@d4p^^P4Z+vr>@Pusv#Yor~u-j}iE`<#qXCUoxkmJ#!?+g_;?d3409cS7(v$c^FVW3ZX-wM%lrlB}fZR;QyC}Y!qh<Fr0O3
0R!V)y6PgYETOHJmslpYGFN??RQqTm+a@Mv+&+vY&=2Q#=kzxo@K(LXbptH8C4Cf5j6EJ<7M~kO{E>7oo`*-E9GtbwP}`J(hRFtH
+3`OK_OWoRaL~*9aFM6p%>n8Oh6D-U#`bDarZm>^0c&7UmrIQtEdTdL>fcxvneuY<@q^{wh)rH(w={Z<i5LJ4e}}t|aR3-vF8#Ie
_W>EvZ2W2Zv88$;<d_*Z%kNc}LYF*1I#Hz+h-SaIdBKtua|nhq>JEK+b){pCK{)~8M*o_ixv5OAhU(6CW1)BF+bP_)g?SV=ZtIP-
i9XHuLZi(YKHaE7R#2;iRN1bK@bdzx(@YasfKchDxk-7h@<sX8KdwXDm838c{b3}DSa0Q^nxn?j>4Dy64*=wue1ckr#(AXP{r#h3
QtCgN6%<j_GP^d5kCm}l;;Ej$<?T#ZvSO)=td(4(0SAQXsER?sAF%^z5QUXUpJ_Uyvebqz4Awx&hN*#U<><!(1$3AU`CjrAc{o)y
^2G%(FjqUe;whT^VE6RuaMg%!Xaq%O;KLlUZa1lpfE$SU8WDl9ptk3A%{+6S5{#&z6k^#d7pQ#a0Sg;{(f3@1P{^BGgJvt&WRd{j
!!NCZ_x=HX^2s>0x-a5l8^X3p!^$4+s)epKGY7(?R;1yK44qvxIjba7_eGo09eTpcjzHCmmj`Rvd9X#8s8>ota90Crpx?zgA?cJ#
A(sjyhKG1XiomJ^)?`#>$1ot4=?H6`?1=DVXwUYg2)bnWC-!*XT(89wRM#edz3J;rIUCO%?ZqbzWXLq+NS4*e%<`|M8R9(E@~?nI
C+t3<M6#{bAf58j>GO49)K@lR)&BWvEXaz@u|Uh~5r}7~V;pcQI2i=)A*DgkWjoe<AZ#$67R+7;S&Fmh4w?~jf_<i_m+xizy3>g|
aU@<opsr%e95A1XO!T!Eakx><y_7zv2?bLd@OCCpuz1FzNH8<3^Ql_65!yQ8Vn~`v3Ws4s=nqp>8hvN1jmv2vk+za%SuUD8%mMOR
kLM`~{<&VCm<{;*CyDxhN`lsDjxH1Oa;^e|r}cQs#qxrhW~SPX=og*cC>;;TiY5szOy7kNK(nzwt{rPdcS6TeDQ0o^fN6>^tan3h
u4Oxbs@>vL=UJEPJd%w*h%8r$<%Bei>OfY+5BGJ3EjUv2kxmsUIvGruE;y<NPc-F@D%2Da-WnvYHM)!(eTfzpDQ)a~Q;n?wVRv*(
uF4x7UC$`a2g-G27`z9ooW>D$%SLICSKovHxuQ=S$|xy&o4d(&M$W0iy5zwj+Jl5ugWRqrFq&$Ol)o<VL~on;Nx?xUx5O|>ZH0HB
+03|d?ZqE>MxX;}{z^uGZgBJmJp~oqXO-_v?WQ^kbARr0DvC@Hv+0*9j{FFbnIacXTo`YcyU5LU!J2U6;PtEc$5NiBIl9UiCp5Bu
K3*WVYTY=?%o^<hDfizn9tg9&9H$#<`NcE}YOQQB*@z$EKgL{tzPCd(P1ly)R+B`m3x8GU?lt(feE&YjHa4|WY<`FVz~xGH9;CYu
8#B@CrH5dl{B?N%qwqk9bu^Z49^Xfulsllx2`MpfeKwUD5xDwts_($~0-m8WK%8Hvd_Bgopl1<k6~`R;1Or`gX+M-{aPndK`n1!l
)$C1zZ|Y24)PMc6IABOy89H$-NvLN&y9buykndiiDTX_#a-yZD>VbrIh~Y(9nRMBWNA6a<pu5Dw4tRCX$FvKkUPCO5NiC_gsVR@)
hn6WW)at6mK@}&r8R>VhMG_yYq^29SDW$ON^wWy`qH|!XF5hQtT~Jaj&3-uZ4{={+{2;v$M-_J1lneenRu-V&qnes4>s41u)#qfZ
)bWPJdF#0*$q<^@X`C1ZiO~5A%31RD@x?0osIg;lfn-Q~)VR#3h0hkB;>ch`fB|{xpz6-2X%k3wS9n_xnT#rTuD@F;$UkuK=>Qc9
^HAoZ()8k3wt5kNSpu0e#GU~J9TD@+7wR{MXFzzNaF0GfqNtmocQVMkvWx)6bMqLSv=)7e|JV<cL;mj|ps$}=q_phS-&&yz=JSFX
;61RE{QIcD)DNopbEUi_X+hoZh0|k%nivZ`wzR5INKOUTP3bWjtCsY2PbqcR*8a7yHd?GiH9_YecRa~#^BcfJL4z)eWyO7^!~{h`
m3n%UEtA%+`N=6n-)7))Fw|oWIi1(B=&0Lh^4r=xG{y049104eF%I*6(V%6t>xh|jWMP5>ND?d2&Q3aD!YY7cZ0NSfnJ!HYO7m%7
25v}_YP&07M?k`w)g5^3l(-{Z_$`dME^8`Lf5zu)Zk_SwscLL-B#!t=vK1|SV$z_&uhPXc0{N2*w^hR|Mr!p4g{S4Q5w~sAt?-}e
xv^OiO)9OUm`T1a82%QP8?{9j%GpCF&=JX=IW!Z0XXudQATKKdX?n~5w;(C3(u>g2S7RA_xF;c+6m_B7BJ&sjh9}mC3s|1DFfKoM
1c$G(rjBw~28O!>0$G}fd52ILR7#lIF7<0!m(fy99|?PU{f{-K81}!7^FEkVg``HB-KImta!n(L2SdK^xqo^_U_l7$IX~WaoAC5y
R-F$G$)%(t>(aZe(5-+^s-qbw2B*krWZE0@asDmhvb+X*)S9Ic%yi%msJRG-B35F#9o?B;L%y^e@4^ax%2P;=yd}o&pPh<R^vS1<
YE%o(WVeMs1A>gmyFe~j@SgZh$Y;?0nrv-6t9naNq94I3@1PuFUf|9){y1^7SxgwN7c$31^}E}dc`z;%TdD+VilYxD*|J}rX;Lb{
D!N1^<2oXXS}-R#tJNl#_swjyj=w)PNn)K!H*qiNRJ3c<(e8qpG8Bd`;I>ReK`u3^zhV>#=tEqx2+C$~5O1bcubP+Ry>WH5lvPRU
VLy0dj6lPfWdH`k*P$4*N@xT{xNM<L4^{3no4rdPN-I(nsldXvt5U$POZCJTYQ4vPs5wtOPS8BnF&7n*zLR6fZ^#bIKhW|=cBdO@
7P^x95lD(f7s6M>8}(Pi@wF);xhM{gsTnBHv;%nAMCOxpQ3QqhNGQEN*SLgoFt|eAXXCOXynYByCytyJcUjs{Z4>2v)lO7z6bHE>
$Kj9<HWeGM2?&yS|4TS#;xUlXGf!XVR{-?98<Boofz+w}jodV_4%0^Dv_t7dPyK-5nnL%@=6FP^p+{&aK&<hAcMp|P4=zrNCfJf;
A30UEZ`|JK0VUWXHB7^>%Gn{AJ`9e8A!E2ith~BY?h?IoVc)L67Ss<yQ-^f}jB)V+E&00(Qu>MzAns?S%EXK*r+qa=*R|GzQxvOC
;J_FUNKz{Pd2y*`e_2oAx?K#EfN?vJQUu>!GRuTV^HaZf6n_UDtghTgO+I-~G&A0JB-<FLcndAAXWFof>rsAYpvEbfTW>VbnR^!w
JhiE5I9`{R{kRC1rs_kkh3=f$B2>XDIRYstw-wxo=n;)+4_d*=_Jt-3I;$_jPUgOK`le@<b{<SOcEt?Wq^0i$UJZt?+HsPs0`%{+
oGQ&kUv+M2QWlpNMg+PuGvQqOBiS`UO>wy4<5tduQbH6UkQcTQuhj>J_$#%E2?E2ywZsmo;Ed!<qgtE-7<@W0QB1s-a$K#uqz9_5
#aYR7R-z(eyoSZ)jl`$Jj~?fnrB=#)f2wRfQNHUq-$N5=vwZw#{6lLh^{Uec#l`jL2E%l&)9PsOTI-MyMuti>MP)P*#iEYS!*2nV
Ti4S1xbqOX5K%MdzK^}rbBwUPX+UG>hTe#y3SkOU$4fSm$vA$m(3+k`<-;g9^4(Wit<bZ-O?k0g4zLb2H>bIx2!`6q41vMw?F)K@
iaVtvA-r6<w5YX6aZCcOu=^eotb`NOBFSv(wg<Aqh%AnYWXx9&VeTG=lTUrK1V}@#=FEoq#F!^i8hKpw-#=(4tG+GIjwc5LC%|=l
=U-S)XK#`w)xp(e*liW?rAYv>v}@IJxZMT{T%d8JR$AbPFV*Nq;s6Ga17xomwZ@JIw%^iE0a{BC_+MNcJ8K!j??qGmC(4j4MYbWP
b~vidCd&|sC{nyW?dWVf7w{Ur<h%QVMFe@RjcPSt|L#qVXoi}lst1O<P<2{7!5|jI0%%pi_$4x=U_0mV9V|-G0-g|*r0`EAhI~C+
WqaIdmxiqT8PVA*cM7QHK9%_8Xp+lU=VJLnNP_eH1f;Um#c4l+5;i+tggeD?FjR)1iiTgQviET2IY@;vr?X|&;%Um+`RAJtT=nFz
9v7sl>Yr{@XF9)MNIVDJDkS682Fn)pqwpO-43I7u<spEdBxf|3KDHuNf;)mB^LNinD0t!BVT3Sk6UA3KYV3B37~qCK%TozW7oa#b
%>oj@pa#codkN6Jd4~W3|Nh5iF)fgvXJ$Z*UQc1Y(VC~hht-sRUbEFHEZ2;(p!GD(=o`BIqRpGWQI-*}_lyxRm>;K7mTc+9{iCBV
?J$`s4KHKQ5+;7S--pGtQVM`p+c4J=F-WsZq2BAp=TdKGu9!56Xc!qfYfYH>gWr)qdx&A_jXbl0@+M*O0TY%E91uO1K1wx_DSWFS
EjnvB-Wn{FS=nwyu4*M_{Uyj#d(hI!EzIJ3Wi)LMWWFn8Aoud}JT;Q%C0)V(i&U@;b3CH>GA0xeZo`sgdEtnWe(2L|(Rs8&W_%6?
jopGaG2e`mTvivwy~Z&E2WSfF(@ta3nstp#++K#KJpvI%$4EzAsu`4;(|G-W`#bU|<SHla1g5&-op#^#cd6QwJNppfa{en)VJJ5o
aTZ(~YyHRYdZ{NGe;R{i3WmynKi9{n_yv(*>xFYVm*DbsO*FL>F9+x2SMQs@6K;5!!3_laWE^w%VubQxA|FPXrXj7O&i&K|ngAkI
rMh{^lB31dJDRM(xyeB<b6dWnJ`L$SK=9?~{^U+}IxKSt_k9m+$T$CWG`&zbXKXo-wR2>gj`A7rV1bg`MdI*-!B;iFaNch`6=r@$
OQ{Hbygg(+v49i}g=lGbh){zxlXp(z+q~;7!jh``1GLo+RWj}7ERwg6rY$Vqe(mZ!g|#Kw+~gHlnx+4ida-*1$3t({e(51AK%y)n
wH19XC(!G9%v-l}#@L1jW{BLEyI{8m_HHDEBAzP*Olm+LLh{cOePp6k?P|KPuvfm0l@i719&rc3RvPEr1iG7EUt4bGh0kt5@=~dU
w>Y~T)IzXw59+)}g(g{J4WktW$U!&oG+7E{$<w|3cuo)c+d8ck$sdlY$;+r3)QmsDhH}Z%6u{4k5aYc`=7a&Hy6-l@_SirTb8abv
n})C)%-phf>S2O;%$5DQ^3k`UWvVs%x#Iv^C;Q`@J;4u@jNi~1rXPb27rww>uqy4n8ViCZ7;b-cM<0dnm^B8Ce)1S1aF*K@16O8}
@3)v^>&u4fV`TtV&Vkd#AsP=l>GlFiWRvEiegTbLI`Gz<a@uepXM^c7t;rd0>7hv^`&K31YIGc+FLE4m3qzYV(df5lV)IclPQBQ@
ipP^Bv4v0Ky`j2{9k+MP66*&DbT!WIFjOPMm~2W2*SAFmo563p(3gVCP>M{Vrf(6VTRsv~eML@1O?DdXchwhHPgx+g0-`Y|uY7d>
Dn&M|UUF;iZyMSO8UWF|Dz$%SrJWUI#b^%^ce%(dU?G+l-^dFTC1@2f%;1;E$pZyN@z;~yl}qqslSzB%5HB!L{M{_fBpN9ez9Z)3
E<P&%`EA_)U)H|bfDCMC??IxGHF^+I)5`$lV!QUI1zNC?rd;aX$oVS;msP@-|Bx(ggdDX$F;P~~sHGaED9JCzOfE%-SBrBMdU8Z%
-bj|Gg=BL=jSWxTdzg@5c7bul!&X5lSy7ORuU_u(xkesenHI@*PgpqyDY+3rk15}5OpH;t{haJCLp2y&Pfodq;cQ!|NBMJ=1D6o;
^XX_>qlEa;`X}c`iN$nkusYn&WYOs7`<x>-_&6`_@Wp^}@MY;9f4GzUfhe7Sy~ADoQS&f8*G!h}R3<vt>7Zqw2!+c$A8Jg4#Dikz
SWMBvdVJZfHV6Z#(6xfDgi?_y3f;8h@g1;)RMCDjI=civ1fs!Khcy-!!5(Mt`2QM3P8cm&;)b8zFk-~=A_;BB3x3wA(pv{Dn-W7t
Gn5odSmMgGU`Z|C`5aRsC}$sdog=DUM_VZlFC?ea>1R_Ff~;V&xhY!o>tx!G52CcKVxCuP{i1TbD`Zm@!0yGzd7>a@6FAPMeEDn(
Zv;Z^ifWq}JqELJ_V{af$n;ZdwHk}8V_oj|K4bv?$IbThiSE3*<d(D^h~tfbYg<up8?lfg^Q*X0X8JS0#Uo>!ZEwCSuiS1o_yAe$
a@(YlUqS#Fy#jG-0;<t`6uq?@jH$3gd&-_kCw))(Oue>6hH%+rqG&J^Pim6Z?%X-qX*!FPsJ%a=8fcHSG%zpw_tiO2R&cEgqlC5H
CuzQ9&%eBN<Gc$Yl4_asUpouQKieU?3g)@CFN`Cm-)R3K-O4EMI+EV3gXsCvp?WZkT%CHc8llv_%KCn{IRiD;$6g!Nnr{?~@uJDn
fVl=Fu=?Xx{f*;W0c5IkPjT_^gE6$@z<;5TZ8tylA}W(maG|j3oK_1PJR=zB@wldrm_+Uu`ilfqI(v#8kqKKz3f^x&%t!yiGl6U8
?y;-#7SZOBktjvFYoJNNluDLlPWqaK5z#=syeHKEdQZXK)owan2@DG-#IM#U`l?dAbQ{EV`JH4p&LT8cBinqNEI^Iy8cQo=ID#??
XeQDGm|Ic8sO6SRwR9v00<x%cU-&^*mmWd{Ne~e{HmoukncpLa+oC7;^EXqnndRP8N4cGM4g1B#%i_Dg1jo)uP=c~6%epWdbd(6(
UDVe)9`25Xtm|lT%VXEoWSZ=YwqQVvLaLVivO0d*eFmbC^P~G!MI1&!eWWg6?4(Rb`MH2poH1g{O@qMeTWR@pekZF2iUH3SFUrbo
BJdwdW09wn+D~05^|~nD3M0i^2v)9MD@0Gy-?yh@_sHe(E6w8?V`I7z4D;$b-8BUhnwL;ZG)A5YWCI<_+8i{`D$#c03)>S%wVzW&
E%M6m6yK#zaY5x_!2-Ywl;c0~skKhd^^ApHhIW3nRit(gANCx>ggxx0Y(KsJ+V?>dRWvwMVcP}3cWyT28+BHL+8&}0Lpjlwm_{;7
8eR2Z&qpb?-u>ZiGdIAc@Q8r>n}iQ>)ZKouqr3`R2fB_=PN(9u?n>#mAJ66|$98}Xo1+dfloH=6bP-V_&9-_qeM^kpNxsp7Tv#Gz
a1;fywKVYrUU#eB+vu(Xy#73f$GnbrZ>Rh?{Us@8+H+R4Lr{m75CVz(aVqkIS5(s~H3HwwPkz}DP(YlK!x1@^aoFj&YXC~n1e`bL
PW6eEr87Q$E_uS7WccBa>FNJ?h=mi+B0&=zc#RE|e^0_QWa;x_+$mQyv8Wuc>CW0`vDn*kbCdoyNS*nZ_&pE#<bP`7J)pVR15zYL
)~)SRsif>C^K*l+NAgv8_Mfk$f<H(qu_lv@39!A)u<F0?54?Jr%81;&hH|R(8VIp@=deRSk7%`0ZgC*~150|K-+wi2`C|2oyy-lr
fQK7F*qehE)4q2Y(|OQl7;BCv)hs5^t^!i>Zn0B7*Jm<+k)$L^+|ixmWIlT}KRcTw0lGUd_*0CrqMfQX9Ac~913zgXb*PfI!j+mQ
Uwm|1*4$*|O?_~@cj|<c75MWiBnCX3x_LugvR|tzM+1+oS5V<5EGMOFSG$|YzE$4d*q-p0?Bz5$V$M`B9;_jR_{1ySTLdg5gWXpV
l+2kjpocm8Hfy?-?3X|1!h`R8JS#H8f_TekG$-QEQ`Ailzghz)e5KlhoMwup%#3tBo((8d;kW3^CnQrqb;EPyEJ`T~kEbyHi%k{y
QSR=?hJVUNngx3^nNhne`aMkUoAD6Bd<Y^wHe1AeOkm}CRF6$bc`W5gf)%|e{3$^#ELe*-FsacWq>ZXGpQObJaHeBDz*&l(|0_|)
ECtj}X}Db|A(K|wSl6ou=ieyNG1SvXy*J*bdL5`wO(A@I6(r~lJ&?@`VA9K`3agi9$-KuwcW_-+54W=_#MXnW|F+h=XBCgOTjJ=3
NCYYkx^Wt_+5%bxYse|rgWQ{%FWUVEz3|Dr-YIE@A9h55mj!u{5*;*?6Y{^#IhI#J(aJpN1!ur01>JYNgVP9fZ^}nCY_u*Srdz?5
VHk`1RUtd!zq9A5f1!Z=R4}a6pd?C9z&T$$ofQk?RVn`0g0C*qh0XrJo}zJg<!>G)HFQ>Zn(p}8_Xudo8;O%Hu7*MyY@Kr4Bu*m`
9M<WLTY(c!J28EfG@ca`_ZJl>M;p&dd260j?8e-K(&c-+!U%F+n1jJ0)reP3znZ<FEl2GgZ$1Uj7Y#HCf;=rp5k2ld>6jet;zrZq
QpQcv;)#M-EkH`d*%{>enTD9crH}fFTUi3G)QA4$^ddjl3H8!o8)h`YzJ56*FZI-|3R~_-%DS_&UaiGic%vI6BNk4V@+!&6Nc+|k
pMj-4m$LL|@kZ}8mOpiQGw4=*q=!Thsm@0)U7p@cjk>hj2VmTZ_hx>xX6b_z+%D3HSm`1ZgpwIPdAX5zKh`ds3ST8tpg+B5vo(EM
gofQcw=ZCEN2eyH3QIPmfnctC5-XAqrXRg!lvI-{kwnC?S&XV_DgEK&ogu8!<bD1tPWa)n=V?++e0ABeh}<|=n#|Y;Q%+X$F5ZGF
^DP27^C_h2-OzKw|4u4u97wplbD)o+U+F%GE;3gDfQ@+9y|~fUVs}U)kWLX>3P`xu9Kh_m>+KK_arF6gbYwXOUzsvVViJJ<x<MEa
q!1rAbX?_YP-$g39#V{Q^ZKBM8;#jNM{8|FL7$pAThOQ-Mv_kALb`I^i`)PpiO4oM)WkmLjgs0&KJF*K!{9AXRYm^9Rpv6&8pCoT
OHFFNR-pl;TM^&5j0dK6+QipcS8DpXj_}pL5tzQ4mFGQY;N;6M!_pMmJBb1$Hulv2^+NEk+N?Iw2Y0jq&$|4QpLJ$X(I8+(N~U+Y
r%8w`C!1k|zl_h<{pM#h=5ybKfxJ32`eT(-ss9(kS!;<^C$IgG0ctIM%G*j=hGGQ9W0P_-KH!W}U{&b^*mcp$?e@z(^A0vbD}KvM
8%Cu2Ya~p4-uJS%YB$j&K-vbmA#B5(%eo}4wfQ3Rz1*#l%V(}<rvwn?8+geXR1fJ5O*fIjDfMJJgKyvQCcPH~9K7bS|Ak|gFg#7(
@Vwvis{o=R2-Z5cgJ>vo013y-xh2URJnDeC<uoHcsK{mDNunU<7tU!|CVMx(F5w9U+8EwsE5Hy+2BTb_gG@1NtsraAqS&$9kZg9J
kgcMzzQ-TwWmRBN41eloRhCpGvA|EgpetU|tQ>ligt|Mp;<X8M1N$uU?tr3|g`LkSFtI8(C&)K?TDsl=Px{v%o-hy|AsW?w@zfs=
t}IA^J{?IejM`aCxu-%1D#@ECbj1~(JM$=2^Q=+jAvv5!F~lztk4sv3Qv-<51L$^-HJ#ys28Lalcb|!dm!G~gLT&;gp#sTL-}^$q
GxThFLmQEgOILgHp1lu~9DPu&689>n_dC!{+p%m5!1IZkc+147@<V3*_&3zKp^dqP%tG1_sw(%6hd=kE0cL`s>Lw|w59^N5R7^Du
=1x?Db=<`6j|gD^B`Imz9f0|IFELHpTd8YL#C@kLv#x4Yc$dDPUgB}{>x>2XvtCdsSwsB&aB{KI$2Q?Eh(Sy!$d&v|QnF)I1-+ID
86`62W8ILBa&pc=(tUYJa_R%>d~|N+)`+!XgxljDsSa|kY5%#LEl@1HH+zaS?gMI9vg7tBfhn8t+ZISATlYF8ji{(Y#K0iGllUt1
1vRYPDtNfE-?HWo@ZBx)y58WhFh6S(YJpD@O1n#s4QOH1D&Ay6AFJ4taCNv`IS?eUlbW1@e|Q11aU9>*3DS(Qs+2~&Ht*W3+-+}Y
^9v)7u_Vp9MlBhwFM2ytirRlP$@0Dn7iI@3MeroM-bxL?vE?L>-6uTD{0VSi9S)Z<KVnYEWF=ECnoO-;6KR{jm$1M*WUIcq-~ZG>
%OQM$FLCW(1V^yhuU;Vbu<po3(x=t+zjK+Euqwc+O|F<>tAO1mb7$Jp6d!oSkCyzaFVsTiDPZWhv|ch;`>KYku=iPv0S?Zkq`YA@
ox^1zw0q{AZ)L5(t$WUmkwnMQo-eXM08xX~{@d$YLw(r##wTf02Mq@Ejs$y!;jP9);X82fpN<sil3P3YHG)y?haIhRY!Q!|=D0+T
ZPWe_N55L0u9=c!KVH}t{h~pV_wvx?r#i|Sd=#@Gr`bx;8L!PYGez56C1e*oCc0T1lhSFT3X|6t!OceadRcBrGW^RxD9aD;Qtb0B
-jgo56&AhadCSxL4R0v+hV0<p?~3;5dJdJMaK87Le!!UEndYxG)Wx-Fw+T$hvq;Wu2?*9>RjJEGWod)H4D=V((uramsq}Jn5M+V0
Nfbrr=IMJ@q6c6xeM`=js*SXZln8|HBEACx(A2khWU4Pbze+A>RdX9O?GFbJp^B&vQ2){zUbpHbW32zyI<1F?yk9i&c^0HBrjxT6
W^!}(c@WO4k6OzMM;1WNa7<nGHSOw7G{z1ginBQud47UEGo&lWM{b~xa<gr)*FeO*f(+A+D(d4=BM2PoY60>v!H)~wc{3eyRk%cX
ImXP?-jXImi*CV&k4kw7N?<ZVjsQEoHc*@$M?1eg5DoVaL=(}jrWxNM^Aj1`<Mk%e(7K15$yU?He<fzt`3&Xd;7{>7hy*n%u|_b_
v5lyf2~desGvWLIBdoZ3HUfK6O(1m^zbGL<pHH9LEg!n<{H|7~&NtSCG|FzF&>@XN3JlBv0!I)VMdskOF!cQ492>F`R%XwuxsRfp
S=`0?wzfgb91%U$`2CQsUo|q&P=|+%hg&4!x3vyA_`c<MT`<<Vh&ICs>ES5C8r}j4!WG$YB2W?r<lBWdZO8D6o)aqxhG(AABgXaZ
nDCrvYcV;`XV)Sz(<QrzWLD?D!7Hq5A-r%Q-|4J~jO^-47>gS|NznN|J`wrR%<rIHmN2t$Oot`L*K>j3NszxMRAiGrfB$!rrum8i
q|Jhi<~A|Yz|QM|UW0mny#%8Em?{{83xRvv<3zza_Zs9#so;*=N5ri#iJSYd&O7vRGi@H<k<<KlzdRRjvF`ah^MvQ0PKnrhW44NR
DJ*dhlwb5L<4C}##t)!J)8Rnrii}zDH&=UwRN>mIR|o?0U4DLtg{wFm%2CsI7;1lTU1eh}^ayr_8xXi;zLWYlVd&Q0(>EM)9<A2J
9x0BJbTW%SUw7ZIa>pSb-?LKu93J7u9h;!SzoMFTS(Jk^ZSyrKpAdJ@pau`!0N7;T=@~3$p=rXaES!jM=?Ye~u8@6xuwEE|dfjAO
bOhT=sDfq0)3S8t1^&qbctpK$KNEk8<jDh0YM6+jQlzSDgOC>ds#eg!M;AM@f>psg24Z`hPHBLa(Pv{^+%KCv-DZ05rUJW3&V&8H
lnr-bbn)}98)ltC3Kh#6T^am{5K3Vr)jEhQl)4F)4+7q_mg#HLwp2Wf_}kY<WVHck@d}q!K`iL#88xQlnc!w?j1)yOGT9oUkeCS6
^DFoA|8r@9F{pEt8(;>W8^wxCz>CMcj}#mx7BBgE%1($l`K^jndYtMa>yAZFi@&Fm{Mg84sebn*1a(g4<Wm366{6Pgc-9)#;8}!M
mxf?T0@O@9VNa}ywd)fGb|7eG4gG+-_zl?SWk9xEcwX;nVBI~ks3UD$gHk2!>Tg#q?lFyczxHN6fo;P4lY*I!W8b3n#Y?j7{|3*n
25UFc*YZN=G$E{kuy<BZ0IO*sG77(&874Z$E8EP)zSLE}FCx^+>XEy<w(X{y?!Tvr8;V^<=uxI>`iB@KRr;P4zm$?Lr`@rf?<=iu
7`y|BWy6ry+>>O#e1aws<XuyXghcj-DQDGND@apu-mpt9FRHlD6!UPd7t(puDSkL8C>^7|-rweZl43AZgF+yK5o5kX7(#8l6bwiu
)qXTVg<909M_`d503s6Lhj2>AUTX}idC%zHwly~$`a`&F_45q1&6=Ijf4)UoHE~9;{Q-OSB?|u>GJ02n5!;c-h)1k!^BX*Pw^i=d
r3Z$lvkfOd{@l@Vyw#HE_n>OWvg35>c1|r~4g!hT5=my61~WGsrTneKZq|3es(zfz#D!MgA@VIG6t;SKvdNSpTT&rHd^B-+<$q80
CPE&bn5=!|?~hP#ez{k&qy&+oog5T%SJMC6C>P(p#6x1uBk`CP&!W6{m!TK&N@r_1zCJ|M$9>d*qeYX=xo*u{JaI@M%d0h%QLxih
tT|dH7>+u>Y9H|2i8R0$ucrNwa4x&*X*7ogZbCP#8&_z+?8AT8GGnn-WGCG!bV~(PBoSep02K2vtOB5<tfdHg^D#BR^~<9L=q>_g
MfDen`0C|4z9g0%mbR?sS&21%w6#3uGcnGXM1ja$2sW!D!m`Q?B*TgsE{2IME0~xz8A1lcF6R=r)Il^ILqc<Dw69f?j5$=j2)%i;
l@!`|;y}*@ilFs7G#^lm-Sm~zpopg3e1fZ=Q5zkpW9umm@<J3sG)6WI%<B;PC@B7YlESu7C>A)gMg4WdCMb8v6=Y`OS7_YJM8VoO
m;N88KFinW<<}JmQ5AdVz)7#$zvb0N=UEv{&%S{>$>aokBxZ?$33;;=t?6YaM_Y5P{WpMOnyJIl0~xwyGlJ8XH0o9Y05g&&;C5em
oJ8Y|0zlmIbu>9|g3kyahh}O74$J&k+?tv0jt|fH6@lop|5PR|{2H$tJ6?2kLQCN+B%Lg5+H5@o+B@8JjcRQE%|C)41x6@j%czVN
-0i5}iKND@A*aia&Quez8Jsy&R7P}GT(j23ee<=)pRsG)WY-if$xbxXtjkc}wuKL_(TIm4C9%A_k6uhG_m?JSD~*N9C`koJo9Iwo
_kG$wM5EE5l@o{V>bEHVb}hje8W8tb57)cx!CCou0D;H|CwP7^sr~=0T%YUxq6OfaX>l?UmSzgU5koEN1OS;5Cd{OPC~C=&Z){xa
Doi7{1cRkkcRW<}b4_+D@~|#w?eKSX+FytsfyBXAC5+)OKL|LXzSx~U#@NWtrb){O{UCA~lo*u=qLAoz;C(YAZH8FiWe{P~b4BHc
YcrF<M<tKGx?p`*i1>T!ELA-M92#EUi2UU~=jnoYm=x@RVW#Vqa2p4&B<GP~;wF}*XmKuo+eef~P!I(c?c|-{u(Ciw)Gv#9x?)4c
)lQ_8J75DksSUcF=1_v&XsWUX26>rq&zAE0d<+<~H)*rm4vxPnp-+DNvNdgQ3-_FuQ=1kIY-~<GWy6Pd%QuHSs*QCxdokk_;Du@~
x12`H?gd7RgvGD;yx&86K_?GYYA}3zDN{eH3Bb-ddKsUjMInaAm}tGa&c4&lD{D<$&$b6t#Tiu4yHGgXbe72opCH;YDoiG_D#OZk
@AiAWp$)10qoi2yRwkC9!Ksn<V$0vj4#tLq{1V#fgTMQ|t{vH3tqb*XI{egMW#t8Y5wj9&JCeeGh^z}PCdz^<{!8K&B=I~ub5`N}
t7C^vRhz+ihK(sFtX5c`!_;*G`Md_`1c>d%Jtx{;;dH(SR6G`>oCVK|akKD=SFlZwd<Xi?G1A3BsoQX%FqVs5s4NpCUr5i26{%0x
-n-k_X6l1LJ;~MYLaGjp7=rm6ker!S-b<X2OA(T;UY=DG3|hph%81Z7{<iZ)9S$}#T<0_9m96DNU@&EDAE*^(6dznI*2%M+sxK>g
z&V+>ywAw2dM939xMyV{cv*06A<e*V%6MDUpl+%qmv%lC2qnsRR8SeIoZdajYo4_}4Ke4$$q;vuYZh1bQ8oytZtoG*b8{y7qm_m_
Isvc@L!J2y{yN(hX9^%+bJe@dX+Z*$VM^dwL<66LN$vAH(`?egMMIO&!!6}NRQF6sEjJ?gCUe14s@a{BcI*X$o71DP!NtnGO<YQQ
_NS--XYYhJ`=HP^en>=r0w`D<T5>Q6PC=H3uF)xLsc~S(%L517&{E<{-km;c0ZhWcuT-gi-K?UT6wI<X<UqXH1n}7zNUk+L1Z9<S
0g~d!o5zabYp}e}v6pg4Y~WyKGjiMoLb;%?<yRKfY}%~IUZOD}Qn~|L4yu|}6wS>Oz+M~L(jOc@53AY-&aD+T4fvB*w2n#6zXkp0
b)}T8t&QQC3sCLA!H2+-1hnQ86a|@GkqisL^*n^sY<Y6jBQ84T)t?RM=cT9JQl^>ps6mnjB|yfX>lkWBPdRBLF*GEi3)F*=6Z!>n
%>@-=>iA}Ekw(eeq~oxiT#G_K_S@LHR^u<Gh*Tzx#a~;47Kh>BS2CKchf{dyEmeYlM}z1ipfHfKe078tkj`R$X%xHDNvjSEN_hf-
fnRvY)KVp+!<K|f3W=k-&{A+m4kVo=Le?R7oZrpJfk_Ib@&UqBHF(5`{Um1oe5u}cyaE>d33>?R=Cwu=zypWvygPEWOF(H(!U>h9
t^~o>7P;UpK<d1hr>U%R&v@g04biXqIFjt@^l_a{KtmSZ(A8+a-|h)XgvmW92)sY<wHFI?7V0~N#&q4_8<OB)R7}72aQdf{{%x&!
N9jFnoM|RPZjvQ&WrR0Mm2B)EicCvc637rX^6EmxkEUe$$H=`O;JIv@oQ)D|zq0>DEkPl<TZuYV>mpq9EqD>L$-9>TJ{2x)8AnAY
aNohOvtoil1pq>T0M;YMhZUaA*nPiS@#^;&aor*TkBxTLP^0n{G)}FZVoEz)(Q&yS-$N*Fb`sRKriW(D;t%|cd20V`h8)}CBF12m
aGUd}N}GfFN&$izm1mbkxAdygHKqW_)j=s^jth1kP2GAlB+H%$pC>PMLU^x?>PfIaf`H_O;faMM)G9ztQ>cFvM&ebwLv$fguZI8K
c*=EDg{vWG<X0>rR%RIsQwKMXxRO!lMd@+W*J$*NIQy;wpxr5~>%b)tVPo$3Mqzz=Z><8&NLK%zRn^(htb_o|H{D{4Ih*Po!=&@_
R6*F`3_o_!fk$8oF!<aR9=y|dZ;)_CRSc}$flob6Q$T~ij_}CE;>y!pk7)L(rz@tWs0Y<C=C54~@Vi&xMjp<4{x;^JlWb}Rii_!d
0ZJN<dDU}30n8@nP~Z6krbdD@tkIiTKSowa4Xk!uxfW&dP2AHsHbL67zoL~&IB!}jLC$zC_LE2!z%m4^{bi!J7Jak`x)er18`JG%
iIt=@8<2c~{3Fp6gzTR_iLAd16@mz&9)}htqJ3>XT~{sp6Zx^?z@GmUC%KAWa!t6BNytyx@sUUqe~<n)U2BpD{YFB=N$B$J^(=zV
tu@4$KA~Hdc}$Y`%W!VER9OW)kV-M*GeWr5DI8pZZQB#XL^pY#N>N!E!EVWtqj%Z^VM8#B1iGCFAkS~C&Kw{qS`75>J2oHOVV{!>
+qnTCWuoq{%3#qScu2aH!<P5dN6!q7dcxNN7LVh+?53>IsKT!<W<jO$2l9<3L|*j(>u&|%#9uQO$2PJGY`s6^tb^r!lAEvKU~AvX
9GFMj&gL@fPm>}rkHAa0{19Zk>dDax6w&2?aUf#-D-rCp-Pehq%s2|_HFRoyZLS$-iGZ%JmclS?%f59+p@3bgoyOoY8ccu-m2A#P
orZ%(FRhSdNwTIVlVuV3xI5VMp>nlaE=dl8_>GBEZx1nS`u`xtIw_9HFRpOfek%`o3#Uz=oQ{Z~ydT2_c?*xn*oF(iTlbo6+fvr8
13l8eQAym?`1g~PXi#&mn<Nk{r)owc%rl<HrlXrr+Q!?Kg5Mh#Q@-BUS7+06b8VT=<6CwMqHzw>L4@J`$GEe)9_ja%9p4doM<{)y
<LVFnN&-iNHw{1yYCyQErsF?NC1M)8>WxvosZR(g7~v9iNkQC-oq#H|1*dTk;xz@vE5le=3MGX&p3jBZMYLs<+QHK{L1ClzE&lAv
;{2P+r8RUlTvpuQI;{Yvk5Re92o%$X<y_!Ro46qm3qz=_9bb(vxRaE<xJ&CRC{#vyi7Z`Xvg~H4T3KhKZ92NX3C-+1peEnfG-skI
wC<;qgq`}DKuHDN?Cmauid#syCX@+hq&?^D8mfpg^ClV3T)yO9s14{0mQLN0+qLlVR7Pszh=OHc1Ct+*DlStzuKI`~+l6>`XtmE;
8SP<B<|oa-#j(Mad=;T$q0`4~qrcNSWt<J^TD`{#b;h?O@!c$|TE|wqttjnvfAq}R9|E$04qv$GRINoWFxyo!esJyfDhdL082mQD
T!Wsy4-n&-gU9sb?#q9!vM5K}e``m6_vpuGXC`<V?HM4Gj7hir)w_M=Gy0)LRq%R+1AJAlhm_~RHLN}4RacEnDlIg_?gXO|fs?uw
zT=~O&?c6oAwJy5giCZ?HO^>Y%ai~;707)%X)M$jxOh~qlcE;TL08!CNavRSp4Mknp6Ew0`E@6CHEzVjokVW)L999gAwxhRqo9F6
A3xEO;U94*+hkg)bZ|;Ax!b0u8~L)pVR2Y4F!_QBqa-kW;!~-N4TpfJQ9&>Vwr{bidX61j#pJb@y6pY1(qiUN-(NS*P^H#dyor{I
4}O~`%>$?&rVD~g3W&o&C7fq2H7^}sqU+xG4i|yMdJMl9p(-z&{B`d}pqk&qnApk8DA-})@-N$vQ_Dm@_>P84nj7EhdD$Wwk$Qqz
*Mh^3uBGxF$oaP)AGxo6h_Xpd>GiA6A{qXNpLt<N7AfMs>I-3w8qn=gI*_cyz%>P|@uzXjD%8(6Vlv#JbsAR__$`+q9|NH&n;Bv~
9O+&$C^z?OgdROqO&-qLQ(%y~f(;sBDDhm*ugVwwXk>Wa8t*Io2fLyB|84E^E2l5W(ameR$0z*K57R8f$hw+Nf@mtAbKLI`hZ8jJ
!+G+6D_|0__^$O0WqzU1&W9Hns+|#Ey8wpRBx%Reni1ZY<L5A-)5HYD!@<Fz!;hz6D!VSHw_Lt4ReJPiKssnZrh9zW-1ExU?Ge36
aJR5}X&i{8MUL$DHU$Nb^B%?J72iyeakA&oBaAd^=fRZ>xl3*|0@~grU2{5ggy3`go8UgPY+KN?V0=q!#XntUuT$H>bO}S8fUdM%
p!);?dpF#Dt^l=FABiAwSN}^drpLlSk4{Joquw%SX%uO;(`Fs*fn>>eH<KOW0H&A7&$uHBlh1oywh38mM9EnDRl0A+gE?73e83fE
Kfhh}Lf1tf^F$C>q-}e%m;}A3LCJ|`{SqBAN_6hnWbodfz{JZoFKn~=J7PSZKmrS%^RR6SL~|)n<1s+g2#H;vw22Kq4?HSP;2U8f
AF)X!)?yZ$L4@v}krp9sHG2G-&KcXX?F_9AFL`#dK-j$0%`1)8f<OC++*s1kUG6tQt3sN$SEU3Kqf5_sW&vSE<<E?Qy+7_1Yp@%6
jB=kXIdPhK9X_n9(w9?N&J+^Cr`R*sa@P9`s<9B3%KJbQHFOqMj4E=*w8-B9rNRtF2#Eb^g>lz)4+9_dAm<H7x5qGrEA4})zf(;_
PZNe~JGvSxl*30$8=0#_@?&hHdq>l;a?A6attSom3%8m_Rr?2Nq|@NOB=X9IQGMz0mGrT=LCO>+sO{x88&_VSqs>;{JoMbM&fq?0
HoKVk2q)<)L;<+DF*c$ZWA{-&r?o!EhD|cEwhK-g7udnH4QnYZ^0rAAv9iPtja6ZOtPIcNu(&|At@J*kvfIq%fCLHZ)9~zjI6K!E
B`TO;{d(L)2OBV&$ph3}W9M00;FG8sN3i`lHhF~esvL06mDA<*YLCrae6yAk9Y1sW8j6B?H(`Y(B$mar_P1Ejc!+{dL0FoSQIV+0
&2`4G3&!sCvF>pKoqC|<sc5^LfAS3TP-EPNuZKO0tIvYOd*h%h8ObD0teKKLk9SS3TB$ZFCv|uCCHE(-*<pgViu$}yu;T!UgV-QE
(**^aJ7;9!)&Ycyt7tWN0bXnXH-=gZsg|GPO0t*UR$U7sr&`2a;RbfXFGNw=J(HIX1h~^9%@jZ^On_8~6mzJ*XzQzR$Dd?~wX^+J
gLX*OKlS`<H_3{6(EF4liRt`-?Ist26RsY#yioz|zET7tKY=s%6<<oyZdax?2F8B3go8QQGQGmjtk;t;Vugf-_#X2!tk-d<(h8g%
Vo6AP*uI5;<rt&6gkW>uWf}*go7n6#DI|qss}m+)b;o-zKk{(@x5zOmS{p^nE&1_>!fv#z$$tsm=Y%OGF5l*REx@oEVTi!*`*!>5
5}4-R;FH}lzsJB$YvooCXf-7C!Zdev42sVC)iy^sk}8cihWo>LRB^jMNz>T*eYOy|i*=cl-5&Vhe2OV>t+~}cL@N7yjZPQ=W3|FV
1Ub{A4rIjkecJ$%(mhn6P$x|H)(CKCub)S8bjB-0zcuTB+;NE(FN25v^y(WG5m-E$Qr%T@G%%446sH0nmxMBd^FRkVmJ+jcQO-8e
atHAX>5zc)#G9OxU!j=V22&ur!NhuiA*vd`^?W`q3|NNHrG+fT#hpAxg@WJ+r{5;(&>KFtkRS333328MIkEMqFK#f;FrpD6))IGb
Yq&+^SdpddJZ`2BdaU0}hPdu{P_S6{oO?0xH4~jOv&gl|N2ua%(u*dHrD%}-cEA7S-(%rSLI0zDbRe0-3R@B3uNZ8t(#nc0G_SOM
-1T3$DP}5}D^FSunw9IWk|Qu+cR+n7&;3ad9566clo1;`kqEpy)*k6MlB1#AkQgJ#yKwYC1e0rDgDb%s%p{0w3nnq}f*37|1z1}l
Be~DJY7vBD3(%xg6%V>+d7B++e2_OrqWGe@DbXb%DxtVTyOUUOnSHWSBtvs(cAGX~Ov3K+RArGVf84?KVCMSNx+p$!fD|yMEUp%K
T*_yqi$j*a9vnngo~G>&&|eC1$OEM3AcJP3ylppSVcl>eHFYg9QKN6!vMB_B#oEql1D<}lF1^an60<p}%cUnh%;O1{VPXEAEiEK?
p|CLIA&jbv;fIi|8vTq6Hsx}Gu&70-4vKjT3QR#&Qk85s0iS(oWSzSg2f_)PzmI73{Q;#<>Q#o>*YEgKRXg(HK_1E5sRsf_{w=zo
(wXnMz%c%p`1uYzlLyiP-p4z~q~(BD!`&O`fyI@>SkLfA5`~!i-p1o`{(4Q>JK>$LsV}<vxXVtCU3wIB3X-`Ey=yDjLKFnHZJXzM
6LIIpYX|N^=cQx*;!?8K{<r^^w-Vi{&SwuX6iA6Fydl2bn1e_bRLG?Iy$vy@)gduUusRL;&w@0LP`U{X3w)@B=eKm^dWh}mX1x@;
PIv!?Sx-!x^<&9gEUSHpViFlpBQh5+t;E)^F~eq8bHtHKoiTi9S#d75WYB6Wu$1{APk(_WJE$We7I-)i#I~D|DE_y7wrdSU_Atg^
Aj8IPiWN11&x$w9Z?ft02$FG)uDl1mk6+GrzonY8dAP4m2Jwm#qtiV$*hUKf&CrzM|H{aUK58&iqTGOxXXIQ%dGFKOJEesaL4+LJ
*>rz6IhMM%ai-B-aoMm^9R#-xITf)uE(*`)7?ZCz^!IvS12s8~_p%vNyk%rdJ(KH^Qf*w~TI!tIiIj#~*^w^E>(&i_GRJo5K5TLr
y1J9&v9nQ43KncFGVQ^4aTVDq`pk2__nOzl*F70<i9Jx2$p&Chw_ANq_4BSyiqrf00p2E;&oGj$1{f*z6-<k~2MdCy@48#+qovU5
b59o2>|guXeR_old*nbwfk#>LHR?HeZE!4*dthb3T&S&Eh&Q3hILX!r{_HT814Hihm`JdDe_yR`p>L7N$kI&B!xmGcs+kee=B1L9
llKWYY+vp3*Tv<w=joU1wswe(6}l*|EVhbch~18tHV1zL*Kz^?@L<*>F&!F0zK_<eu;oKZ1xHY3!8dI(!Qrkn4s-Rn1HlUL`wl3K
Vd)#orL;BgEH)T4@<HTZ*A)q#<aT419)g$@Zvb8V`SY_|Tf?Y7dDF|exB^tvEf}k2G{iTjr28#zLf+tN{}kpLn5L&*gV@ER_LWpB
Yt+br``>{>!Ulv(S&!Ru;4W_v^YJ>FUTc>px52Hl>(rv#Gha2s*joJ_Byc6qTbM1D;bC?IzC#mFfKT4E^g$xp+L!8W0=#F_Vc$}m
XmH~)ufRWpFv9^xY^n~{9UWW8%?SeyN89sND?#luBOg(g4Th*?fx9I=fWxQ6@vn#9E+1bYJh2W;(mXG!17gCI#S34Q=DbAZRHIQ+
9|9UADRC($0TuWZ>~I^o&e%Jv00XrrY0_^wwpm7S%&iDDT(P70^sSdDUe^kVlC<W>l;iZtrO?S6`0Q={6sw&LV`|d{YH)o5Bo;Lp
*L#jmKIzAkvUHD1fb#Z5kWO(Syc=yYgk&Z|H|hBaf4vePII0kUxI)GE*NsKy5p)npL+)o(LCae%BoCxuz+aSFpE3CU9}Xjr4wx1x
)f9SQI_?m#+8Nz+VX7mSv^*2C0_!AdV!Q_+RDv!<K62RDhtI-uRxAN@neVML20eYh^<dUYRL`u+86SWHn4?ij00000n8cZGae2Zp
00FXz0f49h($4W<vBYQl0ssI200dcD
""",
)
# COMBO-END


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
JB_TOASTY_NCH = 4               # personnages au plus (= TO_NCH de core.S) : un est tire au sort a chaque economiseur
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


def _jb_builtin_combo():
    """Les 4 sons du combo Bas + Start (JB_COMBO_SND_B85) -> liste de (ADPCM-A, echantillons utiles), vide s'ils ont ete retires."""
    import lzma
    out = []
    for b, used in zip(JB_COMBO_SND_B85, JB_COMBO_SND_USED):
        b = "".join(b.split())
        if b and used:
            out.append((lzma.decompress(base64.b85decode(b)), used))
    return out


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
    converties, dans JB_BOXES_B85 ; ou GIF anime a fond magenta, une image par image du GIF, 2.5.32) : images
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
    if path.lower().endswith(".gif"):                   # GIF anime (2.5.32) : une image par fenetre, meme fenetre pour toutes
        im = Image.open(path)
        fr = []
        for i in range(min(getattr(im, "n_frames", 1), JB_BOX_MAX)):
            im.seek(i)
            fr.append(np.asarray(im.convert("RGB")).astype(np.int16))
        if len({f.shape for f in fr}) != 1:
            raise ValueError("GIF frames must all have the same size")
        fm = [(f[..., 0] > 200) & (f[..., 1] < 70) & (f[..., 2] > 200) for f in fr]
        ys, xs = np.nonzero(~np.logical_and.reduce(fm))
        if not len(ys):
            raise ValueError("no frame found (the GIF must be on a magenta #FF00FF background)")
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1       # fenetre commune : rotation centree
        a = np.concatenate([f[y0:y1, x0:x1] for f in fr])
        mag = np.concatenate([m[y0:y1, x0:x1] for m in fm])
        ch, cw = int(y1 - y0), int(x1 - x0)
        cells = [((i * ch, (i + 1) * ch), (0, cw)) for i in range(len(fr))]
    else:
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
               saver_text=None):
    """Écrit la cartouche dans outdir, dans un ou plusieurs formats :
      mame     : set ngjb.zip (fichiers ROM a la racine du zip) + liste logicielle hash/neogeo.xml
                 (mame neogeo ngjb -hashpath hash -rompath .)
      darksoft : dossier darksoft/ngjb/ (prom, srom, m1rom, vroma0, crom0, fpga) pour le Darksoft Multi
      neosd    : fichier neosd/ngjb.neo (TerraOnion NeoSD)
    boxes : planches des objets animes de l'economiseur (voir jb_box_frames), chemins separes par des virgules (6 au
    plus : les 5 premieres volent a parts egales, la 6e est le CD fixe en haut a droite ; PNG ou GIF anime) ; None = planches integrees, chacune remplacee par jukebox_boxes(n).png s'il est a cote du programme ; "" = sans objets.
    toasty : option unique « Toasty Delta Island » : True = les 4 portraits (un tire au sort a chaque economiseur, au premier
    changement de piste ; voir core.S) ET le son integre (voie ADPCM-A la moins utilisee des albums, empruntee le temps du
    cri) ; False = ni l'un ni l'autre (bloc toastydata a zero, aucune tuile, aucun son).
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
    snd = _jb_builtin_sound() if toasty else None
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
        combo = _jb_builtin_combo()[:4]
        for k, (cadp, cused) in enumerate(combo):         # 2.5.36 : sons du combo Bas + Start (Z80 : FF 08..0B, sfxx)
            cs = -(-len(vrom) // 256) * 256
            if cs // MB != (cs + len(cadp) - 1) // MB:
                cs = -(-cs // MB) * MB
            if cs + len(cadp) > JB_PROFILES[profile]["vrom"]:
                raise ValueError(f"Toasty combo sound {k + 1}: no room left in the V-ROM ({len(cadp)} bytes needed)")
            vrom = vrom.ljust(cs, b"\x80") + cadp
            cticks = int(math.ceil(len(cadp) * 2 / JB_ADPCMA_RATE / JB_TICK_SEC)) + 35
            struct.pack_into("<HHH", m1, JB_SFX_OFF + 11 + 6 * k, cs // 256, (cs + len(cadp)) // 256 - 1, cticks)
        if combo:
            sfx_note += (f"Toasty combo: {len(combo)} sounds ({', '.join(f'{u / JB_ADPCMA_RATE:.2f} s' for _, u in combo)}), "
                         f"one drawn at random when DOWN + START are pressed while the Toasty portrait is on screen, "
                         f"then the screen saver stops (same ADPCM-A voice {ch + 1}).\n")
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
              + ("Screen saver: \"Toasty Delta Island\" ON: one of " + str(len(to)) + " portraits (drawn at random, never the same twice in a row) shows up\n"
                 "once per screen saver, bottom right, in front of everything, when the next track starts (not in LOOP\n"
                 "mode, where the track never changes).\n"
                 "Pictures: portraits of real people, all rights reserved (Aurelien / Bouz for the first one).\n"
                 + (sfx_note + "The Toasty sound and the combo sounds are Mortal Kombat II / 3 sounds, (c) Midway / Warner Bros.: do not distribute this cartridge.\n"
                    if sfx_note else "Toasty sound: none (removed from this program).\n")
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
              "Screen saver after 5 minutes without a press (sine scroll demo screen, mini VU meter, track banner at\n"
              "each track change); any press wakes it.\n\n"
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
        ttk.Checkbutton(sv, text='Toasty Delta Island', variable=self.v_toasty,
                        command=lambda: self.settings.__setitem__("cart_toasty", bool(self.v_toasty.get()))
                        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))
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
            report, files = build_cart(self.pack, self.v_prof.get(), bios, d, formats=fm, toasty=bool(self.v_toasty.get()),
                                       saver_text=self.v_stext.get())
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
            cart_saver_text=cart.v_stext.get(),
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
    ap.add_argument("--boxes", metavar="PNG[,PNG...]", help=f"with --cart --out: one to {JB_BOX_NP} picture sheets of objects rotating in the screen saver (frames on a magenta #FF00FF background, read row by row, or an animated GIF on magenta; the first five sheets fly in equal shares, in turn; a sixth sheet is the fixed CD at the top right); default: the built-in sheets, each one replaced by {JB_BOX_FILES[0]} ... {JB_BOX_FILES[-1]} of the same number if present next to the program; \"\" = none")
    ap.add_argument("--toasty", action="store_true", help='with --cart --out ("Toasty Delta Island"): a portrait (one of the built-in ones, drawn at random) shows up in the screen saver (bottom right, in front of everything), once per screen saver, when the next track starts, with the built-in Toasty sound; pressing DOWN + START (player 1) while the portrait is on screen plays one of 4 built-in Mortal Kombat 3 sounds at random, then the screen saver stops')
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
            report, files = build_cart(pk, a.profile, bios, a.out, formats=fm, boxes=a.boxes, toasty=a.toasty,
                                       saver_text=a.saver_text)
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
