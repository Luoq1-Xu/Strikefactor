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

Two of that model's three tables were also unreachable, which is why the
`test_every_shape_is_reachable` case below is not redundant with the sign
tests: the POP_UP offset anchor sat at 22 px when bat and ball stop touching at
17.2, so pop-ups ran 1.0% of play against MLB's 7% and could only ever win out
of a Gaussian tail.

The replacement is `ball_flight.launch_angle_deg`, which applies the argument
`spray` already makes for the horizontal — a cylinder's surface normal is
radial to its own axis, so the ball leaves perpendicular to the bat — to the
vertical axis, and bands the result by Statcast's cuts.
"""

import math

import pytest

from strikefactor.gameplay import ball_flight as bf
from strikefactor.gameplay import hit_animation
from strikefactor.gameplay.hit_outcome_manager import (
    FT_PER_PX_Z,
    INCHES_PER_FT,
    HitOutcomeManager,
)

AIRBORNE = ("FLY", "POP_UP")
IN_PER_PX = FT_PER_PX_Z * INCHES_PER_FT

# Far enough off centre that no plausible amount of swing-plane scatter should
# be able to argue with the sign. Inside it, near-centred contact is genuinely
# ambiguous and is *supposed* to be.
DECISIVE_IN = 0.6


def classify(offset_px):
    """The production path from a screen-pixel offset to a batted-ball type.

    Two steps now rather than one, and worth spelling out because the split is
    the point: `ball_flight.launch_angle_deg` *draws* the angle (with its
    bounded jitter) and `_classify_batted_ball_type` names the Statcast band it
    fell in. The angle used to be drawn inside the classifier and thrown away,
    which is how a continuous quantity ended up quantised to three values by
    the time anything flew the ball.

    `HitOutcomeManager` is instantiated bare because neither half reads state.
    """
    m = HitOutcomeManager.__new__(HitOutcomeManager)
    return m._classify_batted_ball_type(
        bf.launch_angle_deg(offset_px * IN_PER_PX))


# ---- The reported bug ------------------------------------------------------

@pytest.mark.parametrize("inches", [-2.7, -2.0, -1.5, -1.2, -0.9, -0.6])
def test_the_bat_over_the_ball_is_never_a_fly_ball(inches):
    """The complaint, stated directly and swept across the whole reachable
    over-the-ball range. Scraping the top of the ball sends it into the
    ground; it does not send it into the outfield air."""
    got = [classify(inches / IN_PER_PX) for _ in range(4000)]
    assert not any(s in AIRBORNE for s in got), (
        "bat %.1f in over the ball produced %s" % (
            abs(inches), sorted({s for s in got if s in AIRBORNE})))


@pytest.mark.parametrize("inches", [0.6, 0.9, 1.2, 1.5, 2.0, 2.7])
def test_the_bat_under_the_ball_is_never_a_grounder(inches):
    """The mirror, which the old model got wrong just as often — 29.2% of
    recorded bat-under contacts were classified GROUNDER."""
    got = [classify(inches / IN_PER_PX) for _ in range(4000)]
    assert "GROUNDER" not in got


def test_quality_is_not_an_input_to_the_geometry_at_all():
    """The old model's quality bias ran to -0.85 for pop-ups and +0.55 for
    liners, so how hard the ball was struck argued with which way it left.
    Squaring up a ball you caught the top of does not lift it.

    Asserted against the *signature* rather than by sweeping quality, which is
    the stronger statement now available: quality cannot overturn the geometry
    because it is not passed to it. A sweep would pass whatever the loop chose
    and see no effect, which is exactly what a silently-ignored argument also
    looks like."""
    import inspect
    params = inspect.signature(
        HitOutcomeManager._classify_batted_ball_type).parameters
    assert list(params) == ["launch_deg"], (
        "the batted-ball band takes the launch angle and nothing else; got %s"
        % list(params))
    # And the geometry it bands still holds over the whole reachable undercut.
    got = [classify(-1.2 / IN_PER_PX) for _ in range(2000)]
    assert not any(s in AIRBORNE for s in got)


# ---- The model itself ------------------------------------------------------

def test_a_ball_struck_dead_centre_is_a_line_drive():
    assert bf.shape_for_launch_angle(
        bf.launch_angle_deg(0.0, jitter=False)) == "LINER"


def test_the_launch_angle_rises_with_the_undercut_at_a_real_rate():
    """Monotone *and* responsive. A test that asserted only monotonicity
    would pass on a step function, which is the tautology CLAUDE.md records
    `test_the_attack_angle_is_continuous_across_the_reach_boundary` having
    been — the useful property is the rate."""
    xs = [i * 0.1 for i in range(-27, 28)]
    ys = [bf.launch_angle_deg(x, jitter=False) for x in xs]
    assert ys == sorted(ys)
    # Around the centre the normal turns fastest: ~0.85 rad per radius.
    rate = (bf.launch_angle_deg(0.5, jitter=False)
            - bf.launch_angle_deg(-0.5, jitter=False))
    assert 15.0 < rate < 25.0, "degrees per inch through the centre"


def test_the_normal_comes_all_the_way_round_at_the_touching_offset():
    """At an offset equal to the summed radii the two are exactly tangent, so
    the normal is vertical and the asin saturates rather than going complex."""
    r = bf.CONTACT_NORMAL_RADIUS_IN
    assert bf.launch_angle_deg(r, jitter=False) == pytest.approx(
        bf.ZERO_OFFSET_LAUNCH_DEG + bf.NORMAL_GAIN * 90.0)
    assert bf.shape_for_launch_angle(
        bf.launch_angle_deg(r, jitter=False)) == "POP_UP"
    assert bf.shape_for_launch_angle(
        bf.launch_angle_deg(-r, jitter=False)) == "GROUNDER"
    # Past tangency is not a contact at all, but it must not raise.
    for d in (-4.0, 4.0, -100.0, 100.0):
        assert math.isfinite(bf.launch_angle_deg(d, jitter=False))


def test_every_shape_is_reachable_from_a_contact_that_can_happen():
    """The defect that made pop-ups 1.0% of play against MLB's 7%: the old
    POP_UP anchor named an offset at which a bat and a ball are no longer
    touching. Every shape must be produced by some offset inside tangency."""
    r = bf.CONTACT_NORMAL_RADIUS_IN
    reachable = {
        bf.shape_for_launch_angle(bf.launch_angle_deg(-r + 2 * r * i / 400.0,
                                                      jitter=False))
        for i in range(401)
    }
    assert reachable == {"GROUNDER", "LINER", "FLY", "POP_UP"}


def test_the_bounded_jitter_cannot_outvote_the_geometry():
    """Why the scatter is truncated rather than merely narrow. Asserted at the
    most extreme draw the bound allows, so it cannot pass by luck the way a
    sampled version would — with an unbounded Gaussian this test fails only
    once every few thousand runs, which is the worst possible way to hold a
    guarantee."""
    limit = bf.JITTER_LIMIT_SIGMA * bf.LAUNCH_JITTER_DEG
    hardest_up = bf.launch_angle_deg(-DECISIVE_IN, jitter=False) + limit
    assert bf.shape_for_launch_angle(hardest_up) not in AIRBORNE
    hardest_down = bf.launch_angle_deg(DECISIVE_IN, jitter=False) - limit
    assert bf.shape_for_launch_angle(hardest_down) != "GROUNDER"


def test_the_jitter_really_is_bounded():
    """The bound above is only worth stating if the draw respects it."""
    limit = bf.JITTER_LIMIT_SIGMA * bf.LAUNCH_JITTER_DEG
    drawn = [bf.launch_angle_deg(0.0) for _ in range(20000)]
    assert min(drawn) >= bf.ZERO_OFFSET_LAUNCH_DEG - limit - 1e-9
    assert max(drawn) <= bf.ZERO_OFFSET_LAUNCH_DEG + limit + 1e-9
    # ...and that it is a spread, not a constant the bound happens to contain.
    assert max(drawn) - min(drawn) > limit


# ---- Calibration -----------------------------------------------------------

def test_the_league_type_mix_is_reproduced():
    """GB 42 / LD 24 / FB 27 / PU 7, the 2025 MLB split the old prior tables
    were tuned to hit — the point being that the geometry reaches it without
    a prior, so the marginals and the individual contacts agree.

    Computed by integrating the jitter over the bands rather than sampling:
    deterministic, and it costs nothing. The offset distribution is the
    measured one, which is symmetric because the contact geometry is unbiased
    (a perfect cursor gives 0.00 in of offset everywhere in the zone); its
    width is the recorded p25/p75 of +/-0.82 in.
    """
    def phi(x):
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    def jitter_cdf(x):
        """The truncated jitter, so this integrates the model as it is drawn."""
        a = bf.JITTER_LIMIT_SIGMA
        lo, hi = phi(-a), phi(a)
        return min(1.0, max(0.0, (phi(x / bf.LAUNCH_JITTER_DEG) - lo) / (hi - lo)))

    sd, r = 1.22, bf.CONTACT_NORMAL_RADIUS_IN
    edges = [e for e, _ in bf.SHAPE_LAUNCH_BANDS]
    names = [s for _, s in bf.SHAPE_LAUNCH_BANDS] + [bf.STEEPEST_SHAPE]
    acc = dict.fromkeys(names, 0.0)
    total = 0.0
    for i in range(1001):
        d = -r + 2.0 * r * i / 1000.0
        w = math.exp(-0.5 * (d / sd) ** 2)
        total += w
        mu = bf.launch_angle_deg(d, jitter=False)
        prev = 0.0
        for j, e in enumerate(edges):
            p = jitter_cdf(e - mu)
            acc[names[j]] += w * (p - prev)
            prev = p
        acc[names[-1]] += w * (1.0 - prev)

    mix = {k: 100.0 * v / total for k, v in acc.items()}
    assert 36.0 < mix["GROUNDER"] < 46.0, mix
    assert 21.0 < mix["LINER"] < 29.0, mix
    assert 23.0 < mix["FLY"] < 31.0, mix
    assert 4.0 < mix["POP_UP"] < 11.0, mix


# ---- The animation's own copy of the question ------------------------------

@pytest.mark.parametrize("outcome", ["IN_PLAY", "FOUL"])
def test_the_animation_fallback_agrees_with_the_classifier(outcome):
    """The engine resolves a foul's shape upstream now (`_foul_shape`), so the
    game no longer reaches this fallback — but it is still the FOUL path's
    model, still reached by legacy callers, and it has to keep agreeing with
    the classifier or the two can drift apart unseen. It bucketed raw pixels
    before, with two thresholds above the reachable range."""
    for inches in (-2.0, -1.2, -0.8):
        got = {hit_animation._pick_shape(outcome, inches / IN_PER_PX)
               for _ in range(2000)}
        assert not (got & set(AIRBORNE)), (outcome, inches, got)
    for inches in (0.8, 1.2, 2.0):
        got = {hit_animation._pick_shape(outcome, inches / IN_PER_PX)
               for _ in range(2000)}
        assert "GROUNDER" not in got, (outcome, inches, got)


def test_a_foul_can_finally_pop_up():
    """POP_UP needed an offset over 25 px on the old fallback and bat and ball
    stop touching at 17.2, so no foul has ever animated as a pop-up — which is
    the single most ordinary thing a foul ball does."""
    got = {hit_animation._pick_shape("FOUL", 2.4 / IN_PER_PX)
           for _ in range(2000)}
    assert "POP_UP" in got


def test_a_flyout_stays_airborne():
    """The bands may only choose *which* airborne shape a flyout was. A
    ball caught on the fly cannot be animated as a ball that never left the
    dirt, whatever the offset says."""
    for inches in (-2.5, -1.0, 0.0, 1.0, 2.5):
        got = {hit_animation._pick_shape("FLYOUT", inches / IN_PER_PX)
               for _ in range(500)}
        assert got <= set(AIRBORNE), (inches, got)


def test_a_supplied_type_still_wins():
    """The canonical source is `hit_outcome_manager`. The offset-derived path
    is only for callers with nothing to be told."""
    for t in ("GROUNDER", "LINER", "FLY", "POP_UP"):
        assert hit_animation._pick_shape("IN_PLAY", 0.0, t) == t
    assert hit_animation._pick_shape("HOME RUN", -2.0 / IN_PER_PX,
                                     "GROUNDER") == "FLY"


# ---- The tables must not come back -----------------------------------------

def test_the_prior_tables_are_gone():
    """Same shape as `test_the_dilation_correction_constants_are_gone`: these
    were a second model of a thing the geometry already answered, and two of
    them were tuned against a `ft_per_px_z` that has since changed. A
    reintroduction would be silent."""
    import strikefactor.gameplay.hit_outcome_manager as hom
    for name in ("_TYPE_OFFSET_ANCHORS", "_TYPE_OFFSET_SIGMA",
                 "_TYPE_QUALITY_BIAS", "_TYPE_BASE_PRIOR",
                 "_BATTED_BALL_TYPES"):
        assert not hasattr(hom, name), name
