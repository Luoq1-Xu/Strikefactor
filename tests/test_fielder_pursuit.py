"""How a fielder the ball has beaten actually moves.

Reported from play: a ball up the middle past the pitcher, and the middle
infielders "froze for a split second and stopped moving, then started to
sprint along with the outfielders, all converging on the ball."

Both halves came from one pair of lines. A range-capped fielder was sent
at a *fixed* clamp point, and `_step_fielder` zeroed `current_speed` the
frame they reached any target — so the 2B sprinted to the edge of their
zone, stopped dead, and stood at exactly zero for over a second while the
ball rolled past. The sprint was that same fielder ramping from a
standing start the instant the post-landing chase engaged.

These guard the motion, not the assignment: who fields the ball and what
it is scored are settled elsewhere and must not move.
"""

import math

import pytest

from strikefactor.gameplay import hit_animation as ha
from strikefactor.gameplay.hit_animation import (
    FIELDER_SPRINT_FT_S,
    FIRST_BASE_GROUNDER_RANGE_FT,
    PULL_UP_DRIFT_SPEED_FRAC,
    HitAnimation,
)

INFIELD = ("1B", "2B", "SS", "3B")
UP_THE_MIDDLE = (0.0, 190.0)     # real feet: past the pitcher into shallow CF


class _StubBatter:
    def get_handedness(self):
        return "R"


class _StubGame:
    def __init__(self):
        self.batter = _StubBatter()


@pytest.fixture
def up_the_middle(monkeypatch):
    """Aim every batted ball straight up the middle, past the pitcher."""
    monkeypatch.setattr(ha, "_pick_hit_landing",
                        lambda *a, **k: ha._to_screen(*UP_THE_MIDDLE))


def _make(shape="GROUNDER", quality=0.75):
    return HitAnimation(_StubGame(), outcome="IN_PLAY", on_complete=lambda: None,
                        quality=quality, batted_ball_type=shape)


def _trace(anim):
    """Step one play, sampling per-fielder motion while the ball is live.

    Sampling stops at the catch: once the ball is secured every defender is
    deliberately sent home and stops there, and that legitimate freeze is
    long enough to swamp anything happening during the play.
    """
    frames = []
    t = 0
    while not anim.finished and t < 12000:
        t += 16
        anim.update(t)
        if anim._secured:
            break
        frames.append({
            "t": t,
            "in_flight": t <= anim.duration_ms,
            "cover": anim._cover_role,
            "f": {r: (anim.fielders[r].current_speed_frac,
                      tuple(anim.fielders[r].pos),
                      anim.fielders[r].target)
                  for r in anim.fielders},
        })
    return frames


def _longest_freeze_ms(frames, role):
    """Longest unbroken stretch at exactly zero speed, after first movement,
    ignoring plays where this role went to cover the bag.

    A fielder standing still *on the spot they are running to* is not
    frozen, they are set — so arrival exempts them. This exemption used to
    be unnecessary, for a bad reason: the chase clamp sent middle
    infielders at a point 130 px out that they could never reach in the
    dilated flight time, so they never arrived and never stood. With the
    clamp gone they get there and set their feet, which is what fielding a
    ground ball looks like. The sibling test
    `test_a_chasing_fielder_never_stops_short_of_the_ball` has always drawn
    the line here; this one now draws it in the same place.
    """
    longest = run = 0
    moving_yet = False
    for fr in frames:
        if fr["cover"] == role:
            return 0
        speed, pos, _ = fr["f"][role]
        moving_yet = moving_yet or speed > 0
        if not moving_yet:
            continue
        set_at_spot = math.dist(pos, fr["f"][role][2]) <= 25.0
        run = run + 16 if (speed == 0.0 and not set_at_spot) else 0
        longest = max(longest, run)
    return longest


# ---- The freeze -----------------------------------------------------------

def test_no_infielder_stands_dead_still_while_the_ball_is_live(up_the_middle):
    """The report. Pre-fix the 2B held exactly zero speed for up to 1520 ms
    on this exact ball, on ~36% of them.

    Scoped to the flight, which is the window the bug lived in: the 2B
    sprinted to the edge of a range cap and stopped dead *while the ball was
    still coming*. Once a grounder is through the infield a third baseman
    standing still is a third baseman with nothing to do, and holding the
    whole play to this budget only asserted that the flight was long enough
    to hide the difference — which stopped being true when flight time
    became physical (a grounder is ~1.9 s in the air and the chase after it
    can run twice that)."""
    worst = {r: 0 for r in INFIELD}
    for _ in range(40):
        frames = [fr for fr in _trace(_make()) if fr["in_flight"]]
        for role in INFIELD:
            worst[role] = max(worst[role], _longest_freeze_ms(frames, role))
    # The budget is the reaction window on the animated clock. Stated as a
    # bare 300 ms it silently assumed a presentation scale of 1.0; the
    # legitimate read-the-ball freeze is REACTION_DELAY_MAX_S * scale.
    budget_ms = ha.REACTION_DELAY_MAX_S * 1000.0 * ha.PRESENTATION_TIME_SCALE
    for role, ms in worst.items():
        assert ms <= budget_ms, f"{role} stood still for {ms} ms mid-play"


def test_arriving_at_a_target_does_not_zero_the_speed():
    """The mechanism, stated directly. Snapping speed to 0 on arrival is a
    one-frame stop from a full sprint, and it is what left the fielder at
    rest for the next target switch to ramp out of."""
    anim = _make()
    fielder = anim.fielders["SS"]
    # Pin the speed: if the SS drew the primary role, setup has already paced
    # `max_speed` down to an intercept-timing value and a "1 px away" target
    # is then several frames of travel, not one.
    fielder.max_speed = fielder.base_max_speed
    fielder.current_speed_frac = 1.0                   # at a full sprint
    fielder.decel_radius_px = 0.1                      # isolate: no decel ramp
    # On the field, not at an arbitrary screen coordinate: `_step_fielder`
    # contains its target inside the outfield wall, and (100, 100) is well
    # outside it — the clamp would rewrite the target and the fielder would
    # run somewhere else entirely.
    fielder.pos = list(ha.FIELDER_HOMES["SS"])
    fielder.target = (fielder.pos[0] + 1.0, fielder.pos[1])
    # 100 ms of travel at a sprint covers >3 px, so 1 px away arrives this
    # frame — the `dist <= step` branch, which is the one that zeroed speed.
    expected = fielder.target
    anim._step_fielder(fielder, 100, 99999)            # past any reaction delay
    assert tuple(fielder.pos) == expected, "should still snap position"
    assert fielder.current_speed_frac > 0.0, "speed was zeroed on arrival"
    assert fielder.current_speed_frac < 1.0, "speed should decay"


def test_a_pulled_up_fielder_keeps_moving_with_the_play(up_the_middle):
    """Having been beaten, they drift after the ball rather than planting on
    the clamp point — so there is no standing start to burst out of."""
    seen_drift = False
    for _ in range(40):
        anim = _make()
        frames = _trace(anim)
        flight = [fr for fr in frames if fr["in_flight"]]
        if len(flight) < 40:
            continue
        for role in ("2B", "SS"):
            tail = flight[-25:]                        # last ~0.4 s of flight
            if any(fr["cover"] == role for fr in tail):
                continue
            moved = math.dist(tail[0]["f"][role][1], tail[-1]["f"][role][1])
            if moved > 1.0:
                seen_drift = True
    assert seen_drift, "no middle infielder was still moving late in the flight"


# ---- Legs and glove are two different bounds -----------------------------
# How far a fielder RUNS and how far they can REACH used to be the same
# number, which is why the 2B pulled up 40 px short of a ball they were
# closing on: the only way to stop them catching it was to stop them
# moving. They are now separate, and each has to hold on its own.

def test_the_first_baseman_still_answers_for_the_bag(up_the_middle):
    """The one range cap that survived the clock unification, and the only
    one that was never about the clock: every foot the 1B ranges on a
    grounder is a foot they have to sprint back before the throw lands."""
    for _ in range(30):
        anim = _make()
        for fr in _trace(anim):
            if not fr["in_flight"]:
                break                                   # cap is in-flight only
            if fr["cover"] == "1B":
                continue                                # cover man runs to the bag
            pos = fr["f"]["1B"][1]
            ranged_ft = ha._ft_dist(pos[0] - anim.fielders["1B"].home_pos[0],
                                    pos[1] - anim.fielders["1B"].home_pos[1])
            assert ranged_ft <= FIRST_BASE_GROUNDER_RANGE_FT + 1.0, (
                f"1B ranged {ranged_ft:.0f} ft off the bag")


def test_infield_range_is_bounded_by_the_sprint_not_by_a_constant(up_the_middle):
    """`INFIELD_LOW_BALL_RANGE_PX = 55` and `INFIELD_CHASE_RANGE_PX = 130`
    used to bound this by hand, because a real sprint spent against the old
    dilated flight time covered two to three times the honest ground. They
    are gone. What has to hold now is that the physics reproduces them: a
    fielder cannot cover more ground than their own speed allows in the
    time the ball is actually in play.

    This is the load-bearing check on the clock unification. If flight time
    and fielder speed ever drift onto different clocks again, this is what
    catches it — no cap will be quietly absorbing the difference.
    """
    for _ in range(30):
        anim = _make()
        for fr in _trace(anim):
            if not fr["in_flight"]:
                break
            elapsed_real_s = fr["t"] / (1000.0 * anim.time_scale)
            for role in ("2B", "SS"):
                if fr["cover"] == role:
                    continue
                f = anim.fielders[role]
                ranged_ft = ha._ft_dist(fr["f"][role][1][0] - f.home_pos[0],
                                        fr["f"][role][1][1] - f.home_pos[1])
                # Generous ceiling: full sprint for the whole elapsed time,
                # charging nothing for reaction or the acceleration ramp.
                # A fielder beating this is not running, they are teleporting.
                ceiling_ft = FIELDER_SPRINT_FT_S * 1.25 * elapsed_real_s + 2.0
                assert ranged_ft <= ceiling_ft, (
                    f"{role} covered {ranged_ft:.0f} ft in {elapsed_real_s:.2f}s "
                    f"— faster than a sprint")


def test_middle_infielders_still_outrun_their_own_glove(up_the_middle):
    """They chase a ball they cannot catch — being beaten by it is the whole
    point of the chase — so the run has to exceed the reach."""
    ran_past_reach = False
    for _ in range(30):
        anim = _make()
        for fr in _trace(anim):
            if not fr["in_flight"]:
                break
            for role in ("2B", "SS"):
                if fr["cover"] == role:
                    continue
                f = anim.fielders[role]
                d_ft = ha._ft_dist(fr["f"][role][1][0] - f.home_pos[0],
                                   fr["f"][role][1][1] - f.home_pos[1])
                if d_ft > 12.0:
                    ran_past_reach = True
    assert ran_past_reach, (
        "no middle infielder left their position — the chase is not engaging")


def test_a_fielder_never_catches_a_ball_beyond_their_reach(up_the_middle):
    """The load-bearing half. Once legs and glove came apart, only this stops
    a fielder converting every ball they run down."""
    for _ in range(60):
        anim = _make()
        for fr in _trace(anim):
            if anim._secured_in_flight:
                catcher = anim.fielders[anim._primary_role]
                reach_ft = anim._max_intercept_dist(catcher)
                got_ft = anim._range_ft(catcher, anim._ball_shadow)
                assert got_ft <= reach_ft + 1.0, (
                    f"{anim._primary_role} caught a ball {got_ft:.0f} ft out, "
                    f"reach {reach_ft:.0f} ft")
                break


def test_middle_infielders_chase_a_ball_up_the_middle_at_a_sprint(up_the_middle):
    """The report, restated as the fix: they run at it, hard, for most of the
    flight. Pre-chase they leaned 5-23 px off their home and held there while
    the ball went by 40 px away, which reads as giving up on it."""
    covered = {"2B": [], "SS": []}
    for _ in range(30):
        anim = _make()
        frames = [fr for fr in _trace(anim) if fr["in_flight"]]
        for role in ("2B", "SS"):
            if any(fr["cover"] == role for fr in frames):
                continue
            covered[role].append(max(
                ha._ft_dist(fr["f"][role][1][0] - anim.fielders[role].home_pos[0],
                            fr["f"][role][1][1] - anim.fielders[role].home_pos[1])
                for fr in frames))
    for role, runs in covered.items():
        assert runs, f"no clean sample for {role}"
        median = sorted(runs)[len(runs) // 2]
        assert median > 12.0, (
            f"{role} covered only {median:.0f} ft chasing a ball up the middle")


def test_a_chasing_fielder_never_stops_short_of_the_ball(up_the_middle):
    """The precise complaint: stopping while the ball is still on its way to
    them *and* they are still well off its path.

    Reaching the spot early and setting their feet is not that — a fielder
    standing on the ball's path waiting for it to arrive is what fielding
    looks like. Stopping 40 px away from it while it closes is the bug.
    """
    checked = 0
    budget_ms = ha.REACTION_DELAY_MAX_S * 1000.0 * ha.PRESENTATION_TIME_SCALE
    for _ in range(30):
        anim = _make()
        spot, arrive = {}, {}
        for r in ("2B", "SS"):
            hit = anim._path_intercept(anim.fielders[r])
            spot[r], arrive[r] = hit["point"], hit["ball_arrives_ms"]
        frames = [fr for fr in _trace(anim) if fr["in_flight"]]
        for role in ("2B", "SS"):
            if any(fr["cover"] == role for fr in frames):
                continue
            closing = [fr for fr in frames if fr["t"] <= arrive[role]]
            if len(closing) < 30:
                continue
            stalled = run = 0
            broken_yet = False
            for fr in closing:
                speed, pos, _ = fr["f"][role]
                # Before their first stride they are still reading the ball
                # (REACTION_DELAY_*), which is zero speed for a legitimate
                # 200-380 real ms and is not what this test is about.
                broken_yet = broken_yet or speed > 0.0
                if not broken_yet:
                    continue
                # Against the *live* target, not a point sampled before
                # the play started: `_route_in_flight_chase` re-aims the
                # chase every frame, so a t=0 snapshot drifts away from
                # where the fielder is actually trying to go and reads an
                # arrival as a stall.
                short_of_it = math.dist(pos, fr["f"][role][2]) > 25.0
                run = run + 16 if (speed == 0.0 and short_of_it) else 0
                stalled = max(stalled, run)
            # Same reasoning as the freeze budget above: a stall shorter
            # than one reaction window on the animated clock is a fielder
            # resetting their feet, not one giving up.
            assert stalled <= budget_ms, (
                f"{role} stopped {stalled} ms short of a ball still coming")
            checked += 1
    assert checked, "no chase samples were long enough to judge"


def test_the_drift_is_a_jog_not_a_second_sprint():
    """The ball is usually still short of the fielder when they pull up, so
    the drift starts by shading *back* toward its line. At full speed that
    correction reads as a sprint in the wrong direction."""
    assert 0.0 < PULL_UP_DRIFT_SPEED_FRAC < 1.0


def test_the_pull_up_is_cleared_when_the_ball_lands(up_the_middle):
    """It is an in-flight ranging state. Left latched, the drift speed cap
    would follow the fielder into the post-landing chase and they could
    never sprint after a ball that got through."""
    for _ in range(25):
        anim = _make()
        frames = _trace(anim)
        if frames and frames[-1]["in_flight"]:
            continue                                    # never reached the ground
        for role, f in anim.fielders.items():
            assert not f.pulled_up, f"{role} still pulled up after landing"
            assert f.max_speed >= f.base_max_speed * PULL_UP_DRIFT_SPEED_FRAC
