"""Tick/frame timing conversion.

mmlgb expresses note lengths in a tempo-independent tick unit: 192 ticks per
whole note (BAR_STEPS), 48 ticks per quarter note/beat (BEAT_STEPS) -- this
is where the `l`/length-denominator table in the MML docs comes from, and it
never changes regardless of the `t` (tempo) command.

Target WLA-DX sound engines of the kind this tool generates for (e.g. the
Zelda Oracle of Ages/Seasons disassembly's audio engine) have no such tick
concept at all: every length byte in the channel data *is* a literal count
of game frames (~59.7Hz on real Game Boy hardware) to hold a note/rest for,
with no runtime tempo register. So converting means resolving mmlgb's
tempo-independent ticks into an absolute frame count for whatever `t` (BPM)
is active at that point in the source.

Two things make this trickier than a single multiply-and-round:

1. mmlgb's own tempo command does not produce an exact BPM on real hardware.
   `t` sets a Game Boy hardware timer (TAC clock = 4096Hz) reload value that
   must be a whole number, so the real tick rate it produces is quantized
   and comes out slightly different from the requested BPM (e.g. `t140`
   plays at ~134.7 BPM, not 140). We replicate that exact quantization
   (verified against mmlgb-src/driver/music.c's `mus_init` and
   mmlgb-src/parser/src/Parser.cs's tempo command) so a converted song's
   overall pace matches how mmlgb actually played it, not an idealized BPM.

2. Rounding each note's length independently to the nearest frame introduces
   up to ±0.5 frames of error *per note*. Do that with no correction and the
   error accumulates without bound over a whole song -- on a channel with
   many short notes this becomes audible, and because different channels
   have different rhythms, their accumulated errors diverge from each
   other, so the channels drift out of sync with each other over time (this
   is what caused a reported "channels playing horribly out of sync" bug).
   The fix is a standard error-carry technique: track the leftover
   fractional frame after each rounding decision and fold it into the next
   one, so error never accumulates past +-1 frame no matter how long the
   sequence runs. See `FrameResolver` below.
"""

import math

BAR_STEPS = 192      # ticks per whole note
BEAT_STEPS = 48       # ticks per quarter note / beat (mmlgb "BEAT_STEPS")
TIMA_SPEED = 4096.0   # Game Boy TAC clock selected by the mmlgb driver (TAC=$04)

# Real Game Boy frame rate: one frame = 154 scanlines * 456 T-cycles, at the
# 4194304Hz system clock.
GB_FRAME_RATE = 4194304.0 / 70224.0  # ~59.7275 Hz

MAX_CMD_LENGTH = 255  # max single-byte length ever emitted (never emit the
                       # $00-means-256 underflow trick -- see chunk_length)


def real_seconds_per_tick(bpm: float) -> float:
    """How long one mmlgb tick (1/48 of a beat) actually lasts on real
    hardware for a given `t` (BPM) command, including the same integer
    timer-reload quantization mmlgb-src/parser/src/Parser.cs performs:

        ups = (bpm/60) * BEAT_STEPS          # requested ticks/sec
        mod = round(TIMA_SPEED / ups)        # integer TMA reload distance
        real_ticks_per_sec = TIMA_SPEED / (mod + 1)

    The `+ 1` matters: mmlgb stores `255 - mod` into the hardware TMA
    register (an 8-bit timer-modulo). TIMA counts up from TMA and fires an
    interrupt on overflow past 255, i.e. after (256 - TMA) = (mod + 1)
    ticks of the base clock -- not `mod` ticks.
    """
    ups = (bpm / 60.0) * BEAT_STEPS
    mod = round(TIMA_SPEED / ups)
    real_ticks_per_sec = TIMA_SPEED / (mod + 1)
    return 1.0 / real_ticks_per_sec


def ticks_to_frames_exact(ticks: float, bpm: float) -> float:
    """Exact (unrounded) frame count for `ticks` mmlgb ticks at `bpm`."""
    seconds = ticks * real_seconds_per_tick(bpm)
    return seconds * GB_FRAME_RATE


def chunk_length(total: int):
    """Split a frame count into a sequence of <=255 chunks (never emitting
    the $00-means-256 underflow trick), matching real disassembly usage
    (e.g. a long rest written by hand as `rest $ff` + `rest $25`)."""
    if total <= 0:
        return []
    chunks = []
    remaining = total
    while remaining > MAX_CMD_LENGTH:
        chunks.append(MAX_CMD_LENGTH)
        remaining -= MAX_CMD_LENGTH
    if remaining > 0:
        chunks.append(remaining)
    return chunks


class FrameResolver:
    """Per-channel error-carry rounder: converts a sequence of (ticks, bpm)
    lengths into frame counts whose cumulative timeline tracks the exact
    (unrounded) timeline to within +-1 frame forever, instead of drifting.

    Must be fed lengths *in playback order* for one channel. Two independent
    FrameResolver instances (or two independently-ordered passes through the
    same one, see `snapshot`/`restore`) will not necessarily produce the
    same rounding decisions partway through if their carry states differ --
    this is expected and is exactly what lets `.rept`-vs-literal-expansion
    be decided correctly (see emitter.py).
    """

    __slots__ = ('carry',)

    def __init__(self, carry: float = 0.0):
        self.carry = carry

    def resolve(self, ticks: float, bpm: float) -> int:
        exact = ticks_to_frames_exact(ticks, bpm)
        total = exact + self.carry
        frames = max(1, round(total))
        self.carry = total - frames
        return frames

    def resolve_exact(self, exact_frames: float) -> int:
        """Like `resolve`, but takes an already-computed exact (unrounded)
        frame value directly, for callers that need to blend more than one
        tempo across a single event's duration (see tempo.py -- a note can
        span a tempo change declared on a different channel partway
        through its own length) instead of one (ticks, bpm) pair."""
        total = exact_frames + self.carry
        frames = max(1, round(total))
        self.carry = total - frames
        return frames

    def resolve_no_carry(self, ticks: float, bpm: float) -> int:
        """Plain rounding with no error-carry bookkeeping, for values that
        aren't part of a channel's additive timeline (e.g. a vibrato
        delay -- it doesn't extend how long the channel is "busy", so
        folding its rounding error into the next note's carry would leak
        timing debt into an unrelated parameter)."""
        return max(1, round(ticks_to_frames_exact(ticks, bpm)))

    def snapshot(self) -> float:
        return self.carry

    def restore(self, carry: float):
        self.carry = carry
