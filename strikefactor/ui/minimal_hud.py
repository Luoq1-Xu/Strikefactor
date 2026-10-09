import os

import pygame


class MinimalHUD:
    """Compact corner HUD shown in place of the full scorebug.

    Shows only the essentials — bases, B/S/O count, and score — anchored
    in the bottom-right corner so the field stays mostly unobstructed.
    Shares the scorebug's monochrome palette."""

    # Anchor — bottom-right corner of the 1280x720 logical screen.
    SCREEN_W = 1280
    SCREEN_H = 720
    MARGIN = 14
    PANEL_W = 138
    PANEL_H = 96

    # Palette — strict black/white/gray (matches Scorebug).
    BG_COLOR = (0, 0, 0, 200)
    DIVIDER_COLOR = (90, 90, 90)
    LABEL_COLOR = (140, 140, 140)
    TEXT_COLOR = (240, 240, 240)
    ON_COLOR = (240, 240, 240)
    OFF_COLOR = (50, 50, 50)

    def __init__(self, game):
        self.game = game
        self.visible = True

        font_path = os.path.join(
            os.path.dirname(__file__), "font", "8bitoperator_jve.ttf"
        )
        self.label_font = pygame.font.Font(font_path, 12)
        self.value_font = pygame.font.Font(font_path, 18)

        self._bg_surface = pygame.Surface(
            (self.PANEL_W, self.PANEL_H), pygame.SRCALPHA
        )
        self._bg_surface.fill(self.BG_COLOR)

    def draw(self, screen):
        if not self.visible:
            return

        x = self.SCREEN_W - self.PANEL_W - self.MARGIN
        y = self.SCREEN_H - self.PANEL_H - self.MARGIN

        # Background + thin top/left edge dividers (matches scorebug top line).
        screen.blit(self._bg_surface, (x, y))
        pygame.draw.line(
            screen, self.DIVIDER_COLOR, (x, y), (x + self.PANEL_W, y), 1
        )
        pygame.draw.line(
            screen, self.DIVIDER_COLOR, (x, y), (x, y + self.PANEL_H), 1
        )

        self._draw_bases(screen, x, y)
        self._draw_count(screen, x, y)
        self._draw_score(screen, x, y)

    def _draw_bases(self, screen, x, y):
        """Small base diamond in the top-left of the panel."""
        bases = self.game.scoreKeeper.get_bases()
        cx = x + 24
        cy = y + 26
        size = 6

        # [1B, 2B, 3B] in data → 1B right, 2B top, 3B left
        positions = [(cx + 11, cy), (cx, cy - 11), (cx - 11, cy)]
        for i, (bx, by) in enumerate(positions):
            color = self.ON_COLOR if bases[i] == "yellow" else self.OFF_COLOR
            points = [
                (bx, by - size),
                (bx + size, by),
                (bx, by + size),
                (bx - size, by),
            ]
            pygame.draw.polygon(screen, color, points)
            pygame.draw.polygon(screen, (30, 30, 30), points, 1)

    def _draw_count(self, screen, x, y):
        """Compact B/S/O dots to the right of the bases."""
        bx = x + 56
        by = y + 10
        dot_r = 3
        gap = 9

        rows = [
            ("B", self.game.currentballs, 4),
            ("S", self.game.currentstrikes, 3),
            ("O", self.game.currentouts, 3),
        ]
        for i, (label, value, total) in enumerate(rows):
            row_y = by + i * 12
            label_surf = self.label_font.render(label, True, self.LABEL_COLOR)
            screen.blit(label_surf, (bx, row_y - 2))
            for j in range(total):
                cx = bx + 14 + j * gap
                color = self.ON_COLOR if j < value else self.OFF_COLOR
                pygame.draw.circle(screen, color, (cx, row_y + 4), dot_r)

    def _draw_score(self, screen, x, y):
        """Score line along the bottom of the panel."""
        sy = y + self.PANEL_H - 22

        # Thin divider above the score.
        pygame.draw.line(
            screen,
            self.DIVIDER_COLOR,
            (x + 6, sy - 4),
            (x + self.PANEL_W - 6, sy - 4),
            1,
        )

        if self.game.in_gameday_mode and self.game.gameday_manager:
            gm = self.game.gameday_manager
            half = "T" if gm.is_top_inning else "B"
            line = f"{half}{gm.current_inning}  {gm.player_score}-{gm.opponent_score}"
        else:
            line = f"R {self.game.scoreKeeper.get_score()}"

        text = self.value_font.render(line, True, self.TEXT_COLOR)
        screen.blit(text, (x + 8, sy))
