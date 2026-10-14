"""Player commitments and defensive possession must remain one physical play."""

import json
import random
import sqlite3
from types import SimpleNamespace

import pygame
import pytest

from strikefactor.data.pitch_database import SCHEMA_VERSION, PitchDB
from strikefactor.gameplay import defense
from strikefactor.gameplay import hit_animation as ha
from strikefactor.gameplay.base_geometry import BASE_FT
from strikefactor.gameplay.fielding_record import FieldingRecorder
from strikefactor.gameplay.hit_outcome_manager import HitOutcomeManager
from strikefactor.gameplay.pitch_simulation import PitchSimulation
from strikefactor.gameplay.runner_motion import BatterRun, CircuitRun
from strikefactor.helpers import Runner, ScoreKeeper
from strikefactor.key_binding_manager import KeyAction, KeyBindingManager
from strikefactor.settings_manager import SettingsManager
from strikefactor.ui.fielding_renderer import draw_frame
from strikefactor.ui.settings_panel import KeyBindingsPanel, SettingsPanel


def _animation(mode="manual", *, bases=(), shape="LINER", outs=0, seed=76, hand="R", level="league"):
    random.seed(seed)
    game = SimpleNamespace(batter=SimpleNamespace(get_handedness=lambda: hand), currentouts=outs)
    return ha.HitAnimation(game, "IN_PLAY", lambda: None, quality=0.8,
        batted_ball_type=shape, ev_mph=95,
        launch_deg={"GROUNDER": 5, "LINER": 14, "FLY": 32, "POP_UP": 60}[shape],
        spray_deg=18, initial_bases=bases, baserunning_mode=mode, defense=level)


def _finish(anim, step=16, recorder=None):
    if recorder is None:
        recorder = FieldingRecorder(anim, "manual running")
    time = anim._elapsed
    for _ in range(2500):
        time += step
        anim.update(time)
        recorder.capture(anim)
        if anim.finished:
            return recorder.record
    pytest.fail("live baserunning did not settle")


def _pickup(anim, time=2.9, point=(40, 220), *, ready_cutoff=False):
    anim._elapsed = anim._secured_at_ms = anim._anim_ms(time)
    anim._secured = True
    anim._primary_role = "RF"
    anim.fielders["RF"].pos[:] = ha._to_screen(*point)
    anim.fielders["SS"].pos[:] = ha._to_screen(*BASE_FT[2])
    cutoff_y = (point[1]+BASE_FT[2][1])/2 if ready_cutoff else point[1]/2
    anim.fielders["2B"].pos[:] = ha._to_screen(point[0]/2, cutoff_y)
    anim.fielders["C"].pos[:] = ha._to_screen(*BASE_FT[4])
    anim._ball = anim._ball_shadow = tuple(anim.fielders["RF"].pos)
    anim._begin_return_play()
    anim._stand_down_non_primary(keep_at_bag=True)


def _early_send(anim):
    anim.runner = BatterRun(4.3)
    anim._circuits["B"] = CircuitRun(anim.runner, 27)
    anim.start_time = 0
    anim._elapsed = 400
    assert anim.send_runner()
    assert not anim.send_runner()


@pytest.mark.parametrize("step", [16, 250])
def test_send_risks_second_on_a_single_without_a_speed_boost_or_automatic_escape(step):
    anim = _animation()
    _early_send(anim)
    _pickup(anim)
    record = _finish(anim, step)
    result = record.running_result
    assert result.outcome == "SINGLE"
    assert result.hit_bases == 1
    assert result.batter.final_base is None
    assert result.running_outs == 1
    assert anim._circuits["B"].top_fts == 27
    assert not any(e.label == "RETURN" for e in result.events)
    assert any(e.label == "SEND 2B" for e in record.events)
    assert any(e.label == "MANUAL ADVANCE 2B" for e in record.events)
    event = next(e for e in record.events if e.label == "TAG OUT 2B")
    frame = record.sample(event.time_ms)
    assert frame.runner.state == "out"
    assert frame.runner.base == 1
    assert frame.base_call[:2] == ("OUT", 2)
    assert not any(e.label == "BASE TOUCHED 2B" for e in record.events)


@pytest.mark.parametrize("step", [16, 250])
def test_one_send_stops_at_second_even_when_another_base_might_be_safe(step):
    anim = _animation()
    _early_send(anim)
    assert anim.baserunning.pending_base == 2
    _pickup(anim, time=7.0, point=(0, 380), ready_cutoff=True)
    record = _finish(anim, step)
    manual = [e for e in record.events if e.label.startswith("MANUAL ADVANCE")]
    assert [(e.runner_id, e.base) for e in manual] == [("B", 2)]
    assert record.running_result.batter.final_base == 2
    assert not any(e.base == 3 and e.label.startswith("BASE TOUCHED") for e in record.events)



@pytest.mark.parametrize("step", [16, 250])
def test_held_runner_can_be_sent_after_a_catch_without_backdating_departure(step):
    anim = _animation(bases=(3,), shape="FLY")
    anim.start_time = 0
    anim._elapsed = 4000
    anim.fielders["CF"].pos[:] = ha._to_screen(0, 150)
    anim._trigger_in_flight_intercept("CF", tuple(anim.fielders["CF"].pos))
    assert anim._circuits["3"].target_base == 3
    assert not anim.send_runner()  # tag reaction has not elapsed
    anim.update(4500)
    assert anim.send_runner()
    route = anim._circuits["3"]
    assert route.target_base == 4
    assert route.position_at(4.49) == BASE_FT[3]
    event = next(e for e in anim._running_events if e.label == "MANUAL ADVANCE")
    assert event.time_s == 4.5
    record = _finish(anim, step)
    assert record.running_result.outcome == "FLYOUT"
    assert any(e.label == "MANUAL ADVANCE HOME" for e in record.events)


def test_retreat_cannot_run_into_a_base_reserved_by_another_runner():
    anim = _animation(bases=(2, 3), shape="GROUNDER")
    anim.start_time = 0
    anim._elapsed = 400
    anim._sync_baserunning(0.4)
    assert anim.baserunning.runner_id == "3"
    assert not anim.retreat_runner()
    assert anim._circuits["3"].target_base == 4
    assert not anim._circuits["3"].returning
    assert not anim.baserunning.commands



@pytest.mark.parametrize("shape", ["LINER", "FLY", "POP_UP"])
@pytest.mark.parametrize("bases,outs", [((), 0), ((1, 2, 3), 0), ((1, 2), 2)])
@pytest.mark.parametrize("level", ["sandlot", "minors", "league", "gold_glove"])
@pytest.mark.parametrize("hand", ["R", "L"])
def test_manual_without_input_never_advances_more_than_one_base(shape, bases, outs, level, hand):
    anim = _animation("manual", shape=shape, bases=bases, outs=outs, level=level, hand=hand)
    anim.update(0)
    record = _finish(anim)
    for rid, route in anim._circuits.items():
        through = anim._inning_end_s if anim._inning_end_s is not None else float("inf")
        assert all(base <= route.start_base+1 for base, _ in route.touches(through))
    if record.running_result is not None:
        for movement in record.running_result.movements:
            assert movement.final_base is None or movement.final_base <= movement.start_base+1
    assert not anim.baserunning.commands



def test_two_out_catch_cancels_an_armed_instruction_and_any_apparent_run(monkeypatch):
    monkeypatch.setattr(defense, "roll_misplay", lambda *a, **kw: None)
    anim = _animation(bases=(1, 2), shape="POP_UP", outs=2)
    anim.start_time = 0
    anim._elapsed = 400
    assert anim.send_runner()
    anim._elapsed = 4000
    anim.fielders["CF"].pos[:] = ha._to_screen(0, 150)
    anim._trigger_in_flight_intercept("CF", tuple(anim.fielders["CF"].pos))
    record = _finish(anim)
    assert anim.baserunning.state == "expired"
    assert not any(e.label.startswith("MANUAL ADVANCE") for e in record.events)
    keeper = ScoreKeeper()
    keeper.runners = [Runner(b) for b in (1, 2)]
    assert keeper.update_running_play(record.running_result, outs=2).runs == 0


@pytest.mark.parametrize("margin", [-0.5, 0.5])
@pytest.mark.parametrize("step", [16, 250])
def test_send_cannot_bypass_the_first_base_force(margin, step, monkeypatch):
    anim = _animation()
    anim.shape = "GROUNDER"
    _early_send(anim)
    anim._elapsed = anim._secured_at_ms = 2000
    anim._secured = True
    anim._primary_role = "SS"
    anim.fielders["SS"].pos[:] = ha._to_screen(55, 90)
    timing = anim._begin_infield_play("SS")
    # Preserve the fitted run; choose a received-ball clock on either side.
    from dataclasses import replace
    timing = replace(timing, defense_s=timing.runner_s + margin)
    anim.play_timing = timing
    anim._first_base_retired = margin < 0
    anim.classified_outcome = "GROUNDOUT" if margin < 0 else "SINGLE"
    anim._first_base_call_s = min(timing.runner_s, timing.defense_s)
    anim._go_throw_arrive_ms = anim._anim_ms(timing.defense_s)
    anim._go_done_ms = anim._anim_ms(max(timing.runner_s, timing.defense_s) + 0.5)
    record = _finish(anim, step)
    if margin < 0:
        assert record.outcome == "GROUNDOUT"
        assert not any(e.label.startswith("MANUAL ADVANCE") for e in record.events)
    else:
        assert record.outcome == "SINGLE"
        sent = next(e for e in record.events if e.label == "MANUAL ADVANCE 2B")
        assert sent.time_ms >= anim._anim_ms(max(timing.runner_s, timing.defense_s))
        assert anim.runner_first_s == timing.runner_s
        assert record.running_result.batter.touches[0] == (1, timing.runner_s)


def test_released_throw_is_preserved_when_a_new_runner_becomes_a_threat():
    anim = _animation(bases=(3,))
    anim.baserunning.mode = "auto"
    anim.runner = BatterRun(4.3)
    anim._circuits["B"] = CircuitRun(anim.runner, 27)
    anim._circuits["3"].commit_next(3.1)
    anim.start_time = 0
    _pickup(anim, point=(-200, 250))
    original = anim._return_legs[0]
    anim.update(anim._anim_ms(original.release_s + 0.01))
    anim._circuits["B"].commit_next(anim._elapsed/1000)
    anim._running_events.append(ha.RunningEvent(anim._elapsed/1000, "MANUAL ADVANCE", "B", 2))
    _finish(anim)
    assert anim._return_legs[0] == original


@pytest.mark.parametrize("step", [16, 250])
def test_queued_send_changes_an_unreleased_throw_after_visible_rounding(step):
    anim = _animation(bases=(2,), shape="GROUNDER")
    _early_send(anim)
    _pickup(anim, time=3.0)
    original = anim._return_legs[0]
    assert anim._return_base == 2
    record = _finish(anim, step)
    sent = next(e for e in record.events if e.label == "MANUAL ADVANCE HOME")
    redirected = next(e for e in record.events if e.label == "THROW REDIRECT HOME")
    assert redirected.time_ms >= sent.time_ms + anim._anim_ms(anim.defense.reaction_min_s) - 1e-8
    assert redirected.time_ms < anim._anim_ms(original.release_s)
    assert anim._return_legs[0] != original
    assert anim._return_runner == "2"


@pytest.mark.parametrize("step", [16, 250])
def test_cutoff_can_redirect_to_an_existing_runner_instead_of_only_the_batter(step):
    anim = _animation("auto", bases=(1, 3), shape="FLY")
    anim._circuits["B"].stopped_at_s = 4.0
    anim._runner_stop_s = 4.0
    lead = anim._circuits["3"] = CircuitRun(None, 25, start_base=3)
    lead.commit_next(4.2)
    follower = anim._circuits["1"] = CircuitRun(None, 20, start_base=1)
    follower.commit_next(4.2)
    anim._secured_in_flight = True
    anim.start_time = 0
    _pickup(anim, time=4.0, point=(35, 205))
    assert anim._return_base == 4
    original = anim._return_legs[0]
    record = _finish(anim, step)
    redirect = next(e for e in record.events if e.label == "CUTOFF REDIRECT 2B")
    assert redirect.runner_id == "1"
    assert anim._return_legs[0] == original
    assert any(e.label == "RETURN 3B" for e in record.events)


@pytest.mark.parametrize("step", [16, 250])
def test_lead_send_continues_after_the_batter_is_retired_at_first(step):
    from dataclasses import replace
    anim = _animation(bases=(2,), shape="GROUNDER")
    _early_send(anim)
    anim._elapsed = anim._secured_at_ms = 1000
    anim._secured = True
    anim._primary_role = "SS"
    anim.fielders["SS"].pos[:] = ha._to_screen(55, 90)
    timing = anim._begin_infield_play("SS")
    anim.play_timing = replace(timing, defense_s=3.0)
    anim._first_base_retired = True
    anim.classified_outcome = "GROUNDOUT"
    anim._first_base_call_s = 3.0
    anim._go_throw_arrive_ms = 3000
    record = _finish(anim, step)
    assert record.outcome == "GROUNDOUT"
    assert record.running_result.hit_bases == 0
    assert record.running_result.batter.out_s == 3.0
    sent = next(e for e in record.events if e.label == "MANUAL ADVANCE HOME")
    assert sent.runner_id == "2"
    assert sent.time_ms >= 3000


@pytest.mark.parametrize("step", [16, 250])
def test_defense_tags_one_runner_then_throws_at_another_with_two_running_outs(step):
    anim = _animation(bases=(3,), outs=1)
    anim._circuits["3"].commit_next(1.4)
    anim.runner = BatterRun(4.3)
    anim._circuits["B"] = CircuitRun(anim.runner, 27)
    anim.start_time = 0
    _pickup(anim, point=(40, 100))
    assert anim._return_runner == "3"
    recorder = FieldingRecorder(anim, "two tags")
    while anim._circuits["3"].stopped_at_s is None:
        anim.update(anim._elapsed + step)
        recorder.capture(anim)
    assert anim.baserunning.runner_id == "B"
    assert anim.send_runner()
    record = _finish(anim, step, recorder)
    result = record.running_result
    assert result.running_outs == result.outs_added == 2
    tags = [e for e in record.events if e.label.startswith("TAG OUT")]
    assert [(e.runner_id, e.base) for e in tags] == [("3", 4), ("B", 2)]
    assert any(e.label == "FOLLOW-UP THROW 2B" for e in record.events)
    for event in tags:
        frame = record.sample(event.time_ms)
        runner = next(r for r in (frame.runner,) + frame.runners if r.runner_id == event.runner_id)
        assert runner.state == "out"
        assert frame.base_call[:2] == ("OUT", event.base)
        receiver = next(f for f in frame.fielders if f.role == event.role)
        assert receiver.glove == pytest.approx((runner.pos[0], runner.pos[1]-9))
    keeper = ScoreKeeper()
    keeper.runners = [Runner(3)]
    assert keeper.update_running_play(result, outs=1).running_outs == 2



def test_send_window_stays_open_while_running_then_closes_after_settlement():
    anim = _animation()
    anim.runner = BatterRun(4.3)
    anim._circuits["B"] = CircuitRun(anim.runner, 27)
    anim.start_time = 0
    _pickup(anim)
    anim.update(5000)
    closing = anim.baserunning.closes_s
    assert closing > 7.0
    assert anim.baserunning.available(5.0)
    anim.update(anim._anim_ms(closing))
    assert not anim.send_runner()
    assert anim.baserunning.runner_id == "B"



def _simulation(anim, calls):
    game = anim.game
    game.screen = pygame.Surface((1280, 720))
    game._fielding_play_number = 0
    game.banner = SimpleNamespace(update=lambda dt: None, draw=lambda: None)
    game.flip_display = lambda: None
    game.key_binding_manager = KeyBindingManager(None)
    sim = object.__new__(PitchSimulation)
    sim.game, sim.hit_animation, sim._fielding_recorder = game, anim, None
    sim.pitchtype, sim.speed_mph = "FASTBALL", 95
    sim._publish_review = lambda: calls.append("publish")
    sim._finish_pitch = lambda: calls.append("continue")
    return sim


def test_send_input_is_timestamped_and_never_serves_as_continue(monkeypatch):
    pygame.font.init()
    anim = _animation()
    anim.update(0)
    calls = []
    sim = _simulation(anim, calls)
    # Host frame arrives after the window, but input was pressed within it.
    monkeypatch.setattr(pygame.event, "get", lambda: [
        pygame.event.Event(pygame.KEYDOWN, key=pygame.K_g, timestamp=400)])
    sim._handle_hit_animation_phase(1100, 0.016)
    assert anim.baserunning.requested_s == 0.4
    assert calls == []
    # A repeated/late Send remains consumed after the result appears.
    anim.finished = anim.banner_fired = True
    monkeypatch.setattr(pygame.event, "get", lambda: [
        pygame.event.Event(pygame.KEYDOWN, key=pygame.K_g, repeat=True)])
    sim._handle_hit_animation_phase(1116, 0.016)
    assert "continue" not in calls


def test_manual_overlay_is_recorded_and_replay_draws_the_same_frame():
    pygame.font.init()
    anim = _animation()
    anim.update(0)
    anim.update(400)
    recorder = FieldingRecorder(anim, "send overlay")
    frame = anim.presentation_frame()
    assert frame.send_control[0:2] == ("B", "available")
    live, replay = pygame.Surface((1280, 720)), pygame.Surface((1280, 720))
    draw_frame(live, frame)
    draw_frame(replay, recorder.frames[-1])
    assert pygame.image.tobytes(live, "RGB") == pygame.image.tobytes(replay, "RGB")


def test_settings_and_rebinding_persist_and_invalid_mode_falls_back_to_auto(tmp_path):
    settings = SettingsManager()
    settings.settings_file = str(tmp_path / "settings.json")
    assert settings.get_baserunning_mode() == "auto"
    assert settings.cycle_baserunning_mode() == "manual"
    assert json.loads((tmp_path / "settings.json").read_text())["baserunning_mode"] == "manual"
    assert SettingsPanel().value_for("baserunning", settings) == ("MANUAL", False)
    settings.current_settings["baserunning_mode"] = "invalid"
    assert settings.get_baserunning_mode() == "auto"
    bindings = KeyBindingManager(settings)
    bindings.settings_file = str(tmp_path / "bindings.json")
    bindings.bind_key(KeyAction.SEND_RUNNER, pygame.K_j)
    assert json.loads((tmp_path / "bindings.json").read_text())["send_runner"] == pygame.K_j
    assert KeyAction.SEND_RUNNER in KeyBindingsPanel.ACTIONS


def test_mode_migration_preserves_unknown_history(tmp_path):
    path = str(tmp_path / "v13.db")
    connection = sqlite3.connect(path)
    connection.executescript(PitchDB.SCHEMA)
    connection.execute("ALTER TABLE pitches DROP COLUMN baserunning_mode")
    connection.execute("INSERT INTO pitches (pitch_id, session_id, game_mode, difficulty, created_at, "
        "pitcher_name, pitch_type) VALUES ('p', 's', 'arcade', 'amateur', '2026-01-01', 'Sale', 'FASTBALL')")
    connection.execute("PRAGMA user_version = 13")
    connection.commit()
    connection.close()
    db = PitchDB(path)
    try:
        assert db.conn.execute("SELECT baserunning_mode FROM pitches").fetchone()[0] is None
        assert db.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    finally:
        db.close()


@pytest.mark.parametrize("infield_out", [False, True])
def test_manual_finalization_preserves_hit_credit_outs_and_control_metadata(infield_out):
    anim = _animation(shape="GROUNDER" if infield_out else "LINER")
    _early_send(anim)
    if infield_out:
        anim._elapsed = anim._secured_at_ms = 1000
        anim._secured = True
        anim._primary_role = "SS"
        anim.fielders["SS"].pos[:] = ha._to_screen(55, 90)
        anim._begin_infield_play("SS")
        assert anim._first_base_retired
    else:
        _pickup(anim)
    _finish(anim)
    keeper = ScoreKeeper()
    manager = object.__new__(HitOutcomeManager)
    manager.score_keeper = keeper
    game = SimpleNamespace(currentouts=0, hits=0, last_pitch_information=[], ball=(640, 400),
        in_gameday_mode=False, scoreKeeper=keeper, hit_outcome_manager=manager,
        field_renderer=SimpleNamespace(record_at_bat=lambda: None, record_hit=lambda *a, **k: None),
        banner=SimpleNamespace(show_banner=lambda text: None))
    sim = object.__new__(PitchSimulation)
    sim.game, sim.hit_animation, sim.new_entry = game, anim, {}
    sim._finalize_batted_ball()
    assert game.currentouts == 1
    assert game.hits == int(not infield_out)
    assert sim.baserunning_mode == "manual"
    saved = json.loads(sim.running_play_json)
    assert saved["schema_version"] == 3
    assert saved["outcome"] == ("GROUNDOUT" if infield_out else "SINGLE")
    assert saved["control"]["requested_s"] == 0.4
    assert saved["control"]["state"] == "expired"
    assert saved["control"]["reason"] == "runner retired"
    assert saved["control"]["commands"][0]["base"] == 2
    assert not any(keeper.isRunnerOnBase(b) for b in (1, 2, 3))


def test_adding_send_preserves_custom_legacy_keys_and_reserves_swing_keys(tmp_path):
    bindings = KeyBindingManager(None)
    bindings.settings_file = str(tmp_path / "old_keys.json")
    old = dict(bindings.default_bindings)
    old.pop("send_runner")
    old["fielding_replay"] = pygame.K_g
    (tmp_path / "old_keys.json").write_text(json.dumps(old))
    migrated = bindings.load_bindings()
    assert migrated["fielding_replay"] == pygame.K_g
    assert migrated["send_runner"] != pygame.K_g
    assert migrated["send_runner"] not in old.values()
    for key in (pygame.K_w, pygame.K_e, pygame.K_F11):
        assert not bindings.is_key_available(key, exclude_action=KeyAction.SEND_RUNNER)


@pytest.mark.parametrize("panel_type", [SettingsPanel, KeyBindingsPanel])
def test_scroll_makes_every_control_visible_and_clickable(panel_type):
    pygame.font.init()
    surface = pygame.Surface((1280, 720))
    panel = panel_type()
    manager = SettingsManager() if panel_type is SettingsPanel else KeyBindingManager(None)
    for key in panel._nav_keys:
        panel.select_key(key)
        panel.render(surface, manager)
        if key == SettingsPanel.DIFFICULTY_KEY:
            continue
        rect = next(r for r, drawn in panel._row_rects if drawn == key)
        assert 120 <= rect.top < rect.bottom <= 618
        assert panel.hit_test(rect.center) == key
    assert panel._scroll_y > 0
    panel.reset_cursor()
    panel.render(surface, manager)
    assert panel._scroll_y == 0


@pytest.mark.parametrize("step", [16, 250])
def test_each_additional_send_names_one_more_base_and_requires_another_press(step):
    anim = _animation()
    _early_send(anim)
    _pickup(anim, time=7.0, point=(0, 380), ready_cutoff=True)
    assert anim._circuits["B"].target_base == 2
    anim.update(8000)
    assert anim.send_runner()
    frame = anim.presentation_frame()
    assert frame.send_control[3] == 2  # current leg
    assert frame.send_control[8] == 3  # explicitly queued next destination
    assert not anim.send_runner()
    record = _finish(anim, step)
    assert [c["base"] for c in anim.baserunning.commands if c["action"] == "send"] == [2, 3]
    assert [e.base for e in record.events if e.label.startswith("MANUAL ADVANCE")] == [2, 3]
    assert not any(e.base == 4 and e.label.startswith("BASE TOUCHED") for e in record.events)


def test_send_is_available_well_after_the_initial_takeoff_window():
    anim = _animation()
    anim.runner = BatterRun(4.3)
    anim._circuits["B"] = CircuitRun(anim.runner, 27)
    anim.start_time = 0
    _pickup(anim)
    anim.update(6000)
    assert not anim.finished
    assert anim._circuits["B"].target_base == 1
    assert anim.send_runner()
    assert anim.baserunning.requested_s == 6.0
    assert anim._circuits["B"].target_base == 2
    _finish(anim)


def test_retreat_can_cancel_a_queued_base_without_reversing_the_force_to_first():
    anim = _animation()
    _early_send(anim)
    anim._elapsed = 600
    assert anim.retreat_runner()
    assert anim.baserunning.pending_base is None
    assert anim._circuits["B"].target_base == 1
    assert not anim._circuits["B"].returning
    assert anim.baserunning.commands[0]["status"] == "cancelled"
    _pickup(anim, time=7.0, point=(0, 380), ready_cutoff=True)
    record = _finish(anim)
    assert record.running_result.batter.final_base == 1
    assert any(e.label == "CANCEL SEND 1B" for e in record.events)


def test_retreat_and_resend_preserve_every_previously_observed_position_and_touch():
    anim = _animation()
    _early_send(anim)
    _pickup(anim, time=7.0, point=(0, 380), ready_cutoff=True)
    anim.update(8200)
    route = anim._circuits["B"]
    past = [(t, route.position_at(t)) for t in (4.0, 4.3, 7.0, 7.5, 8.2)]
    touches = route.touches(8.2)
    assert anim.retreat_runner()
    assert route.returning and route.target_base == 1
    assert route.touches(8.2) == touches
    assert all(route.position_at(t) == p for t, p in past)
    anim.update(8500)
    past += [(8.5, route.position_at(8.5))]
    assert anim.send_runner()
    assert not route.returning and route.target_base == 2
    assert all(route.position_at(t) == p for t, p in past)
    assert [c["action"] for c in anim.baserunning.commands] == ["send", "retreat", "send"]
    _finish(anim)


@pytest.mark.parametrize("step", [16, 250])
def test_an_early_manual_retreat_can_save_a_runner_with_real_return_motion(step):
    anim = _animation()
    _early_send(anim)
    _pickup(anim)
    anim.update(5000)
    point = anim._circuits["B"].position_at(5.0)
    assert anim.retreat_runner()
    assert anim._circuits["B"].position_at(5.0) == point
    record = _finish(anim, step)
    assert record.running_result.batter.final_base == 1
    assert record.running_result.running_outs == 0
    assert any(e.label == "MANUAL RETURN 1B" for e in record.events)


@pytest.mark.parametrize("step", [16, 250])
def test_defense_can_throw_back_and_tag_a_retreating_runner_at_a_previously_touched_bag(step):
    anim = _animation()
    _early_send(anim)
    _pickup(anim)
    original = anim._return_legs[0]
    anim.update(6900)
    touched = anim._circuits["B"].touches(6.9)
    assert len(touched) == 1 and touched[0][0] == 1
    assert anim.retreat_runner()
    assert anim.presentation_frame().base_call is None
    record = _finish(anim, step)
    assert anim._return_legs[0] == original
    assert record.running_result.batter.final_base is None
    assert record.running_result.running_outs == 1
    assert record.running_result.batter.touches == touched
    tag = next(e for e in record.events if e.label == "TAG OUT 1B")
    frame = record.sample(tag.time_ms)
    assert frame.runner.state == "out"
    assert frame.base_call[:2] == ("OUT", 1)
    receiver = next(f for f in frame.fielders if f.role == tag.role)
    assert receiver.glove == pytest.approx((frame.runner.pos[0], frame.runner.pos[1]-9))


def test_a_mandatory_first_base_leg_cannot_be_retreating_and_auto_ignores_both_commands():
    for mode in ("manual", "auto"):
        anim = _animation(mode)
        anim.update(0)
        anim.update(1000)
        assert not anim.retreat_runner()
        if mode == "auto":
            assert not anim.send_runner()
        assert not anim._circuits["B"].returning


def test_retreat_is_remappable_and_is_never_a_continue_key(monkeypatch):
    pygame.font.init()
    anim = _animation()
    anim.update(0)
    calls = []
    sim = _simulation(anim, calls)
    sim.game.key_binding_manager.current_bindings["retreat_runner"] = pygame.K_j
    monkeypatch.setattr(pygame.event, "get", lambda: [
        pygame.event.Event(pygame.KEYDOWN, key=pygame.K_j, timestamp=500)])
    sim._handle_hit_animation_phase(1100, 0.016)
    assert not anim._circuits["B"].returning  # force at first remains required
    assert "continue" not in calls
    assert sim._retreat_key_held
    assert KeyAction.RETREAT_RUNNER in KeyBindingsPanel.ACTIONS


def test_send_then_retreat_in_the_same_input_frame_cancels_the_queue(monkeypatch):
    pygame.font.init()
    anim = _animation()
    anim.update(0)
    sim = _simulation(anim, [])
    monkeypatch.setattr(pygame.event, "get", lambda: [
        pygame.event.Event(pygame.KEYDOWN, key=pygame.K_g, timestamp=400),
        pygame.event.Event(pygame.KEYDOWN, key=pygame.K_d, timestamp=400)])
    sim._handle_hit_animation_phase(800, 0.016)
    assert anim.baserunning.pending_base is None
    assert anim._circuits["B"].target_base == 1
    assert [c["action"] for c in anim.baserunning.commands] == ["send", "hold"]
    assert anim.baserunning.commands[0]["status"] == "cancelled"


def test_hold_confirms_a_settled_runner_without_waiting_for_the_longer_window():
    anim = _animation()
    anim.runner = BatterRun(4.3)
    anim._circuits["B"] = CircuitRun(anim.runner, 27)
    anim.start_time = 0
    _pickup(anim)
    anim.update(5000)
    deadline = anim.baserunning.closes_s
    frame = anim.presentation_frame()
    assert frame.send_control[5] == 1 and frame.send_control[9]  # D HOLD AT 1B
    assert anim.retreat_runner()
    record = _finish(anim)
    assert record.duration_ms < anim._anim_ms(deadline)
    assert record.running_result.batter.final_base == 1
    assert anim.baserunning.reason == "player held"
    assert anim.baserunning.commands[-1]["action"] == "hold"


def test_late_send_of_a_leader_never_rewinds_the_batter_retired_at_first():
    from dataclasses import replace
    anim = _animation(bases=(2,), shape="GROUNDER")
    anim.runner = BatterRun(4.3)
    anim._circuits["B"] = CircuitRun(anim.runner, 27)
    anim.start_time = 0
    anim._elapsed = anim._secured_at_ms = 1000
    anim._secured = True
    anim._primary_role = "SS"
    anim.fielders["SS"].pos[:] = ha._to_screen(55, 90)
    timing = anim._begin_infield_play("SS")
    anim.play_timing = replace(timing, defense_s=3.0)
    anim._first_base_retired = True
    anim.classified_outcome = "GROUNDOUT"
    anim._first_base_call_s = 3.0
    anim._go_throw_arrive_ms = 3000
    anim.update(5000)
    batter = anim._circuits["B"]
    past = [(t, batter.position_at(t)) for t in (2.0, 3.0, 4.0, 5.0)]
    assert batter.stopped_at_s == 3.0
    assert anim.baserunning.runner_id == "2"
    assert anim.send_runner()
    assert all(batter.position_at(t) == point for t, point in past)
    _finish(anim)
