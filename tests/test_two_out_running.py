"""Two-out contact sends runners; a caught third out annuls every run."""

import math
import random
from types import SimpleNamespace

import pytest

from strikefactor import outcomes
from strikefactor.gameplay import defense
from strikefactor.gameplay import hit_animation as ha
from strikefactor.gameplay.base_geometry import BASE_FT
from strikefactor.gameplay.fielding_record import FieldingRecorder
from strikefactor.helpers import Runner, ScoreKeeper


def _contact(shape, *, outs=2, hand="R", outcome="IN_PLAY", bases=(1, 2, 3)):
    random.seed(21)
    game = SimpleNamespace(batter=SimpleNamespace(get_handedness=lambda: hand), currentouts=outs)
    ev, angle = {"GROUNDER": (90, 5), "LINER": (90, 15),
                 "FLY": (90, 32), "POP_UP": (85, 60)}[shape]
    anim = ha.HitAnimation(game, outcome, lambda: None, quality=0.85,
        batted_ball_type=shape, ev_mph=ev, launch_deg=angle, spray_deg=18,
        initial_bases=bases)
    anim.update(0)
    return anim


def _finish(anim, step_ms, recorder=None):
    if recorder is None:
        recorder = FieldingRecorder(anim, "two outs")
    for t in range(int(anim._elapsed) + step_ms, 30000, step_ms):
        anim.update(t)
        recorder.capture(anim)
        if anim.finished:
            return recorder.record
    pytest.fail("two-out running play did not settle")


@pytest.mark.parametrize("shape", ["GROUNDER", "LINER", "FLY", "POP_UP"])
@pytest.mark.parametrize("outs", [0, 1, 2])
def test_existing_runners_break_on_every_fair_contact_with_two_outs(monkeypatch, shape, outs):
    monkeypatch.setattr(defense, "roll_misplay", lambda *a, **kw: None)
    anim = _contact(shape, outs=outs)
    anim.update(500)
    for runner in anim.presentation_frame().runners:
        starting_pos = ha._to_screen(*BASE_FT[int(runner.runner_id)])
        if outs == 2 or shape == "GROUNDER":
            assert runner.state == "running"
            assert math.dist(runner.pos, starting_pos) > 1
        else:
            assert runner.state == "holding"
            assert runner.pos == pytest.approx(starting_pos)


@pytest.mark.parametrize("hand", ["R", "L"])
@pytest.mark.parametrize("step_ms", [16, 250])
def test_long_two_out_popup_rounds_bases_then_freezes_at_the_catch(monkeypatch, hand, step_ms):
    monkeypatch.setattr(defense, "roll_misplay", lambda *a, **kw: None)
    anim = _contact("POP_UP", hand=hand)
    record = _finish(anim, step_ms)
    result = record.running_result
    catch_s = anim._secured_at_ms / (1000 * anim.time_scale)
    assert anim._secured_in_flight
    assert anim._inning_end_s == catch_s
    assert result.outcome == outcomes.POP_UP and result.outs_added == 1
    assert not anim._return_legs
    # First and second keep rounding instead of braking to wait for a tag-up.
    for rid, base in (("1", 2), ("2", 3)):
        route = anim._circuits[rid]
        touch_s = route.arrival_at(base)
        assert touch_s < catch_s
        assert math.dist(route.position_at(touch_s + 0.1), BASE_FT[base]) > 1
        assert any(e.runner_id == rid and e.base == base + 1 and e.time_s < catch_s
                   for e in result.events if e.label == "ADVANCE")
    # Home was physically touched before the catch, but that run cannot count.
    runner = next(m for m in result.movements if m.runner_id == "3")
    assert runner.scored_s < catch_s
    sk = ScoreKeeper()
    sk.runners = [Runner(base) for base in (1, 2, 3)]
    play = sk.update_running_play(result, outs=2)
    assert (play.runs, play.rbi, play.sacrifice_fly) == (0, 0, False)
    assert sk.get_score() == sk.get_earned_runs() == 0
    assert not sk.take_charges()
    assert record.frames[-1].runners == record.sample(anim._secured_at_ms).runners
    assert all(t <= catch_s for m in result.movements for _, t in m.touches)
    assert not any(e.label.startswith("THROW") or e.label == "TAG OUT" for e in record.events)
    assert any(e.runner_id == "3" and e.base == 4 and e.time_ms < anim._secured_at_ms
               for e in record.events if e.label.startswith("BASE TOUCHED"))


@pytest.mark.parametrize("shape", ["FLY", "POP_UP"])
@pytest.mark.parametrize("step_ms", [16, 250])
def test_dropped_two_out_fly_preserves_the_contact_head_start_and_live_runs(monkeypatch, shape, step_ms):
    monkeypatch.setattr(defense, "roll_misplay", lambda *a, **kw: "MUFF")
    anim = _contact(shape, bases=(2, 3))
    recorder = FieldingRecorder(anim, "two-out drop")
    # Reach the catching chance at normal live cadence, then vary the
    # return-play cadence. A coarse airborne step can miss the glove window.
    for t in range(16, 8000, 16):
        anim.update(t)
        recorder.capture(anim)
        if anim.is_error:
            break
    record = _finish(anim, step_ms, recorder)
    result = record.running_result
    assert anim.is_error and not anim._secured_in_flight
    assert anim._inning_end_s is None
    assert result.outcome == outcomes.REACHED_ON_ERROR
    runner = next(m for m in result.movements if m.runner_id == "2")
    assert runner.touches[0][0] == 3
    assert runner.touches[0][1] < anim.flight_time_s
    assert runner.scored_s is not None
    sk = ScoreKeeper()
    sk.runners = [Runner(2), Runner(3)]
    play = sk.update_running_play(result, outs=2)
    assert (play.runs, play.rbi, play.sacrifice_fly) == (2, 0, False)
    assert sk.get_score() == 2 and sk.get_earned_runs() == 0


@pytest.mark.parametrize("hand", ["R", "L"])
def test_two_out_foul_keeps_existing_runners_visible_on_their_bases(hand):
    anim = _contact("POP_UP", hand=hand, outcome="FOUL")
    initial = anim.presentation_frame()
    record = _finish(anim, 250)
    assert len(initial.runners) == 3
    assert initial.runner is not None
    assert all(f.runners == initial.runners and f.runner == initial.runner for f in record.frames)
    assert all(r.state == "holding" for r in initial.runners)
    assert record.running_result is None
    assert not anim._running_events
