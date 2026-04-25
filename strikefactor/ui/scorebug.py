import pygame
import os


class Scorebug:
    """TV-style scorebug overlay rendered with pygame primitives."""

    # Layout constants
    BAR_Y = 678
    BAR_HEIGHT = 42
    BAR_WIDTH = 1280

    # Colors
    BG_COLOR = (15, 15, 25, 220)
    TEXT_COLOR = (220, 220, 220)
    LABEL_COLOR = (140, 140, 160)
    BALL_COLOR = (80, 220, 80)
    STRIKE_COLOR = (227, 75, 80)
    OUT_COLOR = (227, 75, 80)
    DOT_OFF_COLOR = (55, 55, 65)
    BASE_ON_COLOR = (255, 220, 50)
    BASE_OFF_COLOR = (70, 70, 80)
    DIVIDER_COLOR = (70, 70, 90)
    FLASH_COLOR = (40, 40, 55, 220)

    # Section X positions
    BASES_X = 12
    SCORE_X = 62
    PITCHER_X = 200
    COUNT_X = 345
    LAST_PITCH_X = 535
    SLASH_X = 790
    STATS_X = 1010

    def __init__(self, game):
        self.game = game
        self.visible = True

        # Load fonts
        font_path = os.path.join(os.path.dirname(__file__), 'font', '8bitoperator_jve.ttf')
        self.font = pygame.font.Font(font_path, 20)
        self.label_font = pygame.font.Font(font_path, 14)
        self.small_font = pygame.font.Font(font_path, 16)

        # Last pitch state
        self.last_pitch_type = ""
        self.last_pitch_speed = 0.0
        self.last_pitch_outcome = ""
        self._flash_timer = 0

        # Pre-render background surface
        self._bg_surface = pygame.Surface((self.BAR_WIDTH, self.BAR_HEIGHT), pygame.SRCALPHA)
        self._bg_surface.fill(self.BG_COLOR)

        # Flash background for last-pitch highlight
        self._flash_bg = pygame.Surface((240, self.BAR_HEIGHT), pygame.SRCALPHA)
        self._flash_bg.fill(self.FLASH_COLOR)

    def set_last_pitch(self, pitch_type: str, speed_mph: float, outcome: str):
        """Called after each pitch result to update last-pitch display."""
        self.last_pitch_type = pitch_type
        self.last_pitch_speed = speed_mph
        self.last_pitch_outcome = outcome
        self._flash_timer = 30  # ~0.5s at 60fps

    def draw(self, screen):
        """Draw the scorebug overlay."""
        if not self.visible:
            return

        y = self.BAR_Y
        y_center = y + self.BAR_HEIGHT // 2

        # Background bar
        screen.blit(self._bg_surface, (0, y))

        # Top divider line
        pygame.draw.line(screen, self.DIVIDER_COLOR, (0, y), (self.BAR_WIDTH, y), 2)

        # Draw each section with vertical dividers between them
        self._draw_bases(screen, y_center)
        self._draw_divider(screen, 55, y)
        self._draw_score(screen, y_center)
        self._draw_divider(screen, 192, y)
        self._draw_pitcher(screen, y_center)
        self._draw_divider(screen, 337, y)
        self._draw_count(screen, y_center)
        self._draw_divider(screen, 527, y)
        self._draw_last_pitch(screen, y, y_center)
        self._draw_divider(screen, 782, y)
        self._draw_triple_slash(screen, y_center)
        self._draw_divider(screen, 1002, y)
        self._draw_stats(screen, y_center)

        # Tick flash timer
        if self._flash_timer > 0:
            self._flash_timer -= 1

    def _draw_divider(self, screen, x, y):
        """Draw a thin vertical divider."""
        pygame.draw.line(screen, self.DIVIDER_COLOR, (x, y + 6), (x, y + self.BAR_HEIGHT - 6), 1)

    def _draw_bases(self, screen, y_center):
        """Draw compact diamond showing runner occupancy."""
        bases = self.game.scoreKeeper.get_bases()
        cx = self.BASES_X + 22
        cy = y_center + 3
        size = 7

        # Diamond positions: [1B, 2B, 3B] in data → visual: 2B top, 1B right, 3B left
        positions = [
            (cx + 12, cy),      # 1B (right)
            (cx, cy - 12),      # 2B (top)
            (cx - 12, cy),      # 3B (left)
        ]

        for i, (bx, by) in enumerate(positions):
            color = self.BASE_ON_COLOR if bases[i] == 'yellow' else self.BASE_OFF_COLOR
            points = [(bx, by - size), (bx + size, by), (bx, by + size), (bx - size, by)]
            pygame.draw.polygon(screen, color, points)
            pygame.draw.polygon(screen, (30, 30, 40), points, 1)

    def _draw_score(self, screen, y_center):
        """Draw score. GameDay shows both teams + inning, otherwise just runs."""
        x = self.SCORE_X

        if self.game.in_gameday_mode and self.game.gameday_manager:
            gm = self.game.gameday_manager
            inning = gm.current_inning
            half = "T" if gm.is_top_inning else "B"

            # Inning label
            inn_text = self.label_font.render(f"{half}{inning}", True, self.LABEL_COLOR)
            screen.blit(inn_text, (x, y_center - 18))

            # Scores
            # After inning ends, current inning runs are already folded into player_score
            # so only add scoreKeeper (current inning) when the inning is still active
            if self.game.inning_ended:
                player_total = gm.player_score
            else:
                player_total = gm.player_score + self.game.scoreKeeper.get_score()
            opp_text = self.small_font.render(f"OPP {gm.opponent_score}", True, self.TEXT_COLOR)
            you_text = self.small_font.render(f"YOU {player_total}", True, self.TEXT_COLOR)
            screen.blit(opp_text, (x, y_center - 4))
            screen.blit(you_text, (x + 65, y_center - 4))
        else:
            # Simple runs display
            label = self.label_font.render("RUNS", True, self.LABEL_COLOR)
            screen.blit(label, (x, y_center - 17))
            score = self.font.render(str(self.game.scoreKeeper.get_score()), True, self.TEXT_COLOR)
            screen.blit(score, (x, y_center + 1))

    def _draw_pitcher(self, screen, y_center):
        """Draw pitcher name."""
        x = self.PITCHER_X
        label = self.label_font.render("PITCHER", True, self.LABEL_COLOR)
        screen.blit(label, (x, y_center - 17))

        full_name = self.game.current_pitcher.name.upper() if self.game.current_pitcher else "---"
        # Use last name only to avoid overflow
        name = full_name.split()[-1] if full_name != "---" else full_name
        max_width = 130
        name_surf = self.font.render(name, True, self.TEXT_COLOR)
        if name_surf.get_width() > max_width:
            name_surf = name_surf.subsurface((0, 0, max_width, name_surf.get_height()))
        screen.blit(name_surf, (x, y_center + 1))

    def _draw_count(self, screen, y_center):
        """Draw BSO indicator dots."""
        x = self.COUNT_X
        balls = self.game.currentballs
        strikes = self.game.currentstrikes
        outs = self.game.currentouts

        dot_r = 5
        gap = 14

        # Balls row (top)
        row_y = y_center - 10
        b_label = self.label_font.render("B", True, self.LABEL_COLOR)
        screen.blit(b_label, (x, row_y - 7))
        for i in range(4):
            cx = x + 18 + i * gap
            color = self.BALL_COLOR if i < balls else self.DOT_OFF_COLOR
            pygame.draw.circle(screen, color, (cx, row_y), dot_r)

        # Strikes row (middle)
        row_y = y_center + 2
        s_label = self.label_font.render("S", True, self.LABEL_COLOR)
        screen.blit(s_label, (x, row_y - 7))
        for i in range(3):
            cx = x + 18 + i * gap
            color = self.STRIKE_COLOR if i < strikes else self.DOT_OFF_COLOR
            pygame.draw.circle(screen, color, (cx, row_y), dot_r)

        # Outs row (bottom)
        row_y = y_center + 14
        o_label = self.label_font.render("O", True, self.LABEL_COLOR)
        screen.blit(o_label, (x, row_y - 7))
        for i in range(3):
            cx = x + 18 + i * gap
            color = self.OUT_COLOR if i < outs else self.DOT_OFF_COLOR
            pygame.draw.circle(screen, color, (cx, row_y), dot_r)

        self._draw_challenge_pips(screen, x + 95, y_center)

    def _draw_challenge_pips(self, screen, x, y_center):
        """Draw remaining ABS challenge pips for the batting side."""
        cm = getattr(self.game, "challenge_manager", None)
        if cm is None:
            return

        sm = getattr(self.game, "settings_manager", None)
        if sm is not None and not sm.get_setting("abs_enabled"):
            return

        if self.game.in_gameday_mode and self.game.gameday_manager is not None:
            side = "away" if self.game.gameday_manager.is_top_inning else "home"
        else:
            side = "home"

        from config import ABS_PINK

        label = self.label_font.render("ABS", True, self.LABEL_COLOR)
        screen.blit(label, (x, y_center - 17))

        # Unlimited mode (sandbox): draw a single infinity symbol instead of pips.
        if cm.is_unlimited():
            inf_surf = self.font.render("∞", True, ABS_PINK)
            screen.blit(inf_surf, (x + 4, y_center - 8))
            return

        remaining = cm.remaining(side)
        per_side = cm.per_side
        diamond_size = 6
        gap = 18
        for i in range(per_side):
            cx = x + 6 + i * gap
            cy = y_center + 4
            points = [
                (cx, cy - diamond_size),
                (cx + diamond_size, cy),
                (cx, cy + diamond_size),
                (cx - diamond_size, cy),
            ]
            if i < remaining:
                pygame.draw.polygon(screen, ABS_PINK, points)
                pygame.draw.polygon(screen, (255, 255, 255), points, 1)
            else:
                pygame.draw.polygon(screen, self.DOT_OFF_COLOR, points, 1)

    def _draw_last_pitch(self, screen, y, y_center):
        """Draw last pitch type + speed + outcome with brief highlight."""
        x = self.LAST_PITCH_X

        # Flash highlight background
        if self._flash_timer > 0:
            alpha = int(220 * (self._flash_timer / 30))
            flash = pygame.Surface((245, self.BAR_HEIGHT), pygame.SRCALPHA)
            flash.fill((40, 50, 70, alpha))
            screen.blit(flash, (x - 5, y))

        if not self.last_pitch_type:
            # No pitch thrown yet
            placeholder = self.label_font.render("AWAITING PITCH", True, self.LABEL_COLOR)
            screen.blit(placeholder, (x, y_center - 7))
            return

        # Pitch type + speed on top line
        pitch_info = f"{self.last_pitch_type} {self.last_pitch_speed:.0f} MPH"
        info_surf = self.small_font.render(pitch_info, True, self.TEXT_COLOR)
        screen.blit(info_surf, (x, y_center - 15))

        # Outcome on bottom line
        outcome_surf = self.small_font.render(self.last_pitch_outcome, True, self.TEXT_COLOR)
        screen.blit(outcome_surf, (x, y_center + 3))

    def _draw_triple_slash(self, screen, y_center):
        """Draw AVG/OBP/SLG triple slash line."""
        x = self.SLASH_X
        label = self.label_font.render("AVG/OBP/SLG", True, self.LABEL_COLOR)
        screen.blit(label, (x, y_center - 17))

        slash = self.game.field_renderer.get_triple_slash_line()
        slash_surf = self.font.render(slash, True, self.TEXT_COLOR)
        screen.blit(slash_surf, (x, y_center + 1))

    def _draw_stats(self, screen, y_center):
        """Draw R/H/K/BB and OPS stat counts."""
        x = self.STATS_X

        runs = self.game.scoreKeeper.get_score()
        ops = self.game.field_renderer.get_ops()
        ops_str = f"{ops:.3f}" if ops < 1 else f"{ops:.3f}"

        stats_text = (
            f"R:{runs}  "
            f"H:{self.game.hits}  "
            f"K:{self.game.currentstrikeouts}  "
            f"BB:{self.game.currentwalks}  "
            f"OPS:{ops_str}"
        )
        label = self.label_font.render("STATS", True, self.LABEL_COLOR)
        screen.blit(label, (x, y_center - 17))
        stats_surf = self.font.render(stats_text, True, self.TEXT_COLOR)
        screen.blit(stats_surf, (x, y_center + 1))
