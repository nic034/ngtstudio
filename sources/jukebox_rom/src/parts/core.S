| rappels du BIOS (PLAYER_START, DEMO_END, COIN_SOUND) : rien a faire
cb_rts: rts

| reprise apres un rappel de USER (MVS : piece inseree -> mode titre) : couleurs, ecran et lecture conserves
resume: clr.l   V_PALFN                | une pose de palettes en attente (entree dans l'economiseur) n'a plus lieu d'etre
        clr.w   V_HUEP
        clr.w   V_SAVER
        clr.w   V_IDLE
        bsr     spr_hide
        moveq   #0,d7
        bsr     setpals
        bsr     cls
        move.w  #1,V_DIRTY
        tst.w   V_FULL
        beq.s   1f
        bsr     draw_full_static
        bra     main
1:      bsr     draw_static
        bra     main

blk_start:
        move.l  d4,V_SOFF
        move.l  d5,V_LEFT
        clr.w   V_NBITS
        clr.w   V_MLEN
        clr.w   V_WPOS
        rts

| STOP auto-resynchronisant : FF 00 FF 01 donne STOP que le Z80 attende ou non deja la suite d'un echappement
| (si un octet s'est perdu, FF 00 devient deux donnees, effacees par le PLAY suivant)
z_stop: move.b  #0xFF,d0
        bsr     sendb
        move.b  #0x00,d0
        bsr     sendb
        move.b  #0xFF,d0
        bsr     sendb
        move.b  #0x01,d0
        bra     sendb
z_play: move.b  #0xFF,d0
        bsr     sendb
        move.b  #0x02,d0
        bra     sendb

| d0 = octet de commande/donnee : attend l'accuse du Z80 (bit7 du retour bascule)
sendb:  tst.w   V_ZDEAD                | Z80 muet : on n'attend plus (l'interface reste fluide)
        bne.s   sb_x
        move.b  0x320000,d3
        and.b   #0x80,d3
        move.b  d0,0x320000
        move.w  #6000,d4
sb1:    move.b  0x320000,d5
        move.b  d5,d6
        and.b   #0x80,d6
        cmp.b   d3,d6
        bne.s   sb2
        dbra    d4,sb1
        move.w  #1,V_ZDEAD
        rts
sb2:    clr.w   V_ZDEAD
        moveq   #0,d6
        move.b  d5,d6
        move.w  d6,V_REPLY
        btst    #6,d6                  | bit 6 : une piste est en cours cote Z80
        sne     d5
        and.w   #1,d5
        move.w  d5,V_ZST
        and.w   #0x3F,d6               | bits 0-5 : places libres / 16
        lsl.w   #4,d6
        move.w  d6,V_FREE
sb_x:   rts

senddata:
        cmp.b   #0xFF,d0
        bne.s   sd1
        bsr     sendb
        move.b  #0xFF,d0
sd1:    bra     sendb

| relaie au plus FEED octets decompresses vers le Z80 (tant qu'il a de la place)
feed:   movem.l d0-d7/a0-a1,-(sp)
        tst.w   V_PLAY
        beq     fd_x
        move.b  #0xFF,d0               | FF 00 : requete d'etat (places libres, piste en cours)
        bsr     sendb
        move.b  #0x00,d0
        bsr     sendb
        cmp.w   #1,V_PLAY
        bne     fd_x
        move.w  #FEED-1,d7
fd_l:   cmp.w   #FEED-1-FEEDMIN,d7     | au-dela des FEEDMIN premiers octets : on s'arrete si la trame touche a sa fin
        bhi.s   fd_ok                  | (64 dernieres lignes visibles) pour laisser vumetres et affichage tenir dans
        cmp.w   #FEEDLOW,V_FREE        | l'image -- seulement si le Z80 a deja au moins 400 octets d'avance (sinon
        bcc.s   fd_ok                  | on continue : la musique passe avant tout)
        move.w  0x3C0006,d0
        lsr.w   #7,d0                  | compteur de ligne : 0xF8..0x1FF, visible 0x110..0x1EF, VBlank a 0x1F0
        cmp.w   #FEEDEND,d0
        bcs.s   fd_ok
        cmp.w   #0x1F0,d0
        bcs     fd_x
fd_ok:  cmp.w   #16,V_FREE
        bcs     fd_x
        tst.l   V_LEFT
        bne.s   fd_get
        move.l  V_LOOP,d4              | fin de bloc : (re)part sur la boucle s'il y en a une
        cmp.l   #-1,d4
        beq     fd_done
        move.l  V_LLEN,d5
        beq     fd_done                | boucle vide : on ne tourne pas sans fin
        cmp.w   #1,V_REPM              | mode AUTO / RAND : apres LOOPS tours, fin de piste (C3) pour enchainer
        beq.s   fd_lp
        cmp.w   #LOOPS,V_INLP
        bcs.s   fd_lp
        move.b  #0xC3,d0
        bsr     senddata
        bra     fd_done
fd_lp:  bsr     blk_start
        addq.w  #1,V_INLP
        bra.s   fd_l
fd_get: bsr     getz
        bsr     senddata
        dbra    d7,fd_l
        bra     fd_x
fd_done: move.w #2,V_PLAY
fd_x:   movem.l (sp)+,d0-d7/a0-a1
        rts

| d0 <- octet decompresse suivant (LZSS, fenetre 32 Ko en RAM) ; utilise d1-d2/a0-a1
getz:   lea     WIN,a1
        move.w  V_MLEN,d1
        beq.s   gz_tok
        subq.w  #1,V_MLEN
gz_cp:  move.w  V_WPOS,d2
        sub.w   V_MDIST,d2
        and.w   #0x7FFF,d2
        moveq   #0,d0
        move.b  (a1,d2.w),d0
        bra     gz_st
gz_tok: tst.w   V_NBITS
        bne.s   gz_fl
        bsr     rdbyte
        move.w  d0,V_FLAGS
        move.w  #8,V_NBITS
gz_fl:  subq.w  #1,V_NBITS
        lsr.w   V_FLAGS                | bit 0 -> C (decalage en memoire : rien ne touche C ensuite)
        bcc.s   gz_m
        bsr     rdbyte                 | litteral
        bra.s   gz_st
gz_m:   bsr     rdbyte                 | copie
        move.w  d0,d1
        btst    #7,d1
        bne.s   gz_lg
        lsr.w   #4,d1                  | courte : longueur 3..10, distance 12 bits
        addq.w  #2,d1                  | longueur - 1 (le premier octet est copie tout de suite)
        move.w  d1,V_MLEN
        and.w   #15,d0
        lsl.w   #8,d0
        move.w  d0,d2
        bsr     rdbyte
        or.w    d2,d0
        addq.w  #1,d0
        move.w  d0,V_MDIST
        bra.s   gz_cp
gz_lg:  and.w   #0x7F,d1               | longue : longueur 3..130, distance 15 bits
        addq.w  #2,d1
        move.w  d1,V_MLEN
        bsr     rdbyte
        lsl.w   #8,d0
        move.w  d0,d2
        bsr     rdbyte
        or.w    d2,d0
        addq.w  #1,d0
        move.w  d0,V_MDIST
        bra     gz_cp
gz_st:  move.w  V_WPOS,d2
        move.b  d0,(a1,d2.w)
        addq.w  #1,d2
        and.w   #0x7FFF,d2
        move.w  d2,V_WPOS
        subq.l  #1,V_LEFT
        rts

| d0 <- octet de la P-ROM a V_SOFF (avec banque de 1 Mo au-dela du premier) ; utilise d1/a0
rdbyte: move.l  V_SOFF,d1
        addq.l  #1,V_SOFF
        move.l  V_SOFF,d0              | debut de Mo (hors P1) : on saute le marqueur de banque
        and.l   #0xFFFFF,d0
        bne.s   rb_go
        cmp.l   #0x100000,V_SOFF
        bcs.s   rb_go
        add.l   #16,V_SOFF
rb_go:  move.l  d1,d0
        swap    d1
        lsr.w   #4,d1
        beq.s   rb_dir
        subq.w  #1,d1
        cmp.w   V_BANK,d1
        beq.s   rb_ok
        move.w  d1,V_BANK
        move.w  d1,0x2FFFF0
rb_ok:  and.l   #0xFFFFF,d0
        add.l   #0x200000,d0
rb_dir: movea.l d0,a0
        moveq   #0,d0
        move.b  (a0),d0
        rts

| verifie chaque banque P2 : selection par ecriture en $2FFFF0, puis lecture du marqueur "NGJB BANK " n ~n
bank_check:
        move.w  #0xFFFF,V_BADB
        move.w  0x14C,d7
        move.w  d7,V_NBK
        moveq   #0,d6
bc_l:   cmp.w   d7,d6
        bcc.s   bc_end
        move.w  d6,0x2FFFF0
        lea     0x200000,a0
        lea     t_mark,a1
        moveq   #9,d5
bc_c:   cmpm.b  (a0)+,(a1)+
        bne.s   bc_bad
        dbra    d5,bc_c
        cmp.b   (a0)+,d6
        bne.s   bc_bad
        move.b  d6,d4
        not.b   d4
        cmp.b   (a0)+,d4
        bne.s   bc_bad
        addq.w  #1,d6
        bra.s   bc_l
bc_bad: move.w  d6,V_BADB
bc_end: move.w  #0xFFFF,V_BANK         | force la reselection au premier acces
        rts

| ================================================================ economiseur d'ecran
| Apres SAVERDLY images sans appui : couche fix entierement transparente, fond a 50 %, et un texte en sine scroll
| (facon Amiga) traverse l'ecran : "NEO GEO JUKEBOX  ENJOY FINE MUSIC" pendant la lecture, "... THANKS FOR USING
| THIS SOFTWARE" a l'arret ou en pause (choisi au debut et a chaque tour du texte).  La lecture continue.
| Le texte est fait de NSPR sprites de 16x32 (2 tuiles), chacun montrant une tranche de 4 pixels d'un caractere de
| 32x32 (police du BIOS agrandie x4 ; 8 tranches par caractere, tuiles C-ROM generees par ngt_studio.py) : chaque
| tranche a sa hauteur sur la sinusoide.  L'amplitude suit la musique (niveaux des vumetres) : elle gonfle a chaque
| note ou percussion et retombe dans les passages calmes, a l'arret ou en pause.
| Derriere le texte, sur fond noir, un damier isometrique tres leger (un losange sur deux gris a ~13 %, l'autre
| transparent ; losanges de 64 x 32) defile en boucle (periode de
| 32 images : le motif est identique a lui-meme decale de 64 x 32) et ondule facon drapeau (chaque colonne de 16 px
| decalee en hauteur, 3 px au calme a 10 px quand la musique est forte, plus vite aussi) : 24 sprites de 16 x 288 (1..24) a carte de tuiles fixe, seules leurs positions changent ; dessines avant
| le texte (sprites 25..105), donc en dessous.  Lettres cernees de noir (lisibles sur fond clair).  Par ligne : au plus 53 tranches de texte (calcule pour
| toutes les amplitudes, 24..64) + 24 colonnes de damier = 77 sprites, sous la limite materielle de 96.
| N'importe quel appui (croix ou bouton) le reveille ; cet appui n'a pas d'autre effet.
        .equ    SAVERDLY, 17756        | 5 minutes a 59,185 images/s (10 minutes jusqu'a la 2.5.18)
        .equ    V_IDLE,  RAM+240        | images sans appui
        .equ    V_ILV,   RAM+268        | V_VBL au dernier passage de saver_in
        .equ    V_SAVER, RAM+242        | 1 = economiseur actif
        .equ    V_SPOS,  RAM+244        | position du texte (pixels, 0 .. 32 x longueur - 1)
        .equ    V_SPH,   RAM+246        | phase de la sinusoide
        .equ    V_SLEN,  RAM+248        | longueur du texte (caracteres)
        .equ    V_STXT,  RAM+252        | adresse du texte (long)
        .equ    V_MAGIC, RAM+272        | "NGJB" une fois le jukebox initialise
        .equ    V_FLASH, RAM+276        | economiseur : images de flash restantes apres un coup de batterie (0..6)
        .equ    V_LASTA, RAM+278        | economiseur : niveau ADPCM-A (batterie) a l'image precedente (octet)
        .equ    V_ENER,  RAM+280        | economiseur : energie de la musique = somme des 7 vumetres (0..896)
        .equ    V_BOXT,  RAM+282        | economiseur : horloge des boites (images, modulo 65536)
        .equ    V_RND,   RAM+284        | generateur pseudo-aleatoire (xorshift 16 bits, jamais nul)
        .equ    V_BOXD,  RAM+286        | diagonale commune : bit 0 = de droite a gauche, bit 1 = de bas en haut
        .equ    V_BOXND, RAM+288        | diagonale suivante (-1 : aucune) : prise quand toutes les boites sont sorties
        .equ    V_BOXI,  RAM+290        | intervalle entre deux departs (images, >= BOX_GAP) : densite visee
        .equ    V_BOXL,  RAM+292        | instant du prochain depart possible (V_BOXT ; signe)
        .equ    V_BOXPH, RAM+294        | images avant le prochain tirage de densite / diagonale
        .equ    V_BOXA,  RAM+296        | boites en vol (bit n = emplacement n)
        .equ    V_BOXS,  RAM+298        | 10 mots : instant de depart de chaque boite
        .equ    V_BOXO,  RAM+318        | 10 mots : decalage du point de depart le long du bord (-160..+160 px)
                                       | (RAM+338 : libre depuis la 2.5.19, V_BOXR deplace pour 4 planches)
        .equ    V_BOXK,  RAM+342        | 10 mots : planche de chaque emplacement (0..5)
        .equ    V_BOXLW, RAM+362        | depart du dernier objet large (deux larges jamais a moins de BOX_GAPW images)
        .equ    V_CKR,   RAM+364        | 24 mots : ondulation de chaque colonne du damier, << 7 (cache, 12 colonnes par image)
        .equ    V_BOXP,  RAM+412        | 10 longs : description de la planche de chaque emplacement (adresse dans boxdata)
        .equ    V_BOXC,  RAM+452        | compteur des departs 0..4 : un objet des autres planches au 5e (un pour quatre boites)
        .equ    V_BOXLS, RAM+454        | dernier depart (tout objet)
        .equ    V_CKP1,  RAM+456        | damier : phase de la grande vague (1/4 de pas de sc_sin)
        .equ    V_CKP2,  RAM+458        | damier : phase de la 2e vague
        .equ    V_CKA,   RAM+460        | damier : amplitude de l'ondulation (32..106 ; 106 = 10 px)
        .equ    V_BOXR,  RAM+462        | 6 mots : image de rotation de base de chaque planche, image en cours
        .equ    V_BOXW,  RAM+474        | planches 2..6 : la prochaine a partir (0..planches-2), chacune a son tour
        .equ    BOX_NP,  6              | planches au plus (palettes 19..24)
        .equ    V_PALFN, RAM+476        | palettes a poser dans le prochain retour de trame : pal_norm / pal_saver (0 : rien)
        .equ    V_HUEP,  RAM+480        | arc-en-ciel du titre : nombre de couleurs a poser (0 : rien), puis V_HUEB
        .equ    V_HUEB,  RAM+482        | 6 mots : couleur 1 des palettes 10..15 (preparees par tick)
        .equ    V_PALB,  RAM+0x380      | copie des palettes 0..15 (couleurs 0..4, 5 mots chacune) + fond : calculee par la
                                       |   boucle principale (pal_prep), recopiee par le VBlank (pal_copy) ; 162 octets
        .equ    NSPR,    81             | sprites du texte : TX0 .. TX0+80
        .equ    CK_N,    24             | sprites du damier : 1..24 (dessines avant le texte = en dessous)
        .equ    BOX0,    CK_N+1         | objets animes : BOX_SPR sprites par emplacement (meneur + colles), entre damier et
                                       |   texte ; chaque planche donne sa grille (colonnes de sprites x rangees de tuiles)
        .equ    BOX_SPR, 4              | sprites par emplacement (objet de 64 px de large au plus)
        .equ    BOX_DSC, 48             | taille d'une description de planche dans boxdata
        .equ    BOX_GAPW, 63            | un objet large (4 sprites) ne partage jamais ses lignes : aucun depart a moins de
                                       |   63 images avant ou apres lui.  Au pire 4 sprites d'objets sur une ligne (une
                                       |   console, ou deux boites) : base mesuree 89 + 4 = 93, limite 96
        .equ    BOX_N,   10             | boites en vol au plus
        .equ    BOX_P,   352            | trajet en images : x de -32 a 320 (1 px par image), y de -48 a 224 (17/22 px)
        .equ    BOX_GAP, 32             | ecart minimal entre deux departs.  Toutes les boites en vol vont dans le meme sens
                                       |   a la meme vitesse : leur ecart en Y ne depend que de l'ecart entre leurs departs
                                       |   (17/22 px par image).  Elles se chevauchent en Y si leurs departs sont a moins de
                                       |   63 images ; avec 32 images au moins, jamais plus de 2 sur une ligne (4 sprites)
        .equ    CD0,     BOX0+BOX_SPR*BOX_N  | CD qui tourne (coin haut droit, position fixe) : 2 sprites (colonnes de
                                       |   16 x 32, planche 4 de boxdata, voir ngt_studio.py JB_BOXES_B85 et label 49:
                                       |   plus bas) ; numerote juste apres les objets volants, avant le texte, pour
                                       |   rester au-dessus du damier/objets mais en dessous du texte qui ondule
        .equ    CD_X,    272            | X ecran du coin haut gauche de l'icone (32 px de large, marge de 16 px a droite)
        .equ    CD_Y,    24             | Y ecran (32 px de haut), sous la barre d'info (couche fixe, hors budget sprites)
        .equ    TX0,     CD0+2
        .equ    SM0,     TX0+NSPR       | petit texte jaune : SM0..SM0+40 en haut, SM0+41..SM0+81 en bas
        .equ    SM_N,    41             | sprites par ligne (un caractere de 8 px chacun, 41 x 8 = 328 px)
        .equ    SM_TILE0, 0x900         | tuiles C-ROM de la petite police : 0x900 + (caractere - 0x20), 0x20..0x7E
        .equ    SM_YT,   4              | Y du petit texte du haut / du bas (hors de la zone de la vague, 32..192)
        .equ    SM_YB,   211
        .equ    SPH0,    SM0+2*SM_N     | essai : sphere de points (remplace le texte qui ondule par phases de 60 s)
        .equ    SPH_N,   96             | nombre de points (NALL = 325, sous les 381 sprites materiels : marge 56)
        .equ    SPH_NPAL,8              | essai : nombre de teintes pour colorer les points (voir pal_saver, sphere_init)
        .equ    SPH_PAL0,25             | palettes 25..25+SPH_NPAL-1 : libres (non utilisees ailleurs dans le jukebox)
        .equ    NALL,    SPH0+SPH_N-1   | sprites 1..NALL utilises par l'economiseur (CD0 inclus, il precede TX0)
        .equ    V_IPOS,  RAM+260        | position du petit texte (pixels)
        .equ    V_ILEN,  RAM+262        | longueur du petit texte (caracteres)
        .equ    V_INEW,  RAM+264        | 1 = reconstruire le petit texte en fin d'image
        .equ    V_IBUF,  RAM+0x300      | petit texte (128 octets, reconstruit toutes les 8 images)
        .equ    CK_TILE, 0xE0           | tuiles C-ROM du damier : 0xE0 + colonne (0..7) + 8 x rangee (0..3) d'une periode 128 x 64
        .equ    V_CKO,   RAM+256        | phase du damier (0..31) : decalage 2 px en X, 1 px en Y par image
        .equ    V_SLAST, RAM+258        | tranche du texte au dernier ecrit des tuiles (SCB1 seulement quand elle change)
        .equ    V_HEAD,  RAM+266        | anneau du grand texte : sprite (0..80) qui montre la tranche la plus a gauche
        .equ    SC_TILE0, 0x100         | tuiles C-ROM : 0x100 + 3 x (10 x (caractere - 0x20) + tranche) (+1, +2 : dessous)
        .equ    V_SAMP,  RAM+250        | amplitude courante (28..64 pixels)
        .equ    V_SCENE, RAM+1100       | essai sphere : 0 = texte qui ondule, 1 = sphere de points
        .equ    V_SCPASS,RAM+1102       | boucles du texte restantes avant le prochain changement de phase (voir scene_pass)
        .equ    SC_TXT_PASSES, 0        | nombre de boucles SUPPLEMENTAIRES du texte avant de passer a la sphere (0 = un
        .equ    SC_SPH_PASSES, 0        |   seul passage ; scene_pass decompte jusqu'a -1, donc la valeur reelle de
                                       |   boucles par phase est toujours SC_xxx_PASSES + 1, voir scene_pass)
        .equ    V_SPHAX, RAM+1104       | angle de rotation axe X (0..255, indexe sc_sin directement)
        .equ    V_SPHAY, RAM+1106       | angle de rotation axe Y
        .equ    V_SPHVX, RAM+1108       | vitesse courante axe X (signee, pas de phase par image)
        .equ    V_SPHVY, RAM+1110       | vitesse courante axe Y
        .equ    V_SPHTX, RAM+1112       | vitesse cible axe X (la courante y derive doucement)
        .equ    V_SPHTY, RAM+1114       | vitesse cible axe Y
        .equ    V_SPHDT, RAM+1116       | images avant le prochain tirage d'une nouvelle cible de derive
        .equ    V_SPHBUF,RAM+1120       | tampon (576 octets) : 3 tableaux de SPH_N mots, SCB3 (Y + hauteur) en +0,
                                       |   SCB4 (X) en +2 x SPH_N, SCB2 (zoom) en +4 x SPH_N, recopies d'un trait en VRAM
        .equ    SPH_TCX, RAM+0xC000     | tables de produits de sphere_draw, refaites a chaque image par additions :
        .equ    SPH_TSX, SPH_TCX+256    |   v x cos/sin(angle X) pour v = -64..63 (128 mots chacune),
        .equ    SPH_TCY, SPH_TSX+256    |   v x cos/sin(angle Y) pour v = -68..67 (136 mots chacune) ; 1056 octets en
        .equ    SPH_TSY, SPH_TCY+272    |   tout, RAM libre (au-dela de la fenetre LZSS, sous la pile)
        .equ    SPH_XSPD,  1            | essai balle : vitesse horizontale du centre (px/image) : lente, deplacement
                                       |   lateral naturel
        .equ    SPH_BXMIN, 20           | bornes du deplacement horizontal : la balle reste visible a l'ecran pendant
        .equ    SPH_BXMAX, 300          |   toute la duree de la scene (rebondit sur les bords au lieu d'en sortir)
        .equ    SPH_FLOOR, 134          | position Y du centre quand la balle touche le "sol" : juste au-dessus du petit
                                       |   texte du bas (SM_YB = 211), sans le chevaucher.  Le point le plus bas projete
                                       |   de la sphere (sph_pts/sphere_draw) peut descendre jusqu'a 75 px sous son centre
                                       |   (mesure sur l'ensemble des points et de toutes les rotations possibles) ; 184
                                       |   (premiere valeur essayee) laissait la balle chevaucher et deborder sous le
                                       |   texte a chaque rebond.  134 + 75 = 209, 2 px sous SM_YB : la balle touche la
                                       |   limite sans jamais passer dessous, et le mouvement garde plus d'amplitude
                                       |   visible (plus centre a l'ecran)
        .equ    SPH_FLOORF,SPH_FLOOR*64 | meme valeur en virgule fixe << 6 (1/64 px : rebond fluide, sans a-coup pres
                                       |   du sommet ou la vitesse est faible)
        .equ    SPH_GRAV,  2            | gravite (virgule fixe << 6, par image) : faible, pour un rebond lent et
                                       |   ample (effet de gravite marque, pas des petits rebonds rapides)
        .equ    SPH_VMIN,  120          | vitesse de rebond minimale (virgule fixe << 6, vers le haut ; ~56 px de haut,
                                       |   ~1 s jusqu'au sommet)
        .equ    SPH_VRANGE,64           | etendue du tirage aleatoire (puissance de 2) a ajouter a SPH_VMIN : une vitesse
                                       |   differente a chaque contact au sol, donc une hauteur de rebond toujours
                                       |   differente, mais plafonnee (jusqu'a ~131 px, ~1,4 s jusqu'au sommet) pour ne
                                       |   pas trop sortir en haut de l'ecran, voir sphere_bounce
        .equ    V_SPHBX,  RAM+1696      | essai balle : position X du centre a l'ecran (pixels)
        .equ    V_SPHBY,  RAM+1698      | essai balle : position Y du centre, virgule fixe << 6
        .equ    V_SPHBV,  RAM+1700      | essai balle : vitesse verticale (meme virgule fixe ; negative = monte)
        .equ    V_SPHBYI, RAM+1702      | essai balle : partie entiere courante de V_SPHBY (evite un decalage par point
                                       |   dans la boucle de projection de sphere_draw, appelee SPH_N fois par image)
        .equ    V_SPHBVX, RAM+1704      | essai balle : vitesse horizontale courante (+SPH_XSPD ou -SPH_XSPD ; change de
                                       |   signe en touchant SPH_BXMIN/SPH_BXMAX, comme un rebond sur les bords)

saver_in:
        move.w  V_VBL,d2               | images reellement affichees depuis le dernier passage (la boucle principale
        move.w  d2,d3                  |   saute parfois une image : compter ses passages allongeait le delai)
        sub.w   V_ILV,d2
        move.w  d3,V_ILV
        cmp.w   #8,d2                  | premier passage (V_ILV pas encore pose) : on compte 1
        bls.s   1f
        moveq   #1,d2
1:      move.b  V_EACC,d0
        or.b    V_SACC,d0
        beq.s   3f
        clr.w   V_IDLE                 | activite
        tst.w   V_SAVER
        beq.s   9f
        move.w  sr,-(sp)               | reveil : l'appui est consomme
        move.w  #0x2700,sr
        clr.b   V_EACC
        clr.b   V_SACC
        move.w  (sp)+,sr
        move.w  #18,V_REP              | haut/bas encore maintenu : pas de repetition immediate (le curseur ne bouge pas)
        bra     saver_off
3:      tst.w   V_SAVER
        bne.s   9f
        add.w   d2,V_IDLE
        bcc.s   4f
        move.w  #0xFFFF,V_IDLE         | (pas de debordement)
4:      cmp.w   #SAVERDLY,V_IDLE
        bcc     saver_on
9:      rts

saver_on:
        lea     V_LVL,a0               | vumetres a zero (ils repartent de zero au reveil)
        lea     V_PK,a1
        moveq   #6,d0
1:      clr.b   (a0)+
        clr.b   (a1)+
        dbra    d0,1b
        move.w  #0x7000,(a6)           | couche fix transparente : seuls les sprites du texte restent visibles
        move.w  #1,4(a6)
        move.w  #0x500-1,d1
2:      move.w  #T_CLEAR,2(a6)
        dbra    d1,2b
        clr.w   V_SPOS
        clr.w   V_SPH
        clr.w   V_FLASH
        move.w  #28,V_SAMP
        bsr     pick_text
        move.w  #0x8001,(a6)           | SCB2 : taille normale (pas de reduction) ...
        move.w  #SM0-2,d0
3:      move.w  #0x0FFF,2(a6)
        dbra    d0,3b
        moveq   #2*SM_N-1,d0           | ... sauf le petit texte : reduction X 7 = 8 px de large (une colonne sur deux
33:     move.w  #0x07FF,2(a6)          |   gardee : les tuiles ont leurs colonnes doublees)
        dbra    d0,33b
        clr.w   V_BOXT                 | boites : aucune en vol, tirage de densite a la premiere image
        lea     V_BOXR,a0              | images de rotation de base a 0 (horloge 0)
        moveq   #BOX_NP-1,d0
38:     clr.w   (a0)+
        dbra    d0,38b
        clr.w   V_BOXA
        clr.w   V_BOXL
        move.w  #1,V_BOXPH
        move.w  #-1,V_BOXND
        move.w  #352,V_BOXI
        move.w  V_VBL,d0               | graine du hasard : le compteur d'images (jamais nulle)
        or.w    #1,d0
        move.w  d0,V_RND
        and.w   #3,d0
        move.w  d0,V_BOXD
        move.w  #1,4(a6)               | boites masquees jusqu'a leur premiere position (et pour toujours sans planche)
        move.w  #0x8200+BOX0,(a6)
        move.w  #BOX_SPR*BOX_N-1,d0
36:     clr.w   2(a6)
        dbra    d0,36b
        move.w  #-1000,V_BOXLW
        move.w  #-1000,V_BOXLS
        clr.w   V_BOXC
        lea     V_CKR,a0               | ondulation du damier : a zero, remplie en 2 images (avant d'etre visible)
        moveq   #CK_N-1,d0
37:     clr.w   (a0)+
        dbra    d0,37b
        clr.w   V_CKP1                 | phases et amplitude (3 px) de l'ondulation
        clr.w   V_CKP2
        move.w  #32,V_CKA
        clr.w   V_BOXW
        move.w  #0xFFFF,V_IPOS         | -> 0 a la premiere image : tuiles ecrites tout de suite
        bsr     build_info             | V_ILEN jamais nul (la boucle de rebouclage en depend)
        move.w  #1,4(a6)
        move.w  #0x8200+SM0,(a6)       | SCB3 des petits textes : un meneur par ligne (Y fixe, 1 tuile), les 40 suivants
        move.w  #((496-SM_YT)<<7)+1,2(a6) |   colles (bit 6) : ils prennent sa hauteur et se placent 8 px a sa droite
        moveq   #SM_N-2,d0
6:      move.w  #0x0040,2(a6)
        dbra    d0,6b
        move.w  #((496-SM_YB)<<7)+1,2(a6)
        moveq   #SM_N-2,d0
7:      move.w  #0x0040,2(a6)
        dbra    d0,7b
        clr.w   V_CKO
        moveq   #0,d4                  | tuiles du texte ecrites ici, avant que l'economiseur soit visible (la premiere
        bsr     sc_full                |   image n'a plus a le faire : 64 lignes dans le retour de trame sinon)
        moveq   #1,d7                  | SCB1 du damier, ecrit une fois : sprite j, tuile k = (j-1) & 7 + 8 x (k & 3)
4:      move.w  d7,d2
        lsl.w   #6,d2
        move.w  d2,(a6)
        moveq   #0,d6
5:      move.w  d7,d2
        subq.w  #1,d2
        and.w   #7,d2
        move.w  d6,d3
        and.w   #3,d3
        lsl.w   #3,d3
        add.w   d3,d2
        add.w   #CK_TILE,d2
        move.w  d2,2(a6)
        move.w  #0x1100,2(a6)          | palette 17
        addq.w  #1,d6
        cmp.w   #18,d6
        bcs.s   5b
        addq.w  #1,d7
        cmp.w   #CK_N+1,d7
        bcs.s   4b
        clr.w   V_SCENE                | essai sphere : on demarre sur le texte qui ondule ; la sphere apparait/disparait
        move.w  #SC_TXT_PASSES,V_SCPASS |   seulement quand le texte vient de boucler (derniere lettre sortie de l'ecran)
        bsr     sphere_init            | tuiles de la sphere (une fois) + etat de rotation a zero
        bsr     sphere_hide            | masquee tant que la phase texte n'est pas terminee
        clr.l   V_PALFN                | (aucune pose en cours pendant le calcul)
        moveq   #1,d7                  | palettes a 50 %, calculees ici (trop long pour le VBlank : 50 lignes mesurees)
        bsr     pal_prep
        move.l  #pal_saver,V_PALFN     | palettes de l'economiseur : posees par le VBlank (jamais pendant l'affichage : une
        bsr     wait_frame             |   ecriture de palette pendant l'affichage laisse des points / traits parasites sur
        bsr     wait_frame             |   une vraie console, MAME ne le montre pas) ; 2 images : au moins un VBlank entier
        move.w  #1,V_SAVER             | en dernier : le VBlank anime l'economiseur des que V_SAVER = 1
        rts

| palettes posees par le VBlank (demandees par V_PALFN, appelees par vblank) : ecran de lecture, economiseur
pal_norm:
        bra     pal_copy
pal_saver:
        bsr     pal_copy               | palettes a 50 % (calculees par saver_on)
        move.w  #0x0222,0x400222       | palette 17, couleur 1 : losanges gris tres sombre (~13 %) ; les autres sont transparents
        lea     boxdata+8,a0           | palettes 19..24 : les 6 planches au plus (ecrites par le constructeur ; zeros
        lea     0x400260,a1            |   pour une planche absente, palette jamais utilisee)
        moveq   #BOX_NP-1,d1
33:     moveq   #15,d0
34:     move.w  (a0)+,(a1)+
        dbra    d0,34b
        lea     BOX_DSC-32(a0),a0
        dbra    d1,33b
        move.w  #0x8000,0x401FFE       | fond (backdrop) noir pendant l'economiseur (setpals le remet au reveil)
        move.w  #0x8000,0x400212       | palette 16, couleur 9 : contour noir des lettres
        move.w  #0x7FF0,0x400242       | palette 18 : petit texte jaune, ombre noire
        move.w  #0x8000,0x400244
        move.w  #0x4F44,0x400322       | essai : SPH_NPAL teintes pour les points de la sphere (palettes SPH_PAL0..+7,
        move.w  #0x6FC4,0x400342       |   couleur 1 seulement) ; valeurs reprises de hues (meme arc-en-ciel que le
        move.w  #0x69F4,0x400362       |   grand texte, index 0/4/8/.../28) pour rester coherent avec le reste du jukebox
        move.w  #0x24F7,0x400382
        move.w  #0x34FF,0x4003A2
        move.w  #0x147F,0x4003C2
        move.w  #0x594F,0x4003E2
        move.w  #0x5F4C,0x400402
        rts

saver_off:
        clr.w   V_SAVER                | en premier : le VBlank ne touche plus a la VRAM
        bsr     spr_hide
        clr.w   V_IDLE
        moveq   #0,d7                  | couleurs normales : calculees ici, posees par le prochain VBlank
        bsr     pal_prep
        move.l  #pal_norm,V_PALFN
        bsr     cls
        move.w  #1,V_DIRTY
        tst.w   V_FULL
        bne     draw_full_static
        bra     draw_static

| sprites du texte caches (hauteur 0)
spr_hide:
        move.w  #1,4(a6)
        move.w  #0x8201,(a6)
        move.w  #NALL-1,d0
1:      clr.w   2(a6)
        dbra    d0,1b
        rts

| texte selon l'etat : lecture en cours -> t_sc_play, sinon (arret, pause) -> t_sc_stop
pick_text:
        lea     t_sc_play,a0
        tst.w   V_PLAY
        beq.s   1f
        tst.w   V_PAUSE
        beq.s   2f
1:      lea     t_sc_stop,a0
2:      move.l  a0,V_STXT
        moveq   #0,d0
3:      tst.b   (a0)+
        beq.s   4f
        addq.w  #1,d0
        bra.s   3b
4:      move.w  d0,V_SLEN
        rts

| boucle principale : le petit texte (temps) est reconstruit hors interruption, apres chaque changement de caractere
saver_info:
        tst.w   V_INEW
        beq.s   1f
        clr.w   V_INEW
        bsr     build_info
1:      rts

| appele par l'interruption VBlank, au debut du retour de trame, a chaque image (meme si la boucle principale prend
| plus d'une image a cause du relais vers le Z80) : petit texte, damier, grand texte -> defilement parfaitement regulier.
| Pendant l'economiseur la boucle principale n'ecrit pas dans la VRAM (pas de conflit sur $3C0000).
saver_scroll:
        tst.w   V_SAVER
        beq     99f
        movem.l d0-d7/a0-a2,-(sp)
        move.w  #1,4(a6)               | petit texte en premier : la ligne du haut est affichee la premiere, tuiles et
        move.w  V_IPOS,d0              |   position changent ensemble avant que le faisceau y arrive.  1 px par image
        addq.w  #1,d0
        move.w  V_ILEN,d1
        lsl.w   #3,d1
21:     cmp.w   d1,d0
        bcs.s   22f
        sub.w   d1,d0
        bra.s   21b
22:     move.w  d0,V_IPOS
        move.w  d0,d2
        and.w   #7,d2
        bne.s   24f                    | haut : tuiles a chaque changement de caractere (toutes les 8 images)
        move.w  d0,d5
        lsr.w   #3,d5
        move.w  #SM0,d7
        bsr     wr_info
        move.w  #1,V_INEW
24:     move.w  V_IPOS,d5              | bas : le meme texte decale d'une demi-longueur et de 4 px : ses tuiles changent
        addq.w  #4,d5                  |   4 images apres celles du haut (jamais deux reecritures dans la meme image,
        move.w  d5,d2                  |   ce qui laisse de la marge aux boites dans le retour de trame)
        and.w   #7,d2
        bne.s   23f
        lsr.w   #3,d5
        move.w  V_ILEN,d0
        lsr.w   #1,d0
        add.w   d0,d5
        move.w  #SM0+SM_N,d7
        bsr     wr_info
23:     move.w  V_IPOS,d3              | SCB4 des 2 meneurs seulement : haut X = -(position & 7), bas -((position + 4) & 7)
        move.w  d3,d2
        and.w   #7,d3
        neg.w   d3
        and.w   #0x1FF,d3
        lsl.w   #7,d3
        move.w  #0x8400+SM0,(a6)
        move.w  d3,2(a6)
        addq.w  #4,d2
        and.w   #7,d2
        neg.w   d2
        and.w   #0x1FF,d2
        lsl.w   #7,d2
        move.w  #0x8400+SM0+SM_N,(a6)
        move.w  d2,2(a6)
        move.w  V_SPOS,d0              | 2 pixels par image ; au bout du texte : on repart, texte choisi a nouveau
        addq.w  #2,d0
        move.w  V_SLEN,d1              | longueur du texte en pixels : 40 x caracteres (40 = 32 + 8, evite mulu : image
        move.w  d1,d7                  |   par image sous l'interruption VBlank)
        lsl.w   #5,d1                  | d1 = longueur x 32
        lsl.w   #3,d7                  | d7 = longueur x 8
        add.w   d7,d1                  | d1 = longueur x 40
        cmp.w   d1,d0
        bcs.s   1f
        sub.w   d1,d0
        move.w  d0,V_SPOS
        bsr     scene_pass             | derniere lettre sortie de l'ecran, juste avant que le texte reparte du debut :
                                       |   seul point ou la sphere apparait/disparait (modifie d0,d3,a0)
        move.l  V_STXT,d2              | au bout du texte : meme texte -> la suite des tranches continue (mise a jour
        bsr     pick_text              |   d'une tranche comme d'habitude) ; texte change -> reecriture complete
        cmp.l   V_STXT,d2              |   (81 tranches : ~58 lignes, plus que le retour de trame ; ici seulement si
        beq.s   35f                    |   la lecture s'arrete ou reprend pendant l'economiseur)
        move.w  #0xFFFE,V_SLAST        | (0xFFFE + 1 n'est jamais une tranche)
        bra.s   2f
35:     move.w  V_SLEN,d1              | tranches deja ecrites, renumerotees : -10 x longueur
        mulu    #10,d1
        sub.w   d1,V_SLAST
        bra.s   2f
1:      move.w  d0,V_SPOS
2:      lea     V_LVL,a0               | energie de la musique : somme des 7 vumetres (0..896 ; piste 4 d'AoF2 : 90..490)
        moveq   #0,d0
        moveq   #6,d1
11:     moveq   #0,d2
        move.b  (a0)+,d2
        add.w   d2,d0
        dbra    d1,11b
        move.w  d0,V_ENER
        divu    #192,d0                | vitesse de la vague : 2 (calme) .. 5 (tres fort) pas de phase par image
        addq.w  #2,d0
        cmp.w   #5,d0
        bls.s   12f
        moveq   #5,d0
12:     add.w   d0,V_SPH
        move.b  V_LVL+5,d0             | coup de batterie (ADPCM-A : son niveau remonte) -> flash de 6 images
        move.b  V_LASTA,d1
        move.b  d0,V_LASTA
        cmp.b   d1,d0
        bls.s   31f
        move.w  #6,V_FLASH
31:     moveq   #0,d6
        move.w  V_FLASH,d1
        beq.s   32f
        subq.w  #1,V_FLASH
        add.w   d1,d1
        lea     sc_flash-2,a0
        move.w  (a0,d1.w),d6           | eclaircissement des couleurs : OU sur les composantes R, V, B
32:     lea     0x400202,a0            | palette 16, couleurs 1..8 (une par paire de rangees des lettres) :
        lea     hues,a1                | arc-en-ciel qui defile verticalement dans le texte
        move.w  V_VBL,d2
        lsr.w   #1,d2
        moveq   #7,d1
3:      and.w   #31,d2
        move.w  d2,d3
        add.w   d3,d3
        move.w  (a1,d3.w),d0
        or.w    d6,d0
        move.w  d0,(a0)+
        addq.w  #3,d2
        dbra    d1,3b
        move.w  #1,4(a6)
        move.w  V_CKO,d0               | damier : glisse le long d'une diagonale des losanges (2 px en X, 1 px en Y)
        addq.w  #1,d0
        and.w   #31,d0                 | apres 32 images : decalage (64, 32) = meme image, la boucle est invisible
        move.w  d0,V_CKO
        moveq   #0,d2                  | ondulation (eau) = A x (2 sin(11 j + p1) + sin(p2 - 7 j)) : deux grandes vagues (23
        move.w  V_ENER,d2              |   et 36 colonnes : marches de 16 px faibles entre colonnes voisines) qui suivent
        divu    #96,d2                 |   la musique (moitie haute de d2 a zero avant divu)
        move.w  d2,d3                  |   Vitesse (1/4 de pas de table par image) : p1 +2..+11, p2 +1..+5
        addq.w  #2,d3                  |   (8,5 s au calme, ~1,5 s tres fort) ; V_ENER = 0..896 (divu : moitie haute
        add.w   d3,V_CKP1              |   nulle, V_ENER est un mot)
        lsr.w   #1,d2
        addq.w  #1,d2
        add.w   d2,V_CKP2
        move.w  V_ENER,d2              | amplitude visee 32 + E / 8, plafonnee a 106 (unites : px x 2048 / 192 ; 106 ->
        lsr.w   #3,d2                  |   -10..+9 px), 32 = 3 px au calme ; V_CKA s'en approche d'une unite par image
        add.w   #32,d2                 |   (pas de saut)
        cmp.w   #106,d2
        bls.s   18f
        moveq   #106,d2
18:     move.w  V_CKA,d3
        cmp.w   d3,d2
        beq.s   19f
        bhi.s   20f
        subq.w  #2,d3
20:     addq.w  #1,d3
        move.w  d3,V_CKA
19:     lea     sc_sin,a2              | une colonne sur deux par image (j pair / impair selon l'image) : l'autre moitie
        move.w  V_VBL,d2               |   a une image de retard, < 0,6 px au plus vite (invisible) ; 2 lignes de moins
        and.w   #1,d2                  |   dans le retour de trame
        move.w  V_CKP1,d4
        lsr.w   #2,d4
        move.w  V_CKP2,d5
        lsr.w   #2,d5
        move.w  d2,d6
        mulu    #11,d6
        add.w   d6,d4
        move.w  d2,d6
        mulu    #7,d6
        sub.w   d6,d5
        lea     V_CKR,a0
        add.w   d2,d2
        adda.w  d2,a0
        moveq   #CK_N/2-1,d7
16:     move.w  d4,d6
        and.w   #255,d6
        move.b  (a2,d6.w),d6
        ext.w   d6
        add.w   d6,d6
        move.w  d5,d1
        and.w   #255,d1
        move.b  (a2,d1.w),d1
        ext.w   d1
        add.w   d1,d6                  | 2 s1 + s2 : -192..189
        muls    d3,d6
        asr.l   #8,d6
        asr.l   #3,d6                  | x A / 2048 : -10..+9 px
        lsl.w   #7,d6
        move.w  d6,(a0)
        addq.l  #4,a0
        add.w   #2*11,d4
        sub.w   #2*7,d5
        dbra    d7,16b
        move.w  #0x8201,(a6)           | SCB3 = (496 - Y) << 7 | 18 avec Y = -12 - phase + ondulation, hauteur 18 tuiles
        move.w  d0,d1                  |   (288 px ; ondulation -10..+9 : haut <= -3 et bas >= 235, l'ecran reste couvert) ;
        add.w   #508,d1                |   le debordement du mot fait le masque des 9 bits de Y
        lsl.w   #7,d1
        add.w   #18,d1
        lea     V_CKR,a0
        moveq   #CK_N-1,d2
69:     move.w  d1,d3
        sub.w   (a0)+,d3
        move.w  d3,2(a6)
        dbra    d2,69b
        move.w  #0x8401,(a6)           | SCB4 : X = 16 j - 2 x phase, directement en X << 7 (+16 << 7 par colonne)
        move.w  d0,d3
        add.w   d3,d3
        neg.w   d3
        lsl.w   #7,d3
        moveq   #CK_N-1,d2
17:     move.w  d3,2(a6)
        add.w   #16<<7,d3
        dbra    d2,17b
        lea     boxdata,a2             | objets : planches fournies au constructeur (0 = aucun objet)
        move.w  (a2),d6
        cmp.w   #4,d6                  | planche 4 (CD, position fixe) jamais tiree au hasard par le systeme volant :
        bls.s   77f                    |   limite a 4 planches ici, meme si boxdata en annonce plus (cd_spin la gere a part)
        moveq   #4,d6
77:     beq     49f
        move.w  #1,4(a6)
        move.w  V_VBL,d0               | lisere : scintillement leger (couleur 15 des palettes 19..24), triangle de 64 images ;
        move.w  d0,d1                  |   la valeur ne change qu'une image sur 4 : ecrite seulement alors, et seulement pour
        and.w   #3,d1                  |   les planches presentes (d6)
        bne.s   58f
        lsr.w   #2,d0
        and.w   #15,d0
        cmp.w   #8,d0
        bcs.s   59f
        eor.w   #15,d0
59:     add.w   d0,d0
        lea     sc_twk,a0
        move.w  (a0,d0.w),d0
        lea     0x40027E,a0
        move.w  d6,d1
        subq.w  #1,d1
57:     move.w  d0,(a0)
        lea     32(a0),a0
        dbra    d1,57b
58:
        move.w  V_BOXT,d4              | horloge
        addq.w  #1,d4
        move.w  d4,V_BOXT
        btst    #0,d4                  | image de rotation de base de chaque planche = (horloge / 2) modulo ses images,
        bne.s   62f                    |   tenue a jour par un compteur (+1 toutes les 2 images, retour a 0 apres la
        moveq   #0,d1                  |   derniere) : plus de division par planche et par image (2.5.19 : 6 planches,
        lea     V_BOXR,a0              |   ~1 ligne de moins dans le retour de trame) ; chaque objet y ajoute 7 x son
        lea     2(a2),a1               |   numero
63:     move.w  (a0),d0
        addq.w  #1,d0
        cmp.w   (a1),d0
        bcs.s   61f
        moveq   #0,d0
61:     move.w  d0,(a0)+
        lea     BOX_DSC(a1),a1
        addq.w  #1,d1
        cmp.w   d6,d1
        bcs.s   63b
62:
        subq.w  #1,V_BOXPH             | de temps en temps : nouvelle densite (2 a 8 objets), peut-etre nouvelle diagonale
        bne.s   50f
        bsr     box_phase
50:     tst.w   V_BOXND                | changement de diagonale : seulement quand les objets en vol sont tous sortis
        bmi.s   51f
        tst.w   V_BOXA
        bne     53f
        move.w  V_BOXND,V_BOXD
        move.w  #-1,V_BOXND
51:     move.w  d4,d0                  | depart si l'intervalle est ecoule et qu'un emplacement est libre
        sub.w   V_BOXL,d0
        bmi     53f
        move.w  V_BOXA,d1
        moveq   #0,d2
52:     btst    d2,d1
        beq.s   60f
        addq.w  #1,d2
        cmp.w   #BOX_N,d2
        bcs.s   52b
        bra     53f
60:     moveq   #0,d3                  | planche : la 1re pour 4 departs sur 5 ; au 5e (compteur V_BOXC 0..4), une des
        cmp.w   #2,d6                  |   autres, chacune a son tour (V_BOXW) : console, puces... un objet de ces
        bcs.s   64f                    |   planches pour quatre boites
        cmp.w   #4,V_BOXC
        bne.s   64f
        move.w  V_BOXW,d3
        addq.w  #1,d3
64:     move.w  d4,d0                  | un objet large (console, 4 sprites) est toujours seul sur ses lignes : personne ne
        sub.w   V_BOXLW,d0             |   part a moins de BOX_GAPW images apres lui...
        cmp.w   #BOX_GAPW,d0
        bcs     53f
        move.w  d3,d0
        mulu    #BOX_DSC,d0
        tst.w   4(a2,d0.w)
        beq.s   66f                    | objet haut : depart
        move.w  d4,d0                  | ... et lui ne part qu'a BOX_GAPW images au moins du depart precedent ; sinon
        sub.w   V_BOXLS,d0             |   rien ne part : on attend la console (jamais remplacee, une pour quatre boites)
        cmp.w   #BOX_GAPW,d0
        bcs     53f
        move.w  d4,V_BOXLW
66:     move.w  d4,V_BOXLS
        tst.w   d3                     | une des autres planches vient de partir : la suivante la prochaine fois
        beq.s   74f
        move.w  V_BOXW,d0
        addq.w  #1,d0
        move.w  d6,d1
        subq.w  #1,d1
        cmp.w   d1,d0
        bcs.s   75f
        moveq   #0,d0
75:     move.w  d0,V_BOXW
74:     addq.w  #1,V_BOXC
        cmp.w   #5,V_BOXC
        bcs.s   73f
        clr.w   V_BOXC
73:     move.w  V_BOXA,d1
        bset    d2,d1
        move.w  d1,V_BOXA
        move.w  d2,d1                  | description de la planche, gardee pour tout le vol
        lsl.w   #2,d1
        move.w  d3,d0
        mulu    #BOX_DSC,d0
        lea     2(a2,d0.w),a1
        lea     V_BOXP,a0
        move.l  a1,(a0,d1.w)
        add.w   d2,d2
        lea     V_BOXK,a0
        move.w  d3,(a0,d2.w)
        lea     V_BOXS,a0
        move.w  d4,(a0,d2.w)
        bsr     rnd                    | point de depart : decale de -160 a +160 px le long du bord (du haut ou du cote)
        divu    #321,d0
        swap    d0
        sub.w   #160,d0
        lea     V_BOXO,a0
        move.w  d0,(a0,d2.w)
        bsr     rnd                    | prochain depart : apres l'intervalle + 0..7 images
        and.w   #7,d0
        add.w   V_BOXI,d0
        add.w   d4,d0
        move.w  d0,V_BOXL
53:     moveq   #0,d5                  | emplacement 0..BOX_N-1
42:     move.w  d5,d3                  | d3 = SCB3 du meneur : BOX0 + BOX_SPR x emplacement
        lsl.w   #2,d3
        add.w   #0x8200+BOX0,d3
        move.w  V_BOXA,d0
        btst    d5,d0
        beq     40f
        move.w  d5,d1                  | a1 = description de la planche
        lsl.w   #2,d1
        lea     V_BOXP,a0
        movea.l (a0,d1.w),a1
        move.w  d5,d1
        add.w   d1,d1
        lea     V_BOXS,a0
        move.w  d4,d0                  | t = images depuis le depart
        sub.w   (a0,d1.w),d0
        lea     V_BOXO,a0
        move.w  (a0,d1.w),d7           | o = decalage du point de depart
        move.w  #BOX_P,d2              | sortie : t >= BOX_P (bord oppose en Y) ou t >= BOX_P - o (bord oppose en X)
        tst.w   d7
        ble.s   55f
        sub.w   d7,d2
55:     cmp.w   d2,d0
        bcs.s   43f
        move.w  V_BOXA,d2              | sortie : l'emplacement se libere
        bclr    d5,d2
        move.w  d2,V_BOXA
40:     move.w  d3,(a6)                | pas en vol : masque (taille 0 pour les BOX_SPR sprites)
        clr.w   2(a6)
        clr.w   2(a6)
        clr.w   2(a6)
        clr.w   2(a6)
        bra     48f
43:     move.w  d0,d1                  | v = t x 17 / 22 - 48 (table) ; de bas en haut : y = (224 - hauteur) - v
        add.w   d1,d1
        lea     box_v,a0
        move.w  (a0,d1.w),d1
        btst    #1,V_BOXD+1
        beq.s   38f
        neg.w   d1
        add.w   46(a1),d1
38:     move.w  #496,d2                | SCB3 : meneur (496 - y) << 7 | rangees de tuiles ; puis colonnes - 1 sprites
        sub.w   d1,d2                  |   colles (bit 6), le reste des BOX_SPR masque
        and.w   #0x1FF,d2
        lsl.w   #7,d2
        add.w   40(a1),d2
        move.w  d3,(a6)
        move.w  d2,2(a6)
        move.w  38(a1),d2              | colonnes - 1
        moveq   #BOX_SPR-2,d1
67:     subq.w  #1,d2
        bmi.s   71f
        move.w  #0x0040,2(a6)
        bra.s   72f
71:     clr.w   2(a6)
72:     dbra    d1,67b
        move.w  d0,d2                  | u = t - 32 + o ; de droite a gauche : x = (320 - largeur) - u
        sub.w   #32,d2                 |   (hors ecran : X sur 9 bits, jamais dans la zone visible par repliement)
        add.w   d7,d2
        btst    #0,V_BOXD+1
        beq.s   39f
        neg.w   d2
        add.w   44(a1),d2
39:     and.w   #0x1FF,d2
        lsl.w   #7,d2
        add.w   #0x200,d3
        move.w  d3,(a6)
        move.w  d2,2(a6)
        move.w  V_IPOS,d1              | image de la rotation : jamais quand le petit texte se reecrit (position & 3 = 0,
        and.w   #3,d1                  |   les images les plus chargees) ; sinon un tiers des objets (emplacement modulo 3
        beq     48f                    |   = phase - 1) : chacun change d'image toutes les 4 images
        subq.w  #1,d1
        lea     box_g,a0
        cmp.b   (a0,d5.w),d1
        bne     48f
        move.w  d5,d0                  | image = base de la planche + 7 x emplacement, modulo ses images
        add.w   d0,d0
        lea     V_BOXK,a0
        move.w  (a0,d0.w),d2           | planche
        lsl.w   #3,d0                  | (d0 = 16 x emplacement ; 7 x = 8 x - 1 x)
        lsr.w   #1,d0
        sub.w   d5,d0
        lea     V_BOXR,a0
        add.w   d2,d2
        add.w   (a0,d2.w),d0
61:     cmp.w   (a1),d0
        bcs.s   62f
        sub.w   (a1),d0
        bra.s   61b
62:     mulu    42(a1),d0              | x tuiles par image
        add.w   4(a1),d0               | + 1re tuile de la planche
        lsl.w   #7,d2                  | attribut : palette 19 + planche (d2 = 2 x planche)
        add.w   #0x1300,d2
        move.w  d5,d1                  | SCB1 des sprites : colonnes x rangees de tuiles (colonne par colonne)
        lsl.w   #2,d1
        add.w   #BOX0,d1
        lsl.w   #6,d1
        move.w  38(a1),d7              | sprites - 1
        move.w  40(a1),d3              | tuiles par sprite - 1
        subq.w  #1,d3
68:     move.w  d1,(a6)
        move.w  d3,-(sp)
46:     move.w  d0,2(a6)
        move.w  d2,2(a6)
        addq.w  #1,d0
        dbra    d3,46b
        move.w  (sp)+,d3
        add.w   #64,d1
        dbra    d7,68b
48:     addq.w  #1,d5
        cmp.w   #BOX_N,d5
        bcs     42b
49:
| CD qui tourne, coin haut droit, position fixe (n'utilise pas box_v/box_g : independant du systeme d'objets
| volants ci-dessus).  Planche 4 de boxdata (voir ngt_studio.py, JB_BOXES_B85 : 16 images, 2 x 2 tuiles = 32 x 32 px).
        lea     boxdata+2+4*BOX_DSC,a1 | description de la planche CD (BOX_DSC = taille d'une description = 48 octets)
        tst.w   (a1)                   | images == 0 : planche absente (ex. --boxes "") -> rien a dessiner
        beq     cd_done
        move.w  V_VBL,d3               | fondu transparent <-> normal (respiration continue, ~4,3 s/cycle, 2x plus
        and.w   #0xFF,d3               |   rapide qu'avant) : triangle 0..255..0 sur 256 images, puis reduit a un
                                       |   palier 0..15 (table cd_fade_tab)
        cmp.w   #128,d3
        bls.s   84f
        move.w  #255,d4
        sub.w   d3,d4
        move.w  d4,d3
84:     lsr.w   #3,d3                   | 0..16 (rarement 16 : plafonne juste en dessous)
        cmp.w   #15,d3
        bls.s   85f
        moveq   #15,d3
85:     move.w  d3,d4                  | 28 = 32 - 4, evite mulu : tourne a chaque image (CD toujours en fondu)
        lsl.w   #5,d3                  | d3 = palier x 32
        lsl.w   #2,d4                  | d4 = palier x 4
        sub.w   d4,d3                  | d3 = palier x 28 : 14 couleurs x 2 octets par palier de la table
        lea     cd_fade_tab,a2
        adda.w  d3,a2
        lea     0x4002E2,a3            | palette 23 (19 + planche 4), couleur 1 (0x400000 + 23 x 32 + 1 x 2)
        moveq   #13,d7
86:     move.w  (a2)+,(a3)+
        dbra    d7,86b
        move.w  V_VBL,d0               | image de rotation : change toutes les 4 images (planche de 16 images ->
        lsr.w   #2,d0                  |   un tour complet toutes les 64 images, ~1 tour/seconde a 60 Hz)
        and.w   #15,d0
        mulu    42(a1),d0              | x tuiles par image (colonnes x rangees)
        add.w   4(a1),d0               | + 1re tuile de la planche (d0 = tuile de depart de l'image courante)
        move.w  #0x1300+(4<<8),d2      | attribut : palette 19 + 4 = palette 23 (ecrite par pal_saver depuis boxdata+8)
        move.w  #1,4(a6)               | SCB1 : 2 colonnes de 2 tuiles (meme agencement que les objets volants)
        move.w  #CD0<<6,d1
        move.w  d1,(a6)
        move.w  d0,2(a6)
        move.w  d2,2(a6)
        addq.w  #1,d0
        move.w  d0,2(a6)
        move.w  d2,2(a6)
        move.w  #(CD0+1)<<6,d1
        move.w  d1,(a6)
        addq.w  #1,d0
        move.w  d0,2(a6)
        move.w  d2,2(a6)
        addq.w  #1,d0
        move.w  d0,2(a6)
        move.w  d2,2(a6)
        move.w  #0x8200+CD0,d1         | SCB3 : les 2 colonnes partagent le meme Y (hauteur fixe, 2 tuiles)
        move.w  d1,(a6)
        move.w  #(((496-CD_Y)&0x1FF)<<7)+2,d2
        move.w  d2,2(a6)
        move.w  #0x8200+CD0+1,d1
        move.w  d1,(a6)
        move.w  d2,2(a6)
        move.w  #0x8400+CD0,d1         | SCB4 : X fixe, 2e colonne a 16 px a droite de la 1re
        move.w  d1,(a6)
        move.w  #(CD_X&0x1FF)<<7,d2
        move.w  d2,2(a6)
        move.w  #0x8400+CD0+1,d1
        move.w  d1,(a6)
        move.w  #((CD_X+16)&0x1FF)<<7,d2
        move.w  d2,2(a6)
cd_done:
        tst.w   V_SCENE                | essai : la bascule texte <-> sphere est decidee dans scene_pass (appele quand
        beq.s   64f                    |   le texte qui ondule vient de boucler) ; ici on ne fait plus qu'aiguiller
        bsr     sphere_draw
        bra     99f                    | sphere active : on saute entierement le dessin du texte qui ondule ci-dessous
64:     move.w  #1,4(a6)               | SCB1 : 3 tuiles par sprite (adresse n x 64 : tuile, attribut, x 3)
        move.w  V_SPOS,d4              | grand texte en anneau : les 81 sprites gardent leur tranche ; quand le texte
        lsr.w   #2,d4                  |   avance d'une tranche (4 px, une image sur deux), seul le sprite sorti a
        move.w  V_SLAST,d0             |   gauche recoit la nouvelle tranche de droite (1 tuile au lieu de 81)
        cmp.w   d0,d4
        beq     19f                    | inchangee
        move.w  d4,V_SLAST
        movea.l V_STXT,a1
        move.w  V_SLEN,d6
        addq.w  #1,d0
        cmp.w   d0,d4
        bne.s   18f
        move.w  V_HEAD,d7              | +1 tranche : le sprite de tete prend la tranche d4 + 80 et passe a droite
        add.w   #TX0,d7
        move.w  d4,d5
        add.w   #NSPR-1,d5
        bsr     sc_tile
        move.w  V_HEAD,d0
        addq.w  #1,d0
        cmp.w   #NSPR,d0
        bcs.s   17f
        moveq   #0,d0
17:     move.w  d0,V_HEAD
        bra.s   19f
18:     bsr     sc_full                | nouveau texte pendant l'economiseur : reecriture complete (~30 lignes de plus)
19:
        moveq   #0,d0                  | (divu divise les 32 bits de d0 : moitie haute a zero)
        move.w  V_ENER,d0              | amplitude : 28 px + energie / 11 (le plus fort des vumetres restait presque
        divu    #11,d0                 |   toujours au maximum : la vague ne reagissait guere), cible 28..64.  Pas moins
        add.w   #28,d0                 |   de 28 : sprites de 48 px (3 tuiles), une vague plus plate mettrait plus de
                                       |   96 sprites sur une ligne (81 tranches + 24 du damier + 2 d'une boite ; mesure)
        cmp.w   #64,d0
        bls.s   13f
        moveq   #64,d0
13:     move.w  V_SAMP,d1
        cmp.w   d1,d0
        bls.s   14f
        addq.w  #3,d1                  | monte de 3 px par image (une montee d'un coup faisait des a-coups de 25 px)
        cmp.w   d0,d1
        bls.s   15f
        move.w  d0,d1
        bra.s   15f
14:     beq.s   15f
        subq.w  #1,d1                  | redescend d'un pixel par image
15:     move.w  d1,V_SAMP
        sub.w   #28,d1                 | SCB3 du grand texte : sc_ytab (tools/gen_tables.py) = 19 amplitudes (28..64 px)
        lsr.w   #1,d1                  |   x 512 demi-pas, en octets 2 x (dy + 64) ; sc_ylut convertit en valeur SCB3
        moveq   #9,d0
        lsl.w   d0,d1                  | table de 512 octets par amplitude
        lea     sc_ytab,a2
        adda.w  d1,a2
        lea     sc_ylut,a0
        move.w  V_HEAD,d0              | premier segment de l'anneau : sprites TX0 + tete .. TX0 + 80
        add.w   #0x8200+TX0,d0
        move.w  d0,(a6)
        move.w  V_SPOS,d3              | en demi-pas : phase de la tranche 1 = 2 x phase - 3/2 x (position & 3) (exact :
        and.w   #3,d3                  |   la position est paire) ; +6 demi-pas par tranche (4 px)
        move.w  d3,d0
        add.w   d3,d3
        add.w   d0,d3
        lsr.w   #1,d3
        move.w  V_SPH,d4
        add.w   d4,d4
        sub.w   d3,d4
        move.w  #0x1FF,d6
        and.w   d6,d4
        moveq   #0,d0                  | octet haut de d0 toujours nul (indice dans sc_ylut)
        moveq   #NSPR-1,d7
        sub.w   V_HEAD,d7
8:      move.b  (a2,d4.w),d0
        move.w  (a0,d0.w),2(a6)
        addq.w  #6,d4
        and.w   d6,d4
        dbra    d7,8b
        move.w  V_HEAD,d7              | second segment : sprites TX0 .. TX0 + tete - 1
        beq.s   27f
        subq.w  #1,d7
        move.w  #0x8200+TX0,(a6)
28:     move.b  (a2,d4.w),d0
        move.w  (a0,d0.w),2(a6)
        addq.w  #6,d4
        and.w   d6,d4
        dbra    d7,28b
27:
        move.w  V_HEAD,d0              | SCB4 : X = 4 i - (position & 3) pour la i-eme tranche de l'ecran, meme anneau ;
        add.w   #0x8400+TX0,d0         |   calcule directement en X << 7 (les 9 bits de X debordent seuls du mot)
        move.w  d0,(a6)
        move.w  V_SPOS,d3
        and.w   #3,d3
        neg.w   d3
        lsl.w   #7,d3
        move.w  #4<<7,d5
        moveq   #NSPR-1,d7
        sub.w   V_HEAD,d7
9:      move.w  d3,2(a6)
        add.w   d5,d3
        dbra    d7,9b
        move.w  V_HEAD,d7
        beq.s   29f
        subq.w  #1,d7
        move.w  #0x8400+TX0,(a6)
10:     move.w  d3,2(a6)
        add.w   d5,d3
        dbra    d7,10b
29:
99:     movem.l (sp)+,d0-d7/a0-a2     | epilogue partage : "bra 99f" (sphere active) doit atterrir ICI, avant la
        rts                             |   restauration des registres empiles au debut de saver_scroll, pas apres

| essai : decompte les boucles completes du texte qui ondule et bascule la phase texte <-> sphere quand le quota est
| atteint (SC_TXT_PASSES boucles de texte, puis SC_SPH_PASSES boucles "virtuelles" pendant que la sphere est affichee :
| V_SPOS continue d'avancer et de boucler en arriere-plan meme quand le texte n'est pas dessine, donc cet appel a lieu
| regulierement dans les deux phases).  Appelee par saver_scroll juste apres que la derniere lettre du texte qui ondule
| est sortie de l'ecran, avant qu'il reparte du debut.  Modifie d0,d3,a0.
scene_pass:
        move.w  V_SCPASS,d3
        subq.w  #1,d3
        bpl.s   70f                    | quota pas encore atteint : on se contente de decompter
        tst.w   V_SCENE
        bne.s   71f
        move.w  #1,V_SCENE             | texte -> sphere : la sphere reprend sa rotation la ou elle s'etait arretee
        bsr     text_hide               | masque aussitot le texte qui ondule (sinon ses 81 sprites restent affiches :
        move.w  #SC_SPH_PASSES,d3       |   cd_done ne les redessine plus du tout tant que la sphere est active)
        bra.s   70f
71:     clr.w   V_SCENE                 | sphere -> texte : la sphere se fige et se masque, elle ne tourne plus hors ecran
        bsr     sphere_hide
        move.w  #SC_TXT_PASSES,d3       | (le texte n'a pas besoin d'etre "demasque" : cd_done reecrit sa hauteur SCB3
70:     move.w  d3,V_SCPASS             |  en entier a chaque image des qu'il redevient actif, voir plus haut)
        rts

| essai : grand texte en anneau masque (hauteur 0), appelee quand on passe sur la sphere (modifie d0,a0).  Son
| reaffichage ne demande aucun appel symetrique : des que le texte redevient actif, cd_done reecrit SCB3 (hauteur)
| pour les NSPR sprites a chaque image (voir plus haut), ce qui les rend visibles de nouveau.
text_hide:
        move.w  #1,4(a6)
        move.w  #0x8200+TX0,(a6)
        moveq   #NSPR-1,d0
1:      clr.w   2(a6)
        dbra    d0,1b
        rts

| essai : sphere de points.  Tuiles (une fois, caractere '.' de la petite police) + etat de rotation a zero.
| Appelee une seule fois par saver_on (modifie d0,d2,d7,a0)
sphere_init:
        move.w  #1,4(a6)
        moveq   #0,d7
1:      move.w  d7,d0
        add.w   #SPH0,d0
        lsl.w   #6,d0
        move.w  d0,(a6)
        move.w  #SM_TILE0+14,2(a6)      | caractere '.' (0x2E - 0x20 = 14), meme police que le petit texte
        move.w  d7,d1                  | essai : couleur du point = une des SPH_NPAL teintes, cyclique par index (attribut
        and.w   #SPH_NPAL-1,d1         |   = palette << 8, voir box_g plus haut pour ce format ; teintes posees par pal_saver)
        add.w   #SPH_PAL0,d1
        lsl.w   #8,d1
        move.w  d1,2(a6)
        addq.w  #1,d7
        cmp.w   #SPH_N,d7
        bcs.s   1b
        clr.w   V_SPHAX
        clr.w   V_SPHAY
        clr.w   V_SPHVX
        clr.w   V_SPHVY
        clr.w   V_SPHTX
        clr.w   V_SPHTY
        move.w  #1,V_SPHDT
        move.w  #SPH_BXMIN,V_SPHBX     | essai balle : repart du bord gauche, posee sur le sol (premier rebond tire
        move.w  #SPH_XSPD,V_SPHBVX     |   tout de suite par sphere_bounce, voir plus bas)
        move.w  #SPH_FLOORF,V_SPHBY
        clr.w   V_SPHBV
        move.w  #SPH_FLOOR,V_SPHBYI
        rts

| essai : sphere de points masquee (hauteur 0), appelee quand on repasse sur le texte qui ondule (modifie d0,a0)
sphere_hide:
        move.w  #1,4(a6)
        move.w  #0x8200+SPH0,(a6)
        moveq   #SPH_N-1,d0
1:      clr.w   2(a6)
        dbra    d0,1b
        rts

| essai : derive doucement la vitesse de rotation (cible aleatoire changee toutes les 1,5-2,5 s) et avance les angles.
| Appelee une fois par image par sphere_draw (modifie d0,d1)
sphere_step:
        move.w  V_SPHDT,d0
        subq.w  #1,d0
        move.w  d0,V_SPHDT
        bpl.s   1f
        bsr     rnd                     | d0.l = 0..65535 (xorshift existant, cf plus bas)
        and.w   #63,d0
        add.w   #90,d0
        move.w  d0,V_SPHDT              | prochain tirage dans 90..153 images (~1,5-2,5 s a 60 Hz)
        bsr     rnd
        and.w   #7,d0
        subq.w  #3,d0                   | d0 = -3..4 pas de phase par image
        move.w  d0,V_SPHTX
        bsr     rnd
        and.w   #7,d0
        subq.w  #3,d0
        move.w  d0,V_SPHTY
1:      move.w  V_SPHTX,d0
        move.w  V_SPHVX,d1
        cmp.w   d1,d0
        beq.s   2f
        bgt.s   3f
        subq.w  #1,d1
        bra.s   4f
3:      addq.w  #1,d1
4:      move.w  d1,V_SPHVX
2:      move.w  V_SPHTY,d0
        move.w  V_SPHVY,d1
        cmp.w   d1,d0
        beq.s   5f
        bgt.s   6f
        subq.w  #1,d1
        bra.s   7f
6:      addq.w  #1,d1
7:      move.w  d1,V_SPHVY
5:      move.w  V_SPHAX,d0
        add.w   V_SPHVX,d0
        and.w   #255,d0
        move.w  d0,V_SPHAX
        move.w  V_SPHAY,d0
        add.w   V_SPHVY,d0
        and.w   #255,d0
        move.w  d0,V_SPHAY
        rts

| essai balle : fait rebondir le centre de la sphere en bas de l'ecran, en glissant d'un bord a l'autre (rebondit
| sur SPH_BXMIN/SPH_BXMAX au lieu d'en sortir : reste toujours visible pendant toute la duree de la scene), pendant
| qu'elle continue de tourner sur elle-meme (sphere_step, inchange).  Chute/rebond en virgule fixe << 6 pour un
| mouvement fluide meme pres du sommet ; gravite faible (SPH_GRAV) pour un rebond lent et ample, pas des petits
| rebonds rapides.  A chaque contact avec le sol, une nouvelle vitesse de rebond est tiree au hasard
| (SPH_VMIN..SPH_VMIN+SPH_VRANGE-1), donc une hauteur toujours differente.  Appelee une fois par image par
| sphere_draw (modifie d0,d1)
sphere_bounce:
        move.w  V_SPHBX,d0
        add.w   V_SPHBVX,d0
        cmp.w   #SPH_BXMAX,d0
        ble.s   8f
        move.w  #SPH_BXMAX,d0           | touche le bord droit : repart vers la gauche (reste toujours visible)
        move.w  #-SPH_XSPD,V_SPHBVX
        bra.s   1f
8:      cmp.w   #SPH_BXMIN,d0
        bge.s   1f
        move.w  #SPH_BXMIN,d0           | touche le bord gauche : repart vers la droite
        move.w  #SPH_XSPD,V_SPHBVX
1:      move.w  d0,V_SPHBX
        move.w  V_SPHBV,d1              | d1 = vitesse verticale courante
        addq.w  #SPH_GRAV,d1            | gravite constante
        move.w  V_SPHBY,d0              | d0 = position verticale courante
        add.w   d1,d0                   | d0 = position + vitesse
        cmp.w   #SPH_FLOORF,d0
        blt.s   2f
        move.w  #SPH_FLOORF,d0          | touche le sol : se recale dessus
        bsr     rnd                     | nouvelle vitesse de rebond aleatoire (d0,d1 ecrases, sans importance : la
                                       |   position d0 vient d'etre fixee au sol, reposee ci-dessous)
        and.w   #SPH_VRANGE-1,d0
        add.w   #SPH_VMIN,d0
        neg.w   d0                      | negatif = vers le haut
        move.w  d0,d1                   | d1 = nouvelle vitesse verticale
        move.w  #SPH_FLOORF,d0          | d0 = position (au sol)
2:      move.w  d1,V_SPHBV
        move.w  d0,V_SPHBY
        asr.w   #6,d0
        move.w  d0,V_SPHBYI             | partie entiere, relue par point dans sphere_draw
        rts

| essai : sphere de points, rotation 2 axes (sc_sin existant) + perspective approchee (sans division : voir
| sph_shrink) + zoom materiel SCB2 selon la profondeur.  Centre de projection anime par sphere_bounce (rebond en
| bas de l'ecran, glisse vers la droite) pendant que la sphere tourne sur elle-meme.  Appelee par saver_scroll
| (cd_done) a la place du dessin du texte qui ondule, quand V_SCENE = 1.  Modifie d0-d7, a0-a6 (a6 rendu = LSPC).
| 2.5.26 : memes resultats a l'octet pres qu'avant, environ deux fois moins de temps.  Les 8 produits de la rotation
| (v x sinus) viennent de 4 tables refaites a chaque image par additions (plus de muls), les points sont des mots
| deja doubles (indices directs), plus de pile dans la boucle, et les 3 x 96 mots partent en VRAM en rafales de
| move.w (a0)+,(a4) (12 cycles entre deux ecritures : le minimum du LSPC, wiki NeoGeoDev, page VRAM).
| Plages verifiees pour tous les couples d'angles et tous les points : Ym, Zm, Xm -64..63, Z1 -65..64 (tables X :
| -64..63, tables Y : -68..67), Z2 -66..66 (voir sph_shrink).
sphere_draw:
        bsr     sphere_step
        bsr     sphere_bounce
        lea     sc_sin,a2
        move.w  V_SPHAX,d0
        move.b  (a2,d0.w),d4            | d4 = sin(angle X)
        ext.w   d4
        move.w  d0,d1
        add.w   #64,d1
        and.w   #255,d1
        move.b  (a2,d1.w),d5            | d5 = cos(angle X) = sin(angle X + 64)
        ext.w   d5
        move.w  V_SPHAY,d0
        move.b  (a2,d0.w),d6            | d6 = sin(angle Y)
        ext.w   d6
        move.w  d0,d1
        add.w   #64,d1
        and.w   #255,d1
        move.b  (a2,d1.w),d7            | d7 = cos(angle Y)
        ext.w   d7
        | --- tables de produits : T[v] = v x c, de v = vmin en montant (une multiplication, puis des additions) ---
        lea     SPH_TCX,a2
        lea     SPH_TSX,a3
        moveq   #-64,d0
        move.w  d0,d1
        muls.w  d5,d0                   | -64 x cosX
        muls.w  d4,d1                   | -64 x sinX
        moveq   #128/8-1,d2
10:     .rept   8
        move.w  d0,(a2)+
        move.w  d1,(a3)+
        add.w   d5,d0
        add.w   d4,d1
        .endr
        dbra    d2,10b
        lea     SPH_TCY,a2
        lea     SPH_TSY,a3
        moveq   #-68,d0
        move.w  d0,d1
        muls.w  d7,d0                   | -68 x cosY
        muls.w  d6,d1                   | -68 x sinY
        moveq   #136/8-1,d2
11:     .rept   8
        move.w  d0,(a2)+
        move.w  d1,(a3)+
        add.w   d7,d0
        add.w   d6,d1
        .endr
        dbra    d2,11b
        lea     SPH_TCX+2*64,a2         | pointeurs sur v = 0 : indice = 2 v (signe)
        lea     SPH_TSX+2*64,a3
        lea     SPH_TCY+2*68,a4
        lea     SPH_TSY+2*68,a5
        lea     sph_shrink+2*64,a6      | zoom de Z2 : (a6, 2 x Z2)
        move.w  V_SPHBX,d4              | centre X (sphere_bounce)
        move.w  #496,d5                 | 496 - centre Y : SCB3 = (d5 - y) << 7
        sub.w   V_SPHBYI,d5
        lea     sph_pts,a0
        lea     V_SPHBUF,a1
        moveq   #SPH_N-1,d6
1:      move.w  (a0)+,d0                | d0 = 2 Xm
        move.w  (a0)+,d1                | d1 = 2 Ym
        move.w  (a0)+,d2                | d2 = 2 Zm
        | --- rotation axe X : Y1 = (Ym cosX - Zm sinX) >> 6 ; Z1 = (Ym sinX + Zm cosX) >> 6 ---
        move.w  (a2,d1.w),d3
        sub.w   (a3,d2.w),d3
        asr.w   #6,d3                   | d3 = Y1 (final)
        move.w  (a3,d1.w),d1
        add.w   (a2,d2.w),d1
        asr.w   #6,d1                   | d1 = Z1
        add.w   d1,d1                   | 2 Z1
        | --- rotation axe Y : X2 = (Xm cosY + Z1 sinY) >> 6 ; Z2 = (Z1 cosY - Xm sinY) >> 6 ---
        move.w  (a4,d0.w),d2
        add.w   (a5,d1.w),d2
        asr.w   #6,d2                   | d2 = X2 (final)
        move.w  (a4,d1.w),d1
        sub.w   (a5,d0.w),d1
        asr.w   #6,d1                   | d1 = Z2 (profondeur)
        | --- zoom materiel (table par Z2) ---
        move.w  d1,d0
        add.w   d0,d0
        move.w  (a6,d0.w),4*SPH_N(a1)   | SCB2
        | --- perspective approchee (sans division) : s = Z2 + 192 (128..256), puis x 3/2 (rayon ecran ~96 px) ---
        add.w   #192,d1                 | d1 = s
        muls.w  d1,d2                   | X2 x s
        asr.w   #8,d2
        move.w  d2,d0
        asr.w   #1,d0
        add.w   d0,d2
        add.w   d4,d2                   | X ecran
        lsl.w   #7,d2
        move.w  d2,2*SPH_N(a1)          | SCB4
        muls.w  d1,d3                   | Y1 x s
        asr.w   #8,d3
        move.w  d3,d0
        asr.w   #1,d0
        add.w   d0,d3
        move.w  d5,d0
        sub.w   d3,d0                   | 496 - Y ecran
        lsl.w   #7,d0                   | (masque des 9 bits implicite : le reste sort du mot)
        addq.w  #1,d0                   | hauteur = 1 tuile
        move.w  d0,(a1)+                | SCB3
        dbra    d6,1b
        | --- ecriture VRAM : 3 passages contigus depuis les 3 tableaux ---
        .if     SPH_N % 8
        .error  "SPH_N doit etre multiple de 8"
        .endif
        lea     LSPC,a6
        lea     2(a6),a4                | port de donnees VRAM
        move.w  #1,4(a6)
        move.w  #0x8000+SPH0,(a6)       | SCB2 : zoom
        lea     V_SPHBUF+4*SPH_N,a0
        moveq   #SPH_N/8-1,d0
2:      .rept   8
        move.w  (a0)+,(a4)
        .endr
        dbra    d0,2b
        move.w  #0x8200+SPH0,(a6)       | SCB3 : Y + hauteur
        lea     V_SPHBUF,a0
        moveq   #SPH_N/8-1,d0
3:      .rept   8
        move.w  (a0)+,(a4)
        .endr
        dbra    d0,3b
        move.w  #0x8400+SPH0,(a6)       | SCB4 : X
        lea     V_SPHBUF+2*SPH_N,a0
        moveq   #SPH_N/8-1,d0
4:      .rept   8
        move.w  (a0)+,(a4)
        .endr
        dbra    d0,4b
        rts

| grand texte : reecriture complete des 81 sprites, sprite TX0 = tranche d4 (modifie d0-d2, d6, d7, a1).  Appelee par
| saver_on (boucle principale, avant que l'economiseur soit visible) et, si le texte change, par l'interruption.
sc_full:
        move.w  d4,V_SLAST
        clr.w   V_HEAD
        movea.l V_STXT,a1
        move.w  V_SLEN,d6
        move.w  #1,4(a6)
        moveq   #0,d0                  | une seule division : caractere et tranche avancent ensuite par increments
        move.w  d4,d0                  |   (81 divisions couteraient ~15 lignes)
        divu    #10,d0
        move.l  d0,d2
        swap    d2
        moveq   #TX0,d7
3:      movem.w d0/d2,-(sp)
        bsr     sc_tile2
        movem.w (sp)+,d0/d2
        addq.w  #1,d2
        cmp.w   #10,d2
        bcs.s   34f
        moveq   #0,d2
        addq.w  #1,d0
34:     addq.w  #1,d7
        cmp.w   #TX0+NSPR,d7
        bcs.s   3b
        rts

| tirage de temps en temps (toutes les 10 a 20 s) : densite visee de 2 a 8 objets a l'ecran -> intervalle entre deux
| departs 312 / n (39..156 images, toujours >= BOX_GAP), et une diagonale (si elle change, elle attend que les
| boites en vol soient sorties) ; modifie d0-d2
box_phase:
        bsr     rnd
        divu    #600,d0
        swap    d0
        add.w   #600,d0
        move.w  d0,V_BOXPH
        bsr     rnd
        divu    #7,d0                  | 2 a 8 objets (10 emplacements : marge pour les vies plus longues)
        swap    d0
        addq.w  #2,d0
        move.l  #312,d2                | vie moyenne d'une boite a l'ecran ~312 images : n boites en vol -> 312 / n
        divu    d0,d2
        cmp.w   #BOX_GAP,d2
        bcc.s   2f
        moveq   #BOX_GAP,d2
2:      move.w  d2,V_BOXI
        bsr     rnd
        and.w   #3,d0
        cmp.w   V_BOXD,d0
        beq.s   1f
        move.w  d0,V_BOXND
1:      rts

| hasard : xorshift 16 bits (7, 9, 8) -> d0.l = 0..65535 (moitie haute nulle, pret pour divu) ; modifie d1
rnd:    move.w  V_RND,d0
        move.w  d0,d1
        lsl.w   #7,d1
        eor.w   d1,d0
        move.w  d0,d1
        lsr.w   #8,d1
        lsr.w   #1,d1
        eor.w   d1,d0
        move.w  d0,d1
        lsl.w   #8,d1
        eor.w   d1,d0
        move.w  d0,V_RND
        and.l   #0xFFFF,d0
        rts

| grand texte : tranche d5 (absolue) -> tuiles du sprite d7 ; a1 = texte, d6 = longueur (modifie d0-d2)
sc_tile:
        moveq   #0,d0
        move.w  d5,d0
        divu    #10,d0                 | 10 tranches de 4 px par caractere (police x5 : 40 px)
        move.l  d0,d2
        swap    d2                     | d2 = tranche dans le caractere
| d0 = caractere (absolu, non reduit), d2 = tranche 0..9, d7 = sprite (modifie d0-d2)
sc_tile2:
1:      cmp.w   d6,d0                  | caractere, modulo la longueur du texte
        bcs.s   2f
        sub.w   d6,d0
        bra.s   1b
2:      moveq   #0,d1
        move.b  (a1,d0.w),d1
        sub.w   #0x20,d1
        cmp.w   #0x40,d1
        bcs.s   3f
        moveq   #0,d1                  | hors de la police (0x20..0x5F) : espace
3:      move.w  d1,d0                  | 10 x caractere + tranche, puis x 3 tuiles
        lsl.w   #3,d1
        add.w   d0,d0
        add.w   d0,d1
        add.w   d2,d1
        move.w  d1,d0
        add.w   d1,d1
        add.w   d0,d1
        add.w   #SC_TILE0,d1
        move.w  d7,d2
        lsl.w   #6,d2
        move.w  d2,(a6)
        move.w  d1,2(a6)               | tuile du haut
        move.w  #0x1000,2(a6)          | palette 16
        addq.w  #1,d1
        move.w  d1,2(a6)               | tuile du milieu
        move.w  #0x1000,2(a6)
        addq.w  #1,d1
        move.w  d1,2(a6)               | tuile du bas
        move.w  #0x1000,2(a6)
        rts

| d5 = premier caractere de V_IBUF, d7 = premier sprite : SM_N sprites d'un caractere (petite police, palette 18)
wr_info:
        lea     V_IBUF,a1
        move.w  V_ILEN,d6
1:      cmp.w   d6,d5
        bcs.s   2f
        sub.w   d6,d5
        bra.s   1b
2:      moveq   #SM_N-1,d4
3:      move.w  d7,d2
        lsl.w   #6,d2
        move.w  d2,(a6)
        moveq   #0,d1
        move.b  (a1,d5.w),d1
        sub.w   #0x20,d1
        cmp.w   #0x5F,d1
        bcs.s   4f
        moveq   #0,d1                  | hors de 0x20..0x7E : espace
4:      add.w   #SM_TILE0,d1
        move.w  d1,2(a6)
        move.w  #0x1200,2(a6)
        addq.w  #1,d5
        cmp.w   d6,d5
        bcs.s   5f
        moveq   #0,d5
5:      addq.w  #1,d7
        dbra    d4,3b
        rts

| V_IBUF <- "ALBUM  <titre>   -   TRACK nn/nn   -   TIME mm:ss   -   REMAINING mm:ss   -   " (PAUSED / STOPPED)
build_info:
        movem.l d0-d7/a0-a3,-(sp)
        lea     V_IBUF,a0
        lea     t_i_album,a2
        bsr     bcopy
        move.w  V_GAME,d0              | jeu en lecture, sinon celui du curseur
        tst.w   V_PLAY
        beq.s   1f
        move.w  V_PG,d0
1:      bsr     gentry
        movea.l a1,a3
        moveq   #23,d2
2:      move.b  (a3)+,d3
        beq.s   3f
        move.b  d3,(a0)+
        dbra    d2,2b
3:      tst.w   V_PLAY
        bne.s   4f
        lea     t_i_stop,a2
        bsr     bcopy
        bra.s   8f
4:      lea     t_i_track,a2
        bsr     bcopy
        move.w  V_PT,d4
        addq.w  #1,d4
        bsr     b2d
        move.b  #0x2F,(a0)+
        move.w  26(a1),d4
        bsr     b2d
        lea     t_i_time,a2
        bsr     bcopy
        move.w  V_SECS,d4
        bsr     bmmss
        lea     t_i_rem,a2
        bsr     bcopy
        move.w  V_TLEN,d4
        sub.w   V_SECS,d4
        bcc.s   5f
        moveq   #0,d4
5:      bsr     bmmss
        tst.w   V_PAUSE
        beq.s   8f
        lea     t_i_pause,a2
        bsr     bcopy
8:      lea     t_i_end,a2
        bsr     bcopy
        move.l  a0,d0
        sub.l   #V_IBUF,d0
        move.w  d0,V_ILEN
        movem.l (sp)+,d0-d7/a0-a3
        rts

bcopy:  move.b  (a2)+,(a0)+
        bne.s   bcopy
        subq.l  #1,a0
        rts

| d4 (0..99, plafonne) -> 2 chiffres
b2d:    and.l   #0xFFFF,d4
        cmp.w   #99,d4
        bls.s   1f
        moveq   #99,d4
1:      divu    #10,d4
        add.b   #0x30,d4
        move.b  d4,(a0)+
        swap    d4
        add.b   #0x30,d4
        move.b  d4,(a0)+
        rts

| d4 secondes -> mm:ss
bmmss:  and.l   #0xFFFF,d4
        divu    #60,d4
        move.l  d4,-(sp)
        bsr     b2d
        move.b  #0x3A,(a0)+
        move.l  (sp)+,d4
        swap    d4
        bra     b2d

t_i_album: .asciz "ALBUM  "
t_i_track: .asciz "   -   TRACK "
t_i_time:  .asciz "   -   TIME "
t_i_rem:   .asciz "   -   REMAINING "
t_i_pause: .asciz "   -   PAUSED"
t_i_stop:  .asciz "   -   STOPPED"
t_i_end:   .asciz "   -   "

| objets animes : remplis par le constructeur (ngt_studio.py, JB_BOXDATA_OFF) : nombre de planches (0..2), puis une
| description par planche
box_g:    .byte   0, 1, 2, 0, 1, 2, 0, 1, 2, 0      | emplacement modulo 3
          .balign 2
| description (BOX_DSC octets, depuis +2) : images, large (regle d'espacement), 1re tuile, palette (16 mots),
| colonnes - 1 (+38), rangees (+40), tuiles par image (+42), 320 - largeur (+44), 224 - hauteur (+46)
boxdata:  .word   0
          .fill   BOX_DSC*BOX_NP, 1, 0
| hauteur des boites : v = t x 17 / 22 - 48 pour t = 0..351 (de -48 a 223 px)
box_v:
        .word   -48, -48, -47, -46, -45, -45, -44, -43, -42, -42, -41, -40, -39, -38, -38, -37
        .word   -36, -35, -35, -34, -33, -32, -31, -31, -30, -29, -28, -28, -27, -26, -25, -25
        .word   -24, -23, -22, -21, -21, -20, -19, -18, -18, -17, -16, -15, -14, -14, -13, -12
        .word   -11, -11, -10, -9, -8, -8, -7, -6, -5, -4, -4, -3, -2, -1, -1, 0
        .word   1, 2, 3, 3, 4, 5, 6, 6, 7, 8, 9, 9, 10, 11, 12, 13
        .word   13, 14, 15, 16, 16, 17, 18, 19, 20, 20, 21, 22, 23, 23, 24, 25
        .word   26, 26, 27, 28, 29, 30, 30, 31, 32, 33, 33, 34, 35, 36, 37, 37
        .word   38, 39, 40, 40, 41, 42, 43, 43, 44, 45, 46, 47, 47, 48, 49, 50
        .word   50, 51, 52, 53, 54, 54, 55, 56, 57, 57, 58, 59, 60, 60, 61, 62
        .word   63, 64, 64, 65, 66, 67, 67, 68, 69, 70, 71, 71, 72, 73, 74, 74
        .word   75, 76, 77, 77, 78, 79, 80, 81, 81, 82, 83, 84, 84, 85, 86, 87
        .word   88, 88, 89, 90, 91, 91, 92, 93, 94, 94, 95, 96, 97, 98, 98, 99
        .word   100, 101, 101, 102, 103, 104, 105, 105, 106, 107, 108, 108, 109, 110, 111, 111
        .word   112, 113, 114, 115, 115, 116, 117, 118, 118, 119, 120, 121, 122, 122, 123, 124
        .word   125, 125, 126, 127, 128, 128, 129, 130, 131, 132, 132, 133, 134, 135, 135, 136
        .word   137, 138, 139, 139, 140, 141, 142, 142, 143, 144, 145, 145, 146, 147, 148, 149
        .word   149, 150, 151, 152, 152, 153, 154, 155, 156, 156, 157, 158, 159, 159, 160, 161
        .word   162, 162, 163, 164, 165, 166, 166, 167, 168, 169, 169, 170, 171, 172, 173, 173
        .word   174, 175, 176, 176, 177, 178, 179, 179, 180, 181, 182, 183, 183, 184, 185, 186
        .word   186, 187, 188, 189, 190, 190, 191, 192, 193, 193, 194, 195, 196, 196, 197, 198
        .word   199, 200, 200, 201, 202, 203, 203, 204, 205, 206, 207, 207, 208, 209, 210, 210
        .word   211, 212, 213, 213, 214, 215, 216, 217, 217, 218, 219, 220, 220, 221, 222, 223
| flash des coups de batterie (indice = images restantes 1..6) : OU sur les composantes R, V, B de l'arc-en-ciel
sc_flash: .word 0x0111, 0x0222, 0x0444, 0x0666, 0x0888, 0x0AAA
| scintillement du lisere des boites : gris de 21/31 a 27/31 (~170 a ~220 sur 255), centre sur le gris 75 % choisi
sc_twk:   .word 0x7AAA, 0x7AAA, 0x0BBB, 0x7BBB, 0x0CCC, 0x7CCC, 0x0DDD, 0x7DDD
| fondu du CD (16 paliers de luminosite, 0 = noir/transparent a l'oeil .. 15 = couleurs d'origine de la planche 4 ;
| genere depuis boxdata par echelle lineaire de chaque composante R/V/B, voir le script de build)
cd_fade_tab:
        .word   0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000
        .word   0x0111, 0x0111, 0x0111, 0x0111, 0x4011, 0x4011, 0x6001, 0x7000, 0x7000, 0x6001, 0x7000, 0x5000, 0x5000, 0x0000
        .word   0x1221, 0x4122, 0x6112, 0x7111, 0x0122, 0x2112, 0x3111, 0x1111, 0x0111, 0x4012, 0x4011, 0x6101, 0x7000, 0x1000
        .word   0x1332, 0x4233, 0x7222, 0x7222, 0x4133, 0x6123, 0x5122, 0x4122, 0x6112, 0x2113, 0x1111, 0x2202, 0x2101, 0x5000
        .word   0x1443, 0x4344, 0x7333, 0x1333, 0x0244, 0x2234, 0x5233, 0x7222, 0x1222, 0x5123, 0x6112, 0x7202, 0x3101, 0x6001
        .word   0x1554, 0x4455, 0x7444, 0x1444, 0x4255, 0x4245, 0x3334, 0x1333, 0x6223, 0x7124, 0x5122, 0x4313, 0x5111, 0x6001
        .word   0x0665, 0x0566, 0x1555, 0x4455, 0x0366, 0x0356, 0x4345, 0x6334, 0x1333, 0x1235, 0x2223, 0x1413, 0x4112, 0x6001
        .word   0x0776, 0x0677, 0x1666, 0x6556, 0x4377, 0x4367, 0x0456, 0x1444, 0x6334, 0x7236, 0x5233, 0x4414, 0x1212, 0x7001
        .word   0x0887, 0x3777, 0x0777, 0x2667, 0x4488, 0x2468, 0x6457, 0x5455, 0x6435, 0x7247, 0x5234, 0x6515, 0x3212, 0x3101
        .word   0x0998, 0x3888, 0x0888, 0x0778, 0x0599, 0x6479, 0x2568, 0x2556, 0x1545, 0x1358, 0x2335, 0x3615, 0x6213, 0x2102
        .word   0x1AA8, 0x7899, 0x6889, 0x5788, 0x45AA, 0x258A, 0x5578, 0x5566, 0x6546, 0x7359, 0x5345, 0x6616, 0x7213, 0x2102
        .word   0x1BB9, 0x79AA, 0x699A, 0x5899, 0x06BB, 0x459B, 0x3679, 0x3667, 0x1656, 0x536A, 0x6346, 0x5726, 0x1323, 0x2102
        .word   0x1CCA, 0x7ABB, 0x6AAB, 0x399A, 0x46CC, 0x06AC, 0x378A, 0x0778, 0x6657, 0x246B, 0x1456, 0x0827, 0x0324, 0x1112
        .word   0x1DDB, 0x7BCC, 0x7BBB, 0x3AAB, 0x07DD, 0x46BD, 0x579B, 0x5788, 0x0768, 0x447C, 0x4457, 0x4828, 0x5324, 0x5112
        .word   0x0EEC, 0x3CDD, 0x1CCC, 0x4ABC, 0x47EE, 0x27BE, 0x08AC, 0x3889, 0x7768, 0x647D, 0x7457, 0x7928, 0x7324, 0x4113
        .word   0x0FFD, 0x3DEE, 0x1DDD, 0x4BCD, 0x08FF, 0x67CF, 0x68AD, 0x489A, 0x0879, 0x058E, 0x0568, 0x2A29, 0x2425, 0x4113
t_sc_play: .asciz "NEO GEO JUKEBOX - ENJOY FINE MUSIC ! - NIC034 / DELTA ISLAND    "
t_sc_stop: .asciz "NEO GEO JUKEBOX THANKS FOR USING THIS SOFTWARE - NIC034 / DELTA ISLAND    "
| sinus x 64 sur 256 pas (l'amplitude est appliquee ensuite)
sc_sin:
        .byte   0, 2, 3, 5, 6, 8, 9, 11, 12, 14, 16, 17, 19, 20, 22, 23
        .byte   24, 26, 27, 29, 30, 32, 33, 34, 36, 37, 38, 39, 41, 42, 43, 44
        .byte   45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 56, 57, 58, 59
        .byte   59, 60, 60, 61, 61, 62, 62, 62, 63, 63, 63, 63, 63, 63, 63, 63
        .byte   63, 63, 63, 63, 63, 63, 63, 63, 63, 62, 62, 62, 61, 61, 60, 60
        .byte   59, 59, 58, 57, 56, 56, 55, 54, 53, 52, 51, 50, 49, 48, 47, 46
        .byte   45, 44, 43, 42, 41, 39, 38, 37, 36, 34, 33, 32, 30, 29, 27, 26
        .byte   24, 23, 22, 20, 19, 17, 16, 14, 12, 11, 9, 8, 6, 5, 3, 2
        .byte   0, -2, -3, -5, -6, -8, -9, -11, -12, -14, -16, -17, -19, -20, -22, -23
        .byte   -24, -26, -27, -29, -30, -32, -33, -34, -36, -37, -38, -39, -41, -42, -43, -44
        .byte   -45, -46, -47, -48, -49, -50, -51, -52, -53, -54, -55, -56, -56, -57, -58, -59
        .byte   -59, -60, -60, -61, -61, -62, -62, -62, -63, -63, -63, -64, -64, -64, -64, -64
        .byte   -64, -64, -64, -64, -64, -64, -63, -63, -63, -62, -62, -62, -61, -61, -60, -60
        .byte   -59, -59, -58, -57, -56, -56, -55, -54, -53, -52, -51, -50, -49, -48, -47, -46
        .byte   -45, -44, -43, -42, -41, -39, -38, -37, -36, -34, -33, -32, -30, -29, -27, -26
        .byte   -24, -23, -22, -20, -19, -17, -16, -14, -12, -11, -9, -8, -6, -5, -3, -2
        .balign 2

| --- essai : sphere de points (tools/gen_sphere.py), remplace le texte qui ondule par phases de 60 s ---
.macro  SPT x, y, z
        .word   2*(\x), 2*(\y), 2*(\z)
        .endm
sph_pts:                               | 96 points (X,Y,Z), -64..63, coherent avec sc_sin (meme amplitude) ;
                                       |   ranges en mots DOUBLES (2.5.26 : indices directs des tables de sphere_draw)
        SPT     0, 63, 0
        SPT     -10, 63, 9
        SPT     2, 61, -18
        SPT     14, 60, 18
        SPT     -25, 59, -4
        SPT     24, 57, -15
        SPT     -8, 56, 30
        SPT     -15, 55, -30
        SPT     33, 53, 12
        SPT     -35, 52, 14
        SPT     17, 51, -36
        SPT     12, 49, 39
        SPT     -37, 48, -21
        SPT     43, 46, -9
        SPT     -26, 45, 37
        SPT     -6, 44, -46
        SPT     37, 42, 31
        SPT     -49, 41, 2
        SPT     36, 40, -35
        SPT     -2, 38, 51
        SPT     -33, 37, -40
        SPT     53, 36, 7
        SPT     -44, 34, 31
        SPT     12, 33, -53
        SPT     28, 32, 48
        SPT     -54, 30, -17
        SPT     52, 29, -24
        SPT     -22, 28, 53
        SPT     -20, 26, -55
        SPT     52, 25, 27
        SPT     -58, 24, 15
        SPT     32, 22, -50
        SPT     10, 21, 60
        SPT     -48, 20, -37
        SPT     61, 18, -5
        SPT     -42, 17, 45
        SPT     0, 15, -62
        SPT     42, 14, 46
        SPT     -62, 13, -6
        SPT     50, 11, -38
        SPT     -11, 10, 62
        SPT     -34, 9, -54
        SPT     61, 7, 17
        SPT     -57, 6, 29
        SPT     22, 5, -60
        SPT     24, 3, 59
        SPT     -58, 2, -27
        SPT     61, 1, -19
        SPT     -32, -1, 55
        SPT     -13, -2, -63
        SPT     52, -3, 37
        SPT     -63, -5, 8
        SPT     41, -6, -49
        SPT     2, -7, 63
        SPT     -44, -9, -45
        SPT     63, -10, 3
        SPT     -49, -11, 40
        SPT     9, -13, -62
        SPT     35, -14, 51
        SPT     -61, -15, -14
        SPT     54, -17, -30
        SPT     -19, -18, 58
        SPT     -25, -20, -55
        SPT     56, -21, 24
        SPT     -57, -22, 20
        SPT     28, -24, -53
        SPT     15, -25, 57
        SPT     -49, -26, -32
        SPT     57, -28, -10
        SPT     -35, -29, 45
        SPT     -4, -30, -56
        SPT     41, -32, 38
        SPT     -55, -33, -1
        SPT     40, -34, -36
        SPT     -5, -36, 53
        SPT     -31, -37, -42
        SPT     50, -38, 9
        SPT     -43, -40, 27
        SPT     13, -41, -47
        SPT     22, -42, 43
        SPT     -44, -44, -16
        SPT     42, -45, -17
        SPT     -19, -46, 40
        SPT     -12, -48, -41
        SPT     35, -49, 21
        SPT     -38, -51, 8
        SPT     22, -52, -30
        SPT     4, -53, 35
        SPT     -25, -55, -22
        SPT     31, -56, -1
        SPT     -20, -57, 20
        SPT     1, -59, -26
        SPT     14, -60, 17
        SPT     -18, -61, -3
        SPT     11, -63, -7
        SPT     0, -64, 0
        .balign 2
        .word   0xF900, 0xC000          | Z2 = -66, -65 (etape A : octets identiques a la 2.5.25)
sph_shrink:                             | SCB2 par Z'' (-64..63) : bits0-7 Y-shrink, bits8-11 X-shrink
        .word   0x0559, 0x055B, 0x055C, 0x055D, 0x065E, 0x0660, 0x0661, 0x0662
        .word   0x0664, 0x0665, 0x0666, 0x0667, 0x0669, 0x066A, 0x066B, 0x066D
        .word   0x066E, 0x076F, 0x0771, 0x0772, 0x0773, 0x0774, 0x0776, 0x0777
        .word   0x0778, 0x077A, 0x077B, 0x077C, 0x077E, 0x077F, 0x0880, 0x0881
        .word   0x0883, 0x0884, 0x0885, 0x0887, 0x0888, 0x0889, 0x088A, 0x088C
        .word   0x088D, 0x088E, 0x0890, 0x0991, 0x0992, 0x0994, 0x0995, 0x0996
        .word   0x0997, 0x0999, 0x099A, 0x099B, 0x099D, 0x099E, 0x099F, 0x09A0
        .word   0x0AA2, 0x0AA3, 0x0AA4, 0x0AA6, 0x0AA7, 0x0AA8, 0x0AAA, 0x0AAB
        .word   0x0AAC, 0x0AAD, 0x0AAF, 0x0AB0, 0x0AB1, 0x0BB3, 0x0BB4, 0x0BB5
        .word   0x0BB6, 0x0BB8, 0x0BB9, 0x0BBA, 0x0BBC, 0x0BBD, 0x0BBE, 0x0BC0
        .word   0x0BC1, 0x0BC2, 0x0BC3, 0x0CC5, 0x0CC6, 0x0CC7, 0x0CC9, 0x0CCA
        .word   0x0CCB, 0x0CCC, 0x0CCE, 0x0CCF, 0x0CD0, 0x0CD2, 0x0CD3, 0x0CD4
        .word   0x0DD6, 0x0DD7, 0x0DD8, 0x0DD9, 0x0DDB, 0x0DDC, 0x0DDD, 0x0DDF
        .word   0x0DE0, 0x0DE1, 0x0DE3, 0x0DE4, 0x0DE5, 0x0EE6, 0x0EE8, 0x0EE9
        .word   0x0EEA, 0x0EEC, 0x0EED, 0x0EEE, 0x0EEF, 0x0EF1, 0x0EF2, 0x0EF3
        .word   0x0EF5, 0x0EF6, 0x0FF7, 0x0FF9, 0x0FFA, 0x0FFB, 0x0FFC, 0x0FFE
        .word   0x41F9, 0x0040, 0x0000  | Z2 = 64, 65, 66 (etape A : octets identiques a la 2.5.25)
| --- fin des tables generees ---

| d7 = 0 : couleurs normales ; 1 : couleurs a 50 % (sauf la couleur 1 des palettes 10..15 : logo vif)
setpals:                               | ecriture directe (demarrage, reprise MVS : une seule fois, l'ecran est redessine)
        lea     0x400000,a0
        lea     0x401FFE,a2
        moveq   #32,d5
        bra.s   setp_to
pal_prep:                              | calcul dans V_PALB (boucle principale), pose ensuite par le VBlank (pal_copy)
        lea     V_PALB,a0
        lea     V_PALB+160,a2
        moveq   #10,d5
setp_to:                               | a0 = palette 0, d5 = ecart entre palettes, a2 = couleur de fond
        lea     paltab,a1
        moveq   #0,d6
1:      clr.w   (a0)
        move.w  (a1)+,d0
        tst.w   d7
        beq.s   3f
        cmp.w   #10,d6
        bcc.s   2f
        bsr     dimc
3:      move.w  d0,2(a0)
2:      move.w  (a1)+,d0
        bsr     dimif
        move.w  d0,4(a0)
        move.w  #0x7FFF,d0
        bsr     dimif
        move.w  d0,6(a0)
        move.w  #0x0236,d0
        bsr     dimif
        move.w  d0,8(a0)
        adda.w  d5,a0
        addq.w  #1,d6
        cmp.w   #16,d6
        bcs.s   1b
        move.w  #BACKDROP,d0
        bsr     dimif
        move.w  d0,(a2)
        rts

| VBlank : recopie de V_PALB (calculee par pal_prep) dans la RAM de palettes : 81 mots, sans calcul
pal_copy:
        lea     V_PALB,a0
        lea     0x400000,a1
        moveq   #15,d0
1:      move.w  (a0)+,(a1)+
        move.w  (a0)+,(a1)+
        move.w  (a0)+,(a1)+
        move.w  (a0)+,(a1)+
        move.w  (a0)+,(a1)+
        lea     22(a1),a1
        dbra    d0,1b
        move.w  (a0),0x401FFE
        rts

dimif:  tst.w   d7
        bne.s   dimc
        rts

| couleur Neo Geo d0 -> meme teinte, intensite / 2 (chaque composante sur 5 bits divisee par 2)
dimc:   movem.l d1-d4,-(sp)
        moveq   #0,d3
        moveq   #8,d4                  | rouge : bits 11..8 + bit faible 14
        moveq   #14,d2
        bsr.s   dimch
        moveq   #4,d4                  | vert : bits 7..4 + bit 13
        moveq   #13,d2
        bsr.s   dimch
        moveq   #0,d4                  | bleu : bits 3..0 + bit 12
        moveq   #12,d2
        bsr.s   dimch
        move.w  d3,d0
        movem.l (sp)+,d1-d4
        rts
dimch:  move.w  d0,d1
        lsr.w   d4,d1
        and.w   #15,d1
        add.w   d1,d1
        btst    d2,d0
        beq.s   1f
        addq.w  #1,d1
1:      lsr.w   #1,d1
        btst    #0,d1
        beq.s   2f
        bset    d2,d3
2:      lsr.w   #1,d1
        lsl.w   d4,d1
        or.w    d1,d3
        rts

        .balign 2
| --- debut des tables generees par tools/gen_tables.py ---
sc_ylut:                                | 2 x (dy + 64) -> valeur SCB3 (hauteur 3 tuiles)
        .word   0xEA03, 0xE983, 0xE903, 0xE883, 0xE803, 0xE783, 0xE703, 0xE683
        .word   0xE603, 0xE583, 0xE503, 0xE483, 0xE403, 0xE383, 0xE303, 0xE283
        .word   0xE203, 0xE183, 0xE103, 0xE083, 0xE003, 0xDF83, 0xDF03, 0xDE83
        .word   0xDE03, 0xDD83, 0xDD03, 0xDC83, 0xDC03, 0xDB83, 0xDB03, 0xDA83
        .word   0xDA03, 0xD983, 0xD903, 0xD883, 0xD803, 0xD783, 0xD703, 0xD683
        .word   0xD603, 0xD583, 0xD503, 0xD483, 0xD403, 0xD383, 0xD303, 0xD283
        .word   0xD203, 0xD183, 0xD103, 0xD083, 0xD003, 0xCF83, 0xCF03, 0xCE83
        .word   0xCE03, 0xCD83, 0xCD03, 0xCC83, 0xCC03, 0xCB83, 0xCB03, 0xCA83
        .word   0xCA03, 0xC983, 0xC903, 0xC883, 0xC803, 0xC783, 0xC703, 0xC683
        .word   0xC603, 0xC583, 0xC503, 0xC483, 0xC403, 0xC383, 0xC303, 0xC283
        .word   0xC203, 0xC183, 0xC103, 0xC083, 0xC003, 0xBF83, 0xBF03, 0xBE83
        .word   0xBE03, 0xBD83, 0xBD03, 0xBC83, 0xBC03, 0xBB83, 0xBB03, 0xBA83
        .word   0xBA03, 0xB983, 0xB903, 0xB883, 0xB803, 0xB783, 0xB703, 0xB683
        .word   0xB603, 0xB583, 0xB503, 0xB483, 0xB403, 0xB383, 0xB303, 0xB283
        .word   0xB203, 0xB183, 0xB103, 0xB083, 0xB003, 0xAF83, 0xAF03, 0xAE83
        .word   0xAE03, 0xAD83, 0xAD03, 0xAC83, 0xAC03, 0xAB83, 0xAB03, 0xAA83
sc_ytab:
| amplitude 28 px
        .byte   128, 128, 128, 128, 130, 130, 132, 132, 132, 134, 134, 134, 134, 136, 136, 138, 138, 138, 140, 140, 142, 142, 142, 142, 144, 144, 144, 146, 146, 146, 148, 148
        .byte   148, 148, 150, 150, 150, 152, 152, 152, 154, 154, 156, 156, 156, 156, 156, 158, 158, 158, 160, 160, 160, 162, 162, 162, 162, 162, 164, 164, 164, 166, 166, 166
        .byte   166, 168, 168, 168, 168, 170, 170, 170, 170, 170, 170, 172, 172, 172, 172, 174, 174, 174, 174, 174, 176, 176, 176, 176, 176, 176, 176, 178, 178, 178, 178, 178
        .byte   178, 178, 180, 180, 180, 180, 180, 180, 180, 180, 182, 182, 182, 182, 182, 182, 182, 182, 182, 182, 182, 182, 182, 182, 182, 182, 182, 182, 182, 182, 182, 182
        .byte   182, 182, 182, 182, 182, 182, 182, 182, 182, 182, 182, 182, 182, 182, 182, 182, 182, 182, 182, 182, 182, 182, 182, 180, 180, 180, 180, 180, 180, 180, 180, 178
        .byte   178, 178, 178, 178, 178, 178, 176, 176, 176, 176, 176, 176, 176, 174, 174, 174, 174, 174, 172, 172, 172, 172, 170, 170, 170, 170, 170, 170, 168, 168, 168, 168
        .byte   166, 166, 166, 166, 164, 164, 164, 162, 162, 162, 162, 162, 160, 160, 160, 158, 158, 158, 156, 156, 156, 156, 156, 154, 154, 152, 152, 152, 150, 150, 150, 148
        .byte   148, 148, 148, 146, 146, 146, 144, 144, 144, 142, 142, 142, 142, 140, 140, 138, 138, 138, 136, 136, 134, 134, 134, 134, 132, 132, 132, 130, 130, 128, 128, 128
        .byte   128, 126, 126, 126, 124, 124, 122, 122, 122, 120, 120, 120, 120, 118, 118, 116, 116, 116, 114, 114, 114, 114, 112, 112, 110, 110, 110, 108, 108, 108, 106, 106
        .byte   106, 106, 104, 104, 104, 102, 102, 102, 100, 100, 100, 100, 98, 98, 98, 96, 96, 96, 94, 94, 94, 92, 92, 92, 92, 92, 90, 90, 90, 88, 88, 88
        .byte   88, 86, 86, 86, 86, 86, 86, 84, 84, 84, 84, 82, 82, 82, 82, 80, 80, 80, 80, 80, 78, 78, 78, 78, 78, 78, 78, 76, 76, 76, 76, 76
        .byte   76, 76, 74, 74, 74, 74, 74, 74, 74, 74, 72, 72, 72, 72, 72, 72, 72, 72, 72, 72, 72, 72, 72, 72, 72, 72, 72, 72, 72, 72, 72, 72
        .byte   72, 72, 72, 72, 72, 72, 72, 72, 72, 72, 72, 72, 72, 72, 72, 72, 72, 72, 72, 72, 72, 72, 72, 74, 74, 74, 74, 74, 74, 74, 74, 76
        .byte   76, 76, 76, 76, 76, 76, 78, 78, 78, 78, 78, 78, 78, 80, 80, 80, 80, 80, 82, 82, 82, 82, 84, 84, 84, 84, 86, 86, 86, 86, 86, 86
        .byte   88, 88, 88, 88, 90, 90, 90, 92, 92, 92, 92, 92, 94, 94, 94, 96, 96, 96, 98, 98, 98, 100, 100, 100, 100, 102, 102, 102, 104, 104, 104, 106
        .byte   106, 106, 106, 108, 108, 108, 110, 110, 110, 112, 112, 114, 114, 114, 114, 116, 116, 116, 118, 118, 120, 120, 120, 120, 122, 122, 122, 124, 124, 126, 126, 126
| amplitude 30 px
        .byte   128, 128, 128, 128, 130, 130, 132, 132, 132, 134, 134, 136, 136, 136, 138, 138, 138, 140, 140, 142, 142, 142, 142, 144, 144, 144, 146, 146, 148, 148, 148, 150
        .byte   150, 150, 152, 152, 152, 154, 154, 154, 156, 156, 158, 158, 158, 158, 158, 160, 160, 160, 162, 162, 162, 164, 164, 164, 166, 166, 166, 166, 168, 168, 168, 170
        .byte   170, 170, 170, 172, 172, 172, 172, 172, 172, 174, 174, 174, 174, 176, 176, 176, 176, 178, 178, 178, 178, 178, 180, 180, 180, 180, 180, 182, 182, 182, 182, 182
        .byte   182, 182, 184, 184, 184, 184, 184, 184, 184, 184, 186, 186, 186, 186, 186, 186, 186, 186, 186, 186, 186, 186, 186, 186, 186, 186, 186, 186, 186, 186, 186, 186
        .byte   186, 186, 186, 186, 186, 186, 186, 186, 186, 186, 186, 186, 186, 186, 186, 186, 186, 186, 186, 186, 186, 186, 186, 184, 184, 184, 184, 184, 184, 184, 184, 182
        .byte   182, 182, 182, 182, 182, 182, 180, 180, 180, 180, 180, 178, 178, 178, 178, 178, 176, 176, 176, 176, 174, 174, 174, 174, 172, 172, 172, 172, 172, 172, 170, 170
        .byte   170, 170, 168, 168, 168, 166, 166, 166, 166, 164, 164, 164, 162, 162, 162, 160, 160, 160, 158, 158, 158, 158, 158, 156, 156, 154, 154, 154, 152, 152, 152, 150
        .byte   150, 150, 148, 148, 148, 146, 146, 144, 144, 144, 142, 142, 142, 142, 140, 140, 138, 138, 138, 136, 136, 136, 134, 134, 132, 132, 132, 130, 130, 128, 128, 128
        .byte   128, 126, 126, 126, 124, 124, 122, 122, 122, 120, 120, 118, 118, 118, 116, 116, 116, 114, 114, 112, 112, 112, 112, 110, 110, 110, 108, 108, 106, 106, 106, 104
        .byte   104, 104, 102, 102, 102, 100, 100, 100, 98, 98, 98, 98, 96, 96, 96, 94, 94, 94, 92, 92, 92, 90, 90, 90, 88, 88, 88, 88, 86, 86, 86, 84
        .byte   84, 84, 84, 82, 82, 82, 82, 82, 82, 80, 80, 80, 80, 78, 78, 78, 78, 76, 76, 76, 76, 76, 74, 74, 74, 74, 74, 72, 72, 72, 72, 72
        .byte   72, 72, 70, 70, 70, 70, 70, 70, 70, 70, 68, 68, 68, 68, 68, 68, 68, 68, 68, 68, 68, 68, 68, 68, 68, 68, 68, 68, 68, 68, 68, 68
        .byte   68, 68, 68, 68, 68, 68, 68, 68, 68, 68, 68, 68, 68, 68, 68, 68, 68, 68, 68, 68, 68, 68, 68, 70, 70, 70, 70, 70, 70, 70, 70, 72
        .byte   72, 72, 72, 72, 72, 72, 74, 74, 74, 74, 74, 76, 76, 76, 76, 76, 78, 78, 78, 78, 80, 80, 80, 80, 82, 82, 82, 82, 82, 82, 84, 84
        .byte   84, 84, 86, 86, 86, 88, 88, 88, 88, 90, 90, 90, 92, 92, 92, 94, 94, 94, 96, 96, 96, 98, 98, 98, 98, 100, 100, 100, 102, 102, 102, 104
        .byte   104, 104, 106, 106, 106, 108, 108, 110, 110, 110, 112, 112, 112, 112, 114, 114, 116, 116, 116, 118, 118, 118, 120, 120, 122, 122, 122, 124, 124, 126, 126, 126
| amplitude 32 px
        .byte   128, 128, 130, 130, 130, 132, 132, 132, 134, 134, 136, 136, 136, 138, 138, 140, 140, 140, 142, 142, 144, 144, 144, 146, 146, 146, 148, 148, 150, 150, 150, 152
        .byte   152, 152, 154, 154, 154, 156, 156, 156, 158, 158, 160, 160, 160, 162, 162, 162, 164, 164, 164, 164, 166, 166, 166, 168, 168, 168, 170, 170, 170, 172, 172, 172
        .byte   172, 174, 174, 174, 174, 176, 176, 176, 176, 178, 178, 178, 178, 180, 180, 180, 180, 182, 182, 182, 182, 182, 184, 184, 184, 184, 184, 186, 186, 186, 186, 186
        .byte   186, 186, 188, 188, 188, 188, 188, 188, 188, 188, 190, 190, 190, 190, 190, 190, 190, 190, 190, 190, 190, 190, 190, 190, 190, 190, 190, 190, 190, 190, 190, 190
        .byte   190, 190, 190, 190, 190, 190, 190, 190, 190, 190, 190, 190, 190, 190, 190, 190, 190, 190, 190, 190, 190, 190, 190, 188, 188, 188, 188, 188, 188, 188, 188, 186
        .byte   186, 186, 186, 186, 186, 186, 184, 184, 184, 184, 184, 182, 182, 182, 182, 182, 180, 180, 180, 180, 178, 178, 178, 178, 176, 176, 176, 176, 174, 174, 174, 174
        .byte   172, 172, 172, 172, 170, 170, 170, 168, 168, 168, 166, 166, 166, 164, 164, 164, 164, 162, 162, 162, 160, 160, 160, 158, 158, 156, 156, 156, 154, 154, 154, 152
        .byte   152, 152, 150, 150, 150, 148, 148, 146, 146, 146, 144, 144, 144, 142, 142, 140, 140, 140, 138, 138, 136, 136, 136, 134, 134, 132, 132, 132, 130, 130, 130, 128
        .byte   128, 126, 126, 126, 124, 124, 122, 122, 122, 120, 120, 118, 118, 118, 116, 116, 116, 114, 114, 112, 112, 112, 110, 110, 108, 108, 108, 106, 106, 106, 104, 104
        .byte   104, 102, 102, 100, 100, 100, 98, 98, 98, 96, 96, 96, 94, 94, 94, 92, 92, 92, 90, 90, 90, 88, 88, 88, 86, 86, 86, 86, 84, 84, 84, 82
        .byte   82, 82, 82, 80, 80, 80, 80, 78, 78, 78, 78, 76, 76, 76, 76, 74, 74, 74, 74, 74, 72, 72, 72, 72, 72, 70, 70, 70, 70, 70, 68, 68
        .byte   68, 68, 68, 68, 68, 66, 66, 66, 66, 66, 66, 66, 66, 66, 66, 64, 64, 64, 64, 64, 64, 64, 64, 64, 64, 64, 64, 64, 64, 64, 64, 64
        .byte   64, 64, 64, 64, 64, 64, 64, 64, 64, 64, 64, 64, 64, 64, 64, 64, 64, 64, 66, 66, 66, 66, 66, 66, 66, 66, 66, 66, 68, 68, 68, 68
        .byte   68, 68, 68, 70, 70, 70, 70, 70, 72, 72, 72, 72, 72, 74, 74, 74, 74, 74, 76, 76, 76, 76, 78, 78, 78, 78, 80, 80, 80, 80, 82, 82
        .byte   82, 82, 84, 84, 84, 86, 86, 86, 86, 88, 88, 88, 90, 90, 90, 92, 92, 92, 94, 94, 94, 96, 96, 96, 98, 98, 98, 100, 100, 100, 102, 102
        .byte   104, 104, 104, 106, 106, 106, 108, 108, 108, 110, 110, 112, 112, 112, 114, 114, 116, 116, 116, 118, 118, 118, 120, 120, 122, 122, 122, 124, 124, 126, 126, 126
| amplitude 34 px
        .byte   128, 128, 130, 130, 130, 132, 132, 132, 134, 134, 136, 136, 136, 138, 138, 140, 140, 140, 142, 142, 144, 144, 146, 146, 148, 148, 148, 150, 150, 150, 152, 152
        .byte   152, 154, 154, 156, 156, 156, 158, 158, 158, 160, 162, 162, 162, 164, 164, 164, 166, 166, 166, 166, 168, 168, 168, 170, 170, 170, 172, 172, 172, 174, 174, 174
        .byte   174, 176, 176, 176, 176, 178, 178, 180, 180, 180, 180, 182, 182, 182, 182, 184, 184, 184, 184, 184, 186, 186, 186, 186, 186, 188, 188, 188, 188, 188, 190, 190
        .byte   190, 190, 190, 190, 190, 192, 192, 192, 192, 192, 192, 192, 192, 192, 192, 194, 194, 194, 194, 194, 194, 194, 194, 194, 194, 194, 194, 194, 194, 194, 194, 194
        .byte   194, 194, 194, 194, 194, 194, 194, 194, 194, 194, 194, 194, 194, 194, 194, 194, 194, 194, 192, 192, 192, 192, 192, 192, 192, 192, 192, 192, 190, 190, 190, 190
        .byte   190, 190, 190, 188, 188, 188, 188, 188, 186, 186, 186, 186, 186, 184, 184, 184, 184, 184, 182, 182, 182, 182, 180, 180, 180, 180, 178, 178, 176, 176, 176, 176
        .byte   174, 174, 174, 174, 172, 172, 172, 170, 170, 170, 168, 168, 168, 166, 166, 166, 166, 164, 164, 164, 162, 162, 162, 160, 158, 158, 158, 156, 156, 156, 154, 154
        .byte   152, 152, 152, 150, 150, 150, 148, 148, 148, 146, 146, 144, 144, 142, 142, 140, 140, 140, 138, 138, 136, 136, 136, 134, 134, 132, 132, 132, 130, 130, 130, 128
        .byte   128, 126, 124, 124, 124, 122, 122, 122, 120, 120, 118, 118, 118, 116, 116, 114, 114, 114, 112, 112, 110, 110, 108, 108, 106, 106, 106, 104, 104, 104, 102, 102
        .byte   102, 100, 100, 98, 98, 98, 96, 96, 96, 94, 94, 94, 92, 90, 90, 90, 88, 88, 88, 88, 86, 86, 86, 84, 84, 84, 82, 82, 82, 80, 80, 80
        .byte   80, 78, 78, 78, 78, 76, 76, 74, 74, 74, 74, 72, 72, 72, 72, 70, 70, 70, 70, 70, 68, 68, 68, 68, 68, 66, 66, 66, 66, 66, 64, 64
        .byte   64, 64, 64, 64, 64, 62, 62, 62, 62, 62, 62, 62, 62, 62, 62, 60, 60, 60, 60, 60, 60, 60, 60, 60, 60, 60, 60, 60, 60, 60, 60, 60
        .byte   60, 60, 60, 60, 60, 60, 60, 60, 60, 60, 60, 60, 60, 60, 60, 60, 60, 60, 62, 62, 62, 62, 62, 62, 62, 62, 62, 62, 64, 64, 64, 64
        .byte   64, 64, 64, 66, 66, 66, 66, 66, 68, 68, 68, 68, 68, 70, 70, 70, 70, 70, 72, 72, 72, 72, 74, 74, 74, 74, 76, 76, 78, 78, 78, 78
        .byte   80, 80, 80, 80, 82, 82, 82, 84, 84, 84, 86, 86, 86, 88, 88, 88, 88, 90, 90, 90, 92, 94, 94, 94, 96, 96, 96, 98, 98, 98, 100, 100
        .byte   102, 102, 102, 104, 104, 104, 106, 106, 106, 108, 108, 110, 110, 112, 112, 114, 114, 114, 116, 116, 118, 118, 118, 120, 120, 122, 122, 122, 124, 124, 124, 126
| amplitude 36 px
        .byte   128, 128, 130, 130, 130, 132, 132, 132, 134, 134, 136, 138, 138, 138, 140, 140, 140, 142, 142, 144, 146, 146, 146, 148, 148, 148, 150, 150, 152, 152, 152, 154
        .byte   154, 156, 156, 158, 158, 158, 160, 160, 160, 162, 164, 164, 164, 166, 166, 166, 168, 168, 168, 168, 170, 170, 170, 172, 174, 174, 174, 174, 176, 176, 176, 178
        .byte   178, 178, 178, 180, 180, 182, 182, 182, 182, 184, 184, 184, 184, 186, 186, 186, 186, 188, 188, 188, 188, 188, 190, 190, 190, 192, 192, 192, 192, 192, 194, 194
        .byte   194, 194, 194, 194, 194, 196, 196, 196, 196, 196, 196, 196, 196, 196, 196, 198, 198, 198, 198, 198, 198, 198, 198, 198, 198, 198, 198, 198, 198, 198, 198, 198
        .byte   198, 198, 198, 198, 198, 198, 198, 198, 198, 198, 198, 198, 198, 198, 198, 198, 198, 198, 196, 196, 196, 196, 196, 196, 196, 196, 196, 196, 194, 194, 194, 194
        .byte   194, 194, 194, 192, 192, 192, 192, 192, 190, 190, 190, 188, 188, 188, 188, 188, 186, 186, 186, 186, 184, 184, 184, 184, 182, 182, 182, 182, 180, 180, 178, 178
        .byte   178, 178, 176, 176, 176, 174, 174, 174, 174, 172, 170, 170, 170, 168, 168, 168, 168, 166, 166, 166, 164, 164, 164, 162, 160, 160, 160, 158, 158, 158, 156, 156
        .byte   154, 154, 152, 152, 152, 150, 150, 148, 148, 148, 146, 146, 146, 144, 142, 142, 140, 140, 140, 138, 138, 138, 136, 134, 134, 132, 132, 132, 130, 130, 130, 128
        .byte   128, 126, 124, 124, 124, 122, 122, 122, 120, 120, 118, 116, 116, 116, 114, 114, 114, 112, 112, 110, 110, 110, 108, 106, 106, 106, 104, 104, 102, 102, 102, 100
        .byte   100, 98, 98, 96, 96, 96, 94, 94, 94, 92, 92, 92, 90, 88, 88, 88, 86, 86, 86, 86, 84, 84, 84, 82, 80, 80, 80, 80, 78, 78, 78, 76
        .byte   76, 76, 76, 74, 74, 74, 74, 72, 72, 70, 70, 70, 70, 68, 68, 68, 68, 66, 66, 66, 66, 66, 64, 64, 64, 62, 62, 62, 62, 62, 60, 60
        .byte   60, 60, 60, 60, 60, 58, 58, 58, 58, 58, 58, 58, 58, 58, 58, 56, 56, 56, 56, 56, 56, 56, 56, 56, 56, 56, 56, 56, 56, 56, 56, 56
        .byte   56, 56, 56, 56, 56, 56, 56, 56, 56, 56, 56, 56, 56, 56, 56, 56, 56, 56, 58, 58, 58, 58, 58, 58, 58, 58, 58, 58, 60, 60, 60, 60
        .byte   60, 60, 60, 62, 62, 62, 62, 62, 64, 64, 64, 66, 66, 66, 66, 66, 68, 68, 68, 68, 70, 70, 70, 70, 72, 72, 74, 74, 74, 74, 76, 76
        .byte   76, 76, 78, 78, 78, 80, 80, 80, 80, 82, 84, 84, 84, 86, 86, 86, 86, 88, 88, 88, 90, 92, 92, 92, 94, 94, 94, 96, 96, 96, 98, 98
        .byte   100, 100, 102, 102, 102, 104, 104, 106, 106, 106, 108, 110, 110, 110, 112, 112, 114, 114, 114, 116, 116, 116, 118, 120, 120, 122, 122, 122, 124, 124, 124, 126
| amplitude 38 px
        .byte   128, 128, 130, 130, 130, 132, 132, 132, 134, 136, 136, 138, 138, 138, 140, 142, 142, 142, 144, 144, 146, 146, 148, 148, 150, 150, 150, 152, 154, 154, 154, 156
        .byte   156, 156, 158, 160, 160, 160, 162, 162, 162, 164, 166, 166, 166, 168, 168, 168, 170, 170, 170, 170, 172, 174, 174, 174, 176, 176, 176, 176, 178, 180, 180, 180
        .byte   180, 182, 182, 182, 182, 184, 184, 186, 186, 186, 186, 188, 188, 188, 188, 190, 190, 192, 192, 192, 192, 192, 194, 194, 194, 194, 194, 196, 196, 196, 198, 198
        .byte   198, 198, 198, 198, 198, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 202, 202, 202, 202, 202, 202, 202, 202, 202, 202, 202, 202, 202, 202, 202, 202, 202
        .byte   202, 202, 202, 202, 202, 202, 202, 202, 202, 202, 202, 202, 202, 202, 202, 202, 202, 202, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 198, 198, 198, 198
        .byte   198, 198, 198, 196, 196, 196, 194, 194, 194, 194, 194, 192, 192, 192, 192, 192, 190, 190, 188, 188, 188, 188, 186, 186, 186, 186, 184, 184, 182, 182, 182, 182
        .byte   180, 180, 180, 180, 178, 176, 176, 176, 176, 174, 174, 174, 172, 170, 170, 170, 170, 168, 168, 168, 166, 166, 166, 164, 162, 162, 162, 160, 160, 160, 158, 156
        .byte   156, 156, 154, 154, 154, 152, 150, 150, 150, 148, 148, 146, 146, 144, 144, 142, 142, 142, 140, 138, 138, 138, 136, 136, 134, 132, 132, 132, 130, 130, 130, 128
        .byte   128, 126, 124, 124, 124, 122, 122, 122, 120, 118, 118, 116, 116, 116, 114, 112, 112, 112, 110, 110, 108, 108, 106, 106, 104, 104, 104, 102, 100, 100, 100, 98
        .byte   98, 98, 96, 94, 94, 94, 92, 92, 92, 90, 90, 90, 88, 86, 86, 86, 84, 84, 84, 84, 82, 80, 80, 80, 78, 78, 78, 78, 76, 74, 74, 74
        .byte   74, 72, 72, 72, 72, 70, 70, 68, 68, 68, 68, 66, 66, 66, 66, 64, 64, 62, 62, 62, 62, 62, 60, 60, 60, 60, 60, 58, 58, 58, 56, 56
        .byte   56, 56, 56, 56, 56, 54, 54, 54, 54, 54, 54, 54, 54, 54, 54, 52, 52, 52, 52, 52, 52, 52, 52, 52, 52, 52, 52, 52, 52, 52, 52, 52
        .byte   52, 52, 52, 52, 52, 52, 52, 52, 52, 52, 52, 52, 52, 52, 52, 52, 52, 52, 54, 54, 54, 54, 54, 54, 54, 54, 54, 54, 56, 56, 56, 56
        .byte   56, 56, 56, 58, 58, 58, 60, 60, 60, 60, 60, 62, 62, 62, 62, 62, 64, 64, 66, 66, 66, 66, 68, 68, 68, 68, 70, 70, 72, 72, 72, 72
        .byte   74, 74, 74, 74, 76, 78, 78, 78, 78, 80, 80, 80, 82, 84, 84, 84, 84, 86, 86, 86, 88, 90, 90, 90, 92, 92, 92, 94, 94, 94, 96, 98
        .byte   98, 98, 100, 100, 100, 102, 104, 104, 104, 106, 106, 108, 108, 110, 110, 112, 112, 112, 114, 116, 116, 116, 118, 118, 120, 122, 122, 122, 124, 124, 124, 126
| amplitude 40 px
        .byte   128, 128, 130, 130, 130, 132, 134, 134, 134, 136, 138, 138, 138, 140, 140, 142, 142, 144, 144, 146, 148, 148, 148, 150, 150, 150, 152, 154, 154, 154, 156, 158
        .byte   158, 158, 160, 160, 160, 162, 164, 164, 164, 166, 168, 168, 168, 170, 170, 170, 172, 172, 174, 174, 174, 176, 176, 178, 178, 178, 180, 180, 180, 182, 182, 184
        .byte   184, 184, 184, 186, 186, 188, 188, 188, 188, 190, 190, 190, 190, 192, 192, 194, 194, 194, 194, 194, 196, 196, 198, 198, 198, 198, 198, 200, 200, 200, 200, 200
        .byte   200, 200, 202, 202, 202, 204, 204, 204, 204, 204, 204, 204, 204, 204, 204, 206, 206, 206, 206, 206, 206, 206, 206, 206, 206, 206, 206, 206, 206, 206, 206, 206
        .byte   206, 206, 206, 206, 206, 206, 206, 206, 206, 206, 206, 206, 206, 206, 206, 206, 206, 206, 204, 204, 204, 204, 204, 204, 204, 204, 204, 204, 202, 202, 202, 200
        .byte   200, 200, 200, 200, 200, 200, 198, 198, 198, 198, 198, 196, 196, 194, 194, 194, 194, 194, 192, 192, 190, 190, 190, 190, 188, 188, 188, 188, 186, 186, 184, 184
        .byte   184, 184, 182, 182, 180, 180, 180, 178, 178, 178, 176, 176, 174, 174, 174, 172, 172, 170, 170, 170, 168, 168, 168, 166, 164, 164, 164, 162, 160, 160, 160, 158
        .byte   158, 158, 156, 154, 154, 154, 152, 150, 150, 150, 148, 148, 148, 146, 144, 144, 142, 142, 140, 140, 138, 138, 138, 136, 134, 134, 134, 132, 130, 130, 130, 128
        .byte   128, 126, 124, 124, 124, 122, 120, 120, 120, 118, 118, 116, 116, 114, 114, 112, 112, 110, 110, 108, 108, 108, 106, 104, 104, 104, 102, 100, 100, 100, 98, 98
        .byte   98, 96, 94, 94, 94, 92, 90, 90, 90, 88, 88, 88, 86, 84, 84, 84, 82, 82, 80, 80, 80, 78, 78, 78, 76, 76, 74, 74, 74, 72, 72, 70
        .byte   70, 70, 70, 68, 68, 68, 68, 66, 66, 64, 64, 64, 64, 62, 62, 60, 60, 60, 60, 60, 58, 58, 58, 58, 58, 56, 56, 54, 54, 54, 54, 54
        .byte   54, 54, 52, 52, 52, 50, 50, 50, 50, 50, 50, 50, 50, 50, 50, 48, 48, 48, 48, 48, 48, 48, 48, 48, 48, 48, 48, 48, 48, 48, 48, 48
        .byte   48, 48, 48, 48, 48, 48, 48, 48, 48, 48, 48, 48, 48, 48, 48, 48, 48, 48, 50, 50, 50, 50, 50, 50, 50, 50, 50, 50, 52, 52, 52, 54
        .byte   54, 54, 54, 54, 54, 54, 56, 56, 58, 58, 58, 58, 58, 60, 60, 60, 60, 60, 62, 62, 64, 64, 64, 64, 66, 66, 68, 68, 68, 68, 70, 70
        .byte   70, 70, 72, 72, 74, 74, 74, 76, 76, 78, 78, 78, 80, 80, 80, 82, 82, 84, 84, 84, 86, 88, 88, 88, 90, 90, 90, 92, 94, 94, 94, 96
        .byte   98, 98, 98, 100, 100, 100, 102, 104, 104, 104, 106, 108, 108, 108, 110, 110, 112, 112, 114, 114, 116, 116, 118, 118, 120, 120, 120, 122, 124, 124, 124, 126
| amplitude 42 px
        .byte   128, 128, 130, 130, 130, 132, 134, 134, 134, 136, 138, 138, 138, 140, 142, 142, 142, 144, 146, 146, 148, 148, 150, 150, 152, 152, 154, 154, 156, 156, 158, 158
        .byte   158, 160, 162, 162, 162, 164, 166, 166, 166, 168, 170, 170, 170, 172, 172, 172, 174, 174, 176, 176, 176, 178, 178, 180, 180, 180, 182, 182, 184, 184, 184, 186
        .byte   186, 188, 188, 188, 188, 190, 190, 192, 192, 192, 192, 194, 194, 196, 196, 196, 196, 198, 198, 198, 200, 200, 200, 200, 200, 202, 202, 204, 204, 204, 204, 204
        .byte   204, 204, 206, 206, 206, 208, 208, 208, 208, 208, 208, 208, 208, 208, 208, 210, 210, 210, 210, 210, 210, 210, 210, 210, 210, 210, 210, 210, 210, 210, 210, 210
        .byte   210, 210, 210, 210, 210, 210, 210, 210, 210, 210, 210, 210, 210, 210, 210, 210, 210, 210, 208, 208, 208, 208, 208, 208, 208, 208, 208, 208, 206, 206, 206, 204
        .byte   204, 204, 204, 204, 204, 204, 202, 202, 200, 200, 200, 200, 200, 198, 198, 198, 196, 196, 196, 196, 194, 194, 192, 192, 192, 192, 190, 190, 188, 188, 188, 188
        .byte   186, 186, 184, 184, 184, 182, 182, 180, 180, 180, 178, 178, 176, 176, 176, 174, 174, 172, 172, 172, 170, 170, 170, 168, 166, 166, 166, 164, 162, 162, 162, 160
        .byte   158, 158, 158, 156, 156, 154, 154, 152, 152, 150, 150, 148, 148, 146, 146, 144, 142, 142, 142, 140, 138, 138, 138, 136, 134, 134, 134, 132, 130, 130, 130, 128
        .byte   128, 126, 124, 124, 124, 122, 120, 120, 120, 118, 116, 116, 116, 114, 112, 112, 112, 110, 108, 108, 106, 106, 104, 104, 102, 102, 100, 100, 98, 98, 96, 96
        .byte   96, 94, 92, 92, 92, 90, 88, 88, 88, 86, 86, 86, 84, 82, 82, 82, 80, 80, 78, 78, 78, 76, 76, 74, 74, 74, 72, 72, 70, 70, 70, 68
        .byte   68, 66, 66, 66, 66, 64, 64, 62, 62, 62, 62, 60, 60, 58, 58, 58, 58, 56, 56, 56, 54, 54, 54, 54, 54, 52, 52, 50, 50, 50, 50, 50
        .byte   50, 50, 48, 48, 48, 46, 46, 46, 46, 46, 46, 46, 46, 46, 46, 44, 44, 44, 44, 44, 44, 44, 44, 44, 44, 44, 44, 44, 44, 44, 44, 44
        .byte   44, 44, 44, 44, 44, 44, 44, 44, 44, 44, 44, 44, 44, 44, 44, 44, 44, 44, 46, 46, 46, 46, 46, 46, 46, 46, 46, 46, 48, 48, 48, 50
        .byte   50, 50, 50, 50, 50, 50, 52, 52, 54, 54, 54, 54, 54, 56, 56, 56, 58, 58, 58, 58, 60, 60, 62, 62, 62, 62, 64, 64, 66, 66, 66, 66
        .byte   68, 68, 70, 70, 70, 72, 72, 74, 74, 74, 76, 76, 78, 78, 78, 80, 80, 82, 82, 82, 84, 86, 86, 86, 88, 88, 88, 90, 92, 92, 92, 94
        .byte   96, 96, 96, 98, 98, 100, 100, 102, 102, 104, 104, 106, 106, 108, 108, 110, 112, 112, 112, 114, 116, 116, 116, 118, 120, 120, 120, 122, 124, 124, 124, 126
| amplitude 44 px
        .byte   128, 128, 130, 130, 132, 132, 134, 134, 136, 136, 138, 140, 140, 140, 142, 144, 144, 144, 146, 148, 150, 150, 150, 152, 154, 154, 154, 156, 158, 158, 158, 160
        .byte   160, 162, 162, 164, 164, 166, 166, 166, 168, 170, 172, 172, 172, 174, 174, 176, 176, 176, 178, 178, 180, 180, 180, 182, 184, 184, 184, 184, 186, 188, 188, 188
        .byte   188, 190, 190, 192, 192, 194, 194, 194, 194, 196, 196, 198, 198, 198, 198, 200, 200, 202, 202, 202, 202, 202, 204, 204, 204, 206, 206, 206, 206, 206, 208, 208
        .byte   208, 208, 210, 210, 210, 210, 210, 210, 210, 210, 212, 212, 212, 212, 212, 214, 214, 214, 214, 214, 214, 214, 214, 214, 214, 214, 214, 214, 214, 214, 214, 214
        .byte   214, 214, 214, 214, 214, 214, 214, 214, 214, 214, 214, 214, 214, 214, 214, 214, 214, 214, 212, 212, 212, 212, 212, 210, 210, 210, 210, 210, 210, 210, 210, 208
        .byte   208, 208, 208, 206, 206, 206, 206, 206, 204, 204, 204, 202, 202, 202, 202, 202, 200, 200, 198, 198, 198, 198, 196, 196, 194, 194, 194, 194, 192, 192, 190, 190
        .byte   188, 188, 188, 188, 186, 184, 184, 184, 184, 182, 180, 180, 180, 178, 178, 176, 176, 176, 174, 174, 172, 172, 172, 170, 168, 166, 166, 166, 164, 164, 162, 162
        .byte   160, 160, 158, 158, 158, 156, 154, 154, 154, 152, 150, 150, 150, 148, 146, 144, 144, 144, 142, 140, 140, 140, 138, 136, 136, 134, 134, 132, 132, 130, 130, 128
        .byte   128, 126, 124, 124, 122, 122, 120, 120, 118, 118, 116, 114, 114, 114, 112, 110, 110, 110, 108, 106, 106, 106, 104, 102, 100, 100, 100, 98, 96, 96, 96, 94
        .byte   94, 92, 92, 90, 90, 88, 88, 88, 86, 84, 84, 84, 82, 80, 80, 78, 78, 78, 76, 76, 74, 74, 74, 72, 70, 70, 70, 70, 68, 66, 66, 66
        .byte   66, 64, 64, 62, 62, 62, 62, 60, 60, 58, 58, 56, 56, 56, 56, 54, 54, 52, 52, 52, 52, 52, 50, 50, 50, 48, 48, 48, 48, 48, 46, 46
        .byte   46, 46, 44, 44, 44, 44, 44, 44, 44, 44, 42, 42, 42, 42, 42, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40
        .byte   40, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40, 42, 42, 42, 42, 42, 44, 44, 44, 44, 44, 44, 44, 44, 46
        .byte   46, 46, 46, 48, 48, 48, 48, 48, 50, 50, 50, 52, 52, 52, 52, 52, 54, 54, 56, 56, 56, 56, 58, 58, 60, 60, 62, 62, 62, 62, 64, 64
        .byte   66, 66, 66, 66, 68, 70, 70, 70, 70, 72, 74, 74, 74, 76, 76, 78, 78, 78, 80, 80, 82, 84, 84, 84, 86, 88, 88, 88, 90, 90, 92, 92
        .byte   94, 94, 96, 96, 96, 98, 100, 100, 100, 102, 104, 106, 106, 106, 108, 110, 110, 110, 112, 114, 114, 114, 116, 118, 118, 120, 120, 122, 122, 124, 124, 126
| amplitude 46 px
        .byte   128, 128, 130, 130, 132, 132, 134, 134, 136, 138, 138, 140, 140, 142, 142, 144, 144, 146, 148, 148, 150, 150, 152, 152, 154, 154, 156, 158, 158, 158, 160, 162
        .byte   162, 162, 164, 166, 166, 168, 168, 168, 170, 172, 174, 174, 174, 176, 176, 178, 178, 178, 180, 180, 182, 184, 184, 184, 186, 186, 188, 188, 188, 190, 190, 192
        .byte   192, 194, 194, 194, 194, 196, 196, 198, 198, 198, 198, 200, 200, 202, 202, 204, 204, 204, 204, 204, 206, 206, 208, 208, 208, 208, 208, 210, 210, 210, 212, 212
        .byte   212, 212, 214, 214, 214, 214, 214, 214, 214, 214, 216, 216, 216, 216, 216, 218, 218, 218, 218, 218, 218, 218, 218, 218, 218, 218, 218, 218, 218, 218, 218, 218
        .byte   218, 218, 218, 218, 218, 218, 218, 218, 218, 218, 218, 218, 218, 218, 218, 218, 218, 218, 216, 216, 216, 216, 216, 214, 214, 214, 214, 214, 214, 214, 214, 212
        .byte   212, 212, 212, 210, 210, 210, 208, 208, 208, 208, 208, 206, 206, 204, 204, 204, 204, 204, 202, 202, 200, 200, 198, 198, 198, 198, 196, 196, 194, 194, 194, 194
        .byte   192, 192, 190, 190, 188, 188, 188, 186, 186, 184, 184, 184, 182, 180, 180, 178, 178, 178, 176, 176, 174, 174, 174, 172, 170, 168, 168, 168, 166, 166, 164, 162
        .byte   162, 162, 160, 158, 158, 158, 156, 154, 154, 152, 152, 150, 150, 148, 148, 146, 144, 144, 142, 142, 140, 140, 138, 138, 136, 134, 134, 132, 132, 130, 130, 128
        .byte   128, 126, 124, 124, 122, 122, 120, 120, 118, 116, 116, 114, 114, 112, 112, 110, 110, 108, 106, 106, 104, 104, 102, 102, 100, 100, 98, 96, 96, 96, 94, 92
        .byte   92, 92, 90, 88, 88, 86, 86, 86, 84, 82, 82, 82, 80, 78, 78, 76, 76, 76, 74, 74, 72, 70, 70, 70, 68, 68, 66, 66, 66, 64, 64, 62
        .byte   62, 60, 60, 60, 60, 58, 58, 56, 56, 56, 56, 54, 54, 52, 52, 50, 50, 50, 50, 50, 48, 48, 46, 46, 46, 46, 46, 44, 44, 44, 42, 42
        .byte   42, 42, 40, 40, 40, 40, 40, 40, 40, 40, 38, 38, 38, 38, 38, 36, 36, 36, 36, 36, 36, 36, 36, 36, 36, 36, 36, 36, 36, 36, 36, 36
        .byte   36, 36, 36, 36, 36, 36, 36, 36, 36, 36, 36, 36, 36, 36, 36, 36, 36, 36, 38, 38, 38, 38, 38, 40, 40, 40, 40, 40, 40, 40, 40, 42
        .byte   42, 42, 42, 44, 44, 44, 46, 46, 46, 46, 46, 48, 48, 50, 50, 50, 50, 50, 52, 52, 54, 54, 56, 56, 56, 56, 58, 58, 60, 60, 60, 60
        .byte   62, 62, 64, 64, 66, 66, 66, 68, 68, 70, 70, 70, 72, 74, 74, 76, 76, 76, 78, 78, 80, 82, 82, 82, 84, 86, 86, 86, 88, 88, 90, 92
        .byte   92, 92, 94, 96, 96, 96, 98, 100, 100, 102, 102, 104, 104, 106, 106, 108, 110, 110, 112, 112, 114, 114, 116, 116, 118, 120, 120, 122, 122, 124, 124, 126
| amplitude 48 px
        .byte   128, 128, 130, 130, 132, 134, 134, 134, 136, 138, 140, 140, 140, 142, 144, 146, 146, 146, 148, 150, 152, 152, 152, 154, 156, 156, 158, 158, 160, 160, 162, 164
        .byte   164, 164, 166, 168, 168, 170, 170, 170, 172, 174, 176, 176, 176, 178, 178, 180, 182, 182, 182, 182, 184, 186, 186, 188, 188, 188, 190, 190, 192, 194, 194, 194
        .byte   194, 196, 196, 198, 198, 200, 200, 200, 200, 202, 202, 204, 204, 206, 206, 206, 206, 208, 208, 208, 210, 210, 212, 212, 212, 212, 212, 214, 214, 214, 216, 216
        .byte   216, 216, 218, 218, 218, 218, 218, 218, 218, 218, 220, 220, 220, 220, 220, 222, 222, 222, 222, 222, 222, 222, 222, 222, 222, 222, 222, 222, 222, 222, 222, 222
        .byte   222, 222, 222, 222, 222, 222, 222, 222, 222, 222, 222, 222, 222, 222, 222, 222, 222, 222, 220, 220, 220, 220, 220, 218, 218, 218, 218, 218, 218, 218, 218, 216
        .byte   216, 216, 216, 214, 214, 214, 212, 212, 212, 212, 212, 210, 210, 208, 208, 208, 206, 206, 206, 206, 204, 204, 202, 202, 200, 200, 200, 200, 198, 198, 196, 196
        .byte   194, 194, 194, 194, 192, 190, 190, 188, 188, 188, 186, 186, 184, 182, 182, 182, 182, 180, 178, 178, 176, 176, 176, 174, 172, 170, 170, 170, 168, 168, 166, 164
        .byte   164, 164, 162, 160, 160, 158, 158, 156, 156, 154, 152, 152, 152, 150, 148, 146, 146, 146, 144, 142, 140, 140, 140, 138, 136, 134, 134, 134, 132, 130, 130, 128
        .byte   128, 126, 124, 124, 122, 122, 120, 120, 118, 116, 116, 114, 114, 112, 110, 110, 110, 108, 106, 104, 104, 104, 102, 100, 98, 98, 98, 96, 94, 94, 92, 92
        .byte   92, 90, 88, 86, 86, 86, 84, 84, 82, 80, 80, 80, 78, 76, 76, 74, 74, 74, 72, 72, 70, 68, 68, 68, 66, 66, 64, 64, 62, 62, 62, 60
        .byte   60, 58, 58, 56, 56, 56, 56, 54, 54, 52, 52, 50, 50, 50, 50, 48, 48, 46, 46, 46, 44, 44, 44, 44, 44, 42, 42, 40, 40, 40, 38, 38
        .byte   38, 38, 38, 38, 38, 36, 36, 36, 36, 36, 34, 34, 34, 34, 34, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32
        .byte   32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 32, 34, 34, 34, 34, 34, 36, 36, 36, 36, 36, 38, 38, 38, 38
        .byte   38, 38, 38, 40, 40, 40, 42, 42, 44, 44, 44, 44, 44, 46, 46, 46, 48, 48, 50, 50, 50, 50, 52, 52, 54, 54, 56, 56, 56, 56, 58, 58
        .byte   60, 60, 62, 62, 62, 64, 64, 66, 66, 68, 68, 68, 70, 72, 72, 74, 74, 74, 76, 76, 78, 80, 80, 80, 82, 84, 84, 86, 86, 86, 88, 90
        .byte   92, 92, 92, 94, 94, 96, 98, 98, 98, 100, 102, 104, 104, 104, 106, 108, 110, 110, 110, 112, 114, 114, 116, 116, 118, 120, 120, 122, 122, 124, 124, 126
| amplitude 50 px
        .byte   128, 128, 130, 130, 132, 134, 134, 134, 136, 138, 140, 142, 142, 142, 144, 146, 146, 148, 148, 150, 152, 152, 154, 156, 156, 156, 158, 160, 162, 162, 162, 164
        .byte   164, 166, 168, 170, 170, 170, 172, 172, 174, 176, 178, 178, 178, 180, 180, 182, 184, 184, 184, 184, 186, 188, 188, 190, 192, 192, 192, 192, 194, 196, 196, 198
        .byte   198, 198, 198, 200, 200, 202, 202, 204, 204, 206, 206, 206, 206, 208, 208, 210, 210, 212, 212, 212, 212, 212, 214, 214, 214, 216, 216, 218, 218, 218, 220, 220
        .byte   220, 220, 220, 220, 220, 222, 222, 222, 222, 222, 224, 224, 224, 224, 224, 226, 226, 226, 226, 226, 226, 226, 226, 226, 226, 226, 226, 226, 226, 226, 226, 226
        .byte   226, 226, 226, 226, 226, 226, 226, 226, 226, 226, 226, 226, 226, 226, 226, 226, 226, 226, 224, 224, 224, 224, 224, 222, 222, 222, 222, 222, 220, 220, 220, 220
        .byte   220, 220, 220, 218, 218, 218, 216, 216, 214, 214, 214, 212, 212, 212, 212, 212, 210, 210, 208, 208, 206, 206, 206, 206, 204, 204, 202, 202, 200, 200, 198, 198
        .byte   198, 198, 196, 196, 194, 192, 192, 192, 192, 190, 188, 188, 186, 184, 184, 184, 184, 182, 180, 180, 178, 178, 178, 176, 174, 172, 172, 170, 170, 170, 168, 166
        .byte   164, 164, 162, 162, 162, 160, 158, 156, 156, 156, 154, 152, 152, 150, 148, 148, 146, 146, 144, 142, 142, 142, 140, 138, 136, 134, 134, 134, 132, 130, 130, 128
        .byte   128, 126, 124, 124, 122, 120, 120, 120, 118, 116, 114, 112, 112, 112, 110, 108, 108, 106, 106, 104, 102, 102, 100, 98, 98, 98, 96, 94, 92, 92, 92, 90
        .byte   90, 88, 86, 84, 84, 84, 82, 82, 80, 78, 78, 78, 76, 74, 74, 72, 70, 70, 70, 70, 68, 66, 66, 64, 62, 62, 62, 62, 60, 58, 58, 56
        .byte   56, 56, 56, 54, 54, 52, 52, 50, 50, 48, 48, 48, 48, 46, 46, 44, 44, 42, 42, 42, 42, 42, 40, 40, 40, 38, 38, 36, 36, 36, 34, 34
        .byte   34, 34, 34, 34, 34, 32, 32, 32, 32, 32, 30, 30, 30, 30, 30, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28
        .byte   28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 30, 30, 30, 30, 30, 32, 32, 32, 32, 32, 34, 34, 34, 34
        .byte   34, 34, 34, 36, 36, 36, 38, 38, 40, 40, 40, 42, 42, 42, 42, 42, 44, 44, 46, 46, 48, 48, 48, 48, 50, 50, 52, 52, 54, 54, 56, 56
        .byte   56, 56, 58, 58, 60, 62, 62, 62, 62, 64, 66, 66, 68, 70, 70, 70, 70, 72, 74, 74, 76, 78, 78, 78, 80, 82, 82, 84, 84, 84, 86, 88
        .byte   90, 90, 92, 92, 92, 94, 96, 98, 98, 98, 100, 102, 102, 104, 106, 106, 108, 108, 110, 112, 112, 112, 114, 116, 118, 120, 120, 120, 122, 124, 124, 126
| amplitude 52 px
        .byte   128, 128, 130, 130, 132, 134, 136, 136, 136, 138, 140, 142, 142, 144, 144, 146, 146, 148, 150, 152, 154, 154, 154, 156, 158, 158, 160, 162, 162, 162, 164, 166
        .byte   166, 168, 170, 170, 170, 172, 174, 174, 176, 178, 180, 180, 180, 182, 182, 184, 186, 186, 188, 188, 188, 190, 190, 192, 194, 194, 196, 196, 196, 198, 198, 200
        .byte   200, 202, 202, 204, 204, 206, 206, 206, 206, 208, 208, 210, 210, 212, 212, 214, 214, 214, 214, 214, 216, 216, 218, 218, 218, 220, 220, 222, 222, 222, 222, 222
        .byte   222, 222, 224, 224, 224, 226, 226, 226, 226, 226, 228, 228, 228, 228, 228, 230, 230, 230, 230, 230, 230, 230, 230, 230, 230, 230, 230, 230, 230, 230, 230, 230
        .byte   230, 230, 230, 230, 230, 230, 230, 230, 230, 230, 230, 230, 230, 230, 230, 230, 230, 230, 228, 228, 228, 228, 228, 226, 226, 226, 226, 226, 224, 224, 224, 222
        .byte   222, 222, 222, 222, 222, 222, 220, 220, 218, 218, 218, 216, 216, 214, 214, 214, 214, 214, 212, 212, 210, 210, 208, 208, 206, 206, 206, 206, 204, 204, 202, 202
        .byte   200, 200, 198, 198, 196, 196, 196, 194, 194, 192, 190, 190, 188, 188, 188, 186, 186, 184, 182, 182, 180, 180, 180, 178, 176, 174, 174, 172, 170, 170, 170, 168
        .byte   166, 166, 164, 162, 162, 162, 160, 158, 158, 156, 154, 154, 154, 152, 150, 148, 146, 146, 144, 144, 142, 142, 140, 138, 136, 136, 136, 134, 132, 130, 130, 128
        .byte   128, 126, 124, 124, 122, 120, 118, 118, 118, 116, 114, 112, 112, 110, 110, 108, 108, 106, 104, 102, 102, 102, 100, 98, 96, 96, 94, 92, 92, 92, 90, 88
        .byte   88, 86, 84, 84, 84, 82, 80, 80, 78, 76, 76, 76, 74, 72, 72, 70, 68, 68, 66, 66, 66, 64, 64, 62, 60, 60, 58, 58, 58, 56, 56, 54
        .byte   54, 52, 52, 50, 50, 50, 50, 48, 48, 46, 46, 44, 44, 42, 42, 40, 40, 40, 40, 40, 38, 38, 36, 36, 36, 34, 34, 32, 32, 32, 32, 32
        .byte   32, 32, 30, 30, 30, 28, 28, 28, 28, 28, 26, 26, 26, 26, 26, 24, 24, 24, 24, 24, 24, 24, 24, 24, 24, 24, 24, 24, 24, 24, 24, 24
        .byte   24, 24, 24, 24, 24, 24, 24, 24, 24, 24, 24, 24, 24, 24, 24, 24, 24, 24, 26, 26, 26, 26, 26, 28, 28, 28, 28, 28, 30, 30, 30, 32
        .byte   32, 32, 32, 32, 32, 32, 34, 34, 36, 36, 36, 38, 38, 40, 40, 40, 40, 40, 42, 42, 44, 44, 46, 46, 48, 48, 50, 50, 50, 50, 52, 52
        .byte   54, 54, 56, 56, 58, 58, 58, 60, 60, 62, 64, 64, 66, 66, 66, 68, 68, 70, 72, 72, 74, 76, 76, 76, 78, 80, 80, 82, 84, 84, 84, 86
        .byte   88, 88, 90, 92, 92, 92, 94, 96, 96, 98, 100, 102, 102, 102, 104, 106, 108, 108, 110, 110, 112, 112, 114, 116, 118, 118, 118, 120, 122, 124, 124, 126
| amplitude 54 px
        .byte   128, 128, 130, 130, 132, 134, 136, 136, 138, 138, 140, 142, 142, 144, 146, 148, 148, 148, 150, 152, 154, 154, 156, 158, 160, 160, 160, 162, 164, 164, 166, 168
        .byte   168, 170, 170, 172, 172, 174, 176, 176, 178, 180, 182, 182, 182, 184, 184, 186, 188, 188, 190, 190, 192, 192, 192, 194, 196, 196, 198, 198, 200, 202, 202, 202
        .byte   202, 204, 204, 206, 206, 208, 208, 210, 210, 212, 212, 214, 214, 214, 214, 216, 216, 218, 218, 218, 220, 220, 222, 222, 222, 224, 224, 224, 224, 224, 226, 226
        .byte   226, 226, 228, 228, 228, 230, 230, 230, 230, 230, 232, 232, 232, 232, 232, 234, 234, 234, 234, 234, 234, 234, 234, 234, 234, 234, 234, 234, 234, 234, 234, 234
        .byte   234, 234, 234, 234, 234, 234, 234, 234, 234, 234, 234, 234, 234, 234, 234, 234, 234, 234, 232, 232, 232, 232, 232, 230, 230, 230, 230, 230, 228, 228, 228, 226
        .byte   226, 226, 226, 224, 224, 224, 224, 224, 222, 222, 222, 220, 220, 218, 218, 218, 216, 216, 214, 214, 214, 214, 212, 212, 210, 210, 208, 208, 206, 206, 204, 204
        .byte   202, 202, 202, 202, 200, 198, 198, 196, 196, 194, 192, 192, 192, 190, 190, 188, 188, 186, 184, 184, 182, 182, 182, 180, 178, 176, 176, 174, 172, 172, 170, 170
        .byte   168, 168, 166, 164, 164, 162, 160, 160, 160, 158, 156, 154, 154, 152, 150, 148, 148, 148, 146, 144, 142, 142, 140, 138, 138, 136, 136, 134, 132, 130, 130, 128
        .byte   128, 126, 124, 124, 122, 120, 118, 118, 116, 116, 114, 112, 112, 110, 108, 106, 106, 106, 104, 102, 100, 100, 98, 96, 94, 94, 94, 92, 90, 90, 88, 86
        .byte   86, 84, 84, 82, 82, 80, 78, 78, 76, 74, 74, 74, 72, 70, 70, 68, 66, 66, 64, 64, 62, 62, 62, 60, 58, 58, 56, 56, 54, 52, 52, 52
        .byte   52, 50, 50, 48, 48, 46, 46, 44, 44, 42, 42, 40, 40, 40, 40, 38, 38, 36, 36, 36, 34, 34, 32, 32, 32, 30, 30, 30, 30, 30, 28, 28
        .byte   28, 28, 26, 26, 26, 24, 24, 24, 24, 24, 22, 22, 22, 22, 22, 20, 20, 20, 20, 20, 20, 20, 20, 20, 20, 20, 20, 20, 20, 20, 20, 20
        .byte   20, 20, 20, 20, 20, 20, 20, 20, 20, 20, 20, 20, 20, 20, 20, 20, 20, 20, 22, 22, 22, 22, 22, 24, 24, 24, 24, 24, 26, 26, 26, 28
        .byte   28, 28, 28, 30, 30, 30, 30, 30, 32, 32, 32, 34, 34, 36, 36, 36, 38, 38, 40, 40, 40, 40, 42, 42, 44, 44, 46, 46, 48, 48, 50, 50
        .byte   52, 52, 52, 52, 54, 56, 56, 58, 58, 60, 62, 62, 62, 64, 64, 66, 66, 68, 70, 70, 72, 74, 74, 74, 76, 78, 78, 80, 82, 82, 84, 84
        .byte   86, 86, 88, 90, 90, 92, 94, 94, 94, 96, 98, 100, 100, 102, 104, 106, 106, 106, 108, 110, 112, 112, 114, 116, 116, 118, 118, 120, 122, 124, 124, 126
| amplitude 56 px
        .byte   128, 128, 130, 130, 132, 134, 136, 136, 138, 140, 142, 142, 142, 144, 146, 148, 148, 150, 152, 154, 156, 156, 156, 158, 160, 160, 162, 164, 166, 166, 168, 170
        .byte   170, 170, 172, 174, 174, 176, 178, 178, 180, 182, 184, 184, 184, 186, 186, 188, 190, 190, 192, 192, 194, 196, 196, 198, 198, 198, 200, 200, 202, 204, 204, 206
        .byte   206, 208, 208, 210, 210, 212, 212, 212, 212, 214, 214, 216, 216, 218, 218, 220, 220, 222, 222, 222, 224, 224, 226, 226, 226, 226, 226, 228, 228, 228, 230, 230
        .byte   230, 230, 232, 232, 232, 234, 234, 234, 234, 234, 236, 236, 236, 236, 236, 238, 238, 238, 238, 238, 238, 238, 238, 238, 238, 238, 238, 238, 238, 238, 238, 238
        .byte   238, 238, 238, 238, 238, 238, 238, 238, 238, 238, 238, 238, 238, 238, 238, 238, 238, 238, 236, 236, 236, 236, 236, 234, 234, 234, 234, 234, 232, 232, 232, 230
        .byte   230, 230, 230, 228, 228, 228, 226, 226, 226, 226, 226, 224, 224, 222, 222, 222, 220, 220, 218, 218, 216, 216, 214, 214, 212, 212, 212, 212, 210, 210, 208, 208
        .byte   206, 206, 204, 204, 202, 200, 200, 198, 198, 198, 196, 196, 194, 192, 192, 190, 190, 188, 186, 186, 184, 184, 184, 182, 180, 178, 178, 176, 174, 174, 172, 170
        .byte   170, 170, 168, 166, 166, 164, 162, 160, 160, 158, 156, 156, 156, 154, 152, 150, 148, 148, 146, 144, 142, 142, 142, 140, 138, 136, 136, 134, 132, 130, 130, 128
        .byte   128, 126, 124, 124, 122, 120, 118, 118, 116, 114, 114, 112, 112, 110, 108, 106, 106, 104, 102, 100, 100, 100, 98, 96, 94, 94, 92, 90, 88, 88, 86, 86
        .byte   86, 84, 82, 80, 80, 78, 76, 76, 74, 72, 72, 72, 70, 68, 68, 66, 64, 64, 62, 62, 60, 58, 58, 58, 56, 56, 54, 54, 52, 50, 50, 48
        .byte   48, 46, 46, 44, 44, 44, 44, 42, 42, 40, 40, 38, 38, 36, 36, 34, 34, 32, 32, 32, 30, 30, 30, 30, 30, 28, 28, 26, 26, 26, 24, 24
        .byte   24, 24, 22, 22, 22, 20, 20, 20, 20, 20, 18, 18, 18, 18, 18, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16
        .byte   16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 16, 18, 18, 18, 18, 18, 20, 20, 20, 20, 20, 22, 22, 22, 24
        .byte   24, 24, 24, 26, 26, 26, 28, 28, 30, 30, 30, 30, 30, 32, 32, 32, 34, 34, 36, 36, 38, 38, 40, 40, 42, 42, 44, 44, 44, 44, 46, 46
        .byte   48, 48, 50, 50, 52, 54, 54, 56, 56, 58, 58, 58, 60, 62, 62, 64, 64, 66, 68, 68, 70, 72, 72, 72, 74, 76, 76, 78, 80, 80, 82, 84
        .byte   86, 86, 86, 88, 88, 90, 92, 94, 94, 96, 98, 100, 100, 100, 102, 104, 106, 106, 108, 110, 112, 112, 114, 114, 116, 118, 118, 120, 122, 124, 124, 126
| amplitude 58 px
        .byte   128, 128, 130, 130, 132, 134, 136, 136, 138, 140, 142, 144, 144, 146, 146, 148, 148, 150, 152, 154, 156, 156, 158, 160, 162, 162, 164, 166, 166, 166, 168, 170
        .byte   170, 172, 174, 176, 176, 178, 180, 180, 182, 184, 186, 186, 186, 188, 188, 190, 192, 192, 194, 194, 196, 198, 198, 200, 202, 202, 204, 204, 204, 206, 206, 208
        .byte   208, 210, 210, 212, 212, 214, 214, 216, 216, 218, 218, 220, 220, 222, 222, 224, 224, 224, 224, 224, 226, 226, 228, 228, 228, 230, 230, 232, 232, 232, 234, 234
        .byte   234, 234, 236, 236, 236, 238, 238, 238, 238, 238, 240, 240, 240, 240, 240, 242, 242, 242, 242, 242, 242, 242, 242, 242, 242, 242, 242, 242, 242, 242, 242, 242
        .byte   242, 242, 242, 242, 242, 242, 242, 242, 242, 242, 242, 242, 242, 242, 242, 242, 242, 242, 240, 240, 240, 240, 240, 238, 238, 238, 238, 238, 236, 236, 236, 234
        .byte   234, 234, 234, 232, 232, 232, 230, 230, 228, 228, 228, 226, 226, 224, 224, 224, 224, 224, 222, 222, 220, 220, 218, 218, 216, 216, 214, 214, 212, 212, 210, 210
        .byte   208, 208, 206, 206, 204, 204, 204, 202, 202, 200, 198, 198, 196, 194, 194, 192, 192, 190, 188, 188, 186, 186, 186, 184, 182, 180, 180, 178, 176, 176, 174, 172
        .byte   170, 170, 168, 166, 166, 166, 164, 162, 162, 160, 158, 156, 156, 154, 152, 150, 148, 148, 146, 146, 144, 144, 142, 140, 138, 136, 136, 134, 132, 130, 130, 128
        .byte   128, 126, 124, 124, 122, 120, 118, 118, 116, 114, 112, 110, 110, 108, 108, 106, 106, 104, 102, 100, 98, 98, 96, 94, 92, 92, 90, 88, 88, 88, 86, 84
        .byte   84, 82, 80, 78, 78, 76, 74, 74, 72, 70, 70, 70, 68, 66, 66, 64, 62, 62, 60, 60, 58, 56, 56, 54, 52, 52, 50, 50, 50, 48, 48, 46
        .byte   46, 44, 44, 42, 42, 40, 40, 38, 38, 36, 36, 34, 34, 32, 32, 30, 30, 30, 30, 30, 28, 28, 26, 26, 26, 24, 24, 22, 22, 22, 20, 20
        .byte   20, 20, 18, 18, 18, 16, 16, 16, 16, 16, 14, 14, 14, 14, 14, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12
        .byte   12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 14, 14, 14, 14, 14, 16, 16, 16, 16, 16, 18, 18, 18, 20
        .byte   20, 20, 20, 22, 22, 22, 24, 24, 26, 26, 26, 28, 28, 30, 30, 30, 30, 30, 32, 32, 34, 34, 36, 36, 38, 38, 40, 40, 42, 42, 44, 44
        .byte   46, 46, 48, 48, 50, 50, 50, 52, 52, 54, 56, 56, 58, 60, 60, 62, 62, 64, 66, 66, 68, 70, 70, 70, 72, 74, 74, 76, 78, 78, 80, 82
        .byte   84, 84, 86, 88, 88, 88, 90, 92, 92, 94, 96, 98, 98, 100, 102, 104, 106, 106, 108, 108, 110, 110, 112, 114, 116, 118, 118, 120, 122, 124, 124, 126
| amplitude 60 px
        .byte   128, 128, 130, 130, 132, 134, 136, 136, 138, 140, 142, 144, 144, 146, 148, 150, 150, 152, 154, 156, 158, 158, 158, 160, 162, 162, 164, 166, 168, 168, 170, 172
        .byte   172, 174, 176, 178, 178, 180, 182, 182, 184, 186, 188, 188, 188, 190, 190, 192, 194, 194, 196, 196, 198, 200, 200, 202, 204, 204, 206, 206, 208, 210, 210, 212
        .byte   212, 214, 214, 216, 216, 218, 218, 218, 218, 220, 220, 222, 222, 224, 224, 226, 226, 228, 228, 228, 230, 230, 232, 232, 232, 234, 234, 236, 236, 236, 238, 238
        .byte   238, 238, 240, 240, 240, 242, 242, 242, 242, 242, 244, 244, 244, 244, 244, 246, 246, 246, 246, 246, 246, 246, 246, 246, 246, 246, 246, 246, 246, 246, 246, 246
        .byte   246, 246, 246, 246, 246, 246, 246, 246, 246, 246, 246, 246, 246, 246, 246, 246, 246, 246, 244, 244, 244, 244, 244, 242, 242, 242, 242, 242, 240, 240, 240, 238
        .byte   238, 238, 238, 236, 236, 236, 234, 234, 232, 232, 232, 230, 230, 228, 228, 228, 226, 226, 224, 224, 222, 222, 220, 220, 218, 218, 218, 218, 216, 216, 214, 214
        .byte   212, 212, 210, 210, 208, 206, 206, 204, 204, 202, 200, 200, 198, 196, 196, 194, 194, 192, 190, 190, 188, 188, 188, 186, 184, 182, 182, 180, 178, 178, 176, 174
        .byte   172, 172, 170, 168, 168, 166, 164, 162, 162, 160, 158, 158, 158, 156, 154, 152, 150, 150, 148, 146, 144, 144, 142, 140, 138, 136, 136, 134, 132, 130, 130, 128
        .byte   128, 126, 124, 124, 122, 120, 118, 118, 116, 114, 112, 110, 110, 108, 106, 104, 104, 102, 100, 98, 98, 98, 96, 94, 92, 92, 90, 88, 86, 86, 84, 82
        .byte   82, 80, 78, 76, 76, 74, 72, 72, 70, 68, 68, 68, 66, 64, 64, 62, 60, 60, 58, 58, 56, 54, 54, 52, 50, 50, 48, 48, 46, 44, 44, 42
        .byte   42, 40, 40, 38, 38, 38, 38, 36, 36, 34, 34, 32, 32, 30, 30, 28, 28, 26, 26, 26, 24, 24, 22, 22, 22, 20, 20, 18, 18, 18, 16, 16
        .byte   16, 16, 14, 14, 14, 12, 12, 12, 12, 12, 10, 10, 10, 10, 10, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8
        .byte   8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 10, 10, 10, 10, 10, 12, 12, 12, 12, 12, 14, 14, 14, 16
        .byte   16, 16, 16, 18, 18, 18, 20, 20, 22, 22, 22, 24, 24, 26, 26, 26, 28, 28, 30, 30, 32, 32, 34, 34, 36, 36, 38, 38, 38, 38, 40, 40
        .byte   42, 42, 44, 44, 46, 48, 48, 50, 50, 52, 54, 54, 56, 58, 58, 60, 60, 62, 64, 64, 66, 68, 68, 68, 70, 72, 72, 74, 76, 76, 78, 80
        .byte   82, 82, 84, 86, 86, 88, 90, 92, 92, 94, 96, 98, 98, 98, 100, 102, 104, 104, 106, 108, 110, 110, 112, 114, 116, 118, 118, 120, 122, 124, 124, 126
| amplitude 62 px
        .byte   128, 128, 130, 130, 132, 134, 136, 136, 138, 140, 142, 144, 144, 146, 148, 150, 150, 152, 154, 156, 158, 158, 160, 162, 164, 164, 166, 168, 170, 170, 172, 174
        .byte   174, 176, 178, 180, 180, 182, 184, 184, 186, 188, 190, 190, 190, 192, 192, 194, 196, 196, 198, 198, 200, 202, 202, 204, 206, 206, 208, 208, 210, 212, 212, 214
        .byte   214, 216, 216, 218, 218, 220, 220, 222, 222, 224, 224, 226, 226, 228, 228, 230, 230, 232, 232, 232, 234, 234, 236, 236, 236, 238, 238, 240, 240, 240, 242, 242
        .byte   242, 242, 244, 244, 244, 246, 246, 246, 246, 246, 248, 248, 248, 248, 248, 250, 250, 250, 250, 250, 250, 250, 250, 250, 250, 250, 250, 250, 250, 250, 250, 250
        .byte   250, 250, 250, 250, 250, 250, 250, 250, 250, 250, 250, 250, 250, 250, 250, 250, 250, 250, 248, 248, 248, 248, 248, 246, 246, 246, 246, 246, 244, 244, 244, 242
        .byte   242, 242, 242, 240, 240, 240, 238, 238, 236, 236, 236, 234, 234, 232, 232, 232, 230, 230, 228, 228, 226, 226, 224, 224, 222, 222, 220, 220, 218, 218, 216, 216
        .byte   214, 214, 212, 212, 210, 208, 208, 206, 206, 204, 202, 202, 200, 198, 198, 196, 196, 194, 192, 192, 190, 190, 190, 188, 186, 184, 184, 182, 180, 180, 178, 176
        .byte   174, 174, 172, 170, 170, 168, 166, 164, 164, 162, 160, 158, 158, 156, 154, 152, 150, 150, 148, 146, 144, 144, 142, 140, 138, 136, 136, 134, 132, 130, 130, 128
        .byte   128, 126, 124, 124, 122, 120, 118, 118, 116, 114, 112, 110, 110, 108, 106, 104, 104, 102, 100, 98, 96, 96, 94, 92, 90, 90, 88, 86, 84, 84, 82, 80
        .byte   80, 78, 76, 74, 74, 72, 70, 70, 68, 66, 66, 66, 64, 62, 62, 60, 58, 58, 56, 56, 54, 52, 52, 50, 48, 48, 46, 46, 44, 42, 42, 40
        .byte   40, 38, 38, 36, 36, 34, 34, 32, 32, 30, 30, 28, 28, 26, 26, 24, 24, 22, 22, 22, 20, 20, 18, 18, 18, 16, 16, 14, 14, 14, 12, 12
        .byte   12, 12, 10, 10, 10, 8, 8, 8, 8, 8, 6, 6, 6, 6, 6, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4
        .byte   4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 6, 6, 6, 6, 6, 8, 8, 8, 8, 8, 10, 10, 10, 12
        .byte   12, 12, 12, 14, 14, 14, 16, 16, 18, 18, 18, 20, 20, 22, 22, 22, 24, 24, 26, 26, 28, 28, 30, 30, 32, 32, 34, 34, 36, 36, 38, 38
        .byte   40, 40, 42, 42, 44, 46, 46, 48, 48, 50, 52, 52, 54, 56, 56, 58, 58, 60, 62, 62, 64, 66, 66, 66, 68, 70, 70, 72, 74, 74, 76, 78
        .byte   80, 80, 82, 84, 84, 86, 88, 90, 90, 92, 94, 96, 96, 98, 100, 102, 104, 104, 106, 108, 110, 110, 112, 114, 116, 118, 118, 120, 122, 124, 124, 126
| amplitude 64 px
        .byte   128, 130, 132, 132, 134, 136, 138, 138, 140, 142, 144, 146, 146, 148, 150, 152, 152, 154, 156, 158, 160, 160, 162, 164, 166, 166, 168, 170, 172, 172, 174, 176
        .byte   176, 178, 180, 182, 182, 184, 186, 186, 188, 190, 192, 192, 194, 196, 196, 198, 200, 200, 202, 202, 204, 206, 206, 208, 210, 210, 212, 212, 214, 216, 216, 218
        .byte   218, 220, 220, 222, 222, 224, 224, 226, 226, 228, 228, 230, 230, 232, 232, 234, 234, 236, 236, 236, 238, 238, 240, 240, 240, 242, 242, 244, 244, 244, 246, 246
        .byte   246, 246, 248, 248, 248, 250, 250, 250, 250, 250, 252, 252, 252, 252, 252, 254, 254, 254, 254, 254, 254, 254, 254, 254, 254, 254, 254, 254, 254, 254, 254, 254
        .byte   254, 254, 254, 254, 254, 254, 254, 254, 254, 254, 254, 254, 254, 254, 254, 254, 254, 254, 252, 252, 252, 252, 252, 250, 250, 250, 250, 250, 248, 248, 248, 246
        .byte   246, 246, 246, 244, 244, 244, 242, 242, 240, 240, 240, 238, 238, 236, 236, 236, 234, 234, 232, 232, 230, 230, 228, 228, 226, 226, 224, 224, 222, 222, 220, 220
        .byte   218, 218, 216, 216, 214, 212, 212, 210, 210, 208, 206, 206, 204, 202, 202, 200, 200, 198, 196, 196, 194, 192, 192, 190, 188, 186, 186, 184, 182, 182, 180, 178
        .byte   176, 176, 174, 172, 172, 170, 168, 166, 166, 164, 162, 160, 160, 158, 156, 154, 152, 152, 150, 148, 146, 146, 144, 142, 140, 138, 138, 136, 134, 132, 132, 130
        .byte   128, 126, 124, 124, 122, 120, 118, 118, 116, 114, 112, 110, 110, 108, 106, 104, 104, 102, 100, 98, 96, 96, 94, 92, 90, 90, 88, 86, 84, 84, 82, 80
        .byte   80, 78, 76, 74, 74, 72, 70, 70, 68, 66, 64, 64, 62, 60, 60, 58, 56, 56, 54, 54, 52, 50, 50, 48, 46, 46, 44, 44, 42, 40, 40, 38
        .byte   38, 36, 36, 34, 34, 32, 32, 30, 30, 28, 28, 26, 26, 24, 24, 22, 22, 20, 20, 20, 18, 18, 16, 16, 16, 14, 14, 12, 12, 12, 10, 10
        .byte   10, 10, 8, 8, 8, 6, 6, 6, 6, 6, 4, 4, 4, 4, 4, 2, 2, 2, 2, 2, 2, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
        .byte   0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 2, 2, 2, 2, 2, 2, 4, 4, 4, 4, 4, 6, 6, 6, 6, 6, 8, 8, 8, 10
        .byte   10, 10, 10, 12, 12, 12, 14, 14, 16, 16, 16, 18, 18, 20, 20, 20, 22, 22, 24, 24, 26, 26, 28, 28, 30, 30, 32, 32, 34, 34, 36, 36
        .byte   38, 38, 40, 40, 42, 44, 44, 46, 46, 48, 50, 50, 52, 54, 54, 56, 56, 58, 60, 60, 62, 64, 64, 66, 68, 70, 70, 72, 74, 74, 76, 78
        .byte   80, 80, 82, 84, 84, 86, 88, 90, 90, 92, 94, 96, 96, 98, 100, 102, 104, 104, 106, 108, 110, 110, 112, 114, 116, 118, 118, 120, 122, 124, 124, 126
| --- fin des tables generees ---
