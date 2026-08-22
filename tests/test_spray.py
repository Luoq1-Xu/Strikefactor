"""Which way the ball went.

Before this module the game had four answers to that question and the one it
used most was `random.uniform(50°, 130°)` — a ball in play had no pull or
opposite-field tendency at all, while a home run read the *pitch's* location, a
ball off the wall flipped a coin, and only a foul consulted the swing. What is
guarded here is that there is one answer now, that it is read off the bat, and
that the two batters are mirror images of each other.

The last of those is the one to watch. A sign error in a spray model mirrors
the hitter, and this project has already lost a year to exactly that defect
once (`collision_angled` rotated its circle the wrong way for the life of the
project). Every directional claim below is therefore made for both hands.
"""

import math
import random

import pytest

from strikefactor.gameplay import bat_contact as bc
from strikefactor.gameplay import bat_path as bp
from strikefactor.gameplay import spray
from strikefactor.settings_manager import DIFFICULTY_MULTIPLIERS, DifficultyLevel
from strikefactor.utils.pitch_physics import DEFAULT_CAMERA, PitchTrajectory

HANDS = ("R", "L")

# The assist slides a swing to on-time inside its budget, so at the default
# difficulty a +/-20 ms sweep is shown to the geometry as a perfectly timed
# swing. Anything asking how *timing* reaches the ball has to work in the
# residual — same reason and same device as `tests/test_bat_contact.py`.
TIGHT = dict(timing_window_mult=0.2)


def pitch(target_x=0.0, target_z=2.5, speed_mph=93.0):
    return PitchTrajectory.from_pitch_params(
        release_pos=(-1.8, 54.0, 6.0), speed_mph=speed_mph,
        pfx_x_inches=-4.0, pfx_z_inches=14.0,
        target_x_ft=target_x, target_z_ft=target_z)


def squared_up(trajectory, hand="R"):
    """The swing of a hitter who tracks the ball and puts the bat on it."""
    aim = (0.0, 2.5)
    for _ in range(6):
        swing = bp.swing(aim, hand)
        ball = trajectory.position_at(
            trajectory.time_at_depth(swing.contact_depth_ft))
        px, py, _ = DEFAULT_CAMERA.project(*ball)
        aim = DEFAULT_CAMERA.screen_to_world_at_plate(px, py)
    return bp.swing(aim, hand)


def swing_at(trajectory, swing, timing_ms, **kw):
    """Resolve a swing `timing_ms` off. Negative early, positive late."""
    due = trajectory.time_at_depth(swing.contact_depth_ft)
    start = due - bp.SWING_DURATION_S + timing_ms / 1000.0
    return bc.resolve_contact(swing, trajectory, start, **kw)


def _mirror(x, hand):
    """A pitch location as the same location relative to *this* batter."""
    return x if hand == "R" else -x


# ---- The bearing is real ---------------------------------------------------

@pytest.mark.parametrize("hand", HANDS)
def test_early_pulls_and_late_goes_the_other_way(hand):
    """The headline claim, and the reason the module exists.

    Nothing states it: the bat turns as the swing runs, so a swing that got
    there early meets the ball with the face further round and the ball leaves
    toward the batter's own field.
    """
    tr = pitch()
    sw = squared_up(tr, hand)
    sprays = []
    for ms in (-20.0, -10.0, 0.0, 10.0, 20.0):
        got = swing_at(tr, sw, ms, **TIGHT)
        assert got is not None, f"no contact at {ms:+.0f} ms"
        sprays.append(got.spray_deg)
    assert sprays == sorted(sprays, reverse=True), (
        f"spray should fall monotonically from early to late, got {sprays}")
    assert sprays[0] - sprays[-1] > 20.0, "timing barely moves the ball"


@pytest.mark.parametrize("hand", HANDS)
def test_an_inside_pitch_is_pulled_and_one_away_is_not(hand):
    """The other half of the model, and it is not a rule either: an inside
    pitch has to be met further out in front, which is a bat further round."""
    sprays = []
    for x in (0.6, 0.2, -0.2, -0.6):
        tr = pitch(target_x=_mirror(x, hand))
        sw = squared_up(tr, hand)
        got = swing_at(tr, sw, 0.0)
        assert got is not None
        sprays.append(got.spray_deg)
    assert sprays == sorted(sprays, reverse=True), (
        f"inside should be pulled more than away, got {sprays}")


def test_the_two_batters_are_mirror_images():
    """The pin on the sign, made against the *field* rather than the bat.

    A left-handed hitter's pull field is right field. Both batters, shown the
    same pitch relative to themselves and swinging identically, must send the
    ball to mirrored places on the field — never to the same place, which is
    what signing the face normal instead of the angle produces.
    """
    for x in (0.5, 0.0, -0.5):
        for ms in (-15.0, 0.0, 15.0):
            fields = {}
            for hand in HANDS:
                tr = pitch(target_x=_mirror(x, hand))
                got = swing_at(tr, squared_up(tr, hand), ms, **TIGHT)
                assert got is not None
                fields[hand] = spray.field_angle_deg(
                    got.spray_deg, spray.spin_for(hand))
            # Mirrored about centre field, to within the couple of degrees the
            # pitch's own break puts between the two mirrored trajectories.
            assert fields["R"] + fields["L"] == pytest.approx(180.0, abs=6.0), (
                f"x={x} ms={ms}: R->{fields['R']:.1f} L->{fields['L']:.1f} "
                "are not mirror images")


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


# ---- The geometry underneath ------------------------------------------------

@pytest.mark.parametrize("hand", HANDS)
def test_the_attack_angle_is_continuous_across_the_reach_boundary(hand):
    """No flat spot where the bat stops being able to span the ball.

    `bat_path._reach` used to answer that case with a bat lying flat in the
    plane of the plate, whose face normal points at *exactly* centre field.
    It fires on ~10% of swings, so the spray distribution grew a spike one
    value wide — the same defect as clamping the home-run angle onto the foul
    poles. The pose comes off the quadratic's vertex now, which is the
    analytic continuation of the root.
    """
    xs = [1.6 - 0.05 * i for i in range(70)]
    angles = [spray.attack_direction_deg(
        bp.swing((_mirror(x, hand), 2.5), hand).contact_axis,
        spray.spin_for(hand)) for x in xs]
    assert angles == sorted(angles, reverse=True), "not monotone in the aim"
    repeats = max(angles.count(a) for a in angles)
    assert repeats == 1, f"{repeats} aims share one attack angle — a flat spot"


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

def test_direction_is_only_part_of_the_foul_verdict():
    """Both halves have to reach it, and each has to be able to act alone.

    Measured before it was written: direction alone caps near 25% of contact
    against a real ~50%, and quality alone cannot see which way the ball went.
    """
    q_foul = bc.Contact(swing_t_s=0.15, pitch_t_s=0.4, ball_ft=(0, 0, 2.5),
                        axis_point_ft=(0, 0, 2.5), along=0.5, gap_ft=-0.01,
                        vertical_offset_ft=0.0, bat_speed_mph=70.0,
                        attack_deg=49.0, pose_attack_deg=49.0)
    assert q_foul.spray_deg == pytest.approx(spray.LEAGUE_MEAN_DEG)
    assert not spray.is_foul(q_foul.spray_deg), "this one is fair by direction"
    assert q_foul.is_foul(0.95), "but foul on quality"
    assert not q_foul.is_foul(0.01), "and fair when quality is not the problem"

    hooked = bc.Contact(swing_t_s=0.15, pitch_t_s=0.4, ball_ft=(0, 0, 2.5),
                        axis_point_ft=(0, 0, 2.5), along=bp.SWEET_SPOT_FRAC,
                        gap_ft=-0.05, vertical_offset_ft=0.0,
                        bat_speed_mph=70.0, attack_deg=95.0, pose_attack_deg=95.0)
    assert hooked.quality > 0.9, "struck cleanly"
    assert spray.is_foul(hooked.spray_deg), "and still foul, by direction"
    assert hooked.is_foul(0.01), "which the verdict has to see"


@pytest.mark.parametrize("hand", HANDS)
def test_a_flawless_swing_can_be_fair_anywhere_in_the_zone(hand):
    """The constraint that sets `LOCATION_GAIN`, and the reason spray is not
    calibrated as a single scale over the raw angle.

    The raw geometry swings the bat's angle 79 degrees across a two-foot plate
    — `bat_path._contact_pose` is pinned to a screen-space aiming pivot, so on
    an inside pitch the bat points nearly at the pitcher. Passed through at
    full strength that makes a perfect swing on an inside or outside strike an
    automatic foul, which is not a thing that happens in baseball.
    """
    for x in (0.8, 0.4, 0.0, -0.4, -0.8):
        tr = pitch(target_x=_mirror(x, hand))
        got = swing_at(tr, squared_up(tr, hand), 0.0)
        assert got is not None, f"no contact at x={x}"
        assert not spray.is_foul(got.spray_deg), (
            f"a flawless swing at x={x:+.1f} sprays foul "
            f"({got.spray_deg:+.1f} deg)")


# ---- The distribution -------------------------------------------------------

def _population(level, n=1200, hand="R", seed=17):
    """Contacts a plausible player produces, through the real sweep.

    Aim scatter and a late-running timing bias, both off recorded play. Never
    sweep quality or spray uniformly to calibrate anything in this codebase —
    see the warning over `contact_audio.EV_CALIBRATION`.
    """
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
    # near-zero residual timing once the assist has run, and a term that is
    # zero cannot be spread — so the band is wide on purpose. What it is
    # actually pinning is that all three fields get used.
    assert 0.22 <= pull <= 0.45, f"pull share {pull:.0%}"
    assert 0.38 <= centre <= 0.60, f"centre share {centre:.0%}"
    assert 0.10 <= oppo <= 0.30, f"oppo share {oppo:.0%}"


def test_direction_fouls_a_believable_share_of_contact():
    contacts = _population(DifficultyLevel.AMATEUR)
    share = sum(1 for c in contacts if spray.is_foul(c.spray_deg)) / len(contacts)
    assert 0.15 <= share <= 0.32, f"direction fouled {share:.0%} of contact"


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
    sides = []
    # A fly ball, because only a fly carries far enough to be a wall candidate:
    # `WALL_REACH_FT` is 380 ft and the hardest line drive the exit-velocity
    # model produces carries about 300.
    for spray_deg in (+35.0, -35.0):
        angles = []
        for seed in range(12):
            random.seed(seed)
            anim = ha.HitAnimation(_StubGame(hand), outcome="IN_PLAY",
                                   on_complete=lambda: None, quality=0.95,
                                   batted_ball_type="FLY",
                                   spray_deg=spray_deg)
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
