"""Shared test setup.

Forces SDL onto its dummy video/audio drivers *before* pygame is imported by
any test or module under test, so the suite needs no display and no sound
device. This must stay at import time of conftest — pygame caches the driver
choice on first init.
"""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402  (must follow the env setup above)
import pytest

from tools import sim  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _pygame_session():
    """Initialise pygame once for the whole session and tear it down after."""
    sim.init_headless()
    yield
    pygame.quit()


# ---- The batter the model actually faces ----------------------------------
# Re-exported from `tools.sim`, which owns them, so that `conftest.<name>` goes
# on working for the files that already import it that way. They moved out of
# here because the calibration harness needs the same batter: a band asserted
# in a test and a number quoted in docs/defense-strength.md can only mean the
# same thing if one definition produced both. CLAUDE.md records that drifting
# copies of exactly these numbers have caused four separate miscalibrations.
QUALITY_QUANTILES = sim.QUALITY_QUANTILES
QUALITY_BY_SHAPE = sim.QUALITY_BY_SHAPE
LAUNCH_ANGLE_QUANTILES = sim.LAUNCH_ANGLE_QUANTILES
SPRAY_MEAN_DEG = sim.SPRAY_MEAN_DEG
SPRAY_SD_DEG = sim.SPRAY_SD_DEG
BATTED_BALL_MIX = sim.BATTED_BALL_MIX

realistic_quality = sim.realistic_quality
realistic_spray = sim.realistic_spray
realistic_batted_ball = sim.realistic_batted_ball
realistic_launch_angle = sim.realistic_launch_angle
realistic_contact = sim.realistic_contact


# ---- Letting a ball reach the fence ---------------------------------------


def uncaught(anim):
    """Hold the defense off a ball in flight; returns the animation.

    For tests about how something is *drawn* — the carom off the wall, the
    fielding clip's event list — rather than about who caught it.

    A ball that reaches the fence gets there below its 12 ft rim by definition
    (anything higher cleared it and is a home run), so it arrives at glove
    height and an outfielder standing there catches it, which is the whole
    point of the wall-ball fix in `_update_hit`. Roughly one wall ball in six
    still gets past everybody, but *which* one depends on where the defense
    happened to be routed — and a rendering test that had to be threaded
    through the defense would be pinning the calibration instead of the
    picture. So the defense is held off explicitly, and the frames these tests
    inspect are exactly the frames the balls that do beat it produce.
    """
    anim._check_in_flight_intercept = lambda: False
    return anim
