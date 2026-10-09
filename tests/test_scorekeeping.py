"""The official scorer: earned runs, whose run it is, RBI and sacrifice flies.

Every run used to be charged as earned, to whoever was on the mound when it
scored, and credited to the batter as a run batted in. So a two-out error
followed by a home run cost the pitcher two earned runs, a reliever wore the
runners he inherited, and a run an error let in was an RBI.

`helpers.ScoreKeeper` now rules on each run the way Rule 9.16 does: it rebuilds
the half-inning as it would have gone with errorless fielding, and a run is
earned when that inning scores it too. The cases below named for a rule are the
Official Baseball Rules' own worked examples.
"""

import random
import sqlite3
from types import SimpleNamespace

import pygame
import pytest

from strikefactor import outcomes
from strikefactor.data.pitch_database import SCHEMA_VERSION, PitchDB
from strikefactor.gameplay.gameday_manager import (
    GameDayManager,
    GameEvent,
    PitcherStats,
)
from strikefactor.helpers import Play, Runner, ScoreKeeper

ERROR = outcomes.REACHED_ON_ERROR


def _inning(*plays):
    """A half-inning from `(outcome, outs_before, ...)` plays.

    A play is `("walk", outs)`, `("pitcher", name)` for a change on the mound,
    or `(outcome, outs)` with an optional dict of `update_hit_event` keywords.
    """
    sk = ScoreKeeper()
    for play in plays:
        if play[0] == "pitcher":
            sk.set_pitcher(play[1])
        elif play[0] == "walk":
            sk.update_walk_event(outs=play[1])
        else:
            kw = play[2] if len(play) > 2 else {}
            sk.update_hit_event(play[0], outs=play[1], **kw)
    return sk


def _error(outs, out="GROUNDOUT", bases=1):
    return (ERROR, outs, dict(clean_outcome=out, bases=bases))


def _charges(sk):
    return {pitcher: (runs, earned) for pitcher, runs, earned in sk.take_charges()}


# ---- A run an error let in is unearned --------------------------------------

def test_a_runner_who_reached_on_an_error_scores_an_unearned_run():
    sk = _inning(_error(0), ("TRIPLE", 0))
    assert (sk.get_score(), sk.get_earned_runs()) == (1, 0)

    # The batter who drove him in reached on his own, and his run is earned.
    sk.update_hit_event("SINGLE", outs=0)
    assert (sk.get_score(), sk.get_earned_runs()) == (2, 1)


def test_a_clean_inning_earns_every_run():
    sk = _inning(("SINGLE", 0), ("walk", 0), ("DOUBLE", 0), ("HOME RUN", 0))
    assert sk.get_score() == sk.get_earned_runs() == 4


def test_rule_9_16_a_nothing_is_earned_after_the_third_out_that_should_have_been():
    """Two out, an error, two home runs: three runs, none earned, because the
    error should have ended the inning."""
    sk = _inning(("GROUNDOUT", 0), ("FLYOUT", 1), _error(2),
                 ("HOME RUN", 2), ("HOME RUN", 2), ("GROUNDOUT", 2))
    assert (sk.get_score(), sk.get_earned_runs()) == (3, 0)


def test_an_error_with_none_out_does_not_spoil_the_rest_of_the_inning():
    """The reconstructed inning has one out, not three: the home run that
    follows is earned for the batter and unearned for the runner."""
    sk = _inning(_error(0), ("HOME RUN", 0))
    assert (sk.get_score(), sk.get_earned_runs()) == (2, 1)


def test_strikeouts_count_toward_the_third_out_without_reaching_the_scorekeeper():
    """A strikeout is never passed in. It arrives as the `outs` of the next
    play, which is why outs are an argument and not a count kept here."""
    sk = _inning(_error(0), ("HOME RUN", 2))    # two strikeouts in between
    assert (sk.get_score(), sk.get_earned_runs()) == (2, 0)


# ---- A runner an error moved up (Rule 9.16(d)) ------------------------------

def test_a_run_an_error_advanced_is_earned_only_if_it_would_have_scored_anyway():
    """A single, then a fly ball dropped at the wall: the runner is on third
    in fact and still on first in the errorless inning."""
    def start():
        return _inning(("SINGLE", 0), _error(0, out="FLYOUT", bases=2))

    # A sacrifice fly scores him. Errorless, he is on first with two out.
    sk = start()
    sk.update_hit_event("FLYOUT", outs=0)
    assert (sk.get_score(), sk.get_earned_runs()) == (1, 0)
    # A double would not have brought him round from first either.
    sk.update_hit_event("DOUBLE", outs=1)
    assert (sk.get_score(), sk.get_earned_runs()) == (2, 0)

    # A home run would have, so the run he had already scored becomes earned
    # on a play it did not score on.
    sk = start()
    sk.update_hit_event("FLYOUT", outs=0)
    assert sk.get_earned_runs() == 0
    sk.update_hit_event("HOME RUN", outs=1)
    # The runner and the batter are earned; the man who reached on the error
    # is not.
    assert (sk.get_score(), sk.get_earned_runs()) == (3, 2)


def test_an_early_run_stays_unearned_if_the_errorless_inning_ends_first():
    """Home in fact, on second in the reconstruction, which then makes its
    third out. The home run after it cannot earn him."""
    sk = _inning(("DOUBLE", 0), _error(0, out="LINEOUT", bases=2))
    assert (sk.get_score(), sk.get_earned_runs()) == (1, 0)
    sk.update_hit_event("LINEOUT", outs=0)      # reconstruction: two out
    sk.update_hit_event("POP UP", outs=1)       # reconstruction: three
    sk.update_hit_event("HOME RUN", outs=2)
    assert (sk.get_score(), sk.get_earned_runs()) == (3, 0)


def test_a_walk_forces_the_reconstruction_off_its_own_bases():
    """A two-base error leaves the runner on third in fact and on first in the
    errorless inning, so the same walks force him along at different times."""
    sk = _inning(("SINGLE", 0), _error(0, out="POP UP", bases=2),
                 ("walk", 0))
    # In fact the walk loaded the bases behind him and forced nobody.
    # Errorless, it forced him from first to second.
    assert sk.get_bases() == ["yellow", "yellow", "yellow"]
    assert sk.get_score() == 0

    # Forced home in fact; forced only to third in the errorless inning.
    sk.update_walk_event(outs=0)
    assert (sk.get_score(), sk.get_earned_runs()) == (1, 0)

    # Now the errorless inning has the bases loaded and a walk, and his run is
    # earned. The run this walk forced in is the man the error put on.
    sk.update_walk_event(outs=0)
    assert (sk.get_score(), sk.get_earned_runs()) == (2, 1)


def test_the_out_an_error_should_have_been_moves_the_runners_as_that_out_does():
    """Runner on third, none out. A booted grounder would have scored him as
    an out, so his run is earned; a dropped pop-up would not have."""
    grounder = _inning(("TRIPLE", 0), _error(0, out="GROUNDOUT"))
    assert (grounder.get_score(), grounder.get_earned_runs()) == (1, 1)

    popup = _inning(("TRIPLE", 0), _error(0, out="POP UP"))
    assert (popup.get_score(), popup.get_earned_runs()) == (1, 0)

    # Unknown: the pitcher gets the benefit of the doubt (Rule 9.16(f)).
    unknown = _inning(("TRIPLE", 0), (ERROR, 0))
    assert (unknown.get_score(), unknown.get_earned_runs()) == (1, 0)


# ---- Whose run it is (Rules 9.16(g) and 9.16(i)) ----------------------------

def test_rule_9_16_g_an_inherited_runner_is_charged_to_the_pitcher_who_put_him_on():
    """Peter walks Abel; Roger relieves. A groundout, a flyout, and a single
    that scores Abel: the run is Peter's."""
    sk = _inning(("pitcher", "peter"), ("walk", 0), ("pitcher", "roger"),
                 ("GROUNDOUT", 0), ("FLYOUT", 1), ("DOUBLE", 2))
    assert _charges(sk) == {"peter": (1, 1)}


def test_rule_9_16_i_example_1_the_reliever_gets_no_benefit_of_earlier_chances():
    """Two out. Peter walks one and the next reaches on an error; Roger
    relieves and gives up a home run. Two unearned to Peter, one earned to
    Roger — the inning should have been over, but not on Roger's watch."""
    sk = _inning(("pitcher", "peter"), ("walk", 2), _error(2),
                 ("pitcher", "roger"), ("HOME RUN", 2))
    assert _charges(sk) == {"peter": (2, 0), "roger": (1, 1)}


def test_rule_9_16_i_example_2_an_error_behind_the_reliever_is_his_chance():
    sk = _inning(("pitcher", "peter"), ("walk", 2), ("walk", 2),
                 ("pitcher", "roger"), _error(2), ("HOME RUN", 2))
    assert _charges(sk) == {"peter": (2, 0), "roger": (2, 0)}


def test_rule_9_16_i_example_3():
    """None out: a walk and an error off Peter, a home run off Roger, two
    strikeouts, another error, another home run. Peter two runs, one earned;
    Roger three runs, one earned."""
    sk = _inning(("pitcher", "peter"), ("walk", 0), _error(0),
                 ("pitcher", "roger"), ("HOME RUN", 0),
                 _error(2), ("HOME RUN", 2))
    assert _charges(sk) == {"peter": (2, 1), "roger": (3, 1)}


def test_charges_are_handed_over_once():
    sk = _inning(("HOME RUN", 0))
    assert _charges(sk) == {None: (1, 1)}
    assert sk.take_charges() == []


# ---- Runs batted in and sacrifice flies (Rules 9.04, 9.08(d)) ---------------

@pytest.mark.parametrize("play, expected", [
    (("SINGLE", 0), Play(1, 1, False)),
    (("HOME RUN", 0), Play(2, 2, False)),
    (("GROUNDOUT", 0), Play(1, 1, False)),
    (("FLYOUT", 0), Play(1, 1, True)),       # the sacrifice fly
    (("FLYOUT", 2), Play(0, 0, False)),      # the third out scores nobody
    (("LINEOUT", 0), Play(0, 0, False)),
    (("POP UP", 0), Play(0, 0, False)),
])
def test_the_batters_line_with_a_runner_on_third(play, expected):
    sk = _inning(("TRIPLE", 0), play)
    assert sk.last_play == expected


@pytest.mark.parametrize("play, expected", [
    # Fewer than two out and the runner would have scored on the out: an RBI.
    (_error(0, out="GROUNDOUT"), Play(1, 1, False)),
    # A dropped fly ball he would have tagged up on is still a sacrifice fly.
    (_error(1, out="FLYOUT"), Play(1, 1, True)),
    # He would have held on these.
    (_error(0, out="LINEOUT"), Play(1, 0, False)),
    (_error(0, out="POP UP"), Play(1, 0, False)),
    # Two out: the out ends the inning, so the error is all that scored him.
    (_error(2, out="GROUNDOUT"), Play(1, 0, False)),
    (_error(2, out="FLYOUT"), Play(1, 0, False)),
])
def test_a_run_that_scores_on_an_error_is_batted_in_only_if_the_out_would_have_scored_it(
        play, expected):
    sk = _inning(("TRIPLE", 0), play)
    assert sk.last_play == expected


def test_a_two_base_error_bats_in_only_the_runner_from_third():
    sk = _inning(("SINGLE", 0), ("DOUBLE", 0), _error(0, bases=2))
    assert sk.last_play == Play(runs=2, rbi=1, sacrifice_fly=False)


def test_a_fly_ball_that_only_moves_a_runner_up_is_an_at_bat():
    sk = _inning(("DOUBLE", 0), ("FLYOUT", 0))
    assert sk.last_play == Play(0, 0, False)
    assert sk.isRunnerOnBase(3)


def test_a_bases_loaded_walk_bats_in_the_run():
    sk = _inning(("SINGLE", 0), ("SINGLE", 0), ("SINGLE", 0), ("walk", 0))
    assert sk.last_play == Play(1, 1, False)
    assert sk.get_earned_runs() == 1


# ---- The reconstruction never runs ahead of the game ------------------------

def test_no_sequence_of_plays_earns_more_runs_than_scored():
    """The guarantee the two-position model rests on: nobody is further along
    in the errorless inning than in the real one. Checked on the state itself
    after every play, over innings made of every kind of play there is."""
    outs_made = set(outcomes.BATTED_OUT_OUTCOMES) | {"STRIKEOUT"}
    plays = (list(outcomes.HIT_OUTCOMES) + list(outs_made)
             + ["walk", ERROR, ERROR])
    rng = random.Random(9_16)
    for _ in range(400):
        sk, outs, charged = ScoreKeeper(), 0, [0, 0]
        while outs < 3:
            if rng.random() < 0.15:
                sk.set_pitcher(rng.choice("abc"))
            play = rng.choice(plays)
            if play == "walk":
                sk.update_walk_event(outs=outs)
            elif play == ERROR:
                sk.update_hit_event(
                    ERROR, outs=outs, bases=rng.randint(1, 3),
                    clean_outcome=rng.choice(outcomes.BATTED_OUT_OUTCOMES + (None,)))
            elif play != "STRIKEOUT":
                sk.update_hit_event(play, outs=outs)
            outs += play in outs_made

            for runner in sk.runners:
                assert runner.clean_base is None or runner.clean_base <= runner.base
            for runner in sk._home_early:
                assert runner.scored and runner.clean_base <= 3
            for _, runs, earned in sk.take_charges():
                charged[0] += runs
                charged[1] += earned
            assert 0 <= sk.get_earned_runs() <= sk.get_score()
            assert charged == [sk.get_score(), sk.get_earned_runs()]


# ---- The scorekeeper survives the things done to it -------------------------

def test_restoring_a_snapshot_takes_the_earned_runs_back_with_the_runs():
    """An ABS overturn rolls the scorekeeper back. The copy used to be four
    named fields, which would have left the scorer's half behind."""
    sk = _inning(("pitcher", "sale"), ("SINGLE", 0), ("SINGLE", 0), ("SINGLE", 0))
    sk.take_charges()
    snapshot = ScoreKeeper()
    snapshot.restore_from(sk)

    sk.update_walk_event(outs=0)                 # the call under review
    assert (sk.get_score(), sk.get_earned_runs()) == (1, 1)

    sk.restore_from(snapshot)
    assert (sk.get_score(), sk.get_earned_runs()) == (0, 0)
    assert sk.take_charges() == []
    assert sk.pitcher == "sale"
    # The restored runners are the scorekeeper's own again, not the snapshot's.
    sk.update_hit_event("HOME RUN", outs=0)
    assert (sk.get_score(), sk.get_earned_runs()) == (4, 4)
    assert snapshot.get_score() == 0 and len(snapshot.runners) == 3


def test_a_runner_placed_on_base_by_a_scenario_is_earned_when_he_scores():
    """`Game` seeds a random scenario's runners straight into `runners`."""
    sk = ScoreKeeper()
    sk.runners.append(Runner(3))
    sk.update_hit_event("SINGLE", outs=2)
    assert (sk.get_score(), sk.get_earned_runs()) == (1, 1)


# ---- GameDay: the pitching lines --------------------------------------------

def _gameday():
    return GameDayManager(difficulty='amateur', starter_name='sale')


def test_an_unearned_run_is_on_the_pitchers_r_and_not_his_er():
    gm = _gameday()
    sk = ScoreKeeper()
    sk.set_pitcher(gm.current_pitcher_name)

    sk.update_hit_event(ERROR, outs=2, clean_outcome="GROUNDOUT")
    gm.record_player_at_bat("REACHED ON ERROR", runs_scored=0, pitches_thrown=3,
                            play=sk.last_play, charges=sk.take_charges())
    sk.update_hit_event("HOME RUN", outs=2)
    gm.record_player_at_bat("HOME RUN", runs_scored=2, pitches_thrown=2,
                            play=sk.last_play, charges=sk.take_charges())

    stats = gm.get_active_pitcher_stats()
    assert (stats.runs_allowed, stats.earned_runs) == (2, 0)
    assert gm.player_score == 2
    # The hit that scored them still batted them both in.
    assert gm.event_log[-1].rbi == 2


def test_a_run_ruled_earned_later_reaches_the_line_on_the_later_play():
    gm = _gameday()
    sk = _inning(("pitcher", gm.current_pitcher_name), ("SINGLE", 0),
                 _error(0, out="FLYOUT", bases=2), ("FLYOUT", 0))
    gm.record_player_at_bat("FLYOUT", runs_scored=1, pitches_thrown=1,
                            play=sk.last_play, charges=sk.take_charges())
    stats = gm.get_active_pitcher_stats()
    assert (stats.runs_allowed, stats.earned_runs) == (1, 0)

    sk.update_hit_event("HOME RUN", outs=1)
    gm.record_player_at_bat("HOME RUN", runs_scored=2, pitches_thrown=1,
                            play=sk.last_play, charges=sk.take_charges())
    assert (stats.runs_allowed, stats.earned_runs) == (3, 2)


def test_recording_an_at_bat_without_the_scorer_charges_every_run_as_earned():
    gm = _gameday()
    gm.record_player_at_bat("HOME RUN", runs_scored=1, pitches_thrown=1)
    stats = gm.get_active_pitcher_stats()
    assert (stats.runs_allowed, stats.earned_runs) == (1, 1)
    assert gm.event_log[-1].rbi == 1


def test_the_simulated_staff_charges_inherited_runners_to_who_left_them(monkeypatch):
    """The player's own staff changes pitchers mid-inning. The runs used to go
    on the line of whoever was pitching when they scored."""
    gm = _gameday()
    starter = gm.current_player_pitcher_name

    def bat(outcome):
        monkeypatch.setattr(gm, "_get_adjusted_probabilities",
                            lambda extra_hit_boost=0.0: {outcome: 1.0})
        return gm.simulate_opponent_at_bat()

    bat("WALK")
    bat("SINGLE")
    reliever = gm.substitute_player_relief_pitcher()
    assert reliever and reliever != starter
    assert bat("HOME RUN") == ("HOME RUN", 3)

    left, came_in = gm.player_pitcher_stats[starter], gm.player_pitcher_stats[reliever]
    assert (left.runs_allowed, left.earned_runs) == (2, 2)
    assert (came_in.runs_allowed, came_in.earned_runs) == (1, 1)
    assert (left.hits_allowed, came_in.hits_allowed) == (1, 1)
    assert gm.opponent_score == 3


def test_a_session_saved_before_earned_runs_reads_its_runs_as_earned():
    """Every run was charged as earned then, so that is what its line said."""
    old = PitcherStats("sale").to_dict()
    old["runs_allowed"] = 4
    del old["earned_runs"]
    assert PitcherStats.from_dict(old).earned_runs == 4

    new = PitcherStats("sale")
    new.charge_runs(4, 1)
    assert PitcherStats.from_dict(new.to_dict()).earned_runs == 1


def test_an_event_keeps_the_scorers_ruling_through_a_save():
    event = GameEvent(3, False, "Player", "sale", "REACHED ON ERROR",
                      runs_scored=1, rbi=0)
    assert GameEvent.from_dict(event.to_dict()).rbi == 0

    fly = GameEvent(3, False, "Player", "sale", "FLYOUT", runs_scored=1,
                    rbi=1, sacrifice_fly=True)
    assert GameEvent.from_dict(fly.to_dict()).sacrifice_fly is True

    # A play logged before the scorer ruled on it: its runs were its RBI.
    legacy = GameEvent.from_dict({"inning": 1, "is_top": False,
                                  "batter_name": "Player", "pitcher_name": "sale",
                                  "result": "SINGLE", "runs_scored": 2})
    assert (legacy.rbi, legacy.sacrifice_fly) == (2, False)


# ---- GameDay: the batting line ----------------------------------------------

def test_the_batting_line_charges_no_at_bat_for_a_sacrifice_fly_and_no_rbi_for_an_error():
    from strikefactor.gameplay.game_states import GameDayTransitionState

    gm = _gameday()
    gm.is_top_inning = False
    sk = ScoreKeeper()

    def bat(outcome, outs, **kw):
        sk.update_hit_event(outcome, outs=outs, **kw)
        gm.record_player_at_bat(outcome, runs_scored=sk.last_play.runs,
                                play=sk.last_play, charges=sk.take_charges())

    bat("TRIPLE", 0)
    bat("FLYOUT", 0)                                     # sacrifice fly, RBI
    bat("TRIPLE", 1)
    bat(ERROR, 1, clean_outcome="POP UP")                # run in, no RBI
    gm.record_player_at_bat("STRIKEOUT")

    state = object.__new__(GameDayTransitionState)
    state.game = SimpleNamespace(gameday_manager=gm)
    line = state._player_batting_stats()
    # Two triples, the error and the strikeout; the sacrifice fly is not one.
    assert (line['AB'], line['H'], line['RBI'], line['R']) == (4, 2, 1, 2)
    assert line['AVG'] == pytest.approx(0.5)


# ---- GameDay: the linescore's E ---------------------------------------------

def test_the_linescore_charges_an_error_to_the_team_in_the_field():
    """The E column was a literal 0 for both teams. An error made while the
    player bats is the opponent's, whatever spelling the play log is in."""
    plays = [("REACHED ON ERROR", False), ("SINGLE", False),
             ("REACHED_ON_ERROR", False),            # the database's spelling
             ("GROUNDOUT", True), ("reached on error", True)]
    assert GameDayManager.error_totals(plays) == (1, 2)


def test_the_live_linescore_draws_the_errors_from_the_event_log(monkeypatch):
    from strikefactor.gameplay.game_states import GameDayTransitionState
    from strikefactor.ui import gameday_theme as gdt

    gm = _gameday()
    gm.is_top_inning = False
    gm.record_player_at_bat("REACHED ON ERROR")
    gm.record_player_at_bat("SINGLE")

    rows = []
    monkeypatch.setattr(
        gdt, "_draw_linescore_row",
        lambda screen, fonts, label, runs, r, h, e, *a, **k: rows.append((label, h, e)))
    state = object.__new__(GameDayTransitionState)
    state.game = SimpleNamespace(gameday_manager=gm)
    state._gd_fonts = gdt.load_fonts()
    state._draw_linescore(pygame.Surface((gdt.SCREEN_W, gdt.SCREEN_H)), 0, 0)
    # The opponent's defense made the error; the player has the one hit.
    assert rows == [("OPPONENT", 0, 1), ("YOU", 1, 0)]


# ---- The play reaches the scorer from the animation -------------------------

def _finalize(classified, sk, outs=0, **anim):
    """Run `_finalize_batted_ball` over a real scorekeeper. Returns the game."""
    from strikefactor.gameplay.hit_outcome_manager import HitOutcomeManager
    from strikefactor.gameplay.pitch_simulation import PitchSimulation

    manager = object.__new__(HitOutcomeManager)
    manager.score_keeper = sk
    counts = SimpleNamespace(at_bats=0, sacrifice_flies=0, hits=0)

    def count(name):
        return lambda *a, **k: setattr(counts, name, getattr(counts, name) + 1)

    game = SimpleNamespace(
        currentouts=outs, hits=0, last_pitch_information=[], ball=(640, 400),
        in_gameday_mode=False, scoreKeeper=sk, hit_outcome_manager=manager,
        field_renderer=SimpleNamespace(record_hit=count("hits"),
                                       record_at_bat=count("at_bats"),
                                       record_sacrifice_fly=count("sacrifice_flies")),
        ui_manager=SimpleNamespace(show_banner=lambda text: None),
        counts=counts,
    )
    sim = object.__new__(PitchSimulation)
    sim.game, sim.new_entry = game, {}
    sim.hit_animation = SimpleNamespace(
        classified_outcome=classified, fielder_role="CF", play_timing=None,
        extra_base_margin_s=None, **anim)
    sim._finalize_batted_ball()
    return game


def test_a_home_run_reaches_the_scorer_with_the_outs():
    """The home run is scored at contact, on its own path to the scorekeeper."""
    from strikefactor.gameplay.hit_outcome_manager import HitOutcomeManager

    sk = _inning(_error(2))
    manager = object.__new__(HitOutcomeManager)
    manager.score_keeper, manager.hit_type = sk, 4
    manager.update_runners_and_score(outs=2)
    assert manager.get_homerun_text() == 'TWO-RUN HOME RUN'
    assert (sk.get_score(), sk.get_earned_runs()) == (2, 0)


def test_a_sacrifice_fly_is_recorded_in_place_of_the_at_bat():
    game = _finalize("FLYOUT", _inning(("TRIPLE", 0)))
    assert game.scoreKeeper.get_score() == 1
    assert (game.counts.at_bats, game.counts.sacrifice_flies) == (0, 1)

    # The same fly ball with nobody to score is an ordinary at-bat...
    game = _finalize("FLYOUT", ScoreKeeper())
    assert (game.counts.at_bats, game.counts.sacrifice_flies) == (1, 0)
    # ...and so is the one that makes the third out.
    game = _finalize("FLYOUT", _inning(("TRIPLE", 0)), outs=2)
    assert game.scoreKeeper.get_score() == 0
    assert (game.counts.at_bats, game.counts.sacrifice_flies) == (1, 0)


def test_an_error_reaches_the_scorer_with_the_out_it_cost():
    """`currentouts` already counts the out being finalized, and the scorer
    wants the outs before it. Two down and an error: nothing after is earned."""
    sk = _inning(("TRIPLE", 0))
    game = _finalize("REACHED ON ERROR", sk, outs=2, error_bases=1,
                     error_out="GROUNDOUT")
    assert game.currentouts == 2 and game.hits == 0
    assert (sk.get_score(), sk.get_earned_runs()) == (1, 0)
    assert sk.last_play == Play(runs=1, rbi=0, sacrifice_fly=False)
    assert (game.counts.at_bats, game.counts.hits) == (1, 0)

    game = _finalize("GROUNDOUT", _inning(("TRIPLE", 0)), outs=0)
    assert game.currentouts == 1
    assert game.scoreKeeper.get_score() == 1


# ---- The database column ----------------------------------------------------

def test_a_fresh_database_has_the_earned_run_column(tmp_path):
    db = PitchDB(str(tmp_path / "fresh.db"))
    try:
        cols = {r[1] for r in db.conn.execute("PRAGMA table_info(pitches)")}
        assert "earned_runs_on_pitch" in cols
        assert SCHEMA_VERSION >= 12
    finally:
        db.close()


def test_migrating_adds_the_earned_run_column_as_unknown(tmp_path):
    """A row from before v12 has runs and no ruling on them. NULL, and never
    a copy of the runs: some of them an error let in."""
    path = str(tmp_path / "v11.db")
    conn = sqlite3.connect(path)
    conn.executescript(PitchDB.SCHEMA)
    conn.execute("ALTER TABLE pitches DROP COLUMN earned_runs_on_pitch")
    conn.execute(
        "INSERT INTO pitches (pitch_id, session_id, game_mode, difficulty, "
        "created_at, pitcher_name, pitch_type, outcome, runs_scored_on_pitch) "
        "VALUES ('p1', 's1', 'gameday', 'amateur', '2026-01-01T00:00:00', "
        "'Sale', 'FASTBALL', 'HOME RUN', 2)")
    conn.execute("PRAGMA user_version = 11")
    conn.commit()
    conn.close()

    db = PitchDB(path)
    try:
        row = db.conn.execute(
            "SELECT runs_scored_on_pitch, earned_runs_on_pitch FROM pitches").fetchone()
        assert tuple(row) == (2, None)
        assert db.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    finally:
        db.close()


# ---- The offline pitching line ----------------------------------------------

def _pitching_line(rows):
    import pandas as pd

    from analysis import metrics

    df = pd.DataFrame(rows, columns=["outcome", "runs_scored_on_pitch",
                                     "earned_runs_on_pitch"])
    df["pitcher_name"] = "Sale"
    df["game_mode"] = "gameday"
    df["game_id"] = "g1"
    df["is_terminal"] = True
    ctx = SimpleNamespace(pitches=df, games=pd.DataFrame())
    return metrics.pitching_line(ctx).iloc[0]


# ---- The offline at-bat count -----------------------------------------------

# The out an error costs, by the shape of the ball: a drop is the catch it was.
# tests/test_defense.py pins the animation to the FLY row of it, which is the
# one the analysis leans on.
_ERROR_OUT = {"GROUNDER": "GROUNDOUT", "LINER": "LINEOUT", "FLY": "FLYOUT",
              "POP_UP": "POP UP"}


def test_the_analysis_rules_a_sacrifice_fly_wherever_the_scorer_does(tmp_path):
    """The offline scripts cannot import the scorer — they have to read an
    archive without the game installed — so they read the ruling off the row
    (`data.sac_fly_sql`). Every ball in play, on every shape, with and without
    a runner on third, at every out count: the two must agree on each one."""
    from analysis import data

    path = str(tmp_path / "plays.db")
    db = PitchDB(path)
    rulings = {}
    for outs in (0, 1, 2):
        for on_third in (False, True):
            for outcome in outcomes.IN_PLAY_OUTCOMES:
                for shape, error_out in _ERROR_OUT.items():
                    sk = ScoreKeeper()
                    sk.runners.append(Runner(2))
                    if on_third:
                        sk.runners.append(Runner(3))
                    sk.update_hit_event(outcome, outs=outs, clean_outcome=error_out)
                    pitch_id = f"p{len(rulings)}"
                    rulings[pitch_id] = sk.last_play.sacrifice_fly
                    db.conn.execute(
                        "INSERT INTO pitches (pitch_id, session_id, game_mode, "
                        "difficulty, created_at, pitcher_name, pitch_type, "
                        "swing_type, plate_x_ft, plate_z_ft, balls_before, "
                        "strikes_before, outcome, runs_scored_on_pitch, "
                        "batted_ball_type, runner_3b, outs_before) "
                        "VALUES (?, 's1', 'arcade', 'amateur', "
                        "'2026-01-01T00:00:00', 'Sale', 'FF', 1, 0.0, 2.5, 0, 0, "
                        "?, ?, ?, ?, ?)",
                        (pitch_id, outcome, sk.last_play.runs, shape,
                         int(on_third), outs))
    db.conn.commit()
    db.close()

    df = data.load_pitches(path)
    assert dict(zip(df["pitch_id"], df["is_sac_fly"])) == rulings
    # Not vacuous: the caught fly on every shape label, and the dropped FLY,
    # each with a runner on third and none or one out.
    assert sum(rulings.values()) == 2 * len(_ERROR_OUT) + 2


def test_an_archive_without_the_columns_keeps_every_at_bat():
    """The analysis connection is read-only, so an old archive is never
    migrated. A half of the ruling it cannot ask is left out, not guessed."""
    from analysis import data

    assert data.sac_fly_sql({"outcome"}) == "0"
    caught_only = data.sac_fly_sql({"outcome", "runs_scored_on_pitch"})
    assert "FLYOUT" in caught_only and "batted_ball_type" not in caught_only


def test_the_slash_line_charges_no_at_bat_for_a_sacrifice_fly():
    """One hit in three at-bats, not four. The sacrifice fly is still a plate
    appearance (OBP) and still a ball in play (BABIP)."""
    import pandas as pd

    from analysis import metrics

    g = pd.DataFrame({
        "outcome":    ["SINGLE", "FLYOUT", "FLYOUT", "GROUNDOUT", "walk"],
        "is_sac_fly": [False,    True,     False,    False,       False],
    })
    g["is_terminal"] = True
    line = metrics._outcome_metrics(g)
    assert (line["pa"], line["ab"], line["sf"], line["h"]) == (5, 3, 1, 1)
    assert line["avg"] == pytest.approx(1 / 3)
    assert line["slg"] == pytest.approx(1 / 3)
    assert line["obp"] == pytest.approx(2 / 5)
    assert line["bip"] == 4 and line["babip"] == pytest.approx(1 / 4)


def test_the_pitching_lines_era_is_over_earned_runs():
    """Two out, an error, a two-run homer, a strikeout: R 2, ER 0."""
    line = _pitching_line([
        ("GROUNDOUT", 0, 0), ("FLYOUT", 0, 0), ("REACHED ON ERROR", 0, 0),
        ("HOME RUN", 2, 0), ("strikeout", 0, 0),
    ])
    assert (line["r"], line["er"], line["outs"]) == (2, 0, 3)
    assert line["era"] == 0.0
    assert bool(line["er_exact"])


def test_rows_without_a_ruling_count_every_run_as_earned_and_say_so():
    line = _pitching_line([
        ("HOME RUN", 1, None), ("strikeout", 0, None),      # before v12
        ("REACHED ON ERROR", 0, 0), ("TRIPLE", 1, 0),       # ruled: unearned
        ("SINGLE", 1, 1), ("strikeout", 0, 0), ("strikeout", 0, 0),
    ])
    assert (line["r"], line["er"]) == (3, 2)
    assert not bool(line["er_exact"])
    assert line["era"] == pytest.approx(18.0)
