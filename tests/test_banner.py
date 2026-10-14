"""The outcome banner (`ui/banner.py`), which replaced a pygame_gui label.

It was matched to that widget pixel for pixel while both existed. What is
pinned here is what keeps it matched: where it sits, the typing rule, and the
scheduling the umpire's call and the review modal depend on.
"""

import numpy as np
import pygame
import pytest

from strikefactor.ui.banner import OutcomeBanner


@pytest.fixture
def surface():
    surf = pygame.Surface((1280, 720))
    surf.fill("black")
    return surf


def _type_all(banner, per_letter=0.1):
    for _ in range(len(banner._text) + 1):
        banner.update(per_letter)


# The line box is what is centred. The ink inside it can sit a few pixels to
# one side (a trailing "!" is narrower than its advance), well under a letter.
_INK_SLACK_PX = 6


def _lit_bounds(surface):
    lit = pygame.surfarray.array3d(surface).any(axis=2)
    xs, ys = np.where(lit)
    return pygame.Rect(xs.min(), ys.min(), xs.max() - xs.min() + 1,
                       ys.max() - ys.min() + 1)


# ── Typing ───────────────────────────────────────────────────────────────

def test_nothing_is_drawn_before_the_first_letter(surface):
    banner = OutcomeBanner(surface)
    banner.show_banner("STRIKEOUT")
    banner.draw()
    assert not pygame.surfarray.array3d(surface).any()


@pytest.mark.parametrize('typing_speed', [0.1, 0.05])
def test_one_letter_appears_per_typing_interval(surface, typing_speed):
    banner = OutcomeBanner(surface)
    banner.show_banner("STRIKEOUT", typing_speed=typing_speed)
    frame = typing_speed / 6           # six frames to a letter
    for _ in range(6 * 4 + 1):
        banner.update(frame)
    assert banner._letters == 4


def test_a_stall_types_one_letter_not_the_rest_of_the_word(surface):
    """A modal that paused the game hands back one long frame. The widget
    typed a single letter on it, and so does this."""
    banner = OutcomeBanner(surface)
    banner.show_banner("STRIKEOUT")
    banner.update(30.0)
    assert banner._letters == 1


def test_typing_stops_at_the_end_of_the_text(surface):
    banner = OutcomeBanner(surface)
    banner.show_banner("WALK")
    for _ in range(50):
        banner.update(0.1)
    assert banner._letters == len("WALK")


def test_letters_appear_where_they_will_end_up(surface):
    """The line is laid out for the whole string, so the left edge is fixed
    from the first letter and nothing slides as the rest types."""
    banner = OutcomeBanner(surface)
    banner.show_banner("HOME RUN")
    banner.update(0.1)
    banner.draw()
    first = _lit_bounds(surface)

    surface.fill("black")
    _type_all(banner)
    banner.draw()
    assert _lit_bounds(surface).left == first.left


# ── Placement ────────────────────────────────────────────────────────────

@pytest.mark.parametrize('text', ["STRIKEOUT", "WALK", "HOME RUN", "FOUL BALL",
                                  "WALK-OFF WIN!", "SINGLE · TO 2B ON THROW"])
def test_the_banner_is_centred_inside_its_strip(surface, text):
    banner = OutcomeBanner(surface)
    banner.show_banner(text)
    _type_all(banner)
    banner.draw()
    bounds = _lit_bounds(surface)
    assert OutcomeBanner.RECT.contains(bounds)
    assert abs(bounds.centerx - OutcomeBanner.RECT.centerx) <= _INK_SLACK_PX


def test_the_longest_call_is_shown_whole(surface):
    """The widget clipped at the strip's right edge, which cut the end off
    exactly the calls with the most to say. A long line runs past the strip
    instead, still centred and still on the screen."""
    text = "DOUBLE · TO HOME ON THROW · OUT ADVANCING"
    banner = OutcomeBanner(surface)
    banner.show_banner(text)
    _type_all(banner)
    banner.draw()
    bounds = _lit_bounds(surface)
    assert bounds.width > OutcomeBanner.RECT.width, "this case must overflow"
    assert surface.get_rect().contains(bounds)
    assert bounds.left > 0 and bounds.right < surface.get_width()
    assert abs(bounds.centerx - surface.get_rect().centerx) <= _INK_SLACK_PX


def test_a_line_wider_than_the_screen_is_shrunk_to_fit(surface):
    banner = OutcomeBanner(surface)
    banner.show_banner("X" * 80)
    _type_all(banner)
    banner.draw()
    bounds = _lit_bounds(surface)
    assert bounds.left > 0 and bounds.right < surface.get_width()


# ── Hiding and scheduling ────────────────────────────────────────────────

def test_a_hidden_banner_draws_nothing(surface):
    banner = OutcomeBanner(surface)
    banner.show_banner("WALK")
    _type_all(banner)
    banner.hide_banner()
    banner.draw()
    assert not pygame.surfarray.array3d(surface).any()


def test_a_scheduled_banner_waits_for_its_time(surface, monkeypatch):
    now = [1000]
    monkeypatch.setattr(pygame.time, 'get_ticks', lambda: now[0])
    banner = OutcomeBanner(surface)
    banner.schedule_banner("STRIKEOUT", delay=450)

    now[0] = 1449
    banner.update(0.016)
    assert not banner._visible and banner._pending_banner is not None

    now[0] = 1450
    banner.update(0.016)
    assert banner._visible and banner._text == "STRIKEOUT"
    assert banner._pending_banner is None


def test_a_modal_can_push_a_scheduled_banner_back(surface, monkeypatch):
    """`review_modal.run_modal` adds the time it paused to `show_time`."""
    now = [1000]
    monkeypatch.setattr(pygame.time, 'get_ticks', lambda: now[0])
    banner = OutcomeBanner(surface)
    banner.schedule_banner("WALK", delay=450)
    banner._pending_banner['show_time'] += 5000

    now[0] = 2000
    banner.update(0.016)
    assert not banner._visible
    now[0] = 6450
    banner.update(0.016)
    assert banner._visible


def test_clearing_the_pending_banner_cancels_it(surface, monkeypatch):
    """What an ABS overturn does to the call it reverses."""
    now = [1000]
    monkeypatch.setattr(pygame.time, 'get_ticks', lambda: now[0])
    banner = OutcomeBanner(surface)
    banner.schedule_banner("STRIKEOUT", delay=450)
    banner._pending_banner = None
    now[0] = 9000
    banner.update(0.016)
    assert not banner._visible


def test_hiding_does_not_cancel_a_scheduled_banner(surface, monkeypatch):
    """`PitchSimulation.run` hides the old banner as the pitch starts, and
    the call scheduled during that pitch must still arrive."""
    now = [1000]
    monkeypatch.setattr(pygame.time, 'get_ticks', lambda: now[0])
    banner = OutcomeBanner(surface)
    banner.schedule_banner("WALK", delay=450)
    banner.hide_banner()
    now[0] = 1500
    banner.update(0.016)
    assert banner._visible
