"""Retouch duties on a caught fly ball, read off the played routes. No RNG.

A runner may leave his base once a fielder first touches a fly ball that is
then caught. One who left before that touch must retouch his base, and the
defense can put him out by holding the ball on that base, or by tagging
him, before he does (OBR 5.09(c)(1)). Nobody is ever out merely for leaving
early: the defense has to make the play.

The duty is a reading of the runner's `CircuitRun` and the time of the
touch, not a second record of where he has been, so the picture, the
defense's choice and the scorer cannot disagree about it. All times are
contact-relative real seconds.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RetouchDuty:
    runner_id: str
    base: int
    departed_s: float
    first_touch_s: float


def retouch_s(route, first_touch_s, *, routes=None):
    """When the runner is on his original bag at or after the touch, or None.

    Planned contacts count, so a runner who is retracing has a retouch
    time before he gets there. A runner standing on the bag at the touch
    tags up at the touch itself.
    """
    for arrive, leave in route.contacts(route.start_base):
        if leave >= first_touch_s:
            back = max(arrive, first_touch_s)
            if routes is not None and not _can_correct(route, routes, back):
                return None
            return back
    return None


def duty(runner_id, route, first_touch_s):
    """The retouch this runner owes because of the touch, or None.

    The batter is never subject to it, and neither is a runner who was on
    his base when the ball was first touched.
    """
    if (runner_id == "B" or route.start_base < 1 or first_touch_s is None
            or (route.stopped_at_s is not None and route.stopped_at_s <= first_touch_s)):
        return None
    spans = route.contacts(route.start_base)
    if any(arrive <= first_touch_s <= leave for arrive, leave in spans):
        return None
    departed = max((leave for _, leave in spans if leave < first_touch_s), default=0.0)
    return RetouchDuty(runner_id, route.start_base, departed, first_touch_s)


def duties(routes, first_touch_s):
    """Every runner who was off his base when the caught ball was touched."""
    found = (duty(rid, route, first_touch_s) for rid, route in routes.items())
    return {d.runner_id: d for d in found if d is not None}


def owes(route, first_touch_s, now_s, *, motion_through_s=None, routes=None):
    """Is the runner still short of his retouch at `now_s`?"""
    if route.stopped_at_s is not None and route.stopped_at_s <= now_s:
        return False
    back = retouch_s(route, first_touch_s, routes=routes)
    through = min(now_s, motion_through_s) if motion_through_s is not None else now_s
    return back is None or back > through


def can_correct(runner_id, routes, now_s):
    """A following runner scoring closes the opportunity to correct (5.09(c)(2))."""
    return _can_correct(routes[runner_id], routes, now_s)


def _can_correct(route, routes, time_s):
    return not any(other.start_base < route.start_base and any(base == 4 and t <= time_s
                   for base, t in other.touches(time_s)) for other in routes.values())
