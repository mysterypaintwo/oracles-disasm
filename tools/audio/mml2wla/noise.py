"""Noise channel frequency mapping.

mmlgb treats the noise channel as a smooth, continuous 8-octave chromatic
scale (see mmlgb-src/scripts/gen_noise.py / driver/noisefreq.c), computing a
standard Game Boy noise-channel NR43 byte directly via
bitmask(r,s) = (s<<4)|r, for r = 8-octave, s = 15-note_index.

The target WLA sound engine's noise channel (verified against the reference
audio/common/noise.s) instead only has a small, fixed palette of hand-tuned
noise "notes" -- specific (envelope, NR43) pairs picked for particular drum
sounds (crash, snare, dash noise, digging, etc.), not derived from any
smooth scale. We map any mmlgb noise pitch to whichever of those fixed
entries has the closest *actual hardware frequency* -- both tables decode to
the same NR43 register format, so this is an apples-to-apples comparison,
using log-frequency distance for perceptual nearness. This is necessarily a
many-to-one quantization: nearby octaves can legitimately land on the same
output note, and there is no way to get a finer-grained noise "pitch" than
whatever the target engine's fixed table offers.
"""

import math
from typing import List, Tuple


def _noise_freq(r: int, s: int) -> float:
    if r == 0:
        r = 0.5
    return 524228.0 / r / (2 ** (s + 1))


def _mmlgb_noise_rs(octave: int, note_index: int):
    """Returns (r, s) for a given noise "octave" (1-10) and note index
    (0-11), matching mmlgb's noisefreq table construction exactly."""
    if 1 <= octave <= 8:
        return 8 - octave, 15 - note_index
    if octave == 9:
        # Extended table: values 55,54,...,20 stepping across 3 groups of 4.
        i, j = divmod(note_index, 4)
        byte = 56 - i * 16 - j - 1
        return None, byte  # raw NR43 byte, not a clean (r,s) pair
    if octave == 10:
        byte = max(1, 7 - note_index)
        return None, byte
    raise ValueError(f"noise octave {octave} out of range")


def mmlgb_noise_exact_nr43(octave: int, note_index: int) -> int:
    """The exact NR43 byte mmlgb itself would use for this noise pitch (not
    a nearest-match against a fixed palette -- used when proposing brand
    new noise-table entries, which can represent any (r,s) pair exactly)."""
    octave = max(1, min(10, octave))
    r, s_or_byte = _mmlgb_noise_rs(octave, note_index)
    if r is None:
        return s_or_byte
    return (s_or_byte << 4) | r


def mmlgb_noise_target_freq(octave: int, note_index: int) -> float:
    octave = max(1, min(10, octave))
    r, s_or_byte = _mmlgb_noise_rs(octave, note_index)
    if r is None:
        byte = s_or_byte
        return _noise_freq(byte & 0x7, byte >> 4)
    return _noise_freq(r, s_or_byte)


class NoiseTable:
    """A target engine's fixed noise-note palette: (note_byte, nr43_byte)
    pairs, decoded to their real hardware frequency for nearest-match
    lookup. Populate from whatever reference noise.s the target project
    uses."""

    def __init__(self, entries: List[Tuple[int, int]]):
        # entries: (note_byte, nr43_byte)
        self._freqs = [(note, _noise_freq(nr43 & 0x7, nr43 >> 4)) for note, nr43 in entries]

    def nearest(self, octave: int, note_index: int) -> int:
        target = mmlgb_noise_target_freq(octave, note_index)
        log_target = math.log(target) if target > 0 else -999.0
        best_note, best_dist = None, None
        for note, freq in self._freqs:
            d = abs((math.log(freq) if freq > 0 else -999.0) - log_target)
            if best_dist is None or d < best_dist:
                best_dist = d
                best_note = note
        return best_note


# Reference noise table decoded directly from audio/common/noise.s in the
# Zelda Oracle of Ages/Seasons disassembly: (note_byte, envelope_nibble, nr43_byte).
# The envelope nibble isn't used for frequency matching (it's a fixed,
# non-adjustable part of each entry -- see mml2wla_documentation.md) but is
# kept here for reference/documentation purposes.
REFERENCE_NOISE_ENTRIES = [
    (0x24, 0x01, 0x47),
    (0x22, 0x00, 0x47),
    (0x23, 0x02, 0x46),
    (0x26, 0x02, 0x26),
    (0x28, 0x00, 0x35),
    (0x27, 0x02, 0x14),
    (0x2a, 0x01, 0x14),
    (0x2e, 0x06, 0x07),
    (0x52, 0x03, 0x17),
    (0x32, 0x02, 0x37),
    (0x2f, 0x02, 0x45),
    (0x29, 0x02, 0x47),
    (0x30, 0x00, 0x07),
    # Increasing-envelope (fade-in) variants added alongside the engine's new
    # hardware envelope support -- see audio/common/noise.s. Editable-build
    # only (not present in vanilla ROM data), but real entries the noise
    # channel can select once compiled through that build.
    (0x25, 0x09, 0x47),
    (0x2c, 0x09, 0x47),
    (0x2b, 0x0a, 0x37),
]

DEFAULT_NOISE_TABLE = NoiseTable([(note, nr43) for note, _env, nr43 in REFERENCE_NOISE_ENTRIES])

# The complete set of documented, hand-tuned noise pitch bytes this engine's
# noise channel actually supports (from s_file_documentation.mediawikipage's
# "Pitch Macros" section, and matching REFERENCE_NOISE_ENTRIES above exactly).
# Used to sanity-check explicit `n$XX`/alias noise-literal selections in
# parser.py -- not to restrict them, since we can't rule out an undocumented
# byte being intentional, but a value outside this set is unusual enough to
# be worth flagging.
KNOWN_NOISE_FREQUENCIES = frozenset(note for note, _env, _nr43 in REFERENCE_NOISE_ENTRIES)


def load_noise_json(path: str):
    """Loads a noise.json manifest (see audio/common/noise.json in the
    Zelda Oracle of Ages/Seasons disassembly) -- the single source of truth
    REFERENCE_NOISE_ENTRIES above used to be a hand-maintained duplicate of.
    Returns (NoiseTable, known_frequencies, names) -- names maps alias name
    -> note byte, for whoever needs to emit `@alias = n$XX` definitions
    (see sToMml.py's render()); an entry with no "name" field just
    contributes to the table/known-frequencies set, not to that dict.
    `editableOnly` entries (the hardware fade-in variants, not present in
    vanilla ROM data) are included here unconditionally -- it's only
    tools/audio/noiseJsonToS.py's generated noise.s that actually needs to
    gate them behind `.ifndef BUILD_VANILLA`."""
    import json
    with open(path) as f:
        entries = json.load(f)
    table_entries = [(e['note'], e['nr43']) for e in entries]
    known = frozenset(e['note'] for e in entries)
    names = {e['name']: e['note'] for e in entries if 'name' in e}
    return NoiseTable(table_entries), known, names
