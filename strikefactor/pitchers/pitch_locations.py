"""Named pitch-location archetypes, loaded from data/pitch_locations.json.

An archetype is one recognisable way a pitch gets used — a back-foot slider,
a backdoor slider and a get-me-over slider are the same pitch aimed at three
completely different places. Before this, location was "pick a random zone
edge", which is why every slider from a given pitcher traced the same arc.

The same file carries the at-bat plans and each pitcher's plan mix
(`PLANS`, `PLAN_MIX`); see at_bat_plan.py.

Lookup order for (pitcher, pitch type, platoon):
    pitchers[<pitcher>][<pitch>][<platoon>]  → per-pitcher signature pitch
    defaults[<pitch>][<platoon>]             → per-pitch-type baseline
    None                                     → caller falls back to generic geometry
"""

import json
import os

_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'pitch_locations.json')

# In the column order of Pitcher.INTENT_TABLE.
INTENTS = ('zone', 'edge', 'chase', 'waste')
VALID_INTENTS = set(INTENTS)
_REQUIRED = ('name', 'intent', 'weight', 'in_away', 'height', 'spread_x', 'spread_z')


def _validate(archetypes, where):
    """Drop malformed archetypes rather than crashing mid-game on bad data."""
    clean = []
    for a in archetypes:
        missing = [k for k in _REQUIRED if k not in a]
        if missing:
            print(f"[WARNING] pitch_locations {where}: archetype "
                  f"{a.get('name', '?')} missing {missing}, skipped")
            continue
        if a['intent'] not in VALID_INTENTS:
            print(f"[WARNING] pitch_locations {where}: archetype {a['name']} "
                  f"has unknown intent '{a['intent']}', skipped")
            continue
        clean.append(a)
    return clean


def _validate_mix(mix, plans, where):
    """Drop plan-mix entries naming an undefined plan or with no weight."""
    clean = {}
    for name, weight in mix.items():
        if name not in plans or weight <= 0:
            print(f"[WARNING] pitch_locations {where}/_plans: plan '{name}' "
                  f"undefined or weight {weight}, skipped")
            continue
        clean[name] = weight
    return clean


def _load():
    try:
        with open(_PATH, 'r') as f:
            raw = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[WARNING] Could not load pitch_locations.json ({e}); "
              f"falling back to generic pitch targeting")
        raw = {}

    def clean_group(group, label):
        out = {}
        for pitch, platoons in group.items():
            if pitch.startswith('_'):
                continue
            out[pitch] = {
                pl: _validate(arch, f"{label}/{pitch}/{pl}")
                for pl, arch in platoons.items() if not pl.startswith('_')
            }
        return out

    defaults = clean_group(raw.get('defaults', {}), 'defaults')
    raw_pitchers = {name: pitches for name, pitches in raw.get('pitchers', {}).items()
                    if not name.startswith('_')}
    pitchers = {name: clean_group(pitches, name) for name, pitches in raw_pitchers.items()}
    # At-bat plans (see at_bat_plan.py) and each pitcher's mix of them. The
    # mix sits under the pitcher's own entry as "_plans", which clean_group
    # skips because it is not a pitch type.
    plans = {name: phases for name, phases in raw.get('plans', {}).items()
             if not name.startswith('_')}
    plan_mix = {name: _validate_mix(pitches.get('_plans', {}), plans, name)
                for name, pitches in raw_pitchers.items()}
    return defaults, pitchers, plans, plan_mix


DEFAULT_LOCATIONS, PITCHER_LOCATIONS, PLANS, PLAN_MIX = _load()


def get_archetypes(pitcher_key, pitch_type, platoon):
    """Archetypes for one (pitcher, pitch, platoon), or [] if none defined.

    A per-pitcher entry that only defines one platoon still falls back to the
    defaults for the other, so a signature pitch can be tuned for just the
    matchup that matters.
    """
    by_pitch = PITCHER_LOCATIONS.get(pitcher_key, {}).get(pitch_type)
    if by_pitch and by_pitch.get(platoon):
        return by_pitch[platoon]
    return DEFAULT_LOCATIONS.get(pitch_type, {}).get(platoon, [])
