"""Pitch-linked review data. Capturing a review never commits gameplay effects."""

from dataclasses import dataclass

from strikefactor.gameplay.swing_record import from_simulation as swing_from_simulation


@dataclass(frozen=True)
class PitchPoint:
    time_ms: float
    x: float
    y: float
    size: float


@dataclass(frozen=True)
class ReviewRecord:
    review_id: tuple[int, int]  # session generation, pitch sequence (not a DB/list index)
    pitcher: str
    pitch_type: str
    speed_mph: float
    outcome: str
    handedness: str
    count: tuple[int, int, int]  # balls, strikes, outs BEFORE the pitch
    scope: str
    points: tuple[PitchPoint, ...]
    trajectory: object = None
    swing: object = None
    fielding: object = None
    fielding_unavailable: str = "No fielding play on this pitch."
    bases: tuple[str, ...] = ('white', 'white', 'white')

    @property
    def number(self):
        return self.review_id[1]

    def unavailable(self, view):
        if view == "swing" and self.swing is None:
            return "Pitch was taken — no swing."
        if view == "fielding":
            if self.fielding is None:
                return self.fielding_unavailable
            if not self.fielding.frames:
                return "No complete fielding recording."
        if view == "zone" and not self.points:
            return "No pitch trajectory was captured."
        return ""


def scope_for(game):
    gd = getattr(game, "gameday_manager", None)
    return f"INNING {gd.current_inning}" if gd is not None else "SESSION"


def from_simulation(sim):
    """Snapshot settled values, both before Continue and later at cleanup.

    The screen trail is preserved, not regenerated from a new pitch model.
    Its timestamps name the ball position actually sampled (the previous
    update's position), NOT the time the trail was appended. The exact pitch
    function is also retained on takes, for future linked-camera playback.
    """
    trail = sim.game.last_pitch_information
    times = sim._review_sample_times
    points = []
    for i, frame in enumerate(trail):
        t = times[i] if i < len(times) else sim._ball_sample_ms
        point = PitchPoint(t, frame[0], frame[1], frame[2])
        if points and points[-1].time_ms == t:
            points[-1] = point
        else:
            points.append(point)
        # After this marker the live ball is held for the call/banner. Contact
        # can stop the trace before plate arrival; never extend it through a bat.
        if frame[4]:
            break
    recorder = sim._fielding_recorder
    fielding = recorder.record if recorder is not None else None
    if recorder is not None and recorder.incomplete:
        reason = "Recording exceeded capture limit."
    elif sim.made_contact == "fouled" and sim.hit_animation is None:
        reason = "Foul animation was disabled."
    elif sim.made_contact == "swung_and_miss":
        reason = "No fielding play on a whiff."
    else:
        reason = "No fielding play on this pitch."
    swing = swing_from_simulation(sim)
    return ReviewRecord(
        sim.review_id, sim.pitchername, sim.pitchtype, sim.speed_mph,
        sim._get_outcome_display(), sim._review_handedness, sim._review_count,
        sim._review_scope, tuple(points), sim.trajectory, swing, fielding, reason,
        sim._review_bases,
    )
