from helper.pitcher import Pitcher
import random

class ERAI():

    def __init__(self, actions: list, alpha=0.5, epsilon=0.1):
        """
        Initialize AI with an empty Q-learning dictionary,
        an alpha (learning) rate, and an epsilon rate.

        The Q-learning dictionary maps `(state, action)`
        pairs to a Q-value (a number).
         - `state` is a tuple of remaining piles, e.g. (1, 1, 4, 4)
         - `action` is a tuple `(i, j)` for an action
        """
        self.q = dict()
        self.alpha = alpha
        self.epsilon = epsilon
        self.actions = actions

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
        is the sum of the current reward and estimated future rewards.
        """
        self.q[(tuple(state), action)] = old_q + (self.alpha * (reward + future_rewards - old_q))

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

    def choose_action(self, state, epsilon=True):
        """
        Given a state `state`, return an action `(i, j)` to take.

        If `epsilon` is `False`, then return the best action
        available in the state (the one with the highest Q-value,
        using 0 for pairs that have no Q-values).

        If `epsilon` is `True`, then with probability
        `self.epsilon` choose a random available action,
        otherwise choose the best action available.

        If multiple actions have the same Q-value, any of those
        options is an acceptable return value.
        """
        actions = self.actions
        action_value = {}
        for action in actions:
            if (state, action) in self.q:
                action_value[action] = self.q[(state, action)]
            else:
                action_value[action] = 0
        max_actions = [action for action in actions if action_value[action] == max(action_value.values())]
        if len(max_actions) > 1:
            best_action = random.choice(max_actions)
        else:
            best_action = max_actions[0]
        if epsilon:
            random_action = random.choice(actions)
            return random.choices([random_action, best_action], weights=[self.epsilon, 1-self.epsilon], k=1)[0]
        else:
            return best_action