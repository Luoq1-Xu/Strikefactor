"""Does the batter-runner take the extra base?

The same race as `infield_timing`, one base over, and per the recorded data
the larger of the two distortions: doubles ran at 0.96 per single against an
MLB 0.32, and triples at 7-8% of hits against ~1%.

What it replaced was `RETRIEVE_TIME_SINGLE_MAX_MS = 2800` /
`..._DOUBLE_MAX_MS = 4200` — animated milliseconds from landing to pickup,
against two fixed thresholds. Two things were wrong with that and both are
guarded here: it could see how *long* the fielder took but not where they
ended up, and it lived on the presentation clock, so unifying that clock
moved triples from 8% of hits to 23% without anyone touching a constant.
"""

import random

import pytest

from strikefactor.gameplay import extra_bases as xb

# ---- The runner ------------------------------------------------------------

def test_bases_after_the_first_are_run_with_a_running_start():
    """Home-to-first is a standing start with a bat to drop; every base
    after it is run at speed. MLB home-to-second on a double is ~7.8 s
    against a 4.3 s home-to-first."""
    first = xb.home_to_base_s(1)
    second = xb.home_to_base_s(2)
    third = xb.home_to_base_s(3)
    assert 4.2 <= first <= 4.4
    assert 7.5 <= second <= 8.1
    assert 10.8 <= third <= 11.6
    # Later legs are quicker than the first, and equal to each other.
    assert (second - first) < first
    assert (third - second) == pytest.approx(second - first)


def test_a_faster_runner_gains_more_over_a_longer_advance():
    """Why triples belong to fast runners: the advantage compounds per leg
    rather than being a one-off bonus at first."""
    slow_gap = xb.home_to_base_s(1, sprint_fts=23) - xb.home_to_base_s(1, sprint_fts=30)
    long_gap = xb.home_to_base_s(3, sprint_fts=23) - xb.home_to_base_s(3, sprint_fts=30)
    assert long_gap > slow_gap * 2


def test_difficulty_reaches_the_base_race_too():
    """Difficulty is time on the runner's clock, and it must not stop
    applying once the runner rounds first."""
    easy = xb.home_to_base_s(2, difficulty_offset_s=-0.15)
    hard = xb.home_to_base_s(2, difficulty_offset_s=+0.30)
    assert hard > easy


# ---- The throw -------------------------------------------------------------

def test_where_the_ball_was_retrieved_is_what_matters():
    """The property the retrieve-time thresholds could not express: two
    balls picked up at the same moment, one in shallow left and one at the
    wall, are not the same play."""
    shallow = xb.defense_to_base_s(2, (0.0, 200.0), retrieved_at_s=4.0)
    deep = xb.defense_to_base_s(2, (0.0, 380.0), retrieved_at_s=4.0)
    assert deep > shallow + 1.0


def test_long_throws_go_through_a_cutoff_man():
    """A relay is not slower per foot — the two legs are thrown harder than
    one 250 ft heave — but the exchange costs a fixed beat, and that beat is
    what gives the runner a chance."""
    near = xb.throw_to_base_s((0.0, 127.28 + xb.RELAY_DISTANCE_FT - 10), 2)
    far = xb.throw_to_base_s((0.0, 127.28 + xb.RELAY_DISTANCE_FT + 10), 2)
    assert far - near > xb.RELAY_EXCHANGE_S * 0.9


def test_an_outfielder_is_slower_to_release_than_an_infielder():
    """An outfielder throwing to a base crow-hops into it."""
    of = xb.defense_to_base_s(2, (0.0, 250.0), 4.0, is_outfielder=True)
    inf = xb.defense_to_base_s(2, (0.0, 250.0), 4.0, is_outfielder=False)
    assert of > inf


# ---- The decision ----------------------------------------------------------

def test_a_ball_fielded_quickly_holds_the_runner_at_first():
    """A routine single to left: the outfielder has the ball long before
    the runner could reach second."""
    base, _ = xb.final_base((-80.0, 240.0), retrieved_at_s=4.0)
    assert base == 1


def test_a_ball_that_gets_deep_is_a_double():
    base, _ = xb.final_base((0.0, 370.0), retrieved_at_s=6.0)
    assert base >= 2


def test_a_runner_needs_daylight_not_just_a_dead_heat():
    """A third-base coach does not send a runner who arrives level with the
    throw. Without `AGGRESSION_MARGIN_S` runners take every base they can
    theoretically reach and every gapper is a triple — which is the shape
    the retrieve-time thresholds produced."""
    ball, retrieved = (0.0, 300.0), 5.2
    runner_s = xb.home_to_base_s(2)
    defense_s = xb.defense_to_base_s(2, ball, retrieved)
    # Set up a play the runner wins by less than the margin.
    assert 0 < defense_s - runner_s < xb.AGGRESSION_MARGIN_S
    base, _ = xb.final_base(ball, retrieved)
    assert base == 1, "runner advanced on a play they only barely win"


def test_the_wall_floor_cannot_be_undercut():
    """A ball that reached the wall is past every outfielder by definition,
    so it is never a single however fast the carom comes back."""
    base, _ = xb.final_base((0.0, 200.0), retrieved_at_s=3.0, min_base=2)
    assert base >= 2


def _race_s(base, ball, retrieved):
    """`runner_s - defense_s` to `base`: the infield margin's sign."""
    return xb.home_to_base_s(base) - xb.defense_to_base_s(base, ball, retrieved)


_GAPPER = (-150.0, 330.0)


@pytest.mark.parametrize("retrieved,base", [(4.0, 1), (7.0, 2), (8.0, 3)])
def test_the_margin_reported_is_the_race_that_settled_the_hit(retrieved, base):
    """`extra_base_margin_s` is only falsifiable if it describes the race that
    decided how far the runner got: the base they held short of, or third on
    a triple. It used to be the race to second on both a single (declined)
    and a double (won), and nothing read it, so nothing noticed."""
    got, margin = xb.final_base(_GAPPER, retrieved_at_s=retrieved)
    assert got == base
    decisive = min(base + 1, 3)
    assert margin == pytest.approx(_race_s(decisive, _GAPPER, retrieved))


@pytest.mark.parametrize("retrieved", [3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 10.0])
def test_the_margin_is_the_physical_race_signed_like_the_infield_one(retrieved):
    """Positive favours the defense, as `PlayTiming.margin_s` does, and it is
    the race itself rather than the coach's decision about it: a runner who
    held lacked `AGGRESSION_MARGIN_S` of daylight — and may still have been
    ahead of the throw — while one who reached third had more than it."""
    base, margin = xb.final_base(_GAPPER, retrieved_at_s=retrieved)
    if base < 3:
        assert margin >= -xb.AGGRESSION_MARGIN_S
    else:
        assert margin < -xb.AGGRESSION_MARGIN_S


def test_a_runner_held_while_ahead_of_the_throw_reads_as_ahead():
    """The case the old aggression-shifted margin could not express: beating
    the throw to second by a third of a second is not enough to be sent."""
    base, margin = xb.final_base(_GAPPER, retrieved_at_s=4.0)
    assert base == 1
    assert -xb.AGGRESSION_MARGIN_S < margin < 0.0


def test_a_runner_tagged_out_reports_the_race_they_lost_on_the_tag():
    """Sent with daylight and beaten by the tag: that base's race settled it."""
    class _TagAlwaysWins:
        def random(self):
            return 1.0          # above any p_safe short of certainty

    base, margin = xb.final_base(_GAPPER, retrieved_at_s=5.0, rng=_TagAlwaysWins())
    assert base == 2
    assert margin == pytest.approx(_race_s(2, _GAPPER, 5.0))


def test_faster_runners_take_more_bases_over_many_plays():
    rng = random.Random(4)
    def total(sprint):
        return sum(xb.final_base((0.0, 300.0), retrieved_at_s=5.0 + rng.random(),
                                 sprint_fts=sprint, rng=rng)[0]
                   for _ in range(200))
    assert total(30.0) > total(23.0)
