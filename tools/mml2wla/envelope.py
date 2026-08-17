"""Volume envelope translation for the square channels.

mmlgb's `@ve[n]` writes straight to the real Game Boy hardware envelope
register (verified against mmlgb-src/driver/music.c: `NRx2_REG = mus_volume
| mus_env`, with `mus_env` being exactly the signed pace byte from `@ve`).
On real hardware this means: the note starts at whatever volume `v` set,
and the hardware envelope steps it toward 15 (increasing) or 0 (decreasing)
once every `pace/64` seconds, entirely in hardware, no software involved.

The target engine's `env` command drives the *same* real hardware envelope
register, but through a very different, two-phase, software-orchestrated
state machine (traced through code/audio.s's `handleEnvelopes` and
`getWaitTimeForEnvelope`):

- `env`'s second argument (decay) is an *exact* match for mmlgb's
  decreasing `@ve`: it writes the hardware envelope directly, starting at
  the note's target volume, decreasing at the given pace, and then lets it
  run to completion in hardware with no further software involvement --
  structurally identical to what mmlgb does.
- `env`'s first argument (attack) is *not* a direct match for mmlgb's
  increasing `@ve`. The engine hard-codes the attack's *starting* volume to
  1 (not whatever `vol` last set) and ramps *up to* the target volume from
  `vol` (not up to 15). It tracks how long this should take using its own
  `envelopeWaitTable` (indexed by target volume, capped at 13 -- volumes 14
  and 15 have no table row at all, a real limitation/bug in the reference
  engine itself), then forces the volume to the exact target once that
  timer expires. So there is no pace value that reproduces mmlgb's
  increasing envelope exactly; the closest available approximation is to
  pick whichever attack pace makes the engine's own (1 -> target) sweep
  take about the same real-world *duration* as mmlgb's (v -> 15) sweep
  would have, so the swell's speed reads similarly even though its range
  and starting point don't match.
"""

from typing import Optional, Tuple

from .timing import GB_FRAME_RATE

GB_ENVELOPE_HZ = 64.0  # real Game Boy envelope sweep clock, fixed in hardware

# Reference engine's envelopeWaitTable (code/audio.s): wait time, in ~frames,
# for the attack phase to climb from volume 1 to the target volume (rows,
# 0-13) at a given hardware envelope pace (columns, 0-7). Column 0 (pace 0)
# is unused -- a zero attack pace never triggers the attack phase at all.
ENVELOPE_WAIT_TABLE = [
    [0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07],
    [0x00, 0x02, 0x04, 0x06, 0x07, 0x09, 0x0b, 0x0d],
    [0x00, 0x03, 0x06, 0x08, 0x0b, 0x0e, 0x11, 0x14],
    [0x00, 0x04, 0x07, 0x0b, 0x0f, 0x13, 0x16, 0x1a],
    [0x00, 0x05, 0x09, 0x0e, 0x13, 0x17, 0x1c, 0x21],
    [0x00, 0x06, 0x0b, 0x11, 0x16, 0x1c, 0x22, 0x27],
    [0x00, 0x07, 0x0d, 0x14, 0x1a, 0x21, 0x27, 0x2e],
    [0x00, 0x07, 0x0f, 0x16, 0x1e, 0x25, 0x2d, 0x34],
    [0x00, 0x08, 0x11, 0x19, 0x22, 0x2a, 0x32, 0x3b],
    [0x00, 0x09, 0x13, 0x1c, 0x25, 0x2f, 0x38, 0x41],
    [0x00, 0x0a, 0x15, 0x1f, 0x29, 0x33, 0x3e, 0x48],
    [0x00, 0x0b, 0x16, 0x22, 0x2d, 0x38, 0x43, 0x4e],
    [0x00, 0x0c, 0x18, 0x24, 0x31, 0x3d, 0x49, 0x55],
    [0x00, 0x0d, 0x1a, 0x27, 0x34, 0x41, 0x4e, 0x5b],
]


def best_attack_pace(target_vol: int, mmlgb_pace: int) -> Tuple[Optional[int], Optional[str]]:
    """Returns (engine_attack_pace, warning_or_None). `engine_attack_pace`
    is None when no attack should be emitted at all: either because mmlgb's
    own envelope would have had nothing left to climb (target_vol == 15,
    silently skipped, matching mmlgb exactly), or because target_vol is 14
    and the engine's own timing table has no row for it (warned)."""
    if target_vol >= 15:
        return None, None
    if target_vol == 14:
        return None, (
            "increasing volume envelope requested at volume 14, but this engine's "
            "envelope-timing table has no row for volumes 14-15 (a limitation in the "
            "reference engine itself); envelope dropped for this note")

    steps = 15 - target_vol
    mmlgb_seconds = steps * (mmlgb_pace / GB_ENVELOPE_HZ)
    mmlgb_frames = mmlgb_seconds * GB_FRAME_RATE

    row = ENVELOPE_WAIT_TABLE[target_vol]
    best_pace, best_dist = None, None
    for pace in range(1, 8):
        dist = abs(row[pace] - mmlgb_frames)
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_pace = pace
    return best_pace, None
