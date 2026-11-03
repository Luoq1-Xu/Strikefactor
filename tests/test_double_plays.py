"""Ground-ball turns share their physical timeline with controls and scoring."""

import json
import math
import random
from types import SimpleNamespace

import pytest

from analysis import metrics, theme
from strikefactor import outcomes
from strikefactor.data.pitch_database import PitchDataExtractor
from strikefactor.gameplay import force_play, infield_timing
from strikefactor.gameplay import hit_animation as ha
from strikefactor.gameplay.base_geometry import BASE_FT
from strikefactor.gameplay.fielding_record import FieldingRecorder
from strikefactor.gameplay.gameday_manager import GameDayManager, GameEvent
from strikefactor.gameplay.hit_outcome_manager import HitOutcomeManager
from strikefactor.gameplay.pitch_simulation import PitchSimulation
from strikefactor.gameplay.runner_motion import BatterRun, CircuitRun
from strikefactor.gameplay.running_play import RunnerMovement, RunnerRetirement, RunningResult
from strikefactor.helpers import Runner, ScoreKeeper


def _pickup(monkeypatch, *, role="SS", pickup_s=1.5, first_s=4.3, outs=0,
            mode="manual", bases=(1,), point=None, game_mode="arcade", misplay_s=0.0):
    random.seed(76)
    monkeypatch.setattr(infield_timing, "release_time_s", lambda *args, **kwargs: 0.60)
    game = SimpleNamespace(currentouts=outs, game_mode=game_mode,
                           batter=SimpleNamespace(get_handedness=lambda: "R"))
    anim = ha.HitAnimation(game, "IN_PLAY", lambda: None, quality=0.8,
        batted_ball_type="GROUNDER", ev_mph=95, launch_deg=5, spray_deg=18,
        initial_bases=bases, baserunning_mode=mode)
    anim.runner = BatterRun(first_s)
    anim._circuits["B"] = CircuitRun(anim.runner, 27)
    anim.start_time = 0
    anim._elapsed = anim._secured_at_ms = anim._anim_ms(pickup_s)
    anim._secured = anim._secured_in_flight = True
    anim._primary_role = role
    anim._misplay_s = misplay_s
    receiver = "SS" if role == "2B" else "2B"
    point = point or {"SS": (-50, 110), "2B": (45, 110), "3B": (-70, 70)}[role]
    for r, xy in ((role, point), (receiver, BASE_FT[2]), ("1B", BASE_FT[1])):
        anim.fielders[r].pos[:] = ha._to_screen(*xy)
    anim._ball = anim._ball_shadow = tuple(anim.fielders[role].pos)
    anim._begin_infield_play(role)
    anim._stand_down_non_primary(keep_at_bag=True)
    return anim


def _finish(anim, step=16):
    recorder = FieldingRecorder(anim, "DOUBLE PLAY TEST")
    recorder.capture(anim)
    for _ in range(1500):
        anim.update(anim._elapsed + step)
        recorder.capture(anim)
        if anim.finished:
            return recorder.record
    pytest.fail("ground-ball play did not settle")


@pytest.mark.parametrize("role,sequence", [("SS", ("SS", "2B", "1B")),
                                          ("2B", ("2B", "SS", "1B")),
                                          ("3B", ("3B", "2B", "1B"))])
@pytest.mark.parametrize("mode", ["auto", "manual"])
@pytest.mark.parametrize("step", [16, 250])
@pytest.mark.parametrize("outs", [0, 1])
def test_turns_record_two_physical_outs_and_the_receiving_bags(monkeypatch, role, sequence, mode, step, outs):
    anim = _pickup(monkeypatch, role=role, mode=mode, outs=outs)
    assert anim._force_turn
    # Choosing a turn must not announce either out before it happens.
    assert anim.running_result.outs_added == 0
    record = _finish(anim, step)
    result = record.running_result
    assert result.outcome == outcomes.GROUNDOUT
    assert result.double_play and result.ground_double_play
    assert result.outs_added == 2 and result.running_outs == 1
    assert result.fielding_sequence == sequence
    assert [(r.runner_id, r.base, r.kind) for r in result.retirements] == [
        ("1", 2, "force"), ("B", 1, "batter_before_first")]
    assert all(m.final_base is None for m in result.movements)
    assert not any(m.touches for m in result.movements)
    assert record.duration_ms >= anim._anim_ms(anim.runner.arrival_s + ha.GO_CATCH_HOLD_S)
    assert math.dist((0, 0), ha._to_field_ft(record.frames[-1].runner.pos)) > 90.0
    for retirement in result.retirements:
        frame = record.sample(anim._anim_ms(retirement.time_s))
        runner = frame.runner if retirement.runner_id == "B" else next(
            r for r in frame.runners if r.runner_id == retirement.runner_id)
        assert runner.state == "out"
        assert frame.first_base_call is None
        assert frame.base_call[:2] == ("OUT", retirement.base)
        assert frame.shadow == pytest.approx(ha._to_screen(*BASE_FT[retirement.base]))
        defender = next(f for f in frame.fielders if f.role == retirement.role)
        assert defender.pos == pytest.approx(ha._to_screen(*BASE_FT[retirement.base]))
    if outs == 1:
        assert anim._inning_end_s == result.batter.out_s
        assert not any(e.time_s > anim._inning_end_s for e in result.events)
    else:
        assert anim._inning_end_s is None


@pytest.mark.parametrize("mode", ["auto", "manual"])
@pytest.mark.parametrize("step", [16, 250])
def test_batter_beats_the_relay_for_a_fielders_choice(monkeypatch, mode, step):
    anim = _pickup(monkeypatch, pickup_s=2.1, mode=mode)
    record = _finish(anim, step)
    result = record.running_result
    assert len(anim._return_legs) == 2
    assert result.outcome == outcomes.FIELDERS_CHOICE
    assert result.outs_added == result.running_outs == 1
    assert result.hit_bases == 0 and not result.double_play
    assert result.batter.final_base == 1
    assert result.batter.touches == ((1, 4.3),)
    assert anim.play_timing.defense_s > result.batter.touches[0][1]
    assert any(e.label == "FORCE OUT 2B" for e in record.events)
    assert not any(e.label == "FORCE OUT 1B" for e in record.events)


@pytest.mark.parametrize("step", [16, 250])
def test_a_relay_redirected_away_from_first_leaves_the_batter_safe_on_a_fielders_choice(monkeypatch, step):
    # The planned relay forecast the out at first. Sending the ball to third
    # instead must take that forecast back: the batter reaches untouched.
    # The defense is held to the redirect, as when a runner caught off third
    # draws the throw (found by fuzzing a manual play).
    anim = _pickup(monkeypatch, bases=(1, 3))
    for _ in range(400):
        if anim._return_runner == "B" and len(anim._return_legs) == 2:
            break
        anim.update(anim._elapsed + 16)
    else:
        pytest.fail("the turn never planned its relay to first")
    now = anim._elapsed / (1000 * anim.time_scale)
    pivot = anim._return_legs[0]
    assert now < anim._return_legs[1].release_s  # the relay is not thrown yet
    legs, approaches = anim._return_schedule(3, pivot.target, now, holder=pivot.receiver,
                                             transfer_s=0.0, allow_relay=False)
    anim._replace_return_plan((pivot,), legs, approaches, "3", 3, now, "THROW REDIRECT")
    assert anim.play_timing is None and not anim._first_base_retired
    for rethink in ("_reconsider_return", "_redirect_cutoff"):
        monkeypatch.setattr(anim, rethink, lambda now_s: None)
    result = _finish(anim, step).running_result
    assert result.batter.out_s is None and result.batter.final_base == 1
    assert result.outcome == outcomes.FIELDERS_CHOICE
    assert [(r.runner_id, r.kind) for r in result.retirements] == [("1", "force")]
    assert anim.play_timing is None and not anim._first_base_retired


@pytest.mark.parametrize("delay", [0.0, 0.8])
def test_slow_pickup_or_bobble_takes_the_available_out_at_first(monkeypatch, delay):
    anim = _pickup(monkeypatch, pickup_s=3.0-delay, point=(50, 70), misplay_s=delay)
    assert not anim._force_turn
    assert anim._first_base_retired
    record = _finish(anim)
    assert record.outcome == outcomes.GROUNDOUT
    assert record.running_result.outs_added == 1
    assert not record.running_result.double_play


def test_a_feed_that_the_runner_beats_cannot_record_a_force_out(monkeypatch):
    anim = _pickup(monkeypatch, pickup_s=3.0)
    assert anim._force_turn
    assert anim._return_race.defense_s > anim._return_race.runner_s
    result = _finish(anim).running_result
    assert result.outcome == outcomes.SINGLE
    assert result.outs_added == 0
    assert next(m for m in result.movements if m.runner_id == "1").final_base == 2


def test_a_simultaneous_first_base_reception_is_safe(monkeypatch):
    reference = _pickup(monkeypatch)
    feed_s = reference._return_legs[-1].arrival_s
    first_s = feed_s + 0.45 + 90/reference.defense.throw_fts
    anim = _pickup(monkeypatch, first_s=first_s)
    result = _finish(anim, 250).running_result
    assert anim.play_timing.defense_s == pytest.approx(first_s, abs=1e-12)
    assert result.outcome == outcomes.FIELDERS_CHOICE
    assert result.batter.out_s is None


def test_a_fielder_can_step_on_second_and_throw_without_a_fictitious_feed(monkeypatch):
    anim = _pickup(monkeypatch, point=(-2, BASE_FT[2][1]))
    first = anim._return_legs[0]
    assert first.thrower == first.receiver == "SS"
    record = _finish(anim, 250)
    assert record.running_result.double_play
    assert record.running_result.fielding_sequence == ("SS", "1B")
    assert any(e.label == "CARRY START" for e in record.events)
    assert sum(e.label == "THROW RELEASE" for e in record.events) == 1


def _routes(bases):
    routes = {"B": CircuitRun(BatterRun(4.3), 27)}
    for base in bases:
        route = routes[str(base)] = CircuitRun(None, 27, start_base=base)
        route.commit_next(0.20)
    return routes


@pytest.mark.parametrize("bases,expected", [((1, 2, 3), {"B": 1, "1": 2, "2": 3, "3": 4}),
                                           ((1, 3), {"B": 1, "1": 2, "3": None}),
                                           ((2, 3), {"B": 1, "2": None, "3": None})])
def test_only_the_occupied_chain_creates_forces(bases, expected):
    routes = _routes(bases)
    assert {rid: force_play.forced_base(rid, routes, 1.0) for rid in routes} == expected


def test_retiring_a_following_runner_removes_a_force_and_a_touch_discharges_it():
    routes = _routes((1, 2, 3))
    routes["1"].stopped_at_s = 2.0
    assert force_play.forced_base("2", routes, 1.9) == 3
    assert force_play.forced_base("2", routes, 2.0) is None
    assert force_play.forced_base("3", routes, 2.0) is None
    assert force_play.forced_base("B", routes, 2.0) == 1
    routes = _routes((1,))
    assert force_play.forced_base("1", routes, routes["1"].arrival_s) is None
    routes["B"].stopped_at_s = 2.0
    assert force_play.forced_base("1", routes, 2.0) is None


def test_manual_retreat_cannot_cancel_a_force_and_pending_send_stays_with_runner(monkeypatch):
    anim = _pickup(monkeypatch)
    anim._sync_baserunning(1.5)
    assert anim.baserunning.runner_id == "1"
    assert anim.send_runner()  # asks for third after the required second
    assert anim.retreat_runner()  # cancels third, preserving the required leg
    assert not anim._circuits["1"].returning
    assert anim._circuits["1"].target_base == 2
    result = _finish(anim).running_result
    assert result.double_play
    assert not any(e.label == "MANUAL ADVANCE" and e.runner_id == "B" for e in result.events)


@pytest.mark.parametrize("outs", [0, 1, 2, 7])
def test_sandbox_turns_two_without_ending_the_play_at_a_cumulative_third_out(monkeypatch, outs):
    anim = _pickup(monkeypatch, outs=outs, game_mode="sandbox")
    result = _finish(anim, 250).running_result
    assert result.double_play
    assert anim._inning_end_s is None


def test_two_outs_take_one_out_and_never_throw_a_relay_after_the_third(monkeypatch):
    anim = _pickup(monkeypatch, outs=2)
    result = _finish(anim, 250).running_result
    assert result.outs_added == 1
    assert not result.double_play
    assert anim._inning_end_s is not None
    assert len(anim._return_legs) <= 1


def test_an_inning_ending_force_at_second_stops_before_a_relay(monkeypatch):
    anim = _pickup(monkeypatch, pickup_s=2.7, outs=2)
    assert anim._force_turn
    result = _finish(anim, 250).running_result
    assert result.outcome == outcomes.FIELDERS_CHOICE
    assert result.outs_added == 1
    assert len(anim._return_legs) == 1
    assert anim.play_timing is None  # no first-base race was played
    assert anim._inning_end_s == result.retirements[0].time_s


@pytest.mark.parametrize("outs,runs,rbi", [(0, 1, 0), (1, 0, 0)])
def test_ground_double_play_run_and_rbi_rules(monkeypatch, outs, runs, rbi):
    anim = _pickup(monkeypatch, outs=outs, bases=(1, 3))
    result = _finish(anim).running_result
    keeper = ScoreKeeper()
    keeper.runners = [Runner(1), Runner(3)]
    play = keeper.update_running_play(result, outs=outs)
    assert (play.runs, play.rbi, play.running_outs, play.double_play) == (runs, rbi, 1, True)
    assert all(r.base == 3 for r in keeper.runners)


@pytest.mark.parametrize("kind,expected", [("force", 0), ("tag", 1)])
def test_third_out_kind_controls_an_earlier_run(kind, expected):
    result = RunningResult(outcomes.FIELDERS_CHOICE, 0, (
        RunnerMovement("B", 0, 1, ((1, 4.3),)),
        RunnerMovement("1", 1, None, (), 3.0),
        RunnerMovement("3", 3, 4, ((4, 2.0),)),
    ), retirements=(RunnerRetirement("1", 3.0, 2, kind, "2B"),))
    keeper = ScoreKeeper()
    keeper.runners = [Runner(1), Runner(3)]
    assert keeper.update_running_play(result, outs=2).runs == expected


@pytest.mark.parametrize("pickup_s,outs_added", [(1.5, 2), (2.1, 1)])
def test_finalization_and_gameday_record_outs_once_without_crediting_a_hit(monkeypatch, pickup_s, outs_added):
    anim = _pickup(monkeypatch, pickup_s=pickup_s)
    result = _finish(anim).running_result
    keeper = ScoreKeeper()
    keeper.runners = [Runner(1)]
    manager = object.__new__(HitOutcomeManager)
    manager.score_keeper = keeper
    banners = []
    game = SimpleNamespace(currentouts=0, hits=0, last_pitch_information=[], ball=(640, 400),
        in_gameday_mode=False, scoreKeeper=keeper, hit_outcome_manager=manager,
        field_renderer=SimpleNamespace(record_at_bat=lambda: None,
            record_hit=lambda *a, **k: pytest.fail("a ground out/choice is not a hit")),
        banner=SimpleNamespace(show_banner=banners.append))
    sim = object.__new__(PitchSimulation)
    sim.game, sim.hit_animation, sim.new_entry = game, anim, {}
    sim._finalize_batted_ball()
    assert game.currentouts == outs_added and game.hits == 0 and not sim.is_hit
    assert sim.tag_margin_s is None
    payload = json.loads(sim.running_play_json)
    assert payload["schema_version"] == 5
    assert len(payload["retirements"]) == outs_added
    assert "OUT ADVANCING" not in banners[0]
    assert banners[0] == result.display_name
    gm = GameDayManager()
    gm.record_player_at_bat(result.outcome, play=keeper.last_play)
    assert gm.current_outs == outs_added
    assert gm.get_active_pitcher_stats().outs_recorded == outs_added
    assert gm.get_active_pitcher_stats().hits_allowed == 0
    event = gm.event_log[-1]
    restored = GameEvent.from_dict(json.loads(json.dumps(event.to_dict())))
    assert restored.double_play == result.double_play
    assert restored.fielding_sequence == result.fielding_sequence
    assert "OUT ADVANCING" not in str(restored)


def test_fielders_choice_is_terminal_and_an_at_bat_but_not_a_hit_or_error():
    assert outcomes.db_key(outcomes.FIELDERS_CHOICE) in PitchDataExtractor.TERMINAL_OUTCOMES
    assert outcomes.FIELDERS_CHOICE in theme.IN_PLAY_OUTCOMES
    assert outcomes.FIELDERS_CHOICE not in theme.HIT_OUTCOMES + theme.ERROR_OUTCOMES
    assert GameDayManager.error_totals([(outcomes.FIELDERS_CHOICE, False)]) == (0, 0)
    import pandas as pd
    pitches = pd.DataFrame({"is_terminal": [True], "outcome": [outcomes.FIELDERS_CHOICE],
                            "is_sac_fly": [False]})
    stats = metrics._outcome_metrics(pitches)
    assert (stats["pa"], stats["ab"], stats["h"], stats["roe"]) == (1, 1, 0, 0)


def test_historical_gameday_events_default_to_no_double_play():
    event = GameEvent.from_dict({"inning": 1, "is_top": False, "batter_name": "Player",
                                 "pitcher_name": "Pitcher", "result": outcomes.GROUNDOUT})
    assert not event.double_play and event.fielding_sequence == ()


@pytest.mark.parametrize("reached_on_error", [False, True])
def test_fielders_choice_preserves_inherited_pitcher_responsibility(monkeypatch, reached_on_error):
    anim = _pickup(monkeypatch, pickup_s=2.1)
    result = _finish(anim).running_result
    keeper = ScoreKeeper()
    keeper.set_pitcher("Starter")
    keeper.runners = [Runner(1, "Starter", reached_on_error=reached_on_error)]
    keeper.set_pitcher("Reliever")
    keeper.update_running_play(result)
    replacement = keeper.runners[0]
    assert replacement.pitcher == "Starter"
    assert (replacement.clean_base is None) == reached_on_error
    keeper.update_hit_event(outcomes.HOME_RUN, outs=1)
    assert keeper.take_charges() == [("Starter", 1, int(not reached_on_error)), ("Reliever", 1, 1)]


def test_offline_pitching_line_counts_both_outs_and_a_choice_once():
    import pandas as pd
    pitches = pd.DataFrame({"pitcher_name": ["Sale"]*3, "game_mode": ["gameday"]*3,
        "game_id": ["g1"]*3, "is_terminal": [True]*3,
        "outcome": [outcomes.GROUNDOUT, outcomes.FIELDERS_CHOICE, outcomes.STRIKEOUT],
        "baserunning_outs": [1, 1, None], "runs_scored_on_pitch": [0]*3,
        "earned_runs_on_pitch": [0]*3})
    context = SimpleNamespace(pitches=pitches, games=pd.DataFrame())
    line = metrics.pitching_line(context).iloc[0]
    assert line["outs"] == 4
    assert line["h"] == 0 and line["bf"] == 3
