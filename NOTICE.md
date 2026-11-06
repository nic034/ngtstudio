# Notice: what the MIT License covers, and what it does not

*Version française plus bas.*

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

---

# Avis : ce que couvre la licence MIT, et ce qu'elle ne couvre pas

La [licence MIT](LICENSE) (© 2026 Nicolas (Nic034)) couvre **le code écrit pour NGT Studio** : `ngt_studio.py`,
`sources/m1render/m1render.cpp`, `sources/jukebox_rom/` (sources 68000 et Z80, outils, tests Lua), `sources/tests/`,
`sources/windows/` (scripts de construction) et la documentation.

## Non couverts par la licence MIT

1. **Les jeux, BIOS et musiques Neo Geo.** Aucun n'est fourni dans ce dépôt. Ils restent la propriété de SNK et des autres éditeurs
   et ayants droit. Il vous faut votre propre `neogeo.zip` et vos propres romsets, obtenus légalement.
   - Une ROM jukebox construite avec NGT Studio contient deux petits éléments pris dans **votre** `neogeo.zip` (le bloc de
     sécurité de la cartouche et la police du système) et les données musicales de **vos** romsets. Ces ROM construites ne sont
     pas placées sous licence par ce projet et **ne doivent pas être diffusées**. Partagez l'outil, pas les ROM construites.
2. **Les images intégrées de l'économiseur d'écran** (dans `ngt_studio.py`, `JB_BOXES_B85`, et dans les tuiles du jukebox) :
   - la **boîte de jeu** et la **console Neo Geo** montrent des illustrations et des marques de SNK, © SNK. Elles ne sont pas sous licence MIT ;
   - le **logo et le triangle Delta Island** et l'**icône de CD qui tourne** sont des œuvres de l'auteur (Nic034 / Delta Island),
     **tous droits réservés**. Elles ne sont pas sous licence MIT. Elles peuvent être utilisées, sans modification, dans NGT Studio
     et dans les cartouches jukebox qu'il construit pour un usage personnel ; tout autre usage requiert l'accord de l'auteur.
   - Vous pouvez remplacer toutes les images intégrées par les vôtres (`jukebox_boxes.png` … `jukebox_boxes6.png` ou `--boxes`) ;
     une image que vous fournissez reste la vôtre.
3. **Composants tiers**, qui gardent leur propre licence, voir [`sources/THIRD_PARTY_NOTICES.md`](sources/THIRD_PARTY_NOTICES.md) :
   ymfm (BSD 3-Clause, © Aaron Giles) et l'émulateur z80 (MIT, © Nicolas Allemand), tous deux compilés dans le moteur intégré.
   Une version Windows que vous construisez vous-même embarque aussi Python, Tcl/Tk, numpy, Pillow, sounddevice, soundfile,
   libsndfile (LGPL 2.1), cffi et le bootloader PyInstaller : voir `sources/windows/THIRD_PARTY_NOTICES_WINDOWS.txt`.
4. **Images et noms récupérés sur Internet pendant l'utilisation du lecteur** (captures d'écran de thumbnails.libretro.com, titres
   complets de l'Arcade Database) : ils appartiennent à leurs auteurs, sont conservés dans un dossier temporaire supprimé à la
   fermeture du programme et ne font jamais partie d'une ROM construite.

## Marques

Neo Geo et SNK sont des marques de leur titulaire. MAME, Darksoft, NeoSD, Yamaha et YM2610 sont des noms appartenant à leurs
propriétaires respectifs, cités uniquement pour dire avec quoi NGT Studio fonctionne. Ce projet est indépendant et **sans lien avec eux,
ni approuvé ni parrainé par eux**.
