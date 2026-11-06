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
