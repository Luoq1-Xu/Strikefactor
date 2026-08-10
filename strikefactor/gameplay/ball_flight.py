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

Airborne shapes use the no-drag projectile identity

    R = v² sin(2θ) / g        T = 2 v sin(θ) / g     =>     T = sqrt(2 R tanθ / g)

which needs only the landing distance and a per-shape launch angle — the
exit velocity is already encoded in how far the ball went, so nothing has
to be double-counted. `DRAG_HANG_FACTOR` then corrects for the one thing
the vacuum identity gets materially wrong: drag costs a real batted ball
more distance than it costs hang time, so a real ball hangs longer than
the vacuum solution for the distance it actually covered.

Ground balls are not projectiles and do not use any of that. They take
their speed from `infield_timing`'s retention curve, which is the same
number the infield verdict is computed against — so the ball the viewer
watches reach the shortstop and the ball the model says reached the
shortstop are the same ball.
"""

import math

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

# Hang-time correction over the vacuum solution, per shape. A real ball
# loses more range to drag than it loses hang time, so for a *given
# observed distance* it stays up longer than the no-drag identity says.
# The correction is smallest on pop-ups, which barely travel and spend
# their flight nearly vertical where drag does least to the range.
DRAG_HANG_FACTOR = {
    "LINER":  1.15,
    "FLY":    1.20,
    "POP_UP": 1.10,
}

# Floor and ceiling on any modelled flight, in seconds. The floor keeps a
# near-zero landing distance from producing a zero-length animation; the
# ceiling is above the longest real hang time (a 400 ft fly is ~4.7 s, an
# infield pop ~5 s) and exists only so a pathological input cannot stall
# the play.
MIN_FLIGHT_S = 0.35
MAX_FLIGHT_S = 6.50


def hang_time_s(shape, distance_ft):
    """Contact to landing for an airborne batted ball, in real seconds.

    Monotonically increasing in distance, which is the property the
    animation's quality-scaled duration got backwards.
    """
    angle_deg = LAUNCH_ANGLE_DEG.get(shape, LAUNCH_ANGLE_DEG["FLY"])
    drag = DRAG_HANG_FACTOR.get(shape, DRAG_HANG_FACTOR["FLY"])
    r = max(0.0, distance_ft)
    t = math.sqrt(2.0 * r * math.tan(math.radians(angle_deg)) / G_FT_S2)
    return max(MIN_FLIGHT_S, min(MAX_FLIGHT_S, t * drag))


def ground_time_s(ev_mph, distance_ft):
    """Contact to `distance_ft` for a ball on the ground, in real seconds.

    Delegates to `infield_timing` rather than re-deriving the retention
    curve, so the animation and the infield verdict cannot drift apart.
    """
    return max(MIN_FLIGHT_S,
               min(MAX_FLIGHT_S,
                   infield_timing.ball_travel_time_s(ev_mph, distance_ft)))


def flight_time_s(shape, ev_mph, distance_ft):
    """Real seconds from contact until the ball first reaches the ground
    at `distance_ft` — the window the defense has to cover ground.
    """
    if shape == "GROUNDER":
        return ground_time_s(ev_mph, distance_ft)
    return hang_time_s(shape, distance_ft)


# Range correction over the vacuum solution, per shape — the companion to
# DRAG_HANG_FACTOR and always the smaller number, because drag costs a
# batted ball more distance than it costs hang time.
#
# It is a *declining* function of exit velocity, not a constant, and that
# detail carries real weight. Drag force goes as v², so the fraction of
# the vacuum range a real ball keeps shrinks the harder it is hit. Held
# constant at the value that fits a 90 mph fly, the model gave a 109 mph
# fly 456 ft against a real ~415 — and since anything reaching the fence
# becomes a wall ball and therefore at minimum a double, that error alone
# put 28.6% of fly balls off the wall, all of which fell in. Fly-ball
# BABIP was .271 against an MLB .120 and it was almost entirely this.
#
# (base, knee_mph, slope_per_mph): the factor is `base` up to `knee`, then
# declines. Fitted to Statcast carry at each shape's launch angle — a fly
# travels ~295 ft at 90 mph, ~365 at 100, ~420 at 110; a line drive
# ~165 ft at 80 mph, ~225 at 95, ~280 at 110.
DRAG_RANGE_FIT = {
    "LINER":  (0.830, 80.0, 0.0031),
    "FLY":    (0.605, 95.0, 0.0022),
    "POP_UP": (0.500, 95.0, 0.0020),
}

# Exit-velocity span used to place a ground ball inside its depth range.
# Ground balls are not projectiles — where one stops is friction and
# whether anybody cut it off, not ballistics — so they keep a range map.
# What changed is what indexes it.
GROUND_EV_SPAN_MPH = (40.0, 112.0)


def carry_distance_ft(shape, ev_mph):
    """How far an airborne batted ball carries, from the same projectile
    identity `hang_time_s` uses — so distance and hang time are two
    consequences of one flight rather than two independent guesses.

    This replaced a linear map from contact quality into a per-shape
    depth range, `mid = dist_min + (dist_max - dist_min) * quality`. The
    map is not wrong in shape, it is wrong in its input distribution:
    quality is only computed for swings that already timed the ball, so
    its real median is 0.88 and its p25 is 0.77, not 0.5. Liners were
    landing 235-307 ft on average and rolling another 60 ft, which put
    nearly every one of them past the outfielders for a double — 2B/1B
    came out at 1.34 against an MLB 0.32.

    This is the same trap `contact_audio.EV_CALIBRATION` documents, one
    module over, and the reason to key off exit velocity is that EV is
    already the calibrated quantity: it has the real distribution baked
    into it.
    """
    angle_deg = LAUNCH_ANGLE_DEG.get(shape, LAUNCH_ANGLE_DEG["FLY"])
    base, knee, slope = DRAG_RANGE_FIT.get(shape, DRAG_RANGE_FIT["FLY"])
    ev = max(0.0, ev_mph or 0.0)
    drag = max(0.30, base - slope * max(0.0, ev - knee))
    v = ev * 5280.0 / 3600.0
    r = v * v * math.sin(2.0 * math.radians(angle_deg)) / G_FT_S2
    return max(0.0, r * drag)


def ground_depth_fraction(ev_mph):
    """Where inside its depth range a ground ball ends its bouncing
    phase, as a fraction in [0, 1], indexed on exit velocity.

    Keyed on EV for the same reason as `carry_distance_ft` — the quality
    it replaced was concentrated near 1.0, so almost every grounder was
    placed at the deep end of its range.
    """
    lo, hi = GROUND_EV_SPAN_MPH
    return max(0.0, min(1.0, ((ev_mph or 0.0) - lo) / (hi - lo)))
