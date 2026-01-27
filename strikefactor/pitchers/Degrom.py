from utils.physics import calculate_pitch_velocity, calculate_travel_time
from .pitcher import Pitcher
import random
import pygame

class Degrom(Pitcher):

    def __init__(self, screen, loadfunc) -> None:
        super().__init__((screen.get_width() / 2) - 30,
                         (screen.get_height() / 3) + 175,
                         pygame.Vector2((screen.get_width() / 2) - 45, (screen.get_height() / 3) + 187),
                         screen,
                         'Jacob deGrom',
                         1100,
                         6.7)  # arm_extension in feet
        self.load_img(loadfunc, 'assets/images/degrom/RIGHTY', 9)
        self.add_pitch_type(self.CB, "CB")
        self.add_pitch_type(self.FB_strike, "FF_strike")
        self.add_pitch_type(self.FB_chase, "FF_chase")
        self.add_pitch_type(self.SL, "SL")
        self.add_pitch_type(self.CH, "CH")
        
    def draw_pitcher(self, start_time, current_time):
        if current_time == 0 and start_time == 0:
            self.draw(self.screen, 1)
        if current_time <= start_time + 300:
            self.draw(self.screen, 1)
        elif current_time > start_time + 300 and current_time <= start_time + 500:
            self.draw(self.screen, 2, -10, 0)
        elif current_time > start_time + 500 and current_time <= start_time + 700:
            self.draw(self.screen, 3, -13, 0)
        elif current_time > start_time + 700 and current_time <= start_time + 900:
            self.draw(self.screen, 4, -27, 5)
        elif current_time > start_time + 900 and current_time <= start_time + 1000:
            self.draw(self.screen, 5, -33, 12)
        elif current_time > start_time + 1000 and current_time <= start_time + 1100:
            self.draw(self.screen, 6, 12, 13)
        elif current_time > start_time + 1100 and current_time <= start_time + 1110:
            self.draw(self.screen, 7, -20, 7)
        elif current_time > start_time + 1110 and current_time <= start_time + 1140:
            self.draw(self.screen, 8, 0, 27)
        elif current_time > start_time + 1140:
            self.draw(self.screen, 9, -11, 25)

    def CB(self, simulation_func):
        ax, ay = 0.005, 0.045
        speed_mph = random.gauss(81.0, 1.0)
        travel_time = calculate_travel_time(speed_mph, self.arm_extension)

        # Specify target location directly (with optional randomness)
        target_x = random.uniform(590, 670)  # x position at plate
        target_y = random.uniform(520, 620)  # y position at plate

        vx, vy = calculate_pitch_velocity(
            self.release_point,
            target_x=target_x,
            target_y=target_y,
            ax=ax,
            ay=ay,
            traveltime=travel_time
        )

        simulation_func(self.release_point, 'jacobdegrom', ax, ay, vx, vy, travel_time, 'CB')

    def FB_strike(self, simulation_func):
        ax, ay = -0.0075, 0.005
        speed_mph = random.gauss(99.0, 1.0)
        travel_time = calculate_travel_time(speed_mph, self.arm_extension)

        # Specify target location directly (with optional randomness)
        target_x = random.uniform(590, 670)  # x position at plate
        target_y = random.uniform(380, 520)  # y position at plate

        vx, vy = calculate_pitch_velocity(
            self.release_point,
            target_x=target_x,
            target_y=target_y,
            ax=ax,
            ay=ay,
            traveltime=travel_time
        )

        simulation_func(self.release_point, 'jacobdegrom', ax, ay, vx, vy, travel_time, 'FF')

    def FB_chase(self, simulation_func):
        ax, ay = -0.0075, 0.005
        speed_mph = random.gauss(99.0, 2.5)
        travel_time = calculate_travel_time(speed_mph, self.arm_extension)

        # Specify target location directly (with optional randomness)
        target_x = random.choice([random.uniform(490, 520), random.uniform(580, 650)]) # x position at plate
        target_y = random.choice([random.uniform(400, 450), random.uniform(550, 600)]) # y position at plate

        vx, vy = calculate_pitch_velocity(
            self.release_point,
            target_x=target_x,
            target_y=target_y,
            ax=ax,
            ay=ay,
            traveltime=travel_time
        )

        simulation_func(self.release_point, 'jacobdegrom', ax, ay, vx, vy, travel_time, 'FF')


    def SL(self, simulation_func):
        ax, ay = 0.015, 0.04
        speed_mph = random.gauss(91.0, 1.0)
        travel_time = calculate_travel_time(speed_mph, self.arm_extension)

        # Specify target location directly (with optional randomness)
        target_x = random.uniform(590, 670)  # x position at plate
        target_y = random.uniform(480, 620)  # y position at plate

        vx, vy = calculate_pitch_velocity(
            self.release_point,
            target_x=target_x,
            target_y=target_y,
            ax=ax,
            ay=ay,
            traveltime=travel_time
        )

        simulation_func(self.release_point, 'jacobdegrom', ax, ay, vx, vy, travel_time, 'SL')

    def CH(self, simulation_func):
        ax, ay = -0.015, 0.035
        speed_mph = random.gauss(89.0, 1.5)
        travel_time = calculate_travel_time(speed_mph, self.arm_extension)

        # Specify target location directly (with optional randomness)
        target_x = random.uniform(590, 670)  # x position at plate
        target_y = random.uniform(500, 620)  # y position at plate

        vx, vy = calculate_pitch_velocity(
            self.release_point,
            target_x=target_x,
            target_y=target_y,
            ax=ax,
            ay=ay,
            traveltime=travel_time
        )

        simulation_func(self.release_point, 'jacobdegrom', ax, ay, vx, vy, travel_time, 'CH')
        

