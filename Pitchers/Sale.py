from helper import pitcher
import random
import pygame

class Sale(pitcher.Pitcher):

    def __init__(self, screen, loadfunc) -> None:
        super().__init__((screen.get_width() / 2) - 40,
                         (screen.get_height() / 3) + 180,
                         pygame.Vector2((screen.get_width() / 2) + 61, (screen.get_height() / 3) + 209),
                         screen,
                         'Chris Sale')
        self.load_img(loadfunc, 'Images/LEFTY', 9)
        self.add_pitch_type(self.saleMiddleMiddleFastball, 'FF')
        self.add_pitch_type(self.saleChangeup, 'CH')
        self.add_pitch_type(self.saleSlider, 'SL')

    def saleMiddleMiddleFastball(self, simulation_func):
        sampley = random.uniform(0,20)
        samplex = random.uniform(-10,-30)
        simulation_func(self.release_point, 'chrissale', 0.01, 0.01, samplex, sampley, 380, 'FF')

    def saleChangeup(self, simulation_func):
        sampley = random.uniform(-10,10)
        samplex = random.uniform(-20,0)
        simulation_func(self.release_point, 'chrissale', 0.01, 0.04, samplex, sampley, 420, 'CH')

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

    def saleSinker(self, main_simulation):
        sampley = random.uniform(0,10)
        samplex = random.uniform(-25,5)
        main_simulation(self.release_point, 'chrissale', 0.015, 0.035, samplex, sampley, 400, 'FF')

    def saleUpLeftFastball(self, main_simulation):
        sampley = random.uniform(0,-25)
        samplex = random.uniform(-45,-15)
        main_simulation(self.release_point, 'chrissale', 0.005, 0.01, samplex, sampley, 400, 'FF')
    def saleDownRightFastball(self, main_simulation):
        sampley = random.uniform(10,30)
        samplex = random.uniform(-20,5)
        main_simulation(self.release_point, 'chrissale', 0.015, 0.01, samplex, sampley, 380, 'FF')
    def saleMiddleMiddleFastball(self, main_simulation):
        sampley = random.uniform(0,20)
        samplex = random.uniform(-10,-40)
        main_simulation(self.release_point, 'chrissale', 0.015, 0.01, samplex, sampley, 380, 'FF')
    def saleDownLeftFastball(self, main_simulation):
        sampley = random.uniform(10,25)
        samplex = random.uniform(-35,-50)
        main_simulation(self.release_point, 'chrissale', 0.01, 0.01, samplex, sampley, 380, 'FF')
    def saleUpRightFastball(self, main_simulation):
        sampley = random.uniform(10, -20)
        samplex = random.uniform(-25,0)
        main_simulation(self.release_point, 'chrissale', 0.015, 0.01, samplex, sampley, 380, 'FF')
    def saleChangeup(self, main_simulation):
        sampley = random.uniform(-10,10)
        samplex = random.uniform(-30,5)
        main_simulation(self.release_point, 'chrissale', 0.01, 0.0225, samplex, sampley, 450, 'CH')
    def saleSlider(self, main_simulation):
        sampley = random.uniform(-20,5)
        samplex = random.uniform(-40,25)
        main_simulation(self.release_point, 'chrissale', -0.015, 0.05, samplex, sampley, 500, 'SL')



