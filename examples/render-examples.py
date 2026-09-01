#!/usr/bin/env python3
"""Render all .ggarch examples to SVG pairs (light + dark).

Run from the ggarch repo root:
    python examples/render-examples.py

Produces <name>-light.svg and <name>-dark.svg next to each .ggarch file.
Every view in every file is rendered; file names are derived from the
view/sequence name.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT.parent / "src"))

from ggarch import parse, validate, solve, route, render
from ggarch.sequence_renderer import render_sequence


def slug(name: str) -> str:
    return name.lower().replace(" ", "-").replace("/", "-")


def render_file(src_path: pathlib.Path) -> list[str]:
    """Render all views in src_path; return list of written filenames."""
    src = src_path.read_text(encoding="utf-8")
    f = parse(src)
    validate(f)
    written = []

    for d in f.diagrams:
        m = f.get_model(d.model_name)
        layout = solve(d, m)
        routed = route(layout, m, d.select)
        for suffix, dark in (("light", False), ("dark", True)):
            svg = render(routed, m, d, dark=dark)
            out = src_path.with_name(f"{slug(d.name)}-{suffix}.svg")
            out.write_text(svg, encoding="utf-8")
            written.append(out.name)

    for s in f.sequences:
        m = f.get_model(s.model_name)
        for suffix, dark in (("light", False), ("dark", True)):
            svg = render_sequence(s, m, dark=dark)
            out = src_path.with_name(f"{slug(s.name)}-{suffix}.svg")
            out.write_text(svg, encoding="utf-8")
            written.append(out.name)

    return written


def main() -> None:
    examples = sorted(ROOT.glob("*.ggarch"))
    if not examples:
        print("No .ggarch files found in", ROOT)
        sys.exit(1)

    total = 0
    errors = 0
    for src in examples:
        try:
            written = render_file(src)
            for name in written:
                print(f"  {name}")
            total += len(written)
        except Exception as exc:
            print(f"ERROR {src.name}: {exc}", file=sys.stderr)
            errors += 1

    print(f"\n{total} SVG(s) written from {len(examples)} source(s)", end="")
    if errors:
        print(f"  ({errors} error(s))", file=sys.stderr)
        sys.exit(1)
    else:
        print()


if __name__ == "__main__":
    main()
