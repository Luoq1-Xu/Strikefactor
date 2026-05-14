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
  * HR distance — quality-driven mapping (~365–485 ft) overlays once
    the ball clears the wall.

Field geometry is anchored to a 45° foul-line cone. Bases sit on the foul
lines (1B / 3B) and at the apex (2B). All in-play destinations satisfy
|dx| < dy so the ball stays in fair territory.
"""

import math
import random
from dataclasses import dataclass

import pygame


HOME = (640, 670)

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

# Default standing positions for all 9 defenders, in real feet. Distances are
# typical MLB positioning: corner IFs ~95 ft, middle IFs ~145 ft, corner OFs
# ~290 ft, CF ~310 ft. The anisotropic projection then stretches the layout
# horizontally on screen — fielders end up "wider apart" than they would be
# under a square top-down camera.
FIELDER_HOMES = {
    "P":  PITCHERS_MOUND,
    "C":  _to_screen(0.0,   -20.0),     # behind plate (slight foul-territory offset)
    "1B": _to_screen(+61.0,  71.0),     # ~95 ft, off bag toward 2B
    "2B": _to_screen(+50.0, 136.0),     # ~145 ft, between 1B and 2B
    "SS": _to_screen(-50.0, 136.0),     # ~145 ft, between 2B and 3B
    "3B": _to_screen(-61.0,  71.0),     # ~95 ft, off bag toward home
    "LF": _to_screen(-99.0, 273.0),     # ~290 ft
    "CF": _to_screen(0.0,   310.0),     # ~310 ft (deepest)
    "RF": _to_screen(+99.0, 273.0),     # ~290 ft
}
ROLES = list(FIELDER_HOMES.keys())
INFIELD_ROLES = ["1B", "2B", "SS", "3B"]
OUTFIELD_ROLES = ["LF", "CF", "RF"]
# Groundout primary candidates — 1B excluded so we keep the throw-to-first beat.
GROUNDOUT_PRIMARY_ROLES = ["SS", "2B", "3B"]

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

# Foul lines drawn from home out to where they meet the elliptical wall
# (the 45° real-field direction, anisotropically projected). For an ellipse
# (x/a)² + (y/b)² = 1 with x = y on the foul line, the intersection is at
# a·b / √(a² + b²) per axis — NOT a/√2 (which would only be right for a
# circular wall). Under our 330·400 wall this is ≈ 254.6 ft, not 233 ft.
FOUL_LINE_END_FT = WALL_FT_X * WALL_FT_Y / math.sqrt(WALL_FT_X**2 + WALL_FT_Y**2)

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

# Phase timings (ms). Lengthened for more cinematic pacing — fast translation
# of small circles read as "gliding"; slower timings give the eye time to
# track the ball and the fielders' run-ups.
GROUNDOUT_TRAVEL_MS    = 1700
GROUNDOUT_FIELD_HOLD   =  350
GROUNDOUT_THROW_MS     =  850
GROUNDOUT_CATCH_HOLD   =  450

FLYOUT_TRAVEL_MS       = 4000
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

# Per-shape landing-distance ranges (ft) for the generic HIT outcome,
# parameterized by quality. Quality maps the random sample inside the
# range — q=0 lands near the min, q=1 near the max — and a small uniform
# spread keeps each contact looking distinct. GROUNDER doesn't use this
# table; it routes through SQUIBBLER_LANDING / GROUNDER_SINGLE_LANDING
# (already shape-specific). POP_UP routes through POPUP_LANDING (shallow
# regardless). LINER/FLY use these ranges directly.
HIT_LANDING_FT = {
    # FLY range extends past the OFs (~290–310 ft home) into the warning
    # track so well-struck balls actually clear the defenders. Combined with
    # wall-hit detection in classification, this lets balls off the wall
    # become doubles/triples instead of dying as singles in the OF's glove.
    "LINER": (140, 290),
    "FLY":   (170, 360),
}

# Retrieve-time thresholds (ms from landing to fielder securing the ball).
# Drives SINGLE / DOUBLE / TRIPLE classification for the HIT outcome.
# Calibrated against a fielder's natural run-up time on routine plays —
# even an OF charging in on a shallow fly takes ~2.5–3 s from landing to
# the ball, so the SINGLE cutoff has to sit above that or every routine
# play classifies as a single. The TRIPLE cutoff is set against the
# deepest geometrically-possible chase (CF home → wall ≈ 100 px ≈ 2.5 s
# sprint, plus reaction + accel ramp ≈ ~3 s), so it sits just above that
# natural ceiling — too high and no chase reaches it (5000 ms produced
# zero triples in practice). Wall-bouncers use a lower cutoff (see
# RETRIEVE_TIME_WALL_TRIPLE_MS) since a ball off the wall is physically
# at minimum a double and a large fraction should be triples.
RETRIEVE_TIME_SINGLE_MAX_MS = 2800
RETRIEVE_TIME_DOUBLE_MAX_MS = 3800
RETRIEVE_TIME_WALL_TRIPLE_MS = 3300
# Separate, much lower triple threshold for in-flight wall hits. Retrieve
# time on these is measured from the moment of wall impact (the helper
# truncates duration_ms there), and the fielder is typically near the
# wall already because they paced themselves toward the past-the-wall
# landing during flight. Empirically retrieve times cluster in
# 400–1500 ms; ~1050 ms picks out the longest chases (gap shots where
# the closest OF still had ground to cover) as triples while keeping
# the routine corner-OF caroms as doubles.
RETRIEVE_TIME_INFLIGHT_WALL_TRIPLE_MS = 1050
# Pop-up landing — shallow, regardless of underlying outcome (real-feet depth).
POPUP_LANDING = {"depth_ft": (105, 155), "lateral_frac": 0.5}

# Hard grounder single — lands inside the IF (between/just past the IFs)
# and rolls out into the OF for the OF to retrieve. Models the real-life
# pattern where a sharp grounder up the middle or in the hole becomes a
# single by passing the IFs, not by being dropped past them.
GROUNDER_SINGLE_LANDING = {"depth_ft": (130, 185), "lateral_frac": 0.55}

# Rolling friction during the post-landing phase (px/ms²). Uniform across
# hit outcomes — once a baseball is on the grass, friction is a property
# of the surface, not how the ball got there. Distance-to-stop scales as
# v²/(2a), so harder hits naturally roll farther without any per-outcome
# tuning. Real grass rolling friction is ~3–10 ft/s² (≈0.1–0.3g); we run
# higher than that for game pacing, but low enough that the ball still
# clearly rolls for 1–2 s after the bounces stop. Higher friction also
# keeps balls from routinely reaching the wall and rebounding straight
# back into a fielder's glove.
ROLLING_DECEL_PX_MS2 = 0.000035

# Energy retained on impact, multiplied onto the sampled in-flight velocity.
# Liner skips through; grounder is already on the ground; fly drops nearly
# vertically and loses some horizontal carry; pop-up deadens hard. This is
# the only place shape affects post-landing speed — once the ball is on the
# ground, friction is a property of the grass, not the trajectory shape, so
# rolling decel is uniform across shapes (see ROLLING_DECEL_PX_MS2).
SHAPE_LAND_FACTOR = {
    "LINER":    0.92,
    "GROUNDER": 1.00,
    "FLY":      0.80,
    "POP_UP":   0.55,
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
# Wall caroms now lose ~80% of energy on impact (was 0.55 = ~70% retained).
# At the previous restitution, a screamer that reached the wall came back
# at 55% of its incoming speed and rolled most of the way back to a fielder
# in shallow OF — turning what should be a wall-bound XBH into an instant
# single. With 0.20, the ball loses most of its momentum on the wall and
# essentially dies there; a fielder still has to run all the way out.
WALL_BOUNCE_RESTITUTION = 0.20

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
WALL_HIT_QUALITY_THRESHOLD = 0.50
WALL_HIT_PROB_MAX          = 0.40
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
# Restitution on the post-impact rolling velocity. Lower than the
# ground-phase WALL_BOUNCE_RESTITUTION because a ball striking the wall
# in flight loses more energy than one already on the ground grazing it.
# The velocity is also flipped inward so the ball rebounds toward the
# fielder rather than continuing outward (and clipping further into
# the on-ground wall-containment logic).
WALL_HIT_FLIGHT_RESTITUTION = 0.15

# Squibbler landing — weak grounder, very short travel (~70–125 ft).
SQUIBBLER_LANDING = {"depth_ft": (70, 125), "lateral_frac": 0.5}

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
FLYOUT_FLY_PEAK = 180

# Hit shape weights — drives the "every SINGLE looks different" feel.
SHAPE_WEIGHTS = {
    "SINGLE":   [("LINER", 0.50), ("GROUNDER", 0.30), ("FLY", 0.15), ("POP_UP", 0.05)],
    "DOUBLE":   [("LINER", 0.60), ("FLY", 0.40)],
    "TRIPLE":   [("FLY", 1.00)],
    "HOME RUN": [("FLY", 1.00)],
}

# HR carry past the wall (px). Most HRs barely clear; only the highest
# quality contact carries deep. The displayed distance is computed from
# the actual landing position rather than a quality-only mapping, so the
# number on screen always matches where the ball lands. A squared bias
# (carry = base + (rand**EXPONENT) * range) skews most carries toward
# zero — i.e., "just-cleared" wall-scrapers — so blasts to the deepest
# part of the screen are the rare exception, not the norm.
HR_CARRY_MIN_PX           = 4
HR_CARRY_BASE_RANGE_PX    = 22
HR_CARRY_QUALITY_BONUS_PX = 60
HR_CARRY_BIAS_EXPONENT    = 2.0

# Fielder motion. Constant-velocity with acceleration/deceleration phases —
# exponential easing produced a "snap to position then freeze" look that
# read as unnatural. Real fielders ramp up, cruise, and decelerate.
FIELDER_MAX_SPEED_PX_MS = 0.040         # ~28 ft/sec at 1.4 px/ft (MLB Statcast avg sprint speed)
FIELDER_ACCEL_TIME_MS   = 220.0         # ramp from 0 to max_speed
FIELDER_DECEL_RADIUS_PX = 28.0          # start slowing within this radius of target
FIELDER_DECEL_FLOOR     = 0.20          # never below 20% speed in decel zone
REACTION_DELAY_MIN_MS   = 200.0         # see-react-step: a real OF needs 200–400 ms before the first stride
REACTION_DELAY_MAX_MS   = 380.0         # jittered per fielder so they don't all start in sync
SWAY_AMPLITUDE          = 1.6
SWAY_FREQUENCY          = 0.0018        # rad/ms
LEAN_BASE_PX            = 5.0           # initial lean magnitude
LEAN_GROWTH_PX          = 18.0          # additional lean magnitude as play progresses

BODY_RADIUS_PX          = 8
BODY_COLOR              = (220, 220, 220)
GLOVE_COLOR             = (255, 200, 100)

# Hit chase phase. After the ball lands on a SINGLE/DOUBLE/TRIPLE, the
# primary fielder keeps running until they reach the ball, then the
# animation pauses. SECURE_RADIUS is the body+ball overlap distance
# (roughly the body radius) at which the ball is "secured." No timeout —
# friction guarantees the ball stops eventually, and the fielder converges
# afterwards; we let the play run to a natural close rather than truncating.
SECURE_RADIUS_PX        = 14
# Post-landing, any non-primary fielder this close to the live ball ditches
# the "lean toward the ball" idle and actively chases at full sprint. Real
# baseball isn't single-fielder — when a ball rolls past the assigned
# pursuer toward another defender, that defender is who actually picks it
# up. ~100 px ≈ 70 ft is tight enough that only genuinely nearby fielders
# intervene; with a wider radius, multiple OFs converged on every play and
# the closest one always secured fast (turning extra-base hits into singles).
ACTIVE_CHASE_RADIUS_PX  = 100


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


def _pick_hit_landing(outcome, shape, quality=1.0):
    """Pick a landing point that matches the real-life pattern of each hit
    type. Singles drop in front of the OFs (or sneak through the IF) so the
    OF charges forward; doubles split the gaps or roll down the line;
    triples carry to (or near) the wall in deep gaps or down the corner;
    HRs land past the elliptical wall, biased toward the pull/center area.

    POP_UPs and squibblers override outcome-specific depth — they're shape-
    driven (pop-up = shallow infield fly; squibbler = weak grounder) and
    behave the same regardless of which SINGLE outcome generated them.

    GROUNDER hits also override depth: real grounder singles land inside
    the IF and roll past the IFs into the OF, rather than dropping in past
    them. The post-landing roll (ROLLING_DECEL_PX_MS2) carries the ball out.
    """
    # Shape overrides — POP_UP and squibblers ignore outcome distance.
    if shape == "POP_UP":
        spec = POPUP_LANDING
        depth_ft = random.uniform(*spec["depth_ft"])
        lat_ft = random.uniform(-1, 1) * depth_ft * spec["lateral_frac"]
        return _clamp_inside_wall(_to_screen(lat_ft, depth_ft),
                                  LANDING_WALL_MARGIN_PX)
    # Grounder hits — squibbler vs hard contact split. Both apply to the
    # generic HIT outcome and to legacy SINGLE callers.
    if shape == "GROUNDER" and outcome in ("SINGLE", "HIT"):
        if quality < SQUIBBLER_QUALITY_THRESHOLD:
            spec = SQUIBBLER_LANDING
        else:
            spec = GROUNDER_SINGLE_LANDING
        depth_ft = random.uniform(*spec["depth_ft"])
        lat_ft = random.uniform(-1, 1) * depth_ft * spec["lateral_frac"]
        return _clamp_inside_wall(_to_screen(lat_ft, depth_ft),
                                  LANDING_WALL_MARGIN_PX)

    # Generic HIT — quality-driven distance and a layered angle bias for
    # higher-quality contact: down-the-line shots, LCF/RCF gap shots, or
    # uniform-across-fair as a fallback. The retrieve-time classification
    # downstream converts long carries into doubles/triples and short ones
    # into singles, so we only need to produce a believable physical
    # landing — but routing more high-quality contact toward the lines and
    # gaps is what gives the corner OF a long chase, which is where real-
    # life doubles and triples come from.
    if outcome == "HIT":
        q = max(0.0, min(1.0, quality))
        dist_min, dist_max = HIT_LANDING_FT.get(shape, HIT_LANDING_FT["LINER"])
        # Center the random window around q-scaled mid; keeps each contact
        # different even at fixed quality.
        mid = dist_min + (dist_max - dist_min) * q
        spread = (dist_max - dist_min) * 0.18
        dist_ft = random.uniform(max(dist_min, mid - spread),
                                 min(dist_max, mid + spread))
        # Probabilities sum to <= 1; the leftover budget falls through to
        # the uniform-across-fair branch. Higher quality unlocks more line
        # and gap shots — the angles where the corner OF has the longest
        # run-up.
        line_prob = 0.08 + 0.20 * q
        gap_prob  = 0.22 + 0.30 * q
        roll = random.random()
        if roll < line_prob:
            # Down-the-line shot. 53° / 127° sit just inside the foul lines
            # (50° / 130° clamp) so the ball stays fair without drifting
            # back toward CF. The corner OF (LF/RF) has to cover ~150–200 px
            # to retrieve, naturally producing extra-base hits.
            side = random.choice((-1, 1))
            base = math.radians(53) if side > 0 else math.radians(127)
            angle = base + random.uniform(-0.05, 0.05)
        elif roll < line_prob + gap_prob:
            side = random.choice((-1, 1))
            gap = math.radians(79) if side > 0 else math.radians(101)
            angle = gap + random.uniform(-0.10, 0.10)
        else:
            angle = random.uniform(math.radians(50), math.radians(130))
        return _clamp_inside_wall(_polar_point_ft(angle, dist_ft),
                                  LANDING_WALL_MARGIN_PX)

    if outcome == "HOME RUN":
        # HRs land past the wall. Direction biased toward the pull/center
        # area (most HRs aren't down-the-line shots). Carry past the wall
        # uses a squared bias so most rolls produce small carries (just-
        # cleared, wall-scrapers); only the right tail produces deep blasts.
        # Quality enlarges the *range* of possible carries, not the
        # likelihood of large ones — so even on max-quality contact, most
        # HRs still barely clear, with the occasional moonshot.
        #
        # Note: the gauss is sampled in screen-angle space because the wall
        # ellipse and carry distance are both in screen-space pixels. The
        # std-dev is tighter than the original 22° because the anisotropic
        # projection makes the fair cone span a narrower range of *screen*
        # angles (~59°–121°) than it did under the old isotropic projection.
        angle = random.gauss(math.radians(90), math.radians(15))
        angle = max(math.radians(50), min(math.radians(130), angle))
        wall_r = _wall_r_at(angle)
        q = max(0.0, min(1.0, quality))
        bias = random.random() ** HR_CARRY_BIAS_EXPONENT
        carry_range = HR_CARRY_BASE_RANGE_PX + q * HR_CARRY_QUALITY_BONUS_PX
        carry_px = HR_CARRY_MIN_PX + bias * carry_range
        return _polar_point(angle, wall_r + carry_px)

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
        return "POP_UP" if vertical_offset < -25 else "FLY"
    if outcome == "HIT":
        if vertical_offset < -25:
            return "POP_UP"
        if vertical_offset < -8:
            return "FLY"
        if vertical_offset > 8:
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


@dataclass
class Fielder:
    """One defender. `pos` is mutated each frame.

    Motion model: after `reaction_delay_ms`, accelerate over `accel_time_ms`
    to `max_speed`, cruise at constant velocity toward `target`, then
    decelerate inside `decel_radius_px`. All four are jittered per fielder
    so the team doesn't speed up, cruise, or settle in lockstep.
    """
    role: str
    home_pos: tuple
    pos: list           # [x, y], mutable
    target: tuple
    sway_phase: float
    max_speed: float = FIELDER_MAX_SPEED_PX_MS
    reaction_delay_ms: float = 200.0
    accel_time_ms: float = FIELDER_ACCEL_TIME_MS
    decel_radius_px: float = FIELDER_DECEL_RADIUS_PX


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

    def __init__(self, game, outcome, on_complete, vertical_offset=0.0, quality=0.0, batted_ball_type=None):
        self.game = game
        self.outcome = outcome
        self.on_complete = on_complete
        self.vertical_offset = vertical_offset
        self.quality = quality
        self.batted_ball_type = batted_ball_type

        self.start_time = None
        self.banner_fired = False
        self.finished = False
        self._elapsed = 0
        self._last_elapsed = 0

        # For HIT (and legacy SINGLE/DOUBLE/TRIPLE) the ball lands on the
        # ground and a fielder has to run it down. Animation pauses when
        # secured (within SECURE_RADIUS_PX of the ball) instead of timing
        # out at duration_ms. For HIT the resolved outcome is classified
        # from the secure time — see classified_outcome below.
        self._needs_secure = outcome in ("SINGLE", "DOUBLE", "TRIPLE", "HIT")
        self._secured = False
        self._secured_at_ms = None  # elapsed time when ball was retrieved

        # Final outcome after classification. For non-HIT outcomes this is
        # known up front; for HIT it stays None until the fielder secures
        # the ball, at which point retrieve time picks SINGLE/DOUBLE/TRIPLE.
        self.classified_outcome = None if outcome == "HIT" else outcome

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
            reaction_delay_ms=random.uniform(REACTION_DELAY_MIN_MS, REACTION_DELAY_MAX_MS),
            max_speed=FIELDER_MAX_SPEED_PX_MS * random.uniform(0.78, 1.22),
            accel_time_ms=FIELDER_ACCEL_TIME_MS * random.uniform(0.7, 1.35),
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

        # Per-frame ball state.
        self._ball = HOME
        self._ball_shadow = HOME

        # HR distance (set after _setup_hit, from the actual landing point).
        self.hr_distance_ft = None

        # Outcome-specific setup + target assignment.
        if outcome == "GROUNDOUT":
            self._setup_groundout()
        elif outcome == "FLYOUT":
            self._setup_flyout()
        elif outcome in ("HIT", "HOME RUN", "SINGLE", "DOUBLE", "TRIPLE"):
            self._setup_hit(outcome)
        else:
            self.outcome = "HIT"
            self.classified_outcome = None
            self._setup_hit("HIT")

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

    # ---- Setup ----------------------------------------------------------

    def _setup_groundout(self):
        # Primary infielder: random among SS/2B/3B.
        self._primary_role = random.choice(GROUNDOUT_PRIMARY_ROLES)
        primary_home = self.fielders[self._primary_role].home_pos

        # Small "fielding hop" — primary takes a step toward the ball arrival
        # point so they aren't statue-still when the ball reaches them.
        hop = (random.uniform(-7, 7), random.uniform(-7, 7))
        self._fielder_at = (primary_home[0] + hop[0], primary_home[1] + hop[1])
        self.fielders[self._primary_role].target = self._fielder_at

        # Bounce profile — weak contact bounces multiple times. Distance
        # to the fielder scales the bounce count so each hop covers
        # spacing_px and the ball touches grass between every hop.
        groundout_dist_px = math.hypot(self._fielder_at[0] - HOME[0],
                                       self._fielder_at[1] - HOME[1])
        self._grounder_peaks = _grounder_peaks(self.quality, groundout_dist_px)

        # 1B covers the bag; throw destination follows them so the ball
        # arrives where the fielder actually is.
        self.fielders["1B"].target = (BASES["1B"][0] - 7, BASES["1B"][1] + 5)
        self._first_base = self.fielders["1B"].target

        # Backup at second: 2B normally, SS if 2B is the primary.
        backup_role = "2B" if self._primary_role != "2B" else "SS"
        self.fielders[backup_role].target = (BASES["2B"][0] + 4, BASES["2B"][1] + 2)

        self._t_ball_arrive = GROUNDOUT_TRAVEL_MS
        self._t_throw_start = self._t_ball_arrive + GROUNDOUT_FIELD_HOLD
        self._t_throw_arrive = self._t_throw_start + GROUNDOUT_THROW_MS
        self._t_done = self._t_throw_arrive + GROUNDOUT_CATCH_HOLD
        self.duration_ms = self._t_done

        # Primary, 1B, and backup have explicit targets — exclude from lean.
        self._lean_excluded = {self._primary_role, "1B", backup_role}

    def _setup_flyout(self):
        # POP_UP — caught by an infielder near the diamond.
        # LINER  — line-drive caught by the closest OF/IF on a flat arc.
        # FLY    — caught by the closest outfielder on a high arc.
        if self.shape == "POP_UP":
            base = self.fielders[random.choice(INFIELD_ROLES)].home_pos
            target = (base[0] + random.uniform(-25, 25),
                      base[1] + random.uniform(-15, 15))
            self._flyout_peak = random.uniform(*POPUP_PEAK_RANGE)
            pool = INFIELD_ROLES
        elif self.shape == "LINER":
            # Liner outs are line drives right at someone — usually an OF
            # but occasionally an IF snags one. Flat arc per LINER_PEAK_RANGE.
            pool = OUTFIELD_ROLES if random.random() < 0.80 else INFIELD_ROLES
            base = self.fielders[random.choice(pool)].home_pos
            target = (base[0] + random.uniform(-30, 30),
                      base[1] + random.uniform(-20, 20))
            self._flyout_peak = random.uniform(*LINER_PEAK_RANGE)
        else:
            base = self.fielders[random.choice(OUTFIELD_ROLES)].home_pos
            target = (base[0] + random.uniform(-50, 50),
                      base[1] + random.uniform(-30, 30))
            self._flyout_peak = FLYOUT_FLY_PEAK
            pool = OUTFIELD_ROLES

        # Clamp inside fair territory.
        depth = abs(HOME[1] - target[1])
        max_lat = depth * 0.75
        dx = target[0] - HOME[0]
        target = (HOME[0] + max(-max_lat, min(max_lat, dx)), target[1])
        self._fielder_target = target

        # Primary: closest fielder in the relevant pool.
        self._primary_role = self._closest_role_in(pool, target)
        self._fielder_start = self.fielders[self._primary_role].home_pos

        self._t_ball_arrive = FLYOUT_TRAVEL_MS
        self._t_done = self._t_ball_arrive + FLYOUT_CATCH_HOLD
        self.duration_ms = self._t_done

        # Adjacent fielder backs up — steps a third of the way toward the catch.
        backup = self._adjacent_role(self._primary_role, pool)
        excluded = {self._primary_role}
        if backup is not None:
            home = self.fielders[backup].home_pos
            self.fielders[backup].target = _lerp(home, target, 0.3)
            excluded.add(backup)

        # Stash for phase-tied primary motion in _update_flyout.
        self._primary_start = self._fielder_start
        self._primary_stop = target

        self._lean_excluded = excluded

    def _setup_hit(self, outcome):
        # Wall-candidate selection. A subset of high-quality FLY/LINER HITs
        # are routed past the wall so they strike the wall face on the fly
        # (see WALL_HIT_* constants and _maybe_trigger_in_flight_wall_impact).
        # Default off; flipped on only when all the gates pass.
        self._is_wall_candidate = False
        if (
            outcome == "HIT"
            and self.shape in ("FLY", "LINER")
            and self.quality >= WALL_HIT_QUALITY_THRESHOLD
        ):
            q = max(0.0, min(1.0, self.quality))
            prob = WALL_HIT_PROB_MAX * (q - WALL_HIT_QUALITY_THRESHOLD) / (
                1.0 - WALL_HIT_QUALITY_THRESHOLD
            )
            if random.random() < prob:
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
            self._hit_end = _pick_hit_landing(outcome, self.shape, self.quality)

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

        # Duration. HOME RUN keeps its scripted hang time. HIT (across all
        # shapes) is quality-scaled: harder contact zips visually, weaker
        # contact drifts. Scaling is intentionally gentle (1.2 → 0.8 of
        # base) so even q=1 contact takes ~2.6 s in the air rather than
        # rocketing through the field faster than the fielders can read.
        if outcome == "HOME RUN":
            self.duration_ms = HR_DURATION_MS
        else:
            q = max(0.0, min(1.0, self.quality))
            self.duration_ms = int(HIT_BASE_DURATION_MS * (1.2 - 0.4 * q))

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

        # Pick primary fielder by depth: POP_UPs and squibblers (which land
        # 80–130 ft from home) go to an IF; balls past the IFs go to the OF.
        # Threshold (-220 px) sits just past the deepest IF home (145 ft =
        # 203 px). Hard grounder hits get a dedicated override — they land
        # in the IF but roll out past it, and the OF (not the IF) picks
        # them up, so we route to the OF up front.
        is_grounder_single_through = (
            outcome in ("SINGLE", "HIT") and self.shape == "GROUNDER"
            and self.quality >= SQUIBBLER_QUALITY_THRESHOLD
        )
        if self.shape == "POP_UP" or (
            self._hit_end[1] > HOME[1] - 220
            and not is_grounder_single_through
        ):
            primary = self._closest_role_in(INFIELD_ROLES, self._hit_end)
            primary_pool = INFIELD_ROLES
        else:
            primary = self._closest_role_in(OUTFIELD_ROLES, self._hit_end)
            primary_pool = OUTFIELD_ROLES
        self._primary_role = primary

        # Primary runs toward the projected landing point. _update_hit
        # retargets the live ball each frame after landing, so the fielder
        # keeps moving until they secure it — no "stops short, then resumes
        # chase" beat. _primary_start kept for the guard in _update_hit.
        primary_home = self.fielders[primary].home_pos
        self._primary_start = primary_home
        self.fielders[primary].target = self._hit_end
        # Tight decel zone so the primary doesn't ease off as they approach
        # the landing — only decelerate at the ball itself. Outside this
        # radius they run at constant cruise speed.
        self.fielders[primary].decel_radius_px = SECURE_RADIUS_PX

        # Pace the primary so they're STILL RUNNING IN when the ball lands —
        # not standing on the spot waiting. With realistic OF positioning,
        # the closest fielder is often only 50–100 ft from where the ball
        # ends up, and at full sprint (28 ft/sec) they'd cover that in
        # 1.5–3 sec while the ball is in the air for ~3 sec. Without
        # pacing they reach the landing spot before the ball does and the
        # ball drops onto them — exactly what the user reported.
        #
        # We pace so the fielder finishes their run-up ~1200 ms after the
        # ball lands; the buffer is sized so the gap between fielder and
        # ball at landing is roughly run_dist × 1490/(flight+1200) ≈
        # run_dist × 0.4 — i.e., about 20–40 px of visible separation for
        # typical run distances, comfortably outside SECURE_RADIUS_PX.
        # On long routes (deep gappers, balls down the line) the required
        # speed exceeds max and they sprint anyway, naturally arriving
        # late; pacing only kicks in for the medium-range routes that
        # were producing the "ball lands on the fielder" frames.
        self._primary_full_speed = self.fielders[primary].max_speed
        run_dist = math.hypot(self._hit_end[0] - primary_home[0],
                              self._hit_end[1] - primary_home[1])
        move_ms = max(1.0, self.duration_ms + 1200)
        required = run_dist / move_ms
        # No floor — close-by balls intentionally jog slowly so the fielder
        # doesn't arrive early and stand under the drop. The post-landing
        # phase sprints at full speed regardless (see _update_hit), so the
        # slow pace only applies during ball flight.
        self.fielders[primary].max_speed = min(self._primary_full_speed, required)

        excluded = {primary}

        # Cutoff vs. backup. The classified outcome isn't known yet for HIT,
        # so use the landing depth as the proxy: any ball that lands deep
        # enough to be a potential XBH gets the relay infielder shifted to
        # the cutoff line. Shallow hits get an adjacent backup instead.
        landing_dist = math.hypot(self._hit_end[0] - HOME[0],
                                  self._hit_end[1] - HOME[1])
        deep_hit = landing_dist > 280  # ~200 ft — past where corner OFs play
        if outcome in ("DOUBLE", "TRIPLE") or (outcome == "HIT" and deep_hit):
            cutoff = "SS" if self._hit_end[0] < HOME[0] else "2B"
            if cutoff != primary:
                cutoff_home = self.fielders[cutoff].home_pos
                self.fielders[cutoff].target = _lerp(cutoff_home, self._hit_end, 0.45)
                excluded.add(cutoff)
        else:
            # Adjacent fielder backs up.
            backup = self._adjacent_role(primary, primary_pool)
            if backup is not None:
                home = self.fielders[backup].home_pos
                self.fielders[backup].target = _lerp(home, self._hit_end, 0.25)
                excluded.add(backup)

        self._lean_excluded = excluded

    # ---- Helpers --------------------------------------------------------

    def _closest_role_in(self, roles, target):
        return min(roles, key=lambda r: math.hypot(
            self.fielders[r].home_pos[0] - target[0],
            self.fielders[r].home_pos[1] - target[1]))

    def _adjacent_role(self, role, pool):
        """Pick a different role from the same pool — the backup."""
        others = [r for r in pool if r != role]
        if not others:
            return None
        return min(others, key=lambda r: math.hypot(
            self.fielders[r].home_pos[0] - self.fielders[role].home_pos[0],
            self.fielders[r].home_pos[1] - self.fielders[role].home_pos[1]))

    def _update_lean_targets(self):
        """Recompute non-primary fielder targets each frame.

        Default: small "lean" toward the ball — keeps the team alive at
        rest without committing to a play. Magnitude grows with progress,
        so fielders keep moving a step at a time instead of freezing.

        After the ball has landed and is on the ground, any non-primary
        fielder within ACTIVE_CHASE_RADIUS_PX of the live ball ditches the
        lean and actively chases at full sprint. This handles the case
        where the ball rolls past the assigned primary toward a different
        defender — that defender becomes a real pursuer instead of just
        leaning into the play.
        """
        progress = min(1.0, self._elapsed / max(1, self.duration_ms))
        max_lean = LEAN_BASE_PX + LEAN_GROWTH_PX * progress
        focus = self._ball
        ball_on_ground = (self._needs_secure
                          and self._elapsed > self.duration_ms
                          and not self._secured)
        for role, f in self.fielders.items():
            if role in self._lean_excluded:
                continue
            if ball_on_ground:
                d_ball = math.hypot(focus[0] - f.pos[0],
                                    focus[1] - f.pos[1])
                if d_ball < ACTIVE_CHASE_RADIUS_PX:
                    f.target = (focus[0], focus[1])
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
        """Constant-velocity motion with acceleration ramp + decel zone.

        Phases:
          1. Reaction delay — fielder reads the ball; no movement.
          2. Acceleration — speed ramps from 0 to max_speed over accel_time_ms.
          3. Cruise — constant velocity toward target.
          4. Deceleration — within decel_radius_px, scale speed by dist/radius
             (with a floor) so the fielder settles instead of hard-stopping.

        max_speed, accel_time_ms, and decel_radius_px are per-fielder so the
        team naturally staggers — different sprinters, different read times,
        different settling distances.
        """
        if dt_ms <= 0 or elapsed_ms < fielder.reaction_delay_ms:
            return
        tx, ty = fielder.target
        dx = tx - fielder.pos[0]
        dy = ty - fielder.pos[1]
        dist = math.hypot(dx, dy)
        if dist < 0.5:
            return

        since_reaction = elapsed_ms - fielder.reaction_delay_ms
        accel_factor = min(1.0, since_reaction / fielder.accel_time_ms)

        if dist < fielder.decel_radius_px:
            decel_factor = max(FIELDER_DECEL_FLOOR, dist / fielder.decel_radius_px)
        else:
            decel_factor = 1.0

        step = fielder.max_speed * accel_factor * decel_factor * dt_ms
        if dist <= step:
            fielder.pos[0] = tx
            fielder.pos[1] = ty
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
        self._ball_decel = ROLLING_DECEL_PX_MS2

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

        if self.outcome == "GROUNDOUT":
            self._update_groundout(self._elapsed)
        elif self.outcome == "FLYOUT":
            self._update_flyout(self._elapsed)
        else:
            self._update_hit(self._elapsed)

        # Hits (SINGLE/DOUBLE/TRIPLE) wait for the primary to reach the ball,
        # however long that takes — friction guarantees the ball stops and
        # the fielder converges on it, so there's no need for a timeout.
        # FLYOUT/GROUNDOUT/HOME RUN finish at the scripted duration as before.
        if self._elapsed >= self.duration_ms:
            if self._needs_secure:
                if self._secured:
                    self.finished = True
            else:
                self.finished = True

    def _update_groundout(self, elapsed):
        if elapsed <= self._t_ball_arrive:
            t = elapsed / self._t_ball_arrive
            self._ball = _arc_grounder(HOME, self._fielder_at, self._grounder_peaks, t)
            self._ball_shadow = _lerp(HOME, self._fielder_at, t)
        elif elapsed <= self._t_throw_start:
            self._ball = self._fielder_at
            self._ball_shadow = self._fielder_at
        elif elapsed <= self._t_throw_arrive:
            t = (elapsed - self._t_throw_start) / GROUNDOUT_THROW_MS
            self._ball = _arc_fly(self._fielder_at, self._first_base, THROW_PEAK_H, t)
            self._ball_shadow = _lerp(self._fielder_at, self._first_base, t)
        else:
            self._ball = self._first_base
            self._ball_shadow = self._first_base

    def _update_flyout(self, elapsed):
        ball_t = min(1.0, elapsed / self._t_ball_arrive)
        self._ball = _arc_fly(HOME, self._fielder_target, self._flyout_peak, ball_t)
        self._ball_shadow = _lerp(HOME, self._fielder_target, ball_t)

        # Primary runs into the catch with cosine ease-in/out, arriving on the
        # ball. Override pos directly so we get exactly-on-ball arrival
        # regardless of the constant-velocity stepper. Reaction delay holds
        # the fielder in place for the first 200–380 ms (see-react-step) —
        # without it, every fielder starts running the instant the ball is
        # struck, which reads as superhuman.
        primary = self.fielders[self._primary_role]
        delay = primary.reaction_delay_ms
        move_window = max(1.0, self._t_ball_arrive - delay)
        move_t = max(0.0, min(1.0, (elapsed - delay) / move_window))
        eased = 0.5 - 0.5 * math.cos(math.pi * move_t)
        cx, cy = _lerp(self._primary_start, self._primary_stop, eased)
        primary.pos[0] = cx
        primary.pos[1] = cy

    def _update_hit(self, elapsed):
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
            primary.target = self._hit_end
        elif self._needs_secure and not self._secured:
            primary.target = self._ball
            # Pacing was for the in-flight phase only — once the ball is on
            # the ground the fielder sprints to chase it down.
            primary.max_speed = self._primary_full_speed
            primary.decel_radius_px = SECURE_RADIUS_PX
            # Any fielder near the ball can secure it — the ball sometimes
            # rolls past the assigned primary toward a different defender,
            # and that defender (already chasing via _update_lean_targets'
            # active-chase branch) makes the play. Closest fielder to the
            # ball wins the race; pin the play to whoever it was so the
            # post-secure rendering shows the right glove.
            closest_role = None
            closest_dist = float('inf')
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
                # For the generic HIT outcome, classify SINGLE / DOUBLE /
                # TRIPLE from how long the fielder took. Balls that reached
                # the wall override the SINGLE branch entirely — by physical
                # definition the ball got past every OF, so it has to be at
                # minimum a double regardless of how the carom returns.
                if self.outcome == "HIT" and self.classified_outcome is None:
                    retrieve_ms = self._secured_at_ms - self.duration_ms
                    if self._wall_hit:
                        # In-flight wall hits use a much lower triple
                        # threshold than rolling wall hits because retrieve
                        # time is measured from the moment of impact (no
                        # rolling phase eating clock first).
                        if self._is_wall_candidate:
                            triple_threshold = RETRIEVE_TIME_INFLIGHT_WALL_TRIPLE_MS
                        else:
                            triple_threshold = RETRIEVE_TIME_WALL_TRIPLE_MS
                        if retrieve_ms >= triple_threshold:
                            self.classified_outcome = "TRIPLE"
                        else:
                            self.classified_outcome = "DOUBLE"
                    elif retrieve_ms < RETRIEVE_TIME_SINGLE_MAX_MS:
                        self.classified_outcome = "SINGLE"
                    elif retrieve_ms < RETRIEVE_TIME_DOUBLE_MAX_MS:
                        self.classified_outcome = "DOUBLE"
                    else:
                        self.classified_outcome = "TRIPLE"

    # ---- Draw -----------------------------------------------------------

    def draw(self, screen):
        self._draw_field(screen)

        # Fielders first so the ball renders on top (sells "ball in glove").
        for fielder in self.fielders.values():
            self._draw_fielder(screen, fielder, self._ball)

        sx, sy = int(self._ball_shadow[0]), int(self._ball_shadow[1])
        pygame.draw.ellipse(screen, (60, 60, 60), pygame.Rect(sx - 5, sy - 2, 10, 4))

        bx, by = int(self._ball[0]), int(self._ball[1])
        pygame.draw.circle(screen, (255, 255, 255), (bx, by), 5)

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
        # left a gap between the foul lines and the wall.)
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

        # Wall face — filled band so the wall reads as a 3D structure.
        face_poly = wall_top_pts + list(reversed(wall_bot_pts))
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
