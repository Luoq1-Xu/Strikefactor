"""Return targets protect the next base; on-throw advances do not inflate hits."""

import json
import random
from types import SimpleNamespace

import pytest

from strikefactor import outcomes
from strikefactor.gameplay import hit_animation as ha
from strikefactor.gameplay.base_geometry import BASE_FT
from strikefactor.gameplay.fielding_record import FieldingRecorder
from strikefactor.gameplay.gameday_manager import GameDayManager, GameEvent
from strikefactor.gameplay.hit_outcome_manager import HitOutcomeManager
from strikefactor.gameplay.pitch_simulation import PitchSimulation
from strikefactor.gameplay.runner_motion import BatterRun, CircuitRun
from strikefactor.helpers import Runner, ScoreKeeper


def _pickup(*, lead="holding", point=(40, 220), pickup_s=2.9, double=False, triple=False, outs=0):
    random.seed(76)
    game = SimpleNamespace(batter=SimpleNamespace(get_handedness=lambda: "R"), currentouts=outs)
    anim = ha.HitAnimation(game, "IN_PLAY", lambda: None, quality=0.8,
        batted_ball_type="LINER", ev_mph=95, launch_deg=14, initial_bases=(3,))
    anim.runner = BatterRun(4.3)
    anim._circuits["B"] = CircuitRun(anim.runner, 27)
    if double or triple:
        anim._circuits["B"].commit_next(3.85)
    if triple:
        route = anim._circuits["B"]
        route.commit_next(route.arrival_s - 0.45)
        anim._run_decisions.add(("B", 3))
    if lead in ("scored", "hopeless", "home", "retreat", "slow"):
        speed = 20 if lead == "slow" else 25 if lead == "retreat" else 27
        runner = anim._circuits["3"] = CircuitRun(None, speed, start_base=3)
        departure = {"scored": 0.20, "hopeless": pickup_s - 3.7,
                     "home": pickup_s + 0.20, "retreat": pickup_s, "slow": pickup_s}[lead]
        runner.commit_next(departure)
    else:
        # This runner has already elected to hold third, rather than being
        # an active home-plate threat. The old fallback still threw home.
        anim._run_decisions.add(("3", 3))
    anim.start_time = 0
    anim._elapsed = anim._secured_at_ms = anim._anim_ms(pickup_s)
    anim._secured = True
    anim._primary_role = "RF" if point[0] > 0 else "LF"
    anim.fielders[anim._primary_role].pos[:] = ha._to_screen(*point)
    if point[0] > 0:
        anim.fielders["2B"].pos[:] = ha._to_screen(point[0] / 2, point[1] / 2)
    else:
        anim.fielders["2B"].pos[:] = ha._to_screen(*BASE_FT[2])
    anim.fielders["SS"].pos[:] = ha._to_screen(*BASE_FT[2])
    anim.fielders["C"].pos[:] = ha._to_screen(*BASE_FT[4])
    anim._ball = anim._ball_shadow = tuple(anim.fielders[anim._primary_role].pos)
    anim._begin_return_play()
    anim._stand_down_non_primary(keep_at_bag=True)
    return anim


def _finish(anim, step_ms):
    recorder = FieldingRecorder(anim, "single / return")
    t = anim._elapsed
    for _ in range(2000):
        t += step_ms
        anim.update(t)
        recorder.capture(anim)
        if anim.finished:
            return recorder.record
    pytest.fail("return play did not finish")


@pytest.mark.parametrize("lead", ["holding", "scored", "hopeless"])
@pytest.mark.parametrize("step_ms", [16, 250])
def test_do_not_throw_home_at_a_held_scored_or_uncatchable_runner(lead, step_ms):
    anim = _pickup(lead=lead, pickup_s=4.5 if lead == "scored" else 2.9)
    assert anim._return_runner == "B"
    assert anim._return_base == 2
    assert anim._return_legs[-1].target == BASE_FT[2]
    record = _finish(anim, step_ms)
    assert record.outcome == "SINGLE"
    assert record.running_result.hit_bases == 1
    assert record.running_result.batter.final_base == 1
    assert record.running_result.batter_on_throw_base is None


@pytest.mark.parametrize("step_ms", [16, 250])
def test_real_direct_home_play_can_concede_second_but_still_scores_a_single(step_ms):
    anim = _pickup(lead="home", point=(-200, 250))
    assert anim._return_base == 4
    assert len(anim._return_legs) == 1
    release_s = anim._return_legs[0].release_s
    assert anim._hit_defense_s[2] < anim._circuits["B"].projected_next(release_s)
    record = _finish(anim, step_ms)
    result = record.running_result
    assert result.outcome == "SINGLE"
    assert result.hit_bases == 1
    assert result.batter.final_base == result.batter_on_throw_base == 2
    assert result.batter.on_throw_bases == (2,)
    event = next(e for e in record.events if e.label == "ADVANCE ON THROW 2B")
    assert event.time_ms >= anim._anim_ms(release_s)
    touched = next(e for e in record.events if e.runner_id == "B" and e.base == 2
                   and e.label.startswith("BASE TOUCHED"))
    assert record.sample(touched.time_ms).runner.pos == pytest.approx(ha.BASES["2B"])
    assert record.running_result == result


@pytest.mark.parametrize("step_ms", [16, 250])
def test_cutoff_is_not_already_committed_home_and_can_stop_the_free_second(step_ms):
    anim = _pickup(lead="retreat", point=(35, 205))
    first, old_home = anim._return_legs
    assert anim._return_base == 4
    assert old_home.target == BASE_FT[4]
    record = _finish(anim, step_ms)
    assert anim._return_legs[0] == first
    assert anim._return_legs[-1].target == BASE_FT[2]
    assert anim._return_runner == "B"
    assert record.outcome == "SINGLE"
    assert record.running_result.batter.final_base == 1
    assert any(e.label == "CUTOFF REDIRECT 2B" for e in record.events)
    assert not any(e.label == "THROW ARRIVAL" and e.role == "C" for e in record.events)
    assert not any(e.label == "ADVANCE ON THROW 2B" for e in record.events)
    received = record.sample(anim._anim_ms(anim._return_legs[-1].arrival_s))
    assert ha._to_field_ft(received.shadow) == pytest.approx(BASE_FT[2])


def test_a_genuine_double_remains_a_double_with_a_runner_holding_third():
    anim = _pickup(point=(0, 330), pickup_s=5.7, double=True)
    record = _finish(anim, 16)
    result = record.running_result
    assert result.outcome == "DOUBLE"
    assert result.hit_bases == 2
    assert result.batter.final_base == 2
    assert not result.batter.on_throw_bases
    assert result.batter_on_throw_base is None


def test_preceding_runner_put_out_at_home_precludes_three_base_hit_credit():
    anim = _pickup(lead="slow", point=(-200, 250), pickup_s=9.0, triple=True)
    record = _finish(anim, 16)
    result = record.running_result
    leading = next(m for m in result.movements if m.runner_id == "3")
    assert leading.out_s is not None
    assert result.batter.final_base == 3
    assert result.batter.on_throw_bases == (3,)
    assert result.outcome == "DOUBLE"
    assert result.hit_bases == 2
    assert result.running_outs == 1


def test_on_throw_advances_keep_earned_run_positions_and_gameday_hit_credit():
    anim = _pickup(lead="home", point=(-200, 250))
    result = _finish(anim, 16).running_result
    sk = ScoreKeeper()
    sk.set_pitcher("starter")
    sk.runners = [Runner(3, "previous")]
    play = sk.update_running_play(result)
    assert play.batter_on_throw_base == 2
    batter = sk.basesfilled[2]
    assert batter.base == batter.clean_base == 2
    gm = GameDayManager(difficulty="amateur", starter_name="sale")
    gm.record_player_at_bat(result.outcome, runs_scored=play.runs,
                           play=play, charges=sk.take_charges())
    event = GameEvent.from_dict(gm.event_log[-1].to_dict())
    assert event.result == "SINGLE"
    assert event.batter_on_throw_base == 2
    assert "SINGLE · TO 2B ON THROW" in str(event)
    # This earned advance must not leave the batter behind in the clean
    # reconstruction and incorrectly make his later run unearned.
    sk.update_hit_event("DOUBLE", outs=1)
    assert sk.last_play.runs == 1
    assert sk.take_charges() == [("starter", 1, 1)]


def test_single_on_throw_finalizes_as_a_single_while_persisting_second_base():
    anim = _pickup(lead="home", point=(-200, 250))
    _finish(anim, 16)
    sk = ScoreKeeper()
    sk.runners = [Runner(3)]
    manager = object.__new__(HitOutcomeManager)
    manager.score_keeper = sk
    banners, hits = [], []
    game = SimpleNamespace(currentouts=0, hits=0, last_pitch_information=[], ball=(640, 400),
        in_gameday_mode=False, scoreKeeper=sk, hit_outcome_manager=manager,
        field_renderer=SimpleNamespace(record_at_bat=lambda: None,
                                       record_hit=lambda *a, **kw: hits.append(kw["hit_type"])),
        ui_manager=SimpleNamespace(show_banner=banners.append))
    sim = object.__new__(PitchSimulation)
    sim.game, sim.hit_animation, sim.new_entry = game, anim, {}
    sim._finalize_batted_ball()
    assert hits == ["SINGLE"]
    assert game.hits == 1
    assert sim.outcome == sim.new_entry["isHit"] == "SINGLE"
    assert sim.batter_final_base == 2
    assert banners == ["SINGLE · TO 2B ON THROW"]
    saved = json.loads(sim.running_play_json)
    assert saved["hit_bases"] == 1
    assert saved["movements"][0]["final_base"] == 2
    assert saved["movements"][0]["on_throw_bases"] == [2]


def test_old_gameday_events_default_to_no_on_throw_annotation():
    event = GameEvent.from_dict(dict(inning=1, is_top=False, batter_name="Player",
                                   pitcher_name="Sale", result="DOUBLE"))
    assert event.batter_on_throw_base is None
    assert "ON THROW" not in str(event)
    assert event.result == outcomes.DOUBLE
