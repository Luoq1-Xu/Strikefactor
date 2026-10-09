"""The mouse position in the game's internal 1280x720 frame.

The game draws to a fixed internal surface and scales it into the window with
letterboxing (`Game.flip_display`), so the window's pixel coordinates are not
the coordinates anything is laid out in once the window is resized or
fullscreen. Events are translated on their way in (`Game._translate_mouse_event`),
but a hover highlight or a mouse-wheel scroll reads the pointer directly — and
`pygame.mouse.get_pos()` answers in window pixels, so those broke on any
window that was not exactly 1280x720.

`Game` installs its window-to-internal transform here at startup. Until it
does (tests, tools), the window *is* the internal frame and this is
`pygame.mouse.get_pos()`.
"""

import pygame

_to_internal = None


def install(window_to_internal):
    """Register the window-pixel -> internal-frame transform."""
    global _to_internal
    _to_internal = window_to_internal


def pos():
    """The pointer in internal-frame coordinates."""
    x, y = pygame.mouse.get_pos()
    if _to_internal is None:
        return (x, y)
    return _to_internal(x, y)
