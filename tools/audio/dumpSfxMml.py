#!/usr/bin/python3
"""Dumps every vanilla sound effect directly from a clean ROM into .mml --
the sfx counterpart of dumpMusicMml.py (see its docstring for the overall
rationale). Reuses that module's decode_channel wholesale: sfx and music
share the exact same channel-data opcode format, just on a different set of
4 engine channel slots (see emitter.py's CHANNEL_NUM_SFX) -- decode_channel
already handles both.

Unlike music, sfx entries carry no hand-curated name->directory manifest:
which of the ~140 vanilla sound effects is shared between both games versus
unique to one isn't recorded anywhere before this script decides it, so it
needs *both* ROMs at once to find out. Matching is done by each entry's
*table index* (soundPointers.s's own `/* 0xXX */` position), not by name --
confirmed necessary, not just simpler: several real entries are named a
real word in one game (e.g. Ages' sndOpenGate) but only a generic
`sndUnknown7d`/bare `snd7a`-style placeholder in the other, at the exact
same index, because whoever filled in that game's table didn't know what
the sound was. Matching by name alone would treat those as two unrelated
sounds instead of the one shared effect they actually are. Once matched by
index:
  - an index that only exists in one game's soundPointers.s -> that game's
    audio/<game>/sfx/ only.
  - an index in both games, with identical decoded content -> audio/common/sfx/.
  - an index in both games, with genuinely different content -> both
    audio/ages/sfx/ and audio/seasons/sfx/ (same treatment as music's
    pirates.s/mml -- see sToMml.py's split_pirates docstring).
The filename itself always prefers whichever game's name for that index
isn't a generic placeholder (see _is_placeholder_name), so a real name in
either game wins over the other game's "unknownXX"/bare-hex guess.

Run this against your own legally-owned ROMs to (re)generate the .mml files
locally; they're gitignored on purpose (see .gitignore) -- for legal reasons
this repo cannot distribute Nintendo's copyrighted audio data directly, only
the tooling to reconstruct it from ROMs you already own.

Usage: dumpSfxMml.py <ages-romfile> <seasons-romfile>
"""
import os
import re
import sys

sys.path.append(os.path.dirname(__file__) + '/..')  # for common.py
from common import read16, bankedAddress, romIsSeasons

sys.path.insert(0, os.path.dirname(__file__))
from sToMml import ENGINE_CH_TO_LETTER, add_sfx_linebreaks, render
from dumpMusicMml import (decode_channel, parse_sound_pointer_names,
                           parse_channel_pointer_table, _base_name)

REPO = os.path.join(os.path.dirname(__file__), '..', '..')

# The 4 engine channel numbers sfx use in place of music's 0/1/4/6 (see
# emitter.py's CHANNEL_NUM_SFX) -- an entry is a sound effect, not a song,
# iff any of its channels is one of these.
_SFX_ENGINE_CHANNELS = (2, 3, 5, 7)

_PLACEHOLDER_NAME_RE = re.compile(r'^(?:[0-9a-f]+|unknown[0-9a-f]+)$')


def _is_placeholder_name(name):
    """True for a table-index-derived guess ("7a", "unknownb5") rather than
    a real descriptive name -- see module docstring."""
    return bool(_PLACEHOLDER_NAME_RE.match(name))


def _collect(rom_path):
    """Decodes every sfx-classified entry from one ROM. Returns {first_index:
    (candidate_names, {letter: tokens})} -- keyed by table index (stable
    across games), not name (isn't -- see module docstring)."""
    rom = bytearray(open(rom_path, 'rb').read())
    seasons = romIsSeasons(rom)
    game_dir = 'seasons' if seasons else 'ages'
    sound_base_bank = 0x39
    sound_pointer_table = 0xe57cf if seasons else 0xe5748
    num_sound_indices = 0xdf

    names = parse_sound_pointer_names(os.path.join(REPO, f"audio/{game_dir}/soundPointers.s"))

    # Group indices sharing the exact same address -- see dumpMusicMml.py's
    # dump() for why this (not (bank, address)) is the right dedup key.
    groups = {}  # address -> (bank, [index, ...])
    for i in range(num_sound_indices):
        bank = sound_base_bank + rom[sound_pointer_table + i * 3]
        pointer = read16(rom, sound_pointer_table + i * 3 + 1)
        address = bankedAddress(sound_base_bank, pointer)
        if address not in groups:
            groups[address] = (bank, [])
        groups[address][1].append(i)

    result = {}
    for address, (bank, indices) in groups.items():
        entries = parse_channel_pointer_table(rom, address, bank)
        if not entries:
            continue
        if not any(ch in _SFX_ENGINE_CHANNELS for ch, _ in entries):
            continue  # a music entry -- see dumpMusicMml.py instead
        candidate_names = [_base_name(names[i]) for i in sorted(indices) if i in names]
        if not candidate_names:
            continue  # unnamed/unreferenced entry
        channels = {}
        for channel, target in entries:
            if channel not in ENGINE_CH_TO_LETTER:
                continue
            letter = ENGINE_CH_TO_LETTER[channel]
            channels[letter] = decode_channel(rom, target, channel)
        if not any(channels.values()):
            continue  # every channel immediately terminates -- a real, silent no-op entry
        add_sfx_linebreaks(channels)
        result[min(indices)] = (candidate_names, channels)
    return result


def _choose_name(ages_names, seasons_names):
    for names in (ages_names, seasons_names):
        for name in names:
            if not _is_placeholder_name(name):
                return name
    return (ages_names or seasons_names)[0]


def dump(ages_rom_path, seasons_rom_path):
    ages_sfx = _collect(ages_rom_path)
    seasons_sfx = _collect(seasons_rom_path)

    written = 0
    for index in sorted(set(ages_sfx) | set(seasons_sfx)):
        ages_names, ages_ch = ages_sfx.get(index, ([], None))
        seasons_names, seasons_ch = seasons_sfx.get(index, ([], None))

        if ages_ch is not None and seasons_ch is not None and ages_ch == seasons_ch:
            # Genuinely the same sound in both games (identical decoded
            # content) -- one shared file, named via whichever game's label
            # isn't a placeholder guess (see module docstring).
            out_dirs = [('common', _choose_name(ages_names, seasons_names), ages_ch)]
        else:
            # NOT necessarily "the same effect with per-game data" (unlike
            # music's pirates.s): confirmed against real data that two
            # completely unrelated sounds can coincidentally share a table
            # index (e.g. Ages' sndMoveBlock2 and Seasons'
            # sndDodongoOpenMouth both sit at index 0x7f) -- each game's own
            # name is used for its own file rather than cross-picking one,
            # since picking the other game's name here would silently
            # mislabel this game's actual, unrelated sound.
            out_dirs = []
            if ages_ch is not None:
                out_dirs.append(('ages', ages_names[0], ages_ch))
            if seasons_ch is not None:
                out_dirs.append(('seasons', seasons_names[0], seasons_ch))

        for out_dir, name, channels in out_dirs:
            text = render(channels, name, is_sfx=True)
            out_path = os.path.join(REPO, f"audio/{out_dir}/sfx/{name}.mml")
            with open(out_path, 'w') as f:
                f.write(text)
            written += 1
            print(f"wrote {os.path.relpath(out_path, REPO)}")

    print(f"\n{written} sound effect file(s) written")


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <ages-romfile> <seasons-romfile>")
        sys.exit(1)
    dump(sys.argv[1], sys.argv[2])
