"""Who fields the ball, and who covers first base.

Two decisions, one bug. A grounder hit dead at the 2B was fielded by the
1B, because the primary was picked on *when* the intercept happened and
the ball reaches the 1B's stretch of the path first — so the fielder
standing on the ball was free to be assigned somewhere else. Somewhere
else was first base, since the pitcher's follow-through delay was charged
against their ETA to the bag and pushed them out of the running. The
result on screen: the ball is hit right at the second baseman, who turns
and runs to first while it rolls through.

These guard both halves — the ball belongs to whoever has least ground to
cover, and the bag goes down a strict priority list (1B, then the pitcher
on the 3-1, and the 2B only when nobody ahead of them can get there).
"""

import collections
import math
import random

import pytest

from strikefactor.gameplay import hit_animation as ha
from strikefactor.gameplay.hit_animation import (
    COVER_ROLE_PRIORITY,
    FIELDER_HOMES,
    FIRST_BASE_BAG_POS,
    ROLE_REACTION_BIAS_S,
    HitAnimation,
)

INFIELD = ("P", "1B", "2B", "SS", "3B")


class _StubBatter:
    def get_handedness(self):
        return "R"


class _StubGame:
    def __init__(self):
        self.batter = _StubBatter()


def _aim(monkeypatch, point):
    monkeypatch.setattr(ha, "_pick_hit_landing", lambda *a, **k: point)


def _make(shape="GROUNDER", quality=0.6):
    return HitAnimation(
        _StubGame(),
        outcome="IN_PLAY",
        on_complete=lambda: None,
        quality=quality,
        batted_ball_type=shape,
    )


def _play(shape="GROUNDER", quality=0.6):
    """Run one animation to completion, recording every cover assignment.

    `clashes` is the instantaneous form of the invariant below: frames where
    the same fielder was both on the ball and on the bag. It has to be sampled
    per frame rather than reconstructed afterwards, because *both* roles can
    legitimately change mid-play — see
    `test_the_fielder_it_was_hit_to_is_never_sent_to_cover`.
    """
    anim = _make(shape, quality)
    setup_primary, covers, clashes = anim._primary_role, set(), []
    t = 0
    while not anim.finished and t < 40000:
        t += 16
        anim.update(t)
        if anim._cover_role is not None:
            covers.add(anim._cover_role)
            if anim._cover_role == anim._primary_role:
                clashes.append((t, anim._primary_role))
    return anim, setup_primary, covers, clashes


# ---- Whose ball is it -----------------------------------------------------

def test_ball_hit_at_a_fielder_is_fielded_by_that_fielder(monkeypatch):
    """The report this file exists for. Aim a grounder at each infielder's
    feet; they are the one who fields it."""
    for role in ("1B", "2B", "SS", "3B"):
        _aim(monkeypatch, FIELDER_HOMES[role])
        picks = collections.Counter(_make()._primary_role for _ in range(40))
        assert picks[role] == 40, f"ball hit at the {role} went to {picks}"


def test_the_fielder_it_was_hit_to_is_never_sent_to_cover(monkeypatch):
    """Standing on the ball must not be a reason to be free for the bag.

    Asserted **per frame**, against whoever is on the ball at that instant.

    It used to compare the primary as it was at *setup* against every cover
    assignment made over the whole play, and that is a different claim: both
    roles are allowed to change, so the union over time catches a sequence
    that is ordinary baseball. A ball that goes THROUGH the first baseman
    (`defense.py`'s misplay model, newer than this test) hands the primary to
    the second baseman, and the first baseman — no longer fielding anything —
    correctly goes back to cover their own bag. That is right, and the old
    form called it a bug on about 2.5% of ambient RNG states, which is a flake
    that only ever surfaced when something reordered the suite.

    The per-frame form is also the stronger one: it checks the invariant on
    every frame of every play rather than once against a stale value.
    """
    for role in ("1B", "2B", "SS", "3B"):
        _aim(monkeypatch, FIELDER_HOMES[role])
        for _ in range(20):
            _, _, _, clashes = _play()
            assert not clashes, (
                f"{clashes[0][1]} was fielding the ball and covering first "
                f"at t={clashes[0][0]}ms")


def test_closest_fielder_wins_over_an_earlier_intercept(monkeypatch):
    """The mechanism, stated directly: the 1B's perpendicular foot on a
    ball hit at the 2B comes earlier in the flight — so they'd win a
    timing race — but they are 30 ft away from it and the 2B is on it."""
    _aim(monkeypatch, FIELDER_HOMES["2B"])
    anim = _make()
    first, second = anim.fielders["1B"], anim.fielders["2B"]
    early = anim._path_intercept(first)
    on_it = anim._path_intercept(second)
    assert early["ball_arrives_ms"] < on_it["ball_arrives_ms"]
    assert on_it["fielder_dist_ft"] < early["fielder_dist_ft"]
    assert anim._primary_role == "2B"


def test_fielders_beyond_the_landing_spot_can_still_make_the_play(monkeypatch):
    """A ball that dies in front of a fielder is a fielder charging, not a
    ball nobody can reach. Excluding the far end of the path put the 1B on
    balls dying at the 2B's feet and stopped outfielders charging bloops.

    The CF's speed is pinned to the nominal sprint because this is a test
    of the *eligibility* gate, not of the dice: fielders are born with
    ±22% speed jitter, and now that flight time is physical rather than a
    flat 3.3 s, a slow draw genuinely cannot charge 80 ft in a 240 ft fly
    ball's hang time. That is correct behaviour and it is not what this
    test is about — left unpinned it passes or fails on the RNG.
    """
    _aim(monkeypatch, ha._to_screen(0.0, 240.0))     # shallow centre field
    anim = _make(shape="FLY", quality=0.4)
    centerfielder = anim.fielders["CF"]              # home is 320 ft — behind it
    centerfielder.max_speed = ha.FIELDER_SPRINT_FT_S
    assert anim._path_intercept(centerfielder)["can_make"]


def test_fielders_behind_the_plate_still_cannot(monkeypatch):
    """The half of the segment guard that was load-bearing: the catcher's
    clamped intercept sits right next to them on every deep ball."""
    _aim(monkeypatch, ha._to_screen(0.0, 240.0))
    anim = _make(shape="FLY", quality=0.4)
    assert not anim._path_intercept(anim.fielders["C"])["can_make"]


# ---- Who covers first -----------------------------------------------------

def test_first_base_priority_puts_the_second_baseman_last():
    """Order is the claim: the bag is the 1B's, the pitcher takes the 3-1,
    and the 2B covering first is a busted play."""
    assert COVER_ROLE_PRIORITY == ["1B", "P", "2B"]


# Both of the next two compare a set unioned over the whole play against a
# single expected cover, so both are scoped to plays the defense handled
# cleanly. A misplay is a *different play*: a ball through the 1B hands the
# primary to the 2B and sends the 1B back to their own bag, so `covers` reads
# {'P', '1B'} and `primary` is no longer "1B" — all correct, and all outside
# what these two claim. Unscoped, the first of them failed on ~4% of ambient
# RNG states; the second has the same shape and had simply not been caught.
# The instantaneous invariant that holds on *every* play, misplays included,
# is the one in `test_the_fielder_it_was_hit_to_is_never_sent_to_cover`.

def test_pitcher_covers_when_the_first_baseman_fields_it(monkeypatch):
    """The 3-1: the bag is the 1B's, so when they field it the pitcher takes it."""
    _aim(monkeypatch, FIELDER_HOMES["1B"])
    clean = 0
    for _ in range(25):
        anim, primary, covers, _ = _play()
        if anim._misplay_kind is not None:
            continue
        clean += 1
        assert primary == "1B"
        assert covers == {"P"}, f"3-1 play covered by {covers}"
    assert clean > 15, f"only {clean}/25 clean plays — too few to judge"


def test_first_baseman_covers_when_anyone_else_fields_it(monkeypatch):
    for role in ("2B", "SS", "3B"):
        _aim(monkeypatch, FIELDER_HOMES[role])
        clean = 0
        for _ in range(20):
            anim, _, covers, _ = _play()
            if anim._misplay_kind is not None:
                continue
            clean += 1
            assert covers == {"1B"}, f"ball to the {role}, bag covered by {covers}"
        assert clean > 12, f"only {clean}/20 clean plays to the {role}"


def test_second_baseman_almost_never_covers_first():
    """Across a full spray of grounders — no aiming, real landing spots."""
    seen = collections.Counter()
    n = 150
    for i in range(n):
        _, _, covers, _ = _play(quality=(i % 10) / 10.0)
        seen.update(covers)
    assert seen["2B"] / n < 0.05, (
        f"2B covered first on {seen['2B']}/{n} grounders: {dict(seen)}")


def test_pitcher_breaks_for_the_bag_without_the_follow_through_delay():
    """`break_delay_ms` is the whole reason the pitcher can win the 3-1:
    the follow-through bias is recovery time before they can field a
    comebacker, not before they can run."""
    anim = _make()
    pitcher = anim.fielders["P"]
    # The bias is stated in real seconds and both clocks are projected
    # onto the animated one, so the gap between them is the bias scaled.
    bias_ms = anim._anim_ms(ROLE_REACTION_BIAS_S["P"])
    assert pitcher.reaction_delay_ms - pitcher.break_delay_ms == pytest.approx(bias_ms)
    fielding_eta = anim._eta_to_point(pitcher, FIRST_BASE_BAG_POS)
    break_eta = anim._eta_to_point(pitcher, FIRST_BASE_BAG_POS,
                                   reaction_ms=pitcher.break_delay_ms)
    assert fielding_eta - break_eta == pytest.approx(bias_ms)


def test_cover_deadline_runs_from_the_catch_not_from_contact(monkeypatch):
    """The cover man has the ball's whole flight to get to the bag. Timed
    from contact instead, the 60 ft from the mound vetoed the pitcher on
    every 3-1 and the bag fell through to the 2B."""
    _aim(monkeypatch, FIELDER_HOMES["1B"])
    anim = _make()
    pitcher = anim.fielders["P"]
    eta = anim._eta_to_point(pitcher, FIRST_BASE_BAG_POS,
                             reaction_ms=pitcher.break_delay_ms)
    budget_ms = anim._anim_ms(ha.COVER_IN_TIME_BUDGET_S)
    assert eta > budget_ms                           # loses the naive test
    assert anim._fielded_at_ms > 0
    assert eta <= anim._fielded_at_ms + budget_ms


def test_the_cover_man_does_not_field_the_ball(monkeypatch):
    """Their route to the bag crosses the flight path of anything hit at
    the 1B; a fielder running to receive a throw is not making a play."""
    _aim(monkeypatch, FIELDER_HOMES["1B"])
    anim = _make()
    anim._pitcher_fields_clean = True    # else they're out of the pool anyway
    anim._cover_role = "P"
    pitcher = anim.fielders["P"]
    anim._elapsed = anim.duration_ms
    anim._ball = anim._ball_shadow = (pitcher.pos[0], pitcher.pos[1])
    assert anim._check_in_flight_intercept() is False
    anim._cover_role = None
    assert anim._check_in_flight_intercept() is True


# ---- The throw gets made --------------------------------------------------

def _run(anim, limit_ms=40000):
    """Run to completion, recording whether a throw or a carry was drawn."""
    t, thrown, carried = 0, False, False
    while not anim.finished and t < limit_ms:
        t += 16
        anim.update(t)
        if anim._secured and anim._go_throw_start_ms is not None:
            if anim._go_throw_start_ms < t <= anim._go_throw_arrive_ms:
                thrown = True
        elif anim._secured and anim._go_done_ms is not None:
            carried = True
    return thrown, carried


def _is_infield_play(anim):
    return (anim._secured
            and anim.shape == "GROUNDER"
            and anim._primary_role not in ha.OUTFIELD_ROLES
            and anim._fielded_ft() <= ha.INFIELD_PLAY_MAX_FT)


# Three tests below assert different properties of one deterministic sweep.
# `random.seed(i)` per play makes each one a function of its index alone, so
# the sample is reproducible and a longer run is a superset of a shorter one.
# Simulated once and handed out, for the reason `test_defense.py::_plays`
# gives: separate assertions each naming their own cause, one run.
_SWEEP_CACHE = {}


def _sweep(n=200, q0=0.20, step=0.004):
    """`n` plays off one quality ramp as `(anim, thrown, carried)`, memoized."""
    key = (n, q0, step)
    if key not in _SWEEP_CACHE:
        plays = []
        for i in range(n):
            random.seed(i)
            anim = _make(quality=q0 + step * i)
            thrown, carried = _run(anim)
            plays.append((anim, thrown, carried))
        _SWEEP_CACHE[key] = plays
    return _SWEEP_CACHE[key]


def test_an_infielder_who_fields_a_grounder_always_makes_a_play_on_it():
    """The reported bug: GROUNDOUT appearing the instant the fielder reached
    the ball, with no throw and nobody covering first.

    The throw sub-animation used to be scheduled *only* inside
    `_trigger_in_flight_intercept`, so it existed only for a ball cut off in
    the air. A grounder secured after it had already landed — the fielder
    charging a slow roller and picking it up, which is the most ordinary
    infield play there is — ran its race in `_resolve_extra_bases` and went
    straight to the banner. Both paths schedule through
    `_begin_infield_play` now.

    Swept rather than aimed, because the population this missed is exactly
    the one a single hand-placed ball is least likely to land in: a slow
    roller dies short of every set position, so it is *never* intercepted in
    flight. `quality` is swept low, where those live.
    """
    missed = []
    for i in range(60):
        random.seed(i)
        anim = _make(quality=0.20 + 0.01 * i)
        thrown, carried = _run(anim)
        if _is_infield_play(anim) and not (thrown or carried):
            missed.append((i, anim._primary_role, anim.classified_outcome))
    assert not missed, (
        f"{len(missed)} fielded infield grounders showed no throw and no "
        f"carry: {missed[:5]}")


def test_the_throw_is_drawn_on_a_ball_picked_up_off_the_ground():
    """The specific path that had none — asserted directly, so a regression
    cannot hide behind the in-flight intercepts in the sweep above."""
    found = None
    for anim, thrown, carried in _sweep():
        if _is_infield_play(anim) and not anim._secured_in_flight:
            found = (anim, thrown, carried)
            break
    assert found is not None, "no ball was picked up off the ground to test"
    anim, thrown, carried = found
    assert thrown or carried, (
        f"{anim._primary_role} picked the ball up and did nothing with it "
        f"({anim.classified_outcome})")
    assert anim._post_fielding, "the post-fielding sub-animation never started"


def test_the_runner_beating_the_throw_still_shows_the_throw():
    """A SINGLE off an infield grounder is a race the runner won, not a ball
    nobody played. `_resolve_ground_ball` says so in as many words — "the
    throw still plays, the runner just gets there first" — and it is the
    whole reason the play is worth watching."""
    seen = 0
    for anim, thrown, carried in _sweep():
        if _is_infield_play(anim) and anim.classified_outcome == "SINGLE":
            seen += 1
            assert thrown or carried, "an infield single with no play made"
    assert seen, "no infield singles in the sweep — widen it"


def test_first_base_is_still_covered_when_the_ball_was_picked_up():
    """Standing the defense down before resolving the play sent the cover man
    home, so the throw arced to an empty bag. Order of operations."""
    for anim, _thrown, _carried in _sweep():
        if (_is_infield_play(anim) and not anim._secured_in_flight
                and anim._go_throw_start_ms is not None):
            assert anim._cover_role is not None, "throw to an empty bag"
            cover = anim.fielders[anim._cover_role]
            assert math.dist(cover.pos, ha.FIRST_BASE_BAG_POS) < 40.0, (
                f"{anim._cover_role} was {math.dist(cover.pos, ha.FIRST_BASE_BAG_POS):.0f} "
                "px from the bag when the throw arrived")
            return
    pytest.skip("no assisted play off a ground pickup in the sweep")
