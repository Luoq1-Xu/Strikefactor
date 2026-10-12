"""Guards that no two simultaneously-visible buttons overlap.

Overlapping rects are not just cosmetic: pygame_gui hit-tests by layer, so the
button that happens to be created first swallows every click in the shared
area. That is how PITCHVIZ (an Arcade sidebar slot) ate the SASAKI pitcher
switch in Sandbox — the two rects were 2px apart with identical widths.
"""

import pygame
import pytest

from strikefactor.ui.ui_manager import UIManager

# Every state string accepted by UIManager.set_button_visibility that shows
# buttons. Menus and gameplay both go through the same column layout code.
VISIBILITY_STATES = [
    'in_game',
    'pitching',
    'main_menu',
    'visualise',
    'summary',
    'inning_end',
    'settings',
    'key_bindings',
    'mode_select',
    'gameday_start',
    'gameday_transition',
    'gameday_simulation',
    'gameday_final',
    'gameday_resume',
    'gameday_history',
    'gameday_history_detail',
    'sandbox_menu',
    'sandbox_gameplay',
]


@pytest.fixture(scope="module")
def ui():
    screen = pygame.display.get_surface()
    manager = UIManager(screen, screen.get_size())
    yield manager


def _visible_rects(ui):
    return {name: btn.rect.copy() for name, btn in ui.buttons.items() if btn.visible}


def _overlaps(rects):
    names = sorted(rects)
    return [
        (a, tuple(rects[a]), b, tuple(rects[b]))
        for i, a in enumerate(names)
        for b in names[i + 1:]
        if rects[a].colliderect(rects[b])
    ]


@pytest.mark.parametrize("state", VISIBILITY_STATES)
def test_no_visible_buttons_overlap(ui, state):
    ui.set_button_visibility(state, force_show=True)
    clashes = _overlaps(_visible_rects(ui))
    assert not clashes, f"overlapping buttons in '{state}': {clashes}"


def test_sandbox_pitch_buttons_do_not_overlap_sidebar(ui):
    """The pitch toggles are shown separately from set_button_visibility."""
    ui.set_button_visibility('sandbox_gameplay', force_show=True)
    ui.update_sandbox_pitch_buttons(
        ['FASTBALL', 'SLIDER', 'CHANGEUP', 'CURVE', 'SPLITTER', 'CUTTER'])
    clashes = _overlaps(_visible_rects(ui))
    assert not clashes, f"overlapping buttons in sandbox gameplay: {clashes}"


# ── Gameplay has no buttons ──────────────────────────────────────────────

# The in-game sidebar. Each of these duplicated a key binding (Z, B, V, M,
# ESC), or opened a feature that went with it (the scouting report and the lap
# log). If one comes back, gameplay has grown a second way to do something a
# key already does.
_RETIRED_BUTTONS = [
    'strikezone', 'toggle_batter', 'view_pitches', 'toggle_ump_sound',
    'main_menu', 'scout', 'lap_stats', 'view_laps',
    'sandbox_sound', 'sandbox_exit',
]


@pytest.mark.parametrize('name', _RETIRED_BUTTONS)
def test_the_in_game_sidebar_buttons_are_gone(ui, name):
    assert name not in ui.buttons


@pytest.mark.parametrize('state', ['in_game', 'pitching', 'visualise'])
def test_gameplay_shows_no_buttons(ui, state):
    ui.set_button_visibility(state, force_show=True)
    assert not _visible_rects(ui)


def test_the_scouting_and_lap_panels_are_gone(ui):
    for gone in ('scouting_panel', 'lap_log_panel', 'toggle_scouting_panel',
                 'toggle_lap_log_panel'):
        assert not hasattr(ui, gone)


def test_inning_end_keeps_only_continue(ui):
    ui.set_button_visibility('inning_end', force_show=True)
    assert set(_visible_rects(ui)) == {'continue_to_summary'}


def test_sandbox_keeps_only_its_selectors(ui):
    """The pitcher switch and the pitch toggles are selections, not actions:
    no key does what they do, so they are the one sidebar left."""
    ui.set_button_visibility('sandbox_gameplay', force_show=True)
    ui.update_sandbox_pitch_buttons(['FF', 'SL', 'CH'])
    visible = set(_visible_rects(ui))
    assert visible
    assert all(name.startswith(('sandbox_pitcher_', 'sandbox_pitch_'))
               for name in visible)
