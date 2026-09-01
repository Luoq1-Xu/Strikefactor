"""Construction smoke tests for the pygame-free core objects.

Deliberately shallow — these only prove the objects can be built and touched
outside a running game, which is the precondition for the real characterization
tests in Phase 1. Behaviour is asserted only where it is unambiguous.
"""

from strikefactor import config
from strikefactor.ai.batter_profile import BatterProfile
from strikefactor.data.pitch_database import SCHEMA_VERSION, PitchDB
from strikefactor.gameplay.challenge_manager import ChallengeManager
from strikefactor.gameplay.gameday_manager import GameDayManager
from strikefactor.helpers import ScoreKeeper


def test_scorekeeper_starts_empty():
    sk = ScoreKeeper()
    assert sk.get_score() == 0
    assert sk.get_bases() == ["white", "white", "white"]


def test_scorekeeper_home_run_with_empty_bases_scores_one():
    sk = ScoreKeeper()
    sk.update_hit_event("HOME RUN")
    assert sk.get_score() == 1
    assert sk.get_bases() == ["white", "white", "white"]


def test_scorekeeper_reset_clears_state():
    sk = ScoreKeeper()
    sk.update_hit_event("SINGLE")
    sk.reset()
    assert sk.get_score() == 0
    assert sk.get_bases() == ["white", "white", "white"]


def test_gameday_manager_constructs():
    gm = GameDayManager(starter_name="yamamoto")
    assert gm.current_inning == 1
    assert gm.is_top_inning is True
    assert gm.player_score == 0
    assert gm.opponent_score == 0
    assert gm.game_over is False


def test_gameday_manager_round_trips_through_dict():
    gm = GameDayManager(starter_name="sasaki")
    restored = GameDayManager.from_dict(gm.to_dict())
    assert restored.current_inning == gm.current_inning
    assert restored.player_score == gm.player_score
    assert restored.opponent_score == gm.opponent_score
    assert restored.session_uuid == gm.session_uuid


def test_challenge_manager_defaults_and_unlimited():
    cm = ChallengeManager()
    cm.reset_all()
    cm.set_unlimited(True)
    cm.set_unlimited(False)


def test_batter_profile_constructs():
    BatterProfile()


def test_pitch_db_creates_schema_in_temp_dir(tmp_path):
    """A fresh DB builds its schema and reports the current version."""
    db = PitchDB(str(tmp_path / "test.db"))
    assert db.conn is not None

    import sqlite3

    with sqlite3.connect(str(tmp_path / "test.db")) as check:
        tables = {
            row[0]
            for row in check.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    for expected in ["pitches", "pitch_trajectories", "at_bats", "games"]:
        assert expected in tables, f"missing table {expected}; got {sorted(tables)}"

    # The half the docstring promised and the test never checked. A fresh
    # database must be stamped at the *current* version, or the next launch
    # re-runs every migration over a schema that already has them — the
    # `user_version` preservation `reset_tracking` is careful about, asserted
    # at the point the file is created.
    with sqlite3.connect(str(tmp_path / "test.db")) as check:
        version = check.execute("PRAGMA user_version").fetchone()[0]
    assert version == SCHEMA_VERSION, f"fresh DB stamped v{version}"


def test_roster_constant_matches_pitcher_modules():
    """config.ALL_PITCHERS is meant to be the single source of truth."""
    from strikefactor.data.pitch_database import PITCHER_HANDEDNESS

    assert set(config.ALL_PITCHERS) == set(PITCHER_HANDEDNESS)


def test_strikezone_constants_are_consistent():
    left, top, width, height = config.STRIKEZONE_RECT
    assert left == config.ZONE_LEFT
    assert top == config.ZONE_TOP
    assert left + width == config.ZONE_RIGHT
    assert top + height == config.ZONE_BOTTOM
    assert config.ZONE_CENTER_X == left + width / 2
    assert config.ZONE_CENTER_Y == top + height / 2
