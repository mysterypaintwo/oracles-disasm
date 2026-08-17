# Oracles audio MML documentation

This project's music and sound effects are authored as `.mml` files (an
mmlgb-derived dialect) and compiled by the vendored `tools/audio/mml2wla`
into the WLA-DX assembly the real sound engine (`code/audio.s`) understands.
This document covers the whole dialect as it
exists in *this* project specifically -- where it matches mmlgb exactly, where
it's been extended for this engine, and where an mmlgb feature has no
equivalent here and is silently dropped. Formatted to match
`mmlgb_documentation.md` from the original mml2wla project.

Every `.mml` file, and everything under `audio/*/mus/bin/` and
`audio/*/sfx/bin/`, is generated -- see "Build pipeline" at the end.

## Channels

The Game Boy has four sound channels: two square waves, one user-defined
wave, and a noise generator -- referred to throughout this document (and in
every `.mml` file) as `A`/`B`/`C`/`D`.

| Letter | Channel  |
|:-------|:---------|
| `A`    | Square 1 |
| `B`    | Square 2 |
| `C`    | Wave     |
| `D`    | Noise    |

Under the hood, this engine gives sound effects their own separate set of 4
channel slots so an sfx can briefly interrupt whatever music is already
playing without clobbering it. Which set a `.mml` file targets is decided by
the `#SFX` directive (see below), never written explicitly in the channel
letters themselves -- `A`/`B`/`C`/`D` mean the same 4 physical channels either
way.

| Letter | Physical channel | Music engine channel | Sfx engine channel |
|:-------|:------------------|:---------------------:|:--------------------:|
| `A`    | Square 1          | 0                     | 2                     |
| `B`    | Square 2          | 1                     | 3                     |
| `C`    | Wave              | 4                     | 5                     |
| `D`    | Noise             | 6                     | 7                     |

## Commands

| Command | Description |
|:--------|:------------|
| `;` | Comment. Rest of the line is ignored. |
| `ABCD` | Selects the current channel(s) for the rest of the line. Multiple letters apply the same line to each, e.g. `AB t120 cdef...`. |
| `cdefgab` | Play a note. Append `+` (preferred) or `#` for sharp, `-` for flat. |
| `r` | Rest (silence, clean cutoff). Append a length. |
| `w` | Wait/tie: holds the currently playing note instead of cutting it off. Append a length. |
| `o` | Followed by a number, sets the current octave. |
| `>`, `<` | Octave up / down by one. |
| `l` | Followed by a number, sets the default note length used whenever a note omits its own. |
| `v` | Followed by a number, sets channel volume. `A`/`B`/`D` take 0-15; `C` (wave) takes 0-3 -- see "Waveforms" for why. |
| `t` | Set tempo in BPM. Global -- affects every channel from the real-time moment each one's own playback reaches it, not just whatever comes later in the source text. |
| `L` | Marks the loop point: the song plays from the start once, then repeats forever from here. |
| `[...]n` | Repeat block `n` times. Nestable, e.g. `[c4[d4e4]5]8` plays `c4 d4e4 d4e4 d4e4` (`c4` followed by `d4e4` repeated 5 times) a total of 8 times -- 88 notes altogether -- and compiles correctly either way. See "Space optimization" for whether it actually saves ROM space. |

### Numbers

Decimal by default. `0x` prefix for hex (`0xA3` = 163), `0b` for binary
(`0b10100011`).

### Note length

Append a number for a musical length, e.g. `c+4` is a C# quarter note. Add
`.`/`..`/... for dotted/double-dotted, etc.

| Value | Length | Ticks |
|:------|:-------|------:|
| `1`  | Whole note | 192 |
| `2`  | Half note | 96 |
| `3`  | Half triplet note | 64 |
| `4`  | Quarter note | 48 |
| `6`  | Quarter triplet note | 32 |
| `8`  | Eighth note | 24 |
| `12` | Eighth triplet note | 16 |
| `16` | Sixteenth note | 12 |
| `24` | Sixteenth triplet note | 8 |
| `32` | Thirty-second note | 6 |

Use `=X` for an exact tick count instead of one of the named fractions above
-- e.g. `c+=17` is 17 ticks, still fully tempo-relative like any other
length, just not one of the standard note values. In a `#VANILLA`-flagged
file (see "File-level directives"), `=X` means something different instead:
a raw, tempo-*independent* hardware frame count (`c+=4` holds for exactly 4
frames no matter what `t` says). This is what every vanilla song dumped
straight from the ROM uses throughout (see "Build pipeline"), since vanilla
data has no tempo of its own to convert to -- only literal frame counts. Not
something a hand-authored song needs to reach for.

Use `^` to tie lengths together, e.g. `c4^4` is the same duration as `c2`
(but still one single note-trigger, not two). A bare dot or tie with nothing
after it falls back to the channel's current default length (`l`) rather
than being a parse error.

### Valid notes

| Channel | First note | Last note |
|:--------|:-----------|:----------|
| `A` Square 1 | `C1` | `B8` |
| `B` Square 2 | `C1` | `B8` |
| `C` Wave     | `C2` | `B8` |
| `D` Noise    | n/a -- see "Noise channel" below |

The wave channel's usable range is one octave narrower than the square
channels -- a real asymmetry in this engine's own frequency-lookup code (its
square-channel path subtracts an octave before the table lookup; its wave
path doesn't), not a rounding artifact. A note outside a channel's range is
clamped, with a warning.

## File-level directives

Written as their own line, anywhere in the file (conventionally the top).
Stripped before the rest of the file is parsed, so they never collide with
real MML syntax.

| Directive | Effect |
|:----------|:-------|
| `#TITLE <name>` | Overrides every generated label (`mus<Name>Start`, `mus<Name>Channel0`, the loop label, etc.) that would otherwise be derived from the output filename. Must be a valid label: letters/digits/underscore, not starting with a digit. |
| `#COMPOSER <text>` | Documentation only -- has no effect on the compiled output. |
| `#SFX` | Marks this file as a sound effect rather than music -- see "Channels" above and "Sfx-specific commands" below. |
| `#VANILLA` | Marks this file as a byte-accurate reproduction of real ROM data (every file `tools/audio/dumpMusicMml.py`/`dumpSfxMml.py` write has this). Changes `=X` to mean a raw, tempo-independent frame count instead of a tick count -- see "Note length" -- and switches the default-length space optimization to its automatic, same-length-run-detecting mode -- see "Space optimization". |

## Macros

### Volume envelope -- `@ve` (channels A, B, D)

`@ve<length>` requests a hardware volume envelope, `length` from -7 to 7.
Negative decays, positive climbs. `@ve0` disables it.

An increasing envelope (`@ve+n`) is an *exact* match only when the channel's
current volume is already 0 -- this engine has a real hardware fade-in-from-
zero feature for exactly that case. From any other starting volume there's no
exact equivalent, so it's approximated by matching the real-world sweep
duration instead (a warning is printed when this approximation is used).
Decreasing envelopes (and `@ve0`) are always an exact match.

Not available on the wave channel (`C`) at all -- volume there is baked
directly into the waveform sample data (see "Waveforms").

On the noise channel (`D`), envelope pace is normally fixed per noise
"pitch" (baked into the fixed noise table -- see "Noise channel"), so `@ve`
is dropped there with a warning by default. Pass `--noise-envelope` to
mml2wla to instead have it generate new, exact noise-table entries on the
fly.

### Raw envelope -- `@ea<attack>,<decay>` (channels A, B, D)

A direct, two-parameter passthrough of this engine's own envelope command,
with no mmlgb equivalent: `attack` (0-15) and `decay` (0-7) are independently
controllable in a way no single `@ve` value can express (`@ve` can only ever
request one direction per trigger). Mostly useful for `#VANILLA` reproductions;
hand-authored songs will usually want `@ve` instead.

### Wave pattern duty -- `@wd<duty>` (channels A, B)

Sets the square wave's duty cycle, `duty` 0-3:

```
      _
0    | |             |  12.5%
     | |_____________|
      ___
1    |   |           |  25%
     |   |___________|
      _______
2    |       |       |  50%
     |       |_______|
      ___________
3    |           |   |  75%
     |           |___|
```

### Waveform select -- `@wave<id>` (channel C)

See "Waveforms" below -- both defining new wave data and selecting an
already-existing one use the exact same numeric syntax.

### Release -- `@rl` (channels A, B only)

`@rl` followed by a length decays the currently-playing note from whatever
volume it's already at, at a fixed hardware pace, instead of cutting it off
(`r`) or holding it (`w`). No mmlgb equivalent -- it exists because this is
what a real pre-fix bug in this engine's own `r` used to do, and it turned
out to be the dominant note-release technique in the original game's music,
so it was kept as a real, intentionally-available command.

### Raw volume -- `@vr<0-15>` (any channel)

A direct passthrough of this engine's own volume register write, bypassing
`v`'s usual per-channel meaning. Mainly relevant on the wave channel, where
plain `v` (0-3) instead selects a pre-scaled waveform variant (see
"Waveforms") -- `@vr` writes the raw 0-15 hardware value directly, matching
what the original vanilla wave-channel data actually does.

### Pitch offset -- `@po<-127..127>` (channels A, B, C)

A signed value added once to a note's frequency at trigger time, held for
that note's whole duration. `@po0` disables it. No effect on the noise
channel.

### Pitch slide -- `@s<-127..127>` (channels A, B, C)

A signed value re-added to the channel's live frequency every single frame,
for as long as it stays nonzero -- a continuous, unbounded slide (distinct
from mmlgb's portamento, which glides toward and settles on a specific
target note; this engine has no equivalent to that). `@s0` disables it. No
effect on the noise channel.

### Vibrato -- `@v<speed>,<depth>[,<delay>]` (channels A, B)

`depth` (0-15) and an optional `delay` (a note length, defaulting to none)
work as in mmlgb. `speed` is accepted for compatibility but has no effect --
this engine's vibrato oscillation rate is fixed in hardware, so any nonzero
value prints a warning. Conventionally written as `@v0,<depth>,<delay>`. Use
`@v0,0` to disable.

### User macros -- `@@`

Define with `@@<id> = { <data> }`; call with `@@<id>`, which is exactly
equivalent to re-inserting the macro body at that point. The macro body is
re-parsed against the *calling* channel's live octave/default-length state
at each call site (and continues to mutate that state afterwards), matching
real hardware playback behavior rather than mmlgb's own compile-time-only
macro expansion.

```
@@1 = { v13 @ve-5 @v0,5 }
A l8 cdef @@1 g
; equivalent to:  A l8 cdef v13 @ve-5 @v0,5 g
```

## Noise channel

Unlike the other three channels, the noise channel doesn't play a smooth
chromatic scale -- this engine only has a small, fixed palette of hand-tuned
"noise notes" (drum/crash/dash-style sounds), each a specific (envelope,
hardware frequency) pair, authored in `audio/common/noise.json` (see "Build
pipeline"). A regular note letter (`c`-`b`) on channel `D` is automatically
matched to whichever palette entry is the closest real hardware frequency.

To pick a specific palette entry exactly, instead of the closest match to a
chromatic note, use:

- **`n$XX`** or **`n34`** -- a literal palette entry by its raw byte value,
  hex or decimal. Needs a comma before the length, e.g. `n$22,4` or
  `n34,=8`.
- **A named alias**, if the entry has one in `noise.json` (`crash`, `snare`,
  `dashLong`, etc.) -- defined once per file as `@crash = n$22` (conventionally
  at the top, right after the channel-select letters), then used just like a
  note: `@crash=4`.

A value that isn't one of `noise.json`'s documented entries still works, but
prints a warning, since it's unusual enough to be worth double-checking.

## Sfx-specific commands

Two more commands exist only because sound effects use engine features
music never does -- both are overloads of the same underlying opcode
depending on which channel they're used on. Neither has any mmlgb
equivalent.

### Raw noise envelope -- `@er<vol>,<dir>,<pace>` (channel D, sfx only)

A raw, immediate hardware envelope write: `vol` (0-15) is the starting
volume, `dir` is `0` (decrease) or `1` (increase -- something no `@ve`/`@ea`
value can express on the noise channel, since its envelope is normally fixed
per palette entry), `pace` is 0-7. Unlike `@ve`/`@ea`, this takes effect
immediately rather than waiting for the next note-trigger, and real sfx data
re-issues it before every single note it's meant to affect (needed again
each time, not deduplicated).

### Raw frequency mode -- `@fm<byte>` + `@rf$<hex>=<length>` (channels A, B, sfx only)

`@fm<byte>` (0-255) is a one-way switch: from that point on, this channel
stops reading regular note letters entirely and instead reads a literal raw
hardware frequency value for every event, via `@rf$<hex>=<length>` (hex
0-$ffff, exact frame length required). Used for siren/pitch-sweep effects
that need to sweep completely outside the normal chromatic note range (e.g.
the `beam` sound effect). There's no way back to regular notes on that
channel once `@fm` has been used -- real sfx data never needs one, since
`@fm` is always issued once, right at the very start of the channel.

## Space optimization

None of this changes what a song sounds like -- these are purely how many
ROM bytes it takes to say it, and the compiler applies all of them
automatically wherever profitable.

### Repeat blocks -- `[...]n`

A `[...]n` block is checked for whether every iteration is guaranteed to
compile to identical bytes: if so, it becomes one real WLA-DX `.rept n`
block -- the repeated content exists exactly once in ROM no matter how
large `n` is, e.g. `[abcd]3` compiling `abcd` once instead of three times.
This is always guaranteed when every length inside the block is written as
an exact tick/frame count (`=X`), since those never depend on tempo
rounding at all. For ordinary tick-based lengths (`4`, `8`, ...), it's
guaranteed whenever the block's *total* length happens to land on a whole
number of frames at the current tempo -- common, but not certain, since the
Game Boy's hardware timer only supports discrete tempo steps to begin with.
When it isn't guaranteed, later iterations really can round to very
slightly different frame counts than the first (never audible, but no
longer byte-identical), so the block is expanded in full instead, to keep
every iteration's timing exactly accurate rather than risk drifting for the
sake of a smaller ROM. A run that happens to still be byte-identical after
expansion may yet get merged by the next optimization below.

### Repeat detection

Separately from `[...]n` above, whenever a channel's fully-compiled output
contains a run of literally identical consecutive chunks -- a repeated `@@`
macro call, an expanded (not `.rept`-collapsed) `[...]n` block, or just
coincidentally-identical stretches of same-pitch, same-length notes -- it's
automatically collapsed into a `.rept` block too. This is a byte-for-byte
equality check on the *already-fully-resolved* output, so it finds real
repetition regardless of what produced it.

### Default note length

Square channels (`A`/`B`) only. A normal note costs 2 bytes (pitch byte +
explicit length byte); this engine also has a 1-byte short form for a note
playing at the channel's currently-stored default length (2 bytes to set,
once). This is a genuinely new engine feature with no vanilla-ROM
equivalent, so the compiler always emits both forms side by side, guarded
so a from-scratch reproduction of the original game keeps using the plain
form byte-for-byte while every other build benefits from the shorter one.

Which notes actually get the short form depends on `#VANILLA`:

- **Hand-authored (no `#VANILLA`):** the default length is manually defined
  in the MML, via `l` -- a note that omits its own length, relying on the
  channel's current `l`, is exactly the author's own signal that this note
  "is at the default," and that's what triggers the short form (`l4 cdefg`
  -- all five notes qualify). A note with an explicit length of its own
  doesn't, even if the number happens to match.
- **`#VANILLA`:** vanilla data has no `l`/default-length concept at all --
  every note already carries its own exact length. So instead, the compiler
  looks for same-length runs after the fact: whenever 3 or more
  single-trigger notes in a row happen to share a length, it's worth
  switching the stored default once and using the short form for all of
  them (2 notes cost the same either way, so shorter runs are left alone).
  This is a nice space win for reproductions with no authoring effort at
  all, since it's automatic.

### Looping

`L` marks a song's loop point. Everything before it plays once as an intro;
everything from `L` onward repeats forever via a single `goto` back to that
point -- the loop body's bytes exist exactly once in ROM no matter how many
times it repeats during playback, which is normally by far the single
biggest space saving available for any looping song.

## Waveforms

The wave channel's usable sounds are 32-sample (4-bit each) waveforms,
looked up by a numeric id via `duty $XX` at the engine level. Every `.mml`
file uses one unified syntax for both defining brand new waveform data and
selecting an already-existing one -- there's no separate "local" vs
"external reference" syntax to choose between.

**Defining new data**, inline in the `.mml` file, at the top level (not
inside a channel):

```
@wave50 = { 0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 15 14 13 12 11 10 9 8 7 6 5 4 3 2 1 0 }
```

32 samples, each 0-15, in playback order. The id (`50` here) only has to be
unique within this file and not already claimed by an existing named
waveform (see below) -- it isn't the id the data ends up at in the final
ROM table.

**Selecting a waveform**, whether it's one just defined above or one that
already exists project-wide, in a channel:

```
C @wave50 l4 cdefg
```

**Project-wide waveforms** (`audio/common/waveforms.json`) are the
already-named, already-cataloged entries every song can use for free, by id,
with no `{...}` definition of their own -- e.g. `@wave14` might already be
`WF_SQUARE_50_VOL_8`. Referencing one of these costs nothing extra: no new
data is written anywhere, the compiled song just points `duty` at the
existing table entry directly.

### How local and global waveforms actually compile together

This is the important part: a song's own newly-authored waveform (a
`@waveN = {...}` whose id isn't already in `waveforms.json`) isn't left as a
separate, manually-merged side file. The whole project's audio is compiled
in one pass (`tools/audio/buildAudio.py`, run by the Makefile), sharing a
single waveform table builder across every song and sound effect at once.
Any new waveform any song defines is automatically deduplicated (an
identical waveform, even one authored independently in two different songs,
or at two different volume levels of the same source data, becomes one
shared table entry), assigned the next free id after everything already in
`waveforms.json`, and folded directly into the single generated
`audio/common/bin/waveforms.s` alongside the existing catalog -- so there is
always exactly one complete, self-consistent table, and every song's `duty`
reference (old or new, local or global) points at the correct final entry
with no manual step required.

Volume on the wave channel works differently from every other channel: this
engine's `vol`/`v` command does nothing there at all -- volume has to be
baked into the waveform's own sample data. `v0`-`v3` (100%/50%/25%/mute)
automatically requests a scaled variant of whatever waveform is currently
selected, generated and deduplicated the same way. `@vr` (see above) is the
escape hatch for when you specifically want the raw 0-15 hardware value
written instead, matching how the original vanilla wave-channel data is
actually authored.

## Build pipeline

`.mml` is the authored source. Nothing else in `audio/*/mus/` or
`audio/*/sfx/` is meant to be hand-edited:

- `audio/*/mus/*.mml` and `audio/*/sfx/*.mml` compile to
  `audio/*/mus/bin/*.s` / `audio/*/sfx/bin/*.s` automatically as part of a
  normal `make`/`make ages`/`make seasons` -- see `tools/audio/buildAudio.py`
  and the Makefile's `$(AUDIO_MML_STAMP)` rule. The `bin/` output is
  gitignored, regenerated on demand.
- `audio/common/waveforms.json` and `audio/common/noise.json` are the
  committed sources for the wave/noise tables; `audio/common/bin/waveforms.s`
  and `noise.s` are generated from them the same way (see
  `tools/audio/waveformsJsonToS.py` / `noiseJsonToS.py`).
- The `.mml` files themselves are **not committed** -- they encode
  Nintendo's copyrighted music/sfx data, so for legal reasons this repo only
  distributes the tooling to reconstruct them, never the reconstructed files
  themselves. Run `make dumpmusic ROM=path/to/rom.gbc` once per game (music)
  or `make dumpsfx ROM_AGES_FILE=path/to/ages.gbc ROM_SEASONS_FILE=path/to/seasons.gbc`
  once total (sfx, both ROMs needed together) against your own legally-owned
  ROMs to regenerate them locally -- see `tools/audio/dumpMusicMml.py` /
  `dumpSfxMml.py`.
