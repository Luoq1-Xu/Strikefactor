"""Explicit one-base commands and a generous live decision window, no RNG.

Manual running gets one ordinary base. Every later base has an explicit
Send destination. The clock closes only after possession and routes settle.
"""

from dataclasses import dataclass, field

DECISION_WINDOW_S = 2.5


@dataclass
class BaserunningControl:
    mode: str = "auto"
    runner_id: str | None = None
    opened_s: float | None = None
    requested_s: float | None = None
    executed_s: float | None = None
    destination: int | None = None
    state: str = "waiting"
    reason: str | None = None
    pending_base: int | None = None
    deadline_s: float | None = None
    closed: bool = False
    commands: list = field(default_factory=list)

    def open(self, runner_id, time_s):
        if self.mode != "manual" or self.closed:
            return
        if self.runner_id != runner_id:
            self.cancel_pending("runner changed")
            self.runner_id = runner_id
            self.state, self.destination = "available", None
        if self.opened_s is None:
            self.opened_s = time_s

    @property
    def closes_s(self):
        return self.deadline_s

    def available(self, time_s):
        return (self.mode == "manual" and not self.closed and self.opened_s is not None
                and time_s >= self.opened_s
                and (self.deadline_s is None or time_s < self.deadline_s))

    def request(self, time_s, base):
        if not self.available(time_s) or self.pending_base is not None or self.requested_s == time_s:
            return False
        self.requested_s, self.pending_base = time_s, base
        self.destination, self.state = base, "armed"
        self.deadline_s, self.reason = None, None
        self.commands.append(dict(action="send", runner_id=self.runner_id, base=base,
                                  time_s=time_s, executed_s=None, status="queued"))
        return True

    def can_override(self, runner_id):
        return self.pending_base is not None and runner_id == self.runner_id and not self.closed

    def commit(self, runner_id, base, time_s):
        if not self.can_override(runner_id) or self.pending_base != base:
            return False
        self.executed_s, self.destination, self.state = time_s, base, "committed"
        self.pending_base = None
        self.commands[-1].update(executed_s=time_s, status="executed")
        return True

    def cancel_pending(self, reason):
        if self.pending_base is not None:
            self.commands[-1].update(status="cancelled", reason=reason)
            self.pending_base = None

    def retreat(self, base, time_s, *, hold=False):
        if not self.available(time_s):
            return False
        if (self.commands and self.commands[-1]["action"] in ("retreat", "hold")
                and self.commands[-1]["time_s"] == time_s):
            return False
        self.cancel_pending("retreat" if not hold else "hold")
        self.requested_s = self.executed_s = time_s
        self.destination, self.state = base, "available" if hold else "returning"
        self.deadline_s, self.reason = None, None
        self.commands.append(dict(action="hold" if hold else "retreat", runner_id=self.runner_id,
                                  base=base, time_s=time_s, executed_s=time_s, status="executed"))
        return True

    def expire(self, reason):
        self.cancel_pending(reason)
        self.closed, self.reason = True, reason
        if self.state != "completed":
            self.state = "expired"

    def tick(self, time_s, routes, *, inning_ended=False, settled_s=None):
        if inning_ended:
            self.expire("inning ended")
            return
        route = routes.get(self.runner_id)
        if route is not None and self.pending_base is None:
            if self.state in ("committed", "returning") and time_s >= route.arrival_s:
                self.state = "completed"
        if settled_s is None:
            self.deadline_s = None
        elif self.deadline_s is None:
            self.deadline_s = settled_s + DECISION_WINDOW_S
        if self.deadline_s is not None and time_s >= self.deadline_s:
            self.expire("window closed")

    def remaining(self, time_s):
        if self.deadline_s is None:
            return 1.0
        return max(0.0, min(1.0, (self.deadline_s-time_s) / DECISION_WINDOW_S))
