# Mentions légales

*Résumé en anglais en bas de page / English summary at the bottom.*

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

## 4. Marques et absence d'affiliation

Neo Geo et SNK sont des marques de leur titulaire. MAME, Darksoft, NeoSD, Yamaha, YM2610, libretro et Arcade Database sont des
noms appartenant à leurs propriétaires respectifs, cités uniquement pour indiquer avec quoi NGT Studio fonctionne ou d'où il récupère
des informations. NGT Studio est un projet de fan indépendant : il n'est **ni affilié, ni approuvé, ni parrainé** par SNK ni par aucun
de ces ayants droit.

## 5. Jeux, BIOS et musiques : aucun contenu protégé n'est distribué

- Ce dépôt **ne contient aucun jeu, aucun BIOS et aucune musique** de la Neo Geo. Ils restent la propriété de SNK et des autres
  ayants droit.
- L'utilisateur doit disposer de ses **propres** romsets et de son **propre** `neogeo.zip`, obtenus légalement. Il est **seul
  responsable** de l'usage qu'il fait du logiciel et du respect de la loi applicable dans son pays (droit d'auteur, exceptions de copie
  privée, protections techniques).
- Une ROM jukebox construite par le logiciel contient la musique de **vos** romsets et deux petits éléments de **votre** `neogeo.zip`
  (bloc de sécurité de la cartouche, police du système). **Ne diffusez pas ces ROM construites** : partagez l'outil, pas les ROM.
- Les fichiers `.ngt` produits ne contiennent que des données numériques pour le YM2610 / Z80 tirées des jeux de l'utilisateur ; ils
  ne sont pas davantage libres de droits et ne doivent pas être diffusés.
- Si vous êtes titulaire de droits et estimez qu'un élément de ce dépôt porte atteinte à vos droits, écrivez à l'éditeur (voir 1) : il sera
  examiné et retiré rapidement si nécessaire.

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

---

## English summary

- **Publisher**: Nicolas, alias Nic034, a personal, free project. Contact through an issue on <https://github.com/nic034/ngtstudio/issues>
  or the GitHub profile <https://github.com/nic034>. **Host**: GitHub, Inc., 88 Colin P. Kelly Jr. Street, San Francisco, CA 94107, USA.
- **Licence**: code under the MIT License. Not covered: SNK artwork, the author's own artwork, games, BIOS, music, third-party
  components (see [`NOTICE.md`](NOTICE.md)).
- **No game, BIOS or music is distributed.** Bring your own `neogeo.zip` and romsets. Do not distribute the ROMs you build with the tool.
- **Not affiliated with SNK**, MAME, Darksoft, NeoSD or any game publisher. Neo Geo and SNK are trademarks of their owner.
- **Privacy**: no personal data is collected and nothing is sent to the author. Optional network requests: PyPI at first launch,
  `thumbnails.libretro.com` and `adb.arcadeitalia.net` while the player runs. Local files: two caches, a diagnostic log, a temporary folder.
- **Warranty**: provided "as is"; not verified on every real console or flash cartridge, use at your own risk.
- **Rights holders**: contact the publisher to have any item reviewed and removed.
