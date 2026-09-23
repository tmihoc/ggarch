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

    scaffold_cmd = sub.add_parser(
        "scaffold", help="generate a .ggarch fragment from a SQLite DDL")
    scaffold_cmd.add_argument("ddl", type=Path, help="the .ddl file")
    scaffold_cmd.add_argument("--db", default="schema",
                              help="db label for ground pointers")
    scaffold_cmd.add_argument("--tables", default="",
                              help="comma-separated table subset (default: all)")

    dump = sub.add_parser("dump", help="parse and dump the model as JSON")
    dump.add_argument("file", type=Path)

    solve_cmd = sub.add_parser("solve", help="solve layout and print node geometry")
    solve_cmd.add_argument("file", type=Path)
    solve_cmd.add_argument("--view", help="diagram view name (default: first)")

    route_cmd = sub.add_parser("route", help="solve layout and print routed edges")
    route_cmd.add_argument("file", type=Path)
    route_cmd.add_argument("--view", help="diagram view name (default: first)")

    render_cmd = sub.add_parser("render", help="render diagram to SVG file(s)")
    render_cmd.add_argument("file", type=Path)
    render_cmd.add_argument("--view", help="diagram view name (default: first)")
    render_cmd.add_argument("--out", type=Path, default=None,
                            help="output path stem (default: <file>-<view>)")
    render_cmd.add_argument("--dark", action="store_true",
                            help="render dark mode only")
    render_cmd.add_argument("--light", action="store_true",
                            help="render light mode only (default: both)")

    seq_cmd = sub.add_parser("render-seq", help="render sequence view to SVG file(s)")
    seq_cmd.add_argument("file", type=Path)
    seq_cmd.add_argument("--view", help="sequence view name (default: first)")
    seq_cmd.add_argument("--out", type=Path, default=None,
                         help="output path stem")
    seq_cmd.add_argument("--dark", action="store_true")
    seq_cmd.add_argument("--light", action="store_true")

    args = p.parse_args()
    if args.cmd is None:
        p.print_help()
        sys.exit(0)

    if args.cmd == "scaffold":
        from ggarch.scaffold import scaffold_file
        only = ({t.strip() for t in args.tables.split(",") if t.strip()}
                or None)
        sys.stdout.write(scaffold_file(args.ddl, args.db, only))
        return

    source = args.file.read_text(encoding="utf-8")
    try:
        f = parse(source)
        validate(f, check_orphans=True, check_labels=True)
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

    elif args.cmd == "route":
        from ggarch.solver import solve
        from ggarch.router import route
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
            rl = route(layout, model, diagram.select)
        except GgarchError as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"view: {diagram.name!r}")
        print(f"edges: {len(rl.edges)}")
        for e in rl.edges:
            pts = "  ".join(f"({p.x:.0f},{p.y:.0f})" for p in e.points)
            print(f"  {e.source_id} -> {e.target_id} [{e.edge_type}/{e.style}]"
                  f"  {pts}"
                  + (f'  "{e.label}"' if e.label else ""))

    elif args.cmd == "render":
        from ggarch.solver import solve
        from ggarch.router import route
        from ggarch.renderer import render
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
        # Build output path stem.
        if args.out:
            stem = args.out
        else:
            view_slug = diagram.name.lower().replace(" ", "-")
            stem = args.file.parent / f"{args.file.stem}-{view_slug}"
        try:
            layout = solve(diagram, model)
            rl = route(layout, model, diagram.select)
        except GgarchError as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(1)
        both = not args.dark and not args.light
        if both or args.light:
            light_path = Path(str(stem) + "-light.svg")
            light_path.write_text(render(rl, model, diagram, dark=False), encoding="utf-8")
            print(f"wrote {light_path}")
        if both or args.dark:
            dark_path = Path(str(stem) + "-dark.svg")
            dark_path.write_text(render(rl, model, diagram, dark=True), encoding="utf-8")
            print(f"wrote {dark_path}")

    elif args.cmd == "render-seq":
        from ggarch.sequence_renderer import render_sequence
        if not f.sequences:
            print("error: no sequence views in file", file=sys.stderr)
            sys.exit(1)
        if args.view:
            seq = next((s for s in f.sequences if s.name == args.view), None)
            if seq is None:
                names = [s.name for s in f.sequences]
                print(f"error: view {args.view!r} not found; available: {names}",
                      file=sys.stderr)
                sys.exit(1)
        else:
            seq = f.sequences[0]
        model = f.get_model(seq.model_name)
        if args.out:
            stem = args.out
        else:
            view_slug = seq.name.lower().replace(" ", "-")
            stem = args.file.parent / f"{args.file.stem}-{view_slug}"
        try:
            both = not args.dark and not args.light
            if both or args.light:
                light_path = Path(str(stem) + "-light.svg")
                light_path.write_text(
                    render_sequence(seq, model, dark=False), encoding="utf-8"
                )
                print(f"wrote {light_path}")
            if both or args.dark:
                dark_path = Path(str(stem) + "-dark.svg")
                dark_path.write_text(
                    render_sequence(seq, model, dark=True), encoding="utf-8"
                )
                print(f"wrote {dark_path}")
        except (GgarchError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(1)
