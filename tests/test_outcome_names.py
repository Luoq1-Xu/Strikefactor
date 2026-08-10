"""Guards for the recorded-outcome vocabulary.

Outcomes are stored as free text and matched by exact string in a dozen places
(scoring, GameDay out-counting, the analysis groups), so a spelling drifting
apart from the rest is a silent miscount rather than a crash. Pop-ups were
recorded as ``POP_UP`` until schema v5 renamed them to ``POP UP``, in line with
``HOME RUN``.
"""

import sqlite3

import pytest

from analysis import theme
from strikefactor.data.pitch_database import SCHEMA_VERSION, V5_OUTCOME_RENAMES, PitchDB


def test_recorded_outcomes_use_spaces_not_underscores():
    """No recorded outcome name may carry an underscore."""
    for group in (
        theme.HIT_OUTCOMES,
        theme.BATTED_OUT_OUTCOMES,
        theme.IN_PLAY_OUTCOMES,
        theme.OUT_OUTCOMES,
        theme.TERMINAL_OUTCOMES,
    ):
        offenders = [o for o in group if "_" in o]
        assert not offenders, f"underscored outcome names: {offenders}"


def test_pop_up_is_present_in_every_outcome_group():
    """The rename must not drop it out of the denominators it belongs in."""
    assert "POP UP" in theme.BATTED_OUT_OUTCOMES
    assert "POP UP" in theme.IN_PLAY_OUTCOMES
    assert "POP UP" in theme.OUT_OUTCOMES
    assert "POP UP" in theme.TERMINAL_OUTCOMES
    assert "POP UP" in theme.OUTCOME_ORDER
    assert "POP UP" in theme.OUTCOME_COLORS
    assert "POP UP" in theme.OUTCOME_ABBREV
    assert "POP UP" in theme.EVENT_RUN_VALUE


@pytest.mark.parametrize("outcome", ["POP UP", "HOME RUN"])
def test_terminal_outcomes_still_match_after_normalization(outcome):
    """PitchDataExtractor normalizes spaces to underscores before matching."""
    from strikefactor.data.pitch_database import PitchDataExtractor

    assert outcome.upper().replace(" ", "_") in PitchDataExtractor.TERMINAL_OUTCOMES


def test_migration_rewrites_legacy_pop_up(tmp_path):
    """A pre-v5 database has its old spelling rewritten on open, once."""
    db_path = str(tmp_path / "legacy.db")

    # Build a v4-shaped database carrying the old spelling.
    pitch_cols = "session_id, created_at, pitcher_name, pitch_type, outcome"
    seed = PitchDB(db_path)
    for outcome in ("POP_UP", "HOME RUN"):
        seed.conn.execute(
            f"INSERT INTO pitches ({pitch_cols}) VALUES ('s', 't', 'sale', 'FF', ?)",
            (outcome,),
        )
    seed.conn.execute(
        "INSERT INTO at_bats (session_id, created_at, final_outcome) "
        "VALUES ('s', 't', 'POP_UP')"
    )
    seed.conn.execute("PRAGMA user_version = 4")
    seed.conn.commit()
    seed.close()

    db = PitchDB(db_path)
    try:
        assert db.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        counts = dict(
            db.conn.execute("SELECT outcome, COUNT(*) FROM pitches GROUP BY 1")
        )
        assert counts == {"POP UP": 1, "HOME RUN": 1}
        assert db.conn.execute(
            "SELECT final_outcome FROM at_bats"
        ).fetchone()[0] == "POP UP"
    finally:
        db.close()

    # Idempotent: re-opening an already-migrated db changes nothing.
    again = PitchDB(db_path)
    try:
        assert again.conn.execute(
            "SELECT COUNT(*) FROM pitches WHERE outcome = 'POP UP'"
        ).fetchone()[0] == 1
    finally:
        again.close()


def test_rename_table_maps_old_to_new():
    assert dict(V5_OUTCOME_RENAMES) == {"POP_UP": "POP UP"}


def test_gameday_history_normalizes_legacy_play_results():
    """Restored archives still carry POP_UP; the loader maps them on read."""
    from strikefactor.gameplay.gameday_manager import GameDayManager

    games = [
        {"result": "WIN", "play_log": [
            {"result": "POP_UP"}, {"result": "FLYOUT"}, {"result": "HOME RUN"},
        ]},
        {"result": "LOSS", "play_log": "not-a-list"},   # must not raise
        {"no_play_log": True},
    ]
    GameDayManager._normalize_legacy_outcomes(games)

    assert [p["result"] for p in games[0]["play_log"]] == [
        "POP UP", "FLYOUT", "HOME RUN",
    ]
    # Game-level result ('WIN'/'LOSS') is a different field and untouched.
    assert games[0]["result"] == "WIN"


def test_live_database_has_no_legacy_spelling():
    """The user's real db was migrated; catch a regression that reintroduces it."""
    from strikefactor.config import get_path

    conn = sqlite3.connect(get_path("data/strikefactor.db"))
    try:
        for table, col in (("pitches", "outcome"), ("at_bats", "final_outcome")):
            stale = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {col} = 'POP_UP'"
            ).fetchone()[0]
            assert stale == 0, f"{table}.{col} still has {stale} POP_UP rows"
    finally:
        conn.close()
