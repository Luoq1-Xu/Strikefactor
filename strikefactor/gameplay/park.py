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
