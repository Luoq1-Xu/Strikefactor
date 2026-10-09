"""The pitch-selection AI chooses from the game as it stands at the pitch.

`current_state` used to be whatever the previous pitch left behind, and the
first pitch of every game and half-inning inherited `reset_game_stats`'s
placeholder: a right-handed batter at 0-0, no outs, bases empty. A left-hander,
or a random scenario set up at 3-2 with the bases loaded, was pitched to as
that placeholder, and the Q-update for the pitch was keyed on it too.
"""

from types import SimpleNamespace

from strikefactor.ai.AI_2 import build_state
from strikefactor.gameplay.game_states import GameplayState, SandboxGameplayState
from strikefactor.main import Game


def test_the_first_pitch_is_chosen_from_the_real_count_runners_and_hand():
    seen = []
    pitcher = SimpleNamespace(
        _get_count_state=lambda: 'full',
        ai=SimpleNamespace(choose_action=lambda state, **kw: seen.append(state) or 'FF'),
        get_pitch_names=lambda: ['FF'],
        pitch=lambda simulate, name: None,
    )
    game = SimpleNamespace(
        first_pitch_thrown=False, current_pitcher=pitcher, batter_profile=None,
        pitch_history=[], pitch_chosen=None,
        # The placeholder a fresh game starts with.
        current_state=build_state(0, 0, 0, 0, 0, None, 'R', 0),
        currentouts=1, currentstrikes=2, currentballs=3, pitchnumber=0,
        last_pitch_type_thrown=None,
        scoreKeeper=SimpleNamespace(get_runners_on_base=lambda: 3, get_score=lambda: 0),
        batter=SimpleNamespace(get_handedness=lambda: 'L'),
    )
    game.build_ai_state = Game.build_ai_state.__get__(game)

    state = object.__new__(GameplayState)
    state.game = game
    state._initiate_pitch()

    expected = build_state(outs=1, strikes=2, balls=3, runners=3, pitch_number_in_ab=0,
                           prev_pitch=None, handedness='L', score_diff=0)
    assert seen == [expected]
    # And the Q-update reads the same state back off the game.
    assert game.current_state == expected


def test_the_first_sandbox_pitch_trains_on_the_real_state():
    seen = []
    pitcher = SimpleNamespace(pitch=lambda simulate, name: seen.append(name))
    game = SimpleNamespace(
        first_pitch_thrown=False, current_pitcher=pitcher, pitch_chosen=None,
        current_state='placeholder', currentouts=1, currentstrikes=2,
        currentballs=3, pitchnumber=0, last_pitch_type_thrown=None,
        scoreKeeper=SimpleNamespace(get_runners_on_base=lambda: 2,
                                    get_score=lambda: 0),
        batter=SimpleNamespace(get_handedness=lambda: 'L'),
    )
    game.build_ai_state = Game.build_ai_state.__get__(game)
    state = object.__new__(SandboxGameplayState)
    state.game = game
    state.active_pitches = {'FF'}

    state._initiate_pitch()

    expected = build_state(outs=1, strikes=2, balls=3, runners=2,
                           pitch_number_in_ab=0, prev_pitch=None,
                           handedness='L', score_diff=0)
    assert seen == ['FF']
    assert game.current_state == expected
