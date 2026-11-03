"""The pitcher-pick screen: one layout for Arcade, Sandbox and GameDay.

GameDay's setup screen was the only one of the three drawn this way; the other
two were a typewriter title over five loose buttons. They ask the same
question, so they are one screen now, configured by the owning state with a
header, the label on the confirm button and whatever extra buttons that mode
has (GameDay's RESUME and PAST GAMES, Arcade's RANDOM SCENARIO).

Presentational in the same sense as :mod:`strikefactor.ui.settings_panel`: it
draws, it hit-tests and it returns an **action id** for the state to dispatch.
It never touches ``Game``. Turning the carousel is the one thing it does
itself, because that changes nothing outside the screen.

Actions returned by :meth:`PitcherSelect.handle_event`:

- ``'confirm'``: the player chose :meth:`selected` (the button, or ENTER)
- ``'back'``: the BACK button, or ESC
- the action id of any extra button the state supplied
"""

import pygame

from strikefactor.ui import gameday_theme as gdt
from strikefactor.ui.pitcher_carousel import PitcherCarousel
from strikefactor.ui.widgets import Button, ButtonGroup

# Tall enough for a five-pitch arsenal plus GameDay's record line.
CARD_RECT = pygame.Rect(310, 196, 660, 320)

# The arrows flank the card, centred on it; the confirm button is centred
# under it, and one row of secondary buttons can sit beneath that.
_ARROW = 50
_ARROW_GAP = 5
_CONFIRM_RECT = pygame.Rect(490, 580, 300, 44)
_EXTRA_Y = 634
_EXTRA_H = 36
_EXTRA_GAP = 10
_HINT_Y = CARD_RECT.bottom + 16


class PitcherSelect:
    """A carousel card, its arrows, a confirm button and a BACK button.

    ``extras`` is a callable returning ``[(action, label)]`` for the row under
    the confirm button. A callable rather than a list because what GameDay
    offers there depends on whether a game is waiting to be resumed.
    ``show_record`` puts the player's GameDay record on the card; only
    GameDay, which has games to win or lose, asks for it.
    """

    def __init__(self, pitcher_manager, *, header, subtitle, headline="STEP IN.",
                 confirm_label="STEP IN  >", back_label="<  BACK",
                 extras=None, default='yamamoto', show_record=False):
        self.carousel = PitcherCarousel(pitcher_manager, default=default,
                                        show_record=show_record)
        self.header = header
        self.subtitle = subtitle
        self.headline = headline
        self.confirm_label = confirm_label
        self.back_label = back_label
        self._extras = extras or (lambda: [])
        self._group = ButtonGroup(default='confirm')

    def selected(self) -> str:
        return self.carousel.get_selected()

    def reset(self, default=None):
        """Put the carousel back on ``default`` and drop the keyboard cursor.

        Also re-reads the record on the next draw, since a game may have
        finished since the screen was last open.
        """
        if default is not None:
            self.carousel.reset(default)
        self.carousel.refresh()
        self._group.clear_focus()

    # --- buttons ---

    def buttons(self):
        """Every button on the screen now, as specs."""
        arrow_y = CARD_RECT.centery - _ARROW // 2
        out = [
            Button('prev', "<", pygame.Rect(
                CARD_RECT.left - _ARROW_GAP - _ARROW, arrow_y, _ARROW, _ARROW)),
            Button('next', ">", pygame.Rect(
                CARD_RECT.right + _ARROW_GAP, arrow_y, _ARROW, _ARROW)),
            Button('confirm', self.confirm_label, _CONFIRM_RECT.copy(),
                   style='primary'),
        ]
        extras = self._extras()
        if extras:
            # The row is as wide as the confirm button and split evenly, so
            # one extra spans it and two sit side by side beneath it.
            width = ((_CONFIRM_RECT.width - _EXTRA_GAP * (len(extras) - 1))
                     // len(extras))
            for index, (action, label) in enumerate(extras):
                x = _CONFIRM_RECT.left + index * (width + _EXTRA_GAP)
                if index == len(extras) - 1:
                    width = _CONFIRM_RECT.right - x     # absorb the rounding
                out.append(Button(action, label,
                                  pygame.Rect(x, _EXTRA_Y, width, _EXTRA_H)))
        out.append(Button('back', self.back_label, gdt.footer_back_rect()))
        return out

    # --- events ---

    def handle_event(self, event):
        """Return the action ``event`` fires for the owning state, or None."""
        self._group.set(self.buttons())
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_LEFT:
                self.carousel.prev()
                return None
            if event.key == pygame.K_RIGHT:
                self.carousel.next()
                return None
            if event.key == pygame.K_ESCAPE:
                return 'back'
        action = self._group.handle_event(event)
        if action == 'prev':
            self.carousel.prev()
            return None
        if action == 'next':
            self.carousel.next()
            return None
        return action

    # --- render ---

    def render(self, screen, note=""):
        """Draw the screen. ``note`` is a line under the brand, top right."""
        fonts = gdt.load_fonts()
        screen.fill(gdt.BG)
        gdt.draw_page_header(screen, fonts, self.header, self.subtitle,
                             self.headline)
        if note:
            gdt.blit_text(screen, note, fonts['small'],
                          (gdt.SCREEN_W - gdt.MARGIN_X, 92), gdt.FG,
                          align='right')
        self.carousel.render(screen, CARD_RECT)
        gdt.blit_text(screen, "LEFT / RIGHT  CHOOSE      ENTER  STEP IN"
                              "      ESC  BACK",
                      fonts['micro'], (gdt.SCREEN_W // 2, _HINT_Y),
                      gdt.DIM_SOFT, align='center')
        self._group.set(self.buttons())
        self._group.draw(screen, fonts)
