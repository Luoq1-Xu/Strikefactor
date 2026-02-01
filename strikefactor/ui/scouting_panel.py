"""Scouting Report Panel - displays pitcher stats and arsenal during gameplay."""

import pygame
import pygame_gui
from pygame_gui.elements import UIPanel, UILabel
from pygame_gui.core import ObjectID


# Pitch type full names
PITCH_NAMES = {
    'FF': 'Fastball',
    'SI': 'Sinker',
    'FC': 'Cutter',
    'SL': 'Slider',
    'CB': 'Curveball',
    'CU': 'Curveball',
    'CH': 'Changeup',
    'FS': 'Splitter',
    'KC': 'Knuckle Curve'
}

# Average pitch velocities by type (MPH)
PITCH_VELOCITIES = {
    'FF': '93-99',
    'SI': '91-95',
    'FC': '87-92',
    'SL': '79-85',
    'CB': '73-81',
    'CU': '73-81',
    'CH': '83-89',
    'FS': '85-90',
    'KC': '75-82'
}

# Color constants for stat quality (RGB tuples for pygame)
COLOR_GREEN = (46, 204, 113)   # Good stat
COLOR_YELLOW = (241, 196, 15)  # Average stat
COLOR_RED = (231, 76, 60)      # Poor stat
COLOR_WHITE = (255, 255, 255)
COLOR_GRAY = (150, 150, 150)


class ScoutingReportPanel(UIPanel):
    """Persistent overlay panel showing pitcher scouting information."""

    PANEL_WIDTH = 250  # Match scoreboard width
    PANEL_HEIGHT = 200  # Match scoreboard height

    def __init__(self, position, manager, container=None):
        super().__init__(
            relative_rect=pygame.Rect(position, (self.PANEL_WIDTH, self.PANEL_HEIGHT)),
            manager=manager,
            container=container,
            starting_height=1,
            object_id=ObjectID(object_id='#scouting_panel')
        )

        self.pitcher_ref = None
        self.stat_labels = {}
        self.arsenal_labels = []
        self._create_layout()

    def _create_layout(self):
        """Create the panel layout with labels for each section."""
        y_offset = 3

        # Pitcher name and pitch count row (acts as title)
        self.name_label = UILabel(
            relative_rect=pygame.Rect((5, y_offset), (self.PANEL_WIDTH - 10, 18)),
            text='SCOUTING REPORT',
            manager=self.ui_manager,
            container=self,
            object_id=ObjectID(class_id='@pitchviz_label')
        )
        y_offset += 20

        # Create stat rows: K/9, BB/9, Strike%, WHIP (compact, 2 per row)
        # Row 1: K/9 and BB/9
        UILabel(
            relative_rect=pygame.Rect((5, y_offset), (55, 16)),
            text='K/9:',
            manager=self.ui_manager,
            container=self,
            object_id=ObjectID(class_id='@pitchviz_label')
        )
        self.stat_labels['K/9'] = UILabel(
            relative_rect=pygame.Rect((60, y_offset), (60, 16)),
            text='--',
            manager=self.ui_manager,
            container=self,
            object_id=ObjectID(class_id='@pitchviz_label')
        )
        UILabel(
            relative_rect=pygame.Rect((125, y_offset), (55, 16)),
            text='BB/9:',
            manager=self.ui_manager,
            container=self,
            object_id=ObjectID(class_id='@pitchviz_label')
        )
        self.stat_labels['BB/9'] = UILabel(
            relative_rect=pygame.Rect((180, y_offset), (60, 16)),
            text='--',
            manager=self.ui_manager,
            container=self,
            object_id=ObjectID(class_id='@pitchviz_label')
        )
        y_offset += 18

        # Row 2: Strike% and WHIP
        UILabel(
            relative_rect=pygame.Rect((5, y_offset), (55, 16)),
            text='STR%:',
            manager=self.ui_manager,
            container=self,
            object_id=ObjectID(class_id='@pitchviz_label')
        )
        self.stat_labels['Strike%'] = UILabel(
            relative_rect=pygame.Rect((60, y_offset), (60, 16)),
            text='--',
            manager=self.ui_manager,
            container=self,
            object_id=ObjectID(class_id='@pitchviz_label')
        )
        UILabel(
            relative_rect=pygame.Rect((125, y_offset), (55, 16)),
            text='WHIP:',
            manager=self.ui_manager,
            container=self,
            object_id=ObjectID(class_id='@pitchviz_label')
        )
        self.stat_labels['WHIP'] = UILabel(
            relative_rect=pygame.Rect((180, y_offset), (60, 16)),
            text='--',
            manager=self.ui_manager,
            container=self,
            object_id=ObjectID(class_id='@pitchviz_label')
        )
        y_offset += 20

        # Separator (empty spacer to avoid text width warnings)
        UILabel(
            relative_rect=pygame.Rect((5, y_offset), (self.PANEL_WIDTH - 10, 14)),
            text='',
            manager=self.ui_manager,
            container=self,
            object_id=ObjectID(class_id='@pitchviz_label')
        )
        y_offset += 16

        # Arsenal section header
        UILabel(
            relative_rect=pygame.Rect((5, y_offset), (80, 16)),
            text='ARSENAL',
            manager=self.ui_manager,
            container=self,
            object_id=ObjectID(class_id='@pitchviz_label')
        )
        y_offset += 18

        # Arsenal rows (max 5 pitches, compact)
        for i in range(5):
            arsenal_label = UILabel(
                relative_rect=pygame.Rect((5, y_offset + i * 16), (self.PANEL_WIDTH - 10, 16)),
                text='',
                manager=self.ui_manager,
                container=self,
                object_id=ObjectID(class_id='@pitchviz_label')
            )
            self.arsenal_labels.append(arsenal_label)

    def update_data(self, pitcher):
        """Update panel with new pitcher data."""
        self.pitcher_ref = pitcher
        self.refresh_stats()

    def refresh_stats(self):
        """Refresh displayed stats from pitcher reference."""
        if not self.pitcher_ref:
            return

        pitcher = self.pitcher_ref

        # Update pitcher name with pitch count
        pitch_count = pitcher.basic_stats.get('pitch_count', 0)
        # Truncate name if too long
        name = pitcher.name if len(pitcher.name) <= 14 else pitcher.name[:12] + '..'
        self.name_label.set_text(f'{name} [{pitch_count}P]')

        # Calculate stats
        k9 = pitcher._calculate_k9()
        bb9 = pitcher._calculate_bb9()
        strike_pct = pitcher._calculate_strike_pct()
        whip = pitcher._calculate_whip()

        # Update stat labels with color-coded values
        self._update_stat_label('K/9', k9, self._get_k9_color(k9))
        self._update_stat_label('BB/9', bb9, self._get_bb9_color(bb9))
        self._update_stat_label('Strike%', strike_pct, self._get_strike_pct_color(strike_pct), suffix='%')
        self._update_stat_label('WHIP', whip, self._get_whip_color(whip))

        # Update arsenal (compact format)
        pitch_names = pitcher.get_pitch_names()
        for i, label in enumerate(self.arsenal_labels):
            if i < len(pitch_names):
                pitch_code = pitch_names[i]
                full_name = PITCH_NAMES.get(pitch_code, pitch_code)
                velocity = PITCH_VELOCITIES.get(pitch_code, '??')
                label.set_text(f'{pitch_code} {full_name} {velocity}')
            else:
                label.set_text('')

    def _update_stat_label(self, stat_name, value, color, suffix=''):
        """Update a stat label with formatted value and color indicator."""
        if stat_name in self.stat_labels:
            # Format value
            if value is None or value == 0:
                formatted = '--'
                color_indicator = ''
            else:
                formatted = f'{value:.2f}{suffix}'
                # Add color indicator symbol
                if color == COLOR_GREEN:
                    color_indicator = ' [+]'
                elif color == COLOR_YELLOW:
                    color_indicator = ' [=]'
                else:
                    color_indicator = ' [-]'

            self.stat_labels[stat_name].set_text(f'{formatted}{color_indicator}')

    def _get_k9_color(self, k9):
        """Get color for K/9 based on thresholds."""
        if k9 >= 9.0:
            return COLOR_GREEN
        elif k9 >= 6.0:
            return COLOR_YELLOW
        else:
            return COLOR_RED

    def _get_bb9_color(self, bb9):
        """Get color for BB/9 based on thresholds (lower is better)."""
        if bb9 <= 2.5:
            return COLOR_GREEN
        elif bb9 <= 4.0:
            return COLOR_YELLOW
        else:
            return COLOR_RED

    def _get_strike_pct_color(self, pct):
        """Get color for strike percentage."""
        if pct >= 65:
            return COLOR_GREEN
        elif pct >= 55:
            return COLOR_YELLOW
        else:
            return COLOR_RED

    def _get_whip_color(self, whip):
        """Get color for WHIP (lower is better)."""
        if whip <= 1.10:
            return COLOR_GREEN
        elif whip <= 1.35:
            return COLOR_YELLOW
        else:
            return COLOR_RED

    def toggle(self):
        """Toggle panel visibility."""
        if self.visible:
            self.hide()
        else:
            self.show()
