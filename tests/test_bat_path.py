"""Where the bat is, and whether it is where the engine said it was.

The replay's whole claim is that it shows the swing that actually happened.
That claim rests on two pins and one calibration:

  * the geometry constants restated in `bat_path` really are the ones
    `HitOutcomeManager` swings;
  * the drawn bat's screen-plane orientation matches the rectangle
    `collision_angled` tested — its (x, z) projection lies along that ray.
    The depth component is deliberately free: the engine's rectangle has no
    depth axis, so pinning it to zero was a choice, and the choice drew the
    hands directly under the ball;
  * the barrel arrives at contact at a real MLB bat speed, which is what
    separates a kinematic model from an easing curve.

Everything else here guards properties that were wrong in a draft or shipped
wrong: a barrel that loaded toward the pitcher, a swing whose rotation all
happened in the last few milliseconds, a bat that dropped below the knees at
load, a swing modelled as its own finish minus some rotation (which started
the barrel below the ball and swept it up out of the ground instead of down
off the shoulder), and — the faults the hands-first model exists for — a
barrel path that plunged vertically and then reversed depth in a sharp V on
an ordinary mistimed contact, with the knob derived backwards into places no
body could put it.
"""

import math

import pytest

from strikefactor.gameplay import bat_path as bp
from strikefactor.gameplay.hit_outcome_manager import HitOutcomeManager
from strikefactor.utils.physics import collision_angled

HANDS = ("R", "L")


# ---- Pins to the engine's own geometry --------------------------------------

def test_pivots_match_the_hit_outcome_manager():
    """`bat_path` restates these so a pure module need not import gameplay.
    If they drift, the replay draws a bat the engine never swung."""
    mgr = HitOutcomeManager.__new__(HitOutcomeManager)
    HitOutcomeManager.__init__(mgr, *_manager_args())
    assert bp.PIVOT_PX["R"] == tuple(float(v) for v in mgr.rhpos)
    assert bp.PIVOT_PX["L"] == tuple(float(v) for v in mgr.lhpos)


def test_contact_zone_matches_the_engine_rectangle():
    """120 x 50 on a contact swing, 120 x 25 on a power swing, and the cursor
    30 px inboard of the centre — read straight out of
    `get_ball_to_bat_contact_outcome`."""
    import inspect
    src = inspect.getsource(HitOutcomeManager.get_ball_to_bat_contact_outcome)
    assert "base_contact_zone_height = 50 if swing_type == 1 else 25" in src
    assert "base_contact_zone_width = 120" in src
    assert "(30 * x)" in src
    assert bp.CONTACT_ZONE_WIDTH_PX == 120.0
    assert bp.CONTACT_ZONE_HEIGHT_PX == {1: 50.0, 2: 25.0}
    assert bp.CURSOR_TO_ZONE_CENTRE_PX == 30.0


def test_swing_duration_is_the_engines_150ms():
    """The bat lag the whole timing system is built on."""
    assert bp.SWING_DURATION_MS == 150
    assert bp.SWING_DURATION_S == pytest.approx(0.150)


# ---- The mirror -------------------------------------------------------------

@pytest.mark.parametrize("cursor", [
    (630, 520),   # low and away from a RH pivot
    (630, 420),   # high
    (560, 500),   # inside
    (700, 470),   # away
])
def test_bat_axis_matches_the_rectangle_collision_angled_tests(cursor):
    """The drawn bat must lie along the rectangle the engine actually tests.

    Walks the true long axis out of `collision_angled` itself rather than
    trusting either function's arithmetic, which is what let this survive the
    sign fix in `collision_angled` unchanged: before it, both sides were
    mirrored and agreed; after it, neither is and they still agree. A test
    written against the *expected* angle instead would have had to be edited
    in lockstep with the bug, and so would have proved nothing."""
    pivot = bp.PIVOT_PX["R"]
    angle = math.atan2(cursor[1] - pivot[1], cursor[0] - pivot[0])
    centre = (cursor[0] - 30.0, cursor[1])

    # Probe a ring just outside the rectangle's half-height but inside its
    # half-width; only bearings along the true long axis register.
    inside = []
    for deg in range(0, 360):
        a = math.radians(deg)
        px = centre[0] + 55.0 * math.cos(a)
        py = centre[1] + 55.0 * math.sin(a)
        if collision_angled(px, py, 0.001, centre[0], centre[1], 120.0, 50.0, angle):
            inside.append(a)
    assert inside, "probe radius must straddle the rectangle"

    # Mean direction of the lobe pointing away from the pivot.
    outboard = [a for a in inside if math.cos(a) > 0]
    mean = math.atan2(sum(math.sin(a) for a in outboard) / len(outboard),
                      sum(math.cos(a) for a in outboard) / len(outboard))
    screen_axis = (math.cos(mean), math.sin(mean))

    # The same axis in world feet, via bat_axis. Screen-x maps to world-x and
    # screen-y to world-z with both signs flipped, so a screen direction
    # (dx, dy) is a world direction proportional to (-dx/sx, -dy/sz).
    aim_ft = bp._to_ft(cursor)
    got = bp.bat_axis(aim_ft, bp.pivot_ft("R"))
    cam = bp.DEFAULT_CAMERA
    want = (-screen_axis[0] / cam.scale_x, -screen_axis[1] / cam.scale_y)
    mag = math.hypot(*want)
    want = (want[0] / mag, want[1] / mag)

    assert got[0] == pytest.approx(want[0], abs=0.02)
    assert got[1] == pytest.approx(want[1], abs=0.02)


@pytest.mark.parametrize("cursor", [(630, 520), (630, 420), (560, 500), (700, 470)])
@pytest.mark.parametrize("hand", HANDS)
def test_bat_axis_is_the_pivot_to_cursor_ray(cursor, hand):
    """The bat points from the hands at what the player is aiming at.

    Obvious, and it was false until the `collision_angled` sign fix: the
    engine's rectangle sat mirrored across the horizontal, so aiming at a low
    pitch tilted the barrel *up*.
    """
    aim = bp._to_ft(cursor)
    pivot = bp.pivot_ft(hand)
    ray = (aim[0] - pivot[0], aim[1] - pivot[1])
    mag = math.hypot(*ray)
    got = bp.bat_axis(aim, pivot)
    assert got[0] == pytest.approx(ray[0] / mag)
    assert got[1] == pytest.approx(ray[1] / mag)


@pytest.mark.parametrize("deg", [-40, -20, 0, 15, 30, 55])
def test_collision_angled_tests_a_rectangle_at_the_angle_it_was_given(deg):
    """The regression pin, one level below `bat_axis`.

    `collision_angled` rotated the circle by `+angle` and tested an
    axis-aligned box, which is a test against a box at `-angle` — against its
    own docstring, which said it was rotating the point *back*. Because the
    rectangle is long and thin, the mirror changed the bat's effective reach
    as a function of aim height: contact ran 67% on low pitches against 93% in
    the middle of the zone, and correcting the sign flattens it to 80 / 86.
    """
    angle = math.radians(deg)
    centre = (600.0, 480.0)
    inside = [math.radians(d) for d in range(360)
              if collision_angled(centre[0] + 55.0 * math.cos(math.radians(d)),
                                  centre[1] + 55.0 * math.sin(math.radians(d)),
                                  0.001, centre[0], centre[1], 120.0, 50.0, angle)
              and math.cos(math.radians(d) - angle) > 0]
    assert inside, "probe radius must straddle the rectangle"
    mean = math.degrees(math.atan2(sum(math.sin(a) for a in inside) / len(inside),
                                   sum(math.cos(a) for a in inside) / len(inside)))
    assert mean == pytest.approx(deg, abs=1.0)


# ---- Both ends pinned -------------------------------------------------------

@pytest.mark.parametrize("hand", HANDS)
@pytest.mark.parametrize("depth", [-3.0, 0.0, 2.7])
def test_the_sweet_spot_at_contact_is_exactly_where_the_ball_was(hand, depth):
    """The pin. At `SWING_DURATION_S` the bat sits at the aim point the
    collision used, at the depth the trajectory says the ball was — so the
    replay cannot show a bat somewhere the engine never tested."""
    aim = (0.35, 2.4)
    s = bp.swing(aim_ft=aim, contact_depth_ft=depth,
                 handedness=hand, swing_type=1)
    st = s.state_at(bp.SWING_DURATION_S)
    assert st.sweet_spot_ft[0] == pytest.approx(aim[0], abs=1e-6)
    assert st.sweet_spot_ft[1] == pytest.approx(depth, abs=1e-6)
    assert st.sweet_spot_ft[2] == pytest.approx(aim[1], abs=1e-6)


@pytest.mark.parametrize("hand", HANDS)
def test_the_bat_is_a_rigid_body(hand):
    """Knob to barrel is one bat length at every instant, not just at contact."""
    s = bp.swing((0.0, 2.5), 1.0, hand, 1)
    for st in s.barrel_track(24):
        length = math.dist(st.knob_ft, st.barrel_ft)
        assert length == pytest.approx(bp.BAT_LENGTH_FT, abs=1e-6)


# ---- Bat speed --------------------------------------------------------------

@pytest.mark.parametrize("hand", HANDS)
def test_barrel_reaches_mlb_bat_speed_at_contact(hand):
    """The check that SWING_EASE_K is kinematics and not a shape parameter:
    peak angular speed times the barrel radius has to come out at a real bat
    speed. MLB average is ~72 mph."""
    s = bp.swing((0.0, 2.5), 0.0, hand, 1)
    assert s.state_at(bp.SWING_DURATION_S).speed_mph == pytest.approx(72.0, abs=0.5)


@pytest.mark.parametrize("hand", HANDS)
def test_the_swing_accelerates_into_contact(hand):
    """Fastest at contact, and building the whole way. A linear sweep would
    move the barrel at its average speed throughout — the same mistake as
    flying a batted ball at its average speed. Not strictly monotone any
    more: the load terms contribute real speed mid-swing and hand it over to
    the rotation, so a fraction of a mph may wash between samples."""
    s = bp.swing((0.0, 2.5), 0.0, hand, 1)
    speeds = [st.speed_mph for st in s.barrel_track(32)]
    for a, b in zip(speeds, speeds[1:]):
        assert b > a - 0.75
    assert speeds[0] < 1.0
    assert speeds[-1] > speeds[len(speeds) // 2] * 1.8


@pytest.mark.parametrize("depth", [-3.0, -2.7, 0.0, 2.5, 2.7])
@pytest.mark.parametrize("aim", [(0.0, 1.6), (0.0, 2.5), (0.2, 3.4)])
def test_peak_speed_is_not_wildly_front_loaded_in_the_arc(depth, aim):
    """The ease exponent is solved per swing now — the rotation radius
    depends on where the ball was met — but the peak-to-mean angular speed
    ratio *is* k, and a draft that forced it to 2.93 read as a bat that
    stands still and then teleports. Everything a player ordinarily hits
    must stay inside the rails."""
    s = bp.swing(aim, depth, "R", 1)
    assert 1.6 <= s.ease_k <= 3.0


# ---- The load position ------------------------------------------------------

@pytest.mark.parametrize("hand,side", [("R", 1.0), ("L", -1.0)])
def test_the_barrel_loads_behind_the_batter_not_in_front(hand, side):
    """Without the handedness spin, both hitters loaded their barrel toward
    the *pitcher* — the finish of a swing drawn as its start."""
    s = bp.swing((0.0, 2.5), 0.0, hand, 1)
    start = s.state_at(0.0).sweet_spot_ft
    assert start[1] < -1.0, "barrel should start behind the plate"
    assert start[0] * side > 0, "barrel should start on the batter's own side"


@pytest.mark.parametrize("hand", HANDS)
def test_the_barrel_never_drops_below_the_knees(hand):
    """The plane is a tilted circle, so it bottoms out a quarter turn before
    contact and comes back. Read as a ramp instead it just keeps going down,
    which is what buried the barrel."""
    s = bp.swing((0.0, 2.5), 0.0, hand, 1)
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
    s = bp.swing(aim, 0.0, hand, 1)
    track = [st.sweet_spot_ft[2] for st in s.barrel_track(40)]
    assert track[0] > 5.0, "the barrel should load at shoulder height or above"
    # Clear of the ball it will meet, by a margin that *shrinks* as the pitch
    # gets higher — 3.6 ft of drop to a knee-high pitch against 1.8 to one at
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
    s = bp.swing((0.0, 2.5), 0.0, hand, 1)
    load, contact = s.state_at(0.0), s.state_at(bp.SWING_DURATION_S)
    barrel_drop = load.barrel_ft[2] - contact.barrel_ft[2]
    hand_drop = load.knob_ft[2] - contact.knob_ft[2]
    assert barrel_drop > 3.0
    assert 0.3 < hand_drop < barrel_drop / 2


@pytest.mark.parametrize("hand", HANDS)
@pytest.mark.parametrize("aim", [(0.0, 1.6), (0.0, 2.5), (0.2, 3.4)])
def test_the_ball_is_met_on_the_way_up_at_the_swing_plane(hand, aim):
    """"Met on the way up" is a fact about the barrel at *contact*, not about
    where the swing started — the assertion this replaces confused the two and
    so was satisfied by a bat rising out of the dirt.

    Every load term is flat at contact by construction (`ON_PLANE_EASE >= 2`),
    which is what leaves the tilted plane as the only thing acting there and
    makes the attack angle exactly `SWING_PLANE_DEG`. If a load term ever
    stops being flat, this is where it shows up.
    """
    s = bp.swing(aim, 0.0, hand, 1)
    a = s.state_at(bp.SWING_DURATION_S * 0.999).sweet_spot_ft
    b = s.state_at(bp.SWING_DURATION_S).sweet_spot_ft
    rise = b[2] - a[2]
    run = math.hypot(b[0] - a[0], b[1] - a[1])
    assert math.degrees(math.atan2(rise, run)) == pytest.approx(
        bp.SWING_PLANE_DEG, abs=0.2)


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


# ---- The contact pose -------------------------------------------------------

def _contact_axis(swing_obj):
    """The drawn bat's unit axis at contact, knob to barrel."""
    st = swing_obj.state_at(bp.SWING_DURATION_S)
    return tuple((st.barrel_ft[i] - st.knob_ft[i]) / bp.BAT_LENGTH_FT
                 for i in range(3))


@pytest.mark.parametrize("hand", HANDS)
@pytest.mark.parametrize("depth", [-2.7, 0.0, 2.5])
def test_the_bat_at_contact_projects_onto_the_engines_rectangle(hand, depth):
    """The engine's rectangle lives in the plane of the screen, so it pins
    exactly two of the drawn axis's three components: the (x, z) projection
    must lie along the pivot-to-aim ray `collision_angled` tested, pointing
    outboard. The depth component is deliberately free — see
    `bat_path._contact_lead` — because the engine never had an opinion on it,
    and zeroing it drew the hands directly under the ball."""
    aim = (0.35 if hand == "R" else -0.35, 2.4)
    s = bp.swing(aim, depth, hand, 1)
    axis3 = _contact_axis(s)
    ax, az = bp.bat_axis(aim, bp.pivot_ft(hand))
    assert axis3[0] * az - axis3[2] * ax == pytest.approx(0.0, abs=1e-9)
    assert axis3[0] * ax + axis3[2] * az > 0.1


@pytest.mark.parametrize("hand", HANDS)
def test_deep_contact_lags_the_barrel_and_early_contact_releases_it(hand):
    """What the freed depth component is *for*. A ball caught 2.7 ft deep is
    an inside-out swing — barrel behind the hands, hands ahead of the ball —
    and a ball met 2.5 ft out front has released past square and is being
    pulled. Both poses are bounded: past `MAX_CONTACT_LEAD_DEG` the orbit
    stretches instead, because a bat cannot fold around its own grip."""
    aim = (0.0, 2.5)
    lead_limit = math.sin(math.radians(bp.MAX_CONTACT_LEAD_DEG)) + 1e-9
    deep = _contact_axis(bp.swing(aim, -2.7, hand, 1))
    early = _contact_axis(bp.swing(aim, 2.5, hand, 1))
    assert deep[1] < -0.2
    assert early[1] > 0.2
    assert abs(deep[1]) <= lead_limit
    assert abs(early[1]) <= lead_limit


@pytest.mark.parametrize("hand", HANDS)
@pytest.mark.parametrize("depth", [-3.0, 0.0, 2.7])
@pytest.mark.parametrize("aim", [(0.0, 1.6), (0.0, 2.5), (0.2, 3.4)])
def test_the_hands_stay_attached_to_a_body(hand, depth, aim):
    """The regression the hands-first model exists for. The old model derived
    the knob backwards from the barrel's circle, which put the hands 2.7 ft
    into the catcher's box on an ordinary late swing. The hands orbit the
    spine now — stretching past their radius only as far as a lunge — and
    they stay at heights a body can hold them, the whole swing long."""
    aim = (aim[0] if hand == "R" else -aim[0], aim[1])
    s = bp.swing(aim, depth, hand, 1)
    for st in s.barrel_track(32):
        reach = math.hypot(st.knob_ft[0] - s.spine_xy[0],
                           st.knob_ft[1] - s.spine_xy[1])
        assert reach < 2.2
        assert 1.8 < st.knob_ft[2] < 5.0


# ---- The loop ---------------------------------------------------------------

@pytest.mark.parametrize("hand", HANDS)
@pytest.mark.parametrize("depth", [-2.7, 0.0, 2.5])
@pytest.mark.parametrize("aim", [(0.0, 1.6), (0.0, 2.5), (0.2, 3.4)])
def test_the_side_view_never_stalls_into_a_cusp(hand, depth, aim, n=96):
    """The V-corner in the old replay was a projected-velocity zero: the
    barrel's depth reversed at an instant when nothing was moving vertically
    either, so the side view drew two straight legs meeting at a point. A
    loop only *rounds* if the projection keeps real speed through the
    turnaround — this is the floor under that, over every ordinary contact."""
    aim = (aim[0] if hand == "R" else -aim[0], aim[1])
    s = bp.swing(aim, depth, hand, 1)
    sweet = [st.sweet_spot_ft for st in s.barrel_track(n)]
    dt = bp.SWING_DURATION_S / (n - 1)
    contact_ft_s = s.state_at(bp.SWING_DURATION_S).speed_mph / bp.MPH_PER_FT_S
    projected = [math.hypot(sweet[i + 1][1] - sweet[i][1],
                            sweet[i + 1][2] - sweet[i][2]) / dt
                 for i in range(int(0.3 * (n - 1)), n - 1)]
    assert min(projected) > 0.10 * contact_ft_s


@pytest.mark.parametrize("hand", HANDS)
@pytest.mark.parametrize("depth", [-2.7, 0.0, 2.5])
def test_the_barrels_depth_reversal_is_not_saved_for_the_last_instant(hand, depth):
    """The old circle placement made the barrel overshoot the contact depth
    and double back at 83% of the swing — the boomerang. The loop's
    turnaround belongs in the body of the swing, not at its end."""
    s = bp.swing((0.0, 2.5), depth, hand, 1)
    ys = [st.sweet_spot_ft[1] for st in s.barrel_track(96)]
    assert ys.index(min(ys)) <= 0.88 * (len(ys) - 1)


# ---- Contact zone -----------------------------------------------------------

def test_power_swing_zone_is_half_the_height_of_a_contact_swing():
    assert bp.contact_zone_ft(2)[1] == pytest.approx(bp.contact_zone_ft(1)[1] / 2)
    assert bp.contact_zone_ft(2)[0] == pytest.approx(bp.contact_zone_ft(1)[0])


def test_difficulty_scales_the_zone_the_player_actually_gets():
    """`contact_zone_size` runs 1.4 at ROOKIE to 0.7 at HALL_OF_FAME and is
    invisible everywhere else in the game."""
    rookie = bp.contact_zone_ft(1, 1.4)
    hof = bp.contact_zone_ft(1, 0.7)
    assert rookie[0] == pytest.approx(hof[0] * 2)
    assert rookie[1] == pytest.approx(hof[1] * 2)


def test_the_zone_is_a_believable_size_in_feet():
    """120 px of bat is a bit over a foot; 50 px of vertical slop is 8 inches."""
    length, height = bp.contact_zone_ft(1)
    assert 1.0 < length < 1.6
    assert 0.5 < height < 0.8


def test_the_projection_is_anisotropic_so_length_and_height_do_not_share_a_scale():
    """A px is 0.0109 ft across and 0.0133 ft down. Treating them as one
    number is the bug `hit_animation._ft_dist` exists to prevent."""
    length, height = bp.contact_zone_ft(1)
    assert length / 120.0 != pytest.approx(height / 50.0)


def _manager_args():
    """HitOutcomeManager's constructor signature, filled with throwaways."""
    import inspect
    params = list(inspect.signature(HitOutcomeManager.__init__).parameters)[1:]
    return [None] * len(params)
