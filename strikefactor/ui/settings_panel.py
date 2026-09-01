"""Settings and key-binding screens, drawn in the GameDay chrome.

These two screens used to be grids of absolutely-positioned ``pygame_gui``
buttons declared as literal rects in ``UIManager._create_game_buttons``. Nothing
was derived from the screen width, so each row ended up centred on a *different*
axis — with the screen centre at 640, the difficulty rows sat at 620, the
toggle row at 800 (its right edge 10px off the screen), the FPS row at 740 and
only the bottom pair at 640. That is what read as "off centre": the two correct
rows anchored the eye and everything above them appeared to drift.

The fix is not better literals. Layout here is a **cursor walked down the
page** (``render``), so every rect comes from ``gameday_theme``'s margins and
the row stride; a row cannot drift off-centre because no row carries an x of its
own. ``tests/test_settings_layout.py`` guards the containment and the fact that
the old button grid is gone.

The panels are presentational in the same sense as
:mod:`strikefactor.ui.play_by_play_panel`: they draw, they hit-test, and they
return an **action tuple** for the owning state to dispatch. They never touch
``Game``, a ``SettingsManager`` write path or a key binding, which is what lets
the tests drive them with plain fakes.
"""

import pygame

from strikefactor.key_binding_manager import KeyAction
from strikefactor.settings_manager import DifficultyLevel
from strikefactor.ui import gameday_theme as gdt

# ── Vertical rhythm ──────────────────────────────────────────────────────
# One cursor walks the page; these are the only spacings involved. The
# headline is `big` (30) rather than the GameDay setup screen's `huge` (60):
# that screen has a single card to show off, this one has ten rows to fit, and
# a 60px headline eats a third of the page before the first setting.
_SUBHEAD_Y = 58
_HEADLINE_Y = 76
_HINT_Y = 88
# Reclaimed 12px when the DEFENSE row landed: eight rows at the old
# _CONTENT_TOP/_SECTION_GAP put the last one's bottom at 632, four past
# _FOOTER_DIVIDER_Y. Taken out of the dead air above the list rather than out
# of _ROW_STRIDE, because the rows are the content — compressing the stride to
# 34 fits too, but pays for the new row with 4px of every other row's gutter.
# The headline box ends at y=106, so 120 still leaves 14px of air.
_CONTENT_TOP = 120

_SECTION_GAP = 16          # space above a section label
_SECTION_LABEL_H = 22
_ROW_STRIDE = 38
_ROW_H = 32
_ROW_PAD_X = 16

_CHIP_PAD_Y = 4
_CAPTION_GAP = 10          # chips -> difficulty description
_CAPTION_H = 26

_FOOTER_DIVIDER_Y = 628


def content_bounds():
    """(left, right) of the single content column. Everything lives inside."""
    return gdt.MARGIN_X, gdt.SCREEN_W - gdt.MARGIN_X


class _RowPanel:
    """Shared chrome + row hit-testing for the settings and keybind screens.

    Subclasses supply the header text and a static nav order; this owns the
    cursor layout, the keyboard cursor, hover, and drawing a label/value row.
    """

    HEADER = "=== SETTINGS ==="
    SUBTITLE = ""
    HEADLINE = "SETTINGS."
    # Keys the screen actually answers to — the two screens differ, so this
    # cannot be one shared string.
    HINT = "UP / DOWN  MOVE      ESC  BACK"

    def __init__(self):
        self._fonts = None
        self.selected = 0
        self._row_rects = []   # [(rect, nav_key)] rebuilt every render
        # Nav order is static, *not* accumulated during render: a row needs to
        # know whether it is the selected one while it is being drawn, and a
        # list built as we go is always short by exactly the row in hand.
        self._nav_keys = []

    # --- fonts ---
    def _f(self):
        if self._fonts is None:
            self._fonts = gdt.load_fonts()
        return self._fonts

    # --- keyboard cursor ---
    def move(self, delta):
        """Move the keyboard cursor, clamped to the row list."""
        if not self._nav_keys:
            return
        self.selected = max(0, min(len(self._nav_keys) - 1,
                                   self.selected + delta))

    def reset_cursor(self):
        self.selected = 0

    def selected_key(self):
        if 0 <= self.selected < len(self._nav_keys):
            return self._nav_keys[self.selected]
        return None

    def hit_test(self, pos):
        """Return the nav key under ``pos``, or None."""
        for rect, key in self._row_rects:
            if rect.collidepoint(pos):
                return key
        return None

    def select_key(self, key):
        """Move the keyboard cursor onto ``key`` if it is a nav stop."""
        if key in self._nav_keys:
            self.selected = self._nav_keys.index(key)

    # --- drawing primitives ---
    def _draw_chrome(self, screen):
        f = self._f()
        screen.fill(gdt.BG)
        gdt.draw_top_chrome(screen, self.HEADER, f)
        if self.SUBTITLE:
            gdt.blit_text(screen, self.SUBTITLE, f['micro'],
                          (gdt.MARGIN_X, _SUBHEAD_Y), gdt.DIM)
        gdt.blit_text(screen, self.HEADLINE, f['big'],
                      (gdt.MARGIN_X, _HEADLINE_Y), gdt.FG)
        _, right = content_bounds()
        gdt.blit_text(screen, self.HINT, f['micro'], (right, _HINT_Y),
                      gdt.DIM_SOFT, align='right')
        return f

    def _draw_section(self, screen, label, y):
        """Draw a section label. Returns the y of the first row beneath it."""
        gdt.blit_text(screen, label, self._f()['micro'],
                      (gdt.MARGIN_X, y), gdt.DIM)
        return y + _SECTION_LABEL_H

    def _draw_row(self, screen, key, label, value, y, mouse, value_dim=False):
        """Draw one label/value row and register it for hit-testing.

        Returns the y of the next row. Rows carry no x of their own — they
        span the whole content column, so the value column is anchored to the
        page's right margin rather than to a per-row literal.
        """
        f = self._f()
        left, right = content_bounds()
        rect = pygame.Rect(left, y, right - left, _ROW_H)
        active = rect.collidepoint(mouse) or self.selected_key() == key

        if active:
            pygame.draw.rect(screen, (20, 20, 20), rect)
            pygame.draw.rect(screen, gdt.FG, rect, 1)
        else:
            pygame.draw.line(screen, gdt.DIVIDER, (rect.left, rect.bottom),
                             (rect.right, rect.bottom), 1)

        gdt.blit_text(screen, label, f['small'],
                      (rect.left + _ROW_PAD_X, rect.centery - 11),
                      gdt.FG if active else gdt.DIM)
        # An OFF value stays dim unless its row is active, so the state of the
        # whole list is scannable without reading every word.
        value_color = gdt.DIM_SOFT if (value_dim and not active) else gdt.FG
        gdt.blit_text(screen, value, f['med'],
                      (rect.right - _ROW_PAD_X, rect.centery - 13),
                      value_color, align='right')

        self._row_rects.append((rect, key))
        return y + _ROW_STRIDE

    def _draw_footer(self, screen):
        left, right = content_bounds()
        pygame.draw.line(screen, gdt.DIVIDER, (left, _FOOTER_DIVIDER_Y),
                         (right, _FOOTER_DIVIDER_Y), 1)


class SettingsPanel(_RowPanel):
    """The settings screen: difficulty chips over three sections of rows."""

    HEADER = "=== SETTINGS ==="
    SUBTITLE = "TUNE THE AT-BAT"
    HEADLINE = "SETTINGS."
    HINT = "UP / DOWN  MOVE      LEFT / RIGHT  CHANGE      ESC  BACK"

    # Difficulty in ladder order. The chip row *is* the selected-state
    # indicator — the five old buttons were styled identically, so the only
    # cue that Amateur was active was a banner in a different corner.
    DIFFICULTIES = [
        (DifficultyLevel.ROOKIE, "ROOKIE"),
        (DifficultyLevel.AMATEUR, "AMATEUR"),
        (DifficultyLevel.PROFESSIONAL, "PROFESSIONAL"),
        (DifficultyLevel.ALL_STAR, "ALL-STAR"),
        (DifficultyLevel.HALL_OF_FAME, "HALL OF FAME"),
    ]

    DIFFICULTY_KEY = 'difficulty'

    # (nav key, row label, action id). Sections are display grouping only.
    SECTIONS = [
        ("GAMEPLAY", [
            ('defense', "DEFENSE", 'cycle_defense_strength'),
            ('strikezone', "STRIKEZONE", 'toggle_strikezone'),
            ('abs', "ABS CHALLENGE", 'toggle_abs'),
            ('foul_animation', "FOUL ANIMATION", 'toggle_foul_animation'),
        ]),
        ("PRESENTATION", [
            ('hud', "HUD", 'cycle_hud_mode'),
            ('umpire_sound', "UMPIRE SOUND", 'toggle_umpire_sound'),
        ]),
        ("PERFORMANCE", [
            ('display_fps', "DISPLAY FPS", 'cycle_display_fps'),
            ('engine_fps', "ENGINE FPS", 'cycle_engine_fps'),
        ]),
    ]

    _BOOL_SETTING = {
        'strikezone': 'show_strikezone',
        'abs': 'abs_enabled',
        'foul_animation': 'foul_animation_enabled',
        'umpire_sound': 'umpire_sound',
    }

    _ACTIONS = {key: action
                for _title, rows in SECTIONS
                for key, _label, action in rows}

    def __init__(self):
        super().__init__()
        self._chip_rects = []
        self._nav_keys = [self.DIFFICULTY_KEY] + [
            key for _title, rows in self.SECTIONS for key, _l, _a in rows]

    # --- values ---
    def value_for(self, key, settings_manager):
        """(text, is_dim) for a row's value column."""
        if key in self._BOOL_SETTING:
            on = bool(settings_manager.get_setting(self._BOOL_SETTING[key]))
            return ("ON" if on else "OFF"), not on
        if key == 'defense':
            return settings_manager.get_defense_level().replace("_", " ").upper(), False
        if key == 'hud':
            return settings_manager.get_hud_mode().upper(), False
        if key == 'display_fps':
            return str(settings_manager.get_display_fps()), False
        if key == 'engine_fps':
            return str(settings_manager.get_engine_fps()), False
        return "", False

    def _caption(self, settings_manager):
        """The difficulty blurb, minus the level name the chip already shows.

        ``get_difficulty_description`` returns "Amateur: Balanced gameplay"
        because it used to be the only thing on screen naming the level.
        """
        description = settings_manager.get_difficulty_description()
        _name, sep, blurb = description.partition(": ")
        return blurb if sep else description

    def difficulty_index(self, settings_manager):
        current = settings_manager.get_difficulty()
        for i, (level, _label) in enumerate(self.DIFFICULTIES):
            if level == current:
                return i
        return 1  # AMATEUR

    # --- interaction ---
    def hit_test(self, pos):
        """Rows first, then the difficulty chips (which carry their index)."""
        key = super().hit_test(pos)
        if key is not None:
            return key
        for rect, index in self._chip_rects:
            if rect.collidepoint(pos):
                return (self.DIFFICULTY_KEY, index)
        return None

    def activate(self, key, settings_manager, direction=1):
        """Resolve a nav key into an ``(action_id, payload)`` for the caller.

        Every row is a cycle — a boolean is just a two-long one — so ENTER,
        LEFT and RIGHT all route here, and forward-only cycles simply ignore
        ``direction``. Difficulty is the one row that steps both ways, so it
        resolves to an explicit target rather than to a "next" action.
        """
        if isinstance(key, tuple) and key[0] == self.DIFFICULTY_KEY:
            return ('set_difficulty', self.DIFFICULTIES[key[1]][0].value)
        if key == self.DIFFICULTY_KEY:
            index = (self.difficulty_index(settings_manager)
                     + direction) % len(self.DIFFICULTIES)
            return ('set_difficulty', self.DIFFICULTIES[index][0].value)
        action = self._ACTIONS.get(key)
        return None if action is None else (action, None)

    def activate_selected(self, settings_manager, direction=1):
        key = self.selected_key()
        return None if key is None else self.activate(key, settings_manager,
                                                      direction)

    def select_key(self, key):
        """Chip hits arrive as ``(DIFFICULTY_KEY, index)``; both land on the
        one difficulty nav stop."""
        if isinstance(key, tuple):
            key = key[0]
        super().select_key(key)

    # --- render ---
    def render(self, screen, settings_manager):
        f = self._draw_chrome(screen)
        self._row_rects = []
        self._chip_rects = []
        mouse = pygame.mouse.get_pos()

        y = self._draw_section(screen, "DIFFICULTY", _CONTENT_TOP)
        self._chip_rects = gdt.draw_chips(
            screen, f['tiny'], [label for _l, label in self.DIFFICULTIES],
            self.difficulty_index(settings_manager), gdt.MARGIN_X, y,
            pad_y=_CHIP_PAD_Y, anchor='left')
        chip_bottom = max(r.bottom for r, _i in self._chip_rects)
        if self.selected_key() == self.DIFFICULTY_KEY:
            chip_right = max(r.right for r, _i in self._chip_rects)
            pygame.draw.line(screen, gdt.FG, (gdt.MARGIN_X, chip_bottom + 3),
                             (chip_right, chip_bottom + 3), 1)

        # The difficulty description is a caption under its own control, in
        # `small` DIM. It used to be the shared 80px banner label, which made a
        # settings *value* the loudest thing on a page whose own title was
        # smaller — the banner is for in-game results, not for chrome.
        y = chip_bottom + _CAPTION_GAP
        gdt.blit_text(screen, self._caption(settings_manager),
                      f['small'], (gdt.MARGIN_X, y), gdt.DIM)
        y += _CAPTION_H

        for title, rows in self.SECTIONS:
            y = self._draw_section(screen, title, y + _SECTION_GAP)
            for key, label, _action in rows:
                value, dim = self.value_for(key, settings_manager)
                y = self._draw_row(screen, key, label, value, y, mouse,
                                   value_dim=dim)

        self._draw_footer(screen)


class KeyBindingsPanel(_RowPanel):
    """The key-binding screen: one row per bindable action."""

    HEADER = "=== SETTINGS · KEY BINDINGS ==="
    SUBTITLE = "PICK A ROW, THEN PRESS A KEY"
    HEADLINE = "KEY BINDINGS."
    HINT = "UP / DOWN  MOVE      ENTER  REBIND      ESC  BACK"

    # TOGGLE_HUD_MODE is bound (U) and dispatched like every other hotkey, but
    # the old screen had no button for it, so it was unrebindable and
    # undiscoverable. A drawn list has no per-row cost, so it is listed here.
    ACTIONS = [
        KeyAction.TOGGLE_UI,
        KeyAction.TOGGLE_STRIKEZONE,
        KeyAction.TOGGLE_SOUND,
        KeyAction.TOGGLE_BATTER,
        KeyAction.QUICK_PITCH,
        KeyAction.VIEW_PITCHES,
        KeyAction.TOGGLE_TRACK,
        KeyAction.TOGGLE_HUD_MODE,
        KeyAction.CHALLENGE,
        KeyAction.SWING_REPLAY,
        KeyAction.MAIN_MENU,
    ]

    def __init__(self):
        super().__init__()
        self._nav_keys = list(self.ACTIONS)

    def activate_selected(self):
        """Return the KeyAction under the keyboard cursor, or None."""
        return self.selected_key()

    def render(self, screen, key_binding_manager, pending=None, error=None):
        """Draw the list. ``pending`` is the action awaiting a keypress."""
        f = self._draw_chrome(screen)
        self._row_rects = []
        mouse = pygame.mouse.get_pos()

        y = self._draw_section(screen, "CONTROLS", _CONTENT_TOP)
        for action in self.ACTIONS:
            label = key_binding_manager.get_action_name(action).upper()
            if action == pending:
                value = "PRESS A KEY"
            else:
                value = key_binding_manager.get_key_name(
                    key_binding_manager.get_key_for_action(action)).upper()
            y = self._draw_row(screen, action, label, value, y, mouse)

        # Rebind collisions report here rather than through the shared banner,
        # for the same reason the difficulty description does.
        if error:
            gdt.blit_text(screen, error.upper(), f['small'],
                          (gdt.MARGIN_X, y + 14), gdt.FG)

        self._draw_footer(screen)
