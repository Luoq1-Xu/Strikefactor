"""The batted-ball columns (schema v7), and what makes them falsifiable.

Before v7 the database could not tell a ground ball from a fly ball. Every
aggregate that wanted "GB BABIP" or "how often is a fielded grounder beaten
out" had to infer the type from `outcome`, which is circular — the outcome
is what the fielding model produced, so checking the model against it only
ever confirmed the model.
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from strikefactor.data.pitch_database import SCHEMA_VERSION, PitchDB

NEW_COLUMNS = ("batted_ball_type", "fielder_role", "play_margin_s")


@pytest.fixture
def db_path():
    with tempfile.TemporaryDirectory() as d:
        yield str(Path(d) / "test.db")


def test_a_fresh_database_has_the_batted_ball_columns(db_path):
    db = PitchDB(db_path)
    try:
        cols = {r[1] for r in db.conn.execute("PRAGMA table_info(pitches)")}
        assert set(NEW_COLUMNS) <= cols
        assert db.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    finally:
        db.close()


def test_migrating_an_older_database_keeps_its_rows(db_path):
    """The recipe in CLAUDE.md, exercised: an ALTER TABLE migration must
    add the columns without touching what is already recorded."""
    conn = sqlite3.connect(db_path)
    conn.executescript(PitchDB.SCHEMA)
    for col in NEW_COLUMNS:
        conn.execute(f"ALTER TABLE pitches DROP COLUMN {col}")
    conn.execute(
        "INSERT INTO pitches (pitch_id, session_id, game_mode, difficulty, "
        "created_at, pitcher_name, pitch_type, outcome) VALUES (?,?,?,?,?,?,?,?)",
        ("p1", "s1", "arcade", "ROOKIE", "2026-01-01T00:00:00", "Sale",
         "FASTBALL", "SINGLE"))
    conn.execute("PRAGMA user_version = 6")
    conn.commit()
    conn.close()

    db = PitchDB(db_path)
    try:
        cols = {r[1] for r in db.conn.execute("PRAGMA table_info(pitches)")}
        assert set(NEW_COLUMNS) <= cols
        assert db.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        row = db.conn.execute(
            "SELECT outcome, batted_ball_type FROM pitches WHERE pitch_id='p1'"
        ).fetchone()
        assert row[0] == "SINGLE"
        assert row[1] is None, "pre-v7 rows must not be guessed at"
    finally:
        db.close()


def test_the_new_columns_round_trip(db_path):
    db = PitchDB(db_path)
    try:
        db.insert_pitch({
            "pitch_id": "p2", "session_id": "s1", "game_mode": "arcade",
            "difficulty": "ROOKIE", "created_at": "2026-01-01T00:00:00",
            "pitcher_name": "Sale", "pitch_type": "FASTBALL",
            "outcome": "GROUNDOUT",
            "batted_ball_type": "GROUNDER", "fielder_role": "SS",
            "play_margin_s": 0.42,
        }, [])
        row = db.conn.execute(
            "SELECT batted_ball_type, fielder_role, play_margin_s "
            "FROM pitches WHERE pitch_id='p2'").fetchone()
        assert tuple(row) == ("GROUNDER", "SS", 0.42)
    finally:
        db.close()


# ---- What the columns have to mean ----------------------------------------

class _StubBatter:
    def get_handedness(self):
        return "R"


class _StubSettings:
    def get_difficulty_multipliers(self):
        return {"out_probability_modifier": 1.0}


class _StubGame:
    def __init__(self):
        self.batter = _StubBatter()
        self.settings_manager = _StubSettings()


def _play(shape, quality=0.8):
    from strikefactor.gameplay.hit_animation import HitAnimation

    anim = HitAnimation(_StubGame(), outcome="IN_PLAY", on_complete=lambda: None,
                        quality=quality, batted_ball_type=shape)
    t = 0
    while not anim.finished and t < 25000:
        t += 16
        anim.update(t)
    return anim


def test_fielder_role_is_only_set_when_somebody_fielded_it():
    """`_primary_role` is a *routing* assignment that exists from the first
    frame and changes as the play develops. Reporting it unconditionally
    would record a fielder for balls nobody fielded — exactly the rows a
    fielding aggregate must not count."""
    from strikefactor.gameplay.hit_animation import HitAnimation

    fresh = HitAnimation(_StubGame(), outcome="IN_PLAY",
                         on_complete=lambda: None, quality=0.8,
                         batted_ball_type="GROUNDER")
    assert fresh._primary_role is not None      # routing is already assigned
    assert fresh.fielder_role is None           # but nobody has the ball

    finished = _play("GROUNDER")
    assert finished.fielder_role is not None


def test_a_play_with_no_race_reports_no_margin():
    """NULL rather than 0.0. A ball nobody raced for has no margin, and
    recording a zero would put a spike at dead-even in a distribution whose
    entire purpose is its shape."""
    seen_null = seen_value = False
    for i in range(60):
        anim = _play("FLY" if i % 2 else "GROUNDER", quality=0.55 + (i % 30) / 60.0)
        timing = anim.play_timing
        margin = timing.margin_s if timing is not None else None
        if margin is None:
            seen_null = True
        else:
            seen_value = True
            assert isinstance(margin, float)
    assert seen_null, "no play reported a NULL margin"
    assert seen_value, "no play reported a margin at all"


def test_batted_ball_type_is_an_independent_axis():
    """Classified at contact, upstream of any fielding decision — which is
    what stops it being a restatement of `outcome`. A GROUNDER can be an
    out or a hit, and the type does not change either way."""
    outcomes = {_play("GROUNDER", quality=0.5 + i / 40.0).classified_outcome
                for i in range(30)}
    assert len(outcomes) > 1, "every grounder resolved the same way"


# ---- v10: which defense the ball was hit into -----------------------------

V10_COLUMNS = ("defense_strength",)


def test_a_fresh_database_records_the_defense(db_path):
    db = PitchDB(db_path)
    try:
        for table in ("pitches", "games"):
            cols = {r[1] for r in db.conn.execute(f"PRAGMA table_info({table})")}
            assert set(V10_COLUMNS) <= cols, table
        assert db.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    finally:
        db.close()


def test_migrating_a_v9_database_adds_the_defense_column_to_both_tables(db_path):
    """`games` had no migration loop at all before v10 — only `pitches` and
    `at_bats` did — so this is the first thing that would have silently
    skipped it."""
    conn = sqlite3.connect(db_path)
    conn.executescript(PitchDB.SCHEMA)
    conn.execute("ALTER TABLE pitches DROP COLUMN defense_strength")
    conn.execute("ALTER TABLE games DROP COLUMN defense_strength")
    conn.execute(
        "INSERT INTO pitches (pitch_id, session_id, game_mode, difficulty, "
        "created_at, pitcher_name, pitch_type, outcome) VALUES (?,?,?,?,?,?,?,?)",
        ("p1", "s1", "arcade", "amateur", "2026-01-01T00:00:00", "Sale",
         "FASTBALL", "SINGLE"))
    conn.execute(
        "INSERT INTO games (game_id, session_id, game_mode, difficulty, "
        "started_at) VALUES (?,?,?,?,?)",
        ("g1", "s1", "arcade", "amateur", "2026-01-01T00:00:00"))
    conn.execute("PRAGMA user_version = 9")
    conn.commit()
    conn.close()

    db = PitchDB(db_path)
    try:
        for table in ("pitches", "games"):
            cols = {r[1] for r in db.conn.execute(f"PRAGMA table_info({table})")}
            assert set(V10_COLUMNS) <= cols, table
        assert db.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert db.conn.execute("SELECT COUNT(*) FROM pitches").fetchone()[0] == 1
        assert db.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 1
    finally:
        db.close()


def test_play_recorded_before_the_setting_existed_stays_null(db_path):
    """NULL means "not recorded", and must never be back-filled to "league".

    A pre-v10 row is not a league-defense row: errors did not exist when it was
    written, so its error rate is structurally zero. Filling it in would make
    every error aggregate quietly average those zeros in — the same shape as
    the pre-v2 `game_id IS NULL` correlation that forces the pitching line to
    compute over one slice.
    """
    conn = sqlite3.connect(db_path)
    conn.executescript(PitchDB.SCHEMA)
    conn.execute("ALTER TABLE pitches DROP COLUMN defense_strength")
    conn.execute(
        "INSERT INTO pitches (pitch_id, session_id, game_mode, difficulty, "
        "created_at, pitcher_name, pitch_type, outcome) VALUES (?,?,?,?,?,?,?,?)",
        ("old", "s1", "arcade", "amateur", "2026-01-01T00:00:00", "Sale",
         "FASTBALL", "GROUNDOUT"))
    conn.execute("PRAGMA user_version = 9")
    conn.commit()
    conn.close()

    db = PitchDB(db_path)
    try:
        value = db.conn.execute(
            "SELECT defense_strength FROM pitches WHERE pitch_id='old'"
        ).fetchone()[0]
        assert value is None
    finally:
        db.close()


def test_the_defense_column_round_trips(db_path):
    db = PitchDB(db_path)
    try:
        db.insert_pitch({
            "pitch_id": "p2", "session_id": "s1", "game_mode": "arcade",
            "difficulty": "amateur", "defense_strength": "gold_glove",
            "created_at": "2026-01-01T00:00:00", "pitcher_name": "Sale",
            "pitch_type": "FASTBALL", "outcome": "GROUNDOUT",
        }, [])
        assert db.conn.execute(
            "SELECT defense_strength FROM pitches WHERE pitch_id='p2'"
        ).fetchone()[0] == "gold_glove"
    finally:
        db.close()


def test_the_extractor_reads_the_live_defense_setting():
    """The capture seam: whatever the settings manager says is what lands in
    the column, so the recorded level and the level the ball was hit into
    cannot disagree."""
    from strikefactor.data.pitch_database import PitchDataExtractor
    from strikefactor.settings_manager import SettingsManager

    class _Game:
        settings_manager = SettingsManager()

    class _Sim:
        game = _Game()

    _Game.settings_manager.current_settings["defense_strength"] = "sandlot"
    assert PitchDataExtractor._defense_value(_Sim()) == "sandlot"


def test_an_unreadable_setting_records_null_rather_than_neutral():
    """A row that could not read the setting is unknown, not average. Writing
    "league" there would be the back-fill this column exists to avoid."""
    from strikefactor.data.pitch_database import PitchDataExtractor

    class _Sim:
        game = object()          # no settings_manager at all

    assert PitchDataExtractor._defense_value(_Sim()) is None
