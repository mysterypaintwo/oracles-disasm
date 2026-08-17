"""Infers a plausible tempo (and, from it, a measure length in frames) for
a vanilla song's raw frame-length data, purely so sToMml.py can insert
readable line breaks at measure boundaries instead of emitting one giant
line per channel.

Vanilla data has no tempo concept at all -- every length byte already is a
literal frame count (see code/audio.s). There's no way to recover the
composer's *actual* intended tempo from that alone. What this does instead
is search the Game Boy hardware timer's own discrete quantization steps
(see mml2wla/timing.py's real_seconds_per_tick) for whichever one makes the
most of a song's observed frame lengths line up closely with a musically
clean number of 192-ticks-per-whole-note ticks -- i.e., the tempo grid the
song most plausibly would have been authored on. This is a readability
heuristic only: line breaks are pure whitespace to the parser, so getting
this approximately right (not byte-exact) is all that's needed. Every note
still keeps its own exact frame length via `=N` regardless of where the
line breaks fall -- this module never changes what a note sounds like.

Time signature: assumed 4/4 (one measure = 192 ticks, i.e. exactly one
whole note) by default; TIME_SIG_OVERRIDES lets specific songs be told
otherwise once someone's actually listened and confirmed it, rather than
trying to auto-detect a time signature from frame lengths alone.
"""
from mml2wla.timing import GB_FRAME_RATE, TIMA_SPEED, BEAT_STEPS

BAR_STEPS = 192  # ticks per whole note == ticks per measure in 4/4

# value -> ticks, per mmlgb_documentation.md's "Note length" table -- used
# only to define what counts as a "musically clean" tick value for scoring
# candidate tempos, not for note notation (every note still emits =N).
BASE_LENGTHS = {1: 192, 2: 96, 3: 64, 4: 48, 6: 32, 8: 24, 12: 16, 16: 12, 24: 8, 32: 6}
_CLEAN_TICKS = []
for _ticks in BASE_LENGTHS.values():
    _CLEAN_TICKS.append(_ticks)
    half = _ticks // 2
    if half * 2 == _ticks:
        _CLEAN_TICKS.append(_ticks + half)  # dotted

from songConfig import TIME_SIG_OVERRIDES, ECHO_CHANNELS  # noqa: E402

# Real game music tempos live in roughly this range; searching outside it
# is actively counterproductive, not just unnecessary -- a tiny enough
# frames-per-tick blows every raw length up into a huge tick count, and
# rounding error trivially (and meaninglessly) looks great for *any* data
# once ticks are in the thousands. Bounding the search to musically real
# tempos is what keeps the fit meaningful.
MIN_BPM, MAX_BPM = 40, 300


def mod_to_bpm(mod: int) -> float:
    """The exact BPM that reproduces this integer TMA-reload distance when
    fed back through real_seconds_per_tick's own round(TIMA_SPEED/ups)
    quantization -- see timing.py's real_seconds_per_tick docstring."""
    ups = TIMA_SPEED / mod
    return ups * 60.0 / BEAT_STEPS


def frames_per_tick_for_mod(mod: int) -> float:
    real_ticks_per_sec = TIMA_SPEED / (mod + 1)
    return GB_FRAME_RATE / real_ticks_per_sec


def _nearest_clean_tick_distance(ticks: float) -> float:
    """Relative distance from `ticks` to whichever musically clean tick
    value is closest -- this is what actually distinguishes a plausible
    tempo from an implausible one; distance to the nearest *integer* can't
    tell them apart, since every tempo rounds equally well to some integer."""
    best = None
    for t in _CLEAN_TICKS:
        d = abs(ticks - t) / t
        if best is None or d < best:
            best = d
    return best


def estimate_tempo(all_frame_lengths):
    """Returns (bpm, frames_per_tick) for whichever hardware timer setting
    (restricted to a musically plausible tempo range) makes the most of
    this song's frame lengths land closest to a musically clean tick
    value, scored by relative (not absolute) distance so a quarter note
    landing 0.4 frames off isn't drowned out by a 32nd note landing 0.4
    frames off (proportionally far worse for the latter)."""
    lo_ups = (MIN_BPM / 60.0) * BEAT_STEPS
    hi_ups = (MAX_BPM / 60.0) * BEAT_STEPS
    mod_hi = max(1, round(TIMA_SPEED / lo_ups))
    mod_lo = max(1, round(TIMA_SPEED / hi_ups))
    best = None
    for mod in range(mod_lo, mod_hi + 1):
        fpt = frames_per_tick_for_mod(mod)
        score = 0.0
        for length in all_frame_lengths:
            score += _nearest_clean_tick_distance(length / fpt)
        if best is None or score < best[0]:
            best = (score, mod, fpt)
    _, mod, fpt = best
    return mod_to_bpm(mod), fpt


def measure_length_frames(fpt: float, file_base: str) -> float:
    ticks_per_measure = TIME_SIG_OVERRIDES.get(file_base, BAR_STEPS)
    return ticks_per_measure * fpt


def check_alignment(total_frames: float, measure_frames: float, tolerance: float = 0.05):
    """Whether a segment's total length divides evenly into whole measures
    at the given measure length, within `tolerance` relative error.
    Returns (is_aligned, nearest_whole_measure_count, relative_error) --
    used by checkAlignment.py to flag songs whose real time signature (or
    an echoing channel -- see songConfig.py) doesn't match the 4/4
    default, for a human to confirm and record an override."""
    if measure_frames <= 0 or total_frames <= 0:
        return True, 0, 0.0
    measures = total_frames / measure_frames
    rounded = max(1, round(measures))
    error = abs(measures - rounded) / rounded
    return error <= tolerance, rounded, error


def _forward_breaks(lengths, measure_frames: float):
    breaks = set()
    total = 0.0
    next_boundary = measure_frames
    for i, length in enumerate(lengths):
        total += length
        if total >= next_boundary:
            breaks.add(i)
            while next_boundary <= total:
                next_boundary += measure_frames
    return breaks


def insert_linebreaks(lengths, measure_frames: float, loop_index=None):
    """Given one channel's tick-consuming events' raw frame lengths (in
    playback order), returns the set of indices *after* which a line break
    reads best -- i.e. wherever cumulative elapsed frames first reaches or
    passes each successive measure boundary. Purely a readability grouping
    -- an event's own frame length is never touched by this.

    `loop_index`, if given, is the position of this channel's own loop
    point (the 'L' marker) in `lengths`: the segment from there to the end
    is measure-aligned forward from the loop point itself (0 there), and
    the segment before it (the intro) is aligned *backward* from the loop
    point instead of forward from the very start. This matters because the
    loop point -- not the very first note -- is the one boundary
    guaranteed to land on a real measure line (the loop has to tile
    cleanly to repeat correctly); a song's intro very often leads into it
    with an anacrusis (a pickup phrase shorter than a full measure), which
    forward-from-0 alignment would otherwise cut at the wrong points."""
    if loop_index is None or loop_index == 0:
        return _forward_breaks(lengths, measure_frames)

    intro, loop = lengths[:loop_index], lengths[loop_index:]
    # A break at reversed-index k means "the last (k+1) original elements
    # sum to a measure" -- i.e. the boundary falls right before original
    # index n-1-k, so (using this function's own "break after index i"
    # convention) at original index n-2-k. k == n-1 (everything consumed)
    # maps to index -1, meaning "break before the very first element",
    # which isn't a real break -- that's the anacrusis remainder, left
    # untouched.
    intro_breaks_from_end = _forward_breaks(list(reversed(intro)), measure_frames)
    n = len(intro)
    breaks = {n - 2 - k for k in intro_breaks_from_end if k != n - 1}
    loop_breaks = _forward_breaks(loop, measure_frames)
    breaks |= {loop_index + i for i in loop_breaks}
    return breaks
