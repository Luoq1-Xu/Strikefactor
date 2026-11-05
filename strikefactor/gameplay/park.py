"""The ballpark, in real feet.

Same contract as `ball_flight.py` and `spray.py` — real feet, no pygame, no
game state. One question: how far away is the fence, and how high is it.

**This exists because whether a ball left the park was decided by a
probability table.** `hit_outcome_manager` rolled a home run off a
quality-indexed rate that could not see how far the ball was going to carry,
while `ball_flight` was separately computing exactly that — so one batted ball
was asked "did it clear the fence?" twice, by two models that disagreed. At the
median they disagreed *systematically*: a line drive carrying 241 ft was given
a 9.8% chance of clearing a fence no nearer than 360 ft, and a fly with more
carry than the fence could lose the roll and be turned into a double off it.

With the fence stated here as a distance and a height, the question has one
answer — `ball_flight.height_at_distance_ft` at `wall_distance_ft` against
`FENCE_HEIGHT_FT` — and `hit_outcome_manager` and `hit_animation` reach it from
the same three inputs (launch angle, exit velocity, bearing), so they cannot
disagree.

The wall was a pair of constants inside `hit_animation`, immediately multiplied
into screen pixels; that file now derives its render semi-axes from these, so
the drawn fence and the fence the verdict is computed against are one fence.
"""

import math

from strikefactor.gameplay import ball_flight

# The outfield wall is an ellipse in real field feet, semi-axes along the
# lateral (x) and straight-away (y) axes of `spray`'s field frame.
#
# **Note what these are not.** `FOUL_LINE_SEMI_FT` is the semi-axis at a field
# bearing of 0 degrees, which is out in foul territory — it is not the distance
# down the foul line. Fair territory starts at 45 degrees, where the ellipse
# measures `wall_distance_ft(pi/4)` = 360 ft. So this park is deep down the
# lines by MLB standards (325-335 ft is typical) and ordinary to centre, and
# a sub-360 ft home run is geometrically impossible in it.
#
# That is a pre-existing property of the drawn field rather than something
# chosen here, and it now has teeth: with the home run decided by physics
# rather than by a roll, the park's depth suppresses home runs directly.
# Bringing the lines in means reshaping the wall that gets drawn, which is a
# rendering change and not a constant edit — see `hit_animation._wall_r_at`.
FOUL_LINE_SEMI_FT = 330.0
CENTRE_FIELD_FT = 400.0

# How high the fence is. A ball is out of the park when it is above this at the
# fence's own distance, and off the wall when it gets there lower. Real parks
# run from 3 ft to Fenway's 37, and a per-bearing height would go here if the
# drawn wall ever grew one.
#
# **12 ft rather than the ordinary MLB 8, and the height is doing two jobs —
# but only one of them is still the reason.** It was raised for the home-run
# rate: at 8 ft this deep park sent **6.3%** of fair batted balls out against
# MLB's 4-5%, 5.1% at 12. Those figures were measured against the vacuum
# parabola `ball_flight.height_at_distance_ft` used to be, which read a ball's
# height at the fence 1.6-2.7x *low* — so the fence was being raised to hold a
# rate that a flat arc was already suppressing. With the arc physical
# (`DRAG_APEX_ANCHORS`) the same batter puts 6.0% out at 12 ft, and holding
# the rate here would have meant a fence taller still. The rate is held by
# the top of `contact_audio.EV_CALIBRATION` instead (4.1% on the harness),
# which is the lever that reaches the balls that should not be leaving and
# not the ones that should. Do not raise this for the home-run rate again.
#
# The job it does keep is the one that is easy to miss: **the fence height
# decides what a ball off the wall is allowed to be.** A ball is off the wall
# exactly when it arrives below the rim, so an 8 ft fence means every wall
# ball arrives inside a fielder's 8 ft reach and a fielder standing there
# catches it — the ladder measured 50 of 58 caught, which is why doubles ran
# at 0.16 per single against MLB's 0.33. A taller fence puts the band between
# the glove and the rim back: a ball reaching the wall at 10 ft is over the
# fielder's head, off the wall, and a double. That band is narrower on the
# real descent than it was on the parabola — about 2.4 mph of exit velocity
# at a 30 degree launch, because past the fence a real ball is still 60-90 ft
# up — and the catch is asked ~2.7 ft in front of the face where the ball is
# that much higher, so a ball is gloved at the wall only if it arrives under
# about 5 ft. See `tests/test_catchable_in_flight._WALL_BALL_HEIGHT_FT`.
FENCE_HEIGHT_FT = 12.0


def wall_distance_ft(field_rad):
    """Feet from home plate to the fence along a real-field bearing.

    `field_rad` is `spray.field_angle_rad` — pi/2 is centre field, pi/4 and
    3pi/4 are the foul lines. Runs 360 ft down either line to 400 ft to
    straight-away centre.

    The polar form of the ellipse, which is the same expression
    `hit_animation._wall_r_at` evaluates against the *rendered* semi-axes. It
    has to be: the render axes are these two scaled anisotropically, and an
    ellipse scaled along its own axes is still that ellipse, so the two agree
    at every bearing by construction rather than by coincidence.
    """
    cos_a = math.cos(field_rad)
    sin_a = math.sin(field_rad)
    return (FOUL_LINE_SEMI_FT * CENTRE_FIELD_FT
            / math.hypot(CENTRE_FIELD_FT * cos_a, FOUL_LINE_SEMI_FT * sin_a))


# What the fence does to a flight. Three states, not two — a ball can clear it,
# strike its face, or land in front of it — and the middle one is what makes a
# wall ball an outcome of the physics rather than a separate roll.
OUT_OF_PARK = "OUT_OF_PARK"
OFF_THE_WALL = "OFF_THE_WALL"
SHORT_OF_WALL = "SHORT_OF_WALL"


def fence_verdict(launch_deg, ev_mph, field_rad):
    """What this flight does when it reaches the fence.

    The one place the question is asked. `hit_outcome_manager` calls it at
    contact to decide a home run and `hit_animation` calls it again to place
    the ball; both pass the same launch angle, exit velocity and bearing —
    each drawn exactly once upstream — so the two calls are the same call and
    the picture cannot contradict the verdict.

    It replaced three separate answers: a quality-indexed home-run probability,
    a `WALL_REACH_FT = 380` scalar tested against an elliptical wall that runs
    360 to 400 ft, and a `random` carry past the fence that ignored the exit
    velocity entirely.

    Returns `SHORT_OF_WALL` for anything that lands in front, which includes
    every ground ball without needing a special case: `height_at_distance_ft`
    is negative past the carry, and nothing struck at 5 degrees is above a
    fence 360 ft away.
    """
    carry_ft = ball_flight.carry_distance_ft(launch_deg, ev_mph)
    wall_ft = wall_distance_ft(field_rad)
    if carry_ft < wall_ft:
        return SHORT_OF_WALL
    height_ft = ball_flight.height_at_distance_ft(launch_deg, carry_ft, wall_ft)
    return OUT_OF_PARK if height_ft > FENCE_HEIGHT_FT else OFF_THE_WALL


# --- Foul ground -------------------------------------------------------------
#
# The wall above bounds fair territory. This bounds the foul ground beside it:
# where a fielder can still run, and so where a foul fly can still be caught.
# Same contract as the wall — real feet, one answer, asked by the animation,
# the fielders and the catch gate alike.
#
# **The backstop is the bottom edge of the screen.** Home plate is drawn 50 px
# above it at `FT_TO_PX_Y = 1.10`, which is 45.5 ft, and real backstops stand
# 45-60 ft behind the plate. Putting the net there keeps every catchable foul
# on screen, catcher included, and it gives "the ball left the bottom of the
# screen" a meaning: it went into the net.
#
# The rail is stated as a distance *from fair territory*, so one rule draws all
# of it: a 45 ft arc behind the plate (where the nearest fair ground is the
# plate itself) that runs straight into rails 45 ft off each foul line. Real
# parks put the dugouts 40-60 ft off the line and pinch the corners, so the
# rail closes in to `FOUL_GROUND_AT_POLE_FT` by the foul pole.
#
# **That width is the calibration of the foul out.** Whether a foul fly is
# caught is the defense getting under it, and nothing else, so how much foul
# ground there is to get under it in is the dial. MLB caught about 2.5% of
# fouls in 2019 (1.4 foul outs a game against ~54 fouls); `tools.calibrate_
# fouls` measured, over 26,000 swings a hand, 1.8% / 1.9% (RHB / LHB) at
# 25 ft, and 2.3% / 2.5% at 40 ft. 45 — no pinch at all — overshoots to 2.7%.
BACKSTOP_FT = 45.0
FOUL_GROUND_AT_POLE_FT = 40.0
FOUL_POLE_FT = wall_distance_ft(math.pi / 4.0)

# Where a ball in foul ground is. `FAIR` is there so the question is total;
# nothing that asks it should be handed a fair ball.
FAIR = "FAIR"
PLAYABLE = "PLAYABLE"     # foul ground a fielder can reach
BACKSTOP = "BACKSTOP"     # behind the plate, past the net
STANDS = "STANDS"         # past the rail beside a line, or past the pole


def foul_ground_width_ft(along_ft):
    """How far the rail stands off a foul line, `along_ft` feet down it."""
    frac = max(0.0, min(1.0, along_ft / FOUL_POLE_FT))
    return BACKSTOP_FT + (FOUL_GROUND_AT_POLE_FT - BACKSTOP_FT) * frac


def foul_ground_verdict(x_ft, y_ft):
    """What is at this point of the field: fair ground, playable foul ground,
    the backstop or the stands.

    `x_ft` is lateral (positive toward first base) and `y_ft` toward centre
    field, the frame `hit_animation._to_field_ft` returns. Foul lines at 45
    degrees, so a point is fair exactly when `|x| <= y`.
    """
    ax = abs(x_ft)
    if ax <= y_ft:
        return FAIR
    root2 = math.sqrt(2.0)
    along = (ax + y_ft) / root2
    if along <= 0.0:
        # Behind the plate: the nearest fair ground is home itself.
        return PLAYABLE if math.hypot(x_ft, y_ft) <= BACKSTOP_FT else BACKSTOP
    off = (ax - y_ft) / root2
    if along > FOUL_POLE_FT or off > foul_ground_width_ft(along):
        return STANDS
    return PLAYABLE


def foul_rail_ft(side, samples=48):
    """The playable foul ground's outer edge on one side, in field feet.

    `side` is +1 for the first-base side and -1 for third. Starts on the
    centre line behind the plate and runs out to the rail's end at the pole,
    so the two sides drawn together are the whole boundary.
    """
    root2 = math.sqrt(2.0)
    points = []
    arc = max(2, samples // 4)
    # The arc behind the plate: from straight back round to the line's
    # perpendicular, which is 45 degrees either side of straight back.
    for i in range(arc + 1):
        a = -math.pi / 2.0 + side * (math.pi / 4.0) * i / arc
        points.append((BACKSTOP_FT * math.cos(a), BACKSTOP_FT * math.sin(a)))
    for i in range(1, samples + 1):
        along = FOUL_POLE_FT * i / samples
        off = foul_ground_width_ft(along)
        points.append((side * (along + off) / root2, (along - off) / root2))
    return points


def clamp_to_foul_ground_ft(x_ft, y_ft, margin_ft=0.0):
    """The nearest point to `(x_ft, y_ft)` that a fielder can stand on.

    Fair ground comes back unchanged, and so does foul ground at least
    `margin_ft` inside the rail and the net. Anything nearer, or past them, is
    pulled straight in toward the plate behind it and square back to the rail
    beside a line — the rail is a wall, and a fielder chasing a ball into the
    seats stops at it.
    """
    ax = abs(x_ft)
    if ax <= y_ft:
        return (x_ft, y_ft)
    root2 = math.sqrt(2.0)
    sign = 1.0 if x_ft >= 0.0 else -1.0
    along = (ax + y_ft) / root2
    if along <= 0.0:
        r = math.hypot(x_ft, y_ft)
        limit = max(0.0, BACKSTOP_FT - margin_ft)
        if r <= limit:
            return (x_ft, y_ft)
        return (x_ft * limit / r, y_ft * limit / r)
    off = (ax - y_ft) / root2
    held = min(along, FOUL_POLE_FT)
    limit = max(0.0, foul_ground_width_ft(held) - margin_ft)
    if held == along and off <= limit:
        return (x_ft, y_ft)
    off = min(off, limit)
    return (sign * (held + off) / root2, (held - off) / root2)
