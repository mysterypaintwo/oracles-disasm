#!/usr/bin/python3
"""Diagnostic: assumes every song is 4/4 (see tempoInfer.py/songConfig.py)
and reports which ones *don't* actually line up cleanly under that
assumption -- i.e. where a channel's intro (before its loop point) or loop
body (from the loop point to the end) isn't a near-whole number of
192-tick measures at the song's own inferred tempo. Those are exactly the
songs that need a TIME_SIG_OVERRIDES (a genuinely different time
signature) or ECHO_CHANNELS (a delayed-echo channel whose timing is
intentionally offset from the real grid) entry in songConfig.py.

Run directly: reads every committed audio/*/mus/*.mml, decodes each
channel's own note lengths back out of its =N notation (no need to touch
ROM or .s data -- the committed .mml is already the source of truth), and
prints one line per misaligned channel.
"""
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
import tempoInfer

REPO = os.path.join(os.path.dirname(__file__), '..', '..')

_CHANNEL_LINE_RE = re.compile(r'^([ABCD]) ')
# A note/rest/wait/release/noise-note occurrence, with an optional leading
# octave change (sToMml.py packs those onto the same note with no space --
# see convert()'s note-building code), OR a standalone 'L' marker.
# Consecutive notes are also packed with no space between them (e.g.
# "c=4d=8"), so this has to scan the whole line with finditer rather than
# split on whitespace -- splitting would merge a run of packed notes into
# one unsplittable token. Anything else that happens to contain '=' (a
# vibrato delay's ",=N") is deliberately not matched here.
_LENGTH_TOKEN_RE = re.compile(
    r'(?:o\d+)?(?:[a-g][+\-]?|n\$[0-9a-fA-F]+,|@rl|r|w)=(\d+)|(?<![\w@])(L)(?![a-zA-Z0-9_])')


def channel_lengths_and_loop(mml_text, letter):
    """Returns (lengths, loop_index) for one channel across every line in
    the file that starts with that channel's letter -- loop_index is the
    position (in `lengths`) of the note immediately after the 'L' marker,
    or None if this channel has no loop point."""
    lengths = []
    loop_index = None
    for line in mml_text.splitlines():
        m = _CHANNEL_LINE_RE.match(line)
        if not m or m.group(1) != letter:
            continue
        rest = line[len(letter):]
        for m2 in _LENGTH_TOKEN_RE.finditer(rest):
            if m2.group(2) == 'L':
                loop_index = len(lengths)
            else:
                lengths.append(int(m2.group(1)))
    return lengths, loop_index


def main():
    mml_files = sorted(glob.glob(os.path.join(REPO, 'audio/*/mus/*.mml')))
    any_flagged = False
    for path in mml_files:
        rel = os.path.relpath(path, REPO)
        file_base = os.path.splitext(os.path.basename(path))[0]
        text = open(path).read()

        all_lengths = []
        per_channel = {}
        for letter in 'ABCD':
            lengths, loop_index = channel_lengths_and_loop(text, letter)
            if lengths:
                per_channel[letter] = (lengths, loop_index)
                all_lengths.extend(lengths)
        if not all_lengths:
            continue

        bpm, fpt = tempoInfer.estimate_tempo(all_lengths)
        measure_frames = tempoInfer.measure_length_frames(fpt, file_base)
        echo_channels = set(tempoInfer.ECHO_CHANNELS.get(file_base, ()))

        for letter, (lengths, loop_index) in per_channel.items():
            if letter in echo_channels:
                continue
            # Only the loop body has to tile cleanly into whole measures
            # (it repeats, so it must); the intro leading into it is
            # frequently an anacrusis -- a pickup phrase shorter than a
            # full measure -- which is a normal, expected reason for it
            # *not* to land on a whole-measure boundary, not a misalignment
            # worth flagging (see insert_linebreaks's own docstring).
            segments = [('whole', lengths)] if loop_index is None else [('loop', lengths[loop_index:])]
            for name, seg in segments:
                if not seg:
                    continue
                total = sum(seg)
                ok, measures, error = tempoInfer.check_alignment(total, measure_frames)
                if not ok:
                    any_flagged = True
                    print(f"{rel} channel {letter} ({name}): {measures} measures "
                          f"at {error*100:.1f}% error (bpm={bpm:.1f})")
    if not any_flagged:
        print("Every song lines up cleanly under the 4/4 assumption.")


if __name__ == '__main__':
    main()
