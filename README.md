# NGT Studio

*[Version française plus bas](#ngt-studio--version-française)*

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
| `LICENSE` · `NOTICE.md` · `MENTIONS_LEGALES.md` · `sources/THIRD_PARTY_NOTICES.md` | MIT licence · what it does not cover · legal notice (FR, with an English summary) · third-party licences. |

## Status

- The jukebox cartridge was tested **in MAME** (7 BIOS: MVS and AES, original and UniBIOS) and boots and plays on a
  Darksoft Multi-AES (UniBIOS 4.0). It has **not** been verified on every real hardware / flash cartridge: use it at your own risk.
- Latest version: **2.5.25**. Version history: [`sources/CHANGELOG.txt`](sources/CHANGELOG.txt) (short version: [`sources/CHANGES.txt`](sources/CHANGES.txt)).

## License and legal

- Code: **MIT License**, © 2026 Nicolas (Nic034), see [`LICENSE`](LICENSE).
- **Not covered by the MIT License**: the built-in screen-saver pictures (SNK artwork, author's artwork), and of course every
  game, BIOS and music. Details in [`NOTICE.md`](NOTICE.md).
- Third-party libraries (ymfm, z80, and the components of the Windows build): [`sources/THIRD_PARTY_NOTICES.md`](sources/THIRD_PARTY_NOTICES.md).
- Legal notice (publisher, host, trademarks, network access, privacy, liability): [`MENTIONS_LEGALES.md`](MENTIONS_LEGALES.md).
- NGT Studio is an independent fan project, **not affiliated with, endorsed by or sponsored by SNK**, MAME, Darksoft, NeoSD or any game publisher.
  Neo Geo and SNK are trademarks of their owner.

---

# NGT Studio : version française

**La musique Neo Geo : l'extraire, l'écouter, fabriquer une cartouche jukebox.**

NGT Studio est un utilitaire Windows / Linux / Python (interface graphique + ligne de commande) qui extrait la musique des
jeux Neo Geo à partir de **vos propres romsets MAME** (`.zip`). Un lecteur intégré émule le matériel sonore d'origine
(Z80 + YM2610) et joue la musique avec des visualisations. Les albums sont enregistrés dans de petits fichiers `.ngt` qui
ne contiennent que des données numériques pour le YM2610 / Z80 (index, flux, samples) : ni enregistrement audio, ni code de jeu.

Il peut aussi construire à la volée une **ROM jukebox jouable** pour MAME et pour les cartouches Darksoft Multi et NeoSD Pro,
afin d'emporter votre musique préférée sur une vraie Neo Geo.

> ## ⚠️ Il vous faut vos propres fichiers
>
> - **Romsets des jeux** : non fournis, ils restent la propriété de leurs ayants droit.
> - **`neogeo.zip` (BIOS Neo Geo)** : non fourni et ne le sera jamais (BIOS de SNK, protégé par le droit d'auteur). Il est
>   **obligatoire pour construire une cartouche jukebox** (la construction y lit le bloc de sécurité de la cartouche et la police du
>   système) et pour la tester dans MAME. L'extraction et l'écoute n'en ont **pas** besoin.
> - Une ROM jukebox construite contient ces deux petits éléments du BIOS : **partagez l'outil, pas les ROM construites.**

## Fonctions

- **Extract** : trouve la musique d'un romset, détecte boucles et doublons, coupe le silence final, garde les courtes pistes qui bouclent.
- **Player** : lit les albums avec un YM2610 émulé, vumètres, clavier et piano roll, captures d'écran des jeux.
- **Cartridge** : construit une ROM jukebox (set MAME `ngjb.zip`, dossier Darksoft Multi, `.neo` NeoSD) à partir de plusieurs albums, avec contrôle de capacité.
- **ROM jukebox** : commandes à la manette (A lecture/pause, B stop, C/D piste précédente/suivante, SELECT AUTO / LOOP / RAND),
  vumètres plein écran, économiseur d'écran style Amiga après 5 minutes. Fonctionne sur MVS, AES, BIOS d'origine et UniBIOS.

## Démarrage rapide

Prérequis : Python 3.8 ou plus récent avec tkinter (Linux : `python3-tk`). Les autres modules (`numpy`, et en option
`sounddevice`, `Pillow`, `soundfile`) sont installés depuis PyPI au premier lancement.

```
python ngt_studio.py                                                     # interface : Extract / Player / Cartridge
python ngt_studio.py --cli --src roms/aof2.zip --out albums              # extraction en ligne de commande
python ngt_studio.py --cart albums/aof2.ngt albums/samsho3.ngt --out jukebox   # construire une cartouche jukebox
python ngt_studio.py --help
```

Tester un jukebox construit dans MAME (mettre `neogeo.zip` dans le dossier de sortie) :
`mame neogeo ngjb -hashpath hash -rompath .`

Le `hash/neogeo.xml` produit par la construction doit être celui que MAME lit, sinon MAME affiche
`P2 00 = FIRST BANK MISSING`. Lancez MAME avec `-hashpath hash` depuis le dossier de sortie.

**Exécutable Windows** : il n'est pas conservé dans ce dépôt. Pour le fabriquer vous-même sous Windows avec Python 3.12,
lancez `sources\windows\build_exe.bat`. Un exécutable construit par vos soins n'est pas signé : SmartScreen peut avertir.

Documentation complète (options, formats, commandes, économiseur d'écran, reconstruction de la ROM et du moteur) : [`sources/README.md`](sources/README.md).

## Organisation du dépôt

| Chemin | Contenu |
|---|---|
| `ngt_studio.py` | Toute l'application en un seul fichier (même fichier que `sources/ngt_studio.py`). Le moteur, le programme 68000 du jukebox, le driver Z80 et les tuiles y sont intégrés. |
| `sources/` | Sources complètes : moteur C++ (`m1render/`), ROM jukebox (`jukebox_rom/`), tests, fichiers de construction Windows, journaux de modifications, licences. |
| `LICENSE` · `NOTICE.md` · `MENTIONS_LEGALES.md` · `sources/THIRD_PARTY_NOTICES.md` | Licence MIT · ce qu'elle ne couvre pas · mentions légales (FR, avec un résumé en anglais) · licences tierces. |

## État

- La cartouche jukebox a été testée **dans MAME** (7 BIOS : MVS et AES, d'origine et UniBIOS) et démarre et joue sur une
  Darksoft Multi-AES (UniBIOS 4.0). Elle n'a **pas** été vérifiée sur tous les matériels réels ni toutes les cartouches flash : à utiliser à vos risques.
- Dernière version : **2.5.25**. Historique : [`sources/CHANGELOG.txt`](sources/CHANGELOG.txt) (version courte : [`sources/CHANGES.txt`](sources/CHANGES.txt)).

## Licence et mentions légales

- Code : **licence MIT**, © 2026 Nicolas (Nic034), voir [`LICENSE`](LICENSE).
- **Non couverts par la licence MIT** : les images intégrées de l'économiseur d'écran (illustrations SNK, illustrations de l'auteur) et, bien sûr,
  les jeux, BIOS et musiques. Détails dans [`NOTICE.md`](NOTICE.md).
- Bibliothèques tierces (ymfm, z80, et composants de la version Windows) : [`sources/THIRD_PARTY_NOTICES.md`](sources/THIRD_PARTY_NOTICES.md).
- Mentions légales (éditeur, hébergeur, marques, accès réseau, données personnelles, responsabilité) : [`MENTIONS_LEGALES.md`](MENTIONS_LEGALES.md).
- NGT Studio est un projet de fan indépendant, **sans lien avec SNK**, MAME, Darksoft, NeoSD ni aucun éditeur de jeux, et non approuvé ni parrainé par eux.
  Neo Geo et SNK sont des marques de leur titulaire.
