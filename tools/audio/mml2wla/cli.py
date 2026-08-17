"""Command-line entry point and single/batch file orchestration."""

import argparse
import os
import re
import sys
from typing import Dict, List, Optional, Tuple

from .lexer import lex, MmlError
from .parser import Parser
from .emitter import emit_song
from .waveforms import WaveformAggregator, load_waveforms_json
from .noise import NoiseTable, load_noise_json
from .noise_envelope import NoiseEnvelopeAggregator


def label_name_from_base(file_base: str) -> str:
    if not file_base:
        return file_base
    return file_base[0].upper() + file_base[1:]


# #TITLE/#COMPOSER/#SFX: file-level directives, not part of mmlgb's own
# grammar at all, so they're stripped out of the raw text before lexing
# rather than tokenized -- letting them reach the lexer would be actively
# wrong, not just unrecognized: e.g. the 'L' in "TITLE" or the 'C' in
# "COMPOSER" would be picked up as real tokens (the loop-marker command, a
# channel selector) once the rest of the line's letters get silently
# skipped as unmatched.
_TITLE_RE = re.compile(r'^#TITLE\b(.*)$', re.MULTILINE)
_COMPOSER_RE = re.compile(r'^#COMPOSER\b(.*)$', re.MULTILINE)
# Marks this file as a sound effect rather than music: A/B/C/D compile to
# this engine's separate sfx-override channel slots (2/3/5/7, see
# emitter.py's CHANNEL_NUM_SFX) instead of the music ones (0/1/4/6), and
# generated labels use the "snd" prefix (sndFooStart/...) instead of "mus" --
# matching the reference disassembly's own mus/snd naming split for the two
# content types exactly (see audio/*/{mus,sfx}/*.s).
_SFX_RE = re.compile(r'^#SFX\b.*$', re.MULTILINE)
# Marks this file as a byte-accurate reproduction of real vanilla ROM data
# (see tools/audio/dumpMusicMml.py/dumpSfxMml.py -- every song/sfx dumped
# straight from a ROM gets this), which changes what `=X` means for the
# whole file: a raw, tempo-independent hardware frame count (what vanilla
# data actually is -- it has no tempo of its own) instead of a musical tick
# count (see parser.py's Parser.is_vanilla). Also switches on the
# automatic same-length-run detection for the shortNote/setDefaultLength
# space optimization (see emitter.py) -- a hand-authored file gets that
# same optimization too, but only for notes that already rely on `l`
# themselves, since which notes "share the same length" as a deliberate
# choice is something only the author actually knows.
_VANILLA_RE = re.compile(r'^#VANILLA\b.*$', re.MULTILINE)
# Obsolete: #FIX_REST_BLIP existed to work around a real audio.s bug where a
# chained `rest` retriggered an audible decay-to-silence envelope on every
# chunk. That's fixed now -- `rest` forces an instant, silent volume-0 write
# with no envelope stepping at all, so retriggering it produces no blip
# regardless of chaining. Kept recognized (and stripped, so it doesn't get
# misparsed as note data) purely so old .mml files with the directive don't
# suddenly fail to parse; it's a no-op now, and flagged as such below.
_FIX_REST_BLIP_RE = re.compile(r'^#FIX_REST_BLIP\b.*$', re.MULTILINE)
_VALID_TITLE_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def _extract_directives(text: str) -> Tuple[str, Optional[str], bool, bool, Optional[str]]:
    """Strips file-level directive lines out of the source. Returns
    (remaining_text, title_or_None, is_sfx, is_vanilla,
    obsolete_directive_warning_or_None). #COMPOSER's value is recognized
    and discarded -- it's documentation only, with no effect on the
    output."""
    title: Optional[str] = None

    def _take_title(m: 're.Match') -> str:
        nonlocal title
        value = m.group(1).strip()
        if title is None:
            title = value
        return ''

    text = _TITLE_RE.sub(_take_title, text)
    text = _COMPOSER_RE.sub('', text)
    is_sfx = _SFX_RE.search(text) is not None
    text = _SFX_RE.sub('', text)
    is_vanilla = _VANILLA_RE.search(text) is not None
    text = _VANILLA_RE.sub('', text)
    warning = None
    if _FIX_REST_BLIP_RE.search(text) is not None:
        warning = ("#FIX_REST_BLIP is obsolete and has no effect: the engine bug it worked "
                   "around (a chained `rest` audibly retriggering a decay envelope) is fixed "
                   "-- `rest` is now an instant, clean cutoff regardless of chaining. Safe to "
                   "remove this line.")
    text = _FIX_REST_BLIP_RE.sub('', text)

    if title is not None and not _VALID_TITLE_RE.match(title):
        raise MmlError(
            f"Invalid #TITLE {title!r}: must be a valid label -- letters, digits, and "
            f"underscore only, not starting with a digit -- since it's used directly in "
            f"every generated label name (musTITLEStart/sndTITLEStart, musTITLEChannel0, "
            f"etc).")

    return text, title, is_sfx, is_vanilla, warning


def convert_text(mml_text: str, file_base: str, waveform_agg: WaveformAggregator,
                  noise_envelope_agg: Optional[NoiseEnvelopeAggregator] = None,
                  noise_table: Optional[NoiseTable] = None,
                  json_waveforms: Optional[Dict[int, str]] = None,
                  known_noise_frequencies=None) -> Tuple[str, List[str]]:
    """Parse+emit one MML source string. Returns (wla_text, warnings)."""
    mml_text, title, is_sfx, is_vanilla, obsolete_directive_warning = _extract_directives(mml_text)
    # #TITLE overrides every label/symbol this run would otherwise derive
    # from the filename -- not just mus<Name>Start/Channel/Loop, but also
    # waveform_agg's/noise_envelope_agg's WF_<NAME>_.../"Used by" naming,
    # since both are handed this same effective base. Useful whenever the
    # filename itself isn't a valid or desired label component (spaces,
    # dashes, or just a name you'd rather see in the generated asm).
    effective_base = title if title is not None else file_base
    tokens = lex(mml_text)
    parser = Parser(tokens, json_waveforms=json_waveforms,
                     known_noise_frequencies=known_noise_frequencies, is_vanilla=is_vanilla)
    song = parser.parse()
    label_name = label_name_from_base(effective_base)
    text = emit_song(song, label_name, effective_base, waveform_agg, noise_table=noise_table,
                      noise_envelope_agg=noise_envelope_agg, is_sfx=is_sfx,
                      json_waveforms=json_waveforms, is_vanilla=is_vanilla)
    warnings = song.warnings
    if obsolete_directive_warning:
        warnings = [obsolete_directive_warning] + warnings
    return text, warnings


def convert_file(input_path: str, output_path: str, waveform_agg: WaveformAggregator,
                  noise_envelope_agg: Optional[NoiseEnvelopeAggregator] = None,
                  noise_table: Optional[NoiseTable] = None,
                  json_waveforms: Optional[Dict[int, str]] = None,
                  known_noise_frequencies=None) -> List[str]:
    with open(input_path, 'r') as f:
        mml_text = f.read()
    file_base = os.path.splitext(os.path.basename(output_path))[0]
    text, warnings = convert_text(mml_text, file_base, waveform_agg, noise_envelope_agg,
                                   noise_table=noise_table, json_waveforms=json_waveforms,
                                   known_noise_frequencies=known_noise_frequencies)
    with open(output_path, 'w') as f:
        f.write(text)
    return warnings


def _print_warnings(source_label: str, warnings: List[str]):
    for w in warnings:
        print(f"warning: {source_label}: {w}", file=sys.stderr)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='mml2wla',
        description='Convert mmlgb MML music into WLA-DX sound-engine channel data, as used '
                    'by the Zelda Oracle of Ages/Seasons disassembly and compatible projects.')
    ap.add_argument('--batch', action='store_true',
                     help='Treat input/output as directories: convert every .mml file in '
                          'the input directory, with waveform deduplication shared across '
                          'the whole batch.')
    ap.add_argument('--noise-envelope', action='store_true',
                     help="Give the noise channel exact @ve support by generating new "
                          "noise-table entries on the fly (deduplicated across a --batch run "
                          "the same way waveforms are) and referencing them directly in the "
                          "converted song, instead of dropping @ve on that channel. Writes "
                          "noise_new.s (or <output>_noise_new.s without --batch) with the new "
                          "entries to merge into your project's noise table. See "
                          "mml2wla_documentation.md and noise_envelope.py for the alternative "
                          "of rewriting the song instead of extending the table.")
    ap.add_argument('--waveforms-json',
                     help='Path to a waveforms.json manifest (see audio/common/waveforms.json '
                          'in the Zelda Oracle of Ages/Seasons disassembly): pre-existing named '
                          'waveforms a .mml file can reference by numeric id (@waveN) with no '
                          'local {...} definition of its own. Without this, every @waveN a '
                          'song uses must be locally defined in that same file.')
    ap.add_argument('--noise-json',
                     help='Path to a noise.json manifest (see audio/common/noise.json in the '
                          'Zelda Oracle of Ages/Seasons disassembly): the target engine\'s '
                          'fixed noise-channel palette, replacing this tool\'s own compiled-in '
                          'reference copy (noise.py\'s REFERENCE_NOISE_ENTRIES) for '
                          'nearest-frequency matching, n$XX/alias validation, and noise-alias '
                          'definitions.')
    ap.add_argument('input', help='Input .mml file, or input directory with --batch')
    ap.add_argument('output', help='Output .s file, or output directory with --batch')
    args = ap.parse_args(argv)

    had_warnings = False
    noise_envelope_agg = NoiseEnvelopeAggregator() if args.noise_envelope else None
    json_waveforms = load_waveforms_json(args.waveforms_json) if args.waveforms_json else None
    if args.noise_json:
        noise_table, known_noise_frequencies, _names = load_noise_json(args.noise_json)
    else:
        noise_table, known_noise_frequencies = None, None

    if args.batch:
        if not os.path.isdir(args.input):
            print(f"error: {args.input} is not a directory", file=sys.stderr)
            return 1
        os.makedirs(args.output, exist_ok=True)
        mml_files = sorted(f for f in os.listdir(args.input) if f.lower().endswith('.mml'))
        if not mml_files:
            print(f"warning: no .mml files found in {args.input}", file=sys.stderr)
        waveform_agg = WaveformAggregator()
        for fname in mml_files:
            in_path = os.path.join(args.input, fname)
            file_base = os.path.splitext(fname)[0]
            out_path = os.path.join(args.output, file_base + '.s')
            try:
                warnings = convert_file(in_path, out_path, waveform_agg, noise_envelope_agg,
                                         noise_table=noise_table, json_waveforms=json_waveforms,
                                         known_noise_frequencies=known_noise_frequencies)
            except MmlError as e:
                print(f"error: {fname}: {e}", file=sys.stderr)
                return 1
            if warnings:
                had_warnings = True
                _print_warnings(fname, warnings)
            print(f"converted {fname} -> {os.path.relpath(out_path)}")
        waveforms_text = waveform_agg.emit()
        if waveforms_text:
            wf_path = os.path.join(args.output, 'waveforms_new.s')
            with open(wf_path, 'w') as f:
                f.write(waveforms_text)
            print(f"wrote {os.path.relpath(wf_path)} ({len(waveform_agg.entries)} new waveform(s))")
        if noise_envelope_agg is not None:
            noise_text = noise_envelope_agg.emit()
            if noise_text:
                ne_path = os.path.join(args.output, 'noise_new.s')
                with open(ne_path, 'w') as f:
                    f.write(noise_text)
                print(f"wrote {os.path.relpath(ne_path)} "
                      f"({len(noise_envelope_agg.entries)} new noise-table entr"
                      f"{'y' if len(noise_envelope_agg.entries) == 1 else 'ies'})")
    else:
        waveform_agg = WaveformAggregator()
        try:
            warnings = convert_file(args.input, args.output, waveform_agg, noise_envelope_agg,
                                     noise_table=noise_table, json_waveforms=json_waveforms,
                                     known_noise_frequencies=known_noise_frequencies)
        except MmlError as e:
            print(f"error: {args.input}: {e}", file=sys.stderr)
            return 1
        if warnings:
            had_warnings = True
            _print_warnings(os.path.basename(args.input), warnings)
        print(f"converted {args.input} -> {args.output}")
        waveforms_text = waveform_agg.emit()
        if waveforms_text:
            base = os.path.splitext(args.output)[0]
            wf_path = base + '_waveforms_new.s'
            with open(wf_path, 'w') as f:
                f.write(waveforms_text)
            print(f"wrote {wf_path} ({len(waveform_agg.entries)} new waveform(s))")
        if noise_envelope_agg is not None:
            noise_text = noise_envelope_agg.emit()
            if noise_text:
                base = os.path.splitext(args.output)[0]
                ne_path = base + '_noise_new.s'
                with open(ne_path, 'w') as f:
                    f.write(noise_text)
                print(f"wrote {ne_path} "
                      f"({len(noise_envelope_agg.entries)} new noise-table entr"
                      f"{'y' if len(noise_envelope_agg.entries) == 1 else 'ies'})")

    if had_warnings:
        print("warning: some MML features had no equivalent in this engine's format and "
              "were dropped or approximated; see warnings above.", file=sys.stderr)

    return 0
