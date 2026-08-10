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


@pytest.fixture(scope="session", autouse=True)
def _pygame_session():
    """Initialise pygame once for the whole session and tear it down after."""
    pygame.init()
    pygame.display.set_mode((1280, 720))
    yield
    pygame.quit()
