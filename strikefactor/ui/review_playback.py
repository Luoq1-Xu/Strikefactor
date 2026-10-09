"""Local transport. Times are source milliseconds, never display frame counts."""

from dataclasses import dataclass


@dataclass
class Playback:
    duration_ms: float
    speed: float = 1.0
    time_ms: float = 0.0
    paused: bool = False
    loop: bool = False

    def update(self, dt_ms):
        if self.paused or self.duration_ms <= 0:
            return
        end = self.time_ms + max(0.0, dt_ms) * self.speed
        if self.loop:
            self.time_ms = end % self.duration_ms
        else:
            self.time_ms = min(self.duration_ms, end)
            if self.time_ms == self.duration_ms:
                self.paused = True

    def seek(self, time_ms):
        self.time_ms = max(0.0, min(self.duration_ms, time_ms))
        self.paused = True

    def restart(self):
        self.time_ms = 0.0
        self.paused = False

    def toggle(self):
        if self.time_ms >= self.duration_ms:
            self.restart()
        else:
            self.paused = not self.paused

    def step_event(self, events, direction):
        choices = [t for t, _ in events if (t - self.time_ms) * direction > 0.01]
        self.seek((min(choices) if direction > 0 else max(choices)) if choices
                  else (self.duration_ms if direction > 0 else 0.0))
