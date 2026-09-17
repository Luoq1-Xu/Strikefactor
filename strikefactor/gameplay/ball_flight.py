"""How long a batted ball takes to get where it is going, in real seconds.

The companion to `infield_timing`: that module races a throw against a
runner, this one supplies the first term of the defense's clock and the
window every fielder has to cover ground. Same contract as
`engine/contact_audio.py` — real feet and seconds, no pygame, no game
state, no animation objects.

This exists because the animation had no flight-time model at all. Flight
duration was `HIT_BASE_DURATION_MS * (1.2 - 0.4 * quality)`: a *presentation*
value keyed off contact quality, which made harder contact fly for a
shorter time. That is right for a grounder and backwards for a fly ball —
harder contact goes farther, and a ball hit farther hangs *longer*.
Measured over 900 fly balls, animated flight time fell from 3.7 s on a
150 ft bloop to 2.7 s on a 400 ft drive, so the deepest balls gave
outfielders the least time to run them down. Fly-ball BABIP came out .425
against an MLB .120, and those fly balls were the largest single source of
the doubles surplus.

**An airborne flight is a function of the launch angle and the exit velocity,
and of nothing else.** It uses the no-drag projectile identity

    R = v² sin(2θ) / g        T = 2 v sin(θ) / g     =>     T = sqrt(2 R tanθ / g)

which needs only the landing distance and the launch angle — the exit velocity
is already encoded in how far the ball went, so nothing has to be
double-counted. `DRAG_RANGE_ANCHORS` and `DRAG_HANG_ANCHORS` then correct for
the one thing the vacuum identity gets materially wrong: drag costs a real
batted ball more distance than it costs hang time, so a real ball hangs longer
than the vacuum solution for the distance it actually covered.

The angle used to be the *shape's band centre* rather than the ball's own
angle, which put a cliff at every band edge — see the long note above
`DRAG_HANG_ANCHORS`. The shape is still what this module classifies, and the
DB and the animation still speak it; it is simply no longer an input to how
far the ball goes.

A third table, `DRAG_APEX_ANCHORS`, gives the flight its *shape* — how high
it gets and where along the carry. It is what `height_at_distance_ft` is
built on, and that function is both the drawn arc and the fence predicate,
so it is the one place the picture and the home run are the same number.

Ground balls are not projectiles and do not use any of that. They take
their speed from `infield_timing`'s retention curve, which is the same
number the infield verdict is computed against — so the ball the viewer
watches reach the shortstop and the ball the model says reached the
shortstop are the same ball.
"""

import math
import random

from strikefactor.gameplay import infield_timing

G_FT_S2 = 32.174

# Per-shape launch angle. These are the centres of the Statcast bands the
# batted-ball classifier is built around: ground balls under 10°, line
# drives 10-25°, fly balls 25-50°, pop-ups above 50°.
LAUNCH_ANGLE_DEG = {
    "LINER":  14.0,
    "FLY":    32.0,
    "POP_UP": 68.0,
}


# --- Which way the ball left the bat, vertically ---------------------------
#
# The same argument `spray` makes for the horizontal: a cylinder's surface
# normal is radial to its own axis, so the ball leaves perpendicular to the
# bat. `bat_contact` already hands the normal over — `axis_point_ft` is the
# *nearest* point on the axis, so (ball - axis_point) is perpendicular to the
# bat by construction and `vertical_offset_ft` is that normal's rise.
#
# It replaced a weighted random roll over the four shapes in
# `hit_outcome_manager`, where the geometry only tilted a Gaussian weight and
# never fixed the sign. A bat 1.2 in *over* the ball drew a FLY 11% of the time
# and a LINER 30%, and over recorded play 14.8% of every bat-over-the-ball
# contact was classified airborne (and 29.2% of bat-under contacts came out
# grounders). The swing replay reports that offset to the player, so they were
# shown the contact and then handed a trajectory contradicting it.
#
# Two of that model's three tables were also unreachable, which is worth
# recording because the failure was silent. The largest offset at which a bat
# and a ball still touch is the sum of their radii, 1.30 + 1.45 = 2.75 in, and
# at the current `ft_per_px_z` that is 17.2 px — but the POP_UP offset anchor
# sat at 22 px = 3.5 in, naming a contact that cannot happen. Pop-ups therefore
# ran 1.0% of recorded play against MLB's 7%, winning only out of a Gaussian
# tail. (That table's comment claimed a reach of "~+/-25 px", true back when
# `ft_per_px_z` was ~0.0111 and stale ever since.) The sigmas had the same
# problem from the other end: 1.4-2.2 in against a whole domain of +/-2.75 left
# the offset term nearly flat over everything physically possible, so the base
# prior did most of the work.

# Bat radius at the sweet spot plus ball radius: the centre-to-centre
# separation at which the two are exactly touching, and so the offset at which
# the normal has come all the way round to vertical. Stated here rather than
# imported from `bat_path` to keep this module free of the swing.
CONTACT_NORMAL_RADIUS_IN = 2.75

# Where a ball struck dead centre goes. Not a free parameter: the bat is coming
# up through the ball at `bat_path.ATTACK_ANGLE_DEG` (10 deg) and the pitch is
# coming down, and the collision hands part of that descent back as rise.
ZERO_OFFSET_LAUNCH_DEG = 16.0

# How much of the normal's rise the ball keeps. Below 1 because the tangential
# (friction) impulse pulls the ball back toward the bat's own direction of
# travel, so it does not leave exactly along the normal.
NORMAL_GAIN = 0.85

# Swing-to-swing scatter in the effective attack angle: swing plane, bat flex,
# where around the barrel's circumference the ball caught it. Real launch-angle
# scatter at a given undercut is wider than this; it is kept narrow because it
# must not overturn the geometry's sign, which is the whole point of the model.
LAUNCH_JITTER_DEG = 8.0

# ...and it is *bounded*, which is the part that makes the guarantee a
# guarantee. A Gaussian has infinite support, so however narrow it is set there
# is some tail that contradicts the geometry it is perturbing — and a tail that
# rare is worse than a common one, because it reads to a player as the model
# being arbitrary rather than as it being noisy. The physical variations behind
# this term are all bounded, so the scatter is too. Beyond about 0.4 in over the
# ball a fly ball becomes unreachable and beyond 0.6 in under it a ground ball
# does; inside that, near-square contact genuinely is ambiguous and should be.
JITTER_LIMIT_SIGMA = 2.0

# The Statcast band edges. `LAUNCH_ANGLE_DEG` above states each shape's centre;
# these are the boundaries between them, so "what shape is this" has one
# definition serving both the classifier and the flight model.
SHAPE_LAUNCH_BANDS = (
    (10.0, "GROUNDER"),
    (25.0, "LINER"),
    (50.0, "FLY"),
)
STEEPEST_SHAPE = "POP_UP"


def launch_angle_deg(vertical_offset_in, jitter=True, rng=random):
    """Degrees above horizontal for a ball struck `vertical_offset_in` off centre.

    The offset is ball centre minus bat axis, positive when the bat was *under*
    the ball — the undercut. That is `bat_contact.Contact.vertical_offset_ft`'s
    sign, and the one `hit_outcome_manager` and the swing replay both speak.

    `jitter=False` gives the bare geometry, which is what a test asking about
    the model rather than about the scatter wants.
    """
    u = max(-1.0, min(1.0, vertical_offset_in / CONTACT_NORMAL_RADIUS_IN))
    angle = ZERO_OFFSET_LAUNCH_DEG + NORMAL_GAIN * math.degrees(math.asin(u))
    if jitter and LAUNCH_JITTER_DEG > 0.0:
        limit = JITTER_LIMIT_SIGMA * LAUNCH_JITTER_DEG
        angle += max(-limit, min(limit, rng.gauss(0.0, LAUNCH_JITTER_DEG)))
    return angle


def shape_for_launch_angle(angle_deg):
    """Which trajectory shape a launch angle is, by the Statcast bands."""
    for edge, shape in SHAPE_LAUNCH_BANDS:
        if angle_deg < edge:
            return shape
    return STEEPEST_SHAPE

# --- The flight ------------------------------------------------------------
#
# **Everything below is a function of the launch angle and the exit velocity,
# and of nothing else.** That is new, and it is the point.
#
# It used to be a function of the *shape*. `launch_angle_deg` above produced a
# real continuous angle, `shape_for_launch_angle` banded it, and then the carry
# and the hang time threw the angle away and looked up the band's centre — so
# every airborne ball in the game flew at exactly 14, 32 or 68 degrees. The
# cost was a cliff at each band edge: at 100 mph a ball 0.2 in higher on the
# bat, which is inside this model's own jitter, went from a 241 ft / 2.22 s
# liner to a 357 ft / 4.47 s fly. A tenth of an inch of bat position bought
# 116 ft of carry and two and a quarter seconds of hang time.
#
# The fix is not a new calibration. The three fitted anchors are exactly the
# numbers the per-shape tables held, at exactly the angles those shapes' band
# centres sit at, so a ball at 14, 32 or 68 degrees flies precisely as far and
# hangs precisely as long as it did before. What changes is that the angles in
# between are now interpolated rather than snapped, and the band edges stop
# being discontinuities. Same argument `spray`'s `tanh` was given: preserve the
# value at the reference and only bend where the model was previously faking an
# answer.
#
# The shape survives as a *classification* — it names what kind of batted ball
# this was, for the DB, the animation's arc and `ground_roll`'s descent — but
# it is no longer an input to how far the ball goes.

# Hang-time correction over the vacuum solution. A real ball hangs *longer*
# than the vacuum solution for the distance it actually covered, because drag
# costs it more range than it costs it time in the air.
#
# `(launch angle, factor)`, interpolated linearly in the angle and held flat
# outside the span — see `_interpolate`. The three rows marked *fitted* are the
# values the old per-shape table held, unchanged; the rest fill in between them.
#
# **These are fitted to observed hang times, not read off the same integration
# as `DRAG_RANGE_ANCHORS`**, and that is deliberate rather than sloppy. That
# integration reproduces real *carry* at the reference point by construction
# and then over-predicts *hang time* by about 12% — a 400 ft fly comes out at
# 5.1 s against a real 4.5 — because its lift model keeps the ball up too long
# (the tell is a 68 degree pop-up hanging 7.3 s). Taking the hang time from it
# would hand every outfielder 12% more time to run a ball down, and the whole
# fielding model is calibrated against this clock. Both tables are fits to
# reality at the same angles; neither is a fit to the other.
DRAG_HANG_ANCHORS = (
    # (launch angle, factor)
    ( 5.0, 1.10),
    (10.0, 1.12),
    (14.0, 1.15),   # fitted — the old DRAG_HANG_FACTOR["LINER"]
    (18.0, 1.17),
    (22.0, 1.185),
    (26.0, 1.195),
    (30.0, 1.20),
    (35.0, 1.20),   # fitted — the old DRAG_HANG_FACTOR["FLY"], at 32
    (40.0, 1.19),
    (45.0, 1.17),
    (50.0, 1.15),
    (60.0, 1.12),
    (68.0, 1.10),   # fitted — the old DRAG_HANG_FACTOR["POP_UP"]
    (75.0, 1.08),
)

# Range correction over the vacuum solution — the companion to
# `DRAG_HANG_ANCHORS` and always the smaller number, because drag costs a
# batted ball more distance than it costs hang time.
#
# It is a *declining* function of exit velocity, not a constant, and that
# detail carries real weight. Drag force goes as v^2, so the fraction of the
# vacuum range a real ball keeps shrinks the harder it is hit. Held constant at
# the value that fits a 90 mph fly, the model gave a 109 mph fly 456 ft against
# a real ~415 — and since anything reaching the fence is at minimum a double,
# that error alone put 28.6% of fly balls off the wall, all of which fell in.
#
# `(launch angle, base, knee_mph, slope_per_mph)`: the factor is `base` up to
# `knee`, then declines. Fitted to Statcast carry at each angle — a fly travels
# ~295 ft at 90 mph, ~365 at 100, ~420 at 110; a line drive ~165 ft at 80 mph,
# ~225 at 95, ~280 at 110. Verified against those anchors, which the
# interpolation reproduces exactly at 14, 32 and 68 degrees.
# **Fitted to a numerically integrated trajectory with drag *and lift*** —
# 0.145 kg, 37 mm radius, Cd 0.35, and a backspin ramping to 2000 rpm by 26
# degrees of launch, with the lift coefficient scaled so that the standard
# reference point lands where everyone agrees it does: 100 mph at 30 degrees
# carries 400 ft. The row comments give each angle's carry at 100 mph, which
# is the whole table in one column.
#
# **This replaced a three-row table read at the band centres, and both the
# shape and the level were wrong.** The rows were 14, 32 and 68 degrees, and
# `carry_distance_ft` looked up whichever one the *shape* named — so every
# airborne ball in the game flew at exactly one of three angles, with a cliff
# at each band edge worth 116 ft of carry at 100 mph. That is the defect the
# continuous model removes.
#
# What removing it exposed is that the level was wrong too, and it had been
# hidden. Those three rows were fitted to a *no-lift* trajectory, and real
# batted balls carry backspin:
#
#     angle     old factor    with lift     old carry    real carry  (100 mph)
#       14         0.768        0.876          241 ft       281 ft
#       32         0.594        0.660          357          401
#       68         0.490        0.402          228          187
#
# So line drives flew about 15% short and pop-ups about 20% long. Nobody saw
# it because `hit_animation` clamped every landing into a per-shape range —
# a 130 ft floor under liners, a 365 ft cap over flies, a 160 ft cap over
# pop-ups — which is exactly the compensation those ranges were doing. With
# the landing now taken from the carry, the clamps are gone and the carry has
# to be right on its own: shipped uncorrected, line drives landed short of the
# outfielders and were caught, and BABIP came out .205 against MLB's .300.
#
# `DRAG_HANG_ANCHORS` above is read off the same integrated flights, so the
# carry and the hang time are two consequences of one trajectory. Re-derive
# them together or not at all.
#
# The factor exceeds 1.0 below about 12 degrees, which is not a bug: on a low
# line drive backspin lift more than pays for the drag, and the ball carries
# further than a vacuum would take it.
DRAG_RANGE_ANCHORS = (
    # (launch angle, base, knee_mph, slope_per_mph)
    ( 5.0, 1.0170, 75.0, 0.00138),   # 100 mph carries 114 ft
    (10.0, 1.0069, 75.0, 0.00272),   # 215
    (14.0, 0.9836, 75.0, 0.00361),   # 281
    (18.0, 0.9512, 75.0, 0.00429),   # 332
    (22.0, 0.9134, 75.0, 0.00478),   # 369
    (26.0, 0.8732, 75.0, 0.00511),   # 392
    (30.0, 0.8238, 75.0, 0.00524),   # 400
    (35.0, 0.7718, 75.0, 0.00530),   # 400
    (40.0, 0.7281, 75.0, 0.00530),   # 390
    (45.0, 0.6905, 75.0, 0.00527),   # 371
    (50.0, 0.6571, 75.0, 0.00522),   # 344
    (60.0, 0.5947, 75.0, 0.00515),   # 267
    (68.0, 0.5360, 75.0, 0.00513),   # 187
    (75.0, 0.4534, 75.0, 0.00516),   # 106
)

# Floor on any drag factor, so an extrapolated angle cannot drive the range to
# nothing.
MIN_DRAG_RANGE_FACTOR = 0.30

# Floor and ceiling on any modelled flight, in seconds. The floor keeps a
# near-zero landing distance from producing a zero-length animation; the
# ceiling is above the longest real hang time (a 400 ft fly is ~4.7 s, an
# infield pop ~5 s) and exists only so a pathological input cannot stall the
# play.
MIN_FLIGHT_S = 0.35
MAX_FLIGHT_S = 6.50

# Where the ground-ball band ends, and so where a batted ball stops being a
# projectile at all. Read off `SHAPE_LAUNCH_BANDS` rather than restated, so
# "is this a ground ball" has one definition serving the classifier and the
# flight dispatch.
GROUND_BAND_EDGE_DEG = SHAPE_LAUNCH_BANDS[0][0]

# The angle a caller who has only a *shape* is taken to mean. Every airborne
# entry is that band's centre, which is exactly what the old per-shape tables
# used — so a legacy caller passing a shape gets bit-identical numbers to the
# ones it got before this module became continuous. `GROUNDER` has no entry in
# `LAUNCH_ANGLE_DEG` (that table states the airborne centres) and takes a
# nominal mid-band value here.
GROUNDER_NOMINAL_LAUNCH_DEG = 5.0


def launch_angle_for_shape(shape):
    """The launch angle a caller holding only a shape is taken to mean.

    The bridge for anything that predates the angle being carried — the
    animation's legacy `batted_ball_type` kwarg, and tests that name a shape.
    It returns the band centre, so those callers see exactly the flight the
    per-shape tables used to give them.

    A caller that *has* the real angle must pass it instead. This one cannot
    tell a 26-degree fly from a 49-degree one, which is the whole defect the
    continuous model removes.
    """
    if shape == "GROUNDER":
        return GROUNDER_NOMINAL_LAUNCH_DEG
    return LAUNCH_ANGLE_DEG.get(shape, LAUNCH_ANGLE_DEG["FLY"])


def _interpolate(anchors, angle_deg):
    """Piecewise-linear interpolation of `anchors` in the launch angle.

    `anchors` is a sorted sequence of `(angle, *values)`; the tuple of values
    is interpolated component-wise and held flat outside the span. Flat rather
    than extrapolated on purpose: past the fitted range the slope carries no
    information, and a linear extrapolation of a drag factor runs negative.
    """
    if angle_deg <= anchors[0][0]:
        return anchors[0][1:]
    if angle_deg >= anchors[-1][0]:
        return anchors[-1][1:]
    for (a0, *v0), (a1, *v1) in zip(anchors, anchors[1:]):
        if angle_deg <= a1:
            f = (angle_deg - a0) / (a1 - a0)
            return tuple(x0 + (x1 - x0) * f for x0, x1 in zip(v0, v1))
    return anchors[-1][1:]


def drag_range_factor(launch_deg, ev_mph):
    """The fraction of the vacuum range a real ball keeps, at this angle and speed.

    The fitted `(base, knee, slope)` triple is interpolated in the angle and
    then evaluated at the speed — rather than the other way round — so the
    result is exactly the fitted factor whenever the angle is one of the
    anchors, whatever the exit velocity.
    """
    base, knee, slope = _interpolate(DRAG_RANGE_ANCHORS, launch_deg)
    ev = max(0.0, ev_mph or 0.0)
    return max(MIN_DRAG_RANGE_FACTOR, base - slope * max(0.0, ev - knee))


def drag_hang_factor(launch_deg):
    """How much longer than the vacuum solution a real ball hangs, at this angle."""
    return _interpolate(DRAG_HANG_ANCHORS, launch_deg)[0]


def carry_distance_ft(launch_deg, ev_mph):
    """How far a batted ball carries, from the projectile identity

        R = v^2 sin(2 theta) / g

    corrected by `drag_range_factor`. The same identity gives `hang_time_s`,
    so distance and hang time are two consequences of one flight rather than
    two independent guesses.

    This replaced a linear map from contact quality into a per-shape depth
    range, `mid = dist_min + (dist_max - dist_min) * quality`. The map is not
    wrong in shape, it is wrong in its input distribution: quality is only
    computed for swings that already timed the ball, so its real median is
    well above 0.5 and nearly every batted ball landed at the deep end of its
    range. Keying off exit velocity is right because EV is already the
    calibrated quantity — it has the real distribution baked into it.

    A ground-ball angle is answered honestly rather than refused: the identity
    is still the right one at 5 degrees, it simply gives a short flight. Where
    a *grounder* ends up is friction and whether anybody cut it off, which is
    `ground_depth_fraction` and `ground_roll`, not this.
    """
    v = max(0.0, ev_mph or 0.0) * 5280.0 / 3600.0
    r = v * v * math.sin(2.0 * math.radians(launch_deg)) / G_FT_S2
    return max(0.0, r * drag_range_factor(launch_deg, ev_mph))


def hang_time_s(launch_deg, distance_ft):
    """Contact to landing for an airborne batted ball, in real seconds.

    From the same no-drag identity as the carry,

        T = sqrt(2 R tan(theta) / g)

    which needs only the landing distance and the launch angle — the exit
    velocity is already encoded in how far the ball went, so nothing is
    double-counted. `drag_hang_factor` then corrects for the one thing the
    vacuum solution gets materially wrong.

    Monotonically increasing in distance, which is the property the
    animation's old quality-scaled duration got backwards.

    Takes the *observed* distance rather than deriving one, because the
    animation may have clamped the landing inside the park — so the ball the
    viewer watches and the clock the defense races are one flight.
    """
    r = max(0.0, distance_ft)
    angle = max(0.5, min(89.5, launch_deg))
    t = math.sqrt(2.0 * r * math.tan(math.radians(angle)) / G_FT_S2)
    return max(MIN_FLIGHT_S, min(MAX_FLIGHT_S, t * drag_hang_factor(angle)))


# --- The shape of the flight ------------------------------------------------
#
# How high the ball is at any point along its carry. **This is the drawn arc
# and the fence predicate**, and the two tables above say nothing about it:
# `DRAG_RANGE_ANCHORS` fixes where the ball lands and `DRAG_HANG_ANCHORS` how
# long it takes, and neither says how high it was in between.
#
# It used to be the vacuum parabola through the origin with the drag-corrected
# range and the launch angle's initial slope, `h = d tan(theta) (1 - d/R)`, and
# that shape is wrong in a way that matters. Drag costs a ball far more
# *range* than it costs *height*: it decelerates horizontally the whole way,
# so for the distance it actually covers it goes much higher than a vacuum
# ball covering the same distance, and it spends longer in the second half of
# the path than the first. Against the same integrated trajectory the range
# table is fitted to, the parabola's apex came out **1.5-1.6x too low** across
# every home-run angle (a 105 mph ball at 28 degrees peaks at 89 ft in the air
# and drew at 56) and sat at half the path where the real apex is at 58%.
# The docstring had confessed the opposite — "reads a little high on the way
# down" — and it was low everywhere past about a sixth of the path, at 90%
# of the way by half: 39 ft up in the air against 20 drawn.
#
# Two things read that height and both were wrong by it. The picture: every
# home run drew as a low, gliding arc, which is the signature of a line drive,
# so the fly balls that were leaving the park did not look like fly balls.
# And the decisions: `park.fence_verdict` needed 1.6-2.7x more height at the
# fence than a real ball has there, so a home run needed more carry than it
# should — and the 12 ft fence was raised against *that*; and the catch gate
# in `hit_animation` read a 90 mph line drive at 200 ft as 7.7 ft up, inside
# an 8 ft glove, where the real ball is 14.5 ft over it.
#
# `DRAG_APEX_ANCHORS` is what the integration gives, fitted at the same angles
# as the two tables above and to the same flights: how much higher than the
# vacuum apex the real apex is (`gain`, against `R tan(theta) / 4`), and where
# along the path it sits (`apex_frac`). The profile is two half-parabolas
# meeting at that apex — the simplest shape with the right height, the right
# place, and a steeper descent than ascent, which is what a real trajectory
# has. Three properties survive from the parabola because every consumer
# rests on them: zero at the carry, negative beyond it (the falling branch
# keeps going, so a ground ball's height at the fence is still an honest
# negative number), and `tan(theta)` is still the initial slope in the limit
# — the gain is applied to the *apex*, not the launch.
#
# **Fitted to reality at the same angles, not to each other** — the rule the
# two tables above already state. Re-derive all three together or none.
DRAG_APEX_ANCHORS = (
    # (launch angle, apex gain over R tan(theta)/4, apex path fraction)
    (10.0, 1.221, 0.547),
    (14.0, 1.318, 0.562),
    (18.0, 1.400, 0.572),
    (22.0, 1.468, 0.577),
    (26.0, 1.522, 0.579),
    (30.0, 1.542, 0.578),
    (35.0, 1.563, 0.576),
    (40.0, 1.582, 0.572),
    (45.0, 1.602, 0.567),
    (50.0, 1.627, 0.562),
    (60.0, 1.715, 0.550),
)


def apex_profile(launch_deg):
    """`(gain, apex_frac)` for this launch angle — how much higher than the
    vacuum apex a real ball peaks, and how far along its carry it does so."""
    return _interpolate(DRAG_APEX_ANCHORS, launch_deg)


def apex_height_ft(launch_deg, carry_ft):
    """How high the ball gets, in feet, over a flight of `carry_ft`."""
    gain, _ = apex_profile(launch_deg)
    angle = max(0.0, min(89.5, launch_deg))
    return gain * max(0.0, carry_ft) * math.tan(math.radians(angle)) / 4.0


def height_at_distance_ft(launch_deg, carry_ft, distance_ft):
    """How high the ball is when it has travelled `distance_ft`, in feet.

    **This is what decides a home run**, and it is why the decision no longer
    needs a probability table. A ball clears the fence when it is higher than
    the fence at the fence's own distance, which is one question asked of one
    flight; it strikes the face when it gets there lower than that. Before
    this, whether a ball left the park was a quality-indexed roll in
    `hit_outcome_manager` that could not see the carry, so a median line drive
    with 241 ft of carry was given a 9.8% chance of clearing a wall no nearer
    than 360 ft, and a fly with more carry than the fence could be denied and
    turned into a double off it.

    **It is also the drawn arc** — `hit_animation._flight_height_ft` is this
    function over the ball's own launch angle and carry — so the shape has to
    be right and not merely the endpoints. See the note over
    `DRAG_APEX_ANCHORS` for what the vacuum parabola it replaced got wrong.

    Two half-parabolas: rising to `apex_height_ft` at the fitted apex fraction
    of the carry, falling from there to zero at the carry. Negative past the
    carry, which is the honest answer and the one that makes a ground ball
    fall out without a special case: nothing hit at 5 degrees is above a
    fence 360 ft away.
    """
    r = max(1e-6, carry_ft)
    u = max(0.0, distance_ft) / r
    apex = apex_height_ft(launch_deg, r)
    _, apex_frac = apex_profile(launch_deg)
    if u <= apex_frac:
        return apex * (1.0 - ((apex_frac - u) / apex_frac) ** 2)
    return apex * (1.0 - ((u - apex_frac) / (1.0 - apex_frac)) ** 2)


def ground_time_s(ev_mph, distance_ft):
    """Contact to `distance_ft` for a ball on the ground, in real seconds.

    Delegates to `infield_timing` rather than re-deriving the retention
    curve, so the animation and the infield verdict cannot drift apart.
    """
    return max(MIN_FLIGHT_S,
               min(MAX_FLIGHT_S,
                   infield_timing.ball_travel_time_s(ev_mph, distance_ft)))


def flight_time_s(launch_deg, ev_mph, distance_ft):
    """Real seconds from contact until the ball first reaches the ground at
    `distance_ft` — the window the defense has to cover ground.

    Ground balls are not projectiles and do not use the identity above. They
    take their speed from `infield_timing`'s retention curve, which is the same
    number the infield verdict is computed against, so the ball the viewer
    watches reach the shortstop is the ball the model says reached it.
    """
    if launch_deg < GROUND_BAND_EDGE_DEG:
        return ground_time_s(ev_mph, distance_ft)
    return hang_time_s(launch_deg, distance_ft)


# Exit-velocity span used to place a ground ball inside its depth range.
# Ground balls are not projectiles — where one stops is friction and whether
# anybody cut it off, not ballistics — so they keep a range map. What changed
# is what indexes it.
GROUND_EV_SPAN_MPH = (40.0, 112.0)


def ground_depth_fraction(ev_mph):
    """Where inside its depth range a ground ball ends its bouncing
    phase, as a fraction in [0, 1], indexed on exit velocity.

    Keyed on EV for the same reason as `carry_distance_ft` — the quality
    it replaced was concentrated near 1.0, so almost every grounder was
    placed at the deep end of its range.
    """
    lo, hi = GROUND_EV_SPAN_MPH
    return max(0.0, min(1.0, ((ev_mph or 0.0) - lo) / (hi - lo)))
