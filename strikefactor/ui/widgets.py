"""Buttons a screen owns: specs, hit-testing and the keyboard cursor.

Every button in the game used to be a ``pygame_gui`` widget created up front in
one dictionary, shown and hidden by a switch keyed on the name of the screen.
The library drew its widgets on top of everything and hit-tested them
globally, so a modal had to hide the buttons underneath it by pretending to be
a different screen, and two screens that shared a widget moved it back and
forth.

Here a button is a value. A state lists the ones it has *right now*
(``buttons()``, a function of its own phase or page), hands them to a
:class:`ButtonGroup`, draws the group inside its own ``render`` and asks it
about events inside its own ``handle_event``. Whatever is drawn later covers
them, and a handler that returns early never reaches them, so z-order and
modality are just the order of the code.

The group is presentational in the same sense as
:mod:`strikefactor.ui.settings_panel`: it returns the *action* of the button
that fired and never calls anything. The owning state maps actions to methods,
which is what lets the tests enumerate a screen's buttons without a ``Game``.

Drawing is :func:`strikefactor.ui.gameday_theme.draw_button`; this module adds
only the state that function is told about.
"""

from typing import Hashable, NamedTuple

import pygame

from strikefactor.ui import gameday_theme as gdt
from strikefactor.ui import pointer

_ACTIVATE_KEYS = (pygame.K_RETURN, pygame.K_KP_ENTER)
_NEXT_KEYS = (pygame.K_DOWN, pygame.K_RIGHT)
_PREV_KEYS = (pygame.K_UP, pygame.K_LEFT)


class Button(NamedTuple):
    """One button, as a screen states it. See ``gdt.draw_button`` for looks."""

    action: Hashable
    label: str
    rect: pygame.Rect
    style: str = 'default'      # 'default' | 'primary'
    enabled: bool = True
    selected: bool = False


class ButtonGroup:
    """The buttons on screen now, the one under the cursor, and what fired.

    ``arrows`` says whether the arrow keys move the cursor. A screen whose
    arrows already mean something (a carousel, a paged list, a column of
    rows) leaves it off and keeps TAB, which always cycles.

    ``default`` is the action ENTER fires while no button holds the keyboard
    cursor: the screen's primary action, so ENTER works before any TAB.
    """

    def __init__(self, *, arrows=False, default=None):
        self.arrows = arrows
        self.default = default
        self.buttons = []
        # Index of the button holding the keyboard cursor, or None. The
        # pointer and the keyboard never highlight two buttons at once:
        # moving the mouse hands the highlight back to hover.
        self.focus = None

    def set(self, buttons):
        """Replace the buttons. The cursor stays on its action if it can."""
        held = self.focused_action()
        self.buttons = list(buttons)
        self.focus = next(
            (i for i, b in enumerate(self.buttons)
             if b.enabled and b.action == held and held is not None), None)

    def clear_focus(self):
        self.focus = None

    def focused_action(self):
        if self.focus is None or self.focus >= len(self.buttons):
            return None
        return self.buttons[self.focus].action

    def hit_test(self, pos):
        """The action of the enabled button under ``pos``, or None."""
        for button in self.buttons:
            if button.enabled and button.rect.collidepoint(pos):
                return button.action
        return None

    def move_focus(self, step):
        """Step the keyboard cursor to the next enabled button, wrapping."""
        stops = [i for i, b in enumerate(self.buttons) if b.enabled]
        if not stops:
            self.focus = None
            return
        if self.focus not in stops:
            self.focus = stops[0] if step > 0 else stops[-1]
            return
        self.focus = stops[(stops.index(self.focus) + step) % len(stops)]

    def handle_event(self, event):
        """Return the action ``event`` fires, or None.

        A button fires on the press (left button down), as every drawn row,
        chip and Review control already does. Nothing listens for the
        release.
        """
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button != 1:
                return None
            return self.hit_test(event.pos)
        if event.type == pygame.MOUSEMOTION:
            self.focus = None
            return None
        if event.type != pygame.KEYDOWN:
            return None

        if event.key == pygame.K_TAB:
            back = bool(getattr(event, 'mod', 0) & pygame.KMOD_SHIFT)
            self.move_focus(-1 if back else 1)
        elif self.arrows and event.key in _NEXT_KEYS:
            self.move_focus(1)
        elif self.arrows and event.key in _PREV_KEYS:
            self.move_focus(-1)
        elif event.key in _ACTIVATE_KEYS:
            focused = self.focused_action()
            if focused is not None:
                return focused
            if any(b.enabled and b.action == self.default
                   for b in self.buttons):
                return self.default
        return None

    def draw(self, screen, fonts=None):
        fonts = fonts or gdt.load_fonts()
        pos = pointer.pos()
        for index, button in enumerate(self.buttons):
            active = (index == self.focus
                      or (self.focus is None
                          and button.rect.collidepoint(pos)))
            gdt.draw_button(screen, fonts, button.label, button.rect,
                            style=button.style, enabled=button.enabled,
                            selected=button.selected, active=active)
