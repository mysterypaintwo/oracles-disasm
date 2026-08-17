; Musical notes, usable on square & wave channels
.enum $0
	c1: db
	cs1: db
	d1: db
	ds1: db
	e1: db
	f1: db
	fs1: db
	g1: db
	gs1: db
	a1: db
	as1: db
	b1: db
	c2: db
	cs2: db
	d2: db
	ds2: db
	e2: db
	f2: db
	fs2: db
	g2: db
	gs2: db
	a2: db
	as2: db
	b2: db
	c3: db
	cs3: db
	d3: db
	ds3: db
	e3: db
	f3: db
	fs3: db
	g3: db
	gs3: db
	a3: db
	as3: db
	b3: db
	c4: db
	cs4: db
	d4: db
	ds4: db
	e4: db
	f4: db
	fs4: db
	g4: db
	gs4: db
	a4: db
	as4: db
	b4: db
	c5: db
	cs5: db
	d5: db
	ds5: db
	e5: db
	f5: db
	fs5: db
	g5: db
	gs5: db
	a5: db
	as5: db
	b5: db
	c6: db
	cs6: db
	d6: db
	ds6: db
	e6: db
	f6: db
	fs6: db
	g6: db
	gs6: db
	a6: db
	as6: db
	b6: db
	c7: db
	cs7: db
	d7: db
	ds7: db
	e7: db
	f7: db
	fs7: db
	g7: db
	gs7: db
	a7: db
	as7: db
	b7: db
	c8: db
	cs8: db
	d8: db
	ds8: db
	e8: db
	f8: db
	fs8: db
	g8: db
	gs8: db
	a8: db
	as8: db
	b8: db
.ende

; Other values that can be use within note/beat macros
.redefine od (-1) ; octave down
.redefine ou (-2) ; octave up
.redefine r (-3)  ; rest

; Define relative notes names within a given octave
.macro octave
	.redefine OCTAVE \1
	.redefine OFFSET (-$c)

	.redefine c 12*\1+0 + OFFSET
	.redefine cs 12*\1+1 + OFFSET
	.redefine d 12*\1+2 + OFFSET
	.redefine ds 12*\1+3 + OFFSET
	.redefine e 12*\1+4 + OFFSET
	.redefine f 12*\1+5 + OFFSET
	.redefine fs 12*\1+6 + OFFSET
	.redefine g 12*\1+7 + OFFSET
	.redefine gs 12*\1+8 + OFFSET
	.redefine a 12*\1+9 + OFFSET
	.redefine as 12*\1+10 + OFFSET
	.redefine b 12*\1+11 + OFFSET
.endm

.macro octaved
	octave OCTAVE-1
.endm
.macro octaveu
	octave OCTAVE+1
.endm

.macro m_soundPointer
	.db :\1Start - :b39_initSound ; Bank number
	.dw \1 ; Pointer
.endm

; Byte 1: frequency
; Byte 2: length
;
; Frequencies for noise:
; 22,23,24,26,27,28,29,2a,2e,2f,30,32,52
.macro note
	.redefine offset 0
	.rept NARGS
	.if NARGS >= 1
		.if \1 == od
			octaved
			.redefine offset offset-12
			.shift
		.else
		.if \1 == ou
			octaveu
			.redefine offset offset+12
			.shift
		.endif
		.endif
	.endif

	.if NARGS >= 2
	.if \1 == r
		rest \2
		.shift
		.shift
	.else
	.if \1 >= 0
		.db \1+offset
		.db \2

		.shift
		.shift
	.endif
	.endif
	.endif
	.endr
.endm

; Editable-build-only (see setDefaultLength below and code/audio.s's @channel0To3 short-
; note dispatch): plays a pitch (square channels only for now) using the channel's
; current default length instead of an explicit one -- 1 byte total instead of 2. Set
; the default length first with setDefaultLength.
.ifndef BUILD_VANILLA
.macro shortNote
	.db $62 + \1
.endm

; f4: sets the channel's default length, used by shortNote whenever it's called
; afterward (until changed again or the channel restarts).
.macro setDefaultLength
	.db $f4 \1
.endm
.endif

; This is NOT used by the base game; it's an attempt to provide a more sane way to define music
; (multiple notes per line). Each pair of arguments is a note followed by a length. Can define
; "NOTE_END_WAIT" to set a certain amount of a note to be "rest" instead of being actually played.
.macro beat
	.redefine offset 0
	.rept NARGS
	.if NARGS >= 1
		.if \1 == od
			octaved
			.redefine offset offset-12
			.shift
		.else
		.if \1 == ou
			octaveu
			.redefine offset offset+12
			.shift
		.endif
		.endif
	.endif

	.if NARGS >= 2
	.if \1 == r
		rest \2*BEAT
		.shift
		.shift
	.else
	.if \1 >= 0
		.db \1+offset

		.ifndef NOTE_END_WAIT
			.define NOTE_END_WAIT 0
		.endif

		.if NOTE_END_WAIT != 0
			.db \2*BEAT - NOTE_END_WAIT
			rest NOTE_END_WAIT
		.else
			.db \2*BEAT
		.endif

		.shift
		.shift
	.endif
	.endif
	.endif
	.endr
.endm

; 60: cuts the channel off (immediate, clean silence -- see @cmd60/standardCmdChannel6 in
;     code/audio.s). Use this for an actual audible rest.
.macro rest
	.db $60 \1
.endm

; 61: extends the currently playing note/rest without retriggering or otherwise
;     affecting it -- a tie/sustain, not a rest. (Named `rest2` prior to the `rest` fix
;     above; renamed since a name implying "another kind of rest" was actively
;     misleading for what's the opposite of one. Not named `wait`: that name is already
;     taken by the unrelated cutscene-script `wait` macro in script_commands.s.)
.macro sust
	.db $61 \1
.endm

; f5: decays the currently playing note from its current volume at a fixed fast pace
;     (square channels 0-3 only -- see channelCmdf5 in code/audio.s). This is what `rest`
;     accidentally did before its fix, and turned out to be the actual note-release
;     technique used by the vast majority of existing content, so it's kept available
;     as its own command: a soft/decaying release, distinct from `rest` (hard cutoff)
;     and `sust` (hold).
.macro release
	.db $f5 \1
.endm

; d0-df: set volume
.macro vol
	.if \1 > $f
		.fail
	.endif
	.db $d0 | \1
.endm

; e0-e7: set envelope (\1 $0-$7: software-simulated attack pace, starting at volume 1 and
;        snapping to the note's target volume after a fixed delay -- see func_39_464c)
; e8-ef: \1 $8-$f (i.e. $8 | pace): true hardware envelope fade-in, starting at volume 0
;        and increasing to volume 15 entirely in hardware at the given pace (\1 & $7) --
;        see hardwareAttackEnvelope in code/audio.s
; \2 ($0-$7 either way): decay pace -- an exact hardware envelope match in both cases,
;        decreasing from the note's target volume to 0
.macro env
	.if \1 > $f
		.fail
	.endif
	.db $e0 | \1
	.db \2
.endm

; f0: unknown
; Sometimes sets wc039
.macro cmdf0
	.db $f0 \1
.endm

; f1/f3: pattern-call / pattern-end (editable-build only -- see code/audio.s). Confirmed
; unused as bare no-op bytes by every vanilla song, which is what let them be repurposed.
; Only valid on channels 0, 1, 4, and 6 (square 1/2, wave, noise -- see
; patternChannelSlotTable in code/audio.s); not nestable.
.ifndef BUILD_VANILLA
.macro patternCall
	.db $f1
	.dw \1
	.db \2
.endm

.macro patternEnd
	.db $f3
	.dw \1
.endm
.endif

; f2: does nothing
.macro cmdf2
	.db $f2
.endm

; f4-f5: duplicates of ff?
.macro cmdf4
	.db $f4
.endm
.macro cmdf5
	.db $f5
.endm

; f6: sets wChannelDutyCycles
.macro duty
	.db $f6 \1
.endm

; f7: duplicate of ff?

; f8: sets wc03f (for channels 0-5)
.macro cmdf8
	.db $f8 \1
.endm

; f9: sets wChannelVibratos.
; Upper nibble is time to wait until vibrato starts.
; Lower nibble is intensity of vibrato.
.macro vibrato
	.db $f9 \1
.endm

; fa-fc: duplicates of ff?

; fd: sets wc033
; Shifts pitch
.macro cmdfd
	.db $fd \1
.endm

; fe: jump to the given address
.macro goto
	.db $fe
	.dw \1
.endm

; ff: might mute the channel?
.macro cmdff
	.db $ff
.endm


; Parameters:
;   \1: Index
;   \2: Name
.macro m_waveform
	.DEFINE \2, \1 EXPORT
	@waveform{%.2x{\1}}:
.endm
