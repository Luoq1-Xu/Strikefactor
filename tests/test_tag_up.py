"""Early manual departures, physical appeals, and their scoring consequences."""

import json
import random
from dataclasses import asdict, replace
from types import SimpleNamespace

import pygame
import pytest

from strikefactor import outcomes, paths
from strikefactor.gameplay import hit_animation as ha
from strikefactor.gameplay import return_play, tag_up
from strikefactor.gameplay.base_geometry import BASE_FT
from strikefactor.gameplay.defense import profile_for
from strikefactor.gameplay.fielding_record import FieldingRecorder
from strikefactor.gameplay.runner_motion import CircuitRun
from strikefactor.gameplay.running_play import RunnerMovement, RunnerRetirement, RunningResult, ThrowLeg
from strikefactor.helpers import Runner, ScoreKeeper
from strikefactor.key_binding_manager import KeyAction, KeyBindingManager
from strikefactor.ui.fielding_renderer import draw_frame


def _animation(bases=(1,), shape="FLY", *, outs=0, mode="manual", game_mode="arcade"):
    random.seed(21)
    game = SimpleNamespace(currentouts=outs, game_mode=game_mode,
                           batter=SimpleNamespace(get_handedness=lambda: "R"))
    anim = ha.HitAnimation(game, "IN_PLAY", lambda: None, quality=0.85,
        batted_ball_type=shape, ev_mph=90,
        launch_deg={"LINER": 15, "FLY": 32, "POP_UP": 60}[shape], spray_deg=18,
        initial_bases=bases, baserunning_mode=mode)
    anim.start_time = 0
    return anim


def _at(anim, time_s):
    # A scripted catch isolates the races from the airborne interception
    # integration. All subsequent routes, coverage and throws run live.
    anim._elapsed = anim._anim_ms(time_s)


def _catch(anim, time_s, point=(0, 370), role="CF"):
    _at(anim, time_s)
    anim.fielders[role].pos[:] = ha._to_screen(*point)
    anim._trigger_in_flight_intercept(role, tuple(anim.fielders[role].pos))


def _finish(anim, step=16):
    recorder = FieldingRecorder(anim, "tag-up appeal")
    for _ in range(4000):
        anim.update(anim._elapsed + step)
        recorder.capture(anim)
        if anim.finished:
            return recorder.record
    pytest.fail("tag-up play failed to settle")


def _keeper(bases, *, sandbox=False):
    keeper = ScoreKeeper(unlimited_outs=sandbox)
    keeper.runners = [Runner(base) for base in bases]
    return keeper


@pytest.mark.parametrize("shape", ["LINER", "FLY", "POP_UP"])
@pytest.mark.parametrize("step", [16, 250])
def test_early_send_is_live_and_a_catch_never_returns_the_runner_automatically(shape, step):
    anim = _animation(shape=shape)
    _at(anim, 0.4)
    assert anim.send_runner()
    route = anim._circuits["1"]
    assert route.position_at(0.8) != BASE_FT[1]
    _catch(anim, 1.0)
    assert anim.presentation_frame().retouch_owed == (("1", 1),)
    assert not route.returning
    assert not anim.can_continue_early
    result = _finish(anim, step).running_result
    assert result.outs_added == 2
    appeal = next(r for r in result.retirements if r.kind == "appeal")
    assert appeal.base == 1
    assert appeal.time_s == anim._return_legs[-1].arrival_s
    assert not any(e.label == "MANUAL RETURN" for e in result.events)
    assert result.retouches[0].resolution == "appealed"


@pytest.mark.parametrize("step", [16, 250])
def test_early_retreat_beats_the_appeal_and_does_not_grant_another_automatic_advance(step):
    anim = _animation()
    _at(anim, 0.4)
    assert anim.send_runner()
    _catch(anim, 0.8)
    released = anim._return_legs
    assert anim.retreat_runner()
    back = anim._circuits["1"].arrival_s
    record = _finish(anim, step)
    result = record.running_result
    runner = next(m for m in result.movements if m.runner_id == "1")
    assert runner.final_base == 1 and runner.out_s is None
    assert result.outs_added == 1
    assert result.retouches[0].retouched_s == pytest.approx(back)
    assert result.retouches[0].resolution == "retouched"
    assert anim._return_legs[0] == released[0]
    assert not record.frames[-1].retouch_owed
    assert _keeper((1,)).update_running_play(result).runs == 0


@pytest.mark.parametrize("step", [16, 250])
def test_advanced_bag_does_not_protect_a_runner_from_a_late_appeal(step):
    anim = _animation()
    _at(anim, 0.4)
    assert anim.send_runner()
    route = anim._circuits["1"]
    _catch(anim, route.arrival_s + 0.1, point=(0, 160))
    assert route.base_at(anim._elapsed / (1000*anim.time_scale)) == 2
    assert anim._retreat_destination(anim._elapsed / (1000*anim.time_scale)) == 1
    assert anim.retreat_runner()
    result = _finish(anim, step).running_result
    runner = next(m for m in result.movements if m.runner_id == "1")
    assert runner.out_s is not None
    assert any(r.kind == "appeal" and r.runner_id == "1" for r in result.retirements)


def test_precautionary_return_before_a_catch_preserves_the_played_route():
    anim = _animation()
    _at(anim, 0.4)
    assert anim.send_runner()
    route = anim._circuits["1"]
    past = [(t, route.position_at(t)) for t in (0.2, 0.4, 0.7)]
    _at(anim, 0.7)
    assert anim.retreat_runner()
    _catch(anim, route.arrival_s + 0.1)
    assert all(route.position_at(t) == point for t, point in past)
    assert not anim._duties
    assert _finish(anim).running_result.outs_added == 1


def test_retrace_crosses_every_intermediate_bag_and_interrupting_it_keeps_history():
    route = CircuitRun(None, 27, start_base=1)
    route.commit_next(0.4)
    route.commit_next(route.arrival_s - 0.3)
    turn = route.arrival_at(2) + 0.5
    past = [(t, route.position_at(t)) for t in (0.4, 1.0, route.arrival_at(2), turn)]
    route.retrace_to(1, turn)
    assert [base for base, t in route.touches() if t > turn] == [2, 1]
    assert all(route.position_at(t) == point for t, point in past)
    assert route.forward_base(turn + 0.1) == 3
    point = route.position_at(turn + 0.1)
    route.resume_to(3, turn + 0.1)
    assert route.position_at(turn + 0.1) == point
    assert all(route.position_at(t) == point for t, point in past)
    assert not any(t > turn and base == 1 for base, t in route.touches())


def test_first_touch_eligibility_uses_contact_intervals_including_a_pre_catch_return():
    route = CircuitRun(None, 27, start_base=1)
    route.commit_next(0.4)
    route.retrace_to(1, 0.8)
    back = route.arrival_s
    assert tag_up.duty("1", route, back + 0.1) is None
    route.resume_to(2, back + 0.2)
    assert tag_up.duty("1", route, back + 0.3) is not None
    assert tag_up.retouch_s(route, back + 0.1) == back + 0.1


def test_first_touch_can_precede_the_completed_catch():
    anim = _animation()
    anim._first_touch_s = 0.3  # the ball is bobbled before eventual secure possession
    _at(anim, 0.4)
    assert anim.send_runner()
    _catch(anim, 0.8)
    assert anim._first_touch_s == 0.3
    assert not anim._duties
    assert not any(r.kind == "appeal" for r in _finish(anim).running_result.retirements)


def test_following_runner_scoring_during_a_return_prevents_the_later_correction():
    follower = CircuitRun(None, 100, start_base=1)
    follower.commit_next(0.2)
    follower.commit_next(follower.arrival_s)
    follower.commit_next(follower.arrival_s)
    turn = follower.arrival_s - 0.2
    leader = CircuitRun(None, 10, start_base=3)
    leader.commit_next(0.2)
    leader.retrace_to(3, turn)
    routes = {"1": follower, "3": leader}
    assert tag_up.can_correct("3", routes, turn)
    assert leader.arrival_s > follower.arrival_s
    assert tag_up.retouch_s(leader, turn, routes=routes) is None
    assert tag_up.owes(leader, turn, leader.arrival_s + 0.1, routes=routes)


@pytest.mark.parametrize("step", [16, 250])
def test_drop_preserves_the_early_head_start_without_retouch_or_extra_auto_base(step):
    anim = _animation()
    _at(anim, 0.4)
    assert anim.send_runner()
    route = anim._circuits["1"]
    point = route.position_at(1.0)
    _at(anim, 1.0)
    anim.fielders["CF"].pos[:] = ha._to_screen(0, 250)
    anim._trigger_muff("CF")
    anim._advance_runners(1.0)
    assert anim._circuits["1"].position_at(1.0) == point
    result = _finish(anim, step).running_result
    runner = next(m for m in result.movements if m.runner_id == "1")
    assert not result.retouches
    assert not any(base > 2 for base, _ in runner.touches)


def test_crossing_home_early_keeps_controls_and_all_affected_runners_can_be_selected():
    anim = _animation((2, 3))
    _at(anim, 0.4)
    assert anim.send_runner()
    _at(anim, 0.5)
    assert anim.select_runner()
    assert anim.baserunning.runner_id == "2"
    assert anim.send_runner()
    _catch(anim, max(anim._circuits[r].arrival_s for r in ("2", "3")) + 0.1)
    now = anim._elapsed / (1000*anim.time_scale)
    assert set(anim.presentation_frame().retouch_owed) == {("2", 2), ("3", 3)}
    assert anim.select_runner()
    assert anim.baserunning.runner_id == "3"
    assert anim._retreat_destination(now) == 3
    assert anim.retreat_runner()
    assert anim._circuits["3"].returning


def test_send_can_interrupt_a_correction_without_forgiving_the_missing_retouch():
    anim = _animation()
    _at(anim, 0.4)
    assert anim.send_runner()
    _catch(anim, 0.8)
    assert anim.retreat_runner()
    _at(anim, 0.9)
    assert anim.send_runner()
    assert not anim._circuits["1"].returning
    assert anim._owes_retouch("1", 0.9)
    record = _finish(anim)
    assert record.running_result.running_outs == 1
    appeal = next(e for e in record.events if e.label == "APPEAL OUT 1B")
    assert next(r for r in record.sample(appeal.time_ms).runners if r.runner_id == "1").state == "out"


def test_successful_correction_requires_a_fresh_send_and_uses_the_current_departure_time():
    anim = _animation()
    _at(anim, 0.4)
    assert anim.send_runner()
    _catch(anim, 0.8)
    assert anim.retreat_runner()
    back = anim._circuits["1"].arrival_s
    anim.update(anim._anim_ms(back + 0.05))
    assert anim._circuits["1"].target_base == 1
    assert not anim._owes_retouch("1", back + 0.05)
    assert anim.send_runner()
    assert anim._circuits["1"].target_base == 2
    assert anim._circuits["1"].pieces[-1].start_s == pytest.approx(back + 0.05)


def test_retouch_tying_ball_possession_is_safe():
    anim = _animation()
    _at(anim, 0.4)
    assert anim.send_runner()
    _catch(anim, 0.8)
    assert anim.retreat_runner()
    back = anim._circuits["1"].arrival_s
    leg = ThrowLeg((0, 370), BASE_FT[1], 0.8, back, "CF", "1B")
    race = anim._race_for("1", 1, (leg,), 0.8)
    assert race.kind == "appeal"
    assert race.tag_s is None
    assert not anim._owes_retouch("1", back)


@pytest.mark.parametrize("shape", ["LINER", "FLY"])
def test_an_appeal_through_a_cutoff_starts_in_the_glove_that_made_the_catch(shape):
    # From here the cutoff man stands near first. He once "carried" the
    # ball there from the instant of the catch, while the CF still held it.
    anim = _animation(shape=shape)
    _at(anim, 0.4)
    assert anim.send_runner()
    _catch(anim, 1.5, point=(0, 270))
    legs = anim._return_legs
    assert len(legs) == 2  # the throw goes through a cutoff
    assert legs[0].thrower == "CF"
    assert legs[0].origin == pytest.approx(ha._to_field_ft(anim.fielders["CF"].pos))
    assert all(leg.thrower == prev.receiver for prev, leg in zip(legs, legs[1:]))
    result = _finish(anim).running_result
    assert not any(e.label == "CARRY START" for e in result.events)


def test_rethinking_an_unthrown_relay_starts_from_the_fielder_who_holds_the_ball(monkeypatch):
    # Before the CF throws to his cutoff, a change of plan is his to make.
    # It was once made from the cutoff man's spot, as if he had the ball.
    anim = _animation()
    _at(anim, 0.4)
    assert anim.send_runner()
    _catch(anim, 1.5, point=(0, 270))
    now = 1.6
    assert [leg.thrower for leg in anim._return_legs] == ["CF", "2B"]
    assert now < anim._return_legs[0].release_s
    _at(anim, now)
    asked = {}

    def spy(point, now_s, *, holder=None, transfer_s=None, allow_relay=True, current=None):
        asked.update(point=point, holder=holder, transfer_s=transfer_s, allow_relay=allow_relay)
        return None
    monkeypatch.setattr(anim, "_choose_return", spy)
    anim._return_react_s = now
    anim._reconsider_return(now)
    assert asked["holder"] == "CF"
    assert asked["point"] == pytest.approx(ha._to_field_ft(anim.fielders["CF"].pos))
    assert asked["transfer_s"] == pytest.approx(anim._return_legs[0].release_s - now + return_play.TURN_SETUP_S)
    assert asked["allow_relay"]


def test_only_the_fielder_holding_the_ball_can_carry_it():
    # Same defenders, with and without the right to carry: the cutoff man
    # is never handed a carry he could win only by starting with the ball.
    def defender(role, position):
        return return_play.Defender(role, position, 27.0, 0.25, 0.0, 0.0)
    # The infield at its homes; the 2B is both the cutoff and close to first.
    defenders = {role: defender(role, pos) for role, pos in {
        "CF": (0, 270), "1B": (58, 83), "2B": (50, 136), "SS": (-50, 136), "P": (0, 60)}.items()}
    league = profile_for("league")
    thrown, _ = return_play.schedule_return(1, (0, 270), 1.5, defenders, league, holder="CF")
    legs, _ = return_play.schedule_return(1, (0, 270), 1.5, defenders, league, holder="CF",
                                          carry_delay_s=0.0, allow_holder_carry=True)
    assert [leg.thrower for leg in thrown] == ["CF", "2B"]
    assert legs == thrown
    # The holder himself may still carry when he is close enough to win.
    near = {**defenders, "1B": defender("1B", (55, 70))}
    legs, approaches = return_play.schedule_return(1, (55, 70), 1.5, near, league, holder="1B",
                                                   carry_delay_s=0.0, allow_holder_carry=True)
    assert [(leg.thrower, leg.receiver) for leg in legs] == [("1B", "1B")]
    assert set(approaches) == {"1B"}


def test_unassisted_appeal_requires_actual_base_contact_and_no_fictitious_throw():
    anim = _animation()
    _at(anim, 0.4)
    assert anim.send_runner()
    _catch(anim, 1.0, BASE_FT[1], "1B")
    result = _finish(anim).running_result
    appeal = next(r for r in result.retirements if r.kind == "appeal")
    assert appeal.time_s == pytest.approx(1.0)
    assert appeal.role == "1B"
    assert any(e.label == "BASE POSSESSION" for e in result.events)
    assert not any(e.label == "THROW RELEASE" for e in result.events)


@pytest.mark.parametrize("step", [16, 250])
def test_advantageous_appeal_continues_after_third_out_and_is_recorded_without_a_fourth_official_out(step):
    anim = _animation((1, 3), outs=1)
    for rid in ("1", "3"):
        anim._circuits[rid].commit_next(0.4)
    _catch(anim, max(anim._circuits[r].arrival_s for r in ("1", "3")) + 0.1)
    now = anim._elapsed / (1000*anim.time_scale)
    # The defense's committed initial play is at first. After that third
    # out it must still appeal third to remove the run which crossed early.
    point = ha._to_field_ft(anim.fielders["CF"].pos)
    legs, approaches = anim._return_schedule(1, point, now)
    anim._replace_return_plan((), legs, approaches, "1", 1, now, "APPEAL THROW")
    record = _finish(anim, step)
    result = record.running_result
    assert result.outs_added == 2  # one out already existed
    appeals = [r for r in result.retirements if r.kind == "appeal"]
    assert [(r.runner_id, r.official) for r in appeals] == [("1", True), ("3", False)]
    assert appeals[-1].time_s > anim._inning_end_s
    assert result.fielding_sequence[-1] == appeals[0].role
    assert any(e.label == "APPEAL OUT 3B" and e.time_ms > anim._anim_ms(anim._inning_end_s)
               for e in record.events)
    assert _keeper((1, 3)).update_running_play(result, outs=1).runs == 0
    assert all(t <= anim._inning_end_s for m in result.movements for _, t in m.touches)
    assert json.loads(json.dumps(asdict(result)))["retirements"][-1]["official"] is False


@pytest.mark.parametrize("appealed,expected", [(1, 1), (3, 0)])
def test_third_out_appeal_respects_runner_order_even_after_an_earlier_home_touch(appealed, expected):
    moves = [RunnerMovement("B", 0, None, (), 4.0),
             RunnerMovement("3", 3, 4, ((4, 5.0),)),
             RunnerMovement("1", 1, 4, ((2, 1.0), (3, 3.0), (4, 5.5)))]
    moves = tuple(replace(m, final_base=None, out_s=6.0) if m.runner_id == str(appealed) else m for m in moves)
    result = RunningResult(outcomes.FLYOUT, 0, moves, retirements=(
        RunnerRetirement("B", 4.0, 0, "catch"), RunnerRetirement(str(appealed), 6.0, appealed, "appeal")))
    keeper = _keeper((1, 3))
    play = keeper.update_running_play(result, outs=1)
    assert play.runs == expected
    assert keeper.get_earned_runs() == expected


def test_withdrawn_home_touch_never_scores_and_a_corrected_rescore_uses_its_later_time():
    runner = RunnerMovement("3", 3, 3, ((4, 2.0), (3, 5.0)))
    assert runner.scored_s is None
    runner = replace(runner, final_base=4, touches=runner.touches + ((4, 9.0),))
    assert runner.scored_s == 9.0
    result = RunningResult(outcomes.FLYOUT, 0, (
        RunnerMovement("B", 0, None, (), 3.0), runner, RunnerMovement("1", 1, None, (), 8.0)),
        retirements=(RunnerRetirement("B", 3.0, 0, "catch"), RunnerRetirement("1", 8.0, 1, "appeal")))
    assert _keeper((1, 3)).update_running_play(result, outs=1).runs == 0


def test_selector_migration_preserves_custom_keys_and_warnings_render_in_replay(monkeypatch, tmp_path):
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path))
    manager = KeyBindingManager(None)
    (tmp_path / paths.KEY_BINDINGS_FILE).write_text(json.dumps({"main_menu": pygame.K_TAB}))
    migrated = manager.load_bindings()
    assert migrated["main_menu"] == pygame.K_TAB
    assert migrated["select_runner"] != pygame.K_TAB
    for key in (pygame.K_w, pygame.K_e, pygame.K_F11):
        assert not manager.is_key_available(key, exclude_action=KeyAction.SELECT_RUNNER)
    anim = _animation((1, 3))
    _at(anim, 0.4)
    assert anim.send_runner()
    _catch(anim, 1.0)
    pygame.font.init()
    frame = anim.presentation_frame()
    assert frame.send_control[10] == "Tab"
    assert frame.retouch_owed == (("3", 3),)
    draw_frame(pygame.Surface((1280, 720)), frame)


@pytest.mark.parametrize("outs", [2, 10])
def test_sandbox_keeps_manual_tag_up_rules_with_cumulative_outs(outs):
    anim = _animation(outs=outs, game_mode="sandbox")
    _at(anim, 0.4)
    assert anim.send_runner()
    _catch(anim, 0.8)
    assert anim.retreat_runner()
    result = _finish(anim).running_result
    assert result.outs_added == 1
    assert anim._inning_end_s is None

