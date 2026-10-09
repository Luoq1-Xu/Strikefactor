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

from strikefactor import paths

from . import theme

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The game's own pitch database, in the player's data directory. `paths` is a
# pure module (no pygame), so reading it keeps the analysis runnable on its own.
DB_PATH = paths.db_path()
DEFAULT_OUT_DIR = os.path.join(REPO_ROOT, "analysis_output")

_cache = {}


def connect(db_path=None):
    path = db_path or DB_PATH
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Pitch database not found at {path}. Play a game first — the DB is "
            f"created on the first recorded pitch.")
    conn = sqlite3.connect(paths.sqlite_readonly_uri(path), uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def pitch_columns(conn):
    """The pitches table's columns, as this particular database has them."""
    return {row[1] for row in conn.execute("PRAGMA table_info(pitches)")}


def sac_fly_sql(columns):
    """SQL that is true on a row that was a sacrifice fly (Rule 9.08(d)).

    A sacrifice fly is a plate appearance and not an at-bat. The game's scorer
    rules on it (`strikefactor.helpers.ScoreKeeper`) and charges none, and
    both scripts here used to charge one, so AVG and SLG ran below the game's.

    The ruling is not a column, and does not need to be. Both halves of it
    are facts a row already holds:

      * a fly ball was caught and a run scored on it;
      * a fly ball was dropped for an error with a runner on third and fewer
        than two out, so he would have scored after the catch. An error on a
        FLY is always the dropped catch (`HitAnimation._charge_error`), which
        is what lets `batted_ball_type` stand in for the out it cost.

    `columns` is the table's own (`pitch_columns`), because the connection is
    read-only and an archive is never migrated: `runs_scored_on_pitch` arrived
    in v2 and `batted_ball_type` in v7. A half that cannot be asked is left
    out, and a row with NULL runs is not a sacrifice fly. Either way the row
    stays an at-bat, which is what it was counted as before.

    One statement of it for both scripts: `load_pitches` selects it as
    `is_sac_fly`, and batting_analysis.py puts it in its own queries.
    tests/test_scorekeeping.py pins it to the scorer play by play.
    """
    clauses = []
    if "runs_scored_on_pitch" in columns:
        clauses.append("(outcome = 'FLYOUT' AND runs_scored_on_pitch > 0)")
    if {"batted_ball_type", "runner_3b", "outs_before"} <= set(columns):
        reach = ", ".join(f"'{o}'" for o in theme.REACH_OUTCOMES)
        clauses.append(f"(outcome IN ({reach}) AND batted_ball_type = 'FLY' "
                       f"AND runner_3b = 1 AND outs_before < 2)")
    return f"({' OR '.join(clauses)})" if clauses else "0"


def load_pitches(db_path=None):
    """Full pitches table as a DataFrame with derived analysis columns."""
    key = ("pitches", db_path or DB_PATH)
    if key in _cache:
        return _cache[key]

    with connect(db_path) as conn:
        df = pd.read_sql_query(
            f"SELECT *, {sac_fly_sql(pitch_columns(conn))} AS is_sac_fly "
            f"FROM pitches", conn)

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

    # earned_runs_on_pitch arrived in schema v12, and an unmigrated archive
    # lacks it for the same reason. NA, never a copy of runs_scored_on_pitch:
    # which of an older row's runs were earned is not known, and the pitching
    # line says so (`er_exact`) rather than have it decided here.
    if "earned_runs_on_pitch" not in df.columns:
        df["earned_runs_on_pitch"] = pd.NA

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
    # Selected by `load_pitches` (see `sac_fly_sql`). NULL where the row
    # cannot say, which is not a sacrifice fly.
    df["is_sac_fly"] = df["is_sac_fly"].fillna(0).astype(bool)
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
