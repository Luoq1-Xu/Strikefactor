"""Entry point for ``python -m strikefactor``.

Running ``strikefactor/main.py`` directly no longer works: the modules import
each other as ``strikefactor.<module>``, which requires the *repository root*
on sys.path, not the package directory. Launch the game with:

    python -m strikefactor
"""

from strikefactor.main import main

if __name__ == "__main__":
    main()
