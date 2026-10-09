"""Immutable presentation samples of a played ball; replay never simulates."""

from bisect import bisect_right
from dataclasses import dataclass, replace
from functools import cached_property


@dataclass(frozen=True, slots=True)
class FielderFrame:
    role: str
    pos: tuple
    glove: tuple


@dataclass(frozen=True, slots=True)
class FieldingFrame:
    time_ms: float
    ball: tuple
    shadow: tuple
    ball_visible: bool
    shadow_visible: bool
    fielders: tuple
    error: tuple | None = None  # x, y, opacity
    distance: tuple | None = None  # feet, x, y, opacity


@dataclass(frozen=True, slots=True)
class FieldingEvent:
    time_ms: float
    label: str
    role: str | None = None


@dataclass(frozen=True)
class FieldingRecord:
    frames: tuple
    events: tuple
    play_label: str
    outcome: str
    size: tuple = (1280, 720)
    exit_velocity_mph: float | None = None
    launch_angle_deg: float | None = None
    fielder_role: str | None = None
    time_scale: float = 1.0
    hr_distance_ft: float | None = None

    @cached_property
    def times(self):
        return tuple(f.time_ms for f in self.frames)

    @cached_property
    def event_times(self):
        return tuple(e.time_ms for e in self.events)

    @property
    def duration_ms(self):
        return self.times[-1] if self.frames else 0.0

    def sample(self, time_ms):
        if not self.frames:
            raise ValueError("A replay requires a completed recording")
        i = bisect_right(self.times, time_ms) - 1
        if i < 0:
            return self.frames[0]
        a = self.frames[i]
        if i == len(self.frames) - 1 or time_ms == a.time_ms:
            return a
        b = self.frames[i + 1]
        # Hold the last observed pose across a collision or possession change.
        # Guessing motion across that interval would draw through the glove.
        event_i = bisect_right(self.event_times, a.time_ms)
        if event_i < len(self.events) and self.events[event_i].time_ms <= b.time_ms:
            return a
        u = (time_ms - a.time_ms) / (b.time_ms - a.time_ms)

        def lerp(p, q):
            return tuple(x + (y - x) * u for x, y in zip(p, q))

        return replace(a, time_ms=time_ms, ball=lerp(a.ball, b.ball),
                       shadow=lerp(a.shadow, b.shadow),
                       fielders=tuple(FielderFrame(f.role, lerp(f.pos, g.pos), lerp(f.glove, g.glove))
                                      for f, g in zip(a.fielders, b.fielders)))


class FieldingRecorder:
    """Bounded capture, only attached to live animations by PitchSimulation.

    7,200 frames is two minutes at 60 FPS. Exceeding this budget discards the
    incomplete clip; time spent reading the result never extends capture.
    """

    MAX_FRAMES = 7200

    def __init__(self, animation, play_label, size=(1280, 720)):
        self.play_label = play_label
        self.size = size
        self.frames = []
        self.events = [FieldingEvent(0.0, "CONTACT")]
        self._seen = set()
        self.incomplete = False
        self.record = None
        self.capture(animation)

    def capture(self, animation):
        if self.incomplete or self.record is not None:
            return
        frame = animation.presentation_frame()
        if self.frames and frame.time_ms == self.frames[-1].time_ms:
            self.frames[-1] = frame
        elif len(self.frames) >= self.MAX_FRAMES:
            self.incomplete = True
            self.frames.clear()
            self.events.clear()
            return
        else:
            self.frames.append(frame)
        # These flags/schedules belong to the original play. Observe them,
        # never invoke transitions or roll any new decisions here.
        transitions = [
            ("wall", animation._wall_hit, "WALL IMPACT", None),
            ("error", animation._misplay_kind is not None, "MISPLAY", animation._misplay_role),
            ("secured", animation._secured, "BALL SECURED", animation.fielder_role),
            ("throw", animation._go_throw_start_ms is not None
             and frame.time_ms >= animation._go_throw_start_ms, "THROW RELEASE", animation.fielder_role),
            ("arrival", animation._go_throw_arrive_ms is not None
             and frame.time_ms >= animation._go_throw_arrive_ms, "THROW ARRIVAL", animation._cover_role),
            ("ground", animation._ball_pos is not None
             and (animation._wall_drop is None
                  or frame.time_ms >= animation.duration_ms + animation._wall_drop[1]), "BOUNCE", None),
        ]
        for n in range(animation._bounces_completed):
            transitions.append((f"bounce{n}", True, "BOUNCE", None))
        for key, happened, label, role in transitions:
            if happened and key not in self._seen:
                self._seen.add(key)
                # First observed frame is exactly seekable, even if the source
                # frame straddled the simulation's scheduled transition time.
                self.events.append(FieldingEvent(frame.time_ms, label, role))
        if animation.finished:
            self.events.append(FieldingEvent(frame.time_ms, "END"))
            self.record = FieldingRecord(
                tuple(self.frames), tuple(self.events), self.play_label,
                animation.classified_outcome or animation.outcome, self.size,
                animation.exit_velocity_mph, animation.launch_deg,
                animation.fielder_role, animation.time_scale, animation.hr_distance_ft)
            self.frames.clear()
