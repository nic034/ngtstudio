# NGT Studio 2.5.23: Neo Geo music. Extract it, listen to it, build a jukebox cartridge

*Version française plus bas.*

> ## ⚠️ YOU NEED YOUR OWN `neogeo.zip` (Neo Geo BIOS)
>
> **It is NOT included in this archive and never will be.** It is SNK's copyrighted BIOS and cannot be
> redistributed. Use the `neogeo.zip` file from your MAME installation, in the usual MAME set.
>
> - **Jukebox cartridge**: `neogeo.zip` is **required**. The build reads two small items from it: the cartridge
>   security block (without it the BIOS refuses the cartridge) and the system font. There is no fallback: no `neogeo.zip`, no jukebox ROM.
> - **Where to put it** (one of the two): next to `NGT_Studio.exe` / `ngt_studio.py`, or in the folder of the last
>   Neo Geo ROM you opened in the Extract tab (usually your MAME `roms` folder). It is then found automatically;
>   otherwise NGT Studio tells you where it looked and asks for it. It is checked before use (security block + font).
> - **Testing the jukebox in MAME**: MAME also needs `neogeo.zip`, in the ROM folder.
> - **Extracting and listening** (Extract / Player tabs): `neogeo.zip` is **not** needed, only the game romsets
>   (also yours, not included).
>
> A jukebox ROM you build contains these two items of the BIOS. Share the tool, not the built ROMs.

NGT Studio rips the music of Neo Geo games from your own MAME romsets. It emulates the sound hardware
(Z80 + YM2610), plays the music with visualisations and exports albums. It also builds a **playable jukebox
cartridge**: a MAME set, a Darksoft Multi folder and a NeoSD `.neo` file.

## What's in this archive

| Path | Content |
|---|---|
| `ngt_studio.py` | The whole application (GUI + command line), in one file. The emulation engine, the 68000 jukebox program, the Z80 driver and the interface tiles are embedded in it, built from the sources below. |
| `m1render/` | C++ source of the emulation engine (Z80 + YM2610) and its `Makefile`. It also compresses the jukebox streams (`--lzss-batch`, same result as the Python `lzss_compress`, which remains the fallback). |
| `jukebox_rom/src/` | Jukebox cartridge sources: `jukebox.S` (68000, GNU as syntax) and `m1drv.asm` (Z80, z80asm). `parts/` holds the pieces `jukebox.S` is made of. `parts/theme_calm/` is an alternative, calmer colour theme. |
| `jukebox_rom/tools/` | `tiles.py` (custom fix-layer tiles), `tbuild.py` (assembles the sources and can build a MAME test set), `mock.py` (screen mock-up). |
| `jukebox_rom/mame_tests/` | MAME Lua scripts used for testing (pad simulation, endurance test, video capture). |
| `jukebox_rom/NOTES_JUKEBOX.md` | Technical notes (in French): formats, protocol, pitfalls, test results. |
| `tests/` | Development test scripts. They expect your own `.ngt` files under `./testdata/`. |
| `windows/` | Files used to build the Windows executable (`build_exe.bat` → `build_exe.py`, icon, version resource, Windows README and notices). |
| `CHANGES.txt` · `CHANGELOG.txt` · `LICENSE` · `THIRD_PARTY_NOTICES.md` | Short changelog, version by version · full version history · MIT License · licences of the bundled libraries. |

## Using it

Requirements: Python 3.8 or later, with tkinter (on Linux, install the `python3-tk` package). `numpy` is required.
`sounddevice`, `Pillow` and `soundfile` are optional (scipy is no longer used since 2.5.14). All of these are installed automatically on first launch.
The engine is embedded for Windows x86-64 and Linux x86-64 (`_ENGINE_B64`, xz + base85; the Linux copy is built with
`-ffunction-sections -fdata-sections -Wl,--gc-sections -s`, which only drops unused code and symbols).
On other systems, build it (see below) and keep the `m1render/` folder next to `ngt_studio.py`.

```
python ngt_studio.py                       # GUI: Extract / Player / Cartridge tabs
python ngt_studio.py --help                # command line
python ngt_studio.py --cli --src roms/aof2.zip --out albums
python ngt_studio.py --cli --src roms --out albums --min-len 45 --short loops   # short tracks: ask|skip|loops|keep
python ngt_studio.py --cart albums/aof2.ngt albums/samsho3.ngt                                # capacity check only
python ngt_studio.py --cart albums/aof2.ngt albums/samsho3.ngt --out jukebox   # build (--bios optional, see above)
python ngt_studio.py --upgrade old_folder  # converts old NGT1 files (one per track) into NGT2 (one per game)
```

**Short tracks**: for tracks shorter than 45 s (one loop included; `--min-len`, or the Extract tab), NGT Studio asks
during the extraction. By default the ones that loop are kept (short game music loops: Puzzle De Pon, Windjammers...)
and the others (jingles, stingers) are skipped; this is also what happens without an answer within 30 s (GUI) or when
not interactive (command line). A track that does not loop ends 1 s after its last sound (the trailing silence is cut).

**Early games** (Magician Lord, NAM-1975…: `v11`, `v21`, `v22` ROMs) have a separate ADPCM-B ROM: supported, the two
are merged into one V-ROM in the `.ngt` and in the jukebox.

`--profile standard` (default) uses P1 1 MB + P2 4 MB, the largest official layout without a protection chip.
`--profile extended` uses an 8 MB P2, a layout found only in homebrew. `--formats mame,darksoft,neosd` is the default.
The build is refused if any ROM exceeds 95 % of its limit.

Testing a built jukebox in MAME: the set is `ngjb.zip` (ROM files inside) with `hash/neogeo.xml`; put `neogeo.zip` in the output folder, then run
`mame neogeo ngjb -hashpath hash -rompath .`

**Jukebox controls (pad):**
- UP/DOWN: choose a track.
- LEFT/RIGHT: change game.
- A: play/pause.
- B: stop.
- C/D: previous/next track.
- START: full-screen VU meters.
- SELECT: AUTO (chains every track, then every album, endlessly; the default), LOOP (repeats one track) or RAND
  (a random track of any album, never the same twice in a row).

It plays automatically from power-on. MVS has no SELECT button, so it stays in AUTO.

Screen saver: after 5 minutes without a press, an Amiga-style demo screen: a big outlined rainbow sine scroll
("NEO GEO JUKEBOX - ENJOY FINE MUSIC !" while music plays, the wave swells with the music; "THANKS FOR USING THIS SOFTWARE"
when stopped or paused) over a very faint isometric checkerboard that scrolls and ripples like water (more and faster when the music is loud), with the album,
track, elapsed and remaining time scrolling in small yellow letters at the top and bottom. The music keeps playing.
Since 2.5.37: a mini VU meter (7 voices) top left, opposite the spinning CD; a banner with the album and "TRACK nn/nn" that
opens when the screen saver starts and at every track change; the wavy text changes colour theme at each pass (rainbow, gold,
the colours of the player screen, fire, ice).
Any press wakes it up and does nothing else.

Rotating objects: a game box, a Neo Geo console and the Delta Island logo and triangle rotate and drift
diagonally between the checkerboard and the text (2 to 8 at a time; four boxes for one object of the other sheets, which
take turns). Four sheets are built in. To use your own (1 to 6), put `jukebox_boxes.png` ... `jukebox_boxes6.png` next to
the program (each one replaces the built-in sheet of the same number, the others stay) or give them with `--boxes a.png,b.png,...` (`a.png@1.3` = 30 % larger, at most 46 px
high); `--boxes ""` = no objects. A sheet is a grid of
frames on a magenta (#FF00FF) background, read row by row; tall (box, about 30 x 42 px on screen) or wide (console,
about 56 x 40 px) is detected automatically. The built-in pictures (SNK artwork for the box and console, the author's own for the others) are NOT covered by the MIT
License (see LICENSE).

## Windows executable

A ready-to-run Windows build is distributed separately (`NGT_Studio_2.5.23_win64.zip`): unzip the whole folder and
double-click `NGT_Studio.exe` (no Python needed). It is not code-signed, so SmartScreen may warn ("More info" → "Run anyway").
To rebuild it yourself on Windows with Python 3.12: run `windows\build_exe.bat` from this folder.

## Rebuilding from source

```
cd m1render && make                         # engine (gcc + g++)   — or: python ngt_studio.py --build
cd jukebox_rom && python tools/tbuild.py    # 68000 + Z80 (needs m68k binutils: m68k-linux-gnu-as/ld/objcopy/nm, and z80asm)
```
`tbuild.py` writes `build/prom_nosec.bin`, `build/m1drv.bin` and `build/tiles.bin`.
For this release they are identical to the copies embedded in `ngt_studio.py` (`JB_PROM_B64`, `JB_M1_B64`,
`JB_TILES_B64`, zlib + base64). `tbuild.py` does not compare them for you.
`NGT_BIOS=path/neogeo.zip python tools/tbuild.py OUTDIR game.ngt…` also builds a MAME test set with the freshly
assembled code, without modifying `ngt_studio.py`.

## Honest status

- The jukebox cartridge was tested **in MAME only**:
  - the audio was compared with the reference render;
  - P2 bank switching was tested mid-song;
  - a 6-minute random pad endurance test was run.
  
  It has **not** been tested yet on a real console, a Darksoft Multi or a NeoSD.
- The Darksoft folder layout and the `fpga` value come from games that others converted (public checksum database), not from official
  documentation. The jukebox boots and plays on a Darksoft Multi-AES (UniBIOS 4.0). Still unverified on the Darksoft: the
  C ROM of the screen saver (word-interleaved `crom0`) and `fpga` with an 8 MB P2.
- MAME runs the YM2610 at 8 MHz (MVS). On an AES (8.056 MHz) tempo and pitch are 0.7 % higher, which is correct.
- Note decoding (keyboard and piano roll) was checked against the audio on 3 games: 517 of 520 FM notes are exact.

## License

NGT Studio is released under the **MIT License**, © 2026 Nicolas (Nic034); see `LICENSE`. The bundled libraries keep
their own licences, listed in `THIRD_PARTY_NOTICES.md`: ymfm (BSD 3-Clause, © Aaron Giles) and z80 (MIT, © Nicolas Allemand).
No Neo Geo game, BIOS or music is included. They remain the property of their owners (SNK and the other publishers).

---

# NGT Studio 2.5.23 : la musique Neo Geo. L'extraire, l'écouter, fabriquer une cartouche jukebox

> ## ⚠️ IL FAUT VOTRE PROPRE `neogeo.zip` (BIOS Neo Geo)
>
> **Il n'est PAS fourni dans cette archive et ne le sera pas.** C'est le BIOS de SNK, protégé par le droit
> d'auteur : il ne peut pas être redistribué. Prenez le fichier `neogeo.zip` de votre installation MAME, dans le jeu MAME habituel.
>
> - **Cartouche jukebox** : `neogeo.zip` est **obligatoire**. La construction y lit deux petits éléments : le bloc de sécurité de
>   la cartouche (sans lui le BIOS refuse la cartouche) et la police du système. Il n'y a pas de solution de repli : sans `neogeo.zip`,
>   pas de ROM jukebox.
> - **Où le mettre** (au choix) : à côté de `NGT_Studio.exe` / `ngt_studio.py`, ou dans le dossier de la dernière
>   ROM Neo Geo ouverte dans l'onglet Extract (en général votre dossier `roms` de MAME). Il est alors trouvé
>   automatiquement ; sinon NGT Studio indique où il a cherché et le demande. Il est vérifié avant usage.
> - **Tester le jukebox sous MAME** : MAME a aussi besoin de `neogeo.zip`, dans le dossier des ROM.
> - **Extraire et écouter** (onglets Extract / Player) : `neogeo.zip` n'est **pas** nécessaire, seulement les
>   romsets des jeux (à vous aussi, non fournis).
>
> Une ROM jukebox fabriquée contient ces deux éléments du BIOS. Partagez l'outil, pas les ROM construites.

NGT Studio extrait les musiques des jeux Neo Geo à partir de **vos** romsets MAME. Il émule la partie son
(Z80 + YM2610), joue les musiques avec des visualisations et exporte des albums. Il fabrique aussi une
**cartouche jukebox jouable** : un jeu MAME, un dossier Darksoft Multi et un fichier `.neo` pour NeoSD.

**Contenu** :
- `ngt_studio.py` : l'application complète, en un seul fichier. Le moteur, le programme 68000, le driver Z80 et les tuiles y sont intégrés.
- `m1render/` : le moteur C++.
- `jukebox_rom/` : les sources 68000 et Z80, les outils, les scripts de test MAME et les notes techniques `NOTES_JUKEBOX.md`.
- `tests/` : les scripts de test de développement.
- `CHANGES.txt` (changelog court, version par version), `CHANGELOG.txt` (historique complet), `LICENSE` et `THIRD_PARTY_NOTICES.md`.

**Utilisation** : Python 3.8 ou plus récent, avec tkinter. Les modules sont installés automatiquement au premier lancement.
Lancez `python ngt_studio.py` pour l'interface, ou `python ngt_studio.py --help` pour la ligne de commande.
Construction du jukebox : `python ngt_studio.py --cart a.ngt b.ngt --bios neogeo.zip --out jukebox`. La construction est refusée
si une ROM dépasse 95 % de sa limite.
Test sous MAME : le set est `ngjb.zip` (fichiers ROM dedans) avec `hash/neogeo.xml` ; mettez `neogeo.zip` dans le dossier de sortie, puis lancez `mame neogeo ngjb -hashpath hash -rompath .`

**Pistes courtes** : pour les pistes de moins de 45 s (une boucle comprise ; réglable, `--min-len`), la question est
posée pendant l'extraction. Par défaut, celles qui bouclent sont gardées (musiques à boucle courte : Puzzle De Pon,
Windjammers…) et les autres (jingles) ignorées ; c'est aussi le choix appliqué sans réponse en 30 s (interface) ou hors
console interactive (ligne de commande). Une piste qui ne boucle pas s'arrête 1 s après son dernier son (le silence
final est coupé).

**Manette du jukebox** :
- HAUT/BAS : choix de la piste.
- GAUCHE/DROITE : changement de jeu.
- A : lecture/pause.
- B : stop.
- C/D : piste précédente/suivante.
- START : vumètres plein écran.
- SELECT : AUTO (enchaîne toutes les pistes puis tous les albums, sans fin ; mode par défaut), LOOP (répète la piste)
  ou RAND (une piste au hasard parmi tous les albums, jamais deux fois la même de suite).

La lecture démarre automatiquement à l'allumage. Le MVS n'a pas de bouton SELECT : il reste en AUTO.

Économiseur d'écran : après 5 minutes sans appui, un écran de démo façon Amiga : grand texte arc-en-ciel cerné de noir
en sine scroll (« NEO GEO JUKEBOX - ENJOY FINE MUSIC ! » pendant la lecture, la vague gonfle avec la musique ; « THANKS FOR
USING THIS SOFTWARE » à l'arrêt ou en pause) sur un damier isométrique très léger qui défile et ondule comme de l'eau (plus fort et plus vite quand la musique monte),
avec l'album, la piste, le temps écoulé et restant qui défilent en petit, en jaune, en haut et en bas. La musique
continue. Un appui le réveille, sans autre effet.

Objets animés : une boîte de jeu, une console Neo Geo, le logo et le triangle Delta Island tournent et
glissent en diagonale entre le damier et le texte (de 2 à 8 à la fois ; quatre boîtes pour un objet des autres planches,
qui passent chacune à leur tour). Quatre planches sont intégrées. Pour utiliser les vôtres (1 à 6), posez
`jukebox_boxes.png` ... `jukebox_boxes6.png` à côté du programme (chacune remplace la planche intégrée de même numéro, les autres restent) ou `--boxes a.png,b.png,...`
(`a.png@1.3` = 30 % plus grande, 46 px de haut au plus) ; `--boxes ""` = sans objets. Une planche est une grille d'images sur fond magenta (#FF00FF),
lue ligne par ligne ; haute (boîte, environ 30 x 42 px à l'écran) ou large (console, environ 56 x 40 px), détecté tout
seul. Les images intégrées (visuels SNK pour la boîte et la console, de l'auteur pour les autres) ne sont PAS sous licence MIT (voir LICENSE).

**Exécutable Windows** : distribué à part (`NGT_Studio_2.5.23_win64.zip`). Décompressez tout le dossier et lancez `NGT_Studio.exe` (sans Python). Il n'est pas signé, donc SmartScreen peut avertir (« Informations complémentaires » → « Exécuter quand même »). Pour le refaire soi-même : `windows\build_exe.bat`.

**Recompiler** : lancez `cd m1render && make` (ou `python ngt_studio.py --build`), puis `cd jukebox_rom && python tools/tbuild.py`.
Il faut les binutils m68k et z80asm. Pour cette version, les binaires obtenus sont identiques à ceux intégrés dans `ngt_studio.py`.

**État réel** :
- La cartouche jukebox a été testée **sous MAME uniquement** : son comparé au rendu de référence, changement de banque P2 en
  plein morceau, test d'endurance manette de 6 min. Elle n'a **pas encore** été testée sur console réelle, Darksoft Multi ou NeoSD.
- Le format Darksoft et la valeur `fpga` viennent de jeux convertis par d'autres, pas d'une documentation officielle.

**Licence** : MIT, © 2026 Nicolas (Nic034). Les bibliothèques incluses gardent leur licence : ymfm en BSD 3-Clause, z80 en MIT.
Aucun jeu, BIOS ni musique Neo Geo n'est inclus.
