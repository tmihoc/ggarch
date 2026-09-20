"""Scaffold a .ggarch model fragment from a SQLite DDL.

The agent-authored-diagram workflow's "study the code" accelerator:
point it at a DDL file and it emits record nodes (fields with
pk/fk/nullable markers, ground pointers) and data edges (FK column ->
parent PK column, one per declared foreign key — the arrow is where
the pointer lives). The agent then curates: trims tables, names
relationships, builds views. The FK-completeness validator
(validator._fk_complete) checks the scaffold's correctness bar by
construction: every fk: field is the origin of exactly one data edge,
and every data edge originates at an fk: field.

Labels are deliberately absent: the FK->PK arrow's meaning is
structural, and a verb the generator cannot know would be a guess.
"""

from __future__ import annotations

import re
from pathlib import Path

_CREATE = re.compile(r"CREATE TABLE (\w+) \((.*?)\n\);", re.S)
_FK = re.compile(r"FOREIGN KEY\s*\((\w+)\)\s*REFERENCES\s+(\w+)\s*\((\w+)\)")
_SKIP = ("FOREIGN", "CONSTRAINT", "PRIMARY", "UNIQUE", "CHECK", "--")
_TYPES = {"INT": "int", "INTEGER": "int", "TEXT": "text", "BOOLEAN": "bool"}


def parse_ddl(text: str) -> dict[str, dict]:
    """{table: {columns: [(name, type, pk, nullable)], fks: [(col, ptable, pcol)]}}"""
    out: dict[str, dict] = {}
    for m in _CREATE.finditer(text):
        table, body = m.group(1), m.group(2)
        cols: list[tuple[str, str, bool, bool]] = []
        for line in body.splitlines():
            line = line.strip()
            if not line or line.startswith(_SKIP):
                continue
            cm = re.match(r"^(\w+)\s+([A-Z]+)", line)
            if not cm:
                continue
            name, ctype = cm.group(1), cm.group(2)
            pk = "PRIMARY KEY" in line
            nullable = "NOT NULL" not in line
            cols.append((name, _TYPES.get(ctype, ctype.lower()), pk, nullable))
        fks = [(fk.group(1), fk.group(2), fk.group(3))
               for fk in _FK.finditer(body)]
        out[table] = {"columns": cols, "fks": fks}
    return out


def scaffold(tables: dict[str, dict], db: str, only: set[str] | None = None) -> str:
    """Render the .ggarch fragment: nodes, then data edges.

    `only` names root tables; the TRANSITIVE FK-parent closure is
    auto-included — pruning a referenced parent would hide the pointer
    (the fk: field would originate 0 data edges, which the
    FK-completeness validator forbids). Curation happens after
    scaffolding, by the agent, with the validator watching.
    """
    if only is not None:
        closure: set[str] = set()
        queue = [t for t in only if t in tables]
        missing = {t for t in only if t not in tables}
        if missing:
            raise SystemExit(f"tables not in DDL: {sorted(missing)}")
        while queue:
            t = queue.pop()
            if t in closure:
                continue
            closure.add(t)
            queue.extend(p for _, p, _ in tables[t]["fks"]
                         if p in tables and p not in closure)
        names = sorted(closure)
    else:
        names = sorted(tables)

    lines: list[str] = []
    lines.append('model "Schema" {\n')
    lines.append("\n  nodes {\n")
    for t in names:
        info = tables[t]
        lines.append(f'    {t} [type: record, label: "{t}",\n'
                     f'                 ground: "{db}:{t}"] {{\n')
        lines.append("      fields {\n")
        for name, ctype, pk, nullable in info["columns"]:
            marks = []
            if pk:
                marks.append("pk: true")
            if name in {f[0] for f in info["fks"]}:
                marks.append("fk: true")
            if nullable:
                marks.append("null: true")
            tail = (", " + ", ".join(marks)) if marks else ""
            lines.append(f'        {name} [label: "{name}", '
                         f'type: "{ctype}"{tail}]\n')
        lines.append("      }\n")
        lines.append("    }\n\n")
    lines.append("  }\n\n  edges {\n")
    for t in names:
        for col, ptable, pcol in tables[t]["fks"]:
            lines.append(f"    {t}.{col} -> {ptable}.{pcol} [type: data]\n")
    lines.append("  }\n\n  style { extends: juju }\n\n}\n")
    return "".join(lines)


def scaffold_file(ddl: Path, db: str, only: set[str] | None = None) -> str:
    return scaffold(parse_ddl(ddl.read_text()), db, only)
