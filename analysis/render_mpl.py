"""Matplotlib helpers shared by every figure.

Anything that used to be copy-pasted into each figure function — table styling,
strike-zone overlays, empty-state panels, saving — lives here so a fix lands
everywhere at once.
"""

import os

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.patches as patches  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from . import theme  # noqa: E402

theme.apply_mpl_style()


def save(fig, ctx, filename, tight=True):
    path = os.path.join(ctx.ensure_out_dir(), filename)
    if tight:
        fig.savefig(path, dpi=150, bbox_inches="tight")
    else:
        fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def figure_title(fig, title, ctx, y=0.99):
    fig.suptitle(f"{title}\n{ctx.label}", fontsize=15, fontweight="bold", y=y)


def empty_figure(ctx, filename, title, reason=None):
    """Placeholder so a missing slice doesn't silently drop a report section."""
    fig, ax = plt.subplots(figsize=(10, 4.5))
    fig.suptitle(f"{title}\n{ctx.label}", fontsize=14, fontweight="bold")
    ax.text(0.5, 0.5, reason or f"No data matches the active filter:\n{ctx.label}",
            ha="center", va="center", fontsize=13, color=theme.MUTED)
    ax.axis("off")
    return save(fig, ctx, filename)


def note(ax, text):
    ax.text(0.5, 0.5, text, ha="center", va="center", transform=ax.transAxes,
            fontsize=11, color=theme.MUTED, wrap=True)
    ax.axis("off")


def styled_table(ax, rows, columns, col_widths=None, fontsize=9, header_bg=None,
                 cell_colors=None, cell_text_colors=None):
    """Render a table sized to its axes, with columns wide enough for their text.

    Two fixes over the old inline tables: matplotlib does not size columns to
    their contents (hence "Yoshinobu Yama" and "Jacob deGr"), and a scaled
    table overflows its axes so the axes title lands on top of the header row.
    Measuring the widest string per column fixes the first; drawing into
    bbox=[0,0,1,1] pins the table to its axes and fixes the second.
    """
    ax.axis("off")
    if not rows:
        note(ax, "No rows")
        return None

    text_rows = [[("" if v is None else str(v)) for v in r] for r in rows]

    if col_widths is None:
        widths = []
        for j, col in enumerate(columns):
            longest = max([len(str(col))] + [len(r[j]) for r in text_rows])
            # +1.5 chars of padding keeps text off the cell border.
            widths.append(longest + 1.5)
        total = float(sum(widths)) or 1.0
        col_widths = [w / total for w in widths]

    table = ax.table(cellText=text_rows, colLabels=list(columns),
                     colWidths=col_widths, cellLoc="center", bbox=[0, 0, 1, 1])
    table.auto_set_font_size(False)
    table.set_fontsize(fontsize)

    for (r, c), cell in table.get_celld().items():
        cell.set_edgecolor(theme.GRID)
        if r == 0:
            cell.set_facecolor(header_bg or theme.HEADER_BG)
            cell.set_text_props(fontweight="bold", color="#ffffff")
        else:
            fill = None
            if cell_colors is not None:
                fill = cell_colors.get((r - 1, c))
            cell.set_facecolor(fill or theme.PANEL)
            fg = theme.FG
            if cell_text_colors is not None and (r - 1, c) in cell_text_colors:
                fg = cell_text_colors[(r - 1, c)]
            elif fill:
                fg = theme.text_color_for(fill)
            cell.set_text_props(color=fg)
    return table


def draw_strike_zone(ax, linestyle="--", color="#ffffff", linewidth=2, alpha=1.0):
    rect = patches.Rectangle(
        (-theme.SZ_X_HALF, theme.SZ_Z_MIN),
        theme.SZ_X_HALF * 2, theme.SZ_Z_MAX - theme.SZ_Z_MIN,
        linewidth=linewidth, edgecolor=color, facecolor="none",
        linestyle=linestyle, alpha=alpha, zorder=6)
    ax.add_patch(rect)
    return rect


def draw_zone_grid(ax, values, counts, cmap=None, vmin=None, vmax=None,
                   fmt="{:.0f}%", show_counts=True, na_color="#20283d"):
    """Draw a 5x5 zone grid produced by metrics.zone_grid()."""
    from . import metrics

    cmap = plt.get_cmap(cmap or theme.HEAT_CMAP)
    finite = values[np.isfinite(values)]
    if vmin is None:
        vmin = float(finite.min()) if finite.size else 0.0
    if vmax is None:
        vmax = float(finite.max()) if finite.size else 1.0
    if vmax - vmin < 1e-9:
        vmax = vmin + 1.0

    xe, ze = metrics.ZONE_X_EDGES, metrics.ZONE_Z_EDGES
    for row in range(5):
        for col in range(5):
            v = values[row, col]
            x0, x1 = xe[col], xe[col + 1]
            # Row 0 is the top of the zone; z edges run bottom-up.
            z0, z1 = ze[4 - row], ze[5 - row]
            if np.isnan(v):
                face = na_color
                label = "·"
            else:
                face = cmap((v - vmin) / (vmax - vmin))
                label = fmt.format(v)
            ax.add_patch(patches.Rectangle(
                (x0, z0), x1 - x0, z1 - z0, facecolor=face,
                edgecolor=theme.BG, linewidth=1.0))
            if not np.isnan(v):
                rgba = face if isinstance(face, str) else matplotlib.colors.to_hex(face)
                txt = theme.text_color_for(rgba)
                ax.text((x0 + x1) / 2, (z0 + z1) / 2 + (0.06 if show_counts else 0),
                        label, ha="center", va="center", fontsize=8.5,
                        fontweight="bold", color=txt)
                if show_counts:
                    ax.text((x0 + x1) / 2, (z0 + z1) / 2 - 0.16,
                            f"n={counts[row, col]}", ha="center", va="center",
                            fontsize=6, color=txt, alpha=0.75)

    draw_strike_zone(ax, linewidth=1.8, alpha=0.85)
    ax.set_xlim(xe[0] - 0.08, xe[-1] + 0.08)
    ax.set_ylim(ze[0] - 0.08, ze[-1] + 0.08)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)


def pitch_legend_handles(pitch_types):
    from matplotlib.lines import Line2D
    return [Line2D([0], [0], color=theme.pitch_color(pt), linewidth=3,
                   label=theme.pitch_name(pt)) for pt in pitch_types]


def bar_labels(ax, values, fmt="{:.0f}%", offset=1.0, fontsize=8.5, horizontal=True):
    for i, v in enumerate(values):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            continue
        if horizontal:
            ax.text(v + offset, i, fmt.format(v), va="center", fontsize=fontsize)
        else:
            ax.text(i, v + offset, fmt.format(v), ha="center", fontsize=fontsize)


def diverging_colors(values, vmax=None):
    """Map values to the diverging ramp, centred on zero."""
    arr = np.asarray(values, dtype=float)
    if vmax is None:
        finite = arr[np.isfinite(arr)]
        vmax = float(np.abs(finite).max()) if finite.size else 1.0
    vmax = vmax or 1.0
    cmap = plt.get_cmap(theme.DIVERGING_CMAP)
    return [cmap(0.5 + 0.5 * float(np.clip(v / vmax, -1, 1))) if np.isfinite(v)
            else theme.PANEL for v in arr]
