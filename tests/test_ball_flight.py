"""How long a batted ball is in the air, and how far it gets.

The animation had no flight-time model at all. Duration was
`HIT_BASE_DURATION_MS * (1.2 - 0.4 * quality)` — a presentation value keyed
off contact quality, which made *harder* contact fly for a *shorter* time.
That is right for a grounder and backwards for a fly ball, and it was the
single largest distortion in the fielding sim: deep flies were given the
least hang time, so nobody could run them down, and fly-ball BABIP came out
.425 against an MLB .120.

These guard the two properties that fixes it — hang time rises with
distance, and carry falls off with exit velocity the way drag makes it —
plus the calibration points behind each.
"""

import math

import pytest

from strikefactor.gameplay import ball_flight as bf

SHAPES = ("LINER", "FLY", "POP_UP")


# ---- Hang time -------------------------------------------------------------

@pytest.mark.parametrize("shape", SHAPES)
def test_hang_time_rises_with_distance(shape):
    """The inversion that broke fly balls, stated directly. A ball hit
    farther is in the air longer — always, for every airborne shape."""
    times = [bf.hang_time_s(shape, d) for d in range(60, 420, 20)]
    assert times == sorted(times)
    assert times[-1] > times[0]


@pytest.mark.parametrize("distance_ft,lo,hi", [
    (165, 2.7, 3.4),      # shallow bloop
    (300, 3.8, 4.4),      # routine fly
    (400, 4.3, 5.1),      # warning track
])
def test_fly_hang_time_matches_real_hang_times(distance_ft, lo, hi):
    assert lo <= bf.hang_time_s("FLY", distance_ft) <= hi


def test_a_pop_up_hangs_far_longer_than_a_liner_of_the_same_length():
    """Launch angle, not distance, is what separates the shapes — a 120 ft
    pop-up is in the air about twice as long as a 120 ft liner."""
    assert bf.hang_time_s("POP_UP", 120) > 2 * bf.hang_time_s("LINER", 120)


def test_flight_time_is_bounded():
    """A pathological input must not stall the play or produce a
    zero-length animation."""
    for shape in SHAPES + ("GROUNDER",):
        for d in (-50, 0, 1e6):
            t = bf.flight_time_s(shape, 90.0, d)
            assert bf.MIN_FLIGHT_S <= t <= bf.MAX_FLIGHT_S


# ---- Ground balls ----------------------------------------------------------

def test_ground_balls_are_not_projectiles():
    """A grounder's clock comes from the retention curve in
    `infield_timing`, not from the launch-angle identity — so the ball the
    viewer watches reach the shortstop is the ball the verdict was computed
    against."""
    from strikefactor.gameplay import infield_timing

    for ev, d in ((95, 140), (45, 110), (70, 90)):
        assert bf.flight_time_s("GROUNDER", ev, d) == pytest.approx(
            infield_timing.ball_travel_time_s(ev, d), rel=1e-6)


@pytest.mark.parametrize("ev,distance_ft,lo,hi", [
    (95, 140, 1.3, 1.5),      # scorched, to a normally-positioned IF
    (45, 110, 2.5, 3.5),      # topped chopper down the line
])
def test_ground_ball_travel_matches_the_reference_table(ev, distance_ft, lo, hi):
    assert lo <= bf.flight_time_s("GROUNDER", ev, distance_ft) <= hi


# ---- Carry -----------------------------------------------------------------

@pytest.mark.parametrize("shape", SHAPES)
def test_carry_rises_with_exit_velocity(shape):
    carries = [bf.carry_distance_ft(shape, ev) for ev in range(50, 120, 5)]
    assert carries == sorted(carries)


@pytest.mark.parametrize("ev,lo,hi", [
    (90, 275, 315),       # ~295 ft
    (100, 340, 385),      # ~365 ft
    (110, 395, 440),      # ~420 ft
])
def test_fly_carry_matches_statcast(ev, lo, hi):
    assert lo <= bf.carry_distance_ft("FLY", ev) <= hi


@pytest.mark.parametrize("ev,lo,hi", [
    (80, 150, 185),       # ~165 ft
    (95, 205, 240),       # ~225 ft
    (110, 260, 300),      # ~280 ft
])
def test_liner_carry_matches_statcast(ev, lo, hi):
    assert lo <= bf.carry_distance_ft("LINER", ev) <= hi


def test_drag_grows_with_speed_so_carry_is_sublinear_in_the_vacuum_solution():
    """The detail that mattered most. Drag force goes as v², so the
    fraction of the vacuum range a real ball keeps *shrinks* the harder it
    is hit. Held constant at the value fitting a 90 mph fly, a 109 mph fly
    got 456 ft against a real ~415 — and since anything reaching the fence
    becomes a wall ball and therefore at minimum a double, that alone put
    28.6% of fly balls off the wall.
    """
    def vacuum_ratio(ev):
        v = ev * 5280.0 / 3600.0
        angle = math.radians(bf.LAUNCH_ANGLE_DEG["FLY"])
        return bf.carry_distance_ft("FLY", ev) / (
            v * v * math.sin(2 * angle) / bf.G_FT_S2)

    assert vacuum_ratio(110) < vacuum_ratio(95) < vacuum_ratio(80) + 1e-9


def test_carry_and_hang_time_come_from_the_same_flight():
    """A ball given a carry has to be given the hang time that goes with
    that carry. Two independent models here is how the animation ended up
    showing a 400 ft fly with 2.7 s of hang."""
    for ev in (75, 90, 105):
        d = bf.carry_distance_ft("FLY", ev)
        t = bf.flight_time_s("FLY", ev, d)
        # Vertical launch component implied by the hang time should land
        # in the right neighbourhood for a fly ball (~40-80 ft/s up).
        implied_v_up = t * bf.G_FT_S2 / 2.0
        assert 40.0 <= implied_v_up <= 90.0
