| =====================================================================
|  Neo Geo JUKEBOX  (68000)  -  lit un index NGJB dans la P-ROM et
|  alimente le driver Z80 (latch $320000) en flux d'ecritures YM2610.
| =====================================================================
        .text
        .org    0
        .long   0x10F300, 0xC00402, 0xC00408, 0xC0040E, 0xC00414, 0xC00426, 0xC00426, 0xC00426
        .long   0xC0041A, 0xC00420, 0xC00426, 0xC00426, 0xC00426, 0xC00426, 0xC00426, 0xC0042C
        .long   0xC00426, 0xC00426, 0xC00426, 0xC00426, 0xC00426, 0xC00426, 0xC00426, 0xC00426
        .long   0xC00432, vblank, irqother, irqother
        .long   0xC00426, 0xC00426, 0xC00426, 0xC00426
        .long   0xC00438
        .fill   (0x100-0x84), 1, 0x55
        .org    0x100
        .ascii  "NEO-GEO"
        .byte   0x01
        .word   0x0999                 | NGH (a changer pour une vraie cartouche)
        .long   0x00100000             | taille P-ROM visible
        .long   0x00108800             | backup RAM
        .word   0x0800
        .byte   2                      | eyecatcher : ignore
        .byte   0
        .long   0,0,0
        .word   0x4EF9                 | 0x122 USER : jmp absolu ecrit a la main (l'assembleur raccourcissait
        .long   user                   |   "jmp user" en jmp relatif de 4 octets et decalait les vecteurs suivants)
        .word   0x4EF9                 | 0x128 PLAYER_START : appele par le BIOS (AES / UniBIOS) quand START
        .long   cb_rts                 |   est presse ; le jukebox gere START lui-meme -> simple rts
        .word   0x4EF9                 | 0x12E DEMO_END
        .long   cb_rts
        .word   0x4EF9                 | 0x134 COIN_SOUND
        .long   cb_rts
        .fill   (0x140-0x13A), 1, 0x55
        .org    0x140
        .ascii  "NGJB"                 | 0x140 : repere pour le constructeur
        .long   0                      | 0x144 : offset de l'index dans la P-ROM (rempli par le constructeur)
        .long   0                      | 0x148 : base des offsets de flux (0 : offsets absolus)
        .word   0                      | 0x14C : nombre de banques P2 (chacune commence par un marqueur de 16 octets)
        .word   0                      | 0x14E : occupation globale de la ROM en % (calculee par le constructeur)
        .org    0x182
        .long   secblk, 0, 1, 0
        .org    0x200
