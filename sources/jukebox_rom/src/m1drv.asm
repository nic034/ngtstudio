; ---------------------------------------------------------------------
; Driver Z80 "NGJB" : lit un flux d'ecritures YM2610 envoye octet par octet
; par le 68000 (latch $320000 -> NMI), temps = Timer A du YM2610.
;
; Flux (octets) :
;   00..BF  rr vv   ecriture port A  (registre rr, valeur vv)
;   C0      rr vv   ecriture port B
;   C1      nn      attente nn ticks (1 tick = 32 echantillons = 0,57 ms)
;   C2      lo hi   attente 16 bits
;   C3              fin de piste (silence)
; Commandes via le latch (echappement) :
;   FF FF   octet de donnees 0xFF
;   FF 00   requete d'etat (reponse seule)
;   FF 01   STOP (silence)      FF 02   PLAY (vide le tampon, demarre)
;   FF 03   PAUSE               FF 04   REPRISE
;   FF 06   voix declenchees (reponse bits 0-3 FM1-4, 4 SSG, 5 ADPCM-A, 6 ADPCM-B), puis remise a zero
;   FF 07   cri du Toasty : echantillon ADPCM-A du bloc sfxp (0x0040, rempli par le constructeur) sur la voie
;           sfxch, empruntee a la musique pendant sfxdur ticks ; sfxch >= 6 : pas de son, commande ignoree
; Voie empruntee : pendant le cri, les ecritures de la musique sur ses registres (08/10/18/20/28 + voie) sont
; retenues dans une copie (shad) et son bit est retire des declenchements / coupures (reg 0) ; a la fin, la copie
; est reecrite.  Les autres voies (FM, SSG, 5 ADPCM-A, ADPCM-B) ne sont jamais touchees.  silence (fin de piste,
; STOP) et pmute (pause) epargnent aussi la voie du cri : la musique peut changer de piste pendant le cri.
; Volume general ADPCM-A (port B reg 01) : 0 au demarrage de la puce = voies ADPCM-A muettes (niveau 31 + total 0 =
; 63 d'attenuation).  Si la musique ne l'a jamais ecrit depuis le demarrage (tlseen = 0), le cri le met a 0x3F puis
; le remet a 0 ; sinon il garde la valeur de la musique (les autres voies ADPCM-A ne changent pas de volume).
; Reponse (port 0x0C) : bit7 = bascule a chaque octet recu,
;   bit6 = 1 tant qu'une piste est en cours (y compris en pause),
;   bits 0..5 = places libres / 16
; Pause : notes FM relachees (key-off), volumes SSG a 0, ADPCM coupes, temps
; gele ; a la reprise les volumes SSG memorises sont reecrits (les notes FM
; et ADPCM repartent a leur prochain declenchement).
; ---------------------------------------------------------------------
rd:     equ 0xFC00
wr:     equ 0xFC02
wcnt:   equ 0xFC04
state:  equ 0xFC06              ; 1 = piste en cours
esc:    equ 0xFC07
tog:    equ 0xFC08
m27:    equ 0xFC09
magic:  equ 0xFC0A              ; 0xA5 une fois le driver initialise
tcnt:   equ 0xFC0C              ; compteur de ticks (diagnostic)
paused: equ 0xFC0E              ; demande de pause (NMI)
pmuted: equ 0xFC0F              ; 1 = la coupure de pause a ete faite
ssgv:   equ 0xFC10              ; 3 octets : derniers volumes SSG (regs 8..A)
vflags: equ 0xFC13              ; voix declenchees depuis la derniere requete FF 06 (vumetres)
sfxreq: equ 0xFC14              ; 1 = cri demande (NMI), joue par la boucle principale
sfxon:  equ 0xFC15              ; 1 = voie empruntee (cri en cours)
sfxend: equ 0xFC16              ; tcnt de fin du cri
shad:   equ 0xFC18              ; 5 octets : derniere valeur ecrite par la musique en 08/10/18/20/28 + voie
tlseen: equ 0xFC1D              ; 1 = la musique a ecrit le volume general ADPCM-A (port B reg 01) depuis le demarrage
tlset:  equ 0xFC1E              ; 1 = le cri a mis ce volume a 0x3F (a remettre a 0 a la fin)
stk:    equ 0xFFF0

        org 0x0000
        di
        im 1
        ld sp,stk
        jp boot
        defs 0x38-$
        jp isr
        defs 0x40-$
; bloc du cri du Toasty (0x0040), ecrit par le constructeur (ngt_studio.py, build_cart) ; par defaut : aucun son
sfxp:   defb 'S','F','X',0
sfxch:  defb 0xFF               ; voie ADPCM-A 0..5 (la moins utilisee par les albums), 0xFF = pas de son
sfxs:   defw 0                  ; adresse de debut / 256 en V-ROM
sfxe:   defw 0                  ; adresse de fin / 256 (incluse)
sfxdur: defw 0                  ; duree en ticks (32 echantillons de sortie)
        defs 0x66-$
        jp nmi

boot:   out (0x18),a
        ld hl,0xF800
        ld (rd),hl
        ld (wr),hl
        ld hl,0
        ld (wcnt),hl
        ld (ssgv),hl
        xor a
        ld (ssgv+2),a
        ld (sfxreq),a
        ld (sfxon),a
        ld (tlseen),a
        ld (tlset),a
        ld hl,shad
        ld b,5
bz1:    ld (hl),a
        inc hl
        djnz bz1
        ld (state),a
        ld (esc),a
        ld (tog),a
        ld (paused),a
        ld (pmuted),a
        ld (vflags),a
        ld a,0x15
        ld (m27),a
        call silence
        ld b,0x24
        ld c,0xF8               ; NA = 992 : un tick = 32 echantillons (0,57 ms)
        call ym_a
        ld b,0x25
        ld c,0x00
        call ym_a
        ld b,0x27
        ld c,0x15
        call ym_a
        ld a,0xA5
        ld (magic),a
        out (0x08),a
        ei
idle:   call sfxchk             ; cri du Toasty possible a l'arret aussi
        ld a,(state)
        or a
        jr z,idle
main:   call pchk
        call getb
        cp 0xC0
        jr nc,special
        ld b,a
        call getb
        ld c,a
        ld a,b
        cp 0x27
        jr nz,wa
        ld a,c
        and 0x40
        or 0x15
        ld (m27),a
        jr main
wa:     cp 0x08                 ; volumes SSG : memorises pour la reprise apres pause
        jr c,wa2
        cp 0x0B
        jr nc,wa2
        push hl
        ld hl,ssgv-8
        add a,l
        ld l,a
        jr nc,wa1
        inc h
wa1:    ld (hl),c
        pop hl
wa2:    call ym_a
        ld a,b                  ; vumetres : note FM, son SSG, depart ADPCM-B
        cp 0x28
        jr nz,wa4
        ld a,c
        and 0xF0
        jr z,main
        ld a,c
        and 7
        ld d,1
        cp 1
        jr z,wa3
        ld d,2
        cp 2
        jr z,wa3
        ld d,4
        cp 5
        jr z,wa3
        ld d,8
        cp 6
        jr nz,main
wa3:    ld a,(vflags)
        or d
        ld (vflags),a
        jp main
wa4:    ld d,0x40
        cp 0x10
        jr nz,wa5
        bit 7,c
        jr nz,wa3
        jp main
wa5:    ld d,0x10
        cp 0x08
        jp c,main
        cp 0x0B
        jp nc,main
        ld a,c
        and 0x1F
        jr nz,wa3
        jp main
special: cp 0xC0
        jr z,wb
        cp 0xC1
        jr z,d1
        cp 0xC2
        jr z,d2
        xor a                   ; C3 : fin
        ld (state),a
        jp stopped
wb:     call getb
        ld b,a
        call getb
        ld c,a
        call sfxflt             ; voie empruntee par le cri : ecriture retenue (Z) ou bit retire de C
        jr z,wb1
        call ym_b
        ld a,b                  ; vumetres : depart ADPCM-A (port B, reg 0)
        or a
        jr nz,wb1
        bit 7,c
        jr nz,wb1
        ld a,c
        and 0x3F
        jr z,wb1
        ld a,(vflags)
        or 0x20
        ld (vflags),a
wb1:    jp main
d1:     call getb
        ld e,a
        ld d,0
        jr addw
d2:     call getb
        ld e,a
        call getb
        ld d,a
addw:   di
        ld hl,(wcnt)
        add hl,de
        ld (wcnt),hl
        ei
wait:   call pchk
        ld hl,(wcnt)
        bit 7,h
        jp nz,main
        ld a,h
        or l
        jp z,main
        halt
        ld a,(state)
        or a
        jr nz,wait
stopped: ld sp,stk
        xor a
        ld (paused),a
        ld (pmuted),a
        call silence
        jp idle

; pause : coupe le son une fois, puis attend la reprise (ou un STOP)
pchk:   call sfxchk
        ld a,(paused)
        or a
        ret z
        ld a,(pmuted)
        or a
        jr nz,pc_w
        ld a,1
        ld (pmuted),a
        call pmute
pc_w:   call sfxchk
        ld a,(state)
        or a
        jr z,stopped
        ld a,(paused)
        or a
        jr nz,pc_w
        xor a                   ; reprise : volumes SSG d'avant la pause
        ld (pmuted),a
        ld b,0x08
        ld a,(ssgv)
        ld c,a
        call ym_a
        ld b,0x09
        ld a,(ssgv+1)
        ld c,a
        call ym_a
        ld b,0x0A
        ld a,(ssgv+2)
        ld c,a
        jp ym_a

pmute:  ld b,0x28               ; FM : key-off des 4 voies (relachement naturel)
        ld c,0x01
        call ym_a
        ld c,0x02
        call ym_a
        ld c,0x05
        call ym_a
        ld c,0x06
        call ym_a
        ld c,0
        ld b,0x08               ; SSG : volume 0
        call ym_a
        ld b,0x09
        call ym_a
        ld b,0x0A
        call ym_a
        call sx_cut             ; ADPCM-A : coupe les 6 voies (sauf celle du cri en cours)
        ld b,0x10
        ld c,0x01               ; ADPCM-B : reset puis arret
        call ym_a
        ld c,0x00
        jp ym_a

; A <- octet suivant du tampon (bloquant) ; conserve BC DE HL
getb:   push hl
        push de
gb_l:   ld hl,(rd)
        ld de,(wr)
        ld a,l
        cp e
        jr nz,gb_ok
        ld a,h
        cp d
        jr nz,gb_ok
        ld a,(state)
        or a
        jr nz,gb_l
        pop de
        pop hl
        jp stopped
gb_ok:  ld a,(hl)
        inc hl
        ld e,a
        ld a,h
        cp 0xFC
        jr nz,gb_s
        ld h,0xF8
gb_s:   ld (rd),hl
        ld a,e
        pop de
        pop hl
        ret

; ecritures YM (B=registre, C=valeur) ; l'ISR ne doit pas s'intercaler
ym_a:   di
ya1:    in a,(4)
        or a
        jp m,ya1
        ld a,b
        out (4),a
        ld a,c
        out (5),a
        ei
        ret
ym_b:   di
yb1:    in a,(4)
        or a
        jp m,yb1
        ld a,b
        out (6),a
        ld a,c
        out (7),a
        ei
        ret

silence: ld b,7
        ld c,0x3F
        call ym_a
        ld b,8
        ld c,0
        call ym_a
        ld b,9
        call ym_a
        ld b,0x0A
        call ym_a
        ld b,0x80
sl1:    ld c,0xFF               ; SL=15 RR=15 : relachement immediat
        call ym_a
        call ym_b
        inc b
        ld a,b
        cp 0x90
        jr nz,sl1
        ld b,0x28
        ld c,0x00
        call ym_a
        ld c,0x01
        call ym_a
        ld c,0x02
        call ym_a
        ld c,0x05
        call ym_a
        ld c,0x06
        call ym_a
        call sx_cut             ; ADPCM-A : coupe les 6 voies (sauf celle du cri en cours)
        ld b,0x10
        ld c,0x01               ; ADPCM-B : reset (bit 0 ; le bit 7 = START relancerait le dernier echantillon)
        call ym_a
        ld c,0x00
        call ym_a
        ret

; cri du Toasty : depart demande (FF 07) ou fin de l'emprunt de la voie ; conserve BC DE HL
sfxchk: push bc
        push de
        push hl
        ld a,(sfxreq)
        or a
        jr z,sx_t
        xor a
        ld (sfxreq),a
        ld a,(sfxch)
        cp 6
        jp nc,sx_x              ; pas de son dans cette cartouche
        call sx_bit             ; D = bit de la voie
        ld b,0
        ld a,d
        or 0x80
        ld c,a
        call ym_b               ; coupe la note de la musique sur cette voie
        ld a,(sfxch)
        add a,0x08
        ld b,a
        ld c,0xDF               ; gauche + droite, niveau 31
        call ym_b
        ld hl,sfxs
        ld e,4                  ; debut lo / hi (10, 18 + voie), fin lo / hi (20, 28 + voie)
sx_w:   ld a,b
        add a,8
        ld b,a
        ld c,(hl)
        call ym_b
        inc hl
        dec e
        jr nz,sx_w
        ld a,(tlseen)           ; volume general ADPCM-A jamais ecrit par la musique : 0 = muet -> 0x3F le temps du cri
        or a
        jr nz,sx_v
        ld b,0x01
        ld c,0x3F
        call ym_b
        ld a,1
        ld (tlset),a
sx_v:   ld b,0
        ld c,d
        call ym_b               ; depart
        ld a,1
        ld (sfxon),a
        di
        ld hl,(tcnt)
        ei
        ld de,(sfxdur)
        add hl,de
        ld (sfxend),hl
        jr sx_x
sx_t:   ld a,(sfxon)
        or a
        jr z,sx_x
        di
        ld hl,(tcnt)
        ei
        ld de,(sfxend)
        or a
        sbc hl,de
        bit 7,h
        jr nz,sx_x              ; pas encore fini
        xor a
        ld (sfxon),a
        ld a,(sfxch)            ; voie rendue : registres de la musique reecrits (08, 10, 18, 20, 28 + voie)
        add a,0x08
        ld b,a
        ld hl,shad
        ld e,5
sx_r:   ld c,(hl)
        call ym_b
        inc hl
        ld a,b
        add a,8
        ld b,a
        dec e
        jr nz,sx_r
        ld a,(tlset)
        or a
        jr z,sx_x
        xor a
        ld (tlset),a
        ld a,(tlseen)           ; la musique l'a ecrit entre-temps : sa valeur est deja en place
        or a
        jr nz,sx_x
        ld b,0x01
        ld c,0
        call ym_b
sx_x:   pop hl
        pop de
        pop bc
        ret

; reg 0 = 0xBF (coupe les 6 voies ADPCM-A), sans la voie du cri s'il est en cours ; modifie A B C D
sx_cut: ld b,0
        ld c,0xBF
        ld a,(sfxon)
        or a
        jp z,ym_b
        call sx_bit
        ld a,d
        cpl
        and c
        ld c,a
        jp ym_b

; D <- 1 << sfxch (modifie A)
sx_bit: ld a,(sfxch)
        ld d,1
        or a
        ret z
sx_b1:  sla d
        dec a
        jr nz,sx_b1
        ret

; ecriture port B de la musique (B = registre, C = valeur) face a la voie du cri :
; copie tenue a jour ; pendant le cri -> Z = ne pas ecrire, ou NZ avec le bit de la voie retire de C (reg 0)
sfxflt: push de
        push hl
        ld a,(sfxch)
        cp 6
        jr nc,sf_ok             ; pas de son : tout passe
        ld e,a
        ld a,b
        or a
        jr z,sf_key
        cp 1                    ; volume general ADPCM-A : ecrit par la musique (toujours transmis)
        jr nz,sf0
        ld a,1
        ld (tlseen),a
        jr sf_ok
sf0:    ld a,b
        sub e                   ; registre - voie : 8, 16, 24, 32, 40 -> copie 0..4
        jr c,sf_ok
        ld d,a
        and 7
        jr nz,sf_ok
        ld a,d
        cp 8
        jr c,sf_ok
        cp 41
        jr nc,sf_ok
        rrca
        rrca
        rrca
        dec a
        ld hl,shad
        add a,l
        ld l,a
        jr nc,sf1
        inc h
sf1:    ld (hl),c
        ld a,(sfxon)
        or a
        jr z,sf_ok
        xor a                   ; Z : retenue pendant le cri
        jr sf_x
sf_key: ld a,(sfxon)
        or a
        jr z,sf_ok
        call sx_bit
        ld a,d
        cpl
        and c
        ld c,a                  ; voie retiree du declenchement / de la coupure
        and 0x3F                ; Z si plus aucune voie concernee
        jr sf_x
sf_ok:  or 1                    ; NZ : ecrire
sf_x:   pop hl
        pop de
        ret

; Timer A du YM2610 : un tick tous les 32 echantillons (NA = 992)
isr:    push af
        push hl
is1:    in a,(4)
        or a
        jp m,is1
        ld a,0x27
        out (4),a
        ld a,(m27)
        out (5),a
        ld hl,(tcnt)            ; compteur de ticks (diagnostic)
        inc hl
        ld (tcnt),hl
        ld a,(paused)           ; en pause : le temps est gele
        or a
        jr nz,is3
        ld hl,(wcnt)
        bit 7,h
        jr z,is2
        ld a,h
        cp 0xFC
        jr c,is3                ; trop negatif : on ne descend plus
is2:    dec hl
        ld (wcnt),hl
is3:    pop hl
        pop af
        ei
        reti

; NMI : commande / donnee du 68000
nmi:    push af
        ld a,(magic)
        cp 0xA5
        jr z,nmi_ok
        in a,(0)                ; premier contact apres la bascule sm1 -> M1 (commande 3 du BIOS) :
        ld a,0x80               ; on accuse et on demarre le driver (le Z80 tournait encore dans la
        out (0x0C),a            ; boucle RAM du BIOS)
        di
        ld sp,stk
        jp boot
nmi_ok: push bc
        push de
        push hl
        in a,(0)
        ld b,a
        ld a,(esc)
        or a
        jr nz,n_esc
        ld a,b
        cp 0xFF
        jr nz,n_data
        ld a,1
        ld (esc),a
        jr n_rep
n_esc:  xor a
        ld (esc),a
        ld a,b
        cp 0xFF
        jr z,n_data
        cp 1
        jr nz,n_play
        xor a                   ; STOP
        ld (state),a
        ld (paused),a
        jr n_rep
n_play: cp 2
        jr nz,n_pau
        ld hl,(wr)              ; PLAY
        ld (rd),hl
        ld hl,0
        ld (wcnt),hl
        xor a
        ld (paused),a
        ld a,1
        ld (state),a
        jr n_rep
n_pau:  cp 3
        jr nz,n_res
        ld a,1                  ; PAUSE
        ld (paused),a
        jr n_rep
n_res:  cp 6
        jr nz,n_rs2
        ld a,(vflags)           ; FF 06 : voix declenchees, puis remise a zero
        and 0x7F
        ld b,a
        xor a
        ld (vflags),a
        jr n_r2
n_rs2:  cp 4
        jr nz,n_rs3
        xor a                   ; REPRISE
        ld (paused),a
        jr n_rep
n_rs3:  cp 7
        jr nz,n_rep
        ld a,1                  ; CRI DU TOASTY : joue par la boucle principale (le NMI n'ecrit jamais dans le YM)
        ld (sfxreq),a
        jr n_rep
n_data: ld hl,(wr)
        ld (hl),b
        inc hl
        ld a,h
        cp 0xFC
        jr nz,n_w
        ld h,0xF8
n_w:    ld (wr),hl
n_rep:  ld hl,(rd)              ; places libres = (rd - wr - 1) & 0x3FF, en unites de 16
        ld de,(wr)
        or a
        sbc hl,de
        dec hl
        ld a,h
        and 3
        rlca
        rlca
        rlca
        rlca
        ld b,a                  ; bits 9..8 -> bits 5..4
        ld a,l
        rrca
        rrca
        rrca
        rrca
        and 0x0F                ; bits 7..4 -> bits 3..0
        or b
        ld b,a
        ld a,(state)
        or a
        jr z,n_r2
        set 6,b
n_r2:   ld a,(tog)
        xor 0x80
        ld (tog),a
        or b
        out (0x0C),a
        pop hl
        pop de
        pop bc
        pop af
        retn
