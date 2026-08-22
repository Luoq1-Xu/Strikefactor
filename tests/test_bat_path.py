"""Where the bat is, and whether it is where the engine said it was.

The replay's whole claim is that it shows the swing that actually happened.
That claim rests on two pins and one calibration:

  * the geometry constants restated in `bat_path` really are the ones
    `HitOutcomeManager` swings;
  * the drawn bat's screen-plane orientation matches the rectangle
    `collision_angled` tested — its (x, z) projection lies along that ray. The
    depth component is not free: it is *forced* by foreshortening, because the
    pivot is where the hands are and a bat of a known length has to span the
    gap from there to the aim point;
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
from strikefactor.gameplay.hit_outcome_manager import HitOutcomeManager

HANDS = ("R", "L")

# Aims spanning the plate and a little past it, in world feet at the plate.
# Stated for a right-hander; `_mirror` flips them for a left-hander so both
# hitters are asked the same question about their own inside and outside.
AIMS = [(0.0, 1.6), (0.0, 2.5), (0.2, 3.4), (0.7, 2.5), (-0.7, 2.5), (-1.2, 1.5)]


def _mirror(aim, hand):
    return (aim[0] if hand == "R" else -aim[0], aim[1])


# ---- Pins to the engine's own geometry --------------------------------------

def test_pivots_match_the_hit_outcome_manager():
    """`bat_path` restates these so a pure module need not import gameplay.
    If they drift, the replay draws a bat the engine never swung."""
    mgr = HitOutcomeManager.__new__(HitOutcomeManager)
    HitOutcomeManager.__init__(mgr, *_manager_args())
    assert bp.PIVOT_PX["R"] == tuple(float(v) for v in mgr.rhpos)
    assert bp.PIVOT_PX["L"] == tuple(float(v) for v in mgr.lhpos)


def test_the_engines_contact_rectangle_is_gone():
    """The engine swings a bat now, so `bat_path` has nothing to restate.

    `CONTACT_ZONE_*` mirrored a 120 x 50 px box that `collision_angled` tested
    for one frame; keeping a copy of a rectangle nobody swings would be the
    second model of contact this whole refactor exists to remove. The one
    survivor is `PIVOT_PX`, because what it was all along is where the hands
    are.
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
    the third of those on the wrong side of the plate for a right-hander. The
    only aim-driven movement left is the hands sliding along the aiming ray to
    reach a ball the bat cannot otherwise span.
    """
    knobs = [bp.swing(_mirror(aim, hand), hand).state_at(0.0).knob_ft
             for aim in AIMS]
    for axis in range(3):
        spread = max(k[axis] for k in knobs) - min(k[axis] for k in knobs)
        assert spread < 0.5, f"load pose wanders {spread:.2f} ft on axis {axis}"


# ---- The bat lies where the player pointed it -------------------------------
# What used to live here walked the true long axis out of `collision_angled`
# empirically, because the engine's rectangle and the drawn bat were two
# objects that had to be checked against each other — and because that
# rectangle spent the life of the project mirrored across the horizontal, so
# aiming at a low pitch tilted the barrel *up*. Both the rectangle and the
# function are gone: the bat is solved directly onto the hands-to-cursor line
# in `_contact_pose`, which has no sign to get wrong.
#
# `test_the_whole_bat_projects_onto_the_hands_to_cursor_line` below is the
# successor pin, and it is strictly stronger — it holds for every point of the
# bat rather than for its bearing. This one guards the direction, which is the
# half the sign bug broke.

@pytest.mark.parametrize("hand", HANDS)
def test_aiming_low_points_the_barrel_low(hand):
    """The regression the `collision_angled` sign fix was about.

    Because the bat is long and thin, mirroring its tilt changed its effective
    reach as a *function of aim height*: contact ran 67% on low pitches against
    93% in the middle of the zone. Stated in screen pixels because that is
    where the player is aiming and where the fault was visible.
    """
    cam = bp.DEFAULT_CAMERA
    pivot = bp.PIVOT_PX[hand]
    previous = None
    for cursor_y in (545, 485, 425):
        s = bp.swing(bp._to_ft((630, cursor_y)), hand)
        st = s.state_at(bp.SWING_DURATION_S)
        barrel_y = cam.project(*st.barrel_ft)[1]
        knob_y = cam.project(*st.knob_ft)[1]
        # Aim below the hands and the barrel goes below them, and vice versa.
        assert (barrel_y > knob_y) is (cursor_y > pivot[1])
        # And it tracks the cursor monotonically, with no fold in the middle.
        if previous is not None:
            assert barrel_y < previous
        previous = barrel_y


# ---- The contact pose -------------------------------------------------------

@pytest.mark.parametrize("hand", HANDS)
@pytest.mark.parametrize("aim", AIMS)
def test_the_sweet_spot_at_contact_lands_under_the_cursor(hand, aim):
    """The pin, and it is a *screen* pin because the aim is a screen point.

    A cursor names a ray. The sweet spot has to sit on that ray at the depth
    the bat reaches, which is not the same world point as the aim resolved at
    the plate — it is 7% further out and a couple of inches higher. Asserting
    the world coordinates instead would be asserting that the player aims at
    the plate, which is exactly the bias `_unproject` exists to remove.
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

    How far the aim point sits from the hands is how much the bat is
    foreshortened, so a pitch inside — close to the hands — is met well out in
    front, and one away is met deeper. That is real: MLB contact depth runs
    about 3 ft out front on a pulled inside pitch down to roughly the plate on
    a ball served the other way. Nothing here is tuned to produce it; it falls
    out of `cos(psi) = d / HANDS_TO_SWEET_SPOT_FT`.
    """
    depths = [bp.swing(_mirror((x, 2.5), hand), hand).contact_depth_ft
              for x in (0.7, 0.35, 0.0, -0.35, -0.7, -1.2)]
    assert depths == sorted(depths, reverse=True), "inside must be met further out front"
    assert 2.4 < depths[0] < 3.2, "a pulled inside pitch is met well out front"
    assert 0.0 < depths[-1] < 1.0, "a ball low and away is met at the plate"
    assert 1.8 < depths[2] < 2.8, "an ordinary pitch is met about 2 ft out front"


@pytest.mark.parametrize("hand", HANDS)
@pytest.mark.parametrize("aim", AIMS)
def test_the_whole_bat_projects_onto_the_hands_to_cursor_line(hand, aim):
    """The bat lies along the axis the old rectangle was rotated to, exactly.

    Perspective maps lines to lines, so pinning the knob onto the pivot pixel
    and the sweet spot onto the cursor pixel puts *every* point of the bat on
    the line between them — including the tip, which is past the cursor. This
    is the stronger form of the property the world-space `bat_axis` test used
    to check, and it is what makes the drawn bat and the graded bat one object.
    """
    aim = _mirror(aim, hand)
    s = bp.swing(aim, hand)
    st = s.state_at(bp.SWING_DURATION_S)
    cam = bp.DEFAULT_CAMERA
    pivot = bp.PIVOT_PX[hand]
    cursor = (cam.screen_center_x - aim[0] * cam.scale_x / cam.cam_dist,
              cam.screen_center_y - (aim[1] - cam.cam_height) * cam.scale_y / cam.cam_dist)
    dx, dy = cursor[0] - pivot[0], cursor[1] - pivot[1]
    span = math.hypot(dx, dy)
    for point in (st.knob_ft, st.sweet_spot_ft, st.barrel_ft):
        px, py, _ = cam.project(*point)
        off = abs((px - pivot[0]) * dy - (py - pivot[1]) * dx) / span
        assert off == pytest.approx(0.0, abs=1e-6)


@pytest.mark.parametrize("hand", HANDS)
def test_the_depth_lead_is_bounded_by_the_geometry_not_by_a_cap(hand):
    """The barrel leads the hands in depth by exactly what the perspective
    demands, and nothing caps it because nothing needs to: the camera is 30 ft
    back, so the most foreshortened a bat can get is pointing straight down the
    view — very nearly the y axis — and it is only 2.46 ft long. Contact depth
    therefore cannot pass `HAND_CONTACT_DEPTH_FT + HANDS_TO_SWEET_SPOT_FT`
    however the player aims.

    The *lower* end is bounded by geometry too, and it is not
    `HAND_CONTACT_DEPTH_FT`. A ball the bat cannot span is met off the
    quadratic's vertex, where the barrel trails the hands rather than leading
    them — so the lead goes slightly negative and contact depth dips below the
    hands. It used to floor at exactly the hands' depth with a lead of exactly
    zero, which pinned the bat flat in the plane of the plate and, once the
    bearing was read as the ball's direction, stacked a tenth of all contact on
    one spray angle. What bounds the trail is still the bat's own length."""
    assert not hasattr(bp, "MAX_CONTACT_LEAD_DEG")
    ceiling = bp.HAND_CONTACT_DEPTH_FT + bp.HANDS_TO_SWEET_SPOT_FT
    leads = []
    for x in (0.7, 0.0, -0.7, -1.2):
        s = bp.swing(_mirror((x, 2.5), hand), hand)
        assert -0.2 <= s.contact_axis[1] <= 1.0
        assert -1e-9 <= s.contact_depth_ft <= ceiling
        leads.append(s.contact_axis[1])
    assert leads == sorted(leads, reverse=True)


@pytest.mark.parametrize("hand", HANDS)
def test_even_an_absurd_aim_keeps_the_bat_on_a_body(hand):
    """A cursor anywhere on the screen, including well off the plate, has to
    produce a bat a person could be holding. The reach case is the one with a
    cap on it (`MAX_HAND_SLIDE_FT`), and past that the bat honestly falls
    short of the cursor rather than the hands being flung after it.

    Contact depth floors at the plate, not at the hands: on a ball the bat
    cannot span the barrel trails the hands (see
    `test_the_depth_lead_is_bounded_by_the_geometry_not_by_a_cap`)."""
    ceiling = bp.HAND_CONTACT_DEPTH_FT + bp.HANDS_TO_SWEET_SPOT_FT
    for sx in range(0, 1281, 80):
        for sy in range(200, 721, 40):
            s = bp.swing(bp._to_ft((sx, sy)), hand)
            assert -1e-9 <= s.contact_depth_ft <= ceiling
            reach = math.hypot(s.hands_contact[0] - s.spine_xy[0],
                               s.hands_contact[1] - s.spine_xy[1])
            assert reach < 3.2


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
    point, about 3.7 ft — implies ~1600 deg/s, which is also right."""
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
    assert bc.margin_ft(1.4) > bc.margin_ft(1.0) > bc.margin_ft(0.7)
    assert bc.margin_ft(1.0, power=True) < bc.margin_ft(1.0)
    assert (bc.timing_assist_s(1.5) > bc.timing_assist_s(1.0)
            > bc.timing_assist_s(0.4))
    assert bc.foul_threshold(1.5) < bc.foul_threshold(1.0) < bc.foul_threshold(0.4)


def _manager_args():
    """HitOutcomeManager's constructor signature, filled with throwaways."""
    import inspect
    params = list(inspect.signature(HitOutcomeManager.__init__).parameters)[1:]
    return [None] * len(params)
