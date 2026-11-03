"""One 90-foot diamond, shared by motion, throws, tags and projection."""

import math

AXIS_FT = 90.0 / math.sqrt(2)
BASE_FT = {0: (0.0, 0.0), 1: (AXIS_FT, AXIS_FT),
           2: (0.0, 2 * AXIS_FT), 3: (-AXIS_FT, AXIS_FT), 4: (0.0, 0.0)}
