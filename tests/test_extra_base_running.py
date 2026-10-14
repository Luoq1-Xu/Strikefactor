"""Base contacts, possession and tags are one timeline, including the scorer."""

import json
import math
import random
import sqlite3
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pygame
import pytest

from strikefactor import outcomes
from strikefactor.data.pitch_database import SCHEMA_VERSION, PitchDB
from strikefactor.gameplay import extra_bases
from strikefactor.gameplay import hit_animation as ha
from strikefactor.gameplay.base_geometry import BASE_FT
from strikefactor.gameplay.fielding_record import FieldingRecorder
from strikefactor.gameplay.gameday_manager import GameDayManager, GameEvent
from strikefactor.gameplay.hit_outcome_manager import HitOutcomeManager
from strikefactor.gameplay.pitch_simulation import PitchSimulation
from strikefactor.gameplay.runner_motion import BatterRun, CircuitRun
from strikefactor.gameplay.running_play import RunnerMovement, RunningResult
from strikefactor.helpers import Runner, ScoreKeeper
from strikefactor.ui.fielding_renderer import draw_frame


@pytest.mark.parametrize("destination", [2, 3, 4])
def test_rounding_preserves_the_played_path_and_contacts_every_base(destination):
    route = CircuitRun(BatterRun(4.3), 27.0)
    for base in range(2, destination + 1):
        decision = route.arrival_s - 0.45
        past = [(t / 10, route.position_at(t / 10)) for t in range(int(decision * 10))]
        point = route.position_at(decision)
        forecast = route.preview_next(decision)
        route.commit_next(decision)
        assert route.position_at(decision) == point
        assert route.arrival_s == forecast.arrival_s
        assert all(route.position_at(t) == p for t, p in past)
        assert route.target_base == base
    assert [b for b, _ in route.touches()] == list(range(1, destination + 1))
    for base, t in route.touches():
        assert route.position_at(t) == pytest.approx(BASE_FT[base])
        assert route.base_at(t - 0.00001) == base - 1
        assert route.base_at(t) == base
    # Curved arc length, acceleration and braking consume real seconds.
    for piece in route.pieces:
        for i in range(100):
            t = piece.start_s + piece.duration_s * i / 100
            assert math.dist(piece.position_at(t), piece.position_at(t + 0.0001)) / 0.0001 <= 27.001
    assert route.position_at(route.arrival_s + 5) == BASE_FT[destination]


def test_restart_and_retreat_keep_already_observed_base_contacts():
    route = CircuitRun(BatterRun(4.3), 27)
    route.commit_next(5.0)  # held at first before deciding to go
    assert route.position_at(4.8) == BASE_FT[1]
    assert route.touches(5.0) == ((1, 4.3),)
    decision = 5.3
    past = route.position_at(decision)
    route.return_to(1, decision)
    assert route.position_at(decision) == past
    assert route.touches(decision) == ((1, 4.3),)
    assert route.base_at(route.arrival_s) == 1
    assert [b for b, t in route.touches()] == [1, 1]
    assert not route.commit_next(route.arrival_s + 1)


def _return_play(base=2, margin=-0.10, relay=False, outs=0):
    random.seed(76)
    game = SimpleNamespace(batter=SimpleNamespace(get_handedness=lambda: "R"), currentouts=outs)
    anim = ha.HitAnimation(game, "IN_PLAY", lambda: None, quality=0.8,
                           batted_ball_type="LINER", ev_mph=95, launch_deg=14)
    route = CircuitRun(BatterRun(4.3), 27)
    while route.target_base < base:
        route.commit_next(route.arrival_s - 0.45)
    anim._circuits = {"B": route}
    anim.runner = route.first
    anim._run_decisions = {("B", b) for b in range(1, 4)}
    anim._primary_role = "LF"
    target = BASE_FT[base]
    origin = (target[0] + (220 if relay else 100), target[1])
    anim.fielders["LF"].pos[:] = ha._to_screen(*origin)
    receiver = {2: "SS", 3: "3B", 4: "C"}[base]
    anim.fielders[receiver].pos[:] = ha._to_screen(*target)
    if relay:
        anim.fielders["2B"].pos[:] = ha._to_screen((origin[0] + target[0]) / 2, target[1])
    elapsed = (route.arrival_s - margin
               - extra_bases.OF_RELEASE_S * anim.defense.release_scale
               - math.dist(origin, target) / anim.defense.throw_fts
               - (extra_bases.RELAY_EXCHANGE_S if relay else 0))
    anim._elapsed = anim._secured_at_ms = anim._anim_ms(elapsed)
    anim._secured = True
    anim.start_time = 0
    anim._ball = anim._ball_shadow = tuple(anim.fielders["LF"].pos)
    anim._begin_return_play()
    assert anim._return_race.margin_s == pytest.approx(margin)
    return anim


@pytest.mark.parametrize("base", [2, 3, 4])
@pytest.mark.parametrize("margin", [-0.005, 0.0, 0.005, 0.12, 0.121, 0.14])
@pytest.mark.parametrize("step_ms", [16, 250])
def test_extra_base_verdict_matches_the_visible_tag_and_touch(base, margin, step_ms):
    anim = _return_play(base, margin)
    recorder = FieldingRecorder(anim, "base race")
    t = anim._elapsed
    while not anim.finished:
        t += step_ms
        anim.update(t)
        recorder.capture(anim)
    result = anim.running_result
    record = recorder.record
    assert record.running_result == result
    tagged = margin > 0.12
    assert result.outs_added == int(tagged)
    if tagged:
        tag = next(e for e in record.events if e.label.startswith("TAG OUT"))
        frame = record.sample(tag.time_ms)
        assert frame.runner.state == "out"
        assert frame.runner.base == base - 1
        assert frame.base_call[:2] == ("OUT", base)
        receiver = next(f for f in frame.fielders if f.role == anim._return_legs[-1].receiver)
        assert receiver.glove[0] == pytest.approx(frame.runner.pos[0])
        assert receiver.glove[1] == pytest.approx(frame.runner.pos[1] - 9)
        assert math.dist(frame.runner.pos, ha._to_screen(*BASE_FT[base])) > 1e-8
        assert result.hit_bases == base - 1
        assert result.batter.final_base is None
        assert not any(e.base == base and e.label.startswith("BASE TOUCHED") for e in record.events)
    else:
        touch = next(e for e in record.events if e.base == base and e.label.startswith("BASE TOUCHED"))
        assert touch.time_ms <= anim._anim_ms(anim._return_race.defense_s + 0.12) + 1e-9
        frame = record.sample(touch.time_ms)
        assert frame.runner.pos == pytest.approx(ha._to_screen(*BASE_FT[base]))
        assert frame.base_call[:2] == ("SAFE", base)
        assert result.hit_bases == base
        assert result.batter.final_base == base
    random_state = random.getstate()
    live = pygame.Surface((1280, 720))
    replay = pygame.Surface((1280, 720))
    pygame.font.init()
    draw_frame(live, anim.presentation_frame())
    draw_frame(replay, record.frames[-1])
    assert pygame.image.tobytes(live, "RGB") == pygame.image.tobytes(replay, "RGB")
    record.sample(0)
    record.sample(record.duration_ms / 2)
    assert random.getstate() == random_state
    with pytest.raises(FrozenInstanceError):
        result.hit_bases = 0


def test_relay_waits_for_each_receiver_and_keeps_possession_between_throws():
    anim = _return_play(2, -0.1, relay=True)
    assert len(anim._return_legs) == 2
    first, second = anim._return_legs
    assert first.receiver == second.thrower
    assert first.target == second.origin
    assert second.release_s - first.arrival_s == pytest.approx(extra_bases.RELAY_EXCHANGE_S)
    for leg in anim._return_legs:
        assert anim._base_approaches[leg.receiver].arrival_s <= leg.arrival_s
        anim.update(anim._anim_ms(leg.arrival_s))
        assert ha._to_field_ft(anim.fielders[leg.receiver].pos) == pytest.approx(leg.target)
        assert ha._to_field_ft(anim._ball_shadow) == pytest.approx(leg.target)


def test_late_receiver_changes_both_the_forecast_and_the_actual_throw():
    anim = _return_play(2, 0.4)
    for receiver in ("SS", "2B"):
        anim.fielders[receiver].pos[:] = ha._to_screen(-120, 50)
        anim.fielders[receiver].base_max_speed = 15
    now = anim._elapsed / 1000
    predicted, _ = anim._return_schedule(2, ha._to_field_ft(anim.fielders["LF"].pos), now)
    rng = random.getstate()
    anim._begin_return_play()
    assert random.getstate() == rng
    assert anim._return_legs == predicted
    assert anim._return_race.tag_s is None
    assert anim._return_race.defense_s > anim._circuits["B"].arrival_s


def test_runner_retreats_after_a_committed_throw_without_changing_its_path():
    anim = _return_play(3, 2.0)
    original_throw = anim._return_legs
    release = original_throw[0].release_s
    before = anim._circuits["B"].position_at(release)
    anim.update(anim._anim_ms(release))
    route = anim._circuits["B"]
    assert route.returning
    assert route.target_base == 2
    assert route.position_at(release) == before
    assert anim._return_legs == original_throw
    assert anim._return_race.tag_s is None
    assert any(e.label == "RETURN" for e in anim._running_events)
    anim.update(anim._go_done_ms)
    assert anim.running_result.outs_added == 0
    assert anim.running_result.hit_bases == 2
    assert anim.running_result.batter.final_base == 2
    assert not any(e.label == "TAG OUT" for e in anim.running_result.events)


def test_a_held_leading_runner_blocks_the_batter_from_the_same_base():
    anim = _return_play(2, -0.1)
    anim._return_legs = ()
    anim._return_race = None
    anim._post_fielding = False
    anim._run_decisions = {("1", 1)}
    anim._circuits = {"B": CircuitRun(BatterRun(4.3), 27),
                      "1": CircuitRun(None, 27, start_base=1)}
    anim.fielders["LF"].pos[:] = ha._to_screen(200, 300)
    anim._ball_shadow = tuple(anim.fielders["LF"].pos)
    anim._advance_runners(3.9)
    assert anim._circuits["B"].target_base == 1
    assert anim._circuits["1"].target_base == 1


def test_a_changed_loose_ball_can_turn_a_hold_into_a_coherent_standing_start(monkeypatch):
    anim = _return_play(2, -0.1)
    anim._return_legs = ()
    anim._return_race = None
    anim._post_fielding = False
    anim._secured = False
    anim._run_decisions = set()
    route = CircuitRun(BatterRun(4.3), 27)
    anim._circuits = {"B": route}
    monkeypatch.setattr(anim, "_estimate_pickup", lambda now: ((0, 160), 4.0))
    anim._advance_runners(3.9)
    assert route.target_base == 1
    assert ("B", 1) not in anim._run_decisions
    past = route.position_at(4.4)
    monkeypatch.setattr(anim, "_estimate_pickup", lambda now: ((150, 300), 12.0))
    anim._advance_runners(4.5)
    revised = anim._circuits["B"]
    assert revised.target_base == 2
    assert revised.position_at(4.4) == past
    assert revised.position_at(4.5) == BASE_FT[1]
    assert revised.arrival_at(1) == 4.3


def test_clear_tag_third_out_can_end_without_inventing_later_contacts():
    anim = _return_play(3, 0.5, outs=2)
    recorder = FieldingRecorder(anim, "third out")
    anim.update(anim._anim_ms(anim._return_race.tag_s))
    recorder.capture(anim)
    assert anim.can_continue_early
    assert anim.skip_remaining()
    recorder.capture(anim)
    record = recorder.record
    assert record.frames[-1].runner.state == "out"
    assert record.running_result.batter.final_base is None
    assert not any(e.base == 3 and e.label.startswith("BASE TOUCHED") for e in record.events)
    assert not any(e.time_s > anim._inning_end_s for e in record.running_result.events)


@pytest.mark.parametrize("outs", [3, 4, 10])
@pytest.mark.parametrize("margin", [-0.1, 0.5])
@pytest.mark.parametrize("step_ms", [16, 250])
def test_return_play_finishes_with_cumulative_sandbox_outs(outs, margin, step_ms):
    anim = _return_play(3, margin, outs=outs)
    t = anim._elapsed
    for _ in range(2000):
        t += step_ms
        anim.update(t)
        if anim.finished:
            break
    assert anim.finished
    assert anim._inning_end_s is None
    result = anim.running_result
    tagged = margin > 0
    assert result.outcome == (outcomes.DOUBLE if tagged else outcomes.TRIPLE)
    assert result.running_outs == int(tagged)
    assert result.batter.final_base == (None if tagged else 3)
    sk = ScoreKeeper()
    play = sk.update_running_play(result, outs=outs)
    assert play.running_outs == int(tagged)
    assert sk.isRunnerOnBase(3) == (not tagged)


def test_home_run_runs_the_whole_circuit_with_leading_runners():
    random.seed(1)
    game = SimpleNamespace(batter=SimpleNamespace(get_handedness=lambda: "L"))
    anim = ha.HitAnimation(game, "HOME RUN", lambda: None, quality=0.9,
                           batted_ball_type="FLY", initial_bases=(1, 2, 3))
    anim.update(0)
    for t in range(16, 22000, 16):
        anim.update(t)
        if anim.finished:
            break
    assert anim.finished
    for rid, route in anim._circuits.items():
        assert route.base_at(anim._elapsed / 1000) == 4
        assert [b for b, _ in route.touches()] == list(range(route.start_base + 1, 5))
        assert route.position_at(route.arrival_s) == BASE_FT[4]
    assert anim.runner_frame(anim._elapsed).state == "scored"
    assert anim._elapsed > 12000


@pytest.mark.parametrize("base", [1, 2, 3])
def test_hit_credit_survives_a_later_tag_and_gameday_logs_both(base):
    sk = ScoreKeeper()
    result = RunningResult({n: o for o, n in outcomes.HIT_BASES.items()}[base], base,
        (RunnerMovement("B", 0, None, tuple((b, b * 4.0) for b in range(1, base + 1)), 15.0),))
    play = sk.update_running_play(result, outs=2)
    assert play.running_outs == 1
    assert sk.get_runners_on_base() == 0
    gm = GameDayManager(difficulty="amateur", starter_name="sale")
    gm.current_outs = 2
    gm.record_player_at_bat(result.outcome, play=play, charges=sk.take_charges())
    assert gm.current_outs == 3
    assert gm.get_active_pitcher_stats().hits_allowed == 1
    assert gm.get_active_pitcher_stats().outs_recorded == 1
    event = GameEvent.from_dict(gm.event_log[-1].to_dict())
    assert event.result == result.outcome
    assert event.running_outs == 1
    assert "OUT ADVANCING" in str(event)


@pytest.mark.parametrize("crossed,batter_outcome,counts", [
    (9.0, outcomes.DOUBLE, True), (10.0, outcomes.DOUBLE, False),
    (11.0, outcomes.DOUBLE, False), (9.0, outcomes.GROUNDOUT, False),
    (9.0, outcomes.FLYOUT, False), (9.0, outcomes.LINEOUT, False),
    (9.0, outcomes.POP_UP, False),
])
def test_runs_obey_the_actual_third_out_time_and_batter_out_rule(crossed, batter_outcome, counts):
    sk = ScoreKeeper()
    sk.set_pitcher("starter")
    original = Runner(3, "previous")
    sk.runners = [original]
    hit = outcomes.HIT_BASES.get(batter_outcome, 0)
    result = RunningResult(batter_outcome, hit, (
        RunnerMovement("B", 0, None, ((1, 4.3), (2, 8)) if hit else (), 10.0),
        RunnerMovement("3", 3, 4, ((4, crossed),)),
    ))
    play = sk.update_running_play(result, outs=2)
    assert play.runs == int(counts)
    assert play.rbi == int(counts)
    assert not play.sacrifice_fly
    assert sk.get_score() == sk.get_earned_runs() == int(counts)
    assert sk.take_charges() == ([("previous", 1, 1)] if counts else [])


@pytest.mark.parametrize("outs", [3, 4, 10])
@pytest.mark.parametrize("out_s", [None, 10.0])
def test_cumulative_sandbox_outs_do_not_cancel_later_runs(outs, out_s):
    sk = ScoreKeeper()
    sk.runners = [Runner(3)]
    result = RunningResult(outcomes.SINGLE, 1, (
        RunnerMovement("B", 0, 1 if out_s is None else None, ((1, 4.3),), out_s),
        RunnerMovement("3", 3, 4, ((4, 11.0),)),
    ))
    play = sk.update_running_play(result, outs=outs)
    assert (play.runs, play.rbi, play.running_outs) == (1, 1, int(out_s is not None))
    assert sk.get_score() == 1
    assert sk.isRunnerOnBase(1) == (out_s is None)


def test_actual_single_can_bring_a_fast_runner_home_from_second():
    sk = ScoreKeeper()
    original = Runner(2, "previous")
    sk.runners = [original]
    result = RunningResult(outcomes.SINGLE, 1, (
        RunnerMovement("B", 0, 1, ((1, 4.3),)),
        RunnerMovement("2", 2, 4, ((3, 3.7), (4, 7.3))),
    ))
    play = sk.update_running_play(result)
    assert (play.runs, play.rbi) == (1, 1)
    assert sk.take_charges() == [("previous", 1, 1)]
    assert sk.isRunnerOnBase(1)
    assert not sk.isRunnerOnBase(2)


def test_deferred_finalization_keeps_hit_out_stats_and_persisted_result_together():
    anim = _return_play(3, 0.5, outs=2)
    anim.update(anim._go_done_ms)
    sk = ScoreKeeper()
    manager = object.__new__(HitOutcomeManager)
    manager.score_keeper = sk
    calls = []
    gm = GameDayManager(difficulty="amateur", starter_name="sale")
    gm.current_outs = 2
    game = SimpleNamespace(currentouts=2, hits=0, last_pitch_information=[], ball=(640, 400),
        in_gameday_mode=True, scoreKeeper=sk, hit_outcome_manager=manager, gameday_manager=gm,
        field_renderer=SimpleNamespace(record_hit=lambda *a, **k: calls.append(k["hit_type"]),
                                       record_at_bat=lambda: calls.append("AB")),
        banner=SimpleNamespace(show_banner=lambda text: calls.append(text)))
    sim = object.__new__(PitchSimulation)
    sim.game, sim.hit_animation, sim.new_entry = game, anim, {}
    sim._check_walkoff = lambda: None
    sim._finalize_batted_ball()
    assert sim.outcome == "DOUBLE"
    assert game.hits == 1
    assert game.currentouts == gm.current_outs == 3
    assert calls == ["AB", "DOUBLE", "DOUBLE · OUT ADVANCING"]
    assert sim.baserunning_outs == 1
    assert sim.batter_final_base is None
    saved = json.loads(sim.running_play_json)
    assert saved["hit_bases"] == 2
    assert saved["outcome"] == "DOUBLE"
    assert saved["movements"][0]["out_s"] is not None
    assert sim.tag_margin_s > 0


def test_dropped_sacrifice_preserves_rbi_and_earned_run_reconstruction():
    sk = ScoreKeeper()
    sk.runners = [Runner(3)]
    result = RunningResult(outcomes.REACHED_ON_ERROR, 0, (
        RunnerMovement("B", 0, 2, ((1, 4.3), (2, 8))),
        RunnerMovement("3", 3, 4, ((4, 4),)),
    ), error_out=outcomes.FLYOUT, error_bases=2)
    play = sk.update_running_play(result, outs=0)
    assert play.sacrifice_fly
    assert (play.runs, play.rbi) == (1, 1)
    assert sk.score == sk.earned == 1
    assert sk.missed_outs == 1
    assert sk.basesfilled[2].clean_base is None


def test_two_out_error_scores_physical_runs_as_unearned():
    sk = ScoreKeeper()
    sk.runners = [Runner(3)]
    result = RunningResult(outcomes.REACHED_ON_ERROR, 0, (
        RunnerMovement("B", 0, 1, ((1, 4.3),)),
        RunnerMovement("3", 3, 4, ((4, 4),)),
    ), error_out=outcomes.GROUNDOUT, error_bases=1)
    play = sk.update_running_play(result, outs=2)
    assert (play.runs, play.rbi) == (1, 0)
    assert sk.score == 1 and sk.earned == 0
    assert sk.missed_outs == 1


def test_new_baserunning_columns_leave_historical_rows_unknown(tmp_path):
    path = str(tmp_path / "v12.db")
    connection = sqlite3.connect(path)
    connection.executescript(PitchDB.SCHEMA)
    columns = ("baserunning_outs", "batter_final_base", "tag_margin_s", "running_play_json")
    for name in columns:
        connection.execute(f"ALTER TABLE pitches DROP COLUMN {name}")
    connection.execute("INSERT INTO pitches (pitch_id, session_id, game_mode, difficulty, created_at, "
                       "pitcher_name, pitch_type, outcome) VALUES ('p', 's', 'arcade', 'amateur', "
                       "'2026-01-01', 'Sale', 'FASTBALL', 'DOUBLE')")
    connection.execute("PRAGMA user_version = 12")
    connection.commit()
    connection.close()
    db = PitchDB(path)
    try:
        row = db.conn.execute(f"SELECT {', '.join(columns)} FROM pitches").fetchone()
        assert tuple(row) == (None, None, None, None)
        assert db.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert SCHEMA_VERSION >= 13
    finally:
        db.close()
