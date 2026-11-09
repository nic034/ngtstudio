# Notice: what the MIT License covers, and what it does not

The [MIT License](LICENSE) (© 2026 Nicolas (Nic034)) covers **the code written for NGT Studio**:
`ngt_studio.py`, `sources/m1render/m1render.cpp`, `sources/jukebox_rom/` (68000 and Z80 sources, tools, Lua tests),
`sources/tests/`, `sources/windows/` (build scripts) and the documentation.

## Not covered by the MIT License

1. **Neo Geo games, BIOS and music.** None is included in this repository. They remain the property of SNK and of the
   other publishers and rights holders. You need your own legally obtained `neogeo.zip` and romsets.
   - A jukebox ROM built with NGT Studio contains two small items taken from **your** `neogeo.zip` (the cartridge
     security block and the system font) and the music data taken from **your** romsets. These built ROMs are not licensed
     by this project and **must not be distributed**. Share the tool, not the built ROMs.
2. **The built-in screen-saver pictures** (embedded in `ngt_studio.py`, `JB_BOXES_B85`, and in the jukebox tiles):
   - the **game box** and the **Neo Geo console** show SNK artwork and trademarks, © SNK. They are not licensed under the MIT License;
   - the **Delta Island logo and triangle** and the **spinning CD icon** are artwork by the author (Nic034 / Delta Island),
     **all rights reserved**. They are not licensed under the MIT License. They may be used, unmodified, as part of NGT
     Studio and of the jukebox cartridges it builds for personal use; any other use needs the author's permission.
   - You can replace every built-in picture with your own (`jukebox_boxes.png` … `jukebox_boxes6.png` or `--boxes`); a
     picture you provide stays yours.
   - the **three "Toasty" pictures** (`JB_TOASTY_B85`, `sources/jukebox_rom/art/toasty_frame.png`, `toasty_frame_2.png`,
     `toasty_frame_3.png`, used only when the Toasty option is ticked) are portraits of real people, **all rights reserved**
     by their authors. They are not licensed under the MIT License and may not be reused, copied or modified outside NGT
     Studio without the permission of their authors. First one ("Aurelien - Toasty"): **© Aurelien / Bouz**; its mug shows
     a Pac-Man design (© Bandai Namco). Rights holders of the two other portraits: to be completed by the project author
     (see `sources/jukebox_rom/art/RIGHTS.txt`).
   - the **Toasty sound** (`JB_TOASTY_SND_B85`, since 2.5.28) is the **"Toasty!" shout of Mortal Kombat II, © Midway
     Games / Warner Bros.** It is **not** covered by the MIT License and this project has no licence for it: converting it
     to ADPCM-A does not change its rights. It is embedded at the project author's own decision and risk, and can be
     removed at any time (empty `JB_TOASTY_SND_B85` and set `JB_TOASTY_SND_USED = 0`; the option then plays no sound, or
     the file you give). Untick "Toasty sound" (or `--no-toasty-sound`) to build a cartridge without it. A cartridge built
     with it contains that sound: like every built ROM, **do not distribute it**. If you redistribute NGT Studio, you
     redistribute the sound too: remove it first if you have no right to share it.
3. **Third-party components**, which keep their own licences, see [`sources/THIRD_PARTY_NOTICES.md`](sources/THIRD_PARTY_NOTICES.md):
   ymfm (BSD 3-Clause, © Aaron Giles) and the z80 emulator (MIT, © Nicolas Allemand), both compiled into the embedded engine.
   A Windows build you make yourself also bundles Python, Tcl/Tk, numpy, Pillow, sounddevice, soundfile, libsndfile
   (LGPL 2.1), cffi and the PyInstaller bootloader: see `sources/windows/THIRD_PARTY_NOTICES_WINDOWS.txt`.
4. **Pictures and names fetched from the Internet while the player runs** (game screenshots from thumbnails.libretro.com,
   full game titles from the Arcade Database): they belong to their authors, are kept in a temporary folder deleted when the
   program closes, and are never part of a built ROM.

## Trademarks

Neo Geo and SNK are trademarks of their owner. MAME, Darksoft, NeoSD, Yamaha and YM2610 are names of their respective
owners, used only to say what NGT Studio works with. This is an independent project, **not affiliated with, endorsed by or
sponsored by** any of them.
