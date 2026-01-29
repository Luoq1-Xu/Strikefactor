import pygame
import pygame.gfxdraw
import pygame_gui
import json
from config import SCREEN_WIDTH, SCREEN_HEIGHT, get_path, resource_path


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

def create_ui_manager(screen_size, theme_path=None):
    """Creates and configures the pygame_gui.UIManager."""
    theme_file = get_path(theme_path or "assets/theme.json")
    with open(theme_file, 'r') as f:
        theme_data = json.load(f)
    
    # Update font paths in the theme
    dynamic_font_path = resource_path(get_path('ui/font/8bitoperator_jve.ttf'))
    if "label" in theme_data and "font" in theme_data["label"]:
        theme_data["label"]["font"]["regular_path"] = dynamic_font_path
    if "button" in theme_data and "font" in theme_data["button"]:
        theme_data["button"]["font"]["regular_path"] = dynamic_font_path

    manager = pygame_gui.UIManager(screen_size, theme_path=theme_data)
    manager.preload_fonts([{'name': 'noto_sans', 'point_size': 18, 'style': 'regular'},
                           {'name': 'noto_sans', 'point_size': 18, 'style': 'bold'}])
    return manager

def create_game_buttons(manager):
    """Creates and returns a dictionary of in-game UI buttons."""
    buttons = {
        'strikezone': pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((0, 100), (200, 100)),
            text='STRIKEZONE', manager=manager),
        'pitch': pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((0, 0), (200, 100)),
            text='PITCH', manager=manager),
        'main_menu': pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((0, 620), (200, 100)),
            text='MAIN MENU', manager=manager),
        'toggle_ump_sound': pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((0, 200), (200, 100)),
            text='TOGGLEUMP', manager=manager),
        'view_pitches': pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((0, 300), (200, 100)),
            text='VIEW PITCHES', manager=manager),
        'return_to_game': pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((0, 300), (200, 100)),
            text='RETURN', manager=manager),
        'toggle_batter': pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((0, 400), (200, 100)),
            text='BATTER', manager=manager),
        'visualise': pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((0, 500), (200, 100)),
            text='TRACK', manager=manager)
    }
    return buttons