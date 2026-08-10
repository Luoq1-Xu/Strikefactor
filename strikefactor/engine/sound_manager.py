import os
import random

import pygame

from strikefactor.config import get_path, resource_path
from strikefactor.engine.contact_audio import contact_sound_for


class SoundManager:
    def __init__(self, sound_dir="assets/sounds", settings_manager=None):
        self.sound_dir = sound_dir
        self.settings_manager = settings_manager
        self.sounds = {}
        self.pending_sounds = []
        self.load_sounds()

    def set_settings_manager(self, settings_manager):
        """Attach settings so playback can honour master_volume."""
        self.settings_manager = settings_manager

    def _master_volume(self):
        if self.settings_manager is None:
            return 1.0
        try:
            vol = float(self.settings_manager.get_setting("master_volume"))
        except (TypeError, ValueError):
            return 1.0
        return max(0.0, min(1.0, vol))

    # Assets are grouped by *sound source*, one directory per source, the
    # way umpire_sounds/ already was:
    #
    #   contact/       bat on ball, weakest -> hardest
    #   mitt/          catcher receiving a pitch
    #   umpire_sounds/ ball / strike / strike_3 calls
    #
    # Keys are named for what the sample sounds like, never for an outcome.
    # The contact samples used to be SINGLE/DOUBLE/TRIPLE/HOMERUN, which
    # stopped being true the moment selection moved to the exit-velocity
    # ladder in contact_audio — `contact_solid` plays on any ~95 mph ball
    # whatever the result. Keeping the source in the key (contact_ / mitt_)
    # is what stops a mitt slap being wired in as a bat sound again.
    CONTACT_DIR = "contact"
    MITT_DIR = "mitt"
    UMPIRE_DIR = "umpire_sounds"

    SOUND_FILES = {
        # Bat contact. engine/contact_audio.py's ladder refers to these keys.
        'contact_weak': f"{CONTACT_DIR}/weak.mp3",
        'contact_medium': f"{CONTACT_DIR}/medium.mp3",
        'contact_solid': f"{CONTACT_DIR}/solid.mp3",
        'contact_hard': f"{CONTACT_DIR}/hard.mp3",
        'contact_crushed': f"{CONTACT_DIR}/crushed.mp3",
        # Catcher's mitt on a caught pitch (see glovepop). NOT bat sounds.
        'mitt_pop_short': f"{MITT_DIR}/short.mp3",
        'mitt_pop_medium': f"{MITT_DIR}/medium.mp3",
        'mitt_pop_long': f"{MITT_DIR}/long.mp3",
        # Ball travelling through the air.
        'sizzle': "pitch_sizzle.mp3",
    }

    def load_sounds(self):
        # Load all game sounds
        sound_files = self.SOUND_FILES

        for name, filename in sound_files.items():
            full_path = resource_path(get_path(os.path.join(self.sound_dir, filename)))
            if os.path.exists(full_path):
                self.sounds[name] = pygame.mixer.Sound(full_path)
            else:
                print(f"Warning: Sound file not found at {full_path}")

        # Load umpire sounds from subdirectories
        umpire_dir = os.path.join(self.sound_dir, self.UMPIRE_DIR)

        # Load all strike call variants for random selection
        self.strike_sounds = []
        strike_dir = resource_path(get_path(os.path.join(umpire_dir, "strike")))
        if os.path.isdir(strike_dir):
            for f in os.listdir(strike_dir):
                if f.endswith(".mp3"):
                    self.strike_sounds.append(pygame.mixer.Sound(os.path.join(strike_dir, f)))

        # Load strike 3 call
        strike3_path = resource_path(get_path(os.path.join(umpire_dir, "strike_3", "strike_3.mp3")))
        if os.path.exists(strike3_path):
            self.sounds['strike3'] = pygame.mixer.Sound(strike3_path)

        # Load ball call variants for random selection (excluding low-ball-specific call)
        self.ball_sounds = []
        ball_dir = resource_path(get_path(os.path.join(umpire_dir, "ball")))
        if os.path.isdir(ball_dir):
            for f in os.listdir(ball_dir):
                if f.endswith(".mp3") and f != "no_thats_down_ball.mp3":
                    self.ball_sounds.append(pygame.mixer.Sound(os.path.join(ball_dir, f)))

        # Load low ball specific call
        ball_low_path = resource_path(get_path(os.path.join(umpire_dir, "ball", "no_thats_down_ball.mp3")))
        if os.path.exists(ball_low_path):
            self.sounds['ball_low'] = pygame.mixer.Sound(ball_low_path)
            
    def play(self, sound_name, volume=None):
        """Play a sound, optionally at a per-playback `volume` (0..1).

        Gain is applied to the *channel*, never to the Sound object. Sounds
        are shared singletons, so `Sound.set_volume()` would leak this
        playback's level into every later (and any concurrent) play of the
        same sample — a soft foul tick would quietly turn down the next
        home run. Channel volume is scoped to this one playback.
        """
        if sound_name == 'strike' and self.strike_sounds:
            sound = random.choice(self.strike_sounds)
        elif sound_name == 'ball' and self.ball_sounds:
            sound = random.choice(self.ball_sounds)
        elif sound_name in self.sounds:
            sound = self.sounds[sound_name]
        else:
            return None

        channel = sound.play()
        if channel is not None:
            gain = self._master_volume()
            if volume is not None:
                gain *= max(0.0, min(1.0, volume))
            channel.set_volume(gain)
        return channel

    def play_contact(self, quality, swing_type="contact", hr_distance_ft=None):
        """Play the bat-contact sound for a swing of the given quality.

        Single entry point for every bat-on-ball event — fouls, in-play
        contact and home runs alike. Selection and loudness both come from
        the modelled exit velocity, so the sample is a consequence of how
        hard the ball was struck rather than of which outcome was rolled.

        `hr_distance_ft` is the one exception, and it is not an outcome
        cue: on a home run the distance the player is about to see is a
        *better measurement* of how hard the ball was hit than quality is,
        because the carry model rolls its own randomness. Passing it keeps
        the crack and the 460 FT readout describing the same swing.

        Returns the modelled EV so callers can record it.
        """
        name, gain, ev = contact_sound_for(
            quality, swing_type=swing_type, available=self.sounds,
            hr_distance_ft=hr_distance_ft)
        self.play(name, volume=gain)
        return ev

    def schedule_sound(self, sound_name, delay=1000):
        """Schedule a sound to be played after a delay"""
        if sound_name in self.sounds or (sound_name == 'strike' and self.strike_sounds) or (sound_name == 'ball' and self.ball_sounds) or sound_name == 'ball_low':
            play_time = pygame.time.get_ticks() + delay
            self.pending_sounds.append((play_time, sound_name))
    
    def glovepop(self):
        """Catcher receiving a pitch. Weighted toward the short pop."""
        rand = random.randint(2, 5)
        if rand == 2:
            self.play('mitt_pop_short')
        elif rand == 3:
            self.play('mitt_pop_long')
        else:
            self.play('mitt_pop_medium')
        return

    def update(self):
        """Check and play scheduled sounds. This should be called once per frame."""
        current_time = pygame.time.get_ticks()
        # Iterate over a copy since we might modify the list
        for play_time, sound_name in list(self.pending_sounds):
            if current_time >= play_time:
                self.play(sound_name)
                self.pending_sounds.remove((play_time, sound_name))