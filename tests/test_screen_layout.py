"""Every screen's buttons, read from the screen itself.

A state lists the buttons it has right now (`buttons()`), so layout can be
checked for every phase and sub-mode without rendering a frame or building a
`Game`. Two buttons that overlap are not just untidy: the first one listed
takes the click, which is how PITCHVIZ (an Arcade sidebar slot) once ate the
SASAKI pitcher switch in Sandbox.
"""

from types import SimpleNamespace

import pygame
import pytest

from strikefactor.gameplay import game_states as gs
from strikefactor.ui import gameday_theme as gdt
from strikefactor.ui.pitcher_select import CARD_RECT, PitcherSelect
from strikefactor.ui.settings_panel import KeyBindingsPanel, SettingsPanel

SCREEN_RECT = pygame.Rect(0, 0, gdt.SCREEN_W, gdt.SCREEN_H)


def _game():
    return SimpleNamespace(
        pitcher_manager=None,
        ui_manager=SimpleNamespace(set_visibility_state=lambda name: None,
                                   process_events=lambda event: None,
                                   hide_banner=lambda: None))


def _gameday_setup(resume):
    state = gs.GameDayState(_game())
    state._has_resume = resume
    return state


def _transition(phase):
    state = gs.GameDayTransitionState(_game())
    state.phase = phase
    return state


def _list(cls, pages=3, page=1, selected=None):
    state = cls(_game())
    state.items = [object()] * (cls.PAGE_SIZE * pages)
    state.page = page
    state.selected = selected
    return state


# Every screen and phase that shows buttons: label -> the buttons it shows.
SCREENS = {
    'settings': lambda: SettingsPanel().footer_buttons(),
    'key_bindings': lambda: KeyBindingsPanel().footer_buttons(),
    'gameday_setup': lambda: _gameday_setup(False).buttons(),
    'gameday_setup_with_resume': lambda: _gameday_setup(True).buttons(),
    'gameday_between_innings': lambda: _transition("SHOW_SCORE").buttons(),
    'gameday_opponent_half': lambda: _transition("SIMULATING").buttons(),
    'gameday_final': lambda: _transition("FINAL").buttons(),
    'gameday_resume_list': lambda: _list(gs.GameDayResumeState).buttons(),
    'gameday_history_list': lambda: _list(gs.GameDayHistoryState).buttons(),
    'gameday_history_detail':
        lambda: _list(gs.GameDayHistoryState, selected={'date': ''}).buttons(),
}


@pytest.mark.parametrize('screen', SCREENS)
def test_no_two_buttons_overlap(screen):
    buttons = SCREENS[screen]()
    clashes = [(a.action, b.action) for i, a in enumerate(buttons)
               for b in buttons[i + 1:] if a.rect.colliderect(b.rect)]
    assert not clashes, f"overlapping buttons on '{screen}': {clashes}"


@pytest.mark.parametrize('screen', SCREENS)
def test_every_button_is_on_screen_and_inside_the_margins(screen):
    for button in SCREENS[screen]():
        assert SCREEN_RECT.contains(button.rect), button
        assert button.rect.left >= gdt.MARGIN_X, button
        assert button.rect.right <= gdt.SCREEN_W - gdt.MARGIN_X, button


@pytest.mark.parametrize('screen', SCREENS)
def test_action_ids_are_unique_on_a_screen(screen):
    """The group reports *which action* fired; two buttons sharing an id
    would be indistinguishable to the state."""
    actions = [b.action for b in SCREENS[screen]()]
    assert len(actions) == len(set(actions))


# BACK (or MAIN MENU, where backing out abandons a game) is the same slot on
# every screen that has one.
_BACK_ACTIONS = {'back', 'back_to_main', 'back_from_keybinds', 'gd_list_back',
                 'gameday_main_menu'}


@pytest.mark.parametrize('screen', SCREENS)
def test_the_way_back_is_always_in_the_same_place(screen):
    backs = [b for b in SCREENS[screen]() if b.action in _BACK_ACTIONS]
    for button in backs:
        assert button.rect == gdt.footer_back_rect()
    if screen != 'gameday_final':
        assert len(backs) == 1, f"'{screen}' needs exactly one way back"


# ── Pitcher select ───────────────────────────────────────────────────────

def _select(extras=None):
    return PitcherSelect(None, header="=== TEST ===", subtitle="",
                         extras=extras)


def _key(code):
    return pygame.event.Event(pygame.KEYDOWN, key=code, mod=0)


def test_the_arrows_flank_the_card_and_the_confirm_sits_under_it():
    buttons = {b.action: b.rect for b in _select().buttons()}
    assert buttons['prev'].right < CARD_RECT.left
    assert buttons['next'].left > CARD_RECT.right
    assert buttons['prev'].centery == buttons['next'].centery == CARD_RECT.centery
    assert buttons['confirm'].centerx == CARD_RECT.centerx == gdt.SCREEN_W // 2
    assert buttons['confirm'].top > CARD_RECT.bottom


@pytest.mark.parametrize('count', [1, 2, 3])
def test_extra_buttons_share_the_width_of_the_confirm_button(count):
    extras = [(f'extra{i}', f"EXTRA {i}") for i in range(count)]
    buttons = {b.action: b.rect for b in _select(lambda: extras).buttons()}
    row = [buttons[action] for action, _label in extras]
    assert row[0].left == buttons['confirm'].left
    assert row[-1].right == buttons['confirm'].right
    assert all(r.top > buttons['confirm'].bottom for r in row)
    assert not any(a.colliderect(b) for i, a in enumerate(row)
                   for b in row[i + 1:])


def test_left_and_right_turn_the_carousel_and_report_nothing():
    select = _select()
    start = select.selected()
    assert select.handle_event(_key(pygame.K_RIGHT)) is None
    assert select.selected() != start
    assert select.handle_event(_key(pygame.K_LEFT)) is None
    assert select.selected() == start


def test_the_arrow_buttons_turn_the_carousel_too():
    select = _select()
    start = select.selected()
    rects = {b.action: b.rect for b in select.buttons()}
    click = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                               pos=rects['next'].center)
    assert select.handle_event(click) is None
    assert select.selected() != start


def test_enter_confirms_and_escape_backs_out():
    select = _select()
    assert select.handle_event(_key(pygame.K_RETURN)) == 'confirm'
    assert select.handle_event(_key(pygame.K_ESCAPE)) == 'back'


def test_every_button_reports_its_own_action():
    extras = [('gameday_resume', "RESUME"), ('gameday_past_games', "PAST GAMES")]
    select = _select(lambda: extras)
    for button in select.buttons():
        if button.action in ('prev', 'next'):
            continue
        click = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                   pos=button.rect.center)
        assert select.handle_event(click) == button.action


# ── GameDay ──────────────────────────────────────────────────────────────

def test_resume_is_offered_only_when_a_game_is_waiting():
    without = {b.action for b in _gameday_setup(False).buttons()}
    with_resume = {b.action for b in _gameday_setup(True).buttons()}
    assert 'gameday_resume' not in without
    assert with_resume - without == {'gameday_resume'}
    assert 'gameday_past_games' in without


@pytest.mark.parametrize('phase,primary', [
    ("SHOW_SCORE", 'next_inning'),
    ("SIMULATING", 'start_batting'),
    ("FINAL", 'final_menu'),
])
def test_each_phase_has_one_primary_button_and_the_game_log(phase, primary):
    buttons = _transition(phase).buttons()
    assert [b.action for b in buttons if b.style == 'primary'] == [primary]
    assert 'view_game_log' in {b.action for b in buttons}


def test_a_finished_game_offers_no_way_to_abandon_it():
    assert 'gameday_main_menu' not in {
        b.action for b in _transition("FINAL").buttons()}


def test_every_transition_button_has_a_handler():
    seen = set()
    for phase in gs.GameDayTransitionState._PRIMARY:
        seen |= {b.action for b in _transition(phase).buttons()}
    assert seen == set(gs.GameDayTransitionState._BUTTON_ACTIONS)
    for method in gs.GameDayTransitionState._BUTTON_ACTIONS.values():
        assert callable(getattr(gs.GameDayTransitionState, method, None)), method


def test_enter_fires_the_primary_button_of_the_phase(monkeypatch):
    state = _transition("SIMULATING")
    fired = []
    monkeypatch.setattr(state, '_start_player_batting',
                        lambda: fired.append('start_batting'))
    state.handle_event(_key(pygame.K_RETURN))
    assert fired == ['start_batting']


@pytest.mark.parametrize('page,prev,nxt', [(0, False, True), (1, True, True),
                                           (2, True, False)])
def test_the_pager_is_disabled_at_the_ends(page, prev, nxt):
    buttons = {b.action: b for b in
               _list(gs.GameDayResumeState, pages=3, page=page).buttons()}
    assert buttons['gd_page_prev'].enabled is prev
    assert buttons['gd_page_next'].enabled is nxt


def test_a_single_page_list_cannot_page():
    buttons = {b.action: b for b in
               _list(gs.GameDayResumeState, pages=1, page=0).buttons()}
    assert not buttons['gd_page_prev'].enabled
    assert not buttons['gd_page_next'].enabled


def test_the_pager_buttons_page_and_stop_at_the_ends():
    state = _list(gs.GameDayResumeState, pages=2, page=0)
    rects = {b.action: b.rect for b in state.buttons()}

    def click(action):
        state.handle_event(pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, button=1, pos=rects[action].center))

    click('gd_page_next')
    assert state.page == 1
    click('gd_page_next')
    assert state.page == 1, "there is no third page"
    click('gd_page_prev')
    assert state.page == 0


def test_the_detail_view_has_one_button_and_it_returns_to_the_list():
    state = _list(gs.GameDayHistoryState, selected={'date': ''})
    state._pbp = SimpleNamespace(handle_event=lambda event: False)
    state._panel = lambda: state._pbp
    (back,) = state.buttons()
    state.handle_event(pygame.event.Event(
        pygame.MOUSEBUTTONDOWN, button=1, pos=back.rect.center))
    assert state.selected is None
    assert len(state.buttons()) == 3, "back on the list, with its pager"
