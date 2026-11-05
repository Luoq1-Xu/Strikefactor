"""The vocabulary of what can happen to a plate appearance.

One definition, because there were four, and they did not agree about
spelling. Adding `REACHED ON ERROR` meant editing every one of them, and the
three failure modes were all *silent*:

  * `PitchDataExtractor.TERMINAL_OUTCOMES` is a closed set — an outcome
    missing from it never closes the at-bat.
  * `_finalize_batted_ball`'s binary `is_out` credited an unknown outcome as
    a hit and fed the batting heatmap.
  * `GameDayTransitionState._player_batting_stats` counts `ab` only inside
    its result lists, so the plate appearance vanished from the AVG
    denominator.

Worse than the count of sites was that they used three different
normalizations of the same words — spaced (`POP UP`), underscored (`POP_UP`,
which the DB compares against) and mixed-case (`'strikeout'` beside
`'SINGLE'`) — so "is this outcome in that set" had a different answer
depending on which set was asked. `db_key` is where the underscored form is
produced, once, instead of at each comparison.

Top-level beside `config.py` rather than in `gameplay/`: this is shared
vocabulary, read by `helpers`, `data/pitch_database`, `gameplay/*` and the
GameDay UI. It imports nothing, so no module that needs it can be made
cyclic by taking it.

`analysis/theme.py` deliberately keeps its own copy. It is a separate,
offline process that must be able to read an archived database without the
game installed, and it already composes its groups rather than enumerating
them. `tests/test_outcome_names.py` pins the two together instead.
"""

# ---- The words --------------------------------------------------------------

SINGLE = "SINGLE"
DOUBLE = "DOUBLE"
TRIPLE = "TRIPLE"
HOME_RUN = "HOME RUN"

GROUNDOUT = "GROUNDOUT"
FLYOUT = "FLYOUT"
LINEOUT = "LINEOUT"
POP_UP = "POP UP"

# Neither a hit nor an out, which is the whole difficulty of it: it belongs in
# every PA/AB/BIP denominator and in none of the numerators. That falls out of
# the grouping below rather than needing a special case anywhere.
REACHED_ON_ERROR = "REACHED ON ERROR"
FIELDERS_CHOICE = "FIELDER'S CHOICE"

STRIKEOUT = "strikeout"
WALK = "walk"


# ---- The groups -------------------------------------------------------------
#
# Composed, never enumerated twice. A new outcome joins the one group it
# belongs to and every derived set follows.

HIT_OUTCOMES = (SINGLE, DOUBLE, TRIPLE, HOME_RUN)
BATTED_OUT_OUTCOMES = (GROUNDOUT, FLYOUT, LINEOUT, POP_UP)
ERROR_OUTCOMES = (REACHED_ON_ERROR,)
REACH_OUTCOMES = ERROR_OUTCOMES + (FIELDERS_CHOICE,)

IN_PLAY_OUTCOMES = HIT_OUTCOMES + BATTED_OUT_OUTCOMES + REACH_OUTCOMES
OUT_OUTCOMES = (STRIKEOUT,) + BATTED_OUT_OUTCOMES
TERMINAL_OUTCOMES = (STRIKEOUT, WALK) + IN_PLAY_OUTCOMES

# How many bases the batter-runner takes on a clean hit.
HIT_BASES = {SINGLE: 1, DOUBLE: 2, TRIPLE: 3, HOME_RUN: 4}


# ---- What became of a foul ---------------------------------------------------
#
# The `foul_result` column. Set on every pitch the batter fouled off, including
# the ones a fielder caught (whose `outcome` is the out, spelled as above), and
# NULL on everything else. Its own vocabulary rather than new outcomes: a foul
# that drops is still a foul and a foul that is caught is still a pop up, so
# every group above already counts both correctly.

FOUL_GROUND = "GROUND"        # a ground ball, dead where it stopped
FOUL_BACKSTOP = "BACKSTOP"    # back into the net, or over it
FOUL_STANDS = "STANDS"        # into the seats beside a line
FOUL_LANDED = "LANDED"        # came down untouched where it could be caught
FOUL_MUFFED = "MUFFED"        # a fielder got there and dropped it
FOUL_CAUGHT = "CAUGHT"        # caught: the batter is out

FOUL_RESULTS = (FOUL_GROUND, FOUL_BACKSTOP, FOUL_STANDS, FOUL_LANDED,
                FOUL_MUFFED, FOUL_CAUGHT)

# What a caught foul is called on the banner. The recorded outcome stays the
# out it was (`POP UP`, `FLYOUT`, `LINEOUT`).
FOUL_OUT_DISPLAY = "FOUL OUT"


# ---- Spelling ---------------------------------------------------------------

def db_key(outcome):
    """The underscored, upper-cased form the pitch database stores.

    `HOME RUN` -> `HOME_RUN`, `POP UP` -> `POP_UP`. The one place that
    transform lives; it used to be written out at each comparison site, which
    is how `POP_UP` and `POP UP` came to be two spellings of one outcome that
    both had to be matched.
    """
    return (outcome or "").upper().replace(" ", "_")


DB_TERMINAL_OUTCOMES = frozenset(db_key(o) for o in TERMINAL_OUTCOMES)


# ---- How it is shown --------------------------------------------------------
#
# The recorded value and the displayed word are deliberately different things.
# `REACHED ON ERROR` is matched by exact string in about a dozen places that
# fail silently on an unknown value, so the banner says ERROR by translating
# at the one seam where an outcome becomes words on a screen
# (`PitchSimulation._format_display_outcome`) rather than by renaming the
# value.

DISPLAY_NAMES = {
    REACHED_ON_ERROR: "ERROR",
}


def display_name(outcome):
    """What the player should see for this outcome."""
    return DISPLAY_NAMES.get(outcome, (outcome or "").upper())


def play_display_name(outcome, double_play=False, fielding_sequence=()):
    if not double_play:
        return display_name(outcome)
    numbers = {"P": "1", "C": "2", "1B": "3", "2B": "4", "3B": "5",
               "SS": "6", "LF": "7", "CF": "8", "RF": "9"}
    # A plain hyphen, as a scorebook writes it (6-4-3). The game's pixel font
    # has no en dash and would draw a missing-glyph box in its place.
    sequence = "-".join(numbers[role] for role in fielding_sequence)
    return "DOUBLE PLAY" + (f" · {sequence}" if sequence else "")


# ---- What colour it is ------------------------------------------------------
#
# The amber was written out as a literal in four separate files, and the
# constant that was meant to be authoritative carried a comment *listing* the
# other three copies — which is the tell that it was not.

COLORS = {
    STRIKEOUT.upper(): (227, 75, 80),      # Red
    "STRIKE": (227, 75, 80),               # Red
    "BALL": (75, 227, 148),                # Green
    WALK.upper(): (75, 227, 148),          # Green
    "FOUL": (255, 200, 100),               # Orange
    SINGLE: (71, 204, 252),                # Cyan
    DOUBLE: (71, 204, 252),                # Cyan
    TRIPLE: (71, 204, 252),                # Cyan
    HOME_RUN: (71, 204, 252),              # Cyan
    GROUNDOUT: (198, 169, 251),            # Purple
    FLYOUT: (198, 169, 251),               # Purple
    LINEOUT: (198, 169, 251),              # Purple
    POP_UP: (198, 169, 251),               # Purple
    REACHED_ON_ERROR: (214, 158, 46),      # Amber — reached, but not earned
    FIELDERS_CHOICE: (198, 169, 251),
}

# The three trail-dot colours `_finalize_batted_ball` picks between. Named
# here so the dot and the banner cannot drift: they are one fact drawn twice.
OUT_COLOR = (119, 86, 179)
HIT_COLOR = (71, 204, 252)
ERROR_COLOR = COLORS[REACHED_ON_ERROR]
