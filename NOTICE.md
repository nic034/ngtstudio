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
