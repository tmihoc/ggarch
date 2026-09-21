#!/usr/bin/env python3
"""Floor vs ELK, side by side — the on-demand oracle comparison.

ADR-006 amendment (2026-09-21): solve() no longer auto-selects ELK —
the floor serves every view and the typed hub planes are synthesis
machinery an ELK build cannot express. ELK stays consultable as a
PARALLEL build: this script renders every view of a model file twice
(floor | ELK) into one HTML sheet, so the oracle's choices can still
teach (where the floor matches, where it doesn't, what a pure layering
engine would have done with the same select).

Views out of ELK's v1 scope (nested containers) render floor-only with
a note.

Usage: python3 scripts/elk-compare.py model.ggarch [--only NAME] [--out FILE]
Requires node + the elkjs bundle (GGARCH_ELK_BUNDLE or ./node_modules).
"""
import argparse
import sys
from pathlib import Path

from ggarch import parse, validate, solve, route, render
from ggarch import elk


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("model", help=".ggarch file")
    ap.add_argument("--only", default="", help="render only views whose "
                    "name contains this substring")
    ap.add_argument("--out", default="elk-compare.html")
    args = ap.parse_args()

    if not elk.available():
        print("elk-compare: node + the elkjs bundle required "
              "(GGARCH_ELK_BUNDLE or ./node_modules)", file=sys.stderr)
        return 1

    f = parse(Path(args.model).read_text(encoding="utf-8"))
    validate(f)
    parts = ["<!doctype html><meta charset='utf-8'>",
             "<title>Floor vs ELK — %s</title>" % Path(args.model).name,
             "<style>body{font-family:sans-serif;max-width:1900px;"
             "margin:1rem auto}h2{margin:1.4rem 0 .3rem}"
             "p{color:#555;margin:.2rem 0 .5rem}"
             ".row{display:flex;gap:16px;align-items:flex-start}"
             ".row>div{flex:1;min-width:0}h3{font-weight:600;"
             "font-size:14px;margin:.2rem 0}svg{max-width:100%;"
             "height:auto}</style>"]
    for d in f.diagrams:
        if args.only and args.only not in d.name:
            continue
        m = f.get_model(d.model_name)
        if getattr(d, "sequences", None) or not hasattr(d, "select"):
            continue  # sequence/state views: ELK's scope is topology
        floor = render(route(solve(d, m), m, d.select), m, d)
        elk_layout = elk.solve_view(d, m, d.select)
        if elk_layout is None:
            parts.append(f"<h2>{d.name}</h2><p>ELK: out of scope "
                         "(nested containers) — floor only.</p>")
            parts.append(f"<div>{floor}</div>")
            continue
        elk_svg = render(route(elk_layout, m, d.select), m, d)
        parts.append(f"<h2>{d.name}</h2>")
        parts.append("<p>left: the floor (typed hub planes, two-sided "
                     "fans, port closure) — right: ELK Layered on the "
                     "same select.</p>")
        parts.append(f"<div class='row'><div><h3>floor</h3>"
                     f"{floor}</div><div><h3>ELK Layered</h3>"
                     f"{elk_svg}</div></div>")
    Path(args.out).write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
