"""Recursive-descent parser mirroring mmlgb-src/parser/src/Parser.cs.

Produces a flat per-channel event stream (`Ev`). Note/rest/wait/vibrato-delay
lengths are stored as (ticks, bpm) rather than pre-resolved frame counts --
frame resolution happens later in emitter.py, once repeat-block structure is
known, so that timing stays exactly in sync across every channel (see
timing.py for why this has to happen after structuring).

Two deliberate departures from mmlgb's own compiler:

1. Macro bodies (`@@N`) are fully re-parsed/inlined at each call site against
   the calling channel's *live* octave/default-length state, and continue to
   mutate that state afterwards. This matches real mmlgb *playback* behavior
   (register state leaks across a macro call/return -- several of the
   example songs even end their macros with `<<`/`>>` specifically to undo
   an octave shift before returning) more faithfully than mmlgb's own
   compiler, which parses macro bodies in isolation at compile time.

2. A confirmed mmlgb compiler bug is fixed rather than reproduced: a bare
   dot with no preceding digit (`c.`, `c^.`, `w.`) crashes the real parser,
   including the documentation's own suggested workaround (`c+w.` -- also
   verified to crash against the real compiler). We instead apply the
   dot(s) to the channel's current default length, matching the obviously
   intended behavior.

Comments (`;...`) are preserved as `Ev('comment', ...)` nodes at their
original position in the stream, so the emitter can reproduce them in the
generated output. A comment on a line with channel selector(s) is attached
to each of those channels (matching the source exactly for one channel and
duplicating for multiple, as the source itself does for real commands). A
comment on its own line (no channel selector) is queued and attached to
whichever channel(s) the next channel line targets.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .lexer import Token, MmlError, parse_int
from .noise import KNOWN_NOISE_FREQUENCIES

NOTE_NAMES = ['c', 'cs', 'd', 'ds', 'e', 'f', 'fs', 'g', 'gs', 'a', 'as', 'b']

BAR_STEPS = 192  # ticks per whole note
DEFAULT_OCTAVE = 4
DEFAULT_LENGTH_TICKS = 48    # matches mmlgb driver mus_length default
DEFAULT_TEMPO_BPM = 120      # used only if a channel emits notes before any
                              # 't' command is ever seen anywhere in the file


def _parse_noise_literal_value(data: str) -> int:
    """Parses a NOISE_LITERAL token's text ("n34" or "n$22") into its raw
    byte value. Note the '$' hex prefix here, not mmlgb's own '0x' -- this
    matches the *target engine's* hex notation, since the value is a literal
    engine command byte, not an mmlgb-side quantity."""
    body = data[1:]  # strip leading 'n'
    if body.startswith('$'):
        return int(body[1:], 16)
    return int(body)


@dataclass
class Ev:
    """A single parsed MML event. `kind` tags which fields are meaningful
    (see module docstrings in parser.py/emitter.py for the field layout
    used by each kind).

    `frame_exact`: only meaningful for the tick-consuming kinds (note/
    noise_literal/rest/wait). False (the normal case) means the length
    field (see tempo.py's _TICKS_FIELD) holds a tick count, resolved to
    frames via the tempo active when it plays. True means it came from
    `=X` syntax in a `#VANILLA`-flagged file (an explicit, tempo-independent
    frame count) and the *same* field instead holds that frame count
    directly, verbatim, completely bypassing tempo/tick conversion -- see
    tempo.py and Parser.is_vanilla.

    `used_default_length`: 'note' kind only. True when this note omitted
    its own length entirely, i.e. it's playing at whatever the channel's
    current `l` default is -- see emitter.py's non-#VANILLA shortNote
    handling, which treats this as the author's own explicit opt-in signal
    for the shortNote optimization (as opposed to a #VANILLA file, where
    the compiler looks for same-length runs on its own instead)."""
    kind: str
    line: int = 0
    a: object = None
    b: object = None
    c: object = None
    d: object = None
    frame_exact: bool = False
    used_default_length: bool = False


@dataclass
class RepeatBlock:
    """Structured node produced by the bracket-matching pass (structure())."""
    count: int
    children: list = field(default_factory=list)
    line: int = 0


# Node = Ev | RepeatBlock in the structured per-channel tree.


class TokenStream:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0

    @property
    def cur(self) -> Token:
        return self.tokens[self.pos]

    def eat(self) -> Token:
        t = self.tokens[self.pos]
        if self.pos < len(self.tokens) - 1:
            self.pos += 1
        return t

    def expect(self, ttype: str, msg: str) -> Token:
        if self.cur.type != ttype:
            raise MmlError(f"Found token {self.cur.data!r}. Expected {msg}.", self.cur.line)
        return self.eat()


class Song:
    """Holds everything parsed out of one .mml file."""

    def __init__(self):
        # channel index 0..3 -> A,B,C,D -> flat list of Ev
        self.channels: List[List[Ev]] = [[], [], [], []]
        self.waves: Dict[int, List[int]] = {}  # id -> 32 samples 0-15
        self.warnings: List[str] = []

    def warn(self, msg, line=None):
        self.warnings.append(f"line {line}: {msg}" if line else msg)


@dataclass
class ChannelState:
    octave: int = DEFAULT_OCTAVE
    default_length: int = DEFAULT_LENGTH_TICKS  # ticks, unless default_length_frame_exact
    default_length_frame_exact: bool = False    # see Ev.frame_exact
    raw_freq_mode: bool = False  # see @fm's handling in _parse_macro_command


class Parser:
    def __init__(self, tokens: List[Token], json_waveforms: Optional[Dict[int, str]] = None,
                 known_noise_frequencies=None, is_vanilla: bool = False):
        self.tokens = tokens
        self.song = Song()
        self.macro_tokens: Dict[int, List[Token]] = {}
        self.noise_aliases: Dict[str, int] = {}
        self.channel_state = [ChannelState() for _ in range(4)]
        self.current_bpm = DEFAULT_TEMPO_BPM
        self.tempo_ever_set = False
        self._warned_no_tempo = False
        self.pending_comments: List[Token] = []
        # Pre-existing named waveforms (e.g. from the target project's own
        # waveforms.json), keyed by the same numeric id used in-song --
        # replaces the old bracket syntax (`@wave[LABEL]`): every @wave
        # reference now uses one plain numeric id space, whether it names an
        # already-existing entry from here or a freshly `@waveN = {...}`
        # -defined one (see _parse_wave_data/@wave usage below).
        self.json_waveforms: Dict[int, str] = json_waveforms or {}
        # Overridable so a target project's own noise.json (see noise.py's
        # load_noise_json) is what actually gets checked against, instead of
        # this module's own compiled-in reference copy.
        self.known_noise_frequencies = (
            known_noise_frequencies if known_noise_frequencies is not None
            else KNOWN_NOISE_FREQUENCIES)
        # See #VANILLA in cli.py/mml_documentation.md: controls what `=X`
        # means for this whole file (raw frames vs. musical ticks).
        self.is_vanilla = is_vanilla

    # -- top level -------------------------------------------------------

    def parse(self) -> Song:
        ts = TokenStream(self.tokens)
        while ts.cur.type != 'EOF':
            if ts.cur.type == 'CHANNEL':
                self._parse_channel_line(ts)
            elif ts.cur.type == 'MACRO' and ts.cur.data in ('@wave', '@@'):
                self._parse_definition(ts)
            elif ts.cur.type == 'NOISE_ALIAS':
                self._parse_noise_alias_definition(ts)
            elif ts.cur.type == 'COMMENT':
                self.pending_comments.append(ts.eat())
                if ts.cur.type == 'NEWLINE':
                    ts.eat()
            elif ts.cur.type == 'NEWLINE':
                ts.eat()
            else:
                raise MmlError(f"Unexpected token {ts.cur.data!r}.", ts.cur.line)

        # Any comments left over at EOF (trailing comments with no further
        # channel line to attach to) get attached to whichever channels
        # already have real content, so we don't spuriously mark an unused
        # channel as "used" just because of a floating comment.
        for ch in range(4):
            if self.song.channels[ch]:
                for tok in self.pending_comments:
                    self.song.channels[ch].append(Ev('comment', tok.line, tok.data))
        self.pending_comments = []

        return self.song

    def _parse_definition(self, ts: TokenStream):
        if ts.cur.data == '@wave':
            self._parse_wave_data(ts)
        else:
            self._parse_macro_definition(ts)

    def _parse_wave_data(self, ts: TokenStream):
        ts.eat()  # @wave
        if ts.cur.type != 'NUMBER':
            raise MmlError("Expected wave data id.", ts.cur.line)
        line = ts.cur.line
        wave_id = parse_int(ts.eat().data)
        if wave_id in self.json_waveforms:
            raise MmlError(
                f"@wave{wave_id} = {{...}} conflicts with the existing waveform "
                f"{self.json_waveforms[wave_id]!r} (id {wave_id}) -- pick an id that isn't "
                f"already in waveforms.json.", line)
        ts.expect('ASSIGN', '=')
        ts.expect('LCURLY', '{')
        samples = []
        for _ in range(32):
            while ts.cur.type in ('NEWLINE', 'COMMENT'):
                ts.eat()
            if ts.cur.type != 'NUMBER':
                raise MmlError("Invalid wave sample. Expected number.", ts.cur.line)
            v = parse_int(ts.eat().data)
            if v < 0 or v > 15:
                raise MmlError(f"Invalid wave sample {v}. Expected 0-15.", ts.cur.line)
            samples.append(v)
            while ts.cur.type in ('NEWLINE', 'COMMENT'):
                ts.eat()
        ts.expect('RCURLY', '}')
        if ts.cur.type == 'NEWLINE':
            ts.eat()
        self.song.waves[wave_id] = samples

    def _parse_macro_definition(self, ts: TokenStream):
        ts.eat()  # @@
        if ts.cur.type != 'NUMBER':
            raise MmlError("Expected macro id.", ts.cur.line)
        macro_id = parse_int(ts.eat().data)
        ts.expect('ASSIGN', '=')
        ts.expect('LCURLY', '{')
        body: List[Token] = []
        while ts.cur.type != 'RCURLY':
            while ts.cur.type == 'NEWLINE':
                ts.eat()
            body.append(ts.eat())
            while ts.cur.type == 'NEWLINE':
                ts.eat()
        body.append(Token('NEWLINE', '\n', ts.cur.line))
        ts.expect('RCURLY', '}')
        if ts.cur.type == 'NEWLINE':
            ts.eat()
        self.macro_tokens[macro_id] = body

    def _parse_noise_alias_definition(self, ts: TokenStream):
        # A tool-specific extension letting a song define its own short,
        # friendly names for noise-channel pitch bytes (e.g. "@k = n$22"
        # for a kick drum), entirely within the .mml source -- deliberately
        # not built into this tool, so a song's own choice of names/mapping
        # travels with the file wherever it's shared, and can be freely
        # redefined per song without touching any code.
        t = ts.eat()  # e.g. "@k"
        name = t.data[1:]
        ts.expect('ASSIGN', '=')
        if ts.cur.type != 'NOISE_LITERAL':
            raise MmlError(f"Expected a noise pitch literal (e.g. n$22) after '@{name} ='.",
                            ts.cur.line)
        value = _parse_noise_literal_value(ts.eat().data)
        if ts.cur.type == 'NEWLINE':
            ts.eat()
        self.noise_aliases[name] = value

    def _parse_channel_line(self, ts: TokenStream):
        active = []
        while ts.cur.type == 'CHANNEL':
            active.append('ABCD'.index(ts.eat().data))

        # Flush any comments queued up since the last channel line into
        # every channel this line targets, before this line's own content.
        if self.pending_comments:
            for ch in active:
                for tok in self.pending_comments:
                    self.song.channels[ch].append(Ev('comment', tok.line, tok.data))
            self.pending_comments = []

        # Collect the token span for this line's commands (up to NEWLINE).
        start = ts.pos
        depth_end = start
        while ts.tokens[depth_end].type not in ('NEWLINE', 'EOF'):
            depth_end += 1
        span = ts.tokens[start:depth_end] + [Token('NEWLINE', '\n', ts.tokens[depth_end].line)]
        # Advance the outer stream past this line.
        ts.pos = depth_end
        if ts.cur.type == 'NEWLINE':
            ts.eat()

        for ch in active:
            sub = TokenStream(span)
            self._parse_commands(sub, ch)

    # -- shared command parsing (channel lines AND macro bodies) --------

    def _parse_commands(self, ts: TokenStream, ch: int):
        state = self.channel_state[ch]
        out = self.song.channels[ch]
        while ts.cur.type != 'NEWLINE':
            t = ts.cur
            if t.type == 'NOTE':
                out.append(self._parse_note(ts, ch, state))
            elif t.type == 'COMMAND':
                self._parse_command(ts, ch, state, out)
            elif t.type == 'TIE':
                line = t.line
                ts.eat()
                ticks, frame_exact = self._parse_length(ts, state, False)
                if ticks == 0:
                    ticks = state.default_length
                    frame_exact = state.default_length_frame_exact
                out.append(Ev('wait', line, ticks, self.current_bpm, frame_exact=frame_exact))
            elif t.type == 'MACRO':
                self._parse_macro_command(ts, ch, state, out)
            elif t.type == 'NOISE_LITERAL':
                ts.eat()
                value = _parse_noise_literal_value(t.data)
                # ppmck-style required comma before the length (matching its
                # own analogous "direct note number" syntax) -- see the
                # lexer's NOISE_LITERAL comment for why a separator is
                # needed here at all, unlike a normal note.
                ts.expect('COMMA', "',' before the length (e.g. n34,4)")
                out.append(self._parse_noise_note_tail(ts, ch, state, value, t.line))
            elif t.type == 'RAWFREQ':
                ts.eat()
                out.append(self._parse_raw_freq_tail(ts, ch, state, t.data, t.line))
            elif t.type == 'NOISE_ALIAS':
                ts.eat()
                name = t.data[1:]
                # "=" here is ambiguous on its own: a genuine top-level
                # definition ("@k = n$22", rejected below) and a valid
                # mid-channel use with an exact-frame length ("@k=4", a
                # completely ordinary use of the =X syntax every other
                # note/rest/wait already supports) both start with
                # NOISE_ALIAS then ASSIGN. They're only distinguishable by
                # what follows the "=": a NOISE_LITERAL (n$XX) means
                # definition, anything else (a plain number) means length.
                next_i = min(ts.pos + 1, len(ts.tokens) - 1)
                if ts.cur.type == 'ASSIGN' and ts.tokens[next_i].type == 'NOISE_LITERAL':
                    raise MmlError(
                        f"'@{name} = ...' noise alias definitions must be written at the top "
                        f"level, not inside a channel's data.", t.line)
                if name not in self.noise_aliases:
                    raise MmlError(f"Noise alias @{name} not defined.", t.line)
                value = self.noise_aliases[name]
                out.append(self._parse_noise_note_tail(ts, ch, state, value, t.line))
            elif t.type == 'LBRACKET':
                ts.eat()
                out.append(Ev('rep_start', t.line))
            elif t.type == 'RBRACKET':
                ts.eat()
                if ts.cur.type != 'NUMBER':
                    raise MmlError("Expected repetition count.", ts.cur.line)
                reps = parse_int(ts.eat().data)
                if reps < 2:
                    raise MmlError("Invalid repetition count. Must be >= 2.", t.line)
                out.append(Ev('rep_end', t.line, reps))
            elif t.type == 'COMMENT':
                ts.eat()
                out.append(Ev('comment', t.line, t.data))
            elif t.type == 'EOF':
                return
            else:
                raise MmlError(f"Unexpected token {t.data!r}.", t.line)

    def _note_tempo_check(self, line: int):
        if not self.tempo_ever_set and not self._warned_no_tempo:
            self._warned_no_tempo = True
            self.song.warn(
                f"no 't' (tempo) command found before this point; assuming "
                f"{DEFAULT_TEMPO_BPM} BPM", line)

    # -- length parsing (with the bare-dot bugfix) -----------------------

    def _parse_length(self, ts: TokenStream, state: ChannelState, required: bool) -> Tuple[int, bool]:
        """Returns (length, frame_exact) -- see Ev.frame_exact's docstring.
        `length` is 0 (frame_exact False) only when no length was written
        at all and `required` is False; callers fall back to the channel's
        current default length (also a (value, frame_exact) pair -- see
        ChannelState) in that case."""
        length = 0
        frame_exact = False
        line = ts.cur.line
        if ts.cur.type == 'NUMBER':
            n = parse_int(ts.eat().data)
            if n < 1 or n > BAR_STEPS:
                raise MmlError(f"Invalid note length {n}. Expected 1-{BAR_STEPS}.", line)
            if (BAR_STEPS // n) * n != BAR_STEPS:
                raise MmlError(f"Invalid note length {n}. Not enough precision.", line)
            length = BAR_STEPS // n
            dot = length // 2
            while ts.cur.type == 'DOT':
                if dot <= 0:
                    raise MmlError("Too many dots in length. Not enough precision.", ts.cur.line)
                ts.eat()
                length += dot
                dot //= 2
        elif ts.cur.type == 'ASSIGN':
            # `=X`'s meaning depends on #VANILLA (see cli.py/
            # mml_documentation.md): in a #VANILLA file it's a raw,
            # tempo-independent hardware frame count (e.g. `c+=4` is exactly
            # 4 frames -- what a byte-accurate ROM reproduction needs, since
            # vanilla data has no tempo of its own, only literal frame
            # counts). Otherwise it's a raw musical *tick* count instead
            # (still 192 ticks per whole note, same as every other length
            # here) -- an exact alternative to the named fractions (1, 4, 8,
            # ...) above for a length that doesn't reduce cleanly to one of
            # them, but still fully tempo-relative like any other note.
            ts.eat()
            n = parse_int(ts.eat().data)
            if self.is_vanilla:
                if n < 1 or n > 255:
                    raise MmlError(f"Invalid note frame length {n}. Expected 1-255.", line)
                length = n
                frame_exact = True
            else:
                if n < 1:
                    raise MmlError(f"Invalid note tick length {n}. Expected a positive number.",
                                    line)
                length = n
                frame_exact = False
        elif ts.cur.type == 'DOT':
            # Fix for the confirmed mmlgb bug: apply the dot(s) to the
            # channel's current default length instead of crashing.
            length = state.default_length
            frame_exact = state.default_length_frame_exact
            dot = length // 2
            while ts.cur.type == 'DOT':
                if dot <= 0:
                    raise MmlError("Too many dots in length. Not enough precision.", ts.cur.line)
                ts.eat()
                length += dot
                dot //= 2
        elif required:
            raise MmlError("Expected note length.", line)

        if ts.cur.type == 'TIE':
            ts.eat()
            # Second fix in the same spirit as the bare-dot fix above (also
            # confirmed against the real compiler: a tie with genuinely
            # nothing after it -- not even a dot -- crashes there too,
            # e.g. a note at the very end of a line like `g6^` with the
            # continuation's length meant to be implicit). Falls back to
            # the channel's current default length, matching how a bare
            # standalone tie (`^` with nothing after it, handled in
            # _parse_commands) already behaves.
            tie_length, tie_frame_exact = self._parse_length(ts, state, False)
            if tie_length == 0:
                tie_length = state.default_length
                tie_frame_exact = state.default_length_frame_exact
            if frame_exact == tie_frame_exact:
                length += tie_length
            else:
                # Mixing an exact-frame length with a tick-based one in the
                # same tie: there's no unit both halves already share, so
                # this converts the tick-based half to frames at whatever
                # tempo is active right now (not a full chronological
                # resolution the way tempo.py normally does it -- a
                # reasonable approximation for what's already an unusual
                # construct, since ticks and exact frames aren't naturally
                # comparable at parse time).
                from .timing import ticks_to_frames_exact
                if frame_exact:
                    length += round(ticks_to_frames_exact(tie_length, self.current_bpm))
                else:
                    length = round(ticks_to_frames_exact(length, self.current_bpm)) + tie_length
                frame_exact = True
        return length, frame_exact

    # -- notes -------------------------------------------------------------

    def _parse_note(self, ts: TokenStream, ch: int, state: ChannelState) -> Ev:
        line = ts.cur.line
        if state.raw_freq_mode:
            raise MmlError(
                "A regular note can't be used here: `@fm` earlier on this channel switched it "
                "into raw-frequency mode, so every event from there on is read as a literal "
                "hardware frequency, not a note-table lookup -- use @rf$<hex> instead (see "
                "@fm's own error/docs).", line)
        letter = ts.eat().data
        idx = NOTE_NAMES.index(letter)
        if ts.cur.type == 'SHARP':
            idx += 1
            ts.eat()
        elif ts.cur.type == 'DASH':
            idx -= 1
            ts.eat()
        if idx == -1:
            idx = 11
        elif idx == 12:
            idx = 0

        ticks, frame_exact = self._parse_length(ts, state, False)
        used_default_length = (ticks == 0)
        if used_default_length:
            ticks = state.default_length
            frame_exact = state.default_length_frame_exact
        self._note_tempo_check(line)
        return Ev('note', line, idx, state.octave, ticks, self.current_bpm,
                   frame_exact=frame_exact, used_default_length=used_default_length)

    def _parse_noise_note_tail(self, ts: TokenStream, ch: int, state: ChannelState,
                                value: int, line: int) -> Ev:
        """Shared by NOISE_LITERAL ('n$22') and NOISE_ALIAS ('@k') usage: an
        explicit, exact noise-channel pitch byte, chosen directly rather
        than approximated via nearest-frequency matching from a chromatic
        note+octave. Length parses exactly like a regular note's."""
        if ch != 3:
            raise MmlError(
                "Noise pitch literals/aliases (n$XX, @alias) can only be used on channel D "
                "(noise) -- square/wave channels use regular note letters instead.", line)
        if value not in self.known_noise_frequencies:
            self.song.warn(
                f"noise pitch ${value:02x} is not one of this engine's documented noise "
                f"frequency table entries; using it as-is", line)
        ticks, frame_exact = self._parse_length(ts, state, False)
        if ticks == 0:
            ticks = state.default_length
            frame_exact = state.default_length_frame_exact
        self._note_tempo_check(line)
        return Ev('noise_literal', line, value, ticks, self.current_bpm, frame_exact=frame_exact)

    def _parse_raw_freq_tail(self, ts: TokenStream, ch: int, state: ChannelState,
                              token_data: str, line: int) -> Ev:
        """@rf$<hex>: a literal raw hardware frequency value, only valid
        after `@fm` has switched this channel into raw-frequency mode (see
        that macro's handling below) -- see musicMacros.s/audio.s's
        channelCmdf0 for why this mode exists and what it bypasses. Length
        parses exactly like a regular note's."""
        if ch not in (0, 1):
            raise MmlError(
                "@rf (raw frequency) is only valid on the square channels (A/B) -- the "
                "engine's raw-frequency mode (see @fm) only exists on those channels.", line)
        if not state.raw_freq_mode:
            raise MmlError(
                "@rf (raw frequency) used before this channel was switched into raw-frequency "
                "mode -- put an `@fm<byte>` earlier on this channel first.", line)
        value = int(token_data[len('@rf$'):], 16)
        if value > 0xffff:
            raise MmlError(f"Invalid @rf value ${value:x}. Expected $0-$ffff.", line)
        ticks, frame_exact = self._parse_length(ts, state, False)
        if ticks == 0:
            ticks = state.default_length
            frame_exact = state.default_length_frame_exact
        self._note_tempo_check(line)
        return Ev('raw_freq', line, value, ticks, self.current_bpm, frame_exact=frame_exact)

    # -- simple commands -----------------------------------------------------

    def _parse_command(self, ts: TokenStream, ch: int, state: ChannelState, out: List[Ev]):
        t = ts.eat()
        line = t.line
        cmd = t.data

        if cmd == 'r':
            ticks, frame_exact = self._parse_length(ts, state, False)
            if ticks == 0:
                ticks = state.default_length
                frame_exact = state.default_length_frame_exact
            self._note_tempo_check(line)
            out.append(Ev('rest', line, ticks, self.current_bpm, frame_exact=frame_exact))

        elif cmd == 'w':
            ticks, frame_exact = self._parse_length(ts, state, False)
            if ticks == 0:
                ticks = state.default_length
                frame_exact = state.default_length_frame_exact
            self._note_tempo_check(line)
            out.append(Ev('wait', line, ticks, self.current_bpm, frame_exact=frame_exact))

        elif cmd == 'o':
            if ts.cur.type != 'NUMBER':
                raise MmlError("Expected number after octave command.", ts.cur.line)
            state.octave = parse_int(ts.eat().data)

        elif cmd == '<':
            state.octave -= 1

        elif cmd == '>':
            state.octave += 1

        elif cmd == 'l':
            length_line = ts.cur.line
            length, frame_exact = self._parse_length(ts, state, True)
            if length > 255:
                raise MmlError("Length overflow. Lengths more than 255 frames not allowed for l command.", length_line)
            state.default_length = length
            state.default_length_frame_exact = frame_exact

        elif cmd == 'v':
            if ts.cur.type != 'NUMBER':
                raise MmlError("Invalid volume. Expected number.", ts.cur.line)
            vol = parse_int(ts.eat().data)
            if ch == 2 and (vol < 0 or vol > 3):
                raise MmlError("Invalid volume for wave channel. Expected 0-3.", line)
            if vol < 0 or vol > 15:
                raise MmlError("Invalid volume value. Expected 0-15.", line)
            out.append(Ev('vol', line, vol))

        elif cmd == 't':
            if ts.cur.type != 'NUMBER':
                raise MmlError("Invalid tempo command. Expected number.", ts.cur.line)
            bpm = parse_int(ts.eat().data)
            self.current_bpm = bpm
            self.tempo_ever_set = True
            # `t` is global -- real mmlgb hardware has one shared tempo
            # clock for all four channels (see mmlgb-src/driver/music.c),
            # so this must take effect for every channel at the real-time
            # moment *this* channel's own playback reaches it, not just for
            # whatever gets parsed later in the source text (which is what
            # merely updating self.current_bpm here would do -- wrong
            # whenever a tempo change is written on a channel whose block
            # comes before another channel's in the file, e.g. a dedicated
            # "tempo control" channel positioned after the melody). Recorded
            # positionally in this channel's own stream; tempo.resolve_tempo
            # does the actual cross-channel, chronological resolution later.
            out.append(Ev('tempo', line, bpm))

        elif cmd == 'y':
            if ts.cur.type == 'DASH':
                ts.eat()
            if ts.cur.type != 'NUMBER':
                raise MmlError("Invalid panning command. Expected number.", ts.cur.line)
            parse_int(ts.eat().data)
            self.song.warn("panning (y) has no equivalent in this engine's channel-data "
                            "format; dropped", line)

        elif cmd == 'L':
            out.append(Ev('loop', line))

        else:
            raise MmlError(f"Unknown command {cmd!r}.", line)

    # -- macro-prefixed commands (@wave recall, @ve, @wd, @p, @po, @v, @ns, @@) --

    def _parse_macro_command(self, ts: TokenStream, ch: int, state: ChannelState, out: List[Ev]):
        t = ts.eat()
        line = t.line
        cmd = t.data

        if cmd == '@wave':
            if ts.cur.type != 'NUMBER':
                raise MmlError("Expected wave data id.", ts.cur.line)
            wave_id = parse_int(ts.eat().data)
            if wave_id not in self.song.waves and wave_id not in self.json_waveforms:
                raise MmlError(f"Wave {wave_id} not defined.", line)
            out.append(Ev('wave_select', line, wave_id))

        elif cmd == '@ve':
            increasing = True
            if ts.cur.type == 'DASH':
                ts.eat()
                increasing = False
            if ts.cur.type != 'NUMBER':
                raise MmlError("Invalid volume envelope. Expected number.", ts.cur.line)
            env = parse_int(ts.eat().data)
            if env > 7:
                raise MmlError("Invalid volume envelope. Expected values from -7 to 7.", line)
            out.append(Ev('env', line, env if increasing else -env))

        elif cmd == '@ea':
            # Tool-specific extension, not part of upstream mmlgb at all:
            # raw, direct passthrough of this engine's own two-parameter
            # `env $attack $decay` command (see musicMacros.s), bypassing
            # @ve's semantic translation entirely. @ve alone can only ever
            # request an attack *or* a decay in one command (real mmlgb
            # hardware envelopes only ever sweep one direction per trigger,
            # which is exactly why @ve is single-valued -- see emitter.py's
            # _emit_env), but this engine's own attack/decay pair is
            # actually two independent software-tracked values: attack
            # governs the note's initial software-simulated (or, with bit 3
            # set via $8-$f, true hardware) ramp-up, and decay separately
            # configures the real hardware envelope pace that continues
            # decaying *after* that ramp finishes -- a combination no single
            # @ve value can express. Vanilla data overwhelmingly uses one or
            # the other (mapped fine by plain @ve), but a handful of real
            # sites set both simultaneously, needing this exact escape hatch
            # for a byte-accurate round trip.
            if ts.cur.type != 'NUMBER':
                raise MmlError("Invalid @ea. Expected attack,decay.", ts.cur.line)
            attack = parse_int(ts.eat().data)
            if attack > 15:
                raise MmlError("Invalid @ea attack. Expected values from 0 to 15.", line)
            ts.expect('COMMA', 'comma')
            if ts.cur.type != 'NUMBER':
                raise MmlError("Invalid @ea. Expected decay after comma.", ts.cur.line)
            decay = parse_int(ts.eat().data)
            if decay > 7:
                raise MmlError("Invalid @ea decay. Expected values from 0 to 7.", line)
            out.append(Ev('env_raw', line, attack, decay))

        elif cmd == '@wd':
            if ts.cur.type != 'NUMBER':
                raise MmlError("Invalid wave duty. Expected number.", ts.cur.line)
            duty = parse_int(ts.eat().data)
            if duty < 0 or duty > 3:
                raise MmlError("Invalid wave duty. Expected values 0-3.", line)
            out.append(Ev('wd', line, duty))

        elif cmd == '@rl':
            # Tool-specific extension, not part of upstream mmlgb at all: a
            # "soft release" -- decays the currently playing note from
            # whatever volume it's already at, at a fixed hardware pace,
            # instead of cutting it off (`r`) or holding it (`w`). Maps
            # directly to this engine's own `release` command (see
            # channelCmdf5 in code/audio.s), which has no mmlgb equivalent
            # to translate from -- it exists because it's what a real,
            # pre-fix engine bug in `rest` actually did, and turned out to
            # be the dominant note-release technique in existing vanilla
            # content, so it was kept as a real, intentionally-available
            # command rather than discarded. Square channels only (A/B),
            # matching channelCmdf5's own scope.
            if ch not in (0, 1):
                raise MmlError(
                    "@rl (a decaying release -- see mml2wla_documentation.md) is only valid "
                    "on the square channels (A/B); the engine command it maps to has no "
                    "effect elsewhere.", line)
            length, frame_exact = self._parse_length(ts, state, False)
            if length == 0:
                length = state.default_length
                frame_exact = state.default_length_frame_exact
            self._note_tempo_check(line)
            out.append(Ev('release', line, length, self.current_bpm, frame_exact=frame_exact))

        elif cmd == '@p':
            if ts.cur.type != 'NUMBER':
                raise MmlError("Expected speed after @p macro.", ts.cur.line)
            parse_int(ts.eat().data)
            self.song.warn("portamento (@p) has no equivalent in this engine's channel-data "
                            "format; dropped", line)

        elif cmd == '@po':
            # mmlgb's flat pitch offset: a signed value added once to a
            # note's frequency at trigger time and held constant for that
            # note's whole duration -- an exact match for this engine's own
            # cmdfd/pitchOffset (see musicMacros.s), which was confirmed to
            # do exactly this by reading its handler in code/audio.s
            # (setSoundFrequency). Only square/wave channels support it on
            # this engine (channelCmdfd is a no-op on noise); mmlgb's own
            # driver additionally excludes noise for the same command, so
            # this isn't a new restriction relative to real mmlgb.
            if ch == 3:
                raise MmlError(
                    "@po (pitch offset) has no effect on the noise channel (D) in this "
                    "engine or in real mmlgb.", line)
            neg = False
            if ts.cur.type == 'DASH':
                ts.eat()
                neg = True
            if ts.cur.type != 'NUMBER':
                raise MmlError("Expected number after @po macro.", ts.cur.line)
            val = parse_int(ts.eat().data)
            if val > 127:
                raise MmlError("Invalid @po value. Expected -127 to 127.", line)
            out.append(Ev('pitch_offset', line, -val if neg else val))

        elif cmd == '@s':
            # mmlgb's pitch slide: a signed value re-added to the channel's
            # frequency every single frame for as long as it stays nonzero,
            # producing a continuous, unbounded slide (distinct from `@p`
            # portamento, which glides toward and settles on a specific
            # target note -- this engine has nothing resembling that, so
            # `@p` stays dropped above). Matches this engine's own
            # cmdf8/pitchSlide exactly (confirmed via func_39_41c2/
            # func_39_41f3 in code/audio.s: called every frame, accumulates
            # into the live frequency in place). Same channel scope as @po.
            if ch == 3:
                raise MmlError(
                    "@s (pitch slide) has no effect on the noise channel (D) in this "
                    "engine.", line)
            neg = False
            if ts.cur.type == 'DASH':
                ts.eat()
                neg = True
            if ts.cur.type != 'NUMBER':
                raise MmlError("Expected speed after @s macro.", ts.cur.line)
            val = parse_int(ts.eat().data)
            if val > 127:
                raise MmlError("Invalid @s value. Expected -127 to 127.", line)
            out.append(Ev('pitch_slide', line, -val if neg else val))

        elif cmd == '@vr':
            # Tool-specific extension, not part of upstream mmlgb at all: a
            # raw, direct passthrough of this engine's own `vol $N` command
            # (see musicMacros.s), for any channel including the wave
            # channel -- bypassing `v`'s own per-channel semantics entirely.
            # On the wave channel, plain `v` (0-3) doesn't emit a runtime
            # engine command at all: it bakes the level into a pre-scaled
            # waveform table entry instead (see emitter.py's
            # _maybe_emit_duty), which is the right authoring model for new
            # content but isn't what existing vanilla wave-channel data
            # actually does -- vanilla writes a literal runtime `vol $0-$f`
            # command there instead (confirmed against every committed
            # audio/*/mus/*.s: values well outside 0-3 appear on the wave
            # channel), which this exists to reproduce exactly.
            if ts.cur.type != 'NUMBER':
                raise MmlError("Invalid @vr. Expected a number 0-15.", ts.cur.line)
            vol = parse_int(ts.eat().data)
            if vol < 0 or vol > 15:
                raise MmlError("Invalid @vr value. Expected 0-15.", line)
            out.append(Ev('vol_raw', line, vol))

        elif cmd == '@er':
            # Sfx-only extension, not part of upstream mmlgb: a raw, direct
            # passthrough of this engine's own noise-channel `cmdf0 $XX`
            # command (see channelCmdf0's label_39_038 in code/audio.s),
            # which writes straight to the hardware envelope register
            # (NR42) once, immediately -- distinct from @ea/@ve's env
            # command, which only *stages* a value the software envelope
            # simulation applies on the *next* note-trigger. This one has no
            # software simulation at all: it's an instant hardware write,
            # observed in real sfx data issued right before (and re-issued
            # for) every single note it's meant to affect. vol (0-15),
            # dir (0=decrease, 1=increase -- the increasing direction has no
            # equivalent via @ea/@ve at all, since the software-simulated
            # envelope only ever decays), pace (0-7) -- packed into one byte
            # as (vol<<4)|(dir<<3)|pace, matching the real NR42 bit layout.
            if ch != 3:
                raise MmlError(
                    "@er (raw noise envelope) is only valid on the noise channel (D) -- it "
                    "maps directly to a noise-channel-only engine command.", line)
            if ts.cur.type != 'NUMBER':
                raise MmlError("Invalid @er. Expected vol,dir,pace.", ts.cur.line)
            vol = parse_int(ts.eat().data)
            if vol < 0 or vol > 15:
                raise MmlError("Invalid @er vol. Expected 0-15.", line)
            ts.expect('COMMA', 'comma')
            if ts.cur.type != 'NUMBER':
                raise MmlError("Invalid @er. Expected dir after first comma.", ts.cur.line)
            direction = parse_int(ts.eat().data)
            if direction not in (0, 1):
                raise MmlError("Invalid @er dir. Expected 0 or 1.", line)
            ts.expect('COMMA', 'comma')
            if ts.cur.type != 'NUMBER':
                raise MmlError("Invalid @er. Expected pace after second comma.", ts.cur.line)
            pace = parse_int(ts.eat().data)
            if pace < 0 or pace > 7:
                raise MmlError("Invalid @er pace. Expected 0-7.", line)
            out.append(Ev('noise_raw_env', line, vol, direction, pace))

        elif cmd == '@fm':
            # Sfx-only extension, not part of upstream mmlgb: a raw, direct
            # passthrough of this engine's own square-channel `cmdf0 $XX`
            # command (see channelCmdf0 in code/audio.s), which switches
            # this channel permanently (for the rest of this sound effect --
            # there's no way back) into raw-frequency mode: every event from
            # here on is a literal hardware frequency (@rf$<hex>), not a
            # note-table lookup. Confirmed against every vanilla sfx file
            # that this is only ever issued once, near the very start of a
            # channel, never mid-stream. See @rf's own docs for the paired
            # event syntax.
            if ch not in (0, 1):
                raise MmlError(
                    "@fm (raw frequency-mode switch) is only valid on the square channels "
                    "(A/B) -- the engine's raw-frequency mode only exists on those channels.",
                    line)
            if ts.cur.type != 'NUMBER':
                raise MmlError("Invalid @fm. Expected a byte value 0-255.", ts.cur.line)
            byte = parse_int(ts.eat().data)
            if byte < 0 or byte > 255:
                raise MmlError("Invalid @fm value. Expected 0-255.", line)
            state.raw_freq_mode = True
            out.append(Ev('freq_mode', line, byte))

        elif cmd == '@v':
            if ts.cur.type != 'NUMBER':
                raise MmlError("Expected vibrato speed after @v macro.", ts.cur.line)
            speed = parse_int(ts.eat().data)
            ts.expect('COMMA', 'comma')
            if ts.cur.type != 'NUMBER':
                raise MmlError("Expected vibrato depth after @v macro.", ts.cur.line)
            depth = parse_int(ts.eat().data)
            delay_ticks = None
            delay_frame_exact = False
            if ts.cur.type == 'COMMA':
                ts.eat()
                delay_ticks, delay_frame_exact = self._parse_length(ts, state, True)
            if speed != 0:
                self.song.warn(
                    "vibrato speed has no equivalent in this engine (its vibrato oscillation "
                    "rate is fixed); only depth and delay are used", line)
            out.append(Ev('vibrato', line, depth, delay_ticks, self.current_bpm,
                           frame_exact=delay_frame_exact))

        elif cmd == '@ns':
            if ts.cur.type != 'NUMBER':
                raise MmlError("Expected 0 or 1 after @ns macro.", ts.cur.line)
            parse_int(ts.eat().data)
            self.song.warn("noise counter step (@ns) has no equivalent in this engine's "
                            "channel-data format; dropped", line)

        elif cmd == '@@':
            if ts.cur.type != 'NUMBER':
                raise MmlError("Expected macro id.", ts.cur.line)
            macro_id = parse_int(ts.eat().data)
            if macro_id not in self.macro_tokens:
                raise MmlError(f"Macro @@{macro_id} not found.", line)
            sub = TokenStream(self.macro_tokens[macro_id])
            self._parse_commands(sub, ch)

        else:
            raise MmlError(f"Unknown macro command {cmd!r}.", line)


# ---------------------------------------------------------------------------
# Structurer: flat Ev stream -> tree of Ev/RepeatBlock nodes, by matching
# rep_start/rep_end markers.
# ---------------------------------------------------------------------------

def structure(events: List[Ev]) -> list:
    root: list = []
    stack = [root]
    open_lines = []
    for ev in events:
        if ev.kind == 'rep_start':
            block = RepeatBlock(count=0, children=[], line=ev.line)
            stack[-1].append(block)
            stack.append(block.children)
            open_lines.append(ev.line)
        elif ev.kind == 'rep_end':
            if len(stack) == 1:
                raise MmlError("Unmatched ']' (no open '[').", ev.line)
            stack.pop()
            open_lines.pop()
            parent = stack[-1]
            for node in reversed(parent):
                if isinstance(node, RepeatBlock) and node.count == 0:
                    node.count = ev.a
                    break
        else:
            stack[-1].append(ev)
    if len(stack) != 1:
        raise MmlError("Unmatched '[' (missing ']').", open_lines[-1])
    return root
