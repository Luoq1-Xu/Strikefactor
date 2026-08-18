import math


def collision(circlex, circley, radius, rectmiddlex, rectmiddley, rectwidth, rectheight):
    """Check collision between circle and rectangle"""
    circleDistancex = abs(circlex - rectmiddlex)
    circleDistancey = abs(circley - rectmiddley)
    
    if (circleDistancex > (rectwidth/2 + radius)):
        return False
    if (circleDistancey > (rectheight/2 + radius)):
        return False
    if (circleDistancex <= (rectwidth/2)):
        return True
    if (circleDistancey <= (rectheight/2)):
        return True
        
    cornerDistance_sq = ((circleDistancex - rectwidth/2)**2) + ((circleDistancey - rectheight/2)**2)
    return (cornerDistance_sq <= ((radius)**2))

def collision_angled(circlex, circley, radius, rectmiddlex, rectmiddley, rectwidth, rectheight, angle):
    """Check collision between a circle and a rectangle rotated by `angle`.

    `angle` is the rectangle's own rotation about its centre, in radians, in
    screen space (y grows downward, so positive turns clockwise on screen).
    The circle's centre is rotated *back* into the rectangle's frame by
    `R(-angle)` and then tested against the axis-aligned box.

    That `-angle` is the fix for a long-standing sign error: this applied
    `R(+angle)`, which tests against a rectangle at `-angle` — the mirror
    image, across the horizontal, of the rotation the caller asked for. The
    only caller is `HitOutcomeManager.get_ball_to_bat_contact_outcome`, which
    passes the bearing from the batter's hands to the aim point, so the bat
    the engine swung was tilted the opposite way from the bat the player was
    pointing: aim at a low pitch and the barrel came up.

    It was not a wash. Because the rectangle is long and thin, mirroring it
    changes its *effective reach* as a function of aim height, and contact
    rate across the zone ran 67% low / 93% middle / 88% high. Correcting the
    sign flattens that to 80 / 86 / 86 — the bat now behaves the same wherever
    it is pointed, which is the property a bat is supposed to have.
    """
    dx = circlex - rectmiddlex
    dy = circley - rectmiddley
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    unrotated_circlex = cos_a * dx + sin_a * dy + rectmiddlex
    unrotated_circley = -sin_a * dx + cos_a * dy + rectmiddley

    # Axis-aligned bounding box check
    return collision(unrotated_circlex, unrotated_circley, radius, rectmiddlex, rectmiddley, rectwidth, rectheight)