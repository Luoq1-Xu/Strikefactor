import pygame
import pygame.gfxdraw


def create_pci_cursor():
    """Creates and sets the custom circular mouse cursor."""
    surf = pygame.Surface((100, 40), pygame.SRCALPHA)
    pygame.gfxdraw.aacircle(surf, 50, 20, 15, (255, 255, 255))
    pygame.gfxdraw.aacircle(surf, 50, 20, 30, (255, 255, 255))
    pygame.gfxdraw.aacircle(surf, 50, 20, 31, (255, 255, 255))
    pygame.gfxdraw.aacircle(surf, 50, 20, 32, (255, 255, 255))
    crosshair = pygame.cursors.Cursor((40, 15), surf)
    pygame.mouse.set_cursor(crosshair)
    return crosshair
