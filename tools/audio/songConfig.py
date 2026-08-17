"""Per-song hand-tuned overrides for sToMml.py's measure/line-break
heuristic (see tempoInfer.py). Everything here defaults to empty --
populate an entry only once you've actually confirmed (by listening, or
from check_alignment.py's report) that a specific song needs it. Neither
override changes a single byte of the converted output; both only affect
where line breaks land in the generated .mml.
"""

# Song name (the same one used for its .mml filename) -> which
# audio/<dir>/mus/ directory it belongs in. Needed because a raw ROM dump
# (see dumpMusicMml.py) has no notion of "shared between both games" on
# its own -- only committed-file history does. 'gamespecific' means write
# it under whichever game is currently being dumped (audio/ages/mus/ or
# audio/seasons/mus/) rather than a fixed directory -- pirates.mml is the
# one song with genuinely different data per game (see sToMml.py's
# split_pirates docstring from when it was bootstrapped from committed
# .s history); dumping straight from each game's own ROM produces the
# right per-game content automatically, with no splitting logic needed at
# all this time.
SONG_MANIFEST = {
    'ambiPalace': 'ages', 'ancientTomb': 'ages', 'blackTower': 'ages', 'crescent': 'ages',
    'crownDungeon': 'ages', 'fairyForest': 'ages', 'jabuJabusBelly': 'ages', 'lynnaCity': 'ages',
    'lynnaVillage': 'ages', 'makuPath': 'ages', 'mermaidsCave': 'ages', 'moonlitGrotto': 'ages',
    'nayru': 'ages', 'overworldPast': 'ages', 'ralph': 'ages', 'skullDungeon': 'ages',
    'spiritsGrave': 'ages', 'symmetryPast': 'ages', 'symmetryPresent': 'ages', 'tokayHouse': 'ages',
    'underwater': 'ages', 'wingDungeon': 'ages', 'zoraVillage': 'ages',

    'ancientRuins': 'seasons', 'carnival': 'seasons', 'dancingDragonDungeon': 'seasons',
    'explorersCrypt': 'seasons', 'gnarledRootDungeon': 'seasons', 'herosCave': 'seasons',
    'hideAndSeek': 'seasons', 'horonVillage': 'seasons',
    'poisonMothsLair': 'seasons', 'samasaDesert': 'seasons', 'snakesRemains': 'seasons',
    'songOfStorms': 'seasons', 'subrosia': 'seasons', 'subrosianDance': 'seasons',
    'subrosianShop': 'seasons', 'sunkenCity': 'seasons', 'swordAndShieldMaze': 'seasons',
    'tarmRuins': 'seasons', 'templeRemains': 'seasons', 'unicornsCave': 'seasons',
    'unused1': 'seasons', 'unused2': 'seasons',

    # Both games happen to have their own, genuinely different "Maku Tree"
    # theme under the exact same label name (audio/ages/soundPointers.s
    # and audio/seasons/soundPointers.s both define musMakuTree
    # independently) -- same situation as pirates above, not a typo.
    'makuTree': 'gamespecific',

    'blackTowerEntrance': 'common', 'boss': 'common', 'cave': 'common', 'crazyDance': 'common',
    'credits1': 'common', 'credits2': 'common', 'disaster': 'common', 'essence': 'common',
    'essenceRoom': 'common', 'fairyFountain': 'common', 'fileSelect': 'common',
    'finalBoss': 'common', 'finalDungeon': 'common', 'gameover': 'common', 'ganon': 'common',
    'getEssence': 'common', 'goronCave': 'common', 'greatMoblin': 'common', 'indoors': 'common',
    'intro1': 'common', 'intro2': 'common', 'ladxSideview': 'common', 'mapleGame': 'common',
    'mapleTheme': 'common', 'miniboss': 'common', 'minigame': 'common', 'onoxCastle': 'common',
    'overworld': 'common', 'precredits': 'common', 'roomOfRites': 'common', 'rosaDate': 'common',
    'sadness': 'common', 'syrup': 'common', 'titlescreen': 'common', 'triumphant': 'common',
    'twinrova': 'common', 'zeldaSaved': 'common',

    'pirates': 'gamespecific',
}

# file_base -> ticks per measure, for a song whose real time signature
# isn't 4/4 (192 ticks/measure, the default every song is assumed to use
# otherwise). Run tools/dump/checkAlignment.py to see which songs don't
# line up cleanly under that default assumption.
TIME_SIG_OVERRIDES = {}

# file_base -> list of channel letters ('A'/'B'/'C'/'D') that run a
# delayed-echo effect (notes shifted slightly behind another channel,
# played back at reduced volume) -- e.g. horonVillage, snakesRemains,
# rosaDate. That channel's own note grouping is intentionally offset from
# the song's real measure grid, so measure-based line breaks on it would
# be misleading rather than helpful; it's left as one unbroken line
# instead. Known cases only -- there's no way to detect this from frame
# lengths alone, so add to this by ear as you find more.
ECHO_CHANNELS = {}
