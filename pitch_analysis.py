#!/usr/bin/env python3
"""
StrikeFactor pitch analysis.

Renders figures (and a combined report.html) from the SQLite pitch log, or
prints the same numbers as tables in the terminal.

Usage:
    python pitch_analysis.py                              # figures + report.html
    python pitch_analysis.py --terminal                   # tables in the terminal
    python pitch_analysis.py --terminal --figures         # both
    python pitch_analysis.py --mode all --difficulty all  # every pitch on record
    python pitch_analysis.py --pitcher degrom --terminal
    python pitch_analysis.py --sections arsenal,sequencing
    python pitch_analysis.py --list                       # show figures/sections

Implementation lives in the analysis/ package; this file is the CLI.
"""

import argparse
import sys
import time

from analysis import data, figures as fig_registry, filters, report


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="StrikeFactor pitch analysis (filterable, figures or terminal).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Sections: " + ", ".join(fig_registry.SECTIONS))
    filters.add_filter_args(p)
    p.add_argument("--terminal", "-t", action="store_true",
                   help="Print tables to the terminal. Skips figure rendering "
                        "unless --figures is also passed.")
    p.add_argument("--figures", action="store_true",
                   help="Render figures even when --terminal is set.")
    p.add_argument("--sections", default=None,
                   help="Comma-separated subset of sections to render "
                        "(default: all).")
    p.add_argument("--only", default=None,
                   help="Comma-separated figure keys to render (see --list).")
    p.add_argument("--out", default=None,
                   help="Output directory root (default: analysis_output/).")
    p.add_argument("--db", default=None, help="Path to strikefactor.db.")
    p.add_argument("--no-report", action="store_true",
                   help="Skip writing report.html.")
    p.add_argument("--width", type=int, default=None,
                   help="Terminal render width (default: terminal width, "
                        "floored so wide tables aren't truncated).")
    p.add_argument("--list", action="store_true",
                   help="List available figures and sections, then exit.")
    return p.parse_args(argv)


def _list_figures():
    print("Sections:")
    for s in fig_registry.SECTIONS:
        print(f"  {s:<12} {fig_registry.SECTION_TITLES[s]}")
    print("\nFigures:")
    for f in fig_registry.FIGURES:
        print(f"  {f.key:<12} {f.section:<12} {f.filename:<26} {f.title}")


def _split(value):
    return [x.strip() for x in value.split(",") if x.strip()] if value else None


def main(argv=None):
    args = parse_args(argv)
    if args.list:
        _list_figures()
        return 0

    sections = _split(args.sections)
    if sections:
        unknown = [s for s in sections if s not in fig_registry.SECTIONS]
        if unknown:
            print(f"Unknown section(s): {', '.join(unknown)}", file=sys.stderr)
            print(f"Valid sections: {', '.join(fig_registry.SECTIONS)}",
                  file=sys.stderr)
            return 2

    filt = filters.filter_from_args(args)
    try:
        ctx = data.Context(filt, out_dir=args.out, db_path=args.db)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1

    if ctx.empty:
        print(f"No pitches match the active filter: {ctx.label}")
        print("Try --mode all --difficulty all to widen the slice.")
        return 1

    render_figures = args.figures or not args.terminal

    if args.terminal:
        from analysis import render_term
        render_term.render(ctx, sections=sections, width=args.width)

    if not render_figures:
        return 0

    selected = fig_registry.select(sections=sections, keys=_split(args.only))
    if not selected:
        print("Nothing to render for the requested sections/figures.",
              file=sys.stderr)
        return 2

    if not args.terminal:
        print(f"Generating StrikeFactor pitch analysis ({ctx.label})...")
        if not filt.is_empty:
            print("  (filtered view — pass --mode all --difficulty all "
                  "--handedness all to include every pitch)")

    rendered = []
    for i, figure in enumerate(selected, 1):
        started = time.perf_counter()
        try:
            figure.render(ctx)
        except Exception as exc:  # keep going; one bad slice shouldn't kill the run
            print(f"  [{i}/{len(selected)}] {figure.title} — FAILED: "
                  f"{type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        rendered.append(figure)
        print(f"  [{i}/{len(selected)}] {figure.title} "
              f"({time.perf_counter() - started:.1f}s)")

    print(f"\nFigures saved to {ctx.out_dir}/")
    if not args.no_report and rendered:
        path = report.write(ctx, rendered)
        print(f"Combined report: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
