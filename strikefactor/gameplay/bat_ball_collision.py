"""Which way the ball leaves the bat, from one collision.

Same contract as `spray.py` and `ball_flight.py` — real feet and seconds, no
pygame, no game state. One question, asked once per contact: given a bat and a
ball that met, in what direction did the ball leave.

This module exists because that one collision was modelled three times.
Horizontal direction came from the bat's bearing (`spray`), with a reference
angle subtracted and two gains applied. Vertical direction came from the
vertical offset alone (`ball_flight.launch_angle_deg`), with a fitted intercept,
a fitted gain and a bounded jitter. The first two are one vector in a real
collision, and they interact: on a bat that is tilted barrel-down, getting
under the ball also turns it toward the opposite field. Nothing modelled that,
because nothing held both halves at once.

Three things are worth knowing.

**It is evaluated at first touch, not at closest approach.** `bat_contact`'s
sweep reports the instant the two centres are nearest, and there the
separation is perpendicular to the relative velocity by construction. Used
directly as the contact normal it describes a glancing blow on every swing,
including a ball struck dead centre. That separation is the *impact
parameter*: how far off centre the ball was heading. The normal at the instant
the surfaces first touched is rebuilt from it — see `first_touch_normal`.

**The ball does not leave along the normal.** Along the normal it rebounds
with the collision efficiency `q`. Across it — along the barrel, and around it
— it keeps part of the motion it arrived with, because a ball that grips the
bat leaves rolling and not stopped. So a pitch met by a bat turned past square
leaves further round than the bat's face points: about 1.6 times as far, at
these speeds. A bunt off an angled bat is the limiting case. That ratio is
what the old `spray.TIMING_GAIN` was standing in for.

**Only the direction is used.** The speed of the vector built here is thrown
away. The swing has one bat speed (`bat_path.PEAK_BAT_SPEED_MPH`), so a speed
read off this collision tops out near 103 mph and has nothing like a real
exit-velocity distribution; exit velocity stays on
`contact_audio.EV_CALIBRATION`. Do not read a second exit velocity from here.

Deterministic, like `spray`: the spread a player sees comes from their own aim
and timing, and a ball that goes where it was hit is what the replay teaches.
"""

import math

# Collision efficiency at the sweet spot: the standard
# `EV = q * pitch speed + (1 + q) * bat speed`, with both speeds taken along
# the contact normal. Physics, not a dial — it folds the ball's coefficient of
# restitution and the bat's recoil into one measured number.
COLLISION_EFFICIENCY = 0.20

# The share of its tangential motion, relative to the bat's surface, that the
# ball keeps. 5/7 is a solid sphere that arrives without spin and leaves
# rolling: friction acts until the contact point stops sliding, and that takes
# 2/7 of the sliding speed.
#
# Cross and Nathan measured a baseball gripping slightly harder than rolling
# (a tangential restitution near 0.16, which is 0.67 by the same algebra), and
# a bat that can twist about its own axis gives some of that back. The two
# roughly cancel, so the rolling value stands. Physics, not a dial: change it
# against a measurement, never to move a rate.
TANGENTIAL_KEEP = 5.0 / 7.0

_EPS = 1e-12


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _unit(v):
    mag = math.sqrt(_dot(v, v))
    if mag < _EPS:
        return None
    return (v[0] / mag, v[1] / mag, v[2] / mag)


def _without(v, unit_dir):
    """`v` with its component along `unit_dir` removed."""
    k = _dot(v, unit_dir)
    return (v[0] - k * unit_dir[0], v[1] - k * unit_dir[1],
            v[2] - k * unit_dir[2])


def first_touch_normal(separation_ft, bat_axis, reach_ft, v_ball, v_bat,
                       end_cap=False):
    """Unit vector from the bat to the ball at the instant they first touched.

    `separation_ft` is the ball's centre minus the nearest point on the bat's
    axis at **closest approach**, which is what the sweep reports. `reach_ft`
    is the centre-to-axis distance at which the two surfaces touch: the bat's
    radius there plus the ball's.

    Seen along the bat, the ball is a point approaching a circle of radius
    `reach_ft` on a straight line. The part of the separation that is
    perpendicular to that line is the impact parameter `b`, and it does not
    change as the ball comes in. Where the line first crosses the circle, the
    radius to the ball makes an angle `psi` with the line, `sin(psi) =
    |b| / reach`. So the normal is the reversed approach direction turned
    toward `b` by `psi`: zero for a ball struck dead centre, a quarter turn
    for one that only grazed.

    A bat is a cylinder along its length, so the approach and the separation
    are both taken perpendicular to the axis. `end_cap` is for a ball that met
    the rounded end beyond the axis: there the bat is a sphere, nothing is
    projected, and the normal can point along the bat.

    The taper is ignored. Through the barrel the bat is parallel-sided, and
    where it does narrow the surface leans under four degrees.
    """
    approach = tuple(v_ball[i] - v_bat[i] for i in range(3))
    offset = tuple(separation_ft)
    if not end_cap:
        axis = _unit(bat_axis)
        if axis is not None:
            approach = _without(approach, axis)
            offset = _without(offset, axis)

    incoming = _unit(approach)
    if incoming is None:
        # No closing motion to speak of. The separation is all there is.
        return _unit(offset) or (0.0, 1.0, 0.0)

    impact = _without(offset, incoming)
    b = math.sqrt(_dot(impact, impact))
    if b < _EPS or reach_ft <= _EPS:
        return (-incoming[0], -incoming[1], -incoming[2])
    sin_psi = min(1.0, b / reach_ft)
    cos_psi = math.sqrt(1.0 - sin_psi * sin_psi)
    return tuple(-incoming[i] * cos_psi + impact[i] / b * sin_psi
                 for i in range(3))


def exit_direction(separation_ft, bat_axis, reach_ft, v_ball, v_bat,
                   end_cap=False):
    """Unit vector the ball leaves along, in the frame the inputs are in.

    Velocities are in feet per second: the ball's from its trajectory, the
    bat's at the point of the bat that met the ball. See `first_touch_normal`
    for the other arguments.

    Along the normal `n` the ball leaves at
    `(1 + q) * (v_bat . n) - q * (v_ball . n)`. Across it the bat's own motion
    carries over whole and the ball keeps `TANGENTIAL_KEEP` of what it had
    relative to the bat.

    **The length of the vector this builds is not an exit velocity** and is
    not returned. See the module docstring.
    """
    n = first_touch_normal(separation_ft, bat_axis, reach_ft, v_ball, v_bat,
                           end_cap=end_cap)
    bat_n = _dot(v_bat, n)
    ball_n = _dot(v_ball, n)
    out_n = (1.0 + COLLISION_EFFICIENCY) * bat_n - COLLISION_EFFICIENCY * ball_n

    relative = tuple(v_ball[i] - v_bat[i] for i in range(3))
    slide = _without(relative, n)
    v_out = tuple(out_n * n[i] + (v_bat[i] - bat_n * n[i])
                  + TANGENTIAL_KEEP * slide[i] for i in range(3))
    return _unit(v_out) or n


# --- Reading the vector ----------------------------------------------------
#
# Both take the direction **pull-positive**: `(toward the batter's pull field,
# toward the pitcher, up)`. `spray.pull_frame` is the conversion from world
# feet, and the one place the handedness flip happens on the way in.

def spray_deg(direction):
    """Degrees from centre field, pull-positive, of a pull-frame direction."""
    if math.hypot(direction[0], direction[1]) < _EPS:
        return 0.0
    return math.degrees(math.atan2(direction[0], direction[1]))


def launch_deg(direction):
    """Degrees above horizontal of a direction."""
    return math.degrees(math.atan2(direction[2],
                                   math.hypot(direction[0], direction[1])))
