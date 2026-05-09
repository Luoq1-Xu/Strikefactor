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


HOME = (640, 620)

# Field scale — picked so a real 400 ft CF wall fits on a 720-tall screen with
# home plate near the bottom. At 1.4 px/ft, infield bases (90 ft) come out
# slightly compressed compared to a real-scale infield, but the proportions
# (wall vs. bases vs. fielder depth) match real MLB averages, which is what
# makes the field feel right under a top-down camera.
FT_TO_PX = 1.4

# Bases — 90 ft path. 1B and 3B sit on the foul lines (45°), so |dx| == dy.
BASE_DIST = 89   # per-axis offset from home; 89·√2 ≈ 126 px ≈ 90 ft
MOUND_DIST = 85  # 60.5 ft from home plate, straight out toward CF

BASES = {
    "1B": (HOME[0] + BASE_DIST, HOME[1] - BASE_DIST),
    "2B": (HOME[0],             HOME[1] - 2 * BASE_DIST),
    "3B": (HOME[0] - BASE_DIST, HOME[1] - BASE_DIST),
}
PITCHERS_MOUND = (HOME[0], HOME[1] - MOUND_DIST)

# Default standing positions for all 9 defenders (top-down). Distances tuned
# to typical MLB positioning: corner IFs ~95 ft, middle IFs ~145 ft, corner
# OFs ~290 ft, CF ~310 ft.
FIELDER_HOMES = {
    "P":  PITCHERS_MOUND,
    "C":  (HOME[0],         HOME[1] + 30),        # behind plate (foul territory, OK)
    "1B": (HOME[0] +  85,   HOME[1] - 100),       # ~95 ft, off bag toward 2B
    "2B": (HOME[0] +  70,   HOME[1] - 190),       # ~145 ft, between 1B and 2B
    "SS": (HOME[0] -  70,   HOME[1] - 190),       # ~145 ft, between 2B and 3B
    "3B": (HOME[0] -  85,   HOME[1] - 100),       # ~95 ft, off bag toward home
    "LF": (HOME[0] - 152,   HOME[1] - 376),       # ~290 ft
    "CF": (HOME[0],         HOME[1] - 434),       # ~310 ft (deepest)
    "RF": (HOME[0] + 152,   HOME[1] - 376),       # ~290 ft
}
ROLES = list(FIELDER_HOMES.keys())
INFIELD_ROLES = ["1B", "2B", "SS", "3B"]
OUTFIELD_ROLES = ["LF", "CF", "RF"]
# Groundout primary candidates — 1B excluded so we keep the throw-to-first beat.
GROUNDOUT_PRIMARY_ROLES = ["SS", "2B", "3B"]

# Outfield wall — elliptical, not circular. Real MLB walls are deeper in CF
# (~400 ft) than along the foul lines (~330 ft); a single radius makes the
# outfield feel cramped at center and too long down the lines. The polar
# wall radius at angle θ (from +x axis) is then
#   r(θ) = a·b / √((b·cosθ)² + (a·sinθ)²)
# which evaluates to ~330 ft along the foul lines and 400 ft straight out.
WALL_SEMI_X = 402   # gives ~330 ft along the 45° foul-line direction
WALL_SEMI_Y = 560   # CF wall at ~400 ft

# Foul lines drawn out to where they meet the wall (along the 45° direction).
FOUL_LINE_LENGTH = 327

# Phase timings (ms). Lengthened for more cinematic pacing — fast translation
# of small circles read as "gliding"; slower timings give the eye time to
# track the ball and the fielders' run-ups.
GROUNDOUT_TRAVEL_MS    = 1700
GROUNDOUT_FIELD_HOLD   =  350
GROUNDOUT_THROW_MS     =  850
GROUNDOUT_CATCH_HOLD   =  450

FLYOUT_TRAVEL_MS       = 4000
FLYOUT_CATCH_HOLD      =  500

# In-air time per outcome (FLY shape default). Calibrated against MLB hang
# times: routine fly to OF ~3–4 sec, HRs 4.5–6 sec. Singles run shorter
# because most are liners or grounders, not full flies. Triples and HRs are
# longest — they have to carry to (or past) the wall.
HIT_DURATIONS = {
    "SINGLE":   2500,
    "DOUBLE":   3300,
    "TRIPLE":   4000,
    "HOME RUN": 5000,
}
# Standard fly-arc peak per outcome.
HIT_PEAK_H = {
    "SINGLE":    50,
    "DOUBLE":    80,
    "TRIPLE":   110,
    "HOME RUN": 200,
}
# Per-outcome landing distance from home (ft). These are the source of truth
# for where the ball lands (not where it ends up — see HIT_ROLL for friction).
# Lateral angle is sampled separately per outcome (see _pick_hit_landing) so
# we can model real hit patterns:
#   SINGLE — LINER/FLY shapes drop in front of OFs (180–250 ft); GROUNDER
#            shapes use GROUNDER_SINGLE_LANDING and land within the IF, then
#            roll out past it.
#   DOUBLE — gaps between OFs, or hard-hit balls down the line.
#   TRIPLE — deepest hits, carry to the wall in deep gaps or down the line.
HIT_DIST_FT = {
    "SINGLE": (180, 250),
    "DOUBLE": (260, 330),
    "TRIPLE": (310, 365),
}
# Pop-up landing — shallow, regardless of underlying outcome (px depth).
POPUP_LANDING = {"depth": (150, 220), "lateral_frac": 0.5}

# Hard grounder single — lands inside the IF (between/just past the IFs)
# and rolls out into the OF for the OF to retrieve. Models the real-life
# pattern where a sharp grounder up the middle or in the hole becomes a
# single by passing the IFs, not by being dropped past them.
GROUNDER_SINGLE_LANDING = {"depth_ft": (130, 185), "lateral_frac": 0.55}

# Post-landing ball physics for SINGLE / DOUBLE / TRIPLE. After landing
# the ball integrates with linear friction v(τ) = v0 − a·τ. v0 is sampled
# off the in-flight arc just before landing (finite difference), so the
# transition has no perceptible pause. Friction is tuned much lower than
# pure grass-rolling friction (~3 ft/s²) for game pacing, but low enough
# that the ball clearly continues to roll for ~2–4 seconds after the
# bounces stop — the fielder has to chase, which is what makes hits read
# like real plays. Tighter values made balls die inside the bounce window.
HIT_ROLL = {
    "SINGLE": {"decel": 0.000022},
    "DOUBLE": {"decel": 0.000016},
    "TRIPLE": {"decel": 0.000012},
}

# Energy retained on impact, multiplied onto the sampled in-flight velocity.
# Liner skips through; grounder is already on the ground; fly drops nearly
# vertically and loses some horizontal carry; pop-up deadens hard. This is
# the only place shape affects post-landing speed — once the ball is on the
# ground, friction is a property of the grass, not the trajectory shape, so
# rolling decel is uniform across shapes (see HIT_ROLL).
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
# horizontal speed. Continuous friction (HIT_ROLL.decel) handles the slow
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
WALL_BOUNCE_RESTITUTION = 0.55

# Squibbler landing — weak grounder, very short travel (~70–125 ft).
SQUIBBLER_LANDING = {"depth": (100, 175), "lateral_frac": 0.5}

# Quality thresholds for grounder bounce profile (see _grounder_peaks).
SQUIBBLER_QUALITY_THRESHOLD = 0.32
SHARP_QUALITY_THRESHOLD     = 0.55

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

# HR distance scaling (ft). Quality-driven; below threshold pegs to min.
HR_DIST_MIN_FT = 365
HR_DIST_MAX_FT = 485
HR_QUALITY_THRESHOLD = 0.4

# Fielder motion. Constant-velocity with acceleration/deceleration phases —
# exponential easing produced a "snap to position then freeze" look that
# read as unnatural. Real fielders ramp up, cruise, and decelerate.
FIELDER_MAX_SPEED_PX_MS = 0.040         # ~28 ft/sec at 1.4 px/ft (MLB Statcast avg sprint speed)
FIELDER_ACCEL_TIME_MS   = 220.0         # ramp from 0 to max_speed
FIELDER_DECEL_RADIUS_PX = 28.0          # start slowing within this radius of target
FIELDER_DECEL_FLOOR     = 0.20          # never below 20% speed in decel zone
REACTION_DELAY_MIN_MS   = 120.0         # jittered per fielder so they don't all start in sync
REACTION_DELAY_MAX_MS   = 240.0
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
    """Variable-bounce arc; one bounce per entry in `peaks`. Most grounders
    use a single bounce; squibblers use 2-3 weak bounces.
    """
    t = max(0.0, min(1.0, t))
    x, y = _lerp(a, b, t)
    n = len(peaks)
    bounce_idx = min(n - 1, int(t * n))
    bounce_t = (t * n) % 1.0
    lift = peaks[bounce_idx] * math.sin(math.pi * bounce_t)
    return (x, y - lift)


def _grounder_peaks(quality):
    """Pick bounce profile from contact quality.

    Sharp grounders (good contact) take one solid hop and travel.
    Squibblers (low quality) bounce weakly multiple times.
    """
    if quality < SQUIBBLER_QUALITY_THRESHOLD:
        return (16, 11, 7)        # squibbler: 3 weak bounces
    if quality < SHARP_QUALITY_THRESHOLD:
        return (24, 13)           # medium: 2 bounces
    return (32,)                  # sharp: 1 solid bounce


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
    """(x, y) in pygame coords for a polar (angle, dist) sampled from home.
    `angle` is the standard math angle (radians) measured from +x axis CCW;
    90° points straight out toward CF.
    """
    return (HOME[0] + dist_px * math.cos(angle),
            HOME[1] - dist_px * math.sin(angle))


def _pick_hit_landing(outcome, shape, quality=1.0):
    """Pick a landing point that matches the real-life pattern of each hit
    type. Singles drop in front of the OFs (or sneak through the IF) so the
    OF charges forward; doubles split the gaps or roll down the line;
    triples carry to (or near) the wall in deep gaps or down the corner;
    HRs land past the elliptical wall, biased toward the pull/center area.

    POP_UPs and squibblers override outcome-specific depth — they're shape-
    driven (pop-up = shallow infield fly; squibbler = weak grounder) and
    behave the same regardless of which SINGLE outcome generated them.

    GROUNDER singles also override depth: real grounder singles land inside
    the IF and roll past the IFs into the OF, rather than dropping in past
    them. The post-landing roll (HIT_ROLL.decel) carries the ball out.
    """
    # Shape overrides — POP_UP and squibblers ignore outcome distance.
    if shape == "POP_UP":
        spec = POPUP_LANDING
        depth = random.uniform(*spec["depth"])
        lat = random.uniform(-1, 1) * depth * spec["lateral_frac"]
        return _clamp_inside_wall((HOME[0] + lat, HOME[1] - depth),
                                  LANDING_WALL_MARGIN_PX)
    if (shape == "GROUNDER" and outcome == "SINGLE"
            and quality < SQUIBBLER_QUALITY_THRESHOLD):
        spec = SQUIBBLER_LANDING
        depth = random.uniform(*spec["depth"])
        lat = random.uniform(-1, 1) * depth * spec["lateral_frac"]
        return _clamp_inside_wall((HOME[0] + lat, HOME[1] - depth),
                                  LANDING_WALL_MARGIN_PX)
    # Hard grounder single — lands within / just past the IF, rolls out
    # to where the OF picks it up. Squibbler case caught above.
    if shape == "GROUNDER" and outcome == "SINGLE":
        spec = GROUNDER_SINGLE_LANDING
        depth = random.uniform(*spec["depth_ft"]) * FT_TO_PX
        lat = random.uniform(-1, 1) * depth * spec["lateral_frac"]
        return _clamp_inside_wall((HOME[0] + lat, HOME[1] - depth),
                                  LANDING_WALL_MARGIN_PX)

    if outcome == "HOME RUN":
        # HRs land past the wall. Direction biased toward the pull/center
        # area (most HRs aren't down-the-line shots); how far past the wall
        # scales with quality (better contact = deeper carry).
        angle = random.gauss(math.radians(90), math.radians(22))
        angle = max(math.radians(50), min(math.radians(130), angle))
        wall_r = _wall_r_at(angle)
        q = max(0.0, min(1.0, quality))
        carry_px = random.uniform(15, 45) + q * 55
        return _polar_point(angle, wall_r + carry_px)

    if outcome == "SINGLE":
        # In front of the OFs — short distance from home (130–225 ft) keeps
        # the ball from clearing where corner OFs play (~290 ft) even after
        # the post-landing roll. Angle uniform across fair territory, with
        # a slight pull toward the lines for variety.
        dist_ft = random.uniform(*HIT_DIST_FT["SINGLE"])
        angle = random.uniform(math.radians(48), math.radians(132))
        return _polar_point(angle, dist_ft * FT_TO_PX)

    if outcome == "DOUBLE":
        # 30% down-the-line, 70% in the gap. Gap angles are the BISECTORS
        # between adjacent OFs — LF (112°) and CF (90°) → 101°; CF (90°) and
        # RF (68°) → 79°. Spread is kept under 6° so the ball doesn't drift
        # back onto an OF's standing position (which is what made every gap
        # double previously land underneath the corner OF).
        dist_ft = random.uniform(*HIT_DIST_FT["DOUBLE"])
        if random.random() < 0.30:
            side = random.choice((-1, 1))
            base = math.radians(50) if side > 0 else math.radians(130)
            angle = base + random.uniform(0, 0.08) * side
        else:
            side = random.choice((-1, 1))
            gap = math.radians(79) if side > 0 else math.radians(101)
            angle = gap + random.uniform(-0.10, 0.10)
        point = _polar_point(angle, dist_ft * FT_TO_PX)
        return _clamp_inside_wall(point, LANDING_WALL_MARGIN_PX)

    if outcome == "TRIPLE":
        # Triples carry deeper — ~45% down-the-line, ~55% deep gap. Almost
        # never up the middle (CF can usually catch up to those). Gap angles
        # match the OF bisectors (79° / 101°), same reasoning as DOUBLE.
        dist_ft = random.uniform(*HIT_DIST_FT["TRIPLE"])
        side = random.choice((-1, 1))
        if random.random() < 0.45:
            base = math.radians(48) if side > 0 else math.radians(132)
            angle = base + random.uniform(0, 0.06) * side
        else:
            gap = math.radians(79) if side > 0 else math.radians(101)
            angle = gap + random.uniform(-0.10, 0.10)
        point = _polar_point(angle, dist_ft * FT_TO_PX)
        return _clamp_inside_wall(point, LANDING_WALL_MARGIN_PX)

    # Fallback — treat unknown outcomes as singles.
    dist_ft = random.uniform(*HIT_DIST_FT["SINGLE"])
    angle = random.uniform(math.radians(48), math.radians(132))
    return _polar_point(angle, dist_ft * FT_TO_PX)


def _pick_shape(outcome, vertical_offset):
    """Hybrid: outs are deterministic from vertical_offset; hits are weighted-random."""
    if outcome == "GROUNDOUT":
        return "GROUNDER"
    if outcome == "FLYOUT":
        # Bat way under the ball -> infield pop-up.
        return "POP_UP" if vertical_offset < -25 else "FLY"
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

    def __init__(self, game, outcome, on_complete, vertical_offset=0.0, quality=0.0):
        self.game = game
        self.outcome = outcome
        self.on_complete = on_complete
        self.vertical_offset = vertical_offset
        self.quality = quality

        self.start_time = None
        self.banner_fired = False
        self.finished = False
        self._elapsed = 0
        self._last_elapsed = 0

        # For SINGLE/DOUBLE/TRIPLE the ball lands on the ground and a fielder
        # has to run it down. Animation pauses when secured (within
        # SECURE_RADIUS_PX of the ball) instead of timing out at duration_ms.
        self._needs_secure = outcome in ("SINGLE", "DOUBLE", "TRIPLE")
        self._secured = False

        # Stateful ball-on-ground physics (SDT). Lazy-initialized at the
        # landing transition by _init_ball_on_ground.
        self._ball_pos = None
        self._ball_v = None
        self._ball_decel = 0.0

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

        # Trajectory shape (decoupled from outcome resolution).
        self.shape = _pick_shape(outcome, vertical_offset)

        # Per-frame ball state.
        self._ball = HOME
        self._ball_shadow = HOME

        # HR distance (None for non-HR).
        self.hr_distance_ft = None
        if outcome == "HOME RUN":
            q = max(HR_QUALITY_THRESHOLD, min(1.0, quality))
            t = (q - HR_QUALITY_THRESHOLD) / max(1e-6, 1.0 - HR_QUALITY_THRESHOLD)
            self.hr_distance_ft = round(
                HR_DIST_MIN_FT + t * (HR_DIST_MAX_FT - HR_DIST_MIN_FT)
            )

        # Outcome-specific setup + target assignment.
        if outcome == "GROUNDOUT":
            self._setup_groundout()
        elif outcome == "FLYOUT":
            self._setup_flyout()
        elif outcome in HIT_DURATIONS:
            self._setup_hit(outcome)
        else:
            self.outcome = "SINGLE"
            self._setup_hit("SINGLE")

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

        # Bounce profile — weak contact bounces multiple times.
        self._grounder_peaks = _grounder_peaks(self.quality)

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
        # FLY — caught by the closest outfielder.
        if self.shape == "POP_UP":
            base = self.fielders[random.choice(INFIELD_ROLES)].home_pos
            target = (base[0] + random.uniform(-25, 25),
                      base[1] + random.uniform(-15, 15))
            self._flyout_peak = random.uniform(*POPUP_PEAK_RANGE)
            pool = INFIELD_ROLES
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
        self._hit_end = _pick_hit_landing(outcome, self.shape, self.quality)

        # Peak chosen per shape (FLY uses outcome's standard peak).
        if self.shape == "FLY":
            self._hit_peak = HIT_PEAK_H[outcome]
        elif self.shape == "LINER":
            self._hit_peak = random.uniform(*LINER_PEAK_RANGE)
        elif self.shape == "POP_UP":
            self._hit_peak = random.uniform(*POPUP_PEAK_RANGE)
        else:  # GROUNDER — peaks vary with contact quality
            self._hit_peak = 0
            self._grounder_peaks = _grounder_peaks(self.quality)

        self.duration_ms = HIT_DURATIONS[outcome]

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
        # 203 px). Hard grounder singles get a dedicated override — they
        # land in the IF but roll out past it, and the OF (not the IF)
        # picks them up, so we route to the OF up front.
        is_grounder_single_through = (
            outcome == "SINGLE" and self.shape == "GROUNDER"
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

        # XBH: cutoff infielder shifts to relay between OF and 2B.
        if outcome in ("DOUBLE", "TRIPLE"):
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
        """Recompute lean targets each frame so non-primary fielders track the
        live ball position. Lean magnitude grows with play progress, so fielders
        keep moving (a step at a time) instead of snapping to one spot at t=0
        and freezing for the rest of the play.
        """
        progress = min(1.0, self._elapsed / max(1, self.duration_ms))
        max_lean = LEAN_BASE_PX + LEAN_GROWTH_PX * progress
        focus = self._ball
        for role, f in self.fielders.items():
            if role in self._lean_excluded:
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

        Velocity is sampled off the in-flight arc just before landing
        (finite difference at t≈0.97), then trimmed by SHAPE_LAND_FACTOR for
        impact energy loss. This is what kills the perceived 'pause' at the
        bounce: the ball arrives at the ground moving at its in-flight
        speed and continues at the same speed. Stash the in-flight peak so
        the post-landing bounce visualization scales with it.
        """
        self._ball_pos = [self._hit_end[0], self._hit_end[1]]
        self._ball_decel = HIT_ROLL[self.outcome]["decel"]

        t_sample = 0.97
        if self.shape == "GROUNDER":
            sample = _arc_grounder(HOME, self._hit_end,
                                   self._grounder_peaks, t_sample)
        elif self.shape == "LINER":
            sample = _arc_liner(HOME, self._hit_end, self._hit_peak, t_sample)
        else:
            sample = _arc_fly(HOME, self._hit_end, self._hit_peak, t_sample)
        dt = (1.0 - t_sample) * self.duration_ms
        factor = SHAPE_LAND_FACTOR.get(self.shape, 1.0)
        self._ball_v = [
            (self._hit_end[0] - sample[0]) / dt * factor,
            (self._hit_end[1] - sample[1]) / dt * factor,
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
                k = (1.0 + WALL_BOUNCE_RESTITUTION) * v_outward
                self._ball_v[0] -= k * nx_p
                self._ball_v[1] -= k * ny_p
            # Pull ball back inside: scale toward home along the radial line
            # in ellipse-normalized space (linear in pygame coords too).
            s = limit / ellipse_d
            self._ball_pos[0] = HOME[0] + dx * s
            self._ball_pos[1] = HOME[1] + dy_pyg * s

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
        # regardless of the constant-velocity stepper.
        eased = 0.5 - 0.5 * math.cos(math.pi * ball_t)
        primary = self.fielders[self._primary_role]
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
                t = elapsed / self.duration_ms
                eased = 0.5 - 0.5 * math.cos(math.pi * t)
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
            d = math.hypot(primary.pos[0] - self._ball[0],
                           primary.pos[1] - self._ball[1])
            if d < SECURE_RADIUS_PX:
                self._secured = True

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

        rect = body.get_rect(center=(int(self._hit_end[0]), int(self._hit_end[1]) - 28))
        screen.blit(shadow, rect.move(2, 2))
        screen.blit(body, rect)

    def _draw_field(self, screen):
        hx, hy = HOME

        # Foul lines (45°)
        line_color = (90, 90, 90)
        pygame.draw.line(screen, line_color, (hx, hy),
                         (hx - FOUL_LINE_LENGTH, hy - FOUL_LINE_LENGTH), 1)
        pygame.draw.line(screen, line_color, (hx, hy),
                         (hx + FOUL_LINE_LENGTH, hy - FOUL_LINE_LENGTH), 1)

        # Outfield wall — elliptical arc spanning the fair-territory cone.
        # pygame.draw.arc is parameterized by ellipse parametric angle (not
        # polar), so the foul-line intersection is at atan(a/b), not 45°.
        wall_rect = pygame.Rect(hx - WALL_SEMI_X, hy - WALL_SEMI_Y,
                                2 * WALL_SEMI_X, 2 * WALL_SEMI_Y)
        foul_t = math.atan2(WALL_SEMI_X, WALL_SEMI_Y)
        pygame.draw.arc(screen, (110, 110, 110), wall_rect,
                        foul_t, math.pi - foul_t, 2)

        # Infield diamond fill
        diamond = [HOME, BASES["1B"], BASES["2B"], BASES["3B"]]
        pygame.draw.polygon(screen, (80, 60, 45), diamond, 0)
        pygame.draw.polygon(screen, (130, 100, 70), diamond, 2)

        # Bases
        for bp in BASES.values():
            bx, by = int(bp[0]), int(bp[1])
            pygame.draw.rect(screen, (220, 220, 220),
                             pygame.Rect(bx - 5, by - 5, 10, 10))

        # Pitcher's mound
        pygame.draw.circle(screen, (80, 60, 45), PITCHERS_MOUND, 14)
        pygame.draw.circle(screen, (130, 100, 70), PITCHERS_MOUND, 14, 1)

        # Home plate
        pygame.draw.polygon(screen, (220, 220, 220), [
            (hx - 8, hy - 8), (hx + 8, hy - 8), (hx + 8, hy),
            (hx, hy + 6), (hx - 8, hy),
        ], 0)
