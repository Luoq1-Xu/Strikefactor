from helper import pitcher
import random
import pygame

class Degrom(pitcher.Pitcher):

    def __init__(self, screen, loadfunc) -> None:
        super().__init__((screen.get_width() / 2) - 30,
                         (screen.get_height() / 3) + 175,
                         pygame.Vector2((screen.get_width() / 2) - 45, (screen.get_height() / 3) + 187),
                         screen,
                         'Jacob deGrom')
        self.load_img(loadfunc, 'Images/RIGHTY', 9)
        self.add_pitch_type(self.deGromFBD, "FFD")
        self.add_pitch_type(self.deGromFBU, "FFU")
        self.add_pitch_type(self.deGromFBM, "FFM")

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

    def deGromFB1(self, simulation_func):
            sampley = random.uniform(0,10)
            samplex = random.uniform(-10,10)
            simulation_func(self.release_point, 'jacobdegrom', -0.015, 0.015, samplex, sampley, 370, 'FF')

    def deGromFBU(self, simulation_func):
            sampley = random.uniform(-25,5)
            samplex = random.uniform(-5,10)
            simulation_func(self.release_point, 'jacobdegrom', -0.015, 0.010, samplex, sampley, 370, 'FF')

    def deGromFB1(self, main_simulation):
        sampley = random.uniform(0,10)
        samplex = random.uniform(-10,10)
        main_simulation(self.release_point, 'jacobdegrom', -0.015, 0.015, samplex, sampley, 370, 'FF')
    def deGromFB2(self, main_simulation):
        sampley = random.uniform(10,30)
        samplex = random.uniform(15,35)
        main_simulation(self.release_point, 'jacobdegrom', -0.015, 0.0075, samplex, sampley, 370, 'FF')
    def deGromFBM(self, main_simulation):
        sampley = random.uniform(0,20)
        samplex = random.uniform(0,30)
        main_simulation(self.release_point, 'jacobdegrom', -0.015, 0.005, samplex, sampley, 370, 'FF')
    def deGromFBD(self, main_simulation):
        sampley = random.uniform(15,30)
        samplex = random.uniform(-5,35)
        main_simulation(self.release_point, 'jacobdegrom', -0.015, 0.005, samplex, sampley, 370, 'FF')
    
    def deGromSlider(self, main_simulation):
        sampley = random.uniform(5,-5)
        samplex = random.uniform(-20,20)
        main_simulation(self.release_point, 'jacobdegrom', 0.025, 0.04, samplex, sampley, 410, 'SL')
    def deGromChangeup(self, main_simulation):
        sampley = random.uniform(0,20)
        samplex = random.uniform(-10,30)
        main_simulation(self.release_point, 'jacobdegrom', -0.015, 0.0255, samplex, sampley, 420, 'CH')

