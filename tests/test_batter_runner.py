"""First-base calls must agree with possession, bag contact and runner motion."""

import math
import random
from dataclasses import replace
from types import SimpleNamespace

import pygame
import pytest

from strikefactor.gameplay import hit_animation as ha
from strikefactor.gameplay import infield_timing as it
from strikefactor.gameplay.fielding_record import FieldingRecorder
from strikefactor.gameplay.runner_motion import BaseApproach, BatterRun, CircuitRun


@pytest.mark.parametrize("arrival_s", [3.55, 4.2, 4.3, 5.0])
def test_runner_accelerates_and_touches_the_real_bag_at_the_fitted_time(arrival_s):
    run = BatterRun(arrival_s)
    assert run.position_at(0) == (0.0, 0.0)
    assert run.position_at(run.start_delay_s) == (0.0, 0.0)
    assert math.dist((0, 0), run.position_at(arrival_s - 0.001)) < 90
    assert run.position_at(arrival_s) == it.FIRST_BASE_FT
    assert math.dist((0, 0), run.position_at(arrival_s + 0.1)) > 90
    # The standing start is slower than a later interval of the same length.
    start = math.dist(run.position_at(0.3), run.position_at(0.5))
    cruise = math.dist(run.position_at(2.3), run.position_at(2.5))
    assert 0 < start < cruise


def test_average_runner_is_shown_in_real_time_with_the_rest_of_the_play(monkeypatch):
    monkeypatch.setattr(random, "gauss", lambda mean, sigma: mean)
    game = SimpleNamespace(batter=SimpleNamespace(get_handedness=lambda: "R"))
    anim = ha.HitAnimation(game, "IN_PLAY", lambda: None, quality=0.8,
                           batted_ball_type="GROUNDER", ev_mph=95.0)
    assert anim._anim_ms(anim.runner.arrival_s) == pytest.approx(4300.0)
    assert not anim.runner_frame(4299).reached_first
    assert anim.runner_frame(4300).reached_first
    assert anim.runner_frame(4300).pos == pytest.approx(ha.BASES["1B"])
    assert anim.duration_ms == pytest.approx(anim.flight_time_s * 1000, abs=1.0)


@pytest.mark.parametrize("distance_ft", [0, 0.25, 8, 100])
@pytest.mark.parametrize("initial_fraction", [0.0, 0.6, 1.0])
def test_defender_approach_arrival_is_the_same_as_its_position(distance_ft, initial_fraction):
    path = BaseApproach((0, 0), (distance_ft, 0), 1.0, 27.0, 0.5, initial_fraction)
    assert path.position_at(0.9) == (0.0, 0.0)
    assert path.position_at(path.arrival_s) == (distance_ft, 0)
    assert path.position_at(path.arrival_s + 5) == (distance_ft, 0)
    if distance_ft:
        assert path.position_at(path.arrival_s - 0.0001)[0] < distance_ft
        assert path.duration_s >= distance_ft / 27.0


def _timing(misplay_s=0.0):
    return it.resolve_infield_play(95.0, (-50.0, 120.0), 130.0,
                                  ball_to_glove_s=1.0, misplay_s=misplay_s)


@pytest.mark.parametrize("margin_s,verdict", [(-0.001, "HIT"), (0.0, "HIT"), (0.001, "OUT")])
def test_arrival_order_decides_the_verdict_even_if_probability_says_otherwise(margin_s, verdict):
    timing = it.schedule_first_base(_timing(), 4.0)
    timing = replace(timing, runner_s=timing.defense_s + margin_s,
                     p_out=0.0 if verdict == "OUT" else 1.0)
    assert it.timed_verdict(timing) == verdict


def test_cover_wait_can_absorb_a_bobble_without_inventing_an_error():
    base = _timing(misplay_s=0.7)
    timing = it.schedule_first_base(base, 3.0, cover_at_s=4.0)
    assert timing.defense_s == pytest.approx(4.0)
    assert timing.clean_defense_s == timing.defense_s
    assert it.timed_verdict(timing) == "HIT"


def test_bobble_is_an_error_only_when_the_clean_schedule_beats_the_runner():
    timing = it.schedule_first_base(_timing(misplay_s=0.7), 3.0, throw_flight_s=1.0)
    assert timing.clean_defense_s < timing.runner_s <= timing.defense_s
    assert it.timed_verdict(timing) == "ERROR"
    assert it.timed_verdict(replace(timing, runner_s=5.0)) == "OUT"
    assert it.timed_verdict(replace(timing, runner_s=2.0)) == "HIT"


def _play_at_first(monkeypatch, margin_s, *, carry=False, cover_delay=False, scale=1.25, misplay_s=0.0,
                   mode="auto", outs=0, bases=()):
    random.seed(14)
    game = SimpleNamespace(batter=SimpleNamespace(get_handedness=lambda: "R"), currentouts=outs)
    anim = ha.HitAnimation(game, "IN_PLAY", lambda: None, quality=0.8,
                           batted_ball_type="GROUNDER", spray_deg=18.0, ev_mph=95.0,
                           baserunning_mode=mode, initial_bases=bases)
    anim.time_scale = scale
    anim.start_time = 0
    anim._elapsed = anim._secured_at_ms = anim._anim_ms(2.0)
    anim._secured = True
    role = "1B" if carry else "SS"
    anim._primary_role = role
    anim._misplay_s = misplay_s
    if misplay_s:
        anim._misplay_kind = "BOBBLE"
        anim._misplay_role = role
    catcher = anim.fielders[role]
    origin = (it.FIRST_BASE_FT[0] - 8, it.FIRST_BASE_FT[1]) if carry else (-50.0, 120.0)
    catcher.pos[:] = ha._to_screen(*origin)
    catcher.base_max_speed = 27.0
    catcher.accel_time_s = 0.5
    catcher.current_speed_frac = 0.0
    anim._ball = anim._ball_shadow = tuple(catcher.pos)
    cover = anim.fielders["1B"]
    if not carry:
        cover.pos[:] = ha._to_screen(it.FIRST_BASE_FT[0] + (48 if cover_delay else 0),
                                    it.FIRST_BASE_FT[1])
        cover.break_delay_s = cover.break_delay_ms = 0.0
        cover.base_max_speed = 27.0
        cover.accel_time_s = 0.5
        cover.current_speed_frac = 0.0
    monkeypatch.setattr(it, "release_time_s", lambda *a, **kw: 0.8 + a[4])
    if carry:
        defense_s = 2.0 + misplay_s + BaseApproach(origin, it.FIRST_BASE_FT, 0, 27.0, 0.5).duration_s
    else:
        flight_s = math.dist(origin, it.FIRST_BASE_FT) / anim.defense.throw_fts
        cover_at = 2.0 + (BaseApproach(ha._to_field_ft(cover.pos), it.FIRST_BASE_FT,
                                    0, 27.0, 0.5).duration_s)
        defense_s = max(2.8 + misplay_s + flight_s, cover_at)
    anim.runner = BatterRun(defense_s + margin_s)
    anim._circuits["B"] = CircuitRun(anim.runner, 27)
    anim._begin_infield_play(role)
    assert anim.play_timing.defense_s == pytest.approx(defense_s)
    return anim


@pytest.mark.parametrize("margin_s", [-0.8, -0.005, 0.0, 0.005, 0.8])
@pytest.mark.parametrize("mode", ["auto", "manual"])
@pytest.mark.parametrize("outs", [0, 2])
@pytest.mark.parametrize("step_ms", [16, 250])
def test_ground_ball_batter_runs_through_first_even_after_an_out_or_the_third_out(
        monkeypatch, margin_s, mode, outs, step_ms):
    anim = _play_at_first(monkeypatch, margin_s, mode=mode, outs=outs, bases=(2,))
    recorder = FieldingRecorder(anim, "ground-ball run-through")
    finish_s = anim.runner.arrival_s + ha.GO_CATCH_HOLD_S
    t = anim._elapsed
    while not anim.finished:
        t += step_ms
        anim.update(t)
        recorder.capture(anim)
        if t < anim._anim_ms(finish_s):
            assert not anim.can_continue_early
    record = recorder.record
    assert record.duration_ms >= anim._anim_ms(finish_s)
    first_ms = anim._anim_ms(anim.runner.arrival_s)
    assert record.sample(first_ms).runner.pos == pytest.approx(ha.BASES["1B"])
    frame = record.frames[-1]
    assert math.dist((0, 0), ha._to_field_ft(frame.runner.pos)) > 90.0
    assert frame.runner.reached_first
    batter = record.running_result.batter
    if margin_s > 0:
        assert frame.runner.state == "out"
        assert batter.out_s == anim.play_timing.defense_s
        assert batter.final_base is None and not batter.touches
        if outs == 2:
            assert anim._inning_end_s == batter.out_s
    else:
        assert batter.out_s is None and batter.final_base == 1
        assert batter.touches == ((1, anim.runner.arrival_s),)


def test_sending_after_a_ground_ball_run_through_preserves_actual_position_and_first_touch():
    route = CircuitRun(BatterRun(4.3), 27, run_through_first=True)
    before = [(t, route.position_at(t)) for t in (4.2, 4.3, 4.4, 4.5)]
    decision_s = 4.6
    point = route.position_at(decision_s)
    assert math.dist((0, 0), point) > 90.0
    preview = route.preview_next(decision_s)
    assert route.commit_next(decision_s)
    assert route.position_at(decision_s) == point
    assert all(route.position_at(t) == p for t, p in before)
    assert route.arrival_s == preview.arrival_s
    assert route.touches(decision_s) == ((1, 4.3),)
    assert route.position_at(route.arrival_s) == it.BASE_FT[2]


@pytest.mark.parametrize("margin_s", [-0.005, 0.005])
@pytest.mark.parametrize("step_ms", [8, 16, 85, 250])
@pytest.mark.parametrize("scale", [0.75, 1.25, 2.0])
def test_close_play_and_replay_preserve_arrival_order_at_any_frame_rate(monkeypatch, margin_s, step_ms, scale):
    anim = _play_at_first(monkeypatch, margin_s, scale=scale)
    recorder = FieldingRecorder(anim, "close play")
    t = anim._elapsed
    while not anim.finished:
        t += step_ms
        anim.update(t)
        recorder.capture(anim)
    record = recorder.record
    assert record is not None
    assert record.outcome == ("GROUNDOUT" if margin_s > 0 else "SINGLE")
    runner_event = next(e for e in record.events if e.label == "RUNNER AT FIRST")
    defense_event = next(e for e in record.events if e.label == "DEFENSE AT FIRST")
    assert (runner_event.time_ms > defense_event.time_ms) == (margin_s > 0)
    assert runner_event.time_ms == anim._anim_ms(anim.runner.arrival_s)
    assert defense_event.time_ms == anim._anim_ms(anim.play_timing.defense_s)
    runner_frame = record.sample(runner_event.time_ms)
    assert runner_frame.runner.reached_first
    assert runner_frame.runner.pos == pytest.approx(ha.BASES["1B"])
    defense_frame = record.sample(defense_event.time_ms)
    assert defense_frame.ball == pytest.approx(ha.BASES["1B"])
    assert next(f for f in defense_frame.fielders if f.role == anim._cover_role).pos == pytest.approx(ha.BASES["1B"])
    earlier = record.sample(min(runner_event.time_ms, defense_event.time_ms))
    assert earlier.first_base_call[0] == ("OUT" if margin_s > 0 else "SAFE")
    between = record.sample((runner_event.time_ms + defense_event.time_ms) / 2)
    assert between.runner.reached_first == (margin_s < 0)
    if margin_s > 0:
        assert between.ball == pytest.approx(ha.BASES["1B"])
    else:
        assert math.dist(between.ball, ha.BASES["1B"]) > 0
    assert record.play_margin_s == pytest.approx(margin_s)


@pytest.mark.parametrize("margin_s", [-0.02, 0.02])
def test_unassisted_play_requires_actual_bag_contact(monkeypatch, margin_s):
    anim = _play_at_first(monkeypatch, margin_s, carry=True)
    assert anim._go_throw_start_ms is None
    assert anim.play_timing.throw_flight_s > 0  # eight feet is a carry, not a free out
    anim.update(anim._anim_ms(anim.play_timing.defense_s - 0.001))
    assert math.dist(anim.fielders["1B"].pos, ha.BASES["1B"]) > 0
    anim.update(anim._anim_ms(anim.play_timing.defense_s))
    assert anim.fielders["1B"].pos == pytest.approx(ha.BASES["1B"])
    assert anim._ball == pytest.approx(ha.BASES["1B"])
    assert anim.classified_outcome == ("GROUNDOUT" if margin_s > 0 else "SINGLE")


def test_late_cover_delays_the_throw_and_the_same_defensive_clock(monkeypatch):
    anim = _play_at_first(monkeypatch, -0.01, cover_delay=True)
    assert anim.play_timing.release_s > 0.8
    assert anim.classified_outcome == "SINGLE"
    anim.update(anim._go_throw_arrive_ms)
    assert anim.fielders[anim._cover_role].pos == pytest.approx(ha.BASES["1B"])
    assert anim._ball == pytest.approx(ha.BASES["1B"])


def test_even_a_sub_millisecond_toss_reaches_the_glove_on_its_arrival_frame(monkeypatch):
    anim = _play_at_first(monkeypatch, 0.01)
    # A defender nearly on the bag feeds an already stationed receiver.
    anim.fielders["SS"].pos[:] = ha._to_screen(it.FIRST_BASE_FT[0] - 0.01, it.FIRST_BASE_FT[1])
    anim._begin_infield_play("SS")
    assert 0 < anim._go_throw_ms < 1
    anim.update(anim._go_throw_arrive_ms)
    assert anim._ball == pytest.approx(ha.BASES["1B"], abs=1e-9)


@pytest.mark.parametrize("carry", [False, True])
@pytest.mark.parametrize("margin_s,outcome,is_error", [
    (-0.1, "REACHED ON ERROR", True), (0.1, "GROUNDOUT", False), (-0.4, "SINGLE", False),
])
def test_visible_bobble_is_scored_against_the_same_clean_runner(monkeypatch, carry, margin_s, outcome, is_error):
    anim = _play_at_first(monkeypatch, margin_s, carry=carry, misplay_s=0.3)
    assert anim.classified_outcome == outcome
    assert anim.is_error == is_error
    assert anim.play_timing.runner_s == anim.runner.arrival_s
    anim.update(anim._go_done_ms)
    assert anim.presentation_frame().first_base_call[0] == ("OUT" if margin_s > 0 else "SAFE")
    if is_error:
        assert anim.error_out == "GROUNDOUT"
        assert anim._error_role == anim._primary_role


@pytest.mark.parametrize("carry", [False, True])
def test_clear_out_retains_the_batters_run_through_before_finishing(monkeypatch, carry):
    anim = _play_at_first(monkeypatch, 0.8, carry=carry)
    recorder = FieldingRecorder(anim, "clear out")
    made_ms = anim._anim_ms(anim.play_timing.defense_s)
    anim.update(made_ms - 1)
    recorder.capture(anim)
    assert not anim.skip_remaining()
    anim.update(made_ms)
    recorder.capture(anim)
    before = anim.presentation_frame()
    assert not anim.can_continue_early
    assert not before.runner.reached_first
    assert not anim.skip_remaining()
    assert not anim.finished
    first_ms = anim._anim_ms(anim.runner.arrival_s)
    anim.update(first_ms)
    recorder.capture(anim)
    assert anim.presentation_frame().runner.pos == pytest.approx(ha.BASES["1B"])
    assert not anim.skip_remaining()
    finish_ms = anim._anim_ms(anim.runner.arrival_s + ha.GO_CATCH_HOLD_S)
    anim.update(finish_ms)
    recorder.capture(anim)
    assert anim.finished
    assert recorder.record.duration_ms == finish_ms
    assert recorder.record.outcome == "GROUNDOUT"
    assert recorder.record.events[-1].label == "END"
    assert next(e.time_ms for e in recorder.record.events if e.label == "RUNNER AT FIRST") == first_ms
    assert math.dist((0, 0), ha._to_field_ft(recorder.record.frames[-1].runner.pos)) > 90.0
    assert not anim.skip_remaining()


@pytest.mark.parametrize("margin_s", [-0.1, 0.0, 0.1])
def test_safe_and_close_plays_require_the_full_race(monkeypatch, margin_s):
    anim = _play_at_first(monkeypatch, margin_s)
    anim.update(anim._anim_ms(anim.play_timing.defense_s))
    assert not anim.can_continue_early
    assert not anim.skip_remaining()
    assert not anim.finished
    anim.update(anim._go_done_ms)
    assert anim.finished


@pytest.mark.parametrize("event", [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE),
                                   pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(640, 640))])
@pytest.mark.parametrize("margin_s,phase,can_finish", [(0.8, "before_out", False),
    (0.8, "out", False), (0.1, "out", False), (0.8, "through", True)])
def test_continue_input_waits_for_run_through_and_finalizes_once(monkeypatch, event, margin_s, phase, can_finish):
    from strikefactor.gameplay.pitch_simulation import PitchSimulation

    anim = _play_at_first(monkeypatch, margin_s)
    calls = []
    anim.on_complete = lambda: calls.append("finalize")
    game = anim.game
    game.screen = pygame.Surface((1280, 720))
    game.last_fielding_play = None
    game.banner = SimpleNamespace(update=lambda dt: None, draw=lambda: None)
    game.flip_display = lambda: None
    game.key_binding_manager = SimpleNamespace(get_key_for_action=lambda action: None)
    sim = object.__new__(PitchSimulation)
    sim.game, sim.hit_animation = game, anim
    sim._fielding_recorder = FieldingRecorder(anim, "clear out")
    sim._publish_review = lambda: calls.append("publish")
    sim._finish_pitch = lambda: calls.append("finish")
    monkeypatch.setattr(pygame.event, "get", lambda: [event, event])
    made_ms = anim._anim_ms(anim.play_timing.defense_s)
    current_ms = {"before_out": made_ms-1, "out": made_ms,
                  "through": anim._anim_ms(anim.runner.arrival_s + ha.GO_CATCH_HOLD_S)}[phase]
    sim._handle_hit_animation_phase(current_ms, 0.016)
    if can_finish:
        assert calls == ["finalize", "publish", "finish"]
        record = game.last_fielding_play
        assert record is sim._fielding_recorder.record
        assert record.frames[-1].runner.reached_first
        assert record.outcome == "GROUNDOUT"
        assert anim.banner_fired
        sim._complete_hit_animation()
        assert calls == ["finalize", "publish", "finish"]
    else:
        assert not calls
        assert not anim.finished
        assert not anim.banner_fired
        assert game.last_fielding_play is None


def test_caught_air_ball_stops_runner_and_never_makes_a_first_base_call(monkeypatch):
    anim = _play_at_first(monkeypatch, -0.01)
    # Use a fresh airborne play so no throw/carry schedule is present.
    anim = ha.HitAnimation(anim.game, "IN_PLAY", lambda: None, quality=0.8,
                           batted_ball_type="FLY", ev_mph=85, launch_deg=32)
    anim.update(0)
    anim._elapsed = anim._anim_ms(1.5)
    anim._trigger_in_flight_intercept("CF", tuple(anim.fielders["CF"].pos))
    caught = anim.presentation_frame().runner
    anim.update(anim._go_done_ms)
    assert anim.presentation_frame().runner == caught
    assert anim.presentation_frame().first_base_call is None
    assert anim.classified_outcome == "FLYOUT"
