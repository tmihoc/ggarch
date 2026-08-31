"""ggarch CLI — parse, validate, and solve .ggarch files."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from ggarch.errors import GgarchError
from ggarch.parser import parse
from ggarch.validator import validate


def main() -> None:
    import argparse
    p = argparse.ArgumentParser(description="ggarch diagram tool")
    sub = p.add_subparsers(dest="cmd")

    check = sub.add_parser("check", help="parse and validate a .ggarch file")
    check.add_argument("file", type=Path)

    dump = sub.add_parser("dump", help="parse and dump the model as JSON")
    dump.add_argument("file", type=Path)

    solve_cmd = sub.add_parser("solve", help="solve layout and print node geometry")
    solve_cmd.add_argument("file", type=Path)
    solve_cmd.add_argument("--view", help="diagram view name (default: first)")

    args = p.parse_args()
    if args.cmd is None:
        p.print_help()
        sys.exit(0)

    source = args.file.read_text(encoding="utf-8")
    try:
        f = parse(source)
        validate(f)
    except GgarchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.cmd == "check":
        models = len(f.models)
        diagrams = len(f.diagrams)
        sequences = len(f.sequences)
        print(
            f"OK — {models} model(s), {diagrams} diagram view(s), {sequences} sequence view(s)"
        )

    elif args.cmd == "dump":
        import dataclasses
        def _default(o):
            if dataclasses.is_dataclass(o):
                return dataclasses.asdict(o)
            if hasattr(o, "value"):
                return o.value
            return str(o)
        print(json.dumps(dataclasses.asdict(f), default=_default, indent=2))

    elif args.cmd == "solve":
        from ggarch.solver import solve
        import dataclasses
        if not f.diagrams:
            print("error: no diagram views in file", file=sys.stderr)
            sys.exit(1)
        if args.view:
            diagram = next((d for d in f.diagrams if d.name == args.view), None)
            if diagram is None:
                names = [d.name for d in f.diagrams]
                print(f"error: view {args.view!r} not found; available: {names}",
                      file=sys.stderr)
                sys.exit(1)
        else:
            diagram = f.diagrams[0]
        model = f.get_model(diagram.model_name)
        try:
            layout = solve(diagram, model)
        except GgarchError as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(1)
        def _fmt_node(n, indent=0):
            pad = "  " * indent
            r = n.rect
            print(f"{pad}{n.id}: x={r.x:.0f} y={r.y:.0f} w={r.w:.0f} h={r.h:.0f}")
            for child in n.children:
                _fmt_node(child, indent + 1)
        print(f"view: {diagram.name!r}")
        print(f"bounds: {layout.bounds.w:.0f} x {layout.bounds.h:.0f}")
        for node in layout.nodes:
            _fmt_node(node)
