"""Live force obligations, shared by defensive races and runner commands.

The initial occupied chain establishes a force. Touching the required bag
discharges it; retiring any following runner removes it. These questions use
the played routes at an instant, never a forecast out or a target assignment.
All times are contact-relative real seconds.
"""


def forced_base(runner_id, routes, time_s):
    route = routes[runner_id]

    def alive(other):
        return other.stopped_at_s is None or other.stopped_at_s > time_s

    if not alive(route):
        return None
    base = route.start_base
    if base == 0:
        return 1 if route.base_at(time_s) < 1 else None
    following = {r.start_base: r for r in routes.values() if r.start_base < base}
    if any(b not in following or not alive(following[b]) for b in range(base)):
        return None
    # Returning behind a forced bag reestablishes the obligation (5.09(b)(6)).
    if route.base_at(time_s) >= base + 1 and not (route.returning and route.target_base <= base):
        return None
    return base + 1
