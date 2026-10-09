"""A pitch in the air must still answer the window.

The ball-flight phase drains the event queue to catch the swing key, and it
used to drain *everything*: a QUIT, a resize or F11 pressed while the ball was
in the air was consumed and dropped, so closing the window mid-pitch did
nothing. Both blocking loops now share `PitchSimulation._handle_window_event`.
"""

from types import SimpleNamespace

import pygame

from strikefactor.gameplay.pitch_simulation import PitchSimulation


def _in_flight_sim(calls):
    game = SimpleNamespace(
        _update_scaling=lambda: calls.append("rescale"),
        toggle_fullscreen=lambda: calls.append("fullscreen"),
        field_renderer=SimpleNamespace(draw_strikezone=lambda: None,
                                       draw_field=lambda bases: None),
        scoreKeeper=SimpleNamespace(get_bases=lambda: None),
        flip_display=lambda: calls.append("flip"),
        sound_manager=SimpleNamespace(glovepop=lambda: None),
    )
    sim = object.__new__(PitchSimulation)
    sim.game = game
    sim.running = True
    sim.sizz = True
    sim.arrival_time = 10_000
    sim.contact_time = 10_150
    sim.soundplayed = 1
    sim.on_time = 0
    sim.made_contact = "no_swing"
    sim._draw_batter = lambda now: None
    sim._update_ball_position = lambda now: None
    sim._handle_swing_input = lambda event, now: calls.append(("swing", event.key))
    return sim


def _flight_frame(monkeypatch, events):
    calls, posted = [], []
    sim = _in_flight_sim(calls)
    monkeypatch.setattr(pygame.event, "get", lambda: list(events))
    monkeypatch.setattr(pygame.event, "post", posted.append)
    sim._handle_ball_flight_phase(current_time=9_500)
    return sim, calls, posted


def test_closing_the_window_while_the_ball_is_in_the_air_ends_the_pitch(monkeypatch):
    quit_event = pygame.event.Event(pygame.QUIT)
    sim, calls, posted = _flight_frame(monkeypatch, [quit_event])
    assert sim.running is False
    assert posted == [quit_event], "the outer loop has to see the QUIT to exit"
    assert "flip" not in calls, "a stopped pitch must not draw another frame"


def test_a_resize_in_flight_is_honoured_and_the_swing_still_registers(monkeypatch):
    events = [pygame.event.Event(pygame.VIDEORESIZE, size=(800, 450), w=800, h=450),
              pygame.event.Event(pygame.KEYDOWN, key=pygame.K_w)]
    sim, calls, posted = _flight_frame(monkeypatch, events)
    assert sim.running is True
    assert posted == []
    assert calls[:2] == ["rescale", ("swing", pygame.K_w)]
    assert "flip" in calls


def test_f11_in_flight_toggles_fullscreen_rather_than_being_dropped(monkeypatch):
    sim, calls, _ = _flight_frame(
        monkeypatch, [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F11)])
    assert calls[0] == "fullscreen"
    assert ("swing", pygame.K_F11) not in calls
