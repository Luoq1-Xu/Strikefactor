import pygame
import pygame_gui
import json
from helpers import StatSwing
from config import get_path, resource_path


class UIManager:
    def __init__(self, screen, screen_size, theme_path=None):
        self.screen = screen
        self.manager = self._create_ui_manager(screen_size, theme_path)
        self.font = pygame.font.Font(resource_path(get_path("ui/font/8bitoperator_jve.ttf")), 40)
        self.big_font = pygame.font.Font(resource_path(get_path("ui/font/8bitoperator_jve.ttf")), 70)
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
        dynamic_font_path = resource_path(get_path('ui/font/8bitoperator_jve.ttf'))
        if "label" in theme_data and "font" in theme_data["label"]:
            theme_data["label"]["font"]["regular_path"] = dynamic_font_path
        if "button" in theme_data and "font" in theme_data["button"]:
            theme_data["button"]["font"]["regular_path"] = dynamic_font_path

        manager = pygame_gui.UIManager(screen_size, theme_path=theme_data)
        manager.preload_fonts([{'name': 'noto_sans', 'point_size': 18, 'style': 'regular'},
                            {'name': 'noto_sans', 'point_size': 18, 'style': 'bold'}])
        return manager
    
    def _create_game_buttons(self, manager):
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
                text='TRACK', manager=manager),

            # Pitcher selection buttons for main  menu
            'sale': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((400, 500), (190, 50)),
                text='Chris Sale', manager=manager),
            'degrom': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((400, 600), (190, 50)),
                text='Jacob deGrom', manager=manager),
            'sasaki': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((600, 500), (190, 50)),
                text='Roki Sasaki', manager=manager),
            'yamamoto': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((600, 600), (190, 50)),
                text='Y. Yamamoto', manager=manager),
            'mcclanahan': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((800, 500), (190, 50)),
                text='S. Mcclanahan', manager=manager),

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
                relative_rect=pygame.Rect((540, 530), (200, 50)),
                text='MAIN MENU', manager=manager),
                
            # Button for inning end screen
            'continue_to_summary': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((540, 630), (200, 50)),
                text='CONTINUE', manager=manager),

            # Settings menu buttons
            'settings': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((1130, 650), (140, 40)),
                text='Settings', manager=manager),
            'back_to_main': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((50, 650), (150, 50)),
                text='Back', manager=manager),

            # Difficulty selection buttons
            'difficulty_rookie': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((360, 200), (160, 50)),
                text='Rookie', manager=manager),
            'difficulty_amateur': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((540, 200), (160, 50)),
                text='Amateur', manager=manager),
            'difficulty_professional': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((720, 200), (160, 50)),
                text='Professional', manager=manager),
            'difficulty_allstar': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((450, 270), (160, 50)),
                text='All-Star', manager=manager),
            'difficulty_halloffame': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((630, 270), (160, 50)),
                text='Hall of Fame', manager=manager),

            # Other settings toggles
            'toggle_ump_sound_settings': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((390, 360), (220, 50)),
                text='Umpire Sound: ON', manager=manager),
            'toggle_strikezone_settings': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((630, 360), (220, 50)),
                text='Strikezone: ON', manager=manager),
            # FPS settings buttons (cycle-style)
            'display_fps_setting': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((390, 430), (220, 50)),
                text='Display FPS: 60', manager=manager),
            'engine_fps_setting': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((630, 430), (220, 50)),
                text='Engine FPS: 60', manager=manager),
            'key_bindings': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((515, 500), (250, 50)),
                text='Key Bindings', manager=manager),
            'reset_settings': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((515, 570), (250, 50)),
                text='Reset to Defaults', manager=manager),

            # Key binding configuration buttons
            'back_from_keybinds': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((50, 650), (150, 50)),
                text='Back', manager=manager),
            'reset_keybinds': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((1080, 650), (150, 50)),
                text='Reset Keys', manager=manager),

            # Individual key binding buttons
            'bind_toggle_ui': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((300, 200), (680, 50)),
                text='Toggle UI: H', manager=manager),
            'bind_toggle_strikezone': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((300, 260), (680, 50)),
                text='Toggle Strikezone: Z', manager=manager),
            'bind_toggle_sound': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((300, 320), (680, 50)),
                text='Toggle Sound: M', manager=manager),
            'bind_toggle_batter': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((300, 380), (680, 50)),
                text='Toggle Batter: B', manager=manager),
            'bind_quick_pitch': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((300, 440), (680, 50)),
                text='Quick Pitch: Space', manager=manager),
            'bind_view_pitches': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((300, 500), (680, 50)),
                text='View Pitches: V', manager=manager),
            'bind_main_menu': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((300, 560), (680, 50)),
                text='Main Menu: Escape', manager=manager),
            'bind_toggle_track': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((300, 620), (680, 50)),
                text='Toggle Track: T', manager=manager),

            # GameDay mode buttons
            'start_gameday': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((490, 550), (300, 60)),
                text='Start Game', manager=manager),
            'next_inning': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((490, 550), (300, 50)),
                text='Next Inning', manager=manager),
            'start_batting': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((490, 550), (300, 50)),
                text='Start Your At-Bat', manager=manager),
            'view_game_log': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((490, 620), (300, 40)),
                text='View Game Log', manager=manager),
            'final_menu': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((490, 550), (300, 50)),
                text='Return to Main Menu', manager=manager)
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
        self.banner = pygame_gui.elements.UILabel(
            relative_rect=pygame.Rect((150, 0), (980, 100)),
            manager=self.manager,
            text=""
        )
        self.scoreboard = pygame_gui.elements.UITextBox(
            html_text="",
            relative_rect=pygame.Rect((1000, 50), (250, 200)),
            manager=self.manager
        )
        self.pitch_result = pygame_gui.elements.UITextBox(
            html_text="",
            relative_rect=pygame.Rect((1000, 250), (250, 200)),
            manager=self.manager
        )
        self.view_window = StatSwing((25, 25), self.manager, [], [])
        self.banner.hide()
        self.view_window.hide()
        self.scoreboard.hide()
        self.pitch_result.hide()

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

    def update_scoreboard(self, text, typing_speed=0.0075):
        """Updates the scoreboard with new text and a typing effect."""
        # Only show if UI is visible
        if not self.key_binding_manager or self.key_binding_manager.is_ui_visible():
            self.scoreboard.show()
        self.scoreboard.set_text(text)
        self.scoreboard.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': typing_speed})

    def update_pitch_result(self, text, typing_speed=0.0085):
        """Updates the pitch result box with new text and a typing effect."""
        # Only show if UI is visible
        if not self.key_binding_manager or self.key_binding_manager.is_ui_visible():
            self.pitch_result.show()
        self.pitch_result.set_text(text)
        self.pitch_result.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': typing_speed})

    def clear_pitch_result(self):
        """Clears the pitch result and scoreboard."""
        self.pitch_result.set_text("")
        self.scoreboard.set_text("")

    def show_banner(self, text, typing_speed=0.1):
        """Shows the banner with the given text and a typing effect."""
        self.banner.set_text(text)
        self.banner.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': typing_speed})
        self.banner.show()

    def update(self, time_delta):
        """Updates the UI manager and all UI elements."""
        self.manager.update(time_delta)

    def draw(self):
        """Draws the UI manager and all UI elements to the screen."""
        self.manager.draw_ui(self.screen)

    def create_scoreboard(self, results):
        """Creates and returns a new scoreboard text box."""
        return pygame_gui.elements.UITextBox(
            html_text=results,
            relative_rect=pygame.Rect((1000, 50), (250, 200)),
            manager=self.manager
        )

    def update_container(self, textbox, scoreboard):
        """Updates the container with new textbox and scoreboard."""
        self.container.clear()
        self.container.add_element(textbox)
        self.container.add_element(scoreboard)

    def update_pitch_info(self, pitch_trajectories, last_pitch_info):
        """Updates pitch information in the view window (legacy method)."""
        self.view_window.update_pitch_info(pitch_trajectories, last_pitch_info)

    def update_pitch_info_enhanced(self, enhanced_records):
        """Updates pitch information with enhanced record data for advanced visualization."""
        self.view_window.update_pitch_info_enhanced(enhanced_records)

    def show_view_window(self):
        """Shows the pitch view window."""
        self.view_window.show()

    def hide_view_window(self):
        """Hides the pitch view window."""
        self.view_window.hide()

    def update_view_window_fps(self, display_fps):
        """Update the view window's display FPS for animation timing."""
        self.view_window.set_display_fps(display_fps)

    def hide_banner(self):
        self.banner.hide()

    def set_visibility_state(self, state):
        """Alias for set_button_visibility for clearer state-based visibility."""
        self.set_button_visibility(state)

    def set_button_visibility(self, state, force_show=False):
        """Show or hide buttons based on game state ('in_game', 'pitching', 'menu')."""

        # Check if UI should be hidden due to key binding toggle
        if (self.key_binding_manager and
            not self.key_binding_manager.is_ui_visible() and
            not force_show):
            # Hide all UI elements when UI visibility is toggled off (except banner)
            for button in self.buttons.values():
                button.hide()
            # Keep banner visible - it should be unaffected by UI toggle
            # self.banner.hide()  # Commented out to keep banner visible
            self.scoreboard.hide()
            self.pitch_result.hide()
            self.view_window.hide()
            return

        # Hide all buttons initially
        for button in self.buttons.values():
            button.hide()

        if state == 'in_game':
            self.buttons['strikezone'].show()
            self.buttons['main_menu'].show()
            self.buttons['toggle_ump_sound'].show()
            self.buttons['view_pitches'].show()
            self.buttons['toggle_batter'].show()
            self.buttons['visualise'].show()
            self.buttons['pitch'].show()
            # Only show textboxes if UI is visible
            if not self.key_binding_manager or self.key_binding_manager.is_ui_visible():
                self.scoreboard.show()
                self.pitch_result.show()
        elif state == 'pitching':
            # All buttons are hidden during the pitch animation
            pass
        elif state == 'view_pitches':
            # Show the same buttons as in_game so they can toggle back
            self.buttons['strikezone'].show()
            self.buttons['main_menu'].show()
            self.buttons['toggle_ump_sound'].show()
            self.buttons['view_pitches'].show()
            self.buttons['toggle_batter'].show()
            self.buttons['visualise'].show()
            self.buttons['pitch'].show()
            if not self.key_binding_manager or self.key_binding_manager.is_ui_visible():
                self.scoreboard.show()
                self.pitch_result.show()
        elif state == 'main_menu':
            self.buttons['sale'].show()
            self.buttons['degrom'].show()
            self.buttons['sasaki'].show()
            self.buttons['yamamoto'].show()
            self.buttons['mcclanahan'].show()
            self.buttons['random_scenario'].show()
            self.buttons['gameday'].show()
            self.buttons['settings'].show()
            self.banner.hide()
            self.scoreboard.hide()
            self.pitch_result.hide()
        elif state == "visualise":
            # Show the same buttons as in_game so they can toggle back
            self.buttons['strikezone'].show()
            self.buttons['main_menu'].show()
            self.buttons['toggle_ump_sound'].show()
            self.buttons['view_pitches'].show()
            self.buttons['toggle_batter'].show()
            self.buttons['visualise'].show()
            self.buttons['pitch'].show()
            if not self.key_binding_manager or self.key_binding_manager.is_ui_visible():
                self.scoreboard.show()
                self.pitch_result.show()
        elif state == 'summary':
            self.buttons['back_to_main_menu'].show()
            self.banner.hide()
            self.scoreboard.hide()
            self.pitch_result.hide()
        elif state == 'inning_end':
            self.buttons['continue_to_summary'].show()
            self.buttons['visualise'].show()
            self.buttons['view_pitches'].show()
            self.buttons['strikezone'].show()
            self.buttons['main_menu'].show()
            # Only show textboxes if UI is visible
            if not self.key_binding_manager or self.key_binding_manager.is_ui_visible():
                self.scoreboard.show()
                self.pitch_result.show()
        elif state == 'settings':
            self.buttons['back_to_main'].show()
            self.buttons['difficulty_rookie'].show()
            self.buttons['difficulty_amateur'].show()
            self.buttons['difficulty_professional'].show()
            self.buttons['difficulty_allstar'].show()
            self.buttons['difficulty_halloffame'].show()
            self.buttons['toggle_ump_sound_settings'].show()
            self.buttons['toggle_strikezone_settings'].show()
            self.buttons['display_fps_setting'].show()
            self.buttons['engine_fps_setting'].show()
            self.buttons['key_bindings'].show()
            self.buttons['reset_settings'].show()
            self.banner.hide()
            self.scoreboard.hide()
            self.pitch_result.hide()
        elif state == 'key_bindings':
            self.buttons['back_from_keybinds'].show()
            self.buttons['reset_keybinds'].show()
            self.buttons['bind_toggle_ui'].show()
            self.buttons['bind_toggle_strikezone'].show()
            self.buttons['bind_toggle_sound'].show()
            self.buttons['bind_toggle_batter'].show()
            self.buttons['bind_quick_pitch'].show()
            self.buttons['bind_view_pitches'].show()
            self.buttons['bind_main_menu'].show()
            self.buttons['bind_toggle_track'].show()
            self.banner.hide()
            self.scoreboard.hide()
            self.pitch_result.hide()
        elif state == 'gameday_start':
            # Initial gameday screen with start button
            self.buttons['start_gameday'].show()
            self.buttons['main_menu'].show()
            self.scoreboard.hide()
            self.pitch_result.hide()
        elif state == 'gameday_transition':
            # After player's inning ends, before opponent bats
            self.buttons['next_inning'].show()
            self.buttons['view_game_log'].show()
            self.buttons['main_menu'].show()
            self.scoreboard.hide()
            self.pitch_result.hide()
        elif state == 'gameday_simulation':
            # After opponent simulation, ready to start player batting
            self.buttons['start_batting'].show()
            self.buttons['view_game_log'].show()
            self.buttons['main_menu'].show()
            self.scoreboard.hide()
            self.pitch_result.hide()
        elif state == 'gameday_final':
            # Game over screen
            self.buttons['final_menu'].show()
            self.buttons['view_game_log'].show()
            self.scoreboard.hide()
            self.pitch_result.hide()

    def draw_typing_effect(self, message, counter, speed, position, use_big_font=False):
        """Draws text with a typing effect at the given position."""
        font = self.big_font if use_big_font else self.font
        snip = font.render(message[0:counter//speed], True, 'white')
        self.screen.blit(snip, position)
        
    def draw_completed_message(self, message, position, use_big_font=False):
        """Draws a completed message at the given position."""
        font = self.big_font if use_big_font else self.font
        text = font.render(message, True, 'white')
        self.screen.blit(text, position)

    def update_settings_button_states(self, settings_manager):
        """Update the text and appearance of settings buttons based on current settings."""
        # Update umpire sound button
        ump_sound = settings_manager.get_setting("umpire_sound")
        self.buttons['toggle_ump_sound_settings'].set_text(f"Umpire Sound: {'ON' if ump_sound else 'OFF'}")

        # Update strikezone button
        show_strikezone = settings_manager.get_setting("show_strikezone")
        self.buttons['toggle_strikezone_settings'].set_text(f"Strikezone: {'ON' if show_strikezone else 'OFF'}")

        # Update FPS buttons
        display_fps = settings_manager.get_display_fps()
        engine_fps = settings_manager.get_engine_fps()
        self.buttons['display_fps_setting'].set_text(f"Display FPS: {display_fps}")
        self.buttons['engine_fps_setting'].set_text(f"Engine FPS: {engine_fps}")

        # Highlight current difficulty button
        current_difficulty = settings_manager.get_difficulty().value
        difficulty_buttons = {
            'rookie': 'difficulty_rookie',
            'amateur': 'difficulty_amateur',
            'professional': 'difficulty_professional',
            'all_star': 'difficulty_allstar',
            'hall_of_fame': 'difficulty_halloffame'
        }

        # Reset all difficulty button colors (you might need to adjust this based on your theme)
        for button_key in difficulty_buttons.values():
            if button_key in self.buttons:
                # This would need theme support for button highlighting
                pass

    def show_settings_info(self, settings_manager):
        """Show current difficulty description in the banner."""
        difficulty_desc = settings_manager.get_difficulty_description()
        self.show_banner(difficulty_desc, typing_speed=0.02)

    def update_key_binding_buttons(self, key_binding_manager):
        """Update the text of key binding buttons based on current bindings."""
        from key_binding_manager import KeyAction

        bindings = {
            KeyAction.TOGGLE_UI: 'bind_toggle_ui',
            KeyAction.TOGGLE_STRIKEZONE: 'bind_toggle_strikezone',
            KeyAction.TOGGLE_SOUND: 'bind_toggle_sound',
            KeyAction.TOGGLE_BATTER: 'bind_toggle_batter',
            KeyAction.QUICK_PITCH: 'bind_quick_pitch',
            KeyAction.VIEW_PITCHES: 'bind_view_pitches',
            KeyAction.MAIN_MENU: 'bind_main_menu',
            KeyAction.TOGGLE_TRACK: 'bind_toggle_track'
        }

        for action, button_key in bindings.items():
            if button_key in self.buttons:
                action_name = key_binding_manager.get_action_name(action)
                key_name = key_binding_manager.get_key_name(key_binding_manager.get_key_for_action(action))
                self.buttons[button_key].set_text(f"{action_name}: {key_name}")

    def show_key_bindings_info(self):
        """Show key bindings help text in the banner."""
        # Don't show banner for key bindings page - keep it clean
        pass

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
            # self.banner.hide()  # Commented out to keep banner visible
            self.scoreboard.hide()
            self.pitch_result.hide()
            self.view_window.hide()

    def is_ui_hidden(self):
        """Check if all UI elements are currently hidden."""
        # Check if any essential UI elements are visible
        essential_buttons = ['pitch', 'main_menu', 'strikezone']
        for button_name in essential_buttons:
            if button_name in self.buttons and self.buttons[button_name].visible:
                return False
        return not (self.banner.visible or self.scoreboard.visible or self.pitch_result.visible)