import os
import sys

# Paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
AI_DIR = "AI_2"

# Display
SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720
FPS = 60

# Game mechanics
BAT_RADIUS = 40
STRIKEZONE_RECT = ((565, 410), (130, 150))

# Physics constants (legacy - kept for backward compat with ball renderer)
BALL_MIN_SIZE = 3
BALL_MAX_SIZE = 11
MAX_DISTANCE = 4600
PHYSICS_Z_DISTANCE = 4300  # Total z-distance the ball travels

# Statcast 3D physics constants
MOUND_DISTANCE_FT = 60.5
BALL_RADIUS_FT = 0.121  # ~1.45 inches

# Umpire camera projection (calibrated to match strike zone screen rect)
CAM_DIST_FT = 30.0      # Camera distance behind plate
CAM_HEIGHT_FT = 2.5     # Camera height (strike zone midpoint)
CAM_SCREEN_CENTER_X = 630.0  # Screen x at plate center
CAM_SCREEN_CENTER_Y = 485.0  # Screen y at zone vertical midpoint
CAM_SCALE_X = 2753.4    # Horizontal projection scale
CAM_SCALE_Y = 2250.0    # Vertical projection scale


def calculate_z_delta(engine_fps: int, traveltime: float) -> float:
    """Calculate per-frame z-axis change based on engine FPS.

    Args:
        engine_fps: The physics engine FPS (60 or 120)
        traveltime: Pitch travel time in milliseconds

    Returns:
        Z-axis change per frame
    """
    return (PHYSICS_Z_DISTANCE * 1000) / (engine_fps * traveltime)

# Player positions
RIGHT_BATTER_POS = (330, 190)
LEFT_BATTER_POS = (735, 190)

# File paths
def get_path(orig_path):
    return os.path.join(SCRIPT_DIR, orig_path)

#Setup for Conversion into EXE
def resource_path(relative_path):
    try:
    # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)