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

from strikefactor.engine import contact_audio
from strikefactor.gameplay import ball_flight, extra_bases, infield_timing

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
# Lateral angle bounds (radians, math convention with 90° straight to CF).
# 50°–130° matches the fair-territory cone — same clamp _pick_hit_landing's
# legacy gap branch already used. Uniform distribution: real BABIP varies
# by spray angle, but the relevant inequities (pull-side pull, opposite-
# field power) belong to the swing model, not the landing pick.
IN_PLAY_ANGLE_MIN = math.radians(50)
IN_PLAY_ANGLE_MAX = math.radians(130)

# Foul-ball animation (cosmetic — the outcome is already a settled foul).
# Direction comes from the *signed* swing timing: early swings hook the ball
# past the batter's pull-side line, late swings glance it off past the
# opposite-field line. Off-line angle grows with timing severity so a
# barely-foul swing hugs the line and a badly mistimed one sprays sharply.
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
FOUL_OFF_MIN_RAD = math.radians(6)
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
# Rolling friction during the post-landing phase, in real ft/s². Uniform
# across hit outcomes — once a baseball is on the grass, friction is a
# property of the surface, not how the ball got there. Distance-to-stop
# scales as v²/(2a), so harder hits naturally roll farther without any
# per-outcome tuning.
#
# Real grass rolls a baseball down at ~3–10 ft/s² (≈0.1–0.3g); this sits
# at the top of that band, which keeps balls from routinely reaching the
# wall while still letting one clearly roll for a second or two after the
# bounces stop.
#
# It was `ROLLING_DECEL_PX_MS2 = 0.000035` — px per *animated* ms², which
# made stopping distance a function of presentation pacing. See
# `_roll_decel_px_ms2` for what that cost.
ROLLING_DECEL_FT_S2 = 16.0

# Speed the ball starts its roll at, as a fraction of its *average* flight
# speed. Liner skips through; grounder has been bleeding speed the whole
# way; fly drops nearly vertically and loses most of its horizontal carry;
# pop-up deadens hard. This is the only place shape affects post-landing
# speed — once the ball is on the ground, friction is a property of the
# grass, not the trajectory shape, so rolling decel is uniform across
# shapes (see ROLLING_DECEL_FT_S2).
#
# These are the designated calibration dial for roll distance, and they
# were 1.00 / 0.92 / 0.80 / 0.55 — near-lossless, which is why the friction
# constant had to run at ~50 ft/s², five times real grass, to stop the ball
# at all. The two are interchangeable for stopping distance (v²/2a), so the
# choice of which to bend is the interesting one: grass friction is a
# measurable surface property and how much energy an arbitrary batted ball
# leaves in its bounces is not, so the calibration belongs here and the
# friction constant gets to stay near its real value. Same principle as
# `infield_timing`'s release time being the dial there.
#
# Note these multiply the *average* flight speed, not the impact speed —
# `_init_ball_on_ground` samples (hit_end - HOME) / duration_ms — so 0.35
# on a grounder averaging 94 ft/s starts the roll at 33 ft/s, which is a
# ball that has already taken its hops through the infield.
SHAPE_LAND_FACTOR = {
    "LINER":    0.45,
    "GROUNDER": 0.35,
    "FLY":      0.35,
    "POP_UP":   0.25,
}

# Post-landing bouncing — modeled as a sequence of parabolic hops with a
# coefficient of restitution. Real baseballs on natural grass have vertical
# COR ≈ 0.55 (so each bounce retains ~30% of height — h_{n+1} = COR² · h_n).
# Air time scales with √h, so duration shrinks per bounce: T_{n+1} = COR · T_n.
# We use a slightly higher COR than reality for game-feel — more visible
# bounces — but the profile is otherwise the realistic decay (chest-high
# first hop, then half, then a quarter, settling into a roll).
BOUNCE_COR                 = 0.62
BOUNCE_INITIAL_DURATION_MS = 620   # first hop's air time
# Visibility cutoff for the bounce schedule. Set deliberately high (3 px ≈
# 2 ft) so the ball bounces "at most a few times" — typically 2 hops on
# liners/fly singles, 3 on triples — and then transitions to a clean roll.
# Lower values produced 4–5 micro-bounces whose combined air-time gave
# friction enough window to nuke the velocity before the ball could roll.
BOUNCE_HEIGHT_THRESHOLD_PX = 3.0

# Per-bounce horizontal velocity loss. Each time the ball completes a
# bounce, ground friction during the impact removes a small fraction of
# horizontal speed. Continuous friction (ROLLING_DECEL_PX_MS2) handles the slow
# decay during air time and rolling; this captures the impulse-style loss
# at each impact. 4% per bounce is on the low end of real grass-impact
# friction, chosen so the ball still has meaningful momentum when it
# settles into rolling — combined with the reduced bounce count, this
# leaves a clear, visible roll phase after the hops stop.
BOUNCE_HORIZONTAL_RETENTION = 0.96

# Initial bounce height per shape, derived from the in-flight peak. A liner
# skips with most of its energy — chest-high first hop. A fly comes down
# nearly vertically and dampens hard against the grass. A pop-up plops.
SHAPE_BOUNCE_HEIGHT_FRAC = {
    "LINER":    0.65,
    "GROUNDER": 0.55,
    "FLY":      0.28,
    "POP_UP":   0.15,
}
BOUNCE_HEIGHT_MAX_PX = 26   # cap so a tall fly doesn't moonshot the first hop

# Wall containment. Landings clamp inside the wall arc so a deep gapper
# doesn't visually start past it. Rolling balls clamp closer to the wall
# and reflect their radial-outward velocity component on contact, with
# restitution < 1 so the carom loses energy.
LANDING_WALL_MARGIN_PX  = 25
BALL_WALL_MARGIN_PX     = 8
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
# Peak scale for wall-candidate FLYs. The standard FLY peak (60–130 px)
# would put the ball *over* the wall at the crossing point — i.e., HR
# territory, not "off the wall." Scaling down to ~0.6 of the standard
# peak keeps the ball low enough at the wall to strike the face.
WALL_HIT_FLY_PEAK_SCALE  = 0.60
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


def _arc_fly(a, b, peak, t):
    """Standard sin-shaped arc."""
    t = max(0.0, min(1.0, t))
    x, y = _lerp(a, b, t)
    lift = peak * math.sin(math.pi * t)
    return (x, y - lift)


def _arc_liner(a, b, peak, t):
    """Low fast arc with linear horizontal motion. Ease-out (1−(1−t)²) was
    used here previously for a 'shot' feel, but it pulls horizontal velocity
    to zero at landing — which read as the ball pausing before its
    post-landing roll picked up. Linear t keeps the ball at constant pace
    so the hand-off into ball-on-ground physics is seamless.
    """
    t = max(0.0, min(1.0, t))
    x, y = _lerp(a, b, t)
    lift = peak * math.sin(math.pi * t)
    return (x, y - lift)


def _arc_grounder(a, b, peaks, t):
    """Variable-bounce arc; one parabolic hop per entry in `peaks`, with the
    ball touching ground at every segment boundary. Splits the flight into
    len(peaks) equal-duration segments — combined with linear x,y motion
    from _lerp, each segment also covers an equal fraction of the path, so
    bounces are evenly spaced along the trajectory.
    """
    t = max(0.0, min(1.0, t))
    x, y = _lerp(a, b, t)
    n = len(peaks)
    bounce_idx = min(n - 1, int(t * n))
    bounce_t = (t * n) % 1.0
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


# HR direction tuning. Pulled HRs are the dominant pattern in real MLB
# (~55–60% of HRs are pulled, ~10% oppo, the rest straightaway). The
# pull/oppo bias from pitch location is overlaid on top of a small
# default pull bias so even a centered pitch tends slightly toward the
# batter's pull side, matching reality.
HR_INSIDE_NORM_PX     = 65.0                  # half-width of strike zone (ABS_ZONE width / 2)
HR_PULL_SHIFT_RAD     = math.radians(22)      # max angle shift from inside/outside contact
HR_BASE_PULL_RAD      = math.radians(7)       # default pull bias on a centered pitch
HR_ANGLE_SIGMA_RAD    = math.radians(20)      # gaussian spread around the biased mean
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


def _pick_hit_landing(outcome, shape, quality=1.0, horizontal_inside=0.0, batter_handedness='R'):
    """Pick a landing point for the contact.

    For IN_PLAY (the unified ball-in-play outcome) the landing is sampled
    naturally — uniform lateral angle across fair territory, depth scaled
    by contact quality within the per-shape IN_PLAY_LANDING_FT range.
    Hit vs. out emerges later from whether a fielder reaches the ball;
    the landing distribution is intentionally unbiased so a ball aimed
    "right at" an IF really does end up in their range, and a ball aimed
    through a gap really does get past them.

    HOME RUN landings bias by pitch location and batter handedness:
    inside pitches get pulled (RHB → LF, LHB → RF); outside pitches go
    opposite field. `horizontal_inside` is positive when the pitch was
    inside the batter (handedness already folded in upstream), so the
    pull direction in field-angle space depends only on handedness.
    """
    if outcome == "IN_PLAY":
        dist_min, dist_max = IN_PLAY_LANDING_FT.get(shape, IN_PLAY_LANDING_FT["LINER"])
        ev = contact_audio.exit_velocity_mph(quality)
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
        spread = (dist_max - dist_min) * 0.18
        dist_ft = random.uniform(max(dist_min, mid - spread),
                                 min(dist_max, mid + spread))
        # Lateral angle uniform across fair territory. No artificial pull
        # toward gaps or lines — the spray pattern is the input to the
        # fielder simulation, not a hint about the desired outcome.
        angle = random.uniform(IN_PLAY_ANGLE_MIN, IN_PLAY_ANGLE_MAX)
        return _clamp_inside_wall(_polar_point_ft(angle, dist_ft),
                                  LANDING_WALL_MARGIN_PX)

    if outcome == "HOME RUN":
        # Pull/oppo bias from pitch location. `horizontal_inside` is
        # positive when the pitch was inside the batter (i.e. pull
        # territory), negative when outside. Field-angle convention:
        # angle 130° = LF, angle 50° = RF. For RHB pull is +angle (LF);
        # for LHB pull is -angle (RF). The pull sign converts inside-
        # offset into the correct field direction; a small base pull bias
        # is added so even a centered pitch leans slightly toward the
        # batter's pull side (matches real MLB HR spray).
        pull_sign = 1.0 if batter_handedness != 'L' else -1.0
        norm_inside = max(-1.0, min(1.0, horizontal_inside / HR_INSIDE_NORM_PX))
        bias_rad = pull_sign * (HR_BASE_PULL_RAD + norm_inside * HR_PULL_SHIFT_RAD)
        mean_angle = math.radians(90) + bias_rad
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
    angle = random.uniform(math.radians(50), math.radians(130))
    return _clamp_inside_wall(_polar_point_ft(angle, dist_ft),
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
                 batted_ball_type=None, horizontal_inside=0.0, foul_timing_norm=0.0):
        self.game = game
        self.outcome = outcome
        self.on_complete = on_complete
        self.vertical_offset = vertical_offset
        self.quality = quality
        self.batted_ball_type = batted_ball_type
        # Signed timing severity for FOUL outcomes, in [-1, 1]: negative =
        # early swing (pull-side foul), positive = late (opposite field).
        # Magnitude is the position within the foul timing window.
        self.foul_timing_norm = foul_timing_norm
        # Signed inside/outside contact offset from hit_outcome_manager.
        # Positive = ball was inside the batter (drives pull-side HRs);
        # negative = outside (drives opposite-field HRs). Already sign-
        # adjusted for handedness upstream, so a single sign convention
        # captures both RHB and LHB.
        self.horizontal_inside = horizontal_inside

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
        # _render_post_in_flight_catch (catch hold for flies; throw-to-1B
        # for grounders).
        self._secured_in_flight = False
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
        # landing transition by _init_ball_on_ground.
        self._ball_pos = None
        self._ball_v = None
        self._ball_decel = 0.0

        # Set true the first time the rolling ball reflects off the elliptical
        # outfield wall (see _step_ball_on_ground). Drives an XBH override in
        # the HIT classifier — a ball that reaches the wall is, by physical
        # definition, past every OF, so it should never resolve as a single
        # regardless of how quickly the ricochet brings it back to a fielder.
        self._wall_hit = False

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
            reaction_delay_s=random.uniform(REACTION_DELAY_MIN_S, REACTION_DELAY_MAX_S)
                + ROLE_REACTION_BIAS_S.get(role, 0.0),
            max_speed=FIELDER_SPRINT_FT_S * random.uniform(0.78, 1.22),
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

        # Whether the pitcher can handle a ball hit back at them on this
        # play. Rolled once, up front, rather than per-frame: a coin
        # flipped every frame would let a pitcher who "missed" the ball
        # at the mound snare it two frames later. See
        # PITCHER_CLEAN_FIELD_PROB.
        self._pitcher_fields_clean = self._roll_pitcher_clean_field()

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
            ev = contact_audio.exit_velocity_mph(self.quality)
            carry_ft = ball_flight.carry_distance_ft(self.shape, ev)
            # Measured toward centre field, the shallowest part of the
            # park; the angle isn't chosen yet, and picking the deepest
            # reference keeps this from over-selecting balls that only
            # reach a wall they were never hit toward.
            if carry_ft >= WALL_REACH_FT:
                self._is_wall_candidate = True

        if self._is_wall_candidate:
            # Aim past the wall along a realistic angle (down-the-line or
            # gap shot — same distribution _pick_hit_landing uses for high-
            # quality HITs, since those are the angles where real wall
            # caroms originate). Distance is wall_r + carry, with squared
            # bias so most carries are small (impact low on the face).
            q = max(0.0, min(1.0, self.quality))
            line_prob = 0.20 + 0.30 * q
            gap_prob  = 0.40 + 0.30 * q
            roll = random.random()
            if roll < line_prob:
                side = random.choice((-1, 1))
                base = math.radians(53) if side > 0 else math.radians(127)
                angle = base + random.uniform(-0.05, 0.05)
            elif roll < line_prob + gap_prob:
                side = random.choice((-1, 1))
                gap = math.radians(79) if side > 0 else math.radians(101)
                angle = gap + random.uniform(-0.10, 0.10)
            else:
                angle = random.uniform(math.radians(50), math.radians(130))
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
            handedness = 'R'
            batter = getattr(self.game, 'batter', None)
            if batter is not None and hasattr(batter, 'get_handedness'):
                handedness = batter.get_handedness()
            self._hit_end = _pick_hit_landing(
                outcome, self.shape, self.quality,
                horizontal_inside=self.horizontal_inside,
                batter_handedness=handedness,
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
                # Wall candidates need a lower peak so the ball is *below*
                # the wall top at the crossing point — otherwise the
                # trajectory would clear the wall (HR territory).
                if self._is_wall_candidate:
                    self._hit_peak *= WALL_HIT_FLY_PEAK_SCALE
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
                self.shape, contact_audio.exit_velocity_mph(self.quality),
                landing_ft)
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

        # Route every plausible defender to their best intercept point on
        # the ball's path. The fielder whose intercept timing best matches
        # the ball's arrival becomes the nominal primary (used by the
        # post-landing chase logic); secondary fielders within a margin
        # back up the play. Hits vs. outs emerge from whether any
        # routed fielder actually reaches the ball — there is no
        # pre-decided primary "going to the landing spot" any more.
        self._assign_in_play_targets()

    def _setup_foul(self):
        """Scripted foul-ball flight. Direction is driven by the signed
        timing severity (early → pull side, late → opposite field), shape
        by vertical contact offset (already bucketed into self.shape), and
        depth/foul-HR by quality. No interception or securing — the ball
        lands untouched and the animation finishes on duration_ms.
        """
        handedness = 'R'
        batter = getattr(self.game, 'batter', None)
        if batter is not None and hasattr(batter, 'get_handedness'):
            handedness = batter.get_handedness()
        # Field-angle pull side: +1 = 3B/LF line for a RHB, -1 = RF for LHB.
        pull_sign = 1.0 if handedness != 'L' else -1.0
        early = self.foul_timing_norm < 0
        foul_side = pull_sign if early else -pull_sign
        severity = min(1.0, abs(self.foul_timing_norm))
        q = max(0.0, min(1.0, self.quality))
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
            off = (FOUL_OFF_MIN_RAD
                   + severity * (FOUL_OFF_MAX_RAD - FOUL_OFF_MIN_RAD)
                   + random.gauss(0.0, math.radians(4)))
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
            return ["1B", "2B", "SS", "3B"]
        else:
            pool = list(ROLES)
        if not self._pitcher_fields_clean:
            pool.remove("P")
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
            ball_arrives = t_proj * self.duration_ms

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
        if makeable:
            self._primary_role = min(
                makeable,
                key=lambda r: (intercepts[r]["fielder_dist_ft"], score(r)),
            )
        else:
            self._primary_role = self._closest_role_in(pool, self._hit_end)
        primary = self.fielders[self._primary_role]
        pri_int = intercepts[self._primary_role]

        # When the ball gets fielded, as best we can tell before it's
        # thrown: the later of the two arrivals at the intercept point.
        # This is what the cover man's deadline is measured from.
        self._fielded_at_ms = score(self._primary_role)

        # Clamped, because the no-makeable-fielder fallback above picks
        # on raw distance-to-landing and would otherwise send a fielder
        # sprinting to a point their own range cap just disqualified.
        primary.target = self._range_limited_point(primary, pri_int["point"])
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

        tx, ty = fielder.target
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

    # ---- Ball on ground -------------------------------------------------

    def _init_ball_on_ground(self):
        """Initialize stateful ball physics at the landing transition.

        Horizontal motion is linear in all four arc shapes (the sin-based
        lift only offsets the rendered y), so the ground-frame velocity at
        landing is exactly (hit_end − HOME) / duration_ms. Trimmed by
        SHAPE_LAND_FACTOR for impact energy loss. Sampling from the
        rendered arc (with lift) instead leaks the arc's vertical-lift
        component into _ball_v[1] — for a sharp grounder, lift at t=0.97
        is ~3 px, contributing a spurious ~0.04 px/ms downward y-velocity
        that pushes the ball deeper post-landing. Linear sampling avoids
        the artifact entirely.
        """
        self._ball_pos = [self._hit_end[0], self._hit_end[1]]
        # Friction is a real deceleration in ft/s²; the animated clock and
        # the projection are applied here, once. Left as a raw px-per-
        # animated-ms² constant it was a hidden function of pacing —
        # distance-to-stop goes as v²/2a, so unifying the clock (which
        # raised every ball's px/ms velocity) silently multiplied roll
        # distance by about 1.7 and sent 18.5% of line-drive hits rolling
        # to the wall, where each one is forced to a double.
        self._ball_decel = self._roll_decel_px_ms2(
            self._hit_end[0] - HOME[0], self._hit_end[1] - HOME[1])

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

        factor = SHAPE_LAND_FACTOR.get(self.shape, 1.0)
        self._ball_v = [
            (self._hit_end[0] - HOME[0]) / self.duration_ms * factor,
            (self._hit_end[1] - HOME[1]) / self.duration_ms * factor,
        ]

        # Precompute a bounce schedule: a list of (start_ms, duration_ms, height_px)
        # entries running from landing forward. Each bounce retains COR² of the
        # previous height and COR of the previous duration (since t_air ∝ √h).
        # Generation stops when height drops below the visibility threshold.
        if self.shape == "GROUNDER" and self._grounder_peaks:
            base_peak = max(self._grounder_peaks)
        else:
            base_peak = self._hit_peak
        h = base_peak * SHAPE_BOUNCE_HEIGHT_FRAC.get(self.shape, 0.4)
        h = min(h, BOUNCE_HEIGHT_MAX_PX)

        self._bounces = []
        t_start = 0.0
        T = float(BOUNCE_INITIAL_DURATION_MS)
        # Grounders skip the post-flight bounce schedule. Their bounces are
        # already modeled in-flight (see _grounder_peaks / _arc_grounder),
        # so layering a fresh schedule on top re-bounces a ball that should
        # be settling into a roll — and the long bounce window combined with
        # friction + per-bounce loss kills the ball's velocity before it
        # gets through the infield. Pure rolling matches the real motion of
        # a grounder that's already taken its hops.
        if self.shape != "GROUNDER":
            while h > BOUNCE_HEIGHT_THRESHOLD_PX:
                self._bounces.append((t_start, T, h))
                t_start += T
                h *= BOUNCE_COR * BOUNCE_COR
                T *= BOUNCE_COR
        self._bounces_end_ms = t_start  # ball is rolling after this
        # Bounces fully completed so far — used to apply the per-bounce
        # horizontal-velocity impulse exactly once per impact.
        self._bounces_completed = 0

    def _fielded_ft(self):
        """Where the ball was actually gloved, in feet from home.

        Deliberately *not* `_ball`: on a grounder the throw sub-animation
        walks `_ball` over to first base, so by the time the play resolves
        `_ball` reads ~90 ft on every single one of them regardless of
        where it was fielded.
        """
        pos = self._inflight_catch_pos or self._ball
        return math.hypot(*_to_field_ft(pos))

    def _roll_decel_px_ms2(self, dx_px, dy_px):
        """Rolling friction as px per animated ms², along a screen bearing.

        Direction-dependent for the same reason fielder speed is: the
        projection is anisotropic, so one scalar px/ms² would be two
        different real decelerations depending on which way the ball rolled.
        """
        px = math.hypot(dx_px, dy_px)
        ft = _ft_dist(dx_px, dy_px)
        px_per_ft = (px / ft) if ft > 1e-9 else FT_TO_PX_X
        return ROLLING_DECEL_FT_S2 * px_per_ft / (1000.0 * self.time_scale) ** 2

    def _predict_ball_stop(self):
        """Predicted resting point of the rolling ball under linear friction.

        Stopping distance with constant deceleration a is v² / (2a). The
        prediction extrapolates from the ball's current velocity, so it
        adapts each frame as friction (and per-bounce impulses) shave
        speed off. Clamped inside the elliptical wall so a long chase
        target doesn't sit in geometry the fielder can't reach.

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
        stop_dist = (speed * speed) / (2.0 * max(1e-6, self._ball_decel))
        px = self._ball_pos[0] + vx / speed * stop_dist
        py = self._ball_pos[1] + vy / speed * stop_dist
        return _clamp_inside_wall((px, py), BALL_WALL_MARGIN_PX)

    def _current_bounce_lift(self, tau_ms):
        """Visual lift (px above ground) at time `tau_ms` since landing,
        looked up from the precomputed bounce schedule. Each entry is a
        parabolic hop with its own height and air-time. After the last
        bounce, the ball is rolling on the ground and lift is 0.
        """
        if tau_ms >= self._bounces_end_ms:
            return 0.0
        for t_start, t_dur, h in self._bounces:
            if t_start <= tau_ms < t_start + t_dur:
                phase = (tau_ms - t_start) / t_dur
                return h * math.sin(math.pi * phase)
        return 0.0

    def _step_ball_on_ground(self, dt_ms, tau_ms):
        """Integrate ball with linear friction; on contact with the elliptical
        wall, reflect the velocity component along the ellipse's outward
        normal (not the radial direction — the two only coincide for a
        circle). Restitution < 1 so a hard double caroms back toward the
        chasing fielder with reduced speed.

        Each time `tau_ms` crosses a bounce boundary, an impulse-style
        horizontal velocity loss (BOUNCE_HORIZONTAL_RETENTION) is applied
        on top of the continuous friction — captures ground friction during
        the impact, which is otherwise unmodeled by linear drag alone.
        """
        if dt_ms <= 0:
            return

        # Per-bounce horizontal impulse — apply once per completed bounce.
        completed = 0
        for t_start, t_dur, _ in self._bounces:
            if tau_ms >= t_start + t_dur:
                completed += 1
            else:
                break
        if completed > self._bounces_completed:
            retention = BOUNCE_HORIZONTAL_RETENTION ** (completed - self._bounces_completed)
            self._ball_v[0] *= retention
            self._ball_v[1] *= retention
            self._bounces_completed = completed

        speed = math.hypot(self._ball_v[0], self._ball_v[1])
        if speed > 0:
            new_speed = max(0.0, speed - self._ball_decel * dt_ms)
            if new_speed == 0.0:
                self._ball_v[0] = 0.0
                self._ball_v[1] = 0.0
            else:
                s = new_speed / speed
                self._ball_v[0] *= s
                self._ball_v[1] *= s
        self._ball_pos[0] += self._ball_v[0] * dt_ms
        self._ball_pos[1] += self._ball_v[1] * dt_ms

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
        margin_norm = BALL_WALL_MARGIN_PX / min(a, b)
        limit = 1.0 - margin_norm
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
                # to the wall before its bounce schedule is exhausted
                # would otherwise keep pogoing in place at the wall as
                # the remaining hops play out — same visual bug as the
                # in-flight wall impact. Truncate the schedule on contact
                # so the rebounded ball just rolls.
                self._bounces = []
                self._bounces_end_ms = 0.0
                self._bounces_completed = 0
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

        # Impact point: the wall edge along this angle, pulled in by
        # BALL_WALL_MARGIN_PX so the ball renders flush with the wall
        # face rather than embedded in it.
        impact_r = wall_r - BALL_WALL_MARGIN_PX
        impact_x = HOME[0] + impact_r * math.cos(angle)
        impact_y = HOME[1] - impact_r * math.sin(angle)
        self._hit_end = (impact_x, impact_y)

        # Initialize the on-ground physics with the original duration_ms
        # so the rolling velocity matches the ball's flight pace, then
        # scale by the wall-impact restitution and flip inward. The
        # inward flip is what makes the carom rebound back toward the
        # field; without it, ROLLING_DECEL takes the ball outward right
        # back into the rolling-phase wall-containment code, which
        # double-applies the reflection and reads as jittery.
        self._init_ball_on_ground()
        self._ball_v[0] = -self._ball_v[0] * WALL_HIT_FLIGHT_RESTITUTION
        self._ball_v[1] = -self._ball_v[1] * WALL_HIT_FLIGHT_RESTITUTION

        # The wall absorbs the vertical bounce energy on impact — in real
        # video the ball drops down the face and rolls back, it does not
        # pogo at the foot of the wall. _init_ball_on_ground built a fresh
        # bounce schedule from self._hit_peak (the original arc peak),
        # which combined with the heavily-damped rebound velocity produced
        # the "ball clips up and down at the wall then settles dead" bug.
        # Clearing the schedule lets the ball roll back cleanly from the
        # impact point.
        self._bounces = []
        self._bounces_end_ms = 0.0

        self._wall_hit = True

        # Render ball at the wall this frame too (otherwise the impact
        # frame briefly shows the ball past the wall before the next
        # frame snaps it back).
        self._ball = (impact_x, impact_y)
        self._ball_shadow = (impact_x, impact_y)

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
        catch_ft = _to_field_ft(catcher.pos)
        home_ft = _to_field_ft(catcher.home_pos)
        ball_distance_ft = math.hypot(*catch_ft)
        ranging_ft = math.dist(catch_ft, home_ft)

        # Charging = the fielder came up through the ball, toward the
        # plate. That is the barehand play on a slow roller, and it is
        # faster to release than a set throw, not slower.
        is_charging = math.hypot(*catch_ft) < math.hypot(*home_ft) - 2.0

        ev_mph = contact_audio.exit_velocity_mph(self.quality)

        # No throw means the fielder carries it to the bag on their own
        # legs, which is far slower per foot than an arm. Feeding the
        # model a sprint speed instead of a throw speed is all it takes —
        # it already measures the distance to first itself. Modelling a
        # carry as a throw would turn every unassisted play into an easy
        # out.
        throw_fts = (FIELDER_SPRINT_FT_S if unassisted
                     else infield_timing.THROW_EFFECTIVE_FTS)

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
            rng=random,
        )
        self.play_timing = timing
        if not infield_timing.roll_is_out(timing):
            # Beaten out. The throw still plays — the runner just gets
            # there first, which is the whole point of showing it.
            self.classified_outcome = "SINGLE"
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
            fielder = self.fielders[self._primary_role]
            timing = self._resolve_ground_ball(fielder, unassisted=False)
            if self.classified_outcome is None:
                self.classified_outcome = "GROUNDOUT"
            return timing

        secured_ft = _to_field_ft(self._ball)
        retrieved_at_s = self._secured_at_ms / (1000.0 * self.time_scale)
        # A ball that reached the wall is past every outfielder by
        # definition, so it cannot be a single however the carom returns.
        min_base = 2 if self._wall_hit else 1
        base, margin = extra_bases.final_base(
            ball_xy_ft=secured_ft,
            retrieved_at_s=retrieved_at_s,
            is_outfielder=self._primary_role in OUTFIELD_ROLES,
            handedness=self._batter_handedness(),
            sprint_fts=self._runner_sprint_fts(),
            difficulty_offset_s=self._difficulty_time_offset_s(),
            min_base=min_base,
            rng=random,
        )
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

    def _trigger_in_flight_intercept(self, catcher_role, catch_pos):
        """A fielder reached the ball pre-landing. Switch to the
        appropriate finishing sub-animation: throw-to-1B for grounders
        fielded by an infielder, a catch-hold for everything else.
        """
        self._secured = True
        self._secured_in_flight = True
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

    def _render_post_in_flight_catch(self, elapsed):
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

        # Finishing rules:
        #   * Ball secured in flight (FLYOUT/GROUNDOUT branch): the
        #     post-catch sub-animation owns timing — finish once
        #     `_go_done_ms` has elapsed.
        #   * IN_PLAY ball lands and rolls (SINGLE/DOUBLE/TRIPLE): finish
        #     once a fielder secures it on the ground.
        #   * HOME RUN: scripted duration_ms; finish on expiry.
        if self._secured_in_flight:
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
        if self._secured_in_flight:
            self._render_post_in_flight_catch(elapsed)
            return

        in_flight = elapsed <= self.duration_ms

        if in_flight:
            t = elapsed / self.duration_ms
            if self.shape == "GROUNDER":
                self._ball = _arc_grounder(HOME, self._hit_end, self._grounder_peaks, t)
            elif self.shape == "LINER":
                self._ball = _arc_liner(HOME, self._hit_end, self._hit_peak, t)
            else:
                self._ball = _arc_fly(HOME, self._hit_end, self._hit_peak, t)
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
                    # Intercept fired this frame — the post-catch flow
                    # owns rendering and fielder targets from here on.
                    # Returning short-circuits the in-flight primary
                    # motion block below, which would otherwise reset
                    # the catcher's target to self._hit_end and pull
                    # the 1B away from the bag we just routed them to.
                    self._render_post_in_flight_catch(elapsed)
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
            if self._chases_in_flight(self._primary_role):
                self._route_in_flight_chase(primary)
            elif self._primary_role not in ("P", "C"):
                primary.target = self._pursuit_point(primary, self._hit_end)
        elif self._needs_secure and not self._secured:
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
            chase_pool = [r for r in self.fielders.keys() if r not in ("P", "C")]
            closest_role = min(
                chase_pool,
                key=lambda r: math.hypot(
                    self.fielders[r].pos[0] - self._ball[0],
                    self.fielders[r].pos[1] - self._ball[1],
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
            # Aim for the predicted stopping point so the primary cuts
            # off the roll instead of trailing the live ball — same
            # straight-line-to-the-spot logic the lean-target chase uses.
            primary.target = self._predict_ball_stop()
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
                primary.pos[0] - self._ball[0],
                primary.pos[1] - self._ball[1],
            )
            for role, f in self.fielders.items():
                d = math.hypot(f.pos[0] - self._ball[0],
                               f.pos[1] - self._ball[1])
                if d < closest_dist:
                    closest_dist = d
                    closest_role = role
            if closest_dist < SECURE_RADIUS_PX:
                self._secured = True
                self._secured_at_ms = self._elapsed
                if closest_role is not None and closest_role != self._primary_role:
                    self._primary_role = closest_role
                # Stand down every other defender. On this branch
                # `self.finished` flips on the next update tick, so
                # there's only one frame left to render — but without
                # this reset that final frame still shows the pitcher
                # / cutoff IF / unused secondaries one stride into
                # their stale targets, which reads as them not noticing
                # the play is over.
                self._stand_down_non_primary(keep_at_bag=False)
                if self.outcome == "IN_PLAY" and self.classified_outcome is None:
                    self._resolve_extra_bases()

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

        sx, sy = int(self._ball_shadow[0]), int(self._ball_shadow[1])
        pygame.draw.ellipse(screen, (60, 60, 60), pygame.Rect(
            sx - BALL_SHADOW_W_PX // 2, sy - BALL_SHADOW_H_PX // 2,
            BALL_SHADOW_W_PX, BALL_SHADOW_H_PX))

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

    def _draw_hr_distance(self, screen):
        # Fade in once t > 0.7 (ball is near/over the wall); full at 0.85.
        t = self._elapsed / max(1, self.duration_ms)
        if t < 0.7:
            return
        alpha = max(0.0, min(1.0, (t - 0.7) / 0.15))

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
