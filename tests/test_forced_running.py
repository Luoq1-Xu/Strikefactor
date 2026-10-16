"""Required advances cannot be declined or reversed into an occupied bag."""

import random
from types import SimpleNamespace

import pytest

from strikefactor import outcomes
from strikefactor.gameplay import hit_animation as ha
from strikefactor.gameplay.fielding_record import FieldingRecorder
from strikefactor.helpers import Runner, ScoreKeeper


def _animation(mode="manual", bases=(1,), shape="LINER"):
    random.seed(0)
    game = SimpleNamespace(currentouts=0, game_mode="arcade",
                           batter=SimpleNamespace(get_handedness=lambda: "R"))
    return ha.HitAnimation(game, "IN_PLAY", lambda: None, quality=0.85,
        batted_ball_type=shape, ev_mph=95, launch_deg={"GROUNDER": 5, "LINER": 14, "FLY": 32}[shape],
        spray_deg=18, initial_bases=bases, baserunning_mode=mode)


def _finish(anim, step):
    recorder = FieldingRecorder(anim, "force occupancy")
    for t in range(int(anim._elapsed), 40001, step):
        anim.update(t)
        recorder.capture(anim)
        if anim.finished:
            return recorder.record
    pytest.fail("forced running did not settle")


@pytest.mark.parametrize("mode", ["auto", "manual"])
@pytest.mark.parametrize("bases", [(1,), (1, 2), (1, 2, 3)])
@pytest.mark.parametrize("step", [16, 250])
def test_uncaught_liner_cannot_leave_the_forced_runner_on_the_batters_base(mode, bases, step):
    anim = _animation(mode, bases)
    record = _finish(anim, step)
    assert not anim._secured_in_flight
    result = record.running_result
    occupied = [m.final_base for m in result.movements if m.final_base in (1, 2, 3)]
    assert len(occupied) == len(set(occupied))
    keeper = ScoreKeeper()
    keeper.runners = [Runner(base) for base in bases]
    keeper.update_running_play(result)
    live = [r.base for r in keeper.runners if r.onBase]
    assert len(live) == len(set(live))
    for movement in result.movements:
        if movement.runner_id != "B" and movement.out_s is None:
            assert movement.final_base > movement.start_base


@pytest.mark.parametrize("mode", ["auto", "manual"])
def test_a_forced_runner_leaves_after_a_landing_even_when_the_throw_will_beat_them(mode):
    anim = _animation(mode, (1, 2, 3))
    anim.start_time = 0
    anim._elapsed = anim._anim_ms(2.0)
    anim._ball_pos = list(anim._hit_end)
    # A prior hold on an airborne ball must not veto a mandatory advance.
    anim._run_decisions = {(str(base), base) for base in (1, 2, 3)}
    anim._run_recheck_s = {key: 100.0 for key in anim._run_decisions}
    anim._advance_runners(2.0)
    for base in (1, 2, 3):
        route = anim._circuits[str(base)]
        assert route.target_base == base + 1
        assert not route.returning
        assert route.position_at(2.0) == ha.BASE_FT[base]
        assert route.position_at(2.1) != ha.BASE_FT[base]


def test_an_active_force_resumes_an_illegal_return_without_rewriting_the_played_route():
    anim = _animation(shape="GROUNDER")
    route = anim._circuits["1"]
    route.return_to(1, 1.0)
    before = [(t, route.position_at(t)) for t in (0.0, 0.5, 1.0, 1.1)]
    point = route.position_at(1.2)
    anim._advance_runners(1.2)
    route = anim._circuits["1"]
    assert route.target_base == 2 and not route.returning
    assert route.position_at(1.2) == point
    assert all(route.position_at(t) == p for t, p in before)


def test_retiring_the_batter_still_allows_a_legal_return_to_first():
    anim = _animation(shape="GROUNDER")
    anim.start_time = 0
    anim._elapsed = anim._anim_ms(1.0)
    anim._circuits["B"].stopped_at_s = 0.8
    assert anim.retreat_runner()
    anim._advance_runners(1.0)
    route = anim._circuits["1"]
    assert route.target_base == 1 and route.returning


@pytest.mark.parametrize("mode", ["auto", "manual"])
@pytest.mark.parametrize("step", [16, 250])
def test_landed_infield_liner_sends_forced_runner_before_publishing_the_first_base_result(mode, step):
    anim = _animation(mode)
    anim.start_time = 0
    anim._elapsed = anim._secured_at_ms = anim._anim_ms(4.0)
    anim._secured = True
    anim._primary_role = "SS"
    anim.fielders["SS"].pos[:] = ha._to_screen(-50, 110)
    anim._begin_infield_play("SS")
    assert not anim._first_base_retired
    result = _finish(anim, step).running_result
    assert result.batter.final_base == 1
    assert next(m for m in result.movements if m.runner_id == "1").final_base == 2


@pytest.mark.parametrize("mode", ["auto", "manual"])
def test_dropping_a_fly_starts_the_entire_forced_chain_without_a_send(mode):
    anim = _animation(mode, (1, 2, 3), "FLY")
    anim._elapsed = anim._anim_ms(3.0)
    assert all(anim._circuits[str(base)].target_base == base for base in (1, 2, 3))
    anim.fielders["CF"].pos[:] = ha._to_screen(0, 180)
    anim._trigger_muff("CF")
    anim._advance_runners(3.0)
    assert [anim._circuits[str(base)].target_base for base in (1, 2, 3)] == [2, 3, 4]
    assert not any(anim._circuits[str(base)].returning for base in (1, 2, 3))


@pytest.mark.parametrize("mode", ["auto", "manual"])
def test_a_clean_catch_preserves_the_right_to_hold_the_original_bag(mode):
    anim = _animation(mode, (1, 2, 3), "FLY")
    anim._elapsed = anim._anim_ms(3.0)
    anim.fielders["CF"].pos[:] = ha._to_screen(0, 180)
    anim._trigger_in_flight_intercept("CF", tuple(anim.fielders["CF"].pos))
    anim._advance_runners(3.0)
    assert [anim._circuits[str(base)].target_base for base in (1, 2, 3)] == [1, 2, 3]


@pytest.mark.parametrize("mode", ["auto", "manual"])
def test_retiring_a_forced_runner_on_an_uncaught_liner_is_a_choice(mode):
    anim = _animation(mode)
    anim.start_time = 0
    anim._elapsed = anim._secured_at_ms = anim._anim_ms(3.0)
    anim._secured = True
    anim._primary_role = "RF"
    anim.fielders["RF"].pos[:] = ha._to_screen(0, 150)
    anim.fielders["SS"].pos[:] = ha._to_screen(*ha.BASE_FT[2])
    anim._begin_return_play()
    result = _finish(anim, 16).running_result
    assert result.outcome == outcomes.FIELDERS_CHOICE
    assert result.hit_bases == 0 and result.outs_added == 1
    assert result.batter.final_base == 1
    assert result.retirements[0].runner_id == "1" and result.retirements[0].kind == "force"
