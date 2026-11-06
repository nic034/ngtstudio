# Mentions légales

Ces mentions concernent le dépôt GitHub **nic034/ngtstudio** et le logiciel **NGT Studio** qui y est publié
(article 6 de la loi n° 2004-575 du 21 juin 2004 pour la confiance dans l'économie numérique).

## 1. Éditeur et contact

- **Éditeur** : Nicolas, alias **Nic034**, auteur du logiciel. Projet personnel, distribué gratuitement.
- **Contact** : par une *issue* sur ce dépôt (<https://github.com/nic034/ngtstudio/issues>) ou via le profil GitHub
  <https://github.com/nic034>. Site de l'auteur : <https://nic034.fr>.
- **Directeur de la publication** : l'éditeur.

## 2. Hébergeur

Le dépôt est hébergé par **GitHub, Inc.**, 88 Colin P. Kelly Jr. Street, San Francisco, CA 94107, États-Unis
(<https://github.com>). Les données de navigation sur GitHub sont traitées par GitHub selon sa propre politique de confidentialité.

## 3. Licence et propriété intellectuelle

- Le code de NGT Studio est publié sous **licence MIT** (fichier [`LICENSE`](LICENSE)), © 2026 Nicolas (Nic034).
- La licence MIT **ne couvre pas** certains éléments (images intégrées, jeux, BIOS, musiques, composants tiers) : voir [`NOTICE.md`](NOTICE.md).
- Les bibliothèques tierces gardent leur licence : [`sources/THIRD_PARTY_NOTICES.md`](sources/THIRD_PARTY_NOTICES.md).

## 4. SNK, éditeurs et développeurs des jeux : droits et absence d'affiliation

**Titulaires de droits.** Neo Geo, SNK, le BIOS de la console, les jeux, leurs titres, personnages, logos, graphismes, musiques, sons et
données sonores sont des œuvres et des marques protégées, qui appartiennent à **SNK Corporation** (anciennement SNK Playmore) pour ce qui
la concerne, et, pour les autres jeux sortis sur Neo Geo, à **leurs éditeurs, développeurs et compositeurs respectifs** ou à leurs
ayants droit. NGT Studio ne revendique aucun droit sur ces éléments, et la licence MIT du code **ne donne aucun droit** sur eux.

**Absence d'affiliation.** NGT Studio est un projet de fan indépendant. Il n'est **ni affilié, ni approuvé, ni parrainé, ni
validé** par SNK, par un éditeur ou un développeur de jeu, ni par MAME, Darksoft, NeoSD, Yamaha, libretro ou Arcade Database. Ces noms
(ainsi que YM2610) appartiennent à leurs propriétaires respectifs et ne sont cités que pour indiquer avec quoi NGT Studio fonctionne ou
d'où il récupère des informations. Les titres de jeux affichés par le logiciel et les captures d'écran récupérées sur Internet
appartiennent à leurs titulaires.

**Ce que ce dépôt ne contient pas.** Aucun jeu (ROM), aucun BIOS, aucune musique, aucun fichier audio, aucune capture d'écran et aucun
code de jeu de la Neo Geo. Les illustrations intégrées qui représentent du matériel ou un jeu SNK (la boîte de jeu et la console de l'économiseur
d'écran) sont © SNK et ne sont pas sous licence MIT : voir [`NOTICE.md`](NOTICE.md).

**Ce que l'utilisateur doit faire.**
- Disposer de ses **propres** romsets et de son **propre** `neogeo.zip`, obtenus légalement. NGT Studio n'est pas fait pour pirater et
  ne fournit aucun moyen de se procurer des jeux ou des BIOS.
- N'utiliser les albums `.ngt` et les ROM jukebox construites que pour un **usage personnel**. Ces fichiers contiennent des données
  musicales tirées des jeux (œuvres protégées) et, pour les ROM, deux éléments du BIOS : **ne pas les diffuser, ni les publier, ni les
  vendre**. Ce projet n'autorise pas la diffusion ni la vente de cartouches ou de fichiers contenant la musique ou le BIOS d'un jeu,
  et ne donne aucun droit pour le faire.
- Respecter la loi applicable dans son pays (droit d'auteur, exceptions de copie privée, protections techniques) : il en est **seul
  responsable**. L'éditeur du logiciel ne donne aucun avis juridique.

**Retrait à la demande.** Si vous êtes titulaire de droits (SNK, éditeur, développeur, compositeur) et estimez qu'un élément de ce dépôt
porte atteinte à vos droits, écrivez à l'éditeur (voir 1) en indiquant l'élément concerné : il sera examiné et retiré sans délai si
nécessaire.

## 5. Autres marques

Les autres noms de produits ou de sociétés cités dans ce dépôt (Python, Windows, GitHub, etc.) appartiennent à leurs propriétaires respectifs.

## 6. Données personnelles et accès réseau

- NGT Studio **ne collecte aucune donnée personnelle**, n'a ni compte, ni publicité, ni statistiques, et n'envoie rien à l'éditeur.
- Le logiciel fonctionne localement. Il ne se connecte à Internet que dans les cas suivants :
  - **Premier lancement** : installation automatique des modules Python manquants (`numpy`, `sounddevice`, `Pillow`, `soundfile`) depuis PyPI.
  - **Lecteur** : récupération des captures d'écran des jeux sur `thumbnails.libretro.com` et du titre complet d'un jeu sur
    l'Arcade Database (`adb.arcadeitalia.net`, le nom court MAME du jeu, par exemple `kof98`, est envoyé). Ces serveurs voient, comme
    tout serveur web, votre adresse IP et un agent utilisateur `NGT-Studio/<version>`. Sans connexion, le logiciel fonctionne sans ces
    informations.
  - **Commande de diagnostic manuelle** `--probe-pics` (uniquement si vous la lancez) : interroge aussi une recherche d'images Google.
- Fichiers écrits sur votre ordinateur : cache des noms `~/.ngt_studio_names.json`, cache `~/.ngt_studio_pics_index.json`, journal de
  diagnostic `ngt_studio.log` (à côté du programme, sinon dans le dossier temporaire ; version, système, erreurs ; jamais envoyé), dossier
  temporaire des images supprimé à la fermeture. Vous pouvez supprimer ces fichiers à tout moment.

## 7. Garantie et responsabilité

Le logiciel est fourni **« tel quel », sans garantie d'aucune sorte** (voir la licence MIT). La cartouche jukebox a été testée dans MAME
et sur une Darksoft Multi-AES, mais **pas sur tous les matériels réels ni toutes les cartouches flash** : vous l'utilisez à vos risques,
et l'éditeur ne peut être tenu responsable d'un dommage causé à une console, une cartouche, des fichiers ou des données.

## 8. Droit applicable

Les présentes mentions et l'utilisation de ce dépôt sont soumises au droit français, sous réserve des dispositions impératives
applicables à l'utilisateur dans son pays de résidence.
