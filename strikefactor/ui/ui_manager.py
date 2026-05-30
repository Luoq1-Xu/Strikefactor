import pygame
import pygame_gui
from pygame_gui.core import ObjectID
import json
from helpers import StatSwing
from config import get_path, resource_path
from ui.scouting_panel import ScoutingReportPanel
from ui.lap_log_panel import LapLogPanel
from ui.box_score_panel import BoxScorePanel


class UIManager:
    def __init__(self, screen, screen_size, theme_path=None):
        self.screen = screen
        self.manager = self._create_ui_manager(screen_size, theme_path)
        self.small_font = pygame.font.Font(resource_path(get_path("ui/font/8bitoperator_jve.ttf")), 28)
        self.font = pygame.font.Font(resource_path(get_path("ui/font/8bitoperator_jve.ttf")), 48)  # +20% from 40
        self.big_font = pygame.font.Font(resource_path(get_path("ui/font/8bitoperator_jve.ttf")), 84)  # +20% from 70
        self.button_callbacks = {}
        self.key_binding_manager = None  # Will be set after initialization
        self.settings_manager = None  # Will be set after initialization
        self._create_ui_elements()

    def set_key_binding_manager(self, key_binding_manager):
        """Set the key binding manager reference for UI visibility control."""
        self.key_binding_manager = key_binding_manager

    def set_settings_manager(self, settings_manager):
        """Set the settings manager reference (e.g. for HUD mode lookups)."""
        self.settings_manager = settings_manager

    def _hud_mode(self) -> str:
        if self.settings_manager is None:
            return "legacy"
        return self.settings_manager.get_hud_mode()

    def _is_legacy_hud(self) -> bool:
        """Side-panel buttons only render in legacy mode."""
        return self._hud_mode() == "legacy"

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
            'scout': pygame_gui.elements.UIButton(
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
            # Session group
            'lap_stats': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((6, 362), (58, 28)),
                text='LAP', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'view_laps': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((68, 362), (58, 28)),
                text='LOG', manager=manager,
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
                text='Rookie', manager=manager,
                object_id=ObjectID(class_id='@settings_button')),
            'difficulty_amateur': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((540, 200), (160, 50)),
                text='Amateur', manager=manager,
                object_id=ObjectID(class_id='@settings_button')),
            'difficulty_professional': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((720, 200), (160, 50)),
                text='Professional', manager=manager,
                object_id=ObjectID(class_id='@settings_button')),
            'difficulty_allstar': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((450, 270), (160, 50)),
                text='All-Star', manager=manager,
                object_id=ObjectID(class_id='@settings_button')),
            'difficulty_halloffame': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((630, 270), (160, 50)),
                text='Hall of Fame', manager=manager,
                object_id=ObjectID(class_id='@settings_button')),

            # Other settings toggles
            'toggle_ump_sound_settings': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((390, 360), (220, 50)),
                text='Umpire Sound: ON', manager=manager,
                object_id=ObjectID(class_id='@settings_button')),
            'toggle_strikezone_settings': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((630, 360), (220, 50)),
                text='Strikezone: ON', manager=manager,
                object_id=ObjectID(class_id='@settings_button')),
            'toggle_abs_settings': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((870, 360), (220, 50)),
                text='ABS Challenge: ON', manager=manager,
                object_id=ObjectID(class_id='@settings_button')),
            # FPS settings buttons (cycle-style)
            'display_fps_setting': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((390, 430), (220, 50)),
                text='Display FPS: 60', manager=manager,
                object_id=ObjectID(class_id='@settings_button')),
            'engine_fps_setting': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((630, 430), (220, 50)),
                text='Engine FPS: 60', manager=manager,
                object_id=ObjectID(class_id='@settings_button')),
            'toggle_hud_mode_settings': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((870, 430), (220, 50)),
                text='HUD: Legacy', manager=manager,
                object_id=ObjectID(class_id='@settings_button')),
            'key_bindings': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((515, 500), (250, 50)),
                text='Key Bindings', manager=manager,
                object_id=ObjectID(class_id='@settings_button')),
            'reset_settings': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((515, 570), (250, 50)),
                text='Reset to Defaults', manager=manager,
                object_id=ObjectID(class_id='@settings_button')),

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
            'bind_challenge': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((300, 680), (680, 50)),
                text='ABS Challenge: C', manager=manager),

            # GameDay mode buttons (broadcast-styled to match the refreshed UI)
            'start_gameday': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((490, 580), (300, 44)),
                text='STEP IN  >', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'gameday_prev_pitcher': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((255, 330), (50, 50)),
                text='<', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'gameday_next_pitcher': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((975, 330), (50, 50)),
                text='>', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            # Dedicated menu-screen sized "main menu" for gameday menu states,
            # so the tiny (6, 428) sidebar button isn't shown on full menu screens.
            'gameday_main_menu': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((40, 660), (150, 36)),
                text='MAIN MENU', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'next_inning': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((780, 600), (440, 44)),
                text='NEXT INNING  >', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'start_batting': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((780, 600), (440, 44)),
                text='STEP IN  >', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'view_game_log': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((780, 650), (210, 32)),
                text='GAME LOG', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'final_menu': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((780, 600), (440, 44)),
                text='NEXT GAME  >', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),

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
                relative_rect=pygame.Rect((6, 356), (120, 28)),
                text='SALE', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitcher_degrom': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((6, 384), (120, 28)),
                text='DEGROM', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitcher_sasaki': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((6, 412), (120, 28)),
                text='SASAKI', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitcher_yamamoto': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((6, 440), (120, 28)),
                text='YAMAMOTO', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitcher_mcclanahan': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((6, 468), (120, 28)),
                text='MCCLANAHAN', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),

            # Sandbox gameplay - Pitch toggle buttons (left sidebar, 2-column broadcast style)
            'sandbox_pitch_1': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((6, 508), (58, 28)),
                text='', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitch_2': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((68, 508), (58, 28)),
                text='', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitch_3': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((6, 538), (58, 28)),
                text='', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitch_4': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((68, 538), (58, 28)),
                text='', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitch_5': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((6, 568), (58, 28)),
                text='', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_pitch_6': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((68, 568), (58, 28)),
                text='', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),

            # Sandbox gameplay - System buttons (left sidebar bottom)
            'sandbox_sound': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((6, 608), (120, 28)),
                text='SOUND', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button')),
            'sandbox_exit': pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((6, 636), (120, 28)),
                text='EXIT', manager=manager,
                object_id=ObjectID(class_id='@broadcast_button'))
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
            relative_rect=pygame.Rect((950, 30), (310, 260)),  # Enlarged: +60px width, +60px height
            manager=self.manager
        )
        self.pitch_result = pygame_gui.elements.UITextBox(
            html_text="",
            relative_rect=pygame.Rect((950, 300), (310, 200)),  # Enlarged: +60px width, adjusted position
            manager=self.manager
        )
        self.view_window = StatSwing((25, 25), self.manager, [], [])
        self.scouting_panel = ScoutingReportPanel(
            position=(1000, 50),  # Same position as scoreboard
            manager=self.manager
        )
        self.lap_log_panel = LapLogPanel(
            position=(465, 160),  # Center of screen
            manager=self.manager
        )
        self.box_score_panel = BoxScorePanel(
            position=(80, 100),
            manager=self.manager
        )
        self.banner.hide()
        self.view_window.hide()
        self.scoreboard.hide()
        self.pitch_result.hide()
        self.scouting_panel.hide()
        self.lap_log_panel.hide()
        self.box_score_panel.hide()

        # Hide all buttons initially
        for button in self.buttons.values():
            button.hide() 

    def process_events(self, event):
        """Processes events for the UI manager."""
        self.manager.process_events(event)
        if event.type == pygame_gui.UI_BUTTON_PRESSED:
            # Handle lap log panel close button
            if event.ui_element == self.lap_log_panel.get_close_button():
                self.lap_log_panel.hide()
                return

            for key, button in self.buttons.items():
                if event.ui_element == button and key in self.button_callbacks:
                    # Call the registered callback for the button
                    self.button_callbacks[key]()
                    break

    def show_banner(self, text, typing_speed=0.1):
        """Shows the banner with the given text and a typing effect."""
        self.banner.set_text(text)
        self.banner.set_active_effect(pygame_gui.TEXT_EFFECT_TYPING_APPEAR, {'time_per_letter': typing_speed})
        self.banner.show()

    def schedule_banner(self, text, delay=450, typing_speed=0.1):
        """Schedule a banner to show after a delay (in ms), to sync with umpire call."""
        self._pending_banner = {
            'text': text,
            'typing_speed': typing_speed,
            'show_time': pygame.time.get_ticks() + delay
        }

    def update(self, time_delta):
        """Updates the UI manager and all UI elements."""
        # Check for pending scheduled banners
        if hasattr(self, '_pending_banner') and self._pending_banner is not None:
            if pygame.time.get_ticks() >= self._pending_banner['show_time']:
                self.show_banner(self._pending_banner['text'], self._pending_banner['typing_speed'])
                self._pending_banner = None
        self.manager.update(time_delta)

    def draw(self):
        """Draws the UI manager and all UI elements to the screen."""
        self.manager.draw_ui(self.screen)

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

    def toggle_scouting_panel(self, pitcher=None):
        """Toggle the scouting report panel visibility (replaces scoreboard when shown)."""
        if pitcher:
            self.scouting_panel.update_data(pitcher)

        if self.scouting_panel.visible:
            # Hide scouting panel, show scoreboard
            self.scouting_panel.hide()
            self.scoreboard.show()
        else:
            # Show scouting panel, hide scoreboard
            self.scoreboard.hide()
            self.scouting_panel.show()

    def update_scouting_panel(self, pitcher):
        """Update the scouting panel with pitcher data."""
        if pitcher:
            self.scouting_panel.update_data(pitcher)

    def hide_scouting_panel(self):
        """Hide the scouting report panel."""
        self.scouting_panel.hide()

    def refresh_scouting_panel(self):
        """Refresh the scouting panel stats (call after each pitch)."""
        if self.scouting_panel.visible:
            self.scouting_panel.refresh_stats()

    def toggle_lap_log_panel(self, field_renderer=None):
        """Toggle the lap log panel visibility."""
        # Hide scouting panel if visible to avoid overlap
        if self.scouting_panel.visible:
            self.scouting_panel.hide()
            self.scoreboard.show()

        if field_renderer:
            laps = field_renderer.get_lap_history()
            # Get current session stats
            current_stats = {
                'total_pitches': field_renderer.total_pitches,
                'total_swings': field_renderer.total_swings,
                'total_hits': field_renderer.total_hits,
                'total_at_bats': field_renderer.total_at_bats,
                'batting_average': field_renderer.get_overall_batting_average()
            }
            self.lap_log_panel.update_data(laps, current_stats)

        if self.lap_log_panel.visible:
            self.lap_log_panel.hide()
        else:
            self.lap_log_panel.show()

    def hide_lap_log_panel(self):
        """Hide the lap log panel."""
        self.lap_log_panel.hide()

    def is_lap_log_visible(self) -> bool:
        """Check if lap log panel is visible."""
        return self.lap_log_panel.visible

    def show_box_score(self, box_data, current_inning=None, position=None):
        """Show and update the box score panel."""
        if position:
            self.box_score_panel.set_position(position)
        self.box_score_panel.update_scores(box_data, current_inning)
        self.box_score_panel.show()

    def hide_box_score(self):
        """Hide the box score panel."""
        self.box_score_panel.hide()

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
        for i, pitch_name in enumerate(pitch_names):
            if i < len(pitch_buttons):
                btn = self.buttons[pitch_buttons[i]]
                # Add indicator for active pitches
                if pitch_name in active_pitches:
                    btn.set_text(f"[{pitch_name}]")
                else:
                    btn.set_text(pitch_name)
                btn.show()

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

        # States that should always show their UI regardless of H-toggle
        ui_toggle_exempt = {
            'gameday_start', 'gameday_transition', 'gameday_simulation',
            'gameday_final', 'main_menu', 'mode_select', 'settings',
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
            # self.banner.hide()  # Commented out to keep banner visible
            self.scoreboard.hide()
            self.pitch_result.hide()
            self.view_window.hide()
            self.scouting_panel.hide()
            self.box_score_panel.hide()
            self.lap_log_panel.hide()
            return

        # Hide all buttons initially
        for button in self.buttons.values():
            button.hide()

        if state == 'in_game':
            if self._is_legacy_hud():
                self.buttons['strikezone'].show()
                self.buttons['main_menu'].show()
                self.buttons['toggle_ump_sound'].show()
                self.buttons['view_pitches'].show()
                self.buttons['toggle_batter'].show()
                self.buttons['visualise'].show()
                self.buttons['scout'].show()
                self.buttons['lap_stats'].show()
                self.buttons['view_laps'].show()
            # Scorebug handles stats display during gameplay
            self.scoreboard.hide()
            self.pitch_result.hide()
        elif state == 'pitching':
            # All buttons are hidden during the pitch animation
            pass
        elif state == 'view_pitches':
            # Show the same buttons as in_game so they can toggle back
            if self._is_legacy_hud():
                self.buttons['strikezone'].show()
                self.buttons['main_menu'].show()
                self.buttons['toggle_ump_sound'].show()
                self.buttons['view_pitches'].show()
                self.buttons['toggle_batter'].show()
                self.buttons['visualise'].show()
                self.buttons['scout'].show()
                self.buttons['lap_stats'].show()
                self.buttons['view_laps'].show()
            # Scorebug handles stats display
            self.scoreboard.hide()
            self.pitch_result.hide()
        elif state == 'main_menu':
            self.buttons['sale'].show()
            self.buttons['degrom'].show()
            self.buttons['sasaki'].show()
            self.buttons['yamamoto'].show()
            self.buttons['mcclanahan'].show()
            self.buttons['random_scenario'].show()
            self.buttons['gameday'].show()
            self.buttons['back_to_mode_select'].show()
            self.banner.hide()
            self.scoreboard.hide()
            self.pitch_result.hide()
            self.scouting_panel.hide()
            self.lap_log_panel.hide()
            self.box_score_panel.hide()
        elif state == "visualise":
            # Show the same buttons as in_game so they can toggle back
            if self._is_legacy_hud():
                self.buttons['strikezone'].show()
                self.buttons['main_menu'].show()
                self.buttons['toggle_ump_sound'].show()
                self.buttons['view_pitches'].show()
                self.buttons['toggle_batter'].show()
                self.buttons['visualise'].show()
                self.buttons['scout'].show()
                self.buttons['lap_stats'].show()
                self.buttons['view_laps'].show()
            self.scoreboard.hide()
            self.pitch_result.hide()
        elif state == 'summary':
            self.buttons['back_to_main_menu'].show()
            self.banner.hide()
            self.scoreboard.hide()
            self.pitch_result.hide()
            self.scouting_panel.hide()
            self.lap_log_panel.hide()
            self.box_score_panel.hide()
        elif state == 'inning_end':
            # Continue button always shown so the player can advance.
            self.buttons['continue_to_summary'].show()
            if self._is_legacy_hud():
                self.buttons['visualise'].show()
                self.buttons['view_pitches'].show()
                self.buttons['strikezone'].show()
                self.buttons['main_menu'].show()
                self.buttons['lap_stats'].show()
                self.buttons['view_laps'].show()
            self.scouting_panel.hide()
            self.lap_log_panel.hide()
            self.scoreboard.hide()
            self.pitch_result.hide()
        elif state == 'settings':
            self.buttons['back_to_main'].show()
            self.buttons['difficulty_rookie'].show()
            self.buttons['difficulty_amateur'].show()
            self.buttons['difficulty_professional'].show()
            self.buttons['difficulty_allstar'].show()
            self.buttons['difficulty_halloffame'].show()
            self.buttons['toggle_ump_sound_settings'].show()
            self.buttons['toggle_strikezone_settings'].show()
            self.buttons['toggle_abs_settings'].show()
            self.buttons['display_fps_setting'].show()
            self.buttons['engine_fps_setting'].show()
            self.buttons['toggle_hud_mode_settings'].show()
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
            self.buttons['bind_challenge'].show()
            self.banner.hide()
            self.scoreboard.hide()
            self.pitch_result.hide()
        elif state == 'gameday_start':
            # Initial gameday screen with pitcher carousel
            self.buttons['start_gameday'].show()
            self.buttons['gameday_prev_pitcher'].show()
            self.buttons['gameday_next_pitcher'].show()
            self.buttons['gameday_main_menu'].show()
            self.scoreboard.hide()
            self.pitch_result.hide()
            self.scouting_panel.hide()
            self.lap_log_panel.hide()
            self.box_score_panel.hide()
        elif state == 'gameday_transition':
            # After player's inning ends, before opponent bats
            self.buttons['next_inning'].show()
            self.buttons['view_game_log'].show()
            self.buttons['gameday_main_menu'].show()
            self.scoreboard.hide()
            self.pitch_result.hide()
            self.scouting_panel.hide()
            self.lap_log_panel.hide()
            self.box_score_panel.hide()
        elif state == 'gameday_simulation':
            # After opponent simulation, ready to start player batting
            self.buttons['start_batting'].show()
            self.buttons['view_game_log'].show()
            self.buttons['gameday_main_menu'].show()
            self.scoreboard.hide()
            self.pitch_result.hide()
            self.scouting_panel.hide()
            self.lap_log_panel.hide()
            self.box_score_panel.hide()
        elif state == 'gameday_final':
            # Game over screen
            self.buttons['final_menu'].show()
            self.buttons['view_game_log'].show()
            self.scoreboard.hide()
            self.pitch_result.hide()
            self.scouting_panel.hide()
            self.lap_log_panel.hide()
            self.box_score_panel.hide()
        elif state == 'mode_select':
            # Top-level mode selection (Arcade/Sandbox)
            self.buttons['arcade_mode'].show()
            self.buttons['sandbox_mode'].show()
            self.buttons['settings'].show()
            self.banner.hide()
            self.scoreboard.hide()
            self.pitch_result.hide()
            self.scouting_panel.hide()
            self.box_score_panel.hide()
        elif state == 'sandbox_menu':
            # Sandbox mode menu - pitcher selection (matching arcade aesthetic)
            self.buttons['sandbox_menu_sale'].show()
            self.buttons['sandbox_menu_degrom'].show()
            self.buttons['sandbox_menu_sasaki'].show()
            self.buttons['sandbox_menu_yamamoto'].show()
            self.buttons['sandbox_menu_mcclanahan'].show()
            self.buttons['back_to_mode_select'].show()
            self.banner.hide()
            self.scoreboard.hide()
            self.pitch_result.hide()
            self.scouting_panel.hide()
            self.lap_log_panel.hide()
            self.box_score_panel.hide()
        elif state == 'sandbox_gameplay':
            # Sandbox gameplay - broadcast-style left sidebar
            # Standard controls
            self.buttons['strikezone'].show()
            self.buttons['toggle_batter'].show()
            self.buttons['view_pitches'].show()
            # Pitcher switch buttons
            self.buttons['sandbox_pitcher_sale'].show()
            self.buttons['sandbox_pitcher_degrom'].show()
            self.buttons['sandbox_pitcher_sasaki'].show()
            self.buttons['sandbox_pitcher_yamamoto'].show()
            self.buttons['sandbox_pitcher_mcclanahan'].show()
            # Pitch buttons shown via update_sandbox_pitch_buttons()
            # System buttons
            self.buttons['sandbox_sound'].show()
            self.buttons['sandbox_exit'].show()
            self.banner.hide()
            self.scouting_panel.hide()
            self.scoreboard.hide()
            self.pitch_result.hide()
        elif state == 'sandbox_view_pitches':
            # Sandbox mode view pitches - same sidebar layout
            self.buttons['strikezone'].show()
            self.buttons['toggle_batter'].show()
            self.buttons['view_pitches'].show()
            self.buttons['sandbox_pitcher_sale'].show()
            self.buttons['sandbox_pitcher_degrom'].show()
            self.buttons['sandbox_pitcher_sasaki'].show()
            self.buttons['sandbox_pitcher_yamamoto'].show()
            self.buttons['sandbox_pitcher_mcclanahan'].show()
            self.buttons['sandbox_sound'].show()
            self.buttons['sandbox_exit'].show()
            self.banner.hide()
            self.scouting_panel.hide()
            self.scoreboard.hide()
            self.pitch_result.hide()

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

    def update_settings_button_states(self, settings_manager):
        """Update the text and appearance of settings buttons based on current settings."""
        # Update umpire sound button
        ump_sound = settings_manager.get_setting("umpire_sound")
        self.buttons['toggle_ump_sound_settings'].set_text(f"Umpire Sound: {'ON' if ump_sound else 'OFF'}")

        # Update strikezone button
        show_strikezone = settings_manager.get_setting("show_strikezone")
        self.buttons['toggle_strikezone_settings'].set_text(f"Strikezone: {'ON' if show_strikezone else 'OFF'}")

        # Update ABS challenge button
        abs_enabled = settings_manager.get_setting("abs_enabled")
        self.buttons['toggle_abs_settings'].set_text(f"ABS Challenge: {'ON' if abs_enabled else 'OFF'}")

        # Update FPS buttons
        display_fps = settings_manager.get_display_fps()
        engine_fps = settings_manager.get_engine_fps()
        self.buttons['display_fps_setting'].set_text(f"Display FPS: {display_fps}")
        self.buttons['engine_fps_setting'].set_text(f"Engine FPS: {engine_fps}")

        # Update HUD mode button (cycles legacy → broadcast → minimal).
        hud_mode = settings_manager.get_hud_mode()
        self.buttons['toggle_hud_mode_settings'].set_text(
            f"HUD: {hud_mode.capitalize()}"
        )

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
            KeyAction.TOGGLE_TRACK: 'bind_toggle_track',
            KeyAction.CHALLENGE: 'bind_challenge',
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
            self.scouting_panel.hide()
            self.lap_log_panel.hide()
            self.box_score_panel.hide()

    def is_ui_hidden(self):
        """Check if all UI elements are currently hidden."""
        # Check if any essential UI elements are visible
        essential_buttons = ['scout', 'main_menu', 'strikezone']
        for button_name in essential_buttons:
            if button_name in self.buttons and self.buttons[button_name].visible:
                return False
        return not (self.banner.visible or self.scoreboard.visible or self.pitch_result.visible)