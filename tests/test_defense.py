"""The defense-strength profiles, and the identity that makes wiring them safe.

The load-bearing test here is `test_the_league_profile_is_the_existing_game`.
Every other level is a design choice that can be retuned; LEAGUE is a *claim*
-- that plugging this module in changes nothing at the default -- and it is
what lets the integration phase be verified by "no rate moved" rather than by
re-measuring every MLB-calibrated band in the suite.
"""

import contextlib
import random
import subprocess
import sys

import conftest
import pytest

from strikefactor.gameplay import defense as d
from strikefactor.gameplay import infield_timing as it
from strikefactor.settings_manager import SettingsManager

LADDER = [d.DefenseLevel.SANDLOT, d.DefenseLevel.MINORS,
          d.DefenseLevel.LEAGUE, d.DefenseLevel.GOLD_GLOVE]


# ---- The module's contract ------------------------------------------------

def test_the_module_is_pure():
    """No pygame, no game state -- same contract as infield_timing.

    Checked in a subprocess because conftest imports pygame for the whole
    session, so `"pygame" in sys.modules` is always True in-process and would
    make this pass for the wrong reason.
    """
    out = subprocess.run(
        [sys.executable, "-c",
         "import strikefactor.gameplay.defense, sys;"
         " print('pygame' in sys.modules)"],
        capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def test_how_hard_the_play_was_has_one_definition():
    """`stretch` must interpolate on the same 18 ft that release time does.

    A second copy of this constant is how two models of one thing start: the
    release penalty and the misplay probability would drift apart and the
    fielder would be "stretched" for one and not the other.
    """
    assert d.RANGING_FULL_FT == it.RELEASE_STRETCH_FT


def test_the_settings_ladder_matches_the_enum():
    """SettingsManager keeps its own string list so that settings does not
    import the gameplay layer (which already imports settings). This is what
    holds the two together instead."""
    assert tuple(SettingsManager.DEFENSE_LEVELS) == d.LEVEL_VALUES


# ---- profile_for is total -------------------------------------------------

@pytest.mark.parametrize("bad", [None, "nonsense", "", 7, object()])
def test_anything_unrecognised_falls_back_to_neutral(bad):
    assert d.profile_for(bad) is d.NEUTRAL


def test_a_level_resolves_from_either_the_enum_or_its_string():
    for level in LADDER:
        assert d.profile_for(level) is d.profile_for(level.value)


def test_a_profile_passes_through():
    assert d.profile_for(d.NEUTRAL) is d.NEUTRAL


# ---- The identity ---------------------------------------------------------

def test_the_league_profile_is_the_existing_game():
    """LEAGUE restates today's constants field for field.

    If this fails, wiring the profile through will silently move every
    fielding rate in the suite and the "no behaviour change" phase is a
    fiction. Compared against the real constants rather than against literals,
    so that a change to either side is caught here rather than in a Monte
    Carlo run weeks later.
    """
    from strikefactor.gameplay import hit_animation as ha
    p = d.profile_for(d.DefenseLevel.LEAGUE)
    assert p.sprint_fts == ha.FIELDER_SPRINT_FT_S
    assert p.reaction_min_s == ha.REACTION_DELAY_MIN_S
    assert p.reaction_max_s == ha.REACTION_DELAY_MAX_S
    assert p.throw_fts == it.THROW_EFFECTIVE_FTS
    assert p.release_scale == 1.0
    assert d.NEUTRAL is p


def test_the_arm_ladder_tops_out_at_the_sourced_maximum():
    """infield_timing already declared (100, 118) as the honest range for an
    effective throw and never used it. The ladder fills that hole rather than
    inventing an axis -- so its top rung is that number, not a rounder one.
    (SANDLOT sits below the floor on purpose: it is not an MLB defense.)"""
    assert (d.profile_for(d.DefenseLevel.GOLD_GLOVE).throw_fts
            == it.THROW_EFFECTIVE_FTS_RANGE[1])
    assert (it.THROW_EFFECTIVE_FTS_RANGE[0]
            <= d.NEUTRAL.throw_fts <= it.THROW_EFFECTIVE_FTS_RANGE[1])


# ---- Monotonicity ---------------------------------------------------------

RISING = ["sprint_fts", "throw_fts", "body_block"]
FALLING = ["reaction_min_s", "reaction_max_s", "release_scale",
           "field_misplay_p", "catch_muff_p", "muff_recovery_s"]


@pytest.mark.parametrize("field", RISING)
def test_better_defense_has_more_of_it(field):
    values = [getattr(d.profile_for(lv), field) for lv in LADDER]
    assert values == sorted(values), f"{field} not rising: {values}"
    assert values[0] < values[-1]


@pytest.mark.parametrize("field", FALLING)
def test_better_defense_has_less_of_it(field):
    values = [getattr(d.profile_for(lv), field) for lv in LADDER]
    assert values == sorted(values, reverse=True), f"{field} not falling: {values}"
    assert values[0] > values[-1]


def test_a_better_defense_reacts_faster_and_more_consistently():
    """Elite is not just quicker on average -- the draw is narrower. A wide
    band at the top of the ladder shows up as a Gold Glove infielder
    occasionally statue-ing on a routine ball, which is not what the setting
    is meant to buy."""
    spans = [d.profile_for(lv).reaction_max_s - d.profile_for(lv).reaction_min_s
             for lv in LADDER]
    assert spans == sorted(spans, reverse=True)


def test_every_reaction_band_is_a_real_interval():
    for lv in LADDER:
        p = d.profile_for(lv)
        assert 0.0 < p.reaction_min_s < p.reaction_max_s


# ---- Misplay probability --------------------------------------------------

def test_a_stretched_play_is_misplayed_more_often():
    p = d.NEUTRAL
    assert (d.misplay_prob(p, ranging_ft=d.RANGING_FULL_FT)
            > d.misplay_prob(p, ranging_ft=0.0))


def test_a_hotter_ball_is_misplayed_more_often():
    p = d.NEUTRAL
    assert d.misplay_prob(p, ev_mph=105.0) > d.misplay_prob(p, ev_mph=60.0)


def test_charging_a_slow_roller_is_harder_than_standing_still():
    p = d.NEUTRAL
    assert (d.misplay_prob(p, ev_mph=50.0, is_charging=True)
            > d.misplay_prob(p, ev_mph=50.0, is_charging=False))


def test_the_hop_does_not_apply_to_a_ball_caught_in_the_air():
    """Exit velocity makes a ground ball harder to field because of the hop.
    A fly ball has no hop -- it has hang time -- so the term must not sneak
    into the catch."""
    p = d.NEUTRAL
    assert (d.misplay_prob(p, ev_mph=110.0, in_air=True)
            == d.misplay_prob(p, ev_mph=60.0, in_air=True))


def test_misplay_probability_is_bounded():
    """Even the worst play on the worst defense is mostly made."""
    worst = d.profile_for(d.DefenseLevel.SANDLOT)
    p = d.misplay_prob(worst, ranging_ft=500.0, ev_mph=130.0, is_charging=True)
    assert p == d.MISPLAY_P_MAX
    for lv in LADDER:
        for ranging in (0.0, 9.0, 18.0, 60.0):
            for ev in (None, 40.0, 75.0, 110.0):
                q = d.misplay_prob(d.profile_for(lv), ranging, ev)
                assert 0.0 <= q <= d.MISPLAY_P_MAX


def test_a_better_defense_misplays_less_on_the_same_play():
    prev = None
    for lv in LADDER:
        q = d.misplay_prob(d.profile_for(lv), ranging_ft=9.0, ev_mph=95.0)
        if prev is not None:
            assert q < prev
        prev = q


# ---- Through-balls --------------------------------------------------------

def test_a_worse_defense_lets_more_balls_through():
    """`body_block` is the point of the field: getting the body in front is
    what stops a ball you cannot glove."""
    prev = None
    for lv in LADDER:
        s = d.through_share(d.profile_for(lv), ranging_ft=6.0, ev_mph=95.0)
        if prev is not None:
            assert s < prev
        prev = s


def test_a_ball_in_the_hole_goes_through_more_than_one_hit_at_you():
    p = d.NEUTRAL
    assert (d.through_share(p, ranging_ft=d.RANGING_FULL_FT, ev_mph=95.0)
            > d.through_share(p, ranging_ft=0.0, ev_mph=95.0))


def test_a_scorched_ball_goes_through_more_than_a_soft_one():
    p = d.NEUTRAL
    assert d.through_share(p, ev_mph=110.0) > d.through_share(p, ev_mph=55.0)


def test_the_through_share_is_bounded():
    for lv in LADDER:
        for ranging in (0.0, 18.0, 200.0):
            for ev in (None, 45.0, 130.0):
                s = d.through_share(d.profile_for(lv), ranging, ev)
                assert 0.0 <= s <= d.THROUGH_SHARE_MAX


def test_the_routine_through_rate_halves_up_the_ladder():
    """Through-balls as a share of balls an infielder *reached*, on a routine
    play: at the top a ball reached is a ball fielded, at the bottom a
    moderate share still gets through.

    The shape is pinned rather than the absolute numbers, which move whenever
    `field_misplay_p` is recalibrated against the error rate. What must not
    move is that each rung is roughly half the one below it — that is the
    ladder being worth having.
    """
    rates = [d.profile_for(lv).field_misplay_p * d.through_share(d.profile_for(lv))
             for lv in LADDER]
    assert rates == sorted(rates, reverse=True)
    for lower, higher in zip(rates, rates[1:]):
        assert 1.6 < lower / higher < 4.0, f"{rates}"
    # And the whole ladder sits where a *reached* ball is usually fielded.
    assert 0.02 < rates[0] < 0.08          # sandlot: a moderate share through
    assert rates[-1] < 0.005               # gold glove: almost never


# ---- roll_misplay ---------------------------------------------------------

def test_a_ball_never_goes_through_a_fielder_who_was_going_to_catch_it():
    """In the air a misplay is a drop, not a deflection that carries. The
    distinction is what keeps MUFF's dead-ball recovery separate from
    THROUGH's live ball rolling on."""
    rng = random.Random(7)
    worst = d.profile_for(d.DefenseLevel.SANDLOT)
    kinds = {d.roll_misplay(worst, rng, ranging_ft=15.0, ev_mph=100.0,
                            in_air=True) for _ in range(4000)}
    assert "THROUGH" not in kinds
    assert "BOBBLE" not in kinds
    assert kinds <= {None, "MUFF"}
    assert "MUFF" in kinds


def test_a_ground_ball_misplay_is_a_bobble_or_a_through_ball():
    rng = random.Random(11)
    worst = d.profile_for(d.DefenseLevel.SANDLOT)
    kinds = {d.roll_misplay(worst, rng, ranging_ft=10.0, ev_mph=95.0)
             for _ in range(4000)}
    assert kinds == {None, "BOBBLE", "THROUGH"}


def test_the_sampled_rate_matches_the_stated_probability():
    """roll_misplay must not quietly draw a different distribution from the
    one misplay_prob reports -- the reported number is what gets calibrated."""
    p = d.profile_for(d.DefenseLevel.MINORS)
    rng = random.Random(3)
    n = 20000
    hits = sum(d.roll_misplay(p, rng, ranging_ft=9.0, ev_mph=90.0) is not None
               for _ in range(n))
    assert hits / n == pytest.approx(
        d.misplay_prob(p, ranging_ft=9.0, ev_mph=90.0), abs=0.01)


def test_the_through_split_matches_the_stated_share():
    p = d.profile_for(d.DefenseLevel.SANDLOT)
    rng = random.Random(5)
    kinds = [d.roll_misplay(p, rng, ranging_ft=9.0, ev_mph=90.0)
             for _ in range(30000)]
    misplays = [k for k in kinds if k is not None]
    through = sum(k == "THROUGH" for k in misplays)
    assert through / len(misplays) == pytest.approx(
        d.through_share(p, ranging_ft=9.0, ev_mph=90.0), abs=0.02)


def test_a_gold_glove_infield_almost_always_makes_the_play():
    """The headline behaviour of the setting, stated as a rate."""
    rng = random.Random(13)
    best = d.profile_for(d.DefenseLevel.GOLD_GLOVE)
    n = 20000
    clean = sum(d.roll_misplay(best, rng, ranging_ft=6.0, ev_mph=90.0) is None
                for _ in range(n))
    assert clean / n > 0.95


# ---- Costs ----------------------------------------------------------------

def test_a_bobble_costs_the_same_wherever_it_happens():
    """Defense strength decides how *often* a ball is misplayed, not how
    badly. Keeping the cost fixed means retuning the frequency never changes
    what a bobble looks like on screen."""
    rng = random.Random(2)
    costs = [d.misplay_cost_s(rng) for _ in range(500)]
    assert all(d.MISPLAY_COST_S[0] <= c <= d.MISPLAY_COST_S[1] for c in costs)


def test_a_muffed_ball_dies_and_a_through_ball_does_not():
    """The glove takes nearly everything on a drop; a ball going through keeps
    most of its pace and carries into the outfield."""
    rng = random.Random(4)
    assert d.MUFF_RETENTION < 0.2
    assert all(0.5 < d.through_retention(rng) <= 1.0 for _ in range(200))
    assert d.THROUGH_RETENTION[1] == 1.0     # clean under the glove, no deflection


# ---- Integration: the profile reaching the fielders -----------------------

class _StubBatter:
    def get_handedness(self):
        return "R"


class _StubGame:
    def __init__(self):
        self.batter = _StubBatter()


def _anim(level=None, **kw):
    from strikefactor.gameplay.hit_animation import HitAnimation
    return HitAnimation(_StubGame(), outcome="IN_PLAY", on_complete=lambda: None,
                        quality=0.6, batted_ball_type="GROUNDER",
                        defense=level, **kw)


def test_an_animation_built_without_a_defense_gets_the_neutral_one():
    """The default has to be the identity, or every existing fielding test is
    silently measuring a different defense."""
    assert _anim().defense is d.NEUTRAL


def test_every_fielder_can_still_break_to_a_base():
    """The test that `test_reaction_delays_are_real_latencies...` only looks
    like it is: that one asserts `reaction_delay_s - break_delay_s == bias`,
    which `Fielder.__post_init__` guarantees by algebra whatever the numbers
    are. The real constraint is that break_delay_s stays positive — a
    negative one is a fielder breaking for the bag before contact, and it is
    what scaling the reaction band *through* ROLE_REACTION_BIAS_S would
    produce at the top of the ladder.
    """
    for lv in LADDER:
        for _ in range(50):
            anim = _anim(lv)
            for role, f in anim.fielders.items():
                assert f.break_delay_s > 0.0, f"{lv.value}/{role}: {f.break_delay_s}"


def test_a_better_defense_is_quicker_off_the_mark_and_faster():
    """Sampled rather than asserted on one draw: both quantities carry
    per-fielder jitter on purpose."""
    def means(level):
        speeds, reactions = [], []
        for _ in range(60):
            anim = _anim(level)
            for f in anim.fielders.values():
                speeds.append(f.base_max_speed)
                reactions.append(f.reaction_delay_s)
        return sum(speeds) / len(speeds), sum(reactions) / len(reactions)

    slow_speed, slow_react = means(d.DefenseLevel.SANDLOT)
    fast_speed, fast_react = means(d.DefenseLevel.GOLD_GLOVE)
    assert fast_speed > slow_speed
    assert fast_react < slow_react


def test_the_speed_jitter_keeps_its_shape_across_the_ladder():
    """The profile moves the centre of the distribution, not its width.
    Widening the jitter to express the setting is what COVER_ROLE_PRIORITY
    exists to prevent."""
    def spread(level):
        vals = []
        for _ in range(120):
            anim = _anim(level)
            vals += [f.base_max_speed / d.profile_for(level).sprint_fts
                     for f in anim.fielders.values()]
        return min(vals), max(vals)

    for level in (d.DefenseLevel.SANDLOT, d.DefenseLevel.GOLD_GLOVE):
        lo, hi = spread(level)
        assert 0.78 <= lo < 0.85
        assert 1.15 < hi <= 1.22


def test_defense_strength_does_not_move_the_batter_runner():
    """Defense strength is not batter speed. Conflating them would make a
    weak defense silently a fast batter, and would double-count against
    `_difficulty_time_offset_s`, which already moves that clock."""
    def mean_sprint(level):
        anim = _anim(level)
        return sum(anim._runner_sprint_fts() for _ in range(4000)) / 4000

    random.seed(1)
    slow = mean_sprint(d.DefenseLevel.SANDLOT)
    random.seed(1)
    fast = mean_sprint(d.DefenseLevel.GOLD_GLOVE)
    assert slow == pytest.approx(fast, abs=1e-9)
    assert slow == pytest.approx(it.SPRINT_SPEED_LEAGUE_FTS, abs=0.15)


def test_the_unassisted_carry_and_the_sprint_are_the_same_legs():
    """`_resolve_ground_ball` feeds the model a sprint speed when nobody
    throws, because the fielder carries it to the bag. That has to be *this*
    defense's legs, or a Gold Glove first baseman runs at 29 ft/s and carries
    the ball at 27."""
    import inspect

    from strikefactor.gameplay import hit_animation as ha
    src = inspect.getsource(ha.HitAnimation._resolve_ground_ball)
    assert "self.defense.sprint_fts" in src
    assert "FIELDER_SPRINT_FT_S" not in src


def test_the_settings_seam_is_total():
    """A hand-edited settings.json must not raise on the path that decides a
    batted ball, and a game with no settings manager at all (every fielding
    test) must get the neutral profile."""
    from strikefactor.gameplay.pitch_simulation import PitchSimulation

    class _Sim:
        game = _StubGame()                       # no settings_manager
        _defense_profile = PitchSimulation._defense_profile

    assert _Sim()._defense_profile() is d.NEUTRAL

    class _Settings:
        def get_defense_level(self):
            return "not-a-level"

    class _Sim2:
        game = _StubGame()
        _defense_profile = PitchSimulation._defense_profile

    _Sim2.game.settings_manager = _Settings()
    assert _Sim2()._defense_profile() is d.NEUTRAL


# ---- The ladder actually does something, and neutral does nothing ---------

def _ball_in_play(seed, quality, shape, spray_deg, profile):
    from strikefactor.gameplay.hit_animation import HitAnimation
    random.seed(seed)
    anim = HitAnimation(_StubGame(), outcome="IN_PLAY", on_complete=lambda: None,
                        quality=quality, batted_ball_type=shape,
                        spray_deg=spray_deg, defense=profile)
    t = 0
    while not anim.finished and t < 14000:
        t += 16
        anim.update(t)
    return anim


# ---- One sample, many assertions ------------------------------------------
#
# These sweeps are deterministic: `_ball_in_play` seeds the global RNG from
# the play index and every draw comes from a locally seeded `random.Random`,
# so the same arguments always produce the same plays. The tests below
# deliberately assert *different* properties of the same sample — four of them
# ask for `_misplayed(worst, 300, shape="GROUNDER")` verbatim and three for
# `_sweep(worst, 200, seed=808)` — because a merged test that failed would
# name six possible causes instead of one. Simulating once and handing the
# result out keeps both: separate assertions, one run.
#
# A longer sweep is a *superset* of a shorter one with the same
# (profile, seed, shape): play `i` depends only on `i` and on the draws made
# before it, so `_sweep(p, 400, seed)[:200] == _sweep(p, 200, seed)` exactly.
# The cache serves those prefixes rather than re-simulating them, which is
# what collapses the four 200/260/400-play sweeps at seed 808 into one.
#
# `shape` belongs in the key because passing one *skips* the batted-ball draw,
# which shifts the whole downstream stream — a forced-GROUNDER run and a free
# run are different samples, not the same one filtered.
_PLAY_CACHE = {}


def _plays(profile, n, seed, shape=None):
    """`n` balls in play against one defense, memoized and prefix-served."""
    key = (profile, seed, shape)
    have = _PLAY_CACHE.get(key)
    if have is not None and len(have) >= n:
        return have[:n]
    rng = random.Random(seed)
    plays = []
    for i in range(n):
        q = conftest.realistic_quality(rng)
        s = shape or conftest.realistic_batted_ball(rng)
        deg = conftest.realistic_spray(rng)
        plays.append(_ball_in_play(i, q, s, deg, profile))
    _PLAY_CACHE[key] = plays
    return plays


@contextlib.contextmanager
def _scratch(anim):
    """Borrow a cached animation for clock-poking, and put it back.

    The two mark tests drive `_error_mark_alpha` by hand, which means writing
    to the animation's own clock. Sweeps are shared between tests now, so a
    write left in place would hand the next test a doctored play — the one
    hazard memoizing these introduces, made explicit here rather than left to
    the accident that the fields happen not to be read again.
    """
    saved = (anim._elapsed, anim._error_marked_at_ms)
    try:
        yield anim
    finally:
        anim._elapsed, anim._error_marked_at_ms = saved


def _sweep(profile, n, seed=4242):
    """Balls in play against one defense, over the batter this game has."""
    return _plays(profile, n, seed)


def _babip(plays):
    hits = sum(p.classified_outcome in _HITS for p in plays)
    hr = sum(p.classified_outcome == "HOME RUN" for p in plays)
    n = sum(p.classified_outcome is not None for p in plays)
    return (hits - hr) / max(1, n - hr)


_HITS = {"SINGLE", "DOUBLE", "TRIPLE", "HOME RUN"}


def test_the_neutral_profile_changes_nothing_at_all():
    """The identity, checked as exact equality rather than as "no rate moved".

    This is what makes wiring the profile through a safe change: LEAGUE
    restates the module constants, so the arithmetic is the same, the RNG is
    consumed identically, and every play resolves to the same outcome and the
    same margin as passing no defense at all. Measured over 900 balls in play
    it was 0 differing plays; a smaller sample is enough here because the
    assertion is equality, not a band.

    If this ever fails, the neutral row has drifted off the constants and
    every MLB-calibrated band in the suite is silently measuring a different
    defense.
    """
    def fingerprint(profile):
        return [(p.classified_outcome,
                 None if p.play_timing is None
                 else round(p.play_timing.margin_s, 9))
                for p in _sweep(profile, 120)]

    assert fingerprint(None) == fingerprint("league")


def test_a_better_defense_converts_more_balls_in_play():
    """The ladder has to be worth having. Measured end to end over the full
    four levels at n=1200 this runs BABIP .435 / .383 / .332 / .290 -- a
    145-point spread, comfortably wider than the ~60 points between the best
    and worst real defensive teams, which is the point of a setting.

    Only the two ends are swept here; the middle rungs are monotone by
    construction (every field is) and sweeping four levels would put a minute
    on the suite for no extra information.
    """
    worst = _babip(_sweep(d.profile_for(d.DefenseLevel.SANDLOT), 220))
    best = _babip(_sweep(d.profile_for(d.DefenseLevel.GOLD_GLOVE), 220))
    assert worst - best > 0.06, f"sandlot {worst:.3f} vs gold glove {best:.3f}"


# ---- The misplay model in the animation ----------------------------------

def _misplayed(profile, n, seed=31, shape=None):
    """Balls in play where the fielder did not handle it cleanly."""
    return [a for a in _plays(profile, n, seed, shape)
            if a._misplay_kind is not None]


def test_a_misplay_is_rolled_once_and_latched():
    """A coin flipped every frame would let a fielder who muffed it snare the
    ball two frames later — the reasoning `_roll_pitcher_clean_field` gives
    for its own once-per-ball roll."""
    worst = d.profile_for(d.DefenseLevel.SANDLOT)
    for anim in _misplayed(worst, 120)[:10]:
        assert anim._misplay_rolled
        assert anim._misplay_kind in ("BOBBLE", "THROUGH", "MUFF")
        assert anim._misplay_role is not None


def test_a_ball_through_a_fielder_usually_reaches_the_outfield():
    """The whole point: reaching the ball stopped meaning fielding it.

    Not *never* an out — a ball that ticks off the glove and drops at the
    fielder's feet can be picked up and thrown in time, which is ordinary
    baseball. But it has to be the exception: measured over 400 sandlot
    grounders the ball travels a median 104 ft past the fielder and only 2 of
    35 through-balls were still converted.

    This is the assertion that caught the model's worst bug. Scaling the
    *nominal landing speed* instead of the ball's live speed left it dead
    16 ft on, so the fielder simply turned round and picked it up on 28 of 35
    through-balls and a third of them were outs — a "through-ball" that never
    went through anybody.
    """
    worst = d.profile_for(d.DefenseLevel.SANDLOT)
    through = [a for a in _misplayed(worst, 300, shape="GROUNDER")
               if a._misplay_kind == "THROUGH"]
    assert through, "no through-balls in 300 grounders against a sandlot defense"
    outs = sum(a.classified_outcome in ("GROUNDOUT", "FLYOUT", "LINEOUT", "POP UP")
               for a in through)
    assert outs / len(through) < 0.20, f"{outs}/{len(through)} through-balls were outs"


def test_a_beaten_fielder_mostly_does_not_get_the_ball_back():
    """The pool filter stops them re-intercepting on the very next frame,
    standing where the ball just was. Chasing down their own miss is allowed
    — that is what happens on a ball that ticks off the glove and dies — but
    it must be the minority, or the ball is not getting through anybody.
    Measured: 8 of 35."""
    worst = d.profile_for(d.DefenseLevel.SANDLOT)
    through = [a for a in _misplayed(worst, 300, shape="GROUNDER")
               if a._misplay_kind == "THROUGH"]
    assert through
    assert all(a._beaten_roles for a in through)
    recovered = sum(a._primary_role in a._beaten_roles for a in through)
    assert recovered / len(through) < 0.45, f"{recovered}/{len(through)}"


def test_a_through_ball_keeps_the_pace_it_had():
    """The ball has to carry past the fielder, and the speed it carries at is
    the one `infield_timing`'s retention curve gives it — the same curve the
    infield race times the ball with, so the ball that beats the shortstop is
    the ball the verdict was computed against."""
    worst = d.profile_for(d.DefenseLevel.SANDLOT)
    through = [a for a in _misplayed(worst, 300, shape="GROUNDER")
               if a._misplay_kind == "THROUGH"]
    assert through
    from strikefactor.gameplay import hit_animation as ha
    travelled = []
    for a in through:
        travelled.append(ha._ft_dist(a._ball[0] - a._hit_end[0],
                                     a._ball[1] - a._hit_end[1]))
    travelled.sort()
    assert travelled[len(travelled) // 2] > 40.0, f"median {travelled[len(travelled)//2]:.1f} ft"


def test_a_muffed_catch_is_always_charged_as_an_error():
    """The counterfactual is unambiguous — the fielder was going to catch it,
    so the clean play was a certain out."""
    worst = d.profile_for(d.DefenseLevel.SANDLOT)
    muffs = [a for a in _misplayed(worst, 400) if a._misplay_kind == "MUFF"]
    assert muffs, "no muffs in 400 balls against a sandlot defense"
    for anim in muffs:
        assert anim.is_error
        assert anim.classified_outcome == "REACHED ON ERROR"


def test_the_picture_and_the_record_cannot_disagree():
    """An ERROR banner over a fielder holding the ball is the failure mode
    this whole design is shaped to prevent. The label comes from the same
    branch as the fielding event, so a clean play can never carry it."""
    worst = d.profile_for(d.DefenseLevel.SANDLOT)
    rng = random.Random(77)
    for i in range(250):
        anim = _ball_in_play(i, conftest.realistic_quality(rng),
                             conftest.realistic_batted_ball(rng),
                             conftest.realistic_spray(rng), worst)
        if anim.classified_outcome == "REACHED ON ERROR":
            assert anim.is_error
            assert anim._misplay_kind is not None
        if anim._misplay_kind is None:
            assert not anim.is_error
            assert anim.classified_outcome != "REACHED ON ERROR"


def test_a_bobble_lands_on_the_release_clock():
    """It has to, or `defense_s == ball + release + throw` stops holding —
    and it is where a bobble physically belongs, since glove contact to
    release is exactly what it delays."""
    worst = d.profile_for(d.DefenseLevel.SANDLOT)
    bobbles = [a for a in _misplayed(worst, 300, shape="GROUNDER")
               if a._misplay_kind == "BOBBLE" and a.play_timing is not None]
    assert bobbles
    for anim in bobbles:
        t = anim.play_timing
        assert t.misplay_s > 0
        assert t.defense_s == pytest.approx(
            t.ball_to_glove_s + t.release_s + t.throw_flight_s)
        # A bobble can only ever hurt the defense.
        assert t.p_out_clean >= t.p_out


def test_a_clean_play_has_an_empty_error_window():
    """With no misplay, `roll_verdict` must be exactly `roll_is_out` — the
    error window is [p_out, p_out_clean) and it has to be empty."""
    best = d.profile_for(d.DefenseLevel.GOLD_GLOVE)
    rng = random.Random(9)
    seen = 0
    for i in range(200):
        anim = _ball_in_play(i, conftest.realistic_quality(rng), "GROUNDER",
                             conftest.realistic_spray(rng), best)
        if anim._misplay_kind is None and anim.play_timing is not None:
            assert anim.play_timing.p_out_clean == anim.play_timing.p_out
            assert anim.play_timing.misplay_s == 0.0
            seen += 1
    assert seen > 50


def test_a_worse_defense_commits_more_errors():
    """Measured end to end at n=2500 the ladder runs 3.04% / 2.16% / 1.00% /
    0.64% of balls in play. Only the ends are swept here; at the sample size
    a test can afford, adjacent rungs are inside each other's noise."""
    def error_rate(profile, n=260):
        plays = _sweep(profile, n, seed=808)
        live = [p for p in plays if p.classified_outcome is not None]
        errors = sum(p.classified_outcome == "REACHED ON ERROR" for p in live)
        return errors / max(1, len(live))

    worst = error_rate(d.profile_for(d.DefenseLevel.SANDLOT))
    best = error_rate(d.profile_for(d.DefenseLevel.GOLD_GLOVE))
    assert worst > best, f"sandlot {worst:.3f} vs gold glove {best:.3f}"
    assert worst > 0.01


# ---- Telling the player -----------------------------------------------------
#
# An error used to have no picture at all: the only thing that said one had
# happened was the banner, several seconds later and after the runner was
# already on. A muff read as "the ball bounced oddly" and a ball through the
# shortstop read as an ordinary base hit. The "!" is the one thing on screen
# that reports `is_error` at the moment it is charged.

def test_every_error_marks_the_fielder_who_made_it():
    """`_charge_error` is the single place `is_error` is set, which is what
    makes the mark and the outcome the same fact rendered twice.

    The fielder charged is the one who misplayed the ball, not the primary:
    a ball through the shortstop is retrieved by the left fielder, who becomes
    the primary and did nothing wrong.
    """
    worst = d.profile_for(d.DefenseLevel.SANDLOT)
    plays = _sweep(worst, 400, seed=808)
    errors = [p for p in plays if p.classified_outcome == "REACHED ON ERROR"]
    assert errors, "no errors in 400 balls against a sandlot defense"
    kinds = {p._misplay_kind for p in errors}
    assert kinds == {"BOBBLE", "THROUGH", "MUFF"}, f"only saw {kinds}"
    for anim in errors:
        assert anim._error_role is not None
        assert anim._error_marked_at_ms is not None
        assert anim._error_role == anim._misplay_role
        assert anim._error_role in anim.fielders


def test_a_clean_play_never_marks_anyone():
    """The other half of the same claim — the mark cannot appear over a
    fielder who handled the ball."""
    worst = d.profile_for(d.DefenseLevel.SANDLOT)
    for anim in _sweep(worst, 200, seed=808):
        if anim.is_error:
            continue
        assert anim._error_role is None
        assert anim._error_marked_at_ms is None
        assert anim._error_mark_alpha() == 0.0


def test_the_mark_is_brief_and_never_early():
    """It holds, fades, and is gone — and shows nothing before the misplay.

    Asserted in *real* seconds through `_anim_ms`, because the mark is a
    duration like every other one in that file and must not drift with the
    play's time scale.
    """
    from strikefactor.gameplay import hit_animation as ha

    worst = d.profile_for(d.DefenseLevel.SANDLOT)
    errors = [p for p in _sweep(worst, 200, seed=808) if p.is_error]
    assert errors
    with _scratch(errors[0]) as anim:
        anim._error_marked_at_ms = 1000.0

        anim._elapsed = 1000.0 - anim._anim_ms(0.1)
        assert anim._error_mark_alpha() == 0.0, "visible before the misplay"

        anim._elapsed = 1000.0
        assert anim._error_mark_alpha() == 1.0
        anim._elapsed = 1000.0 + anim._anim_ms(ha.ERROR_MARK_HOLD_S)
        assert anim._error_mark_alpha() == 1.0
        anim._elapsed = 1000.0 + anim._anim_ms(
            ha.ERROR_MARK_HOLD_S + ha.ERROR_MARK_FADE_S / 2.0)
        assert 0.2 < anim._error_mark_alpha() < 0.8
        anim._elapsed = 1000.0 + anim._anim_ms(
            ha.ERROR_MARK_HOLD_S + ha.ERROR_MARK_FADE_S)
        assert anim._error_mark_alpha() == 0.0
    # Brief: gone well inside the read window the banner sits in.
    assert ha.ERROR_MARK_HOLD_S + ha.ERROR_MARK_FADE_S < 2.5


def test_the_mark_actually_paints_over_the_fielders_head():
    """The alpha ramp is only half of it — the glyph has to land above the
    body, in the amber "reached, but not earned" wears everywhere else, and
    it has to be gone once it has faded."""
    import pygame

    from strikefactor.gameplay import hit_animation as ha

    worst = d.profile_for(d.DefenseLevel.SANDLOT)
    errors = [p for p in _sweep(worst, 200, seed=808) if p.is_error]
    assert errors
    with _scratch(errors[0]) as anim:
        anim._error_marked_at_ms = 1000.0
        fielder = anim.fielders[anim._error_role]

        pygame.font.init()
        screen = pygame.Surface((1280, 720))

        def amber_above_head():
            hx = int(fielder.pos[0])
            hy = int(fielder.pos[1]) - ha.ERROR_MARK_OFFSET_PX
            lit = 0
            for dx in range(-10, 11):
                for dy in range(-14, 10):
                    x = max(0, min(screen.get_width() - 1, hx + dx))
                    y = max(0, min(screen.get_height() - 1, hy + dy))
                    r, g, b, _ = screen.get_at((x, y))
                    if r > 120 and g > 70 and b < 90:
                        lit += 1
            return lit

        anim._elapsed = 1000.0 + anim._anim_ms(0.3)
        screen.fill((0, 0, 0))
        anim.draw(screen)
        assert amber_above_head() > 4, "the ! did not paint"

        anim._elapsed = 1000.0 + anim._anim_ms(
            ha.ERROR_MARK_HOLD_S + ha.ERROR_MARK_FADE_S + 0.5)
        screen.fill((0, 0, 0))
        anim.draw(screen)
        assert amber_above_head() == 0, "the ! outstayed its fade"
