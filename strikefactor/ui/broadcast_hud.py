import os

import pygame


class BroadcastHUD:
    """Four-corner broadcast-style HUD.

    Top-left:    B/S/O count (square indicators)
    Top-right:   inning + score
    Bottom-left: pitcher name + last pitch (speed/type)
    Bottom-right: bases diamond + on-base text

    Shares the monochrome palette with Scorebug and MinimalHUD."""

    SCREEN_W = 1280
    SCREEN_H = 720
    MARGIN = 16

    # Palette — strict black/white/gray.
    TEXT_COLOR = (240, 240, 240)
    LABEL_COLOR = (140, 140, 140)
    ON_COLOR = (240, 240, 240)
    OFF_COLOR = (60, 60, 60)
    OUTLINE_COLOR = (30, 30, 30)

    def __init__(self, game):
        self.game = game
        self.visible = True

        font_path = os.path.join(
            os.path.dirname(__file__), "font", "8bitoperator_jve.ttf"
        )
        self.tiny_font = pygame.font.Font(font_path, 12)
        self.label_font = pygame.font.Font(font_path, 14)
        self.value_font = pygame.font.Font(font_path, 18)
        self.big_font = pygame.font.Font(font_path, 26)

    def draw(self, screen):
        if not self.visible:
            return
        self._draw_count_top_left(screen)
        self._draw_score_top_right(screen)
        self._draw_pitcher_bottom_left(screen)
        self._draw_bases_bottom_right(screen)

    # --- top-left: B/S/O count ---------------------------------------------------

    def _draw_count_top_left(self, screen):
        x = self.MARGIN
        y = self.MARGIN
        sq = 9      # square size
        gap = 4     # gap between squares
        line_h = 18

        rows = (
            ("B", self.game.currentballs, 4),
            ("S", self.game.currentstrikes, 3),
            ("O", self.game.currentouts, 3),
        )
        for i, (label, value, total) in enumerate(rows):
            row_y = y + i * line_h
            label_surf = self.label_font.render(label, True, self.TEXT_COLOR)
            screen.blit(label_surf, (x, row_y))
            for j in range(total):
                rx = x + 18 + j * (sq + gap)
                ry = row_y + 3
                rect = pygame.Rect(rx, ry, sq, sq)
                if j < value:
                    pygame.draw.rect(screen, self.ON_COLOR, rect)
                else:
                    pygame.draw.rect(screen, self.OFF_COLOR, rect, 1)

    # --- top-right: inning + score ----------------------------------------------

    def _draw_score_top_right(self, screen):
        x_right = self.SCREEN_W - self.MARGIN
        y = self.MARGIN

        if self.game.in_gameday_mode and self.game.gameday_manager:
            gm = self.game.gameday_manager
            half = "TOP" if gm.is_top_inning else "BOT"
            opp_name = self._opponent_abbrev(gm)
            lines = [
                (f"{half} {gm.current_inning}", self.label_font, self.LABEL_COLOR),
                (f"YOU  {gm.player_score}", self.value_font, self.TEXT_COLOR),
                (f"{opp_name}  {gm.opponent_score}", self.value_font, self.TEXT_COLOR),
            ]
        else:
            lines = [
                ("RUNS", self.label_font, self.LABEL_COLOR),
                (f"{self.game.scoreKeeper.get_score()}", self.big_font, self.TEXT_COLOR),
            ]

        cy = y
        for text, font, color in lines:
            surf = font.render(text, True, color)
            screen.blit(surf, (x_right - surf.get_width(), cy))
            cy += surf.get_height() - 2

    def _opponent_abbrev(self, gameday_manager):
        # Try common attribute names; fall back to a generic label.
        for attr in ("opponent_abbrev", "opponent_short", "opponent_name", "opponent"):
            val = getattr(gameday_manager, attr, None)
            if isinstance(val, str) and val:
                return val[:3].upper()
        return "OPP"

    # --- bottom-left: pitcher + last pitch --------------------------------------

    def _draw_pitcher_bottom_left(self, screen):
        x = self.MARGIN
        y_bottom = self.SCREEN_H - self.MARGIN

        # Last pitch line (anchored at the bottom).
        sb = self.game.scorebug  # reuse the scorebug's stored last-pitch state
        if sb.last_pitch_type:
            last = f"{sb.last_pitch_speed:.1f} MPH  {sb.last_pitch_type}"
        else:
            last = "AWAITING PITCH"
        last_surf = self.label_font.render(last, True, self.LABEL_COLOR)

        # Pitcher name.
        full = (
            self.game.current_pitcher.name.upper()
            if self.game.current_pitcher
            else "---"
        )
        name = full.split()[-1] if full != "---" else full
        name_surf = self.big_font.render(name, True, self.TEXT_COLOR)

        # Small "PITCHER" header.
        header_surf = self.tiny_font.render("PITCHER", True, self.LABEL_COLOR)

        # Stack from bottom up.
        last_y = y_bottom - last_surf.get_height()
        name_y = last_y - name_surf.get_height() + 2
        header_y = name_y - header_surf.get_height() + 2

        screen.blit(header_surf, (x, header_y))
        screen.blit(name_surf, (x, name_y))
        screen.blit(last_surf, (x, last_y))

    # --- bottom-right: bases diamond + occupancy text ---------------------------

    def _draw_bases_bottom_right(self, screen):
        x_right = self.SCREEN_W - self.MARGIN
        y_bottom = self.SCREEN_H - self.MARGIN

        bases = self.game.scoreKeeper.get_bases()  # [1B, 2B, 3B]

        # Occupancy text along the bottom.
        names = ("1ST", "2ND", "3RD")
        occupied = [n for n, b in zip(names, bases) if b == "yellow"]
        on_str = "ON: " + ("  ·  ".join(occupied) if occupied else "---")
        on_surf = self.tiny_font.render(on_str, True, self.LABEL_COLOR)

        # Diamond geometry.
        radius = 16  # distance from center → each base
        size = 10    # half-diagonal of each base diamond

        # Layout: 2B at top, 1B right, 3B left of an invisible center.
        # Place center so the rightmost vertex sits a margin in from x_right,
        # and the bottom of the cluster sits just above the on_surf line.
        on_y = y_bottom - on_surf.get_height()
        cy = on_y - radius - size - 6
        cx = x_right - radius - size - 4

        positions = (
            (cx + radius, cy),       # 1B (right)
            (cx, cy - radius),       # 2B (top)
            (cx - radius, cy),       # 3B (left)
        )
        for i, (bx, by) in enumerate(positions):
            points = [
                (bx, by - size),
                (bx + size, by),
                (bx, by + size),
                (bx - size, by),
            ]
            if bases[i] == "yellow":
                pygame.draw.polygon(screen, self.ON_COLOR, points)
                pygame.draw.polygon(screen, self.OUTLINE_COLOR, points, 1)
            else:
                pygame.draw.polygon(screen, self.OFF_COLOR, points, 1)

        screen.blit(on_surf, (x_right - on_surf.get_width(), on_y))
