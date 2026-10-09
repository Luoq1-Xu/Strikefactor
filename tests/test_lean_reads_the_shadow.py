"""Fielders who are not making the play still decide off the ball's shadow.

`_update_lean_targets` moves every fielder who is not the primary: a lean
toward the ball in flight, and — once it is rolling — a sprint at it for
anyone inside the chase radius. It measured both against `_ball`, the *drawn*
ball, which carries its lift up the screen. So the whole defense leaned at a
point high above a fly ball, and whether a fielder joined the chase was
settled by a distance to a ball in mid-hop. `_ball_past_fielder` and the
secure test in `_update_hit` already read the shadow for exactly this reason.
"""

import math
import random

from strikefactor.gameplay.hit_animation import (
    FT_TO_PX_X,
    FT_TO_PX_Y,
    OUTFIELD_ROLES,
    POST_LAND_CHASE_RADIUS_FT,
    SECURE_RADIUS_PX,
    HitAnimation,
)


class _StubBatter:
    def get_handedness(self):
        return "R"


class _StubGame:
    def __init__(self):
        self.batter = _StubBatter()


def _fly(seed=5):
    random.seed(seed)
    return HitAnimation(_StubGame(), "IN_PLAY", lambda: None, quality=0.9,
                        batted_ball_type="FLY", spray_deg=0.0,
                        ev_mph=95.0, launch_deg=30.0)


def _free_fielders(anim, roles):
    return [r for r in roles if r not in anim._lean_excluded]


def test_the_lean_points_at_the_ground_under_the_ball_not_at_the_drawn_ball():
    anim = _fly()
    t = 1000
    anim.update(t)
    # Mid-flight, when the drawn ball is far above its shadow.
    while anim._elapsed < 0.5 * anim.duration_ms:
        t += 16
        anim.update(t)
    lift = anim._ball_shadow[1] - anim._ball[1]
    assert lift > 40, "need a ball well up in the air for this to mean anything"

    anim._update_lean_targets()
    sx, sy = anim._ball_shadow
    leaners = _free_fielders(anim, anim.fielders)
    assert leaners
    for role in leaners:
        f = anim.fielders[role]
        hx, hy = f.home_pos
        lean = (f.target[0] - hx, f.target[1] - hy)
        to_shadow = (sx - hx, sy - hy)
        cross = lean[0] * to_shadow[1] - lean[1] * to_shadow[0]
        assert abs(cross) < 1e-6 * math.hypot(*to_shadow) * max(1.0, math.hypot(*lean)), role
        assert lean[0] * to_shadow[0] + lean[1] * to_shadow[1] > 0, role


def _rolling_fly():
    """A fly that has landed and is live on the grass, nobody on it yet."""
    anim = _fly(seed=7)
    t = 1000
    anim.update(t)
    while anim._elapsed <= anim.duration_ms + 50:
        t += 16
        anim.update(t)
    anim._secured = False
    return anim


def _place(anim, role, dy_from_shadow):
    f = anim.fielders[role]
    f.pos = [anim._ball_shadow[0], anim._ball_shadow[1] + dy_from_shadow]
    f.home_pos = tuple(f.pos)
    f.decel_radius_px = 999.0
    return f


def test_joining_the_chase_is_measured_to_the_shadow():
    anim = _rolling_fly()
    role = _free_fielders(anim, OUTFIELD_ROLES)[0]
    # The ball mid-hop: drawn 60 px up the screen from where it is.
    sx, sy = anim._ball_shadow
    anim._ball = (sx, sy - 60.0)

    # Inside the radius from the shadow, outside it from the drawn ball.
    near = (POST_LAND_CHASE_RADIUS_FT - 10) * FT_TO_PX_Y
    f = _place(anim, role, +near)
    anim._update_lean_targets()
    assert f.target == anim._predict_ball_stop(), "a fielder this close chases"
    assert f.decel_radius_px == SECURE_RADIUS_PX


def test_a_fielder_out_of_range_of_the_ball_does_not_chase_its_picture():
    anim = _rolling_fly()
    role = _free_fielders(anim, OUTFIELD_ROLES)[0]
    sx, sy = anim._ball_shadow
    anim._ball = (sx, sy - 60.0)

    # Outside the radius from the shadow, inside it from the drawn ball.
    far = (POST_LAND_CHASE_RADIUS_FT + 10) * FT_TO_PX_Y
    f = _place(anim, role, -far)
    anim._update_lean_targets()
    assert f.target != anim._predict_ball_stop(), "the drawn ball is not where the ball is"
    assert f.decel_radius_px == 999.0


def test_post_landing_chase_radius_is_the_same_in_both_field_directions():
    anim = _rolling_fly()
    role = _free_fielders(anim, OUTFIELD_ROLES)[0]
    f = anim.fielders[role]
    sx, sy = anim._ball_shadow
    stop = anim._predict_ball_stop()

    for offset in (-1.0, 1.0):
        distance_ft = POST_LAND_CHASE_RADIUS_FT + offset
        for dx, dy in ((distance_ft * FT_TO_PX_X, 0.0),
                       (0.0, distance_ft * FT_TO_PX_Y)):
            f.pos = [sx + dx, sy + dy]
            f.home_pos = tuple(f.pos)
            f.decel_radius_px = 999.0
            anim._update_lean_targets()
            assert (f.target == stop) == (offset < 0), (dx, dy)
