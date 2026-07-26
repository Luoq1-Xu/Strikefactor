"""Scrollable play-by-play panel for GameDay screens.

Renders a stored ``play_log`` (list of ``GameEvent.to_dict()`` entries) as a
grouped, scrollable log: half-inning headers, one row per at-bat, a running
score column, and scoring plays visually promoted. Filters let the viewer
narrow to scoring plays or a single side.

Palette/fonts come from :mod:`ui.gameday_theme` so the panel matches the rest
of the GameDay chrome. The panel owns no pygame_gui elements — it draws itself
into a caller-supplied rect and consumes raw events.
"""

import pygame

from ui import gameday_theme as gdt

# --- Result categories (used for chip styling) ---
_HOMERS = {'HOME RUN', 'HOMERUN', 'HR'}
_HITS = {'SINGLE', 'DOUBLE', 'TRIPLE'}
_WALKS = {'WALK', 'HIT BY PITCH', 'HBP', 'BB'}

# Filters: (key, label, predicate on a normalized play dict)
_FILTERS = [
    ('ALL', lambda p: True),
    ('SCORING', lambda p: p['runs'] > 0),
    ('YOU', lambda p: not p['is_top']),
    ('OPP', lambda p: p['is_top']),
]


def _fit(text, font, max_w):
    """Truncate ``text`` with a '..' suffix so it fits ``max_w`` pixels."""
    if max_w <= 0:
        return ''
    if font.size(text)[0] <= max_w:
        return text
    while text and font.size(text + '..')[0] > max_w:
        text = text[:-1]
    return text + '..'


class PlayByPlayPanel:
    """A self-contained, scrollable play-by-play list.

    Usage::

        panel = PlayByPlayPanel(fonts)
        panel.set_plays(play_log)
        panel.handle_event(event)      # returns True when consumed
        panel.draw(screen, pygame.Rect(...))
    """

    PAD = 16
    TITLE_H = 28
    COLS_H = 20
    ROW_H = 26
    HALF_HEADER_H = 32
    HALF_GAP = 8
    SCROLL_STEP = 3 * ROW_H

    def __init__(self, fonts):
        self.fonts = fonts
        self.rect = pygame.Rect(0, 0, 0, 0)
        self._plays = []          # normalized, chronological
        self._half_runs = {}      # (inning, is_top) -> runs scored that half
        self._rows = []           # flat render model for the active filter
        self._content_h = 0
        self.scroll = 0
        self.filter_index = 0
        self._filter_rects = []   # [(rect, index)] for click hit-testing

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    def set_plays(self, play_log):
        """Load a play log (list of dicts) and reset scroll/filter state."""
        self._plays = []
        self._half_runs = {}
        player_score = 0
        opponent_score = 0
        half_counts = {}

        for entry in play_log or []:
            result = str(entry.get('result') or 'UNKNOWN').replace('_', ' ').upper()
            is_top = bool(entry.get('is_top'))
            inning = entry.get('inning', 0)
            runs = int(entry.get('runs_scored', 0) or 0)
            is_visit = result.startswith('MOUND VISIT') or result.startswith('PITCHING CHANGE')

            if is_top:
                opponent_score += runs
            else:
                player_score += runs

            key = (inning, is_top)
            self._half_runs[key] = self._half_runs.get(key, 0) + runs
            if is_visit:
                order = None
            else:
                half_counts[key] = half_counts.get(key, 0) + 1
                order = half_counts[key]

            batter = entry.get('batter_name') or ('Opponent' if is_top else 'Player')
            if batter.strip().lower() == 'player':
                batter = 'YOU'

            self._plays.append({
                'inning': inning,
                'is_top': is_top,
                'batter': batter,
                'pitcher': (entry.get('pitcher_name') or '?').upper(),
                'result': result,
                'runs': runs,
                'is_visit': is_visit,
                'order': order,
                'player_score': player_score,
                'opponent_score': opponent_score,
            })

        self.scroll = 0
        self.filter_index = 0
        self._rebuild_rows()

    @property
    def has_plays(self):
        return bool(self._plays)

    def _rebuild_rows(self):
        """Flatten the filtered plays into half-inning headers + play rows."""
        predicate = _FILTERS[self.filter_index][1]
        self._rows = []
        current_key = None

        for play in self._plays:
            if not predicate(play):
                continue
            key = (play['inning'], play['is_top'])
            if key != current_key:
                current_key = key
                self._rows.append({
                    'kind': 'half',
                    'inning': play['inning'],
                    'is_top': play['is_top'],
                    'runs': self._half_runs.get(key, 0),
                    'first': not self._rows,
                })
            self._rows.append({'kind': 'play', 'play': play})

        y = 0
        for row in self._rows:
            row['y'] = y
            if row['kind'] == 'half':
                y += self.HALF_HEADER_H + (0 if row['first'] else self.HALF_GAP)
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

    def scroll_to_end(self):
        """Jump to the most recent play (clamped again on the next draw, so it
        is safe to call before the panel has been given a rect)."""
        self.scroll = self._content_h

    def set_filter(self, index):
        index %= len(_FILTERS)
        if index != self.filter_index:
            self.filter_index = index
            self.scroll = 0
            self._rebuild_rows()

    def cycle_filter(self, step=1):
        self.set_filter(self.filter_index + step)

    def handle_event(self, event):
        """Consume scroll/filter input. Returns True when the event was used."""
        if event.type == pygame.MOUSEWHEEL:
            if self.rect.collidepoint(pygame.mouse.get_pos()):
                self.scroll_by(-event.y * self.SCROLL_STEP)
                return True
            return False

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for rect, index in self._filter_rects:
                if rect.collidepoint(event.pos):
                    self.set_filter(index)
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
            elif event.key == pygame.K_TAB:
                mods = pygame.key.get_mods()
                self.cycle_filter(-1 if mods & pygame.KMOD_SHIFT else 1)
            else:
                return False
            return True

        return False

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def draw(self, screen, rect):
        self.rect = pygame.Rect(rect)
        f = self.fonts
        self._clamp_scroll()

        pygame.draw.rect(screen, gdt.DIVIDER, self.rect, 1)

        # --- Title bar: label + filter chips ---
        title_y = self.rect.top + 7
        gdt.blit_text(screen, "PLAY-BY-PLAY", f['micro'],
                      (self.rect.left + self.PAD, title_y), gdt.DIM)
        self._draw_filter_chips(screen, title_y - 2)

        bar_y = self.rect.top + self.TITLE_H
        pygame.draw.line(screen, gdt.DIVIDER,
                         (self.rect.left + 1, bar_y), (self.rect.right - 1, bar_y), 1)

        cols = self._columns()
        if not self._rows:
            msg = ("NO PLAY-BY-PLAY RECORDED FOR THIS GAME"
                   if not self._plays else "NO PLAYS MATCH THIS FILTER")
            gdt.blit_text(screen, msg, f['small'],
                          (self.rect.centerx, self.rect.centery - 9),
                          gdt.DIM_SOFT, align='center')
            return

        # --- Column labels ---
        label_y = bar_y + 4
        gdt.blit_text(screen, "BATTER", f['micro'], (cols['batter'], label_y), gdt.DIM_SOFT)
        gdt.blit_text(screen, "RESULT", f['micro'], (cols['result'], label_y), gdt.DIM_SOFT)
        gdt.blit_text(screen, "PITCHER", f['micro'], (cols['pitcher'], label_y), gdt.DIM_SOFT)
        gdt.blit_text(screen, "YOU-OPP", f['micro'], (cols['score'], label_y),
                      gdt.DIM_SOFT, align='right')

        view = pygame.Rect(self.rect.left + 1, bar_y + self.COLS_H,
                           self.rect.width - 2, self._viewport_h())
        prev_clip = screen.get_clip()
        screen.set_clip(view)
        sticky = None  # half-inning header scrolled off the top, pinned below
        for row in self._rows:
            y = view.top + row['y'] - self.scroll
            if row['kind'] == 'half':
                y += 0 if row['first'] else self.HALF_GAP
                if y <= view.top:
                    sticky = row
                if y + self.HALF_HEADER_H < view.top or y > view.bottom:
                    continue
                self._draw_half_header(screen, row, y, view, cols)
            else:
                if y + self.ROW_H < view.top or y > view.bottom:
                    continue
                self._draw_play_row(screen, row['play'], y, view, cols)
        if sticky is not None:
            # Keep the inning you're reading visible while scrolling.
            self._draw_half_header(screen, sticky, view.top, view, cols)
        screen.set_clip(prev_clip)

        self._draw_scrollbar(screen, view)

    # --- pieces ---
    def _columns(self):
        """Column x-positions derived from the panel rect."""
        x0 = self.rect.left + self.PAD
        right = self.rect.right - self.PAD - 10  # leave room for the scrollbar
        return {
            'x0': x0,
            'num': x0 + 22,          # right-aligned
            'batter': x0 + 38,
            'result': x0 + 250,
            'pitcher': x0 + 520,
            'runs': right - 120,     # right-aligned
            'score': right,          # right-aligned
        }

    def _draw_filter_chips(self, screen, y):
        f = self.fonts['micro']
        self._filter_rects = []
        x = self.rect.right - self.PAD
        for index in range(len(_FILTERS) - 1, -1, -1):
            label = _FILTERS[index][0]
            surf = f.render(label, True, gdt.FG)
            w = surf.get_width() + 16
            chip = pygame.Rect(x - w, y, w, surf.get_height() + 8)
            active = index == self.filter_index
            if active:
                pygame.draw.rect(screen, gdt.HIGHLIGHT_BG, chip)
                screen.blit(f.render(label, True, gdt.HIGHLIGHT_FG),
                            (chip.x + 8, chip.y + 4))
            else:
                pygame.draw.rect(screen, gdt.DIVIDER, chip, 1)
                screen.blit(f.render(label, True, gdt.DIM),
                            (chip.x + 8, chip.y + 4))
            self._filter_rects.append((chip, index))
            x = chip.left - 8

    def _draw_half_header(self, screen, row, y, view, cols):
        f = self.fonts
        band = pygame.Rect(view.left + 1, y, view.width - 2, self.HALF_HEADER_H)
        pygame.draw.rect(screen, (16, 16, 16), band)
        pygame.draw.line(screen, gdt.DIVIDER,
                         (band.left, band.bottom - 1), (band.right, band.bottom - 1), 1)

        # Half marker: triangle up for the top half, down for the bottom.
        tx, ty = cols['x0'] + 2, band.centery
        if row['is_top']:
            points = [(tx, ty + 4), (tx + 10, ty + 4), (tx + 5, ty - 5)]
        else:
            points = [(tx, ty - 4), (tx + 10, ty - 4), (tx + 5, ty + 5)]
        pygame.draw.polygon(screen, gdt.FG, points)

        half = "TOP" if row['is_top'] else "BOT"
        side = "OPPONENT BATTING" if row['is_top'] else "YOU BATTING"
        ty_text = band.centery - f['small'].get_height() // 2
        gdt.blit_text(screen, f"{half} {row['inning']}", f['small'],
                      (cols['x0'] + 20, ty_text), gdt.FG)
        gdt.blit_text(screen, side, f['micro'],
                      (cols['batter'] + 82, band.centery - 7), gdt.DIM)

        runs = row['runs']
        if runs:
            gdt.blit_text(screen, f"{runs} RUN{'S' if runs != 1 else ''}", f['micro'],
                          (cols['score'], band.centery - 7), gdt.FG, align='right')
        else:
            gdt.blit_text(screen, "NO RUNS", f['micro'],
                          (cols['score'], band.centery - 7), gdt.DIM_SOFT, align='right')

    def _draw_play_row(self, screen, play, y, view, cols):
        f = self.fonts
        row_rect = pygame.Rect(view.left + 1, y, view.width - 2, self.ROW_H)
        scoring = play['runs'] > 0
        if scoring:
            pygame.draw.rect(screen, (24, 24, 24), row_rect)
            pygame.draw.rect(screen, gdt.FG,
                             (row_rect.left, row_rect.top, 3, row_rect.height))

        text_y = row_rect.centery - f['small'].get_height() // 2

        if play['is_visit']:
            label = _fit(play['result'], f['small'],
                         cols['score'] - cols['batter'] - 20)
            gdt.blit_text(screen, "--", f['micro'], (cols['num'], text_y + 2),
                          gdt.DIM_SOFT, align='right')
            gdt.blit_text(screen, label, f['small'], (cols['batter'], text_y), gdt.DIM)
            return

        if play['order'] is not None:
            gdt.blit_text(screen, str(play['order']), f['micro'],
                          (cols['num'], text_y + 2), gdt.DIM_SOFT, align='right')

        batter = _fit(play['batter'], f['small'], cols['result'] - cols['batter'] - 14)
        gdt.blit_text(screen, batter, f['small'], (cols['batter'], text_y), gdt.FG)

        self._draw_result_chip(screen, play['result'], cols['result'], row_rect.centery)

        pitcher = _fit(f"vs {play['pitcher']}", f['micro'],
                       cols['runs'] - cols['pitcher'] - 20)
        gdt.blit_text(screen, pitcher, f['micro'],
                      (cols['pitcher'], row_rect.centery - 7), gdt.DIM_SOFT)

        if scoring:
            gdt.blit_text(screen, f"+{play['runs']}", f['small'],
                          (cols['runs'], text_y), gdt.FG, align='right')

        score = f"{play['player_score']}-{play['opponent_score']}"
        gdt.blit_text(screen, score, f['small'], (cols['score'], text_y),
                      gdt.FG if scoring else gdt.DIM, align='right')

    def _draw_result_chip(self, screen, result, x, cy):
        """HOME RUN inverts, other hits get an outline, outs stay plain/dim."""
        f = self.fonts['small']
        text = _fit(result, f, 240)
        if result in _HOMERS:
            surf = f.render(text, True, gdt.HIGHLIGHT_FG)
            chip = pygame.Rect(x - 6, cy - surf.get_height() // 2 - 3,
                               surf.get_width() + 12, surf.get_height() + 6)
            pygame.draw.rect(screen, gdt.HIGHLIGHT_BG, chip)
            screen.blit(surf, (x, cy - surf.get_height() // 2))
        elif result in _HITS:
            surf = f.render(text, True, gdt.FG)
            chip = pygame.Rect(x - 6, cy - surf.get_height() // 2 - 3,
                               surf.get_width() + 12, surf.get_height() + 6)
            pygame.draw.rect(screen, gdt.DIM, chip, 1)
            screen.blit(surf, (x, cy - surf.get_height() // 2))
        elif result in _WALKS:
            gdt.blit_text(screen, text, f, (x, cy - f.get_height() // 2), gdt.FG)
        else:
            gdt.blit_text(screen, text, f, (x, cy - f.get_height() // 2), gdt.DIM)

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
