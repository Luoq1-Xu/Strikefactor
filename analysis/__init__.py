"""StrikeFactor offline analysis package.

Layered so that metrics are computed once and rendered many ways:

    data     SQLite -> pandas, derived columns, Context
    filters  mode / difficulty / handedness / pitcher slicing
    metrics  pure DataFrame -> DataFrame statistics (no I/O, no drawing)
    theme    palettes, labels, benchmarks
    render_mpl / render_term   the two renderers
    figures  one module per PNG figure, registered in figures.FIGURES
    report   HTML index over the generated PNGs

Entry points are the repo-root scripts pitch_analysis.py and
batting_analysis.py.
"""

__all__ = ["data", "filters", "metrics", "theme", "report"]
