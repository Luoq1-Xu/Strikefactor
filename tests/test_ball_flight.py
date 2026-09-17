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
    times = [bf.hang_time_s(bf.launch_angle_for_shape(shape), d) for d in range(60, 420, 20)]
    assert times == sorted(times)
    assert times[-1] > times[0]


@pytest.mark.parametrize("distance_ft,lo,hi", [
    (165, 2.7, 3.4),      # shallow bloop
    (300, 3.8, 4.4),      # routine fly
    (400, 4.3, 5.1),      # warning track
])
def test_fly_hang_time_matches_real_hang_times(distance_ft, lo, hi):
    assert lo <= bf.hang_time_s(bf.launch_angle_for_shape("FLY"), distance_ft) <= hi


def test_a_pop_up_hangs_far_longer_than_a_liner_of_the_same_length():
    """Launch angle, not distance, is what separates the shapes — a 120 ft
    pop-up is in the air about twice as long as a 120 ft liner."""
    assert bf.hang_time_s(bf.launch_angle_for_shape("POP_UP"), 120) > 2 * bf.hang_time_s(bf.launch_angle_for_shape("LINER"), 120)


def test_flight_time_is_bounded():
    """A pathological input must not stall the play or produce a
    zero-length animation."""
    for shape in SHAPES + ("GROUNDER",):
        for d in (-50, 0, 1e6):
            t = bf.flight_time_s(bf.launch_angle_for_shape(shape), 90.0, d)
            assert bf.MIN_FLIGHT_S <= t <= bf.MAX_FLIGHT_S


# ---- Ground balls ----------------------------------------------------------

def test_ground_balls_are_not_projectiles():
    """A grounder's clock comes from the retention curve in
    `infield_timing`, not from the launch-angle identity — so the ball the
    viewer watches reach the shortstop is the ball the verdict was computed
    against."""
    from strikefactor.gameplay import infield_timing

    for ev, d in ((95, 140), (45, 110), (70, 90)):
        assert bf.flight_time_s(bf.launch_angle_for_shape("GROUNDER"), ev, d) == pytest.approx(
            infield_timing.ball_travel_time_s(ev, d), rel=1e-6)


@pytest.mark.parametrize("ev,distance_ft,lo,hi", [
    (95, 140, 1.3, 1.5),      # scorched, to a normally-positioned IF
    (45, 110, 2.5, 3.5),      # topped chopper down the line
])
def test_ground_ball_travel_matches_the_reference_table(ev, distance_ft, lo, hi):
    assert lo <= bf.flight_time_s(bf.launch_angle_for_shape("GROUNDER"), ev, distance_ft) <= hi


# ---- Carry -----------------------------------------------------------------

@pytest.mark.parametrize("shape", SHAPES)
def test_carry_rises_with_exit_velocity(shape):
    carries = [bf.carry_distance_ft(bf.launch_angle_for_shape(shape), ev) for ev in range(50, 120, 5)]
    assert carries == sorted(carries)


# Re-derived when `DRAG_RANGE_ANCHORS` was fitted to a trajectory carrying
# *lift*. The old bands came off a no-lift integration and ran about 15% short
# at line-drive angles: a 100 mph fly was pinned at ~365 ft against a real ~400,
# and a 100 mph line drive at ~241 against a real ~280. Nobody saw it because
# `hit_animation` clamped every landing into a per-shape range that happened to
# compensate — see the note over `DRAG_RANGE_ANCHORS`.
@pytest.mark.parametrize("ev,lo,hi", [
    (90, 330, 375),       # ~352 ft
    (100, 380, 425),      # ~403 ft
    (110, 425, 475),      # ~450 ft
])
def test_fly_carry_matches_statcast(ev, lo, hi):
    assert lo <= bf.carry_distance_ft(bf.launch_angle_for_shape("FLY"), ev) <= hi


@pytest.mark.parametrize("ev,lo,hi", [
    (80, 175, 215),       # ~194 ft
    (95, 235, 280),       # ~258 ft
    (110, 300, 350),      # ~326 ft
])
def test_liner_carry_matches_statcast(ev, lo, hi):
    assert lo <= bf.carry_distance_ft(bf.launch_angle_for_shape("LINER"), ev) <= hi


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
        return bf.carry_distance_ft(bf.launch_angle_for_shape("FLY"), ev) / (
            v * v * math.sin(2 * angle) / bf.G_FT_S2)

    assert vacuum_ratio(110) < vacuum_ratio(95) < vacuum_ratio(80) + 1e-9


def test_carry_and_hang_time_come_from_the_same_flight():
    """A ball given a carry has to be given the hang time that goes with
    that carry. Two independent models here is how the animation ended up
    showing a 400 ft fly with 2.7 s of hang."""
    for ev in (75, 90, 105):
        d = bf.carry_distance_ft(bf.launch_angle_for_shape("FLY"), ev)
        t = bf.flight_time_s(bf.launch_angle_for_shape("FLY"), ev, d)
        # Vertical launch component implied by the hang time should land
        # in the right neighbourhood for a fly ball (~40-80 ft/s up).
        implied_v_up = t * bf.G_FT_S2 / 2.0
        assert 40.0 <= implied_v_up <= 90.0


# ---- The flight is continuous in the launch angle --------------------------
#
# The headline property of the continuous model, and the one nothing guarded
# while the flight was a per-shape table lookup.

# Only the *airborne* edges. The GROUNDER/LINER boundary at 10 degrees is a
# genuine discontinuity and is supposed to be one: below it the ball is not a
# projectile at all and `flight_time_s` hands over to `infield_timing`'s
# retention curve, which is a different model of a different thing.
@pytest.mark.parametrize("edge", [b[0] for b in bf.SHAPE_LAUNCH_BANDS
                                  if b[0] > bf.GROUND_BAND_EDGE_DEG])
@pytest.mark.parametrize("ev", [80.0, 100.0, 112.0])
def test_no_cliff_at_an_airborne_band_edge(edge, ev):
    """A tenth of a degree either side of a band edge is a tenth of a degree.

    The defect this replaced: `carry_distance_ft` and `hang_time_s` took the
    *shape* and looked up its band's centre, so crossing an edge jumped the
    flight from one centre to the next. Measured at 100 mph across the
    LINER/FLY edge that was **116 ft of carry and 2.25 s of hang time**, bought
    by a fifth of an inch of bat position — well inside this model's own
    `LAUNCH_JITTER_DEG`.
    """
    lo, hi = edge - 0.1, edge + 0.1
    assert bf.shape_for_launch_angle(lo) != bf.shape_for_launch_angle(hi), (
        "the two sides of this edge are the same shape; the test is not "
        "measuring what it thinks it is")
    carry_lo, carry_hi = bf.carry_distance_ft(lo, ev), bf.carry_distance_ft(hi, ev)
    assert abs(carry_hi - carry_lo) < 5.0, (
        f"{carry_lo:.0f} -> {carry_hi:.0f} ft across the {edge} deg edge")
    hang_lo = bf.flight_time_s(lo, ev, carry_lo)
    hang_hi = bf.flight_time_s(hi, ev, carry_hi)
    assert abs(hang_hi - hang_lo) < 0.35, (
        f"{hang_lo:.2f} -> {hang_hi:.2f} s across the {edge} deg edge")


def test_a_caller_with_only_a_shape_gets_the_band_centre():
    """The bridge for legacy callers, and the reason they saw no change.

    `launch_angle_for_shape` is what the per-shape tables used to look up, so
    anything still passing a shape (the harness, older tests) flies exactly the
    flight it flew before the angle was carried.
    """
    assert bf.launch_angle_for_shape("LINER") == bf.LAUNCH_ANGLE_DEG["LINER"]
    assert bf.launch_angle_for_shape("FLY") == bf.LAUNCH_ANGLE_DEG["FLY"]
    assert bf.launch_angle_for_shape("POP_UP") == bf.LAUNCH_ANGLE_DEG["POP_UP"]
    assert bf.launch_angle_for_shape("GROUNDER") == bf.GROUNDER_NOMINAL_LAUNCH_DEG
    # Total, like `defense.profile_for` — an unrecognised shape is a fly ball
    # rather than a crash on the path that decides a batted ball.
    assert bf.launch_angle_for_shape("nonsense") == bf.LAUNCH_ANGLE_DEG["FLY"]


def test_the_drag_anchors_reproduce_their_fitted_carries():
    """Each anchor row's comment states its carry at 100 mph. Pin them.

    These are the whole table in one column, and they are what
    `tests/test_ball_flight.py::test_fly_carry_matches_statcast` and the
    home-run distribution ultimately rest on.
    """
    # The tolerance is a few feet rather than exact because each row's
    # `(base, knee, slope)` is a least-squares fit across 75-115 mph and is not
    # pinned to pass through 100 exactly.
    expected = {5: 114, 10: 215, 14: 281, 18: 332, 22: 369, 26: 392, 30: 400,
                35: 400, 40: 390, 45: 371, 50: 344, 60: 267, 68: 187, 75: 106}
    for angle, carry in expected.items():
        assert bf.carry_distance_ft(float(angle), 100.0) == pytest.approx(
            carry, abs=4.0), f"{angle} deg"


def test_height_at_the_carry_is_zero_and_negative_past_it():
    """What makes the fence verdict need no special case for ground balls.

    `height_at_distance_ft` is zero where the ball lands and negative beyond
    — the falling branch keeps going — so nothing struck at 5 degrees is
    above a fence 360 ft away.
    """
    carry = bf.carry_distance_ft(30.0, 100.0)
    assert bf.height_at_distance_ft(30.0, carry, carry) == pytest.approx(0.0, abs=1e-6)
    assert bf.height_at_distance_ft(30.0, carry, carry * 1.2) < 0.0
    assert bf.height_at_distance_ft(30.0, carry, carry * 0.5) > 0.0
    grounder = bf.carry_distance_ft(5.0, 100.0)
    assert bf.height_at_distance_ft(5.0, grounder, 360.0) < 0.0


# ---- The shape of the flight ----------------------------------------------


def test_the_apex_anchors_reproduce_the_integrated_flight():
    """`DRAG_APEX_ANCHORS` is fitted to the same drag-and-lift integration as
    `DRAG_RANGE_ANCHORS`, at 100 mph. Pin the apex it gives at a few angles,
    in feet, and where along the carry it sits.

    The vacuum parabola this replaced gave `R tan(theta) / 4` at half the
    path: 58 ft at the midpoint for a 100 mph ball at 30 degrees, where the
    real ball peaks at 89 ft, 58% of the way out. That shape was both the
    drawn arc and the fence predicate, so every home run drew as a line
    drive and needed more carry than a real one.
    """
    # The integrated apex at 100 mph. The model applies the fitted gain to
    # *its own* carry, which is within a few percent of the integration's at
    # each angle (`test_the_drag_anchors_reproduce_their_fitted_carries`), so
    # the apex inherits that tolerance.
    expected = {14: (24.8, 0.56), 22: (56.1, 0.58), 30: (89.0, 0.58),
                45: (145.1, 0.57)}
    for angle, (apex_ft, frac) in expected.items():
        carry = bf.carry_distance_ft(float(angle), 100.0)
        assert bf.apex_height_ft(float(angle), carry) == pytest.approx(
            apex_ft, rel=0.08), f"{angle} deg apex"
        # The apex really is where the profile says it is.
        samples = [(f / 200.0, bf.height_at_distance_ft(float(angle), carry,
                                                        f / 200.0 * carry))
                   for f in range(201)]
        at, peak = max(samples, key=lambda s: s[1])
        assert at == pytest.approx(frac, abs=0.02), f"{angle} deg apex frac"
        assert peak == pytest.approx(bf.apex_height_ft(float(angle), carry),
                                     rel=1e-3)


def test_the_flight_is_higher_than_the_vacuum_parabola_everywhere():
    """Drag costs a ball more range than height, so for the distance it
    actually covers it is above the vacuum ball at every point in between.
    The parabola was the shape the arc used to be drawn as; anything that
    dips under it again has brought the flat home run back."""
    for angle in (12.0, 20.0, 28.0, 36.0, 48.0):
        carry = bf.carry_distance_ft(angle, 102.0)
        for f in range(1, 100):
            d = f / 100.0 * carry
            vacuum = d * math.tan(math.radians(angle)) * (1.0 - d / carry)
            assert bf.height_at_distance_ft(angle, carry, d) > vacuum, (
                f"{angle} deg at {f}% of the carry")


def test_the_descent_is_steeper_than_the_ascent():
    """The apex sits past the midpoint of the carry, so the ball comes down
    over less ground than it went up over. A real trajectory is asymmetric
    that way; a parabola is not, and the symmetric arc is what made every
    home run glide in shallow on its last third."""
    for angle in (14.0, 22.0, 30.0, 40.0):
        _, frac = bf.apex_profile(angle)
        assert 0.54 < frac < 0.60, f"{angle} deg apex at {frac:.3f}"
        carry = bf.carry_distance_ft(angle, 100.0)
        # Height at 90% of the carry is well over a third of the apex, where
        # the vacuum parabola had it at 0.36 of the apex and falling slowly.
        near_end = bf.height_at_distance_ft(angle, carry, 0.9 * carry)
        assert near_end > 0.38 * bf.apex_height_ft(angle, carry)
