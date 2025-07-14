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
    """Check collision between circle and rotated rectangle"""
    # Rotate circle's center point back
    unrotated_circlex = math.cos(angle) * (circlex - rectmiddlex) - math.sin(angle) * (circley - rectmiddley) + rectmiddlex
    unrotated_circley = math.sin(angle) * (circlex - rectmiddlex) + math.cos(angle) * (circley - rectmiddley) + rectmiddley

    # Axis-aligned bounding box check
    return collision(unrotated_circlex, unrotated_circley, radius, rectmiddlex, rectmiddley, rectwidth, rectheight)