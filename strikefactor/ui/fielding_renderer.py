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
    for runner in ((frame.runner,) if frame.runner is not None else ()) + frame.runners:
        # The small foot marker is the contact anchor. The body sits above
        # it so its radius cannot imply an early arrival at the bag.
        x, y = map(round, runner.pos)
        color = (71, 204, 252) if runner.runner_id == "B" else (100, 220, 175)
        if runner.state == "out":
            color = (130, 140, 150)
        if runner.state == "sliding":
            pygame.draw.line(screen, color, (x-9, y-3), (x+3, y-3), 5)
        else:
            pygame.draw.circle(screen, (15, 25, 30), (x, y - 9), 8)
            pygame.draw.circle(screen, color, (x, y - 9), 6)
        pygame.draw.circle(screen, color, (x, y), 2)
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
    if frame.first_base_call is not None:
        verdict, margin_s = frame.first_base_call
        gap = abs(margin_s)
        detail = "EVEN" if gap == 0 else ("<0.01s" if gap < 0.01 else f"{gap:.2f}s")
        text = f"{verdict} · {detail}" if gap == 0 else f"{verdict} BY {detail}"
        color = (71, 204, 252) if verdict == "SAFE" else (255, 195, 120)
        bx, by = ha.BASES["1B"]
        _label(screen, text, 24, color, (round(bx + 40), round(by - 43)), 1.0, 1)
    if frame.base_call is not None:
        verdict, base, margin_s = frame.base_call
        where = "HOME" if base == 4 else f"{base}B"
        color = (71, 204, 252) if verdict == "SAFE" else (255, 195, 120)
        point = ha.HOME if base == 4 else ha.BASES[f"{base}B"]
        _label(screen, f"{verdict} AT {where}", 24, color,
               (round(point[0]), round(point[1]-43)), 1.0, 1)
    if frame.send_control is not None:
        rid, state, remaining, destination, key = frame.send_control[:5]
        runners = ((frame.runner,) if frame.runner is not None else ()) + frame.runners
        selected = next((r for r in runners if r.runner_id == rid), None)
        color = (255, 230, 120)
        if selected is not None:
            x, y = map(round, selected.pos)
            pygame.draw.circle(screen, color, (x, y-7), 13, 2)

        def base_name(base):
            return "HOME" if base == 4 else f"{base}B"

        if len(frame.send_control) == 5:
            text = (f"{key.upper()}  SEND LEAD RUNNER" if state == "available" else
                    "SEND QUEUED" if state == "armed" else f"GOING TO {base_name(destination)}")
            _label(screen, text, 25, color, (screen.get_width()//2, 46), 1.0, 1)
        else:
            retreat, retreat_key, send, pending, cancel = frame.send_control[5:]
            verb = ("AT" if selected is not None and selected.state == "holding" else
                    "RETURNING TO" if selected is not None and selected.state == "returning" else "TO")
            heading = f"LEAD  {verb} {base_name(destination)}"
            if pending is not None:
                heading += f"  /  THEN {base_name(pending)}"
            choices = []
            if send is not None:
                choices.append(f"{key.upper()}  SEND TO {base_name(send)}")
            if retreat is not None:
                choices.append(f"{retreat_key.upper()}  {'HOLD AT' if cancel else 'RETURN TO'} {base_name(retreat)}")
            _label(screen, heading, 25, color, (screen.get_width()//2, 42), 1.0, 1)
            _label(screen, "     ".join(choices), 23, color, (screen.get_width()//2, 66), 1.0, 1)
        if remaining is not None:
            bar = pygame.Rect(screen.get_width()//2-100, 84, 200, 4)
            pygame.draw.rect(screen, (65, 65, 65), bar)
            pygame.draw.rect(screen, color, (bar.x, bar.y, round(bar.width*remaining), bar.height))


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
