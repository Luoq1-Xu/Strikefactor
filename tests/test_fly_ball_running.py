"""A catch creates a tag-up race, not free running while a relay assembles."""

import random
from types import SimpleNamespace

import pygame
import pytest

from strikefactor.gameplay import defense, extra_bases
from strikefactor.gameplay import hit_animation as ha
from strikefactor.gameplay.base_geometry import BASE_FT
from strikefactor.gameplay.fielding_record import FieldingRecorder
from strikefactor.gameplay.pitch_simulation import PitchSimulation
from strikefactor.helpers import Runner, ScoreKeeper
from strikefactor.key_binding_manager import KeyAction


def _catch(point, *, bases=(1, 2, 3), shape="FLY", holder="CF", outs=0, ready_cutoff=False):
    random.seed(21)
    game = SimpleNamespace(batter=SimpleNamespace(get_handedness=lambda: "R"), currentouts=outs)
    anim = ha.HitAnimation(game, "IN_PLAY", lambda: None, quality=0.85,
        batted_ball_type=shape, ev_mph=90, launch_deg=60 if shape == "POP_UP" else 32,
        initial_bases=bases)
    anim.start_time = 0
    anim._elapsed = anim._anim_ms(4.0)
    if ready_cutoff:
        target = BASE_FT[min(4, max(bases) + 1)]
        cutoff = tuple((a + b) / 2 for a, b in zip(point, target))
        anim.fielders["2B"].pos[:] = ha._to_screen(*cutoff)
    anim.fielders[holder].pos[:] = ha._to_screen(*point)
    anim._trigger_in_flight_intercept(holder, tuple(anim.fielders[holder].pos))
    return anim


def _finish(anim, step_ms=16):
    recorder = FieldingRecorder(anim, "tag up")
    t = anim._elapsed
    for _ in range(2000):
        t += step_ms
        anim.update(t)
        recorder.capture(anim)
        if anim.finished:
            return recorder.record
    pytest.fail("caught-ball return did not settle")


@pytest.mark.parametrize("shape", ["FLY", "POP_UP"])
@pytest.mark.parametrize("step_ms", [16, 250])
def test_shallow_clean_catches_hold_runners_and_return_promptly(shape, step_ms):
    anim = _catch((0, 180), shape=shape)
    record = _finish(anim, step_ms)
    result = record.running_result
    assert result.outs_added == 1
    for move in result.movements:
        if move.runner_id != "B":
            assert move.final_base == move.start_base
            assert not move.touches
    assert not any(e.label == "ADVANCE" for e in result.events)
    release = anim._return_legs[0].release_s
    assert release - 4.0 == pytest.approx(extra_bases.OF_RELEASE_S * anim.defense.release_scale)
    sk = ScoreKeeper()
    sk.runners = [Runner(base) for base in (1, 2, 3)]
    assert sk.update_running_play(result).runs == 0


def test_late_cutoff_does_not_delay_an_outfielders_available_direct_throw():
    anim = _catch((0, 340), bases=(3,))
    for role in ("2B", "SS", "P"):
        anim.fielders[role].pos[:] = ha._to_screen(-180, 20)
        anim.fielders[role].base_max_speed = 15
    legs, approaches = anim._return_schedule(4, (0, 340), 4.0)
    assert len(legs) == 1
    assert legs[0].thrower == "CF"
    assert legs[0].release_s == pytest.approx(5.05)
    assert approaches[legs[0].receiver].arrival_s <= legs[0].arrival_s


def test_second_base_uses_the_available_infielder_instead_of_waiting_for_the_other():
    anim = _catch((0, 200), bases=(1,))
    anim.fielders["SS"].pos[:] = ha._to_screen(-160, 300)
    anim.fielders["SS"].base_max_speed = 15
    anim.fielders["2B"].pos[:] = ha._to_screen(*BASE_FT[2])
    legs, _ = anim._return_schedule(2, (0, 200), 4.0)
    assert legs[-1].receiver == "2B"
    assert legs[0].release_s == pytest.approx(5.05)


@pytest.mark.parametrize("step_ms", [16, 250])
def test_deep_fly_allows_one_tag_up_from_second_without_rounding_home(step_ms):
    anim = _catch((0, 370), bases=(2,), ready_cutoff=True)
    record = _finish(anim, step_ms)
    result = record.running_result
    runner = next(m for m in result.movements if m.runner_id == "2")
    assert runner.final_base == 3
    assert [base for base, _ in runner.touches] == [3]
    assert runner.touches[0][1] > 4.0
    assert not any(e.label == "ADVANCE" and e.base == 4 for e in result.events)
    assert len([e for e in result.events if e.label == "ADVANCE"]) == 1
    at_third = record.sample(anim._anim_ms(runner.touches[0][1]))
    assert at_third.runners[0].pos == pytest.approx(ha.BASES["3B"])
    sk = ScoreKeeper()
    sk.runners = [Runner(2)]
    assert sk.update_running_play(result).runs == 0
    assert sk.isRunnerOnBase(3)


def test_deep_fly_still_scores_a_legitimate_sacrifice_from_third():
    anim = _catch((0, 370), bases=(3,), ready_cutoff=True)
    record = _finish(anim)
    result = record.running_result
    sk = ScoreKeeper()
    sk.runners = [Runner(3)]
    play = sk.update_running_play(result)
    assert (play.runs, play.rbi, play.sacrifice_fly) == (1, 1, True)
    runner = next(m for m in result.movements if m.runner_id == "3")
    assert runner.scored_s < anim._return_legs[-1].arrival_s


def test_third_out_catch_stops_runners_who_already_broke_on_contact():
    anim = _catch((0, 370), bases=(2, 3), outs=2)
    assert all(route.position_at(1.0) != BASE_FT[route.start_base]
               for rid, route in anim._circuits.items() if rid != "B")
    assert anim.can_continue_early
    assert not anim._return_legs
    record = _finish(anim)
    assert record.running_result.outs_added == 1
    assert not any(e.label == "ADVANCE" for e in record.running_result.events)
    assert all(not m.touches for m in record.running_result.movements if m.runner_id != "B")
    assert record.frames[-1].runners == record.frames[0].runners


@pytest.mark.parametrize("hand", ["L", "R"])
@pytest.mark.parametrize("level", ["sandlot", "league", "gold_glove"])
@pytest.mark.parametrize("base", [1, 2])
@pytest.mark.parametrize("shape,angle,ev", [("FLY", 32, 75), ("POP_UP", 60, 85)])
def test_live_shallow_catches_hold_first_and_second_across_defenses(monkeypatch, hand, level, base, shape, angle, ev):
    monkeypatch.setattr(defense, "roll_misplay", lambda *a, **kw: None)
    random.seed(21)
    game = SimpleNamespace(batter=SimpleNamespace(get_handedness=lambda: hand))
    anim = ha.HitAnimation(game, "IN_PLAY", lambda: None, quality=0.85,
        batted_ball_type=shape, ev_mph=ev, launch_deg=angle, spray_deg=18,
        initial_bases=(base,), defense=defense.profile_for(level))
    anim.update(0)
    record = _finish(anim)
    assert anim._secured_in_flight
    runner = next(m for m in record.running_result.movements if m.runner_id == str(base))
    assert runner.final_base == base
    assert not runner.touches


def test_a_dropped_fly_still_leaves_a_live_error_play(monkeypatch):
    monkeypatch.setattr(defense, "roll_misplay", lambda *a, **kw: "MUFF")
    random.seed(21)
    game = SimpleNamespace(batter=SimpleNamespace(get_handedness=lambda: "R"))
    anim = ha.HitAnimation(game, "IN_PLAY", lambda: None, quality=0.85,
        batted_ball_type="FLY", ev_mph=90, launch_deg=32, spray_deg=18, initial_bases=(2,))
    anim.update(0)
    _finish(anim)
    assert anim.is_error
    assert not anim._secured_in_flight
    assert anim.running_result.outcome == "REACHED ON ERROR"
    assert anim.running_result.hit_bases == 0


@pytest.mark.parametrize("action", ["continue", "review", "watch"])
def test_home_run_banner_at_the_fence_keeps_scoring_and_publication_once(monkeypatch, action):
    pygame.font.init()
    random.seed(21)
    calls = []
    game = SimpleNamespace(batter=SimpleNamespace(get_handedness=lambda: "R"),
        screen=pygame.Surface((1280, 720)), _fielding_play_number=0, last_fielding_play=None,
        banner=SimpleNamespace(update=lambda dt: None, draw=lambda: None), flip_display=lambda: None,
        key_binding_manager=SimpleNamespace(get_key_for_action=lambda key: pygame.K_f
            if key == KeyAction.FIELDING_REPLAY else None),
        request_fielding_replay=lambda **kw: calls.append("review"))
    anim = ha.HitAnimation(game, "HOME RUN", lambda: calls.append("banner"),
        quality=0.9, batted_ball_type="FLY", initial_bases=(1, 2, 3))
    sim = object.__new__(PitchSimulation)
    sim.game, sim.hit_animation, sim._fielding_recorder = game, anim, None
    sim.pitchtype, sim.speed_mph = "FASTBALL", 95
    sim._publish_review = lambda: calls.append("publish")
    sim._finish_pitch = lambda: calls.append("finish")
    monkeypatch.setattr(pygame.event, "get", lambda: [])
    for t in range(0, 8000, 16):
        sim._handle_hit_animation_phase(t, 0.016)
        if anim.banner_fired:
            break
        assert not anim.banner_ready
    assert anim.banner_fired
    assert ha._point_outside_wall(anim._ball_shadow)
    assert not anim.finished
    assert not anim.completion_published
    assert calls == ["banner"]
    assert game.last_fielding_play is None
    assert anim._elapsed < anim._anim_ms(anim._circuits["B"].arrival_s)
    if action == "watch":
        sim._handle_hit_animation_phase(anim._anim_ms(anim._circuits["B"].arrival_s + 1), 0.016)
        assert calls == ["banner", "publish"]
        assert anim.runner_frame(anim._elapsed).state == "scored"
    else:
        event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_f if action == "review" else pygame.K_SPACE)
        monkeypatch.setattr(pygame.event, "get", lambda: [event, event])
        sim._handle_hit_animation_phase(t + 16, 0.016)
        assert calls == ["banner", "publish", "review" if action == "review" else "finish"]
        assert not sim._fielding_recorder.record.frames[-1].runner.state == "scored"
    assert game.last_fielding_play is sim._fielding_recorder.record
    assert anim.finished and anim.completion_published
    before = calls[:]
    sim._complete_hit_animation()
    assert calls == before
