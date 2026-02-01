"""Lap Log Panel - displays lap history during gameplay."""

import pygame
import pygame_gui
from pygame_gui.elements import UIPanel, UILabel, UIButton
from pygame_gui.elements.ui_scrolling_container import UIScrollingContainer
from pygame_gui.core import ObjectID
from datetime import datetime


class LapLogPanel(UIPanel):
    """Panel for viewing lap history with scrollable list."""

    PANEL_WIDTH = 350
    PANEL_HEIGHT = 400
    LAP_ITEM_HEIGHT = 80
    CURRENT_SESSION_HEIGHT = 95  # Slightly taller for current session

    def __init__(self, position, manager, container=None):
        super().__init__(
            relative_rect=pygame.Rect(position, (self.PANEL_WIDTH, self.PANEL_HEIGHT)),
            manager=manager,
            container=container,
            starting_height=2,
            object_id=ObjectID(object_id='#lap_log_panel')
        )

        self.lap_data = []
        self.current_stats = None  # Current session stats
        self.lap_item_labels = []
        self._create_layout()

    def _create_layout(self):
        """Create the panel layout."""
        y_offset = 5

        # Title
        self.title_label = UILabel(
            relative_rect=pygame.Rect((5, y_offset), (self.PANEL_WIDTH - 10, 25)),
            text='LAP HISTORY',
            manager=self.ui_manager,
            container=self,
            object_id=ObjectID(class_id='@pitchviz_label')
        )
        y_offset += 30

        # Scrollable container for lap entries
        scroll_height = self.PANEL_HEIGHT - 80
        self.scroll_container = UIScrollingContainer(
            relative_rect=pygame.Rect((5, y_offset), (self.PANEL_WIDTH - 10, scroll_height)),
            manager=self.ui_manager,
            container=self,
            allow_scroll_x=False
        )

        # Close button at bottom
        self.close_btn = UIButton(
            relative_rect=pygame.Rect((self.PANEL_WIDTH // 2 - 50, self.PANEL_HEIGHT - 40), (100, 35)),
            text='CLOSE',
            manager=self.ui_manager,
            container=self,
            object_id=ObjectID(class_id='@sandbox_button')
        )

    def update_data(self, laps: list, current_stats: dict = None):
        """Update panel with lap history data and current session stats.

        Args:
            laps: List of lap history entries
            current_stats: Current session stats dict with keys:
                - total_pitches, total_swings, total_hits, total_at_bats, batting_average
        """
        self.lap_data = laps
        self.current_stats = current_stats
        self._rebuild_lap_list()

    def _rebuild_lap_list(self):
        """Rebuild the lap list UI."""
        # Clear existing labels
        for label in self.lap_item_labels:
            label.kill()
        self.lap_item_labels.clear()

        y_pos = 0

        # Show current session stats first
        if self.current_stats:
            y_pos = self._add_current_session_entry(y_pos)

        # Show lap history (most recent first)
        if self.lap_data:
            for lap in reversed(self.lap_data):
                y_pos = self._add_lap_entry(lap, y_pos)

        # If no data at all, show message
        if not self.current_stats and not self.lap_data:
            no_data_label = UILabel(
                relative_rect=pygame.Rect((5, 10), (self.PANEL_WIDTH - 30, 25)),
                text='No stats recorded yet',
                manager=self.ui_manager,
                container=self.scroll_container,
                object_id=ObjectID(class_id='@pitchviz_label')
            )
            self.lap_item_labels.append(no_data_label)
            return

        # Calculate scrollable area
        scroll_container_height = self.scroll_container.get_container().get_size()[1]
        self.scroll_container.set_scrollable_area_dimensions(
            (self.PANEL_WIDTH - 30, max(y_pos, scroll_container_height))
        )

    def _add_current_session_entry(self, y_pos: int) -> int:
        """Add current session stats entry at the given y position.

        Returns:
            int: The new y position after this entry
        """
        # Header: CURRENT SESSION
        header_label = UILabel(
            relative_rect=pygame.Rect((5, y_pos), (self.PANEL_WIDTH - 30, 20)),
            text=">> CURRENT SESSION <<",
            manager=self.ui_manager,
            container=self.scroll_container,
            object_id=ObjectID(class_id='@pitchviz_label')
        )
        self.lap_item_labels.append(header_label)

        # Stats line 1: BA and Hits
        ba = self.current_stats.get('batting_average', 0)
        hits = self.current_stats.get('total_hits', 0)
        at_bats = self.current_stats.get('total_at_bats', 0)
        stats1_label = UILabel(
            relative_rect=pygame.Rect((5, y_pos + 22), (self.PANEL_WIDTH - 30, 18)),
            text=f"BA: {ba:.3f}  |  H: {hits}  |  AB: {at_bats}",
            manager=self.ui_manager,
            container=self.scroll_container,
            object_id=ObjectID(class_id='@pitchviz_label')
        )
        self.lap_item_labels.append(stats1_label)

        # Stats line 2: Pitches and Swings
        pitches = self.current_stats.get('total_pitches', 0)
        swings = self.current_stats.get('total_swings', 0)
        stats2_label = UILabel(
            relative_rect=pygame.Rect((5, y_pos + 42), (self.PANEL_WIDTH - 30, 18)),
            text=f"Pitches: {pitches}  |  Swings: {swings}",
            manager=self.ui_manager,
            container=self.scroll_container,
            object_id=ObjectID(class_id='@pitchviz_label')
        )
        self.lap_item_labels.append(stats2_label)

        # Tip to save
        tip_label = UILabel(
            relative_rect=pygame.Rect((5, y_pos + 62), (self.PANEL_WIDTH - 30, 18)),
            text="(Press LAP to save)",
            manager=self.ui_manager,
            container=self.scroll_container,
            object_id=ObjectID(class_id='@pitchviz_label')
        )
        self.lap_item_labels.append(tip_label)

        # Separator (empty spacer to avoid text width warnings)
        sep_label = UILabel(
            relative_rect=pygame.Rect((5, y_pos + 80), (self.PANEL_WIDTH - 30, 15)),
            text='',
            manager=self.ui_manager,
            container=self.scroll_container,
            object_id=ObjectID(class_id='@pitchviz_label')
        )
        self.lap_item_labels.append(sep_label)

        return y_pos + self.CURRENT_SESSION_HEIGHT

    def _add_lap_entry(self, lap: dict, y_pos: int) -> int:
        """Add a lap entry at the given y position.

        Returns:
            int: The new y position after this entry
        """
        # Lap number and timestamp
        timestamp = lap.get('timestamp', '')
        try:
            dt = datetime.fromisoformat(timestamp)
            time_str = dt.strftime('%m/%d %H:%M')
        except (ValueError, TypeError):
            time_str = 'Unknown'

        header_label = UILabel(
            relative_rect=pygame.Rect((5, y_pos), (self.PANEL_WIDTH - 30, 20)),
            text=f"Lap {lap.get('lap_number', '?')} - {time_str}",
            manager=self.ui_manager,
            container=self.scroll_container,
            object_id=ObjectID(class_id='@pitchviz_label')
        )
        self.lap_item_labels.append(header_label)

        # Stats line 1: BA and Hits
        ba = lap.get('batting_average', 0)
        hits = lap.get('total_hits', 0)
        at_bats = lap.get('total_at_bats', 0)
        stats1_label = UILabel(
            relative_rect=pygame.Rect((5, y_pos + 22), (self.PANEL_WIDTH - 30, 18)),
            text=f"BA: {ba:.3f}  |  H: {hits}  |  AB: {at_bats}",
            manager=self.ui_manager,
            container=self.scroll_container,
            object_id=ObjectID(class_id='@pitchviz_label')
        )
        self.lap_item_labels.append(stats1_label)

        # Stats line 2: Pitches and Swings
        pitches = lap.get('total_pitches', 0)
        swings = lap.get('total_swings', 0)
        stats2_label = UILabel(
            relative_rect=pygame.Rect((5, y_pos + 42), (self.PANEL_WIDTH - 30, 18)),
            text=f"Pitches: {pitches}  |  Swings: {swings}",
            manager=self.ui_manager,
            container=self.scroll_container,
            object_id=ObjectID(class_id='@pitchviz_label')
        )
        self.lap_item_labels.append(stats2_label)

        # Separator line (empty spacer to avoid text width warnings)
        sep_label = UILabel(
            relative_rect=pygame.Rect((5, y_pos + 62), (self.PANEL_WIDTH - 30, 15)),
            text='',
            manager=self.ui_manager,
            container=self.scroll_container,
            object_id=ObjectID(class_id='@pitchviz_label')
        )
        self.lap_item_labels.append(sep_label)

        return y_pos + self.LAP_ITEM_HEIGHT

    def get_close_button(self):
        """Return the close button for event handling."""
        return self.close_btn

    def toggle(self):
        """Toggle panel visibility."""
        if self.visible:
            self.hide()
        else:
            self.show()
