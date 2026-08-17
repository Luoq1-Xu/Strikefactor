"""What a batted ball does after it lands.

The reported bug: a ball hit to the outfield landed, lost most of its
speed instantly, took a few quick hops in place and stopped. Real balls
take a big first hop, carry their speed through it, and then roll a long
way while slowly bleeding off.

These pin the three things that were wrong — the landing speed, the
bounce, and friction running while the ball was in the air — plus the
distribution the whole thing has to keep producing on the other end.
"""

import math

import pytest

from strikefactor.gameplay import ball_flight, ground_roll, infield_timing
from strikefactor.gameplay import hit_animation as ha

AIRBORNE = ("LINER", "FLY", "POP_UP")


def _landing(shape, ev_mph):
    dist = ball_flight.carry_distance_ft(shape, ev_mph)
    hang = ball_flight.hang_time_s(shape, dist)
    return dist, ground_roll.landing_speed_fts(shape, ev_mph, dist, hang)


# ---- Landing ---------------------------------------------------------------

def test_every_batted_ball_lands_at_about_terminal_velocity():
    """The fact the module is built on. Integrating a drag trajectory over
    the launch grid puts landing speed at 46-59 mph for everything from a
    60 mph liner to a 110 mph fly — exit velocity buys distance and hang
    time, and does not survive the trip as speed.

    `SHAPE_LAND_FACTOR` asserted the opposite: landing speed as a fraction
    of the flight average, so a fly ball that flew at 78 ft/s landed at 27.

    The pop-up is the one shape with real spread in it: it falls from far
    enough up to get closest to a baseball's ~95 mph free-fall terminal
    velocity, and the drag integration has it landing at 64 mph off 95 mph
    contact."""
    for shape in AIRBORNE:
        for ev in (70, 85, 100, 110):
            _, horizontal = _landing(shape, ev)
            angle = ground_roll.descent_angle_deg(shape, ev)
            speed = horizontal / math.cos(math.radians(angle))
            ceiling = 75.0 if shape == "POP_UP" else 62.0
            assert 42.0 <= speed / ground_roll.MPH_TO_FTS <= ceiling, (
                f"{shape} at {ev} mph lands at "
                f"{speed / ground_roll.MPH_TO_FTS:.0f} mph")


def test_landing_speed_is_a_large_fraction_of_the_flight_speed():
    """The reported symptom, stated as a number. A ball may not shed most
    of its speed in the frame it touches the grass."""
    for shape in AIRBORNE:
        dist, horizontal = _landing(shape, 95)
        average = dist / ball_flight.hang_time_s(shape, dist)
        assert horizontal / average >= 0.60, (
            f"{shape} keeps only {horizontal / average:.0%} of its flight speed")


def test_a_bloop_cannot_land_faster_than_it_flew():
    """Horizontal speed decays monotonically under drag, so the terminal
    figure has to yield to the flight's own average on weak contact —
    otherwise the ball speeds up on touching the grass."""
    for shape in AIRBORNE:
        for dist, hang in ((60.0, 2.5), (110.0, 3.0)):
            speed = ground_roll.landing_speed_fts(shape, 95, dist, hang)
            assert speed <= dist / hang


def test_a_line_drive_lands_shallow_and_a_fly_ball_lands_steep():
    """Landing speed barely moves between shapes; the angle ranges from 20
    to 74 degrees, and the angle is what the bounce is a function of."""
    liner = ground_roll.descent_angle_deg("LINER", 95)
    fly = ground_roll.descent_angle_deg("FLY", 95)
    popup = ground_roll.descent_angle_deg("POP_UP", 95)
    assert 15.0 < liner < 32.0
    assert liner + 15.0 < fly < 56.0
    assert fly + 15.0 < popup < 80.0


# ---- The bounce ------------------------------------------------------------

def test_the_first_bounce_takes_nearly_all_the_horizontal_loss():
    """`BOUNCE_HORIZONTAL_RETENTION = 0.96` charged every contact the same
    4%, which is the one thing a bounce model must not do — the impulse a
    contact can take is set by how hard the ball is coming *down*, and
    after the first one there is very little slip left to take."""
    for shape in ("LINER", "FLY"):
        _, speed = _landing(shape, 95)
        path = ground_roll.ground_path(shape, speed, ev_mph=95)
        assert path.hops, f"{shape} does not bounce at all"
        first = 1.0 - path.hops[0].retention
        rest = 1.0 - math.prod(h.retention for h in path.hops[1:])
        assert first > rest, (
            f"{shape}: first bounce takes {first:.0%}, the rest take {rest:.0%}")


def test_a_steep_fly_ball_checks_up_and_a_shallow_liner_skips():
    """One impulse calculation, two incidence angles. The fly ball is
    gripped by the grass and converted into topspin; the line drive slides
    across it and keeps most of what it had."""
    _, liner = _landing("LINER", 95)
    _, fly = _landing("FLY", 95)
    liner_keeps = ground_roll.ground_path("LINER", liner, ev_mph=95).hops[0].retention
    fly_keeps = ground_roll.ground_path("FLY", fly, ev_mph=95).hops[0].retention
    assert fly_keeps < liner_keeps


def test_hop_height_and_duration_come_from_one_rebound():
    """A hop is a projectile arc: `h = u^2/2g` and `T = 2u/g` are two
    consequences of one rebound speed. `BOUNCE_INITIAL_DURATION_MS = 620`
    made the first hop's air time a constant, independent of how hard the
    ball had just hit the ground."""
    for shape in AIRBORNE:
        _, speed = _landing(shape, 100)
        for hop in ground_roll.ground_path(shape, speed, ev_mph=100).hops:
            u = hop.duration_s * ground_roll.G_FT_S2 / 2.0
            assert hop.height_ft == pytest.approx(
                u * u / (2.0 * ground_roll.G_FT_S2), rel=1e-9)


def test_a_fly_ball_takes_a_real_first_hop():
    """Chest-high or better, and over a second in the air — the hop that
    carries over an infielder's head. It was a 3 px cosmetic bump."""
    _, speed = _landing("FLY", 100)
    first = ground_roll.ground_path("FLY", speed, ev_mph=100).hops[0]
    assert 3.0 <= first.height_ft <= 12.0
    assert 0.8 <= first.duration_s <= 2.0


def test_hopping_stops_and_the_ball_rolls():
    """Rebound decays geometrically, so the schedule terminates on its own
    rather than against MAX_HOPS."""
    for shape in AIRBORNE:
        _, speed = _landing(shape, 105)
        path = ground_roll.ground_path(shape, speed, ev_mph=105)
        assert len(path.hops) < ground_roll.MAX_HOPS
        assert path.hops[-1].height_ft >= ground_roll.MIN_HOP_HEIGHT_FT
        assert path.roll_speed_fts > 0


def test_a_grounder_gets_no_rebound():
    """It has been on the grass the whole way and its hops are already
    modelled in flight. Layering a fresh schedule on top re-bounces a ball
    that should be settling into a roll."""
    path = ground_roll.ground_path("GROUNDER", 45.0, descent_deg=0.0)
    assert path.hops == ()
    assert path.roll_speed_fts == pytest.approx(45.0)


def test_a_grounder_reaches_the_grass_at_the_speed_the_infield_model_gave_it():
    """Derived from `infield_timing`'s retention curve rather than a free
    constant, so the ball the outfielder chases is the ball the infield
    verdict was computed against."""
    for ev in (50, 70, 90, 110):
        r = infield_timing.ground_speed_retention(ev)
        assert ground_roll.grounder_landing_fraction(ev) == pytest.approx(
            max(0.0, min(1.0, (2.0 * r - 1.0) / r)))
    # Monotone in exit velocity: a scorched grounder still has something
    # left at the far end, a topped roller has stopped.
    fractions = [ground_roll.grounder_landing_fraction(ev)
                 for ev in (45, 60, 75, 90, 105)]
    assert fractions == sorted(fractions)
    assert fractions[0] < 0.2 < fractions[-1]


# ---- The roll --------------------------------------------------------------

def test_rolling_friction_is_a_real_surface_value():
    """It was 16 ft/s^2, twice the high end of real cut grass, and it had
    to be because the ball arrived at a third of its true speed."""
    assert 3.0 <= ground_roll.GRASS_ROLL_DECEL_FT_S2 <= 8.0


def test_air_drag_matters_at_the_top_of_the_roll_and_not_at_the_bottom():
    """It goes as v^2, which is the shape of correction the far tail
    needs: shortens the long rolls, leaves the slow ones alone."""
    fast = ground_roll.roll_decel_ft_s2(46.0)
    slow = ground_roll.roll_decel_ft_s2(5.0)
    assert fast > 1.5 * ground_roll.GRASS_ROLL_DECEL_FT_S2
    assert slow == pytest.approx(ground_roll.GRASS_ROLL_DECEL_FT_S2, abs=0.1)


def test_roll_distance_matches_its_own_integrator():
    """The closed form has to agree with stepping the same equation, or
    the fielder is chasing a different ball from the one being drawn."""
    for v0 in (12.0, 30.0, 55.0):
        v, dist, dt = v0, 0.0, 0.0005
        while v > ground_roll.STOPPED_SPEED_FTS:
            v -= ground_roll.roll_decel_ft_s2(v) * dt
            dist += v * dt
        assert ground_roll.roll_distance_ft(v0) == pytest.approx(dist, rel=0.02)


def test_a_ball_nobody_touches_travels_a_long_way_after_it_lands():
    """The bug, from the other end. Measured over 500 fly balls the old
    model moved the ball a median of 14 ft past its landing point; a real
    one carries into three figures, and what stops it is an outfielder."""
    for shape, low, high in (("LINER", 90.0, 220.0),
                             ("FLY", 60.0, 160.0),
                             ("POP_UP", 8.0, 60.0)):
        _, speed = _landing(shape, 95)
        travelled = ground_roll.ground_path(
            shape, speed, ev_mph=95).total_distance_ft
        assert low <= travelled <= high, (
            f"{shape} travels {travelled:.0f} ft after landing")


def test_the_trajectory_agrees_with_the_distance_it_reports():
    """`trajectory` is what routes the fielder and `total_distance_ft` is
    what predicts the stop; they are the same roll seen two ways."""
    for shape in AIRBORNE:
        _, speed = _landing(shape, 100)
        path = ground_roll.ground_path(shape, speed, ev_mph=100)
        samples = ground_roll.trajectory(path)
        assert samples[-1][1] == pytest.approx(path.total_distance_ft, rel=0.05)
        assert samples[-1][0] == pytest.approx(path.total_time_s, rel=0.1)
        times = [t for t, _ in samples]
        dists = [d for _, d in samples]
        assert times == sorted(times)
        assert dists == sorted(dists)


def test_remaining_distance_shrinks_as_the_ball_works_through_its_hops():
    """Walked the way the animation walks it — each completed hop has
    already taken its bite out of the speed. This is what aims the chasing
    fielder, so it has to fall to zero rather than wander."""
    _, speed = _landing("FLY", 100)
    path = ground_roll.ground_path("FLY", speed, ev_mph=100)
    seen = []
    live = speed
    for n in range(len(path.hops) + 1):
        seen.append(ground_roll.remaining_distance_ft(path, live, n))
        if n < len(path.hops):
            live *= path.hops[n].retention
    assert seen == sorted(seen, reverse=True)
    assert seen[0] == pytest.approx(path.total_distance_ft)


# ---- The animation boundary -------------------------------------------------

class _StubBatter:
    def get_handedness(self):
        return "R"


class _StubGame:
    def __init__(self):
        self.batter = _StubBatter()


def _anim(shape, quality=0.85):
    return ha.HitAnimation(_StubGame(), outcome="IN_PLAY",
                           on_complete=lambda: None, quality=quality,
                           batted_ball_type=shape)


def test_the_ball_is_not_braked_while_it_is_in_the_air(monkeypatch):
    """Rolling friction used to run through the hop schedule, so the ball
    was being slowed by grass it was six feet above. Between contacts its
    speed must be flat."""
    monkeypatch.setattr(ha, "_pick_hit_landing",
                        lambda *a, **k: (ha.HOME[0] + 120, ha.HOME[1] - 260))
    anim = _anim("FLY")
    anim._init_ball_on_ground()
    assert anim._bounces, "a fly ball has to bounce"
    start, dur, _h, _r = anim._bounces[0]
    before = math.hypot(*anim._ball_v)
    # Step through the interior of the first hop, well clear of both
    # contacts, and confirm nothing touches the speed.
    tau = start + dur * 0.15
    while tau < start + dur * 0.85:
        anim._step_ball_on_ground(16.0, tau)
        tau += 16.0
    assert math.hypot(*anim._ball_v) == pytest.approx(before, rel=1e-9)


def test_the_hop_schedule_carries_the_real_heights_and_durations(monkeypatch):
    """The one conversion point. Feet become pixels through FT_TO_PX_Y and
    seconds become animated ms through `_anim_ms`, once each."""
    monkeypatch.setattr(ha, "_pick_hit_landing",
                        lambda *a, **k: (ha.HOME[0] + 120, ha.HOME[1] - 260))
    anim = _anim("FLY")
    anim._init_ball_on_ground()
    for hop, (_start, dur, height_px, retention) in zip(anim._ground_path.hops,
                                                        anim._bounces):
        assert dur == pytest.approx(anim._anim_ms(hop.duration_s))
        assert height_px == pytest.approx(hop.height_ft * ha.FT_TO_PX_Y)
        assert retention == hop.retention


def test_a_ball_over_a_fielders_head_is_not_in_their_glove():
    """A real first bounce clears 7 ft, so the securing check needs a
    height gate it never needed when hops were cosmetic."""
    assert 5.0 <= ha.GLOVE_REACH_FT <= 11.0
    _, speed = _landing("FLY", 100)
    assert ground_roll.ground_path(
        "FLY", speed, ev_mph=100).hops[0].height_ft < ha.GLOVE_REACH_FT * 1.6
