"""Pitcher selection carousel used on the GameDay intro screen.

Renders a single pitcher "card" (portrait + scouting stats + career record vs.
that pitcher) with left/right navigation handled externally through the
`prev()` / `next()` / `get_selected()` methods. The carousel is purely
presentational - the owning state wires up mouse arrow buttons and keyboard
handling and calls into these methods.
"""

import pygame

from gameplay.gameday_manager import GameDayManager, ALL_PITCHERS
from ui.scouting_panel import COLOR_GRAY


# Pitcher handedness is encoded only in sprite paths (e.g. ".../sale/LEFTY"),
# so keep a small static map here rather than reaching into each pitcher class.
PITCHER_HANDEDNESS = {
    'sale': 'LHP',
    'degrom': 'RHP',
    'yamamoto': 'RHP',
    'sasaki': 'RHP',
    'mcclanahan': 'LHP',
}


class PitcherCarousel:
    """Cyclic selector over the gameday pitcher roster."""

    CARD_BG = (20, 28, 38)
    CARD_BORDER = (90, 120, 160)
    ACCENT = (255, 210, 90)
    LABEL_COLOR = (180, 195, 210)
    SEPARATOR = (60, 75, 95)
    PORTRAIT_BG = (10, 16, 24)

    def __init__(self, pitcher_manager, ui_manager, default: str = 'yamamoto'):
        self.pitcher_manager = pitcher_manager
        self.ui_manager = ui_manager
        self.order = list(ALL_PITCHERS)
        self.reset(default)

    # --- Navigation ---

    def reset(self, default: str = 'yamamoto'):
        """Reset the carousel to the given default pitcher."""
        if default in self.order:
            self.index = self.order.index(default)
        else:
            self.index = 0

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

        # Card background + border
        pygame.draw.rect(screen, self.CARD_BG, rect, border_radius=12)
        pygame.draw.rect(screen, self.CARD_BORDER, rect, width=3, border_radius=12)

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
        pygame.draw.rect(screen, self.PORTRAIT_BG, panel_rect, border_radius=8)

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
        """Draw the name, handedness, command, stats, arsenal, and record."""
        small = self.ui_manager.small_font
        big = self.ui_manager.font

        info_x = rect.left + 195
        info_right = rect.right - 18
        y = rect.top + 16

        # Name
        name_surf = big.render(pitcher.name, True, self.ACCENT)
        screen.blit(name_surf, (info_x, y))
        y += name_surf.get_height() + 1

        # Handedness and command on one line
        hand = PITCHER_HANDEDNESS.get(pitcher_name, '')
        command = getattr(pitcher, 'command', None)
        sub_parts = []
        if hand:
            sub_parts.append(hand)
        if command is not None:
            sub_parts.append(f"Command {command:.2f}")
        if sub_parts:
            sub_surf = small.render("  ·  ".join(sub_parts), True, self.LABEL_COLOR)
            screen.blit(sub_surf, (info_x, y))
            y += sub_surf.get_height() + 5

        # Separator
        pygame.draw.line(screen, self.SEPARATOR,
                         (info_x, y), (info_right, y), 1)
        y += 5

        # Record vs this pitcher
        record = GameDayManager.load_history_record_vs(pitcher_name)
        if record['total'] > 0:
            record_text = (f"Your record: {record['wins']}W - "
                           f"{record['losses']}L - {record['ties']}T")
            record_color = self.ACCENT
        else:
            record_text = "Your record: (never faced)"
            record_color = COLOR_GRAY
        record_surf = small.render(record_text, True, record_color)
        screen.blit(record_surf, (info_x, y))

