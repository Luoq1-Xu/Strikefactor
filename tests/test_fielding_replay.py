"""Replay captures what happened without ever running the play a second time."""

import random
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import pygame
import pytest

from strikefactor.gameplay.fielding_record import FieldingEvent, FieldingRecorder
from strikefactor.gameplay.hit_animation import HitAnimation
from strikefactor.ui.fielding_renderer import draw_frame


class GameStub:
    internal_width, internal_height = 1280, 720

    def __init__(self):
        self.batter = SimpleNamespace(get_handedness=lambda: "R")
        self.settings_manager = SimpleNamespace(get_difficulty_multipliers=lambda: {"out_probability_modifier": 1.0})


def play(seed=4, shape="GROUNDER", outcome="IN_PLAY", capture=True):
    random.seed(seed)
    animation = HitAnimation(GameStub(), outcome, lambda: pytest.fail("Replay fired a gameplay callback"),
                             quality=0.8, batted_ball_type=shape, spray_deg=18.0,
                             ev_mph=95.0, launch_deg={"GROUNDER": 2.0, "LINER": 15.0, "FLY": 32.0}[shape])
    recorder = FieldingRecorder(animation, "PLAY 1 / FF 93 MPH") if capture else None
    for t in range(0, 60000, 16):
        animation.update(1000 + t)
        if recorder:
            recorder.capture(animation)
        if animation.finished:
            break
    assert animation.finished
    return animation, recorder


@pytest.mark.parametrize("shape,outcome", [(s, o) for s in ("GROUNDER", "LINER", "FLY")
                                          for o in ("IN_PLAY", "FOUL", "HOME RUN")])
def test_capture_preserves_original_result_positions_and_random_state(shape, outcome):
    baseline, _ = play(shape=shape, outcome=outcome, capture=False)
    baseline_random = random.getstate()
    captured, recorder = play(shape=shape, outcome=outcome)
    assert random.getstate() == baseline_random
    assert captured.classified_outcome == baseline.classified_outcome
    assert captured.presentation_frame() == baseline.presentation_frame()
    rec = recorder.record
    assert rec is not None
    assert rec.frames[-1] == captured.presentation_frame()
    assert len(rec.frames[-1].fielders) == 9
    assert rec.events[0].label == "CONTACT"
    assert rec.events[-1].label == "END"
    for frame in rec.frames:
        assert rec.sample(frame.time_ms) == frame
    # Waiting at the continue prompt cannot lengthen or alter the clip.
    captured.update(100000)
    recorder.capture(captured)
    assert recorder.record is rec
    assert rec.frames[-1] != captured.presentation_frame()


def test_frames_are_independent_of_mutable_animation():
    anim, recorder = play()
    rec = recorder.record
    before = rec.frames[-1]
    anim.fielders["SS"].pos[0] += 100
    assert rec.frames[-1] == before
    with pytest.raises(FrozenInstanceError):
        before.ball = (0, 0)


def test_interpolation_holds_at_collisions_and_clamps_endpoints():
    _, recorder = play()
    rec = recorder.record
    a = rec.frames[0]
    b = replace(a, time_ms=100, ball=(a.ball[0] + 100, a.ball[1]))
    rec = replace(rec, frames=(a, b), events=())
    assert rec.sample(50).ball[0] == pytest.approx(a.ball[0] + 50)
    assert rec.sample(-100) == a
    assert rec.sample(10000) == b
    rec = replace(rec, events=(FieldingEvent(100, "BALL SECURED"),))
    assert rec.sample(99) == a
    assert rec.sample(100) == b


def test_overflow_withholds_the_incomplete_recording():
    anim, _ = play(capture=False)
    anim.finished = False
    recorder = FieldingRecorder(anim, "overflow")
    recorder.MAX_FRAMES = 1
    anim._elapsed += 16
    anim.finished = True
    recorder.capture(anim)
    assert recorder.incomplete
    assert recorder.record is None
    assert not recorder.frames


def test_live_and_replay_render_identically_at_saved_frames():
    pygame.font.init()
    anim, recorder = play()
    live, replay = pygame.Surface((1280, 720)), pygame.Surface((1280, 720))
    anim.draw(live)
    draw_frame(replay, recorder.record.frames[-1])
    assert pygame.image.tobytes(live, "RGB") == pygame.image.tobytes(replay, "RGB")


def _continue_screen(monkeypatch, event):
    from strikefactor.gameplay.pitch_simulation import PitchSimulation
    from strikefactor.key_binding_manager import KeyAction

    pygame.font.init()
    anim, recorder = play()
    calls = []
    anim.on_complete = lambda: calls.append("finalize")
    game = GameStub()
    game.screen = pygame.Surface((1280, 720))
    game._fielding_play_number = 0
    game.last_fielding_play = None
    game.ui_manager = SimpleNamespace(update=lambda dt: None, draw=lambda: None)
    game.flip_display = lambda: None
    game.request_fielding_replay = lambda **kw: calls.append("replay")
    game._window_to_internal = lambda x, y: (x, y)
    game.key_binding_manager = SimpleNamespace(
        get_key_for_action=lambda a: pygame.K_f if a == KeyAction.FIELDING_REPLAY else None,
        get_key_name=lambda k: "F")
    sim = object.__new__(PitchSimulation)
    sim.game, sim.hit_animation, sim._fielding_recorder = game, anim, recorder
    sim._finish_pitch = lambda: calls.append("finish")
    monkeypatch.setattr(pygame.event, "get", lambda: [event])
    sim._handle_hit_animation_phase(anim.start_time + anim._elapsed, 0.016)
    assert game.last_fielding_play is recorder.record
    sim._handle_hit_animation_phase(anim.start_time + anim._elapsed + 16, 0.016)
    return calls


def test_continue_screen_replay_does_not_advance_or_finalize_twice(monkeypatch):
    calls = _continue_screen(monkeypatch, pygame.event.Event(pygame.KEYDOWN, key=pygame.K_f))
    assert calls == ["finalize", "replay", "replay"]


def test_continue_screen_has_no_review_button(monkeypatch):
    # The on-screen REVIEW [F] button is gone; a click where it sat advances the play.
    click = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(640, 638))
    calls = _continue_screen(monkeypatch, click)
    assert calls[:2] == ["finalize", "finish"]


def test_live_pitch_cannot_open_replay():
    from strikefactor.main import Game

    game = SimpleNamespace(state_manager=SimpleNamespace(current_state=SimpleNamespace(
        pitch_simulation=SimpleNamespace(running=True, hit_animation=None))))
    game.request_review = lambda **kw: Game.request_review(game, **kw)
    # No UI or record is consulted until the active pitch has finished: the
    # stub owns no `review_overlay`, so reaching one would raise here.
    Game.request_fielding_replay(game)


def test_recording_includes_original_throw_events():
    _, recorder = play()
    labels = [e.label for e in recorder.record.events]
    assert "BALL SECURED" in labels
    assert "THROW RELEASE" in labels
    assert "THROW ARRIVAL" in labels
    assert labels.index("BALL SECURED") <= labels.index("THROW RELEASE") < labels.index("THROW ARRIVAL")


def test_misplay_is_recorded_even_when_it_is_not_charged_as_an_error(monkeypatch):
    from strikefactor.gameplay import defense
    monkeypatch.setattr(defense, "roll_misplay", lambda *a, **kw: "MUFF" if kw["in_air"] else "THROUGH")
    anim, recorder = play(shape="FLY")
    assert anim._misplay_kind is not None
    event = next(e for e in recorder.record.events if e.label == "MISPLAY")
    assert event.role == anim._misplay_role
    frame = recorder.record.sample(event.time_ms)
    assert frame.time_ms == event.time_ms
    if anim._error_role is not None:
        assert any(f.error is not None for f in recorder.record.frames)


def test_wall_rebound_does_not_invent_a_bounce_before_the_ball_lands():
    import conftest

    from strikefactor.gameplay import park, spray
    bearing = spray.field_angle_rad(18.0, 1.0)
    velocities = [v / 10 for v in range(800, 1300)
                  if park.fence_verdict(30.0, v / 10, bearing) == park.OFF_THE_WALL]
    ev = (velocities[0] + velocities[-1]) / 2
    random.seed(7)
    # `uncaught`, because this is about the event list a carom records and a
    # ball that reaches the fence arrives within an outfielder's reach — so
    # whether this one gets there to be recorded at all would otherwise be a
    # question about the defense. See the helper.
    anim = conftest.uncaught(
        HitAnimation(GameStub(), "IN_PLAY", lambda: None, quality=0.9,
                     batted_ball_type="FLY", spray_deg=18.0, launch_deg=30.0,
                     ev_mph=ev))
    recorder = FieldingRecorder(anim, "wall")
    for t in range(0, 60000, 16):
        anim.update(t)
        recorder.capture(anim)
        if anim.finished:
            break
    assert recorder.record is not None
    wall = next(e for e in recorder.record.events if e.label == "WALL IMPACT")
    secured = next(e for e in recorder.record.events if e.label == "BALL SECURED")
    assert secured.time_ms > wall.time_ms
    # This play ends with the ball secured during the wall drop. Recording
    # initialization of ground motion must not manufacture a grass bounce.
    assert not any(e.label == "BOUNCE" for e in recorder.record.events)
    assert recorder.record.sample(wall.time_ms).ball_visible
