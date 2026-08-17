#!/usr/bin/python3
"""Build-time orchestrator for every .mml -> .s conversion in one game's
build, across every song and sound effect at once, sharing a single
WaveformAggregator -- this is what actually makes "a song's own newly
authored waveform" and "an existing named one from waveforms.json" compile
into one single, self-consistent audio/common/bin/waveforms.s, with every
song's `duty` reference landing on the right final entry.

Running mml2wla once per .mml file (the naive approach) can't do this: each
invocation would get its own fresh WaveformAggregator, so a brand new
waveform a song defines locally (`@waveN = {...}`, not an id already in
waveforms.json) would only ever be written to a `_waveforms_new.s` side
file nobody's build actually includes -- a real song's real audio would be
silently missing that waveform's data. This script instead converts every
.mml in one pass, all sharing one aggregator seeded to start numbering new
entries right after the last id already in waveforms.json, and folds
whatever it collects directly into the generated waveforms.s alongside the
JSON-sourced entries -- so there is exactly one generated table, and it's
always complete.

Usage: buildAudio.py --waveforms-json <path> --noise-json <path>
                      --waveforms-out <path> <song1.mml> <song2.mml> ...
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from mml2wla.cli import convert_file, MmlError
from mml2wla.noise import load_noise_json
from mml2wla.waveforms import WaveformAggregator
from waveformsJsonToS import generate as generate_waveforms_s


def _unpack(packed_bytes):
    """16 packed bytes -> 32 unpacked 0-15 samples, as a space-separated
    string -- the same "data" format waveforms.json/waveformsJsonToS.py use
    (see mml2wla/waveforms.py's pack_wave_samples for the inverse)."""
    samples = []
    for b in packed_bytes:
        samples.append(b >> 4)
        samples.append(b & 0xf)
    return ' '.join(str(s) for s in samples)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--waveforms-json', required=True)
    ap.add_argument('--noise-json')
    ap.add_argument('--waveforms-out', required=True)
    ap.add_argument('mml_files', nargs='+')
    args = ap.parse_args()

    with open(args.waveforms_json) as f:
        json_entries = json.load(f)
    json_waveforms = {e['id']: e['name'] for e in json_entries}

    noise_table, known_noise_frequencies = None, None
    if args.noise_json:
        noise_table, known_noise_frequencies, _names = load_noise_json(args.noise_json)

    waveform_agg = WaveformAggregator(next_free_id_hint=len(json_entries))

    had_errors = False
    for mml_path in args.mml_files:
        out_path = os.path.join(os.path.dirname(mml_path), 'bin',
                                 os.path.splitext(os.path.basename(mml_path))[0] + '.s')
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        try:
            warnings = convert_file(mml_path, out_path, waveform_agg,
                                     noise_table=noise_table, json_waveforms=json_waveforms,
                                     known_noise_frequencies=known_noise_frequencies)
        except MmlError as e:
            print(f"error: {mml_path}: {e}", file=sys.stderr)
            had_errors = True
            continue
        for w in warnings:
            print(f"warning: {mml_path}: {w}", file=sys.stderr)
    if had_errors:
        return 1

    # Fold whatever new waveforms this run discovered directly into the
    # generated table -- see module docstring for why this can't just be a
    # side file the user merges by hand.
    new_entries = [
        {'id': len(json_entries) + i, 'name': e['name'], 'data': _unpack(e['packed'])}
        for i, e in enumerate(waveform_agg.entries)
    ]
    all_entries = json_entries + new_entries
    text = generate_waveforms_s(all_entries)
    with open(args.waveforms_out, 'w') as f:
        f.write(text)
    if new_entries:
        print(f"waveforms.s: {len(json_entries)} from waveforms.json + "
              f"{len(new_entries)} newly authored in .mml (ids "
              f"{len(json_entries)}-{len(all_entries) - 1}): "
              + ', '.join(e['name'] for e in new_entries))
    return 0


if __name__ == '__main__':
    sys.exit(main())
