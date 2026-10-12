"""Which way the ball went.

Before `spray` the game had four answers to that question and the one it used
most was `random.uniform(50°, 130°)` — a ball in play had no pull or
opposite-field tendency at all, while a home run read the *pitch's* location, a
ball off the wall flipped a coin, and only a foul consulted the swing. What is
guarded here is that there is one answer now, that it comes off the bat, and
that the two batters are mirror images of each other.

The answer is the horizontal reading of one collision
(`bat_ball_collision`, which `tests/test_bat_ball_collision.py` covers on its
own). These tests ask about it through the whole chain: a real swing against a
real pitch, and then the animation that flies the result.

The mirror is the one to watch. A sign error in a spray model mirrors the
hitter, and this project has already lost a year to exactly that defect once
(`collision_angled` rotated its circle the wrong way for the life of the
project). Every directional claim below is therefore made for both hands.
"""

import functools
import math
import random

import pytest

from strikefactor.gameplay import bat_contact as bc
from strikefactor.gameplay import bat_path as bp
from strikefactor.gameplay import spray
from strikefactor.settings_manager import DIFFICULTY_MULTIPLIERS, DifficultyLevel
from strikefactor.utils.pitch_physics import DEFAULT_CAMERA, PitchTrajectory
from tools import calibrate_contact as harness

HANDS = ("R", "L")

# The assist slides a swing to on-time inside its budget, so at the default
# difficulty a +/-20 ms sweep is shown to the geometry as a perfectly timed
# swing. Anything asking how *timing* reaches the ball has to work in the
# residual — same reason and same device as `tests/test_bat_contact.py`.
TIGHT = dict(timing_window_mult=0.2)

# The strike zone, as locations relative to the batter (inside-positive).
ZONE_X = (0.7, 0.35, 0.0, -0.35, -0.7)
ZONE_Z = (1.7, 2.5, 3.3)


def pitch(target_x=0.0, target_z=2.5, speed_mph=93.0):
    return PitchTrajectory.from_pitch_params(
        release_pos=(-1.8, 54.0, 6.0), speed_mph=speed_mph,
        pfx_x_inches=-4.0, pfx_z_inches=14.0,
        target_x_ft=target_x, target_z_ft=target_z)


def on_time(hand, x=0.0, z=2.5, timing_ms=0.0, **kw):
    """The contact a perfectly aimed swing makes, `timing_ms` off.

    The game's own path — cursor on the ball, through `aim_at_pitch` — against
    a pitch mirrored whole for a left-hander, so both batters are shown the
    same pitch relative to themselves. `x` is inside-positive for either.
    """
    return harness.on_time_swing(hand, x, z, timing_ms=timing_ms, **kw)[1]


def residual_ms(contact, timing_ms):
    """The timing error still on the bat after the assist slid the swing."""
    return timing_ms + contact.shift_s * 1000.0


# ---- The bearing is real ---------------------------------------------------

@pytest.mark.parametrize("hand", HANDS)
def test_early_pulls_and_late_goes_the_other_way(hand):
    """The headline claim, and the reason the module exists.

    Nothing states it: the bat turns as the swing runs, so a swing that got
    there early meets the ball with the face further round and the ball leaves
    toward the batter's own field.

    Asked while the ball is still on the barrel. Further early than this it
    runs off the end of the bat, and a ball off the rounded end goes where the
    end sends it.
    """
    sprays = []
    for ms in (-12.0, -9.0, 0.0, 11.0, 17.0, 23.0):
        got = on_time(hand, timing_ms=ms, **TIGHT)
        assert got is not None, f"no contact at {ms:+.0f} ms"
        assert got.along < 0.99, f"{ms:+.0f} ms is off the end of the bat"
        sprays.append(got.spray_deg)
    assert sprays == sorted(sprays, reverse=True), (
        f"spray should fall monotonically from early to late, got {sprays}")
    assert sprays[0] - sprays[-1] > 25.0, "timing barely moves the ball"


@pytest.mark.parametrize("hand", HANDS)
def test_the_ball_turns_at_the_rate_a_bat_does(hand):
    """About a degree and a half per millisecond, **with no gain constant**.

    A bat turns about a degree a millisecond through contact, and the ball
    leaves about 1.6 times as far round as the bat faces
    (`bat_ball_collision`). This used to be 0.63 deg/ms of model multiplied by
    a `TIMING_GAIN` of 2.4 to reach the same place. Measured as a rate over
    the residual timing, on the barrel.
    """
    pts = []
    for ms in range(-12, 21, 2):
        got = on_time(hand, timing_ms=float(ms), **TIGHT)
        if got is not None and got.along < 0.99:
            pts.append((residual_ms(got, ms), got.spray_deg))
    assert len(pts) >= 10
    assert max(t for t, _ in pts) - min(t for t, _ in pts) > 15.0
    mean_t = sum(t for t, _ in pts) / len(pts)
    mean_s = sum(d for _, d in pts) / len(pts)
    rate = -(sum((t - mean_t) * (d - mean_s) for t, d in pts)
             / sum((t - mean_t) ** 2 for t, _ in pts))
    assert 1.3 < rate < 1.9, f"{rate:.2f} deg of spray per ms of timing"
    assert not hasattr(spray, "TIMING_GAIN")


@pytest.mark.parametrize("hand", HANDS)
def test_an_inside_pitch_is_pulled_and_one_away_is_not(hand):
    """The other half of the model, and it is not a rule either: the bat is
    further round when it meets a pitch inside, and behind square on one
    away."""
    for z in ZONE_Z:
        sprays = []
        for x in ZONE_X:
            got = on_time(hand, x, z)
            assert got is not None
            sprays.append(got.spray_deg)
        assert sprays == sorted(sprays, reverse=True), (
            f"inside should be pulled more than away, got {sprays}")
        assert sprays[0] > 15.0 > -5.0 > sprays[-1]


def test_the_two_batters_are_mirror_images():
    """The pin on the sign, made against the *field* rather than the bat.

    A left-handed hitter's pull field is right field. Both batters, shown the
    same pitch relative to themselves and swinging identically, must send the
    ball to mirrored places on the field — never to the same place, which is
    what signing the face normal instead of the angle produces.

    Exact, because the pitch is mirrored whole (release point and break as
    well as location) and nothing in the chain draws a random number.
    """
    for x in (0.5, 0.0, -0.5):
        for ms in (-12.0, 0.0, 15.0):
            fields = {}
            for hand in HANDS:
                got = on_time(hand, x, timing_ms=ms, **TIGHT)
                assert got is not None
                fields[hand] = spray.field_angle_deg(
                    got.spray_deg, spray.spin_for(hand))
            assert fields["R"] + fields["L"] == pytest.approx(180.0, abs=1e-6), (
                f"x={x} ms={ms}: R->{fields['R']:.1f} L->{fields['L']:.1f} "
                "are not mirror images")
            assert abs(fields["R"] - 90.0) > 1.0, "nothing to mirror at centre"


def test_a_right_hander_pulls_toward_left_field():
    """The one absolute orientation claim, spelled out so that a mirrored
    model cannot pass by being self-consistently backwards.

    Field angles: 90 is centre, above 90 is left field, 45/135 are the lines.
    """
    assert spray.field_angle_deg(30.0, spray.spin_for("R")) > 90.0
    assert spray.field_angle_deg(30.0, spray.spin_for("L")) < 90.0
    assert spray.field_angle_deg(0.0, spray.spin_for("R")) == 90.0
    assert spray.field_angle_deg(45.0, spray.spin_for("R")) == pytest.approx(135.0)
    assert spray.field_angle_deg(45.0, spray.spin_for("L")) == pytest.approx(45.0)
    # And the same claim about the frame the collision's vector is stamped in:
    # world +x is the third-base side, a right-hander's pull field.
    assert spray.pull_frame((1.0, 2.0, 3.0), spray.spin_for("R")) == (1.0, 2.0, 3.0)
    assert spray.pull_frame((1.0, 2.0, 3.0), spray.spin_for("L")) == (-1.0, 2.0, 3.0)


# ---- The geometry underneath ------------------------------------------------

def test_the_spray_remap_is_gone():
    """`spray_angle_deg` read the ball's direction off a bat that was 49
    degrees past square, by subtracting the 49, rescaling the location
    response and multiplying the timing response by 2.4. The bat is near
    square now and one collision gives the direction, so there is no reference
    angle and no gain between the bat and the ball. The three that described
    the location response moved to `bat_path` as statements about the bat."""
    for name in ("spray_angle_deg", "SQUARE_REF_DEG", "LOCATION_GAIN",
                 "LOCATION_SPAN_DEG", "TIMING_GAIN", "LEAGUE_MEAN_DEG"):
        assert not hasattr(spray, name), name
    assert bp.POSE_SPAN_DEG > 0.0 and bp.POSE_GAIN_DEG_PER_FT > 0.0


@pytest.mark.parametrize("hand", HANDS)
def test_the_ball_leaves_further_round_than_the_bat_faces(hand):
    """What the retired gain was standing in for, through the real chain.

    On a middle pitch struck on time the bat is a few degrees past square and
    the ball leaves further round than that. Not the 49 degrees apart the two
    used to be drawn at.
    """
    swing, got = harness.on_time_swing(hand, 0.0, 2.5)
    bat = spray.attack_direction_deg(swing.contact_axis, swing.spin)
    assert got.attack_deg == pytest.approx(bat, abs=0.2)
    assert 0.0 < bat < got.spray_deg < bat + 10.0


@pytest.mark.parametrize("hand", HANDS)
def test_a_ball_the_hitter_has_to_reach_for_goes_the_other_way_and_fair(hand):
    """A pitch off the plate away, reached and struck on time.

    The bat's bearing saturates smoothly out there (`bat_path.POSE_SPAN_DEG`)
    instead of running on, so the ball goes to the opposite field and stays
    inside the line with room for some timing error. Read through a straight
    line this used to come out thirteen degrees foul: every ball the hitter
    stretched for hooked past the same pole.

    Asserted against `FOUL_LINE_DEG` rather than a literal, so it still asks
    the right question if the park changes.
    """
    for x in (-0.9, -1.1, -1.3):
        got = on_time(hand, x)
        assert got is not None, f"an on-time swing cannot reach x={x}"
        assert got.spray_deg < 0.0, "a ball reached for should go the other way"
        assert spray.FOUL_LINE_DEG - abs(got.spray_deg) > 5.0, (
            f"x={x}: {got.spray_deg:+.1f} deg leaves too little room")


def test_the_field_conversion_agrees_with_the_projection():
    """`field_angle_deg` is `90 + spin * spray`, which is only correct if the
    world's +x really is the third-base side. Rebuild it from the world vector
    and the camera rather than restating the formula."""
    for hand in HANDS:
        spin = spray.spin_for(hand)
        for deg in (-40.0, -15.0, 0.0, 15.0, 40.0):
            rad = math.radians(deg)
            # The departure direction in world feet: pull is +x for a RHB.
            world = (spin * math.sin(rad), math.cos(rad))
            # field_x = -world_x (the camera negates x; screen-left is 3B).
            rebuilt = math.degrees(math.atan2(world[1], -world[0]))
            assert rebuilt == pytest.approx(
                spray.field_angle_deg(deg, spin), abs=1e-9)


# ---- Fair and foul ----------------------------------------------------------

def _leaving(spray_deg):
    """A level exit direction at `spray_deg`, pull-positive."""
    rad = math.radians(spray_deg)
    return (math.sin(rad), math.cos(rad), 0.0)


def test_direction_is_only_part_of_the_foul_verdict():
    """Both halves have to reach it, and each has to be able to act alone."""
    q_foul = bc.Contact(swing_t_s=0.15, pitch_t_s=0.4, ball_ft=(0, 0, 2.5),
                        axis_point_ft=(0, 0, 2.5), along=0.5, gap_ft=-0.01,
                        vertical_offset_ft=0.0, bat_speed_mph=70.0,
                        exit_direction=_leaving(8.0))
    assert q_foul.spray_deg == pytest.approx(8.0)
    assert not spray.is_foul(q_foul.spray_deg), "this one is fair by direction"
    assert q_foul.is_foul(0.95), "but foul on quality"
    assert not q_foul.is_foul(0.01), "and fair when quality is not the problem"

    hooked = bc.Contact(swing_t_s=0.15, pitch_t_s=0.4, ball_ft=(0, 0, 2.5),
                        axis_point_ft=(0, 0, 2.5),
                        along=bp.CONTACT_SWEET_SPOT_FRAC, gap_ft=-0.05,
                        vertical_offset_ft=0.0,
                        bat_speed_mph=70.0, exit_direction=_leaving(55.0))
    assert hooked.quality > 0.99, "struck cleanly"
    assert spray.is_foul(hooked.spray_deg), "and still foul, by direction"
    assert hooked.is_foul(0.01), "which the verdict has to see"


def test_a_contact_built_without_a_collision_goes_straight_up_the_middle():
    """The default exit direction, for a `Contact` assembled by hand: level
    and dead centre. A real one is stamped by `resolve_contact`."""
    bare = bc.Contact(swing_t_s=0.15, pitch_t_s=0.4, ball_ft=(0, 0, 2.5),
                      axis_point_ft=(0, 0, 2.5), along=0.9, gap_ft=-0.01,
                      vertical_offset_ft=0.0, bat_speed_mph=70.0)
    assert bare.spray_deg == 0.0
    assert bare.launch_deg == 0.0


@pytest.mark.parametrize("hand", HANDS)
def test_an_on_time_swing_is_fair_anywhere_in_the_zone(hand):
    """The constraint that bounds `bat_path.POSE_GAIN_DEG_PER_FT`.

    A perfectly aimed, perfectly timed swing on a strike has to be able to
    stay fair, at every location in the zone, with some degrees to spare for
    the timing nobody has. Pass the location response through any harder and
    a strike on the inside corner is an automatic foul, which is not a thing
    that happens in baseball.

    The high inside corner is the tight one: the bat is barrel-up there, and
    on a barrel-up bat getting under the ball also pulls it.
    """
    tightest = None
    for z in ZONE_Z:
        for x in ZONE_X:
            got = on_time(hand, x, z)
            assert got is not None, f"no contact at x={x}, z={z}"
            margin = spray.FOUL_LINE_DEG - abs(got.spray_deg)
            assert margin >= 4.0, (
                f"an on-time swing at x={x:+.2f}, z={z} leaves at "
                f"{got.spray_deg:+.1f} deg, {margin:.1f} inside the line")
            tightest = margin if tightest is None else min(tightest, margin)
    assert tightest < 12.0, "the response has gone slack: no corner is close"


# ---- The distribution -------------------------------------------------------

# Three tests below ask for `_population(AMATEUR)` verbatim and a fourth
# sweeps it as one rung of the difficulty ladder — four identical runs of a
# 1200-swing sweep, each asserting a different property. The chain is pure
# (`spray`, `bat_path` and `bat_contact` take no global RNG) and every draw
# comes from a locally seeded `random.Random`, so the same arguments always
# produce the same contacts. `Contact` is frozen, so handing the same list to
# four tests cannot let one of them disturb another.
def _population(level, n=1200, hand="R", seed=17):
    """Contacts a plausible player produces, through the real sweep.

    Aim scatter and a late-running timing bias, both off recorded play. Never
    sweep quality or spray uniformly to calibrate anything in this codebase —
    see the warning over `contact_audio.EV_CALIBRATION`.
    """
    return _run_population(level, n, hand, seed)


@functools.lru_cache(maxsize=None)
def _run_population(level, n, hand, seed):
    rng = random.Random(seed)
    mult = DIFFICULTY_MULTIPLIERS[level]
    out = []
    for _ in range(n):
        tr = pitch(target_x=rng.gauss(0.0, 0.55),
                   target_z=rng.gauss(2.5, 0.62),
                   speed_mph=rng.uniform(80.0, 99.0))
        ball = tr.position_at(tr.travel_time)
        px, py, _ = DEFAULT_CAMERA.project(*ball)
        cx, cz = DEFAULT_CAMERA.screen_to_world_at_plate(px, py)
        aim = bc.aim_at_pitch((cx + rng.gauss(0, 0.42), cz + rng.gauss(0, 0.42)),
                              tr, hand, assist=mult["aim_assist"])
        sw = bp.swing(aim, hand)
        start = (tr.time_at_depth(sw.contact_depth_ft) - bp.SWING_DURATION_S
                 + rng.gauss(19.0, 35.0) / 1000.0)
        got = bc.resolve_contact(sw, tr, start,
                                 zone_size_mult=mult["contact_zone_size"],
                                 timing_window_mult=mult["contact_timing_window"])
        if got is not None:
            out.append(got)
    return out


def test_the_fair_population_looks_like_a_real_spray_chart():
    contacts = _population(DifficultyLevel.AMATEUR)
    fair = [c.spray_deg for c in contacts if not spray.is_foul(c.spray_deg)]
    assert len(fair) > 500, "not enough fair contact to judge"
    pull = sum(1 for s in fair if s > 15.0) / len(fair)
    centre = sum(1 for s in fair if -15.0 <= s <= 15.0) / len(fair)
    oppo = sum(1 for s in fair if s < -15.0) / len(fair)
    # MLB is 40/35/25. This model is flatter — half of all contact has
    # near-zero residual timing once the assist has run, so its direction is
    # the pitch's location alone, and the location response cannot be made
    # steeper without fouling the corners — so the band is wide on purpose.
    # What it is actually pinning is that all three fields get used.
    assert 0.22 <= pull <= 0.42, f"pull share {pull:.0%}"
    assert 0.34 <= centre <= 0.54, f"centre share {centre:.0%}"
    assert 0.15 <= oppo <= 0.33, f"oppo share {oppo:.0%}"


def test_direction_fouls_a_believable_share_of_contact():
    contacts = _population(DifficultyLevel.AMATEUR)
    share = sum(1 for c in contacts if spray.is_foul(c.spray_deg)) / len(contacts)
    assert 0.10 <= share <= 0.26, f"direction fouled {share:.0%} of contact"


def test_no_pile_up_on_the_foul_lines():
    """The `_sample_hr_angle` lesson, applied to the new distribution.

    A clamp anywhere in this chain stacks every out-of-range draw onto the two
    boundary angles, and the foul line is exactly where one would be reached
    for. It has to be asked as a *density* question and not a count: the region
    either side of the line is genuinely populated — a ball down the line is an
    ordinary thing to hit — so what marks a clamp is the band at the line
    holding many times its neighbours, not holding anything at all.
    """
    contacts = _population(DifficultyLevel.AMATEUR)
    mags = [abs(c.spray_deg) for c in contacts]

    def band(lo):
        return sum(1 for m in mags if lo <= m < lo + 1.0)

    line = spray.FOUL_LINE_DEG
    at_line = band(line - 0.5)
    neighbours = [band(line - 3.5), band(line - 2.5), band(line + 1.5),
                  band(line + 2.5)]
    typical = max(1.0, sum(neighbours) / len(neighbours))
    assert at_line <= 4.0 * typical, (
        f"{at_line} balls in the degree straddling the foul line against "
        f"{typical:.1f} in a typical neighbouring degree — that is a clamp")


def test_a_harder_setting_sprays_more_contact_foul():
    """Difficulty reaches the ball's direction with nothing tuned for it.

    There is no difficulty dial in `spray` and there should not be one: a
    smaller `timing_assist_s` leaves more of the player's timing error on the
    bat, and the bat is what points the ball.
    """
    shares = []
    for level in (DifficultyLevel.ROOKIE, DifficultyLevel.AMATEUR,
                  DifficultyLevel.PROFESSIONAL, DifficultyLevel.HALL_OF_FAME):
        contacts = _population(level)
        shares.append(
            sum(1 for c in contacts if spray.is_foul(c.spray_deg)) / len(contacts))
    assert shares == sorted(shares), f"not monotone in difficulty: {shares}"
    assert shares[-1] > shares[0] * 1.5, "difficulty barely reaches the spray"


# ---- End to end -------------------------------------------------------------

class _StubBatter:
    def __init__(self, hand):
        self._hand = hand

    def get_handedness(self):
        return self._hand


class _StubGame:
    def __init__(self, hand):
        self.batter = _StubBatter(hand)


def _landing_field_deg(hand, spray_deg, outcome="IN_PLAY", shape="LINER"):
    """Where the animation actually puts the ball, as a real-field bearing.

    Inverts the anisotropic projection rather than reading the screen bearing,
    because the two spaces put the foul lines in different places — 45/135 in
    feet against ~30.7/149.3 on screen. Asserting on the raw screen angle is
    what let the original foul-home-run bug through.
    """
    from strikefactor.gameplay import hit_animation as ha
    random.seed(4)
    anim = ha.HitAnimation(_StubGame(hand), outcome=outcome,
                           on_complete=lambda: None, quality=0.85,
                           batted_ball_type=shape, spray_deg=spray_deg)
    dx_ft = (anim._hit_end[0] - ha.HOME[0]) / ha.FT_TO_PX_X
    dy_ft = (ha.HOME[1] - anim._hit_end[1]) / ha.FT_TO_PX_Y
    return math.degrees(math.atan2(dy_ft, dx_ft))


@pytest.mark.parametrize("hand", HANDS)
@pytest.mark.parametrize("outcome,shape", [("IN_PLAY", "LINER"),
                                           ("IN_PLAY", "GROUNDER"),
                                           ("HOME RUN", "FLY")])
def test_the_ball_lands_where_the_bat_was_pointing(hand, outcome, shape):
    """The whole chain, and the thing a player actually sees.

    A ball in play, a home run and a ball off the wall used to reach their
    directions by three unrelated routes — a uniform draw, a pitch-location
    bias, and `random.choice((-1, 1))`. All three read the bat now, so all
    three have to answer this.
    """
    pulled = _landing_field_deg(hand, +30.0, outcome, shape)
    centre = _landing_field_deg(hand, 0.0, outcome, shape)
    oppo = _landing_field_deg(hand, -30.0, outcome, shape)
    if hand == "R":
        assert pulled > centre > oppo, (
            f"a right-hander's pull should be a larger field angle (left "
            f"field): {pulled:.0f} / {centre:.0f} / {oppo:.0f}")
    else:
        assert pulled < centre < oppo, (
            f"a left-hander's pull should be a smaller field angle (right "
            f"field): {pulled:.0f} / {centre:.0f} / {oppo:.0f}")
    assert abs(centre - 90.0) < 25.0, "a centred ball should go near centre"


@pytest.mark.parametrize("hand", HANDS)
def test_a_ball_that_reaches_the_wall_keeps_its_direction(hand):
    """The wall-candidate branch, which used to flip a coin for the side.

    Which way a ball off the wall goes is the difference between a double down
    the line and one in the gap, and it was being decided after the swing was
    over.
    """
    from strikefactor.gameplay import hit_animation as ha
    from strikefactor.gameplay import park
    sides = []
    # A ball off the wall is one whose carry *reaches* the fence without
    # clearing it (`park.fence_verdict`), and that window is narrow — a
    # max-quality fly carries past the fence and is a home run. So the exit
    # velocity is solved for rather than assumed: this test is about which way
    # the ball went, not about how hard it was hit.
    launch = 30.0
    for spray_deg in (+35.0, -35.0):
        field_rad = spray.field_angle_rad(spray_deg, spray.spin_for(hand))

        def first_ev(reached, field_rad=field_rad):
            lo, hi = 40.0, 160.0
            for _ in range(60):
                mid = 0.5 * (lo + hi)
                if reached(park.fence_verdict(launch, mid, field_rad)):
                    hi = mid
                else:
                    lo = mid
            return hi

        ev = 0.5 * (first_ev(lambda v: v != park.SHORT_OF_WALL)
                    + first_ev(lambda v: v == park.OUT_OF_PARK))
        angles = []
        for seed in range(12):
            random.seed(seed)
            anim = ha.HitAnimation(_StubGame(hand), outcome="IN_PLAY",
                                   on_complete=lambda: None, quality=0.95,
                                   batted_ball_type="FLY",
                                   spray_deg=spray_deg,
                                   launch_deg=launch, ev_mph=ev)
            if not anim._is_wall_candidate:
                continue
            angles.append(anim._hit_end[0] - ha.HOME[0])
        assert angles, "no wall candidates produced"
        sides.append(sum(angles) / len(angles))
    pull_px, oppo_px = sides
    # Screen x: left of home is left field, which is a right-hander's pull.
    assert (pull_px < oppo_px) == (hand == "R"), (
        f"{hand}HB wall balls went the wrong way: {pull_px:.0f} vs {oppo_px:.0f}")


@pytest.mark.parametrize("hand", HANDS)
def test_a_foul_goes_out_on_the_side_it_was_pointed(hand):
    """Fouls were the *only* place the swing reached the ball's direction, and
    they got there through the sign of a timing error against a window of
    hand-tuned milliseconds. Same claim, one model earlier."""
    from strikefactor.gameplay import hit_animation as ha
    for spray_deg, expect_left in ((+70.0, hand == "R"), (-70.0, hand != "R")):
        random.seed(9)
        anim = ha.HitAnimation(_StubGame(hand), outcome="FOUL",
                               on_complete=lambda: None, quality=0.5,
                               batted_ball_type=None, spray_deg=spray_deg)
        dx_ft = (anim._hit_end[0] - ha.HOME[0]) / ha.FT_TO_PX_X
        dy_ft = (ha.HOME[1] - anim._hit_end[1]) / ha.FT_TO_PX_Y
        field = math.degrees(math.atan2(dy_ft, dx_ft))
        assert field > 135.0 or field < 45.0, f"{field:.0f}° is not foul"
        assert (field > 90.0) == expect_left, (
            f"{hand}HB spray {spray_deg:+.0f} landed at {field:.0f}°")


# ---- Where a foul actually went --------------------------------------------
#
# `spray_deg` is where the bat *pointed*. On a foul that is not where the ball
# *went*, and for half of all fouls it is nowhere near: a tipped or topped ball
# keeps a perfectly fair-looking bearing and deflects into foul ground. Nothing
# modelled that, so `hit_animation._setup_foul` invented it out of `random` —
# and the swing replay, drawing `spray_deg`, disagreed with the picture by a
# median of 40.7 degrees over 600 recorded fouls.

@pytest.mark.parametrize("shape", ["GROUNDER", "LINER", "FLY", "POP_UP"])
def test_a_ball_ruled_foul_leaves_in_foul_ground(shape):
    """The property the whole thing rests on: whatever draws this number draws
    a ball outside the lines, so the picture and the verdict cannot disagree.

    Swept over the bearings a bat really produces and the full quality range a
    foul can be graded at.

    No `hand` parameter, and that is the claim rather than an omission: like
    `spray_angle_deg` and `is_foul`, this is stated pull-positive and is
    therefore handedness-free. The flip happens once, downstream, in
    `field_angle_deg` — see `test_a_foul_goes_out_on_the_side_it_was_pointed`
    for the end-to-end mirror.
    """
    for bat_deg in range(-170, 171, 5):
        for q in (0.0, 0.15, 0.4, 0.58, 0.9, 1.0):
            got = spray.foul_departure_deg(float(bat_deg), q, shape)
            assert spray.is_foul(got), (
                f"{shape} at bat {bat_deg:+d} deg, q={q} departs at "
                f"{got:+.1f} deg, which is fair")


def test_a_foul_leaves_on_the_side_the_bat_pointed_it():
    """A deflection changes how far foul, never which pole."""
    for bat_deg in (0.5, 12.0, 44.0, 46.0, 90.0, 150.0):
        for q in (0.1, 0.5, 0.95):
            for shape in ("GROUNDER", "LINER", "FLY"):
                pull = spray.foul_departure_deg(bat_deg, q, shape)
                oppo = spray.foul_departure_deg(-bat_deg, q, shape)
                assert pull > 0 > oppo, (bat_deg, q, shape, pull, oppo)


def test_the_two_ways_to_foul_a_ball_meet_at_the_line():
    """A ball hooked a degree past the pole was struck cleanly and is only just
    foul, so it has to draw a degree past the pole — the deflection is what a
    *glancing* blow adds, and a barrelled ball has nothing to add.

    Continuity here is what makes the direction limb and the quality limb one
    model rather than two: at q = 1 the departure is the bat's own bearing.
    """
    for bat_deg in (50.0, 60.0, 75.0, 100.0):
        got = spray.foul_departure_deg(bat_deg, 1.0, "LINER")
        assert got == pytest.approx(bat_deg, abs=1e-9), (bat_deg, got)


def test_a_deflection_only_ever_pushes_the_ball_further_foul():
    """It cannot straighten a ball out. The animation used to cap the bearing
    at 90 deg, so a swing the bat genuinely sent 128 deg round — behind the
    plate, opposite field — was drawn 38 deg away from where the bat put it."""
    for bat_deg in (46.0, 70.0, 128.0, 165.0):
        for q in (0.0, 0.3, 0.7, 1.0):
            got = spray.foul_departure_deg(bat_deg, q, "LINER")
            assert got >= bat_deg - 1e-9, (bat_deg, q, got)


def test_a_glancing_blow_goes_further_foul_than_a_squared_up_one():
    """The whole content of the quality limb: `severity`. A ball off the end or
    on the handle sprays sharply foul however it was pointed."""
    got = [spray.foul_departure_deg(3.0, q, "LINER")
           for q in (1.0, 0.8, 0.6, 0.4, 0.2, 0.0)]
    assert got == sorted(got), got
    assert got[-1] - got[0] > 30.0, got


def test_a_pop_up_comes_down_behind_the_plate():
    """A ball hit almost straight up does not travel out past a pole — it
    comes down near where it was struck, which is the catcher's. It is also
    the single most ordinary foul there is, and the shape the reported bug
    was: `spray_deg -0.7 deg` drawn forward, animated 154 deg behind."""
    for bat_deg in (-30.0, 0.0, 30.0):
        got = spray.foul_departure_deg(bat_deg, 0.2, "POP_UP")
        assert abs(got) > 90.0, (bat_deg, got)


def test_the_deflection_is_deterministic():
    """`spray` promises a bearing that is a function of the swing and nothing
    else. The model this replaced broke that promise: one identical contact
    animated at eight different bearings across eight plays, so no replay
    could have drawn what the player was shown."""
    assert len({spray.foul_departure_deg(4.0, 0.35, "LINER")
                for _ in range(50)}) == 1
