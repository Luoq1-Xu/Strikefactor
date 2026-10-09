"""Guards the settings and key-binding screens.

These two screens were grids of absolutely-positioned buttons whose rows each
centred on a different axis — 620, 640, 740 and 800 against a screen centre of
640, with the toggle row's right edge 10px off the screen. Nothing in the code
made that visible, because every rect was an independent literal.

So the load-bearing property here is that **no element carries its own x**:
rows span a content column derived from the margins, and footer buttons are
derived from SCREEN_WIDTH. The tests below assert containment and alignment
against those derived bounds rather than against remembered numbers, plus the
"the old grid is gone" guard this codebase uses elsewhere.
"""

import numpy
import pygame
import pytest

from strikefactor.config import SCREEN_HEIGHT, SCREEN_WIDTH
from strikefactor.gameplay.game_states import MenuState
from strikefactor.key_binding_manager import KeyAction, KeyBindingManager
from strikefactor.settings_manager import DifficultyLevel, SettingsManager
from strikefactor.ui import gameday_theme as gdt
from strikefactor.ui import settings_panel as sp
from strikefactor.ui.settings_panel import KeyBindingsPanel, SettingsPanel
from strikefactor.ui.ui_manager import UIManager

SCREEN_RECT = pygame.Rect(0, 0, 1280, 720)


@pytest.fixture(scope="module")
def ui():
    screen = pygame.display.get_surface()
    return UIManager(screen, screen.get_size())


@pytest.fixture
def settings(tmp_path, monkeypatch):
    """A SettingsManager writing to a throwaway file, never the user's."""
    monkeypatch.setattr(SettingsManager, "settings_file",
                        str(tmp_path / "settings.json"), raising=False)
    manager = SettingsManager()
    manager.settings_file = str(tmp_path / "settings.json")
    return manager


@pytest.fixture
def bindings(tmp_path, monkeypatch):
    manager = KeyBindingManager(settings_manager=None)
    manager.settings_file = str(tmp_path / "key_bindings.json")
    return manager


@pytest.fixture
def surface():
    return pygame.Surface((1280, 720))


def _rendered_settings(surface, settings):
    panel = SettingsPanel()
    panel.render(surface, settings)
    return panel


def _rendered_keybinds(surface, bindings):
    panel = KeyBindingsPanel()
    panel.render(surface, bindings)
    return panel


# ── The old grid is gone ─────────────────────────────────────────────────

# Every button the off-centre settings/keybind grid used to define. If one
# comes back, a screen has grown a second, hand-placed source of layout truth.
_RETIRED_BUTTONS = [
    'difficulty_rookie', 'difficulty_amateur', 'difficulty_professional',
    'difficulty_allstar', 'difficulty_halloffame',
    'toggle_ump_sound_settings', 'toggle_strikezone_settings',
    'toggle_abs_settings', 'toggle_foul_anim_settings',
    'display_fps_setting', 'engine_fps_setting', 'toggle_hud_mode_settings',
    'bind_toggle_ui', 'bind_toggle_strikezone', 'bind_toggle_sound',
    'bind_toggle_batter', 'bind_quick_pitch', 'bind_view_pitches',
    'bind_main_menu', 'bind_toggle_track', 'bind_challenge',
]


@pytest.mark.parametrize("name", _RETIRED_BUTTONS)
def test_the_hardcoded_settings_grid_is_gone(ui, name):
    assert name not in ui.buttons


def test_ui_manager_no_longer_pushes_settings_button_text(ui):
    """The per-widget text updaters went with the widgets."""
    for gone in ('update_settings_button_states', 'show_settings_info',
                 'update_key_binding_buttons', 'show_key_bindings_info'):
        assert not hasattr(ui, gone)


def test_the_settings_button_theme_class_is_gone():
    """It styled only the retired grid. Left behind it would invite a new
    button back onto the old, greyer visual track."""
    import json

    from strikefactor.config import get_path
    with open(get_path('assets/theme.json')) as f:
        theme = json.load(f)
    assert '@settings_button' not in theme


# ── Footer nav is derived, not literal ───────────────────────────────────

@pytest.mark.parametrize("state,names", [
    ('settings', ['back_to_main', 'key_bindings', 'reset_settings']),
    ('key_bindings', ['back_from_keybinds', 'reset_keybinds']),
])
def test_footer_buttons_are_margin_anchored(ui, state, names):
    ui.set_button_visibility(state, force_show=True)
    visible = {n: b.rect.copy() for n, b in ui.buttons.items() if b.visible}
    assert set(visible) == set(names)

    margin = UIManager.MENU_MARGIN_X
    for rect in visible.values():
        assert rect.left >= margin
        assert rect.right <= SCREEN_WIDTH - margin
        assert SCREEN_RECT.contains(rect)

    # Back sits on the left margin; the action run ends on the right one.
    back = visible[names[0]]
    assert back.left == margin
    assert max(r.right for r in visible.values()) == SCREEN_WIDTH - margin


def test_footer_row_is_recomputed_from_screen_width():
    """The helper is the reason a row cannot drift — check it actually uses
    SCREEN_WIDTH rather than baking a remembered right edge."""
    rects = UIManager._footer_row_right([100, 100], gap=10)
    assert rects[0].left == SCREEN_WIDTH - UIManager.MENU_MARGIN_X - 210
    assert rects[-1].right == SCREEN_WIDTH - UIManager.MENU_MARGIN_X


# ── Panel rows stay in the content column ────────────────────────────────

def test_settings_rows_stay_inside_the_content_column(surface, settings):
    panel = _rendered_settings(surface, settings)
    left, right = sp.content_bounds()
    assert (left, right) == (gdt.MARGIN_X, SCREEN_WIDTH - gdt.MARGIN_X)

    rects = [rect for rect, _key in panel._row_rects]
    assert rects, "settings screen drew no rows"
    for rect in rects:
        assert rect.left == left and rect.right == right
        assert rect.bottom <= sp._FOOTER_DIVIDER_Y
        assert SCREEN_RECT.contains(rect)


def test_settings_rows_do_not_overlap(surface, settings):
    panel = _rendered_settings(surface, settings)
    rects = [rect for rect, _key in panel._row_rects]
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            assert not a.colliderect(b)


def test_difficulty_chips_stay_inside_the_content_column(surface, settings):
    panel = _rendered_settings(surface, settings)
    left, right = sp.content_bounds()
    assert len(panel._chip_rects) == len(SettingsPanel.DIFFICULTIES)
    for rect, _index in panel._chip_rects:
        assert rect.left >= left and rect.right <= right


def test_keybind_rows_stay_inside_the_content_column(surface, bindings):
    panel = _rendered_keybinds(surface, bindings)
    left, right = sp.content_bounds()
    rects = [rect for rect, _key in panel._row_rects]
    assert len(rects) == len(KeyBindingsPanel.ACTIONS)
    for rect in rects:
        assert rect.left == left and rect.right == right
        assert rect.bottom <= sp._FOOTER_DIVIDER_Y


def _lit_bounds(surface):
    """Bounding box of every non-background pixel, as (left, top, right, bot).

    Probing a few corners misses a spill that happens at one row height, and
    pygame silently clips drawing at the surface edge — so an out-of-bounds
    blit shows up here as content *touching* the edge, not as an error.
    """
    lit = numpy.argwhere(pygame.surfarray.array3d(surface).max(axis=2) > 40)
    assert lit.size, "panel drew nothing"
    xs, ys = lit[:, 0], lit[:, 1]
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


@pytest.mark.parametrize("which", ["settings", "keybinds"])
def test_drawn_content_respects_the_page_margins(which, settings, bindings):
    """The whole complaint in one assertion: the old toggle row ran to x=1270
    on a 1280px screen while `Back` sat at x=50, so the page had no margin it
    agreed on. Every pixel now lives inside the one content column."""
    surface = pygame.Surface((1280, 720))
    surface.fill((0, 0, 0))
    if which == "settings":
        SettingsPanel().render(surface, settings)
    else:
        KeyBindingsPanel().render(surface, bindings)

    left, top, right, bottom = _lit_bounds(surface)
    col_left, col_right = sp.content_bounds()
    assert left >= col_left
    assert right <= col_right
    assert top >= 0 and bottom < SCREEN_RECT.height


# ── Values reflect the settings manager ──────────────────────────────────

@pytest.mark.parametrize("key,setting", list(SettingsPanel._BOOL_SETTING.items()))
def test_boolean_rows_read_through_to_the_setting(settings, key, setting):
    panel = SettingsPanel()
    settings.set_setting(setting, True)
    assert panel.value_for(key, settings) == ("ON", False)
    settings.set_setting(setting, False)
    assert panel.value_for(key, settings) == ("OFF", True)


def test_active_difficulty_chip_follows_the_setting(settings):
    panel = SettingsPanel()
    for index, (level, _label) in enumerate(SettingsPanel.DIFFICULTIES):
        settings.set_difficulty(level)
        assert panel.difficulty_index(settings) == index


def test_difficulty_steps_both_ways_and_wraps(settings):
    """The old screen had no selected state at all; this row is the fix, so
    the cursor has to land somewhere real from either direction."""
    panel = SettingsPanel()
    settings.set_difficulty(DifficultyLevel.ROOKIE)
    assert panel.activate('difficulty', settings, -1) == (
        'set_difficulty', DifficultyLevel.HALL_OF_FAME.value)
    assert panel.activate('difficulty', settings, 1) == (
        'set_difficulty', DifficultyLevel.AMATEUR.value)


def test_clicking_a_chip_selects_that_difficulty_directly(surface, settings):
    panel = _rendered_settings(surface, settings)
    for rect, index in panel._chip_rects:
        action = panel.activate(panel.hit_test(rect.center), settings)
        assert action == ('set_difficulty',
                          SettingsPanel.DIFFICULTIES[index][0].value)


# ── Actions resolve to real Game methods ─────────────────────────────────

def test_every_row_resolves_to_an_action(surface, settings):
    panel = _rendered_settings(surface, settings)
    for rect, key in panel._row_rects:
        assert panel.hit_test(rect.center) == key
        assert panel.activate(key, settings) is not None


def test_every_action_maps_to_a_game_method():
    """The panel names an intent and MenuState maps it to Game. A typo in
    either half is a crash on click, which no rendering test would catch."""
    from strikefactor.main import Game

    actions = set(SettingsPanel._ACTIONS.values()) | {'set_difficulty'}
    assert actions == set(MenuState._SETTINGS_ACTIONS)
    for method_name in MenuState._SETTINGS_ACTIONS.values():
        assert callable(getattr(Game, method_name, None)), method_name


# ── Keyboard navigation covers exactly what is drawn ─────────────────────

def test_settings_keyboard_nav_covers_difficulty_plus_every_row(surface, settings):
    panel = _rendered_settings(surface, settings)
    drawn = [key for _rect, key in panel._row_rects]
    assert panel._nav_keys == [SettingsPanel.DIFFICULTY_KEY] + drawn


def _render_at(panel, settings, selected):
    """Render onto a fresh surface with the cursor on ``selected``."""
    surface = pygame.Surface((1280, 720))
    surface.fill((0, 0, 0))
    panel.selected = selected
    panel.render(surface, settings)
    return surface


def _row_rect(panel, key):
    return dict((k, r) for r, k in panel._row_rects)[key]


def test_every_row_can_actually_show_the_cursor(surface, settings):
    """Nav order is static for a reason: a list accumulated during render is
    always short by exactly the row in hand, so the last row could never see
    itself as selected and the cursor would vanish on it. Drive every index
    and require the highlight to land on that row and nowhere else.
    """
    panel = SettingsPanel()
    # Index 0 is the difficulty chip row, which highlights its chips instead.
    for index in range(1, len(panel._nav_keys)):
        key = panel._nav_keys[index]
        lit = _render_at(panel, settings, index)
        dark = _render_at(panel, settings, 0)
        rect = _row_rect(panel, key)
        assert pygame.surfarray.array3d(lit.subsurface(rect)).sum() > \
            pygame.surfarray.array3d(dark.subsurface(rect)).sum(), \
            f"row {key} never highlights when selected"


def test_cursor_clamps_at_both_ends(surface, settings):
    panel = _rendered_settings(surface, settings)
    panel.move(-99)
    assert panel.selected == 0
    panel.move(99)
    assert panel.selected == len(panel._nav_keys) - 1


# ── Key bindings ─────────────────────────────────────────────────────────

def test_every_bindable_action_has_a_row():
    """TOGGLE_HUD_MODE was bound and dispatched but had no button, so it was
    unrebindable. A drawn list has no per-row cost — list all of them."""
    assert set(KeyBindingsPanel.ACTIONS) == set(KeyAction)


def test_pending_rebind_changes_only_its_own_row(bindings):
    """The 'press a key' prompt used to be written into a button's label. It
    is now drawn from Game state, so check it actually reaches the screen —
    and touches no other row."""
    panel = KeyBindingsPanel()
    target = KeyAction.QUICK_PITCH

    idle = pygame.Surface((1280, 720))
    idle.fill((0, 0, 0))
    panel.render(idle, bindings)
    rects = {key: rect for rect, key in panel._row_rects}

    pending = pygame.Surface((1280, 720))
    pending.fill((0, 0, 0))
    panel.render(pending, bindings, pending=target)

    for action, rect in rects.items():
        same = (pygame.surfarray.array3d(idle.subsurface(rect)) ==
                pygame.surfarray.array3d(pending.subsurface(rect))).all()
        if action == target:
            assert not same, "the pending row drew no prompt"
        else:
            assert same, f"{action} changed while rebinding {target}"


def test_the_settings_page_has_headroom_left():
    """The page is nearly full: with the DEFENSE row it bottoms out at 614
    against a 628 divider, so exactly *no* further row fits at this stride.

    The margin is asserted so the next person to add a setting finds out at
    review time rather than by looking at a screenshot. When it fails, the
    answer is not to shave the stride again — it is a scroll, a second column,
    or a sub-screen.
    """
    panel = sp.SettingsPanel()
    settings = SettingsManager()
    surface = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    panel.render(surface, settings)
    bottom = max(rect.bottom for rect, _ in panel._row_rects)
    assert bottom <= sp._FOOTER_DIVIDER_Y - 8, (
        f"settings rows reach {bottom}, divider at {sp._FOOTER_DIVIDER_Y}")


def test_the_defense_row_shows_the_current_level():
    panel = sp.SettingsPanel()
    settings = SettingsManager()
    original = settings.get_setting("defense_strength")
    try:
        settings.current_settings["defense_strength"] = "gold_glove"
        assert panel.value_for('defense', settings)[0] == "GOLD GLOVE"
        settings.current_settings["defense_strength"] = "league"
        assert panel.value_for('defense', settings)[0] == "LEAGUE"
    finally:
        settings.current_settings["defense_strength"] = original
