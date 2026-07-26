"""Real-world pitch usage priors, used to anchor the Q-learning pitch mix.

The Q-table on its own converges on whatever single pitch beats the current
human player, which produces mixes no MLB starter would ever throw (logged
games had Sasaki at 50% splitters and 32% fastballs against a real ~48% FF /
~34% FS). These priors are blended into action selection as a log-prior term
so the AI still adapts, but around a believable baseline arsenal usage.

Numbers are approximate season-level Statcast mixes and are meant to be
tuned; verify against Baseball Savant before treating any of them as exact.
Keys are the internal pitcher names used by PitcherManager, and each mix must
cover exactly that pitcher's registered arsenal (see `validate_usage_priors`).
"""

# Base usage fractions per pitcher. Values are normalized at attach time, so
# they only need to be proportionally right.
BASE_USAGE = {
    'sale': {
        'FF': 0.34,
        'SL': 0.33,
        'CH': 0.22,
        'SI': 0.11,
    },
    'degrom': {
        'FF': 0.52,
        'SL': 0.28,
        'CH': 0.11,
        'CB': 0.09,
    },
    'yamamoto': {
        'FF': 0.38,
        'FS': 0.23,
        'CB': 0.19,
        'FC': 0.12,
        'SI': 0.08,
    },
    'sasaki': {
        'FF': 0.48,
        'FS': 0.34,
        'SL': 0.18,
    },
    'mcclanahan': {
        'FF': 0.47,
        'CH': 0.24,
        'SL': 0.21,
        'CB': 0.08,
    },
}


def validate_usage_priors(name, arsenal):
    """Return the prior mix for `name` restricted to `arsenal`, or None.

    Warns (rather than raising) when a mix does not line up with the
    pitcher's registered pitches, so adding a pitch to an arsenal without
    updating this table degrades to uniform instead of crashing the game.
    """
    mix = BASE_USAGE.get(name)
    if not mix:
        return None

    arsenal = set(arsenal)
    missing = arsenal - set(mix)
    extra = set(mix) - arsenal
    if missing:
        print(f"[WARNING] No usage prior for {name} pitches {sorted(missing)}")
    if extra:
        print(f"[WARNING] Usage prior for {name} lists unknown pitches {sorted(extra)}")

    filtered = {p: w for p, w in mix.items() if p in arsenal}
    return filtered or None
