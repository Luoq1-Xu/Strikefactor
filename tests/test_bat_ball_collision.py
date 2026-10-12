"""One collision, one exit direction.

The ball's horizontal and vertical directions used to come from two models
that could not see each other: `spray` read the bat's bearing through a remap,
and `ball_flight` read the vertical offset through a fit. They are one vector
in a real collision, and what is guarded here is that they are one vector in
this one — and that it points where a bat and a ball would actually send it.

Every directional claim is made for both hands (CLAUDE.md, rule 9), and every
guarantee is asserted on a stated case rather than a sample (rule 10).
"""

import inspect
import math

import pytest

from strikefactor.gameplay import bat_ball_collision as col
from strikefactor.gameplay import bat_path as bp
from strikefactor.gameplay import spray
from strikefactor.gameplay.bat_contact import BALL_RADIUS_FT

HANDS = ("R", "L")
FT_S_PER_MPH = 5280.0 / 3600.0

# Bat radius at the sweet spot plus the ball's: where the two surfaces touch.
REACH_FT = bp.bat_radius_ft(bp.CONTACT_SWEET_SPOT_FRAC) + BALL_RADIUS_FT


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def meet(hand="R", offset_in=0.0, bearing_deg=0.0, tilt_deg=0.0,
         attack_deg=bp.ATTACK_ANGLE_DEG, descent_deg=6.0,
         bat_mph=bp.PEAK_BAT_SPEED_MPH, pitch_mph=84.0):
    """The exit direction of one stated collision, pull-positive.

    The bat is `bearing_deg` past square and `tilt_deg` above horizontal
    (negative is barrel-down), moving square to its own length and rising at
    `attack_deg`. The pitch comes straight in, falling at `descent_deg`.
    `offset_in` is how far the ball's line passes above the bat's axis:
    positive is the bat under the ball.
    """
    spin = spray.spin_for(hand)
    b, t = math.radians(bearing_deg), math.radians(tilt_deg)
    a, d = math.radians(attack_deg), math.radians(descent_deg)
    axis = (-spin * math.cos(b) * math.cos(t), math.sin(b) * math.cos(t),
            math.sin(t))
    v_bat = tuple(bat_mph * FT_S_PER_MPH * c for c in (
        spin * math.sin(b) * math.cos(a), math.cos(b) * math.cos(a),
        math.sin(a)))
    v_ball = (0.0, -pitch_mph * FT_S_PER_MPH * math.cos(d),
              -pitch_mph * FT_S_PER_MPH * math.sin(d))

    # The impact parameter is perpendicular to the bat and to the approach.
    approach = col._unit(col._without(
        tuple(v_ball[i] - v_bat[i] for i in range(3)), col._unit(axis)))
    over = _cross(col._unit(axis), approach)
    if over[2] < 0.0:
        over = tuple(-c for c in over)
    separation = tuple(offset_in / 12.0 * c for c in over)
    out = col.exit_direction(separation, axis, REACH_FT, v_ball, v_bat)
    return spray.pull_frame(out, spin)


def spray_and_launch(**kw):
    out = meet(**kw)
    return col.spray_deg(out), col.launch_deg(out)


# ---- The module contract ----------------------------------------------------

def test_the_module_is_pure():
    """Real units, no pygame, no game state: the `spray` / `ball_flight`
    contract, which is what lets it be tested without a display."""
    imports = [line for line in inspect.getsource(col).splitlines()
               if line.startswith(("import ", "from "))]
    assert imports == ["import math"]


def test_only_a_direction_comes_out():
    """The swing has one bat speed, so a speed read off this collision would
    be a second exit velocity with the wrong distribution. The vector is
    normalised and nothing in the module offers its length."""
    out = meet(offset_in=0.4, bearing_deg=12.0)
    assert math.sqrt(sum(c * c for c in out)) == pytest.approx(1.0)
    assert not [name for name in dir(col)
                if "velocity" in name.lower() or "speed" in name.lower()
                or name.lower().startswith("ev_")]


def test_the_collision_is_deterministic():
    assert len({meet(offset_in=0.3, bearing_deg=8.0, tilt_deg=-10.0)
                for _ in range(20)}) == 1


# ---- First touch ------------------------------------------------------------

def test_a_ball_struck_dead_centre_is_met_head_on():
    """The reason this is not read at closest approach. There the separation
    is perpendicular to the approach by construction, so used as the normal it
    calls every swing a glancing blow."""
    v_ball, v_bat = (0.0, -120.0, -12.0), (0.0, 100.0, 15.0)
    n = col.first_touch_normal((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), REACH_FT,
                               v_ball, v_bat)
    approach = col._unit(tuple(v_ball[i] - v_bat[i] for i in range(3)))
    assert n == pytest.approx(tuple(-c for c in approach))


def test_the_normal_turns_toward_the_side_the_ball_was_off_centre():
    """`sin(psi) = b / reach`: a quarter of the reach off centre is a normal
    14.5 degrees round, and a ball that only grazed is a quarter turn."""
    v_ball, v_bat = (0.0, -120.0, 0.0), (0.0, 0.0, 0.0)
    for share in (0.25, 0.5, 0.9, 1.0):
        n = col.first_touch_normal((0.0, 0.0, share * REACH_FT),
                                   (1.0, 0.0, 0.0), REACH_FT, v_ball, v_bat)
        assert math.degrees(math.atan2(n[2], n[1])) == pytest.approx(
            math.degrees(math.asin(share)))
        assert n[0] == pytest.approx(0.0)


def test_only_the_part_of_the_separation_across_the_approach_counts():
    """The sweep's instant is refined, not exact, and a separation taken a
    moment early or late carries a component along the ball's own line. That
    component is not an impact parameter and must not turn the normal."""
    v_ball, v_bat = (0.0, -120.0, 0.0), (0.0, 0.0, 0.0)
    clean = col.first_touch_normal((0.0, 0.0, 0.05), (1.0, 0.0, 0.0),
                                   REACH_FT, v_ball, v_bat)
    early = col.first_touch_normal((0.0, 0.08, 0.05), (1.0, 0.0, 0.0),
                                   REACH_FT, v_ball, v_bat)
    assert early == pytest.approx(clean)


def test_a_bat_is_a_cylinder_along_its_length_and_a_sphere_at_its_end():
    """Along the barrel the normal cannot point along the bat. Off the rounded
    end it can, which is what sends a ball caught off the tip sideways."""
    v_ball, v_bat = (0.0, -120.0, 0.0), (0.0, 0.0, 0.0)
    axis, off = (1.0, 0.0, 0.0), (0.1, 0.0, 0.03)
    side = col.first_touch_normal(off, axis, REACH_FT, v_ball, v_bat)
    cap = col.first_touch_normal(off, axis, REACH_FT, v_ball, v_bat,
                                 end_cap=True)
    assert side[0] == pytest.approx(0.0)
    assert cap[0] > 0.3


# ---- Launch angle -----------------------------------------------------------

@pytest.mark.parametrize("hand", HANDS)
def test_a_square_level_bat_turns_a_vertical_offset_into_launch_and_no_spray(hand):
    """The two readings separate cleanly only here, on a bat with no bearing
    and no tilt. Getting further under the ball sends it higher, monotonically,
    and never sideways."""
    launches = []
    for offset in (-1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5):
        deg, launch = spray_and_launch(hand=hand, offset_in=offset)
        assert deg == pytest.approx(0.0, abs=1e-9)
        launches.append(launch)
    assert launches == sorted(launches)
    assert launches[-1] - launches[0] > 60.0


@pytest.mark.parametrize("hand", HANDS)
def test_a_ball_struck_dead_centre_leaves_near_the_swings_own_plane(hand):
    """Not a fitted intercept. The bat is rising at the attack angle and the
    pitch is falling, and the ball leaves between the two lines."""
    _, launch = spray_and_launch(hand=hand)
    assert 4.0 < launch < bp.ATTACK_ANGLE_DEG + 2.0


@pytest.mark.parametrize("hand", HANDS)
def test_a_bat_over_the_ball_never_produces_a_fly_ball(hand):
    """The guarantee the bounded jitter used to exist to protect, and it needs
    no jitter bound now because there is no jitter. Swept over every bat a
    swing can present and every pitch it can meet."""
    from strikefactor.gameplay import ball_flight
    for offset in (0.0, -0.1, -0.5, -1.0, -2.0, -2.7):
        for bearing in (-25.0, 0.0, 30.0):
            for tilt in (-35.0, -10.0, 15.0):
                for descent in (4.0, 8.0, 12.0):
                    _, launch = spray_and_launch(
                        hand=hand, offset_in=offset, bearing_deg=bearing,
                        tilt_deg=tilt, descent_deg=descent)
                    shape = ball_flight.shape_for_launch_angle(launch)
                    assert shape in ("GROUNDER", "LINER"), (
                        f"bat {-offset} in over the ball launched at "
                        f"{launch:+.1f} deg ({shape})")
                    if offset <= -0.5:
                        assert shape == "GROUNDER"


@pytest.mark.parametrize("hand", HANDS)
def test_getting_well_under_the_ball_pops_it_up(hand):
    from strikefactor.gameplay import ball_flight
    _, launch = spray_and_launch(hand=hand, offset_in=1.6)
    assert ball_flight.shape_for_launch_angle(launch) == "POP_UP"


# ---- Spray ------------------------------------------------------------------

@pytest.mark.parametrize("hand", HANDS)
def test_the_ball_leaves_further_round_than_the_bat_faces(hand):
    """The physical content of the gain `spray` used to carry. The pitch's
    motion along the barrel is partly kept, so the ball leaves about 1.6 times
    as far round as the bat has turned — measured as a ratio, both ways."""
    for bearing in (-20.0, -8.0, 6.0, 15.0, 30.0):
        deg, _ = spray_and_launch(hand=hand, bearing_deg=bearing)
        assert 1.3 < deg / bearing < 1.9, (
            f"bat {bearing:+.0f} deg sent the ball {deg:+.1f}")


@pytest.mark.parametrize("hand", HANDS)
def test_a_barrel_down_bat_sends_an_undercut_ball_the_other_way(hand):
    """The interaction two separate models could not produce. On a bat tilted
    barrel-down, the face under the ball points away from the pull side, so
    getting under it also turns it toward the opposite field — and getting on
    top of it pulls it."""
    under, _ = spray_and_launch(hand=hand, offset_in=1.0, tilt_deg=-25.0)
    centre, _ = spray_and_launch(hand=hand, offset_in=0.0, tilt_deg=-25.0)
    over, _ = spray_and_launch(hand=hand, offset_in=-1.0, tilt_deg=-25.0)
    assert under < centre < over
    assert centre - under > 8.0
    assert over - centre > 8.0


def test_the_two_batters_are_mirror_images():
    """Same collision relative to each batter, same pull-positive direction."""
    for kw in (dict(offset_in=0.4, bearing_deg=12.0, tilt_deg=-15.0),
               dict(offset_in=-0.7, bearing_deg=-9.0, tilt_deg=8.0),
               dict(offset_in=1.2, bearing_deg=25.0, tilt_deg=-30.0)):
        assert meet(hand="L", **kw) == pytest.approx(meet(hand="R", **kw))


def test_reading_the_vector_is_pull_positive_and_up_positive():
    assert col.spray_deg((1.0, 1.0, 0.0)) == pytest.approx(45.0)
    assert col.spray_deg((-1.0, 1.0, 0.0)) == pytest.approx(-45.0)
    assert col.spray_deg((0.0, 1.0, 0.0)) == 0.0
    assert col.launch_deg((0.0, 1.0, 1.0)) == pytest.approx(45.0)
    assert col.launch_deg((0.0, 1.0, -1.0)) == pytest.approx(-45.0)
    # Straight up has no bearing; it must not raise or return a NaN.
    assert col.spray_deg((0.0, 0.0, 1.0)) == 0.0
    assert col.launch_deg((0.0, 0.0, 1.0)) == pytest.approx(90.0)


# ---- A bat that is not swung --------------------------------------------------

def test_a_stationary_bat_sends_the_ball_back_on_the_mirror_side():
    """A bunt. Met square, the ball comes straight back along the normal. Met
    at an angle it leaves on the far side of the normal from where it came in,
    in the plane it arrived in — and *more* glancing than a mirror would send
    it, because the bat takes most of the normal speed (`q`) and little of the
    sliding speed. That is the limiting case of the ball leaving further round
    than the bat faces."""
    axis, still = (1.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    back = col.exit_direction((0.0, 0.0, 0.0), axis, REACH_FT,
                              (0.0, -100.0, 0.0), still)
    assert back == pytest.approx((0.0, 1.0, 0.0))

    v_ball = (0.0, -100.0, 0.0)
    for incidence in (10.0, 25.0, 40.0):
        rad = math.radians(incidence)
        # A ball passing `sin(incidence)` of the reach above the axis meets a
        # surface whose normal is `incidence` round from the ball's own line.
        separation = (0.0, 0.0, REACH_FT * math.sin(rad))
        n = col.first_touch_normal(separation, axis, REACH_FT, v_ball, still)
        assert n == pytest.approx((0.0, math.cos(rad), math.sin(rad)))

        out = col.exit_direction(separation, axis, REACH_FT, v_ball, still)
        assert out[0] == pytest.approx(0.0), "left the plane it arrived in"
        assert sum(out[i] * n[i] for i in range(3)) > 0.0, (
            "did not come back off the bat")
        # Measured from the normal, away from the side the ball came in on.
        leaving = math.degrees(math.atan2(out[2], out[1])) - incidence
        assert leaving > incidence, "a bat is not a mirror"
        expected = math.degrees(math.atan(
            col.TANGENTIAL_KEEP * math.tan(rad) / col.COLLISION_EFFICIENCY))
        assert leaving == pytest.approx(expected, abs=1e-6)


def test_the_two_constants_are_physics_and_stay_where_measurement_put_them():
    """`q` is the collision efficiency in `EV = q * pitch + (1 + q) * bat`;
    `keep` is a sphere that leaves rolling. Neither is a calibration dial, and
    a rate that needs moving has to be moved somewhere else."""
    assert col.COLLISION_EFFICIENCY == pytest.approx(0.20)
    assert col.TANGENTIAL_KEEP == pytest.approx(5.0 / 7.0)
