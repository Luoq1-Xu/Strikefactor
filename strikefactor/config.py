import os
import sys

# Paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Display
SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720

# ABS (Automated Ball-Strike) challenge system
ABS_ZONE = (630, 482.5, 130, 150)  # (center_x, center_y, width, height) in screen pixels
ABS_BALL_RADIUS = 11
ABS_PINK = (233, 30, 99)
ABS_GREEN = (75, 227, 148)
CHALLENGES_PER_SIDE = 2
CHALLENGE_WINDOW_MS = 1800

# Gameplay strike zone (screen pixels) — single source for the zone geometry
# shared by the pitcher AI and the batter profile. NOTE: ABS_ZONE above uses a
# 482.5 center_y for ABS truth calibration and is intentionally distinct from
# this gameplay zone (center_y 485).
STRIKEZONE_RECT = (565, 410, 130, 150)  # (left, top, width, height)
ZONE_LEFT = 565
ZONE_RIGHT = 695
ZONE_TOP = 410
ZONE_BOTTOM = 560
ZONE_CENTER_X = 630
ZONE_CENTER_Y = 485

# Canonical pitcher roster (internal keys). Single source of truth for the
# pitchers available across GameDay / Sandbox / random scenarios.
ALL_PITCHERS = ['sale', 'degrom', 'yamamoto', 'sasaki', 'mcclanahan']

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