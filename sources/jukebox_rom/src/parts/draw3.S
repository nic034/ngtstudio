
| ================================================================ affichage
| Vue liste (par defaut) et vue plein ecran (START).  Tuiles maison (T_*) dans la S-ROM a partir de 0xC00 (zone de remplissage de sfix).

| ---------------------------------------------------------------- outils
| d0=colonne d1=rangee -> adresse VRAM fix, increment d'une colonne
setaddr: move.w d0,d2
        lsl.w   #5,d2
        add.w   d1,d2
        add.w   #0x7000,d2
        move.w  d2,(a6)
        move.w  #0x20,4(a6)
        rts

print:  bsr     setaddr
puts:   moveq   #0,d3
        move.b  (a0)+,d3
        beq.s   1f
        bsr     putc
        bra.s   puts
1:      rts

putc:   or.w    V_ATTR,d3
        move.w  d3,2(a6)
        rts

| tuile d3 (avec sa palette dans les bits 12-15) a la position courante
putt:   move.w  d3,2(a6)
        rts

| d6+1 espaces
spaces: moveq   #0x20,d3
        bsr     putc
        dbra    d6,spaces
        rts

| d4 (0..99) -> 2 chiffres
put2:   moveq   #0,d3
        move.w  d4,d3
        divu    #10,d3
        move.w  d3,d2
        swap    d3
        move.w  d3,-(sp)
        moveq   #0x30,d3
        add.w   d2,d3
        bsr     putc
        move.w  (sp)+,d3
        add.w   #0x30,d3
        bra     putc

| d4 secondes -> mm:ss
putmmss: and.l  #0xFFFF,d4
        divu    #60,d4
        move.l  d4,-(sp)
        cmp.w   #99,d4
        bls.s   1f
        moveq   #99,d4
1:      bsr     put2
        moveq   #0x3A,d3
        bsr     putc
        move.l  (sp)+,d4
        swap    d4
        bra     put2

| titre d'un jeu (a1 = entree) sur d6+1 caracteres
puttitle:
        moveq   #0,d3
        move.b  (a1)+,d3
        bne.s   1f
        subq.l  #1,a1                  | fin du titre : on complete par des espaces
        moveq   #0x20,d3
1:      bsr     putc
        dbra    d6,puttitle
        rts

| ---------------------------------------------------------------- dispatch
draw:   bsr     note_anim
        tst.w   V_FULL
        bne     draw_full
        tst.w   V_DIRTY
        beq.s   1f
        clr.w   V_DIRTY
        bsr     draw_list
        bsr     draw_gameline
1:      moveq   #5,d7                  | panneau "now playing" : rangees 5..7, colonnes 3..
        moveq   #5,d1
        bsr     draw_now
        moveq   #3,d0
        moveq   #7,d1
        bsr     setaddr
        bsr     put_bar
        bsr     draw_vu_small
        bra     draw_marquee

| notes de l'entete : la jaune (colonne 2) et la blanche (colonne 20) rebondissent de 2 pixels en opposition pendant
| la lecture (poses 0-1-2-1, 8 images chacune : ~1,85 battement/s) ; a l'arret et en pause : pose du milieu
note_anim:
        moveq   #1,d4
        tst.w   V_PLAY
        beq.s   1f
        tst.w   V_PAUSE
        bne.s   1f
        move.w  V_TICKS,d4
        lsr.w   #3,d4
        and.w   #3,d4
        cmp.w   #3,d4
        bne.s   1f
        moveq   #1,d4
1:      moveq   #2,d0
        moveq   #3,d1
        bsr     setaddr
        move.w  d4,d3
        add.w   #T_HN0+PAL8,d3
        bsr     putt
        moveq   #20,d0
        moveq   #3,d1
        bsr     setaddr
        moveq   #2,d3
        sub.w   d4,d3
        add.w   #T_WN0+PAL0,d3
        bra     putt

toggle_view:
        bsr     cls
        eor.w   #1,V_FULL
        beq.s   1f
        bra     draw_full_static
1:      move.w  #1,V_DIRTY
        bra     draw_static

cls:    move.w  #0x7000,(a6)           | efface toute la couche fix (40 x 32 cases)
        move.w  #1,4(a6)
        move.w  #0x500-1,d1
1:      move.w  #0x20,2(a6)
        dbra    d1,1b
        rts

| ---------------------------------------------------------------- elements communs
| entete : note, titre arc-en-ciel (une palette par lettre), occupation de la ROM
draw_header:
        moveq   #2,d0
        moveq   #3,d1
        bsr     setaddr
        move.w  #T_HN1+PAL8,d3            | note de l'entete (pose du milieu ; animee par note_anim)
        bsr     putt
        moveq   #4,d0
        moveq   #3,d1
        bsr     setaddr
        lea     t_title,a0
        moveq   #0,d5                  | palette 10 + (n mod 6)
1:      moveq   #0,d3
        move.b  (a0)+,d3
        beq.s   2f
        move.w  d5,d2
        add.w   #10,d2
        lsl.w   #8,d2
        lsl.w   #4,d2
        or.w    d2,d3
        bsr     putt
        addq.w  #1,d5
        cmp.w   #6,d5
        bcs.s   1b
        moveq   #0,d5
        bra.s   1b
2:      moveq   #20,d0                 | croche blanche a droite du titre (colonnes 4..18, une case d'espace)
        moveq   #3,d1
        bsr     setaddr
        move.w  #T_WN1+PAL0,d3
        bsr     putt
        move.w  #PAL3,V_ATTR           | ROM nn%
        lea     t_rom,a0
        moveq   #29,d0
        moveq   #3,d1
        bsr     print
        move.w  0x14E,d4
        cmp.w   #100,d4
        bcs.s   3f
        moveq   #0x31,d3
        bsr     putc
        sub.w   #100,d4
3:      bsr     put2
        moveq   #0x25,d3
        bsr     putc
        clr.w   V_ATTR
        rts

| bouton de manette d3 (tuile+palette) puis texte a0 en gris ; avance de 2 colonnes apres le texte
putbtn: bsr     putt
        moveq   #0x20,d3
        bsr     putc
        move.w  #PAL3,V_ATTR
        bsr     puts
        clr.w   V_ATTR
        moveq   #0x20,d3
        bsr     putc
        moveq   #0x20,d3
        bra     putc

| panneau d'etat a partir de la colonne 3, rangee d1 : icone, titre ; rangee d1+1 : piste, temps, mode
| d7 = colonne du texte (5 en vue liste, 4 en vue plein ecran)
draw_now:
        move.w  d1,-(sp)
        moveq   #3,d0
        cmp.w   #5,d7
        beq.s   1f
        moveq   #2,d0
1:      bsr     setaddr
        move.w  #T_STOP+PAL7,d3        | icone d'etat
        tst.w   V_PLAY
        beq.s   2f
        move.w  #T_PLAY+PAL4,d3
        tst.w   V_PAUSE
        beq.s   2f
        move.w  #T_PAUSE+PAL8,d3
        btst    #4,V_TICKS+1           | pause : l'icone clignote
        beq.s   2f
        move.w  #0x20,d3
2:      bsr     putt
        move.w  d7,d0                  | titre : jeu en lecture, sinon jeu du curseur
        move.w  (sp),d1
        bsr     setaddr
        move.w  V_GAME,d0
        tst.w   V_PLAY
        beq.s   3f
        move.w  V_PG,d0
3:      bsr     gentry
        move.l  a1,-(sp)
        move.w  #PAL2,V_ATTR
        moveq   #23,d6
        bsr     puttitle
        clr.w   V_ATTR
        movea.l (sp)+,a1
        move.w  d7,d0                  | TRACK nn/nn
        move.w  (sp)+,d1
        addq.w  #1,d1
        move.w  d1,-(sp)
        bsr     setaddr
        lea     t_trk,a0
        bsr     puts
        move.w  V_TRK,d4
        tst.w   V_PLAY
        beq.s   4f
        move.w  V_PT,d4
4:      addq.w  #1,d4
        bsr     put2
        moveq   #0x2F,d3
        bsr     putc
        move.w  26(a1),d4
        bsr     put2
        move.w  d7,d0                  | mm:ss / mm:ss
        add.w   #13,d0
        move.w  (sp),d1
        bsr     setaddr
        move.w  V_SECS,d4
        tst.w   V_PLAY
        bne.s   5f
        moveq   #0,d4
5:      bsr     putmmss
        lea     t_sl,a0
        bsr     puts
        moveq   #0,d4
        tst.w   V_PLAY
        beq.s   6f
        move.w  V_TLEN,d4
6:      bsr     putmmss
        moveq   #32,d0                 | mode AUTO / LOOP / RAND
        move.w  (sp)+,d1
        bsr     setaddr
        move.w  #T_AUTO+PAL8,d3
        lea     t_auto,a0
        cmp.w   #1,V_REPM
        bne.s   8f
        move.w  #T_LOOP+PAL8,d3
        lea     t_loop1,a0
        bra.s   7f
8:      cmp.w   #2,V_REPM
        bne.s   7f
        move.w  #T_RAND+PAL8,d3
        lea     t_rand,a0
7:      bsr     putt
        move.w  #PAL8,V_ATTR
        bsr     puts
        clr.w   V_ATTR
        rts

| barre de progression lisse de 34 cases (8 px par case) a l'adresse courante
put_bar:
        moveq   #0,d5                  | d5 = pixels remplis sur 272
        tst.w   V_PLAY
        beq.s   2f
        move.w  V_TLEN,d2
        beq.s   2f
        move.w  V_SECS,d5
        cmp.w   d2,d5
        bcs.s   1f
        move.w  #272,d5
        bra.s   2f
1:      mulu    #272,d5
        divu    d2,d5
2:      moveq   #33,d6
3:      move.w  d5,d3
        bmi.s   4f
        cmp.w   #8,d3
        bls.s   5f
        moveq   #8,d3
        bra.s   5f
4:      moveq   #0,d3
5:      add.w   #T_H0+PAL2,d3
        bsr     putt
        subq.w  #8,d5
        dbra    d6,3b
        rts

| une colonne de vumetre : d0 col, d1 rangee du haut, d7 hauteur (cases),
| d4 pixels allumes, d5 pixel de crete, d6 attribut de la voix ; rouge en haut (>= 80 %), jaune (>= 55 %)
vucol:  movem.l d0-d7,-(sp)
        bsr     setaddr
        move.w  #1,4(a6)               | on descend la colonne
        move.w  d7,d1                  | d1 = rangee en partant du bas (d7-1 .. 0)
        subq.w  #1,d1
1:      move.w  d1,d2                  | t = pixels - 8 * rangee
        lsl.w   #3,d2
        move.w  d4,d3
        sub.w   d2,d3
        ble.s   3f
        cmp.w   #8,d3
        bls.s   2f
        moveq   #8,d3
2:      add.w   #T_V0,d3
        bra.s   5f
3:      move.w  d5,d3                  | case vide : la crete y est-elle ?
        sub.w   d2,d3
        ble.s   4f
        cmp.w   #8,d3
        bhi.s   4f
        add.w   #T_PK1-1,d3
        bra.s   5f
4:      move.w  #T_V0,d3
5:      move.w  d1,d2                  | couleur selon la hauteur (x20 = x16 + x4, x11 = x8 + x1 + x1 + x1 : evite mulu,
        add.w   d2,d2                  |   appele a chaque ligne de chaque vumetre, a chaque image)
        add.w   d2,d2                  | d2 = rangee x 4
        move.w  d2,d0                  | d0 = rangee x 4 (temporaire)
        add.w   d2,d2
        add.w   d2,d2                  | d2 = rangee x 16
        add.w   d0,d2                  | d2 = rangee x 20
        move.w  d7,d0
        lsl.w   #4,d0                  | d0 = niveau x 16
        cmp.w   d0,d2
        bcs.s   6f
        or.w    #PAL7,d3
        bra.s   8f
6:      move.w  d7,d0
        lsl.w   #3,d0                  | d0 = niveau x 8
        add.w   d7,d0
        add.w   d7,d0
        add.w   d7,d0                  | d0 = niveau x 11
        cmp.w   d0,d2
        bcs.s   7f
        or.w    #PAL8,d3
        bra.s   8f
7:      or.w    d6,d3
8:      move.w  d3,2(a6)
        dbra    d1,1b
        movem.l (sp)+,d0-d7
        rts

| niveau de la voix d7 -> d4 pixels, d5 crete (pour une hauteur de d2 cases) ; d6 attribut
vulevel:
        lea     V_LVL,a0
        moveq   #0,d4
        move.b  (a0,d7.w),d4
        mulu    d2,d4
        lsr.l   #4,d4                  | 128 -> d2*8 pixels
        lea     V_PK,a0
        moveq   #0,d5
        move.b  (a0,d7.w),d5
        mulu    d2,d5
        lsr.l   #4,d5
        tst.w   d4                     | voix muette : pas de crete isolee (trait blanc flottant)
        bne.s   1f
        moveq   #0,d5
1:      lea     vupal,a0
        move.w  d7,d6
        add.w   d6,d6
        move.w  (a0,d6.w),d6
        rts

| bandeau defilant, rangee 27 (vue liste) ou 28 (plein ecran), colonnes 4..37
draw_marquee:
        moveq   #28,d1
        moveq   #4,d0
        bsr     setaddr
        tst.w   V_PLAY
        bne.s   2f
        moveq   #33,d6                 | arret : bandeau vide
        bra     spaces
2:      move.w  #PAL5,V_ATTR
        lea     V_MBUF,a0
        move.w  V_MQPOS,d2
        moveq   #33,d6
3:      cmp.w   V_MQLEN,d2
        bcs.s   4f
        moveq   #0,d2
4:      moveq   #0,d3
        move.b  (a0,d2.w),d3
        bsr     putc
        addq.w  #1,d2
        dbra    d6,3b
        clr.w   V_ATTR
        rts

| ---------------------------------------------------------------- vue liste
draw_static:
        bsr     draw_header
        moveq   #1,d0                  | cadre du panneau, rangees 4..8, colonnes 1..37
        moveq   #4,d1
        bsr     setaddr
        move.w  #T_TL+PAL9,d3
        bsr     putt
        moveq   #34,d6
1:      move.w  #T_HZ+PAL9,d3
        bsr     putt
        dbra    d6,1b
        move.w  #T_TR+PAL9,d3
        bsr     putt
        moveq   #1,d0
        moveq   #8,d1
        bsr     setaddr
        move.w  #T_BL+PAL9,d3
        bsr     putt
        moveq   #34,d6
2:      move.w  #T_HZ+PAL9,d3
        bsr     putt
        dbra    d6,2b
        move.w  #T_BR+PAL9,d3
        bsr     putt
        moveq   #5,d1
3:      moveq   #1,d0
        bsr     setaddr
        move.w  #T_VL+PAL9,d3
        bsr     putt
        moveq   #37,d0
        bsr     setaddr
        move.w  #T_VR+PAL9,d3
        bsr     putt
        addq.w  #1,d1
        cmp.w   #8,d1
        bcs.s   3b
        moveq   #LVCOL,d0              | etiquettes des vumetres : 1 2 3 4 S A B
        moveq   #LROW+LVH,d1
        bsr     setaddr
        move.w  #0x20,4(a6)
        lea     vulab,a0
        lea     vupal,a1
        moveq   #6,d6
4:      moveq   #0,d3
        move.b  (a0)+,d3
        or.w    (a1)+,d3
        bsr     putt
        move.w  #0x20,d3
        bsr     putt
        dbra    d6,4b
        moveq   #2,d0                  | aide : boutons de la manette
        moveq   #25,d1
        bsr     setaddr
        move.w  #T_BTNA+PAL7,d3
        lea     t_hplay,a0
        bsr     putbtn
        move.w  #T_BTNB+PAL8,d3
        lea     t_hstop,a0
        bsr     putbtn
        move.w  #T_BTNC+PAL4,d3
        lea     t_hprev,a0
        bsr     putbtn
        move.w  #T_BTND+PAL9,d3
        lea     t_hnext,a0
        bsr     putbtn
        lea     t_start,a0
        moveq   #2,d0
        moveq   #26,d1
        bsr     print
        move.w  #PAL3,V_ATTR
        lea     t_bigvu,a0
        bsr     puts
        clr.w   V_ATTR
        lea     t_select,a0
        bsr     puts
        move.w  #PAL3,V_ATTR
        lea     t_mode,a0
        bsr     puts
        moveq   #2,d0                  | bandeau : note
        moveq   #28,d1
        bsr     setaddr
        move.w  #T_NOTE+PAL5,d3
        bsr     putt
        move.w  V_BADB,d4              | banque P2 manquante : message en rouge (rien si tout va bien)
        cmp.w   #0xFFFF,d4
        beq.s   6f
        move.w  #PAL7,V_ATTR
        moveq   #2,d0
        moveq   #29,d1
        bsr     setaddr
        lea     t_p2,a0
        bsr     puts
        bsr     put2
        lea     t_bko,a0
        bsr     puts
6:      clr.w   V_ATTR
        rts

| ligne du jeu parcouru : < GAME nn/nn > titre
draw_gameline:
        moveq   #2,d0
        moveq   #23,d1
        bsr     setaddr
        move.w  #T_LEFT+PAL3,d3
        bsr     putt
        moveq   #0x20,d3
        bsr     putc
        lea     t_game,a0
        bsr     puts
        move.w  V_GAME,d4
        addq.w  #1,d4
        bsr     put2
        moveq   #0x2F,d3
        bsr     putc
        move.w  V_NG,d4
        bsr     put2
        moveq   #0x20,d3
        bsr     putc
        move.w  #T_RIGHT+PAL3,d3
        bsr     putt
        moveq   #0x20,d3
        bsr     putc
        move.w  V_GAME,d0
        bsr     gentry
        move.w  #PAL2,V_ATTR
        moveq   #21,d6
        bsr     puttitle
        clr.w   V_ATTR
        rts

| liste des pistes, rangees 10..20, colonnes 2..22 ; curseur = barre jaune, piste en lecture = cyan + icone
draw_list:
        move.w  V_GAME,d0
        bsr     gentry
        moveq   #0,d7
dl_l:   move.w  d7,d1
        add.w   #LROW,d1
        moveq   #2,d0
        bsr     setaddr
        move.w  V_TOP,d1
        add.w   d7,d1                  | d1 = piste de la ligne
        cmp.w   26(a1),d1
        bcs.s   1f
        clr.w   V_ATTR                 | ligne vide
        moveq   #20,d6
        bsr     spaces
        bra     dl_n
1:      bsr     tentry
        moveq   #0,d5                  | d5 = 1 si c'est la piste en lecture
        tst.w   V_PLAY
        beq.s   2f
        cmp.w   V_PT,d1
        bne.s   2f
        move.w  V_PG,d2
        cmp.w   V_GAME,d2
        bne.s   2f
        moveq   #1,d5
2:      move.w  #PAL0,V_ATTR
        tst.w   d5
        beq.s   3f
        move.w  #PAL2,V_ATTR
3:      cmp.w   V_TRK,d1
        bne.s   4f
        move.w  #PAL1,V_ATTR           | curseur
4:      moveq   #0x20,d3               | icone de lecture
        tst.w   d5
        beq.s   5f
        move.w  #T_PLAY,d3
        tst.w   V_PAUSE
        beq.s   5f
        move.w  #T_PAUSE,d3
5:      bsr     putc
        moveq   #0x20,d3
        bsr     putc
        lea     t_trk,a0               | TRACK nn
        bsr     puts
        move.w  18(a3),d4
        bsr     put2
        lea     t_sp2,a0
        bsr     puts
        move.w  20(a3),d4              | duree d'un passage
        bsr     putmmss
        moveq   #0x20,d3
        bsr     putc
        moveq   #0x20,d3               | icone de boucle
        cmp.l   #-1,8(a3)
        beq.s   6f
        move.w  #T_LOOP,d3
6:      bsr     putc
        moveq   #1,d6
        bsr     spaces
dl_n:   addq.w  #1,d7
        cmp.w   #NLINES,d7
        bcs     dl_l
        clr.w   V_ATTR
        rts

| 7 petits vumetres (une colonne sur deux), rangees 9..19
draw_vu_small:
        moveq   #0,d7
1:      moveq   #LVH,d2
        bsr     vulevel
        move.w  d7,d0
        add.w   d0,d0
        add.w   #LVCOL,d0
        movem.l d7,-(sp)
        moveq   #LROW,d1
        moveq   #LVH,d7
        bsr     vucol
        movem.l (sp)+,d7
        addq.w  #1,d7
        cmp.w   #7,d7
        bcs.s   1b
        rts

| ---------------------------------------------------------------- vue plein ecran
draw_full_static:
        bsr     draw_header
        moveq   #3,d0                  | noms des voix sous les barres, dans leur couleur
        moveq   #FROW+FH,d1
        bsr     setaddr
        lea     t_flab,a0
        lea     vupal,a1
        moveq   #6,d6
1:      move.w  (a1)+,V_ATTR
        moveq   #4,d5
2:      moveq   #0,d3
        move.b  (a0)+,d3
        bsr     putc
        dbra    d5,2b
        dbra    d6,1b
        clr.w   V_ATTR
        moveq   #2,d0                  | aide
        moveq   #26,d1
        bsr     setaddr
        move.w  #T_BTNA+PAL7,d3
        lea     t_hpause,a0
        bsr     putbtn
        move.w  #T_BTNC+PAL4,d3
        lea     t_hprev,a0
        bsr     putbtn
        move.w  #T_BTND+PAL9,d3
        lea     t_hnext,a0
        bsr     putbtn
        lea     t_start,a0
        bsr     puts
        move.w  #PAL3,V_ATTR
        lea     t_list,a0
        bsr     puts
        clr.w   V_ATTR
        moveq   #2,d0
        moveq   #28,d1
        bsr     setaddr
        move.w  #T_NOTE+PAL5,d3
        bsr     putt
        rts

draw_full:
        moveq   #4,d7                  | etat : rangees 5 et 6, texte en colonne 4
        moveq   #5,d1
        bsr     draw_now
        moveq   #0,d7                  | 7 vumetres de 4 colonnes
1:      moveq   #FH,d2
        bsr     vulevel
        move.w  d7,d0
        mulu    #5,d0
        addq.w  #3,d0
        moveq   #3,d2
2:      movem.l d2/d7,-(sp)
        moveq   #FROW,d1
        moveq   #FH,d7
        bsr     vucol
        movem.l (sp)+,d2/d7
        addq.w  #1,d0
        dbra    d2,2b
        addq.w  #1,d7
        cmp.w   #7,d7
        bcs.s   1b
        moveq   #3,d0                  | barre de progression
        moveq   #24,d1
        bsr     setaddr
        bsr     put_bar
        bra     draw_marquee

| ---------------------------------------------------------------- interruptions
vblank: tst.b   0x10FD80
        bpl     sysmode
        move.b  d0,0x300001
        movem.l d0-d7/a0-a6,-(sp)
        move.l  V_PALFN,d0             | palettes : toujours ecrites ici, dans le retour de trame (pendant l'affichage, une
        beq.s   4f                     |   ecriture de palette laisse un point / trait parasite sur une vraie console)
        clr.l   V_PALFN
        cmp.l   #pal_norm,d0           | seulement les routines prevues (la RAM peut contenir n'importe quoi au demarrage)
        beq.s   5f
        cmp.l   #pal_saver,d0
        bne.s   4f
5:      movea.l d0,a0
        jsr     (a0)
4:      move.w  V_HUEP,d1              | arc-en-ciel du titre (prepare par tick)
        beq.s   6f
        clr.w   V_HUEP
        cmp.w   #7,d1
        bcc.s   6f
        lea     V_HUEB,a0
        lea     0x400142,a1
        subq.w  #1,d1
7:      move.w  (a0)+,(a1)
        lea     32(a1),a1
        dbra    d1,7b
6:      tst.w   V_SAVER                | economiseur : animation au tout debut du retour de trame, a chaque image
        beq.s   1f
        lea     LSPC,a6
        bsr     toasty_vbl             | Toasty : attente / animation, en premier (1 a 2 lignes) : ses positions sont posees
        bsr     saver_scroll           |   au debut du retour de trame, meme quand saver_scroll deborde (scene sphere)
1:      bsr     toasty_time            | Toasty : temps de lecture (20 min)
        jsr     0xC0044A               | SYSTEM_IO
        move.b  P1CHG,d0               | cumule les appuis jusqu'a la prochaine lecture par la boucle principale
        or.b    d0,V_EACC
        move.b  STCHG,d0
        or.b    d0,V_SACC
        addq.w  #1,V_VBL
        move.b  #1,V_FRAME
        movem.l (sp)+,d0-d7/a0-a6
        move.w  #4,0x3C000C
        rte
sysmode:
        trap    #0
        move.w  #4,0x3C000C
        rte
irqother:
        move.w  #3,0x3C000C
        rte

| ---------------------------------------------------------------- textes
t_title: .asciz "NEO GEO JUKEBOX"
t_rom:   .asciz "ROM "
t_trk:   .asciz "TRACK "
t_game:  .asciz "GAME "
t_sl:    .asciz " / "
t_sp2:   .asciz "  "
t_auto:  .asciz "AUTO"
t_loop1: .asciz "LOOP"
t_rand:  .asciz "RAND"
t_hplay: .asciz "PLAY/PAUSE"
t_hpause: .asciz "PAUSE"
t_hstop: .asciz "STOP"
t_hprev: .asciz "PREV"
t_hnext: .asciz "NEXT"
t_start: .asciz "START "
t_bigvu: .asciz "BIG VU  "
t_list:  .asciz "LIST"
t_select: .asciz "SELECT "
t_mode:  .asciz "AUTO/LOOP/RAND"
t_flab:  .ascii "FM1  FM2  FM3  FM4  SSG  ADPA ADPB "
t_nowp:  .asciz "NOW PLAYING  "
t_mtrk:  .asciz "  -  TRACK "
t_p2:    .asciz "P2 "
t_bko:   .asciz " = FIRST MISSING BANK"
vulab:   .ascii "1234SAB"
t_mark:  .ascii "NGJB BANK "
        .balign 2
vupal:   .word   PAL2, PAL2, PAL2, PAL2, PAL4, PAL5, PAL6
secblk: .incbin "build/sec.bin"
        .balign 2
jb_end:
