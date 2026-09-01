"""Loading layer: SQLite → pandas, plus the derived columns every metric needs.

One query per table, once per process. The old scripts issued a query per
(pitcher × pitch type × metric) inside each figure; deriving the flags here
instead means a metric function is a groupby, and the same frame feeds both the
PNG and the terminal renderer.
"""

import os
import sqlite3

import numpy as np
import pandas as pd

from . import theme

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(REPO_ROOT, "strikefactor", "data", "strikefactor.db")
DEFAULT_OUT_DIR = os.path.join(REPO_ROOT, "analysis_output")

_cache = {}


def connect(db_path=None):
    path = db_path or DB_PATH
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Pitch database not found at {path}. Play a game first — the DB is "
            f"created on the first recorded pitch.")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def load_pitches(db_path=None):
    """Full pitches table as a DataFrame with derived analysis columns."""
    key = ("pitches", db_path or DB_PATH)
    if key in _cache:
        return _cache[key]

    with connect(db_path) as conn:
        df = pd.read_sql_query("SELECT * FROM pitches", conn)

    if df.empty:
        _cache[key] = df
        return df

    df = _derive(df)
    _cache[key] = df
    return df


def load_trajectories(pitch_ids=None, db_path=None):
    """Trajectory samples, optionally restricted to a set of pitch_ids."""
    with connect(db_path) as conn:
        if pitch_ids is None:
            return pd.read_sql_query(
                "SELECT * FROM pitch_trajectories ORDER BY pitch_id, sample_idx", conn)
        ids = list(pitch_ids)
        if not ids:
            return pd.DataFrame(
                columns=["pitch_id", "sample_idx", "t_sec", "x_ft", "y_ft", "z_ft"])
        out = []
        # SQLite caps variables per statement; chunk to stay well under it.
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            q = (f"SELECT * FROM pitch_trajectories WHERE pitch_id IN "
                 f"({','.join('?' * len(chunk))}) ORDER BY pitch_id, sample_idx")
            out.append(pd.read_sql_query(q, conn, params=chunk))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def load_games(db_path=None):
    key = ("games", db_path or DB_PATH)
    if key in _cache:
        return _cache[key]
    with connect(db_path) as conn:
        df = pd.read_sql_query("SELECT * FROM games", conn)
    _cache[key] = df
    return df


# ── Derived columns ──────────────────────────────────────────────────────
def _derive(df):
    df = df.copy()

    # pitcher_hand is only populated on recent rows but is a static property of
    # the pitcher, so backfill it and unlock platoon splits across all history.
    mapped = df["pitcher_name"].map(theme.PITCHER_HAND)
    if "pitcher_hand" in df.columns:
        df["pitcher_hand"] = df["pitcher_hand"].where(
            df["pitcher_hand"].notna() & (df["pitcher_hand"] != ""), mapped)
    else:
        df["pitcher_hand"] = mapped

    # defense_strength arrived in schema v10. The analysis connection is
    # read-only, so a database opened here is never migrated — an archive
    # snapshot under data/archives/ genuinely lacks the column. Materialise it
    # as all-NA rather than letting --defense raise KeyError on old data.
    #
    # NA, never "league": a pre-v10 row is not a league-defense row, it is a
    # row from before the setting existed, and filtering on a level must
    # exclude it rather than silently claim it.
    if "defense_strength" not in df.columns:
        df["defense_strength"] = pd.NA

    outcome = df["outcome"]
    swing = df["swing_type"].fillna(0)

    df["is_swing"] = swing > 0
    df["is_power_swing"] = swing == 2
    df["is_take"] = swing == 0
    df["is_foul"] = outcome == "foul"

    # A swing with no contact. Fouls have outcome='foul' and contact has an
    # in-play outcome, so a swing landing on strike/strikeout is exactly a
    # swing-and-miss. The previous `on_time == 0` test only caught mistimed
    # swings and missed the ~3.6k that were timed but off-location.
    df["is_whiff"] = df["is_swing"] & outcome.isin(theme.WHIFF_OUTCOMES)
    df["is_called_strike"] = df["is_take"] & outcome.isin(theme.WHIFF_OUTCOMES)
    df["is_contact"] = df["is_swing"] & ~df["is_whiff"]

    df["in_zone"] = (
        df["plate_x_ft"].abs().le(theme.SZ_X_HALF)
        & df["plate_z_ft"].between(theme.SZ_Z_MIN, theme.SZ_Z_MAX)
    )
    df["is_chase"] = df["is_swing"] & ~df["in_zone"]

    df["is_terminal"] = outcome.isin(theme.TERMINAL_OUTCOMES)
    df["is_in_play"] = outcome.isin(theme.IN_PLAY_OUTCOMES)
    df["is_hit_outcome"] = outcome.isin(theme.HIT_OUTCOMES)
    df["is_out"] = outcome.isin(theme.OUT_OUTCOMES)

    balls = df["balls_before"].fillna(0).astype(int).clip(0, 3)
    strikes = df["strikes_before"].fillna(0).astype(int).clip(0, 2)
    df["balls_before"] = balls
    df["strikes_before"] = strikes
    df["count_str"] = balls.astype(str) + "-" + strikes.astype(str)
    df["count_state"] = np.select(
        [
            strikes == 2,
            (balls == 0) & (strikes == 0),
            strikes > balls,
            balls > strikes,
        ],
        ["two_strike", "first_pitch", "ahead", "behind"],
        default="even",
    )
    df["is_first_pitch"] = (balls == 0) & (strikes == 0)

    hand = df["batter_hand"].fillna("?")
    df["platoon"] = df["pitcher_hand"].fillna("?") + "HP vs " + hand + "HB"

    # Horizontal location from the batter's point of view: positive = inside.
    # Without this, L and R batters smear together in every location plot.
    df["plate_x_batter"] = np.where(hand == "L", -df["plate_x_ft"], df["plate_x_ft"])

    df["date"] = pd.to_datetime(df["created_at"], errors="coerce")
    df["day"] = df["date"].dt.floor("D")

    return df


class Context:
    """Everything a figure or terminal panel needs, assembled once by the CLI.

    Replaces the module-level FILTER / OUT_DIR / conn globals the old scripts
    mutated from `__main__`.
    """

    def __init__(self, filt, out_dir=None, db_path=None):
        self.filter = filt
        self.db_path = db_path or DB_PATH
        self.all_pitches = load_pitches(self.db_path)
        self.pitches = filt.apply(self.all_pitches)
        base = out_dir or DEFAULT_OUT_DIR
        # One subfolder per slice so runs with different filters don't clobber
        # each other's PNGs.
        self.out_dir = os.path.join(base, filt.slug)
        self._games = None
        self._run_value = None

    @property
    def label(self):
        return self.filter.label

    @property
    def empty(self):
        return self.pitches.empty

    @property
    def games(self):
        if self._games is None:
            self._games = load_games(self.db_path)
        return self._games

    @property
    def pitchers(self):
        """Pitcher names present in the slice, most-thrown first."""
        if self.empty:
            return []
        return list(self.pitches["pitcher_name"].value_counts().index)

    @property
    def pitch_types(self):
        if self.empty:
            return []
        return list(self.pitches["pitch_type"].value_counts().index)

    @property
    def date_span(self):
        if self.empty or self.pitches["date"].isna().all():
            return None
        d = self.pitches["date"].dropna()
        return d.min(), d.max()

    def ensure_out_dir(self):
        os.makedirs(self.out_dir, exist_ok=True)
        return self.out_dir

    def for_pitcher(self, name):
        return self.pitches[self.pitches["pitcher_name"] == name]

    @property
    def run_value(self):
        """Lazily-built empirical count-value model for the active slice."""
        if self._run_value is None:
            from . import metrics
            self._run_value = metrics.run_value_model(self.pitches)
        return self._run_value
