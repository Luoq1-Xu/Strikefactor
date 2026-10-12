"""Does the trajectory the player is shown agree with the contact they made.

Reported as: the swing replay says the bat was 1.2 inches *over* the ball, and
the ball is then animated as a fly ball. It was real, and it was not a display
bug — the replay was the honest half.

`hit_outcome_manager._classify_batted_ball_type` used to be a weighted random
roll over the four shapes, in which the vertical offset only tilted a Gaussian
weight and so never fixed the *sign* of the launch. At 1.2 in over the ball it
drew a FLY 11% of the time and a LINER 30%; measured over recorded play, 14.8%
of every bat-over-the-ball contact came out airborne and 29.2% of bat-under
contacts came out grounders.

Its first replacement was a fit on the vertical offset alone
(`ball_flight.launch_angle_deg`), with a bounded jitter that existed to keep a
bat over the ball from ever producing a fly ball. The launch angle is now the
vertical reading of one collision between the bat and the ball
(`bat_ball_collision`, stamped on the `Contact`), which holds the same
guarantee with no jitter to bound. What is checked here is that guarantee
through the real chain — a swing, a pitch, the sweep — and that nothing
downstream works the angle out a second time.
"""

import inspect

import pytest

from strikefactor.gameplay import ball_flight as bf
from strikefactor.gameplay import bat_contact as bc
from strikefactor.gameplay import bat_path as bp
from strikefactor.gameplay import hit_animation
from strikefactor.gameplay.hit_outcome_manager import HitOutcomeManager
from tools import calibrate_contact as harness

HANDS = ("R", "L")
AIRBORNE = ("FLY", "POP_UP")
UNDERCUT_IN = bc.SWING_UNDERCUT_FT * 12.0

# Far enough off centre that nothing about the swing can argue with the sign.
# They are not the same distance either side, because dead centre is not the
# middle of the launch range: a ball struck there leaves at about 8 degrees,
# already a ground ball. So half an inch over is decisive, and it takes an
# inch under to be sure of getting the ball off the ground when the swing is
# late and the pitch is low.
DECISIVE_OVER_IN = 0.5
DECISIVE_UNDER_IN = 1.0

# Residual timing errors to sweep, in ms, at a difficulty whose assist leaves
# nearly all of them on the bat. Early, on time, late and later.
TIGHT = dict(timing_window_mult=0.2)
TIMINGS_MS = (-12.0, 0.0, 14.0, 22.0)
LOCATIONS = ((0.0, 2.5), (0.6, 3.2), (-0.6, 3.2), (0.6, 1.8), (-0.6, 1.8))


def swing_through(hand, x, z, bat_over_in, timing_ms=0.0, **kw):
    """One real contact, with the bat aimed `bat_over_in` above the ball's
    centre (negative is under it). None on a whiff."""
    tr = harness._pitch(hand, x, z, 93.0)
    cx, cz = harness._cursor_on_ball(tr)
    # `aim_at_pitch` puts a cursor on the ball `SWING_UNDERCUT_FT` under its
    # centre, so the cursor is raised by that much to state the aim from the
    # centre itself.
    cursor = (cx, cz + (bat_over_in + UNDERCUT_IN) / 12.0)
    swing = bp.swing(bc.aim_at_pitch(cursor, tr, hand), hand)
    start = (tr.time_at_depth(swing.contact_depth_ft) - bp.SWING_DURATION_S
             + timing_ms / 1000.0)
    return bc.resolve_contact(swing, tr, start, **kw)


def contacts(hand):
    """Every contact in a grid of aims, locations and timings, for one hand."""
    out = []
    for x, z in LOCATIONS:
        for step in range(-10, 11):
            for ms in TIMINGS_MS:
                got = swing_through(hand, x, z, step * 0.25, ms, **TIGHT)
                if got is not None:
                    out.append(got)
    return out


def shape_of(contact):
    """The production path from a contact to a batted-ball type."""
    return HitOutcomeManager._classify_batted_ball_type(
        HitOutcomeManager.launch_angle_deg(contact))


# ---- The reported bug ------------------------------------------------------

@pytest.mark.parametrize("hand", HANDS)
def test_the_bat_over_the_ball_is_never_a_fly_ball(hand):
    """The complaint, stated directly and swept across every contact the grid
    produces: early and late, at five places in the zone, from a bat grazing
    the top of the ball to one grazing the bottom.

    Read off the contact's *own* offset, which is the number the replay shows
    the player. Scraping the top of the ball sends it into the ground; it does
    not send it into the outfield air.
    """
    over = [c for c in contacts(hand)
            if c.vertical_offset_ft * 12.0 <= -DECISIVE_OVER_IN]
    assert len(over) > 100, "the sweep found too few bat-over contacts"
    for c in over:
        assert shape_of(c) not in AIRBORNE, (
            "bat %.2f in over the ball launched at %+.1f deg" % (
                -c.vertical_offset_ft * 12.0, c.launch_deg))


@pytest.mark.parametrize("hand", HANDS)
def test_the_bat_well_under_the_ball_is_never_a_grounder(hand):
    """The mirror, which the weighted roll got wrong just as often — 29.2% of
    recorded bat-under contacts were classified GROUNDER."""
    under = [c for c in contacts(hand)
             if c.vertical_offset_ft * 12.0 >= DECISIVE_UNDER_IN
             # A ball clipped so thinly that it carried on backward has no
             # launch angle worth the name; it is a foul tip.
             and c.exit_direction[1] > 0.0]
    assert len(under) > 60, "the sweep found too few bat-under contacts"
    for c in under:
        assert shape_of(c) != "GROUNDER", (
            "bat %.2f in under the ball launched at %+.1f deg" % (
                c.vertical_offset_ft * 12.0, c.launch_deg))


def test_quality_is_not_an_input_to_the_geometry_at_all():
    """The old model's quality bias ran to -0.85 for pop-ups and +0.55 for
    liners, so how hard the ball was struck argued with which way it left.
    Squaring up a ball you caught the top of does not lift it.

    Asserted against the *signature* rather than by sweeping quality, which is
    the stronger statement now available: quality cannot overturn the geometry
    because it is not passed to it. A sweep would pass whatever the loop chose
    and see no effect, which is exactly what a silently-ignored argument also
    looks like."""
    params = inspect.signature(
        HitOutcomeManager._classify_batted_ball_type).parameters
    assert list(params) == ["launch_deg"], (
        "the batted-ball band takes the launch angle and nothing else; got %s"
        % list(params))
    # And neither do the two functions that produce the angle.
    from strikefactor.gameplay import bat_ball_collision
    for fn in (bat_ball_collision.exit_direction,
               bat_ball_collision.first_touch_normal):
        assert "quality" not in inspect.signature(fn).parameters


# ---- The model itself ------------------------------------------------------

@pytest.mark.parametrize("hand", HANDS)
def test_the_contact_a_swing_is_for_is_a_line_drive(hand):
    """A cursor on the ball, timed right: the bat `SWING_UNDERCUT_FT` under
    the ball's centre, and a line drive over most of the zone.

    Not all of it, and the exception is baseball. Low and away the bat is
    barrel-down and behind square, the ball slides down it as it leaves, and
    the best swing there is a hard ground ball the other way. Up in the zone
    the same swing gets the ball in the air.
    """
    launches = {}
    for x, z in LOCATIONS:
        got = swing_through(hand, x, z, -UNDERCUT_IN)
        assert got.quality > 0.96
        launches[(x, z)] = got.launch_deg
        assert 5.0 < got.launch_deg < 28.0, (x, z, got.launch_deg)
    assert shape_of(swing_through(hand, 0.0, 2.5, -UNDERCUT_IN)) == "LINER"
    assert launches[(-0.6, 1.8)] == min(launches.values())
    assert launches[(-0.6, 1.8)] < launches[(-0.6, 3.2)] - 10.0


@pytest.mark.parametrize("hand", HANDS)
def test_a_ball_struck_dead_centre_is_a_hard_ground_ball(hand):
    """Why the swing aims under the centre and not at it. With the bat's axis
    on the ball's own line the ball leaves between the bat's path and the
    pitch's — about eight degrees up, which is the top of the ground-ball
    band. `ZERO_OFFSET_LAUNCH_DEG` said sixteen, and it was a fitted number."""
    got = swing_through(hand, 0.0, 2.5, 0.0)
    assert abs(got.vertical_offset_ft * 12.0) < 0.05
    assert 4.0 < got.launch_deg < bp.ATTACK_ANGLE_DEG
    assert shape_of(got) == "GROUNDER"


@pytest.mark.parametrize("hand", HANDS)
def test_the_launch_angle_rises_with_the_undercut_at_a_real_rate(hand):
    """Monotone *and* responsive. A test that asserted only monotonicity
    would pass on a step function; the useful property is the rate, and it is
    about thirty degrees an inch through the centre."""
    over = [1.5 - 0.25 * i for i in range(13)]          # 1.5 over .. 1.5 under
    launches = [swing_through(hand, 0.0, 2.5, o).launch_deg for o in over]
    assert launches == sorted(launches)
    centre = len(over) // 2
    rate = (launches[centre + 2] - launches[centre - 2]) / 1.0
    assert 24.0 < rate < 36.0, f"{rate:.0f} deg of launch per inch"


def test_every_shape_is_reachable_from_a_contact_that_can_happen():
    """The defect that made pop-ups 1.0% of play against MLB's 7%: the old
    POP_UP anchor named an offset at which a bat and a ball are no longer
    touching. Every shape must come off some bat that met the ball."""
    reachable = {shape_of(swing_through("R", 0.0, 2.5, 2.0 - 0.1 * i))
                 for i in range(41)}
    assert reachable == {"GROUNDER", "LINER", "FLY", "POP_UP"}


def test_one_contact_has_one_launch_angle():
    """Nothing is drawn. The fit this replaced carried a jitter, so the angle
    had to be drawn once and carried, and the animation's fallback drew it
    again. Asking the same contact any number of times gives one answer."""
    got = swing_through("R", 0.2, 2.6, -0.3, 6.0, **TIGHT)
    manager = HitOutcomeManager(None, None)
    asked = {manager.launch_angle_deg(got) for _ in range(50)}
    assert asked == {got.launch_deg}


def test_the_launch_angle_fit_is_gone():
    """`ball_flight.launch_angle_deg(vertical_offset_in)` read the vertical
    half of the collision off the offset alone: an intercept, a gain on the
    normal's rise and a bounded scatter. It could not know that on a tilted
    bat the same undercut also turns the ball sideways, and its response was
    a little over half what a bat and a ball give. None of its names may come
    back, and the animation's second copy of it goes with them."""
    for name in ("launch_angle_deg", "ZERO_OFFSET_LAUNCH_DEG", "NORMAL_GAIN",
                 "CONTACT_NORMAL_RADIUS_IN", "LAUNCH_JITTER_DEG",
                 "JITTER_LIMIT_SIGMA"):
        assert not hasattr(bf, name), name
    assert not hasattr(hit_animation, "_shape_from_offset")
    assert not hasattr(hit_animation, "_OFFSET_PX_TO_IN")
    assert "vertical_offset" not in inspect.signature(
        hit_animation.HitAnimation.__init__).parameters
    # The bands and the classifier are what `ball_flight` keeps.
    assert bf.shape_for_launch_angle(9.9) == "GROUNDER"
    assert bf.shape_for_launch_angle(10.0) == "LINER"
    assert bf.shape_for_launch_angle(25.0) == "FLY"
    assert bf.shape_for_launch_angle(50.0) == "POP_UP"


# ---- The animation is told, it does not work it out -------------------------

def test_a_supplied_type_still_wins():
    """The canonical source is `hit_outcome_manager`."""
    for t in ("GROUNDER", "LINER", "FLY", "POP_UP"):
        assert hit_animation._pick_shape("IN_PLAY", t) == t
        assert hit_animation._pick_shape("FOUL", t, launch_deg=70.0) == t
    assert hit_animation._pick_shape("HOME RUN", "GROUNDER") == "FLY"


@pytest.mark.parametrize("outcome", ["IN_PLAY", "FOUL"])
def test_a_caller_with_only_a_launch_angle_gets_its_band(outcome):
    """Through the one classifier, so the animation cannot disagree with
    `hit_outcome_manager` about what an angle is called."""
    for angle in (-30.0, 5.0, 12.0, 24.9, 25.0, 49.0, 50.0, 80.0):
        assert hit_animation._pick_shape(outcome, None, angle) == (
            bf.shape_for_launch_angle(angle))


def test_a_foul_can_pop_up():
    """POP_UP needed an offset over 25 px on the oldest fallback and bat and
    ball stop touching at 17.2, so no foul animated as a pop-up — which is
    the single most ordinary thing a foul ball does."""
    assert hit_animation._pick_shape("FOUL", None, 68.0) == "POP_UP"


def test_a_flyout_stays_airborne():
    """The bands may only choose *which* airborne shape a flyout was. A
    ball caught on the fly cannot be animated as a ball that never left the
    dirt, whatever the angle says."""
    for angle in (-20.0, 5.0, 15.0, 30.0, 60.0, None):
        assert hit_animation._pick_shape("FLYOUT", None, angle) in AIRBORNE


def test_a_caller_who_states_nothing_gets_a_line_drive():
    """There is no geometry left in the animation to fall back on, by design:
    only the caller has the contact. Deterministic, where the fallback it
    replaced drew a jittered angle off a vertical offset."""
    for outcome in ("IN_PLAY", "FOUL"):
        assert {hit_animation._pick_shape(outcome) for _ in range(20)} == {
            hit_animation.DEFAULT_SHAPE}
    assert hit_animation.DEFAULT_SHAPE == "LINER"


# ---- The tables must not come back -----------------------------------------

def test_the_prior_tables_are_gone():
    """Same shape as `test_the_dilation_correction_constants_are_gone`: these
    were a second model of a thing the geometry already answered, and two of
    them were tuned against a `ft_per_px_z` that has since changed. A
    reintroduction would be silent."""
    import strikefactor.gameplay.hit_outcome_manager as hom
    for name in ("_TYPE_OFFSET_ANCHORS", "_TYPE_OFFSET_SIGMA",
                 "_TYPE_QUALITY_BIAS", "_TYPE_BASE_PRIOR",
                 "_BATTED_BALL_TYPES", "INCHES_PER_FT"):
        assert not hasattr(hom, name), name
