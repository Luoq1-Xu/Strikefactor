"""GameDay facts that have to be true pitch by pitch, not only at-bat by at-bat."""

import copy
from types import SimpleNamespace

import pytest

from strikefactor import outcomes
from strikefactor.gameplay.gameday_manager import GameDayManager, PitcherStats
from strikefactor.gameplay.pitch_simulation import PitchSimulation
from strikefactor.helpers import Play, ScoreKeeper

# ---- A walk-off can come on an out -----------------------------------------

def _finalize(outcome, play, *, running_result=None):
    walkoff_checks = []
    manager = SimpleNamespace(
        record_player_at_bat=lambda *a, **k: None,
        check_walkoff=lambda: walkoff_checks.append(True) or True)
    game = SimpleNamespace(
        currentouts=1, hits=0, last_pitch_information=[], ball=(640, 400),
        in_gameday_mode=True, gameday_manager=manager, scoreKeeper=ScoreKeeper(),
        inning_ended=False,
        hit_outcome_manager=SimpleNamespace(
            apply_classified_outcome=lambda *a, **k: play,
            apply_running_result=lambda *a, **k: play),
        field_renderer=SimpleNamespace(record_hit=lambda *a, **k: None,
                                       record_at_bat=lambda: None,
                                       record_sacrifice_fly=lambda: None),
        banner=SimpleNamespace(show_banner=lambda text: None),
    )
    sim = object.__new__(PitchSimulation)
    sim.game, sim.new_entry = game, {}
    sim.hit_animation = SimpleNamespace(classified_outcome=outcome,
                                        running_result=running_result)
    sim._finalize_batted_ball()
    return sim, walkoff_checks


@pytest.mark.parametrize("outcome,play", [
    (outcomes.FLYOUT, Play(runs=1, rbi=1, sacrifice_fly=True)),
    (outcomes.GROUNDOUT, Play(runs=1, rbi=1)),
])
def test_an_out_that_scores_the_winning_run_ends_the_game(outcome, play):
    """Only the live-running path used to look: an out whose runner the
    classified outcome brought home left a won game being played on."""
    sim, checks = _finalize(outcome, play)
    assert checks
    assert sim._pending_walkoff


def test_an_out_that_scores_nobody_cannot_end_it():
    _, checks = _finalize(outcomes.FLYOUT, Play())
    assert not checks


# ---- Pitches count as they are thrown --------------------------------------

def _gameday_game(manager):
    return SimpleNamespace(in_gameday_mode=True, gameday_manager=manager)


def test_each_pitch_counts_against_the_pitcher_as_it_is_thrown():
    """The count used to move only when an at-bat ended, so fatigue stood still
    through it and pitch 6 of an at-bat recorded the count before pitch 1."""
    manager = GameDayManager(starter_name="sale")
    stats = manager.get_active_pitcher_stats()
    stats.pitch_count = 89

    recorded = []
    for _ in range(3):
        sim = object.__new__(PitchSimulation)
        sim.game = _gameday_game(manager)
        sim._count_gameday_pitch()
        recorded.append(sim.pitcher_pitch_count)
    assert recorded == [89, 90, 91], "each row: the count entering that pitch"
    assert stats.pitch_count == 92

    manager.record_player_at_bat(outcomes.STRIKEOUT, runs_scored=0)
    assert stats.pitch_count == 92, "the at-bat does not count them again"


def test_a_pitch_outside_gameday_counts_against_nobody():
    sim = object.__new__(PitchSimulation)
    sim.game = SimpleNamespace(in_gameday_mode=False, gameday_manager=None)
    sim._count_gameday_pitch()
    assert sim.pitcher_pitch_count is None


def test_the_row_records_the_count_entering_the_pitch():
    from strikefactor.data.pitch_database import PitchDataExtractor

    manager = GameDayManager(starter_name="sale")
    manager.get_active_pitcher_stats().pitch_count = 40
    sim = object.__new__(PitchSimulation)
    sim.game = _gameday_game(manager)
    sim._count_gameday_pitch()
    ctx = PitchDataExtractor._gameday_context(sim)
    assert ctx["pitcher_pitch_count"] == 40
    assert manager.get_active_pitcher_stats().pitch_count == 41


# ---- An ABS overturn keeps the pitcher's fatigue wired up -------------------

def test_an_overturn_restores_pitcher_lines_in_place():
    """The pitcher on the mound reads fatigue off his own `PitcherStats`. The
    restore used to swap in copies, so every pitch after a GameDay overturn
    was counted on an object the pitcher no longer read."""
    from strikefactor.main import Game

    manager = GameDayManager(starter_name="sale")
    on_mound = manager.get_active_pitcher_stats()
    on_mound.pitch_count = 50
    snap = {
        "player_score": 0, "opponent_score": 0, "_current_half_runs": 0,
        "current_outs": 0, "_consecutive_hits": 0, "player_consecutive_hits": 0,
        "event_log_len": 0, "is_walkoff": False, "game_over": False,
        "opponent_pitcher_stats": copy.deepcopy(manager.opponent_pitcher_stats),
        "player_pitcher_stats": copy.deepcopy(manager.player_pitcher_stats),
        "player_inning_scores": [], "opponent_inning_scores": [],
    }
    on_mound.walks += 1            # what the umpire's ball four recorded
    game = SimpleNamespace(
        game_stats=SimpleNamespace(), scoreKeeper=ScoreKeeper(), inning_ended=False,
        state_manager=SimpleNamespace(current_state_name="gameplay"),
        gameday_manager=manager,
        field_renderer=SimpleNamespace(),
        banner=SimpleNamespace(hide_banner=lambda: None),
        sound_manager=SimpleNamespace(pending_sounds=[]),
    )
    Game.restore_for_abs(game, {
        "game_stats": SimpleNamespace(), "scoreKeeper": ScoreKeeper(),
        "inning_ended": False, "state_name": "gameplay", "gameday": snap,
        "field_renderer": {"total_at_bats": 0, "total_walks": 0, "hit_records_len": 0}})

    assert manager.get_active_pitcher_stats() is on_mound
    assert (on_mound.walks, on_mound.pitch_count) == (0, 50)
    assert isinstance(on_mound, PitcherStats)
