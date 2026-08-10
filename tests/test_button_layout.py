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
    'view_pitches',
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
    'sandbox_view_pitches',
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


def test_sandbox_layout_moves_pitchviz_off_the_pitcher_column(ui):
    """PITCHVIZ must leave its Arcade slot when the Sandbox column is up."""
    ui.set_button_visibility('in_game', force_show=True)
    arcade_pos = ui.buttons['view_pitches'].rect.topleft

    ui.set_button_visibility('sandbox_gameplay', force_show=True)
    assert ui.buttons['view_pitches'].rect.topleft != arcade_pos

    # And it must go back when Arcade comes round again.
    ui.set_button_visibility('in_game', force_show=True)
    assert ui.buttons['view_pitches'].rect.topleft == arcade_pos
