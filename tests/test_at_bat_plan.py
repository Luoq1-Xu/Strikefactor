"""At-bat plans: chosen when the batter steps in, held for the plate
appearance, and a re-weighting of the book rather than a replacement for it.
"""

import json
import random
from collections import Counter

import pygame
import pytest

from strikefactor import config
from strikefactor.pitchers import pitch_locations as pl
from strikefactor.pitchers.at_bat_plan import NO_PLAN, PHASES, AtBatPlan, choose_plan, phase_for
from strikefactor.pitchers.pitch_locations import INTENTS
from strikefactor.pitchers.pitcher import Pitcher

COUNTS = {'first_pitch': (0, 0), 'even': (1, 1), 'ahead': (0, 2),
          'behind': (2, 0), 'full': (3, 2)}


class _Game:
    def __init__(self, balls=0, strikes=0, pitchnumber=1):
        self.currentballs = balls
        self.currentstrikes = strikes
        self.pitchnumber = pitchnumber
        self.batter = None
        self.last_pitch_type_thrown = None


def _pitcher(key, throws='R'):
    cls = type(key.capitalize(), (Pitcher,), {})
    return cls(0, 0, pygame.Vector2(600, 300), None, key, 1000, 6.5, throws=throws)


def _sample(p, pitch, count_state, plan, n):
    """Intent shares and mean intended (in_away, height) under one plan.

    `plan` is an AtBatPlan, None for the plan-free book, or 'mix' to re-roll
    from the pitcher's mix every pitch, which averages over it.
    """
    balls, strikes = COUNTS[count_state]
    game = _Game(balls, strikes)
    p.set_game_ref(game)
    half_w = (p.ZONE_RIGHT - p.ZONE_LEFT) / 2
    half_h = (p.ZONE_BOTTOM - p.ZONE_TOP) / 2
    intents = Counter()
    in_away = height = 0.0
    for _ in range(n):
        if plan == 'mix':
            game.pitchnumber = 0
        else:
            p.plan = plan
        p.get_pitch_target(pitch)
        li = p.last_intent
        intents[li.intent_kind] += 1
        in_away += (li.intent_x - p.ZONE_CENTER_X) * p.in_sign('R') / half_w
        height += (p.ZONE_CENTER_Y - li.intent_y) / half_h
    return ({k: intents[k] / n for k in INTENTS}, in_away / n, height / n)


def test_every_pitcher_mix_names_defined_plans_and_every_plan_is_well_formed():
    with open(pl._PATH) as f:
        raw = json.load(f)['pitchers']
    for key in config.ALL_PITCHERS:
        # _load skips a bad mix entry with a warning, so nothing may be missing.
        assert pl.PLAN_MIX[key] and pl.PLAN_MIX[key] == raw[key]['_plans'], key
    for name, phases in pl.PLANS.items():
        assert set(phases) <= set(PHASES), (name, phases)
        for phase in phases.values():
            assert set(phase) <= {'intent', 'in_away', 'height'}, (name, phase)
            assert set(phase.get('intent', {})) <= pl.VALID_INTENTS, (name, phase)


def test_every_count_state_maps_to_a_phase():
    count_states = set(Pitcher.INTENT_TABLE['fastball'])
    assert set(COUNTS) == count_states
    for count_state in count_states:
        assert phase_for(count_state) in PHASES


def test_a_plan_is_rolled_when_the_batter_steps_in_and_held_for_the_at_bat():
    random.seed(11)
    p = _pitcher('degrom')
    game = _Game(pitchnumber=0)
    p.set_game_ref(game)
    p.get_pitch_target('FF')
    first = p.plan
    assert first is not None and first.name in pl.PLANS
    assert p.last_intent.plan == first.name

    for pitchnumber in range(1, 8):
        game.pitchnumber = pitchnumber
        game.currentstrikes = min(2, pitchnumber)
        p.get_pitch_target('SL')
        assert p.plan is first

    seen = set()
    for _ in range(200):
        game.pitchnumber = 0
        p.get_pitch_target('FF')
        seen.add(p.plan.name)
    assert seen == set(pl.PLAN_MIX['degrom'])


def test_a_pitcher_with_no_mix_pitches_the_book_unchanged():
    p = _pitcher('nobody')
    assert choose_plan('nobody') is NO_PLAN
    p.set_game_ref(_Game(pitchnumber=0))
    p.get_pitch_target('FF')
    assert p.plan is NO_PLAN
    assert p.last_intent.plan == ''


def test_an_empty_phase_is_the_identity():
    plan = AtBatPlan('flat', {})
    assert plan.intent_multipliers('ahead') == {}
    for pitch_class in ('fastball', 'breaking'):
        assert plan.archetype_multiplier('ahead', pitch_class, 1.3, -1.9) == 1.0


def test_a_pull_can_send_the_fastball_up_and_the_breaking_ball_down():
    ladder = AtBatPlan('ladder', pl.PLANS['ladder'])
    up, down = (0.0, 1.0), (0.0, -1.0)
    assert ladder.archetype_multiplier('ahead', 'fastball', *up) > \
        ladder.archetype_multiplier('ahead', 'fastball', *down)
    assert ladder.archetype_multiplier('ahead', 'breaking', *up) < \
        ladder.archetype_multiplier('ahead', 'breaking', *down)


@pytest.mark.parametrize('pitch', ['FF', 'SL'])
def test_averaged_over_the_mix_the_season_mix_is_still_the_book(pitch):
    """The plan moves pitches between at-bats, not the season-level rates.

    Measured drift is ~0.02 per intent; the band is 3 sigma at this n.
    """
    random.seed(23)
    p = _pitcher('degrom')
    n = 2000
    for count_state in COUNTS:
        book, _, _ = _sample(p, pitch, count_state, None, n)
        mixed, _, _ = _sample(p, pitch, count_state, 'mix', n)
        for intent in INTENTS:
            assert abs(mixed[intent] - book[intent]) < 0.05, (count_state, intent, book, mixed)


def test_two_plans_use_the_same_pitch_differently_within_an_at_bat():
    random.seed(31)
    n = 1500
    plans = {name: AtBatPlan(name, phases) for name, phases in pl.PLANS.items()}

    # steal_early: the breaking ball comes for a strike early in the at-bat.
    degrom = _pitcher('degrom')
    book, _, _ = _sample(degrom, 'SL', 'first_pitch', None, n)
    steal, _, _ = _sample(degrom, 'SL', 'first_pitch', plans['steal_early'], n)
    assert steal['zone'] > book['zone'] + 0.08

    # ladder: with two strikes the fastball climbs higher than under east_west.
    _, _, ladder_h = _sample(degrom, 'FF', 'ahead', plans['ladder'], n)
    _, _, ew_h = _sample(degrom, 'FF', 'ahead', plans['east_west'], n)
    assert ladder_h > ew_h + 0.2

    # jam_then_expand: Sale's put-away sweeper leaves the back foot for away.
    sale = _pitcher('sale', throws='L')
    _, jam_x, _ = _sample(sale, 'SL', 'ahead', plans['jam_then_expand'], n)
    _, ladder_x, _ = _sample(sale, 'SL', 'ahead', plans['ladder'], n)
    assert jam_x < ladder_x - 0.5
