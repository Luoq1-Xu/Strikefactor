"""Pitcher selection carousel: the card on every pitcher-pick screen.

The card is a scouting report: portrait, name, handedness and command, then
the arsenal, one row per pitch with its share of the pitcher's usual mix.
That share is the usage prior his AI is anchored to (ai/pitch_priors.py), read
off the attached AI so the card and the pitch selection cannot disagree.

GameDay's card also shows the player's win-loss record against him. Arcade
and Sandbox have no games to win or lose, so theirs leaves it off
(``show_record``).

Navigation is handled externally through the `prev()` / `next()` /
`get_selected()` methods. The carousel is purely presentational:
`ui/pitcher_select.py` owns the arrows, the keys and the buttons around it and
calls into these methods.
"""

import pygame

from strikefactor.gameplay.gameday_manager import ALL_PITCHERS, GameDayManager
from strikefactor.ui import gameday_theme as gdt

# Pitcher handedness is encoded only in sprite paths (e.g. ".../sale/LEFTY"),
# so keep a small static map here rather than reaching into each pitcher class.
PITCHER_HANDEDNESS = {
    'sale': 'LHP',
    'degrom': 'RHP',
    'yamamoto': 'RHP',
    'sasaki': 'RHP',
    'mcclanahan': 'LHP',
}

# Display names for the arsenal rows. An unlisted code is shown as itself.
PITCH_NAMES = {
    'FF': 'Four-Seam',
    'SI': 'Sinker',
    'FC': 'Cutter',
    'SL': 'Slider',
    'CB': 'Curveball',
    'CH': 'Changeup',
    'FS': 'Splitter',
}

# Info column layout, in px from the card's edges.
_INFO_LEFT = 195
_INFO_RIGHT = 18
_INFO_TOP = 16
_INFO_BOTTOM = 16
_ROW_H = 26
_BAR_LEFT = 150          # from the column's left edge, after the pitch name
_BAR_RIGHT = 60          # from the column's right edge, before the percentage
_BAR_H = 6


def arsenal_rows(pitcher):
    """``[(code, display name, share)]``, most-used first.

    ``share`` is the fraction of the AI's usage prior, or None when no AI
    is attached. Ties keep arsenal order.
    """
    ai = getattr(pitcher, 'ai', None)
    mix = ai.usage_prior() if ai is not None else {}
    rows = [(code, PITCH_NAMES.get(code, code), mix.get(code))
            for code in pitcher.get_pitch_names()]
    return sorted(rows, key=lambda row: -(row[2] or 0.0))


class PitcherCarousel:
    """Cyclic selector over the gameday pitcher roster."""

    # Monochrome palette to match the refreshed GameDay screens.
    CARD_BG = (8, 8, 8)
    CARD_BORDER = (90, 90, 90)
    ACCENT = (240, 240, 240)
    LABEL_COLOR = (140, 140, 140)
    MUTED = (150, 150, 150)
    SEPARATOR = (60, 60, 60)
    PORTRAIT_BG = (0, 0, 0)

    def __init__(self, pitcher_manager, default: str = 'yamamoto', *, show_record=False):
        self.pitcher_manager = pitcher_manager
        self.order = list(ALL_PITCHERS)
        self.show_record = show_record
        # GameDay records, read once per visit rather than once per frame:
        # each read opens the history file.
        self._records = {}
        self.reset(default)

    # --- Navigation ---

    def reset(self, default: str = 'yamamoto'):
        """Reset the carousel to the given default pitcher."""
        if default in self.order:
            self.index = self.order.index(default)
        else:
            self.index = 0
        self.refresh()

    def refresh(self):
        """Forget cached records, so the next draw reads history again."""
        self._records.clear()

    def next(self):
        self.index = (self.index + 1) % len(self.order)

    def prev(self):
        self.index = (self.index - 1) % len(self.order)

    def get_selected(self) -> str:
        return self.order[self.index]

    # --- Rendering ---

    def render(self, screen, rect: pygame.Rect):
        """Draw the carousel card into `rect`."""
        pitcher_name = self.get_selected()
        pitcher = self.pitcher_manager.get_pitcher(pitcher_name)
        if pitcher is None:
            return

        # Card background + thin border (no rounded corners — matches the
        # rest of the refreshed gameday chrome).
        pygame.draw.rect(screen, self.CARD_BG, rect)
        pygame.draw.rect(screen, self.CARD_BORDER, rect, width=1)

        self._draw_portrait(screen, pitcher, rect)
        self._draw_info(screen, pitcher, pitcher_name, rect)

    def _draw_portrait(self, screen, pitcher, rect: pygame.Rect):
        """Blit the pitcher's first windup frame scaled to fit the left panel."""
        panel_w = 165
        panel_margin = 14
        panel_rect = pygame.Rect(
            rect.left + panel_margin,
            rect.top + panel_margin,
            panel_w,
            rect.height - 2 * panel_margin,
        )
        pygame.draw.rect(screen, self.PORTRAIT_BG, panel_rect)
        pygame.draw.rect(screen, self.SEPARATOR, panel_rect, width=1)

        sprites = getattr(pitcher, 'sprites', None)
        if not sprites:
            return

        sprite = sprites[0]
        sw, sh = sprite.get_size()
        # Fit sprite inside the panel while preserving aspect ratio.
        scale = min((panel_rect.width - 12) / sw, (panel_rect.height - 12) / sh)
        scale = max(scale, 0.01)
        new_size = (max(1, int(sw * scale)), max(1, int(sh * scale)))
        scaled = pygame.transform.smoothscale(sprite, new_size)
        blit_x = panel_rect.centerx - new_size[0] // 2
        blit_y = panel_rect.centery - new_size[1] // 2
        screen.blit(scaled, (blit_x, blit_y))

    def _draw_info(self, screen, pitcher, pitcher_name: str, rect: pygame.Rect):
        """Name, handedness and command, the arsenal, and GameDay's record."""
        fonts = gdt.load_fonts()
        left = rect.left + _INFO_LEFT
        right = rect.right - _INFO_RIGHT
        y = rect.top + _INFO_TOP

        name_surf = fonts['title'].render(pitcher.name, True, self.ACCENT)
        screen.blit(name_surf, (left, y))
        y += name_surf.get_height() + 1

        hand = PITCHER_HANDEDNESS.get(pitcher_name, '')
        command = getattr(pitcher, 'command', None)
        sub_parts = []
        if hand:
            sub_parts.append(hand)
        if command is not None:
            sub_parts.append(f"Command {command:.2f}")
        if sub_parts:
            sub_surf = fonts['big'].render("  ·  ".join(sub_parts), True, self.LABEL_COLOR)
            screen.blit(sub_surf, (left, y))
            y += sub_surf.get_height() + 5

        pygame.draw.line(screen, self.SEPARATOR, (left, y), (right, y), 1)
        y += 10

        bottom = rect.bottom - _INFO_BOTTOM
        if self.show_record:
            bottom = self._draw_record(screen, fonts, pitcher_name, left, right, bottom)
        self._draw_arsenal(screen, fonts, pitcher, left, right, y, bottom)

    def _draw_arsenal(self, screen, fonts, pitcher, left, right, y, bottom):
        """One row per pitch: name, a usage bar on a 0-100% track, the share."""
        gdt.blit_text(screen, "ARSENAL", fonts['micro'], (left, y), self.LABEL_COLOR)
        gdt.blit_text(screen, "USAGE", fonts['micro'], (right, y), self.LABEL_COLOR,
                      align='right')
        y += 20
        font = fonts['med']
        track = pygame.Rect(left + _BAR_LEFT, 0, right - _BAR_RIGHT - left - _BAR_LEFT, _BAR_H)
        for _, name, share in arsenal_rows(pitcher):
            if y + font.get_height() > bottom:
                break  # never draw over the record or past the card
            gdt.blit_text(screen, name, font, (left, y), self.ACCENT)
            if share is not None:
                track.centery = y + font.get_height() // 2
                pygame.draw.rect(screen, self.SEPARATOR, track)
                fill = track.copy()
                fill.width = round(track.width * share)
                pygame.draw.rect(screen, self.ACCENT, fill)
                gdt.blit_text(screen, f"{share * 100:.0f}%", font, (right, y),
                              self.ACCENT, align='right')
            y += _ROW_H

    def _draw_record(self, screen, fonts, pitcher_name, left, right, bottom):
        """The GameDay record along the card's foot; returns the space left above it."""
        record = self._record(pitcher_name)
        font = fonts['med']
        y = bottom - font.get_height()
        line_y = y - 8
        pygame.draw.line(screen, self.SEPARATOR, (left, line_y), (right, line_y), 1)
        gdt.blit_text(screen, "Your record", font, (left, y), self.LABEL_COLOR)
        if record['total'] > 0:
            text, color = f"{record['wins']}W - {record['losses']}L", self.ACCENT
        else:
            text, color = "never faced", self.MUTED
        gdt.blit_text(screen, text, font, (right, y), color, align='right')
        return line_y - 6

    def _record(self, pitcher_name):
        if pitcher_name not in self._records:
            self._records[pitcher_name] = GameDayManager.load_history_record_vs(pitcher_name)
        return self._records[pitcher_name]
