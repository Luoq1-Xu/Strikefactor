"""What a batted ball does after it first touches the ground.

The fourth of the pure batted-ball modules, alongside `ball_flight`,
`infield_timing` and `extra_bases`: real feet and seconds, no pygame, no
game state, no animation objects. `ball_flight` ends the moment the ball
reaches the grass; this module owns everything from that instant until
the ball comes to rest.

It exists because the animation had no landing model at all. The ball's
post-landing speed was `average flight speed x SHAPE_LAND_FACTOR`, with
the factor set to 0.35 on a fly ball — so a ball whose shadow had been
crossing the screen at 78 ft/s dropped to 27 ft/s in a single frame, took
three cosmetic hops on a fixed 620 ms schedule while rolling friction ran
the whole time it was supposedly airborne, and had ~10 ft/s left by the
time it was actually on the ground. Measured over 500 fly balls, the ball
travelled a median of 14 ft after landing and was secured 0.32 s later.
Real fly balls do not stop; they take a big first hop and keep going, and
what ends the play is an outfielder, not friction.

Three corrections, in order of how much they were worth:

1.  **The ball lands at the speed it lands at.** Every batted ball
    arrives at the grass near terminal velocity — integrating a drag
    trajectory (Cd 0.35, modest lift) over the whole Statcast launch
    grid puts landing speed between 54 and 59 mph for everything from an
    80 mph liner to a 110 mph fly, which is why `LANDING_SPEED_FRACTION`
    can be one number per shape rather than a function of exit velocity.
    What differs between shapes is the *angle* it arrives at, and that
    is what decides the bounce.

2.  **The bounce is an impulse problem, not a decay constant.** A ball
    landing shallow skids and keeps most of its speed; one landing steep
    is gripped by the grass and converted into topspin. Both fall out of
    the same rigid-sphere calculation (`_impact_impulse`), so the liner
    that skips into the gap and the fly ball that checks up in front of
    the centre fielder are the same model at two incidence angles. The
    old per-bounce `BOUNCE_HORIZONTAL_RETENTION = 0.96` could not
    express the difference, and the *first* bounce is where nearly all
    the horizontal loss happens.

3.  **A ball in the air is not subject to rolling friction.** The hops
    are real projectile arcs now, with heights and durations derived
    from the rebound speed rather than a 620 ms schedule with a
    presentation-clock unit on it.

The remaining calibration dial is `GRASS_ROLL_DECEL_FT_S2`, for the same
reason `infield_timing` calibrates on release time: it is the input whose
real-world value is genuinely uncertain (published rolling-resistance
figures for a ball on cut grass span 0.1-0.25 g), so absorbing error
there does not distort a better-measured number.
"""

import math
from dataclasses import dataclass

from strikefactor.gameplay import infield_timing

G_FT_S2 = 32.174
MPH_TO_FTS = 5280.0 / 3600.0

# Ceiling on the landing speed as a fraction of the flight's own average
# speed — see `landing_speed_fts`. Just under 1 rather than at it because
# even the weakest fly ball loses a little to drag on the way down.
LANDING_SPEED_MAX_FRACTION = 0.95


# ---- Landing ---------------------------------------------------------------
# Landing kinematics, fitted to a drag integration (Cd 0.35, modest lift,
# 5.125 oz / 2.9 in) run across the Statcast launch grid at each shape's
# `ball_flight.LAUNCH_ANGLE_DEG`. Both are `(value at 60 mph exit velocity,
# change per mph)`, linear over the 60-110 mph span where batted balls
# live.
#
# Speed along the flight path at the moment the ball reaches the grass,
# mph. The striking result is how little of it there is: a line drive
# lands between 48 and 57 mph whether it was struck at 60 or at 110, and a
# fly between 46 and 59 over the same span. A batted ball is near terminal
# velocity by the time it comes down, so exit velocity buys distance and
# hang time and does not survive the trip as speed. That is what lets the
# landing speed be stated outright here rather than re-derived from a
# carry model that might disagree with it.
LANDING_SPEED_MPH = {
    "LINER":  (48.1, 0.178),
    "FLY":    (45.5, 0.274),
    "POP_UP": (49.4, 0.414),
}

# Angle below horizontal at which the ball reaches the grass, degrees.
# Steeper than the launch angle in every case, because drag costs the
# horizontal component far more than gravity gives back to the vertical.
#
# This is the term that does the work. Landing speed barely moves; landing
# *angle* ranges from 20 to 74 degrees, and the angle is what the bounce
# is a function of. A line drive arrives shallow and skips; a fly ball
# arrives near 50 degrees and is gripped by the grass.
#
# It steepens with exit velocity, which reads backwards until you notice
# that drag is what makes a trajectory asymmetric: the harder a ball is
# hit, the more of its horizontal speed is gone by the time it lands, so
# the descent is steeper. Hence the scorched line drive that checks up in
# front of the left fielder and the 70 mph one that skips past them.
DESCENT_ANGLE_DEG = {
    "LINER":  (19.6, 0.194),
    "FLY":    (40.9, 0.234),
    "POP_UP": (72.0, 0.054),
}

# Exit velocity the fits above are anchored at, and the span they were
# fitted over. Outside it they are clamped rather than extrapolated.
LANDING_FIT_REF_MPH = 60.0
LANDING_FIT_SPAN_MPH = (45.0, 115.0)

# Backspin at landing, expressed as the surface speed of the contact
# point (omega x radius, ft/s) — the form the impulse calculation wants.
# A batted ball leaves the bat at 1500-3000 rpm and sheds some of it in
# flight; 2000 rpm on a 2.9 in ball is ~25 ft/s of surface speed. Backspin
# adds directly to how fast the bottom of the ball is sliding forward, so
# it is the reason a fly ball checks up on the first hop instead of
# skipping through.
BACKSPIN_SURFACE_FTS = {
    "LINER":  16.0,
    "FLY":    24.0,
    "POP_UP": 28.0,
}


# ---- The bounce ------------------------------------------------------------
# Vertical coefficient of restitution against natural grass over soil.
# Well below the ~0.55 a baseball shows against a rigid wall: the ground
# deforms, and most of the measured range for turf-over-soil is 0.25-0.40.
# This is what sizes the first hop — 0.32 against a fly ball's ~64 ft/s
# descent gives a 6.5 ft hop lasting 1.3 s, which is the over-the-infield
# hop you see on a ball that lands in front of an outfielder.
TURF_NORMAL_COR = 0.32

# Sliding friction between ball and grass during the impact. Sets the
# ceiling on how much horizontal speed one bounce can take: the tangential
# impulse available is mu * (1 + cor) * v_descent.
TURF_FRICTION_MU = 0.45

# Floor on the horizontal loss at an impact, as a fraction of current
# speed. The rigid-sphere model says a ball that is already rolling loses
# nothing tangentially on the next bounce, which is right for a rigid
# sphere and wrong for a leather ball landing on soil — some speed always
# goes into deforming the turf. Small, because after the first bounce
# there is genuinely not much left to take.
IMPACT_MIN_LOSS_FRACTION = 0.06

# A hop that would rebound lower than this is not a hop; the ball is
# rolling. Three inches — about the height of the seams' worth of skip you
# stop being able to see.
MIN_HOP_HEIGHT_FT = 0.25

# Hard cap on the generated hop count. The geometric decay in
# TURF_NORMAL_COR reaches MIN_HOP_HEIGHT_FT in 2-4 hops from any real
# landing speed; this only exists so a pathological input cannot build an
# unbounded list.
MAX_HOPS = 8


# ---- The roll --------------------------------------------------------------
# Rolling resistance on outfield grass, ft/s^2, and speed-independent by
# definition — this is the surface term. Published rolling-resistance
# coefficients for a ball on cut grass run 0.1-0.25 g (3-8 ft/s^2); 6 is
# mid-band and consistent with the one everyday observation that pins it,
# a bunt laid down at ~20 ft/s dying 50-60 ft up the line.
#
# It was `ROLLING_DECEL_FT_S2 = 16.0` in hit_animation — twice the high end
# of the real range — and it had to be, because the ball was being handed
# to it at a third of its real speed and something still had to stop it in
# a plausible distance. Fixing the landing speed is what let this come
# back to a real number. Before that it was `ROLLING_DECEL_PX_MS2`, px per
# *animated* ms^2, which made stopping distance a function of presentation
# pacing.
GRASS_ROLL_DECEL_FT_S2 = 6.0

# Aerodynamic drag on the rolling ball, as the coefficient k in
# `a = grass + k * v^2`. Not a tuning knob: it is Cd * rho * A / 2m for a
# baseball (Cd 0.35, 2.9 in diameter, 5.125 oz), which works out at
# 1.9e-3 per foot.
#
# Worth having because it is not small where it matters. A ball leaving
# its last hop at 46 ft/s is fighting 4.1 ft/s^2 of air on top of 6 ft/s^2
# of grass, so drag is 40% of what stops it — and since it falls off as
# v^2 it shortens the long rolls without touching the short ones, which is
# exactly the shape of correction the far tail needs. Modelling the grass
# alone and raising its coefficient to compensate would have bought the
# same mean at the cost of over-braking every slow roller.
ROLL_AIR_DRAG_PER_FT = 1.9e-3

# Below this the ball is at rest. A hair above zero so the integrator has
# a definite stopping point rather than an asymptote.
STOPPED_SPEED_FTS = 0.5


@dataclass(frozen=True)
class Hop:
    """One airborne arc between two ground contacts.

    `retention` is the fraction of horizontal speed that survives the
    impact *starting* this hop, so the caller applies it at the hop
    boundary and then leaves the ball alone until the next one — a ball in
    the air has no rolling friction acting on it.
    """
    retention: float
    duration_s: float
    height_ft: float


@dataclass(frozen=True)
class GroundPath:
    """The whole post-landing story for one batted ball."""
    speed_fts: float          # horizontal speed the instant it lands
    hops: tuple               # tuple[Hop, ...], in order
    final_retention: float    # the contact that ends the hopping
    grass_decel_ft_s2: float

    @property
    def hop_time_s(self):
        return sum(h.duration_s for h in self.hops)

    @property
    def roll_speed_fts(self):
        speed = self.speed_fts
        for hop in self.hops:
            speed *= hop.retention
        return speed * self.final_retention

    @property
    def roll_distance_ft(self):
        return roll_distance_ft(self.roll_speed_fts, self.grass_decel_ft_s2)

    @property
    def total_distance_ft(self):
        """How far past the landing point the ball ends up, unmolested."""
        return remaining_distance_ft(self, self.speed_fts, 0)

    @property
    def total_time_s(self):
        """Landing to rest, unmolested — the window the defense has to run
        the ball down before it is a question of the wall instead."""
        return self.hop_time_s + roll_time_s(self.roll_speed_fts,
                                             self.grass_decel_ft_s2)


def _fit(table, shape, ev_mph):
    base, slope = table.get(shape, table["FLY"])
    lo, hi = LANDING_FIT_SPAN_MPH
    ev = max(lo, min(hi, ev_mph if ev_mph else lo))
    return base + slope * (ev - LANDING_FIT_REF_MPH)


def descent_angle_deg(shape, ev_mph):
    """Angle below horizontal the ball reaches the grass at, degrees."""
    return _fit(DESCENT_ANGLE_DEG, shape, ev_mph)


def landing_speed_fts(shape, ev_mph, distance_ft=None, flight_time_s=None):
    """Horizontal speed at the moment the ball reaches the grass, ft/s.

    The near-terminal landing speed resolved onto the horizontal by the
    descent angle: 66-73 ft/s for a line drive, 50-54 for a fly ball,
    21-26 for a pop-up, against 66-75 / 50-54 / 22-26 from the drag
    integration this is fitted to.

    Given the flight it also caps at just under the flight's own average
    speed, which is what makes weak contact behave. Horizontal speed
    decays monotonically under drag, so a ball cannot land faster than it
    averaged; a bloop that only ever travelled at 45 ft/s has to land
    under that, and without the cap the terminal figure would have it
    speed up on touching the grass. The flight passed in is the one the
    animation actually flew, so the ball that lands is the ball that was
    in the air — the same contract `ball_flight.ground_time_s` keeps with
    `infield_timing`.
    """
    speed = _fit(LANDING_SPEED_MPH, shape, ev_mph) * MPH_TO_FTS
    horizontal = speed * math.cos(math.radians(descent_angle_deg(shape, ev_mph)))
    if not flight_time_s or distance_ft is None:
        return horizontal
    average = max(0.0, distance_ft) / flight_time_s
    return min(horizontal, LANDING_SPEED_MAX_FRACTION * average)


def grounder_landing_fraction(ev_mph):
    """End-of-bouncing speed for a GROUNDER, as a fraction of its average.

    A ground ball never has a landing transition — it has been in contact
    with the grass the whole way, and `infield_timing`'s retention curve
    already describes its *average* speed over that path. What the roll
    needs is the speed at the far end, which for a roughly uniform
    deceleration from v0 to v_end averaging `r * v0` is `(2r - 1) * v0`,
    i.e. `(2r - 1) / r` of the average.

    So it is derived from the same curve the infield verdict is computed
    against rather than being a free constant: a scorched grounder
    (r = 0.75) still carries two thirds of its average speed when it
    reaches the outfield grass, and a topped roller (r = 0.48) has
    already stopped, which is exactly the play it is.
    """
    r = infield_timing.ground_speed_retention(ev_mph)
    if r <= 0:
        return 0.0
    return max(0.0, min(1.0, (2.0 * r - 1.0) / r))


def _impact_impulse(speed_fts, descent_fts, spin_surface_fts):
    """Tangential impulse per unit mass taken by one ground contact, ft/s.

    The bottom of the ball is sliding forward at `speed + spin_surface`
    (backspin adds to the slip, which is why a backspun fly checks up).
    Friction acts backward on that slip until either it is gone — the ball
    grips and rolls, which for a sphere costs 2/7 of the slip — or the
    impact ends, which caps the impulse at `mu * (1 + cor) * v_descent`.

    Whichever comes first is the answer, and the two limits are what make
    one formula cover both the skidding line drive and the gripping fly
    ball.
    """
    slip = speed_fts + spin_surface_fts
    if slip <= 0:
        grip = 0.0
    else:
        grip = (2.0 / 7.0) * slip
    available = TURF_FRICTION_MU * (1.0 + TURF_NORMAL_COR) * max(0.0, descent_fts)
    impulse = min(grip, available)
    # Turf deformation, which the rigid-sphere model has no term for.
    return max(impulse, IMPACT_MIN_LOSS_FRACTION * max(0.0, speed_fts))


def ground_path(shape, speed_fts, ev_mph=None, descent_deg=None,
                spin_surface_fts=None,
                grass_decel_ft_s2=GRASS_ROLL_DECEL_FT_S2):
    """Bounce schedule and rolling speed for a ball landing at `speed_fts`.

    Each contact is resolved by `_impact_impulse`; the rebound is
    `TURF_NORMAL_COR` of the descent speed, and the hop it produces is an
    ordinary projectile arc, so height and duration are two consequences
    of one rebound rather than two independent schedules. Hops stop when
    the rebound no longer clears `MIN_HOP_HEIGHT_FT`.

    Pass `descent_deg = 0` for a ball that is already on the ground (a
    GROUNDER that has finished its modelled bouncing): with no vertical
    component there is no rebound, so it goes straight to the roll.
    """
    speed = max(0.0, speed_fts)
    if descent_deg is None:
        descent_deg = descent_angle_deg(shape, ev_mph)
    if spin_surface_fts is None:
        spin_surface_fts = BACKSPIN_SURFACE_FTS.get(
            shape, BACKSPIN_SURFACE_FTS["FLY"])

    descent = speed * math.tan(math.radians(max(0.0, min(89.0, descent_deg))))
    spin = spin_surface_fts
    hops = []
    for _ in range(MAX_HOPS):
        rebound = TURF_NORMAL_COR * descent
        height = rebound * rebound / (2.0 * G_FT_S2)
        if height < MIN_HOP_HEIGHT_FT or speed <= STOPPED_SPEED_FTS:
            break
        impulse = _impact_impulse(speed, descent, spin)
        impulse = min(impulse, speed)
        new_speed = speed - impulse
        # Friction converts slip into topspin at 5/2 the rate it removes
        # forward speed; once the two meet the ball is rolling and the
        # next contact has nothing left to take.
        spin = max(-new_speed, spin - 2.5 * impulse)
        hops.append(Hop(retention=(new_speed / speed) if speed > 0 else 1.0,
                        duration_s=2.0 * rebound / G_FT_S2,
                        height_ft=height))
        speed = new_speed
        descent = rebound

    # The contact that ends the hopping still costs the ball something.
    final_retention = 1.0
    if hops and speed > 0:
        final_impulse = min(_impact_impulse(speed, descent, spin), speed)
        final_retention = (speed - final_impulse) / speed

    return GroundPath(speed_fts=max(0.0, speed_fts), hops=tuple(hops),
                      final_retention=final_retention,
                      grass_decel_ft_s2=grass_decel_ft_s2)


def roll_decel_ft_s2(speed_fts, grass_ft_s2=GRASS_ROLL_DECEL_FT_S2):
    """Total deceleration of a ball rolling at `speed_fts`: grass plus air."""
    return grass_ft_s2 + ROLL_AIR_DRAG_PER_FT * speed_fts * speed_fts


def roll_distance_ft(speed_fts, grass_ft_s2=GRASS_ROLL_DECEL_FT_S2):
    """How far a ball rolling at `speed_fts` travels before it stops.

    Closed form of `dv/dx = -(a + k v^2) / v`, which integrates to
    `ln(1 + k v^2 / a) / 2k`. Reduces to the familiar `v^2 / 2a` as k
    goes to zero.
    """
    if speed_fts <= STOPPED_SPEED_FTS or grass_ft_s2 <= 0:
        return 0.0
    k = ROLL_AIR_DRAG_PER_FT
    if k <= 0:
        return speed_fts * speed_fts / (2.0 * grass_ft_s2)
    return math.log1p(k * speed_fts * speed_fts / grass_ft_s2) / (2.0 * k)


def roll_time_s(speed_fts, grass_ft_s2=GRASS_ROLL_DECEL_FT_S2):
    """Seconds a ball rolling at `speed_fts` takes to come to rest."""
    if speed_fts <= STOPPED_SPEED_FTS or grass_ft_s2 <= 0:
        return 0.0
    k = ROLL_AIR_DRAG_PER_FT
    if k <= 0:
        return speed_fts / grass_ft_s2
    w = math.sqrt(grass_ft_s2 * k)
    return math.atan(speed_fts * math.sqrt(k / grass_ft_s2)) / w


def trajectory(path, step_s=0.15):
    """The roll sampled as `(seconds since landing, feet travelled)`.

    Enough to answer "where will the ball be when I get there", which is
    the question a fielder chasing a ball into the gap is actually asking.
    Straight-line: the bearing is the caller's business, and only the wall
    can change it.
    """
    samples = []
    speed = path.speed_fts
    t = 0.0
    dist = 0.0
    for hop in path.hops:
        speed *= hop.retention
        n = max(1, int(math.ceil(hop.duration_s / step_s)))
        for _ in range(n):
            dt = hop.duration_s / n
            t += dt
            dist += speed * dt
            samples.append((t, dist))
    speed *= path.final_retention if path.hops else 1.0
    remaining = roll_time_s(speed, path.grass_decel_ft_s2)
    n = max(0, int(math.ceil(remaining / step_s)))
    for _ in range(n):
        t += step_s
        speed = max(0.0, speed - roll_decel_ft_s2(
            speed, path.grass_decel_ft_s2) * step_s)
        dist += speed * step_s
        samples.append((t, dist))
    return samples


def remaining_distance_ft(path, speed_fts, hops_completed):
    """Distance still to travel for a ball moving at `speed_fts` that has
    already finished `hops_completed` of `path`'s hops.

    Used to aim the chasing fielder at where the ball is going to stop
    rather than at where it currently is. It has to know about the hops,
    because a ball two feet off the ground is not decelerating and the
    naive v^2/2a underestimates it by most of its remaining travel.
    """
    speed = max(0.0, speed_fts)
    dist = 0.0
    remaining = path.hops[hops_completed:]
    for hop in remaining:
        speed *= hop.retention
        dist += speed * hop.duration_s
    if remaining:
        speed *= path.final_retention
    return dist + roll_distance_ft(speed, path.grass_decel_ft_s2)
