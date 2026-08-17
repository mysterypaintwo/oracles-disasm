"""Command-line entry point and single/batch file orchestration."""

import argparse
import os
import re
import sys
from typing import List, Optional, Tuple

from .lexer import lex, MmlError
from .parser import Parser
from .emitter import emit_song
from .waveforms import WaveformAggregator
from .noise_envelope import NoiseEnvelopeAggregator


def label_name_from_base(file_base: str) -> str:
    if not file_base:
        return file_base
    return file_base[0].upper() + file_base[1:]


# #TITLE/#COMPOSER: file-level directives, not part of mmlgb's own grammar at
# all, so they're stripped out of the raw text before lexing rather than
# tokenized -- letting them reach the lexer would be actively wrong, not just
# unrecognized: e.g. the 'L' in "TITLE" or the 'C' in "COMPOSER" would be
# picked up as real tokens (the loop-marker command, a channel selector)
# once the rest of the line's letters get silently skipped as unmatched.
_TITLE_RE = re.compile(r'^#TITLE\b(.*)$', re.MULTILINE)
_COMPOSER_RE = re.compile(r'^#COMPOSER\b(.*)$', re.MULTILINE)
_FIX_REST_BLIP_RE = re.compile(r'^#FIX_REST_BLIP\b.*$', re.MULTILINE)
_VALID_TITLE_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def _extract_directives(text: str) -> Tuple[str, Optional[str], bool]:
    """Strips file-level directive lines out of the source. Returns
    (remaining_text, title_or_None, fix_rest_blip). #COMPOSER's value is
    recognized and discarded -- it's documentation only, with no effect on
    the output."""
    title: Optional[str] = None

    def _take_title(m: 're.Match') -> str:
        nonlocal title
        value = m.group(1).strip()
        if title is None:
            title = value
        return ''

    text = _TITLE_RE.sub(_take_title, text)
    text = _COMPOSER_RE.sub('', text)
    fix_rest_blip = _FIX_REST_BLIP_RE.search(text) is not None
    text = _FIX_REST_BLIP_RE.sub('', text)

    if title is not None and not _VALID_TITLE_RE.match(title):
        raise MmlError(
            f"Invalid #TITLE {title!r}: must be a valid label -- letters, digits, and "
            f"underscore only, not starting with a digit -- since it's used directly in "
            f"every generated label name (musTITLEStart, musTITLEChannel0, etc).")

    return text, title, fix_rest_blip


def convert_text(mml_text: str, file_base: str, waveform_agg: WaveformAggregator,
                  noise_envelope_agg: Optional[NoiseEnvelopeAggregator] = None) -> Tuple[str, List[str]]:
    """Parse+emit one MML source string. Returns (wla_text, warnings)."""
    mml_text, title, fix_rest_blip = _extract_directives(mml_text)
    # #TITLE overrides every label/symbol this run would otherwise derive
    # from the filename -- not just mus<Name>Start/Channel/Loop, but also
    # waveform_agg's/noise_envelope_agg's WF_<NAME>_.../"Used by" naming,
    # since both are handed this same effective base. Useful whenever the
    # filename itself isn't a valid or desired label component (spaces,
    # dashes, or just a name you'd rather see in the generated asm).
    effective_base = title if title is not None else file_base
    tokens = lex(mml_text)
    parser = Parser(tokens)
    song = parser.parse()
    label_name = label_name_from_base(effective_base)
    text = emit_song(song, label_name, effective_base, waveform_agg,
                      noise_envelope_agg=noise_envelope_agg, fix_rest_blip=fix_rest_blip)
    return text, song.warnings


def convert_file(input_path: str, output_path: str, waveform_agg: WaveformAggregator,
                  noise_envelope_agg: Optional[NoiseEnvelopeAggregator] = None) -> List[str]:
    with open(input_path, 'r') as f:
        mml_text = f.read()
    file_base = os.path.splitext(os.path.basename(output_path))[0]
    text, warnings = convert_text(mml_text, file_base, waveform_agg, noise_envelope_agg)
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
    ap.add_argument('input', help='Input .mml file, or input directory with --batch')
    ap.add_argument('output', help='Output .s file, or output directory with --batch')
    args = ap.parse_args(argv)

    had_warnings = False
    noise_envelope_agg = NoiseEnvelopeAggregator() if args.noise_envelope else None

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
                warnings = convert_file(in_path, out_path, waveform_agg, noise_envelope_agg)
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
            warnings = convert_file(args.input, args.output, waveform_agg, noise_envelope_agg)
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
