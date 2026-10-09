import math
import random

# Version tag for state format compatibility
AI_VERSION = 2

class ERAI():

    # Discount factor for future reward. Defined at class level so instances
    # unpickled from models trained before gamma existed fall back to this
    # value instead of raising AttributeError in update_q_value().
    gamma = 0.9

    # Floor for the visit-annealed learning rate. Roughly a 12-pitch memory,
    # which keeps in-game adaptation alive without letting the table thrash.
    ALPHA_MIN = 0.08

    def __init__(self, actions: list, alpha=0.5, epsilon=0.1, gamma=0.9):
        """
        Initialize AI with an empty Q-learning dictionary,
        an alpha (learning) rate, an epsilon rate, and a gamma
        (discount) rate.

        The Q-learning dictionary maps `(state, action)`
        pairs to a Q-value (a number).
         - `state` is a tuple of remaining piles, e.g. (1, 1, 4, 4)
         - `action` is a tuple `(i, j)` for an action
        """
        self.q = dict()
        self.visits = dict()
        self.alpha = alpha
        self.epsilon = epsilon
        self.gamma = gamma
        self.actions = actions
        self.version = AI_VERSION

    # --- Pitch Sequencing Data ---

    # Tunnel pairs: pitches that look similar out of the hand but break differently.
    # Defined as {pitch_type: [good_follow_up_pitches]}
    # Can be overridden per-pitcher via set_tunnel_pairs().
    DEFAULT_TUNNEL_PAIRS = {
        'FF': ['SL', 'CH', 'CB', 'SLD', 'FS'],
        'SI': ['CH', 'SL', 'CB'],
        'SL': ['FF', 'SI', 'CH'],
        'CB': ['FF', 'SI'],
        'CH': ['FF', 'SI', 'SL'],
        'FO': ['FF', 'SI'],
        'FS': ['FF', 'SI'],
        'SLD': ['FF', 'SI'],
    }

    TUNNEL_BONUS = 0.25       # Q-value bonus for good tunnel follow-up
    REPETITION_PENALTY = -0.4  # Penalty for throwing same pitch 3x in a row

    # --- Usage Prior Data ---

    # Pitch groups used to shift arsenal usage by count. Cutters sit between
    # a fastball and a breaking ball in how count-dependent their usage is.
    PITCH_GROUPS = {
        'FF': 'fastball', 'SI': 'fastball',
        'FC': 'hard',
        'SL': 'soft', 'SLD': 'soft', 'CB': 'soft',
        'CH': 'soft', 'FS': 'soft', 'FO': 'soft',
    }

    # Multipliers applied to the base usage prior per count state, then
    # renormalized. Tuned by replaying every logged pitch context through
    # selection; the resulting fastball rates land at ~53% on 0-0, ~75%
    # when behind, ~35% when ahead and ~56% full, against league splits of
    # roughly 55 / 72 / 36 / 56.
    COUNT_USAGE_MULTIPLIERS = {
        'first_pitch': {'fastball': 1.15, 'hard': 1.00, 'soft': 0.88},
        'ahead':       {'fastball': 0.82, 'hard': 0.95, 'soft': 1.26},
        'behind':      {'fastball': 1.80, 'hard': 1.10, 'soft': 0.48},
        'even':        {'fastball': 1.08, 'hard': 1.00, 'soft': 0.95},
        'full':        {'fastball': 1.40, 'hard': 1.05, 'soft': 0.78},
    }

    # Softmax temperature over Q-values. Within-state Q spreads run ~0.4-0.7
    # median / ~1.5 at p90, so 0.65 leaves the best pitch clearly favored
    # (roughly 2-3x the worst) without making selection deterministic.
    TEMPERATURE = 0.65
    # Weight on the log usage prior. Higher = closer to the real-world mix,
    # lower = more willing to abandon the book for what is working. Tuned by
    # replaying all logged pitch contexts against the target mixes: 1.10
    # minimized both mix error and fastball-by-count error.
    PRIOR_WEIGHT = 1.10
    MIN_PRIOR = 0.005

    def set_tunnel_pairs(self, tunnel_pairs):
        """Override default tunnel pairs with pitcher-specific ones."""
        self._tunnel_pairs = tunnel_pairs

    def _get_tunnel_pairs(self):
        """Get active tunnel pairs (pitcher-specific or default)."""
        return getattr(self, '_tunnel_pairs', self.DEFAULT_TUNNEL_PAIRS)

    def set_usage_prior(self, usage):
        """Set the pitcher's baseline arsenal usage (see ai/pitch_priors.py).

        `usage` maps pitch type to a relative weight; it is normalized over
        this AI's action list. Pitches missing from `usage` fall back to an
        even share of whatever weight is left over, so a partially specified
        mix still behaves sensibly.
        """
        if not usage or not self.actions:
            self._usage_prior = None
            return

        known = {a: float(usage[a]) for a in self.actions if usage.get(a, 0) > 0}
        unknown = [a for a in self.actions if a not in known]
        known_total = sum(known.values())
        if known_total <= 0:
            self._usage_prior = None
            return

        # Give unlisted pitches a small share rather than zero, splitting an
        # extra 10% of the total across them.
        if unknown:
            leftover = known_total * 0.10
            for a in unknown:
                known[a] = leftover / len(unknown)

        total = sum(known.values())
        self._usage_prior = {a: known[a] / total for a in self.actions}

    def _get_usage_prior(self):
        """Base usage prior, or a uniform mix when none was attached."""
        prior = getattr(self, '_usage_prior', None)
        if prior:
            return prior
        if not self.actions:
            return {}
        share = 1.0 / len(self.actions)
        return {a: share for a in self.actions}

    def _count_adjusted_prior(self, count_state):
        """Base usage prior shifted for the count, renormalized."""
        prior = self._get_usage_prior()
        mults = self.COUNT_USAGE_MULTIPLIERS.get(count_state)
        if not mults or not prior:
            return prior

        adjusted = {}
        for action, weight in prior.items():
            group = self.PITCH_GROUPS.get(action, 'soft')
            adjusted[action] = weight * mults.get(group, 1.0)

        total = sum(adjusted.values())
        if total <= 0:
            return prior
        return {a: w / total for a, w in adjusted.items()}

    def _selection_logits(self, action_value, count_state):
        """Combine Q-values and the usage prior into softmax logits."""
        prior = self._count_adjusted_prior(count_state)
        temperature = max(1e-3, self.TEMPERATURE)
        logits = {}
        for action in self.actions:
            p = max(prior.get(action, self.MIN_PRIOR), self.MIN_PRIOR)
            logits[action] = (action_value[action] / temperature
                              + self.PRIOR_WEIGHT * math.log(p))
        return logits

    def selection_probabilities(self, action_value, count_state='even'):
        """Softmax over the combined logits, mixed with `epsilon` uniform noise.

        Returns {action: probability}. Exposed (rather than inlined into
        choose_action) so the pitch mix can be inspected offline without
        sampling thousands of pitches.
        """
        logits = self._selection_logits(action_value, count_state)
        top = max(logits.values())
        weights = {a: math.exp(logits[a] - top) for a in self.actions}
        total = sum(weights.values())
        if total <= 0:
            share = 1.0 / len(self.actions)
            return {a: share for a in self.actions}

        # Blend in a uniform floor so epsilon keeps its "wildcard rate"
        # meaning now that selection is stochastic rather than argmax.
        eps = max(0.0, min(1.0, self.epsilon))
        uniform = 1.0 / len(self.actions)
        return {a: (1 - eps) * (w / total) + eps * uniform
                for a, w in weights.items()}

    def update(self, old_state, action, new_state, reward):
        """
        Update Q-learning model, given an old state, an action taken
        in that state, a new resulting state, and the reward received
        from taking that action.
        """
        old = self.get_q_value(old_state, action)
        best_future = self.best_future_reward(new_state)
        self.update_q_value(old_state, action, old, reward, best_future)

    def get_q_value(self, state, action):
        """
        Return the Q-value for the state `state` and the action `action`.
        If no Q-value exists yet in `self.q`, return 0.
        """
        if (tuple(state), action) in self.q:
            return self.q[(tuple(state), action)]
        return 0

    def update_q_value(self, state, action, old_q, reward, future_rewards):
        """
        Update the Q-value for the state `state` and the action `action`
        given the previous Q-value `old_q`, a current reward `reward`,
        and an estimate of future rewards `future_rewards`.

        Use the formula:

        Q(s, a) <- old value estimate
                   + alpha * (new value estimate - old value estimate)

        where `old value estimate` is the previous Q-value,
        `alpha` is the learning rate, and `new value estimate`
        is the sum of the current reward and the gamma-discounted
        estimate of future rewards. Discounting future_rewards by
        gamma (< 1) keeps the values from diverging in the continuing
        per-pitch update loop.

        The learning rate anneals with visit count (see _effective_alpha) so
        a single home run or strikeout can't swing a well-visited Q-value by
        half its magnitude, which is what let the table lock onto one pitch.
        """
        key = (tuple(state), action)
        alpha = self._effective_alpha(key)
        self.q[key] = old_q + (alpha * (reward + self.gamma * future_rewards - old_q))
        visits = self._get_visits()
        visits[key] = visits.get(key, 0) + 1

    def _get_visits(self):
        """Per-(state, action) visit counts, created lazily.

        Models pickled before visit tracking existed have no `visits` dict,
        so this backfills one instead of raising AttributeError.
        """
        visits = getattr(self, 'visits', None)
        if visits is None:
            visits = {}
            self.visits = visits
        return visits

    def _effective_alpha(self, key):
        """Learning rate for one (state, action), annealed by visit count.

        Starts at `self.alpha` for an unseen pair and decays as 1/(1+n), with
        a floor so the AI never stops adapting to a player who changes their
        approach mid-game.
        """
        n = self._get_visits().get(key, 0)
        return max(self.ALPHA_MIN, self.alpha / (1.0 + n))

    def best_future_reward(self, state):
        """
        Given a state `state`, consider all possible `(state, action)`
        pairs available in that state and return the maximum of all
        of their Q-values.

        Use 0 as the Q-value if a `(state, action)` pair has no
        Q-value in `self.q`. If there are no available actions in
        `state`, return 0.
        """
        actions = self.actions
        if not actions:
            return 0
        q_values = []
        for action in actions:
            if (tuple(state), action) in self.q:
                q_values.append(self.q[(tuple(state), action)])
            else:
                q_values.append(0)
        return max(q_values)

    def choose_action(self, state, epsilon=True, batter_profile=None,
                      pitch_history=None, count_state='even'):
        """
        Given a state `state`, return an action to take.

        If `epsilon` is `False`, then return the best action
        available in the state (the one with the highest Q-value,
        using 0 for pairs that have no Q-values).

        If `epsilon` is `True`, sample from a softmax over the combined
        Q-value and usage-prior score. Sampling rather than taking the argmax
        is what keeps the pitcher from throwing the same pitch every time it
        sees a given count — see set_usage_prior() and TEMPERATURE.

        Additional modifiers:
        - batter_profile: BatterProfile instance for tendency-based bonuses
        - pitch_history: list of recent pitch types thrown (most recent last)
        - count_state: current count state, used for both the usage prior and
          the batter profile bonuses
        """
        actions = self.actions
        action_value = {}

        # Normalize the state key the same way get_q_value/update do, so a
        # list state can't silently miss every Q-entry (or raise on hashing).
        state = tuple(state)

        # Base Q-values
        for action in actions:
            if (state, action) in self.q:
                action_value[action] = self.q[(state, action)]
            else:
                action_value[action] = 0

        # Apply batter tendency bonuses
        if batter_profile is not None:
            bonuses = batter_profile.get_pitch_bonuses(actions, count_state)
            for action in actions:
                action_value[action] += bonuses.get(action, 0.0)

        # Apply sequencing modifiers
        if pitch_history:
            tunnel_pairs = self._get_tunnel_pairs()
            last_pitch = pitch_history[-1] if pitch_history else None

            for action in actions:
                # Tunnel bonus: reward pitches that tunnel well off the previous pitch
                if last_pitch and last_pitch in tunnel_pairs:
                    if action in tunnel_pairs[last_pitch]:
                        action_value[action] += self.TUNNEL_BONUS

                # Repetition penalty: penalize throwing same pitch 3+ times in a row
                if len(pitch_history) >= 2:
                    if pitch_history[-1] == action and pitch_history[-2] == action:
                        action_value[action] += self.REPETITION_PENALTY

        if not epsilon:
            # Deterministic pick, still prior-aware so it reflects what the
            # pitcher would most likely throw rather than raw Q alone.
            logits = self._selection_logits(action_value, count_state)
            max_val = max(logits.values())
            max_actions = [a for a in actions if logits[a] == max_val]
            return random.choice(max_actions) if len(max_actions) > 1 else max_actions[0]

        probs = self.selection_probabilities(action_value, count_state)
        return random.choices(actions, weights=[probs[a] for a in actions], k=1)[0]


def build_state(outs, strikes, balls, runners, pitch_number_in_ab,
                prev_pitch, handedness, score_diff):
    """Build a bounded state tuple for the AI.

    Args:
        outs: Current outs (0-2)
        strikes: Current strikes (0-2)
        balls: Current balls (0-3)
        runners: Number of runners on base (0-3)
        pitch_number_in_ab: Pitch number in current at-bat (1+)
        prev_pitch: Previous pitch type string, or None
        handedness: Batter handedness ('L' or 'R')
        score_diff: Runs allowed minus runs scored (positive = pitcher losing)

    Returns:
        Bounded state tuple for Q-learning lookup.
    """
    # Cap pitch number at 4+ bucket
    pitch_bucket = min(pitch_number_in_ab, 4)

    # Clamp score differential to [-2, 2] buckets
    score_bucket = max(-2, min(2, score_diff))

    # Previous pitch as string or 'none'
    prev = prev_pitch if prev_pitch is not None else 'none'

    return (outs, strikes, balls, runners, pitch_bucket, prev, handedness, score_bucket)
