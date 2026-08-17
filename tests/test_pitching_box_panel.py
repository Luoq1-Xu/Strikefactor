"""Guards the GameDay pitching box score.

This panel exists because the GAME LOG overlay used to draw pitching lines as a
fixed 76px strip under the play-by-play — two lines per side, `stats[-2:]` — so
in any game that went to the bullpen the earlier arms had no screen anywhere
that could show them. The load-bearing property is therefore *completeness*:
every arm that appeared gets a row with its whole line, no matter how many arms
there were or how little room the panel is given.
"""

import pygame
import pytest

from strikefactor.gameplay.game_states import GameDayTransitionState
from strikefactor.gameplay.gameday_manager import GameDayManager, PitcherStats
from strikefactor.ui import gameday_theme as gdt
from strikefactor.ui.pitching_box_panel import (
    COLUMNS,
    PitchingBoxPanel,
    PitchingSide,
    format_era,
    format_ip,
)

PANEL_RECT = pygame.Rect(100, 80, 1080, 510)   # the real GAME LOG panel rect


@pytest.fixture(scope="module")
def fonts():
    return gdt.load_fonts()


def _arm(name, outs=3, hits=1, runs=1, walks=1, k=2, hr=0, pitches=18,
         active=False):
    ps = PitcherStats(name)
    ps.outs_recorded = outs
    ps.hits_allowed = hits
    ps.runs_allowed = runs
    ps.walks = walks
    ps.strikeouts = k
    ps.home_runs_allowed = hr
    ps.pitch_count = pitches
    ps.is_active = active
    return ps


def _staff(names, **kwargs):
    return [_arm(name, **kwargs) for name in names]


def _panel(fonts, sides, live=True):
    panel = PitchingBoxPanel(fonts)
    panel.set_sides(sides, live=live)
    return panel


def _rows_of(panel, kind):
    return [row for row in panel._rows if row['kind'] == kind]


def _names(panel):
    return [row['line']['name'] for row in _rows_of(panel, 'pitcher')]


def _drawn_bounds(screen):
    """Bounding rect of every non-black pixel — i.e. everything the panel put on
    a black surface. Probing a handful of points isn't enough: the numeric
    columns are anchored to the right edge, so a too-narrow rect pushes the
    leftmost of them out sideways at one specific row height."""
    import numpy as np

    lit = pygame.surfarray.array3d(screen).sum(axis=2)
    xs, ys = np.nonzero(lit)
    assert xs.size, "the panel drew nothing at all"
    return pygame.Rect(xs.min(), ys.min(),
                       xs.max() - xs.min() + 1, ys.max() - ys.min() + 1)


# --- Completeness: the whole point of the panel ---------------------------

def test_every_arm_on_both_sides_gets_a_row(fonts):
    """A six-arm bullpen game shows eleven pitchers, not four."""
    mine = _staff(['yesavage', 'hoffman', 'lauer', 'woo', 'vesia', 'chapman'])
    theirs = _staff(['yamamoto', 'sasaki', 'degrom', 'sale', 'mcclanahan'])
    panel = _panel(fonts, [PitchingSide("THEIRS", theirs),
                           PitchingSide("MINE", mine)])

    assert _names(panel) == [ps.name.upper() for ps in theirs + mine]


def test_a_panel_too_short_for_the_staff_scrolls_instead_of_dropping_arms(fonts):
    """Height is a scrolling problem, never a truncation problem."""
    screen = pygame.Surface((1280, 720))
    mine = _staff(['yesavage', 'hoffman', 'lauer', 'woo', 'vesia', 'chapman'])
    theirs = _staff(['yamamoto', 'sasaki', 'degrom', 'sale', 'mcclanahan'])
    panel = _panel(fonts, [PitchingSide("THEIRS", theirs),
                           PitchingSide("MINE", mine)])

    panel.draw(screen, pygame.Rect(100, 80, 1080, 180))  # deliberately cramped

    assert len(_names(panel)) == 11
    assert panel._max_scroll() > 0, "a staff that overflows must be scrollable"

    # END reaches the bottom of the content, so the last arm is readable.
    panel.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_END))
    last = panel._rows[-1]
    assert last['y'] - panel.scroll + panel.TOTALS_H <= panel._viewport_h() + 1


def test_the_active_arm_is_kept_and_unused_arms_are_left_out(fonts):
    """A reliever warming with no line yet is on the mound and must show; a
    rostered arm that never appeared is not part of this game's box score."""
    used = _arm('yamamoto')
    warm = _arm('sasaki', outs=0, hits=0, runs=0, walks=0, k=0, pitches=0,
                active=True)
    never = _arm('degrom', outs=0, hits=0, runs=0, walks=0, k=0, pitches=0)
    panel = _panel(fonts, [PitchingSide("THEIRS", [used, warm, never])])

    assert _names(panel) == ['YAMAMOTO', 'SASAKI']


def test_a_side_that_never_pitched_says_so(fonts):
    panel = _panel(fonts, [PitchingSide("THEIRS", [])])
    assert _rows_of(panel, 'pitcher') == []
    assert len(_rows_of(panel, 'empty')) == 1


# --- The numbers ----------------------------------------------------------

def test_totals_row_sums_the_side(fonts):
    theirs = [_arm('yamamoto', outs=16, hits=5, runs=3, walks=2, k=7, hr=1,
                   pitches=92),
              _arm('sasaki', outs=5, hits=2, runs=1, walks=1, k=3, hr=1,
                   pitches=24)]
    panel = _panel(fonts, [PitchingSide("THEIRS", theirs)])
    totals = _rows_of(panel, 'totals')[0]['totals']

    assert totals['counts'] == {'outs': 21, 'h': 7, 'r': 4, 'bb': 3, 'k': 10,
                               'hr': 2, 'pc': 116}
    assert totals['values']['ip'] == '7.0'
    assert totals['values']['era'] == format_era(4, 21)


def test_ip_formatting_matches_pitcher_stats():
    """The panel formats a *summed* out count for its totals row, which no
    PitcherStats instance owns — so it has its own formatter. Pin the two
    together rather than letting them drift."""
    for outs in range(0, 40):
        stats = PitcherStats('x')
        stats.outs_recorded = outs
        assert format_ip(outs) == stats.get_ip_display()


def test_era_never_divides_by_zero_or_invents_a_clean_line():
    assert format_era(0, 0) == '-'      # no outs, no damage: no rate exists
    assert format_era(2, 0) == 'INF'    # came in, gave up two, got nobody out
    assert format_era(1, 9) == '3.00'
    assert format_era(4, 21) == '5.14'


def test_every_column_is_populated_for_pitchers_and_totals(fonts):
    panel = _panel(fonts, [PitchingSide("THEIRS", _staff(['yamamoto']))])
    keys = [key for _, key in COLUMNS]
    line = _rows_of(panel, 'pitcher')[0]['line']
    totals = _rows_of(panel, 'totals')[0]['totals']
    for key in keys:
        assert line['values'][key] != ''
        assert totals['values'][key] != ''


# --- Drawing --------------------------------------------------------------

@pytest.mark.parametrize("rect", [
    PANEL_RECT,
    pygame.Rect(300, 200, 200, 120),   # far narrower than the box score wants
])
def test_draw_stays_inside_its_rect_and_restores_the_clip(fonts, rect):
    """Column x-positions are derived from the rect, so a panel that is too
    narrow for the table has to clamp rather than spill numbers over whatever is
    beside it — and the clip must come back however it exits."""
    screen = pygame.Surface((1280, 720))
    screen.fill((0, 0, 0))
    before = screen.get_clip()
    panel = _panel(fonts, [PitchingSide("THEIRS", _staff(['yamamoto', 'sasaki'])),
                           PitchingSide("MINE", _staff(['yesavage', 'chapman']))])

    panel.draw(screen, rect)

    assert screen.get_clip() == before
    assert rect.contains(_drawn_bounds(screen))


def test_live_false_drops_the_on_the_mound_marker(fonts):
    """A finished game has nobody on the mound; the last arm used shouldn't be
    drawn as though they were still working."""
    screen = pygame.Surface((1280, 720))
    theirs = [_arm('yamamoto', active=True)]
    for live in (True, False):
        panel = _panel(fonts, [PitchingSide("THEIRS", theirs)], live=live)
        assert panel._live is live
        panel.draw(screen, PANEL_RECT)   # both paths must render


# --- The overlay that hosts it -------------------------------------------

class _StubUIManager:
    """Just enough of UIManager for the overlay's modal handoff."""

    def __init__(self):
        self.visibility_state = None

    def set_visibility_state(self, state):
        self.visibility_state = state

    def process_events(self, event):
        pass


class _StubGame:
    def __init__(self, manager):
        self.gameday_manager = manager
        self.ui_manager = _StubUIManager()


def test_the_two_line_per_side_pitching_strip_is_gone():
    """The strip is what hid the arms. If it comes back, so does the bug."""
    assert not hasattr(GameDayTransitionState, '_LOG_PITCHERS_H')
    assert not hasattr(GameDayTransitionState, '_render_log_pitchers')
    assert 'PITCHING' in GameDayTransitionState._LOG_TABS


def test_log_tabs_cycle_and_select_the_right_panel():
    state = GameDayTransitionState(_StubGame(None))
    state._pbp = object()
    state._pitching_box = object()

    assert state._active_log_panel() is state._pbp
    state._set_log_tab(1)
    assert state._active_log_panel() is state._pitching_box
    state._set_log_tab(state._log_tab + 1)          # wraps forward
    assert state._active_log_panel() is state._pbp
    state._set_log_tab(state._log_tab - 1)          # and backward
    assert state._active_log_panel() is state._pitching_box


def test_pitching_sides_covers_both_staffs_with_the_right_tags():
    """Opponent arms are tagged by handedness (the player bats against them);
    the player's own staff by bullpen role (they only ever manage it)."""
    manager = GameDayManager(difficulty='amateur', starter_name='sale')
    manager.substitute_relief_pitcher()             # a second opponent arm
    state = GameDayTransitionState(_StubGame(manager))

    opponent, mine = state._pitching_sides()

    assert [ps.name for ps in opponent.stats] == list(manager.opponent_pitcher_stats)
    assert [ps.name for ps in mine.stats] == list(manager.player_pitcher_stats)
    assert opponent.tags['sale'] == 'L'
    assert all(tag in ('L', 'R') for tag in opponent.tags.values())
    assert all(tag for tag in mine.tags.values()), "player arms need a role tag"


def _bullpen_game():
    """A manager whose opponent went through its whole staff, each arm having
    actually thrown — i.e. the game the old two-line strip could not show."""
    manager = GameDayManager(difficulty='amateur', starter_name='sale')
    for _ in range(3):
        manager.substitute_relief_pitcher()
    for i, stats in enumerate(manager.opponent_pitcher_stats.values()):
        stats.pitch_count = 60 - 10 * i
        stats.outs_recorded = 9 - 2 * i
    return manager


def test_the_overlay_shows_every_arm_on_the_pitching_tab(fonts):
    """End-to-end through the real open + render path, no Game instance."""
    screen = pygame.Surface((1280, 720))
    manager = _bullpen_game()
    state = GameDayTransitionState(_StubGame(manager))
    state._gd_fonts = fonts

    state._show_game_log()
    assert state._log_open
    # Opening the log is modal — the phase buttons have to go away.
    assert state.game.ui_manager.visibility_state == 'pitching'

    state._set_log_tab(1)
    state._render_game_log_overlay(screen)

    names = _names(state._pitching_box)
    assert 'SALE' in names
    assert len(names) == len(manager.opponent_pitcher_stats) + 1, (
        f"expected all four opponent arms plus the player's starter, got {names}")
    # The tab chips must be hit-testable, or the pitching view is unreachable
    # by mouse.
    assert len(state._log_tab_rects) == len(GameDayTransitionState._LOG_TABS)


def test_clicking_a_tab_chip_switches_view_instead_of_closing_the_log(fonts):
    """The chips are drawn outside _LOG_RECT, so they'd otherwise land in the
    click-outside-to-close branch."""
    screen = pygame.Surface((1280, 720))
    state = GameDayTransitionState(_StubGame(_bullpen_game()))
    state._gd_fonts = fonts
    state._show_game_log()
    state._render_game_log_overlay(screen)   # publishes the chip rects

    chip = dict((index, rect) for rect, index in state._log_tab_rects)[1]
    state.handle_event(pygame.event.Event(
        pygame.MOUSEBUTTONDOWN, button=1, pos=chip.center))

    assert state._log_tab == 1
    assert state._log_open, "clicking a tab must not dismiss the overlay"
