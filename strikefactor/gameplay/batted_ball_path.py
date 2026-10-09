"""A small, deterministic lateral-curve model for batted-ball flight.

Carry and hang time still belong to :mod:`ball_flight`.  This module only
answers where the ground projection of that flight is at a given fraction of
its path.  Keeping that question pure lets the renderer, fielders, and wall
collision all inspect the same curve without introducing a second clock or a
frame-by-frame aerodynamic integrator.

``curve_ft`` is the lateral displacement at the end of the nominal carry.  A
quadratic buildup approximates a bounded Magnus drift: the initial tangent is
the contact's spray bearing, then the bend develops smoothly through flight.
"""

import math
from dataclasses import dataclass

# Maximum end-of-flight lateral drift for a fully turned contact.  These are
# deliberately modest first-pass gameplay values, not claimed RPM fits.  A
# grounder gets almost none because its post-contact behaviour already belongs
# to ground_roll; liners and flies get enough movement to be readable.
MAX_CURVE_FT = {
    "GROUNDER": 2.0,
    "LINER": 12.0,
    "FLY": 18.0,
    "POP_UP": 8.0,
}

# Bat turn (actual attack minus nominal contact pose) that approaches a full
# bend. tanh keeps exceptional contacts bounded without a hard discontinuity.
TURN_SCALE_DEG = 12.0


def curve_distance_ft(shape, timing_turn_deg, handedness_sign=1.0):
    """Signed lateral drift in field feet for one contact.

    ``timing_turn_deg`` is pull-signed for either batter.  The handedness sign
    converts it once into the animation's field frame, just as spray direction
    does.  No randomness occurs here: one contact always describes one path.
    """
    maximum = MAX_CURVE_FT.get(shape, MAX_CURVE_FT["FLY"])
    turn = float(timing_turn_deg or 0.0)
    hand = 1.0 if handedness_sign >= 0.0 else -1.0
    return hand * maximum * math.tanh(turn / TURN_SCALE_DEG)


@dataclass(frozen=True)
class BattedBallPath:
    """Ground-plane flight in real field feet.

    ``bearing_rad`` follows the field convention used by hit_animation:
    zero points toward first-base foul territory and pi/2 toward centre.
    Positive curve is perpendicular in the increasing-angle direction.
    """

    bearing_rad: float
    carry_ft: float
    curve_ft: float = 0.0

    def point_ft(self, progress):
        """Return ``(x, y)`` at path fraction ``progress``."""
        s = max(0.0, min(1.0, float(progress)))
        cos_a = math.cos(self.bearing_rad)
        sin_a = math.sin(self.bearing_rad)
        forward = max(0.0, self.carry_ft) * s
        lateral = self.curve_ft * s * s
        return (forward * cos_a - lateral * sin_a,
                forward * sin_a + lateral * cos_a)

    @property
    def endpoint_ft(self):
        return self.point_ft(1.0)

    def tangent_ft(self, progress):
        """Unnormalised direction of travel at ``progress``."""
        s = max(0.0, min(1.0, float(progress)))
        cos_a = math.cos(self.bearing_rad)
        sin_a = math.sin(self.bearing_rad)
        forward = max(0.0, self.carry_ft)
        lateral = 2.0 * self.curve_ft * s
        return (forward * cos_a - lateral * sin_a,
                forward * sin_a + lateral * cos_a)

    def with_curve(self, curve_ft):
        return BattedBallPath(self.bearing_rad, self.carry_ft, curve_ft)
