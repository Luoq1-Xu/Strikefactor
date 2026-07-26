"""Outcomes, count usage, and the full per-pitcher rate-stat table."""

import numpy as np
from matplotlib.gridspec import GridSpec

from .. import metrics, theme
from ..render_mpl import (empty_figure, figure_title, note, plt, save,
                          styled_table)


def outcomes(ctx):
    """Terminal outcomes per pitcher, as counts and as a share of PA."""
    tab = metrics.outcome_breakdown(ctx)
    if tab.empty:
        return empty_figure(ctx, "11_outcomes.png", "At-Bat Outcomes")

    x = np.arange(len(tab))

    fig, axes = plt.subplots(1, 2, figsize=(17, 6.5))
    figure_title(fig, "At-Bat Outcomes by Pitcher", ctx, y=1.02)

    for ax, normalize in zip(axes, (False, True)):
        data = tab.div(tab.sum(axis=1), axis=0) * 100 if normalize else tab
        bottoms = np.zeros(len(tab))
        for outcome in theme.OUTCOME_ORDER:
            vals = data[outcome].to_numpy(dtype=float)
            if vals.sum() <= 0:
                continue
            ax.bar(x, vals, bottom=bottoms, label=outcome,
                   color=theme.OUTCOME_COLORS.get(outcome, "#888"),
                   edgecolor=theme.BG, linewidth=0.5)
            bottoms += vals
        ax.set_xticks(x)
        ax.set_xticklabels([theme.pitcher_short(p) for p in tab.index], fontsize=10)
        ax.set_ylabel("% of plate appearances" if normalize else "Plate appearances")
        ax.set_title("Share of PA" if normalize else "Counts", fontweight="bold")
        ax.grid(True, axis="y")

    axes[1].legend(fontsize=9, loc="center left", bbox_to_anchor=(1.01, 0.5),
                   frameon=False)
    fig.tight_layout()
    return save(fig, ctx, "11_outcomes.png")


def count_usage(ctx):
    """Pitch-type usage by count, plus how each count state actually plays."""
    usage = metrics.usage_by_count(ctx)
    if usage.empty:
        return empty_figure(ctx, "12_count_usage.png", "Pitch Usage by Count")

    fig = plt.figure(figsize=(15, 9.5))
    figure_title(fig, "Pitch Selection by Count", ctx, y=0.99)
    gs = GridSpec(2, 1, figure=fig, hspace=0.36, height_ratios=[1.15, 1.0])

    ax = fig.add_subplot(gs[0, 0])
    mat = usage.to_numpy()
    im = ax.imshow(mat, cmap="YlOrRd", aspect="auto", vmin=0)
    ax.set_xticks(range(len(usage.columns)))
    ax.set_xticklabels(usage.columns)
    ax.set_yticks(range(len(usage.index)))
    ax.set_yticklabels([theme.pitch_name(t) for t in usage.index])
    ax.set_xlabel("Count (balls-strikes)")
    ax.set_title("Usage % by count (columns sum to 100)", fontweight="bold")
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            if mat[i, j] > 0.5:
                ax.text(j, i, f"{mat[i, j]:.0f}", ha="center", va="center",
                        fontsize=8, color="#111" if mat[i, j] > 30 else "#e0e0e0")
    fig.colorbar(im, ax=ax, shrink=0.85, label="usage %")

    ax = fig.add_subplot(gs[1, 0])
    st = metrics.performance_by_count_state(ctx)
    if st.empty:
        note(ax, "No data")
    else:
        rows = [[
            r["state"].replace("_", " "), f"{r['n']:,}",
            metrics.fmt_pct(r["usage_pct"]),
            metrics.fmt_pct(r["zone_pct"]),
            metrics.fmt_pct(r["swing_pct"]),
            metrics.fmt_pct(r["whiff_pct"]),
            metrics.fmt_pct(r["chase_pct"]),
            metrics.fmt_pct(r["csw_pct"]),
            metrics.fmt_pct(r["terminal_pct"]),
            metrics.fmt_pct(r["k_share"]),
        ] for _, r in st.iterrows()]
        styled_table(ax, rows,
                     ["Count state", "Pitches", "Share", "Zone%", "Swing%",
                      "Whiff%", "Chase%", "CSW%", "Ends PA%", "K% of PA"],
                     fontsize=10.5)
        ax.set_title("How each count state plays", fontweight="bold", pad=10)
    return save(fig, ctx, "12_count_usage.png")


def plate_discipline(ctx):
    """The full Statcast-style table plus the two charts worth having."""
    df = metrics.plate_discipline(ctx)
    if df.empty:
        return empty_figure(ctx, "13_plate_discipline.png",
                            "Plate Discipline & Rate Stats")

    fig = plt.figure(figsize=(17, 10))
    figure_title(fig, "Plate Discipline & Rate Stats", ctx, y=0.985)
    gs = GridSpec(2, 2, figure=fig, height_ratios=[1.3, 1.0], hspace=0.34,
                  wspace=0.24)

    ax = fig.add_subplot(gs[0, :])
    rows = [[
        r["display"], r["pa"], r["pitches"], metrics.fmt_num(r["p_per_pa"]),
        metrics.fmt_pct(100 * r["k_pct"]), metrics.fmt_pct(100 * r["bb_pct"]),
        metrics.fmt_pct(100 * r["k_minus_bb_pct"]),
        metrics.fmt_num(r["k_per_bb"]),
        metrics.fmt_pct(100 * r["csw_pct"]), metrics.fmt_pct(100 * r["whiff_pct"]),
        metrics.fmt_pct(100 * r["swing_pct"]), metrics.fmt_pct(100 * r["zone_pct"]),
        metrics.fmt_pct(100 * r["chase_pct"]),
        metrics.fmt_pct(100 * r["f_strike_pct"]),
        metrics.fmt_num(r["go_ao"]),
        metrics.fmt_avg(r["babip"]) if r["bip"] else "—",
        metrics.fmt_avg(r["woba"]),
    ] for _, r in df.iterrows()]
    cols = ["Pitcher", "TBF", "NP", "P/PA", "K%", "BB%", "K-BB%", "K/BB",
            "CSW%", "Whiff%", "Swing%", "Zone%", "Chase%", "F-Strike%",
            "GO/AO", "BABIP", "wOBA"]
    styled_table(ax, rows, cols, fontsize=9)
    ax.set_title("Per-Pitcher Summary", fontweight="bold", pad=10)

    ax = fig.add_subplot(gs[1, 0])
    short = [theme.pitcher_short(p) for p in df["pitcher"]]
    x = np.arange(len(short))
    width = 0.27
    for i, (col, label, color) in enumerate([
        ("csw_pct", "CSW%", "#e74c3c"),
        ("whiff_pct", "Whiff%", "#f39c12"),
        ("chase_pct", "Chase%", "#3498db"),
    ]):
        ax.bar(x + (i - 1) * width, 100 * df[col], width, label=label, color=color,
               edgecolor=theme.BG)
    ax.set_xticks(x)
    ax.set_xticklabels(short, rotation=20, fontsize=9)
    ax.set_ylabel("Percent")
    ax.set_title("Stuff & Discipline", fontweight="bold")
    ax.legend(fontsize=9, frameon=False)
    ax.grid(True, axis="y")

    ax = fig.add_subplot(gs[1, 1])
    for i, (_, r) in enumerate(df.iterrows()):
        ax.scatter(100 * r["bb_pct"], 100 * r["k_pct"], s=220,
                   c=theme.PITCHER_PALETTE[i % len(theme.PITCHER_PALETTE)],
                   edgecolors="white", linewidths=1.4, zorder=3)
        ax.annotate(theme.pitcher_short(r["pitcher"]),
                    (100 * r["bb_pct"], 100 * r["k_pct"]),
                    xytext=(9, 4), textcoords="offset points", fontsize=9)
    ax.axhline(theme.MLB_REFERENCE["k_pct"], color=theme.MUTED, linewidth=0.8,
               linestyle=":", alpha=0.7)
    ax.axvline(theme.MLB_REFERENCE["bb_pct"], color=theme.MUTED, linewidth=0.8,
               linestyle=":", alpha=0.7)
    ax.set_xlabel("BB%")
    ax.set_ylabel("K%")
    ax.set_title("K% vs BB% (upper-left = dominant; dotted = MLB average)",
                 fontweight="bold", fontsize=10.5)
    ax.grid(True)
    return save(fig, ctx, "13_plate_discipline.png")
