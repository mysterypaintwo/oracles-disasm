"""Tokenizer for mmlgb MML source.

Mirrors mmlgb-src/parser/src/Lexer.cs's token grammar. Comments are kept
(not discarded) so the parser can carry them through into the generated
output at their original position.
"""

import re
from dataclasses import dataclass
from typing import List


class MmlError(Exception):
    def __init__(self, msg, line=None):
        self.line = line
        super().__init__(f"line {line}: {msg}" if line else msg)


TOKEN_SPECS = [
    ('COMMENT', r';.*'),
    # A tool-specific extension, not part of upstream mmlgb syntax: selects a
    # waveform by referencing an existing external label/macro (e.g. one
    # already defined in the target project's waveform.s) instead of a
    # locally-defined numeric @wave id. Must come before MACRO below so
    # "@wave[FOO]" wins over the plain "@wave" alternative at this position.
    ('WAVECONST', r'@wave\[[A-Za-z_][A-Za-z0-9_]*\]'),
    # Another tool-specific extension: a literal noise-channel pitch byte,
    # e.g. "n34" (decimal) or "n$22" (hex, using the target engine's own $
    # notation rather than mmlgb's 0x) -- both spellings can name the same
    # byte. Lets a song pick one of the noise channel's fixed hardware
    # frequencies exactly, instead of via nearest-frequency matching from an
    # arbitrary chromatic note. Unlike a note letter (unambiguously one
    # character), the value here can be 1-3 decimal or hex digits, so a
    # length written straight after with no separator ("n$224") would be
    # genuinely ambiguous -- is that byte $22 length 4, or byte $224 (out of
    # range) with no explicit length? Bracket/brace-wrapping the value was
    # considered, but ppmck (a well-established predecessor MML compiler)
    # already solves this exact problem for its own analogous "direct note
    # number" syntax with a required comma before the length ("n0,4") --
    # matching that convention (see parser.py usage-site handling) instead
    # of inventing a new one.
    ('NOISE_LITERAL', r'n(\$[0-9a-fA-F]+|[0-9]+)'),
    ('HEXNUMBER', r'0x[0-9a-fA-F]+'),
    ('BINNUMBER', r'0b[01]+'),
    ('NUMBER', r'[0-9]+'),
    ('CHANNEL', r'[ABCD]'),
    ('NOTE', r'[cdefgab]'),
    ('SHARP', r'[#+]'),
    ('DASH', r'-'),
    ('COMMAND', r'[rwo<>lvtysL]'),
    ('DOT', r'\.'),
    ('COMMA', r','),
    ('TIE', r'\^'),
    ('MACRO', r'(@@|@po|@p|@ns|@ve|@v|@wave|@wd)'),
    # A user-defined noise pitch alias (e.g. "@k", "@snare", "@hhc") -- must
    # come after MACRO above so the fixed macro names still win when they
    # match; this catches any other "@word", meaningful only via a prior
    # "@word = n$XX" definition elsewhere in the same file (see parser.py).
    # Letters/underscore only, deliberately no digits: usage is written
    # like a note ("@k4"), so a digit right after the name has to be
    # unambiguously the length that follows, not part of the alias itself.
    ('NOISE_ALIAS', r'@[a-zA-Z_]+'),
    ('ASSIGN', r'='),
    ('LCURLY', r'\{'),
    ('RCURLY', r'\}'),
    ('LBRACKET', r'\['),
    ('RBRACKET', r'\]'),
    ('NEWLINE', r'\n'),
    ('WHITESPACE', r'[ \t\f\r]+'),
]

_TOKEN_RE = re.compile('|'.join(f'(?P<{name}>{pat})' for name, pat in TOKEN_SPECS))


@dataclass
class Token:
    type: str
    data: str
    line: int = 0

    def __repr__(self):
        return f"({self.type}, {self.data!r})"


def lex(text: str) -> List[Token]:
    """Tokenizes `text`, matching mmlgb's own lexer (parser/src/Lexer.cs)
    exactly, including a real quirk in its behavior: it scans for matches
    with .NET's `Regex.Matches`, a global "find every match anywhere in the
    string" search, rather than requiring the whole input to be covered by
    back-to-back matches. Any character (or run of characters) that doesn't
    match *any* token pattern is therefore silently skipped rather than
    rejected -- confirmed against the real compiler, which happily compiles
    a file containing a stray non-MML character (e.g. a decorative line of
    unicode box-drawing or other symbols with no leading `;`) with no error
    and no effect on the parsed result. We match that with `finditer`
    (Python's equivalent global search) instead of a strict, gap-free scan."""
    tokens = []
    line = 1
    for m in _TOKEN_RE.finditer(text):
        kind = m.lastgroup
        value = m.group()
        if kind != 'WHITESPACE':
            tokens.append(Token(kind, value, line))
        if kind == 'NEWLINE':
            line += 1
    tokens.append(Token('EOF', '', line))
    return tokens


def parse_int(s: str) -> int:
    neg = s.startswith('-')
    if neg:
        s = s[1:]
    if s.startswith('0x'):
        v = int(s[2:], 16)
    elif s.startswith('0b'):
        v = int(s[2:], 2)
    else:
        v = int(s)
    return -v if neg else v
