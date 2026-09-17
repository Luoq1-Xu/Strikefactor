"""Session-local review history and bounded original-fielding capture cache."""

from dataclasses import replace


class ReviewStore:
    # Roughly 33 MiB of captured poses at the measured recorder frame size.
    # One clip is already bounded at 7,200 frames by FieldingRecorder. Always
    # retain the newest complete clip; metadata and swings survive eviction.
    MAX_FIELDING_FRAMES = 14_400
    MAX_FIELDING_CLIPS = 8

    def __init__(self):
        self.generation = 0
        self.clear()

    def clear(self):
        self.generation += 1
        self._sequence = 0
        self._records = {}
        self._sorted = None

    def allocate_id(self):
        self._sequence += 1
        return self.generation, self._sequence

    @property
    def records(self):
        """Every record in this session, oldest first.

        Memoised behind `_sorted`, which every writer below clears. The
        overlay asks for this five or six times per frame — the row list,
        its length, the adapter and the button strip each want it — and a
        session's record count only grows, so re-sorting per access made
        the chrome's cost scale with how long the game had been running.
        """
        if self._sorted is None:
            self._sorted = tuple(self._records[k] for k in sorted(self._records))
        return self._sorted

    def get(self, review_id):
        return self._records.get(review_id)

    def publish(self, record):
        if record.review_id[0] != self.generation:
            return  # a session already left cannot publish into a new one
        self._records[record.review_id] = record
        self._sorted = None
        clips = [r for r in self.records if r.fielding is not None]
        frames = sum(len(r.fielding.frames) for r in clips)
        while len(clips) > 1 and (len(clips) > self.MAX_FIELDING_CLIPS
                                 or frames > self.MAX_FIELDING_FRAMES):
            old = clips.pop(0)
            frames -= len(old.fielding.frames)
            self._records[old.review_id] = replace(
                old, fielding=None, fielding_unavailable="Clip no longer retained.")
            self._sorted = None

    def latest(self, view=None):
        return next((r for r in reversed(self.records)
                     if view is None or not r.unavailable(view)), None)

    def revise_outcome(self, review_id, outcome):
        record = self.get(review_id)
        if record is None:
            return
        swing = replace(record.swing, outcome=outcome) if record.swing is not None else None
        self._records[review_id] = replace(record, outcome=outcome, swing=swing)
        self._sorted = None
