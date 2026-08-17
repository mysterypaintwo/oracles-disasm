"""Walks a channel's structured event tree and produces WLA-DX text using
the target engine's real macros (note/rest/sust/vol/env/duty/vibrato/goto/
cmdff), matching the reference disassembly's own mus/*.s conventions.
(`sust` -- a tie/sustain, extending the current note/rest without
retriggering -- was named `rest2` prior to a since-landed engine fix; see
musicMacros.s.)

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

import re
from typing import Dict, List, Optional, Tuple

from .parser import Ev, RepeatBlock, Song, structure
from .timing import FrameResolver, chunk_length
from .notes import resolve_pitch, NOTE_ENUM
from .noise import DEFAULT_NOISE_TABLE, NoiseTable
from .waveforms import WaveformAggregator
from .envelope import best_attack_pace
from .noise_envelope import NoiseEnvelopeAggregator
from .tempo import resolve_tempo

DEFAULT_VOLUME = 15  # matches mmlgb driver default (mus_volume1/2/4 = 0xF0)

# MML channel index (0=A,1=B,2=C,3=D) -> target engine music channel number.
CHANNEL_NUM = {0: 0, 1: 1, 2: 4, 3: 6}
# Sfx files (see cli.py's #SFX directive) use a separate set of 4 engine
# channel slots for the exact same 4 physical channels -- letting a sound
# effect briefly override whatever music is already using 0/1/4/6 without
# clobbering it (confirmed by reading standardSoundCmd's dispatch table and
# channelCmdf0/standardCmdChannel6/7 in code/audio.s, which all treat
# 2/3/5/7 as the wave/noise/pulse counterparts of 0/1/4/6 exactly).
CHANNEL_NUM_SFX = {0: 2, 1: 3, 2: 5, 3: 7}
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


_NOTE_LINE_RE = re.compile(r'^note (\S+) +\$([0-9a-f]{2})$')


def _apply_default_length(lines: List[str], loop_label: str) -> List[str]:
    """Rewrites a run of 3+ consecutive single-trigger notes (no chained
    `sust` -- see _emit_note) that all share the same length into
    `setDefaultLength` (2 bytes, once) + one `shortNote` per note (1 byte
    each, see musicMacros.s) instead of `note NAME $LEN` (2 bytes each).
    3 is the real breakeven point: 2 notes cost 4 bytes either way (2*2
    plain vs 2-byte setup + 2*1), so only 3+ actually saves anything.

    Purely a byte-count optimization -- every note's own audible length is
    completely unchanged, this only changes how many bytes it takes to
    request it. Conservative on purpose: only strictly consecutive note
    lines are considered, so a vol/env/etc. change between two otherwise-
    matching notes just means this pass doesn't merge across it, not a
    correctness risk -- see ChannelEmitter.emit(), which only calls this
    for the square channels (A/B), matching the engine's own current
    support.

    shortNote/setDefaultLength are themselves `.ifndef BUILD_VANILLA` in
    musicMacros.s (a genuinely new, non-vanilla-compatible opcode, unlike
    e.g. release/pitchSlide, which are real vanilla opcodes this tool was
    already using unconditionally) -- so every optimized run is wrapped in
    the same guard here, with the untouched original notes as the
    `.else` fallback, keeping a BUILD_VANILLA compile exactly byte-for-byte
    what it already was."""
    out = []
    i, n = 0, len(lines)
    current_default = None  # the engine's actual wChannelDefaultLength, once known
    while i < n:
        if lines[i] == f"{loop_label}:":
            # A fresh `goto`-driven pass through the loop body can't assume
            # anything this pass decided during the (chronologically
            # earlier, but textually-first) intro -- same reasoning as
            # _emit_ev's own loop-reset comment for vol/env/etc.
            current_default = None
            out.append(lines[i])
            i += 1
            continue
        m = _NOTE_LINE_RE.match(lines[i])
        if not m:
            out.append(lines[i])
            i += 1
            continue
        length_hex = m.group(2)
        j = i
        run = []
        while j < n:
            m2 = _NOTE_LINE_RE.match(lines[j])
            if not m2 or m2.group(2) != length_hex:
                break
            run.append(m2.group(1))
            j += 1
        if len(run) >= 3:
            out.append(".ifndef BUILD_VANILLA")
            if current_default != length_hex:
                out.append(f"setDefaultLength ${length_hex}")
                current_default = length_hex
            for note_name in run:
                out.append(f"shortNote {NOTE_ENUM.index(note_name)}")
            out.append(".else")
            out.extend(lines[i:j])
            out.append(".endif")
        else:
            out.extend(lines[i:j])
        i = j
    return out


class ChannelEmitter:
    def __init__(self, song: Song, label_name: str, file_base: str, ch: int,
                 waveform_agg: WaveformAggregator, noise_table: NoiseTable,
                 noise_envelope_agg: Optional[NoiseEnvelopeAggregator] = None,
                 resolved_iter=None, is_sfx: bool = False,
                 json_waveforms: Optional[Dict[int, str]] = None,
                 is_vanilla: bool = False):
        self.song = song
        self.label_name = label_name
        self.file_base = file_base
        self.ch = ch
        self.is_sfx = is_sfx
        self.is_vanilla = is_vanilla
        self.label_prefix = 'snd' if is_sfx else 'mus'
        self.engine_ch = (CHANNEL_NUM_SFX if is_sfx else CHANNEL_NUM)[ch]
        self.waveform_agg = waveform_agg
        self.noise_table = noise_table
        self.noise_envelope_agg = noise_envelope_agg
        self.json_waveforms: Dict[int, str] = json_waveforms or {}
        # Non-#VANILLA shortNote tracking only (see _emit_note) -- the
        # #VANILLA automatic pass (_apply_default_length) tracks its own
        # separately, as a text-level post-pass.
        self._authored_default_length: Optional[int] = None
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
        # `vibrato`, `env`, and pitchOffset/pitchSlide below): None until
        # the first real command of that kind is seen, so the *first* one
        # is always emitted regardless of its value -- we don't know what
        # the engine's actual register state is before that (unlike mmlgb,
        # nothing here guarantees it starts at any particular default). See
        # _emit_env_bytes for why re-issuing an identical `env` is also
        # safe to drop, despite looking at first glance like it should
        # restart something.
        self._last_emitted_vol: Optional[int] = None
        self._last_emitted_wd: Optional[int] = None
        self._last_emitted_vibrato_byte: Optional[int] = None
        self._last_emitted_env: Optional[Tuple[int, int]] = None
        self._last_emitted_pitch_offset: Optional[int] = None
        self._last_emitted_pitch_slide: Optional[int] = None
        self._loop_emitted = False
        self.loop_label = f"{self.label_prefix}{label_name}Channel{self.engine_ch}Loop"
        self.resolver = FrameResolver()

    def emit(self, tree: list) -> List[str]:
        self._emit_nodes(tree)
        if self.is_vanilla and self.ch in (0, 1):
            # setDefaultLength/shortNote (see musicMacros.s) only exist on
            # the square channels so far ("square channels only for now" --
            # its own comment) -- this applies equally to a music channel
            # (engine 0/1) or an sfx one (engine 2/3), both of which
            # dispatch through the same @channel0To3 short-note check.
            #
            # #VANILLA only: a byte-accurate ROM reproduction has no
            # authored `l` defaults to go on (every note already carries
            # its own exact length -- see #VANILLA's effect on `=X`), so
            # this looks for same-length runs after the fact instead. A
            # hand-authored file gets the equivalent optimization live, in
            # _emit_note, keyed on Ev.used_default_length -- an explicit
            # signal from the author (via `l`) rather than a guess.
            self.lines = _apply_default_length(self.lines, self.loop_label)
        return self.lines

    def _emit_nodes(self, nodes: list):
        i, n = 0, len(nodes)
        while i < n:
            node = nodes[i]
            if isinstance(node, RepeatBlock):
                self._emit_repeat(node)
            else:
                self._emit_ev(node)
            i += 1

    def _emit_repeat(self, block: RepeatBlock):
        # Renders one iteration, then checks FrameResolver's own carry
        # (snapshot/restore -- see timing.py's own docstring, which names
        # this exact use) before vs. after: if it comes back to the same
        # value, every remaining iteration is mathematically guaranteed to
        # round identically to the first (nothing else feeds into that
        # rounding), so it's safe to emit one real WLA-DX `.rept` instead of
        # unrolling -- zero timing/accuracy cost, since the text really is
        # byte-for-byte what every iteration would have produced anyway.
        # `=N` frame-exact lengths never touch carry at all, so a block
        # built entirely from them is always carry-neutral and always
        # collapses this way -- exactly the case a byte-accurate vanilla
        # reproduction needs (see #VANILLA in mml_documentation.md).
        #
        # When it isn't carry-neutral, later iterations can legitimately
        # round differently from the first (e.g. a tick length whose
        # fractional remainder doesn't return to zero over one full pass) --
        # unrolling in full is the only way to keep every iteration's timing
        # exact, so that's the fallback, same as before. Even then,
        # _collapse_repeated_lines below may still separately find and merge
        # a byte-identical run, just without this method's own guarantee.
        if block.count < 2:
            for _ in range(block.count):
                self._emit_nodes(block.children)
            return

        carry_before = self.resolver.snapshot()
        first_iteration = self._render_once(block.children)
        carry_after = self.resolver.snapshot()

        if abs(carry_after - carry_before) < 1e-9:
            self.lines.append(f".rept {block.count}")
            self.lines.extend(first_iteration)
            self.lines.append(".endr")
            # The remaining iterations' *text* is already proven identical
            # and doesn't need re-emitting, but resolved_iter/self.resolver
            # still need to land exactly where `count` real iterations would
            # have left them, for whatever comes after this block.
            for _ in range(block.count - 1):
                self._render_once(block.children)
        else:
            self.lines.extend(first_iteration)
            for _ in range(block.count - 1):
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
        elif k == 'raw_freq':
            self._emit_raw_freq(ev)
        elif k == 'noise_raw_env':
            # @er: always a literal raw `cmdf0 $XX` hardware envelope write,
            # re-issued verbatim on every occurrence -- see parser.py's
            # handling for why this can't be deduped like vol/duty/env
            # (each one is paired with the specific note event that follows
            # it, observed in every real vanilla use).
            byte = (ev.a << 4) | (ev.b << 3) | ev.c
            self.lines.append(f"cmdf0 ${byte:02x}")
        elif k == 'freq_mode':
            # @fm: same underlying `cmdf0 $XX` command as @er, but on a
            # square channel this byte means something entirely different
            # (see channelCmdf0) -- a one-way switch into raw-frequency mode
            # for the rest of this channel, not an envelope write.
            self.lines.append(f"cmdf0 ${ev.a:02x}")
        elif k == 'rest':
            # A real, instant, clean cutoff regardless of chaining -- no
            # workaround needed here (an earlier version of this engine had
            # a chained-rest audible-blip bug; that's fixed now, see
            # cli.py's #FIX_REST_BLIP handling).
            exact_frames = next(self.resolved_iter)
            frames = self.resolver.resolve_exact(exact_frames)
            for chunk in chunk_length(frames):
                self.lines.append(f"rest ${chunk:02x}")
        elif k == 'wait':
            exact_frames = next(self.resolved_iter)
            frames = self.resolver.resolve_exact(exact_frames)
            for chunk in chunk_length(frames):
                self.lines.append(f"sust ${chunk:02x}")
        elif k == 'release':
            # @rl: a tool-specific extension with no mmlgb equivalent (see
            # lexer.py) -- maps 1:1 to the engine's own `release` opcode
            # ($f5), which decays from the channel's current volume at a
            # fixed pace. Emitted plainly, chunk by chunk, the same as
            # `wait`/sust above -- there's no blip concern here (that was
            # only ever a `rest`-chaining bug, long since fixed) and nothing
            # else to collapse or group.
            exact_frames = next(self.resolved_iter)
            frames = self.resolver.resolve_exact(exact_frames)
            for chunk in chunk_length(frames):
                self.lines.append(f"release ${chunk:02x}")
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
        elif k == 'vol_raw':
            # @vr: always a literal `vol $N` engine command regardless of
            # channel -- see parser.py's handling for why the wave channel
            # needs this bypass around `v`'s own pre-scaled-waveform model.
            self.cur_vol = ev.a
            self._emit_vol_raw(ev.a)
        elif k == 'env':
            self._emit_env(ev)
        elif k == 'env_raw':
            self._emit_env_raw(ev)
        elif k == 'pitch_offset':
            if ev.a != self._last_emitted_pitch_offset:
                self._last_emitted_pitch_offset = ev.a
                self.lines.append(f"pitchOffset ${ev.a & 0xff:02x}")
        elif k == 'pitch_slide':
            if ev.a != self._last_emitted_pitch_slide:
                self._last_emitted_pitch_slide = ev.a
                self.lines.append(f"pitchSlide ${ev.a & 0xff:02x}")
        elif k == 'wd':
            if ev.a != self._last_emitted_wd:
                self._last_emitted_wd = ev.a
                self.lines.append(f"duty ${ev.a:x}")
        elif k == 'wave_select':
            if ev.a in self.json_waveforms:
                # References a waveform that already exists elsewhere in the
                # target project (e.g. audio/common/waveforms.json), by its
                # numeric id -- as opposed to a locally `@waveN = {...}`
                # -defined one, which names data defined in this .mml file
                # and gets generated (and deduplicated) via
                # WaveformAggregator. So no aggregator request here: the
                # existing entry's name is emitted as-is, and no new
                # waveform data is added to the output waveform list.
                self.wave_id = None  # numeric wave_id no longer applies
                self.wave_is_const = True
                self._maybe_emit_duty_const(self.json_waveforms[ev.a])
            elif ev.a not in self.song.waves:
                self.song.warn(f"@wave{ev.a} was never defined; skipping duty change", ev.line)
                return
            else:
                self.wave_id = ev.a
                self.wave_is_const = False
                self._maybe_emit_duty()
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
                self._last_emitted_pitch_offset = None
                self._last_emitted_pitch_slide = None
                self._authored_default_length = None
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
            if self.cur_vol == 0:
                # Exact match: this engine now has a real hardware envelope
                # fade-in (env's attack param with bit 3 set), which starts
                # at volume 0 and climbs to 15 entirely in hardware at the
                # given pace -- identical to what mmlgb's own increasing
                # @ve does whenever the current volume is already 0 (mmlgb
                # always sweeps from the current `v`, so this is only an
                # exact match at v=0; see the `else` below for other
                # starting volumes, where no such hardware feature exists).
                start = 0x8 | ev.a
                end = 0
            else:
                # Not a direct match (see envelope.py) -- this engine's
                # only other attack option always starts at volume 1 and
                # only climbs up to the target, never to 15, so it's
                # approximated by matching real-world sweep duration
                # instead.
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
        self._emit_env_bytes(start, end)

    def _emit_env_raw(self, ev: Ev):
        # @ea: same scope restriction as @ve (see _emit_env above) -- the
        # noise channel's envelope pace is baked into its fixed noise-table
        # entries, not settable by command.
        if self.ch == 3:
            if self.noise_envelope_agg is not None:
                self.noise_pace = ev.b
                self.noise_dir = 'inc' if ev.a & 0x8 else ('dec' if ev.b else None)
                return
            self.song.warn(
                "volume envelope (@ea) cannot be controlled on the noise channel in this "
                "engine: its envelope pace is fixed per noise type; dropped. `vol` still "
                "works normally on this channel, or pass --noise-envelope to generate exact "
                "new table entries instead.", ev.line)
            return
        self._emit_env_bytes(ev.a, ev.b)

    def _emit_env_bytes(self, start: int, end: int):
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

    def _emit_vibrato(self, ev: Ev):
        depth = max(0, min(15, ev.a))
        delay_ticks = ev.b
        bpm = next(self.resolved_iter)
        wait_code = 0
        if delay_ticks is not None:
            if ev.frame_exact:
                # mmlgb's `=X` syntax: delay_ticks is already an exact frame
                # count, not ticks -- see Ev.frame_exact.
                delay_frames = delay_ticks
            else:
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
            if (not self.is_vanilla and self.ch in (0, 1)
                    and ev.used_default_length and len(chunks) == 1):
                # The author already opted into this length being "the
                # default" by omitting it (relying on `l`) -- see
                # Ev.used_default_length's own docstring for why that's the
                # right signal here instead of guessing from same-length
                # runs (which is what the #VANILLA path below does
                # instead). len(chunks) == 1 excludes a note long enough to
                # need chained `sust` continuations, same restriction as
                # the #VANILLA path.
                self.lines.append(".ifndef BUILD_VANILLA")
                if self._authored_default_length != chunks[0]:
                    self.lines.append(f"setDefaultLength ${chunks[0]:02x}")
                    self._authored_default_length = chunks[0]
                self.lines.append(f"shortNote {NOTE_ENUM.index(name)}")
                self.lines.append(".else")
                self.lines.append(f"note {name:<4}${chunks[0]:02x}")
                self.lines.append(".endif")
            else:
                self.lines.append(f"note {name:<4}${chunks[0]:02x}")
        for c in chunks[1:]:
            self.lines.append(f"sust ${c:02x}")

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
            self.lines.append(f"sust ${c:02x}")

    def _emit_raw_freq(self, ev: Ev):
        # @rf: a literal raw hardware frequency (see @fm/parser.py), emitted
        # as the plain `.db lo hi wait` triple this engine's raw-frequency
        # mode actually reads -- matching every real vanilla use (there's no
        # named engine macro for this triple; it's always written as raw
        # .db bytes in the reference disassembly too). Overflow past one
        # byte's length re-emits the *same* frequency triple for each
        # remaining chunk rather than chaining `sust` like a regular note:
        # once this channel is in raw-frequency mode, a literal $61 byte is
        # no longer dispatched as sust at all -- it would just be consumed
        # as another raw frequency's low byte instead (confirmed by reading
        # @channel0To3 in code/audio.s, which only checks for $60/$61 in the
        # *non*-raw-frequency branch) -- so re-triggering the identical
        # frequency is the only correct way to hold it past 255 frames.
        value = ev.a
        lo, hi = value & 0xff, (value >> 8) & 0xff
        exact_frames = next(self.resolved_iter)
        frames = self.resolver.resolve_exact(exact_frames)
        for chunk in chunk_length(frames):
            self.lines.append(f".db ${lo:02x} ${hi:02x} ${chunk:02x}")

def emit_song(song: Song, label_name: str, file_base: str, waveform_agg: WaveformAggregator,
              noise_table: NoiseTable = None,
              noise_envelope_agg: Optional[NoiseEnvelopeAggregator] = None,
              is_sfx: bool = False,
              json_waveforms: Optional[Dict[int, str]] = None,
              is_vanilla: bool = False) -> str:
    noise_table = noise_table or DEFAULT_NOISE_TABLE
    channel_num = CHANNEL_NUM_SFX if is_sfx else CHANNEL_NUM
    label_prefix = 'snd' if is_sfx else 'mus'
    out = []
    out.append(f"{label_prefix}{label_name}Start:")
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
        engine_ch = channel_num[ch]
        if ch not in used:
            continue
        events = song.channels[ch]
        has_loop = any(e.kind == 'loop' for e in events)
        tree = trees[ch]

        out.append(f"{label_prefix}{label_name}Channel{engine_ch}:")
        emitter = ChannelEmitter(song, label_name, file_base, ch, waveform_agg, noise_table,
                                  noise_envelope_agg, resolved_bpms[ch], is_sfx=is_sfx,
                                  json_waveforms=json_waveforms, is_vanilla=is_vanilla)
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
        engine_ch = channel_num[ch]
        if ch not in used:
            out.append(f".define {label_prefix}{label_name}Channel{engine_ch} "
                       f"MUSIC_CHANNEL_FALLBACK EXPORT")

    text = '\n'.join(out).rstrip() + '\n'
    return text
