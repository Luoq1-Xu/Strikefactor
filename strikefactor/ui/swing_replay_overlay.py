"""Slow-motion replay of the last swing: bat path, contact point, timing.

The game tells a player *what* happened to a swing and never *why*. The three
facts that decided it — when the bat arrived, where it was, and where the ball
was at that instant — were each computed for one frame and discarded. This
draws them.

Structure follows `ABSChallengeOverlay`: an instance built once on `Game`, a
keyword-only `trigger()`, a phase machine on cumulative millisecond
boundaries, and `is_active()` driving a nested render loop in `main.py` that
supplies the pause. It deliberately does *not* follow that overlay's
typography — the ABS card is the one screen in the UI that uses
`SysFont("arial")` and its own pink palette, which makes it the exception
rather than the pattern. Everything here is `gameday_theme`.

**Two views, one source.** SIDE looks down the world x axis, so the horizontal
screen axis is `y` (feet from the plate) and the timing error appears as
literal horizontal separation between barrel and ball — that is the whole
reason this view exists. OVERHEAD looks down z and shows the barrel sweeping
across the plate, which is where pull-versus-oppo contact reads. Both project
from the same world-feet models, so they cannot tell different stories.

**Both views are seen from a real place, and both used to be mirror images of
it.** The world's `+x` is the third-base side (`pivot_ft("R")` is at `+1.53`,
and a right-hander stands at third). A camera on that line sees the pitcher on
its *left* and the catcher on its right, and a camera above the field sees
third base on the left — which is why `_project` negates. Drawn the other way
the SIDE view was a first-base camera captioned as a third-base one, and the
OVERHEAD view put `+x` on the right under a label reading `<- 3B`, i.e. a bird's
eye from underneath the infield. Nothing about a swing is symmetric, so a
mirrored replay quietly reverses which way the batter is turning.

**The projections are deliberately separate from the game's camera.** The
`UmpireCamera` is a perspective projection from behind the plate; a bat path
seen from there sweeps almost entirely toward the viewer, which is exactly the
axis the analysis is about. These are plain orthographic feet-to-pixel maps
with their own scales, and the conversion happens in one place per view
(`_project`) so no drawing code ever handles a raw pixel scale.

**The ball is drawn unclamped.** The engine tests contact against a ball frozen
at the plate (see `swing_record`), but the pitch model keeps describing a real
ball for the few feet past it, and on a late swing that extrapolation *is* the
finding. Drawing the clamped ball would show every late swing meeting the ball
exactly at the plate, which is the one thing that cannot have happened.
"""


import math

import pygame

from strikefactor.gameplay import bat_path
from strikefactor.ui import gameday_theme as gdt

# --- Phases, cumulative ms ---------------------------------------------------
_PHASE_INTRO_END = 420      # panel fades up, pitch card slides in
_PHASE_REPLAY_END = 2600    # the swing, in slow motion
_PHASE_FREEZE_END = 3100    # held at contact, ghost bat fades in
_DISMISS_FADE_MS = 260

_DIM_ALPHA = 225

# How much of the pitch to replay. The whole flight is ~0.4 s and the bat is
# only present for the last 0.15, so starting at release would spend most of
# the replay on an empty screen. Never shorter than the swing itself, or the
# bat would pop into existence already mid-arc.
_REPLAY_LEAD_S = bat_path.SWING_DURATION_S + 0.03
# The replay ends *at* bat arrival, with no tail. A tail looks like it should
# be free — let the ball carry on past the barrel for a moment — but the
# freeze is the whole payoff, and at 93 mph even 60 ms of tail drags the ball
# eight feet past the contact marker, so the frame the player studies shows
# the bat and the ball in different places.
_REPLAY_TAIL_S = 0.0

_VIEW_SIDE = 0
_VIEW_OVERHEAD = 1
_VIEW_LABELS = ["SIDE", "OVERHEAD"]

# --- Field of view, in feet --------------------------------------------------
# Depth is framed per swing (see `_ranges`) rather than fixed: contact ranges
# from about 11 ft out front on a badly early swing to 11 ft deep on a late
# one, and any single window wide enough for both squeezes the ordinary swing
# into the middle sixth of the view.
_SIDE_Z_RANGE = (0.0, 7.5)   # the loaded barrel tip sits at ~7 ft
_OVER_X_RANGE = (-5.5, 5.5)
_DEPTH_MARGIN_FT = 4.0
_MIN_DEPTH_RANGE = (-5.0, 9.0)

_STRIKE_ZONE_Z = (1.5, 3.5)
_STRIKE_ZONE_X = (-0.708, 0.708)   # 17 in

_TRAIL_LEN = 26
_BAT_TRACK_LEN = 18

# --- The shape of a bat ------------------------------------------------------
# Drawn as a line, a bat is a line. It is drawn instead as a *swept sphere of
# varying radius*, which is what a bat is — and which gives the rounded end cap
# and the knob flare for free rather than as two special cases — sampled from
# this profile: fraction of the way from the knob to the tip, against the real
# radius there in inches. An MLB bat is 2.61 in across the barrel and under an
# inch through the handle, and that taper is essentially the whole of why a bat
# is recognisable in silhouette.
#
# Radii are stated in **inches and scaled**, never set as a pixel width: each
# view frames a different number of feet and reframes depth per swing, so one
# pixel width is a different real bat in each view. See `_bat_scale` for why
# thickness takes a single scale where position and length take the honest
# anisotropic projection.
#
# The stations are placed to keep the taper **concave**, which is the shape's
# whole signature: a thin handle held most of the way, a quick flare, and a
# barrel that is then very nearly parallel-sided. Spread the same radii evenly
# and the flare straightens into a cone, which is what a traffic bollard looks
# like.
_BAT_PROFILE_IN = (
    (0.00, 1.05),   # knob, ~2.1 in across
    (0.02, 1.05),
    (0.05, 0.48),   # handle, a shade under 1 in and held to a third of the way
    (0.36, 0.50),
    (0.45, 0.58),   # into the taper
    (0.52, 0.72),
    (0.60, 0.94),
    (0.67, 1.13),
    (0.73, 1.24),
    (0.80, 1.29),   # barrel, 2.6 in across — the MLB maximum
    (1.00, 1.30),
)
# Below this the bat has no drawable length to taper along and is rendered as
# its two end caps. Ordinary rather than exceptional: the SIDE view looks down
# the x axis and a bat at contact points largely along it.
_BAT_END_ON_PX = 2.0


def _ease_out(t):
    return 1.0 - (1.0 - t) ** 3


def _lerp(a, b, t):
    return a + (b - a) * t


class SwingReplayOverlay:
    """Phased slow-motion replay of a `SwingRecord`."""

    PANEL_W = 1120
    PANEL_H = 640
    VIEW_H = 340

    def __init__(self, game):
        self.game = game
        self.screen_w = game.internal_width
        self.screen_h = game.internal_height

        self._active = False
        self._completed = False
        self._elapsed_ms = 0
        self._dismiss_started = False
        self._dismiss_elapsed = 0

        self._record = None
        self._swing = None
        self._ghost = None
        self._view = _VIEW_SIDE
        self._paused = False
        self._chip_hits = []

        self._fonts = None

    # -- lifecycle --------------------------------------------------------

    def _f(self):
        if self._fonts is None:
            self._fonts = gdt.load_fonts()
        return self._fonts

    def is_active(self):
        return self._active

    def trigger(self, *, record):
        """Open the replay on `record`. Builds both bats once, up front."""
        self._record = record
        self._swing = record.bat_swing()
        self._ghost = record.perfect_swing()
        self._elapsed_ms = 0
        self._dismiss_started = False
        self._dismiss_elapsed = 0
        self._completed = False
        self._paused = False
        self._active = True

    def dismiss(self):
        if self._active and not self._dismiss_started:
            self._dismiss_started = True

    def update(self, dt_ms):
        if not self._active:
            return
        if self._dismiss_started:
            self._dismiss_elapsed += int(dt_ms)
            if self._dismiss_elapsed >= _DISMISS_FADE_MS and not self._completed:
                self._completed = True
                self._active = False
            return
        if self._paused:
            return
        self._elapsed_ms = min(_PHASE_FREEZE_END, self._elapsed_ms + int(dt_ms))

    def handle_event(self, event):
        """Scrub, toggle view, close. Returns True if the event was consumed."""
        if not self._active or self._dismiss_started:
            return False

        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_KP_ENTER):
                self.dismiss()
                return True
            if event.key == pygame.K_SPACE:
                # Replaying from the end rather than resuming a finished clip,
                # which is the only sensible reading of "play" once the
                # animation has already landed on the freeze.
                if self._elapsed_ms >= _PHASE_FREEZE_END:
                    self._elapsed_ms = _PHASE_INTRO_END
                    self._paused = False
                else:
                    self._paused = not self._paused
                return True
            if event.key == pygame.K_TAB:
                self._view = 1 - self._view
                return True
            if event.key in (pygame.K_LEFT, pygame.K_RIGHT):
                self._step(-1 if event.key == pygame.K_LEFT else 1)
                return True
        elif event.type == pygame.MOUSEBUTTONDOWN:
            for rect, index in self._chip_hits:
                if rect.collidepoint(event.pos):
                    self._view = index
                    return True
            self.dismiss()
            return True
        return False

    def _step(self, direction):
        """Scrub one frame of the replay. Pauses, since scrubbing implies it."""
        self._paused = True
        span = _PHASE_REPLAY_END - _PHASE_INTRO_END
        self._elapsed_ms = max(_PHASE_INTRO_END,
                               min(_PHASE_FREEZE_END,
                                   self._elapsed_ms + direction * span // 40))

    # -- the replay clock -------------------------------------------------

    def _replay_progress(self):
        """0 at the start of the shown window, 1 at the freeze."""
        if self._elapsed_ms <= _PHASE_INTRO_END:
            return 0.0
        span = max(1, _PHASE_REPLAY_END - _PHASE_INTRO_END)
        return min(1.0, (self._elapsed_ms - _PHASE_INTRO_END) / span)

    def _window_s(self):
        """(start, end) of the replayed slice of the pitch, in seconds."""
        arrival = self._record.bat_arrival_s
        return arrival - _REPLAY_LEAD_S, arrival + _REPLAY_TAIL_S

    def _now_s(self):
        """Where the replay clock currently sits, in pitch seconds."""
        start, end = self._window_s()
        return _lerp(start, end, self._replay_progress())

    def _swing_t(self, now_s):
        """Where the barrel is, in swing seconds. Clamped at both ends."""
        launch = self._record.bat_arrival_s - bat_path.SWING_DURATION_S
        return max(0.0, min(bat_path.SWING_DURATION_S, now_s - launch))

    # -- projection -------------------------------------------------------

    def _view_rect(self):
        panel = self._panel_rect()
        return pygame.Rect(panel.x + 24, panel.y + 76, panel.width - 48, self.VIEW_H)

    def _depth_range(self):
        """The framed slice of depth, in feet, for this swing.

        Always contains the plate and the contact point with room to spare,
        whichever side of the plate contact happened on.
        """
        depth = self._record.contact_depth_ft
        return (min(_MIN_DEPTH_RANGE[0], depth - _DEPTH_MARGIN_FT),
                max(_MIN_DEPTH_RANGE[1], depth + _DEPTH_MARGIN_FT))

    def _project(self, point_ft):
        """World feet to screen pixels for the active view.

        The single crossing from feet to pixels. Both views are orthographic,
        both flip their vertical axis since screen y grows downward while every
        world quantity here grows up or out, and both negate their horizontal
        one so the camera stands where its label says it does — see the note on
        mirroring at the top of the module.
        """
        rect = self._view_rect()
        x_ft, y_ft, z_ft = point_ft
        if self._view == _VIEW_SIDE:
            # From the third-base line: the pitcher (+y) is to the left.
            lo, hi = self._depth_range()
            h_lo, h_hi = -hi, -lo
            v_lo, v_hi = _SIDE_Z_RANGE
            h, v = -y_ft, z_ft
        else:
            # From above: third base (+x) is to the left, the pitcher is up.
            h_lo, h_hi = -_OVER_X_RANGE[1], -_OVER_X_RANGE[0]
            v_lo, v_hi = self._depth_range()
            h, v = -x_ft, y_ft
        px = rect.x + (h - h_lo) / (h_hi - h_lo) * rect.width
        py = rect.bottom - (v - v_lo) / (v_hi - v_lo) * rect.height
        return (px, py)

    def _px_per_ft(self):
        """Pixels per foot along each screen axis, for the active view.

        Two numbers and never one. Both views scale their axes independently
        and the depth axis is reframed per swing, so ~76 px/ft across can sit
        against ~45 px/ft down in the same picture — which is why anything
        drawn with a real thickness has to ask for both.
        """
        rect = self._view_rect()
        lo, hi = self._depth_range()
        if self._view == _VIEW_SIDE:
            return (rect.width / (hi - lo),
                    rect.height / (_SIDE_Z_RANGE[1] - _SIDE_Z_RANGE[0]))
        return (rect.width / (_OVER_X_RANGE[1] - _OVER_X_RANGE[0]),
                rect.height / (hi - lo))

    def _bat_scale(self):
        """Pixels per foot for the bat's *thickness* — one number, not two.

        Position and length are projected exactly, like everything else here.
        Thickness deliberately is not, because these views squash their two
        axes against each other by as much as 4:1 as a framing choice: the
        OVERHEAD picture fits 14 ft of depth into a rect three times wider
        than it is tall. Projected honestly, a bat lying across that view
        collapses to a five-pixel needle and the taper that makes it read as
        a bat goes with it. One scale also keeps the bat one shape as it
        turns, instead of fattening and thinning through the swing.

        This is the call the ball already makes and has since the first
        draft — drawn at a flat 5 px rather than as the ellipse its real 2.9
        in would project to. What separates the two cases from
        `hit_animation._ft_dist` is that nobody measures a bat's diameter off
        this diagram; the thickness is what makes the object recognisable,
        not a quantity being reported.
        """
        sx, sy = self._px_per_ft()
        return math.sqrt(sx * sy)

    def _bat_silhouette(self, state):
        """The bat's outline in screen pixels, as `(polygon, caps)`.

        The polygon is the tapered body; `caps` are the two swept-sphere ends
        as `(centre, radius_px)`. Cap centres are inset from the projected
        ends by their own radii, so the drawn silhouette spans exactly the
        bat's projected length — a bat that grew by its own end caps each
        time it was drawn would be a quiet lie about the one length the
        collision geometry is pinned to.

        `polygon` is None when the bat is near enough to end-on that it has
        no length to taper along and the insets would cross over. That is an
        ordinary thing to be looking at rather than an error: the SIDE view
        looks down the x axis and a bat at contact points largely along it,
        so the two caps *are* what it looks like.
        """
        knob = self._project(state.knob_ft)
        tip = self._project(state.barrel_ft)
        scale = self._bat_scale()
        dx, dy = tip[0] - knob[0], tip[1] - knob[1]
        span = math.hypot(dx, dy)

        r_knob = _BAT_PROFILE_IN[0][1] / 12.0 * scale
        r_tip = _BAT_PROFILE_IN[-1][1] / 12.0 * scale
        if span < r_knob + r_tip + _BAT_END_ON_PX:
            return None, ((knob, r_knob), (tip, r_tip))

        # Inset in *screen* space, so the caps land exactly on the projected
        # ends however foreshortened the bat is.
        ux, uy = dx / span, dy / span
        lo = (knob[0] + ux * r_knob, knob[1] + uy * r_knob)
        hi = (tip[0] - ux * r_tip, tip[1] - uy * r_tip)
        nx, ny = -uy, ux

        near, far = [], []
        for frac, radius_in in _BAT_PROFILE_IN:
            cx = lo[0] + (hi[0] - lo[0]) * frac
            cy = lo[1] + (hi[1] - lo[1]) * frac
            half = radius_in / 12.0 * scale
            near.append((cx + nx * half, cy + ny * half))
            far.append((cx - nx * half, cy - ny * half))
        return near + far[::-1], ((lo, r_knob), (hi, r_tip))

    # -- render -----------------------------------------------------------

    def render(self, surface):
        if not self._active or self._record is None:
            return

        alpha = 1.0
        if self._dismiss_started:
            alpha = 1.0 - _ease_out(min(1.0, self._dismiss_elapsed / _DISMISS_FADE_MS))

        intro = min(1.0, self._elapsed_ms / _PHASE_INTRO_END)
        dim = pygame.Surface((self.screen_w, self.screen_h), pygame.SRCALPHA)
        dim.fill((0, 0, 0, int(_DIM_ALPHA * _ease_out(intro) * alpha)))
        surface.blit(dim, (0, 0))

        if alpha <= 0.01:
            return

        panel = self._panel_rect()
        pygame.draw.rect(surface, gdt.BG, panel)
        pygame.draw.rect(surface, gdt.DIVIDER, panel, 1)

        fonts = self._f()
        gdt.blit_text(surface, "=== SWING REPLAY ===", fonts['micro'],
                      (panel.x + 24, panel.y + 20), gdt.FG)
        self._chip_hits = gdt.draw_chips(
            surface, fonts['micro'], _VIEW_LABELS, self._view,
            panel.right - 24, panel.y + 16)
        pygame.draw.line(surface, gdt.DIVIDER,
                         (panel.x + 24, panel.y + 46),
                         (panel.right - 24, panel.y + 46), 1)

        self._draw_view(surface)
        self._draw_stats(surface)
        self._draw_hint(surface)

    def _panel_rect(self):
        rect = pygame.Rect(0, 0, self.PANEL_W, self.PANEL_H)
        rect.center = (self.screen_w // 2, self.screen_h // 2)
        return rect

    def _draw_view(self, surface):
        rect = self._view_rect()
        prev_clip = surface.get_clip()
        surface.set_clip(rect)

        self._draw_reference(surface)
        now_s = self._now_s()
        self._draw_ball_trail(surface, now_s)
        self._draw_bat_track(surface, now_s)
        self._draw_ghost(surface)
        self._draw_bat(surface, now_s)
        self._draw_ball(surface, now_s)
        self._draw_contact_marker(surface)

        surface.set_clip(prev_clip)
        pygame.draw.rect(surface, gdt.DIVIDER, rect, 1)
        self._draw_axis_labels(surface)

    # -- static reference -------------------------------------------------

    def _draw_reference(self, surface):
        """The plate, the ground or the batter's box, and the strike zone.

        Without these the view is two dots in a black rectangle; the whole
        readout depends on being able to see where the plate is.
        """
        rect = self._view_rect()
        if self._view == _VIEW_SIDE:
            ground = self._project((0.0, 0.0, 0.0))[1]
            pygame.draw.line(surface, gdt.DIVIDER,
                             (rect.x, ground), (rect.right, ground), 1)
            # Plate: a vertical band at y = 0, the timing datum.
            plate_x = self._project((0.0, 0.0, 0.0))[0]
            pygame.draw.line(surface, gdt.DIM_SOFT,
                             (plate_x, rect.y), (plate_x, ground), 1)
            gdt.blit_text(surface, "PLATE", self._f()['micro'],
                          (plate_x + 4, ground - 16), gdt.DIM_SOFT)
            top = self._project((0.0, 0.0, _STRIKE_ZONE_Z[1]))[1]
            bottom = self._project((0.0, 0.0, _STRIKE_ZONE_Z[0]))[1]
            pygame.draw.rect(surface, gdt.DIM_SOFT,
                             pygame.Rect(plate_x - 10, top, 20, bottom - top), 1)
        else:
            # Home plate, point toward the catcher: the 17 in edge faces the
            # pitcher at y = 0 and the apex is the far end, at y = -1.42. It
            # was drawn apex-first, which is a plate laid in back to front.
            left = self._project((_STRIKE_ZONE_X[0], 0.0, 0.0))[0]
            right = self._project((_STRIKE_ZONE_X[1], 0.0, 0.0))[0]
            front = self._project((0.0, 0.0, 0.0))[1]
            back = self._project((0.0, -1.42, 0.0))[1]
            pygame.draw.polygon(surface, gdt.DIM_SOFT, [
                (left, front), (right, front),
                (right, (front + back) / 2), ((left + right) / 2, back),
                (left, (front + back) / 2)], 1)
            lo, hi = self._depth_range()
            for depth in range(int(lo) + 1, int(hi)):
                if depth == 0:
                    continue
                y = self._project((0.0, float(depth), 0.0))[1]
                pygame.draw.line(surface, (24, 24, 24),
                                 (rect.x, y), (rect.right, y), 1)

    def _draw_axis_labels(self, surface):
        rect = self._view_rect()
        font = self._f()['micro']
        if self._view == _VIEW_SIDE:
            label = "FEET FROM PLATE  <- PITCHER   CATCHER ->"
        else:
            label = "OVERHEAD  <- 3B   1B ->"
        gdt.blit_text(surface, label, font,
                      (rect.x + 6, rect.bottom - 18), gdt.DIM_SOFT)

    # -- moving parts -----------------------------------------------------

    def _draw_ball_trail(self, surface, now_s):
        start, _ = self._window_s()
        pts = []
        for i in range(_TRAIL_LEN):
            t = _lerp(start, now_s, i / (_TRAIL_LEN - 1))
            pts.append(self._project(self._record.ball_at(t)))
        for i in range(1, len(pts)):
            shade = int(_lerp(40, 150, i / (len(pts) - 1)))
            pygame.draw.line(surface, (shade, shade, shade), pts[i - 1], pts[i], 1)

    def _draw_ball(self, surface, now_s):
        px, py = self._project(self._record.ball_at(now_s))
        pygame.draw.circle(surface, gdt.FG, (int(px), int(py)), 5)

    def _draw_bat_track(self, surface, now_s):
        """The barrel's path so far — the 'bat path' the feature is named for —
        and the hands' path under it, dimmer. The two arcs are the two facts
        of a swing (a small hand arc, a barrel whipping around it), and the
        hand path is what makes an inside-out or pulled contact legible as a
        body doing something rather than a line finding a point."""
        t_now = self._swing_t(now_s)
        if t_now <= 0:
            return
        sweet, knob = [], []
        for i in range(_BAT_TRACK_LEN):
            state = self._swing.state_at(t_now * i / (_BAT_TRACK_LEN - 1))
            sweet.append(self._project(state.sweet_spot_ft))
            knob.append(self._project(state.knob_ft))
        for i in range(1, _BAT_TRACK_LEN):
            fade = i / (_BAT_TRACK_LEN - 1)
            shade = int(_lerp(18, 70, fade))
            pygame.draw.line(surface, (shade, shade, shade), knob[i - 1], knob[i], 1)
            shade = int(_lerp(30, 120, fade))
            pygame.draw.line(surface, (shade, shade, shade), sweet[i - 1], sweet[i], 2)

    def _draw_bat(self, surface, now_s, state=None, color=None):
        """The bat itself: knob flare, handle, taper, barrel, rounded tip."""
        state = state or self._swing.state_at(self._swing_t(now_s))
        color = color or gdt.FG
        polygon, caps = self._bat_silhouette(state)
        for (cx, cy), radius in caps:
            pygame.draw.circle(surface, color, (round(cx), round(cy)),
                               max(1, round(radius)))
        if polygon is not None:
            pygame.draw.polygon(surface, color, polygon)

    def _draw_ghost(self, surface):
        """The same swing timed perfectly, once the replay reaches the freeze.

        Drawn only at the end: during the swing it would be a second bat
        moving in step with the first, which reads as a rendering fault rather
        than a reference.
        """
        if self._elapsed_ms < _PHASE_REPLAY_END:
            return
        fade = min(1.0, (self._elapsed_ms - _PHASE_REPLAY_END)
                   / max(1, _PHASE_FREEZE_END - _PHASE_REPLAY_END))
        shade = int(_lerp(0, 90, fade))
        if shade <= 2:
            return
        state = self._ghost.state_at(bat_path.SWING_DURATION_S)
        self._draw_bat(surface, 0.0, state=state, color=(shade, shade, shade))

    def _draw_contact_marker(self, surface):
        """Where the barrel actually met the ball."""
        if self._replay_progress() < 1.0:
            return
        px, py = self._project(self._swing.contact_ft)
        pygame.draw.circle(surface, gdt.FG, (int(px), int(py)), 9, 1)
        pygame.draw.line(surface, gdt.FG, (px - 12, py), (px + 12, py), 1)
        pygame.draw.line(surface, gdt.FG, (px, py - 12), (px, py + 12), 1)

    # -- numbers ----------------------------------------------------------

    def _draw_stats(self, surface):
        if self._elapsed_ms < _PHASE_INTRO_END:
            return
        panel = self._panel_rect()
        rect = self._view_rect()
        fonts = self._f()
        rec = self._record
        top = rect.bottom + 16

        self._draw_timing_scale(surface, panel.x + 24, top, panel.width - 48)

        cells = [
            ("TIMING", self._timing_text()),
            ("CONTACT PT", "%+.1f FT" % rec.contact_depth_ft),
            ("PITCH", "%s %.0f MPH" % (rec.pitch_type or "-", rec.speed_mph or 0)),
            ("RESULT", self._result_text()),
            ("QUALITY", "-" if rec.contact_quality is None
                        else "%.2f" % rec.contact_quality),
            ("BAT / BALL", self._offset_text()),
            ("EXIT VELO", "-" if rec.exit_velocity_mph is None
                          else "%.0f MPH" % rec.exit_velocity_mph),
            ("BAT SPEED", "%.0f MPH" % self._swing.bat_speed_mph),
        ]
        col_w = (panel.width - 48) // 4
        for i, (label, value) in enumerate(cells):
            cx = panel.x + 24 + (i % 4) * col_w
            cy = top + 54 + (i // 4) * 46
            gdt.blit_text(surface, label, fonts['micro'], (cx, cy), gdt.DIM)
            gdt.blit_text(surface, value, fonts['med'], (cx, cy + 15), gdt.FG)

    def _draw_timing_scale(self, surface, x, y, width):
        """Where this swing landed inside its own difficulty-scaled window.

        The windows move under the player between difficulties and are shown
        nowhere else in the game, so the bands are drawn rather than assumed.
        """
        rec = self._record
        fonts = self._f()
        span = max(rec.foul_ms * 1.6, abs(rec.signed_timing_ms) * 1.15, 40.0)
        centre = x + width / 2

        def at(ms):
            return centre + (ms / span) * (width / 2)

        bar_y = y + 22
        pygame.draw.line(surface, gdt.DIVIDER, (x, bar_y), (x + width, bar_y), 1)
        # Foul band, then the perfect band inside it.
        pygame.draw.rect(surface, (38, 38, 38), pygame.Rect(
            at(-rec.foul_ms), bar_y - 7, at(rec.foul_ms) - at(-rec.foul_ms), 14))
        pygame.draw.rect(surface, (78, 78, 78), pygame.Rect(
            at(-rec.perfect_ms), bar_y - 7,
            at(rec.perfect_ms) - at(-rec.perfect_ms), 14))

        gdt.blit_text(surface, "EARLY", fonts['micro'], (x, y), gdt.DIM_SOFT)
        gdt.blit_text(surface, "LATE", fonts['micro'],
                      (x + width, y), gdt.DIM_SOFT, align='right')

        marker = at(max(-span, min(span, rec.signed_timing_ms)))
        pygame.draw.line(surface, gdt.FG,
                         (marker, bar_y - 12), (marker, bar_y + 12), 2)

    def _timing_text(self):
        rec = self._record
        if rec.timing_label == "ON TIME":
            return "ON TIME"
        return "%s %.0f MS" % (rec.timing_label, abs(rec.signed_timing_ms))

    def _offset_text(self):
        inches = self._record.vertical_offset_inches
        if inches is None:
            return "-"
        # Positive offset means the bat sat below the ball (pygame y-down),
        # which is what `_compute_contact_quality` means by it.
        return "%.1f IN %s" % (abs(inches), "UNDER" if inches > 0 else "OVER")

    def _result_text(self):
        rec = self._record
        if rec.made_contact == "swung_and_miss":
            return "WHIFF"
        if rec.made_contact == "fouled":
            return "FOUL"
        return (rec.outcome or "IN PLAY").upper()

    def _draw_hint(self, surface):
        """Controls, on their own line below the stats grid.

        The grid is two rows of four and grows downward from the view, so the
        hint has to sit under the *taller* of the two possible layouts rather
        than at a fixed offset from the panel — it was landing on top of the
        EXIT VELO row.
        """
        panel = self._panel_rect()
        gdt.blit_text(
            surface,
            "SPACE  REPLAY      < >  SCRUB      TAB  VIEW      ESC  CLOSE",
            self._f()['micro'],
            (panel.centerx, panel.bottom - 24), gdt.DIM, align='center')
