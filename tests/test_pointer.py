"""Hover and wheel input read the pointer in the internal 1280x720 frame.

The game is drawn to a fixed surface and letterboxed into the window, so once
the window is resized or fullscreen, window pixels are not layout pixels.
Panels that asked `pygame.mouse.get_pos()` directly scrolled only when the raw
pointer happened to sit over the *unscaled* rect.
"""

import pygame

from strikefactor.ui import gameday_theme as gdt
from strikefactor.ui import pointer
from strikefactor.ui.play_by_play_panel import PlayByPlayPanel


def test_the_pointer_goes_through_the_installed_transform(monkeypatch):
    monkeypatch.setattr(pygame.mouse, "get_pos", lambda: (1000, 600))
    monkeypatch.setattr(pointer, "_to_internal", None)
    assert pointer.pos() == (1000, 600)
    pointer.install(lambda x, y: (x // 2, y // 2))
    assert pointer.pos() == (500, 300)


def test_the_wheel_scrolls_a_panel_under_a_scaled_pointer(monkeypatch):
    # A window twice the internal size: the pointer is over the panel in the
    # internal frame, and nowhere near it in raw window pixels.
    monkeypatch.setattr(pygame.mouse, "get_pos", lambda: (1000, 600))
    monkeypatch.setattr(pointer, "_to_internal", lambda x, y: (x // 2, y // 2))

    panel = PlayByPlayPanel(gdt.load_fonts())
    panel.set_plays([{"play_index": i, "inning": 1 + i // 6, "is_top": i % 2 == 0,
                      "batter_name": "Player", "pitcher_name": "sale",
                      "result": "SINGLE", "runs_scored": 0} for i in range(60)])
    panel.draw(pygame.Surface((1280, 720)), (400, 200, 300, 200))

    wheel = pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-1)
    assert panel.handle_event(wheel)
    assert panel.scroll > 0
