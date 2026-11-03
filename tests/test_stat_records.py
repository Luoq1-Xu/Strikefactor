"""Small records that have to describe the pitch, the pitcher or the window as
they really were."""

from types import SimpleNamespace

import pytest

from strikefactor.helpers import ScoreKeeper
from strikefactor.pitchers.pitcher import Pitcher, count_state

# ---- The batter's count tendencies use the count the pitch was thrown in ----

@pytest.mark.parametrize("before,state", [((0, 0), "first_pitch"), ((1, 2), "ahead"),
                                          ((3, 2), "full"), ((2, 0), "behind")])
def test_a_pitch_is_filed_under_the_count_it_was_thrown_in(before, state):
    """Cleanup runs after the count has moved on — or reset to 0-0 when the
    pitch ended the at-bat — so a strikeout at 1-2 was filed as a first pitch."""
    from strikefactor.ai.AI_2 import ERAI
    from strikefactor.gameplay.pitch_simulation import PitchSimulation
    from strikefactor.main import GameStats

    recorded = {}
    game = SimpleNamespace(
        ball=(630, 480), swing_started=1, pitchnumber=0, last_pitch_information=[],
        currentballs=0, currentstrikes=0,               # the at-bat just ended
        pitch_trajectories=[], pitch_history=[], current_pitches=0,
        field_renderer=SimpleNamespace(record_pitch=lambda: None, total_pitches=1,
                                       record_attempt=lambda x, y: None),
        current_pitcher=SimpleNamespace(get_ai=lambda: ERAI(["FF"])),
        batter_profile=SimpleNamespace(record_pitch=lambda **kw: recorded.update(kw)),
        batter=SimpleNamespace(get_handedness=lambda: "R"),
        build_ai_state=lambda: (0, 0, 0), outcome_value=GameStats().outcome_value,
        pitch_chosen="FF", scoreKeeper=ScoreKeeper(), pending_challenge=None,
    )
    sim = object.__new__(PitchSimulation)
    sim.game, sim.new_entry, sim.pitchtype, sim.outcome = game, {}, "FF", "strikeout"
    sim.new_data_entry = {"Balls": before[0], "Strikes": before[1]}
    sim.previous_state = (0, before[1], before[0])
    sim._score_before_pitch = sim._earned_before_pitch = 0
    sim._record_to_database = lambda: None
    sim.cleanup()
    assert recorded["count_state"] == state


def test_the_pitcher_and_the_profile_classify_a_count_the_same_way():
    pitcher = object.__new__(Pitcher)
    for balls in range(4):
        for strikes in range(3):
            pitcher._game_ref = SimpleNamespace(currentballs=balls, currentstrikes=strikes)
            assert pitcher._get_count_state() == count_state(balls, strikes)


# ---- ERA -----------------------------------------------------------------------

def test_earned_runs_without_an_out_are_an_infinite_era():
    """It was None, which the pitching summary printed as a perfect 0.00."""
    era = Pitcher.recalculate_era(SimpleNamespace(outs=0, earned_runs=3))
    assert era == float("inf")


def test_no_outs_and_no_runs_is_no_era_yet():
    assert Pitcher.recalculate_era(SimpleNamespace(outs=0, earned_runs=0)) is None


def test_an_era_is_still_nine_innings_of_earned_runs():
    assert Pitcher.recalculate_era(SimpleNamespace(outs=9, earned_runs=1)) == 3.0


# ---- The window ------------------------------------------------------------------

def test_a_window_with_no_area_keeps_the_last_scale():
    """A minimised window can report 0x0, and a zero scale made mapping the
    next mouse event divide by zero."""
    from strikefactor.main import Game

    game = SimpleNamespace(internal_width=1280, internal_height=720,
                           window=SimpleNamespace(get_size=lambda: (1920, 1080)))
    Game._update_scaling(game)
    assert game._scale == 1.5

    game.window = SimpleNamespace(get_size=lambda: (0, 0))
    Game._update_scaling(game)
    assert game._scale == 1.5
    assert Game._window_to_internal(game, 960, 540) == (640, 360)
