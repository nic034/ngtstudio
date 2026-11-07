# Notes techniques : cartouche jukebox Neo Geo (NGT Studio 2.5.21, 26/10/2026 ; section Toasty : 2.5.26, 07/11/2026)

Ces notes décrivent l'état réel de la version 2.5.21 (2.5.21 : planches des deux puces retirées, 4 planches intégrées ; 2.5.20 : palettes écrites seulement dans le retour de trame ; 2.5.19 : mode RAND, économiseur à 5 min, animations de l'interface arrêtées pendant l'économiseur, 6 planches d'objets ; 2.5.18 : ondulation du damier plus ample, liée à la musique ; 2.5.17 : planches des objets intégrées, sortie MAME seule corrigée ; 2.5.16 : set MAME en zip `ngjb.zip` ; 2.5.15 : console isolée sur ses lignes, densité 2 à 8, 93 sprites par ligne au pire ; 2.5.14 : économiseur sine scroll + damier + infos + objets animés (planches fournies par l'utilisateur), animé par l'interruption VBlank, notes de l'en-tête animées sur 2 pixels, tuiles maison déplacées en 0xC00 ; 2.5.12 : remise à zéro ADPCM-B du driver Z80 corrigée). Le constructeur se trouve dans `ngt_studio.py` (fonctions
`jukebox_pack`, `evaluate_cart`, `layout_prom`, `build_cart`). Les sources du programme 68000 et du driver Z80
sont dans `src/`. Les binaires assemblés sont intégrés à `ngt_studio.py` en base64 + zlib : `JB_PROM_B64`, `JB_M1_B64`
et `JB_TILES_B64`.

**Le BIOS `neogeo.zip` de l'utilisateur est obligatoire pour construire. Il n'est jamais fourni.** Deux éléments y sont lus :
- le bloc de sécurité de 122 octets, recopié dans le programme en `JB_SECBLK_OFF` = 0x520A (0x1840 jusqu'à la 2.5.12, 0x1882 en 2.5.13 ; à reprendre de `nm` à chaque modification du code,
  comme `JB_BOXDATA_OFF` = 0x1A82, le bloc des objets animés) ;
- la police `sfix`, recopiée telle quelle dans la S-ROM (les tuiles maison sont posées en 0xC00-0xC35, zone de remplissage),
  et dont les caractères forment les tuiles C-ROM de l'économiseur (grand texte x5, petit texte 8x8).

## État de validation

- Validé sous MAME 0.264 uniquement :
  - les octets reçus par le Z80 sont identiques à la référence ;
  - le son MAME a été comparé au rendu de référence : écart constant d'environ 90 ms, aucune dérive sur 60 s, passage en boucle correct ;
  - 3 jeux dans une cartouche, dont un 3e jeu à V-ROM relocalisée (corrélation 0,93-0,97) ;
  - P2 en 9 Mo testée avec un changement de banque 6 → 7 en plein morceau, son identique ;
  - test d'endurance de 6 min avec des appuis aléatoires sur la manette (`fuzz.lua`), sans blocage.
- **Darksoft Multi-AES (Nicolas, UniBIOS 4.0)** : le jukebox démarre et joue (dossier `ngjb` accepté) ; c'est là qu'ont
  été vus le plantage de START (corrigé en 2.5.8), la barre B coupée et le splash UniBIOS altéré (corrigé en 2.5.14).
  Restent à vérifier sur la carte : le C-ROM du sine scroll (`crom0`, entrelacement par mots) et `fpga` = 10 avec une
  P2 de 8 Mo.
- **Non testé** : console réelle avec cartouche, NeoSD.
- MAME fait tourner le YM2610 à 8 MHz, comme le MVS. Sur AES (8,056 MHz), le tempo et la hauteur sont 0,7 % plus hauts.
  C'est le comportement attendu, pas un bug.

## Formats de cartouche

| Profil | P-ROM | V-ROM | M1 | Remarque |
|---|---|---|---|---|
| `standard` (défaut) | P1 1 Mo + P2 4 Mo | 16 Mo | 128 Ko | plus grand format officiel sans puce de protection (kof97, rbff2, lastblad, shocktr2) |
| `extended` | P1 1 Mo + P2 8 Mo | 16 Mo | 128 Ko | banque sur 3 bits, utilisé seulement par des homebrews |

- **Marge** : il faut 5 % de marge sous chaque limite (`JB_MARGIN`), sinon la construction est refusée. L'estimation compte
  la taille réelle du programme 68000 (19,9 Ko en 2.5.15, dont 9,7 Ko de tables de l'économiseur ; avant la 2.5.14,
  64 Ko étaient réservés d'office), l'index, les flux et les marqueurs de banque ; programme + index doivent tenir en P1.
- **Formats 8-9 Mo officiels non retenus** : kof99, garou, mslug3 et kof2000 utilisent la puce SMA ; mslug5, svc et kof2003 la PVC ;
  samsh5sp la K2K2. Chaque puce a son propre système de banques (registre brouillé, adresses non alignées), impossible à reproduire proprement.
- **Banque P2** : une écriture d'un mot en `$2FFFF0` sélectionne la banque de 1 Mo affichée en `$200000` (sous MAME : data & 7).
  Chaque Mo de P2 commence par un marqueur de 16 octets `NGJB BANK n ~n`, que le 68000 saute à la lecture. Au démarrage,
  toutes les banques sont vérifiées. Rien ne s'affiche si elles sont toutes présentes ; sinon une ligne rouge `P2 nn = FIRST MISSING BANK` apparaît.
- **V-ROM** : les échantillons sont relocalisés jeu par jeu (`reduce_samples_multi`, base par jeu). Un échantillon ADPCM-A ne
  traverse jamais une frontière de 1 Mo. C'est une limite matérielle du YM2610 que MAME et ymfm ne reproduisent pas.

## Fichiers produits par `build_cart`

- **MAME** : `ngjb.zip` (dossier `ngjb/` jusqu'à la 2.5.15 ; date fixe dans le zip ; fichiers et CRC identiques entre Windows et Linux, octets compressés différents selon zlib) contenant `ngjb-p1.p1`, `ngjb-p2.sp2` (si besoin), `s1`, `m1` (128 Ko), `v1..vn` (4 Mo chacun), `c1/c2` (graphismes de l'économiseur),
  et `hash/neogeo.xml`. Lancement : `mame neogeo ngjb -hashpath hash -rompath .`, avec `neogeo.zip` dans le même dossier.
  Les P-ROM sont échangées par mots, comme les jeux MAME (load16_word_swap).
- **Darksoft** : dossier `darksoft/ngjb/` contenant :
  - `prom` : les P MAME concaténées, échangées par mots ; la P2 est complétée à 4 Mo ;
  - `srom`, `m1rom`, `vroma0`, `crom0` (2 Mo : C1 / C2 entrelacées par mots de 2 octets, « word merge » selon Darksoft) ;
  - `fpga` en ASCII : `12` pour une P de 1 Mo (comme aof2), `10` pour P1 + P2 (comme kof97). Ces valeurs viennent de jeux
    convertis par d'autres (base publique de sommes de contrôle), pas d'une documentation officielle.
- **NeoSD** : `neosd/ngjb.neo`.
  - En-tête de 4096 octets, petit-boutiste : `NEO` 1, puis les tailles P, S, M, V1, V2, C, l'année, le genre, la capture, le NGH (0x0999), le nom (33 octets) et l'éditeur (17 octets).
  - Les zones suivent dans cet ordre ; C est entrelacée octet par octet (ordre MAME). Non vérifié sur NeoSD.
- `README_jukebox.txt` et `capacity.txt` : mode d'emploi et rapport de capacité.

## En-tête et contenu de la P-ROM

- En `$100` : `NEO-GEO`, NGH 0x0999 (à changer pour une vraie cartouche), pointeur long en `$182` vers le bloc de sécurité,
  eyecatcher en `$114` = 2 (ignoré, ce qui évite les graphismes du logo en C-ROM).
- Champs remplis par le constructeur :
  - `$140` = `NGJB` ;
  - `$144` = offset de l'index ;
  - `$148` = base des offsets de flux ;
  - `$14C` = nombre de banques P2 ;
  - `$14E` = occupation globale en %, affichée en haut à droite.
- **Index NGJB** :
  - en-tête : `NGJB`, u16 nombre de jeux, u16 nombre de pistes, u32 offset de la table des jeux, u32 offset de la table des pistes ;
  - entrée jeu (32 octets) : titre (24 octets), u16 première piste, u16 nombre de pistes, base V-ROM ;
  - entrée piste (32 octets) : intro_off, intro_len, loop_off, loop_len, jeu, numéro, durée (s), drapeaux, puis loop_secs en +24.

## Flux YM2610 (Z80)

- `rr vv` : écriture sur le port A (rr < 0xC0) ; `C0 rr vv` : écriture sur le port B.
- `C1 n` / `C2 lo hi` : attente en ticks ; `C3` : fin de piste.
- **1 tick = 32 échantillons** (0,57 ms) : Timer A avec NA = 992 (`0x24 = 0xF8`, `0x25 = 0`). Le driver gère lui-même le
  registre 0x27. Le constructeur supprime donc les écritures 0x24-0x26 du flux, ainsi que le mode CSM.
- Les délais sont quantifiés avec un cumul absolu, donc sans dérive. Une boucle de moins de 2 ticks est traitée comme une piste sans boucle.
- **Compression LZSS**, appliquée séparément aux blocs intro et boucle, avec un gain d'environ ×5 à ×7 :
  - le 68000 décompresse dans une fenêtre de 32 Ko en RAM, 0x100800-0x1087FF ;
  - les éléments sont groupés par 8 derrière un octet de drapeaux, bit 0 en premier ; un drapeau à 1 indique un littéral ;
  - copie courte `0LLL OOOO oooooooo` : longueur 3-10, distance jusqu'à 4096 ;
  - copie longue `1LLL LLLL 0OOOOOOO oooooooo` : longueur 3-130, distance jusqu'à 32768.

## Protocole 68000 → Z80

- Le 68000 écrit en `$320000`, ce qui déclenche un NMI côté Z80. L'octet `FF` sert d'échappement :
  - `FF FF` : octet de données 0xFF ;
  - `FF 00` : requête d'état ;
  - `FF 01` : STOP ;
  - `FF 02` : PLAY (vide le tampon) ;
  - `FF 03` : PAUSE ;
  - `FF 04` : REPRISE ;
  - `FF 06` : voix déclenchées, pour les vumètres.
- Réponse du Z80 (port 0x0C, relue en `$320000`) :
  - bit 7 : bascule à chaque octet reçu (accusé de réception) ;
  - bit 6 : piste en cours ;
  - bits 0-5 : places libres / 16 dans l'anneau de 1 Ko situé en F800.
- Le 68000 relaie au plus `JB_FEED` = 160 octets par image et envoie `FF 00` à chaque image. Sans cela, le tampon plein
  provoquait un interblocage.
- **Pause** : les notes FM sont relâchées, les volumes SSG mis à 0 et l'ADPCM coupé ; le temps est gelé. À la reprise, les volumes SSG
  mémorisés sont réécrits.
- **Mode AUTO** (défaut) : une piste qui boucle joue l'intro puis 2 tours de boucle avant de passer à la suivante ;
  après la dernière piste du dernier jeu, le premier jeu (la lecture ne s'arrête jamais ; `mame_tests/album_wrap.lua`).
  **LOOP** répète la piste. **RAND** (2.5.19, `pick_rand`) : comme AUTO, mais la piste suivante est tirée au hasard
  parmi les N pistes de tous les jeux, sauf celle qui vient de finir (`rnd`, graine = compteur d'images ;
  `mame_tests/random_mode.lua`). SELECT fait tourner AUTO -> LOOP -> RAND (`V_REPM` 0/1/2) ; C / D restent la piste
  précédente / suivante de la liste.
- **Robustesse** :
  - les appuis sont cumulés par le VBlank, aucun n'est perdu ;
  - un Z80 muet ne fige pas l'écran (il est sauté, puis relancé) ;
  - le STOP se resynchronise de lui-même ;
  - le temps affiché suit les images réelles.

## Interface (couche fix)

- Les tuiles maison (54 : icônes, barres lisses, boutons de manette, cadre, notes de l'en-tête en 3 poses, case transparente, icône RAND)
  commencent à **0xC00** dans la S-ROM (zone de remplissage de `sfix`, 0xB69-0xFFF, jamais affichée). Jusqu'à la 2.5.13
  elles étaient en 0x200 et écrasaient le logo SNK et la police double hauteur du splash BIOS / UniBIOS : sur AES, qui n'a
  pas de `sfix` sur la carte mère, le splash lit la S-ROM de la cartouche et apparaissait altéré. Elles sont générées par
  `tools/tiles.py`. Le fond des tuiles utilise la couleur 2. Pour les glyphes du BIOS, la couleur 1 est le tracé et la couleur 2 le fond.
- Adresse VRAM fix = 0x7000 + col×32 + ligne. Registre d'incrément `$3C0004` : 0x20 = colonne suivante, 1 = ligne suivante.
  La mise en page utilise les lignes 3-28 (marge pour les écrans cathodiques).
- Thème coloré par défaut : `parts/ui3.S` et `parts/draw3.S`. Thème calme de la 2.5.1 : `parts/theme_calm/`. Pour l'utiliser,
  reconstruire `src/jukebox.S` = `head.S + ui3_calm.S + core.S + draw3_calm.S`, puis lancer `tools/tbuild.py`.
- En-tête (rangée 3) : note jaune en colonne 2, titre arc-en-ciel en colonnes 4..18, croche blanche en colonne 20,
  « ROM nn % » à partir de la colonne 29. `note_anim` (appelée par `draw` à chaque image, vue liste et plein écran) :
  pendant la lecture, les deux notes (6 rangées de haut, tuiles `T_HN0..2` / `T_WN0..2` décalées de 0, 1, 2 pixels)
  rebondissent de 2 pixels en opposition, poses 0-1-2-1 de 8 images chacune (≈ 1,85 battement/s) ; à l'arrêt et en
  pause : pose du milieu.
- Manette (BIOS) : appuis de la manette 1 en `$10FD97`, état courant en `$10FD96`, START/SELECT en `$10FDAD`. Le MVS n'a pas de SELECT.

## Palettes : seulement dans le retour de trame (2.5.20)

- Sur une vraie Neo Geo, le 68000 a priorité sur la vidéo pour la RAM de palettes : une couleur écrite pendant
  l'affichage apparaît sur un pixel là où se trouve le balayage (« neige » : petits points / traits de couleur au hasard ;
  MAME ne le reproduit pas). Voir https://wiki.neogeodev.org/index.php/Palettes .
- Toutes les écritures récurrentes se font donc dans le VBlank (`vblank`, draw3.S) :
  - arc-en-ciel du titre : `tick` prépare les couleurs dans `V_HUEB` et leur nombre dans `V_HUEP` ; le VBlank les pose ;
  - jeux de palettes (entrée / sortie de l'économiseur) : `pal_prep` calcule dans `V_PALB` (RAM+0x380, 162 octets) depuis
    la boucle principale (le calcul à 50 % prend 50 lignes, plus que le retour de trame) ; la boucle principale demande
    `V_PALFN` = `pal_norm` ou `pal_saver`, que le VBlank appelle (seulement ces deux adresses : la RAM peut contenir
    n'importe quoi au démarrage) ; la pose prend 11 lignes au plus. `saver_on` attend 2 images que ce soit fait avant
    d'animer l'économiseur ;
  - arc-en-ciel du grand texte et scintillement des lisères : déjà dans `saver_scroll` (VBlank).
- Restent directes, une seule fois, quand l'écran est redessiné : `setpals` au démarrage et à la reprise MVS (pièce).
- Vérifié sous MAME : RAM de palettes identique à la 2.5.19 en lecture, pendant l'économiseur et au réveil.

## Économiseur d'écran (2.5.14 ; `core.S` : saver_in / saver_on / saver_off / saver_scroll / sc_full / box_phase / rnd / saver_info / pick_text / build_info)

- Après `SAVERDLY` = 17756 images (5 min ; 10 min de la 2.5.14 à la 2.5.18, 15 min avant) sans appui : couche fix remplie de la case
  transparente `T_CLEAR`, fond noir. La musique continue. Tout appui (croix, boutons, START/SELECT) réveille l'écran ; il
  est consommé. Textes : « NEO GEO JUKEBOX - ENJOY FINE MUSIC ! - NIC034 / DELTA ISLAND » pendant la lecture, « NEO GEO
  JUKEBOX THANKS FOR USING THIS SOFTWARE - NIC034 / DELTA ISLAND » à l'arrêt ou en pause (textes fournis par Nicolas).
- **Animation dans l'interruption VBlank** (`saver_scroll`, au tout début du retour de trame, à chaque image) : la boucle
  principale dépasse parfois une image (relais vers le Z80) et l'animation saccadait. Pendant l'économiseur la boucle
  principale n'écrit plus dans la VRAM : `saver_on` met `V_SAVER` à 1 en dernier, `saver_off` et `resume` à 0 en
  premier. **Mesuré sous MAME (4 min, objets au plus dense) : 26 lignes en moyenne, 35 au plus** (retour de trame :
  40 lignes). La réécriture complète des 81 tranches (~30 lignes) est faite par `saver_on`, dans la boucle principale,
  avant que l'économiseur soit visible ; l'interruption ne la refait que si le texte change pendant l'économiseur.

### Sprites (ordre d'affichage : un numéro plus grand passe devant)

| Sprites | Rôle |
|---|---|
| 1..24 | damier (`CK_N`) |
| 25..64 | objets animés : 10 emplacements de 4 sprites (`BOX0`, `BOX_SPR`, `BOX_N`) |
| 65..145 | grand texte, 81 tranches (`TX0`, `NSPR`) |
| 146..227 | petit texte jaune, 2 lignes de 41 (`SM0`, `SM_N`) |

**Limite matérielle de 96 sprites par ligne** (MAME l'applique aussi, `neogeo_spr.cpp`) : une copie des SCB3 tenue
par espionnage des écritures LSPC (`mame_tests/saver_perline.lua`) compte les sprites de chaque ligne à chaque image.
Mesuré sur 4 min : **93 au plus à l'arrêt, 92 en lecture** (base sans objet : 89). Les règles qui le garantissent sont
ci-dessous (amplitude minimale, espacement des objets).

### Grand texte en sine scroll

- Police du BIOS agrandie **x5 (40 x 40)**, contour noir de 2 px, 10 tranches de 4 px par lettre ; chaque tranche = un
  sprite de 3 tuiles (48 px : les 8 dernières lignes sont vides), `SC_TILE0` 0x100 + 3 x (10 x (c − 0x20) + tranche).
  Centré à la même hauteur qu'en x4 (`SC_Y0` = 92, centre 112). 2 px par image ; 40 px par caractère (`mulu #40`).
- Hauteur : sinus x amplitude ; l'amplitude suit l'**énergie** de la musique `V_ENER` = somme des 7 vumètres (0..896) :
  28 px + énergie / 11, max 64 ; monte de 3 px par image, redescend d'1 px (jamais de saut de la courbe). **Pas moins
  de 28 px** : une vague plus plate mettrait plus de 96 sprites sur une ligne (sprites de 48 px de haut : à 24 px,
  107 sprites mesurés). **Vitesse** : 2 + énergie / 192 pas de phase par image (2..5). **Flash** : quand le niveau
  ADPCM-A (batterie, `V_LVL+5`) remonte, 6 images d'arc-en-ciel éclairci (OU dégressif `sc_flash`).
- **Tables** `sc_ytab` (19 amplitudes de 28 à 64 px x 512 demi-phases, en octets `2 x (dy + 64)`, 9,5 Ko,
  `tools/gen_tables.py`) + `sc_ylut` (128 mots : octet -> valeur SCB3, taille 3 tuiles) : 5 instructions par tranche.
  Index en demi-pas (`2 x V_SPH − (3 x frac) / 2`, masque 0x1FF, +6 par tranche). SCB4 directement en `X << 7`.
- **Anneau** : les 81 sprites gardent leur tranche ; quand le texte avance d'une tranche, seul le sprite sorti à gauche
  reçoit la nouvelle tranche de droite (`V_HEAD`, `sc_tile` : une division). Au bout du texte, si c'est le même texte
  (cas habituel), la numérotation des tranches est simplement décalée de 10 x longueur : pas de réécriture complète.
- Couleurs : palette 16, arc-en-ciel (`hues`) qui défile verticalement ; couleur 9 = contour noir.

### Damier isométrique

- Losanges de 64 x 32, un sur deux gris à ~13 % (palette 17), l'autre transparent ; carte de tuiles fixe (`CK_TILE`
  0xE0.., 32 tuiles) ; glisse en diagonale (2 px en X, 1 px en Y par image, boucle de 32 images).
- Ondulation (eau, 2.5.18) : `A x (2 sin(11 j + p1) + sin(p2 − 7 j)) / 2048` : deux grandes vagues (23 et 36 colonnes,
  marches de 16 px faibles entre colonnes voisines, 2 à 3 px au maximum). Elle suit la musique (`V_ENER`) : amplitude
  `V_CKA` visée 32 + E/8 plafonnée à 106 (3 px au calme, −10..+9 px très fort), approchée d'une unité par image ;
  vitesse `V_CKP1` +2..+11 et `V_CKP2` +1..+5 quarts de pas de `sc_sin` par image (une vague en 8,5 s au calme, ~1,5 s
  très fort). Recalculée pour une colonne sur deux à chaque image (l'autre moitié a une image de retard, < 0,6 px),
  gardée `<< 7` dans `V_CKR`. Colonnes de 18 tuiles (288 px), Y = −12 − phase + ondulation : haut ≤ −3, bas ≥ 235,
  écran toujours couvert (vérifié image par image sous MAME : `mame_tests/saver_cover.lua`).
  SCB3 = base − cache (une soustraction par colonne), SCB4 en `X << 7` (+16 << 7 par colonne).

### Petit texte jaune

- En haut (Y 4) et en bas (Y 211) : « ALBUM  <titre>  -  TRACK nn/nn  -  TIME mm:ss  -  REMAINING mm:ss  - »
  (+ PAUSED ; STOPPED à l'arrêt) ; le bas montre le même texte décalé d'une demi-longueur **et de 4 px** : ses tuiles
  changent 4 images après celles du haut, jamais dans la même image (marge pour les objets). Police du BIOS 8x8 + ombre,
  colonnes doublées et sprites réduits à 8 px (SCB2 0x07FF) ; sprites collés (bit 6 de SCB3) : 2 écritures de X par
  image. Texte reconstruit par la boucle principale (`saver_info`).

### Objets animés (planches intégrées depuis la 2.5.17 ; 6 planches en 2.5.19-2.5.20, 4 depuis la 2.5.21)

- **Planches** : images sur fond magenta (#FF00FF), lues ligne par ligne par `jb_box_frames` (ngt_studio.py), à côté du
  programme sous les noms `jukebox_boxes.png` ... `jukebox_boxes6.png` (chacun remplace la planche intégrée de même numéro, 2.5.20 ; avant, un seul fichier les remplaçait toutes), ou `--boxes a.png,b.png,...` ;
  sinon les **planches intégrées** `JB_BOXES_B85` (boîte, console, logo et triangle Delta Island de Nicolas ; puces retirées en 2.5.21 ;
  les deux derniers agrandis par `planche.png@1.3`, plafonné à 46 px de haut : logo 40 x 47 px sur 3 colonnes, triangle
  52 x 48 px ; déjà converties par `jb_box_frames` : même ROM
  à l'octet près que les PNG ; Pillow inutile dans ce cas ; régénérées par `tools/pack_boxes.py`). Ce sont des visuels
  SNK : exclus de la licence MIT (LICENSE). `--boxes ""` = sans objets. Orientation déduite des images :
  haute (boîte, 30 x 42 px au plus, grille 2 x 3 tuiles) ou large (console, 62 x 38 px au plus, 4 x 3 tuiles) ;
  72 images par planche ici (96 au plus) ; palette de 14 couleurs pondérée (racine du nombre de pixels : les touches
  vives gardent leur place) + lisère clair d'1 px (couleur 15). C-ROM : à partir de `BOX_TILE0` 0xA00 (petite police
  déplacée de 0x500 à 0x900), colonne par colonne.
- **`boxdata`** (core.S, rempli par `build_cart` à `JB_BOXDATA_OFF`) : nombre de planches, puis 48 octets par planche :
  images, large, 1re tuile, palette (16 mots, copiée en palettes 19..24 par `saver_on`), colonnes − 1, rangées,
  tuiles par image, 320 − largeur, 224 − hauteur. Sans planche : 0, aucun objet (sprites masqués).
- **Flux continu** : 10 emplacements ; un départ dès que l'intervalle `V_BOXI` est écoulé et qu'un emplacement est
  libre. Toutes les 10 à 20 s (`box_phase`) : densité visée de 2 à 8 objets (intervalle 312 / n, au moins 32 images,
  + 0..7) et diagonale (4 sens) ; une nouvelle diagonale attend que les objets en vol soient sortis. Point de départ
  décalé de −160 à +160 px le long du bord (entrée par le haut ou par le côté). Trajet : 1 px par image en X, 17/22 en
  Y (`box_v`), miroirs `320 − largeur − u` et `224 − hauteur − v`. Hasard : xorshift 16 bits (7, 9, 8), graine = `V_VBL`.
- **Un objet des autres planches pour quatre boîtes** : compteur `V_BOXC` (0..4) ; au 5e départ, une des planches 2..4,
  chacune à son tour (`V_BOXW`, 2.5.21 : console, logo, triangle ; en 2.5.19-2.5.20 les deux puces en plus). Si cet objet large ne peut pas
  encore partir (moins de 63 images depuis le dernier départ), rien ne part : il n'est jamais remplacé par une boîte
  (sinon, avec un flux dense, il ne viendrait presque jamais). Mesuré (2.5.19, 6 planches) : 161 boîtes et 8 objets de
  chacune des 5 autres planches en 5 min. Jusqu'à 6 planches (`BOX_NP`, palettes 19..24, `V_BOXR` 6 mots). Image de
  rotation de base tenue par un compteur (plus de division par planche et par image) ; scintillement du lisère écrit une
  image sur 4, pour les planches présentes seulement.
- **Objets hauts de 3 colonnes** (logo agrandi) : deux sur une ligne = 6 sprites, 89 + 6 = 95 (mesuré avec le logo seul,
  `--boxes jukebox_boxes5.png@1.3`). Les objets restent à 3 rangées (48 px) : la trajectoire (y de −48 à 224) et la règle
  « 2 objets par ligne au plus » en dépendent.
- **Règles pour les 96 sprites par ligne** : tous les objets en vol vont dans le même sens à la même vitesse, leur écart
  en Y ne dépend que de l'écart entre leurs départs (17/22 px par image) ; départs espacés d'au moins 32 images ->
  jamais plus de 2 objets sur une ligne ; un objet large (console, 4 sprites) ne part qu'à 63 images (`BOX_GAPW`) au
  moins du départ précédent et rien ne part dans les 63 images qui suivent (`V_BOXLS`, `V_BOXLW`) -> une console est
  toujours seule sur ses lignes. Pire cas : 2 boîtes (2 sprites chacune) = 4, ou une console seule = 4 ; 89 + 4 = 93.
- **Rotation** : image = (horloge / 2 + 7 x emplacement) modulo les images de la planche (une division par planche et
  par image) ; chaque objet change d'image toutes les 4 images (un tiers des objets à la fois), jamais quand le petit
  texte se réécrit (`V_IPOS & 3` = 0, les images les plus chargées).
- **Lisère** : gris 75 % (choisi par Nicolas parmi 50 / 75 / 100 %), scintillement léger de 21/31 à 27/31 sur 64 images
  (`sc_twk`, couleur 15 des palettes 19..24).
- **Relais vers le Z80** (`feed`) : au-delà des 24 premiers octets d'une image, on s'arrête dans les 64 dernières lignes
  visibles — seulement si le Z80 a au moins 400 octets d'avance. Mesuré : tampon jamais vide.
- Tests MAME : `mame_tests/saver_test.lua` (textes, 187 sprites posés hors objets, tous cachés au réveil objets compris,
  appui consommé, pièce MVS) : 12/12 MVS euro/us/japan/unibios40, 11/11 AES asia/japan/unibios40 ; `full_test.lua`
  40/40 MVS, 38/38 AES ; endurance 5 min ; fuzz 6 min (4 configurations) ; sans planche et avec une seule planche
  (large) ; `saver_perline.lua` (sprites par ligne), `saver_irqcost.lua` (coût de l'interruption), `saver_flux.lua`, `saver_cover.lua` (couverture du damier).

## Toasty « Aurelien - Toasty » (2.5.26, option du constructeur ; `core.S` : toasty_init / toasty_alb / toasty_time / toasty_setup / toasty_vbl / toasty_hide)

- **Option** : case de l'onglet Cartridge (réglage `cart_toasty`), `--toasty` en ligne de commande, `TOASTY=1` pour
  `tools/tbuild.py`. Décochée : le bloc `toastydata` (360 octets, `JB_TOASTY_OFF`) reste à zéro, aucune tuile ;
  `toasty_init` met alors `V_TOST` = 3 au démarrage et rien ne se déclenche.
- **Quand** : une seule fois par mise sous tension (requête 2 ; la reprise MVS par une pièce ne réarme pas), au premier de :
  - début d'une piste du 3e album de la liste (jeu 2) en venant d'un autre album (`toasty_alb`, appelé par `play`
    avant `move.w d0,V_PG`) : passage AUTO 2 -> 3 ou tirage RAND qui tombe dans l'album 3 ;
  - 20 min de lecture réelle (`toasty_time`, VBlank : `V_TOPL` compte les images où `V_PLAY` ≠ 0 et hors pause ;
    `TO_TIME` = 71022 images).
  - Seulement pendant l'économiseur : déclenché (`V_TOST` = 1), il part quand l'économiseur est affiché depuis
    `TO_WAIT` = 592 images (10 s, `V_TOSA`). Déclenché hors économiseur, il attend donc le suivant. Un réveil pendant
    l'animation la masque (`spr_hide` couvre les sprites du Toasty) et la compte comme passée (`toasty_setup`).
  - `V_TOST` : 0 armé, 1 déclenché, 2 animé, 3 passé / désactivé. RAM+1720..1729 (hors de la remise à zéro des
    256 premiers octets : initialisée par `toasty_init`).
- **Image** : une seule (case 8 de la planche fournie : les 16 cases sont la même pose déplacée verticalement, avec de
  petites différences de dessin aléatoires d'une case à l'autre), `art/toasty_frame.png` -> `tools/pack_toasty.py` ->
  `JB_TOASTY_B85`. Détourage du fond magenta bruité, réduction à 112 x 94 px (moyenne des seuls pixels du personnage :
  pas de frange rose), calée en bas d'un bloc de 7 x 6 tuiles. 4 palettes de 15 couleurs (k-means par groupe de tuiles,
  33..36), chaque tuile prend la plus proche. Colonnes rognées à leur contenu : 1res rangées [4, 1, 0, 0, 0, 3, 4],
  30 tuiles C-ROM à partir de `JB_TOASTY_TILE0` = 0x3F00 (les objets s'arrêtent avant 0x2500).
- **Sprites 326..333** (`TO0` = `NALL` + 1, 7 utilisés) : numéros plus grands que tous les autres -> devant tout ;
  la couche fix est transparente pendant l'économiseur. SCB1/SCB2 posés par `toasty_setup` dans `saver_on` (hors
  VBlank), colonnes masquées ; X posé une fois au départ ; ensuite seulement 7 SCB3 par image.
- **Mouvement** : table `to_dy` (dy + 8 par image, 255 = fin), repos `JB_TOASTY_Y` = 132 (haut du bloc ; bas en 228),
  X `JB_TOASTY_X` = 200 (bord droit en 312) : montée 30 images (ease-out, 2 px de dépassement), tenue 96 images
  (gorgée de 2 px), descente 24 images ; 150 images, ~2,5 s.
- **96 sprites par ligne** : mesuré sur la 2.5.25 (6 min, sans Toasty) : 89 au pire en lignes 120-127, 82 en
  128-135, ≤ 77 plus bas. Le haut du bloc ne monte jamais au-dessus de la ligne 130 (repos 132 − 2) et les colonnes
  rognées ne mettent que 3 sprites sur les 16 lignes du haut. Mesuré avec le Toasty rejoué sans fin pendant 6 min
  (20 932 images animées, scènes texte et sphère, objets au plus dense) : **89 au plus, jamais au-delà de 96**.
- **VBlank** : `toasty_vbl` passe **avant** `saver_scroll` : 2 lignes au plus, ses écritures sont faites au début du
  retour de trame, même quand `saver_scroll` déborde (ci-dessous).
- Tests : `mame_tests/toasty_cases.lua` (CASE = album / time / pending / wake / off) et `mame_tests/toasty_stress.lua`.

### Mesure faite en 2.5.26 : la scène sphère déborde du retour de trame (problème antérieur, NON corrigé)

- Mesuré sur la 2.5.25 d'origine (ROM instrumentée : compteur de ligne `$3C0006` relevé avant / après `saver_scroll`,
  4 min) : scène texte 27,2 lignes en moyenne, 72 au plus (5 images sur 7 617 au-delà de 40) ; **scène sphère
  144,6 lignes en moyenne, 155 au plus, à chaque image** (retour de trame : 40 lignes, image : 264).
- Sur une vraie console, cela veut dire : écritures VRAM des points pendant l'affichage (déchirures possibles, que
  MAME ne montre pas) et plus de la moitié du temps du 68000 prise par l'interruption (relais vers le Z80 à vérifier).
  Les palettes de l'économiseur sont écrites avant `sphere_draw` (pal_saver, fondu du CD) ; à vérifier aussi.
- Le texte « Hardware limits are checked in MAME: ... the vertical blank » du README n'est plus vrai depuis la 2.5.24.

## Pièges Neo Geo rencontrés (toujours valables)

1. Sans le bloc de sécurité (pointeur en `$182`), le BIOS refuse la cartouche et reste sur une grille de test.
2. Il faut `move #$2000,sr` dans le jeu. Sans les interruptions, plus de VBlank, et le watchdog resette la machine en environ 9 images.
3. VBlank cartouche : si le bit 7 de `$10FD80` vaut 0, `trap #0` (BIOS) ; sinon watchdog (`$300001`), `jsr $C0044A`, puis IRQACK `$3C000C`.
4. Ne **jamais** écrire en `$3A000B` : cela rebascule le Z80 sur la ROM son du BIOS. La police doit donc venir de la S-ROM de la cartouche.
5. Le Z80 peut rester dans la boucle RAM du BIOS (FFFD). Le NMI du driver démarre donc le driver au premier contact, et le 68000
   envoie 0x03 à l'initialisation.
6. Décompresseur : `move.w d1,V_FLAGS` effaçait la retenue avant `bcc`. Remplacé par `lsr.w V_FLAGS`, un décalage directement en mémoire.
7. Avec des ticks de 8 échantillons, 4 à 6 % des ticks étaient perdus sous la charge NMI. Avec 32 échantillons, aucune perte n'a été mesurée.
8. z80asm ne remplit pas les trous laissés par `org` : utiliser `defs`.
9. **En-tête : jamais `jmp etiquette` en $122..$139.** GNU as raccourcit `jmp user` en `jmp (d16,pc)` (4 octets) et
   décale les vecteurs suivants : PLAYER_START ($128) tombait au milieu d'une instruction. Le BIOS MVS ne l'appelle
   pas sans crédit, mais l'AES / UniBIOS l'appelle à chaque START -> « ILLEGAL INSTRUCTION 00000128 » (vu sur le
   Darksoft AES + UniBIOS 4.0, reproduit sous MAME `aes -bios unibios40`). Corrigé en 2.5.7 : `.word 0x4EF9` +
   `.long cible`, PLAYER_START / DEMO_END / COIN_SOUND -> `rts`. Tester aussi sous `aes` (asia, unibios40), pas
   seulement `neogeo` (MVS).
10. **MVS : une pièce fait rappeler USER avec la requête 3 (titre).** Avant la 2.5.8 le jukebox repartait de zéro
    (musique coupée). Il reprend maintenant là où il en était (`resume`, repère `V_MAGIC` = "NGJB" posé après
    l'initialisation ; la requête 2 du démarrage réinitialise toujours tout).
11. Test complet multi-BIOS : `mame_tests/full_test.lua` (START x12, pause, stop, SELECT, pièces, boutons, économiseur,
    appuis aléatoires ; lignes PASS/FAIL). 2.5.8 : 40/40 sur `neogeo` euro/us/japan/unibios40, 38/38 sur `aes`
    asia/japan/unibios40.
12. Lua MAME :
   - un script autoboot est relancé à chaque reset, d'où la garde `_G.reg` ;
   - les ports s'appellent « P1 A » ou « 1 Player Start » ;
   - les écoutes en écriture (write taps) ne se déclenchent pas sur la RAM : passer par des lectures ou des dumps
     (`tap.lua` fonctionne parce qu'il écoute le latch `$320000`).

## Outils et tests

- `tools/tbuild.py` assemble avec `m68k-linux-gnu-as/ld/objcopy/nm` et `z80asm`. Il écrit `build/prom_nosec.bin`
  (21124 octets en 2.5.20), `build/m1drv.bin` (972 octets) et `build/tiles.bin`. Avec `OUTDIR fichiers.ngt` et `NGT_BIOS`,
  il fabrique aussi un jeu MAME de test avec ces binaires, sans modifier `ngt_studio.py`.
- `mame_tests/` :
  - `ui.lua` : parcours de toutes les commandes ;
  - `full.lua` : vue plein écran ;
  - `auto.lua` : enchaînement et LOOP ;
  - `fuzz.lua` : endurance avec des appuis aléatoires ;
  - `perf.lua` : images sans progression de la boucle principale ;
  - `play.lua` / `tap.lua` : lecture et capture des octets envoyés au Z80 ;
  - `video.lua` / `video60.lua` : captures vidéo de 30 s et 60 s.
- Exemple de lancement : `mame neogeo ngjb -hashpath hash -rompath . -autoboot_script ui.lua -seconds_to_run 40`.
  Ajouter `-aviwrite x.avi` ou `-wavwrite x.wav` pour capturer.
- `tests/t_robust.py` : LZSS, modèle du driver Z80 rejoué sur de vraies pistes, cas dégénérés (sélection vide, boucles courtes), fichiers abîmés. `tests/cmp2.py` : compare une capture
  MAME au rendu de référence.

## Premier essai sur matériel réel (19/10/2026, retour de Nicolas, vidéo sur téléviseur)

- La cartouche démarre et joue (AoF2 piste 5).
- Vumètre B coupé à droite : la colonne 38 de la couche fix est cachée par le cache du téléviseur. En 2.5.4, les
  vumètres de la vue liste sont en colonnes 24..36 (`LVCOL` = 24), la liste en 2..22, le cadre en 1..37 et AUTO/LOOP
  en 32..36. Règle retenue : rien d'important au-delà de la colonne 37.
- « Petits parasites horizontaux blancs » : ce sont, selon toute vraisemblance, les traits de crête des vumètres
  (tuiles `pk1..pk8`, blanches) qui restaient affichés jusqu'à 2 s au-dessus d'une barre vide. En 2.5.4 la crête
  chute en ~0,7 s (3/128 par image) et n'est plus dessinée quand la voix est muette. À confirmer sur le téléviseur.

## Reste à faire

- Test sur Darksoft Multi-AES (chez Nicolas), puis NeoSD et console réelle.
- Confirmer sur Darksoft : le sine scroll et les objets (format `crom0`), `fpga` avec une P2 de 8 Mo.
- Sur une vraie console : coût de l'interruption (35 lignes sur 40 dans MAME) et 96 sprites par ligne (95 au pire).
