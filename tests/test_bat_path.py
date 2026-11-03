"""Where the bat is, and whether it is where the engine said it was.

The replay's whole claim is that it shows the swing that actually happened.
That claim rests on three things:

  * the swing is a function of the aim and the handedness and nothing else;
  * the contact pose is the one `_contact_pose` states — sweet spot on the
    cursor's ray, the bat at the bearing the aim asks for, near square on a
    middle pitch — with the hands wherever that puts them, inside a reach a
    body has;
  * the barrel arrives at contact at a real MLB bat speed, which is what
    separates a kinematic model from an easing curve.

The load-bearing property, and the one this module was rebuilt for, is
`test_the_swing_does_not_depend_on_the_pitch`. The previous model took a
`contact_depth_ft` read off the *pitch's* trajectory and derived the hands, the
bearing, the tilt, the rotation radius, the eased exponent and therefore the
entire load pose from it. On a swing 68 ms early that put the hands 5.13 ft
from a spine they orbit at 1.15, and started the knob four feet behind the
plate on the wrong side of it; 51 ms late, seven and a half feet toward third
base. Everything else here guards properties that were wrong in a draft or
shipped wrong: a barrel that loaded toward the pitcher, a swing whose rotation
all happened in the last few milliseconds, a bat that dropped below the knees
at load, a swing modelled as its own finish minus some rotation, and a barrel
path that plunged vertically and then reversed depth in a sharp V.
"""

import math

import pytest

from strikefactor.gameplay import bat_path as bp
from strikefactor.gameplay import spray
from strikefactor.gameplay.hit_outcome_manager import HitOutcomeManager

HANDS = ("R", "L")

# Aims spanning the plate and a little past it, in world feet at the plate.
# Stated for a right-hander; `_mirror` flips them for a left-hander so both
# hitters are asked the same question about their own inside and outside.
AIMS = [(0.0, 1.6), (0.0, 2.5), (0.2, 3.4), (0.7, 2.5), (-0.7, 2.5), (-1.2, 1.5)]
# The last of those is a foot and a half off the plate and at the knees, past
# what the hands can reach (`HAND_REACH_FT`). Tests about where the barrel
# lands use the rest.
REACHABLE = AIMS[:5]

# The strike zone's own corners and middles, a ball's width outside the plate.
ZONE = [(x, z) for x in (0.83, 0.0, -0.83) for z in (1.4, 2.5, 3.6)]


def _mirror(aim, hand):
    return (aim[0] if hand == "R" else -aim[0], aim[1])


# ---- Pins to the engine's own geometry --------------------------------------

def test_the_pixel_pivot_is_gone():
    """The hands used to be one screen pixel for every pitch.

    `PIVOT_PX` restated `HitOutcomeManager.rhpos` / `lhpos`, the point the
    engine's contact rectangle rotated about, and `_contact_pose` pinned the
    knob to it. That is what put the bat 49 degrees past square on a middle
    pitch: 1.55 ft off the centreline with 2.46 ft of bat to get the sweet
    spot over the plate. The hands' depth and height are stated in feet now
    and their lateral position is solved, so none of the pivot's names may
    come back — nor `_reach` and its slide cap, which existed to stretch a
    pinned knob after a ball it could not span.
    """
    for name in ("PIVOT_PX", "pivot_ft", "hands_anchor_ft", "_reach",
                 "MAX_HAND_SLIDE_FT"):
        assert not hasattr(bp, name), name
    mgr = HitOutcomeManager(None, None)
    assert not hasattr(mgr, "rhpos")
    assert not hasattr(mgr, "lhpos")
    assert bp.HAND_CONTACT_DEPTH_FT == pytest.approx(0.40)
    assert 2.5 < bp.HAND_CONTACT_HEIGHT_FT < 3.3


def test_the_engines_contact_rectangle_is_gone():
    """The engine swings a bat now, so `bat_path` has nothing to restate.

    `CONTACT_ZONE_*` mirrored a 120 x 50 px box that `collision_angled` tested
    for one frame; keeping a copy of a rectangle nobody swings would be the
    second model of contact this whole refactor exists to remove. Its pivot
    outlived it for a while as the hands' position, and is gone too
    (`test_the_pixel_pivot_is_gone`).
    """
    assert not hasattr(bp, "CONTACT_ZONE_WIDTH_PX")
    assert not hasattr(bp, "CONTACT_ZONE_HEIGHT_PX")
    assert not hasattr(bp, "contact_zone_ft")
    assert not hasattr(HitOutcomeManager, "get_ball_to_bat_contact_outcome")
    assert not hasattr(HitOutcomeManager, "contact_timing_quality")
    assert not hasattr(HitOutcomeManager, "power_timing_quality")


def test_swing_duration_is_the_engines_150ms():
    """The bat lag the whole timing system is built on."""
    assert bp.SWING_DURATION_MS == 150
    assert bp.SWING_DURATION_S == pytest.approx(0.150)


# ---- The swing is the player's, not the pitch's -----------------------------

def test_the_contact_depth_input_is_gone():
    """The regression pin, at the signature.

    `swing()` used to take the ball's depth at bat arrival and build the whole
    kinematic chain backwards from it. Anything that reintroduces a pitch
    argument here reintroduces a bat modelled as a consequence of the ball.
    """
    import inspect
    params = list(inspect.signature(bp.swing).parameters)
    assert params == ["aim_ft", "handedness"]
    assert not hasattr(bp, "_contact_lead")


@pytest.mark.parametrize("hand", HANDS)
@pytest.mark.parametrize("aim", AIMS)
def test_the_swing_does_not_depend_on_the_pitch(hand, aim):
    """Two swings aimed the same way are the same swing, to the bit.

    Trivially true now and the entire point: there is no longer any channel
    through which the ball can reach the bat. It is asserted over the whole
    track rather than at contact because what the old model corrupted was the
    *load* pose — the sweet spot at contact was pinned and looked fine.
    """
    aim = _mirror(aim, hand)
    a = bp.swing(aim, hand).full_track(48)
    b = bp.swing(aim, hand).full_track(48)
    for sa, sb in zip(a, b):
        assert sa.knob_ft == sb.knob_ft
        assert sa.barrel_ft == sb.barrel_ft


@pytest.mark.parametrize("hand", HANDS)
def test_the_load_pose_is_a_constant_of_the_stance(hand):
    """Every swing starts in the same place.

    This is what "standardized" means and it is what the screenshots showed
    was false: the knob started at (+2.46, -1.06) on a perfectly timed swing,
    (+7.46, +0.40) on one 51 ms late and (-0.18, -4.10) on one 68 ms early —
    the third of those on the wrong side of the plate for a right-hander.

    **It is a constant by construction now, and for a while it was one by
    accident.** The load position was the contact position turned back through
    the swing, which only stood still because the hands' contact position did.
    Letting the hands move with the pitch started the swing a foot and a half
    apart between an inside pitch and one away, with nothing failing but this
    test. The stance states where the hands start (`LOAD_HANDS_IN_FT`,
    `LOAD_HANDS_BACK_FT`) and each swing solves how to get from there to its
    own contact pose.

    Across the ground it is exact. In height the swing plane's dip still
    scales with the turn radius, which is a few inches between aims.
    """
    spin = 1.0 if hand == "R" else -1.0
    knobs = [bp.swing(_mirror(aim, hand), hand).state_at(0.0).knob_ft
             for aim in AIMS]
    for knob in knobs:
        assert knob[0] == pytest.approx(
            spin * (bp.SPINE_OFFSET_FT - bp.LOAD_HANDS_IN_FT), abs=1e-9)
        assert knob[1] == pytest.approx(
            bp.SPINE_DEPTH_FT - bp.LOAD_HANDS_BACK_FT, abs=1e-9)
    heights = [k[2] for k in knobs]
    assert max(heights) - min(heights) < 0.25


def test_the_load_rotated_back_from_contact_is_gone():
    """`HAND_RADIUS_B` and `HAND_LEAD_DEG` stated the load as a scale and a
    turn applied to the contact position. Either coming back means the swing
    starts where it finishes minus some rotation again."""
    assert not hasattr(bp, "HAND_RADIUS_B")
    assert not hasattr(bp, "HAND_LEAD_DEG")
    assert not hasattr(bp, "HAND_LEAD_RAD")


# ---- The bat lies where the player pointed it -------------------------------
# What used to live here walked the true long axis out of `collision_angled`
# empirically, because the engine's rectangle and the drawn bat were two
# objects that had to be checked against each other — and because that
# rectangle spent the life of the project mirrored across the horizontal, so
# aiming at a low pitch tilted the barrel *up*. Both the rectangle and the
# function are gone. This guards the direction, which is the half the sign bug
# broke.

@pytest.mark.parametrize("hand", HANDS)
def test_aiming_low_points_the_barrel_low(hand):
    """The regression the `collision_angled` sign fix was about.

    Because the bat is long and thin, mirroring its tilt changed its effective
    reach as a *function of aim height*: contact ran 67% on low pitches against
    93% in the middle of the zone. Stated in screen pixels because that is
    where the player is aiming and where the fault was visible.
    """
    cam = bp.DEFAULT_CAMERA
    previous = None
    for cursor_y in (545, 485, 425):
        s = bp.swing(bp._to_ft((630, cursor_y)), hand)
        st = s.state_at(bp.SWING_DURATION_S)
        barrel_y = cam.project(*st.barrel_ft)[1]
        knob_y = cam.project(*st.knob_ft)[1]
        # Aim below the hands and the barrel goes below them, and vice versa.
        assert (barrel_y > knob_y) is (cursor_y > knob_y)
        # And it tracks the cursor monotonically, with no fold in the middle.
        if previous is not None:
            assert barrel_y < previous
        previous = barrel_y


# ---- The contact pose -------------------------------------------------------

@pytest.mark.parametrize("hand", HANDS)
@pytest.mark.parametrize("aim", REACHABLE + ZONE)
def test_the_sweet_spot_at_contact_lands_under_the_cursor(hand, aim):
    """The pin, and it is a *screen* pin because the aim is a screen point.

    A cursor names a ray. The sweet spot has to sit on that ray at the depth
    the bat reaches, which is not the same world point as the aim resolved at
    the plate — it is further out and a little higher or lower. Asserting
    the world coordinates instead would be asserting that the player aims at
    the plate, which is exactly the bias `_unproject` exists to remove.

    Asked of the whole strike zone as well as the ordinary aims: the reach
    bounds on the hands must not bind anywhere a strike can be.
    """
    aim = _mirror(aim, hand)
    s = bp.swing(aim, hand)
    st = s.state_at(bp.SWING_DURATION_S)
    cam = bp.DEFAULT_CAMERA
    want_x = cam.screen_center_x - aim[0] * cam.scale_x / cam.cam_dist
    want_y = cam.screen_center_y - (aim[1] - cam.cam_height) * cam.scale_y / cam.cam_dist
    got = cam.project(*st.sweet_spot_ft)
    assert got[0] == pytest.approx(want_x, abs=1e-6)
    assert got[1] == pytest.approx(want_y, abs=1e-6)
    assert st.sweet_spot_ft[1] == pytest.approx(s.contact_depth_ft, abs=1e-6)


@pytest.mark.parametrize("hand", HANDS)
def test_contact_depth_varies_with_location_the_way_real_contact_does(hand):
    """Contact depth is an *output*, and it comes out right.

    The bat is further round on a pitch inside and behind square on one away,
    and the barrel leads the hands by the bat's length times the sine of that.
    So a pitch inside is met over a foot in front of the plate, one down the
    middle about half a foot out, and one on the outside corner a couple of
    inches *behind* the plate's front edge. Nothing clamps the last of those
    at zero: it is where the ball is struck.
    """
    depths = [bp.swing(_mirror((x, 2.5), hand), hand).contact_depth_ft
              for x in (0.7, 0.35, 0.0, -0.35, -0.7)]
    assert depths == sorted(depths, reverse=True), "inside must be met further out front"
    assert 0.9 < depths[0] < 1.6, "an inside pitch is met over a foot out front"
    assert 0.3 < depths[2] < 1.0, "a middle pitch is met about half a foot out"
    assert -0.5 < depths[-1] < 0.0, "the outside corner is met behind the front edge"


@pytest.mark.parametrize("hand", HANDS)
def test_the_on_time_bat_is_near_square_on_a_middle_pitch(hand):
    """The defect this pose replaced, stated as its fix.

    With the knob pinned 1.55 ft off the centreline, the only way to put the
    sweet spot over the plate was to point the bat at the pitcher: 49 degrees
    past square on a middle-middle pitch, and 19 to 71 across the zone. A bat
    meets a middle pitch about square.
    """
    s = bp.swing((0.0, 2.5), hand)
    bearing = spray.attack_direction_deg(s.contact_axis, s.spin)
    assert abs(bearing) < 10.0, f"{bearing:+.1f} deg past square"
    assert bearing == pytest.approx(bp.POSE_MEAN_DEG, abs=1e-6)


@pytest.mark.parametrize("hand", HANDS)
@pytest.mark.parametrize("aim", AIMS)
def test_the_bat_has_the_bearing_the_aim_asks_for(hand, aim):
    """The condition that closes the pose, checked against the bat itself.

    It replaced a pin on the projection of the bat onto a hands-to-cursor line
    on screen, which held only because the knob was a fixed pixel. The bat's
    bearing is stated now, and it holds for every aim — including one past the
    hands' reach, where the barrel falls short of the cursor and the attitude
    does not change.
    """
    aim = _mirror(aim, hand)
    s = bp.swing(aim, hand)
    want = math.degrees(bp.pose_bearing_rad(s.spin * aim[0]))
    assert spray.attack_direction_deg(s.contact_axis, s.spin) == pytest.approx(
        want, abs=1e-6)
    st = s.state_at(bp.SWING_DURATION_S)
    drawn = tuple(st.barrel_ft[i] - st.knob_ft[i] for i in range(3))
    assert spray.attack_direction_deg(drawn, s.spin) == pytest.approx(
        want, abs=1e-6)


@pytest.mark.parametrize("hand", HANDS)
def test_the_bearing_answers_the_aim_all_the_way_across(hand):
    """Further inside is further round, at a rate that never goes slack inside
    the zone and never reverses outside it. Measured as a rate: a step is
    monotone too."""
    xs = [-1.8 + 0.05 * i for i in range(73)]
    bearings = [math.degrees(bp.pose_bearing_rad(x)) for x in xs]
    assert bearings == sorted(bearings)
    rates = [(b1 - b0) / 0.05 for x, b0, b1 in zip(xs, bearings, bearings[1:])
             if -0.85 <= x <= 0.80]
    assert min(rates) > 8.0, f"{min(rates):.1f} deg/ft inside the zone"
    assert max(rates) == pytest.approx(bp.POSE_GAIN_DEG_PER_FT, rel=0.02)
    # And it saturates smoothly: no aim, however far off, turns the bat past
    # the stated span.
    for x in (-40.0, 40.0):
        assert abs(math.degrees(bp.pose_bearing_rad(x)) - bp.POSE_MEAN_DEG
                   ) <= bp.POSE_SPAN_DEG + 1e-9


@pytest.mark.parametrize("hand", HANDS)
def test_contact_depth_follows_from_the_bearing_and_nothing_caps_it(hand):
    """`depth = hand depth + L * cos(tilt) * sin(bearing)`, checked on the bat.

    So depth is bounded by the bearing's span and the bat's length, which is
    why nothing needs to cap it, and it goes negative where the bat is behind
    square. The old clamp at zero is gone, and with it the pile of swings met
    at exactly the plate.
    """
    assert not hasattr(bp, "MAX_CONTACT_LEAD_DEG")
    reach = bp.HANDS_TO_SWEET_SPOT_FT * math.sin(
        math.radians(bp.POSE_MEAN_DEG + bp.POSE_SPAN_DEG))
    seen_behind = False
    for x in (1.5, 0.7, 0.0, -0.7, -1.5):
        for z in (1.5, 2.5, 3.5):
            s = bp.swing(_mirror((x, z), hand), hand)
            bearing = bp.pose_bearing_rad(x)
            want = (bp.HAND_CONTACT_DEPTH_FT + bp.HANDS_TO_SWEET_SPOT_FT
                    * math.cos(s.contact_tilt_rad) * math.sin(bearing))
            assert s.contact_depth_ft == pytest.approx(want, abs=1e-9)
            assert abs(s.contact_depth_ft - bp.HAND_CONTACT_DEPTH_FT) <= reach
            seen_behind = seen_behind or s.contact_depth_ft < 0.0
    assert seen_behind, "no aim met the ball behind the plate's front edge"


@pytest.mark.parametrize("hand", HANDS)
def test_even_an_absurd_aim_keeps_the_bat_on_a_body(hand):
    """A cursor anywhere on the screen, including well off the plate, has to
    produce a bat a person could be holding.

    Solved without a bound, the hands run away: out over the plate's far edge
    on a ball a foot outside, behind the batter's own body on one a foot
    inside. So they stay within `HAND_REACH_FT` of the spine toward the plate
    and `HAND_TUCK_FT` the other way, at their authored depth and height, in
    front of the body. Past that the barrel honestly falls short of the cursor
    and the sweep whiffs.
    """
    spin = 1.0 if hand == "R" else -1.0
    for sx in range(0, 1281, 80):
        for sy in range(200, 721, 40):
            s = bp.swing(bp._to_ft((sx, sy)), hand)
            hands_in = spin * s.hands_contact[0]
            assert (bp.SPINE_OFFSET_FT - bp.HAND_REACH_FT - 1e-9 <= hands_in
                    <= bp.SPINE_OFFSET_FT + bp.HAND_TUCK_FT + 1e-9)
            assert hands_in > 0.0, "the hands crossed the plate's centreline"
            assert s.hands_contact[1] == pytest.approx(bp.HAND_CONTACT_DEPTH_FT)
            assert s.hands_contact[1] > s.spine_xy[1], "hands behind the body"
            assert s.hands_contact[2] == pytest.approx(bp.HAND_CONTACT_HEIGHT_FT)
            assert abs(math.degrees(s.contact_tilt_rad)) <= bp.MAX_CONTACT_TILT_DEG + 1e-9
            assert math.dist(s.contact_ft, s.hands_contact) == pytest.approx(
                bp.HANDS_TO_SWEET_SPOT_FT)
            assert -2.5 < s.contact_depth_ft < 2.9


@pytest.mark.parametrize("hand", HANDS)
def test_a_ball_past_the_hands_reach_is_left_short(hand):
    """The reach bound moves the bat, never its attitude: the barrel stops on
    the batter's side of the cursor, at the bearing the aim asked for."""
    aim = _mirror((-1.6, 1.4), hand)
    s = bp.swing(aim, hand)
    cursor_x = bp._unproject(aim, s.contact_depth_ft)[0]
    short_by = s.spin * (s.contact_ft[0] - cursor_x)
    assert short_by > 0.2, "the barrel reached a ball the hands could not"
    assert spray.attack_direction_deg(s.contact_axis, s.spin) == pytest.approx(
        math.degrees(bp.pose_bearing_rad(s.spin * aim[0])), abs=1e-6)


# ---- Both ends pinned -------------------------------------------------------

@pytest.mark.parametrize("hand", HANDS)
def test_the_bat_is_a_rigid_body(hand):
    """Knob to barrel is one bat length at every instant, follow-through
    included — not just at contact."""
    s = bp.swing((0.0, 2.5), hand)
    for st in s.full_track(48):
        length = math.dist(st.knob_ft, st.barrel_ft)
        assert length == pytest.approx(bp.BAT_LENGTH_FT, abs=1e-6)


# ---- Bat speed --------------------------------------------------------------

@pytest.mark.parametrize("hand", HANDS)
@pytest.mark.parametrize("aim", AIMS)
def test_barrel_reaches_mlb_bat_speed_at_contact(hand, aim):
    """The check that `ease_k` is kinematics and not a shape parameter: the
    solved exponent has to put a real bat speed on the barrel. MLB average is
    ~72 mph, and the rotation radius it is solved against — spine to contact
    point, a little over 3 ft — implies ~1900 deg/s."""
    s = bp.swing(_mirror(aim, hand), hand)
    assert s.state_at(bp.SWING_DURATION_S).speed_mph == pytest.approx(72.0, abs=1.5)


@pytest.mark.parametrize("hand", HANDS)
def test_the_swing_accelerates_into_contact(hand):
    """Fastest at contact, and building the whole way. A linear sweep would
    move the barrel at its average speed throughout — the same mistake as
    flying a batted ball at its average speed. Not strictly monotone: the load
    terms contribute real speed mid-swing and hand it over to the rotation, so
    a fraction of a mph may wash between samples.

    The end-to-middle ratio is ~1.5 rather than the ~2 an earlier draft got,
    and the difference is a correction rather than a regression: `ease_k` is
    solved against the spine-to-contact radius, which grew from 2.9 ft to
    3.7 ft once contact stopped being pinned to the plate. 3.7 ft is the
    honest number, so the gentler profile is the honest one.
    """
    s = bp.swing((0.0, 2.5), hand)
    speeds = [st.speed_mph for st in s.barrel_track(32)]
    for a, b in zip(speeds, speeds[1:]):
        assert b > a - 0.75
    assert speeds[0] < 1.0
    assert speeds[-1] > speeds[len(speeds) // 2] * 1.2


@pytest.mark.parametrize("hand", HANDS)
@pytest.mark.parametrize("aim", AIMS)
def test_the_solved_exponent_never_rails(hand, aim):
    """`ease_k`'s rails exist to stop a pathological swing, not to be load
    bearing. They bound the peak-to-mean angular speed ratio, and a swing that
    hits one is a sign the contact pose has come loose from the body again —
    which is exactly what happened before, where a mistimed swing railed at the
    1.05 floor and the acceleration profile flattened out entirely."""
    s = bp.swing(_mirror(aim, hand), hand)
    assert bp.EASE_K_MIN < s.ease_k < bp.EASE_K_MAX
    assert 1.6 < s.ease_k < 2.7


# ---- The load position ------------------------------------------------------

@pytest.mark.parametrize("hand,side", [("R", 1.0), ("L", -1.0)])
def test_the_barrel_loads_behind_the_batter_not_in_front(hand, side):
    """Without the handedness spin, both hitters loaded their barrel toward
    the *pitcher* — the finish of a swing drawn as its start."""
    s = bp.swing((0.0, 2.5), hand)
    start = s.state_at(0.0).sweet_spot_ft
    assert start[1] < -1.0, "barrel should start behind the plate"
    assert start[0] * side > 0, "barrel should start on the batter's own side"


@pytest.mark.parametrize("hand", HANDS)
@pytest.mark.parametrize("aim", AIMS)
def test_the_barrel_never_drops_below_the_knees(hand, aim):
    """The plane is a tilted circle, so it bottoms out a quarter turn before
    contact and comes back. Read as a ramp instead it just keeps going down,
    which is what buried the barrel."""
    s = bp.swing(_mirror(aim, hand), hand)
    heights = [st.sweet_spot_ft[2] for st in s.barrel_track(32)]
    assert min(heights) > 1.2


@pytest.mark.parametrize("hand", HANDS)
@pytest.mark.parametrize("aim", [(0.0, 1.6), (0.0, 2.5), (0.2, 3.4)])
def test_the_barrel_loads_above_the_shoulder_and_comes_down(hand, aim):
    """The regression this module's load exists for.

    Modelling the swing as its finish minus 120° of rotation, with the whole
    rigid bat slid down an inclined plane, started the barrel *below* the
    contact point — four inches off the dirt on a knee-high pitch — and swept
    it up out of the ground. A swing starts with the bat at the shoulder.

    Stated as a height off the ground rather than as an offset from contact,
    because the point is that the load is an absolute attitude: a low pitch
    costs the barrel a longer drop, it does not lower where the bat starts.
    """
    s = bp.swing(_mirror(aim, hand), hand)
    track = [st.sweet_spot_ft[2] for st in s.barrel_track(40)]
    assert track[0] > 5.0, "the barrel should load at shoulder height or above"
    # Clear of the ball it will meet, by a margin that *shrinks* as the pitch
    # gets higher — 4.6 ft of drop to a knee-high pitch against 2.8 to one at
    # the letters, which is the load being an absolute attitude rather than an
    # offset from contact.
    assert track[0] > track[-1] + 1.5
    # Down, then the plane's short lift into contact — never up and then down.
    assert track.index(min(track)) > 0.8 * len(track)


@pytest.mark.parametrize("hand", HANDS)
def test_the_hands_lead_the_barrel_down_into_the_slot(hand):
    """The barrel gives up more height than the hands do, which is what
    separates a bat tipping over onto the plane from one being lowered
    bodily — the old model moved every point of the bat by the same amount."""
    s = bp.swing((0.0, 2.5), hand)
    load, contact = s.state_at(0.0), s.state_at(bp.SWING_DURATION_S)
    barrel_drop = load.barrel_ft[2] - contact.barrel_ft[2]
    hand_drop = load.knob_ft[2] - contact.knob_ft[2]
    assert barrel_drop > 3.0
    assert 0.3 < hand_drop < barrel_drop / 2


@pytest.mark.parametrize("hand", HANDS)
@pytest.mark.parametrize("aim", AIMS)
def test_the_ball_is_met_on_the_way_up_at_the_swing_plane(hand, aim):
    """"Met on the way up" is a fact about the barrel at *contact*, not about
    where the swing started — the assertion this replaces confused the two and
    so was satisfied by a bat rising out of the dirt.

    Every load term is flat at contact by construction (`ON_PLANE_EASE >= 2`,
    and the hand-radius profile is stated as a function of the load for the
    same reason), which is what leaves the tilted plane as the only thing
    acting there and makes the attack angle exactly `ATTACK_ANGLE_DEG`. If a
    load term ever stops being flat, this is where it shows up.
    """
    s = bp.swing(_mirror(aim, hand), hand)
    a = s.state_at(bp.SWING_DURATION_S * 0.999).sweet_spot_ft
    b = s.state_at(bp.SWING_DURATION_S).sweet_spot_ft
    rise = b[2] - a[2]
    run = math.hypot(b[0] - a[0], b[1] - a[1])
    assert math.degrees(math.atan2(rise, run)) == pytest.approx(
        bp.ATTACK_ANGLE_DEG, abs=0.2)


def test_the_inclined_ramp_that_buried_the_barrel_is_gone():
    """`MAX_PLANE_DROP_FT` existed only to stop a monotonic ramp from putting
    the barrel under the batter's feet. A tilted circle does not need a cap,
    and a cap coming back means the ramp did too."""
    assert not hasattr(bp, "MAX_PLANE_DROP_FT")


def test_the_fixed_barrel_circle_is_gone():
    """The barrel-on-a-circle model drew the V-cusp and the vertical plunge,
    and derived the knob backwards into the catcher's box. Its constants
    coming back means the sweet spot stopped being derived from the hands:
    `BARREL_RADIUS_FT` was the circle, module-level `SWING_EASE_K` was its
    single global profile (per-swing `ease_k` replaced it), and
    `LOAD_HAND_HEIGHT_FT` was hand height as an *offset* from contact rather
    than the absolute `LOAD_HANDS_HEIGHT_FT` a body actually has."""
    assert not hasattr(bp, "BARREL_RADIUS_FT")
    assert not hasattr(bp, "SWING_EASE_K")
    assert not hasattr(bp, "LOAD_HAND_HEIGHT_FT")


def test_the_orbit_solve_that_flung_the_hands_is_gone():
    """`HAND_ORBIT_RADIUS_FT` and `HAND_DEPTH_PRIOR_FT` parameterised a
    root-find for hands that would sit on a fixed orbit around a contact point
    taken from the *pitch*. Past about three feet off the plate it had no
    solution and fell through to "closest approach", which is how the hands
    ended up 5 ft from the spine. The contact pose is solved from the aim now
    and cannot fail."""
    assert not hasattr(bp, "HAND_ORBIT_RADIUS_FT")
    assert not hasattr(bp, "HAND_DEPTH_PRIOR_FT")
    assert not hasattr(bp, "PLANE_DIP_RADIUS_CAP_FT")


@pytest.mark.parametrize("hand", HANDS)
@pytest.mark.parametrize("aim", AIMS)
def test_the_hands_stay_attached_to_a_body(hand, aim):
    """The regression the hands-first model exists for.

    This test existed while the fault shipped and passed, because it only ever
    asked about contact within three feet of the plate — where the old orbit
    solve still had a root. It is parameterised on *aim* now, which is the
    only thing the swing depends on, so there is no longer an unexplored
    corner of the input space for the hands to escape into.
    """
    s = bp.swing(_mirror(aim, hand), hand)
    for st in s.full_track(48):
        reach = math.hypot(st.knob_ft[0] - s.spine_xy[0],
                           st.knob_ft[1] - s.spine_xy[1])
        assert reach < 2.7
        assert 1.8 < st.knob_ft[2] < 5.0


# ---- The loop ---------------------------------------------------------------

@pytest.mark.parametrize("hand", HANDS)
@pytest.mark.parametrize("aim", AIMS)
def test_the_side_view_never_stalls_into_a_cusp(hand, aim, n=96):
    """The V-corner in the old replay was a projected-velocity zero: the
    barrel's depth reversed at an instant when nothing was moving vertically
    either, so the side view drew two straight legs meeting at a point. A
    loop only *rounds* if the projection keeps real speed through the
    turnaround — this is the floor under that, over every ordinary aim."""
    s = bp.swing(_mirror(aim, hand), hand)
    sweet = [st.sweet_spot_ft for st in s.barrel_track(n)]
    dt = bp.SWING_DURATION_S / (n - 1)
    contact_ft_s = s.state_at(bp.SWING_DURATION_S).speed_mph / bp.MPH_PER_FT_S
    projected = [math.hypot(sweet[i + 1][1] - sweet[i][1],
                            sweet[i + 1][2] - sweet[i][2]) / dt
                 for i in range(int(0.3 * (n - 1)), n - 1)]
    assert min(projected) > 0.10 * contact_ft_s


@pytest.mark.parametrize("hand", HANDS)
@pytest.mark.parametrize("aim", AIMS)
def test_the_barrels_depth_reversal_sits_in_the_body_of_the_swing(hand, aim):
    """The old circle placement made the barrel overshoot the contact depth
    and double back at 83% of the swing — the boomerang. The loop's
    turnaround belongs in the body of the swing, and now lands between a
    third and two thirds of the way through it."""
    s = bp.swing(_mirror(aim, hand), hand)
    ys = [st.sweet_spot_ft[1] for st in s.barrel_track(96)]
    turn = ys.index(min(ys)) / (len(ys) - 1)
    assert 0.2 < turn < 0.75


# ---- The follow-through -----------------------------------------------------

@pytest.mark.parametrize("hand", HANDS)
def test_the_swing_carries_on_past_contact(hand):
    """The bat does not stop at the ball. It matters beyond looking right: a
    swing that arrives early is still moving when the ball gets there, and
    `bat_contact` sweeps this stretch of the path too."""
    s = bp.swing((0.0, 2.5), hand)
    contact = s.state_at(bp.SWING_DURATION_S)
    finish = s.state_at(bp.TOTAL_DURATION_S)
    assert bp.TOTAL_DURATION_S > bp.SWING_DURATION_S
    assert math.dist(contact.sweet_spot_ft, finish.sweet_spot_ft) > 1.5
    # It decelerates rather than stopping dead at the ball.
    assert finish.speed_mph < contact.speed_mph
    assert s.state_at(bp.SWING_DURATION_S * 1.1).speed_mph > 0.4 * contact.speed_mph


@pytest.mark.parametrize("hand,side", [("R", 1.0), ("L", -1.0)])
def test_the_follow_through_wraps_the_bat_and_does_not_un_swing_it(hand, side):
    """Past contact the load is spent and stays spent. Expressed as
    `|theta|` it would revive after contact and pull the bat back toward its
    load attitude, which draws the finish as the swing running backwards."""
    s = bp.swing((0.0, 2.5), hand)
    ys = [st.sweet_spot_ft[1] for st in s.full_track(64)]
    contact_i = int(64 * bp.SWING_DURATION_S / bp.TOTAL_DURATION_S) - 1
    assert ys[-1] > ys[contact_i], "the barrel keeps going forward through the finish"
    assert 30.0 < math.degrees(s.extension_arc_rad) < 90.0


# ---- The bat's own shape ----------------------------------------------------

def test_the_bat_profile_is_a_bat():
    """Knob flare, thin handle held a third of the way out, concave taper into
    a barrel at the MLB maximum. Stated in real inches because `bat_contact`
    sweeps these radii against the ball — a bat that is a uniform cylinder
    makes a handle hit indistinguishable from a barrel one."""
    assert bp.bat_radius_ft(0.0) * 24.0 == pytest.approx(2.10, abs=0.05)
    assert bp.bat_radius_ft(0.2) * 24.0 == pytest.approx(0.99, abs=0.06)
    assert bp.bat_radius_ft(1.0) * 24.0 == pytest.approx(2.60, abs=0.03)
    assert bp.bat_radius_ft(1.0) * 24.0 <= 2.61, "the MLB maximum, and not over it"
    # Monotone through the taper, and concave — still thin a third of the way.
    taper = [bp.bat_radius_ft(f) for f in (0.36, 0.5, 0.6, 0.7, 0.8, 1.0)]
    assert taper == sorted(taper)
    assert bp.bat_radius_ft(0.36) < 1.2 * bp.bat_radius_ft(0.2)
    # Out of range clamps rather than extrapolating into a negative radius.
    assert bp.bat_radius_ft(-1.0) == bp.bat_radius_ft(0.0)
    assert bp.bat_radius_ft(2.0) == bp.bat_radius_ft(1.0)


def test_the_sweet_spot_is_where_the_engines_cursor_is():
    """`SWEET_SPOT_FRAC` is not a chosen number: it is the 30 px of rectangle
    the engine leaves outboard of the cursor, in bat lengths."""
    assert bp.SWEET_SPOT_FRAC == pytest.approx(
        (bp.BAT_LENGTH_FT - bp.CURSOR_TO_TIP_FT) / bp.BAT_LENGTH_FT)
    assert 0.85 < bp.SWEET_SPOT_FRAC < 0.92


# ---- Difficulty moved out of the swing --------------------------------------

def test_difficulty_and_swing_type_do_not_reach_the_swings_shape():
    """A hitter on Hall of Fame swings the same bat as one on Rookie.

    `contact_zone_size` used to scale a rectangle restated in this module, and
    `swing_type` used to halve its height. Neither is a fact about the swing's
    *shape*, so both live in `bat_contact` now — which is the module that asks
    whether the bat and the ball touched, and therefore the only one with an
    opinion about how close they had to come.
    """
    from strikefactor.gameplay import bat_contact as bc
    assert bc.spatial_assist_ft(1.4) > bc.spatial_assist_ft(1.0) > bc.spatial_assist_ft(0.7)
    assert bc.spatial_assist_ft(1.0, power=True) < bc.spatial_assist_ft(1.0)
    assert (bc.timing_assist_s(1.5) > bc.timing_assist_s(1.0)
            > bc.timing_assist_s(0.4))
    assert bc.foul_threshold(1.5) < bc.foul_threshold(1.0) < bc.foul_threshold(0.4)


def test_a_translated_swing_moves_rigidly_without_changing_its_shape():
    """Spatial forgiveness must be visible without changing swing direction."""
    base = bp.swing((0.2, 2.8), "R")
    dx, dz = 0.11, -0.07
    moved = bp.translated_swing(base, (dx, dz))

    assert moved.contact_axis == base.contact_axis
    assert moved.contact_depth_ft == base.contact_depth_ft
    for t_s in (0.0, bp.SWING_DURATION_S * 0.6, bp.TOTAL_DURATION_S):
        before, after = base.state_at(t_s), moved.state_at(t_s)
        for a, b in ((before.knob_ft, after.knob_ft),
                     (before.barrel_ft, after.barrel_ft),
                     (before.sweet_spot_ft, after.sweet_spot_ft)):
            assert b == pytest.approx((a[0] + dx, a[1], a[2] + dz))
        assert after.speed_mph == pytest.approx(before.speed_mph)
        # The collision reads the bat's velocity off whichever swing was
        # swept, so the assisted one has to answer and answer the same.
        assert moved.point_velocity_at(t_s, 0.9) == pytest.approx(
            base.point_velocity_at(t_s, 0.9))


@pytest.mark.parametrize("hand,side", [("R", 1.0), ("L", -1.0)])
def test_the_bats_velocity_is_asked_of_a_point_on_it(hand, side):
    """`point_velocity_at` is the bat's half of the collision.

    At contact the sweet spot is moving at the stated bat speed, forward and
    rising at the attack angle. The handle is on the same bat and moving a
    good deal slower, which is why the collision asks about the wood that met
    the ball and not about the swing.
    """
    s = bp.swing((0.0, 2.5), hand)
    v = s.point_velocity_at(bp.SWING_DURATION_S, bp.CONTACT_SWEET_SPOT_FRAC)
    speed = math.sqrt(sum(c * c for c in v))
    assert speed * bp.MPH_PER_FT_S == pytest.approx(bp.PEAK_BAT_SPEED_MPH, abs=1.5)
    assert v[1] > 0.8 * speed, "the barrel should be moving at the pitcher"
    assert math.degrees(math.asin(v[2] / speed)) == pytest.approx(
        bp.ATTACK_ANGLE_DEG, abs=1.0)
    # The barrel is sweeping across the plate toward the batter's pull side.
    assert v[0] * side > 0.0
    handle = s.point_velocity_at(bp.SWING_DURATION_S, 0.2)
    assert math.sqrt(sum(c * c for c in handle)) < 0.75 * speed
    # Defined at both ends of the swing, where a central difference has only
    # one side to stand on.
    for t_s in (0.0, bp.TOTAL_DURATION_S):
        assert all(math.isfinite(c) for c in s.point_velocity_at(t_s, 0.9))
