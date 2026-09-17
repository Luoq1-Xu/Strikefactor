"""Three faithful presentations behind one review transport.

PitchViz uses captured screen points. Swing samples its resolved bat and
pitch. Fielding samples original presentation frames and never re-simulates.
"""

from bisect import bisect_right

import pygame

from strikefactor import outcomes
from strikefactor.config import STRIKEZONE_RECT, ZONE_CENTER_X, ZONE_CENTER_Y
from strikefactor.ui import gameday_theme as gdt
from strikefactor.ui.fielding_renderer import draw_frame
from strikefactor.ui.review_playback import Playback
from strikefactor.ui.swing_replay_overlay import SwingReplayOverlay


def fit_surface(screen, source, rect):
    fitted = source.get_rect().fit(rect)
    screen.blit(pygame.transform.smoothscale(source, fitted.size), fitted)


class PitchView:
    speeds = (0.25, 0.5, 1.0)
    speed_labels = ("0.25x", "0.5x", "1x")
    clock_label = "PITCH TIME · RELEASE ALIGNED · 1x = REAL TIME"
    step_ms = 10

    def __init__(self, game, records, focus):
        self.game, self.records, self.focus = game, records, focus
        self.end_ms = max((r.points[-1].time_ms for r in records if r.points), default=0.0)
        # Match PitchViz's endpoint pause; every pitch shares ONE cycle and
        # shorter flights hold instead of restarting ahead of longer pitches.
        # A full pitch lasts about 400 ms at 1x. Open in slow motion so its
        # movement is readable, keeping 1x available as literal real time.
        self.playback = Playback(self.end_ms + 400, speed=0.25, loop=True)
        self.events = sorted({(r.points[-1].time_ms, f"#{r.number} ENDPOINT")
                              for r in records if r.points})
        self._source = pygame.Surface((660, 500))
        self._times = {r.review_id: tuple(p.time_ms for p in r.points) for r in records}

    # The live zone re-centred into this 660x500 surface. Derived from
    # `STRIKEZONE_RECT` rather than restated, because that constant is the
    # single source for the zone the pitch points themselves were captured
    # against — a literal here would draw every pitch offset against a zone
    # left behind in the old place.
    _LOCAL_CENTER = (330, 250)
    _OFFSET = (_LOCAL_CENTER[0] - ZONE_CENTER_X, _LOCAL_CENTER[1] - ZONE_CENTER_Y)

    def draw(self, screen, rect):
        source = self._source
        source.fill(gdt.BG)
        dx, dy = self._OFFSET
        zone = pygame.Rect(STRIKEZONE_RECT[0] + dx, STRIKEZONE_RECT[1] + dy,
                           STRIKEZONE_RECT[2], STRIKEZONE_RECT[3])
        pygame.draw.rect(source, gdt.FG, zone, 1)
        # Home plate, in the same translated frame: `FieldRenderer.draw_homeplate`'s
        # five-point shape off the zone's left edge.
        px, py = zone.left, 440
        pygame.draw.polygon(source, gdt.FG,
                            [(px, py), (px + 130, py), (px + 130, py + 10),
                             (px + 65, py + 25), (px, py + 10)])
        t = self.playback.time_ms
        for record in self.records:
            n = bisect_right(self._times[record.review_id], t)
            points = record.points[:n]
            if not points:
                continue
            color = outcomes.COLORS.get(record.outcome, gdt.FG)
            dim = tuple(c // 2 for c in color)
            for point in points:
                pygame.draw.circle(source, dim, (round(point.x + dx), round(point.y + dy)),
                                   max(2, round(point.size / 2)))
            last = points[-1]
            pygame.draw.circle(source, color, (round(last.x + dx), round(last.y + dy)), 8, 2)
        fit_surface(screen, source, rect)


class SwingView:
    speeds = (1 / 12, 0.25, 1.0)
    speed_labels = ("1/12x", "0.25x", "1x")
    clock_label = "PITCH TIME · SWING WINDOW · 1x = REAL TIME"
    step_ms = 5

    def __init__(self, game, record):
        self.renderer = SwingReplayOverlay(game)
        self.renderer.trigger(record=record.swing)
        duration = self.renderer.review_duration_ms()
        self.playback = Playback(duration, speed=1 / 12)
        self.events = [(0.0, "START"), (duration, "CONTACT" if record.swing.contact else "CLIP END")]

    @property
    def camera(self):
        return self.renderer.camera

    def toggle_camera(self):
        self.renderer.toggle_camera()

    def draw(self, screen, rect):
        self.renderer.render_review(screen, rect, self.playback.time_ms)


class FieldingView:
    speeds = (0.25, 0.5, 1.0)
    speed_labels = ("0.25x", "0.5x", "1x")
    clock_label = "ORIGINAL ANIMATION TIME"
    step_ms = 100

    def __init__(self, game, record):
        self.record = record.fielding
        self.playback = Playback(self.record.duration_ms, speed=0.5)
        self.events = [(e.time_ms, e.label + (f" ({e.role})" if e.role else ""))
                       for e in self.record.events]
        self._source = pygame.Surface(self.record.size)
        self._fonts = None
        self._scaled = None
        self._scaled_key = None

    def draw(self, screen, rect):
        view = rect.copy()
        view.height -= 30
        fitted = self._source.get_rect().fit(view)
        # `Playback` pauses on seek and auto-pauses at the end of a clip, so a
        # frozen frame is the normal state of this view — and `sample` returns
        # the *same object* while paused. Re-filling, re-drawing nine fielders
        # and re-running a 1280x720 smoothscale (~1 ms) to produce a picture
        # identical to the last one is the whole cost of sitting on a frame.
        frame = self.record.sample(self.playback.time_ms)
        # Keyed on the frame's own time, not `id()`: `sample` interpolates into
        # a fresh object between stored frames, so an identity key would never
        # hit on exactly the paused-mid-interval case this exists for. The
        # picture is a pure function of the (immutable) record and that time.
        key = (frame.time_ms, fitted.size)
        if key != self._scaled_key:
            self._source.fill(gdt.BG)
            draw_frame(self._source, frame)
            self._scaled = pygame.transform.smoothscale(self._source, fitted.size)
            self._scaled_key = key
        screen.blit(self._scaled, fitted)
        if self._fonts is None:
            self._fonts = gdt.load_fonts()
        # `play_label` leads the row because it is the one thing here the
        # review chrome does not already say: the play's ordinal in the
        # session. Pitcher, pitch, speed and outcome are in `ReviewOverlay`'s
        # title bar, so this row stays the *batted ball's* measurements.
        stats = [self.record.play_label]
        for label, value, unit in [("EXIT", self.record.exit_velocity_mph, "MPH"),
                                   ("LAUNCH", self.record.launch_angle_deg, "DEG"),
                                   ("DISTANCE", self.record.hr_distance_ft, "FT")]:
            if value is not None:
                stats.append(f"{label} {value:.0f} {unit}")
        if self.record.fielder_role:
            stats.append(f"FIELDER {self.record.fielder_role}")
        gdt.blit_text(screen, "     ".join(stats), self._fonts['small'],
                      (rect.centerx, rect.bottom - 22), gdt.DIM, align='center')
