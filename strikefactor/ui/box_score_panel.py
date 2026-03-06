"""Box Score Panel - retro-styled inning-by-inning scoreboard for GameDay mode."""

import pygame
import pygame_gui
from pygame_gui.elements import UIPanel, UILabel
from pygame_gui.core import ObjectID


# Column layout constants
TEAM_COL_WIDTH = 80    # Width for team name column
INNING_COL_WIDTH = 30  # Width for each inning column
SEP_COL_WIDTH = 10     # Width for the separator "|"
TOTAL_COL_WIDTH = 30   # Width for the "R" (runs total) column
ROW_HEIGHT = 22        # Height per row
PADDING = 6            # Internal padding

NUM_INNINGS = 9
PANEL_WIDTH = (TEAM_COL_WIDTH + INNING_COL_WIDTH * NUM_INNINGS
               + SEP_COL_WIDTH + TOTAL_COL_WIDTH + PADDING * 2)
PANEL_HEIGHT = ROW_HEIGHT * 3 + PADDING * 2  # header + 2 team rows


class BoxScorePanel(UIPanel):
    """Retro-styled box score panel showing inning-by-inning scores."""

    def __init__(self, position, manager, container=None):
        super().__init__(
            relative_rect=pygame.Rect(position, (PANEL_WIDTH, PANEL_HEIGHT)),
            manager=manager,
            container=container,
            starting_height=2,
            object_id=ObjectID(class_id='@box_score_panel')
        )

        self.header_labels = []
        self.opp_labels = []
        self.plr_labels = []
        self.opp_name_label = None
        self.plr_name_label = None
        self.opp_total_label = None
        self.plr_total_label = None
        self._current_inning = None

        self._create_layout()

    def _create_layout(self):
        """Build the grid of labels inside the panel."""
        x_start = PADDING
        y = PADDING

        # --- Header row: blank + 1..9 + "|" + R ---
        # Blank cell for team name column
        UILabel(
            relative_rect=pygame.Rect((x_start, y), (TEAM_COL_WIDTH, ROW_HEIGHT)),
            text='',
            manager=self.ui_manager,
            container=self,
            object_id=ObjectID(class_id='@box_score_header')
        )

        x = x_start + TEAM_COL_WIDTH
        for i in range(1, NUM_INNINGS + 1):
            lbl = UILabel(
                relative_rect=pygame.Rect((x, y), (INNING_COL_WIDTH, ROW_HEIGHT)),
                text=str(i),
                manager=self.ui_manager,
                container=self,
                object_id=ObjectID(class_id='@box_score_header')
            )
            self.header_labels.append(lbl)
            x += INNING_COL_WIDTH

        # Separator
        UILabel(
            relative_rect=pygame.Rect((x, y), (SEP_COL_WIDTH, ROW_HEIGHT)),
            text='|',
            manager=self.ui_manager,
            container=self,
            object_id=ObjectID(class_id='@box_score_header')
        )
        x += SEP_COL_WIDTH

        # "R" header
        UILabel(
            relative_rect=pygame.Rect((x, y), (TOTAL_COL_WIDTH, ROW_HEIGHT)),
            text='R',
            manager=self.ui_manager,
            container=self,
            object_id=ObjectID(class_id='@box_score_header')
        )

        # --- Opponent row ---
        y += ROW_HEIGHT
        x = x_start

        self.opp_name_label = UILabel(
            relative_rect=pygame.Rect((x, y), (TEAM_COL_WIDTH, ROW_HEIGHT)),
            text='OPP',
            manager=self.ui_manager,
            container=self,
            object_id=ObjectID(class_id='@box_score_opp')
        )
        x += TEAM_COL_WIDTH

        for _ in range(NUM_INNINGS):
            lbl = UILabel(
                relative_rect=pygame.Rect((x, y), (INNING_COL_WIDTH, ROW_HEIGHT)),
                text='0',
                manager=self.ui_manager,
                container=self,
                object_id=ObjectID(class_id='@box_score_opp')
            )
            self.opp_labels.append(lbl)
            x += INNING_COL_WIDTH

        # Separator
        UILabel(
            relative_rect=pygame.Rect((x, y), (SEP_COL_WIDTH, ROW_HEIGHT)),
            text='|',
            manager=self.ui_manager,
            container=self,
            object_id=ObjectID(class_id='@box_score_opp')
        )
        x += SEP_COL_WIDTH

        self.opp_total_label = UILabel(
            relative_rect=pygame.Rect((x, y), (TOTAL_COL_WIDTH, ROW_HEIGHT)),
            text='0',
            manager=self.ui_manager,
            container=self,
            object_id=ObjectID(class_id='@box_score_opp')
        )

        # --- Player row ---
        y += ROW_HEIGHT
        x = x_start

        self.plr_name_label = UILabel(
            relative_rect=pygame.Rect((x, y), (TEAM_COL_WIDTH, ROW_HEIGHT)),
            text='YOU',
            manager=self.ui_manager,
            container=self,
            object_id=ObjectID(class_id='@box_score_plr')
        )
        x += TEAM_COL_WIDTH

        for _ in range(NUM_INNINGS):
            lbl = UILabel(
                relative_rect=pygame.Rect((x, y), (INNING_COL_WIDTH, ROW_HEIGHT)),
                text='0',
                manager=self.ui_manager,
                container=self,
                object_id=ObjectID(class_id='@box_score_plr')
            )
            self.plr_labels.append(lbl)
            x += INNING_COL_WIDTH

        # Separator
        UILabel(
            relative_rect=pygame.Rect((x, y), (SEP_COL_WIDTH, ROW_HEIGHT)),
            text='|',
            manager=self.ui_manager,
            container=self,
            object_id=ObjectID(class_id='@box_score_plr')
        )
        x += SEP_COL_WIDTH

        self.plr_total_label = UILabel(
            relative_rect=pygame.Rect((x, y), (TOTAL_COL_WIDTH, ROW_HEIGHT)),
            text='0',
            manager=self.ui_manager,
            container=self,
            object_id=ObjectID(class_id='@box_score_plr')
        )

    def update_scores(self, box_data, current_inning=None):
        """Update all score labels from gameday_manager.get_box_score_lines() data.

        Args:
            box_data: dict with 'opponent', 'player' (lists of 9 ints),
                      'opponent_total', 'player_total'
            current_inning: 1-based inning number to highlight (or None)
        """
        self._current_inning = current_inning

        for i in range(NUM_INNINGS):
            self.opp_labels[i].set_text(str(box_data['opponent'][i]))
            self.plr_labels[i].set_text(str(box_data['player'][i]))

        self.opp_total_label.set_text(str(box_data['opponent_total']))
        self.plr_total_label.set_text(str(box_data['player_total']))

    def set_position(self, position):
        """Move the panel to a new position."""
        self.set_relative_position(position)
