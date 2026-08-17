"""Shared chrome for the GameDay screens — single source of truth.

The GameDay setup / transition / final screens (and the new resume + history
screens) all share a strict black/white/gray retro aesthetic, the
``8bitoperator_jve`` pixel font set, a common top header, and an
inning-by-inning linescore. Those primitives live here so every screen renders
identically and there's one place to tune them.

All draw helpers are plain functions taking ``screen`` + a ``fonts`` dict from
``load_fonts()`` so they have no dependency on any particular GameState.
"""

import pygame

from strikefactor.config import get_path, resource_path

# --- Palette (matches BroadcastHUD) ---
BG = (0, 0, 0)
FG = (240, 240, 240)
DIM = (140, 140, 140)
DIM_SOFT = (90, 90, 90)
DIVIDER = (60, 60, 60)
HIGHLIGHT_BG = (240, 240, 240)
HIGHLIGHT_FG = (10, 10, 10)

# --- Layout ---
SCREEN_W = 1280
SCREEN_H = 720
MARGIN_X = 40

_FONT_PATH = "ui/font/8bitoperator_jve.ttf"
_FONT_SIZES = {
    'micro': 14, 'tiny': 16, 'small': 18, 'med': 22,
    'big': 30, 'huge': 60, 'mega': 110,
}


def load_fonts() -> dict:
    """Build the pixel font set used across GameDay screens."""
    base = resource_path(get_path(_FONT_PATH))
    return {name: pygame.font.Font(base, size)
            for name, size in _FONT_SIZES.items()}


def blit_text(screen, text, font, pos, color, align='left'):
    """Render text once and blit it. Returns the blit rect."""
    surf = font.render(text, True, color)
    x, y = pos
    if align == 'right':
        x -= surf.get_width()
    elif align == 'center':
        x -= surf.get_width() // 2
    rect = surf.get_rect(topleft=(x, y))
    screen.blit(surf, rect)
    return rect


def draw_top_chrome(screen, header_text, fonts,
                    screen_w=SCREEN_W, margin_x=MARGIN_X):
    """Shared header: '=== TITLE ===' top-left, brand top-right, thin divider."""
    blit_text(screen, header_text, fonts['micro'], (margin_x, 20), FG)
    blit_text(screen, "StrikeFactor 0.1", fonts['micro'],
              (screen_w - margin_x, 20), DIM, align='right')
    pygame.draw.line(screen, DIVIDER,
                     (margin_x, 44), (screen_w - margin_x, 44), 1)


def draw_chips(screen, font, labels, active_index, x, y,
               gap=8, pad_x=8, pad_y=4, anchor='right'):
    """Draw a row of selectable chips (active one inverted).

    ``x`` is the anchored edge: the row's right edge when ``anchor='right'``
    (laid out right-to-left, so the row keeps that edge however long the
    labels are) and its left edge when ``anchor='left'``. Right-anchoring
    suits chips tucked into a panel's top-right corner; the settings screen
    anchors left because its whole column starts at ``MARGIN_X``.

    Returns ``[(rect, index)]`` for click hit-testing — the caller owns the
    selection, this only draws it.
    """
    hits = []
    cursor = x
    order = (range(len(labels) - 1, -1, -1) if anchor == 'right'
             else range(len(labels)))
    for index in order:
        label = labels[index]
        surf = font.render(label, True, FG)
        width = surf.get_width() + 2 * pad_x
        left = cursor - width if anchor == 'right' else cursor
        chip = pygame.Rect(left, y, width, surf.get_height() + 2 * pad_y)
        if index == active_index:
            pygame.draw.rect(screen, HIGHLIGHT_BG, chip)
            screen.blit(font.render(label, True, HIGHLIGHT_FG),
                        (chip.x + pad_x, chip.y + pad_y))
        else:
            pygame.draw.rect(screen, DIVIDER, chip, 1)
            screen.blit(font.render(label, True, DIM),
                        (chip.x + pad_x, chip.y + pad_y))
        hits.append((chip, index))
        cursor = chip.left - gap if anchor == 'right' else chip.right + gap
    return hits


# --- Linescore ---

_LINESCORE_TEAM_COL_W = 130
_LINESCORE_INNING_COL_W = 60
_LINESCORE_TOTAL_COL_W = 60
_LINESCORE_MIN_INNING_W = 36
_LINESCORE_MIN_TOTAL_W = 50


def linescore_column_widths(n_innings, screen_w=SCREEN_W, margin_x=MARGIN_X):
    """Return (team_w, inn_w, tot_w) sized to fit ``n_innings`` columns within
    the screen margins; shrinks inning then total widths for extra innings."""
    team_w = _LINESCORE_TEAM_COL_W
    inn_w = _LINESCORE_INNING_COL_W
    tot_w = _LINESCORE_TOTAL_COL_W
    max_w = screen_w - 2 * margin_x

    if team_w + n_innings * inn_w + 3 * tot_w > max_w:
        avail = max_w - team_w - 3 * tot_w
        inn_w = max(_LINESCORE_MIN_INNING_W, avail // n_innings)
    if team_w + n_innings * inn_w + 3 * tot_w > max_w:
        avail = max_w - team_w - n_innings * inn_w
        tot_w = max(_LINESCORE_MIN_TOTAL_W, avail // 3)
    return team_w, inn_w, tot_w


def _draw_linescore_row(screen, fonts, team_label, runs_per_inning,
                        r_total, h_total, e_total,
                        x, y, team_w, inn_w, tot_w, table_w, highlight=False):
    """Render a single linescore row (OPPONENT / YOU). ``y`` is the row top-y."""
    row_h = 36

    if highlight:
        block = pygame.Rect(x - 6, y - 4, table_w + 12, row_h - 4)
        pygame.draw.rect(screen, HIGHLIGHT_BG, block)
        text_color = HIGHLIGHT_FG
        dim_color = HIGHLIGHT_FG
    else:
        text_color = FG
        dim_color = DIM_SOFT

    blit_text(screen, team_label, fonts['med'], (x, y), text_color)

    cx = x + team_w
    for runs in runs_per_inning:
        color = text_color if runs > 0 else dim_color
        blit_text(screen, str(runs), fonts['med'],
                  (cx + inn_w // 2, y), color, align='center')
        cx += inn_w

    for value in (r_total, h_total, e_total):
        blit_text(screen, str(value), fonts['med'],
                  (cx + tot_w // 2, y), text_color, align='center')
        cx += tot_w


def draw_linescore_from_arrays(screen, x, y, fonts,
                               opp_runs, plr_runs, opp_total, plr_total,
                               opp_hits=0, plr_hits=0,
                               opp_label="OPPONENT", plr_label="YOU",
                               current_inning=None,
                               screen_w=SCREEN_W, margin_x=MARGIN_X):
    """Draw an inning-by-inning linescore from explicit run arrays.

    Works for both the live manager (via get_box_score_lines) and a stored
    history row (its ``*_inning_scores`` arrays). Auto-expands for extras.
    Returns the y just below the table.
    """
    n_innings = len(opp_runs)
    team_w, inn_w, tot_w = linescore_column_widths(n_innings, screen_w, margin_x)
    table_w = team_w + n_innings * inn_w + 3 * tot_w
    row_h = 38

    label = "LINESCORE"
    if n_innings > 9:
        label = f"LINESCORE  ·  {n_innings} INN"
    blit_text(screen, label, fonts['micro'], (x, y), DIM)

    header_y = y + 28
    blit_text(screen, "TEAM", fonts['tiny'], (x, header_y), DIM)
    cx = x + team_w
    for i in range(1, n_innings + 1):
        color = FG if i == current_inning else DIM
        blit_text(screen, str(i), fonts['tiny'],
                  (cx + inn_w // 2, header_y), color, align='center')
        cx += inn_w
    for lab in ("R", "H", "E"):
        blit_text(screen, lab, fonts['tiny'],
                  (cx + tot_w // 2, header_y), DIM, align='center')
        cx += tot_w

    sep_y = header_y + 22
    pygame.draw.line(screen, DIVIDER, (x, sep_y), (x + table_w, sep_y), 1)

    opp_y = sep_y + 8
    _draw_linescore_row(screen, fonts, opp_label, opp_runs, opp_total,
                        opp_hits, 0, x, opp_y, team_w, inn_w, tot_w, table_w,
                        highlight=False)
    plr_y = opp_y + row_h
    _draw_linescore_row(screen, fonts, plr_label, plr_runs, plr_total,
                        plr_hits, 0, x, plr_y, team_w, inn_w, tot_w, table_w,
                        highlight=True)
    return plr_y + row_h
