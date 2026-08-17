"""Cross-channel, chronological tempo resolution.

mmlgb's `t` (tempo) command is global: real hardware has exactly one shared
tempo clock (a single programmable timer interrupt -- see
mmlgb-src/driver/music.c's `mus_init`/TAC setup) driving all four channels'
countdowns at once. A `t` command compiles into a byte in whichever
channel's own data stream it was written on (confirmed against
mmlgb-src/parser/src/Parser.cs: `song.AddData(active, ...)` only touches the
channel(s) active on that line), and takes effect for every channel starting
at the real-time moment *that* channel's own playback reaches it -- not
wherever it happens to sit in the source text, and not just for whichever
channel wrote it.

That has a consequence beyond simple ordering: since every channel's note
countdown ticks against the *same* clock, a tempo change on one channel can
land in the middle of another channel's still-playing note. On real
hardware that note's remaining ticks genuinely play out at the new rate --
there's no such thing as "this note's tempo," only "the tempo, whatever it
is at each tick." So resolving a note to one flat bpm for its whole
duration is only an approximation; if a tempo change falls inside that
note's span, the correct frame count is a *blend*: part of the note's ticks
converted at the old rate, the rest at the new one, summed together.

This module handles both problems with one discrete-event simulation: walk
all four channels' fully-unrolled event streams together, always advancing
toward whichever channel's own elapsed real time is currently smallest,
applying `tempo` events the instant they're chronologically reached
(regardless of which channel wrote them) -- and whenever one lands inside
another channel's already-started note, checkpointing that note's progress
so its eventual frame count correctly blends every tempo that was active
across its span.
"""

from typing import List, Optional, Tuple

from .parser import Ev, RepeatBlock, DEFAULT_TEMPO_BPM
from .timing import real_seconds_per_tick, GB_FRAME_RATE

# Event kinds whose `ticks` field advances that channel's own real-time
# cursor (they occupy real playback time on that channel).
_TICK_KINDS = {'note', 'noise_literal', 'rest', 'wait'}
# Field index (Ev.a/.b/.c/.d) holding the ticks value, per kind.
_TICKS_FIELD = {'note': 'c', 'noise_literal': 'b', 'rest': 'a', 'wait': 'a'}


def flatten_tree(tree: list) -> List[Ev]:
    """Fully unrolls RepeatBlocks (respecting `.count`), returning every
    leaf Ev in true playback order -- the same order `ChannelEmitter`'s own
    tree walk visits them in, which is what makes it safe to hand this
    function's output (or values derived from it) to the emitter as a
    plain, in-order queue."""
    out: List[Ev] = []
    for node in tree:
        if isinstance(node, RepeatBlock):
            for _ in range(node.count):
                out.extend(flatten_tree(node.children))
        else:
            out.append(node)
    return out


def resolve_tempo(trees: List[list]) -> List[List[float]]:
    """Given the 4 channels' structured (unroll-ready) trees, in A/B/C/D
    order, returns one resolved value per tick-consuming event
    (note/noise_literal/rest/wait) and per vibrato event, per channel, in
    that channel's own playback order -- ready to be consumed as a plain
    queue (one `next()` per such event) by the emitter, in place of the bpm
    each event's own Ev carries (which only reflects source-text order, not
    real chronological order -- see module docstring).

    For a tick-consuming event, the value is an *exact frame count*
    (float, not yet rounded -- feed it to FrameResolver.resolve_exact),
    already blended across any tempo change(s) that occurred mid-event. For
    a vibrato event, the value is a plain bpm (its delay isn't part of the
    channel's additive timeline -- see timing.py -- so there's nothing to
    blend; it just needs whatever tempo is chronologically current).
    """
    flat = [flatten_tree(t) for t in trees]
    cursors = [0, 0, 0, 0]
    real_time = [0.0, 0.0, 0.0, 0.0]
    # None, or (remaining_ticks, accumulated_exact_frames) for a
    # tick-consuming event that's been partially resolved already because
    # some other channel's tempo change landed inside it.
    in_progress: List[Optional[Tuple[float, float]]] = [None, None, None, None]
    resolved: List[List[float]] = [[], [], [], []]
    global_bpm = DEFAULT_TEMPO_BPM

    def checkpoint(other: int, at_time: float):
        """Partially advances `other`'s current (fresh or in-progress)
        tick-consuming event up to `at_time`, at the tempo active up to
        now, folding the covered portion into its accumulated frame total.
        No-op if `other`'s current event isn't a tick-consuming one, or
        hasn't started yet."""
        if cursors[other] >= len(flat[other]) or real_time[other] >= at_time:
            return
        if in_progress[other] is not None:
            remaining_ticks, accum = in_progress[other]
        else:
            oev = flat[other][cursors[other]]
            if oev.kind not in _TICK_KINDS:
                return
            remaining_ticks, accum = getattr(oev, _TICKS_FIELD[oev.kind]), 0.0
        spt = real_seconds_per_tick(global_bpm)
        coverable_ticks = min(remaining_ticks, (at_time - real_time[other]) / spt)
        frames_partial = coverable_ticks * spt * GB_FRAME_RATE
        in_progress[other] = (remaining_ticks - coverable_ticks, accum + frames_partial)
        real_time[other] = at_time

    while True:
        active = [ch for ch in range(4) if cursors[ch] < len(flat[ch])]
        if not active:
            break

        boundaries = []  # (projected_time, ch, is_instant)
        for ch in active:
            if in_progress[ch] is not None:
                remaining_ticks, _ = in_progress[ch]
                t = real_time[ch] + remaining_ticks * real_seconds_per_tick(global_bpm)
                boundaries.append((t, ch, False))
                continue
            ev = flat[ch][cursors[ch]]
            if ev.kind in _TICK_KINDS:
                ticks = getattr(ev, _TICKS_FIELD[ev.kind])
                t = real_time[ch] + ticks * real_seconds_per_tick(global_bpm)
                boundaries.append((t, ch, False))
            else:
                # tempo, vibrato, or any other instantaneous kind (vol/env/
                # wd/wave_select(_const)/loop/comment): zero duration.
                boundaries.append((real_time[ch], ch, True))

        min_t = min(b[0] for b in boundaries)
        at_min = [b for b in boundaries if b[0] == min_t]
        # Among ties, an instant event must go first -- see module
        # docstring and _emit_ev's `loop`-reset comment for the same
        # principle applied elsewhere: nothing tick-consuming may advance
        # past a chronologically-simultaneous instant event.
        instants = [b for b in at_min if b[2]]
        _, ch, is_instant = instants[0] if instants else at_min[0]
        ev = flat[ch][cursors[ch]]

        if is_instant:
            if ev.kind == 'tempo':
                new_bpm = ev.a
                if new_bpm != global_bpm:
                    for other in range(4):
                        if other != ch:
                            checkpoint(other, min_t)
                global_bpm = new_bpm
            elif ev.kind == 'vibrato':
                resolved[ch].append(global_bpm)
            cursors[ch] += 1
            continue

        # A tick-consuming event reaching its own (uninterrupted) natural
        # completion: this boundary is the global minimum, so nothing else
        # is chronologically due before it -- safe to finish it now.
        if in_progress[ch] is not None:
            remaining_ticks, accum = in_progress[ch]
        else:
            remaining_ticks, accum = getattr(ev, _TICKS_FIELD[ev.kind]), 0.0
        spt = real_seconds_per_tick(global_bpm)
        exact_frames = accum + remaining_ticks * spt * GB_FRAME_RATE
        resolved[ch].append(exact_frames)
        real_time[ch] += remaining_ticks * spt
        in_progress[ch] = None
        cursors[ch] += 1

    return resolved
