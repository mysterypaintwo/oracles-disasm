.include "include/constants.s"
.include "include/macros.s"
.include "include/rominfo.s"
.include "include/musicMacros.s"

.BANK $39 SLOT 1
.ORG 0

m_section_superfree AudioCode NAMESPACE audio

;;
b39_initSound:
	jp initSound

;;
b39_updateSound:
	jp updateSound

;;
; @param	a	Sound to play
b39_playSound:
	jp playSound

;;
b39_stopSound:
	jp stopSound

;;
; Unused? (The address it jumps too doesn't seem like it would do anything useful...)
func_39_400c:
	pop af
	jp $4d3e

;;
; @param	a	Volume (0-3)
b39_updateMusicVolume:
	jp updateMusicVolume


; This is pointless?
.dw musNone


;;
initSound:
	ldh (<hSoundDataBaseBank),a
	call stopSound
	ld a,$03
	ld (wMusicVolume),a
	ld a,$00
	ld (wSoundFadeDirection),a
	ld (wSoundFadeCounter),a
	ld (wSoundDisabled),a
	ld (wc023),a
	ld a,$8f
	ld ($ff00+R_NR52),a
	ld a,$77
	ld (wSoundVolume),a
	ld ($ff00+R_NR50),a
	ld a,$ff
	ld ($ff00+R_NR51),a
	ld c,@readFunctionEnd-@readFunction+2
	ld hl,@readFunction
	ld de,wMusicReadFunction
-
	ldi a,(hl)
	ld (de),a
	inc de
	dec c
	jr nz,-
	ret

; This function is copied to wMusicReadFunction and executed there.
@readFunction:
	ldh (<hSoundDataBaseBank2),a
	ld ($2000),a
	ldi a,(hl)
	ld c,a
	ldh a,(<hSoundDataBaseBank)
	ldh (<hSoundDataBaseBank2),a
	ld ($2000),a
	ld a,c
	ret
	ret
	ret
@readFunctionEnd:


;;
; @param	a	Volume (0-3)
;
updateMusicVolume:
	push bc
	push de
	push hl
	push af
	call @updateSquareChannelVolumes

	pop af
	ld (wMusicVolume),a
	cp $00
	jr nz,+

	ld a,$01
	jr ++
+
	ld a,$00
++
	ld (wc023),a
	pop hl
	pop de
	pop bc
	ret

;;
@updateSquareChannelVolumes:
	; Update square 1's volume
	ld a,$00
	ld (wSoundChannel),a
	ld hl,wChannelsEnabled
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	cp $00
	jr z,+
	call updateChannelStuff
+
	; Update square 2's volume
	ld a,$01
	ld (wSoundChannel),a
	ld hl,wChannelsEnabled
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	cp $00
	jr z,+
	call updateChannelStuff
+
	ret

;;
stopSound:
	ld a,$00
-
	ld (wSoundChannel),a
	call channelCmdff
	ld a,(wSoundChannel)
	inc a
	cp $08
	jr nz,-
	ret

;;
func_39_40b9:
	ld a,$00
-
	ld (wSoundChannel),a
	call updateChannelStuff
	ld a,(wSoundChannel)
	inc a
	cp $08
	jr nz,-
	ret

;;
; Disable all sound effect channels
;
stopSfx:
	; Square 1
	ld a,$02
	ld (wSoundChannel),a
	ld hl,wChannelsEnabled
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	cp $00
	jr z,+
	call channelCmdff
+
	; Square 2
	ld a,$03
	ld (wSoundChannel),a
	ld hl,wChannelsEnabled
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	cp $00
	jr z,+
	call channelCmdff
+
	; Wave
	ld a,$05
	ld (wSoundChannel),a
	ld hl,wChannelsEnabled
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	cp $00
	jr z,+
	call channelCmdff
+
	; Noise
	ld a,$07
	ld (wSoundChannel),a
	ld hl,wChannelsEnabled
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	cp $00
	jr z,+
	call channelCmdff
+
	ret

;;
updateSound:
	push bc
	push de
	push hl
	ld a,(wSoundDisabled)
	cp $00
	jr z,+
	jp @ret
+
	ld a,(wSoundVolume)
	ld ($ff00+R_NR50),a
	ld a,(wSoundFadeDirection)
	cp $00
	jr z,@updateChannels

	ld a,(wSoundFadeSpeed)
	ld b,a
	ld a,(wSoundFadeCounter)
	inc a
	ld (wSoundFadeCounter),a
	and b
	cp b
	jr nz,@updateChannels

	ld a,(wSoundFadeDirection)
	cp $0a
	jr z,@incVolume

@decVolume:
	ld a,(wSoundVolume)
	cp $00
	jr z,@stopSound

	sub $11
	ld (wSoundVolume),a
	jp @updateChannels

@incVolume:
	ld a,(wSoundVolume)
	cp $77
	jr z,@clearFadeVariables

	add $11
	ld (wSoundVolume),a
	jp @updateChannels

@stopSound:
	call stopSound

@clearFadeVariables:
	ld a,$00
	ld (wSoundFadeCounter),a
	ld (wSoundFadeDirection),a

@updateChannels:
	ld a,$00
@channelLoop:
	ld (wSoundChannel),a
	ld hl,wChannelsEnabled
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	cp $00
	jr z,@nextChannel

	ld hl,wChannelWaitCounters
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	cp $00
	jr nz,+

	call doNextChannelCommand
	jr @nextChannel
+
	call func_39_41c2
@nextChannel:
	ld a,(wSoundChannel)
	inc a
	cp $08
	jr nz,@channelLoop

	ld a,(wc023)
	cp $01
	jr nz,@ret

	ld a,$02
	ld (wc023),a

@ret:
	pop hl
	pop de
	pop bc
	ret

;;
func_39_41c2:
	ld hl,wChannelWaitCounters
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	dec a
	ld (hl),a
	ld a,(wSoundChannel)
	cp $06
	jr nc,@ret

	ld hl,wc039
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	and $40
	jr nz,@ret
	ld a,(wSoundChannel)
	cp $05
	jr nc,+
	call func_39_464c
+
	call func_39_41f3
@ret:
	ret

;;
func_39_41f3:
	ld hl,wc03f
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	ld c,a
	and $7f
	jr z,label_39_024

	ld a,c
	and $80
	jr nz,+

	ld d,$00
	jr ++
+
	ld d,$ff
++
	push de
	ld hl,wc03f
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	pop de
	ld e,a
	ld a,(wSoundChannel)
	sla a
	ld b,a
	ld a,b
	add <hSoundData3
	ld c,a
	ld a,($ff00+c)
	inc c
	ld l,a
	ld a,($ff00+c)
	inc c
	ld h,a
	add hl,de
	ld a,(wSoundChannel)
	sla a
	ld b,a
	ld a,l
	ld c,<hSoundData3
	call writeIndexedHighRamAndIncrement
	ld a,h
	ld ($ff00+c),a
	inc c
label_39_024:
	ld hl,wc045
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	and $10
	jr nz,label_39_026

	ld hl,wc051
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	cp $00
	jr z,label_39_025

	dec a
	ld hl,wc051
	push af
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	pop af
	ld (hl),a
	ld hl,$0000
	jp func_42d1

label_39_025:
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	ld hl,wc045
	add hl,de
	ld (hl),$10
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	ld hl,wc051
	add hl,de
	ld (hl),$00
label_39_026:
	ld hl,wc051
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	cp $08
	jr nz,label_39_027

	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	ld hl,wc051
	add hl,de
	ld (hl),$00
	ld a,$00
label_39_027:
	ld hl,data_4b40
	call readWordFromTable
	push hl
	ld hl,wc051
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	inc a
	ld (hl),a
	ld hl,wChannelVibratos
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	and $0f
	pop hl
	call func_39_4a10

;;
func_42d1:
	ld a,(wSoundChannel)
	sla a
	ld b,a
	ld a,b
	add $f2
	ld c,a
	ld a,($ff00+c)
	inc c
	ld e,a
	ld a,($ff00+c)
	inc c
	ld d,a
	add hl,de
	ld a,l
	ld (wSoundFrequencyL),a
	ld a,h
	ld (wSoundFrequencyH),a

;;
func_42ea:
	ld a,(wSoundChannel)
	scf
	ccf
	cp $04
	jr nc,label_39_029

	cp $02
	jr nc,label_39_028

	inc a
	inc a
	ld e,a
	ld hl,wChannelsEnabled
	ld d,$00
	add hl,de
	ld a,(hl)
	cp $00
	jr z,label_39_028
	ret

label_39_028:
	ld a,(wSoundChannel)
	and $01
	ld b,a
	sla a
	sla a
	add b
	ld b,a
	push bc
	ld a,(wSoundFrequencyL)
	ld c,R_NR13
	call writeIndexedHighRamAndIncrement
	ld a,(wSoundCmdEnvelope)
	ld e,a
	ld a,(wSoundFrequencyH)
	or e
	ld ($ff00+c),a
	inc c
	pop bc
	push bc
	ld hl,wChannelDutyCycles
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	pop bc
	ld c,$11
	call writeIndexedHighRamAndIncrement
	ret

label_39_029:
	call func_39_434b
	cp $00
	jr nz,label_39_030
	ld a,l
	ld ($ff00+R_NR33),a
	ld a,h
	ld ($ff00+R_NR34),a
	ld a,$00
	ld ($ff00+R_NR31),a
label_39_030:
	ret

;;
; @param[out]	a	0 or 1 (something about whether wSoundChannel can be active?)
func_39_434b:
	ld a,(wSoundChannel)
	cp $05
	jr z,@zero

	ld a,(wChannelsEnabled+5)
	cp $00
	jr nz,@one

	ld a,(wc023)
	cp $02
	jr z,@one
@zero:
	ld a,$00
	ret
@one:
	ld a,$01
	ret

;;
getNextChannelByte:
	push bc
	push de
	push hl
	ld a,(wSoundChannel)
	sla a
	add <hSoundChannelAddresses
	ld c,a
	ld a,($ff00+c)
	inc c
	ld l,a
	ld a,($ff00+c)
	ld h,a
	ld a,(wSoundChannel)
	add <hSoundChannelBanks
	ld c,a
	ld a,($ff00+c)
	inc c
	call wMusicReadFunction
	push af
	ld a,(wSoundChannel)
	sla a
	ld b,a
	ld a,l
	ld c,<hSoundChannelAddresses
	call writeIndexedHighRamAndIncrement
	ld a,h
	ld ($ff00+c),a
	inc c
	pop af
	pop hl
	pop de
	pop bc
	ret

;;
doNextChannelCommand:
	call getNextChannelByte
	scf
	ccf
	cp $f0
	jr nc,@cmdf0Toff

	scf
	ccf
	cp $e0
	jr c,+
	jp cmde0Toef
+
	scf
	ccf
	cp $d0
	jr c,+
	jp cmdVolume
+
	ld (wSoundCmd),a
	jp standardSoundCmd

@cmdf0Toff:
	ld e,a
	ld a,$ff
	sub e
	ld hl,@table
	call readWordFromTable
	jp hl

@table:
	.dw channelCmdff
	.dw channelCmdfe
	.dw channelCmdfd
	.dw channelCmdff
	.dw channelCmdff
	.dw channelCmdff
	.dw channelCmdf9
	.dw channelCmdf8
	.dw channelCmdff
	.dw channelCmdf6
	.dw channelCmdf5
.ifdef BUILD_VANILLA
	.dw channelCmdff
.else
	.dw channelCmdf4
.endif
	.dw channelCmdf3
	.dw channelCmdf2
	.dw channelCmdf1
	.dw channelCmdf0

;;
channelCmdf2:
	jp doNextChannelCommand

.ifndef BUILD_VANILLA
;;
; setDefaultLength $len -- sets wChannelDefaultLength[ch], used by short notes ($62-$c1
; in @channel0To3/standardCmdChannels4To5/standardCmdChannel6) whenever they omit an
; explicit length byte.
channelCmdf4:
	call getNextChannelByte
	ld hl,wChannelDefaultLength
	push af
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	pop af
	ld (hl),a
	jp doNextChannelCommand
.endif

.ifdef BUILD_VANILLA
;;
channelCmdf1:
	jp doNextChannelCommand
;;
channelCmdf3:
	jp doNextChannelCommand
.else
; Channel -> pattern-call-slot lookup (indexed by wSoundChannel 0-7). Only the 4 music
; channels (square 1/2, wave, noise) get pattern-call RAM slots -- sfx are short one-shots
; that don't benefit, and RAM here is scarce. $ff marks a channel with no slot; using
; patternCall/patternEnd on one of those channels is undefined (mml2wla must never emit
; it there).
patternChannelSlotTable:
	.db $00 $01 $ff $ff $02 $ff $03 $ff

;;
; patternCall $addrLo $addrHi $count -- jumps the channel's read cursor to $addr, having
; first remembered where to come back to (the address right after this instruction) and
; how many times total to play the pattern before returning. Pairs with patternEnd,
; placed at the end of the pattern body. Not nestable: a pattern must not itself contain
; a patternCall, since there's only one RAM slot per channel, not a call stack.
channelCmdf1:
	call getNextChannelByte
	ld c,a                  ; c = pattern address, low byte
	call getNextChannelByte
	ld b,a                  ; b = pattern address, high byte (bc = pattern start address)
	call getNextChannelByte
	ld e,a                  ; e = repeat count
	push bc                 ; stash the pattern start address for later

	; d = slot = patternChannelSlotTable[wSoundChannel]
	ld a,(wSoundChannel)
	ld hl,patternChannelSlotTable
	ld c,a
	ld b,$00
	add hl,bc
	ld d,(hl)

	; wPatternRepeatRemaining[slot] = count
	ld hl,wPatternRepeatRemaining
	ld c,d
	ld b,$00
	add hl,bc
	ld (hl),e

	; wPatternReturnAddr[slot] = current read cursor (already past this instruction --
	; this is exactly where execution should resume once the pattern finishes repeating)
	ld a,(wSoundChannel)
	sla a
	add <hSoundChannelAddresses
	ld c,a
	ld a,($ff00+c)
	ld l,a
	inc c
	ld a,($ff00+c)
	ld h,a                  ; hl = current hSoundChannelAddresses[ch]

	ld a,d
	sla a                   ; a = slot*2 (word array index)
	ld c,a
	ld b,$00
	push hl                 ; stash the return address value
	ld hl,wPatternReturnAddr
	add hl,bc
	pop de                  ; de = return address value
	ld a,e
	ld (hl),a
	inc hl
	ld a,d
	ld (hl),a

	; hSoundChannelAddresses[ch] = pattern start address (stashed on the stack above)
	pop hl
	ld a,(wSoundChannel)
	sla a
	ld b,a
	ld a,l
	ld c,<hSoundChannelAddresses
	call writeIndexedHighRamAndIncrement
	ld a,h
	ld ($ff00+c),a
	inc c
	jp doNextChannelCommand

;;
; patternEnd $addrLo $addrHi -- placed at the end of a pattern body. $addr is the
; pattern's own start address (a cheap redundant copy of patternCall's target, so no
; extra RAM is needed to remember it). Decrements the repeat counter; if still nonzero,
; loops the read cursor back to $addr; once it hits zero, resumes at the address
; patternCall originally remembered.
channelCmdf3:
	call getNextChannelByte
	ld c,a                  ; c = pattern start address, low byte
	call getNextChannelByte
	ld b,a                  ; b = pattern start address, high byte
	push bc                 ; stash it in case we need to loop back to it

	; e = slot = patternChannelSlotTable[wSoundChannel]
	ld a,(wSoundChannel)
	ld hl,patternChannelSlotTable
	ld c,a
	ld b,$00
	add hl,bc
	ld e,(hl)

	; if --wPatternRepeatRemaining[slot] != 0, loop back to the pattern start
	ld hl,wPatternRepeatRemaining
	ld c,e
	ld b,$00
	add hl,bc
	ld a,(hl)
	dec a
	ld (hl),a
	cp $00
	jr z,@returnFromPattern

	pop hl                  ; hl = pattern start address
	ld a,(wSoundChannel)
	sla a
	ld b,a
	ld a,l
	ld c,<hSoundChannelAddresses
	call writeIndexedHighRamAndIncrement
	ld a,h
	ld ($ff00+c),a
	inc c
	jp doNextChannelCommand

@returnFromPattern:
	pop bc                  ; discard the pattern start address, not needed anymore
	ld hl,wPatternReturnAddr
	ld a,e
	sla a                   ; a = slot*2 (word array index)
	ld c,a
	ld b,$00
	add hl,bc
	ld e,(hl)
	inc hl
	ld d,(hl)                ; de = wPatternReturnAddr[slot]
	ld a,(wSoundChannel)
	sla a
	ld b,a
	ld a,e
	ld c,<hSoundChannelAddresses
	call writeIndexedHighRamAndIncrement
	ld a,d
	ld ($ff00+c),a
	inc c
	jp doNextChannelCommand
.endif

;;
; Vibrato
;
channelCmdf9:
	ld a,(wSoundChannel)
	scf
	ccf
	cp $06
	jr nc,++

	call getNextChannelByte
	ld hl,wChannelVibratos
	push af
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	pop af
	ld (hl),a
	jp doNextChannelCommand

;;
channelCmdf8:
	ld a,(wSoundChannel)
	scf
	ccf
	cp $06
	jr nc,++

	call getNextChannelByte
	ld hl,wc03f
	push af
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	pop af
	ld (hl),a
	jp doNextChannelCommand

;;
channelCmdfd:
	ld a,(wSoundChannel)
	scf
	ccf
	cp $06
	jr nc,++

	call getNextChannelByte
	ld hl,wChannelPitchShift
	push af
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	pop af
	ld (hl),a
	jp doNextChannelCommand
++
	call getNextChannelByte
	jp doNextChannelCommand

;;
cmde0Toef:
	and $0f
	ld hl,wChannelEnvelopes
	push af
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	pop af
	ld (hl),a
	call getNextChannelByte
	and $07
	ld hl,wChannelEnvelopes2
	push af
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	pop af
	ld (hl),a
	jp doNextChannelCommand

;;
channelCmdf0:
	ld a,(wSoundChannel)
	cp $07
	jr z,label_39_038
.ifndef BUILD_VANILLA
	cp $06 ; also allow raw NR42 writes on the music noise channel, not just sfx (7);
	       ; confirmed unused by any vanilla music channel 6 data (bank $39 has no free
	       ; space in the vanilla ROM to carry this unconditionally)
	jr z,label_39_038
.endif

	call getNextChannelByte
	push af
	and $3f
	jr z,label_39_037

	pop af
	ld hl,wChannelDutyCycles
	push af
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	pop af
	ld (hl),a
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	ld hl,wc039
	add hl,de
	ld (hl),$41
	jp doNextChannelCommand
label_39_037:
	pop af
	and $c0
	ld hl,wChannelDutyCycles
	push af
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	pop af
	ld (hl),a
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	ld hl,wc039
	add hl,de
	ld (hl),$01
	jp doNextChannelCommand
label_39_038:
	call getNextChannelByte
	ld ($ff00+R_NR42),a
	ld a,$00
	ld ($ff00+R_NR41),a
	ld a,$80
	ld ($c01c),a
	jp doNextChannelCommand

; Command $d0 to $df
cmdVolume:
	push af
	ld a,(wSoundChannel)
	cp $04
	jr z,@next

	pop af
	and $0f
	ld hl,wChannelVolumes
	push af
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	pop af
	ld (hl),a
	jp doNextChannelCommand

@next:
	pop af
	jp doNextChannelCommand

;;
channelCmdf6:
	ld a,(wSoundChannel)
	cp $04
	jr z,@wave

	cp $05
	jr z,@wave

	call getNextChannelByte
	and $03
	swap a
	sla a
	sla a
	ld hl,wChannelDutyCycles
	push af
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	pop af
	ld (hl),a
	jp doNextChannelCommand

@wave:
	call getNextChannelByte
	ld hl,wChannelDutyCycles
	push af
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	pop af
	ld (hl),a
	ld (wWaveformIndex),a
	call setWaveform
	jp doNextChannelCommand

;;
; release $len -- decays the currently playing note from its current volume at a fixed
; fast hardware envelope pace, instead of cutting it off immediately like the (fixed)
; `rest` command now does. This is exactly the original, pre-fix `rest` command's
; behavior, byte for byte -- it turns out that was the *dominant* use of `rest` across
; existing vanilla content (roughly 90% of occurrences had no decay envelope already
; running when `rest` fired, meaning `rest`'s accidental decay-from-current-volume *was*
; the intended note-release effect, not an edge case), so it's kept available under its
; own opcode rather than dropped, both to let existing content keep sounding the same
; with new bytes and as a genuine new authoring option (a soft/decaying release,
; distinct from a hard `rest` cutoff or a `sust` hold). Square channels only (0-3) --
; a no-op elsewhere, since the original behavior only ever existed in their dispatch.
channelCmdf5:
	; No channel-range guard: every emitter of this opcode (the vanilla-data conversion
	; and dumpMusic.py) only ever targets square channels 0-3, and bank $39 has no spare
	; bytes in the vanilla build for a safety check nothing here actually needs.
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	ld hl,wc05d
	add hl,de
	ld (hl),$02
	call getChannelVolume
	sla a
	sla a
	sla a
	sla a
	or $01
	ld (wSoundCmdEnvelope),a
	call updateChannelVolume
	call func_39_41f3
	jp setChannelWaitCounter

;;
standardSoundCmd:
	ld a,(wSoundChannel)
	ld hl,@table
	call readWordFromTable
	jp hl

@table:
	.dw @channel0To3
	.dw @channel0To3
	.dw @channel0To3
	.dw @channel0To3
	.dw standardCmdChannels4To5
	.dw standardCmdChannels4To5
	.dw standardCmdChannel6
	.dw standardCmdChannel7

@channel0To3:
	ld hl,wc039
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	cp $00
	jr z,+

	call getNextChannelByte
	ld l,a
	ld a,(wSoundCmd)
	ld h,a
	jp @cmdUnknown
+
	ld a,(wSoundCmd)
	cp $60
	jr z,@cmd60

	cp $61
	jr z,@cmd61

.ifndef BUILD_VANILLA
	; Short note ($62-$c1): plays pitch (byte-$62) using the channel's stored default
	; length instead of reading an explicit length byte -- 1 byte total instead of 2.
	; Confirmed unused by any vanilla song. $62-$c1 covers the full 0-95 pitch range
	; with headroom before $d0 (volume commands).
	cp $62
	jr c,@notShortNote
	cp $c2
	jr nc,@notShortNote
	sub $62
	ld (wSoundCmd),a
	ld a,$01
	ld (wUseChannelDefaultLength),a
@notShortNote:
.endif
	jp @cmdFrequency

@cmd60:
	ld hl,wChannelEnvelopes2
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	cp $00
	jr nz,@cmd61

	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	ld hl,wc05d
	add hl,de
	ld (hl),$02
	ld a,$08 ; volume 0, no envelope stepping: immediate, clean, permanent silence,
	         ; instead of the old fast-decay-from-current-volume (which could sound like
	         ; it never actually cuts off if another command retriggers the channel again
	         ; before the decay finishes -- see the mml2wla documentation's "rest blip"
	         ; writeup, and the reason it recommends against chaining bare `rest`s)
	ld (wSoundCmdEnvelope),a
	call updateChannelVolume
	call func_39_41f3
@cmd61:
	jp setChannelWaitCounter

@cmdFrequency:
	ld a,(wSoundCmd)
	sub $0c
	ld hl,soundFrequencyTable
	call readWordFromTable
@cmdUnknown:
	call setSoundFrequency
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	ld hl,wc05d
	add hl,de
	ld (hl),$00
	call func_39_464c
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	ld hl,wc045
	add hl,de
	ld (hl),$00
	ld a,$00
	ld hl,wChannelVibratos
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	and $f0
	srl a
	srl a
	srl a
	ld hl,wc051
	push af
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	pop af
	ld (hl),a
	call func_42ea
;;
; Read a byte, set the channel wait counter to the value -- unless a short note (see
; the $62-$c1 dispatch in @channel0To3) set wUseChannelDefaultLength, in which case the
; "byte" comes from wChannelDefaultLength[ch] instead of the channel data stream.
setChannelWaitCounter:
.ifndef BUILD_VANILLA
	ld a,(wUseChannelDefaultLength)
	cp $00
	jr z,@readLengthByte
	xor a
	ld (wUseChannelDefaultLength),a
	ld hl,wChannelDefaultLength
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	jr @gotLength
@readLengthByte:
.endif
	call getNextChannelByte
@gotLength:
	dec a
	ld hl,wChannelWaitCounters
	push af
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	pop af
	ld (hl),a
	ret

;;
func_39_4609:
	ld hl,data_4ad0
	ld a,b
	sla a
	sla a
	sla a
	add c
	ld d,$00
	ld e,a
	add hl,de
	ld a,(hl)
	ret

;;
; Sends wSoundFrequency to given value plus value in table at wChannelPitchShift.
setSoundFrequency:
	push hl
	ld hl,wChannelPitchShift
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	ld d,a
	sla d
	jr c,+

	ld d,$00
	jr ++
+
	ld d,$ff
++
	ld e,a
	pop hl
	add hl,de
	ld a,(wSoundChannel)
	sla a
	ld b,a
	ld a,l
	ld c,<hSoundData3
	call writeIndexedHighRamAndIncrement
	ld a,h
	ld ($ff00+c),a
	inc c
	ld a,l
	ld (wSoundFrequencyL),a
	ld a,h
	ld (wSoundFrequencyH),a
	ret

;;
func_39_464c:
	ld a,(wSoundChannel)
	cp $04
	jr nz,+
	jp func_39_4766
+
	ld hl,wc05d
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	cp $00
	jr z,label_39_047

	cp $01
	jr z,label_39_048

	ld a,$00
	ld (wSoundCmdEnvelope),a
	ret
label_39_047:
	ld hl,wChannelEnvelopes
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	cp $00
	jr z,label_39_049

.ifndef BUILD_VANILLA
	bit 3,a
	jr nz,hardwareAttackEnvelope
.endif

	ld c,a
	or $18
	ld (wSoundCmdEnvelope),a
	push bc
	call getChannelVolume
	pop bc
	ld b,a
	call func_39_4609
	ld hl,wc061
	push af
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	pop af
	ld (hl),a
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	ld hl,wc05d
	add hl,de
	ld (hl),$01
	jp updateChannelVolume

;;
; True hardware envelope fade-in (attack param had bit 3 set, i.e. an $e8-$ef `env`
; command instead of $e0-$e7). Unlike the software-simulated ramp above -- which always
; starts at volume 1 and snaps to the target volume after a fixed table-driven delay --
; this triggers one real hardware envelope (initial volume 0, direction increase, pace
; from the low 3 bits) and lets it run to completion entirely in hardware, exactly like
; the decay path below (label_39_049), just increasing from 0 instead of decreasing from
; the target. Only compiled into the editable build (see the .ifndef BUILD_VANILLA guard
; on the branch to this label above) -- bank $39 has no free space in the vanilla ROM,
; and vanilla song data never uses this (env's attack param never has bit 3 set there).
.ifndef BUILD_VANILLA
hardwareAttackEnvelope:
	and $07
	or $08
	ld (wSoundCmdEnvelope),a
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	ld hl,wc05d
	add hl,de
	ld (hl),$02
	jp updateChannelVolume
.endif

label_39_048:
	ld hl,wc061
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	cp $00
	jr z,label_39_049

	ld hl,wc061
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	dec a
	ld (hl),a
	ld a,$00
	ld (wSoundCmdEnvelope),a
	ret

label_39_049:
	ld hl,wChannelEnvelopes2
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	cp $00
	jr nz,+

	ld a,$02
	jr ++
+
	ld a,$03
++
	ld hl,wc05d
	push af
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	pop af
	ld (hl),a
	call getChannelVolume
	sla a
	sla a
	sla a
	sla a
	ld (wSoundCmdEnvelope),a
	ld hl,wChannelEnvelopes2
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	ld c,a
	ld a,(wSoundCmdEnvelope)
	or c
	ld (wSoundCmdEnvelope),a
	jp updateChannelVolume

;;
updateChannelVolume:
	ld a,(wSoundChannel)
	cp $02
	jr nc,++

	ld a,(wMusicVolume)
	cp $00
	jr z,@ret

	ld a,(wSoundChannel)
	inc a
	inc a
	ld e,a
	ld hl,wChannelsEnabled
	ld d,$00
	add hl,de
	ld a,(hl)
	cp $00
	jr z,++
@ret:
	ret
++
	ld a,(wSoundChannel)
	and $01
	jr nz,+

	; Channel 1 only: sweep off
	ld a,$08
	ld ($ff00+R_NR10),a
+
	; Set channel volume
	ld a,(wSoundChannel)
	and $01
	ld b,a
	sla a
	sla a
	add b
	ld b,a
	ld a,(wSoundCmdEnvelope)
	ld c,R_NR12
	call writeIndexedHighRamAndIncrement
	ld hl,wc039
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	and $40
	or $80
	ld (wSoundCmdEnvelope),a
	ret

;;
func_39_4766:
	call func_39_489e
	ld b,a
	ld a,(wc025+4)
	cp b
	jr z,+

	call func_39_489e
	ld (wc025+4),a
	call func_39_434b
	cp $00
	jr nz,+

	ld a,(wc025+4)
	ld ($ff00+R_NR32),a
+
	ret

;;
getChannelVolume:
	ld a,(wSoundChannel)
	scf
	ccf
	cp $02
	jr nc,label_39_056
;;
func_39_478c:
	ld a,(wMusicVolume)
	cp $00
	jr z,label_39_059
	cp $01
	jr z,label_39_058
	cp $02
	jr z,label_39_057
label_39_056:
	ld hl,wChannelVolumes
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	ret
label_39_057:
	ld hl,wChannelVolumes
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	srl a
	ret
label_39_058:
	ld hl,wChannelVolumes
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	srl a
	srl a
	ret
label_39_059:
	ld a,$00
	ret

standardCmdChannels4To5:
	ld hl,wc039
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	cp $00
	jr z,+

	call getNextChannelByte
	ld l,a
	ld a,(wSoundCmd)
	ld h,a
	jp @cmdUnknown
+
	ld a,(wSoundCmd)
	scf
	ccf
	cp $60
	jr nz,@freqCommand
@cmd60:
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	ld hl,wc02d
	add hl,de
	ld (hl),$01
	call func_39_489e
	ld hl,wc025
	push af
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	pop af
	ld (hl),a
	call func_39_434b
	cp $00
	jr nz,+

	ld hl,wc025
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	ld ($ff00+R_NR32),a
+
	jp setChannelWaitCounter
@freqCommand:
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	ld hl,wc02d
	add hl,de
	ld (hl),$00
	ld a,(wSoundCmd)
	ld hl,soundFrequencyTable
	call readWordFromTable
@cmdUnknown:
	call setSoundFrequency
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	ld hl,wc045
	add hl,de
	ld (hl),$00
	ld a,$00
	ld hl,wChannelVibratos
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	and $f0
	srl a
	srl a
	srl a
	ld hl,wc051
	push af
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	pop af
	ld (hl),a
	call func_39_489e
	ld hl,wc025
	push af
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	pop af
	ld (hl),a
	call func_39_434b
	cp $00
	jr nz,+

	ld hl,wc025
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	ld ($ff00+R_NR32),a
	ld a,(wSoundFrequencyL)
	ld ($ff00+R_NR33),a
	ld a,(wSoundFrequencyH)
	ld ($ff00+R_NR34),a
+
	jp setChannelWaitCounter

;;
func_39_489e:
	ld hl,wc02d
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	cp $00
	jr nz,label_39_067
	ld a,(wSoundChannel)
	cp $05
	jr nc,label_39_064
	ld a,(wMusicVolume)
	cp $00
	jr z,label_39_067
	cp $01
	jr z,label_39_066
	cp $02
	jr z,label_39_065
label_39_064:
	ld a,$20
	ret
label_39_065:
	ld a,$40
	ret
label_39_066:
	ld a,$60
	ret
label_39_067:
	ld a,$00
	ret

;;
standardCmdChannel6:
	ld a,(wSoundCmd)
	cp $60 ; rest: unlike the square/wave channels, this byte was never special-cased
	       ; here before, so it just failed to match any noiseFrequencyTable row and
	       ; fell through as a pure no-op -- the noise channel never actually silenced
	       ; on a rest at all. Force volume 0 (no envelope stepping) directly instead.
	jr nz,+
	ld a,$08
	ld ($ff00+R_NR42),a
	jp setChannelWaitCounter
+
	ld a,(wSoundCmd)
	ld c,a
	ld de,noiseFrequencyTable
-
	ld a,(de)
	inc de
	cp $ff
	jr z,@end

	cp c
	jr z,+

	inc de
	inc de
	jr -
+
	ld a,(de)
	ld l,a
	inc de
	ld a,(de)
	ld h,a
	ld a,($c074)
	cp $00
	jr nz,@end

	push hl
	call func_39_478c
	pop hl
	sla a
	sla a
	sla a
	sla a
	or l
	ld ($ff00+R_NR42),a
	ld a,h
	ld ($ff00+R_NR43),a
	ld a,$80
	ld ($ff00+R_NR44),a
@end:
	jp setChannelWaitCounter

;;
standardCmdChannel7:
	ld a,(wSoundCmd)
	ld ($ff00+R_NR43),a
	ld a,$00
	ld ($ff00+R_NR41),a
	ld a,($c01c)
	cp $00
	jr z,+
	ld ($ff00+R_NR44),a
+
	ld a,$00
	ld ($c01c),a
	jp setChannelWaitCounter

channelCmdff:
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	ld hl,wChannelsEnabled
	add hl,de
	ld (hl),$00
;;
; Checks whether to call updateChannelVolume on square channels, does some other things
; with the other types of channels...
;
updateChannelStuff:
	ld a,(wSoundChannel)
	ld hl,@table
	call readWordFromTable
	jp hl

@table:
	.dw @musicSquareChannel
	.dw @musicSquareChannel
	.dw @sfxSquareChannel
	.dw @sfxSquareChannel
	.dw @musicWaveChannel
	.dw @sfxWaveChannel
	.dw @noiseChannel
	.dw @noiseChannel

@musicSquareChannel:
	; Only update if the corresponding sfx channel is not enabled
	ld a,(wSoundChannel)
	inc a
	inc a
	ld e,a
	ld hl,wChannelsEnabled
	ld d,$00
	add hl,de
	ld a,(hl)
	cp $00
	jr z,+
	ret

@sfxSquareChannel:
	; Sfx always updates (but it still does this pointless check of the corresponding
	; music channel)
	ld a,(wSoundChannel)
	dec a
	dec a
	ld e,a
	ld hl,wChannelsEnabled
	ld d,$00
	add hl,de
	ld a,(hl)
	cp $00
	jr z,+
+
	ld hl,wc05d
	ld a,(wSoundChannel)
	ld e,a
	ld d,$00
	add hl,de
	ld a,(hl)
	cp $03
	jr nz,+
	ret
+
	ld a,$08
	ld (wSoundCmdEnvelope),a
	call updateChannelVolume
	jp func_42ea

@musicWaveChannel:
	call func_39_434b
	cp $00
	jr nz,+

	ld a,$00
	ld ($ff00+R_NR30),a
+
	ret

@sfxWaveChannel:
	ld a,(wChannelsEnabled+4)
	cp $00
	jr z,++

	ld a,$04
	ld e,a
	ld hl,wChannelDutyCycles
	ld d,$00
	add hl,de
	ld a,(hl)
	ld (wWaveformIndex),a
	call setWaveform
	ld a,(wc025+4)
	ld ($ff00+R_NR32),a
	ret
++
	ld a,$00
	ld ($ff00+R_NR30),a
	ret

@noiseChannel:
	ld a,$08
	ld ($ff00+R_NR42),a
	ld a,$80
	ld ($ff00+R_NR44),a
	ret

;;
setWaveform:
	call func_39_434b
	cp $00
	jr z,@waitLoop
	ret

@waitLoop:
	; Wait for channel 3 to be on
	ld a,$00
	ld ($ff00+R_NR30),a
	ld a,($ff00+R_NR52)
	and $04
	jr nz,@waitLoop

	; Copy waveform to $ff30
	ld a,(wWaveformIndex)
	ld hl,waveformTable
	call readWordFromTable
	ld c,$10
	ld de,$ff30
-
	ldi a,(hl)
	ld (de),a
	inc de
	dec c
	jr nz,-

-	; Enable channel 3
	ld a,$80
	ld ($ff00+R_NR30),a
	ld a,($ff00+R_NR30)
	and $80
	jr z,-

	; Restart channel 3 (but trashes lower frequency bits?)
	ld a,$80
	ld ($ff00+R_NR34),a
	ret

channelCmdfe:
	call getNextChannelByte
	ld l,a
	call getNextChannelByte
	ld h,a
	ld a,(wSoundChannel)
	sla a
	ld b,a
	ld a,l
	ld c,<hSoundChannelAddresses
	call writeIndexedHighRamAndIncrement
	ld a,h
	ld ($ff00+c),a
	inc c
	jp doNextChannelCommand

;;
func_39_4a10:
	cp $00
	jr nz,+
	ld hl,$0000
	ret
+
	ld e,l
	ld d,h
--
	dec a
	jr z,+

	add hl,de
	jp --
+
	ret

soundFrequencyTable:
	.dw $002d
	.dw $009d
	.dw $0108
	.dw $016c
	.dw $01cb
	.dw $0224
	.dw $0279
	.dw $02c8
	.dw $0313
	.dw $0358
	.dw $039b
	.dw $03db
	.dw $0416
	.dw $044f
	.dw $0484
	.dw $04b6
	.dw $04e5
	.dw $0512
	.dw $053c
	.dw $0564
	.dw $058a
	.dw $05ac
	.dw $05ce
	.dw $05ed
	.dw $060b
	.dw $0627
	.dw $0642
	.dw $065b
	.dw $0673
	.dw $0689
	.dw $069e
	.dw $06b2
	.dw $06c5
	.dw $06d6
	.dw $06e7
	.dw $06f7
	.dw $0706
	.dw $0714
	.dw $0721
	.dw $072e
	.dw $0739
	.dw $0745
	.dw $074f
	.dw $0759
	.dw $0762
	.dw $076b
	.dw $0773
	.dw $077b
	.dw $0783
	.dw $078a
	.dw $0790
	.dw $0797
	.dw $079d
	.dw $07a2
	.dw $07a8
	.dw $07ad
	.dw $07b1
	.dw $07b6
	.dw $07ba
	.dw $07be
	.dw $07c1
	.dw $07c5
	.dw $07c8
	.dw $07cb
	.dw $07ce
	.dw $07d1
	.dw $07d4
	.dw $07d6
	.dw $07d9
	.dw $07db
	.dw $07dd
	.dw $07df
	.dw $07e1
	.dw $07e2
	.dw $07e4
	.dw $07e6
	.dw $07e7
	.dw $07e9
	.dw $07ea
	.dw $07eb
	.dw $07ec
	.dw $07ed
	.dw $07ee
	.dw $07ef
	.dw $07f0
	.dw $07f1
	.dw $07f2

data_4ad0:
	.db $00 $01 $02 $03 $04 $05 $06 $07
	.db $00 $02 $04 $06 $07 $09 $0b $0d
	.db $00 $03 $06 $08 $0b $0e $11 $14
	.db $00 $04 $07 $0b $0f $13 $16 $1a
	.db $00 $05 $09 $0e $13 $17 $1c $21
	.db $00 $06 $0b $11 $16 $1c $22 $27
	.db $00 $07 $0d $14 $1a $21 $27 $2e
	.db $00 $07 $0f $16 $1e $25 $2d $34
	.db $00 $08 $11 $19 $22 $2a $32 $3b
	.db $00 $09 $13 $1c $25 $2f $38 $41
	.db $00 $0a $15 $1f $29 $33 $3e $48
	.db $00 $0b $16 $22 $2d $38 $43 $4e
	.db $00 $0c $18 $24 $31 $3d $49 $55
	.db $00 $0d $1a $27 $34 $41 $4e $5b
data_4b40:
	.db $00 $00 $01 $00 $02 $00 $01 $00
	.db $00 $00 $ff $ff $fe $ff $ff $ff

;;
; @param a The sound to play.
playSound:
	push bc
	push de
	push hl
	ld (wSoundTmp),a
	cp $00
	jr nz,+
	jp @playSoundEnd
+
	cp $f0
	jr z,@sndf0
	cp $f1
	jr z,@sndf1
	cp $f5
	jr z,@sndf5
	cp $f6
	jr z,@sndf6
	cp $f7
	jr z,@sndf7
	cp $f8
	jr z,@sndf8
	cp $f9
	jr z,@sndf9
	cp $fa
	jr z,@sndfa
	cp $fb
	jr z,@sndfb
	cp $fc
	jr z,@sndfc
	jr @normalSound

; Stop music
@sndf0:
	ld a,SNDCTRL_DE
	ld (wSoundTmp),a
	jr @normalSound

; Stop sound effects
@sndf1:
	call stopSfx
	jp @playSoundEnd

; Disable sound
@sndf5:
	call func_39_40b9
	ld a,$01
	ld (wSoundDisabled),a
	jp @setVolumeAndEnd

; Enable sound
@sndf6:
	ld a,$00
	ld (wSoundDisabled),a
	jp @setVolumeAndEnd

; Fast fadeout
@sndfa:
	ld a,$07
	jr +

; Medium fadeout
@sndfb:
	ld a,$0f
	jr +

; Slow fadeout
@sndfc:
	ld a,$1f
+
	ld (wSoundFadeSpeed),a
	ld a,$00
	ld (wSoundFadeCounter),a
	ld a,$01
	ld (wSoundFadeDirection),a
	ld a,$77
	ld (wSoundVolume),a
	jp @playSoundEnd

; Fast fadein
@sndf7:
	ld a,$03
	jr +

; Medium fadein
@sndf8:
	ld a,$07
	jr +

; Slow fadein
@sndf9:
	ld a,$0f
+
	ld (wSoundFadeSpeed),a
	ld a,$00
	ld (wSoundFadeCounter),a
	ld a,$0a
	ld (wSoundFadeDirection),a
	ld a,$00
	ld (wSoundVolume),a
	jp @playSoundEnd

@normalSound:
	ld a,$00
	ld (wSoundFadeDirection),a
	ld a,(wSoundTmp)

	; Get a*3 in de
	ld d,$00
	ld e,a
	ld h,$00
	ld l,a
	sla l
	rl h
	add hl,de
	ld d,h
	ld e,l

	ld hl,soundPointers
	add hl,de

	; Wrapping this in a BUILD_VANILLA check because: A) it's unused, B) it can cause problems
	; if audio data gets placed into an unexpected bank (which WLA could decide to do).
.ifdef BUILD_VANILLA
	ld a,(hl)
	and $80
	jr z,@skipWeirdCall

	; This function doesn't exist, so clearly this section of code should never be executed
	call nonExistentFunction

	jp @setVolumeAndEnd

@skipWeirdCall:

.endif

	ldi a,(hl)
	ld c,a
	ldh a,(<hSoundDataBaseBank)
	add c
	ld (wLoadingSoundBank),a
	ldi a,(hl)
	ld c,a
	ld a,(hl)
	ld b,a
	ld l,c
	ld h,b

@nextSoundChannel:
	; NOTE: this reads soundChannelPointers.s's own bytes (the per-sound/per-channel
	; pointer table), which always lives in the fixed base bank -- NOT wLoadingSoundBank,
	; which tracks where that *song's note data* (soundChannelData.s) lives instead, a
	; separate and generally different bank. (An earlier version of this code
	; incorrectly used wLoadingSoundBank here, corrupting every sound's setup by reading
	; the pointer table from whatever random bank a song's note data happened to be in.)
	ldh a,(<hSoundDataBaseBank)
	call wMusicReadFunction
	cp $ff
	jr nz,+
	jp @setVolumeAndEnd
+
	ld (wSoundTmp),a
	and $f0
	swap a
	inc a
	ld (wSoundChannelValue),a
	ld a,(wSoundTmp)
	and $0f
	ld (wSoundTmp),a
	ld e,a
	push hl
	ld hl,wChannelsEnabled
	ld d,$00
	add hl,de
	ld a,(hl)
	pop hl
	ld c,a
	ld a,(wSoundChannelValue)
	cp c
	jr nc,+

	inc hl
	inc hl
	jp @nextSoundChannel
+
	push hl
	ld a,(wSoundTmp)
	ld e,a
	ld a,(wSoundChannelValue)
	ld hl,wChannelsEnabled
	ld d,$00
	add hl,de
	ld (hl),a
	ld a,$08
	ld hl,wChannelVolumes
	ld d,$00
	add hl,de
	ld (hl),a
	ld a,$00
	ld hl,wChannelWaitCounters
	ld d,$00
	add hl,de
	ld (hl),a
	ld a,(wSoundTmp)
	cp $00
	jr z,@squareChannel
	cp $01
	jr z,@squareChannel
	cp $02
	jr z,@squareChannel
	cp $03
	jr z,@squareChannel
	cp $04
	jr z,@waveChannel
	cp $05
	jr z,@waveChannel

	; Noise channels
	jr ++

@waveChannel:
	ld a,(wSoundTmp)
	ld e,a
	ld a,$00
	ld hl,wChannelVibratos
	ld d,$00
	add hl,de
	ld (hl),a
	ld hl,wc03f
	ld d,$00
	add hl,de
	ld (hl),a
	ld hl,wChannelPitchShift
	ld d,$00
	add hl,de
	ld (hl),a
	ld hl,wc039
	ld d,$00
	add hl,de
	ld (hl),a
	jr ++

@squareChannel:
	ld a,(wSoundTmp)
	ld e,a

	; Clear a bunch of variables
	ld a,$00
	ld hl,wChannelEnvelopes
	ld d,$00
	add hl,de
	ld (hl),a
	ld hl,wChannelEnvelopes2
	ld d,$00
	add hl,de
	ld (hl),a
	ld hl,wChannelDutyCycles
	ld d,$00
	add hl,de
	ld (hl),a
	ld hl,wChannelVibratos
	ld d,$00
	add hl,de
	ld (hl),a
	ld hl,wc03f
	ld d,$00
	add hl,de
	ld (hl),a
	ld hl,wChannelPitchShift
	ld d,$00
	add hl,de
	ld (hl),a
	ld hl,wc039
	ld d,$00
	add hl,de
	ld (hl),a
++
	; Write the bank for this sound channel into hSoundChannelBanks
	pop hl
	ld a,(wSoundTmp)
	ld b,a
	ld a,(wLoadingSoundBank)
	ld c,<hSoundChannelBanks
	call writeIndexedHighRamAndIncrement

	; Write the address for this sound channel into hSoundChannelAddresses
	ld a,(wSoundTmp)
	sla a
	ld b,a
	push bc
	ldh a,(<hSoundDataBaseBank) ; see @nextSoundChannel above -- also reading from
	                            ; soundChannelPointers.s, so also the fixed base bank
	call wMusicReadFunction
	pop bc
	ld c,<hSoundChannelAddresses
	call writeIndexedHighRamAndIncrement
	push bc
	ldh a,(<hSoundDataBaseBank)
	call wMusicReadFunction
	pop bc
	ld ($ff00+c),a
	inc c
	jp @nextSoundChannel

@setVolumeAndEnd:
	ld a,$77
	ld (wSoundVolume),a
@playSoundEnd:
	pop hl
	pop de
	pop bc
	ret

;;
; Reads a word at hl+a*2 into de and hl. Index can't be higher than $7f.
readWordFromTable:
	sla a
	ld d,$00
	ld e,a
	add hl,de
	ld e,(hl)
	inc hl
	ld d,(hl)
	ld h,d
	ld l,e
	ret

;;
; Adds b to c, writes a to ($ff00+c), increments c.
writeIndexedHighRamAndIncrement:
	push af
	ld a,b
	add c
	ld c,a
	pop af
	ld ($ff00+c),a
	inc c
	ret


; A function which doesn't exist. Call this if you want your game to crash.
nonExistentFunction:


.include "audio/common/noise.s"
.include "audio/common/waveforms.s"
; soundChannelPointers.s is read exclusively via playSound's @nextSoundChannel loop,
; always from the fixed base bank (hSoundDataBaseBank) -- unlike soundChannelData.s
; (the actual song note-data, which legitimately lives in whatever bank each song was
; placed in; tracked separately via wLoadingSoundBank), there is no delta/relocation
; mechanism for *this* table, so it must stay in this bank in every build. (An earlier
; version of this comment claimed otherwise and relocated it for the editable build --
; that was wrong, reused wLoadingSoundBank for the wrong purpose, and corrupted every
; sound's setup. Fixed by reverting the relocation entirely.)
.include {"audio/{GAME}/soundChannelPointers.s"}
.include {"audio/{GAME}/soundPointers.s"}

.ends ; End of section AudioCode


.include {"audio/{GAME}/soundChannelData.s"}
