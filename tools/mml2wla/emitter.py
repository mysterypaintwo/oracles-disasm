"""Walks a channel's structured event tree and produces WLA-DX text using
the target engine's real macros (note/rest/rest2/vol/env/duty/vibrato/goto/
cmdff), matching the reference disassembly's own mus/*.s conventions.

This is where tick lengths finally get resolved into frame counts (see
timing.py for why that has to happen here rather than during parsing): each
channel gets its own FrameResolver carrying rounding error forward so the
channel's cumulative timeline never drifts, no matter how many notes it has.

Repeat blocks (`[...]n` in the source) get special handling for the same
reason. WLA's `.rept` duplicates literal bytes -- it cannot represent
"repeat this pattern, but round slightly differently each time to stay in
sync," which is what fully-accurate playback calls for whenever a block's
iterations don't round identically (they only do by coincidence: the real
Game Boy frame rate, 4194304/70224 Hz, reduces to a fraction with a
denominator of 3*7*11*19, so an exact repeat requires a fairly specific
relationship between a block's tick length and the current tempo). Rather
than approximate that away, every repeat block is unrolled: each iteration
is rendered independently with the carry evolving with full accuracy
across all of them, with no tolerance involved at all. (An earlier version
of this tool allowed a small, bounded amount of drift here in exchange for
more `.rept` output; that traded away exactly the guarantee this timing
model exists to provide; a converted song audibly sounding "off" in-game
after that change was the concrete signal that the tradeoff wasn't worth
it, so it's gone.)

A second, independent, genuinely lossless pass (_collapse_repeated_lines)
then scans each channel's *fully rendered* output for any run of
literally-identical consecutive lines -- from repeat blocks whose
iterations happened to round identically anyway, from a repeated `@@`
macro call inlined at multiple sites, or from coincidentally-identical
default-length notes -- and merges it into `.rept`. Since it only ever
compares text that's already been computed with full accuracy, this one
involves no approximation at all.

Separately, redundant `vol`/`duty`/`vibrato`/`env` assignments (re-issuing
a value a channel already has) are dropped outright, since they're
confirmed no-ops on real hardware (see _emit_env's comment for why this is
true of `env` too, despite looking at first glance like it should restart
something). This tracking resets at the loop point (see `_emit_ev`'s `loop`
case): a command there that looks redundant against the intro's history
isn't provably redundant against how the loop body itself left that state
on the previous lap, so the first occurrence of each kind after the loop
label is always kept.
"""

from typing import List, Optional, Tuple

from .parser import Ev, RepeatBlock, Song, structure
from .timing import FrameResolver, chunk_length
from .notes import resolve_pitch
from .noise import DEFAULT_NOISE_TABLE, NoiseTable
from .waveforms import WaveformAggregator
from .envelope import best_attack_pace
from .noise_envelope import NoiseEnvelopeAggregator
from .tempo import resolve_tempo

DEFAULT_VOLUME = 15  # matches mmlgb driver default (mus_volume1/2/4 = 0xF0)

# MML channel index (0=A,1=B,2=C,3=D) -> target engine music channel number.
CHANNEL_NUM = {0: 0, 1: 1, 2: 4, 3: 6}
# Emission order matches the convention used by every real reference example
# (melody/square2 first, then square1, then wave, then noise).
CHANNEL_EMIT_ORDER = [1, 0, 2, 3]


# Max size (in lines) of a repeating chunk this pass will look for. Bounded
# purely to keep the O(lines * chunk_size) scan fast on large songs; the
# reference disassembly's own hand-written `.rept` blocks are a handful of
# lines, so this comfortably covers realistic musical phrases.
_COLLAPSE_MAX_CHUNK = 64


def _is_hard_boundary(line: str) -> bool:
    # Labels (e.g. a loop point) and existing .rept/.endr markers must never
    # end up straddled or duplicated by a chunk from this pass.
    return line.endswith(':') or line.startswith('.rept') or line == '.endr'


def _collapse_repeated_lines(lines: List[str]) -> List[str]:
    """Replaces any run of literally-identical consecutive line-groups with
    `.rept N ... .endr`. Purely a text-level exact-equality compression: it
    never reinterprets or adjusts any already-computed value, so unlike the
    tolerance-bounded repeat-block handling above, this never trades away
    any timing accuracy -- it only ever merges output that was already
    going to play back identically. This is what actually catches most
    real-world compaction opportunities in practice, since it doesn't care
    what produced the repetition: an explicit `[...]n` block, a repeated
    `@@` macro call, or coincidentally-identical runs of same-length,
    same-pitch notes are all found the same way.
    """
    out: List[str] = []
    n = len(lines)
    i = 0
    while i < n:
        if _is_hard_boundary(lines[i]):
            out.append(lines[i])
            i += 1
            continue

        best_chunk, best_reps, best_savings = None, None, 0
        max_chunk = min(_COLLAPSE_MAX_CHUNK, (n - i) // 2)
        for chunk in range(1, max_chunk + 1):
            if any(_is_hard_boundary(l) for l in lines[i:i + chunk]):
                break  # larger chunk sizes only include more of the same boundary
            reps = 1
            while (i + (reps + 1) * chunk <= n and
                   lines[i + reps * chunk: i + (reps + 1) * chunk] == lines[i:i + chunk]):
                reps += 1
            if reps >= 2:
                savings = chunk * (reps - 1) - 2  # 2 lines of overhead: .rept/.endr
                if savings > best_savings:
                    best_chunk, best_reps, best_savings = chunk, reps, savings

        if best_chunk is not None:
            out.append(f".rept {best_reps}")
            out.extend(lines[i:i + best_chunk])
            out.append(".endr")
            i += best_chunk * best_reps
        else:
            out.append(lines[i])
            i += 1
    return out


class ChannelEmitter:
    def __init__(self, song: Song, label_name: str, file_base: str, ch: int,
                 waveform_agg: WaveformAggregator, noise_table: NoiseTable,
                 noise_envelope_agg: Optional[NoiseEnvelopeAggregator] = None,
                 fix_rest_blip: bool = False, resolved_iter=None):
        self.song = song
        self.label_name = label_name
        self.file_base = file_base
        self.ch = ch
        self.engine_ch = CHANNEL_NUM[ch]
        self.waveform_agg = waveform_agg
        self.noise_table = noise_table
        self.noise_envelope_agg = noise_envelope_agg
        self.fix_rest_blip = fix_rest_blip
        # One resolved value per tick-consuming/vibrato event on this
        # channel, in playback order, from tempo.resolve_tempo -- NOT each
        # event's own Ev.bpm field, which only reflects source-text order
        # and is wrong whenever a tempo change lives on a different channel
        # (or lands mid-note) than the one reading it (see tempo.py's
        # module docstring). For note/noise_literal/rest/wait, the value is
        # an *exact frame count* already blended across any tempo change
        # that landed mid-event -- feed it to `resolver.resolve_exact`, not
        # `resolver.resolve`. For vibrato, it's a plain bpm, unchanged.
        self.resolved_iter = iter(resolved_iter) if resolved_iter is not None else None
        self.lines: List[str] = []
        self.wave_id: Optional[int] = None
        self.wave_is_const: bool = False  # True after a @wave[LABEL] select
        self.wave_vol: int = 3  # matches mmlgb driver default (100%)
        self.cur_vol: int = DEFAULT_VOLUME  # square/noise channels only
        self.noise_pace: int = 0  # noise channel only, used only when noise_envelope_agg is set
        self.noise_dir: Optional[str] = None
        self._last_duty_key: Optional[Tuple] = None
        # Redundant-assignment tracking (square/noise `vol`, square `duty`,
        # `vibrato`): None until the first real command of that kind is
        # seen, so the *first* one is always emitted regardless of its
        # value -- we don't know what the engine's actual register state
        # is before that (unlike mmlgb, nothing here guarantees it starts
        # at any particular default). `env` is deliberately never deduped
        # this way: re-issuing an identical env command still retriggers
        # its attack/decay sequence from scratch, which is not a no-op.
        self._last_emitted_vol: Optional[int] = None
        self._last_emitted_wd: Optional[int] = None
        self._last_emitted_vibrato_byte: Optional[int] = None
        self._last_emitted_env: Optional[Tuple[int, int]] = None
        self._loop_emitted = False
        self.loop_label = f"mus{label_name}Channel{self.engine_ch}Loop"
        self.resolver = FrameResolver()

    def emit(self, tree: list) -> List[str]:
        self._emit_nodes(tree)
        return self.lines

    def _emit_nodes(self, nodes: list):
        i, n = 0, len(nodes)
        while i < n:
            node = nodes[i]
            if isinstance(node, RepeatBlock):
                self._emit_repeat(node)
                i += 1
            elif isinstance(node, Ev) and node.kind == 'rest':
                # Consecutive `rest` events -- whether from one source rest
                # long enough to need several chunks, or from several
                # separate `r` commands back to back -- are grouped and
                # handled together (see _emit_rest_run), since the blip
                # workaround needs to know the *whole* run's chunk count,
                # not just one event's.
                j = i
                chunks: List[int] = []
                while j < n and isinstance(nodes[j], Ev) and nodes[j].kind == 'rest':
                    exact_frames = next(self.resolved_iter)
                    frames = self.resolver.resolve_exact(exact_frames)
                    chunks.extend(chunk_length(frames))
                    j += 1
                self._emit_rest_run(chunks)
                i = j
            else:
                self._emit_ev(node)
                i += 1

    def _emit_rest_run(self, chunks: List[int]):
        if not chunks:
            return
        # Opt-in only (#FIX_REST_BLIP): the workaround costs 2 extra bytes
        # per occurrence (the vol-0 / vol-restore pair) versus plain chained
        # `rest` commands, which adds up across a whole song. Since the
        # blip itself is inaudible-to-minor for most material, defaulting
        # to the smaller, engine-native output and letting a song opt in
        # only where it actually matters keeps insert size down everywhere
        # else.
        if self.fix_rest_blip and self.ch in (0, 1) and len(chunks) > 1:
            self._emit_long_rest_workaround(chunks)
        else:
            for chunk in chunks:
                self.lines.append(f"rest ${chunk:02x}")

    def _emit_repeat(self, block: RepeatBlock):
        # Always unrolled: each iteration is rendered independently so the
        # carry (and therefore each iteration's rounding) evolves with full
        # accuracy across all of them, with no tolerance or approximation
        # involved. An earlier version of this tool traded a small, bounded
        # amount of timing precision here for more `.rept` output on the
        # reasoning that the error was small enough to be inaudible: that
        # traded away exactly the guarantee this project's timing model
        # exists to provide, and it's not this tool's call to make that
        # trade on your behalf. Any iterations that do turn out perfectly
        # identical are still recombined into `.rept` afterward by
        # _collapse_repeated_lines below, with zero risk, since that pass
        # only ever merges text that's already been computed exactly.
        for _ in range(block.count):
            self._emit_nodes(block.children)

    def _render_once(self, nodes: list) -> List[str]:
        saved = self.lines
        self.lines = []
        self._emit_nodes(nodes)
        rendered = self.lines
        self.lines = saved
        return rendered

    def _emit_ev(self, ev: Ev):
        k = ev.kind
        if k == 'note':
            self._emit_note(ev)
        elif k == 'noise_literal':
            self._emit_noise_literal(ev)
        elif k == 'wait':
            exact_frames = next(self.resolved_iter)
            frames = self.resolver.resolve_exact(exact_frames)
            for chunk in chunk_length(frames):
                self.lines.append(f"rest2 ${chunk:02x}")
        elif k == 'tempo':
            pass  # informational only -- already consumed by tempo.resolve_tempo
        elif k == 'vol':
            if self.ch == 2:
                self.wave_vol = ev.a
                if self.wave_is_const:
                    self.song.warn(
                        "volume (v) has no effect on a @wave[LABEL]-selected waveform in this "
                        "engine: volume is baked into the pre-scaled waveform data, and an "
                        "externally-defined label can't be re-scaled here; ignored", ev.line)
                else:
                    self._maybe_emit_duty()
            else:
                self.cur_vol = ev.a
                self._emit_vol_raw(ev.a)
        elif k == 'env':
            self._emit_env(ev)
        elif k == 'wd':
            if ev.a != self._last_emitted_wd:
                self._last_emitted_wd = ev.a
                self.lines.append(f"duty ${ev.a:x}")
        elif k == 'wave_select':
            if ev.a not in self.song.waves:
                self.song.warn(f"@wave{ev.a} was never defined; skipping duty change", ev.line)
                return
            self.wave_id = ev.a
            self.wave_is_const = False
            self._maybe_emit_duty()
        elif k == 'wave_select_const':
            # @wave[LABEL]: references a waveform that already exists
            # elsewhere in the target project (e.g. hand-written into
            # waveform.s), by label -- as opposed to numeric @waveN, which
            # names data defined in this .mml file and gets generated (and
            # deduplicated) via WaveformAggregator. So no aggregator request
            # here: the label is emitted as-is, and no waveform data for it
            # is added to the output waveform list.
            self.wave_id = None  # numeric wave_id no longer applies
            self.wave_is_const = True
            self._maybe_emit_duty_const(ev.a)
        elif k == 'vibrato':
            self._emit_vibrato(ev)
        elif k == 'loop':
            if not self._loop_emitted:
                self.lines.append(f"{self.loop_label}:")
                self._loop_emitted = True
                # Redundant-assignment tracking (see __init__) reflects
                # linear playback history, which is only valid for however
                # the channel actually arrived here. On the first pass
                # through, that's a straight fall-through from the intro; on
                # every later pass, it's a `goto` from the *end* of the loop
                # body -- a different, and from here unknowable, state. A
                # command right after the loop point that happens to match
                # the value already active at the *end of the intro* is
                # therefore not provably redundant: it may be exactly what's
                # needed to re-normalize state that the loop body left
                # different by the time it jumps back. So every kind of
                # redundant-assignment tracking resets here, forcing the
                # next occurrence of each to be emitted regardless of its
                # value. Once that's happened, normal deduping resumes for
                # the rest of the loop body, which is safe: from that point
                # on, every iteration replays the identical sequence of
                # commands, so a repeat with nothing state-changing in
                # between really is a no-op on every iteration alike.
                self._last_emitted_vol = None
                self._last_emitted_wd = None
                self._last_emitted_vibrato_byte = None
                self._last_emitted_env = None
                self._last_duty_key = None
        elif k == 'comment':
            self.lines.append(ev.a)  # already includes the leading ';'
        else:
            raise ValueError(f"internal: unhandled event kind {k!r}")

    def _emit_env(self, ev: Ev):
        if self.ch == 3:
            if self.noise_envelope_agg is not None:
                # --noise-envelope: track it instead of dropping it -- an
                # envelope-affected note requests an exact new table entry
                # in _emit_note below, rather than a nearest-frequency match.
                self.noise_pace = abs(ev.a)
                self.noise_dir = 'inc' if ev.a > 0 else ('dec' if ev.a < 0 else None)
                return
            self.song.warn(
                "volume envelope (@ve) cannot be controlled on the noise channel in this "
                "engine: its envelope pace is fixed per noise type (baked into the noise "
                "table entry chosen for each note's frequency, not settable by command); "
                "dropped. `vol` still works normally on this channel, or pass "
                "--noise-envelope to generate exact new table entries instead.", ev.line)
            return

        if ev.a > 0:
            # Increasing envelope: not a direct match (see envelope.py) --
            # approximated by matching real-world sweep duration instead.
            pace, warning = best_attack_pace(self.cur_vol, ev.a)
            if warning:
                self.song.warn(warning, ev.line)
            start = pace or 0
            end = 0
        else:
            # Decreasing (or disabled) envelope: exact match, direct passthrough.
            start = 0
            end = -ev.a if ev.a < 0 else 0
        # Safe to dedupe like vol/duty/vibrato: confirmed against
        # code/audio.s that the `env` command handler (cmde0Toef) only
        # stores the two values for whichever note triggers next -- it does
        # not itself touch wChannelEnvelopeStates (that only resets, i.e.
        # actually restarts the attack/decay sequence, in the note-trigger
        # path), so re-issuing identical values has no effect to preserve.
        key = (start, end)
        if key != self._last_emitted_env:
            self._last_emitted_env = key
            self.lines.append(f"env ${start:x} ${end:x}")

    def _emit_vol_raw(self, value: int):
        if value != self._last_emitted_vol:
            self._last_emitted_vol = value
            self.lines.append(f"vol ${value:x}")

    def _emit_long_rest_workaround(self, chunks: List[int]):
        # Square channels only. Confirmed against code/audio.s: a bare
        # `rest` (@cmd60) retriggers the channel with a fast decay-to-0
        # envelope to cut the previous note off quickly, whenever no
        # naturally-decaying envelope is already active -- and it does this
        # on *every* `rest` dispatch, not just the first. A rest long
        # enough to need chaining multiple `rest` commands (>255 frames)
        # therefore retriggers, and audibly blips, once per chunk. The
        # reference documentation's own recommended fix: hold the silence
        # with a repeatedly-retriggered *note* instead, at volume 0 --
        # retriggering a note that's already inaudible produces no blip,
        # unlike retriggering the decay-to-silence envelope. `gs3` is the
        # low pitch the games themselves use for this. (The wave and noise
        # channel `rest` handlers do nothing comparable -- a clean NR32
        # mute and a total no-op respectively -- so this is scoped to
        # square channels only; see mml2wla_documentation.md.)
        self._emit_vol_raw(0)
        for chunk in chunks:
            self.lines.append(f"note {'gs3':<4}${chunk:02x}")
        self._emit_vol_raw(self.cur_vol)

    def _emit_vibrato(self, ev: Ev):
        depth = max(0, min(15, ev.a))
        delay_ticks = ev.b
        bpm = next(self.resolved_iter)
        wait_code = 0
        if delay_ticks is not None:
            delay_frames = self.resolver.resolve_no_carry(delay_ticks, bpm)
            wait_code = round(delay_frames / 2)
            if wait_code > 15:
                self.song.warn(
                    f"vibrato delay ({delay_frames} frames) exceeds this engine's "
                    f"representable range (max 30 frames); clamped", ev.line)
                wait_code = 15
        byte = (wait_code << 4) | depth
        if byte != self._last_emitted_vibrato_byte:
            self._last_emitted_vibrato_byte = byte
            self.lines.append(f"vibrato ${byte:02x}")

    def _maybe_emit_duty(self):
        if self.wave_id is None:
            return
        key = ('id', self.wave_id, self.wave_vol)
        if key == self._last_duty_key:
            return
        self._last_duty_key = key
        symbol = self.waveform_agg.request(
            self.song.waves[self.wave_id], self.wave_vol, self.file_base, self.wave_id)
        self.lines.append(f"duty {symbol}")

    def _maybe_emit_duty_const(self, label: str):
        key = ('const', label)
        if key == self._last_duty_key:
            return
        self._last_duty_key = key
        self.lines.append(f"duty {label}")

    def _emit_note(self, ev: Ev):
        note_idx, octave = ev.a, ev.b
        exact_frames = next(self.resolved_iter)
        frames = self.resolver.resolve_exact(exact_frames)
        chunks = chunk_length(frames)
        if not chunks:
            return
        if self.ch == 3:
            if self.noise_envelope_agg is not None and self.noise_pace > 0 and self.noise_dir:
                byte = self.noise_envelope_agg.request(
                    octave, note_idx, self.noise_pace, self.noise_dir, self.file_base, ev.line)
            else:
                byte = self.noise_table.nearest(octave, note_idx)
            self.lines.append(f"note ${byte:02x} ${chunks[0]:02x}")
        else:
            name, warning = resolve_pitch(self.ch, octave, note_idx)
            if warning:
                self.song.warn(warning, ev.line)
            self.lines.append(f"note {name:<4}${chunks[0]:02x}")
        for c in chunks[1:]:
            self.lines.append(f"rest2 ${c:02x}")

    def _emit_noise_literal(self, ev: Ev):
        # An explicitly-chosen noise pitch byte (n$XX / @alias), bypassing
        # noise_table.nearest()/noise_envelope_agg entirely -- the whole
        # point is picking one of the fixed table entries exactly, so there
        # is nothing to nearest-match or generate a new entry for here.
        byte = ev.a
        exact_frames = next(self.resolved_iter)
        frames = self.resolver.resolve_exact(exact_frames)
        chunks = chunk_length(frames)
        if not chunks:
            return
        if self.noise_envelope_agg is not None and self.noise_pace > 0 and self.noise_dir:
            self.song.warn(
                "volume envelope (@ve) has no effect on an explicitly-chosen noise pitch "
                "(n$XX/@alias): it selects a fixed, existing noise table entry with its own "
                "baked-in envelope, rather than requesting a new one; ignored here", ev.line)
        self.lines.append(f"note ${byte:02x} ${chunks[0]:02x}")
        for c in chunks[1:]:
            self.lines.append(f"rest2 ${c:02x}")

def emit_song(song: Song, label_name: str, file_base: str, waveform_agg: WaveformAggregator,
              noise_table: NoiseTable = None,
              noise_envelope_agg: Optional[NoiseEnvelopeAggregator] = None,
              fix_rest_blip: bool = False) -> str:
    noise_table = noise_table or DEFAULT_NOISE_TABLE
    out = []
    out.append(f"mus{label_name}Start:")
    out.append("")

    used = [ch for ch in range(4) if song.channels[ch]]

    # Tempo is global and must be resolved chronologically across all four
    # channels together, not per-channel -- e.g. a dedicated "tempo
    # control" channel's `t` commands have to affect every other channel
    # starting at the real-time moment *that* channel's own playback
    # reaches them, regardless of which channel's line they were written
    # on or where that falls in the source text. See tempo.py.
    trees = [structure(song.channels[ch]) for ch in range(4)]
    resolved_bpms = resolve_tempo(trees)

    for ch in CHANNEL_EMIT_ORDER:
        engine_ch = CHANNEL_NUM[ch]
        if ch not in used:
            continue
        events = song.channels[ch]
        has_loop = any(e.kind == 'loop' for e in events)
        tree = trees[ch]

        out.append(f"mus{label_name}Channel{engine_ch}:")
        emitter = ChannelEmitter(song, label_name, file_base, ch, waveform_agg, noise_table,
                                  noise_envelope_agg, fix_rest_blip, resolved_bpms[ch])
        body_lines = []
        body_lines.extend(emitter.emit(tree))
        body_lines = _collapse_repeated_lines(body_lines)
        for line in body_lines:
            out.append("\t" + line)
        if has_loop:
            out.append(f"\tgoto {emitter.loop_label}")
        out.append("\tcmdff")
        out.append("")

    for ch in CHANNEL_EMIT_ORDER:
        engine_ch = CHANNEL_NUM[ch]
        if ch not in used:
            out.append(f".define mus{label_name}Channel{engine_ch} MUSIC_CHANNEL_FALLBACK EXPORT")

    text = '\n'.join(out).rstrip() + '\n'
    return text
