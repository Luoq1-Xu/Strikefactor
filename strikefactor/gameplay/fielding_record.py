"""Immutable presentation samples of a played ball; replay never simulates."""

from bisect import bisect_right
from dataclasses import dataclass, replace
from functools import cached_property

from strikefactor.gameplay.running_play import RunningEvent


@dataclass(frozen=True, slots=True)
class FielderFrame:
    role: str
    pos: tuple
    glove: tuple


@dataclass(frozen=True, slots=True)
class RunnerFrame:
    pos: tuple  # contact anchor at the runner's feet
    reached_first: bool
    runner_id: str = "B"
    base: int = 0
    target_base: int = 1
    state: str = "running"


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
    runner: RunnerFrame | None = None
    first_base_call: tuple | None = None  # SAFE/OUT, runner_s - defense_s
    runners: tuple = ()
    base_call: tuple | None = None  # SAFE/OUT, target base, arrival/tag margin
    send_control: tuple | None = None  # control snapshot; renderer also accepts legacy five-field frames


@dataclass(frozen=True, slots=True)
class FieldingEvent:
    time_ms: float
    label: str
    role: str | None = None
    runner_id: str | None = None
    base: int | None = None


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
    play_margin_s: float | None = None
    running_result: object | None = None

    @cached_property
    def times(self):
        return tuple(f.time_ms for f in self.frames)

    @cached_property
    def event_times(self):
        return tuple(e.time_ms for e in self.events)

    @cached_property
    def possession_event_times(self):
        return tuple(e.time_ms for e in self.events if e.label in {
            "WALL IMPACT", "MISPLAY", "BALL SECURED", "THROW RELEASE", "THROW ARRIVAL", "BOUNCE",
        })

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
        # Hold possession across collisions. Runner motion is independent
        # and must not freeze whenever the ball is released or received.
        event_i = bisect_right(self.possession_event_times, a.time_ms)
        hold_ball = (event_i < len(self.possession_event_times)
                     and self.possession_event_times[event_i] <= b.time_ms)
        u = (time_ms - a.time_ms) / (b.time_ms - a.time_ms)

        def lerp(p, q):
            return tuple(x + (y - x) * u for x, y in zip(p, q))

        runner = (replace(a.runner, pos=lerp(a.runner.pos, b.runner.pos))
                  if a.runner is not None and b.runner is not None else a.runner)
        runners = tuple(replace(r, pos=lerp(r.pos, s.pos)) for r, s in zip(a.runners, b.runners))
        if hold_ball:
            return replace(a, time_ms=time_ms, runner=runner, runners=runners)
        return replace(a, time_ms=time_ms, ball=lerp(a.ball, b.ball), runner=runner, runners=runners,
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
        # Live update splits at exact first-base events. Keeping these poses
        # makes two arrivals within one source frame separately seekable.
        frame = animation.presentation_frame()
        boundaries = list(animation._presentation_boundaries)
        if animation.runner is not None and self.frames and "runner" not in self._seen:
            arrival_ms = animation._anim_ms(animation.runner_first_s)
            before = self.frames[-1]
            if (before.time_ms < arrival_ms < frame.time_ms and frame.runner.reached_first
                    and not any(b.time_ms == arrival_ms for b in boundaries)):
                # Before a first-base play is scheduled, touching first must
                # not add an integration step to airborne ball physics. Copy
                # a presentation sample instead, retaining the old ball pose
                # across any collision in the source interval.
                u = (arrival_ms - before.time_ms) / (frame.time_ms - before.time_ms)

                def lerp(p, q):
                    return tuple(a + (b - a) * u for a, b in zip(p, q))

                collision = ((animation._secured and "secured" not in self._seen)
                             or (animation._wall_hit and "wall" not in self._seen)
                             or (animation._misplay_kind is not None and "error" not in self._seen))
                boundaries.append(replace(
                    before, time_ms=arrival_ms, runner=animation.runner_frame(arrival_ms),
                    ball=before.ball if collision else lerp(before.ball, frame.ball),
                    shadow=before.shadow if collision else lerp(before.shadow, frame.shadow),
                    fielders=tuple(FielderFrame(f.role, lerp(f.pos, g.pos), lerp(f.glove, g.glove))
                                   for f, g in zip(before.fielders, frame.fielders))))
        for boundary in sorted(boundaries, key=lambda sample: sample.time_ms):
            if not self._append_frame(boundary):
                return
        if not self._append_frame(frame):
            return
        # These flags/schedules belong to the original play. Observe them,
        # never invoke transitions or roll any new decisions here.
        transitions = [
            ("wall", animation._wall_hit, "WALL IMPACT", None, None),
            ("error", animation._misplay_kind is not None, "MISPLAY", animation._misplay_role, None),
            ("secured", animation._secured, "BALL SECURED", animation.fielder_role, animation._secured_at_ms),
            ("throw", animation._go_throw_start_ms is not None
             and frame.time_ms >= animation._go_throw_start_ms, "THROW RELEASE", animation.fielder_role,
             animation._go_throw_start_ms),
            ("arrival", animation._go_throw_arrive_ms is not None
             and frame.time_ms >= animation._go_throw_arrive_ms, "THROW ARRIVAL", animation._cover_role,
             animation._go_throw_arrive_ms),
            ("ground", animation._ball_pos is not None and not animation._post_fielding
             and (animation._wall_drop is None
                  or frame.time_ms >= animation.duration_ms + animation._wall_drop[1]), "BOUNCE", None, None),
        ]
        if animation.runner is not None:
            transitions.append(("runner", frame.runner.reached_first, "RUNNER AT FIRST", None,
                                animation._anim_ms(animation.runner_first_s)))
        if animation.play_timing is not None:
            ready_ms = animation._anim_ms(animation.play_timing.defense_s)
            transitions.append(("base", frame.time_ms >= ready_ms, "DEFENSE AT FIRST",
                                animation._cover_role or animation.fielder_role, ready_ms))
            transitions.append(("call", frame.first_base_call is not None,
                                "OUT" if animation.classified_outcome == "GROUNDOUT" else "SAFE", None,
                                animation._anim_ms(animation._first_base_call_s)))
        for n in range(animation._bounces_completed):
            transitions.append((f"bounce{n}", True, "BOUNCE", None, None))
        for key, happened, label, role, scheduled_ms in transitions:
            if happened and key not in self._seen:
                self._seen.add(key)
                event_ms = frame.time_ms if scheduled_ms is None else max(self.frames[0].time_ms, scheduled_ms)
                self.events.append(FieldingEvent(event_ms, label, role))
        self.events.sort(key=lambda event: event.time_ms)
        # Running and relay events are exact instants from the original play.
        # Observe only events which have happened, including a skipped end.
        observed_s = frame.time_ms / (1000*animation.time_scale)
        if animation._inning_end_s is not None:
            observed_s = min(observed_s, animation._inning_end_s)
        running = list(animation._running_events)
        for rid, route in animation._circuits.items():
            running.extend(RunningEvent(
                t, "BASE TOUCHED", rid, base) for base, t in route.touches(observed_s)
                if rid != "B" or base != 1)
        for event in running:
            key = (event.label, event.runner_id, event.base, event.role, event.time_s)
            if event.time_s <= observed_s and key not in self._seen:
                self._seen.add(key)
                target = "HOME" if event.base == 4 else f"{event.base}B"
                label = f"{event.label} {target}" if event.base is not None else event.label
                self.events.append(FieldingEvent(animation._anim_ms(event.time_s), label,
                                                 event.role, event.runner_id, event.base))
        self.events.sort(key=lambda event: event.time_ms)
        if animation.finished:
            self.events.append(FieldingEvent(frame.time_ms, "END"))
            self.record = FieldingRecord(
                tuple(self.frames), tuple(self.events), self.play_label,
                animation.classified_outcome or animation.outcome, self.size,
                animation.exit_velocity_mph, animation.launch_deg,
                animation.fielder_role, animation.time_scale, animation.hr_distance_ft,
                animation.play_timing.margin_s if animation.play_timing is not None else None,
                animation.running_result)
            self.frames.clear()

    def _append_frame(self, frame):
        if self.frames and frame.time_ms < self.frames[-1].time_ms:
            return True
        if self.frames and frame.time_ms == self.frames[-1].time_ms:
            self.frames[-1] = frame
        elif len(self.frames) >= self.MAX_FRAMES:
            self.incomplete = True
            self.frames.clear()
            self.events.clear()
            return False
        else:
            self.frames.append(frame)
        return True
