"""The button kit: `ui/widgets.py` over `gameday_theme.draw_button`.

These pin the input rules every screen shares, so a screen's own tests only
have to say which buttons it has and what they do.
"""

import pygame
import pytest

from strikefactor.ui import gameday_theme as gdt
from strikefactor.ui import pointer
from strikefactor.ui.widgets import Button, ButtonGroup


def _group(**kwargs):
    group = ButtonGroup(**kwargs)
    group.set([
        Button('back', "<  BACK", pygame.Rect(40, 646, 150, 36)),
        Button('prev', "<  PREV", pygame.Rect(900, 646, 150, 36), enabled=False),
        Button('next', "NEXT  >", pygame.Rect(1090, 646, 150, 36)),
    ])
    return group


def _click(pos, button=1, kind=pygame.MOUSEBUTTONDOWN):
    return pygame.event.Event(kind, pos=pos, button=button)


def _key(key, mod=0):
    return pygame.event.Event(pygame.KEYDOWN, key=key, mod=mod)


# ── The mouse ────────────────────────────────────────────────────────────

def test_a_press_inside_a_button_fires_its_action():
    assert _group().handle_event(_click((50, 650))) == 'back'


def test_a_press_outside_every_button_fires_nothing():
    assert _group().handle_event(_click((640, 360))) is None


@pytest.mark.parametrize('event', [
    _click((50, 650), kind=pygame.MOUSEBUTTONUP),   # the release
    _click((50, 650), button=3),                    # right button
    _click((50, 650), button=4),                    # wheel
])
def test_only_the_left_press_fires(event):
    """Rows, chips and Review controls fire on the press; so do buttons.
    Firing on both press and release would run every action twice."""
    assert _group().handle_event(event) is None


def test_a_disabled_button_cannot_fire():
    group = _group()
    assert group.handle_event(_click((910, 650))) is None
    assert group.hit_test((910, 650)) is None


# ── The keyboard cursor ──────────────────────────────────────────────────

def test_tab_walks_the_enabled_buttons_and_wraps():
    group = _group()
    seen = []
    for _ in range(4):
        group.handle_event(_key(pygame.K_TAB))
        seen.append(group.focused_action())
    assert seen == ['back', 'next', 'back', 'next'], "PREV is disabled"


def test_shift_tab_walks_backwards():
    group = _group()
    group.handle_event(_key(pygame.K_TAB, pygame.KMOD_SHIFT))
    assert group.focused_action() == 'next'


def test_enter_fires_the_focused_button():
    group = _group()
    group.handle_event(_key(pygame.K_TAB))
    group.handle_event(_key(pygame.K_TAB))
    assert group.handle_event(_key(pygame.K_RETURN)) == 'next'


def test_enter_with_no_cursor_fires_the_default_action():
    group = _group(default='next')
    assert group.handle_event(_key(pygame.K_RETURN)) == 'next'
    assert _group().handle_event(_key(pygame.K_RETURN)) is None


def test_enter_does_not_fire_a_default_that_is_disabled_or_absent():
    assert _group(default='prev').handle_event(_key(pygame.K_KP_ENTER)) is None
    assert _group(default='gone').handle_event(_key(pygame.K_RETURN)) is None


def test_arrows_move_the_cursor_only_where_the_screen_gives_them_up():
    """A carousel or a paged list already uses the arrows."""
    plain = _group()
    plain.handle_event(_key(pygame.K_DOWN))
    assert plain.focused_action() is None

    arrows = _group(arrows=True)
    arrows.handle_event(_key(pygame.K_DOWN))
    assert arrows.focused_action() == 'back'
    arrows.handle_event(_key(pygame.K_RIGHT))
    assert arrows.focused_action() == 'next'
    arrows.handle_event(_key(pygame.K_UP))
    assert arrows.focused_action() == 'back'


def test_moving_the_mouse_hands_the_highlight_back_to_hover():
    group = _group()
    group.handle_event(_key(pygame.K_TAB))
    group.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=(5, 5),
                                          rel=(1, 1), buttons=(0, 0, 0)))
    assert group.focused_action() is None


def test_the_cursor_follows_its_action_when_the_buttons_change():
    """A screen restates its buttons when its phase or page changes; the
    cursor should stay on NEXT, not on whatever now sits at that index."""
    group = _group()
    group.handle_event(_key(pygame.K_TAB))
    group.handle_event(_key(pygame.K_TAB))
    group.set([Button('next', "NEXT  >", pygame.Rect(1090, 646, 150, 36)),
               Button('back', "<  BACK", pygame.Rect(40, 646, 150, 36))])
    assert group.focused_action() == 'next'
    group.set([Button('back', "<  BACK", pygame.Rect(40, 646, 150, 36))])
    assert group.focused_action() is None


# ── Drawing ──────────────────────────────────────────────────────────────

def _drawn(group, monkeypatch, at):
    """The `active` flag each button was drawn with, pointer at ``at``."""
    monkeypatch.setattr(pointer, 'pos', lambda: at)
    seen = {}

    def spy(screen, fonts, label, rect, **kwargs):
        seen[label] = kwargs['active']
    monkeypatch.setattr(gdt, 'draw_button', spy)
    group.draw(pygame.Surface((1280, 720)), fonts={})
    return seen


def test_hover_reads_the_pointer_in_the_internal_frame(monkeypatch):
    """`pygame.mouse.get_pos()` is in window pixels, which stop matching the
    layout the moment the window is resized. `ui.pointer` is the one answer."""
    monkeypatch.setattr(pygame.mouse, 'get_pos', lambda: (1100, 650))
    seen = _drawn(_group(), monkeypatch, at=(50, 650))
    assert seen == {"<  BACK": True, "<  PREV": False, "NEXT  >": False}


def test_the_keyboard_cursor_wins_over_hover(monkeypatch):
    group = _group()
    group.handle_event(_key(pygame.K_TAB))          # cursor on BACK
    seen = _drawn(group, monkeypatch, at=(1100, 650))   # pointer on NEXT
    assert seen == {"<  BACK": True, "<  PREV": False, "NEXT  >": False}


@pytest.mark.parametrize('kwargs', [
    {}, {'active': True}, {'selected': True}, {'enabled': False},
    {'style': 'primary'}, {'style': 'primary', 'active': True},
    {'style': 'row', 'detail': "ONE INNING"}, {'style': 'row'},
    {'style': 'row', 'detail': "ONE INNING", 'active': True},
])
def test_a_button_is_drawn_inside_its_own_rect(kwargs):
    surface = pygame.Surface((400, 200))
    rect = (pygame.Rect(20, 40, 360, 84) if kwargs.get('style') == 'row'
            else pygame.Rect(100, 60, 150, 36))
    gdt.draw_button(surface, gdt.load_fonts(), "NEXT  >", rect, **kwargs)
    lit = pygame.mask.from_threshold(surface, (0, 0, 0), (1, 1, 1, 255))
    lit.invert()
    bounds = lit.get_bounding_rects()
    assert bounds, "nothing was drawn"
    assert all(rect.contains(b) for b in bounds)


def test_the_selected_look_is_the_inverted_block():
    surface = pygame.Surface((400, 200))
    rect = pygame.Rect(100, 60, 150, 36)
    gdt.draw_button(surface, gdt.load_fonts(), "FF", rect, selected=True)
    assert surface.get_at((rect.left + 2, rect.top + 2))[:3] == gdt.HIGHLIGHT_BG


def test_footer_rows_are_derived_from_the_screen_width():
    """The helper is the reason a footer cannot drift."""
    rects = gdt.footer_row_right([100, 100], gap=10)
    assert rects[0].left == gdt.SCREEN_W - gdt.MARGIN_X - 210
    assert rects[-1].right == gdt.SCREEN_W - gdt.MARGIN_X
    assert gdt.footer_back_rect().left == gdt.MARGIN_X
    assert {r.top for r in rects} == {gdt.footer_back_rect().top} == {gdt.FOOTER_Y}
