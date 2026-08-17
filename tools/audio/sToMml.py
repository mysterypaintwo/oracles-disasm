#!/usr/bin/python3
"""One-time migration prototype: transpiles an already-committed, already
ROM-decoded audio/*/mus/*.s channel-data file into an equivalent .mml file,
for validating the mml2wla round trip before porting this same mapping into
dumpMusic.py's real ROM->MML decode path.

This deliberately does NOT touch ROM bytes at all -- it works off the .s
text that a prior, legitimate dumpMusic.py run (against the real clean ROM)
already produced, and which already carries the correct rest/release/sust
classification (see code/audio.s's channelCmdf5 and dumpMusic.py's own
parseChannelData comments). That's a valid one-time bootstrap of the .mml
corpus; it is not a substitute for dumpMusic.py itself eventually emitting
.mml directly from ROM bytes.

Usage: sToMml.py <song.s> <song.mml>
       sToMml.py --pirates <pirates.s> <ages.mml> <seasons.mml>
"""
import json
import os
import re
import sys

import tempoInfer
from songConfig import ECHO_CHANNELS

_REPO = os.path.join(os.path.dirname(__file__), '..', '..')

NOTE_RE = re.compile(r'^\tnote ([a-g]s?)(\d) +\$([0-9a-fA-F]+)$')
NOISE_NOTE_RE = re.compile(r'^\tnote \$([0-9a-fA-F]+) \$([0-9a-fA-F]+)$')
REST_RE = re.compile(r'^\trest \$([0-9a-fA-F]+)$')
SUST_RE = re.compile(r'^\tsust \$([0-9a-fA-F]+)$')
RELEASE_RE = re.compile(r'^\trelease \$([0-9a-fA-F]+)$')
VOL_RE = re.compile(r'^\tvol \$([0-9a-fA-F]+)$')
ENV_RE = re.compile(r'^\tenv \$([0-9a-fA-F]+) \$([0-9a-fA-F]+)$')
DUTY_RE = re.compile(r'^\tduty \$([0-9a-fA-F]+)$')
VIBRATO_RE = re.compile(r'^\tvibrato \$([0-9a-fA-F]+)$')
PITCH_OFFSET_RE = re.compile(r'^\tpitchOffset \$([0-9a-fA-F]+)$')
PITCH_SLIDE_RE = re.compile(r'^\tpitchSlide \$([0-9a-fA-F]+)$')
CMDF0_RE = re.compile(r'^\tcmdf0 \$([0-9a-fA-F]+)$')
RAWFREQ_DB_RE = re.compile(r'^\t\.db \$([0-9a-fA-F]+) \$([0-9a-fA-F]+) \$([0-9a-fA-F]+)$')
GOTO_RE = re.compile(r'^\tgoto (\S+)$')
LABEL_RE = re.compile(r'^(music[0-9a-fA-F]+):$')
CHANNEL_START_RE = re.compile(r'^(?:mus|snd)\w+Channel(\d+):$')
DROP_EXACT = {'\tcmdf2', '\tcmdff'}

# engine channel index -> mml channel letter (see emitter.py: ch 0=A/1=B/2=C/3=D
# internally, matching engine WRAM channel numbers 0,1,4,6 in that order). Sfx
# files (see emitter.py's CHANNEL_NUM_SFX) reuse the same 4 letters via a
# separate set of engine channel numbers (2,3,5,7) for the exact same 4
# physical channels, so both map onto the same letter here.
ENGINE_CH_TO_LETTER = {0: 'A', 1: 'B', 4: 'C', 6: 'D', 2: 'A', 3: 'B', 5: 'C', 7: 'D'}

CHANNEL_LABELS = {
    'A': '; pulse channel 1',
    'B': '; pulse channel 2',
    'C': '; wavetable channel',
    'D': '; noise channel',
}

# '+' preferred over '#' for sharps -- both are accepted by the lexer (see
# lexer.py's SHARP token, r'[#+]'), but '+' is the more idiomatic mmlgb
# convention (see mmlgb_documentation.md's own examples).
NOTE_LETTER_MML = {'c': 'c', 'cs': 'c+', 'd': 'd', 'ds': 'd+', 'e': 'e', 'f': 'f',
                   'fs': 'f+', 'g': 'g', 'gs': 'g+', 'a': 'a', 'as': 'a+', 'b': 'b'}

# Loaded from audio/common/noise.json (the single source of truth this used
# to be a hand-maintained duplicate of -- see tools/audio/noiseJsonToS.py,
# which generates the actual noise.s from the same file). Only entries with
# a "name" field become an alias here; an unnamed entry can still be
# selected via a raw n$XX literal, just without a friendly alias.
def _load_noise_names():
    with open(os.path.join(_REPO, 'audio/common/noise.json')) as f:
        entries = json.load(f)
    return {e['note']: (e['name'], e.get('description', '')) for e in entries if 'name' in e}


NOISE_NAMES = _load_noise_names()

# file_base -> (#TITLE override, header comment). This song's real internal
# ROM-derived primary name (see dumpMusicMml.py's _base_name -- also the
# SONG_MANIFEST/lookup key, so this dict's own keys must match it exactly)
# -> (nicer output filename, #TITLE to restore the label
# soundChannelPointers.s actually expects, optional header comment).
# soundPointers.s's raw label is "musPrecredits" (lowercase c), so
# _base_name derives "precredits" -- an awkward filename. This renames the
# output file to the nicer camelCase "preCredits" while #TITLE keeps the
# compiled label exactly "musPrecredits", matching soundChannelPointers.s's
# own reference with no build-affecting change at all.
TITLE_OVERRIDES = {
    'precredits': ('preCredits', 'Precredits', (
        "soundPointers.s's raw label is \"musPrecredits\" (lowercase c); this renames "
        "the output file to the nicer \"preCredits\" while #TITLE keeps the compiled "
        "label exactly \"musPrecredits\", matching soundChannelPointers.s's own "
        "reference.")),
}

# Commands that only take effect the next time a note/rest/wait/noise-note
# triggers (see emitter.py/code/audio.s for each): re-issuing one of these
# with nothing that actually triggers in between means the earlier issue is
# never observed and can be dropped outright. pitchOffset and pitchSlide
# are kept as distinct kinds (not merged) since they're independent engine
# state (wChannelPitchShift vs wChannelPitchSlide) -- superseding one must
# never drop a pending write to the other.
STATE_KINDS = {'vol', 'env', 'duty', 'vibrato', 'pitchOffset', 'pitchSlide'}
TRANSPARENT_KINDS = {'__label__', '__linebreak__', '__goto__'}


def _expand_rept(raw_lines):
    """Some committed .s files already hand-apply WLA's `.rept N ... .endr`
    (a source-level space optimization -- see Makefile/README) to a few
    vanilla songs -- including, in at least one case, a `.rept` nested
    directly inside another. Expanding it back into literal copies here
    (rather than teaching the rest of this script to understand it) is
    lossless and keeps everything downstream simple; mml2wla's own
    _collapse_repeated_lines re-compacts identical runs on the way back out
    anyway, so nothing about the final ROM-space savings is lost by
    expanding here first."""
    def expand(lines, i):
        """Expands lines[i:] up to (and consuming) the .endr matching the
        block this call is inside, or to the end of the list at the top
        level. Returns (expanded_lines, index_just_past_the_matching_endr)."""
        out = []
        n = len(lines)
        while i < n:
            s = lines[i].strip()
            if s == '.endr':
                return out, i + 1
            m = re.match(r'^\.rept (\d+)', s)
            if not m:
                out.append(lines[i])
                i += 1
                continue
            count = int(m.group(1))
            body, i = expand(lines, i + 1)
            out.extend(body * count)
        return out, i

    expanded, _ = expand(raw_lines, 0)
    return expanded


def split_pirates(lines):
    """pirates.s is the one confirmed case in the whole corpus of a genuine
    per-game content fork (different noise-channel data for Ages vs
    Seasons, not just a wrapped no-op) -- see the .ifdef ROM_SEASONS /
    .else / .endif around its Channel6 data. Splits the raw line list into
    (ages_lines, seasons_lines), each with the fork resolved to just that
    game's own branch, so the rest of this script can treat each as an
    ordinary single-variant file."""
    ifdef_i = next(i for i, l in enumerate(lines) if l.strip().startswith('.ifdef ROM_SEASONS'))
    else_i = next(i for i, l in enumerate(lines) if l.strip().startswith('.else'))
    endif_i = next(i for i, l in enumerate(lines) if l.strip().startswith('.endif'))
    before, seasons_branch, ages_branch, after = (
        lines[:ifdef_i], lines[ifdef_i + 1:else_i], lines[else_i + 1:endif_i], lines[endif_i + 1:])
    return before + ages_branch + after, before + seasons_branch + after


def convert(lines):
    """`lines` is a raw list of source lines (already .rept-expanded).
    Returns (channels, is_sfx) -- is_sfx is True iff any channel header used
    one of the sfx-only engine channel numbers (2/3/5/7), so callers know
    whether the file needs a `#SFX` directive when rendering it back out."""
    channels = {}  # letter -> list of (kind, val) tokens
    cur_letter = None
    cur_engine_ch = None
    octave = {}  # letter -> last emitted octave (mmlgb default octave is 4)
    channel_ended = {}  # letter -> True once cmdff/goto seen (see below)
    raw_freq_mode = {}  # letter -> True once @fm (cmdf0 on a square channel) seen
    is_sfx = False

    for raw_line in lines:
        line = raw_line.rstrip('\n')
        # Strip a trailing inline comment (e.g. "sust $2e  ;$18 + $16") --
        # but not a leading one (a whole-line comment, handled below by its
        # own dedicated check, since some, like "; Measure 1", are meant to
        # stay readable as section/line-break markers rather than silently
        # vanish mid-parse). ';' never appears inside a real command's own
        # syntax, so a naive split is unambiguous here.
        if ';' in line and not line.strip().startswith(';'):
            line = line.split(';', 1)[0]
        line = line.rstrip()
        if not line.strip():
            continue
        if line[:1] in ('\t', ' '):
            # Normalize to exactly one leading tab: a command nested inside
            # a (possibly doubly-nested) hand-written `.rept` block carries
            # extra indentation in the source that has no bearing on the
            # command itself -- see _expand_rept, which preserves each
            # body line's original indentation verbatim when it copies it
            # out N times.
            line = '\t' + line.lstrip('\t ')

        m = CHANNEL_START_RE.match(line.strip())
        if m:
            cur_engine_ch = int(m.group(1))
            if cur_engine_ch not in ENGINE_CH_TO_LETTER:
                raise ValueError(f"unexpected channel index {cur_engine_ch}")
            if cur_engine_ch in (2, 3, 5, 7):
                is_sfx = True
            cur_letter = ENGINE_CH_TO_LETTER[cur_engine_ch]
            channels[cur_letter] = []
            octave[cur_letter] = 4
            raw_freq_mode[cur_letter] = False
            continue

        if (line.startswith('mus') or line.startswith('snd')) and line.endswith('Start:'):
            continue
        if '.define' in line and 'MUSIC_CHANNEL_FALLBACK' in line:
            continue
        stripped_full = line.strip()
        if stripped_full.startswith(';'):
            # Any plain comment, including hand-added "; Measure N" markers
            # some committed .s files have -- line breaks are now inferred
            # algorithmically instead (see tempoInfer.py/insert_linebreaks),
            # so these don't need to be preserved or acted on.
            continue
        if re.match(r'^\.else\b', stripped_full):
            raise ValueError(
                "'.else' found -- this file has real per-game content differences; "
                "use split_pirates (or handle manually), not this function directly.")
        if re.match(r'^\.(ifdef|ifndef|endif)\b', stripped_full):
            # Every other .ifdef/.endif found in committed music data (with
            # no .else, ruled out above) wraps nothing but a `cmdf2`
            # (confirmed no-op -- see DROP_EXACT) or post-terminator filler
            # bytes -- an artifact of the two ROMs' sound data not laying
            # out byte-identically, not a real musical difference. Skipping
            # the directive itself and letting the rest of this loop handle
            # whatever's inside (including the channel_ended skip below) is
            # safe: anything both unexpected AND still musically live still
            # hits the "unhandled line" error rather than being silently
            # swallowed.
            continue

        if cur_letter is None:
            continue  # header/blank noise before the first channel block

        if channel_ended.get(cur_letter):
            # Past this channel's own cmdff/goto: real committed data has a
            # few cases of raw `.db`/`.dsb` filler bytes here (BUILD_VANILLA
            # padding to match the original ROM's exact layout) -- dead,
            # unreachable, and irrelevant to audio output either way, so
            # everything here is simply ignored until the next channel.
            continue

        stripped = line.strip('\t')

        m = LABEL_RE.match(stripped)
        if m:
            channels[cur_letter].append(('__label__', m.group(1)))
            continue

        if line in DROP_EXACT:
            if line == '\tcmdff':
                channel_ended[cur_letter] = True
            continue

        m = GOTO_RE.match(line)
        if m:
            channels[cur_letter].append(('__goto__', m.group(1)))
            channel_ended[cur_letter] = True
            continue

        m = NOTE_RE.match(line)
        if m:
            letter, oct_str, len_hex = m.groups()
            oct_n = int(oct_str)
            if cur_letter == 'C':
                # notes.py's resolve_pitch applies a -12 (one octave)
                # correction on the wave channel only (NOTE_BYTE_ADJUST[2] =
                # -12): it's a genuine hardware quirk (the wave channel's
                # usable range sits one octave lower than the same raw byte
                # would mean on square/noise), deliberately compensated for
                # so *new* MML input's octave numbers name the pitch that's
                # actually heard. But the octave digit here came straight
                # from this engine's own raw byte-constant label (e.g. "e3"
                # names one specific, uncorrected byte value in
                # musicMacros.s's .enum table) -- feeding that digit
                # straight through would get the correction applied *again*
                # on top of an already-raw value. Adding 1 here cancels it
                # out so mml2wla's own correction reconstructs the exact
                # original byte.
                oct_n += 1
            length = int(len_hex, 16)
            mml_letter = NOTE_LETTER_MML[letter]
            toks = []
            if oct_n != octave[cur_letter]:
                toks.append(f"o{oct_n}")
                octave[cur_letter] = oct_n
            toks.append(f"{mml_letter}={length}")
            # No space between an octave change and the note it applies to
            # -- "o3c4" is the normal, idiomatic way to write that in MML,
            # not "o3 c4".
            channels[cur_letter].append(('note', ''.join(toks)))
            continue

        m = NOISE_NOTE_RE.match(line)
        if m:
            byte_hex, len_hex = m.groups()
            byte = int(byte_hex, 16)
            length = int(len_hex, 16)
            if byte in NOISE_NAMES:
                alias, _comment = NOISE_NAMES[byte]
                channels[cur_letter].append(('note', f"@{alias}={length}"))
            else:
                channels[cur_letter].append(('note', f"n${byte_hex},={length}"))
            continue

        m = REST_RE.match(line)
        if m:
            length = int(m.group(1), 16)
            channels[cur_letter].append(('note', f"r={length}"))
            continue

        m = SUST_RE.match(line)
        if m:
            length = int(m.group(1), 16)
            channels[cur_letter].append(('note', f"w={length}"))
            continue

        m = RELEASE_RE.match(line)
        if m:
            length = int(m.group(1), 16)
            channels[cur_letter].append(('note', f"@rl={length}"))
            continue

        m = VOL_RE.match(line)
        if m:
            val = int(m.group(1), 16)
            if cur_letter == 'C':
                channels[cur_letter].append(('vol', f"@vr{val}"))
            else:
                channels[cur_letter].append(('vol', f"v{val}"))
            continue

        m = ENV_RE.match(line)
        if m:
            attack, decay_raw = int(m.group(1), 16), int(m.group(2), 16)
            # cmde0Toef masks the decay byte with & $07 at runtime (only the
            # attack param's mask was widened to $0f for the hardware-fade
            # feature -- see musicMacros.s's env macro comment); the decay
            # macro parameter itself is emitted unchecked, so a handful of
            # real vanilla bytes have upper bits set that are silently
            # ignored on real hardware. Masking here matches actual runtime
            # behavior, not just the literal committed byte.
            decay = decay_raw & 0x7
            if attack == 0 and decay == 0:
                channels[cur_letter].append(('env', "@ve0"))
            elif attack == 0:
                # Exact, unconditional match (see emitter.py _emit_env's
                # decreasing-envelope branch: no cur_vol dependency at all).
                channels[cur_letter].append(('env', f"@ve-{decay}"))
            else:
                # Any nonzero attack: @ve+n's *exact* match depends on
                # emitter.py's runtime cur_vol being 0 at that exact point
                # (picking the true-hardware-fade branch vs an approximated
                # one) -- not something this script can safely predict
                # without re-simulating the whole engine's volume state.
                # @ea is a raw, unconditional passthrough of the same two
                # bytes regardless of cur_vol, so it's used for every
                # nonzero-attack case, matching real vanilla data exactly
                # every time.
                channels[cur_letter].append(('env', f"@ea{attack},{decay}"))
            continue

        m = DUTY_RE.match(line)
        if m:
            val = int(m.group(1), 16)
            if cur_letter == 'C':
                # Numeric @waveN, matching the waveforms.json table index
                # directly (see mml2wla's unified @wave syntax) -- no name
                # lookup needed at all.
                channels[cur_letter].append(('duty', f"@wave{val}"))
            else:
                channels[cur_letter].append(('duty', f"@wd{val}"))
            continue

        m = VIBRATO_RE.match(line)
        if m:
            byte = int(m.group(1), 16)
            wait_code = byte >> 4
            depth = byte & 0xf
            if wait_code == 0:
                # No delay clause at all -- omitting it (rather than =0,
                # which _parse_length rejects: frame lengths must be >=1)
                # is what naturally makes the emitter compute wait_code=0
                # itself (see emitter.py's _emit_vibrato: delay_ticks is
                # None -> wait_code stays 0).
                channels[cur_letter].append(('vibrato', f"@v0,{depth}"))
            else:
                channels[cur_letter].append(('vibrato', f"@v0,{depth},={wait_code * 2}"))
            continue

        m = PITCH_OFFSET_RE.match(line)
        if m:
            byte = int(m.group(1), 16)
            signed = byte if byte < 128 else byte - 256
            channels[cur_letter].append(('pitchOffset', f"@po{signed}"))
            continue

        m = PITCH_SLIDE_RE.match(line)
        if m:
            byte = int(m.group(1), 16)
            signed = byte if byte < 128 else byte - 256
            channels[cur_letter].append(('pitchSlide', f"@s{signed}"))
            continue

        m = CMDF0_RE.match(line)
        if m:
            # Sfx-only command, overloaded per channel type -- see
            # channelCmdf0 in code/audio.s. On the noise channel (D), a raw
            # one-shot hardware envelope write (@er); on a square channel
            # (A/B), a one-way switch into raw-frequency mode (@fm), after
            # which subsequent `.db lo hi wait` triples (see RAWFREQ_DB_RE
            # below) are literal hardware frequencies (@rf$<hex>), not
            # note-table lookups.
            byte = int(m.group(1), 16)
            if cur_letter == 'D':
                vol, direction, pace = (byte >> 4) & 0xf, (byte >> 3) & 1, byte & 0x7
                channels[cur_letter].append(('noise_raw_env', f"@er{vol},{direction},{pace}"))
            else:
                raw_freq_mode[cur_letter] = True
                channels[cur_letter].append(('freq_mode', f"@fm{byte}"))
            continue

        m = RAWFREQ_DB_RE.match(line)
        if m and raw_freq_mode.get(cur_letter):
            lo, hi, length = int(m.group(1), 16), int(m.group(2), 16), int(m.group(3), 16)
            value = (hi << 8) | lo
            channels[cur_letter].append(('note', f"@rf${value:04x}={length}"))
            continue

        raise ValueError(f"unhandled line: {line!r}")

    for letter in channels:
        channels[letter] = _collapse_redundant_state(channels[letter])
    return channels, is_sfx


def _collapse_redundant_state(tokens):
    """vol/env/duty/vibrato/pitchOffset/pitchSlide only take effect at the
    next note/rest/wait/noise-note trigger (see STATE_KINDS' docstring
    above) -- so if one of these is immediately followed by another of the
    *same* kind with nothing that actually triggers in between, the
    earlier one was never observed and is dead weight. This is stronger
    than mml2wla's own redundant-value dedup (which only drops an
    *identical* reissue): here the values don't need to match, since the
    earlier one never had a chance to apply to anything regardless.
    Confirmed against real vanilla data: e.g. boss.s's noise channel opens
    with a `vol $5` immediately overwritten by `vol $8` before any note."""
    pending = {}  # kind -> index of the last not-yet-observed instance
    remove = set()
    for i, (kind, _val) in enumerate(tokens):
        if kind in STATE_KINDS:
            if kind in pending:
                remove.add(pending[kind])
            pending[kind] = i
        elif kind not in TRANSPARENT_KINDS:
            pending.clear()  # a note/rest/wait/noise-note observes everything pending
    return [t for i, t in enumerate(tokens) if i not in remove]


# Prefixes of a 'note'-kind token's string that should NOT pack against a
# neighboring note with no space (see _is_packable_note): an octave change
# ("o3c+=4") and a noise literal/alias note ("n$27,=5", "@sn=1") both read
# better set off on their own, even though they're still tick-consuming
# 'note'-kind events for collapse/linebreak purposes. Plain notes and
# rest/sust/release are the only ones that pack.
_OCTAVE_PREFIX_RE = re.compile(r'^o\d')
_NOISE_ALIAS_PREFIXES = tuple(f"@{alias}=" for alias, _comment in NOISE_NAMES.values())


def _is_packable_note(val: str) -> bool:
    if _OCTAVE_PREFIX_RE.match(val):
        return False
    if val.startswith('n$') or val.startswith('@rf$') or val.startswith(_NOISE_ALIAS_PREFIXES):
        return False
    return True


def _note_frame_length(val: str) -> int:
    """Every 'note' kind token's string ends in "=N" regardless of its
    exact shape (a plain note, an octave-prefixed one, a noise literal or
    alias, or @rl) -- the frame length is always whatever's after the last
    '='."""
    return int(val.rsplit('=', 1)[1])


def add_linebreaks(channels, file_base):
    """Inserts '__linebreak__' markers (pure whitespace to the parser --
    see render()) into each channel's token list at inferred measure
    boundaries, so a converted song doesn't render as one giant line per
    channel. See tempoInfer.py for how the tempo/measure length is
    estimated and songConfig.py for per-song overrides and known-echo
    channels this deliberately skips."""
    all_lengths = [_note_frame_length(val) for toks in channels.values()
                   for kind, val in toks if kind == 'note']
    if not all_lengths:
        return
    bpm, fpt = tempoInfer.estimate_tempo(all_lengths)
    measure_frames = tempoInfer.measure_length_frames(fpt, file_base)
    echo_channels = set(ECHO_CHANNELS.get(file_base, ()))

    for letter, toks in channels.items():
        if letter in echo_channels:
            continue
        lengths = []
        loop_index = None
        goto_targets = [v for k, v in toks if k == '__goto__']
        loop_target = goto_targets[0] if goto_targets else None
        for kind, val in toks:
            if kind == 'note':
                lengths.append(_note_frame_length(val))
            elif kind == '__label__' and val == loop_target:
                loop_index = len(lengths)
        break_after = tempoInfer.insert_linebreaks(lengths, measure_frames, loop_index)
        new_toks = []
        note_i = 0
        for kind, val in toks:
            new_toks.append((kind, val))
            if kind == 'note':
                if note_i in break_after:
                    new_toks.append(('__linebreak__', None))
                note_i += 1
        channels[letter] = new_toks


# Sfx line-breaking doesn't try to infer a tempo/measure grid at all --
# unlike a song, a one-shot sound effect isn't written on a musical beat,
# and most of its events (raw-frequency sweeps, per-note noise envelope
# triggers) aren't "notes" in any tempo-relevant sense to begin with. This
# just chunks by a fixed, arbitrary frame count purely for readability (see
# tempoInfer._forward_breaks, reused as-is with a fixed boundary instead of
# an inferred measure length).
SFX_CHUNK_FRAMES = 96


def add_sfx_linebreaks(channels, chunk_frames=SFX_CHUNK_FRAMES):
    """Same '__linebreak__'-insertion mechanics as add_linebreaks, but
    chunked by a fixed frame count instead of an inferred measure length --
    see module comment above."""
    for letter, toks in channels.items():
        lengths = [_note_frame_length(val) for kind, val in toks if kind == 'note']
        if not lengths:
            continue
        break_after = tempoInfer._forward_breaks(lengths, chunk_frames)
        new_toks = []
        note_i = 0
        for kind, val in toks:
            new_toks.append((kind, val))
            if kind == 'note':
                if note_i in break_after:
                    new_toks.append(('__linebreak__', None))
                note_i += 1
        channels[letter] = new_toks


def render(channels, title, extra_header_comment=None, is_sfx=False, is_vanilla=True):
    out = [f"#TITLE {title}"]
    if is_sfx:
        out.append("#SFX")
    if is_vanilla:
        # Every song/sfx this renders is decoded straight from real ROM
        # data (or, for sToMml.py's legacy bootstrap path, from a .s file
        # that itself was) -- every length below is an exact, literal frame
        # count (`=N`), not a musical tick count, since vanilla data has no
        # tempo of its own to derive one from. #VANILLA tells mml2wla to
        # interpret `=N` that way (see mml_documentation.md) instead of its
        # normal, tempo-relative meaning for hand-authored music.
        out.append("#VANILLA")
    if extra_header_comment:
        out.append(f"; {extra_header_comment}")
    out.append("")

    used_letters = [l for l in ['A', 'B', 'C', 'D'] if channels.get(l)]
    out.append(''.join(used_letters) + " t120 l8")
    out.append("")

    for letter in used_letters:
        toks = channels[letter]
        goto_targets = [t[1] for t in toks if t[0] == '__goto__']
        assert len(goto_targets) <= 1, "more than one goto per channel unsupported"
        loop_target = goto_targets[0] if goto_targets else None

        out.append(CHANNEL_LABELS[letter])

        if letter == 'D':
            used_aliases = {byte for kind, v in toks if kind == 'note'
                             for byte, (alias, _c) in NOISE_NAMES.items()
                             if v.startswith(f"@{alias}=")}
            for byte in sorted(used_aliases):
                alias, comment = NOISE_NAMES[byte]
                out.append(f"@{alias} = n${byte:02x} ; {comment}")
            if used_aliases:
                out.append("")

        line_toks = []  # (kind, str) pairs -- kind decides spacing, see flush()
        lines_for_channel = []

        def flush():
            if not line_toks:
                return
            pieces = [letter, ' ']
            prev_packable = False
            for kind, s in line_toks:
                # No space needed between two consecutive plain notes (also
                # rest/sust/release) -- the grammar doesn't need one there,
                # and packing them together reads like normal hand-written
                # MML (e.g. "cdefg"). An octave change or a noise
                # literal/alias note are still 'note'-kind events but read
                # better set off on their own (see _is_packable_note), same
                # as every other command (including the 'L' loop marker).
                cur_packable = kind == 'note' and _is_packable_note(s)
                if pieces[-1] != ' ' and not (prev_packable and cur_packable):
                    pieces.append(' ')
                pieces.append(s)
                prev_packable = cur_packable
            lines_for_channel.append(''.join(pieces))
            line_toks.clear()

        for kind, val in toks:
            if kind == '__goto__':
                continue  # implicit: emit_song auto-adds goto+cmdff from the 'L' marker
            elif kind == '__label__':
                if val == loop_target:
                    line_toks.append(('__label__', "L"))
                # else: an unreferenced mid-stream label -- shouldn't occur given
                # vanilla's one-loop-per-channel convention; if it does, this
                # silently drops the label, which is safe (nothing points to it).
            elif kind == '__linebreak__':
                flush()
            else:
                line_toks.append((kind, val))
        flush()

        out.extend(lines_for_channel)
        out.append("")
        out.append("")
    # Drop the extra trailing blank line after the very last channel.
    while out and out[-1] == "":
        out.pop()
    return '\n'.join(out) + '\n'


def main():
    import os
    if len(sys.argv) >= 2 and sys.argv[1] == '--pirates':
        _, _flag, s_path, ages_mml, seasons_mml = sys.argv
        ages_lines, seasons_lines = split_pirates(open(s_path).readlines())
        for lines, mml_path, game in [(ages_lines, ages_mml, 'Ages'), (seasons_lines, seasons_mml, 'Seasons')]:
            channels, is_sfx = convert(_expand_rept(lines))
            add_linebreaks(channels, os.path.splitext(os.path.basename(mml_path))[0])
            text = render(channels, 'Pirates',
                           extra_header_comment=("This differs between Ages and Seasons: the noise "
                                                  "channel's percussion pattern is unique to each "
                                                  "game (see the original audio/common/mus/pirates.s "
                                                  "for the shared square/wave channels this used to "
                                                  "include alongside it)."),
                           is_sfx=is_sfx)
            with open(mml_path, 'w') as f:
                f.write(text)
            print(f"wrote {mml_path} ({game})")
        return

    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <song.s> <song.mml>")
        print(f"       {sys.argv[0]} --pirates <pirates.s> <ages.mml> <seasons.mml>")
        sys.exit(1)
    s_path, mml_path = sys.argv[1:3]
    channels, is_sfx = convert(_expand_rept(open(s_path).readlines()))
    file_base = os.path.splitext(os.path.basename(mml_path))[0]
    if is_sfx:
        add_sfx_linebreaks(channels)
    else:
        add_linebreaks(channels, file_base)
    title = file_base
    extra_comment = None
    if title in TITLE_OVERRIDES:
        # This legacy bootstrap path already takes the output filename as an
        # explicit CLI arg, so the override's filename half is irrelevant here.
        _output_name, title, extra_comment = TITLE_OVERRIDES[title]
    text = render(channels, title, extra_header_comment=extra_comment, is_sfx=is_sfx)
    with open(mml_path, 'w') as f:
        f.write(text)
    print(f"wrote {mml_path}")


if __name__ == '__main__':
    main()
