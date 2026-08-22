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
third base on the left — which is why `_project` orients its horizontal axis
rather than taking `y` and `x` as they come. Drawn the other way the SIDE view
was a first-base camera captioned as a third-base one, and the OVERHEAD view
put `+x` on the right under a label reading `<- 3B`, i.e. a bird's eye from
underneath the infield. Nothing about a swing is symmetric, so a mirrored
replay quietly reverses which way the batter is turning.

**The SIDE camera changes sides with the batter** (`_side_camera_x`): it stands
down the first-base line for a right-hander and the third-base line for a
left-hander, which in both cases is the hitter's **open** side. Fixed on one
line — as it was — it was the open side for one hand and the *closed* side for
the other, and those are not two renderings of the same swing. From behind the
hitter the hands travel away from the camera, the barrel spends the swing
hidden behind the body, and the ball comes in over the batter's back, so every
quantity this view exists to show (how far out front contact was, whether the
barrel got on plane, the daylight between bat and ball) is a foreshortened
guess. It is the same reason a broadcast's swing camera and a hitting coach's
phone are both on the open side. OVERHEAD does *not* flip: a bird's eye has no
open side, and keeping 3B left / 1B right shared with the hit animation means
the spray ray reads the same way in both.

**The projections are deliberately separate from the game's camera.** The
`UmpireCamera` is a perspective projection from behind the plate; a bat path
seen from there sweeps almost entirely toward the viewer, which is exactly the
axis the analysis is about. These are plain orthographic feet-to-pixel maps
with their own scales, and the conversion happens in one place per view
(`_project`) so no drawing code ever handles a raw pixel scale.

**The clip ends when the bat and the ball met, not when the barrel arrived.**
Those are two different instants on any swing that was not squared up:
`bat_arrival_s` is a fact about the swing alone, while `bat_contact`'s sweep is
free to find the two at their closest anywhere in the arc, and on a mistimed
swing it does — up to ~25 ms of pitch time away, which at 101 mph is six feet
of ball. Running to the first while marking the second put a bat, a ball and a
crosshair in three different places on the one frame the player actually
studies, which is what made a HOME RUN look like a whiff. See
`SwingRecord.contact_time_s`.

**The bat and the ball touch, and it took a model change to make that true.**
`bat_contact` used to grant contact anisotropically — the bat was an ellipsoid
stretched along the ball's flight line by the cushion times the ball's speed,
5.8 ft at ROOKIE against a 101 mph fastball — so the model put the bat within
an inch or two of the ball's *line* and a foot or more from the ball itself. No
instant existed where they touched, because the forgiveness was in time rather
than in space, and this view drew that honestly: a foul ball with two and a
half feet of daylight under it. The forgiveness is now spent by sliding the
swing in time, so the frozen frame shows a real intersection. What survives is
`margin_ft`, an inch or two of bat tolerance, and `_draw_reach` still annotates
it on the rare frame where it is wide enough to see — shrinking that is a
difficulty decision, not a drawing one.

**The bat drawn is the bat that was swept**, which after the model change means
the *slid* swing: `SwingRecord.swing_launch_s` carries the shift. The timing
readouts stay on what the player actually did (`signed_timing_ms`), so the
panel reports the real error while the picture shows the swing the engine
graded. Those are two different true things and this view needs both.

**The ball is drawn unclamped.** The engine tests contact against a ball frozen
at the plate (see `swing_record`), but the pitch model keeps describing a real
ball for the few feet past it, and on a late swing that extrapolation *is* the
finding. Drawing the clamped ball would show every late swing meeting the ball
exactly at the plate, which is the one thing that cannot have happened.
"""


import math

import pygame

from strikefactor.gameplay import bat_path, spray
from strikefactor.ui import gameday_theme as gdt

# --- Phases, cumulative ms ---------------------------------------------------
_PHASE_INTRO_END = 420      # panel fades up, pitch card slides in
_PHASE_REPLAY_END = 2600    # the swing, in slow motion
_PHASE_FREEZE_END = 3100    # held at contact, ghost bat fades in
_DISMISS_FADE_MS = 260

_DIM_ALPHA = 225

# How much of the pitch to replay before the bat starts moving. The whole
# flight is ~0.4 s and the bat is only present for the last 0.15, so starting at
# release would spend most of the replay on an empty screen. Anchored to the
# swing's *launch* rather than measured back from the end, so the bat can never
# pop into existence already mid-arc however the swing was timed.
_PRE_SWING_S = 0.03
# The replay ends *at contact*, with no tail. A tail looks like it should be
# free — let the ball carry on past the barrel for a moment — but the freeze is
# the whole payoff, and at 93 mph even 60 ms of tail drags the ball eight feet
# past the contact marker, so the frame the player studies would show the bat
# and the ball in different places.
_REPLAY_TAIL_S = 0.0

# Below this much daylight the reach is not worth annotating: a squared-up
# swing has none, and a line drawn between two things already touching reads as
# clutter. Two inches, about two thirds of a ball.
_REACH_VISIBLE_FT = 0.17

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
# How far the spray ray is drawn, in feet. Long enough to leave the framed box
# from anywhere inside it, so the ray reads as a direction rather than as a
# segment with a meaningful end; the view's own clip trims it.
_SPRAY_RAY_FT = 14.0
_DEGREE = "\u00b0"
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
# `bat_path.BAT_PROFILE_IN`: fraction of the way from the knob to the tip,
# against the real radius there in inches.
#
# The profile lives in `bat_path` rather than here because `bat_contact` sweeps
# the same radii against the ball. One profile, or the bat the player is graded
# by is a different object from the bat they are shown.
#
# Radii are stated in **inches and scaled**, never set as a pixel width: each
# view frames a different number of feet and reframes depth per swing, so one
# pixel width is a different real bat in each view. See `_bat_scale` for why
# thickness takes a single scale where position and length take the honest
# anisotropic projection.
_BAT_PROFILE_IN = bat_path.BAT_PROFILE_IN

# Below this the bat has no drawable length to taper along and is rendered as
# its two end caps. Ordinary rather than exceptional: the SIDE view looks down
# the x axis and a bat at contact points largely along it.
_BAT_END_ON_PX = 2.0


def _ease_out(t):
    return 1.0 - (1.0 - t) ** 3


def _lerp(a, b, t):
    return a + (b - a) * t


def _draw_dashed_line(surface, color, a, b, dash=6, gap=5):
    """A dashed segment. Dashed so it reads as an annotation, not as an object
    in the scene — a solid line between the bat and the ball would look like
    part of one or the other."""
    span = math.dist(a, b)
    if span < 1.0:
        return
    ux, uy = (b[0] - a[0]) / span, (b[1] - a[1]) / span
    pos = 0.0
    while pos < span:
        end = min(span, pos + dash)
        pygame.draw.line(surface, color,
                         (a[0] + ux * pos, a[1] + uy * pos),
                         (a[0] + ux * end, a[1] + uy * end), 1)
        pos = end + gap


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
        self._ghost = None   # a BatState, not a second swing — see _draw_ghost
        self._depth_span = None
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
        """Open the replay on `record`. Builds both bats once, up front.

        The timing windows are measured here too, for the same reason the
        depth range is: `timing_windows_ms` re-sweeps the swing about 37 times
        and costs ~54 ms once. Left to compute lazily it would fire on the
        first frame `_draw_stats` runs, which is 420 ms into the replay — a
        visible stutter partway through the swing. Paid on the keypress that
        opens the overlay, it lands on a frame that was changing anyway.
        """
        self._record = record
        self._swing = record.bat_swing()
        self._ghost = record.bat_state_at_ball_arrival()
        self._depth_span = None
        self._depth_span = self._compute_depth_range()
        record.timing_windows_ms
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
        """(start, end) of the replayed slice of the pitch, in seconds.

        **It ends when the bat and the ball met, not when the barrel reached
        its contact pose.** Those are two different instants on any swing that
        was not squared up, and running to the second one is what made the
        frozen frame — the one the player actually studies — show the bat and
        the ball feet apart under a HOME RUN banner. The clip used to run
        ~25 ms of pitch time past a late contact, which at 101 mph is six feet
        of ball, and stop ~3 ms short of an early one; the crosshair marked the
        real contact point, so the freeze had a bat, a ball and a mark in three
        different places. See `SwingRecord.contact_time_s`.

        The start is anchored to the swing's launch rather than measured back
        from the end, so moving the end cannot pull the bat into the frame
        already mid-arc.
        """
        rec = self._record
        return (rec.swing_launch_s - _PRE_SWING_S,
                rec.contact_time_s + _REPLAY_TAIL_S)

    def _now_s(self):
        """Where the replay clock currently sits, in pitch seconds."""
        start, end = self._window_s()
        return _lerp(start, end, self._replay_progress())

    def _swing_t(self, now_s):
        """Where the barrel is, in swing seconds. Clamped at both ends.

        The upper clamp is the *end of the follow-through*, not contact: the
        bat keeps moving after the ball is met, and on an early swing it is
        still moving when the ball arrives.
        """
        launch = self._record.swing_launch_s
        return max(0.0, min(bat_path.TOTAL_DURATION_S, now_s - launch))

    # -- projection -------------------------------------------------------

    def _view_rect(self):
        panel = self._panel_rect()
        return pygame.Rect(panel.x + 24, panel.y + 76, panel.width - 48, self.VIEW_H)

    def _depth_range(self):
        """The framed slice of depth, in feet, for this swing.

        Cached at `trigger`, because `_project` asks for it on every point it
        converts and `barrel_depth_ft` rebuilds four swings each time it is
        read — a few hundred `bat_path.swing` constructions a frame, for a
        number that cannot change while a record is open.
        """
        if self._depth_span is None:
            self._depth_span = self._compute_depth_range()
        return self._depth_span

    def _compute_depth_range(self):
        """Everything the frozen frame has to hold, plus a margin.

        Framed per swing rather than fixed because contact runs from about
        11 ft out front on a badly early swing to 11 ft deep on a late one, and
        any single window wide enough for both squeezes the ordinary swing into
        the middle sixth of the view.

        What it has to hold is what gets *drawn*: the plate, the ball and the
        bat at the freeze, and the barrel's nominal arrival, which the stats
        name and the ghost sits near. It used to be framed on the ball at bat
        arrival — which on a late swing is several feet past anything the clip
        now reaches, so half the view was empty air behind the catcher.
        """
        rec = self._record
        marks = [rec.struck_depth_ft, rec.barrel_depth_ft]
        state = self._swing.state_at(self._swing_t(rec.contact_time_s))
        marks += [state.knob_ft[1], state.barrel_ft[1]]
        return (min([_MIN_DEPTH_RANGE[0]] + [d - _DEPTH_MARGIN_FT for d in marks]),
                max([_MIN_DEPTH_RANGE[1]] + [d + _DEPTH_MARGIN_FT for d in marks]))

    def _side_camera_x(self):
        """Which foul line the SIDE camera stands on, as the sign of world x.

        The batter's **open** side, so it depends on which box they are in: a
        right-hander stands on the third-base side (`+x`), and the camera that
        sees the front of that swing is the one down the *first*-base line.
        A left-hander is the mirror of it and gets the third-base camera.

        Fixed on one line it was the open side for one hand and the closed
        side for the other, and those are not two renderings of one swing —
        from behind, the hands travel away from the camera, the barrel spends
        the swing hidden behind the body, and the ball arrives from behind the
        hitter's back. Everything this view is read for (how far in front
        contact was, whether the barrel got on plane, the daylight between bat
        and ball) is a foreshortened guess from there. It is also why a
        broadcast and a hitting coach both film from the open side.

        Stated as the negative of `spray.spin_for`, which is already the sign
        of the batter's own box, rather than as a second reading of `"L"`:
        the camera is *opposite* the hitter by definition, so there is one
        handedness convention here and not two that could drift apart.
        """
        return -spray.spin_for(self._record.handedness)

    def _project(self, point_ft):
        """World feet to screen pixels for the active view.

        The single crossing from feet to pixels. Both views are orthographic
        and both flip their vertical axis, since screen y grows downward while
        every world quantity here grows up or out. Their horizontal axes are
        oriented so that each camera stands where its label says it does — see
        the note on mirroring at the top of the module.
        """
        rect = self._view_rect()
        x_ft, y_ft, z_ft = point_ft
        if self._view == _VIEW_SIDE:
            # Facing the batter from `_side_camera_x`: from the third-base
            # line the pitcher (+y) is to the left, from first base to the
            # right. One sign, applied to the point and to the window
            # together, so the two can never disagree about which way is which.
            lo, hi = self._depth_range()
            sign = -self._side_camera_x()
            h_lo, h_hi = sorted((sign * lo, sign * hi))
            v_lo, v_hi = _SIDE_Z_RANGE
            h, v = sign * y_ft, z_ft
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
        self._draw_spray(surface)

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
            # Labelled on the catcher's side of the line, which changes screen
            # side with the camera. Pinned to +4 px it sat out in front of the
            # plate for a first-base camera, i.e. across the contact point,
            # the bat and the ball — the busiest few inches of the view.
            behind = 1 if self._project((0.0, -1.0, 0.0))[0] > plate_x else -1
            gdt.blit_text(surface, "PLATE", self._f()['micro'],
                          (plate_x + 4 * behind, ground - 16), gdt.DIM_SOFT,
                          align='left' if behind > 0 else 'right')
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

    def _axis_label(self):
        """The caption under the view, naming what each screen axis is.

        A method rather than a literal because the SIDE camera swaps foul
        lines with the batter, and which line it is standing on is the one
        thing the player cannot read off the picture — a mirrored swing is
        still a swing. Kept together with the projection so a test can hold
        the two to the same story; a caption that outlives the geometry it
        describes is exactly the fault this view was drawn wrong by before.
        """
        if self._view != _VIEW_SIDE:
            return "OVERHEAD  <- 3B   1B ->"
        if self._side_camera_x() > 0:
            return "FROM 3B SIDE  <- PITCHER   CATCHER ->"
        return "FROM 1B SIDE  <- CATCHER   PITCHER ->"

    def _draw_axis_labels(self, surface):
        rect = self._view_rect()
        gdt.blit_text(surface, self._axis_label(), self._f()['micro'],
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
        """Where the bat was when the ball reached the barrel's plane.

        The reference the player reads the error off, and it costs nothing:
        with the path independent of the pitch, "the swing timed properly" is
        *this* swing at a different phase, so the ghost is one more sample of
        the same motion rather than a second bat built from a second model.
        A late swing was still on its way; an early one is already into the
        follow-through, which is one of the things `bat_path` is defined past
        contact for.

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
        self._draw_bat(surface, 0.0, state=self._ghost,
                       color=(shade, shade, shade))

    def _draw_contact_marker(self, surface):
        """Where the bat and the ball actually met.

        Falls back to where the barrel arrived when they never met at all — a
        whiff, where the gap between this mark and the ball is exactly what
        the view is for. The clip now freezes *at* this instant, so on contact
        the mark sits on the drawn ball rather than somewhere neither the bat
        nor the ball ever reached.
        """
        if self._replay_progress() < 1.0:
            return
        contact = self._record.contact
        point = contact.ball_ft if contact is not None else self._swing.contact_ft
        px, py = self._project(point)
        pygame.draw.circle(surface, gdt.FG, (int(px), int(py)), 9, 1)
        pygame.draw.line(surface, gdt.FG, (px - 12, py), (px + 12, py), 1)
        pygame.draw.line(surface, gdt.FG, (px, py - 12), (px, py + 12), 1)
        self._draw_reach(surface, contact)

    def _draw_spray(self, surface):
        """Where the ball went, drawn from where it was struck.

        OVERHEAD only, and this is what that view was always for — the module
        docstring calls it the view "where pull-versus-oppo contact reads", and
        until the ball had a bearing there was nothing there to read. The ray
        is the ball's actual departure direction (`spray`), the same number the
        animation flies it along, so the picture and the outcome cannot
        disagree: a bat caught out in front with its face toward third draws a
        ray toward third, and the ball then goes to left.

        Frozen-frame only, like the contact marker and for the same reason —
        until the two have met there is no direction yet.
        """
        if self._view != _VIEW_OVERHEAD or self._replay_progress() < 1.0:
            return
        contact = self._record.contact
        if contact is None:
            return

        spin = spray.spin_for(self._record.handedness)
        deg = contact.spray_deg
        rad = math.radians(deg)
        # The departure direction in world feet. Pull is +x for a right-hander
        # and -x for a left-hander, which is exactly what `spin` is.
        direction = (spin * math.sin(rad), math.cos(rad), 0.0)
        start = contact.ball_ft
        end = tuple(start[i] + _SPRAY_RAY_FT * direction[i] for i in range(3))
        # Projected rather than stepped in pixels: `_project` is the one
        # crossing from feet to pixels and it orients the horizontal axis, so
        # anything drawing its own screen vector here gets the mirror wrong.
        a, b = self._project(start), self._project(end)

        foul = spray.is_foul(deg)
        color = gdt.DIM if foul else gdt.FG
        _draw_dashed_line(surface, color, a, b, dash=7, gap=6)

        side = "PULL" if deg > 0 else "OPPO"
        text = "%s %.0f%s" % (side, abs(deg), _DEGREE)
        if foul:
            text = "FOUL  " + text
        gdt.blit_text(surface, text, self._f()['micro'],
                      (b[0] + 8, b[1] - 6), color)

    def _draw_reach(self, surface, contact):
        """The daylight `margin_ft` covered, drawn as a line.

        Rare now, and small when it appears: the median contact has the bat and
        the ball genuinely overlapping, and the tolerance that is left is
        bounded by `bat_contact.margin_ft` — 2.4 in at AMATEUR, 3.4 at ROOKIE.
        Roughly the top decile of contacts clear `_REACH_VISIBLE_FT` and get a
        line.

        **It used to be the thing this view could not make disappear**, because
        the timing forgiveness was spent as a reach along the ball's flight
        line: 5.8 ft of it at ROOKIE, so a mistimed swing was granted contact
        with the bat a foot or more from the ball and the frozen frame showed
        no contact at all. Keeping the annotation is what makes the remaining
        inch or two legible instead of leaving it to read as a rendering fault
        — and `tests/test_swing_replay.py` pins that it can never grow back
        past the margin.
        """
        if contact is None:
            return
        reach = contact.surface_gap_ft
        if reach < _REACH_VISIBLE_FT:
            return
        a = self._project(contact.axis_point_ft)
        b = self._project(contact.ball_ft)
        span = math.dist(a, b)
        if span < 1.0:
            return
        _draw_dashed_line(surface, gdt.DIM, a, b)
        # Labelled past the *ball*, on the far side from the bat, rather than
        # over the midpoint: the bat is a long object lying along this line and
        # the midpoint is usually on top of it, or on the ghost.
        rect = self._view_rect()
        ux = (b[0] - a[0]) / span
        x = min(rect.right - 6, max(rect.x + 6, b[0] + ux * 10))
        gdt.blit_text(surface, "REACH %.1f FT" % reach, self._f()['micro'],
                      (x, b[1] - 20), gdt.DIM,
                      align='right' if ux < 0 else 'left')

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
            # The ball's depth *in the frame on screen*, which on contact is
            # where it was struck and on a whiff is where it had got to when
            # the barrel arrived. It read `contact_depth_ft` unconditionally,
            # so a late swing showed the ball 6 ft behind the one it drew.
            ("BALL AT", "%+.1f FT" % rec.struck_depth_ft),
            ("BARREL AT", "%+.1f FT" % rec.barrel_depth_ft),
            ("RESULT", self._result_text()),
            ("PITCH", "%s %.0f MPH" % (rec.pitch_type or "-", rec.speed_mph or 0)),
            ("QUALITY", "-" if rec.contact_quality is None
                        else "%.2f" % rec.contact_quality),
            ("BAT / BALL", self._offset_text()),
            ("EXIT VELO", "-" if rec.exit_velocity_mph is None
                          else "%.0f MPH" % rec.exit_velocity_mph),
        ]
        col_w = (panel.width - 48) // 4
        for i, (label, value) in enumerate(cells):
            cx = panel.x + 24 + (i % 4) * col_w
            cy = top + 54 + (i // 4) * 46
            gdt.blit_text(surface, label, fonts['micro'], (cx, cy), gdt.DIM)
            gdt.blit_text(surface, value, fonts['med'], (cx, cy + 15), gdt.FG)

    def _draw_timing_scale(self, surface, x, y, width):
        """The timing this swing had, and where in it the swing landed.

        **The bands are measured, not assumed** — `SwingRecord.timing_windows_ms`
        re-sweeps this swing against its own pitch, so the outer band is where
        it would have touched the ball at all and the inner one where it would
        have been fair. They used to be `perfect_ms` / `foul_ms`, 30 and 60 ms
        scaled by difficulty, inherited from the timing *gate* the geometry
        replaced; by the end they were fiction, drawing an ON TIME band across
        a range over which quality ran from 1.00 to 0.12.

        The measured bands are **strongly asymmetric** — roughly -42..+81 ms at
        AMATEUR — and that asymmetry is the most useful thing on the bar: a
        late bat still catches the ball on the handle, an early one runs out of
        barrel. A symmetric pair of constants could not show it, and the player
        has no other way to learn it.
        """
        rec = self._record
        fonts = self._f()
        windows = rec.timing_windows_ms
        reach = max(abs(v) for v in (windows.contact or (0.0, 0.0)))
        span = max(reach * 1.2, abs(rec.signed_timing_ms) * 1.15, 40.0)
        centre = x + width / 2

        def at(ms):
            return centre + (max(-span, min(span, ms)) / span) * (width / 2)

        def band(pair, color):
            if pair is None:
                return
            lo, hi = at(pair[0]), at(pair[1])
            pygame.draw.rect(surface, color,
                             pygame.Rect(lo, bar_y - 7, max(1.0, hi - lo), 14))

        bar_y = y + 22
        pygame.draw.line(surface, gdt.DIVIDER, (x, bar_y), (x + width, bar_y), 1)
        # Any contact, then the fair band inside it.
        band(windows.contact, (38, 38, 38))
        band(windows.fair, (78, 78, 78))
        self._draw_budget_ticks(surface, at, bar_y)

        gdt.blit_text(surface, "EARLY", fonts['micro'], (x, y), gdt.DIM_SOFT)
        gdt.blit_text(surface, "LATE", fonts['micro'],
                      (x + width, y), gdt.DIM_SOFT, align='right')

        marker = at(max(-span, min(span, rec.signed_timing_ms)))
        pygame.draw.line(surface, gdt.FG,
                         (marker, bar_y - 12), (marker, bar_y + 12), 2)
        self._draw_assist(surface, at, bar_y, y)

    def _draw_budget_ticks(self, surface, at, bar_y):
        """How much of the clock the difficulty covers for free.

        Ticks rather than a third band, because the assist budget and the fair
        window very nearly coincide — measured on a well-aimed swing, +/-39 ms
        of budget against a fair window of -41..+42 at ROOKIE, and +/-26
        against -32..+33 at AMATEUR. A band would imply a distinction that is
        not there and would be drawn all but on the edge of the one beneath it.
        As ticks it reads as what it is: inside here the slide covers the error
        outright, which at every difficulty is very nearly the same line as
        squaring the ball up.
        """
        budget = self._record.timing_assist_ms
        if budget <= 0.0:
            return
        for ms in (-budget, budget):
            px = at(ms)
            pygame.draw.line(surface, gdt.DIM_SOFT,
                             (px, bar_y - 7), (px, bar_y - 2), 1)
            pygame.draw.line(surface, gdt.DIM_SOFT,
                             (px, bar_y + 2), (px, bar_y + 7), 1)

    def _draw_assist(self, surface, at, bar_y, y):
        """Where the engine put the swing, against where the player put it.

        `bat_contact` slides a swing by up to `timing_assist_s` before sweeping
        it, so a swing that reads 40 ms late can still meet the ball squarely —
        and the quality it scores is charged for exactly that borrowed time.
        Leaving it off the panel would put this screen back to reporting a
        number the player has no way to account for, which is the fault the
        model change removed: the old cushion charged for its reach too, as
        five inches of "bat over ball" that no aim error explained.

        Drawn dim and thin against the player's own solid marker: the bright
        one is what they did, which is the thing worth learning.
        """
        rec = self._record
        shift_ms = rec.shift_s * 1000.0
        if abs(shift_ms) < 1.0:
            return
        slid = at(rec.signed_timing_ms + shift_ms)
        pygame.draw.line(surface, gdt.DIM,
                         (slid, bar_y - 12), (slid, bar_y + 12), 1)
        gdt.blit_text(surface, "ASSIST %.0f MS" % abs(shift_ms),
                      self._f()['micro'], (slid, y + 34), gdt.DIM,
                      align='center')

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
