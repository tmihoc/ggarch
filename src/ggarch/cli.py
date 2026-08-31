"""ggarch CLI — parse and validate .ggarch files."""
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
