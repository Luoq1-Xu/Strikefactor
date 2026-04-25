import os
import sys

# Paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Display
SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720
FPS = 60

# ABS (Automated Ball-Strike) challenge system
ABS_ZONE = (630, 482.5, 130, 150)  # (center_x, center_y, width, height) in screen pixels
ABS_BALL_RADIUS = 11
ABS_PINK = (233, 30, 99)
ABS_GREEN = (75, 227, 148)
CHALLENGES_PER_SIDE = 2
CHALLENGE_WINDOW_MS = 1800
CHALLENGE_ANIMATION_MS = 2200

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