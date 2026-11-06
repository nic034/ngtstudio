
        .equ    LSPC,    0x3C0000
        .equ    RAM,     0x100000
        .equ    V_FRAME, RAM+0
        .equ    V_GAME,  RAM+2          | jeu affiche (curseur)
        .equ    V_TRK,   RAM+4          | piste sous le curseur
        .equ    V_PLAY,  RAM+6          | 0 arret, 1 envoi en cours, 2 tout envoye (le Z80 finit la piste)
        .equ    V_SOFF,  RAM+8          | prochain octet compresse (offset P-ROM)
        .equ    V_LEFT,  RAM+12         | octets decompresses restant dans le bloc
        .equ    V_LOOP,  RAM+16         | offset P-ROM du bloc de boucle (-1 : aucun)
        .equ    V_LLEN,  RAM+20         | taille decompressee du bloc de boucle
        .equ    V_FREE,  RAM+24
        .equ    V_SECS,  RAM+26
        .equ    V_FCNT,  RAM+28
        .equ    V_BANK,  RAM+30
        .equ    V_ZDEAD, RAM+32
        .equ    V_NG,    RAM+34
        .equ    V_IDX,   RAM+36
        .equ    V_LENS,  RAM+40
        .equ    V_REPLY, RAM+42
        .equ    V_SBASE, RAM+44         | offset P-ROM des flux
        .equ    V_FLAGS, RAM+48         | LZSS : drapeaux courants (mot)
        .equ    V_NBITS, RAM+50         | LZSS : drapeaux restants
        .equ    V_MLEN,  RAM+52         | LZSS : octets de copie restants
        .equ    V_MDIST, RAM+54         | LZSS : distance de la copie
        .equ    V_WPOS,  RAM+56         | LZSS : position dans la fenetre
        .equ    V_INLP,  RAM+58         | 1 = on joue le bloc de boucle
        .equ    V_BADB,  RAM+60         | premiere banque P2 absente (0xFFFF : toutes presentes)
        .equ    V_NBK,   RAM+62         | nombre de banques P2 annoncees
        .equ    V_PG,    RAM+64         | jeu en lecture
        .equ    V_PT,    RAM+66         | piste en lecture
        .equ    V_PAUSE, RAM+68         | 1 = en pause
        .equ    V_TOP,   RAM+70         | premiere piste visible dans la liste
        .equ    V_ZST,   RAM+72         | 1 = le Z80 joue encore une piste (bit 6 de sa reponse)
        .equ    V_ATTR,  RAM+74         | palette des caracteres (bits 12-15)
        .equ    V_REP,   RAM+76         | repetition haut/bas maintenus
        .equ    V_DIRTY, RAM+78         | 1 = liste a redessiner
        .equ    V_TLEN,  RAM+80         | duree de la piste en lecture (s)
        .equ    V_HASLP, RAM+82         | 1 = la piste en lecture boucle
        .equ    V_EDGE,  RAM+84         | boutons nouvellement presses (image courante)
        .equ    V_LVL,   RAM+86         | 7 octets : niveau des vumetres (0..10)
        .equ    V_HUE,   RAM+94         | phase de l'arc-en-ciel du titre
        .equ    V_TICKS, RAM+96         | compteur d'images (animations)
        .equ    V_VBL,   RAM+98         | images (VBlank) depuis le demarrage
        .equ    V_LVBL,  RAM+100        | V_VBL au dernier passage de tick
        .equ    V_EACC,  RAM+102        | boutons presses, cumules par le VBlank (octet)
        .equ    V_SACC,  RAM+103        | START/SELECT presses, cumules par le VBlank (octet)
        .equ    V_FULL,  RAM+104        | 1 = vue plein ecran (vumetres geants)
        .equ    V_PK,    RAM+106        | 7 octets : crete maintenue de chaque vumetre
        .equ    V_MS,    RAM+114        | temps de lecture : millimes d'image accumules
        .equ    V_CBUF,  RAM+120        | 16 mots : colonne de vumetre preparee
        .equ    V_REPM,  RAM+152        | 0 AUTO (enchaine tout), 1 LOOP1 (repete la piste), 2 RAND (piste au hasard)
        .equ    V_MQPOS, RAM+154        | position du bandeau defilant
        .equ    V_MQLEN, RAM+156        | longueur du texte du bandeau
        .equ    V_MBUF,  RAM+160        | texte du bandeau (80 octets)
        .equ    LOOPS,   2              | mode AUTO : tours de boucle avant la piste suivante
        .equ    WIN,     0x100800       | fenetre LZSS 32 Ko (s'arrete avant la backup RAM en 0x108800)
        .equ    P1CUR,   0x10FD96
        .equ    P1CHG,   0x10FD97
        .equ    STCHG,   0x10FDAD       | START/SELECT nouvellement presses (bit 0 START J1, bit 1 SELECT J1)
        .equ    FEED,    160            | octets relayes au Z80 par image au plus (= JB_FEED de ngt_studio.py)
        .equ    FEEDMIN, 24             | ... dont au moins FEEDMIN, meme en fin de trame
        .equ    FEEDEND, 0x1B0          | ligne a partir de laquelle on cesse de relayer (64 lignes avant le VBlank)
        .equ    FEEDLOW, 1008-400       | ... seulement si le Z80 a au moins 400 octets en reserve (V_FREE < 608)
        .equ    NLINES,  11             | pistes visibles (lignes 10 a 20)
        .equ    LROW,    10
        .equ    LVH,     11             | vumetres de la vue liste : hauteur (cases)
        .equ    LVCOL,   24             | vue liste : premier vumetre (une colonne sur deux) ; B en colonne 36
                                        | (la colonne 38 est cachee par le cache de certains televiseurs)
        .equ    FROW,    8              | vue plein ecran : haut des vumetres
        .equ    FH,      14             | vue plein ecran : hauteur des vumetres
        .equ    PAL0,    0x0000         | blanc
        .equ    PAL1,    0x1000         | selection : noir sur jaune
        .equ    PAL2,    0x2000         | cyan (+ rail de la barre de progression)
        .equ    PAL3,    0x3000         | gris
        .equ    PAL4,    0x4000         | vert
        .equ    PAL5,    0x5000         | orange
        .equ    PAL6,    0x6000         | magenta
        .equ    PAL7,    0x7000         | rouge
        .equ    PAL8,    0x8000         | jaune
        .equ    PAL9,    0x9000         | bleu
        .equ    PALR,    0xA000         | 10..15 : arc-en-ciel du titre (couleurs animees)
        .equ    BACKDROP, 0x7001        | fond bleu nuit

        .include "build/tiles_equ.S"

user:   moveq   #0,d0
        move.b  0x10FDAE,d0
        cmp.b   #2,d0
        bcc.s   game
        jmp     0xC00444

game:   clr.l   V_PALFN                | (palettes en attente : aucune ; le VBlank verifie de toute facon l'adresse)
        clr.w   V_HUEP
        move.w  #0x2000,%sr
        move.w  #7,0x3C000C
        lea     LSPC,a6
        move.b  d0,0x300001
        cmp.b   #3,d0                  | MVS : une piece fait rappeler USER avec 3 (titre) ; le jukebox tourne deja :
        bne.s   6f                     | on reprend la ou on en etait (la musique continue) au lieu de tout relancer
        cmp.l   #0x4E474A42,V_MAGIC
        bne.s   6f
        bra     resume
6:      move.w  #0x7000,(a6)           | efface la couche fix
        move.w  #1,4(a6)
        move.w  #0x500-1,d1
1:      move.w  #0x20,2(a6)
        dbra    d1,1b
        move.w  #0x8200,(a6)           | cache les sprites
        move.w  #1,4(a6)
        move.w  #381-1,d1
2:      clr.w   2(a6)
        dbra    d1,2b
        moveq   #0,d7                  | 16 palettes : couleur 1 (texte/icone), 2 (fond des lettres), 3 blanc, 4 rail
        bsr     setpals
        lea     RAM,a0                 | variables a zero
        moveq   #0,d0
        moveq   #128-1,d1
3:      move.w  d0,(a0)+
        dbra    d1,3b
        move.w  #0xFFFF,V_BANK
        move.w  #1008,V_FREE
        move.l  #0x4E474A42,V_MAGIC    | "NGJB" : jukebox initialise (voir la reprise ci-dessus)
        move.w  #1,V_DIRTY
        move.l  0x148,V_SBASE
        move.l  0x144,d0               | index NGJB
        move.l  d0,V_IDX
        movea.l d0,a0
        move.w  4(a0),V_NG
        bsr     bank_check
        bsr     draw_static
        move.b  #3,0x320000            | reveille le driver Z80 s'il attend encore (bascule BIOS -> M1)
        moveq   #9,d7
4:      bsr     wait_frame
        dbra    d7,4b
        bsr     z_stop
        tst.w   V_NG                   | lecture automatique des le demarrage (mode AUTO)
        beq.s   main
        moveq   #0,d0
        moveq   #0,d1
        bsr     play

main:   bsr     wait_frame
        bsr     saver_info             | economiseur : texte d'informations (l'animation est dans le VBlank)
        bsr     saver_in               | economiseur d'ecran : un appui le reveille (et n'agit pas)
        tst.w   V_SAVER                | economiseur actif : les appuis restent pour saver_in (reveil, image suivante) ;
        bne.s   1f                     |   ainsi un appui pendant l'entree dans l'economiseur ne fait que le reveiller
        bsr     inputs
1:
        bsr     autonext
        bsr     feed
        bsr     vu_query
        bsr     tick
        tst.w   V_SAVER                | economiseur actif : affichage fige
        bne.s   main
        bsr     draw
        bra     main

wait_frame:
        tst.b   V_FRAME
        beq.s   wait_frame
        clr.b   V_FRAME
        rts

| ---------------------------------------------------------------- index
| d0 = jeu -> a1 = entree du jeu (titre 24, +24 premiere piste, +26 nombre)
gentry: movea.l V_IDX,a1
        move.l  8(a1),d2
        adda.l  d2,a1
        move.w  d0,d2
        lsl.w   #5,d2
        adda.w  d2,a1
        rts

| a1 = entree du jeu, d1 = piste -> a3 = entree de la piste (32 octets)
tentry: movea.l V_IDX,a3
        move.l  12(a3),d2
        adda.l  d2,a3
        move.w  24(a1),d2
        add.w   d1,d2
        lsl.w   #5,d2
        adda.w  d2,a3
        rts

| ---------------------------------------------------------------- manette
inputs: move.w  sr,-(sp)               | appuis cumules par le VBlank : aucun n'est perdu si une image saute
        move.w  #0x2700,sr
        move.b  V_EACC,d0
        clr.b   V_EACC
        move.b  V_SACC,d1
        clr.b   V_SACC
        move.w  (sp)+,sr
        move.b  d0,V_EDGE
        btst    #1,d1                  | SELECT : AUTO -> LOOP1 -> RAND -> AUTO
        beq.s   7f
        move.w  V_REPM,d2
        addq.w  #1,d2
        cmp.w   #3,d2
        bcs.s   8f
        moveq   #0,d2
8:      move.w  d2,V_REPM
        move.w  #1,V_DIRTY
7:      btst    #0,d1                  | START : liste <-> plein ecran
        beq.s   6f
        move.w  d0,-(sp)
        bsr     toggle_view
        move.w  (sp)+,d0
6:
        move.b  d0,d2                  | haut/bas : appui, puis repetition si maintenu
        and.b   #3,d2
        bne.s   in_new
        move.b  P1CUR,d2
        and.b   #3,d2
        beq.s   in_btn
        subq.w  #1,V_REP
        bgt.s   in_btn
        move.w  #4,V_REP
        bra.s   in_mv
in_new: move.w  #18,V_REP
in_mv:  btst    #0,d2
        beq.s   in_dn
        bsr     cur_up
        bra.s   in_btn
in_dn:  btst    #1,d2
        beq.s   in_btn
        bsr     cur_dn
in_btn: move.b  V_EDGE,d0
        btst    #2,d0                  | gauche : jeu precedent
        beq.s   in_r
        move.w  V_GAME,d1
        bne.s   1f
        move.w  V_NG,d1
1:      subq.w  #1,d1
        bra.s   in_g
in_r:   btst    #3,d0                  | droite : jeu suivant
        beq.s   in_a
        move.w  V_GAME,d1
        addq.w  #1,d1
        cmp.w   V_NG,d1
        bcs.s   in_g
        moveq   #0,d1
in_g:   move.w  d1,V_GAME
        clr.w   V_TRK
        clr.w   V_TOP
        move.w  #1,V_DIRTY
        rts
in_a:   btst    #4,d0                  | A : lecture de la piste choisie / pause si c'est elle
        beq.s   in_b
        tst.w   V_PLAY
        beq.s   play_cur
        move.w  V_PG,d1
        cmp.w   V_GAME,d1
        bne.s   play_cur
        move.w  V_PT,d1
        cmp.w   V_TRK,d1
        bne.s   play_cur
        bra     pause_tg
play_cur:
        move.w  V_GAME,d0
        move.w  V_TRK,d1
        bra     play
in_b:   btst    #5,d0                  | B : stop
        beq.s   in_c
        bra     stop
in_c:   btst    #6,d0                  | C : piste precedente
        beq.s   in_d
        tst.w   V_PLAY
        beq.s   1f
        move.w  V_PG,V_GAME
        move.w  V_PT,V_TRK
1:      bsr     cur_up
        bra.s   play_cur
in_d:   btst    #7,d0                  | D : piste suivante
        beq.s   in_x
        tst.w   V_PLAY
        beq.s   1f
        move.w  V_PG,V_GAME
        move.w  V_PT,V_TRK
1:      bsr     cur_dn
        bra.s   play_cur
in_x:   rts

cur_up: move.w  V_GAME,d0
        bsr     gentry
        move.w  V_TRK,d1
        bne.s   1f
        move.w  26(a1),d1
1:      subq.w  #1,d1
        move.w  d1,V_TRK
        bra.s   cur_vis
cur_dn: move.w  V_GAME,d0
        bsr     gentry
        move.w  V_TRK,d1
        addq.w  #1,d1
        cmp.w   26(a1),d1
        bcs.s   1f
        moveq   #0,d1
1:      move.w  d1,V_TRK
cur_vis:                               | garde le curseur dans la fenetre de NLINES pistes
        move.w  V_TRK,d1
        cmp.w   V_TOP,d1
        bcc.s   1f
        move.w  d1,V_TOP
1:      move.w  V_TOP,d2
        add.w   #NLINES,d2
        cmp.w   d2,d1
        bcs.s   2f
        sub.w   #NLINES-1,d1
        move.w  d1,V_TOP
2:      move.w  #1,V_DIRTY
        rts

| ---------------------------------------------------------------- lecture
| d0 = jeu, d1 = piste
play:   movem.l d0-d1,-(sp)
        bsr     z_stop
        bsr     wait_frame
        bsr     wait_frame
        movem.l (sp)+,d0-d1
        move.w  d0,V_PG
        move.w  d1,V_PT
        move.w  d0,V_GAME
        move.w  d1,V_TRK
        bsr     cur_vis
        move.w  V_PG,d0
        bsr     gentry
        move.w  V_PT,d1
        cmp.w   26(a1),d1
        bcc     stop                   | piste inexistante
        bsr     tentry
        move.l  (a3),d4                | bloc d'intro
        add.l   V_SBASE,d4
        move.l  4(a3),d5
        bsr     blk_start
        move.l  8(a3),d4               | bloc de boucle
        clr.w   V_HASLP
        cmp.l   #-1,d4
        beq.s   1f
        add.l   V_SBASE,d4
        move.w  #1,V_HASLP
1:      move.l  d4,V_LOOP
        move.l  12(a3),V_LLEN
        clr.w   V_INLP
        move.w  20(a3),d0              | duree affichee : en AUTO / RAND, intro + LOOPS tours de boucle
        tst.w   V_HASLP
        beq.s   2f
        cmp.w   #1,V_REPM
        beq.s   2f
        add.w   24(a3),d0
2:      move.w  d0,V_TLEN
        bsr     build_marquee
        bsr     z_play
        move.w  #1,V_PLAY
        move.w  #1,V_ZST
        clr.w   V_PAUSE
        clr.w   V_SECS
        clr.w   V_MS
        move.w  #1,V_DIRTY
        bra     feed

| texte du bandeau : "NOW PLAYING  <titre>  -  TRACK nn" suivi d'espaces (a1 = entree du jeu)
build_marquee:
        lea     V_MBUF,a0
        lea     t_nowp,a2
1:      move.b  (a2)+,(a0)+
        bne.s   1b
        subq.l  #1,a0
        movea.l a1,a2                  | titre (24 car. max, sans les zeros de fin)
        moveq   #23,d2
2:      move.b  (a2)+,d3
        beq.s   3f
        move.b  d3,(a0)+
        dbra    d2,2b
3:      lea     t_mtrk,a2
4:      move.b  (a2)+,(a0)+
        bne.s   4b
        subq.l  #1,a0
        move.w  V_PT,d3                | numero de piste sur 2 chiffres
        addq.w  #1,d3
        ext.l   d3
        divu    #10,d3
        add.b   #0x30,d3
        move.b  d3,(a0)+
        swap    d3
        add.b   #0x30,d3
        move.b  d3,(a0)+
        moveq   #7,d2                  | espaces avant la reprise
5:      move.b  #0x20,(a0)+
        dbra    d2,5b
        move.l  a0,d0
        sub.l   #V_MBUF,d0
        move.w  d0,V_MQLEN
        clr.w   V_MQPOS
        rts

stop:   bsr     z_stop
        clr.w   V_PLAY
        clr.w   V_PAUSE
        move.w  #1,V_DIRTY
        rts

pause_tg:
        move.b  #0xFF,d0
        bsr     sendb
        tst.w   V_PAUSE
        bne.s   1f
        move.b  #0x03,d0               | FF 03 : pause
        move.w  #1,V_PAUSE
        bra.s   2f
1:      move.b  #0x04,d0               | FF 04 : reprise
        clr.w   V_PAUSE
2:      move.w  #1,V_DIRTY
        bra     sendb

| fin de piste : AUTO piste suivante (puis jeu suivant ; apres le dernier jeu, le premier : la lecture ne s'arrete
| jamais), LOOP1 la meme, RAND une piste au hasard parmi tous les jeux (jamais la meme deux fois de suite)
autonext:
        cmp.w   #2,V_PLAY
        bne.s   an_x
        tst.w   V_ZST
        bne.s   an_x
        tst.w   V_PAUSE
        bne.s   an_x
        move.w  V_PG,d0
        move.w  V_PT,d1
        move.w  V_REPM,d2
        cmp.w   #1,d2                  | LOOP1 : on rejoue la meme piste
        beq     play
        cmp.w   #2,d2
        beq.s   pick_rand
        bsr     gentry
        move.w  V_PT,d1
        addq.w  #1,d1
        cmp.w   26(a1),d1
        bcs.s   1f
        moveq   #0,d1                  | dernier morceau du jeu : jeu suivant
        addq.w  #1,d0
        cmp.w   V_NG,d0
        bcs.s   1f
        moveq   #0,d0
1:      bra     play
an_x:   rts

| RAND : piste tiree au hasard parmi les N pistes de tous les jeux, sauf celle qui vient de finir (N - 1 choix
| equiprobables) ; d0/d1 = jeu / piste en cours.  Graine du hasard : le compteur d'images (rnd ne sort jamais de 0
| une fois amorce ; l'economiseur la repose aussi).  Modifie d0-d6/a1.
pick_rand:
        moveq   #0,d3                  | d3 = N, d5 = rang global de la piste en cours
        moveq   #0,d4
        moveq   #0,d5
1:      move.w  d4,d0
        bsr     gentry
        cmp.w   V_PG,d4
        bne.s   2f
        move.w  d3,d5
        add.w   V_PT,d5
2:      add.w   26(a1),d3
        addq.w  #1,d4
        cmp.w   V_NG,d4
        bcs.s   1b
        cmp.w   #2,d3
        bcs.s   6f                     | une seule piste en tout : on la rejoue
        tst.w   V_RND
        bne.s   3f
        move.w  V_VBL,d0
        or.w    #1,d0
        move.w  d0,V_RND
3:      bsr     rnd                    | d0.l = 0..65535 (moitie haute nulle)
        move.w  d3,d2
        subq.w  #1,d2
        divu    d2,d0
        swap    d0                     | 0..N-2
        cmp.w   d5,d0
        bcs.s   4f
        addq.w  #1,d0                  | on saute la piste qui vient de finir
4:      move.w  d0,d6                  | rang -> jeu / piste
        moveq   #0,d4
5:      move.w  d4,d0
        bsr     gentry
        move.w  26(a1),d2
        cmp.w   d2,d6
        bcs.s   7f
        sub.w   d2,d6
        addq.w  #1,d4
        bra.s   5b
7:      move.w  d4,d0
        move.w  d6,d1
        bra     play
6:      move.w  V_PG,d0
        move.w  V_PT,d1
        bra     play

| vumetres : le Z80 renvoie les voix declenchees depuis la derniere image (FF 06)
vu_query:
        tst.w   V_PLAY
        beq.s   9f
        tst.w   V_PAUSE
        bne.s   9f
        move.w  V_FREE,-(sp)           | cette reponse ne porte pas les places libres : on les garde
        move.w  V_ZST,-(sp)
        move.b  #0xFF,d0
        bsr     sendb
        move.b  #0x06,d0
        bsr     sendb
        move.w  (sp)+,V_ZST
        move.w  (sp)+,V_FREE
        move.w  V_REPLY,d0
        lea     V_LVL,a0
        moveq   #6,d1
1:      lsr.w   #1,d0
        bcc.s   2f
        move.b  #128,(a0)
2:      addq.l  #1,a0
        dbra    d1,1b
9:      rts

tick:   addq.w  #1,V_TICKS
        tst.w   V_ZDEAD                | Z80 muet : nouvel essai une fois par seconde
        beq.s   5f
        move.w  V_TICKS,d0
        and.w   #63,d0
        bne.s   5f
        clr.w   V_ZDEAD
        move.b  #0xFF,d0
        bsr     sendb
        move.b  #0x00,d0
        bsr     sendb
5:      tst.w   V_SAVER                | economiseur : rien a afficher (vumetres, cretes, titre, bandeau arretes ; ils
        bne     tk_sv                  |   reprennent au reveil) ; seuls les niveaux tombent (energie de la vague)
        lea     V_LVL,a0               | vumetres : chute de 5/128 par image ; cretes : maintien puis chute lente
        lea     V_PK,a1
        moveq   #6,d1
1:      moveq   #0,d2
        move.b  (a0),d2
        moveq   #0,d3
        move.b  (a1),d3
        cmp.w   d3,d2
        bls.s   2f
        move.b  d2,(a1)
        bra.s   3f
2:      moveq   #0,d3                  | crete : chute de 3/128 par image (~0,7 s)
        move.b  (a1),d3
        subq.w  #3,d3
        bpl.s   8f
        moveq   #0,d3
8:      move.b  d3,(a1)
3:      subq.w  #5,d2
        bpl.s   4f
        moveq   #0,d2
4:      move.b  d2,(a0)+
        addq.l  #1,a1
        dbra    d1,1b
        moveq   #0,d0                  | (divu divise les 32 bits de d0)
        move.w  V_TICKS,d0             | arc-en-ciel : les 6 palettes du titre tournent toutes les 3 images
        divu    #3,d0
        swap    d0
        tst.w   d0
        bne.s   5f
        addq.w  #1,V_HUE
        lea     V_HUEB,a0              | couleur 1 des palettes 10.. : preparee ici, posee par le VBlank (V_HUEP)
        move.w  V_HUE,d1
        moveq   #3,d2
6:      and.w   #31,d1
        move.w  d1,d3
        add.w   d3,d3
        lea     hues,a1
        move.w  (a1,d3.w),(a0)+
        addq.w  #4,d1
        dbra    d2,6b
        move.w  #4,V_HUEP
5:      move.w  V_TICKS,d0             | bandeau : un caractere toutes les 8 images
        and.w   #7,d0
        bne.s   7f
        move.w  V_MQPOS,d0
        addq.w  #1,d0
        cmp.w   V_MQLEN,d0
        bcs.s   8f
        moveq   #0,d0
8:      move.w  d0,V_MQPOS
7:
tk_tm:  move.w  V_VBL,d0               | temps de lecture : images reelles (VBlank a 59,185 Hz)
        move.w  d0,d1
        sub.w   V_LVBL,d1
        move.w  d0,V_LVBL
        cmp.w   #6,d1
        bls.s   5f
        moveq   #6,d1
5:      tst.w   V_PLAY
        beq.s   1f
        tst.w   V_PAUSE
        bne.s   1f
        mulu    #1000,d1
        add.w   d1,V_MS
6:      cmp.w   #59185,V_MS
        bcs.s   1f
        sub.w   #59185,V_MS
        addq.w  #1,V_SECS
        bra.s   6b
1:      rts
tk_sv:  lea     V_LVL,a0               | economiseur : chute des niveaux seulement
        moveq   #6,d1
1:      moveq   #0,d2
        move.b  (a0),d2
        subq.w  #5,d2
        bpl.s   2f
        moveq   #0,d2
2:      move.b  d2,(a0)+
        dbra    d1,1b
        bra     tk_tm


        .balign 2
| couleur 1, couleur 2 de chaque palette (format Neo Geo) ; couleur 2 = fond bleu nuit sauf la selection
paltab: .word   0x5DEE, 0x7001
        .word   0x8000, 0x7FB3
        .word   0x74CF, 0x7001
        .word   0x6679, 0x7001
        .word   0x79EF, 0x7001
        .word   0x38AC, 0x7001
        .word   0x3D44, 0x7001
        .word   0x7FB3, 0x7001
        .word   0x6EC4, 0x7001
        .word   0x5259, 0x7001
        .word   0x74CF, 0x7001
        .word   0x74CF, 0x7001
        .word   0x74CF, 0x7001
        .word   0x74CF, 0x7001
        .word   0x65B6, 0x7001
        .word   0x747E, 0x7001
vucols: .word   0x13EF, 0x74F4, 0x7F91, 0x6F4E, 0x5F32   | FM, SSG, ADPCM-A, ADPCM-B, crete
hues:   .word   0x74CF, 0x74CF, 0x56DF, 0x78DF, 0x1BEF, 0x3DEF, 0x1FFF, 0x3DEF, 0x1BEF, 0x78DF, 0x56DF, 0x74CF, 0x74CF, 0x74CF, 0x74CF, 0x74CF, 0x74CF, 0x74CF, 0x74CF, 0x74CF, 0x74CF, 0x74CF, 0x74CF, 0x74CF, 0x74CF, 0x74CF, 0x74CF, 0x74CF, 0x74CF, 0x74CF, 0x74CF, 0x74CF   | reflet du titre
