"""Top-down ball-flight animation shown after the batter makes contact.

Renders for the brief window between a hit being resolved (in
PitchSimulation._handle_successful_hit) and the outcome banner appearing,
giving the player visual payoff before the SINGLE / FLYOUT / etc. reveal.

Geometric primitives only — no sprite assets. Three layers of motion sell
the read:

  * Trajectory shape — GROUNDER / LINER / FLY / POP_UP, picked from the
    outcome plus the swing's vertical_offset (outs are deterministic;
    hits are weighted-random per outcome). A SINGLE that's a screaming
    liner reads differently from a SINGLE that's a slow roller.
  * Nine-fielder roster — every defender visible. Per-outcome target
    assignment moves the primary fielder toward the ball, a backup
    fielder shifts to coverage (e.g. 2B at second on a SS grounder),
    and everyone else leans a step toward the play. Idle sin-sway
    keeps fielders alive at rest.
  * HR distance — measured from the actual landing point, overlaid once
    the ball clears the wall. Home runs only: a foul that carries past
    the pole gets the same flight but no number, since the distance says
    nothing about a ball that still counts as a strike.

Field geometry is anchored to a 45° foul-line cone. Bases sit on the foul
lines (1B / 3B) and at the apex (2B). All in-play destinations satisfy
|dx| < dy so the ball stays in fair territory.
"""

import math
import random
from dataclasses import dataclass

import pygame

from strikefactor import outcomes
from strikefactor.engine import contact_audio
from strikefactor.gameplay import (
    ball_flight,
    extra_bases,
    ground_roll,
    infield_timing,
    spray,
)

# Aliased because `defense` is also the name of this class's constructor
# argument, which would shadow the module inside __init__.
from strikefactor.gameplay import defense as defense_model

HOME = (640, 670)

# How many animated seconds one real second is shown over. This is the
# *only* place presentation pacing is allowed to diverge from physics:
# everything physical in this file is specified in real feet and seconds
# and passes through `_travel_ms` / `self.time_scale` exactly once, at the
# boundary where it becomes screen motion.
#
# Before this there were two clocks and no constant relating them. Ball
# flight was `HIT_BASE_DURATION_MS * (1.2 - 0.4 * quality)` — around 3.3 s
# to cover 140 ft, an implied 29 mph for a ball struck at 90 — while
# fielders moved at a correct MLB sprint speed against that stretched
# window, so they covered two to three times the ground they ever could.
# `INFIELD_LOW_BALL_RANGE_PX`, `INFIELD_CHASE_RANGE_PX` and
# `FIRST_BASE_GROUNDER_RANGE_PX` all existed to claw that back by hand,
# and all three are gone: a real sprint spent against a real flight time
# reproduces their ~30 ft of infield range on its own.
#
# 1.25 is a mild slow-motion — enough that the eye can follow a fielded
# grounder, close enough to life that the play reads as baseball. Setting
# it to 1.0 gives true real time and is a legitimate choice; what is not
# legitimate is any physical quantity bypassing it.
PRESENTATION_TIME_SCALE = 1.25

# Anisotropic feet→pixels projection. The MLB Gameday "live view" the field is
# styled after is wide and y-foreshortened: home plate near the bottom edge,
# foul lines spreading almost to the bottom corners, wall arc flat across the
# top. We achieve the same look by giving the horizontal axis more pixels per
# foot than the vertical. A real MLB layout in feet (90 ft bases, 330/400 ft
# wall) flows through these scales and ends up rendered wide and shallow.
FT_TO_PX_X = 1.85
FT_TO_PX_Y = 1.10


def _to_screen(x_ft, y_ft):
    """Project a real-field point (feet, math convention +y toward CF) to
    pygame screen coordinates. Single source of truth for the perspective.
    """
    return (HOME[0] + x_ft * FT_TO_PX_X, HOME[1] - y_ft * FT_TO_PX_Y)


def _to_field_ft(screen_pos):
    """Inverse of `_to_screen`: screen pixels back to real field feet.

    The timing model in `infield_timing` reasons entirely in feet and
    seconds, so anything handed to it has to come back through here
    first. Going the other way — doing the physics in pixels — is what
    makes the anisotropic projection leak into the numbers, which is the
    same mistake `_px_per_ft_at` exists to prevent for HR carry.
    """
    return ((screen_pos[0] - HOME[0]) / FT_TO_PX_X,
            (HOME[1] - screen_pos[1]) / FT_TO_PX_Y)


def _ft_dist(dx_px, dy_px):
    """Length of a screen-space displacement, in real feet.

    The projection is anisotropic, so a pixel is not a fixed number of
    feet — it is 1/1.85 ft across and 1/1.10 ft deep. Any speed expressed
    as a scalar in px/ms therefore means two different real speeds
    depending on which way the fielder is running: 40 px/s was 21.6 ft/s
    laterally and 36.4 ft/s straight back, so outfielders going back on a
    ball ran faster than any human has, and infielders moving laterally
    ran slower than a jog. Converting the displacement to feet first is
    what makes one honest ft/s speed mean one honest speed in every
    direction. Same reasoning as `_px_per_ft_at` for home-run carry.
    """
    return math.hypot(dx_px / FT_TO_PX_X, dy_px / FT_TO_PX_Y)


# Bases — 90 ft path. 1B/3B sit at ±90/√2 ft on both axes (the 45° real-field
# foul-line direction); the anisotropic projection then puts them on the
# wider-than-tall *rendered* foul lines.
_BASE_AXIS_FT = 90.0 / math.sqrt(2)   # ≈ 63.64 ft on each axis

BASES = {
    "1B": _to_screen(+_BASE_AXIS_FT, _BASE_AXIS_FT),
    "2B": _to_screen(0.0,            127.0),
    "3B": _to_screen(-_BASE_AXIS_FT, _BASE_AXIS_FT),
}
PITCHERS_MOUND = _to_screen(0.0, 60.5)


def _corner_infielder(side_sign, behind_ft, inside_ft):
    """Corner-IF standing spot, stated the way the position is coached:
    so many feet *behind* the bag (further from home, along the foul
    line) and so many feet *inside* it (toward the middle of the
    diamond, square to that line). `side_sign` is +1 for the 1B, -1 for
    the 3B — the two are mirror images, so only x flips.

    Neither corner plays on their base. Standing on the bag is holding a
    runner, which is a situational alignment, not the default one; with
    nobody on, both play behind the base path and a step or two toward
    the middle. Writing the homes as raw (x, y) feet hid how close to
    the bags they had drifted — the old pair sat ~8 ft off, which under
    this projection is 9 px, so the 8 px fielder body covered the 10 px
    base square and both corners looked glued to their bases.
    """
    along_ft = 90.0 + behind_ft         # distance from home along the foul line
    return _to_screen(side_sign * (along_ft - inside_ft) / math.sqrt(2),
                      (along_ft + inside_ft) / math.sqrt(2))


# Default standing positions for all 9 defenders, in real feet. Distances are
# typical MLB positioning: corner IFs ~100–110 ft, middle IFs ~145 ft, corner
# OFs ~302 ft, CF ~320 ft. The anisotropic projection then stretches the
# layout horizontally on screen — fielders end up "wider apart" than they
# would be under a square top-down camera.
#
# The outfield was at 290/310, about 12 ft shallower than Statcast's average
# alignment. That is small in isolation and not small in effect: 12 ft is
# most of a second of an outfielder's route, spent exactly on the deep balls
# that are the difference between a caught fly and a double. Fly-ball BABIP
# ran .271 against an MLB .120 with the outfield there.
FIELDER_HOMES = {
    "P":  PITCHERS_MOUND,
    "C":  _to_screen(0.0,   -20.0),     # behind plate (slight foul-territory offset)
    "1B": _corner_infielder(+1, 10.0, 18.0),   # ~102 ft, behind the bag toward 2B
    "2B": _to_screen(+50.0, 136.0),     # ~145 ft, between 1B and 2B
    "SS": _to_screen(-50.0, 136.0),     # ~145 ft, between 2B and 3B
    "3B": _corner_infielder(-1, 16.0, 20.0),   # ~108 ft, behind the bag toward SS
    "LF": _to_screen(-103.0, 284.0),    # ~302 ft
    "CF": _to_screen(0.0,    320.0),    # ~320 ft (deepest)
    "RF": _to_screen(+103.0, 284.0),    # ~302 ft
}
ROLES = list(FIELDER_HOMES.keys())
INFIELD_ROLES = ["1B", "2B", "SS", "3B"]
OUTFIELD_ROLES = ["LF", "CF", "RF"]

# Outfield wall — elliptical in real feet (330 ft along foul lines, 400 ft to
# CF), then projected anisotropically. The render semi-axes inherit the same
# x-stretch / y-foreshortening as everything else, so the wall ends up ~1220
# px wide × 440 px tall — a flat arc spanning most of the screen width, sitting
# just inside the 1280 px frame. The polar render radius at screen-angle θ
# (from +x axis) is r(θ) = a·b / √((b·cosθ)² + (a·sinθ)²), evaluated against
# the rendered semi-axes below.
WALL_FT_X = 330.0
WALL_FT_Y = 400.0
WALL_SEMI_X = WALL_FT_X * FT_TO_PX_X   # ≈ 611 px
WALL_SEMI_Y = WALL_FT_Y * FT_TO_PX_Y   # ≈ 440 px

# Visible "depth" of the outfield wall in pygame pixels. The wall is drawn as
# a thin elliptical band rather than a single line so the field reads as a 3D
# structure under the camera-tilt projection. The strip between the outer
# (camera-far / top of wall) and inner (camera-near / wall meets field) arcs
# is the visible wall face. Tuned to roughly match how a 10–12 ft real wall
# would project under our y-foreshortening.
WALL_FACE_HEIGHT_PX = 11

# Foul pole vertical pixel height above the wall corner. Bright accent
# against the dark field — reads unambiguously as "foul pole."
FOUL_POLE_HEIGHT_PX = 28

# Hold on the catch before the outcome banner, in ms. Paced for the eye to
# register the play rather than for realism.
FLYOUT_CATCH_HOLD      =  500

# Flight duration. HOME RUN keeps its own value (calibrated against real
# 4–6 s HR hang times). Generic HIT uses a base value that's quality-scaled
# in _setup_hit. Tuned higher than a screamer's "instant" feel — at q=1
# we end up around 2.6 s, at q=0 around 4 s — so balls don't rocket through
# the air faster than the fielders can read.
HIT_BASE_DURATION_MS = 3300
HR_DURATION_MS = 5000

# HR distance readout, measured from the landing (`duration_ms`). The
# number is the payoff of the play, and showing it mid-flight answers
# the one question the flight is asking — so it is held until the ball
# is down, with a beat after that before it fades up. The ball has
# already dropped out of sight behind the fence a frame or two earlier
# (see `_ball_behind_wall`), so the reveal lands into an empty outfield
# instead of competing with the ball for the eye.
#
# Pacing, not physics, so both are stated directly in ms — the same
# footing as FLYOUT_CATCH_HOLD, and the units `_elapsed` is already in.
# The delay is kept short on purpose: the outcome banner fires at
# landing and the continue prompt with it, so a player who hits a key
# the instant the banner appears can still outrun the reveal.
HR_DISTANCE_REVEAL_DELAY_MS = 350
HR_DISTANCE_FADE_MS         = 220

# Fly-arc peak (px) for HOME RUN. HIT shapes derive their peak from
# LINER_PEAK_RANGE / quality-scaled FLY peak / POPUP_PEAK_RANGE.
HR_PEAK_H = 200
FLY_HIT_PEAK_RANGE = (60, 130)   # quality-scaled inside _setup_hit

# Per-shape landing-distance ranges (ft) for the unified IN_PLAY outcome,
# parameterized by quality. Quality maps the random sample inside the
# range — q=0 lands near the min, q=1 near the max — and a small uniform
# spread keeps each contact looking distinct. The lateral angle is picked
# uniformly across fair territory; whether the contact resolves as an out
# or a hit depends on whether a fielder can route to the landing point
# in time. Ranges intentionally span the realistic depth of each shape:
# GROUNDER goes from weak rollers (~45 ft) out through the IF and into
# shallow OF (~215 ft); LINER from short flares to wall liners; FLY from
# shallow OF blooper through to warning-track shots; POP_UP stays shallow
# regardless of quality.
IN_PLAY_LANDING_FT = {
    "GROUNDER": (45, 215),
    "LINER":    (130, 295),
    "FLY":      (165, 365),
    "POP_UP":   (80, 160),
}
# `IN_PLAY_ANGLE_MIN` / `IN_PLAY_ANGLE_MAX` are **gone**. They were a 50°–130°
# cone that a ball in play was drawn *uniformly* across, and its own comment
# admitted the problem: the pull/oppo inequities "belong to the swing model,
# not the landing pick" — and then it drew `random.uniform`. The swing model
# supplies the angle now (`spray`), so there is no distribution left here to
# bound.
#
# The cone was also a conservative subset of fair territory, 5° inside each
# real foul line, which is exactly where a ball down the line lands and where
# doubles come from. Fair balls are bounded by `spray.FOUL_LINE_DEG` already,
# so all that is needed is a hair of inset to keep a ball landing at exactly
# 45.0° from being drawn on the line itself.
FAIR_DRAW_MARGIN_RAD = math.radians(0.5)

# Foul-ball animation (cosmetic — the outcome is already a settled foul).
# Direction is the ball's own bearing (`spray`), the same one a fair ball gets.
#
# CRITICAL: these are the *actual* foul lines, per coordinate space — NOT
# the 50°/130° IN_PLAY fair cone, which is a conservative fair subset. In
# real-field feet (the _polar_point_ft space) the foul lines sit at 45°/135°.
# In screen space (the _polar_point space) the anisotropic projection
# flattens them to atan2(FT_TO_PX_Y, ±FT_TO_PX_X) ≈ 30.7°/149.3°. Aiming
# "just past 130°" in either space lands well inside rendered fair
# territory — a ball that looks like a fair home run but reads FOUL.
FOUL_LINE_FIELD_LEFT_RAD   = math.radians(135)   # 3B/LF line, real-field feet
FOUL_LINE_FIELD_RIGHT_RAD  = math.radians(45)    # 1B/RF line, real-field feet
FOUL_LINE_SCREEN_RIGHT_RAD = math.atan2(FT_TO_PX_Y, FT_TO_PX_X)   # ≈ 30.7°
FOUL_LINE_SCREEN_LEFT_RAD  = math.pi - FOUL_LINE_SCREEN_RIGHT_RAD  # ≈ 149.3°
# `FOUL_OFF_MIN_RAD` is gone: it was the floor of a severity ramp that started
# at "barely mistimed", and a ball hooked a degree past the pole has to be able
# to draw a degree past the pole.
FOUL_OFF_MAX_RAD = math.radians(45)
FOUL_LANDING_FT = {
    "GROUNDER": (25, 110),
    "LINER":    (90, 260),
    "FLY":      (110, 330),
}
FOUL_POP_BACK_FT = (15, 50)     # straight-back pop radius behind the plate
FOUL_FLIGHT_MS = {
    "GROUNDER": 1600,
    "LINER":    2200,
    "FLY":      3000,
    "POP_UP":   2700,
}
FOUL_HOLD_MS = 700              # dead-ball beat after the foul lands
# "Foul home run" gate: well-barreled (quality) and only barely mistimed
# (severity) fly/liner contact carries past the foul pole, with the HR
# distance overlay reused for the tease.
FOUL_HR_QUALITY_MIN   = 0.75
FOUL_HR_MAX_SEVERITY  = 0.5
FOUL_HR_OFF_RAD = (math.radians(2), math.radians(9))

# Legacy alias retained for the fallback branch in _pick_hit_landing —
# callers that don't pass IN_PLAY (or HOME RUN) drop through here.
HIT_LANDING_FT = {
    "LINER": IN_PLAY_LANDING_FT["LINER"],
    "FLY":   IN_PLAY_LANDING_FT["FLY"],
}

# SINGLE / DOUBLE / TRIPLE used to be four retrieve-time thresholds here —
# `RETRIEVE_TIME_SINGLE_MAX_MS = 2800`, `..._DOUBLE_MAX_MS = 4200` and two
# wall variants — measured in animated ms from landing to the fielder
# securing the ball. They are gone; see `_resolve_extra_bases` and
# gameplay/extra_bases.py, which race the runner against the throw.
#
# Two things were wrong with them and both are worth remembering. They
# could see how *long* a fielder took but not where they ended up, so a
# bloop run down in the shallow outfield and a ball retrieved 320 ft away
# scored identically. And they were stated on the presentation clock, which
# made them silently dependent on pacing: unifying that clock moved every
# flight time and took triples from 8% of hits to 23% with the constants
# untouched. A threshold on an animated duration is not a baseball fact.
#
# Everything about what the ball does after it lands — how fast it is
# going when it gets there, how it bounces, how far it rolls — now lives in
# `gameplay/ground_roll.py`, in real feet and seconds. This file converts
# it to screen motion once, in `_init_ball_on_ground`.
#
# Six constants died to make that possible and are worth naming, because
# every one of them was a physical quantity wearing a render unit:
#
#   SHAPE_LAND_FACTOR           landing speed as a fraction of the flight
#                               average — 0.35 on a fly, which dropped the
#                               ball from 78 ft/s to 27 ft/s in one frame.
#                               A real fly ball lands at 52 ft/s, and it is
#                               the same 52 ft/s whether it was struck at
#                               75 mph or 108, because it is at terminal
#                               velocity by then.
#   ROLLING_DECEL_FT_S2 = 16.0  twice the high end of real grass. It had to
#                               be, to stop a ball that arrived at a third
#                               of its true speed.
#   BOUNCE_INITIAL_DURATION_MS  a hop's air time as a fixed 620 *animated*
#                               ms, independent of how hard the ball hit
#                               the ground. A hop's duration is 2u/g.
#   BOUNCE_COR / _HEIGHT_FRAC / a bounce schedule in pixels with rolling
#   _HEIGHT_MAX_PX              friction running underneath it, so the ball
#                               was braked by the grass while airborne.
#   BOUNCE_HORIZONTAL_RETENTION one flat 4% per bounce, which cannot tell a
#                               line drive skipping off the grass from a fly
#                               ball being gripped by it. Nearly all the
#                               horizontal loss is at the *first* contact
#                               and its size is set by the descent angle.
#
# Together they produced the reported bug: a ball landed in the outfield,
# lost half its speed instantly, took three cosmetic hops while friction
# ate the rest, and stopped 14 ft (median, over 500 fly balls) from where
# it touched down. `tests/test_ground_roll.py` fails if one comes back.
#
# Glove reach above the ground, in feet. A ball higher than this is over
# the fielder, not in their glove — which never came up when the first hop
# was a 3 px cosmetic bump, and matters now that a fly ball's first bounce
# clears 7 ft.
GLOVE_REACH_FT = 8.0

# Resolution and horizon of the ball's forward forecast (`_forecast_ball`),
# on the animated clock. 80 ms is finer than the ~30 ft a sprinting fielder
# and a rolling ball close on each other in one sample, and 90 steps covers
# 7.2 animated seconds — past the longest roll `ground_roll` produces, so
# the search never runs out of path before it runs out of fielder.
FORECAST_STEP_MS  = 80.0
FORECAST_MAX_STEPS = 90

# Wall containment. Landings clamp inside the wall arc so a deep gapper
# doesn't visually start past it. Rolling balls clamp closer to the wall
# and reflect their radial-outward velocity component on contact, with
# restitution < 1 so the carom loses energy.
LANDING_WALL_MARGIN_PX  = 25
BALL_WALL_MARGIN_PX     = 8
# The ball's margin in normalized-ellipse units — √((dx/a)² + (dy/b)²),
# which is 1 on the wall — since that is the form the containment step
# works in. This is the line a live ball is *held* at, and every place
# that puts a ball against the fence has to use this one expression of
# it: written as a radial `wall_r - BALL_WALL_MARGIN_PX` instead it is a
# different line at every angle but dead centre, because the ellipse's
# radius runs 440–611 px while the normalization is against the smaller
# semi-axis. `_maybe_trigger_in_flight_wall_impact` did exactly that, and
# so parked the ball a shade *outside* the boundary on every carom that
# was not to straightaway centre.
#
# It is deliberately *not* the boundary of the park — see
# `_point_outside_wall`, which tests the fence itself.
BALL_WALL_LIMIT_NORM    = 1.0 - BALL_WALL_MARGIN_PX / min(WALL_SEMI_X,
                                                          WALL_SEMI_Y)
# Fielder containment lives with the fielder constants
# (FIELDER_WALL_MARGIN_PX, below BODY_RADIUS_PX).
#
# Real fence height. A ball beyond the wall is hidden from a camera on
# this side of it only while it is below the top of the fence — see
# `_ball_behind_wall`.
WALL_HEIGHT_FT          = 10.0
# Coefficient of restitution for wall contact during the rolling phase.
# Real ball-on-padded-wall COR is ~0.45–0.55; we run a bit under that
# (0.45) so a screamer still loses meaningful energy on impact but
# rebounds with enough momentum to visibly roll back into play instead
# of dying at the foot of the wall. The "fielder in shallow OF picks it
# up instantly" concern that justified the old 0.20 is now handled
# by self._wall_hit forcing a minimum-XBH classification regardless of
# how quickly the carom returns to a defender, so the restitution can
# be tuned for visual realism.
WALL_BOUNCE_RESTITUTION = 0.45

# In-flight wall hits — a subset of high-quality FLY/LINER contacts are
# routed past the wall so they strike the wall face on the fly rather
# than landing in the OF and rolling. Real MLB has lots of these (gappers
# off the wall, line drives that clang the corner) and they're a major
# source of doubles and triples — without this branch, the only way a
# ball reaches the wall is by rolling there post-landing, which dampens
# the variance and produces too many "long-route singles".
#
# Quality-gated: ramps from 0 probability at q=0.5 up to WALL_HIT_PROB_MAX
# at q=1.0. GROUNDER never reaches the wall in the air; POP_UP is shallow
# by definition — both shapes are excluded.
# Carry a ball has to have to reach the fence at all. The park is deepest
# to centre at 400 ft and this sits just under it, so a ball qualifies as
# a wall candidate only if it was struck hard enough to reach the fence
# somewhere. Whether it actually does depends on the angle picked next —
# down the line the wall is nearer, so a ball with less than this never
# reaches it anywhere and a ball with more may still land in front of a
# deep centre field.
#
# `WALL_HIT_QUALITY_THRESHOLD = 0.50` / `WALL_HIT_PROB_MAX = 0.22` used to
# decide this by a roll on contact quality. See _setup_hit for why that
# was over-firing.
WALL_REACH_FT              = 380.0
# Carry past the wall (ft) for wall-candidate landings — picks where the
# ball *would have* landed if the wall weren't there. The arc is computed
# all the way to that point, but in-flight detection (see
# _maybe_trigger_in_flight_wall_impact) ends the flight when the shadow
# crosses the wall ellipse. Squared bias keeps most carries small (impact
# low on the wall face) with the occasional deep one (impact higher up).
WALL_HIT_CARRY_FT_MIN    = 5.0
WALL_HIT_CARRY_FT_MAX    = 35.0
WALL_HIT_CARRY_BIAS_EXP  = 2.0
# How far up the fence face a ball off the wall may strike it, as a
# fraction of the fence's own height. A **bound that is solved for**, not
# a shape parameter: `_wall_impact_peak_cap` inverts the arc for the peak
# that puts the ball exactly here at the moment its ground point reaches
# the fence, and caps the shape's own peak at that.
#
# It replaced `WALL_HIT_FLY_PEAK_SCALE = 0.60`, a scale on the FLY peak
# meant to do this same job, which could not: how high the ball is when it
# reaches the fence is a consequence of where the arc was *aimed* and how
# the flight is *paced*, and a scale on the peak can see neither. Measured
# over 162 wall balls, **54% were drawn above the top of the fence at the
# instant they struck it** — median 12 px against an 11 px fence, out to
# 27.8 px, two and a half fence-heights up — and were then planted on the
# grass in one frame. That is the reported "ball goes over the wall, then
# clips back into play". It was always possible (the same measurement on a
# linear flight gives median 7.8 px, max 18.2) but the decelerating flight
# ease made it the common case: the last 2% of the path is covered over
# the last 10% of the flight *time*, and the arc's height is keyed to the
# time, not the path.
#
# The cap is written shape-independent. `_is_wall_candidate` admits FLY
# and LINER, but `ball_flight` caps a liner's carry at ~320 ft against
# WALL_REACH_FT's 380, so only FLY has ever reached it — which is why
# nobody noticed that the old scale was applied to FLY alone.
WALL_IMPACT_MAX_HEIGHT_FRAC = 0.85
# Restitution on the post-impact rolling velocity for in-flight wall
# contact. Real outfield walls have COR ~0.45–0.55; matching that lets a
# screaming liner visibly carom off the wall and roll back into play, the
# way it does in real video. The velocity is also flipped inward so the
# ball rebounds toward the fielder rather than continuing outward (and
# clipping further into the on-ground wall-containment logic). Previously
# 0.15 — at that value the ball lost nearly all momentum on impact and
# friction killed it before it could clear the wall, producing the
# "bounces in place at the wall then dies" look. The _wall_hit XBH
# override prevents a fast carom from getting misclassified as a single,
# so the restitution can be tuned for visual realism.
WALL_HIT_FLIGHT_RESTITUTION = 0.50

# Quality thresholds for grounder bounce profile (see _grounder_peaks).
SQUIBBLER_QUALITY_THRESHOLD = 0.32
SHARP_QUALITY_THRESHOLD     = 0.55

# Grounder bounce profile — first-hop peak (px above ground at apex) and
# per-bounce spacing (px of travel covered by one hop) keyed by quality
# band. Sharp contact short-hops to roughly chest height (~12 px ≈ 4 ft at
# the field render scale where a 16-px-tall fielder represents ~6 ft) and
# travels ~40 px between impacts; squibblers barely lift the ball and take
# short, frequent hops. Per-bounce height decay is GROUNDER_BOUNCE_COR_SQ
# (~real grass COR² of 0.35–0.45), so each hop retains ~40% of the previous
# peak; a 2-px floor keeps the last hops visible as hops instead of
# flattening into a roll prematurely. Bounce count is derived from travel
# distance ÷ spacing so the ball touches grass between every hop regardless
# of how far it goes — without distance scaling, a long sharp grounder
# rendered as a single 32-px arc spanning the full flight and read as a
# low fly ball clearing the infielders.
GROUNDER_BOUNCE_PROFILE = {
    "squibbler": {"first_peak_px": 5.0,  "spacing_px": 24.0},
    "medium":    {"first_peak_px": 8.0,  "spacing_px": 32.0},
    "sharp":     {"first_peak_px": 11.0, "spacing_px": 40.0},
}
GROUNDER_BOUNCE_COR_SQ      = 0.40
GROUNDER_BOUNCE_MIN_PEAK_PX = 2.0
GROUNDER_BOUNCE_MIN_COUNT   = 3
GROUNDER_BOUNCE_MAX_COUNT   = 8

THROW_PEAK_H = 30     # low arc on infield throw
LINER_PEAK_RANGE = (25, 40)
POPUP_PEAK_RANGE = (270, 320)

# Hit shape weights — drives the "every SINGLE looks different" feel.
SHAPE_WEIGHTS = {
    "SINGLE":   [("LINER", 0.50), ("GROUNDER", 0.30), ("FLY", 0.15), ("POP_UP", 0.05)],
    "DOUBLE":   [("LINER", 0.60), ("FLY", 0.40)],
    "TRIPLE":   [("FLY", 1.00)],
    "HOME RUN": [("FLY", 1.00)],
}

# HR carry past the wall, in REAL FEET (converted to px per-angle via
# _px_per_ft_at). Most HRs barely clear; only the highest quality contact
# carries deep. The displayed distance is computed from the actual landing
# position rather than a quality-only mapping, so the number on screen
# always matches where the ball lands. The biased roll
# (carry = min + (rand**EXPONENT) * range) skews most carries toward zero —
# "just-cleared" wall-scrapers — so blasts are the rare exception.
#
# Calibrated against MLB home-run distances (mean ~400 ft, p50 ~399,
# p75 ~417, p90 ~433, ~5% beyond 440). Carry was previously expressed in
# pixels, which made it 17% longer in feet at centre field than down the
# line for the same constant, and combined with the old angle clamp it
# produced a 392–476 ft distribution averaging 423 — every home run a
# no-doubter.
HR_CARRY_MIN_FT           = 0.0
HR_CARRY_BASE_RANGE_FT    = 16.0
HR_CARRY_QUALITY_BONUS_FT = 45.0
HR_CARRY_BIAS_EXPONENT    = 3.5

# Fielder motion. Constant-velocity with acceleration/deceleration phases —
# exponential easing produced a "snap to position then freeze" look that
# read as unnatural. Real fielders ramp up, cruise, and decelerate.
#
# Stated in real feet per second, and it is the only place fielder speed is
# stated at all. It used to be `FIELDER_MAX_SPEED_PX_MS = 0.040` — px per
# *animated* ms — which folded three separate things into one number: the
# real sprint speed, the anisotropy of the projection, and the animation's
# time dilation. `_travel_ms` now unfolds them at the point of use.
#
# MLB average Sprint Speed. Note this one is legitimately a top speed: it
# is spent against `FIELDER_ACCEL_TIME_S`, so a fielder covering 30 ft
# averages well under it. (Contrast the batter-runner, where using Sprint
# Speed as an average is the trap `infield_timing` documents.)
FIELDER_SPRINT_FT_S = 27.0
# Spread of batter-runner top speed, ft/s. MLB is roughly 23 (slow) to 30
# (elite) around a 27 mean, so ~1.8 puts almost everyone in that band.
RUNNER_SPRINT_SIGMA_FTS = 1.8
# Difficulty, converted from `out_probability_modifier` into seconds on the
# runner's clock. At 0.5 the spread across ROOKIE (0.7) to HALL_OF_FAME
# (1.6) is -0.15 s to +0.30 s of runner time — enough to move close plays
# without letting difficulty overrule the physics on routine ones.
DIFFICULTY_SECONDS_PER_MODIFIER = 0.5
# Real seconds to ramp from a standing start to full sprint.
FIELDER_ACCEL_TIME_S    = 0.22
FIELDER_DECEL_RADIUS_PX = 28.0          # start slowing within this radius of target
FIELDER_DECEL_FLOOR     = 0.20          # never below 20% speed in decel zone
# See-react-step, in real seconds: a real fielder needs 200–400 ms before
# the first stride. Jittered per fielder so they don't all start in sync.
REACTION_DELAY_MIN_S    = 0.200
REACTION_DELAY_MAX_S    = 0.380
# Per-role reaction-delay bonus on top of the base. The pitcher just
# released the ball — in their follow-through they're off-balance,
# falling toward the first-base side with their glove nowhere near
# ready, and need extra time to recover before reacting to contact.
# The catcher starts in a deep crouch behind the plate and similarly
# needs more time. Both end up routinely beaten to grounders by IFs,
# which keeps the realistic "comebackers only" balance for the pitcher
# and stops the catcher claiming popups they'd never actually take.
#
# The pitcher's bias is deliberately larger than a pure see-react
# figure: at 0.90 s on top of the 0.20–0.38 s base they're frozen at the
# mound for ~1.1–1.3 s, which is about how long recovery from the
# follow-through actually takes. A ball hit hard up the middle covers
# the 60 ft to the mound well inside that window, so it goes past a
# pitcher who hasn't squared up yet — the real reason comebackers are
# hits far more often than outs.
#
# These are now the real seconds that comment always claimed. Charged
# against the old dilated clock the same numbers bought roughly 0.4 s of
# real recovery, so the pitcher was reacting more than twice as fast as
# documented — the honest clock is what makes the figure mean what it says.
ROLE_REACTION_BIAS_S = {
    "P": 0.90,
    "C": 0.32,
}

# Chance the pitcher cleanly handles a ball hit back through the box,
# as (soft contact, hard contact) — interpolated by contact quality and
# rolled once per batted ball.
#
# Geometry alone can't express this. A ball hit straight up the middle
# *always* passes within the pitcher's intercept reach, so a purely
# positional model converts every one of them into a comebacker out.
# Real pitchers are compromised fielders: they field the weak roller
# and the soft one-hopper routinely, and they almost never turn a
# scorched grounder or a liner up the middle into an out — those go
# through the box for a base hit. When the roll fails, the pitcher is
# dropped from the intercept pool for the whole play (see
# _eligible_intercept_pool), so the ball passes through them and the
# middle infielders get their normal chance to range over and cut it
# off. Shapes absent from this table (FLY, POP_UP) are already handled
# by the lift/eligibility gates and never roll.
PITCHER_CLEAN_FIELD_PROB = {
    "GROUNDER": (0.95, 0.15),
    "LINER":    (0.35, 0.04),
}

# Per-role maximum intercept range, in real feet from home position.
# Pitchers and catchers have very limited mobility off the bat — pitchers
# because they're in follow-through, catchers because they're crouched
# behind the plate with gear. They only field balls that come close to
# them; anything beyond this radius gets called off / handed to an
# infielder. Without this constraint the pitcher sat at the geographic
# center of the diamond and intercepted half the grounders, since their
# perpendicular foot on most trajectories is only a step or two away.
#
# Stated in feet rather than the old 28/32 px because a pixel radius is
# not a circle on the field: under the anisotropic projection the same
# 28 px bought 15 ft of lateral range but 25 ft straight back, so the
# pitcher's zone was an ellipse pointing at centre field.
ROLE_MAX_INTERCEPT_DIST_FT = {
    "P": 15.0,
    "C": 17.0,
}

# The middle infield. Their zone is the one the ball crosses on its way to
# centre field, so they are the pair whose ranging reads wrong first.
MIDDLE_INFIELD_ROLES = ["2B", "SS"]

# `INFIELD_LOW_BALL_RANGE_PX = 55` and `INFIELD_CHASE_RANGE_PX = 130` used
# to live here, capping how far an infielder could reach and run at a
# GROUNDER or LINER. Both are gone, and neither was physics — they were
# corrections for the clock. A fielder spending a real 27 ft/s sprint
# against a real ~1.5 s grounder now covers about 30 ft on his own, which
# is what the 55 px cap was hand-setting, so the cap has nothing left to
# do. See PRESENTATION_TIME_SCALE.
#
# What remains capped is genuinely positional, not temporal:
# ROLE_MAX_INTERCEPT_DIST_PX (a pitcher in his follow-through and a
# crouched catcher really do have tiny fielding zones) and
# PITCHER_CLEAN_FIELD_PROB (a pitcher really is a compromised fielder on
# a ball hit at him). Those model the players; the deleted pair modelled
# the renderer.

# Decel radius applied once the ball is past a chasing infielder. Wide, so
# they coast down over ~90 px instead of braking on the spot — the whole
# point of the chase is that it ends by being beaten, not by stopping.
CHASE_PULL_UP_DECEL_PX = 90

# How close a range-capped fielder has to get to their pull-up spot before
# they stop breaking at it and start drifting with the ball instead (see
# `_pursuit_point`). Small on purpose: this is "arrived", not "nearly
# there" — leaving the break early would cut the sprint that sells the
# attempt short.
PULL_UP_ARRIVED_PX = 6

# Speed a pulled-up fielder drifts at, as a fraction of their sprint. They
# have already been beaten by the ball; what's left is shading toward its
# line and trailing it, which is a jog. Left at full speed the drift reads
# as a second sprint — and since the ball is usually still short of them
# when they pull up, that sprint is briefly *backwards*, toward the plate.
PULL_UP_DRIFT_SPEED_FRAC = 0.45

# Per-role post-landing chase radius. Pitchers and catchers have small
# fielding zones — a pitcher in real baseball fields comebackers and
# slow rollers right at the mound, but never chases a ball that's
# already in the IFs' coverage. Catchers similarly only range out for
# bunts and short tappers. Other roles inherit POST_LAND_CHASE_RADIUS_PX
# (220 px), which keeps the IF/OF cooperative chase wide enough to
# cover the diamond.
ROLE_POST_LAND_CHASE_RADIUS_PX = {
    "P": 40,
    "C": 35,
}

# Per-role override for `_ball_past_fielder` — the radial distance past
# the fielder's home (measured from HOME plate) at which they bail out
# of the chase and defer to a deeper defender. Pitchers and catchers
# use 0: the moment the ball is radially past their home, they hand
# off to the infielders. Other infielders keep the default 30 px so
# they don't bail out mid-range. Outfielders are exempt (see
# `_ball_past_fielder` — past an OF is the wall, not another defender).
ROLE_BAIL_OUT_BEHIND_PX = {
    "P": 0,
    "C": 0,
}
SWAY_AMPLITUDE          = 1.6
SWAY_FREQUENCY          = 0.0018        # rad/ms
LEAN_BASE_PX            = 5.0           # initial lean magnitude
LEAN_GROWTH_PX          = 18.0          # additional lean magnitude as play progresses

BODY_RADIUS_PX          = 8
BODY_COLOR              = (220, 220, 220)
GLOVE_COLOR             = (255, 200, 100)

# The "!" that pops over a fielder the instant they are charged with an
# error. Until now the only thing that said an error had happened was the
# banner, several seconds later and after the runner had already been put
# on base — so a muff read on screen as "the ball bounced oddly" and a
# ball through the shortstop read as an ordinary base hit. This is the one
# thing on screen that reports `is_error` before the banner does, and it
# is drawn over the fielder who actually made it (`_error_role`), which is
# not always the primary: a ball through the SS is retrieved by the LF,
# and the LF did nothing wrong.
#
# Stated in real seconds and brought onto the animated clock by `_anim_ms`
# like every other duration in this file, so it lasts the same wall-clock
# time whatever time scale the play is running at.
ERROR_MARK_HOLD_S       = 1.10          # full brightness before the fade
ERROR_MARK_FADE_S       = 0.45
ERROR_MARK_POP_S        = 0.16          # rise from the head, on appearance
ERROR_MARK_RISE_PX      = 6.0
ERROR_MARK_OFFSET_PX    = 17            # above the body's centre
# The amber "reached, but not earned". Taken from the shared palette rather
# than restated: it is also the pitchviz trail dot
# (pitch_simulation._finalize_batted_ball) and the ScoreKeeper colour, and
# this comment used to *list* those copies, which is how you can tell there
# were four of them.
ERROR_MARK_COLOR        = outcomes.ERROR_COLOR

# How close to the fence a fielder may get, and the *only* thing that
# stops them leaving the park: every target a defender is given is the
# answer to a physical question — where the ball is, where it will land,
# where it will come to rest — and a wall-candidate or HOME RUN
# `_hit_end` is beyond the fence by construction. Nothing downstream of
# that has any notion of a boundary, so an outfielder chasing one ran
# straight through the wall into the black.
#
# Containment is applied at the mover (`_step_fielder`) and once more
# over every fielder at the end of `update`, rather than at each of the
# half-dozen places a target is set. The targets are allowed to be off
# the field — a fielder running at a ball that leaves the park is what
# a fielder does — it is only the body that isn't.
#
# WALL_FACE_HEIGHT_PX is the inward offset from the wall ellipse (which
# is the *top* of the fence, the camera-far edge) down to where the wall
# meets the grass, so it is what puts a fielder at the base of the
# fence; the body radius keeps their whole marker on the field.
FIELDER_WALL_MARGIN_PX  = WALL_FACE_HEIGHT_PX + BODY_RADIUS_PX

# Ball sprite. Deliberately *not* to scale: a real baseball is ~0.24 ft
# across against a fielder's ~2 ft of shoulder, which at this projection
# would be a 2 px dot — invisible while moving, and the ball is the one
# thing on screen the eye has to track. So it stays oversized; the only
# question is by how much. At radius 5 it read as 0.63x the fielder's
# width, which made the ball look like a thrown melon. Radius 4 keeps it
# comfortably trackable at 0.5x — still far larger than life, but the
# fielders now clearly dwarf it, which is the relationship that sells the
# scale of the field.
#
# Purely cosmetic: nothing reads this. The catch and secure distances
# (INTERCEPT_REACH_PX, SECURE_RADIUS_PX) are gameplay tuning measured
# between body and ball *centres*, so resizing the sprite cannot change
# any outcome.
BALL_RADIUS_PX          = 3
BALL_SHADOW_W_PX        = 8             # ellipse, flattened by the camera tilt
BALL_SHADOW_H_PX        = 3

# Hit chase phase. After the ball lands on a SINGLE/DOUBLE/TRIPLE, the
# primary fielder keeps running until they reach the ball, then the
# animation pauses. SECURE_RADIUS is the body+ball overlap distance
# (roughly the body radius) at which the ball is "secured." No timeout —
# friction guarantees the ball stops eventually, and the fielder converges
# afterwards; we let the play run to a natural close rather than truncating.
SECURE_RADIUS_PX        = 14
# How far in front of their home position a fielder has to have come before
# the play counts as a charge rather than a set throw. See _play_geometry.
CHARGING_MARGIN_FT      = 2.0

# In-flight interception tuning. INTERCEPT_REACH_PX is the screen-space
# distance from a fielder's body to the ball at which an in-flight catch
# fires; tuned slightly above SECURE_RADIUS_PX so a fielder positioned
# in the ball's path will catch even if their step is half a beat off,
# but a fielder a clean half-stride away cleanly misses. INTERCEPT_MAX_LIFT_PX
# caps the ball-above-ground distance at which a fielder can still reach
# — anything higher than ~6 ft (jump + glove extension) is over their
# head and goes through. INTERCEPT_GRACE_S is the timing slack used by
# fielder routing to decide whether a fielder can plausibly make a play
# on the path (so they actually run a route, instead of standing at home
# watching).
INTERCEPT_REACH_PX      = 12
# Vertical reach of a fielder's glove above the ground (px ≈ ft × 2.5
# at the render scale). A real player can catch up to ~9–10 ft with
# jump + glove extension; we use 25 px (~10 ft) so jumping liners are
# catchable but balls passing genuinely overhead are not. Replaces the
# old INTERCEPT_MAX_LIFT_PX=80 which was so loose that a fly ball at
# 6-ft mid-flight height registered as a catch when the *rendered*
# ball position happened to overlap a fielder's body in screen space —
# what we now detect as "ball flies over the pitcher and is caught."
INTERCEPT_MAX_LIFT_PX   = 25
# Real seconds — it is a fielder's margin for error, so it belongs on the
# same clock as their sprint and their reaction, not on the render's.
INTERCEPT_GRACE_S       = 0.22

# Throw-to-1B sub-animation, in real seconds.
#
# The hold and the throw are no longer fixed: `_trigger_in_flight_intercept`
# takes them from the `PlayTiming` that decided the play, so the ball leaves
# the fielder's hand after the modelled release time and is in the air for
# the modelled flight time. That is what stops the picture and the verdict
# from being two different plays — a throw from deep in the hole now
# visibly takes longer than a throw from right on top of the bag, and it is
# longer by exactly the amount that lost the runner.
#
# These remain as the fallback for the paths that have no timing to read
# (an unassisted carry never throws) and as the floor on the pre-throw
# hold, so a fielder always visibly gathers before releasing.
GO_FIELD_HOLD_S         = 0.28
GO_THROW_S              = 0.76
GO_CATCH_HOLD_S         = 0.42

# ---- First-base coverage --------------------------------------------------
# The standing spot at the bag (a step to the home-plate side of it, which
# is where a cover man actually sets up). Single source of truth — this
# used to be re-derived inline in three places.
FIRST_BASE_BAG_POS = (BASES["1B"][0] - 7, BASES["1B"][1] + 5)

# Who covers first base, in strict preference order — a priority list,
# not a race. The bag belongs to the 1B; when the 1B is the one fielding
# the ball, the pitcher breaks over to take the throw (the canonical 3-1).
# The 2B covering first is a busted play in real baseball — it happens,
# but only when nobody ahead of them can get there — so they sit at the
# end of the list instead of competing on ETA.
#
# This was an ETA race with preference bonuses, and it lost to its own
# tuning: the pitcher's 0.90 s follow-through bias (ROLE_REACTION_BIAS_S)
# went into their ETA, which pushed them past COVER_IN_TIME_BUDGET_S on
# about a third of right-side grounders and handed the bag to the 2B —
# who then abandoned balls hit into their own zone to go stand on it.
# See `Fielder.break_delay_s` for the other half of that fix.
COVER_ROLE_PRIORITY = ["1B", "P", "2B"]

# How long a fielder will stand holding the ball waiting for the cover man
# to reach the bag before throwing anyway, in real seconds. Real infielders
# double-clutch when first isn't covered yet; without a cap, a badly-timed
# play could stall the whole animation.
GO_COVER_WAIT_MAX_S = 1.40

# A cover man is "in time" if they can reach the bag before a maximally
# delayed throw would land on it. This is the veto on COVER_ROLE_PRIORITY:
# the point of the whole mechanism is that the bag is occupied when the
# ball arrives, and a stylistic preference must never outrank that.
#
# It is measured from the moment the ball is *fielded*, not from contact,
# and _route_first_base_cover adds the time still left before that moment.
# Compared naively against an ETA from contact it vetoes everybody: the
# 60 ft from the mound to the bag is ~2.2 s of fielder motion, well past
# this budget on its own, so the pitcher failed every 3-1 and the bag fell
# through to the 2B. A cover man has the whole flight of the ball to get
# there, and that is most of the time they get.
COVER_IN_TIME_BUDGET_S = GO_COVER_WAIT_MAX_S + GO_THROW_S

# Extra budget the fielder already running to the bag gets, so the job
# doesn't change hands over a few ms of jitter. Without it two candidates
# either side of the in-time line can trade the assignment frame to frame
# and both end up jogging in place.
COVER_INCUMBENT_BONUS_S = 0.25

# How far the 1B may range from their home position to play a GROUNDER,
# in real feet. Their home already sits ~13 ft behind and inside the bag,
# so this is "how much further off it will they go" — deliberately tight,
# because every foot the 1B ranges is a foot they have to sprint back
# before a throw arrives, and they start that sprint from off the bag.
# Balls outside it belong to the 2B/pitcher and the 1B stays home to take
# the throw. Grounder-only: there's no throw to beat on a pop-up or liner,
# so the 1B is free to range on those.
#
# This is the one range cap that survived the clock unification, and it is
# kept because it is not a clock correction: it encodes a *responsibility*
# (the 1B owes the bag) that stays true at any pacing. It was 55 px, which
# under the anisotropic projection meant 30 ft of lateral ground but 50 ft
# straight in — the same cap buying wildly different range depending on
# which way the ball went. Stated in feet it is one distance.
FIRST_BASE_GROUNDER_RANGE_FT = 30.0

# How far from home a ground ball can be fielded and still be an infield
# play — roughly the outfield grass line, a step behind the deepest
# middle-infield alignment (~145 ft). Past it there is no throw to first
# worth making: the runner is nearly there, and the defense's job is to
# hold them to a single. A grounder fielded beyond this goes to the
# base-advance race instead, whoever picked it up.
INFIELD_PLAY_MAX_FT = 160.0

# Post-landing chase radius. Wider than the in-flight chase commitment
# because once the ball is on the ground, every nearby defender pitches
# in (the closest one secures it). 220 px covers the IF/OF boundary
# so an OF in shallow position will pick up a grounder that rolled
# past the IFs, instead of leaving the IF to chase it 200 ft into
# their own zone.
POST_LAND_CHASE_RADIUS_PX = 220

# How far past an infielder (measured radially from home plate) the live
# ball must be before the infielder bails out and lets the OF take over.
# ~12 ft at the render scale — enough that the ball is unambiguously
# behind them, not just at the edge of their range. Pitchers and catchers
# share this gate; outfielders are exempt (they're the last line of
# defense, so anything past them is wall-bound, not OF-handoff). Without
# this gate, an SS visibly chased a sharp grounder ~150 ft into shallow
# LF while the LF stood watching.
BAIL_OUT_BEHIND_PX = 30


def _lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


# ---- Flight deceleration ---------------------------------------------------
#
# A batted ball is slower when it reaches the grass than it was when it
# left the bat, and `ground_roll` already says by how much. The flight did
# not: horizontal motion was linear in time, so the ball crossed its whole
# path at its *average* speed and then changed speed in a single frame at
# the landing transition — down to 53% of it on a 90 mph grounder and to
# 8% on a 45 mph roller, which is the ball visibly hitting a wall of
# molasses the moment it reaches the outfield grass. Every shape had it
# (0.61-0.95 across the airborne ones); the grounder is worst because its
# whole path is the part where a ball is decelerating hardest.
#
# The fix is not a new model — it is the model that was already written
# down. `ground_roll.grounder_landing_fraction` derives the end-of-path
# speed by assuming a roughly uniform deceleration from v0 to v_end whose
# time-average is the retention curve's `r * v0`; all that was missing was
# for the animation to fly that profile instead of the average of it.
# Velocity linear in time makes position quadratic, and parameterising on
# `f` = landing speed / average speed gives the whole family at once:
#
#     p(u) = (2 - f) u - (1 - f) u²
#
# f = 1 is the old linear motion, f = 0 is a ball that dies exactly as it
# arrives. It covers the same path in the same time as the linear one, so
# `flight_time_s`, `duration_ms` and every whole-flight schedule built on
# them are untouched; what changes is that the ball arrives travelling at
# precisely the speed `_init_ball_on_ground` then hands to `ground_roll`.
#
# The implied contact speed, `(2 - f) * v_avg`, is the check that this is
# physics and not an easing curve: on a grounder it comes out at the exit
# velocity itself (v_avg = r·EV and v_end = (2r-1)·EV, so v0 = EV), and on
# a 100 mph line drive at 145 ft/s against a horizontal component of 143.


def _decel_path_fraction(u, end_speed_ratio):
    """Fraction of the path covered at time fraction `u`.

    `end_speed_ratio` is the ball's speed at landing over its average
    speed across the flight. Clamped into [0, 1]: above 1 would mean a
    ball that speeds up on its way down, and below 0 one that goes
    backwards.
    """
    u = max(0.0, min(1.0, u))
    f = max(0.0, min(1.0, end_speed_ratio))
    return (2.0 - f) * u - (1.0 - f) * u * u


def _decel_time_fraction(s, end_speed_ratio):
    """Inverse of `_decel_path_fraction` — when the ball reaches `s`.

    The positive root of `(1-f)u² - (2-f)u + s = 0`. Needed wherever the
    defense asks "when does the ball get *here*" about a point partway
    down the path, which is `_path_intercept` on the two low shapes.
    """
    s = max(0.0, min(1.0, s))
    f = max(0.0, min(1.0, end_speed_ratio))
    a = 1.0 - f
    if a < 1e-9:
        return s
    b = 2.0 - f
    disc = max(0.0, b * b - 4.0 * a * s)
    return max(0.0, min(1.0, (b - math.sqrt(disc)) / (2.0 * a)))


def _arc_fly(a, b, peak, t, phase=None):
    """Standard sin-shaped arc.

    `t` places the ball along the path and `phase` drives the vertical
    arc. They are the same number only when the flight is unretarded: the
    apex is halfway through the *flight time*, which under a decelerating
    horizontal is past the halfway point of the path.
    """
    t = max(0.0, min(1.0, t))
    phase = t if phase is None else max(0.0, min(1.0, phase))
    x, y = _lerp(a, b, t)
    lift = peak * math.sin(math.pi * phase)
    return (x, y - lift)


def _arc_liner(a, b, peak, t, phase=None):
    """Low fast arc. Ease-out (1−(1−t)²) was used here previously for a
    'shot' feel, but it pulls horizontal velocity to zero at landing —
    which read as the ball pausing before its post-landing roll picked up.
    The pacing is no longer a feel choice at all: `_decel_path_fraction`
    hands this the ball's real position and it arrives at the speed
    `ground_roll` is about to take it at.
    """
    t = max(0.0, min(1.0, t))
    phase = t if phase is None else max(0.0, min(1.0, phase))
    x, y = _lerp(a, b, t)
    lift = peak * math.sin(math.pi * phase)
    return (x, y - lift)


def _arc_grounder(a, b, peaks, t, phase=None):
    """Variable-bounce arc; one parabolic hop per entry in `peaks`, with the
    ball touching ground at every segment boundary.

    The hops are split evenly over `phase`, the flight *time*, not over
    `t`, the path — so a decelerating grounder takes hops of equal
    duration that cover progressively less ground, which is what a ball
    losing speed does. Keying them to the path instead spends the same
    hop count over a shrinking distance per unit time, and the last hop
    of a dying roller becomes one long float through 58% of the flight.
    """
    t = max(0.0, min(1.0, t))
    phase = t if phase is None else max(0.0, min(1.0, phase))
    x, y = _lerp(a, b, t)
    n = len(peaks)
    bounce_idx = min(n - 1, int(phase * n))
    bounce_t = (phase * n) % 1.0
    lift = peaks[bounce_idx] * math.sin(math.pi * bounce_t)
    return (x, y - lift)


def _grounder_peaks(quality, distance_px=None):
    """Pick bounce profile from contact quality and travel distance.

    Real grounders take many short hops as they travel — each bounce loses
    ~60% of its height (COR² ≈ 0.4). The ball touches grass between every
    hop, so a sharp grounder that travels into the OF visibly rolls through
    the IF rather than arcing over it. Without distance-scaled bounce count,
    a long sharp-grounder hit used a single 32-px arc spanning the full
    flight, which read as a low fly clearing the infielders — defeating the
    point of classifying the contact as a grounder.

    `_arc_grounder` plays one hop per peak entry, so scaling the count with
    distance keeps each hop ~spacing_px wide regardless of how far the ball
    goes. Peaks are clamped to GROUNDER_BOUNCE_MIN_PEAK_PX so the final
    hops still render as hops instead of flattening into a roll.
    """
    if quality < SQUIBBLER_QUALITY_THRESHOLD:
        profile = GROUNDER_BOUNCE_PROFILE["squibbler"]
    elif quality < SHARP_QUALITY_THRESHOLD:
        profile = GROUNDER_BOUNCE_PROFILE["medium"]
    else:
        profile = GROUNDER_BOUNCE_PROFILE["sharp"]

    if distance_px is None:
        n_bounces = GROUNDER_BOUNCE_MIN_COUNT
    else:
        n_bounces = max(GROUNDER_BOUNCE_MIN_COUNT,
                        min(GROUNDER_BOUNCE_MAX_COUNT,
                            int(round(distance_px / profile["spacing_px"]))))

    peaks = []
    h = profile["first_peak_px"]
    for _ in range(n_bounces):
        peaks.append(max(GROUNDER_BOUNCE_MIN_PEAK_PX, h))
        h *= GROUNDER_BOUNCE_COR_SQ
    return tuple(peaks)


def _shadow_t(shape, t):
    """Ground-projection progress; all shapes use linear t (matches arc x,y)."""
    return max(0.0, min(1.0, t))


def _wall_r_at(angle):
    """Polar wall radius (px) at angle `angle` (radians, from +x axis CCW),
    for the elliptical outfield wall. Used both for landing clamps and for
    placing fielders / HR landings relative to the wall.
    """
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    return WALL_SEMI_X * WALL_SEMI_Y / math.hypot(WALL_SEMI_Y * cos_a,
                                                  WALL_SEMI_X * sin_a)


def _clamp_inside_wall(point, margin):
    """Clamp a point to inside the elliptical outfield wall, with a margin in
    pixels measured along the polar radius at that angle.
    """
    dx = point[0] - HOME[0]
    dy_math = HOME[1] - point[1]   # +y outward (math convention)
    dist = math.hypot(dx, dy_math)
    if dist == 0:
        return point
    angle = math.atan2(dy_math, dx)
    limit = _wall_r_at(angle) - margin
    if dist <= limit:
        return point
    s = limit / dist
    return (HOME[0] + dx * s, HOME[1] - dy_math * s)


def _point_outside_wall(point):
    """True when a point on the *ground* lies beyond the outfield wall.

    The boundary is the fence. A ball that reached it and is rattling
    around at its foot reads False no matter how hard it caromed, because
    `_step_ball_on_ground` holds a live ball at BALL_WALL_LIMIT_NORM,
    comfortably inside. Anything that reads True got there by being
    *aimed* past the wall: a home run, or the overshoot point of a
    wall-candidate flight.

    It used to test BALL_WALL_LIMIT_NORM itself, which is that holding
    line — 8 px inside the fence at centre field and 11 down the line. So
    a band in front of the fence read "out of the park", and a ball still
    in flight goes straight through it: a fly ball approaching the wall
    low was hidden by `_ball_behind_wall` for the last several frames
    before it got there and then reappeared at the fence. That is half of
    the reported "the ball clips and abruptly appears back in play"; the
    other half was the impact point itself landing outside this line.

    Home runs clear the fence by as little as a pixel of screen radius
    (the carry distribution is dominated by wall-scrapers), so a test
    with any slack in it would call half of them still in the park.
    """
    dx = point[0] - HOME[0]
    dy_math = HOME[1] - point[1]
    ellipse_d = math.hypot(dx / WALL_SEMI_X, dy_math / WALL_SEMI_Y)
    # On the line counts as past it. A home run's carry past the fence
    # starts at HR_CARRY_MIN_FT = 0, so 0.5% of them land within 1e-9 of
    # exactly 1.0 — a strict `>` leaves those wall-scrapers drawn as a
    # white dot in the black beyond the fence, which is the artifact
    # `test_a_home_run_ball_is_gone_once_it_lands` was written for.
    return ellipse_d >= 1.0


def _polar_point(angle, dist_px):
    """(x, y) in pygame coords for a polar (angle, dist) sampled from home,
    interpreted in *screen-space* pixels. Used for HR landings that overshoot
    the wall by a literal pixel carry. For real-foot hit landings, use
    `_polar_point_ft` instead.

    `angle` is the standard math angle (radians) measured from +x axis CCW;
    90° points straight out toward CF.
    """
    return (HOME[0] + dist_px * math.cos(angle),
            HOME[1] - dist_px * math.sin(angle))


def _polar_point_ft(angle, dist_ft):
    """(x, y) in pygame coords for a polar landing in the *real* field — angle
    is the real-field bearing (90° = straight to CF), distance is in real
    feet. The anisotropic projection then renders the same physical landing
    point wide-and-shallow on screen.
    """
    return _to_screen(dist_ft * math.cos(angle), dist_ft * math.sin(angle))


def _screen_angle_of(field_rad):
    """A real-field bearing as the equivalent *screen-polar* angle.

    The two spaces are the standing trap in this module: the real foul lines
    are at 45°/135° in field feet and at ~30.7°/149.3° on screen, because the
    projection is anisotropic. Anything that reaches the wall — home runs, wall
    caroms, foul home runs — is written in screen polar, because the wall is;
    everything else is written in feet. `spray` speaks feet, so this is the one
    place a spray angle crosses over.
    """
    return math.atan2(math.sin(field_rad) * FT_TO_PX_Y,
                      math.cos(field_rad) * FT_TO_PX_X)


# HR direction. Pulled home runs are the dominant pattern in real MLB (~55-60%
# pulled, ~10% opposite field, the rest straightaway), and that now *emerges*:
# a ball has to be met out in front to be driven, being met out in front means
# the bat is further round, and `spray` reads the bat.
#
# `HR_INSIDE_NORM_PX`, `HR_PULL_SHIFT_RAD` and `HR_BASE_PULL_RAD` are **gone**
# with the model that needed them — a pull bias derived from the *pitch's*
# inside/outside location, which was this file's own second answer to the
# question `spray` now answers once.
#
# The sigma came down from 20° with them. It was noise around a mean that
# carried very little information (the location bias could shift it 29° at
# most, against 20° of scatter); the mean is a real measurement now, so the
# scatter around it can be what it is — the several degrees of variation two
# identically-struck balls really do show.
HR_ANGLE_SIGMA_RAD    = math.radians(7)       # gaussian spread around the mean
HR_FOUL_MARGIN_RAD    = math.radians(2)       # keep HRs clearly inside the poles
HR_ANGLE_MAX_TRIES    = 40                    # rejection-sampling attempts

# Sigma was 9° with a hard clamp to 50°–130° of screen angle. That clamp
# sits well inside the foul lines (which are at ~30.7°/149.3° on screen),
# so home runs could never reach the corners — where the wall is nearest
# and short home runs come from. Every HR landed in the 382–400 ft band of
# wall, which is why distances ran 392–476 ft with a mean of 423.


def _sample_hr_angle(mean_angle):
    """Truncated gaussian over fair territory, by rejection.

    Rejection rather than clamping: at this sigma a clamp would pile every
    out-of-range draw onto the two boundary angles, stacking a visible
    fraction of all home runs on exactly the foul-pole line. The uniform
    fallback is unreachable in practice and exists only to bound the loop.
    """
    lo = FOUL_LINE_SCREEN_RIGHT_RAD + HR_FOUL_MARGIN_RAD
    hi = FOUL_LINE_SCREEN_LEFT_RAD - HR_FOUL_MARGIN_RAD
    for _ in range(HR_ANGLE_MAX_TRIES):
        angle = random.gauss(mean_angle, HR_ANGLE_SIGMA_RAD)
        if lo <= angle <= hi:
            return angle
    return random.uniform(lo, hi)


def _px_per_ft_at(angle):
    """Screen pixels per real foot along the bearing `angle`.

    The feet->pixel projection is anisotropic but *linear along any fixed
    bearing*: a point at polar (angle, r_px) lies
    `r_px * hypot(cos a / FT_TO_PX_X, sin a / FT_TO_PX_Y)` feet from home.
    Feet and pixels are therefore proportional at a given angle, and one
    division converts between them exactly. This is what lets the HR carry
    be specified in feet — the number that is actually meaningful — instead
    of pixels, whose worth in feet silently varies by 17% between the foul
    line and centre field.
    """
    ft_per_px = math.hypot(math.cos(angle) / FT_TO_PX_X,
                           math.sin(angle) / FT_TO_PX_Y)
    return 1.0 / ft_per_px


def _fair_field_angle(spray_field_rad, allow_foul=False):
    """A spray bearing as a real-field angle fit to draw.

    `spray` bounds a fair ball inside the real foul lines already, so this is
    an inset of half a degree and not a clamp — the only ball it moves is one
    landing at exactly 45.0°, which would otherwise draw *on* the line. A real
    clamp here would pile every out-of-range ball onto the two boundary angles,
    which is the defect `_sample_hr_angle` exists to avoid.

    `allow_foul` is for the home run, whose angle is then rejection-sampled
    against the poles anyway, and for the foul, which is outside the lines by
    definition. `None` means a caller that has no swing behind it (a legacy
    outcome string); dead centre is the honest answer there.
    """
    if spray_field_rad is None:
        return math.radians(90.0)
    if allow_foul:
        return spray_field_rad
    return max(FOUL_LINE_FIELD_RIGHT_RAD + FAIR_DRAW_MARGIN_RAD,
               min(FOUL_LINE_FIELD_LEFT_RAD - FAIR_DRAW_MARGIN_RAD,
                   spray_field_rad))


def _pick_hit_landing(outcome, shape, quality=1.0, spray_field_rad=None,
                      ev_mph=None):
    """Pick a landing point for the contact.

    **The direction is an input now**, not a draw. `spray_field_rad` is the
    ball's real-field bearing, read off the bat's own face at the moment it met
    the ball (`spray`), and it is the same number for a ball in play, a home
    run and a foul. What is still sampled here is *depth* — how far the ball
    carried — which comes from the exit velocity through the same projectile
    identity that gives it its hang time.

    Before this the lateral angle was `random.uniform(50°, 130°)` for a ball in
    play, a pitch-location bias for a home run, and a `random.choice((-1, 1))`
    for a ball that reached the wall: three answers, none of them the swing.
    Hit vs. out still emerges from whether a fielder reaches the ball, and the
    landing is still unbiased *with respect to the fielders* — nothing here
    steers toward a gap or a glove.
    """
    if outcome == "IN_PLAY":
        dist_min, dist_max = IN_PLAY_LANDING_FT.get(shape, IN_PLAY_LANDING_FT["LINER"])
        # Passed in, not re-drawn: `exit_velocity_mph` jitters, so drawing
        # it here would give this ball a different speed from the one its
        # hang time and wall candidacy were computed against.
        ev = ev_mph if ev_mph is not None else contact_audio.exit_velocity_mph(quality)
        # Depth comes from how hard the ball was hit, through the same
        # projectile identity that gives it its hang time — not from a
        # linear map on contact quality, whose real distribution sits at
        # 0.88 and put nearly every batted ball at the deep end of its
        # range. See ball_flight.carry_distance_ft.
        if shape == "GROUNDER":
            mid = dist_min + (dist_max - dist_min) * ball_flight.ground_depth_fraction(ev)
        else:
            mid = ball_flight.carry_distance_ft(shape, ev)
        # A small uniform spread so each contact looks distinct even at
        # a fixed exit velocity.
        #
        # `mid` is clamped into the range *before* the window is built, and
        # that ordering is the whole point. Written as
        # `uniform(max(dist_min, mid - spread), min(dist_max, mid + spread))`
        # the bounds cross over as soon as `mid` sits more than `spread`
        # outside the range — and `random.uniform(a, b)` does not care which
        # way round its arguments are, it samples `[b, a]`. So the clamp
        # inverted into its own opposite exactly where it was needed, and the
        # ball landed *outside* the range on the far side.
        #
        # It was not a corner. Over the real quality distribution: 62% of
        # POP_UPs cleared their 160 ft cap, out to 272 ft — a pop-up landing
        # in the outfield — plus 8.9% of FLYs past 365 ft (to 416) and 4.3%
        # of LINERs short of their 130 ft floor (to 100). The EV
        # recalibration widened it by pushing carry up, but the defect is
        # independent of calibration and predates it.
        spread = (dist_max - dist_min) * 0.18
        mid = min(max(mid, dist_min), dist_max)
        dist_ft = random.uniform(max(dist_min, mid - spread),
                                 min(dist_max, mid + spread))
        # The bat's bearing, unchanged. Still no artificial pull toward gaps
        # or lines — the spray pattern is the input to the fielder simulation,
        # not a hint about the desired outcome. It simply comes from the swing
        # now instead of from `random.uniform`.
        angle = _fair_field_angle(spray_field_rad)
        return _clamp_inside_wall(_polar_point_ft(angle, dist_ft),
                                  LANDING_WALL_MARGIN_PX)

    if outcome == "HOME RUN":
        # The bat's bearing again, crossed into screen polar because the wall
        # is a screen-space ellipse. It replaced a pull bias read off the
        # *pitch's* inside/outside location (`HR_INSIDE_NORM_PX`,
        # `HR_PULL_SHIFT_RAD`, `HR_BASE_PULL_RAD`, all gone): pitch location
        # does belong in the answer, but it belongs the way it reaches a real
        # hitter — by moving where the bat points when it arrives — and
        # `bat_path` already models that. Reading it off the pitch as well was
        # the second model of one thing.
        mean_angle = _screen_angle_of(_fair_field_angle(spray_field_rad,
                                                        allow_foul=True))
        angle = _sample_hr_angle(mean_angle)
        wall_r = _wall_r_at(angle)
        q = max(0.0, min(1.0, quality))
        # Carry past the wall uses a biased roll so most produce small
        # carries (just-cleared, wall-scrapers); only the right tail
        # produces deep blasts. Quality enlarges the *range* of possible
        # carries, not the likelihood of large ones — so even on max-
        # quality contact, most HRs still barely clear, with the
        # occasional moonshot.
        bias = random.random() ** HR_CARRY_BIAS_EXPONENT
        carry_range = HR_CARRY_BASE_RANGE_FT + q * HR_CARRY_QUALITY_BONUS_FT
        carry_ft = HR_CARRY_MIN_FT + bias * carry_range
        return _polar_point(angle, wall_r + carry_ft * _px_per_ft_at(angle))

    # Fallback — treat any unknown outcome as a generic HIT (which the
    # caller above already handles for the standard case). Reaches here
    # only if a stale legacy outcome string is passed in.
    q = max(0.0, min(1.0, quality))
    dist_min, dist_max = HIT_LANDING_FT.get(shape, HIT_LANDING_FT["LINER"])
    dist_ft = random.uniform(dist_min, dist_min + (dist_max - dist_min) * (0.4 + 0.4 * q))
    return _clamp_inside_wall(
        _polar_point_ft(_fair_field_angle(spray_field_rad), dist_ft),
        LANDING_WALL_MARGIN_PX)


def _pick_shape(outcome, vertical_offset, batted_ball_type=None):
    """Pick a trajectory shape from outcome + bat-vs-ball alignment.

    When batted_ball_type is supplied (by hit_outcome_manager — the canonical
    source), use it directly so the visual matches the resolved type. HOME
    RUN always animates as FLY regardless of underlying type (a line-drive
    HR clearing the wall would read poorly with a low arc). Legacy callers
    without a type fall back to the old vertical_offset bucketing.
    """
    if outcome == "HOME RUN":
        return "FLY"
    if batted_ball_type in ("LINER", "FLY", "GROUNDER", "POP_UP"):
        return batted_ball_type
    if outcome == "GROUNDOUT":
        return "GROUNDER"
    if outcome == "FLYOUT":
        return "POP_UP" if vertical_offset > 25 else "FLY"
    if outcome in ("IN_PLAY", "FOUL"):
        if vertical_offset > 25:
            return "POP_UP"
        if vertical_offset > 8:
            return "FLY"
        if vertical_offset < -8:
            return "GROUNDER"
        return "LINER"
    weights = SHAPE_WEIGHTS.get(outcome, [("FLY", 1.0)])
    r = random.random()
    cum = 0.0
    for shape, w in weights:
        cum += w
        if r <= cum:
            return shape
    return weights[-1][0]


_WALL_GEOMETRY = None


def _wall_geometry():
    """Compute and cache the static outfield-wall geometry.

    Every point here is anchored to module constants (HOME and the WALL_*
    semi-axes), so it never changes frame-to-frame. Recomputing the ~97
    sin/cos samples and the point lists every frame was pure waste; build
    them once and reuse the same lists (pygame.draw does not mutate them).
    """
    global _WALL_GEOMETRY
    if _WALL_GEOMETRY is not None:
        return _WALL_GEOMETRY
    hx, hy = HOME
    foul_t = math.atan2(WALL_FT_X, WALL_FT_Y)
    samples = 96
    wall_top_pts = []
    wall_bot_pts = []
    for i in range(samples + 1):
        t = foul_t + (math.pi - 2 * foul_t) * i / samples
        x = hx + WALL_SEMI_X * math.cos(t)
        y_top = hy - WALL_SEMI_Y * math.sin(t)
        wall_top_pts.append((x, y_top))
        wall_bot_pts.append((x, y_top + WALL_FACE_HEIGHT_PX))
    _WALL_GEOMETRY = {
        'top': wall_top_pts,
        'bot': wall_bot_pts,
        'face_poly': wall_top_pts + list(reversed(wall_bot_pts)),
    }
    return _WALL_GEOMETRY


@dataclass
class Fielder:
    """One defender. `pos` is mutated each frame.

    Motion model: after `reaction_delay_s`, accelerate over `accel_time_s`
    to `max_speed`, cruise at constant velocity toward `target`, then
    decelerate inside `decel_radius_px`. All four are jittered per fielder
    so the team doesn't speed up, cruise, or settle in lockstep.

    Speeds and delays are in **real** seconds and feet per second; the
    conversion to screen motion happens once, in
    `HitAnimation._travel_ms`. Nothing here may be compared against
    `HitAnimation._elapsed`, which is an animated clock — use
    `HitAnimation._anim_ms` to bring a real duration onto it.

    `current_speed_frac` is stateful — it ramps toward a desired fraction
    at most `dt / accel_time_s` per frame. Without this, the legacy
    elapsed-time `accel_factor` locked to 1.0 after ~220 ms; any later
    target switch (lean → chase, intercept point → live ball) multiplied
    that against a freshly-rising `decel_factor` and produced a one-frame
    jump from ~20% to 100% speed — the "sudden sprint" tell. It is a
    *fraction* rather than a speed so the ramp is unaffected by the
    direction-dependent px/ft conversion applied downstream.
    """
    role: str
    home_pos: tuple
    pos: list           # [x, y], mutable
    target: tuple
    sway_phase: float
    # Real feet per second. Turned into screen motion only by
    # `HitAnimation._travel_ms`, which is the single place the projection
    # and the presentation scale are applied.
    max_speed: float = FIELDER_SPRINT_FT_S
    reaction_delay_s: float = 0.20
    accel_time_s: float = FIELDER_ACCEL_TIME_S
    decel_radius_px: float = FIELDER_DECEL_RADIUS_PX
    # Fraction of max_speed, so the ramp is unit-free and survives the
    # px/ft conversion happening downstream of it.
    current_speed_frac: float = 0.0
    # Immutable copy of the jittered sprint speed this fielder was born
    # with. `max_speed` gets temporarily *paced down* while a fielder is
    # routed to an in-flight intercept (so they arrive with the ball
    # instead of standing under it), and every code path that later
    # re-tasks them — most importantly "get back and cover the bag" —
    # has to restore the real speed. Reading it back off `max_speed`
    # would read the paced value; this field is the source of truth.
    base_max_speed: float = None
    # Reaction clock for *breaking to a base* rather than fielding the
    # batted ball: `reaction_delay_s` minus this role's fielding bias.
    # ROLE_REACTION_BIAS_S models glove-readiness — the pitcher's
    # 0.90 s is recovery from the follow-through, which is what stands
    # between them and a comebacker, not between them and first base.
    # They are already falling toward the first-base side as the ball is
    # struck; the break is the one thing that delay should not gate.
    # Charging it anyway pushed the pitcher's ETA past
    # COVER_IN_TIME_BUDGET_S on a third of right-side grounders, and
    # the 2B inherited the bag — see _route_first_base_cover.
    break_delay_s: float = None
    # Latched once this fielder has run out their range cap and been beaten
    # by the ball — see `_pursuit_point`. A latch rather than a per-frame
    # distance test because drifting with the ball moves them *off* the
    # pull-up spot, so re-testing flips the target back and forth between
    # the two and the fielder shuffles in place.
    pulled_up: bool = False
    # The two reaction clocks projected onto the animated clock, so the
    # per-frame gates can compare them against `_elapsed` directly.
    # Derived — `HitAnimation._setup_hit` rewrites both once the play's
    # time scale is known. Never set these by hand; set the `_s` fields.
    reaction_delay_ms: float = 0.0
    break_delay_ms: float = 0.0

    def __post_init__(self):
        if self.base_max_speed is None:
            self.base_max_speed = self.max_speed
        if self.break_delay_s is None:
            self.break_delay_s = (self.reaction_delay_s
                                  - ROLE_REACTION_BIAS_S.get(self.role, 0.0))
        # Provisional projection at the module default scale. Correct for
        # the foul path (which has no fielding and never calls _setup_hit)
        # and overwritten for every live ball.
        scale = PRESENTATION_TIME_SCALE * 1000.0
        self.reaction_delay_ms = self.reaction_delay_s * scale
        self.break_delay_ms = self.break_delay_s * scale


class HitAnimation:
    """Plays a top-down ball-flight animation, then fires the outcome callback.

    Lifecycle:
        1. update(now) repeatedly to advance ball + fielder positions.
        2. draw(screen) to render onto the (already-cleared) screen.
        3. When `finished` flips True, the caller fires `on_complete` and
           may begin its post-banner read window.

    All 9 defenders are drawn every frame. The primary fielder for the play
    is positioned by phase logic; the rest ease toward `target` (set by
    `_assign_targets`-style logic in the per-outcome setup) with a small
    idle sway when at rest.
    """

    def __init__(self, game, outcome, on_complete, vertical_offset=0.0, quality=0.0,
                 batted_ball_type=None, spray_deg=0.0, defense=None):
        self.game = game
        self.outcome = outcome
        self.on_complete = on_complete
        self.vertical_offset = vertical_offset
        self.quality = quality
        self.batted_ball_type = batted_ball_type
        # The nine gloves behind the pitcher, as real feet and seconds
        # (`gameplay/defense.py`). Handed in rather than read off
        # `game.settings_manager` here: `defense` is a pure module and must
        # not learn about a settings manager, and every fielding test builds
        # this class with a stub game that has none. The default is the
        # neutral profile, which restates the module constants exactly — so
        # a caller that passes nothing gets precisely the old behaviour.
        self.defense = defense_model.profile_for(defense)
        # Which way the ball left the bat: degrees from centre field,
        # pull-positive for either batter (`spray`). One number, used by every
        # direction decision in this class — the ball in play, the home run,
        # the ball that reaches the wall and the foul. It replaced
        # `horizontal_inside` (a pitch-location bias the home run read) and
        # `foul_timing_norm` (a signed timing severity the foul read), which
        # were two different answers to this question and left the ordinary
        # ball in play with none.
        self.spray_deg = spray_deg
        self.spin = spray.spin_for(self._batter_handedness())
        # Resolved once, here, rather than at each of the four sites: the
        # handedness flip has exactly one home.
        self.spray_field_rad = spray.field_angle_rad(spray_deg, self.spin)

        self.start_time = None
        self.banner_fired = False
        self.finished = False
        self._elapsed = 0
        self._last_elapsed = 0

        # Animated ms per real ms for this play. Set in _setup_hit once the
        # ball's physical flight time is known; every real duration reaches
        # the animated clock through `_anim_ms` or `_travel_ms`, and nothing
        # physical is allowed to bypass it. See PRESENTATION_TIME_SCALE.
        self.time_scale = PRESENTATION_TIME_SCALE
        # The ball's modelled flight, in real seconds — the window the
        # defense actually has. duration_ms is just this on the animated
        # clock.
        self.flight_time_s = 0.0

        # For HIT (the unified in-play outcome) the animation determines
        # the resolved outcome — FLYOUT/GROUNDOUT/SINGLE/DOUBLE/TRIPLE —
        # from whether a fielder intercepts the ball in flight or only
        # picks it up after landing. Animation pauses when secured (or
        # caught in-flight) instead of timing out at duration_ms.
        self._needs_secure = outcome == "IN_PLAY"
        self._secured = False
        self._secured_at_ms = None  # elapsed time when ball was secured

        # Final outcome after classification. HOME RUN is known up front;
        # HIT stays None until interception/secure resolves the outcome.
        self.classified_outcome = None if outcome == "IN_PLAY" else outcome
        # Both clocks for a fielded ground ball, once one has been run.
        # Kept on the animation so the verdict is inspectable — for the
        # SAFE/OUT call, for tests, and for the play_margin_s column.
        self.play_timing = None
        # The equivalent for a ball that got through: the margin on the
        # last base the runner attempted. Only one of the two is ever set,
        # since a ball is either fielded in the infield or it isn't.
        self.extra_base_margin_s = None

        # In-flight interception state. Set by _check_in_flight_intercept
        # when a fielder reaches the ball before it lands. Drives the
        # post-intercept sub-animation rendered by
        # _render_post_fielding (catch hold for flies; throw-to-1B
        # for grounders).
        self._secured_in_flight = False
        # A fielder has the ball and a sub-animation owns the ball's position
        # and the finish clock: the catch hold on a fly, or the throw to first
        # on a grounder. **Deliberately not the same thing as
        # `_secured_in_flight`**, which is how the ball got there. Gating the
        # throw on that one is what let a grounder picked up off the ground
        # skip straight from the pickup to the outcome banner.
        self._post_fielding = False
        self._inflight_caught_at_ms = None
        self._inflight_catch_pos = None
        # Throw-to-1B schedule (used only for grounder intercepts). The
        # flight duration is taken from the PlayTiming that decided the
        # play, not from a constant — see _trigger_in_flight_intercept.
        self._go_throw_start_ms = None
        self._go_throw_arrive_ms = None
        self._go_throw_ms = 0.0
        self._go_done_ms = None
        self._go_first_base_pos = None
        # Who is currently assigned to cover first base. Maintained every
        # frame on grounders (see _route_first_base_cover) rather than
        # decided once at intercept time — the fielder chasing the ball
        # can't also be standing on the bag, so the assignment has to
        # follow the play as it develops.
        self._cover_role = None
        # Estimated elapsed-ms at which the ball gets fielded — the start
        # of the cover man's deadline (see COVER_IN_TIME_BUDGET_MS). Set
        # from the primary's intercept timing at setup, then replaced with
        # the real catch time once one happens.
        self._fielded_at_ms = 0.0

        # Stateful ball-on-ground physics (SDT). Lazy-initialized at the
        # landing transition by _init_ball_on_ground, which is also where
        # `ground_roll`'s feet and seconds become screen motion.
        self._ball_pos = None
        self._ball_v = None
        self._ground_path = None
        self._landing_path_cache = None
        # Landing speed over average flight speed — the `f` of
        # `_decel_path_fraction`. 1.0 is undecelerated motion, which is
        # what the scripted flights (HOME RUN, fouls) keep.
        self._flight_end_speed_ratio = 1.0
        self._ball_px_per_ft = FT_TO_PX_X
        self._bounces = []
        self._bounces_end_ms = 0.0
        # A ball that struck the fence above the grass, falling down the
        # face: (height_px, duration_ms). See `_begin_wall_drop`.
        self._wall_drop = None
        self._bounces_completed = 0
        # Per-frame cache for _forecast_ball.
        self._forecast = None
        self._forecast_at_ms = None
        # Set only when nobody can catch the ball — see _pick_retrieval_role.
        self._retrieval_point = None

        # Set true the first time the rolling ball reflects off the elliptical
        # outfield wall (see _step_ball_on_ground). Drives an XBH override in
        # the HIT classifier — a ball that reaches the wall is, by physical
        # definition, past every OF, so it should never resolve as a single
        # regardless of how quickly the ricochet brings it back to a fielder.
        self._wall_hit = False
        # Struck the wall in the air, as opposed to rolling into it. Only
        # this one forces an extra base — see `_resolve_extra_bases`.
        self._wall_hit_in_flight = False

        # Build the 9-fielder roster. Random sway phases + reaction delays so
        # fielders don't move in lockstep — the team reads the ball with
        # slightly different latency, which sells "alive" reactions.
        # Per-fielder motion jitter so the team doesn't move in lockstep:
        # speeds vary ±25%, acceleration ramps vary ±35%, deceleration radii
        # vary ±40%. Combined with jittered reaction delays, fielders ramp up,
        # cruise, and settle on visibly different schedules.
        self.fielders = {role: Fielder(
            role=role,
            home_pos=FIELDER_HOMES[role],
            pos=list(FIELDER_HOMES[role]),
            target=FIELDER_HOMES[role],
            sway_phase=random.uniform(0, math.tau),
            # The profile moves the *base draw*; ROLE_REACTION_BIAS_S is not
            # scaled. That bias is recovery from a follow-through and a
            # catcher's crouch — a fact about the position, not about skill —
            # and scaling through it drives `break_delay_s` (which
            # __post_init__ derives by subtracting it) toward zero, i.e. a
            # pitcher breaking for first before contact.
            reaction_delay_s=random.uniform(self.defense.reaction_min_s,
                                            self.defense.reaction_max_s)
                + ROLE_REACTION_BIAS_S.get(role, 0.0),
            # The profile moves the centre of the speed distribution; the
            # jitter keeps its shape. Widening the jitter to express the
            # setting is what COVER_ROLE_PRIORITY exists to prevent — it is a
            # strict list precisely because speed jitter was flipping an ETA
            # race.
            max_speed=self.defense.sprint_fts * random.uniform(0.78, 1.22),
            accel_time_s=FIELDER_ACCEL_TIME_S * random.uniform(0.7, 1.35),
            decel_radius_px=FIELDER_DECEL_RADIUS_PX * random.uniform(0.65, 1.4),
        ) for role in ROLES}

        # Roles whose targets are explicitly set per outcome (primary, backup,
        # cutoff, 1B-on-grounder). All other roles get continuous lean targets
        # tracking the live ball position via _update_lean_targets.
        self._lean_excluded: set = set()

        # Trajectory shape (decoupled from outcome resolution). When
        # batted_ball_type is provided by hit_outcome_manager, it's the
        # canonical source — vertical_offset is only a fallback for
        # legacy callers.
        self.shape = _pick_shape(outcome, vertical_offset, batted_ball_type)

        # This batted ball's exit velocity. Drawn once, here, because
        # `contact_audio.exit_velocity_mph` carries jitter — identical
        # swings must not sound mechanically identical — so calling it per
        # use gives one ball several different speeds. Carry, hang time,
        # whether it reaches the wall and the infield verdict were being
        # computed from four independent draws, which is the same "two
        # models of one thing" mistake as the two clocks, at a smaller
        # scale: a ball could be given a 380 ft carry and the hang time of
        # a 340 ft one.
        self.exit_velocity_mph = contact_audio.exit_velocity_mph(quality)

        # Whether the pitcher can handle a ball hit back at them on this
        # play. Rolled once, up front, rather than per-frame: a coin
        # flipped every frame would let a pitcher who "missed" the ball
        # at the mound snare it two frames later. See
        # PITCHER_CLEAN_FIELD_PROB.
        self._pitcher_fields_clean = self._roll_pitcher_clean_field()

        # Misplay state. Rolled once per batted ball, at the moment a fielder
        # first reaches the ball, and latched — a coin flipped every frame
        # would let a fielder who muffed it snare it two frames later, which
        # is the same reasoning `_roll_pitcher_clean_field` gives.
        #
        # It cannot be rolled here in __init__ like the pitcher's is, because
        # the probability depends on how far the fielder had to range, which
        # does not exist until somebody gets there.
        self._misplay_rolled = False
        self._misplay_kind = None          # None | "BOBBLE" | "THROUGH" | "MUFF"
        self._misplay_s = 0.0              # a bobble's cost, seconds on release
        self._misplay_role = None
        # Fielders who have already had their chance at this ball. A beaten
        # fielder is filtered out of the intercept pool for the rest of the
        # play, exactly as the pitcher is when they lose their clean-fielding
        # roll — otherwise they re-intercept on the very next frame.
        self._beaten_roles = set()
        # Ball on the grass after a muff: the earliest the fielder can pick it
        # back up. Those seconds flow into `_secured_at_ms` and are spent by
        # `extra_bases`, so a drop costs what it should.
        self._misplay_recovered_at_ms = 0.0
        self.is_error = False
        self.error_bases = 1
        # The presentation of the above: who wears the "!" and when it
        # popped. Latched by `_charge_error`, the one place `is_error` is
        # set, so the mark and the banner cannot disagree about whether
        # there was an error or about whose it was.
        self._error_role = None
        self._error_marked_at_ms = None

        # Per-frame ball state.
        self._ball = HOME
        self._ball_shadow = HOME

        # HR distance (set after _setup_hit, from the actual landing point).
        # Home runs only — a foul's distance is not a real accomplishment, so
        # the overlay would just be noise on a ball that counts as a strike.
        self.hr_distance_ft = None

        # True when the foul path took the "foul home run" branch: barreled
        # contact hooking just past the pole. Purely a flight-shape marker now
        # (HR carry model + HR peak), with no distance readout.
        self.is_foul_hr = False

        # Outcome-specific setup. The unified BATTED_BALL flow handles
        # "IN_PLAY" (in-play, resolution emerges from fielder routing) and
        # "HOME RUN" (scripted past-the-wall flight). Legacy outcomes
        # are no longer fed in by pitch_simulation — anything unknown
        # falls back to the unified HIT path.
        if outcome == "HOME RUN":
            self._setup_hit(outcome)
        elif outcome == "FOUL":
            # Cosmetic foul playback: scripted timeout like HOME RUN
            # (_needs_secure stays False, classified_outcome stays "FOUL").
            # Critically, this must NOT fall into the else-branch below,
            # which would rewrite the foul into a live in-play ball that
            # never finishes until a fielder secures it.
            self._setup_foul()
        else:
            self.outcome = "IN_PLAY"
            self.classified_outcome = None
            self._needs_secure = True
            self._setup_hit("IN_PLAY")

        # Compute HR distance from where the ball actually lands so the
        # number on screen always matches the visual. Without this, the old
        # quality-driven mapping could show 480 ft on a HR that visibly
        # landed just past the wall (or vice versa).
        if outcome == "HOME RUN":
            # Invert the anisotropic projection so the displayed distance is
            # the real-field distance, not a stretched screen-space distance.
            dx_ft = (self._hit_end[0] - HOME[0]) / FT_TO_PX_X
            dy_ft = (HOME[1] - self._hit_end[1]) / FT_TO_PX_Y
            self.hr_distance_ft = round(math.hypot(dx_ft, dy_ft))

        # Lazy-init fonts on first draw that needs them.
        self._font = None
        self._prompt_font = None
        self._error_font = None

    # ---- The real-time boundary -----------------------------------------
    #
    # Everything physical in this class is specified in real feet and real
    # seconds; `_elapsed`, `duration_ms` and every `*_ms` schedule are on
    # the animated clock. These two methods are the only legitimate way
    # across, and keeping it to two is what makes the unit discipline
    # checkable — before, fielder speed carried the projection and the
    # dilation folded into a single px/ms constant, so there was no line to
    # audit.

    def _anim_ms(self, real_s):
        """A real duration, in animated milliseconds."""
        return real_s * 1000.0 * self.time_scale

    def _travel_ms(self, fielder, from_pos, to_pos, speed_fts=None):
        """Animated ms for `fielder` to cover a screen displacement at a
        real sprint speed, honouring the anisotropic projection.

        The projection is why this cannot be a division by a scalar px/ms
        speed: the same pixel distance is 1.68x more feet across the screen
        than up it, so a single px/ms number silently means two different
        real speeds. Converting the displacement to feet first is what makes
        one ft/s speed mean one speed in every direction.
        """
        ft = _ft_dist(to_pos[0] - from_pos[0], to_pos[1] - from_pos[1])
        speed = max(0.1, speed_fts if speed_fts is not None else fielder.max_speed)
        return self._anim_ms(ft / speed)

    # ---- Setup ----------------------------------------------------------

    def _setup_hit(self, outcome):
        # Wall-candidate selection: does this ball actually carry to the
        # wall? A FLY or LINER whose modelled carry reaches the fence and
        # which the HR gate upstream did not turn into a home run is, by
        # definition, a ball off the wall.
        #
        # This was a quality-gated coin flip — `WALL_HIT_PROB_MAX = 0.22`
        # ramped from q=0.5 — and it is the third place the uniform-quality
        # assumption did damage. Real quality sits at a 0.88 median, so the
        # ramp fired at ~17% rather than the ~11% it was tuned for, and
        # since every wall ball is at minimum a double it alone produced
        # 15% of line drives landing past 360 ft. Asking the carry model
        # is both correct and self-calibrating: it cannot disagree with
        # the distance the same ball would have been given anyway.
        self._is_wall_candidate = False
        if outcome == "IN_PLAY" and self.shape in ("FLY", "LINER"):
            carry_ft = ball_flight.carry_distance_ft(
                self.shape, self.exit_velocity_mph)
            # Measured toward centre field, the shallowest part of the
            # park; the angle isn't chosen yet, and picking the deepest
            # reference keeps this from over-selecting balls that only
            # reach a wall they were never hit toward.
            if carry_ft >= WALL_REACH_FT:
                self._is_wall_candidate = True

        if self._is_wall_candidate:
            # The bat's bearing, crossed into screen polar because the wall
            # is. Distance is wall_r + carry, with squared bias so most
            # carries are small (impact low on the face).
            # This branch used to run its own line-versus-gap lottery and
            # then pick the *side* with `random.choice((-1, 1))` — so which
            # way a ball off the wall went, which is the difference between a
            # double down the line and one in the gap, was a coin flip taken
            # after the swing was over.
            angle = _screen_angle_of(_fair_field_angle(self.spray_field_rad))
            bias = random.random() ** WALL_HIT_CARRY_BIAS_EXP
            carry_ft = WALL_HIT_CARRY_FT_MIN + bias * (
                WALL_HIT_CARRY_FT_MAX - WALL_HIT_CARRY_FT_MIN
            )
            # Convert the polar wall-radius (px) at this angle back into
            # the equivalent screen distance, then add carry. We pick the
            # landing point directly in screen pixels (no foot-space
            # _polar_point_ft) because the wall is defined in screen-
            # space and the in-flight check uses screen-space too.
            wall_px = _wall_r_at(angle)
            dist_px = wall_px + carry_ft * FT_TO_PX_Y  # use y-scale as
            # a rough px-per-ft for radial carry; exact value is not
            # critical — the in-flight detector kills the arc at the
            # wall regardless of how far past the landing was aimed.
            self._hit_end = (
                HOME[0] + dist_px * math.cos(angle),
                HOME[1] - dist_px * math.sin(angle),
            )
        else:
            self._hit_end = _pick_hit_landing(
                outcome, self.shape, self.quality,
                spray_field_rad=self.spray_field_rad,
                ev_mph=self.exit_velocity_mph,
            )

        # Peak chosen per shape. HOME RUN uses its scripted peak; HIT uses
        # a quality-scaled FLY peak so soft flies arc lower than screamers.
        if self.shape == "FLY":
            if outcome == "HOME RUN":
                self._hit_peak = HR_PEAK_H
            else:
                q = max(0.0, min(1.0, self.quality))
                lo, hi = FLY_HIT_PEAK_RANGE
                self._hit_peak = lo + q * (hi - lo)
                # A wall candidate's peak is capped further down, once the
                # flight's pacing is known — see `_wall_impact_peak_cap`.
                # It cannot be done here: the height at the fence depends
                # on when the ball gets there, and that is not settled
                # until `_flight_end_speed_ratio` is.
        elif self.shape == "LINER":
            self._hit_peak = random.uniform(*LINER_PEAK_RANGE)
        elif self.shape == "POP_UP":
            self._hit_peak = random.uniform(*POPUP_PEAK_RANGE)
        else:  # GROUNDER — peaks vary with contact quality. Distance to
            # the landing point scales the bounce count (one hop per
            # spacing_px of travel) so the ball touches grass between every
            # hop instead of arcing once over the entire infield.
            self._hit_peak = 0
            grounder_dist_px = math.hypot(self._hit_end[0] - HOME[0],
                                          self._hit_end[1] - HOME[1])
            self._grounder_peaks = _grounder_peaks(self.quality, grounder_dist_px)

        # Duration. HOME RUN keeps its scripted hang time — it is a
        # cutscene, nobody is racing it. Everything else takes the flight
        # time the ball physically has, from `ball_flight`, shown through
        # the one presentation scale.
        #
        # This replaced `HIT_BASE_DURATION_MS * (1.2 - 0.4 * quality)`,
        # which was backwards for airborne balls: quality drives distance,
        # so the harder a ball was hit the *less* time it spent in the air.
        # Fly balls landing past 400 ft were given 2.67 s of hang against a
        # real 4.7 s, and were caught 0% of the time; bloops at 200 ft got
        # 3.4 s against a real 3.3 s and were caught always. Fly-ball BABIP
        # came out .425 against an MLB .120, and those extra fly-ball hits
        # were most of the doubles surplus.
        if outcome == "HOME RUN":
            self.duration_ms = HR_DURATION_MS
            self.flight_time_s = HR_DURATION_MS / 1000.0
        else:
            landing_ft = _ft_dist(self._hit_end[0] - HOME[0],
                                  self._hit_end[1] - HOME[1])
            self.flight_time_s = ball_flight.flight_time_s(
                self.shape, self.exit_velocity_mph, landing_ft)
            self.duration_ms = int(self._anim_ms(self.flight_time_s))

        # Fielder reaction delays are stored in real seconds (they are
        # human latencies, not pacing), so bring them onto this play's
        # animated clock now that the scale is known. Done once, here,
        # rather than at every comparison site — `_elapsed` is compared
        # against these in five places and a missed conversion would show
        # up as a fielder who reads the ball before it is hit.
        for f in self.fielders.values():
            f.reaction_delay_ms = self._anim_ms(f.reaction_delay_s)
            f.break_delay_ms = self._anim_ms(f.break_delay_s)

        if outcome == "HOME RUN":
            # Closest OF runs back toward the wall along the ball's bearing,
            # stopping ~30 px in front of the wall. Use the polar wall
            # radius at that angle so the stop point sits on the elliptical
            # warning track regardless of where the HR is going (lines vs.
            # CF have different wall depths).
            primary = self._closest_role_in(OUTFIELD_ROLES, self._hit_end)
            self._primary_role = primary
            angle = math.atan2(HOME[1] - self._hit_end[1],
                               self._hit_end[0] - HOME[0])
            target_r = _wall_r_at(angle) - 30
            wall_x = HOME[0] + target_r * math.cos(angle)
            wall_y = HOME[1] - target_r * math.sin(angle)
            self._primary_start = self.fielders[primary].home_pos
            self._primary_stop = (wall_x, wall_y)
            self.fielders[primary].target = self._primary_stop
            self._lean_excluded = {primary}
            return

        # How much slower the ball is at the end of its flight than the
        # average it is about to be flown at. Fixed here, before anything
        # asks where the ball is or when it gets there — `_path_intercept`
        # runs inside `_assign_in_play_targets` below and has to be timing
        # the same flight the viewer sees.
        self._flight_end_speed_ratio = self._landing_speed_ratio()

        # A wall candidate is aimed *past* the fence, so how high the ball
        # is when it actually reaches the fence is a leftover of the arc
        # unless something asks for it. Ask: cap the peak at the value
        # that has the ball strike the face rather than clear it. This has
        # to run here rather than beside the peak, because the crossing
        # phase is a question about the flight's pacing and the line above
        # is where that is settled.
        if self._is_wall_candidate:
            self._hit_peak = min(self._hit_peak, self._wall_impact_peak_cap())

        # Route every plausible defender to their best intercept point on
        # the ball's path. The fielder whose intercept timing best matches
        # the ball's arrival becomes the nominal primary (used by the
        # post-landing chase logic); secondary fielders within a margin
        # back up the play. Hits vs. outs emerge from whether any
        # routed fielder actually reaches the ball — there is no
        # pre-decided primary "going to the landing spot" any more.
        self._assign_in_play_targets()

    def _setup_foul(self):
        """Scripted foul-ball flight. Direction is the ball's own bearing,
        shape is the vertical contact offset (already bucketed into
        self.shape), and depth/foul-HR come from quality. No interception or
        securing — the ball lands untouched and the animation finishes on
        duration_ms.

        Direction used to be the *sign of the swing's timing error* against a
        window of hand-tuned milliseconds: early meant pull side, late meant
        opposite field, and how far foul was how badly mistimed. That was the
        only place in the game where the swing reached the ball's direction at
        all, and it was a different model from the one the home run used and
        from the nothing a ball in play used. It reads the same `spray_deg` as
        everything else now, and being early still hooks the ball toward the
        pull-side pole — because that is what turning the bat further round
        does, not because a branch says so.
        """
        # Which side of the field: straight off the bearing, so handedness is
        # already folded in.
        foul_side = 1.0 if self.spray_field_rad > math.radians(90.0) else -1.0
        q = max(0.0, min(1.0, self.quality))
        # How far past the line. **The two ways to foul a ball land here as
        # two different pictures**, which is worth keeping: a ball hooked past
        # the pole was struck cleanly and is only just foul, so it hugs the
        # line; a ball that left between the lines is here because the contact
        # was glancing — tipped, topped, caught off the end — and those spray
        # sharply foul however they were pointed. `severity` is the second one
        # measured off quality, where it used to be measured off a timing
        # window that had stopped meaning anything.
        past_rad = max(0.0, math.radians(abs(self.spray_deg) - spray.FOUL_LINE_DEG))
        severity = min(1.0, max(past_rad, (1.0 - q) * FOUL_OFF_MAX_RAD)
                       / FOUL_OFF_MAX_RAD)
        # Two line constants because the two landing pickers work in
        # different spaces: generic fouls go through _polar_point_ft
        # (real-field feet, lines at 45°/135°), the foul-HR through
        # _polar_point (screen pixels, lines at ≈30.7°/149.3°).
        field_line = (FOUL_LINE_FIELD_LEFT_RAD if foul_side > 0
                      else FOUL_LINE_FIELD_RIGHT_RAD)
        screen_line = (FOUL_LINE_SCREEN_LEFT_RAD if foul_side > 0
                       else FOUL_LINE_SCREEN_RIGHT_RAD)

        if self.shape == "POP_UP":
            # Severe undercut: popped straight back behind the plate. The
            # camera leaves only ~50 px of screen below home, so the pop
            # reads mostly through its tall arc; the landing is clamped
            # onto the visible apron.
            angle = math.radians(270) - foul_side * random.uniform(
                math.radians(15), math.radians(60))
            dist_ft = random.uniform(*FOUL_POP_BACK_FT)
            end = _polar_point_ft(angle, dist_ft)
            self._hit_end = (max(15.0, min(1265.0, end[0])), min(712.0, end[1]))
            self._hit_peak = random.uniform(*POPUP_PEAK_RANGE)
            self._foul_flight_ms = FOUL_FLIGHT_MS["POP_UP"]
            drift_role = "C"
        elif (q >= FOUL_HR_QUALITY_MIN and severity <= FOUL_HR_MAX_SEVERITY
                and self.shape in ("FLY", "LINER")):
            # "Foul home run": barreled but barely mistimed — a deep fly
            # hooking just past the pole. Reuses the HR carry model for the
            # flight, but deliberately shows no distance: it's still a strike.
            self.shape = "FLY"
            self.is_foul_hr = True
            angle = screen_line + foul_side * random.uniform(*FOUL_HR_OFF_RAD)
            bias = random.random() ** HR_CARRY_BIAS_EXPONENT
            carry_ft = HR_CARRY_MIN_FT + bias * (
                HR_CARRY_BASE_RANGE_FT + q * HR_CARRY_QUALITY_BONUS_FT)
            self._hit_end = _polar_point(
                angle, _wall_r_at(angle) + carry_ft * _px_per_ft_at(angle))
            self._hit_peak = HR_PEAK_H
            self._foul_flight_ms = HR_DURATION_MS
            pool = ("LF", "3B") if foul_side > 0 else ("RF", "1B")
            drift_role = self._closest_role_in(pool, self._hit_end)
        else:
            # Generic foul: off-line angle grows with timing severity so a
            # barely-foul swing hugs the line while a badly mistimed one
            # sprays sharply foul. Depth is quality-centered inside the
            # per-shape range (same style as _pick_hit_landing).
            off = severity * FOUL_OFF_MAX_RAD + random.gauss(0.0, math.radians(4))
            if self.shape == "GROUNDER":
                # Choppers need to clearly leave fair ground.
                off = max(off, math.radians(10))
            off = max(math.radians(2), min(math.radians(55), off))
            angle = field_line + foul_side * off
            dist_min, dist_max = FOUL_LANDING_FT[self.shape]
            mid = dist_min + (dist_max - dist_min) * q
            spread = (dist_max - dist_min) * 0.18
            dist_ft = random.uniform(max(dist_min, mid - spread),
                                     min(dist_max, mid + spread))
            end = _clamp_inside_wall(_polar_point_ft(angle, dist_ft),
                                     LANDING_WALL_MARGIN_PX)
            self._hit_end = (max(15.0, min(1265.0, end[0])), min(712.0, end[1]))
            if self.shape == "FLY":
                lo, hi = FLY_HIT_PEAK_RANGE
                self._hit_peak = lo + q * (hi - lo)
            elif self.shape == "LINER":
                self._hit_peak = random.uniform(*LINER_PEAK_RANGE)
            else:  # GROUNDER
                self._hit_peak = 0
                dist_px = math.hypot(self._hit_end[0] - HOME[0],
                                     self._hit_end[1] - HOME[1])
                self._grounder_peaks = _grounder_peaks(q, dist_px)
            self._foul_flight_ms = FOUL_FLIGHT_MS[self.shape]
            if foul_side > 0:
                pool = ("LF",) if dist_ft > 150 else ("3B",)
            else:
                pool = ("RF",) if dist_ft > 150 else ("1B",)
            drift_role = pool[0]

        self.duration_ms = self._foul_flight_ms + FOUL_HOLD_MS

        # One side-appropriate fielder drifts toward the landing spot but
        # pulls up short — sells "lets it drop foul". Everyone else keeps
        # the standard lean-at-the-ball sway.
        drift = self.fielders[drift_role]
        ddx = self._hit_end[0] - drift.home_pos[0]
        ddy = self._hit_end[1] - drift.home_pos[1]
        d = math.hypot(ddx, ddy) or 1.0
        back = min(25.0, d)
        drift.target = (self._hit_end[0] - back * ddx / d,
                        self._hit_end[1] - back * ddy / d)
        self._lean_excluded = {drift_role}

    # ---- Helpers --------------------------------------------------------

    def _closest_role_in(self, roles, target):
        return min(roles, key=lambda r: math.hypot(
            self.fielders[r].home_pos[0] - target[0],
            self.fielders[r].home_pos[1] - target[1]))

    def _max_intercept_dist(self, fielder):
        """How far this fielder may range from home to play the ball in
        flight, **in real feet**. Single source of truth for every
        in-flight routing decision — eligibility (`can_make`), the fallback
        primary pick, and the mid-flight retarget to the landing point
        all read it, so a capped fielder can never be handed a target
        outside their range by one path after another path rejected it.

        What is left here is positional, not temporal. The infielder range
        caps that used to sit alongside these were corrections for the
        animation clock and are gone — a real sprint against a real flight
        time reproduces them. A pitcher in his follow-through and a
        crouched catcher genuinely do have tiny fielding zones at any
        pacing, and the 1B genuinely does owe the bag, so those stay.
        """
        max_dist = ROLE_MAX_INTERCEPT_DIST_FT.get(fielder.role, float('inf'))
        # The 1B's cap on grounders isn't mobility, it's responsibility:
        # every step away from the bag is a step back before the throw
        # lands. See FIRST_BASE_GROUNDER_RANGE_FT.
        if fielder.role == "1B" and self.shape == "GROUNDER":
            max_dist = min(max_dist, FIRST_BASE_GROUNDER_RANGE_FT)
        return max_dist

    def _range_ft(self, fielder, point):
        """How far `point` is from this fielder's home position, in feet."""
        return _ft_dist(point[0] - fielder.home_pos[0],
                        point[1] - fielder.home_pos[1])

    def _play_geometry(self, fielder):
        """Where the fielder took the ball, and how hard a play that made it.

        One definition of "how hard was this play", for the same reason
        `defense.RANGING_FULL_FT` imports `infield_timing.RELEASE_STRETCH_FT`
        rather than restating it: the release clock, the misplay roll and the
        clean-play counterfactual all grade the same play, and three copies
        of the inputs are three chances for them to grade it differently.

        Returns `(catch_ft, ball_distance_ft, ranging_ft, is_charging)`.
        """
        catch_ft = _to_field_ft(fielder.pos)
        home_ft = _to_field_ft(fielder.home_pos)

        # Charging = the fielder came up through the ball, toward the
        # plate. That is the barehand play on a slow roller, and it is
        # faster to release than a set throw, not slower.
        is_charging = (math.hypot(*catch_ft)
                       < math.hypot(*home_ft) - CHARGING_MARGIN_FT)

        return (catch_ft, math.hypot(*catch_ft),
                self._range_ft(fielder, fielder.pos), is_charging)

    def _range_limited_point(self, fielder, point):
        """`point` clamped to the fielder's in-flight ranging radius.

        A fielder handed a target beyond their range runs at it until
        they hit the edge of their zone and pulls up there — which is
        what the ball beating a diving infielder looks like — instead of
        tracking it down from 60 ft away.

        The clamp is computed in feet and applied along the *screen*
        direction, so the zone it carves out is the ellipse the projection
        makes of a real circle — a fielder's range is round on the field,
        not on the screen.
        """
        cap_ft = self._max_intercept_dist(fielder)
        if cap_ft == float('inf'):
            return point
        hx, hy = fielder.home_pos
        dx, dy = point[0] - hx, point[1] - hy
        d_ft = _ft_dist(dx, dy)
        if d_ft <= cap_ft:
            return point
        scale = cap_ft / d_ft
        return (hx + scale * dx, hy + scale * dy)

    def _pursuit_point(self, fielder, landing):
        """Where the primary fielder runs during the flight.

        Inside their range, that's the landing spot — a straight line to
        where the ball will be beats trailing it through a pursuit curve,
        and the pacing that produces the hit/out split is tuned against
        exactly that route.

        Outside it, the range-limited landing spot is a *fixed* point on
        the edge of their zone, and a fielder who reaches a fixed point
        has nothing left to do. On a ball up the middle the 2B got there
        with a third of the flight still to run and stood perfectly still
        while it rolled past — then, the instant it landed and the
        post-landing chase engaged, went straight into a sprint. So once
        they've made it to the pull-up spot, aim at the range-limited
        *live* ball instead: the target slides along the edge of their
        zone as the ball goes by, and they keep drifting after it under
        their own momentum. They still never reach it — the cap is
        untouched, and being beaten by the ball is the whole point of it.
        """
        if self._range_ft(fielder, landing) <= self._max_intercept_dist(fielder):
            return landing
        pull_up = self._range_limited_point(fielder, landing)
        if not fielder.pulled_up:
            if math.dist(fielder.pos, pull_up) > PULL_UP_ARRIVED_PX:
                return pull_up
            fielder.pulled_up = True
            fielder.max_speed = fielder.base_max_speed * PULL_UP_DRIFT_SPEED_FRAC
        return self._range_limited_point(fielder, self._ball)

    def _roll_pitcher_clean_field(self):
        """Decide, once per batted ball, whether the pitcher can field a
        ball hit back through the box. Hard contact goes through them;
        weak contact is the comebacker they actually convert. See
        PITCHER_CLEAN_FIELD_PROB.
        """
        band = PITCHER_CLEAN_FIELD_PROB.get(self.shape)
        if band is None:
            return True
        soft, hard = band
        q = max(0.0, min(1.0, self.quality))
        return random.random() < soft + (hard - soft) * q

    def _eligible_intercept_pool(self):
        """Which fielders can plausibly field this ball in flight.

        Grounders are played in flight only by IFs and the pitcher — if
        the ball gets past them it has to roll into the OF for retrieval,
        not be magically caught on a single bounce by the LF. Pop-ups
        belong to the diamond. Flies and liners can be caught by anyone
        in the ball's path.

        The pitcher drops out entirely when they lost the clean-fielding
        roll for this play (_pitcher_fields_clean) — that's what lets a
        ball smoked up the middle pass through the box instead of being
        converted by the one defender the trajectory is guaranteed to
        run through.
        """
        if self.shape == "GROUNDER":
            pool = ["P", "1B", "2B", "SS", "3B"]
        elif self.shape == "POP_UP":
            # Real baseball: infielders always call off the pitcher and
            # catcher on pop-ups in fair territory. Including P/C in the
            # pool sent the pitcher chasing every centered pop-up, which
            # they almost never field in reality.
            pool = ["1B", "2B", "SS", "3B"]
        else:
            pool = list(ROLES)
        if not self._pitcher_fields_clean and "P" in pool:
            pool.remove("P")
        # A fielder the ball has already gone through has had their chance.
        # Without this they re-intercept on the next frame and the
        # through-ball never happens. Same mechanism as the pitcher's roll
        # above, applied at the moment of the reach rather than at setup.
        if self._beaten_roles:
            pool = [r for r in pool if r not in self._beaten_roles]
        return pool

    def _path_intercept(self, fielder):
        """Best intercept point on the ball's flight path for `fielder`.

        Returns a dict with the closest path point to the fielder, the
        ball's time-of-arrival at that point, the fielder's time-of-arrival
        (reaction delay + sprint), and a `can_make` flag — True when the
        fielder arrives no later than the ball plus INTERCEPT_GRACE_S.

        Shape-aware target selection:
            FLY / POP_UP — the ball is far above the path until it
                descends to landing, so an "on-path" intercept at a mid-
                path point is meaningless (ball is overhead). Target the
                landing point instead — that's where the ball comes down
                to glove height.
            GROUNDER / LINER — low-arc shapes catchable anywhere along
                the path; the perpendicular foot is the optimal point.

        Fielders *behind* the contact point (t_proj < 0 — the ball is
        going the other way) are marked can_make=False so they don't win
        the primary-selection race by virtue of being near home plate.
        Without this guard the catcher reliably "intercepts" every deep
        ball at the contact point, because the clamped intercept lands
        right next to them.

        Fielders past the far end (t_proj > 1) are *not* excluded: the
        ball is coming toward them and stops short, which is a fielder
        charging, the most ordinary play there is. Excluding them (the
        guard used to reject both ends) meant a shallow fly could not be
        caught by the outfielder it was hit to — only by whoever was
        standing in front of it — so infielders drifted back on 34% of
        all fly balls and outfielders never charged. On grounders it
        handed a ball dying at the 2B's feet to the 1B. Range caps and
        the timing gate below are what keep the far end honest; the
        segment test was never the right tool for it.
        """
        home = fielder.home_pos
        px = self._hit_end[0] - HOME[0]
        py = self._hit_end[1] - HOME[1]
        path_len_sq = px * px + py * py
        if path_len_sq < 1.0:
            return {
                "point": home,
                "ball_arrives_ms": 0.0,
                "fielder_arrives_ms": float('inf'),
                "fielder_dist_ft": float('inf'),
                "can_make": False,
            }
        hx = home[0] - HOME[0]
        hy = home[1] - HOME[1]
        t_proj_raw = (hx * px + hy * py) / path_len_sq
        ahead_of_contact = t_proj_raw >= 0.0
        t_proj = max(0.0, min(1.0, t_proj_raw))

        # FLY/POP_UP route to landing; GROUNDER/LINER to the perp foot.
        if self.shape in ("FLY", "POP_UP"):
            intercept = self._hit_end
            ball_arrives = self.duration_ms
        else:
            intercept = (HOME[0] + t_proj * px, HOME[1] + t_proj * py)
            # Not `t_proj * duration_ms`: the ball decelerates, so it is
            # ahead of the linear schedule everywhere in between and only
            # meets it at the two ends. Timing an infielder against the
            # linear one would have them break on a ball that is already
            # past them.
            ball_arrives = self._flight_time_fraction(t_proj) * self.duration_ms

        f_dist_ft = _ft_dist(intercept[0] - home[0], intercept[1] - home[1])
        f_travel = self._travel_ms(fielder, home, intercept)
        f_arrives = fielder.reaction_delay_ms + f_travel

        max_dist = self._max_intercept_dist(fielder)

        # Fielders behind the plate relative to the ball's bearing can't
        # make the play in flight — the ball is travelling away from
        # them. The catcher, and the corner OF when the ball is hit to
        # the opposite side of the diamond, both fall in this bucket and
        # should lean, not lead.
        can_make = (ahead_of_contact
                    and f_dist_ft <= max_dist
                    and f_arrives <= ball_arrives + self._anim_ms(INTERCEPT_GRACE_S))
        return {
            "point": intercept,
            "ball_arrives_ms": ball_arrives,
            "fielder_arrives_ms": f_arrives,
            "fielder_dist_ft": f_dist_ft,
            "can_make": can_make,
        }

    def _assign_in_play_targets(self):
        """Route every eligible fielder to their optimal intercept point.

        Replaces the legacy "pick one primary by home-distance to landing"
        routing — under that model, fielders not picked as primary stood
        flat-footed leaning toward the ball while a grounder visibly
        rolled past them. The new model routes every defender who has a
        plausible play to *their* intercept point on the path; out vs.
        hit then emerges from whether any of them reaches the ball.
        """
        pool = self._eligible_intercept_pool()
        intercepts = {role: self._path_intercept(self.fielders[role]) for role in pool}

        # Score: the play happens at max(ball_arrives, fielder_arrives) —
        # whichever party gets there last is the moment of intercept.
        # Smaller is better. Used to rank *backup* commitment, not to pick
        # the fielder (see below).
        def score(role):
            d = intercepts[role]
            return max(d["ball_arrives_ms"], d["fielder_arrives_ms"])

        # Primary selection respects `can_make` — a fielder who physically
        # can't reach the intercept point shouldn't be picked as primary
        # just because the path geometry puts the perp foot near their
        # home. Most acute on grounders, where the pitcher's perp foot is
        # often <30 px from the mound and they win the race despite the
        # actual intercept being a slap shot past the mound. Without this
        # filter the pitcher was primary on ~70% of grounders and visibly
        # ran around the mound on the third of those where the routed
        # point wandered off it.
        #
        # Among fielders who can make the play, the ball belongs to
        # whoever has to move least to get to it — the real rule, and the
        # one thing `score` cannot express. Scoring on the *moment* of
        # intercept systematically hands the ball to whoever stands
        # nearest home plate, because the ball reaches their stretch of
        # the path first: a grounder hit dead at the 2B was fielded by
        # the 1B 100% of the time (the path passes ~30 ft to their side
        # earlier in its flight), and one hit at the SS by the 3B. The
        # fielder actually standing on the ball then got treated as a
        # spare part and, worse, was free to be sent to cover first.
        #
        # Ranking by distance also fixes FLY/POP_UP, where every eligible
        # fielder routes to the same landing point and therefore has an
        # identical score — the winner was decided by `sorted`'s stability
        # over pool order, which is how the 1B came to catch 45% of all
        # pop-ups and infielders 36% of all fly balls.
        #
        # If no fielder can make the play in flight (the ball gets past
        # everyone — a base hit), the post-land chase takes over anyway;
        # we just pick whoever's home is closest to the landing so the
        # initial scramble has a sensible lead.
        pool_sorted = sorted(pool, key=score)
        makeable = [r for r in pool_sorted if intercepts[r]["can_make"]]
        retrieval_point = None
        if makeable:
            self._primary_role = min(
                makeable,
                key=lambda r: (intercepts[r]["fielder_dist_ft"], score(r)),
            )
        else:
            self._primary_role, retrieval_point = self._pick_retrieval_role(pool)
        # Where the primary is actually going, when it isn't the landing
        # spot. Read back by the in-flight motion block, which would
        # otherwise overwrite the target with the landing point on every
        # frame and undo the pick above.
        self._retrieval_point = retrieval_point
        primary = self.fielders[self._primary_role]
        pri_int = intercepts[self._primary_role]

        # When the ball gets fielded, as best we can tell before it's
        # thrown: the later of the two arrivals at the intercept point.
        # This is what the cover man's deadline is measured from.
        self._fielded_at_ms = score(self._primary_role)

        # Clamped, because the no-makeable-fielder fallback above can pick
        # a fielder whose own range cap disqualifies the point they were
        # picked for.
        primary.target = self._range_limited_point(
            primary, retrieval_point or pri_int["point"])
        primary.decel_radius_px = SECURE_RADIUS_PX
        self._primary_start = primary.home_pos
        self._primary_full_speed = primary.max_speed

        # Pace the primary so they ARRIVE at the intercept point when the
        # ball does — earlier and they stand under the ball waiting (the
        # original visual bug, in reverse); later and they miss. If they
        # can't make it at full sprint, leave them at full speed — the
        # ball will get past them and the post-landing chase takes over.
        if pri_int["fielder_arrives_ms"] < pri_int["ball_arrives_ms"]:
            # Pace in ft/s, the unit max_speed is now in. Computing it as
            # px-over-animated-ms and assigning that to max_speed would put
            # a px/ms number in a ft/s field — the fielder would jog or
            # teleport depending on which way the ball went.
            budget_s = max(
                0.01,
                (pri_int["ball_arrives_ms"] - primary.reaction_delay_ms)
                / (1000.0 * self.time_scale),
            )
            f_dist_ft = _ft_dist(pri_int["point"][0] - primary.home_pos[0],
                                 pri_int["point"][1] - primary.home_pos[1])
            primary.max_speed = min(self._primary_full_speed,
                                    f_dist_ft / budget_s)

        excluded = {self._primary_role}

        # The outfielder whose part of the field it is runs the ball down
        # from the first frame, whether or not anyone in front of them has
        # a play on it. That is what an outfielder does, and leaving it out
        # was the largest remaining hole in the defense once the ball
        # stopped dying where it landed.
        #
        # What it looked like: a line drive down the right-field line, the
        # 1B picked as primary because they genuinely can reach the path,
        # tracking it to within 10 ft at 100 ft out — and missing. By then
        # the ball had 130 ft of roll left and the right fielder, who had
        # moved 15 ft in two and a half seconds, was 92 ft behind it and
        # never got there. The ball reached the wall on 23% of line drives
        # and doubles ran at 46% of hits against a real 25%.
        #
        # `_pick_retrieval_role` is the same path search the primary
        # fallback uses, restricted to the three outfielders, so the answer
        # is "where do I meet this ball", not "where does it land".
        backup_role, backup_point = self._pick_retrieval_role(OUTFIELD_ROLES)
        if backup_role is not None and backup_role != self._primary_role:
            backup = self.fielders[backup_role]
            backup.target = backup_point
            backup.decel_radius_px = SECURE_RADIUS_PX
            excluded.add(backup_role)

        # Grounders: somebody covers the bag from the first frame — the 1B
        # normally, the pitcher/2B when the 1B is the one fielding it.
        # This has to run BEFORE the secondaries loop, or a cover man
        # whose timing put them in the secondary window would get routed
        # on a 25% chase instead and leave the bag empty when the actual
        # fielder threw across the diamond. Pre-excluding them here keeps
        # the secondaries loop from overwriting the bag target.
        if self.shape == "GROUNDER":
            cover_role, _ = self._route_first_base_cover(self._primary_role)
            if cover_role is not None:
                excluded.add(cover_role)

        # Secondary fielders within a timing margin lean toward their
        # own intercept points — modeling the backup defender shifting
        # to cover. Kept at a partial route (25%) so they aren't
        # *also* in catch range — only the primary gets a real shot at
        # an in-flight catch. Without this restraint, the secondary
        # ended up at the same intercept point as the primary and
        # turned medium-aimed liners into outs at unrealistic rates.
        primary_score = score(self._primary_role)
        for role in pool_sorted:
            if role in excluded:
                # The primary, and anyone locked into a cover assignment,
                # already have targets — skip past, because later roles in
                # the sorted list may still qualify as secondaries.
                continue
            # Absolute gap, and no early `break`: now that the primary is
            # picked on distance rather than timing, they no longer hold
            # the minimum score, so roles on *either* side of them in this
            # list can be backing up the same play. A fielder whose
            # intercept resolves well before or well after the primary's
            # is playing a different moment of the ball's flight and
            # shouldn't commit to it.
            if abs(score(role) - primary_score) > self._anim_ms(INTERCEPT_GRACE_S) * 2:
                continue
            # Same can_make filter as primary selection — a fielder who
            # can't physically reach the intercept point shouldn't get
            # a 25% commit toward it either. They lean by default.
            if not intercepts[role]["can_make"]:
                continue
            d = intercepts[role]
            f = self.fielders[role]
            back = _lerp(f.home_pos, d["point"], 0.25)
            f.target = back
            excluded.add(role)

        # Cutoff infielder for deep balls — same XBH-relay positioning
        # the legacy code used, so the visual depth-of-play still reads
        # right when the corner OF has a long chase.
        landing_dist = math.hypot(
            self._hit_end[0] - HOME[0],
            self._hit_end[1] - HOME[1],
        )
        if landing_dist > 280:
            cutoff = "SS" if self._hit_end[0] < HOME[0] else "2B"
            if cutoff not in excluded:
                cutoff_home = self.fielders[cutoff].home_pos
                self.fielders[cutoff].target = _lerp(cutoff_home, self._hit_end, 0.45)
                excluded.add(cutoff)

        self._lean_excluded = excluded

    def _pick_retrieval_role(self, pool):
        """Nobody can catch it, so the play is a retrieval: whoever gets to
        the ball first once it is on the ground. Returns `(role, point)`.

        The fallback this replaced picked whoever's *home* was nearest the
        landing spot, which is only the same question when the ball stops
        where it lands. It does not: a line drive coming down at 226 ft is
        still doing 71 ft/s and has 130 ft to go. So the ball went to the
        second baseman, who chased it into right field while the right
        fielder — standing 76 ft beyond the landing point, with the ball
        rolling straight at them — held their ground and watched. The ball
        then reached the wall on 23% of line drives.

        Searching the ball's own path fixes it without a special case for
        who plays where: a fielder beyond the landing point wins because
        the ball comes to them, one in front of it loses because it is
        running away, and the flight time counts toward everybody's
        journey because they are all already moving.
        """
        path = self._landing_ground_path()
        px_per_ft = self._landing_px_per_ft()
        dx = self._hit_end[0] - HOME[0]
        dy = self._hit_end[1] - HOME[1]
        norm = math.hypot(dx, dy)
        ux, uy = (dx / norm, dy / norm) if norm > 1e-9 else (0.0, -1.0)
        flight_ms = self._anim_ms(self.flight_time_s)
        # One path, walked once — every fielder is racing the same ball.
        route = [(flight_ms + self._anim_ms(t_s),
                  _clamp_inside_wall(
                      (self._hit_end[0] + ux * dist_ft * px_per_ft,
                       self._hit_end[1] + uy * dist_ft * px_per_ft),
                      BALL_WALL_MARGIN_PX))
                 for t_s, dist_ft in ground_roll.trajectory(path)]

        best_role, best_point, best_ms = None, None, None
        for role in pool:
            fielder = self.fielders[role]
            for arrives_ms, point in route:
                if self._eta_to_point(fielder, point) <= arrives_ms:
                    if best_ms is None or arrives_ms < best_ms:
                        best_role, best_point, best_ms = role, point, arrives_ms
                    break
        if best_role is None:
            # Nobody beats it anywhere on its path — a ball to the wall.
            # Closest home to where it comes to rest, so the scramble at
            # least starts in the right direction.
            rest = _clamp_inside_wall(
                (self._hit_end[0] + ux * path.total_distance_ft * px_per_ft,
                 self._hit_end[1] + uy * path.total_distance_ft * px_per_ft),
                BALL_WALL_MARGIN_PX)
            return self._closest_role_in(pool, rest), rest
        return best_role, best_point

    def _eta_to_point(self, fielder, point, reaction_ms=None):
        """Approximate ms for `fielder` to reach `point` from where they
        currently stand, at their true (un-paced) sprint speed.

        Mirrors the phases of _step_fielder closely enough to time a throw
        against: whatever is left of the see-react delay, the acceleration
        ramp (which costs roughly half the ramp window in lost ground),
        cruise, and the slow last few pixels inside the decel radius.
        Deliberately a little pessimistic — arriving at the bag early and
        waiting looks fine, arriving late is the bug this exists to fix.

        `reaction_ms` overrides which reaction clock to charge; callers
        timing a run to a *base* pass `Fielder.break_delay_ms`, since the
        fielding bias in `reaction_delay_ms` doesn't gate a break to the
        bag.
        """
        dist = math.hypot(point[0] - fielder.pos[0], point[1] - fielder.pos[1])
        if dist < 1.0:
            return 0.0
        if reaction_ms is None:
            reaction_ms = fielder.reaction_delay_ms
        reaction = max(0.0, reaction_ms - self._elapsed)
        ramp = self._anim_ms(fielder.accel_time_s * 0.5)
        run = self._travel_ms(fielder, fielder.pos, point,
                              speed_fts=fielder.base_max_speed)
        # The slow last stride into the bag, charged as a fraction of the
        # run it belongs to rather than as a separate distance/speed — the
        # latter needed a px/ms speed, which no longer exists.
        decel_extra = 0.7 * run * min(dist, SECURE_RADIUS_PX) / dist
        return reaction + ramp + run + decel_extra

    def _route_first_base_cover(self, fielding_role):
        """Assign — and keep re-assigning — somebody to first base.

        This is the fix for the play that reads worst on screen: the 1B
        breaks after a ball, a different infielder ends up fielding it,
        and the throw goes to an empty bag because the 1B is still 60 ft
        away with their back turned.

        The rule is the real one: whoever is fielding the ball is not
        covering the bag, and the bag goes to the first fielder in
        COVER_ROLE_PRIORITY who is free and can beat the throw there —
        the 1B, else the pitcher on the 3-1, and only then the 2B.
        Because it's recomputed as `fielding_role` changes, the moment
        the 1B stops being the likely fielder they abandon the chase and
        sprint back — the behaviour a real 1B has.

        Preference is strict rather than an ETA race with bonuses: the
        candidates' ETAs differ by a few hundred ms at most, so any
        weighting fine enough to keep the 1B and the pitcher ahead of the
        2B was fine enough to be flipped by per-fielder speed jitter.
        ETA is now only a veto — "can this fielder actually get there" —
        which is the one thing it should decide.

        Returns `(cover_role, eta_ms)` — the ETA is what
        _trigger_in_flight_intercept times the throw against so the ball
        and the cover man arrive together. Returns `(None, 0.0)` only if
        every candidate is somehow unavailable.
        """
        candidates = [r for r in COVER_ROLE_PRIORITY
                      if r != fielding_role and r in self.fielders]
        if not candidates:
            return None, 0.0

        # Timed on the break clock, not the fielding one — see
        # Fielder.break_delay_ms.
        etas = {r: self._eta_to_point(self.fielders[r], FIRST_BASE_BAG_POS,
                                      reaction_ms=self.fielders[r].break_delay_ms)
                for r in candidates}

        # The deadline is the throw's, not the clock's: whatever is left
        # of the ball's flight to the fielder, plus how long that fielder
        # will hold it waiting for the bag. See COVER_IN_TIME_BUDGET_S.
        budget = (max(0.0, self._fielded_at_ms - self._elapsed)
                  + self._anim_ms(COVER_IN_TIME_BUDGET_S))

        def in_time(role):
            limit = budget
            if role == self._cover_role:
                limit += self._anim_ms(COVER_INCUMBENT_BONUS_S)
            return etas[role] <= limit

        # First choice who can actually beat the throw. If nobody can (the
        # ball was fielded right next to the bag, so it's going to be an
        # unassisted play anyway), fall back to whoever is closest — the
        # assignment is cosmetic at that point.
        cover_role = next((r for r in candidates if in_time(r)),
                          min(candidates, key=etas.get))

        # Release the previous cover man if the job changed hands, so they
        # don't keep standing on a bag that isn't theirs any more. Guarded
        # against releasing someone who has since become the fielder —
        # their chase target must win.
        prev = self._cover_role
        if prev is not None and prev != cover_role and prev != fielding_role:
            old = self.fielders[prev]
            old.target = old.home_pos
            old.max_speed = old.base_max_speed
            old.decel_radius_px = FIELDER_DECEL_RADIUS_PX
            self._lean_excluded.discard(prev)

        cover = self.fielders[cover_role]
        cover.target = FIRST_BASE_BAG_POS
        # Full sprint with a tight decel zone — the cover man is racing a
        # throw. Restoring max_speed matters: if this fielder was the
        # primary a moment ago they were paced *down* to arrive with the
        # ball, and that paced speed would have them jogging to the bag.
        cover.max_speed = cover.base_max_speed
        cover.decel_radius_px = SECURE_RADIUS_PX
        self._lean_excluded.add(cover_role)
        self._cover_role = cover_role
        return cover_role, etas[cover_role]

    def _ball_past_fielder(self, fielder):
        """True when the live ball is radially past the fielder's home
        position by more than their per-role bail-out buffer.

        "Past" is measured in distance from HOME (not in raw y), so a
        slow roller down the line correctly reads as "past 3B" once it
        carries beyond 3B's natural depth, not only when its on-screen
        y dips below the bag. Outfielders are exempt — they're the
        last line of defense, and "past the OF" is the wall, not an
        OF-to-someone-else handoff.

        Pitchers and catchers use a 0 px buffer (any ball past their
        home is hands-off); the 30 px default applies to corner/middle
        infielders so they don't bail out at the very edge of their
        range.
        """
        if fielder.role in OUTFIELD_ROLES:
            return False
        d_ball = math.hypot(self._ball[0] - HOME[0], self._ball[1] - HOME[1])
        d_home = math.hypot(fielder.home_pos[0] - HOME[0],
                            fielder.home_pos[1] - HOME[1])
        bail_buffer = ROLE_BAIL_OUT_BEHIND_PX.get(fielder.role, BAIL_OUT_BEHIND_PX)
        return d_ball > d_home + bail_buffer

    def _stand_down_non_primary(self, keep_at_bag):
        """Reset every non-primary fielder back to their home position
        and rebuild self._lean_excluded so _update_lean_targets does
        not re-route them.

        Called whenever a catch fires (in-flight or post-landing).
        Without this, fielders committed to a pre-catch target — the
        pitcher's 25% secondary lerp, a cutoff IF's relay spot, the old
        primary's full sprint route — kept running long after the play
        was over, because _update_lean_targets skips _lean_excluded
        members and never wipes those stale targets.

        `keep_at_bag` preserves the cover man's target during the
        throw-to-1B sub-animation; otherwise they are also sent home.
        """
        new_excluded = {self._primary_role}
        if keep_at_bag and self._cover_role in self.fielders:
            new_excluded.add(self._cover_role)
        for role, f in self.fielders.items():
            if role in new_excluded:
                continue
            f.target = f.home_pos
            f.max_speed = f.base_max_speed
            f.decel_radius_px = FIELDER_DECEL_RADIUS_PX
        self._lean_excluded = new_excluded

    def _chases_in_flight(self, role):
        """Does this fielder actively run at a ball still in the air?

        Only the middle infielders, and only on the two low shapes. FLY
        and POP_UP already route everyone to the landing point through
        the normal primary/lean machinery, and the corner infielders have
        a base to answer for — the 1B especially, whose every step away
        from the bag is a step back before the throw.
        """
        return (role in MIDDLE_INFIELD_ROLES
                and self.shape in ("GROUNDER", "LINER"))

    def _route_in_flight_chase(self, fielder):
        """Run at the ball for as long as there is a ball to run at.

        A middle infielder breaks for the point on the flight path they
        could cut the ball off at, and sprints flat out until the ball
        reaches it. After that the ball is past them and on its way to
        the outfield, so they ease down over a wide decel radius rather
        than braking — being beaten is how this chase is supposed to
        end.

        This replaces a small "lean" that moved them 5–23 px off their
        home and then held: on a ball up the middle both middle
        infielders drifted a couple of steps and stopped while the ball
        went by 40 px away, which is the "they stop and refuse to keep
        running" report.

        Nothing bounds the distance any more. `INFIELD_CHASE_RANGE_PX`
        used to, at 130 px — a number chosen to be *further* than the old
        55 px reach cap so the chase didn't visibly stop short of a ball
        it was about to reach. Both are gone: on the honest clock the
        infielder simply runs, and the ball beats him to the outfield on
        its own, which is what the two constants were arranging by hand.
        """
        hit = self._path_intercept(fielder)
        fielder.target = hit["point"]
        if self._elapsed <= hit["ball_arrives_ms"]:
            fielder.decel_radius_px = SECURE_RADIUS_PX      # still coming — sprint
        else:
            fielder.decel_radius_px = CHASE_PULL_UP_DECEL_PX   # past — ease down

    def _update_lean_targets(self):
        """Recompute non-primary fielder targets each frame.

        Default: small "lean" toward the ball — keeps the team alive at
        rest without committing to a play. Magnitude grows with progress,
        so fielders keep moving a step at a time instead of freezing.

        After the ball has landed and is on the ground, any non-primary
        fielder within POST_LAND_CHASE_RADIUS_PX of the live ball ditches
        the lean and actively chases at full sprint — except infielders
        and P/C for whom the ball is already past their depth (see
        _ball_past_fielder); those defer to the OFs instead of sprinting
        deep into someone else's zone. OFs always chase.

        Once the ball is secured, this method bails out entirely — the
        catch handler has just reset every non-essential fielder to
        their home position, and re-running the lean loop would
        immediately drag them back toward the ball/catcher.
        """
        if self._secured:
            return
        progress = min(1.0, self._elapsed / max(1, self.duration_ms))
        max_lean = LEAN_BASE_PX + LEAN_GROWTH_PX * progress
        focus = self._ball
        ball_on_ground = (self._needs_secure
                          and self._elapsed > self.duration_ms
                          and not self._secured)
        for role, f in self.fielders.items():
            if role in self._lean_excluded:
                continue
            if not ball_on_ground and self._chases_in_flight(role):
                self._route_in_flight_chase(f)
                continue
            if ball_on_ground and not self._ball_past_fielder(f):
                chase_radius = ROLE_POST_LAND_CHASE_RADIUS_PX.get(
                    role, POST_LAND_CHASE_RADIUS_PX
                )
                d_ball = math.hypot(focus[0] - f.pos[0],
                                    focus[1] - f.pos[1])
                if d_ball < chase_radius:
                    # Route to where the ball will come to rest, not where
                    # it currently is — a straight-line run to the
                    # predicted stop reaches the ball faster than chasing
                    # a moving target through a pursuit curve. Visually
                    # this is what makes OFs "cut off" rolling balls
                    # instead of trailing them across the screen.
                    f.target = self._predict_ball_stop()
                    # Tight decel zone so the chaser doesn't ease off
                    # before reaching the ball — secure-radius approach.
                    f.decel_radius_px = SECURE_RADIUS_PX
                    continue
            home = f.home_pos
            dx = focus[0] - home[0]
            dy = focus[1] - home[1]
            dist = math.hypot(dx, dy) or 1.0
            f.target = (home[0] + max_lean * dx / dist,
                        home[1] + max_lean * dy / dist)

    def _step_fielder(self, fielder, dt_ms, elapsed_ms):
        """Stateful motion with smooth accel/decel ramps.

        Phases:
          1. Reaction delay — fielder reads the ball; the speed fraction
             decays to 0 (carries no momentum into the next play).
          2. Acceleration — the fraction ramps linearly toward 1.0 over
             accel_time_s.
          3. Cruise — the fraction sits at 1.0 (full sprint).
          4. Deceleration — the target fraction is scaled by
             dist/decel_radius_px (with a floor) and ramps down to it.

        The stateful current_speed_frac is what kills the "sudden sprint"
        artifact: when a fielder's target switches from a near-home
        lean to a far-away chase target, decel_factor jumps from
        ~FLOOR back up to 1.0, but the fraction can only climb by
        frac_step per frame — so the eye sees a smooth ramp instead
        of a one-frame velocity discontinuity.

        max_speed, accel_time_s, and decel_radius_px are per-fielder so
        the team naturally staggers.

        The fielder currently covering first is on the shorter
        `break_delay_ms` clock: they are running to a base, not reading a
        batted ball. Left on the fielding clock the pitcher stood on the
        mound for the first ~1.2 s of every 3-1 play before starting for
        the bag, which is the visual half of the bug that had the 2B
        taking the throw instead.
        """
        if dt_ms <= 0:
            return

        # Ramp in *fraction of top speed* rather than in px/ms. The px/ms a
        # fielder is worth depends on which way they are pointing (see
        # `_travel_ms`), so a stateful speed in px/ms would jump whenever
        # the target moved them from a lateral run to a radial one — a
        # discontinuity indistinguishable from the "sudden sprint" the
        # stateful ramp exists to prevent.
        frac_step = dt_ms / max(1.0, self._anim_ms(fielder.accel_time_s))

        reaction_ms = (fielder.break_delay_ms if fielder.role == self._cover_role
                       else fielder.reaction_delay_ms)
        if elapsed_ms < reaction_ms:
            fielder.current_speed_frac = max(0.0, fielder.current_speed_frac - frac_step)
            return

        # Run at the target, but never past the fence. Clamping here as
        # well as after the step matters: a target beyond the wall left
        # the fielder pinned against the clamp with `dist` still large,
        # so they never stopped sprinting and jittered at the wall. Aimed
        # at the containment point instead, they arrive and settle like
        # any other arrival.
        tx, ty = _clamp_inside_wall(fielder.target, FIELDER_WALL_MARGIN_PX)
        dx = tx - fielder.pos[0]
        dy = ty - fielder.pos[1]
        dist = math.hypot(dx, dy)

        if dist < 0.5:
            fielder.current_speed_frac = max(0.0, fielder.current_speed_frac - frac_step)
            return

        if dist < fielder.decel_radius_px:
            decel_factor = max(FIELDER_DECEL_FLOOR, dist / fielder.decel_radius_px)
        else:
            decel_factor = 1.0

        if decel_factor > fielder.current_speed_frac:
            fielder.current_speed_frac = min(
                decel_factor, fielder.current_speed_frac + frac_step)
        elif decel_factor < fielder.current_speed_frac:
            fielder.current_speed_frac = max(
                decel_factor, fielder.current_speed_frac - frac_step)

        # Full-sprint px/ms along *this* direction, then scaled by the ramp.
        full_ms = self._travel_ms(fielder, fielder.pos, (tx, ty))
        step = dist * fielder.current_speed_frac * dt_ms / max(1e-6, full_ms)
        if dist <= step:
            # Arriving snaps the *position*, never the speed. Zeroing it
            # here was a one-frame stop from a full sprint — precisely the
            # discontinuity the stateful ramp above exists to prevent — and
            # it parked the fielder at rest, so the next target switch had
            # to ramp up from a standing start. That pair is what made a
            # pulled-up infielder freeze dead and then visibly burst into a
            # sprint when the post-landing chase engaged. Decay at the
            # normal rate instead, like every other arrival path.
            fielder.pos[0] = tx
            fielder.pos[1] = ty
            fielder.current_speed_frac = max(0.0, fielder.current_speed_frac - frac_step)
        else:
            fielder.pos[0] += dx / dist * step
            fielder.pos[1] += dy / dist * step

    def _ball_behind_wall(self):
        """True when the wall is between the ball and the camera.

        Two conditions, and both are needed. The ball has to be out of
        the park — asked of its *shadow*, the ground point — and it has
        to be below the top of the fence, or we would be hiding a ball
        that is sailing over it. That second term is why a home run
        stays on screen for its whole arc and then drops out of sight in
        its last few feet, instead of blinking out at the apex the
        moment it crossed the fence line.

        Without this the HOME RUN branch of `_update_hit` parked the
        ball at its landing point and left it sitting in the black
        beyond the wall for the remaining seconds of the animation.

        The lift is read off the rendered pair — the ball is drawn at
        `shadow_y - lift` — and converted with FT_TO_PX_Y, the same
        vertical scale the glove-reach test uses.
        """
        if not _point_outside_wall(self._ball_shadow):
            return False
        lift_px = self._ball_shadow[1] - self._ball[1]
        return lift_px < WALL_HEIGHT_FT * FT_TO_PX_Y

    def _contain_fielders(self):
        """Keep every defender inside the outfield wall.

        See FIELDER_WALL_MARGIN_PX. Cheap enough to run unconditionally
        over all nine every frame, and it is a no-op for the eight of
        them who are nowhere near the fence.
        """
        for f in self.fielders.values():
            cx, cy = _clamp_inside_wall(f.pos, FIELDER_WALL_MARGIN_PX)
            f.pos[0] = cx
            f.pos[1] = cy

    # ---- Ball on ground -------------------------------------------------

    def _init_ball_on_ground(self):
        """Initialize stateful ball physics at the landing transition.

        `ground_roll` owns the physics and states it in feet and seconds;
        this is the single place it becomes screen motion. The *direction*
        comes from the flight — horizontal motion is linear in all four arc
        shapes, so the ground-frame bearing at landing is exactly
        (hit_end − HOME); sampling the rendered arc instead would leak the
        sin lift into the y component and push the ball deeper. The
        *magnitude* is not taken from the flight either: a batted ball
        lands at its own speed, near terminal velocity, and how fast the
        animation happened to fly it has no claim on what that is.

        It is no longer a change of speed, though. The flight decelerates
        onto exactly this number — `_landing_speed_ratio` reads it off the
        same cached `GroundPath` — so this transition is now continuous in
        velocity as well as position, and the ball stops appearing to hit
        a wall of molasses where the model changes hands.
        """
        self._ball_pos = [self._hit_end[0], self._hit_end[1]]

        # The flight is over, so nobody is pulled up any more — it is a
        # ranging state that only exists while the ball is in the air. This
        # is the one hook that fires exactly once at the landing transition,
        # which makes it the place to give back the drift speed cap: a
        # fielder the ball beat in flight has to be able to sprint after it
        # like anyone else once the post-landing chase engages.
        for f in self.fielders.values():
            if f.pulled_up:
                f.pulled_up = False
                f.max_speed = f.base_max_speed

        dx = self._hit_end[0] - HOME[0]
        dy = self._hit_end[1] - HOME[1]
        dist_px = math.hypot(dx, dy)
        self._ball_px_per_ft = self._landing_px_per_ft()
        self._ground_path = self._landing_ground_path()

        speed_px_ms = self._fts_to_px_ms(self._ground_path.speed_fts)
        if dist_px > 1e-9:
            self._ball_v = [dx / dist_px * speed_px_ms,
                            dy / dist_px * speed_px_ms]
        else:
            self._ball_v = [0.0, 0.0]

        # Hop schedule on the animated clock: (start_ms, duration_ms,
        # height_px, retention). The retention is applied to the velocity
        # at the *start* of its hop — that is the ground contact — and then
        # the ball is left alone until the next one, because a ball in the
        # air is not being braked by grass.
        self._bounces = []
        t_start = 0.0
        for hop in self._ground_path.hops:
            dur = self._anim_ms(hop.duration_s)
            self._bounces.append(
                (t_start, dur, hop.height_ft * FT_TO_PX_Y, hop.retention))
            t_start += dur
        self._bounces_end_ms = t_start  # ball is rolling after this
        # Impacts already applied — the schedule has one per hop plus the
        # contact that ends the hopping, so this runs to len(hops) + 1.
        self._bounces_completed = 0

    def _landing_px_per_ft(self):
        """Pixels per foot along the ball's bearing.

        The projection is anisotropic, so this is the only honest way to
        carry a real speed or a real distance onto the screen — same
        reasoning as `_ft_dist` and `_px_per_ft_at`.
        """
        dx = self._hit_end[0] - HOME[0]
        dy = self._hit_end[1] - HOME[1]
        dist_ft = _ft_dist(dx, dy)
        if dist_ft <= 1e-9:
            return FT_TO_PX_X
        return math.hypot(dx, dy) / dist_ft

    def _landing_ground_path(self):
        """The ball's post-landing physics, from `ground_roll`.

        Deterministic in the shape, the exit velocity and where the ball
        comes down, all of which are fixed at setup — so the defense can
        ask this before the ball has landed, which is what
        `_pick_retrieval_role` needs to route the right fielder at it.
        Cached for the same reason: it is one ball, and the routing pass
        and the landing transition have to be looking at the same one.
        """
        if self._landing_path_cache is not None:
            return self._landing_path_cache
        dist_ft = _ft_dist(self._hit_end[0] - HOME[0], self._hit_end[1] - HOME[1])
        ev = self.exit_velocity_mph
        if self.shape == "GROUNDER":
            # A grounder has no landing transition — it has been on the
            # grass the whole way and its hops are already modelled in
            # flight (_grounder_peaks / _arc_grounder). What it has is an
            # end-of-path speed, taken from the same retention curve the
            # infield verdict is computed against, and no rebound to give
            # it a fresh hop.
            average = dist_ft / max(1e-6, self.flight_time_s)
            path = ground_roll.ground_path(
                self.shape, average * ground_roll.grounder_landing_fraction(ev),
                descent_deg=0.0)
        else:
            path = ground_roll.ground_path(
                self.shape,
                ground_roll.landing_speed_fts(
                    self.shape, ev, dist_ft, self.flight_time_s),
                ev_mph=ev)
        self._landing_path_cache = path
        return path

    def _landing_speed_ratio(self):
        """The ball's landing speed as a fraction of its average, or 1.0.

        The single number the flight's deceleration is parameterised on —
        see the note above `_decel_path_fraction`. Taken from the same
        cached `GroundPath` that `_init_ball_on_ground` will start the
        roll from, which is what makes the two continuous: whatever speed
        the ball is handed to `ground_roll` at is the speed it was already
        travelling on the last frame of the flight.

        1.0 for the scripted flights, which have no landing to be
        continuous with — a HOME RUN never touches the grass in view.
        """
        if not self._needs_secure or self.flight_time_s <= 0:
            return 1.0
        dist_ft = _ft_dist(self._hit_end[0] - HOME[0], self._hit_end[1] - HOME[1])
        average = dist_ft / self.flight_time_s
        if average <= 1e-6:
            return 1.0
        return max(0.0, min(1.0, self._landing_ground_path().speed_fts / average))

    def _flight_path_fraction(self, u):
        """Where along the path the ball is at time fraction `u`."""
        return _decel_path_fraction(u, self._flight_end_speed_ratio)

    def _flight_time_fraction(self, s):
        """When the ball reaches path fraction `s`, as a time fraction."""
        return _decel_time_fraction(s, self._flight_end_speed_ratio)

    def _wall_impact_peak_cap(self):
        """The largest arc peak that still strikes the fence *face*.

        The ball reaches the fence at path fraction `wall_r / dist`, which
        the flight's deceleration puts at an earlier *phase* — and the
        arc's height is keyed to the phase. Inverting `peak · sin(π·phase)`
        for the peak at WALL_IMPACT_MAX_HEIGHT_FRAC of the fence height is
        the whole calculation.

        A crossing so late that the ball is already on the ground there
        needs no cap and would divide by ~0, so it returns the peak
        unchanged.
        """
        dx = self._hit_end[0] - HOME[0]
        dy_math = HOME[1] - self._hit_end[1]
        dist_px = math.hypot(dx, dy_math)
        if dist_px <= 1e-9:
            return self._hit_peak
        wall_px = _wall_r_at(math.atan2(dy_math, dx))
        phase = self._flight_time_fraction(min(1.0, wall_px / dist_px))
        lift_per_peak = math.sin(math.pi * phase)
        if lift_per_peak <= 1e-6:
            return self._hit_peak
        target_px = WALL_IMPACT_MAX_HEIGHT_FRAC * WALL_HEIGHT_FT * FT_TO_PX_Y
        return target_px / lift_per_peak

    def _fielded_ft(self):
        """Where the ball was actually gloved, in feet from home.

        Deliberately *not* `_ball`: on a grounder the throw sub-animation
        walks `_ball` over to first base, so by the time the play resolves
        `_ball` reads ~90 ft on every single one of them regardless of
        where it was fielded.
        """
        pos = self._inflight_catch_pos or self._ball
        return math.hypot(*_to_field_ft(pos))

    def _fts_to_px_ms(self, speed_fts):
        """A real ft/s onto the animated clock, along the ball's bearing.

        Direction-dependent for the same reason fielder speed is: the
        projection is anisotropic, so one scalar px/ms would be two
        different real speeds depending on which way the ball went.
        """
        return speed_fts * self._ball_px_per_ft / (1000.0 * self.time_scale)

    def _px_ms_to_fts(self, speed_px_ms):
        """Inverse of `_fts_to_px_ms` — the ball's live speed in real ft/s,
        which is the unit `ground_roll` reasons in."""
        if self._ball_px_per_ft <= 1e-9:
            return 0.0
        return speed_px_ms * 1000.0 * self.time_scale / self._ball_px_per_ft

    def _end_hopping(self):
        """Drop the rest of the hop schedule — the ball is rolling now.

        Both callers are wall contacts, where the wall has absorbed the
        vertical component. `_ground_path` has to be replaced as well as
        the animated schedule, because `_predict_ball_stop` reads its hops
        to work out how much travel is left; leaving them there would aim
        the chasing fielder at a hop the ball is no longer going to take.
        """
        self._bounces = []
        self._bounces_end_ms = 0.0
        self._bounces_completed = 0
        self._wall_drop = None
        if self._ground_path is not None:
            self._ground_path = ground_roll.GroundPath(
                speed_fts=0.0, hops=(), final_retention=1.0,
                grass_decel_ft_s2=self._ground_path.grass_decel_ft_s2)

    def _begin_wall_drop(self, height_px):
        """Let a ball that struck the fence fall down the face.

        It hits the wall several feet up (bounded by
        WALL_IMPACT_MAX_HEIGHT_FRAC) and has to get to the grass. Planting
        it there in the same frame is a jump downward at the exact moment
        the viewer is watching the carom — the last of the reported
        abruptness, and the part that survives even once the ball is no
        longer being drawn over the fence. It falls the way a dropped ball
        falls, free fall from rest over `sqrt(2h/g)`, while the rebound
        carries it back out into the field. That is what a carom looks
        like.

        Vertical only. The horizontal is already the rebound
        `_maybe_trigger_in_flight_wall_impact` set, and `_bounces_end_ms`
        is set to the fall so `_integrate_ball`'s existing airborne gate
        suspends friction for exactly as long as the ball is off the
        ground — the module's rule that grass only brakes a ball that is
        touching it. `_end_hopping` has already emptied the hop schedule,
        so the single contact that gate releases carries a retention of
        1.0 and changes nothing.
        """
        height_ft = max(0.0, height_px) / FT_TO_PX_Y
        if height_ft <= 1e-6:
            return
        fall_ms = self._anim_ms(math.sqrt(2.0 * height_ft / ball_flight.G_FT_S2))
        self._wall_drop = (height_px, fall_ms)
        self._bounces_end_ms = fall_ms

    def _hops_completed(self, tau_ms):
        """Ground contacts already made at `tau_ms` since landing."""
        n = 0
        for t_start, t_dur, _h, _r in self._bounces:
            if tau_ms >= t_start + t_dur:
                n += 1
            else:
                break
        return n

    def _predict_ball_stop(self):
        """Predicted resting point of the ball, hops included.

        Delegates the distance to `ground_roll.remaining_distance_ft`,
        which walks the rest of the hop schedule before applying the
        rolling solution — a ball two feet off the ground is not
        decelerating, so the naive v²/2a used to under-predict by most of
        the remaining travel and parked the chasing outfielder well short
        of where the ball was actually going. Clamped inside the
        elliptical wall so a long chase target doesn't sit in geometry the
        fielder can't reach.

        Used as the chaser's target instead of the live ball position —
        running straight to where the ball will come to rest reaches the
        play faster than tracking the live ball through a pursuit curve
        (which is what produced the "OF trails the ball across the
        screen and never catches up" look). Wall caroms aren't modeled
        in the prediction; if the ball hits a wall the velocity flips
        and the next frame's prediction snaps to the new direction,
        which the smooth fielder speed-ramp handles naturally.

        Before the ball lands (or once it's stopped), falls back to the
        current ball position so callers can use this unconditionally.
        """
        if self._ball_pos is None or self._ball_v is None:
            return self._ball
        vx, vy = self._ball_v
        speed = math.hypot(vx, vy)
        if speed < 1e-4:
            return (self._ball_pos[0], self._ball_pos[1])
        stop_ft = ground_roll.remaining_distance_ft(
            self._ground_path, self._px_ms_to_fts(speed),
            min(self._bounces_completed, len(self._ground_path.hops)))
        stop_px = stop_ft * self._ball_px_per_ft
        px = self._ball_pos[0] + vx / speed * stop_px
        py = self._ball_pos[1] + vy / speed * stop_px
        return _clamp_inside_wall((px, py), BALL_WALL_MARGIN_PX)

    def _current_bounce_lift(self, tau_ms):
        """Visual lift (px above ground) at time `tau_ms` since landing,
        looked up from the precomputed hop schedule. Each entry is a real
        projectile arc whose height and air-time both come from the same
        rebound speed. After the last hop, the ball is rolling on the
        ground and lift is 0.
        """
        if self._wall_drop is not None:
            height_px, fall_ms = self._wall_drop
            if tau_ms >= fall_ms:
                return 0.0
            # Free fall from rest: h − ½gt², with T² = 2h/g.
            return height_px * (1.0 - (tau_ms / fall_ms) ** 2)
        if tau_ms >= self._bounces_end_ms:
            return 0.0
        for t_start, t_dur, h, _r in self._bounces:
            if t_start <= tau_ms < t_start + t_dur:
                phase = (tau_ms - t_start) / t_dur
                return h * math.sin(math.pi * phase)
        return 0.0

    def _integrate_ball(self, pos, vel, completed, tau_ms, dt_ms):
        """One step of the ball's ground physics, wall excluded.

        Returns fresh `(pos, vel, completed)` rather than mutating, which
        is what lets `_forecast_ball` run the same physics forward off the
        live state without touching it. The wall stays in
        `_step_ball_on_ground`: a forecast that caroms would have the
        chasing fielder reacting to a bounce that has not happened yet.
        """
        vel = [vel[0], vel[1]]

        # Ground contacts crossed by this step. There is one impact per hop
        # plus the one that ends the hopping, hence `final_retention`.
        crossed = self._hops_completed(tau_ms)
        if tau_ms >= self._bounces_end_ms:
            crossed = len(self._bounces) + 1
        while completed < crossed:
            if completed < len(self._bounces):
                retention = self._bounces[completed][3]
            else:
                retention = self._ground_path.final_retention
            vel[0] *= retention
            vel[1] *= retention
            completed += 1

        airborne = tau_ms < self._bounces_end_ms
        speed = math.hypot(vel[0], vel[1])
        if speed > 0 and not airborne:
            # Grass plus air drag, evaluated at the live speed — the drag
            # term is quadratic, so it cannot be folded into a constant.
            decel_fts2 = ground_roll.roll_decel_ft_s2(
                self._px_ms_to_fts(speed), self._ground_path.grass_decel_ft_s2)
            decel_px_ms2 = (self._fts_to_px_ms(decel_fts2)
                            / (1000.0 * self.time_scale))
            new_speed = max(0.0, speed - decel_px_ms2 * dt_ms)
            if new_speed == 0.0:
                vel[0] = 0.0
                vel[1] = 0.0
            else:
                s = new_speed / speed
                vel[0] *= s
                vel[1] *= s
        return ([pos[0] + vel[0] * dt_ms, pos[1] + vel[1] * dt_ms],
                vel, completed)

    def _forecast_ball(self, tau_ms):
        """Where the live ball will be from here on, as `(dt_ms, (x, y))`
        samples on the animated clock. Cached per frame.

        This is what lets a fielder *charge*. Aiming the chase at the
        ball's resting point is right for a ball rolling away into the gap
        and exactly wrong for one coming at you: an outfielder standing at
        300 ft with a line drive landing at 220 ft would turn and retreat
        to its predicted stop at 390 ft while the ball rolled underneath
        them, and the ball reached the wall — which forces a double. That
        alone took doubles to 69% of hits. A ball dying in front of a
        fielder is a fielder charging, the most ordinary play in baseball,
        and it is the same argument `_path_intercept` makes for the
        in-flight phase.
        """
        if self._forecast_at_ms == tau_ms and self._forecast is not None:
            return self._forecast
        samples = []
        if self._ball_pos is not None and self._ball_v is not None:
            pos, vel = list(self._ball_pos), list(self._ball_v)
            completed = self._bounces_completed
            t = tau_ms
            for _ in range(FORECAST_MAX_STEPS):
                if math.hypot(*vel) < 1e-5:
                    break
                t += FORECAST_STEP_MS
                pos, vel, completed = self._integrate_ball(
                    pos, vel, completed, t, FORECAST_STEP_MS)
                samples.append((t - tau_ms,
                                _clamp_inside_wall(pos, BALL_WALL_MARGIN_PX)))
        self._forecast = samples
        self._forecast_at_ms = tau_ms
        return samples

    def _chase_target(self, fielder, tau_ms):
        """Where a chasing fielder should run: the first point on the
        ball's remaining path they can actually get to.

        Falls back to the predicted resting point when they cannot beat the
        ball anywhere — which is the honest answer for a ball already past
        them, and the only case the old unconditional `_predict_ball_stop`
        was right about.
        """
        for dt_ms, point in self._forecast_ball(tau_ms):
            if self._travel_ms(fielder, fielder.pos, point) <= dt_ms:
                return point
        return self._predict_ball_stop()

    def _step_ball_on_ground(self, dt_ms, tau_ms):
        """Integrate the ball forward one frame.

        Three things act on it, and only ever one at a time:

        * **A ground contact** takes a fraction of the horizontal speed.
          Fires once as `tau_ms` crosses each hop boundary, with the
          fraction `ground_roll` computed for that specific impact — the
          first one is by far the largest, and how large depends on the
          descent angle.
        * **Friction**, but *only while the ball is on the ground*. It used
          to run through the hops as well, which braked the ball while it
          was several feet in the air and is most of why it died so fast.
        * **The wall**: reflect the velocity component along the ellipse's
          outward normal (not the radial direction — the two only coincide
          for a circle), with restitution < 1 so a hard double caroms back
          toward the chasing fielder with reduced speed.
        """
        if dt_ms <= 0:
            return
        (self._ball_pos, self._ball_v,
         self._bounces_completed) = self._integrate_ball(
            self._ball_pos, self._ball_v, self._bounces_completed,
            tau_ms, dt_ms)

        # Wall containment for the elliptical wall. Normalized ellipse
        # distance is √((dx/a)² + (dy/b)²); =1 on the wall, <1 inside.
        dx = self._ball_pos[0] - HOME[0]
        dy_pyg = self._ball_pos[1] - HOME[1]      # pygame y (down +)
        dy_math = -dy_pyg                          # math y (up +)
        a = WALL_SEMI_X
        b = WALL_SEMI_Y
        ellipse_d = math.hypot(dx / a, dy_math / b)
        if ellipse_d <= 0:
            return
        # Shared with `_point_outside_wall`, which is the test for whether
        # the wall is hiding the ball from the camera — the line the ball
        # is held at and the line past which it is out of the park have to
        # be the same line.
        limit = BALL_WALL_LIMIT_NORM
        if ellipse_d > limit:
            # Outward normal at this point is the ellipse-equation gradient
            # ∝ (dx/a², dy_math/b²); normalize, then flip y for pygame.
            nx_m = dx / (a * a)
            ny_m = dy_math / (b * b)
            nm = math.hypot(nx_m, ny_m)
            if nm > 0:
                nx_m /= nm
                ny_m /= nm
            nx_p = nx_m
            ny_p = -ny_m
            v_outward = self._ball_v[0] * nx_p + self._ball_v[1] * ny_p
            if v_outward > 0:
                # Record the impact for HIT classification — any ball that
                # reaches the wall is at minimum a double regardless of how
                # the carom lands.
                self._wall_hit = True
                k = (1.0 + WALL_BOUNCE_RESTITUTION) * v_outward
                self._ball_v[0] -= k * nx_p
                self._ball_v[1] -= k * ny_p
                # Wall absorbs the vertical bounce energy. A hard liner
                # that lands just inside LANDING_WALL_MARGIN_PX and rolls
                # to the wall before its hop schedule is exhausted would
                # otherwise keep pogoing in place at the wall as the
                # remaining hops play out — same visual bug as the
                # in-flight wall impact. Truncate the schedule on contact
                # so the rebounded ball just rolls.
                self._end_hopping()
            # Pull ball back inside: scale toward home along the radial line
            # in ellipse-normalized space (linear in pygame coords too).
            s = limit / ellipse_d
            self._ball_pos[0] = HOME[0] + dx * s
            self._ball_pos[1] = HOME[1] + dy_pyg * s

    def _maybe_trigger_in_flight_wall_impact(self):
        """Check whether the ball's shadow has crossed outside the wall
        ellipse during flight. If yes, fire the wall-impact transition:
        plant the ball at the wall edge, kill most of its velocity (and
        flip inward so it rebounds toward the fielder rather than
        continuing radially outward), set self._wall_hit so the
        classifier upgrades the outcome, and truncate self.duration_ms so
        the next frame's in_flight check is false and ball-on-ground
        physics takes over.

        Only called for wall-candidate hits. The hit-end was aimed past
        the wall in _setup_hit; this function is what actually stops the
        ball when it strikes the wall, instead of letting the arc
        continue all the way to its (past-the-wall) landing point.
        """
        sx = self._ball_shadow[0]
        sy = self._ball_shadow[1]
        dx = sx - HOME[0]
        dy_math = HOME[1] - sy   # math convention (+y outward)
        if dx == 0 and dy_math == 0:
            return
        angle = math.atan2(dy_math, dx)
        wall_r = _wall_r_at(angle)
        shadow_r = math.hypot(dx, dy_math)
        if shadow_r < wall_r:
            return

        # How far up the face the ball hit. Bounded by
        # WALL_IMPACT_MAX_HEIGHT_FRAC, and read off the frame rather than
        # re-derived, so the drop below starts from exactly where the ball
        # was last drawn.
        impact_lift_px = max(0.0, self._ball_shadow[1] - self._ball[1])

        # Impact point: the wall edge along this angle, pulled in to the
        # line a live ball is held at so the ball renders flush with the
        # face rather than embedded in it.
        #
        # That line is BALL_WALL_LIMIT_NORM, in normalized-ellipse units.
        # This used to subtract BALL_WALL_MARGIN_PX from the *radius*,
        # which is the same line only at dead centre field: the ellipse's
        # radius runs 440–611 px, so 8 px off it is a smaller normalized
        # bite than 8 px off the 440 the constant normalizes against, and
        # the impact point therefore landed *outside* the boundary at
        # every other angle. `_point_outside_wall` then called it out of
        # the park and `_ball_behind_wall` hid the ball on the very frame
        # it struck the wall, on every carom — which is the other half of
        # "it clips and abruptly appears back in play".
        impact_r = wall_r * BALL_WALL_LIMIT_NORM
        impact_x = HOME[0] + impact_r * math.cos(angle)
        impact_y = HOME[1] - impact_r * math.sin(angle)
        self._hit_end = (impact_x, impact_y)

        # Initialize the on-ground physics at the ball's landing speed,
        # then scale by the wall-impact restitution and flip inward. The
        # inward flip is what makes the carom rebound back toward the
        # field; without it, rolling friction takes the ball outward right
        # back into the rolling-phase wall-containment code, which
        # double-applies the reflection and reads as jittery.
        self._init_ball_on_ground()
        self._ball_v[0] = -self._ball_v[0] * WALL_HIT_FLIGHT_RESTITUTION
        self._ball_v[1] = -self._ball_v[1] * WALL_HIT_FLIGHT_RESTITUTION

        # The wall absorbs the vertical bounce energy on impact — in real
        # video the ball drops down the face and rolls back, it does not
        # pogo at the foot of the wall. _init_ball_on_ground built a fresh
        # hop schedule for a ball landing on grass, which combined with the
        # heavily-damped rebound velocity produced the "ball clips up and
        # down at the wall then settles dead" bug. Clearing the schedule
        # lets the ball roll back cleanly from the impact point.
        self._end_hopping()
        # ...but it does still have to *come down*. Must follow
        # `_end_hopping`, which clears this along with the hops.
        self._begin_wall_drop(impact_lift_px)

        self._wall_hit = True
        self._wall_hit_in_flight = True

        # Render ball at the wall this frame too (otherwise the impact
        # frame briefly shows the ball past the wall before the next
        # frame snaps it back). The shadow is at the foot of the fence;
        # the ball is still up the face, where it just hit.
        self._ball_shadow = (impact_x, impact_y)
        self._ball = (impact_x, impact_y - impact_lift_px)

        # End the flight phase now. Next frame's `in_flight` check is
        # `elapsed <= self.duration_ms`; setting duration_ms to the
        # current elapsed makes that false, and the elif branch picks
        # up with self._ball_pos already set (skipping re-init).
        self.duration_ms = self._elapsed

    # ---- In-flight intercept --------------------------------------------

    def _check_in_flight_intercept(self):
        """Per-frame check: has any eligible fielder reached the ball
        before it lands? Catch fires when (1) the fielder has read the
        ball (past their see-react delay), (2) the ball's *ground
        projection* (shadow) comes within INTERCEPT_REACH_PX of their
        body, and (3) the ball's lift is within glove reach
        (INTERCEPT_MAX_LIFT_PX).

        The shadow-based lateral check decouples "where the ball is on
        the field" from "how high above the ground the ball is", so a
        chest-high liner over the mound no longer registers as a catch
        purely because the rendered ball (lift applied) overlapped the
        pitcher's body in screen space.

        The reaction-delay gate stops the related "ball flies over the
        pitcher and is caught while the sprite hasn't moved" bug:
        pitchers carry a 900 ms follow-through bias on top of the base
        200–400 ms see-react delay (ROLE_REACTION_BIAS_S), so they're
        frozen at the mound for the first ~1.1–1.3 s after contact. A
        liner up the middle reaches the mound in ~400–600 ms, and
        without this gate the stationary pitcher snared anything whose
        shadow happened to pass through them with lift under 25 px —
        even though in real baseball the pitcher hasn't raised their
        glove yet. Now a fielder must have at least read the ball
        before they can intercept; the moving-still-recovering pitcher
        is allowed to take true comebackers (which arrive after their
        reaction window) but not zip-by liners.

        Eligibility (see _eligible_intercept_pool) restricts grounders
        to IFs + pitcher, so a hot one-hopper doesn't get magically
        snagged by the LF as it bounces by — and drops the pitcher
        outright on plays where they lost the clean-fielding roll, so
        hard-hit balls up the middle go through the box.

        Returns True if a catch fired this frame, False otherwise — the
        caller uses this to short-circuit the rest of _update_hit's
        in-flight code (which would otherwise overwrite the targets
        _trigger_in_flight_intercept just set on the fielders).
        """
        bx, by = self._ball
        sx, sy = self._ball_shadow
        lift = max(0.0, sy - by)
        if lift > INTERCEPT_MAX_LIFT_PX:
            return False
        for role in self._eligible_intercept_pool():
            # Whoever is covering first is running to receive a throw, not
            # making a play on the ball. Their route to the bag crosses
            # the flight path of anything hit at the 1B, so without this
            # the pitcher on a 3-1 sprinted through the ball and fielded
            # it himself on ~40% of those, and the 1B — the fielder it was
            # hit to — turned around and covered the bag instead.
            if role == self._cover_role:
                continue
            # Both middle infielders break on a ball through the middle,
            # but only one is making the play — the other is converging
            # in support. Whoever was picked as the primary is the one
            # who calls for it; the other cannot convert a catch just by
            # arriving. This is not a new restriction so much as an
            # explicit one: before they chased, the non-primary middle
            # infielder leaned 5–23 px off their home and was never near
            # enough for the proximity test to fire. Freeing their legs
            # without this handed them balls in the hole that used to be
            # hits (+3.4 pp of grounders, +5.3 pp of liners became outs).
            if self._chases_in_flight(role) and role != self._primary_role:
                continue
            f = self.fielders[role]
            if self._elapsed < f.reaction_delay_ms:
                continue
            # Reach cap, enforced on the *ball* rather than implied by
            # where the fielder is standing. This used to be free: a
            # capped fielder's target was clamped, so their body could
            # never get near an out-of-range ball and no catch could
            # fire. Middle infielders now chase well past their reach
            # (INFIELD_CHASE_RANGE_PX), which would otherwise hand them
            # every ball they run down — the exact "2B runs down
            # everything over the bag" outcome the cap exists to
            # prevent. Their legs got longer; their glove did not.
            if self._range_ft(f, (sx, sy)) > self._max_intercept_dist(f):
                continue
            if math.hypot(sx - f.pos[0], sy - f.pos[1]) < INTERCEPT_REACH_PX:
                # Reaching the ball is no longer the same as fielding it.
                # Rolled here rather than at setup — which is how the
                # pitcher's clean-fielding roll works — so the fielder is
                # seen breaking for the ball and failing, instead of never
                # routing to it at all.
                kind = self._roll_misplay(f, in_air=(self.shape != "GROUNDER"))
                if kind == "THROUGH":
                    self._trigger_through(role)
                elif kind == "MUFF":
                    self._trigger_muff(role)
                else:
                    self._trigger_in_flight_intercept(role, (bx, by))
                return True
        return False

    def _resolve_ground_ball(self, catcher, unassisted):
        """Decide a fielded grounder by the clock, not by the geometry.

        Reaching the ball used to *be* the out. It now only means the
        fielder came up with it; whether that retires the runner is a race
        between the throw and the batter, run in real seconds by
        `infield_timing`. This is what makes a slow roller beaten out down
        the line possible at all — under the geometric test, dawdling to
        the fielder gave them *more* time to get there, so the softest
        contact was converted most reliably.

        Note the two clocks are deliberately not the same clock. The
        animation runs dilated (see docs/infield-timing-refactor.md §2) so
        the play is watchable; the verdict is computed from the real
        geometry in feet and the modelled exit velocity, and never reads
        `self._elapsed`. The viewer cannot perceive absolute seconds — what
        they see is the fielder come up with it, throw, and the runner
        beat it or not, which is the play either way.
        """
        catch_ft, ball_distance_ft, ranging_ft, is_charging = \
            self._play_geometry(catcher)

        ev_mph = self.exit_velocity_mph

        # No throw means the fielder carries it to the bag on their own
        # legs, which is far slower per foot than an arm. Feeding the
        # model a sprint speed instead of a throw speed is all it takes —
        # it already measures the distance to first itself. Modelling a
        # carry as a throw would turn every unassisted play into an easy
        # out.
        # Both branches come off the profile. Reading the module constant for
        # the unassisted carry would let a Gold Glove first baseman sprint at
        # 29 ft/s and then carry the ball to the bag at 27 — two models of one
        # fielder's legs.
        throw_fts = (self.defense.sprint_fts if unassisted
                     else self.defense.throw_fts)

        # How long the ball actually took to reach the glove. For an
        # in-flight intercept the ball's own travel time is right, because
        # the fielder was there waiting for it. For a ball picked up off
        # the ground it is not: the fielder had to go and get it, and the
        # play does not start until they do. Using the ball's travel time
        # for both scored a grounder chased down 200 ft into left field as
        # though the shortstop had it at 1.5 s, which turned balls that had
        # comfortably gone through the infield into outs — ground-ball hit
        # rate fell to 12.8% against an MLB 24%.
        #
        # `_secured_at_ms` is the animation's own record of when the glove
        # closed, so this is the one place a real duration is read *back*
        # off the animated clock rather than pushed onto it.
        secured_s = None
        if self._secured_at_ms is not None:
            secured_s = self._secured_at_ms / (1000.0 * self.time_scale)

        timing = infield_timing.resolve_infield_play(
            ev_mph=ev_mph,
            fielder_xy_ft=catch_ft,
            ball_distance_ft=ball_distance_ft,
            ball_to_glove_s=secured_s,
            ranging_ft=ranging_ft,
            is_charging=is_charging,
            handedness=self._batter_handedness(),
            sprint_fts=self._runner_sprint_fts(),
            difficulty_offset_s=self._difficulty_time_offset_s(),
            effective_throw_fts=throw_fts,
            defense=self.defense,
            # A bobble the roll at the reach already decided, in seconds.
            # It lands on the release clock because glove contact to release
            # is what a bobble delays, and because `defense_s` has to stay
            # equal to ball + release + throw. It also means the throw the
            # player watches is scheduled off the delayed release, so the
            # picture and the verdict cannot disagree.
            misplay_s=self._misplay_s,
            rng=random,
        )
        self.play_timing = timing
        # One draw, three outcomes. The window [p_out, p_out_clean) is exactly
        # the set of plays that would have been outs without the bobble and
        # were not with it — the official scorer's rule, arrived at rather
        # than judged. With no bobble the window is empty and this is a plain
        # draw against `p_out`.
        verdict = infield_timing.roll_verdict(timing)
        if verdict == "ERROR":
            # The bobble is what the window [p_out, p_out_clean) is made of,
            # so the fielder charged is the one who rolled it.
            self._charge_error(self._misplay_role or catcher.role)
            self.error_bases = 1
            self.classified_outcome = "REACHED ON ERROR"
        elif verdict == "HIT":
            # Beaten out. The throw still plays — the runner just gets
            # there first, which is the whole point of showing it.
            self.classified_outcome = "SINGLE"
        return timing

    def _begin_infield_play(self, catcher_role):
        """An infielder has the ball. Route the bag, run the clocks, and
        schedule the throw the player is about to watch.

        **Shared by both ways a fielder ends up holding a grounder**, and
        that is the whole point of it being a method. It used to live inline
        in `_trigger_in_flight_intercept`, which meant only a ball cut off
        *in the air* ever got a throw drawn. A grounder secured after it had
        already landed — the fielder charging a slow roller and picking it
        up, which is the most ordinary infield play there is — ran the race
        in `_resolve_extra_bases` and then jumped straight to the banner:
        the fielder reached the ball and GROUNDOUT appeared, with no throw
        and nobody covering first.

        The two paths differ only in how the ball got to the glove, which is
        `_resolve_ground_ball`'s business (it reads `_secured_at_ms` for
        exactly that) and not the throw's. Anything else they disagreed
        about would be two models of one play — the fault this file has been
        pulled apart to remove several times already. `unassisted` is the
        one that had actually drifted: the ground path hard-coded it False,
        so a first baseman who picked the ball up beside the bag was modelled
        as throwing it to somebody instead of stepping on the base, and
        `_resolve_ground_ball` explicitly warns that costs a throw's speed
        against a carry's.

        Returns the `infield_timing` result, which is also parked on
        `self.play_timing`.
        """
        catcher = self.fielders[catcher_role]
        # Provisional. The real verdict is a race between the throw and
        # the runner, and it cannot be settled until the branch below
        # decides whether this is a throw or an unassisted carry — the
        # two have very different clocks. See `_resolve_ground_ball`.
        self.classified_outcome = "GROUNDOUT"
        self._go_first_base_pos = FIRST_BASE_BAG_POS
        # Re-resolve the bag assignment now that we know who actually
        # came up with the ball — it may not be who we expected during
        # flight, and the fielder holding the ball is never the cover.
        # The estimate the deadline was running on is now a fact.
        self._fielded_at_ms = self._elapsed
        cover_role, cover_eta_ms = self._route_first_base_cover(catcher_role)
        carry_ms = self._eta_to_point(catcher, FIRST_BASE_BAG_POS)
        unassisted = cover_role is None or carry_ms <= cover_eta_ms

        # Run the clocks *before* scheduling the sub-animation, so the
        # throw the player watches is the throw the verdict was computed
        # from — the release the model charged and the flight time it
        # measured. Previously the schedule was fixed at 280/760 ms and
        # the timing was resolved afterwards, so a throw from deep in
        # the hole looked identical to one from on top of the bag while
        # the model knew they were 0.4 s apart.
        timing = self._resolve_ground_ball(catcher, unassisted=unassisted)

        # From here the throw (or the carry) owns ball rendering and the
        # finish clock, whichever way the ball reached the glove.
        self._post_fielding = True

        if unassisted:
            # Unassisted: the fielder is closer to the bag than anyone
            # they'd throw to, so they carry the ball over and step on
            # it. `_go_throw_start_ms = None` is the flag the renderer
            # uses to skip the throw arc and pin the ball to the
            # fielder as they cross to the base.
            catcher.target = FIRST_BASE_BAG_POS
            # Restore full sprint speed (the primary was paced for the
            # in-flight catch) and a tight decel zone so they run hard
            # for the bag and land on it.
            catcher.max_speed = catcher.base_max_speed
            catcher.decel_radius_px = SECURE_RADIUS_PX
            self._go_throw_start_ms = None
            self._go_throw_arrive_ms = None
            # Time the done-frame to the actual run from the catch
            # position to the bag (plus a brief step-on-base hold). A
            # fixed window would either leave them short of the bag on
            # long carries or stall the animation on short ones.
            run_ms = self._travel_ms(catcher, catcher.pos, FIRST_BASE_BAG_POS)
            self._go_done_ms = (self._elapsed + run_ms
                                + self._anim_ms(GO_CATCH_HOLD_S))
            # Nobody is receiving a throw, so wave the cover man off
            # rather than have two defenders converge on the bag.
            cover = self.fielders.get(cover_role)
            if cover is not None:
                cover.target = cover.home_pos
                cover.decel_radius_px = FIELDER_DECEL_RADIUS_PX
                self._lean_excluded.discard(cover_role)
            self._cover_role = None
        else:
            # Throw to first — but not before the bag is covered.
            # Delaying the *release* (rather than stretching the throw,
            # which would read as a lob) makes the ball and the cover
            # man arrive together, so the throw always has someone to
            # arrive to. Capped by GO_COVER_WAIT_MAX_S so a badly
            # out-of-position cover can't stall the animation; the
            # fielder just holds the ball a beat, which is exactly what
            # an infielder does when first isn't covered yet.
            #
            # The release and the flight come from the timing that
            # decided the play, so the throw on screen is the throw in
            # the model. GO_FIELD_HOLD_S survives only as the floor on
            # the gather — a fielder must be seen to have the ball
            # before it leaves — and GO_THROW_S as the fallback if the
            # model produced no flight (a fielder standing on the bag).
            self._go_throw_ms = (self._anim_ms(timing.throw_flight_s)
                                 if timing.throw_flight_s > 0
                                 else self._anim_ms(GO_THROW_S))
            release_ms = self._anim_ms(max(GO_FIELD_HOLD_S, timing.release_s))
            wait_ms = min(max(0.0, cover_eta_ms - self._go_throw_ms),
                          self._anim_ms(GO_COVER_WAIT_MAX_S))
            self._go_throw_start_ms = (self._elapsed
                                       + max(release_ms, wait_ms))
            self._go_throw_arrive_ms = self._go_throw_start_ms + self._go_throw_ms
            self._go_done_ms = (self._go_throw_arrive_ms
                                + self._anim_ms(GO_CATCH_HOLD_S))
        return timing

    def _resolve_extra_bases(self):
        """How far a ball that got through the defense is worth.

        A grounder an infielder picked up off the ground is not "through"
        anything — it is the most ordinary play in baseball, and it runs
        the infield race like any other. It used not to: `_resolve_ground_ball`
        was reachable only from `_trigger_in_flight_intercept`, so a
        grounder that was secured after landing skipped the race entirely
        and became an automatic single.

        That gap was invisible in the aggregate but it removed a specific
        population: the slow roller. A weakly-hit ball dies short of every
        infielder's set position, so it is *never* intercepted in flight —
        it has to be charged and picked up, which is precisely the play
        this branch was handling. Fielded grounders came out with a
        ball-to-glove p75 of 1.67 s against the 2.60 s the reference table
        gives a slow roller, because every slow roller in the sample had
        been classified as a hit before the model saw it.

        A race, like the infield play, and for the same reason. This used
        to be `retrieve_ms` — animated milliseconds from landing to
        pickup — against two fixed thresholds, which knew how *long* the
        fielder took but not how far from a base they ended up, and which
        lived on the presentation clock: unifying that clock moved triples
        from 8% of hits to 23% without anyone editing the thresholds.

        Now the runner runs and the ball has to be thrown somewhere.
        """
        # Bounded by where the ball was fielded, not by who fielded it.
        # Nobody throws to first on a ball picked up in the outfield — the
        # runner is most of the way there and the play is to hold them to a
        # single. An infielder who chased a grounder onto the grass is
        # making an outfielder's play, so it goes to the base race below.
        if (self.shape == "GROUNDER"
                and self._primary_role not in OUTFIELD_ROLES
                and self._fielded_ft() <= INFIELD_PLAY_MAX_FT):
            return self._begin_infield_play(self._primary_role)

        secured_ft = _to_field_ft(self._ball)
        retrieved_at_s = self._secured_at_ms / (1000.0 * self.time_scale)
        # A ball that struck the wall *on the fly* cleared every outfielder
        # in the air, so it cannot be a single however the carom returns.
        #
        # A ball that merely rolled there does not get the override, and
        # the distinction is load-bearing. When the only way to reach the
        # wall was to be aimed past it, the two were the same event and
        # `self._wall_hit` covered both. Honest post-landing physics makes
        # rolling to the wall an ordinary thing for a line drive to do —
        # 23% of them — and forcing each one to a double took doubles to
        # 46% of hits. There is no need to shortcut it: the ball was
        # retrieved 360 ft from home after five seconds, and the race
        # below can see both of those and will award most of them a double
        # on the merits.
        min_base = 2 if self._wall_hit_in_flight else 1
        base, margin = extra_bases.final_base(
            ball_xy_ft=secured_ft,
            retrieved_at_s=retrieved_at_s,
            is_outfielder=self._primary_role in OUTFIELD_ROLES,
            handedness=self._batter_handedness(),
            sprint_fts=self._runner_sprint_fts(),
            difficulty_offset_s=self._difficulty_time_offset_s(),
            min_base=min_base,
            defense=self.defense,
            rng=random,
        )
        if self.is_error:
            # The batter reached on the misplay. How far they got is the
            # ordinary base race — a drop in shallow left is a one-base error
            # and one at the track is a two-base error, out of the same model
            # that decides doubles, with no new distance thresholds.
            self.error_bases = base
            self.classified_outcome = "REACHED ON ERROR"
        else:
            self.classified_outcome = {1: "SINGLE", 2: "DOUBLE", 3: "TRIPLE"}[base]
        # Recorded as the play's margin when no infield race ran — this is
        # the race that decided the outcome, so it is the honest thing to
        # put in `play_margin_s`.
        if self.play_timing is None:
            self.extra_base_margin_s = margin

    def _batter_handedness(self):
        batter = getattr(self.game, "batter", None)
        try:
            return batter.get_handedness()
        except Exception:
            return "R"

    def _runner_sprint_fts(self):
        """Top-end speed for this batter-runner, in ft/s.

        No per-batter speed attribute exists yet, so this draws from the
        league distribution each play. Making it a real batter property is
        the natural next step and would give BatterProfile something new
        to model.
        """
        return random.gauss(infield_timing.SPRINT_SPEED_LEAGUE_FTS,
                            RUNNER_SPRINT_SIGMA_FTS)

    def _difficulty_time_offset_s(self):
        """Difficulty as seconds on the runner's clock rather than a
        multiplier on the verdict — see infield_timing.home_to_first_s.

        Derived from the existing `out_probability_modifier` so difficulty
        stays in one place: >1 means "more outs", which here means giving
        the batter-runner a slower clock.
        """
        settings = getattr(self.game, "settings_manager", None)
        try:
            modifier = settings.get_difficulty_multipliers()["out_probability_modifier"]
        except Exception:
            return 0.0
        return (modifier - 1.0) * DIFFICULTY_SECONDS_PER_MODIFIER

    def _roll_misplay(self, fielder, in_air):
        """Did this fielder handle the ball cleanly? Rolled once, then latched.

        `in_air` means the ball was going to be *caught* for an out, as
        opposed to fielded off the ground — which is what decides whether a
        misplay can be a through-ball at all. A ball does not go "through" a
        fielder who was going to catch it; that is a drop.

        Returns None (clean), "BOBBLE", "THROUGH" or "MUFF".
        """
        if self._misplay_rolled:
            return None
        self._misplay_rolled = True
        _, _, ranging_ft, is_charging = self._play_geometry(fielder)
        kind = defense_model.roll_misplay(
            self.defense, random,
            ranging_ft=ranging_ft,
            ev_mph=self.exit_velocity_mph,
            is_charging=is_charging,
            in_air=in_air,
        )
        if kind is not None:
            self._misplay_kind = kind
            self._misplay_role = fielder.role
            if kind == "BOBBLE":
                self._misplay_s = defense_model.misplay_cost_s(random)
        return kind

    def _charge_error(self, role):
        """Charge the play as an error, and pop the "!" over the fielder.

        Every site that decides there was an error goes through here, for
        the same reason `spray_deg` is resolved once: the mark on screen and
        the outcome in the record are then the same fact rendered twice
        rather than two things that could drift apart. `role` is who
        misplayed the ball, which the play may well move on from — a ball
        through the shortstop is retrieved by the left fielder, who becomes
        the primary and did nothing wrong.

        The mark's clock starts now rather than at the banner, because the
        moment worth seeing is the misplay itself: the fielder gets there,
        and the ball does not stay in the glove.
        """
        self.is_error = True
        self._error_role = role
        self._error_marked_at_ms = self._elapsed

    def _clean_play_p_out(self, fielder):
        """What this play would have been had the fielder handled it cleanly.

        The counterfactual half of the scorer's rule. For a ball that went
        through a fielder there is no `PlayTiming` to read a `p_out_clean`
        off — no play happened — so it is computed here from the same inputs
        the real race would have used, with no misplay on the clock.
        """
        catch_ft, ball_distance_ft, ranging_ft, is_charging = \
            self._play_geometry(fielder)
        timing = infield_timing.resolve_infield_play(
            ev_mph=self.exit_velocity_mph,
            fielder_xy_ft=catch_ft,
            ball_distance_ft=ball_distance_ft,
            ranging_ft=ranging_ft,
            is_charging=is_charging,
            handedness=self._batter_handedness(),
            sprint_fts=self._runner_sprint_fts(),
            difficulty_offset_s=self._difficulty_time_offset_s(),
            defense=self.defense,
            rng=None,          # the counterfactual must not add its own noise
        )
        return timing.p_out

    def _trigger_through(self, role):
        """The ball goes through the fielder and on into the outfield.

        The third state, and until now the model had only two: a ball was
        either untouched (a hit) or touched (a race). Real baseball has
        "reached, and still through", and §8 of
        docs/infield-timing-refactor.md names it as the missing 2.7 points of
        ground-ball hit rate: "our fielders execute a clean route on every
        ball they can reach; MLB's do not."

        The play does *not* end here. The ball keeps most of its pace, the
        beaten fielder is latched out of the pool, and the outfield runs it
        down — which needs no new routing, because `_pick_retrieval_role`
        already sends the responsible outfielder as a backup from the first
        frame.
        """
        f = self.fielders[role]
        self._beaten_roles.add(role)
        self._hit_end = (f.pos[0], f.pos[1])
        self._init_ball_on_ground()
        # How much it kept says what happened: a ball that kept everything
        # went clean under the glove and did not turn; one that lost half its
        # pace clearly hit something, and should have deflected. Coupling the
        # bearing to the speed lost is the physical statement, and it has a
        # consequence — a deflected ball is slower and easier to run down, so
        # it is more often a single than a gapper.
        retention = defense_model.through_retention(random)
        deflect = (1.0 - retention) * random.uniform(-1.2, 1.2)
        # The ball keeps a fraction of the speed it *actually had*, not of the
        # nominal landing speed `_init_ball_on_ground` builds for the shape.
        # A grounder is intercepted partway along its path, where it is still
        # moving far faster than it would be when it finally settles; scaling
        # the landing speed instead left the ball dead 16 ft past the fielder
        # (median, over 400 sandlot grounders), so they simply turned round
        # and picked it up — 28 of 35 through-balls were retrieved by the very
        # fielder they went through, and a third of them were still outs.
        #
        # The live speed comes off `infield_timing`'s retention curve rather
        # than a new estimate, because that is the same curve the infield race
        # times the ball with: the ball that beats the shortstop has to be the
        # ball the verdict was computed against.
        live_fts = infield_timing.ground_speed_fts(self.exit_velocity_mph)
        speed_px_ms = self._fts_to_px_ms(
            max(infield_timing.MIN_GROUND_SPEED_FTS, live_fts * retention))
        vx, vy = self._ball_v
        mag = math.hypot(vx, vy)
        if mag > 1e-9:
            vx, vy = vx / mag * speed_px_ms, vy / mag * speed_px_ms
        self._ball_v = [
            vx * math.cos(deflect) - vy * math.sin(deflect),
            vx * math.sin(deflect) + vy * math.cos(deflect),
        ]
        self._ball = self._ball_shadow = self._hit_end
        # End the flight here, so the next frame takes the ball-on-ground
        # path — the same idiom `_maybe_trigger_in_flight_wall_impact` uses.
        # The play is not over; the ball is loose in the outfield.
        self.duration_ms = self._elapsed
        # The ball is past them: they have to turn and go after it, and
        # cannot re-secure it on the very next frame just by standing there.
        self._misplay_recovered_at_ms = (
            self._elapsed + self._anim_ms(self.defense.through_turn_s))
        # The `p_out = 0` case of the scorer's rule: no race ran, so the batter
        # reached, and the only question is whether the clean play would have
        # been an out. Deferred to `infield_timing` rather than written out as
        # a second draw here — it is the same rule a bobble is judged by, and
        # two copies of it are two things to keep in step.
        #
        # It gives the right baseball answer without being asked for: a ball
        # through a diving fielder in the hole was a bang-bang play anyway and
        # is scored a hit, while the same ball through a fielder standing still
        # on a routine hop is an error. That extends to the outfield on its
        # own — `_clean_play_p_out` is ~0 at 250 ft, so a ball past an
        # outfielder is a hit, and an outfielder who *drops* one is a MUFF,
        # charged unconditionally. There used to be a `role in OUTFIELD_ROLES`
        # short-circuit here asserting the opposite (always an error); it never
        # fired in 5000 plays, because a through-ball only comes from
        # `_check_in_flight_intercept` and outfielders do not reach that state.
        if infield_timing.verdict_from(0.0, self._clean_play_p_out(f)) == "ERROR":
            self._charge_error(role)

    def _trigger_muff(self, role):
        """Off the glove. The ball is on the grass at the fielder's feet.

        The play stays live: an error is a *fielding* event, and the races
        already in this class decide what it costs. Nothing here decides an
        out. A drop in shallow left stays a one-base error and one at the
        track becomes a two-base error, out of the same `extra_bases` model
        that already decides doubles — no new distance thresholds.
        """
        f = self.fielders[role]
        self._hit_end = (f.pos[0], f.pos[1])
        self._init_ball_on_ground()
        # The glove takes nearly all of it, so the ball squirts a few feet
        # and dies. A small bearing jitter so it reads as a muff rather than
        # a teleport, and so the fielder has to take a step to it.
        theta = random.uniform(-0.7, 0.7)
        vx, vy = self._ball_v
        self._ball_v = [
            (vx * math.cos(theta) - vy * math.sin(theta)) * defense_model.MUFF_RETENTION,
            (vx * math.sin(theta) + vy * math.cos(theta)) * defense_model.MUFF_RETENTION,
        ]
        self._ball = self._ball_shadow = self._hit_end
        self._primary_role = role
        self.duration_ms = self._elapsed
        # What stops it being re-secured on the very next frame, and the one
        # place the drop's cost is charged. These seconds flow into
        # `_secured_at_ms` -> `retrieved_at_s` -> `extra_bases.final_base`.
        self._misplay_recovered_at_ms = (
            self._elapsed + self._anim_ms(self.defense.muff_recovery_s))
        # No counterfactual roll needed: the fielder was going to catch it,
        # so the clean play was a certain out and the drop is what the batter
        # reached on.
        self._charge_error(role)

    def _trigger_in_flight_intercept(self, catcher_role, catch_pos):
        """A fielder reached the ball pre-landing. Switch to the
        appropriate finishing sub-animation: throw-to-1B for grounders
        fielded by an infielder, a catch-hold for everything else.
        """
        self._secured = True
        self._secured_in_flight = True
        self._post_fielding = True
        self._secured_at_ms = self._elapsed
        # The catcher becomes the primary so subsequent draw logic shows
        # them holding the ball.
        self._primary_role = catcher_role
        # Snap the ball + shadow to the catcher right now so there's no
        # one-frame flicker before the post-catch render takes over.
        catcher = self.fielders[catcher_role]
        self._inflight_catch_pos = (catcher.pos[0], catcher.pos[1])
        self._ball = self._inflight_catch_pos
        self._ball_shadow = self._inflight_catch_pos

        if self.shape == "GROUNDER":
            self._begin_infield_play(catcher_role)
        else:
            # A line drive caught before it lands is a LINEOUT; everything
            # else caught in the air (fly balls, pop-ups) is classified by
            # its trajectory shape so pop-ups remain distinct from sac flies.
            # NB two namespaces meet here. self.shape is the internal
            # trajectory enum (GROUNDER / LINER / FLY / POP_UP), which keeps
            # its underscore; classified_outcome is the recorded outcome, which
            # is spelled like the rest of them ("POP UP", cf. "HOME RUN").
            if self.shape == "LINER":
                self.classified_outcome = "LINEOUT"
            elif self.shape == "POP_UP":
                self.classified_outcome = "POP UP"
            else:
                self.classified_outcome = "FLYOUT"
            self._go_done_ms = self._elapsed + FLYOUT_CATCH_HOLD

        # Stand down everyone else now that the play is over. The
        # catcher (new primary) and — on grounders — whoever is covering
        # first are the only fielders with live responsibilities; the
        # old primary and any pre-catch secondaries would otherwise
        # keep sprinting toward stale targets through the entire
        # post-catch hold (most visibly: pitcher running into the
        # diamond after a 2B catch).
        self._stand_down_non_primary(keep_at_bag=(self.shape == "GROUNDER"))

    def _render_post_fielding(self, elapsed):
        """Ball rendering during the post-catch sub-animation. For
        FLYOUT, the ball is pinned to the catcher (who may still be
        decelerating into position). For GROUNDOUT, the ball stays at
        the fielder until the throw fires, arcs to 1B, then sits at the
        bag for the catch hold.
        """
        catcher = self.fielders[self._primary_role]
        catcher_pos = (catcher.pos[0], catcher.pos[1])

        if self.classified_outcome == "FLYOUT":
            self._ball = catcher_pos
            self._ball_shadow = catcher_pos
            return

        # GROUNDOUT — either the throw-to-1B sequence, or (when the 1B
        # fielded it themselves) the 1B carries the ball to the bag.
        first_base = self._go_first_base_pos or BASES["1B"]
        if self._go_throw_start_ms is None:
            # 1B is the catcher: ball stays with them while they run to
            # the base. catcher_pos updates per-frame as 1B moves, so
            # this naturally pins the ball to their glove.
            self._ball = catcher_pos
            self._ball_shadow = catcher_pos
            return
        if elapsed <= self._go_throw_start_ms:
            self._ball = catcher_pos
            self._ball_shadow = catcher_pos
        elif elapsed <= self._go_throw_arrive_ms:
            t = (elapsed - self._go_throw_start_ms) / max(1.0, self._go_throw_ms)
            self._ball = _arc_fly(catcher_pos, first_base, THROW_PEAK_H, t)
            self._ball_shadow = _lerp(catcher_pos, first_base, t)
        else:
            self._ball = first_base
            self._ball_shadow = first_base

    # ---- Update ---------------------------------------------------------

    def update(self, current_time):
        if self.start_time is None:
            self.start_time = current_time
        self._last_elapsed = self._elapsed
        self._elapsed = current_time - self.start_time
        dt_ms = max(0, self._elapsed - self._last_elapsed)

        # Re-target lean fielders against the live ball position. Magnitude
        # grows with play progress so they keep moving instead of snapping
        # to a single position at t=0 and freezing.
        self._update_lean_targets()

        # Step all fielders FIRST so per-outcome phase logic can override the
        # primary's position last (preventing the override from being eased
        # back the next frame).
        for f in self.fielders.values():
            self._step_fielder(f, dt_ms, self._elapsed)

        # IN_PLAY, HOME RUN and FOUL flow through pitch_simulation now;
        # _update_hit handles the first two, _update_foul the scripted foul
        # playback. Legacy _update_groundout / _update_flyout are
        # unreachable from the live game but kept for any direct callers.
        if self.outcome == "FOUL":
            self._update_foul(self._elapsed)
        else:
            self._update_hit(self._elapsed)

        # Last word on where a defender may stand, after the per-outcome
        # phase logic has had its turn at writing positions directly (the
        # HOME RUN retreat eases `pos` rather than stepping toward a
        # target, and the post-catch flow pins fielders outright).
        self._contain_fielders()

        # Finishing rules:
        #   * Ball secured in flight (FLYOUT/GROUNDOUT branch): the
        #     post-catch sub-animation owns timing — finish once
        #     `_go_done_ms` has elapsed.
        #   * IN_PLAY ball lands and rolls (SINGLE/DOUBLE/TRIPLE): finish
        #     once a fielder secures it on the ground.
        #   * HOME RUN: scripted duration_ms; finish on expiry.
        if self._post_fielding:
            if self._go_done_ms is not None and self._elapsed >= self._go_done_ms:
                self.finished = True
        elif self._elapsed >= self.duration_ms:
            if self._needs_secure:
                if self._secured:
                    self.finished = True
            else:
                self.finished = True

    def _update_foul(self, elapsed):
        """Scripted foul flight: arc from home to the pre-picked landing
        point over _foul_flight_ms, then rest as a dead ball through the
        FOUL_HOLD_MS beat. No roll, no wall reflection, no interception —
        the play is already over, this is pure presentation.
        """
        t = min(1.0, elapsed / max(1, self._foul_flight_ms))
        if self.shape == "GROUNDER":
            self._ball = _arc_grounder(HOME, self._hit_end, self._grounder_peaks, t)
        elif self.shape == "LINER":
            self._ball = _arc_liner(HOME, self._hit_end, self._hit_peak, t)
        else:
            self._ball = _arc_fly(HOME, self._hit_end, self._hit_peak, t)
        self._ball_shadow = _lerp(HOME, self._hit_end, _shadow_t(self.shape, t))

    def _update_hit(self, elapsed):
        # Post-intercept sub-animations (the in-flight catch + the throw
        # to first on a fielded grounder) own ball rendering once the
        # catch fires — bypass the standard flight/ground branches.
        if self._post_fielding:
            self._render_post_fielding(elapsed)
            return

        in_flight = elapsed <= self.duration_ms

        if in_flight:
            # Two parameters, because the ball decelerates: `phase` is how
            # far through the flight time it is, `t` how far along the
            # path that puts it. The vertical shape belongs to the first
            # and the position to the second.
            phase = elapsed / self.duration_ms
            t = self._flight_path_fraction(phase)
            if self.shape == "GROUNDER":
                self._ball = _arc_grounder(HOME, self._hit_end,
                                           self._grounder_peaks, t, phase)
            elif self.shape == "LINER":
                self._ball = _arc_liner(HOME, self._hit_end, self._hit_peak,
                                        t, phase)
            else:
                self._ball = _arc_fly(HOME, self._hit_end, self._hit_peak,
                                      t, phase)
            self._ball_shadow = _lerp(HOME, self._hit_end, _shadow_t(self.shape, t))
            # Wall-candidate trajectories aim past the wall; this is what
            # actually stops the ball at the wall and routes it through
            # the wall-hit classifier. No-op for non-wall-candidates.
            if self._is_wall_candidate and not self._wall_hit:
                self._maybe_trigger_in_flight_wall_impact()
            # Keep first base covered as the play develops. `_primary_role`
            # can change mid-flight, and whoever it lands on has to be off
            # the bag — so the assignment is re-resolved rather than fixed
            # at setup. This is what turns the 1B around and sends them
            # back the instant they stop being the likely fielder.
            if self.shape == "GROUNDER" and not self._secured:
                self._route_first_base_cover(self._primary_role)
            # In-flight intercept check — any fielder reaching the ball
            # before it lands turns this into a FLYOUT or GROUNDOUT.
            # Suppressed for wall-candidate trajectories: those are aimed
            # past the wall by definition (gappers/down-the-line shots
            # that pass every fielder by design), and letting an OF
            # interception fire there would defeat the wall-bounce XBH
            # logic the wall-candidate path exists to produce.
            if (self.outcome == "IN_PLAY"
                    and not self._secured
                    and not self._is_wall_candidate):
                if self._check_in_flight_intercept():
                    # Something happened at the ball this frame. Returning
                    # short-circuits the in-flight primary motion block
                    # below, which would otherwise reset the catcher's
                    # target to self._hit_end and pull the 1B away from the
                    # bag we just routed them to.
                    #
                    # Only a *catch* hands rendering to the post-catch flow.
                    # A ball that went through the fielder or off their glove
                    # is loose: its triggers truncated the flight, so the
                    # next frame takes the ball-on-ground path instead.
                    if self._secured_in_flight:
                        self._render_post_fielding(elapsed)
                    return
        elif self._needs_secure:
            # SINGLE/DOUBLE/TRIPLE: stateful ball-on-ground physics — linear
            # friction + radial reflection off the wall, lazy-initialized
            # at the landing transition. Once secured, pin to fielder so
            # the ball stops cleanly in the glove. Otherwise integrate
            # forward and add a decaying-sin lift on top so the ball
            # visibly bounces a few times instead of looking like it's
            # stuck to the ground.
            if self._ball_pos is None:
                self._init_ball_on_ground()
            if self._secured:
                primary = self.fielders[self._primary_role]
                self._ball_pos[0] = primary.pos[0]
                self._ball_pos[1] = primary.pos[1]
                self._ball_v[0] = 0.0
                self._ball_v[1] = 0.0
                self._ball = (self._ball_pos[0], self._ball_pos[1])
            else:
                dt_ms = max(0.0, self._elapsed - self._last_elapsed)
                tau = elapsed - self.duration_ms
                self._step_ball_on_ground(dt_ms, tau)
                lift = self._current_bounce_lift(tau)
                self._ball = (self._ball_pos[0], self._ball_pos[1] - lift)
            self._ball_shadow = (self._ball_pos[0], self._ball_pos[1])
        else:
            # HOME RUN: ball is over the wall, no retrieval. Freeze at HR spot.
            self._ball = self._hit_end
            self._ball_shadow = self._hit_end

        if not hasattr(self, "_primary_start"):
            return

        # Primary fielder motion is split by outcome:
        #   HOME RUN — fielder retreats to a fixed wall spot; ball clears
        #     the wall, no live retrieval. Phase-tied cosine ease reads
        #     right because there's no chase.
        #   SINGLE/DOUBLE/TRIPLE — full-speed pursuit. Target is the
        #     projected landing during flight, then the live (rolling)
        #     ball after landing. The constant-velocity stepper (called
        #     in update()) handles motion — no phase-tied easing — so
        #     the fielder runs continuously and doesn't slow down to
        #     ball-watch before the bounce.
        primary = self.fielders[self._primary_role]
        if self.outcome == "HOME RUN":
            if in_flight:
                # Reaction delay before the OF turns and retreats to the wall.
                delay = primary.reaction_delay_ms
                move_window = max(1.0, self.duration_ms - delay)
                move_t = max(0.0, min(1.0, (elapsed - delay) / move_window))
                eased = 0.5 - 0.5 * math.cos(math.pi * move_t)
                cx, cy = _lerp(self._primary_start, self._primary_stop, eased)
                primary.pos[0] = cx
                primary.pos[1] = cy
        elif in_flight:
            # Most primaries route toward the landing during flight —
            # "full-speed pursuit" — and the pacing math ensures they
            # arrive late enough that they only intercept some of the
            # time (which is what produces a realistic hit/out split).
            #
            # The pitcher and catcher are the exception: their max
            # intercept radius (ROLE_MAX_INTERCEPT_DIST_PX) keeps them
            # close to home, but the target-to-landing override would
            # pull them 100 px past that on a routine grounder. For
            # those two, preserve the perp-foot intercept set by
            # _assign_in_play_targets so they stay near the mound /
            # plate and only convert genuine comebackers.
            #
            # A middle infielder chases the same way whether or not they
            # happen to be the primary — see `_route_in_flight_chase`.
            # Routing them here instead left the pair visibly
            # inconsistent on a ball up the middle: the SS ran 90 px at
            # it while the 2B, who was closer and had been picked as the
            # primary, pulled up at 52 px. The fielder nearest the ball
            # was the one who gave up on it.
            #
            # Everyone else gets the landing point clamped to their own
            # range cap — without that clamp this line silently undid
            # every cap, since it overwrites the routed intercept with
            # an unbounded sprint to the landing spot. `_pursuit_point`
            # applies that clamp and keeps a pulled-up fielder moving
            # with the play rather than frozen on the clamp point.
            #
            # On a ball nobody can catch, the landing spot is the wrong
            # place to stand: `_pick_retrieval_role` has already worked out
            # where on the roll this fielder actually meets the ball, and
            # this is the line that used to throw that answer away every
            # frame and send them to watch it land instead.
            if self._chases_in_flight(self._primary_role):
                self._route_in_flight_chase(primary)
            elif self._primary_role not in ("P", "C"):
                primary.target = self._pursuit_point(
                    primary, self._retrieval_point or self._hit_end)
        elif self._needs_secure and not self._secured:
            tau_now = elapsed - self.duration_ms
            # Reassign the primary to whichever fielder is geographically
            # closest to the live ball. Real baseball — once the ball is
            # rolling, the chase passes to whoever is closest, not to
            # whoever was originally routed during flight. Without this,
            # an IF tagged as primary for an in-flight grounder keeps
            # sprinting deep into the OF after the ball rolls past them,
            # while the OFs stand around watching (the bug reported).
            #
            # Pitcher and catcher are excluded from the post-landing
            # chase pool: a ball rolling 50 ft from the mound shouldn't
            # be the pitcher's responsibility, and the catcher only
            # comes off the plate for bunts/pop-fouls (covered by the
            # in-flight intercept gating). The chase belongs to the
            # position players.
            # Measured against the shadow, not the rendered ball. They are
            # the same point for a rolling ball and several feet apart
            # mid-hop, and what decides who is closest to the play is where
            # the ball is on the *field*.
            ball_ground = self._ball_shadow
            chase_pool = [r for r in self.fielders.keys() if r not in ("P", "C")]
            closest_role = min(
                chase_pool,
                key=lambda r: math.hypot(
                    self.fielders[r].pos[0] - ball_ground[0],
                    self.fielders[r].pos[1] - ball_ground[1],
                ),
            )
            if closest_role != self._primary_role:
                # Old primary stops sprinting — they go back to their
                # natural max_speed and standard decel; lean takes over.
                old = self.fielders[self._primary_role]
                old.max_speed = old.base_max_speed
                old.decel_radius_px = FIELDER_DECEL_RADIUS_PX
                self._lean_excluded.discard(self._primary_role)
                # New primary's "full speed" is their natural jittered max.
                # Read it off base_max_speed rather than max_speed — the
                # latter may still hold a paced-down intercept value.
                self._primary_role = closest_role
                self._primary_full_speed = self.fielders[closest_role].base_max_speed
                self._lean_excluded.add(closest_role)

            primary = self.fielders[self._primary_role]
            # Aim at the first point on the ball's path the primary can
            # reach, so they cut the ball off instead of trailing it —
            # charging it when it is coming at them, running to the spot
            # when it is not. Same straight-line-to-a-fixed-point logic
            # the lean-target chase uses; only the point is smarter.
            primary.target = self._chase_target(primary, tau_now)
            # Pacing was for the in-flight phase only — once the ball is on
            # the ground the fielder sprints to chase it down.
            primary.max_speed = self._primary_full_speed
            primary.decel_radius_px = SECURE_RADIUS_PX
            # Securing — any fielder within SECURE_RADIUS_PX of the ball
            # wins the race. With the closest-role reassignment above this
            # is usually the current primary, but a fielder activated by
            # the post-landing chase radius in _update_lean_targets can
            # also secure if their step happens to reach first.
            closest_dist = math.hypot(
                primary.pos[0] - ball_ground[0],
                primary.pos[1] - ball_ground[1],
            )
            for role, f in self.fielders.items():
                d = math.hypot(f.pos[0] - ball_ground[0],
                               f.pos[1] - ball_ground[1])
                if d < closest_dist:
                    closest_dist = d
                    closest_role = role
            # A ball over their head is not in their glove. Never bound
            # before, because the old hop schedule topped out at 26 px of
            # cosmetic lift; a real first bounce off a fly ball clears 7 ft,
            # and without this the centre fielder gloves it at the top of
            # its arc.
            in_reach = (self._ball_shadow[1] - self._ball[1]
                        <= GLOVE_REACH_FT * FT_TO_PX_Y)
            if (closest_dist < SECURE_RADIUS_PX and in_reach
                    and self._elapsed >= self._misplay_recovered_at_ms):
                self._secured = True
                self._secured_at_ms = self._elapsed
                if closest_role is not None and closest_role != self._primary_role:
                    self._primary_role = closest_role
                # Resolve *before* standing anyone down. On an infield
                # grounder this schedules the throw and names the cover
                # man, and `keep_at_bag` then has to spare them — sending
                # the whole defense home first left the throw arcing to an
                # empty bag. Everyone else is reset because without it the
                # remaining frames still show the pitcher / cutoff IF /
                # unused secondaries running at stale targets, which reads
                # as them not noticing the play is over.
                if self.outcome == "IN_PLAY" and self.classified_outcome is None:
                    self._resolve_extra_bases()
                self._stand_down_non_primary(keep_at_bag=self._post_fielding)

    @property
    def fielder_role(self):
        """Who ended up with the ball, or None if nobody did.

        Deliberately gated on `_secured` rather than just reporting
        `_primary_role`: the primary is a *routing* assignment that exists
        from the first frame and changes as the play develops, so reading it
        unconditionally would record a fielder for balls that were never
        fielded at all — exactly the rows a fielding aggregate must not
        count.
        """
        return self._primary_role if self._secured else None

    # ---- Draw -----------------------------------------------------------

    def draw(self, screen):
        self._draw_field(screen)

        # Fielders first so the ball renders on top (sells "ball in glove").
        for fielder in self.fielders.values():
            self._draw_fielder(screen, fielder, self._ball)

        # The shadow is the ball's point on the *ground*, so once that is
        # out of the park it is on the far side of the fence and nothing
        # on this side can see it — regardless of how high the ball is.
        if not _point_outside_wall(self._ball_shadow):
            sx, sy = int(self._ball_shadow[0]), int(self._ball_shadow[1])
            pygame.draw.ellipse(screen, (60, 60, 60), pygame.Rect(
                sx - BALL_SHADOW_W_PX // 2, sy - BALL_SHADOW_H_PX // 2,
                BALL_SHADOW_W_PX, BALL_SHADOW_H_PX))

        if not self._ball_behind_wall():
            bx, by = int(self._ball[0]), int(self._ball[1])
            pygame.draw.circle(screen, (255, 255, 255), (bx, by), BALL_RADIUS_PX)

        if self.hr_distance_ft is not None:
            self._draw_hr_distance(screen)

        # Once the banner has fired, show a "press any key" prompt so the
        # player controls when to advance instead of an arbitrary timeout.
        if self.banner_fired:
            self._draw_continue_prompt(screen)

    def _draw_continue_prompt(self, screen):
        if self._prompt_font is None:
            self._prompt_font = pygame.font.SysFont(None, 28, bold=True)

        # Subtle pulse so the prompt is unmistakably interactive.
        pulse = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(self._elapsed * 0.005))
        text = "PRESS ANY KEY TO CONTINUE"
        body = self._prompt_font.render(text, True, (235, 235, 235))
        shadow = self._prompt_font.render(text, True, (0, 0, 0))
        body.set_alpha(int(255 * pulse))
        shadow.set_alpha(int(200 * pulse))

        screen_rect = screen.get_rect()
        rect = body.get_rect(center=(screen_rect.centerx, screen_rect.bottom - 36))
        screen.blit(shadow, rect.move(2, 2))
        screen.blit(body, rect)

    def _draw_fielder(self, screen, fielder, ball_pos):
        x, y = fielder.pos[0], fielder.pos[1]
        # Subtle idle sway only when essentially at target (not actively moving).
        dist_to_target = math.hypot(fielder.target[0] - x, fielder.target[1] - y)
        if dist_to_target < 2.0:
            y = y + math.sin(self._elapsed * SWAY_FREQUENCY + fielder.sway_phase) * SWAY_AMPLITUDE

        pygame.draw.circle(screen, BODY_COLOR, (int(x), int(y)), BODY_RADIUS_PX)

        bdx = ball_pos[0] - x
        bdy = ball_pos[1] - y
        bd = math.hypot(bdx, bdy) or 1.0
        gx = int(x + 6 * bdx / bd)
        gy = int(y + 6 * bdy / bd)
        pygame.draw.circle(screen, GLOVE_COLOR, (gx, gy), 3)

        if fielder.role == self._error_role:
            self._draw_error_mark(screen, x, y)

    def _error_mark_alpha(self):
        """Fade ramp for the error "!": 1 through the hold, then down.

        Split out from the draw for the same reason `_hr_distance_alpha` is:
        *when the mark is on screen* becomes one pure expression that can be
        tested without a display.
        """
        if self._error_marked_at_ms is None:
            return 0.0
        since = self._elapsed - self._error_marked_at_ms
        if since < 0.0:
            return 0.0
        hold = self._anim_ms(ERROR_MARK_HOLD_S)
        if since <= hold:
            return 1.0
        return max(0.0, 1.0 - (since - hold) / self._anim_ms(ERROR_MARK_FADE_S))

    def _draw_error_mark(self, screen, x, y):
        """The "!" over the fielder who just booted it.

        Anchored to the fielder's own drawn position — including the idle
        sway — rather than to where the misplay happened, so it stays with
        them while they turn and chase the ball they let through.
        """
        alpha = self._error_mark_alpha()
        if alpha <= 0.0:
            return

        if self._error_font is None:
            self._error_font = pygame.font.SysFont(None, 30, bold=True)

        # A small pop upward off the head on appearance, so it reads as
        # something that just happened rather than a label that was always
        # there.
        since = self._elapsed - self._error_marked_at_ms
        rise = ERROR_MARK_RISE_PX * min(
            1.0, since / max(1e-6, self._anim_ms(ERROR_MARK_POP_S)))

        body = self._error_font.render("!", True, ERROR_MARK_COLOR)
        shadow = self._error_font.render("!", True, (0, 0, 0))
        body.set_alpha(int(alpha * 255))
        shadow.set_alpha(int(alpha * 200))

        rect = body.get_rect(
            center=(int(x), int(y - ERROR_MARK_OFFSET_PX - rise)))
        screen.blit(shadow, rect.move(1, 1))
        screen.blit(body, rect)

    def _hr_distance_alpha(self):
        """Reveal ramp for the distance readout: 0 until it appears, then
        up to 1 over the fade.

        Nothing until the ball is down, then a beat, then fade up — see
        HR_DISTANCE_REVEAL_DELAY_MS. It used to fade in at 70% of the
        flight, which put the number on screen while the ball was still
        on its way to the wall and gave away how far it was going to go
        before it had gone there.

        Split out from the draw so *when the number appears* is one pure
        expression, testable without a display.
        """
        since_landing = self._elapsed - self.duration_ms
        if since_landing < HR_DISTANCE_REVEAL_DELAY_MS:
            return 0.0
        return min(1.0, (since_landing - HR_DISTANCE_REVEAL_DELAY_MS)
                   / HR_DISTANCE_FADE_MS)

    def _draw_hr_distance(self, screen):
        alpha = self._hr_distance_alpha()
        if alpha <= 0.0:
            return

        if self._font is None:
            self._font = pygame.font.SysFont(None, 36, bold=True)

        text = f"{self.hr_distance_ft} FT"
        body = self._font.render(text, True, (255, 230, 120))
        shadow = self._font.render(text, True, (0, 0, 0))
        body.set_alpha(int(alpha * 255))
        shadow.set_alpha(int(alpha * 200))

        # Clamp text to remain visible even when the ball lands at or above
        # the top of the screen (the rare deep blasts). Without this, the
        # distance disappears off-screen exactly when the player most wants
        # to read it.
        text_h = body.get_height()
        text_y = max(text_h // 2 + 4, int(self._hit_end[1]) - 28)
        rect = body.get_rect(center=(int(self._hit_end[0]), text_y))
        screen.blit(shadow, rect.move(2, 2))
        screen.blit(body, rect)

    def _draw_field(self, screen):
        hx, hy = HOME

        # Outfield wall — sampled-arc band rather than a single pygame.draw.arc.
        # The arc spans from one foul-pole corner across CF to the other,
        # forming a continuous boundary. The parametric ellipse angle at the
        # foul corners is `atan2(WALL_FT_X, WALL_FT_Y)` — using the *real-foot*
        # semi-axes, since the parametric angle is invariant under axis-aligned
        # scaling. (Using the screen-pixel semi-axes was the previous bug that
        # left a gap between the foul lines and the wall.) The geometry is
        # static, so it's computed once and cached in _wall_geometry().
        geo = _wall_geometry()
        wall_top_pts = geo['top']
        wall_bot_pts = geo['bot']
        face_poly = geo['face_poly']

        # Wall face — filled band so the wall reads as a 3D structure.
        pygame.draw.polygon(screen, (60, 60, 60), face_poly, 0)
        # Bright top edge (outer rim of the wall, where it meets the sky/black
        # background) and a softer inner edge where it meets the field.
        pygame.draw.lines(screen, (200, 200, 200), False, wall_top_pts, 2)
        pygame.draw.lines(screen, (115, 115, 115), False, wall_bot_pts, 1)

        # Foul lines — terminate at the inner-wall edge (where the field
        # meets the wall face), not at the outer rim. wall_bot_pts[0] is the
        # right foul-pole base, wall_bot_pts[-1] is the left.
        foul_right_base = wall_bot_pts[0]
        foul_left_base  = wall_bot_pts[-1]
        line_color = (150, 150, 150)
        pygame.draw.line(screen, line_color, (hx, hy), foul_right_base, 1)
        pygame.draw.line(screen, line_color, (hx, hy), foul_left_base, 1)

        # Foul poles — short vertical bars rising from the wall corners. Match
        # the glove yellow so the only non-gray elements are the two play-
        # critical accents (poles + glove).
        foul_right_top = wall_top_pts[0]
        foul_left_top  = wall_top_pts[-1]
        pole_color = (245, 215, 90)
        pygame.draw.line(screen, pole_color, foul_right_top,
                         (foul_right_top[0], foul_right_top[1] - FOUL_POLE_HEIGHT_PX), 2)
        pygame.draw.line(screen, pole_color, foul_left_top,
                         (foul_left_top[0], foul_left_top[1] - FOUL_POLE_HEIGHT_PX), 2)

        # Infield diamond — minimalist grayscale (was brown).
        diamond = [HOME, BASES["1B"], BASES["2B"], BASES["3B"]]
        pygame.draw.polygon(screen, (35, 35, 35), diamond, 0)
        pygame.draw.polygon(screen, (180, 180, 180), diamond, 2)

        # Bases
        for bp in BASES.values():
            bx, by = int(bp[0]), int(bp[1])
            pygame.draw.rect(screen, (220, 220, 220),
                             pygame.Rect(bx - 5, by - 5, 10, 10))

        # Pitcher's mound — grayscale to match the diamond.
        pygame.draw.circle(screen, (35, 35, 35), PITCHERS_MOUND, 14)
        pygame.draw.circle(screen, (180, 180, 180), PITCHERS_MOUND, 14, 1)

        # Home plate
        pygame.draw.polygon(screen, (220, 220, 220), [
            (hx - 8, hy - 8), (hx + 8, hy - 8), (hx + 8, hy),
            (hx, hy + 6), (hx - 8, hy),
        ], 0)
