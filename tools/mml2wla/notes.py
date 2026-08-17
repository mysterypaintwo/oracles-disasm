"""Pitched-note (square/wave channel) name resolution.

Both mmlgb and the target WLA sound engine share the same absolute pitch
encoding in principle: octave 1-8, 12 semitones each, C at the bottom. The
target engine's musicMacros.s exposes this as a flat `.enum` (c1=0 .. b8=95)
usable as a `note` argument on any of its pitched channels.

However: the reference engine's own frequency-lookup code (code/audio.s)
does NOT treat the wave channel the same as the square channels. The square
channel path (`@cmdFrequency`) subtracts 12 from the note byte before
indexing into `soundFrequencyTable`; the wave channel path (`@freqCommand`)
does not subtract anything. Since both paths index the *same* table, a wave
note written with the same enum value as an equivalent square note ends up
12 table entries higher, i.e. exactly one octave sharp. This is a real
asymmetry in that engine's code (confirmed by reading both code paths), not
a rounding or timing artifact -- so the wave channel needs every note
pre-shifted down by 12 (one octave) to land on the intended pitch.
"""

from typing import Optional, Tuple

NOTE_NAMES = ['c', 'cs', 'd', 'ds', 'e', 'f', 'fs', 'g', 'gs', 'a', 'as', 'b']

# musicMacros.s .enum labels, c1..b8 (96 entries, indices 0-95).
NOTE_ENUM = [f"{n}{o}" for o in range(1, 9) for n in NOTE_NAMES]

# MML channel index (0=A,1=B,2=C,3=D) -> per-channel note-byte adjustment.
# Only the wave channel (C, index 2) needs the -12 compensation described
# above; the noise channel doesn't use this table at all (see noise.py).
NOTE_BYTE_ADJUST = {0: 0, 1: 0, 2: -12, 3: 0}


def resolve_pitch(ch: int, octave: int, note_idx: int) -> Tuple[str, Optional[str]]:
    """Returns (enum_name, warning_or_None) for a square/wave channel note.

    `ch` is the MML channel index (0=A/square1, 1=B/square2, 2=C/wave).
    Not valid for the noise channel (3) -- see noise.nearest_noise_note.
    """
    absolute = (octave - 1) * 12 + note_idx + NOTE_BYTE_ADJUST[ch]
    warning = None
    if absolute < 0 or absolute > 95:
        clamped = max(0, min(95, absolute))
        extra = ""
        if ch == 2:
            extra = (" (the wave channel's usable range is one octave "
                     "narrower than square/noise -- see mml2wla_documentation.md)")
        warning = (f"note at octave {octave} is outside this engine's representable "
                   f"range (C1-B8){extra}; clamped")
        absolute = clamped
    return NOTE_ENUM[absolute], warning
