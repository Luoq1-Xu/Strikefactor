"""
BatterProfile: Tracks batter tendencies within a game session.

Records swing decisions by zone quadrant, pitch type, and count to help
the AI exploit patterns in the player's behavior.
"""

import config


class BatterProfile:
    """Tracks batter swing tendencies during a game session."""

    # Strike zone geometry — single source in config.py.
    ZONE_CENTER_X = config.ZONE_CENTER_X
    ZONE_CENTER_Y = config.ZONE_CENTER_Y
    ZONE_LEFT = config.ZONE_LEFT
    ZONE_RIGHT = config.ZONE_RIGHT
    ZONE_TOP = config.ZONE_TOP
    ZONE_BOTTOM = config.ZONE_BOTTOM

    def __init__(self):
        self.reset()

    def reset(self):
        """Reset all tracked tendencies."""
        # Swing counts by zone quadrant: {quadrant: [swings, pitches_seen]}
        # Quadrants: 'up_in', 'up_away', 'down_in', 'down_away'
        self.zone_swings = {
            'up_in': [0, 0],
            'up_away': [0, 0],
            'down_in': [0, 0],
            'down_away': [0, 0],
        }

        # Swing counts by pitch type: {pitch_type: [swings, pitches_seen]}
        self.pitch_type_swings = {}

        # Chase tracking: swings at pitches outside the zone
        self.chase_swings = 0
        self.chase_pitches = 0

        # First-pitch tracking
        self.first_pitch_swings = 0
        self.first_pitch_count = 0

        # Swing rate by count state: {count_state: [swings, pitches_seen]}
        self.count_swings = {
            'first_pitch': [0, 0],
            'ahead': [0, 0],
            'behind': [0, 0],
            'even': [0, 0],
            'full': [0, 0],
        }

    def _get_quadrant(self, ball_x, ball_y, handedness='R'):
        """Determine zone quadrant from ball position and batter handedness.

        'in' = toward the batter, 'away' = away from the batter.
        For a RHB, inside is left side of zone (low x). For LHB, inside is right side (high x).
        """
        is_up = ball_y < self.ZONE_CENTER_Y
        if handedness == 'R':
            is_in = ball_x < self.ZONE_CENTER_X
        else:
            is_in = ball_x >= self.ZONE_CENTER_X

        if is_up and is_in:
            return 'up_in'
        elif is_up and not is_in:
            return 'up_away'
        elif not is_up and is_in:
            return 'down_in'
        else:
            return 'down_away'

    def _is_in_zone(self, ball_x, ball_y):
        """Check if ball position is within the strike zone."""
        return (self.ZONE_LEFT <= ball_x <= self.ZONE_RIGHT and
                self.ZONE_TOP <= ball_y <= self.ZONE_BOTTOM)

    def record_pitch(self, ball_x, ball_y, pitch_type, did_swing, count_state,
                     is_first_pitch, handedness='R'):
        """Record a pitch for tendency tracking.

        Args:
            ball_x: Final x position of the ball (screen pixels)
            ball_y: Final y position of the ball (screen pixels)
            pitch_type: Pitch type string (e.g., 'FF', 'SL')
            did_swing: Whether the batter swung
            count_state: Current count state ('first_pitch', 'ahead', etc.)
            is_first_pitch: Whether this is the first pitch of the at-bat
            handedness: Batter handedness ('L' or 'R')
        """
        # Zone quadrant tracking
        quadrant = self._get_quadrant(ball_x, ball_y, handedness)
        self.zone_swings[quadrant][1] += 1
        if did_swing:
            self.zone_swings[quadrant][0] += 1

        # Pitch type tracking
        if pitch_type not in self.pitch_type_swings:
            self.pitch_type_swings[pitch_type] = [0, 0]
        self.pitch_type_swings[pitch_type][1] += 1
        if did_swing:
            self.pitch_type_swings[pitch_type][0] += 1

        # Chase tracking (swings at pitches outside the zone)
        if not self._is_in_zone(ball_x, ball_y):
            self.chase_pitches += 1
            if did_swing:
                self.chase_swings += 1

        # First pitch tracking
        if is_first_pitch:
            self.first_pitch_count += 1
            if did_swing:
                self.first_pitch_swings += 1

        # Count state tracking
        if count_state in self.count_swings:
            self.count_swings[count_state][1] += 1
            if did_swing:
                self.count_swings[count_state][0] += 1

    def get_swing_rate(self, pitch_type):
        """Get swing rate for a specific pitch type (0.0-1.0)."""
        if pitch_type not in self.pitch_type_swings:
            return 0.5  # No data, assume neutral
        swings, seen = self.pitch_type_swings[pitch_type]
        if seen < 2:
            return 0.5  # Not enough data
        return swings / seen

    def get_chase_rate(self):
        """Get chase rate (swing rate on pitches outside the zone)."""
        if self.chase_pitches < 3:
            return 0.3  # Default assumption, not enough data
        return self.chase_swings / self.chase_pitches

    def get_first_pitch_swing_rate(self):
        """Get first pitch swing rate."""
        if self.first_pitch_count < 2:
            return 0.3
        return self.first_pitch_swings / self.first_pitch_count

    def to_dict(self) -> dict:
        """Serialize the profile's aggregates to a JSON-safe dict.

        Used by PitchDatabaseService.save_batter_profile so tendencies
        survive across launches, segregated by (game_mode, difficulty).
        """
        return {
            "version": 1,
            "zone_swings": self.zone_swings,
            "pitch_type_swings": self.pitch_type_swings,
            "chase_swings": self.chase_swings,
            "chase_pitches": self.chase_pitches,
            "first_pitch_swings": self.first_pitch_swings,
            "first_pitch_count": self.first_pitch_count,
            "count_swings": self.count_swings,
        }

    def from_dict(self, data: dict):
        """Restore aggregates from a previously to_dict()'d payload.

        Resets first so missing keys behave like a fresh profile, then
        copies in whatever was persisted. Unknown keys are ignored.
        """
        self.reset()
        if not isinstance(data, dict):
            return
        # zone_swings / count_swings are dicts of [int, int]; coerce list
        # values back to lists so increments work.
        zs = data.get("zone_swings")
        if isinstance(zs, dict):
            for k, v in zs.items():
                if k in self.zone_swings and isinstance(v, (list, tuple)) and len(v) == 2:
                    self.zone_swings[k] = [int(v[0]), int(v[1])]
        pts = data.get("pitch_type_swings")
        if isinstance(pts, dict):
            for k, v in pts.items():
                if isinstance(v, (list, tuple)) and len(v) == 2:
                    self.pitch_type_swings[k] = [int(v[0]), int(v[1])]
        cs = data.get("count_swings")
        if isinstance(cs, dict):
            for k, v in cs.items():
                if k in self.count_swings and isinstance(v, (list, tuple)) and len(v) == 2:
                    self.count_swings[k] = [int(v[0]), int(v[1])]
        self.chase_swings = int(data.get("chase_swings", 0))
        self.chase_pitches = int(data.get("chase_pitches", 0))
        self.first_pitch_swings = int(data.get("first_pitch_swings", 0))
        self.first_pitch_count = int(data.get("first_pitch_count", 0))

    def get_pitch_bonuses(self, available_pitches, count_state):
        """Calculate Q-value bonuses for each pitch type based on batter tendencies.

        Returns a dict of {pitch_type: bonus} to add to Q-values during action selection.
        Positive bonus = AI should favor this pitch, negative = avoid it.
        """
        bonuses = {}
        chase_rate = self.get_chase_rate()
        total_pitches_seen = sum(v[1] for v in self.pitch_type_swings.values())

        for pitch in available_pitches:
            bonus = 0.0
            swing_rate = self.get_swing_rate(pitch)

            # If batter chases a lot (>45%), reward chase pitches (breaking balls)
            if chase_rate > 0.45 and pitch in ('SL', 'CB', 'SLD', 'FS', 'FO', 'CH'):
                bonus += (chase_rate - 0.35) * 1.5  # Up to ~0.3 bonus

            # If batter rarely swings at this pitch type, it's less effective as a chase
            # but can be used to steal strikes
            if swing_rate < 0.25 and total_pitches_seen >= 8:
                # Batter is patient against this pitch — use it in the zone for called strikes
                if count_state in ('behind', 'even'):
                    bonus += 0.15

            # If batter always swings at this pitch (>70%), throw it outside the zone
            if swing_rate > 0.70 and total_pitches_seen >= 8:
                if count_state in ('ahead', 'even'):
                    bonus += 0.25  # Great chase pitch candidate

            # First-pitch aggression exploitation
            if count_state == 'first_pitch':
                fp_rate = self.get_first_pitch_swing_rate()
                if fp_rate > 0.60 and pitch in ('SL', 'CB', 'SLD', 'FS', 'FO'):
                    bonus += 0.2  # Aggressive batter → start with breaking ball
                elif fp_rate < 0.25 and pitch in ('FF', 'SI'):
                    bonus += 0.15  # Passive batter → steal first-pitch strike

            bonuses[pitch] = bonus

        return bonuses
