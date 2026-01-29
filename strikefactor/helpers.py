import pygame
import pygame_gui
import random
import math
from dataclasses import dataclass, field
from typing import List, Tuple, Optional
from pygame_gui.elements.ui_window import UIWindow
from pygame_gui.elements.ui_image import UIImage
from pygame_gui.elements.ui_button import UIButton
from pygame_gui.elements.ui_label import UILabel
from pygame_gui.elements.ui_scrolling_container import UIScrollingContainer
from pygame_gui.core import ObjectID
from pygame_gui.elements.ui_horizontal_slider import UIHorizontalSlider
import pandas as pd


# Pitch type display name mapping
PITCH_TYPE_NAMES = {
    'FF': 'Fastball', 'SI': 'Sinker', 'FC': 'Cutter',
    'SL': 'Slider', 'CB': 'Curveball', 'CU': 'Curveball',
    'CH': 'Changeup', 'FS': 'Splitter', 'KC': 'Knuckle Curve',
    'FF_strike': 'Fastball', 'FF_chase': 'Fastball',
    'SL_strike': 'Slider', 'SL_chase': 'Slider',
    'CB_strike': 'Curveball', 'CB_chase': 'Curveball',
    'CH_strike': 'Changeup', 'CH_chase': 'Changeup',
}

# Outcome color mapping
OUTCOME_COLORS = {
    'STRIKEOUT': (227, 75, 80),    # Red
    'STRIKE': (227, 75, 80),        # Red
    'BALL': (75, 227, 148),         # Green
    'WALK': (75, 227, 148),         # Green
    'FOUL': (255, 200, 100),        # Orange
    'SINGLE': (71, 204, 252),       # Cyan
    'DOUBLE': (71, 204, 252),       # Cyan
    'TRIPLE': (71, 204, 252),       # Cyan
    'HOME RUN': (71, 204, 252),     # Cyan
    'FLYOUT': (198, 169, 251),      # Purple
    'GROUNDOUT': (198, 169, 251),   # Purple
    'LINEOUT': (198, 169, 251),     # Purple
}


@dataclass
class EnhancedPitchRecord:
    """Data class for enhanced pitch information with metadata."""
    trajectory: list                    # Frame-by-frame trajectory data
    pitch_type: str                     # e.g., 'FF', 'SL', 'CB'
    velocity_mph: float                 # Calculated from travel time
    outcome: str                        # 'STRIKE', 'BALL', 'SINGLE', 'FLYOUT', etc.
    final_location: Tuple[float, float] # (x, y) at plate
    index: int                          # Pitch number in game
    selected: bool = False              # For overlay selection

    def get_display_color(self) -> Tuple[int, int, int]:
        """Get color based on outcome for display."""
        return OUTCOME_COLORS.get(self.outcome, (255, 255, 255))

    def get_pitch_type_display(self) -> str:
        """Get user-friendly pitch type name."""
        # Extract base pitch type (remove _strike, _chase suffixes)
        base_type = self.pitch_type.split('_')[0] if '_' in self.pitch_type else self.pitch_type
        return PITCH_TYPE_NAMES.get(self.pitch_type, PITCH_TYPE_NAMES.get(base_type, self.pitch_type))

# Button class
class Button():
    def __init__(self, x, y, image, scale):
        width = image.get_width()
        height = image.get_height()
        self.image = pygame.transform.scale(image, (int(width * scale), int(height * scale)))
        self.rect = self.image.get_rect()
        self.rect.topleft = (x,y)
        self.clicked = False

    def draw(self, screen):
        action = False
        mousepos = pygame.mouse.get_pos()
        
        if self.rect.collidepoint(mousepos):
            if pygame.mouse.get_pressed()[0] == 1 and self.clicked == False:
                self.clicked = True
                action = True
            
        if pygame.mouse.get_pressed()[0] == 0:
            self.clicked = False

        screen.blit(self.image, (self.rect.x, self.rect.y))

        return action
    
# Runner class
class Runner:

    # 0 = Home plate, 1 = First base, 2 = Second base, 3 = Third base
    onBase = False
    base = 0

    def __init__(self, hit_type):
        self.base = hit_type
        if hit_type == 4:
            self.onBase = False
            self.scored = True
        else:
            self.onBase = True
            self.scored = False
        self.speed = random.randint(1, 3)

    def walk(self):
        self.base += 1
        if self.base > 3:
            self.scored = True
            self.onBase = False

    def advance(self, hit):
        self.base += hit
        if self.base > 3:
            self.scored = True
            self.onBase = False

    def extraBases(self, hit):
        self.base += hit + 1
        if self.base > 3:
            self.scored = True
            self.onBase = False

# Scorekeeper class
class ScoreKeeper:

    def __init__(self):
        self.runners = []
        self.bases = ['white', 'white', 'white']
        self.basesfilled = {1: 0, 2: 0, 3: 0}
        self.score = 0

    # Takes in hit_type, then returns tuple of (bases, score)
    def update_hit_event(self, hit_type):
        batter = Runner(hit_type)
        self.runners.append(batter)
        basesFilled = ['white', 'white', 'white']
        scored = 0
        for runner in self.runners[:]:
            if runner != batter:
                self.basesfilled[runner.base] = 0
                runner.advance(hit_type)
            if runner.scored:
                self.runners.remove(runner)
                scored += 1
            else:
                basesFilled[runner.base - 1] = 'yellow'
                self.basesfilled[runner.base] = runner
        self.score += scored
        self.bases = basesFilled
        self.basesfilled[batter.base] = batter
        return (basesFilled, scored)

    def updateScored(self):
        for runner in self.runners[:]:
            if runner.scored:
                self.runners.remove(runner)
                self.score += 1

    def update_walk_event(self):
        batter = Runner(1)
        self.runners.append(batter)
        prevrunner = batter
        base = 1
        while base < 4 and self.basesfilled[base] != 0 :
            currRunner = self.basesfilled[base]
            self.basesfilled[base].walk()
            self.basesfilled[base] = prevrunner
            prevrunner = currRunner
            base += 1
        self.basesfilled[base] = prevrunner
        self.bases = ['white' if base == 0
                            else 'yellow' for base in self.basesfilled.values()]
        self.updateScored()

    def get_bases(self):
        return self.bases
    
    def isRunnerOnBase(self, base):
        return self.basesfilled[base] != 0

    def get_score(self):
        return self.score

    def reset(self):
        self.runners = []
        self.bases = ['white', 'white', 'white']
        self.basesfilled = {1: 0, 2: 0, 3: 0}
        self.score = 0

    def get_runners_on_base(self):
        return len(self.runners)

# Data Visualisation Window Class - Enhanced with pitch history and overlay
class StatSwing(UIWindow):
    """Enhanced pitch visualization window with filtering, selection, and trajectory overlay."""

    # Layout constants
    FILTER_BAR_HEIGHT = 50
    PITCH_LIST_WIDTH = 280
    CONTROLS_HEIGHT = 50
    PITCH_ITEM_HEIGHT = 55

    def __init__(self,
                 position,
                 ui_manager,
                 pitch_trajectories=[],
                 last_pitch_information=[]):
        super().__init__(pygame.Rect(position, (900, 640)), ui_manager,
                         window_display_title='PitchViz - Enhanced',
                         object_id=ObjectID(object_id='#stat_swing_window'),)

        self.parent_ui_manager = ui_manager

        # Calculate visualization area size (right side of window)
        container_size = self.get_container().get_size()
        self.viz_width = container_size[0] - self.PITCH_LIST_WIDTH - 20
        self.viz_height = container_size[1] - self.FILTER_BAR_HEIGHT - self.CONTROLS_HEIGHT - 20
        self.viz_surface_size = (self.viz_width, self.viz_height)

        # Strike zone position within visualization
        self.strikezone = pygame.Rect(
            (self.viz_width // 2 - 65, self.viz_height // 2 - 75),
            (130, 150)
        )

        # Data storage
        self.pitch_records: List[EnhancedPitchRecord] = []
        self.filtered_records: List[EnhancedPitchRecord] = []
        self.selected_records: List[EnhancedPitchRecord] = []
        self.current_filter = 'All'

        # Animation state
        self.animation_frame = 0
        self.animation_playing = True
        self.last_time = pygame.time.get_ticks()
        self.display_fps = 60  # Default, can be updated via set_display_fps()

        # Legacy compatibility
        self.pitch_trajectories = pitch_trajectories
        self.last_pitch_information = last_pitch_information
        self.x = 0  # Legacy frame counter

        # UI element storage
        self.filter_buttons = {}
        self.pitch_item_buttons = []
        self.pitch_item_labels = []

        # Create UI layout
        self._create_ui_layout()

        # Migrate legacy data if provided
        if pitch_trajectories:
            self._migrate_legacy_data()

    def _create_ui_layout(self):
        """Create all UI elements."""
        self._create_filter_buttons()
        self._create_pitch_list_panel()
        self._create_visualization_area()
        self._create_animation_controls()
        self._draw_visualization()

    def _create_filter_buttons(self):
        """Create pitch type filter buttons at the top."""
        filter_types = ['All', 'FF', 'SL', 'CB', 'CH', 'SI', 'FC']
        button_width = 70
        start_x = 10

        for i, filter_type in enumerate(filter_types):
            display_text = 'All' if filter_type == 'All' else filter_type
            btn = UIButton(
                relative_rect=pygame.Rect((start_x + i * (button_width + 5), 5), (button_width, 40)),
                text=display_text,
                manager=self.ui_manager,
                container=self,
                object_id=ObjectID(object_id=f'#filter_{filter_type.lower()}')
            )
            self.filter_buttons[filter_type] = btn

    def _create_pitch_list_panel(self):
        """Create scrollable pitch list panel on the left."""
        list_top = self.FILTER_BAR_HEIGHT + 5
        list_height = self.get_container().get_size()[1] - self.FILTER_BAR_HEIGHT - self.CONTROLS_HEIGHT - 15

        self.pitch_list_container = UIScrollingContainer(
            relative_rect=pygame.Rect((5, list_top), (self.PITCH_LIST_WIDTH, list_height)),
            manager=self.ui_manager,
            container=self,
            allow_scroll_x=False
        )

    def _create_visualization_area(self):
        """Create the pitch trajectory visualization area on the right."""
        viz_left = self.PITCH_LIST_WIDTH + 15
        viz_top = self.FILTER_BAR_HEIGHT + 5

        self.viz_surface_element = UIImage(
            relative_rect=pygame.Rect((viz_left, viz_top), self.viz_surface_size),
            image_surface=pygame.Surface(self.viz_surface_size, pygame.SRCALPHA).convert_alpha(),
            manager=self.ui_manager,
            container=self,
            parent_element=self
        )

    def _create_animation_controls(self):
        """Create animation control buttons at the bottom."""
        container_height = self.get_container().get_size()[1]
        controls_y = container_height - self.CONTROLS_HEIGHT

        # Select All / Clear buttons on left
        self.select_all_btn = UIButton(
            relative_rect=pygame.Rect((10, controls_y + 5), (90, 40)),
            text='Select All',
            manager=self.ui_manager,
            container=self
        )

        self.clear_btn = UIButton(
            relative_rect=pygame.Rect((105, controls_y + 5), (70, 40)),
            text='Clear',
            manager=self.ui_manager,
            container=self
        )

        # Play/Pause button
        slider_start_x = self.PITCH_LIST_WIDTH + 10
        self.play_pause_btn = UIButton(
            relative_rect=pygame.Rect((slider_start_x, controls_y + 5), (60, 40)),
            text='Pause',
            manager=self.ui_manager,
            container=self
        )

        # Frame slider (replaces rewind/forward buttons)
        slider_x = slider_start_x + 70
        slider_width = self.viz_width - 180
        self.frame_slider = UIHorizontalSlider(
            relative_rect=pygame.Rect((slider_x, controls_y + 10), (slider_width, 30)),
            start_value=0,
            value_range=(0, 100),
            manager=self.ui_manager,
            container=self
        )

        # Frame counter label
        label_x = slider_x + slider_width + 10
        self.frame_label = UILabel(
            relative_rect=pygame.Rect((label_x, controls_y + 5), (120, 40)),
            text='Frame: 0/0',
            manager=self.ui_manager,
            container=self,
            object_id=ObjectID(class_id='@pitchviz_label')
        )

    def _rebuild_pitch_list(self):
        """Rebuild the pitch list UI from filtered records."""
        # Clear existing items
        for btn in self.pitch_item_buttons:
            btn.kill()
        for label in self.pitch_item_labels:
            label.kill()
        self.pitch_item_buttons.clear()
        self.pitch_item_labels.clear()

        if not self.filtered_records:
            return

        # Calculate required height
        total_height = len(self.filtered_records) * self.PITCH_ITEM_HEIGHT

        # Set scrollable area size
        self.pitch_list_container.set_scrollable_area_dimensions(
            (self.PITCH_LIST_WIDTH - 20, max(total_height, self.pitch_list_container.get_container().get_size()[1]))
        )

        # Create items for each pitch
        for i, record in enumerate(self.filtered_records):
            y_pos = i * self.PITCH_ITEM_HEIGHT

            # Selection button (checkbox style)
            checkbox_text = 'X' if record.selected else ' '
            btn = UIButton(
                relative_rect=pygame.Rect((5, y_pos + 5), (30, 30)),
                text=checkbox_text,
                manager=self.ui_manager,
                container=self.pitch_list_container,
                object_id=ObjectID(object_id=f'#pitch_checkbox_{record.index}')
            )
            self.pitch_item_buttons.append(btn)

            # Pitch info label: "#N TYPE VEL"
            velocity_str = f"{record.velocity_mph:.0f}" if record.velocity_mph > 0 else "?"
            info_text = f"#{record.index + 1} {record.pitch_type} {velocity_str}mph"
            info_label = UILabel(
                relative_rect=pygame.Rect((40, y_pos + 2), (200, 25)),
                text=info_text,
                manager=self.ui_manager,
                container=self.pitch_list_container,
                object_id=ObjectID(class_id='@pitchviz_label')
            )
            self.pitch_item_labels.append(info_label)

            # Outcome label with color indicator
            outcome_label = UILabel(
                relative_rect=pygame.Rect((40, y_pos + 25), (200, 25)),
                text=record.outcome,
                manager=self.ui_manager,
                container=self.pitch_list_container,
                object_id=ObjectID(class_id='@pitchviz_label')
            )
            self.pitch_item_labels.append(outcome_label)

    def _apply_filter(self, filter_type: str):
        """Apply pitch type filter to the list."""
        self.current_filter = filter_type

        if filter_type == 'All':
            self.filtered_records = self.pitch_records.copy()
        else:
            self.filtered_records = [
                r for r in self.pitch_records
                if r.pitch_type.upper().startswith(filter_type.upper())
            ]

        self._rebuild_pitch_list()
        self._update_selected_records()

    def _update_selected_records(self):
        """Update the list of selected records and redraw."""
        self.selected_records = [r for r in self.pitch_records if r.selected]

        # Update slider range based on selected trajectories
        max_frames = max((len(r.trajectory) for r in self.selected_records if r.trajectory), default=1)
        new_max = max(1, max_frames - 1)
        self.frame_slider.value_range = (0, new_max)

        # Clamp animation frame to valid range
        self.animation_frame = min(self.animation_frame, new_max)
        self.frame_slider.set_current_value(self.animation_frame)

        self._draw_visualization()

    def _toggle_pitch_selection(self, pitch_index: int):
        """Toggle selection state for a pitch by its index."""
        for record in self.pitch_records:
            if record.index == pitch_index:
                record.selected = not record.selected
                break

        self._rebuild_pitch_list()
        self._update_selected_records()

    def _select_all_filtered(self):
        """Select all pitches in current filter."""
        for record in self.filtered_records:
            record.selected = True
        self._rebuild_pitch_list()
        self._update_selected_records()

    def _clear_all_selections(self):
        """Clear all pitch selections."""
        for record in self.pitch_records:
            record.selected = False
        self._rebuild_pitch_list()
        self._update_selected_records()

    def _draw_visualization(self):
        """Draw the visualization with selected pitch trajectories overlaid."""
        surface = pygame.Surface(self.viz_surface_size, pygame.SRCALPHA)
        surface.fill((0, 0, 0, 255))

        # Draw strike zone
        pygame.draw.rect(surface, (255, 255, 255), self.strikezone, 1)

        # Draw home plate
        plate_x = self.viz_width // 2 - 65
        plate_y = self.viz_height - 60
        pygame.draw.polygon(surface, (255, 255, 255),
                           ((plate_x, plate_y), (plate_x + 130, plate_y),
                            (plate_x + 130, plate_y + 10), (plate_x + 65, plate_y + 25),
                            (plate_x, plate_y + 10)), 0)

        # Calculate coordinate offset for trajectory rendering
        # Game strike zone: top-left (565, 410), size 130x150, center (630, 485)
        # Viz strike zone: centered at (viz_width/2, viz_height/2)
        # Offset aligns game center to viz center
        game_strikezone_center_x = 630  # 565 + 65
        game_strikezone_center_y = 485  # 410 + 75
        x_offset = game_strikezone_center_x - (self.viz_width // 2)
        y_offset = game_strikezone_center_y - (self.viz_height // 2)

        # Get max frame count for animation
        max_frames = 0
        for record in self.selected_records:
            if record.trajectory:
                max_frames = max(max_frames, len(record.trajectory))

        # Draw each selected trajectory with transparency
        if self.selected_records:
            # Calculate alpha based on number of selected trajectories
            num_selected = len(self.selected_records)
            alpha = max(80, min(200, 255 // max(1, num_selected)))

            for record in self.selected_records:
                trajectory = record.trajectory
                if not trajectory:
                    continue

                color = record.get_display_color()
                color_with_alpha = (*color, alpha)

                # Draw trajectory up to current frame
                frame_limit = min(self.animation_frame + 1, len(trajectory))

                for i in range(frame_limit):
                    frame = trajectory[i]
                    x_pos = int(frame[0]) - x_offset
                    y_pos = int(frame[1]) - y_offset
                    size = max(4, int(frame[2])) if len(frame) > 2 else 8

                    # Draw ball at this frame position
                    pygame.draw.circle(surface, color_with_alpha, (x_pos, y_pos), size // 2)

                # Draw final position marker with ring outline
                if frame_limit > 0:
                    final_idx = min(frame_limit - 1, len(trajectory) - 1)
                    final = trajectory[final_idx]
                    x_pos = int(final[0]) - x_offset
                    y_pos = int(final[1]) - y_offset
                    pygame.draw.circle(surface, (*color, 255), (x_pos, y_pos), 8, 2)

        # Update frame label
        self.frame_label.set_text(f'Frame: {self.animation_frame}/{max_frames}')

        # Update the image element
        self.viz_surface_element.set_image(surface)

    def process_event(self, event):
        """Process UI events for the window."""
        handled = super().process_event(event)

        if event.type == pygame_gui.UI_BUTTON_PRESSED:
            # Check filter buttons
            for filter_type, btn in self.filter_buttons.items():
                if event.ui_element == btn:
                    self._apply_filter(filter_type)
                    return True

            # Check pitch selection checkboxes
            for i, btn in enumerate(self.pitch_item_buttons):
                if event.ui_element == btn:
                    if i < len(self.filtered_records):
                        pitch_index = self.filtered_records[i].index
                        self._toggle_pitch_selection(pitch_index)
                    return True

            # Play/Pause button
            if event.ui_element == self.play_pause_btn:
                self.animation_playing = not self.animation_playing
                self.play_pause_btn.set_text('Play' if not self.animation_playing else 'Pause')
                return True

            # Select all / clear
            if event.ui_element == self.select_all_btn:
                self._select_all_filtered()
                return True

            if event.ui_element == self.clear_btn:
                self._clear_all_selections()
                return True

        # Handle slider movement
        if event.type == pygame_gui.UI_HORIZONTAL_SLIDER_MOVED:
            if event.ui_element == self.frame_slider:
                self.animation_frame = int(self.frame_slider.get_current_value())
                self.animation_playing = False
                self.play_pause_btn.set_text('Play')
                self._draw_visualization()
                return True

        return handled

    def on_close_window_button_pressed(self):
        """Handle window close button."""
        return super().hide()

    def _migrate_legacy_data(self):
        """Convert legacy trajectory data to enhanced records."""
        self.pitch_records.clear()

        for i, trajectory in enumerate(self.pitch_trajectories):
            if trajectory:
                # Extract outcome from last frame status
                last_frame = trajectory[-1] if trajectory else [0, 0, 0, (255, 255, 255), '']
                status = last_frame[4] if len(last_frame) > 4 else ''
                outcome = status.upper() if status else 'UNKNOWN'

                record = EnhancedPitchRecord(
                    trajectory=trajectory,
                    pitch_type='UNK',  # Unknown for legacy data
                    velocity_mph=0.0,
                    outcome=outcome,
                    final_location=(last_frame[0], last_frame[1]),
                    index=i,
                    selected=False
                )
                self.pitch_records.append(record)

        self.filtered_records = self.pitch_records.copy()
        self._rebuild_pitch_list()

    def update_pitch_info_enhanced(self, enhanced_records: List[EnhancedPitchRecord]):
        """Update with enhanced pitch record data."""
        self.pitch_records = enhanced_records.copy()
        self.filtered_records = enhanced_records.copy()
        self._apply_filter(self.current_filter)
        self._rebuild_pitch_list()
        self.animation_frame = 0

    def update_pitch_info(self, pitch_trajectories, last_pitch_information):
        """Legacy update method for backward compatibility."""
        self.pitch_trajectories = pitch_trajectories
        self.last_pitch_information = last_pitch_information
        self._migrate_legacy_data()

    def set_display_fps(self, fps):
        """Set the display FPS for animation timing."""
        self.display_fps = fps

    def update(self, time_delta):
        """Update animation state."""
        current_time = pygame.time.get_ticks()

        # Calculate max frames from selected trajectories
        max_frames = max((len(r.trajectory) for r in self.selected_records if r.trajectory), default=1)

        # Update slider range if it changed
        current_range = self.frame_slider.value_range
        new_max = max(1, max_frames - 1)
        if current_range[1] != new_max:
            self.frame_slider.value_range = (0, new_max)

        # Scale animation interval based on display FPS (base: 20ms at 60 FPS)
        frame_interval = 1200 / self.display_fps  # 20ms at 60 FPS, 10ms at 120 FPS

        if self.animation_playing and self.selected_records:
            if current_time - self.last_time > frame_interval:
                self.animation_frame += 1
                self.last_time = current_time

                if max_frames > 0:
                    self.animation_frame %= max_frames

                # Sync slider to current frame
                self.frame_slider.set_current_value(self.animation_frame)
                self._draw_visualization()

        # Also update legacy x counter for compatibility
        if len(self.last_pitch_information) > 0:
            self.x = self.animation_frame % len(self.last_pitch_information)

        super().update(time_delta)

# Asset class to store all assets (images, sounds, etc.)
class AssetEngine:
    def __init__(self):
        self.images = {}
        self.sounds = {}

    def load_image(self, path):
        if path not in self.images:
            self.images[path] = pygame.image.load(path)
        return self.images[path]

    def load_sound(self, path):
        if path not in self.sounds:
            self.sounds[path] = pygame.mixer.Sound(path)
        return self.sounds[path]

class StateEngine:
    def __init__(self):
        self.states = {}

    def add_state(self, name, state):
        self.states[name] = state

    def get_state(self, name):
        return self.states[name]

    def remove_state(self, name):
        del self.states[name]

    def clear_states(self):
        self.states = {}

class GUImanager:
    pass

class PitchDataManager:

    def __init__(self):
        self.records = []

    def insert_row(self, row):
        self.records.append(row)

    def append_to_file(self, file):
        pd.DataFrame(self.records).to_csv(file, mode='a', header=False, index=False)
        print("Data appended to file")

class Ball:
    def __init__(self, images, screen):
        self.true_x = 0
        self.true_y = 0
        self.true_z = 0
        self.size = 0
        self.images = images
        self.screen = screen
        self.projected_x = 0
        self.projected_y = 0
        self.scale = 0

    def set_position(self, x, y, z):
        self.true_x = x
        self.true_y = y
        self.true_z = z
        self.counter = 0

    def set_z(self, z):
        self.true_z = z

    def set_size(self, size):
        self.size = size

    def print_position(self):
        print(f"X: {self.true_x}, Y: {self.true_y}, Z: {self.true_z}")

    def draw(self):
        image = pygame.transform.scale(self.images[self.counter], (self.size, self.size))
        self.screen.blit(image, (self.x, self.y))
        self.counter = (self.counter + 1) % len(self.images)
        return 
    
    def draw_with_pos(self, x, y, size):
        ratio = size / 64
        image = pygame.transform.scale(self.images[self.counter], (int(ratio * 64), int(ratio * 66)))
        self.screen.blit(image, (x  - (29.22 * ratio), y - (32.62 * ratio)))
        self.counter = (self.counter + 1) % len(self.images)
        return
    
    def update_projection_details(self, x, y, scale):
        self.projected_x = x
        self.projected_y = y
        self.scale = scale
    
    def blit_ball_outline(self):
        pygame.gfxdraw.aacircle(self.screen, int(self.projected_x), int(self.projected_y), 11, (255, 255, 255))

    