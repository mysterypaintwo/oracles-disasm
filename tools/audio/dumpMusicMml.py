#!/usr/bin/python3
"""Dumps every vanilla music track directly from a clean ROM into .mml --
the real, from-scratch source of truth this project needs (see
sToMml.py's docstring: that script bootstrapped the initial .mml corpus
from already-committed, already-decoded .s text, which is a one-time
shortcut, not a substitute for this).

Run this against your own legally-owned ROM to (re)generate the .mml
files locally; they're gitignored on purpose (see .gitignore) -- for legal
reasons this repo cannot distribute Nintendo's copyrighted music data
directly, only the tooling to reconstruct it from a ROM you already own.

Usage: dumpMusicMml.py <romfile>
"""
import os
import sys

sys.path.append(os.path.dirname(__file__) + '/..')  # for common.py, matching dumpMusic.py's own convention
from common import read16, bankedAddress, romIsSeasons

sys.path.insert(0, os.path.dirname(__file__))
from sToMml import (NOTE_LETTER_MML, NOISE_NAMES, TITLE_OVERRIDES,
                     ENGINE_CH_TO_LETTER, _collapse_redundant_state, add_linebreaks,
                     render)
from songConfig import SONG_MANIFEST

REPO = os.path.join(os.path.dirname(__file__), '..', '..')

# c1=0 .. b8=95 -- matches include/musicMacros.s's .enum block exactly (the
# same ordering byteToNote()/dumpMusic.py's noteTable uses).
_NOTE_ORDER = ['c', 'cs', 'd', 'ds', 'e', 'f', 'fs', 'g', 'gs', 'a', 'as', 'b']


def decode_channel(rom, start_address, engine_ch):
    """Decodes one music channel's raw byte stream into the same (kind,
    val) token list sToMml.py's convert() produces from .s text -- see its
    per-opcode comments for why each byte maps the way it does (rest vs
    sust vs release classification, env decay masking, the wave channel's
    octave/volume/duty quirks, etc.); this mirrors that exactly, just
    reading straight from ROM bytes instead of already-decoded .s text.
    """
    # First pass: does this channel loop, and if so, to where? (a `goto`
    # is always the very last real opcode in a channel -- see code/audio.s.)
    # Total instruction size (including the opcode byte itself) per range,
    # matching doNextChannelCommand's own dispatch exactly:
    #   $00-$5f (note), $60 (rest/release/sust register), $61 (sust),
    #   noise note (any byte, channel 6/7): opcode + 1 param = 2
    #   $d0-$df (vol): opcode only, volume is in the low nibble = 1
    #   $e0-$ef (env), $f0/$f6/$f8/$f9/$fd: opcode + 1 param = 2
    #   anything else $f0-$ff (unused by real vanilla data): opcode only = 1
    # This ignores raw-frequency mode (see decode_channel's own raw_freq_mode
    # below) -- once a $f0 on a square channel (engine_ch<4) has switched it
    # on, a byte < $d0 here is actually 3 bytes (lo/hi/wait), not 2 -- so
    # this scan tracks that same state itself rather than calling this
    # helper blindly.
    def _instruction_size(addr):
        byte = rom[addr]
        if byte in (0xf0, 0xf6, 0xf8, 0xf9, 0xfd) or byte < 0xd0 or 0xe0 <= byte < 0xf0:
            return 2
        return 1  # $d0-$df (vol), or an unused-by-vanilla $f0-$ff opcode

    address = start_address
    loop_target = None
    scan_raw_freq_mode = False
    while True:
        b = rom[address]
        if b == 0xff:
            break
        if b == 0xfe:
            target = read16(rom, address + 1)
            loop_target = bankedAddress((address + 1) // 0x4000, target)
            break
        if b == 0xf0:
            if engine_ch < 4:
                scan_raw_freq_mode = True
            address += 2
        elif scan_raw_freq_mode and b < 0xd0:
            address += 3
        else:
            address += _instruction_size(address)

    tokens = []
    address = start_address
    octave = 4
    decay = 0
    raw_freq_mode = False  # see the $f0 and raw-frequency-note handling below
    while True:
        if loop_target is not None and address == loop_target:
            tokens.append(('__label__', 'LOOP'))

        b = rom[address]
        address += 1

        if b == 0xff:
            break
        elif b == 0xfe:
            tokens.append(('__goto__', 'LOOP'))
            break
        elif b == 0xf2:
            continue  # confirmed no-op (see musicMacros.s's cmdf2 comment)
        elif b == 0xf6:
            param = rom[address]
            address += 1
            if engine_ch in (4, 5):
                # Numeric @waveN, matching the waveforms.json table index
                # directly (see mml2wla's unified @wave syntax) -- no name
                # lookup needed at all.
                tokens.append(('duty', f"@wave{param}"))
            else:
                tokens.append(('duty', f"@wd{param}"))
        elif b == 0xf9:
            param = rom[address]
            address += 1
            wait_code, depth = param >> 4, param & 0xf
            if wait_code == 0:
                tokens.append(('vibrato', f"@v0,{depth}"))
            else:
                tokens.append(('vibrato', f"@v0,{depth},={wait_code * 2}"))
        elif b == 0xf8:
            param = rom[address]
            address += 1
            signed = param if param < 128 else param - 256
            tokens.append(('pitchSlide', f"@s{signed}"))
        elif b == 0xfd:
            param = rom[address]
            address += 1
            signed = param if param < 128 else param - 256
            tokens.append(('pitchOffset', f"@po{signed}"))
        elif b == 0xf0:
            # Sfx-only in practice (confirmed unused by any real vanilla
            # music channel 0/1/4/6 data) -- overloaded per channel type,
            # see channelCmdf0 in code/audio.s. Noise: a raw one-shot
            # hardware envelope write (@er). Square: a one-way switch into
            # raw-frequency mode (@fm), after which subsequent notes are
            # literal hardware frequencies (@rf$<hex>), not note-table
            # lookups -- see the raw_freq_mode branch below.
            param = rom[address]
            address += 1
            if engine_ch in (6, 7):
                vol = (param >> 4) & 0xf
                direction = (param >> 3) & 1
                pace = param & 0x7
                tokens.append(('noise_raw_env', f"@er{vol},{direction},{pace}"))
            elif engine_ch < 4:
                raw_freq_mode = True
                tokens.append(('freq_mode', f"@fm{param}"))
            else:
                raise ValueError(f"unexpected cmdf0 on wave channel (engine_ch={engine_ch})")
        elif b >= 0xf0:
            pass  # any other f0-ff: no known music usage
        elif b >= 0xe0:
            attack = b & 0xf
            param = rom[address]
            address += 1
            decay = param & 0x7  # cmde0Toef masks decay with & $07 at runtime
            if attack == 0 and decay == 0:
                tokens.append(('env', "@ve0"))
            elif attack == 0:
                tokens.append(('env', f"@ve-{decay}"))
            else:
                tokens.append(('env', f"@ea{attack},{decay}"))
        elif b >= 0xd0:
            vol = b & 0xf
            if engine_ch in (4, 5):
                tokens.append(('vol', f"@vr{vol}"))
            else:
                tokens.append(('vol', f"v{vol}"))
        elif raw_freq_mode:
            # See the $f0/@fm handling above: once set, this channel's
            # dispatch (code/audio.s's @channel0To3) never checks for $60/
            # $61 again -- every byte here (any value 0-$cf, since $d0-$ff
            # are always intercepted earlier regardless of this mode) is a
            # literal raw hardware frequency's low byte instead.
            hi = rom[address]
            address += 1
            length = rom[address]
            address += 1
            value = (hi << 8) | b
            tokens.append(('note', f"@rf${value:04x}={length}"))
        elif b == 0x60:
            param = rom[address]
            address += 1
            if engine_ch in (4, 5):
                tokens.append(('note', f"r={param}"))
            elif engine_ch not in (6, 7) and decay == 0:
                tokens.append(('note', f"@rl={param}"))
            else:
                tokens.append(('note', f"w={param}"))
        elif b == 0x61:
            param = rom[address]
            address += 1
            tokens.append(('note', f"w={param}"))
        elif engine_ch in (6, 7):
            wait = rom[address]
            address += 1
            if b in NOISE_NAMES:
                alias, _comment = NOISE_NAMES[b]
                tokens.append(('note', f"@{alias}={wait}"))
            else:
                tokens.append(('note', f"n${b:02x},={wait}"))
        else:
            length = rom[address]
            address += 1
            note_octave = b // 12 + 1
            note_idx = b % 12
            letter = NOTE_LETTER_MML[_NOTE_ORDER[note_idx]]
            if engine_ch in (4, 5):
                note_octave += 1  # see notes.py's NOTE_BYTE_ADJUST[2] == -12
            toks = []
            if note_octave != octave:
                toks.append(f"o{note_octave}")
                octave = note_octave
            toks.append(f"{letter}={length}")
            tokens.append(('note', ''.join(toks)))

    return _collapse_redundant_state(tokens)


def parse_sound_pointer_names(sound_pointers_s_path):
    """index -> label name (e.g. "musAmbiPalace"), from the committed
    soundPointers.s -- a plain index/address table with no music content
    of its own, so (unlike the .mml this script produces) it's fine to
    keep this committed and read it back here."""
    import re
    names = {}
    pat = re.compile(r'/\*\s*0x([0-9a-fA-F]+)\s*\*/\s*m_soundPointer\s+(\S+)')
    for line in open(sound_pointers_s_path):
        m = pat.search(line)
        if m:
            names[int(m.group(1), 16)] = m.group(2)
    return names


def parse_channel_pointer_table(rom, address, bank):
    """Reads the (channel, address) list for one song -- terminated by
    $ff -- matching dumpMusic.py's own parseChannelPointers exactly.
    `bank` is the *sound entry's own* computed bank (soundBaseBank + its
    delta byte from the first-level pointer table), not one derived from
    the current read position: the channel pointer table and the actual
    channel data it points to can legitimately live in a different bank
    than the first-level pointer table itself (that delta byte is exactly
    what makes that possible), unlike a `goto` loop target, which always
    stays within its own channel's bank and so *is* safe to derive from
    the current position (see decode_channel)."""
    entries = []
    while True:
        b = rom[address]
        address += 1
        if b == 0xff:
            break
        channel = b & 0xf
        target = bankedAddress(bank, read16(rom, address))
        address += 2
        entries.append((channel, target))
    return entries


def _base_name(label):
    """"musAmbiPalace" -> "ambiPalace", "sndSubrosianShop" -> "subrosianShop"
    -- both real label prefixes seen in soundPointers.s (see sToMml.py's
    CHANNEL_START_RE for the same "mus"/"snd" duality on the channel-data
    side); both happen to be 3 characters, so one slice handles either.
    A handful of real sfx labels are literally a bare hex index with no
    real name at all (e.g. "snd7a") -- stripping the prefix there would
    produce a name starting with a digit, invalid as an mml #TITLE/label
    (see cli.py's _VALID_TITLE_RE), so the prefix is kept instead."""
    rest = label[3:]
    base = rest[0].lower() + rest[1:]
    if base[0].isdigit():
        return label[0].lower() + label[1:]
    return base


def dump(rom_path):
    rom = bytearray(open(rom_path, 'rb').read())
    seasons = romIsSeasons(rom)
    game_dir = 'seasons' if seasons else 'ages'
    sound_base_bank = 0x39
    sound_pointer_table = 0xe57cf if seasons else 0xe5748
    num_sound_indices = 0xdf

    names = parse_sound_pointer_names(os.path.join(REPO, f"audio/{game_dir}/soundPointers.s"))

    # Group indices sharing the exact same address -- e.g. sound index 0
    # ("musNone") and index 1 ("musTitlescreen") are the same title-screen
    # theme twice (see dumpMusic.py's own identical dedup-by-address logic
    # for confirmation this is the right equality check, not one this
    # script invented). SONG_MANIFEST (songConfig.py) says which of a
    # group's candidate names is the one to actually write a file for;
    # non-primary names are meant to be reattached as build-time aliases
    # in soundChannelData.s instead of dumped a second time (see the
    # existing musNone/musTitlescreen and sndSubrosianShop aliases there
    # for the pattern -- this script only produces the .mml, it doesn't
    # touch those .s alias lines).
    groups = {}  # address -> (bank, [index, ...])
    for i in range(num_sound_indices):
        bank = sound_base_bank + rom[sound_pointer_table + i * 3]
        pointer = read16(rom, sound_pointer_table + i * 3 + 1)
        address = bankedAddress(sound_base_bank, pointer)
        if address not in groups:
            groups[address] = (bank, [])
        groups[address][1].append(i)

    written = 0
    for address, (bank, indices) in groups.items():
        candidate_bases = [_base_name(names[i]) for i in indices if i in names]
        primary = next((b for b in candidate_bases if b in SONG_MANIFEST), None)
        if primary is None:
            continue  # not a recognized music track (sfx marker, padding, etc.)

        is_gamespecific = SONG_MANIFEST[primary] == 'gamespecific'
        out_dir = game_dir if is_gamespecific else SONG_MANIFEST[primary]

        channels = {}
        for channel, target in parse_channel_pointer_table(rom, address, bank):
            if channel not in ENGINE_CH_TO_LETTER:
                continue
            letter = ENGINE_CH_TO_LETTER[channel]
            channels[letter] = decode_channel(rom, target, channel)

        extra_comment = None
        title = primary
        output_name = primary
        if primary in TITLE_OVERRIDES:
            output_name, title, extra_comment = TITLE_OVERRIDES[primary]
        elif is_gamespecific:
            extra_comment = ("This song is dumped separately per game (see SONG_MANIFEST in "
                              "songConfig.py): Ages and Seasons each have their own copy of it "
                              "in the ROM, which may or may not actually differ.")
        add_linebreaks(channels, primary)
        text = render(channels, title, extra_header_comment=extra_comment)

        out_path = os.path.join(REPO, f"audio/{out_dir}/mus/{output_name}.mml")
        with open(out_path, 'w') as f:
            f.write(text)
        written += 1
        print(f"wrote {os.path.relpath(out_path, REPO)}")

    print(f"\n{written} songs written for {game_dir}")


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <romfile>")
        sys.exit(1)
    dump(sys.argv[1])
