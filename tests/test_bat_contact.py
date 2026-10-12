"""The sweep of the bat against the ball.

This is the module that made contact *emergent*. Before it the engine asked
two unrelated questions — a timing gate against the ball reaching the plate,
and, only if that passed, a 120 x 50 px rectangle tested against the ball's
screen position for one frame — and neither had a depth axis. Contact depth
could not be an output of that arrangement, which is why the replay's bat had
to be modelled backwards from the pitch to obtain one.

What is guarded here is mostly that: that depth, sweet-spot fraction and
quality are all consequences of one geometric question, that they move the way
real contact moves, and that the difficulty settings still reach every part of
the verdict they used to reach.
"""

import math

import pytest

from strikefactor.gameplay import bat_contact as bc
from strikefactor.gameplay import bat_path as bp
from strikefactor.gameplay import spray
from strikefactor.utils.pitch_physics import DEFAULT_CAMERA, PitchTrajectory

UNDERCUT_IN = bc.SWING_UNDERCUT_FT * 12.0


def pitch(speed_mph=93.0, target_z=2.5, target_x=0.0):
    return PitchTrajectory.from_pitch_params(
        release_pos=(-1.8, 54.0, 6.0), speed_mph=speed_mph,
        pfx_x_inches=-4.0, pfx_z_inches=14.0,
        target_x_ft=target_x, target_z_ft=target_z)


def squared_up(trajectory, hand="R"):
    """The swing of a hitter who tracks the ball and puts the bat on it.

    The game's own path: a cursor on the ball's plate crossing, carried to the
    barrel's depth by `aim_at_pitch`. That puts the bat's axis
    `SWING_UNDERCUT_FT` under the ball's centre, which is the contact a swing
    is for: a line drive. This is the reference every timing sweep below is
    measured from.
    """
    ball = trajectory.position_at(trajectory.travel_time)
    px, py, _ = DEFAULT_CAMERA.project(ball[0], 0.0, ball[2])
    cursor = DEFAULT_CAMERA.screen_to_world_at_plate(px, py)
    return bp.swing(bc.aim_at_pitch(cursor, trajectory, hand), hand)


def swing_at(trajectory, swing, timing_ms, **kw):
    """Resolve a swing `timing_ms` off. Negative early, positive late."""
    due = trajectory.time_at_depth(swing.contact_depth_ft)
    start = due - bp.SWING_DURATION_S + timing_ms / 1000.0
    return bc.resolve_contact(swing, trajectory, start, **kw)


# The engine slides the swing by up to `timing_assist_s` before sweeping it, so
# at the default multiplier everything inside 26 ms is brought to on-time and
# the geometry is shown a perfectly timed swing. Any test about how *timing*
# reaches the bat therefore has to work in the residual — the part of the error
# the assist did not cover — and the tests below do that by asking at a
# difficulty whose budget is small. That is not a workaround: it is the model,
# and a test that swept +/-20 ms at AMATEUR and saw the ball move would mean the
# assist had stopped working.
TIGHT = dict(timing_window_mult=0.2)     # a 5 ms budget: near-bare geometry


# ---- The basic question -----------------------------------------------------

def test_a_squared_up_swing_hits_the_ball_on_the_sweet_spot():
    tr = pitch()
    got = swing_at(tr, squared_up(tr), 0.0)
    assert got is not None
    assert got.along == pytest.approx(bp.CONTACT_SWEET_SPOT_FRAC, abs=0.05)
    assert got.vertical_offset_ft * 12.0 == pytest.approx(UNDERCUT_IN, abs=0.05)
    assert got.quality > 0.96
    assert not got.is_foul()


def test_the_hardest_hit_ball_is_the_one_struck_dead_centre():
    """Quality peaks with the bat's axis on the ball's own line, which is
    half an inch *above* where a swing aims. That ball is a low liner or a
    hard grounder; the line drive a swing is for is struck a little less
    hard, and a ball lifted further still less. It is what a bat and a ball
    do, and it is what keeps fly balls from being struck as well as line
    drives."""
    tr = pitch()
    scores = {}
    for inches_high in (0.0, UNDERCUT_IN, 2.0 * UNDERCUT_IN):
        swing = bp.swing(bc.aim_at_pitch(aim_off_by(tr, inches_high), tr, "R"),
                         "R")
        scores[inches_high] = swing_at(tr, swing, 0.0)
    dead_centre = scores[UNDERCUT_IN]
    assert abs(dead_centre.vertical_offset_ft * 12.0) < 0.05
    assert dead_centre.quality > 0.999
    assert dead_centre.launch_deg < 10.0
    assert scores[0.0].quality < dead_centre.quality
    assert scores[2.0 * UNDERCUT_IN].quality == pytest.approx(
        scores[0.0].quality, abs=0.01), "the peak should be symmetric"


@pytest.mark.parametrize("timing_ms", [-200.0, -120.0, 150.0, 300.0])
def test_a_wildly_mistimed_swing_misses(timing_ms):
    tr = pitch()
    assert swing_at(tr, squared_up(tr), timing_ms) is None


def test_a_swing_aimed_somewhere_else_entirely_misses():
    """Timing is not the only way to miss, and it never was — this is the half
    the old rectangle test was for."""
    tr = pitch()
    ref = squared_up(tr)
    away = bp.swing((ref.aim_ft[0], ref.aim_ft[1] + 1.6), "R")
    assert swing_at(tr, away, 0.0) is None


# ---- The player's aim reaches the ball --------------------------------------

def cursor_on_the_ball(trajectory):
    """The cursor of a player pointing exactly at the ball's plate crossing.

    What the game asks of them: the ball is drawn all the way to the plate and
    the strike zone is drawn there too, so this is the only aim the screen
    gives them any way to express.
    """
    ball = trajectory.position_at(trajectory.travel_time)
    px, py, _ = DEFAULT_CAMERA.project(ball[0], 0.0, ball[2])
    return DEFAULT_CAMERA.screen_to_world_at_plate(px, py)


ARSENAL = {
    "four-seam":  dict(),
    "up in the zone": dict(target_z=3.2),
    "at the knees": dict(target_z=1.9),
    "inside":     dict(target_x=0.6),
    "away":       dict(target_x=-0.6),
}


@pytest.mark.parametrize("name", sorted(ARSENAL))
def test_a_perfectly_aimed_perfectly_timed_swing_squares_the_ball_up(name):
    """The property the whole difficulty ladder sits on top of, and the one
    thing that was wrong.

    `bat_path._unproject` puts the barrel on the cursor's ray at the depth the
    barrel reaches — a couple of feet in front of the plate. Nothing carried
    the *ball* out there with it, and the ball is still descending: two to
    five inches higher, against a bat and ball that are 2.75 in of tolerance
    between them. So the best a correctly-aimed, correctly-timed player could
    do was foul it off — middle-middle came out 3.2 in under the ball for a
    quality of 0.23 — and a 12-6 curveball could not be touched at all.

    `aim_at_pitch` resolves which point on the ray the cursor meant. There is
    no tolerance in this assertion on purpose: a perfect swing is perfect.

    Perfect is the bat `SWING_UNDERCUT_FT` under the ball's centre, not on it:
    that is the contact the swing is for, a line drive, where dead centre is a
    ground ball. It costs a little quality, because the hardest-hit ball is
    the one struck dead centre, and no more than that. And it holds where the
    barrel arrives *behind* the plate's front edge, which is where a pitch
    away is met.
    """
    tr = pitch(**ARSENAL[name])
    swing = bp.swing(bc.aim_at_pitch(cursor_on_the_ball(tr), tr, "R"), "R")
    got = swing_at(tr, swing, 0.0)
    assert got is not None
    assert got.quality > 0.96
    # The datum is a height at the barrel's depth, and the offset is measured
    # square to the bat, so on a bat tilted down after a low pitch the two
    # differ by the tilt's cosine squared. A fifth of an inch at most.
    assert 0.75 * UNDERCUT_IN <= got.vertical_offset_ft * 12.0 <= UNDERCUT_IN + 0.02
    assert not got.is_foul()
    # A line drive, or a degree into the next band on a pitch up in the zone,
    # where the bat is barrel-up and lifts the ball a little more.
    assert 10.0 < got.launch_deg < 28.0, "a perfect swing is a line drive"
    if name == "away":
        assert swing.contact_depth_ft < 0.0
        assert got.depth_ft < 0.0


def test_the_resolved_aim_carries_the_player_error_through_untouched():
    """It is a translation of the cursor, not a correction of it. A player who
    aims four inches high must still be four inches high — the bias removed is
    the one nothing on screen could have told them about."""
    tr = pitch()
    on_ball = cursor_on_the_ball(tr)
    high = (on_ball[0], on_ball[1] + 4.0 / 12.0)
    a = bc.aim_at_pitch(on_ball, tr, "R")
    b = bc.aim_at_pitch(high, tr, "R")
    assert b[1] - a[1] == pytest.approx(4.0 / 12.0, abs=0.01)
    assert b[0] - a[0] == pytest.approx(0.0, abs=0.01)


def test_a_breaking_ball_is_resolved_further_than_a_fastball():
    """The correction is the ball's own motion between the barrel and the
    plate, so a pitch dropping harder needs more of it. This is why the bias
    could not be a constant, and why a 12-6 curveball was the pitch it made
    unhittable."""
    fast = pitch(speed_mph=96.0)
    curve = PitchTrajectory.from_pitch_params(
        release_pos=(-1.8, 54.0, 6.0), speed_mph=79.0,
        pfx_x_inches=-4.0, pfx_z_inches=-8.0, target_x_ft=0.0, target_z_ft=2.5)
    lift = []
    for tr in (fast, curve):
        cursor = cursor_on_the_ball(tr)
        lift.append(bc.aim_at_pitch(cursor, tr, "R")[1] - cursor[1])
    assert 0.0 < lift[0] < lift[1]


def test_the_swing_still_never_sees_the_pitch():
    """`aim_at_pitch` is the seam, and it stays a seam: what it returns is an
    ordinary plate-frame aim, and `bat_path.swing` keeps its two arguments.
    A swing built from the same aim is the same swing whatever threw it."""
    a = bp.swing((0.15, 2.6), "R")
    b = bp.swing((0.15, 2.6), "R")
    for x, y in zip(a.full_track(24), b.full_track(24)):
        assert x.knob_ft == y.knob_ft
        assert x.barrel_ft == y.barrel_ft


# ---- Contact depth is an output --------------------------------------------

def test_contact_depth_moves_with_timing():
    """The question that drove this rewrite. A bat sweeping a fixed path meets
    a ball that has not arrived yet further out in front, and one that is
    already past deeper — so how early or late the swing was is *visible* in
    where the ball was struck, without anything modelling it."""
    tr = pitch()
    ref = squared_up(tr)
    depths = []
    for ms in (-15, -10, 0, 15, 30):
        got = swing_at(tr, ref, ms, **TIGHT)
        assert got is not None, f"{ms} ms should still find the ball"
        depths.append(got.depth_ft)
    assert depths == sorted(depths, reverse=True)
    assert depths[0] > depths[-1] + 1.5, "feet apart across 45 ms, not inches"
    assert depths[-1] < 0.0, "a late swing meets the ball behind the plate"


def test_contact_depth_also_moves_with_location():
    """Independently of timing. The bat is further round when it meets a pitch
    inside, so the barrel is further out in front — pulled — and behind square
    on one away, which is met at the plate's front edge or just behind it.
    Both dependencies are real and they are separate."""
    inside = pitch(target_x=0.65)
    away = pitch(target_x=-0.65)
    a = swing_at(inside, squared_up(inside), 0.0)
    b = swing_at(away, squared_up(away), 0.0)
    assert a is not None and b is not None
    assert a.depth_ft > b.depth_ft + 0.7


def test_timing_reaches_the_balls_direction_before_it_reaches_the_barrel():
    """A few milliseconds off, the ball is still on the barrel and goes
    somewhere else. That is the order a real hitter meets it in, and it is new:
    the bat used to be 49 degrees past square, so the same error slid the ball
    most of the way to the handle before it turned it at all.
    """
    tr = pitch()
    ref = squared_up(tr)
    on_time = swing_at(tr, ref, 0.0, **TIGHT)
    early = swing_at(tr, ref, -10.0, **TIGHT)     # ~5 ms left after the slide
    late = swing_at(tr, ref, 10.0, **TIGHT)
    for got in (early, late):
        assert got.quality > 0.95, "still squared up"
        assert abs(got.along - bp.CONTACT_SWEET_SPOT_FRAC) < 0.06
    assert early.spray_deg > on_time.spray_deg + 5.0, "early should pull it"
    assert late.spray_deg < on_time.spray_deg - 5.0, "late should push it"


def test_early_meets_the_ball_off_the_end_and_late_on_the_handle():
    """Where along the bat, which is what timing does to the ball once it is
    far enough off to stop being only a direction."""
    tr = pitch()
    ref = squared_up(tr)
    early = swing_at(tr, ref, -15.0, **TIGHT)
    late = swing_at(tr, ref, 20.0, **TIGHT)
    assert early.along > bp.CONTACT_SWEET_SPOT_FRAC + 0.05
    assert late.along < bp.CONTACT_SWEET_SPOT_FRAC - 0.05

    # And at a difficulty that covers 20 ms, both are slid onto the sweet spot.
    # The assist is meant to be visible here: this is what it buys.
    for ms in (-20.0, 20.0):
        helped = swing_at(tr, ref, ms)
        assert helped.along == pytest.approx(
            bp.CONTACT_SWEET_SPOT_FRAC, abs=0.01)
        assert helped.shift_s == pytest.approx(-ms / 1000.0, abs=1e-4)


# ---- The exit direction -----------------------------------------------------

@pytest.mark.parametrize("hand", ["R", "L"])
def test_the_exit_direction_is_stamped_once_and_both_angles_read_it(hand):
    """One collision, one vector, two readings.

    `resolve_contact` asks `bat_ball_collision` once and carries the answer.
    `spray_deg` and `launch_deg` are that vector's bearing and elevation, so
    they cannot describe two different balls.
    """
    side = spray.spin_for(hand)
    tr = PitchTrajectory.from_pitch_params(
        release_pos=(-1.8 * side, 54.0, 6.0), speed_mph=93.0,
        pfx_x_inches=-4.0 * side, pfx_z_inches=14.0,
        target_x_ft=0.2 * side, target_z_ft=2.5)
    got = swing_at(tr, squared_up(tr, hand), 8.0, **TIGHT)
    x, y, z = got.exit_direction
    assert math.sqrt(x * x + y * y + z * z) == pytest.approx(1.0)
    assert got.spray_deg == pytest.approx(math.degrees(math.atan2(x, y)))
    assert got.launch_deg == pytest.approx(
        math.degrees(math.atan2(z, math.hypot(x, y))))
    assert y > 0.0, "a ball struck on the barrel goes out, not back"


def test_the_two_hands_get_the_same_exit_direction():
    """Pull-positive, so a mirrored swing at a mirrored pitch is the same
    vector to the last bit that matters."""
    got = {}
    for hand in ("R", "L"):
        side = spray.spin_for(hand)
        tr = PitchTrajectory.from_pitch_params(
            release_pos=(-1.8 * side, 54.0, 6.0), speed_mph=93.0,
            pfx_x_inches=-4.0 * side, pfx_z_inches=14.0,
            target_x_ft=0.4 * side, target_z_ft=2.1)
        got[hand] = swing_at(tr, squared_up(tr, hand), 9.0, **TIGHT)
    assert got["L"].exit_direction == pytest.approx(got["R"].exit_direction,
                                                    abs=1e-9)


def test_getting_under_the_ball_lifts_it_and_getting_over_it_tops_it():
    """The vertical half, through the real sweep. About thirty degrees of
    launch for every inch of bat position, which is what a bat and a ball do
    and nearly twice what the fitted model allowed."""
    tr = pitch()
    launches = []
    for inches_high in (1.0, 0.5, 0.0, -0.5, -1.0):
        swing = bp.swing(bc.aim_at_pitch(aim_off_by(tr, inches_high), tr, "R"),
                         "R")
        launches.append(swing_at(tr, swing, 0.0).launch_deg)
    assert launches == sorted(launches)
    per_inch = (launches[-1] - launches[0]) / 2.0
    assert 22.0 < per_inch < 40.0, f"{per_inch:.0f} deg of launch per inch"


def test_the_assisted_swing_gets_an_exit_direction_too():
    """The spatial assist sweeps a translated swing, and the bat's velocity is
    read off whichever swing was swept.

    A near miss is moved only until the surfaces touch, so what it makes is a
    foul tip: the ball is barely turned and carries on toward the backstop.
    That is why widening the contact zone turns whiffs into fouls and never
    into balls in play, and the collision says so without being told.
    """
    tr = pitch()
    swing = bp.swing(bc.aim_at_pitch(aim_off_by(tr, 4.0), tr, "R"), "R")
    got = swing_at(tr, swing, 0.0)
    assert math.hypot(*got.spatial_shift_ft) > 0.0
    assert math.sqrt(sum(c * c for c in got.exit_direction)) == pytest.approx(1.0)
    assert got.exit_direction[1] < 0.0, "a tipped ball keeps going back"
    assert spray.is_foul(got.spray_deg)
    assert got.is_foul()


# ---- Quality ----------------------------------------------------------------

def test_quality_peaks_at_dead_on_and_falls_off_both_sides():
    """Unimodal, and it took a redesign to be.

    A draft swept the ball as a capsule over the timing cushion and took the
    closest approach, which let a mistimed swing pick the instant that
    flattered it: quality dipped at dead-on and peaked at +/- 20 ms. The ball
    is where it is now; only the bat's tolerance is generous.
    """
    tr = pitch()
    ref = squared_up(tr)
    got = [(ms, swing_at(tr, ref, ms)) for ms in range(-30, 31, 2)]
    inside = [(ms, c.quality) for ms, c in got if c]
    assert len(inside) > 10
    peak_ms = max(inside, key=lambda p: p[1])[0]
    assert abs(peak_ms) <= 4, f"quality peaks at {peak_ms} ms, not at 0"
    for side in (lambda p: p[0] <= 0, lambda p: p[0] >= 0):
        run = [q for ms, q in inside if side((ms, q))]
        if side((-1, 0)):
            run = run[::-1]
        assert all(b <= a + 0.02 for a, b in zip(run, run[1:])), "not monotone"


def test_quality_preserves_the_geometric_mean_and_charges_spatial_help():
    """Along the bat, across it, and how much of the clock the swing had to be
    given — deliberately the same shape `_compute_contact_quality` used, which
    is what keeps `contact_audio.EV_CALIBRATION`'s distribution recognisable
    rather than replacing it wholesale.

    The timing term joins the mean rather than multiplying it. Multiplied on
    the outside it is a full-strength penalty on top of a mean of two, and it
    flattened the top of the distribution — the best contact available to a
    player borrowing any time at all came out near 0.89 against the 0.96 the
    anisotropic model produced, which is the end of the scale EV is anchored
    on.
    """
    tr = pitch()
    got = swing_at(tr, squared_up(tr), -8.0)
    assert got.shift_s > 0.0, "an early swing is slid later"
    assert got.timing_score < 1.0, "and charged for it"
    assert got.quality == pytest.approx(
        (got.sweet_spot_score * got.centre_score * got.timing_score
         ) ** (1 / 3) * got.spatial_score)


def test_a_swing_that_needed_no_help_is_charged_nothing():
    """The charge is for the borrowed time, so a swing that borrowed none pays
    none — which is what keeps a perfectly timed swing at exactly 1.00."""
    tr = pitch()
    got = swing_at(tr, squared_up(tr), 0.0)
    assert got.shift_s == pytest.approx(0.0, abs=1e-6)
    assert got.timing_score == pytest.approx(1.0)


def test_the_slide_never_exceeds_the_budget_and_never_overshoots():
    """Two bounds, and the model is wrong without either. Past the budget it
    would be a magnet rather than an assist; past the error it would push a
    well-timed swing *away* from the ball."""
    tr = pitch()
    ref = squared_up(tr)
    for mult in (1.5, 1.0, 0.4):
        budget = bc.timing_assist_s(mult)
        for ms in (-80, -30, -12, -3, 0, 3, 12, 30, 80):
            got = swing_at(tr, ref, ms, timing_window_mult=mult)
            if got is None:
                continue
            assert abs(got.shift_s) <= budget + 1e-9
            assert abs(got.shift_s) <= abs(ms) / 1000.0 + 1e-9
            if ms:
                assert got.shift_s * ms <= 0.0, "slid toward on-time"


def test_the_physical_contact_and_spatial_assist_are_real_sized():
    """The physical solid stays a bat and ball; difficulty moves that bat."""
    solid_in = (bp.bat_radius_ft(bp.CONTACT_SWEET_SPOT_FRAC)
                + bc.BALL_RADIUS_FT) * 12.0
    assert 2.4 < solid_in < 3.1, "a bat and a ball, in inches"
    assists = [bc.spatial_assist_ft(mult) for mult in (1.4, 1.0, 0.7)]
    assert assists == sorted(assists, reverse=True)
    assert all(0.0 < value < 0.5 for value in assists)


# ---- Difficulty -------------------------------------------------------------

DIFFICULTIES = [("ROOKIE", 1.4, 1.5), ("AMATEUR", 1.0, 1.0), ("PRO", 0.9, 0.8),
                ("ALL_STAR", 0.8, 0.6), ("HALL_OF_FAME", 0.7, 0.4)]


def test_difficulty_narrows_both_touching_the_ball_and_squaring_it_up():
    """It has to reach both. The tolerances decide whether the bat found the
    ball at all; without `foul_threshold` moving too, a harder setting would
    only convert fair contact into fouls at the edges and leave squaring it up
    exactly as easy — which is not what `contact_timing_window` has ever
    meant, since it scaled the perfect and foul windows together."""
    tr = pitch()
    ref = squared_up(tr)
    windows, fair = [], []
    for _, zone, window in DIFFICULTIES:
        got = [swing_at(tr, ref, ms, zone_size_mult=zone,
                        timing_window_mult=window)
               for ms in range(-90, 91)]
        hits = [c for c in got if c]
        windows.append(len(hits))
        fair.append(sum(1 for c in hits if not c.is_foul(bc.foul_threshold(window))))
    assert windows == sorted(windows, reverse=True), windows
    assert fair == sorted(fair, reverse=True), fair
    assert windows[0] > windows[-1] * 1.5


def test_the_charge_is_never_narrower_than_the_budget_it_charges_for():
    """The invariant behind `timing_charge_sigma_s`, stated directly.

    `TIMING_CHARGE_SIGMA_FLOOR_S` was calibrated at one difficulty and applied
    to all five. Because the charge is a Gaussian in the slide while
    `timing_assist_s` runs 39 ms down to 10, a fixed 20 ms width meant the
    easier the setting the deeper it could dig.
    """
    for _, _, window in DIFFICULTIES:
        assert bc.timing_charge_sigma_s(window) >= bc.timing_assist_s(window)
    # And the floor still binds where the budget is inside it, so the hard end
    # is exactly as it was calibrated.
    assert bc.timing_charge_sigma_s(0.4) == bc.TIMING_CHARGE_SIGMA_FLOOR_S


def test_an_easier_difficulty_never_charges_a_full_budget_swing_more():
    """The inversion this fixes, measured the way a player meets it.

    A swing that spends its whole timing allowance is the *common* case at the
    easy end — about 45% of AMATEUR contacts sat at full saturation — and
    before the fix it was charged against a width narrower than the allowance
    itself. The result ran backwards down the ladder: a full-budget swing was
    capped at quality 0.531 at ROOKIE against 0.956 at HALL OF FAME, and after
    the foul threshold moved with it that left ROOKIE **1.72 in** of vertical
    aim room against 2.06 at AMATEUR and 2.13 at ALL STAR. The easiest setting
    was the strictest one on the ladder for a mistimed swing, which is the
    mechanism behind "even on rookie it is all foul balls" — difficulty was
    converting whiffs into fouls rather than into balls in play.

    Ordered rather than pinned to values: what must never come back is the
    *inversion*, and any future recalibration of the charge is free to move
    the numbers.
    """
    tr = pitch()
    ref = squared_up(tr)
    floors = []
    for name, zone, window in DIFFICULTIES:
        budget = bc.timing_assist_s(window)
        # Late by exactly the budget, so the slide is spent in full.
        got = swing_at(tr, ref, budget * 1000.0, zone_size_mult=zone,
                       timing_window_mult=window)
        assert got is not None, f"{name}: a full-budget swing must reach"
        assert got.shift_s == pytest.approx(-budget, abs=1e-9), name
        floors.append((name, got.timing_score))
    # Non-decreasing toward the hard end. Tolerant because the three easy
    # rungs now tie exactly — their budget *is* their charge width, so all
    # three floor at exp(-1/2) — and an exact `sorted` comparison turns the
    # last bit of that tie into a failure.
    for (easier, lo), (harder, hi) in zip(floors, floors[1:]):
        assert lo <= hi + 1e-9, f"{easier} charges more than {harder}: {floors}"
    # The easy end is where it was inverted, so pin that pair explicitly.
    assert floors[0][1] == pytest.approx(floors[1][1]), floors[:2]


def test_a_power_swing_is_harder_than_a_contact_swing():
    """It always has been — the old rectangle was 50 px tall on a W swing and
    25 on an E. Most of the difference comes free from `power_timing_window`
    being tighter, and `POWER_MARGIN_FT` is the part that does not, so power
    stays harder even at the difficulty where the two windows agree."""
    tr = pitch()
    ref = squared_up(tr)
    contact = [swing_at(tr, ref, ms) for ms in range(-90, 91)]
    power = [swing_at(tr, ref, ms, power=True) for ms in range(-90, 91)]
    assert sum(c is not None for c in power) < sum(c is not None for c in contact)


# ---- The sweep itself -------------------------------------------------------

def test_the_contact_instant_is_stable_under_refinement():
    """The coarse walk is 1 ms and the bat covers about 1.3 in in that time,
    which is half a ball — so the reported instant has to come from the
    refinement, not from the nearest sample."""
    tr = pitch()
    ref = squared_up(tr)
    # Outside the timing assist, so the authored 150 ms contact pose is not
    # the true minimum and the refinement has a non-integral instant to find.
    got = swing_at(tr, ref, -27.0)
    ms = got.swing_t_s * 1000.0
    assert abs(ms - round(ms)) > 1e-6, "landed exactly on a coarse sample"
    # And the ball reported is the ball at the instant reported.
    assert got.ball_ft == tr.position_at(got.pitch_t_s)


def test_the_follow_through_is_swept_too():
    """A swing that arrived early is still moving when the ball gets there.

    Early is the direction that needs it: the bat got to its contact pose
    first, so the ball only reaches it *after* that instant, out in the
    follow-through. `bat_path` is defined past contact precisely so this can
    see it — without that stretch every early swing would become a whiff the
    moment the barrel arrived. (Late swings go the other way, meeting the ball
    on the way in, and never need it.)
    """
    tr = pitch()
    ref = squared_up(tr)
    budget_ms = bc.timing_assist_s(1.0) * 1000.0
    # Only the part of the error the assist did not cover can put the ball out
    # in the follow-through; inside the budget the swing is slid onto it.
    early = [(ms, swing_at(tr, ref, ms)) for ms in range(-90, -4)]
    after = [(ms, c) for ms, c in early
             if c and c.swing_t_s > bp.SWING_DURATION_S + 1e-6
             # A residual of a millisecond or two is inches, not the
             # feet this is about; ask for one worth measuring.
             and ms + budget_ms < -4.0]
    assert after, "nothing was ever met during the follow-through"
    # And the ball those met is genuinely still out in front of where the
    # barrel arrived, which is what being early means.
    assert all(c.depth_ft > ref.contact_depth_ft + 0.25 for _, c in after)

    # Late swings never get there. (A tenth of a millisecond of slack: the
    # bat's axis passes under the ball's centre by design, so the two are
    # nearest a hair after the authored pose and not exactly at it.)
    late = [swing_at(tr, ref, ms) for ms in range(5, 91)]
    assert all(c.swing_t_s <= bp.SWING_DURATION_S + 1e-4 for c in late if c)


def test_the_bat_is_tapered_and_the_sweep_can_tell():
    """A uniform cylinder would make a handle hit indistinguishable from a
    barrel one, and quality would collapse onto the vertical offset alone."""
    assert bp.bat_radius_ft(0.2) < 0.5 * bp.bat_radius_ft(1.0)
    tr = pitch()
    ref = squared_up(tr)
    got = [swing_at(tr, ref, ms, **TIGHT) for ms in range(-20, 31, 5)]
    alongs = [c.along for c in got if c]
    assert max(alongs) - min(alongs) > 0.15


def test_contact_is_reported_in_feet_and_seconds():
    """The module contract, and the reason it can be tested without a mixer,
    a display or a game — same as `ball_flight` and `ground_roll`."""
    import inspect
    imports = [line for line in inspect.getsource(bc).splitlines()
               if line.startswith(("import ", "from "))]
    assert not [line for line in imports if "pygame" in line]
    assert not [line for line in imports if "strikefactor.ui" in line]
    tr = pitch()
    got = swing_at(tr, squared_up(tr), 0.0)
    assert 0.0 < got.swing_t_s < bp.TOTAL_DURATION_S
    assert -2.0 < got.depth_ft < 6.0
    assert 60.0 < got.bat_speed_mph < 80.0


def test_the_sweep_is_cheap_enough_to_run_on_an_input_frame():
    """It resolves once, on the frame the player presses the key.

    A first draft walked 33 stations at every one of 221 time samples and took
    12 ms a swing — most of a frame, spent at the exact moment the game is
    reading the player. Solving the closest point instead of walking to it
    brought that under 3 ms *and* made it more accurate, since the walk landed
    the sweet-spot fraction 0.19 out on average. The bound here is loose on
    purpose: it is guarding against the order of magnitude coming back, not
    policing a millisecond on someone else's machine.
    """
    import time
    tr = pitch()
    ref = squared_up(tr)
    swing_at(tr, ref, 0.0)          # warm
    start = time.perf_counter()
    for ms in range(-10, 10):
        swing_at(tr, ref, float(ms))
    per_call_ms = (time.perf_counter() - start) / 20.0 * 1000.0
    assert per_call_ms < 25.0, f"{per_call_ms:.1f} ms per swing"


# ---- The in-swing aim assist ------------------------------------------------
#
# The pre-build aim assist pulls a difficulty-scaled fraction of the player's
# own aim error out before the swing is built. It is tested separately from the
# bounded rigid correction applied to a near miss during contact resolution.
#
# It exists because contact was measurably out of reach. Recorded play on the
# build before it — 222 swings at AMATEUR — whiffed 79% of the time against
# MLB's 24%, and the cause was a vertical cliff: the old margin at 1.0 was
# 0.0, so the player had to place a mouse cursor inside the real 2.75 in a bat
# and a ball are between them.

# The ladder in `settings_manager.get_difficulty_multipliers`, restated so this
# module can be tested without a settings file — same contract as `DIFFICULTIES`
# above, and a test below pins it to the real table.
AIM_ASSIST = [("ROOKIE", 0.90), ("AMATEUR", 0.88), ("PROFESSIONAL", 0.50),
              ("ALL_STAR", 0.35), ("HALL_OF_FAME", 0.20)]


def aim_off_by(trajectory, inches_high, across_in=0.0):
    """The cursor of a player whose aim is off by a stated amount."""
    on_ball = cursor_on_the_ball(trajectory)
    return (on_ball[0] + across_in / 12.0, on_ball[1] + inches_high / 12.0)


def miss_inches(trajectory, cursor, assist):
    """How far the resolved aim still sits from where a perfect one would put
    the bat, in inches.

    Measured where it matters — at the barrel's own depth, which is what
    `aim_at_pitch` resolves against — rather than at the plate, and against
    the swing's datum: `SWING_UNDERCUT_FT` under the ball's centre.
    """
    aim = bc.aim_at_pitch(cursor, trajectory, "R", assist=assist)
    swing = bp.swing(aim, "R")
    depth = swing.contact_depth_ft
    ball = trajectory.position_at(trajectory.time_at_depth(depth))
    barrel = bp._unproject(aim, depth)
    return math.hypot(barrel[0] - ball[0],
                      barrel[1] - (ball[2] - bc.SWING_UNDERCUT_FT)) * 12.0


def test_the_assist_does_nothing_to_a_perfect_aim():
    """The property that keeps
    `test_a_perfectly_aimed_perfectly_timed_swing_squares_the_ball_up`
    meaningful at every difficulty: the assist shrinks the error the player
    made, so a player who made none is untouched. If this ever fails the assist
    has become a magnet that drags the bat off a correct aim."""
    tr = pitch()
    on_ball = cursor_on_the_ball(tr)
    unassisted = bc.aim_at_pitch(on_ball, tr, "R")
    for _, assist in AIM_ASSIST:
        got = bc.aim_at_pitch(on_ball, tr, "R", assist=assist)
        assert got[0] == pytest.approx(unassisted[0], abs=1e-9)
        assert got[1] == pytest.approx(unassisted[1], abs=1e-9)


def test_the_assist_pulls_the_aim_toward_the_ball_and_never_past_it():
    """A fraction of the error is removed, and only ever a fraction.

    Overshooting would be worse than not helping: it would turn a swing aimed
    high into one aimed low, so a player correcting their own aim would be
    fighting the assist rather than the pitch.
    """
    tr = pitch()
    for inches in (2.0, 4.0, 8.0):
        cursor = aim_off_by(tr, inches)
        unassisted = miss_inches(tr, cursor, 0.0)
        for _, assist in AIM_ASSIST:
            got = miss_inches(tr, cursor, assist)
            assert 0.0 <= got < unassisted, f"{inches} in, assist {assist}"


def test_a_stronger_assist_is_never_worse():
    """Monotone in the setting, across the whole ladder.

    The ladder is the only place difficulty reaches the assist, so a
    non-monotone response would mean a player choosing ROOKIE could be handed a
    harder game than one choosing HALL OF FAME.
    """
    tr = pitch()
    for inches in (1.0, 3.0, 6.0, 12.0):
        cursor = aim_off_by(tr, inches)
        misses = [miss_inches(tr, cursor, a) for _, a in AIM_ASSIST]
        assert misses == sorted(misses), f"{inches} in high: {misses}"


def test_the_assist_is_capped_so_a_bad_guess_still_misses():
    """`MAX_ASSIST_FT` is what keeps this a compensation rather than a magnet.

    A player who reads the pitch two feet wrong has not made a swing that
    deserves contact, however easy the difficulty is set.
    """
    tr = pitch()
    cursor = aim_off_by(tr, 24.0)
    for _, assist in AIM_ASSIST:
        swing = bp.swing(bc.aim_at_pitch(cursor, tr, "R", assist=assist), "R")
        assert swing_at(tr, swing, 0.0) is None, f"assist {assist} reached it"


def test_the_correction_is_clamped_in_length_not_per_axis():
    """A radial clamp, so the assist cannot change the *direction* of the
    player's error — only its size. Clamping each axis on its own would pull a
    swing that was high and inside back to being merely high, which is a
    statement about the pitch that the player never made."""
    err = (0.9, 1.2)                       # 1.5 ft, well past the cap
    cx, cz = bc._assist_correction(err, 1.0)
    assert math.hypot(cx, cz) == pytest.approx(bc.MAX_ASSIST_FT)
    assert cz / cx == pytest.approx(err[1] / err[0])


def test_no_assist_is_the_default_everywhere():
    """Every existing caller and every test above gets the pure translation.
    The assist is opt-in, keyword-only, and off unless a difficulty asks."""
    tr = pitch()
    cursor = aim_off_by(tr, 5.0)
    assert bc.aim_at_pitch(cursor, tr, "R") == bc.aim_at_pitch(
        cursor, tr, "R", assist=0.0)
    assert bc._assist_correction((1.0, 1.0), 0.0) == (0.0, 0.0)


# ---- The vertical cliff -----------------------------------------------------

def test_amateur_has_real_vertical_tolerance():
    """The regression pin for what made contact unreachable.

    The old margin was `(zone_size_mult - 1.0) * K`, which is exactly 0.0 at
    AMATEUR and *negative* above it — so the default difficulty gave the bat no
    tolerance beyond its own surface, and asked the player to place a mouse
    cursor inside the 2.75 in a bat and a ball are between them. That is 22 px
    on a moving target, and it read as a cliff: dead-on scored 1.00, three
    inches high fouled, four inches high missed the ball outright.
    """
    tr = pitch()
    for inches, floor in ((2.0, 0.55), (3.0, 0.30)):
        swing = bp.swing(bc.aim_at_pitch(aim_off_by(tr, inches), tr, "R"), "R")
        got = swing_at(tr, swing, 0.0)
        assert got is not None, f"{inches} in high whiffs with no assist"
        assert got.quality > floor


def test_the_zone_multiplier_scales_a_visible_assist_not_the_bat():
    """Every difficulty gets an ordered movement budget, never a fat hitbox."""
    assists = [bc.spatial_assist_ft(z) for _, z, _ in DIFFICULTIES]
    assert all(a > 0.0 for a in assists), assists
    assert assists == sorted(assists, reverse=True)


def test_a_near_miss_is_moved_within_budget_then_swept_strictly():
    tr = pitch()
    cursor = aim_off_by(tr, 4.0)
    swing = bp.swing(bc.aim_at_pitch(cursor, tr, "R"), "R")
    start = (tr.time_at_depth(swing.contact_depth_ft)
             - bp.SWING_DURATION_S)
    got = bc.resolve_contact(swing, tr, start)

    assert got is not None
    moved = math.hypot(*got.spatial_shift_ft)
    assert 0.0 < moved <= bc.spatial_assist_ft(1.0)
    assert got.spatial_score < 1.0

    corrected = bp.translated_swing(swing, got.spatial_shift_ft)
    gap, _, _, _ = bc._gap_at(
        corrected, tr, start + got.shift_s, got.swing_t_s)
    assert gap <= 0.0


@pytest.mark.parametrize("zone,window", [(1.4, 1.5), (1.0, 1.0), (0.7, 0.4)])
@pytest.mark.parametrize("timing_ms", [-35.0, -15.0, 0.0, 20.0, 45.0])
def test_every_returned_contact_is_a_physical_intersection(zone, window,
                                                            timing_ms):
    tr = pitch()
    got = swing_at(tr, squared_up(tr), timing_ms,
                   zone_size_mult=zone, timing_window_mult=window)
    if got is not None:
        assert got.gap_ft <= 0.0
        assert got.surface_gap_ft <= 1e-9


def test_the_ladder_matches_the_difficulty_table():
    """`AIM_ASSIST` above is a restatement, and restatements drift.

    Same guard `DIFFICULTIES` deserves: the numbers a player actually gets come
    from `settings_manager`, so that is what has to be ordered and non-zero.
    """
    from strikefactor.settings_manager import DifficultyLevel, SettingsManager

    got = []
    for name, expected in AIM_ASSIST:
        mults = SettingsManager.__dict__["get_difficulty_multipliers"]
        # Read the table directly rather than through a settings file.
        table = mults(_FixedDifficulty(DifficultyLevel[name]))
        assert table["aim_assist"] == expected, name
        got.append(table["aim_assist"])
    assert got == sorted(got, reverse=True)
    assert all(0.0 <= v <= 1.0 for v in got)


class _FixedDifficulty:
    """Just enough of `SettingsManager` to read the multiplier table."""

    def __init__(self, level):
        self._level = level

    def get_difficulty(self):
        return self._level


def test_the_no_settings_fallback_is_the_real_amateur_row():
    """`HitOutcomeManager` without a `SettingsManager` must still answer.

    `settings_manager=None` is the *default* in the constructor signature, so
    the fallback is a supported configuration, not a corner. It used to be a
    dict literal restating the AMATEUR row, and a restatement drifts: when
    `aim_assist` was added to the real table nobody added it here, so
    `resolve_aim` raised `KeyError: 'aim_assist'` on the first swing any such
    manager resolved.

    Pinning the whole key set rather than that one key is the point — the next
    multiplier added would reopen the same hole, and this fails on it.
    """
    from strikefactor.gameplay.hit_outcome_manager import HitOutcomeManager
    from strikefactor.settings_manager import DIFFICULTY_MULTIPLIERS, DifficultyLevel

    fallback = HitOutcomeManager(None, None)._get_difficulty_multipliers()
    amateur = DIFFICULTY_MULTIPLIERS[DifficultyLevel.AMATEUR]
    assert fallback == amateur
    # And it is a copy: callers have always been handed a per-call dict, so a
    # caller that mutates one must not rewrite the difficulty of every later
    # reader in the process.
    assert fallback is not amateur


def test_every_difficulty_reading_path_works_without_a_settings_manager():
    """Exercise the paths, not just the dict — a missing key only bites on use.

    `resolve_aim` is the one that was broken; the others share the accessor and
    would break the same way on the next key that goes missing.
    """
    from strikefactor.gameplay.hit_outcome_manager import HitOutcomeManager

    manager = HitOutcomeManager(None, None)
    trajectory = pitch()
    for swing_type in (1, 2):
        aim = manager.resolve_aim((0.0, 2.5), trajectory, "R")
        assert len(aim) == 2
        assert manager.contact_multipliers(swing_type) == (1.0, 1.0)
        assert manager._foul_threshold(swing_type) > 0.0
