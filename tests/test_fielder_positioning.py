"""Where the defenders stand before the pitch.

Corner infielders don't play on their bases. A 1B standing on the bag is
holding a runner and a 3B standing on it is guarding the line — both are
situational alignments, not the default one. The homes had drifted to
~8 ft off their bags, which under this projection is 9 px: the 8 px
fielder body drew on top of the 10 px base square, so on screen the two
corners looked glued to first and third.

These guard the default alignment — off the bag, at realistic depth, and
still inside their own quadrant of the diamond.
"""

import math

from strikefactor.gameplay.hit_animation import (
    BASES,
    BODY_RADIUS_PX,
    FIELDER_HOMES,
    FT_TO_PX_X,
    FT_TO_PX_Y,
    HOME,
)

CORNERS = ("1B", "3B")


def _feet_from_plate(pos):
    """Screen position back-projected to real feet from home plate."""
    return ((pos[0] - HOME[0]) / FT_TO_PX_X, (HOME[1] - pos[1]) / FT_TO_PX_Y)


def test_corner_infielders_do_not_stand_on_their_bases():
    """The report this file exists for: the body must clear the bag, with
    daylight between them, not merely miss its centre."""
    for role in CORNERS:
        gap = math.dist(FIELDER_HOMES[role], BASES[role])
        assert gap > BODY_RADIUS_PX * 2, (
            f"{role} home is {gap:.0f} px from the bag — the fielder is "
            f"drawn on top of it")


def test_corner_infielders_play_behind_the_bag():
    """Further from home than the base, along the foul line — a corner IF
    plays on the outfield side of the base path."""
    for role in CORNERS:
        x_ft, y_ft = _feet_from_plate(FIELDER_HOMES[role])
        assert math.hypot(x_ft, y_ft) > 90.0, f"{role} plays in front of the bag"


def test_corner_infielders_play_at_realistic_depth():
    """~100–115 ft from the plate: behind the base path but well in front
    of the infield-grass arc (~128 ft out along the line)."""
    for role in CORNERS:
        depth = math.hypot(*_feet_from_plate(FIELDER_HOMES[role]))
        assert 100.0 <= depth <= 115.0, f"{role} plays at {depth:.0f} ft"


def test_corner_infielders_play_inside_their_foul_lines():
    """Off the bag means toward the middle of the diamond, in fair
    territory — never into foul ground beside the line."""
    for role in CORNERS:
        x_ft, y_ft = _feet_from_plate(FIELDER_HOMES[role])
        assert abs(x_ft) < y_ft, f"{role} home is in foul territory"


def test_corner_infielders_stay_in_front_of_the_middle_infielders():
    """Depth is a step off the bag, not a slide into the middle-IF band."""
    for corner, middle in (("1B", "2B"), ("3B", "SS")):
        assert (_feet_from_plate(FIELDER_HOMES[corner])[1]
                < _feet_from_plate(FIELDER_HOMES[middle])[1] - 20.0)


def test_the_two_corners_are_mirror_images():
    """Same helper, opposite side — the only asymmetry should be depth."""
    x_first, _ = _feet_from_plate(FIELDER_HOMES["1B"])
    x_third, _ = _feet_from_plate(FIELDER_HOMES["3B"])
    assert x_first > 0 > x_third
