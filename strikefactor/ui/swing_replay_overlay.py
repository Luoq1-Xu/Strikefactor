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
axis the analysis is about. These are plain orthographic feet-to-pixel maps,
and the conversion happens in one place per view (`_project`) so no drawing
code ever handles a raw pixel scale.

**A foot is a foot in every direction, in both views.** Each view has one
scale, shared by its two axes (`_fit_isotropic`): the axis with the least room
per foot sets it, and the other is widened about its centre until it fills its
side of the rect. It used to be two scales per view — the range framed along
each axis was simply stretched across the rect — and the OVERHEAD picture was
fitting 11 ft of width into 1072 px and 14 ft of depth into 340, a 4:1 squash
that drew the swing's round arc as a flattened ellipse and a bat lying across
the plate at four times the length of one pointing at the mound. SIDE carried
the same fault at 1.6:1. The isotropic OVERHEAD window shows some 30 ft of
field either side of the plate, so the batter's boxes and the foul lines are
drawn in it — that is what makes the width read as a field rather than as the
picture having shrunk, and it puts the spray ray's fair-or-foul against the
lines it is a verdict about.

**The clip ends when the bat and the ball met, not when the barrel arrived.**
Those are two different instants on any swing that was not squared up:
`bat_arrival_s` is a fact about the swing alone, while `bat_contact`'s sweep is
free to find the two at their closest anywhere in the arc, and on a mistimed
swing it does — up to ~25 ms of pitch time away, which at 101 mph is six feet
of ball. Running to the first while marking the second put a bat, a ball and a
crosshair in three different places on the one frame the player actually
studies, which is what made a HOME RUN look like a whiff. See
`SwingRecord.contact_time_s`.

**A swing that missed names neither instant, so it runs to the plate.** There
was no meeting to freeze on, and the fallback — the barrel's arrival — is a
fact about the bat alone: on an early miss the ball is still feet out in front
there, so the clip stopped with the pitch hanging in mid-air, which is the one
frame nothing can be read off. Followed to the plate the pitch finishes, the
swing carries into its follow-through beside it, and the ball the batter missed
is last seen where the call is made. `SwingRecord.clip_end_s` owns the choice;
the crosshair still marks the barrel's arrival and `_draw_missed_ball` outlines
the ball as it was at that same moment, so the instant the panel reports is
still on screen.

**One slow-motion rate, not one duration.** The wall-clock length of the clip
is the length of the slice it shows (`_compute_phases`), because the slice is
not the same length every time — a late contact is more pitch than an early
one, and a miss followed to the plate is more again. Divided out of a fixed
duration, as it was, the rate became a function of the swing and the clips that
had most to show played fastest.

**The bat and the ball touch, and it took a model change to make that true.**
Difficulty forgiveness once enlarged the collision solid invisibly, so the
engine could award a hit while the real bat and ball had daylight between
them. It now slides the swing in time and, for a bounded near miss, translates
the whole swing visibly in x/z before a strict physical re-sweep. The frozen
contact frame therefore always contains a real intersection.

**The bat drawn is the bat that was swept.** `SwingRecord.swing_launch_s`
carries the timing shift and `bat_swing()` carries the rigid spatial shift.
The timing readouts stay on what the player actually did (`signed_timing_ms`),
so the panel reports the real error while the picture shows the swing the
engine graded. Those are two different true things and this view needs both.

**The ball is drawn unclamped.** The engine tests contact against a ball frozen
at the plate (see `swing_record`), but the pitch model keeps describing a real
ball for the few feet past it, and on a late swing that extrapolation *is* the
finding. Drawing the clamped ball would show every late swing meeting the ball
exactly at the plate, which is the one thing that cannot have happened.
"""


import math

import pygame

from strikefactor.gameplay import bat_contact, bat_path, spray
from strikefactor.ui import gameday_theme as gdt

# --- Phases, cumulative ms ---------------------------------------------------
# The intro is a fixed piece of chrome; the two that follow are computed per
# swing by `_compute_phases`, because the slice of pitch being shown is not the
# same length every time.
_PHASE_INTRO_END = 420      # panel fades up, pitch card slides in
_FREEZE_HOLD_MS = 500       # held at the end, ghost bat fading in
_DISMISS_FADE_MS = 260

# **One slow-motion rate for every swing**, stated as wall-clock milliseconds
# per second of pitch. The replay used to be a fixed 2180 ms of wall clock
# divided by whatever window the swing happened to need, which is two clocks
# again: a late contact is a longer slice of pitch and so played *faster* than
# an early one, and a miss that follows the ball to the plate would have been
# faster still. Fixing the rate instead means the swing looks the same at every
# timing and a clip that has more pitch to show simply runs longer. 12000 is
# 12x slow motion, and reproduces the old duration for an ordinary swing --
# 0.18 s of pitch, since the window is `_PRE_SWING_S` plus the swing.
_REPLAY_MS_PER_PITCH_S = 12000

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

_VIEW_SIDE = 0
_VIEW_OVERHEAD = 1
_VIEW_LABELS = ["SIDE", "OVERHEAD"]

# --- Field of view, in feet --------------------------------------------------
# These are the ranges each view *must* hold; `_fit_isotropic` then widens
# whichever axis has room to spare so both share one scale. Depth is framed per
# swing (`_compute_depth_range`) rather than fixed: contact ranges from about
# 11 ft out front on a badly early swing to 11 ft deep on a late one, and any
# single window wide enough for both squeezes the ordinary swing into the
# middle sixth of the view.
_SIDE_Z_RANGE = (0.0, 7.5)   # the loaded barrel tip sits at ~7 ft
_OVER_X_RANGE = (-5.5, 5.5)
# How far the spray ray is drawn, in feet. Long enough to leave the framed box
# from anywhere inside it, so the ray reads as a direction rather than as a
# segment with a meaningful end; the view's own clip trims it, and the label
# sits where the ray leaves the frame (`_draw_spray`), not at this end.
_SPRAY_RAY_FT = 40.0
# Points along that ray. The flown track is a quadratic, so a handful of
# segments draws it smoothly; the bend is worth having because it is not
# uniformly small. Over the drawn 40 ft it is 2-4 inches on a 380 ft fly and
# **2.4 ft on a 110 ft foul**, since the drift goes as the square of the
# fraction of the carry covered — and the short balls are most of what this
# view is opened to look at.
_SPRAY_TRACK_SAMPLES = 12
_DEGREE = "\u00b0"
# The depth window is what the frozen frame draws, plus this margin. It stands
# on the OVERHEAD view's *short* axis and so sets that picture's scale
# directly: at the old 4 ft margin over a (-5, 9) floor it was 14 ft deep in
# 340 px, 24 px/ft, and a bat was a 67 px sliver. The swing's own path is part
# of what is framed (the load pose puts the barrel nearly 4 ft behind the
# plate), so the floor only has to guarantee the plate and its surrounds.
_DEPTH_MARGIN_FT = 1.5
_MIN_DEPTH_RANGE = (-4.0, 5.0)
_FRAME_TRACK_SAMPLES = 24

_STRIKE_ZONE_Z = (1.5, 3.5)
_STRIKE_ZONE_X = (-0.708, 0.708)   # 17 in
# The plate and the boxes beside it, from the MLB field diagram: the plate is
# 17 in across and 17 in from its front edge to the apex; each batter's box is
# 4 ft by 6 ft, 6 in off the plate's edge and centred on the plate's centre
# line. OVERHEAD only, where the isotropic window has the room for them.
_PLATE_DEPTH_FT = 1.42
_BATTERS_BOX_W_FT = 4.0
_BATTERS_BOX_L_FT = 6.0
_BATTERS_BOX_GAP_FT = 0.5

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
# pixel width is a different real bat in each view. They go through the same
# `_projected_radius` as everything else, which is only honest because the
# projection is isotropic — under the old per-axis scales a bat lying across
# the OVERHEAD view was a needle a quarter as thick as one pointing up it.
_BAT_PROFILE_IN = bat_path.BAT_PROFILE_IN
_BAT_RENDER_SAMPLES = 96
# The stations every bat is sampled at: an even sweep plus the profile's
# own breakpoints, so the taper's corners survive the resampling. Constant,
# so it is built once rather than per bat per frame.
_BAT_BASE_FRACTIONS = frozenset(
    [i / (_BAT_RENDER_SAMPLES - 1) for i in range(_BAT_RENDER_SAMPLES)]
    + [frac for frac, _ in _BAT_PROFILE_IN])
_BAT_SORTED_FRACTIONS = tuple(sorted(_BAT_BASE_FRACTIONS))

def _ease_out(t):
    return 1.0 - (1.0 - t) ** 3


def _fit_isotropic(h_range, v_range, width_px, height_px):
    """One scale for both axes: the ranges a view must hold, widened to fill it.

    Whichever axis has the least room per foot sets the scale; the other is
    widened symmetrically about its own centre until it fills its side of the
    rect at that same scale. So the binding axis comes back exactly as given
    and the other comes back wider, never narrower — isotropy is bought with
    field of view, not by shrinking anything the view had to hold. Returns
    `((h_lo, h_hi), (v_lo, v_hi))`, in feet along the screen's axes.
    """
    scale = min(width_px / (h_range[1] - h_range[0]),
                height_px / (v_range[1] - v_range[0]))

    def widen(rng, px):
        half = px / scale / 2.0
        mid = (rng[0] + rng[1]) / 2.0
        return (mid - half, mid + half)

    return widen(h_range, width_px), widen(v_range, height_px)


def _exit_point(a, b, rect):
    """Where the segment `a -> b` leaves `rect`; `b` itself if it never does.

    `a` is taken to be inside. Written for the spray label, which wants to sit
    where the ray crosses out of the view rather than at a far end the clip
    has removed.
    """
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = 1.0
    for lo, hi, start, delta in ((rect.left, rect.right, a[0], dx),
                                 (rect.top, rect.bottom, a[1], dy)):
        if delta > 0:
            t = min(t, (hi - start) / delta)
        elif delta < 0:
            t = min(t, (lo - start) / delta)
    t = max(0.0, t)
    return (a[0] + dx * t, a[1] + dy * t)


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
        self._frames = None   # per-view isotropic windows, see _compute_frame
        # Per-swing phase boundaries, set by `_compute_phases` at `trigger`.
        # Defaulted so the clock methods are total even with no record open.
        self._replay_end_ms = _PHASE_INTRO_END
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
        self._review_rect = None
        self._record = record
        self._swing = record.bat_swing()
        self._ghost = record.bat_state_at_ball_arrival()
        self._replay_end_ms = self._compute_phases()
        self._depth_span = self._compute_depth_range()
        self._frames = {view: self._compute_frame(view)
                        for view in (_VIEW_SIDE, _VIEW_OVERHEAD)}
        # Warmed here rather than on the first frame that draws the bands:
        # measuring them re-sweeps the swing about 26 times, which is a
        # visible stutter partway through an already-running replay.
        record.warm_timing_windows()
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
        self._elapsed_ms = min(self._freeze_end_ms, self._elapsed_ms + int(dt_ms))

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
                if self._elapsed_ms >= self._freeze_end_ms:
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
        span = self._replay_end_ms - _PHASE_INTRO_END
        self._elapsed_ms = max(_PHASE_INTRO_END,
                               min(self._freeze_end_ms,
                                   self._elapsed_ms + direction * span // 40))

    # -- the replay clock -------------------------------------------------

    def _replay_progress(self):
        """0 at the start of the shown window, 1 at the freeze."""
        if self._elapsed_ms <= _PHASE_INTRO_END:
            return 0.0
        span = max(1, self._replay_end_ms - _PHASE_INTRO_END)
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

        **A swing that missed has no such instant, and used to stop the pitch
        in mid-air.** It runs to the plate instead — see
        `SwingRecord.clip_end_s`, which owns that choice because it is a fact
        about the swing rather than about the drawing.

        The start is anchored to the swing's launch rather than measured back
        from the end, so moving the end cannot pull the bat into the frame
        already mid-arc.
        """
        rec = self._record
        return (rec.swing_launch_s - _PRE_SWING_S,
                rec.clip_end_s + _REPLAY_TAIL_S)

    def _compute_phases(self):
        """`replay_end_ms` for the record now open.

        The replay's wall-clock length is the window's length at one fixed
        slow-motion rate, so the bat sweeps at the same speed on every swing
        and a clip with more pitch to show simply runs for longer. Fixed at
        2180 ms — as it was — the rate instead became a function of the swing:
        a late contact is a longer slice of pitch and so played *faster* than
        an early one, and a miss followed to the plate would have been faster
        again, which is the opposite of what a replay is for.

        Computed at `trigger` for the same reason the depth range is: it
        cannot change while a record is open, and three clock methods ask for
        it on every frame.
        """
        start, end = self._window_s()
        return _PHASE_INTRO_END + round(max(0.0, end - start)
                                        * _REPLAY_MS_PER_PITCH_S)

    @property
    def _freeze_end_ms(self):
        """When the held frame is done. Derived rather than stored: the hold
        is a fixed length after the replay ends, and two fields with an
        invariant between them are two chances to break it."""
        return self._replay_end_ms + _FREEZE_HOLD_MS

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
        if getattr(self, '_review_rect', None) is not None:
            return pygame.Rect(panel.x + 24, panel.y + 6, panel.width - 48, panel.height - 190)
        return pygame.Rect(panel.x + 24, panel.y + 76, panel.width - 48, self.VIEW_H)

    def _depth_range(self):
        """The framed slice of depth, in feet, for this swing.

        Computed at `trigger`, because `_project` asks for it on every point
        it converts and it cannot change while a record is open.
        """
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

        Everything here is asked at `clip_end_s`, which is where the clip
        actually stops: on a miss that is the plate rather than the barrel's
        arrival, and the bat has carried further into its follow-through by
        then.

        **The swing's own path is in it too**, sampled as far as the clip
        runs, plus the ghost. This range stands on the OVERHEAD view's short
        axis, where it sets the scale of the whole picture, so it is framed
        on what is drawn at a small margin rather than on the end points at a
        large one: the load pose puts the barrel nearly 4 ft behind the
        plate, which the old (-5, 9) floor happened to cover and this one
        does not need to.
        """
        rec = self._record
        marks = [rec.struck_depth_ft, rec.barrel_depth_ft,
                 rec.ball_at(rec.clip_end_s)[1]]
        t_end = self._swing_t(rec.clip_end_s)
        for i in range(_FRAME_TRACK_SAMPLES + 1):
            state = self._swing.state_at(t_end * i / _FRAME_TRACK_SAMPLES)
            marks += [state.knob_ft[1], state.barrel_ft[1]]
        marks += [self._ghost.knob_ft[1], self._ghost.barrel_ft[1]]
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

    def _compute_frame(self, view):
        """The window `view` shows, as `((h_lo, h_hi), (v_lo, v_hi))` in feet
        along the screen's own axes — the ranges the view must hold, fitted
        to the rect at one scale by `_fit_isotropic`.

        SIDE must hold the depth range across and `_SIDE_Z_RANGE` up; depth
        has the long side of the rect and so is the one that gets widened.
        OVERHEAD must hold `_OVER_X_RANGE` across and the depth range up, and
        there depth is on the short side and sets the scale, which is why
        `_compute_depth_range` frames tightly. Both are computed at `trigger`
        for both views, since `_project` asks on every point and TAB can
        switch views mid-replay.
        """
        rect = self._view_rect()
        lo, hi = self._depth_range()
        if view == _VIEW_SIDE:
            # One sign, applied to the range here and to the point in
            # `_project`, so the two can never disagree about which way is
            # which.
            sign = -self._side_camera_x()
            h_range = tuple(sorted((sign * lo, sign * hi)))
            v_range = _SIDE_Z_RANGE
        else:
            h_range = (-_OVER_X_RANGE[1], -_OVER_X_RANGE[0])
            v_range = (lo, hi)
        return _fit_isotropic(h_range, v_range, rect.width, rect.height)

    def _frame_ft(self):
        """The active view's window — see `_compute_frame`."""
        return self._frames[self._view]

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
            # right.
            h, v = -self._side_camera_x() * y_ft, z_ft
        else:
            # From above: third base (+x) is to the left, the pitcher is up.
            h, v = -x_ft, y_ft
        (h_lo, h_hi), (v_lo, v_hi) = self._frame_ft()
        px = rect.x + (h - h_lo) / (h_hi - h_lo) * rect.width
        py = rect.bottom - (v - v_lo) / (v_hi - v_lo) * rect.height
        return (px, py)

    def _px_per_ft(self):
        """Pixels per foot along each screen axis, for the active view.

        Two numbers that are equal by construction (`_fit_isotropic`), still
        handed out as a pair because a projected sphere has a radius along
        each axis and the drawing code asks for both; a test pins them equal.
        They were genuinely different — ~97 px/ft across against ~24 down in
        OVERHEAD — which is the squash this module no longer has.
        """
        rect = self._view_rect()
        (h_lo, h_hi), (v_lo, v_hi) = self._frame_ft()
        return (rect.width / (h_hi - h_lo), rect.height / (v_hi - v_lo))

    def _projected_radius(self, radius_ft):
        """Ellipse radii produced by projecting a world-space sphere."""
        sx, sy = self._px_per_ft()
        return radius_ft * sx, radius_ft * sy

    def _bat_ellipses(self, state, extra_fracs=()):
        """Project the shared swept-sphere bat used by collision.

        Sampling the same centre/radius function as `bat_contact` prevents a
        real intersection from opening into visible daylight merely because
        the bat happens to point across the view. The radii come back as a
        pair because `_projected_radius` is a general projection of a
        sphere; with one scale per view they are equal and the ellipses are
        circles.
        """
        if extra_fracs:
            fractions = sorted(_BAT_BASE_FRACTIONS.union(
                max(0.0, min(1.0, f)) for f in extra_fracs))
        else:
            fractions = _BAT_SORTED_FRACTIONS
        # One scale for the whole bat: `_projected_radius` would re-derive it
        # per station, and it builds a fresh Rect each time via `_view_rect`.
        # That is ~100 redundant Rect constructions per bat per frame for a
        # value that cannot change within one projection.
        sx, sy = self._px_per_ft()
        result = []
        for frac in fractions:
            centre, radius = bat_path.bat_solid_point(state, frac)
            result.append((self._project(centre), (radius * sx, radius * sy)))
        return result

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

    def review_duration_ms(self):
        """Length of the replayed slice, in milliseconds of pitch time.

        The transport and this renderer must measure the clip against the
        same `_window_s`; computing it in both places means a change to the
        window (`_PRE_SWING_S`, the miss-to-plate rule) has to be edited
        twice, and if they diverge the scrubber runs off the end of the clip
        with no error.
        """
        start, end = self._window_s()
        return max(0.0, (end - start) * 1000)

    @property
    def camera(self):
        """Which of the two cameras is live (`_VIEW_SIDE` / `_VIEW_OVERHEAD`)."""
        return self._view

    def toggle_camera(self):
        self._view = 1 - self._view

    def render_review(self, surface, rect, time_ms):
        """Embed the existing geometry/analysis without its modal chrome.

        The workspace owns playback in pitch milliseconds. The old overlay's
        phase clock is only a presentation adapter here; seeking the end also
        completes the ghost fade so a paused endpoint contains all diagnostics.
        """
        if getattr(self, '_review_rect', None) != rect:
            self._review_rect = rect.copy()
            self._frames = {view: self._compute_frame(view)
                            for view in (_VIEW_SIDE, _VIEW_OVERHEAD)}
        duration = self.review_duration_ms()
        fraction = min(1.0, max(0.0, time_ms) / max(1e-9, duration))
        self._elapsed_ms = (self._freeze_end_ms if fraction >= 1.0 else
                            _PHASE_INTRO_END + fraction * (self._replay_end_ms - _PHASE_INTRO_END))
        previous = surface.get_clip()
        surface.set_clip(rect)
        self._draw_view(surface)
        self._draw_stats(surface)
        surface.set_clip(previous)

    def _panel_rect(self):
        if getattr(self, '_review_rect', None) is not None:
            return self._review_rect
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
        self._draw_contact_marker(surface)
        self._draw_spray(surface)
        self._draw_ball(surface, now_s)

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
            # Faintest first: the depth ruler, then the field lines, then
            # the plate on top of both.
            lo, hi = self._depth_range()
            for depth in range(int(lo) + 1, int(hi)):
                if depth == 0:
                    continue
                y = self._project((0.0, float(depth), 0.0))[1]
                pygame.draw.line(surface, (24, 24, 24),
                                 (rect.x, y), (rect.right, y), 1)
            self._draw_field_lines(surface)
            left = self._project((_STRIKE_ZONE_X[0], 0.0, 0.0))[0]
            right = self._project((_STRIKE_ZONE_X[1], 0.0, 0.0))[0]
            front = self._project((0.0, 0.0, 0.0))[1]
            back = self._project((0.0, -_PLATE_DEPTH_FT, 0.0))[1]
            pygame.draw.polygon(surface, gdt.DIM_SOFT, [
                (left, front), (right, front),
                (right, (front + back) / 2), ((left + right) / 2, back),
                (left, (front + back) / 2)], 1)

    def _draw_field_lines(self, surface):
        """The batter's boxes and the foul lines. OVERHEAD only.

        The isotropic window is some 30 ft wide from above and the swing uses
        the middle six; drawn bare, the rest read as the picture having shrunk
        rather than as the field it is. The boxes say where the hitter is
        standing (`bat_path.pivot_ft` puts a right-hander's hands at +1.53 ft,
        inside the third-base box), and the foul lines put the spray ray's
        verdict beside the thing it is a verdict about. They are drawn at
        `spray.FOUL_LINE_DEG` from the apex through `spray.world_direction`,
        the same number and the same frame conversion `is_foul` and the ray
        use, so the ray and the lines cannot disagree about which side of
        fair a ball left on.
        """
        inner = _STRIKE_ZONE_X[1] + _BATTERS_BOX_GAP_FT
        outer = inner + _BATTERS_BOX_W_FT
        mid_y = -_PLATE_DEPTH_FT / 2.0
        front, back = mid_y + _BATTERS_BOX_L_FT / 2.0, mid_y - _BATTERS_BOX_L_FT / 2.0
        apex = (0.0, -_PLATE_DEPTH_FT, 0.0)
        _, (_, v_hi) = self._frame_ft()
        for side in (1.0, -1.0):
            box = [(side * inner, front, 0.0), (side * outer, front, 0.0),
                   (side * outer, back, 0.0), (side * inner, back, 0.0)]
            pygame.draw.polygon(surface, gdt.DIVIDER,
                                [self._project(p) for p in box], 1)
            direction = spray.world_direction(spray.FOUL_LINE_DEG, side)
            # Long enough to leave the top of the frame; the clip trims it.
            length = (v_hi + _PLATE_DEPTH_FT + 1.0) / direction[1]
            end = tuple(apex[i] + length * direction[i] for i in range(3))
            pygame.draw.line(surface, gdt.DIVIDER,
                             self._project(apex), self._project(end), 1)

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
        rx, ry = self._projected_radius(bat_contact.BALL_RADIUS_FT)
        rect = pygame.Rect(round(px - rx), round(py - ry),
                           max(1, round(2 * rx)), max(1, round(2 * ry)))
        pygame.draw.ellipse(surface, gdt.FG, rect)
        # Projected silhouettes can overlap even at true 3D contact.
        # An inner edge keeps the ball distinct without moving its surface.
        pygame.draw.ellipse(surface, gdt.BG, rect, 1)

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
        """The same swept-sphere bat that the contact solver tested."""
        live = state is None
        state = state or self._swing.state_at(self._swing_t(now_s))
        color = color or gdt.FG
        extra = ()
        contact = self._record.replay_contact
        if live and contact is not None and self._replay_progress() >= 1.0:
            extra = (contact.along,)
        for (cx, cy), (rx, ry) in self._bat_ellipses(state, extra):
            pygame.draw.ellipse(
                surface, color,
                pygame.Rect(round(cx - rx), round(cy - ry),
                            max(1, round(2 * rx)), max(1, round(2 * ry))))

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
        if self._elapsed_ms < self._replay_end_ms:
            return
        fade = min(1.0, (self._elapsed_ms - self._replay_end_ms)
                   / _FREEZE_HOLD_MS)
        shade = int(_lerp(0, 90, fade))
        if shade <= 2:
            return
        self._draw_bat(surface, 0.0, state=self._ghost,
                       color=(shade, shade, shade))

    def _draw_contact_marker(self, surface):
        """Where the bat and the ball actually met.

        Falls back to where the barrel arrived when they never met at all — a
        whiff, where the gap between this mark and the ball is exactly what
        the view is for. On contact the clip freezes *at* this instant, so the
        mark sits on the drawn ball rather than somewhere neither the bat nor
        the ball ever reached.
        """
        if self._replay_progress() < 1.0:
            return
        contact = self._record.replay_contact
        point = contact.ball_ft if contact is not None else self._swing.contact_ft
        px, py = self._project(point)
        pygame.draw.circle(surface, gdt.FG, (int(px), int(py)), 9, 1)
        pygame.draw.line(surface, gdt.FG, (px - 12, py), (px + 12, py), 1)
        pygame.draw.line(surface, gdt.FG, (px, py - 12), (px, py + 12), 1)
        self._draw_missed_ball(surface, contact)

    def _draw_missed_ball(self, surface, contact):
        """On a miss, the ball as it was when the barrel arrived — outlined.

        The crosshair beside it marks where the bat got to, and the two
        together are the miss: one moment, two objects, however far apart the
        swing left them. It is also the frame `BALL AT` reports, which is why
        it has to be drawn now that the clip carries on to the plate — without
        it the panel names a depth that is nowhere on screen, and the solid
        ball sitting on the plate is a later instant than the mark.

        Outlined rather than filled, and never on a contact: the solid circle
        is *the* ball, and a second filled one would read as two balls rather
        than as one ball twice.
        """
        rec = self._record
        if contact is not None:
            return
        # A late miss ends *at* the barrel's arrival, so the outline would be
        # a halo around the ball already drawn there. One ball, one circle.
        if rec.clip_end_s <= rec.bat_arrival_s:
            return
        px, py = self._project(rec.ball_at(rec.bat_arrival_s))
        pygame.draw.circle(surface, gdt.DIM, (int(px), int(py)), 5, 1)

    def _draw_spray(self, surface):
        """Where the ball went, drawn from where it was struck.

        OVERHEAD only, and this is what that view was always for — the module
        docstring calls it the view "where pull-versus-oppo contact reads", and
        until the ball had a bearing there was nothing there to read.

        **This is the track the animation flew, not a second answer to the
        same question**, and getting that wrong is what this method is a
        rewrite of. It used to draw `Contact.spray_deg` — the bearing the
        *bat* pointed — under a docstring claiming it was the number the
        animation used. For fouls it never was: a tipped ball keeps a
        fair-looking bearing while the ball itself deflects into foul ground,
        so the ray and the flight disagreed by a median of 40.7 degrees, 45%
        of fouls were drawn as a *fair* ray under a FOUL banner, and on 272 of
        600 the animation put the ball behind the plate while this pointed
        forward. `spray.foul_departure_deg` answers that question once now,
        upstream, and `SwingRecord.flight_path` carries the track that came of
        it.

        Drawn as the real path rather than its tangent, because
        `batted_ball_path` bends the flight by up to 18 ft. Anchored at the
        contact point rather than at home plate, where the animation flies it
        from: the couple of feet between them is not worth a ray that appears
        to leave from somewhere the ball never was.

        Frozen-frame only, like the contact marker and for the same reason —
        until the two have met there is no direction yet.
        """
        if self._view != _VIEW_OVERHEAD or self._replay_progress() < 1.0:
            return
        contact = self._record.replay_contact
        if contact is None:
            return

        deg = self._record.departure_or_spray_deg
        if deg is None:
            return
        points = [self._project(p) for p in self._spray_track_ft(deg)]

        foul = spray.is_foul(deg)
        color = gdt.DIM if foul else gdt.FG
        for a, b in zip(points, points[1:]):
            _draw_dashed_line(surface, color, a, b, dash=7, gap=6)
        a, b = points[0], points[-1]

        side = "PULL" if deg > 0 else "OPPO"
        text = "%s %.0f%s" % (side, abs(deg), _DEGREE)
        if foul:
            text = "FOUL  " + text
        # Labelled where the ray *leaves* the view, not at its end. The ray
        # is drawn long enough to run out of the frame from anywhere inside
        # it, so a label at the end was clipped with the rest and had never
        # once appeared on screen. Anchored a few pixels inside the edge it
        # exits through, on the side of the ray away from the nearer edge.
        rect = self._view_rect()
        ex, ey = _exit_point(a, b, rect.inflate(-24, -24))
        align = 'right' if ex > rect.centerx else 'left'
        x = ex - 8 if align == 'right' else ex + 8
        y = min(max(ey - 6, rect.y + 4), rect.bottom - 18)
        gdt.blit_text(surface, text, self._f()['micro'], (x, y), color,
                      align=align)

    def _spray_track_ft(self, deg):
        """The drawn ray as world-feet points: the ball's own track.

        `SwingRecord.flight_path` is the `BattedBallPath` the animation
        actually flew, in field feet from home plate, so this is a piece of
        that object rather than a line reconstructed from a bearing — which is
        the whole point. `field_x = -world_x` (see `spray.field_angle_deg`) is
        the one conversion; the track is then translated onto the contact
        point, which it can be because a path starts at its own origin.

        Falls back to a straight ray at `deg` when there is no path — a whiff
        has none, and neither does a foul played with the animation switched
        off. That fallback is a *bearing* and says so; it is not a second
        flight model.
        """
        start = self._record.replay_contact.ball_ft
        path = self._record.flight_path
        if path is None or getattr(path, "carry_ft", 0.0) <= 1e-6:
            direction = spray.world_direction(
                deg, spray.spin_for(self._record.handedness))
            return [start,
                    tuple(start[i] + _SPRAY_RAY_FT * direction[i]
                          for i in range(3))]
        # Only the part of the flight the view can hold. The rest is drawn by
        # the animation, on a field.
        span = min(1.0, _SPRAY_RAY_FT / path.carry_ft)
        points = []
        for i in range(_SPRAY_TRACK_SAMPLES + 1):
            fx, fy = path.point_ft(span * i / _SPRAY_TRACK_SAMPLES)
            points.append((start[0] - fx, start[1] + fy, start[2]))
        return points

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
            # On contact, where the ball was struck — the frame on screen. On
            # a miss, where it had got to when the barrel arrived, which is
            # the instant the crosshair marks and `_draw_missed_ball` outlines
            # rather than the last frame, since that clip runs on to the
            # plate. It read `contact_depth_ft` unconditionally, so a late
            # swing showed the ball 6 ft behind the one it drew.
            ("BALL AT", "%+.1f FT" % (rec.replay_contact.depth_ft
                                      if rec.contact is not None else rec.struck_depth_ft)),
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
        # which is what `hit_outcome_manager.contact_metrics` means by it.
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
