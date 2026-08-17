"""Full pitching box score for the GameDay screens.

Every arm both teams used gets a row and its whole line — IP / H / R / BB / K /
HR / PC / ERA — under a per-side header, closed by a totals row. Rows scroll, so
the panel is never forced to truncate: the GAME LOG overlay used to render this
as a fixed two-line strip beneath the play-by-play (``stats[-2:]`` per side),
which silently hid every arm before the last two. A game that went to a
four-reliever bullpen simply had no screen anywhere that could show it.

Palette/fonts come from :mod:`ui.gameday_theme` so the panel matches the rest of
the GameDay chrome. It owns no pygame_gui elements — it draws itself into a
caller-supplied rect and consumes raw events, the same contract as
:class:`ui.play_by_play_panel.PlayByPlayPanel`.
"""

from typing import Mapping, NamedTuple, Optional, Sequence

import pygame

from strikefactor.ui import gameday_theme as gdt

# Column labels, in display order, paired with the key their formatted value is
# stored under. Counting stats sit between IP and the rate stat the way a real
# box score orders them; PC (pitch count) is the one column that isn't a
# traditional line stat but is what the hook decisions in this game turn on.
COLUMNS = (
    ('IP', 'ip'),
    ('H', 'h'),
    ('R', 'r'),
    ('BB', 'bb'),
    ('K', 'k'),
    ('HR', 'hr'),
    ('PC', 'pc'),
    ('ERA', 'era'),
)

# Counting columns render a zero dimly, so a line's actual damage stands out at
# a glance. IP / PC / ERA are always lit — a 0.0 IP appearance is information.
_DIM_WHEN_ZERO = ('h', 'r', 'bb', 'k', 'hr')


class PitchingSide(NamedTuple):
    """One team's pitching staff as the panel wants it.

    ``stats`` holds :class:`gameplay.gameday_manager.PitcherStats`-shaped
    objects (name / pitch_count / outs_recorded / hits_allowed / runs_allowed /
    strikeouts / walks / home_runs_allowed / is_active, plus
    ``get_fatigue_label()``). ``tags`` maps a pitcher name to a short label
    drawn beside it — handedness for arms the player bats against, bullpen role
    for the arms they only ever manage. The caller supplies those because the
    panel deliberately doesn't reach into the gameplay layer to look them up.
    """

    label: str
    stats: Sequence
    tags: Optional[Mapping[str, str]] = None


def format_ip(outs: int) -> str:
    """Innings pitched in baseball notation: 20 outs -> '6.2'.

    Duplicated from ``PitcherStats.get_ip_display`` on purpose — the totals row
    formats a *summed* out count, which belongs to no single PitcherStats
    instance, and one formatter for every number the panel prints beats two that
    can drift apart. ``test_pitching_box_panel`` pins the two together.
    """
    return f"{outs // 3}.{outs % 3}"


def format_era(runs: int, outs: int) -> str:
    """Earned runs per nine. No outs recorded has no rate: '-' when unscored
    upon, 'INF' once a run is in, never a divide-by-zero or a fake 0.00."""
    if outs <= 0:
        return 'INF' if runs > 0 else '-'
    return f"{27.0 * runs / outs:.2f}"


def _fit(text, font, max_w):
    """Truncate ``text`` with a '..' suffix so it fits ``max_w`` pixels."""
    if max_w <= 0:
        return ''
    if font.size(text)[0] <= max_w:
        return text
    while text and font.size(text + '..')[0] > max_w:
        text = text[:-1]
    return text + '..'


class PitchingBoxPanel:
    """A self-contained, scrollable pitching box score.

    Usage::

        panel = PitchingBoxPanel(fonts)
        panel.set_sides([PitchingSide("OPPONENT PITCHING", stats, tags), ...])
        panel.handle_event(event)      # returns True when consumed
        panel.draw(screen, pygame.Rect(...))
    """

    PAD = 16
    TITLE_H = 28
    COLS_H = 20
    ROW_H = 26
    SIDE_HEADER_H = 30
    SIDE_GAP = 10
    TOTALS_H = 30
    SCROLL_STEP = 3 * ROW_H

    COL_W = 92          # preferred width of one numeric column
    COL_MIN_W = 42
    NAME_MIN_W = 180    # the name column never shrinks past this

    def __init__(self, fonts):
        self.fonts = fonts
        self.rect = pygame.Rect(0, 0, 0, 0)
        self._sides = []          # normalized [(label, [row dicts], totals)]
        self._rows = []           # flat render model
        self._content_h = 0
        self._live = True
        self.scroll = 0

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    def set_sides(self, sides, live: bool = True):
        """Load the staffs to display, in the order they should be stacked.

        ``live`` controls the on-the-mound marker: a finished game has no
        active pitcher, and leaving `is_active` lit on the FINAL screen would
        claim the last arm used is still working.
        """
        self._live = live
        self._sides = []
        for side in sides:
            tags = side.tags or {}
            lines = [self._line(ps, tags.get(ps.name, ''))
                     for ps in side.stats if self._appeared(ps)]
            self._sides.append((side.label, lines, self._totals(lines)))
        self.scroll = 0
        self._rebuild_rows()

    @staticmethod
    def _appeared(ps) -> bool:
        """Skip rostered arms that never got into the game — but keep the one
        currently warm on the mound, who legitimately has no line yet."""
        return bool(ps.pitch_count or ps.outs_recorded or ps.is_active)

    def _line(self, ps, tag) -> dict:
        outs = int(ps.outs_recorded)
        runs = int(ps.runs_allowed)
        counts = {
            'outs': outs,
            'h': int(ps.hits_allowed),
            'r': runs,
            'bb': int(ps.walks),
            'k': int(ps.strikeouts),
            'hr': int(ps.home_runs_allowed),
            'pc': int(ps.pitch_count),
        }
        fatigue = ''
        if getattr(ps, 'get_fatigue_label', None):
            fatigue = ps.get_fatigue_label().upper()
        return {
            'name': str(ps.name).upper(),
            'tag': str(tag or '').upper(),
            'active': bool(ps.is_active),
            'fatigue': fatigue,
            'counts': counts,
            'values': self._values(counts),
        }

    def _totals(self, lines) -> dict:
        counts = {key: sum(line['counts'][key] for line in lines)
                  for key in ('outs', 'h', 'r', 'bb', 'k', 'hr', 'pc')}
        return {'counts': counts, 'values': self._values(counts)}

    @staticmethod
    def _values(counts) -> dict:
        """Format one set of counting stats into the panel's display strings."""
        values = {key: str(counts[key])
                  for key in ('h', 'r', 'bb', 'k', 'hr', 'pc')}
        values['ip'] = format_ip(counts['outs'])
        values['era'] = format_era(counts['r'], counts['outs'])
        return values

    def _rebuild_rows(self):
        """Flatten the sides into header / pitcher / totals rows."""
        self._rows = []
        for label, lines, totals in self._sides:
            self._rows.append({
                'kind': 'side',
                'label': label,
                'count': len(lines),
                'first': not self._rows,
            })
            for line in lines:
                self._rows.append({'kind': 'pitcher', 'line': line})
            if lines:
                self._rows.append({'kind': 'totals', 'totals': totals})
            else:
                self._rows.append({'kind': 'empty'})

        y = 0
        for row in self._rows:
            row['y'] = y
            if row['kind'] == 'side':
                y += self.SIDE_HEADER_H + (0 if row['first'] else self.SIDE_GAP)
            elif row['kind'] == 'totals':
                y += self.TOTALS_H
            else:
                y += self.ROW_H
        self._content_h = y
        self._clamp_scroll()

    # ------------------------------------------------------------------
    # Scrolling / input
    # ------------------------------------------------------------------
    def _viewport_h(self):
        return max(0, self.rect.height - self.TITLE_H - self.COLS_H - self.PAD)

    def _max_scroll(self):
        return max(0, self._content_h - self._viewport_h())

    def _clamp_scroll(self):
        self.scroll = max(0, min(self.scroll, self._max_scroll()))

    def scroll_by(self, dy):
        self.scroll += dy
        self._clamp_scroll()

    def handle_event(self, event):
        """Consume scroll input. Returns True when the event was used."""
        if event.type == pygame.MOUSEWHEEL:
            if self.rect.collidepoint(pygame.mouse.get_pos()):
                self.scroll_by(-event.y * self.SCROLL_STEP)
                return True
            return False

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_DOWN:
                self.scroll_by(self.ROW_H)
            elif event.key == pygame.K_UP:
                self.scroll_by(-self.ROW_H)
            elif event.key == pygame.K_PAGEDOWN:
                self.scroll_by(self._viewport_h())
            elif event.key == pygame.K_PAGEUP:
                self.scroll_by(-self._viewport_h())
            elif event.key == pygame.K_HOME:
                self.scroll = 0
            elif event.key == pygame.K_END:
                self.scroll = self._max_scroll()
            else:
                return False
            return True

        return False

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _layout(self):
        """Column x-positions derived from the panel rect. Numeric columns are
        right-aligned and anchored to the right edge, so the name column
        absorbs whatever width is left."""
        x0 = self.rect.left + self.PAD
        right = self.rect.right - self.PAD - 10  # leave room for the scrollbar
        n = len(COLUMNS)
        usable = max(0, right - x0)
        # Prefer COL_W, shrink toward COL_MIN_W to protect the name column, and
        # never let the numeric block outgrow the panel itself: a rect too narrow
        # for a box score still has to draw inside its own border. The name is
        # what gives (via _fit), because a truncated name still identifies an arm
        # and a truncated stat is a wrong number.
        col_w = min(self.COL_W,
                    max(self.COL_MIN_W, (usable - self.NAME_MIN_W) // n))
        col_w = max(1, min(col_w, usable // n))
        cols = {key: right - (n - 1 - i) * col_w
                for i, (_, key) in enumerate(COLUMNS)}
        return {
            'x0': x0,
            'name': x0 + 16,                    # leaves the marker gutter
            'name_right': right - n * col_w - 10,
            'right': right,
            'cols': cols,
        }

    def draw(self, screen, rect):
        self.rect = pygame.Rect(rect)
        f = self.fonts
        self._clamp_scroll()

        pygame.draw.rect(screen, gdt.DIVIDER, self.rect, 1)

        # --- Title bar ---
        title_y = self.rect.top + 7
        gdt.blit_text(screen, "PITCHING", f['micro'],
                      (self.rect.left + self.PAD, title_y), gdt.DIM)
        arms = sum(len(lines) for _, lines, _ in self._sides)
        gdt.blit_text(screen, f"{arms} ARM{'S' if arms != 1 else ''} USED",
                      f['micro'], (self.rect.right - self.PAD, title_y),
                      gdt.DIM_SOFT, align='right')

        bar_y = self.rect.top + self.TITLE_H
        pygame.draw.line(screen, gdt.DIVIDER,
                         (self.rect.left + 1, bar_y), (self.rect.right - 1, bar_y), 1)

        lay = self._layout()
        if not self._rows:
            gdt.blit_text(screen, "NO PITCHING RECORDED FOR THIS GAME",
                          f['small'],
                          (self.rect.centerx, self.rect.centery - 9),
                          gdt.DIM_SOFT, align='center')
            return

        # --- Column labels (fixed; the rows scroll under them) ---
        label_y = bar_y + 4
        gdt.blit_text(screen, "PITCHER", f['micro'], (lay['name'], label_y),
                      gdt.DIM_SOFT)
        for label, key in COLUMNS:
            gdt.blit_text(screen, label, f['micro'], (lay['cols'][key], label_y),
                          gdt.DIM_SOFT, align='right')

        view = pygame.Rect(self.rect.left + 1, bar_y + self.COLS_H,
                           self.rect.width - 2, self._viewport_h())
        prev_clip = screen.get_clip()
        screen.set_clip(view)
        sticky = None  # side header scrolled off the top, pinned below
        for row in self._rows:
            y = view.top + row['y'] - self.scroll
            if row['kind'] == 'side':
                y += 0 if row['first'] else self.SIDE_GAP
                if y <= view.top:
                    sticky = row
                if y + self.SIDE_HEADER_H < view.top or y > view.bottom:
                    continue
                self._draw_side_header(screen, row, y, view, lay)
            elif row['kind'] == 'totals':
                if y + self.TOTALS_H < view.top or y > view.bottom:
                    continue
                self._draw_totals_row(screen, row['totals'], y, view, lay)
            elif row['kind'] == 'empty':
                if y + self.ROW_H < view.top or y > view.bottom:
                    continue
                gdt.blit_text(screen, "NO ARMS USED", f['small'],
                              (lay['name'], y + 4), gdt.DIM_SOFT)
            else:
                if y + self.ROW_H < view.top or y > view.bottom:
                    continue
                self._draw_pitcher_row(screen, row['line'], y, view, lay)
        if sticky is not None:
            # Keep the staff you're reading labelled while scrolling.
            self._draw_side_header(screen, sticky, view.top, view, lay)
        screen.set_clip(prev_clip)

        self._draw_scrollbar(screen, view)

    # --- pieces ---
    def _draw_side_header(self, screen, row, y, view, lay):
        f = self.fonts
        band = pygame.Rect(view.left + 1, y, view.width - 2, self.SIDE_HEADER_H)
        pygame.draw.rect(screen, (16, 16, 16), band)
        pygame.draw.line(screen, gdt.DIVIDER,
                         (band.left, band.bottom - 1), (band.right, band.bottom - 1), 1)
        gdt.blit_text(screen, row['label'], f['small'],
                      (lay['x0'], band.centery - f['small'].get_height() // 2),
                      gdt.FG)
        count = row['count']
        gdt.blit_text(screen, f"{count} ARM{'S' if count != 1 else ''}",
                      f['micro'], (lay['right'], band.centery - 7),
                      gdt.DIM, align='right')

    def _draw_pitcher_row(self, screen, line, y, view, lay):
        f = self.fonts
        row_rect = pygame.Rect(view.left + 1, y, view.width - 2, self.ROW_H)
        on_mound = self._live and line['active']
        if on_mound:
            pygame.draw.rect(screen, (24, 24, 24), row_rect)
            pygame.draw.rect(screen, gdt.FG,
                             (row_rect.left, row_rect.top, 3, row_rect.height))

        text_y = row_rect.centery - f['small'].get_height() // 2
        name_w = lay['name_right'] - lay['name']

        # Tag (handedness / bullpen role) and the on-the-mound note share the
        # space to the right of the name, so measure them off it first.
        notes = []
        if line['tag']:
            notes.append(line['tag'])
        if on_mound:
            notes.append(line['fatigue'] or 'ON THE MOUND')
        note_text = '  ·  '.join(notes)
        note_w = f['micro'].size(note_text)[0] + 10 if note_text else 0

        name = _fit(line['name'], f['small'], name_w - note_w)
        name_rect = gdt.blit_text(screen, name, f['small'],
                                  (lay['name'], text_y), gdt.FG)
        if note_text:
            gdt.blit_text(screen, note_text, f['micro'],
                          (name_rect.right + 10, row_rect.centery - 7), gdt.DIM)

        self._draw_values(screen, line['values'], row_rect.centery, lay,
                          dim_zeros=True)

    def _draw_totals_row(self, screen, totals, y, view, lay):
        f = self.fonts
        row_rect = pygame.Rect(view.left + 1, y, view.width - 2, self.TOTALS_H)
        pygame.draw.line(screen, gdt.DIVIDER,
                         (row_rect.left, row_rect.top),
                         (row_rect.right, row_rect.top), 1)
        gdt.blit_text(screen, "TEAM TOTALS", f['micro'],
                      (lay['name'], row_rect.centery - 7), gdt.DIM)
        self._draw_values(screen, totals['values'], row_rect.centery, lay,
                          dim_zeros=False)

    def _draw_values(self, screen, values, cy, lay, dim_zeros):
        f = self.fonts['small']
        text_y = cy - f.get_height() // 2
        for _, key in COLUMNS:
            text = values[key]
            dim = dim_zeros and key in _DIM_WHEN_ZERO and text == '0'
            gdt.blit_text(screen, text, f, (lay['cols'][key], text_y),
                          gdt.DIM_SOFT if dim else gdt.FG, align='right')

    def _draw_scrollbar(self, screen, view):
        max_scroll = self._max_scroll()
        if max_scroll <= 0:
            return
        track = pygame.Rect(self.rect.right - 8, view.top + 2, 3, view.height - 4)
        pygame.draw.rect(screen, gdt.DIVIDER, track)
        frac = view.height / max(1, self._content_h)
        thumb_h = max(24, int(track.height * frac))
        travel = track.height - thumb_h
        offset = int(travel * (self.scroll / max_scroll))
        pygame.draw.rect(screen, gdt.FG,
                         (track.x, track.y + offset, track.width, thumb_h))
