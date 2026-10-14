"""Manual controls must not reveal a home run before the ball clears the wall."""

import random
from types import SimpleNamespace

import pytest

from strikefactor import outcomes
from strikefactor.gameplay import hit_animation as ha
from strikefactor.gameplay.base_geometry import BASE_FT
from strikefactor.gameplay.fielding_record import FieldingRecorder


def _animation(outcome=outcomes.HOME_RUN, *, mode="manual", bases=(), outs=0, hand="R"):
    random.seed(21)
    game = SimpleNamespace(batter=SimpleNamespace(get_handedness=lambda: hand), currentouts=outs)
    animation = ha.HitAnimation(game, outcome, lambda: None, quality=0.9,
        batted_ball_type="FLY", ev_mph=110, launch_deg=32, spray_deg=18,
        initial_bases=bases, baserunning_mode=mode, send_key_name="J", retreat_key_name="K")
    animation.update(0)
    return animation


@pytest.mark.parametrize("bases,outs", [((), 0), ((1,), 0), ((1, 2, 3), 0), ((1, 2, 3), 2)])
@pytest.mark.parametrize("hand", ["R", "L"])
def test_home_run_keeps_the_same_early_controls_and_routes_as_a_fly_ball(bases, outs, hand):
    homer = _animation(bases=bases, outs=outs, hand=hand)
    fly = _animation("IN_PLAY", bases=bases, outs=outs, hand=hand)
    for time_ms in (400, 2000):
        homer.update(time_ms)
        fly.update(time_ms)
        assert not homer.banner_ready
        assert homer.presentation_frame().send_control == fly.presentation_frame().send_control
        for rid, route in homer._circuits.items():
            ordinary = fly._circuits[rid]
            assert route.target_base == ordinary.target_base
            assert route.position_at(time_ms / 1000) == pytest.approx(ordinary.position_at(time_ms / 1000))
    if not bases or outs == 2:
        assert homer.presentation_frame().send_control is not None
        assert homer.presentation_frame().send_control[4] == "J"


@pytest.mark.parametrize("step_ms", [16, 250])
@pytest.mark.parametrize("mode", ["auto", "manual"])
@pytest.mark.parametrize("bases,outs", [((), 0), ((1, 2, 3), 0), ((1, 2, 3), 2)])
def test_fence_confirmation_hides_controls_and_sends_every_runner_home(step_ms, mode, bases, outs):
    anim = _animation(mode=mode, bases=bases, outs=outs)
    recorder = FieldingRecorder(anim, "home run running")
    while not anim.banner_ready:
        anim.update(anim._elapsed + step_ms)
        recorder.capture(anim)
        if not anim.banner_ready:
            assert not ha._point_outside_wall(anim._ball_shadow)
            assert anim._hr_confirmed_s is None
    assert not anim.finished
    assert anim._hr_confirmed_s == pytest.approx(anim._hr_fence_ms / (1000 * anim.time_scale))
    assert ha._point_outside_wall(anim._ball_shadow)
    assert anim.baserunning.closed
    assert anim.baserunning.reason == "home run confirmed"
    assert anim.presentation_frame().send_control is None
    assert all(route.target_base == 4 for route in anim._circuits.values())
    assert not anim.send_runner()
    assert not anim.retreat_runner()
    for _ in range(2000):
        anim.update(anim._elapsed + step_ms)
        recorder.capture(anim)
        if anim.finished:
            break
    assert anim.finished
    record = recorder.record
    confirmed = next(e for e in record.events if e.label == "HOME RUN CONFIRMED")
    assert record.sample(confirmed.time_ms).send_control is None
    assert record.outcome == outcomes.HOME_RUN
    for rid, route in anim._circuits.items():
        frame = anim.runner_frame(anim._elapsed) if rid == "B" else anim._circuit_frame(rid, anim._elapsed / 1000)
        assert frame.state == "scored"
        assert frame.pos == pytest.approx(ha.HOME)
        assert [base for base, _ in route.touches()] == list(range(route.start_base + 1, 5))
        assert route.position_at(route.arrival_s) == BASE_FT[4]


def test_confirmation_cancels_a_queued_send_and_preserves_the_played_route():
    anim = _animation()
    anim.update(400)
    assert anim.send_runner()
    assert anim.baserunning.pending_base == 2
    anim.update(anim._hr_fence_ms - 1)
    assert not anim.banner_ready
    assert anim.presentation_frame().send_control is not None
    # Queue another optional base while the second-base leg is underway.
    assert anim.send_runner()
    assert anim.baserunning.pending_base == 3
    route = anim._circuits["B"]
    observed = [(t, route.position_at(t), route.touches(t)) for t in (0.4, 2.0, 3.0)]
    anim.update(anim._hr_fence_ms)
    assert anim.banner_ready
    assert anim.baserunning.pending_base is None
    assert anim.baserunning.commands[-1]["status"] == "cancelled"
    assert anim.baserunning.commands[-1]["reason"] == "home run confirmed"
    assert route.target_base == 4
    for time_s, position, touches in observed:
        assert route.position_at(time_s) == pytest.approx(position)
        assert route.touches(time_s) == touches


def test_confirmation_turns_a_retreating_runner_home_without_a_position_jump():
    anim = _animation(bases=(2,), outs=2)
    anim.update(400)
    assert anim.retreat_runner()
    assert anim._circuits["2"].returning
    anim.update(anim._hr_fence_ms - 1)
    now_s = anim._elapsed / 1000
    observed = {rid: route.position_at(now_s) for rid, route in anim._circuits.items()}
    anim.update(anim._hr_fence_ms)
    assert anim.banner_ready
    for rid, route in anim._circuits.items():
        assert not route.returning
        assert route.target_base == 4
        assert route.position_at(now_s) == pytest.approx(observed[rid])
        assert route.position_at(route.arrival_s) == BASE_FT[4]
