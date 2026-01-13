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


def simulate_pitch_trajectory(release_x, release_y, vx, vy, ax, ay, traveltime, z_start=4600, z_end=300, fps=60):
    """
    Simulate a pitch trajectory using the game's physics model.

    Args:
        release_x: Starting x position (release point)
        release_y: Starting y position (release point)
        vx: Initial x velocity
        vy: Initial y velocity
        ax: x acceleration (horizontal break)
        ay: y acceleration (vertical break)
        traveltime: Total travel time in milliseconds
        z_start: Starting z position (default 4600)
        z_end: Ending z position where dist=1 (default 300)
        fps: Frames per second (default 60)

    Returns:
        Tuple of (final_x, final_y) - the position when pitch reaches the plate
    """
    x, y, z = release_x, release_y, z_start
    current_vx, current_vy = vx, vy

    # Z decreases by this amount per frame
    dz_per_frame = (4300 * 1000) / (fps * traveltime)

    # Simulate until z reaches z_end (dist = 1)
    while z > z_end:
        dist = z / 300
        if dist > 1:
            # Update position
            x += current_vx / dist
            y += current_vy / dist
            # Update z
            z -= dz_per_frame
            # Update velocity
            current_vy += (ay * 300) / dist
            current_vx += (ax * 300) / dist

    return x, y


def calculate_pitch_velocity(release_point, target_x, target_y, ax, ay, traveltime,
                             z_start=4600, z_end=300, fps=60, tolerance=0.01, max_iterations=100):
    """
    Calculate the initial velocity (vx, vy) needed for a pitch to arrive at a target location.

    This function uses the game's physics model to find the initial velocity components
    that will cause a pitch to land at the specified target coordinates when it reaches
    the plate.

    Args:
        release_point: Tuple/Vector2 of (x, y) for the pitcher's release point
        target_x: Target x coordinate where pitch should arrive
        target_y: Target y coordinate where pitch should arrive
        ax: x acceleration (horizontal break, e.g., -0.015 for arm-side run)
        ay: y acceleration (vertical break, e.g., 0.01 for sink, negative for rise)
        traveltime: Pitch travel time in milliseconds (e.g., 370 for fastball, 420 for changeup)
        z_start: Starting z position (default 4600)
        z_end: Ending z position (default 300)
        fps: Frames per second (default 60)
        tolerance: Convergence tolerance in pixels (default 0.01)
        max_iterations: Maximum optimization iterations (default 100)

    Returns:
        Tuple of (vx, vy) - the initial velocity components needed

    Example usage in a pitcher class:
        from utils.physics import calculate_pitch_velocity

        def my_fastball(self, simulation_func):
            # Define pitch characteristics
            ax, ay = -0.015, 0.010  # horizontal run, vertical sink
            traveltime = 370

            # Target location (with some randomness)
            target_x = random.uniform(590, 670)  # around strike zone
            target_y = random.uniform(450, 520)  # around strike zone

            # Calculate required velocity
            vx, vy = calculate_pitch_velocity(
                self.release_point, target_x, target_y, ax, ay, traveltime
            )

            simulation_func(self.release_point, 'pitcher_name', ax, ay, vx, vy, traveltime, 'FF')
    """
    release_x, release_y = release_point[0], release_point[1]

    # Use bisection/iterative approach for each dimension independently
    # Since x and y physics are independent, we can solve them separately

    def find_velocity_for_target(release_val, target_val, accel, is_x=True):
        """Find the initial velocity needed to reach target in one dimension."""
        # Start with a reasonable initial guess based on distance and time
        distance = target_val - release_val

        # Initial guess: simple linear estimate
        v_guess = distance / 10  # rough starting point

        # Bounds for binary search
        v_low, v_high = -200, 200

        for _ in range(max_iterations):
            # Simulate with current guess
            if is_x:
                final_pos, _ = simulate_pitch_trajectory(
                    release_x, release_y, v_guess, 0, accel, 0, traveltime, z_start, z_end, fps
                )
            else:
                _, final_pos = simulate_pitch_trajectory(
                    release_x, release_y, 0, v_guess, 0, accel, traveltime, z_start, z_end, fps
                )

            error = final_pos - target_val

            if abs(error) < tolerance:
                return v_guess

            # Adjust bounds and make new guess
            if error > 0:
                v_high = v_guess
            else:
                v_low = v_guess

            v_guess = (v_low + v_high) / 2

        return v_guess

    vx = find_velocity_for_target(release_x, target_x, ax, is_x=True)
    vy = find_velocity_for_target(release_y, target_y, ay, is_x=False)

    return vx, vy


def create_targeted_pitch(release_point, target_x, target_y, ax, ay, traveltime):
    """
    Convenience function to create pitch parameters for a targeted location.

    Args:
        release_point: Pitcher's release point (x, y)
        target_x: Target x coordinate
        target_y: Target y coordinate
        ax: Horizontal acceleration (break)
        ay: Vertical acceleration (movement)
        traveltime: Pitch travel time in ms

    Returns:
        Dict with all pitch parameters ready for simulation:
        {
            'ax': ax,
            'ay': ay,
            'vx': calculated vx,
            'vy': calculated vy,
            'traveltime': traveltime
        }
    """
    vx, vy = calculate_pitch_velocity(release_point, target_x, target_y, ax, ay, traveltime)
    return {
        'ax': ax,
        'ay': ay,
        'vx': vx,
        'vy': vy,
        'traveltime': traveltime
    }


def calculate_travel_time(speed_mph: float, arm_extension: float) -> float:
    """
    Calculate pitch travel time in milliseconds from speed and arm extension.

    Args:
        speed_mph: Pitch speed in miles per hour
        arm_extension: Pitcher's arm extension in feet (reduces effective distance)

    Returns:
        Travel time in milliseconds

    Formula:
        distance = 60.5 feet (mound to plate) - arm_extension
        time = distance / speed, converted to milliseconds
    """
    distance = 60.5 - arm_extension
    return distance * 1000 * 3600 / (speed_mph * 5280)