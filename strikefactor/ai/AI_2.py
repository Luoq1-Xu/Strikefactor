import random

# Version tag for state format compatibility
AI_VERSION = 2

class ERAI():

    # Discount factor for future reward. Defined at class level so instances
    # unpickled from models trained before gamma existed fall back to this
    # value instead of raising AttributeError in update_q_value().
    gamma = 0.9

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

    def set_tunnel_pairs(self, tunnel_pairs):
        """Override default tunnel pairs with pitcher-specific ones."""
        self._tunnel_pairs = tunnel_pairs

    def _get_tunnel_pairs(self):
        """Get active tunnel pairs (pitcher-specific or default)."""
        return getattr(self, '_tunnel_pairs', self.DEFAULT_TUNNEL_PAIRS)

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
        """
        self.q[(tuple(state), action)] = old_q + (self.alpha * (reward + self.gamma * future_rewards - old_q))

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

        If `epsilon` is `True`, then with probability
        `self.epsilon` choose a random available action,
        otherwise choose the best action available.

        Additional modifiers:
        - batter_profile: BatterProfile instance for tendency-based bonuses
        - pitch_history: list of recent pitch types thrown (most recent last)
        - count_state: current count state string for batter profile bonuses
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

        # Find best action(s)
        max_val = max(action_value.values())
        max_actions = [a for a in actions if action_value[a] == max_val]
        best_action = random.choice(max_actions) if len(max_actions) > 1 else max_actions[0]

        if epsilon:
            random_action = random.choice(actions)
            return random.choices([random_action, best_action],
                                  weights=[self.epsilon, 1 - self.epsilon], k=1)[0]
        else:
            return best_action


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
