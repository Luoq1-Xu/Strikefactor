import pygame
import pygame.gfxdraw
import pygame_gui
import json
from config import get_path, resource_path


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
    from pygame_gui.core import ObjectID
    buttons = {
        # View toggles group
        'strikezone': pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((6, 200), (120, 28)),
            text='ZONE', manager=manager,
            object_id=ObjectID(class_id='@broadcast_button')),
        'toggle_batter': pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((6, 230), (120, 28)),
            text='BATTER', manager=manager,
            object_id=ObjectID(class_id='@broadcast_button')),
        'visualise': pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((6, 260), (120, 28)),
            text='TRACK', manager=manager,
            object_id=ObjectID(class_id='@broadcast_button')),
        # Analysis group
        'pitch': pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((6, 296), (120, 28)),
            text='SCOUT', manager=manager,
            object_id=ObjectID(class_id='@broadcast_button')),
        'view_pitches': pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((6, 326), (120, 28)),
            text='PITCHVIZ', manager=manager,
            object_id=ObjectID(class_id='@broadcast_button')),
        'return_to_game': pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((6, 326), (120, 28)),
            text='RETURN', manager=manager,
            object_id=ObjectID(class_id='@broadcast_button')),
        # System group
        'toggle_ump_sound': pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((6, 398), (120, 28)),
            text='SOUND', manager=manager,
            object_id=ObjectID(class_id='@broadcast_button')),
        'main_menu': pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((6, 428), (120, 28)),
            text='MENU', manager=manager,
            object_id=ObjectID(class_id='@broadcast_button')),
    }
    return buttons