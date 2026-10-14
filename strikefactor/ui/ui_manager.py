import json

import pygame
import pygame_gui
from pygame_gui.core import ObjectID

from strikefactor.config import get_path
from strikefactor.ui.banner import OutcomeBanner


class UIManager:
    # ── Left sidebar layout ──────────────────────────────────────────────
    # Only Sandbox has a sidebar: the pitcher switch and the pitch toggles,
    # which are selections and have no key. Everything else that used to sit
    # in this column (ZONE, BATTER, REVIEW, SOUND, MENU, EXIT) is a key
    # binding, so gameplay itself shows no buttons at all.
    SIDEBAR_X = 6
    SIDEBAR_W = 120
    SIDEBAR_H = 28
    SIDEBAR_TOP = 188
    SIDEBAR_STEP = 28

    # Sandbox column slots: 0-4 pitchers, 6-8 pitch toggles.

    def __init__(self, screen, screen_size, theme_path=None):
        self.screen = screen
        self.manager = self._create_ui_manager(screen_size, theme_path)
        self.small_font = pygame.font.Font(get_path("ui/font/8bitoperator_jve.ttf"), 28)
        self.font = pygame.font.Font(get_path("ui/font/8bitoperator_jve.ttf"), 48)  # +20% from 40
        self.big_font = pygame.font.Font(get_path("ui/font/8bitoperator_jve.ttf"), 84)  # +20% from 70
        self.button_callbacks = {}
        self.key_binding_manager = None  # Will be set after initialization
        self._create_ui_elements()

    def set_key_binding_manager(self, key_binding_manager):
        """Set the key binding manager reference for UI visibility control."""
        self.key_binding_manager = key_binding_manager

    def register_button_callback(self, button_name, callback):
        """
        Registers a callback function for a button click event.

        :param button_name: The name of the button to register the callback for.
        :param callback: The function to call when the button is clicked.
        """
        if button_name in self.buttons:
            self.button_callbacks[button_name] = callback
        else:
            raise ValueError(f"Button '{button_name}' does not exist.")

    def _create_ui_manager(self, screen_size, theme_path=None):
        """Creates and configures the pygame_gui.UIManager."""
        theme_file = get_path(theme_path or 'assets/theme.json')
        with open(theme_file, 'r') as f:
            theme_data = json.load(f)
        
        # Update font paths in the theme
        dynamic_font_path = get_path('ui/font/8bitoperator_jve.ttf')
        for key, section in theme_data.items():
            if isinstance(section, dict) and "font" in section:
                if section["font"].get("name") == "8bitoperator_jve":
                    section["font"]["regular_path"] = dynamic_font_path

        manager = pygame_gui.UIManager(screen_size, theme_path=theme_data)
        manager.preload_fonts([{'name': 'noto_sans', 'point_size': 18, 'style': 'regular'},
                            {'name': 'noto_sans', 'point_size': 18, 'style': 'bold'}])
        return manager
    
    def _create_game_buttons(self, manager):
        """Creates and returns a dictionary of in-game UI buttons."""
        sandbox_x = self.SIDEBAR_X
        sandbox_w = self.SIDEBAR_W
        sandbox_h = self.SIDEBAR_H
        sandbox_top = self.SIDEBAR_TOP
        sandbox_step = self.SIDEBAR_STEP
        buttons = {
            # Pitcher selection buttons for main  menu
            'sale': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((400, 500), (190, 50)),
                text='Chris Sale', manager=manager,
                object_id=ObjectID(class_id='@pitcher_button')),
            'degrom': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((400, 600), (190, 50)),
                text='Jacob deGrom', manager=manager,
                object_id=ObjectID(class_id='@pitcher_button')),
            'sasaki': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((600, 500), (190, 50)),
                text='Roki Sasaki', manager=manager,
                object_id=ObjectID(class_id='@pitcher_button')),
            'yamamoto': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((600, 600), (190, 50)),
                text='Y. Yamamoto', manager=manager,
                object_id=ObjectID(class_id='@pitcher_button')),
            'mcclanahan': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((800, 500), (190, 50)),
                text='S. Mcclanahan', manager=manager,
                object_id=ObjectID(class_id='@pitcher_button')),

            # Random scenario button
            'random_scenario': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((500, 400), (280, 50)),
                text='Random Scenario', manager=manager),

            # GameDay mode button
            'gameday': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((800, 600), (190, 50)),
                text='GameDay Mode', manager=manager),

            # Button for summary screen
            'back_to_main_menu': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((540, 600), (200, 50)),
                text='MAIN MENU', manager=manager),
                
            # Button for inning end screen
            'continue_to_summary': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((540, 630), (200, 50)),
                text='CONTINUE', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button_primary')),

            # Settings entry point (lives on the mode-select screen)
            'settings': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((1130, 650), (140, 40)),
                text='Settings', manager=manager),

            # The settings, key-binding and GameDay screens have no widgets
            # here any more: each draws and handles its own buttons through
            # ui/widgets.py.

            # Mode selection buttons (for top-level menu)
            'arcade_mode': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((490, 450), (300, 70)),
                text='ARCADE', manager=manager),
            'sandbox_mode': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((490, 540), (300, 70)),
                text='SANDBOX', manager=manager),
            'back_to_mode_select': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((50, 650), (150, 50)),
                text='Back', manager=manager),

            # Sandbox menu - Pitcher selection buttons (matching arcade layout)
            'sandbox_menu_sale': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((400, 500), (190, 50)),
                text='Chris Sale', manager=manager,
                object_id=ObjectID(class_id='@pitcher_button')),
            'sandbox_menu_degrom': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((400, 600), (190, 50)),
                text='Jacob deGrom', manager=manager,
                object_id=ObjectID(class_id='@pitcher_button')),
            'sandbox_menu_sasaki': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((600, 500), (190, 50)),
                text='Roki Sasaki', manager=manager,
                object_id=ObjectID(class_id='@pitcher_button')),
            'sandbox_menu_yamamoto': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((600, 600), (190, 50)),
                text='Y. Yamamoto', manager=manager,
                object_id=ObjectID(class_id='@pitcher_button')),
            'sandbox_menu_mcclanahan': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((800, 500), (190, 50)),
                text='S. Mcclanahan', manager=manager,
                object_id=ObjectID(class_id='@pitcher_button')),

            # Sandbox gameplay - Pitcher switch buttons (left sidebar, broadcast style)
            'sandbox_pitcher_sale': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x, sandbox_top), (sandbox_w, sandbox_h)),
                text='SALE', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitcher_degrom': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x, sandbox_top + sandbox_step * 1), (sandbox_w, sandbox_h)),
                text='DEGROM', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitcher_sasaki': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x, sandbox_top + sandbox_step * 2), (sandbox_w, sandbox_h)),
                text='SASAKI', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitcher_yamamoto': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x, sandbox_top + sandbox_step * 3), (sandbox_w, sandbox_h)),
                text='YAMAMOTO', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitcher_mcclanahan': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x, sandbox_top + sandbox_step * 4), (sandbox_w, sandbox_h)),
                text='MCCLANAHAN', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),

            # Sandbox gameplay - Pitch toggle buttons (left sidebar, 2-column broadcast style)
            'sandbox_pitch_1': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x, sandbox_top + sandbox_step * 6), (58, sandbox_h)),
                text='', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitch_2': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x + 62, sandbox_top + sandbox_step * 6), (58, sandbox_h)),
                text='', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitch_3': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x, sandbox_top + sandbox_step * 7), (58, sandbox_h)),
                text='', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitch_4': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x + 62, sandbox_top + sandbox_step * 7), (58, sandbox_h)),
                text='', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitch_5': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x, sandbox_top + sandbox_step * 8), (58, sandbox_h)),
                text='', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitch_6': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((sandbox_x + 62, sandbox_top + sandbox_step * 8), (58, sandbox_h)),
                text='', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
        }
        return buttons

    def _create_ui_elements(self):
        """
        Initializes all UI elements for the game.
        """

        # pygame_gui elements
        self.buttons = self._create_game_buttons(self.manager)
        self.container = pygame_gui.core.UIContainer(
            relative_rect=pygame.Rect((0, 0), self.screen.get_size()),
            manager=self.manager
        )
        self.banner = OutcomeBanner(self.screen)

        # Hide all buttons initially
        for button in self.buttons.values():
            button.hide() 

    def process_events(self, event):
        """Processes events for the UI manager."""
        self.manager.process_events(event)
        if event.type == pygame_gui.UI_BUTTON_PRESSED:
            for key, button in self.buttons.items():
                if event.ui_element == button and key in self.button_callbacks:
                    # Call the registered callback for the button
                    self.button_callbacks[key]()
                    break

    # The banner is drawn by ui/banner.py. These forward to it so the callers
    # that speak to `game.ui_manager` keep working while the widgets go.
    def show_banner(self, text, typing_speed=0.1):
        """Shows the banner with the given text and a typing effect."""
        self.banner.show_banner(text, typing_speed)

    def schedule_banner(self, text, delay=450, typing_speed=0.1):
        """Schedule a banner to show after a delay (in ms), to sync with umpire call."""
        self.banner.schedule_banner(text, delay, typing_speed)

    @property
    def _pending_banner(self):
        return self.banner._pending_banner

    @_pending_banner.setter
    def _pending_banner(self, value):
        self.banner._pending_banner = value

    def update(self, time_delta):
        """Updates the UI manager and all UI elements."""
        self.banner.update(time_delta)
        self.manager.update(time_delta)

    def draw(self):
        """Draws the UI manager and all UI elements to the screen."""
        self.manager.draw_ui(self.screen)
        self.banner.draw()

    def update_sandbox_pitch_buttons(self, pitch_names: list, active_pitches: set = None):
        """Update sandbox pitch type buttons based on current pitcher's arsenal.

        Args:
            pitch_names: List of available pitch type names (e.g., ['FF', 'SL', 'CH'])
            active_pitches: Set of currently active/toggled-on pitch types
        """
        if active_pitches is None:
            active_pitches = set()

        pitch_buttons = ['sandbox_pitch_1', 'sandbox_pitch_2', 'sandbox_pitch_3',
                         'sandbox_pitch_4', 'sandbox_pitch_5', 'sandbox_pitch_6']

        # Hide all pitch buttons first
        for btn_key in pitch_buttons:
            self.buttons[btn_key].hide()

        # Show and configure buttons for available pitches
        if len(pitch_names) > len(pitch_buttons):
            print(f"Warning: pitcher has {len(pitch_names)} pitches but only "
                  f"{len(pitch_buttons)} Sandbox buttons; "
                  f"{pitch_names[len(pitch_buttons):]} will be unselectable.")
        for i, pitch_name in enumerate(pitch_names):
            if i < len(pitch_buttons):
                btn = self.buttons[pitch_buttons[i]]
                # Add indicator for active pitches
                if pitch_name in active_pitches:
                    btn.set_text(f"[{pitch_name}]")
                else:
                    btn.set_text(pitch_name)
                btn.show()

    def hide_banner(self):
        self.banner.hide_banner()

    def set_visibility_state(self, state):
        """Alias for set_button_visibility for clearer state-based visibility."""
        self.set_button_visibility(state)

    def set_button_visibility(self, state, force_show=False):
        """Show or hide buttons based on game state ('in_game', 'pitching', 'menu')."""

        # States that should always show their UI regardless of H-toggle
        ui_toggle_exempt = {
            'gameday_start', 'gameday_transition', 'gameday_simulation',
            'gameday_final', 'gameday_resume', 'gameday_history',
            'gameday_history_detail', 'main_menu', 'mode_select', 'settings',
            'key_bindings', 'summary', 'sandbox_menu',
        }

        # Check if UI should be hidden due to key binding toggle
        if (self.key_binding_manager and
            not self.key_binding_manager.is_ui_visible() and
            not force_show and
            state not in ui_toggle_exempt):
            # Hide all UI elements when UI visibility is toggled off (except banner)
            for button in self.buttons.values():
                button.hide()
            # Keep banner visible - it should be unaffected by UI toggle
            # self.banner.hide_banner()  # Commented out to keep banner visible
            return

        # Hide all buttons initially
        for button in self.buttons.values():
            button.hide()

        if state in ('in_game', 'pitching', 'visualise'):
            # Gameplay shows no buttons: every in-game action is a key
            # binding (see KeyBindingsPanel.ACTIONS).
            pass
        elif state == 'main_menu':
            self.buttons['sale'].show()
            self.buttons['degrom'].show()
            self.buttons['sasaki'].show()
            self.buttons['yamamoto'].show()
            self.buttons['mcclanahan'].show()
            self.buttons['random_scenario'].show()
            self.buttons['gameday'].show()
            self.buttons['back_to_mode_select'].show()
            self.banner.hide_banner()
        elif state == 'summary':
            self.buttons['back_to_main_menu'].show()
            self.banner.hide_banner()
        elif state == 'inning_end':
            # Continue button always shown so the player can advance.
            self.buttons['continue_to_summary'].show()
        elif state in ('settings', 'key_bindings'):
            # These screens own their buttons now; all that is left to do
            # here is what the branch always did besides showing them.
            self.banner.hide_banner()
        elif state == 'mode_select':
            # Top-level mode selection (Arcade/Sandbox)
            self.buttons['arcade_mode'].show()
            self.buttons['sandbox_mode'].show()
            self.buttons['settings'].show()
            self.banner.hide_banner()
        elif state == 'sandbox_menu':
            # Sandbox mode menu - pitcher selection (matching arcade aesthetic)
            self.buttons['sandbox_menu_sale'].show()
            self.buttons['sandbox_menu_degrom'].show()
            self.buttons['sandbox_menu_sasaki'].show()
            self.buttons['sandbox_menu_yamamoto'].show()
            self.buttons['sandbox_menu_mcclanahan'].show()
            self.buttons['back_to_mode_select'].show()
            self.banner.hide_banner()
        elif state == 'sandbox_gameplay':
            # Sandbox gameplay - broadcast-style left sidebar
            # Pitcher switch buttons
            self.buttons['sandbox_pitcher_sale'].show()
            self.buttons['sandbox_pitcher_degrom'].show()
            self.buttons['sandbox_pitcher_sasaki'].show()
            self.buttons['sandbox_pitcher_yamamoto'].show()
            self.buttons['sandbox_pitcher_mcclanahan'].show()
            # Pitch buttons shown via update_sandbox_pitch_buttons()
            self.banner.hide_banner()

    def draw_typing_effect(self, message, counter, speed, position, use_big_font=False):
        """Draws text with a typing effect at the given position."""
        font = self.big_font if use_big_font else self.font
        snip = font.render(message[0:counter//speed], True, 'white')
        self.screen.blit(snip, position)

    def draw_completed_message(self, message, position, use_big_font=False, use_small_font=False, color='white'):
        """Draws a completed message at the given position."""
        if use_big_font:
            font = self.big_font
        elif use_small_font:
            font = self.small_font
        else:
            font = self.font
        text = font.render(message, True, color)
        self.screen.blit(text, position)

    def set_ui_visibility(self, visible: bool, current_state: str = None):
        """Toggle visibility of all UI elements except the game screen."""
        if visible and current_state:
            # Show all UI elements based on current state
            self.set_button_visibility(current_state)
        elif not visible:
            # Hide all UI elements except banner
            for button in self.buttons.values():
                button.hide()
            # Keep banner visible - it should be unaffected by UI toggle
            # self.banner.hide_banner()  # Commented out to keep banner visible
