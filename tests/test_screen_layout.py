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


class _Pitcher:
    def __init__(self, pitches):
        self._pitches = list(pitches)

    def get_pitch_names(self):
        return list(self._pitches)


_ROSTER = ('sale', 'degrom', 'yamamoto', 'sasaki', 'mcclanahan')


def _sandbox(pitches=('FF', 'SL', 'CH', 'SI'), ui_visible=True):
    """A Sandbox state on a stub game whose five pitchers share an arsenal."""
    game = _game()
    pitchers = {name: _Pitcher(pitches) for name in _ROSTER}

    def set_current_pitcher(name):
        game.current_pitcher = pitchers[name]

    game.pitcher_manager = SimpleNamespace(
        pitchers=pitchers, set_current_pitcher=set_current_pitcher)
    game.current_pitcher = pitchers['sale']
    game.key_binding_manager = SimpleNamespace(is_ui_visible=lambda: ui_visible)
    game.ui_manager.set_button_visibility = lambda name: None
    state = gs.SandboxGameplayState(game)
    state.active_pitches = set(pitches)
    return state


def _inning_end(revealed=True):
    game = _game()
    game.continued = 0

    def continue_to_summary():
        game.continued += 1

    game.continue_to_summary = continue_to_summary
    state = gs.InningEndState(game)
    state._continue_revealed = revealed
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
    'inning_end': lambda: _inning_end().buttons(),
    'sandbox_gameplay': lambda: _sandbox().buttons(),
    'sandbox_gameplay_seven_pitches':
        lambda: _sandbox(('FF', 'SI', 'FC', 'SL', 'CU', 'CH', 'FS')).buttons(),
}

# Screens whose buttons sit over the field rather than on a menu page. They
# are laid out against the play, not the page margins, and leaving is a key.
_IN_GAME = {'inning_end', 'sandbox_gameplay', 'sandbox_gameplay_seven_pitches'}


@pytest.mark.parametrize('screen', SCREENS)
def test_no_two_buttons_overlap(screen):
    buttons = SCREENS[screen]()
    clashes = [(a.action, b.action) for i, a in enumerate(buttons)
               for b in buttons[i + 1:] if a.rect.colliderect(b.rect)]
    assert not clashes, f"overlapping buttons on '{screen}': {clashes}"


@pytest.mark.parametrize('screen', SCREENS)
def test_every_button_is_on_screen(screen):
    for button in SCREENS[screen]():
        assert SCREEN_RECT.contains(button.rect), button


@pytest.mark.parametrize('screen', sorted(set(SCREENS) - _IN_GAME))
def test_menu_buttons_stay_inside_the_page_margins(screen):
    for button in SCREENS[screen]():
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


@pytest.mark.parametrize('screen', sorted(set(SCREENS) - _IN_GAME))
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


# ── During play ──────────────────────────────────────────────────────────

def _click(pos):
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos)


@pytest.mark.parametrize('state_cls', [gs.GameplayState, gs.VisualizationState])
def test_gameplay_shows_no_buttons(state_cls):
    """An in-game action is a key binding, not a widget. If one of these
    grows buttons, gameplay has a second way to do something a key does."""
    assert not hasattr(state_cls, 'buttons')
    assert state_cls.render_overlay is gs.GameState.render_overlay


def test_inning_end_keeps_only_continue():
    assert [b.action for b in _inning_end().buttons()] == ['continue_to_summary']


def test_continue_is_withheld_during_the_walk_off_celebration():
    """A stray click must not skip the banner reveal."""
    state = _inning_end(revealed=False)
    assert state.buttons() == []
    state.handle_event(_click(pygame.Rect(gs.InningEndState._CONTINUE_RECT).center))
    assert state.game.continued == 0


@pytest.mark.parametrize('event', [
    _click(pygame.Rect(gs.InningEndState._CONTINUE_RECT).center),
    _key(pygame.K_RETURN),
])
def test_a_click_or_enter_continues(event):
    state = _inning_end()
    state.handle_event(event)
    assert state.game.continued == 1


def test_q_does_not_continue_or_pitch_at_inning_end():
    state = _inning_end()
    state.handle_event(_key(pygame.K_q))
    assert state.game.continued == 0


def test_sandbox_keeps_only_its_selectors():
    """The pitcher switch and the pitch toggles are selections, not actions:
    no key does what they do, so they are the one sidebar left."""
    actions = [b.action for b in _sandbox().buttons()]
    assert actions
    assert {kind for kind, _name in actions} == {'pitcher', 'pitch'}


def test_the_sidebar_lists_every_pitcher_and_the_whole_arsenal():
    seven = ('FF', 'SI', 'FC', 'SL', 'CU', 'CH', 'FS')
    actions = [b.action for b in _sandbox(seven).buttons()]
    assert [n for kind, n in actions if kind == 'pitcher'] == list(_ROSTER)
    assert [n for kind, n in actions if kind == 'pitch'] == list(seven), (
        "the old sidebar had six pitch slots and dropped the seventh")


def test_the_sidebar_shows_the_sandbox_state_as_selection():
    state = _sandbox()
    state.active_pitches = {'FF', 'CH'}
    selected = {b.action for b in state.buttons() if b.selected}
    assert selected == {('pitcher', 'sale'), ('pitch', 'FF'), ('pitch', 'CH')}


def test_selected_neighbours_do_not_merge_into_one_block():
    """Selected is a filled block. Slots that touched would read as one."""
    rects = [b.rect for b in _sandbox().buttons()]
    grown = [r.inflate(2, 2) for r in rects]
    assert not any(a.colliderect(b) for i, a in enumerate(grown)
                   for b in grown[i + 1:])


def test_clicking_the_sidebar_switches_pitcher_and_toggles_pitches():
    state = _sandbox()
    rects = {b.action: b.rect for b in state.buttons()}

    state.handle_event(_click(rects[('pitch', 'SL')].center))
    assert state.active_pitches == {'FF', 'CH', 'SI'}
    state.handle_event(_click(rects[('pitch', 'SL')].center))
    assert state.active_pitches == {'FF', 'SL', 'CH', 'SI'}

    state.handle_event(_click(rects[('pitcher', 'degrom')].center))
    assert state.game.current_pitcher is state.game.pitcher_manager.pitchers['degrom']


def test_the_last_active_pitch_cannot_be_switched_off():
    state = _sandbox(('FF', 'SL'))
    rects = {b.action: b.rect for b in state.buttons()}
    state.handle_event(_click(rects[('pitch', 'FF')].center))
    state.handle_event(_click(rects[('pitch', 'SL')].center))
    assert state.active_pitches == {'SL'}


def test_a_hidden_sidebar_is_not_drawn_and_takes_no_clicks():
    """H hides the sidebar with the HUD. What cannot be seen must not be
    clickable, or a swing-side click changes the pitcher."""
    state = _sandbox(ui_visible=False)
    rects = {b.action: b.rect for b in state.buttons()}
    state.handle_event(_click(rects[('pitcher', 'degrom')].center))
    assert state.game.current_pitcher is state.game.pitcher_manager.pitchers['sale']

    surface = pygame.Surface((gdt.SCREEN_W, gdt.SCREEN_H))
    state.render_overlay(surface)
    assert not pygame.surfarray.array3d(surface).any()

    _sandbox(ui_visible=True).render_overlay(surface)
    assert pygame.surfarray.array3d(surface).any(), "the control case draws"


def test_the_sidebar_and_continue_are_drawn_above_the_hud():
    """They go in `render_overlay`, which the frame draws after the HUD."""
    assert gs.SandboxGameplayState.render_overlay is not gs.GameState.render_overlay
    assert gs.InningEndState.render_overlay is not gs.GameState.render_overlay
