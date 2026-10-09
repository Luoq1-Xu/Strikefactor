"""At-bat plans: one pitcher's approach to one plate appearance.

Every pitch used to be an independent draw from the count table, so an
at-bat had no through-line -- nothing was set up and nothing was finished,
and a slider from a given pitcher went to the same spot in every count of
every at-bat. A plan is chosen once, when the batter steps in
(`Pitcher.get_pitch_target` rolls it on the first pitch), and held until the
plate appearance ends.

A plan never chooses the pitch; the AI still does that. It decides how the
chosen pitch is *used*, by multiplying the intent probabilities and the
archetype weights per phase of the at-bat, exactly as an archetype's
`counts` entry already does. Pulls are stated in the archetype's own
batter-relative coordinates (`in_away`, `height`), so one plan serves every
pitch type, both platoons and both batter hands without listing spots.

Plans and each pitcher's mix of them are data in pitch_locations.json. A
pitcher with no mix gets `NO_PLAN`, which multiplies everything by exactly
1.0 and so pitches the book unchanged.
"""

import math
import random
from dataclasses import dataclass

from . import pitch_locations

PHASES = ('get_ahead', 'put_away', 'behind')

# Phase of the at-bat, from the count state pitcher.py already classifies.
_PHASE_OF_COUNT = {
    'first_pitch': 'get_ahead',
    'even': 'get_ahead',
    'ahead': 'put_away',
    'behind': 'behind',
    'full': 'behind',
}


def phase_for(count_state):
    return _PHASE_OF_COUNT[count_state]


def _by_class(value, pitch_class):
    """A pull is a number, or {pitch_class: number} with '*' as the default."""
    if isinstance(value, dict):
        return value.get(pitch_class, value.get('*', 0.0))
    return value


@dataclass(frozen=True)
class AtBatPlan:
    name: str
    phases: dict  # phase -> {'intent': {...}, 'in_away': pull, 'height': pull}

    def _phase(self, count_state):
        return self.phases.get(phase_for(count_state), {})

    def intent_multipliers(self, count_state):
        """{intent: multiplier} for this phase; unlisted intents are 1.0."""
        return self._phase(count_state).get('intent', {})

    def archetype_multiplier(self, count_state, pitch_class, in_away, height):
        """Weight multiplier for an archetype at (in_away, height).

        exp(pull . position): a pull of +1 on height favours an archetype at
        the top of the zone over one at the bottom by about e^2, strong
        enough to read as a plan and not enough to make any spot impossible.
        """
        phase = self._phase(count_state)
        pull_x = _by_class(phase.get('in_away', 0.0), pitch_class)
        pull_z = _by_class(phase.get('height', 0.0), pitch_class)
        return math.exp(pull_x * in_away + pull_z * height)


NO_PLAN = AtBatPlan('', {})


def choose_plan(pitcher_key):
    """Draw a plan from this pitcher's mix, or NO_PLAN when none is defined.

    The mix was validated at load (pitch_locations._load), so every name in
    it is a defined plan with a positive weight.
    """
    mix = pitch_locations.PLAN_MIX.get(pitcher_key)
    if not mix:
        return NO_PLAN
    name = random.choices(list(mix), weights=list(mix.values()), k=1)[0]
    return AtBatPlan(name, pitch_locations.PLANS[name])
