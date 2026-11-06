# NGT Studio

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
