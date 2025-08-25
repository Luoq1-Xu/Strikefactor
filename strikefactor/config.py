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

# Physics constants
BALL_MIN_SIZE = 3
BALL_MAX_SIZE = 11
MAX_DISTANCE = 4600
PHYSICS_HZ = 240  # High-frequency physics simulation for better contact detection

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