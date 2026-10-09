"""Shared, read-only drawing for live fielding and recorded frames."""

import pygame

from strikefactor.gameplay import hit_animation as ha


def _label(screen, text, size, color, center, alpha, offset):
    font = _font(size)
    body = font.render(text, True, color)
    shadow = font.render(text, True, (0, 0, 0))
    body.set_alpha(int(alpha * 255))
    shadow.set_alpha(int(alpha * 200))
    rect = body.get_rect(center=center)
    screen.blit(shadow, rect.move(offset, offset))
    screen.blit(body, rect)


_fonts = {}


def _font(size):
    if size not in _fonts:
        _fonts[size] = pygame.font.SysFont(None, size, bold=True)
    return _fonts[size]


def draw_frame(screen, frame):
    draw_field(screen)
    for f in frame.fielders:
        pygame.draw.circle(screen, ha.BODY_COLOR, tuple(map(int, f.pos)), ha.BODY_RADIUS_PX)
        pygame.draw.circle(screen, ha.GLOVE_COLOR, tuple(map(int, f.glove)), 3)
    if frame.error is not None:
        x, y, alpha = frame.error
        _label(screen, "!", 30, ha.ERROR_MARK_COLOR, (int(x), int(y)), alpha, 1)
    if frame.shadow_visible:
        sx, sy = map(int, frame.shadow)
        pygame.draw.ellipse(screen, (60, 60, 60), pygame.Rect(
            sx - ha.BALL_SHADOW_W_PX // 2, sy - ha.BALL_SHADOW_H_PX // 2,
            ha.BALL_SHADOW_W_PX, ha.BALL_SHADOW_H_PX))
    if frame.ball_visible:
        pygame.draw.circle(screen, (255, 255, 255), tuple(map(int, frame.ball)), ha.BALL_RADIUS_PX)
    if frame.distance is not None:
        feet, x, y, alpha = frame.distance
        y = max(_font(36).get_height() // 2 + 4, y)
        _label(screen, f"{feet} FT", 36, (255, 230, 120), (int(x), int(y)), alpha, 2)


def draw_field(screen):
    hx, hy = ha.HOME

    # Outfield wall — sampled-arc band rather than a single pygame.draw.arc.
    # The arc spans from one foul-pole corner across CF to the other,
    # forming a continuous boundary. The parametric ellipse angle at the
    # foul corners is `atan2(WALL_FT_X, WALL_FT_Y)` — using the *real-foot*
    # semi-axes, since the parametric angle is invariant under axis-aligned
    # scaling. (Using the screen-pixel semi-axes was the previous bug that
    # left a gap between the foul lines and the wall.) The geometry is
    # static, so it's computed once and cached in ha._wall_geometry().
    geo = ha._wall_geometry()
    wall_top_pts = geo['top']
    wall_bot_pts = geo['bot']
    face_poly = geo['face_poly']

    # Wall face — filled band so the wall reads as a 3D structure.
    pygame.draw.polygon(screen, (60, 60, 60), face_poly, 0)
    # Bright top edge (outer rim of the wall, where it meets the sky/black
    # background) and a softer inner edge where it meets the field.
    pygame.draw.lines(screen, (200, 200, 200), False, wall_top_pts, 2)
    pygame.draw.lines(screen, (115, 115, 115), False, wall_bot_pts, 1)

    # Foul lines — terminate at the inner-wall edge (where the field
    # meets the wall face), not at the outer rim. wall_bot_pts[0] is the
    # right foul-pole base, wall_bot_pts[-1] is the left.
    foul_right_base = wall_bot_pts[0]
    foul_left_base  = wall_bot_pts[-1]
    line_color = (150, 150, 150)
    pygame.draw.line(screen, line_color, (hx, hy), foul_right_base, 1)
    pygame.draw.line(screen, line_color, (hx, hy), foul_left_base, 1)

    # Foul poles — short vertical bars rising from the wall corners. Match
    # the glove yellow so the only non-gray elements are the two play-
    # critical accents (poles + glove).
    foul_right_top = wall_top_pts[0]
    foul_left_top  = wall_top_pts[-1]
    pole_color = (245, 215, 90)
    pygame.draw.line(screen, pole_color, foul_right_top,
                     (foul_right_top[0], foul_right_top[1] - ha.FOUL_POLE_HEIGHT_PX), 2)
    pygame.draw.line(screen, pole_color, foul_left_top,
                     (foul_left_top[0], foul_left_top[1] - ha.FOUL_POLE_HEIGHT_PX), 2)

    # Infield diamond — minimalist grayscale (was brown).
    diamond = [ha.HOME, ha.BASES["1B"], ha.BASES["2B"], ha.BASES["3B"]]
    pygame.draw.polygon(screen, (35, 35, 35), diamond, 0)
    pygame.draw.polygon(screen, (180, 180, 180), diamond, 2)

    # Bases
    for bp in ha.BASES.values():
        bx, by = int(bp[0]), int(bp[1])
        pygame.draw.rect(screen, (220, 220, 220),
                         pygame.Rect(bx - 5, by - 5, 10, 10))

    # Pitcher's mound — grayscale to match the diamond.
    pygame.draw.circle(screen, (35, 35, 35), ha.PITCHERS_MOUND, 14)
    pygame.draw.circle(screen, (180, 180, 180), ha.PITCHERS_MOUND, 14, 1)

    # Home plate
    pygame.draw.polygon(screen, (220, 220, 220), [
        (hx - 8, hy - 8), (hx + 8, hy - 8), (hx + 8, hy),
        (hx, hy + 6), (hx - 8, hy),
    ], 0)
