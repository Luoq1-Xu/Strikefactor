"""Shared palettes, labels, and matplotlib styling for the analysis scripts.

Everything visual that both the PNG renderer and the terminal renderer need to
agree on lives here. No queries, no plotting — just constants.
"""

# ── Pitch types ──────────────────────────────────────────────────────────
# Keys are the pitch_type values written by PitchDataExtractor. FO (forkball,
# Sasaki) and SLD (sweeper) used to be missing here and rendered as unlabelled
# gray bars; the AI treats both as real arsenal entries (see ai/AI_2.py).
PITCH_COLORS = {
    "FF": "#e74c3c",  # Four-seam fastball
    "SI": "#e67e22",  # Sinker
    "FC": "#1abc9c",  # Cutter
    "SL": "#3498db",  # Slider
    "SLD": "#5dade2",  # Sweeper
    "CB": "#2ecc71",  # Curveball
    "CH": "#9b59b6",  # Changeup
    "FS": "#f39c12",  # Splitter
    "FO": "#e84393",  # Forkball
}

PITCH_NAMES = {
    "FF": "Four-Seam",
    "SI": "Sinker",
    "FC": "Cutter",
    "SL": "Slider",
    "SLD": "Sweeper",
    "CB": "Curveball",
    "CH": "Changeup",
    "FS": "Splitter",
    "FO": "Forkball",
}

UNKNOWN_COLOR = "#8899aa"


def pitch_color(pt):
    return PITCH_COLORS.get(pt, UNKNOWN_COLOR)


def pitch_name(pt):
    return PITCH_NAMES.get(pt, pt or "?")


# ── Pitchers ─────────────────────────────────────────────────────────────
PITCHER_DISPLAY = {
    "chrissale": "Chris Sale",
    "jacobdegrom": "Jacob deGrom",
    "rokisasaki": "Roki Sasaki",
    "Yamamoto": "Yoshinobu Yamamoto",
    "shanemcclanahan": "Shane McClanahan",
}

# pitches.pitcher_hand is only populated on recent rows (~11% of the table),
# but handedness is a static property of the pitcher. Mirrors
# PITCHER_HANDEDNESS in strikefactor/data/pitch_database.py, keyed by the name
# actually stored in the DB so historical rows can be backfilled.
PITCHER_HAND = {
    "chrissale": "L",
    "shanemcclanahan": "L",
    "jacobdegrom": "R",
    "Yamamoto": "R",
    "rokisasaki": "R",
}


def pitcher_display(name):
    return PITCHER_DISPLAY.get(name, name)


def pitcher_short(name):
    """Last name only — for tick labels and terminal tables."""
    return pitcher_display(name).split()[-1]


# ── Strike zone (matches gameplay; see strikefactor/config.py) ───────────
SZ_X_HALF = 0.83   # ft, half-width of the plate
SZ_Z_MIN = 1.5     # ft, bottom of the zone
SZ_Z_MAX = 3.5     # ft, top of the zone

# Commit point: where a hitter must decide. ~167ms before the ball reaches the
# plate at typical velocity, which lands at roughly 23.8 ft of remaining
# travel. Trajectory samples straddle it (sample_idx 10 ≈ 24.7ft, 11 ≈ 21.9ft),
# so the tunneling figure interpolates.
COMMIT_POINT_FT = 23.8


# ── Outcome groups ───────────────────────────────────────────────────────
HIT_OUTCOMES = ("SINGLE", "DOUBLE", "TRIPLE", "HOME RUN")
# "POP UP" is a real terminal outcome (verified against at_bats.final_outcome)
# and was previously missing from every one of these groups, silently dropping
# at-bats from PA/BF/IP/K% denominators.
BATTED_OUT_OUTCOMES = ("GROUNDOUT", "FLYOUT", "LINEOUT", "POP UP")
IN_PLAY_OUTCOMES = HIT_OUTCOMES + BATTED_OUT_OUTCOMES
OUT_OUTCOMES = ("strikeout",) + BATTED_OUT_OUTCOMES
TERMINAL_OUTCOMES = ("strikeout", "walk") + IN_PLAY_OUTCOMES

# A swing that produced no contact. Fouls carry outcome='foul' and contact
# carries an in-play outcome, so this test is exact — see the design doc.
WHIFF_OUTCOMES = ("strike", "strikeout")

OUTCOME_COLORS = {
    "strikeout": "#e74c3c",
    "GROUNDOUT": "#95a5a6",
    "FLYOUT": "#7f8c8d",
    "LINEOUT": "#bdc3c7",
    "POP UP": "#636e72",
    "SINGLE": "#2ecc71",
    "DOUBLE": "#27ae60",
    "TRIPLE": "#1abc9c",
    "HOME RUN": "#f1c40f",
    "walk": "#3498db",
}

OUTCOME_ORDER = [
    "strikeout", "GROUNDOUT", "FLYOUT", "LINEOUT", "POP UP",
    "SINGLE", "DOUBLE", "TRIPLE", "HOME RUN", "walk",
]

# Short forms for narrow tables — the full names blow past any terminal width.
OUTCOME_ABBREV = {
    "strikeout": "K", "GROUNDOUT": "GO", "FLYOUT": "FO", "LINEOUT": "LO",
    "POP UP": "PU", "SINGLE": "1B", "DOUBLE": "2B", "TRIPLE": "3B",
    "HOME RUN": "HR", "walk": "BB",
}


# ── Linear weights (runs above average per PA) ───────────────────────────
# Standard modern-era values. Used to seed the empirical count-value model in
# metrics.run_value_model(); outs are split because a strikeout costs slightly
# more than a ball in play.
EVENT_RUN_VALUE = {
    "walk": 0.29,
    "SINGLE": 0.44,
    "DOUBLE": 0.74,
    "TRIPLE": 1.01,
    "HOME RUN": 1.39,
    "strikeout": -0.27,
    "GROUNDOUT": -0.26,
    "FLYOUT": -0.26,
    "LINEOUT": -0.26,
    "POP UP": -0.26,
}


# ── MLB benchmarks (poor, average, elite) ────────────────────────────────
# Used by the scouting card. The card also computes a within-dataset
# percentile, because this game's rates sit far outside MLB ranges (K% ≈ 48%)
# and fixed thresholds saturate to solid green otherwise.
SCOUTING_BENCH = {
    "CSW%":     (26.0, 30.0, 34.0),
    "Whiff%":   (18.0, 24.0, 32.0),
    "Chase%":   (25.0, 31.0, 36.0),
    "PutAway%": (17.0, 21.0, 25.0),
    "xBA":      (0.270, 0.245, 0.220),   # lower is better
}

MLB_REFERENCE = {"k_pct": 22.0, "bb_pct": 8.0}

# The league spray split, quoted against the conventional +/-15 degree cut
# (`metrics.SPRAY_THIRD_DEG`). Here rather than in `metrics` because this is a
# benchmark rather than a statistic, and both renderers already import theme.
SPRAY_MLB_SPLIT = {"Pull": 40.0, "Centre": 35.0, "Oppo": 25.0}


# ── Colors ───────────────────────────────────────────────────────────────
BG = "#1a1a2e"
PANEL = "#16213e"
GRID = "#2a2a4a"
FG = "#e0e0e0"
MUTED = "#9aa5b1"
HEADER_BG = "#1f4068"

GOOD_RGB = (39, 174, 96)
NEUTRAL_RGB = (236, 219, 143)
BAD_RGB = (192, 57, 43)
VOLUME_LO_RGB = (45, 55, 72)
VOLUME_HI_RGB = (49, 130, 206)

# Sequential ramp for heatmaps that read "more = hotter".
HEAT_CMAP = "magma"
# Diverging ramp for run value / whiff-vs-baseline, centred on zero. Oriented
# so green is always pitcher-favourable; panels reporting batter-POV numbers
# use DIVERGING_CMAP_R so the colour still means the same thing.
DIVERGING_CMAP = "RdYlGn"
DIVERGING_CMAP_R = "RdYlGn_r"

PITCHER_PALETTE = ["#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6",
                   "#1abc9c", "#e84393"]


def blend(c1, c2, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def to_hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def text_color_for(bg_hex):
    """Black or white text, whichever contrasts better with the fill."""
    r, g, b = (int(bg_hex[i:i + 2], 16) for i in (1, 3, 5))
    return "#1a1a2e" if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "#ffffff"


MPL_RCPARAMS = {
    "figure.facecolor": BG,
    "axes.facecolor": PANEL,
    "axes.edgecolor": FG,
    "axes.labelcolor": FG,
    "text.color": FG,
    "xtick.color": FG,
    "ytick.color": FG,
    "grid.color": GRID,
    "grid.alpha": 0.5,
    "font.family": "monospace",
    "font.size": 11,
    "savefig.facecolor": BG,
}


def apply_mpl_style():
    import matplotlib.pyplot as plt
    plt.rcParams.update(MPL_RCPARAMS)
