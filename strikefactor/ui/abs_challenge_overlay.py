import pygame

from config import (
    ABS_PINK,
    ABS_GREEN,
    ABS_ZONE,
    ABS_BALL_RADIUS,
    get_path,
)


_BALL_IMG = None
_BALL_IMG_PATH = "assets/images/abs/abs_ball.png"


def _get_ball_image():
    """Lazy-load the ABS ball sprite once pygame.display is initialized."""
    global _BALL_IMG
    if _BALL_IMG is None:
        _BALL_IMG = pygame.image.load(get_path(_BALL_IMG_PATH)).convert_alpha()
    return _BALL_IMG


# Animation phase boundaries (ms)
_PHASE_INTRO_END = 350      # ABS card slides in, panel fades up
_PHASE_REPLAY_END = 1900    # Ball animates from release to plate
_PHASE_ZOOM_END = 2500      # Camera zooms toward where ball crossed
_PHASE_BANNER_END = 3050    # CALL CONFIRMED / OVERTURNED banner appears
# After BANNER_END the overlay holds and waits for the player to dismiss.
_DISMISS_FADE_MS = 350      # Fade-out duration once dismissed

_DIM_ALPHA = 180

# Maximum camera zoom factor reached at _PHASE_ZOOM_END.
_MAX_ZOOM = 4.5


def _ease_out(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) * (1.0 - t)


def _ease_in_out(t: float) -> float:
    t = max(0.0, min(1.0, t))
    if t < 0.5:
        return 2 * t * t
    return 1 - (-2 * t + 2) ** 2 / 2


def _lerp(a, b, t):
    return a + (b - a) * t


def _draw_baseball(surface, center, radius):
    """Blit the ABS ball sprite scaled to the given radius."""
    r = max(3, int(radius))
    img = _get_ball_image()
    size = r * 2
    scaled = pygame.transform.smoothscale(img, (size, size))
    rect = scaled.get_rect(center=(int(center[0]), int(center[1])))
    surface.blit(scaled, rect)


class ABSChallengeOverlay:
    """MLB-style ABS challenge replay.

    Renders a pitchviz-style top-down strike zone with home plate set well
    below it, replays the pitch trajectory in flat 2D, then zooms toward where
    the ball crossed the plate before revealing whether the umpire's call
    stood.
    """

    PANEL_W = 720
    PANEL_H = 540

    # ------------------------------------------------------------------
    # Layout — mirrors PitchViz proportions (130x150 zone, plate centered
    # 60 px above the bottom, in a 600x520 visualization area).
    # We scale the same arrangement down by ~0.85 to fit the panel.
    VIEW_W = 510
    VIEW_H = 442
    ZONE_DRAW_W = 110
    ZONE_DRAW_H = 128                 # 110 * 150/130 ≈ 127, rounded
    PLATE_DRAW_W = ZONE_DRAW_W
    PLATE_DRAW_H = 22

    # Within VIEW: zone is centered, plate sits 50 px from the bottom,
    # leaving a ~100 px gap between zone bottom and plate top.
    _VIEW_ZONE_CX = VIEW_W // 2
    _VIEW_ZONE_CY = VIEW_H // 2
    _VIEW_PLATE_TOP = VIEW_H - 50

    # Internal scene is taller than the view so the upper portion of the
    # trajectory (release point, etc.) has somewhere to render before being
    # clipped by the visible window.
    _SCENE_TOP_PAD = 160
    SCENE_W = VIEW_W
    SCENE_H = VIEW_H + _SCENE_TOP_PAD

    _SCENE_ZONE_CX = _VIEW_ZONE_CX
    _SCENE_ZONE_CY = _VIEW_ZONE_CY + _SCENE_TOP_PAD
    _SCENE_PLATE_TOP = _VIEW_PLATE_TOP + _SCENE_TOP_PAD
    # ------------------------------------------------------------------

    def __init__(self, game):
        self.game = game
        self.screen_w = game.internal_width
        self.screen_h = game.internal_height

        self._active = False
        self._elapsed_ms = 0
        self._on_complete = None
        self._completed = False
        self._waiting_for_dismiss = False
        self._dismiss_started = False
        self._dismiss_elapsed = 0

        self._trajectory = []
        self._final_ball_xy = (0, 0)
        self._original_call = "ball"
        self._truth_strike = False
        self._overturned = False
        self._pre_balls = 0
        self._pre_strikes = 0
        self._pitch_label = ""
        self._post_count_label = "0-0"

        self._title_font = pygame.font.SysFont("arial", 26, bold=True)
        self._small_font = pygame.font.SysFont("arial", 14, bold=True)
        self._result_font = pygame.font.SysFont("arial", 20, bold=True)
        self._banner_font = pygame.font.SysFont("arial", 28, bold=True)
        self._count_font = pygame.font.SysFont("arial", 22, bold=True)
        self._hint_font = pygame.font.SysFont("arial", 12, bold=True)

    # ------------------------------------------------------------------

    def is_active(self) -> bool:
        return self._active

    def trigger(self, *, ball_xy, original_call: str, truth_strike: bool,
                trajectory, pre_balls: int, pre_strikes: int,
                pitch_label: str = "", post_count_label: str = "",
                on_complete=None) -> None:
        self._final_ball_xy = (float(ball_xy[0]), float(ball_xy[1]))
        self._original_call = original_call
        self._truth_strike = bool(truth_strike)
        truth_call = "strike" if truth_strike else "ball"
        self._overturned = (truth_call != original_call)
        self._trajectory = list(trajectory) if trajectory else []
        self._pre_balls = pre_balls
        self._pre_strikes = pre_strikes
        self._pitch_label = pitch_label
        self._post_count_label = post_count_label
        self._on_complete = on_complete
        self._completed = False
        self._elapsed_ms = 0
        self._waiting_for_dismiss = False
        self._dismiss_started = False
        self._dismiss_elapsed = 0
        self._active = True

    def dismiss(self) -> None:
        if self._waiting_for_dismiss and not self._dismiss_started:
            self._dismiss_started = True
            self._dismiss_elapsed = 0

    def is_waiting_for_dismiss(self) -> bool:
        return self._waiting_for_dismiss and not self._dismiss_started

    def update(self, dt_ms: int) -> None:
        if not self._active:
            return

        if self._dismiss_started:
            self._dismiss_elapsed += int(dt_ms)
            if self._dismiss_elapsed >= _DISMISS_FADE_MS and not self._completed:
                self._completed = True
                self._active = False
                cb = self._on_complete
                self._on_complete = None
                if cb is not None:
                    cb(self._overturned)
            return

        if self._waiting_for_dismiss:
            return

        self._elapsed_ms += int(dt_ms)
        if self._elapsed_ms >= _PHASE_BANNER_END:
            self._elapsed_ms = _PHASE_BANNER_END
            self._waiting_for_dismiss = True

    def render(self, surface) -> None:
        if not self._active:
            return

        t = self._elapsed_ms
        if self._dismiss_started:
            alpha_mult = 1.0 - _ease_out(min(1.0, self._dismiss_elapsed / _DISMISS_FADE_MS))
        else:
            alpha_mult = 1.0

        if t < _PHASE_INTRO_END:
            dim_alpha = int(_DIM_ALPHA * _ease_out(t / _PHASE_INTRO_END))
        else:
            dim_alpha = _DIM_ALPHA
        dim_alpha = int(dim_alpha * alpha_mult)

        if dim_alpha > 0:
            dim = pygame.Surface((self.screen_w, self.screen_h), pygame.SRCALPHA)
            dim.fill((0, 0, 0, dim_alpha))
            surface.blit(dim, (0, 0))

        self._draw_panel(surface, t, alpha_mult)

        if t >= _PHASE_ZOOM_END:
            self._draw_result_banner(surface, t, alpha_mult)

        if self._waiting_for_dismiss and not self._dismiss_started:
            self._draw_continue_hint(surface)

    def _draw_continue_hint(self, surface):
        font = self._hint_font
        text_str = "PRESS  SPACE  TO  CONTINUE"
        text = font.render(text_str, True, (220, 220, 230))

        pulse = (pygame.time.get_ticks() // 30) % 60
        text.set_alpha(180 + int(60 * abs(30 - pulse) / 30))

        pad_x, pad_y = 14, 6
        pill_w = text.get_width() + pad_x * 2
        pill_h = text.get_height() + pad_y * 2
        x = (self.screen_w - pill_w) // 2
        y = self.screen_h - 16 - pill_h

        pill = pygame.Surface((pill_w, pill_h), pygame.SRCALPHA)
        pygame.draw.rect(pill, (12, 16, 24, 210), (0, 0, pill_w, pill_h),
                         border_radius=pill_h // 2)
        pygame.draw.rect(pill, (*ABS_PINK, 170), (0, 0, pill_w, pill_h),
                         width=1, border_radius=pill_h // 2)
        pill.blit(text, (pad_x, pad_y))
        surface.blit(pill, (x, y))

    # ------------------------------------------------------------------

    def _draw_panel(self, surface, t, alpha_mult=1.0):
        intro_t = _ease_out(min(1.0, t / _PHASE_INTRO_END))

        panel_x = (self.screen_w - self.PANEL_W) // 2
        target_y = (self.screen_h - self.PANEL_H) // 2 - 40
        panel_y = int(_lerp(target_y - 60, target_y, intro_t))

        panel_alpha = int(235 * intro_t * alpha_mult)

        panel = pygame.Surface((self.PANEL_W, self.PANEL_H), pygame.SRCALPHA)
        pygame.draw.rect(panel, (18, 22, 32, panel_alpha),
                         (0, 0, self.PANEL_W, self.PANEL_H), border_radius=14)
        pygame.draw.rect(panel, (*ABS_PINK, panel_alpha),
                         (0, 0, self.PANEL_W, self.PANEL_H), width=3, border_radius=14)

        # Pink title strip
        strip_h = 56
        pygame.draw.rect(panel, (*ABS_PINK, panel_alpha),
                         (0, 0, self.PANEL_W, strip_h),
                         border_top_left_radius=14, border_top_right_radius=14)

        title = self._title_font.render("ABS  REVIEW", True, (255, 255, 255))
        title.set_alpha(panel_alpha)
        panel.blit(title, (24, (strip_h - title.get_height()) // 2))

        if self._pitch_label:
            sub = self._small_font.render(self._pitch_label.upper(), True, (255, 240, 245))
            sub.set_alpha(panel_alpha)
            panel.blit(sub, (self.PANEL_W - sub.get_width() - 24,
                             (strip_h - sub.get_height()) // 2))

        # Result indicator card on the right, just below the strip
        ind_w, ind_h = 130, 36
        ind_x = self.PANEL_W - ind_w - 24
        ind_y = strip_h + 12
        if t >= _PHASE_REPLAY_END:
            self._draw_result_card(panel, ind_x, ind_y, ind_w, ind_h, panel_alpha)

        # Strike zone view, centered in the remaining panel area.
        view_top = strip_h + 14
        view_bottom = self.PANEL_H - 14
        view_cx = self.PANEL_W // 2
        view_cy = (view_top + view_bottom) // 2
        self._draw_zone_view(panel, view_cx, view_cy, t, panel_alpha)

        surface.blit(panel, (panel_x, panel_y))

    def _draw_result_card(self, panel, x, y, w, h, alpha):
        truth_label = "STRIKE" if self._truth_strike else "BALL"
        dot_color = ABS_PINK if self._truth_strike else ABS_GREEN
        pygame.draw.rect(panel, (250, 250, 250, alpha), (x, y, w, h), border_radius=8)
        pygame.draw.rect(panel, (*dot_color, alpha), (x, y, w, h), width=2, border_radius=8)
        pygame.draw.circle(panel, (*dot_color, alpha), (x + 16, y + h // 2), 7)
        label_surf = self._result_font.render(truth_label, True, (40, 40, 40))
        label_surf.set_alpha(alpha)
        panel.blit(label_surf, (x + 32, y + (h - label_surf.get_height()) // 2))

    # ------------------------------------------------------------------
    # Zone view: pitchviz-style scene rendered to a scratch surface, then a
    # (possibly zoomed) sub-region is blit into the panel.

    def _draw_zone_view(self, panel, view_cx, view_cy, t, alpha):
        scene = pygame.Surface((self.SCENE_W, self.SCENE_H), pygame.SRCALPHA)

        zone_rect = pygame.Rect(0, 0, self.ZONE_DRAW_W, self.ZONE_DRAW_H)
        zone_rect.center = (self._SCENE_ZONE_CX, self._SCENE_ZONE_CY)

        # Strike zone outline is rendered post-smoothscale (see below) so the
        # boundary stays a crisp 1-px line at any zoom — that way the visual
        # edge matches the actual collision rectangle exactly.

        # Home plate: same width as the zone, well below it (matches PitchViz)
        plate_top = self._SCENE_PLATE_TOP
        plate_left = self._SCENE_ZONE_CX - self.PLATE_DRAW_W // 2
        plate_w = self.PLATE_DRAW_W
        plate_lip = max(6, self.PLATE_DRAW_H // 3)
        pygame.draw.polygon(scene, (255, 255, 255, alpha), [
            (plate_left, plate_top),
            (plate_left + plate_w, plate_top),
            (plate_left + plate_w, plate_top + plate_lip),
            (self._SCENE_ZONE_CX, plate_top + self.PLATE_DRAW_H),
            (plate_left, plate_top + plate_lip),
        ])

        # Trail dots only — the ball itself is drawn after the smoothscale so
        # the pixel-art seams stay crisp at high zoom factors. The trail
        # fades out as the camera starts zooming so the close-up frame is
        # just the ball and the zone.
        if t >= _PHASE_INTRO_END:
            if t < _PHASE_REPLAY_END:
                trail_fade = 1.0
            else:
                fade_dur = max(1, (_PHASE_ZOOM_END - _PHASE_REPLAY_END) // 2)
                trail_fade = max(0.0, 1.0 - (t - _PHASE_REPLAY_END) / fade_dur)
            if trail_fade > 0:
                self._draw_trail(scene, zone_rect, t - _PHASE_INTRO_END,
                                 int(alpha * trail_fade))

        # ----- Camera (zoom in toward the ball after the replay finishes) ----
        zoom = 1.0
        if t >= _PHASE_REPLAY_END:
            zoom_t = _ease_in_out(min(1.0, (t - _PHASE_REPLAY_END) /
                                          max(1, _PHASE_ZOOM_END - _PHASE_REPLAY_END)))
            zoom = _lerp(1.0, _MAX_ZOOM, zoom_t)

        final_sx, final_sy = self._scene_pos_for_final(zone_rect)
        cur_sx, cur_sy = self._current_ball_scene_pos(zone_rect, t - _PHASE_INTRO_END)

        # Default crop centers on the visible portion of the scene so the
        # arrangement of zone + plate appears identical to PitchViz at zoom=1.
        default_cx = self.SCENE_W / 2
        default_cy = self._SCENE_TOP_PAD + self.VIEW_H / 2

        pan_t = (zoom - 1.0) / max(0.0001, _MAX_ZOOM - 1.0)
        target_cx = _lerp(default_cx, final_sx, pan_t)
        target_cy = _lerp(default_cy, final_sy, pan_t)

        crop_w = max(2, self.VIEW_W / zoom)
        crop_h = max(2, self.VIEW_H / zoom)
        crop_x = max(0, min(self.SCENE_W - crop_w, target_cx - crop_w / 2))
        crop_y = max(0, min(self.SCENE_H - crop_h, target_cy - crop_h / 2))

        crop_rect = pygame.Rect(int(crop_x), int(crop_y),
                                int(crop_w), int(crop_h))
        cropped = scene.subsurface(crop_rect).copy()
        scaled = pygame.transform.smoothscale(cropped, (self.VIEW_W, self.VIEW_H))

        scale_x = self.VIEW_W / crop_w
        scale_y = self.VIEW_H / crop_h

        # Crisp strike-zone outline drawn post-scale, so the visible boundary
        # is a sharp 1-px line that exactly matches the collision rectangle.
        zv_rect = pygame.Rect(
            int(round((zone_rect.left - crop_x) * scale_x)),
            int(round((zone_rect.top - crop_y) * scale_y)),
            int(round(zone_rect.width * scale_x)),
            int(round(zone_rect.height * scale_y)),
        )
        pygame.draw.rect(scaled, (255, 255, 255, alpha), zv_rect, width=2)

        # Now render the ball (and any overlap highlight) directly onto the
        # scaled view so it stays pixel-sharp regardless of the zoom factor.
        if t >= _PHASE_INTRO_END:
            ball_vx = (cur_sx - crop_x) * scale_x
            ball_vy = (cur_sy - crop_y) * scale_y

            # Collision radius in scene coords → view coords.
            ball_r_scene = ABS_BALL_RADIUS * self.ZONE_DRAW_W / ABS_ZONE[2]
            ball_r_view = max(4, int(round(ball_r_scene * scale_x)))

            _draw_baseball(scaled, (ball_vx, ball_vy), ball_r_view)

            # Pink halo only when the ball actually overlapped the zone — i.e.
            # the truth is a strike. Balls show no halo since nothing touched.
            if t >= _PHASE_REPLAY_END and self._truth_strike:
                self._draw_zone_overlap_highlight(
                    scaled, zone_rect, crop_x, crop_y, scale_x, scale_y,
                    ball_vx, ball_vy, ball_r_view, alpha)

        panel.blit(scaled, (view_cx - self.VIEW_W // 2, view_cy - self.VIEW_H // 2))

    def _draw_zone_overlap_highlight(self, scaled, zone_rect,
                                     crop_x, crop_y, scale_x, scale_y,
                                     ball_vx, ball_vy, ball_r_view, alpha):
        """Pink halo on the ball's outline, clipped so it only renders inside
        the strike-zone rectangle. This makes ball/zone contact unambiguous
        right at the boundary."""
        zv_x = (zone_rect.left - crop_x) * scale_x
        zv_y = (zone_rect.top - crop_y) * scale_y
        zv_w = zone_rect.width * scale_x
        zv_h = zone_rect.height * scale_y
        zv_rect = pygame.Rect(int(round(zv_x)), int(round(zv_y)),
                              int(round(zv_w)), int(round(zv_h)))
        zv_rect = zv_rect.clip(scaled.get_rect())
        if zv_rect.width <= 0 or zv_rect.height <= 0:
            return

        old_clip = scaled.get_clip()
        scaled.set_clip(zv_rect)

        cx = int(round(ball_vx))
        cy = int(round(ball_vy))
        thick = max(1, ball_r_view // 10)

        # Soft outer glow: a few concentric rings stepping outward with
        # decreasing alpha to fake a blurred halo. pygame.draw.circle's width
        # extends inward from the given radius, so each ring is a thin
        # annulus just outside the previous one. Kept slim so the ball outline
        # underneath stays readable.
        glow_steps = (
            (ball_r_view + thick + 4, 1, 0.18),
            (ball_r_view + thick + 2, 1, 0.32),
            (ball_r_view + thick + 1, 1, 0.55),
        )
        for ring_r, ring_w, a_factor in glow_steps:
            ring_alpha = int(alpha * a_factor)
            if ring_alpha <= 0:
                continue
            pygame.draw.circle(scaled, (*ABS_PINK, ring_alpha),
                               (cx, cy), ring_r, ring_w)

        # Solid core ring straddling the ball outline so the pink reads as
        # contact with the zone edge, not just an outer glow.
        core_r = ball_r_view + thick // 2
        pygame.draw.circle(scaled, (*ABS_PINK, alpha),
                           (cx, cy), core_r, thick)

        scaled.set_clip(old_clip)

    def _scene_pos_for_final(self, zone_rect):
        """Final ball position (game coords → scene coords)."""
        zx, zy, zw, zh = ABS_ZONE
        sx = zone_rect.width / zw
        sy = zone_rect.height / zh
        entry = self._trajectory[-1] if self._trajectory else None
        if entry and len(entry) >= 2:
            gx, gy = entry[0], entry[1]
        else:
            gx, gy = self._final_ball_xy
        return (zone_rect.centerx + (gx - zx) * sx,
                zone_rect.centery + (gy - zy) * sy)

    def _current_ball_scene_pos(self, zone_rect, anim_t):
        """Ball position (in scene coords) at the given animation time."""
        if not self._trajectory:
            return self._scene_pos_for_final(zone_rect)

        replay_progress = min(1.0, anim_t / max(1, _PHASE_REPLAY_END - _PHASE_INTRO_END))
        n = len(self._trajectory)
        cutoff = max(1, int(n * replay_progress))

        zx, zy, zw, zh = ABS_ZONE
        sx = zone_rect.width / zw
        sy = zone_rect.height / zh
        entry = self._trajectory[cutoff - 1]
        if not entry or len(entry) < 2:
            return self._scene_pos_for_final(zone_rect)
        return (zone_rect.centerx + (entry[0] - zx) * sx,
                zone_rect.centery + (entry[1] - zy) * sy)

    def _draw_trail(self, scene, zone_rect, anim_t, alpha):
        """White trail dots leading up to (but not including) the current
        ball position. The ball itself is drawn separately on the scaled
        view so it stays crisp at high zoom."""
        if not self._trajectory:
            return

        replay_progress = min(1.0, anim_t / max(1, _PHASE_REPLAY_END - _PHASE_INTRO_END))
        n = len(self._trajectory)
        cutoff = max(1, int(n * replay_progress))

        zx, zy, zw, zh = ABS_ZONE
        sx = zone_rect.width / zw
        sy = zone_rect.height / zh

        for i in range(cutoff - 1):
            entry = self._trajectory[i]
            if not entry or len(entry) < 2:
                continue
            px = int(zone_rect.centerx + (entry[0] - zx) * sx)
            py = int(zone_rect.centery + (entry[1] - zy) * sy)
            age_t = i / max(1, cutoff - 1)
            trail_alpha = int(_lerp(50, 200, age_t)) * alpha // 255
            radius = max(2, int(_lerp(2, 4, age_t)))
            if trail_alpha > 0:
                pygame.draw.circle(scene, (255, 255, 255, trail_alpha),
                                   (px, py), radius)

    # ------------------------------------------------------------------

    def _draw_result_banner(self, surface, t, alpha_mult=1.0):
        banner_w = 520
        banner_h = 70
        target_y = self.screen_h - banner_h - 60
        slide_t = _ease_out(min(1.0, (t - _PHASE_ZOOM_END) /
                                max(1, _PHASE_BANNER_END - _PHASE_ZOOM_END)))
        banner_y = int(_lerp(self.screen_h + 10, target_y, slide_t))
        banner_x = (self.screen_w - banner_w) // 2

        alpha = int(255 * alpha_mult)

        accent = ABS_GREEN if self._overturned else ABS_PINK
        banner = pygame.Surface((banner_w, banner_h), pygame.SRCALPHA)
        pygame.draw.rect(banner, (18, 22, 32, alpha),
                         (0, 0, banner_w, banner_h), border_radius=12)
        pygame.draw.rect(banner, (*accent, alpha),
                         (0, 0, banner_w, banner_h), width=3, border_radius=12)

        if self._overturned:
            new_call = "STRIKE" if self._truth_strike else "BALL"
            label = f"CALL OVERTURNED  →  {new_call}"
        else:
            label = "CALL CONFIRMED"
        label_surf = self._banner_font.render(label, True, (245, 245, 250))
        label_surf.set_alpha(alpha)
        banner.blit(label_surf, (24, (banner_h - label_surf.get_height()) // 2))

        if self._post_count_label:
            count_surf = self._count_font.render(self._post_count_label, True, accent)
            count_surf.set_alpha(alpha)
            banner.blit(count_surf, (banner_w - count_surf.get_width() - 24,
                                     (banner_h - count_surf.get_height()) // 2))

        surface.blit(banner, (banner_x, banner_y))
