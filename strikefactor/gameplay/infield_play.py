"""Ground-ball defensive choices, expressed in real seconds and feet.

The initial transfer is sampled by infield_timing once, then shared by the
first- and second-base previews. Probabilities rank choices only; reception
and base contacts adjudicate the executed play. The pivot is shorter than a
pickup transfer because the middle infielder is receiving a prepared feed.
Its 0.45 s neutral exchange is a design value, scaled by the defense profile.
"""

from strikefactor.gameplay import infield_timing

PIVOT_EXCHANGE_S = 0.45
CHOICE_MARGIN = 0.10


def choose_infield(first, second, relay_arrival_s, batter_arrival_s, *, outs=0):
    """Take a plausible turn only when it improves the available outs."""
    if second.arrival_s > second.runner_s + infield_timing.BANG_BANG_S:
        return first
    first_value = infield_timing.p_out_from_margin(first.runner_s - first.arrival_s)
    second_value = infield_timing.p_out_from_margin(second.runner_s - second.arrival_s)
    if outs < 2:
        second_value += infield_timing.p_out_from_margin(batter_arrival_s - relay_arrival_s)
    return second if second_value > first_value + CHOICE_MARGIN else first
