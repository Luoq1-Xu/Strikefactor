import pygame
import pygame.gfxdraw
import colorsys
import json
import os
import shutil
from datetime import datetime
from utils.io import atomic_write_json


# Bucket key sentinel used until the Game tells us which (mode, difficulty)
# bucket is active. Pitches recorded under this key indicate the bucket
# wasn't initialized — should not happen in normal flow.
DEFAULT_BUCKET_KEY = "unknown|unknown"


def _fresh_bucket() -> dict:
    """Empty stats block used for a brand-new (mode, difficulty) bucket."""
    return {
        'heatmap_data': [0] * 9,
        'heatmap_attempts': [0] * 9,
        'total_swings': 0,
        'total_hits': 0,
        'total_pitches': 0,
        'total_at_bats': 0,
        'total_singles': 0,
        'total_doubles': 0,
        'total_triples': 0,
        'total_home_runs': 0,
        'total_walks': 0,
        'total_hbp': 0,
        'total_sacrifice_flies': 0,
    }


class FieldRenderer:
    """Renders the static components of the baseball field.

    Persists batting aggregates (heatmap + triple-slash counters) under
    `batting_stats.json`, partitioned by (game_mode, difficulty) so analytics
    can filter cleanly. The exposed instance attrs (heatmap_data, total_*)
    are live references to the active bucket so the existing record_*
    methods don't need to know about bucketing.
    """

    BUCKET_INT_FIELDS = (
        'total_swings', 'total_hits', 'total_pitches', 'total_at_bats',
        'total_singles', 'total_doubles', 'total_triples', 'total_home_runs',
        'total_walks', 'total_hbp', 'total_sacrifice_flies',
    )
    DATA_VERSION = '2.0'

    def __init__(self, screen, strikezone_rect=(565, 410, 130, 150)):
        """
        Initialize the field renderer.

        Args:
            screen: Pygame surface to draw on
            strikezone_rect: Rectangle defining the strike zone (x, y, width, height)
        """
        self.screen = screen
        self.strikezone = pygame.Rect(strikezone_rect)
        self.strikezonedrawn = 1  # 1: Hidden, 2: Outline only, 3: Grid, 4: Heatmap, 5: Heatmap with Averages
        self.show_bases = True  # Disabled in minimal HUD mode (the corner widget shows them).

        # Heatmap fonts are reused every frame the heatmap is active; build
        # them once here rather than reallocating a Font object per frame.
        self._heatmap_header_font = pygame.font.Font(None, 20)
        self._heatmap_avg_font = pygame.font.Font(None, 24)

        # Bucketed batting aggregates: { "mode|difficulty": fresh_bucket() }
        self._buckets: dict = {}
        # The bucket that record_* writes into. Game.set_active_bucket(mode,
        # difficulty) flips this when the user enters a new (mode, difficulty).
        self._active_key = DEFAULT_BUCKET_KEY
        # Optional rendering override: None = active bucket, "all" = sum of
        # all buckets, "{mode}|{difficulty}" = a specific bucket.
        self._view_override_key = None

        # Initialize the default bucket and bind instance attrs as live
        # references so existing record_* code mutates the bucket directly.
        self._buckets[DEFAULT_BUCKET_KEY] = _fresh_bucket()
        self._bind_instance_to_active()

        # Data file paths
        self.data_file = os.path.join(os.path.dirname(__file__), '..', 'data', 'batting_stats.json')
        self.legacy_archive_path = os.path.join(
            os.path.dirname(__file__), '..', 'data', 'batting_stats_legacy_v1.json'
        )

        # Lap history file path
        self.lap_history_file = os.path.join(os.path.dirname(__file__), '..', 'data', 'lap_history.json')
        self.lap_start_time = datetime.now()

        # Load existing data if available
        self.load_data()

    # ----------------- Bucket management -----------------

    @staticmethod
    def _key(game_mode: str, difficulty: str) -> str:
        return f"{game_mode}|{difficulty}"

    def _bind_instance_to_active(self):
        """Point self.heatmap_data / self.total_* at the active bucket."""
        b = self._buckets[self._active_key]
        # Lists: use the same reference so in-place mutations propagate.
        self.heatmap_data = b['heatmap_data']
        self.heatmap_attempts = b['heatmap_attempts']
        # Ints: assign a snapshot; _sync_ints_to_bucket() copies them back
        # before any save / bucket switch.
        for f in self.BUCKET_INT_FIELDS:
            setattr(self, f, b.get(f, 0))

    def _sync_ints_to_bucket(self):
        """Persist the int instance attrs back into the active bucket dict."""
        b = self._buckets[self._active_key]
        for f in self.BUCKET_INT_FIELDS:
            b[f] = int(getattr(self, f, 0))

    def set_active_bucket(self, game_mode: str, difficulty: str):
        """Switch the bucket that future record_* writes will land in.

        Called by Game when the user enters a new (mode, difficulty)
        combination. Safe to call repeatedly with the same args.
        """
        new_key = self._key(game_mode, difficulty)
        if new_key == self._active_key:
            return
        # Persist current attrs into the old bucket before swapping.
        self._sync_ints_to_bucket()
        # Initialize the destination bucket if it's new.
        self._buckets.setdefault(new_key, _fresh_bucket())
        self._active_key = new_key
        self._bind_instance_to_active()

    def get_active_bucket_key(self) -> str:
        return self._active_key

    def list_buckets(self) -> list:
        """Return the keys of all known buckets."""
        return list(self._buckets.keys())

    def set_view_override(self, key_or_mode: str = None, difficulty: str = None):
        """Set the bucket that the heatmap renders.

        - None: render the active bucket (default).
        - "all": render the sum across all buckets.
        - "{mode}|{difficulty}" or (mode, difficulty): render that bucket.
        """
        if key_or_mode is None:
            self._view_override_key = None
            return
        if difficulty is not None:
            self._view_override_key = self._key(key_or_mode, difficulty)
            return
        self._view_override_key = key_or_mode  # may be "all" or a key string

    def _render_view(self) -> dict:
        """Return the bucket dict that the heatmap should display."""
        if self._view_override_key is None:
            # Sync ints into the active bucket so the renderer sees current totals.
            self._sync_ints_to_bucket()
            return self._buckets[self._active_key]
        if self._view_override_key == "all":
            combined = _fresh_bucket()
            self._sync_ints_to_bucket()
            for b in self._buckets.values():
                for i in range(9):
                    combined['heatmap_data'][i] += b['heatmap_data'][i]
                    combined['heatmap_attempts'][i] += b['heatmap_attempts'][i]
                for f in self.BUCKET_INT_FIELDS:
                    combined[f] += b.get(f, 0)
            return combined
        return self._buckets.get(self._view_override_key, _fresh_bucket())

    # ----------------- Drawing -----------------

    def toggle_strikezone_mode(self):
        """Cycle through strike zone display modes."""
        self.strikezonedrawn = self.strikezonedrawn + 1 if self.strikezonedrawn < 5 else 1
        return self.strikezonedrawn

    def draw_strikezone(self):
        """Draw the strike zone based on current mode."""
        if self.strikezonedrawn == 1:
            # Hidden, don't draw
            return

        # Draw strike zone outline
        pygame.draw.rect(self.screen, "white", self.strikezone, 1)

        # Draw strike zone grid lines
        if self.strikezonedrawn == 3:
            x, y, width, height = self.strikezone

            # Horizontal dividing lines (divide into thirds)
            pygame.draw.line(self.screen, "white",
                            (x, y + (height/3)),
                            (x + width, y + (height/3)))
            pygame.draw.line(self.screen, "white",
                            (x, y + 2*(height/3)),
                            (x + width, y + 2*(height/3)))

            # Vertical dividing lines (divide into thirds)
            pygame.draw.line(self.screen, "white",
                            (x + (width/3), y),
                            (x + (width/3), y + height))
            pygame.draw.line(self.screen, "white",
                            (x + 2*(width/3), y),
                            (x + 2*(width/3), y + height))

        # Draw heatmap
        elif self.strikezonedrawn == 4:
            self._draw_heatmap()

        # Draw heatmap with batting averages
        elif self.strikezonedrawn == 5:
            self._draw_heatmap_with_averages()

    def draw_homeplate(self):
        """Draw the home plate."""
        x, y = 565, 660
        pygame.draw.polygon(self.screen, "white", [
            (x, y),                  # Top left
            (x + 130, y),            # Top right
            (x + 130, y + 10),       # Middle right
            (x + 65, y + 25),        # Bottom
            (x, y + 10)              # Middle left
        ], 0)

    def draw_bases(self, bases_status):
        """
        Draw the bases with their current status.

        Args:
            bases_status: List of colors for the bases ['white'/'yellow', ...]
        """
        # Draw first base (bottom right)
        pygame.draw.polygon(self.screen, bases_status[0], [
            (1115, 585), (1140, 610), (1115, 635), (1090, 610)
        ], 0 if bases_status[0] == 'yellow' else 1)

        # Draw second base (top)
        pygame.draw.polygon(self.screen, bases_status[1], [
            (1080, 550), (1105, 575), (1080, 600), (1055, 575)
        ], 0 if bases_status[1] == 'yellow' else 1)

        # Draw third base (bottom left)
        pygame.draw.polygon(self.screen, bases_status[2], [
            (1045, 585), (1070, 610), (1045, 635), (1020, 610)
        ], 0 if bases_status[2] == 'yellow' else 1)

    def draw_field(self, bases_status):
        """
        Draw all static field components.

        Args:
            bases_status: List of colors for the bases ['white'/'yellow', ...]
        """
        self.draw_strikezone()
        self.draw_homeplate()
        if self.show_bases:
            self.draw_bases(bases_status)

    def get_zone_segment(self, x, y):
        """
        Get the zone segment (0-8) for a given position.
        9 segments layout (including center):
        0  1  2
        3  4  5
        6  7  8
        """
        sx, sy, width, height = self.strikezone

        # Check if point is within strikezone
        if not (sx <= x <= sx + width and sy <= y <= sy + height):
            return -1  # Outside strikezone

        # Calculate relative position within strikezone (0.0 to 1.0)
        rel_x = (x - sx) / width
        rel_y = (y - sy) / height

        # Determine segment based on thirds, including center
        if rel_y <= 1/3:  # Top row
            if rel_x <= 1/3:
                return 0  # top_left
            elif rel_x <= 2/3:
                return 1  # top_center
            else:
                return 2  # top_right
        elif rel_y <= 2/3:  # Middle row (including center)
            if rel_x <= 1/3:
                return 3  # mid_left
            elif rel_x <= 2/3:
                return 4  # center
            else:
                return 5  # mid_right
        else:  # Bottom row
            if rel_x <= 1/3:
                return 6  # bot_left
            elif rel_x <= 2/3:
                return 7  # bot_center
            else:
                return 8  # bot_right

    def record_hit(self, x, y, hit_type=None):
        """
        Record a hit at the given position with type tracking.

        Args:
            x: X-coordinate of the hit
            y: Y-coordinate of the hit
            hit_type: Type of hit - can be 'SINGLE', 'DOUBLE', 'TRIPLE', 'HOME RUN' or numeric 1-4
        """
        segment = self.get_zone_segment(x, y)

        # Record heatmap data only if within strike zone (segment 0-8)
        if 0 <= segment <= 8:
            self.heatmap_data[segment] += 1

        # ALWAYS record the hit for overall batting statistics (regardless of zone)
        self.total_hits += 1

        # Track hit type breakdown
        if hit_type == 'SINGLE' or hit_type == 1:
            self.total_singles += 1
        elif hit_type == 'DOUBLE' or hit_type == 2:
            self.total_doubles += 1
        elif hit_type == 'TRIPLE' or hit_type == 3:
            self.total_triples += 1
        elif hit_type == 'HOME RUN' or hit_type == 4:
            self.total_home_runs += 1

        # Persist after each hit. Hits are infrequent (a few per game), so the
        # synchronous write is not a per-frame cost.
        self.save_data()

    def record_attempt(self, x, y):
        """Record an attempt (swing) at the given position."""
        segment = self.get_zone_segment(x, y)
        if 0 <= segment <= 8:
            self.heatmap_attempts[segment] += 1
            self.total_swings += 1

    def record_pitch(self):
        """Record that a pitch was thrown (for tracking total pitches)."""
        self.total_pitches += 1

    def record_walk(self):
        """
        Record a walk (base on balls).

        Note: Walks do NOT count as at-bats in baseball.
        """
        self.total_walks += 1

    def record_at_bat(self):
        """
        Record an official at-bat.

        In real baseball, at-bats include plate appearances that result in:
        - Hits (singles, doubles, triples, home runs)
        - Outs (flyouts, groundouts, lineouts, strikeouts)

        At-bats EXCLUDE:
        - Walks (base on balls)
        - Hit by pitch
        - Sacrifice flies/bunts
        - Catcher's interference
        """
        self.total_at_bats += 1

    def get_hit_rate(self, segment):
        """Get the hit rate for a segment (hits/attempts)."""
        view = self._render_view()
        attempts = view['heatmap_attempts'][segment]
        if attempts == 0:
            return 0.0
        return view['heatmap_data'][segment] / attempts

    def _get_heatmap_color(self, hit_rate):
        """Convert hit rate to a color (blue = cold/low, red = hot/high)."""
        if hit_rate == 0:
            return (80, 80, 80)  # Darker gray for no data

        # Normalize hit rate based on realistic baseball batting averages
        # Excellent: 0.400+ (red), Good: 0.300+ (orange/yellow), Average: 0.200+ (white), Poor: <0.200 (blue)
        # Scale the hit rate so that:
        # - 0.000-0.150 maps to blue (cold)
        # - 0.150-0.250 maps to white/neutral
        # - 0.250-0.350+ maps to red (hot)

        if hit_rate <= 0.150:
            # Poor performance - blue range
            intensity = hit_rate / 0.150  # 0 to 1
            hue = 240 / 360  # Blue hue
            saturation = 0.7 + intensity * 0.2  # More saturated for worse performance
            value = 0.5 + intensity * 0.3
        elif hit_rate <= 0.250:
            # Average performance - transition from blue to white
            progress = (hit_rate - 0.150) / 0.100  # 0 to 1
            hue = (240 - progress * 240) / 360  # Blue to neutral
            saturation = 0.7 - progress * 0.5  # Less saturated towards white
            value = 0.7 + progress * 0.2
        else:
            # Good to excellent performance - red range
            # Cap at 0.400 for scaling (anything above is exceptional)
            capped_rate = min(hit_rate, 0.400)
            progress = (capped_rate - 0.250) / 0.150  # 0 to 1
            hue = 0  # Red hue
            saturation = 0.6 + progress * 0.3  # More saturated for better performance
            value = 0.7 + progress * 0.3  # Brighter for better performance

        rgb = colorsys.hsv_to_rgb(hue, saturation, value)
        return (int(rgb[0] * 255), int(rgb[1] * 255), int(rgb[2] * 255))

    def _draw_heatmap(self):
        """Draw the batting heatmap."""
        x, y, width, height = self.strikezone

        # Calculate segment dimensions
        segment_width = width // 3
        segment_height = height // 3

        # Draw each segment with its color
        segments = [
            (0, 0, 0),      # top_left
            (1, 1, 0),      # top_center
            (2, 2, 0),      # top_right
            (3, 0, 1),      # mid_left
            (4, 1, 1),      # center
            (5, 2, 1),      # mid_right
            (6, 0, 2),      # bot_left
            (7, 1, 2),      # bot_center
            (8, 2, 2),      # bot_right
        ]

        for segment_id, col, row in segments:
            hit_rate = self.get_hit_rate(segment_id)
            color = self._get_heatmap_color(hit_rate)

            # Calculate segment rectangle
            seg_x = x + col * segment_width
            seg_y = y + row * segment_height

            # Fill the segment with the heatmap color
            segment_rect = pygame.Rect(seg_x, seg_y, segment_width, segment_height)
            pygame.draw.rect(self.screen, color, segment_rect)

            # Draw segment border
            pygame.draw.rect(self.screen, "white", segment_rect, 1)

        # Draw the overall strikezone border
        pygame.draw.rect(self.screen, "white", self.strikezone, 2)

        # Add a visual indicator that heatmap is active, including bucket label.
        label = self._heatmap_label()
        text = self._heatmap_header_font.render(f"HEATMAP — {label}", True, (255, 255, 255))
        self.screen.blit(text, (self.strikezone.x, self.strikezone.y - 26))

    def _draw_heatmap_with_averages(self):
        """Draw the batting heatmap with numerical averages displayed."""
        x, y, width, height = self.strikezone

        # Calculate segment dimensions
        segment_width = width // 3
        segment_height = height // 3

        # Draw each segment with its color and batting average text
        segments = [
            (0, 0, 0),      # top_left
            (1, 1, 0),      # top_center
            (2, 2, 0),      # top_right
            (3, 0, 1),      # mid_left
            (4, 1, 1),      # center
            (5, 2, 1),      # mid_right
            (6, 0, 2),      # bot_left
            (7, 1, 2),      # bot_center
            (8, 2, 2),      # bot_right
        ]

        # Font for displaying averages (cached in __init__)
        font = self._heatmap_avg_font
        view = self._render_view()

        for segment_id, col, row in segments:
            hit_rate = self.get_hit_rate(segment_id)
            color = self._get_heatmap_color(hit_rate)

            # Calculate segment rectangle
            seg_x = x + col * segment_width
            seg_y = y + row * segment_height

            # Fill the segment with the heatmap color
            segment_rect = pygame.Rect(seg_x, seg_y, segment_width, segment_height)
            pygame.draw.rect(self.screen, color, segment_rect)

            # Draw segment border
            pygame.draw.rect(self.screen, "white", segment_rect, 1)

            # Display batting average text in the center of each segment
            if view['heatmap_attempts'][segment_id] > 0:
                if hit_rate >= 1.0:
                    avg_text = f"{hit_rate:.2f}"
                else:
                    avg_text = f"{hit_rate:.3f}"[1:]
                    if len(avg_text) > 4:
                        avg_text = avg_text[:4]
            else:
                avg_text = "---"

            # Render text
            text_surface = font.render(avg_text, True, (255, 255, 255))
            text_rect = text_surface.get_rect()

            text_x = seg_x + (segment_width - text_rect.width) // 2
            text_y = seg_y + (segment_height - text_rect.height) // 2

            bg_rect = pygame.Rect(text_x - 2, text_y - 1, text_rect.width + 4, text_rect.height + 2)
            bg_surface = pygame.Surface((bg_rect.width, bg_rect.height))
            bg_surface.set_alpha(128)
            bg_surface.fill((0, 0, 0))
            self.screen.blit(bg_surface, bg_rect)

            self.screen.blit(text_surface, (text_x, text_y))

        pygame.draw.rect(self.screen, "white", self.strikezone, 2)

        label = self._heatmap_label()
        text = self._heatmap_header_font.render(f"HEATMAP + AVG — {label}", True, (255, 255, 255))
        self.screen.blit(text, (self.strikezone.x, self.strikezone.y - 26))

    def _heatmap_label(self) -> str:
        """Human-readable bucket label for the heatmap header."""
        if self._view_override_key == "all":
            return "ALL"
        key = self._view_override_key or self._active_key
        if "|" in key:
            mode, diff = key.split("|", 1)
            return f"{mode.upper()} / {diff.upper()}"
        return key.upper()

    def reset_heatmap_data(self):
        """Reset the active bucket's heatmap and counters."""
        b = self._buckets[self._active_key]
        b['heatmap_data'][:] = [0] * 9
        b['heatmap_attempts'][:] = [0] * 9
        for f in self.BUCKET_INT_FIELDS:
            b[f] = 0
        # Refresh instance attrs from the cleared bucket.
        self._bind_instance_to_active()
        self.save_data()

    # ----------------- Persistence -----------------

    def save_data(self):
        """Save bucketed batting statistics to file (atomically, so a crash
        mid-write can't truncate the file and lose all batting history)."""
        self._sync_ints_to_bucket()
        data = {
            'version': self.DATA_VERSION,
            'last_updated': datetime.now().isoformat(),
            'buckets': self._buckets,
        }
        atomic_write_json(self.data_file, data)

    def load_data(self):
        """Load bucketed stats. Migrate v1 (flat) to v2 by archiving + wiping."""
        try:
            if not os.path.exists(self.data_file):
                print("No saved batting statistics found. Starting fresh.")
                return

            with open(self.data_file, 'r') as f:
                data = json.load(f)

            version = str(data.get('version', '1.0'))
            if not version.startswith('2.'):
                # v1 schema: flat fields, no bucket partitioning.
                # Per user directive: archive the legacy file then wipe and
                # start fresh, so future analytics are mode/difficulty-aware.
                self._archive_legacy(data)
                # Discard legacy totals — start with an empty bucket for the
                # current active key (Game will set it shortly).
                self._buckets = {self._active_key: _fresh_bucket()}
                self._bind_instance_to_active()
                self.save_data()
                print("  Legacy v1 stats archived to batting_stats_legacy_v1.json; "
                      "going forward stats are partitioned by (game_mode, difficulty).")
                return

            # v2.x — load buckets directly. Coerce any missing fields to defaults.
            buckets = data.get('buckets', {})
            cleaned = {}
            for key, b in buckets.items():
                if not isinstance(b, dict):
                    continue
                fresh = _fresh_bucket()
                fresh['heatmap_data'] = list(b.get('heatmap_data', fresh['heatmap_data']))[:9]
                if len(fresh['heatmap_data']) < 9:
                    fresh['heatmap_data'] += [0] * (9 - len(fresh['heatmap_data']))
                fresh['heatmap_attempts'] = list(b.get('heatmap_attempts', fresh['heatmap_attempts']))[:9]
                if len(fresh['heatmap_attempts']) < 9:
                    fresh['heatmap_attempts'] += [0] * (9 - len(fresh['heatmap_attempts']))
                for f in self.BUCKET_INT_FIELDS:
                    fresh[f] = int(b.get(f, 0))
                cleaned[key] = fresh
            if not cleaned:
                cleaned[DEFAULT_BUCKET_KEY] = _fresh_bucket()
            self._buckets = cleaned
            # If the previous active key isn't in the loaded set, fall back to
            # the default sentinel (Game will set the real active soon).
            if self._active_key not in self._buckets:
                self._active_key = next(iter(self._buckets.keys()))
            self._bind_instance_to_active()
            print(f"✓ Batting statistics loaded from {self.data_file} "
                  f"({len(self._buckets)} bucket{'s' if len(self._buckets) != 1 else ''})")

        except Exception as e:
            print(f"✗ Error loading batting statistics: {e}")
            print("Starting with fresh data.")
            self._buckets = {self._active_key: _fresh_bucket()}
            self._bind_instance_to_active()

    def _archive_legacy(self, data: dict):
        """Copy the existing v1 file to *_legacy_v1.json verbatim."""
        try:
            # If the legacy archive already exists, append a numeric suffix
            # so we don't overwrite a previous archive.
            path = self.legacy_archive_path
            if os.path.exists(path):
                base, ext = os.path.splitext(path)
                i = 2
                while os.path.exists(f"{base}_{i}{ext}"):
                    i += 1
                path = f"{base}_{i}{ext}"
            # Prefer copying the original file to preserve formatting; fall
            # back to dumping the parsed dict if the file moved between
            # exists() and copy().
            try:
                shutil.copy2(self.data_file, path)
            except Exception:
                with open(path, 'w') as f:
                    json.dump(data, f, indent=2)
            print(f"  Archived legacy batting_stats.json to {path}")
        except Exception as e:
            print(f"  ⚠ Failed to archive legacy stats: {e}")

    # ----------------- Triple-slash helpers -----------------

    def get_overall_batting_average(self):
        """
        Get overall batting average across all zones.

        Batting average (BA) = Hits / At-Bats
        - Hits: singles, doubles, triples, home runs
        - At-Bats: excludes walks, hit-by-pitch, sacrifice flies/bunts
        """
        if self.total_at_bats == 0:
            return 0.0
        return self.total_hits / self.total_at_bats

    def get_on_base_percentage(self):
        """
        Calculate On-Base Percentage (OBP).

        OBP = (H + BB + HBP) / (AB + BB + HBP + SF)
        """
        numerator = self.total_hits + self.total_walks + self.total_hbp
        denominator = (self.total_at_bats + self.total_walks +
                       self.total_hbp + self.total_sacrifice_flies)

        if denominator == 0:
            return 0.0
        return numerator / denominator

    def get_slugging_percentage(self):
        """
        Calculate Slugging Percentage (SLG).

        SLG = Total Bases / At-Bats
        Total Bases = (1B × 1) + (2B × 2) + (3B × 3) + (HR × 4)
        """
        if self.total_at_bats == 0:
            return 0.0

        total_bases = (
            self.total_singles * 1 +
            self.total_doubles * 2 +
            self.total_triples * 3 +
            self.total_home_runs * 4
        )
        return total_bases / self.total_at_bats

    def get_ops(self):
        """OPS = OBP + SLG."""
        return self.get_on_base_percentage() + self.get_slugging_percentage()

    def get_triple_slash_line(self):
        """Return triple-slash as ".AVG/.OBP/.SLG"."""
        avg = self.get_overall_batting_average()
        obp = self.get_on_base_percentage()
        slg = self.get_slugging_percentage()

        def format_stat(value):
            if value >= 1.0:
                return f"{value:.3f}"
            return f"{value:.3f}"[1:]

        return f"{format_stat(avg)}/{format_stat(obp)}/{format_stat(slg)}"

    # ==================== Lap Feature Methods ====================

    def has_stats_to_lap(self) -> bool:
        """Check if there are any stats to create a lap from."""
        return (self.total_pitches > 0 or
                self.total_swings > 0 or
                sum(self.heatmap_attempts) > 0)

    def create_lap(self) -> dict:
        """Snapshot active-bucket stats into lap history; reset the bucket."""
        # Calculate batting average before creating lap
        batting_avg = self.get_overall_batting_average()

        # Calculate duration since last lap (or session start)
        lap_end_time = datetime.now()
        duration = (lap_end_time - self.lap_start_time).total_seconds()

        # Load existing lap history
        lap_history = self.load_lap_history()

        # Determine lap number
        lap_number = len(lap_history.get('laps', [])) + 1

        # Create lap entry — tag with the bucket so per-(mode, difficulty)
        # laps don't get mixed in side-by-side comparisons.
        lap_entry = {
            'lap_number': lap_number,
            'timestamp': lap_end_time.isoformat(),
            'bucket_key': self._active_key,
            'heatmap_data': list(self.heatmap_data),
            'heatmap_attempts': list(self.heatmap_attempts),
            'total_swings': self.total_swings,
            'total_hits': self.total_hits,
            'total_pitches': self.total_pitches,
            'total_at_bats': self.total_at_bats,
            'batting_average': round(batting_avg, 3),
            'duration_seconds': duration,
            'triple_slash': self.get_triple_slash_line(),
            'total_singles': self.total_singles,
            'total_doubles': self.total_doubles,
            'total_triples': self.total_triples,
            'total_home_runs': self.total_home_runs,
            'total_walks': self.total_walks,
            'on_base_percentage': round(self.get_on_base_percentage(), 3),
            'slugging_percentage': round(self.get_slugging_percentage(), 3),
            'ops': round(self.get_ops(), 3)
        }

        # Add to history
        if 'laps' not in lap_history:
            lap_history['laps'] = []
            lap_history['version'] = '1.1'
            lap_history['created_date'] = lap_end_time.isoformat()

        lap_history['laps'].append(lap_entry)
        lap_history['last_updated'] = lap_end_time.isoformat()

        # Enforce max history limit (100 laps)
        MAX_LAP_HISTORY = 100
        if len(lap_history['laps']) > MAX_LAP_HISTORY:
            lap_history['laps'] = lap_history['laps'][-MAX_LAP_HISTORY:]

        # Save lap history
        self.save_lap_history(lap_history)

        # Reset current stats (using existing method)
        self.reset_heatmap_data()

        # Reset lap timer
        self.lap_start_time = datetime.now()

        print(f"✓ Lap {lap_number} created [{self._active_key}]: "
              f"BA {batting_avg:.3f}, {self.total_hits} hits in {self.total_at_bats} ABs")

        return lap_entry

    def load_lap_history(self) -> dict:
        """Load lap history from file."""
        try:
            if os.path.exists(self.lap_history_file):
                with open(self.lap_history_file, 'r') as f:
                    return json.load(f)
            else:
                return {
                    'version': '1.1',
                    'created_date': datetime.now().isoformat(),
                    'last_updated': datetime.now().isoformat(),
                    'laps': []
                }
        except Exception as e:
            print(f"✗ Error loading lap history: {e}")
            return {'version': '1.1', 'laps': []}

    def save_lap_history(self, lap_history: dict):
        """Save lap history to file (atomically)."""
        atomic_write_json(self.lap_history_file, lap_history)

    def get_lap_history(self) -> list:
        """Get all lap entries."""
        history = self.load_lap_history()
        return history.get('laps', [])
