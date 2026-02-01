from .pitcher import Pitcher
import random
import pygame
from utils.physics import calculate_pitch_velocity, calculate_travel_time

class Sale(Pitcher):

    def __init__(self, screen, loadfunc) -> None:
        super().__init__((screen.get_width() / 2) - 40,
                         (screen.get_height() / 3) + 180,
                         pygame.Vector2((screen.get_width() / 2) + 61, (screen.get_height() / 3) + 209),
                         screen,
                         'Chris Sale',
                         1100,
                         6.7)  # arm_extension in feet
        self.load_img(loadfunc, 'assets/images/sale/LEFTY', 9)
        self.add_pitch_type(self.FF, 'FF')
        self.add_pitch_type(self.SL, 'SL')
        self.add_pitch_type(self.CH, 'CH')
        self.add_pitch_type(self.SI, 'SI')

    def draw_pitcher(self, start_time, current_time):
        if current_time == 0 and start_time == 0:
            self.draw(self.screen, 1)
        if current_time <= start_time + 300:
            self.draw(self.screen, 1)
        elif current_time > start_time + 300 and current_time <= start_time + 500:
            self.draw(self.screen, 2)
        elif current_time > start_time + 500 and current_time <= start_time + 700:
            self.draw(self.screen, 3)
        elif current_time > start_time + 700 and current_time <= start_time + 900:
            self.draw(self.screen, 4)
        elif current_time > start_time + 900 and current_time <= start_time + 1000:
            self.draw(self.screen, 5, 0, 10)
        elif current_time > start_time + 1000 and current_time <= start_time + 1100:
            self.draw(self.screen, 6, 10, 25)
        elif current_time > start_time + 1100 and current_time <= start_time + 1120:
            self.draw(self.screen, 7, 8, 22)
        elif current_time > start_time + 1120 and current_time <= start_time + 1140:
            self.draw(self.screen, 8, -11, 22)
        elif current_time > start_time + 1140:
            self.draw(self.screen, 9, 16, 22)

    def SL(self, simulation_func):
        ax, ay = -0.02, 0.045
        speed_mph = random.gauss(79.0, 1.0)
        travel_time = calculate_travel_time(speed_mph, self.arm_extension)

        # Specify target location directly (with optional randomness)
        target_x = random.uniform(490, 700)  # x position at plate
        target_y = random.uniform(480, 620)  # y position at plate

        vx, vy = calculate_pitch_velocity(
            self.release_point,
            target_x=target_x,
            target_y=target_y,
            ax=ax,
            ay=ay,
            traveltime=travel_time
        )

        simulation_func(self.release_point, 'chrissale', ax, ay, vx, vy, travel_time, 'SL')

    def FF(self, simulation_func):
        ax, ay = 0.005, 0.005
        speed_mph = random.gauss(94.8, 0.25)
        travel_time = calculate_travel_time(speed_mph, self.arm_extension)

        # Specify target location directly (with optional randomness)
        target_x = random.uniform(490, 670)  # x position at plate
        target_y = random.uniform(420, 600)  # y position at plate

        vx, vy = calculate_pitch_velocity(
            self.release_point,
            target_x=target_x,
            target_y=target_y,
            ax=ax,
            ay=ay,
            traveltime=travel_time
        )

        simulation_func(self.release_point, 'chrissale', ax, ay, vx, vy, travel_time, 'FF')

    def SI(self, simulation_func):
        ax, ay = 0.025, 0.015
        speed_mph = random.gauss(93.9, 0.25)
        travel_time = calculate_travel_time(speed_mph, self.arm_extension)

        # Specify target location directly (with optional randomness)
        target_x = random.uniform(490, 670)  # x position at plate
        target_y = random.uniform(420, 600)  # y position at plate

        vx, vy = calculate_pitch_velocity(
            self.release_point,
            target_x=target_x,
            target_y=target_y,
            ax=ax,
            ay=ay,
            traveltime=travel_time
        )

        simulation_func(self.release_point, 'chrissale', ax, ay, vx, vy, travel_time, 'SI')

    def CH(self, simulation_func):
        ax, ay = 0.015, 0.025
        speed_mph = random.gauss(87.0, 0.50)
        travel_time = calculate_travel_time(speed_mph, self.arm_extension)

        # Specify target location directly (with optional randomness)
        target_x = random.uniform(490, 670)  # x position at plate
        target_y = random.uniform(420, 600)  # y position at plate

        vx, vy = calculate_pitch_velocity(
            self.release_point,
            target_x=target_x,
            target_y=target_y,
            ax=ax,
            ay=ay,
            traveltime=travel_time
        )

        simulation_func(self.release_point, 'chrissale', ax, ay, vx, vy, travel_time, 'CH')

