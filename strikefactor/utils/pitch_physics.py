"""
Statcast-style 3D pitch trajectory physics with umpire-view projection.

Uses the same 9-parameter constant-acceleration kinematic model as MLB's
Statcast/PITCHf/x system:
    x(t) = x0 + vx0*t + 0.5*ax*t^2
    y(t) = y0 + vy0*t + 0.5*ay*t^2
    z(t) = z0 + vz0*t + 0.5*az*t^2

Coordinate system (Statcast convention):
    x: horizontal, positive to catcher's right
    y: toward pitcher, positive away from plate (release ~55ft, plate at 0)
    z: vertical, positive upward
"""

import math

# Gravity constant (ft/s^2)
GRAVITY = 32.174

# Realistic air drag deceleration (ft/s^2).
# A 95 mph fastball typically arrives at ~85 mph, losing ~10 mph over ~0.4s.
# decel ≈ (139.3 - 124.7) / 0.4 ≈ 30 ft/s²
DEFAULT_DRAG = 30.0


class PitchTrajectory:
    """9-parameter constant-acceleration pitch trajectory in 3D Statcast coordinates."""

    def __init__(self, x0, y0, z0, vx0, vy0, vz0, ax, ay, az):
        self.x0 = x0
        self.y0 = y0
        self.z0 = z0
        self.vx0 = vx0
        self.vy0 = vy0
        self.vz0 = vz0
        self.ax = ax
        self.ay = ay
        self.az = az
        self._travel_time = None

    def position_at(self, t):
        """Get 3D position at time t (seconds)."""
        x = self.x0 + self.vx0 * t + 0.5 * self.ax * t * t
        y = self.y0 + self.vy0 * t + 0.5 * self.ay * t * t
        z = self.z0 + self.vz0 * t + 0.5 * self.az * t * t
        return x, y, z

    @property
    def travel_time(self):
        """Time in seconds for ball to reach the plate (y=0)."""
        if self._travel_time is None:
            # Solve: y0 + vy0*t + 0.5*ay*t^2 = 0
            a = 0.5 * self.ay
            b = self.vy0
            c = self.y0

            if abs(a) < 1e-10:
                # Linear case (no y-acceleration / drag)
                if abs(b) < 1e-10:
                    self._travel_time = 0.0
                else:
                    self._travel_time = -c / b
            else:
                disc = b * b - 4 * a * c
                if disc < 0:
                    self._travel_time = -b / (2 * a)
                else:
                    sqrt_disc = math.sqrt(disc)
                    t1 = (-b + sqrt_disc) / (2 * a)
                    t2 = (-b - sqrt_disc) / (2 * a)
                    # Pick the positive root where ball moves toward plate
                    candidates = [t for t in (t1, t2) if t > 0]
                    self._travel_time = min(candidates) if candidates else 0.0

        return self._travel_time

    def time_at_depth(self, y_ft):
        """When the ball was `y_ft` in front of the plate, in seconds.

        `travel_time` is this at `y_ft = 0`; the general form is needed
        because the bat meets the ball a couple of feet out in front, so
        "when should the barrel have been there" is a question about a depth
        the pitch reaches before the plate. Unclamped on purpose — past the
        plate the model still describes a real ball heading for the mitt, and
        that extrapolation is exactly what a late swing is.

        Of the two roots the near one is on the way in; the far one is the
        ball being decelerated back out again by the drag term, which is not
        a thing that happens to a pitch.
        """
        a = 0.5 * self.ay
        b = self.vy0
        c = self.y0 - y_ft
        if abs(a) < 1e-10:
            return self.travel_time if abs(b) < 1e-10 else -c / b
        disc = b * b - 4 * a * c
        if disc < 0:
            return -b / (2 * a)
        root = math.sqrt(disc)
        return min(((-b + root) / (2 * a), (-b - root) / (2 * a)),
                   key=lambda t: abs(t - self.travel_time))

    @property
    def travel_time_ms(self):
        """Travel time in milliseconds."""
        return self.travel_time * 1000.0

    @classmethod
    def from_pitch_params(cls, release_pos, speed_mph, pfx_x_inches, pfx_z_inches,
                          target_x_ft, target_z_ft, drag_coefficient=None):
        """
        Create a trajectory from pitcher-friendly parameters.

        Args:
            release_pos: (x, y, z) in feet - 3D release position
            speed_mph: pitch speed in mph
            pfx_x_inches: horizontal movement due to spin (inches, + = catcher's right)
            pfx_z_inches: induced vertical break due to spin (inches, + = rise)
            target_x_ft: target horizontal position at plate (feet, + = catcher's right)
            target_z_ft: target vertical position at plate (feet)
            drag_coefficient: y-axis drag deceleration (ft/s^2, default ~30 for realistic air resistance)
        """
        # Realistic air drag: a baseball loses ~8-10 mph from release to plate.
        # For a 95 mph pitch arriving at ~85 mph over ~0.4s this is roughly 30 ft/s².
        if drag_coefficient is None:
            drag_coefficient = DEFAULT_DRAG
        x0, y0, z0 = release_pos

        # Convert speed to initial y-velocity (negative = toward plate)
        speed_fps = speed_mph * 5280.0 / 3600.0
        vy0 = -speed_fps

        # Y-axis: drag decelerates the ball (positive ay since vy0 is negative)
        ay = drag_coefficient

        # Compute travel time: y0 + vy0*T + 0.5*ay*T^2 = 0
        if abs(ay) < 1e-10:
            T = y0 / speed_fps
        else:
            a = 0.5 * ay
            b = vy0
            c = y0
            disc = b * b - 4 * a * c
            sqrt_disc = math.sqrt(max(0, disc))
            t1 = (-b + sqrt_disc) / (2 * a)
            t2 = (-b - sqrt_disc) / (2 * a)
            candidates = [t for t in (t1, t2) if t > 0]
            T = min(candidates) if candidates else y0 / speed_fps

        # Convert pfx (inches) to Magnus acceleration (ft/s^2)
        # pfx = 0.5 * a_magnus * T^2, so a_magnus = 2 * pfx / T^2
        # Convert inches to feet: pfx_ft = pfx_inches / 12
        T_sq = T * T
        ax_magnus = (2.0 * pfx_x_inches) / (12.0 * T_sq) if T_sq > 0 else 0.0
        az_magnus = (2.0 * pfx_z_inches) / (12.0 * T_sq) if T_sq > 0 else 0.0

        # Total accelerations
        ax = ax_magnus
        az = -GRAVITY + az_magnus  # gravity pulls down + Magnus

        # Compute initial velocities to hit target at time T
        # x(T) = x0 + vx0*T + 0.5*ax*T^2 = target_x
        # z(T) = z0 + vz0*T + 0.5*az*T^2 = target_z
        vx0 = (target_x_ft - x0 - 0.5 * ax * T_sq) / T if T > 0 else 0.0
        vz0 = (target_z_ft - z0 - 0.5 * az * T_sq) / T if T > 0 else 0.0

        return cls(x0, y0, z0, vx0, vy0, vz0, ax, ay, az)


class UmpireCamera:
    """Perspective projection from 3D Statcast coordinates to 2D screen (umpire view)."""

    def __init__(self, cam_dist=5.0, cam_height=2.5,
                 screen_center_x=630.0, screen_center_y=485.0,
                 scale_x=458.9, scale_y=375.0):
        """
        Args:
            cam_dist: camera distance behind home plate (feet)
            cam_height: camera height (feet), should be midpoint of strike zone
            screen_center_x: screen x-pixel at plate center
            screen_center_y: screen y-pixel at strike zone vertical midpoint
            scale_x: horizontal scale factor (pixels * feet at plate distance)
            scale_y: vertical scale factor
        """
        self.cam_dist = cam_dist
        self.cam_height = cam_height
        self.screen_center_x = screen_center_x
        self.screen_center_y = screen_center_y
        self.scale_x = scale_x
        self.scale_y = scale_y

    def project(self, x, y, z):
        """
        Project 3D world position to 2D screen coordinates.

        Returns:
            (screen_x, screen_y, depth) or None if behind camera
        """
        depth = y + self.cam_dist
        if depth <= 0.01:
            return None

        screen_x = self.screen_center_x - x * self.scale_x / depth
        screen_y = self.screen_center_y - (z - self.cam_height) * self.scale_y / depth
        return screen_x, screen_y, depth

    def project_radius(self, y, real_radius_ft=0.121):
        """
        Get projected ball radius in pixels.

        Args:
            y: depth in world coords (feet from plate)
            real_radius_ft: actual baseball radius (~1.45 inches = 0.121 ft)
        """
        depth = y + self.cam_dist
        if depth <= 0.01:
            return 0
        return real_radius_ft * self.scale_y / depth

    @property
    def ft_per_px_z(self):
        """Vertical feet per screen pixel at the plate.

        The one conversion that keeps a height stated in real feet and one
        stated in the engine's pixels agreeing. It lives on the camera because
        it is a fact about the projection, and because it was written out
        independently in two gameplay modules that have to produce the same
        number or the batted-ball model and the swing replay start describing
        different swings.
        """
        return self.cam_dist / self.scale_y

    def screen_to_world_at_plate(self, screen_x, screen_y):
        """Convert screen pixel coordinates to real-world feet at the plate (y=0)."""
        depth_at_plate = self.cam_dist  # y=0, so depth = cam_dist
        x_ft = (self.screen_center_x - screen_x) * depth_at_plate / self.scale_x
        z_ft = self.cam_height - (screen_y - self.screen_center_y) * depth_at_plate / self.scale_y
        return x_ft, z_ft


# Default camera calibrated to match existing strike zone:
#   Strike zone screen rect: top-left (565, 410), size 130x150
#   Center: (630, 485)
#   Real strike zone: 17" wide (1.417 ft), ~2 ft tall (1.5 to 3.5 ft)
#   Camera: 5 ft behind plate, at 2.5 ft height (zone midpoint)
DEFAULT_CAMERA = UmpireCamera(
    cam_dist=30.0,
    cam_height=2.5,
    screen_center_x=630.0,
    screen_center_y=485.0,
    scale_x=2753.4,
    scale_y=2250.0,
)
